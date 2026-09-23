import pytest

from pole_position.rag.contracts import ExtractedDocument, ExtractedPage
from pole_position.rag.ingestion.structure_parser import get_heading, parse_document

SOURCE_SHA256 = "a" * 64


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("PREAMBLE", ("preamble", None, "Preamble")),
        ("ARTICLE A1: PURPOSE", ("article", "A1", "PURPOSE")),
        (
            "APPENDIX A1: GOVERNANCE STRUCTURE",
            ("appendix", "A1", "GOVERNANCE STRUCTURE"),
        ),
        ("1.1 This is a clause, not a heading", None),
    ],
)
def test_get_heading_recognizes_supported_top_level_headings(
    line: str,
    expected: tuple[str, str | None, str] | None,
) -> None:
    assert get_heading(line) == expected


def test_parse_document_skips_contents_and_collects_units() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-a-issue-03",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=("CONTENTS\n\nPREAMBLE\nARTICLE A1: PURPOSE\nARTICLE A2: SCOPE"),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    "PREAMBLE\n"
                    "Advisory Committee: FIA Formula One Commission\n\n"
                    "These provisions establish the framework."
                ),
            ),
            ExtractedPage(
                pdf_page_number=3,
                text=(
                    "ARTICLE A1: PURPOSE\n"
                    "Advisory Committee: FIA Formula One Commission\n\n"
                    "This Article defines the purpose."
                ),
            ),
            ExtractedPage(
                pdf_page_number=4,
                text="This paragraph continues on the following PDF page.",
            ),
            ExtractedPage(
                pdf_page_number=5,
                text=(
                    "APPENDIX A1: GOVERNANCE STRUCTURE\n"
                    "The appendix text is collected until the document ends."
                ),
            ),
        ],
    )

    parsed = parse_document(document)

    assert parsed.document_id == document.document_id
    assert parsed.source_sha256 == document.source_sha256
    assert [(unit.kind, unit.identifier, unit.title) for unit in parsed.units] == [
        ("preamble", None, "Preamble"),
        ("article", "A1", "PURPOSE"),
        ("appendix", "A1", "GOVERNANCE STRUCTURE"),
    ]

    preamble, article, appendix = parsed.units
    assert preamble.start_pdf_page == 2
    assert preamble.end_pdf_page == 2
    assert "CONTENTS" not in preamble.text
    assert "These provisions establish the framework." in preamble.text

    assert article.start_pdf_page == 3
    assert article.end_pdf_page == 4
    assert "This Article defines the purpose." in article.text
    assert "continues on the following PDF page" in article.text

    assert appendix.start_pdf_page == 5
    assert appendix.end_pdf_page == 5
    assert "document ends" in appendix.text


def test_parse_document_separates_article_and_appendix_on_same_page() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-a-issue-03",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "ARTICLE A1: PURPOSE\n"
                    "Advisory Committee: FIA Formula One Commission\n"
                    "The article begins here."
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    "The article ends here.\n"
                    "APPENDIX A1: DEFINITIONS\n"
                    "The appendix begins here."
                ),
            ),
            ExtractedPage(
                pdf_page_number=3,
                text="The appendix continues here.",
            ),
        ],
    )

    parsed = parse_document(document)

    assert [(unit.kind, unit.identifier) for unit in parsed.units] == [
        ("article", "A1"),
        ("appendix", "A1"),
    ]

    article, appendix = parsed.units
    assert [segment.pdf_page_number for segment in article.page_segments] == [1, 2]
    assert article.page_segments[1].text == "The article ends here."
    assert "APPENDIX A1" not in article.page_segments[1].text

    assert [segment.pdf_page_number for segment in appendix.page_segments] == [2, 3]
    assert appendix.page_segments[0].text == (
        "APPENDIX A1: DEFINITIONS\nThe appendix begins here."
    )
    assert "The article ends here." not in appendix.page_segments[0].text
    assert appendix.page_segments[1].text == "The appendix continues here."


def test_parse_document_includes_blank_page_in_visual_appendix_range() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-c-issue-20",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "ARTICLE C1: GENERAL PRINCIPLES\n"
                    "Advisory Committee: TAC\n"
                    "Article text."
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text="APPENDIX C3: DRAWINGS\nFigure reference.",
            ),
            ExtractedPage(pdf_page_number=3, text=""),
            ExtractedPage(
                pdf_page_number=4,
                text="APPENDIX C4: COMPONENTS\nAppendix C4 text.",
            ),
        ],
    )

    parsed = parse_document(document)

    appendix_c3 = next(unit for unit in parsed.units if unit.identifier == "C3")
    assert appendix_c3.start_pdf_page == 2
    assert appendix_c3.end_pdf_page == 3
    assert [segment.pdf_page_number for segment in appendix_c3.page_segments] == [2]
    assert "Figure reference." in appendix_c3.page_segments[0].text


@pytest.mark.parametrize(
    ("section", "contents_page_number"),
    [("D", "4"), ("E", "3")],
)
def test_parse_document_skips_financial_contents_and_starts_at_article(
    section: str,
    contents_page_number: str,
) -> None:
    article_identifier = f"{section}1"
    document = ExtractedDocument(
        document_id=f"fia-f1-2026-section-{section.lower()}",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "CONTENTS:\n"
                    f"ARTICLE {article_identifier}: GENERAL PRINCIPLES\n"
                    f"{contents_page_number}\n"
                    f"{article_identifier}.1\n"
                    "Scope\n"
                    f"{contents_page_number}"
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    f"ARTICLE {article_identifier}: GENERAL PRINCIPLES\n"
                    f"{article_identifier}.1\n"
                    "Scope\n"
                    f"{article_identifier}.1.1\n"
                    "The regulation text begins here."
                ),
            ),
        ],
    )

    parsed = parse_document(document)

    assert len(parsed.units) == 1
    article = parsed.units[0]
    assert article.kind == "article"
    assert article.identifier == article_identifier
    assert article.start_pdf_page == 2
    assert article.end_pdf_page == 2
    assert "CONTENTS:" not in article.text
    assert "The regulation text begins here." in article.text


def test_parse_document_keeps_quoted_article_inside_approved_changes_appendix() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-b-issue-08",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "ARTICLE B2: FORMAT OF A COMPETITION\n"
                    "Advisory Committee: SAC\n"
                    "B2.1\n"
                    "Current 2026 rule."
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    "APPENDIX B5: APPROVED CHANGES TO SECTION B FOR SUBSEQUENT YEARS\n"
                    "Changes for 2027"
                ),
            ),
            ExtractedPage(
                pdf_page_number=3,
                text=(
                    "ARTICLE B2: FORMAT OF A COMPETITION\n"
                    "B2.5\n"
                    "Amended 2027 rule."
                ),
            ),
        ],
    )

    parsed = parse_document(document)

    assert [(unit.kind, unit.identifier) for unit in parsed.units] == [
        ("article", "B2"),
        ("appendix", "B5"),
    ]
    article, appendix = parsed.units
    assert "Current 2026 rule." in article.text
    assert "Amended 2027 rule." not in article.text
    assert appendix.start_pdf_page == 2
    assert appendix.end_pdf_page == 3
    assert "Changes for 2027" in appendix.text
    assert "ARTICLE B2: FORMAT OF A COMPETITION" in appendix.text
    assert "Amended 2027 rule." in appendix.text


def test_parse_document_keeps_repeated_appendix_heading_inside_current_unit() -> None:
    document = ExtractedDocument(
        document_id="fia-f1-2026-section-a-issue-03",
        source_sha256=SOURCE_SHA256,
        pages=[
            ExtractedPage(
                pdf_page_number=1,
                text=(
                    "APPENDIX A7: POWER UNIT SUPPLY\n"
                    "Advisory Committee: FIA Formula One Commission\n\n"
                    "The current Appendix A7 text."
                ),
            ),
            ExtractedPage(
                pdf_page_number=2,
                text=(
                    "APPENDIX A9: APPROVED CHANGES\n"
                    "Changes for 2027\n"
                    "APPENDIX A7: POWER UNIT SUPPLY\n"
                    "The historical amendment text."
                ),
            ),
        ],
    )

    parsed = parse_document(document)

    assert [(unit.identifier, unit.title) for unit in parsed.units] == [
        ("A7", "POWER UNIT SUPPLY"),
        ("A9", "APPROVED CHANGES"),
    ]

    appendix_a9 = parsed.units[1]
    assert appendix_a9.start_pdf_page == 2
    assert appendix_a9.end_pdf_page == 2
    assert "APPENDIX A7: POWER UNIT SUPPLY" in appendix_a9.text
    assert "The historical amendment text." in appendix_a9.text
