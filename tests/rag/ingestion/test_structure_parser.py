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
