from argparse import Namespace
from contextlib import closing
from datetime import date
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pymupdf
import pytest
from openai import OpenAI
from qdrant_client import QdrantClient, models

from pole_position.corpus import updates
from pole_position.corpus.schemas import CorpusManifest, RegulationDocument
from pole_position.corpus.verification import calculate_sha256
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.indexing.qdrant_store import point_from_chunk
from pole_position.rag.retrieval.dense import retrieve_dense

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/update_regulations.py"
spec = importlib.util.spec_from_file_location("regulation_update_script", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def make_pdf(path: Path, section="B", issue=2, season=2026, published="01/10/2026",
             approved="30/09/2026", status="PUBLISHED", body=None, cover_title=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((40, 40), (
            f"{cover_title or f'{season} Formula 1 Regulations - Section {section}'}\nSECTION {section}: TEST\n"
            f"Version:\nIssue {issue:02d}\nStatus:\n{status}\nDate:\n{published}\n"
            f"WMSC approval date:\n{approved}\nCONTENTS:\nARTICLE {section}1: RULES\n3\n"
        ), fontsize=10)
        pdf.new_page().insert_text((40, 40), "Contents continued", fontsize=10)
        pdf.new_page().insert_text((40, 40), body or (
            f"ARTICLE {section}1: RULES\nAdvisory Committee: TEST\n"
            f"{section}1.1\nGeneral Rules\n{section}1.1.1\n"
            f"The permitted allocation is {issue}.\n"
        ), fontsize=10)
        pdf.save(path)
    return path


def make_project(root: Path, sections=("B",)):
    documents = []
    incoming = []
    for section in sections:
        old_pdf = make_pdf(root / f"regulations/old-{section}.pdf", section, issue=1,
                           published="01/01/2026", approved="01/01/2026")
        document = RegulationDocument(
            document_id=f"old-{section}", section=section, title=f"Section {section}",
            season=2026, issue_number=1, published_date=date(2026, 1, 1),
            wmsc_approval_date=date(2026, 1, 1), source_path=f"regulations/old-{section}.pdf",
            sha256=calculate_sha256(old_pdf), page_count=3, is_active=True,
        )
        updates.prepare_update(old_pdf, document, document, root)
        documents.append(document)
        incoming.append(make_pdf(root / f"incoming/{section}.pdf", section))
    manifest = CorpusManifest(documents=documents)
    manifest_path = root / "data/manifests/2026_f1_regulations.json"
    updates.atomic_write(manifest_path, manifest.model_dump_json(indent=2) + "\n")
    return manifest, manifest_path, incoming


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path)


def add_old_points(client, manifest, root):
    updates.ensure_collection(client, "test", updates.VECTOR_SIZE)
    for document in manifest.documents:
        chunked = ChunkedDocument.model_validate_json(
            (root / "artifacts/chunks" / f"{document.document_id}.json").read_text()
        )
        client.upsert("test", [point_from_chunk(chunk, [1.0] + [0.0] * 1535, document)
                               for chunk in chunked.chunks], wait=True)


def mock_embeddings(monkeypatch):
    embed = Mock(side_effect=lambda client, texts: [[1.0] + [0.0] * 1535 for _ in texts])
    monkeypatch.setattr(updates, "embed_texts", embed)
    return embed


def test_pdf_metadata_is_read_from_cover_not_filename(project):
    manifest, _, paths = project
    document = updates.read_pdf_document(paths[0], manifest)
    assert document.section == "B" and document.issue_number == 2
    assert document.published_date == date(2026, 10, 1)
    assert document.wmsc_approval_date == date(2026, 9, 30)
    assert document.page_count == 3
    assert document.sha256 == calculate_sha256(paths[0])
    assert document.sha256[:12] in document.document_id
    assert document.source_path.startswith("regulations/versions/")


@pytest.mark.parametrize("cover_title", [
    "2026 Formula 1: General Regulatory Provisions",
    "2026 Formula 1 Regulations: Financial Regulations (Power Unit Manufacturers)",
    "2026 Formula One Regulations - Section B",
])
def test_cover_title_variants_used_across_sections(project, tmp_path, cover_title):
    manifest, _, _ = project
    path = make_pdf(tmp_path / "variant.pdf", cover_title=cover_title)
    assert updates.read_pdf_document(path, manifest).season == 2026


@pytest.mark.parametrize(("changes", "error"), [
    ({"season": 2027}, "Wrong season"),
    ({"status": "DRAFT"}, "Only PUBLISHED"),
    ({"published": "01/01/2025", "approved": "01/01/2025"}, "older regulations"),
    ({"approved": "02/10/2026"}, "approval cannot"),
    ({"issue": 1}, "same issue number"),
])
def test_bad_metadata_cannot_be_activated(project, tmp_path, changes, error):
    manifest, _, _ = project
    path = make_pdf(tmp_path / "bad.pdf", **changes)
    with pytest.raises(ValueError, match=error):
        updates.read_pdf_document(path, manifest)


def test_same_issue_official_correction_requires_explicit_opt_in(project, tmp_path):
    manifest, _, _ = project
    path = make_pdf(tmp_path / "correction.pdf", issue=1)
    document = updates.read_pdf_document(path, manifest, allow_same_issue=True)
    assert document.issue_number == 1
    assert document.document_id != manifest.documents[0].document_id


def test_unchanged_input_is_a_noop_even_when_apply_is_requested(project, tmp_path, monkeypatch):
    manifest, manifest_path, _ = project
    original = manifest_path.read_bytes()
    prepare = Mock(wraps=updates.prepare_update)
    monkeypatch.setattr(updates, "prepare_update", prepare)
    embed = mock_embeddings(monkeypatch)
    args = Namespace(pdf=[tmp_path / manifest.documents[0].source_path], pdf_dir=None,
                     restore_manifest=None, apply=True, allow_same_issue=False)
    assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 0
    assert manifest_path.read_bytes() == original
    prepare.assert_not_called()
    embed.assert_not_called()


def test_duplicate_sections_are_rejected_before_preparation(project, monkeypatch):
    manifest, _, paths = project
    prepare = Mock()
    monkeypatch.setattr(updates, "prepare_update", prepare)
    with pytest.raises(ValueError, match="Multiple input PDFs"):
        updates.prepare_batch(paths * 2, manifest, paths[0].parents[1])
    prepare.assert_not_called()


def test_preview_prepares_artifacts_without_switch_or_model_calls(project, tmp_path, monkeypatch):
    _, manifest_path, paths = project
    original = manifest_path.read_bytes()
    embed = mock_embeddings(monkeypatch)
    args = Namespace(pdf=None, pdf_dir=paths[0].parent, restore_manifest=None,
                     apply=False, allow_same_issue=False)
    assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 0
    assert manifest_path.read_bytes() == original
    report = json.loads(next((tmp_path / "artifacts/updates").glob("*/report.json")).read_text())
    assert report["status"] == "prepared"
    assert report["updates"][0]["pages"] == 3
    assert report["proposed_active_chunks"] == 2
    embed.assert_not_called()


def test_unknown_appendix_fails_closed(project, tmp_path):
    manifest, _, _ = project
    body = "ARTICLE B1: RULES\nAdvisory Committee: TEST\nB1.1\nA rule.\nAPPENDIX B99: NEW RULES\nNew text."
    path = make_pdf(tmp_path / "unknown.pdf", body=body)
    with pytest.raises(ValueError, match="No indexing policy"):
        updates.prepare_batch([path], manifest, tmp_path)


def test_duplicate_clause_is_not_silently_deduplicated(project, tmp_path):
    manifest, _, _ = project
    body = "ARTICLE B1: RULES\nAdvisory Committee: TEST\nB1.1\nFirst rule.\nB1.1\nA different rule."
    path = make_pdf(tmp_path / "duplicate.pdf", body=body)
    with pytest.raises(ValueError, match="duplicate clause"):
        updates.prepare_batch([path], manifest, tmp_path)


def test_valid_page_number_with_wrong_excerpt_provenance_is_rejected(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    actual_chunker = updates.chunk_clauses

    def wrong_page_chunker(clauses):
        chunked = actual_chunker(clauses)
        chunked.chunks[0] = chunked.chunks[0].model_copy(
            update={"start_pdf_page": 2, "end_pdf_page": 2}
        )
        return chunked

    monkeypatch.setattr(updates, "chunk_clauses", wrong_page_chunker)
    with pytest.raises(ValueError, match="text/pages lost"):
        updates.prepare_batch(paths, manifest, tmp_path)


def test_malformed_pdf_layout_never_changes_the_current_manifest(project, tmp_path):
    _, manifest_path, _ = project
    original = manifest_path.read_bytes()
    path = make_pdf(tmp_path / "malformed.pdf", body="Scanned text is not available.")
    args = Namespace(pdf=[path], pdf_dir=None, restore_manifest=None, apply=False, allow_same_issue=False)
    assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 1
    assert manifest_path.read_bytes() == original


def test_stage_retry_reuses_points_and_audits_all_payloads(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        embed = mock_embeddings(monkeypatch)
        assert updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0]) == 2
        assert updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0]) == 0
        embed.assert_called_once()
        chunk = prepared[0].chunked.chunks[0]
        point = client.retrieve("test", ids=[updates._point_id(chunk.chunk_id)])[0]
        assert point.payload["is_active"] is False
        assert point.payload["embedding_model"] == updates.EMBEDDING_MODEL
        client.set_payload("test", {"text": "Corrupted stored text"}, points=[point.id])
        with pytest.raises(ValueError, match="payload mismatch"):
            updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0])
        assert embed.call_count == 1


def test_only_missing_staged_points_are_embedded_on_retry(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        embed = mock_embeddings(monkeypatch)
        updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0])
        chunk = prepared[0].chunked.chunks[-1]
        client.delete("test", points_selector=models.PointIdsList(points=[updates._point_id(chunk.chunk_id)]))
        assert updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0]) == 1
        assert len(embed.call_args.args[1]) == 1


def test_incompatible_embedding_dimensions_are_rejected_before_upsert(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        monkeypatch.setattr(updates, "embed_texts", lambda client, texts: [[1.0, 0.0] for _ in texts])
        before = client.count("test", exact=True).count
        with pytest.raises(ValueError, match="dimensions"):
            updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0])
        assert client.count("test", exact=True).count == before


def test_incomplete_or_concurrently_changed_corpus_cannot_activate(project, tmp_path, monkeypatch):
    manifest, manifest_path, paths = project
    original = manifest_path.read_text()
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    proposed = updates.replacement_manifest(manifest, prepared)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        with pytest.raises(ValueError, match="Incomplete stored"):
            updates.activate_manifest(tmp_path, manifest_path, original, proposed, client, "test")
        assert manifest_path.read_text() == original
        mock_embeddings(monkeypatch)
        updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0])
        updates.atomic_write(manifest_path, original + "\n")
        with pytest.raises(ValueError, match="Manifest changed"):
            updates.activate_manifest(tmp_path, manifest_path, original, proposed, client, "test")
        assert manifest_path.read_text() == original + "\n"


def test_all_six_sections_switch_together_and_rollback_preserves_history(tmp_path, monkeypatch):
    manifest, manifest_path, paths = make_project(tmp_path, tuple("ABCDEF"))
    original = manifest_path.read_text()
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    proposed = updates.replacement_manifest(manifest, prepared)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        mock_embeddings(monkeypatch)
        for update in prepared:
            updates.stage_document(client, Mock(spec=OpenAI), "test", update)
        assert manifest_path.read_text() == original
        assert updates.activate_manifest(tmp_path, manifest_path, original, proposed, client, "test") == []
        current = CorpusManifest.model_validate_json(manifest_path.read_text())
        assert {doc.document_id for doc in current.documents} == {u.document.document_id for u in prepared}
        assert len(current.documents) == 6
        assert client.count("test", exact=True).count == 24  # Both complete versions retained.
        old_id = updates._point_id("old-B:B1.1:0")
        assert client.retrieve("test", ids=[old_id])[0].payload["is_active"] is False
        updates.activate_manifest(tmp_path, manifest_path, manifest_path.read_text(), manifest, client, "test")
        assert CorpusManifest.model_validate_json(manifest_path.read_text()) == manifest
        assert client.retrieve("test", ids=[old_id])[0].payload["is_active"] is True


def test_dense_search_cannot_see_staged_or_retired_versions(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        mock_embeddings(monkeypatch)
        updates.stage_document(client, Mock(spec=OpenAI), "test", prepared[0])
        monkeypatch.setattr("pole_position.rag.retrieval.dense.embed_texts",
                            lambda client, texts: [[1.0] + [0.0] * 1535])
        for document_id in (manifest.documents[0].document_id, prepared[0].document.document_id):
            hits = retrieve_dense("allocation?", openai_client=Mock(spec=OpenAI), qdrant_client=client,
                                  collection_name="test", document_ids=(document_id,))
            assert hits and {hit.chunk.document_id for hit in hits} == {document_id}


def test_cli_apply_staging_failure_does_not_switch_manifest(project, tmp_path, monkeypatch):
    manifest, manifest_path, paths = project
    original = manifest_path.read_bytes()
    client = QdrantClient(":memory:")
    add_old_points(client, manifest, tmp_path)
    # Context managers are inert wrappers around an in-memory store, never real services.
    from contextlib import nullcontext
    from pole_position.config import settings
    monkeypatch.setattr(settings, "qdrant_collection", "test")
    monkeypatch.setattr("qdrant_client.QdrantClient", lambda **kwargs: client)
    monkeypatch.setattr("openai.OpenAI", lambda **kwargs: nullcontext(Mock()))
    stage = Mock(side_effect=RuntimeError("Simulated upsert failure"))
    monkeypatch.setattr(script, "stage_document", stage)
    args = Namespace(pdf=paths, pdf_dir=None, restore_manifest=None, apply=True, allow_same_issue=False)
    assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 1
    assert manifest_path.read_bytes() == original
    report = json.loads(next((tmp_path / "artifacts/updates").glob("*/report.json")).read_text())
    assert report["status"] == "failed" and report["manifest_changed"] is False
    stage.assert_called_once()
    client.close()


def test_cli_apply_and_restore_complete_workflow(project, tmp_path, monkeypatch):
    from contextlib import nullcontext
    from pole_position.config import settings

    manifest, manifest_path, paths = project
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        wrapper = Mock(spec=QdrantClient, wraps=client)
        wrapper.close = Mock()  # Keep the test's shared store open across invocations.
        monkeypatch.setattr("qdrant_client.QdrantClient", lambda **kwargs: wrapper)
        monkeypatch.setattr("openai.OpenAI", lambda **kwargs: nullcontext(Mock()))
        monkeypatch.setattr(settings, "qdrant_collection", "test")
        embed = mock_embeddings(monkeypatch)
        args = Namespace(pdf=paths, pdf_dir=None, restore_manifest=None, apply=True, allow_same_issue=False)
        assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 0
        current = CorpusManifest.model_validate_json(manifest_path.read_text())
        assert current.documents[0].issue_number == 2
        report_path = next((tmp_path / "artifacts/updates").glob("*/report.json"))
        assert json.loads(report_path.read_text())["status"] == "activated"
        assert embed.call_count == 1
        # A repeated upload does not perform another upsert or embedding call.
        before_calls = len(wrapper.mock_calls)
        assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 0
        assert len(wrapper.mock_calls) == before_calls
        backup = report_path.parent / "manifest.before.json"
        args = Namespace(pdf=None, pdf_dir=None, restore_manifest=backup, apply=True, allow_same_issue=False)
        assert script.run(args, root=tmp_path, manifest_path=manifest_path) == 0
        assert CorpusManifest.model_validate_json(manifest_path.read_text()) == manifest
        assert embed.call_count == 1  # Rollback needs no embeddings.
        assert client.count("test", exact=True).count == 4


def test_partial_batch_failure_can_resume_without_reembedding_completed_batches(project, tmp_path, monkeypatch):
    manifest, _, paths = project
    prepared, _ = updates.prepare_batch(paths, manifest, tmp_path)
    source = prepared[0].chunked.chunks[0]
    chunks = [source.model_copy(update={"chunk_id": f"{source.document_id}:B1.1:{i}",
                                        "chunk_index": i, "text": f"Allocation rule part {i}."}) for i in range(150)]
    update = updates.PreparedUpdate(prepared[0].previous, prepared[0].document,
        ChunkedDocument(document_id=source.document_id, source_sha256=source.source_sha256, chunks=chunks), {})
    with closing(QdrantClient(":memory:")) as client:
        add_old_points(client, manifest, tmp_path)
        embed = mock_embeddings(monkeypatch)
        actual_upsert = client.upsert
        calls = 0

        def intermittent_upsert(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Interrupted second batch")
            return actual_upsert(*args, **kwargs)

        monkeypatch.setattr(client, "upsert", intermittent_upsert)
        with pytest.raises(RuntimeError, match="Interrupted second batch"):
            updates.stage_document(client, Mock(spec=OpenAI), "test", update)
        assert updates.stage_document(client, Mock(spec=OpenAI), "test", update) == 50
        assert len(embed.call_args.args[1]) == 50
        assert len(updates.audit_document(client, "test", update.document, update.chunked)) == 150


def test_two_update_processes_cannot_share_the_same_project(tmp_path):
    with script.update_lock(tmp_path):
        with pytest.raises(ValueError, match="Another regulation update"):
            with script.update_lock(tmp_path):
                pytest.fail("Second updater obtained the lock")


def test_cli_options_accept_single_batch_and_rollback_inputs():
    parser = script.build_parser()
    assert parser.parse_args(["--pdf", "b.pdf", "d.pdf", "--apply"]).apply
    assert parser.parse_args(["--pdf-dir", "incoming"]).pdf_dir == Path("incoming")
    assert parser.parse_args(["--restore-manifest", "backup.json"]).restore_manifest == Path("backup.json")
    with pytest.raises(SystemExit):
        parser.parse_args(["--pdf", "a.pdf", "--pdf-dir", "incoming"])
