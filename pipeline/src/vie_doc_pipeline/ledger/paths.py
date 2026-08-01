from pathlib import Path


def resolve_state_path(config_path: Path, state_path: Path | None = None) -> Path:
    """Use an explicit state path or derive one from the config filename."""
    if state_path is not None:
        return state_path
    return Path(".pipeline-state") / "v2" / f"{config_path.stem}.jsonl"
