"""Source-specific, read-only loaders for BOSCH and PHM datasets."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from io import BufferedReader
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
    open_regular_file,
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

    max_file_size_bytes: int = 64 * 1024 * 1024
    max_archive_uncompressed_bytes: int = 256 * 1024 * 1024
    max_archive_members: int = 10_000
    max_bosch_runs: int = 10_000
    max_run_observations: int = 5_000_000
    max_features: int = 10_000
    max_dictionary_entries: int = 10_000_000
    max_decoded_cells: int = 25_000_000
    max_tabular_rows: int = 10_000_000
    max_tabular_columns: int = 10_000
    max_tabular_memory_bytes: int = 512 * 1024 * 1024
    max_metrology_rows: int = 1_000_000
    max_fault_events: int = 100_000
    max_workbook_rows: int = 100_000
    max_workbook_columns: int = 1_000
    max_decoded_bytes: int = 256 * 1024 * 1024
    max_feature_text_bytes: int = 4 * 1024 * 1024
    max_delimited_record_bytes: int = 1024 * 1024


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
    content_sha256: str = ""


@dataclass(frozen=True)
class PhmDataset:
    provenance: DatasetProvenance
    observations: pd.DataFrame
    faults: tuple[FaultEvent, ...]
    manifest: dict[str, Any]
    supplied_validation: dict[str, Any]
    validation: ValidationSummary
    content_sha256: str = ""


def _update_json_hash(digest: Any, value: Any) -> None:
    digest.update(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    )


def _update_frame_hash(digest: Any, frame: pd.DataFrame) -> None:
    _update_json_hash(
        digest,
        {
            "columns": [str(column) for column in frame.columns],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "shape": frame.shape,
        },
    )
    digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())


def _dataset_content_sha256(dataset: BoschDataset | PhmDataset) -> str:
    """Seal the exact in-memory content consumed by qualification and analytics."""
    digest = hashlib.sha256()
    _update_json_hash(digest, dataset.provenance.model_dump(mode="json"))
    if isinstance(dataset, BoschDataset):
        for run in dataset.runs:
            _update_json_hash(digest, run.metadata.model_dump(mode="json"))
            coordinates = np.asarray(run.elapsed_time_s, dtype=np.float64)
            _update_json_hash(digest, {"shape": coordinates.shape, "dtype": str(coordinates.dtype)})
            digest.update(coordinates.tobytes())
            _update_frame_hash(digest, run.values)
        _update_frame_hash(digest, dataset.metrology)
        _update_frame_hash(digest, dataset.lot_status)
        _update_json_hash(
            digest,
            [item.model_dump(mode="json") for item in dataset.scientific_references],
        )
    else:
        _update_frame_hash(digest, dataset.observations)
        _update_json_hash(digest, [item.model_dump(mode="json") for item in dataset.faults])
        _update_json_hash(digest, dataset.manifest)
        _update_json_hash(digest, dataset.supplied_validation)
    _update_json_hash(digest, dataset.validation.model_dump(mode="json"))
    return digest.hexdigest()


def _decode_bounded_hdf5_strings(dataset: h5py.Dataset, max_bytes: int) -> list[str]:
    decoded: list[str] = []
    total_bytes = 0
    for index in range(dataset.size):
        value = dataset[index]
        text = value.decode("utf-8") if isinstance(value, bytes) else str(value)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > max_bytes:
            raise DatasetLoadError("HDF5 string content exceeds configured safety limit")
        decoded.append(text)
    return decoded


def _decode_attribute(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _validate_source_files(files: tuple[Path, ...], limits: IngestionLimits) -> None:
    for path in files:
        if path.is_symlink():
            raise DatasetLoadError(f"Source files must not be symlinks: {path.name}")
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


def _hash_open_handle(handle: BufferedReader) -> str:
    digest = hashlib.sha256()
    handle.seek(0)
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


@contextmanager
def _open_verified_source(path: Path, expected_sha256: str) -> Iterator[BufferedReader]:
    with open_regular_file(path) as handle:
        if _hash_open_handle(handle) != expected_sha256:
            raise DatasetLoadError(f"Source changed before parsing: {path.name}")
        yield handle
        if _hash_open_handle(handle) != expected_sha256:
            raise DatasetLoadError(f"Source changed during parsing: {path.name}")


def _read_bounded_csv(
    path: Path,
    expected_sha256: str,
    limits: IngestionLimits,
    max_rows: int,
) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    row_count = 0
    decoded_memory = 0
    with _open_verified_source(path, expected_sha256) as handle:
        current_record_bytes = 0
        for physical_chunk in iter(lambda: handle.read(64 * 1024), b""):
            for byte in physical_chunk:
                if byte in (10, 13):
                    current_record_bytes = 0
                else:
                    current_record_bytes += 1
                    if current_record_bytes > limits.max_delimited_record_bytes:
                        raise DatasetLoadError(
                            f"Delimited source record exceeds configured safety limit: {path.name}"
                        )
        handle.seek(0)
        header = pd.read_csv(handle, nrows=0)
        if len(header.columns) > limits.max_tabular_columns:
            raise DatasetLoadError(f"Delimited source column limit exceeded: {path.name}")
        handle.seek(0)
        for frame_chunk in pd.read_csv(handle, chunksize=10_000):
            row_count += len(frame_chunk)
            if row_count > max_rows:
                raise DatasetLoadError(
                    f"Delimited source row count exceeds configured safety limit: {path.name}"
                )
            if row_count * len(header.columns) > limits.max_decoded_cells:
                raise DatasetLoadError(
                    f"Delimited source cell count exceeds configured safety limit: {path.name}"
                )
            decoded_memory += int(frame_chunk.memory_usage(index=True, deep=True).sum())
            if decoded_memory > limits.max_tabular_memory_bytes // 2:
                raise DatasetLoadError(
                    f"Delimited source memory exceeds configured safety limit: {path.name}"
                )
            chunks.append(frame_chunk)
    if not chunks:
        return header
    return pd.concat(chunks, ignore_index=True)


def _bosch_experiment_key(group_name: str) -> str | None:
    match = _BOSCH_GROUP.fullmatch(group_name)
    if match is None:
        return None
    year, month, day, wafer = match.groups()
    return f"{year}-{month}-{day}_{int(wafer):02d}"


def _read_lot_status(path: Path, expected_sha256: str, limits: IngestionLimits) -> pd.DataFrame:
    with _open_verified_source(path, expected_sha256) as source_handle:
        workbook = load_workbook(source_handle, read_only=True, data_only=True)
        try:
            worksheet = workbook.active
            if worksheet is None:
                raise DatasetLoadError(f"Lot status workbook has no active worksheet: {path}")
            if worksheet.max_row > limits.max_workbook_rows:
                raise DatasetLoadError(f"Lot status workbook row limit exceeded: {path}")
            if worksheet.max_column > limits.max_workbook_columns:
                raise DatasetLoadError(f"Lot status workbook column limit exceeded: {path}")
            if worksheet.max_row * worksheet.max_column > limits.max_decoded_cells:
                raise DatasetLoadError(f"Lot status workbook cell limit exceeded: {path}")
            rows = list(worksheet.values)
        finally:
            workbook.close()
    if not rows:
        raise DatasetLoadError(f"Lot status workbook is empty: {path}")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    return pd.DataFrame(rows[1:], columns=headers)


def _require_internal_hdf5_dataset(dataset: object, label: str) -> None:
    if not isinstance(dataset, h5py.Dataset):
        raise DatasetLoadError(f"HDF5 member is not a dataset: {label}")
    if dataset.is_virtual or dataset.external:
        raise DatasetLoadError(f"HDF5 dataset uses external storage: {label}")


def _require_hdf5_allocation(
    dataset: h5py.Dataset,
    label: str,
    limits: IngestionLimits,
    *,
    kind: str,
) -> None:
    dtype = dataset.dtype
    if kind == "integer" and not np.issubdtype(dtype, np.integer):
        raise DatasetLoadError(f"HDF5 dataset must use an integer dtype: {label}")
    if kind == "numeric" and not (
        np.issubdtype(dtype, np.integer) or np.issubdtype(dtype, np.floating)
    ):
        raise DatasetLoadError(f"HDF5 dataset must use a real numeric dtype: {label}")
    if kind == "string" and h5py.check_string_dtype(dtype) is None:
        raise DatasetLoadError(f"HDF5 dataset must use a string dtype: {label}")
    decoded_bytes = dataset.size * dtype.itemsize
    if decoded_bytes > limits.max_decoded_bytes:
        raise DatasetLoadError(f"HDF5 decoded bytes exceed configured safety limit: {label}")


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
        if primary_reference_path.is_symlink():
            raise DatasetLoadError("Primary scientific reference must not be a symlink")
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
    with (
        _open_verified_source(
            source_dir / "Dictionary_process.nc",
            provenance.sha256["Dictionary_process.nc"],
        ) as source_handle,
        h5py.File(source_handle, "r") as dictionary_file,
    ):
        if not isinstance(dictionary_file.get("data", getlink=True), h5py.HardLink):
            raise DatasetLoadError("BOSCH dictionary data must be an internal hard link")
        if "data" not in dictionary_file:
            raise DatasetLoadError("Dictionary_process.nc does not contain required dataset 'data'")
        _require_internal_hdf5_dataset(dictionary_file["data"], "Dictionary_process.nc/data")
        _require_hdf5_allocation(
            dictionary_file["data"],
            "Dictionary_process.nc/data",
            active_limits,
            kind="numeric",
        )
        if dictionary_file["data"].size > active_limits.max_dictionary_entries:
            raise DatasetLoadError("BOSCH dictionary exceeds configured entry safety limit")
        decoder = np.asarray(dictionary_file["data"][:], dtype=np.float64)
    with (
        _open_verified_source(
            source_dir / "Process_data.nc", provenance.sha256["Process_data.nc"]
        ) as source_handle,
        h5py.File(source_handle, "r") as process_file,
    ):
        if not process_file.keys():
            raise DatasetLoadError("Process_data.nc contains no wafer groups")
        if len(process_file) > active_limits.max_bosch_runs:
            raise DatasetLoadError("BOSCH run count exceeds configured safety limit")
        for group_name in sorted(process_file.keys()):
            if not isinstance(process_file.get(group_name, getlink=True), h5py.HardLink):
                raise DatasetLoadError(f"BOSCH group must be an internal hard link: {group_name}")
            group = process_file[group_name]
            if not isinstance(group, h5py.Group):
                raise DatasetLoadError(f"BOSCH run member is not a group: {group_name}")
            missing_members = {"data", "feature", "times"} - set(group.keys())
            if missing_members:
                raise DatasetLoadError(
                    f"BOSCH group {group_name} is missing: {', '.join(sorted(missing_members))}"
                )
            for member_name in ("data", "feature", "times"):
                if not isinstance(group.get(member_name, getlink=True), h5py.HardLink):
                    raise DatasetLoadError(
                        f"BOSCH member must be an internal hard link: {group_name}/{member_name}"
                    )
                _require_internal_hdf5_dataset(group[member_name], f"{group_name}/{member_name}")
            _require_hdf5_allocation(
                group["data"], f"{group_name}/data", active_limits, kind="integer"
            )
            _require_hdf5_allocation(
                group["feature"], f"{group_name}/feature", active_limits, kind="string"
            )
            _require_hdf5_allocation(
                group["times"], f"{group_name}/times", active_limits, kind="numeric"
            )
            data_shape = group["data"].shape
            if len(data_shape) != 2:
                raise DatasetLoadError(f"Invalid BOSCH data rank in group {group_name}")
            run_observations, run_features = data_shape
            feature_shape = group["feature"].shape
            time_shape = group["times"].shape
            if feature_shape != (run_features,) or time_shape != (run_observations,):
                raise DatasetLoadError(f"Shape mismatch in BOSCH group {group_name}")
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
            if encoded.size and int(encoded.min()) < 0:
                raise DatasetLoadError(f"Negative dictionary index in BOSCH group {group_name}")
            features = _decode_bounded_hdf5_strings(
                group["feature"], active_limits.max_feature_text_bytes
            )
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
        metrology = _read_bounded_csv(
            source_dir / "Si_Oxide_etch_89_points.csv",
            provenance.sha256["Si_Oxide_etch_89_points.csv"],
            active_limits,
            active_limits.max_metrology_rows,
        )
    except (OSError, pd.errors.ParserError, UnicodeError) as exc:
        raise DatasetLoadError(f"Cannot parse BOSCH metrology CSV: {exc}") from exc
    missing_columns = set(BOSCH_METROLOGY_COLUMNS) - set(metrology.columns)
    if missing_columns:
        raise DatasetLoadError(
            f"BOSCH metrology CSV missing columns: {', '.join(sorted(missing_columns))}"
        )
    if len(metrology) > active_limits.max_metrology_rows:
        raise DatasetLoadError("BOSCH metrology row count exceeds configured safety limit")
    if len(metrology.columns) > active_limits.max_tabular_columns:
        raise DatasetLoadError("BOSCH metrology column count exceeds configured safety limit")
    if len(metrology) * len(metrology.columns) > active_limits.max_decoded_cells:
        raise DatasetLoadError("BOSCH metrology cell count exceeds configured safety limit")
    if (
        int(metrology.memory_usage(index=True, deep=True).sum())
        > active_limits.max_tabular_memory_bytes
    ):
        raise DatasetLoadError("BOSCH metrology exceeds configured in-memory safety limit")
    lot_status = _read_lot_status(
        source_dir / "Lot_status.xlsx",
        provenance.sha256["Lot_status.xlsx"],
        active_limits,
    )
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
    dataset = BoschDataset(
        provenance,
        tuple(runs),
        metrology,
        lot_status,
        validation,
        scientific_references,
    )
    return replace(dataset, content_sha256=_dataset_content_sha256(dataset))


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
    with _open_verified_source(
        source_dir / "equipment_sensor_data.parquet",
        provenance.sha256["equipment_sensor_data.parquet"],
    ) as source_handle:
        parquet_metadata = pq.ParquetFile(source_handle).metadata
    if parquet_metadata.num_rows > active_limits.max_tabular_rows:
        raise DatasetLoadError("PHM Parquet row count exceeds configured safety limit")
    if parquet_metadata.num_columns > active_limits.max_tabular_columns:
        raise DatasetLoadError("PHM Parquet column count exceeds configured safety limit")
    parquet_cells = parquet_metadata.num_rows * parquet_metadata.num_columns
    if parquet_cells > active_limits.max_decoded_cells:
        raise DatasetLoadError("PHM Parquet decoded cell count exceeds configured safety limit")
    uncompressed_bytes = sum(
        parquet_metadata.row_group(row_group).column(column).total_uncompressed_size
        for row_group in range(parquet_metadata.num_row_groups)
        for column in range(parquet_metadata.num_columns)
    )
    if uncompressed_bytes > active_limits.max_tabular_memory_bytes:
        raise DatasetLoadError("PHM Parquet decoded bytes exceed configured safety limit")
    try:
        with _open_verified_source(
            source_dir / "equipment_sensor_data.parquet",
            provenance.sha256["equipment_sensor_data.parquet"],
        ) as source_handle:
            observations = pd.read_parquet(source_handle)
        fault_frame = _read_bounded_csv(
            source_dir / "fault_events.csv",
            provenance.sha256["fault_events.csv"],
            active_limits,
            active_limits.max_fault_events,
        )
        with _open_verified_source(
            source_dir / "dataset_manifest.json",
            provenance.sha256["dataset_manifest.json"],
        ) as source_handle:
            manifest = json.load(source_handle)
        with _open_verified_source(
            source_dir / "validation_report.json",
            provenance.sha256["validation_report.json"],
        ) as source_handle:
            supplied_validation = json.load(source_handle)
    except (OSError, ValueError, pd.errors.ParserError, json.JSONDecodeError) as exc:
        raise DatasetLoadError(f"Cannot parse PHM compact dataset: {exc}") from exc
    if (
        int(observations.memory_usage(index=True, deep=True).sum())
        > active_limits.max_tabular_memory_bytes
    ):
        raise DatasetLoadError("PHM observations exceed configured in-memory safety limit")
    missing_sensor_columns = set(PHM_ID_COLUMNS) - set(observations.columns)
    missing_fault_columns = set(PHM_FAULT_COLUMNS) - set(fault_frame.columns)
    if missing_sensor_columns or missing_fault_columns:
        raise DatasetLoadError(
            "PHM source schema missing required columns: "
            + ", ".join(sorted(missing_sensor_columns | missing_fault_columns))
        )
    if len(fault_frame) > active_limits.max_fault_events:
        raise DatasetLoadError("PHM fault row count exceeds configured safety limit")
    if len(fault_frame.columns) > active_limits.max_tabular_columns:
        raise DatasetLoadError("PHM fault column count exceeds configured safety limit")
    if len(fault_frame) * len(fault_frame.columns) > active_limits.max_decoded_cells:
        raise DatasetLoadError("PHM fault cell count exceeds configured safety limit")
    if (
        int(fault_frame.memory_usage(index=True, deep=True).sum())
        > active_limits.max_tabular_memory_bytes
    ):
        raise DatasetLoadError("PHM faults exceed configured in-memory safety limit")
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
    sensor_tools = set(observations["Tool"].dropna().astype(str))
    fault_tools = set(fault_frame["Tool"].dropna().astype(str))
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
    for column in PHM_FAULT_COLUMNS:
        missing_fault_values = int(fault_frame[column].isna().sum())
        if missing_fault_values:
            issues.append(
                DataQualityIssue(
                    code="MISSING_FAULT_EVENT_FIELD",
                    severity=Severity.WARNING,
                    message=(
                        f"PHM fault field {column} is missing in "
                        f"{missing_fault_values} event records."
                    ),
                    source_file="fault_events.csv",
                )
            )
    start, end = int(observations["time"].min()), int(observations["time"].max())
    present_fault_coordinates = fault_frame["time"].dropna()
    faults_outside_range = int((~present_fault_coordinates.between(start, end)).sum())
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
    fault_times = [None if pd.isna(value) else int(value) for value in fault_frame["time"]]
    fault_names = [None if pd.isna(value) else str(value) for value in fault_frame["fault_name"]]
    fault_equipment = [None if pd.isna(value) else str(value) for value in fault_frame["Tool"]]
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
    dataset = PhmDataset(
        provenance, observations, faults, manifest, supplied_validation, validation
    )
    return replace(dataset, content_sha256=_dataset_content_sha256(dataset))
