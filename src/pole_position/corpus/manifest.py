from pathlib import Path

from pole_position.corpus.schemas import CorpusManifest


def load_manifest(path: Path) -> CorpusManifest:
    manifest_json = path.read_text(encoding="utf-8")

    return CorpusManifest.model_validate_json(manifest_json)
