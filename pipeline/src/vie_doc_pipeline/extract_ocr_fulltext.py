from typing import Annotated

import typer

from gc_vision_adapter.ocr.extract import extract_ocr_fulltext
from vie_doc_pipeline.logging import configure_logging

configure_logging()
app = typer.Typer()

@app.command()
def main(
    src_dir: Annotated[str, typer.Option()],
    dst_dir: Annotated[str, typer.Option()],
    workers: Annotated[int, typer.Option(min=1)] = 4
):
    extract_ocr_fulltext(src_dir, dst_dir, workers)
