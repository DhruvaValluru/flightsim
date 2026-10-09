using System;
using System.IO;
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
			// W5: the scene level's Landscape (ALandscapeProxy, ULandscapeInfo)
			// read by FlightSimVisualScene LoadSceneLevel; level streaming is
			// "Engine".
			"Landscape",
			// The weather (FlightSimWeather.cpp): the optional Niagara rain
			// backend (UNiagaraComponent, UNiagaraFunctionLibrary). The
			// procedural backend, the storm, the lightning and the thunder
			// (USoundWaveProcedural, UGameplayStatics) are all "Engine".
			"Niagara",
		});

		// Google Photorealistic 3D Tiles (FlightSimGoogleTiles.cpp) ride the
		// Cesium for Unreal plugin. It is optional: found -> compiled in and
		// FLIGHTSIM_GOOGLE_TILES=on can use it; absent -> the same build as
		// before, and asking for the tiles refuses by name.
		// FLIGHTSIM_CESIUM=0 forces it out.
		bool bCesium = System.Environment.GetEnvironmentVariable("FLIGHTSIM_CESIUM") != "0"
			&& FindCesium(Target) != null;
		if (bCesium)
		{
			PublicDependencyModuleNames.Add("CesiumRuntime");
		}
		PublicDefinitions.Add("WITH_FLIGHTSIM_CESIUM=" + (bCesium ? "1" : "0"));
	}

	private string FindCesium(ReadOnlyTargetRules Target)
	{
		var roots = new System.Collections.Generic.List<string>();
		if (Target.ProjectFile != null)
		{
			roots.Add(Path.Combine(Target.ProjectFile.Directory.FullName, "Plugins"));
		}
		roots.Add(Path.Combine(EngineDirectory, "Plugins", "Marketplace"));
		foreach (string root in roots)
		{
			if (!Directory.Exists(root))
			{
				continue;
			}
			try
			{
				string[] found = Directory.GetFiles(root, "CesiumForUnreal.uplugin",
				                                    SearchOption.AllDirectories);
				if (found.Length > 0)
				{
					return found[0];
				}
			}
			catch (Exception)
			{
				// An unreadable folder is not a Cesium install.
			}
		}
		return null;
	}
}
