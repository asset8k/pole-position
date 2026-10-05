from collections.abc import Callable, Sequence
from typing import Literal

import pytest

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.evaluation.metrics import (
    CaseRetrievalMetrics,
    recall_at_k,
    reciprocal_rank_at_k,
    score_retrieval,
    source_matches_chunk,
    summarize_metrics,
)
from pole_position.rag.evaluation.schemas import EvaluationCase, ExpectedSource

DOCUMENT_ID = "test-section-b"
type SourceKind = Literal["clause", "appendix", "preamble"]


def make_source(
    *,
    kind: SourceKind = "clause",
    identifier: str = "B1.1",
    pages: tuple[int, ...] = (10,),
    document_id: str = DOCUMENT_ID,
) -> ExpectedSource:
    return ExpectedSource(
        document_id=document_id,
        source_kind=kind,
        clause_identifier=identifier if kind == "clause" else None,
        appendix_identifier=identifier if kind == "appendix" else None,
        pdf_pages=list(pages),
    )


def make_chunk(
    *,
    kind: SourceKind = "clause",
    identifier: str = "B1.1",
    page: int = 10,
    end_page: int | None = None,
    chunk_index: int = 0,
    document_id: str = DOCUMENT_ID,
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{document_id}:{kind}:{identifier}:{chunk_index}",
        document_id=document_id,
        source_sha256="a" * 64,
        section="B",
        source_kind=kind,
        article_identifier=identifier.split(".")[0] if kind == "clause" else None,
        clause_identifier=identifier if kind == "clause" else None,
        appendix_identifier=identifier if kind == "appendix" else None,
        chunk_index=chunk_index,
        text="Synthetic regulation evidence for metric tests.",
        start_pdf_page=page,
        end_pdf_page=page if end_page is None else end_page,
    )


def make_case(sources: list[ExpectedSource]) -> EvaluationCase:
    return EvaluationCase(
        id="test_question",
        category="semantic",
        question="Which rules apply?",
        answerable=True,
        expected_sources=sources,
        expected_facts=["A manually verified fact."],
    )


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [("clause", "B1.1"), ("appendix", "B1"), ("preamble", "unused")],
)
def test_matching_supports_all_source_kinds(kind: SourceKind, identifier: str) -> None:
    assert source_matches_chunk(
        make_source(kind=kind, identifier=identifier),
        make_chunk(kind=kind, identifier=identifier),
    )


@pytest.mark.parametrize("mismatch", ["document", "kind", "identifier", "page"])
def test_clause_match_requires_document_kind_identifier_and_page(mismatch: str) -> None:
    chunk = make_chunk()
    if mismatch == "document":
        chunk = make_chunk(document_id="another-document")
    elif mismatch == "kind":
        chunk = make_chunk(kind="appendix", identifier="B1")
    elif mismatch == "identifier":
        chunk = make_chunk(identifier="B1.2")
    elif mismatch == "page":
        chunk = make_chunk(page=11)

    assert not source_matches_chunk(make_source(), chunk)


def test_appendix_match_requires_the_correct_appendix_identifier() -> None:
    assert not source_matches_chunk(
        make_source(kind="appendix", identifier="B1"),
        make_chunk(kind="appendix", identifier="B2"),
    )


@pytest.mark.parametrize(
    ("expected_page", "matches"),
    [(9, False), (10, True), (11, True), (12, True), (13, False)],
)
def test_page_range_matching_is_inclusive(expected_page: int, matches: bool) -> None:
    assert source_matches_chunk(
        make_source(pages=(expected_page,)),
        make_chunk(page=10, end_page=12),
    ) is matches


def test_matching_needs_only_one_of_the_labelled_pages() -> None:
    assert source_matches_chunk(
        make_source(pages=(8, 12)), make_chunk(page=12)
    )


def test_recall_measures_fraction_of_expected_sources_found() -> None:
    expected = [make_source(identifier=f"B1.{index}") for index in range(1, 4)]
    chunks = [make_chunk(identifier="B1.1"), make_chunk(identifier="B1.3")]

    assert recall_at_k(chunks, expected, k=5) == pytest.approx(2 / 3)


def test_recall_does_not_double_count_multiple_chunks_from_one_source() -> None:
    expected = [make_source(), make_source(identifier="B1.2")]
    chunks = [make_chunk(chunk_index=index) for index in range(5)]

    assert recall_at_k(chunks, expected, k=5) == 0.5
    assert recall_at_k([chunks[0]] * 5, expected, k=5) == 0.5


def test_duplicate_hits_keep_their_original_ranking_slots() -> None:
    irrelevant = make_chunk(identifier="B1.9")
    chunks = [irrelevant, irrelevant, make_chunk()]
    expected = [make_source()]

    assert recall_at_k(chunks, expected, k=2) == 0.0
    assert reciprocal_rank_at_k(chunks, expected, k=10) == pytest.approx(1 / 3)


@pytest.mark.parametrize("has_irrelevant_hit", [False, True])
def test_missing_relevant_results_score_zero(has_irrelevant_hit: bool) -> None:
    chunks = [make_chunk(identifier="B1.9")] if has_irrelevant_hit else []
    expected = [make_source()]

    assert recall_at_k(chunks, expected, k=10) == 0.0
    assert reciprocal_rank_at_k(chunks, expected, k=10) == 0.0


@pytest.mark.parametrize("rank", [1, 3, 5, 10, 11])
def test_reciprocal_rank_uses_first_relevant_position_and_cutoff(rank: int) -> None:
    chunks = [
        make_chunk(identifier="B1.9", chunk_index=index)
        for index in range(rank - 1)
    ] + [make_chunk()]
    expected_score = 1 / rank if rank <= 10 else 0.0

    assert reciprocal_rank_at_k(chunks, [make_source()], k=10) == pytest.approx(
        expected_score
    )
    assert recall_at_k(chunks, [make_source()], k=10) == (
        1.0 if rank <= 10 else 0.0
    )


def test_reciprocal_rank_uses_first_relevant_hit_not_number_of_sources_found() -> None:
    expected = [make_source(), make_source(identifier="B1.2")]
    chunks = [
        make_chunk(identifier="B1.9"),
        make_chunk(identifier="B1.2"),
        make_chunk(),
    ]

    assert reciprocal_rank_at_k(chunks, expected, k=10) == 0.5


def test_case_scoring_matches_rank_three_and_rank_eight_example() -> None:
    case = make_case([make_source(), make_source(identifier="B1.2")])
    chunks = [
        make_chunk(identifier="B1.9", chunk_index=index) for index in range(10)
    ]
    chunks[2] = make_chunk()
    chunks[7] = make_chunk(identifier="B1.2")
    original_order = [chunk.chunk_id for chunk in chunks]
    original_sources = [source.model_dump() for source in case.expected_sources]

    scores = score_retrieval(case, chunks)

    assert scores is not None
    assert scores.recall_at_5 == 0.5
    assert scores.recall_at_10 == 1.0
    assert scores.reciprocal_rank_at_10 == pytest.approx(1 / 3)
    assert [chunk.chunk_id for chunk in chunks] == original_order
    assert [source.model_dump() for source in case.expected_sources] == original_sources


def test_unanswerable_case_is_skipped_even_if_search_returns_chunks() -> None:
    case = EvaluationCase(
        id="unanswerable",
        category="unanswerable",
        question="Who will win the next race?",
        answerable=False,
    )

    assert score_retrieval(case, []) is None
    assert score_retrieval(case, [make_chunk()]) is None


# Both metric functions share these invalid-input rules.
type MetricFunction = Callable[..., float]


@pytest.mark.parametrize("metric", [recall_at_k, reciprocal_rank_at_k])
@pytest.mark.parametrize("k", [0, -1])
def test_metrics_reject_nonpositive_k(metric: MetricFunction, k: int) -> None:
    with pytest.raises(ValueError, match="k must be positive"):
        metric([], [make_source()], k=k)


@pytest.mark.parametrize("metric", [recall_at_k, reciprocal_rank_at_k])
def test_metrics_reject_missing_expected_sources(metric: MetricFunction) -> None:
    with pytest.raises(ValueError, match="require expected sources"):
        metric([], [], k=10)


@pytest.mark.parametrize("metric", [recall_at_k, reciprocal_rank_at_k])
@pytest.mark.parametrize("reorder_pages", [False, True])
def test_metrics_reject_duplicate_source_labels(
    metric: MetricFunction, reorder_pages: bool
) -> None:
    first = make_source(pages=(10, 11))
    second = make_source(pages=(11, 10) if reorder_pages else (10, 11))
    with pytest.raises(ValueError, match="Expected sources must be unique"):
        metric([], [first, second], k=10)


def test_summary_averages_per_question_and_excludes_unanswerable_cases() -> None:
    scores = [
        CaseRetrievalMetrics(1.0, 1.0, 1.0),
        CaseRetrievalMetrics(0.5, 1.0, 0.5),
        CaseRetrievalMetrics(0.0, 0.0, 0.0),
        None,
    ]
    summary = summarize_metrics(scores)

    assert summary is not None
    assert summary.evaluated_cases == 3
    assert summary.skipped_cases == 1
    assert summary.recall_at_5 == 0.5
    assert summary.recall_at_10 == pytest.approx(2 / 3)
    assert summary.mrr_at_10 == 0.5


def test_summary_is_macro_average_not_weighted_by_number_of_expected_sources() -> None:
    small_case = make_case([make_source()])
    large_case = make_case([
        make_source(identifier=f"B1.{index}") for index in range(1, 5)
    ])
    summary = summarize_metrics([
        score_retrieval(small_case, [make_chunk()]),
        score_retrieval(large_case, []),
    ])

    assert summary is not None
    # Each question has equal weight: (1 + 0) / 2, not 1 / 5 sources.
    assert summary.recall_at_5 == 0.5
    assert summary.recall_at_10 == 0.5
    assert summary.mrr_at_10 == 0.5


@pytest.mark.parametrize("scores", [[], [None], [None, None]])
def test_summary_without_scored_cases_is_none(
    scores: Sequence[CaseRetrievalMetrics | None],
) -> None:
    assert summarize_metrics(scores) is None


def test_answerable_case_with_no_results_remains_a_scored_zero() -> None:
    score = score_retrieval(make_case([make_source()]), [])
    summary = summarize_metrics([score])

    assert score == CaseRetrievalMetrics(0.0, 0.0, 0.0)
    assert summary is not None
    assert summary.evaluated_cases == 1
    assert summary.skipped_cases == 0
    assert summary.mrr_at_10 == 0.0
