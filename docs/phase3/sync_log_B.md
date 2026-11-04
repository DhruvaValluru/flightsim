# Letter B sync log (Windows cross-check)

## B3 · PASS · run B-1 · 2026-11-04T17:40:16Z

verify line(s) from tasks/phase3_checklist.md:

```
100:   - Check: `pytest -q tests/test_toolchain_pins.py` passes.
```

output line(s) that satisfy it:

```
runs/p3/A-2/B3-pytest.log: .......                                                                  [100%]   (7 passed, exit 0)
```

note: run B-1 on 3e59358d; Python-only box, no Windows steps in the note; the pins the test guards (toolchain.json, EngineAssociation, IncludeOrderVersion, UE_ENGINE_VERSION, lock covers requirements.txt) are the ones this machine measured for decision 13

### synopsis

# B3 synopsis

run_id: B-1
machine: windows
written: 2026-11-04T17:40:15Z

## B3 verify: pytest -q tests/test_toolchain_pins.py

- log: `runs/p3/A-2/B3-pytest.log`
- exit: 0 (expected 0) -> PASS

```
.......                                                                  [100%]
```

note: run B-1 on 3e59358d (letter B push); 7 tests, all dots, exit 0

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
6e757d72 Phase 3 B3: integrated_commit stored as a string
73975501 Phase 3 B3/B4: builder notes and state restored from the integrator's stash
1fa0df0f B3: restore tests/test_toolchain_pins.py (a staged deletion slipped into the bookkeeping commit)
b3ed6a52 Phase 3 B3: integrated state and note; A6 and A8 PASS logged
69726238 Merge p3-B3: test_toolchain_pins keeps every pin in one place
679e9fb1 B3: the two engine-pin mutation guards also run tests/test_toolchain_pins.py
8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place
af39a626 Merge branch 'p3-B1' into p3-B3

6e757d72 Phase 3 B3: integrated_commit stored as a string

 docs/phase3/state/B3.json | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

73975501 Phase 3 B3/B4: builder notes and state restored from the integrator's stash

 docs/phase3/notes/B3.md   | 11 +++++++++++
 docs/phase3/notes/B4.md   | 11 +++++++++++
 docs/phase3/state/B3.json | 10 +++++++---
 docs/phase3/state/B4.json | 18 +++++++++++++++---
 4 files changed, 44 insertions(+), 6 deletions(-)

1fa0df0f B3: restore tests/test_toolchain_pins.py (a staged deletion slipped into the bookkeeping commit)

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

b3ed6a52 Phase 3 B3: integrated state and note; A6 and A8 PASS logged

 docs/phase3/events_mac.log   |   3 +
 docs/phase3/notes/B3.md      |   3 +
 docs/phase3/state/B3.json    |   5 +-
 tests/test_toolchain_pins.py | 238 -------------------------------------------
 4 files changed, 9 insertions(+), 240 deletions(-)

69726238 Merge p3-B3: test_toolchain_pins keeps every pin in one place

 docs/phase3/events_mac.log   |   6 ++
 scripts/mutation_check.sh    |   4 +-
 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 246 insertions(+), 2 deletions(-)

679e9fb1 B3: the two engine-pin mutation guards also run tests/test_toolchain_pins.py

 scripts/mutation_check.sh | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

af39a626 Merge branch 'p3-B1' into p3-B3

 .github/workflows/ci.yml   |   8 +-
 requirements.lock          | 737 +++++++++++++++++++++++++++++++++++++++++++++
 scripts/deploy_windows.ps1 |   8 +-
 3 files changed, 748 insertions(+), 5 deletions(-)
```

## B2 · PASS · run B-1 · 2026-11-04T17:56:46Z

verify line(s) from tasks/phase3_checklist.md:

```
98:   - Check: preflight prints `OK` per tool, and a wrong version stops it.
```

output line(s) that satisfy it:

```
runs/p3/A-2/B2-preflight-2.log: toolchain engine OK engine 5.7.4 (CL 51494982) / msvc OK 14.44.35207 / windows_sdk OK 10.0.26100.0 / cesium_for_unreal OK 2.30.0 / ffmpeg OK 9.0.2 / python OK 3.12.10 / jsbsim OK 1.2.4 ; Preflight OK -- the Unreal host can run here. (exit 0)
runs/p3/A-2/B2-preflight-ffmpeg-2.log: toolchain ffmpeg  toolchain.ffmpeg_mismatch: found 9.0.2, pinned 9.0.1 (exit 1)
runs/p3/A-2/B2-preflight-sdk-2.log: toolchain windows_sdk  toolchain.windows_sdk_mismatch: found 10.0.26100.0, pinned 10.0.22621.0 (exit 1)
```

note: run B-1: one FAIL packet (B2-1, the reader lost the exit code behind Select-Object in PowerShell 5.1), fixed by the Windows builder in scripts/ue_preflight.ps1; the Mac side (toolchain.json, platform.py reader, test_powershell_scripts) unchanged

### synopsis

# B2 synopsis

run_id: B-1
machine: windows
written: 2026-11-04T17:56:45Z

## B2 step 5: ue_preflight.ps1 toolchain section on the 5.7 laptop (after 0dd863f9)

- log: `runs/p3/A-2/B2-preflight-2.log`
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
  flightsim bridge                   23 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  toolchain engine                   OK engine 5.7.4 (CL 51494982)
  toolchain msvc                     OK msvc 14.44.35207
  toolchain windows_sdk              OK windows_sdk 10.0.26100.0
  toolchain cesium_for_unreal        OK cesium_for_unreal 2.30.0
  toolchain ffmpeg                   OK ffmpeg 9.0.2
  toolchain python                   OK python 3.12.10
  toolchain jsbsim                   OK jsbsim 1.2.4

Preflight OK -- the Unreal host can run here.
Validate the render output on THIS machine with:
  .\.venv\Scripts\python.exe experiments\gate6_visual.py
```

## B2 step 6: ffmpeg pinned 9.0.1 must refuse by name

- log: `runs/p3/A-2/B2-preflight-ffmpeg-2.log`
- exit: 1 (expected 1) -> PASS

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
  flightsim bridge                   23 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  toolchain engine                   OK engine 5.7.4 (CL 51494982)
  toolchain msvc                     OK msvc 14.44.35207
  toolchain windows_sdk              OK windows_sdk 10.0.26100.0
  toolchain cesium_for_unreal        OK cesium_for_unreal 2.30.0
  toolchain ffmpeg                   toolchain.ffmpeg_mismatch: found 9.0.2, pinned 9.0.1
  toolchain python                   OK python 3.12.10
  toolchain jsbsim                   OK jsbsim 1.2.4

Preflight FAILED -- see above.
```

## B2 step 7: windows_sdk pinned 10.0.22621.0 must refuse by name

- log: `runs/p3/A-2/B2-preflight-sdk-2.log`
- exit: 1 (expected 1) -> PASS

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
  flightsim bridge                   23 translation units
  bridge binary                      built
  material assets                    M_VertexColor + M_TerrainImagery present
  physical-sky materials             M_Moon + M_StarEmissive + M_TerrainImageryNight present
  toolchain engine                   OK engine 5.7.4 (CL 51494982)
  toolchain msvc                     OK msvc 14.44.35207
  toolchain windows_sdk              toolchain.windows_sdk_mismatch: found 10.0.26100.0, pinned 10.0.22621.0
  toolchain cesium_for_unreal        OK cesium_for_unreal 2.30.0
  toolchain ffmpeg                   OK ffmpeg 9.0.2
  toolchain python                   OK python 3.12.10
  toolchain jsbsim                   OK jsbsim 1.2.4

Preflight FAILED -- see above.
```

note: run B-1 on 3e59358d + the Windows builder's 0dd863f9 (merged b3937b92): packet B2-1's false jsbsim mismatch is gone; toolchain.json restored after steps 6 and 7

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
4842e0bf Phase 3: B2 builder merge log
9ec1a18f B2: preflight python/jsbsim readers capture Probe output before taking the first line, so $LASTEXITCODE is read right after the call (PowerShell 5.1 pipe to Select-Object left it at -1)
5e9d0527 Phase 3 run B-1: B2 FAIL packet 1 (preflight jsbsim reader loses the exit code behind Select-Object)
365e8d90 Phase 3 run B-1: B3 PASS; B2 preflight measurements
031e796d Phase 3 B2: integrator notes, state, Mac event log
9dcc7d5a Phase 3 B2: integrated note and state
f8add1b1 Merge p3-B2: toolchain.json manifest, platform.py reads the pin from it, preflight toolchain section
8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place
92c0d957 Phase 3 B2: integrator notes, state, Mac event log
d9870df5 Phase 3 B2: integrated note and state
8dedc449 B2: retarget the platform pin guard to toolchain.json (the constant is read from it now)
ab07961c Merge p3-B2: toolchain.json manifest, platform.py reads the pin from it, preflight toolchain section
14e81906 B2: toolchain.json pins every tool; platform.py reads it, preflight refuses by name

4842e0bf Phase 3: B2 builder merge log

 docs/phase3/events_windows.log | 5 +++++
 1 file changed, 5 insertions(+)

9ec1a18f B2: preflight python/jsbsim readers capture Probe output before taking the first line, so $LASTEXITCODE is read right after the call (PowerShell 5.1 pipe to Select-Object left it at -1)

 scripts/ue_preflight.ps1 | 20 +++++++++++++++-----
 1 file changed, 15 insertions(+), 5 deletions(-)

5e9d0527 Phase 3 run B-1: B2 FAIL packet 1 (preflight jsbsim reader loses the exit code behind Select-Object)

 docs/phase3/events_windows.log | 20 +++++++++++++++
 docs/phase3/packets/B2-1.md    | 55 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A12.json     |  8 +++---
 docs/phase3/state/B2.json      |  9 ++++++-
 4 files changed, 87 insertions(+), 5 deletions(-)

365e8d90 Phase 3 run B-1: B3 PASS; B2 preflight measurements

 docs/PHASE3_LOG.md                 |   8 +++
 docs/phase3/events_windows.log     |  21 ++++++++
 docs/phase3/packets/B3-synopsis.md |  20 +++++++
 docs/phase3/state/A12.json         |  10 ++--
 docs/phase3/state/B3.json          |   6 ++-
 docs/phase3/sync_log_B.md          | 104 +++++++++++++++++++++++++++++++++++++
 tasks/phase3_checklist.md          |   2 +-
 7 files changed, 165 insertions(+), 6 deletions(-)

031e796d Phase 3 B2: integrator notes, state, Mac event log

 docs/phase3/events_mac.log |  6 ++++++
 docs/phase3/notes/B1.md    | 13 +++++++++++++
 docs/phase3/notes/B2.md    |  1 +
 docs/phase3/state/B1.json  | 19 +++++++++++--------
 docs/phase3/state/B2.json  |  2 +-
 5 files changed, 32 insertions(+), 9 deletions(-)

9dcc7d5a Phase 3 B2: integrated note and state

 docs/phase3/events_mac.log | 50 ++++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/B2.md    | 16 +++++++++++++++
 docs/phase3/state/B2.json  | 22 +++++++++++---------
 3 files changed, 79 insertions(+), 9 deletions(-)

f8add1b1 Merge p3-B2: toolchain.json manifest, platform.py reads the pin from it, preflight toolchain section

 core/util/platform.py            |  72 +++++++++++++++++++--
 scripts/mutation_check.sh        |   6 +-
 scripts/ue_preflight.ps1         | 135 +++++++++++++++++++++++++++++++++++++--
 tests/test_powershell_scripts.py |  61 ++++++++++++++++++
 toolchain.json                   |  19 ++++++
 5 files changed, 280 insertions(+), 13 deletions(-)

8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

92c0d957 Phase 3 B2: integrator notes, state, Mac event log

 docs/phase3/events_mac.log |  6 ++++++
 docs/phase3/notes/B1.md    | 13 +++++++++++++
 docs/phase3/notes/B2.md    |  1 +
 docs/phase3/state/B1.json  | 19 +++++++++++--------
 docs/phase3/state/B2.json  |  2 +-
 5 files changed, 32 insertions(+), 9 deletions(-)

d9870df5 Phase 3 B2: integrated note and state

 docs/phase3/events_mac.log | 50 ++++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/B2.md    | 16 +++++++++++++++
 docs/phase3/state/B2.json  | 22 +++++++++++---------
 3 files changed, 79 insertions(+), 9 deletions(-)

8dedc449 B2: retarget the platform pin guard to toolchain.json (the constant is read from it now)

 scripts/mutation_check.sh | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)

ab07961c Merge p3-B2: toolchain.json manifest, platform.py reads the pin from it, preflight toolchain section

 core/util/platform.py            |  72 +++++++++++++++++++--
 scripts/mutation_check.sh        |   6 +-
 scripts/ue_preflight.ps1         | 135 +++++++++++++++++++++++++++++++++++++--
 tests/test_powershell_scripts.py |  61 ++++++++++++++++++
 toolchain.json                   |  19 ++++++
 5 files changed, 280 insertions(+), 13 deletions(-)

14e81906 B2: toolchain.json pins every tool; platform.py reads it, preflight refuses by name

 core/util/platform.py            |  72 +++++++++++++++++++--
 scripts/ue_preflight.ps1         | 135 +++++++++++++++++++++++++++++++++++++--
 tests/test_powershell_scripts.py |  61 ++++++++++++++++++
 toolchain.json                   |  19 ++++++
 4 files changed, 277 insertions(+), 10 deletions(-)
```

