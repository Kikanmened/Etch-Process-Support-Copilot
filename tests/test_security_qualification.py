from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from etch_copilot.loaders import IngestionLimits, load_bosch_dataset, load_phm_dataset
from etch_copilot.models import DatasetLoadError
from etch_copilot.provenance import build_provenance, verify_provenance
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


def test_loader_uses_neutral_time_semantics_before_qualification(
    bosch_fixture: Path,
) -> None:
    dataset = load_bosch_dataset(bosch_fixture)

    assert dataset.runs[0].metadata.time_basis == "unqualified NetCDF source coordinate"
