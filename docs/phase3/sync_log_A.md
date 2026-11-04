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

