from math import isfinite, sqrt

from openai import OpenAI

from pole_position.rag.contracts import RetrievalChunk

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_BATCH_SIZE = 100


def format_chunk_for_embedding(
    chunk: RetrievalChunk,
    document_title: str,
) -> str:
    """Add useful context to the text sent for embedding."""
    parts = [document_title.strip(), f"Section {chunk.section}"]

    if chunk.source_kind == "clause":
        parts.append(
            f"Article {chunk.article_identifier}, clause {chunk.clause_identifier}"
        )
        if chunk.clause_title:
            parts.append(chunk.clause_title)

    elif chunk.source_kind == "appendix":
        parts.append(f"Appendix {chunk.appendix_identifier}")
        if chunk.appendix_title:
            parts.append(chunk.appendix_title)

    else:
        parts.append("Preamble")

    parts.append("")
    parts.append(chunk.text)
    return "\n".join(parts)


def embed_texts(
    client: OpenAI,
    texts: list[str],
    *,
    model: str = EMBEDDING_MODEL,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[list[float]]:
    """Return one embedding per input text, in input order."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    if any(not text.strip() for text in texts):
        raise ValueError("Embedding inputs cannot be empty")

    vectors: list[list[float]] = []
    vector_size: int | None = None

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]

        response = client.embeddings.create(
            model=model,
            input=batch,
            encoding_format="float",
        )

        if len(response.data) != len(batch):
            raise RuntimeError("Embedding response count does not match input count")

        ordered = sorted(response.data, key=lambda item: item.index)

        for expected_index, item in enumerate(ordered):
            if item.index != expected_index:
                raise RuntimeError("Embedding response indexes are incomplete")

            vector = item.embedding

            if not vector or any(not isfinite(value) for value in vector):
                raise RuntimeError("Embedding response contains an invalid vector")

            if vector_size is None:
                vector_size = len(vector)
            elif len(vector) != vector_size:
                raise RuntimeError("Embedding vectors have inconsistent dimensions")

            vectors.append(vector)

    return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Vectors must be nonempty and have equal dimensions")

    left_length = sqrt(sum(value * value for value in left))
    right_length = sqrt(sum(value * value for value in right))

    if left_length == 0 or right_length == 0:
        raise ValueError("Cannot compare a zero-length vector")

    dot_product = sum(a * b for a, b in zip(left, right))
    return dot_product / (left_length * right_length)
