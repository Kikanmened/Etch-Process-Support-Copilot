from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset
from etch_copilot.qualification import (
    AnalysisBlockedError,
    AnalysisId,
    ReadinessStatus,
    assert_analysis_permitted,
    build_bosch_qualification,
    build_phm_qualification,
    canonicalize_phm_equipment_id,
    event_coordinate_coverage,
    phm_analytical_view,
    qualify_bosch_scope,
)
from etch_copilot.qualification_reports import write_qualification_reports


def test_bosch_elapsed_time_is_qualified_but_absolute_time_is_blocked(
    bosch_fixture: Path,
) -> None:
    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    assert qualification.time.elapsed_time_verified
    assert qualification.time.elapsed_time_unit == "s"
    assert qualification.time.absolute_time_verified is False
    assert qualification.time.recording_span_eligible
    assert qualification.time.exact_etch_duration_verified is False
    assert qualification.time.sample_interval_s == pytest.approx(0.2)

    elapsed = qualification.decision(AnalysisId.BOSCH_ELAPSED_TREND)
    calendar = qualification.decision(AnalysisId.BOSCH_CALENDAR_EVENT_CORRELATION)
    assert elapsed.status is ReadinessStatus.SUPPORTED
    assert calendar.status is ReadinessStatus.BLOCKED
    with pytest.raises(AnalysisBlockedError):
        assert_analysis_permitted(calendar)


def test_bosch_missing_time_units_block_elapsed_analysis(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        del handle["Day_2024_07_02_Wafer_01/times"].attrs["units"]

    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    assert qualification.time.elapsed_time_verified is False
    decision = qualification.decision(AnalysisId.BOSCH_ELAPSED_TREND)
    assert decision.status is ReadinessStatus.BLOCKED
    with pytest.raises(AnalysisBlockedError):
        assert_analysis_permitted(decision)


def test_bosch_metrology_contract_handles_missing_and_partial_sites(
    bosch_fixture: Path,
) -> None:
    metrology_path = bosch_fixture / "Si_Oxide_etch_89_points.csv"
    frame = pd.read_csv(metrology_path)
    frame.loc[0, "postox_thickness_nan"] = None
    frame.to_csv(metrology_path, index=False)

    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    wafer = qualification.metrology.wafers[0]
    assert wafer.expected_site_count == 89
    assert wafer.observed_site_count == 1
    assert wafer.complete_spatial_coverage is False
    assert wafer.missing_raw_post_thickness_sites == 1
    assert (
        qualification.decision(AnalysisId.BOSCH_WAFER_UNIFORMITY).status is ReadinessStatus.BLOCKED
    )


def test_bosch_run_aware_feature_registry_preserves_source_names(
    bosch_fixture: Path,
) -> None:
    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    feature = qualification.features.features[0]
    assert feature.source_name == "pressure"
    assert feature.available_run_ids == ("Day_2024_07_02_Wafer_01",)
    assert feature.engineering_unit is None
    assert feature.unit_verified is False


def test_bosch_scoped_readiness_blocks_absent_feature(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        group = handle.create_group("Day_2024_07_03_Wafer_01")
        group.create_dataset("data", data=np.array([[1], [2]], dtype=np.uint16))
        group.create_dataset("feature", data=np.array(["temperature"], dtype=h5py.string_dtype()))
        times = group.create_dataset("times", data=np.array([90.0, 90.2]))
        times.attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"

    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    decision = qualify_bosch_scope(
        qualification,
        AnalysisId.BOSCH_CROSS_RUN_COMPARISON,
        run_ids=("Day_2024_07_02_Wafer_01", "Day_2024_07_03_Wafer_01"),
        feature="pressure",
    )

    assert decision.status is ReadinessStatus.BLOCKED
    assert "feature is absent" in decision.blocking_issues[0]


def test_bosch_ambiguous_run_join_and_wrong_lot_are_not_eligible(
    bosch_fixture: Path,
) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        original = handle["Day_2024_07_02_Wafer_01"]
        duplicate = handle.create_group("Day_2024_07_02_Wafer_1")
        for name in ("data", "feature", "times"):
            original.copy(name, duplicate)
    metrology_path = bosch_fixture / "Si_Oxide_etch_89_points.csv"
    frame = pd.read_csv(metrology_path)
    frame["lot_number"] = 2
    frame.to_csv(metrology_path, index=False)

    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    wafer = qualification.metrology.wafers[0]
    assert wafer.relationship_unambiguous is False
    assert wafer.run_id is None
    assert "multiple matching process runs" in wafer.blocking_reasons
    assert "lot/date relationship mismatch" in wafer.blocking_reasons


def test_phm_equipment_mapping_is_verified_and_reversible(phm_fixture: Path) -> None:
    qualification = build_phm_qualification(load_phm_dataset(phm_fixture))
    mapping = qualification.identifiers.equipment_mappings[0]

    assert mapping.source_ids == ("01M01", "01_M01")
    assert mapping.canonical_id == "01M01"
    assert mapping.verified
    assert canonicalize_phm_equipment_id("01_M01", qualification.identifiers) == "01M01"
    assert canonicalize_phm_equipment_id("UNKNOWN", qualification.identifiers) is None


def test_phm_exact_duplicates_are_identified_without_mutating_raw_data(
    phm_fixture: Path,
) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
    frame.to_parquet(path, index=False)
    manifest_path = phm_fixture / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["retained_sensor_rows"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    dataset = load_phm_dataset(phm_fixture)

    view, policy = phm_analytical_view(dataset)

    assert len(dataset.observations) == 4
    assert len(view) == 3
    assert policy.exact_duplicate_count == 1
    assert policy.raw_records_preserved
    assert policy.removal_mode == "analytical_view_only"


def test_phm_duplicate_with_nan_still_has_matching_timestamp(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame.loc[1, "SENSOR_A"] = None
    frame = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
    frame.to_parquet(path, index=False)
    manifest_path = phm_fixture / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["retained_sensor_rows"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    qualification = build_phm_qualification(load_phm_dataset(phm_fixture))

    assert qualification.duplicates.exact_duplicate_count == 1
    assert qualification.duplicates.duplicate_rows_share_timestamp


def test_phm_event_coverage_is_equipment_scoped(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    frame.loc[1, "Tool"] = "OTHER"
    frame.to_parquet(path, index=False)

    coverage = event_coordinate_coverage(load_phm_dataset(phm_fixture))

    assert coverage[0].exact_match is False
    assert coverage[0].previous_coordinate == 100
    assert coverage[0].following_coordinate == 120


def test_phm_event_coverage_uses_raw_coordinate_without_claiming_time_units(
    phm_fixture: Path,
) -> None:
    dataset = load_phm_dataset(phm_fixture)
    coverage = event_coordinate_coverage(dataset)

    assert len(coverage) == 1
    assert coverage[0].exact_match
    assert coverage[0].nearest_distance == 0
    assert coverage[0].previous_coordinate == 100
    assert coverage[0].following_coordinate == 120
    assert coverage[0].coordinate_unit is None
    assert coverage[0].fault_semantics == "recorded_equipment_event"


def test_phm_unverified_time_units_block_temporal_fault_analysis(phm_fixture: Path) -> None:
    qualification = build_phm_qualification(load_phm_dataset(phm_fixture))

    assert qualification.time.coordinate_comparable
    assert qualification.time.unit_verified is False
    assert (
        qualification.decision(AnalysisId.PHM_EVENT_CENTERED_COMPARISON).status
        is ReadinessStatus.BLOCKED
    )
    assert (
        qualification.decision(AnalysisId.PHM_FAULT_EVENT_INVENTORY).status
        is ReadinessStatus.SUPPORTED
    )


def test_readiness_evidence_is_source_specific(phm_fixture: Path, bosch_fixture: Path) -> None:
    bosch = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    phm = build_phm_qualification(load_phm_dataset(phm_fixture))

    assert all(item.dataset_id.startswith("bosch_") for item in bosch.readiness)
    assert all(item.dataset_id.startswith("phm_") for item in phm.readiness)
    assert all(item.evidence for item in (*bosch.readiness, *phm.readiness))


def test_qualification_reports_are_deterministic(
    phm_fixture: Path, bosch_fixture: Path, tmp_path: Path
) -> None:
    bosch = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    phm = build_phm_qualification(load_phm_dataset(phm_fixture))

    first = write_qualification_reports(bosch, phm, tmp_path / "first")
    second = write_qualification_reports(bosch, phm, tmp_path / "second")

    assert [path.read_bytes() for path in first] == [path.read_bytes() for path in second]
    payload = json.loads(first[0].read_text(encoding="utf-8"))
    assert set(payload["provenance"]["source_files"]) == {
        "Dictionary_process.nc",
        "Lot_status.xlsx",
        "Process_data.nc",
        "Si_Oxide_etch_89_points.csv",
    }
