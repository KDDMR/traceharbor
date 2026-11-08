"""Safe ZIP inspection and pixel-level snapshot comparison."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile, ZipInfo

from PIL import Image, ImageChops, UnidentifiedImageError

from .artifact_repository import ArtifactRepository
from .artifact_store import LocalArtifactStore


class PermanentAnalysisError(ValueError):
    """Raised for malformed input that should not be retried."""


@dataclass(frozen=True, slots=True)
class Snapshot:
    path: str
    info: ZipInfo
    sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    summary: dict[str, Any]
    diffs: list[dict[str, Any]]


class SnapshotAnalyzer:
    def __init__(
        self,
        repository: ArtifactRepository,
        object_store: LocalArtifactStore,
        *,
        max_snapshots: int = 10_000,
        max_uncompressed_bytes: int = 500_000_000,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.max_snapshots = max_snapshots
        self.max_uncompressed_bytes = max_uncompressed_bytes

    def analyze(self, build_id: str) -> AnalysisResult:
        build = self.repository.get_build(build_id)
        if build is None:
            raise PermanentAnalysisError("build does not exist")

        baseline = None
        if build.get("baseline_build_id"):
            baseline = self.repository.get_build(build["baseline_build_id"])
            if baseline is None or baseline["project"] != build["project"]:
                raise PermanentAnalysisError("baseline build is invalid for this project")
            if baseline["status"] != "completed":
                raise PermanentAnalysisError("baseline build has not completed")
        else:
            baseline = self.repository.latest_completed_build(build["project"], build_id)

        try:
            with ZipFile(self.object_store.path_for(build["object_key"])) as current_archive:
                current = self._index(current_archive)
                if baseline is None:
                    diffs = [
                        self._diff_record(
                            snapshot.path,
                            "baseline",
                            0.0,
                            None,
                            snapshot,
                        )
                        for snapshot in current.values()
                    ]
                else:
                    with ZipFile(self.object_store.path_for(baseline["object_key"])) as baseline_archive:
                        previous = self._index(baseline_archive)
                        diffs = self._compare(baseline_archive, previous, current_archive, current)
        except BadZipFile as exc:
            raise PermanentAnalysisError("artifact must be a valid ZIP archive") from exc

        counts: dict[str, int] = {}
        for item in diffs:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        summary = {
            "baseline_build_id": baseline["build_id"] if baseline else None,
            "snapshot_count": len(current),
            "counts": counts,
            "changed": counts.get("changed", 0) + counts.get("added", 0) + counts.get("removed", 0),
        }
        return AnalysisResult(summary=summary, diffs=diffs)

    def _index(self, archive: ZipFile) -> dict[str, Snapshot]:
        candidates = [item for item in archive.infolist() if not item.is_dir()]
        if len(candidates) > self.max_snapshots:
            raise PermanentAnalysisError(f"archive contains more than {self.max_snapshots} files")
        total_size = sum(item.file_size for item in candidates)
        if total_size > self.max_uncompressed_bytes:
            raise PermanentAnalysisError("archive exceeds the uncompressed-size limit")

        snapshots: dict[str, Snapshot] = {}
        for info in candidates:
            path = self._safe_png_path(info.filename)
            if path is None:
                continue
            if path in snapshots:
                raise PermanentAnalysisError(f"duplicate snapshot path: {path}")
            data = archive.read(info)
            try:
                with Image.open(BytesIO(data)) as image:
                    width, height = image.size
                    image.verify()
            except (UnidentifiedImageError, OSError) as exc:
                raise PermanentAnalysisError(f"invalid PNG image: {path}") from exc
            snapshots[path] = Snapshot(
                path=path,
                info=info,
                sha256=hashlib.sha256(data).hexdigest(),
                width=width,
                height=height,
            )
        if not snapshots:
            raise PermanentAnalysisError("archive does not contain PNG snapshots")
        return snapshots

    @staticmethod
    def _safe_png_path(filename: str) -> str | None:
        normalized = filename.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise PermanentAnalysisError("archive contains an unsafe path")
        if path.suffix.lower() != ".png":
            return None
        return str(path)

    def _compare(
        self,
        baseline_archive: ZipFile,
        baseline: dict[str, Snapshot],
        current_archive: ZipFile,
        current: dict[str, Snapshot],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in sorted(baseline.keys() | current.keys()):
            previous = baseline.get(path)
            latest = current.get(path)
            if previous is None:
                assert latest is not None
                result.append(self._diff_record(path, "added", 1.0, None, latest))
            elif latest is None:
                result.append(self._diff_record(path, "removed", 1.0, previous, None))
            elif previous.sha256 == latest.sha256:
                result.append(self._diff_record(path, "unchanged", 0.0, previous, latest))
            else:
                ratio = self._pixel_difference(
                    baseline_archive.read(previous.info),
                    current_archive.read(latest.info),
                )
                result.append(self._diff_record(path, "changed", ratio, previous, latest))
        return result

    @staticmethod
    def _pixel_difference(baseline: bytes, current: bytes) -> float:
        with Image.open(BytesIO(baseline)) as previous_image, Image.open(BytesIO(current)) as current_image:
            previous = previous_image.convert("RGBA")
            latest = current_image.convert("RGBA")
            if previous.size != latest.size:
                return 1.0
            difference = ImageChops.difference(previous, latest)
            red, green, blue, alpha = difference.split()
            mask = ImageChops.lighter(ImageChops.lighter(red, green), ImageChops.lighter(blue, alpha))
            changed_pixels = previous.width * previous.height - mask.histogram()[0]
            return round(changed_pixels / (previous.width * previous.height), 6)

    @staticmethod
    def _diff_record(
        path: str,
        status: str,
        difference_ratio: float,
        baseline: Snapshot | None,
        current: Snapshot | None,
    ) -> dict[str, Any]:
        dimensions = current or baseline
        assert dimensions is not None
        return {
            "path": path,
            "status": status,
            "difference_ratio": difference_ratio,
            "baseline_sha256": baseline.sha256 if baseline else None,
            "current_sha256": current.sha256 if current else None,
            "width": dimensions.width,
            "height": dimensions.height,
        }
