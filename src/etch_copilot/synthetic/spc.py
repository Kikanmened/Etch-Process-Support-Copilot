"""Readiness-gated synthetic candidate SPC qualification and evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from etch_copilot.models import DatasetLoadError
from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic.contracts import (
    SYNTHETIC_RUN_INTERVAL_S,
    ScenarioId,
    SyntheticCapability,
)
from etch_copilot.synthetic.qualification import qualify_synthetic_dataset
from etch_copilot.synthetic.spc_contracts import (
    MINIMUM_BASELINE_OBSERVATIONS,
    AdmissionIssue,
    CandidateSpcSignal,
    DependenceAdmissionOutcome,
    SourceDigest,
    SyntheticCandidateBaseline,
    SyntheticCandidateBaselineQualification,
    SyntheticCandidateSpcEvaluation,
    TransitionAssessment,
    TransitionDisposition,
    WaferEtchObservation,
)
from etch_copilot.synthetic.spc_methods import (
    calculate_candidate_imr,
    diagnose_lag1_dependence,
)
from etch_copilot.synthetic.validation import (
    SyntheticDataset,
    _synthetic_dataset_content_sha256,
    load_synthetic_dataset,
)


class SyntheticSpcBlockedError(RuntimeError):
    """Raised when a synthetic candidate SPC operation is not authorized."""


def _trusted_reload(dataset: SyntheticDataset) -> SyntheticDataset:
    if not isinstance(dataset, SyntheticDataset):
        raise DatasetLoadError("Synthetic candidate SPC requires a SyntheticDataset")
    trusted = load_synthetic_dataset(Path(dataset.provenance.source_directory))
    if _synthetic_dataset_content_sha256(dataset) != trusted.content_sha256:
        raise DatasetLoadError("Synthetic in-memory content changed after ingestion")
    return trusted


def _source_digests(dataset: SyntheticDataset) -> tuple[SourceDigest, ...]:
    return tuple(
        SourceDigest(source_file=name, sha256=digest)
        for name, digest in sorted(dataset.provenance.sha256.items())
    )


def _stable_mean(values: tuple[float, ...]) -> float:
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("mean requires finite observations")
    scale = max(abs(value) for value in values)
    result = (
        0.0 if scale == 0.0 else math.fsum(value / scale for value in values) / len(values) * scale
    )
    if not math.isfinite(result):
        raise ValueError("mean is not finite and representable")
    return result


def _scenario_runs(dataset: SyntheticDataset, scenario: ScenarioId) -> pd.DataFrame:
    runs = dataset.runs.loc[dataset.runs["scenario_id"] == scenario.value].sort_values(
        ["start_ts_utc", "run_id"], kind="stable"
    )
    expected_count = (
        dataset.manifest.baseline_runs_per_scenario + dataset.manifest.incident_runs_per_scenario
    )
    if len(runs) != expected_count:
        raise DatasetLoadError("trusted synthetic membership has an unexpected run count")
    expected_ids = [f"{scenario.value}-R{index:03d}" for index in range(1, expected_count + 1)]
    if runs["run_id"].astype(str).tolist() != expected_ids:
        raise DatasetLoadError("trusted synthetic membership order does not match run identifiers")
    expected_phases = ["baseline"] * dataset.manifest.baseline_runs_per_scenario + [
        "incident"
    ] * dataset.manifest.incident_runs_per_scenario
    if runs["phase"].astype(str).tolist() != expected_phases:
        raise DatasetLoadError("trusted synthetic membership contradicts the source contract")
    return runs


def _wafer_observations(
    dataset: SyntheticDataset, scenario: ScenarioId
) -> tuple[WaferEtchObservation, ...]:
    runs = _scenario_runs(dataset, scenario)
    metrology = dataset.metrology.loc[dataset.metrology["scenario_id"] == scenario.value]
    grouped = {str(run_id): frame for run_id, frame in metrology.groupby("run_id", sort=False)}
    observations: list[WaferEtchObservation] = []
    for _, run in runs.iterrows():
        run_id = str(run["run_id"])
        sites = grouped.get(run_id)
        if sites is None or len(sites) != 5:
            raise DatasetLoadError(f"SPC observation requires five sites: {run_id}")
        if not sites["measurement_status"].astype(str).eq("VALID").all():
            raise DatasetLoadError(f"SPC observation has invalid metrology: {run_id}")
        if not sites["thickness_unit"].astype(str).eq("nm").all():
            raise DatasetLoadError(f"SPC observation has inconsistent units: {run_id}")
        duration_minutes = float(run["etch_duration_s"]) / 60.0
        rates = (
            pd.to_numeric(sites["pre_thickness_nm"], errors="raise")
            - pd.to_numeric(sites["post_thickness_nm"], errors="raise")
        ) / duration_minutes
        values = tuple(float(value) for value in rates)
        if not all(math.isfinite(value) for value in values):
            raise DatasetLoadError(f"SPC observation is non-finite: {run_id}")
        try:
            mean_rate = _stable_mean(values)
        except ValueError as exc:
            raise DatasetLoadError(f"SPC observation mean is not representable: {run_id}") from exc
        observations.append(
            WaferEtchObservation(
                scenario_id=scenario,
                run_id=run_id,
                wafer_id=str(run["wafer_id"]),
                start_ts_utc=run["start_ts_utc"].isoformat().replace("+00:00", "Z"),
                phase=str(run["phase"]),
                etch_rate_nm_per_min=mean_rate,
                valid_site_count=len(values),
            )
        )
    return tuple(observations)


def _nominal_interval_seconds(observations: tuple[WaferEtchObservation, ...]) -> float:
    if len(observations) < 2:
        raise DatasetLoadError("cannot establish a nominal synthetic sampling interval")
    return float(SYNTHETIC_RUN_INTERVAL_S)


def _has_alarm(dataset: SyntheticDataset, run_id: str) -> bool:
    alarms = dataset.telemetry.loc[dataset.telemetry["run_id"] == run_id, "alarm_code"]
    return bool(alarms.dropna().astype(str).str.strip().ne("").any())


def _assess_transition(
    dataset: SyntheticDataset,
    previous: WaferEtchObservation,
    current: WaferEtchObservation,
    nominal_interval_s: float,
    moving_range_ucl: float | None,
) -> TransitionAssessment:
    runs = dataset.runs.set_index("run_id")
    previous_run = runs.loc[previous.run_id]
    current_run = runs.loc[current.run_id]
    reasons: list[str] = []
    if str(previous_run["chamber_id"]) != str(current_run["chamber_id"]):
        reasons.append("equipment-state/chamber change")
    if str(previous_run["recipe_id"]) != str(current_run["recipe_id"]):
        reasons.append("recipe change")
    previous_maintenance = str(previous_run["maintenance_event_id"]).strip()
    current_maintenance = str(current_run["maintenance_event_id"]).strip()
    previous_maintenance = "" if previous_maintenance.lower() == "nan" else previous_maintenance
    current_maintenance = "" if current_maintenance.lower() == "nan" else current_maintenance
    if current_maintenance:
        event_rows = dataset.maintenance.loc[
            dataset.maintenance["event_id"].astype(str) == current_maintenance
        ]
        if event_rows.empty:
            reasons.append("unqualified maintenance reference")
        else:
            event_timestamp = pd.Timestamp(event_rows.iloc[0]["timestamp_utc"])
            previous_end = pd.Timestamp(str(previous_run["end_ts_utc"]))
            current_start = pd.Timestamp(str(current_run["start_ts_utc"]))
            if previous_end < event_timestamp <= current_start:
                reasons.append("maintenance")
            elif current_maintenance != previous_maintenance:
                reasons.append("unqualified maintenance timing")
    if _has_alarm(dataset, previous.run_id) or _has_alarm(dataset, current.run_id):
        reasons.append("equipment-state alarm")
    previous_timestamp = pd.Timestamp(previous.start_ts_utc)
    current_timestamp = pd.Timestamp(current.start_ts_utc)
    observed_interval = (current_timestamp - previous_timestamp).total_seconds()
    if not math.isclose(observed_interval, nominal_interval_s, rel_tol=0.0, abs_tol=1e-9):
        reasons.append("unqualified sampling gap")
    if reasons:
        return TransitionAssessment(
            previous_run_id=previous.run_id,
            current_run_id=current.run_id,
            disposition=TransitionDisposition.BOUNDARY_REPORTED,
            reasons=tuple(reasons),
            moving_range=None,
            moving_range_signal=False,
        )
    moving_range = abs(current.etch_rate_nm_per_min - previous.etch_rate_nm_per_min)
    return TransitionAssessment(
        previous_run_id=previous.run_id,
        current_run_id=current.run_id,
        disposition=TransitionDisposition.CONTINUITY_VERIFIED,
        reasons=("continuity verified",),
        moving_range=moving_range,
        moving_range_signal=(moving_range_ucl is not None and moving_range > moving_range_ucl),
    )


def _baseline_identifier(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def qualify_synthetic_candidate_baseline(
    dataset: SyntheticDataset, scenario_id: str | ScenarioId
) -> SyntheticCandidateBaselineQualification:
    """Qualify a frozen synthetic candidate baseline without authorizing operational SPC."""
    trusted = _trusted_reload(dataset)
    scenario = ScenarioId(scenario_id)
    phase_three = qualify_synthetic_dataset(trusted).scenario(scenario)
    issues: list[AdmissionIssue] = []
    if phase_three.status(SyntheticCapability.ETCH_RATE_INPUTS) is ReadinessStatus.BLOCKED:
        issues.append(
            AdmissionIssue(
                code="METROLOGY_BLOCKED",
                message="Scenario metrology readiness blocks candidate SPC observations.",
            )
        )
        return SyntheticCandidateBaselineQualification(
            dataset_id=trusted.manifest.dataset_id,
            scenario_id=scenario,
            observation_count=0,
            dependence=None,
            baseline_transitions=(),
            issues=tuple(issues),
            baseline=None,
            interpretation_policy=(
                "Synthetic candidate limits are not operational control limits or specifications."
            ),
        )
    observations = _wafer_observations(trusted, scenario)
    baseline_observations = tuple(item for item in observations if item.phase == "baseline")
    values = tuple(item.etch_rate_nm_per_min for item in baseline_observations)
    dependence = diagnose_lag1_dependence(values)
    if len(values) < MINIMUM_BASELINE_OBSERVATIONS:
        issues.append(
            AdmissionIssue(
                code="INSUFFICIENT_BASELINE_HISTORY",
                message="Project policy requires at least 25 ordered baseline observations.",
            )
        )
    if dependence.outcome is DependenceAdmissionOutcome.MATERIAL_AUTOCORRELATION:
        issues.append(
            AdmissionIssue(
                code="MATERIAL_AUTOCORRELATION",
                message="Lag-1 dependence exceeds the declared admission screening bound.",
            )
        )
    elif dependence.outcome is DependenceAdmissionOutcome.INSUFFICIENT_EVIDENCE:
        issues.append(
            AdmissionIssue(
                code="DEPENDENCE_EVIDENCE_INSUFFICIENT",
                message="Dependence evidence is insufficient for candidate I-MR admission.",
            )
        )
    try:
        limits = calculate_candidate_imr(values)
    except (OverflowError, ValueError) as exc:
        issues.append(
            AdmissionIssue(
                code="NUMERICAL_ADMISSION_BLOCK",
                message=f"Candidate I-MR parameters are not representable: {exc}",
            )
        )
        return SyntheticCandidateBaselineQualification(
            dataset_id=trusted.manifest.dataset_id,
            scenario_id=scenario,
            observation_count=len(baseline_observations),
            dependence=dependence,
            baseline_transitions=(),
            issues=tuple(issues),
            baseline=None,
            interpretation_policy=(
                "Numerically unsafe data cannot produce synthetic candidate limits; "
                "operational SPC remains blocked."
            ),
        )
    nominal_interval = _nominal_interval_seconds(baseline_observations)
    baseline_transitions = tuple(
        _assess_transition(trusted, previous, current, nominal_interval, limits.moving_range_ucl)
        for previous, current in zip(baseline_observations, baseline_observations[1:], strict=False)
    )
    boundary_runs = tuple(
        item.current_run_id
        for item in baseline_transitions
        if item.disposition is TransitionDisposition.BOUNDARY_REPORTED
    )
    if boundary_runs:
        issues.append(
            AdmissionIssue(
                code="UNQUALIFIED_BASELINE_BOUNDARY",
                message="Baseline contains a transition whose continuity is not verified.",
                run_ids=boundary_runs,
            )
        )
    phase_one_signals = tuple(
        item.run_id
        for item in baseline_observations
        if item.etch_rate_nm_per_min < limits.individual_lcl
        or item.etch_rate_nm_per_min > limits.individual_ucl
    )
    if phase_one_signals:
        issues.append(
            AdmissionIssue(
                code="UNRESOLVED_PHASE_ONE_SIGNAL",
                message="Baseline contains Individuals-chart signals; no points were removed.",
                run_ids=phase_one_signals,
            )
        )
    phase_one_mr_signal_runs = tuple(
        run_id
        for transition in baseline_transitions
        if transition.moving_range_signal
        for run_id in (transition.previous_run_id, transition.current_run_id)
    )
    if phase_one_mr_signal_runs:
        issues.append(
            AdmissionIssue(
                code="UNRESOLVED_PHASE_ONE_MR_SIGNAL",
                message="Baseline contains Moving-Range-chart signals; no pairs were removed.",
                run_ids=tuple(dict.fromkeys(phase_one_mr_signal_runs)),
            )
        )
    if limits.average_moving_range == 0.0:
        issues.append(
            AdmissionIssue(
                code="ZERO_MOVING_RANGE",
                message="Zero average moving range cannot estimate baseline variability.",
            )
        )
    baseline: SyntheticCandidateBaseline | None = None
    if not issues:
        source_digests = _source_digests(trusted)
        identity_payload = {
            "dataset_id": trusted.manifest.dataset_id,
            "scenario_id": scenario.value,
            "observations": [item.model_dump(mode="json") for item in baseline_observations],
            "limits": limits.model_dump(mode="json"),
            "dependence": dependence.model_dump(mode="json"),
            "nominal_sampling_interval_s": nominal_interval,
            "source_digests": [item.model_dump(mode="json") for item in source_digests],
        }
        baseline = SyntheticCandidateBaseline(
            baseline_id=_baseline_identifier(identity_payload),
            dataset_id=trusted.manifest.dataset_id,
            scenario_id=scenario,
            observation_count=len(baseline_observations),
            observations=baseline_observations,
            limits=limits,
            dependence=dependence,
            nominal_sampling_interval_s=nominal_interval,
            source_digests=source_digests,
            interpretation_policy=(
                "Synthetic candidate I-MR parameters are frozen for method evaluation only; "
                "they are not operational control limits or specifications."
            ),
        )
    return SyntheticCandidateBaselineQualification(
        dataset_id=trusted.manifest.dataset_id,
        scenario_id=scenario,
        observation_count=len(baseline_observations),
        dependence=dependence,
        baseline_transitions=baseline_transitions,
        issues=tuple(issues),
        baseline=baseline,
        interpretation_policy=(
            "Admission qualifies only a synthetic candidate SPC method. Operational control "
            "limits, capability, and physical root-cause conclusions remain blocked."
        ),
    )


def evaluate_synthetic_candidate_spc(
    dataset: SyntheticDataset, baseline: SyntheticCandidateBaseline
) -> SyntheticCandidateSpcEvaluation:
    """Evaluate synthetic incidents against an independently verified frozen baseline."""
    trusted = _trusted_reload(dataset)
    if trusted.manifest.dataset_id != baseline.dataset_id:
        raise SyntheticSpcBlockedError("Frozen baseline belongs to a different dataset")
    verified = qualify_synthetic_candidate_baseline(trusted, baseline.scenario_id)
    if verified.baseline is None or verified.baseline != baseline:
        raise SyntheticSpcBlockedError("Supplied frozen baseline failed trusted verification")
    baseline = verified.baseline
    observations = _wafer_observations(trusted, baseline.scenario_id)
    incident = tuple(item for item in observations if item.phase == "incident")
    if not incident:
        raise SyntheticSpcBlockedError("No trusted incident observations are available")
    sequence = (baseline.observations[-1], *incident)
    transitions = tuple(
        _assess_transition(
            trusted,
            previous,
            current,
            baseline.nominal_sampling_interval_s,
            baseline.limits.moving_range_ucl,
        )
        for previous, current in zip(sequence, sequence[1:], strict=False)
    )
    individual_signals: list[CandidateSpcSignal] = []
    for item in incident:
        if item.etch_rate_nm_per_min < baseline.limits.individual_lcl:
            individual_signals.append(
                CandidateSpcSignal(
                    chart="Individuals",
                    run_id=item.run_id,
                    value=item.etch_rate_nm_per_min,
                    limit=baseline.limits.individual_lcl,
                    direction="below_lcl",
                )
            )
        elif item.etch_rate_nm_per_min > baseline.limits.individual_ucl:
            individual_signals.append(
                CandidateSpcSignal(
                    chart="Individuals",
                    run_id=item.run_id,
                    value=item.etch_rate_nm_per_min,
                    limit=baseline.limits.individual_ucl,
                    direction="above_ucl",
                )
            )
    moving_range_signals = tuple(
        CandidateSpcSignal(
            chart="Moving Range",
            run_id=item.current_run_id,
            previous_run_id=item.previous_run_id,
            value=float(item.moving_range),
            limit=baseline.limits.moving_range_ucl,
            direction="above_ucl",
        )
        for item in transitions
        if item.moving_range_signal and item.moving_range is not None
    )
    try:
        incident_mean = _stable_mean(tuple(item.etch_rate_nm_per_min for item in incident))
    except ValueError as exc:
        raise SyntheticSpcBlockedError(
            "Incident observations cannot produce a finite synthetic candidate mean"
        ) from exc
    incident_mean_difference = incident_mean - baseline.limits.center_line
    if not math.isfinite(incident_mean_difference):
        raise SyntheticSpcBlockedError("Incident mean difference is not finite and representable")
    return SyntheticCandidateSpcEvaluation(
        dataset_id=trusted.manifest.dataset_id,
        scenario_id=baseline.scenario_id,
        baseline_id=baseline.baseline_id,
        incident_observations=incident,
        transitions=transitions,
        individual_signals=tuple(individual_signals),
        moving_range_signals=moving_range_signals,
        incident_mean=incident_mean,
        incident_mean_difference=incident_mean_difference,
        source_digests=_source_digests(trusted),
        interpretation_policy=(
            "Signals identify synthetic changes in location or short-term successive variation; "
            "they do not confirm a physical root cause, production state, or recipe action."
        ),
    )
