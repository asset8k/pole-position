from dataclasses import dataclass

from openai import OpenAI
from qdrant_client import QdrantClient, models

from pole_position.corpus.schemas import RegulationSection
from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.indexing.embeddings import embed_texts
from pole_position.rag.indexing.qdrant_store import DENSE_VECTOR_NAME


@dataclass(frozen=True)
class DenseHit:
    chunk: RetrievalChunk
    score: float
    document_title: str


def retrieve_dense(
    question: str,
    *,
    openai_client: OpenAI,
    qdrant_client: QdrantClient,
    collection_name: str,
    top_k: int = 5,
    section: RegulationSection | None = None,
) -> list[DenseHit]:
    """Find chunks semantically similar to a question."""
    question = question.strip()

    if not question:
        raise ValueError("Question cannot be empty")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if not collection_name.strip():
        raise ValueError("Collection name cannot be empty")

    query_vector = embed_texts(openai_client, [question])[0]

    section_filter = None
    if section is not None:
        section_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="section",
                    match=models.MatchValue(value=section),
                )
            ]
        )

    response = qdrant_client.query_points(
        collection_name=collection_name,
        query=query_vector,
        using=DENSE_VECTOR_NAME,
        query_filter=section_filter,
        limit=top_k,
        with_payload=True,
        with_vectors=False,
    )

    results: list[DenseHit] = []
    for point in response.points:
        payload = point.payload
        if payload is None:
            raise RuntimeError(f"Qdrant point {point.id} has no payload")

        title = payload.get("document_title")
        if not isinstance(title, str) or not title.strip():
            raise RuntimeError(f"Qdrant point {point.id} has no document title")

        results.append(
            DenseHit(
                chunk=RetrievalChunk.model_validate(payload),
                score=point.score,
                document_title=title,
            )
        )

    return results
