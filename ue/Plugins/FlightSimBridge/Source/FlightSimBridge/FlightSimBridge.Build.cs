using UnrealBuildTool;

public class FlightSimBridge : ModuleRules
{
	public FlightSimBridge(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine",
			// Camera-preset keys in the interactive host (EKeys).
			"InputCore",
			"JSBSimFlightDynamicsModel",
			"GeoReferencing",
			"Json", "JsonUtilities",
			"CinematicCamera",
			// Offscreen frame capture for the two Gate 5 clauses that are
			// about what a viewer sees (FlightSimRenderCommandlet).
			"RenderCore", "RHI",
			// Gate 6's terrain-in-shot: a mesh built at runtime from the same
			// baked .r16 heightfield the physics pipeline produces (§3.2).
			"ProceduralMeshComponent",
		});
	}
}
