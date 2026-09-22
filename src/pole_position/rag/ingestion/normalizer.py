import re

from pole_position.rag.contracts import ExtractedDocument, ExtractedPage

RUNNING_HEADER_PATTERNS = (
    re.compile(r"^SECTION [A-F]: .+$"),
    re.compile(r"^0\s+[A-F]$"),
    re.compile(r"^[A-F]\d+$"),
    re.compile(r"^2026 Formula 1.*$"),
    re.compile("^©2026 Fédération Internationale de l\u2019Automobile$"),
    re.compile(
        r"^\d{2} "
        r"(January|February|March|April|May|June|July|August|September|October|"
        r"November|December) "
        r"\d{4}$"
    ),
    re.compile(r"^Issue \d+$"),
)


def is_running_header(line: str) -> bool:
    return any(pattern.fullmatch(line) for pattern in RUNNING_HEADER_PATTERNS)


def normalize_page_text(raw_text: str) -> str:
    normalized_lines: list[str] = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()

        if is_running_header(line):
            continue

        if not line:
            if normalized_lines and normalized_lines[-1] != "":
                normalized_lines.append("")
            continue

        normalized_lines.append(line)

    return "\n".join(normalized_lines).strip()


def normalize_document(document: ExtractedDocument) -> ExtractedDocument:
    normalized_pages = [
        ExtractedPage(
            pdf_page_number=page.pdf_page_number,
            text=normalize_page_text(page.text),
        )
        for page in document.pages
    ]

    return ExtractedDocument(
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        pages=normalized_pages,
    )
