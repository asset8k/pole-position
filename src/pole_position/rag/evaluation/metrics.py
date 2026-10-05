from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.evaluation.schemas import (
    EvaluationCase,
    ExpectedSource,
)


@dataclass(frozen=True)
class CaseRetrievalMetrics:
    recall_at_5: float
    recall_at_10: float
    reciprocal_rank_at_10: float


@dataclass(frozen=True)
class RetrievalSummary:
    evaluated_cases: int
    skipped_cases: int
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float


def source_matches_chunk(
    source: ExpectedSource,
    chunk: RetrievalChunk,
) -> bool:
    """Match evidence location, not generated answer wording."""
    if (
        chunk.document_id != source.document_id
        or chunk.source_kind != source.source_kind
        or chunk.clause_identifier != source.clause_identifier
        or chunk.appendix_identifier != source.appendix_identifier
    ):
        return False

    return any(
        chunk.start_pdf_page <= page <= chunk.end_pdf_page for page in source.pdf_pages
    )


def _validate_expected_sources(
    expected_sources: Sequence[ExpectedSource],
) -> None:
    if not expected_sources:
        raise ValueError("Retrieval metrics require expected sources")

    keys = [
        (
            source.document_id,
            source.source_kind,
            source.clause_identifier,
            source.appendix_identifier,
            tuple(sorted(source.pdf_pages)),
        )
        for source in expected_sources
    ]
    if len(keys) != len(set(keys)):
        raise ValueError("Expected sources must be unique")


def recall_at_k(
    chunks: Sequence[RetrievalChunk],
    expected_sources: Sequence[ExpectedSource],
    *,
    k: int,
) -> float:
    """Fraction of expected sources found in the first k ranked chunks."""
    if k <= 0:
        raise ValueError("k must be positive")
    _validate_expected_sources(expected_sources)

    top_chunks = chunks[:k]

    found = sum(
        any(source_matches_chunk(source, chunk) for chunk in top_chunks)
        for source in expected_sources
    )

    return found / len(expected_sources)


def reciprocal_rank_at_k(
    chunks: Sequence[RetrievalChunk],
    expected_sources: Sequence[ExpectedSource],
    *,
    k: int,
) -> float:
    """Return 1 / rank of the first relevant chunk, or zero if none."""
    if k <= 0:
        raise ValueError("k must be positive")
    _validate_expected_sources(expected_sources)

    for rank, chunk in enumerate(chunks[:k], start=1):
        if any(source_matches_chunk(source, chunk) for source in expected_sources):
            return 1.0 / rank

    return 0.0


def score_retrieval(
    case: EvaluationCase,
    chunks: Sequence[RetrievalChunk],
) -> CaseRetrievalMetrics | None:
    """Score answerable cases; evaluate abstention separately."""
    if not case.answerable:
        return None

    return CaseRetrievalMetrics(
        recall_at_5=recall_at_k(
            chunks,
            case.expected_sources,
            k=5,
        ),
        recall_at_10=recall_at_k(
            chunks,
            case.expected_sources,
            k=10,
        ),
        reciprocal_rank_at_10=reciprocal_rank_at_k(
            chunks,
            case.expected_sources,
            k=10,
        ),
    )


def summarize_metrics(
    scores: Sequence[CaseRetrievalMetrics | None],
) -> RetrievalSummary | None:
    """Average scores across questions, excluding unanswerable cases."""
    scored_cases = [score for score in scores if score is not None]

    if not scored_cases:
        return None

    return RetrievalSummary(
        evaluated_cases=len(scored_cases),
        skipped_cases=len(scores) - len(scored_cases),
        recall_at_5=fmean(score.recall_at_5 for score in scored_cases),
        recall_at_10=fmean(score.recall_at_10 for score in scored_cases),
        mrr_at_10=fmean(score.reciprocal_rank_at_10 for score in scored_cases),
    )
