from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.sparse import SparseHit


@dataclass(frozen=True)
class FusedHit:
    chunk: RetrievalChunk
    document_title: str
    fusion_score: float
    dense_rank: int | None
    sparse_rank: int | None
    dense_score: float | None
    sparse_score: float | None

    @property
    def score(self) -> float:
        """The combined score, for consumers that expect a hit.score."""
        return self.fusion_score


@dataclass
class _Candidate:
    chunk: RetrievalChunk
    document_title: str
    fusion_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    dense_score: float | None = None
    sparse_score: float | None = None


def fuse_hits(
    dense_hits: Sequence[DenseHit],
    sparse_hits: Sequence[SparseHit],
    *,
    top_k: int = 20,
    rrf_k: int = 60,
) -> list[FusedHit]:
    """Merge ranked dense and sparse results using reciprocal rank fusion."""
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    candidates: dict[str, _Candidate] = {}

    def add_hits(
        hits: Sequence[DenseHit | SparseHit],
        source: Literal["dense", "sparse"],
    ) -> None:
        seen_in_this_list: set[str] = set()

        for rank, hit in enumerate(hits, start=1):
            chunk_id = hit.chunk.chunk_id
            candidate = candidates.get(chunk_id)

            if candidate is None:
                candidate = _Candidate(
                    chunk=hit.chunk,
                    document_title=hit.document_title,
                )
                candidates[chunk_id] = candidate
            elif (
                candidate.chunk != hit.chunk
                or candidate.document_title != hit.document_title
            ):
                raise ValueError(f"Conflicting metadata for chunk {chunk_id}")

            # A duplicate within one result list gets credit only once.
            if chunk_id in seen_in_this_list:
                continue
            seen_in_this_list.add(chunk_id)

            candidate.fusion_score += 1 / (rrf_k + rank)

            if source == "dense":
                candidate.dense_rank = rank
                candidate.dense_score = hit.score
            else:
                candidate.sparse_rank = rank
                candidate.sparse_score = hit.score

    add_hits(dense_hits, "dense")
    add_hits(sparse_hits, "sparse")

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (
            -candidate.fusion_score,
            candidate.chunk.chunk_id,
        ),
    )

    return [
        FusedHit(
            chunk=candidate.chunk,
            document_title=candidate.document_title,
            fusion_score=candidate.fusion_score,
            dense_rank=candidate.dense_rank,
            sparse_rank=candidate.sparse_rank,
            dense_score=candidate.dense_score,
            sparse_score=candidate.sparse_score,
        )
        for candidate in ranked[:top_k]
    ]
