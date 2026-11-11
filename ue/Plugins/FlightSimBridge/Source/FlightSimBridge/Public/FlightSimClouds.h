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
//   the aerial perspective distance scale per preset; the planet's ground
//   albedo (the atmosphere's multiple-scattering ground bounce, never a
//   horizon fill: the main view draws no albedo-lit ground) from the card's
//   surface, darkened by the tiles' own wet law. The height fog's
//   volumetric fog on, the sun casting shadows on the atmosphere and clouds,
//   per-pixel atmosphere transmittance. -NoAerialPerspective (Gate 6's
//   extinction control) is respected: a hidden atmosphere is left alone.
// * CLOUDS. Every volumetric cloud on the engine's simple material (the
//   look's layer, the physical sky's) is redrawn with M_FlightSimCloudLayers
//   (scripts/ue_create_materials.py, assets/shaders/world/cloud_layers.hlsl):
//   layered seeded noise, cumulus / stratocumulus / overcast / nimbostratus
//   shapes chosen from the layer's cover and thickness. The layer's cover
//   stays the card's; its base and top too, unless the aircraft would fly
//   INSIDE it: then the slab moves clear of the aircraft, thickness kept
//   (visual round 2, KeepAircraftClearOfClouds). The storm's M_StormCell is
//   never redrawn (its deck and tower are kept clear the same way, by the
//   weather's ApplyBeautyStormVantage).
//   -beauty-clouds=fair adds a fair-weather cumulus layer when the card has
//   none (a stated stylisation); -beauty-clouds=engine leaves the clouds as
//   built.
// * LABEL HONESTY FOR CLOUDS. Volumetric clouds write no depth and no
//   stencil: the mask, class and depth passes never see them. A cloud
//   between the camera and the aircraft would hide in the beauty what the
//   mask shows. Decision (recorded): clouds stay where the card puts them,
//   except a deck the aircraft would be INSIDE, which moves off it so the
//   subject the mask shows is not buried in cloud; every frame records the camera-to-aircraft path through each layer, its
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
#include "FlightSimSunShafts.h"

class AActor;
class AGeoReferencingSystem;
class FFlightSimGoogleTiles;
class FFlightSimVisualScene;
class FFlightSimWeather;
class UMaterialInstanceDynamic;
class UMaterialParameterCollection;
class UProceduralMeshComponent;
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

	// sun-shafts-sky-occlusion: the cvars Build's sun shafts wrote, put back
	// (the render commandlet's teardown).
	void RestoreCvars();

	// Round 1 hang (2026-11-09): the constrained GPU class, the one predicate
	// (FlightSimClouds.cpp CloudConstrainedGpu): an integrated adapter
	// (GRHIDeviceIsIntegrated) or any adapter below SM6 (D3D11 SM5). It keeps
	// ef361bd6's cloud and sky settings here; the render commandlet reads it
	// for its own constrained-GPU safeguards (FlightSimRenderCommandlet.cpp
	// "constrained gpu"). Beauty only: measure never asks.
	static bool ConstrainedGpu();

	// look_applied.world_beauty (the same object the scene's LookApplied holds).
	TSharedPtr<FJsonObject> Record;

	// render.json root "cloud_occlusion" (the verifier's key, core/capture/
	// beauty_look.py OCCLUSION_POLICIES): the world lane's decision -- clouds
	// stay where the card puts them and the mask is not edited, so the policy
	// is "labels_unoccluded" -- with the largest per-frame covered fraction the
	// slab model gives (1 - the product of the layers' transmittances along
	// the camera-to-aircraft ray). The fraction is MODELLED, never "measured":
	// the verifier grades it beauty-not-label-aligned until
	// experiments/look_label_check.py measures it. Null fraction when a drawn
	// cloud is outside the model (cloud_occlusion_complete false on a frame).
	TSharedPtr<FJsonObject> CloudOcclusionRecord() const;

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
	// Visual round 2 (weather scenes): every redrawn deck, and the storm cell's
	// deck and tower, kept clear of the aircraft (beauty only; recorded in
	// world_beauty.aircraft_clearance).
	void KeepAircraftClearOfClouds(const TSharedPtr<FJsonObject>& Card, AActor* Aircraft,
	                               FFlightSimWeather& Weather);
	// Visual round 5, lane L3: the distant 2D cloud sheet (one earth-curved
	// translucent disc at the deck's altitude, M_FlightSimDistantClouds; no
	// depth, no custom depth, BeautyOnlyActors) and, on the constrained GPU,
	// the volumetric march's trace shrunk to the near field it hands over to.
	// Recorded in world_beauty.distant_clouds. -distant-clouds=on|off.
	void ApplyDistantClouds(UWorld* World, FFlightSimVisualScene& Scene, FFlightSimWeather& Weather,
	                        const FString& Mode, int32 Seed);
	// Visual round 5, lane L3 (optional probe): -sky-hdri=<name> puts the
	// pinned, sun-clamped Poly Haven sky (core/scene/sky_hdri.py, imported as
	// /Game/FlightSim/Sky/T_SkyHdri_<name>) on the sky light as its specified
	// cubemap, clear and hazy presets only. Recorded in world_beauty.sky_hdri.
	bool ApplySkyHdri(FFlightSimVisualScene& Scene, const FString& Name, const TCHAR* Params, FString& Error);

	bool bBuilt = false;
	// A -sky= plan lights the scene (FFlightSimSky): it owns the sun's
	// per-pixel atmosphere transmittance, which this look then leaves alone.
	bool bPhysicalSkyPlan = false;
	// Visual round 6: -deck-shadow=on|off (Build reads it; ApplyClouds applies
	// world_beauty.deck_shadows_beam under it).
	FString DeckShadowSwitch = TEXT("on");
	// Lane C (round 7's green #10): under the storm preset the sky's and the
	// clouds' ground bounce is the surface row's luminance as a grey
	// (world_beauty.neutral_albedo_srgb); -storm-ground-albedo=surface keeps the hue.
	FString StormAlbedoSwitch = TEXT("neutral");
	bool StormNeutralAlbedo() const;
	int32 Preset = 0;
	// The tables in force (the pure block's defaults, then the overrides).
	TArray<double> AtmosphereValues;   // PresetCount x AtmosphereFieldCount
	TArray<double> CloudValues;        // CloudCount x CloudFieldCount
	double CloudExtinctionScale = 1.0;
	double OcclusionFlagTransmittance = 0.5;
	double LightningReferenceLux = 50.0;
	double DetailFadeM = 400.0;
	double DetailScaleM = 2.0;
	double PuddleShare = 0.5;
	double TilesDehaze = 0.8;
	double TilesSaturation = 1.05;
	// The ground's wetness (TilesWetness: the card's, at least the preset's
	// floor) and the card's surface word: the tiles, the scatter and the
	// planet's ground albedo read these one pair.
	double GroundWetness = 0.0;
	FString Surface;
	TArray<FString> Overridden;

	TArray<FCloudLayerState> CloudLayers;
	// Visual round 5, lane L3: the distant sheet (ApplyDistantClouds; Advance
	// re-centres it on the camera and sets its altitude and fade per frame).
	struct FDistantSheetState
	{
		AActor* Actor = nullptr;
		UProceduralMeshComponent* Mesh = nullptr;
		UMaterialInstanceDynamic* Material = nullptr;
		double BaseM = 0.0;
		double TopM = 0.0;
		bool bDrawn = false;
	};
	FDistantSheetState DistantSheet;
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
	// sun-shafts-sky-occlusion: light shafts, cloud shadow on the atmosphere,
	// cloud sky AO, the still tier's fog grid (FlightSimSunShafts.h).
	FFlightSimSunShafts SunShafts;

	// clouds-sky round 2: the cloud cvar ApplyClouds wrote and its value
	// before (empty: untouched), put back by RestoreCvars.
	FString CloudFogAllPixelBefore;

	// dust-humidity-haze: the overlay after ApplyAtmosphere (FlightSimDustHaze.h).
	FFlightSimDustHaze DustHaze;
	TArray<TSharedPtr<FJsonValue>> Frames;
	// The occlusion summary CloudOcclusionRecord reports (Advance keeps it).
	double MaxOccludedFraction = 0.0;
	int32 OcclusionFrames = 0;
	int32 OcclusionFlaggedFrames = 0;
	int32 OcclusionIncompleteFrames = 0;
};
