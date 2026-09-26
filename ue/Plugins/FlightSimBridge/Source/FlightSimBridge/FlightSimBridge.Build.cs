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
			// Phase 10 labels: 8/16-bit grey PNGs (FImageUtils writes RGBA8 only).
			"ImageWrapper",
			// Gate 6's terrain-in-shot: a mesh built at runtime from the same
			// baked .r16 heightfield the physics pipeline produces (§3.2).
			// Phase 2 Look lane: the georeferenced terrain is TILED procedural
			// mesh components (FlightSimVisualScene.cpp), same module.
			"ProceduralMeshComponent",
			// Phase 2 Look lane (contracts §5.4): UVolumetricCloudComponent,
			// USkyAtmosphereComponent's Mie scale and the physical-camera
			// post-process settings all live in "Engine" (already above);
			// LexToString(EShaderPlatform) for render.json render_settings
			// is in "RHI" (already above). No new module is required.
		});
	}
}
