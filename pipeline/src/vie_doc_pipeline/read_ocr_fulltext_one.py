from typing import Annotated

import typer

from gc_vision_adapter.ocr.extract import get_ocr_fulltext_one
from vie_doc_pipeline.logging import configure_logging

configure_logging()
app = typer.Typer()

@app.command()
def main(
    filepath: Annotated[str, typer.Option()]
):
    print(get_ocr_fulltext_one(filepath))
