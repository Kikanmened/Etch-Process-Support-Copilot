from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest

from etch_copilot.analytics import (
    AnalyticsScopeError,
    bosch_compare_runs,
    bosch_elapsed_trend,
    bosch_metrology_coverage,
    bosch_sensor_statistics,
)
from etch_copilot.loaders import load_bosch_dataset
from etch_copilot.models import DatasetLoadError
from etch_copilot.qualification import AnalysisBlockedError, ReadinessStatus


def test_sensor_statistics_use_finite_values_and_sample_variance(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Dictionary_process.nc", "r+") as handle:
        handle["data"][:] = np.array([0.0, 1.0, 3.0])
    dataset = load_bosch_dataset(bosch_fixture)

    result = bosch_sensor_statistics(dataset, "Day_2024_07_02_Wafer_01", "pressure")

    assert result.readiness_status is ReadinessStatus.LIMITED
    assert result.engineering_unit is None
    assert result.unit_verified is False
    assert result.statistics.observation_count == 2
    assert result.statistics.finite_count == 2
    assert result.statistics.mean == pytest.approx(2.0)
    assert result.statistics.median == pytest.approx(2.0)
    assert result.statistics.variance == pytest.approx(2.0)
    assert result.statistics.standard_deviation == pytest.approx(2**0.5)
    assert result.statistics.available_coverage == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("values", "finite_count", "missing_count", "positive_inf", "negative_inf", "variance"),
    [
        ([np.inf, -np.inf], 0, 0, 1, 1, None),
        ([4.0, np.nan], 1, 1, 0, 0, None),
        ([4.0, 4.0], 2, 0, 0, 0, 0.0),
    ],
)
def test_sensor_statistics_edge_cases(
    bosch_fixture: Path,
    values: list[float],
    finite_count: int,
    missing_count: int,
    positive_inf: int,
    negative_inf: int,
    variance: float | None,
) -> None:
    with h5py.File(bosch_fixture / "Dictionary_process.nc", "r+") as handle:
        handle["data"][:] = np.array([0.0, *values])
    dataset = load_bosch_dataset(bosch_fixture)

    result = bosch_sensor_statistics(dataset, "Day_2024_07_02_Wafer_01", "pressure")

    assert result.statistics.finite_count == finite_count
    assert result.statistics.missing_count == missing_count
    assert result.statistics.positive_infinity_count == positive_inf
    assert result.statistics.negative_infinity_count == negative_inf
    assert result.statistics.variance == variance


def test_elapsed_trend_preserves_coordinates_and_detects_gap(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        handle["Day_2024_07_02_Wafer_01/times"][:] = [90.0, 90.5]
    dataset = load_bosch_dataset(bosch_fixture)

    result = bosch_elapsed_trend(dataset, "Day_2024_07_02_Wafer_01", "pressure")

    assert result.elapsed_coordinates == (90.0, 90.5)
    assert result.sensor_values == (1.5, 2.5)
    assert result.coordinate_semantics == "run-local elapsed coordinate"
    assert result.documented_acquisition_hz is None
    assert result.interval_summary.median_interval_s == pytest.approx(0.5)
    assert result.provenance.dataset_id == "bosch_plasma_etch_2025"


def test_in_memory_mutation_breaks_dataset_content_seal(bosch_fixture: Path) -> None:
    dataset = load_bosch_dataset(bosch_fixture)
    dataset.runs[0].values.loc[0, "pressure"] = 999.0

    with pytest.raises(DatasetLoadError, match="content changed"):
        bosch_sensor_statistics(dataset, "Day_2024_07_02_Wafer_01", "pressure")


def test_non_finite_elapsed_coordinate_is_blocked(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        handle["Day_2024_07_02_Wafer_01/times"][:] = [90.0, np.inf]

    with pytest.raises(AnalysisBlockedError):
        bosch_elapsed_trend(
            load_bosch_dataset(bosch_fixture),
            "Day_2024_07_02_Wafer_01",
            "pressure",
        )


def test_elapsed_trend_rechecks_blocked_time_contract(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        del handle["Day_2024_07_02_Wafer_01/times"].attrs["units"]

    with pytest.raises(AnalysisBlockedError):
        bosch_elapsed_trend(
            load_bosch_dataset(bosch_fixture),
            "Day_2024_07_02_Wafer_01",
            "pressure",
        )


def test_cross_run_comparison_requires_two_compatible_runs(bosch_fixture: Path) -> None:
    dataset = load_bosch_dataset(bosch_fixture)

    with pytest.raises(AnalyticsScopeError, match="at least two"):
        bosch_compare_runs(dataset, ("Day_2024_07_02_Wafer_01",), "pressure")


def test_cross_run_comparison_rejects_duplicate_scope_amplification(
    bosch_fixture: Path,
) -> None:
    dataset = load_bosch_dataset(bosch_fixture)
    run_id = "Day_2024_07_02_Wafer_01"

    with pytest.raises(AnalyticsScopeError, match="duplicate run IDs"):
        bosch_compare_runs(dataset, (run_id, run_id), "pressure")


def test_cross_run_comparison_is_side_by_side_not_pooled(bosch_fixture: Path) -> None:
    with h5py.File(bosch_fixture / "Process_data.nc", "r+") as handle:
        source = handle["Day_2024_07_02_Wafer_01"]
        target = handle.create_group("Day_2024_07_03_Wafer_01")
        for name in ("data", "feature", "times"):
            source.copy(name, target)
    dataset = load_bosch_dataset(bosch_fixture)

    result = bosch_compare_runs(
        dataset,
        ("Day_2024_07_02_Wafer_01", "Day_2024_07_03_Wafer_01"),
        "pressure",
    )

    assert result.readiness_status is ReadinessStatus.LIMITED
    assert len(result.runs) == 2
    assert not hasattr(result, "pooled_statistics")


def test_metrology_coverage_flags_direct_and_reconstructed_values(
    bosch_fixture: Path,
) -> None:
    path = bosch_fixture / "Si_Oxide_etch_89_points.csv"
    frame = pd.read_csv(path)
    frame.loc[0, "postox_thickness_nan"] = np.nan
    frame.loc[0, "postox_thickness"] = 0.4
    frame.to_csv(path, index=False)

    result = bosch_metrology_coverage(load_bosch_dataset(bosch_fixture))

    assert result.readiness_status is ReadinessStatus.LIMITED
    assert result.total_site_records == 1
    assert result.wafers[0].pre_etch_reconstructed_count == 0
    assert result.wafers[0].pre_etch_unclassified_count == 1
    assert result.wafers[0].post_etch_direct_count == 0
    assert result.wafers[0].post_etch_reconstructed_count == 0
    assert result.wafers[0].post_etch_unclassified_count == 1
    assert result.wafers[0].run_id == "Day_2024_07_02_Wafer_01"
    assert result.data_quality_issues


def test_metrology_scope_rejects_duplicate_wafer_amplification(bosch_fixture: Path) -> None:
    dataset = load_bosch_dataset(bosch_fixture)

    with pytest.raises(AnalyticsScopeError, match="duplicate wafer keys"):
        bosch_metrology_coverage(dataset, ("2024-07-02_01", "2024-07-02_01"))
