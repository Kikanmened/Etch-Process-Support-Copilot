"""Readiness-gated deterministic inventories for the PHM dataset."""

from __future__ import annotations

import json
from collections import Counter

import numpy as np
import pandas as pd

from etch_copilot.analytics.contracts import (
    AnalyticsScopeError,
    CategoryCount,
    FaultEventRecord,
    FeatureInventoryItem,
    MetadataItem,
    PhmFaultInventoryResult,
    PhmFeatureInventoryResult,
)
from etch_copilot.analytics.policies import analysis_context, authorize_phm
from etch_copilot.loaders import PHM_ID_COLUMNS, PhmDataset
from etch_copilot.qualification import (
    AnalysisId,
    build_phm_qualification,
    canonicalize_phm_equipment_id,
)

_MAX_FAULT_EVENT_RECORDS = 50_000


def _feature_item(frame: pd.DataFrame, feature: str) -> FeatureInventoryItem:
    series = frame[feature]
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float64)
    invalid_non_numeric = int((pd.isna(numeric) & series.notna().to_numpy()).sum())
    return FeatureInventoryItem(
        source_name=feature,
        recorded_dtype=str(series.dtype),
        observation_count=len(series),
        finite_count=int(np.isfinite(numeric).sum()),
        missing_count=int(series.isna().sum()),
        positive_infinity_count=int(np.isposinf(numeric).sum()),
        negative_infinity_count=int(np.isneginf(numeric).sum()),
        invalid_non_numeric_count=invalid_non_numeric,
        repeated_value_count=int(series.duplicated(keep="first").sum()),
        engineering_unit=None,
        unit_verified=False,
    )


def phm_feature_inventory(
    dataset: PhmDataset, equipment_id: str | None = None
) -> PhmFeatureInventoryResult:
    """Inventory source sensor fields without inferring units or removing duplicates."""
    decision, selected_ids, canonical, dataset = authorize_phm(
        dataset, AnalysisId.PHM_FEATURE_AVAILABILITY, equipment_id
    )
    frame = dataset.observations[dataset.observations["Tool"].astype(str).isin(selected_ids)]
    features = tuple(sorted(set(frame.columns) - set(PHM_ID_COLUMNS)))
    qualification = build_phm_qualification(dataset)
    metadata = tuple(
        MetadataItem(
            name=str(name),
            json_value=json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
        )
        for name, value in sorted(dataset.manifest.items(), key=lambda item: str(item[0]))
    )
    return PhmFeatureInventoryResult(
        **analysis_context(decision, dataset.provenance),
        source_equipment_ids=selected_ids,
        canonical_equipment_id=canonical,
        raw_observation_count=len(frame),
        exact_duplicate_count=int(frame.duplicated(keep="first").sum()),
        features=tuple(_feature_item(frame, feature) for feature in features),
        metadata=metadata,
        time_unit=qualification.time.unit,
        time_semantics="raw source coordinate; duration and calendar units unresolved",
        sampling_bias=qualification.time.extraction_bias,
    )


def phm_fault_inventory(
    dataset: PhmDataset, equipment_id: str | None = None
) -> PhmFaultInventoryResult:
    """Inventory recorded events without temporal analysis or onset interpretation."""
    decision, selected_ids, canonical, dataset = authorize_phm(
        dataset,
        AnalysisId.PHM_FAULT_EVENT_INVENTORY,
        equipment_id,
        include_fault_identifiers=True,
    )
    qualification = build_phm_qualification(dataset)
    events = tuple(
        (index, event)
        for index, event in enumerate(dataset.faults)
        if equipment_id is None
        or event.equipment_id in selected_ids
        or (
            canonical is not None
            and event.equipment_id is not None
            and canonicalize_phm_equipment_id(event.equipment_id, qualification.identifiers)
            == canonical
        )
    )
    if len(events) > _MAX_FAULT_EVENT_RECORDS:
        raise AnalyticsScopeError(
            AnalysisId.PHM_FAULT_EVENT_INVENTORY,
            decision.scope,
            (f"fault inventory exceeds {_MAX_FAULT_EVENT_RECORDS} event records",),
        )
    counts = Counter(event.fault_name for _, event in events)
    records = tuple(
        FaultEventRecord(
            source_index=index,
            source_equipment_id=event.equipment_id,
            canonical_equipment_id=(
                canonicalize_phm_equipment_id(event.equipment_id, qualification.identifiers)
                if event.equipment_id is not None
                else None
            ),
            category=event.fault_name,
            source_coordinate=event.event_time,
            coordinate_unit=qualification.time.unit,
            is_confirmed_fault_onset=False,
            missing_fields=tuple(
                name
                for name, value in (
                    ("source_coordinate", event.event_time),
                    ("fault_name", event.fault_name),
                    ("equipment_id", event.equipment_id),
                )
                if value is None or (isinstance(value, str) and not value)
            ),
        )
        for index, event in events
    )
    return PhmFaultInventoryResult(
        **analysis_context(decision, dataset.provenance),
        source_equipment_ids=selected_ids,
        canonical_equipment_id=canonical,
        total_recorded_events=len(records),
        category_counts=tuple(
            CategoryCount(category=category, count=count)
            for category, count in sorted(
                counts.items(), key=lambda item: "" if item[0] is None else item[0]
            )
        ),
        events=records,
        event_semantics=qualification.time.event_semantics,
        ambiguous_event_field_count=sum(bool(record.missing_fields) for record in records),
    )
