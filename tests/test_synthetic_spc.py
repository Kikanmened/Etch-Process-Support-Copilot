from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etch_copilot.provenance import sha256_file
from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic import (
    SyntheticCapability,
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
    qualify_synthetic_dataset,
)
from etch_copilot.synthetic.spc import (
    SyntheticSpcBlockedError,
    evaluate_synthetic_candidate_spc,
    qualify_synthetic_candidate_baseline,
)
from etch_copilot.synthetic.spc_contracts import (
    DependenceAdmissionOutcome,
    TransitionDisposition,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DATASET = PROJECT_ROOT / "data" / "synthetic" / "demo-v1"


def test_canonical_s1_is_blocked_by_dependence_and_phase_one_signal() -> None:
    qualification = qualify_synthetic_candidate_baseline(load_synthetic_dataset(DEMO_DATASET), "S1")

    assert qualification.status is ReadinessStatus.BLOCKED
    assert qualification.baseline is None
    assert qualification.dependence.outcome is DependenceAdmissionOutcome.MATERIAL_AUTOCORRELATION
    assert qualification.dependence.lag1_autocorrelation == pytest.approx(0.5104151954)
    assert {issue.code for issue in qualification.issues} >= {
        "MATERIAL_AUTOCORRELATION",
        "UNRESOLVED_PHASE_ONE_SIGNAL",
    }


def test_canonical_s2_qualifies_and_detects_variability_without_causal_claim() -> None:
    dataset = load_synthetic_dataset(DEMO_DATASET)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S2")

    assert qualification.status is ReadinessStatus.SUPPORTED
    assert qualification.baseline is not None
    assert qualification.dependence.outcome is DependenceAdmissionOutcome.PASS
    assert qualification.baseline.observation_count == 30
    assert qualification.baseline.limits.sigma_moving_range == pytest.approx(1.2955950202)
    assert qualification.baseline.limits.sample_standard_deviation == pytest.approx(1.2608481263)

    evaluation = evaluate_synthetic_candidate_spc(dataset, qualification.baseline)

    assert evaluation.status is ReadinessStatus.SUPPORTED
    assert evaluation.limit_scope == "synthetic_candidate_not_operational"
    assert len(evaluation.individual_signals) == 6
    assert len(evaluation.moving_range_signals) == 8
    assert evaluation.incident_mean_difference == pytest.approx(1.4336484042)
    assert "root cause" in evaluation.interpretation_policy.lower()
    assert evaluation == evaluate_synthetic_candidate_spc(dataset, qualification.baseline)


def test_canonical_s3_refuses_spc_due_to_invalid_metrology() -> None:
    dataset = load_synthetic_dataset(DEMO_DATASET)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S3")

    assert qualification.status is ReadinessStatus.BLOCKED
    assert qualification.baseline is None
    assert "METROLOGY_BLOCKED" in {issue.code for issue in qualification.issues}


def test_qualified_s1_reports_maintenance_transition_as_boundary(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    dataset = load_synthetic_dataset(output)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S1")

    assert qualification.status is ReadinessStatus.SUPPORTED
    assert qualification.baseline is not None

    evaluation = evaluate_synthetic_candidate_spc(dataset, qualification.baseline)
    first_transition = evaluation.transitions[0]

    assert first_transition.current_run_id == "S1-R031"
    assert first_transition.disposition is TransitionDisposition.BOUNDARY_REPORTED
    assert "maintenance" in first_transition.reasons
    assert first_transition.moving_range is None
    assert all(
        transition.disposition is TransitionDisposition.CONTINUITY_VERIFIED
        for transition in evaluation.transitions[1:]
    )


def test_equipment_alarm_creates_separate_transition_boundary(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=1))
    telemetry = pd.read_csv(output / "telemetry.csv")
    alarm_mask = telemetry["run_id"] == "S1-R032"
    telemetry["alarm_code"] = telemetry["alarm_code"].astype(object)
    telemetry.loc[
        alarm_mask & (telemetry.index == telemetry.index[alarm_mask][0]), "alarm_code"
    ] = "SYNTHETIC_STATE_CHANGE"
    telemetry.to_csv(
        output / "telemetry.csv", index=False, lineterminator="\n", float_format="%.6f"
    )
    manifest_path = output / "dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["telemetry.csv"] = sha256_file(output / "telemetry.csv")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    dataset = load_synthetic_dataset(output)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S1")
    assert qualification.baseline is not None

    evaluation = evaluate_synthetic_candidate_spc(dataset, qualification.baseline)

    alarm_transition = next(
        item for item in evaluation.transitions if item.current_run_id == "S1-R032"
    )
    assert alarm_transition.disposition is TransitionDisposition.BOUNDARY_REPORTED
    assert "equipment-state alarm" in alarm_transition.reasons


def test_candidate_contracts_never_promote_operational_spc_or_expose_truth() -> None:
    dataset = load_synthetic_dataset(DEMO_DATASET)
    qualification = qualify_synthetic_candidate_baseline(dataset, "S2")
    assert qualification.baseline is not None
    evaluation = evaluate_synthetic_candidate_spc(dataset, qualification.baseline)
    serialized = json.dumps(evaluation.model_dump(mode="json"), sort_keys=True)
    phase_three = qualify_synthetic_dataset(dataset)

    assert "synthetic_candidate_not_operational" in serialized
    assert "scenario_truth" not in serialized
    assert (
        phase_three.scenario("S2").status(SyntheticCapability.SPC_CONTROL_LIMITS)
        is ReadinessStatus.BLOCKED
    )

    forged_evaluation = evaluation.model_copy(
        update={
            "limit_scope": "operational",
            "method_version": "forged",
            "operational_control_limits_status": ReadinessStatus.SUPPORTED,
            "status": ReadinessStatus.BLOCKED,
        }
    )
    forged_payload = forged_evaluation.model_dump(mode="json")
    assert forged_payload["limit_scope"] == "synthetic_candidate_not_operational"
    assert forged_payload["method_version"] == "1.0.0"
    assert forged_payload["operational_control_limits_status"] == "BLOCKED"
    assert forged_payload["status"] == "SUPPORTED"

    baseline_removed = qualification.model_copy(
        update={"baseline": None, "status": ReadinessStatus.SUPPORTED}
    )
    assert baseline_removed.status is ReadinessStatus.BLOCKED


def test_forged_or_cross_dataset_baseline_is_rejected(tmp_path: Path) -> None:
    canonical = load_synthetic_dataset(DEMO_DATASET)
    qualification = qualify_synthetic_candidate_baseline(canonical, "S2")
    assert qualification.baseline is not None
    forged = qualification.baseline.model_copy(update={"baseline_id": "0" * 64})

    with pytest.raises(SyntheticSpcBlockedError, match="frozen baseline"):
        evaluate_synthetic_candidate_spc(canonical, forged)

    forged_limits = qualification.baseline.limits.model_copy(
        update={"individual_lcl": -1e9, "individual_ucl": 1e9, "moving_range_ucl": 1e9}
    )
    retained_id_forgery = qualification.baseline.model_copy(update={"limits": forged_limits})
    with pytest.raises(SyntheticSpcBlockedError, match="frozen baseline"):
        evaluate_synthetic_candidate_spc(canonical, retained_id_forgery)

    other_path = tmp_path / "other"
    generate_synthetic_dataset(other_path, SyntheticGeneratorConfig(seed=1))
    other = load_synthetic_dataset(other_path)
    with pytest.raises(SyntheticSpcBlockedError, match="dataset"):
        evaluate_synthetic_candidate_spc(other, qualification.baseline)
