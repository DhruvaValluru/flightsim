# Phase 3 — implementation plan

Source: *Phase 3 — Requirements* (13 October 2026). Theme: **pull back — refine
and consolidate rather than extend.** Written 2026-10-18 on `phase-2-final` at
8a05a3f. This file is a plan only. No code has been written for it yet.

## Repository context (the stack the tasks below are written against)

| Layer | What it is | Where |
|---|---|---|
| Physics | JSBSim 1.2.4 (Python wheel), 120 Hz | `core/fdm`, `core/control` |
| Capture and labels | Python. The manifest is v7. Per-frame `labels.objects[]` | `core/capture/labels.py`, `manifest.py`, `schema.py`, `verify.py` |
| Engine half | Unreal Engine C++ plugin plus a render commandlet. Custom-stencil ID pass (8-bit, aircraft is `int_id` 1) | `ue/Plugins/FlightSimBridge/…/FlightSimRenderCommandlet.cpp`, `ue/FlightSim.uproject` |
| User interface | FastAPI web app and static JS pages | `webapp/server.py`, `webapp/runs.py`, `webapp/static/*` |
| Aircraft | One JSON per subject plus a FlightGear `.ac` at a pinned commit plus a JSBSim FDM | `assets/aircraft_config/*.json`, `assets_pipeline/`, `scripts/import_aircraft.py` |
| Toolchain | `requirements.txt` pinned with `==` (direct dependencies only). The engine pin is `"5.7"` in four places | `core/util/platform.py:142`, `ue/FlightSim.uproject:3`, `ue/Source/*.Target.cs` |
| Tests | pytest. 156 files, 900 s timeout, `ue_host` marker for engine-only tests. Mutation guards in `scripts/mutation_check.sh` (never run them at the same time as pytest) | `tests/` |

**Where each Phase 2 blocker actually sits (checked against the tree):**

- **The label record is never completed from the rendered bundle.** The completion code exists.
  - `attach_engine_labels` is at `core/capture/labels.py:1670`. It is called from `flightsim/capture.py:1569` and `webapp/runs.py:3583`.
  - It finds no bundle, because no engine build has ever produced the `-labels` pass output (`render.json` `labels` block, ID image, depth, alone passes).
  - It then reports `without_bundle == frames` as a progress line, not a failure.
- **The build compiles against an engine nobody has installed.**
  - The pin is 5.7 everywhere (`EngineAssociation`, `UE_ENGINE_VERSION`, `IncludeOrderVersion Unreal5_7`). NEXT.md gotcha 32 says nothing has been built on 5.7, and the only measurements were taken on 5.5.
  - `scripts/build_ue.ps1:13-17` falls back to *any* `UE_5.*` it finds, so a 5.5 machine silently compiles 5.7 targets.
- **The aircraft's tight box is empty.** `bbox_2d_tight` is one of `ENGINE_LABEL_KEYS` (`labels.py:599`). It stays null with `NO_BUNDLE_BASIS` until the bundle exists. Component boxes will be written by this same path, so it has to work first.

**Size key:** **XS** = 1 file · **S** = 1–2 files · **M** = 3–5 files. "Windows" means the
step needs the render machine with the engine installed. Every other verification runs in this
Linux container or in CI.

**Owner's standing rules this plan keeps** (CLAUDE.md):

- Google tiles stay ON by default for every terrain render.
- Web-app storm weather stays ON by default.
- No scheduled PR check-ins.

Three tasks below run into these rules. Each one is flagged **[OWNER]** rather than changed silently.

---

## Phase A — Phase 2 blockers (must be green before any Phase 3 feature)

**Engine decision (owner, 2026-10-19): Unreal 5.7**, chosen for render quality. Nothing
moves back to 5.5. The pins (`EngineAssociation`, `UE_ENGINE_VERSION`, `IncludeOrderVersion
Unreal5_7`) already say 5.7. NEXT.md L69-80 records that the commandlet has already built and
rendered on 5.7 (2026-10-08/09). That needed C4883 silenced and the 5.7
`GetMaterialResource(EShaderPlatform)` signature, and the `select_if` material bug was found
then.

The following are still **5.5-era** and get redone on 5.7 below:

- the vendored JSBSim plugin and its four local patches (A4);
- the label materials, since `M_LandcoverID` failed to compile on 5.7 (A5);
- the look tuning: Gate 6 thresholds, the vertex palette and the exposure biases (B4);
- gotcha 32's text, which is stale because it still says "nothing built on 5.7" (A9).

### A1 · Record the 5.7 toolchain on the three demo machines — XS
- **Files:** `docs/TOOLCHAIN.md` (new)
- **Do:** On each machine, record the exact 5.7 build (`Engine/Build/Build.version` Major.Minor.Patch and Changelist), the Visual Studio/MSVC toolset and the Windows SDK. All three must be on the same 5.7 patch; write the one chosen (e.g. 5.7.x).
- **Verify:** `Get-Content "<UE_5.7>\Engine\Build\Build.version"` is pasted per machine. `grep -c "^| machine" docs/TOOLCHAIN.md` ≥ 3, and all rows show the same patch version.

### A2 · Lock the 5.7 pin to the patch level — M
- **Files:** `core/util/platform.py`, `ue/FlightSim.uproject`, `ue/Source/FlightSim.Target.cs`, `ue/Source/FlightSimEditor.Target.cs`, `tests/test_platform.py`
- **Do:** Keep 5.7 everywhere. Add the A1 patch level as `UE_ENGINE_PATCH` so preflight can refuse a machine on a different 5.7 hotfix. `tests/test_platform.py` (L262-318) keeps asserting that every pin equals the constant.
- **Verify:**
  - `pytest -q tests/test_platform.py` passes.
  - `python -c "import json,core.util.platform as p;assert json.load(open('ue/FlightSim.uproject'))['EngineAssociation']==p.UE_ENGINE_VERSION=='5.7'"` exits 0.

### A3 · Build scripts refuse a mismatched engine instead of globbing — S
- **Files:** `scripts/build_ue.ps1`, `scripts/ue_preflight.ps1`
- **Do:** Remove the `UE_5.*` "newest found" fallback (`build_ue.ps1:13-17`). Resolve only `UE_ROOT` or the pinned install root. Read `Engine/Build/Build.version` and refuse by name (`engine.version_mismatch: found X, pinned Y`) before invoking `Build.bat`.
- **Verify:**
  - Windows: with `UE_ROOT` pointed at a different minor version, `.\scripts\build_ue.ps1` exits non-zero and prints `engine.version_mismatch`.
  - With the pinned engine, it exits 0 and prints the version it built against.
  - Container: `pytest -q tests/test_platform.py -k build_script` (a source-reading test asserts the glob is gone).

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is fully green. Windows: `.\scripts\ue_preflight.ps1` reports the pinned engine found, with no warnings.

### A4 · Re-vendor the JSBSim plugin and re-apply the four local patches on 5.7 — S
- **Files:** `scripts/vendor_ue_plugin.ps1`, `ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json`
- **Do:** Re-run vendoring against 5.7. The plugin itself claims 5.0–5.6 and the patches were measured on 5.5. For each of the four patches in `scripts/jsbsim_plugin_patches_5_6.diff`, record in `VENDORED.json` `local_patches` whether it is still needed, still applied, or no longer applies. Also write `ue_engine_target: "5.7"`.
- **Also check:** after the plugin builds, the flight still matches. A short c172p hold on 5.7 must agree with the Python headless flight within the bound recorded on 5.5 (`experiments/gate5_ue_parity.py`).
- **Verify:**
  - Windows: `bash scripts/check_bridge_api.sh` (Git Bash) exits 0.
  - `.\scripts\build_ue.ps1` exits 0 and the log has zero `error C`.
  - `python -c "import json;d=json.load(open('<VENDORED.json path>'));assert d['ue_engine_target']=='<pin>'"`.

### A5 · The `-labels` pass actually writes a bundle — S
- **Files:** `ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimRenderCommandlet.cpp`, `scripts/ue_create_materials.py`
- **Do:**
  - Rebuild the label materials on 5.7 (`M_CustomStencilID`, `M_LandcoverID`; the latter failed on 5.7 because of the `select_if` pin name, NEXT.md L76-79), using `FLIGHTSIM_REBUILD_MATERIALS` once.
  - Make sure `M_CustomStencilID` is created headlessly. It must not depend on a by-hand editor step, so the materials script runs unattended and is idempotent.
  - Make sure the commandlet writes `frames/<camera>/render.json` with a `labels` block naming `mask`, `depth_f32` and `objects[].alone_png` for every frame rendered with `-labels`.
  - Fix whatever the first compiled run shows (the stencil path at L2876-2877, the mask writer at ~L4385).
- **Verify:** Windows: render one still through `scripts\run_test_scenarios.py --still --only 1`, then
  `python -c "import json,glob;r=json.load(open(glob.glob('runs/<id>/frames/*/render.json')[0]));assert all(k in r['labels'] for k in ('mask','depth_f32','objects'))"` exits 0. The `_mask.png` file exists and is not all zeros.

### A6 · A render run with no bundle is a failure, not a progress line — M
- **Files:** `webapp/runs.py`, `flightsim/capture.py`, `core/messages/catalog.yaml`, `tests/test_camera_labels.py`
- **Do:** After `attach_engine_labels`, a run that *requested* a render and got `attached == 0` (or `without_bundle > 0`) refuses with `labels.no_bundle`, naming the camera and frame count. A headless (no-render) run keeps today's behaviour.
- **Verify:**
  - `pytest -q tests/test_camera_labels.py -k no_bundle`: a synthetic render run with frames and no `render.json` exits 2 with `labels.no_bundle`.
  - A synthetic run with a bundle attaches every frame.
  - `python -m core.messages` (the catalogue two-way test) passes.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green. Windows: one web-app render completes and its status stream shows `engine labels attached on N of N frame(s) (0 without a bundle)`.

### A7 · The aircraft's tight box is filled and graded — S
- **Files:** `core/capture/verify.py`, `scripts/label_diagnose.py`
- **Do:**
  - Add a verifier check: every frame where the primary aircraft is `in_frame` and a bundle exists must have a non-null `bbox_2d_tight` lying inside `bbox_2d` (within the stated tolerance).
  - Extend `label_diagnose.py` to print, per camera, the counts of null tight boxes and of filled ones.
- **Verify:**
  - Container: `pytest -q tests/test_annotation_gates.py -k tight` passes on the synthetic bundle. A mutant that nulls the box makes it fail.
  - Windows: `python -m flightsim.verify runs/<id>` reports `bbox_tight` PASS and `mask_containment` PASS. `python scripts/label_diagnose.py runs/<id>` prints `tight null: 0`.

### A8 · Commit one real engine bundle as a regression fixture — S
- **Files:** `tests/fixtures/engine_bundle_min/` (one frame: render.json, mask PNG, depth .f32, manifest), `tests/test_engine_bundle_golden.py`
- **Do:** Take the smallest A7 run (one camera, one frame, low resolution) and commit it. The test runs `attach_engine_labels` on it and pins the tight box, the visible fraction and the depth median. From then on, CI covers real engine output and not only synthetic bundles.
- **Verify:** `pytest -q tests/test_engine_bundle_golden.py` passes. `du -sh tests/fixtures/engine_bundle_min` < 2 MB.

### A9 · Phase 2 close-out record — XS
- **Files:** `NEXT.md`
- **Do:** Rewrite gotcha 32 with the measured result on the pinned engine. Remove the "UNCOMPILED" statements that A4–A7 have now measured, and leave the rest marked.
- **Verify:** `grep -n "NOTHING has been built" NEXT.md` returns nothing. The gotcha cites the A7 run id and the A8 fixture path.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
**Gate A:**

- CI is green on all three OSes.
- Windows: the pinned engine builds clean.
- One web-app render has 0 frames without a bundle and 0 null tight boxes where the aircraft is in frame.

No Phase 3 feature work starts before Gate A.

---

## Phase B — Toolchain stability (Req. 4)

### B1 · Lock transitive Python dependencies with hashes — S
- **Files:** `requirements.lock` (new, `pip-compile --generate-hashes` from `requirements.txt`), `.github/workflows/ci.yml`
- **Do:** CI and the launcher (C6) install from the lock. `requirements.txt` stays the human-edited source.
- **Verify:** In a fresh venv, `pip install --require-hashes -r requirements.lock && pytest -q` passes on Linux, macOS and Windows CI. `pip freeze | diff - <(grep -E '^[a-z].*==' requirements.lock | cut -d' ' -f1)` shows no drift.

### B2 · One toolchain manifest for non-Python tools — M
- **Files:** `toolchain.json` (new: engine version, MSVC toolset, Windows SDK, Cesium for Unreal plugin version, ffmpeg version, Python version), `scripts/ue_preflight.ps1`, `core/util/platform.py`
- **Do:** `platform.py` reads the engine pin from `toolchain.json`, which replaces the A2 literal. Preflight compares each installed tool with the manifest and refuses by name (`toolchain.<tool>_mismatch`).
- **Verify:**
  - Windows: `.\scripts\ue_preflight.ps1` prints one `OK <tool> <version>` line per entry.
  - Editing `toolchain.json` to a wrong ffmpeg version makes it exit non-zero with `toolchain.ffmpeg_mismatch`.

### B3 · A test that keeps the pins in one place — XS
- **Files:** `tests/test_toolchain_pins.py`
- **Do:** Assert that `toolchain.json` engine == `EngineAssociation` == both `IncludeOrderVersion` == `UE_ENGINE_VERSION`. Also assert that `requirements.lock` covers every name in `requirements.txt`.
- **Verify:** `pytest -q tests/test_toolchain_pins.py` passes. Changing one pin by hand makes it fail with the file named.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green. Windows: preflight is all `OK`, and a clean rebuild from a fresh clone succeeds with no flag or environment variable set beyond `toolchain.json`.

### B4 · Re-tune the look on 5.7 for best render quality — M
- **Files:** `experiments/gate6_visual.py`, `ue/Config/DefaultEngine.ini`, `core/sky/plan.py`, `tests/test_gate6_visual.py`, `docs/VALIDITY.md`
- **Do:**
  - Keep the 5.7 renderer switches on: Lumen GI and reflections, virtual shadow maps, Nanite, TSR, extended luminance range. Substrate stays off unless measured.
  - Re-measure Gate 6 at `--quality beauty`. The palette and exposure biases (gotchas 6 and 7) were tuned on 5.5, so re-derive them from probe renders on 5.7, not by theory.
  - Record the 5.7 numbers beside the 5.5 ones in VALIDITY 2.13 (the 5.5 values stay as history, marked "measured on 5.5").
  - Labels are unaffected: the ID and depth passes do not depend on the look, so this task cannot break A5–A8.
- **Verify:** Windows:
  - `python experiments/gate6_visual.py --quality beauty` passes every clause.
  - `python experiments/gate6_visual.py` (measure quality) still passes.
  - `python experiments/gate10_render_repro.py` reports a bit-identical or bounded verdict on 5.7.
  - Container: `pytest -q tests/test_gate6_visual.py` passes.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
Windows: a beauty-quality render of the default run passes Gate 6 on 5.7, and the A8 label fixture still passes.

---

## Phase C — Consolidate the capture pipeline (Req. 1)

### C1 · Inventory the configuration surface — S
- **Files:** `core/registry.py`, `docs/CONFIG_SURFACE.md` (new)
- **Do:**
  - List every `FLIGHTSIM_*` variable (27 today; `FLIGHTSIM_LLM` 64 reads, `GOOGLE_TILES` 30, `SKY` 18, `WEATHER_BACKEND` 15, `RENDER_QUALITY` 14, `CAPTURE_PASSES` 7…), plus `UE_ROOT` and every `flightsim/*.py` CLI flag that the user path reaches.
  - Give each one a decision: **UI** (stays exposed, moves to the interface), **default** (hidden, value fixed), **dev-only** (tests and debugging scripts), or **remove**.
- **Verify:** `pytest -q tests/test_registry.py` gains a check that every `os.environ`/`getenv("FLIGHTSIM_…")` name found by `grep -rhoE 'FLIGHTSIM_[A-Z_]+' core webapp flightsim | sort -u` is registered and carries a decision.

### C2 · A single configuration path — M
- **Files:** `core/registry.py`, `webapp/server.py`, `webapp/runs.py`, `tests/test_settings.py` (new)
- **Do:**
  - One settings file (`settings.json` in the user's FlightSim data directory) becomes the only source for the "UI" items, read through the registry.
  - Environment variables remain as developer overrides only, and the run record says when one was used.
  - Add `GET/PUT /settings` endpoints with validation by the registry.
  - The owner's defaults are kept: Google tiles on, storm weather on.
- **Verify:**
  - `pytest -q tests/test_settings.py`: an empty settings file plus no environment gives the documented defaults.
  - A PUT round-trips.
  - An environment override appears in the run's `applied_variables` with basis `env override`.
  - `FLIGHTSIM_GOOGLE_TILES` is still honoured as `off` (CLAUDE.md rule).

### C3 · Settings panel in the interface — S
- **Files:** `webapp/static/index.html`, `webapp/static/settings.js` (new)
- **Do:**
  - Expose only the C1 "UI" items: the Google tiles key, the Cesium plugin status, the engine location (read-only, from preflight), render quality, and the LLM key. Everything else goes in a collapsed "Advanced" section or disappears.
  - Show a missing required item (for example the tiles key) as a named, fixable message, not as a failed run.
- **Verify:** A headless-Chromium page test in the style of `tests/test_route_page.py` loads the page, sets the tiles key, reloads, and finds it persisted through `/settings`. The visible top-level field count is ≤ 6.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green. Start the server with an empty environment and confirm `GET /settings` returns every default. The page renders the panel with no console errors.

### C4 · Defaults that produce a working capture when nothing is stated — S
- **Files:** `webapp/runs.py`, `webapp/server.py`
- **Do:**
  - Give `/run` a fully defaulted request: default aircraft, the Desert environment once E4 lands (prairie until then), the chase camera, a short clip, and labels on.
  - The "Capture" button submits it with no prompt typed.
  - **[OWNER]** The storm-weather default (CLAUDE.md) also applies to this default run. Confirm whether the demo default keeps it.
- **Verify:**
  - `pytest -q tests/test_settings.py -k default_run`: `POST /run {}` in headless mode reaches `done`, and `verify.json` has no FAIL.
  - Windows: the same request renders and passes `python -m flightsim.verify`.

### C5 · Move env-only capture options into the UI or remove them — S
- **Files:** `webapp/capture.py`, `webapp/static/index.html`
- **Do:** `FLIGHTSIM_CAPTURE_PASSES` (normals, flow, amodal) becomes checkboxes. The X-Plane and debug variables marked "dev-only" in C1 are no longer read on the web path.
- **Verify:**
  - `grep -n "FLIGHTSIM_CAPTURE_PASSES\|FLIGHTSIM_XPLANE" webapp/*.py` returns only the registry-override read.
  - The page test ticks "normals", and the run's `labels.passes.normal` is declared.

### C6 · One-click launcher (no command line on the user path) — M
- **Files:** `Launch FlightSim.cmd` (new, double-click), `scripts/launch.ps1` (new), `scripts/ue_preflight.ps1`, `scripts/setup.ps1`
- **Do:** The launcher runs these steps in order and stops at the first step that fails, showing a named reason in a window:
  1. Create the venv from `requirements.lock`.
  2. Run preflight against `toolchain.json`.
  3. Build if the binaries are older than the sources.
  4. Run `ue_create_materials.py` if any material is missing or stale.
  5. Import aircraft models, which the web app already does on demand.
  6. Start the server and open the browser.
- **Verify:**
  - Windows, fresh clone: double-click `Launch FlightSim.cmd`. The browser opens on the app within the first-run budget recorded in `docs/TOOLCHAIN.md`, and `logs/launch.log` ends with `READY`.
  - A second launch skips the build and the materials (logged `up to date`).
  - Container: `pytest -q tests/test_launcher.py` (a source-reading test) asserts the step order and that no step prompts for input.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
**Gate C:**

- On Windows, someone other than the two authors clones the repo, double-clicks the launcher, presses Capture, and gets a verified run.
- They do not touch NEXT.md, a terminal or an environment variable.
- Record their unanswered questions in `docs/PHASE3_LOG.md`.

---

## Phase D — Component-level annotation (Req. 3; payload required, landing gear optional)

Conventions are reused, not duplicated. A component is one more entry in the frame's
`labels.objects[]`, with:

- a `parent` id (the aircraft) and a `class_id` of `payload` or `landing_gear`;
- the same keys as the aircraft: `bbox_2d_hull`, `fraction_in_frame`, `bbox_2d_tight`, `visible_fraction`, `occluded_by`, `not_claimed`, `basis`;
- the same null-with-basis rule when it is out of frame or hidden.

### D1 · `components` block in the aircraft config — S
- **Files:** `core/capture/airframe.py`, `assets/aircraft_config/A4.json`
- **Do:**
  - Add an optional `components: [{id, class: payload|landing_gear, parts: [<regex on .ac part names>], station?: <loading station>}]` block.
  - Landing gear reuses the existing `gear_geometry` patterns.
  - The loader refuses a pattern that matches no part (`aircraft.component_unmatched`).
  - Start on the A4, the only existing airframe with store stations (`A4.json:120-164`).
- **Verify:** `pytest -q tests/test_airframe.py -k components` loads the A4 with ≥ 1 payload component. A config with a dead regex is refused by name.

### D2 · The mesh pipeline keeps components as named sub-meshes — M
- **Files:** `assets_pipeline/convert.py`, `assets_pipeline/importer.py`, `scripts/ue_import_aircraft.py`
- **Do:**
  - Split each component's parts into their own static mesh and record them in `mesh_manifest.json` under `components[]` with id, class, extents and origin. This bumps the manifest version, and a stale manifest is re-converted, as today.
  - **Spike first (one hour):** confirm the A4 `.ac` source actually contains store geometry. If it does not, use the first aircraft from E2 for D2–D6 and keep the A4 for gear only.
- **Verify:**
  - `python assets_pipeline/convert.py assets/aircraft_config/A4.json`, then `python -c "import json;m=json.load(open('<A4 mesh_manifest.json>'));assert any(c['class']=='payload' for c in m['components'])"`.
  - Windows: the import log lists one `SM_<aircraft>_<component>` per component.

### D3 · Each component gets its own stencil id in the render — M
- **Files:** `FlightSimRenderCommandlet.cpp`, `FlightSimScenarioWorld.cpp`, `FlightSimScenarioWorld.h`
- **Do:**
  - Attach the component meshes under the aircraft's `MeshOrigin`. Give each one `SetCustomDepthStencilValue(<component int_id>)`; the 8-bit budget is ample.
  - List them in `render.json` `labels.objects[]` with `parent`, plus an alone pass per component so `visible_fraction` can be computed.
- **Verify:** Windows: render one A4 (or E2) still with `-labels`. Then `python -c` on `render.json` asserts ≥ 1 object with `parent == 1`, `class == "payload"`. The mask PNG contains that object's int_id: `numpy.unique(mask)` includes it.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green, including A8's golden fixture unchanged. The aircraft's own tight box is still filled on the D3 render.

### D4 · Component label records, written in the existing manifest — M
- **Files:** `core/capture/labels.py`, `core/capture/manifest.py`, `core/capture/schema.py`, `tests/test_component_labels.py` (new)
- **Do:**
  - `object_label_record` emits component entries. The analytic `bbox_2d_hull` and `fraction_in_frame` come from the component extents projected through the same camera.
  - `attach_engine_labels`/`measure_object` fill the engine keys from the component's int_id.
  - Bump `MANIFEST_VERSION` to 8, keeping 3–7 supported. `conventions()` documents `payload` and `landing_gear`.
- **Verify:** `pytest -q tests/test_component_labels.py` covers:
  - a synthetic bundle with a payload pixel blob gives a tight box equal to the blob;
  - an out-of-frame payload gives `bbox_2d_tight: null` with the out-of-frame basis;
  - a payload hidden behind the fuselage gives `visible_fraction == 0` and `occluded_by == [<aircraft id>]`;
  - `validate_manifest` accepts v8 and still accepts v7.

### D5 · Verifier and exporters know the components — M
- **Files:** `core/capture/verify.py`, `core/dataset/export.py`, `tests/test_dataset_boxes.py`
- **Do:**
  - The verifier checks that each component's tight box lies within its hull and within its parent's tight box. Every frame with visible payload pixels must carry a payload record; this is the acceptance criterion 3 check.
  - COCO, YOLO and VOC export `payload` (and `landing_gear`) as their own categories.
  - The independent round-trip readers re-read them.
- **Verify:** `pytest -q tests/test_dataset_boxes.py tests/test_annotation_gates.py -k component` passes. A mutant that drops the payload record fails `component_coverage`.

### D6 · Landing gear (optional; only if D1–D5 are green) — S
- **Files:** `assets/aircraft_config/c172p.json`, `assets/aircraft_config/B747.json`
- **Do:** Add `landing_gear` components from the existing `gear_geometry` patterns. Retracted gear is `not_claimed` with basis `gear retracted (gear/gear-pos-norm=0)`, never a zero-size box.
- **Verify:**
  - `pytest -q tests/test_component_labels.py -k gear` passes.
  - Windows: a c172p render gives a `landing_gear` tight box on every frame where `numpy.unique(mask)` contains its id.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
**Gate D:**

- On Windows, a web-app run of the payload aircraft passes `python -m flightsim.verify` with `component_coverage` PASS.
- `dataset.zip` opens in COCO with a `payload` category.
- No user step was added (no flag, no post-pass button).

---

## Phase E — New subjects and environments (Req. 2)

### E1 · Source survey and go/no-go for J-15 / J-11 / J-35 — XS
- **Files:** `docs/PHASE3_AIRCRAFT_SOURCES.md` (new)
- **Do:** For each candidate, give:
  - the mesh source with licence and pinned commit (FlightGear hangars first, as for the existing six);
  - the JSBSim FDM source (stock, community, or a repo-owned derivation under `assets/fdm_root/aircraft/`, as the A4 is);
  - whether the mesh has separable payload and gear parts;
  - the keypoint provenance (`fdm_contact` / `structural_in` / `estimate`).
- **[OWNER]** Pick one or two. If no licence-clean source exists, say so now, per the brief's "say so early and we will cut it".
- **Verify:** The file has one table row per candidate with every column filled or marked `none found`, and a recorded owner decision line.

### E2 · First new aircraft — M
- **Files:** `assets/aircraft_config/<J15|J11|J35>.json`, `assets/fdm_root/aircraft/<id>/<id>.xml`, `assets/fdm_root/aircraft/<id>/engine/<engine>.xml`, `tests/test_aircraft_configs.py`
- **Do:** Write the config with labels (dimensions, the 7 `KEYPOINT_NAMES`), `components` (payload, and optionally gear), `limits`, `licence`, and `gear_geometry`. The FDM must trim at the default run's altitude and speed.
- **Verify:**
  - `pytest -q tests/test_aircraft_configs.py -k <id>` passes (config schema, licence file present, keypoints resolve).
  - `python -m flightsim.capture` headless on a default card with this aircraft trims and verifies with no FAIL (developer check).
  - Windows: `python scripts/import_aircraft.py <id>` exits 0.

### E3 · Second new aircraft (only if the owner chose two in E1) — S
- **Files:** `assets/aircraft_config/<id2>.json`, `assets/fdm_root/aircraft/<id2>/…`
- **Do:** Same as E2. If the type shares an engine or FDM lineage with E2 (J-11 and J-15 both come from the Su-27 family), reuse E2's engine file and do not copy it.
- **Verify:** Same commands as E2 with `<id2>`.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green. The `/aircraft` endpoint lists the new type or types. The web app's aircraft picker shows them, with no other UI change.

### E4 · "Desert" and "Forest" as named environment presets — S
- **Files:** `webapp/runs.py`, `webapp/static/index.html`
- **Do:**
  - Surface the existing `plan_scene_setting` rule (desert → `grand_canyon`, forest → `yosemite`) as a two-option environment picker. A preset fixes the location, surface class, sun and season.
  - Global terrain is not in scope: only these two, plus the existing default.
  - Google tiles remain the ground (CLAUDE.md).
- **Verify:** `pytest -q tests/test_route_map.py tests/test_settings.py -k environment`. Choosing "Desert" gives `scene.terrain_source == grand_canyon` and surface `desert` on the run card; "Forest" gives `yosemite`/`forest`.

### E5 · Make the two environments reliable offline-of-bake — S
- **Files:** `scripts/launch.ps1`, `scripts/bake_terrain.py`
- **Do:**
  - The launcher pre-bakes the two preset GLO-30 tiles on first run. It checks the sha256 recorded in the bake sidecar and never re-streams on later runs.
  - **[OWNER]** Google tiles still stream at render time and need a key. That is the one external dependency the demo keeps; confirm that this is acceptable as "no manual intervention" once the key is entered in Settings.
- **Verify:**
  - Windows: a second launch logs `bake grand_canyon up to date` and `bake yosemite up to date`.
  - With the network to the DEM host blocked, a Desert run still reaches the render step.

### E6 · Same pipeline, unchanged, across the matrix — M
- **Files:** `scripts/run_test_scenarios.py`, `tests/test_phase3_matrix.py` (new), `docs/PHASE3_LOG.md`
- **Do:** Add a developer matrix of {new aircraft × Desert, Forest} using the *default* run plus only the aircraft and environment choice, with no per-cell overrides. Record the run ids and verify results.
- **Verify:**
  - Container: `pytest -q tests/test_phase3_matrix.py` (headless cells) passes.
  - Windows: `python scripts/run_test_scenarios.py --phase3-matrix` gives every cell `verify PASS` with `component_coverage` PASS. `git diff --stat` between cells' card templates touches only `aircraft` and `scene`.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
**Gate E:** acceptance criteria 2 and 3 are met on Windows. The A8 golden fixture and A7 tight-box checks are still green, so no regression on the original aircraft.

---

## Phase F — Demonstration and close-out (Req. 4–5)

### F1 · Automated end-to-end run: configure → capture → label — S
- **Files:** `tests/test_demo_e2e.py` (new, `ue_host` marker), `webapp/static/index.html`
- **Do:** Drive the real page in a headless browser through these steps with no other input:
  1. Pick the aircraft.
  2. Pick Desert.
  3. Press Capture.
  4. Wait for `done`.
  5. Download `dataset.zip`.
- **Verify:** Windows: `pytest -q -m ue_host tests/test_demo_e2e.py` passes, and the downloaded zip's manifest has payload boxes on every frame with payload pixels. CI (no engine) runs the same test in headless mode up to the render step.

### F2 · Three-machine reproduction — XS
- **Files:** `docs/PHASE3_LOG.md`
- **Do:** Run F1 from a fresh clone on each of the three A1 machines. Record the machine, toolchain preflight output, run id, verify result and wall time.
- **Verify:** The file has three rows, each with `verify PASS` and the same toolchain hash (`sha256sum toolchain.json requirements.lock`).

### F3 · The short guide — S
- **Files:** `docs/GUIDE.md` (new), `README.md`
- **Do:** Cover only what to open, what to choose, what to expect, and what the output contains, including the manifest's aircraft and component boxes. The README's first screen links the guide. NEXT.md is no longer referenced on the user path.
- **Verify:**
  - `wc -w docs/GUIDE.md` < 1000.
  - `grep -nE '\bpython\b|\.ps1|\$env:|FLIGHTSIM_|--[a-z]' docs/GUIDE.md` returns nothing, so there is no command line in the guide (acceptance criterion 6).
  - A new reader completes Gate C's walkthrough from the guide alone.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
`pytest -q` is green on all three OSes. F2's three rows all pass. `docs/GUIDE.md` passes its grep.

### F4 · Recorded run — XS
- **Files:** `docs/demo/README.md` (link and checksum to the video; the video itself is stored outside git if it is over 20 MB)
- **Do:** Screen-record one F1 run from double-clicking the launcher to opening the dataset.
- **Verify:** `ffprobe -v error -show_entries format=duration <video>` ≤ 300 s. The recorded run id appears in `docs/PHASE3_LOG.md` with `verify PASS`.

### F5 · Phase 3 acceptance sheet — XS
- **Files:** `docs/PHASE3_REPORT.md` (new)
- **Do:** Give one row per acceptance criterion (1–6 of the brief), with the evidence (task id, run id, test name), plus what was cut and why.
- **Verify:** `grep -c "^| [1-6] " docs/PHASE3_REPORT.md` == 6, and no row's evidence cell is empty.

**[CHECKPOINT - PAUSE AND RE-VERIFY SYSTEM STATE]**
Final: every acceptance criterion has evidence. CI is green. Nothing on the user path needs the command line.

---

## Acceptance criteria → tasks

| # | Criterion (brief) | Closed by |
|---|---|---|
| 1 | A newcomer completes a capture without the notes | C1–C6, Gate C, F3 |
| 2 | J-35/J-15/J-11 available; same pipeline in desert and forest | E1–E6 |
| 3 | Payload boxes in the manifest wherever visible | A5–A8 (path), D1–D5 |
| 4 | Hands-off end-to-end run on a pinned toolchain | A1–A4, B1–B4, F1–F2 |
| 5 | Short video plus a guide short enough to read | F3, F4 |
| 6 | No command line on the user path | C3, C5, C6, F3 |

## Owner decisions this plan waits on

1. ~~**A1:** the engine pin~~ Decided 2026-10-19: **5.7**, for render quality. A1, A4, A5, A9 and B4 redo the 5.5-era pieces on it.
2. **E1:** which one or two Chinese airframes, given licence-clean sources. This is the item most likely to be cut.
3. **C4/E5:** whether the storm-weather default and the Google-tiles key (both owner rules) sit inside a "no manual intervention" demo as they are.
4. **D2 spike:** whether the A4 or the first new airframe carries the payload work.
