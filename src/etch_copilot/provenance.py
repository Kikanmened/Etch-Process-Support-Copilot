"""Local source-file provenance helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from etch_copilot.models import DatasetLoadError, DatasetProvenance


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_files(directory: Path, names: tuple[str, ...]) -> tuple[Path, ...]:
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise DatasetLoadError(
            f"Missing required source files in {directory}: {', '.join(sorted(missing))}"
        )
    return tuple(directory / name for name in names)


def build_provenance(
    dataset_id: str,
    directory: Path,
    files: tuple[Path, ...],
    notes: tuple[str, ...] = (),
) -> DatasetProvenance:
    ordered = tuple(sorted(files, key=lambda item: item.name))
    return DatasetProvenance(
        dataset_id=dataset_id,
        source_directory=directory.as_posix(),
        source_files=tuple(item.name for item in ordered),
        sha256={item.name: sha256_file(item) for item in ordered},
        extraction_notes=notes,
    )
