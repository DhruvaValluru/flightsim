# Camera Phase 1 plan, item by item, against this repository

Every checkbox of the phase plan, with where it lives, the test that
proves it and whether a mutation guard covers it. "Done" means the
item is implemented, tested and guarded on this branch; nothing here
is inferred from a docstring. Platform note first: the plan said
"rendering is macOS-only and will remain so this phase". That was the
plan's assumption, not a property of the code; **Windows is the render
platform** (README "Platform support"), every rendered measurement
below was taken on Windows, and macOS is neither required nor the
tested path.

Commands the plan lists for the instructor, unchanged:

    git clone <repo> && cd flightsim && ./scripts/setup.sh      # Windows: .\scripts\setup.ps1
    .venv/bin/python -m flightsim.capture examples/cameras_multi.yaml --out runs/demo
    .venv/bin/python -m flightsim.verify runs/demo
    .venv/bin/python -m pytest tests/test_camera_*.py -q
    .venv/bin/uvicorn webapp.server:app --port 8008

Expected on a machine without the engine: a manifest, a geometry
preview image set, a passing verification summary with the engine
checks reported NOT RUN by name, and rendered frames refused by name
(`ue.platform`). On Windows with the built host the same commands with
`--render` produce the frames per camera.

## Design decisions

| decision | status | where |
| --- | --- | --- |
| 1. Poses computed in Python, consumed verbatim by the engine | done | `core/capture/poses.py` solves; `PoseTrack.card_block` on the run card; the commandlet's consume-poses mode refuses a track that does not cover the run and fails loudly past 10 cm / 0.05 deg applied-vs-solved |
| 2. Demonstration does not require macOS | done, and stronger | everything but pixels runs on any OS; pixels on Windows; `core/capture/preview.py` draws terrain + aircraft through the recorded matrix without the engine |
| 3. Cameras reuse the attribution machinery | done | every camera field is a provenanced `Quantity`; review table block per camera; `set()`/`plan()` through `cameras[i].<field>`; refusals by named constraint |
| 4. Repeated block, version bumped | done | `spec_version` 5 -> 6 (cameras), 7 (sensor profile); older versions refuse by name (`tests/test_camera_spec.py`, `tests/test_scenario_spec.py`) |

## Work package A -- specification and schema

| item | status | proof |
| --- | --- | --- |
| CameraSpec of provenanced quantities: id, preset/explicit, position or offset, aim mode and target, lens and sensor, resolution, near/far | done | `core/scenario/camera.py` FIELD_ORDER (33 fields incl. profile); `tests/test_camera_spec.py` |
| Camera list in the spec: serialisation, YAML round trip, digest | done | `tests/test_camera_spec.py::test_yaml_round_trip_preserves_the_digest`, `::test_specs_differing_only_in_cameras_hash_differently` |
| Review table renders each camera as a labelled block with per-field sources | done | `ScenarioSpec.render_table`; `webapp/static/index.html` camera blocks, editable |
| Version bump; version-5 document refuses by name | done | `tests/test_camera_spec.py::test_spec_version_5_documents_refuse_by_name`; guarded |
| Documented defaults; no camera stated == the current build | done | `default_cameras()`; `tests/test_camera_spec.py::test_cameraless_spec_builds_byte_identical_commandlet_args` (argv pinned byte for byte) |

## Work package B -- deterministic pose solver

| item | status | proof |
| --- | --- | --- |
| Pure function: flight state + camera -> per-sample pose with full intrinsics | done | `solve_pose_track`; `tests/test_camera_poses.py` |
| Five presets ported; only the cockpit inherits roll; the flag recorded | done | `horizon_stable` / `inherits_roll` per camera block; `tests/test_camera_poses.py` |
| Explicit placement in scene and geographic coordinates | done | `position_mode` scene / geographic via `SceneFrame` |
| Time-keyed moves over position, aim, focal length (and offsets), deterministic, rate-free | done | `MOVE_KEYS`; `_keyframe_value`; `tests/test_camera_poses.py::test_keyframes_agree_across_telemetry_rates` |
| Poses solved over headless telemetry | done | `flightsim.capture` on any OS |
| Bit-identical across invocations and across sample rates with fixed keyframes | done | invocation digest test; keyframes bit-identical across rates; lagged presets integrate exactly (first-order hold): chase 0.3 mm / wingman 0.6 mm between 10 and 20 Hz, pinned under 1 cm and stated as the track's own interpolation, not integrator error |

## Work package C -- capture scheduling

| item | status | proof |
| --- | --- | --- |
| Interval triggers by period or exact count | done | `core/capture/schedule.py`; `tests/test_camera_schedule.py` |
| Waypoint triggers by distance and by proximity | done | `_distance`, `_proximity` |
| Event triggers over recorded channels with a refractory period | done | `_event`, `refractory_s` |
| Emitted count exactly matches or refuses first | done | `camera.schedule` refusal; `count_exactness` verifier check |
| Trigger evaluation a function of the telemetry record | done | schedules solved before any render; identical with or without pixels |

## Work package D -- validation and refusal

| constraint | status | proof |
| --- | --- | --- |
| `camera.terrain_clearance` along the whole track | done | `track_violations`; `examples/cameras_refusal.yaml`, `cameras_mountain_refusal.yaml` |
| `camera.scene_bounds` | done | `track_violations` |
| `camera.hazard_intersection` (tornado core) | done | `track_violations` with the card's own tornado block |
| `camera.intrinsics` | done | `intrinsics_violations` |
| `camera.schedule` | done | `schedule_violations` |
| `camera.moves` (a keyframe key no solver field reads) | done (gap closure) | `moves_violations`; `tests/test_camera_prompts.py` |
| A stated camera field is never silently moved | done | `CameraSpec.plan` refuses; `tests/test_camera_spec.py::test_stated_camera_placement_is_never_replanned` |
| Constraints on the existing refusal surface (web) | done | `/run` verdict carries `camera_scene_violations`; `tests/test_webapp.py` |

## Work package E -- capture manifest

| item | status | proof |
| --- | --- | --- |
| Per frame: index, time, camera id, filename, position, quaternion + Euler, full intrinsics incl. principal point and resolution | done | frame record; `tests/test_camera_manifest.py` |
| Per frame: projection matrix | done (gap closure) | `intrinsic_matrix` + `projection_matrix`; verifier `projection_matrix` check (0.001 px, measured 2.5e-9) |
| Per frame: aircraft position and attitude; the reference frame | done | `aircraft` per frame; `frame` (CRS, origin) per run |
| Per run: spec digest, telemetry digest, seed, scene id, terrain digest, software version | done | top-level keys |
| Documented, versioned schema | done (gap closure) | `docs/schemas/capture_manifest.v5.schema.json`; `core/capture/schema.py`; verifier `json_schema` check; `tests/test_capture_schema.py` |
| Render manifest fields additive; gate scripts pass | done | `render.json` additive; Gate 6 unchanged |

## Work package F -- prompt surface

| item | status | proof |
| --- | --- | --- |
| Named views, counts, lens words, simple move phrases | done (moves and multi-camera in gap closure) | `core/nl/compiler.py` CAMERA_VIEW_WORDS, LENS_WORDS, MOVE_WORDS; `tests/test_camera_prompts.py` corpus, 100% |
| Model response schema: cameras with attribution, refused/overridden downstream | done | `core/nl/llm_compiler.py` bounded `cameras` block tied to `CameraSpec.FIELD_ORDER` by import-time assert; `tests/test_llm_compiler.py` |
| Clarifying question for camera intent | done (regex path in gap closure) | `camera_questions`; the LLM path's instruction; `/compile` asks once |
| Corpus check measures camera extraction | done | `tests/test_camera_prompts.py` (26 prompts, rate printed, must be 100%); Gate 8 corpus carries camera prompts for the LLM |

## Work package G -- engine consumption (on Windows)

| item | status | proof |
| --- | --- | --- |
| Solved pose track on the run card | done | `write_run_card(cameras=...)` |
| Director consumes poses per frame; refuses a track that does not cover the run | done | `FlightSimCameraDirector::SetPoseTrack` / `ApplyPoseAtTime` |
| One pass per camera into per-camera directories | done | `-camera-index=N`; `scripts/render_ue_scenario.ps1` |
| Commandlet emits the same fields; fails loudly on solved-vs-applied disagreement | done | applied-pose fields in `render.json`; 10 cm / 0.05 deg; plugin automation tests `scripts\test_ue.ps1` |
| World-to-pixel helper reused to verify against rendered frames | done | landmarks projected by the commandlet's `ProjectToPixel` into `render.json`; verifier compares (0.00 px over 916 on Windows) |

## Work package H -- verification

| item | status | proof |
| --- | --- | --- |
| Temporal alignment | done | `temporal_alignment` check; `flightsim.verify --camera-sets`; `tests/test_camera_cli.py` |
| Geometry recovery with an independent implementation | done | `tests/test_camera_engine_parity.py` builds its projection the commandlet's way and imports nothing from the verifier or the solver |
| Cross-view consistency (triangulation) | done | `two_view_triangulation`, NOT RUN without independently measured pixels; 0.000 m over 216 sightings on Windows |
| Refusal coverage | done | `tests/test_camera_validate.py`, `tests/test_camera_verify_corruption.py` |
| Count exactness across interval, waypoint, event | done | `tests/test_camera_schedule.py` |
| Mutation guards | done | `scripts/mutation_check.sh`: 260+ guards, all load-bearing on the last full run |
| Engine parity (rendered frames vs solved manifest) | done, on Windows | Camera Phase 2 measurements in `docs/CAMERA_PHASE2_WINDOWS_PLAN.md` |

## Work package I -- demonstration and documentation

| item | status | proof |
| --- | --- | --- |
| Geometry preview renderer without the engine | done | `core/capture/preview.py`; `runs/<id>/previews/` |
| Examples: multi-camera interval, waypoint over real terrain, camera inside a mountain | done | `examples/cameras_multi.yaml`, `cameras_terrain.yaml` (synthesised raster, deterministic, no network), `cameras_waypoint.yaml`, `cameras_mountain_refusal.yaml`, `cameras_refusal.yaml` |
| Single verification command with a pass/fail summary | done | `python -m flightsim.verify <run>` (writes `verification.json` too) |
| Short document: implemented, not, how to run, expected output, limitations | done | `docs/CAMERA_PHASE1_REPORT.md` (+ "Gap closure"), `docs/CAMERA_WINDOWS.md`, this checklist |

## The web page

Every number a consumer needs is on the page, not only in the files:
the frames page (`/frames.html?run=<id>&camera=<id>`) shows, per
frame, the pose, the quaternion and Euler angles, the full intrinsics,
**K and P as matrices with one-click JSON copy**, the labels (boxes,
keypoints, horizon), the recorded flight state, and a copy button for
the whole record; and, once per run, the reference frame every
position is expressed in, the spec / simulation / telemetry digests,
the seed, the scene and terrain digest, the software revision, the
manifest version with a link to its JSON Schema, the camera's own
block (preset, roll inheritance, trigger, count, pose-track digest,
sensor profile), the sampled randomisation if any, and the
verification verdict with the failed and NOT RUN checks named. The
gallery links the whole-run manifest, the verification JSON, the
schema, the run card and the provenance once per run.

## Out of scope for the phase, since delivered

Masks and boxes, domain randomisation and batch execution, all
delivered in Phase 10 (`docs/PHASE10_REPORT.md`). Ground materials,
vegetation, weather visuals and the agent controller remain out of
scope by the owner's decision; camera moves remain keyframed (no
simulated camera platform).
