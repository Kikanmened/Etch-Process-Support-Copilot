"""Safe deterministic serialization for local analytics artifacts."""

from __future__ import annotations

import os
import re
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel


def write_analytics_results(
    results: dict[str, BaseModel], output_directory: str | Path
) -> tuple[Path, ...]:
    """Write sorted, indented JSON artifacts without following output symlinks."""
    output = Path(output_directory)
    try:
        directory_fd = _open_directory_no_symlinks(output)
    except OSError as exc:
        raise ValueError(f"unsafe analytics output directory: {output}") from exc
    try:
        paths: list[Path] = []
        for name, result in sorted(results.items()):
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is None:
                raise ValueError(f"unsafe analytics result name: {name}")
            filename = f"{name}.json"
            content = result.model_dump_json(indent=2) + "\n"
            _atomic_write(directory_fd, filename, content)
            paths.append(output / filename)
        return tuple(paths)
    finally:
        os.close(directory_fd)


def _open_directory_no_symlinks(path: Path) -> int:
    if ".." in path.parts:
        raise ValueError(f"unsafe analytics output directory: {path}")
    absolute = path if path.is_absolute() else Path.cwd() / path
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            with suppress(FileExistsError):
                os.mkdir(component, mode=0o700, dir_fd=directory_fd)
            next_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd
    except Exception:
        os.close(directory_fd)
        raise


def _atomic_write(directory_fd: int, filename: str, content: str) -> None:
    try:
        target_status = os.stat(filename, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        target_status = None
    if target_status is not None and not stat.S_ISREG(target_status.st_mode):
        raise ValueError(f"unsafe analytics output target: {filename}")
    temporary_name = f".{filename}.{secrets.token_hex(12)}.tmp"
    temporary_created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_descriptor = os.open(temporary_name, flags, 0o600, dir_fd=directory_fd)
        temporary_created = True
        with os.fdopen(file_descriptor, mode="w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_created = False
        os.fsync(directory_fd)
    finally:
        if temporary_created:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_fd)
