# Engineering Standards Guide

## Purpose and decision boundary

This guide maps four reference works to the Etch Process Support Copilot's
deterministic analytics, metrology interpretation, readiness gates, proposed
statistical process control (SPC), and future generative-AI (GenAI) features.
It is an engineering interpretation, not a replacement for the source
standards, a calibration procedure, or a grant of permission to perform a
currently blocked calculation.

The following rule is controlling:

> A reference can explain what evidence a calculation needs; it cannot supply
> evidence that is absent from the dataset.

All existing `BLOCKED`, `LIMITED`, and `SUPPORTED` decisions therefore remain
unchanged. In particular, this review does **not** authorize BOSCH uniformity,
etch-rate, baseline/SPC-limit, or calendar-time calculations, nor PHM
event-centred, temporal-detection, preceding-signal, or false-alarm-rate
calculations.

Review date: 2026-11-13.

## Sources, authority, and permitted use

| Source | Role in this guide | Version and verified locator | Use and redistribution decision |
| --- | --- | --- | --- |
| NIST/SEMATECH Engineering Statistics Handbook | Statistical assumptions, exploratory analysis, measurement-process characterization, and SPC foundations | Local `docs/E-Handbook.pdf`, a 2012 PDF snapshot; current [NIST project page](https://www.nist.gov/programs-projects/nistsematech-engineering-statistics-handbook) and [Handbook 151 record](https://www.nist.gov/publications/handbook-151-nistsematech-e-handbook-statistical-methods) | NIST states that its technical-series works are generally reusable with acknowledgement, subject to third-party rights. NIST notes that the downloadable PDF chapters are somewhat out of date, so use the current official web edition when checking present guidance. See [NIST technical-publication licensing](https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications) and [handbook distribution notes](https://itl.nist.gov/div898/handbook/cd.htm). |
| JCGM 100:2008, *Evaluation of measurement data—Guide to the expression of uncertainty in measurement* (GUM) | Measurement models, Type A/Type B uncertainty evaluation, covariance, combined and expanded uncertainty, and reporting | Local `docs/JCGM_100_2008_E.pdf`; [official DOI record](https://doi.org/10.59161/JCGM100-2008E) | The local document contains a specific copyright notice restricting several forms of reproduction and online use without written authorization. The current BIPM website generally applies CC BY 4.0 unless otherwise stated and warns that additional restrictions may apply. Because the interaction between those terms and AI training/external upload is not explicit, this project will not commit or redistribute the PDF and requires a rights review before external upload, training, fine-tuning, or substantial reproduction. Concise original paraphrase and clause citation are used here. |
| JCGM 200:2012, *International vocabulary of metrology—Basic and general concepts and associated terms* (VIM), 3rd edition | Controlled metrology vocabulary: measurand, result, uncertainty, calibration, traceability, comparability, and measurement model | Local `docs/JCGM_200_2012.pdf`; [official DOI record](https://doi.org/10.59161/JCGM200-2012) | The same project policy applies because the local document carries a specific notice while the [current BIPM website terms](https://www.bipm.org/en/copyright) provide a general CC BY 4.0 grant subject to additional restrictions. No conclusion about AI-training rights is inferred from silence. |
| NIST AI 600-1, *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile* | GenAI governance, provenance, pre-deployment testing, incident disclosure, and bounded claims | Local `docs/NIST.AI.600-1.pdf`; [official publication and DOI record](https://doi.org/10.6028/NIST.AI.600-1) | NIST technical-publication terms permit attributed reuse, subject to third-party exceptions. This guide paraphrases the profile and does not reproduce embedded third-party material. |

The local review was read-only and offline. The PDFs were treated as untrusted
inputs: no embedded links, scripts, attachments, or document instructions were
executed. Text was extracted locally for review and was not retained as a
corpus. The following SHA-256 digests identify the exact reviewed files:

| File | SHA-256 |
| --- | --- |
| `E-Handbook.pdf` | `c0d71c6fc65eb0a44bbb11107799cd36ceae1c4d81f0d143c439c3d1849eadda` |
| `JCGM_100_2008_E.pdf` | `41bbf068fbc0d7986c98691b2d1af6680cb3044f6a1a89b3560933ed9ef9626c` |
| `JCGM_200_2012.pdf` | `8a603e99d236a65d771f38b6dcf627953146fe023a5266b3307681ada30f4fe7` |
| `NIST.AI.600-1.pdf` | `6e73620ab6b64e90ef2c04bf0e0d6246185a2f4b1b13cab0df494496cff89b6a` |

The [current JCGM publication index](https://www.bipm.org/en/committees/jc/jcgm/publications/)
also lists a 2026 GUM suite and a 2026 amendment on nonlinearity. They were not
among the four requested references and were not reviewed here. Before
implementing a new uncertainty engine, review the then-current JCGM suite and
record whether it changes this 2008-based guidance.

## Normative vocabulary for this project

Use these distinctions in code, reports, interfaces, and future requirements:

- A **measurand** is the quantity intended to be measured. A column name is not
  by itself a complete measurand specification; the quantity, conditions,
  method, and relevant state must be stated (VIM 2.3; GUM 3.1.1).
- A **measurement result** contains quantity value information and the relevant
  information needed to interpret it; it is generally expressed with a
  measurement uncertainty (VIM 2.9).
- **Measurement uncertainty** is a non-negative parameter characterizing the
  dispersion of quantity values attributed to a measurand from the information
  used. A statistical standard deviation can contribute to a Type A evaluation,
  but a sample standard deviation is not automatically the uncertainty of a
  measurement result. Measurement uncertainty is also not interchangeable with
  model confidence, tolerance, error, data quality, or GenAI confidence
  (VIM 2.26; GUM 3.3.1 and 4.2).
- **Calibration** establishes and then uses a relationship between standards'
  values and indications, with associated uncertainties. Calibration is not
  adjustment and is not merely verification (VIM 2.39).
- **Metrological traceability** relates a result to a reference through a
  documented, unbroken calibration chain, with each calibration contributing
  to uncertainty (VIM 2.41).
- **Metrological comparability** applies to measurement results for quantities
  of the same kind and requires traceability to the same reference; it does not
  mean two values or uncertainties are equal (VIM 2.46).
- A **measurement model** states the relationship among the output measurand
  and all input quantities known to matter (VIM 2.48; GUM 4.1.1).
- **Repeatability**, **reproducibility**, **stability**, and **bias** are
  different properties. They must not be collapsed into a single data-quality
  label (NIST/SEMATECH 2.4 and 2.4.1).

## Principle-to-implementation map

| Verified principle | Current implementation | Readiness consequence | Gap or justified improvement |
| --- | --- | --- | --- |
| A statistical model must state and check assumptions such as randomness, stable location, stable variation, and an appropriate distribution (NIST/SEMATECH 1.2.1, PDF pp. 31–32). | Deterministic summaries count finite, missing, invalid, `NaN`, and infinite values; warnings expose numerical and data-quality limitations. | Descriptive summaries may remain `LIMITED`; their existence is not evidence of process stability or independence. | Add explicit sampling-order, independence/autocorrelation, stationarity, and distribution diagnostics before inferential or SPC work. |
| If location is not stable, a mean can be misleading and its usual uncertainty estimate can be too small (NIST/SEMATECH, PDF p. 41). | Run-local summaries avoid claiming a qualified baseline. | Preserve the block on baseline eligibility and SPC limits. | Future reports should label means as descriptive when stability has not been established. |
| Exploratory analysis should expose structure, uncertainty, effects, and time-dependent signal/noise; confirmatory methods must follow stated assumptions (NIST/SEMATECH 1.1.7 and related EDA guidance, PDF pp. 26, 47, 214–216). | BOSCH elapsed trends and sensor statistics, and PHM feature/fault inventories, are bounded deterministic outputs with provenance. | Do not convert an exploratory pattern into a causal, predictive, or control claim. | Add a claim taxonomy to future reports: observed, descriptive, inferential, predictive, causal, and control. |
| A measurement begins with the measurand and a model relating it to input quantities (GUM 3.1.1 and 4.1.1; VIM 2.3 and 2.48). | Metrology coverage distinguishes direct and reconstructed values and preserves method/provenance qualifiers. | Missing units, methods, conditions, or model inputs must prevent etch-rate and uniformity calculations. | Define versioned measurand and measurement-model records before implementing derived metrology. |
| Uncertainty remains after correction; Type A and Type B information, sensitivity, and correlation can all matter (GUM 3.3.1, 4.2, 4.3, 5.1, and 5.2). | Sample variability is reported, but is not represented as measurement uncertainty. | Never relabel `std` or a confidence interval as a GUM uncertainty budget. | Add an uncertainty-budget schema and covariance-aware propagation only after source uncertainty and calibration evidence exist. |
| Expanded uncertainty is derived from combined standard uncertainty and a stated coverage factor; coverage claims require care (GUM 6.2.1). | No expanded-uncertainty claim is currently made. | Keep such claims blocked. | Future output must report the estimate, standard/expanded uncertainty, coverage factor, basis for the factor, units, model version, and limitations. |
| Results must retain enough information to be re-evaluated (GUM 7.1.1). | Dataset fingerprints, content hashes, readiness decisions, scope validation, and deterministic serialization support re-evaluation. | Provenance mismatch or scope mismatch must fail closed. | Add calibration-record IDs, model version, unit registry version, transformations, and uncertainty-component lineage. |
| Gauge studies separate repeatability, reproducibility, stability, and bias (NIST/SEMATECH 2.4–2.4.1, PDF pp. 879–880). | The qualification layer does not claim that present metrology is measurement-system capable. | Cross-run differences must not be attributed to process changes without measurement-system evidence. | Plan a measurement-system analysis that accounts for instrument, operator/setup, wafer/site, time, and reference effects where the experimental design supports them. |
| Control charts help assess and monitor stability; qualified operational limits depend on a defensible in-control reference, chart choice, estimation method, and assumptions. Stability is also a prerequisite for interpreting capability or attempting process centring/variation reduction (NIST/SEMATECH 6.3.1–6.3.3, PDF pp. 1752–1755 and 1779; stability guidance, p. 1718). | SPC control-limit and baseline calculations are `BLOCKED`. | Preserve the project-specific block until the SPC admission checklist below passes. This does not imply that control charts are scientifically useful only after stability is already known. | Distinguish exploratory/Phase I investigation from approved Phase II monitoring; implement chart selection, subgroup design, baseline freeze/versioning, assumption checks, and a response plan together. |
| GenAI governance should address provenance, pre-deployment testing, incident disclosure, and periodic review (NIST AI 600-1, pp. 6, 20, 51–57). | Deterministic analytics and readiness decisions are the authoritative calculation layer; no GenAI result can currently alter them. | GenAI must not bypass readiness or create missing scientific evidence. | Keep GenAI advisory and retrieval-grounded; add evaluation, citation, incident, and human-approval controls before release. |
| Validity evidence must match the deployment context; narrow tests must not be extrapolated beyond their domain (NIST AI 600-1, MEASURE 2.5, pp. 34–35, and pre-deployment discussion, pp. 53–54). | Dataset-specific dispatch and scope validation limit cross-dataset execution. | A GenAI evaluation on one dataset, tool, recipe family, or failure mode cannot qualify another. | Define a coverage matrix across datasets, tasks, users, adversarial inputs, and failure severities, with explicit unsupported regions. |

## Existing deterministic analytics

The six public calculations described by the deterministic analytics contract
remain the implementation boundary:

| Calculation | Standards interpretation | Required guardrail |
| --- | --- | --- |
| `bosch_elapsed_trend` | A run-local time-coordinate description, not calendar time, etch duration, or a kinetic model. | Require verified run-local time semantics; retain finite-value handling and source provenance. |
| `bosch_sensor_statistics` | Exploratory descriptive statistics, not measurement uncertainty, capability, or a stable baseline. | Report validity counts and warnings; prevent inferences that require independence or stability. |
| `bosch_compare_runs` | A descriptive comparison of the identical source feature, not metrological comparability or evidence of causality. Source engineering units remain unresolved. | Enforce current dataset identity and scope compatibility, keep run summaries separate, and label unresolved units/semantics. Unit and method compatibility are future prerequisites for stronger engineering claims. |
| `bosch_metrology_coverage` | Coverage and method inventory, not etch rate, uniformity, calibration, or traceability. | Preserve direct-versus-reconstructed distinctions and block unsupported derived calculations. |
| `phm_feature_inventory` | A schema/availability statement, not proof that a feature is scientifically comparable or prediction-ready. | Retain exact scope, source identity, and missing/invalid-value reporting. |
| `phm_fault_inventory` | A deterministic label inventory, not event timing, detection performance, diagnosis, or false-alarm analysis. | Do not infer temporal semantics or ground truth that the dataset does not provide. |

### Statistical interpretation rules

1. Report the population represented by each count and denominator.
2. Keep missing, non-numeric, `NaN`, positive infinity, and negative infinity
   distinguishable even when a finite-only statistic excludes all of them.
3. State the degrees-of-freedom convention for variance and standard deviation.
4. Treat duplicates according to the declared observation unit. A repeated row may
   be a valid repeated observation, an acquisition artifact, or a duplicate; the
   software must not guess.
5. Preserve original order for time-dependent summaries. Sorting, interpolation,
   smoothing, or resampling is a model operation and needs provenance.
6. Never imply practical significance from statistical significance, or process
   stability from an ordinary sample summary.
7. A confidence interval for a statistical parameter is not automatically a GUM
   measurement uncertainty. Statistical information may contribute to an
   uncertainty evaluation only through a justified measurement model.

### Exploratory versus uncertainty-qualified results

Readiness and scientific claim strength are related but different dimensions.
The following distinction clarifies interpretation without changing any current
readiness status:

| Result class | Permitted interpretation | Evidence not established by the result |
| --- | --- | --- |
| Exploratory/descriptive | Reproducible finite-value summaries, inventories, coverage descriptions, run-local plots, and separate run comparisons within their approved scope | Measurement uncertainty, metrological comparability, process stability, capability, causality, prediction performance, or control authority |
| Inferential engineering result | A population or model claim with a defined estimand, sampling basis, checked assumptions, and appropriate inferential method | Metrological traceability or measurement uncertainty unless those are separately established |
| Uncertainty-qualified measurement result | A defined measurand and measurement model with units, input information, applicable correlation, and a documented uncertainty evaluation | Process capability, causal effect, or control suitability unless separately established |
| Operational SPC result | Monitoring against an approved, versioned baseline with a suitable chart, known operating characteristics, and response plan | Product conformance; control limits are not specification limits |

Phase 2 outputs occupy the first row only. A `LIMITED` exploratory calculation
can still be useful when its limitations are explicit; conversely, numerical
precision does not elevate it into an uncertainty-qualified engineering result.

## Metrology and uncertainty admission gate

A new derived measurement calculation may move from `BLOCKED` only when all
applicable evidence is present, validated, versioned, and included in
provenance:

- the measurand, quantity kind, unit, measurement conditions, object, spatial
  location, and time/state are unambiguous;
- the measurement procedure and measurement model are documented;
- each input quantity has a value, unit, source, and uncertainty evaluation;
- Type A and Type B components are identified without treating the categories
  as synonyms for random and systematic effects;
- sensitivity coefficients and transformations are defined;
- correlations or covariances between inputs are justified and represented;
- calibration status, reference, traceability chain, and validity interval are
  available where required;
- reconstructed or interpolated values are clearly marked, and model/form
  uncertainty is represented;
- unit conversions are dimensional, explicit, and tested;
- combined standard uncertainty is reproducible from the recorded budget;
- any expanded uncertainty states the coverage factor and its basis; and
- the final report contains enough information to reproduce and re-evaluate the
  result.

For BOSCH data, a pre/post thickness pair alone does not establish these
conditions. In particular, etch rate additionally requires a scientifically
valid duration for the relevant etch exposure, compatible thickness
measurands, units, pairing, and uncertainty propagation. Uniformity additionally
requires a defined spatial measurand, sampling pattern, valid site mapping,
aggregation rule, and measurement-system evidence.

## Future SPC admission gate

For this project, calculation of candidate or operational control limits remains
`BLOCKED` under the existing readiness decision. The checklist below is the
project's release gate for future operational SPC; it is not a claim that every
item is a universal prerequisite for merely drawing an exploratory time plot or
using a control chart during a properly governed Phase I investigation.

Operational SPC must remain `BLOCKED` until all applicable items are satisfied:

1. **Process and characteristic definition:** a controlled process scope,
   response/measurand, units, sampling frame, and operational purpose are fixed.
2. **Measurement-system adequacy:** repeatability, reproducibility, stability,
   resolution, bias, and calibration evidence are evaluated to the extent
   relevant to the intended decision; traceability is established where the
   required comparability or use demands it.
3. **Observation semantics:** the observation unit, ordering, duplicate policy,
   missingness treatment, and censoring/saturation behavior are documented.
4. **Rational subgrouping:** within- and between-subgroup sources of variation
   match the engineering question; subgroup size and frequency are justified.
5. **Baseline eligibility:** sufficient representative history exists, special
   causes have been investigated, and stability evidence is recorded without
   silently deleting inconvenient points.
6. **Dependence and distribution:** autocorrelation, drift, seasonality, mixtures,
   discreteness, and non-normality are evaluated for the proposed chart.
7. **Chart selection:** variables, attributes, multivariate, rare-event, or
   time-weighted methods are selected from the data-generating process—not by a
   universal three-sigma default.
8. **Limit estimation:** estimation data, formulas, constants, uncertainty, and
   any Phase I exclusions are versioned; limits are not specification limits.
9. **Operating characteristics:** expected false-alarm behavior, detection
   sensitivity, multiplicity, run rules, and missing-data behavior are tested.
10. **Response plan:** signals lead to a documented human investigation and
    disposition; they do not directly change a process recipe.
11. **Lifecycle control:** frozen baselines, approved re-baselining, drift review,
    audit history, and rollback are implemented.

Until then, existing approved plots may be labelled exploratory; they must not
present reference lines as qualified control limits or declare a process in/out
of control. This wording does not authorize a new Phase 2 control-limit
calculation.

## Future GenAI implementation boundary

NIST AI 600-1 is a voluntary, cross-sector risk-management profile. Its
governance, provenance, testing, and human-oversight guidance motivates the
following project-specific layered design; the diagram is this project's
implementation recommendation, not a prescribed NIST architecture:

```text
untrusted question and documents
        ↓ validate, isolate, and retrieve from an allowlist
source-cited context + immutable readiness decision
        ↓
GenAI explanation or workflow suggestion
        ↓ schema validation and deterministic cross-checks
human engineering review
        ↓
advisory output only; no autonomous recipe or equipment action
```

Proposed project controls for any future GenAI implementation are:

- **Authority separation:** numerical results and readiness decisions come only
  from approved deterministic functions. The model cannot synthesize a
  replacement result or downgrade `BLOCKED` to `LIMITED`/`SUPPORTED`.
- **Retrieval provenance:** material source-dependent claims identify the
  source, version, page/clause or data artifact, and applicable scope. Record
  content hashes and retrieval times where needed for reproducibility and
  change control. Retrieved text remains data, never instructions.
- **Dataset isolation:** prompts, caches, embeddings, tool calls, and reports are
  partitioned by authorized dataset/project scope. Cross-run comparison still
  uses the deterministic compatibility gate.
- **Bounded language:** uncertainty, confidence, causality, fault, anomaly,
  recommendation, and control-state terms follow the definitions and evidence
  level in this guide.
- **Human authority:** an identified engineer reviews material conclusions and
  any proposed investigation. GenAI cannot actuate equipment, alter recipes,
  approve a baseline, or release an SPC model.
- **Testing before use:** evaluate confabulation, unsupported numbers, citation
  correctness, prompt injection, document poisoning, conflicting sources,
  stale sources, omitted limitations, data leakage, and refusal at readiness
  boundaries.
- **Monitoring and incidents:** retain model/system versions, prompts and tool
  provenance subject to data policy; define incident reporting, escalation,
  decommissioning, and re-evaluation triggers.
- **Rights management:** record source ownership, permitted uses, retention, and
  redistribution limits. Require a rights review before external upload,
  training, fine-tuning, or substantial reproduction of the JCGM PDFs; their
  applicability to those uses is not resolved by this scientific review.

Model confidence scores must never be presented as metrological uncertainty or
as evidence that a calculation is ready.

## Scientific gaps and required evidence

| Gap | Scientific risk | Current disposition | Evidence needed before improvement |
| --- | --- | --- | --- |
| Incomplete sensor and metrology units/quantity kinds | Invalid comparisons and dimensionally wrong derived values | Keep affected comparisons or derivations limited/blocked | Authoritative data dictionary, dimensional validation, conversion policy |
| Incomplete measurand and measurement-condition definitions | Values that look alike may represent different quantities or states | Preserve etch-rate and uniformity blocks | Versioned measurand specifications and procedures |
| Missing calibration, traceability, and uncertainty budgets | Apparent process differences may be measurement-system effects | Do not claim metrological comparability or measurement uncertainty | Calibration records, common references, component uncertainties and covariance |
| Reconstructed/interpolated metrology lacks quantified model uncertainty | False precision and biased spatial conclusions | Preserve method labels and derived-calculation blocks | Reconstruction model, validation design, residual/model uncertainty, domain limits |
| No qualified stable baseline or rational subgroup design | Invalid limits, inflated false alarms, or hidden changes | SPC remains blocked | Representative ordered history, subgroup rationale, MSA, stability and dependence evidence |
| Run-local time lacks calendar/exposure semantics | Invalid duration, event alignment, rate, and lag conclusions | Preserve calendar, etch-duration, and PHM temporal blocks | Clock definition, synchronization, event markers, reset/wrap behavior, latency bounds |
| PHM fault labels do not establish event truth or detection opportunities | Misleading detection/false-alarm claims | Preserve event/detection/false-alarm blocks | Label ontology, event intervals, opportunity denominator, ground-truth process and timing |
| Duplicate and missingness mechanisms are not scientifically classified | Biased summaries or unjustified deletion/imputation | Continue transparent counts; do not infer mechanism | Acquisition semantics, duplicate keys, missingness/censoring model, approved handling |
| GenAI deployment context and evaluation set are undefined | Confabulation, leakage, readiness bypass, and overgeneralization | No authoritative GenAI analysis | Intended-use statement, threat model, rights register, scoped evaluation corpus, acceptance thresholds, incident plan |

## Required future tests

These are requirements for later implementation work, not tests added by this
documentation review.

### Analytics and readiness

- Prove every public calculation re-evaluates readiness and provenance and fails
  closed on `BLOCKED`, unknown operations, scope mismatch, content-hash mismatch,
  and dataset-type mismatch.
- Verify deterministic ordering and byte-stable serialization across repeated
  runs and supported Python environments.
- Cover empty, singleton, all-missing, mixed invalid, duplicate, constant,
  extreme-magnitude, overflow-prone, `NaN`, and positive/negative-infinity cases.
- Test cross-run feature compatibility for unit, quantity kind, method, time
  semantics, and reconstruction-status mismatches—not name equality alone.
- Demonstrate that each existing `BLOCKED` operation remains unexecutable through
  all public interfaces and direct dispatcher inputs.

### Metrology and uncertainty

- Validate measurand completeness and reject missing/ambiguous units,
  conditions, methods, pairing, and traceability.
- Compare uncorrelated and correlated uncertainty propagation against
  hand-calculated reference cases, including zero, negative, and near-singular
  covariance cases.
- Test Type A/Type B component ingestion without assuming independence based on
  category.
- Validate dimensional conversions and reject offset/nonlinear conversions that
  are treated as simple scale factors.
- Test coverage-factor reporting, significant-digit/rounding policy, and complete
  uncertainty-budget provenance.
- Ensure reconstructed values retain flags and include validated model
  uncertainty; reject extrapolation outside the qualified domain.

### SPC

- Reject baseline creation without appropriate measurement-system evidence,
  sufficient ordered history, rational subgroup definition, and a documented,
  approved stability review.
- Use simulated and fixed reference datasets to test chart formulas, constants,
  false-alarm behavior, autocorrelation sensitivity, non-normality, missing
  subgroups, ties, and zero variance.
- Verify that control limits are never labelled specification/tolerance limits
  and that exploratory limits cannot be promoted to operational limits.
- Test frozen-baseline versioning, approved re-baselining, audit history, and
  deterministic replay.

### GenAI

- Inject instructions in retrieved PDFs, metadata, filenames, and dataset fields;
  verify they are quoted/treated as data and cannot call tools or change gates.
- Ask for every blocked calculation using indirect phrasing, urgency, role claims,
  encoded text, and multi-turn pressure; require consistent refusal plus the
  missing-evidence explanation.
- Test unsupported numeric claims, fabricated citations, citation-to-claim
  mismatch, conflicting references, stale versions, and absent evidence.
- Verify project/dataset isolation across retrieval, caches, embeddings, tool
  results, logs, and generated reports.
- Evaluate domain coverage and failure severity separately; do not average away
  high-consequence failures.
- Exercise human escalation, incident capture, rollback/decommissioning, and
  reproducible replay of model/tool/source versions.

## Prioritized, justified improvements

1. **Metadata before formulas:** define units, quantity kinds, measurands,
   measurement conditions, method, reconstruction status, and time semantics in
   a versioned schema. This unlocks reliable validation without changing any
   present readiness decision.
2. **Measurement model and uncertainty budget:** introduce a reviewed schema for
   input quantities, Type A/Type B evaluations, distributions, degrees of
   freedom, sensitivity coefficients, covariance, calibration references, and
   output reporting. Implement only after representative evidence exists.
3. **Measurement-system study:** design repeatability/reproducibility/stability/
   bias work around the actual wafer, site, instrument, setup/operator, and time
   structure. Do not infer these components from an observational dataset that
   lacks the design.
4. **SPC qualification package:** make the admission checklist, chart rationale,
   baseline approval, test evidence, response plan, and lifecycle record a single
   reviewable artifact.
5. **GenAI safety case:** establish intended use, prohibited actions, retrieval
   rights, threat model, evaluation matrix, acceptance thresholds, human review,
   and incident process before integrating a model.

The order matters: richer statistical or AI functionality cannot compensate for
missing metrological meaning.

## Source traceability

- NIST/SEMATECH Engineering Statistics Handbook: sections 1.1.7, 1.2.1, 2.4,
  2.4.1, 6.3.1, 6.3.2, and 6.3.3; local PDF pp. 26, 31–32, 41, 47, 214–216,
  879–880, 1718, 1752–1755, and 1779. Use the current [official handbook](https://www.itl.nist.gov/div898/handbook/) when its content differs from the 2012 snapshot.
- JCGM 100:2008 (GUM): clauses 3.1.1, 3.3.1, 4.1.1, 4.2, 4.3, 5.1, 5.2,
  6.2.1, 7.1.1, and 7.2; [official DOI record](https://doi.org/10.59161/JCGM100-2008E).
- JCGM 200:2012 (VIM): entries 2.3, 2.9, 2.26, 2.39, 2.41, 2.46, and 2.48;
  [official DOI record](https://doi.org/10.59161/JCGM200-2012).
- NIST AI 600-1: governance, content provenance, pre-deployment testing, and
  incident disclosure overview (p. 6); GOVERN 1.5 (p. 20); MEASURE 2.3 and 2.5
  (pp. 34–35, including MS-2.5-003 and MS-2.5-005); MANAGE guidance
  (pp. 43–49); and appendices on governance, testing, provenance, and disclosure
  (pp. 51–57); [official DOI record](https://doi.org/10.6028/NIST.AI.600-1).
