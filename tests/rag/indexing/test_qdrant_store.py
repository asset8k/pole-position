from datetime import date
from math import sqrt
from unittest.mock import patch
from uuid import UUID

import pytest
from qdrant_client import QdrantClient

from pole_position.corpus.schemas import RegulationDocument
from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk
from pole_position.rag.indexing.qdrant_store import (
    DENSE_VECTOR_NAME,
    ensure_collection,
    point_from_chunk,
    upsert_chunked_document,
)

DOCUMENT_ID = "fia-f1-2026-section-b-issue-08"
SOURCE_SHA256 = "a" * 64


def make_document() -> RegulationDocument:
    return RegulationDocument(
        document_id=DOCUMENT_ID,
        section="B",
        title="Sporting Regulations",
        season=2026,
        issue_number=8,
        published_date=date(2026, 8, 5),
        wmsc_approval_date=date(2026, 8, 3),
        source_path="regulations/section_b.pdf",
        sha256=SOURCE_SHA256,
        page_count=98,
        is_active=True,
    )


def make_chunk(*, chunk_id: str = f"{DOCUMENT_ID}:B8.2.8:0") -> RetrievalChunk:
    return RetrievalChunk(
        chunk_id=chunk_id,
        document_id=DOCUMENT_ID,
        source_sha256=SOURCE_SHA256,
        section="B",
        source_kind="clause",
        article_identifier="B8",
        clause_identifier="B8.2.8",
        clause_title="Power unit elements",
        chunk_index=0,
        text="Exceeding the allocation incurs a grid penalty.",
        start_pdf_page=42,
        end_pdf_page=42,
    )


def make_chunked_document(count: int) -> ChunkedDocument:
    return ChunkedDocument(
        document_id=DOCUMENT_ID,
        source_sha256=SOURCE_SHA256,
        chunks=[
            make_chunk(chunk_id=f"{DOCUMENT_ID}:B8.2.8:{index}")
            for index in range(count)
        ],
    )


def test_point_from_chunk_keeps_vector_and_citation_payload() -> None:
    chunk = make_chunk()
    vector = [0.1, 0.2, 0.3]

    point = point_from_chunk(chunk, vector, make_document())

    assert isinstance(point.id, str)
    assert UUID(point.id).version == 5
    assert point.vector == {DENSE_VECTOR_NAME: vector}
    assert point.payload is not None
    assert point.payload["chunk_id"] == chunk.chunk_id
    assert point.payload["document_id"] == DOCUMENT_ID
    assert point.payload["source_kind"] == "clause"
    assert point.payload["clause_identifier"] == "B8.2.8"
    assert point.payload["text"] == chunk.text
    assert point.payload["start_pdf_page"] == 42
    assert point.payload["end_pdf_page"] == 42
    assert point.payload["document_title"] == "Sporting Regulations"
    assert point.payload["season"] == 2026
    assert point.payload["issue_number"] == 8
    assert point.payload["published_date"] == "2026-08-05"
    assert point.payload["is_active"] is True


def test_point_from_chunk_id_is_stable_and_unique_per_chunk() -> None:
    document = make_document()
    vector = [0.1, 0.2]

    first = point_from_chunk(make_chunk(), vector, document)
    repeated = point_from_chunk(make_chunk(), vector, document)
    another = point_from_chunk(
        make_chunk(chunk_id=f"{DOCUMENT_ID}:B8.2.8:1"),
        vector,
        document,
    )

    assert first.id == repeated.id
    assert first.id != another.id


@pytest.mark.parametrize(
    ("document_changes", "message"),
    [
        ({"document_id": "another-document"}, "IDs do not match"),
        ({"section": "C"}, "sections do not match"),
        ({"sha256": "b" * 64}, "source hashes do not match"),
    ],
)
def test_point_from_chunk_rejects_wrong_document(
    document_changes: dict[str, str],
    message: str,
) -> None:
    document = make_document().model_copy(update=document_changes)

    with pytest.raises(ValueError, match=message):
        point_from_chunk(make_chunk(), [0.1, 0.2], document)


@pytest.mark.parametrize("vector", [[], [float("nan")], [float("inf")]])
def test_point_from_chunk_rejects_invalid_vector(vector: list[float]) -> None:
    with pytest.raises(ValueError, match="finite numbers"):
        point_from_chunk(make_chunk(), vector, make_document())


def test_ensure_collection_creates_and_reuses_compatible_collection() -> None:
    client = QdrantClient(":memory:")

    ensure_collection(client, "test_regulations", vector_size=3)
    ensure_collection(client, "test_regulations", vector_size=3)

    vectors = client.get_collection("test_regulations").config.params.vectors
    assert isinstance(vectors, dict)
    assert vectors[DENSE_VECTOR_NAME].size == 3


def test_ensure_collection_rejects_existing_wrong_dimension() -> None:
    client = QdrantClient(":memory:")
    ensure_collection(client, "test_regulations", vector_size=3)

    with pytest.raises(ValueError, match="incompatible vector settings"):
        ensure_collection(client, "test_regulations", vector_size=4)


def test_upsert_chunked_document_splits_points_into_batches() -> None:
    client = QdrantClient(":memory:")
    chunked_document = make_chunked_document(3)
    vectors = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]

    with patch.object(client, "upsert", wraps=client.upsert) as upsert_mock:
        count = upsert_chunked_document(
            client,
            "test_regulations",
            chunked_document,
            vectors,
            make_document(),
            batch_size=2,
        )

    assert count == 3
    assert [len(call.kwargs["points"]) for call in upsert_mock.call_args_list] == [
        2,
        1,
    ]
    assert all(call.kwargs["wait"] is True for call in upsert_mock.call_args_list)
    assert client.count("test_regulations", exact=True).count == 3


def test_upsert_chunked_document_rerun_replaces_points() -> None:
    client = QdrantClient(":memory:")
    chunked_document = make_chunked_document(2)
    document = make_document()

    upsert_chunked_document(
        client,
        "test_regulations",
        chunked_document,
        [[1.0, 0.0], [0.0, 1.0]],
        document,
    )
    updated_chunk = chunked_document.chunks[0].model_copy(
        update={"text": "Updated penalty wording."}
    )
    updated_document = chunked_document.model_copy(
        update={"chunks": [updated_chunk, chunked_document.chunks[1]]}
    )

    upsert_chunked_document(
        client,
        "test_regulations",
        updated_document,
        [[0.8, 0.2], [0.0, 1.0]],
        document,
    )

    point_id = point_from_chunk(updated_chunk, [0.8, 0.2], document).id
    retrieved = client.retrieve(
        "test_regulations", ids=[point_id], with_payload=True, with_vectors=True
    )
    assert client.count("test_regulations", exact=True).count == 2
    assert len(retrieved) == 1
    assert retrieved[0].payload is not None
    assert retrieved[0].payload["text"] == "Updated penalty wording."
    assert isinstance(retrieved[0].vector, dict)
    magnitude = sqrt(0.8**2 + 0.2**2)
    assert retrieved[0].vector[DENSE_VECTOR_NAME] == pytest.approx(
        [0.8 / magnitude, 0.2 / magnitude]
    )


@pytest.mark.parametrize("batch_size", [0, -1])
def test_upsert_chunked_document_rejects_invalid_batch_size(batch_size: int) -> None:
    client = QdrantClient(":memory:")

    with pytest.raises(ValueError, match="batch_size must be positive"):
        upsert_chunked_document(
            client,
            "test_regulations",
            make_chunked_document(1),
            [[1.0, 0.0]],
            make_document(),
            batch_size=batch_size,
        )

    assert not client.collection_exists("test_regulations")


def test_upsert_chunked_document_rejects_missing_vector_before_writing() -> None:
    client = QdrantClient(":memory:")

    with pytest.raises(ValueError, match="exactly one vector"):
        upsert_chunked_document(
            client,
            "test_regulations",
            make_chunked_document(2),
            [[1.0, 0.0]],
            make_document(),
        )

    assert not client.collection_exists("test_regulations")


def test_upsert_chunked_document_rejects_dimension_mismatch_before_writing() -> None:
    client = QdrantClient(":memory:")

    with pytest.raises(ValueError, match="same dimensions"):
        upsert_chunked_document(
            client,
            "test_regulations",
            make_chunked_document(2),
            [[1.0, 0.0], [0.0, 1.0, 0.0]],
            make_document(),
        )

    assert not client.collection_exists("test_regulations")


def test_upsert_chunked_document_validates_all_points_before_writing() -> None:
    client = QdrantClient(":memory:")

    with pytest.raises(ValueError, match="finite numbers"):
        upsert_chunked_document(
            client,
            "test_regulations",
            make_chunked_document(3),
            [[1.0, 0.0], [0.0, 1.0], [float("nan"), 0.0]],
            make_document(),
            batch_size=2,
        )

    assert not client.collection_exists("test_regulations")
