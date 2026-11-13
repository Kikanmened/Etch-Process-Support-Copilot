from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.analytics import (
    AnalyticsScopeError,
    bosch_compare_runs,
    bosch_elapsed_trend,
    bosch_metrology_coverage,
    bosch_sensor_statistics,
    phm_fault_inventory,
    phm_feature_inventory,
)
from etch_copilot.analytics.policies import numeric_statistics
from etch_copilot.analytics.reporting import write_analytics_results
from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset


def test_empty_numeric_statistics_are_explicit() -> None:
    result = numeric_statistics(pd.Series([], dtype="float64"))

    assert result.observation_count == 0
    assert result.available_coverage == 0.0
    assert result.mean is None
    assert result.variance is None


def test_numeric_statistics_flag_variance_overflow_without_non_finite_output() -> None:
    result = numeric_statistics(pd.Series([1e308, -1e308], dtype="float64"))

    assert result.mean == 0.0
    assert result.standard_deviation == pytest.approx(2**0.5 * 1e308)
    assert result.variance is None
    assert result.calculation_warnings == ("sample variance overflowed float64 range",)


def test_numeric_statistics_preserve_subnormal_median_and_flag_variance_underflow() -> None:
    result = numeric_statistics(pd.Series([5e-324, 1e-323], dtype="float64"))

    assert result.median == 1e-323
    assert result.standard_deviation == 5e-324
    assert result.variance is None
    assert result.calculation_warnings == ("sample variance underflowed float64 range",)


def test_numeric_statistics_flag_sparse_subnormal_underflow() -> None:
    result = numeric_statistics(pd.Series([5e-324, *([0.0] * 99)], dtype="float64"))

    assert result.mean is None
    assert result.standard_deviation is None
    assert result.variance is None
    assert result.calculation_warnings == (
        "arithmetic mean underflowed float64 range",
        "sample standard deviation underflowed float64 range",
        "sample variance underflowed float64 range",
    )


def test_empty_metrology_scope_is_rejected(bosch_fixture: Path) -> None:
    with pytest.raises(AnalyticsScopeError, match="at least one wafer"):
        bosch_metrology_coverage(load_bosch_dataset(bosch_fixture), ())


def test_cross_dataset_mixing_is_rejected(phm_fixture: Path) -> None:
    phm = load_phm_dataset(phm_fixture)

    with pytest.raises(AnalyticsScopeError, match="BoschDataset"):
        bosch_sensor_statistics(  # type: ignore[arg-type]
            phm, "not-a-bosch-run", "not-a-bosch-feature"
        )


def test_analytics_json_reporting_is_deterministic_and_rejects_symlink(
    phm_fixture: Path, tmp_path: Path
) -> None:
    result = phm_feature_inventory(load_phm_dataset(phm_fixture))
    first = write_analytics_results({"feature_inventory": result}, tmp_path / "first")
    second = write_analytics_results({"feature_inventory": result}, tmp_path / "second")

    assert first[0].read_bytes() == second[0].read_bytes()
    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to(tmp_path / "first", target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe analytics output directory"):
        write_analytics_results({"feature_inventory": result}, unsafe)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe analytics output directory"):
        write_analytics_results({"feature_inventory": result}, linked_parent / "reports")
    with pytest.raises(ValueError, match="unsafe analytics result name"):
        write_analytics_results({"../escape": result}, tmp_path / "safe")
    target = tmp_path / "preserve.json"
    target.write_text("preserve", encoding="utf-8")
    target_output = tmp_path / "target-output"
    target_output.mkdir()
    (target_output / "feature_inventory.json").symlink_to(target)
    with pytest.raises(ValueError, match="unsafe analytics output target"):
        write_analytics_results({"feature_inventory": result}, target_output)
    assert target.read_text(encoding="utf-8") == "preserve"


@pytest.mark.integration
def test_actual_bosch_analytics() -> None:
    dataset = load_bosch_dataset(Path("data/external/bosch"))
    run_ids = (dataset.runs[0].metadata.run_id, dataset.runs[1].metadata.run_id)
    feature = "Stat3_Etch_MV_ForeLinePressure"

    trend = bosch_elapsed_trend(dataset, run_ids[0], feature)
    statistics = bosch_sensor_statistics(dataset, run_ids[0], feature)
    comparison = bosch_compare_runs(dataset, run_ids, feature)
    metrology = bosch_metrology_coverage(dataset)

    assert len(trend.elapsed_coordinates) == dataset.runs[0].metadata.observation_count
    assert trend.documented_acquisition_hz == 5.0
    assert statistics.statistics.observation_count == dataset.runs[0].metadata.observation_count
    assert len(comparison.runs) == 2
    assert metrology.total_site_records == 7_832
    assert metrology.selected_wafer_count == 88
    assert "wafers=none" not in metrology.scope
    assert metrology.scope.count("2024-") == 88
    assert sum(item.post_etch_reconstructed_count for item in metrology.wafers) == 157
    assert any(item.source_file == "research/Readme.pdf" for item in trend.provenance.files)


@pytest.mark.integration
def test_actual_phm_analytics() -> None:
    dataset = load_phm_dataset(Path("data/external/phm_ion_mill_2018/compact"))

    features = phm_feature_inventory(dataset)
    faults = phm_fault_inventory(dataset)

    assert features.raw_observation_count == len(dataset.observations)
    assert features.exact_duplicate_count == 5
    assert len(features.features) == len(dataset.validation.features)
    assert faults.total_recorded_events == 19
    assert sum(item.count for item in faults.category_counts) == 19
