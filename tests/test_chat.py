from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.router import get_openai_client, get_qdrant_client
from pole_position.config import settings
from pole_position.main import app
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.citations import ValidatedAnswer, ValidatedCitation
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import DenseHit


@pytest.fixture
def client() -> Iterator[tuple[TestClient, Mock, Mock]]:
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_openai_client] = lambda: openai_client
    app.dependency_overrides[get_qdrant_client] = lambda: qdrant_client

    try:
        with TestClient(app) as test_client:
            yield test_client, openai_client, qdrant_client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


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
        answer="The first additional element carries a ten-place penalty [S1].",
        citations=(ValidatedCitation(source_id="S1", hit=hit),),
    )


def test_chat_returns_grounded_answer_and_citation(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, openai_client, qdrant_client = client
    answer = make_answer()

    with patch(
        "pole_position.chat.router.answer_question", return_value=answer
    ) as answer_mock:
        response = test_client.post(
            "/api/chat", json={"message": "  What is the power unit penalty?  "}
        )

    assert response.status_code == 200
    answer_mock.assert_called_once_with(
        "What is the power unit penalty?",
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name=settings.qdrant_collection,
        model=settings.answer_model,
    )
    assert response.json() == {
        "answer": answer.answer,
        "citations": [
            {
                "source_id": "S1",
                "chunk_id": "fia-f1-2026-section-b-issue-08:B8.2.8:0",
                "document_id": "fia-f1-2026-section-b-issue-08",
                "document_title": "Sporting Regulations",
                "section": "B",
                "source_kind": "clause",
                "article_identifier": "B8",
                "clause_identifier": "B8.2.8",
                "appendix_identifier": None,
                "start_pdf_page": 67,
                "end_pdf_page": 67,
                "snippet": (
                    "The first additional element carries a ten-place grid penalty."
                ),
            }
        ],
        "conversation_id": None,
    }


def test_chat_returns_uncited_abstention(
    client: tuple[TestClient, Mock, Mock],
) -> None:
    test_client, _, _ = client
    answer = ValidatedAnswer(answer=INSUFFICIENT_EVIDENCE_ANSWER, citations=())

    with patch("pole_position.chat.router.answer_question", return_value=answer):
        response = test_client.post("/api/chat", json={"message": "Unknown rule?"})

    assert response.status_code == 200
    assert response.json() == {
        "answer": INSUFFICIENT_EVIDENCE_ANSWER,
        "citations": [],
        "conversation_id": None,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"message": "   "},
        {"message": "x" * 4_001},
        {"message": "Valid question", "unexpected": True},
    ],
)
def test_chat_rejects_invalid_request_before_answering(
    client: tuple[TestClient, Mock, Mock],
    body: dict[str, object],
) -> None:
    test_client, _, _ = client

    with patch("pole_position.chat.router.answer_question") as answer_mock:
        response = test_client.post("/api/chat", json=body)

    assert response.status_code == 422
    answer_mock.assert_not_called()
