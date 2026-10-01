from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.chat import service
from pole_position.chat.model import Conversation, Message
from pole_position.chat.schemas import Citation, ConversationResponse
from pole_position.users.model import User


def make_citation() -> Citation:
    return Citation(
        source_id="S1",
        chunk_id="fia-f1-2026-section-b-issue-08:B8.2.8:0",
        document_id="fia-f1-2026-section-b-issue-08",
        document_title="Sporting Regulations",
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier="B8.2.8",
        start_pdf_page=67,
        end_pdf_page=67,
        snippet="The first additional element carries a ten-place grid penalty.",
    )


async def add_user(db: AsyncSession, username: str = "owner") -> User:
    # Authentication is covered separately; this fixture needs only a DB owner.
    user = User(username=username, password_hash="unused-test-hash")
    db.add(user)
    await db.commit()
    return user


async def save_first_turn(
    db: AsyncSession, user_id: int
) -> ConversationResponse:
    response = await service.save_chat_turn(
        db,
        user_id=user_id,
        message="What is the power unit penalty?",
        answer="The first additional element carries a ten-place penalty. [S1]",
        citations=[make_citation()],
    )
    assert response is not None
    return response


def test_conversation_title_is_single_line_and_bounded() -> None:
    assert service.make_conversation_title("  What\n  is the penalty?  ") == (
        "What is the penalty?"
    )
    assert len(service.make_conversation_title("a" * 200)) == 160
    with pytest.raises(ValueError):
        service.make_conversation_title(" \n ")


def test_save_and_load_conversation_with_citations(
    db_client: tuple[TestClient, AsyncSession],
) -> None:
    client, db = db_client

    async def check() -> None:
        user = await add_user(db)
        saved = await save_first_turn(db, user.id)
        assert saved.title == "What is the power unit penalty?"
        detail = await service.get_conversation(
            db, user_id=user.id, conversation_id=saved.id
        )
        assert detail is not None
        assert [message.role for message in detail.messages] == ["user", "assistant"]
        assert detail.messages[0].citations == []
        assert detail.messages[1].citations == [make_citation()]
        assert all(message.conversation_id == saved.id for message in detail.messages)
        # Responses are serializable without accessing ORM relationships.
        assert detail.model_dump(mode="json")["messages"][1]["citations"][0] == (
            make_citation().model_dump(mode="json")
        )
        assert "user_id" not in detail.model_dump()

    assert client.portal is not None
    client.portal.call(check)


def test_follow_up_turn_preserves_title_and_message_order(
    db_client: tuple[TestClient, AsyncSession],
) -> None:
    client, db = db_client

    async def check() -> None:
        user = await add_user(db)
        first = await save_first_turn(db, user.id)
        second = await service.save_chat_turn(
            db,
            user_id=user.id,
            conversation_id=first.id,
            message="And a subsequent extra element?",
            answer="A subsequent extra element carries a five-place penalty. [S1]",
            citations=[make_citation()],
        )
        assert second is not None
        assert second.id == first.id
        assert second.title == first.title
        assert second.updated_at >= first.updated_at
        detail = await service.get_conversation(
            db, user_id=user.id, conversation_id=first.id
        )
        assert detail is not None
        assert [message.role for message in detail.messages] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert detail.messages[2].content == "And a subsequent extra element?"
        assert [message.id for message in detail.messages] == sorted(
            message.id for message in detail.messages
        )
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 1

    assert client.portal is not None
    client.portal.call(check)


def test_list_conversations_is_owned_and_recent_first(
    db_client: tuple[TestClient, AsyncSession],
) -> None:
    client, db = db_client

    async def check() -> None:
        owner = await add_user(db)
        other = await add_user(db, "other")
        first = await save_first_turn(db, owner.id)
        second = await save_first_turn(db, owner.id)
        await save_first_turn(db, other.id)
        old = await db.get(Conversation, first.id)
        assert old is not None
        old.updated_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()
        listed = await service.list_conversations(db, user_id=owner.id)
        assert [item.id for item in listed] == [second.id, first.id]
        assert len(await service.list_conversations(db, user_id=other.id)) == 1
        empty_user = await add_user(db, "empty")
        assert await service.list_conversations(db, user_id=empty_user.id) == []

    assert client.portal is not None
    client.portal.call(check)


@pytest.mark.parametrize("missing", [False, True])
def test_missing_and_unowned_conversations_cannot_be_accessed_or_modified(
    db_client: tuple[TestClient, AsyncSession], missing: bool
) -> None:
    client, db = db_client

    async def check() -> None:
        owner = await add_user(db)
        other = await add_user(db, "other")
        saved = await save_first_turn(db, owner.id)
        requested_id = saved.id + 1000 if missing else saved.id
        assert await service.get_conversation(
            db, user_id=other.id, conversation_id=requested_id
        ) is None
        assert await service.rename_conversation(
            db, user_id=other.id, conversation_id=requested_id, title="Not mine"
        ) is None
        assert await service.save_chat_turn(
            db,
            user_id=other.id,
            conversation_id=requested_id,
            message="Not mine",
            answer="This must not be saved.",
            citations=[],
        ) is None
        assert not await service.delete_conversation(
            db, user_id=other.id, conversation_id=requested_id
        )
        detail = await service.get_conversation(
            db, user_id=owner.id, conversation_id=saved.id
        )
        assert detail is not None
        assert detail.title == saved.title
        assert len(detail.messages) == 2

    assert client.portal is not None
    client.portal.call(check)


def test_rename_and_delete_conversation_with_messages(
    db_client: tuple[TestClient, AsyncSession],
) -> None:
    client, db = db_client

    async def check() -> None:
        user = await add_user(db)
        saved = await save_first_turn(db, user.id)
        renamed = await service.rename_conversation(
            db, user_id=user.id, conversation_id=saved.id, title="  Power unit rules  "
        )
        assert renamed is not None
        assert renamed.title == "Power unit rules"
        assert renamed.updated_at >= saved.updated_at
        assert await service.delete_conversation(
            db, user_id=user.id, conversation_id=saved.id
        )
        assert await service.get_conversation(
            db, user_id=user.id, conversation_id=saved.id
        ) is None
        assert await db.scalar(select(func.count()).select_from(Message)) == 0
        assert await db.scalar(select(func.count()).select_from(User)) == 1

    assert client.portal is not None
    client.portal.call(check)


@pytest.mark.parametrize("existing", [False, True])
def test_failed_commit_rolls_back_the_whole_turn(
    db_client: tuple[TestClient, AsyncSession], existing: bool
) -> None:
    client, db = db_client

    async def check() -> None:
        user = await add_user(db)
        # Rollback expires ORM objects, so keep IDs as plain values.
        user_id = user.id
        saved = await save_first_turn(db, user_id) if existing else None
        with patch.object(
            db, "commit", new=AsyncMock(side_effect=RuntimeError("Simulated failure"))
        ):
            with pytest.raises(RuntimeError, match="Simulated failure"):
                await service.save_chat_turn(
                    db,
                    user_id=user_id,
                    conversation_id=saved.id if saved else None,
                    message="A new question",
                    answer="A new answer",
                    citations=[],
                )
        assert await db.scalar(select(func.count()).select_from(Conversation)) == (
            1 if existing else 0
        )
        assert await db.scalar(select(func.count()).select_from(Message)) == (
            2 if existing else 0
        )
        if saved:
            restored = await service.get_conversation(
                db, user_id=user_id, conversation_id=saved.id
            )
            assert restored is not None
            assert restored.updated_at == saved.updated_at

    assert client.portal is not None
    client.portal.call(check)


@pytest.mark.parametrize("title", ["   ", "x" * 161])
def test_rename_rejects_invalid_titles(
    db_client: tuple[TestClient, AsyncSession], title: str
) -> None:
    client, db = db_client

    async def check() -> None:
        user = await add_user(db)
        saved = await save_first_turn(db, user.id)
        with pytest.raises(ValidationError):
            await service.rename_conversation(
                db, user_id=user.id, conversation_id=saved.id, title=title
            )
        unchanged = await service.get_conversation(
            db, user_id=user.id, conversation_id=saved.id
        )
        assert unchanged is not None
        assert unchanged.title == saved.title

    assert client.portal is not None
    client.portal.call(check)
