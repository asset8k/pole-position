from collections.abc import Iterator
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.router import (
    CHUNKS_DIR,
    MANIFEST_PATH,
    _sparse_corpus_for_manifest,
    get_openai_client,
    get_qdrant_client,
    get_sparse_corpus,
)
from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.config import settings
from pole_position.corpus.manifest import load_manifest
from pole_position.corpus.schemas import CorpusManifest
from pole_position.main import app
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.citations import ValidatedAnswer, ValidatedCitation
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.sparse import SparseCorpus


@pytest.fixture
def client() -> Iterator[tuple[TestClient, Mock, Mock, Mock]]:
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    sparse_corpus = Mock(spec=SparseCorpus)
    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_openai_client] = lambda: openai_client
    app.dependency_overrides[get_qdrant_client] = lambda: qdrant_client
    app.dependency_overrides[get_sparse_corpus] = lambda: sparse_corpus

    try:
        with TestClient(app) as test_client:
            yield test_client, openai_client, qdrant_client, sparse_corpus
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
    client: tuple[TestClient, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_enabled", True)
    test_client, openai_client, qdrant_client, sparse_corpus = client
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
        history=[],
        sparse_corpus=sparse_corpus,
        rerank_model=settings.answer_model,
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


def test_guest_chat_passes_history_to_rag(
    client: tuple[TestClient, Mock, Mock, Mock],
) -> None:
    test_client, _, _, _ = client
    history = [
        ChatHistoryMessage(role="user", content="What is the PU penalty?"),
        ChatHistoryMessage(role="assistant", content="Ten places for the first one."),
    ]
    with patch(
        "pole_position.chat.router.answer_question", return_value=make_answer()
    ) as answer_mock:
        response = test_client.post(
            "/api/chat",
            json={
                "message": "And subsequent ones?",
                "history": [item.model_dump() for item in history],
            },
        )

    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    assert answer_mock.call_args.args == ("And subsequent ones?",)
    assert answer_mock.call_args.kwargs["history"] == history


def test_chat_can_disable_reranking(
    client: tuple[TestClient, Mock, Mock, Mock],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "rerank_enabled", False)
    test_client, _, _, _ = client

    with patch(
        "pole_position.chat.router.answer_question",
        return_value=make_answer(),
    ) as answer_mock:
        response = test_client.post("/api/chat", json={"message": "What is the penalty?"})

    assert response.status_code == 200
    assert answer_mock.call_args.kwargs["rerank_model"] is None


def test_chat_returns_uncited_abstention(
    client: tuple[TestClient, Mock, Mock, Mock],
) -> None:
    test_client, _, _, _ = client
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
    client: tuple[TestClient, Mock, Mock, Mock],
    body: dict[str, object],
) -> None:
    test_client, _, _, _ = client

    with patch("pole_position.chat.router.answer_question") as answer_mock:
        response = test_client.post("/api/chat", json=body)

    assert response.status_code == 422
    answer_mock.assert_not_called()


def test_sparse_corpus_is_cached_for_unchanged_manifest() -> None:
    sparse_corpus = Mock(spec=SparseCorpus)
    _sparse_corpus_for_manifest.cache_clear()

    try:
        with patch(
            "pole_position.chat.router.load_sparse_corpus",
            return_value=sparse_corpus,
        ) as load_mock:
            assert get_sparse_corpus() is sparse_corpus
            assert get_sparse_corpus() is sparse_corpus

        load_mock.assert_called_once_with(
            manifest_path=MANIFEST_PATH,
            chunks_dir=CHUNKS_DIR,
            manifest=load_manifest(MANIFEST_PATH),
        )
    finally:
        _sparse_corpus_for_manifest.cache_clear()


def test_sparse_corpus_refreshes_when_manifest_changes(tmp_path, monkeypatch) -> None:
    from pole_position.chat import router as chat_router

    manifest = load_manifest(MANIFEST_PATH)
    path = tmp_path / "manifest.json"
    path.write_text(manifest.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(chat_router, "MANIFEST_PATH", path)
    first, second = Mock(spec=SparseCorpus), Mock(spec=SparseCorpus)
    _sparse_corpus_for_manifest.cache_clear()
    try:
        with patch.object(chat_router, "load_sparse_corpus", side_effect=[first, second]) as loader:
            assert get_sparse_corpus() is first
            assert get_sparse_corpus() is first
            documents = list(manifest.documents)
            documents[0] = documents[0].model_copy(update={"document_id": "new-version"})
            updated = CorpusManifest(documents=documents)
            path.write_text(updated.model_dump_json(), encoding="utf-8")
            assert get_sparse_corpus() is second
            assert get_sparse_corpus() is second
            assert loader.call_count == 2
            assert loader.call_args.kwargs["manifest"] == updated
    finally:
        _sparse_corpus_for_manifest.cache_clear()
