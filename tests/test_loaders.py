from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.audit import write_reports
from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset
from etch_copilot.models import DatasetLoadError


def test_load_bosch_decodes_dictionary_and_relates_metrology(bosch_fixture: Path) -> None:
    dataset = load_bosch_dataset(bosch_fixture)

    assert dataset.runs[0].values["pressure"].tolist() == [1.5, 2.5]
    assert dataset.validation.record_counts["sensor_observations"] == 2
    assert dataset.validation.identifier_relationships["runs_without_metrology"] == []
    assert "TIMESTAMP_METADATA_CONFLICT" in {issue.code for issue in dataset.validation.issues}
    assert "SENSOR_UNITS_UNAVAILABLE" in {issue.code for issue in dataset.validation.issues}


def test_load_phm_preserves_source_isolation_and_event_semantics(phm_fixture: Path) -> None:
    dataset = load_phm_dataset(phm_fixture)

    assert dataset.provenance.dataset_id == "phm_ion_mill_2018_compact"
    assert dataset.validation.record_counts["sensor_observations"] == 3
    assert dataset.validation.record_counts["fault_events"] == 1
    assert "not assumed to be exact fault onset" in dataset.faults[0].time_semantics
    assert (
        dataset.validation.identifier_relationships["sampling_gap_candidates_over_10x_median"] == 0
    )
    assert dataset.observations.columns.tolist()[-1] == "SENSOR_A"


def test_missing_source_file_has_useful_error(phm_fixture: Path) -> None:
    (phm_fixture / "fault_events.csv").unlink()

    with pytest.raises(DatasetLoadError, match="fault_events.csv"):
        load_phm_dataset(phm_fixture)


def test_malformed_phm_schema_is_rejected(phm_fixture: Path) -> None:
    frame = pd.read_parquet(phm_fixture / "equipment_sensor_data.parquet").drop(columns="time")
    frame.to_parquet(phm_fixture / "equipment_sensor_data.parquet", index=False)

    with pytest.raises(DatasetLoadError, match="time"):
        load_phm_dataset(phm_fixture)


def test_invalid_timestamp_order_is_an_error(phm_fixture: Path) -> None:
    frame = pd.read_parquet(phm_fixture / "equipment_sensor_data.parquet")
    frame["time"] = [100, 90, 120]
    frame.to_parquet(phm_fixture / "equipment_sensor_data.parquet", index=False)

    dataset = load_phm_dataset(phm_fixture)

    assert not dataset.validation.valid
    assert "NON_CHRONOLOGICAL_DATASET" in {issue.code for issue in dataset.validation.issues}


def test_duplicate_records_are_reported(phm_fixture: Path) -> None:
    frame = pd.read_parquet(phm_fixture / "equipment_sensor_data.parquet")
    frame = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
    frame.to_parquet(phm_fixture / "equipment_sensor_data.parquet", index=False)
    manifest_path = phm_fixture / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["retained_sensor_rows"] = 4
    manifest_path.write_text(json.dumps(manifest))

    dataset = load_phm_dataset(phm_fixture)

    assert dataset.validation.duplicate_counts["sensor_rows"] == 1


def test_mismatched_fault_equipment_is_rejected(phm_fixture: Path) -> None:
    faults = pd.read_csv(phm_fixture / "fault_events.csv")
    faults["Tool"] = "OTHER"
    faults.to_csv(phm_fixture / "fault_events.csv", index=False)

    dataset = load_phm_dataset(phm_fixture)

    assert not dataset.validation.valid
    assert "FAULT_EQUIPMENT_MISMATCH" in {issue.code for issue in dataset.validation.issues}


def test_audit_reports_are_deterministic(phm_fixture: Path, tmp_path: Path) -> None:
    dataset = load_phm_dataset(phm_fixture)
    first = write_reports(dataset, tmp_path / "first")
    second = write_reports(dataset, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
