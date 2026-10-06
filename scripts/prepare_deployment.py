"""Export only the validated active corpus for a FastAPI Cloud deployment."""

import argparse
import hashlib
import json
from pathlib import Path

from pole_position.corpus.schemas import CorpusManifest
from pole_position.corpus.updates import atomic_write
from pole_position.rag.contracts import ChunkedDocument
from pole_position.rag.retrieval.sparse import load_sparse_corpus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = Path("data/manifests/2026_f1_regulations.json")
CHUNKS_PATH = Path("artifacts/chunks")


def prepare_deployment(project_root: Path, output_dir: Path) -> dict:
    """Do not contact services, change active data, or package PDFs/secrets."""
    project_root = project_root.resolve()
    output_dir = output_dir.resolve()
    if output_dir == project_root or output_dir.is_relative_to(project_root / "artifacts"):
        raise ValueError("Use a separate deployment bundle directory")

    original = (project_root / MANIFEST_PATH).read_text(encoding="utf-8")
    manifest = CorpusManifest.model_validate_json(original)
    active = [doc for doc in manifest.documents if doc.is_active and doc.season == 2026]
    if {doc.section for doc in active} != set("ABCDEF") or len(active) != 6:
        raise ValueError("Deployment requires all six active 2026 sections")
    for doc in active:
        if Path(doc.document_id).name != doc.document_id or doc.document_id in (".", ".."):
            raise ValueError("Document ID must be a filename-safe identifier")

    snapshot = CorpusManifest(documents=active)
    # Read every input before writing anything. Validate the exact snapshot that
    # will be deployed, rather than trusting counts from a previous ingestion.
    contents = {
        doc.document_id: (project_root / CHUNKS_PATH / f"{doc.document_id}.json").read_text(encoding="utf-8")
        for doc in active
    }
    counts = {}
    for doc in active:
        chunked = ChunkedDocument.model_validate_json(contents[doc.document_id])
        if chunked.document_id != doc.document_id or chunked.source_sha256 != doc.sha256:
            raise ValueError(f"Chunk artifact does not match manifest: {doc.document_id}")
        if not chunked.chunks or any(
            chunk.document_id != doc.document_id
            or chunk.source_sha256 != doc.sha256
            or chunk.section != doc.section
            for chunk in chunked.chunks
        ):
            raise ValueError(f"Invalid chunks for {doc.document_id}")
        counts[doc.section] = len(chunked.chunks)
    if (project_root / MANIFEST_PATH).read_text(encoding="utf-8") != original:
        raise ValueError("Manifest changed during export; run again")

    for doc in active:
        atomic_write(output_dir / CHUNKS_PATH / f"{doc.document_id}.json", contents[doc.document_id])
    manifest_json = snapshot.model_dump_json(indent=2) + "\n"
    atomic_write(output_dir / MANIFEST_PATH, manifest_json)
    corpus = load_sparse_corpus(output_dir / MANIFEST_PATH, output_dir / CHUNKS_PATH)
    summary = {
        "season": 2026,
        "manifest_sha256": hashlib.sha256(manifest_json.encode()).hexdigest(),
        "sections": counts,
        "active_chunks": corpus.index.chunk_count,
    }
    atomic_write(output_dir / "bundle.json", json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "deployment_data")
    args = parser.parse_args()
    summary = prepare_deployment(PROJECT_ROOT, args.output)
    print(f"Validated {summary['active_chunks']} active chunks: {summary['sections']}")
    print(f"Deployment bundle: {args.output.resolve()}")


if __name__ == "__main__":
    main()
