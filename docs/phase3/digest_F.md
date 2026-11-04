# Digest F

Plan: tasks/phase3_todo.md · boxes: F1, F2, F3, F4, F5

## F1

### plan (verbatim)

### F1 · Automated end-to-end run — S
- **Files:** `tests/test_demo_e2e.py` (new, `ue_host`)
- **Do:** drive the real page through these steps, with no other input:
  1. Pick the aircraft.
  2. Pick Desert.
  3. Press Capture.
  4. Wait for `done`.
  5. Download `dataset.zip`.

  CI runs the same test headless, up to the render step.
- **Verify:** Windows. `pytest -q -m ue_host tests/test_demo_e2e.py` passes, and the
  zip has payload boxes wherever there are payload pixels.

### files
- `tests/test_demo_e2e.py` [new]

### signatures
(no existing source files)

## F2

### plan (verbatim)

### F2 · Three-machine reproduction — XS
- **Files:** `docs/PHASE3_LOG.md`
- **Do:** run F1 from a fresh clone on all three A1 machines, recording the machine,
  preflight output, run id, verify result, wall time and the hash of
  `toolchain.json` + `requirements.lock`.
- **Verify:** three rows, all `verify PASS`, with the same hash.

### files
- `docs/PHASE3_LOG.md` [exists]

### signatures
- `docs/PHASE3_LOG.md` (6 signatures)
    1:# Phase 3 log
    15:## Letter A
    34:## Letter A, run A-2 (UE 5.7.4, decision 10)
    69:## Letter B, run B-1 (UE 5.7.4, push 3e59358d)
    92:## Letter C, run C-1 (push 845f014d)
    103:## Letter D

## F3

### plan (verbatim)

### F3 · The short guide — S
- **Files:** `docs/GUIDE.md` (new), `README.md`
- **Do:** what to open, what to choose, what to expect, and what the output contains
  (including the aircraft and payload boxes). The README's first screen links it,
  and NEXT.md is off the user path.
- **Verify:**
  - `wc -w docs/GUIDE.md` < 1000.
  - `grep -nE '\bpython\b|\.ps1|\$env:|FLIGHTSIM_|--[a-z]' docs/GUIDE.md` is empty.

### files
- `docs/GUIDE.md` [new]
- `README.md` [exists]

### signatures
- `README.md` (15 signatures)
    1:# flightsim
    93:## Quick start (any machine, ~2 minutes)
    137:## Platform support
    315:## Run the gates
    389:## Capture camera geometry (Camera Phase 1, any platform)
    434:## Lighting and camera views (web page)
    461:## Draw the flight path (web page)
    501:## Fix a refused scenario with the model (web page)
    520:## Terrain downloads start at Interpret
    531:## Test scenarios in one go
    544:## Run the tests
    557:## Layout
    577:## The architectural guards already in place
    596:## Documented deviations from the brief
    610:## Environment hazard

## F4

### plan (verbatim)

### F4 · Recorded run — XS
- **Files:** `docs/demo/README.md` (link and checksum; the video lives outside git if over 20 MB)
- **Do:** screen-record one F1 run, from the double-click to opening the dataset.
- **Verify:** duration ≤ 300 s, and the run id is in `PHASE3_LOG.md` with `verify PASS`.

### files
- `docs/demo/README.md` [missing]

### signatures
(no existing source files)

## F5

### plan (verbatim)

### F5 · Acceptance sheet — XS
- **Files:** `docs/PHASE3_REPORT.md` (new)
- **Do:** one row per acceptance criterion with its evidence (task, run id, test),
  plus what was cut and why.
- **Verify:** six rows, and no evidence cell is empty.

---

### files
- `docs/PHASE3_REPORT.md` [new]

### signatures
(no existing source files)
