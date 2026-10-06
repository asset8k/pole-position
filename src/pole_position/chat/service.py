from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.chat.model import Conversation, Message
from pole_position.chat.schemas import (
    ChatHistoryMessage,
    ChatRequest,
    Citation,
    ConversationDetailResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageResponse,
)
from pole_position.users.model import User  # noqa: F401


def make_conversation_title(first_message: str) -> str:
    """Derive a short, single-line title without an additional model call."""
    title = " ".join(first_message.split())
    if not title:
        raise ValueError("First message cannot be empty")
    return title if len(title) <= 50 else title[:49].rstrip() + "…"


async def _find_owned_conversation(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    for_update: bool = False,
) -> Conversation | None:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.user_id == user_id,
    )
    if for_update:
        # Serialize writes to the same thread; this lock is taken after RAG.
        statement = statement.with_for_update()
    return await db.scalar(statement.execution_options(populate_existing=True))


async def list_conversations(
    db: AsyncSession, *, user_id: int
) -> list[ConversationResponse]:
    """List only this user's conversations, most recently updated first."""
    result = await db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return [ConversationResponse.model_validate(item) for item in result]


async def get_conversation(
    db: AsyncSession, *, user_id: int, conversation_id: int
) -> ConversationDetailResponse | None:
    """Load an owned thread and its messages without async lazy loading."""
    conversation = await _find_owned_conversation(
        db, user_id=user_id, conversation_id=conversation_id
    )
    if conversation is None:
        return None

    messages = await db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(item) for item in messages],
    )


async def get_recent_history(
    db: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
    max_messages: int = 10,
) -> list[ChatHistoryMessage] | None:
    """Read a bounded history window, without changing the saved thread.

    None means missing or unowned; [] means an owned but empty conversation.
    Citation payloads are not needed for question contextualization.
    """
    if not 1 <= max_messages <= 10:
        raise ValueError("max_messages must be between 1 and 10")

    conversation = await _find_owned_conversation(
        db, user_id=user_id, conversation_id=conversation_id
    )
    if conversation is None:
        return None

    result = await db.execute(
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(max_messages)
    )
    # Select newest first so LIMIT keeps the latest messages, then restore
    # chronological order. Truncate only the model's copy, never stored text.
    return [
        ChatHistoryMessage.model_validate(
            {"role": role, "content": content[:8_000]}
        )
        for role, content in reversed(result.all())
    ]


async def save_chat_turn(
    db: AsyncSession,
    *,
    user_id: int,
    message: str,
    answer: str,
    citations: Sequence[Citation],
    conversation_id: int | None = None,
    title: str | None = None,
) -> ConversationResponse | None:
    """Save a completed turn for an authenticated user, atomically.

    The router must obtain user_id from authentication, not the request body,
    and check ownership before running RAG for an existing conversation.
    This function checks ownership again before writing. Guests never call it.
    """
    message = ChatRequest(message=message).message
    answer = answer.strip()
    if not answer:
        raise ValueError("Answer cannot be empty")
    citation_payloads = [citation.model_dump(mode="json") for citation in citations]

    try:
        if conversation_id is None:
            conversation = Conversation(
                user_id=user_id,
                title=(
                    ConversationUpdateRequest(title=title).title
                    if title is not None
                    else make_conversation_title(message)
                ),
            )
            db.add(conversation)
            await db.flush()
        else:
            conversation = await _find_owned_conversation(
                db,
                user_id=user_id,
                conversation_id=conversation_id,
                for_update=True,
            )
            if conversation is None:
                return None

        # Inserting messages alone does not trigger Conversation.onupdate.
        conversation.updated_at = datetime.now(UTC)
        db.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    role="user",
                    content=message,
                    citations=[],
                ),
                Message(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=answer,
                    citations=citation_payloads,
                ),
            ]
        )
        await db.flush()
        response = ConversationResponse.model_validate(conversation)
        await db.commit()
        return response
    except Exception:
        await db.rollback()
        raise


async def rename_conversation(
    db: AsyncSession, *, user_id: int, conversation_id: int, title: str
) -> ConversationResponse | None:
    """Rename only an owned conversation; validate the database title limit."""
    title = ConversationUpdateRequest(title=title).title
    try:
        conversation = await _find_owned_conversation(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            for_update=True,
        )
        if conversation is None:
            return None

        conversation.title = title
        conversation.updated_at = datetime.now(UTC)
        await db.flush()
        response = ConversationResponse.model_validate(conversation)
        await db.commit()
        return response
    except Exception:
        await db.rollback()
        raise


async def delete_conversation(
    db: AsyncSession, *, user_id: int, conversation_id: int
) -> bool:
    """Delete an owned conversation and its messages via the ORM cascade."""
    try:
        conversation = await _find_owned_conversation(
            db,
            user_id=user_id,
            conversation_id=conversation_id,
            for_update=True,
        )
        if conversation is None:
            return False

        await db.delete(conversation)
        await db.commit()
        return True
    except Exception:
        await db.rollback()
        raise
