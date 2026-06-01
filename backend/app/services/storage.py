"""File storage. Local filesystem on the VPS volume, behind an interface so S3 can be
dropped in later without touching call sites.

Layout: {FILE_STORAGE_DIR}/{user_id}/{content_hash}.{ext}  (content-addressed → dedup-friendly)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from app.config import settings


class Storage(Protocol):
    def save(self, *, user_id: str, content_hash: str, filename: str, data: bytes) -> str: ...
    def open(self, uri: str) -> bytes: ...
    def delete(self, uri: str) -> None: ...


class LocalFSStorage:
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir)

    def save(self, *, user_id: str, content_hash: str, filename: str, data: bytes) -> str:
        ext = os.path.splitext(filename)[1].lstrip(".") or "bin"
        target = self.base / user_id / f"{content_hash}.{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    def open(self, uri: str) -> bytes:
        return Path(uri).read_bytes()

    def delete(self, uri: str) -> None:
        Path(uri).unlink(missing_ok=True)


def get_storage() -> Storage:
    # Swap for an S3Storage implementation later — call sites are unaffected.
    return LocalFSStorage(settings.file_storage_dir)
