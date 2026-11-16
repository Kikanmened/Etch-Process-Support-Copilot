#!/usr/bin/env python3
"""Run readiness-gated synthetic candidate SPC qualification and evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from etch_copilot.synthetic import (
    ScenarioId,
    evaluate_synthetic_candidate_spc,
    load_synthetic_dataset,
    qualify_synthetic_candidate_baseline,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify synthetic candidate I-MR baselines; never emits operational control limits."
        )
    )
    parser.add_argument("dataset", type=Path, help="Qualified synthetic dataset directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_synthetic_dataset(args.dataset)
    results: dict[str, object] = {}
    for scenario in ScenarioId:
        qualification = qualify_synthetic_candidate_baseline(dataset, scenario)
        payload: dict[str, object] = {"qualification": qualification.model_dump(mode="json")}
        if qualification.baseline is not None:
            payload["evaluation"] = evaluate_synthetic_candidate_spc(
                dataset, qualification.baseline
            ).model_dump(mode="json")
        results[scenario.value] = payload
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
