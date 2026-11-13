# Synthetic Engineering Data Contract

## Scope

Phase 3 provides deterministic, public, synthetic inputs for future etch-rate,
uniformity, evidence, and SPC work. It does not calculate those results and does
not change any BOSCH or PHM readiness decision. The files describe an
educational experiment context, not a production tool or recipe.

- Contract version: `1.0.0`
- Generator version: `1.0.0`

## Dataset boundary

An application-visible dataset contains exactly these required files:

| File | Grain | Primary key |
| --- | --- | --- |
| `runs.csv` | One synthetic wafer run | `run_id` |
| `telemetry.csv` | One sensor sample within a run | `run_id`, `timestamp_utc` |
| `metrology.csv` | One fixed wafer site within a run | `run_id`, `site_id` |
| `maintenance.csv` | One synthetic maintenance event | `event_id` |
| `dataset_manifest.json` | Dataset identity, generator settings and source hashes | `dataset_id` |

`scenario_truth.json` is deliberately outside this boundary. It may be emitted
only to a separate test-fixture directory. The application loader rejects a
dataset containing that filename.

## Run contract

Required columns, in canonical order:

```text
scenario_id, run_id, wafer_id, chamber_id, recipe_id, start_ts_utc,
end_ts_utc, etch_duration_s, etch_duration_standard_uncertainty_s,
lot_id, phase, maintenance_event_id
```

- Scenario IDs are `S1`, `S2`, and `S3`.
- Each scenario owns a distinct chamber namespace. Cross-scenario pooling is
  prohibited even where recipe labels match.
- Timestamps use UTC ISO 8601 with a `Z` suffix.
- `etch_duration_s` is a declared synthetic exposure duration and must equal
  the difference between run start and end timestamps.
- `phase` is `baseline` or `incident`. Each scenario has at least 30 baseline
  runs in generator version 1.0.0.
- A maintenance reference must resolve to an event in the same scenario and
  chamber and must not occur after the linked run begins.

## Telemetry contract

Required columns, in canonical order:

```text
scenario_id, run_id, timestamp_utc, pressure_mTorr, rf_forward_W,
rf_reflected_W, gas1_flow_sccm, gas2_flow_sccm, chamber_temp_C, alarm_code
```

Telemetry is sampled every five seconds by default, including both run
endpoints for a 120-second run. Pressure, power and flow values cannot be
negative; RF forward power must be positive wherever a reflected-power ratio
could later be considered. Missing sensor values remain missing and are never
imputed during ingestion.

The field names carry declared units for this synthetic contract. They do not
establish that similarly named external dataset fields have the same units or
semantics.

## Metrology contract

Required columns, in canonical order:

```text
scenario_id, run_id, site_id, site_x_normalized, site_y_normalized,
pre_thickness_nm, post_thickness_nm, pre_standard_uncertainty_nm,
post_standard_uncertainty_nm, thickness_unit, measurement_method,
calibration_reference, measurement_status
```

Each run has five fixed illustrative sites:

| Site | Normalized x | Normalized y |
| --- | ---: | ---: |
| `CENTER` | 0.0 | 0.0 |
| `NORTH` | 0.0 | 0.8 |
| `EAST` | 0.8 | 0.0 |
| `SOUTH` | 0.0 | -0.8 |
| `WEST` | -0.8 | 0.0 |

Valid records use `nm`, the declared synthetic ex-situ method and non-negative
standard-uncertainty inputs. The calibration reference is a synthetic context
label, not evidence of traceability to a real standard. Phase 4 must define its
measurement model, covariance assumptions and uncertainty propagation before
producing an uncertainty-qualified result.

S3 intentionally contains incident records with invalid status, an inconsistent
unit and impossible pre/post ordering. These are scientific data-quality
findings rather than parser failures: the dataset remains inspectable, while
etch-rate and uniformity input readiness for S3 is `BLOCKED`.

## Determinism and provenance

- A fixed seed and configuration produce byte-identical canonical CSV and JSON
  files.
- Dataset identity includes a digest of the seed, versions, run counts, duration
  and telemetry interval, preventing different configurations from sharing an
  identifier.
- Column order, row order, timestamp formatting, JSON key order, newline style
  and float formatting are fixed.
- The manifest records SHA-256 for all four CSV sources. Hashes are verified
  against the exact bytes used for CSV parsing. The in-memory provenance
  snapshot retains those hashes plus the hash of the parsed manifest.
- SHA-256 supplies change detection, not publisher authentication. For the
  canonical fixture, Git history is the trust anchor; an independently modified
  data file and manifest must not be treated as an authenticated release.
- The generator refuses to overwrite a non-empty directory.
- Generator configuration is rejected before writing if aggregate run,
  telemetry, metrology or conservative source-byte budgets would exceed loader
  limits. Telemetry and metrology rows are streamed rather than accumulated in
  memory.
- The loader rejects directory and required-file symlinks, unsafe manifest
  filenames, oversized files, excessive row counts, broken relationships and
  unsupported contract versions.
- Output paths are opened component by component without following symlinks;
  files are created exclusively relative to held directory descriptors. CSV
  parsing reads at most the applicable row limit plus one before rejection.
- Qualification reloads the trusted source and compares a seal of every parsed
  frame and immutable contract, so mutation of an in-memory DataFrame cannot
  preserve readiness.

## Readiness boundary

Phase 3 can mark ingestion and valid metrology inputs as `SUPPORTED`. This is
input qualification only. SPC control limits and root-cause attribution remain
`BLOCKED` for every synthetic scenario. No synthetic decision affects external
BOSCH or PHM qualifications. Phase 3 has no synthetic capability whose evidence
supports a `LIMITED` decision: each defined input contract is either satisfied
or blocked. Existing Phase 1.5 and Phase 2 `LIMITED` semantics remain unchanged.
