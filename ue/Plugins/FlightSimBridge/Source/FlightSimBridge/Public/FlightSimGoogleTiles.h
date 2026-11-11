#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class AActor;
class AGeoReferencingSystem;
class UWorld;

// Google Photorealistic 3D Tiles as the render's ground, through the
// Cesium for Unreal plugin (CesiumRuntime). The ground of EVERY terrain
// render (the owner's rule, 2026-10-09; visual only):
//
//   FLIGHTSIM_GOOGLE_TILES=off      the baked ground instead (the only
//                                   way the tiles are off; on by default)
//   GOOGLE_MAPS_API_KEY=<key>       a Google Maps Platform key with the
//                                   Map Tiles API enabled, or
//   CESIUM_ION_TOKEN=<token>        a Cesium ion access token: the same
//                                   tiles through Cesium ion (asset 2275207)
//   FLIGHTSIM_GOOGLE_TILES_SSE=8    Cesium's maximum screen-space error
//                                   (lower is sharper and heavier; 8)
//   FLIGHTSIM_GOOGLE_TILES_TIMEOUT=180   seconds a frame may wait for its
//                                   tiles before the render refuses
//
// The physics, the labels' geometry and the verifier keep the baked
// heightfield; only what the cameras SEE changes. The scene's own ground
// and terrain actors (tagged FlightSim.terrain) are hidden so the two
// grounds never draw through each other. Every frame waits until Cesium
// reports the view fully loaded, from that frame's own camera, before
// anything is captured, so the beauty, ID and depth passes see the same
// tiles.
//
// Built only when the Cesium plugin is installed (FlightSimBridge.Build.cs
// defines WITH_FLIGHTSIM_CESIUM); without it, asking refuses by name.
// Use of the tiles is governed by the Google Maps Platform terms; the
// render records the attribution they require, never the key.
class FLIGHTSIMBRIDGE_API FFlightSimGoogleTiles
{
public:
	// Not switched off (FLIGHTSIM_GOOGLE_TILES=off): on by default.
	static bool Requested();
	// This build carries the Cesium integration.
	static bool Available();

	// Georeference Cesium at the scene origin (the engine frame's Z=0 is
	// the card's orthometric terrain elevation, so the ellipsoidal origin
	// height is that plus the geoid undulation there) and spawn the
	// tileset. Refuses when the engine frame is not east-south-up, the
	// frame Cesium places tiles in.
	bool Enable(UWorld* World, AGeoReferencingSystem* GeoReferencing,
	            double LatitudeDeg, double LongitudeDeg,
	            double OrthometricHeightM, double UndulationM,
	            FString& Error);

	// Hide every actor tagged FlightSim.terrain; returns how many.
	int32 HideOwnTerrain(UWorld* World);

	// The tiles are not drawn for this scene, for a reason stated by name
	// (render.json google_tiles.declined). Only for a scene that stands
	// nowhere on Earth: a -terrain= raster the commandlet places in the
	// engine frame without -GeorefTerrain (the Gate 6 ridge), whose own
	// ground the measurements read. Every georeferenced terrain render
	// still draws the tiles or refuses; this is not a way off.
	void Decline(const FString& Reason) { DeclinedReason = Reason; }

	// Point Cesium's tile selection at this camera and pump the plugin
	// (HTTP, game-thread tasks, tileset tick) until the view reports fully
	// loaded and stays so, or the timeout passes (an error). A view stuck
	// for 30 s (a failed request Cesium never retries) is reloaded.
	bool WaitForView(const FVector& Location, const FRotator& Rotation,
	                 double FieldOfViewDeg, int32 Width, int32 Height,
	                 FString& Error);

	bool IsEnabled() const { return bEnabled; }
	AActor* GetTilesetActor() const { return Tileset.Get(); }
	// Lane B terrain detail (2026-11-11): the engine origin's orthometric
	// height (engine Z 0), so the beauty tiles material's snowline is an
	// altitude (MPC_FlightSimWorld GroundAltitudeM). Meaningful only enabled.
	double GetOriginOrthometricHeightM() const { return OriginEllipsoidHeightM - UndulationM; }

	// For render.json: the source, the settings, the load statistics and
	// the attribution. Never the key.
	TSharedPtr<FJsonObject> Record() const;

	// -- visual overhaul, world lane (2026-11-09): BEAUTY ONLY ---------------
	// The beauty look on the tileset (FFlightSimWorldBeauty calls it only
	// under -quality=beauty; a measure render never does): Material as the
	// tileset's material (M_FlightSimTilesBeauty, driven by MPC_FlightSimWorld)
	// and Cesium's smooth normals on, then a tileset refresh. The tiles stay
	// the ground (the owner's rule): nothing here can turn them off.
	// UNVERIFIED: the Cesium for Unreal headers are not on the authoring
	// machine, so every Cesium setting is reached by REFLECTION by name
	// (the UFunction SetMaterial, else the UPROPERTY Material; the bool
	// GenerateSmoothNormals) and the record says which names were found, and
	// lists the tileset's rendering properties so the render machine sees the
	// real names. Applied only on a Cesium for Unreal 2.x or later (the
	// installed plugin's VersionName). Lane B (2026-11-11): the beauty's
	// finer tile selection, maximum screen-space error BeautyScreenSpaceError
	// (FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE, default 6) unless
	// FLIGHTSIM_GOOGLE_TILES_SSE states one. Returns the record (never fails: a
	// look that cannot be applied is recorded, the tiles draw as before).
	TSharedPtr<FJsonObject> ApplyBeautyLook(class UMaterialInterface* Material);

	// The installed Cesium for Unreal plugin's VersionName ("2.30.0"), read
	// from its .uplugin under the project's or the engine's plugins; empty
	// when none is found.
	static FString CesiumPluginVersion();

	// -- round-2b terrain-ocean (2026-11-09): BEAUTY ONLY --------------------
	// The commandlet calls it once, under -quality=beauty, after the whole
	// scene (world lane, dust haze, weather) is built and the camera sits at
	// its first pose; a measure render never does. Two things, both visual:
	//
	// * the ground reads through the haze. Round 0 #06 (SFO, moderate rain,
	//   3000 m) was a flat grey slab: the rain's Koschmieder extinction
	//   (visibility 5 km) drawn as height fog with a ~50 km scale height left
	//   the tiles 3 km below at optical depth ~10 (only the fog's 8 % max
	//   opacity floor showed). When the camera is CameraAglM >= 1000 m above
	//   the origin's ground, the height fog (both layers) and the sky
	//   atmosphere's Mie layer are scaled by ONE factor so the optical depth
	//   along the read ray (the camera's height over sin 10 deg) is at most
	//   1.5. UNCALIBRATED; recorded with every number before and after.
	// * the open sea's surface. SeaRadiusM > 0 (-beauty-sea-radius-m=, which
	//   webapp/runs.py sends only for a beauty render over open ocean, the
	//   radius inside the GLO-30 land-free cells) draws a spherical cap of
	//   M_Ground_Ocean at sea level (Earth's curvature, 2 m above the geoid)
	//   over Google's matte ocean imagery: water colour, the waves' normal,
	//   the sky's reflection (screen-space and sky-light; no Lumen needed).
	//   The tiles stay drawn under it (the owner's rule: never off). The cap
	//   is added to BeautyOnlyActors, so no label pass ever sees it.
	// Returns the record (also written into Record() as beauty_ground).
	TSharedPtr<FJsonObject> ApplyBeautyGround(UWorld* World, double CameraAglM, double SeaRadiusM,
	                                          TArray<AActor*>& BeautyOnlyActors);

	// Round 1 hang (2026-11-09), the constrained GPU only (the commandlet's
	// -sky-capture-restore=): ApplyBeautyGround's haze scale taken off for the
	// ONE sky light capture (the fog layers and the Mie layer at the values the
	// scene had before it, as ef361bd6 drew them) and put back after it. The
	// record says what was held; nothing when the haze was not scaled.
	TSharedPtr<FJsonObject> SuspendBeautyHaze();
	void ResumeBeautyHaze();

private:
	bool bEnabled = false;
	bool bViaIon = false;
	TWeakObjectPtr<AActor> Tileset;
	TWeakObjectPtr<AActor> CameraManager;
	int32 CameraId = -1;
	double MaximumScreenSpaceError = 8.0;
	double TimeoutSeconds = 180.0;
	double OriginLatitudeDeg = 0.0;
	double OriginLongitudeDeg = 0.0;
	double OriginEllipsoidHeightM = 0.0;
	double UndulationM = 0.0;
	int32 HiddenActors = 0;
	FString DeclinedReason;
	int32 FramesWaited = 0;
	int32 TileRefreshes = 0;
	double LongestWaitSeconds = 0.0;
	double TotalWaitSeconds = 0.0;
	// round-2b terrain-ocean: ApplyBeautyGround's record (null: not run).
	TSharedPtr<FJsonObject> BeautyGround;
	// Round 1 hang: what ApplyBeautyGround scaled (the values before it), and
	// what SuspendBeautyHaze held across the sky capture.
	struct FHazeFogRow
	{
		TWeakObjectPtr<class UExponentialHeightFogComponent> Fog;
		float DensityBefore = 0.0f;
		float SecondDensityBefore = 0.0f;
		float DensityHeld = 0.0f;
		float SecondDensityHeld = 0.0f;
	};
	struct FHazeMieRow
	{
		TWeakObjectPtr<class USkyAtmosphereComponent> Atmosphere;
		float ScatteringBefore = 0.0f;
		float AbsorptionBefore = 0.0f;
		float ScatteringHeld = 0.0f;
		float AbsorptionHeld = 0.0f;
	};
	TArray<FHazeFogRow> HazeFogRows;
	TArray<FHazeMieRow> HazeMieRows;
	bool bHazeSuspended = false;
};
