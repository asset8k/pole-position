import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/prepare_deployment.py"
spec = importlib.util.spec_from_file_location("prepare_deployment_under_test", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.fixture
def corpus_project(tmp_path):
    root = tmp_path / "project"
    documents = []
    chunks_dir = root / "artifacts/chunks"
    chunks_dir.mkdir(parents=True)
    for section in "ABCDEF":
        document_id = f"test-section-{section.lower()}"
        sha = "a" * 64
        documents.append(dict(
            document_id=document_id, section=section, title=f"Section {section}",
            season=2026, issue_number=1, published_date="2026-10-01",
            wmsc_approval_date="2026-09-01", source_path=f"regulations/{section}.pdf",
            sha256=sha, page_count=1, is_active=True,
        ))
        chunk = dict(
            chunk_id=f"{document_id}:{section}1.1:0", document_id=document_id,
            source_sha256=sha, section=section, source_kind="clause",
            article_identifier=f"{section}1", clause_identifier=f"{section}1.1",
            chunk_index=0, text="A verified regulation", start_pdf_page=1, end_pdf_page=1,
        )
        (chunks_dir / f"{document_id}.json").write_text(json.dumps(dict(
            document_id=document_id, source_sha256=sha, chunks=[chunk],
        )))
    manifest_path = root / script.MANIFEST_PATH
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"documents": documents}))
    (root / ".env").write_text("SECRET=not-for-deployment")
    return root


def test_bundle_contains_all_six_sections_but_no_secrets(corpus_project, tmp_path):
    output = tmp_path / "bundle"
    original = (corpus_project / script.MANIFEST_PATH).read_bytes()
    summary = script.prepare_deployment(corpus_project, output)
    assert summary["active_chunks"] == 6
    assert summary["sections"] == dict.fromkeys("ABCDEF", 1)
    assert len(list((output / script.CHUNKS_PATH).glob("*.json"))) == 6
    assert not (output / ".env").exists()
    assert not (output / "regulations").exists()
    assert (corpus_project / script.MANIFEST_PATH).read_bytes() == original
    assert script.prepare_deployment(corpus_project, output) == summary


def test_missing_section_refuses_export(corpus_project, tmp_path):
    path = corpus_project / script.MANIFEST_PATH
    data = json.loads(path.read_text())
    data["documents"].pop()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="six active"):
        script.prepare_deployment(corpus_project, tmp_path / "bundle")


def test_hash_mismatch_refuses_export_before_writing(corpus_project, tmp_path):
    path = corpus_project / script.CHUNKS_PATH / "test-section-a.json"
    data = json.loads(path.read_text())
    data["source_sha256"] = "b" * 64
    path.write_text(json.dumps(data))
    output = tmp_path / "bundle"
    with pytest.raises(ValueError, match="does not match"):
        script.prepare_deployment(corpus_project, output)
    assert not output.exists()
