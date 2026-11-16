from pathlib import Path

import pytest

from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset


@pytest.mark.integration
def test_actual_bosch_dataset_counts() -> None:
    dataset = load_bosch_dataset(Path("data/external/bosch"))

    assert dataset.validation.record_counts == {
        "process_runs": 96,
        "sensor_observations": 313_169,
        "metrology_sites": 7_832,
        "lot_status_rows": 35,
    }
    assert len(dataset.validation.identifier_relationships["runs_without_metrology"]) == 8


@pytest.mark.integration
def test_actual_phm_counts_are_independently_verified() -> None:
    dataset = load_phm_dataset(Path("data/external/phm_ion_mill_2018/compact"))

    assert dataset.validation.record_counts["sensor_observations"] == 67_379
    assert dataset.validation.record_counts["fault_events"] == 19
    assert dataset.validation.duplicate_counts["sensor_rows"] == 5
