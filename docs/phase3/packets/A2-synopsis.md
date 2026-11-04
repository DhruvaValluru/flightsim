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
