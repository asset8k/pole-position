import hashlib
import importlib.util
import json
import sys
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import SecretStr, ValidationError

from pole_position.rag.contracts import RetrievalChunk
from pole_position.rag.evaluation.metrics import score_retrieval, summarize_metrics
from pole_position.rag.evaluation.runner import (
    CaseEvaluation,
    EvaluationReport,
    MethodEvaluation,
    RetrievalMethod,
)
from pole_position.rag.evaluation.schemas import (
    EvaluationCase,
    EvaluationDataset,
    ExpectedSource,
)

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/evaluate_retrieval.py"
spec = importlib.util.spec_from_file_location(
    "evaluation_script_under_test", SCRIPT_PATH
)
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def make_case(case_id: str = "pass") -> EvaluationCase:
    return EvaluationCase(
        id=case_id,
        category="semantic",
        question="Which tyre rule applies?",
        answerable=True,
        expected_sources=[
            ExpectedSource(
                document_id="test-section-b",
                source_kind="clause",
                clause_identifier="B1.1",
                pdf_pages=[10],
            )
        ],
        expected_facts=["A verified tyre rule."],
    )


def make_dataset() -> EvaluationDataset:
    return EvaluationDataset(
        cases=[
            make_case(),
            make_case("miss"),
            EvaluationCase(
                id="unanswerable",
                category="unanswerable",
                question="What is my home address?",
                answerable=False,
            ),
        ]
    )


def make_report(
    dataset: EvaluationDataset,
    *,
    collection_name: str = "test-collection",
    model: str = "test-model",
    candidate_k: int = 20,
    rrf_k: int = 60,
    include_reranking: bool = True,
) -> EvaluationReport:
    chunk = RetrievalChunk(
        chunk_id="test-section-b:B1.1:0",
        document_id="test-section-b",
        source_sha256="a" * 64,
        section="B",
        source_kind="clause",
        article_identifier="B1",
        clause_identifier="B1.1",
        chunk_index=0,
        text="A verified tyre rule — fédération.",
        start_pdf_page=10,
        end_pdf_page=10,
    )
    methods: list[RetrievalMethod] = ["dense", "hybrid"]
    if include_reranking:
        methods.append("hybrid_reranked")
    results = []
    for case in dataset.cases:
        chunks = [] if case.id == "miss" else [chunk]
        results.append(
            CaseEvaluation(
                case_id=case.id,
                category=case.category,
                question=case.question,
                retrieval_question=case.question,
                answerable=case.answerable,
                methods={
                    method: MethodEvaluation(chunks, score_retrieval(case, chunks))
                    for method in methods
                },
            )
        )
    return EvaluationReport(
        collection_name=collection_name,
        model=model,
        candidate_k=candidate_k,
        rrf_k=rrf_k,
        include_reranking=include_reranking,
        cases=results,
        summaries={
            method: summarize_metrics(
                [case.methods[method].metrics for case in results]
            )
            for method in methods
        },
    )


@pytest.fixture(autouse=True)
def prevent_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected use of a remote dependency fails instead of reaching the network."""
    monkeypatch.setattr(
        script,
        "settings",
        SimpleNamespace(
            answer_model="test-model",
            qdrant_collection="test-collection",
            openai_api_key=SecretStr("test-openai-key-not-a-real-secret"),
            qdrant_api_key=SecretStr("test-qdrant-key-not-a-real-secret"),
            qdrant_url="https://example.invalid",
        ),
    )
    for name in ("OpenAI", "QdrantClient", "load_sparse_corpus", "run_evaluation"):
        monkeypatch.setattr(
            script, name, Mock(side_effect=AssertionError(f"Unexpected call to {name}"))
        )


@dataclass
class CliHarness:
    monkeypatch: pytest.MonkeyPatch
    dataset: EvaluationDataset
    dataset_path: Path
    manifest_path: Path
    chunks_dir: Path
    output_path: Path
    reports_dir: Path
    openai_factory: MagicMock
    openai_client: Mock
    qdrant_factory: Mock
    qdrant_client: Mock
    sparse_loader: Mock
    sparse_corpus: Mock
    runner: Mock
    saver: Mock

    def run(self, *arguments: str, default_output: bool = False) -> None:
        argv = [str(SCRIPT_PATH), "--dataset", str(self.dataset_path)]
        if not default_output:
            argv.extend(["--output", str(self.output_path)])
        self.monkeypatch.setattr(sys, "argv", [*argv, *arguments])
        script.main()

    def read_report(self) -> dict[str, Any]:
        return json.loads(self.output_path.read_text(encoding="utf-8"))


@pytest.fixture
def cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CliHarness:
    dataset = make_dataset()
    dataset_path = tmp_path / "questions.json"
    dataset_path.write_text(dataset.model_dump_json(), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text('{"documents": []}', encoding="utf-8")
    chunks_dir = tmp_path / "chunks"
    reports_dir = tmp_path / "reports"
    openai_factory = MagicMock()
    openai_client = Mock()
    openai_factory.return_value.__enter__.return_value = openai_client
    qdrant_client = Mock()
    qdrant_factory = Mock(return_value=qdrant_client)
    sparse_corpus = Mock()
    sparse_loader = Mock(return_value=sparse_corpus)

    def evaluate(
        selected: EvaluationDataset,
        *,
        openai_client: object,
        qdrant_client: object,
        sparse_corpus: object,
        collection_name: str,
        model: str,
        candidate_k: int,
        rrf_k: int,
        include_reranking: bool,
    ) -> EvaluationReport:
        return make_report(
            selected,
            collection_name=collection_name,
            model=model,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
            include_reranking=include_reranking,
        )

    evaluation_mock = Mock(side_effect=evaluate)
    saver = Mock(wraps=script.save_report)
    monkeypatch.setattr(script, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(script, "CHUNKS_DIR", chunks_dir)
    monkeypatch.setattr(script, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(script, "OpenAI", openai_factory)
    monkeypatch.setattr(script, "QdrantClient", qdrant_factory)
    monkeypatch.setattr(script, "load_sparse_corpus", sparse_loader)
    monkeypatch.setattr(script, "run_evaluation", evaluation_mock)
    monkeypatch.setattr(script, "save_report", saver)
    return CliHarness(
        monkeypatch, dataset, dataset_path, manifest_path, chunks_dir,
        tmp_path / "nested/reports/result.json", reports_dir,
        openai_factory, openai_client, qdrant_factory, qdrant_client,
        sparse_loader, sparse_corpus, evaluation_mock, saver,
    )


def test_argument_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT_PATH)])
    args = script.parse_args()
    assert args.dataset == script.DATASET_PATH
    assert args.output is args.limit is args.case_id is None
    assert args.candidate_k == 20
    assert args.rrf_k == 60
    assert args.model == "test-model"
    assert args.no_rerank is False


def test_argument_overrides_and_repeated_case_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", [
        str(SCRIPT_PATH), "--dataset", "custom.json", "--output", "report.json",
        "--limit", "2", "--case-id", "pass", "--case-id", "miss",
        "--candidate-k", "10", "--rrf-k", "30", "--model", "custom-model",
        "--no-rerank",
    ])
    args = script.parse_args()
    assert args.dataset == Path("custom.json")
    assert args.output == Path("report.json")
    assert args.limit == 2
    assert args.case_id == ["pass", "miss"]
    assert args.candidate_k == 10
    assert args.rrf_k == 30
    assert args.model == "custom-model"
    assert args.no_rerank is True


@pytest.mark.parametrize(
    "arguments",
    [
        ["--limit", "0"], ["--limit", "-1"], ["--limit", "not-an-integer"],
        ["--candidate-k", "9"], ["--candidate-k", "21"],
        ["--rrf-k", "0"], ["--rrf-k", "-1"], ["--model", " "],
    ],
)
def test_invalid_arguments_exit_before_external_calls(
    cli: CliHarness, arguments: list[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.run(*arguments)
    assert exc_info.value.code == 2
    cli.openai_factory.assert_not_called()
    cli.qdrant_factory.assert_not_called()
    cli.sparse_loader.assert_not_called()
    assert not cli.output_path.exists()


@pytest.mark.parametrize(
    ("case_ids", "limit", "expected"),
    [
        (None, None, ["pass", "miss", "unanswerable"]),
        (None, 1, ["pass"]),
        (None, 100, ["pass", "miss", "unanswerable"]),
        (["unanswerable", "pass", "pass"], None, ["pass", "unanswerable"]),
        (["unanswerable", "pass"], 1, ["pass"]),
    ],
)
def test_selection_preserves_order_filters_then_limits_without_mutation(
    case_ids: list[str] | None, limit: int | None, expected: list[str]
) -> None:
    dataset = make_dataset()
    original = dataset.model_dump()
    selected = script.select_dataset(dataset, Namespace(case_id=case_ids, limit=limit))
    assert [case.id for case in selected.cases] == expected
    assert dataset.model_dump() == original


def test_unknown_case_id_fails_before_external_calls(cli: CliHarness) -> None:
    with pytest.raises(ValueError, match="Unknown case IDs.*missing"):
        cli.run("--case-id", "missing")
    cli.sparse_loader.assert_not_called()
    cli.openai_factory.assert_not_called()
    cli.qdrant_factory.assert_not_called()
    assert not cli.output_path.exists()


@pytest.mark.parametrize("status", ["running", "completed", "failed"])
def test_save_report_serializes_rankings_metrics_metadata_and_unicode(
    tmp_path: Path, status: str
) -> None:
    dataset = make_dataset()
    report = make_report(dataset)
    output = tmp_path / "report.json"
    script.save_report(
        output, report, dataset,
        dataset_sha256="b" * 64, manifest_sha256="c" * 64,
        started_at="2026-10-05T09:00:00+00:00", elapsed_seconds=1.23456,
        status=status,
    )
    text = output.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["status"] == status
    assert data["selected_cases"] == data["completed_cases"] == 3
    assert data["dataset_sha256"] == "b" * 64
    assert data["manifest_sha256"] == "c" * 64
    assert data["started_at"] == "2026-10-05T09:00:00+00:00"
    assert data["updated_at"].endswith("+00:00")
    assert data["elapsed_seconds"] == 1.235
    assert data["embedding_model"] == script.EMBEDDING_MODEL
    assert data["dataset"] == dataset.model_dump(mode="json")
    assert "fédération" in text
    assert text.endswith("\n")
    assert script.REPORT_ADAPTER.validate_python(data["report"]) == report


def test_main_saves_checkpoints_and_aggregates_all_completed_cases(
    cli: CliHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.run()
    data = cli.read_report()
    assert data["status"] == "completed"
    assert data["completed_cases"] == data["selected_cases"] == 3
    assert data["dataset_sha256"] == hashlib.sha256(
        cli.dataset_path.read_bytes()
    ).hexdigest()
    assert data["manifest_sha256"] == hashlib.sha256(
        cli.manifest_path.read_bytes()
    ).hexdigest()
    assert [case["case_id"] for case in data["report"]["cases"]] == [
        "pass", "miss", "unanswerable"
    ]
    for summary in data["report"]["summaries"].values():
        assert summary == {
            "evaluated_cases": 2, "skipped_cases": 1,
            "recall_at_5": 0.5, "recall_at_10": 0.5, "mrr_at_10": 0.5,
        }
    assert [call.kwargs["status"] for call in cli.saver.call_args_list] == [
        "running", "running", "running", "running", "completed"
    ]
    assert [len(call.args[1].cases) for call in cli.saver.call_args_list] == [
        0, 1, 2, 3, 3
    ]
    cli.sparse_loader.assert_called_once_with(cli.manifest_path, cli.chunks_dir)
    assert cli.runner.call_count == 3
    for call, expected_case in zip(
        cli.runner.call_args_list, cli.dataset.cases, strict=True
    ):
        assert call.args[0].cases == [expected_case]
        assert call.kwargs == {
            "openai_client": cli.openai_client,
            "qdrant_client": cli.qdrant_client,
            "sparse_corpus": cli.sparse_corpus,
            "collection_name": "test-collection",
            "model": "test-model", "candidate_k": 20, "rrf_k": 60,
            "include_reranking": True,
        }
    cli.openai_factory.assert_called_once()
    cli.qdrant_factory.assert_called_once()
    cli.qdrant_client.close.assert_called_once_with()
    cli.openai_factory.return_value.__exit__.assert_called_once()
    output = capsys.readouterr().out
    assert "[3/3] unanswerable" in output
    assert "RETRIEVAL SUMMARY" in output
    assert "excluded unanswerable: 1" in output
    assert "Saved report:" in output


def test_main_forwards_options_and_saves_only_selected_cases(cli: CliHarness) -> None:
    cli.run(
        "--case-id", "unanswerable", "--case-id", "pass", "--limit", "1",
        "--candidate-k", "10", "--rrf-k", "30", "--model", " custom-model ",
        "--no-rerank",
    )
    data = cli.read_report()
    assert data["selected_cases"] == data["completed_cases"] == 1
    assert [case["id"] for case in data["dataset"]["cases"]] == ["pass"]
    assert data["report"]["model"] == "custom-model"
    assert data["report"]["candidate_k"] == 10
    assert data["report"]["rrf_k"] == 30
    assert data["report"]["include_reranking"] is False
    assert set(data["report"]["summaries"]) == {"dense", "hybrid"}
    assert cli.runner.call_args.kwargs["include_reranking"] is False
    assert cli.runner.call_count == 1


def test_default_report_name_is_created_under_reports_directory(
    cli: CliHarness,
) -> None:
    cli.run("--limit", "1", default_output=True)
    reports = list(cli.reports_dir.glob("retrieval-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text())["status"] == "completed"
    assert not cli.output_path.exists()


@pytest.mark.parametrize("completed_before_failure", [0, 1])
def test_failure_saves_partial_results_reraises_and_closes_clients(
    cli: CliHarness,
    completed_before_failure: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = RuntimeError("Mock evaluation failed")
    successful_reports = [
        make_report(EvaluationDataset(cases=[case]))
        for case in cli.dataset.cases[:completed_before_failure]
    ]
    cli.runner.side_effect = [*successful_reports, error]
    with pytest.raises(RuntimeError, match="Mock evaluation failed") as exc_info:
        cli.run()
    assert exc_info.value is error
    data = cli.read_report()
    assert data["status"] == "failed"
    assert data["selected_cases"] == 3
    assert data["completed_cases"] == completed_before_failure
    assert len(data["report"]["cases"]) == completed_before_failure
    assert cli.runner.call_count == completed_before_failure + 1
    assert cli.saver.call_args.kwargs["status"] == "failed"
    assert not any(
        call.kwargs["status"] == "completed" for call in cli.saver.call_args_list
    )
    if completed_before_failure:
        assert data["report"]["cases"][0]["case_id"] == "pass"
        for summary in data["report"]["summaries"].values():
            assert summary["evaluated_cases"] == 1
            assert summary["recall_at_5"] == 1.0
    else:
        assert data["report"]["summaries"] == {}
    cli.qdrant_client.close.assert_called_once_with()
    cli.openai_factory.return_value.__exit__.assert_called_once()
    output = capsys.readouterr().out
    assert "Completed results are saved" in output
    assert "RETRIEVAL SUMMARY" not in output


def test_existing_output_is_not_overwritten_or_evaluated(cli: CliHarness) -> None:
    cli.output_path.parent.mkdir(parents=True)
    cli.output_path.write_text("Keep this existing report.", encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        cli.run()
    assert exc_info.value.code == 2
    assert cli.output_path.read_text() == "Keep this existing report."
    cli.sparse_loader.assert_not_called()
    cli.openai_factory.assert_not_called()
    cli.runner.assert_not_called()


@pytest.mark.parametrize(
    "problem", ["invalid-json", "missing-file", "duplicate-labels"]
)
def test_invalid_dataset_fails_before_corpus_loading_or_api_calls(
    cli: CliHarness, problem: str
) -> None:
    if problem == "invalid-json":
        cli.dataset_path.write_text("not JSON", encoding="utf-8")
        expected_error = ValidationError
    elif problem == "missing-file":
        cli.monkeypatch.setattr(
            cli, "dataset_path", cli.dataset_path.with_name("missing.json")
        )
        expected_error = FileNotFoundError
    else:
        # A bad label in a later case must be caught before evaluating the first.
        case = cli.dataset.cases[1]
        case.expected_sources.append(case.expected_sources[0].model_copy())
        cli.dataset_path.write_text(cli.dataset.model_dump_json(), encoding="utf-8")
        expected_error = ValueError
    with pytest.raises(expected_error):
        cli.run()
    cli.sparse_loader.assert_not_called()
    cli.openai_factory.assert_not_called()
    cli.qdrant_factory.assert_not_called()
    cli.runner.assert_not_called()
    assert not cli.output_path.exists()


def test_corpus_loading_failure_happens_before_api_calls(cli: CliHarness) -> None:
    cli.sparse_loader.side_effect = ValueError("Chunk does not match manifest")
    with pytest.raises(ValueError, match="Chunk does not match manifest"):
        cli.run()
    cli.openai_factory.assert_not_called()
    cli.qdrant_factory.assert_not_called()
    cli.runner.assert_not_called()
    assert not cli.output_path.exists()


def test_all_unanswerable_cases_print_no_scored_summary(
    cli: CliHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    cli.run("--case-id", "unanswerable")
    data = cli.read_report()
    assert all(summary is None for summary in data["report"]["summaries"].values())
    assert all(
        result["metrics"] is None
        for result in data["report"]["cases"][0]["methods"].values()
    )
    output = capsys.readouterr().out
    assert "unanswerable; not scored" in output
    assert "No answerable cases" in output
