import re
from typing import cast

from pole_position.rag.contracts import (
    ChunkedDocument,
    ParsedClauseDocument,
    RegulationSection,
    RetrievalChunk,
)

DEFAULT_MAX_CHARACTERS = 1200
LIST_MARKER_PERIOD_TOKEN = "__LIST_MARKER_PERIOD__"

LIST_ITEM_MARKER_PATTERN = re.compile(
    r"(?<!\w)(?P<marker>(?:\d+|[ivxlcdm]+|[a-z]))\.(?=\s)",
    re.IGNORECASE,
)


def protect_list_item_markers(text: str) -> str:
    return LIST_ITEM_MARKER_PATTERN.sub(
        lambda match: f"{match.group('marker')}{LIST_MARKER_PERIOD_TOKEN}",
        text,
    )


def split_at_word_boundaries(text: str, max_characters: int) -> list[str]:
    normalized_text = " ".join(text.split())
    chunks: list[str] = []
    remaining_text = normalized_text

    while len(remaining_text) > max_characters:
        split_index = remaining_text.rfind(" ", 0, max_characters + 1)

        if split_index <= 0:
            split_index = max_characters
        else:
            last_word = remaining_text[:split_index].rsplit(" ", 1)[-1]

            if re.fullmatch(r"(?:\d+|[a-z]|[ivxlcdm]+)\.", last_word):
                previous_space = remaining_text.rfind(" ", 0, split_index)

                if previous_space > 0:
                    split_index = previous_space

        chunks.append(remaining_text[:split_index].strip())
        remaining_text = remaining_text[split_index:].strip()

    if remaining_text:
        chunks.append(remaining_text)

    return chunks


def split_long_paragraph(paragraph: str, max_characters: int) -> list[str]:
    normalized_paragraph = " ".join(paragraph.split())

    if len(normalized_paragraph) <= max_characters:
        return [normalized_paragraph]

    protected_paragraph = protect_list_item_markers(normalized_paragraph)

    sentences = re.split(r"(?<=[.!?])\s+", protected_paragraph)
    sentences = [
        sentence.replace(LIST_MARKER_PERIOD_TOKEN, ".") for sentence in sentences
    ]

    if len(sentences) == 1:
        return split_at_word_boundaries(normalized_paragraph, max_characters)

    chunks: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        candidate = f"{current_chunk} {sentence}".strip()

        if len(candidate) <= max_characters:
            current_chunk = candidate
            continue

        if current_chunk:
            chunks.append(current_chunk)

        if len(sentence) <= max_characters:
            current_chunk = sentence
        else:
            chunks.extend(split_at_word_boundaries(sentence, max_characters))
            current_chunk = ""

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def split_clause_text(text: str, max_characters: int) -> list[str]:
    if max_characters <= 0:
        raise ValueError("max_characters must be greater than zero")

    paragraphs = [
        paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()
    ]

    chunks: list[str] = []
    current_chunk = ""

    for paragraph in paragraphs:
        paragraph_chunks = split_long_paragraph(paragraph, max_characters)

        for paragraph_chunk in paragraph_chunks:
            candidate = f"{current_chunk}\n\n{paragraph_chunk}".strip()

            if len(candidate) <= max_characters:
                current_chunk = candidate
                continue

            if current_chunk:
                chunks.append(current_chunk)

            current_chunk = paragraph_chunk

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def chunk_clauses(
    document: ParsedClauseDocument,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> ChunkedDocument:
    chunks: list[RetrievalChunk] = []

    for clause in document.clauses:
        chunk_index = 0

        for page_segment in clause.page_segments:
            page_chunks = split_clause_text(page_segment.text, max_characters)

            for chunk_text in page_chunks:
                chunks.append(
                    RetrievalChunk(
                        chunk_id=(
                            f"{document.document_id}:"
                            f"{clause.clause_identifier}:"
                            f"{chunk_index}"
                        ),
                        document_id=document.document_id,
                        source_sha256=document.source_sha256,
                        section=cast(RegulationSection, clause.article_identifier[0]),
                        source_kind="clause",
                        article_identifier=clause.article_identifier,
                        clause_identifier=clause.clause_identifier,
                        clause_title=clause.title,
                        chunk_index=chunk_index,
                        text=chunk_text,
                        start_pdf_page=page_segment.pdf_page_number,
                        end_pdf_page=page_segment.pdf_page_number,
                    )
                )
                chunk_index += 1

    return ChunkedDocument(
        document_id=document.document_id,
        source_sha256=document.source_sha256,
        chunks=chunks,
    )
