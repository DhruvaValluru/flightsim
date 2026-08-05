using UnrealBuildTool;

public class FlightSimBridge : ModuleRules
{
	public FlightSimBridge(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[]
		{
			"Core", "CoreUObject", "Engine",
			"JSBSimFlightDynamicsModel",
			"GeoReferencing",
			"Json", "JsonUtilities",
			"CinematicCamera",
		});
	}
}
