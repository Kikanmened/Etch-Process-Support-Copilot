#!/usr/bin/env python3
"""Generate local engineering-qualification and readiness reports."""

from __future__ import annotations

import argparse
from pathlib import Path

from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset
from etch_copilot.qualification import build_bosch_qualification, build_phm_qualification
from etch_copilot.qualification_reports import write_qualification_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bosch", type=Path, default=Path("data/external/bosch"))
    parser.add_argument(
        "--phm",
        type=Path,
        default=Path("data/external/phm_ion_mill_2018/compact"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/qualifications"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bosch = build_bosch_qualification(load_bosch_dataset(args.bosch))
    phm = build_phm_qualification(load_phm_dataset(args.phm))
    for path in write_qualification_reports(bosch, phm, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
