from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, cast
from unittest.mock import Mock

import pytest
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.evaluation import runner
from pole_position.rag.evaluation.metrics import CaseRetrievalMetrics
from pole_position.rag.evaluation.schemas import (
    EvaluationCase,
    EvaluationDataset,
    ExpectedSource,
)
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.fusion import FusedHit
from pole_position.rag.retrieval.sparse import SparseCorpus, SparseHit

DOCUMENT_ID = "test-section-b"
DOCUMENT_TITLE = "Synthetic Sporting Regulations"
type SourceKind = Literal["clause", "appendix", "preamble"]


def make_chunk(
    identifier: str = "B1.1",
    *,
    kind: SourceKind = "clause",
) -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=f"{DOCUMENT_ID}:{kind}:{identifier}:0",
        document_id=DOCUMENT_ID,
        source_sha256="a" * 64,
        section="B",
        source_kind=kind,
        article_identifier=identifier.split(".")[0] if kind == "clause" else None,
        clause_identifier=identifier if kind == "clause" else None,
        appendix_identifier=identifier if kind == "appendix" else None,
        chunk_index=0,
        text=f"Synthetic evidence for {identifier}.",
        start_pdf_page=10,
        end_pdf_page=10,
    )


def make_case(
    case_id: str = "question-1",
    *,
    identifier: str = "B1.1",
    kind: SourceKind = "clause",
) -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        category="semantic",
        question="Which rule applies?",
        answerable=True,
        expected_sources=[
            ExpectedSource(
                document_id=DOCUMENT_ID,
                source_kind=kind,
                clause_identifier=identifier if kind == "clause" else None,
                appendix_identifier=identifier if kind == "appendix" else None,
                pdf_pages=[10],
            )
        ],
        expected_facts=["A manually verified fact."],
    )


def make_unanswerable_case() -> EvaluationCase:
    return EvaluationCase(
        id="unanswerable",
        category="unanswerable",
        question="Who will win the next race?",
        answerable=False,
    )


def keep_order(
    question: str,
    hits: Sequence[FusedHit],
    **kwargs: object,
) -> list[FusedHit]:
    return list(hits)


@dataclass
class RunnerMocks:
    openai_client: Mock
    qdrant_client: Mock
    sparse_corpus: Mock
    contextualize: Mock
    dense: Mock
    sparse: Mock
    fuse: Mock
    rerank: Mock

    def run(
        self,
        cases: list[EvaluationCase] | None = None,
        *,
        collection_name: str = "fia_regulations",
        model: str = "test-model",
        candidate_k: int = 20,
        rrf_k: int = 60,
        include_reranking: bool = True,
    ) -> runner.EvaluationReport:
        return runner.run_evaluation(
            EvaluationDataset(cases=cases if cases is not None else [make_case()]),
            openai_client=cast(OpenAI, self.openai_client),
            qdrant_client=cast(QdrantClient, self.qdrant_client),
            sparse_corpus=cast(SparseCorpus, self.sparse_corpus),
            collection_name=collection_name,
            model=model,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
            include_reranking=include_reranking,
        )

    def assert_no_pipeline_calls(self) -> None:
        for dependency in (
            self.contextualize,
            self.dense,
            self.sparse,
            self.fuse,
            self.rerank,
        ):
            dependency.assert_not_called()


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> RunnerMocks:
    relevant = make_chunk()
    irrelevant = make_chunk("B1.9")
    mocks = RunnerMocks(
        openai_client=Mock(spec=OpenAI),
        qdrant_client=Mock(spec=QdrantClient),
        sparse_corpus=Mock(spec=SparseCorpus, document_titles={make_chunk().document_id: DOCUMENT_TITLE}),
        contextualize=Mock(side_effect=lambda question, history, **kwargs: question),
        dense=Mock(
            return_value=[
                DenseHit(irrelevant, 0.9, DOCUMENT_TITLE),
                DenseHit(relevant, 0.8, DOCUMENT_TITLE),
            ]
        ),
        sparse=Mock(return_value=[SparseHit(relevant, 3.0, DOCUMENT_TITLE)]),
        # Exercise real local fusion and metrics; mock only retrieval and the LLM.
        fuse=Mock(wraps=runner.fuse_hits),
        rerank=Mock(side_effect=keep_order),
    )
    monkeypatch.setattr(runner, "contextualize_query", mocks.contextualize)
    monkeypatch.setattr(runner, "retrieve_dense", mocks.dense)
    monkeypatch.setattr(runner, "retrieve_sparse", mocks.sparse)
    monkeypatch.setattr(runner, "fuse_hits", mocks.fuse)
    monkeypatch.setattr(runner, "rerank_hits", mocks.rerank)
    return mocks


def test_runner_compares_all_three_methods_and_records_configuration(
    pipeline: RunnerMocks,
) -> None:
    report = pipeline.run()
    assert report.collection_name == "fia_regulations"
    assert report.model == "test-model"
    assert report.candidate_k == 20
    assert report.rrf_k == 60
    assert report.include_reranking is True
    assert len(report.cases) == 1
    result = report.cases[0]
    assert result.case_id == "question-1"
    assert result.category == "semantic"
    assert result.question == result.retrieval_question == "Which rule applies?"
    assert result.answerable is True
    assert set(result.methods) == {"dense", "hybrid", "hybrid_reranked"}
    assert result.methods["dense"].metrics == CaseRetrievalMetrics(1.0, 1.0, 0.5)
    for method in ("hybrid", "hybrid_reranked"):
        assert result.methods[method].metrics == CaseRetrievalMetrics(1.0, 1.0, 1.0)
        assert result.methods[method].chunks[0] == make_chunk()
    assert len(result.methods["hybrid"].chunks) == 2  # Overlap is deduplicated.
    for method, summary in report.summaries.items():
        assert summary is not None
        assert summary.evaluated_cases == 1
        assert summary.skipped_cases == 0
        assert summary.recall_at_5 == summary.recall_at_10 == 1.0
        assert summary.mrr_at_10 == (0.5 if method == "dense" else 1.0)
    # These are inert mocks, never real API clients.
    assert pipeline.openai_client.mock_calls == []
    assert pipeline.qdrant_client.mock_calls == []


def test_runner_reuses_retrieval_results_without_oracle_section_filters(
    pipeline: RunnerMocks,
) -> None:
    pipeline.run(candidate_k=10, rrf_k=30)
    pipeline.dense.assert_called_once_with(
        "Which rule applies?",
        openai_client=pipeline.openai_client,
        qdrant_client=pipeline.qdrant_client,
        collection_name="fia_regulations",
        top_k=10,
        document_ids=(make_chunk().document_id,),
    )
    pipeline.sparse.assert_called_once_with(
        "Which rule applies?", corpus=pipeline.sparse_corpus, top_k=10
    )
    pipeline.fuse.assert_called_once_with(
        pipeline.dense.return_value,
        pipeline.sparse.return_value,
        top_k=10,
        rrf_k=30,
    )
    assert pipeline.rerank.call_count == 1
    assert pipeline.rerank.call_args.kwargs["top_k"] == 10


def test_follow_up_is_contextualized_once_and_shared_by_every_method(
    pipeline: RunnerMocks,
) -> None:
    case = make_case()
    case.category = "follow_up"
    case.question = "What happens if they break that rule?"
    case.history = [
        ChatHistoryMessage(role="user", content="Which tyre rule applies?"),
        ChatHistoryMessage(
            role="assistant", content="Two specifications are required."
        ),
    ]
    pipeline.contextualize.side_effect = None
    pipeline.contextualize.return_value = (
        "What is the penalty for breaking the tyre rule?"
    )
    original_case = case.model_dump()
    report = pipeline.run([case])
    pipeline.contextualize.assert_called_once_with(
        case.question, case.history, client=pipeline.openai_client, model="test-model"
    )
    for dependency in (pipeline.dense, pipeline.sparse, pipeline.rerank):
        assert dependency.call_args.args[0] == pipeline.contextualize.return_value
    assert report.cases[0].question == case.question
    assert report.cases[0].retrieval_question == pipeline.contextualize.return_value
    assert case.model_dump() == original_case


def test_reranker_receives_twenty_candidates_and_keeps_more_than_five(
    pipeline: RunnerMocks,
) -> None:
    chunks = [make_chunk(f"B1.{index}") for index in range(1, 21)]
    pipeline.dense.return_value = [
        DenseHit(chunk, 1 / rank, DOCUMENT_TITLE)
        for rank, chunk in enumerate(chunks, 1)
    ]
    pipeline.sparse.return_value = [
        SparseHit(chunk, 20 / rank, DOCUMENT_TITLE)
        for rank, chunk in enumerate(chunks, 1)
    ]
    pipeline.rerank.side_effect = (
        lambda question, hits, **kwargs: list(reversed(hits))
    )
    report = pipeline.run([make_case(identifier="B1.20")])
    result = report.cases[0]
    assert len(pipeline.rerank.call_args.args[1]) == 20
    assert pipeline.rerank.call_args.kwargs == {
        "client": pipeline.openai_client,
        "model": "test-model",
        "top_k": 20,
    }
    assert result.methods["dense"].chunks == chunks
    assert result.methods["hybrid"].chunks == chunks
    assert result.methods["hybrid_reranked"].chunks == list(reversed(chunks))
    for method in ("dense", "hybrid"):
        assert result.methods[method].metrics == CaseRetrievalMetrics(0.0, 0.0, 0.0)
    assert result.methods["hybrid_reranked"].metrics == CaseRetrievalMetrics(
        1.0, 1.0, 1.0
    )


def test_reranking_can_be_disabled(pipeline: RunnerMocks) -> None:
    report = pipeline.run(include_reranking=False)
    pipeline.rerank.assert_not_called()
    assert report.include_reranking is False
    assert set(report.cases[0].methods) == set(report.summaries) == {"dense", "hybrid"}


def test_sparse_only_results_can_be_scored(pipeline: RunnerMocks) -> None:
    pipeline.dense.return_value = []
    report = pipeline.run()
    result = report.cases[0]
    assert result.methods["dense"].chunks == []
    assert result.methods["dense"].metrics == CaseRetrievalMetrics(0.0, 0.0, 0.0)
    assert result.methods["hybrid"].chunks == [make_chunk()]
    assert result.methods["hybrid"].metrics == CaseRetrievalMetrics(1.0, 1.0, 1.0)


def test_empty_rankings_score_zero_for_answerable_cases(pipeline: RunnerMocks) -> None:
    pipeline.dense.return_value = []
    pipeline.sparse.return_value = []
    report = pipeline.run()
    for result in report.cases[0].methods.values():
        assert result.chunks == []
        assert result.metrics == CaseRetrievalMetrics(0.0, 0.0, 0.0)


def test_unanswerable_rankings_are_retained_but_metrics_are_skipped(
    pipeline: RunnerMocks,
) -> None:
    report = pipeline.run([make_unanswerable_case()])
    assert report.cases[0].answerable is False
    for result in report.cases[0].methods.values():
        assert result.chunks
        assert result.metrics is None
    assert all(summary is None for summary in report.summaries.values())


def test_summaries_average_answerable_cases_and_exclude_unanswerable_cases(
    pipeline: RunnerMocks,
) -> None:
    cases = [
        make_case(),
        make_case("question-2", identifier="B1.2"),
        make_unanswerable_case(),
    ]
    report = pipeline.run(cases)
    assert [result.case_id for result in report.cases] == [case.id for case in cases]
    assert pipeline.dense.call_count == pipeline.sparse.call_count == 3
    assert pipeline.contextualize.call_count == pipeline.rerank.call_count == 3
    for method, summary in report.summaries.items():
        assert summary is not None
        assert summary.evaluated_cases == 2
        assert summary.skipped_cases == 1
        assert summary.recall_at_5 == summary.recall_at_10 == 0.5
        assert summary.mrr_at_10 == (0.25 if method == "dense" else 0.5)


@pytest.mark.parametrize(
    ("kind", "identifier"),
    [("clause", "B1.1"), ("appendix", "B1"), ("preamble", "unused")],
)
def test_runner_preserves_and_scores_every_source_kind(
    pipeline: RunnerMocks, kind: SourceKind, identifier: str
) -> None:
    chunk = make_chunk(identifier, kind=kind)
    pipeline.dense.return_value = [DenseHit(chunk, 0.9, DOCUMENT_TITLE)]
    pipeline.sparse.return_value = []
    report = pipeline.run([make_case(kind=kind, identifier=identifier)])
    for result in report.cases[0].methods.values():
        assert result.chunks == [chunk]
        assert result.chunks[0].source_sha256 == "a" * 64
        assert result.metrics == CaseRetrievalMetrics(1.0, 1.0, 1.0)


@pytest.mark.parametrize(
    ("collection_name", "model", "candidate_k", "rrf_k", "message"),
    [
        (" ", "test-model", 20, 60, "Collection name cannot be empty"),
        ("fia_regulations", " ", 20, 60, "Model cannot be empty"),
        ("fia_regulations", "test-model", 0, 60, "candidate_k must be between"),
        ("fia_regulations", "test-model", 9, 60, "candidate_k must be between"),
        ("fia_regulations", "test-model", 21, 60, "candidate_k must be between"),
        ("fia_regulations", "test-model", 20, 0, "rrf_k must be positive"),
        ("fia_regulations", "test-model", 20, -1, "rrf_k must be positive"),
    ],
)
def test_invalid_configuration_fails_before_pipeline_calls(
    pipeline: RunnerMocks,
    collection_name: str,
    model: str,
    candidate_k: int,
    rrf_k: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        pipeline.run(
            collection_name=collection_name,
            model=model,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
        )
    pipeline.assert_no_pipeline_calls()


def test_collection_and_model_whitespace_is_stripped(pipeline: RunnerMocks) -> None:
    report = pipeline.run(collection_name=" fia_regulations ", model=" test-model ")
    assert report.collection_name == "fia_regulations"
    assert report.model == "test-model"
    assert pipeline.dense.call_args.kwargs["collection_name"] == "fia_regulations"
    assert pipeline.contextualize.call_args.kwargs["model"] == "test-model"
    assert pipeline.rerank.call_args.kwargs["model"] == "test-model"


def test_duplicate_labels_in_a_later_case_fail_before_any_api_work(
    pipeline: RunnerMocks,
) -> None:
    invalid = make_case("invalid-question")
    invalid.expected_sources.append(invalid.expected_sources[0].model_copy())
    with pytest.raises(ValueError, match="Expected sources must be unique"):
        pipeline.run([make_case(), invalid])
    pipeline.assert_no_pipeline_calls()


@pytest.mark.parametrize(
    "stage", ["contextualize", "dense", "sparse", "fuse", "rerank"]
)
def test_pipeline_failures_propagate_instead_of_returning_a_fallback_report(
    pipeline: RunnerMocks, stage: str
) -> None:
    error = RuntimeError(f"{stage} failed")
    dependency: Mock = getattr(pipeline, stage)
    dependency.side_effect = error
    with pytest.raises(RuntimeError, match=f"{stage} failed") as exc_info:
        pipeline.run()
    assert exc_info.value is error
