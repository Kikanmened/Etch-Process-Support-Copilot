"""Seeded generator for the synthetic etch investigation scenarios."""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from etch_copilot.synthetic.contracts import (
    MAINTENANCE_COLUMNS,
    METROLOGY_COLUMNS,
    RUN_COLUMNS,
    SOURCE_FILENAMES,
    TELEMETRY_COLUMNS,
    VISIBLE_FILENAMES,
    ScenarioId,
    SyntheticGenerationResult,
    SyntheticGeneratorConfig,
    SyntheticManifest,
    synthetic_dataset_id,
)

_SITE_LAYOUT = (
    ("CENTER", 0.0, 0.0, 0.0),
    ("NORTH", 0.0, 0.8, 1.0),
    ("EAST", 0.8, 0.0, -0.8),
    ("SOUTH", 0.0, -0.8, 0.6),
    ("WEST", -0.8, 0.0, -0.4),
)
_BASE_START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _open_directory_components(directory: Path) -> int:
    """Open/create every directory component without following symlinks."""
    if ".." in directory.parts:
        raise ValueError(f"Output directory must not contain parent traversal: {directory}")
    absolute = directory.absolute()
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            with suppress(FileExistsError):
                os.mkdir(component, mode=0o755, dir_fd=descriptor)
            try:
                next_descriptor = os.open(component, flags, dir_fd=descriptor)
            except OSError as exc:
                raise ValueError(
                    f"Output path component must be a real directory: {component}"
                ) from exc
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def _open_empty_directory(directory: Path) -> Iterator[int]:
    descriptor = _open_directory_components(directory)
    try:
        if os.listdir(descriptor):
            raise FileExistsError(f"Output directory already contains files: {directory}")
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _open_exclusive_text(directory_fd: int, filename: str) -> Iterator[TextIO]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(filename, flags, 0o644, dir_fd=directory_fd)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
        yield handle


def _canonical_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{float(value):.6f}"
    return value


def _write_csv(
    rows: Iterable[dict[str, Any]],
    directory_fd: int,
    filename: str,
    columns: tuple[str, ...],
) -> None:
    with _open_exclusive_text(directory_fd, filename) as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _canonical_csv_value(row[column]) for column in columns})


def _write_json(payload: dict[str, Any], directory_fd: int, filename: str) -> None:
    with _open_exclusive_text(directory_fd, filename) as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _sha256_at(directory_fd: int, filename: str) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(filename, flags, dir_fd=directory_fd)
    digest = sha256()
    with os.fdopen(descriptor, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_distinct_directories(output_fd: int, truth_fd: int) -> None:
    output_status = os.fstat(output_fd)
    truth_status = os.fstat(truth_fd)
    if (output_status.st_dev, output_status.st_ino) == (
        truth_status.st_dev,
        truth_status.st_ino,
    ):
        raise ValueError("Scenario truth directory must be separate from application data")


def _run_rows(config: SyntheticGeneratorConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_count = config.baseline_runs_per_scenario + config.incident_runs_per_scenario
    for scenario_index, scenario in enumerate(ScenarioId):
        chamber = f"SYN-CHAMBER-{scenario.value}"
        recipe = "SYN-OXIDE-ETCH-V1"
        scenario_start = _BASE_START + timedelta(days=scenario_index * 10)
        for index in range(run_count):
            start = scenario_start + timedelta(minutes=index * 15)
            end = start + timedelta(seconds=config.etch_duration_s)
            phase = "baseline" if index < config.baseline_runs_per_scenario else "incident"
            event_id = "M-S1-001" if scenario is ScenarioId.S1 and phase == "incident" else ""
            rows.append(
                {
                    "scenario_id": scenario.value,
                    "run_id": f"{scenario.value}-R{index + 1:03d}",
                    "wafer_id": f"{scenario.value}-W{index + 1:03d}",
                    "chamber_id": chamber,
                    "recipe_id": recipe,
                    "start_ts_utc": _timestamp(start),
                    "end_ts_utc": _timestamp(end),
                    "etch_duration_s": config.etch_duration_s,
                    "etch_duration_standard_uncertainty_s": 0.1,
                    "lot_id": f"{scenario.value}-LOT-{index // 10 + 1:02d}",
                    "phase": phase,
                    "maintenance_event_id": event_id,
                }
            )
    return rows


def _telemetry_rows(
    runs: list[dict[str, Any]], config: SyntheticGeneratorConfig, rng: np.random.Generator
) -> Iterator[dict[str, Any]]:
    sample_count = config.etch_duration_s // config.telemetry_interval_s + 1
    missing_value_sample_index = min(7, sample_count - 1)
    for run_index, run in enumerate(runs):
        start = datetime.fromisoformat(str(run["start_ts_utc"]).replace("Z", "+00:00"))
        scenario = str(run["scenario_id"])
        incident = run["phase"] == "incident"
        for sample_index in range(sample_count):
            elapsed = sample_index * config.telemetry_interval_s
            pressure = 30.0 + rng.normal(0.0, 0.16)
            reflected = 20.0 + rng.normal(0.0, 0.7)
            if scenario == "S1" and incident:
                reflected = 45.0 + rng.normal(0.0, 1.2)
            if scenario == "S2" and incident:
                pressure += 3.2 * math.sin(2 * math.pi * sample_index / 6) + rng.normal(0.0, 0.5)
            temperature = 40.0 + rng.normal(0.0, 0.12)
            if scenario == "S1" and not incident and run_index == 0 and sample_index == 12:
                temperature += 8.0
            gas2: float | None = 20.0 + rng.normal(0.0, 0.08)
            first_s2_incident = f"S2-R{config.baseline_runs_per_scenario + 1:03d}"
            if (
                scenario == "S2"
                and incident
                and run["run_id"] == first_s2_incident
                and sample_index == missing_value_sample_index
            ):
                gas2 = None
            yield {
                "scenario_id": scenario,
                "run_id": run["run_id"],
                "timestamp_utc": _timestamp(start + timedelta(seconds=elapsed)),
                "pressure_mTorr": pressure,
                "rf_forward_W": 500.0 + rng.normal(0.0, 1.5),
                "rf_reflected_W": reflected,
                "gas1_flow_sccm": 50.0 + rng.normal(0.0, 0.1),
                "gas2_flow_sccm": gas2,
                "chamber_temp_C": temperature,
                "alarm_code": "",
            }


def _metrology_rows(
    runs: list[dict[str, Any]], config: SyntheticGeneratorConfig, rng: np.random.Generator
) -> Iterator[dict[str, Any]]:
    duration_minutes = config.etch_duration_s / 60.0
    for run in runs:
        scenario = str(run["scenario_id"])
        incident = run["phase"] == "incident"
        mean_rate = 100.0 + rng.normal(0.0, 1.2)
        if scenario == "S1" and incident:
            mean_rate = 92.0 + rng.normal(0.0, 1.0)
        elif scenario == "S2" and incident:
            mean_rate = 100.0 + rng.normal(0.0, 6.0)
        elif scenario == "S3" and incident:
            mean_rate = 92.0 + rng.normal(0.0, 1.0)
        for site_index, (site_id, x, y, site_effect) in enumerate(_SITE_LAYOUT):
            pre = 1000.0 + rng.normal(0.0, 1.0)
            site_rate = mean_rate + site_effect + rng.normal(0.0, 0.35)
            post = pre - site_rate * duration_minutes
            unit = "nm"
            status = "VALID"
            if scenario == "S3" and incident:
                status = "INVALID"
                if site_index == 0:
                    unit = "um"
                if site_index == 1:
                    post = pre + 2.0
            yield {
                "scenario_id": scenario,
                "run_id": run["run_id"],
                "site_id": site_id,
                "site_x_normalized": x,
                "site_y_normalized": y,
                "pre_thickness_nm": pre,
                "post_thickness_nm": post,
                "pre_standard_uncertainty_nm": 0.5,
                "post_standard_uncertainty_nm": 0.5,
                "thickness_unit": unit,
                "measurement_method": "synthetic_ex_situ_thickness",
                "calibration_reference": "SYNTHETIC-CALIBRATION-CONTEXT-ONLY",
                "measurement_status": status,
            }


def _maintenance_rows(config: SyntheticGeneratorConfig) -> list[dict[str, Any]]:
    event_time = _BASE_START + timedelta(minutes=config.baseline_runs_per_scenario * 15 - 5)
    return [
        {
            "event_id": "M-S1-001",
            "scenario_id": "S1",
            "chamber_id": "SYN-CHAMBER-S1",
            "timestamp_utc": _timestamp(event_time),
            "event_type": "synthetic_chamber_maintenance",
            "notes": "Synthetic educational event; no real equipment procedure or recipe.",
        }
    ]


def _write_truth(directory_fd: int, config: SyntheticGeneratorConfig) -> None:
    payload = {
        "generator_version": config.generator_version,
        "seed": config.seed,
        "visibility": "test_fixture_only_not_for_application_ingestion_or_genai",
        "scenarios": {
            "S1": {
                "injected_condition": "lower synthetic removal with elevated RF reflection",
                "expected_evidence_ids": [
                    "ETCH_RATE_SHIFT",
                    "RF_REFLECTION_INCREASE",
                    "POST_MAINTENANCE_TIMING",
                ],
            },
            "S2": {
                "injected_condition": "pressure oscillation and variable synthetic removal",
                "expected_evidence_ids": ["PRESSURE_INSTABILITY", "OUTCOME_VARIABILITY"],
            },
            "S3": {
                "injected_condition": "invalid metrology",
                "expected_evidence_ids": ["DATA_QUALITY_BLOCKED"],
            },
        },
    }
    _write_json(payload, directory_fd, "scenario_truth.json")


def generate_synthetic_dataset(
    output_directory: Path,
    config: SyntheticGeneratorConfig,
    *,
    truth_directory: Path | None = None,
) -> SyntheticGenerationResult:
    """Generate canonical visible files and optionally isolated test truth."""
    output_directory = Path(output_directory)
    if truth_directory is not None:
        resolved_output = output_directory.resolve()
        resolved_truth = Path(truth_directory).resolve()
        if (
            resolved_truth == resolved_output
            or resolved_truth.is_relative_to(resolved_output)
            or resolved_output.is_relative_to(resolved_truth)
        ):
            raise ValueError("Scenario truth directory must be separate from application data")
    with ExitStack() as stack:
        output_fd = stack.enter_context(_open_empty_directory(output_directory))
        truth_fd = (
            stack.enter_context(_open_empty_directory(Path(truth_directory)))
            if truth_directory is not None
            else None
        )
        if truth_fd is not None:
            _require_distinct_directories(output_fd, truth_fd)
        rng = np.random.default_rng(config.seed)
        run_rows = _run_rows(config)
        _write_csv(run_rows, output_fd, "runs.csv", RUN_COLUMNS)
        _write_csv(
            _telemetry_rows(run_rows, config, rng),
            output_fd,
            "telemetry.csv",
            TELEMETRY_COLUMNS,
        )
        _write_csv(
            _metrology_rows(run_rows, config, rng),
            output_fd,
            "metrology.csv",
            METROLOGY_COLUMNS,
        )
        _write_csv(
            _maintenance_rows(config),
            output_fd,
            "maintenance.csv",
            MAINTENANCE_COLUMNS,
        )
        file_hashes = {filename: _sha256_at(output_fd, filename) for filename in SOURCE_FILENAMES}
        dataset_id = synthetic_dataset_id(
            seed=config.seed,
            schema_version=config.schema_version,
            generator_version=config.generator_version,
            baseline_runs_per_scenario=config.baseline_runs_per_scenario,
            incident_runs_per_scenario=config.incident_runs_per_scenario,
            telemetry_interval_s=config.telemetry_interval_s,
            etch_duration_s=config.etch_duration_s,
        )
        manifest = SyntheticManifest(
            dataset_id=dataset_id,
            schema_version=config.schema_version,
            generator_version=config.generator_version,
            seed=config.seed,
            generated_at_policy=(
                "fixed timestamps derived from scenario and run index; no wall clock"
            ),
            telemetry_interval_s=config.telemetry_interval_s,
            etch_duration_s=config.etch_duration_s,
            baseline_runs_per_scenario=config.baseline_runs_per_scenario,
            incident_runs_per_scenario=config.incident_runs_per_scenario,
            scenarios=tuple(ScenarioId),
            files=file_hashes,
            scenario_truth_policy="separate test fixture; never present in application dataset",
            scientific_scope="synthetic educational demonstration; not validated plasma physics",
        )
        _write_json(manifest.model_dump(mode="json"), output_fd, "dataset_manifest.json")
        if truth_fd is not None:
            _write_truth(truth_fd, config)
    return SyntheticGenerationResult(
        dataset_id=dataset_id,
        output_directory=output_directory.as_posix(),
        visible_files=VISIBLE_FILENAMES,
        file_sha256=file_hashes,
        truth_directory=Path(truth_directory).as_posix() if truth_directory is not None else None,
    )
