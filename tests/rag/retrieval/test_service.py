from unittest.mock import Mock, patch

import pytest
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.service import answer_question


def make_hit(clause_identifier: str, page: int) -> DenseHit:
    document_id = "fia-f1-2026-section-b-issue-08"
    chunk = RetrievalChunk(
        chunk_id=f"{document_id}:{clause_identifier}:0",
        document_id=document_id,
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier=clause_identifier,
        chunk_index=0,
        text=f"Regulation text for {clause_identifier}.",
        start_pdf_page=page,
        end_pdf_page=page,
    )
    return DenseHit(chunk=chunk, score=0.9, document_title="Sporting Regulations")


def test_answer_question_orchestrates_retrieval_generation_and_citations() -> None:
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    hits = [make_hit("B8.2.8", 67), make_hit("B8.2.3", 66)]
    draft = "The allocation has consequences [S1]. An exception applies [S2]."

    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=hits,
        ) as retrieve_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value=draft,
        ) as generate_mock,
    ):
        result = answer_question(
            "What happens if a driver exceeds the allocation?",
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name="fia_regulations",
            model="test-model",
            top_k=3,
            section="B",
            max_context_chars=2_000,
        )

    retrieve_mock.assert_called_once_with(
        "What happens if a driver exceeds the allocation?",
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name="fia_regulations",
        top_k=3,
        section="B",
    )
    generate_mock.assert_called_once()
    args, kwargs = generate_mock.call_args
    assert args[0] == "What happens if a driver exceeds the allocation?"
    context = args[1]
    assert context.sources == {"S1": hits[0], "S2": hits[1]}
    assert "Regulation text for B8.2.8." in context.text
    assert "Regulation text for B8.2.3." in context.text
    assert kwargs == {"client": openai_client, "model": "test-model"}
    assert result.answer == draft
    assert [(citation.source_id, citation.hit) for citation in result.citations] == [
        ("S1", hits[0]),
        ("S2", hits[1]),
    ]
    openai_client.responses.create.assert_not_called()
    qdrant_client.query_points.assert_not_called()


def test_answer_question_abstains_without_hits_or_generation_api_call() -> None:
    openai_client = Mock(spec=OpenAI)

    with patch(
        "pole_position.rag.retrieval.service.retrieve_dense", return_value=[]
    ) as retrieve_mock:
        result = answer_question(
            "What is the penalty?",
            openai_client=openai_client,
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="test-model",
        )

    retrieve_mock.assert_called_once()
    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == ()
    openai_client.responses.create.assert_not_called()


def test_answer_question_abstains_on_invalid_generated_citation() -> None:
    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=[make_hit("B8.2.8", 67)],
        ),
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value="Invented claim [S2].",
        ),
    ):
        result = answer_question(
            "What is the penalty?",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="test-model",
        )

    assert result.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert result.citations == ()


@pytest.mark.parametrize(
    (
        "question",
        "collection_name",
        "model",
        "top_k",
        "max_context_chars",
        "message",
    ),
    [
        ("  ", "fia_regulations", "test-model", 5, 12_000, "Question cannot be empty"),
        ("Question", "  ", "test-model", 5, 12_000, "Collection name cannot be empty"),
        ("Question", "fia_regulations", "  ", 5, 12_000, "Model cannot be empty"),
        (
            "Question",
            "fia_regulations",
            "test-model",
            0,
            12_000,
            "top_k must be positive",
        ),
        (
            "Question",
            "fia_regulations",
            "test-model",
            5,
            0,
            "max_context_chars must be positive",
        ),
    ],
)
def test_answer_question_rejects_invalid_input_before_retrieval(
    question: str,
    collection_name: str,
    model: str,
    top_k: int,
    max_context_chars: int,
    message: str,
) -> None:
    with (
        patch("pole_position.rag.retrieval.service.retrieve_dense") as retrieve_mock,
        pytest.raises(ValueError, match=message),
    ):
        answer_question(
            question,
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name=collection_name,
            model=model,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )

    retrieve_mock.assert_not_called()


def test_answer_question_does_not_hide_retrieval_failures() -> None:
    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            side_effect=RuntimeError("Qdrant unavailable"),
        ),
        pytest.raises(RuntimeError, match="Qdrant unavailable"),
    ):
        answer_question(
            "What is the penalty?",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="test-model",
        )
