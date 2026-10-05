"""Compare dense, BM25, fused, and optional reranked regulation results."""

from argparse import ArgumentParser, Namespace
from pathlib import Path
from time import perf_counter
from typing import cast

from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.config import settings
from pole_position.corpus.schemas import RegulationSection
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.retrieval.dense import DenseHit, retrieve_dense
from pole_position.rag.retrieval.fusion import FusedHit, fuse_hits
from pole_position.rag.retrieval.reranker import (
    MAX_RERANK_CANDIDATES,
    rerank_hits,
)
from pole_position.rag.retrieval.sparse import (
    SparseHit,
    load_sparse_corpus,
    retrieve_sparse,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"
CHUNKS_DIR = PROJECT_ROOT / "artifacts/chunks"


def parse_args() -> Namespace:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question to search for")
    parser.add_argument("--section", choices=("A", "B", "C", "D", "E", "F"))
    parser.add_argument("--top-k", type=int, default=5, help="Final hits to display")
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=20,
        help="Candidates to retrieve from each search method",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Also rerank fused candidates using a model (adds an API call)",
    )
    parser.add_argument(
        "--rerank-model",
        help="Model for --rerank; defaults to the configured answer model",
    )
    args = parser.parse_args()

    if not args.question.strip():
        parser.error("question cannot be blank")
    if args.top_k <= 0 or args.candidate_k <= 0:
        parser.error("--top-k and --candidate-k must be positive")
    if args.rerank_model is not None and not args.rerank:
        parser.error("--rerank-model requires --rerank")
    if args.rerank_model is not None and not args.rerank_model.strip():
        parser.error("--rerank-model cannot be blank")
    if args.rerank and max(args.candidate_k, args.top_k) > MAX_RERANK_CANDIDATES:
        parser.error(
            f"--rerank supports at most {MAX_RERANK_CANDIDATES} candidates"
        )

    return args


def location(chunk: RetrievalChunk) -> str:
    if chunk.source_kind == "clause":
        return f"clause {chunk.clause_identifier}"
    if chunk.source_kind == "appendix":
        return f"appendix {chunk.appendix_identifier}"
    return "preamble"


def describe_chunk(chunk: RetrievalChunk) -> str:
    pages = str(chunk.start_pdf_page)
    if chunk.end_pdf_page != chunk.start_pdf_page:
        pages += f"-{chunk.end_pdf_page}"
    preview = " ".join(chunk.text.split())[:140]
    return (
        f"Section {chunk.section}, {location(chunk)}, PDF p. {pages}\n"
        f"     {chunk.chunk_id}\n"
        f"     {preview}"
    )


def print_dense(hits: list[DenseHit]) -> None:
    print(f"\nDENSE ({len(hits)} hits; cosine similarity)")
    for rank, hit in enumerate(hits, start=1):
        print(f"{rank:>2}. score={hit.score:.4f}  {describe_chunk(hit.chunk)}")


def print_sparse(hits: list[SparseHit]) -> None:
    print(f"\nBM25 ({len(hits)} hits; keyword score)")
    for rank, hit in enumerate(hits, start=1):
        print(f"{rank:>2}. score={hit.score:.4f}  {describe_chunk(hit.chunk)}")


def print_fused(hits: list[FusedHit]) -> None:
    print(f"\nFUSED ({len(hits)} hits; reciprocal rank fusion)")
    for rank, hit in enumerate(hits, start=1):
        dense_rank = hit.dense_rank if hit.dense_rank is not None else "-"
        sparse_rank = hit.sparse_rank if hit.sparse_rank is not None else "-"
        print(
            f"{rank:>2}. RRF={hit.fusion_score:.5f} "
            f"dense#{dense_rank} BM25#{sparse_rank}  {describe_chunk(hit.chunk)}"
        )


def print_reranked(
    hits: list[FusedHit],
    fused_candidates: list[FusedHit],
    *,
    model: str,
    elapsed_seconds: float,
) -> None:
    fused_ranks = {
        hit.chunk.chunk_id: rank for rank, hit in enumerate(fused_candidates, start=1)
    }
    print(f"\nRERANKED ({len(hits)} hits; {model}; {elapsed_seconds:.2f}s)")
    for rank, hit in enumerate(hits, start=1):
        print(
            f"{rank:>2}. was fused#{fused_ranks[hit.chunk.chunk_id]}  "
            f"{describe_chunk(hit.chunk)}"
        )


def main() -> None:
    args = parse_args()
    section = cast(RegulationSection | None, args.section)
    candidate_k = max(args.candidate_k, args.top_k)

    # Load local chunks before making a remote embedding/search request.
    sparse_corpus = load_sparse_corpus(MANIFEST_PATH, CHUNKS_DIR)

    openai_client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    qdrant_client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value(),
    )
    rerank_model = args.rerank_model or settings.answer_model
    reranked_hits: list[FusedHit] | None = None
    rerank_seconds: float | None = None
    try:
        search_start = perf_counter()
        dense_hits = retrieve_dense(
            args.question,
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=settings.qdrant_collection,
            top_k=candidate_k,
            section=section,
            document_ids=tuple(sparse_corpus.document_titles),
        )
        sparse_hits = retrieve_sparse(
            args.question,
            corpus=sparse_corpus,
            top_k=candidate_k,
            section=section,
        )
        fused_candidates = fuse_hits(
            dense_hits,
            sparse_hits,
            top_k=candidate_k if args.rerank else args.top_k,
        )
        search_seconds = perf_counter() - search_start

        if args.rerank:
            rerank_start = perf_counter()
            reranked_hits = rerank_hits(
                args.question,
                fused_candidates,
                client=openai_client,
                model=rerank_model,
                top_k=args.top_k,
            )
            rerank_seconds = perf_counter() - rerank_start
    finally:
        openai_client.close()
        qdrant_client.close()

    print(f"Question: {args.question}")
    print(f"Section filter: {section or 'none'}")
    print_dense(dense_hits)
    print_sparse(sparse_hits)
    print_fused(fused_candidates[: args.top_k])
    if reranked_hits is not None and rerank_seconds is not None:
        print_reranked(
            reranked_hits,
            fused_candidates,
            model=rerank_model,
            elapsed_seconds=rerank_seconds,
        )
    print(f"\nRetrieval + fusion: {search_seconds:.2f}s")
    print("\nNote: cosine, BM25, and RRF scores are on different scales.")


if __name__ == "__main__":
    main()
