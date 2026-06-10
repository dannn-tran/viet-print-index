from pathlib import Path
from typing import Annotated, Optional

import typer

from gc_vision_adapter.ocr.run import RunBatchOcrCommand, batch_ocr
from vie_doc_pipeline.config.logging import configure_logging
from vie_doc_pipeline.pipeline_config import load_config
from vie_doc_pipeline.stages.calibrate import run_calibrate
from vie_doc_pipeline.stages.explode import run_explode
from vie_doc_pipeline.stages.ingest import run_ingest

configure_logging()
app = typer.Typer(help="Viet Print Index pipeline tools")

_PubArg = Annotated[str, typer.Argument(help="Publication ID (matches sources/<id>.toml)")]
_ConfigDir = Annotated[str, typer.Option(help="Directory containing source TOML configs")]
_Limit = Annotated[Optional[int], typer.Option(help="Process only first N items")]
_Workers = Annotated[int, typer.Option(help="Concurrent workers")]


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


@app.command()
def ingest(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    workers: _Workers = 4,
) -> None:
    """Gather PDFs from source (web/local) and upload to GCS."""
    config = load_config(pub_id, config_dir)
    run_ingest(config, limit=limit, workers=workers)


@app.command()
def explode(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
    limit: _Limit = None,
    workers: _Workers = 4,
) -> None:
    """Explode PDF blobs in GCS into page images and upload back to GCS."""
    config = load_config(pub_id, config_dir)
    run_explode(config, limit=limit, workers=workers)


@app.command(name="run-ocr")
def run_ocr(
    pub_id: _PubArg,
    config_dir: _ConfigDir = "sources",
) -> None:
    """Submit GCS images to Google Cloud Vision batch OCR."""
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
