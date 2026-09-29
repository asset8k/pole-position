from datetime import date
from pathlib import Path

import pytest

from pole_position.corpus.schemas import (
    CorpusManifest,
    RegulationDocument,
    RegulationSection,
)
from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk
from pole_position.rag.indexing.bm25_index import BM25Index
from pole_position.rag.retrieval.sparse import (
    SparseCorpus,
    load_sparse_corpus,
    retrieve_sparse,
)


def make_document(
    section: RegulationSection,
    *,
    season: int = 2026,
    active: bool = True,
) -> RegulationDocument:
    return RegulationDocument(
        document_id=f"fia-f1-{season}-section-{section.lower()}-issue-01",
        section=section,
        title=f"Section {section} Regulations",
        season=season,
        issue_number=1,
        published_date=date(season, 1, 1),
        wmsc_approval_date=date(season - 1, 12, 1),
        source_path=f"regulations/section_{section.lower()}.pdf",
        sha256="a" * 64,
        page_count=10,
        is_active=active,
    )


def make_chunk(
    document: RegulationDocument,
    clause_identifier: str,
    text: str,
    *,
    page: int = 5,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{document.document_id}:{clause_identifier}:0",
        document_id=document.document_id,
        source_sha256=document.sha256,
        section=document.section,
        source_kind="clause",
        article_identifier=clause_identifier.split(".")[0],
        clause_identifier=clause_identifier,
        chunk_index=0,
        text=text,
        start_pdf_page=page,
        end_pdf_page=page,
    )


def write_manifest(tmp_path: Path, documents: list[RegulationDocument]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(
        CorpusManifest(documents=documents).model_dump_json(), encoding="utf-8"
    )
    return path


def write_chunks(
    chunks_dir: Path,
    document: RegulationDocument,
    chunks: list[RetrievalChunk],
) -> Path:
    chunks_dir.mkdir(exist_ok=True)
    path = chunks_dir / f"{document.document_id}.json"
    path.write_text(
        ChunkedDocument(
            document_id=document.document_id,
            source_sha256=document.sha256,
            chunks=chunks,
        ).model_dump_json(),
        encoding="utf-8",
    )
    return path


def test_load_sparse_corpus_indexes_only_active_documents_for_season(
    tmp_path: Path,
) -> None:
    active_2026 = make_document("A")
    inactive_2026 = make_document("B", active=False)
    active_2025 = make_document("C", season=2025)
    manifest_path = write_manifest(
        tmp_path, [active_2026, inactive_2026, active_2025]
    )
    chunks_dir = tmp_path / "chunks"
    chunk = make_chunk(active_2026, "A1.1", "FIA regulations", page=7)
    write_chunks(chunks_dir, active_2026, [chunk])
    # No artifacts for the skipped documents: loading them would fail.

    corpus = load_sparse_corpus(manifest_path, chunks_dir)

    assert corpus.index.chunk_count == 1
    assert corpus.document_titles == {active_2026.document_id: active_2026.title}
    assert corpus.index.search("FIA")[0].chunk == chunk


def test_load_sparse_corpus_accepts_another_season(tmp_path: Path) -> None:
    document = make_document("B", season=2025)
    manifest_path = write_manifest(tmp_path, [document])
    chunks_dir = tmp_path / "chunks"
    chunk = make_chunk(document, "B8.2.8", "Power Unit penalty")
    write_chunks(chunks_dir, document, [chunk])

    corpus = load_sparse_corpus(manifest_path, chunks_dir, season=2025)

    assert corpus.index.chunk_count == 1
    assert corpus.index.search("penalty")[0].chunk == chunk


def test_load_sparse_corpus_rejects_no_active_chunks(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, [make_document("A", active=False)])

    with pytest.raises(ValueError, match="No active chunks found for season 2026"):
        load_sparse_corpus(manifest_path, tmp_path / "chunks")


def test_load_sparse_corpus_rejects_missing_active_artifact(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, [make_document("A")])

    with pytest.raises(FileNotFoundError):
        load_sparse_corpus(manifest_path, tmp_path / "chunks")


@pytest.mark.parametrize("field", ["document_id", "source_sha256"])
def test_load_sparse_corpus_rejects_artifact_header_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    document = make_document("A")
    manifest_path = write_manifest(tmp_path, [document])
    chunks_dir = tmp_path / "chunks"
    path = write_chunks(
        chunks_dir, document, [make_chunk(document, "A1.1", "General rules")]
    )
    artifact = ChunkedDocument.model_validate_json(path.read_text(encoding="utf-8"))
    replacement = "wrong-document" if field == "document_id" else "b" * 64
    path.write_text(
        artifact.model_copy(update={field: replacement}).model_dump_json(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Chunk artifact does not match manifest"):
        load_sparse_corpus(manifest_path, chunks_dir)


@pytest.mark.parametrize("field", ["document_id", "source_sha256", "section"])
def test_load_sparse_corpus_rejects_chunk_metadata_mismatch(
    tmp_path: Path,
    field: str,
) -> None:
    document = make_document("A")
    manifest_path = write_manifest(tmp_path, [document])
    chunks_dir = tmp_path / "chunks"
    chunk = make_chunk(document, "A1.1", "General rules")
    if field == "section":
        # Keep the chunk internally valid so the loader detects its mismatch
        # with the Section A manifest document.
        changes = {
            "section": "B",
            "article_identifier": "B1",
            "clause_identifier": "B1.1",
        }
    else:
        replacement = "wrong-document" if field == "document_id" else "b" * 64
        changes = {field: replacement}
    mismatched_chunk = chunk.model_copy(update=changes)
    write_chunks(chunks_dir, document, [mismatched_chunk])

    with pytest.raises(ValueError, match="Chunk does not match manifest document"):
        load_sparse_corpus(manifest_path, chunks_dir)


def test_retrieve_sparse_returns_ranked_chunk_and_citation_metadata(
    tmp_path: Path,
) -> None:
    document = make_document("B")
    manifest_path = write_manifest(tmp_path, [document])
    chunks_dir = tmp_path / "chunks"
    expected = make_chunk(document, "B8.2.8", "B8.2.8 Power Unit penalty", page=67)
    other = make_chunk(document, "B8.2.3", "B8.2.3 Power Unit allocation")
    write_chunks(chunks_dir, document, [expected, other])
    corpus = load_sparse_corpus(manifest_path, chunks_dir)

    hits = retrieve_sparse("B8.2.8", corpus=corpus, top_k=5)

    assert len(hits) == 1
    assert hits[0].chunk == expected
    assert hits[0].chunk.start_pdf_page == 67
    assert hits[0].document_title == document.title
    assert hits[0].score > 0
    assert retrieve_sparse("unmatched", corpus=corpus) == []


def test_retrieve_sparse_filters_section_before_top_k(tmp_path: Path) -> None:
    document_a = make_document("A")
    document_b = make_document("B")
    manifest_path = write_manifest(tmp_path, [document_a, document_b])
    chunks_dir = tmp_path / "chunks"
    write_chunks(
        chunks_dir,
        document_a,
        [make_chunk(document_a, "A1.1", "power power power")],
    )
    chunk_b = make_chunk(document_b, "B8.2.8", "power")
    write_chunks(chunks_dir, document_b, [chunk_b])
    corpus = load_sparse_corpus(manifest_path, chunks_dir)

    assert retrieve_sparse("power", corpus=corpus, top_k=1)[0].chunk.section == "A"
    filtered = retrieve_sparse("power", corpus=corpus, top_k=1, section="B")

    assert len(filtered) == 1
    assert filtered[0].chunk == chunk_b
    assert filtered[0].document_title == document_b.title


def test_retrieve_sparse_rejects_missing_document_title() -> None:
    document = make_document("A")
    chunk = make_chunk(document, "A1.1", "General rules")
    corpus = SparseCorpus(index=BM25Index([chunk]), document_titles={})

    with pytest.raises(RuntimeError, match="No document title"):
        retrieve_sparse("General", corpus=corpus)


@pytest.mark.parametrize(
    ("question", "top_k", "message"),
    [
        ("  ", 5, "Query cannot be empty"),
        ("power", 0, "top_k must be positive"),
    ],
)
def test_retrieve_sparse_rejects_invalid_inputs(
    question: str,
    top_k: int,
    message: str,
) -> None:
    document = make_document("B")
    chunk = make_chunk(document, "B8.2.8", "Power Unit penalty")
    corpus = SparseCorpus(
        index=BM25Index([chunk]), document_titles={document.document_id: document.title}
    )

    with pytest.raises(ValueError, match=message):
        retrieve_sparse(question, corpus=corpus, top_k=top_k)
