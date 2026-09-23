import re

from pole_position.rag.contracts import (
    ExtractedDocument,
    PageTextSegment,
    ParsedClause,
    ParsedClauseDocument,
)
from pole_position.rag.ingestion.structure_parser import (
    find_first_content_line,
    get_heading,
)

CLAUSE_HEADING_PATTERN = re.compile(r"^(?P<identifier>[A-F]\d+(?:\.\d+)+)$")


def looks_like_table_reference(lines: list[str], index: int) -> bool:
    following = [
        line.strip().casefold() for line in lines[index + 1 :] if line.strip()
    ][:8]

    return sum(line in {"yes", "no"} for line in following) >= 2


def get_clause_identifier(line: str) -> str | None:
    match = CLAUSE_HEADING_PATTERN.fullmatch(line)

    if match is None:
        return None

    return match.group("identifier")


def find_next_non_empty_line(
    lines: list[str],
    start_index: int,
) -> tuple[int, str] | None:
    for index in range(start_index, len(lines)):
        line = lines[index]

        if line:
            return index, line

    return None


def find_clause_title(
    lines: list[str],
    heading_index: int,
) -> tuple[int, str] | None:
    next_line = find_next_non_empty_line(lines, heading_index + 1)

    if next_line is None:
        return None

    title_index, title = next_line

    if get_clause_identifier(title) is not None:
        return None

    if title.endswith((".", ":", ";")):
        return None

    following_line = find_next_non_empty_line(lines, title_index + 1)

    if following_line is not None:
        _, following_text = following_line

        if get_clause_identifier(following_text) is not None:
            return title_index, title

        return None

    return title_index, title


def parse_clauses(document: ExtractedDocument) -> ParsedClauseDocument:
    clauses: list[ParsedClause] = []

    current_article_identifier: str | None = None
    current_clause_identifier: str | None = None
    current_clause_title: str | None = None
    current_start_page: int | None = None
    current_end_page: int | None = None
    current_lines: list[str] = []
    current_page_number: int | None = None
    current_page_lines: list[str] = []
    current_page_segments: list[PageTextSegment] = []

    parsing_started = False
    reached_appendices = False

    def save_page_segment() -> None:
        nonlocal current_page_number, current_page_lines

        if current_page_number is not None:
            text = "\n".join(current_page_lines).strip()

            if text:
                current_page_segments.append(
                    PageTextSegment(
                        pdf_page_number=current_page_number,
                        text=text,
                    )
                )

        current_page_number = None
        current_page_lines = []

    def add_clause_line(line: str, pdf_page_number: int) -> None:
        nonlocal current_page_number, current_end_page

        if current_page_number != pdf_page_number:
            save_page_segment()
            current_page_number = pdf_page_number

        current_lines.append(line)
        current_page_lines.append(line)
        current_end_page = pdf_page_number

    def save_current_clause() -> None:
        if (
            current_article_identifier is None
            or current_clause_identifier is None
            or current_start_page is None
            or current_end_page is None
        ):
            return

        save_page_segment()

        clauses.append(
            ParsedClause(
                article_identifier=current_article_identifier,
                clause_identifier=current_clause_identifier,
                title=current_clause_title,
                text="\n".join(current_lines).strip(),
                start_pdf_page=current_start_page,
                end_pdf_page=current_end_page,
                page_segments=current_page_segments.copy(),
            )
        )

    for page in document.pages:
        lines = [line.strip() for line in page.text.splitlines()]

        if not parsing_started:
            first_content_line = find_first_content_line(lines)

            if first_content_line is None:
                continue

            parsing_started = True
            lines = lines[first_content_line:]

        line_index = 0

        while line_index < len(lines):
            line = lines[line_index]
            unit_heading = get_heading(line)

            if unit_heading is not None:
                kind, identifier, _ = unit_heading

                if kind == "appendix":
                    save_current_clause()
                    current_article_identifier = None
                    current_clause_identifier = None
                    current_clause_title = None
                    current_lines = []
                    reached_appendices = True
                    line_index += 1
                    continue

                if kind == "article" and not reached_appendices:
                    save_current_clause()
                    current_article_identifier = identifier
                    current_clause_identifier = None
                    current_clause_title = None
                    current_lines = []
                    line_index += 1
                    continue

            clause_identifier = get_clause_identifier(line)

            if (
                clause_identifier is not None
                and current_article_identifier is not None
                and clause_identifier.startswith(f"{current_article_identifier}.")
                and not looks_like_table_reference(lines, line_index)
            ):
                save_current_clause()

                title_match = find_clause_title(lines, line_index)

                current_clause_identifier = clause_identifier
                current_clause_title = None
                current_start_page = page.pdf_page_number
                current_end_page = page.pdf_page_number
                current_lines = []
                current_page_number = None
                current_page_lines = []
                current_page_segments = []
                add_clause_line(line, page.pdf_page_number)

                if title_match is not None:
                    title_index, title = title_match
                    current_clause_title = title
                    add_clause_line(title, page.pdf_page_number)
                    line_index = title_index + 1
                    continue

                line_index += 1
                continue

            if current_clause_identifier is not None:
                add_clause_line(line, page.pdf_page_number)

            line_index += 1

    save_current_clause()

    return ParsedClauseDocument(
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        clauses=clauses,
    )
