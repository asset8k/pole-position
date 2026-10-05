"""Evaluate retrieval methods and save a JSON report."""

import hashlib
import json
from argparse import ArgumentParser, Namespace
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from openai import OpenAI
from pydantic import TypeAdapter
from qdrant_client import QdrantClient

from pole_position.config import settings
from pole_position.rag.evaluation.metrics import (
    RetrievalSummary,
    score_retrieval,
    summarize_metrics,
)
from pole_position.rag.evaluation.runner import (
    CaseEvaluation,
    EvaluationReport,
    RetrievalMethod,
    run_evaluation,
)
from pole_position.rag.evaluation.schemas import EvaluationDataset
from pole_position.rag.indexing.embeddings import EMBEDDING_MODEL
from pole_position.rag.retrieval.reranker import MAX_RERANK_CANDIDATES
from pole_position.rag.retrieval.sparse import load_sparse_corpus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data/eval/questions.json"
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"
CHUNKS_DIR = PROJECT_ROOT / "artifacts/chunks"
REPORTS_DIR = PROJECT_ROOT / "artifacts/evaluation"

REPORT_ADAPTER = TypeAdapter(EvaluationReport)


def parse_args() -> Namespace:
    parser = ArgumentParser(description=__doc__)

    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--limit",
        type=int,
        help="Evaluate only the first N questions",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Select a specific case; can be repeated",
    )
    parser.add_argument("--candidate-k", type=int, default=20)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--model",
        default=settings.answer_model,
        help="Model for contextualization and reranking",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="Compare only dense and hybrid retrieval",
    )

    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")

    if not 10 <= args.candidate_k <= MAX_RERANK_CANDIDATES:
        parser.error(f"--candidate-k must be between 10 and {MAX_RERANK_CANDIDATES}")

    if args.rrf_k <= 0:
        parser.error("--rrf-k must be positive")

    if not args.model.strip():
        parser.error("--model cannot be blank")

    if args.output is not None and args.output.exists():
        parser.error("--output already exists; choose a new filename")

    return args


def select_dataset(
    dataset: EvaluationDataset,
    args: Namespace,
) -> EvaluationDataset:
    cases = dataset.cases

    if args.case_id:
        requested_ids = set(args.case_id)
        available_ids = {case.id for case in cases}
        unknown_ids = requested_ids - available_ids

        if unknown_ids:
            raise ValueError(f"Unknown case IDs: {sorted(unknown_ids)}")

        # Preserve the original dataset order.
        cases = [case for case in cases if case.id in requested_ids]

    if args.limit is not None:
        cases = cases[: args.limit]

    return EvaluationDataset(cases=cases)


def save_report(
    output_path: Path,
    report: EvaluationReport,
    dataset: EvaluationDataset,
    *,
    dataset_sha256: str,
    manifest_sha256: str,
    started_at: str,
    elapsed_seconds: float,
    status: str,
) -> None:
    """Save completed results, including a partial run after failure."""
    payload = {
        "status": status,
        "started_at": started_at,
        "updated_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "selected_cases": len(dataset.cases),
        "completed_cases": len(report.cases),
        "embedding_model": EMBEDDING_MODEL,
        "dataset_sha256": dataset_sha256,
        "manifest_sha256": manifest_sha256,
        "dataset": dataset.model_dump(mode="json"),
        "report": REPORT_ADAPTER.dump_python(
            report,
            mode="json",
        ),
    }

    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def print_summary(report: EvaluationReport) -> None:
    print("\nRETRIEVAL SUMMARY")
    print(f"{'Method':<20} {'Recall@5':>10} {'Recall@10':>10} {'MRR@10':>10}")

    for method, summary in report.summaries.items():
        if summary is None:
            print(f"{method:<20} No answerable cases")
            continue

        print(
            f"{method:<20} "
            f"{summary.recall_at_5:>10.3f} "
            f"{summary.recall_at_10:>10.3f} "
            f"{summary.mrr_at_10:>10.3f}"
        )
        print(
            f"  Scored: {summary.evaluated_cases}; "
            f"excluded unanswerable: {summary.skipped_cases}"
        )


def main() -> None:
    args = parse_args()

    dataset_bytes = args.dataset.read_bytes()
    dataset = select_dataset(
        EvaluationDataset.model_validate_json(dataset_bytes),
        args,
    )

    # Check labels before making any paid calls.
    for case in dataset.cases:
        score_retrieval(case, [])

    sparse_corpus = load_sparse_corpus(
        MANIFEST_PATH,
        CHUNKS_DIR,
    )

    dataset_sha256 = hashlib.sha256(dataset_bytes).hexdigest()
    manifest_sha256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()

    started = datetime.now(UTC)
    started_at = started.isoformat()
    start_time = perf_counter()

    output_path = args.output or (
        REPORTS_DIR / f"retrieval-{started:%Y%m%dT%H%M%S%fZ}.json"
    )

    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite report: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    report = EvaluationReport(
        collection_name=settings.qdrant_collection,
        model=args.model.strip(),
        candidate_k=args.candidate_k,
        rrf_k=args.rrf_k,
        include_reranking=not args.no_rerank,
        cases=[],
        summaries={},
    )

    def checkpoint(status: str) -> None:
        save_report(
            output_path,
            report,
            dataset,
            dataset_sha256=dataset_sha256,
            manifest_sha256=manifest_sha256,
            started_at=started_at,
            elapsed_seconds=perf_counter() - start_time,
            status=status,
        )

    checkpoint("running")

    print(f"Selected {len(dataset.cases)} questions")
    print(f"Collection: {report.collection_name}")
    print(f"Reranking: {report.include_reranking}")
    print(f"Report: {output_path}", flush=True)

    completed_cases: list[CaseEvaluation] = []

    with OpenAI(api_key=settings.openai_api_key.get_secret_value()) as openai_client:
        qdrant_client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key.get_secret_value(),
        )

        try:
            for index, case in enumerate(dataset.cases, start=1):
                print(
                    f"\n[{index}/{len(dataset.cases)}] {case.id}: {case.question}",
                    flush=True,
                )

                single_report = run_evaluation(
                    EvaluationDataset(cases=[case]),
                    openai_client=openai_client,
                    qdrant_client=qdrant_client,
                    sparse_corpus=sparse_corpus,
                    collection_name=report.collection_name,
                    model=report.model,
                    candidate_k=report.candidate_k,
                    rrf_k=report.rrf_k,
                    include_reranking=report.include_reranking,
                )

                completed_cases.extend(single_report.cases)

                summaries: dict[RetrievalMethod, RetrievalSummary | None] = {
                    method: summarize_metrics(
                        [result.methods[method].metrics for result in completed_cases]
                    )
                    for method in single_report.summaries
                }

                report = replace(
                    single_report,
                    cases=list(completed_cases),
                    summaries=summaries,
                )

                checkpoint("running")

                for method, result in report.cases[-1].methods.items():
                    metrics = result.metrics

                    if metrics is None:
                        print(f"  {method}: unanswerable; not scored")
                    else:
                        print(
                            f"  {method}: "
                            f"R@5={metrics.recall_at_5:.3f}, "
                            f"R@10={metrics.recall_at_10:.3f}, "
                            f"RR@10={metrics.reciprocal_rank_at_10:.3f}"
                        )

        except Exception:
            checkpoint("failed")
            print(
                f"\nEvaluation failed. Completed results are saved at {output_path}",
                flush=True,
            )
            raise
        finally:
            qdrant_client.close()

    checkpoint("completed")
    print_summary(report)
    print(f"\nSaved report: {output_path}")


if __name__ == "__main__":
    main()
