"""Local source-file provenance helpers."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from io import BufferedReader
from pathlib import Path

from etch_copilot.models import DatasetLoadError, DatasetProvenance


@contextmanager
def open_regular_file(path: Path) -> Iterator[BufferedReader]:
    """Open a source without following a final-component symlink."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as exc:
        raise DatasetLoadError(f"Cannot safely open source file: {path}") from exc
    status = os.fstat(file_descriptor)
    if not stat.S_ISREG(status.st_mode):
        os.close(file_descriptor)
        raise DatasetLoadError(f"Source is not a regular file: {path}")
    with os.fdopen(file_descriptor, "rb") as handle:
        yield handle


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open_regular_file(path) as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_files(directory: Path, names: tuple[str, ...]) -> tuple[Path, ...]:
    if directory.is_symlink():
        raise DatasetLoadError(f"Dataset directory must not be a symlink: {directory}")
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise DatasetLoadError(
            f"Missing required source files in {directory}: {', '.join(sorted(missing))}"
        )
    files = tuple(directory / name for name in names)
    linked = [path.name for path in files if path.is_symlink()]
    if linked:
        raise DatasetLoadError(
            "Required source files must not be symlinks: " + ", ".join(sorted(linked))
        )
    return files


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


def verify_provenance(provenance: DatasetProvenance, directory: Path) -> None:
    """Fail closed if any source changed after its initial provenance snapshot."""
    changed = [
        filename
        for filename, expected_hash in provenance.sha256.items()
        if sha256_file(directory / filename) != expected_hash
    ]
    if changed:
        raise DatasetLoadError(
            "Source files changed during ingestion: " + ", ".join(sorted(changed))
        )
