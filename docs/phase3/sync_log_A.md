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
