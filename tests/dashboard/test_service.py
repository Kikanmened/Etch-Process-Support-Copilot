from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from etch_copilot.dashboard.service import DashboardError, DashboardService, Registry, ResultStore
from etch_copilot.dashboard.views import project, safe_text, select_indices

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def service(tmp_path: Path) -> DashboardService:
    shutil.copytree(ROOT / "data/synthetic/demo-v1", tmp_path / "data/synthetic/demo-v1")
    return DashboardService(Registry(tmp_path))


def test_readiness_is_backend_derived(service: DashboardService) -> None:
    for scenario, status in [("S1", "BLOCKED"), ("S2", "SUPPORTED"), ("S3", "BLOCKED")]:
        result = service.synthetic(scenario)
        payload = json.loads(service.export(result))
        assert payload["results"]["qualification"]["status"] == status
        assert ("evaluation" in payload["results"]) == (status == "SUPPORTED")
        assert "scenario_truth" not in service.export(result).decode()
        assert str(service.registry.root) not in service.export(result).decode()
        assert service.export(result) == service.export(result)
        assert service.synthetic(scenario).payload == result.payload


def test_source_change_and_new_unexpected_file_invalidate(service: DashboardService) -> None:
    result = service.synthetic("S2")
    target = service.registry.root / "data/synthetic/demo-v1/telemetry.csv"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(DashboardError):
        service.export(result)


def test_added_truth_file_invalidates(service: DashboardService) -> None:
    result = service.synthetic("S2")
    (service.registry.root / "data/synthetic/demo-v1/scenario_truth.json").write_text("{}")
    with pytest.raises(DashboardError):
        service.verify(result)


def test_selections_and_missing_data_fail_safely(service: DashboardService) -> None:
    with pytest.raises(DashboardError):
        service.synthetic("../S2")
    with pytest.raises(DashboardError):
        service.catalog("bosch")
    with pytest.raises(DashboardError):
        service.catalog("../../etc")


def test_downsampling_preserves_critical_points() -> None:
    values: list[float | None] = [float(i % 7) for i in range(100)]
    values[10] = 900.0
    values[80] = -900.0
    values[50] = None
    indices = select_indices(values, budget=20, required={33})
    assert {0, 99, 10, 80, 33, 49, 50, 51} <= set(indices)
    assert len(indices) <= 20
    assert indices == sorted(set(indices))
    with pytest.raises(DashboardError):
        select_indices(values, budget=2, required={33})


def test_text_removes_paths_markup_and_secret_fields() -> None:
    assert "/Users/" not in safe_text("failed /Users/private/data.csv")
    assert "<script>" not in safe_text("<script>alert(1)</script>")
    assert "https://" not in safe_text("https://secret.example/token")


def test_integrity_and_store_bounds(service: DashboardService) -> None:
    evidence = service.synthetic("S2")
    with pytest.raises(DashboardError, match="integrity"):
        service.export(replace(evidence, payload=b"{}"))
    with pytest.raises(DashboardError, match="integrity"):
        service.export(replace(evidence, selection="S1"))
    forged = evidence.data()
    forged["results"]["qualification"]["operational_control_limits_status"] = "SUPPORTED"
    forged_bytes = json.dumps(forged).encode()
    with pytest.raises(DashboardError, match="integrity"):
        service.export(
            replace(evidence, payload=forged_bytes, digest=hashlib.sha256(forged_bytes).hexdigest())
        )
    store = ResultStore()
    for key in ("one", "two", "three", "four"):
        store.put(key, evidence)
    assert list(store.entries) == ["two", "three", "four"]
    assert project(
        {
            "metadata": {"secret": "hidden"},
            "source_directory": "/private",
            "mean": float("inf"),
            "limitations": ["valid"],
        }
    ) == {"mean": None, "limitations": ["valid"]}


def test_symlink_source_rejected(service: DashboardService, tmp_path: Path) -> None:
    evidence = service.synthetic("S2")
    source = service.registry.path("synthetic") / "telemetry.csv"
    moved = tmp_path / "moved.csv"
    source.rename(moved)
    source.symlink_to(moved)
    with pytest.raises(DashboardError, match="Linked"):
        service.export(evidence)


def test_size_and_parent_link_rejected(service: DashboardService, tmp_path: Path) -> None:
    source = service.registry.path("synthetic") / "telemetry.csv"
    with source.open("ab") as handle:
        handle.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(DashboardError, match="size"):
        service.registry.fingerprints("synthetic")
    linked = tmp_path / "alias"
    linked.symlink_to(tmp_path / "data", target_is_directory=True)
    with pytest.raises(DashboardError, match="Linked"):
        service.registry.check_path(linked / "synthetic/demo-v1")


def test_external_numerical_agreement_and_optional_absence(
    tmp_path: Path,
    bosch_fixture: Path,
    phm_fixture: Path,
) -> None:
    from etch_copilot.analytics import bosch_sensor_statistics, phm_feature_inventory
    from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset

    shutil.copytree(bosch_fixture, tmp_path / "data/external/bosch")
    shutil.copytree(phm_fixture, tmp_path / "data/external/phm_ion_mill_2018/compact")
    service = DashboardService(Registry(tmp_path))
    catalog = service.catalog("bosch")
    run = next(iter(catalog["runs"]))
    feature = catalog["runs"][run][0]
    evidence = service.bosch(run, feature, (), tuple(catalog["wafers"]))
    backend = bosch_sensor_statistics(load_bosch_dataset(bosch_fixture), run, feature)
    assert evidence.data()["results"]["statistics"] == project(backend)
    assert all(
        item["sha256"] is None for item in evidence.data()["sources"] if item["status"] == "absent"
    )
    phm = service.phm("01M01")
    assert phm.data()["results"]["features"] == project(
        phm_feature_inventory(load_phm_dataset(phm_fixture), "01M01")
    )
    assert b"bosch" not in phm.payload
    assert service.readiness("bosch").data()["dataset_kind"] == "bosch"
    assert service.readiness("phm").data()["dataset_kind"] == "phm"


def test_source_change_during_calculation_rejected(
    service: DashboardService, monkeypatch: pytest.MonkeyPatch
) -> None:
    import etch_copilot.dashboard.service as module

    original = module.qualify_synthetic_candidate_baseline

    def changing(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        source = service.registry.path("synthetic") / "telemetry.csv"
        source.write_bytes(source.read_bytes() + b"\n")
        return result

    monkeypatch.setattr(module, "qualify_synthetic_candidate_baseline", changing)
    with pytest.raises(DashboardError, match="changed during"):
        service.synthetic("S1")
