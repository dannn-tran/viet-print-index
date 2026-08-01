import json
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat
from pathlib import Path


def get_ocr_fulltext_one(filepath: str | Path):
    with open(filepath, encoding="utf-8") as handle:
        data = json.load(handle)

    return data["fullTextAnnotation"]["text"]


def extract_ocr_fulltext(src_dir: str, dst_dir: str, workers: int = 4):
    dst_dirpath = Path(dst_dir)
    dst_dirpath.mkdir(parents=True, exist_ok=True)

    files = Path(src_dir).iterdir()
    if workers < 2:
        for file in files:
            _extract_ocr_fulltext_one(file, dst_dirpath)
        return

    with ThreadPoolExecutor(max_workers=workers) as executor:
        for _ in executor.map(_extract_ocr_fulltext_one, files, repeat(dst_dirpath)):
            continue

def _extract_ocr_fulltext_one(src: Path, dst_dirpath: Path):
    text = get_ocr_fulltext_one(src)
    dst = dst_dirpath / f"{src.stem}.txt"
    dst.write_text(text, encoding="utf-8")
