from pathlib import Path

from pole_position.corpus.manifest import load_manifest
from pole_position.corpus.verification import verify_local_corpus
from pole_position.rag.ingestion.pdf_extractor import extract_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def main() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    verify_local_corpus(manifest, PROJECT_ROOT)

    print(f"Verified {len(manifest.documents)} regulation documents")

    section_a = next(
        document for document in manifest.documents if document.section == "A"
    )

    extracted_document = extract_pdf(section_a, PROJECT_ROOT)

    artifact_directory = PROJECT_ROOT / "artifacts/extracted"
    artifact_directory.mkdir(parents=True, exist_ok=True)

    artifact_path = artifact_directory / f"{section_a.document_id}.json"
    artifact_path.write_text(
        extracted_document.model_dump_json(indent=2), encoding="utf-8"
    )

    print(f"Extracted {len(extracted_document.pages)} pages to {artifact_path}")


if __name__ == "__main__":
    main()
