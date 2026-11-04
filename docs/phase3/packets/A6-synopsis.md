# A6 synopsis

run_id: A-2
machine: windows
written: 2026-11-04T16:56:47Z

## A6 step 4: first run on the owner's Content (5.7, before the storm fix): the five STALE/REBUILT/CREATED

- log: `runs/p3/A-2/A6-run1.log`
- exit: 0 (expected 0) -> PASS

```
[2026.11.04-16.34.00:123][  0]LogTextureEncodingSettings: Display: Oodle Texture Encode Speed settings: Fast: RDO Off Lambda=0, Effort=Normal Final: RDO Off Lambda=0, Effort=Normal
[2026.11.04-16.34.00:123][  0]LogTextureEncodingSettings: Display: Shared linear texture encoding: Disabled
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using QuadricMeshReduction for automatic static mesh reduction
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using SkeletalMeshReduction for automatic skeletal mesh reduction
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: Using ProxyLODMeshReduction for automatic mesh merging
[2026.11.04-16.34.00:152][  0]LogMeshReduction: Display: No distributed automatic mesh merging module available
[2026.11.04-16.34.00:555][  0]LogShaderCompilers: Display: Compiling shader autogen file: ../../../../../../Users/kanth/flightsim/ue/Intermediate/ShaderAutogen/PCD3D_SM5/AutogenShaderHeaders.ush
[2026.11.04-16.34.00:556][  0]LogShaderCompilers: Display: Autogen file is unchanged, skipping write.
[2026.11.04-16.34.00:556][  0]LogVirtualization: Display: VirtualizationSystem name found in ini file: None
[2026.11.04-16.34.00:556][  0]LogVirtualization: Display: FNullVirtualizationSystem mounted, virtualization will be disabled
[2026.11.04-16.34.00:667][  0]LogWorldPartition: Display: FWorldPartitionClassDescRegistry::Initialize started...
[2026.11.04-16.34.00:670][  0]LogWorldPartition: Display: FWorldPartitionClassDescRegistry::Initialize took 2.580 ms
[2026.11.04-16.34.01:159][  0]LogMetaSound: Display: MetaSound Page Target Initialized to 'Default'
[2026.11.04-16.34.01:160][  0]LogAudio: Display: Registering Engine Module Parameter Interfaces...
[2026.11.04-16.34.01:942][  0]LogAudioCaptureCore: Display: No Audio Capture implementations found. Audio input will be silent.
[2026.11.04-16.34.01:942][  0]LogAudioCaptureCore: Display: No Audio Capture implementations found. Audio input will be silent.
[2026.11.04-16.34.01:961][  0]LogGeoReferencing: Display: The engine is currently using Compressed Rotation Transforms. You may encounter accuracy issues with large neshes. We recommend setting all bSupportsSceneDataCompressedTransforms to false in the Engine/Config/[platform]/DataDrivenPlatformInfo.ini file
[2026.11.04-16.34.02:451][  0]LogAssetRegistry: Display: No AssetDiscovery cache present at ../../../../../../Users/kanth/flightsim/ue/Intermediate/CachedAssetRegistryDiscovery.bin. AssetRegistry discovery of files will be uncached.
[2026.11.04-16.34.02:489][  0]LogAssetRegistry: Display: AssetDataGatherer spent 0.027s loading caches ../../../../../../Users/kanth/flightsim/ue/Intermediate/CachedAssetRegistry_*.bin.
[2026.11.04-16.34.02:577][  0]LogCsvProfiler: Display: Metadata set : largeworldcoordinates="1"
[2026.11.04-16.34.02:713][  0]LogPython: Display: No pip-enabled plugins with python dependencies found, skipping
[2026.11.04-16.34.03:421][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/IKRig/Content/Python/init_unreal.py... started...
[2026.11.04-16.34.03:446][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/IKRig/Content/Python/init_unreal.py... took 23.909 ms
[2026.11.04-16.34.03:446][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/ControlRig/Content/Python/init_unreal.py... started...
[2026.11.04-16.34.03:468][  0]LogPython: Display: Running start-up script C:/Program Files/Epic Games/UE_5.7/Engine/Plugins/Animation/ControlRig/Content/Python/init_unreal.py... took 22.739 ms (total: 46.649 ms)
[2026.11.04-16.34.03:469][  0]LogPythonScriptCommandlet: Display: Running Python script: C:/Users/kanth/flightsim/scripts/ue_create_materials.py
[2026.11.04-16.34.03:891][  0]LogObjectTools: Warning: Detected inconsistencies between reference gathering algorithms. Switching 'Editor.UseLegacyGetReferencersForDeletion' on for the remainder of this editor session.
[2026.11.04-16.34.04:060][  0]LogSourceControl: Display: Uncontrolled Changelist persistency file loaded ../../../../../../Users/kanth/flightsim/ue/Saved/SourceControl/UncontrolledChangelists.json
[2026.11.04-16.34.07:872][  0]LogPythonScriptCommandlet: Display: Python script executed successfully
[2026.11.04-16.34.07:872][  0]LogInit: Display: 
[2026.11.04-16.34.07:873][  0]LogInit: Display: Warning/Error Summary (Unique only)
[2026.11.04-16.34.07:873][  0]LogInit: Display: -----------------------------------
[2026.11.04-16.34.07:873][  0]LogInit: Display: LogObjectTools: Warning: Detected inconsistencies between reference gathering algorithms. Switching 'Editor.UseLegacyGetReferencersForDeletion' on for the remainder of this editor session.
[2026.11.04-16.34.07:874][  0]LogInit: Display: 
[2026.11.04-16.34.07:874][  0]LogInit: Display: Success - 0 error(s), 1 warning(s)
[2026.11.04-16.34.07:874][  0]LogInit: Display: 

Execution of commandlet took:  4.45 seconds
[2026.11.04-16.34.08:158][  0]LogShaderCompilers: Display: Shaders left to compile 0
[2026.11.04-16.34.08:234][  0]LogSourceControl: Display: Uncontrolled Changelist persistency file saved ../../../../../../Users/kanth/flightsim/ue/Saved/SourceControl/UncontrolledChangelists.json
```

## A6 steps 6-7 after 79939f51: run 3 and run 4 on MAIN, counts per tag, Missing If

- log: `runs/p3/A-2/A6-summary.log`
- exit: 0 (expected 0) -> PASS

```
run 3 (first run after 79939f51 on MAIN): STALE 0, REBUILT 2, CREATED 2 (M_RainDrops, M_RainSplash: their stamps were re-keyed by the old rename path), EXISTS 34, FAILED 0, Missing If 0, exit 0, Success - 0 error(s), 1 warning(s)
run 4 (second run): STALE 0, REBUILT 0, CREATED 0, EXISTS 36, FAILED 0, Missing If 0, exit 0, Success - 0 error(s), 0 warning(s)
run 4: MATERIAL-EXISTS for M_CustomStencilID, M_GreyCard, M_LandcoverID, M_RainStreaks, M_Ground_City, M_LensDrops, M_RainDrops, M_RainSplash
the five's STALE/REBUILT/CREATED sequence is in runs/p3/A-2/A6-run1-editor.log (first run on this Content, before the fix); editor logs: A6-run3-editor.log, A6-run4-editor.log
```

note: the editor's own log (Saved/Logs/FlightSim.log, copied per run) is the record; the -stdout capture drops LogPython lines; the storm fix (duplicate+delete instead of rename_asset) is the Windows builder's commit 79939f51, merged 156f69ff

## verdict

PASS
