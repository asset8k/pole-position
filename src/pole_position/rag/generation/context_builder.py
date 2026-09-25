from collections.abc import Sequence
from dataclasses import dataclass

from pole_position.rag.retrieval.dense import DenseHit

DEFAULT_MAX_CONTEXT_CHARS = 12_000


@dataclass(frozen=True)
class ContextBundle:
    """Prompt-ready evidence and the hits behind its citation labels."""

    text: str
    sources: dict[str, DenseHit]


def _location(hit: DenseHit) -> str:
    chunk = hit.chunk
    if chunk.source_kind == "clause":
        return f"Clause {chunk.clause_identifier} (Article {chunk.article_identifier})"
    if chunk.source_kind == "appendix":
        return f"Appendix {chunk.appendix_identifier}"
    return "Preamble"


def _page_label(hit: DenseHit) -> str:
    start = hit.chunk.start_pdf_page
    end = hit.chunk.end_pdf_page
    return str(start) if start == end else f"{start}-{end}"


def _format_source(source_id: str, hit: DenseHit) -> str:
    chunk = hit.chunk
    return (
        f"[{source_id}]\n"
        f"Document: {hit.document_title}\n"
        f"Document ID: {chunk.document_id}\n"
        f"Section: {chunk.section}\n"
        f"Location: {_location(hit)}\n"
        f"PDF page(s): {_page_label(hit)}\n"
        f"Text:\n{chunk.text}"
    )


def build_context(
    hits: Sequence[DenseHit],
    *,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> ContextBundle:
    """Select complete excerpts in rank order; never cut a cited excerpt mid-text.

    Character count is a simple size guard, not an exact model-token budget.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    blocks: list[str] = []
    sources: dict[str, DenseHit] = {}
    seen_chunk_ids: set[str] = set()
    used_chars = 0

    for hit in hits:
        chunk_id = hit.chunk.chunk_id
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)

        source_id = f"S{len(sources) + 1}"
        block = _format_source(source_id, hit)
        separator_length = 2 if blocks else 0
        if used_chars + separator_length + len(block) > max_chars:
            continue

        blocks.append(block)
        sources[source_id] = hit
        used_chars += separator_length + len(block)

    return ContextBundle(text="\n\n".join(blocks), sources=sources)
