from openai import OpenAI

from pole_position.rag.generation.context_builder import ContextBundle
from pole_position.rag.generation.prompts import (
    ANSWER_INSTRUCTIONS,
    INSUFFICIENT_EVIDENCE_ANSWER,
    build_answer_input,
)


def generate_draft_answer(
    question: str,
    context: ContextBundle,
    *,
    client: OpenAI,
    model: str,
) -> str:
    """Generate an answer draft; its citations still need backend validation."""
    if not model.strip():
        raise ValueError("model cannot be empty")

    model_input = build_answer_input(question, context)

    # Nothing to ground an answer in: avoid an unnecessary API call.
    if not context.sources or not context.text.strip():
        return INSUFFICIENT_EVIDENCE_ANSWER

    response = client.responses.create(
        model=model,
        instructions=ANSWER_INSTRUCTIONS,
        input=model_input,
    )

    if response.status != "completed":
        raise RuntimeError(f"Answer generation did not complete: {response.status}")

    answer = response.output_text.strip()
    if not answer:
        raise RuntimeError("Answer generation returned no text")

    return answer
