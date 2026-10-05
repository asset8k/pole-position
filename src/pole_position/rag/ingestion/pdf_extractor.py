from pathlib import Path

import pymupdf

from pole_position.corpus.schemas import RegulationDocument
from pole_position.rag.contracts import ExtractedDocument, ExtractedPage


def extract_pdf(
    document: RegulationDocument,
    project_root: Path,
    *,
    exclude_struck_text: bool = False,
) -> ExtractedDocument:

    pdf_path = project_root / document.source_path

    pages: list[ExtractedPage] = []

    with pymupdf.open(pdf_path) as pdf:
        for page_index in range(pdf.page_count):
            page = pdf.load_page(page_index)

            raw_text = page.get_text("text")
            if not isinstance(raw_text, str):
                raise TypeError(
                    f"Expected text extraction to return str for page {page_index + 1}"
                )

            if exclude_struck_text:
                raw_text = extract_current_page_text(page, raw_text)

            pages.append(
                ExtractedPage(
                    pdf_page_number=page_index + 1,
                    text=raw_text,
                )
            )

    return ExtractedDocument(
        document_id=document.document_id,
        source_sha256=document.sha256,
        pages=pages,
    )


def extract_current_page_text(page: pymupdf.Page, raw_text: str) -> str:
    """Exclude revision deletions, not pink additions or underlined text.

    MuPDF detects strike-through vector decorations with TEXT_COLLECT_STYLES.
    Keep the original extraction on pages without deletions. On a deleted line,
    allow a few missed glyph decorations (e.g. a ligature) rather than leaving
    isolated characters from an otherwise entirely struck-out sentence.
    """
    data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_COLLECT_STYLES)
    lines = [line for block in data["blocks"] if "lines" in block for line in block["lines"]]
    if not any(span.get("char_flags", 0) & 1 for line in lines for span in line["spans"]):
        return raw_text
    result: list[str] = []
    for line in lines:
        spans = line["spans"]
        total = sum(len(span["text"].strip()) for span in spans)
        deleted = sum(len(span["text"].strip()) for span in spans if span.get("char_flags", 0) & 1)
        if total and deleted / total >= 0.85:
            continue
        text = "".join(span["text"] for span in spans if not span.get("char_flags", 0) & 1)
        result.append(text)
    return "\n".join(result) + "\n"
