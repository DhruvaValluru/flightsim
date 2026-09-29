using UnrealBuildTool;

// W5 (the world engine side): the editor half of the Landscape route.
// ImportLandscape builds a Landscape from W1's import manifest
// (core/terrain/landscape.py) with its weight layers, tags it with the
// bake's sha256 and refuses by name in its log; BuildNanite is the measured
// toggle. Driven by scripts/ue_build_scene.py inside the editor. UNCOMPILED
// here; the first Windows build verifies (tests/test_ue_world_source.py pins
// the source).
public class FlightSimBridgeEditor : ModuleRules
{
	public FlightSimBridgeEditor(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine",
			// ALandscape, ULandscapeLayerInfoObject, ULandscapeSubsystem.
			"Landscape",
		});
		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			// FAssetRegistryModule::AssetCreated for the layer-info assets.
			"AssetRegistry",
			"Json",
			// The scene tags the render reads (FlightSimVisualScene.h
			// FlightSimWorld), shared so the two sides cannot drift.
			"FlightSimBridge",
		});
	}
}
