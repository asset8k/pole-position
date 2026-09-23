from pole_position.rag.contracts import PageTextSegment, ParsedDocument, ParsedUnit
from pole_position.rag.ingestion.preamble_chunker import chunk_preamble

SOURCE_SHA256 = "a" * 64
DOCUMENT_ID = "fia-f1-2026-section-a-issue-03"


def test_chunk_preamble_preserves_text_and_exact_page() -> None:
    text = "PREAMBLE\nThe regulations promote safety and sporting fairness."
    document = ParsedDocument(
        document_id=DOCUMENT_ID,
        source_sha256=SOURCE_SHA256,
        units=[
            ParsedUnit(
                kind="preamble",
                title="Preamble",
                text=text,
                start_pdf_page=4,
                end_pdf_page=4,
                page_segments=[PageTextSegment(pdf_page_number=4, text=text)],
            )
        ],
    )

    chunks = chunk_preamble(document, section="A")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id == f"{DOCUMENT_ID}:preamble:page-4:0"
    assert chunk.document_id == DOCUMENT_ID
    assert chunk.source_sha256 == SOURCE_SHA256
    assert chunk.section == "A"
    assert chunk.source_kind == "preamble"
    assert chunk.chunk_index == 0
    assert chunk.text == "PREAMBLE The regulations promote safety and sporting fairness."
    assert (chunk.start_pdf_page, chunk.end_pdf_page) == (4, 4)
    assert chunk.article_identifier is None
    assert chunk.clause_identifier is None
    assert chunk.appendix_identifier is None


def test_chunk_preamble_returns_no_chunks_when_document_has_no_preamble() -> None:
    text = "ARTICLE B1: DEFINITIONS\nArticle text."
    document = ParsedDocument(
        document_id="fia-f1-2026-section-b-issue-08",
        source_sha256=SOURCE_SHA256,
        units=[
            ParsedUnit(
                kind="article",
                identifier="B1",
                title="DEFINITIONS",
                text=text,
                start_pdf_page=4,
                end_pdf_page=4,
                page_segments=[PageTextSegment(pdf_page_number=4, text=text)],
            )
        ],
    )

    assert chunk_preamble(document, section="B") == []
