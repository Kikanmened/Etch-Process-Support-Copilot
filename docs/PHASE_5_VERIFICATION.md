# Phase 5 implementation and review record

Verified locally on 2026-11-16, Python 3.12.13, macOS ARM64.
Implementation snapshot reviewed on `feature/phase-5-engineering-dashboard` before
controlled Git integration. The results below describe that dated local verification.

## Delivered

All five read-only Streamlit sections are implemented through the public backend APIs:
readiness overview, BOSCH trends/statistics/compatible comparisons/metrology inventory,
synthetic candidate SPC, PHM equipment/event inventory, and provenance/verified JSON.
No engineering formulas or backend readiness policies changed. Optional UI/test extras,
loopback configuration, offline browser checks and portfolio captures are included.

The [dashboard guide](ENGINEERING_DASHBOARD.md) documents installation, architecture,
scientific interpretation, source registry, budgets and reproduction commands.

## Final verification

| Check | Result |
| --- | --- |
| Full pytest suite | 172 passed in 35.57 seconds |
| Statement coverage | 94% reported; 2,836 of 3,032 statements covered |
| Dashboard modules | 459 of 484 statements covered, approximately 95% |
| Ruff format and lint | Passed |
| Strict mypy | Passed for 29 source/script files |
| Documentation | Relative references resolve; code fences balanced |
| Git whitespace validation | Passed |
| Browser | Chromium, 1440/768/390-pixel viewports; no browser errors |
| Offline smoke | All non-loopback HTTP blocked; zero external requests |
| Downloads | Two independently activated downloads produced identical verified JSON |
| Git exclusions | Screenshots/generated reports/external data/four reference PDFs remain excluded |

The 22 added dashboard tests cover AppTest interactions, backend numerical agreement,
scenario and session isolation, source changes, missing inputs, integrity forgery,
symlinks, output writes, limits, optional dependencies, deterministic exports,
verified units, extrema, missing-data gaps and transition boundaries.

The real-browser test exercises all five sections, S1/S3 refusal, S2 candidate charts,
BOSCH evidence, PHM inventory and deferred JSON downloads. Captures were refreshed
against a restarted server after final changes.

## Scientific outcomes and review

For the committed synthetic demo, S1 remains blocked by baseline admission, S2 receives
synthetic candidate limits and incident evaluation, and S3 remains blocked by invalid
metrology. Outcomes come from backend results. Operational SPC and real-data SPC remain
blocked. No physical root cause or metrology accuracy is asserted.

The scientific review found and resolved three presentation issues:

- Individuals traces now break at every unverified transition and distinguish Phase I/II.
- Engineering-unit axes honor the backend `unit_verified` flag.
- Missing optional references use an explicit absent status and null hash.

Bugbot approved with no correctness findings. A subsequent final code review approved
the security changes and UI refinements. The comparison picker excludes the primary
run and adds it automatically to additional compatible runs; the backend continues to
reject invalid one-run comparisons. A browser-discovered repeated-download race was
fixed by avoiding a redundant rerun while retaining request-time source verification.

## Security findings and resolutions

Locations below identify the reviewed pre-fix snapshot; current line numbers may differ.

| Severity | Location (file:line) | Finding |
| --- | --- | --- |
| MEDIUM | `src/etch_copilot/dashboard/service.py:131` | Fixed: caller-recomputed checksums could accompany relabelled evidence. A process-local HMAC now binds scope, sources and payload digest. |
| MEDIUM | `scripts/benchmark_dashboard.py:40` | Fixed: output paths could follow symlinks. The script now uses fixed-root, descriptor-relative atomic writes. |
| MEDIUM | `scripts/verify_dashboard_browser.py:14` | Fixed: screenshot/report path writes could follow symlinks. Captured bytes now use the same no-follow writer. |
| LOW | `src/etch_copilot/dashboard/service.py:72` | Fixed: synthetic directory enumeration could materialize unlimited names. Enumeration now rejects unexpected or excess entries immediately. |

Separate security re-review found no remaining concrete issue in the requested scope.
Built-in table CSV/copy and chart-image exports are disabled; supported JSON exports
reverify source fingerprints on each button activation. Neither unsafe metadata,
absolute source paths nor hidden scenario truth is included in the export projection.

## Measured local performance

| Investigation | Analysis including selection discovery | Fresh export | JSON bytes |
| --- | --- | --- | --- |
| Synthetic S2 | 0.456 s | 1.32 ms | 36,856 |
| BOSCH default run/feature | 2.218 s | 5.14 ms | 185,940 |
| PHM default equipment | 2.125 s | 1.51 ms | 16,872 |

Peak RSS for the sequential benchmark process: **421.7 MiB**. These measurements meet
the documented local targets of less than 10 seconds per default investigation and
less than 1 GiB peak RSS. They are fixture-specific, not worst-case guarantees for every
allowed input or multiple concurrent browser sessions.

## Captures and remaining limitations

Generated artifacts are intentionally ignored by Git in `data/processed/dashboard/`:
`bosch-desktop.png`, `synthetic-s2-desktop.png`, tablet/mobile captures,
`browser-verification.json`, `performance.json` and `coverage.json`.

Existing scientific restrictions remain: unverified BOSCH units, metrology reconstruction
limits, PHM sampling/event semantics, and synthetic-only candidate SPC. Browser tests
do not constitute full accessibility certification.

Freshness is checked on application actions, not continuously in an untouched browser.
Already displayed data, completed downloads and temporarily retained Streamlit media URLs
cannot be revoked. A strict per-HTTP-retrieval freshness requirement or remote/multi-user
deployment would need a separate authenticated export design. No such deployment is included.

There are no unresolved defects requiring an implementation decision within the approved
local-only Phase 5 scope. Controlled integration preserves this implementation; remote
Git actions remain with the user. See the root README for portable versus provisioned
test instructions and the tracked test-only truth-fixture policy.
