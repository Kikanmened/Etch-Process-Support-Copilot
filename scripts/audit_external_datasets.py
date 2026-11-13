#!/usr/bin/env python3
"""Audit the local BOSCH and PHM external datasets without modifying them."""

from __future__ import annotations

import argparse
from pathlib import Path

from etch_copilot.audit import write_reports
from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bosch", type=Path, default=Path("data/external/bosch"))
    parser.add_argument(
        "--phm",
        type=Path,
        default=Path("data/external/phm_ion_mill_2018/compact"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/audits"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    datasets = (load_bosch_dataset(args.bosch), load_phm_dataset(args.phm))
    for dataset in datasets:
        json_path, markdown_path = write_reports(dataset, args.output)
        print(f"{dataset.provenance.dataset_id}: {json_path} | {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
