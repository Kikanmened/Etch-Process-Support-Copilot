from __future__ import annotations

import json
from pathlib import Path

from etch_copilot.qualification import ReadinessStatus
from etch_copilot.synthetic import (
    SyntheticCapability,
    SyntheticGeneratorConfig,
    generate_synthetic_dataset,
    load_synthetic_dataset,
    qualify_synthetic_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_DATASET = PROJECT_ROOT / "data" / "synthetic" / "demo-v1"
DEMO_TRUTH = PROJECT_ROOT / "tests" / "fixtures" / "synthetic" / "demo-v1"


def test_committed_demo_dataset_matches_canonical_generator(tmp_path: Path) -> None:
    regenerated = tmp_path / "demo-v1"
    regenerated_truth = tmp_path / "truth"
    generate_synthetic_dataset(
        regenerated,
        SyntheticGeneratorConfig(seed=20261112),
        truth_directory=regenerated_truth,
    )

    committed_files = {
        path.name: path.read_bytes() for path in sorted(DEMO_DATASET.iterdir()) if path.is_file()
    }
    regenerated_files = {
        path.name: path.read_bytes() for path in sorted(regenerated.iterdir()) if path.is_file()
    }

    assert committed_files == regenerated_files
    assert (DEMO_TRUTH / "scenario_truth.json").read_bytes() == (
        regenerated_truth / "scenario_truth.json"
    ).read_bytes()


def test_committed_demo_is_qualified_without_exposing_truth() -> None:
    dataset = load_synthetic_dataset(DEMO_DATASET)
    report = qualify_synthetic_dataset(dataset)
    truth = json.loads((DEMO_TRUTH / "scenario_truth.json").read_text(encoding="utf-8"))

    assert dataset.validation.structurally_valid is True
    assert (
        report.scenario("S3").status(SyntheticCapability.ETCH_RATE_INPUTS)
        is ReadinessStatus.BLOCKED
    )
    assert truth["visibility"] == "test_fixture_only_not_for_application_ingestion_or_genai"
    assert "scenario_truth.json" not in dataset.provenance.source_files
