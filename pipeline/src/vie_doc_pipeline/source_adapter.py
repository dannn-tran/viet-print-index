import re
import urllib.request
from pathlib import Path
from typing import Protocol

from vie_doc_pipeline.pipeline_config import SourceConfig


class SourceAdapter(Protocol):
    def list_pdf_items(self) -> list[str]:
        """Return PDF URLs (for web sources) or local file paths."""
        ...


class WebPageAdapter:
    def __init__(self, config: SourceConfig) -> None:
        self._config = config

    def list_pdf_items(self) -> list[str]:
        url = self._config.page_url
        assert url, "page_url required for web_page source type"
        html = _fetch_text(url)
        links = re.findall(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
        base = url.rsplit("/", 1)[0]
        result: list[str] = []
        for link in links:
            if link.startswith("http"):
                result.append(link)
            else:
                result.append(base + "/" + link.lstrip("/"))
        return list(dict.fromkeys(result))


class UrlSequenceAdapter:
    def __init__(self, config: SourceConfig) -> None:
        self._config = config

    def list_pdf_items(self) -> list[str]:
        base = (self._config.base_url or "").rstrip("/")
        pattern = self._config.pattern or "{}.pdf"
        start, end = self._config.range or (1, 1)
        return [f"{base}/{pattern.format(i)}" for i in range(start, end + 1)]


class UrlListAdapter:
    def __init__(self, config: SourceConfig) -> None:
        self._config = config

    def list_pdf_items(self) -> list[str]:
        return list(self._config.urls)


class LocalDirAdapter:
    def __init__(self, config: SourceConfig) -> None:
        self._config = config

    def list_pdf_items(self) -> list[str]:
        path = self._config.path or "."
        return [str(p) for p in sorted(Path(path).glob("*.pdf"))]


def make_adapter(config: SourceConfig) -> SourceAdapter:
    match config.type:
        case "web_page":
            return WebPageAdapter(config)
        case "url_sequence":
            return UrlSequenceAdapter(config)
        case "url_list":
            return UrlListAdapter(config)
        case "local_dir":
            return LocalDirAdapter(config)
        case _:
            raise ValueError(f"Unknown source type: {config.type!r}")


def fetch_bytes(url_or_path: str) -> bytes:
    """Fetch PDF bytes from a URL or local file path."""
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        req = urllib.request.Request(url_or_path, headers={"User-Agent": "vie-pipeline/1.0"})
        with urllib.request.urlopen(req) as resp:
            return resp.read()
    return Path(url_or_path).read_bytes()


def _fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "vie-pipeline/1.0"})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8", errors="replace")
