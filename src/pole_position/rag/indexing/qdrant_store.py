from qdrant_client import QdrantClient, models

DENSE_VECTOR_NAME = "dense"

from math import isfinite
from uuid import NAMESPACE_URL, uuid5

from pole_position.corpus.schemas import RegulationDocument
from pole_position.rag.contracts import ChunkedDocument, RetrievalChunk


def ensure_collection(
    client: QdrantClient,
    collection_name: str,
    vector_size: int,
) -> None:
    if vector_size <= 0:
        raise ValueError("vector_size must be positive")

    if not client.collection_exists(collection_name=collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                )
            },
        )

    vectors = client.get_collection(collection_name).config.params.vectors
    if not isinstance(vectors, dict) or DENSE_VECTOR_NAME not in vectors:
        raise ValueError("Existing collection has no named dense vector")

    dense = vectors[DENSE_VECTOR_NAME]
    if dense.size != vector_size or dense.distance != models.Distance.COSINE:
        raise ValueError("Existing collection has incompatible vector settings")

    payload_schema = client.get_collection(collection_name).payload_schema or {}

    for field in ("document_id", "section"):
        if field not in payload_schema:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )


def point_from_chunk(
    chunk: RetrievalChunk,
    vector: list[float],
    document: RegulationDocument,
) -> models.PointStruct:
    if chunk.document_id != document.document_id:
        raise ValueError("Chunk and document IDs do not match")
    if chunk.section != document.section:
        raise ValueError("Chunk and document sections do not match")
    if chunk.source_sha256 != document.sha256:
        raise ValueError("Chunk and document source hashes do not match")
    if not vector or any(not isfinite(value) for value in vector):
        raise ValueError("Vector must contain finite numbers")

    point_id = str(uuid5(NAMESPACE_URL, f"pole-position:{chunk.chunk_id}"))

    return models.PointStruct(
        id=point_id,
        vector={DENSE_VECTOR_NAME: vector},
        payload={
            **chunk.model_dump(mode="json"),
            "document_title": document.title,
            "season": document.season,
            "issue_number": document.issue_number,
            "published_date": document.published_date.isoformat(),
            "is_active": document.is_active,
        },
    )


def upsert_chunked_document(
    client: QdrantClient,
    collection_name: str,
    chunked_document: ChunkedDocument,
    vectors: list[list[float]],
    document: RegulationDocument,
    *,
    batch_size: int = 100,
) -> int:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    chunks = chunked_document.chunks
    if len(chunks) != len(vectors):
        raise ValueError("Every chunk must have exactly one vector")

    vector_size = len(vectors[0])
    if any(len(vector) != vector_size for vector in vectors):
        raise ValueError("Vectors must have the same dimensions")

    # Validate and build every point before writing any batch.
    points = [
        point_from_chunk(chunk, vector, document)
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]

    ensure_collection(client, collection_name, vector_size)

    for start in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[start : start + batch_size],
            wait=True,
        )

    return len(points)
