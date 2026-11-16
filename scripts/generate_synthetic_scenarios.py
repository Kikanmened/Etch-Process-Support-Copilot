#!/usr/bin/env python3
"""Generate deterministic, scientifically bounded synthetic etch scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from etch_copilot.synthetic import SyntheticGeneratorConfig, generate_synthetic_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the isolated S1-S3 synthetic etch demonstration dataset."
    )
    parser.add_argument("--output", type=Path, required=True, help="Empty output directory")
    parser.add_argument("--seed", type=int, default=20261112, help="Deterministic RNG seed")
    parser.add_argument(
        "--truth-output",
        type=Path,
        help="Optional separate test-only directory for scenario_truth.json",
    )
    parser.add_argument("--baseline-runs", type=int, default=30)
    parser.add_argument("--incident-runs", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = SyntheticGeneratorConfig(
        seed=args.seed,
        baseline_runs_per_scenario=args.baseline_runs,
        incident_runs_per_scenario=args.incident_runs,
    )
    result = generate_synthetic_dataset(
        args.output,
        config,
        truth_directory=args.truth_output,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
