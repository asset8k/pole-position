from pathlib import Path

from pole_position.corpus.manifest import load_manifest
from pole_position.corpus.verification import verify_local_corpus

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data/manifests/2026_f1_regulations.json"


def main() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    verify_local_corpus(manifest, PROJECT_ROOT)

    print(f"Verified {len(manifest.documents)} regulation documents")


if __name__ == "__main__":
    main()
