from __future__ import annotations

import math
import random

import pytest

from etch_copilot.synthetic.spc_contracts import DependenceAdmissionOutcome
from etch_copilot.synthetic.spc_methods import (
    calculate_candidate_imr,
    diagnose_lag1_dependence,
)


def test_hand_calculated_imr_formulas_and_nist_comparator() -> None:
    result = calculate_candidate_imr((10.0, 12.0, 11.0, 13.0, 12.0))

    assert result.center_line == pytest.approx(11.6)
    assert result.moving_ranges == pytest.approx((2.0, 1.0, 2.0, 1.0))
    assert result.average_moving_range == pytest.approx(1.5)
    assert result.d2 == pytest.approx(1.128)
    assert result.d3 == pytest.approx(0.0)
    assert result.d4 == pytest.approx(3.267)
    assert result.sigma_moving_range == pytest.approx(1.5 / 1.128)
    assert result.individual_lcl == pytest.approx(11.6 - 3.0 * 1.5 / 1.128)
    assert result.individual_ucl == pytest.approx(11.6 + 3.0 * 1.5 / 1.128)
    assert result.moving_range_lcl == pytest.approx(0.0)
    assert result.moving_range_ucl == pytest.approx(3.267 * 1.5)
    assert result.sample_standard_deviation == pytest.approx(math.sqrt(1.3))
    assert result.standard_deviation_individual_lcl == pytest.approx(11.6 - 3.0 * math.sqrt(1.3))
    assert result.standard_deviation_individual_ucl == pytest.approx(11.6 + 3.0 * math.sqrt(1.3))
    assert result.limit_scope == "synthetic_candidate_not_operational"


@pytest.mark.parametrize(
    "values",
    [
        (1.0,),
        (1.0, float("nan")),
        (1.0, float("inf")),
        (1.0, float("-inf")),
    ],
)
def test_imr_rejects_small_or_non_finite_inputs(values: tuple[float, ...]) -> None:
    with pytest.raises(ValueError):
        calculate_candidate_imr(values)


def test_dependence_diagnostic_has_explicit_admission_outcomes() -> None:
    insufficient = diagnose_lag1_dependence(tuple(float(index) for index in range(24)))
    material = diagnose_lag1_dependence(tuple(float(index % 2) for index in range(30)))
    generator = random.Random(0)
    passing = diagnose_lag1_dependence(tuple(generator.random() for _ in range(30)))

    assert insufficient.outcome is DependenceAdmissionOutcome.INSUFFICIENT_EVIDENCE
    assert material.outcome is DependenceAdmissionOutcome.MATERIAL_AUTOCORRELATION
    assert passing.outcome is DependenceAdmissionOutcome.PASS


def test_zero_moving_range_is_calculated_but_cannot_estimate_variability() -> None:
    result = calculate_candidate_imr((5.0,) * 25)
    diagnostic = diagnose_lag1_dependence((5.0,) * 25)

    assert result.average_moving_range == 0.0
    assert result.sigma_moving_range == 0.0
    assert diagnostic.outcome is DependenceAdmissionOutcome.INSUFFICIENT_EVIDENCE


def test_extreme_finite_values_are_stable_or_rejected_deterministically() -> None:
    constant = calculate_candidate_imr((1e308, 1e308))

    assert constant.center_line == 1e308
    assert constant.average_moving_range == 0.0

    with pytest.raises(ValueError, match="finite representable limits"):
        calculate_candidate_imr((-1e308, 1e308))
