// The world's beauty look (visual overhaul, world lane, 2026-11-09).
//
// BEAUTY ONLY. The render commandlet calls Build only under -quality=beauty,
// after the scene, the weather and the Google tiles exist, and Advance once a
// frame after the weather's own Advance. A -quality=measure render (every
// render Gate 6 passed on) never constructs anything here and is byte-identical
// to the build before this file existed.
//
// What it does, each row recorded in render.json look_applied.world_beauty:
//
// * ATMOSPHERE DEPTH. One look preset per card (clear / hazy / overcast /
//   rain / storm, FlightSimWorldPure::SelectPreset). A share of the card's
//   haze (Koschmieder beta from look.visibility_km) moves from the height fog
//   into the sky atmosphere's Mie layer, the fog keeping the rest, so the
//   extinction at the ground is counted once and far ridges turn blue-hazy
//   through the atmosphere's own scattering. Mie scale height and anisotropy,
//   the aerial perspective distance scale and the planet's ground albedo
//   (the horizon fill beyond the tiles' extent) per preset. The height fog's
//   volumetric fog on, the sun casting shadows on the atmosphere and clouds,
//   per-pixel atmosphere transmittance. -NoAerialPerspective (Gate 6's
//   extinction control) is respected: a hidden atmosphere is left alone.
// * CLOUDS. Every volumetric cloud on the engine's simple material (the
//   look's layer, the physical sky's) is redrawn with M_FlightSimCloudLayers
//   (scripts/ue_create_materials.py, assets/shaders/world/cloud_layers.hlsl):
//   layered seeded noise, cumulus / stratocumulus / overcast / nimbostratus
//   shapes chosen from the layer's cover and thickness. The layer's base,
//   top and cover stay the card's. The storm's M_StormCell is never touched.
//   -beauty-clouds=fair adds a fair-weather cumulus layer when the card has
//   none (a stated stylisation); -beauty-clouds=engine leaves the clouds as
//   built.
// * LABEL HONESTY FOR CLOUDS. Volumetric clouds write no depth and no
//   stencil: the mask, class and depth passes never see them. A cloud
//   between the camera and the aircraft would hide in the beauty what the
//   mask shows. Decision (recorded): clouds stay where the card puts them;
//   every frame records the camera-to-aircraft path through each layer, its
//   estimated transmittance and a cloud_occludes_aircraft flag, so a
//   consumer drops or down-weights those frames. The mask is not edited.
// * TILES LOOK. When the Google tiles draw, their material becomes
//   M_FlightSimTilesBeauty (the Cesium base-colour texture graded by a
//   dark-object de-haze and saturation, a near-field detail normal faded by
//   distance, wet darkening, puddles on flat ground) driven through
//   MPC_FlightSimWorld; Cesium's smooth normals on. Cesium's API is not on
//   the authoring machine: every Cesium touch is by reflection and recorded
//   as found or not (FFlightSimGoogleTiles::ApplyBeautyLook, UNVERIFIED).
// * RAIN AND STORM. The weather's drawn rain weight times the preset's
//   readability gain (a stated exaggeration on top of -rain-gain=); the
//   lightning as a timed sky-light pulse; both lightning schedules (the
//   weather look's and the storm weather's) recorded per frame.
// * GROUND SCATTER. -ground-scatter=<sidecar> (core/scene/world_beauty.py):
//   seeded instances traced onto the tiles (FFlightSimGroundDetail).
//
// Every look value is UNCALIBRATED: set by probe render on the render machine
// (docs/visual/PROBE_LOG.md ## world). -world-beauty-overrides=<json> replaces
// any of them at run time for a probe sweep (core/scene/world_beauty.py
// validate_overrides is the schema); the record says which were overridden.
// Each flag falls back to an environment variable, so the web app's beauty
// renders (FLIGHTSIM_RENDER_QUALITY=beauty) reach them with no webapp change:
// FLIGHTSIM_BEAUTY_CLOUDS, FLIGHTSIM_WORLD_BEAUTY_OVERRIDES, FLIGHTSIM_GROUND_SCATTER.
//
// UNCOMPILED when written (a Mac whose Xcode is above UE 5.7's cap): every
// engine symbol was checked against the 5.7.4 headers (scripts/
// check_bridge_api.sh "world lane" block); the first build verifies the rest.

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "FlightSimDustHaze.h"
#include "FlightSimGroundDetail.h"

class AActor;
class AGeoReferencingSystem;
class FFlightSimGoogleTiles;
class FFlightSimVisualScene;
class FFlightSimWeather;
class UMaterialInstanceDynamic;
class UMaterialParameterCollection;
class USkyLightComponent;
class UVolumetricCloudComponent;
class UWorld;

class FLIGHTSIMBRIDGE_API FFlightSimWorldBeauty
{
public:
	// Everything above, from the run card and the command line (-beauty-clouds=,
	// -world-beauty-overrides=, -ground-scatter=). Refuses only what was asked
	// for explicitly and cannot be honoured (an unreadable overrides file or
	// scatter sidecar, an unknown -beauty-clouds word); a missing material is
	// recorded, never refused: the look is visual only.
	bool Build(UWorld* World, const TCHAR* Params, const TSharedPtr<FJsonObject>& Card,
	           AActor* Aircraft, AGeoReferencingSystem* GeoReferencing,
	           FFlightSimVisualScene& Scene, FFlightSimWeather& Weather,
	           FFlightSimGoogleTiles& Tiles, FString& Error);

	// Per captured frame, after the weather's Advance and before the captures:
	// the clouds' drift, the lightning's sky pulse, the scatter's re-snap near
	// the camera, and the frame's record (lightning, cloud occlusion).
	// Deterministic in TimeSeconds except the scatter's re-snap, which follows
	// the tiles Cesium streamed for this view (recorded).
	void Advance(double TimeSeconds, const FVector& CameraCm, const FVector& AircraftCm,
	             int32 FrameIndex);

	bool IsBuilt() const { return bBuilt; }

	// look_applied.world_beauty (the same object the scene's LookApplied holds).
	TSharedPtr<FJsonObject> Record;

private:
	struct FCloudLayerState
	{
		UVolumetricCloudComponent* Component = nullptr;
		UMaterialInstanceDynamic* Material = nullptr;
		double BaseM = 0.0;
		double TopM = 0.0;
		double Cover = 0.0;
		int32 Shape = 0;
	};

	bool LoadOverrides(const FString& Path, FString& Error);
	void ApplyAtmosphere(UWorld* World, FFlightSimVisualScene& Scene, double VisibilityKm);
	void ApplyClouds(UWorld* World, FFlightSimVisualScene& Scene, FFlightSimWeather& Weather,
	                 const FString& Mode, double CardCover, double CardBaseM, double CardTopM,
	                 int32 Seed);
	void ApplyTiles(UWorld* World, FFlightSimGoogleTiles& Tiles, double CardWetness);

	bool bBuilt = false;
	int32 Preset = 0;
	// The tables in force (the pure block's defaults, then the overrides).
	TArray<double> AtmosphereValues;   // PresetCount x AtmosphereFieldCount
	TArray<double> CloudValues;        // CloudCount x CloudFieldCount
	double CloudExtinctionScale = 1.0;
	double OcclusionFlagTransmittance = 0.5;
	double LightningReferenceLux = 50.0;
	double DetailFadeM = 1500.0;
	double DetailScaleM = 2.0;
	double PuddleShare = 0.5;
	TArray<FString> Overridden;

	TArray<FCloudLayerState> CloudLayers;
	// Drawn clouds the per-frame occlusion row does not model (ApplyClouds).
	int32 UnmodelledClouds = 0;
	double DriftMps = 0.0;
	double DriftFromDeg = 0.0;

	USkyLightComponent* SkyLight = nullptr;
	float SkyLightBaseIntensity = 1.0f;
	double LightningSkyGain = 0.0;
	bool bLookLightning = false;
	int32 LookSeed = 0;
	const FFlightSimWeather* WeatherRef = nullptr;

	FFlightSimGroundDetail Scatter;
	// dust-humidity-haze: the overlay after ApplyAtmosphere (FlightSimDustHaze.h).
	FFlightSimDustHaze DustHaze;
	TArray<TSharedPtr<FJsonValue>> Frames;
};
