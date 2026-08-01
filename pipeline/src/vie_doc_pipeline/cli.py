"""Command-line interface for the source-to-OCR workflow."""

from collections import Counter
from pathlib import Path
from typing import Annotated, Optional

import typer

from vie_doc_pipeline.logging import configure_logging
from vie_doc_pipeline.ledger.events import image_inverted, source_inverted
from vie_doc_pipeline.ledger.jsonl import append_event
from vie_doc_pipeline.ledger.paths import default_ledger_path
from vie_doc_pipeline.ledger.projection import load_current
from vie_doc_pipeline.models import ImageAsset
from vie_doc_pipeline.pipeline_config import load_config
from vie_doc_pipeline.images.calibration import run_image_calibration
from vie_doc_pipeline.workflow.discover_source import discover_source_assets
from vie_doc_pipeline.workflow.download_source import download_source_assets
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
source_app = typer.Typer(help="Discover and download original source assets")
images_app = typer.Typer(help="Create durable image assets for presentation and OCR")
ocr_app = typer.Typer(help="Submit and check asynchronous OCR jobs")
app.add_typer(source_app, name="source")
app.add_typer(images_app, name="images")
app.add_typer(ocr_app, name="ocr")

_PubArg = Annotated[str, typer.Argument(help="Publication ID (matches sources/<id>.toml)")]
_ConfigDir = Annotated[str, typer.Option(help="Directory containing source TOML configs")]
_Limit = Annotated[Optional[int], typer.Option(help="Process only first N items")]
_StateDir = Annotated[Path, typer.Option(help="Directory for inspectable JSONL state ledgers")]


@app.command()
def status(pub_id: _PubArg, state_dir: _StateDir = Path(".pipeline-state")) -> None:
    """Summarise current workflow lifecycle and review states."""
    current = load_current(default_ledger_path(pub_id, state_dir))
    counts = Counter(item.event or "untracked" for item in current.values())
    review = sum(1 for item in current.values() if item.asset and item.asset.needs_review)
    print(f"Assets      : {len(current)}")
    for event, count in sorted(counts.items()):
        print(f"  {event:<22} {count:>6}")
    print(f"Needs review: {review}")


@source_app.command("discover")
def source_discover(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Discover external source records into the JSONL ledger."""
    config = load_config(pub_id, config_dir)
    ledger_path = default_ledger_path(pub_id, state_dir)
    assets = discover_source_assets(config, ledger_path, limit=limit)
    print(f"Discovered  : {len(assets)}")
    print(f"Ledger      : {ledger_path}")


@source_app.command("download")
def source_download(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Download discovered original source assets into GCS."""
    config = load_config(pub_id, config_dir)
    ledger_path = default_ledger_path(pub_id, state_dir)
    summary = download_source_assets(config, ledger_path, limit=limit)
    print(f"Downloaded  : {summary.downloaded}")
    print(f"Already in GCS: {summary.already_present}")
    print(f"Failed      : {summary.failed}")
    print(f"Ledger      : {ledger_path}")


@images_app.command("normalize")
def images_normalize(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
    source_id: Annotated[Optional[str], typer.Option(help="Issue or PDF identifier to normalize")] = None,
    image_id: Annotated[Optional[str], typer.Option(help="Ledger image asset key to normalize")] = None,
    inverted: Annotated[bool, typer.Option(help="Invert this source or image before OCR and presentation")] = False,
) -> None:
    """Create or designate durable presentation and OCR image assets."""
    config = load_config(pub_id, config_dir)
    ledger_path = default_ledger_path(pub_id, state_dir)
    selection = normalization_selection(source_id, image_id)
    if inverted:
        match selection:
            case SourceNormalizationCandidates():
                append_event(ledger_path, source_inverted(selection.source_id))
            case ImageNormalizationCandidates():
                append_event(ledger_path, image_inverted(selection.image_key))
            case AllNormalizationCandidates():
                raise typer.BadParameter("--inverted requires --source-id or --image-id")
    summary = normalize_images(config, ledger_path, limit=limit, selection=selection)
    print(f"Images created: {summary.created}")
    print(f"Native images : {summary.native_registered} (registered without copying)")
    print(f"Failed        : {summary.failed}")
    print(f"Ledger      : {ledger_path}")


def normalization_selection(source_id: str | None, image_id: str | None) -> NormalizationSelection:
    if source_id and image_id:
        raise typer.BadParameter("Specify at most one of --source-id or --image-id")
    if source_id:
        return SourceNormalizationCandidates(source_id)
    if image_id:
        return ImageNormalizationCandidates(image_id)
    return AllNormalizationCandidates()


@images_app.command("review")
def images_review(pub_id: _PubArg, state_dir: _StateDir = Path(".pipeline-state")) -> None:
    """List normalized images that were retained unchanged for manual review."""
    current = load_current(default_ledger_path(pub_id, state_dir))
    flagged = [(key, item) for key, item in current.items() if item.asset and item.asset.needs_review]
    if not flagged:
        print("No images need review.")
        return
    for key, item in flagged:
        source_id = item.asset.issue_id if isinstance(item.asset, ImageAsset) else ""
        print(f"{key}\n  vie-pipeline images normalize {pub_id} --source-id {source_id} --inverted")


@images_app.command("calibrate")
def images_calibrate(
    pub_id: _PubArg,
    pdf: Annotated[Path, typer.Option(help="PDF file to use for calibration")],
    config_dir: _ConfigDir = "sources",
    out_dir: Annotated[Optional[Path], typer.Option(help="Output directory")] = None,
) -> None:
    """Inspect PDF-to-image variants for a representative source asset."""
    run_image_calibration(load_config(pub_id, config_dir), pdf, out_dir)


@ocr_app.command("submit-jobs")
def ocr_submit_jobs(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Submit OCR jobs for normalized image assets without waiting."""
    config = load_config(pub_id, config_dir)
    ledger_path = default_ledger_path(pub_id, state_dir)
    submitted = submit_ocr_jobs(config, ledger_path, limit=limit)
    print(f"Submitted   : {submitted} images")
    print(f"Ledger      : {ledger_path}")


@ocr_app.command("check-status")
def ocr_check_status(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Report whether submitted OCR jobs have result files in GCS."""
    config = load_config(pub_id, config_dir)
    ledger_path = default_ledger_path(pub_id, state_dir)
    summary = check_ocr_status(config, ledger_path)
    print(f"Completed   : {summary.completed} images")
    print(f"Pending     : {summary.pending} images")
    print(f"Ledger      : {ledger_path}")
