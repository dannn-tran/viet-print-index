import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import repeat
from pathlib import Path, PurePosixPath

from google.cloud import storage

logger = logging.getLogger(__name__)


@dataclass
class DownloadOcrResultToLocalCommand:
    src_bucket: str
    src_file_prefix: str
    dst_dirpath: str
    workers: int = 4


def download_ocr(project_id: str, cmd: DownloadOcrResultToLocalCommand):
    storage_client = storage.Client(project=project_id)
    try:
        dst_dirpath = Path(cmd.dst_dirpath)
        blobs = storage_client.list_blobs(cmd.src_bucket, prefix=cmd.src_file_prefix)
        if cmd.workers < 2:
            for blob in blobs:
                _download_one(dst_dirpath, blob)
            return
        with ThreadPoolExecutor(max_workers=cmd.workers) as executor:
            for _ in executor.map(_download_one, repeat(dst_dirpath), blobs):
                continue
    finally:
        storage_client.close()


def _download_one(dst_dirpath: Path, blob: storage.Blob):
    if not blob.name.endswith(".json"):
        return
    for uri, resp in _explode(blob):
        p = PurePosixPath(uri)
        dirpath = dst_dirpath / p.parent.name
        dirpath.mkdir(parents=True, exist_ok=True)
        dst = dirpath / f"{p.stem}.json"
        with open(dst, "w") as f:
            json.dump(resp, f)
        logger.info("Written %s.", dst)


def _explode(blob: storage.Blob):
    logger.info("Download starting - %s...", blob.name)
    raw = blob.download_as_bytes()
    logger.info("Download finished - %s.", blob.name)

    responses: list[dict] = json.loads(raw).get("responses", [])
    if not responses:
        logger.info("No responses in %s", blob.name)

    for i, resp in enumerate(responses):
        uri = resp.get("context", dict()).get("uri")
        if not uri:
            logger.warning("No URI found for response at index %s of %s", i, blob.name)
            continue
        yield uri, resp
