"""Deterministic engineering qualification and analysis-readiness policies."""

from __future__ import annotations

import re
from enum import StrEnum

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from etch_copilot.loaders import BoschDataset, PhmDataset
from etch_copilot.models import DatasetProvenance

QUALIFICATION_ENGINE_VERSION = "1.0.0"
EXPECTED_BOSCH_SITE_COUNT = 89


class FrozenModel(BaseModel):
    """Immutable base for integrity-critical qualification contracts."""

    model_config = ConfigDict(frozen=True)


class ReadinessStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    LIMITED = "LIMITED"
    BLOCKED = "BLOCKED"


class AnalysisId(StrEnum):
    BOSCH_SENSOR_DESCRIPTIVE = "bosch.sensor_descriptive_statistics"
    BOSCH_SENSOR_VARIABILITY = "bosch.within_run_sensor_variability"
    BOSCH_ELAPSED_TREND = "bosch.elapsed_process_trend"
    BOSCH_CROSS_RUN_COMPARISON = "bosch.cross_run_sensor_comparison"
    BOSCH_WAFER_THICKNESS_DESCRIPTIVE = "bosch.wafer_thickness_descriptive"
    BOSCH_SPATIAL_METROLOGY = "bosch.spatial_wafer_metrology"
    BOSCH_WAFER_UNIFORMITY = "bosch.wafer_uniformity"
    BOSCH_ETCH_RATE = "bosch.etch_rate"
    BOSCH_BASELINE_ELIGIBILITY = "bosch.baseline_eligibility"
    BOSCH_SPC_CONTROL_LIMITS = "bosch.spc_control_limits"
    BOSCH_CALENDAR_EVENT_CORRELATION = "bosch.calendar_event_correlation"
    PHM_SENSOR_DESCRIPTIVE = "phm.sensor_descriptive_statistics"
    PHM_FEATURE_AVAILABILITY = "phm.sensor_feature_availability"
    PHM_TIME_SERIES = "phm.sensor_time_series"
    PHM_FAULT_EVENT_INVENTORY = "phm.fault_event_inventory"
    PHM_EVENT_CENTERED_COMPARISON = "phm.event_centered_sensor_comparison"
    PHM_FAULT_PRECEDING_SIGNALS = "phm.fault_preceding_signal_investigation"
    PHM_TEMPORAL_FAULT_DETECTION = "phm.temporal_fault_detection"
    PHM_FALSE_ALARM_RATE = "phm.unbiased_false_alarm_rate"


class EvidenceReference(FrozenModel):
    dataset_id: str
    source_file: str
    sha256: str
    evidence_type: str
    locator: str
    verification_method: str


class ReadinessDecision(FrozenModel):
    dataset_id: str
    analysis_id: AnalysisId
    scope: str
    status: ReadinessStatus
    evidence: tuple[EvidenceReference, ...]
    missing_requirements: tuple[str, ...] = ()
    blocking_issues: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    validation_rules: tuple[str, ...]
    requires_scope_qualification: bool = False
    scope_qualified: bool = True
    engine_version: str = QUALIFICATION_ENGINE_VERSION


class BoschTimeContract(FrozenModel):
    source_coordinate_name: str
    source_units_attribute: str | None
    source_calendar_attribute: str | None
    elapsed_time_verified: bool
    elapsed_time_unit: str | None
    absolute_time_verified: bool
    coordinates_are_run_local: bool
    coordinate_resets_between_runs: bool
    monotonically_increasing_runs: int
    run_count: int
    sample_interval_s: float | None
    regular_sampling_runs: int
    recording_span_eligible: bool
    exact_etch_duration_verified: bool
    permitted_uses: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    unresolved_issues: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]


class WaferMetrologyQualification(FrozenModel):
    experiment_key: str
    run_id: str | None
    expected_site_count: int
    observed_site_count: int
    unique_position_count: int
    complete_spatial_coverage: bool
    missing_raw_post_thickness_sites: int
    relationship_unambiguous: bool
    calculation_eligible: bool
    blocking_reasons: tuple[str, ...]


class BoschMetrologyContract(FrozenModel):
    process_run_count: int
    metrology_wafer_count: int
    total_site_records: int
    expected_sites_per_wafer: int
    complete_wafer_count: int
    partial_wafer_count: int
    runs_without_metrology: tuple[str, ...]
    metrology_without_runs: tuple[str, ...]
    missing_raw_post_thickness_sites: int
    measurement_unit: str | None
    measurement_unit_verified: bool
    position_unit: str | None
    position_unit_verified: bool
    pre_post_directly_comparable: bool
    wafers: tuple[WaferMetrologyQualification, ...]
    missing_data_policy: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]


class SensorFeatureQualification(FrozenModel):
    source_name: str
    normalized_name: str | None
    available_run_ids: tuple[str, ...]
    available_run_count: int
    common_to_all_runs: bool
    engineering_unit: str | None
    unit_verified: bool


class BoschFeatureRegistry(FrozenModel):
    run_count: int
    common_feature_count: int
    total_feature_count: int
    feature_count_distribution: dict[int, int]
    features: tuple[SensorFeatureQualification, ...]
    absent_feature_policy: str
    evidence: tuple[EvidenceReference, ...]


class EquipmentIdMapping(FrozenModel):
    source_ids: tuple[str, ...]
    canonical_id: str
    mapping_source: str
    verified: bool
    reversible: bool


class IdentifierContract(FrozenModel):
    equipment_mappings: tuple[EquipmentIdMapping, ...]
    unknown_mapping_policy: str


class DuplicatePolicy(FrozenModel):
    definition: str
    exact_duplicate_count: int
    duplicate_rows_share_timestamp: bool
    raw_records_preserved: bool
    removal_mode: str
    statistical_consequence: str


class PhmTimeContract(FrozenModel):
    coordinate_name: str
    coordinate_comparable: bool
    unit: str | None
    unit_verified: bool
    origin: str | None
    timezone: str | None
    event_semantics: str
    extraction_bias: str
    permitted_uses: tuple[str, ...]
    blocked_uses: tuple[str, ...]
    evidence: tuple[EvidenceReference, ...]


class EventCoordinateCoverage(FrozenModel):
    event_index: int
    equipment_id: str
    fault_name: str
    event_coordinate: int
    coordinate_unit: str | None
    exact_match: bool
    previous_coordinate: int | None
    following_coordinate: int | None
    nearest_distance: int | None
    pre_event_observation_available: bool
    post_event_observation_available: bool
    coverage_status: str
    fault_semantics: str = "recorded_equipment_event"


class BoschQualification(FrozenModel):
    dataset_id: str
    engine_version: str
    provenance: DatasetProvenance
    time: BoschTimeContract
    metrology: BoschMetrologyContract
    features: BoschFeatureRegistry
    readiness: tuple[ReadinessDecision, ...]

    def decision(self, analysis_id: AnalysisId) -> ReadinessDecision:
        return next(item for item in self.readiness if item.analysis_id == analysis_id)


class PhmQualification(FrozenModel):
    dataset_id: str
    engine_version: str
    provenance: DatasetProvenance
    time: PhmTimeContract
    identifiers: IdentifierContract
    duplicates: DuplicatePolicy
    event_coverage: tuple[EventCoordinateCoverage, ...]
    readiness: tuple[ReadinessDecision, ...]

    def decision(self, analysis_id: AnalysisId) -> ReadinessDecision:
        return next(item for item in self.readiness if item.analysis_id == analysis_id)


class AnalysisBlockedError(RuntimeError):
    """Raised when downstream code attempts a blocked analysis."""


class AnalysisLimitedError(RuntimeError):
    """Raised when a limited analysis was not explicitly accepted."""


def assert_analysis_permitted(decision: ReadinessDecision, *, allow_limited: bool = False) -> None:
    """Enforce a qualification decision before scientific calculation."""
    if decision.requires_scope_qualification and not decision.scope_qualified:
        raise AnalysisBlockedError(
            f"Analysis {decision.analysis_id} requires run/wafer/feature scope qualification"
        )
    if decision.status is ReadinessStatus.BLOCKED:
        raise AnalysisBlockedError(
            f"Analysis {decision.analysis_id} is blocked: {', '.join(decision.blocking_issues)}"
        )
    if decision.status is ReadinessStatus.LIMITED and not allow_limited:
        raise AnalysisLimitedError(
            f"Analysis {decision.analysis_id} is limited; explicit acceptance is required"
        )


def _evidence(
    dataset: BoschDataset | PhmDataset,
    source_file: str,
    evidence_type: str,
    locator: str,
    method: str,
) -> EvidenceReference:
    return EvidenceReference(
        dataset_id=dataset.provenance.dataset_id,
        source_file=source_file,
        sha256=dataset.provenance.sha256[source_file],
        evidence_type=evidence_type,
        locator=locator,
        verification_method=method,
    )


def _decision(
    dataset_id: str,
    analysis_id: AnalysisId,
    status: ReadinessStatus,
    evidence: tuple[EvidenceReference, ...],
    *,
    missing: tuple[str, ...] = (),
    blocking: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    rules: tuple[str, ...],
    requires_scope: bool = False,
) -> ReadinessDecision:
    return ReadinessDecision(
        dataset_id=dataset_id,
        analysis_id=analysis_id,
        scope="dataset; refine by run, wafer, and feature before execution",
        status=status,
        evidence=evidence,
        missing_requirements=missing,
        blocking_issues=blocking,
        limitations=limitations,
        validation_rules=rules,
        requires_scope_qualification=requires_scope,
        scope_qualified=not requires_scope,
    )


def _bosch_time_contract(dataset: BoschDataset) -> BoschTimeContract:
    intervals: list[float] = []
    monotonic = 0
    regular = 0
    for run in dataset.runs:
        differences = np.diff(run.elapsed_time_s)
        if np.all(differences > 0):
            monotonic += 1
        if len(differences):
            intervals.extend(float(value) for value in differences)
            if np.allclose(differences, 0.2, rtol=0, atol=1e-5):
                regular += 1
    median_interval = float(np.median(intervals)) if intervals else None
    unit_values = {
        str(run.metadata.extra.get("source_time_units"))
        for run in dataset.runs
        if run.metadata.extra.get("source_time_units")
    }
    calendar_values = {
        str(run.metadata.extra.get("source_time_calendar"))
        for run in dataset.runs
        if run.metadata.extra.get("source_time_calendar")
    }
    start_values = [float(run.elapsed_time_s[0]) for run in dataset.runs if len(run.elapsed_time_s)]
    coordinate_resets = len(set(start_values)) > 1 and max(start_values, default=0) < 1_000
    source_units = next(iter(unit_values)) if len(unit_values) == 1 else None
    source_calendar = next(iter(calendar_values)) if len(calendar_values) == 1 else None
    elapsed_verified = (
        bool(dataset.runs)
        and all(len(run.elapsed_time_s) > 1 for run in dataset.runs)
        and monotonic == len(dataset.runs)
        and source_units is not None
        and source_units.lower().startswith("seconds")
        and median_interval is not None
        and median_interval > 0
    )
    netcdf_evidence = _evidence(
        dataset,
        "Process_data.nc",
        "observed_data_and_metadata",
        "all wafer groups: times coordinate and units attribute",
        "inspected monotonicity, range, per-run reset behavior, and sampling deltas",
    )
    evidence_items = [netcdf_evidence]
    if "Readme.pdf" in dataset.provenance.sha256:
        evidence_items.append(
            _evidence(
                dataset,
                "Readme.pdf",
                "source_documentation",
                "section 2.2 Process Parameters",
                "documented 5 Hz acquisition and per-wafer NetCDF groups",
            )
        )
    evidence = tuple(evidence_items)
    return BoschTimeContract(
        source_coordinate_name="times",
        source_units_attribute=source_units,
        source_calendar_attribute=source_calendar,
        elapsed_time_verified=elapsed_verified,
        elapsed_time_unit="s" if elapsed_verified else None,
        absolute_time_verified=False,
        coordinates_are_run_local=True,
        coordinate_resets_between_runs=coordinate_resets,
        monotonically_increasing_runs=monotonic,
        run_count=len(dataset.runs),
        sample_interval_s=median_interval,
        regular_sampling_runs=regular,
        recording_span_eligible=elapsed_verified,
        exact_etch_duration_verified=False,
        permitted_uses=(
            "within-run elapsed-coordinate trends",
            "within-run recording span as last coordinate minus first coordinate",
        ),
        blocked_uses=("absolute calendar ordering", "calendar-time event correlation"),
        unresolved_issues=(
            "CF-style epoch metadata contradicts short run-local coordinate magnitudes.",
            "Absolute process start timestamps are not supplied.",
            "The exact etch interval within each recording is not identified by a verified marker.",
        ),
        evidence=evidence,
    )


def _bosch_metrology_contract(dataset: BoschDataset) -> BoschMetrologyContract:
    frame = dataset.metrology
    run_ids_by_key: dict[str, list[str]] = {}
    for run in dataset.runs:
        if run.metadata.wafer_id is not None:
            run_ids_by_key.setdefault(run.metadata.wafer_id, []).append(run.metadata.run_id)
    lot_by_date: dict[str, int] = {}
    for row in dataset.lot_status.itertuples(index=False, name=None):
        lot_text, date_text = row[0], row[1]
        lot_match = re.fullmatch(r"Lot\s+(\d+)", str(lot_text).strip())
        if lot_match is None or date_text is None:
            continue
        clean_date = re.sub(r"(?<=\d)(st|nd|rd|th)", "", str(date_text), flags=re.I)
        parsed_date = pd.to_datetime(clean_date, dayfirst=True, errors="coerce")
        if not pd.isna(parsed_date):
            lot_by_date[parsed_date.strftime("%Y-%m-%d")] = int(lot_match.group(1))
    wafers: list[WaferMetrologyQualification] = []
    for experiment_key, group in frame.groupby("experiment_key", sort=True):
        matching_runs = run_ids_by_key.get(str(experiment_key), [])
        run_id = matching_runs[0] if len(matching_runs) == 1 else None
        unique_positions = len(group[["X", "Y"]].drop_duplicates())
        missing_raw = int(group["postox_thickness_nan"].isna().sum())
        suffix = re.search(r"_(\d+)$", str(experiment_key))
        suffix_matches = False
        if suffix is not None and group["wafer_number"].nunique() == 1:
            suffix_matches = int(group["wafer_number"].iloc[0]) == int(suffix.group(1))
        date_key = str(experiment_key).split("_", maxsplit=1)[0]
        expected_lot = lot_by_date.get(date_key)
        lot_matches = (
            expected_lot is not None
            and group["lot_number"].nunique() == 1
            and int(group["lot_number"].iloc[0]) == expected_lot
        )
        unambiguous = run_id is not None and suffix_matches and lot_matches
        complete = len(group) == EXPECTED_BOSCH_SITE_COUNT and unique_positions == len(group)
        reasons: list[str] = []
        if run_id is None:
            if len(matching_runs) > 1:
                reasons.append("multiple matching process runs")
            else:
                reasons.append("no matching process run")
        if not suffix_matches:
            reasons.append("wafer identifier mismatch")
        if not complete:
            reasons.append("partial or duplicate spatial coverage")
        if not lot_matches:
            reasons.append("lot/date relationship mismatch")
        if missing_raw:
            reasons.append("raw post-etch thickness is missing at one or more sites")
        reasons.append("89-point metrology engineering units are not unambiguously documented")
        wafers.append(
            WaferMetrologyQualification(
                experiment_key=str(experiment_key),
                run_id=run_id,
                expected_site_count=EXPECTED_BOSCH_SITE_COUNT,
                observed_site_count=len(group),
                unique_position_count=unique_positions,
                complete_spatial_coverage=complete,
                missing_raw_post_thickness_sites=missing_raw,
                relationship_unambiguous=unambiguous,
                calculation_eligible=False,
                blocking_reasons=tuple(reasons),
            )
        )
    run_keys = set(run_ids_by_key)
    metrology_keys = set(frame["experiment_key"].astype(str))
    evidence_items = [
        _evidence(
            dataset,
            "Si_Oxide_etch_89_points.csv",
            "observed_data",
            "experiment_key, wafer_number, X, Y, thickness columns",
            "grouped by experiment key and checked join cardinality, positions, and nulls",
        )
    ]
    if "Readme.pdf" in dataset.provenance.sha256:
        evidence_items.append(
            _evidence(
                dataset,
                "Readme.pdf",
                "source_documentation",
                "section 2.3.2 Measurement of 89 Points",
                "reviewed measurement and interpolation description",
            )
        )
    evidence = tuple(evidence_items)
    return BoschMetrologyContract(
        process_run_count=len(dataset.runs),
        metrology_wafer_count=len(wafers),
        total_site_records=len(frame),
        expected_sites_per_wafer=EXPECTED_BOSCH_SITE_COUNT,
        complete_wafer_count=sum(item.complete_spatial_coverage for item in wafers),
        partial_wafer_count=sum(not item.complete_spatial_coverage for item in wafers),
        runs_without_metrology=tuple(sorted(run_keys - metrology_keys)),
        metrology_without_runs=tuple(sorted(metrology_keys - run_keys)),
        missing_raw_post_thickness_sites=int(frame["postox_thickness_nan"].isna().sum()),
        measurement_unit=None,
        measurement_unit_verified=False,
        position_unit=None,
        position_unit_verified=False,
        pre_post_directly_comparable=False,
        wafers=tuple(wafers),
        missing_data_policy=(
            "Never replace a missing site with zero or an unflagged aggregate.",
            "Treat fewer than 89 unique positions as partial spatial coverage.",
            "Do not use interpolated post-etch values as raw measurements without a flag.",
            "Block calculations for ambiguous wafer/run joins or invalid durations.",
            "Do not interpolate spatial measurements in Phase 1.5.",
        ),
        evidence=evidence,
    )


def _bosch_feature_registry(dataset: BoschDataset) -> BoschFeatureRegistry:
    run_features = {run.metadata.run_id: set(run.values.columns) for run in dataset.runs}
    all_features = set().union(*run_features.values()) if run_features else set()
    common_features = set.intersection(*run_features.values()) if run_features else set()
    entries = tuple(
        SensorFeatureQualification(
            source_name=feature,
            normalized_name=None,
            available_run_ids=tuple(
                sorted(run_id for run_id, features in run_features.items() if feature in features)
            ),
            available_run_count=sum(feature in features for features in run_features.values()),
            common_to_all_runs=feature in common_features,
            engineering_unit=None,
            unit_verified=False,
        )
        for feature in sorted(all_features)
    )
    distribution: dict[int, int] = {}
    for features in run_features.values():
        distribution[len(features)] = distribution.get(len(features), 0) + 1
    return BoschFeatureRegistry(
        run_count=len(dataset.runs),
        common_feature_count=len(common_features),
        total_feature_count=len(all_features),
        feature_count_distribution=distribution,
        features=entries,
        absent_feature_policy=(
            "Absent channels remain unavailable; never replace absence with zero."
        ),
        evidence=(
            _evidence(
                dataset,
                "Process_data.nc",
                "observed_schema",
                "feature coordinate in every wafer group",
                "computed per-run feature sets, union, and intersection",
            ),
        ),
    )


def build_bosch_qualification(dataset: BoschDataset) -> BoschQualification:
    time = _bosch_time_contract(dataset)
    metrology = _bosch_metrology_contract(dataset)
    features = _bosch_feature_registry(dataset)
    sensor_evidence = features.evidence + time.evidence
    metrology_evidence = metrology.evidence
    dataset_id = dataset.provenance.dataset_id
    readiness = (
        _decision(
            dataset_id,
            AnalysisId.BOSCH_SENSOR_DESCRIPTIVE,
            ReadinessStatus.LIMITED,
            sensor_evidence,
            limitations=("Results remain in undocumented source units.",),
            rules=("BOSCH-FEATURE-001", "UNIT-UNKNOWN-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_SENSOR_VARIABILITY,
            ReadinessStatus.LIMITED,
            sensor_evidence,
            limitations=("Compare only the same source channel within a run.",),
            rules=("BOSCH-FEATURE-001", "UNIT-UNKNOWN-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_ELAPSED_TREND,
            ReadinessStatus.SUPPORTED if time.elapsed_time_verified else ReadinessStatus.BLOCKED,
            time.evidence,
            missing=()
            if time.elapsed_time_verified
            else ("verified monotonic seconds coordinate",),
            blocking=() if time.elapsed_time_verified else ("elapsed-time contract failed",),
            rules=("BOSCH-TIME-ELAPSED-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_CROSS_RUN_COMPARISON,
            ReadinessStatus.LIMITED,
            sensor_evidence,
            limitations=("Require the identical source feature in every selected run.",),
            rules=("BOSCH-FEATURE-INTERSECTION-001",),
            requires_scope=True,
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_WAFER_THICKNESS_DESCRIPTIVE,
            ReadinessStatus.LIMITED,
            metrology_evidence,
            limitations=("Report only source-scale values and missingness.",),
            rules=("BOSCH-METROLOGY-MISSING-001", "UNIT-UNKNOWN-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_SPATIAL_METROLOGY,
            ReadinessStatus.LIMITED,
            metrology_evidence,
            limitations=("Coordinates and thickness remain in source scale.",),
            rules=("BOSCH-METROLOGY-COVERAGE-001", "UNIT-UNKNOWN-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_WAFER_UNIFORMITY,
            ReadinessStatus.BLOCKED,
            metrology_evidence,
            missing=("verified thickness unit", "complete valid sites"),
            blocking=("measurement semantics and interpolation flags are not fully qualified",),
            rules=("BOSCH-METROLOGY-CALC-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_ETCH_RATE,
            ReadinessStatus.BLOCKED,
            metrology_evidence + time.evidence,
            missing=("verified thickness unit", "validated etch interval for each wafer"),
            blocking=("metrology units and exact etch-duration semantics remain unresolved",),
            rules=("BOSCH-METROLOGY-CALC-001", "BOSCH-TIME-DURATION-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_BASELINE_ELIGIBILITY,
            ReadinessStatus.BLOCKED,
            metrology_evidence,
            missing=("qualified stable production baseline designation",),
            blocking=("research DOE runs are not qualified production baselines",),
            rules=("BASELINE-QUALIFICATION-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_SPC_CONTROL_LIMITS,
            ReadinessStatus.BLOCKED,
            metrology_evidence,
            missing=("qualified baseline", "eligible run metric"),
            blocking=("baseline eligibility is not established",),
            rules=("SPC-PREREQUISITE-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.BOSCH_CALENDAR_EVENT_CORRELATION,
            ReadinessStatus.BLOCKED,
            time.evidence,
            missing=("trusted absolute process timestamps",),
            blocking=("only run-local elapsed coordinates are qualified",),
            rules=("BOSCH-TIME-ABSOLUTE-001",),
        ),
    )
    return BoschQualification(
        dataset_id=dataset_id,
        engine_version=QUALIFICATION_ENGINE_VERSION,
        provenance=dataset.provenance,
        time=time,
        metrology=metrology,
        features=features,
        readiness=readiness,
    )


def qualify_bosch_scope(
    qualification: BoschQualification,
    analysis_id: AnalysisId,
    *,
    run_ids: tuple[str, ...] = (),
    wafer_keys: tuple[str, ...] = (),
    feature: str | None = None,
) -> ReadinessDecision:
    """Refine dataset readiness for selected runs, wafers, and a source feature."""
    base = qualification.decision(analysis_id)
    blockers = list(base.blocking_issues)
    if analysis_id is AnalysisId.BOSCH_CROSS_RUN_COMPARISON:
        if len(set(run_ids)) < 2:
            blockers.append("cross-run comparison requires at least two distinct run IDs")
        if feature is None:
            blockers.append("cross-run comparison requires one verified source feature")
    all_run_ids = {
        run_id for item in qualification.features.features for run_id in item.available_run_ids
    }
    unknown_runs = sorted(set(run_ids) - all_run_ids)
    if unknown_runs:
        blockers.append(f"unknown run IDs: {', '.join(unknown_runs)}")
    if feature is not None:
        feature_entry = next(
            (item for item in qualification.features.features if item.source_name == feature), None
        )
        if feature_entry is None:
            blockers.append(f"unknown source feature: {feature}")
        else:
            absent = sorted(set(run_ids) - set(feature_entry.available_run_ids))
            if absent:
                blockers.append(f"feature is absent from selected runs: {', '.join(absent)}")
    wafer_by_key = {item.experiment_key: item for item in qualification.metrology.wafers}
    for wafer_key in wafer_keys:
        wafer = wafer_by_key.get(wafer_key)
        if wafer is None:
            blockers.append(f"unknown wafer key: {wafer_key}")
        elif not wafer.relationship_unambiguous:
            blockers.append(f"wafer/run relationship is ambiguous: {wafer_key}")
    status = ReadinessStatus.BLOCKED if blockers else base.status
    scope_parts = [
        f"runs={','.join(run_ids) if run_ids else 'none'}",
        f"wafers={','.join(wafer_keys) if wafer_keys else 'none'}",
        f"feature={feature or 'none'}",
    ]
    return base.model_copy(
        update={
            "scope": "; ".join(scope_parts),
            "status": status,
            "blocking_issues": tuple(blockers),
            "scope_qualified": not blockers,
        }
    )


def _phm_identifier_contract(dataset: PhmDataset) -> IdentifierContract:
    observed = tuple(sorted(set(dataset.observations["Tool"].astype(str))))
    manifest_id = dataset.manifest.get("selected_equipment_id")
    mappings: list[EquipmentIdMapping] = []
    mapped_sources: set[str] = set()
    if isinstance(manifest_id, str):
        canonical_manifest = manifest_id.replace("_", "")
        matching_observed = tuple(
            value for value in observed if value.replace("_", "") == canonical_manifest
        )
        if len(matching_observed) == 1:
            source_ids = tuple(sorted({manifest_id, *matching_observed}))
            mappings.append(
                EquipmentIdMapping(
                    source_ids=source_ids,
                    canonical_id=canonical_manifest,
                    mapping_source=(
                        "dataset_manifest.json selected_equipment_id and retained Tool values"
                    ),
                    verified=True,
                    reversible=True,
                )
            )
            mapped_sources.update(source_ids)
    for source_id in observed:
        if source_id not in mapped_sources:
            mappings.append(
                EquipmentIdMapping(
                    source_ids=(source_id,),
                    canonical_id=source_id,
                    mapping_source="identity mapping from retained Tool value",
                    verified=True,
                    reversible=True,
                )
            )
    return IdentifierContract(
        equipment_mappings=tuple(mappings),
        unknown_mapping_policy=(
            "Return unresolved; never normalize an identifier without a verified mapping."
        ),
    )


def canonicalize_phm_equipment_id(source_id: str, contract: IdentifierContract) -> str | None:
    for mapping in contract.equipment_mappings:
        if mapping.verified and source_id in mapping.source_ids:
            return mapping.canonical_id
    return None


def _phm_duplicate_policy(dataset: PhmDataset) -> DuplicatePolicy:
    duplicate_mask = dataset.observations.duplicated(keep="first")
    return DuplicatePolicy(
        definition="All retained columns are exactly equal; later occurrences are duplicates.",
        exact_duplicate_count=int(duplicate_mask.sum()),
        duplicate_rows_share_timestamp=True,
        raw_records_preserved=True,
        removal_mode="analytical_view_only",
        statistical_consequence=(
            "Including exact repeats gives repeated source rows extra weight in summaries."
        ),
    )


def phm_analytical_view(dataset: PhmDataset) -> tuple[pd.DataFrame, DuplicatePolicy]:
    policy = _phm_duplicate_policy(dataset)
    return dataset.observations.drop_duplicates(keep="first").copy(), policy


def event_coordinate_coverage(dataset: PhmDataset) -> tuple[EventCoordinateCoverage, ...]:
    identifiers = _phm_identifier_contract(dataset)
    results: list[EventCoordinateCoverage] = []
    for index, event in enumerate(dataset.faults):
        canonical_event = canonicalize_phm_equipment_id(event.equipment_id, identifiers)
        matching_tools = [
            tool
            for tool in sorted(set(dataset.observations["Tool"].astype(str)))
            if tool == event.equipment_id
            or (
                canonical_event is not None
                and canonicalize_phm_equipment_id(tool, identifiers) == canonical_event
            )
        ]
        equipment_rows = dataset.observations[
            dataset.observations["Tool"].astype(str).isin(matching_tools)
        ]
        coordinates = np.sort(equipment_rows["time"].astype("int64").unique())
        position = int(np.searchsorted(coordinates, event.event_time))
        exact = position < len(coordinates) and int(coordinates[position]) == event.event_time
        previous = int(coordinates[position - 1]) if position > 0 else None
        following_index = position + 1 if exact else position
        following = (
            int(coordinates[following_index]) if following_index < len(coordinates) else None
        )
        nearest: int | None
        if exact:
            nearest = 0
        else:
            distances = [
                abs(event.event_time - value)
                for value in (previous, following)
                if value is not None
            ]
            nearest = min(distances) if distances else None
        if exact:
            coverage_status = "exact_coordinate_match"
        elif previous is not None and following is not None:
            coverage_status = "bracketed_in_source_coordinate"
        elif previous is not None or following is not None:
            coverage_status = "one_sided_source_coordinate"
        else:
            coverage_status = "unsupported"
        results.append(
            EventCoordinateCoverage(
                event_index=index,
                equipment_id=event.equipment_id,
                fault_name=event.fault_name,
                event_coordinate=event.event_time,
                coordinate_unit=None,
                exact_match=exact,
                previous_coordinate=previous,
                following_coordinate=following,
                nearest_distance=nearest,
                pre_event_observation_available=previous is not None,
                post_event_observation_available=following is not None,
                coverage_status=coverage_status,
            )
        )
    return tuple(results)


def build_phm_qualification(dataset: PhmDataset) -> PhmQualification:
    time_evidence = (
        _evidence(
            dataset,
            "equipment_sensor_data.parquet",
            "observed_data",
            "time column",
            "checked ordering, coordinate range, gaps, and event proximity",
        ),
        _evidence(
            dataset,
            "fault_events.csv",
            "observed_event_data",
            "time and fault_name columns",
            "preserved event labels and compared raw coordinate values",
        ),
        _evidence(
            dataset,
            "dataset_manifest.json",
            "extraction_metadata",
            "sampling_strategy",
            "reviewed fault-centered extraction and equipment mapping",
        ),
    )
    time = PhmTimeContract(
        coordinate_name="time",
        coordinate_comparable=True,
        unit=None,
        unit_verified=False,
        origin=None,
        timezone=None,
        event_semantics="recorded equipment event or shutdown; not verified fault onset",
        extraction_bias=(
            "30-minute pre-event and 10-minute post-event windows plus a deterministic "
            "2% background sample"
        ),
        permitted_uses=("raw-coordinate ordering", "event inventory", "nearest coordinate lookup"),
        blocked_uses=(
            "duration-based event windows",
            "fault onset labeling",
            "calendar-time analysis",
        ),
        evidence=time_evidence,
    )
    identifiers = _phm_identifier_contract(dataset)
    duplicates = _phm_duplicate_policy(dataset)
    coverage = event_coordinate_coverage(dataset)
    dataset_id = dataset.provenance.dataset_id
    readiness = (
        _decision(
            dataset_id,
            AnalysisId.PHM_SENSOR_DESCRIPTIVE,
            ReadinessStatus.LIMITED,
            time_evidence,
            limitations=("Values are normalized and engineering units are unknown.",),
            rules=("PHM-UNIT-001", "PHM-DUPLICATE-001"),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_FEATURE_AVAILABILITY,
            ReadinessStatus.SUPPORTED,
            time_evidence,
            rules=("PHM-SCHEMA-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_TIME_SERIES,
            ReadinessStatus.LIMITED,
            time_evidence,
            limitations=("Use raw source-coordinate order only.",),
            rules=("PHM-TIME-COORDINATE-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_FAULT_EVENT_INVENTORY,
            ReadinessStatus.SUPPORTED,
            time_evidence,
            rules=("PHM-EVENT-PRESERVE-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_EVENT_CENTERED_COMPARISON,
            ReadinessStatus.BLOCKED,
            time_evidence,
            missing=("verified coordinate unit for time windows",),
            blocking=("time-window duration semantics are unresolved",),
            rules=("PHM-TIME-UNIT-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_FAULT_PRECEDING_SIGNALS,
            ReadinessStatus.BLOCKED,
            time_evidence,
            missing=("verified time unit", "verified onset semantics"),
            blocking=("recorded shutdown/event time is not fault onset",),
            rules=("PHM-EVENT-SEMANTICS-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_TEMPORAL_FAULT_DETECTION,
            ReadinessStatus.BLOCKED,
            time_evidence,
            missing=("unbiased temporal labels and sampling",),
            blocking=("fault-centered subset and event semantics are unsuitable",),
            rules=("PHM-SAMPLING-BIAS-001",),
        ),
        _decision(
            dataset_id,
            AnalysisId.PHM_FALSE_ALARM_RATE,
            ReadinessStatus.BLOCKED,
            time_evidence,
            missing=("representative continuous operating population",),
            blocking=("fault-centered extraction biases event prevalence and coverage",),
            rules=("PHM-SAMPLING-BIAS-001",),
        ),
    )
    return PhmQualification(
        dataset_id=dataset_id,
        engine_version=QUALIFICATION_ENGINE_VERSION,
        provenance=dataset.provenance,
        time=time,
        identifiers=identifiers,
        duplicates=duplicates,
        event_coverage=coverage,
        readiness=readiness,
    )
