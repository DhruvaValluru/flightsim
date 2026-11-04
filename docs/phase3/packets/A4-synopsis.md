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
