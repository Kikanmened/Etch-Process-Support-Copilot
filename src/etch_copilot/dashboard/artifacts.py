"""Symlink-safe output for developer verification scripts, never imported by the UI."""

import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from etch_copilot.dashboard.service import ROOT

NAMES = frozenset(
    {
        "performance.json",
        "browser-verification.json",
        "bosch-desktop.png",
        "synthetic-s2-desktop.png",
        "synthetic-s2-768.png",
        "synthetic-s2-390.png",
        "phm-desktop.png",
        "phm-768.png",
        "phm-390.png",
    }
)


def write_verification_artifact(name: str, content: bytes, *, root: Path = ROOT) -> None:
    """Write atomically through directory descriptors; reject links at every component."""
    if name not in NAMES or not root.is_absolute() or ".." in root.parts:
        raise ValueError("Invalid verification artifact target.")
    if len(content) > 10 * 1024 * 1024:
        raise ValueError("Verification artifact exceeds the size limit.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    temporary = ""
    try:
        for component in (*root.parts[1:], "data", "processed", "dashboard"):
            with suppress(FileExistsError):
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        try:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Unsafe verification artifact target.")
        except FileNotFoundError:
            pass
        temporary = f".artifact-{secrets.token_hex(16)}.tmp"
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        temporary = ""
        os.fsync(descriptor)
    finally:
        if temporary:
            with suppress(FileNotFoundError):
                os.unlink(temporary, dir_fd=descriptor)
        os.close(descriptor)
