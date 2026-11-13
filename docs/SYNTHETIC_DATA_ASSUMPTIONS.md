# Synthetic Data Assumptions and Scientific Limitations

## Intended use

The S1-S3 datasets support a local, read-only engineering workflow demonstration.
They are designed to exercise validation, provenance, data-quality blocking and
future evidence logic. They are not measurements, a plasma model, a process
window, a qualified baseline, or an equipment-control dataset.

All numerical values are synthetic educational examples. They must not be used
as commercial equipment setpoints, specifications, acceptance limits or recipe
recommendations.

## Shared assumptions

- Each run represents one wafer and one generic constant-recipe synthetic etch.
- Runs last 120 seconds and telemetry is sampled at a declared five-second
  interval.
- Each scenario contains 30 baseline runs and eight incident runs.
- Baseline mean site removal is generated near an illustrative 100 nm/min after
  applying the declared duration. This is not a physical-fidelity claim.
- Pre/post thickness is synthetic ex-situ metrology at five fixed sites.
- Thickness standard uncertainties of 0.5 nm and duration standard uncertainty
  of 0.1 s are assumed inputs for future method testing. They are not derived
  from a real calibration or measurement-system study.
- Random draws use NumPy's seeded `default_rng`. Generator version changes must
  be treated as new provenance even if a seed is reused.
- Noise is intentionally simple and does not reproduce chamber physics,
  autocorrelation, sensor response, wafer transport or plasma chemistry.

## Scenario assumptions

### S1 — Post-maintenance outcome shift

- Incident metrology is generated near 92 nm/min rather than 100 nm/min.
- RF reflected power is increased during the same incident runs.
- A synthetic maintenance event precedes those runs.
- Pressure, flows and temperature remain approximately stable apart from noise.

This supports a future candidate statement that RF delivery or matching merits
authorized investigation. It does not prove a matching-network or hardware
failure. Reflected-power fraction is an instrument proxy, not a measurement of
ion energy, plasma density or delivered wafer power.

### S2 — Pressure instability and variable outcomes

- Incident pressure contains a deterministic oscillatory component plus noise.
- Incident wafer outcomes have greater run-to-run variability without a fixed
  mean shift.
- One sensor value is missing to verify that missing telemetry remains visible.

This supports future investigation of pressure stability as a candidate
contributing factor. It does not establish causality or identify a physical
component.

### S3 — Metrology-quality block

- Incident values superficially resemble lower removal.
- Measurement status is invalid.
- At least one record uses an inconsistent thickness unit.
- At least one record has post thickness greater than pre thickness.
- Telemetry contains no coherent corresponding equipment anomaly.

The correct disposition is data-quality blocking and metrology verification,
not a process-fault conclusion.

## Challenge observations

- A single synthetic temperature spike is included without a corresponding
  wafer-outcome failure. It must not become a sustained-fault conclusion.
- Missing telemetry is represented as a missing value, never as zero.
- S1-S3 use isolated chamber identifiers to prevent cross-scenario baseline
  leakage.

## Measurement and SPC limitations

Phase 3 does not compute etch rate, within-wafer nonuniformity, capability,
control limits or causal status. A later phase must:

1. define the etch-rate measurand and uncertainty model, including correlation
   assumptions for pre/post thickness;
2. state the exact five-site uniformity convention and its sampling limitation;
3. choose between a conventional Individuals/moving-range method and the PRD's
   illustrative baseline mean ± 3 sample-standard-deviation method; and
4. qualify the baseline and operating characteristics before calling limits
   operational SPC limits.

Scenario truth records injected software conditions and expected test evidence.
It is never available to the normal loader, investigation interface, retrieval
system or future GenAI context.
