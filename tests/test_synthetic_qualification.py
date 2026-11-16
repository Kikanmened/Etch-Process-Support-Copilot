from __future__ import annotations

from pathlib import Path

import pytest

from etch_copilot.models import DatasetLoadError
from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic import (
    SyntheticCapability,
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
    qualify_synthetic_dataset,
)


def test_qualification_is_scenario_scoped_and_preserves_calculation_blocks(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=99))

    report = qualify_synthetic_dataset(load_synthetic_dataset(output))
    s1 = report.scenario("S1")
    s2 = report.scenario("S2")
    s3 = report.scenario("S3")

    assert s1.status(SyntheticCapability.INGESTION) is ReadinessStatus.SUPPORTED
    assert s2.status(SyntheticCapability.INGESTION) is ReadinessStatus.SUPPORTED
    assert s3.status(SyntheticCapability.INGESTION) is ReadinessStatus.SUPPORTED
    assert s1.status(SyntheticCapability.ETCH_RATE_INPUTS) is ReadinessStatus.SUPPORTED
    assert s2.status(SyntheticCapability.UNIFORMITY_INPUTS) is ReadinessStatus.SUPPORTED
    assert s3.status(SyntheticCapability.ETCH_RATE_INPUTS) is ReadinessStatus.BLOCKED
    assert s3.status(SyntheticCapability.UNIFORMITY_INPUTS) is ReadinessStatus.BLOCKED
    for scenario in report.scenarios:
        assert scenario.status(SyntheticCapability.SPC_CONTROL_LIMITS) is ReadinessStatus.BLOCKED
        assert (
            scenario.status(SyntheticCapability.ROOT_CAUSE_ATTRIBUTION) is ReadinessStatus.BLOCKED
        )


def test_qualification_does_not_modify_external_dataset_readiness(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=99))

    report = qualify_synthetic_dataset(load_synthetic_dataset(output))

    assert report.dataset_id.startswith("synthetic-etch-demo-")
    assert report.external_dataset_effect == "none; BOSCH and PHM readiness decisions are unchanged"


def test_qualification_rejects_mutated_in_memory_dataset(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    generate_synthetic_dataset(output, SyntheticGeneratorConfig(seed=99))
    dataset = load_synthetic_dataset(output)
    s1_index = dataset.metrology.index[dataset.metrology["scenario_id"] == "S1"][0]
    dataset.metrology.loc[s1_index, "post_thickness_nm"] = 5000.0

    with pytest.raises(DatasetLoadError, match="in-memory content changed"):
        qualify_synthetic_dataset(dataset)
