from argparse import ArgumentParser
from pathlib import Path

from openai import OpenAI
from qdrant_client import QdrantClient

from pole_position.config import settings
from pole_position.corpus.manifest import load_manifest
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.indexing.embeddings import (
    embed_texts,
    format_chunk_for_embedding,
)
from pole_position.rag.indexing.qdrant_store import upsert_chunked_document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument(
        "--section",
        required=True,
        choices=("A", "B", "C", "D", "E", "F"),
    )
    args = parser.parse_args()

    manifest = load_manifest(MANIFEST_PATH)
    document = next(
        (
            doc
            for doc in manifest.documents
            if doc.section == args.section and doc.is_active
        ),
        None,
    )
    if document is None:
        raise ValueError(f"No active document for section {args.section}")

    chunks_path = PROJECT_ROOT / "artifacts/chunks" / f"{document.document_id}.json"
    chunked_document = ChunkedDocument.model_validate_json(
        chunks_path.read_text(encoding="utf-8")
    )

    if (
        chunked_document.document_id != document.document_id
        or chunked_document.source_sha256 != document.sha256
    ):
        raise ValueError("Chunk artifact does not match the manifest")

    if any(
        chunk.document_id != document.document_id
        or chunk.source_sha256 != document.sha256
        or chunk.section != document.section
        for chunk in chunked_document.chunks
    ):
        raise ValueError("A chunk does not match its manifest document")

    texts = [
        format_chunk_for_embedding(chunk, document.title)
        for chunk in chunked_document.chunks
    ]
    print(f"Loaded {len(texts)} Section {document.section} chunks")

    qdrant_client = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key.get_secret_value(),
    )
    # Check the connection before making paid embedding requests.
    qdrant_client.get_collections()

    openai_client = OpenAI(api_key=settings.openai_api_key.get_secret_value())
    vectors = embed_texts(openai_client, texts)
    print(f"Created {len(vectors)} embeddings")

    count = upsert_chunked_document(
        client=qdrant_client,
        collection_name=settings.qdrant_collection,
        chunked_document=chunked_document,
        vectors=vectors,
        document=document,
    )
    print(f"Upserted {count} points into {settings.qdrant_collection}")


if __name__ == "__main__":
    main()
