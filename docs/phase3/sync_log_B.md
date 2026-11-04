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

## B1 · PASS · run B-1 · 2026-11-04T18:07:44Z

verify line(s) from tasks/phase3_checklist.md:

```
96:   - Check: a fresh install from it, then `pytest -q`, passes.
```

output line(s) that satisfy it:

```
runs/p3/A-2/B1-pip-install.log: Successfully installed affine-3.0.1 ... jsbsim ... (pip exit 0, --require-hashes)  /  runs/p3/A-2/B1-verify-import.log: imports ok; jsbsim 1.2.4
runs/p3/A-2/B1-pytest-2.log: .....................  [100%]  (21 passed: tests/test_toolchain_pins.py tests/test_platform.py in the fresh venv, exit 0; the owner's rule limits the run to the box's files, the full suite runs once at phase end)
runs/p3/A-2/B1-deploy-2.log: ==> this install is at: e35545c3 ... ==> installing the hashed lock ... ==> verifying the physics and server imports (exit 0; deployed venv imports ok; jsbsim 1.2.4)  /  runs/p3/A-2/B1-deploy-broken.log: install.clone_failed: git exited 128 -- the clone of ... (branch no-such-branch-b1) did not complete (exit 1, no install dir left)
```

note: run B-1: step 10 CI = pending draft PR (recorded in docs/PHASE3_LOG.md, reported by the Mac when the first matrix run lands); the first installer run was cut by a network reset and exposed the exit-0 defect fixed in cfa48660

### synopsis

# B1 synopsis

run_id: B-1
machine: windows
written: 2026-11-04T18:07:42Z

## B1 step 8: fresh 3.12.10 venv, pip install --require-hashes -r requirements.lock

- log: `runs/p3/A-2/B1-pip-install.log`
- exit: 0 (expected 0) -> PASS

```
Collecting packaging==26.3 (from -r requirements.lock (line 299))
  Using cached packaging-26.3-py3-none-any.whl (129 kB)
Collecting pillow==11.3.0 (from -r requirements.lock (line 303))
  Using cached pillow-11.3.0-cp312-cp312-win_amd64.whl (7.0 MB)
Collecting pluggy==1.7.0 (from -r requirements.lock (line 411))
  Downloading pluggy-1.7.0-py3-none-any.whl (27 kB)
Collecting pydantic==2.14.2 (from -r requirements.lock (line 415))
  Downloading pydantic-2.14.2-py3-none-any.whl (490 kB)
Collecting pydantic-core==2.50.2 (from -r requirements.lock (line 421))
  Downloading pydantic_core-2.50.2-cp312-cp312-win_amd64.whl (2.3 MB)
     ---------------------------------------- 2.3/2.3 MB 837.9 kB/s eta 0:00:00
Collecting pygments==2.21.0 (from -r requirements.lock (line 564))
  Using cached pygments-2.21.0-py3-none-any.whl (1.3 MB)
Collecting pyparsing==3.3.3 (from -r requirements.lock (line 568))
  Downloading pyparsing-3.3.3-py3-none-any.whl (126 kB)
Collecting pyproj==3.6.1 (from -r requirements.lock (line 572))
  Using cached pyproj-3.6.1-cp312-cp312-win_amd64.whl (6.1 MB)
Collecting pytest==8.4.2 (from -r requirements.lock (line 601))
  Using cached pytest-8.4.2-py3-none-any.whl (365 kB)
Collecting pytest-timeout==2.3.1 (from -r requirements.lock (line 607))
  Using cached pytest_timeout-2.3.1-py3-none-any.whl (14 kB)
Collecting pyyaml==6.0.3 (from -r requirements.lock (line 611))
  Using cached pyyaml-6.0.3-cp312-cp312-win_amd64.whl (154 kB)
Collecting rasterio==1.4.3 (from -r requirements.lock (line 686))
  Using cached rasterio-1.4.3-cp312-cp312-win_amd64.whl (25.4 MB)
Collecting sniffio==1.3.1 (from -r requirements.lock (line 709))
  Using cached sniffio-1.3.1-py3-none-any.whl (10 kB)
Collecting starlette==0.52.1 (from -r requirements.lock (line 713))
  Using cached starlette-0.52.1-py3-none-any.whl (74 kB)
Collecting typing-extensions==4.16.0 (from -r requirements.lock (line 717))
  Using cached typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Collecting typing-inspection==0.4.5 (from -r requirements.lock (line 728))
  Downloading typing_inspection-0.4.5-py3-none-any.whl (14 kB)
Collecting uvicorn==0.39.0 (from -r requirements.lock (line 734))
  Using cached uvicorn-0.39.0-py3-none-any.whl (68 kB)
Installing collected packages: typing-extensions, sniffio, pyyaml, pyparsing, pygments, pluggy, pillow, packaging, numpy, jiter, iniconfig, idna, h11, docstring-parser, distro, colorama, click, certifi, attrs, annotated-types, annotated-doc, uvicorn, typing-inspection, pytest, pyproj, pydantic-core, jsbsim, httpcore, cligj, click-plugins, anyio, affine, starlette, rasterio, pytest-timeout, pydantic, httpx, fastapi, anthropic
Successfully installed affine-3.0.1 annotated-doc-0.0.5 annotated-types-0.8.0 anthropic-0.121.0 anyio-4.16.0 attrs-26.1.0 certifi-2026.10.23 click-8.5.0 click-plugins-1.1.1.2 cligj-0.7.2 colorama-0.4.6 distro-1.9.0 docstring-parser-0.18.0 fastapi-0.128.8 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.20 iniconfig-2.3.1 jiter-0.18.0 jsbsim-1.2.4 numpy-2.0.2 packaging-26.3 pillow-11.3.0 pluggy-1.7.0 pydantic-2.14.2 pydantic-core-2.50.2 pygments-2.21.0 pyparsing-3.3.3 pyproj-3.6.1 pytest-8.4.2 pytest-timeout-2.3.1 pyyaml-6.0.3 rasterio-1.4.3 sniffio-1.3.1 starlette-0.52.1 typing-extensions-4.16.0 typing-inspection-0.4.5 uvicorn-0.39.0

[notice] A new release of pip is available: 25.0.1 -> 26.3
[notice] To update, run: C:\Users\kanth\flightsim\runs\p3\A-2\venv-B1\Scripts\python.exe -m pip install --upgrade pip
```

## B1 step 8: the box's pytest in the fresh venv (FLIGHTSIM_GOOGLE_TILES unset)

- log: `runs/p3/A-2/B1-pytest-2.log`
- exit: 0 (expected 0) -> PASS

```
.....................                                                    [100%]
============================== warnings summary ===============================
tests/test_platform.py::test_webapp_refuses_ue_platform_without_the_engine
  C:\Users\kanth\flightsim\runs\p3\A-2\venv-B1\Lib\site-packages\starlette\testclient.py:45: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## B1 step 9: deploy_windows.ps1 -NoLaunch good run (clone, venv, lock, verify imports)

- log: `runs/p3/A-2/B1-deploy-2.log`
- exit: 0 (expected 0) -> PASS

```
Updating files:  78% (13389/17165)
Updating files:  79% (13561/17165)
Updating files:  80% (13732/17165)
Updating files:  80% (13878/17165)
Updating files:  81% (13904/17165)
Updating files:  82% (14076/17165)
Updating files:  83% (14247/17165)
Updating files:  84% (14419/17165)
Updating files:  85% (14591/17165)
Updating files:  85% (14682/17165)
Updating files:  86% (14762/17165)
Updating files:  87% (14934/17165)
Updating files:  88% (15106/17165)
Updating files:  89% (15277/17165)
Updating files:  90% (15449/17165)
Updating files:  90% (15525/17165)
Updating files:  91% (15621/17165)
Updating files:  91% (15740/17165)
Updating files:  92% (15792/17165)
Updating files:  92% (15804/17165)
Updating files:  93% (15964/17165)
Updating files:  94% (16136/17165)
Updating files:  94% (16297/17165)
Updating files:  95% (16307/17165)
Updating files:  96% (16479/17165)
Updating files:  97% (16651/17165)
Updating files:  98% (16822/17165)
Updating files:  99% (16994/17165)
Updating files:  99% (17144/17165)
Updating files: 100% (17165/17165)
Updating files: 100% (17165/17165), done.
==> this install is at: e35545c3 Phase 3 run A-2: A7 step 8 rows (import once, render completes on a quiet machine)
==> creating venv
==> installing the hashed lock, requirements.lock (first run downloads ~200 MB of wheels)
==> verifying the physics and server imports

Set up. Start it any time with:
  cd C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy2
  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008
deployed venv imports ok; jsbsim 1.2.4
```

## B1 step 9 after cfa48660: broken clone stage must refuse by name

- log: `runs/p3/A-2/B1-deploy-broken.log`
- exit: 1 (expected 1) -> PASS

```
==> using py -3.12
==> cloning https://github.com/DhruvaValluru/flightsim.git -> C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken
Cloning into 'C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken'...
fatal: Remote branch no-such-branch-b1 not found in upstream origin
install.clone_failed: git exited 128 -- the clone of https://github.com/DhruvaValluru/flightsim.git (branch 
'no-such-branch-b1') into C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken did not complete (network cut, or no 
such branch); remove C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken and re-run
At C:\Users\kanth\flightsim\scripts\deploy_windows.ps1:64 char:9
+         throw "${stage}: $tool exited $LASTEXITCODE -- $cause"
+         ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : OperationStopped: (install.clone_f...oken and re-run:String) [], RuntimeException
    + FullyQualifiedErrorId : install.clone_failed: git exited 128 -- the clone of https://github.com/DhruvaValluru/fl 
   ightsim.git (branch 'no-such-branch-b1') into C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken did not comple  
  te (network cut, or no such branch); remove C:/Users/kanth/flightsim/runs/p3/A-2/B1-deploy-broken and re-run
 
```

note: run B-1 on 3e59358d + the Windows builder's cfa48660 (merged 85ac89be); step 10 (CI matrix) is 'CI: pending draft PR' per the Mac (ci.yml runs on master pushes and pull_request only); packet B1-1 closed by the builder

## verdict

PASS

### the box's commits on the branch (final diff, by stat)

```
43732095 Phase 3: B1 builder merge log
d902bda2 B1: deploy_windows.ps1 checks every native stage's exit code and refuses by name (install.clone_failed, install.lock_failed, install.verify_failed) instead of exiting 0 on a broken install
802401a8 Phase 3 run B-1: B1 installer retry passes (clone, lock, verify)
da1a4c97 Phase 3 run B-1: B1 step 10 recorded as CI pending draft PR
27f9d43b Phase 3 run B-1: B1 FAIL packet 1 (installer exits 0 on a broken stage)
e2b34b39 Phase 3 run B-1: B4 re-measurement and B1 fresh-venv rows
a09a5cc3 Phase 3 B1: integrator log line
1f137ada Phase 3 B1: integrated note and state
4e676603 Merge p3-B1: hashed requirements.lock on Python 3.12.10, CI and installer install from it
8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place
af39a626 Merge branch 'p3-B1' into p3-B3
695710c6 B1: install Python deps from a hashed requirements.lock (Python 3.12, uv universal)
fc7aee06 Phase 3 letter B: notes for B1-B4, Align first run, build order

43732095 Phase 3: B1 builder merge log

 docs/phase3/events_windows.log | 3 +++
 1 file changed, 3 insertions(+)

d902bda2 B1: deploy_windows.ps1 checks every native stage's exit code and refuses by name (install.clone_failed, install.lock_failed, install.verify_failed) instead of exiting 0 on a broken install

 scripts/deploy_windows.ps1 | 30 +++++++++++++++++++++++++++++-
 1 file changed, 29 insertions(+), 1 deletion(-)

802401a8 Phase 3 run B-1: B1 installer retry passes (clone, lock, verify)

 docs/PHASE3_LOG.md             | 1 +
 docs/phase3/events_windows.log | 8 ++++++++
 2 files changed, 9 insertions(+)

da1a4c97 Phase 3 run B-1: B1 step 10 recorded as CI pending draft PR

 docs/PHASE3_LOG.md             | 1 +
 docs/phase3/events_windows.log | 1 +
 2 files changed, 2 insertions(+)

27f9d43b Phase 3 run B-1: B1 FAIL packet 1 (installer exits 0 on a broken stage)

 docs/PHASE3_LOG.md             |  1 +
 docs/phase3/events_windows.log | 35 ++++++++++++++++++++++++
 docs/phase3/packets/B1-1.md    | 60 ++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/B1.json      |  9 ++++++-
 docs/phase3/state/B2.json      | 14 +++++-----
 5 files changed, 112 insertions(+), 7 deletions(-)

e2b34b39 Phase 3 run B-1: B4 re-measurement and B1 fresh-venv rows

 docs/PHASE3_LOG.md | 2 ++
 1 file changed, 2 insertions(+)

a09a5cc3 Phase 3 B1: integrator log line

 docs/phase3/events_mac.log | 16 ++++++++++++++++
 1 file changed, 16 insertions(+)

1f137ada Phase 3 B1: integrated note and state

 docs/phase3/notes/B1.md   | 6 ++++++
 docs/phase3/state/B1.json | 5 +++--
 2 files changed, 9 insertions(+), 2 deletions(-)

4e676603 Merge p3-B1: hashed requirements.lock on Python 3.12.10, CI and installer install from it

 .github/workflows/ci.yml   |   8 +-
 requirements.lock          | 737 +++++++++++++++++++++++++++++++++++++++++++++
 scripts/deploy_windows.ps1 |   8 +-
 3 files changed, 748 insertions(+), 5 deletions(-)

8f42b88d B3: tests/test_toolchain_pins.py keeps every pin in one place

 tests/test_toolchain_pins.py | 238 +++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 238 insertions(+)

af39a626 Merge branch 'p3-B1' into p3-B3

 .github/workflows/ci.yml   |   8 +-
 requirements.lock          | 737 +++++++++++++++++++++++++++++++++++++++++++++
 scripts/deploy_windows.ps1 |   8 +-
 3 files changed, 748 insertions(+), 5 deletions(-)

695710c6 B1: install Python deps from a hashed requirements.lock (Python 3.12, uv universal)

 .github/workflows/ci.yml   |   8 +-
 requirements.lock          | 737 +++++++++++++++++++++++++++++++++++++++++++++
 scripts/deploy_windows.ps1 |   8 +-
 3 files changed, 748 insertions(+), 5 deletions(-)

fc7aee06 Phase 3 letter B: notes for B1-B4, Align first run, build order

 docs/phase3/events_mac.log | 75 +++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/B1.md    | 64 ++++++++++++++++++++++++++++++++++
 docs/phase3/notes/B2.md    | 87 ++++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/notes/B3.md    | 57 ++++++++++++++++++++++++++++++
 docs/phase3/notes/B4.md    | 87 ++++++++++++++++++++++++++++++++++++++++++++++
 docs/phase3/state/A5.json  |  9 ++---
 docs/phase3/state/B.json   | 20 +++++++++++
 docs/phase3/state/B1.json  |  8 +++++
 docs/phase3/state/B2.json  |  8 +++++
 docs/phase3/state/B3.json  |  8 +++++
 docs/phase3/state/B4.json  |  8 +++++
 11 files changed, 427 insertions(+), 4 deletions(-)
```

