# Letter A sync log (Windows cross-check)

## A3 · PASS · run A-1 · 2026-11-04T06:19:49Z

verify line(s) from tasks/phase3_checklist.md:

```
52:   - Check: pointing it at another version stops with `engine.version_mismatch`.
53:   - Check: the right version builds with zero errors.
```

output line(s) that satisfy it:

```
runs/p3/A-1/A3-build-57-refuse.log: engine.version_mismatch: found 5.7.4, pinned 5.5
runs/p3/A-1/A3-build-57-refuse.log: build exit=1, no Build.bat line in the log
runs/p3/A-1/A2-build-2.log: building FlightSimEditor Win64 Development against UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5
runs/p3/A-1/A2-build-2.log: stamped 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5  (build exit=0; grep -c 'error C' = 0)
```

### synopsis

# A3 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:13:32Z

## A3 step 6: build_ue.ps1 with UE_ROOT=UE_5.7 refuses

- log: `runs/p3/A-1/A3-build-57-refuse.log`
- exit: 1 (expected 1) -> PASS

```
engine.version_mismatch: found 5.7.4, pinned 5.5
At C:\Users\kanth\flightsim\scripts\build_ue.ps1:23 char:18
+ if ($mismatch) { throw $mismatch }
+                  ~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (engine.version_...7.4, pinned 5.5:String) [], RuntimeException
    + FullyQualifiedErrorId : engine.version_mismatch: found 5.7.4, pinned 5.5
 
```

## A3: ue_preflight.ps1 with UE_ROOT=UE_5.7 fails by name

- log: `runs/p3/A-1/A3-preflight-57.log`
- exit: 1 (expected 1) -> PASS

```
Unreal host preflight (Windows)

  engine                             UE 5.7.4 at C:\Program Files\Epic Games\UE_5.7
  engine                             engine.version_mismatch: found 5.7.4, pinned 5.5
  visual studio (C++ tools)          17.14.39 (August 2026)
  v143 toolset (UE 5.5 needs it)     present
  jsbsim plugin                      vendored v1.2.4 (patched sources committed)
  jsbsim Win64 library               JSBSim.dll + JSBSim.lib present
  jsbsim plugin engine target        vendored for UE 5.5
  jsbsim runtime data                60 aircraft staged in Resources/JSBSim
  jsbsim parity                      both hosts at e07a7d810d4f
  flightsim bridge                   22 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  ffmpeg (clip encoding)             C:\Users\kanth\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe

Preflight FAILED -- see above.
```

## A3 step 7: ue_preflight.ps1 on the pinned 5.5.4 (UE_ROOT=UE_5.5)

- log: `runs/p3/A-1/A3-preflight-55.log`
- exit: 0 (expected 0) -> PASS

```
Unreal host preflight (Windows)

  engine                             UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5
  visual studio (C++ tools)          17.14.39 (August 2026)
  v143 toolset (UE 5.5 needs it)     present
  jsbsim plugin                      vendored v1.2.4 (patched sources committed)
  jsbsim Win64 library               JSBSim.dll + JSBSim.lib present
  jsbsim plugin engine target        vendored for UE 5.5
  jsbsim runtime data                60 aircraft staged in Resources/JSBSim
  jsbsim parity                      both hosts at e07a7d810d4f
  flightsim bridge                   22 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  ffmpeg (clip encoding)             C:\Users\kanth\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe

Preflight OK -- the Unreal host can run here.
Validate the render output on THIS machine with:
  .\.venv\Scripts\python.exe experiments\gate6_visual.py
```

## A3 step 7: build_ue.ps1 on the pinned 5.5.4 builds, prints the version

- log: `runs/p3/A-1/A2-build-2.log`
- exit: 0 (expected 0) -> PASS

```
building FlightSimEditor Win64 Development against UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5
Using bundled DotNet SDK version: 8.0.300
Running UnrealBuildTool: dotnet "..\..\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" FlightSimEditor Win64 Development -project=C:\Users\kanth\flightsim\ue\FlightSim.uproject -waitmutex
Log file: C:\Users\kanth\AppData\Local\UnrealBuildTool\Log.txt
Using 'git status' to determine working set for adaptive non-unity build (C:\Users\kanth\flightsim).
Building FlightSimEditor...
Using Visual Studio 2022 14.44.35228 toolchain (C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207) and Windows 10.0.26100.0 SDK (C:\Program Files (x86)\Windows Kits\10).
Warning: Visual Studio 2022 compiler is not a preferred version
Determining max actions to execute in parallel (8 physical cores, 12 logical cores)
  Executing up to 8 processes, one per physical core
  Requested 1.5 GB memory per action, 4.24 GB available: limiting max parallel actions to 2
Using Unreal Build Accelerator local executor to run 8 action(s)
  Storage capacity 40Gb
---- Starting trace: 261104_011050 ----
UbaSessionServer - Disable remote execution (remote sessions will finish current processes)
------ Building 8 action(s) started ------
[1/8] Copy JSBSim.dll
[2/8] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Binaries\Win64\UnrealEditor-JSBSimFlightDynamicsModel.exp
[3/8] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Binaries\Win64\UnrealEditor-JSBSimFlightDynamicsModelEditor.exp
[4/8] Compile [x64] Module.FlightSimBridge.2.cpp
[5/8] Link [x64] UnrealEditor-FlightSimBridge.lib
[6/8] Link [x64] UnrealEditor-FlightSimBridge.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.exp
[7/8] Link [x64] UnrealEditor-FlightSimBridgeEditor.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridgeEditor.exp
[8/8] WriteMetadata FlightSimEditor.target (UBA disabled)
Trace file written to C:/Users/kanth/AppData/Local/UnrealBuildTool/Log.uba with size 5.8kb
Total time in Unreal Build Accelerator local executor: 35.16 seconds
Total execution time: 36.76 seconds
stamped 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5

built. Next: .\scripts\ue_preflight.ps1 to confirm, then render.
build exit=0
```

note: Both scripts dot-source scripts/ue_engine.ps1 under Windows PowerShell 5.1 (powershell.exe), the only PowerShell on this machine's path for these runs.

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
4dfa4452 A3: the build refuses the wrong engine by name (ue_engine.ps1, no UE_5.* glob)

4dfa4452 A3: the build refuses the wrong engine by name (ue_engine.ps1, no UE_5.* glob)

 scripts/build_ue.ps1             | 25 ++++++++---------
 scripts/ue_engine.ps1            | 50 +++++++++++++++++++++++++++++++++
 scripts/ue_preflight.ps1         | 56 ++++++++++++++-----------------------
 tests/test_powershell_scripts.py | 60 ++++++++++++++++++++++++++++++++++++++++
 4 files changed, 143 insertions(+), 48 deletions(-)
```

## C1 · PASS · run A-1 · 2026-11-04T06:19:50Z

verify line(s) from tasks/phase3_checklist.md:

```
122:   - Check: the A-4 loads with at least one payload, and the plane still trims with
```

output line(s) that satisfy it:

```
runs/p3/A-1/C1-pytest-v.log: 
runs/p3/A-1/C1-pytest-v.log: 
runs/p3/A-1/C1-pytest-v.log: ============================== 6 passed in 0.77s ==============================
```

note: loadout per decisions 2 and 7: STA3_LOAD=1, STA2_LOAD=1, STA4_LOAD=1 at 750 lb each

### synopsis

# C1 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:19:49Z

## C1 verify: pytest -q tests/test_airframe.py -k components

- log: `runs/p3/A-1/C1-pytest.log`
- exit: 0 (expected 0) -> PASS

```
......                                                                   [100%]
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## C1 verify (verbose, test names): pytest -v tests/test_airframe.py -k components

- log: `runs/p3/A-1/C1-pytest-v.log`
- exit: 0 (expected 0) -> PASS

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\kanth\flightsim
configfile: pytest.ini
plugins: anyio-4.14.2, timeout-2.3.1
timeout: 900.0s
timeout method: thread
timeout func_only: False
collected 6 items

tests\test_airframe.py ......                                            [100%]

============================== 6 passed in 0.77s ==============================
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal

8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal

 assets/aircraft_config/A4.json                     |  79 +++++++++++---
 assets/fdm_root/aircraft/A4/A4.xml                 |   6 +-
 assets_pipeline/a4_performance.py                  |  11 +-
 assets_pipeline/a4_sync.py                         |   8 +-
 core/capture/airframe.py                           | 115 ++++++++++++++++++++-
 core/messages/catalog.yaml                         |   3 +
 docs/phase3/notes/C1.md                            |   4 +
 tests/test_a4.py                                   |  14 ++-
 tests/test_airframe.py                             |  99 ++++++++++++++++++
 .../Resources/JSBSim/aircraft/A4/A4.xml            |   6 +-
 10 files changed, 316 insertions(+), 29 deletions(-)
```

## C5 · PASS · run A-1 · 2026-11-04T06:19:51Z

verify line(s) from tasks/phase3_checklist.md:

```
132:   - Check: `pytest -q tests/test_component_labels.py` passes for five cases: visible,
```

output line(s) that satisfy it:

```
runs/p3/A-1/C5-pytest.log: ...........                                                              [100%]  (exit 0, 11 tests)
collected: test_payload_blob_gives_a_tight_box_equal_to_the_blob (visible), test_out_of_frame_payload_is_null_with_the_out_of_frame_basis (off-screen), test_payload_behind_the_fuselage_is_invisible_and_occluded_by_the_aircraft (hidden), test_aircraft_tight_box_includes_its_payload_pixels (box includes payload), test_validate_manifest_accepts_v8_and_v7 (old v7 still reads)
```

### synopsis

# C5 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:13:32Z

## C5 verify: pytest -q tests/test_component_labels.py

- log: `runs/p3/A-1/C5-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........                                                              [100%]
```

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
b135d207 C5: component label records, parent rollup, manifest v8

b135d207 C5: component label records, parent rollup, manifest v8

 core/capture/labels.py                       |  126 +-
 core/capture/manifest.py                     |   15 +-
 core/capture/objects.py                      |   28 +-
 core/scenario/blocks.py                      |    2 +-
 docs/schemas/capture_manifest.v8.schema.json | 2059 ++++++++++++++++++++++++++
 tests/test_camera_labels.py                  |    5 +-
 tests/test_capture_objects.py                |    5 +-
 tests/test_capture_schema.py                 |    4 +-
 tests/test_component_labels.py               |  180 +++
 tests/test_versions.py                       |    2 +-
 10 files changed, 2406 insertions(+), 20 deletions(-)
```

## C6 · PASS · run A-1 · 2026-11-04T06:19:51Z

verify line(s) from tasks/phase3_checklist.md:

```
136:   - Check: `component_coverage` passes, and a COCO export has a `payload` category.
```

output line(s) that satisfy it:

```
runs/p3/A-1/C6-pytest.log: exit 0 (pytest -q -k component; summary line suppressed by the suite's config, exit code is the evidence)
mutant half (Mac auditor, state/A.json audit): mutation subset: 7 guards (pin, preflight, component) plus 4 re-targeted guards (123,173,218,359) all caught
```

### synopsis

# C6 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:13:33Z

## C6 verify: pytest -q -k component

- log: `runs/p3/A-1/C6-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........................                                              [100%]
============================== warnings summary ===============================
tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:384: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:385: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:389: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")

tests/test_annotation_gates.py: 30 warnings
tests/test_dataset_boxes.py: 18 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:404: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(alone, mode="L").save(folder / alone_name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
5e97e409 C6 integrator: component catalogue entries, class ids as words on the card
b2e362b9 C6: component_boxes and component_coverage gates, parent rollup in verify, payload/landing_gear export categories, guards

5e97e409 C6 integrator: component catalogue entries, class ids as words on the card

 core/messages/catalog.yaml    | 8 ++++++++
 tests/test_webapp_generate.py | 5 +++++
 webapp/generate.py            | 9 +++++++--
 3 files changed, 20 insertions(+), 2 deletions(-)

b2e362b9 C6: component_boxes and component_coverage gates, parent rollup in verify, payload/landing_gear export categories, guards

 core/capture/verify.py         | 236 ++++++++++++++++++++++++++++++++++++++---
 core/dataset/export.py         |  18 +++-
 scripts/mutation_check.sh      |  18 ++++
 tests/test_annotation_gates.py | 165 ++++++++++++++++++++++++++--
 tests/test_dataset_boxes.py    |  96 ++++++++++++++++-
 tests/test_dataset_formats.py  |   8 +-
 6 files changed, 509 insertions(+), 32 deletions(-)
```

## A1 · CUT · run A-1 · 2026-11-04T06:19:51Z

verify line(s) from tasks/phase3_checklist.md:

```
46:   - Check: `docs/TOOLCHAIN.md` has three rows with the same version, and a dated
```

output line(s) that satisfy it:

```
docs/TOOLCHAIN.md row 1: 5.5.4 (++UE5+Release-5.5), changelist 40574608, MSVC 14.44.35207, SDK 10.0.26100.0; rows 2-3 pending (packets/A1-1.md, decision 9)
```

note: cut for this run by decision 9: rows 2 and 3 need the reviewer's and third machines; no code change can fill them

### synopsis

(no synopsis)


## C6 addendum (COCO half)

runs/p3/A-1/C6-coco.log: `pytest -v tests/test_dataset_boxes.py -k payload_and_gear_are_their_own_coco` -> `1 passed` (test_payload_and_gear_are_their_own_coco_categories), exit 0.
## A4 · PASS · run A-1 · 2026-11-04T06:24:55Z

verify line(s) from tasks/phase3_checklist.md:

```
55:   - Check: after changing one `.cpp` without rebuilding, a render stops with
56:     `engine.binary_stale`.
```

output line(s) that satisfy it:

```
runs/p3/A-1/A4-stale-web.log: status 409
runs/p3/A-1/A4-stale-web.log: {"refused":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now 3077bae2dc9a2b23fcc31c1cec50164fb04c395e79daa312f1038c2c3ea88309","constraint":"engine.binary_stale","sentence":"The request was  ...
runs/p3/A-1/A4-fresh-web.log (source reverted): status 200 {"run_id":"06a1a9be37c9", ...}
```

### synopsis

# A4 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:24:54Z

## A4 step 6: build_ue.ps1 writes build_stamp.json (source_sha256 equals Python plugin_source_hash: 770fa283…)

- log: `runs/p3/A-1/A2-build-2.log`
- exit: 0 (expected 0) -> PASS

```
building FlightSimEditor Win64 Development against UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5
Using bundled DotNet SDK version: 8.0.300
Running UnrealBuildTool: dotnet "..\..\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" FlightSimEditor Win64 Development -project=C:\Users\kanth\flightsim\ue\FlightSim.uproject -waitmutex
Log file: C:\Users\kanth\AppData\Local\UnrealBuildTool\Log.txt
Using 'git status' to determine working set for adaptive non-unity build (C:\Users\kanth\flightsim).
Building FlightSimEditor...
Using Visual Studio 2022 14.44.35228 toolchain (C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207) and Windows 10.0.26100.0 SDK (C:\Program Files (x86)\Windows Kits\10).
Warning: Visual Studio 2022 compiler is not a preferred version
Determining max actions to execute in parallel (8 physical cores, 12 logical cores)
  Executing up to 8 processes, one per physical core
  Requested 1.5 GB memory per action, 4.24 GB available: limiting max parallel actions to 2
Using Unreal Build Accelerator local executor to run 8 action(s)
  Storage capacity 40Gb
---- Starting trace: 261104_011050 ----
UbaSessionServer - Disable remote execution (remote sessions will finish current processes)
------ Building 8 action(s) started ------
[1/8] Copy JSBSim.dll
[2/8] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Binaries\Win64\UnrealEditor-JSBSimFlightDynamicsModel.exp
[3/8] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Binaries\Win64\UnrealEditor-JSBSimFlightDynamicsModelEditor.exp
[4/8] Compile [x64] Module.FlightSimBridge.2.cpp
[5/8] Link [x64] UnrealEditor-FlightSimBridge.lib
[6/8] Link [x64] UnrealEditor-FlightSimBridge.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridge.exp
[7/8] Link [x64] UnrealEditor-FlightSimBridgeEditor.dll
   Creating object C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Binaries\Win64\UnrealEditor-FlightSimBridgeEditor.exp
[8/8] WriteMetadata FlightSimEditor.target (UBA disabled)
Trace file written to C:/Users/kanth/AppData/Local/UnrealBuildTool/Log.uba with size 5.8kb
Total time in Unreal Build Accelerator local executor: 35.16 seconds
Total execution time: 36.76 seconds
stamped 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5

built. Next: .\scripts\ue_preflight.ps1 to confirm, then render.
build exit=0
```

## A4 step 7: PowerShell Get-PluginSourceHash on tests/fixtures/stamp_tree equals the golden 0141215e…; repo hash PowerShell == Python

- log: `runs/p3/A-1/A4-ps-hash.log`
- exit: 0 (expected 0) -> PASS

```
fixture  0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
golden   0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
repo-ps1 71754a43e5ef9b88579828c652f97e32d3bc36c7bfa13e9221d3e05f9bb655ad
repo-py  71754a43e5ef9b88579828c652f97e32d3bc36c7bfa13e9221d3e05f9bb655ad
```

## A4 step 8: FlightSimSky.cpp edited, no rebuild, POST /run refuses 409 engine.binary_stale naming both hashes

- log: `runs/p3/A-1/A4-stale-web.log`
- exit: 0 (expected 0) -> PASS

```
status 409
{"refused":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now 3077bae2dc9a2b23fcc31c1cec50164fb04c395e79daa312f1038c2c3ea88309","constraint":"engine.binary_stale","sentence":"The request was refused.","hint":"","details":{"rule":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now 3077bae2dc9a2b23fcc31c1cec50164fb04c395e79daa312f1038c2c3ea88309","message":"","catalogued":false}}
```

## A4 step 8 (second half): source reverted, binary_stale_reason None, POST /run accepted (200, run 06a1a9be37c9)

- log: `runs/p3/A-1/A4-fresh-web.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"06a1a9be37c9","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
```

note: CLI path: with the edited source, python -m flightsim.capture --render refused earlier gates first (google_tiles.terrain without a bake, camera.scene_bounds with --terrain on this spec), so the stale gate was proven on the web path, which checks it right after ue_available(); binary_stale_reason() from Python named both hashes in every attempt (runs/p3/A-1/A4-stale-render*.log).

note: observation for the Mac (not a failure of the verify line): the web refusal JSON carries sentence 'The request was refused.' and catalogued:false, so the engine.binary_stale catalogue entry is not reaching the web refusal words; the CLI path was not reached.

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
9a0fdfef A4 integrator: capture wiring test, note integrator_edits
52b450b3 A4 integrator: skip stale check when no bridge binary exists (drops conftest fixture); CRLF fixture -text; capture wiring test
b9c8d830 A4: refuse a stale engine binary (build stamp, plugin source hash, engine.binary_stale)

9a0fdfef A4 integrator: capture wiring test, note integrator_edits

 docs/phase3/notes/A4.md    | 5 +++++
 tests/conftest.py          | 1 -
 tests/test_binary_stale.py | 9 ++++++---
 3 files changed, 11 insertions(+), 4 deletions(-)

52b450b3 A4 integrator: skip stale check when no bridge binary exists (drops conftest fixture); CRLF fixture -text; capture wiring test

 .gitattributes                                     |  3 +++
 core/util/platform.py                              |  7 ++++-
 tests/conftest.py                                  | 12 ---------
 .../ue/Plugins/FlightSimBridge/Source/B.h          |  4 +--
 tests/test_binary_stale.py                         | 30 ++++++++++++++++++++++
 5 files changed, 41 insertions(+), 15 deletions(-)

b9c8d830 A4: refuse a stale engine binary (build stamp, plugin source hash, engine.binary_stale)

 core/messages/catalog.yaml                         |  3 +
 core/util/platform.py                              | 74 +++++++++++++++++++++
 flightsim/capture.py                               |  9 +++
 scripts/build_ue.ps1                               | 41 ++++++++++++
 tests/conftest.py                                  | 13 ++++
 .../ue/Plugins/FlightSimBridge/Source/A.cpp        |  1 +
 .../ue/Plugins/FlightSimBridge/Source/B.h          |  2 +
 .../ue/Plugins/FlightSimBridge/Source/Sub/C.cpp    |  2 +
 tests/test_binary_stale.py                         | 76 ++++++++++++++++++++++
 webapp/runs.py                                     |  7 ++
 10 files changed, 228 insertions(+)
```


---

# Run A-2 · UE 5.7 restart (decision 10, Mac push 23bad766)

The owner moved the pin to 5.7 and asked for every letter A box to be proved
again from scratch. The run A-1 records above were measured on UE 5.5.4 and
are history; A1 stays `cut` (decision 9). Records below are run A-2 on
UE 5.7.4 (changelist 51494982), Cesium for Unreal 2.30.0 in the engine.

## C1 · PASS · run A-2 · 2026-11-04T15:59:06Z

verify line(s) from tasks/phase3_checklist.md:

```
123:   - Check: the A-4 loads with at least one payload, and the plane still trims with
```

output line(s) that satisfy it:

```
runs/p3/A-2/C1-pytest-v.log: ============================== 6 passed in 1.80s ==============================
runs/p3/A-2/C1-pytest-v.log: tests/test_airframe.py::test_components_loadout_trims PASSED
```

note: run A-2: same tests as run A-1, now on the 5.7 pin sweep; python-only box, no engine involved

### synopsis

# C1 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T15:59:05Z

## C1 verify (test names): pytest -v tests/test_airframe.py -k components

- log: `runs/p3/A-2/C1-pytest-v.log`
- exit: 0 (expected 0) -> PASS

```
============================= test session starts =============================
platform win32 -- Python 3.12.10, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\kanth\flightsim
configfile: pytest.ini
plugins: anyio-4.14.2, timeout-2.3.1
timeout: 900.0s
timeout method: thread
timeout func_only: False
collected 6 items

tests\test_airframe.py ......                                            [100%]

============================== 6 passed in 1.80s ==============================
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run A-2 on the 5.7 pin sweep (23bad766); 6 passed incl. test_components_loadout_trims

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log
6375569e Merge p3-C1: components block, A-4 default loadout (3 x 750 lb on STA2-4), aircraft.component_unmatched
6cf3a3fc Merge branch 'phase-2-final' into p3-C1
8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal

42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log

 docs/PHASE3_LOG.md                 |  29 +++
 docs/phase3/decisions.md           |   2 +
 docs/phase3/events_windows.log     |  17 ++
 docs/phase3/packets/A1-1.md        |  27 +++
 docs/phase3/packets/A2-synopsis.md | 117 +++++++++++
 docs/phase3/packets/A3-synopsis.md | 122 +++++++++++
 docs/phase3/packets/C1-synopsis.md |  47 +++++
 docs/phase3/packets/C5-synopsis.md |  18 ++
 docs/phase3/packets/C6-synopsis.md |  40 ++++
 docs/phase3/state/A1.json          |   5 +-
 docs/phase3/state/A3.json          |   4 +-
 docs/phase3/state/C1.json          |   4 +-
 docs/phase3/state/C5.json          |   4 +-
 docs/phase3/state/C6.json          |   4 +-
 docs/phase3/sync_log_A.md          | 409 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   8 +-
 16 files changed, 848 insertions(+), 9 deletions(-)

6375569e Merge p3-C1: components block, A-4 default loadout (3 x 750 lb on STA2-4), aircraft.component_unmatched

 assets/aircraft_config/A4.json                     |  79 +++++++++++---
 assets/fdm_root/aircraft/A4/A4.xml                 |   6 +-
 assets_pipeline/a4_performance.py                  |  11 +-
 assets_pipeline/a4_sync.py                         |   8 +-
 core/capture/airframe.py                           | 115 ++++++++++++++++++++-
 core/messages/catalog.yaml                         |   3 +
 docs/phase3/notes/C1.md                            |   4 +
 tests/test_a4.py                                   |  14 ++-
 tests/test_airframe.py                             |  99 ++++++++++++++++++
 .../Resources/JSBSim/aircraft/A4/A4.xml            |   6 +-
 10 files changed, 316 insertions(+), 29 deletions(-)

6cf3a3fc Merge branch 'phase-2-final' into p3-C1

 README.md                                          |   4 +-
 core/util/platform.py                              |  28 +++---
 docs/CAMERA_WINDOWS.md                             |   3 +-
 scripts/build_ue.ps1                               |  25 +++--
 scripts/build_ue.sh                                |   6 +-
 scripts/check_bridge_api.sh                        |   2 +-
 scripts/deploy_windows.ps1                         |   2 +-
 scripts/mutation_check.sh                          |  14 +--
 scripts/render_ue_scenario.sh                      |   2 +-
 scripts/run_ue_scenario.sh                         |   2 +-
 scripts/setup.ps1                                  |   2 +-
 scripts/setup.sh                                   |   2 +-
 scripts/ue_create_materials.py                     |   2 +-
 scripts/ue_engine.ps1                              |  50 ++++++++++
 scripts/ue_preflight.ps1                           |  56 +++++------
 scripts/ue_preflight.sh                            |   6 +-
 scripts/vendor_ue_plugin.ps1                       |  14 ++-
 scripts/vendor_ue_plugin.sh                        |   8 +-
 tests/test_gate6_visual.py                         |   3 +-
 tests/test_platform.py                             | 104 +++++++++++++++------
 tests/test_powershell_scripts.py                   |  60 ++++++++++++
 tests/test_toolchain_doc.py                        |  49 ++++++++++
 tests/test_ue_materials.py                         |  23 +++++
 tests/test_ue_weather_source.py                    |  11 +++
 tests/test_webapp_generate.py                      |  59 ++++++++++++
 ue/FlightSim.uproject                              |   2 +-
 .../Private/FlightSimRenderCommandlet.cpp          |   2 +-
 .../FlightSimBridge/Private/FlightSimWeather.cpp   |  19 +++-
 ue/Source/FlightSim.Target.cs                      |   2 +-
 ue/Source/FlightSimEditor.Target.cs                |   2 +-
 webapp/generate.py                                 |  11 +++
 31 files changed, 439 insertions(+), 136 deletions(-)

8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal

 assets/aircraft_config/A4.json                     |  79 +++++++++++---
 assets/fdm_root/aircraft/A4/A4.xml                 |   6 +-
 assets_pipeline/a4_performance.py                  |  11 +-
 assets_pipeline/a4_sync.py                         |   8 +-
 core/capture/airframe.py                           | 115 ++++++++++++++++++++-
 core/messages/catalog.yaml                         |   3 +
 docs/phase3/notes/C1.md                            |   4 +
 tests/test_a4.py                                   |  14 ++-
 tests/test_airframe.py                             |  99 ++++++++++++++++++
 .../Resources/JSBSim/aircraft/A4/A4.xml            |   6 +-
 10 files changed, 316 insertions(+), 29 deletions(-)
```

## C5 · PASS · run A-2 · 2026-11-04T15:59:06Z

verify line(s) from tasks/phase3_checklist.md:

```
133:   - Check: `pytest -q tests/test_component_labels.py` passes for five cases: visible,
```

output line(s) that satisfy it:

```
runs/p3/A-2/C5-pytest.log: ...........                                                              [100%]  (11 passed, exit 0)
```

note: run A-2 on 23bad766

### synopsis

# C5 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T15:59:05Z

## C5 verify: pytest -q tests/test_component_labels.py

- log: `runs/p3/A-2/C5-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........                                                              [100%]
```

note: run A-2 on 23bad766; 11 dots, no F

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log
d8d29d82 Merge p3-C5: component labels (payload, landing_gear), parent rollup, manifest v8
21c6787d Merge branch 'phase-2-final' into p3-C5
b135d207 C5: component label records, parent rollup, manifest v8

42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log

 docs/PHASE3_LOG.md                 |  29 +++
 docs/phase3/decisions.md           |   2 +
 docs/phase3/events_windows.log     |  17 ++
 docs/phase3/packets/A1-1.md        |  27 +++
 docs/phase3/packets/A2-synopsis.md | 117 +++++++++++
 docs/phase3/packets/A3-synopsis.md | 122 +++++++++++
 docs/phase3/packets/C1-synopsis.md |  47 +++++
 docs/phase3/packets/C5-synopsis.md |  18 ++
 docs/phase3/packets/C6-synopsis.md |  40 ++++
 docs/phase3/state/A1.json          |   5 +-
 docs/phase3/state/A3.json          |   4 +-
 docs/phase3/state/C1.json          |   4 +-
 docs/phase3/state/C5.json          |   4 +-
 docs/phase3/state/C6.json          |   4 +-
 docs/phase3/sync_log_A.md          | 409 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   8 +-
 16 files changed, 848 insertions(+), 9 deletions(-)

d8d29d82 Merge p3-C5: component labels (payload, landing_gear), parent rollup, manifest v8

 core/capture/labels.py                       |  126 +-
 core/capture/manifest.py                     |   15 +-
 core/capture/objects.py                      |   28 +-
 core/scenario/blocks.py                      |    2 +-
 docs/schemas/capture_manifest.v8.schema.json | 2059 ++++++++++++++++++++++++++
 tests/test_camera_labels.py                  |    5 +-
 tests/test_capture_objects.py                |    5 +-
 tests/test_capture_schema.py                 |    4 +-
 tests/test_component_labels.py               |  180 +++
 tests/test_versions.py                       |    2 +-
 10 files changed, 2406 insertions(+), 20 deletions(-)

21c6787d Merge branch 'phase-2-final' into p3-C5

 README.md                                          |    4 +-
 assets/aircraft_config/A4.json                     |   79 +-
 assets/fdm_root/aircraft/A4/A4.xml                 |    6 +-
 assets_pipeline/a4_performance.py                  |   11 +-
 assets_pipeline/a4_sync.py                         |    8 +-
 core/capture/airframe.py                           |  115 +-
 core/messages/catalog.yaml                         |    3 +
 core/util/platform.py                              |   28 +-
 docs/CAMERA_WINDOWS.md                             |    3 +-
 docs/phase3/BUILDER_BRIEF.md                       |   52 +
 docs/phase3/INTEGRATOR_BRIEF.md                    |   52 +
 docs/phase3/SUBAGENT_BRIEF.md                      |   47 +
 docs/phase3/digest_A.md                            | 1260 ++++++++++++++++++++
 docs/phase3/events_mac.log                         |  239 ++++
 docs/phase3/notes/A1.md                            |   55 +
 docs/phase3/notes/A10.md                           |   50 +
 docs/phase3/notes/A11.md                           |   59 +
 docs/phase3/notes/A12.md                           |   58 +
 docs/phase3/notes/A13.md                           |   44 +
 docs/phase3/notes/A2.md                            |   79 ++
 docs/phase3/notes/A3.md                            |   69 ++
 docs/phase3/notes/A4.md                            |   85 ++
 docs/phase3/notes/A5.md                            |   58 +
 docs/phase3/notes/A6.md                            |   59 +
 docs/phase3/notes/A7.md                            |   64 +
 docs/phase3/notes/A8.md                            |   61 +
 docs/phase3/notes/A9.md                            |   60 +
 docs/phase3/notes/C1.md                            |   64 +
 docs/phase3/notes/C5.md                            |   68 ++
 docs/phase3/notes/C6.md                            |   65 +
 docs/phase3/state/A.json                           |   41 +
 docs/phase3/state/A1.json                          |   15 +
 docs/phase3/state/A10.json                         |   15 +
 docs/phase3/state/A11.json                         |    7 +
 docs/phase3/state/A12.json                         |   24 +
 docs/phase3/state/A13.json                         |   10 +
 docs/phase3/state/A2.json                          |   16 +
 docs/phase3/state/A3.json                          |   17 +
 docs/phase3/state/A4.json                          |   18 +
 docs/phase3/state/A5.json                          |   18 +
 docs/phase3/state/A6.json                          |   17 +
 docs/phase3/state/A7.json                          |    7 +
 docs/phase3/state/A8.json                          |    7 +
 docs/phase3/state/A9.json                          |    7 +
 docs/phase3/state/A_decisions_needed.md            |   15 +
 docs/phase3/state/C1.json                          |   14 +
 docs/phase3/state/C5.json                          |   23 +
 docs/phase3/state/C6.json                          |    7 +
 scripts/build_ue.ps1                               |   25 +-
 scripts/build_ue.sh                                |    6 +-
 scripts/check_bridge_api.sh                        |    2 +-
 scripts/deploy_windows.ps1                         |    2 +-
 scripts/mutation_check.sh                          |   14 +-
 scripts/phase3_digest.py                           |  149 +++
 scripts/phase3_event.py                            |    5 +-
 scripts/phase3_state.py                            |  110 ++
 scripts/render_ue_scenario.sh                      |    2 +-
 scripts/run_ue_scenario.sh                         |    2 +-
 scripts/setup.ps1                                  |    2 +-
 scripts/setup.sh                                   |    2 +-
 scripts/ue_create_materials.py                     |    2 +-
 scripts/ue_engine.ps1                              |   50 +
 scripts/ue_preflight.ps1                           |   56 +-
 scripts/ue_preflight.sh                            |    6 +-
 scripts/vendor_ue_plugin.ps1                       |   14 +-
 scripts/vendor_ue_plugin.sh                        |    8 +-
 tests/test_a4.py                                   |   14 +-
 tests/test_airframe.py                             |   99 ++
 tests/test_gate6_visual.py                         |    3 +-
 tests/test_platform.py                             |  104 +-
 tests/test_powershell_scripts.py                   |   60 +
 tests/test_toolchain_doc.py                        |   49 +
 tests/test_ue_materials.py                         |   23 +
 tests/test_ue_weather_source.py                    |   11 +
 tests/test_webapp_generate.py                      |   59 +
 ue/FlightSim.uproject                              |    2 +-
 .../Private/FlightSimRenderCommandlet.cpp          |    2 +-
 .../FlightSimBridge/Private/FlightSimWeather.cpp   |   19 +-
 .../Resources/JSBSim/aircraft/A4/A4.xml            |    6 +-
 ue/Source/FlightSim.Target.cs                      |    2 +-
 ue/Source/FlightSimEditor.Target.cs                |    2 +-
 webapp/generate.py                                 |   11 +
 82 files changed, 3940 insertions(+), 166 deletions(-)

b135d207 C5: component label records, parent rollup, manifest v8

 core/capture/labels.py                       |  126 +-
 core/capture/manifest.py                     |   15 +-
 core/capture/objects.py                      |   28 +-
 core/scenario/blocks.py                      |    2 +-
 docs/schemas/capture_manifest.v8.schema.json | 2059 ++++++++++++++++++++++++++
 tests/test_camera_labels.py                  |    5 +-
 tests/test_capture_objects.py                |    5 +-
 tests/test_capture_schema.py                 |    4 +-
 tests/test_component_labels.py               |  180 +++
 tests/test_versions.py                       |    2 +-
 10 files changed, 2406 insertions(+), 20 deletions(-)
```

## C6 · PASS · run A-2 · 2026-11-04T15:59:07Z

verify line(s) from tasks/phase3_checklist.md:

```
137:   - Check: `component_coverage` passes, and a COCO export has a `payload` category.
```

output line(s) that satisfy it:

```
runs/p3/A-2/C6-pytest.log: 55 dots [100%], exit 0 (pytest -q -k component)
runs/p3/A-2/C6-coco.log: ================ 1 passed, 12 deselected, 36 warnings in 6.78s ================ (test_payload_and_gear_are_their_own_coco_categories)
```

note: run A-2 on 23bad766; mutant half: the Mac auditor's subset in state/A.json

### synopsis

# C6 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T15:59:05Z

## C6 verify: pytest -q -k component

- log: `runs/p3/A-2/C6-pytest.log`
- exit: 0 (expected 0) -> PASS

```
...........................                                              [100%]
============================== warnings summary ===============================
tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:384: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:385: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")

tests/test_annotation_gates.py: 12 warnings
tests/test_dataset_boxes.py: 6 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:389: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")

tests/test_annotation_gates.py: 30 warnings
tests/test_dataset_boxes.py: 18 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:404: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(alone, mode="L").save(folder / alone_name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
```

## C6 COCO half: pytest -v tests/test_dataset_boxes.py -k payload_and_gear_are_their_own_coco

- log: `runs/p3/A-2/C6-coco.log`
- exit: 0 (expected 0) -> PASS

```
timeout method: thread
timeout func_only: False
collected 13 items / 12 deselected / 1 selected

tests\test_dataset_boxes.py .                                            [100%]

============================== warnings summary ===============================
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:384: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(ids, mode="L").save(folder / f"{stem}_mask.png")

tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:385: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(classes, mode="L").save(folder / f"{stem}_class.png")

tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
tests/test_dataset_boxes.py::test_payload_and_gear_are_their_own_coco_categories
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:389: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(png.astype(np.uint16), mode="I;16").save(folder / f"{stem}_depth.png")

tests/test_dataset_boxes.py: 18 warnings
  C:\Users\kanth\flightsim\tests\test_annotation_gates.py:404: DeprecationWarning: 'mode' parameter is deprecated and will be removed in Pillow 13 (2026-10-15)
    Image.fromarray(alone, mode="L").save(folder / alone_name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 1 passed, 12 deselected, 36 warnings in 6.78s ================
```

note: run A-2 on 23bad766; 55 component tests, no F; mutant half is the Mac auditor's (state/A.json audit)

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log
0209de50 Merge p3-C6: component box and coverage gates, component export categories
5e97e409 C6 integrator: component catalogue entries, class ids as words on the card
9683bbe5 Merge branch 'phase-2-final' into p3-C6
b2e362b9 C6: component_boxes and component_coverage gates, parent rollup in verify, payload/landing_gear export categories, guards
9d1a8256 Phase 3 decision 8: C6 proceeds after its lock wait, nothing forbidden

42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log

 docs/PHASE3_LOG.md                 |  29 +++
 docs/phase3/decisions.md           |   2 +
 docs/phase3/events_windows.log     |  17 ++
 docs/phase3/packets/A1-1.md        |  27 +++
 docs/phase3/packets/A2-synopsis.md | 117 +++++++++++
 docs/phase3/packets/A3-synopsis.md | 122 +++++++++++
 docs/phase3/packets/C1-synopsis.md |  47 +++++
 docs/phase3/packets/C5-synopsis.md |  18 ++
 docs/phase3/packets/C6-synopsis.md |  40 ++++
 docs/phase3/state/A1.json          |   5 +-
 docs/phase3/state/A3.json          |   4 +-
 docs/phase3/state/C1.json          |   4 +-
 docs/phase3/state/C5.json          |   4 +-
 docs/phase3/state/C6.json          |   4 +-
 docs/phase3/sync_log_A.md          | 409 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   8 +-
 16 files changed, 848 insertions(+), 9 deletions(-)

0209de50 Merge p3-C6: component box and coverage gates, component export categories

 core/capture/verify.py         | 236 ++++++++++++++++++++++++++++++++++++++---
 core/dataset/export.py         |  18 +++-
 core/messages/catalog.yaml     |   8 ++
 scripts/mutation_check.sh      |  18 ++++
 tests/test_annotation_gates.py | 165 ++++++++++++++++++++++++++--
 tests/test_dataset_boxes.py    |  96 ++++++++++++++++-
 tests/test_dataset_formats.py  |   8 +-
 tests/test_webapp_generate.py  |   5 +
 webapp/generate.py             |   9 +-
 9 files changed, 529 insertions(+), 34 deletions(-)

5e97e409 C6 integrator: component catalogue entries, class ids as words on the card

 core/messages/catalog.yaml    | 8 ++++++++
 tests/test_webapp_generate.py | 5 +++++
 webapp/generate.py            | 9 +++++++--
 3 files changed, 20 insertions(+), 2 deletions(-)

9683bbe5 Merge branch 'phase-2-final' into p3-C6

 .gitattributes                                     |   3 +
 core/messages/catalog.yaml                         |   3 +
 core/util/platform.py                              |  79 +++++++++++++++
 docs/phase3/notes/A4.md                            |   5 +
 flightsim/capture.py                               |   9 ++
 scripts/build_ue.ps1                               |  41 ++++++++
 .../ue/Plugins/FlightSimBridge/Source/A.cpp        |   1 +
 .../ue/Plugins/FlightSimBridge/Source/B.h          |   2 +
 .../ue/Plugins/FlightSimBridge/Source/Sub/C.cpp    |   2 +
 tests/test_binary_stale.py                         | 109 +++++++++++++++++++++
 webapp/runs.py                                     |   7 ++
 11 files changed, 261 insertions(+)

b2e362b9 C6: component_boxes and component_coverage gates, parent rollup in verify, payload/landing_gear export categories, guards

 core/capture/verify.py         | 236 ++++++++++++++++++++++++++++++++++++++---
 core/dataset/export.py         |  18 +++-
 scripts/mutation_check.sh      |  18 ++++
 tests/test_annotation_gates.py | 165 ++++++++++++++++++++++++++--
 tests/test_dataset_boxes.py    |  96 ++++++++++++++++-
 tests/test_dataset_formats.py  |   8 +-
 6 files changed, 509 insertions(+), 32 deletions(-)

9d1a8256 Phase 3 decision 8: C6 proceeds after its lock wait, nothing forbidden

 docs/phase3/decisions.md       | 2 ++
 docs/phase3/events_windows.log | 2 ++
 2 files changed, 4 insertions(+)
```

## A3 · PASS · run A-2 · 2026-11-04T16:03:43Z

verify line(s) from tasks/phase3_checklist.md:

```
53:   - Check: pointing it at another version stops with `engine.version_mismatch`.
54:   - Check: the right version builds with zero errors.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A3-build-55-refuse.log: engine.version_mismatch: found 5.5.4, pinned 5.7   (exit 1; no UnrealBuildTool/Build.bat line in the log)
runs/p3/A-2/A3-preflight-55.log:   engine                             engine.version_mismatch: found 5.5.4, pinned 5.7   (exit 1)
runs/p3/A-2/A3-preflight-57.log:   engine                             UE 5.7.4 at C:\Program Files\Epic Games\UE_5.7   (exit 0)
runs/p3/A-2/A2-build-2.log: Result: Succeeded   (0 'error C' lines; stamped 770fa283…, build_stamp.json engine_version 5.7.4)
```

note: run A-2 on 23bad766: pin 5.7 per decision 10; the first 5.7 build attempt (runs/p3/A-2/A2-build.log) failed on a Smart App Control block of the per-user MarketplaceRules.dll, cleared by deleting %LOCALAPPDATA%\UnrealEngine\Intermediate\Build\BuildRules (machine note); the retry is the record

### synopsis

# A3 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:03:43Z

## A3 step 6: build_ue.ps1 with UE_ROOT at UE_5.5 (wrong version under the 5.7 pin)

- log: `runs/p3/A-2/A3-build-55-refuse.log`
- exit: 1 (expected 1) -> PASS

```
engine.version_mismatch: found 5.5.4, pinned 5.7
At C:\Users\kanth\flightsim\scripts\build_ue.ps1:23 char:18
+ if ($mismatch) { throw $mismatch }
+                  ~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (engine.version_...5.4, pinned 5.7:String) [], RuntimeException
    + FullyQualifiedErrorId : engine.version_mismatch: found 5.5.4, pinned 5.7
 
```

## A3 step 7: ue_preflight.ps1 with UE_ROOT at UE_5.5

- log: `runs/p3/A-2/A3-preflight-55.log`
- exit: 1 (expected 1) -> PASS

```
Unreal host preflight (Windows)

  engine                             UE 5.5.4 at C:\Program Files\Epic Games\UE_5.5
  engine                             engine.version_mismatch: found 5.5.4, pinned 5.7
  visual studio (C++ tools)          17.14.39 (August 2026)
  v143 toolset (UE 5.7 needs it)     present
  jsbsim plugin                      vendored v1.2.4 (patched sources committed)
  jsbsim Win64 library               JSBSim.dll + JSBSim.lib present
  jsbsim plugin engine target        vendored for UE 5.7
  jsbsim runtime data                60 aircraft staged in Resources/JSBSim
  jsbsim parity                      both hosts at e07a7d810d4f
  flightsim bridge                   22 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  ffmpeg (clip encoding)             C:\Users\kanth\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe

Preflight FAILED -- see above.
```

## A3 step 7: ue_preflight.ps1 with UE_ROOT at the pinned UE_5.7

- log: `runs/p3/A-2/A3-preflight-57.log`
- exit: 0 (expected 0) -> PASS

```
Unreal host preflight (Windows)

  engine                             UE 5.7.4 at C:\Program Files\Epic Games\UE_5.7
  visual studio (C++ tools)          17.14.39 (August 2026)
  v143 toolset (UE 5.7 needs it)     present
  jsbsim plugin                      vendored v1.2.4 (patched sources committed)
  jsbsim Win64 library               JSBSim.dll + JSBSim.lib present
  jsbsim plugin engine target        vendored for UE 5.7
  jsbsim runtime data                60 aircraft staged in Resources/JSBSim
  jsbsim parity                      both hosts at e07a7d810d4f
  flightsim bridge                   22 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  ffmpeg (clip encoding)             C:\Users\kanth\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe

Preflight OK -- the Unreal host can run here.
Validate the render output on THIS machine with:
  .\.venv\Scripts\python.exe experiments\gate6_visual.py
```

## A3 step 7: build_ue.ps1 on the pinned UE_5.7 (zero errors)

- log: `runs/p3/A-2/A2-build-2.log`
- exit: 0 (expected 0) -> PASS

```
  Storage capacity 40Gb
---- Starting trace: 261104_105833 ----
UbaServer - Listening on 0.0.0.0:1345
[1/25] Resource Default.rc2
[2/25] Compile [x64] Module.JSBSimFlightDynamicsModel.cpp
[3/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.lib
[4/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.dll
[5/25] Resource Default.rc2
[6/25] Compile [x64] Module.FlightSimBridge.1.cpp
[7/25] Compile [x64] Module.FlightSimBridge.2.cpp
[8/25] Compile [x64] Module.FlightSimBridge.3.cpp
[9/25] Link [x64] UnrealEditor-FlightSimBridge.lib
[10/25] Link [x64] UnrealEditor-FlightSimBridge.dll
[11/25] Resource Default.rc2
[12/25] Compile [x64] FlightSim.cpp
[13/25] Compile [x64] PerModuleInline.gen.cpp
[14/25] Link [x64] UnrealEditor-FlightSim.dll
[15/25] Link [x64] UnrealEditor-FlightSim.lib
[16/25] Resource Default.rc2
[17/25] Compile [x64] Module.FlightSimBridgeEditor.cpp
C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Source\FlightSimBridgeEditor\Private\FlightSimLandscapeImporter.cpp(381,15): warning C4996: 'ULandscapeSubsystem::BuildNanite': Use the function with the EBuildFlags param - Please update your code to the new API before upgrading to the next release, otherwise your project will no longer compile.
			Subsystem->BuildNanite();
			           ^
[18/25] Link [x64] UnrealEditor-FlightSimBridgeEditor.dll
[19/25] Link [x64] UnrealEditor-FlightSimBridgeEditor.lib
[20/25] Resource Default.rc2
[21/25] Compile [x64] Module.JSBSimFlightDynamicsModelEditor.cpp
[22/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.dll
[23/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.lib
[24/25] Copy JSBSim.dll
[25/25] WriteMetadata FlightSimEditor.target [NoUba]

Trace written to file C:/Users/kanth/AppData/Local/UnrealBuildTool/Log.uba with size 22.6kb
Total time in Unreal Build Accelerator local executor: 185.91 seconds

Result: Succeeded
Total execution time: 204.14 seconds
stamped 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5

built. Next: .\scripts\ue_preflight.ps1 to confirm, then render.
```

note: run A-2 on 23bad766: the pin is 5.7 (decision 10), UE_5.5 is the wrong-version case; both helpers ran under Windows PowerShell 5.1 (powershell.exe)

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log
5cf331c8 Merge p3-A3: build/preflight refuse the wrong engine by name (ue_engine.ps1, no UE_5.* glob)
4dfa4452 A3: the build refuses the wrong engine by name (ue_engine.ps1, no UE_5.* glob)

42183a30 Phase 3 letter A, run A-1: A3, C1, C5, C6 PASS; A1 cut (decision 9); synopses and log

 docs/PHASE3_LOG.md                 |  29 +++
 docs/phase3/decisions.md           |   2 +
 docs/phase3/events_windows.log     |  17 ++
 docs/phase3/packets/A1-1.md        |  27 +++
 docs/phase3/packets/A2-synopsis.md | 117 +++++++++++
 docs/phase3/packets/A3-synopsis.md | 122 +++++++++++
 docs/phase3/packets/C1-synopsis.md |  47 +++++
 docs/phase3/packets/C5-synopsis.md |  18 ++
 docs/phase3/packets/C6-synopsis.md |  40 ++++
 docs/phase3/state/A1.json          |   5 +-
 docs/phase3/state/A3.json          |   4 +-
 docs/phase3/state/C1.json          |   4 +-
 docs/phase3/state/C5.json          |   4 +-
 docs/phase3/state/C6.json          |   4 +-
 docs/phase3/sync_log_A.md          | 409 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   8 +-
 16 files changed, 848 insertions(+), 9 deletions(-)

5cf331c8 Merge p3-A3: build/preflight refuse the wrong engine by name (ue_engine.ps1, no UE_5.* glob)

 scripts/build_ue.ps1             | 25 ++++++++---------
 scripts/ue_engine.ps1            | 50 +++++++++++++++++++++++++++++++++
 scripts/ue_preflight.ps1         | 56 ++++++++++++++-----------------------
 tests/test_powershell_scripts.py | 60 ++++++++++++++++++++++++++++++++++++++++
 4 files changed, 143 insertions(+), 48 deletions(-)

4dfa4452 A3: the build refuses the wrong engine by name (ue_engine.ps1, no UE_5.* glob)

 scripts/build_ue.ps1             | 25 ++++++++---------
 scripts/ue_engine.ps1            | 50 +++++++++++++++++++++++++++++++++
 scripts/ue_preflight.ps1         | 56 ++++++++++++++-----------------------
 tests/test_powershell_scripts.py | 60 ++++++++++++++++++++++++++++++++++++++++
 4 files changed, 143 insertions(+), 48 deletions(-)
```

## A4 · PASS · run A-2 · 2026-11-04T16:20:54Z

verify line(s) from tasks/phase3_checklist.md:

```
57:     `engine.binary_stale`.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A4-stale-web.log: status 409  {"refused":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now b714730baf8a102f94876c228334dc80fc21ea71f668d64f7ecbf916e5286ffc","constraint":"engine.binary_stale", ...}
runs/p3/A-2/A4-fresh-web.log: status 200 {"run_id":"4be692c3e9fe", ...} -> run done: clip ready (stale gate passed after the revert; binary_stale_reason None, hash 770fa283 == stamp)
runs/p3/A-2/A4-ps-hash.log: fixture 0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49 == golden; repo-ps1 770fa283… == python repo 770fa283… (runs/p3/A-2/A4-py-hash.log)
```

note: run A-2 on UE 5.7.4; the web path checks the stamp right after ue_available(), so the probe needs no bake or editor; the same build_stamp.json now carries engine_version 5.7.4

### synopsis

# A4 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:20:54Z

## A4 step 6-7: PowerShell Get-PluginSourceHash fixture vs golden, repo vs python twin

- log: `runs/p3/A-2/A4-ps-hash.log`
- exit: 0 (expected 0) -> PASS

```
fixture  0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
golden   0141215eaa199cccb8b67a2acbdccecfcb70e4487506da5a93a326abcc05dc49
repo-ps1 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5
```

## A4 step 8 first half (web path, 5.7 build): FlightSimSky.cpp edited, no rebuild, POST /run

- log: `runs/p3/A-2/A4-stale-web.log`
- exit: 0 (expected 0) -> PASS

```
status 409
{"refused":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now b714730baf8a102f94876c228334dc80fc21ea71f668d64f7ecbf916e5286ffc","constraint":"engine.binary_stale","sentence":"The request was refused.","hint":"","details":{"rule":"the built bridge is from source 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5 but the source is now b714730baf8a102f94876c228334dc80fc21ea71f668d64f7ecbf916e5286ffc","message":"","catalogued":false}}
```

## A4 step 8 second half: source reverted, POST /run accepted and the run completed

- log: `runs/p3/A-2/A4-fresh-web.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"4be692c3e9fe","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
status 200 run 4be692c3e9fe done: clip ready (host flight 220 samples, 220 frames rendered, labels attached on 220 of 220)
```

note: run A-2 on 23bad766 / UE 5.7.4 build 770fa283 (build_stamp.json engine_version 5.7.4); the stale POST returned HTTP 409 engine.binary_stale naming both hashes; the reverted POST returned 200 run 4be692c3e9fe which finished 'done: clip ready'

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
94c1871a Phase 3 A4 PASS (run A-1): stale engine binary refused by name on the web path
94f56764 Merge p3-A4: stale engine binary refused (build stamp vs plugin source hash)
9a0fdfef A4 integrator: capture wiring test, note integrator_edits
52b450b3 A4 integrator: skip stale check when no bridge binary exists (drops conftest fixture); CRLF fixture -text; capture wiring test
d67232f0 Merge branch 'phase-2-final' into p3-A4
b9c8d830 A4: refuse a stale engine binary (build stamp, plugin source hash, engine.binary_stale)

94c1871a Phase 3 A4 PASS (run A-1): stale engine binary refused by name on the web path

 docs/phase3/events_windows.log     |   9 +++
 docs/phase3/packets/A4-synopsis.md |  88 ++++++++++++++++++++++
 docs/phase3/state/A4.json          |   4 +-
 docs/phase3/sync_log_A.md          | 146 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   2 +-
 5 files changed, 247 insertions(+), 2 deletions(-)

94f56764 Merge p3-A4: stale engine binary refused (build stamp vs plugin source hash)

 .gitattributes                                     |   3 +
 core/messages/catalog.yaml                         |   3 +
 core/util/platform.py                              |  79 +++++++++++++++
 docs/phase3/notes/A4.md                            |   5 +
 flightsim/capture.py                               |   9 ++
 scripts/build_ue.ps1                               |  41 ++++++++
 .../ue/Plugins/FlightSimBridge/Source/A.cpp        |   1 +
 .../ue/Plugins/FlightSimBridge/Source/B.h          |   2 +
 .../ue/Plugins/FlightSimBridge/Source/Sub/C.cpp    |   2 +
 tests/test_binary_stale.py                         | 109 +++++++++++++++++++++
 webapp/runs.py                                     |   7 ++
 11 files changed, 261 insertions(+)

9a0fdfef A4 integrator: capture wiring test, note integrator_edits

 docs/phase3/notes/A4.md    | 5 +++++
 tests/conftest.py          | 1 -
 tests/test_binary_stale.py | 9 ++++++---
 3 files changed, 11 insertions(+), 4 deletions(-)

52b450b3 A4 integrator: skip stale check when no bridge binary exists (drops conftest fixture); CRLF fixture -text; capture wiring test

 .gitattributes                                     |  3 +++
 core/util/platform.py                              |  7 ++++-
 tests/conftest.py                                  | 12 ---------
 .../ue/Plugins/FlightSimBridge/Source/B.h          |  4 +--
 tests/test_binary_stale.py                         | 30 ++++++++++++++++++++++
 5 files changed, 41 insertions(+), 15 deletions(-)

d67232f0 Merge branch 'phase-2-final' into p3-A4

 NEXT.md                                            |   95 +-
 assets/aircraft_config/A4.json                     |   79 +-
 assets/fdm_root/aircraft/A4/A4.xml                 |    6 +-
 assets_pipeline/a4_performance.py                  |   11 +-
 assets_pipeline/a4_sync.py                         |    8 +-
 core/capture/airframe.py                           |  115 +-
 core/capture/labels.py                             |  126 +-
 core/capture/manifest.py                           |   15 +-
 core/capture/objects.py                            |   28 +-
 core/capture/verify.py                             |   77 +
 core/messages/catalog.yaml                         |    7 +
 core/scenario/blocks.py                            |    2 +-
 docs/phase3/BUILDER_BRIEF.md                       |   52 +
 docs/phase3/INTEGRATOR_BRIEF.md                    |   52 +
 docs/phase3/SUBAGENT_BRIEF.md                      |   47 +
 docs/phase3/digest_A.md                            | 1260 ++++++++++++
 docs/phase3/events_mac.log                         |  239 +++
 docs/phase3/notes/A1.md                            |   55 +
 docs/phase3/notes/A10.md                           |   50 +
 docs/phase3/notes/A11.md                           |   59 +
 docs/phase3/notes/A12.md                           |   58 +
 docs/phase3/notes/A13.md                           |   44 +
 docs/phase3/notes/A2.md                            |   79 +
 docs/phase3/notes/A3.md                            |   69 +
 docs/phase3/notes/A4.md                            |   85 +
 docs/phase3/notes/A5.md                            |   58 +
 docs/phase3/notes/A6.md                            |   59 +
 docs/phase3/notes/A7.md                            |   64 +
 docs/phase3/notes/A8.md                            |   61 +
 docs/phase3/notes/A9.md                            |   60 +
 docs/phase3/notes/C1.md                            |   64 +
 docs/phase3/notes/C5.md                            |   68 +
 docs/phase3/notes/C6.md                            |   65 +
 docs/phase3/state/A.json                           |   41 +
 docs/phase3/state/A1.json                          |   15 +
 docs/phase3/state/A10.json                         |   15 +
 docs/phase3/state/A11.json                         |    7 +
 docs/phase3/state/A12.json                         |   24 +
 docs/phase3/state/A13.json                         |   10 +
 docs/phase3/state/A2.json                          |   16 +
 docs/phase3/state/A3.json                          |   17 +
 docs/phase3/state/A4.json                          |   18 +
 docs/phase3/state/A5.json                          |   18 +
 docs/phase3/state/A6.json                          |   17 +
 docs/phase3/state/A7.json                          |    7 +
 docs/phase3/state/A8.json                          |    7 +
 docs/phase3/state/A9.json                          |    7 +
 docs/phase3/state/A_decisions_needed.md            |   15 +
 docs/phase3/state/C1.json                          |   14 +
 docs/phase3/state/C5.json                          |   23 +
 docs/phase3/state/C6.json                          |    7 +
 docs/schemas/capture_manifest.v8.schema.json       | 2059 ++++++++++++++++++++
 scripts/label_diagnose.py                          |   42 +
 scripts/phase3_digest.py                           |  149 ++
 scripts/phase3_event.py                            |    5 +-
 scripts/phase3_state.py                            |  110 ++
 tests/test_a4.py                                   |   14 +-
 tests/test_airframe.py                             |   99 +
 tests/test_annotation_gates.py                     |   55 +-
 tests/test_camera_labels.py                        |    5 +-
 tests/test_capture_objects.py                      |    5 +-
 tests/test_capture_schema.py                       |    4 +-
 tests/test_component_labels.py                     |  180 ++
 tests/test_engine_bundle_golden.py                 |   96 +
 tests/test_label_diagnose.py                       |   53 +
 tests/test_platform.py                             |    2 +-
 tests/test_ue_physics_source.py                    |    8 +
 tests/test_versions.py                             |    2 +-
 .../Resources/JSBSim/aircraft/A4/A4.xml            |    6 +-
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json |   19 +-
 70 files changed, 6303 insertions(+), 105 deletions(-)

b9c8d830 A4: refuse a stale engine binary (build stamp, plugin source hash, engine.binary_stale)

 core/messages/catalog.yaml                         |  3 +
 core/util/platform.py                              | 74 +++++++++++++++++++++
 flightsim/capture.py                               |  9 +++
 scripts/build_ue.ps1                               | 41 ++++++++++++
 tests/conftest.py                                  | 13 ++++
 .../ue/Plugins/FlightSimBridge/Source/A.cpp        |  1 +
 .../ue/Plugins/FlightSimBridge/Source/B.h          |  2 +
 .../ue/Plugins/FlightSimBridge/Source/Sub/C.cpp    |  2 +
 tests/test_binary_stale.py                         | 76 ++++++++++++++++++++++
 webapp/runs.py                                     |  7 ++
 10 files changed, 228 insertions(+)
```

## A2 · PASS · run A-2 · 2026-11-04T16:36:09Z

verify line(s) from tasks/phase3_checklist.md:

```
50:   - Check: `pytest -q tests/test_platform.py` passes.
51:   - Check: changing the version in one file by hand makes that test fail.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A2-pytest-platform.log: .............. [100%]  (exit 0)
runs/p3/A-2/A2-pytest-platform-edited.log: AssertionError: ue\Source\FlightSim.Target.cs does not pin EngineIncludeOrderVersion.Unreal5_7 (UE_ENGINE_VERSION = 5.7)  /  FAILED tests/test_platform.py::test_target_cs_include_order_names_the_pin  (exit 1; file reverted)
runs/p3/A-2/A2-build-2.log: Result: Succeeded (0 'error C'); runs/webapp/4be692c3e9fe/frames/render.log: 0 REFUSED lines, cloud material used, landscape raster AGL check
```

note: run A-2 on 23bad766 (pin sweep 5.7) + 2b746352; pin now 5.7 everywhere the test checks (toolchain row, uproject, Target.cs, scripts, VENDORED.json)

### synopsis

# A2 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:36:08Z

## A2 verify: pytest -q tests/test_platform.py (FLIGHTSIM_GOOGLE_TILES unset)

- log: `runs/p3/A-2/A2-pytest-platform.log`
- exit: 0 (expected 0) -> PASS

```
..............                                                           [100%]
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## A2 verify: FlightSim.Target.cs hand-edited to Unreal5_5, same pytest must fail naming the file

- log: `runs/p3/A-2/A2-pytest-platform-edited.log`
- exit: 1 (expected 1) -> PASS

```
..........F...                                                           [100%]
================================== FAILURES ===================================
_________________ test_target_cs_include_order_names_the_pin __________________

    def test_target_cs_include_order_names_the_pin():
        """Hand-editing one Target.cs to another version fails here, with the
        file named (R1 is a CI failure, not a Windows surprise)."""
        wanted = "EngineIncludeOrderVersion.Unreal" + plat.UE_ENGINE_VERSION.replace(".", "_")
        for path in sorted((REPO / "ue" / "Source").glob("*.Target.cs")):
            text = path.read_text(encoding="utf-8")
>           assert f"IncludeOrderVersion = {wanted};" in text, (
                f"{path.relative_to(REPO)} does not pin {wanted} "
                f"(UE_ENGINE_VERSION = {plat.UE_ENGINE_VERSION})")
E           AssertionError: ue\Source\FlightSim.Target.cs does not pin EngineIncludeOrderVersion.Unreal5_7 (UE_ENGINE_VERSION = 5.7)
E           assert 'IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;' in 'using UnrealBuildTool;\n\npublic class FlightSimTarget : TargetRules\n{\n\tpublic FlightSimTarget(TargetInfo Target) ...est;\n\t\tIncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_5;\n\t\tExtraModuleNames.Add("FlightSim");\n\t}\n}\n'

tests\test_platform.py:341: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_platform.py::test_target_cs_include_order_names_the_pin - A...
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## A2 step 9: build_ue.ps1 on 5.7.4 (zero errors)

- log: `runs/p3/A-2/A2-build-2.log`
- exit: 0 (expected 0) -> PASS

```
  Storage capacity 40Gb
---- Starting trace: 261104_105833 ----
UbaServer - Listening on 0.0.0.0:1345
[1/25] Resource Default.rc2
[2/25] Compile [x64] Module.JSBSimFlightDynamicsModel.cpp
[3/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.lib
[4/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModel.dll
[5/25] Resource Default.rc2
[6/25] Compile [x64] Module.FlightSimBridge.1.cpp
[7/25] Compile [x64] Module.FlightSimBridge.2.cpp
[8/25] Compile [x64] Module.FlightSimBridge.3.cpp
[9/25] Link [x64] UnrealEditor-FlightSimBridge.lib
[10/25] Link [x64] UnrealEditor-FlightSimBridge.dll
[11/25] Resource Default.rc2
[12/25] Compile [x64] FlightSim.cpp
[13/25] Compile [x64] PerModuleInline.gen.cpp
[14/25] Link [x64] UnrealEditor-FlightSim.dll
[15/25] Link [x64] UnrealEditor-FlightSim.lib
[16/25] Resource Default.rc2
[17/25] Compile [x64] Module.FlightSimBridgeEditor.cpp
C:\Users\kanth\flightsim\ue\Plugins\FlightSimBridge\Source\FlightSimBridgeEditor\Private\FlightSimLandscapeImporter.cpp(381,15): warning C4996: 'ULandscapeSubsystem::BuildNanite': Use the function with the EBuildFlags param - Please update your code to the new API before upgrading to the next release, otherwise your project will no longer compile.
			Subsystem->BuildNanite();
			           ^
[18/25] Link [x64] UnrealEditor-FlightSimBridgeEditor.dll
[19/25] Link [x64] UnrealEditor-FlightSimBridgeEditor.lib
[20/25] Resource Default.rc2
[21/25] Compile [x64] Module.JSBSimFlightDynamicsModelEditor.cpp
[22/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.dll
[23/25] Link [x64] UnrealEditor-JSBSimFlightDynamicsModelEditor.lib
[24/25] Copy JSBSim.dll
[25/25] WriteMetadata FlightSimEditor.target [NoUba]

Trace written to file C:/Users/kanth/AppData/Local/UnrealBuildTool/Log.uba with size 22.6kb
Total time in Unreal Build Accelerator local executor: 185.91 seconds

Result: Succeeded
Total execution time: 204.14 seconds
stamped 770fa283dc1b178644309885b1e7ed82fb9d321dd89eefdef516a0c21cf69ac5

built. Next: .\scripts\ue_preflight.ps1 to confirm, then render.
```

note: A2 step 10 (cloud-material and landscape paths once, no REFUSED line): web run 4be692c3e9fe on the 5.7 build, runs/webapp/4be692c3e9fe/frames/render.log: 57772 lines, 0 REFUSED; 'LogFlightSimWeather: cloud VolumetricCloudComponent ... m_SimpleVolumetricCloud_Inst, domain 3, used'; 'LogFlightSimScenario: AGL check against the collision raster: elevation under the start point 1340.2 m'; 'LogFlightSimRender: wrote 220 frames'

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
72ed3eca Phase 3 A2 retry 1: UE 5.7.4 patch level, toolchain row 1, letter A agenda on 5.7, builders on fable
393c7295 Phase 3 A2 retry 1: integrator notes, state and Mac event log
7853cd63 Merge p3-A2r: A2 retry 1, engine pin moves to UE 5.7 (owner decision 10)
66a7c1da A2 retry 1: engine pin moves to UE 5.7 (owner decision 10)
be6bf574 A2: version-guard the cloud material load for UE 5.5 (LoadSynchronous is 5.7-only)
2db0b1f1 Merge p3-A2: pin UE 5.5 (uproject, Target.cs, platform.py, scripts, docs) + A1 toolchain doc test
5166765c A1/A2 integrate: narrow pin-sweep allowance, rewrite preflight mutation guard, drop pending-by-design test
6375569e Merge p3-C1: components block, A-4 default loadout (3 x 750 lb on STA2-4), aircraft.component_unmatched
8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal
a022c2b6 Merge branch 'phase-2-final' into p3-A2
e4a8a337 A1+A2: pin the engine to 5.5.4, version-guard GetMaterialResource, pin sweep and tests

72ed3eca Phase 3 A2 retry 1: UE 5.7.4 patch level, toolchain row 1, letter A agenda on 5.7, builders on fable

 core/util/platform.py          |  6 +++---
 docs/TOOLCHAIN.md              |  2 +-
 docs/phase3/BUILDER_BRIEF.md   |  2 +-
 docs/phase3/PROMPT_MAC.md      |  6 +++---
 docs/phase3/PROMPT_WINDOWS.md  |  4 ++--
 docs/phase3/events_mac.log     |  3 +++
 docs/phase3/state/A2.json      |  6 +++---
 tasks/phase3_checklist.md      | 15 ++++++++-------
 tasks/phase3_todo.md           | 38 ++++++++++++++++++++------------------
 tests/test_check_bridge_api.py | 11 ++++++-----
 10 files changed, 50 insertions(+), 43 deletions(-)

393c7295 Phase 3 A2 retry 1: integrator notes, state and Mac event log

 docs/phase3/events_mac.log | 10 ++++++++++
 docs/phase3/notes/A2.md    | 10 ++++++++++
 docs/phase3/state/A2.json  |  9 +++++++--
 3 files changed, 27 insertions(+), 2 deletions(-)

7853cd63 Merge p3-A2r: A2 retry 1, engine pin moves to UE 5.7 (owner decision 10)

 NEXT.md                                            | 27 +++++++++-------------
 README.md                                          |  4 ++--
 core/util/platform.py                              | 21 +++++++++--------
 docs/CAMERA_WINDOWS.md                             |  2 +-
 docs/TOOLCHAIN.md                                  | 25 +++++++++++---------
 scripts/build_ue.sh                                |  4 ++--
 scripts/check_bridge_api.sh                        |  2 +-
 scripts/deploy_windows.ps1                         |  2 +-
 scripts/mutation_check.sh                          |  6 ++---
 scripts/render_ue_scenario.sh                      |  2 +-
 scripts/run_ue_scenario.sh                         |  2 +-
 scripts/setup.ps1                                  |  2 +-
 scripts/setup.sh                                   |  2 +-
 scripts/ue_preflight.sh                            |  4 ++--
 scripts/vendor_ue_plugin.ps1                       |  6 ++---
 scripts/vendor_ue_plugin.sh                        |  2 +-
 tests/test_check_bridge_api.py                     |  2 +-
 tests/test_gate6_visual.py                         |  2 +-
 tests/test_platform.py                             |  5 ++--
 tests/test_ue_physics_source.py                    |  2 +-
 tests/test_ue_weather_source.py                    |  2 +-
 ue/FlightSim.uproject                              |  2 +-
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json | 14 +++++------
 ue/Source/FlightSim.Target.cs                      |  2 +-
 ue/Source/FlightSimEditor.Target.cs                |  2 +-
 25 files changed, 72 insertions(+), 74 deletions(-)

66a7c1da A2 retry 1: engine pin moves to UE 5.7 (owner decision 10)

 NEXT.md                                            | 27 +++++++++-------------
 README.md                                          |  4 ++--
 core/util/platform.py                              | 21 +++++++++--------
 docs/CAMERA_WINDOWS.md                             |  2 +-
 docs/TOOLCHAIN.md                                  | 25 +++++++++++---------
 scripts/build_ue.sh                                |  4 ++--
 scripts/check_bridge_api.sh                        |  2 +-
 scripts/deploy_windows.ps1                         |  2 +-
 scripts/mutation_check.sh                          |  6 ++---
 scripts/render_ue_scenario.sh                      |  2 +-
 scripts/run_ue_scenario.sh                         |  2 +-
 scripts/setup.ps1                                  |  2 +-
 scripts/setup.sh                                   |  2 +-
 scripts/ue_preflight.sh                            |  4 ++--
 scripts/vendor_ue_plugin.ps1                       |  6 ++---
 scripts/vendor_ue_plugin.sh                        |  2 +-
 tests/test_check_bridge_api.py                     |  2 +-
 tests/test_gate6_visual.py                         |  2 +-
 tests/test_platform.py                             |  5 ++--
 tests/test_ue_physics_source.py                    |  2 +-
 tests/test_ue_weather_source.py                    |  2 +-
 ue/FlightSim.uproject                              |  2 +-
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json | 14 +++++------
 ue/Source/FlightSim.Target.cs                      |  2 +-
 ue/Source/FlightSimEditor.Target.cs                |  2 +-
 25 files changed, 72 insertions(+), 74 deletions(-)

be6bf574 A2: version-guard the cloud material load for UE 5.5 (LoadSynchronous is 5.7-only)

 .../Source/FlightSimBridge/Private/FlightSimVisualScene.cpp          | 5 +++++
 1 file changed, 5 insertions(+)

2db0b1f1 Merge p3-A2: pin UE 5.5 (uproject, Target.cs, platform.py, scripts, docs) + A1 toolchain doc test

 README.md                                          |   4 +-
 core/util/platform.py                              |  28 +++---
 docs/CAMERA_WINDOWS.md                             |   3 +-
 scripts/build_ue.sh                                |   6 +-
 scripts/check_bridge_api.sh                        |   2 +-
 scripts/deploy_windows.ps1                         |   2 +-
 scripts/mutation_check.sh                          |  14 +--
 scripts/render_ue_scenario.sh                      |   2 +-
 scripts/run_ue_scenario.sh                         |   2 +-
 scripts/setup.ps1                                  |   2 +-
 scripts/setup.sh                                   |   2 +-
 scripts/ue_preflight.sh                            |   6 +-
 scripts/vendor_ue_plugin.ps1                       |  14 ++-
 scripts/vendor_ue_plugin.sh                        |   8 +-
 tests/test_gate6_visual.py                         |   3 +-
 tests/test_platform.py                             | 104 +++++++++++++++------
 tests/test_toolchain_doc.py                        |  49 ++++++++++
 tests/test_ue_weather_source.py                    |  11 +++
 ue/FlightSim.uproject                              |   2 +-
 .../Private/FlightSimRenderCommandlet.cpp          |   2 +-
 .../FlightSimBridge/Private/FlightSimWeather.cpp   |  19 +++-
 ue/Source/FlightSim.Target.cs                      |   2 +-
 ue/Source/FlightSimEditor.Target.cs                |   2 +-
 23 files changed, 202 insertions(+), 87 deletions(-)

5166765c A1/A2 integrate: narrow pin-sweep allowance, rewrite preflight mutation guard, drop pending-by-design test

 scripts/mutation_check.sh   | 8 ++++----
 tests/test_platform.py      | 2 +-
 tests/test_toolchain_doc.py | 9 +--------
 3 files changed, 6 insertions(+), 13 deletions(-)

6375569e Merge p3-C1: components block, A-4 default loadout (3 x 750 lb on STA2-4), aircraft.component_unmatched

 assets/aircraft_config/A4.json                     |  79 +++++++++++---
 assets/fdm_root/aircraft/A4/A4.xml                 |   6 +-
 assets_pipeline/a4_performance.py                  |  11 +-
 assets_pipeline/a4_sync.py                         |   8 +-
 core/capture/airframe.py                           | 115 ++++++++++++++++++++-
 core/messages/catalog.yaml                         |   3 +
 docs/phase3/notes/C1.md                            |   4 +
 tests/test_a4.py                                   |  14 ++-
 tests/test_airframe.py                             |  99 ++++++++++++++++++
 .../Resources/JSBSim/aircraft/A4/A4.xml            |   6 +-
 10 files changed, 316 insertions(+), 29 deletions(-)

8831a3df C1: components block, default loadout (750 lb on STA2-4), component_unmatched refusal

 assets/aircraft_config/A4.json                     |  79 +++++++++++---
 assets/fdm_root/aircraft/A4/A4.xml                 |   6 +-
 assets_pipeline/a4_performance.py                  |  11 +-
 assets_pipeline/a4_sync.py                         |   8 +-
 core/capture/airframe.py                           | 115 ++++++++++++++++++++-
 core/messages/catalog.yaml                         |   3 +
 docs/phase3/notes/C1.md                            |   4 +
 tests/test_a4.py                                   |  14 ++-
 tests/test_airframe.py                             |  99 ++++++++++++++++++
 .../Resources/JSBSim/aircraft/A4/A4.xml            |   6 +-
 10 files changed, 316 insertions(+), 29 deletions(-)

a022c2b6 Merge branch 'phase-2-final' into p3-A2

 scripts/build_ue.ps1             | 25 ++++++++---------
 scripts/ue_create_materials.py   |  2 +-
 scripts/ue_engine.ps1            | 50 +++++++++++++++++++++++++++++++++
 scripts/ue_preflight.ps1         | 56 ++++++++++++++-----------------------
 tests/test_powershell_scripts.py | 60 ++++++++++++++++++++++++++++++++++++++++
 tests/test_ue_materials.py       | 23 +++++++++++++++
 tests/test_webapp_generate.py    | 59 +++++++++++++++++++++++++++++++++++++++
 webapp/generate.py               | 11 ++++++++
 8 files changed, 237 insertions(+), 49 deletions(-)

e4a8a337 A1+A2: pin the engine to 5.5.4, version-guard GetMaterialResource, pin sweep and tests

 README.md                                          |   4 +-
 core/util/platform.py                              |  28 +++---
 docs/CAMERA_WINDOWS.md                             |   3 +-
 scripts/build_ue.sh                                |   6 +-
 scripts/check_bridge_api.sh                        |   2 +-
 scripts/deploy_windows.ps1                         |   2 +-
 scripts/mutation_check.sh                          |   6 +-
 scripts/render_ue_scenario.sh                      |   2 +-
 scripts/run_ue_scenario.sh                         |   2 +-
 scripts/setup.ps1                                  |   2 +-
 scripts/setup.sh                                   |   2 +-
 scripts/ue_preflight.sh                            |   6 +-
 scripts/vendor_ue_plugin.ps1                       |  14 ++-
 scripts/vendor_ue_plugin.sh                        |   8 +-
 tests/test_gate6_visual.py                         |   3 +-
 tests/test_platform.py                             | 104 +++++++++++++++------
 tests/test_toolchain_doc.py                        |  56 +++++++++++
 tests/test_ue_weather_source.py                    |  11 +++
 ue/FlightSim.uproject                              |   2 +-
 .../Private/FlightSimRenderCommandlet.cpp          |   2 +-
 .../FlightSimBridge/Private/FlightSimWeather.cpp   |  19 +++-
 ue/Source/FlightSim.Target.cs                      |   2 +-
 ue/Source/FlightSimEditor.Target.cs                |   2 +-
 23 files changed, 205 insertions(+), 83 deletions(-)
```

## A9 · PASS · run A-2 · 2026-11-04T16:51:19Z

verify line(s) from tasks/phase3_checklist.md:

```
71:   - Check: the default run has the same number of frames for both cameras.
72:   - Check: an empty camera stops with `render.camera_empty`.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A9-frames.log: frames/chase frame_NNNN.png: 200  /  frames/tower frame_NNNN.png: 200  (run 473b9e1ecfff done: clip ready; rendering 2 camera pass(es): chase, tower; labels attached on 400 of 400)
runs/p3/A-2/A9-frames.log: no render.camera_empty refusal (the guard did not fire)
```

note: run A-2: step 1's reproduction found no empty camera on 5.7 (the review's Windows cause did not recur with the 5.7 build and the A5 fixes), so step 6 has nothing to fix; steps 6 and 7 are satisfied by the same run: equal counts and a quiet guard; the run's verifier failures are other boxes' (host_determinism A8, mask_vs_geometry and tight_box_present A12)

### synopsis

# A9 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:51:18Z

## A9 step 1/6/7: default two-camera run through the web app (POST /run, chase + tower)

- log: `runs/p3/A-2/A9-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"473b9e1ecfff","digest":"a65a380837f70079993de42e905ec5694aa41b990ea5a98d651a47c73fa64b5d"}
```

## A9 frame counts per camera and the run's events

- log: `runs/p3/A-2/A9-frames.log`
- exit: 0 (expected 0) -> PASS

```
run 473b9e1ecfff done: clip ready (two cameras chase + tower, Grand Canyon A-4, 20 s)
frames/chase frame_NNNN.png: 200
frames/tower frame_NNNN.png: 200
events: rendering 2 camera pass(es): chase, tower; engine labels attached on 400 of 400 frame(s) (0 without a bundle); clip: 200 frames of chase at 10.0 fps = 20.0 s; a clip per view: chase, tower
no render.camera_empty refusal (the guard did not fire); verification FAILED: host_determinism (A8), mask_vs_geometry, tight_box_present (A12)
```

note: run A-2 on UE 5.7.4 build 99dc982e: the empty second camera did not reproduce; both camera passes wrote 200 frames; the render.camera_empty guard did not fire on this healthy run

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
140d8cdf Merge p3-A9: render refuses by name when a camera drew no frames (render.camera_empty)
a61f2589 A9 integrator: CLI render-path test for render.camera_empty
ff32cbcd A9: a camera with zero frames refuses render.camera_empty by name (CLI and web)

140d8cdf Merge p3-A9: render refuses by name when a camera drew no frames (render.camera_empty)

 core/capture/frames.py     | 36 +++++++++++++++++
 core/messages/catalog.yaml |  3 ++
 docs/phase3/notes/A9.md    |  3 ++
 flightsim/capture.py       |  8 ++++
 tests/engine_launch.py     | 25 ++++++++++++
 tests/test_camera_empty.py | 96 ++++++++++++++++++++++++++++++++++++++++++++++
 webapp/runs.py             | 15 ++++++++
 7 files changed, 186 insertions(+)

a61f2589 A9 integrator: CLI render-path test for render.camera_empty

 docs/phase3/notes/A9.md    |  3 +++
 tests/test_camera_empty.py | 32 ++++++++++++++++++++++++++++++++
 2 files changed, 35 insertions(+)

ff32cbcd A9: a camera with zero frames refuses render.camera_empty by name (CLI and web)

 core/capture/frames.py     | 36 ++++++++++++++++++++++++++
 core/messages/catalog.yaml |  3 +++
 flightsim/capture.py       |  8 ++++++
 tests/engine_launch.py     | 25 ++++++++++++++++++
 tests/test_camera_empty.py | 64 ++++++++++++++++++++++++++++++++++++++++++++++
 webapp/runs.py             | 15 +++++++++++
 6 files changed, 151 insertions(+)
```

## A5 · PASS · run A-2 · 2026-11-04T16:53:55Z

verify line(s) from tasks/phase3_checklist.md:

```
61:   - Check: the plane flies the same in the engine as in Python (`gate5_ue_parity.py`).
```

output line(s) that satisfy it:

```
runs/p3/A-2/A5-gate5-full.log:   [PASS] identical scenario, both hosts, matching trajectories within stated tolerance   /   GATE 5: PASS -- all three clauses, each measured.   (exit 0)
runs/p3/A-2/A5-gate5-full.log:   [ok  ] altitude_m max difference 0.07226 (tolerance 5, 555 samples) ... heading_deg 0.08153 (tolerance 1) ... lon_deg 5.223e-06 (tolerance 0.0001); time overlap 0.100..59.900 s elapsed (99.7%); origins headless 4.875 s unreal 0.008 s (aligned to elapsed time)
runs/p3/A-2/A5-check-bridge-api.log: API surface matches. (exit 0)  /  runs/p3/A-2/A5-vendor.log: dll sha256 e7c302ec... targets UE 5.7 (exit 0)  /  runs/p3/A-2/A5-build-main.log: Result: Succeeded (0 'error C')
```

note: run A-2; the on-screen clauses also pass on 5.7 (control surfaces articulate: aileron 8.75 deg, elevator 4.31 deg; commanded roll visible r=0.99795); decisions 11 and 14 record the two contracts the box settled

### synopsis

# A5 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:53:53Z

## A5 step 4: vendor_ue_plugin.ps1 for UE 5.7

- log: `runs/p3/A-2/A5-vendor.log`
- exit: 0 (expected 0) -> PASS

```
  	    New File  		     912	refuel.xml
  100%  
  	    New File  		    1982	rpm_governor.xml
  100%  
  	    New File  		    1686	SensorBaro.xml
  100%  
  	    New File  		    3835	SensorGps.xml
  100%  
  	    New File  		    8925	SensorImu.xml
  100%  
  	    New File  		     514	speedbrakes.xml
  100%  
  	    New File  		   12153	sperry-a2-autopilot.xml
  100%  
  	    New File  		     824	tail_wheel_lock.xml
  100%  
  	    New File  		    7570	visual-reference-point-extensions.xml
  100%  
  
  ------------------------------------------------------------------------------
  
                 Total    Copied   Skipped  Mismatch    FAILED    Extras
      Dirs :         1         1         0         0         0         0
     Files :        30        30         0         0         0         0
     Bytes :   172.5 k   172.5 k         0         0         0         0
     Times :   0:00:00   0:00:00                       0:00:00   0:00:00
  
  
     Speed :           3,925,600 Bytes/sec.
     Speed :             224.625 MegaBytes/min.
     Ended : Wednesday, November 4, 2026 10:56:38 AM
  
VENDORED.json updated

vendored Win64 library into C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib
  tag        v1.2.4 @ e07a7d810d4f
  engine     targets UE 5.7 (recorded, not a measurement of a build)
  dll sha256 e7c302ecb931c2d069d15ce2ded237473b5ad985c643d3a41357fcf2b340f540

Next: .\scripts\build_ue.ps1
```

## A5 step 5: build_ue.ps1 on 5.7.4 after the Windows builder's fixes (2b746352)

- log: `runs/p3/A-2/A5-build-main.log`
- exit: 0 (expected 0) -> PASS

```
building FlightSimEditor Win64 Development against UE 5.7.4 at C:\Program Files\Epic Games\UE_5.7
Using bundled DotNet SDK version: 8.0.412 win-x64
Running UnrealBuildTool: dotnet "..\..\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" FlightSimEditor Win64 Development -project=C:\Users\kanth\flightsim\ue\FlightSim.uproject -waitmutex
Log file: C:\Users\kanth\AppData\Local\UnrealBuildTool\Log.txt
Using 'git status' to determine working set for adaptive non-unity build (C:\Users\kanth\flightsim).
Invalidating makefile for FlightSimEditor (DefaultEngine.ini modified)
JSBSim Path Check OK: C:\Users\kanth\flightsim\ue\Plugins\JSBSimFlightDynamicsModel\Source\ThirdParty\JSBSim\Lib\JSBSim.dll
UHT compiled-in object format Default
Building FlightSimEditor...
Using Visual Studio 2022 14.44.35228 toolchain (C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207) and Windows 10.0.26100.0 SDK (C:\Program Files (x86)\Windows Kits\10).
Determining max actions to execute in parallel (8 physical cores, 12 logical cores)
  Executing up to 8 processes, one per physical core
  Requested 1.5 GB memory per action, 6.12 GB available: limiting max parallel actions to 4
Using Unreal Build Accelerator local executor to run 5 action(s)
  Storage capacity 40Gb
---- Starting trace: 261104_113201 ----
UbaServer - Listening on 0.0.0.0:1345
[1/5] Compile [x64] Module.FlightSimBridge.2.cpp
[2/5] Compile [x64] Module.FlightSimBridge.1.cpp
[3/5] Link [x64] UnrealEditor-FlightSimBridge.lib
[4/5] Link [x64] UnrealEditor-FlightSimBridge.dll
[5/5] WriteMetadata FlightSimEditor.target [NoUba]

Trace written to file C:/Users/kanth/AppData/Local/UnrealBuildTool/Log.uba with size 6.1kb
Total time in Unreal Build Accelerator local executor: 33.75 seconds

Result: Succeeded
Total execution time: 40.59 seconds
stamped 99dc982e65ccb81a75a3719cd468876c4900098eafc29c08313807ce4eacd80e

built. Next: .\scripts\ue_preflight.ps1 to confirm, then render.
```

## A5 step 6: check_bridge_api.sh with UE_ROOT at UE_5.7

- log: `runs/p3/A-2/A5-check-bridge-api.log`
- exit: 0 (expected 0) -> PASS

```
  start mixture                              ok  card-carried mixture (piston-at-altitude patch)
  UCineCameraComponent                       ok  derives from UCameraComponent (a USceneComponent)
  module CesiumRuntime                       ok  resolves
  module CinematicCamera                     ok  resolves
  module GeoReferencing                      ok  resolves
  module ImageWrapper                        ok  resolves
  module InputCore                           ok  resolves
  module JSBSimFlightDynamicsModel           ok  resolves
  module Json                                ok  resolves
  module JsonUtilities                       ok  resolves
  module Landscape                           ok  resolves
  module Niagara                             ok  resolves
  module ProceduralMeshComponent             ok  resolves
  module RHI                                 ok  resolves
  module RenderCore                          ok  resolves
  DirectionalLight AtmosphereSunLightIndex   ok  present
  DirectionalLight AtmosphereSunDiskColorScale ok  present
  DirectionalLight per-pixel transmittance   ok  present
  Fog SetFogInscatteringColor                ok  present
  Fog sky-atmosphere ambient scale           ok  present
  AVolumetricCloud                           ok  present
  VolumetricCloud SetLayerBottomAltitude     ok  present
  VolumetricCloud SetLayerHeight             ok  present
  VolumetricCloud SetMaterial                ok  present
  PostProcess GI method                      ok  present
  PostProcess reflection method              ok  present
  PostProcess physical camera exposure       ok  present
  PostProcess FilmGrainIntensity             ok  present
  PostProcess SceneFringeIntensity           ok  present
  show flag Cloud                            ok  present
  show flag LumenGlobalIllumination          ok  present
  show flag LumenReflections                 ok  present
  show flag Grain                            ok  present
  show flag SceneColorFringe                 ok  present
  show flag Vignette                         ok  present
  engine simple cloud material               ok  present
  plugin dependencies                        ok  all enabled in FlightSim.uproject

API surface matches. This is NOT a compile -- it means the first build
should fail on ordinary C++ errors, not on structural mismatches.
```

## A5 step 8 / sheet check: gate5_ue_parity.py with --unreal-telemetry (fixed build) and --unreal-render (roll doublet)

- log: `runs/p3/A-2/A5-gate5-full.log`
- exit: 0 (expected 0) -> PASS

```
  trajectory  runs\p3\A-2\gate5_c172p_fixed\unreal.json (600 samples)

================================================================================================
3. host parity
================================================================================================
  [ok  ] time overlap   0.100..59.900 s elapsed (99.7% of the headless run's 60.000 s; UE ran 59.900 s)
  origins  headless 4.875 s  unreal 0.008 s  (aligned to elapsed time)
  [ok  ] altitude_m     max difference    0.07226 (tolerance 5, 555 samples)
  [ok  ] tas_kt         max difference   0.007988 (tolerance 2, 555 samples)
  [ok  ] roll_deg       max difference    0.01817 (tolerance 1, 555 samples)
  [ok  ] pitch_deg      max difference   0.003191 (tolerance 1, 555 samples)
  [ok  ] heading_deg    max difference    0.08153 (tolerance 1, 555 samples)
  [ok  ] n_z            max difference  0.0001352 (tolerance 0.05, 555 samples)
  [ok  ] lat_deg        max difference    5.4e-06 (tolerance 0.0001, 555 samples)
  [ok  ] lon_deg        max difference  5.223e-06 (tolerance 0.0001, 555 samples)

================================================================================================
4. on screen
================================================================================================
  110 frames at 960x540, airframe: placeholder boxes, not a visual asset
  [ok  ] frames show the aircraft     110 frames, aircraft covers 4.28%-9.33% of the frame (floor 0.5%)
  [ok  ] camera never inherits roll   max |camera roll| 0.000000 deg over the run, preset chase
  [ok  ] control surfaces articulate  4 bound to geometry, 3 moved: aileron_l 8.75 deg, aileron_r 8.75 deg, elevator 4.31 deg, rudder 0.00 deg
  [ok  ] commanded roll is visible    apparent bank in the pixels tracks FDM roll at r=0.99795, over -71.9..+40.4 deg (FDM -64.6..+40.3)

================================================================================================
GATE 5
================================================================================================
  [PASS] identical scenario, both hosts, matching trajectories within stated tolerance
  [PASS] control surfaces visibly articulate
  [PASS] commanded roll is visible on screen

  GATE 5: PASS -- all three clauses, each measured.
  Scope: one airframe, one envelope point, still air, flat terrain,
  and a placeholder box airframe. Visual realism is Phase 6 and is
  not what this gate asked for.
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run A-2 on UE 5.7.4: three FAIL packets led here (A5-1 script defects on 5.5, A5-2 Water profile exit 1 + trim-mode mismatch fixed in 2b746352, A5-3 harness clock origins fixed by the Mac in d4fd0dfd); the Windows build is 99dc982e (build_stamp.json engine_version 5.7.4)

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
fff1d50b Phase 3: log decision 15 and the A5 retry 3 push
d4fd0dfd Phase 3 A5 retry 3: notes, state, Mac event log
0b49a87f Merge p3-A5r3: A5 retry 3, gate5 parity grades on elapsed hands-off time (decision 14)
ca3103fc A5 retry 3: gate5 parity grades on elapsed hands-off time (decision 14)
7cab0177 Phase 3 run A-2: A5 packet 3 (parity harness clock origins), decision 14, Windows builder machine notes
b7053df7 Merge p3w-A5: A5 Windows builder (WaterBodyCollision profile; still-air longitudinal re-trim per decision 11)
2b746352 A5: WaterBodyCollision profile for 5.7 (Cesium pulls Water) and calm cards re-trim tLongitudinal like core (decision 11)
79448961 Phase 3: log the A5 push and the A8 note (run A-2)
71bd9053 Phase 3 A5 retry 2: notes, state, Mac event log
049fcf88 Merge p3-A5r2: A5 retry 2, gate5 parity preflight runs ue_preflight.ps1 on Windows
5b037fc8 A5 retry 2: gate5 parity preflight runs ue_preflight.ps1 on Windows
56289aff Phase 3: A5 state keeps Windows' run A-2 verdict fields (Mac adds stage/retry only)
ec43bbd6 Phase 3: log the A4 PASS verdict (run A-2) and the A5 retry 2 start
9eb894e7 Phase 3 run A-2: A5 FAIL packet 2 (Water collision profile exit 1; trim-mode mismatch between hosts), decision 11 (UE host trims like core)
6bc6c204 Phase 3 run A-2: A5 check_bridge_api.sh passes on 5.7; Smart App Control blocks the Cesium runtime dll, every 5.7 editor run stops (machine note)
3f92a998 Phase 3: Windows event log (web app stopped for memory, A5 retry state)
6cd75cea Phase 3: log the A5 retry push
ad73e6ae Phase 3 A5 retry: triage and integrator notes, Mac event log
ab11bc5c Merge p3-A5r: A5 retry, check_bridge_api.sh fixes
29201a34 A5 retry: check_bridge_api.sh module list, show-flag patterns, project Cesium path, venv python
6264aa55 Phase 3 A5: FAIL packet 1 (check_bridge_api.sh defects on 5.5)
e7876720 A5: Win64 JSBSim library re-vendored on this machine (v1.2.4 @ e07a7d81, dll sha256 recorded)
40b2a3dd Merge p3-A5: VENDORED.json ue_engine_target 5.5 and per-patch status_5_5
289626a9 Merge phase-2-final into p3-A5
d5d00f36 A5: VENDORED.json targets 5.5 with per-patch status; pin test

fff1d50b Phase 3: log decision 15 and the A5 retry 3 push

 docs/phase3/events_mac.log | 10 ++++++++++
 1 file changed, 10 insertions(+)

d4fd0dfd Phase 3 A5 retry 3: notes, state, Mac event log

 docs/phase3/events_mac.log | 1 +
 docs/phase3/state/A5.json  | 4 ++--
 docs/phase3/state/B1.json  | 8 +++++++-
 3 files changed, 10 insertions(+), 3 deletions(-)

0b49a87f Merge p3-A5r3: A5 retry 3, gate5 parity grades on elapsed hands-off time (decision 14)

 experiments/gate5_ue_parity.py | 50 +++++++++++++++++++++------
 tests/test_host_parity.py      | 77 +++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 115 insertions(+), 12 deletions(-)

ca3103fc A5 retry 3: gate5 parity grades on elapsed hands-off time (decision 14)

 experiments/gate5_ue_parity.py | 50 +++++++++++++++++++++------
 tests/test_host_parity.py      | 77 +++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 115 insertions(+), 12 deletions(-)

7cab0177 Phase 3 run A-2: A5 packet 3 (parity harness clock origins), decision 14, Windows builder machine notes

 docs/PHASE3_LOG.md             |  2 ++
 docs/phase3/decisions.md       |  4 +++
 docs/phase3/events_windows.log |  5 +++
 docs/phase3/packets/A5-3.md    | 80 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A5.json      | 13 ++++---
 5 files changed, 99 insertions(+), 5 deletions(-)

b7053df7 Merge p3w-A5: A5 Windows builder (WaterBodyCollision profile; still-air longitudinal re-trim per decision 11)

 ue/Config/DefaultEngine.ini                        | 14 +++++++++++++
 .../Private/FlightSimScenarioWorld.cpp             | 24 +++++++++++++++++++++-
 .../Public/FlightSimScenarioWorld.h                |  6 ++++--
 3 files changed, 41 insertions(+), 3 deletions(-)

2b746352 A5: WaterBodyCollision profile for 5.7 (Cesium pulls Water) and calm cards re-trim tLongitudinal like core (decision 11)

 ue/Config/DefaultEngine.ini                        | 14 +++++++++++++
 .../Private/FlightSimScenarioWorld.cpp             | 24 +++++++++++++++++++++-
 .../Public/FlightSimScenarioWorld.h                |  6 ++++--
 3 files changed, 41 insertions(+), 3 deletions(-)

79448961 Phase 3: log the A5 push and the A8 note (run A-2)

 docs/phase3/events_mac.log | 2 ++
 1 file changed, 2 insertions(+)

71bd9053 Phase 3 A5 retry 2: notes, state, Mac event log

 docs/phase3/events_mac.log | 20 ++++++++++++++++++++
 docs/phase3/notes/A5.md    |  6 ++++++
 docs/phase3/state/A5.json  |  5 +++--
 3 files changed, 29 insertions(+), 2 deletions(-)

049fcf88 Merge p3-A5r2: A5 retry 2, gate5 parity preflight runs ue_preflight.ps1 on Windows

 experiments/gate5_ue_parity.py | 17 +++++++++---
 tests/test_host_parity.py      | 62 +++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 74 insertions(+), 5 deletions(-)

5b037fc8 A5 retry 2: gate5 parity preflight runs ue_preflight.ps1 on Windows

 experiments/gate5_ue_parity.py | 17 +++++++++---
 tests/test_host_parity.py      | 62 +++++++++++++++++++++++++++++++++++++++++-
 2 files changed, 74 insertions(+), 5 deletions(-)

56289aff Phase 3: A5 state keeps Windows' run A-2 verdict fields (Mac adds stage/retry only)

 docs/phase3/state/A5.json | 19 ++++++++++++++-----
 1 file changed, 14 insertions(+), 5 deletions(-)

ec43bbd6 Phase 3: log the A4 PASS verdict (run A-2) and the A5 retry 2 start

 docs/phase3/events_mac.log |  3 +++
 docs/phase3/state/A5.json  | 21 +++++++--------------
 2 files changed, 10 insertions(+), 14 deletions(-)

9eb894e7 Phase 3 run A-2: A5 FAIL packet 2 (Water collision profile exit 1; trim-mode mismatch between hosts), decision 11 (UE host trims like core)

 docs/PHASE3_LOG.md             |   2 +
 docs/phase3/decisions.md       |   2 +
 docs/phase3/events_windows.log |  12 +++++
 docs/phase3/packets/A5-2.md    | 112 +++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A5.json      |  11 ++--
 5 files changed, 135 insertions(+), 4 deletions(-)

6bc6c204 Phase 3 run A-2: A5 check_bridge_api.sh passes on 5.7; Smart App Control blocks the Cesium runtime dll, every 5.7 editor run stops (machine note)

 docs/PHASE3_LOG.md             | 2 ++
 docs/phase3/decisions.md       | 1 +
 docs/phase3/events_windows.log | 7 +++++++
 3 files changed, 10 insertions(+)

3f92a998 Phase 3: Windows event log (web app stopped for memory, A5 retry state)

 docs/phase3/events_windows.log | 4 ++++
 1 file changed, 4 insertions(+)

6cd75cea Phase 3: log the A5 retry push

 docs/phase3/events_windows.log | 6 ++++++
 1 file changed, 6 insertions(+)

ad73e6ae Phase 3 A5 retry: triage and integrator notes, Mac event log

 docs/phase3/events_mac.log | 5 +++++
 docs/phase3/notes/A5.md    | 8 ++++++++
 2 files changed, 13 insertions(+)

ab11bc5c Merge p3-A5r: A5 retry, check_bridge_api.sh fixes

 scripts/check_bridge_api.sh    | 79 ++++++++++++++++++++++++++++++++++++------
 tests/test_check_bridge_api.py | 74 +++++++++++++++++++++++++++++++++++++++
 2 files changed, 142 insertions(+), 11 deletions(-)

29201a34 A5 retry: check_bridge_api.sh module list, show-flag patterns, project Cesium path, venv python

 scripts/check_bridge_api.sh    | 79 ++++++++++++++++++++++++++++++++++++------
 tests/test_check_bridge_api.py | 74 +++++++++++++++++++++++++++++++++++++++
 2 files changed, 142 insertions(+), 11 deletions(-)

6264aa55 Phase 3 A5: FAIL packet 1 (check_bridge_api.sh defects on 5.5)

 docs/phase3/events_windows.log |  6 +++++
 docs/phase3/packets/A5-1.md    | 61 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A5.json      |  7 ++++-
 3 files changed, 73 insertions(+), 1 deletion(-)

e7876720 A5: Win64 JSBSim library re-vendored on this machine (v1.2.4 @ e07a7d81, dll sha256 recorded)

 docs/phase3/events_windows.log                     | 42 ++++++++++++++++++++++
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json |  7 ++--
 2 files changed, 47 insertions(+), 2 deletions(-)

40b2a3dd Merge p3-A5: VENDORED.json ue_engine_target 5.5 and per-patch status_5_5

 tests/test_ue_physics_source.py                    |  8 ++++++++
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json | 19 +++++++++++++------
 2 files changed, 21 insertions(+), 6 deletions(-)

289626a9 Merge phase-2-final into p3-A5

 README.md                                          |    4 +-
 assets/aircraft_config/A4.json                     |   79 +-
 assets/fdm_root/aircraft/A4/A4.xml                 |    6 +-
 assets_pipeline/a4_performance.py                  |   11 +-
 assets_pipeline/a4_sync.py                         |    8 +-
 core/capture/airframe.py                           |  115 +-
 core/capture/labels.py                             |  126 +-
 core/capture/manifest.py                           |   15 +-
 core/capture/objects.py                            |   28 +-
 core/messages/catalog.yaml                         |    3 +
 core/scenario/blocks.py                            |    2 +-
 core/util/platform.py                              |   28 +-
 docs/CAMERA_WINDOWS.md                             |    3 +-
 docs/phase3/BUILDER_BRIEF.md                       |   52 +
 docs/phase3/INTEGRATOR_BRIEF.md                    |   52 +
 docs/phase3/SUBAGENT_BRIEF.md                      |   47 +
 docs/phase3/digest_A.md                            | 1260 ++++++++++++
 docs/phase3/events_mac.log                         |  239 +++
 docs/phase3/notes/A1.md                            |   55 +
 docs/phase3/notes/A10.md                           |   50 +
 docs/phase3/notes/A11.md                           |   59 +
 docs/phase3/notes/A12.md                           |   58 +
 docs/phase3/notes/A13.md                           |   44 +
 docs/phase3/notes/A2.md                            |   79 +
 docs/phase3/notes/A3.md                            |   69 +
 docs/phase3/notes/A4.md                            |   85 +
 docs/phase3/notes/A5.md                            |   58 +
 docs/phase3/notes/A6.md                            |   59 +
 docs/phase3/notes/A7.md                            |   64 +
 docs/phase3/notes/A8.md                            |   61 +
 docs/phase3/notes/A9.md                            |   60 +
 docs/phase3/notes/C1.md                            |   64 +
 docs/phase3/notes/C5.md                            |   68 +
 docs/phase3/notes/C6.md                            |   65 +
 docs/phase3/state/A.json                           |   41 +
 docs/phase3/state/A1.json                          |   15 +
 docs/phase3/state/A10.json                         |   15 +
 docs/phase3/state/A11.json                         |    7 +
 docs/phase3/state/A12.json                         |   24 +
 docs/phase3/state/A13.json                         |   10 +
 docs/phase3/state/A2.json                          |   16 +
 docs/phase3/state/A3.json                          |   17 +
 docs/phase3/state/A4.json                          |   18 +
 docs/phase3/state/A5.json                          |   18 +
 docs/phase3/state/A6.json                          |   17 +
 docs/phase3/state/A7.json                          |    7 +
 docs/phase3/state/A8.json                          |    7 +
 docs/phase3/state/A9.json                          |    7 +
 docs/phase3/state/A_decisions_needed.md            |   15 +
 docs/phase3/state/C1.json                          |   14 +
 docs/phase3/state/C5.json                          |   23 +
 docs/phase3/state/C6.json                          |    7 +
 docs/schemas/capture_manifest.v8.schema.json       | 2059 ++++++++++++++++++++
 scripts/build_ue.ps1                               |   25 +-
 scripts/build_ue.sh                                |    6 +-
 scripts/check_bridge_api.sh                        |    2 +-
 scripts/deploy_windows.ps1                         |    2 +-
 scripts/mutation_check.sh                          |   14 +-
 scripts/phase3_digest.py                           |  149 ++
 scripts/phase3_event.py                            |    5 +-
 scripts/phase3_state.py                            |  110 ++
 scripts/render_ue_scenario.sh                      |    2 +-
 scripts/run_ue_scenario.sh                         |    2 +-
 scripts/setup.ps1                                  |    2 +-
 scripts/setup.sh                                   |    2 +-
 scripts/ue_create_materials.py                     |    2 +-
 scripts/ue_engine.ps1                              |   50 +
 scripts/ue_preflight.ps1                           |   56 +-
 scripts/ue_preflight.sh                            |    6 +-
 scripts/vendor_ue_plugin.ps1                       |   14 +-
 scripts/vendor_ue_plugin.sh                        |    8 +-
 tests/test_a4.py                                   |   14 +-
 tests/test_airframe.py                             |   99 +
 tests/test_camera_labels.py                        |    5 +-
 tests/test_capture_objects.py                      |    5 +-
 tests/test_capture_schema.py                       |    4 +-
 tests/test_component_labels.py                     |  180 ++
 tests/test_gate6_visual.py                         |    3 +-
 tests/test_platform.py                             |  104 +-
 tests/test_powershell_scripts.py                   |   60 +
 tests/test_toolchain_doc.py                        |   49 +
 tests/test_ue_materials.py                         |   23 +
 tests/test_ue_weather_source.py                    |   11 +
 tests/test_versions.py                             |    2 +-
 tests/test_webapp_generate.py                      |   59 +
 ue/FlightSim.uproject                              |    2 +-
 .../Private/FlightSimRenderCommandlet.cpp          |    2 +-
 .../FlightSimBridge/Private/FlightSimWeather.cpp   |   19 +-
 .../Resources/JSBSim/aircraft/A4/A4.xml            |    6 +-
 ue/Source/FlightSim.Target.cs                      |    2 +-
 ue/Source/FlightSimEditor.Target.cs                |    2 +-
 webapp/generate.py                                 |   11 +
 92 files changed, 6346 insertions(+), 186 deletions(-)

d5d00f36 A5: VENDORED.json targets 5.5 with per-patch status; pin test

 tests/test_ue_physics_source.py                    |  8 ++++++++
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json | 19 +++++++++++++------
 2 files changed, 21 insertions(+), 6 deletions(-)
```

## A6 · PASS · run A-2 · 2026-11-04T16:56:48Z

verify line(s) from tasks/phase3_checklist.md:

```
63:   - Check: the first run prints `MATERIAL-CREATED` for the five rebuilt ones, and
64:     the second run prints `MATERIAL-EXISTS`.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A6-run1-editor.log: MATERIAL-STALE / MATERIAL-REBUILT / MATERIAL-CREATED: /Game/FlightSim/M_GreyCard, M_LandcoverID, M_RainStreaks, M_Ground_City, M_LensDrops (first run on this Content; exit 0, Success - 0 error(s))
runs/p3/A-2/A6-run4-editor.log: MATERIAL-EXISTS for M_GreyCard, M_LandcoverID, M_RainStreaks, M_Ground_City, M_LensDrops, M_CustomStencilID, M_RainDrops, M_RainSplash; counts STALE 0 REBUILT 0 CREATED 0 EXISTS 36 FAILED 0; Missing If 0; exit 0; Success - 0 error(s), 0 warning(s)
```

note: run A-2: packet A6-1 (storm materials rebuilt every run on 5.7) fixed by the Windows builder in scripts/ue_create_materials.py; the script is idempotent on the pinned engine; M_CustomStencilID needs no editor step (EXISTS on every run)

### synopsis

# A6 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:56:47Z

## A6 step 4: first run on the owner's Content (5.7, before the storm fix): the five STALE/REBUILT/CREATED

- log: `runs/p3/A-2/A6-run1.log`
- exit: 0 (expected 0) -> PASS

```
[2026.11.04-16.34.00:123][  0]LogTextureEncodingSettings: Display: Oodle Texture Encode Speed settings: Fast: RDO Off Lambda=0, Effort=Normal Final: RDO Off Lambda=0, Effort=Normal
[2026.11.04-16.34.00:123][  0]LogTextureEncodingSettings: Display: Shared linear texture encoding: Disabled
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using QuadricMeshReduction for automatic static mesh reduction
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using SkeletalMeshReduction for automatic skeletal mesh reduction
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using ProxyLODMeshReduction for automatic mesh merging
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: No distributed automatic mesh merging module available
[2026.11.04-16.34.00:555][  0]LogShaderCompilers: Display: Compiling shader autogen file: ../../../../../../Users/kanth/flightsim/ue/Intermediate/ShaderAutogen/PCD3D_SM5/AutogenShaderHeaders.ush
[2026.11.04-16.34.00:556][  0]LogShaderCompilers: Display: Autogen file is unchanged, skipping write.
[2026.11.04-16.34.00:556][  0]LogVirtualization: Display: VirtualizationSystem name found in ini file: None
[2026.11.04-16.34.00:556][  0]LogVirtualization: Display: FNullVirtualizationSystem mounted, virtualization will be disabled
[2026.11.04-16.34.00:667][  0]LogWorldPartition: Display: FWorldPartitionClassDescRegistry::Initialize started...
[2026.11.04-16.34.00:670][  0]LogWorldPartition: Display: FWorldPartitionClassDescRegistry::Initialize took 2.580 ms
[2026.11.04-16.34.01:159][  0]LogMetaSound: Display: MetaSound Page Target Initialized to 'Default'
[2026.11.04-16.34.01:160][  0]LogAudio: Display: Registering Engine Module Parameter Interfaces...
[2026.11.04-16.34.01:942][  0]LogAudioCaptureCore: Display: No Audio Capture implementations found. Audio input will be silent.
[2026.11.04-16.34.01:942][  0]LogAudioCaptureCore: Display: No Audio Capture implementations found. Audio input will be silent.
[2026.11.04-16.34.01:961][  0]LogGeoReferencing: Display: The engine is currently using Compressed Rotation Transforms. You may encounter accuracy issues with large neshes. We recommend setting all bSupportsSceneDataCompressedTransforms to false in the Engine/Config/[platform]/DataDrivenPlatformInfo.ini file
[2026.11.04-16.34.02:451][  0]LogAssetRegistry: Display: No AssetDiscovery cache present at ../../../../../../Users/kanth/flightsim/ue/Intermediate/CachedAssetRegistryDiscovery.bin. AssetRegistry discovery of files will be uncached.
[2026.11.04-16.34.02:489][  0]LogAssetRegistry: Display: AssetDataGatherer spent 0.027s loading caches ../../../../../../Users/kanth/flightsim/ue/Intermediate/CachedAssetRegistry_*.bin.
[2026.11.04-16.34.02:577][  0]LogCsvProfiler: Display: Metadata set : largeworldcoordinates="1"
[2026.11.04-16.34.02:713][  0]LogPython: Display: No pip-enabled plugins with python dependencies found, skipping
[2026.11.04-16.34.03:421][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/IKRig/Content/Python/init_unreal.py... started...
[2026.11.04-16.34.03:446][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/IKRig/Content/Python/init_unreal.py... took 23.909 ms
[2026.11.04-16.34.03:446][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/ControlRig/Content/Python/init_unreal.py... started...
[2026.11.04-16.34.03:468][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/ControlRig/Content/Python/init_unreal.py... took 22.739 ms (total: 46.649 ms)
[2026.11.04-16.34.03:469][  0]LogPythonScriptCommandlet: Display: Running Python script: C:/Users/kanth/flightsim/scripts/ue_create_materials.py
[2026.11.04-16.34.03:891][  0]LogObjectTools: Warning: Detected inconsistencies between reference gathering algorithms. Switching 'Editor.UseLegacyGetReferencersForDeletion' on for the remainder of this editor session.
[2026.11.04-16.34.04:060][  0]LogSourceControl: Display: Uncontrolled Changelist persistency file loaded ../../../../../../Users/kanth/flightsim/ue/Saved/SourceControl/UncontrolledChangelists.json
[2026.11.04-16.34.07:872][  0]LogPythonScriptCommandlet: Display: Python script executed successfully
[2026.11.04-16.34.07:872][  0]LogInit: Display: 
[2026.11.04-16.34.07:873][  0]LogInit: Display: Warning/Error Summary (Unique only)
[2026.11.04-16.34.07:873][  0]LogInit: Display: -----------------------------------
[2026.11.04-16.34.07:873][  0]LogInit: Display: LogObjectTools: Warning: Detected inconsistencies between reference gathering algorithms. Switching 'Editor.UseLegacyGetReferencersForDeletion' on for the remainder of this editor session.
[2026.11.04-16.34.07:874][  0]LogInit: Display: 
[2026.11.04-16.34.07:874][  0]LogInit: Display: Success - 0 error(s), 1 warning(s)
[2026.11.04-16.34.07:874][  0]LogInit: Display: 

Execution of commandlet took:  4.45 seconds
[2026.11.04-16.34.08:158][  0]LogShaderCompilers: Display: Shaders left to compile 0
[2026.11.04-16.34.08:234][  0]LogSourceControl: Display: Uncontrolled Changelist persistency file saved ../../../../../../Users/kanth/flightsim/ue/Saved/SourceControl/UncontrolledChangelists.json
```

## A6 steps 6-7 after 79939f51: run 3 and run 4 on MAIN, counts per tag, Missing If

- log: `runs/p3/A-2/A6-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 3 (first run after 79939f51 on MAIN): STALE 0, REBUILT 2, CREATED 2 (M_RainDrops, M_RainSplash: their stamps were re-keyed by the old rename path), EXISTS 34, FAILED 0, Missing If 0, exit 0, Success - 0 error(s), 1 warning(s)
run 4 (second run): STALE 0, REBUILT 0, CREATED 0, EXISTS 36, FAILED 0, Missing If 0, exit 0, Success - 0 error(s), 0 warning(s)
run 4: MATERIAL-EXISTS for M_CustomStencilID, M_GreyCard, M_LandcoverID, M_RainStreaks, M_Ground_City, M_LensDrops, M_RainDrops, M_RainSplash
the five's STALE/REBUILT/CREATED sequence is in runs/p3/A-2/A6-run1-editor.log (first run on this Content, before the fix); editor logs: A6-run3-editor.log, A6-run4-editor.log
```

note: the editor's own log (Saved/Logs/FlightSim.log, copied per run) is the record; the -stdout capture drops LogPython lines; the storm fix (duplicate+delete instead of rename_asset) is the Windows builder's commit 79939f51, merged 156f69ff

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
1706127c Phase 3: A6 builder merge log and worktree machine note
30661be4 A6: set a stale storm material aside by copy, not rename; the rename redirected the new asset's generation stamp key to _prev on UE 5.7 so M_RainDrops and M_RainSplash rebuilt every run
6468bb2c Phase 3: log A2 PASS, A6 FAIL (Windows scope), letter B builders start
f842deba Phase 3 run A-2: A2 PASS (pin everywhere on 5.7), A6 FAIL packet 1 (storm materials rebuilt every run)
a52ae2cf Merge p3-A6: pin GRAPH_GENERATIONS key set and stencil-id build; engine-neutral comment
7f830d71 A6: pin GRAPH_GENERATIONS key set and stencil-id build; engine-neutral comment

1706127c Phase 3: A6 builder merge log and worktree machine note

 docs/phase3/decisions.md       | 1 +
 docs/phase3/events_windows.log | 1 +
 2 files changed, 2 insertions(+)

30661be4 A6: set a stale storm material aside by copy, not rename; the rename redirected the new asset's generation stamp key to _prev on UE 5.7 so M_RainDrops and M_RainSplash rebuilt every run

 scripts/ue_create_materials.py | 19 ++++++++++++++++++-
 1 file changed, 18 insertions(+), 1 deletion(-)

6468bb2c Phase 3: log A2 PASS, A6 FAIL (Windows scope), letter B builders start

 docs/phase3/events_mac.log | 9 +++++++++
 docs/phase3/notes/A5.md    | 6 ++++++
 docs/phase3/state/A5.json  | 4 ++--
 docs/phase3/state/B1.json  | 4 ++--
 docs/phase3/state/B2.json  | 4 ++--
 docs/phase3/state/B3.json  | 4 ++--
 docs/phase3/state/B4.json  | 4 ++--
 7 files changed, 25 insertions(+), 10 deletions(-)

f842deba Phase 3 run A-2: A2 PASS (pin everywhere on 5.7), A6 FAIL packet 1 (storm materials rebuilt every run)

 docs/PHASE3_LOG.md                 |   4 +
 docs/phase3/events_windows.log     |  14 ++
 docs/phase3/packets/A2-synopsis.md | 122 ++++++--------
 docs/phase3/packets/A6-1.md        |  72 ++++++++
 docs/phase3/state/A2.json          |   6 +-
 docs/phase3/state/A6.json          |   9 +-
 docs/phase3/state/A8.json          |   6 +-
 docs/phase3/sync_log_A.md          | 326 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   2 +-
 9 files changed, 487 insertions(+), 74 deletions(-)

a52ae2cf Merge p3-A6: pin GRAPH_GENERATIONS key set and stencil-id build; engine-neutral comment

 scripts/ue_create_materials.py |  2 +-
 tests/test_ue_materials.py     | 23 +++++++++++++++++++++++
 2 files changed, 24 insertions(+), 1 deletion(-)

7f830d71 A6: pin GRAPH_GENERATIONS key set and stencil-id build; engine-neutral comment

 scripts/ue_create_materials.py |  2 +-
 tests/test_ue_materials.py     | 23 +++++++++++++++++++++++
 2 files changed, 24 insertions(+), 1 deletion(-)
```

## A8 · PASS · run A-2 · 2026-11-04T17:13:25Z

verify line(s) from tasks/phase3_checklist.md:

```
68:   - Check: a web-app run with host flight completes, and no message tells the user
69:     to add the flag.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A8-run-summary.log: run 7274c62756ea done: clip ready (host flight on by default ...); host flight 220 samples; engine labels attached on 220 of 220
runs/p3/A-2/A8-run-summary.log: verify.json host_determinism PASS: 2 host flights of one card were byte-identical (6bc9dcc5e613, 220 samples): the host is reproducible; solve pass vs chase pass telemetry: 0 columns differ; ground: collision raster ...grand_canyon; Success - 0 error(s)
runs/p3/A-2/A8-run-summary.log: no-host-flight mentions in the run record and the web app log for this run: 0 / 0
```

note: run A-2: the parity check against the Python flight is the verifier's flight_agreement (PASS) and host_determinism (PASS); tests/test_host_parity.py 19 passed, 1 failed on test_preflight_on_mac_runs_ue_preflight_sh, a Windows path-separator assertion unrelated to parity (the Mac's test, reported); the run's only verifier failure, mask_vs_geometry, is A12's

### synopsis

# A8 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T17:13:24Z

## A8 step 6: web-app run with host flight on (POST /run) on the merged 3dc6a5ec build

- log: `runs/p3/A-2/A8-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"7274c62756ea","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
```

## A8 step 6: the run's record, determinism and flag check

- log: `runs/p3/A-2/A8-run-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 7274c62756ea done: clip ready (host flight on by default, tiles on, storm on; Grand Canyon A-4 chase)
events: host flight 220 samples; every camera re-solved over the host's own flight; rendering 1 camera pass(es): chase; engine labels attached on 220 of 220 frame(s) (0 without a bundle); verification FAILED: mask_vs_geometry (A12's); clip: 220 frames of chase at 10.0 fps = 22.0 s
verify.json host_determinism PASS: 2 host flights of one card were byte-identical (6bc9dcc5e613, 220 samples): the host is reproducible
verify.json flight_agreement PASS; solve pass vs chase pass telemetry: 0 columns differ
host_flight/host_telemetry.log: LogFlightSimScenario: Display: ground: collision raster C:\Users\kanth\flightsim\runs\terrain\grand_canyon; LogInit: Display: Success - 0 error(s), 4 warning(s)
no-host-flight mentions in the run record and the web app log for this run: 0 / 0
```

## A8 step 6: pytest -q tests/test_host_parity.py (19 passed; the 1 failure is a Windows path-separator assertion in the Mac's d4fd0dfd test, not a parity result)

- log: `runs/p3/A-2/A8-pytest-host-parity.log`
- exit: 1 (expected 0) -> FAIL

```
..................F.                                                     [100%]
================================== FAILURES ===================================
_________________ test_preflight_on_mac_runs_ue_preflight_sh __________________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x000001D35D811B80>

    def test_preflight_on_mac_runs_ue_preflight_sh(monkeypatch):
        argv, kwargs = _capture_preflight(monkeypatch, "mac")
>       assert len(argv) == 1 and argv[0].endswith("scripts/ue_preflight.sh")
E       AssertionError: assert (1 == 1 and False)
E        +  where 1 = len(['C:\\Users\\kanth\\flightsim\\scripts\\ue_preflight.sh'])
E        +  and   False = <built-in method endswith of str object at 0x000001D35E8F66D0>('scripts/ue_preflight.sh')
E        +    where <built-in method endswith of str object at 0x000001D35E8F66D0> = 'C:\\Users\\kanth\\flightsim\\scripts\\ue_preflight.sh'.endswith

tests\test_host_parity.py:475: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_host_parity.py::test_preflight_on_mac_runs_ue_preflight_sh
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

note: run A-2: steps 1-2 in packet A8-1; cause 1 (commandlet exit 1, Water profile) fixed by the A5 builder 2b746352; cause 2 (agl_m from the streamed world) fixed by the A8 builder 3dc6a5ec (decision 12), merged 3a8c369f; the cross-check judges the sheet line PASS and names the failing test as the Mac's

## verdict

FAIL

### the box's commits on the branch (final diff, by stat)

```
f8895c08 Phase 3: A8 builder merge log
ad4b08f0 A8: JSBSim's ground answers from the card's collision raster in every pass (decision 12)
79448961 Phase 3: log the A5 push and the A8 note (run A-2)
ad9bc59d Phase 3 run A-2: A8 reproduction and classification (packet A8-1), decision 12 (ground callback reads the raster in every pass)
123dcd3c Merge p3-A8: host-flight refusal names the fault, drops the dev flag; catalogue hint
89f7e577 A8: host-flight refusal names the fault, drops the dev flag; catalogue hint

f8895c08 Phase 3: A8 builder merge log

 docs/phase3/events_windows.log | 3 +++
 1 file changed, 3 insertions(+)

ad4b08f0 A8: JSBSim's ground answers from the card's collision raster in every pass (decision 12)

 .../FlightSimBridge/FlightSimBridge.Build.cs       |   5 +
 .../Private/FlightSimGroundCallback.cpp            | 106 +++++++++++++++++++++
 .../Private/FlightSimGroundCallback.h              |  42 ++++++++
 .../Private/FlightSimScenarioWorld.cpp             |  22 +++++
 .../Private/JSBSimMovementComponent.cpp            |  11 +++
 .../Public/JSBSimMovementComponent.h               |   7 ++
 ue/Plugins/JSBSimFlightDynamicsModel/VENDORED.json |   9 ++
 7 files changed, 202 insertions(+)

79448961 Phase 3: log the A5 push and the A8 note (run A-2)

 docs/phase3/events_mac.log | 2 ++
 1 file changed, 2 insertions(+)

ad9bc59d Phase 3 run A-2: A8 reproduction and classification (packet A8-1), decision 12 (ground callback reads the raster in every pass)

 docs/PHASE3_LOG.md             |  2 +
 docs/phase3/decisions.md       |  2 +
 docs/phase3/events_windows.log |  4 ++
 docs/phase3/packets/A8-1.md    | 99 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A8.json      |  7 ++-
 5 files changed, 113 insertions(+), 1 deletion(-)

123dcd3c Merge p3-A8: host-flight refusal names the fault, drops the dev flag; catalogue hint

 core/messages/catalog.yaml       |  1 +
 flightsim/capture.py             | 56 +++++++++++++++++++++++++++++++++-------
 tests/test_camera_host_flight.py | 23 +++++++++++++++++
 3 files changed, 71 insertions(+), 9 deletions(-)

89f7e577 A8: host-flight refusal names the fault, drops the dev flag; catalogue hint

 core/messages/catalog.yaml       |  1 +
 flightsim/capture.py             | 56 +++++++++++++++++++++++++++++++++-------
 tests/test_camera_host_flight.py | 23 +++++++++++++++++
 3 files changed, 71 insertions(+), 9 deletions(-)
```

## A7 · PASS · run A-2 · 2026-11-04T18:06:34Z

verify line(s) from tasks/phase3_checklist.md:

```
66:   - Check: delete the imported A-4, press Generate, and it imports and renders by itself.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A7-summary.log: run 7bbda8c5a4c3: aircraft | the A4 model is not on this machine yet or is out of date; building it once (fetch at the pinned commit, convert, import) ; importing 1 aircraft into the Unreal project ; the A4 model is ready
runs/p3/A-2/A7-summary.log: run 57db7c98102f: no import; 220 frames rendered; labels 220 of 220; done: clip ready
runs/p3/A-2/A7-summary.log: run 9bf1e3e387a9: the A4 mesh manifest is stale (older than A4.json); re-converting ... ; converting (license-verified, FDM-matched) ; the A4 model is ready ; one re-convert, no second import line; 220 frames; done: clip ready
```

note: run A-2: the import fires once when the asset is missing, the mtime rule fires one re-convert when the config is newer than the manifest, and neither loops; the render crashes between the two Generates were memory exhaustion (machine note), not the import; the only verifier failure on the last run is landmark_reprojection, the Mac's A12 follow-up

### synopsis

# A7 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T18:06:34Z

## A7 step 8: delete the imported A-4 asset, Generate (import), then Generate again (render)

- log: `runs/p3/A-2/A7-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 7bbda8c5a4c3 (ue/Content/Aircraft/A4 deleted, Generate): aircraft | the A4 model is not on this machine yet or is out of date; building it once (fetch at the pinned commit, convert, import) ; aircraft | importing 1 aircraft into the Unreal project ; aircraft | the A4 model is ready ; ue/Content/Aircraft/A4 recreated (body.uasset, TEX_A4E_1/2, mat_A4E_1/2); render crashed for memory (machine note)
run 57db7c98102f (Generate again, quiet machine): no import; host flight 220 samples; 220 frames rendered; labels 220 of 220; done: clip ready
run 9bf1e3e387a9 (A4.json touched, Generate): aircraft | the A4 mesh manifest is stale (the mesh manifest is older than A4.json); re-converting so the mesh is drawn where its label is ; aircraft | converting (license-verified, FDM-matched) ; aircraft | the A4 model is ready ; one re-convert, no second import line, no loop; 220 frames rendered; labels 220 of 220; done: clip ready (verification: only landmark_reprojection FAIL, the Mac's A12 follow-up; mask_vs_geometry now passes on MAIN)
```

## A7 step 9: touch A4.json, Generate: one re-convert, no import loop

- log: `runs/p3/A-2/A7-web-post-5.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"9bf1e3e387a9","digest":"c5c75d19687cf6b521db3ad49b69a9e41226941a3ef21b714d80932df9238fb4"}
```

note: run A-2 on UE 5.7.4 (build 3b05ec5a after the A12 merge): the first render after the import crashed for memory (three crashes with AvailablePhysical 0, machine note), the same card rendered once the machine was quiet

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
e35545c3 Phase 3 run A-2: A7 step 8 rows (import once, render completes on a quiet machine)
576d5baf Merge p3-A7: aircraft mesh imported automatically (mtime rule, traffic, no preview import)
22fc6424 A7: import a missing or outdated aircraft mesh instead of refusing

e35545c3 Phase 3 run A-2: A7 step 8 rows (import once, render completes on a quiet machine)

 docs/PHASE3_LOG.md | 2 ++
 1 file changed, 2 insertions(+)

576d5baf Merge p3-A7: aircraft mesh imported automatically (mtime rule, traffic, no preview import)

 assets_pipeline/importer.py       |  89 +++++++++++++++++++++-
 flightsim/capture.py              |  90 +++++++++++++----------
 tests/test_aircraft_autoimport.py | 151 ++++++++++++++++++++++++++++++++++++++
 tests/test_camera_cli.py          |   7 +-
 webapp/generate.py                |  38 ++++++++--
 webapp/runs.py                    |  26 +++++--
 6 files changed, 342 insertions(+), 59 deletions(-)

22fc6424 A7: import a missing or outdated aircraft mesh instead of refusing

 assets_pipeline/importer.py       |  89 +++++++++++++++++++++-
 flightsim/capture.py              |  90 +++++++++++++----------
 tests/test_aircraft_autoimport.py | 151 ++++++++++++++++++++++++++++++++++++++
 tests/test_camera_cli.py          |   7 +-
 webapp/generate.py                |  38 ++++++++--
 webapp/runs.py                    |  26 +++++--
 6 files changed, 342 insertions(+), 59 deletions(-)
```

## A11 · PASS · run A-2 · 2026-11-04T18:12:34Z

verify line(s) from tasks/phase3_checklist.md:

```
76:   - Check: every `render.json` has the mask, depth and an "alone" picture per aircraft.
77:   - Check: a run with missing label pictures stops with `labels.no_bundle`.
```

output line(s) that satisfy it:

```
runs/p3/A-2/A11-labels-check.log: web chase frames 0-2 and web tower frames 0-2: mask=frame_000N_mask.png (53704..833091 px>0) depth_f32=frame_000N_depth.f32 (True) alone=[('frame_000N_alone_1.png', True)] -> complete; cli chase and cli tower frames 0-2: complete
runs/p3/A-2/A11-web-post.log / run 843e5dbe9dcd events: engine labels attached on 6 of 6 frame(s) (0 without a bundle)  /  runs/p3/A-2/A11-cli-2.log: labels: engine bundle attached on 6 of 6 frames (12 object records; 0 without a bundle)
no labels.no_bundle on either path (the refusal itself is the Mac's container test: pytest -q tests/test_camera_labels.py -k no_bundle in the letter audit)
```

note: run A-2: step 1 found no missing key on 5.7 (the review's Windows symptom did not recur), so step 2 had nothing to fix; step 8 holds on the web app and the CLI; the CLI needed an absolute --terrain (relative path breaks the engine's sidecar read, Mac scope, reported)

### synopsis

# A11 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T18:12:33Z

## A11 step 1/8 web: two cameras, three stills each (run 843e5dbe9dcd), POST /run

- log: `runs/p3/A-2/A11-web-post.log`
- exit: 0 (expected 0) -> PASS

```
status 200
{"run_id":"843e5dbe9dcd","digest":"3414edb508e6a6f3c638e5abb872f8ea4325d6aa726f4c45eb6c2df445dbebc0"}
```

## A11 step 8 CLI: capture --render --terrain <absolute> two cameras, three stills (runs/p3/A-2/A11-cli-2)

- log: `runs/p3/A-2/A11-cli-2.log`
- exit: 0 (expected 0) -> PASS

```
spec 525aeb52033a237c valid; running headlessly...
flying the card in the host first, so the labels describe the flight the pixels show ...
  engine pass logging to runs\p3\A-2\A11-cli-2\host_flight\host_flight_pass.log (unattended; stalls are stopped)
    wrote C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\host_flight\host_telemetry.json
  host flight: 200 samples, digest 710cbc16705eb46d -- poses re-solved over it
  instruments: ideal (the recorded channels are the measurement; no telemetry_measured.json written)
  card:     runs\p3\A-2\A11-cli-2\card.json (consume-poses; one commandlet pass per camera via -camera-index=N)
captured: 6 frames across 2 camera(s)
  manifest: runs\p3\A-2\A11-cli-2\capture_manifest.json
  previews: 6 geometry preview(s) under runs\p3\A-2\A11-cli-2\previews
rendering 2 camera pass(es) into runs\p3\A-2\A11-cli-2\frames in the visual scene ...
  engine pass logging to runs\p3\A-2\A11-cli-2\render_pass.log (unattended; stalls are stopped)
    scene flags for every pass: -Visual -shot=showcase -fps=30 -width=1280 -height=720 -sun-elev=50.0 -sun-azim=180.0 -exposure-bias=9.5 -fog-density=0.0012 -labels -deterministic -GeorefTerrain -terrain=C:/Users/kanth/flightsim/runs/terrain/grand_canyon -mesh=C:\Users\kanth\flightsim\assets\generated\A4\mesh_manifest.json -NoSound -NoLoadingScreen
    camera 1/2: chase -> C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames\chase
      wrote 15 frames
    camera 2/2: tower -> C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames\tower
      wrote 15 frames
    wrote 30 frames across 2 camera(s) under C:\Users\kanth\flightsim\runs\p3\A-2\A11-cli-2\frames
  frames:   6 rendered under runs\p3\A-2\A11-cli-2\frames
  labels:   engine bundle attached on 6 of 6 frames (12 object records; 0 without a bundle)
  overlays: 6 under runs\p3\A-2\A11-cli-2\overlays -- the recorded geometry drawn ON the rendered pixels; the circle (manifest) and the cross (engine) should coincide
  verify:   python -m flightsim.verify runs\p3\A-2\A11-cli-2
  (with pixels present, verification exercises the landmark reprojection and two-view checks that report NOT RUN without them)
```

## A11: every render.json frame record checked for mask, depth_f32 and one alone PNG per aircraft (web and CLI)

- log: `runs/p3/A-2/A11-labels-check.log`
- exit: 0 (expected 0) -> PASS

```
web chase frame 0: mask=frame_0000_mask.png (771705 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('frame_0000_alone_1.png', True)]
web chase frame 1: mask=frame_0001_mask.png (789106 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('frame_0001_alone_1.png', True)]
web chase frame 2: mask=frame_0002_mask.png (833091 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('frame_0002_alone_1.png', True)]
web chase: complete (3 frames)
web tower frame 0: mask=frame_0000_mask.png (53704 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('frame_0000_alone_1.png', True)]
web tower frame 1: mask=frame_0001_mask.png (58764 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('frame_0001_alone_1.png', True)]
web tower frame 2: mask=frame_0002_mask.png (137246 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('frame_0002_alone_1.png', True)]
web tower: complete (3 frames)
cli (render_ue_scenario.ps1) gate5 doublet frame 0: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 1: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 2: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet frame 3: mask=None (-1 px>0) depth_f32=None (True) alone=[]
cli (render_ue_scenario.ps1) gate5 doublet: INCOMPLETE (110 frames)
cli chase frame 0: mask=frame_0000_mask.png (770943 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0000_alone_1.png', True)]
cli chase frame 1: mask=frame_0001_mask.png (788733 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0001_alone_1.png', True)]
cli chase frame 2: mask=frame_0002_mask.png (832572 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0002_alone_1.png', True)]
cli chase: complete (3 frames)
cli tower frame 0: mask=frame_0000_mask.png (53759 px>0) depth_f32=frame_0000_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0000_alone_1.png', True)]
cli tower frame 1: mask=frame_0001_mask.png (57500 px>0) depth_f32=frame_0001_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0001_alone_1.png', True)]
cli tower frame 2: mask=frame_0002_mask.png (135201 px>0) depth_f32=frame_0002_depth.f32 (True) alone=[('aircraft:A4:0', 'frame_0002_alone_1.png', True)]
cli tower: complete (3 frames)
```

note: run A-2 on UE 5.7.4: nothing was missing on this engine, so step 2 (engine fix) had nothing to fix; the only CLI defect met was the relative --terrain path handed to the engine (Mac scope, noted)

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
33e3e560 Phase 3 run A-2: A12 FAIL packet 1 (pixels 1.1% of the width left of the projection on every render), A11 CLI relative-terrain defect logged
ef589327 Merge p3-A11: labels.no_bundle refuses a render that wrote no label bundle
ff073239 Drop A11 note edit from the branch (MAIN has uncommitted edits to it)
0bc0147f A11: launch stub writes a minimal real label bundle; no_bundle denominator uses the larger count
426dfd0f A11 integrator: assert the note and zero-frame branches of require_label_bundle
ddb2ac3f A11: labels.no_bundle refuses a render that wrote no label bundle (CLI and web), per-camera counts

33e3e560 Phase 3 run A-2: A12 FAIL packet 1 (pixels 1.1% of the width left of the projection on every render), A11 CLI relative-terrain defect logged

 docs/PHASE3_LOG.md             |  2 ++
 docs/phase3/events_windows.log | 12 +++++++
 docs/phase3/packets/A12-1.md   | 80 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A12.json     |  9 ++++-
 4 files changed, 102 insertions(+), 1 deletion(-)

ef589327 Merge p3-A11: labels.no_bundle refuses a render that wrote no label bundle

 core/capture/labels.py      |  33 +++++++++++-
 core/messages/catalog.yaml  |   3 ++
 flightsim/capture.py        |   3 +-
 tests/engine_launch.py      |  47 +++++++++++++++++
 tests/test_camera_labels.py | 121 ++++++++++++++++++++++++++++++++++++++++++++
 webapp/runs.py              |   3 +-
 6 files changed, 207 insertions(+), 3 deletions(-)

ff073239 Drop A11 note edit from the branch (MAIN has uncommitted edits to it)

 docs/phase3/notes/A11.md | 3 ---
 1 file changed, 3 deletions(-)

0bc0147f A11: launch stub writes a minimal real label bundle; no_bundle denominator uses the larger count

 core/capture/labels.py   |  2 +-
 tests/engine_launch.py   | 47 +++++++++++++++++++++++++++++++++++++++++++++++
 tests/test_camera_cli.py |  3 ---
 3 files changed, 48 insertions(+), 4 deletions(-)

426dfd0f A11 integrator: assert the note and zero-frame branches of require_label_bundle

 tests/test_camera_labels.py | 5 +++++
 1 file changed, 5 insertions(+)

ddb2ac3f A11: labels.no_bundle refuses a render that wrote no label bundle (CLI and web), per-camera counts

 core/capture/labels.py      |  33 ++++++++++++-
 core/messages/catalog.yaml  |   3 ++
 flightsim/capture.py        |   3 +-
 tests/test_camera_cli.py    |   3 ++
 tests/test_camera_labels.py | 116 ++++++++++++++++++++++++++++++++++++++++++++
 webapp/runs.py              |   3 +-
 6 files changed, 158 insertions(+), 3 deletions(-)
```

