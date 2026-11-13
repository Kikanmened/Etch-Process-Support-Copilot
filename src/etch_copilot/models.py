"""Typed engineering contracts shared by source-specific loaders."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DatasetProvenance(BaseModel):
    dataset_id: str
    source_directory: str
    source_files: tuple[str, ...]
    sha256: dict[str, str]
    extraction_notes: tuple[str, ...] = ()


class ScientificReference(BaseModel):
    reference_id: str
    source_path: str
    sha256: str
    role: str
    verified: bool


class EquipmentIdentifier(BaseModel):
    source_value: str
    normalized_value: str | None = None
    normalization_note: str | None = None


class ProcessRun(BaseModel):
    run_id: str
    equipment_id: str | None = None
    lot_id: str | None = None
    recipe_id: str | None = None
    wafer_id: str | None = None
    observation_count: int = Field(ge=0)
    feature_count: int = Field(ge=0)
    time_basis: str
    extra: dict[str, Any] = Field(default_factory=dict)


class SensorObservation(BaseModel):
    dataset_id: str
    run_id: str
    time_value: float
    time_unit: str | None = None
    measurements: dict[str, float | int | str | None]


class WaferMetrology(BaseModel):
    experiment_key: str
    lot_number: int
    wafer_number: int
    x: float
    y: float
    measurements: dict[str, float | None]
    extra: dict[str, Any] = Field(default_factory=dict)


class FaultEvent(BaseModel):
    event_time: int | None
    fault_name: str | None
    equipment_id: str | None
    time_semantics: str = "recorded event time; not assumed to be exact fault onset"


class DataQualityIssue(BaseModel):
    code: str
    severity: Severity
    message: str
    source_file: str | None = None
    record_reference: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationSummary(BaseModel):
    dataset_id: str
    valid: bool
    record_counts: dict[str, int]
    duplicate_counts: dict[str, int]
    missing_values: dict[str, int]
    timestamp_ranges: dict[str, tuple[float | int | None, float | int | None]]
    features: tuple[str, ...]
    identifier_relationships: dict[str, Any]
    issues: tuple[DataQualityIssue, ...]
    unsupported_assumptions: tuple[str, ...]

    model_config = ConfigDict(extra="forbid")


class DatasetLoadError(RuntimeError):
    """Raised when source files cannot be loaded without inventing data."""


def path_text(path: Path) -> str:
    """Return a stable POSIX representation for report serialization."""
    return path.as_posix()
