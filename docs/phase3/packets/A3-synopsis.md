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
