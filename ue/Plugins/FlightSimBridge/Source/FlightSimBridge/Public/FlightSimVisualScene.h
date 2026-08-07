// The Phase 6 scene: atmosphere, fog, shadows, terrain, manual exposure.
//
// Everything here follows docs/BRIEF_PHASE6.md, which quotes §6.6 of the brief
// verbatim -- real Earth atmosphere values, multiscattering on, the two
// documented SkyAtmosphere gotchas, height fog with max opacity below 1, and a
// sun that actually casts shadows. Deviations (no Nanite, therefore no VSM;
// no MRQ) are recorded in docs/VALIDITY.md, not silently absorbed.
//
// The terrain is NOT modelled here. It is read from the same baked .r16 + JSON
// heightfield the physics pipeline produces (§3.2): the harness synthesises a
// ridge through core/terrain/synthesis.py and this class only turns that
// raster into triangles. Rendering a terrain the physics pipeline never saw
// would reintroduce the two-lookup failure §1.4 is about, one tier up.
//
// The visual terrain carries NO collision. The flown scenario is the spec's --
// flat terrain at the spec's elevation, answered by the invisible query slab --
// and the ridge is scenery placed away from the flight path. A colliding
// visual ridge would silently change the ground the FDM feels mid-run.

#pragma once

#include "CoreMinimal.h"

class AActor;
class ADirectionalLight;
class UProceduralMeshComponent;
class USceneCaptureComponent2D;
class UWorld;

struct FFlightSimVisualSceneOptions
{
	// Path to a heightfield (with or without extension; .r16 + .json beside
	// it). Empty renders no terrain, which fails Gate 6's terrain clauses --
	// loudly, in the harness, not here.
	FString TerrainPath;
	// Where the terrain raster's south-west corner lands, in metres from the
	// world origin. The near ridge sits ahead of the flight path; the far
	// instance of the same raster sits at extinction distance.
	FVector2D NearTerrainOriginMetres = FVector2D(-8000.0, 6000.0);
	FVector2D FarTerrainOriginMetres = FVector2D(-8000.0, 26000.0);
	// Sun placed low in the north-west, so the east-west ridge throws its
	// shadow band toward the camera side and the aircraft's own shadow lands
	// ahead-right of it, inside the chase framing.
	FRotator SunRotation = FRotator(-20.0, -45.0, 0.0);
	bool bDynamicShadows = true;
};

class FLIGHTSIMBRIDGE_API FFlightSimVisualScene
{
public:
	// Spawns atmosphere, fog, sun, sky light, visible ground and terrain into
	// the world. Returns false with a reason if the heightfield cannot be
	// read or fails its integrity check.
	bool Build(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	           FString& Error);

	// §6.6: manual exposure. Applied to the capture, because the capture is
	// the camera of record in this pipeline.
	static void ApplyManualExposure(USceneCaptureComponent2D* Capture);

	ADirectionalLight* Sun = nullptr;
	double TerrainPeakMetres = 0.0;   // highest elevation of the placed raster
	FString TerrainSha256;            // from the sidecar, for the manifest
	// World positions (cm) of the raster's peak sample in each instance --
	// the landmarks the harness samples for the extinction measurement.
	FVector NearPeakWorldCm = FVector::ZeroVector;
	FVector FarPeakWorldCm = FVector::ZeroVector;

private:
	bool BuildTerrainInstance(UWorld* World, const FString& Name,
	                          const FVector2D& OriginMetres, FString& Error);

	// Parsed once, shared by both instances.
	TArray<uint16> Samples;
	int32 RasterWidth = 0;
	int32 RasterHeight = 0;
	double PixelSizeMetres = 0.0;
	double ScaleMetres = 0.0;
	double OffsetMetres = 0.0;
};
