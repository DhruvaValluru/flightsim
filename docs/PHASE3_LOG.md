# Phase 3 log

What was run on a real machine, with its result. Written by the Phase 3
Windows runner (the sheet's rule: a failed check is written here before it
is fixed). Outputs live under `runs/p3/<run id>/`; synopses under
`docs/phase3/packets/`; the cross-check records in `docs/phase3/sync_log_<L>.md`.

Machine: Windows laptop, MSVC 14.44.35207, Windows SDK 10.0.26100.0, Python
3.12.10. Run A-1 rows below were measured on UE 5.5.4 (changelist 40574608,
decision 1); Cesium for Unreal was never installed for 5.5 (the 2.28.0 copy was
downloaded but not installed). From decision 10 (2026-11-04, owner override)
the pin is UE 5.7.4 (changelist 51494982) with Cesium for Unreal 2.30.0 in the
engine's Marketplace folder; later rows say which engine they ran on.

## Letter A

| Box | Run | Check | Result | Note |
|---|---|---|---|---|
| A3 | A-1 | `build_ue.ps1` with `UE_ROOT` at UE_5.7 | exit 1, `engine.version_mismatch: found 5.7.4, pinned 5.5`, Build.bat not started | 2026-11-04 |
| A3 | A-1 | `ue_preflight.ps1` at UE_5.7 | exit 1, `engine.version_mismatch: found 5.7.4, pinned 5.5` | |
| A3 | A-1 | `ue_preflight.ps1` at the pinned 5.5.4 | exit 0, `engine UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5` | |
| A2 | A-1 | `build_ue.ps1` on 5.5.4 (first run) | FAIL: `FlightSimVisualScene.cpp(1128): error C2039: 'LoadSynchronous'` (5.7-only) | fixed in be6bf574 (version guard) |
| A2 | A-1 | `build_ue.ps1` on 5.5.4 after be6bf574 | exit 0, zero `error C`, `stamped 770fa283…` | |
| A2 | A-1 | `pytest -q tests/test_platform.py` | exit 0 with `FLIGHTSIM_GOOGLE_TILES` unset; with the owner's `=on` one pre-existing test fails (terrain.unbaked), same on bd68745b | environment interaction, not letter A |
| A2 | A-1 | hand-edit `FlightSim.Target.cs` to Unreal5_7 | exit 1, `ue\Source\FlightSim.Target.cs does not pin EngineIncludeOrderVersion.Unreal5_5` | reverted |
| A4 | A-1 | PowerShell hash of `tests/fixtures/stamp_tree` vs golden | equal (`0141215e…`); repo hash PowerShell == Python (`770fa283…`) | |
| A4 | A-1 | edit a `.cpp`, no rebuild, `capture --render` | `binary_stale_reason` names both hashes; the CLI refused `google_tiles.terrain` first (no bake yet) | re-run after the bake |
| A5 | A-1 | `vendor_ue_plugin.ps1` | run 1 FAIL (stale temp checkout, `fatal: not a git repository`); run 2 exit 0, dll sha256 `853d8bc6…` | temp folder removed |
| A5 | A-1 | `check_bridge_api.sh` on UE_5.5 | exit 1: `module CesiumRuntime FAIL` (not installed for 5.5 at the time), `module Marketplace`/`Plugins FAIL` (path strings parsed as modules), `show flag Grain FAIL` (pattern `(Grain,` never matches `(1, Grain,` on 5.5 or 5.7) | script defects, packet to follow |
| C1 | A-1 | `pytest -v tests/test_airframe.py -k components` | `6 passed` (dots only in that log; test name proved in `runs/p3/G/C1-audit.log`) | corrected |
| C5 | A-1 | `pytest -q tests/test_component_labels.py` | exit 0, 11 tests | |
| C6 | A-1 | `pytest -q -k component` | exit 0 | mutant half: the Mac auditor's mutation subset (state/A.json) |

## Letter A, run A-2 (UE 5.7.4, decision 10)

| Box | Run | Check | Result | Note |
|---|---|---|---|---|
| A5 | A-2 | `vendor_ue_plugin.ps1` with `UE_ROOT` at UE_5.7 | exit 0, `targets UE 5.7`, dll sha256 `e7c302ec…`; diff only `library_win64_sha256` | 2026-11-04 |
| A2 | A-2 | `build_ue.ps1` on 5.7.4 (first run) | FAIL before compiling: UBT `Unable to load … BuildRules\MarketplaceRules.dll … An Application Control policy has blocked this file (0x800711C7)`, then the recompile found it locked; Code Integrity events 3077/3033 name the dll; Smart App Control is on (policy state 1) | machine, not code |
| C1 | A-2 | `pytest -v tests/test_airframe.py -k components` | `6 passed` (dots only in that log; test name proved in `runs/p3/G/C1-audit.log`) | corrected |
| C5 | A-2 | `pytest -q tests/test_component_labels.py` | exit 0, 11 tests | |
| C6 | A-2 | `pytest -q -k component`; COCO half `-k payload_and_gear_are_their_own_coco` | exit 0 (55 tests); `1 passed` | |
| A2 | A-2 | `build_ue.ps1` on 5.7.4, retry after clearing `%LOCALAPPDATA%\UnrealEngine\Intermediate\Build\BuildRules` | `Result: Succeeded`, 25 actions, zero `error C`, one C4996 warning (`ULandscapeSubsystem::BuildNanite` deprecated); `build_stamp.json` engine_version 5.7.4, source `770fa283…`; UBT limited itself to 1 parallel action (2.2 GB free) | 204 s |
| A3 | A-2 | `build_ue.ps1` with `UE_ROOT` at UE_5.5 | exit 1, `engine.version_mismatch: found 5.5.4, pinned 5.7`, UBT not started | |
| A3 | A-2 | `ue_preflight.ps1` at UE_5.5 / at UE_5.7 | exit 1 `engine.version_mismatch: found 5.5.4, pinned 5.7` / exit 0 `engine UE 5.7.4 at C:\Program Files\Epic Games\UE_5.7` | |
| A4 | A-2 | PowerShell `Get-PluginSourceHash` on the fixture and the repo | fixture `0141215e…` equals golden; repo `770fa283…` equals the stamp and the Python twin | |
| A2 | A-2 | `pytest -q tests/test_platform.py` | exit 0 | |
| A5 | A-2 | `check_bridge_api.sh` with `UE_ROOT` at UE_5.7 | exit 0, `API surface matches` (CesiumRuntime module found in the 5.7 Marketplace folder) | |
| A5 | A-2 | `run_ue_scenario.ps1` c172p parity card on 5.7 | FAIL (machine): commandlet exit 1, no telemetry; `Failed to load … UnrealEditor-CesiumRuntime.dll (GetLastError=4551)`, Code Integrity 3077/3033, dll NotSigned; Smart App Control blocks it | blocks every editor run; owner's call |
| A5 | A-2 | `run_ue_scenario.ps1` c172p card on 5.7, Smart App Control off | flight written (600 samples, hold within 0.03 m) but process exit 1: `Failure - 1 error(s)` from `Collision Profile settings do not include an entry for the Water Body Collision profile` (Cesium 2.30.0 depends on the Water plugin) | packet A5-2 cause 1 |
| A5 | A-2 | `gate5_ue_parity.compare` headless vs UE | `PARITY FAIL`, roll max diff 50.64 deg, heading 180: headless trims longitudinal (aileron 0), UE trims full (aileron 0.497 deg) | packet A5-2 cause 2, decision 11 |
| A4 | A-2 | edit `FlightSimSky.cpp`, no rebuild, `POST /run` (web) | HTTP 409 `engine.binary_stale`, both hashes named; reverted: 200, run 4be692c3e9fe done | |
| A8 | A-2 | web `POST /run` Grand Canyon A-4, host flight on | run 4be692c3e9fe `done`; host-flight commandlet `Failure - 1 error(s)` (Water profile) but telemetry read; `verification FAILED: host_determinism, mask_vs_geometry`; the two host flights differ only in `agl_m` (38/220, max 27.6 m) | packet A8-1, decision 12 |
| A8 | A-2 | CLI `capture --render --terrain grand_canyon` of the same card | exit 2 `REFUSED camera.scene_bounds: 380 of 1155 solved poses fall outside the scene raster` (before the host flight) | CLI placement differs from the web path; Mac |
| A5 | A-2 | Windows builder 2b746352: `WaterBodyCollision` profile + still-air tLongitudinal re-trim; `run_ue_scenario.ps1` c172p card | exit 0, engine log `Success - 0 error(s), 4 warning(s)`; t=0 controls identical on both hosts | merged b7053df7 |
| A5 | A-2 | `gate5_ue_parity.compare` after the fixes | `PARITY FAIL` (altitude 40.73 m, heading 46.48 deg) from the 4.875 s clock-origin shift between recorders; origin-aligned residuals: altitude 0.0015 m, heading 0.0010 deg | packet A5-3, decision 14 (Mac) |
| A2 | A-2 | hand-edit `FlightSim.Target.cs` to Unreal5_5, `pytest -q tests/test_platform.py` | exit 1, `ue\Source\FlightSim.Target.cs does not pin EngineIncludeOrderVersion.Unreal5_7` | reverted |
| A2 | A-2 | step 10: cloud material + landscape paths once (web run 4be692c3e9fe render.log) | 0 `REFUSED` lines; cloud `m_SimpleVolumetricCloud_Inst ... used`; collision raster AGL check 1340.2 m; 220 frames | |
| A6 | A-2 | `ue_create_materials.py` unattended, run 1 | exit 0, `Success - 0 error(s)`; M_GreyCard, M_LandcoverID, M_RainStreaks, M_Ground_City, M_LensDrops: STALE, REBUILT, CREATED; `Missing If` 0 | editor log is the record (`-stdout` drops LogPython) |
| A6 | A-2 | run 2 | exit 0; the five + M_CustomStencilID `MATERIAL-EXISTS`; `Missing If` 0; but `M_RainDrops` and `M_RainSplash` REBUILT+CREATED again (storm generation stamp not seen) | packet A6-1 |
| A9 | A-2 | web `POST /run` two cameras (chase + tower), Grand Canyon A-4 20 s | run 473b9e1ecfff done; 200 frames in `frames/chase`, 200 in `frames/tower`; no `render.camera_empty`; verifier: host_determinism (A8), mask_vs_geometry + tight_box_present (A12) FAIL | |
| A5 | A-2 | `gate5_ue_parity.py` end to end on Windows (d4fd0dfd harness, 2b746352 build): telemetry + roll-doublet render | exit 0, `GATE 5: PASS -- all three clauses, each measured`; altitude 0.072 m, heading 0.082 deg; surfaces articulate; roll visible r=0.998 | PASS |
| A6 | A-2 | after 79939f51 (storm set-aside by copy): run 3 and run 4 on MAIN | run 3 REBUILT/CREATED only M_RainDrops, M_RainSplash (re-stamped once); run 4 `MATERIAL-EXISTS` x36, zero STALE/REBUILT/CREATED, `Missing If` 0, exit 0 | PASS |
| A8 | A-2 | web `POST /run` host flight on, after 3dc6a5ec (ground callback on the raster) | run 7274c62756ea done; `host_determinism` PASS (byte-identical 6bc9dcc5e613); 0 columns differ between passes; `ground: collision raster`; no `no-host-flight` text | PASS |
| A8 | A-2 | `pytest -q tests/test_host_parity.py` | 19 passed, 1 failed: `test_preflight_on_mac_runs_ue_preflight_sh` asserts a forward-slash path on Windows | Mac test defect, noted |
| A12 | A-2 | web one-frame 320x180 runs, A-4 (542c05cd9ddc) and c172p (2d70734a8ec4); `flightsim.verify`; `label_diagnose.py` | 6 of 7 gates PASS, `mask_vs_geometry` FAIL on both (mask box 3.5-3.6 px left of the projected hull, 1.1 % of the width, same as 13.7 px at 1280); `tight_box_present` PASS; `tight null: 0` | packet A12-1 |
| A11 | A-2 | CLI `capture --render --terrain runs/terrain/grand_canyon` (two cameras, three stills) | host flight ok; render commandlet exit 1 `cannot read heightfield sidecar runs/terrain/grand_canyon.json` (relative path handed to the engine); `REFUSED camera.render` | CLI path defect (Mac); retry with an absolute path |

## Letter B, run B-1 (UE 5.7.4, push 3e59358d)

| Box | Run | Check | Result | Note |
|---|---|---|---|---|
| B3 | B-1 | `pytest -q tests/test_toolchain_pins.py` | 7 passed, exit 0 | |
| B2 | B-1 | `ue_preflight.ps1` toolchain section on the 5.7 laptop | 6 `OK <tool> <version>` lines (engine 5.7.4 CL 51494982, msvc, windows_sdk, cesium_for_unreal 2.30.0, ffmpeg 9.0.2, python 3.12.10); `toolchain.jsbsim_mismatch: not found, pinned 1.2.4`; exit 1 | jsbsim reader |
| B2 | B-1 | ffmpeg pinned 9.0.1 / windows_sdk pinned 10.0.22621.0 | `toolchain.ffmpeg_mismatch: found 9.0.2, pinned 9.0.1` exit 1 / `toolchain.windows_sdk_mismatch: found 10.0.26100.0, pinned 10.0.22621.0` exit 1; toolchain.json restored | |
| B4 | B-1 | `gate6_visual.py --out runs/gate6 --skip-render --probe-out` on the 2026-10-06 5.7.4 probe renders | probe written (`runs/p3/A-2/B4-probe-existing.json`, 16 runs, bias 11, engine 5.7.4 CL 51494982); gate6 on those renders: `aircraft has a ground shadow` FAIL (0 px, threshold 300), `exposure metric discriminates` FAIL (1.92/255, needs > 16); the rest ok | old renders do not pass unchanged; steps 5-9 need fresh renders |
| B1 | B-1 | fresh Python 3.12.10 venv, `pip install --require-hashes -r requirements.lock`; installer verify import; `pytest -q tests/test_toolchain_pins.py tests/test_platform.py` | pip exit 0 (`Successfully installed ...`); `imports ok; jsbsim 1.2.4`; 21 passed, exit 0 (with `FLIGHTSIM_GOOGLE_TILES` unset; set `=on` by the user env it flips one platform test to `terrain.unbaked`, as in A2 run A-1) | step 9 installer and step 10 CI pending |
| A7 | A-2 | delete `ue/Content/Aircraft/A4`, Generate (run 7bbda8c5a4c3) | `aircraft: the A4 model is not on this machine yet or is out of date; building it once (fetch at the pinned commit, convert, import)`, `importing 1 aircraft into the Unreal project`, `the A4 model is ready`; asset folder recreated; the render then crashed (memory, machine note) | import half |
| A7 | A-2 | Generate again on the imported asset, quiet machine (run 57db7c98102f) | no re-import; host flight 220 samples; 220 frames rendered; labels 220 of 220; `done: clip ready` | render half |
| B1 | B-1 | `deploy_windows.ps1 -NoLaunch -InstallDir <scratch> -Branch phase-2-final` | clone cut by `curl 56 Recv failure`, then `Could not open requirements file`, `ModuleNotFoundError: jsbsim`, yet exit 0 | packet B1-1 (installer must fail by stage); retry running |
| B2 | B-1 | after 0dd863f9: `ue_preflight.ps1` on MAIN; ffmpeg 9.0.1 / windows_sdk 10.0.22621.0 pins | 7 `OK <tool> <version>` lines, `Preflight OK`, exit 0; `toolchain.ffmpeg_mismatch: found 9.0.2, pinned 9.0.1` exit 1; `toolchain.windows_sdk_mismatch: found 10.0.26100.0, pinned 10.0.22621.0` exit 1 | PASS |
| B1 | B-1 | step 10, CI matrix on the lock install | `CI: pending draft PR` (ci.yml runs on master pushes and pull_request only; the Mac is opening a draft PR from phase-2-final and will report the three jobs) | no PR subscription from this session |
| B1 | B-1 | `deploy_windows.ps1 -NoLaunch` retry into a second scratch dir | clone at e35545c3, venv, hashed lock installed, `verifying the physics and server imports` passed, exit 0; the deployed venv imports jsbsim 1.2.4 | step 9 positive half |
| A7 | A-2 | touch `assets/aircraft_config/A4.json`, Generate (run 9bf1e3e387a9, build 3b05ec5a) | `the A4 mesh manifest is stale (older than A4.json); re-converting`, `converting (license-verified, FDM-matched)`, `the A4 model is ready`; one re-convert, no import loop; 220 frames; labels 220/220; only `landmark_reprojection` FAIL (Mac A12 follow-up) | PASS |
| B1 | B-1 | after cfa48660: `deploy_windows.ps1 -Branch no-such-branch-b1` | `install.clone_failed: git exited 128 -- the clone ... did not complete`, exit 1, no install dir | PASS (step 10 CI pending draft PR) |
| A11 | A-2 | CLI `capture --render --terrain C:/.../grand_canyon` two cameras three stills (retry, absolute path) | exit 0; `labels: engine bundle attached on 6 of 6 frames (12 object records; 0 without a bundle)`; every frame record has mask, depth_f32, alone PNG on both cameras; same on the web run 843e5dbe9dcd | PASS |
| A12 | A-2 | run 7237db488652 on MAIN (build 3b05ec5a, grid convergence fix): `flightsim.verify`, `label_diagnose.py`, fixture | seven gates PASS (`mask_vs_geometry` 0.6 px of 130), `tight_box_present` PASS, `tight null: 0`; fixture `tests/fixtures/engine_bundle_min` 807,894 bytes committed; only `landmark_reprojection` FAIL (3.28 px: verifier ignores `camera_grid_convergence_deg`) | packet A12-2, Mac |
| A10 | A-2 | `POST /generate/plan` then `/generate/start` one-line prompt (12 images, 20 s) | plan 200 ok; campaign 56e6d0854f88 `failed`: `campaign.target_unreachable: 2 round(s) added no verified frame: 1 failed capture(s)`; the capture: `REFUSED [google_tiles.terrain] ... the physics ground is the flat slab`; llm tier fell back to regex (`unknown field cameras`) | packet A10-1, decision 17 (Mac) |
| A12 | A-2 | after 968dcb60 (verifier applies the convergence): `flightsim.verify` on 7237db488652; golden fixture test | exit 0: seven gates PASS, `tight_box_present` PASS, `landmark_reprojection` PASS (0.00 px); `pytest -q tests/test_engine_bundle_golden.py` exit 0, no skips | PASS |
| B4 | B-1 | `gate6_visual.py --probe-sweep gate6|noon|dawn` (15 renders, 960x540 measure) then `--rederive <look>` | all 15 probes written (`runs/b4_probe/<look>/<bias>/probe.json`, engine 5.7.4 CL 51494982); gate6 look: `chosen 11: terrain band 116.33/255 against the stated 118/255 (tolerance 4)` (unchanged, B4-2); noon and dawn: `REFUSED gate6.rederive_out_of_tolerance` (nearest noon bias 10 at 106.2, dawn bias 11.5 at 130; the 0.5-bias steps straddle the target) | finer sweeps around the nearest values follow |

## Letter C, run C-1 (push 845f014d)

| Box | Run | Check | Result | Note |
|---|---|---|---|---|
| C2 | C-1 | `pytest -q tests/test_a4_mesh.py` | exit 0 | |
| C3 | C-1 | `pytest -q tests/test_card_components.py` | exit 0 () | |
| A10 | A-2 | retry on 9bb12d95: `/generate/start` one-line prompt, tier llm | campaign c533669e2c7e `failed`: capture `REFUSED [camera.scene_bounds] 608 of 1155 solved poses fall outside the scene raster`; llm tier fell back (`camera 0 field moves`) | packet A10-2 (Mac) |
| B4 | B-1 | `gate6_visual.py --look` (measure) and `--quality beauty --look` | both `GATE 6: FAIL`, exit 1: range extinction ratio 1.12 (thr 0.75), peaks shadow 210 px (thr 10000), ground shadow 143 px (thr 300), exposure metric 4.52 (needs > 16), look clauses FAIL; the terrain is not drawn today (`B4-compare.png`) though the card, settings and RHI equal the 6 Oct run | packet B4-1 (Windows builder) |
| B1 | B-1 | step 10 / gate rows: CI matrix | `CI: blocked by Actions billing` (GitHub: "The job was not started because recent account payments have failed or your spending limit needs to be increased"), runs 41885321776-41911496059 zero steps | owner |
| B4 | B-1 | after 4f8abb78 (tiles decline on the synthetic raster): `gate6_visual.py --look` measure and beauty in the builder worktree | terrain clauses ok (extinction ratio 0.21, peaks shadow 17874 px); five clauses FAIL as on the 6 Oct renders: ground shadow 0 px, auto-exposure control 2.51/255, wetness parameter absent, albedo sun invariance 99.6 %, old footage folder absent; `GATE 6: FAIL` | packet B4-2 (Windows round 2) |

## Letter D

Rows written by the Windows runner for D6 (the {A4, J11} x {desert, forest}
matrix: `python scripts/run_test_scenarios.py --matrix --still --compiler regex`,
summary in `runs/phase3_matrix.json`); one row per cell with the run id, the
verify counts, the `component_coverage` detail and the card diff keys.

| box | run | check | result | note |
|---|---|---|---|---|
| A12 | A-2 | retry 3 (2163a0d5): `pytest -q tests/test_engine_bundle_golden.py` | exit 0, no skips | PASS stands |
| A10 | A-2 | retry 2 (8a9bda0e): `/generate/start` one-line prompt, one campaign | 348abcf4ddce `failed`: both cases render (22 frames, labels 22/22, no refusal) but verify FAIL on `host_determinism` (CLI route), `component_boxes` (mirrored OBJ), `label_geometry_3d` (recount); llm fell back on `unknown field notes` | packet A10-3 (Mac; waits on C4-1 items) |
| C4 | C-1 | re-prove on 1e802859: one A-4 still through the CLI (A7 re-convert) | `host_determinism` PASS (byte-identical), `label_geometry_3d` PASS, `component_coverage` PASS; `component_boxes` FAIL with the same numbers: the re-convert (OBJs + manifest 17:02, obj_frame stamped) was not followed by a re-import (uassets 14:06) | packet C4-2 (Mac importer) |
| C4 | C-1 | re-prove 2 on e6e33c6e+30945bf5: A7 re-imported body + stores (uassets 17:09), one A-4 still | mask ids 64/65/66 (21/8/22 px), aircraft 462 px tight box filled; `component_boxes` PASS, `component_coverage` PASS, `label_geometry_3d` PASS, `host_determinism` PASS; verify exit 0 | PASS |
| C7 | C-1 | step 6 (gear-down c172p render) | deferred: budget (owner rule; C4 renders, decision 16 condition met) | |
| B4 | B-1 | round 2 (215813cd merged; MAIN stamp e952c275; M_VertexColor rebuilt with Wetness): `gate6_visual.py --look` measure and beauty in the builder worktree | wet surface PASS (22443 px); ground shadow 79 px (thr 300); auto-exposure control 4.62/255; albedo unfixed (file claimed); range extinction 1.07, extinction-follows-visibility 0.09 and night ground 1.87/255 now FAIL on the lit ground; `GATE 6: FAIL` | packet B4-3; round 3 deferred: budget |
