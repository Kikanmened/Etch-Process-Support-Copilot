"""Freshness-checked orchestration of public engineering APIs; no analytical cache."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from etch_copilot.analytics import (
    bosch_compare_runs,
    bosch_elapsed_trend,
    bosch_metrology_coverage,
    bosch_sensor_statistics,
    phm_fault_inventory,
    phm_feature_inventory,
    phm_sensor_trend,
)
from etch_copilot.dashboard.views import DashboardError, project
from etch_copilot.loaders import BOSCH_REQUIRED, PHM_REQUIRED, load_bosch_dataset, load_phm_dataset
from etch_copilot.provenance import sha256_file
from etch_copilot.qualification import build_bosch_qualification, build_phm_qualification
from etch_copilot.synthetic import (
    evaluate_synthetic_candidate_spc,
    load_synthetic_dataset,
    qualify_synthetic_candidate_baseline,
    qualify_synthetic_dataset,
)
from etch_copilot.synthetic.contracts import VISIBLE_FILENAMES

MAX_EXPORT = 10 * 1024 * 1024
MAX_RETAINED = 32 * 1024 * 1024
_EVIDENCE_KEY = secrets.token_bytes(32)
ROOT = Path(__file__).resolve().parents[3]
LOCATIONS = {
    "bosch": "data/external/bosch",
    "phm": "data/external/phm_ion_mill_2018/compact",
    "synthetic": "data/synthetic/demo-v1",
}


@dataclass(frozen=True)
class Registry:
    """Application-owned root. The UI never accepts a root or filesystem path."""

    root: Path = ROOT

    def path(self, key: str) -> Path:
        if key not in LOCATIONS:
            raise DashboardError("Unknown dataset selection.")
        path = self.root / LOCATIONS[key]
        self.check_path(path)
        return path

    def check_path(self, path: Path) -> None:
        if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(self.root):
            raise DashboardError("Dataset location is outside the trusted registry.")
        for component in (path, *path.parents):
            if component.is_symlink():
                raise DashboardError("Linked dataset locations are not allowed.")

    def fingerprints(self, key: str) -> tuple[tuple[str, str], ...]:
        directory = self.path(key)
        if not directory.is_dir():
            raise DashboardError(
                "Dataset unavailable. Install the documented local research files."
            )
        names = {"bosch": BOSCH_REQUIRED, "phm": PHM_REQUIRED, "synthetic": VISIBLE_FILENAMES}[key]
        if key == "synthetic":
            seen: set[str] = set()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.name not in names or len(seen) >= len(names):
                        raise DashboardError(
                            "Synthetic dataset boundary rejected unexpected content."
                        )
                    seen.add(entry.name)
            if seen != set(names):
                raise DashboardError("Synthetic dataset boundary rejected missing content.")
        paths = [(name, directory / name, False) for name in names]
        if key == "bosch":
            paths += [
                ("Readme.pdf", directory / "Readme.pdf", True),
                ("research-reference", directory.parent / "research/Readme.pdf", True),
            ]
        result: list[tuple[str, str]] = []
        for name, path, optional in paths:
            self.check_path(path)
            if optional and not path.exists():
                result.append((name, "absent"))
                continue
            try:
                info = path.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024 * 1024:
                    raise DashboardError("Source type or size exceeds the dashboard limit.")
                result.append((name, sha256_file(path)))
            except OSError as exc:
                raise DashboardError("A required source is unavailable or unreadable.") from exc
        return tuple(sorted(result))


@dataclass(frozen=True)
class Evidence:
    dataset: str
    selection: str
    fingerprints: tuple[tuple[str, str], ...]
    payload: bytes
    digest: str
    seal: str

    def data(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(self.payload)
        return value


@dataclass
class ResultStore:
    """Bounded per-session snapshots; verified by the service before every use."""

    entries: OrderedDict[str, Evidence] = field(default_factory=OrderedDict)

    def put(self, key: str, evidence: Evidence) -> None:
        if len(evidence.payload) > MAX_EXPORT:
            raise DashboardError("Result exceeds the export budget. Narrow the selection.")
        self.entries.pop(key, None)
        self.entries[key] = evidence
        while (
            len(self.entries) > 3
            or sum(len(x.payload) for x in self.entries.values()) > MAX_RETAINED
        ):
            self.entries.popitem(last=False)


class DashboardService:
    def __init__(self, registry: Registry | None = None) -> None:
        self.registry = registry or Registry()

    def verify(self, result: Evidence) -> None:
        if hashlib.sha256(result.payload).hexdigest() != result.digest or not hmac.compare_digest(
            result.seal, _seal(result.dataset, result.selection, result.fingerprints, result.digest)
        ):
            raise DashboardError("Retained result integrity failed. Run the analysis again.")
        if self.registry.fingerprints(result.dataset) != result.fingerprints:
            raise DashboardError(
                "Sources changed. Retained evidence was invalidated; rerun analysis."
            )

    def export(self, result: Evidence) -> bytes:
        self.verify(result)
        if len(result.payload) > MAX_EXPORT:
            raise DashboardError("Export exceeds the allowed size.")
        return result.payload

    def _pack(
        self,
        key: str,
        selection: str,
        before: tuple[tuple[str, str], ...],
        results: dict[str, BaseModel | dict[str, Any]],
    ) -> Evidence:
        if self.registry.fingerprints(key) != before:
            raise DashboardError("Sources changed during analysis. Retry with stable source files.")
        payload = {
            "export_schema_version": "1.0.0",
            "dataset_kind": key,
            "evidence_origin": "synthetic" if key == "synthetic" else "research",
            "sources": [
                {
                    "source_file": name,
                    "status": "absent" if digest == "absent" else "verified",
                    "sha256": None if digest == "absent" else digest,
                }
                for name, digest in before
            ],
            "results": {name: project(value) for name, value in results.items()},
        }
        encoded = (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_EXPORT:
            raise DashboardError("Result exceeds the export budget. Narrow the selection.")
        digest = hashlib.sha256(encoded).hexdigest()
        return Evidence(
            key, selection, before, encoded, digest, _seal(key, selection, before, digest)
        )

    def catalog(self, key: str) -> dict[str, Any]:
        before = self.registry.fingerprints(key)
        directory = self.registry.path(key)
        if key == "bosch":
            data = load_bosch_dataset(directory)
            catalog: dict[str, Any] = {
                "runs": {run.metadata.run_id: list(run.values.columns) for run in data.runs},
                "wafers": sorted(set(data.metrology["experiment_key"].astype(str))),
            }
        elif key == "phm":
            phm = load_phm_dataset(directory)
            catalog = {
                "equipment": sorted(
                    set(phm.observations["Tool"].dropna().astype(str))
                    | {event.equipment_id for event in phm.faults if event.equipment_id}
                )
            }
        else:
            synthetic = load_synthetic_dataset(directory)
            catalog = {"scenarios": [s.value for s in synthetic.manifest.scenarios]}
        if self.registry.fingerprints(key) != before:
            raise DashboardError("Sources changed during selection discovery.")
        return catalog

    def readiness(self, key: str) -> Evidence:
        before = self.registry.fingerprints(key)
        directory = self.registry.path(key)
        if key == "bosch":
            report = build_bosch_qualification(load_bosch_dataset(directory))
            result: BaseModel | dict[str, Any] = {
                "dataset_id": report.dataset_id,
                "engine_version": report.engine_version,
                "readiness": report.readiness,
            }
        elif key == "phm":
            phm = build_phm_qualification(load_phm_dataset(directory))
            result = {
                "dataset_id": phm.dataset_id,
                "engine_version": phm.engine_version,
                "readiness": phm.readiness,
            }
        else:
            dataset = load_synthetic_dataset(directory)
            result = qualify_synthetic_dataset(dataset)
            admissions = [
                qualify_synthetic_candidate_baseline(dataset, scenario)
                for scenario in dataset.manifest.scenarios
            ]
            return self._pack(
                key,
                "readiness",
                before,
                {"readiness": result, "candidate_admission": {"scenarios": admissions}},
            )
        return self._pack(key, "readiness", before, {"readiness": result})

    def synthetic(self, scenario: str) -> Evidence:
        if scenario not in ("S1", "S2", "S3"):
            raise DashboardError("Invalid scenario selection.")
        before = self.registry.fingerprints("synthetic")
        dataset = load_synthetic_dataset(self.registry.path("synthetic"))
        qualification = qualify_synthetic_candidate_baseline(dataset, scenario)
        results: dict[str, BaseModel | dict[str, Any]] = {"qualification": qualification}
        if qualification.baseline is not None:
            results["evaluation"] = evaluate_synthetic_candidate_spc(
                dataset, qualification.baseline
            )
        return self._pack("synthetic", scenario, before, results)

    def bosch(
        self,
        run: str,
        feature: str,
        comparisons: tuple[str, ...] = (),
        wafers: tuple[str, ...] = (),
    ) -> Evidence:
        if len(comparisons) > 10 or len(wafers) > 50:
            raise DashboardError("Select at most 10 comparison runs and 50 wafers.")
        before = self.registry.fingerprints("bosch")
        dataset = load_bosch_dataset(self.registry.path("bosch"))
        results: dict[str, BaseModel | dict[str, Any]] = {
            "trend": bosch_elapsed_trend(dataset, run, feature),
            "statistics": bosch_sensor_statistics(dataset, run, feature),
        }
        if comparisons:
            results["comparison"] = bosch_compare_runs(dataset, comparisons, feature)
        if wafers:
            results["metrology"] = bosch_metrology_coverage(dataset, wafers)
        return self._pack(
            "bosch", bosch_selection(run, feature, comparisons, wafers), before, results
        )

    def phm(self, equipment: str) -> Evidence:
        before = self.registry.fingerprints("phm")
        dataset = load_phm_dataset(self.registry.path("phm"))
        return self._pack(
            "phm",
            equipment,
            before,
            {
                "features": phm_feature_inventory(dataset, equipment),
                "events": phm_fault_inventory(dataset, equipment),
                "sensor_trend": phm_sensor_trend(dataset, equipment),
            },
        )


def bosch_selection(
    run: str, feature: str, comparisons: tuple[str, ...], wafers: tuple[str, ...]
) -> str:
    """Bind retained evidence to the entire requested scope, without delimiter collisions."""
    return json.dumps([run, feature, comparisons, wafers], ensure_ascii=True)


def _seal(
    dataset: str, selection: str, fingerprints: tuple[tuple[str, str], ...], digest: str
) -> str:
    """Bind trusted server-issued evidence to its full scope; never sent to the browser."""
    value = json.dumps([dataset, selection, fingerprints, digest], separators=(",", ":")).encode()
    return hmac.new(_EVIDENCE_KEY, value, hashlib.sha256).hexdigest()
