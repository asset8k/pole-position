import re
from dataclasses import dataclass

from pole_position.rag.generation.context_builder import ContextBundle, EvidenceHit
from pole_position.rag.generation.prompts import (
    INSUFFICIENT_EVIDENCE_ANSWER,
)

CITATION_PATTERN = re.compile(r"\[S[^\]\n]*\]")
VALID_SOURCE_ID = re.compile(r"S[1-9]\d*")


class CitationValidationError(ValueError):
    """The draft contains missing or invalid citation labels."""


@dataclass(frozen=True)
class ValidatedCitation:
    source_id: str
    hit: EvidenceHit


@dataclass(frozen=True)
class ValidatedAnswer:
    answer: str
    citations: tuple[ValidatedCitation, ...]


def validate_citations(
    draft: str,
    context: ContextBundle,
) -> ValidatedAnswer:
    """Verify citation labels against the sources sent to the model."""
    answer = draft.strip()
    if not answer:
        raise CitationValidationError("Answer cannot be empty")

    # An abstention needs no supporting citation.
    if answer == INSUFFICIENT_EVIDENCE_ANSWER:
        return ValidatedAnswer(answer=answer, citations=())

    markers = CITATION_PATTERN.findall(answer)
    if not markers:
        raise CitationValidationError("Answer contains no source citations")

    citations: list[ValidatedCitation] = []
    seen_ids: set[str] = set()

    for marker in markers:
        source_id = marker[1:-1]  # "[S1]" -> "S1"

        if VALID_SOURCE_ID.fullmatch(source_id) is None:
            raise CitationValidationError(f"Invalid citation marker: {marker}")

        hit = context.sources.get(source_id)
        if hit is None:
            raise CitationValidationError(f"Unknown citation: {marker}")

        if source_id not in seen_ids:
            citations.append(ValidatedCitation(source_id=source_id, hit=hit))
            seen_ids.add(source_id)

    return ValidatedAnswer(answer=answer, citations=tuple(citations))
