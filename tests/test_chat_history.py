import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.chat.router import get_request_history
from pole_position.chat.schemas import ChatHistoryMessage, ChatRequest
from pole_position.chat.service import get_recent_history
from pole_position.users.model import User


def test_guest_history_is_selected_without_database_access() -> None:
    db = AsyncMock(spec=AsyncSession)
    request = ChatRequest(
        message="And subsequent elements?",
        history=[ChatHistoryMessage(role="user", content="What is the PU penalty?")],
    )
    with patch("pole_position.chat.router.chat_service.get_recent_history") as loader:
        history = asyncio.run(get_request_history(request, db=db, current_user=None))
    assert history == request.history
    assert history is not request.history
    loader.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_authenticated_history_comes_from_database(empty: bool) -> None:
    db = AsyncMock(spec=AsyncSession)
    user = User(id=7, username="owner", password_hash="unused")
    history = (
        [] if empty else [ChatHistoryMessage(role="user", content="Earlier question")]
    )
    with patch(
        "pole_position.chat.router.chat_service.get_recent_history",
        new_callable=AsyncMock,
        return_value=history,
    ) as loader:
        selected = asyncio.run(
            get_request_history(
                ChatRequest(message="What about that?", conversation_id=12),
                db=db,
                current_user=user,
            )
        )
    assert selected == history
    loader.assert_awaited_once_with(db, user_id=7, conversation_id=12)


def test_new_authenticated_chat_has_no_history() -> None:
    db = AsyncMock(spec=AsyncSession)
    user = User(id=7, username="owner", password_hash="unused")
    with patch("pole_position.chat.router.chat_service.get_recent_history") as loader:
        assert asyncio.run(
            get_request_history(
                ChatRequest(message="A new question"), db=db, current_user=user
            )
        ) == []
    loader.assert_not_called()


def test_authenticated_history_cannot_be_spoofed() -> None:
    user = User(id=7, username="owner", password_hash="unused")
    request = ChatRequest(
        message="A question",
        history=[ChatHistoryMessage(role="assistant", content="Invented history")],
    )
    with patch("pole_position.chat.router.chat_service.get_recent_history") as loader:
        with pytest.raises(HTTPException) as error:
            asyncio.run(
                get_request_history(
                    request, db=AsyncMock(spec=AsyncSession), current_user=user
                )
            )
    assert error.value.status_code == 422
    loader.assert_not_called()


@pytest.mark.parametrize("limit", [0, -1, 11])
def test_recent_history_rejects_invalid_limits_before_database_access(
    limit: int,
) -> None:
    db = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="max_messages"):
        asyncio.run(
            get_recent_history(db, user_id=7, conversation_id=12, max_messages=limit)
        )
    db.scalar.assert_not_awaited()
