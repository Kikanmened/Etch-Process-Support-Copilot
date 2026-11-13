from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook


@pytest.fixture
def phm_fixture(tmp_path: Path) -> Path:
    directory = tmp_path / "phm"
    directory.mkdir()
    observations = pd.DataFrame(
        {
            "time": [100, 110, 120],
            "Tool": ["01M01"] * 3,
            "stage": [1, 1, 2],
            "Lot": [7, 7, 7],
            "runnum": [42, 42, 42],
            "recipe": [3, 3, 3],
            "recipe_step": [1.0, 1.0, 2.0],
            "SENSOR_A": [0.1, 0.2, 0.3],
        }
    )
    observations.to_parquet(directory / "equipment_sensor_data.parquet", index=False)
    pd.DataFrame({"time": [110], "fault_name": ["recorded shutdown"], "Tool": ["01M01"]}).to_csv(
        directory / "fault_events.csv", index=False
    )
    (directory / "dataset_manifest.json").write_text(
        json.dumps({"retained_sensor_rows": 3, "retained_fault_rows": 1}), encoding="utf-8"
    )
    (directory / "validation_report.json").write_text("{}", encoding="utf-8")
    (directory / "README.md").write_text("test fixture", encoding="utf-8")
    return directory


@pytest.fixture
def bosch_fixture(tmp_path: Path) -> Path:
    directory = tmp_path / "bosch"
    directory.mkdir()
    with h5py.File(directory / "Dictionary_process.nc", "w") as handle:
        handle.create_dataset("data", data=np.array([0.0, 1.5, 2.5], dtype=np.float32))
    with h5py.File(directory / "Process_data.nc", "w") as handle:
        group = handle.create_group("Day_2024_07_02_Wafer_01")
        group.create_dataset("data", data=np.array([[1], [2]], dtype=np.uint16))
        group.create_dataset("feature", data=np.array(["pressure"], dtype=h5py.string_dtype()))
        times = group.create_dataset("times", data=np.array([90.0, 90.2]))
        times.attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"
    pd.DataFrame(
        {
            "experiment_key": ["2024-07-02_01"],
            "lot_number": [1],
            "wafer_number": [1],
            "X": [0],
            "Y": [0],
            "preox_thickness": [1.0],
            "postox_thickness": [0.5],
            "postox_thickness_nan": [0.5],
            "stepheight": [50.0],
            "oxide_etch": [0.5],
            "si_etch": [49.5],
        }
    ).to_csv(directory / "Si_Oxide_etch_89_points.csv", index=False)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["Lot No.", "Date", "Wafers", "Measurements", "Type"])
    worksheet.append(["Lot 1", "2 July 2024", 1, "89 points", "test"])
    workbook.save(directory / "Lot_status.xlsx")
    return directory
