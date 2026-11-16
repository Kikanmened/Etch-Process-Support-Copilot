# Etch Process Support Copilot

A read-only semiconductor engineering portfolio demonstrating how to qualify data
before interpreting it. The project combines real research-data ingestion, explicit
analysis-readiness gates, deterministic analytics and synthetic SPC method qualification
with a local engineering dashboard.

The current implementation is deterministic software, not a GenAI assistant. It does
not control equipment, recommend recipes or confirm physical root cause.

## Engineering workspace

| Section | What an engineer can inspect |
| --- | --- |
| Overview | Dataset availability, readiness decisions, prerequisites and limitations |
| BOSCH process evidence | Elapsed sensor trends, descriptive statistics, compatible run comparisons and metrology coverage/reconstruction inventory |
| Synthetic SPC | Baseline admission, frozen candidate Individuals–Moving Range charts, signals and transition boundaries |
| PHM equipment evidence | Sensor-feature inventory, missingness, duplicates and recorded event categories |
| Provenance | Source fingerprints, calculation versions and freshly verified JSON exports |

## Architecture

```text
Streamlit dashboard and display-only charts
                  |
Presentation service: fixed dataset registry, sanitized evidence,
source revalidation, bounded session results and verified exports
                  |
Public readiness-gated analytics and synthetic SPC APIs
                  |
Qualification contracts, source validation and SHA-256 provenance
                  |
Local research datasets / committed public synthetic fixtures
```

The UI reuses backend calculations. It does not independently compute engineering
statistics or override readiness decisions. Display sampling preserves critical points,
missing-data gaps and transition boundaries without changing analytical results.

Relevant modules are `src/etch_copilot/analytics/`, `qualification.py`,
`synthetic/` and `dashboard/`. See the
[dashboard architecture guide](docs/ENGINEERING_DASHBOARD.md) for the API mapping.

## Scientific boundaries

- `SUPPORTED`, `LIMITED` and `BLOCKED` are backend decisions, not UI preferences.
- Synthetic candidate limits are method demonstrations, never operational control limits.
  For the committed fixture, S1 fails baseline admission, S2 admits a frozen candidate
  baseline, and S3 is blocked by invalid metrology. Outcomes are computed from the data.
- Real BOSCH and PHM SPC and all operational SPC remain blocked.
- BOSCH source units are labelled unverified where appropriate. Coverage and reconstructed
  metrology do not establish measurement uncertainty or authorize unsupported calculations.
- PHM recorded events do not establish fault onset or diagnostic accuracy. Sampling bias
  and retained duplicates remain part of the interpretation.
- Synthetic values do not validate plasma physics, metrological traceability or causality.

The [engineering standards guide](docs/ENGINEERING_STANDARDS_GUIDE.md),
[analytics contract](docs/DETERMINISTIC_ANALYTICS_CONTRACT.md) and
[synthetic SPC method](docs/SYNTHETIC_SPC_METHOD.md) document these boundaries.

## Reproducible local setup

Use a repository checkout, Python 3.12 and an installed `uv` package manager.
Verification was performed on Python 3.12.13 / macOS ARM64. The verification tools use
POSIX filesystem protections; Windows support has not been established.

From the repository root:

```sh
uv sync --frozen --python 3.12 --extra dashboard --extra dashboard-test
.venv/bin/streamlit run streamlit_app.py
```

Streamlit prints the loopback address to open. Run from the repository root so its
checked-in configuration is applied. Access is bound to `127.0.0.1`, usage telemetry is
disabled and CORS/XSRF protection remains enabled. This is a local trusted-user workspace,
not a remotely deployed or multi-user service.

Dependency installation needs network access initially. The dashboard operates offline
after installation. For backend-only work, use `uv sync --frozen --python 3.12` without
the optional dashboard extras.

## Synthetic demonstration without research downloads

The public fixture in `data/synthetic/demo-v1/` is included in Git; no PDFs or external
research datasets are needed for this demonstration.

1. Launch the dashboard and open **Synthetic SPC investigations**.
2. Select **S2**, then **Run candidate investigation**. Inspect the frozen baseline ID,
   candidate I-MR charts, Phase I/II observations, signals and estimator comparison.
3. Run **S1** and **S3** to inspect the returned blocking explanations.
4. Open **Provenance & JSON exports** and download the verified evidence.

The approved `tests/fixtures/synthetic/demo-v1/scenario_truth.json` is deliberately
tracked as a reproducibility and evaluation fixture. It is hidden from the application,
not secret from repository readers. Production ingestion, analytics and the dashboard
never load it; application-visible source directories reject truth files. Unintended
truth-file copies are ignored. See the
[synthetic data contract](docs/SYNTHETIC_DATA_CONTRACT.md).

## Optional research datasets

Obtain research files separately under their applicable access and licensing terms.
This repository does not redistribute them or automatically download them. Use the
validated dataset versions; arbitrary similarly named files may fail validation.

| Local directory | Required files |
| --- | --- |
| `data/external/bosch/` | `Process_data.nc`, `Dictionary_process.nc`, `Si_Oxide_etch_89_points.csv`, `Lot_status.xlsx` |
| `data/external/phm_ion_mill_2018/compact/` | `equipment_sensor_data.parquet`, `fault_events.csv`, `dataset_manifest.json`, `validation_report.json`, `README.md` |

The BOSCH primary scientific reference, when available and permitted, belongs at
`data/external/research/Readme.pdf`. Its content and presence are included in freshness
checks. Full local integration tests expect the established research files and reference.
Missing datasets remain unavailable in the UI; the synthetic demonstration still works.

External data, the four local standards PDFs, generated reports and screenshots remain
Git-ignored. The repository's [license](LICENSE) does not grant rights to third-party data
or references.

## Tests and verification

Portable checks use committed synthetic data and temporary test fixtures:

```sh
.venv/bin/pytest -q -m "not integration"
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src
```

Run these checks with dashboard extras installed to include AppTest and chart tests.
Those UI tests skip in a backend-only installation. For strict typing of the complete
source tree, install the dashboard extra.

After provisioning the optional research datasets, run the complete suite:

```sh
.venv/bin/pytest -q --cov=etch_copilot --cov-report=term-missing
.venv/bin/python scripts/benchmark_dashboard.py
```

The Phase 5 baseline is **172 passing tests**, including **22 dashboard tests**, with
**94% reported statement coverage** in the provisioned environment. This is a local
verification result, not a claim of configured CI or cross-platform certification.
See the [verification record](docs/PHASE_5_VERIFICATION.md) for review findings and measurements.

For reproducible browser captures, install Chromium once, keep the dashboard running
in another terminal, and use the provisioned research datasets:

```sh
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/verify_dashboard_browser.py
```

The script blocks non-loopback HTTP, exercises the dashboard and saves genuine BOSCH/S2
captures under ignored `data/processed/dashboard/`. Screenshots are not committed or
embedded here; these instructions reproduce them locally.

## Integrity and remaining limitations

Sources are reverified before retained evidence is displayed or exported. Results are
bound to their dataset and selection with a server-local integrity seal. Fixed paths,
field allowlists, symlink rejection and bounded storage protect the presentation boundary.

Freshness is checked on actions, not continuously in an untouched browser. Already
displayed evidence, downloaded files and briefly retained media URLs cannot be revoked.
No GenAI, RAG, equipment control, recipe recommendation or root-cause confirmation is
implemented. Browser smoke tests are not a full accessibility certification.
