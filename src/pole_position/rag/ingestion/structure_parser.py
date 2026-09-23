import re

from pole_position.rag.contracts import (
    ExtractedDocument,
    PageTextSegment,
    ParsedDocument,
    ParsedUnit,
    ParsedUnitKind,
)

ARTICLE_HEADING_PATTERN = re.compile(
    r"^ARTICLE (?P<identifier>[A-F]\d+): (?P<title>.+)$"
)
APPENDIX_HEADING_PATTERN = re.compile(
    r"^APPENDIX (?P<identifier>[A-F]\d+): (?P<title>.+)$"
)

type HeadingMatch = tuple[ParsedUnitKind, str | None, str]


def get_heading(line: str) -> HeadingMatch | None:
    if line == "PREAMBLE":
        return ("preamble", None, "Preamble")

    article_match = ARTICLE_HEADING_PATTERN.fullmatch(line)
    if article_match:
        return (
            "article",
            article_match.group("identifier"),
            article_match.group("title"),
        )

    appendix_match = APPENDIX_HEADING_PATTERN.fullmatch(line)
    if appendix_match:
        return (
            "appendix",
            appendix_match.group("identifier"),
            appendix_match.group("title"),
        )

    return None


def find_first_content_line(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        heading = get_heading(line)

        if heading is None:
            continue

        following_lines = lines[index + 1 :]
        next_non_empty_line = next(
            (candidate for candidate in following_lines if candidate),
            None,
        )

        kind, identifier, _ = heading

        if next_non_empty_line is None:
            continue

        if next_non_empty_line.startswith("Advisory Committee:"):
            return index

        if (
            kind == "article"
            and identifier is not None
            and re.fullmatch(rf"{re.escape(identifier)}\.\d+", next_non_empty_line)
        ):
            return index

    return None


def parse_document(document: ExtractedDocument) -> ParsedDocument:
    units: list[ParsedUnit] = []

    current_kind: ParsedUnitKind | None = None
    current_identifier: str | None = None
    current_title: str | None = None
    current_start_page: int | None = None
    current_end_page: int | None = None
    current_lines: list[str] = []

    current_page_number: int | None = None
    current_page_lines: list[str] = []
    current_page_segments: list[PageTextSegment] = []

    seen_appendix_identifiers: set[str] = set()

    def save_page_segment() -> None:
        nonlocal current_page_number, current_page_lines

        if current_page_number is not None:
            page_text = "\n".join(current_page_lines).strip()

            if page_text:
                current_page_segments.append(
                    PageTextSegment(
                        pdf_page_number=current_page_number,
                        text=page_text,
                    )
                )

        current_page_number = None
        current_page_lines = []

    def append_line(line: str, pdf_page_number: int) -> None:
        nonlocal current_end_page, current_page_number

        if current_page_number != pdf_page_number:
            save_page_segment()
            current_page_number = pdf_page_number

        current_lines.append(line)
        current_page_lines.append(line)
        current_end_page = pdf_page_number

    def save_current_unit() -> None:
        if (
            current_kind is None
            or current_title is None
            or current_start_page is None
            or current_end_page is None
        ):
            return

        save_page_segment()

        units.append(
            ParsedUnit(
                kind=current_kind,
                identifier=current_identifier,
                title=current_title,
                text="\n".join(current_lines).strip(),
                start_pdf_page=current_start_page,
                end_pdf_page=current_end_page,
                page_segments=current_page_segments.copy(),
            )
        )

    parsing_started = False

    for page in document.pages:
        lines = page.text.splitlines()

        if not parsing_started:
            first_content_line = find_first_content_line(lines)

            if first_content_line is None:
                continue

            parsing_started = True
            lines = lines[first_content_line:]

        if not lines and current_kind is not None:
            current_end_page = page.pdf_page_number
            continue

        for line in lines:
            heading = get_heading(line)

            if heading is not None:
                kind, identifier, title = heading

                is_repeated_appendix = (
                    kind == "appendix"
                    and identifier is not None
                    and identifier in seen_appendix_identifiers
                )

                if is_repeated_appendix:
                    if current_kind is not None:
                        append_line(line, page.pdf_page_number)
                    continue

                # Future-year appendices can quote ARTICLE headings.
                if current_kind == "appendix" and kind == "article":
                    append_line(line, page.pdf_page_number)
                    continue

                save_current_unit()

                current_kind = kind
                current_identifier = identifier
                current_title = title
                current_start_page = page.pdf_page_number
                current_end_page = page.pdf_page_number
                current_lines = []
                current_page_segments = []

                append_line(line, page.pdf_page_number)

                if kind == "appendix" and identifier is not None:
                    seen_appendix_identifiers.add(identifier)

                continue

            if current_kind is not None:
                append_line(line, page.pdf_page_number)

    save_current_unit()

    return ParsedDocument(
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        units=units,
    )
