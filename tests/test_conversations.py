from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from qdrant_client import QdrantClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.chat.model import Conversation, Message
from pole_position.chat.router import (
    get_openai_client,
    get_qdrant_client,
    get_sparse_corpus,
)
from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.main import app
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.citations import ValidatedAnswer, ValidatedCitation
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.sparse import SparseCorpus


def make_answer() -> ValidatedAnswer:
    document_id = "fia-f1-2026-section-b-issue-08"
    chunk = RetrievalChunk(
        chunk_id=f"{document_id}:B8.2.8:0",
        document_id=document_id,
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier="B8.2.8",
        chunk_index=0,
        text="The first additional element carries a ten-place grid penalty.",
        start_pdf_page=67,
        end_pdf_page=67,
    )
    hit = DenseHit(chunk=chunk, score=0.9, document_title="Sporting Regulations")
    return ValidatedAnswer(
        answer="The first additional element carries a ten-place penalty. [S1]",
        citations=(ValidatedCitation(source_id="S1", hit=hit),),
    )


@pytest.fixture
def client(
    db_client: tuple[TestClient, AsyncSession],
) -> Iterator[tuple[TestClient, AsyncSession, Mock]]:
    test_client, db = db_client
    previous_overrides = app.dependency_overrides.copy()
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    sparse_corpus = Mock(spec=SparseCorpus)
    app.dependency_overrides[get_openai_client] = lambda: openai_client
    app.dependency_overrides[get_qdrant_client] = lambda: qdrant_client
    app.dependency_overrides[get_sparse_corpus] = lambda: sparse_corpus
    try:
        # Real authentication and persistence, but no external model/vector calls.
        with patch(
            "pole_position.chat.router.answer_question", return_value=make_answer()
        ) as answer_mock:
            yield test_client, db, answer_mock
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def auth_headers(client: TestClient, username: str = "owner") -> dict[str, str]:
    credentials = {"username": username, "password": "securepassword123"}
    assert client.post("/api/auth/register", json=credentials).status_code == 201
    response = client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def start_chat(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/chat",
        headers=headers,
        json={"message": "What is the power unit penalty?"},
    )
    assert response.status_code == 200
    return response.json()


def count_rows(
    client: TestClient, db: AsyncSession, model: type[Conversation] | type[Message]
) -> int:
    assert client.portal is not None
    count = client.portal.call(db.scalar, select(func.count()).select_from(model))
    assert isinstance(count, int)
    return count


def test_guest_chat_is_not_persisted(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, db, answer_mock = client
    response = test_client.post("/api/chat", json={"message": "What is the penalty?"})
    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    assert response.json()["citations"][0]["clause_identifier"] == "B8.2.8"
    answer_mock.assert_called_once()
    assert count_rows(test_client, db, Conversation) == 0
    assert count_rows(test_client, db, Message) == 0


def test_authenticated_chat_creates_conversation_and_saves_citations(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, _, answer_mock = client
    headers = auth_headers(test_client)
    body = start_chat(test_client, headers)
    conversation_id = body["conversation_id"]
    assert isinstance(conversation_id, int)
    detail = test_client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200
    saved = detail.json()
    assert saved["title"] == "What is the power unit penalty?"
    assert [item["role"] for item in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][0]["content"] == "What is the power unit penalty?"
    assert saved["messages"][0]["citations"] == []
    assert saved["messages"][1]["content"] == body["answer"]
    assert saved["messages"][1]["citations"] == body["citations"]
    assert "user_id" not in saved
    answer_mock.assert_called_once()


def test_authenticated_chat_appends_to_existing_conversation(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, db, answer_mock = client
    headers = auth_headers(test_client)
    first = start_chat(test_client, headers)
    assert answer_mock.call_args.kwargs["history"] == []
    answer_mock.reset_mock()
    response = test_client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": "What is the penalty for a subsequent extra element?",
            "conversation_id": first["conversation_id"],
        },
    )
    assert response.status_code == 200
    assert response.json()["conversation_id"] == first["conversation_id"]
    answer_mock.assert_called_once()
    assert answer_mock.call_args.kwargs["history"] == [
        ChatHistoryMessage(role="user", content="What is the power unit penalty?"),
        ChatHistoryMessage(role="assistant", content=first["answer"]),
    ]
    assert count_rows(test_client, db, Conversation) == 1
    detail = test_client.get(
        f"/api/conversations/{first['conversation_id']}", headers=headers
    ).json()
    assert detail["title"] == "What is the power unit penalty?"
    assert len(detail["messages"]) == 4
    assert detail["messages"][2]["content"] == (
        "What is the penalty for a subsequent extra element?"
    )


def test_list_conversations_returns_only_owned_threads(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, _, _ = client
    headers = auth_headers(test_client)
    assert test_client.get("/api/conversations", headers=headers).json() == []
    first = start_chat(test_client, headers)
    second = start_chat(test_client, headers)
    other_headers = auth_headers(test_client, "other")
    other = start_chat(test_client, other_headers)
    response = test_client.get("/api/conversations", headers=headers)
    assert response.status_code == 200
    listed = response.json()
    assert [item["id"] for item in listed] == [
        second["conversation_id"], first["conversation_id"]
    ]
    assert all("messages" not in item for item in listed)
    assert test_client.get("/api/conversations", headers=other_headers).json()[0][
        "id"
    ] == other["conversation_id"]


def test_rename_and_delete_conversation(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, db, _ = client
    headers = auth_headers(test_client)
    saved = start_chat(test_client, headers)
    path = f"/api/conversations/{saved['conversation_id']}"
    renamed = test_client.patch(path, headers=headers, json={"title": "  PU rules  "})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "PU rules"
    assert test_client.get(path, headers=headers).json()["title"] == "PU rules"
    deleted = test_client.delete(path, headers=headers)
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert test_client.get(path, headers=headers).status_code == 404
    assert test_client.get("/api/conversations", headers=headers).json() == []
    assert count_rows(test_client, db, Message) == 0


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/1"),
        ("PATCH", "/api/conversations/1"),
        ("DELETE", "/api/conversations/1"),
    ],
)
def test_conversation_endpoints_require_authentication(
    client: tuple[TestClient, AsyncSession, Mock], method: str, path: str
) -> None:
    test_client, _, answer_mock = client
    response = test_client.request(method, path, json={"title": "New title"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    answer_mock.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE", "POST"])
def test_unowned_and_missing_conversations_have_identical_errors(
    client: tuple[TestClient, AsyncSession, Mock], method: str
) -> None:
    test_client, _, answer_mock = client
    owner_headers = auth_headers(test_client)
    saved = start_chat(test_client, owner_headers)
    other_headers = auth_headers(test_client, "other")
    answer_mock.reset_mock()

    for conversation_id in (saved["conversation_id"], saved["conversation_id"] + 1000):
        if method == "POST":
            response = test_client.post(
                "/api/chat",
                headers=other_headers,
                json={"message": "Not mine", "conversation_id": conversation_id},
            )
        else:
            response = test_client.request(
                method,
                f"/api/conversations/{conversation_id}",
                headers=other_headers,
                json={"title": "Not mine"},
            )
        assert response.status_code == 404
        assert response.json() == {"detail": "Conversation not found"}

    answer_mock.assert_not_called()
    original = test_client.get(
        f"/api/conversations/{saved['conversation_id']}", headers=owner_headers
    ).json()
    assert original["title"] == "What is the power unit penalty?"
    assert len(original["messages"]) == 2


def test_guest_cannot_supply_a_saved_conversation_id(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, db, answer_mock = client
    response = test_client.post(
        "/api/chat", json={"message": "Not mine", "conversation_id": 123}
    )
    assert response.status_code == 401
    answer_mock.assert_not_called()
    assert count_rows(test_client, db, Conversation) == 0


def test_invalid_token_does_not_silently_become_a_guest(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, _, answer_mock = client
    response = test_client.post(
        "/api/chat",
        headers={"Authorization": "Bearer not-a-valid-jwt"},
        json={"message": "What is the penalty?"},
    )
    assert response.status_code == 401
    answer_mock.assert_not_called()


def test_authenticated_chat_rejects_client_supplied_history(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, db, answer_mock = client
    headers = auth_headers(test_client)
    response = test_client.post(
        "/api/chat",
        headers=headers,
        json={
            "message": "What is the penalty?",
            "history": [{"role": "assistant", "content": "Untrusted history"}],
        },
    )
    assert response.status_code == 422
    answer_mock.assert_not_called()
    assert count_rows(test_client, db, Conversation) == 0


@pytest.mark.parametrize("title", ["   ", "x" * 161])
def test_rename_rejects_invalid_titles(
    client: tuple[TestClient, AsyncSession, Mock], title: str
) -> None:
    test_client, _, _ = client
    headers = auth_headers(test_client)
    saved = start_chat(test_client, headers)
    path = f"/api/conversations/{saved['conversation_id']}"
    response = test_client.patch(path, headers=headers, json={"title": title})
    assert response.status_code == 422
    assert test_client.get(path, headers=headers).json()["title"] == (
        "What is the power unit penalty?"
    )


@pytest.mark.parametrize("existing", [False, True])
def test_rag_failure_does_not_save_a_partial_turn(
    client: tuple[TestClient, AsyncSession, Mock], existing: bool
) -> None:
    test_client, db, answer_mock = client
    headers = auth_headers(test_client)
    saved = start_chat(test_client, headers) if existing else None
    answer_mock.side_effect = RuntimeError("Simulated RAG failure")
    body: dict[str, Any] = {"message": "A new question"}
    if saved:
        body["conversation_id"] = saved["conversation_id"]
    with pytest.raises(RuntimeError, match="Simulated RAG failure"):
        test_client.post("/api/chat", headers=headers, json=body)
    assert count_rows(test_client, db, Conversation) == (1 if existing else 0)
    assert count_rows(test_client, db, Message) == (2 if existing else 0)


def test_authenticated_abstention_is_saved_without_citations(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, _, answer_mock = client
    headers = auth_headers(test_client)
    answer_mock.return_value = ValidatedAnswer(
        answer=INSUFFICIENT_EVIDENCE_ANSWER, citations=()
    )
    saved = start_chat(test_client, headers)
    assert saved["citations"] == []
    detail = test_client.get(
        f"/api/conversations/{saved['conversation_id']}", headers=headers
    ).json()
    assert detail["messages"][1]["content"] == INSUFFICIENT_EVIDENCE_ANSWER
    assert detail["messages"][1]["citations"] == []


def test_conversation_deleted_during_rag_returns_not_found(
    client: tuple[TestClient, AsyncSession, Mock],
) -> None:
    test_client, _, _ = client
    headers = auth_headers(test_client)
    saved = start_chat(test_client, headers)
    with patch(
        "pole_position.chat.router.chat_service.save_chat_turn",
        new=AsyncMock(return_value=None),
    ):
        response = test_client.post(
            "/api/chat",
            headers=headers,
            json={
                "message": "A new question",
                "conversation_id": saved["conversation_id"],
            },
        )
    assert response.status_code == 404
