"""Pure numerical methods for synthetic candidate Individuals-MR evaluation."""

from __future__ import annotations

import math

from etch_copilot.synthetic.spc_contracts import (
    MINIMUM_BASELINE_OBSERVATIONS,
    MOVING_RANGE_D2,
    MOVING_RANGE_D3,
    MOVING_RANGE_D4,
    CandidateImrLimits,
    DependenceAdmissionOutcome,
    DependenceDiagnostic,
)


def _finite_values(values: tuple[float, ...], minimum: int) -> tuple[float, ...]:
    numeric = tuple(float(value) for value in values)
    if len(numeric) < minimum:
        raise ValueError(f"at least {minimum} observations are required")
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError("observations must all be finite")
    return numeric


def _scaled(values: tuple[float, ...]) -> tuple[float, tuple[float, ...]]:
    scale = max(abs(value) for value in values)
    if scale == 0.0:
        return 0.0, tuple(0.0 for _ in values)
    return scale, tuple(value / scale for value in values)


def _rescale(value: float, scale: float) -> float:
    result = value * scale
    if not math.isfinite(result):
        raise ValueError("observations do not produce finite representable limits")
    return result


def calculate_candidate_imr(values: tuple[float, ...]) -> CandidateImrLimits:
    """Calculate candidate I-MR limits and a 3-s comparator without admission claims."""
    numeric = _finite_values(values, 2)
    count = len(numeric)
    scale, normalized = _scaled(numeric)
    center_normalized = math.fsum(normalized) / count
    moving_ranges_normalized = tuple(
        abs(current - previous)
        for previous, current in zip(normalized, normalized[1:], strict=False)
    )
    average_moving_range_normalized = math.fsum(moving_ranges_normalized) / len(
        moving_ranges_normalized
    )
    sigma_moving_range_normalized = average_moving_range_normalized / MOVING_RANGE_D2
    sample_variance_normalized = math.fsum(
        (value - center_normalized) ** 2 for value in normalized
    ) / (count - 1)
    sample_standard_deviation_normalized = math.sqrt(sample_variance_normalized)
    center = _rescale(center_normalized, scale)
    moving_ranges = tuple(_rescale(value, scale) for value in moving_ranges_normalized)
    average_moving_range = _rescale(average_moving_range_normalized, scale)
    sigma_moving_range = _rescale(sigma_moving_range_normalized, scale)
    sample_standard_deviation = _rescale(sample_standard_deviation_normalized, scale)
    return CandidateImrLimits(
        observation_count=count,
        center_line=center,
        moving_ranges=moving_ranges,
        average_moving_range=average_moving_range,
        sigma_moving_range=sigma_moving_range,
        individual_lcl=_rescale(center_normalized - 3.0 * sigma_moving_range_normalized, scale),
        individual_ucl=_rescale(center_normalized + 3.0 * sigma_moving_range_normalized, scale),
        moving_range_lcl=MOVING_RANGE_D3 * average_moving_range,
        moving_range_ucl=_rescale(MOVING_RANGE_D4 * average_moving_range_normalized, scale),
        sample_standard_deviation=sample_standard_deviation,
        standard_deviation_individual_lcl=_rescale(
            center_normalized - 3.0 * sample_standard_deviation_normalized, scale
        ),
        standard_deviation_individual_ucl=_rescale(
            center_normalized + 3.0 * sample_standard_deviation_normalized, scale
        ),
    )


def diagnose_lag1_dependence(values: tuple[float, ...]) -> DependenceDiagnostic:
    """Apply a declared lag-1 screening rule; this is not proof of independence."""
    numeric = _finite_values(values, 2)
    count = len(numeric)
    limitation = (
        "Lag-1 screening cannot prove independence or exclude higher-order dependence, "
        "drift, mixtures, or seasonality."
    )
    if count < MINIMUM_BASELINE_OBSERVATIONS:
        return DependenceDiagnostic(
            outcome=DependenceAdmissionOutcome.INSUFFICIENT_EVIDENCE,
            observation_count=count,
            lag1_autocorrelation=None,
            screening_bound=None,
            method="project policy: at least 25 ordered observations before lag-1 screening",
            limitation=limitation,
        )
    _, normalized = _scaled(numeric)
    mean = math.fsum(normalized) / count
    denominator = math.fsum((value - mean) ** 2 for value in normalized)
    if denominator == 0.0:
        return DependenceDiagnostic(
            outcome=DependenceAdmissionOutcome.INSUFFICIENT_EVIDENCE,
            observation_count=count,
            lag1_autocorrelation=None,
            screening_bound=1.96 / math.sqrt(count),
            method="lag-1 sample autocorrelation with approximate white-noise screening bound",
            limitation=limitation,
        )
    numerator = math.fsum(
        (normalized[index] - mean) * (normalized[index - 1] - mean) for index in range(1, count)
    )
    lag1 = numerator / denominator
    bound = 1.96 / math.sqrt(count)
    outcome = (
        DependenceAdmissionOutcome.MATERIAL_AUTOCORRELATION
        if abs(lag1) > bound
        else DependenceAdmissionOutcome.PASS
    )
    return DependenceDiagnostic(
        outcome=outcome,
        observation_count=count,
        lag1_autocorrelation=lag1,
        screening_bound=bound,
        method="lag-1 sample autocorrelation with approximate ±1.96/sqrt(n) screening bound",
        limitation=limitation,
    )
