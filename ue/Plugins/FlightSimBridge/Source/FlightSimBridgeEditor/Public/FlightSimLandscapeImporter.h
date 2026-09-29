// W5 (the world engine side, docs/ADVANCEMENTS_BLUEPRINT.md section 4): the
// editor half of the Landscape route.
//
// ImportLandscape reads W1's import manifest -- the <key>_landscape.json that
// core/terrain/landscape.py import_manifest writes beside the .r16: the Gate
// 4 layout and scale, the weight layers with their sha256s, the bake's
// sha256 and its vertical datum -- and builds an ALandscape from it in the
// editor world: the heights through ALandscape::Import, one paint layer per
// land-cover class (weight-blended, the layers sum to 255 per texel), the
// material the scene script hands it, and two actor tags the render reads:
// FlightSim.Terrain and FlightSim.TerrainSha256=<the bake's sha256>
// (FlightSimVisualScene.h FlightSimWorld). Nothing is resampled here: a layer
// of another layout than the heightmap is refused, as the Python side
// refuses it.
//
// Refusals, by name, in the log and in Report (a null return):
//   terrain.landscape_missing  the manifest is absent or unreadable, or it
//                              carries no datum block (the heights' vertical
//                              datum would be unstated) or no bake;
//   terrain.landscape_stale    the manifest's bake sha256 is not the one the
//                              scene is built for, or a layer file is absent
//                              or differs from its recorded sha256;
//   terrain.landscape_layout   the layout is not a Landscape layout, or the
//                              heightmap or a layer is not resolution^2.
//
// BuildNanite is the measured toggle (no benefit claimed): it sets the
// proxy's bEnableNanite through reflection, builds the Nanite
// representation when enabling, and reports what IsNaniteEnabled() reads
// back.
//
// The row order: the .r16 and the layers are row 0 NORTH (core/terrain/
// heightfield.py); a Landscape's Y index grows along engine +Y. With
// NorthAxis "+Y" (the project's frame: X east, Y north --
// core/scenario/randomization.py engine_sun_azimuth, FlightSimVisualScene's
// Gate 6 instances) the rows are written reversed, so the Landscape's first
// sample is the bake's SOUTH-west one; with "-Y" they are written as they
// are. The render measures the axes through the georeferencing at load and
// refuses world.scene_stale when they are not the ones the scene was built
// for.
//
// The height encoding is W1's (Gate 4): sample 32768 is the actor's Z, one
// unit is ScaleZ / 128 cm, so the actor sits at min + relief * 32768 / 65535
// metres (a flat bake is encoded over 1 m of relief, as landscape.export
// does); the residual of that choice is at most relief * 7.7e-6 m.
//
// UNCOMPILED here (no engine in the build container): the ALandscape::Import
// call is a consistency pin of this call site against the 5.5-5.7 signature
// (the final layer-list argument left to its default), checked by the first
// Windows compile; tests/test_ue_world_source.py pins the source.

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "FlightSimLandscapeImporter.generated.h"

class ALandscape;
class UMaterialInterface;
class UWorld;

DECLARE_LOG_CATEGORY_EXTERN(LogFlightSimWorld, Log, All);

UCLASS()
class FLIGHTSIMBRIDGEEDITOR_API UFlightSimLandscapeImporter : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	// Builds the Landscape of one bake from its import manifest (see the file
	// comment). AssetFolder is the scene's /Game folder (the layer-info assets
	// go under <AssetFolder>/LayerInfo). Returns null with the refusal line in
	// Report; otherwise the Landscape, and Report says what was imported.
	UFUNCTION(BlueprintCallable, Category = "FlightSim|World")
	static ALandscape* ImportLandscape(UWorld* World, const FString& ManifestPath,
	                                   const FString& ExpectedBakeSha256,
	                                   const FString& AssetFolder,
	                                   UMaterialInterface* Material,
	                                   const FString& NorthAxis, FString& Report);

	// The measured toggle: Nanite on (built) or off for this Landscape.
	// True when IsNaniteEnabled() reads back what was asked.
	UFUNCTION(BlueprintCallable, Category = "FlightSim|World")
	static bool BuildNanite(ALandscape* Landscape, bool bEnable, FString& Report);

	// "FlightSim.TerrainSha256=<sha256>", the tag the render matches.
	UFUNCTION(BlueprintPure, Category = "FlightSim|World")
	static FString TerrainSha256Tag(const FString& Sha256);
};
