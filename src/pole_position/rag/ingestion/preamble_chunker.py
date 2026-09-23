from pole_position.rag.contracts import (
    ParsedDocument,
    RegulationSection,
    RetrievalChunk,
)
from pole_position.rag.ingestion.clause_chunker import (
    DEFAULT_MAX_CHARACTERS,
    split_clause_text,
)


def chunk_preamble(
    document: ParsedDocument,
    section: RegulationSection,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> list[RetrievalChunk]:
    if max_characters <= 0:
        raise ValueError("max_characters must be greater than zero")

    preambles = [unit for unit in document.units if unit.kind == "preamble"]

    if len(preambles) > 1:
        raise ValueError("Expected at most one preamble per document")

    chunks: list[RetrievalChunk] = []

    for unit in preambles:
        for segment in unit.page_segments:
            page_number = segment.pdf_page_number

            for chunk_index, text in enumerate(
                split_clause_text(segment.text, max_characters)
            ):
                chunks.append(
                    RetrievalChunk(
                        chunk_id=(
                            f"{document.document_id}:preamble:"
                            f"page-{page_number}:{chunk_index}"
                        ),
                        document_id=document.document_id,
                        source_sha256=document.source_sha256,
                        section=section,
                        source_kind="preamble",
                        chunk_index=chunk_index,
                        text=text,
                        start_pdf_page=page_number,
                        end_pdf_page=page_number,
                    )
                )

    return chunks
