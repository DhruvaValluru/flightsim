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
| C1 | A-1 | `pytest -v tests/test_airframe.py -k components` | `6 passed`, incl. `test_components_loadout_trims` | |
| C5 | A-1 | `pytest -q tests/test_component_labels.py` | exit 0, 11 tests | |
| C6 | A-1 | `pytest -q -k component` | exit 0 | mutant half: the Mac auditor's mutation subset (state/A.json) |

## Letter A, run A-2 (UE 5.7.4, decision 10)

| Box | Run | Check | Result | Note |
|---|---|---|---|---|
| A5 | A-2 | `vendor_ue_plugin.ps1` with `UE_ROOT` at UE_5.7 | exit 0, `targets UE 5.7`, dll sha256 `e7c302ec…`; diff only `library_win64_sha256` | 2026-11-04 |
| A2 | A-2 | `build_ue.ps1` on 5.7.4 (first run) | FAIL before compiling: UBT `Unable to load … BuildRules\MarketplaceRules.dll … An Application Control policy has blocked this file (0x800711C7)`, then the recompile found it locked; Code Integrity events 3077/3033 name the dll; Smart App Control is on (policy state 1) | machine, not code |
| C1 | A-2 | `pytest -v tests/test_airframe.py -k components` | `6 passed` incl. `test_components_loadout_trims` | |
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
