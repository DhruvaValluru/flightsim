# Phase 3 checklist — the guideline sheet

The plain-words version of `tasks/phase3_todo.md` (revision 2, 2026-10-27). The
letters match the plan: **A**1 here is A1 there.

**How to use this sheet**

- Do the letters in order: A → B → C → D → E → F.
- Do not start a letter until the gate before it is ticked.
  - **One exception:** the Python-only boxes in C (marked 🐍) may be done while A is
    still open.
- Tick a box only when its **check** passes. Change `[ ]` to `[x]` and commit.
- 🪟 means the check needs a Windows machine with the engine installed.
- If a check fails, write what you saw in `docs/PHASE3_LOG.md` before fixing it.
- The rule for the whole phase: **do less, and make what remains work for someone
  who is not us.** If a box turns out expensive, say so; it may be cut.

---

## Why the order changed (the weekend Windows review)

**What works:** everything in Python. Plan in plain English, reproducible
campaigns, the verifier, the exporter refusing bad data, and the aircraft
sitting 0.4 m from its label (it was ~25 m).

**What doesn't:** the Unreal half. Each problem below has its own box in A.

| What happened on Windows | Box that fixes it |
|---|---|
| Build failed without 5.7 (the code names a 5.7-only setting); fixed by installing 5.7 | A1, A2, A3 |
| Had to import the aircraft by hand | A7 |
| Had to skip host flight with `--no-host-flight` | A8 |
| An old September program drew the pictures | A4 |
| Only one of two cameras gave pictures | A9 |
| Generate in the web app always refused | A10 |
| Tight box empty, "alone" pictures missing (3 of 7 label checks fail) | A11, A12 |
| The whole aircraft is one colour in the mask (no gear or parts) | C (payload and gear); control surfaces are not this phase |

---

## A · Make the Unreal half work, with no workarounds

- [ ] **A1 · Install UE 5.7 (5.7.4) on all three computers** — *decided
  2026-10-27: 5.7*
  - The engine is **5.7**, patch **5.7.4**, on every computer. No going back to an older engine.
  - The review computers install 5.7.4 before any other A box.
  - Check: `docs/TOOLCHAIN.md` has three rows that all say 5.7.4 (the dated
    decision line is already there).
- [ ] **A2 · That version written in every place the project names it**
  - Check: `pytest -q tests/test_platform.py` passes.
  - Check: changing the version in one file by hand makes that test fail.
- [ ] **A3 · The build refuses the wrong engine** 🪟
  - Check: pointing it at another version stops with `engine.version_mismatch`.
  - Check: the right version builds with zero errors.
- [ ] **A4 · An old engine program can't draw the pictures**
  - Check: after changing one `.cpp` without rebuilding, a render stops with
    `engine.binary_stale`.
- [ ] **A5 · JSBSim plugin set up again on this version** 🪟
  - Check: `scripts/check_bridge_api.sh` passes and the build passes.
  - Check: each of its six patches is marked needed or not needed.
  - Check: the plane flies the same in the engine as in Python (`gate5_ue_parity.py`).
- [ ] **A6 · Materials build by themselves** 🪟
  - Check: the first run prints `MATERIAL-CREATED` for the five rebuilt ones, and
    the second run prints `MATERIAL-EXISTS`.
- [ ] **A7 · The aircraft is imported automatically** 🪟
  - Check: delete the imported A-4, press Generate, and it imports and renders by itself.
- [ ] **A8 · Host flight works; nobody needs `--no-host-flight`** 🪟
  - Check: a web-app run with host flight completes, and no message tells the user
    to add the flag.
- [ ] **A9 · Every camera gives pictures, or the run says which one didn't** 🪟
  - Check: the default run has the same number of frames for both cameras.
  - Check: an empty camera stops with `render.camera_empty`.
- [ ] **A10 · Generate works in the web app** 🪟
  - Check: a one-line prompt on `/generate.html` finishes a campaign.
- [ ] **A11 · The engine writes the label pictures; missing ones fail loudly** 🪟
  - Check: every `render.json` has the mask, depth and an "alone" picture per aircraft.
  - Check: a run with missing label pictures stops with `labels.no_bundle`.
- [ ] **A12 · All seven label checks pass; one real frame saved as a test** 🪟
  - Check: `python -m flightsim.verify runs/<id>` shows 7 of 7 PASS.
  - Check: `label_diagnose.py` shows `tight null: 0`.
  - Check: `pytest -q tests/test_engine_bundle_golden.py` passes.
- [ ] **A13 · NEXT.md says only what was measured**

### GATE A
- [ ] Tests pass on all three operating systems.
- [ ] **On the reviewer's computer, from a fresh download:** Generate gives
  pictures from both cameras and 7 of 7 label checks pass, with no hand import, no
  flag and no old program.
- [ ] The same on the other two computers.

---

## B · Lock the tools

- [ ] **B1 · Exact Python package versions saved with hashes** (`requirements.lock`)
  - Check: a fresh install from it, then `pytest -q`, passes.
- [ ] **B2 · One file lists every other tool's version** (`toolchain.json`)
  - Check: preflight prints `OK` per tool, and a wrong version stops it.
- [ ] **B3 · A test catches any version drifting**
  - Check: `pytest -q tests/test_toolchain_pins.py` passes.
- [ ] **B4 · Picture quality checked on this engine** 🪟
  - Re-tune the colours and exposure on 5.7.4.
  - Check: `gate6_visual.py` passes, and the A12 label test still passes.

### GATE B
- [ ] A fresh download builds with nothing set except `toolchain.json`, and
  preflight is all `OK` on all three computers.

---

## C · Boxes around the payload (and optionally the gear)

Good news: the A-4's model already contains its bombs and tanks as separate pieces.
They are just switched off today, so this does not wait for a new aircraft.

Two rules to keep in mind:

- **The aircraft's own box still includes its payload.** The payload gets its own
  colour in the mask, but it is still part of the plane.
- **Python decides every part's ID; the engine only follows.**

- [ ] **C1 · The A-4 file lists its payload and a default loadout** 🐍 — *you
  decide the loadout*
  - Check: the A-4 loads with at least one payload, and the plane still trims with
    the weight of what it carries.
- [ ] **C2 · Each loaded station exported as its own piece**
  - Check: the mesh manifest lists a `payload` piece per loaded station.
- [ ] **C3 · The run card lists the payload pieces with their own IDs**
  - Check: the IDs are unique and never clash with other aircraft.
- [ ] **C4 · The engine gives each piece its own colour in the mask** 🪟
  - Check: the mask contains the payload's ID, and the aircraft's own tight box is
    still filled.
- [ ] **C5 · Payload boxes written into the label file (manifest v8)** 🐍
  - Check: `pytest -q tests/test_component_labels.py` passes for five cases: visible,
    off-screen, hidden behind the plane, aircraft box includes payload, and old v7
    files still read.
- [ ] **C6 · The checker and exports know about payload** 🐍
  - Check: `component_coverage` passes, and a COCO export has a `payload` category.
- [ ] **C7 · (Optional) Landing gear boxes, on the c172p** (its gear is fixed and
  visible; the A-4's gear is stowed)
  - Check: folded-up gear is "not claimed", never a zero-size box.

### GATE C
- [ ] A web-app A-4 run passes verify with `component_coverage` PASS. 🪟
- [ ] Nobody pressed an extra button or added a flag.

---

## D · New aircraft and places

- [ ] **D1 · Survey: which Chinese aircraft we are allowed to use** — *you decide*
  - So far there is no J-15, J-35 or J-11 in FlightGear's official add-on collection.
    One early Su-27SK project includes a J-11A; its licence still needs checking.
  - Recommended: J-11A only, or **cut it** if the licence isn't clean.
- [ ] **D2 · First new aircraft added** (with payload from day one)
  - Check: its config test passes, it flies level in a headless run, and it
    imports by itself.
- [ ] **D3 · (If two were chosen) second new aircraft**
- [ ] **D4 · Desert and Forest buttons in the app**
  - Check: Desert gives Grand Canyon and Forest gives Yosemite.
- [ ] **D5 · The two places are prepared once and reused** — *you decide whether
  typing the Google tiles key once is acceptable*
  - Check: a second launch says "up to date" for both.
- [ ] **D6 · Every aircraft × place combination runs with no special tweaks** 🪟
  - Check: every combination passes verify and has payload boxes.

### GATE D
- [ ] The new aircraft is available, both places work, payload boxes are present,
  and the old aircraft still pass. 🪟

---

## E · Make it simple for someone new

- [ ] **E1 · Every setting listed and sorted** into: in the app / hidden default /
  developers only / delete
  - Check: a test finds no unlisted setting.
- [ ] **E2 · All settings in one file**, edited from the app
  - Check: an empty settings file gives working defaults, and Google tiles are
    still on.
- [ ] **E3 · Settings panel in the app**
  - Check: the tiles key survives a page reload, and 6 or fewer fields are visible.
- [ ] **E4 · Pressing Capture with nothing typed gives a working run** — *you
  decide whether storm weather is in the demo default*
  - Check: the run finishes and verify has no FAIL.
- [ ] **E5 · Hidden options become checkboxes** (normals / flow / amodal)
- [ ] **E6 · Double-click launcher** (`Launch FlightSim.cmd`) 🪟
  - Check: on a fresh download, the app opens and the log ends with `READY`.
  - Check: a second launch skips everything already done.

### GATE E
- [ ] Someone new uses only the launcher and the app and gets a passing run. They
  don't read NEXT.md, open a terminal or ask you anything. 🪟
- [ ] Their questions are written in `docs/PHASE3_LOG.md`.

---

## F · Demo and wrap-up

- [ ] **F1 · Automated full run:** pick aircraft → pick place → Capture → download 🪟
  - Check: `pytest -q -m ue_host tests/test_demo_e2e.py` passes.
- [ ] **F2 · The same run works on all three computers** 🪟
  - Check: three passing rows in `docs/PHASE3_LOG.md` with the same tool versions.
- [ ] **F3 · Short guide written** (`docs/GUIDE.md`)
  - Check: under 1,000 words, with no terminal commands.
- [ ] **F4 · Video of one full run**, under 5 minutes
- [ ] **F5 · Final report:** each of the six goals with its proof

---

## The six goals (the brief's "done" list)

- [ ] 1. A new person does a full capture without help or the notes.
- [ ] 2. A J-15, J-11 or J-35 is available, and the same pipeline works in Desert and Forest.
- [ ] 3. Payload boxes appear automatically wherever the payload is visible.
- [ ] 4. One full run (configure, capture, label) with no manual steps, on locked tool versions.
- [ ] 5. A short video and a short guide exist.
- [ ] 6. Nothing a user does needs the command line.

## Not this phase

- Separate mask colours for ailerons, elevator, rudder and flaps (control surfaces).
- World-wide terrain.
- Supporting two engine versions at once, or an older-engine fallback.

## Decisions waiting on you or Shashank

- [x] **Engine:** 5.7 (5.7.4) on all three computers. *Decided 2026-10-27 by the
  owner.*
- [ ] Which payload the A-4 carries by default
- [ ] Which Chinese aircraft, or cut it
- [ ] Storm weather on in the demo, or off?
- [ ] Is typing the Google tiles key once acceptable?
- [ ] Keep control surfaces out of Phase 3?
