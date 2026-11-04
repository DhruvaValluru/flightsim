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
