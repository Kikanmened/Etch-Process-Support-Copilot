"""Immutable, JSON-compatible contracts for deterministic engineering analytics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from etch_copilot.qualification import AnalysisId, ReadinessStatus

ANALYTICS_VERSION = "1.0.0"


class FrozenResult(BaseModel):
    """Base model for result objects that must not change after calculation."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FileDigest(FrozenResult):
    source_file: str
    sha256: str


class ProvenanceSnapshot(FrozenResult):
    dataset_id: str
    source_directory: str
    files: tuple[FileDigest, ...]
    extraction_notes: tuple[str, ...]


class AnalysisContext(FrozenResult):
    analysis_id: AnalysisId
    analysis_version: str = ANALYTICS_VERSION
    dataset_id: str
    scope: str
    readiness_status: ReadinessStatus
    limitations: tuple[str, ...]
    validation_rules: tuple[str, ...]
    provenance: ProvenanceSnapshot


class NumericStatistics(FrozenResult):
    observation_count: int
    finite_count: int
    missing_count: int
    positive_infinity_count: int
    negative_infinity_count: int
    available_coverage: float
    minimum: float | None
    maximum: float | None
    mean: float | None
    median: float | None
    standard_deviation: float | None
    variance: float | None
    calculation_warnings: tuple[str, ...]


class IntervalSummary(FrozenResult):
    interval_count: int
    minimum_interval_s: float | None
    median_interval_s: float | None
    maximum_interval_s: float | None
    discontinuity_after_indices: tuple[int, ...]
    non_positive_interval_count: int


class BoschTrendResult(AnalysisContext):
    run_id: str
    feature: str
    engineering_unit: str | None
    unit_verified: bool
    coordinate_name: str
    coordinate_unit: str
    coordinate_semantics: str
    documented_acquisition_hz: float | None
    elapsed_coordinates: tuple[float, ...]
    sensor_values: tuple[float | str | None, ...]
    interval_summary: IntervalSummary


class BoschStatisticsResult(AnalysisContext):
    run_id: str
    feature: str
    engineering_unit: str | None
    unit_verified: bool
    statistics: NumericStatistics


class RunStatistics(FrozenResult):
    run_id: str
    statistics: NumericStatistics


class BoschComparisonResult(AnalysisContext):
    feature: str
    engineering_unit: str | None
    unit_verified: bool
    runs: tuple[RunStatistics, ...]
    interpretation_policy: str


class MissingFieldCount(FrozenResult):
    field: str
    missing_count: int


class WaferCoverage(FrozenResult):
    experiment_key: str
    run_id: str | None
    lot_number: int
    wafer_number: int
    site_record_count: int
    unique_position_count: int
    expected_site_count: int
    relationship_unambiguous: bool
    pre_etch_direct_count: int
    pre_etch_reconstructed_count: int
    pre_etch_unclassified_count: int
    post_etch_direct_count: int
    post_etch_reconstructed_count: int
    post_etch_unclassified_count: int
    missing_fields: tuple[MissingFieldCount, ...]


class GroupMissingness(FrozenResult):
    group_key: str
    record_count: int
    missing_fields: tuple[MissingFieldCount, ...]


class BoschMetrologyCoverageResult(AnalysisContext):
    total_site_records: int
    selected_wafer_count: int
    measurement_unit: str | None
    unit_verified: bool
    wafers: tuple[WaferCoverage, ...]
    missingness_by_lot: tuple[GroupMissingness, ...]
    data_quality_issues: tuple[str, ...]
    reconstruction_policy: tuple[str, ...]


class FeatureInventoryItem(FrozenResult):
    source_name: str
    recorded_dtype: str
    observation_count: int
    finite_count: int
    missing_count: int
    positive_infinity_count: int
    negative_infinity_count: int
    invalid_non_numeric_count: int
    repeated_value_count: int
    engineering_unit: str | None
    unit_verified: bool


class MetadataItem(FrozenResult):
    name: str
    json_value: str


class PhmFeatureInventoryResult(AnalysisContext):
    source_equipment_ids: tuple[str, ...]
    canonical_equipment_id: str | None
    raw_observation_count: int
    exact_duplicate_count: int
    features: tuple[FeatureInventoryItem, ...]
    metadata: tuple[MetadataItem, ...]
    time_unit: str | None
    time_semantics: str
    sampling_bias: str


class CategoryCount(FrozenResult):
    category: str | None
    count: int


class FaultEventRecord(FrozenResult):
    source_index: int
    source_equipment_id: str | None
    canonical_equipment_id: str | None
    category: str | None
    source_coordinate: int | None
    coordinate_unit: str | None
    is_confirmed_fault_onset: bool
    missing_fields: tuple[str, ...]


class PhmFaultInventoryResult(AnalysisContext):
    source_equipment_ids: tuple[str, ...]
    canonical_equipment_id: str | None
    total_recorded_events: int
    category_counts: tuple[CategoryCount, ...]
    events: tuple[FaultEventRecord, ...]
    event_semantics: str
    ambiguous_event_field_count: int


class AnalyticsScopeError(RuntimeError):
    """Structured failure for an invalid or incompatible analysis scope."""

    def __init__(self, analysis_id: AnalysisId, scope: str, reasons: tuple[str, ...]) -> None:
        self.analysis_id = analysis_id
        self.scope = scope
        self.reasons = reasons
        super().__init__(f"{analysis_id}: {'; '.join(reasons)} [scope: {scope}]")
