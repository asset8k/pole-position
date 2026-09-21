import hashlib
from pathlib import Path

import pymupdf

from pole_position.corpus.schemas import CorpusManifest

HASH_CHUNK_SIZE = 1024 * 1024


def calculate_sha256(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as source_file:
        while chunk := source_file.read(HASH_CHUNK_SIZE):
            hasher.update(chunk)

    return hasher.hexdigest()


def verify_local_corpus(manifest: CorpusManifest, project_root: Path) -> None:
    for document in manifest.documents:
        pdf_path = project_root / document.source_path

        if not pdf_path.is_file():
            raise FileNotFoundError(
                f"PDF for {document.document_id} was not found: {pdf_path}"
            )

        actual_sha256 = calculate_sha256(pdf_path)

        if actual_sha256 != document.sha256:
            raise ValueError(
                f"SHA-256 mismatch for {document.document_id}: "
                f"expected {document.sha256}, got {actual_sha256}"
            )

        with pymupdf.open(pdf_path) as pdf:
            actual_page_count = pdf.page_count

        if actual_page_count != document.page_count:
            raise ValueError(
                f"Page-count mismatch for {document.document_id}: "
                f"expected {document.page_count}, got {actual_page_count}"
            )
