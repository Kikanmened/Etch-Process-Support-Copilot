#!/usr/bin/env python3
"""Generate local, readiness-gated Phase 2 analytics artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from etch_copilot.analytics import (
    bosch_compare_runs,
    bosch_elapsed_trend,
    bosch_metrology_coverage,
    bosch_sensor_statistics,
    phm_fault_inventory,
    phm_feature_inventory,
)
from etch_copilot.analytics.reporting import write_analytics_results
from etch_copilot.loaders import load_bosch_dataset, load_phm_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bosch", type=Path, default=Path("data/external/bosch"))
    parser.add_argument(
        "--phm",
        type=Path,
        default=Path("data/external/phm_ion_mill_2018/compact"),
    )
    parser.add_argument("--output", type=Path, default=Path("data/processed/analytics"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bosch = load_bosch_dataset(args.bosch)
    phm = load_phm_dataset(args.phm)
    common_features = set(bosch.runs[0].values.columns)
    for run in bosch.runs[1:]:
        common_features.intersection_update(run.values.columns)
    if len(bosch.runs) < 2 or not common_features:
        raise RuntimeError("BOSCH analytics runner requires two runs with a common source feature")
    run_ids = (bosch.runs[0].metadata.run_id, bosch.runs[1].metadata.run_id)
    feature = sorted(common_features)[0]
    results = {
        "bosch_elapsed_trend": bosch_elapsed_trend(bosch, run_ids[0], feature),
        "bosch_metrology_coverage": bosch_metrology_coverage(bosch),
        "bosch_run_comparison": bosch_compare_runs(bosch, run_ids, feature),
        "bosch_sensor_statistics": bosch_sensor_statistics(bosch, run_ids[0], feature),
        "phm_fault_inventory": phm_fault_inventory(phm),
        "phm_feature_inventory": phm_feature_inventory(phm),
    }
    for path in write_analytics_results(results, args.output):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
