from pathlib import Path

import pytest

from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset
from etch_copilot.qualification import (
    AnalysisId,
    ReadinessStatus,
    build_bosch_qualification,
    build_phm_qualification,
    event_coordinate_coverage,
)


@pytest.mark.integration
def test_actual_bosch_qualification_findings() -> None:
    qualification = build_bosch_qualification(load_bosch_dataset(Path("data/external/bosch")))

    assert qualification.metrology.process_run_count == 96
    assert qualification.metrology.metrology_wafer_count == 88
    assert qualification.metrology.total_site_records == 7_832
    assert qualification.metrology.missing_raw_post_thickness_sites == 157
    assert all(wafer.relationship_unambiguous for wafer in qualification.metrology.wafers)
    assert qualification.features.common_feature_count == 31
    assert qualification.features.total_feature_count == 44
    assert qualification.decision(AnalysisId.BOSCH_ETCH_RATE).status is ReadinessStatus.BLOCKED


@pytest.mark.integration
def test_actual_phm_event_and_duplicate_qualification() -> None:
    dataset = load_phm_dataset(Path("data/external/phm_ion_mill_2018/compact"))
    qualification = build_phm_qualification(dataset)
    coverage = event_coordinate_coverage(dataset)

    assert qualification.duplicates.exact_duplicate_count == 5
    assert len(coverage) == 19
    assert sum(item.exact_match for item in coverage) == 8
    assert all(item.previous_coordinate is not None for item in coverage)
    assert all(item.following_coordinate is not None for item in coverage)
