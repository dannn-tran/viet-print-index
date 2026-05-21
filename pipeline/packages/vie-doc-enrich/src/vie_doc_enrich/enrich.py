from dataclasses import dataclass


@dataclass(frozen=True)
class EnrichCommand:
    doc_ocr_path: str
    output_path: str


class EnrichService:
    def __init__(self):
        pass

    def enrich(self, cmd: EnrichCommand):
        pass