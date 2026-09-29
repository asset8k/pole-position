import pytest

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.fusion import fuse_hits
from pole_position.rag.retrieval.sparse import SparseHit

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"
DOCUMENT_TITLE = "Sporting Regulations"


def make_chunk(clause_identifier: str) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{DOCUMENT_ID}:{clause_identifier}:0",
        document_id=DOCUMENT_ID,
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier=clause_identifier,
        chunk_index=0,
        text=f"Regulation text for {clause_identifier}.",
        start_pdf_page=67,
        end_pdf_page=67,
    )


def dense_hit(chunk: RetrievalChunk, score: float = 0.8) -> DenseHit:
    return DenseHit(chunk=chunk, score=score, document_title=DOCUMENT_TITLE)


def sparse_hit(chunk: RetrievalChunk, score: float = 10.0) -> SparseHit:
    return SparseHit(chunk=chunk, score=score, document_title=DOCUMENT_TITLE)


def test_fuse_hits_combines_overlap_and_preserves_debug_metadata() -> None:
    dense_only = make_chunk("B8.2.2")
    shared = make_chunk("B8.2.8")
    sparse_only = make_chunk("B8.2.3")

    fused = fuse_hits(
        [dense_hit(dense_only, 0.9), dense_hit(shared, 0.7)],
        [sparse_hit(shared, 12.0), sparse_hit(sparse_only, 8.0)],
    )

    assert [hit.chunk.chunk_id for hit in fused] == [
        shared.chunk_id,
        dense_only.chunk_id,
        sparse_only.chunk_id,
    ]
    assert len(fused) == 3

    first = fused[0]
    assert first.chunk == shared
    assert first.document_title == DOCUMENT_TITLE
    assert first.chunk.clause_identifier == "B8.2.8"
    assert first.chunk.start_pdf_page == 67
    assert first.dense_rank == 2
    assert first.sparse_rank == 1
    assert first.dense_score == 0.7
    assert first.sparse_score == 12.0
    assert first.fusion_score == pytest.approx(1 / 62 + 1 / 61)
    assert first.score == first.fusion_score

    assert fused[1].dense_rank == 1
    assert fused[1].sparse_rank is None
    assert fused[1].dense_score == 0.9
    assert fused[1].sparse_score is None
    assert fused[1].fusion_score == pytest.approx(1 / 61)

    assert fused[2].dense_rank is None
    assert fused[2].sparse_rank == 2
    assert fused[2].dense_score is None
    assert fused[2].sparse_score == 8.0
    assert fused[2].fusion_score == pytest.approx(1 / 62)


def test_fuse_hits_uses_ranks_not_incompatible_raw_scores() -> None:
    dense_first = make_chunk("B8.2.2")
    sparse_first = make_chunk("B8.2.3")

    fused = fuse_hits(
        [dense_hit(dense_first, score=0.01)],
        [sparse_hit(sparse_first, score=1_000.0)],
    )

    # Both are rank 1 in one list, despite very different raw score scales.
    assert [hit.chunk.chunk_id for hit in fused] == [
        dense_first.chunk_id,
        sparse_first.chunk_id,
    ]
    assert fused[0].fusion_score == fused[1].fusion_score


def test_fuse_hits_handles_one_empty_list_and_top_k() -> None:
    first = make_chunk("B8.2.2")
    second = make_chunk("B8.2.3")

    fused = fuse_hits([dense_hit(first), dense_hit(second)], [], top_k=1, rrf_k=10)

    assert len(fused) == 1
    assert fused[0].chunk == first
    assert fused[0].fusion_score == pytest.approx(1 / 11)
    assert fused[0].sparse_rank is None

    sparse_fused = fuse_hits([], [sparse_hit(second)])
    assert len(sparse_fused) == 1
    assert sparse_fused[0].chunk == second
    assert sparse_fused[0].dense_rank is None
    assert fuse_hits([], []) == []


def test_duplicate_within_one_list_gets_one_contribution() -> None:
    repeated = make_chunk("B8.2.2")
    next_chunk = make_chunk("B8.2.3")

    fused = fuse_hits(
        [dense_hit(repeated, 0.9), dense_hit(repeated, 0.8), dense_hit(next_chunk)],
        [],
    )

    assert [hit.chunk.chunk_id for hit in fused] == [
        repeated.chunk_id,
        next_chunk.chunk_id,
    ]
    assert fused[0].dense_rank == 1
    assert fused[0].dense_score == 0.9
    assert fused[0].fusion_score == pytest.approx(1 / 61)
    assert fused[1].dense_rank == 3
    assert fused[1].fusion_score == pytest.approx(1 / 63)


@pytest.mark.parametrize("conflict", ["chunk", "title"])
def test_fuse_hits_rejects_conflicting_metadata_for_same_chunk_id(
    conflict: str,
) -> None:
    chunk = make_chunk("B8.2.8")
    sparse = sparse_hit(chunk)
    if conflict == "chunk":
        sparse = SparseHit(
            chunk=chunk.model_copy(update={"text": "Different source text"}),
            score=sparse.score,
            document_title=sparse.document_title,
        )
    else:
        sparse = SparseHit(
            chunk=chunk,
            score=sparse.score,
            document_title="Different document title",
        )

    with pytest.raises(ValueError, match="Conflicting metadata for chunk"):
        fuse_hits([dense_hit(chunk)], [sparse])


@pytest.mark.parametrize(
    ("top_k", "rrf_k", "message"),
    [
        (0, 60, "top_k must be positive"),
        (5, 0, "rrf_k must be positive"),
    ],
)
def test_fuse_hits_rejects_invalid_parameters(
    top_k: int,
    rrf_k: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        fuse_hits([], [], top_k=top_k, rrf_k=rrf_k)
