from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.schemas import ChatRequest, ChatResponse, Citation
from pole_position.config import settings
from pole_position.rag.retrieval.service import answer_question
from pole_position.rag.retrieval.sparse import SparseCorpus, load_sparse_corpus

router = APIRouter(prefix="/api", tags=["chat"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"
CHUNKS_DIR = PROJECT_ROOT / "artifacts/chunks"


def get_openai_client() -> Iterator[OpenAI]:
    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    try:
        yield client
    finally:
        client.close()


def get_qdrant_client() -> Iterator[QdrantClient]:
    client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value(),
    )
    try:
        yield client
    finally:
        client.close()


@lru_cache(maxsize=1)
def get_sparse_corpus() -> SparseCorpus:
    """Load and index active 2026 chunks once per server process."""
    return load_sparse_corpus(
        manifest_path=MANIFEST_PATH,
        chunks_dir=CHUNKS_DIR,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    openai_client: Annotated[OpenAI, Depends(get_openai_client)],
    qdrant_client: Annotated[QdrantClient, Depends(get_qdrant_client)],
    sparse_corpus: Annotated[SparseCorpus, Depends(get_sparse_corpus)],
) -> ChatResponse:
    result = answer_question(
        request.message,
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name=settings.qdrant_collection,
        model=settings.answer_model,
        sparse_corpus=sparse_corpus,
        rerank_model=settings.answer_model if settings.rerank_enabled else None,
    )

    citations: list[Citation] = []

    for validated_citation in result.citations:
        hit = validated_citation.hit
        chunk = hit.chunk

        citations.append(
            Citation(
                source_id=validated_citation.source_id,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=hit.document_title,
                section=chunk.section,
                source_kind=chunk.source_kind,
                article_identifier=chunk.article_identifier,
                clause_identifier=chunk.clause_identifier,
                appendix_identifier=chunk.appendix_identifier,
                start_pdf_page=chunk.start_pdf_page,
                end_pdf_page=chunk.end_pdf_page,
                snippet=chunk.text,
            )
        )

    return ChatResponse(
        answer=result.answer,
        citations=citations,
        conversation_id=None,
    )
