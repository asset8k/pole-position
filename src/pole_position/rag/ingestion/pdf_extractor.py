from pathlib import Path

import pymupdf

from pole_position.corpus.schemas import RegulationDocument
from pole_position.rag.contracts import ExtractedDocument, ExtractedPage


def extract_pdf(
    document: RegulationDocument,
    project_root: Path,
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
