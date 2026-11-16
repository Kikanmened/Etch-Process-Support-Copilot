"""Bounded loading and scientific validation for synthetic demo datasets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import ValidationError

from etch_copilot.models import DatasetLoadError, DatasetProvenance
from etch_copilot.provenance import open_regular_file, require_files
from etch_copilot.synthetic.contracts import (
    MAINTENANCE_COLUMNS,
    MAX_METROLOGY_ROWS,
    MAX_RUNS,
    MAX_SOURCE_BYTES,
    MAX_TELEMETRY_ROWS,
    METROLOGY_COLUMNS,
    RUN_COLUMNS,
    SOURCE_FILENAMES,
    SYNTHETIC_GENERATOR_VERSION,
    SYNTHETIC_SCHEMA_VERSION,
    TELEMETRY_COLUMNS,
    VISIBLE_FILENAMES,
    ScenarioId,
    SyntheticManifest,
    SyntheticValidationIssue,
    SyntheticValidationSummary,
    synthetic_dataset_id,
)

_SITES = {"CENTER", "NORTH", "EAST", "SOUTH", "WEST"}
_SITE_COORDINATES = {
    "CENTER": (0.0, 0.0),
    "NORTH": (0.0, 0.8),
    "EAST": (0.8, 0.0),
    "SOUTH": (0.0, -0.8),
    "WEST": (-0.8, 0.0),
}


@dataclass(frozen=True)
class SyntheticDataset:
    runs: pd.DataFrame
    telemetry: pd.DataFrame
    metrology: pd.DataFrame
    maintenance: pd.DataFrame
    manifest: SyntheticManifest
    provenance: DatasetProvenance
    validation: SyntheticValidationSummary
    content_sha256: str = ""


def _load_manifest(path: Path) -> tuple[SyntheticManifest, str]:
    try:
        content = _read_bounded(path)
        payload: Any = json.loads(content.decode("utf-8"))
        return SyntheticManifest.model_validate(payload), sha256(content).hexdigest()
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise DatasetLoadError(f"Invalid synthetic dataset manifest: {path}") from exc


def _validate_manifest_filenames(manifest: SyntheticManifest) -> None:
    for filename in manifest.files:
        if (
            not filename
            or filename != Path(filename).name
            or "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
        ):
            raise DatasetLoadError(f"unsafe manifest filename: {filename}")
    if set(manifest.files) != set(SOURCE_FILENAMES):
        raise DatasetLoadError("Manifest source-file set does not match the synthetic contract")
    if manifest.schema_version != SYNTHETIC_SCHEMA_VERSION:
        raise DatasetLoadError(f"Unsupported synthetic schema version: {manifest.schema_version}")
    if manifest.generator_version != SYNTHETIC_GENERATOR_VERSION:
        raise DatasetLoadError(
            f"Unsupported synthetic generator version: {manifest.generator_version}"
        )
    if manifest.scenarios != tuple(ScenarioId):
        raise DatasetLoadError("Manifest scenario membership must be exactly S1, S2, S3")
    expected_dataset_id = synthetic_dataset_id(
        seed=manifest.seed,
        schema_version=manifest.schema_version,
        generator_version=manifest.generator_version,
        baseline_runs_per_scenario=manifest.baseline_runs_per_scenario,
        incident_runs_per_scenario=manifest.incident_runs_per_scenario,
        telemetry_interval_s=manifest.telemetry_interval_s,
        etch_duration_s=manifest.etch_duration_s,
    )
    if manifest.dataset_id != expected_dataset_id:
        raise DatasetLoadError("Manifest dataset identity does not match its seed")


def _read_bounded(path: Path) -> bytes:
    with open_regular_file(path) as handle:
        content = handle.read(MAX_SOURCE_BYTES + 1)
    if len(content) > MAX_SOURCE_BYTES:
        raise DatasetLoadError(f"Source file exceeds size limit: {path.name}")
    return content


def _read_csv(
    path: Path,
    expected_columns: tuple[str, ...],
    max_rows: int,
    expected_sha256: str,
) -> pd.DataFrame:
    try:
        content = _read_bounded(path)
        if sha256(content).hexdigest() != expected_sha256:
            raise DatasetLoadError(f"Synthetic provenance hash mismatch: {path.name}")
        frame = pd.read_csv(BytesIO(content), nrows=max_rows + 1)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise DatasetLoadError(f"Cannot parse synthetic source: {path.name}") from exc
    if tuple(frame.columns) != expected_columns:
        raise DatasetLoadError(f"Unexpected columns in {path.name}")
    if len(frame) > max_rows:
        raise DatasetLoadError(f"Source row count exceeds limit: {path.name}")
    return frame


def _require_values(frame: pd.DataFrame, columns: tuple[str, ...], source: str) -> None:
    for column in columns:
        values = frame[column]
        if values.isna().any() or values.astype(str).str.strip().eq("").any():
            raise DatasetLoadError(f"missing required value in {source}.{column}")


def _parse_utc(frame: pd.DataFrame, column: str, source: str) -> None:
    parsed = pd.to_datetime(frame[column], utc=True, errors="coerce")
    if parsed.isna().any():
        raise DatasetLoadError(f"invalid UTC timestamp in {source}.{column}")
    frame[column] = parsed


def _numeric_column(
    frame: pd.DataFrame,
    column: str,
    source: str,
    *,
    allow_missing: bool = False,
) -> pd.Series:
    original = frame[column]
    numeric = pd.to_numeric(original, errors="coerce")
    invalid = numeric.isna() & original.notna()
    if invalid.any():
        raise DatasetLoadError(f"non-numeric {source} value in {column}")
    if not allow_missing and numeric.isna().any():
        raise DatasetLoadError(f"missing required value in {source}.{column}")
    finite = numeric.dropna().to_numpy(dtype=np.float64)
    if not np.isfinite(finite).all():
        raise DatasetLoadError(f"non-finite {source} value in {column}")
    return numeric


def _validate_structure(
    runs: pd.DataFrame,
    telemetry: pd.DataFrame,
    metrology: pd.DataFrame,
    maintenance: pd.DataFrame,
    manifest: SyntheticManifest,
) -> None:
    _require_values(
        runs,
        (
            "scenario_id",
            "run_id",
            "wafer_id",
            "chamber_id",
            "recipe_id",
            "start_ts_utc",
            "end_ts_utc",
            "etch_duration_s",
            "lot_id",
            "phase",
        ),
        "runs",
    )
    _require_values(
        telemetry,
        ("scenario_id", "run_id", "timestamp_utc", "pressure_mTorr", "rf_forward_W"),
        "telemetry",
    )
    _require_values(
        metrology,
        (
            "scenario_id",
            "run_id",
            "site_id",
            "pre_thickness_nm",
            "post_thickness_nm",
            "thickness_unit",
            "measurement_method",
            "measurement_status",
        ),
        "metrology",
    )
    _require_values(
        maintenance,
        ("event_id", "scenario_id", "chamber_id", "timestamp_utc", "event_type"),
        "maintenance",
    )
    _parse_utc(runs, "start_ts_utc", "runs")
    _parse_utc(runs, "end_ts_utc", "runs")
    _parse_utc(telemetry, "timestamp_utc", "telemetry")
    _parse_utc(maintenance, "timestamp_utc", "maintenance")
    if runs["run_id"].duplicated().any():
        raise DatasetLoadError("duplicate run identifier")
    if runs["wafer_id"].duplicated().any():
        raise DatasetLoadError("duplicate wafer identifier")
    if telemetry.duplicated(["run_id", "timestamp_utc"]).any():
        raise DatasetLoadError("duplicate telemetry run/timestamp")
    if metrology.duplicated(["run_id", "site_id"]).any():
        raise DatasetLoadError("duplicate metrology run/site")
    scenario_values = {item.value for item in ScenarioId}
    for source, frame in (("runs", runs), ("telemetry", telemetry), ("metrology", metrology)):
        if not set(frame["scenario_id"].astype(str)).issubset(scenario_values):
            raise DatasetLoadError(f"unknown scenario in {source}")
    if set(runs["phase"].astype(str)) - {"baseline", "incident"}:
        raise DatasetLoadError("unknown run phase")
    for _, run in runs.iterrows():
        scenario = str(run["scenario_id"])
        run_id = str(run["run_id"])
        wafer_id = str(run["wafer_id"])
        if re.fullmatch(rf"{scenario}-R\d{{3}}", run_id) is None:
            raise DatasetLoadError(f"invalid run identifier: {run_id}")
        if re.fullmatch(rf"{scenario}-W\d{{3}}", wafer_id) is None:
            raise DatasetLoadError(f"invalid wafer identifier: {wafer_id}")
        if str(run["chamber_id"]) != f"SYN-CHAMBER-{scenario}":
            raise DatasetLoadError("scenario/chamber identifier mismatch")
        if str(run["recipe_id"]) != "SYN-OXIDE-ETCH-V1":
            raise DatasetLoadError("unsupported synthetic recipe identifier")
    run_ids = set(runs["run_id"].astype(str))
    telemetry_run_ids = set(telemetry["run_id"].astype(str))
    metrology_run_ids = set(metrology["run_id"].astype(str))
    if telemetry_run_ids != run_ids:
        raise DatasetLoadError("telemetry does not cover every run")
    if metrology_run_ids != run_ids:
        raise DatasetLoadError("metrology does not cover every run")
    duration = _numeric_column(runs, "etch_duration_s", "run")
    _numeric_column(runs, "etch_duration_standard_uncertainty_s", "run")
    observed_duration = (runs["end_ts_utc"] - runs["start_ts_utc"]).dt.total_seconds()
    if duration.isna().any() or (duration <= 0).any():
        raise DatasetLoadError("invalid etch duration")
    if not observed_duration.eq(duration).all():
        raise DatasetLoadError("run duration does not match UTC timestamps")
    if not duration.eq(manifest.etch_duration_s).all():
        raise DatasetLoadError("run duration differs from manifest")
    run_scope = runs.loc[:, ["run_id", "scenario_id", "start_ts_utc", "end_ts_utc"]]
    joined = telemetry.merge(run_scope, on="run_id", how="left", suffixes=("", "_run"))
    if not joined["scenario_id"].astype(str).eq(joined["scenario_id_run"].astype(str)).all():
        raise DatasetLoadError("scenario/run mismatch in telemetry")
    if (
        (joined["timestamp_utc"] < joined["start_ts_utc"])
        | (joined["timestamp_utc"] > joined["end_ts_utc"])
    ).any():
        raise DatasetLoadError("telemetry timestamp outside run interval")
    for _, group in telemetry.groupby("run_id", sort=False):
        if not group["timestamp_utc"].is_monotonic_increasing:
            raise DatasetLoadError("telemetry timestamps are not monotonic within run")
        intervals = group["timestamp_utc"].diff().dropna().dt.total_seconds()
        if not intervals.eq(manifest.telemetry_interval_s).all():
            raise DatasetLoadError("telemetry interval differs from manifest")
    nonnegative = (
        "pressure_mTorr",
        "rf_forward_W",
        "rf_reflected_W",
        "gas1_flow_sccm",
        "gas2_flow_sccm",
    )
    for column in nonnegative:
        numeric = _numeric_column(
            telemetry,
            column,
            "telemetry",
            allow_missing=column in {"gas1_flow_sccm", "gas2_flow_sccm"},
        )
        if (numeric.dropna() < 0).any():
            raise DatasetLoadError(f"negative telemetry value in {column}")
    _numeric_column(telemetry, "chamber_temp_C", "telemetry", allow_missing=True)
    if (_numeric_column(telemetry, "rf_forward_W", "telemetry") <= 0).any():
        raise DatasetLoadError("RF forward power must be positive")
    if set(metrology["site_id"].astype(str)) - _SITES:
        raise DatasetLoadError("unknown metrology site")
    if not metrology.groupby("run_id")["site_id"].nunique().eq(5).all():
        raise DatasetLoadError("each run must contain five unique metrology sites")
    for site_id, (expected_x, expected_y) in _SITE_COORDINATES.items():
        selected = metrology.loc[metrology["site_id"] == site_id]
        actual_x = pd.to_numeric(selected["site_x_normalized"], errors="coerce")
        actual_y = pd.to_numeric(selected["site_y_normalized"], errors="coerce")
        if not actual_x.eq(expected_x).all() or not actual_y.eq(expected_y).all():
            raise DatasetLoadError(f"invalid fixed site coordinates for {site_id}")
    uncertainties = (
        "pre_standard_uncertainty_nm",
        "post_standard_uncertainty_nm",
    )
    pre_thickness = _numeric_column(metrology, "pre_thickness_nm", "metrology")
    post_thickness = _numeric_column(metrology, "post_thickness_nm", "metrology")
    if (pre_thickness < 0).any() or (post_thickness < 0).any():
        raise DatasetLoadError("negative thickness is not permitted")
    if not metrology["measurement_method"].astype(str).eq("synthetic_ex_situ_thickness").all():
        raise DatasetLoadError("unsupported measurement method")
    if (
        not metrology["calibration_reference"]
        .astype(str)
        .eq("SYNTHETIC-CALIBRATION-CONTEXT-ONLY")
        .all()
    ):
        raise DatasetLoadError("unsupported synthetic calibration reference")
    _numeric_column(metrology, "site_x_normalized", "metrology")
    _numeric_column(metrology, "site_y_normalized", "metrology")
    for column in uncertainties:
        numeric = _numeric_column(metrology, column, "metrology")
        if (numeric < 0).any():
            raise DatasetLoadError(f"invalid measurement uncertainty in {column}")
    duration_uncertainty = _numeric_column(runs, "etch_duration_standard_uncertainty_s", "run")
    if (duration_uncertainty < 0).any():
        raise DatasetLoadError("invalid duration uncertainty")
    metrology_scope = metrology.merge(
        runs.loc[:, ["run_id", "scenario_id"]],
        on="run_id",
        how="left",
        suffixes=("", "_run"),
    )
    if (
        not metrology_scope["scenario_id"]
        .astype(str)
        .eq(metrology_scope["scenario_id_run"].astype(str))
        .all()
    ):
        raise DatasetLoadError("scenario/run mismatch in metrology")
    baseline = runs.loc[runs["phase"] == "baseline"].groupby("scenario_id").size()
    incident = runs.loc[runs["phase"] == "incident"].groupby("scenario_id").size()
    if any(
        int(baseline.get(scenario.value, 0)) != manifest.baseline_runs_per_scenario
        for scenario in ScenarioId
    ):
        raise DatasetLoadError("baseline run counts differ from manifest")
    if any(
        int(incident.get(scenario.value, 0)) != manifest.incident_runs_per_scenario
        for scenario in ScenarioId
    ):
        raise DatasetLoadError("incident run counts differ from manifest")
    expected_samples = manifest.etch_duration_s // manifest.telemetry_interval_s + 1
    if not telemetry.groupby("run_id").size().eq(expected_samples).all():
        raise DatasetLoadError("telemetry sample count differs from manifest")
    sample_bounds = telemetry.groupby("run_id")["timestamp_utc"].agg(["min", "max"])
    run_bounds = runs.set_index("run_id")[["start_ts_utc", "end_ts_utc"]]
    if (
        not sample_bounds["min"].eq(run_bounds["start_ts_utc"]).all()
        or not sample_bounds["max"].eq(run_bounds["end_ts_utc"]).all()
    ):
        raise DatasetLoadError("telemetry does not include declared run endpoints")
    maintenance_ids = set(maintenance["event_id"].astype(str))
    if maintenance["event_id"].duplicated().any():
        raise DatasetLoadError("duplicate maintenance event identifier")
    if not set(maintenance["scenario_id"].astype(str)).issubset(scenario_values):
        raise DatasetLoadError("unknown scenario in maintenance")
    if maintenance_ids != {"M-S1-001"} or len(maintenance) != 1:
        raise DatasetLoadError("canonical S1 maintenance event is required")
    canonical_event = maintenance.loc[maintenance["event_id"] == "M-S1-001"].iloc[0]
    if (
        str(canonical_event["scenario_id"]) != "S1"
        or str(canonical_event["chamber_id"]) != "SYN-CHAMBER-S1"
        or str(canonical_event["event_type"]) != "synthetic_chamber_maintenance"
    ):
        raise DatasetLoadError("canonical S1 maintenance event scope is invalid")
    s1_incident = runs.loc[(runs["scenario_id"] == "S1") & (runs["phase"] == "incident")]
    if not s1_incident["maintenance_event_id"].astype(str).eq("M-S1-001").all():
        raise DatasetLoadError("every S1 incident run must reference canonical maintenance")
    non_s1_events = runs.loc[runs["scenario_id"] != "S1", "maintenance_event_id"]
    if non_s1_events.dropna().astype(str).str.strip().ne("").any():
        raise DatasetLoadError("only S1 incident runs may reference maintenance")
    s1_baseline_end = runs.loc[
        (runs["scenario_id"] == "S1") & (runs["phase"] == "baseline"), "end_ts_utc"
    ].max()
    first_incident_start = s1_incident["start_ts_utc"].min()
    event_timestamp = canonical_event["timestamp_utc"]
    if not (s1_baseline_end <= event_timestamp < first_incident_start):
        raise DatasetLoadError("canonical S1 maintenance event must separate baseline and incident")
    run_events = runs["maintenance_event_id"].dropna().astype(str)
    run_events = run_events.loc[run_events.str.strip().ne("")]
    if not set(run_events).issubset(maintenance_ids):
        raise DatasetLoadError("run references unknown maintenance event")
    maintenance_scope = maintenance.set_index("event_id")[
        [
            "scenario_id",
            "chamber_id",
            "timestamp_utc",
        ]
    ]
    for _, run in runs.loc[runs["maintenance_event_id"].notna()].iterrows():
        event_id = str(run["maintenance_event_id"])
        if not event_id.strip():
            continue
        event = maintenance_scope.loc[event_id]
        if str(event["scenario_id"]) != str(run["scenario_id"]) or str(event["chamber_id"]) != str(
            run["chamber_id"]
        ):
            raise DatasetLoadError("maintenance event scope does not match run")
        if event["timestamp_utc"] > run["start_ts_utc"]:
            raise DatasetLoadError("maintenance event occurs after linked run start")


def _scientific_issues(
    runs: pd.DataFrame, metrology: pd.DataFrame
) -> list[SyntheticValidationIssue]:
    phase_by_run = runs.set_index("run_id")["phase"].astype(str).to_dict()
    issues: list[SyntheticValidationIssue] = []
    for row_number, (_, row) in enumerate(metrology.iterrows(), start=2):
        scenario = str(row["scenario_id"])
        run_id = str(row["run_id"])
        if phase_by_run[run_id] == "baseline" and (
            str(row["measurement_status"]) != "VALID" or str(row["thickness_unit"]) != "nm"
        ):
            raise DatasetLoadError("baseline metrology must be valid and use nanometres")
        if str(row["measurement_status"]) != "VALID":
            issues.append(
                SyntheticValidationIssue(
                    code="INVALID_MEASUREMENT_STATUS",
                    message="Metrology status does not permit engineering interpretation.",
                    scenario_id=scenario,
                    run_id=run_id,
                    record_reference=f"metrology.csv:{row_number}",
                    blocks_metrology=True,
                )
            )
        if str(row["thickness_unit"]) != "nm":
            issues.append(
                SyntheticValidationIssue(
                    code="INCONSISTENT_THICKNESS_UNIT",
                    message="Thickness unit differs from the declared nanometre contract.",
                    scenario_id=scenario,
                    run_id=run_id,
                    record_reference=f"metrology.csv:{row_number}",
                    blocks_metrology=True,
                )
            )
        pre = float(row["pre_thickness_nm"])
        post = float(row["post_thickness_nm"])
        if post > pre:
            if phase_by_run[run_id] == "baseline":
                raise DatasetLoadError("baseline post thickness exceeds pre thickness")
            issues.append(
                SyntheticValidationIssue(
                    code="POST_THICKNESS_EXCEEDS_PRE",
                    message="Post-etch thickness exceeds pre-etch thickness.",
                    scenario_id=scenario,
                    run_id=run_id,
                    record_reference=f"metrology.csv:{row_number}",
                    blocks_metrology=True,
                )
            )
    return issues


def load_synthetic_dataset(directory: Path) -> SyntheticDataset:
    """Load an exact, bounded synthetic dataset and fail closed on structural defects."""
    directory = Path(directory)
    if directory.is_symlink():
        raise DatasetLoadError(f"Dataset directory must not be a symlink: {directory}")
    if not directory.is_dir():
        raise DatasetLoadError(f"Synthetic dataset directory does not exist: {directory}")
    observed_paths = tuple(directory.iterdir())
    if any(path.name == "scenario_truth.json" for path in observed_paths):
        raise DatasetLoadError("scenario truth must be isolated from application dataset")
    observed_entries = {path.name for path in observed_paths}
    if observed_entries != set(VISIBLE_FILENAMES):
        raise DatasetLoadError("unexpected content in synthetic application dataset")
    require_files(directory, VISIBLE_FILENAMES)
    manifest, manifest_sha256 = _load_manifest(directory / "dataset_manifest.json")
    _validate_manifest_filenames(manifest)
    runs = _read_csv(directory / "runs.csv", RUN_COLUMNS, MAX_RUNS, manifest.files["runs.csv"])
    telemetry = _read_csv(
        directory / "telemetry.csv",
        TELEMETRY_COLUMNS,
        MAX_TELEMETRY_ROWS,
        manifest.files["telemetry.csv"],
    )
    metrology = _read_csv(
        directory / "metrology.csv",
        METROLOGY_COLUMNS,
        MAX_METROLOGY_ROWS,
        manifest.files["metrology.csv"],
    )
    maintenance = _read_csv(
        directory / "maintenance.csv",
        MAINTENANCE_COLUMNS,
        MAX_RUNS,
        manifest.files["maintenance.csv"],
    )
    _validate_structure(runs, telemetry, metrology, maintenance, manifest)
    issues = tuple(_scientific_issues(runs, metrology))
    baseline_counts = {
        str(key): int(value)
        for key, value in runs.loc[runs["phase"] == "baseline"]
        .groupby("scenario_id")
        .size()
        .items()
    }
    incident_counts = {
        str(key): int(value)
        for key, value in runs.loc[runs["phase"] == "incident"]
        .groupby("scenario_id")
        .size()
        .items()
    }
    provenance = DatasetProvenance(
        dataset_id=manifest.dataset_id,
        source_directory=directory.as_posix(),
        source_files=tuple(sorted(VISIBLE_FILENAMES)),
        sha256={**manifest.files, "dataset_manifest.json": manifest_sha256},
        extraction_notes=(
            "Synthetic educational data; not evidence about industrial equipment.",
            "Scenario truth is excluded from application-visible provenance.",
        ),
    )
    summary = SyntheticValidationSummary(
        dataset_id=manifest.dataset_id,
        structurally_valid=True,
        record_counts={
            "maintenance": len(maintenance),
            "metrology": len(metrology),
            "runs": len(runs),
            "telemetry": len(telemetry),
        },
        baseline_counts=baseline_counts,
        incident_counts=incident_counts,
        issues=issues,
        validation_rules=(
            "exact schema and bounded file sizes",
            "SHA-256 manifest verification before parsing",
            "run/scenario referential integrity",
            "UTC run and telemetry interval consistency",
            "five fixed metrology sites per run",
            "scientifically invalid incident metrology remains visible and blocking",
        ),
    )
    dataset = SyntheticDataset(
        runs=runs,
        telemetry=telemetry,
        metrology=metrology,
        maintenance=maintenance,
        manifest=manifest,
        provenance=provenance,
        validation=summary,
    )
    return replace(dataset, content_sha256=_synthetic_dataset_content_sha256(dataset))


def _synthetic_dataset_content_sha256(dataset: SyntheticDataset) -> str:
    """Seal the exact in-memory frames and immutable context used for qualification."""
    digest = sha256()

    def update_json(value: Any) -> None:
        digest.update(
            json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        )

    def update_frame(frame: pd.DataFrame) -> None:
        update_json(
            {
                "columns": [str(column) for column in frame.columns],
                "dtypes": [str(dtype) for dtype in frame.dtypes],
                "shape": frame.shape,
            }
        )
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())

    update_json(dataset.provenance.model_dump(mode="json"))
    update_json(dataset.manifest.model_dump(mode="json"))
    update_json(dataset.validation.model_dump(mode="json"))
    update_frame(dataset.runs)
    update_frame(dataset.telemetry)
    update_frame(dataset.metrology)
    update_frame(dataset.maintenance)
    return digest.hexdigest()
