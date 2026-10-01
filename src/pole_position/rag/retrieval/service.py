import logging
from collections.abc import Sequence

from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.corpus.schemas import RegulationSection
from pole_position.rag.generation.answer_generator import generate_draft_answer
from pole_position.rag.generation.citations import (
    CitationValidationError,
    ValidatedAnswer,
    validate_citations,
)
from pole_position.rag.generation.context_builder import (
    DEFAULT_MAX_CONTEXT_CHARS,
    EvidenceHit,
    build_context,
)
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import retrieve_dense
from pole_position.rag.retrieval.fusion import fuse_hits
from pole_position.rag.retrieval.query_contextualizer import contextualize_query
from pole_position.rag.retrieval.reranker import (
    MAX_RERANK_CANDIDATES,
    rerank_hits,
)
from pole_position.rag.retrieval.sparse import SparseCorpus, retrieve_sparse

logger = logging.getLogger(__name__)


def answer_question(
    question: str,
    *,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    model: str,
    history: Sequence[ChatHistoryMessage] = (),
    sparse_corpus: SparseCorpus | None = None,
    rerank_model: str | None = None,
    top_k: int = 5,
    section: RegulationSection | None = None,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> ValidatedAnswer:
    """Resolve a follow-up, retrieve evidence, and validate the grounded answer.

    History is chronological and excludes the latest question. It is used
    only to rewrite that question, never as authoritative regulation evidence.
    """

    if not question.strip():
        raise ValueError("Question cannot be empty")
    if not collection_name.strip():
        raise ValueError("Collection name cannot be empty")
    if not model.strip():
        raise ValueError("Model cannot be empty")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if max_context_chars <= 0:
        raise ValueError("max_context_chars must be positive")

    if rerank_model is not None:
        if not rerank_model.strip():
            raise ValueError("Rerank model cannot be empty")
        if sparse_corpus is None:
            raise ValueError("Reranking requires a sparse corpus")
        if top_k > MAX_RERANK_CANDIDATES:
            raise ValueError(
                f"Reranking supports at most {MAX_RERANK_CANDIDATES} final hits"
            )

    standalone_question = contextualize_query(
        question,
        history,
        client=openai_client,
        model=model,
    )

    candidate_k = max(20, top_k) if sparse_corpus is not None else top_k

    dense_hits = retrieve_dense(
        standalone_question,
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name=collection_name,
        top_k=candidate_k,
        section=section,
    )

    hits: Sequence[EvidenceHit] = dense_hits

    if sparse_corpus is not None:
        sparse_hits = retrieve_sparse(
            standalone_question,
            corpus=sparse_corpus,
            top_k=candidate_k,
            section=section,
        )

        # Without reranking, fusion selects the final hits immediately.
        # With reranking, retain the larger candidate pool.
        fused_hits = fuse_hits(
            dense_hits,
            sparse_hits,
            top_k=candidate_k if rerank_model is not None else top_k,
        )

        if rerank_model is not None:
            try:
                hits = rerank_hits(
                    standalone_question,
                    fused_hits,
                    client=openai_client,
                    model=rerank_model,
                    top_k=top_k,
                )
            except Exception:
                logger.warning("Reranking failed; using fused results", exc_info=True)
                hits = fused_hits[:top_k]
        else:
            hits = fused_hits

    context = build_context(hits, max_chars=max_context_chars)

    draft = generate_draft_answer(
        standalone_question,
        context,
        client=openai_client,
        model=model,
    )

    try:
        return validate_citations(draft, context)
    except CitationValidationError:
        logger.warning("Generated answer failed citation validation", exc_info=True)
        return validate_citations(INSUFFICIENT_EVIDENCE_ANSWER, context)
