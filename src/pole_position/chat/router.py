from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from fastapi import (
    Path as PathParameter,
)
from openai import OpenAI
from qdrant_client import QdrantClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from pole_position.auth.dependencies import (
    get_optional_current_user,
    require_current_user,
)
from pole_position.chat import service as chat_service
from pole_position.chat.schemas import (
    ChatRequest,
    ChatResponse,
    Citation,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationUpdateRequest,
)
from pole_position.config import settings
from pole_position.database import get_db
from pole_position.rag.retrieval.service import answer_question
from pole_position.rag.retrieval.sparse import SparseCorpus, load_sparse_corpus
from pole_position.users.model import User

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
async def chat(
    request: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_optional_current_user)],
    openai_client: Annotated[OpenAI, Depends(get_openai_client)],
    qdrant_client: Annotated[QdrantClient, Depends(get_qdrant_client)],
    sparse_corpus: Annotated[SparseCorpus, Depends(get_sparse_corpus)],
) -> ChatResponse:
    if current_user is None and request.conversation_id is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access saved conversations",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if current_user is not None:
        if request.history:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Authenticated requests must omit client-supplied history",
            )
        if request.conversation_id is not None:
            conversation = await chat_service.get_conversation(
                db,
                user_id=current_user.id,
                conversation_id=request.conversation_id,
            )
            if conversation is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conversation not found",
                )

    # History contextualization is the next stage. For now, answer the current
    # message independently, and offload synchronous model/vector calls.
    result = await run_in_threadpool(
        answer_question,
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

    saved_conversation_id: int | None = None
    if current_user is not None:
        saved = await chat_service.save_chat_turn(
            db,
            user_id=current_user.id,
            conversation_id=request.conversation_id,
            message=request.message,
            answer=result.answer,
            citations=citations,
        )
        if saved is None:
            # A conversation may have been deleted while RAG was running.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        saved_conversation_id = saved.id

    return ChatResponse(
        answer=result.answer,
        citations=citations,
        conversation_id=saved_conversation_id,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_saved_conversations(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_current_user)],
) -> list[ConversationResponse]:
    return await chat_service.list_conversations(db, user_id=current_user.id)


@router.get(
    "/conversations/{conversation_id}", response_model=ConversationDetailResponse
)
async def get_saved_conversation(
    conversation_id: Annotated[int, PathParameter(gt=0)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_current_user)],
) -> ConversationDetailResponse:
    conversation = await chat_service.get_conversation(
        db, user_id=current_user.id, conversation_id=conversation_id
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conversation


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_saved_conversation(
    conversation_id: Annotated[int, PathParameter(gt=0)],
    request: ConversationUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_current_user)],
) -> ConversationResponse:
    conversation = await chat_service.rename_conversation(
        db,
        user_id=current_user.id,
        conversation_id=conversation_id,
        title=request.title,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return conversation


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_saved_conversation(
    conversation_id: Annotated[int, PathParameter(gt=0)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(require_current_user)],
) -> Response:
    deleted = await chat_service.delete_conversation(
        db, user_id=current_user.id, conversation_id=conversation_id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
