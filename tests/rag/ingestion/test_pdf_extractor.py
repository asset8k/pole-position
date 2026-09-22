from pathlib import Path

import pytest

from pole_position.corpus.manifest import load_manifest
from pole_position.rag.ingestion.pdf_extractor import extract_pdf

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def test_extract_pdf_returns_all_section_a_pages() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    section_a = next(document for document in manifest.documents if document.section == "A")
    source_pdf = PROJECT_ROOT / section_a.source_path

    if not source_pdf.is_file():
        pytest.skip("Section A PDF is not available locally")

    extracted = extract_pdf(section_a, PROJECT_ROOT)

    assert extracted.document_id == section_a.document_id
    assert extracted.source_sha256 == section_a.sha256
    assert len(extracted.pages) == section_a.page_count
    assert [page.pdf_page_number for page in extracted.pages] == list(
        range(1, section_a.page_count + 1)
    )
    assert "GENERAL REGULATORY PROVISIONS" in extracted.pages[0].text
