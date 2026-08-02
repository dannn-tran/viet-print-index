from vie_doc_pipeline.common.config import LocalPdfSource, LocalTarget, OcrConfig, PipelineConfig, PublicationConfig
from vie_doc_pipeline.images.pdf import ExplodeParams


def sample_pipeline_config(config_toml: str = "test-config") -> PipelineConfig:
    return PipelineConfig(
        publication=PublicationConfig("test-publication", "Test publication"),
        target=LocalTarget(root="."),
        source=LocalPdfSource(path="."),
        explode=ExplodeParams(),
        ocr=OcrConfig(),
        config_toml=config_toml,
    )
