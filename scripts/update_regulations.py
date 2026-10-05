"""Preview/apply replacement FIA PDFs, or restore a previous corpus manifest."""

import fcntl
import json
from argparse import ArgumentParser, Namespace
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pole_position.corpus.schemas import CorpusManifest
from pole_position.corpus.updates import (
    VECTOR_SIZE,
    activate_manifest,
    atomic_write,
    audit_document,
    prepare_batch,
    replacement_manifest,
    stage_document,
)
from pole_position.corpus.verification import verify_local_corpus
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.indexing.qdrant_store import ensure_collection
from pole_position.rag.retrieval.sparse import load_sparse_corpus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


@contextmanager
def update_lock(root: Path) -> Iterator[None]:
    lock_path = root / "artifacts/updates/.update.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another regulation update is running") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--pdf", type=Path, nargs="+", help="One or more downloaded FIA PDFs"
    )
    inputs.add_argument(
        "--pdf-dir",
        type=Path,
        help="Directory containing replacement PDFs (non-recursive)",
    )
    inputs.add_argument(
        "--restore-manifest",
        type=Path,
        help="Restore a manifest.before.json from a previous run",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Allow paid embedding calls, Qdrant writes and activation",
    )
    parser.add_argument(
        "--allow-same-issue",
        action="store_true",
        help="Allow a reviewed official correction with the same issue number",
    )
    return parser


def run(
    args: Namespace,
    *,
    root: Path = PROJECT_ROOT,
    manifest_path: Path = MANIFEST_PATH,
) -> int:
    """By default, prepare local files only. External writes require --apply."""
    with update_lock(root):
        original_text = manifest_path.read_text(encoding="utf-8")
        manifest = CorpusManifest.model_validate_json(original_text)
        verify_local_corpus(manifest, root)
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        run_dir = root / "artifacts/updates" / run_id
        atomic_write(run_dir / "manifest.before.json", original_text)
        report: dict[str, Any] = {
            "status": "preparing",
            "apply": args.apply,
            "updates": [],
            "unchanged": [],
        }

        def save_report() -> None:
            atomic_write(run_dir / "report.json", json.dumps(report, indent=2) + "\n")

        save_report()
        print(f"Run report: {run_dir / 'report.json'}")
        try:
            if args.restore_manifest:
                proposed = CorpusManifest.model_validate_json(
                    args.restore_manifest.read_text(encoding="utf-8")
                )
                if {doc.section for doc in proposed.documents if doc.is_active} != {
                    doc.section for doc in manifest.documents if doc.is_active
                }:
                    raise ValueError(
                        "Restore manifest must contain the same active sections"
                    )
                if {doc.season for doc in proposed.documents} != {
                    doc.season for doc in manifest.documents
                }:
                    raise ValueError("Restore manifest must use the current season")
                verify_local_corpus(proposed, root)
                updates = []
            else:
                paths = args.pdf or sorted(
                    path
                    for path in args.pdf_dir.iterdir()
                    if path.is_file() and path.suffix.lower() == ".pdf"
                )
                if not paths:
                    raise ValueError("No PDF files supplied")
                updates, unchanged = prepare_batch(
                    paths, manifest, root, allow_same_issue=args.allow_same_issue
                )
                proposed = replacement_manifest(manifest, updates)
                report["updates"] = [update.summary for update in updates]
                report["unchanged"] = unchanged
                for section in unchanged:
                    print(f"Section {section}: unchanged SHA-256; no embeddings needed")
                for update in updates:
                    print(
                        f"Section {update.document.section}: issue {update.previous.issue_number:02d} → "
                        f"{update.document.issue_number:02d}; {update.document.page_count} pages; "
                        f"{len(update.chunked.chunks)} chunks"
                    )
                    print(
                        f"  Skipped future: {update.summary['skipped_future']}; visual: {update.summary['skipped_visual']}"
                    )
                    if update.summary["pages_without_text"]:
                        print(
                            f"  Review pages without text: {update.summary['pages_without_text']}"
                        )
                if not updates:
                    report["status"] = "unchanged"
                    save_report()
                    print("Nothing to replace. No API calls made.")
                    return 0

            verify_local_corpus(proposed, root)
            # Build the exact proposed BM25 corpus before any remote mutation.
            corpus = load_sparse_corpus(
                manifest_path, root / "artifacts/chunks", manifest=proposed
            )
            report["proposed_active_chunks"] = corpus.index.chunk_count
            report["evaluation_dataset_needs_review"] = True
            print(f"Proposed active corpus: {corpus.index.chunk_count} chunks")
            atomic_write(
                run_dir / "manifest.proposed.json",
                proposed.model_dump_json(indent=2) + "\n",
            )
            if not args.apply:
                report["status"] = "prepared"
                save_report()
                print("Preview passed. Current manifest and databases are unchanged.")
                print(
                    "Review the report/artifacts, then rerun the same command with --apply."
                )
                return 0

            # Import settings/construct external clients only after offline validation.
            from openai import OpenAI
            from qdrant_client import QdrantClient

            from pole_position.config import settings

            qdrant_client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key.get_secret_value(),
            )
            with closing(qdrant_client) as client:
                ensure_collection(client, settings.qdrant_collection, VECTOR_SIZE)
                # Catch an unhealthy starting corpus before spending on new embeddings.
                for document in manifest.documents:
                    if document.is_active:
                        chunked = ChunkedDocument.model_validate_json(
                            (
                                root
                                / "artifacts/chunks"
                                / f"{document.document_id}.json"
                            ).read_text(encoding="utf-8")
                        )
                        audit_document(
                            client, settings.qdrant_collection, document, chunked
                        )
                with OpenAI(
                    api_key=settings.openai_api_key.get_secret_value()
                ) as openai_client:
                    report["status"] = "staging"
                    save_report()
                    for update in updates:
                        embedded = stage_document(
                            client, openai_client, settings.qdrant_collection, update
                        )
                        print(
                            f"Verified Section {update.document.section}: {embedded} new embeddings; "
                            f"{len(update.chunked.chunks) - embedded} reused staged points"
                        )
                warnings = activate_manifest(
                    root,
                    manifest_path,
                    original_text,
                    proposed,
                    client,
                    settings.qdrant_collection,
                )
            report["status"] = "activated"
            report["warnings"] = warnings
            save_report()
            print("Activated. Dense search and BM25 now use the replacement manifest.")
            print("Old PDFs, chunks and Qdrant points retained; PostgreSQL unchanged.")
            print(
                "Review evaluation source IDs/pages for changed sections, then rerun evaluation and live chat checks."
            )
            print(
                f"Rollback: uv run python scripts/update_regulations.py --restore-manifest '{run_dir / 'manifest.before.json'}' --apply"
            )
            for warning in warnings:
                print(f"Warning: {warning}")
            return 0
        except Exception as error:
            # Don't print external client exceptions that might contain connection secrets.
            switched = manifest_path.read_text(encoding="utf-8") != original_text
            report["status"] = "activated_with_error" if switched else "failed"
            report["error_type"] = type(error).__name__
            report["error"] = (
                str(error)
                if isinstance(error, (ValueError, FileNotFoundError))
                else "External operation failed"
            )
            report["manifest_changed"] = switched
            save_report()
            print(f"Update failed: {report['error']} ({report['error_type']})")
            print(
                "Manifest was switched; inspect the report before retrying."
                if switched
                else "Current manifest is unchanged."
            )
            print(
                "Retry the same inputs after resolving the issue; verified staged points are reusable."
            )
            return 1


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(run(args))
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
