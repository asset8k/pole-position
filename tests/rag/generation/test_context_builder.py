import pytest

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.generation.context_builder import build_context
from pole_position.rag.retrieval.dense import DenseHit

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"
SOURCE_SHA256 = "a" * 64


def make_clause_hit(text: str = "The original clause wording.") -> DenseHit:
    return DenseHit(
        chunk=RetrievalChunk(
            chunk_id=f"{DOCUMENT_ID}:B8.2.8:0",
            document_id=DOCUMENT_ID,
            source_sha256=SOURCE_SHA256,
            section="B",
            source_kind="clause",
            article_identifier="B8",
            clause_identifier="B8.2.8",
            chunk_index=0,
            text=text,
            start_pdf_page=67,
            end_pdf_page=68,
        ),
        score=0.9,
        document_title="Sporting Regulations",
    )


def make_appendix_hit() -> DenseHit:
    return DenseHit(
        chunk=RetrievalChunk(
            chunk_id=f"{DOCUMENT_ID}:appendix:B4:page-92:0",
            document_id=DOCUMENT_ID,
            source_sha256=SOURCE_SHA256,
            section="B",
            source_kind="appendix",
            appendix_identifier="B4",
            appendix_title="Appendix title",
            chunk_index=0,
            text="Appendix wording.",
            start_pdf_page=92,
            end_pdf_page=92,
        ),
        score=0.8,
        document_title="Sporting Regulations",
    )


def make_preamble_hit() -> DenseHit:
    return DenseHit(
        chunk=RetrievalChunk(
            chunk_id=f"{DOCUMENT_ID}:preamble:page-3:0",
            document_id=DOCUMENT_ID,
            source_sha256=SOURCE_SHA256,
            section="B",
            source_kind="preamble",
            chunk_index=0,
            text="Preamble wording.",
            start_pdf_page=3,
            end_pdf_page=3,
        ),
        score=0.7,
        document_title="Sporting Regulations",
    )


def test_build_context_labels_sources_and_preserves_complete_excerpt() -> None:
    clause = make_clause_hit("First line.\nSecond line.")
    appendix = make_appendix_hit()
    preamble = make_preamble_hit()

    context = build_context([clause, appendix, preamble])

    assert list(context.sources) == ["S1", "S2", "S3"]
    assert context.sources["S1"] is clause
    assert context.sources["S2"] is appendix
    assert context.sources["S3"] is preamble
    assert "[S1]\nDocument: Sporting Regulations" in context.text
    assert f"Document ID: {DOCUMENT_ID}" in context.text
    assert "Location: Clause B8.2.8 (Article B8)" in context.text
    assert "PDF page(s): 67-68\nText:\nFirst line.\nSecond line." in context.text
    assert "[S2]\nDocument: Sporting Regulations" in context.text
    assert "Location: Appendix B4\nPDF page(s): 92" in context.text
    assert "[S3]\nDocument: Sporting Regulations" in context.text
    assert "Location: Preamble\nPDF page(s): 3" in context.text


def test_build_context_skips_oversized_chunk_without_truncating_other_sources() -> None:
    long_clause = make_clause_hit("Long text. " * 200)
    short_preamble = make_preamble_hit()
    budget = len(build_context([short_preamble]).text)

    context = build_context([long_clause, short_preamble], max_chars=budget)

    assert context.text == build_context([short_preamble]).text
    assert context.sources == {"S1": short_preamble}
    assert len(context.text) == budget


def test_build_context_deduplicates_chunk_ids() -> None:
    hit = make_clause_hit()

    context = build_context([hit, hit])

    assert list(context.sources) == ["S1"]
    assert context.text.count("[S1]") == 1


def test_build_context_handles_no_hits() -> None:
    context = build_context([])

    assert context.text == ""
    assert context.sources == {}


@pytest.mark.parametrize("max_chars", [0, -1])
def test_build_context_rejects_nonpositive_budget(max_chars: int) -> None:
    with pytest.raises(ValueError, match="max_chars must be positive"):
        build_context([make_clause_hit()], max_chars=max_chars)
