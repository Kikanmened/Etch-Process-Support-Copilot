# Synthetic Candidate SPC Method Qualification

## Scope and terminology

Phase 4 qualifies a deterministic Individuals–Moving Range (I-MR) method against
the synthetic S1–S3 datasets. Every API and serialized result labels its limits
`synthetic_candidate_not_operational`. These limits are method-test artifacts:
they are not operational control limits, specifications, tolerances, process
capability evidence, metrological traceability, or permission to change a recipe.

The existing BOSCH and PHM SPC decisions remain `BLOCKED`. The existing
synthetic operational `SPC_CONTROL_LIMITS` capability also remains `BLOCKED`.
Only the separate synthetic candidate-baseline and incident-evaluation
operations can become `SUPPORTED`.

## Source basis and method selection

The primary source is the NIST/SEMATECH Engineering Statistics Handbook,
section 6.3.2.2, “Individuals Control Charts” (local 2012 PDF snapshot,
`docs/E-Handbook.pdf`, PDF pp. 1764–1766). It describes using the moving range
of two successive individual observations to estimate process variability,
identifies `d2 = 1.128` for a pair, and notes a sample-standard-deviation
alternative. The project also applies the stability, chart-selection and
baseline-governance principles mapped in `docs/ENGINEERING_STANDARDS_GUIDE.md`.

I-MR is selected because each ordered observation represents one synthetic
wafer, not a rational subgroup of multiple simultaneously comparable wafers.
The moving-range estimator is sensitive to ordering and serial dependence, so
admission requires an explicit continuity and dependence review. For comparison,
every admitted calculation also records the standard-deviation-based
Individuals limits `xbar ± 3s`. NIST notes that the standard-deviation form is
preferable at the start of Phase II; Phase 4 retains both estimates so their
difference is visible rather than silently choosing whichever gives a desired
result. I-MR remains the primary synthetic challenge method because this phase
specifically qualifies successive-observation behavior and moving-range
boundaries.

## Observation definition

For valid site `j` on wafer run `i`:

```text
site_rate[i,j] = (pre_thickness_nm - post_thickness_nm) / (duration_s / 60)
wafer_rate[i]  = arithmetic mean of the five valid site rates
```

The observation unit is `nm/min`. All five fixed sites, declared nanometre
units, valid measurement status, qualified duration, method and calibration
context must be present. This is a synthetic method observation, not an
uncertainty-qualified production measurand. Hidden scenario truth is not an
input and never appears in provenance or output.

## Baseline membership and ordering

Membership is reconstructed from a trusted reload, manifest run counts,
canonical run identifiers and UTC ordering. A CSV `phase` label is accepted only
when it agrees with that source contract. The first declared baseline count in
each canonical scenario sequence is the reference population; the remaining
runs are incidents. Baseline and incident observations cannot be exchanged by
editing labels and refreshing a file hash.

Ordering is `(start_ts_utc, run_id)`. Duplicate identifiers or timestamps,
missing/non-finite values, invalid metrology, cross-scenario records and
unexpected membership block admission.

## Project admission policy

The minimum of 25 ordered baseline observations is a project release policy,
not a universal NIST rule. It provides enough history for this synthetic method
challenge while remaining compatible with the canonical 30-run baselines.

Admission requires all of the following:

1. synthetic etch-rate input readiness is not `BLOCKED`;
2. at least 25 finite, ordered, valid wafer observations;
3. no unqualified moving-range boundary inside the baseline;
4. non-zero average moving range;
5. no unresolved Phase I Individuals- or Moving-Range-chart signal; and
6. an explicit dependence outcome of `PASS`.

Lag-1 sample autocorrelation is screened against the declared approximate
white-noise bound `±1.96/sqrt(n)`. Exceeding the bound produces
`BLOCKED_MATERIAL_AUTOCORRELATION`; fewer than 25 values or zero variance
produces `BLOCKED_INSUFFICIENT_EVIDENCE`. Passing this screen does not prove
independence or exclude higher-order dependence, drift, mixtures or seasonality.
Those limitations remain in every result.

No baseline point is automatically removed. Signals require a future governed
engineering review and a new versioned baseline; Phase 4 does not rebaseline.

## Formulas

For ordered baseline values `x[1] ... x[n]`:

```text
MR[i]       = abs(x[i] - x[i-1]), i = 2 ... n
xbar        = sum(x) / n
MRbar       = sum(MR) / (n - 1)
sigma_MR    = MRbar / d2, where d2 = 1.128
I_LCL/UCL   = xbar ± 3 * sigma_MR
MR_LCL      = D3 * MRbar, where D3 = 0
MR_UCL      = D4 * MRbar, where D4 = 3.267
comparison  = xbar ± 3 * s, with sample s using n - 1 degrees of freedom
```

Statistical lower limits are not silently clamped to a physical boundary.
Phase 4 implements only single-point limit exceedances. Additional run rules
are deferred because they change false-alarm behavior and multiplicity.

## Moving-range boundaries

A moving range is evaluated only when continuity is verified. The versioned
synthetic generator contract defines the expected run interval as 900 seconds;
the cadence is not estimated from observations undergoing qualification. Maintenance,
recipe or chamber changes, equipment-state alarms and departures from the
qualified sampling interval create a reported boundary. A boundary retains both
run IDs and reasons but has no moving-range value or signal. Missing observations
would likewise break adjacency; the implementation never bridges across a gap.

The first incident may be compared with the final baseline observation only
when continuity is verified. Thus S1's maintenance transition is reported
separately, while an otherwise continuous S2 transition may be evaluated.

## Frozen baseline and interpretation

An admitted baseline is immutable and content-addressed. Its SHA-256 identifier
binds the dataset, scenario, ordered observations, formulas, constants,
dependence diagnostic, source hashes and nominal interval. Incident evaluation
reloads trusted sources, rebuilds qualification and verifies that identifier
before using the frozen parameters. Limits are never recalculated from incident
data.

Individuals signals are evidence of a synthetic location departure; MR signals
are evidence of unusually large successive variation. They do not establish a
physical component, causal mechanism or corrective action. Incident mean
differences are descriptive and are reported separately from MR signals.

## Canonical Phase 4 outcomes

- **S1:** `BLOCKED`. The baseline has material positive lag-1 dependence under
  the declared screen and an unresolved Phase I Individuals signal. The known
  injected shift is therefore not evaluated against candidate limits.
- **S2:** `SUPPORTED` for synthetic candidate method evaluation. Its baseline
  passes the declared admission rules; incident I and MR signals are reported
  without a root-cause claim.
- **S3:** `BLOCKED`. Invalid incident metrology prevents scenario-level SPC
  qualification even though some baseline records are superficially usable.

These outcomes are properties of the chosen versioned admission policy and the
canonical fixture. They are not statements about industrial etch stability.
