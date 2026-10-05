from dataclasses import dataclass
from typing import Literal

from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.evaluation.metrics import (
    CaseRetrievalMetrics,
    RetrievalSummary,
    score_retrieval,
    summarize_metrics,
)
from pole_position.rag.evaluation.schemas import (
    EvaluationCategory,
    EvaluationDataset,
)
from pole_position.rag.retrieval.dense import retrieve_dense
from pole_position.rag.retrieval.fusion import fuse_hits
from pole_position.rag.retrieval.query_contextualizer import (
    contextualize_query,
)
from pole_position.rag.retrieval.reranker import (
    MAX_RERANK_CANDIDATES,
    rerank_hits,
)
from pole_position.rag.retrieval.sparse import (
    SparseCorpus,
    retrieve_sparse,
)

type RetrievalMethod = Literal[
    "dense",
    "hybrid",
    "hybrid_reranked",
]


@dataclass(frozen=True)
class MethodEvaluation:
    """One method's ranking and metrics for one question."""

    chunks: list[RetrievalChunk]
    metrics: CaseRetrievalMetrics | None


@dataclass(frozen=True)
class CaseEvaluation:
    """Results for the same question across retrieval methods."""

    case_id: str
    category: EvaluationCategory
    question: str
    retrieval_question: str
    answerable: bool
    methods: dict[RetrievalMethod, MethodEvaluation]


@dataclass(frozen=True)
class EvaluationReport:
    """Per-question results, aggregate metrics, and run configuration."""

    collection_name: str
    model: str
    candidate_k: int
    rrf_k: int
    include_reranking: bool
    cases: list[CaseEvaluation]
    summaries: dict[RetrievalMethod, RetrievalSummary | None]


def run_evaluation(
    dataset: EvaluationDataset,
    *,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    sparse_corpus: SparseCorpus,
    collection_name: str,
    model: str,
    candidate_k: int = 20,
    rrf_k: int = 60,
    include_reranking: bool = True,
) -> EvaluationReport:
    """Compare dense, hybrid, and optionally reranked retrieval."""
    collection_name = collection_name.strip()
    model = model.strip()

    if not collection_name:
        raise ValueError("Collection name cannot be empty")

    if not model:
        raise ValueError("Model cannot be empty")

    # Recall@10 requires at least ten requested candidates.
    # The existing reranker accepts at most twenty.
    if not 10 <= candidate_k <= MAX_RERANK_CANDIDATES:
        raise ValueError(f"candidate_k must be between 10 and {MAX_RERANK_CANDIDATES}")

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    # Validate expected-source uniqueness before making paid API calls.
    for case in dataset.cases:
        score_retrieval(case, [])

    methods: list[RetrievalMethod] = [
        "dense",
        "hybrid",
    ]

    if include_reranking:
        methods.append("hybrid_reranked")

    case_results: list[CaseEvaluation] = []

    for case in dataset.cases:
        # Empty history returns the original question without an API call.
        # Follow-ups are rewritten once and shared by every method.
        retrieval_question = contextualize_query(
            case.question,
            case.history,
            client=openai_client,
            model=model,
        )

        # No section filter: expected sources must not guide retrieval.
        dense_hits = retrieve_dense(
            retrieval_question,
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name=collection_name,
            top_k=candidate_k,
        )

        sparse_hits = retrieve_sparse(
            retrieval_question,
            corpus=sparse_corpus,
            top_k=candidate_k,
        )

        fused_hits = fuse_hits(
            dense_hits,
            sparse_hits,
            top_k=candidate_k,
            rrf_k=rrf_k,
        )

        rankings: dict[RetrievalMethod, list[RetrievalChunk]] = {
            "dense": [hit.chunk for hit in dense_hits],
            "hybrid": [hit.chunk for hit in fused_hits],
        }

        if include_reranking:
            # Keep the full reordered pool so Recall@10 is meaningful.
            # Production chat can still select only five afterward.
            reranked_hits = rerank_hits(
                retrieval_question,
                fused_hits,
                client=openai_client,
                model=model,
                top_k=candidate_k,
            )

            rankings["hybrid_reranked"] = [hit.chunk for hit in reranked_hits]

        method_results: dict[RetrievalMethod, MethodEvaluation] = {
            method: MethodEvaluation(
                chunks=rankings[method],
                metrics=score_retrieval(
                    case,
                    rankings[method],
                ),
            )
            for method in methods
        }

        case_results.append(
            CaseEvaluation(
                case_id=case.id,
                category=case.category,
                question=case.question,
                retrieval_question=retrieval_question,
                answerable=case.answerable,
                methods=method_results,
            )
        )

    summaries: dict[RetrievalMethod, RetrievalSummary | None] = {
        method: summarize_metrics(
            [result.methods[method].metrics for result in case_results]
        )
        for method in methods
    }

    return EvaluationReport(
        collection_name=collection_name,
        model=model,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        include_reranking=include_reranking,
        cases=case_results,
        summaries=summaries,
    )
