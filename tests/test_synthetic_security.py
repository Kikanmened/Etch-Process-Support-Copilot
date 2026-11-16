from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from etch_copilot.models import DatasetLoadError
from etch_copilot.synthetic import (
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
)
from etch_copilot.synthetic.generator import _require_distinct_directories


def test_loader_rejects_truth_file_in_application_dataset(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    (output / "scenario_truth.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="scenario truth must be isolated"):
        load_synthetic_dataset(output)


def test_generator_rejects_distinct_descriptors_for_same_directory(tmp_path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    first = os.open(tmp_path, flags)
    second = os.open(tmp_path, flags)
    try:
        with pytest.raises(ValueError, match="must be separate"):
            _require_distinct_directories(first, second)
    finally:
        os.close(first)
        os.close(second)


def test_loader_rejects_nested_truth_and_unexpected_content(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    nested = output / "hidden"
    nested.mkdir()
    (nested / "scenario_truth.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="unexpected content"):
        load_synthetic_dataset(output)


def test_loader_rejects_symlinked_dataset_directory(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    linked = tmp_path / "linked"
    linked.symlink_to(output, target_is_directory=True)

    with pytest.raises(DatasetLoadError, match="must not be a symlink"):
        load_synthetic_dataset(linked)


def test_loader_rejects_symlinked_required_file(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    target = tmp_path / "runs-copy.csv"
    target.write_bytes((output / "runs.csv").read_bytes())
    (output / "runs.csv").unlink()
    (output / "runs.csv").symlink_to(target)

    with pytest.raises(DatasetLoadError, match="must not be symlinks"):
        load_synthetic_dataset(output)


def test_loader_rejects_manifest_path_traversal(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    manifest_path = output / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["../outside.csv"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="unsafe manifest filename"):
        load_synthetic_dataset(output)


def test_loader_rejects_cross_platform_manifest_separator(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    manifest_path = output / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][r"..\outside.csv"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="unsafe manifest filename"):
        load_synthetic_dataset(output)


def test_loader_rejects_manifest_scenario_membership_mismatch(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    manifest_path = output / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["scenarios"] = ["S1"]
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    with pytest.raises(DatasetLoadError, match="scenario membership"):
        load_synthetic_dataset(output)


def test_loader_enforces_source_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    monkeypatch.setattr("etch_copilot.synthetic.validation.MAX_SOURCE_BYTES", 10)

    with pytest.raises(DatasetLoadError, match="exceeds size limit"):
        load_synthetic_dataset(output)


def test_loader_bounds_csv_parse_to_row_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=3))
    monkeypatch.setattr("etch_copilot.synthetic.validation.MAX_RUNS", 1)

    with pytest.raises(DatasetLoadError, match="row count exceeds limit"):
        load_synthetic_dataset(output)
