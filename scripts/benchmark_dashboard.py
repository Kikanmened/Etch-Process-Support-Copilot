"""Measure public presentation calls on installed local fixtures (no analytical caching)."""

import json
import resource
import sys
import time

from etch_copilot.dashboard.artifacts import write_verification_artifact
from etch_copilot.dashboard.service import DashboardService


def main() -> None:
    service = DashboardService()
    timings = {}
    for key in ("synthetic", "bosch", "phm"):
        start = time.perf_counter()
        if key == "synthetic":
            result = service.synthetic("S2")
        elif key == "bosch":
            catalog = service.catalog(key)
            run = next(iter(catalog["runs"]))
            result = service.bosch(run, catalog["runs"][run][0])
        else:
            result = service.phm(service.catalog(key)["equipment"][0])
        elapsed = time.perf_counter() - start
        start = time.perf_counter()
        exported = service.export(result)
        timings[key] = {
            "analysis_seconds": elapsed,
            "fresh_export_seconds": time.perf_counter() - start,
            "export_bytes": len(exported),
        }
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {
        "timings": timings,
        "process_peak_rss_mib": rss / (1024**2 if sys.platform == "darwin" else 1024),
        "python": sys.version.split()[0],
        "scope": "single process, sequential local fixture operations",
    }
    write_verification_artifact("performance.json", (json.dumps(report, indent=2) + "\n").encode())
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
