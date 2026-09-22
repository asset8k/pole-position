from pole_position.rag.contracts import ExtractedDocument, ExtractedPage
from pole_position.rag.ingestion.clause_parser import parse_clauses


SOURCE_SHA256 = "a" * 64


def test_parse_clauses_collects_article_clauses_and_page_ranges() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-a-issue-03",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "ARTICLE A1: GENERAL PRINCIPLES\n"
                    "Advisory Committee: FIA Formula One Commission\n\n"
                    "A1.1\n"
                    "Overview\n\n"
                    "A1.1.1\n"
                    "First clause text."
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    "A1.1.2\n"
                    "Second clause text.\n\n"
                    "a.\n"
                    "A lettered item that belongs to clause A1.1.2."
                ),
            ),
            ExtractedPage(
                pdf_page_number=3,
                text=(
                    "This paragraph continues clause A1.1.2.\n\n"
                    "A1.2\n"
                    "Applicable regulations"
                ),
            ),
        ],
    )

    parsed = parse_clauses(document)

    assert parsed.document_id == document.document_id
    assert parsed.source_sha256 == document.source_sha256

    assert [
        (clause.article_identifier, clause.identifier, clause.title)
        for clause in parsed.clauses
    ] == [
        ("A1", "A1.1", "Overview"),
        ("A1", "A1.1.1", None),
        ("A1", "A1.1.2", None),
        ("A1", "A1.2", "Applicable regulations"),
    ]

    overview, first_clause, second_clause, applicable_regulations = parsed.clauses

    assert overview.start_pdf_page == 1
    assert overview.end_pdf_page == 1

    assert first_clause.start_pdf_page == 1
    assert first_clause.end_pdf_page == 1
    assert "First clause text." in first_clause.text

    assert second_clause.start_pdf_page == 2
    assert second_clause.end_pdf_page == 3
    assert "a." in second_clause.text
    assert "A lettered item" in second_clause.text
    assert "continues clause A1.1.2" in second_clause.text

    assert applicable_regulations.start_pdf_page == 3
    assert applicable_regulations.end_pdf_page == 3
