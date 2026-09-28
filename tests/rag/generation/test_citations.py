import pytest

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.citations import (
    CitationValidationError,
    validate_citations,
)
from pole_position.rag.generation.context_builder import ContextBundle, build_context
from pole_position.rag.generation.prompts import (
    ANSWER_INSTRUCTIONS,
    INSUFFICIENT_EVIDENCE_ANSWER,
)
from pole_position.rag.retrieval.dense import DenseHit

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"
SOURCE_SHA256 = "a" * 64


def make_hit(clause_identifier: str, page: int) -> DenseHit:
    chunk = RetrievalChunk(
        chunk_id=f"{DOCUMENT_ID}:{clause_identifier}:0",
        document_id=DOCUMENT_ID,
        source_sha256=SOURCE_SHA256,
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


@pytest.fixture
def context() -> ContextBundle:
    return build_context([make_hit("B8.2.8", 67), make_hit("B8.2.3", 66)])


def test_validate_citations_returns_only_used_sources_in_first_mention_order(
    context: ContextBundle,
) -> None:
    draft = "  Allowances may apply [S2]. Exceeding them has consequences [S1][S2].  "

    validated = validate_citations(draft, context)

    assert validated.answer == draft.strip()
    assert [citation.source_id for citation in validated.citations] == ["S2", "S1"]
    assert validated.citations[0].hit is context.sources["S2"]
    assert validated.citations[1].hit is context.sources["S1"]
    assert validated.citations[1].hit.chunk.start_pdf_page == 67


def test_validate_citations_accepts_one_valid_source(context: ContextBundle) -> None:
    validated = validate_citations("A supported answer [S1].", context)

    assert len(validated.citations) == 1
    assert validated.citations[0].source_id == "S1"


@pytest.mark.parametrize("has_sources", [False, True])
def test_validate_citations_allows_exact_uncited_abstention(
    context: ContextBundle,
    has_sources: bool,
) -> None:
    selected_context = context if has_sources else ContextBundle(text="", sources={})

    validated = validate_citations(
        f"  {INSUFFICIENT_EVIDENCE_ANSWER}  ", selected_context
    )

    assert validated.answer == INSUFFICIENT_EVIDENCE_ANSWER
    assert validated.citations == ()
    assert INSUFFICIENT_EVIDENCE_ANSWER in ANSWER_INSTRUCTIONS


def test_validate_citations_rejects_unknown_source(context: ContextBundle) -> None:
    with pytest.raises(CitationValidationError, match=r"Unknown citation: \[S3\]"):
        validate_citations("Unsupported claim [S3].", context)


@pytest.mark.parametrize("marker", ["[S0]", "[S01]", "[S]", "[Sabc]", "[S1, S2]"])
def test_validate_citations_rejects_malformed_marker(
    context: ContextBundle,
    marker: str,
) -> None:
    with pytest.raises(CitationValidationError, match="Invalid citation marker"):
        validate_citations(f"Claim {marker}.", context)


def test_validate_citations_rejects_malformed_marker_even_with_valid_one(
    context: ContextBundle,
) -> None:
    with pytest.raises(CitationValidationError, match="Invalid citation marker"):
        validate_citations("Claim [S1]. Another claim [S1, S2].", context)


@pytest.mark.parametrize(
    "draft",
    [
        "A regulation answer without a citation.",
        "The excerpts do not provide enough evidence.",
    ],
)
def test_validate_citations_rejects_other_uncited_text(
    context: ContextBundle,
    draft: str,
) -> None:
    with pytest.raises(CitationValidationError, match="no source citations"):
        validate_citations(draft, context)


def test_validate_citations_rejects_blank_answer(context: ContextBundle) -> None:
    with pytest.raises(CitationValidationError, match="Answer cannot be empty"):
        validate_citations(" \n ", context)


def test_validate_citations_rejects_citation_when_context_is_empty() -> None:
    with pytest.raises(CitationValidationError, match=r"Unknown citation: \[S1\]"):
        validate_citations("Invented answer [S1].", ContextBundle(text="", sources={}))
