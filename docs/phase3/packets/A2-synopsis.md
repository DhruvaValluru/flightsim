# A2 synopsis

run_id: A-1
machine: windows
written: 2026-11-04T06:13:32Z

## A2 verify: pytest -q tests/test_platform.py (FLIGHTSIM_GOOGLE_TILES unset, the CLAUDE.md default)

- log: `runs/p3/A-1/A2-pytest-platform-clean-env.log`
- exit: 0 (expected 0) -> PASS

```
..............                                                           [100%]
            [JSBSim-ML v2.0]

JSBSim startup beginning ...

```

## A2 verify: same with FlightSim.Target.cs hand-edited to Unreal5_7 (must fail naming the file)

- log: `runs/p3/A-1/A2-pytest-platform-mutant.log`
- exit: 1 (expected 1) -> PASS

```
        # same thing on a machine with or without local bakes and models.
        import webapp.runs as runs_module
        import webapp.server as server_module
    
        monkeypatch.setattr(runs_module, "pick_scene",
                            lambda spec: {"key": "flat", "kind": "flat",
                                          "terrain": None, "imagery": None,
                                          "label": "flat (test)"})
        monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                            lambda spec: None)
        spec = compile_prompt("fly the 747 at 3000 m and 250 kt")
        client = TestClient(app)
        reply = client.post("/run", json={"spec": spec.to_dict()})
        assert reply.status_code == 409
        body = reply.json()
>       assert body.get("constraint") == "ue.platform"
E       AssertionError: assert 'terrain.unbaked' == 'ue.platform'
E         
E         - ue.platform
E         + terrain.unbaked

tests\test_platform.py:138: AssertionError
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
E           AssertionError: ue\Source\FlightSim.Target.cs does not pin EngineIncludeOrderVersion.Unreal5_5 (UE_ENGINE_VERSION = 5.5)
E           assert 'IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_5;' in 'using UnrealBuildTool;\n\npublic class FlightSimTarget : TargetRules\n{\n\tpublic FlightSimTarget(TargetInfo Target) ...est;\n\t\tIncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;\n\t\tExtraModuleNames.Add("FlightSim");\n\t}\n}\n'

tests\test_platform.py:342: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_platform.py::test_webapp_refuses_ue_platform_without_the_engine
FAILED tests/test_platform.py::test_target_cs_include_order_names_the_pin - A...
```

## A2 step 9: scripts/build_ue.ps1 on 5.5.4 after be6bf574

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

note: With the owner's shell variable FLIGHTSIM_GOOGLE_TILES=on exported, tests/test_platform.py::test_webapp_refuses_ue_platform_without_the_engine fails (terrain.unbaked instead of ue.platform) on this machine; the same failure occurs on bd68745b before letter A (measured in a worktree), so it is a pre-existing environment interaction, not an A2 regression; see runs/p3/A-1/A2-pytest-platform.log.

note: First build (runs/p3/A-1/A2-build.log) failed with one 5.7-only call: FlightSimVisualScene.cpp(1128) LoadSynchronous on TObjectPtr; fixed by the A2 Windows builder with a version guard, commit be6bf574.

## verdict

PASS
