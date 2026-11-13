# Phase 2 deterministic analytics contract

Phase 2 exposes six read-only analytical capabilities. Every public entry point rebuilds the
trusted Phase 1.5 qualification from the supplied loaded dataset, refines the requested scope,
and refuses a `BLOCKED` decision before calculation. Callers cannot inject a readiness decision.

## Supported outputs

- BOSCH run-local elapsed-coordinate plotting data and sampling-interval summaries.
- BOSCH run/feature descriptive statistics in unverified source units.
- BOSCH side-by-side comparison of an identical source feature across at least two runs.
- BOSCH metrology coverage, relationships, missingness, and documented reconstruction flags.
- PHM source-feature, dtype, missingness, duplicate, identifier, and metadata inventory.
- PHM recorded fault-event/category inventory in the unresolved source coordinate.

Results are immutable Pydantic models with an analytics version, readiness status, exact scope,
limitations, validation rules, and SHA-256 source provenance. BOSCH outputs also identify the
verified primary scientific reference. Output ordering is deterministic and JSON-compatible.
Each entry point verifies on-disk hashes, reloads the source through the bounded loader, compares
the caller's live in-memory content with that trusted reload, and calculates only from the trusted
copy. Mutating a loaded DataFrame, array, qualification input, or content-seal field therefore
cannot change a result while retaining the original provenance.

## Numerical policy

Statistics report total observations, finite values, missing values, positive infinity, negative
infinity, and finite coverage separately. Minimum, maximum, arithmetic mean, and median use only
finite values. Variance and standard deviation are sample estimates (`ddof=1`): they are `null`
for fewer than two finite values and zero for a constant signal with at least two finite values.
No missing or infinite value is silently converted to zero.
Calculations use scaled finite values to prevent avoidable float64 aggregation overflow. If a valid
sample variance or standard deviation exceeds float64 range, that field is `null` and the result
contains an explicit calculation warning.

Elapsed coordinates remain run-local seconds. They are never interpreted as calendar timestamps
or as verified etch duration. Trend output retains every source sample; Phase 2 performs no
downsampling.

To bound local memory use, a single trend result is limited to 100,000 source samples, a metrology
coverage selection to 250,000 site records, and a fault inventory to 50,000 events. Larger scopes
fail with a structured scope error; they are never silently truncated or downsampled.

## Scientific boundaries

Sensor engineering units remain unresolved. Cross-run results are separate summaries, not pooled
production baselines, SPC evidence, or significance tests. The nominal BOSCH recipe is context,
not a measured etch interval.

For verified BOSCH source documentation, all supplied 89-site pre-etch values are identified as
reconstructed from 15 direct measurements. A post-etch value is direct only when
`postox_thickness_nan` is present; a supplied filled value where that raw field is missing is
identified as reconstructed. Without the verified reference, values remain unclassified.

PHM coordinates support inventory and raw ordering only. They have no verified duration unit,
calendar origin, or timezone. Recorded shutdown/event coordinates are not fault-onset labels, and
the fault-centered subset is not an unbiased prediction benchmark.

Phase 2 deliberately does not calculate etch rate, wafer uniformity, process capability, control
limits, baseline eligibility, temporal fault diagnosis, fault prediction, DOE, or equipment
control.

## Local artifact generation

Run `python scripts/run_deterministic_analytics.py` to write six ignored JSON artifacts under
`data/processed/analytics/`. The runner deterministically chooses the first two BOSCH runs and the
lexicographically first common feature; production code should always supply an explicit scope.

