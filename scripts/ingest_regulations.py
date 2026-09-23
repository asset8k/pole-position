from argparse import ArgumentParser
from pathlib import Path

from pole_position.corpus.manifest import load_manifest
from pole_position.corpus.verification import verify_local_corpus
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.ingestion.appendix_chunker import chunk_appendices
from pole_position.rag.ingestion.clause_chunker import chunk_clauses
from pole_position.rag.ingestion.clause_parser import parse_clauses
from pole_position.rag.ingestion.normalizer import normalize_document
from pole_position.rag.ingestion.pdf_extractor import extract_pdf
from pole_position.rag.ingestion.preamble_chunker import chunk_preamble
from pole_position.rag.ingestion.structure_parser import parse_document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--section", choices=("A", "B", "C", "D", "E", "F"))
    args = parser.parse_args()

    manifest = load_manifest(MANIFEST_PATH)
    verify_local_corpus(manifest, PROJECT_ROOT)

    print(f"Verified {len(manifest.documents)} regulation documents")

    section_document = next(
        document for document in manifest.documents if document.section == args.section
    )

    extracted_document = extract_pdf(section_document, PROJECT_ROOT)

    artifact_directory = PROJECT_ROOT / "artifacts/extracted"
    artifact_directory.mkdir(parents=True, exist_ok=True)

    artifact_path = artifact_directory / f"{section_document.document_id}.json"
    artifact_path.write_text(
        extracted_document.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"Extracted {len(extracted_document.pages)} pages to {artifact_path}")

    normalized_document = normalize_document(extracted_document)

    normalized_directory = PROJECT_ROOT / "artifacts/normalized"
    normalized_directory.mkdir(parents=True, exist_ok=True)

    normalized_path = normalized_directory / f"{section_document.document_id}.json"
    normalized_path.write_text(
        normalized_document.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"Normalized {len(normalized_document.pages)} pages to {normalized_path}")

    pages_without_text = [
        page.pdf_page_number
        for page in normalized_document.pages
        if not page.text.strip()
    ]

    if pages_without_text:
        print(
            "Pages with no extractable text after normalization "
            f"(not indexed): {pages_without_text}"
        )

    parsed_document = parse_document(normalized_document)

    parsed_directory = PROJECT_ROOT / "artifacts/parsed"
    parsed_directory.mkdir(parents=True, exist_ok=True)

    parsed_path = parsed_directory / f"{section_document.document_id}.json"
    parsed_path.write_text(parsed_document.model_dump_json(indent=2), encoding="utf-8")

    print(f"Parsed {len(parsed_document.units)} units to {parsed_path}")

    parsed_clauses = parse_clauses(normalized_document)

    clauses_directory = PROJECT_ROOT / "artifacts/clauses"
    clauses_directory.mkdir(parents=True, exist_ok=True)

    clauses_path = clauses_directory / f"{section_document.document_id}.json"
    clauses_path.write_text(parsed_clauses.model_dump_json(indent=2), encoding="utf-8")

    print(f"Parsed {len(parsed_clauses.clauses)} clauses to {clauses_path}")

    chunked_clauses = chunk_clauses(parsed_clauses)

    appendix_chunks, skipped_future, skipped_visual = chunk_appendices(
        parsed_document,
        section_document.section,
    )

    preamble_chunks = chunk_preamble(
        parsed_document,
        section_document.section,
    )

    chunked_document = ChunkedDocument(
        document_id=section_document.document_id,
        source_sha256=parsed_document.source_sha256,
        chunks=[*chunked_clauses.chunks, *appendix_chunks, *preamble_chunks],
    )

    chunks_directory = PROJECT_ROOT / "artifacts/chunks"
    chunks_directory.mkdir(parents=True, exist_ok=True)

    chunks_path = chunks_directory / f"{section_document.document_id}.json"
    chunks_path.write_text(
        chunked_document.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        f"Created {len(chunked_document.chunks)} chunks "
        f"({len(chunked_clauses.chunks)} clause, "
        f"{len(appendix_chunks)} appendix, "
        f"{len(preamble_chunks)} preamble) at {chunks_path}"
    )
    print(f"Skipped future-year appendices: {skipped_future}")
    print(f"Skipped visual-only appendices: {skipped_visual}")


if __name__ == "__main__":
    main()
