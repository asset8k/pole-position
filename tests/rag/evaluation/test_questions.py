from pathlib import Path

import pytest

from pole_position.corpus.manifest import load_manifest
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.evaluation.schemas import EvaluationDataset

PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUESTIONS_PATH = PROJECT_ROOT / "data/eval/questions.json"
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"
CHUNKS_DIR = PROJECT_ROOT / "artifacts/chunks"


def test_questions_dataset_is_valid_and_covers_planned_categories() -> None:
    dataset = EvaluationDataset.model_validate_json(
        QUESTIONS_PATH.read_text(encoding="utf-8")
    )

    assert 30 <= len(dataset.cases) <= 50
    assert {case.category for case in dataset.cases} == {
        "exact_lookup",
        "semantic",
        "numerical",
        "cross_document",
        "terminology",
        "unanswerable",
        "follow_up",
    }
    assert {
        source.source_kind
        for case in dataset.cases
        for source in case.expected_sources
    } == {"clause", "appendix", "preamble"}

    for case in dataset.cases:
        if case.category == "cross_document":
            assert len({source.document_id for source in case.expected_sources}) >= 2


def test_expected_sources_exist_in_current_corpus_and_on_labelled_pages() -> None:
    dataset = EvaluationDataset.model_validate_json(
        QUESTIONS_PATH.read_text(encoding="utf-8")
    )
    manifest = load_manifest(MANIFEST_PATH)
    documents = {document.document_id: document for document in manifest.documents}
    expected_ids = {
        source.document_id for case in dataset.cases for source in case.expected_sources
    }
    assert expected_ids <= documents.keys()
    assert {
        documents[document_id].section for document_id in expected_ids
    } == set("ABCDEF")

    missing = [
        document_id
        for document_id in sorted(expected_ids)
        if not (CHUNKS_DIR / f"{document_id}.json").is_file()
    ]
    if missing:
        pytest.skip("Generate local chunk artifacts to check evaluation source labels")

    chunk_documents = {
        document_id: ChunkedDocument.model_validate_json(
            (CHUNKS_DIR / f"{document_id}.json").read_text(encoding="utf-8")
        )
        for document_id in expected_ids
    }
    for case in dataset.cases:
        for source in case.expected_sources:
            metadata = documents[source.document_id]
            chunk_document = chunk_documents[source.document_id]
            assert metadata.is_active and metadata.season == 2026
            assert chunk_document.document_id == source.document_id
            assert chunk_document.source_sha256 == metadata.sha256
            matches = [
                chunk
                for chunk in chunk_document.chunks
                if chunk.document_id == source.document_id
                and chunk.source_kind == source.source_kind
                and chunk.clause_identifier == source.clause_identifier
                and chunk.appendix_identifier == source.appendix_identifier
            ]
            assert matches, f"Missing source in {case.id}: {source}"
            for page in source.pdf_pages:
                assert page <= metadata.page_count
                assert any(
                    chunk.start_pdf_page <= page <= chunk.end_pdf_page
                    and chunk.source_sha256 == metadata.sha256
                    for chunk in matches
                ), f"Missing PDF page {page} for {case.id}: {source}"
