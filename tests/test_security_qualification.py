from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import h5py
import pandas as pd
import pytest
from pydantic import ValidationError

from etch_copilot.analytics import bosch_elapsed_trend, bosch_sensor_statistics
from etch_copilot.loaders import (
    IngestionLimits,
    _dataset_content_sha256,
    _open_verified_source,
    load_bosch_dataset,
    load_phm_dataset,
)
from etch_copilot.models import DatasetLoadError
from etch_copilot.provenance import build_provenance, sha256_file, verify_provenance
from etch_copilot.qualification import (
    AnalysisBlockedError,
    AnalysisId,
    ReadinessStatus,
    assert_analysis_permitted,
    build_bosch_qualification,
    build_phm_qualification,
    canonicalize_phm_equipment_id,
    qualify_bosch_scope,
)
from etch_copilot.qualification_reports import write_qualification_reports


def test_cross_run_scope_cannot_be_approved_without_runs_and_feature(
    bosch_fixture: Path,
) -> None:
    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))

    decision = qualify_bosch_scope(qualification, AnalysisId.BOSCH_CROSS_RUN_COMPARISON)

    assert decision.status is ReadinessStatus.BLOCKED
    assert decision.scope_qualified is False
    with pytest.raises(AnalysisBlockedError):
        assert_analysis_permitted(decision, allow_limited=True)


def test_readiness_decision_is_immutable(bosch_fixture: Path) -> None:
    qualification = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    decision = qualification.decision(AnalysisId.BOSCH_ETCH_RATE)

    with pytest.raises(ValidationError):
        decision.status = ReadinessStatus.SUPPORTED


def test_provenance_verification_fails_after_source_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("original", encoding="utf-8")
    provenance = build_provenance("test", tmp_path, (source,))
    source.write_text("changed", encoding="utf-8")

    with pytest.raises(DatasetLoadError, match="changed during ingestion"):
        verify_provenance(provenance, tmp_path)


def test_ambiguous_equipment_normalization_remains_unresolved(phm_fixture: Path) -> None:
    path = phm_fixture / "equipment_sensor_data.parquet"
    frame = pd.read_parquet(path)
    ambiguous = frame.iloc[[0]].copy()
    ambiguous["Tool"] = "0_1M01"
    frame = pd.concat([frame, ambiguous], ignore_index=True)
    frame.to_parquet(path, index=False)
    manifest_path = phm_fixture / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["retained_sensor_rows"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    qualification = build_phm_qualification(load_phm_dataset(phm_fixture))

    assert canonicalize_phm_equipment_id("01_M01", qualification.identifiers) is None


def test_markdown_report_escapes_untrusted_fence_delimiters(
    phm_fixture: Path, bosch_fixture: Path, tmp_path: Path
) -> None:
    fault_path = phm_fixture / "fault_events.csv"
    faults = pd.read_csv(fault_path)
    faults.loc[0, "fault_name"] = "```html\n<script>unsafe</script>"
    faults.to_csv(fault_path, index=False)
    bosch = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    phm = build_phm_qualification(load_phm_dataset(phm_fixture))

    paths = write_qualification_reports(bosch, phm, tmp_path / "reports")
    phm_markdown = next(path for path in paths if path.name == "phm_engineering_qualification.md")
    content = phm_markdown.read_text(encoding="utf-8")

    assert content.count("```") == 2
    assert "```html" not in content


def test_report_writer_rejects_preexisting_symlink(
    phm_fixture: Path, bosch_fixture: Path, tmp_path: Path
) -> None:
    bosch = build_bosch_qualification(load_bosch_dataset(bosch_fixture))
    phm = build_phm_qualification(load_phm_dataset(phm_fixture))
    output = tmp_path / "reports"
    output.mkdir()
    target = tmp_path / "target.txt"
    target.write_text("preserve", encoding="utf-8")
    (output / "bosch_engineering_qualification.json").symlink_to(target)

    with pytest.raises(ValueError, match="unsafe report target"):
        write_qualification_reports(bosch, phm, output)

    assert target.read_text(encoding="utf-8") == "preserve"


def test_ingestion_limits_reject_oversized_source(phm_fixture: Path) -> None:
    limits = IngestionLimits(max_file_size_bytes=1)

    with pytest.raises(DatasetLoadError, match="safety limit"):
        load_phm_dataset(phm_fixture, limits=limits)


def test_ingestion_limits_reject_run_shape_before_decoding(bosch_fixture: Path) -> None:
    limits = IngestionLimits(max_run_observations=1)

    with pytest.raises(DatasetLoadError, match="run observation limit"):
        load_bosch_dataset(bosch_fixture, limits=limits)


def test_hdf5_decoded_byte_limit_is_checked_before_slice(bosch_fixture: Path) -> None:
    limits = IngestionLimits(max_decoded_bytes=1)

    with pytest.raises(DatasetLoadError, match="decoded bytes"):
        load_bosch_dataset(bosch_fixture, limits=limits)


def test_complex_hdf5_numeric_data_is_rejected(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Dictionary_process.nc", "r+") as handle:
        del handle["data"]
        handle.create_dataset("data", data=[0 + 1j, 1 + 2j, 2 + 3j])

    with pytest.raises(DatasetLoadError, match="real numeric dtype"):
        load_bosch_dataset(bosch_fixture)


def test_hdf5_variable_strings_decode_under_text_budget(bosch_fixture: Path) -> None:
    limits = IngestionLimits(max_feature_text_bytes=1)

    with pytest.raises(DatasetLoadError, match="string content"):
        load_bosch_dataset(bosch_fixture, limits=limits)


def test_csv_column_limit_is_checked_from_header_before_full_decode(
    bosch_fixture: Path,
) -> None:
    limits = IngestionLimits(max_tabular_columns=10)

    with pytest.raises(DatasetLoadError, match="column limit"):
        load_bosch_dataset(bosch_fixture, limits=limits)


def test_verified_source_handle_detects_mutation_during_consumption(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"original")
    expected = sha256_file(source)

    with (
        pytest.raises(DatasetLoadError, match="during parsing"),
        _open_verified_source(source, expected),
    ):
        source.write_bytes(b"changed")


def test_forged_in_memory_seal_cannot_bypass_trusted_reload(bosch_fixture: Path) -> None:
    dataset = load_bosch_dataset(bosch_fixture)
    dataset.runs[0].values.loc[0, "pressure"] = 999.0
    forged = replace(dataset, content_sha256=_dataset_content_sha256(dataset))

    with pytest.raises(DatasetLoadError, match="content changed"):
        bosch_sensor_statistics(forged, "Day_2024_07_02_Wafer_01", "pressure")


def test_required_source_symlink_is_rejected(phm_fixture: Path, tmp_path: Path) -> None:
    source = phm_fixture / "README.md"
    external = tmp_path / "external-readme.md"
    source.replace(external)
    source.symlink_to(external)

    with pytest.raises(DatasetLoadError, match="symlink"):
        load_phm_dataset(phm_fixture)


def test_hdf5_soft_link_member_is_rejected(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        group = handle["Day_2024_07_02_Wafer_01"]
        handle.create_dataset("alternate_feature", data=group["feature"][:])
        del group["feature"]
        group["feature"] = h5py.SoftLink("/alternate_feature")

    with pytest.raises(DatasetLoadError, match="internal hard link"):
        load_bosch_dataset(bosch_fixture)


def test_hdf5_auxiliary_shape_is_rejected_before_decode(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        group = handle["Day_2024_07_02_Wafer_01"]
        del group["times"]
        group.create_dataset("times", data=[90.0, 90.2, 90.4])

    with pytest.raises(DatasetLoadError, match="Shape mismatch"):
        load_bosch_dataset(bosch_fixture)


def test_hdf5_external_storage_is_rejected(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        group = handle["Day_2024_07_02_Wafer_01"]
        del group["times"]
        group.create_dataset(
            "times",
            shape=(2,),
            dtype="float64",
            external=[("external-times.bin", 0, 16)],
        )

    with pytest.raises(DatasetLoadError, match="external storage"):
        load_bosch_dataset(bosch_fixture)


def test_negative_bosch_dictionary_index_is_rejected(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        group = handle["Day_2024_07_02_Wafer_01"]
        del group["data"]
        group.create_dataset("data", data=[[-1], [1]], dtype="int16")

    with pytest.raises(DatasetLoadError, match="Negative dictionary index"):
        load_bosch_dataset(bosch_fixture)


def test_phm_total_cell_limit_is_checked_before_materialization(phm_fixture: Path) -> None:
    limits = IngestionLimits(max_decoded_cells=1)

    with pytest.raises(DatasetLoadError, match="decoded cell count"):
        load_phm_dataset(phm_fixture, limits=limits)


def test_fault_event_row_limit_is_checked_before_csv_materialization(phm_fixture: Path) -> None:
    limits = IngestionLimits(max_fault_events=0)

    with pytest.raises(DatasetLoadError, match="row count"):
        load_phm_dataset(phm_fixture, limits=limits)


def test_carriage_return_csv_cannot_bypass_fault_row_limit(phm_fixture: Path) -> None:
    (phm_fixture / "fault_events.csv").write_bytes(
        b"time,fault_name,Tool\r100,first,01M01\r110,second,01M01\r"
    )
    limits = IngestionLimits(max_fault_events=1)

    with pytest.raises(DatasetLoadError, match="row count"):
        load_phm_dataset(phm_fixture, limits=limits)


def test_csv_record_limit_is_checked_before_pandas_decode(phm_fixture: Path) -> None:
    limits = IngestionLimits(max_delimited_record_bytes=8)

    with pytest.raises(DatasetLoadError, match="record exceeds"):
        load_phm_dataset(phm_fixture, limits=limits)


def test_workbook_shape_limit_is_checked_before_rows_materialize(bosch_fixture: Path) -> None:
    limits = IngestionLimits(max_workbook_rows=1)

    with pytest.raises(DatasetLoadError, match="workbook row limit"):
        load_bosch_dataset(bosch_fixture, limits=limits)


def test_trend_result_size_limit_is_enforced(
    bosch_fixture: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("etch_copilot.analytics.bosch._MAX_TREND_POINTS", 1)

    with pytest.raises(RuntimeError, match="trend output exceeds"):
        bosch_elapsed_trend(
            load_bosch_dataset(bosch_fixture),
            "Day_2024_07_02_Wafer_01",
            "pressure",
        )


def test_loader_uses_neutral_time_semantics_before_qualification(
    bosch_fixture: Path,
) -> None:
    dataset = load_bosch_dataset(bosch_fixture)

    assert dataset.runs[0].metadata.time_basis == "unqualified NetCDF source coordinate"
