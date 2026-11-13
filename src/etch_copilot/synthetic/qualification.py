"""Scenario-scoped readiness for synthetic data inputs, not calculations."""

from __future__ import annotations

from pathlib import Path

from etch_copilot.models import DatasetLoadError
from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic.contracts import (
    ScenarioId,
    SyntheticCapability,
    SyntheticCapabilityDecision,
    SyntheticQualificationReport,
    SyntheticScenarioQualification,
)
from etch_copilot.synthetic.validation import (
    SyntheticDataset,
    _synthetic_dataset_content_sha256,
    load_synthetic_dataset,
)


def _decision(
    capability: SyntheticCapability,
    status: ReadinessStatus,
    *reasons: str,
) -> SyntheticCapabilityDecision:
    return SyntheticCapabilityDecision(capability=capability, status=status, reasons=reasons)


def qualify_synthetic_dataset(dataset: SyntheticDataset) -> SyntheticQualificationReport:
    """Qualify data inputs while preserving blocks on unimplemented calculations."""
    trusted_dataset = load_synthetic_dataset(Path(dataset.provenance.source_directory))
    if _synthetic_dataset_content_sha256(dataset) != trusted_dataset.content_sha256:
        raise DatasetLoadError("Synthetic in-memory content changed after ingestion")
    dataset = trusted_dataset
    scenarios: list[SyntheticScenarioQualification] = []
    for scenario in ScenarioId:
        blocking = tuple(
            issue
            for issue in dataset.validation.issues
            if issue.scenario_id == scenario.value and issue.blocks_metrology
        )
        metrology_status = ReadinessStatus.BLOCKED if blocking else ReadinessStatus.SUPPORTED
        metrology_reasons = (
            tuple(sorted({issue.message for issue in blocking}))
            if blocking
            else (
                "Declared nanometre units, five-site mapping, run pairing, duration, and "
                "synthetic uncertainty metadata are present.",
            )
        )
        scenarios.append(
            SyntheticScenarioQualification(
                scenario_id=scenario,
                decisions=(
                    _decision(
                        SyntheticCapability.INGESTION,
                        ReadinessStatus.SUPPORTED,
                        "Structural schema, hashes, identifiers, and timestamps validated.",
                    ),
                    _decision(
                        SyntheticCapability.ETCH_RATE_INPUTS,
                        metrology_status,
                        *metrology_reasons,
                    ),
                    _decision(
                        SyntheticCapability.UNIFORMITY_INPUTS,
                        metrology_status,
                        *metrology_reasons,
                    ),
                    _decision(
                        SyntheticCapability.SPC_CONTROL_LIMITS,
                        ReadinessStatus.BLOCKED,
                        "Phase 3 qualifies inputs only; SPC method and baseline admission "
                        "are not implemented.",
                    ),
                    _decision(
                        SyntheticCapability.ROOT_CAUSE_ATTRIBUTION,
                        ReadinessStatus.BLOCKED,
                        "Synthetic correspondence supports candidate hypotheses, never "
                        "causal confirmation.",
                    ),
                ),
            )
        )
    return SyntheticQualificationReport(
        dataset_id=dataset.manifest.dataset_id,
        scenarios=tuple(scenarios),
        external_dataset_effect="none; BOSCH and PHM readiness decisions are unchanged",
        limitations=(
            "Synthetic values are illustrative and are not validated plasma physics.",
            "Input readiness does not authorize etch-rate, uniformity, or SPC calculations.",
            "The synthetic calibration label is context only and is not real traceability.",
        ),
    )
