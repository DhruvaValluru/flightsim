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
