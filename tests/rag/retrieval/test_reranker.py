import json
from unittest.mock import Mock

import pytest
from openai import OpenAI

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.retrieval.fusion import FusedHit
from pole_position.rag.retrieval.reranker import (
    MAX_RERANK_CANDIDATES,
    RerankOrder,
    rerank_hits,
)

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"


def make_hit(clause_identifier: str, text: str) -> FusedHit:
    chunk = RetrievalChunk(
        chunk_id=f"{DOCUMENT_ID}:{clause_identifier}:0",
        document_id=DOCUMENT_ID,
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier=clause_identifier,
        chunk_index=0,
        text=text,
        start_pdf_page=67,
        end_pdf_page=67,
    )
    return FusedHit(
        chunk=chunk,
        document_title="Sporting Regulations",
        fusion_score=0.03,
        dense_rank=1,
        sparse_rank=2,
        dense_score=0.7,
        sparse_score=10.0,
    )


def make_hits() -> list[FusedHit]:
    return [
        make_hit("B8.2.2", "Power Unit Limitations & Usage"),
        make_hit("B8.2.8", "An additional element incurs a grid-place penalty."),
        make_hit("B8.2.3", "Each driver may use an additional unit."),
    ]


def mock_response(client: Mock, indices: list[int]) -> None:
    client.responses.parse.return_value = Mock(
        status="completed",
        output_parsed=RerankOrder(ranked_indices=indices),
    )


def test_rerank_hits_reorders_original_hits_and_limits_results() -> None:
    client = Mock(spec=OpenAI)
    hits = make_hits()
    mock_response(client, [1, 2, 0])

    reranked = rerank_hits(
        "  What is the penalty for another Power Unit element?  ",
        hits,
        client=client,
        model="test-model",
        top_k=2,
    )

    assert reranked[0] is hits[1]
    assert reranked[1] is hits[2]
    assert len(reranked) == 2

    client.responses.parse.assert_called_once()
    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["text_format"] is RerankOrder
    assert kwargs["store"] is False
    assert "directly state" in kwargs["instructions"]

    payload = json.loads(kwargs["input"])
    assert payload["question"] == "What is the penalty for another Power Unit element?"
    assert [candidate["index"] for candidate in payload["candidates"]] == [0, 1, 2]
    assert [candidate["chunk_id"] for candidate in payload["candidates"]] == [
        hit.chunk.chunk_id for hit in hits
    ]
    assert payload["candidates"][1]["text"] == hits[1].chunk.text


@pytest.mark.parametrize("hit_count", [0, 1])
def test_rerank_hits_skips_model_call_for_at_most_one_hit(hit_count: int) -> None:
    client = Mock(spec=OpenAI)
    hits = make_hits()[:hit_count]

    result = rerank_hits("What is the penalty?", hits, client=client, model="test-model")

    assert result == hits
    client.responses.parse.assert_not_called()


@pytest.mark.parametrize(
    ("question", "model", "top_k", "message"),
    [
        ("  ", "test-model", 5, "Question cannot be empty"),
        ("Question", "  ", 5, "Model cannot be empty"),
        ("Question", "test-model", 0, "top_k must be positive"),
    ],
)
def test_rerank_hits_rejects_invalid_arguments_before_model_call(
    question: str,
    model: str,
    top_k: int,
    message: str,
) -> None:
    client = Mock(spec=OpenAI)

    with pytest.raises(ValueError, match=message):
        rerank_hits(question, make_hits(), client=client, model=model, top_k=top_k)

    client.responses.parse.assert_not_called()


def test_rerank_hits_rejects_too_many_candidates() -> None:
    client = Mock(spec=OpenAI)
    hits = [
        make_hit(f"B8.2.{number}", f"Text {number}")
        for number in range(1, MAX_RERANK_CANDIDATES + 2)
    ]

    with pytest.raises(ValueError, match="at most 20 candidates"):
        rerank_hits("Question", hits, client=client, model="test-model")

    client.responses.parse.assert_not_called()


def test_rerank_hits_rejects_duplicate_chunk_ids() -> None:
    client = Mock(spec=OpenAI)
    hit = make_hits()[0]

    with pytest.raises(ValueError, match="duplicate chunk IDs"):
        rerank_hits("Question", [hit, hit], client=client, model="test-model")

    client.responses.parse.assert_not_called()


@pytest.mark.parametrize(
    ("status", "parsed"),
    [
        ("incomplete", RerankOrder(ranked_indices=[0, 1, 2])),
        ("completed", None),
    ],
)
def test_rerank_hits_rejects_incomplete_or_unparsed_response(
    status: str,
    parsed: RerankOrder | None,
) -> None:
    client = Mock(spec=OpenAI)
    client.responses.parse.return_value = Mock(status=status, output_parsed=parsed)

    with pytest.raises(RuntimeError, match="did not return a completed ranking"):
        rerank_hits("Question", make_hits(), client=client, model="test-model")


@pytest.mark.parametrize(
    "indices",
    [
        [],
        [0, 1],
        [0, 0, 1],
        [0, 1, 3],
    ],
)
def test_rerank_hits_rejects_missing_duplicate_or_unknown_indices(
    indices: list[int],
) -> None:
    client = Mock(spec=OpenAI)
    mock_response(client, indices)

    with pytest.raises(RuntimeError, match="missing, duplicate, or unknown indices"):
        rerank_hits("Question", make_hits(), client=client, model="test-model")


def test_rerank_hits_does_not_hide_api_failures() -> None:
    client = Mock(spec=OpenAI)
    client.responses.parse.side_effect = RuntimeError("Model unavailable")

    with pytest.raises(RuntimeError, match="Model unavailable"):
        rerank_hits("Question", make_hits(), client=client, model="test-model")
