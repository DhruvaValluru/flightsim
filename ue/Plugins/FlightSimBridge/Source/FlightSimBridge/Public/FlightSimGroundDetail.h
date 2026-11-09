// Near-ground geometry for the beauty render: trees, shrubs, rocks and grass
// scattered over the Google tiles (visual overhaul, world lane, 2026-11-09).
//
// BEAUTY ONLY (built by FFlightSimWorldBeauty, which only -quality=beauty
// reaches) and VISUAL ONLY: no collision, nothing the flight model or the
// ground callback sees. The sidecar (-ground-scatter=<path>, written by
// core/scene/world_beauty.py scatter_sidecar) states a seed, a region around
// the start, an exclusion disc, and per species a mesh, a density, a size
// range and its asset pin (source URL, licence, sha256). The placement law is
// the pure block below FLIGHTSIM-SCATTER-PURE-BEGIN in FlightSimGroundDetail.cpp,
// compiled and checked against Python by tests/test_world_beauty.py.
//
// Each candidate is traced straight down onto the tiles (the tileset's own
// hits only when the tiles draw; the scene's hidden baked ground is ignored),
// rejected on a slope over max_slope_deg or a probe ring spanning more than
// step_reject_m (a roof or cliff edge), sunk by sink_m, and drawn as one
// instance of its species' UInstancedStaticMeshComponent. Before the trace the
// tiles are loaded for a nadir view over the region; every frame re-traces the
// instances within resnap_radius_m of the camera onto the tiles that frame
// streamed, so near trees stand on the ground the frame shows.
//
// Labels: the instances are NOT beauty-only. They are in the frame, so they
// are in the mask, class and depth passes of the same frame (a tree in front
// of the aircraft cuts its mask, as it cuts its pixels): labelled as the
// card's vegetation:all aggregate when the card names one (tag
// FlightSim.vegetation), otherwise as the ground they stand on (the terrain
// id the stencil loop gives every untagged actor). Recorded.
//
// A species is drawn only when its pin is complete ("pinned": true, a 64-hex
// sha256, a licence in CC0-1.0 / CC-BY-4.0) and its mesh loads; otherwise it
// is recorded as not drawn with the reason. No asset is bundled.

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class AActor;
class AGeoReferencingSystem;
class FFlightSimGoogleTiles;
class UInstancedStaticMeshComponent;
class UWorld;

class FLIGHTSIMBRIDGE_API FFlightSimGroundDetail
{
public:
	// Reads and checks the sidecar, spawns and places every pinned species.
	// Tiles: when they draw, the region is loaded from a nadir view first and
	// only the tileset's own hits count; otherwise the baked ground. Refuses (ground_scatter.sidecar) a
	// sidecar that cannot be read or is not format flightsim.ground_scatter
	// version 1: it was asked for by path.
	bool Build(UWorld* World, const FString& SidecarPath, const TSharedPtr<FJsonObject>& Card,
	           AActor* Aircraft, FFlightSimGoogleTiles* Tiles, AGeoReferencingSystem* GeoReferencing,
	           FString& Error);

	// The instances within the sidecar's resnap radius of the camera traced
	// again onto the tiles this frame streamed.
	void Resnap(const FVector& CameraCm);

	bool IsBuilt() const { return bBuilt; }
	TSharedPtr<FJsonObject> Record;

	// The engine directions of one metre east and north at the origin (cm),
	// measured through the georeferencing when it exists; east-south-up
	// otherwise (the frame the tiles refuse any other of), recorded.
	FVector EastCm = FVector(100.0, 0.0, 0.0);
	FVector NorthCm = FVector(0.0, -100.0, 0.0);

private:
	struct FSpecies
	{
		UInstancedStaticMeshComponent* Instances = nullptr;
		TArray<FVector2D> GroundXYCm;   // per instance, engine XY of its trace
		TArray<double> Scale;
		TArray<double> YawDeg;
	};

	// One straight-down trace at engine XY: the ground Z (cm) and normal, or false.
	bool TraceGround(double XCm, double YCm, double& OutZCm, FVector& OutNormal) const;

	bool bBuilt = false;
	UWorld* WorldRef = nullptr;
	TWeakObjectPtr<AActor> Tileset;
	TArray<AActor*> Ignored;
	TArray<FSpecies> Species;
	double TraceUpCm = 300000.0;
	double TraceDownCm = 300000.0;
	double SinkCm = 30.0;
	double ResnapRadiusCm = 80000.0;
	int32 ResnapMoved = 0;
	int32 ResnapFrames = 0;
};
