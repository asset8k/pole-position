import re

from pole_position.rag.contracts import (
    ExtractedDocument,
    ParsedClause,
    ParsedClauseDocument,
)
from pole_position.rag.ingestion.structure_parser import (
    find_first_content_line,
    get_heading,
)

CLAUSE_HEADING_PATTERN = re.compile(r"^(?P<identifier>[A-F]\d+(?:\.\d+)+)$")


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

    parsing_started = False
    reached_appendices = False

    def save_current_clause() -> None:
        if (
            current_article_identifier is None
            or current_clause_identifier is None
            or current_start_page is None
            or current_end_page is None
        ):
            return

        clauses.append(
            ParsedClause(
                article_identifier=current_article_identifier,
                clause_identifier=current_clause_identifier,
                title=current_clause_title,
                text="\n".join(current_lines).strip(),
                start_pdf_page=current_start_page,
                end_pdf_page=current_end_page,
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
            ):
                save_current_clause()

                title_match = find_clause_title(lines, line_index)

                current_clause_identifier = clause_identifier
                current_clause_title = None
                current_start_page = page.pdf_page_number
                current_end_page = page.pdf_page_number
                current_lines = [line]

                if title_match is not None:
                    title_index, title = title_match
                    current_clause_title = title
                    current_lines.append(title)
                    line_index = title_index + 1
                    continue

                line_index += 1
                continue

            if current_clause_identifier is not None:
                current_lines.append(line)
                current_end_page = page.pdf_page_number

            line_index += 1

    save_current_clause()

    return ParsedClauseDocument(
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        clauses=clauses,
    )
