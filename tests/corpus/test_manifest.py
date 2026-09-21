from pathlib import Path

from pole_position.corpus.manifest import load_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def test_load_manifest() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.manifest_version == 1
    assert len(manifest.documents) == 6

    sections = {document.section for document in manifest.documents}
    assert sections == {"A", "B", "C", "D", "E", "F"}

    assert all(document.season == 2026 for document in manifest.documents)
    assert all(document.is_active for document in manifest.documents)
