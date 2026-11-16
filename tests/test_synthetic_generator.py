from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from etch_copilot.synthetic import (
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
)


def _file_bytes(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir()) if path.is_file()}


def test_same_seed_produces_byte_identical_dataset_and_separate_truth(tmp_path: Path) -> None:
    config = SyntheticGeneratorConfig(seed=20261112)
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_truth = tmp_path / "first-truth"
    second_truth = tmp_path / "second-truth"

    first_result = generate_synthetic_dataset(first, config, truth_directory=first_truth)
    second_result = generate_synthetic_dataset(second, config, truth_directory=second_truth)

    assert _file_bytes(first) == _file_bytes(second)
    assert _file_bytes(first_truth) == _file_bytes(second_truth)
    assert first_result.file_sha256 == second_result.file_sha256
    assert "scenario_truth.json" not in first_result.visible_files
    assert not (first / "scenario_truth.json").exists()
    assert (first_truth / "scenario_truth.json").is_file()


def test_different_seed_changes_observations_but_preserves_contract(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_synthetic_dataset(first, SyntheticGeneratorConfig(seed=11))
    generate_synthetic_dataset(second, SyntheticGeneratorConfig(seed=12))

    assert (first / "runs.csv").read_bytes() == (second / "runs.csv").read_bytes()
    assert (first / "telemetry.csv").read_bytes() != (second / "telemetry.csv").read_bytes()
    assert (first / "metrology.csv").read_bytes() != (second / "metrology.csv").read_bytes()
    assert (
        pd.read_csv(first / "telemetry.csv").columns.tolist()
        == pd.read_csv(second / "telemetry.csv").columns.tolist()
    )


def test_generator_emits_three_isolated_scenarios_and_declared_sampling(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=7))

    runs = pd.read_csv(output / "runs.csv", dtype={"run_id": str})
    telemetry = pd.read_csv(output / "telemetry.csv", dtype={"run_id": str})
    metrology = pd.read_csv(output / "metrology.csv", dtype={"run_id": str})

    assert set(runs["scenario_id"]) == {"S1", "S2", "S3"}
    assert runs.groupby("scenario_id")["chamber_id"].nunique().to_dict() == {
        "S1": 1,
        "S2": 1,
        "S3": 1,
    }
    assert runs.groupby("scenario_id")["recipe_id"].nunique().to_dict() == {
        "S1": 1,
        "S2": 1,
        "S3": 1,
    }
    assert runs.loc[runs["phase"] == "baseline"].groupby("scenario_id").size().to_dict() == {
        "S1": 30,
        "S2": 30,
        "S3": 30,
    }
    assert runs.loc[runs["phase"] == "incident"].groupby("scenario_id").size().to_dict() == {
        "S1": 8,
        "S2": 8,
        "S3": 8,
    }
    assert telemetry.groupby("run_id").size().eq(25).all()
    assert telemetry["gas2_flow_sccm"].isna().sum() == 1
    assert metrology.groupby("run_id").size().eq(5).all()
    assert set(metrology["site_id"]) == {"CENTER", "NORTH", "EAST", "SOUTH", "WEST"}


def test_generator_refuses_to_overwrite_existing_dataset(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))

    try:
        generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    except FileExistsError as exc:
        assert "already contains" in str(exc)
    else:
        raise AssertionError("generator unexpectedly overwrote an existing dataset")


def test_generator_requires_sampling_interval_to_divide_duration() -> None:
    with pytest.raises(ValidationError, match="must be divisible"):
        SyntheticGeneratorConfig(seed=1, etch_duration_s=121, telemetry_interval_s=5)


def test_generator_requires_truth_to_be_outside_application_dataset(tmp_path: Path) -> None:
    output = tmp_path / "dataset"

    with pytest.raises(ValueError, match="must be separate"):
        generate_synthetic_dataset(
            output,
            SyntheticGeneratorConfig(seed=1),
            truth_directory=output,
        )


def test_generator_rejects_truth_nested_below_application_dataset(tmp_path: Path) -> None:
    output = tmp_path / "dataset"

    with pytest.raises(ValueError, match="must be separate"):
        generate_synthetic_dataset(
            output,
            SyntheticGeneratorConfig(seed=1),
            truth_directory=output / "hidden",
        )


def test_dataset_identity_includes_configuration_not_only_seed(tmp_path: Path) -> None:
    first = generate_synthetic_dataset(
        tmp_path / "first", SyntheticGeneratorConfig(seed=1, etch_duration_s=120)
    )
    second = generate_synthetic_dataset(
        tmp_path / "second", SyntheticGeneratorConfig(seed=1, etch_duration_s=180)
    )

    assert first.dataset_id != second.dataset_id


def test_minimum_supported_run_still_contains_one_missing_value_challenge(
    tmp_path: Path,
) -> None:
    output = tmp_path / "minimum"
    generate_synthetic_dataset(
        output,
        SyntheticGeneratorConfig(seed=1, etch_duration_s=60, telemetry_interval_s=5),
    )

    telemetry = pd.read_csv(output / "telemetry.csv")
    assert telemetry["gas2_flow_sccm"].isna().sum() == 1


@pytest.mark.parametrize(
    ("etch_duration_s", "telemetry_interval_s"),
    [(60, 5), (120, 10), (300, 25), (300, 5)],
)
def test_supported_configuration_boundaries_generate_loadable_datasets(
    tmp_path: Path,
    etch_duration_s: int,
    telemetry_interval_s: int,
) -> None:
    output = tmp_path / f"dataset-{etch_duration_s}-{telemetry_interval_s}"
    generate_synthetic_dataset(
        output,
        SyntheticGeneratorConfig(
            seed=1,
            etch_duration_s=etch_duration_s,
            telemetry_interval_s=telemetry_interval_s,
        ),
    )

    dataset = load_synthetic_dataset(output)

    assert dataset.validation.structurally_valid is True


def test_generator_rejects_sampling_that_omits_scenario_signals() -> None:
    with pytest.raises(ValidationError, match="at least 13 telemetry samples"):
        SyntheticGeneratorConfig(seed=1, etch_duration_s=60, telemetry_interval_s=10)


def test_generator_rejects_configuration_that_exceeds_memory_budget() -> None:
    with pytest.raises(ValidationError, match="telemetry-row limit"):
        SyntheticGeneratorConfig(
            seed=1,
            baseline_runs_per_scenario=500,
            incident_runs_per_scenario=100,
            etch_duration_s=300,
            telemetry_interval_s=1,
        )


def test_generator_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="real directory"):
        generate_synthetic_dataset(
            linked_parent / "dataset",
            SyntheticGeneratorConfig(seed=1),
        )
