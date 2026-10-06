#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class AActor;
class AGeoReferencingSystem;
class UWorld;

// Google Photorealistic 3D Tiles as the render's ground, through the
// Cesium for Unreal plugin (CesiumRuntime). Opt-in and visual only:
//
//   FLIGHTSIM_GOOGLE_TILES=on       ask for it
//   GOOGLE_MAPS_API_KEY=<key>       a Google Maps Platform key with the
//                                   Map Tiles API enabled
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
	// FLIGHTSIM_GOOGLE_TILES is on.
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

	// Point Cesium's tile selection at this camera and pump the plugin
	// (HTTP, game-thread tasks, tileset tick) until the view reports fully
	// loaded and stays so, or the timeout passes (an error).
	bool WaitForView(const FVector& Location, const FRotator& Rotation,
	                 double FieldOfViewDeg, int32 Width, int32 Height,
	                 FString& Error);

	bool IsEnabled() const { return bEnabled; }
	AActor* GetTilesetActor() const { return Tileset.Get(); }

	// For render.json: the source, the settings, the load statistics and
	// the attribution. Never the key.
	TSharedPtr<FJsonObject> Record() const;

private:
	bool bEnabled = false;
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
	int32 FramesWaited = 0;
	double LongestWaitSeconds = 0.0;
	double TotalWaitSeconds = 0.0;
};
