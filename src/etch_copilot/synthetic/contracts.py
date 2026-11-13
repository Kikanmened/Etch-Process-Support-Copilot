"""Typed contracts for isolated synthetic etch demonstration datasets."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from etch_copilot.qualification import ReadinessStatus

SYNTHETIC_SCHEMA_VERSION = "1.0.0"
SYNTHETIC_GENERATOR_VERSION = "1.0.0"
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_RUNS = 2_000
MAX_TELEMETRY_ROWS = 50_000
MAX_METROLOGY_ROWS = 20_000

RUN_COLUMNS = (
    "scenario_id",
    "run_id",
    "wafer_id",
    "chamber_id",
    "recipe_id",
    "start_ts_utc",
    "end_ts_utc",
    "etch_duration_s",
    "etch_duration_standard_uncertainty_s",
    "lot_id",
    "phase",
    "maintenance_event_id",
)
TELEMETRY_COLUMNS = (
    "scenario_id",
    "run_id",
    "timestamp_utc",
    "pressure_mTorr",
    "rf_forward_W",
    "rf_reflected_W",
    "gas1_flow_sccm",
    "gas2_flow_sccm",
    "chamber_temp_C",
    "alarm_code",
)
METROLOGY_COLUMNS = (
    "scenario_id",
    "run_id",
    "site_id",
    "site_x_normalized",
    "site_y_normalized",
    "pre_thickness_nm",
    "post_thickness_nm",
    "pre_standard_uncertainty_nm",
    "post_standard_uncertainty_nm",
    "thickness_unit",
    "measurement_method",
    "calibration_reference",
    "measurement_status",
)
MAINTENANCE_COLUMNS = (
    "event_id",
    "scenario_id",
    "chamber_id",
    "timestamp_utc",
    "event_type",
    "notes",
)
SOURCE_FILENAMES = (
    "maintenance.csv",
    "metrology.csv",
    "runs.csv",
    "telemetry.csv",
)
VISIBLE_FILENAMES = (*SOURCE_FILENAMES, "dataset_manifest.json")


def synthetic_dataset_id(
    *,
    seed: int,
    schema_version: str,
    generator_version: str,
    baseline_runs_per_scenario: int,
    incident_runs_per_scenario: int,
    telemetry_interval_s: int,
    etch_duration_s: int,
) -> str:
    """Bind dataset identity to every generation setting that changes content."""
    configuration = {
        "baseline_runs_per_scenario": baseline_runs_per_scenario,
        "etch_duration_s": etch_duration_s,
        "generator_version": generator_version,
        "incident_runs_per_scenario": incident_runs_per_scenario,
        "schema_version": schema_version,
        "seed": seed,
        "telemetry_interval_s": telemetry_interval_s,
    }
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"synthetic-etch-demo-v1-seed-{seed}-cfg-{digest}"


class FrozenModel(BaseModel):
    """Immutable base for contracts that participate in audit records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ScenarioId(StrEnum):
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"


class SyntheticCapability(StrEnum):
    INGESTION = "synthetic.ingestion"
    ETCH_RATE_INPUTS = "synthetic.etch_rate_inputs"
    UNIFORMITY_INPUTS = "synthetic.uniformity_inputs"
    SPC_CONTROL_LIMITS = "synthetic.spc_control_limits"
    ROOT_CAUSE_ATTRIBUTION = "synthetic.root_cause_attribution"


class SyntheticGeneratorConfig(FrozenModel):
    seed: int
    baseline_runs_per_scenario: int = Field(default=30, ge=30, le=500)
    incident_runs_per_scenario: int = Field(default=8, ge=1, le=100)
    telemetry_interval_s: int = Field(default=5, ge=1, le=60)
    etch_duration_s: int = Field(default=120, ge=60, le=300)
    schema_version: str = SYNTHETIC_SCHEMA_VERSION
    generator_version: str = SYNTHETIC_GENERATOR_VERSION

    @model_validator(mode="after")
    def validate_sampling_contract(self) -> SyntheticGeneratorConfig:
        if self.etch_duration_s % self.telemetry_interval_s != 0:
            raise ValueError("etch_duration_s must be divisible by telemetry_interval_s")
        sample_count = self.etch_duration_s // self.telemetry_interval_s + 1
        if sample_count < 13:
            raise ValueError("configuration must provide at least 13 telemetry samples per run")
        run_count = 3 * (self.baseline_runs_per_scenario + self.incident_runs_per_scenario)
        telemetry_rows = run_count * sample_count
        metrology_rows = run_count * 5
        if run_count > MAX_RUNS:
            raise ValueError("configuration exceeds the synthetic run-count limit")
        if telemetry_rows > MAX_TELEMETRY_ROWS:
            raise ValueError("configuration exceeds the synthetic telemetry-row limit")
        if metrology_rows > MAX_METROLOGY_ROWS:
            raise ValueError("configuration exceeds the synthetic metrology-row limit")
        estimated_source_bytes = {
            "runs.csv": run_count * 512,
            "telemetry.csv": telemetry_rows * 256,
            "metrology.csv": metrology_rows * 512,
        }
        if any(size > MAX_SOURCE_BYTES for size in estimated_source_bytes.values()):
            raise ValueError("configuration exceeds the synthetic source-byte budget")
        return self


class SyntheticManifest(FrozenModel):
    dataset_id: str
    schema_version: str
    generator_version: str
    seed: int
    generated_at_policy: str
    telemetry_interval_s: int
    etch_duration_s: int
    baseline_runs_per_scenario: int
    incident_runs_per_scenario: int
    scenarios: tuple[ScenarioId, ...]
    files: dict[str, str]
    scenario_truth_policy: str
    scientific_scope: str


class SyntheticGenerationResult(FrozenModel):
    dataset_id: str
    output_directory: str
    visible_files: tuple[str, ...]
    file_sha256: dict[str, str]
    truth_directory: str | None


class SyntheticValidationIssue(FrozenModel):
    code: str
    message: str
    scenario_id: str | None = None
    run_id: str | None = None
    record_reference: str | None = None
    blocks_metrology: bool = False


class SyntheticValidationSummary(FrozenModel):
    dataset_id: str
    structurally_valid: bool
    record_counts: dict[str, int]
    baseline_counts: dict[str, int]
    incident_counts: dict[str, int]
    issues: tuple[SyntheticValidationIssue, ...]
    validation_rules: tuple[str, ...]


class SyntheticCapabilityDecision(FrozenModel):
    capability: SyntheticCapability
    status: ReadinessStatus
    reasons: tuple[str, ...]


class SyntheticScenarioQualification(FrozenModel):
    scenario_id: ScenarioId
    decisions: tuple[SyntheticCapabilityDecision, ...]

    def status(self, capability: SyntheticCapability) -> ReadinessStatus:
        for decision in self.decisions:
            if decision.capability is capability:
                return decision.status
        raise KeyError(f"No readiness decision for {capability}")


class SyntheticQualificationReport(FrozenModel):
    dataset_id: str
    scenarios: tuple[SyntheticScenarioQualification, ...]
    external_dataset_effect: str
    limitations: tuple[str, ...]

    def scenario(self, scenario_id: str | ScenarioId) -> SyntheticScenarioQualification:
        requested = ScenarioId(scenario_id)
        for scenario in self.scenarios:
            if scenario.scenario_id is requested:
                return scenario
        raise KeyError(f"Unknown synthetic scenario: {scenario_id}")
