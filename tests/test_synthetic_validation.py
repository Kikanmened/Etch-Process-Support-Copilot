from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.models import DatasetLoadError
from etch_copilot.provenance import sha256_file
from etch_copilot.synthetic import (
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
)


def _refresh_manifest_hash(directory: Path, filename: str) -> None:
    manifest_path = directory / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][filename] = sha256_file(directory / filename)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_generated_dataset_validates_referential_and_time_contracts(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=42))

    dataset = load_synthetic_dataset(output)

    assert dataset.validation.structurally_valid is True
    assert dataset.validation.record_counts == {
        "maintenance": 1,
        "metrology": 570,
        "runs": 114,
        "telemetry": 2850,
    }
    assert dataset.validation.baseline_counts == {"S1": 30, "S2": 30, "S3": 30}
    assert dataset.validation.incident_counts == {"S1": 8, "S2": 8, "S3": 8}
    assert dataset.runs["start_ts_utc"].dt.tz is not None
    assert dataset.telemetry["timestamp_utc"].dt.tz is not None


def test_s3_metrology_is_reported_as_scientifically_blocking_not_structurally_invalid(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=42))

    dataset = load_synthetic_dataset(output)
    s3_codes = {issue.code for issue in dataset.validation.issues if issue.scenario_id == "S3"}

    assert dataset.validation.structurally_valid is True
    assert "INVALID_MEASUREMENT_STATUS" in s3_codes
    assert "INCONSISTENT_THICKNESS_UNIT" in s3_codes
    assert "POST_THICKNESS_EXCEEDS_PRE" in s3_codes
    assert not {
        issue.code for issue in dataset.validation.issues if issue.scenario_id in {"S1", "S2"}
    }


def test_unknown_run_reference_fails_closed(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=5))
    telemetry = pd.read_csv(output / "telemetry.csv")
    telemetry.loc[0, "run_id"] = "UNKNOWN-RUN"
    telemetry.to_csv(output / "telemetry.csv", index=False, lineterminator="\n")

    with pytest.raises(DatasetLoadError, match="provenance hash mismatch"):
        load_synthetic_dataset(output)


def test_duration_timestamp_mismatch_is_rejected_after_manifest_is_refreshed(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=5))
    runs = pd.read_csv(output / "runs.csv")
    runs.loc[0, "etch_duration_s"] = 999
    runs.to_csv(output / "runs.csv", index=False, lineterminator="\n", float_format="%.6f")
    _refresh_manifest_hash(output, "runs.csv")

    with pytest.raises(DatasetLoadError, match="run duration does not match"):
        load_synthetic_dataset(output)


@pytest.mark.parametrize(
    ("filename", "column", "value", "message"),
    [
        ("telemetry.csv", "gas1_flow_sccm", -1.0, "negative telemetry value"),
        ("telemetry.csv", "pressure_mTorr", "not-a-number", "non-numeric telemetry"),
        ("runs.csv", "recipe_id", "", "missing required value"),
        ("runs.csv", "run_id", "bad identifier", "invalid run identifier"),
        ("metrology.csv", "site_id", "UNKNOWN", "unknown metrology site"),
        ("metrology.csv", "pre_thickness_nm", -1.0, "negative thickness"),
        (
            "metrology.csv",
            "measurement_method",
            "fabricated_unknown_method",
            "unsupported measurement method",
        ),
        (
            "metrology.csv",
            "pre_standard_uncertainty_nm",
            -0.1,
            "invalid measurement uncertainty",
        ),
    ],
)
def test_structural_contract_violations_are_rejected(
    tmp_path: Path,
    filename: str,
    column: str,
    value: object,
    message: str,
) -> None:
    output = tmp_path / filename.removesuffix(".csv")
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=8))
    frame = pd.read_csv(output / filename)
    if isinstance(value, str):
        frame[column] = frame[column].astype(object)
    frame.loc[0, column] = value
    frame.to_csv(output / filename, index=False, lineterminator="\n", float_format="%.6f")
    _refresh_manifest_hash(output, filename)

    with pytest.raises(DatasetLoadError, match=message):
        load_synthetic_dataset(output)


def test_missing_telemetry_sample_is_rejected_as_interval_contract_violation(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=8))
    telemetry = pd.read_csv(output / "telemetry.csv")
    telemetry = telemetry.drop(index=1)
    telemetry.to_csv(
        output / "telemetry.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_manifest_hash(output, "telemetry.csv")

    with pytest.raises(DatasetLoadError, match="telemetry interval differs"):
        load_synthetic_dataset(output)


def test_run_without_metrology_is_rejected(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=8))
    metrology = pd.read_csv(output / "metrology.csv")
    metrology = metrology.loc[metrology["run_id"] != "S1-R001"]
    metrology.to_csv(
        output / "metrology.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    _refresh_manifest_hash(output, "metrology.csv")

    with pytest.raises(DatasetLoadError, match="metrology does not cover every run"):
        load_synthetic_dataset(output)


def test_s1_requires_canonical_maintenance_event_and_incident_links(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=8))
    runs = pd.read_csv(output / "runs.csv")
    runs.loc[runs["scenario_id"] == "S1", "maintenance_event_id"] = ""
    runs.to_csv(output / "runs.csv", index=False, lineterminator="\n", float_format="%.6f")
    maintenance = pd.read_csv(output / "maintenance.csv").iloc[0:0]
    maintenance.to_csv(output / "maintenance.csv", index=False, lineterminator="\n")
    _refresh_manifest_hash(output, "runs.csv")
    _refresh_manifest_hash(output, "maintenance.csv")

    with pytest.raises(DatasetLoadError, match="canonical S1 maintenance event"):
        load_synthetic_dataset(output)
