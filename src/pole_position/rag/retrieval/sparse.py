from dataclasses import dataclass
from pathlib import Path

from pole_position.corpus.manifest import load_manifest
from pole_position.corpus.schemas import RegulationSection
from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk
from pole_position.rag.indexing.bm25_index import BM25Index


@dataclass(frozen=True)
class SparseCorpus:
    index: BM25Index
    document_titles: dict[str, str]


@dataclass(frozen=True)
class SparseHit:
    chunk: RetrievalChunk
    score: float
    document_title: str


def load_sparse_corpus(
    manifest_path: Path,
    chunks_dir: Path,
    *,
    season: int = 2026,
) -> SparseCorpus:
    """Build a BM25 index from active documents for one season."""
    manifest = load_manifest(manifest_path)

    chunks: list[RetrievalChunk] = []
    document_titles: dict[str, str] = {}

    for document in manifest.documents:
        if not document.is_active or document.season != season:
            continue

        chunks_path = chunks_dir / f"{document.document_id}.json"
        chunked_document = ChunkedDocument.model_validate_json(
            chunks_path.read_text(encoding="utf-8")
        )

        if (
            chunked_document.document_id != document.document_id
            or chunked_document.source_sha256 != document.sha256
        ):
            raise ValueError(
                f"Chunk artifact does not match manifest: {document.document_id}"
            )

        for chunk in chunked_document.chunks:
            if (
                chunk.document_id != document.document_id
                or chunk.source_sha256 != document.sha256
                or chunk.section != document.section
            ):
                raise ValueError(
                    f"Chunk does not match manifest document: {chunk.chunk_id}"
                )

        chunks.extend(chunked_document.chunks)
        document_titles[document.document_id] = document.title

    if not chunks:
        raise ValueError(f"No active chunks found for season {season}")

    return SparseCorpus(
        index=BM25Index(chunks),
        document_titles=document_titles,
    )


def retrieve_sparse(
    question: str,
    *,
    corpus: SparseCorpus,
    top_k: int = 5,
    section: RegulationSection | None = None,
) -> list[SparseHit]:
    """Find chunks using BM25 keyword scores."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    # With a section filter, score all keyword matches first and filter
    # before taking top_k. Otherwise, higher-ranked chunks from other
    # sections could hide relevant chunks from the requested section.
    search_limit = corpus.index.chunk_count if section is not None else top_k
    matches = corpus.index.search(question, top_k=search_limit)

    if section is not None:
        matches = [match for match in matches if match.chunk.section == section][:top_k]

    hits: list[SparseHit] = []

    for match in matches:
        title = corpus.document_titles.get(match.chunk.document_id)
        if not title:
            raise RuntimeError(f"No document title for {match.chunk.document_id}")

        hits.append(
            SparseHit(
                chunk=match.chunk,
                score=match.score,
                document_title=title,
            )
        )

    return hits
