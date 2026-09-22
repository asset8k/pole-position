import pytest

from pole_position.rag.contracts import ExtractedDocument, ExtractedPage
from pole_position.rag.ingestion.normalizer import (
    is_running_header,
    normalize_document,
    normalize_page_text,
)


@pytest.mark.parametrize(
    "line",
    [
        "SECTION A: GENERAL REGULATORY PROVISIONS",
        "0  A",
        "A5",
        "2026 Formula 1: General Regulatory Provisions",
        "©2026 Fédération Internationale de l\u2019Automobile",
        "25 June 2026",
        "Issue 03",
    ],
)
def test_is_running_header(line: str) -> None:
    assert is_running_header(line)


def test_article_and_clause_are_not_running_headers() -> None:
    assert not is_running_header("ARTICLE A1: GENERAL PRINCIPLES")
    assert not is_running_header("A1.1.1")


def test_normalize_page_text_removes_headers_and_collapses_blank_lines() -> None:
    raw_text = """SECTION A: GENERAL REGULATORY PROVISIONS

0  A
A5
2026 Formula 1: General Regulatory Provisions
©2026 Fédération Internationale de l’Automobile
25 June 2026
Issue 03


ARTICLE A1: GENERAL PRINCIPLES



A1.1
Overview
"""

    normalized_text = normalize_page_text(raw_text)

    assert (
        normalized_text
        == """ARTICLE A1: GENERAL PRINCIPLES

A1.1
Overview"""
    )


def test_normalize_document_preserves_metadata_and_page_numbers() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-a-issue-03",
        source_sha256="a" * 64,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text="Issue 03\n\nARTICLE A1: GENERAL PRINCIPLES",
            ),
            ExtractedPage(
                pdf_page_number=2,
                text="SECTION A: GENERAL REGULATORY PROVISIONS\n\nA1.1\nOverview",
            ),
        ],
    )

    normalized_document = normalize_document(document)

    assert normalized_document.document_id == document.document_id
    assert normalized_document.source_sha256 == document.source_sha256
    assert [page.pdf_page_number for page in normalized_document.pages] == [1, 2]
    assert normalized_document.pages[0].text == "ARTICLE A1: GENERAL PRINCIPLES"
    assert normalized_document.pages[1].text == "A1.1\nOverview"
