"""Command-line interface for the source-to-OCR workflow."""

from collections import Counter
from pathlib import Path
from typing import Annotated, Optional

import typer

from vie_doc_pipeline.logging import configure_logging
from vie_doc_pipeline.ledger.events import image_inverted, source_inverted
from vie_doc_pipeline.ledger.projection import AppState
from vie_doc_pipeline.assets import ImageAsset
from vie_doc_pipeline.config import PipelineConfig, load_config
from vie_doc_pipeline.images.calibration import run_image_calibration
from vie_doc_pipeline.workflow.discover_source import discover_source_assets
from vie_doc_pipeline.workflow.fetch_source import fetch_source_assets
from vie_doc_pipeline.workflow.normalize_images import (
    AllNormalizationCandidates,
    ImageNormalizationCandidates,
    SourceNormalizationCandidates,
    NormalizationSelection,
    normalize_images,
)
from vie_doc_pipeline.workflow.ocr import check_ocr_status, submit_ocr_jobs

configure_logging()
app = typer.Typer(help="Viet Print Index source-to-OCR pipeline")
source_app = typer.Typer(help="Discover and fetch original source assets")
images_app = typer.Typer(help="Create durable image assets for presentation and OCR")
ocr_app = typer.Typer(help="Submit and check asynchronous OCR jobs")
app.add_typer(source_app, name="source")
app.add_typer(images_app, name="images")
app.add_typer(ocr_app, name="ocr")

_ConfigPath = Annotated[Path, typer.Argument(help="Pipeline TOML configuration path")]
_Limit = Annotated[Optional[int], typer.Option(help="Process only first N items")]
_StatePath = Annotated[Optional[Path], typer.Option("--state-path", help="Event-store state path")]


def _resolve_state_path(config_path: Path, state_path: Path | None) -> Path:
    """Resolve the CLI's state-file override or its derived default."""
    if state_path is not None:
        return state_path
    return Path(".pipeline-state") / "v2" / f"{config_path.stem}.jsonl"


def _open_run(config_path: Path, state_path: Path | None) -> tuple[PipelineConfig, AppState, Path]:
    """Load configuration and replay one command's event-backed application state."""
    config = load_config(config_path)
    resolved_state_path = _resolve_state_path(config_path, state_path)
    return config, AppState.open(resolved_state_path, config.config_toml), resolved_state_path


@app.command()
def status(
    config_path: _ConfigPath,
    state_path: _StatePath = None,
) -> None:
    """Summarise current workflow lifecycle and review states."""
    _, state, state_path = _open_run(config_path, state_path)
    current = state.current
    counts = Counter(item.event or "untracked" for item in current.values())
    review = sum(1 for item in current.values() if item.asset and item.asset.needs_review)
    print(f"Assets      : {len(current)}")
    for event, count in sorted(counts.items()):
        print(f"  {event:<22} {count:>6}")
    print(f"Needs review: {review}")


@source_app.command("discover")
def source_discover(
    config_path: _ConfigPath,
    limit: _Limit = None,
    state_path: _StatePath = None,
) -> None:
    """Discover external source records into the event store."""
    config, state, state_path = _open_run(config_path, state_path)
    assets = discover_source_assets(config, state, limit=limit)
    print(f"Discovered  : {len(assets)}")
    print(f"State file  : {state_path}")


@source_app.command("fetch")
def source_fetch(
    config_path: _ConfigPath,
    limit: _Limit = None,
    state_path: _StatePath = None,
) -> None:
    """Fetch discovered original source assets into target storage."""
    config, state, state_path = _open_run(config_path, state_path)
    summary = fetch_source_assets(config, state, limit=limit)
    print(f"Fetched     : {summary.fetched}")
    print(f"Already present: {summary.already_present}")
    print(f"Failed      : {summary.failed}")
    print(f"State file  : {state_path}")


@images_app.command("normalize")
def images_normalize(
    config_path: _ConfigPath,
    limit: _Limit = None,
    state_path: _StatePath = None,
    source_id: Annotated[Optional[str], typer.Option(help="Issue or PDF identifier to normalize")] = None,
    image_id: Annotated[Optional[str], typer.Option(help="Event-store image asset key to normalize")] = None,
    inverted: Annotated[bool, typer.Option(help="Invert this source or image before OCR and presentation")] = False,
) -> None:
    """Create or designate durable presentation and OCR image assets."""
    config, state, state_path = _open_run(config_path, state_path)
    selection = normalization_selection(source_id, image_id)
    if inverted:
        match selection:
            case SourceNormalizationCandidates():
                state.record(source_inverted(selection.source_id))
            case ImageNormalizationCandidates():
                state.record(image_inverted(selection.image_key))
            case AllNormalizationCandidates():
                raise typer.BadParameter("--inverted requires --source-id or --image-id")
    summary = normalize_images(config, state, limit=limit, selection=selection)
    print(f"Images created: {summary.created}")
    print(f"Native images : {summary.native_registered} (registered without copying)")
    print(f"Failed        : {summary.failed}")
    print(f"State file  : {state_path}")


def normalization_selection(source_id: str | None, image_id: str | None) -> NormalizationSelection:
    if source_id and image_id:
        raise typer.BadParameter("Specify at most one of --source-id or --image-id")
    if source_id:
        return SourceNormalizationCandidates(source_id)
    if image_id:
        return ImageNormalizationCandidates(image_id)
    return AllNormalizationCandidates()


@images_app.command("review")
def images_review(
    config_path: _ConfigPath,
    state_path: _StatePath = None,
) -> None:
    """List normalized images that were retained unchanged for manual review."""
    config, state, state_path = _open_run(config_path, state_path)
    current = state.current
    flagged = [(key, item) for key, item in current.items() if item.asset and item.asset.needs_review]
    if not flagged:
        print("No images need review.")
        return
    for key, item in flagged:
        source_id = item.asset.issue_id if isinstance(item.asset, ImageAsset) else ""
        print(f"{key}\n  vie-pipeline images normalize {config_path} --source-id {source_id} --inverted")


@images_app.command("calibrate")
def images_calibrate(
    config_path: _ConfigPath,
    pdf: Annotated[Path, typer.Option(help="PDF file to use for calibration")],
    out_dir: Annotated[Optional[Path], typer.Option(help="Output directory")] = None,
) -> None:
    """Inspect PDF-to-image variants for a representative source asset."""
    summary = run_image_calibration(load_config(config_path), pdf, out_dir)
    for variant in summary.variants:
        print(f"  {variant.name}: {variant.image_count} images → {variant.output_dir}")
    print("\nHeuristic suggestions for [explode] in your TOML:" if summary.hints else "\nNo heuristic hints. Try render variants.")
    for hint in summary.hints:
        print(f"  {hint}")


@ocr_app.command("submit-jobs")
def ocr_submit_jobs(
    config_path: _ConfigPath,
    limit: _Limit = None,
    state_path: _StatePath = None,
) -> None:
    """Submit OCR jobs for normalized image assets without waiting."""
    config, state, state_path = _open_run(config_path, state_path)
    summary = submit_ocr_jobs(config, state, limit=limit)
    print(f"Submitted   : {summary.submitted} images")
    print(f"State file  : {state_path}")


@ocr_app.command("check-status")
def ocr_check_status(
    config_path: _ConfigPath,
    state_path: _StatePath = None,
) -> None:
    """Report whether submitted OCR jobs have result files in GCS."""
    config, state, state_path = _open_run(config_path, state_path)
    summary = check_ocr_status(config, state)
    print(f"Completed   : {summary.completed} images")
    print(f"Pending     : {summary.pending} images")
    print(f"State file  : {state_path}")
