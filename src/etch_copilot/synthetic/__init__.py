"""Qualified synthetic scenario data for the read-only etch demonstrator."""

from etch_copilot.synthetic.contracts import (
    ScenarioId,
    SyntheticCapability,
    SyntheticGenerationResult,
    SyntheticGeneratorConfig,
    SyntheticQualificationReport,
    SyntheticValidationSummary,
)
from etch_copilot.synthetic.generator import generate_synthetic_dataset
from etch_copilot.synthetic.qualification import qualify_synthetic_dataset
from etch_copilot.synthetic.spc import (
    SyntheticSpcBlockedError,
    evaluate_synthetic_candidate_spc,
    qualify_synthetic_candidate_baseline,
)
from etch_copilot.synthetic.spc_contracts import (
    DependenceAdmissionOutcome,
    SyntheticCandidateBaseline,
    SyntheticCandidateBaselineQualification,
    SyntheticCandidateSpcEvaluation,
    TransitionDisposition,
)
from etch_copilot.synthetic.validation import SyntheticDataset, load_synthetic_dataset

__all__ = [
    "ScenarioId",
    "DependenceAdmissionOutcome",
    "SyntheticCapability",
    "SyntheticCandidateBaseline",
    "SyntheticCandidateBaselineQualification",
    "SyntheticCandidateSpcEvaluation",
    "SyntheticDataset",
    "SyntheticGenerationResult",
    "SyntheticGeneratorConfig",
    "SyntheticQualificationReport",
    "SyntheticSpcBlockedError",
    "SyntheticValidationSummary",
    "TransitionDisposition",
    "evaluate_synthetic_candidate_spc",
    "generate_synthetic_dataset",
    "load_synthetic_dataset",
    "qualify_synthetic_dataset",
    "qualify_synthetic_candidate_baseline",
]
