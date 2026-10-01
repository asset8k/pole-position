import json
from collections.abc import Sequence
from unittest.mock import Mock, patch

import pytest
from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.chat.schemas import ChatHistoryMessage
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.prompts import INSUFFICIENT_EVIDENCE_ANSWER
from pole_position.rag.retrieval.dense import DenseHit
from pole_position.rag.retrieval.fusion import FusedHit
from pole_position.rag.retrieval.query_contextualizer import ContextualizedQuery
from pole_position.rag.retrieval.service import answer_question
from pole_position.rag.retrieval.sparse import SparseCorpus, SparseHit


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
    openai_client.responses.parse.assert_not_called()
    qdrant_client.query_points.assert_not_called()


def test_follow_up_rewrite_reaches_all_rag_stages_without_history_as_evidence() -> None:
    openai_client = Mock(spec=OpenAI)
    standalone_question = "What is the penalty for subsequent extra PU elements?"
    openai_client.responses.parse.return_value = Mock(
        status="completed",
        output_parsed=ContextualizedQuery(standalone_question=standalone_question),
    )
    # Even direct service callers supplying more history keep only the latest 10.
    history = [
        ChatHistoryMessage(
            role="user" if index % 2 == 0 else "assistant",
            content=f"Untrusted history message {index}",
        )
        for index in range(12)
    ]
    original_history = [item.model_dump() for item in history]
    original_question = "And subsequent ones?"
    hit = make_hit("B8.2.8", 67)
    selected = FusedHit(
        chunk=hit.chunk,
        fusion_score=0.03,
        document_title=hit.document_title,
        dense_rank=1,
        sparse_rank=1,
        dense_score=hit.score,
        sparse_score=10.0,
    )
    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense", return_value=[hit]
        ) as dense_mock,
        patch(
            "pole_position.rag.retrieval.service.retrieve_sparse",
            return_value=[SparseHit(hit.chunk, 10.0, hit.document_title)],
        ) as sparse_mock,
        patch(
            "pole_position.rag.retrieval.service.rerank_hits", return_value=[selected]
        ) as rerank_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value="Subsequent elements carry a penalty [S1].",
        ) as generate_mock,
    ):
        result = answer_question(
            original_question,
            history=history,
            openai_client=openai_client,
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="answer-model",
            sparse_corpus=Mock(spec=SparseCorpus),
            rerank_model="rerank-model",
        )

    openai_client.responses.parse.assert_called_once()
    kwargs = openai_client.responses.parse.call_args.kwargs
    rewrite_input = json.loads(kwargs["input"])
    assert rewrite_input == {
        "history": original_history[-10:],
        "question": original_question,
    }
    assert kwargs["model"] == "answer-model"
    assert kwargs["store"] is False
    for stage_mock in (dense_mock, sparse_mock, rerank_mock, generate_mock):
        stage_mock.assert_called_once()
        assert stage_mock.call_args.args[0] == standalone_question
    context = generate_mock.call_args.args[1]
    assert "Untrusted history" not in context.text
    assert context.sources == {"S1": selected}
    assert result.citations[0].hit is selected
    assert [item.model_dump() for item in history] == original_history


def test_contextualization_failure_stops_before_search_and_generation() -> None:
    openai_client = Mock(spec=OpenAI)
    openai_client.responses.parse.side_effect = RuntimeError("Rewrite unavailable")
    with (
        patch("pole_position.rag.retrieval.service.retrieve_dense") as dense_mock,
        patch("pole_position.rag.retrieval.service.retrieve_sparse") as sparse_mock,
        patch("pole_position.rag.retrieval.service.generate_draft_answer") as generate_mock,
        pytest.raises(RuntimeError, match="Rewrite unavailable"),
    ):
        answer_question(
            "And subsequent ones?",
            history=[
                ChatHistoryMessage(role="user", content="What is the PU penalty?")
            ],
            openai_client=openai_client,
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="test-model",
            sparse_corpus=Mock(spec=SparseCorpus),
        )
    dense_mock.assert_not_called()
    sparse_mock.assert_not_called()
    generate_mock.assert_not_called()


def test_answer_question_fuses_overlapping_hits_and_cites_fused_sources() -> None:
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    sparse_corpus = Mock(spec=SparseCorpus)
    dense_only = make_hit("B8.2.2", 66)
    shared = make_hit("B8.2.8", 67)
    sparse_only = make_hit("B8.2.3", 67)
    sparse_hits = [
        SparseHit(shared.chunk, 12.0, shared.document_title),
        SparseHit(sparse_only.chunk, 8.0, sparse_only.document_title),
    ]
    question = "What happens if a driver exceeds the allocation?"
    draft = "There is a penalty [S1]. The allocation is specified elsewhere [S3]."

    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=[dense_only, shared],
        ) as retrieve_dense_mock,
        patch(
            "pole_position.rag.retrieval.service.retrieve_sparse",
            return_value=sparse_hits,
        ) as retrieve_sparse_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value=draft,
        ) as generate_mock,
    ):
        result = answer_question(
            question,
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name="fia_regulations",
            model="test-model",
            sparse_corpus=sparse_corpus,
            top_k=3,
            section="B",
        )

    retrieve_dense_mock.assert_called_once_with(
        question,
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name="fia_regulations",
        top_k=20,
        section="B",
    )
    retrieve_sparse_mock.assert_called_once_with(
        question,
        corpus=sparse_corpus,
        top_k=20,
        section="B",
    )
    context = generate_mock.call_args.args[1]
    assert [hit.chunk.chunk_id for hit in context.sources.values()] == [
        shared.chunk.chunk_id,
        dense_only.chunk.chunk_id,
        sparse_only.chunk.chunk_id,
    ]
    assert context.text.count("Regulation text for B8.2.8.") == 1
    assert [citation.source_id for citation in result.citations] == ["S1", "S3"]
    assert result.answer == draft

    shared_citation, sparse_citation = result.citations
    assert isinstance(shared_citation.hit, FusedHit)
    assert shared_citation.hit is context.sources["S1"]
    assert shared_citation.hit.dense_rank == 2
    assert shared_citation.hit.sparse_rank == 1
    assert sparse_citation.hit is context.sources["S3"]
    assert sparse_citation.hit.chunk == sparse_only.chunk
    assert sparse_citation.hit.dense_rank is None
    assert sparse_citation.hit.sparse_rank == 2


def test_answer_question_can_cite_sparse_only_hit_when_dense_finds_nothing() -> None:
    sparse_corpus = Mock(spec=SparseCorpus)
    sparse_only = make_hit("B8.2.8", 67)
    question = "What is the penalty under B8.2.8?"
    draft = "The clause provides the answer [S1]."

    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=[],
        ) as retrieve_dense_mock,
        patch(
            "pole_position.rag.retrieval.service.retrieve_sparse",
            return_value=[
                SparseHit(sparse_only.chunk, 10.0, sparse_only.document_title)
            ],
        ) as retrieve_sparse_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value=draft,
        ) as generate_mock,
    ):
        result = answer_question(
            question,
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="test-model",
            sparse_corpus=sparse_corpus,
        )

    retrieve_dense_mock.assert_called_once()
    retrieve_sparse_mock.assert_called_once_with(
        question,
        corpus=sparse_corpus,
        top_k=20,
        section=None,
    )
    context = generate_mock.call_args.args[1]
    assert list(context.sources) == ["S1"]
    assert result.answer == draft
    assert len(result.citations) == 1
    assert result.citations[0].hit is context.sources["S1"]
    assert isinstance(result.citations[0].hit, FusedHit)
    assert result.citations[0].hit.chunk == sparse_only.chunk
    assert result.citations[0].hit.dense_rank is None
    assert result.citations[0].hit.sparse_rank == 1


def test_answer_question_reranks_twenty_fused_candidates_before_context() -> None:
    question = "Which Power Unit rule applies?"
    openai_client = Mock(spec=OpenAI)
    qdrant_client = Mock(spec=QdrantClient)
    sparse_corpus = Mock(spec=SparseCorpus)
    dense_hits = [make_hit(f"B8.2.{number}", 67) for number in range(1, 21)]
    sparse_hits = [
        SparseHit(hit.chunk, 10.0, hit.document_title) for hit in dense_hits
    ]
    draft = "The first selected rule applies [S1], with support from [S5]."

    def select_last_five(
        _question: str,
        candidates: Sequence[FusedHit],
        **_kwargs: object,
    ) -> list[FusedHit]:
        return list(reversed(candidates[-5:]))

    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=dense_hits,
        ) as retrieve_dense_mock,
        patch(
            "pole_position.rag.retrieval.service.retrieve_sparse",
            return_value=sparse_hits,
        ) as retrieve_sparse_mock,
        patch(
            "pole_position.rag.retrieval.service.rerank_hits",
            side_effect=select_last_five,
        ) as rerank_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value=draft,
        ) as generate_mock,
    ):
        result = answer_question(
            question,
            openai_client=openai_client,
            qdrant_client=qdrant_client,
            collection_name="fia_regulations",
            model="answer-model",
            sparse_corpus=sparse_corpus,
            rerank_model="rerank-model",
            top_k=5,
            section="B",
        )

    retrieve_dense_mock.assert_called_once_with(
        question,
        openai_client=openai_client,
        qdrant_client=qdrant_client,
        collection_name="fia_regulations",
        top_k=20,
        section="B",
    )
    retrieve_sparse_mock.assert_called_once_with(
        question,
        corpus=sparse_corpus,
        top_k=20,
        section="B",
    )
    rerank_mock.assert_called_once()
    rerank_args, rerank_kwargs = rerank_mock.call_args
    assert rerank_args[0] == question
    fused_candidates = rerank_args[1]
    assert len(fused_candidates) == 20
    assert all(isinstance(hit, FusedHit) for hit in fused_candidates)
    assert [hit.chunk.chunk_id for hit in fused_candidates] == [
        hit.chunk.chunk_id for hit in dense_hits
    ]
    assert [hit.dense_rank for hit in fused_candidates] == list(range(1, 21))
    assert [hit.sparse_rank for hit in fused_candidates] == list(range(1, 21))
    assert rerank_kwargs == {
        "client": openai_client,
        "model": "rerank-model",
        "top_k": 5,
    }

    generate_mock.assert_called_once()
    context = generate_mock.call_args.args[1]
    assert [hit.chunk.chunk_id for hit in context.sources.values()] == [
        hit.chunk.chunk_id for hit in reversed(dense_hits[-5:])
    ]
    assert len(context.sources) == 5
    assert len(result.citations) == 2
    assert result.citations[0].hit is context.sources["S1"]
    assert result.citations[1].hit is context.sources["S5"]
    assert result.answer == draft
    openai_client.responses.parse.assert_not_called()
    qdrant_client.query_points.assert_not_called()


def test_answer_question_uses_fused_hits_if_reranking_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    dense_hits = [make_hit(f"B8.2.{number}", 67) for number in range(1, 7)]
    sparse_hits = [
        SparseHit(hit.chunk, 10.0, hit.document_title) for hit in dense_hits
    ]
    draft = "The rule is stated here [S1]."

    with (
        patch(
            "pole_position.rag.retrieval.service.retrieve_dense",
            return_value=dense_hits,
        ),
        patch(
            "pole_position.rag.retrieval.service.retrieve_sparse",
            return_value=sparse_hits,
        ),
        patch(
            "pole_position.rag.retrieval.service.rerank_hits",
            side_effect=RuntimeError("Model unavailable"),
        ) as rerank_mock,
        patch(
            "pole_position.rag.retrieval.service.generate_draft_answer",
            return_value=draft,
        ) as generate_mock,
    ):
        result = answer_question(
            "Which Power Unit rule applies?",
            openai_client=Mock(spec=OpenAI),
            qdrant_client=Mock(spec=QdrantClient),
            collection_name="fia_regulations",
            model="answer-model",
            sparse_corpus=Mock(spec=SparseCorpus),
            rerank_model="rerank-model",
            top_k=5,
        )

    rerank_mock.assert_called_once()
    context = generate_mock.call_args.args[1]
    assert [hit.chunk.chunk_id for hit in context.sources.values()] == [
        hit.chunk.chunk_id for hit in dense_hits[:5]
    ]
    assert result.answer == draft
    assert len(result.citations) == 1
    assert result.citations[0].hit is context.sources["S1"]
    assert "Reranking failed; using fused results" in caplog.text


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
