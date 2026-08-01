from pathlib import Path
from typing import Annotated, Optional
from collections import Counter

import typer

from gc_vision_adapter.ocr.run import RunBatchOcrCommand, batch_ocr
from vie_doc_pipeline.config.logging import configure_logging
from vie_doc_pipeline.pipeline_config import load_config
from vie_doc_pipeline.stages.calibrate import run_calibrate
from vie_doc_pipeline.stages.assets import discover_assets, fetch_assets, materialize_pages
from vie_doc_pipeline.stages.explode import run_explode
from vie_doc_pipeline.stages.ingest import run_ingest
from vie_doc_pipeline.stages.ocr import reconcile_ocr, submit_ocr
from vie_doc_pipeline.state import JsonlStateStore, default_state_path
from vie_doc_pipeline.veridian import VeridianClient

configure_logging()
app = typer.Typer(help="Viet Print Index pipeline tools")
ocr_app = typer.Typer(help="Submit and reconcile persistent OCR jobs")
app.add_typer(ocr_app, name="ocr")

_PubArg = Annotated[str, typer.Argument(help="Publication ID (matches sources/<id>.toml)")]
_ConfigDir = Annotated[str, typer.Option(help="Directory containing source TOML configs")]
_Limit = Annotated[Optional[int], typer.Option(help="Process only first N items")]
_Workers = Annotated[int, typer.Option(help="Concurrent workers")]
_StateDir = Annotated[Path, typer.Option(help="Directory for inspectable JSONL state ledgers")]


@app.command()
def status(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
) -> None:
    """Show blob counts at each pipeline stage."""
    from google.cloud import storage

    config = load_config(pub_id, config_dir)
    client = storage.Client(project=config.gcs.project)

    def _count(prefix: str, suffix: str) -> int:
        return sum(1 for b in client.list_blobs(config.gcs.bucket, prefix=prefix + "/")
                   if b.name.endswith(suffix))

    def _count_dirs(prefix: str) -> int:
        # count virtual subdirectories using delimiter
        blobs_page = client.list_blobs(config.gcs.bucket, prefix=prefix + "/", delimiter="/")
        list(blobs_page)  # exhaust iterator to populate prefixes
        return len(blobs_page.prefixes)

    pdfs      = _count(config.gcs.pdf_prefix, ".pdf")
    exploded  = _count_dirs(config.gcs.images_prefix)
    ocr_blobs = _count(config.gcs.ocr_output_prefix, ".json")

    print(f"Publication : {config.publication.name} ({pub_id})")
    print(f"GCS bucket  : gs://{config.gcs.bucket}")
    print(f"  PDFs      : {pdfs:>6}  ({config.gcs.pdf_prefix}/)")
    print(f"  Exploded  : {exploded:>6}  ({config.gcs.images_prefix}/)")
    print(f"  OCR blobs : {ocr_blobs:>6}  ({config.gcs.ocr_output_prefix}/)")


@app.command("state")
def state_status(
    pub_id: _PubArg,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Summarise the current state reconstructed from a JSONL ledger."""
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    current = state.current()
    counts = Counter(str(record.get("event", "unknown")) for record in current.values())
    print(f"State       : {state.path}")
    print(f"Assets      : {len(current)}")
    for event, count in sorted(counts.items()):
        print(f"  {event:<14} {count:>6}")


@app.command()
def ingest(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    workers: _Workers = 4,
) -> None:
    """Gather source material and upload it to GCS.

    PDF sources are uploaded to the PDF prefix. Veridian sources upload their
    full native page images directly to the images prefix.
    """
    config = load_config(pub_id, config_dir)
    run_ingest(config, limit=limit, workers=workers)


@app.command()
def discover(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Discover source documents or native page images into the JSONL ledger."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    assets = discover_assets(config, state, limit=limit)
    print(f"Publication : {config.publication.name} ({pub_id})")
    print(f"Assets      : {len(assets)}")
    print(f"State       : {state.path}")


@app.command()
def fetch(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Fetch discovered source assets into GCS, resuming from the JSONL ledger."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    fetched, skipped = fetch_assets(config, state, limit=limit)
    print(f"Fetched     : {fetched}")
    print(f"Already in GCS: {skipped}")
    print(f"State       : {state.path}")


@app.command("materialize")
def materialize(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Materialize fetched documents into pages without copying native images."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    pages, passthrough = materialize_pages(config, state, limit=limit)
    print(f"Pages created: {pages}")
    print(f"Native images: {passthrough} (recorded without copying)")
    print(f"State       : {state.path}")


@ocr_app.command("submit")
def ocr_submit(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Submit fetched assets to OCR and persist jobs without blocking."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    submitted = submit_ocr(config, state, limit=limit)
    print(f"Submitted   : {submitted} pages")
    print(f"State       : {state.path}")


@ocr_app.command("reconcile")
def ocr_reconcile(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    state_dir: _StateDir = Path(".pipeline-state"),
) -> None:
    """Reconcile submitted OCR jobs against their GCS output prefixes."""
    config = load_config(pub_id, config_dir)
    state = JsonlStateStore(default_state_path(pub_id, state_dir))
    completed, pending = reconcile_ocr(config, state)
    print(f"Completed   : {completed} pages")
    print(f"Pending     : {pending} pages")
    print(f"State       : {state.path}")


@app.command()
def explode(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    workers: _Workers = 4,
) -> None:
    """Explode PDF blobs in GCS into page images and upload back to GCS."""
    config = load_config(pub_id, config_dir)
    if config.source.type == "veridian":
        print("Veridian sources ingest full page images directly; explode is not needed.")
        return
    run_explode(config, limit=limit, workers=workers)


@app.command(name="run-ocr")
def run_ocr(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
) -> None:
    """Legacy blocking OCR command; prefer `vie-pipeline ocr submit` and `ocr reconcile`."""
    config = load_config(pub_id, config_dir)
    cmd = RunBatchOcrCommand(
        input_bucket=config.gcs.bucket,
        input_file_prefix=config.gcs.images_prefix + "/",
        output_bucket=config.gcs.bucket,
        output_dir=config.gcs.ocr_output_prefix,
        language_hints=list(config.ocr.language_hints),
    )
    batch_ocr(config.gcs.project, cmd)


@app.command()
def calibrate(
    pub_id: _PubArg,
    pdf: Annotated[Path, typer.Option(help="PDF file to use for calibration")],
    config_dir: _ConfigDir = "sources",
    out_dir: Annotated[Optional[Path], typer.Option(help="Output directory")] = None,
) -> None:
    """Extract multiple image variants from a single PDF to calibrate explode params."""
    config = load_config(pub_id, config_dir)
    run_calibrate(config, pdf, out_dir)
