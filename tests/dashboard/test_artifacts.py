"""Verification tools must never overwrite through links or escape their fixed target."""

from pathlib import Path

import pytest

from etch_copilot.dashboard.artifacts import write_verification_artifact


def test_safe_atomic_artifacts(tmp_path: Path) -> None:
    write_verification_artifact("performance.json", b"{}", root=tmp_path)
    path = tmp_path / "data/processed/dashboard/performance.json"
    assert path.read_bytes() == b"{}"
    write_verification_artifact("performance.json", b'{"updated":true}', root=tmp_path)
    assert path.read_bytes() == b'{"updated":true}'
    with pytest.raises(ValueError):
        write_verification_artifact("../outside", b"bad", root=tmp_path)


def test_linked_final_target_is_not_overwritten(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"protected")
    output = tmp_path / "data/processed/dashboard"
    output.mkdir(parents=True)
    (output / "performance.json").symlink_to(outside)
    with pytest.raises(ValueError):
        write_verification_artifact("performance.json", b"bad", root=tmp_path)
    assert outside.read_bytes() == b"protected"


def test_linked_parent_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        write_verification_artifact("performance.json", b"bad", root=tmp_path)
    assert list(outside.iterdir()) == []
