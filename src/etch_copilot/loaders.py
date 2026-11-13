"""Source-specific, read-only loaders for BOSCH and PHM datasets."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from openpyxl import load_workbook

from etch_copilot.models import (
    DataQualityIssue,
    DatasetLoadError,
    DatasetProvenance,
    FaultEvent,
    ProcessRun,
    ScientificReference,
    Severity,
    ValidationSummary,
)
from etch_copilot.provenance import (
    build_provenance,
    require_files,
    sha256_file,
    verify_provenance,
)

BOSCH_REQUIRED = (
    "Process_data.nc",
    "Dictionary_process.nc",
    "Si_Oxide_etch_89_points.csv",
    "Lot_status.xlsx",
)
PHM_REQUIRED = (
    "equipment_sensor_data.parquet",
    "fault_events.csv",
    "dataset_manifest.json",
    "validation_report.json",
    "README.md",
)
PHM_ID_COLUMNS = ("time", "Tool", "stage", "Lot", "runnum", "recipe", "recipe_step")
PHM_FAULT_COLUMNS = ("time", "fault_name", "Tool")
BOSCH_METROLOGY_COLUMNS = (
    "experiment_key",
    "lot_number",
    "wafer_number",
    "X",
    "Y",
    "preox_thickness",
    "postox_thickness",
    "postox_thickness_nan",
    "stepheight",
    "oxide_etch",
    "si_etch",
)
_BOSCH_GROUP = re.compile(r"Day_(\d{4})_(\d{2})_(\d{2})_Wafer_(\d+)$")
BOSCH_PRIMARY_REFERENCE_SHA256 = "7c2690954532617d8681c6c48d65ffb960d8e745c16b0dd12b76c64b1b167336"


@dataclass(frozen=True)
class IngestionLimits:
    """Conservative allocation limits for untrusted external research files."""

    max_file_size_bytes: int = 512 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 256 * 1024 * 1024
    max_archive_members: int = 10_000
    max_bosch_runs: int = 10_000
    max_run_observations: int = 5_000_000
    max_features: int = 10_000
    max_dictionary_entries: int = 10_000_000
    max_decoded_cells: int = 100_000_000
    max_tabular_rows: int = 10_000_000
    max_tabular_columns: int = 10_000


@dataclass(frozen=True)
class BoschRunData:
    metadata: ProcessRun
    elapsed_time_s: np.ndarray[Any, np.dtype[np.float64]]
    values: pd.DataFrame


@dataclass(frozen=True)
class BoschDataset:
    provenance: DatasetProvenance
    runs: tuple[BoschRunData, ...]
    metrology: pd.DataFrame
    lot_status: pd.DataFrame
    validation: ValidationSummary
    scientific_references: tuple[ScientificReference, ...] = ()


@dataclass(frozen=True)
class PhmDataset:
    provenance: DatasetProvenance
    observations: pd.DataFrame
    faults: tuple[FaultEvent, ...]
    manifest: dict[str, Any]
    supplied_validation: dict[str, Any]
    validation: ValidationSummary


def _decode_strings(values: np.ndarray[Any, Any]) -> list[str]:
    return [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]


def _decode_attribute(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _validate_source_files(files: tuple[Path, ...], limits: IngestionLimits) -> None:
    for path in files:
        size = path.stat().st_size
        if size > limits.max_file_size_bytes:
            raise DatasetLoadError(
                f"Source file exceeds configured safety limit: {path.name} ({size} bytes)"
            )
        if path.suffix.lower() == ".xlsx":
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                uncompressed = sum(member.file_size for member in members)
            if len(members) > limits.max_archive_members:
                raise DatasetLoadError(f"XLSX member count exceeds safety limit: {path.name}")
            if uncompressed > limits.max_archive_uncompressed_bytes:
                raise DatasetLoadError(f"XLSX expansion exceeds safety limit: {path.name}")


def _bosch_experiment_key(group_name: str) -> str | None:
    match = _BOSCH_GROUP.fullmatch(group_name)
    if match is None:
        return None
    year, month, day, wafer = match.groups()
    return f"{year}-{month}-{day}_{int(wafer):02d}"


def _read_lot_status(path: Path) -> pd.DataFrame:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        worksheet = workbook.active
        if worksheet is None:
            raise DatasetLoadError(f"Lot status workbook has no active worksheet: {path}")
        rows = list(worksheet.values)
    finally:
        workbook.close()
    if not rows:
        raise DatasetLoadError(f"Lot status workbook is empty: {path}")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    return pd.DataFrame(rows[1:], columns=headers)


def load_bosch_dataset(
    directory: str | Path, *, limits: IngestionLimits | None = None
) -> BoschDataset:
    source_dir = Path(directory)
    active_limits = limits or IngestionLimits()
    required = require_files(source_dir, BOSCH_REQUIRED)
    optional_pdf = source_dir / "Readme.pdf"
    source_files = required + ((optional_pdf,) if optional_pdf.is_file() else ())
    _validate_source_files(source_files, active_limits)
    primary_reference_path = source_dir.parent / "research" / "Readme.pdf"
    scientific_references: tuple[ScientificReference, ...] = ()
    if primary_reference_path.is_file():
        _validate_source_files((primary_reference_path,), active_limits)
        reference_hash = sha256_file(primary_reference_path)
        scientific_references = (
            ScientificReference(
                reference_id="bosch_experimental_context_readme",
                source_path="research/Readme.pdf",
                sha256=reference_hash,
                role="primary_scientific_reference",
                verified=reference_hash == BOSCH_PRIMARY_REFERENCE_SHA256,
            ),
        )
    provenance = build_provenance(
        "bosch_plasma_etch_2025",
        source_dir,
        source_files,
        ("NetCDF uint16 values decoded through Dictionary_process.nc",),
    )
    issues: list[DataQualityIssue] = []
    runs: list[BoschRunData] = []
    all_features: set[str] = set()
    feature_counts: dict[int, int] = {}
    duplicate_count = 0
    sampling_gap_count = 0
    total_observations = 0
    decoded_cells = 0
    with h5py.File(source_dir / "Dictionary_process.nc", "r") as dictionary_file:
        if "data" not in dictionary_file:
            raise DatasetLoadError("Dictionary_process.nc does not contain required dataset 'data'")
        if dictionary_file["data"].size > active_limits.max_dictionary_entries:
            raise DatasetLoadError("BOSCH dictionary exceeds configured entry safety limit")
        decoder = np.asarray(dictionary_file["data"][:], dtype=np.float64)
    with h5py.File(source_dir / "Process_data.nc", "r") as process_file:
        if not process_file.keys():
            raise DatasetLoadError("Process_data.nc contains no wafer groups")
        if len(process_file) > active_limits.max_bosch_runs:
            raise DatasetLoadError("BOSCH run count exceeds configured safety limit")
        for group_name in sorted(process_file.keys()):
            group = process_file[group_name]
            missing_members = {"data", "feature", "times"} - set(group.keys())
            if missing_members:
                raise DatasetLoadError(
                    f"BOSCH group {group_name} is missing: {', '.join(sorted(missing_members))}"
                )
            data_shape = group["data"].shape
            if len(data_shape) != 2:
                raise DatasetLoadError(f"Invalid BOSCH data rank in group {group_name}")
            run_observations, run_features = data_shape
            if run_observations > active_limits.max_run_observations:
                raise DatasetLoadError(
                    f"BOSCH run observation limit exceeded in group {group_name}"
                )
            if run_features > active_limits.max_features:
                raise DatasetLoadError(f"BOSCH feature limit exceeded in group {group_name}")
            decoded_cells += run_observations * run_features
            if decoded_cells > active_limits.max_decoded_cells:
                raise DatasetLoadError("BOSCH decoded allocation exceeds configured safety limit")
            encoded = np.asarray(group["data"][:])
            features = _decode_strings(np.asarray(group["feature"][:]))
            times = np.asarray(group["times"][:], dtype=np.float64)
            time_units = _decode_attribute(group["times"].attrs.get("units", "")) or None
            time_calendar = _decode_attribute(group["times"].attrs.get("calendar", "")) or None
            if encoded.ndim != 2 or encoded.shape != (len(times), len(features)):
                raise DatasetLoadError(f"Shape mismatch in BOSCH group {group_name}")
            if encoded.size and int(encoded.max()) >= len(decoder):
                raise DatasetLoadError(f"Dictionary index out of range in BOSCH group {group_name}")
            values = pd.DataFrame(decoder[encoded], columns=features)
            encoded_with_time = pd.DataFrame(encoded).assign(_source_time=times)
            duplicate_count += int(encoded_with_time.duplicated().sum())
            total_observations += len(times)
            all_features.update(features)
            feature_counts[len(features)] = feature_counts.get(len(features), 0) + 1
            if len(times) > 1:
                sampling_gap_count += int((np.diff(times) > 0.21).sum())
            if len(times) > 1 and np.any(np.diff(times) < 0):
                issues.append(
                    DataQualityIssue(
                        code="NON_CHRONOLOGICAL_RUN",
                        severity=Severity.ERROR,
                        message="Elapsed times decrease within a BOSCH process run.",
                        source_file="Process_data.nc",
                        record_reference=group_name,
                    )
                )
            experiment_key = _bosch_experiment_key(group_name)
            runs.append(
                BoschRunData(
                    metadata=ProcessRun(
                        run_id=group_name,
                        wafer_id=experiment_key,
                        observation_count=len(times),
                        feature_count=len(features),
                        time_basis="unqualified NetCDF source coordinate",
                        extra={
                            "source_time_units": time_units,
                            "source_time_calendar": time_calendar,
                            "source_time_min": float(times.min()) if len(times) else None,
                            "source_time_max": float(times.max()) if len(times) else None,
                        },
                    ),
                    elapsed_time_s=times,
                    values=values,
                )
            )
    try:
        metrology = pd.read_csv(source_dir / "Si_Oxide_etch_89_points.csv")
    except (OSError, pd.errors.ParserError, UnicodeError) as exc:
        raise DatasetLoadError(f"Cannot parse BOSCH metrology CSV: {exc}") from exc
    missing_columns = set(BOSCH_METROLOGY_COLUMNS) - set(metrology.columns)
    if missing_columns:
        raise DatasetLoadError(
            f"BOSCH metrology CSV missing columns: {', '.join(sorted(missing_columns))}"
        )
    if len(metrology) > active_limits.max_tabular_rows:
        raise DatasetLoadError("BOSCH metrology row count exceeds configured safety limit")
    if len(metrology.columns) > active_limits.max_tabular_columns:
        raise DatasetLoadError("BOSCH metrology column count exceeds configured safety limit")
    lot_status = _read_lot_status(source_dir / "Lot_status.xlsx")
    run_keys = {run.metadata.wafer_id for run in runs if run.metadata.wafer_id}
    metrology_keys = set(metrology["experiment_key"].astype(str))
    unmatched_runs = sorted(run_keys - metrology_keys)
    unmatched_metrology = sorted(metrology_keys - run_keys)
    issues.extend(
        [
            DataQualityIssue(
                code="TIMESTAMP_METADATA_CONFLICT",
                severity=Severity.WARNING,
                message=(
                    "NetCDF declares Unix-epoch seconds, but observed values are short "
                    "elapsed-process "
                    "durations; values are preserved as an unqualified source coordinate."
                ),
                source_file="Process_data.nc",
            ),
            DataQualityIssue(
                code="SENSOR_UNITS_UNAVAILABLE",
                severity=Severity.WARNING,
                message="Process feature units are not stored in the supplied NetCDF files.",
                source_file="Process_data.nc",
            ),
        ]
    )
    if unmatched_runs:
        issues.append(
            DataQualityIssue(
                code="RUNS_WITHOUT_METROLOGY",
                severity=Severity.WARNING,
                message=f"{len(unmatched_runs)} process runs have no matching 89-point metrology.",
                details={"run_keys": unmatched_runs},
            )
        )
    if len(feature_counts) > 1:
        issues.append(
            DataQualityIssue(
                code="INCONSISTENT_SENSOR_COVERAGE",
                severity=Severity.WARNING,
                message="BOSCH runs do not all expose the same number of process features.",
                details={"feature_count_by_run_count": feature_counts},
            )
        )
    if unmatched_metrology:
        issues.append(
            DataQualityIssue(
                code="METROLOGY_WITHOUT_RUN",
                severity=Severity.ERROR,
                message=f"{len(unmatched_metrology)} metrology keys have no process run.",
                details={"experiment_keys": unmatched_metrology},
            )
        )
    numeric = metrology.select_dtypes(include=[np.number])
    missing_values = {str(k): int(v) for k, v in metrology.isna().sum().items() if int(v)}
    validation = ValidationSummary(
        dataset_id=provenance.dataset_id,
        valid=not any(issue.severity == Severity.ERROR for issue in issues),
        record_counts={
            "process_runs": len(runs),
            "sensor_observations": total_observations,
            "metrology_sites": len(metrology),
            "lot_status_rows": len(lot_status),
        },
        duplicate_counts={
            "sensor_value_rows_within_run": duplicate_count,
            "metrology_rows": int(metrology.duplicated().sum()),
        },
        missing_values=missing_values,
        timestamp_ranges={
            "elapsed_time_s": (
                min(float(run.elapsed_time_s.min()) for run in runs),
                max(float(run.elapsed_time_s.max()) for run in runs),
            )
        },
        features=tuple(sorted(all_features | set(numeric.columns))),
        identifier_relationships={
            "process_run_keys": len(run_keys),
            "metrology_experiment_keys": len(metrology_keys),
            "runs_without_metrology": unmatched_runs,
            "metrology_without_runs": unmatched_metrology,
            "feature_count_by_run_count": feature_counts,
            "sampling_gaps_over_0_21_elapsed_seconds": sampling_gap_count,
        },
        issues=tuple(issues),
        unsupported_assumptions=(
            "BOSCH experimental runs are not treated as qualified production baselines.",
            "Sensor engineering units are unknown unless explicitly present in source metadata.",
            "Metrology values are preserved in source scale; ambiguous units are not converted.",
            "Calendar timestamps are not derived from contradictory NetCDF time metadata.",
        ),
    )
    verify_provenance(provenance, source_dir)
    for reference in scientific_references:
        if sha256_file(primary_reference_path) != reference.sha256:
            raise DatasetLoadError("Primary scientific reference changed during ingestion")
    return BoschDataset(
        provenance,
        tuple(runs),
        metrology,
        lot_status,
        validation,
        scientific_references,
    )


def load_phm_dataset(directory: str | Path, *, limits: IngestionLimits | None = None) -> PhmDataset:
    source_dir = Path(directory)
    active_limits = limits or IngestionLimits()
    required = require_files(source_dir, PHM_REQUIRED)
    _validate_source_files(required, active_limits)
    provenance = build_provenance(
        "phm_ion_mill_2018_compact",
        source_dir,
        required,
        ("Fault-centered subset plus deterministic normal sample; not an unbiased benchmark",),
    )
    parquet_metadata = pq.ParquetFile(source_dir / "equipment_sensor_data.parquet").metadata
    if parquet_metadata.num_rows > active_limits.max_tabular_rows:
        raise DatasetLoadError("PHM Parquet row count exceeds configured safety limit")
    if parquet_metadata.num_columns > active_limits.max_tabular_columns:
        raise DatasetLoadError("PHM Parquet column count exceeds configured safety limit")
    try:
        observations = pd.read_parquet(source_dir / "equipment_sensor_data.parquet")
        fault_frame = pd.read_csv(source_dir / "fault_events.csv")
        manifest = json.loads((source_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
        supplied_validation = json.loads(
            (source_dir / "validation_report.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, pd.errors.ParserError, json.JSONDecodeError) as exc:
        raise DatasetLoadError(f"Cannot parse PHM compact dataset: {exc}") from exc
    missing_sensor_columns = set(PHM_ID_COLUMNS) - set(observations.columns)
    missing_fault_columns = set(PHM_FAULT_COLUMNS) - set(fault_frame.columns)
    if missing_sensor_columns or missing_fault_columns:
        raise DatasetLoadError(
            "PHM source schema missing required columns: "
            + ", ".join(sorted(missing_sensor_columns | missing_fault_columns))
        )
    if len(fault_frame) > active_limits.max_tabular_rows:
        raise DatasetLoadError("PHM fault row count exceeds configured safety limit")
    issues: list[DataQualityIssue] = []
    for column in PHM_ID_COLUMNS:
        if observations[column].isna().any():
            issues.append(
                DataQualityIssue(
                    code="MISSING_REQUIRED_VALUE",
                    severity=Severity.ERROR,
                    message=f"Required PHM field {column} contains null values.",
                    source_file="equipment_sensor_data.parquet",
                )
            )
    if not observations["time"].is_monotonic_increasing:
        issues.append(
            DataQualityIssue(
                code="NON_CHRONOLOGICAL_DATASET",
                severity=Severity.ERROR,
                message="PHM observations are not globally ordered by source time.",
            )
        )
    actual_sensor_rows = len(observations)
    actual_fault_rows = len(fault_frame)
    if manifest.get("retained_sensor_rows") != actual_sensor_rows:
        issues.append(
            DataQualityIssue(
                code="MANIFEST_SENSOR_COUNT_MISMATCH",
                severity=Severity.ERROR,
                message=(
                    "Manifest retained sensor count differs from independently loaded "
                    "Parquet count."
                ),
            )
        )
    if manifest.get("retained_fault_rows") != actual_fault_rows:
        issues.append(
            DataQualityIssue(
                code="MANIFEST_FAULT_COUNT_MISMATCH",
                severity=Severity.ERROR,
                message=(
                    "Manifest retained fault count differs from independently loaded CSV count."
                ),
            )
        )
    sensor_tools = set(observations["Tool"].astype(str))
    fault_tools = set(fault_frame["Tool"].astype(str))
    unknown_fault_tools = sorted(fault_tools - sensor_tools)
    if unknown_fault_tools:
        issues.append(
            DataQualityIssue(
                code="FAULT_EQUIPMENT_MISMATCH",
                severity=Severity.ERROR,
                message="Fault records reference equipment absent from sensor observations.",
                details={"equipment_ids": unknown_fault_tools},
            )
        )
    start, end = int(observations["time"].min()), int(observations["time"].max())
    faults_outside_range = int((~fault_frame["time"].between(start, end)).sum())
    if faults_outside_range:
        issues.append(
            DataQualityIssue(
                code="FAULT_OUTSIDE_SENSOR_RANGE",
                severity=Severity.WARNING,
                message=(
                    f"{faults_outside_range} fault events fall outside retained sensor time range."
                ),
            )
        )
    issues.extend(
        [
            DataQualityIssue(
                code="TIME_UNIT_UNDOCUMENTED",
                severity=Severity.WARNING,
                message=(
                    "The compact source does not establish a convertible unit or calendar origin "
                    "for time."
                ),
            ),
            DataQualityIssue(
                code="SENSOR_UNITS_UNAVAILABLE",
                severity=Severity.WARNING,
                message="Sensor fields contain normalized values and no engineering-unit metadata.",
            ),
        ]
    )
    duplicate_rows = int(observations.duplicated().sum())
    if duplicate_rows:
        issues.append(
            DataQualityIssue(
                code="DUPLICATE_SENSOR_ROWS",
                severity=Severity.WARNING,
                message=f"PHM observations contain {duplicate_rows} exact duplicate rows.",
            )
        )
    ordered = observations.sort_values(["Tool", "runnum", "time"])
    within_run_deltas = ordered.groupby(["Tool", "runnum"], sort=False)["time"].diff()
    positive_deltas = within_run_deltas[within_run_deltas > 0]
    median_delta = float(positive_deltas.median()) if not positive_deltas.empty else None
    gap_candidates = (
        int((positive_deltas > median_delta * 10).sum()) if median_delta is not None else 0
    )
    manifest_equipment = manifest.get("selected_equipment_id")
    if isinstance(manifest_equipment, str) and manifest_equipment not in sensor_tools:
        issues.append(
            DataQualityIssue(
                code="EQUIPMENT_ID_FORMAT_VARIANT",
                severity=Severity.WARNING,
                message=(
                    "Manifest and observation equipment identifiers differ in punctuation; "
                    "no silent normalization was applied."
                ),
                details={
                    "manifest_value": manifest_equipment,
                    "observation_values": sorted(sensor_tools),
                },
            )
        )
    fault_times = fault_frame["time"].astype("int64").tolist()
    fault_names = fault_frame["fault_name"].astype(str).tolist()
    fault_equipment = fault_frame["Tool"].astype(str).tolist()
    faults = tuple(
        FaultEvent(event_time=event_time, fault_name=fault_name, equipment_id=equipment_id)
        for event_time, fault_name, equipment_id in zip(
            fault_times, fault_names, fault_equipment, strict=True
        )
    )
    sensor_features = tuple(sorted(set(observations.columns) - set(PHM_ID_COLUMNS)))
    run_fault_coverage = int(fault_frame["time"].isin(observations["time"]).sum())
    validation = ValidationSummary(
        dataset_id=provenance.dataset_id,
        valid=not any(issue.severity == Severity.ERROR for issue in issues),
        record_counts={
            "sensor_observations": actual_sensor_rows,
            "fault_events": actual_fault_rows,
            "equipment": observations["Tool"].nunique(),
            "runs": observations["runnum"].nunique(),
        },
        duplicate_counts={
            "sensor_rows": duplicate_rows,
            "fault_events": int(fault_frame.duplicated().sum()),
        },
        missing_values={str(k): int(v) for k, v in observations.isna().sum().items() if int(v)},
        timestamp_ranges={"source_time": (start, end)},
        features=sensor_features,
        identifier_relationships={
            "sensor_equipment_ids": sorted(sensor_tools),
            "fault_equipment_ids": sorted(fault_tools),
            "faults_inside_sensor_range": actual_fault_rows - faults_outside_range,
            "fault_times_exactly_present_in_sample": run_fault_coverage,
            "manifest_equipment_id": manifest_equipment,
            "median_positive_within_run_time_delta": median_delta,
            "sampling_gap_candidates_over_10x_median": gap_candidates,
        },
        issues=tuple(issues),
        unsupported_assumptions=(
            "Recorded shutdown/fault event times are not treated as exact fault-onset timestamps.",
            "Fault-centered samples are not treated as an unbiased prediction benchmark.",
            "Normalized sensor values are not assigned inferred engineering units.",
            "PHM ion-mill observations are not pooled with BOSCH plasma-etch observations.",
        ),
    )
    verify_provenance(provenance, source_dir)
    return PhmDataset(provenance, observations, faults, manifest, supplied_validation, validation)
