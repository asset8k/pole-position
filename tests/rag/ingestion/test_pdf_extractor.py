from pathlib import Path

import pytest
import pymupdf
from unittest.mock import Mock

from pole_position.corpus.manifest import load_manifest
from pole_position.rag.ingestion.pdf_extractor import extract_pdf, extract_current_page_text

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


def test_struck_deleted_text_is_removed_but_additions_and_underlines_remain() -> None:
    page = Mock()
    page.get_text.return_value = {"blocks": [{"lines": [
        {"spans": [{"text": "Deleted old rule", "char_flags": 17}]},
        {"spans": [{"text": "New pink rule", "char_flags": 16, "color": 16711935}]},
        {"spans": [{"text": "Underlined text", "char_flags": 18}]},
        {"spans": [{"text": "Use ", "char_flags": 16},
                   {"text": "old", "char_flags": 17},
                   {"text": "new wording", "char_flags": 16}]},
    ]}]}
    text = extract_current_page_text(page, "Unfiltered extraction")
    assert "Deleted" not in text
    assert "New pink rule\nUnderlined text\nUse new wording" in text
    assert page.get_text.call_args.kwargs["flags"] & pymupdf.TEXT_COLLECT_STYLES


def test_missed_single_glyph_does_not_leave_a_deleted_line_fragment() -> None:
    page = Mock()
    page.get_text.return_value = {"blocks": [{"lines": [{"spans": [
        {"text": "If the Of", "char_flags": 17},
        {"text": "f", "char_flags": 16},
        {"text": "icial Weather Service predicts rain", "char_flags": 17},
    ]}]}]}
    assert extract_current_page_text(page, "Old sentence") == "\n"


def test_pages_without_deletions_keep_original_line_breaks() -> None:
    page = Mock()
    page.get_text.return_value = {"blocks": [{"lines": [{"spans": [
        {"text": "Existing text", "char_flags": 16},
    ]}]}]}
    assert extract_current_page_text(page, "Original\nline breaks\n") == "Original\nline breaks\n"
