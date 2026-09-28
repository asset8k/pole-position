from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import pytest
from openai import OpenAI

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.answer_generator import (
    INSUFFICIENT_EVIDENCE_ANSWER,
    generate_draft_answer,
)
from pole_position.rag.generation.context_builder import ContextBundle, build_context
from pole_position.rag.generation.prompts import ANSWER_INSTRUCTIONS
from pole_position.rag.retrieval.dense import DenseHit


def make_context() -> ContextBundle:
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
        text="Excess power unit elements result in a penalty.",
        start_pdf_page=67,
        end_pdf_page=67,
    )
    return build_context(
        [DenseHit(chunk=chunk, score=0.9, document_title="Sporting Regulations")]
    )


def make_client(*, status: str = "completed", output_text: str = "Answer [S1].") -> Mock:
    client = Mock()
    client.responses.create.return_value = SimpleNamespace(
        status=status,
        output_text=output_text,
    )
    return client


def test_generate_draft_answer_sends_instructions_and_labelled_context() -> None:
    context = make_context()
    client = make_client(output_text="  Exceeding the allocation has a penalty [S1].  ")

    answer = generate_draft_answer(
        "  What happens if the allocation is exceeded?  ",
        context,
        client=cast(OpenAI, client),
        model="test-model",
    )

    assert answer == "Exceeding the allocation has a penalty [S1]."
    client.responses.create.assert_called_once()
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["instructions"] == ANSWER_INSTRUCTIONS
    assert "<question>\nWhat happens if the allocation is exceeded?\n</question>" in kwargs[
        "input"
    ]
    assert "[S1]" in kwargs["input"]
    assert context.text in kwargs["input"]


@pytest.mark.parametrize(
    "context",
    [
        ContextBundle(text="", sources={}),
        ContextBundle(text="Unlabelled text", sources={}),
        ContextBundle(text="", sources=make_context().sources),
    ],
)
def test_generate_draft_answer_abstains_without_usable_context(
    context: ContextBundle,
) -> None:
    client = make_client()

    answer = generate_draft_answer(
        "What is the penalty?",
        context,
        client=cast(OpenAI, client),
        model="test-model",
    )

    assert answer == INSUFFICIENT_EVIDENCE_ANSWER
    client.responses.create.assert_not_called()


@pytest.mark.parametrize(
    ("question", "model", "message"),
    [
        ("   ", "test-model", "Question cannot be empty"),
        ("What is the penalty?", "   ", "model cannot be empty"),
    ],
)
def test_generate_draft_answer_rejects_invalid_input_before_api_call(
    question: str,
    model: str,
    message: str,
) -> None:
    client = make_client()

    with pytest.raises(ValueError, match=message):
        generate_draft_answer(
            question,
            make_context(),
            client=cast(OpenAI, client),
            model=model,
        )

    client.responses.create.assert_not_called()


@pytest.mark.parametrize("status", ["incomplete", "failed", "queued"])
def test_generate_draft_answer_rejects_noncompleted_response(status: str) -> None:
    client = make_client(status=status, output_text="Partial answer [S1].")

    with pytest.raises(RuntimeError, match=f"did not complete: {status}"):
        generate_draft_answer(
            "What is the penalty?",
            make_context(),
            client=cast(OpenAI, client),
            model="test-model",
        )


def test_generate_draft_answer_rejects_blank_model_output() -> None:
    client = make_client(output_text=" \n ")

    with pytest.raises(RuntimeError, match="returned no text"):
        generate_draft_answer(
            "What is the penalty?",
            make_context(),
            client=cast(OpenAI, client),
            model="test-model",
        )
