# Phase 3 checklist

The simple-words version of `tasks/phase3_todo.md`. Tick a box only when its
**check** passes. Do the steps in order. Do not start a step until the gate before
it is ticked.

Ticking: change `[ ]` to `[x]` in this file and commit it.

---

## Step 1 · Fix what's broken from Phase 2

**Engine: Unreal 5.7** (decided, for best render quality). Already built and rendered on
5.7 once. What still dates from 5.5 gets redone below.

- [ ] **All three computers on the same 5.7 patch**, written in `docs/TOOLCHAIN.md`
  - Check: all three rows show the same 5.7.x.
- [ ] **Project locked to that exact 5.7 patch**
  - Check: `pytest -q tests/test_platform.py` passes.
- [ ] **Build refuses the wrong engine**
  - Check: pointing it at a different engine version stops with `engine.version_mismatch`.
  - Check: the right engine builds with no errors.
- [ ] **JSBSim plugin redone on 5.7** (it was set up on 5.5)
  - Check: `scripts/check_bridge_api.sh` passes and the build passes.
  - Check: each of the 4 patches is marked needed or not needed.
  - Check: the plane flies the same in the engine as in Python (`gate5_ue_parity.py`).
- [ ] **Label materials rebuilt on 5.7** (one of them failed to compile on 5.7)
- [ ] **Engine writes the label images**
  - Check: after one render, `render.json` has a `labels` block.
  - Check: the mask picture is not blank.
- [ ] **No label images = the run fails loudly**
  - Check: a run with missing label images stops with `labels.no_bundle`.
- [ ] **Aircraft tight box is filled in**
  - Check: `python -m flightsim.verify runs/<id>` shows `bbox_tight` PASS.
  - Check: `label_diagnose.py` shows `tight null: 0`.
- [ ] **One real rendered frame saved as a test**
  - Check: `pytest -q tests/test_engine_bundle_golden.py` passes.
- [ ] **NEXT.md updated with what was measured**

### GATE 1

- [ ] Tests pass on all three operating systems.
- [ ] The engine builds clean.
- [ ] One app render: every frame has labels and the tight box is never empty.

---

## Step 2 · Lock the tools

- [ ] **Exact versions of every Python package saved**, with hashes, in `requirements.lock`
  - Check: a fresh install from it, then `pytest -q`, passes.
- [ ] **One file lists every other tool's version** (`toolchain.json`): engine, Visual Studio, Windows SDK, Cesium, ffmpeg, Python
  - Check: preflight prints `OK` for each.
  - Check: a wrong version makes preflight stop.
- [ ] **A test catches any version drifting**
  - Check: `pytest -q tests/test_toolchain_pins.py` passes.
  - Check: changing one version by hand makes it fail.

- [ ] **Picture quality re-tuned on 5.7** (Lumen, shadows, Nanite, TSR stay on; brightness and colours were tuned on 5.5)
  - Check: `python experiments/gate6_visual.py --quality beauty` passes.
  - Check: renders repeat the same way (`gate10_render_repro.py`).
  - Check: the labels test still passes.

### GATE 2

- [ ] A fresh clone builds with nothing set except the version file.
- [ ] A beauty-quality render passes the picture checks on 5.7.

---

## Step 3 · Make it simple to use

- [ ] **Every setting listed and sorted** into: in the app / hidden default / developers only / delete
  - Check: a test finds no unlisted setting.
- [ ] **All settings in one file**, edited from the app
  - Check: an empty settings file gives working defaults.
  - Check: Google tiles are still on.
- [ ] **Settings panel in the app**
  - Check: entering the tiles key survives a page reload.
  - Check: 6 or fewer fields are visible.
- [ ] **Pressing Capture with nothing changed gives a working run**
  - Check: the run finishes and verify has no FAIL.
- [ ] **Hidden options moved into the app or removed** (normals / flow / amodal become checkboxes)
- [ ] **Double-click launcher works**
  - Check: on a fresh clone the app opens in the browser and the log ends with `READY`.
  - Check: a second launch skips the build.

### GATE 3

- [ ] Someone new uses only the launcher and the app and gets a passing run, without reading NEXT.md, opening a terminal or asking you anything.
- [ ] Their questions are written in `docs/PHASE3_LOG.md`.

---

## Step 4 · Boxes around parts of the aircraft

- [ ] **Aircraft files can list their parts** (payload, landing gear)
  - Check: the A4 loads with at least one payload part.
- [ ] **Quick check: does the A4 model actually include its missiles or bombs?**
  - If not, use the new Chinese aircraft for this step instead.
- [ ] **Parts kept as separate pieces when importing**
  - Check: the import log lists one mesh per part.
- [ ] **Each part gets its own ID colour in the render**
  - Check: the mask contains the payload's ID.
- [ ] **Payload boxes written into the label file**
  - Check: `pytest -q tests/test_component_labels.py` passes for three cases: visible, off-screen and hidden behind the plane.
- [ ] **Checker and dataset exports know about payload**
  - Check: the COCO export has a `payload` category.
- [ ] *(Optional)* **Landing gear boxes**
  - Check: gear that is folded up is marked "not claimed", not given a zero-size box.

### GATE 4

- [ ] An app run passes verify with `component_coverage` PASS.
- [ ] You didn't have to press any extra button or add any flag.

---

## Step 5 · New aircraft and places

- [ ] **Survey: which of the J-15 / J-11 / J-35 have models we're allowed to use**
  - **You decide** which one or two to add, or cut this.
- [ ] **First new aircraft added**
  - Check: its config test passes.
  - Check: it flies level in a headless run.
  - Check: it imports into the engine.
- [ ] *(If two were chosen)* **Second new aircraft added**
- [ ] **Desert and Forest buttons in the app**
  - Check: Desert gives Grand Canyon terrain and Forest gives Yosemite.
- [ ] **The two places are prepared once and reused**
  - Check: a second launch says "up to date" for both.
- [ ] **Every aircraft × place combination runs with no special tweaks**
  - Check: every combination passes verify and has payload boxes.

### GATE 5

- [ ] New aircraft available, both places work, payload boxes present.
- [ ] The old aircraft still pass their tests.

---

## Step 6 · Demo and wrap-up

- [ ] **Automated full run**: pick aircraft → pick place → Capture → download data
  - Check: `pytest -q -m ue_host tests/test_demo_e2e.py` passes.
- [ ] **Same run works on all three computers**
  - Check: three passing rows in `docs/PHASE3_LOG.md`.
- [ ] **Short guide written** (`docs/GUIDE.md`)
  - Check: under 1,000 words.
  - Check: no terminal commands in it.
- [ ] **Video recorded** of one full run, under 5 minutes
- [ ] **Final report**: each of the six goals has proof next to it

---

## The six goals (the brief's "done" list)

- [ ] 1. A new person does a full capture without help or the notes.
- [ ] 2. A J-15, J-11 or J-35 is available, and the same pipeline works in Desert and Forest.
- [ ] 3. Payload boxes appear automatically wherever the payload is visible.
- [ ] 4. One full run (configure, capture, label) with no manual steps, on locked tool versions.
- [ ] 5. A short video and a short guide exist.
- [ ] 6. Nothing a user does needs the command line.

## Decisions waiting on you or Shashank

- [x] Engine version: **5.7** (decided 2026-10-19)
- [ ] Which Chinese aircraft, or cut it
- [ ] Keep storm weather on by default for the demo?
- [ ] Is entering the Google tiles key once acceptable?
- [ ] Do payload boxes start on the A4 or the new aircraft?
