from pathlib import Path


def default_ledger_path(publication_id: str, state_dir: Path = Path(".pipeline-state")) -> Path:
    """Return a fresh v2 ledger path without touching earlier ledger formats."""
    return state_dir / "v2" / f"{publication_id}.jsonl"
