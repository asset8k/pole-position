"""Prepare and activate immutable regulation versions without deleting history."""

import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pymupdf
from openai import OpenAI
from qdrant_client import QdrantClient, models

from pole_position.corpus.schemas import CorpusManifest, RegulationDocument
from pole_position.corpus.verification import calculate_sha256
from pole_position.rag.contracts import ChunkedDocument, ParsedDocument, RetrievalChunk
from pole_position.rag.indexing.embeddings import (
    EMBEDDING_MODEL,
    embed_texts,
    format_chunk_for_embedding,
)
from pole_position.rag.indexing.qdrant_store import (
    DENSE_VECTOR_NAME,
    point_from_chunk,
)
from pole_position.rag.ingestion.appendix_chunker import (
    CURRENT_APPENDIX_IDS,
    FUTURE_YEAR_APPENDIX_IDS,
    VISUAL_ONLY_APPENDIX_IDS,
    chunk_appendices,
)
from pole_position.rag.ingestion.clause_chunker import (
    DEFAULT_MAX_CHARACTERS,
    chunk_clauses,
)
from pole_position.rag.ingestion.clause_parser import (
    get_clause_identifier,
    looks_like_table_reference,
    parse_clauses,
)
from pole_position.rag.ingestion.normalizer import normalize_document
from pole_position.rag.ingestion.pdf_extractor import extract_pdf
from pole_position.rag.ingestion.preamble_chunker import chunk_preamble
from pole_position.rag.ingestion.structure_parser import get_heading, parse_document
from pole_position.rag.retrieval.sparse import load_sparse_corpus

# This updater deliberately uses the application's existing embedding model.
VECTOR_SIZE = 1536


@dataclass(frozen=True)
class PreparedUpdate:
    previous: RegulationDocument
    document: RegulationDocument
    chunked: ChunkedDocument
    summary: dict[str, object]


def atomic_write(path: Path, content: str) -> None:
    """Never expose half-written JSON to another process."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def read_pdf_document(
    path: Path,
    manifest: CorpusManifest,
    *,
    allow_same_issue: bool = False,
) -> RegulationDocument:
    """Read the FIA cover, not a filename or the website's upload date."""
    with pymupdf.open(path) as pdf:
        if not pdf.is_pdf or pdf.needs_pass or not pdf.page_count:
            raise ValueError(f"Not an unencrypted, readable PDF: {path.name}")
        cover = " ".join(pdf[0].get_text("text").split())
        pages = pdf.page_count

    def capture(pattern: str, label: str) -> str:
        match = re.search(pattern, cover, re.IGNORECASE)
        if match is None:
            raise ValueError(f"Cannot identify {label} on FIA cover: {path.name}")
        return match.group(1)

    section = capture(r"SECTION\s+([A-F]):", "section").upper()
    season = int(
        capture(
            r"\b(20\d{2})\s+(?:Formula\s+(?:1|One)|F1)(?=\s+Regulations\b|:)",
            "season",
        )
    )
    issue = int(capture(r"\bVersion:\s*Issue\s+(\d+)\b", "issue"))
    if capture(r"\bStatus:\s*(\w+)\b", "status").upper() != "PUBLISHED":
        raise ValueError("Only PUBLISHED regulations can be activated")
    published = date.fromisoformat(
        "-".join(
            reversed(
                capture(r"\bDate:\s*(\d{2}/\d{2}/\d{4})", "publication date").split("/")
            )
        )
    )
    approved = date.fromisoformat(
        "-".join(
            reversed(
                capture(
                    r"WMSC\s+approval\s+date:\s*(\d{2}/\d{2}/\d{4})", "approval date"
                ).split("/")
            )
        )
    )
    if approved > published:
        raise ValueError("WMSC approval cannot be later than the publication date")
    previous = next(
        (doc for doc in manifest.documents if doc.is_active and doc.section == section),
        None,
    )
    if previous is None or season != previous.season:
        raise ValueError(
            f"Wrong season or inactive section: {season} Section {section}"
        )
    sha256 = calculate_sha256(path)
    if sha256 == previous.sha256:
        return previous
    if issue < previous.issue_number or published < previous.published_date:
        raise ValueError(f"Refusing older regulations for Section {section}")
    if issue == previous.issue_number and not allow_same_issue:
        raise ValueError(
            f"Section {section} has changed bytes but the same issue number; "
            "review the PDF and use --allow-same-issue only for an official correction"
        )
    # The hash also disambiguates official corrections with the same issue number.
    document_id = (
        f"fia-f1-{season}-section-{section.lower()}-issue-{issue:02d}-sha-{sha256[:12]}"
    )
    return RegulationDocument(
        document_id=document_id,
        section=previous.section,
        title=previous.title,
        season=season,
        issue_number=issue,
        published_date=published,
        wmsc_approval_date=approved,
        sha256=sha256,
        page_count=pages,
        is_active=True,
        source_path=f"regulations/versions/{document_id}.pdf",
    )


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def validate_prepared_content(
    document: RegulationDocument,
    parsed: ParsedDocument,
    chunked: ChunkedDocument,
    clause_ids: list[str],
) -> None:
    """Fail closed on unsupported structure, missing clauses or lost chunk text."""
    if not clause_ids or len(clause_ids) != len(set(clause_ids)):
        raise ValueError("No clauses parsed, or duplicate clause identifiers")
    unit_ids = [(unit.kind, unit.identifier) for unit in parsed.units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("Duplicate parsed article/appendix units")
    expected_clauses: set[str] = set()
    for unit in parsed.units:
        if unit.kind != "article":
            continue
        # Cross-check source headings rather than accepting a plausible count.
        for segment in unit.page_segments:
            lines = segment.text.splitlines()
            for index, line in enumerate(lines):
                identifier = get_clause_identifier(line)
                if (
                    identifier
                    and unit.identifier
                    and identifier.startswith(f"{unit.identifier}.")
                ):
                    if not looks_like_table_reference(lines, index):
                        expected_clauses.add(identifier)
    if expected_clauses != set(clause_ids):
        raise ValueError("Article headings and parsed clauses disagree")
    counts = Counter(chunk.chunk_id for chunk in chunked.chunks)
    if not counts or any(count != 1 for count in counts.values()):
        raise ValueError("Chunks must be nonempty with unique IDs")
    if {
        chunk.clause_identifier
        for chunk in chunked.chunks
        if chunk.source_kind == "clause"
    } != set(clause_ids):
        raise ValueError("Parsed clause and chunk coverage disagree")
    indexed_appendices = {
        unit.identifier
        for unit in parsed.units
        if unit.kind == "appendix" and unit.identifier in CURRENT_APPENDIX_IDS
    }
    found_appendices = {
        chunk.appendix_identifier
        for chunk in chunked.chunks
        if chunk.source_kind == "appendix"
    }
    if indexed_appendices != found_appendices:
        raise ValueError("An applicable appendix is missing from chunks")
    for chunk in chunked.chunks:
        if (
            chunk.document_id != document.document_id
            or chunk.source_sha256 != document.sha256
            or chunk.section != document.section
            or not chunk.text.strip()
            or len(chunk.text) > DEFAULT_MAX_CHARACTERS
            or not 1
            <= chunk.start_pdf_page
            == chunk.end_pdf_page
            <= document.page_count
        ):
            raise ValueError(f"Invalid chunk provenance/size/page: {chunk.chunk_id}")
        if (
            chunk.appendix_identifier
            in FUTURE_YEAR_APPENDIX_IDS | VISUAL_ONLY_APPENDIX_IDS
        ):
            raise ValueError("Skipped appendix leaked into the search corpus")


def prepare_update(
    path: Path,
    previous: RegulationDocument,
    document: RegulationDocument,
    root: Path,
) -> PreparedUpdate:
    destination = root / document.source_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if calculate_sha256(destination) != document.sha256:
            raise ValueError(f"Immutable PDF collision: {destination}")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".pdf-", dir=destination.parent)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "wb") as target, path.open("rb") as source:
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            if calculate_sha256(temporary_path) != document.sha256:
                raise ValueError("Input PDF changed during preparation")
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
    if calculate_sha256(destination) != document.sha256:
        raise ValueError("Input PDF changed during preparation")

    extracted = extract_pdf(document, root, exclude_struck_text=True)
    normalized = normalize_document(extracted)
    parsed = parse_document(normalized)
    clauses = parse_clauses(normalized)
    clause_chunks = chunk_clauses(clauses)
    appendix_chunks, future, visual = chunk_appendices(parsed, document.section)
    preamble_chunks = chunk_preamble(parsed, document.section)
    chunked = ChunkedDocument(
        document_id=document.document_id,
        source_sha256=document.sha256,
        chunks=[*clause_chunks.chunks, *appendix_chunks, *preamble_chunks],
    )
    validate_prepared_content(
        document,
        parsed,
        chunked,
        [clause.clause_identifier for clause in clauses.clauses],
    )
    # Every clause/appendix/preamble must survive splitting without lost text.
    grouped: dict[tuple[str, str | None, int], list[str]] = defaultdict(list)
    for chunk in chunked.chunks:
        key = (
            chunk.source_kind,
            chunk.clause_identifier or chunk.appendix_identifier,
            chunk.start_pdf_page,
        )
        grouped[key].append(chunk.text)
    for clause in clauses.clauses:
        for segment in clause.page_segments:
            key = ("clause", clause.clause_identifier, segment.pdf_page_number)
            if _collapsed(" ".join(grouped[key])) != _collapsed(segment.text):
                raise ValueError(
                    f"Clause text/pages lost while chunking: {clause.clause_identifier}"
                )
    for unit in parsed.units:
        if unit.kind == "preamble" or (
            unit.kind == "appendix" and unit.identifier in CURRENT_APPENDIX_IDS
        ):
            for segment in unit.page_segments:
                key = (unit.kind, unit.identifier, segment.pdf_page_number)
                if _collapsed(" ".join(grouped[key])) != _collapsed(segment.text):
                    raise ValueError(
                        f"Unit text/pages lost while chunking: {unit.identifier}"
                    )

    # Catch missing body articles/appendices, while allowing deliberate VOID articles.
    source_units = set()
    for page in normalized.pages:
        for line in page.text.splitlines():
            heading = get_heading(line)
            if heading and heading[0] in {"article", "appendix"}:
                kind, identifier, title = heading
                if not title.startswith("VOID"):
                    source_units.add((kind, identifier))
    actual_units = {(unit.kind, unit.identifier) for unit in parsed.units}
    if source_units - actual_units:
        raise ValueError(
            f"Missing document units: {sorted(source_units - actual_units)}"
        )

    for stage, artifact in (
        ("extracted", extracted),
        ("normalized", normalized),
        ("parsed", parsed),
        ("clauses", clauses),
        ("chunks", chunked),
    ):
        artifact_path = root / "artifacts" / stage / f"{document.document_id}.json"
        content = artifact.model_dump_json(indent=2)
        if (
            artifact_path.exists()
            and artifact_path.read_text(encoding="utf-8") != content
        ):
            raise ValueError(
                "Prepared artifacts changed for an existing version; review before applying"
            )
        atomic_write(artifact_path, content)

    return PreparedUpdate(
        previous,
        document,
        chunked,
        {
            "section": document.section,
            "document_id": document.document_id,
            "issue": document.issue_number,
            "pages": document.page_count,
            "units": len(parsed.units),
            "clauses": len(clauses.clauses),
            "chunks": len(chunked.chunks),
            "skipped_future": future,
            "skipped_visual": visual,
            "struck_out_text_excluded": True,
            "pages_without_text": [
                page.pdf_page_number
                for page in normalized.pages
                if not page.text.strip()
            ],
        },
    )


def replacement_manifest(
    manifest: CorpusManifest, updates: list[PreparedUpdate]
) -> CorpusManifest:
    replacements = {update.previous.document_id: update.document for update in updates}
    return CorpusManifest(
        documents=[replacements.get(doc.document_id, doc) for doc in manifest.documents]
    )


def _point_id(chunk_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"pole-position:{chunk_id}"))


def _expected_payload(
    chunk: RetrievalChunk, document: RegulationDocument
) -> dict[str, object]:
    payload = point_from_chunk(chunk, [1.0], document).payload or {}
    # Active membership is governed by the atomic manifest, not this display flag.
    payload.pop("is_active", None)
    return payload


def _embedding_fingerprint(chunk: RetrievalChunk, document: RegulationDocument) -> str:
    text = EMBEDDING_MODEL + "\n" + format_chunk_for_embedding(chunk, document.title)
    return sha256(text.encode("utf-8")).hexdigest()


def audit_document(
    client: QdrantClient,
    collection: str,
    document: RegulationDocument,
    chunked: ChunkedDocument,
    *,
    require_complete: bool = True,
    require_embedding_model: bool = False,
) -> set[str]:
    """Audit every payload and vector; optionally find already-staged chunks."""
    found: set[str] = set()
    for start in range(0, len(chunked.chunks), 100):
        chunks = chunked.chunks[start : start + 100]
        expected = {_point_id(chunk.chunk_id): chunk for chunk in chunks}
        records = client.retrieve(
            collection, ids=list(expected), with_payload=True, with_vectors=True
        )
        for record in records:
            chunk = expected[str(record.id)]
            payload = record.payload or {}
            if any(
                payload.get(key) != value
                for key, value in _expected_payload(chunk, document).items()
            ):
                raise ValueError(f"Stored payload mismatch: {chunk.chunk_id}")
            if (
                require_embedding_model
                and payload.get("embedding_model") != EMBEDDING_MODEL
            ):
                raise ValueError(f"Stored embedding model mismatch: {chunk.chunk_id}")
            if require_embedding_model and payload.get(
                "embedding_input_sha256"
            ) != _embedding_fingerprint(chunk, document):
                raise ValueError(f"Stored embedding input mismatch: {chunk.chunk_id}")
            vector = (
                record.vector.get(DENSE_VECTOR_NAME)
                if isinstance(record.vector, dict)
                else None
            )
            if (
                not isinstance(vector, list)
                or len(vector) != VECTOR_SIZE
                or any(not isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
            ):
                raise ValueError(f"Stored vector missing/invalid: {chunk.chunk_id}")
            found.add(chunk.chunk_id)
    count = client.count(
        collection,
        exact=True,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document.document_id),
                )
            ]
        ),
    ).count
    if count != len(found):
        raise ValueError(f"Unexpected points already exist for {document.document_id}")
    if require_complete and len(found) != len(chunked.chunks):
        raise ValueError(f"Incomplete stored document: {document.document_id}")
    return found


def stage_document(
    client: QdrantClient,
    openai_client: OpenAI,
    collection: str,
    update: PreparedUpdate,
) -> int:
    """Reuse verified staged points after failure; embed and upsert only missing ones."""
    found = audit_document(
        client,
        collection,
        update.document,
        update.chunked,
        require_complete=False,
        require_embedding_model=True,
    )
    missing = [chunk for chunk in update.chunked.chunks if chunk.chunk_id not in found]
    inactive = update.document.model_copy(update={"is_active": False})
    for start in range(0, len(missing), 100):
        chunks = missing[start : start + 100]
        vectors = embed_texts(
            openai_client,
            [format_chunk_for_embedding(chunk, inactive.title) for chunk in chunks],
        )
        if any(len(vector) != VECTOR_SIZE or not any(vector) for vector in vectors):
            raise ValueError(
                "Embedding dimensions do not match the existing dense collection"
            )
        points = [
            point_from_chunk(chunk, vector, inactive)
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        for point, chunk in zip(points, chunks, strict=True):
            assert point.payload is not None
            point.payload["embedding_model"] = EMBEDDING_MODEL
            point.payload["embedding_input_sha256"] = _embedding_fingerprint(
                chunk, inactive
            )
        client.upsert(collection_name=collection, points=points, wait=True)
    audit_document(
        client,
        collection,
        update.document,
        update.chunked,
        require_embedding_model=True,
    )
    return len(missing)


def activate_manifest(
    root: Path,
    manifest_path: Path,
    expected_text: str,
    proposed: CorpusManifest,
    client: QdrantClient,
    collection: str,
) -> list[str]:
    """Verify the entire proposed corpus, then commit the single activation pointer."""
    load_sparse_corpus(manifest_path, root / "artifacts/chunks", manifest=proposed)
    for document in proposed.documents:
        if not document.is_active:
            continue
        chunks = ChunkedDocument.model_validate_json(
            (root / "artifacts/chunks" / f"{document.document_id}.json").read_text(
                encoding="utf-8"
            )
        )
        audit_document(client, collection, document, chunks)
    if manifest_path.read_text(encoding="utf-8") != expected_text:
        raise ValueError("Manifest changed during update; refusing activation")
    atomic_write(manifest_path, proposed.model_dump_json(indent=2) + "\n")
    # Best-effort flags for the dashboard; manifest membership remains authoritative.
    previous = CorpusManifest.model_validate_json(expected_text)
    active_ids = {doc.document_id for doc in proposed.documents if doc.is_active}
    retired_ids = {
        doc.document_id for doc in previous.documents if doc.is_active
    } - active_ids
    warnings: list[str] = []
    for ids, active in ((active_ids, True), (retired_ids, False)):
        if ids:
            try:
                client.set_payload(
                    collection_name=collection,
                    payload={"is_active": active},
                    points=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id",
                                match=models.MatchAny(any=sorted(ids)),
                            )
                        ]
                    ),
                    wait=True,
                )
            except Exception as error:
                warnings.append(
                    f"Activated safely, but dashboard active flags need syncing ({type(error).__name__})"
                )
    return warnings


def prepare_batch(
    paths: list[Path],
    manifest: CorpusManifest,
    root: Path,
    *,
    allow_same_issue: bool = False,
) -> tuple[list[PreparedUpdate], list[str]]:
    """Validate ALL covers before preparing anything; one section per invocation input."""
    documents = [
        read_pdf_document(path, manifest, allow_same_issue=allow_same_issue)
        for path in paths
    ]
    sections = [doc.section for doc in documents]
    if len(sections) != len(set(sections)):
        raise ValueError(
            "Multiple input PDFs for the same section; provide one final version per section"
        )
    updates: list[PreparedUpdate] = []
    unchanged: list[str] = []
    for path, document in zip(paths, documents, strict=True):
        previous = next(
            doc
            for doc in manifest.documents
            if doc.is_active and doc.section == document.section
        )
        if previous.sha256 == document.sha256:
            unchanged.append(document.section)
        else:
            updates.append(prepare_update(path, previous, document, root))
    return updates, unchanged
