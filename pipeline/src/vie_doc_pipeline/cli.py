"""Command-line interface for the source-to-OCR workflow."""

from collections import Counter
from pathlib import Path
from typing import Annotated, Optional

import typer

from vie_doc_pipeline.logging import configure_logging
from vie_doc_pipeline.pipeline_config import load_config
from vie_doc_pipeline.state import JsonlStateStore, default_state_path
from vie_doc_pipeline.workflow.calibrate_images import run_image_calibration
from vie_doc_pipeline.workflow.discover_source import discover_source_assets
from vie_doc_pipeline.workflow.download_source import download_source_assets
from vie_doc_pipeline.workflow.normalize_images import normalize_images
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
def status(pub_id: _PubArg, config_dir: _ConfigDir = "sources") -> None:
    """Show GCS object counts for a publication."""
    from google.cloud import storage

    config = load_config(pub_id, config_dir)
    client = storage.Client(project=config.gcs.project)

    def _count(prefix: str, suffix: str) -> int:
        return sum(1 for blob in client.list_blobs(config.gcs.bucket, prefix=prefix + "/") if blob.name.endswith(suffix))

    def _count_dirs(prefix: str) -> int:
        blobs_page = client.list_blobs(config.gcs.bucket, prefix=prefix + "/", delimiter="/")
        list(blobs_page)
        return len(blobs_page.prefixes)

    print(f"Publication : {config.publication.name} ({pub_id})")
    print(f"GCS bucket  : gs://{config.gcs.bucket}")
    print(f"  PDFs      : {_count(config.gcs.pdf_prefix, '.pdf'):>6}  ({config.gcs.pdf_prefix}/)")
    print(f"  Images    : {_count_dirs(config.gcs.images_prefix):>6}  ({config.gcs.images_prefix}/)")
    print(f"  OCR blobs : {_count(config.gcs.ocr_output_prefix, '.json'):>6}  ({config.gcs.ocr_output_prefix}/)")


@source_app.command("discover")
def source_discover(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Discover external source records into the JSONL ledger."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    assets = discover_source_assets(config, state, limit=limit)
    print(f"Discovered  : {len(assets)}")
    print(f"State       : {state.path}")


@source_app.command("download")
def source_download(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Download discovered original source assets into GCS."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    downloaded, existing = download_source_assets(config, state, limit=limit)
    print(f"Downloaded  : {downloaded}")
    print(f"Already in GCS: {existing}")
    print(f"State       : {state.path}")


@images_app.command("normalize")
def images_normalize(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Create or designate durable presentation and OCR image assets."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    images, passthrough = normalize_images(config, state, limit=limit)
    print(f"Images created: {images}")
    print(f"Native images : {passthrough} (registered without copying)")
    print(f"State       : {state.path}")


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
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    submitted = submit_ocr_jobs(config, state, limit=limit)
    print(f"Submitted   : {submitted} images")
    print(f"State       : {state.path}")


@ocr_app.command("check-status")
def ocr_check_status(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Report whether submitted OCR jobs have result files in GCS."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    completed, pending = check_ocr_status(config, state)
    print(f"Completed   : {completed} images")
    print(f"Pending     : {pending} images")
    print(f"State       : {state.path}")


@app.command("state", hidden=True)
def state_status(pub_id: _PubArg, state_dir: _StateDir = Path(".pipeline-state")) -> None:
    """Temporary compatibility command; replaced by the final status view."""
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    current = state.current()
    counts = Counter(str(record.get("event", "unknown")) for record in current.values())
    print(f"State       : {state.path}")
    print(f"Assets      : {len(current)}")
    for event, count in sorted(counts.items()):
        print(f"  {event:<14} {count:>6}")
