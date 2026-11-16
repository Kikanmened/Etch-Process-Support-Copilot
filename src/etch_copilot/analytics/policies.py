"""Shared numerical and trusted-readiness policies for analytics."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd

from etch_copilot.analytics.contracts import (
    AnalyticsScopeError,
    FileDigest,
    NumericStatistics,
    ProvenanceSnapshot,
)
from etch_copilot.loaders import (
    BoschDataset,
    PhmDataset,
    _dataset_content_sha256,
    load_bosch_dataset,
    load_phm_dataset,
)
from etch_copilot.models import DatasetLoadError, DatasetProvenance
from etch_copilot.provenance import sha256_file, verify_provenance
from etch_copilot.qualification import (
    AnalysisId,
    ReadinessDecision,
    ReadinessStatus,
    assert_analysis_permitted,
    build_bosch_qualification,
    build_phm_qualification,
    canonicalize_phm_equipment_id,
    qualify_bosch_scope,
)


class AnalysisContextKwargs(TypedDict):
    analysis_id: AnalysisId
    dataset_id: str
    scope: str
    readiness_status: ReadinessStatus
    limitations: tuple[str, ...]
    validation_rules: tuple[str, ...]
    provenance: ProvenanceSnapshot


def provenance_snapshot(provenance: DatasetProvenance) -> ProvenanceSnapshot:
    return ProvenanceSnapshot(
        dataset_id=provenance.dataset_id,
        source_directory=provenance.source_directory,
        files=tuple(
            FileDigest(source_file=name, sha256=digest)
            for name, digest in sorted(provenance.sha256.items())
        ),
        extraction_notes=provenance.extraction_notes,
    )


def analysis_context(
    decision: ReadinessDecision,
    provenance: DatasetProvenance,
    additional_files: tuple[FileDigest, ...] = (),
) -> AnalysisContextKwargs:
    """Return only fields owned by the common immutable result contract."""
    snapshot = provenance_snapshot(provenance)
    return {
        "analysis_id": decision.analysis_id,
        "dataset_id": decision.dataset_id,
        "scope": decision.scope,
        "readiness_status": decision.status,
        "limitations": decision.limitations,
        "validation_rules": decision.validation_rules,
        "provenance": snapshot.model_copy(
            update={
                "files": tuple(
                    sorted(
                        (*snapshot.files, *additional_files),
                        key=lambda item: item.source_file,
                    )
                )
            }
        ),
    }


def authorize_bosch(
    dataset: BoschDataset,
    analysis_id: AnalysisId,
    *,
    run_ids: tuple[str, ...] = (),
    wafer_keys: tuple[str, ...] | None = (),
    feature: str | None = None,
) -> tuple[ReadinessDecision, BoschDataset]:
    if not isinstance(dataset, BoschDataset):
        raise AnalyticsScopeError(
            analysis_id, "dataset", ("BOSCH analytics require a BoschDataset",)
        )
    source_directory = Path(dataset.provenance.source_directory)
    verify_provenance(dataset.provenance, source_directory)
    for reference in dataset.scientific_references:
        if reference.source_path != "research/Readme.pdf":
            raise DatasetLoadError("Unexpected scientific-reference path in BOSCH dataset")
        reference_path = source_directory.parent / reference.source_path
        if not reference_path.is_file() or sha256_file(reference_path) != reference.sha256:
            raise DatasetLoadError("Scientific reference changed after dataset ingestion")
    trusted_dataset = load_bosch_dataset(source_directory)
    if _dataset_content_sha256(dataset) != trusted_dataset.content_sha256:
        raise DatasetLoadError("Loaded dataset content changed after ingestion")
    qualification = build_bosch_qualification(trusted_dataset)
    scoped_wafer_keys = (
        tuple(sorted(set(trusted_dataset.metrology["experiment_key"].astype(str))))
        if wafer_keys is None
        else wafer_keys
    )
    base_decision = qualification.decision(analysis_id)
    decision = qualify_bosch_scope(
        qualification,
        analysis_id,
        run_ids=run_ids,
        wafer_keys=scoped_wafer_keys,
        feature=feature,
    )
    if (
        base_decision.status is not ReadinessStatus.BLOCKED
        and decision.status is ReadinessStatus.BLOCKED
    ):
        raise AnalyticsScopeError(analysis_id, decision.scope, decision.blocking_issues)
    assert_analysis_permitted(decision, allow_limited=True)
    return decision, trusted_dataset


def authorize_phm(
    dataset: PhmDataset,
    analysis_id: AnalysisId,
    equipment_id: str | None,
    *,
    include_fault_identifiers: bool = False,
) -> tuple[ReadinessDecision, tuple[str, ...], str | None, PhmDataset]:
    if not isinstance(dataset, PhmDataset):
        raise AnalyticsScopeError(analysis_id, "dataset", ("PHM analytics require a PhmDataset",))
    source_directory = Path(dataset.provenance.source_directory)
    verify_provenance(dataset.provenance, source_directory)
    trusted_dataset = load_phm_dataset(source_directory)
    if _dataset_content_sha256(dataset) != trusted_dataset.content_sha256:
        raise DatasetLoadError("Loaded dataset content changed after ingestion")
    qualification = build_phm_qualification(trusted_dataset)
    decision = qualification.decision(analysis_id)
    observed_values = set(trusted_dataset.observations["Tool"].dropna().astype(str))
    scope_values = observed_values | (
        {event.equipment_id for event in trusted_dataset.faults if event.equipment_id is not None}
        if include_fault_identifiers
        else set()
    )
    observed = tuple(sorted(scope_values))
    canonical: str | None = None
    selected = observed
    if equipment_id is not None:
        canonical = canonicalize_phm_equipment_id(equipment_id, qualification.identifiers)
        matching = tuple(
            item
            for item in observed
            if item == equipment_id
            or (
                canonical is not None
                and canonicalize_phm_equipment_id(item, qualification.identifiers) == canonical
            )
        )
        if not matching:
            raise AnalyticsScopeError(
                analysis_id,
                f"equipment={equipment_id}",
                (f"Unknown PHM equipment identifier: {equipment_id}",),
            )
        selected = matching
    assert_analysis_permitted(decision, allow_limited=True)
    scoped = decision.model_copy(
        update={"scope": f"equipment={','.join(selected) if selected else 'none'}"}
    )
    return scoped, selected, canonical, trusted_dataset


def numeric_statistics(values: pd.Series) -> NumericStatistics:
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=np.float64)
    missing = int(np.isnan(numeric).sum())
    positive_infinity = int(np.isposinf(numeric).sum())
    negative_infinity = int(np.isneginf(numeric).sum())
    finite = numeric[np.isfinite(numeric)]
    finite_count = int(finite.size)
    observation_count = int(numeric.size)
    mean: float | None = None
    median: float | None = None
    variance: float | None = None
    standard_deviation: float | None = None
    warnings: list[str] = []
    if finite_count:
        finite_values = sorted(float(value) for value in finite)
        scale = max(abs(value) for value in finite_values)
        if scale == 0:
            mean = 0.0
        else:
            normalized_mean = math.fsum(value / scale for value in finite_values) / finite_count
            candidate_mean = normalized_mean * scale
            if normalized_mean != 0 and candidate_mean == 0:
                warnings.append("arithmetic mean underflowed float64 range")
            else:
                mean = candidate_mean
        midpoint = finite_count // 2
        median = finite_values[midpoint]
        if finite_count % 2 == 0:
            if scale == 0:
                median = 0.0
            else:
                median = (
                    (finite_values[midpoint - 1] / scale + finite_values[midpoint] / scale)
                    / 2.0
                    * scale
                )
        if finite_count >= 2:
            if scale == 0:
                variance = 0.0
                standard_deviation = 0.0
            else:
                normalized_mean_for_variance = (
                    math.fsum(value / scale for value in finite_values) / finite_count
                )
                normalized_variance = math.fsum(
                    (value / scale - normalized_mean_for_variance) ** 2 for value in finite_values
                ) / (finite_count - 1)
                candidate_deviation = math.sqrt(normalized_variance) * scale
                candidate_variance = normalized_variance * scale * scale
                if normalized_variance > 0 and candidate_deviation == 0:
                    warnings.append("sample standard deviation underflowed float64 range")
                elif math.isfinite(candidate_deviation):
                    standard_deviation = candidate_deviation
                else:
                    warnings.append("sample standard deviation overflowed float64 range")
                if normalized_variance > 0 and candidate_variance == 0:
                    warnings.append("sample variance underflowed float64 range")
                elif math.isfinite(candidate_variance):
                    variance = candidate_variance
                else:
                    warnings.append("sample variance overflowed float64 range")
    return NumericStatistics(
        observation_count=observation_count,
        finite_count=finite_count,
        missing_count=missing,
        positive_infinity_count=positive_infinity,
        negative_infinity_count=negative_infinity,
        available_coverage=finite_count / observation_count if observation_count else 0.0,
        minimum=float(np.min(finite)) if finite_count else None,
        maximum=float(np.max(finite)) if finite_count else None,
        mean=mean,
        median=median,
        standard_deviation=standard_deviation,
        variance=variance,
        calculation_warnings=tuple(warnings),
    )


def json_numeric(values: Iterable[float]) -> tuple[float | str | None, ...]:
    result: list[float | str | None] = []
    for value in values:
        numeric = float(value)
        if np.isnan(numeric):
            result.append(None)
        elif np.isposinf(numeric):
            result.append("+Infinity")
        elif np.isneginf(numeric):
            result.append("-Infinity")
        else:
            result.append(numeric)
    return tuple(result)
