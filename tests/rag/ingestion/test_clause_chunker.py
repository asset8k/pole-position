import pytest

from pole_position.rag.contracts import (
    PageTextSegment,
    ParsedClause,
    ParsedClauseDocument,
)
from pole_position.rag.ingestion.clause_chunker import chunk_clauses

SOURCE_SHA256 = "a" * 64
DOCUMENT_ID = "fia-f1-2026-section-a-issue-03"


def make_clause(
    *,
    clause_identifier: str = "A1.2.3",
    text: str = "The clause text used for retrieval.",
    page_texts: tuple[str, ...] | None = None,
) -> ParsedClause:
    if page_texts is None:
        page_texts = (text,)

    return ParsedClause(
        article_identifier="A1",
        clause_identifier=clause_identifier,
        title="Applicable regulations",
        text="\n".join(page_texts),
        start_pdf_page=5,
        end_pdf_page=5 + len(page_texts) - 1,
        page_segments=[
            PageTextSegment(pdf_page_number=5 + index, text=page_text)
            for index, page_text in enumerate(page_texts)
        ],
    )


def make_document(clauses: list[ParsedClause]) -> ParsedClauseDocument:
    return ParsedClauseDocument(
        document_id=DOCUMENT_ID,
        source_sha256=SOURCE_SHA256,
        clauses=clauses,
    )


def test_chunk_clauses_preserves_short_clause_provenance() -> None:
    clause = make_clause()

    chunked_document = chunk_clauses(make_document([clause]))

    assert chunked_document.document_id == DOCUMENT_ID
    assert chunked_document.source_sha256 == SOURCE_SHA256
    assert len(chunked_document.chunks) == 1

    chunk = chunked_document.chunks[0]
    assert chunk.chunk_id == f"{DOCUMENT_ID}:A1.2.3:0"
    assert chunk.section == "A"
    assert chunk.source_kind == "clause"
    assert chunk.article_identifier == "A1"
    assert chunk.clause_identifier == "A1.2.3"
    assert chunk.clause_title == "Applicable regulations"
    assert chunk.chunk_index == 0
    assert chunk.text == clause.text
    assert chunk.start_pdf_page == 5
    assert chunk.end_pdf_page == 5


def test_chunk_clauses_keeps_multi_page_clause_chunks_on_their_source_pages() -> None:
    clause = make_clause(
        page_texts=("First page rule.", "Second page continuation."),
    )

    chunks = chunk_clauses(make_document([clause])).chunks

    assert [chunk.text for chunk in chunks] == [
        "First page rule.",
        "Second page continuation.",
    ]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.chunk_id for chunk in chunks] == [
        f"{DOCUMENT_ID}:A1.2.3:0",
        f"{DOCUMENT_ID}:A1.2.3:1",
    ]
    assert [(chunk.start_pdf_page, chunk.end_pdf_page) for chunk in chunks] == [
        (5, 5),
        (6, 6),
    ]


def test_chunk_clauses_splits_long_clause_with_sequential_chunk_indexes() -> None:
    clause = make_clause(
        text=("First legal sentence. Second legal sentence. Third legal sentence."),
    )

    chunked_document = chunk_clauses(
        make_document([clause]),
        max_characters=35,
    )

    assert len(chunked_document.chunks) == 3
    assert [chunk.chunk_index for chunk in chunked_document.chunks] == [0, 1, 2]
    assert [chunk.chunk_id for chunk in chunked_document.chunks] == [
        f"{DOCUMENT_ID}:A1.2.3:0",
        f"{DOCUMENT_ID}:A1.2.3:1",
        f"{DOCUMENT_ID}:A1.2.3:2",
    ]
    assert all(len(chunk.text) <= 35 for chunk in chunked_document.chunks)
    assert " ".join(chunk.text for chunk in chunked_document.chunks) == clause.text


def test_chunk_clauses_resets_chunk_index_for_each_clause() -> None:
    first_clause = make_clause(clause_identifier="A1.2.3")
    second_clause = make_clause(clause_identifier="A1.2.4")

    chunked_document = chunk_clauses(make_document([first_clause, second_clause]))

    assert [chunk.chunk_id for chunk in chunked_document.chunks] == [
        f"{DOCUMENT_ID}:A1.2.3:0",
        f"{DOCUMENT_ID}:A1.2.4:0",
    ]
    assert [chunk.chunk_index for chunk in chunked_document.chunks] == [0, 0]


@pytest.mark.parametrize("marker", ["b.", "iv."])
def test_chunk_clauses_keeps_list_marker_with_its_item(marker: str) -> None:
    clause = make_clause(
        text=f"First rule applies. {marker} Second rule applies to everyone."
    )

    chunked_document = chunk_clauses(make_document([clause]), max_characters=25)
    texts = [chunk.text for chunk in chunked_document.chunks]

    assert " ".join(texts) == clause.text
    assert all(len(text) <= 25 for text in texts)
    assert not any(text.endswith(f" {marker}") for text in texts)
    assert any(text.startswith(f"{marker} Second") for text in texts)


@pytest.mark.parametrize(
    ("marker", "prefix_length"),
    [("b.", 16), ("iv.", 15)],
)
def test_chunk_clauses_keeps_marker_with_item_during_word_fallback(
    marker: str,
    prefix_length: int,
) -> None:
    clause = make_clause(
        text=f"{'x' * prefix_length} {marker} The regulation continues with details."
    )

    chunked_document = chunk_clauses(make_document([clause]), max_characters=20)
    texts = [chunk.text for chunk in chunked_document.chunks]

    assert " ".join(texts) == clause.text
    assert all(len(text) <= 20 for text in texts)
    assert not any(text.endswith(f" {marker}") for text in texts)
    assert any(text.startswith(f"{marker} The") for text in texts)


def test_chunk_clauses_rejects_non_positive_max_characters() -> None:
    with pytest.raises(ValueError, match="max_characters must be greater than zero"):
        chunk_clauses(make_document([make_clause()]), max_characters=0)
