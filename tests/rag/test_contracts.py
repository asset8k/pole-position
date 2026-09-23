import pytest
from pydantic import ValidationError

from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk

SOURCE_SHA256 = "a" * 64


def make_chunk(**overrides: object) -> RetrievalChunk:
    values: dict[str, object] = {
        "chunk_id": "fia-f1-2026-section-a-issue-03:A1.2.3:0",
        "document_id": "fia-f1-2026-section-a-issue-03",
        "source_sha256": SOURCE_SHA256,
        "section": "A",
        "source_kind": "clause",
        "article_identifier": "A1",
        "clause_identifier": "A1.2.3",
        "clause_title": None,
        "chunk_index": 0,
        "text": "The clause text used for retrieval.",
        "start_pdf_page": 5,
        "end_pdf_page": 6,
    }
    values.update(overrides)

    return RetrievalChunk.model_validate(values)


def test_retrieval_chunk_accepts_valid_provenance() -> None:
    chunk = make_chunk()

    assert chunk.section == "A"
    assert chunk.article_identifier == "A1"
    assert chunk.clause_identifier == "A1.2.3"
    assert chunk.chunk_index == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"chunk_index": -1}, "greater than or equal to 0"),
        ({"section": "B"}, "Article identifier must belong to its Section"),
        (
            {"clause_identifier": "A2.1"},
            "Clause identifier must belong to its parent Article",
        ),
        (
            {"end_pdf_page": 4},
            "Chunk end PDF page cannot precede its start PDF page",
        ),
    ],
)
def test_retrieval_chunk_rejects_invalid_metadata(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        make_chunk(**overrides)


def test_chunked_document_accepts_retrieval_chunks() -> None:
    chunk = make_chunk()

    document = ChunkedDocument(
        document_id=chunk.document_id,
        source_sha256=chunk.source_sha256,
        chunks=[chunk],
    )

    assert document.document_id == chunk.document_id
    assert document.source_sha256 == chunk.source_sha256
    assert document.chunks == [chunk]
