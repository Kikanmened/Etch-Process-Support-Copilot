from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.analytics import (
    AnalyticsScopeError,
    phm_fault_inventory,
    phm_feature_inventory,
)
from etch_copilot.loaders import load_phm_dataset
from etch_copilot.qualification import ReadinessStatus


def test_phm_feature_inventory_preserves_duplicates_and_identifiers(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
    frame.to_parquet(path, index=False)
    manifest_path = phm_fixture / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["retained_sensor_rows"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = phm_feature_inventory(load_phm_dataset(phm_fixture), equipment_id="01_M01")

    assert result.readiness_status is ReadinessStatus.SUPPORTED
    assert result.source_equipment_ids == ("01M01",)
    assert result.canonical_equipment_id == "01M01"
    assert result.raw_observation_count == 4
    assert result.exact_duplicate_count == 1
    sensor = next(item for item in result.features if item.source_name == "SENSOR_A")
    assert sensor.observation_count == 4
    assert sensor.engineering_unit is None
    assert sensor.unit_verified is False


def test_phm_feature_inventory_rejects_unknown_equipment(phm_fixture: Path) -> None:
    with pytest.raises(AnalyticsScopeError, match="Unknown PHM equipment"):
        phm_feature_inventory(load_phm_dataset(phm_fixture), equipment_id="unknown")


def test_phm_null_required_equipment_blocks_feature_inventory(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, "Tool"] = None
    frame.to_parquet(path, index=False)

    dataset = load_phm_dataset(phm_fixture)
    with pytest.raises(RuntimeError, match="source validation failed"):
        phm_feature_inventory(dataset)


def test_phm_feature_inventory_counts_non_numeric_values(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame["SENSOR_A"] = ["0.1", "invalid", "0.3"]
    frame.to_parquet(path, index=False)

    result = phm_feature_inventory(load_phm_dataset(phm_fixture))
    sensor = next(item for item in result.features if item.source_name == "SENSOR_A")

    assert sensor.observation_count == 3
    assert sensor.finite_count == 2
    assert sensor.missing_count == 0
    assert sensor.invalid_non_numeric_count == 1


def test_phm_fault_inventory_reports_events_without_onset_claim(phm_fixture: Path) -> None:
    result = phm_fault_inventory(load_phm_dataset(phm_fixture), equipment_id="01M01")

    assert result.readiness_status is ReadinessStatus.SUPPORTED
    assert result.total_recorded_events == 1
    assert result.category_counts[0].category == "recorded shutdown"
    assert result.events[0].source_coordinate == 110
    assert result.events[0].coordinate_unit is None
    assert result.events[0].is_confirmed_fault_onset is False
    assert "not verified fault onset" in result.event_semantics


def test_phm_fault_inventory_preserves_missing_event_fields(phm_fixture: Path) -> None:
    path = phm_fixture / "fault_events.csv"
    frame = pd.read_csv(path)
    frame.loc[0, ["time", "fault_name", "Tool"]] = None
    frame.to_csv(path, index=False)

    dataset = load_phm_dataset(phm_fixture)
    result = phm_fault_inventory(dataset)

    assert result.total_recorded_events == 1
    assert result.ambiguous_event_field_count == 1
    assert result.events[0].source_coordinate is None
    assert result.events[0].category is None
    assert result.events[0].source_equipment_id is None
    assert result.events[0].missing_fields == (
        "source_coordinate",
        "fault_name",
        "equipment_id",
    )
    assert result.category_counts[0].category is None
    assert all(issue.code != "FAULT_OUTSIDE_SENSOR_RANGE" for issue in dataset.validation.issues)


def test_phm_zero_event_coordinate_is_not_missing(phm_fixture: Path) -> None:
    path = phm_fixture / "fault_events.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "time"] = 0
    frame.to_csv(path, index=False)

    dataset = load_phm_dataset(phm_fixture)
    result = phm_fault_inventory(dataset)

    assert result.events[0].source_coordinate == 0
    assert "source_coordinate" not in result.events[0].missing_fields
    outside_issue = next(
        issue for issue in dataset.validation.issues if issue.code == "FAULT_OUTSIDE_SENSOR_RANGE"
    )
    assert "1 fault events" in outside_issue.message


def test_analytics_results_are_deterministic_json(phm_fixture: Path) -> None:
    dataset = load_phm_dataset(phm_fixture)
    first = phm_feature_inventory(dataset).model_dump_json()
    second = phm_feature_inventory(dataset).model_dump_json()

    assert first == second
