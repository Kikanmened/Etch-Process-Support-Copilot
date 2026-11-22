# Engineering dashboard — Phase 5

The dashboard is a read-only local presentation of the existing engineering APIs.
It does not qualify new statistical methods, control equipment, recommend recipes,
or establish physical root cause. Research datasets and synthetic demonstrations
are labelled separately. All operational SPC remains blocked.

## Install and launch

Use Python 3.12 (verified with 3.12.13) from the repository root:

```sh
uv sync --frozen --extra dashboard --extra dashboard-test --python 3.12
.venv/bin/streamlit run streamlit_app.py
```

Open the local address printed by Streamlit. The checked-in configuration binds
to `127.0.0.1`, disables usage telemetry and retains CORS/XSRF protection. Do not
override the bind address or expose this unauthenticated research workspace to a
network. The installed dashboard operates without an internet connection. Dependency
installation and optional Chromium installation require network access initially.

Backend-only installation remains `uv sync --frozen --python 3.12`; Streamlit, Plotly and
Playwright are optional extras. Dashboard interaction tests skip when the dashboard
extra is not installed. The presentation service itself imports no UI framework.
Install the dashboard extra when running strict mypy over the complete source tree.

## Trusted local inputs

The application accepts dataset identifiers, never uploaded files or filesystem paths.
The application-owned registry uses these repository-relative directories:

| Dataset | Fixed location | Evidence |
| --- | --- | --- |
| BOSCH | `data/external/bosch` | Recorded plasma-etch channels and metrology coverage |
| PHM | `data/external/phm_ion_mill_2018/compact` | Equipment feature and recorded-event inventory |
| Synthetic | `data/synthetic/demo-v1` | Public S1–S3 source contracts |

Missing external data produces an unavailable state. The application never downloads
research data. BOSCH's optional local `Readme.pdf` and sibling
`data/external/research/Readme.pdf` reference are included in freshness checks, including
their absence. The four standards PDFs remain excluded from Git. No new redistribution
permission is implied by this dashboard.

The approved `tests/fixtures/synthetic/demo-v1/scenario_truth.json` is tracked for tests
and reproducibility. It is excluded from application ingestion, not secret from repository
readers. Unintended truth-file copies are Git-ignored; the approved fixture stays unchanged.

## Architecture and public API mapping

`streamlit_app.py` → `dashboard.app` → `dashboard.service` → existing public backend.
`dashboard.views` projects explicit fields and chooses display points;
`dashboard.charts` renders those values without recomputing engineering statistics.

| Section | Public backend | Presentation |
| --- | --- | --- |
| Overview | `build_bosch_qualification`, `build_phm_qualification`, `qualify_synthetic_dataset`, `qualify_synthetic_candidate_baseline` | Readiness, prerequisites, limitations and candidate admission |
| BOSCH | `bosch_elapsed_trend`, `bosch_sensor_statistics`, `bosch_compare_runs`, `bosch_metrology_coverage` | Elapsed trends, descriptive statistics, compatible runs, reconstruction inventory |
| Synthetic | `qualify_synthetic_candidate_baseline`, `evaluate_synthetic_candidate_spc` | Admission issues; frozen candidate I-MR charts only when admitted |
| PHM | `phm_feature_inventory`, `phm_fault_inventory` | Missingness, retained duplicates, recorded event categories |
| Provenance | SHA-256 verification of fixed sources | Sanitized deterministic JSON; logical source names and explicit absence |

## Implemented page contract

The current Streamlit surface has five pages and no public HTTP routes. The controls below
are the complete user-facing action set:

| Page | User action | Service operation | External data required |
| --- | --- | --- | --- |
| Overview & readiness | Verify engineering readiness | `DashboardService.readiness` | No for synthetic; BOSCH/PHM only when selected |
| BOSCH process evidence | Discover, then analyze a run/feature | `catalog` + `DashboardService.bosch` | BOSCH files |
| Synthetic SPC investigations | Run S1, S2 or S3 candidate investigation | `DashboardService.synthetic` | No; committed fixture |
| PHM equipment evidence | Discover, then analyze equipment | `catalog` + `DashboardService.phm` | PHM files |
| Provenance & JSON exports | Download verified JSON from retained evidence | `DashboardService.export` | Same sources as selected evidence |

S1 and S3 are expected refusal demonstrations for the committed fixture; S2 is the
admitted synthetic candidate path. A download is available only after an analysis has
created retained evidence, and the service rechecks source fingerprints at download time.

The overview preserves the Phase 3 input-qualification contract verbatim, including its
historical SPC restriction; Phase 4 candidate admission is shown separately. Input
readiness does not authorize operational SPC. Outcome labels and signal counts are
derived from backend results, never scenario-name branches.

## Scientific interpretation

For the committed demo fixture, the backend rejects S1's candidate baseline and S3's
invalid metrology. These pages show actual admission issues and never call incident
evaluation. S2 is evaluated against its verified frozen baseline. Different qualified
sources may legitimately produce different outcomes; application logic does not assume
any scenario's admission result.

Candidate chart titles and legends identify synthetic, non-operational scope. Phase I
reference and Phase II incident observations are separate traces. Unverified process
transitions break Individuals lines; missing or inadmissible moving ranges remain gaps.
The estimator comparison displays the backend's MR/d2 and sample-standard-deviation
results; it does not select a new estimator or calculate new limits.

BOSCH engineering units are shown as verified only when the backend verifies them.
Elapsed coordinates do not establish shared wall-clock timing between runs. Comparison
requires at least two distinct compatible runs and is descriptive only. Metrology
coverage and reconstruction inventories do not authorize etch-rate or uniformity
calculations. PHM events are recorded categories, not confirmed fault onset; fault-centered
sampling and duplicates remain visible limitations.

See [deterministic analytics](DETERMINISTIC_ANALYTICS_CONTRACT.md),
[synthetic SPC methodology](SYNTHETIC_SPC_METHOD.md) and the
[engineering standards guide](ENGINEERING_STANDARDS_GUIDE.md) for governing assumptions.

## Freshness, isolation and budgets

- Each analysis fingerprints fixed sources before work and compares them after public
  backend calls. Retained results are reverified on each rerender and immediately before
  display. Deferred JSON generation repeats verification at the download request.
- A process-local HMAC binds each server-issued snapshot to its dataset, selection,
  fingerprints and payload digest. Replacing a status or relabelling an S2 result as S1
  invalidates the snapshot even if a caller recomputes its ordinary SHA-256 checksum.
- No Streamlit analytical, authorization or source-validation cache is used. Each session
  retains at most three serialized results, each at most 10 MiB, with a total 32 MiB budget.
  Selection catalogs retain identifiers only and are bound to source fingerprints.
- Symlinked sources or ancestor directories are rejected. Synthetic directories must
  contain exactly the public source filenames. Hidden truth is neither loaded nor exported.
- Explicit field projection excludes paths, arbitrary metadata and extraction notes.
  Dataset text is sanitized before display/export. No unsafe HTML is rendered.
- Built-in table CSV/copy and chart-image download controls are disabled so the supported export path is the
  freshness-checked JSON action. Displayed data still exists in the browser; this UI
  setting cannot prevent screenshots, developer-tools access or copying prior evidence.
- Existing bounded backend loaders remain authoritative for source allocation limits;
  each source file is limited to 64 MiB before hashing. Chart display is limited to 5,000
  BOSCH samples; original numerical evidence and full analytical exports are retained.
- Deterministic display selection preserves endpoints, global extrema, bucket extrema,
  missing-block edges and transition neighbors. If required critical points exceed the
  display budget, the chart is refused instead of silently deleting evidence. Synthetic
  charts retain all backend-bounded observations and signals.
- Exports contain sorted keys, deterministic UTF-8 JSON, finite numbers or explicit nulls,
  contract versions, readiness and candidate scope. Optional missing sources have
  `status: absent` and `sha256: null`, not a fabricated hash.

Freshness is checked at defined actions, not continuously while an untouched browser
view is open. Already downloaded files cannot be revoked; retain their source fingerprints
when sharing. Streamlit's already-generated media URLs may remain briefly replayable;
every new JSON-button activation still revalidates sources. Strict freshness on every
HTTP retrieval would require a different export endpoint. This is a local trusted-user
tool, not a multi-tenant security boundary.

## Verification and portfolio captures

On a fresh checkout without external research data, run
`.venv/bin/pytest -q -m "not integration"`. The full suite and the browser/benchmark
scripts below require the separately provisioned research datasets and reference.

```sh
.venv/bin/pytest -q --cov=etch_copilot --cov-report=term-missing
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
git diff --check
.venv/bin/python scripts/benchmark_dashboard.py
```

For browser verification, install Chromium once, start Streamlit in another terminal,
then run:

```sh
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/verify_dashboard_browser.py
```

The browser script denies all non-loopback HTTP requests, checks S2 charts and a verified
download, loads genuine BOSCH evidence, and captures desktop/tablet/mobile views.
Artifacts are under ignored `data/processed/dashboard/`. `bosch-desktop.png` and
`synthetic-s2-desktop.png` are reproducible portfolio captures from installed sources;
they do not substitute a screenshot for scientific qualification.

The test matrix covers public-result numerical agreement, S1/S2/S3 admission, full backend
regression, scenario switching, separate sessions, source mutation, symlinks, injected
truth files, sanitized fields, optional-source absence, deterministic export, retained-result
integrity, bounded storage, display extrema/gaps/transitions, units, AppTest interactions
and real-browser offline behavior. The benchmark records elapsed analysis/export time,
serialized size and process peak RSS. Local acceptance targets are under 10 seconds per
default investigation and below 1 GiB peak RSS for the sequential benchmark; these are
fixture-specific measurements, not guarantees for arbitrary files or concurrent sessions.

## Remaining scope limits

No GenAI, RAG, dashboard statistical estimators, production limits, root-cause confirmation,
equipment control or recommendation engine is included. Browser checks are smoke tests,
not a full accessibility certification. Tables provide numerical alternatives to chart color
and hover interactions. Dataset licensing and scientific measurement limitations continue
to apply to screenshots and exports.
