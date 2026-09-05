# Camera Phase 1, honest audit and the plan to finish it

Audited 2026-09-03 against the Phase 1 brief, after the first run on the
user's Windows machine produced a clip plus schematic "geometry
previews" instead of a defined set of rendered frames.

## What the brief asked for, and what the build does

| brief item | state on the branch | verdict |
|---|---|---|
| A. camera as provenanced spec block, v6, digest, review table, defaults | done, tested | met |
| B. deterministic pose solver, five presets, explicit placement, keyframes | done, bit-identical test | met |
| C. interval / count / waypoint / event triggers, exact counts, telemetry-driven | done, tested | met |
| D. named refusals (terrain, bounds, hazard, intrinsics, schedule) | done, tested, guarded | met |
| E. per-frame manifest with pose, intrinsics, projection, aircraft state, run digests, versioned schema | done | met |
| F. prompt vocabulary, model schema, clarifying question, corpus check | done | met |
| **G. engine consumes the solved poses, one pass per camera, frames in per-camera directories, applied-vs-solved parity** | C++ written, **never compiled, never run**; the web render flow **does not call it**: it still drives the commandlet with the old preset words and renders one clip | **not met** |
| **"A run should emit a defined number of images rather than a clip"** | true only for the headless previews; on a render-capable machine the run emits a clip and schematic previews | **not met** |
| H. alignment, recovery, consistency, refusal, count, mutation guards | done for the headless path | met |
| H. engine parity (frames agree with the manifest) | never exercised | not met |
| I. geometry preview | exists, but minimal: a 48 x 48 dot sampling of the raster, the aircraft as a circle, a track line, half scale, black background | met in letter, poor in substance |
| I. examples, `flightsim.verify`, document | done | met |

**Why it went wrong.** The brief scoped rendering as macOS-only, so the
engine half was written as C++ nobody in that session could compile and
the web flow was left on its pre-camera path. The Windows deploy later
made rendering available on the user's machine, but nothing re-wired
the web run to the pose-track pass. The result: the one place the user
looks (the run page) shows the weakest artefact the phase produced.

## The plan

Priority order. Each item is code + tests + a guard + one commit, suite
green after each, and each engine item ends with a verification the
user runs on the Windows machine (this environment has no engine), with
the log pasted back and iterated until it passes.

### P0. The run emits rendered frames, not a clip (package G, finished)

1. `webapp/runs.py` render flow: when the spec carries cameras with a
   capture schedule, invoke the commandlet once per camera with
   `-camera-index=N` and `-frames=<run>/capture/frames/<camera_id>`,
   passing the card that already carries the solved pose track and
   capture times. The clip becomes a by-product of camera 0, not the
   deliverable.
2. `FlightSimRenderCommandlet.cpp`: capture at the card's scheduled
   instants (the nearest fixed step; record the applied time), write
   one PNG per scheduled frame named by the manifest's index, and emit
   the applied pose per frame into `render.json`. Refuse when the track
   does not cover the run. Keep the 10 cm applied-vs-solved parity
   check and make it fail the pass, not warn.
3. Reconcile: `core/capture/verify.py` gains an engine-parity check that
   reads `render.json` per camera, compares applied to solved pose and
   time per frame, and reprojects the aircraft position into each
   rendered PNG (the existing world-to-pixel helper) to confirm the
   aircraft sits where the manifest says. This is H's "engine parity"
   row, made real.
4. Verification on the user's machine: build the plugin, run one
   multi-camera spec from the page, confirm `capture/frames/<camera>/`
   holds exactly the scheduled count, `verify.json` shows the engine
   parity check passing, and the temporal-alignment test (same spec,
   two camera sets) passes on rendered frames.

### P1. A preview worth looking at (package I, done properly)

1. Terrain as a projected wireframe of the raster (grid lines, not
   dots), depth-shaded, with a horizon line; flat scenes get a ground
   grid with distance rings.
2. The aircraft as a scaled three-axis body from the FDM's own span and
   length, with heading and track, not a circle.
3. Full-resolution output by default; a labelled frame header with
   camera id, index, simulation time, position and look direction.
4. When rendered frames exist, draw the reprojected aircraft box over
   the rendered PNG as a second image: the verification made visible.
5. A per-camera contact sheet.

### P2. The page tells the truth and shows the frames

1. Gallery per camera of rendered frames when they exist, previews
   only as a labelled fallback ("no engine on this machine").
2. Status lines say what happened: "8 frames scheduled, 8 rendered,
   8 previews" or "8 scheduled, 0 rendered (engine pass not run)".
   Today's "captured 4 frame(s)" for four previews is misleading.
3. The frame set downloads as its own zip, with the manifest.

### P3. Defaults that match the brief

A camera-less prompt keeps today's clip behaviour (pinned by test). A
prompt that mentions imagery, a camera, or a count schedules frames by
default; the clarifying question already exists and should fire.

### P4. Docs

Rewrite the Phase 1 report's "engine boundary" section with what was
verified on Windows, and the Known Limitations to match.

## What is needed from the user

The engine. P0 and P1.4 cannot be verified here. Each engine step ends
with a command to run and a log to paste back. Everything else is
verified in this environment and by CI.
