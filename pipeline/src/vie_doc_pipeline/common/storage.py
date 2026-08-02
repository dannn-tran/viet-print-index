"""Target-storage contracts and local/GCS implementations."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from collections.abc import Iterator

from google.cloud import storage as gcs_storage

from vie_doc_pipeline.common.config import GcsTarget, LocalTarget, TargetStorage


@dataclass(frozen=True)
class StoredObject:
    checksum: str
    size_bytes: int


class TargetStore(ABC):
    """Read/write contract for the configured durable target."""

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read one target-relative object."""

    @abstractmethod
    def write_bytes(self, path: str, data: bytes, *, content_type: str) -> None:
        """Write one target-relative object."""

    @abstractmethod
    def inspect(self, path: str) -> StoredObject | None:
        """Return object metadata when present, otherwise ``None``."""

    @abstractmethod
    def close(self) -> None:
        """Release target resources."""


class LocalTargetStore(TargetStore):
    def __init__(self, target: LocalTarget) -> None:
        self.root = Path(target.root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def write_bytes(self, path: str, data: bytes, *, content_type: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def inspect(self, path: str) -> StoredObject | None:
        target = self._resolve(path)
        if not target.exists():
            return None
        data = target.read_bytes()
        return StoredObject(hashlib.sha256(data).hexdigest(), len(data))

    def close(self) -> None:
        return None

    def _resolve(self, path: str) -> Path:
        relative = PurePosixPath(path)
        target = (self.root / Path(*relative.parts)).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Target path escapes local root: {path!r}")
        return target


class GcsTargetStore(TargetStore):
    def __init__(self, target: GcsTarget) -> None:
        self.client = gcs_storage.Client(project=target.project)
        self.bucket = self.client.bucket(target.bucket)

    def read_bytes(self, path: str) -> bytes:
        return self.bucket.blob(path).download_as_bytes(timeout=600)

    def write_bytes(self, path: str, data: bytes, *, content_type: str) -> None:
        self.bucket.blob(path).upload_from_string(data, content_type=content_type, timeout=600)

    def inspect(self, path: str) -> StoredObject | None:
        blob = self.bucket.blob(path)
        if not blob.exists(self.client):
            return None
        blob.reload(self.client)
        return StoredObject(blob.md5_hash or "unknown", blob.size or 0)

    def close(self) -> None:
        self.client.close()


@contextmanager
def open_target_store(target: TargetStorage) -> Iterator[TargetStore]:
    """Open the configured target and close it at the workflow boundary."""
    match target:
        case LocalTarget():
            store = LocalTargetStore(target)
        case GcsTarget():
            store = GcsTargetStore(target)
    try:
        yield store
    finally:
        store.close()
