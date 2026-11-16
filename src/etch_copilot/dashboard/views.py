"""Bounded, explicit presentation projection and display-only point selection."""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel


class DashboardError(RuntimeError):
    """A safe message suitable for a local dashboard."""


# Deliberately excludes paths, arbitrary metadata, extraction notes and supplied manifests.
FIELDS = frozenset(
    [
        "dataset_id",
        "analysis_id",
        "analysis_version",
        "engine_version",
        "method_version",
        "limit_scope",
        "operational_control_limits_status",
        "capability",
        "status",
        "readiness_status",
        "scope",
        "limitations",
        "validation_rules",
        "reasons",
        "missing_requirements",
        "blocking_issues",
        "readiness",
        "decisions",
        "scenarios",
        "scenario_id",
        "external_dataset_effect",
        "observation_count",
        "dependence",
        "baseline_transitions",
        "issues",
        "baseline",
        "interpretation_policy",
        "code",
        "message",
        "run_ids",
        "outcome",
        "lag1_autocorrelation",
        "screening_bound",
        "method",
        "limitation",
        "baseline_id",
        "observations",
        "limits",
        "nominal_sampling_interval_s",
        "source_digests",
        "source_file",
        "sha256",
        "run_id",
        "wafer_id",
        "start_ts_utc",
        "phase",
        "etch_rate_nm_per_min",
        "valid_site_count",
        "calculation_version",
        "center_line",
        "moving_ranges",
        "average_moving_range",
        "d2",
        "d3",
        "d4",
        "sigma_moving_range",
        "individual_lcl",
        "individual_ucl",
        "moving_range_lcl",
        "moving_range_ucl",
        "sample_standard_deviation",
        "standard_deviation_individual_lcl",
        "standard_deviation_individual_ucl",
        "previous_run_id",
        "current_run_id",
        "disposition",
        "moving_range",
        "moving_range_signal",
        "chart",
        "value",
        "limit",
        "direction",
        "incident_observations",
        "transitions",
        "individual_signals",
        "moving_range_signals",
        "incident_mean",
        "incident_mean_difference",
        "feature",
        "engineering_unit",
        "unit_verified",
        "coordinate_name",
        "coordinate_unit",
        "coordinate_semantics",
        "documented_acquisition_hz",
        "elapsed_coordinates",
        "sensor_values",
        "interval_summary",
        "interval_count",
        "minimum_interval_s",
        "median_interval_s",
        "maximum_interval_s",
        "discontinuity_after_indices",
        "non_positive_interval_count",
        "statistics",
        "finite_count",
        "missing_count",
        "positive_infinity_count",
        "negative_infinity_count",
        "available_coverage",
        "minimum",
        "maximum",
        "mean",
        "median",
        "standard_deviation",
        "variance",
        "calculation_warnings",
        "runs",
        "total_site_records",
        "selected_wafer_count",
        "measurement_unit",
        "wafers",
        "missingness_by_lot",
        "data_quality_issues",
        "reconstruction_policy",
        "experiment_key",
        "lot_number",
        "wafer_number",
        "site_record_count",
        "unique_position_count",
        "expected_site_count",
        "relationship_unambiguous",
        "pre_etch_direct_count",
        "pre_etch_reconstructed_count",
        "pre_etch_unclassified_count",
        "post_etch_direct_count",
        "post_etch_reconstructed_count",
        "post_etch_unclassified_count",
        "missing_fields",
        "field",
        "group_key",
        "record_count",
        "source_equipment_ids",
        "canonical_equipment_id",
        "raw_observation_count",
        "exact_duplicate_count",
        "features",
        "source_name",
        "recorded_dtype",
        "invalid_non_numeric_count",
        "repeated_value_count",
        "time_unit",
        "time_semantics",
        "sampling_bias",
        "total_recorded_events",
        "category_counts",
        "events",
        "event_semantics",
        "ambiguous_event_field_count",
        "category",
        "count",
        "source_index",
        "source_equipment_id",
        "source_coordinate",
        "is_confirmed_fault_onset",
    ]
)


def safe_text(value: str) -> str:
    """Remove paths, active markup, control characters, and credential-like strings."""
    text = re.sub(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]", " ", value)
    text = re.sub(r"(?i)(?:https?://|file://|[a-z]:[\\/]|~/)[^\s<>\"']+", "[redacted]", text)
    text = re.sub(r"(?<![\w])/(?:[^\s<>\"']+)", "[redacted]", text)
    text = re.sub(r"(?i)(?:token|password|secret|api[_-]?key)\s*[:=]\s*\S+", "[redacted]", text)
    text = re.sub(r"(?i)scenario_truth(?:\.json)?", "[excluded reference]", text)
    return text.replace("<", "‹").replace(">", "›")[:2000]


def project(value: Any) -> Any:
    """Project backend values through an explicit recursive field allowlist."""
    if isinstance(value, BaseModel):
        return project(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: project(item) for key, item in value.items() if key in FIELDS}
    if isinstance(value, (list, tuple)):
        return [project(item) for item in value]
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise DashboardError("Unsupported presentation value.")


def select_indices(
    values: list[float | None], *, budget: int = 5000, required: set[int] | None = None
) -> list[int]:
    """Select original samples; preserve signals, gap edges, extrema and bucket extrema."""
    if not values:
        return []
    keep = {0, len(values) - 1} | (required or set())
    if any(index < 0 or index >= len(values) for index in keep):
        raise DashboardError("Invalid display point selection.")
    finite = [i for i, value in enumerate(values) if value is not None and math.isfinite(value)]
    if finite:
        keep |= {
            min(finite, key=lambda i: values[i] or 0.0),
            max(finite, key=lambda i: values[i] or 0.0),
        }
    for index, value in enumerate(values):
        if value is None or not math.isfinite(value):
            # Keep starts/ends of missing blocks and adjacent valid samples.
            if index == 0 or values[index - 1] is not None:
                keep.update(range(max(0, index - 1), min(len(values), index + 2)))
            if index == len(values) - 1 or values[index + 1] is not None:
                keep.update(range(max(0, index - 1), min(len(values), index + 2)))
    if len(keep) > budget:
        raise DashboardError("Too many critical points for this display. Narrow the selection.")
    if len(values) <= budget:
        return list(range(len(values)))
    buckets = max(0, (budget - len(keep)) // 2)
    for bucket in range(buckets):
        start = bucket * len(values) // buckets
        end = (bucket + 1) * len(values) // buckets
        candidates = [i for i in range(start, end) if values[i] is not None]
        if candidates:
            keep.add(min(candidates, key=lambda i: values[i] or 0.0))
            keep.add(max(candidates, key=lambda i: values[i] or 0.0))
    return sorted(keep)
