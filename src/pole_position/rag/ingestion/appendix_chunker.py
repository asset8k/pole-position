from pole_position.rag.contracts import (
    ParsedDocument,
    RegulationSection,
    RetrievalChunk,
)
from pole_position.rag.ingestion.clause_chunker import (
    DEFAULT_MAX_CHARACTERS,
    split_clause_text,
)

CURRENT_APPENDIX_IDS = frozenset(
    {
        *(f"A{number}" for number in range(1, 9)),
        *(f"B{number}" for number in range(1, 5)),
        "C1",
        "C2",
        "C4",
        "C5",
        "C6",
        "D1",
        "E1",
        "E2",
        "F1",
    }
)

FUTURE_YEAR_APPENDIX_IDS = frozenset({"A9", "B5", "D2", "F2"})
VISUAL_ONLY_APPENDIX_IDS = frozenset({"C3"})


def chunk_appendices(
    document: ParsedDocument,
    section: RegulationSection,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> tuple[list[RetrievalChunk], list[str], list[str]]:
    if max_characters <= 0:
        raise ValueError("max_characters must be greater than zero")

    chunks: list[RetrievalChunk] = []
    skipped_future: list[str] = []
    skipped_visual: list[str] = []

    for unit in document.units:
        if unit.kind != "appendix":
            continue

        identifier = unit.identifier

        if identifier is None or not identifier.startswith(section):
            raise ValueError(f"Invalid appendix identifier: {identifier!r}")

        if identifier in FUTURE_YEAR_APPENDIX_IDS:
            skipped_future.append(identifier)
            continue

        if identifier in VISUAL_ONLY_APPENDIX_IDS:
            skipped_visual.append(identifier)
            continue

        if identifier not in CURRENT_APPENDIX_IDS:
            raise ValueError(
                f"No indexing policy for appendix {identifier}; review it explicitly"
            )

        for page_segment in unit.page_segments:
            page_number = page_segment.pdf_page_number
            page_chunks = split_clause_text(
                page_segment.text,
                max_characters,
            )

            for page_chunk_index, chunk_text in enumerate(page_chunks):
                chunks.append(
                    RetrievalChunk(
                        chunk_id=(
                            f"{document.document_id}:appendix:"
                            f"{identifier}:page-{page_number}:"
                            f"{page_chunk_index}"
                        ),
                        document_id=document.document_id,
                        source_sha256=document.source_sha256,
                        section=section,
                        source_kind="appendix",
                        appendix_identifier=identifier,
                        appendix_title=unit.title,
                        chunk_index=page_chunk_index,
                        text=chunk_text,
                        start_pdf_page=page_number,
                        end_pdf_page=page_number,
                    )
                )

    return chunks, skipped_future, skipped_visual
