import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
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

    dst_dirpath = Path(cmd.dst_dirpath)

    blobs = storage_client.list_blobs(cmd.src_bucket, prefix=cmd.src_file_prefix)

    if cmd.workers < 2:
        for b in blobs:
            _download_one(dst_dirpath, b)
        return

    with ThreadPoolExecutor(max_workers=cmd.workers) as executor:
        for _ in executor.map(lambda b: _download_one(dst_dirpath, b), blobs):
            pass


def _download_one(dst_dirpath: Path, blob: storage.Blob):
    try:
        if not blob.name.endswith(".json"):
            return
        # TODO: skip download if file already downloaded
        for uri, resp in _explode(blob):
            p = PurePosixPath(uri)
            dirpath = dst_dirpath / p.parent.name
            dirpath.mkdir(parents=True, exist_ok=True)
            dst = dirpath / f"{p.stem}.json"
            with open(dst, "w") as f:
                json.dump(resp, f)
            logger.info(f"Written {dst}.")
    except Exception as e:
        logger.error(e)
        raise e


def _explode(blob: storage.Blob):
    logger.info(f"Download starting - {blob.name}...")
    raw = blob.download_as_bytes()
    logger.info(f"Download finished - {blob.name}.")

    responses: list[dict] = json.loads(raw).get("responses", [])
    if not responses:
        logger.info(f"No responses in {blob.name}")

    for i, resp in enumerate(responses):
        uri = resp.get("context", dict()).get("uri")
        if not uri:
            logger.warning(f"No URI found for response at index {i} of {blob.name}")
            continue
        yield uri, resp
