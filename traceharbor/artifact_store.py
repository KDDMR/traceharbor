"""Streaming, content-addressed storage for uploaded build artifacts."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


class ArtifactStorageError(RuntimeError):
    """Raised when an artifact cannot be stored safely."""


class ArtifactTooLargeError(ArtifactStorageError):
    """Raised before or during streaming when the configured limit is exceeded."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    object_key: str
    sha256: str
    size_bytes: int


class LocalArtifactStore:
    """Store artifacts by digest without loading the request body into memory.

    The interface deliberately resembles object storage: callers receive an opaque
    object key and never construct filesystem paths themselves. A production
    adapter can replace this implementation with S3-compatible multipart upload.
    """

    chunk_size = 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.objects = self.root / "objects"
        self.temporary = self.root / "tmp"
        self.objects.mkdir(parents=True, exist_ok=True)
        self.temporary.mkdir(parents=True, exist_ok=True)

    def put_stream(
        self,
        stream: BinaryIO,
        content_length: int,
        max_bytes: int,
    ) -> StoredArtifact:
        if content_length <= 0:
            raise ArtifactStorageError("artifact body must not be empty")
        if content_length > max_bytes:
            raise ArtifactTooLargeError(f"artifact exceeds the {max_bytes}-byte limit")

        digest = hashlib.sha256()
        remaining = content_length
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.temporary, delete=False) as temporary:
                temp_path = Path(temporary.name)
                while remaining:
                    chunk = stream.read(min(self.chunk_size, remaining))
                    if not chunk:
                        raise ArtifactStorageError("artifact body ended before Content-Length")
                    digest.update(chunk)
                    temporary.write(chunk)
                    remaining -= len(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())

            hexdigest = digest.hexdigest()
            object_key = f"sha256/{hexdigest[:2]}/{hexdigest}.zip"
            destination = self.root / object_key
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                temp_path.unlink()
            else:
                os.replace(temp_path, destination)
            return StoredArtifact(
                object_key=object_key,
                sha256=hexdigest,
                size_bytes=content_length,
            )
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    def path_for(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        root = self.root.resolve()
        if root not in candidate.parents:
            raise ArtifactStorageError("invalid object key")
        if not candidate.is_file():
            raise ArtifactStorageError("artifact object is missing")
        return candidate
