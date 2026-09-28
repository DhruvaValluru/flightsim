# The advancement additions: contracts

Written 2026-09-28 on `claude/relaxed-cori-gccjvx` (= `phase2`) after
`docs/PHASE3_GAP_ANALYSIS.md`. These are additions to the branch, not a phase.
Each section is a contract an item is built against; the demonstration of each
item is in `docs/ADVANCEMENTS_REPORT.md`. Shared rules first.

## 0. Rules every item obeys

* **The record.** Every variable an item introduces returns the record in
  `core/records.py` (`AppliedVariable`: value, unit, provenance source, model,
  parameters, references, properties written, telemetry columns, frame keys, a
  measured null test, what is not claimed), serialised under
  `applied_variables` in the run manifest (`RunResult.manifest`) and the
  capture manifest. `record_version` 1.
* **Versions bump once.** No item bumps `SPEC_VERSION`, `MANIFEST_VERSION` or
  the bundle version on its own. New keys are optional and absent-canonical;
  the integrator bumps each version once when the addition closes, with the
  list of new keys in this file.
* **Refusals by name**, entries in `core/messages/catalog.yaml` with the
  two-way test; **verifier independence** (`core/capture/verify.py` never
  imports a producer); **a test that fails without each safeguard and a
  mutation guard** in `scripts/mutation_check.sh`; **measured, not asserted**
  (a null test here, a Gate 6 clause with a control render on Windows).
* **Shared files** (`core/messages/catalog.yaml`, `scripts/mutation_check.sh`,
  this file, the report, `NEXT.md`, `flightsim/capture.py` argument wiring)
  are integrated by one integrator in one commit per batch, from text the
  item returns; items never edit them concurrently.

## Batch 1 (no spec change): the items whose design the probes settled

Sections are appended by the integrator as each item lands.
