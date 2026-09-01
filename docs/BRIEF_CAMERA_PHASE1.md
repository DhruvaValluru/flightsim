# Camera Phase 1 — implementation plan against the current tree

How the "Phase 1 — Camera Control and Capture Geometry" plan lands on this
repository as it exists today. Read alongside `docs/PROMPT_CAMERA_PHASE1.md`,
which is the self-contained agent prompt derived from this analysis.

## 1. What the camera is today

The camera is exactly what the phase document says it must stop being: a
render-time preset, chosen by the harness, computed per-frame in C++.

* **Presets live in the engine.** `ue/.../FlightSimCameraDirector.cpp`
  implements five presets — `LaggedChase`, `GroundObserver`, `Wingman`,
  `Tower`, `CockpitShoulder` — as per-tick exponential smoothing
  (`SmoothTowards`, time-constant based). `PresetKeepsHorizonLevel()`
  records that only the cockpit preset inherits roll, and the render
  manifest records which preset flew.
* **The webapp picks the preset, not the spec.** `webapp/runs.py` hardcodes
  `WEBAPP_CHASE` offsets per airframe, passes `-camera=` / `-chase=` /
  `-wingman-abeam=180` flags to the commandlet, and switches chase→wingman
  for through-the-core tornado runs. None of this appears in the spec,
  the digest, or the review table.
* **The prompt surface explicitly ignores cameras.** `core/nl/compiler.py`
  lists `"camera", "chase", "shot", …` in `CINEMATIC_WORDS` and reports them
  in `spec.notes` as ignored. The LLM system prompt tells the model to send
  camera language to `notes`.
* **A run emits a clip, not counted frames.** The commandlet writes frames at
  `-fps=` into one directory and `render.json` (with `frame_records`), the
  webapp encodes to `clip.mp4` capped at `CLIP_SECONDS = 22`.
* **No capture manifest exists off macOS.** Off-mac, `/run` refuses
  `ue.platform` by name (`core/util/platform.py`); the headless half produces
  telemetry and `manifest.json` (spec digest + `output_digest` over telemetry)
  but nothing about cameras or frames.

## 2. The pattern the phase must reuse (it already exists five times)

The phase document's design decision 1 — "computed in Python, consumed
verbatim" — is this repo's core discipline. `core/scenario/card.py
write_run_card` carries `wind_schedule`, `orographic`, `downburst`, `rotor`,
`tornado`, `thermals`, `log_profile` as blocks computed entirely in Python;
the C++ host applies them and "derives nothing". The solved camera pose
track is simply the next such block.

Likewise the attribution machinery (design decision 3) exists and is
load-bearing:

* `core/scenario/fields.py` — frozen `Quantity` (value/unit/source/from/
  std/detail), `Source` enum `user > inferred > model > derived > default`.
* `core/scenario/spec.py` — `set()` (human edit → `user`), `plan()` (system
  move → `derived`, refuses to move user/inferred by name).
* `webapp/runs.py PLANNABLE_SOURCES = ("default", "model", "derived")` — the
  stated-value-never-moves line, called load-bearing in the source.
* `core/scenario/validate.py` — named `Violation`s
  (`altitude.terrain_clearance`, `airspeed.stall_margin`, …) surfaced by the
  webapp as first-class refusals. New `camera.*` constraints ride this
  surface for free once they produce `Violation`s.

Coordinate machinery needed by the pose solver also exists:
`core/terrain/heightfield.py` (`elevation_at`, `contains`, `bounds_m`,
`georeference.crs`), `core/terrain/ground.py TerrainGround.project`,
`core/terrain/glo30.utm_zone_crs`, and the `_projected_origin` pattern in
`webapp/runs.py` (terrain scenes use the raster CRS; flat scenes use the
spec origin's UTM zone, declared on the card as `scene_crs`).

## 3. The structural risk, precisely located

`ScenarioSpec` is a flat set of scalar `Quantity` fields serialized through
`FIELD_ORDER`. A camera **list** touches:

1. `spec.py` — `to_dict`/`from_dict`/`digest`/`render_table`/`set`/`plan`;
   `SPEC_VERSION` 5 → 6 (the version comment block at the top of the file is
   the changelog convention; `from_dict` already refuses wrong versions by
   name).
2. `core/nl/llm_compiler.py` — `FIELD_VALUE_SCHEMAS` is scalar-only and the
   import-time assert `_SPEC_FIELDS` is built from `FIELD_ORDER`; a repeated
   `cameras` block needs its own schema entry and its own generated-not-
   hand-copied assert.
3. `webapp/server.py _spec_payload` + `webapp/static/index.html` — the review
   table is built from `spec.quantities()`, which yields scalars only.
4. `core/scenario/card.py` — the card is a flat projection; cameras arrive as
   a new block (list of camera dicts + solved pose tracks).
5. `tests/test_scenario_spec.py` — round-trip and digest tests.

This is why package A goes first and why "no camera stated == exactly the
current behaviour" must be a test, not an intention: the documented default
camera is the existing chase preset with the `WEBAPP_CHASE` offsets, and a
version-6 spec with an empty camera list must drive the render pipeline to
byte-identical commandlet arguments.

Digest note: bumping `spec_version` changes every digest (the version is in
the canonical payload). That is the designed behaviour — old specs refuse by
name; completed runs recover from `provenance.json`, never by re-parsing.

## 4. Where each work package lands

| Package | New code | Touched code |
|---|---|---|
| A — spec & schema | `core/scenario/camera.py` (`CameraSpec` of `Quantity`s) | `core/scenario/spec.py` (v6, `cameras` list), `tests/test_scenario_spec.py`, `webapp/server.py`, `webapp/static/index.html` |
| B — pose solver | `core/capture/poses.py` (pure solver; five presets ported from `FlightSimCameraDirector.cpp`, explicit + geographic placement, keyframed moves) | none (consumes telemetry columns + `Heightfield`) |
| C — scheduling | `core/capture/schedule.py` (interval / waypoint / event triggers over telemetry, refractory period, exact-count guarantee) | none |
| D — validation | `core/capture/validate.py` (`camera.terrain_clearance`, `camera.scene_bounds`, `camera.hazard_intersection` via `core/environment/tornado.R_CORE_M`, `camera.intrinsics`, `camera.schedule`) | `core/scenario/validate.py` (scene-free checks), `webapp/server.py` `/run` (scene-coupled checks, the `plan_terrain_flight` refusal pattern) |
| E — manifest | `core/capture/manifest.py` (versioned `capture_manifest.json`, per-frame pose+intrinsics+projection+aircraft state, per-run digests incl. terrain raster digest) | `core/scenario/runner.py` (telemetry digest reuse), UE commandlet additively |
| F — prompt surface | — | `core/nl/compiler.py` (camera vocabulary; shrink `CINEMATIC_WORDS`), `core/nl/llm_compiler.py` (repeated camera block in `RESPONSE_SCHEMA` + parse rails + clarifying-question rule), `experiments/gate8_compiler.py` corpus |
| G — engine (macOS) | — | `card.py` (camera/pose block), `FlightSimCameraDirector` (consume-poses mode, refuse short tracks), `FlightSimRenderCommandlet` (pass per camera, per-camera frame dirs, solved-vs-applied parity, ASCII manifest — gotcha 13) |
| H — verification | `core/capture/verify.py` + `tests/test_camera_*.py` (independent reprojection, triangulation, count exactness, refusal coverage) | `scripts/mutation_check.sh` (guards for each new safeguard) |
| I — demo & docs | `flightsim/` CLI package (`capture`, `verify`), `core/capture/preview.py` (numpy + Pillow — matplotlib is not a dependency), `examples/*.yaml`, phase report doc | `README.md` |

The `flightsim/` package is new: the instructor commands in the phase
document (`python -m flightsim.capture`, `python -m flightsim.verify`) name a
package that does not exist; a thin CLI package wrapping `core.capture` and
`core.scenario` satisfies them without moving any existing module.

## 5. Sequencing

1. **A** (schema, v6, defaults-identical test) — everything else depends on it.
2. **B + C** (solver + scheduler, pure Python, heavy tests) — independent of
   each other after A; H's determinism and count-exactness tests land here.
3. **D + E** (validation + manifest) — D needs B's track for whole-track
   checks; E needs B+C for per-frame records.
4. **F** (prompt surface) — needs A's schema; gate 8 corpus extension.
5. **I** (CLI, preview, examples) — makes the phase demonstrable off-mac.
6. **G** (engine consumption) — last, macOS-only, additive; the phase is
   demonstrable without it and the parity check is its acceptance test.
7. **H** is not a stage: each package lands with its tests and mutation
   guards in the same commit, per the existing 429-test / 88-guard
   convention.

## 6. Risks carried over, with local names

* **Schema breadth** — mitigated by A-first and the defaults-identical test
  (§3 above).
* **Solved-vs-applied divergence** — the parity check in G mirrors the
  existing discipline (`gate5_ue_parity`, AGL parity); the commandlet must
  fail loudly, not clamp, when applied pose differs beyond tolerance.
* **Verification that cannot fail** — the reprojection test must implement
  projection independently inside the test (no import from
  `core/capture/poses.py`), and `scripts/mutation_check.sh` must show each
  new guard failing when disabled.
* **Platform split** — poses, schedule, validation, manifest, preview,
  verify: all pure Python, CI-covered on ubuntu/windows/macos. Rendering
  stays behind `ue_available()` and the named `ue.platform` refusal.
