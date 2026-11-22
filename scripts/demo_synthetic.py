#!/usr/bin/env python3
"""Create the committed, no-download synthetic S2 demonstration artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from etch_copilot.dashboard.service import DashboardService
from etch_copilot.synthetic import load_synthetic_dataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "docs" / "examples" / "synthetic-s2-evidence.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the committed synthetic fixture and export admitted S2 evidence."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    dataset_path = ROOT / "data" / "synthetic" / "demo-v1"
    dataset = load_synthetic_dataset(dataset_path)
    evidence = DashboardService().synthetic("S2")
    payload = {
        "demo": {
            "input_manifest": dataset.manifest.model_dump(mode="json"),
            "validation": dataset.validation.model_dump(mode="json"),
            "allowed_analytics": "synthetic candidate SPC only; operational SPC remains blocked",
        },
        "evidence": evidence.data(),
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(f"Wrote deterministic S2 evidence artifact: {args.output}")


if __name__ == "__main__":
    main()
