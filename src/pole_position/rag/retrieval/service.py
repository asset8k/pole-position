import logging
from collections.abc import Sequence

from openai import OpenAI
from qdrant_client import QdrantClient

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
from pole_position.rag.retrieval.sparse import (
    SparseCorpus,
    retrieve_sparse,
)

logger = logging.getLogger(__name__)


def answer_question(
    question: str,
    *,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    model: str,
    sparse_corpus: SparseCorpus | None = None,
    top_k: int = 5,
    section: RegulationSection | None = None,
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> ValidatedAnswer:
    """Retrieve regulation evidence and produce a citation-validated answer."""

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

    # Hybrid search needs more candidates from each method than the number
    # ultimately sent to the answer generator.
    candidate_k = max(20, top_k) if sparse_corpus is not None else top_k

    dense_hits = retrieve_dense(
        question,
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name=collection_name,
        top_k=candidate_k,
        section=section,
    )

    hits: Sequence[EvidenceHit] = dense_hits

    if sparse_corpus is not None:
        sparse_hits = retrieve_sparse(
            question,
            corpus=sparse_corpus,
            top_k=candidate_k,
            section=section,
        )
        hits = fuse_hits(dense_hits, sparse_hits, top_k=top_k)

    context = build_context(hits, max_chars=max_context_chars)

    draft = generate_draft_answer(
        question,
        context,
        client=openai_client,
        model=model,
    )

    try:
        return validate_citations(draft, context)
    except CitationValidationError:
        logger.warning("Generated answer failed citation validation", exc_info=True)
        return validate_citations(INSUFFICIENT_EVIDENCE_ANSWER, context)
