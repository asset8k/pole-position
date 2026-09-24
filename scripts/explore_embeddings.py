from pathlib import Path

from openai import OpenAI

from pole_position.config import settings
from pole_position.corpus.manifest import load_manifest
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.indexing.embeddings import (
    cosine_similarity,
    embed_texts,
    format_chunk_for_embedding,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"

QUESTION = (
    "What happens if a driver exceeds the permitted power unit element allocation?"
)

# A few relevant passages mixed with unrelated ones.
CHUNK_SUFFIXES = (
    "B8.2.2:0",
    "B8.2.2:1",
    "B8.2.3:0",
    "B8.2.8:0",
    "B3.1.1:0",
    "B3.2.1:0",
    "B3.5.1:0",
)


def main() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    document = next(doc for doc in manifest.documents if doc.section == "B")

    chunks_path = PROJECT_ROOT / "artifacts/chunks" / f"{document.document_id}.json"
    chunked_document = ChunkedDocument.model_validate_json(
        chunks_path.read_text(encoding="utf-8")
    )

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunked_document.chunks}
    chunks = [
        chunks_by_id[f"{document.document_id}:{suffix}"] for suffix in CHUNK_SUFFIXES
    ]

    chunk_texts = [
        format_chunk_for_embedding(chunk, document.title) for chunk in chunks
    ]

    client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    vectors = embed_texts(client, [*chunk_texts, QUESTION])

    chunk_vectors = vectors[:-1]
    query_vector = vectors[-1]

    ranked = sorted(
        (
            (cosine_similarity(query_vector, vector), chunk)
            for chunk, vector in zip(chunks, chunk_vectors, strict=True)
        ),
        key=lambda result: result[0],
        reverse=True,
    )

    print(f"Question: {QUESTION}\n")
    for position, (score, chunk) in enumerate(ranked, start=1):
        preview = chunk.text.replace("\n", " ")[:140]
        print(f"{position}. {score:.4f}  {chunk.chunk_id}")
        print(f"   {preview}...")


if __name__ == "__main__":
    main()
