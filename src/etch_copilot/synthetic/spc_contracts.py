"""Immutable contracts for synthetic candidate SPC method qualification."""

from __future__ import annotations

from enum import StrEnum

from pydantic import computed_field

from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic.contracts import FrozenModel, ScenarioId

SPC_METHOD_VERSION = "1.0.0"
SPC_LIMIT_SCOPE = "synthetic_candidate_not_operational"
MINIMUM_BASELINE_OBSERVATIONS = 25
MOVING_RANGE_D2 = 1.128
MOVING_RANGE_D3 = 0.0
MOVING_RANGE_D4 = 3.267


class DependenceAdmissionOutcome(StrEnum):
    PASS = "PASS"
    MATERIAL_AUTOCORRELATION = "BLOCKED_MATERIAL_AUTOCORRELATION"
    INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"


class TransitionDisposition(StrEnum):
    CONTINUITY_VERIFIED = "CONTINUITY_VERIFIED"
    BOUNDARY_REPORTED = "BOUNDARY_REPORTED_NOT_EVALUATED"


class SyntheticSpcCapability(StrEnum):
    METHOD_QUALIFICATION = "synthetic.spc_method_qualification"
    CANDIDATE_LIMITS = "synthetic.spc_candidate_limits"
    INCIDENT_EVALUATION = "synthetic.spc_incident_evaluation"


class SourceDigest(FrozenModel):
    source_file: str
    sha256: str


class VersionedCandidateContract(FrozenModel):
    """Candidate scope/version are output invariants, never caller inputs."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def limit_scope(self) -> str:
        return SPC_LIMIT_SCOPE

    @computed_field  # type: ignore[prop-decorator]
    @property
    def method_version(self) -> str:
        return SPC_METHOD_VERSION


class OperationallyBlockedCandidateContract(VersionedCandidateContract):
    @computed_field  # type: ignore[prop-decorator]
    @property
    def operational_control_limits_status(self) -> ReadinessStatus:
        return ReadinessStatus.BLOCKED


class WaferEtchObservation(VersionedCandidateContract):
    scenario_id: ScenarioId
    run_id: str
    wafer_id: str
    start_ts_utc: str
    phase: str
    etch_rate_nm_per_min: float
    valid_site_count: int


class CandidateImrLimits(VersionedCandidateContract):
    observation_count: int
    center_line: float
    moving_ranges: tuple[float, ...]
    average_moving_range: float
    d2: float = MOVING_RANGE_D2
    d3: float = MOVING_RANGE_D3
    d4: float = MOVING_RANGE_D4
    sigma_moving_range: float
    individual_lcl: float
    individual_ucl: float
    moving_range_lcl: float
    moving_range_ucl: float
    sample_standard_deviation: float
    standard_deviation_individual_lcl: float
    standard_deviation_individual_ucl: float


class DependenceDiagnostic(FrozenModel):
    outcome: DependenceAdmissionOutcome
    observation_count: int
    lag1_autocorrelation: float | None
    screening_bound: float | None
    method: str
    limitation: str


class AdmissionIssue(FrozenModel):
    code: str
    message: str
    run_ids: tuple[str, ...] = ()


class TransitionAssessment(FrozenModel):
    previous_run_id: str
    current_run_id: str
    disposition: TransitionDisposition
    reasons: tuple[str, ...]
    moving_range: float | None
    moving_range_signal: bool


class SyntheticCandidateBaseline(VersionedCandidateContract):
    baseline_id: str
    dataset_id: str
    scenario_id: ScenarioId
    observation_count: int
    observations: tuple[WaferEtchObservation, ...]
    limits: CandidateImrLimits
    dependence: DependenceDiagnostic
    nominal_sampling_interval_s: float
    source_digests: tuple[SourceDigest, ...]
    interpretation_policy: str


class SyntheticCandidateBaselineQualification(OperationallyBlockedCandidateContract):
    dataset_id: str
    scenario_id: ScenarioId
    observation_count: int
    dependence: DependenceDiagnostic | None
    baseline_transitions: tuple[TransitionAssessment, ...]
    issues: tuple[AdmissionIssue, ...]
    baseline: SyntheticCandidateBaseline | None
    interpretation_policy: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def capability(self) -> SyntheticSpcCapability:
        return SyntheticSpcCapability.CANDIDATE_LIMITS

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> ReadinessStatus:
        return ReadinessStatus.SUPPORTED if self.baseline is not None else ReadinessStatus.BLOCKED


class CandidateSpcSignal(FrozenModel):
    chart: str
    run_id: str
    previous_run_id: str | None = None
    value: float
    limit: float
    direction: str


class SyntheticCandidateSpcEvaluation(OperationallyBlockedCandidateContract):
    dataset_id: str
    scenario_id: ScenarioId
    baseline_id: str
    incident_observations: tuple[WaferEtchObservation, ...]
    transitions: tuple[TransitionAssessment, ...]
    individual_signals: tuple[CandidateSpcSignal, ...]
    moving_range_signals: tuple[CandidateSpcSignal, ...]
    incident_mean: float
    incident_mean_difference: float
    source_digests: tuple[SourceDigest, ...]
    interpretation_policy: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def capability(self) -> SyntheticSpcCapability:
        return SyntheticSpcCapability.INCIDENT_EVALUATION

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status(self) -> ReadinessStatus:
        return ReadinessStatus.SUPPORTED
