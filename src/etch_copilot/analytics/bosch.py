"""Readiness-gated deterministic analytics for the BOSCH research dataset."""

from __future__ import annotations

import numpy as np
import pandas as pd

from etch_copilot.analytics.contracts import (
    AnalyticsScopeError,
    BoschComparisonResult,
    BoschMetrologyCoverageResult,
    BoschStatisticsResult,
    BoschTrendResult,
    FileDigest,
    GroupMissingness,
    IntervalSummary,
    MissingFieldCount,
    RunStatistics,
    WaferCoverage,
)
from etch_copilot.analytics.policies import (
    AnalysisContextKwargs,
    analysis_context,
    authorize_bosch,
    json_numeric,
    numeric_statistics,
)
from etch_copilot.loaders import BoschDataset, BoschRunData
from etch_copilot.qualification import AnalysisId, ReadinessDecision, build_bosch_qualification

_METROLOGY_MEASUREMENT_FIELDS = (
    "preox_thickness",
    "postox_thickness_nan",
    "postox_thickness",
    "stepheight",
    "oxide_etch",
    "si_etch",
)
_MAX_TREND_POINTS = 100_000
_MAX_METROLOGY_SITE_RECORDS = 250_000
_MAX_COMPARISON_RUNS = 100
_MAX_METROLOGY_WAFERS = 1_000


def _run(dataset: BoschDataset, run_id: str) -> BoschRunData:
    return next(item for item in dataset.runs if item.metadata.run_id == run_id)


def _feature_semantics(dataset: BoschDataset, feature: str) -> tuple[str | None, bool]:
    qualification = build_bosch_qualification(dataset)
    entry = next(item for item in qualification.features.features if item.source_name == feature)
    return entry.engineering_unit, entry.unit_verified


def _context(dataset: BoschDataset, decision: ReadinessDecision) -> AnalysisContextKwargs:
    references = tuple(
        FileDigest(source_file=item.source_path, sha256=item.sha256)
        for item in dataset.scientific_references
        if item.verified
    )
    return analysis_context(decision, dataset.provenance, references)


def bosch_elapsed_trend(dataset: BoschDataset, run_id: str, feature: str) -> BoschTrendResult:
    """Return original run-local coordinates and source sensor values for plotting."""
    decision, dataset = authorize_bosch(
        dataset, AnalysisId.BOSCH_ELAPSED_TREND, run_ids=(run_id,), feature=feature
    )
    qualification = build_bosch_qualification(dataset)
    run = _run(dataset, run_id)
    if len(run.elapsed_time_s) > _MAX_TREND_POINTS:
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_ELAPSED_TREND,
            decision.scope,
            (f"trend output exceeds {_MAX_TREND_POINTS} source samples",),
        )
    coordinates = np.asarray(run.elapsed_time_s, dtype=np.float64)
    intervals = np.diff(coordinates)
    positive = intervals[intervals > 0]
    median = float(np.median(positive)) if positive.size else None
    discontinuity_threshold = median * 1.5 if median is not None else None
    discontinuities = (
        tuple(
            int(index)
            for index, value in enumerate(intervals)
            if discontinuity_threshold is not None and value > discontinuity_threshold
        )
        if intervals.size
        else ()
    )
    unit, unit_verified = _feature_semantics(dataset, feature)
    return BoschTrendResult(
        **_context(dataset, decision),
        run_id=run_id,
        feature=feature,
        engineering_unit=unit,
        unit_verified=unit_verified,
        coordinate_name="times",
        coordinate_unit="s",
        coordinate_semantics="run-local elapsed coordinate",
        documented_acquisition_hz=(
            5.0 if qualification.experimental_context.primary_reference_verified else None
        ),
        elapsed_coordinates=tuple(float(value) for value in coordinates),
        sensor_values=json_numeric(pd.to_numeric(run.values[feature], errors="coerce")),
        interval_summary=IntervalSummary(
            interval_count=int(intervals.size),
            minimum_interval_s=float(np.min(intervals)) if intervals.size else None,
            median_interval_s=float(np.median(intervals)) if intervals.size else None,
            maximum_interval_s=float(np.max(intervals)) if intervals.size else None,
            discontinuity_after_indices=discontinuities,
            non_positive_interval_count=int((intervals <= 0).sum()),
        ),
    )


def bosch_sensor_statistics(
    dataset: BoschDataset, run_id: str, feature: str
) -> BoschStatisticsResult:
    """Calculate finite-only descriptive statistics for one source channel and run."""
    decision, dataset = authorize_bosch(
        dataset,
        AnalysisId.BOSCH_SENSOR_DESCRIPTIVE,
        run_ids=(run_id,),
        feature=feature,
    )
    run = _run(dataset, run_id)
    unit, unit_verified = _feature_semantics(dataset, feature)
    return BoschStatisticsResult(
        **_context(dataset, decision),
        run_id=run_id,
        feature=feature,
        engineering_unit=unit,
        unit_verified=unit_verified,
        statistics=numeric_statistics(run.values[feature]),
    )


def bosch_compare_runs(
    dataset: BoschDataset, run_ids: tuple[str, ...], feature: str
) -> BoschComparisonResult:
    """Return side-by-side summaries without pooling runs or claiming a baseline."""
    if len(run_ids) > _MAX_COMPARISON_RUNS:
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_CROSS_RUN_COMPARISON,
            "runs=oversized",
            (f"cross-run comparison exceeds {_MAX_COMPARISON_RUNS} runs",),
        )
    if len(set(run_ids)) != len(run_ids):
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_CROSS_RUN_COMPARISON,
            f"runs={','.join(run_ids)}",
            ("cross-run comparison does not accept duplicate run IDs",),
        )
    decision, dataset = authorize_bosch(
        dataset,
        AnalysisId.BOSCH_CROSS_RUN_COMPARISON,
        run_ids=run_ids,
        feature=feature,
    )
    unit, unit_verified = _feature_semantics(dataset, feature)
    return BoschComparisonResult(
        **_context(dataset, decision),
        feature=feature,
        engineering_unit=unit,
        unit_verified=unit_verified,
        runs=tuple(
            RunStatistics(
                run_id=run_id,
                statistics=numeric_statistics(_run(dataset, run_id).values[feature]),
            )
            for run_id in run_ids
        ),
        interpretation_policy=(
            "Side-by-side source-channel summaries only; runs are not pooled, ranked, or used "
            "as a qualified manufacturing baseline."
        ),
    )


def _missing_fields(frame: pd.DataFrame) -> tuple[MissingFieldCount, ...]:
    return tuple(
        MissingFieldCount(field=field, missing_count=int(frame[field].isna().sum()))
        for field in _METROLOGY_MEASUREMENT_FIELDS
    )


def bosch_metrology_coverage(
    dataset: BoschDataset, wafer_keys: tuple[str, ...] | None = None
) -> BoschMetrologyCoverageResult:
    """Inventory metrology coverage and documented reconstruction, without derived metrics."""
    if wafer_keys == ():
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_SPATIAL_METROLOGY,
            "wafers=none",
            ("Metrology coverage requires at least one wafer or an omitted all-wafer scope",),
        )
    if wafer_keys is not None and len(wafer_keys) > _MAX_METROLOGY_WAFERS:
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_SPATIAL_METROLOGY,
            "wafers=oversized",
            (f"metrology scope exceeds {_MAX_METROLOGY_WAFERS} wafers",),
        )
    if wafer_keys is not None and len(set(wafer_keys)) != len(wafer_keys):
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_SPATIAL_METROLOGY,
            f"wafers={','.join(wafer_keys)}",
            ("metrology scope does not accept duplicate wafer keys",),
        )
    decision, dataset = authorize_bosch(
        dataset,
        AnalysisId.BOSCH_SPATIAL_METROLOGY,
        wafer_keys=wafer_keys,
    )
    selected_keys = (
        tuple(sorted(set(dataset.metrology["experiment_key"].astype(str))))
        if wafer_keys is None
        else wafer_keys
    )
    qualification = build_bosch_qualification(dataset)
    reconstruction_verified = (
        qualification.experimental_context.primary_reference_verified
        and qualification.experimental_context.pre_etch_values_were_interpolated is True
        and qualification.experimental_context.post_etch_missing_values_were_interpolated is True
    )
    qualified = {item.experiment_key: item for item in qualification.metrology.wafers}
    selected = dataset.metrology[
        dataset.metrology["experiment_key"].astype(str).isin(selected_keys)
    ].copy()
    if len(selected) > _MAX_METROLOGY_SITE_RECORDS:
        raise AnalyticsScopeError(
            AnalysisId.BOSCH_SPATIAL_METROLOGY,
            decision.scope,
            (f"metrology output exceeds {_MAX_METROLOGY_SITE_RECORDS} site records",),
        )
    wafers: list[WaferCoverage] = []
    for key, frame in selected.groupby("experiment_key", sort=True):
        wafer = qualified[str(key)]
        raw_post = frame["postox_thickness_nan"]
        filled_post = frame["postox_thickness"]
        wafers.append(
            WaferCoverage(
                experiment_key=str(key),
                run_id=wafer.run_id,
                lot_number=int(frame["lot_number"].iloc[0]),
                wafer_number=int(frame["wafer_number"].iloc[0]),
                site_record_count=len(frame),
                unique_position_count=len(frame[["X", "Y"]].drop_duplicates()),
                expected_site_count=wafer.expected_site_count,
                relationship_unambiguous=wafer.relationship_unambiguous,
                pre_etch_direct_count=0,
                pre_etch_reconstructed_count=(
                    int(frame["preox_thickness"].notna().sum()) if reconstruction_verified else 0
                ),
                pre_etch_unclassified_count=(
                    0 if reconstruction_verified else int(frame["preox_thickness"].notna().sum())
                ),
                post_etch_direct_count=int(raw_post.notna().sum())
                if reconstruction_verified
                else 0,
                post_etch_reconstructed_count=(
                    int((raw_post.isna() & filled_post.notna()).sum())
                    if reconstruction_verified
                    else 0
                ),
                post_etch_unclassified_count=(
                    0 if reconstruction_verified else int(filled_post.notna().sum())
                ),
                missing_fields=_missing_fields(frame),
            )
        )
    by_lot = tuple(
        GroupMissingness(
            group_key=str(lot), record_count=len(frame), missing_fields=_missing_fields(frame)
        )
        for lot, frame in selected.groupby("lot_number", sort=True)
    )
    return BoschMetrologyCoverageResult(
        **_context(dataset, decision),
        total_site_records=len(selected),
        selected_wafer_count=len(wafers),
        measurement_unit=qualification.metrology.measurement_unit,
        unit_verified=qualification.metrology.measurement_unit_verified,
        wafers=tuple(wafers),
        missingness_by_lot=by_lot,
        data_quality_issues=tuple(
            f"{issue.code}: {issue.message}" for issue in dataset.validation.issues
        ),
        reconstruction_policy=(
            "Pre-etch values at the 89 output sites are reconstructed from 15 direct points; "
            "the supplied file does not identify those original 15 rows.",
            "postox_thickness_nan is the direct post-etch field; a non-null filled value where "
            "that field is null is counted as reconstructed.",
            "No interpolation or metrology-derived engineering calculation is performed.",
        ),
    )
