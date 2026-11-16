"""Public readiness-gated deterministic analytics API."""

from etch_copilot.analytics.bosch import (
    bosch_compare_runs,
    bosch_elapsed_trend,
    bosch_metrology_coverage,
    bosch_sensor_statistics,
)
from etch_copilot.analytics.contracts import AnalyticsScopeError
from etch_copilot.analytics.phm import phm_fault_inventory, phm_feature_inventory

__all__ = [
    "AnalyticsScopeError",
    "bosch_compare_runs",
    "bosch_elapsed_trend",
    "bosch_metrology_coverage",
    "bosch_sensor_statistics",
    "phm_fault_inventory",
    "phm_feature_inventory",
]
