// The Phase 6 scene: atmosphere, fog, shadows, terrain, manual exposure.
//
// Everything here follows docs/BRIEF_PHASE6.md, which quotes §6.6 of the brief
// verbatim -- real Earth atmosphere values, multiscattering on, the two
// documented SkyAtmosphere gotchas, height fog with max opacity below 1, and a
// sun that actually casts shadows. Deviations (no Nanite, therefore no VSM;
// no MRQ) are recorded in docs/VALIDITY.md, not silently absorbed.
//
// The terrain is NOT modelled here. It is read from the same baked .r16 + JSON
// heightfield the physics pipeline produces (§3.2) and only turned into
// triangles. Two placements exist:
//
// * Gate 6's: the raster twice, at stated offsets, for the extinction
//   measurement. Byte-for-byte the geometry Gate 6 passed on.
// * Georeferenced (Phase 6B.2): the raster once, at its TRUE position --
//   every vertex through the GeoReferencingSystem's projected-CRS transform,
//   so the ridgelines in frame are the real mountain's ridgelines at the real
//   mountain's heights relative to the flight, not scenery dropped nearby.
//
// The visual terrain carries NO collision in either mode. The flown scenario
// is the spec's -- flat terrain at the spec's elevation, answered by the
// invisible query slab. What IS coupled to the real raster in windy scenarios
// is the wind field (FlightSimOrographic); docs/VALIDITY.md states exactly
// which coupling exists and which does not.

#pragma once

#include "CoreMinimal.h"
#include "FlightSimHeightfield.h"

class AActor;
class ADirectionalLight;
class AGeoReferencingSystem;
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

	// -- Phase 6B ---------------------------------------------------------
	// Georeferenced single-instance placement at the raster's true position.
	bool bGeoreferenced = false;
	AGeoReferencingSystem* GeoReferencing = nullptr;
	// Slope/altitude-driven vertex colours (rock / scrub / valley floor /
	// snow above the sidecar's recorded snowline). An approximation and
	// recorded as one in the manifest; requires the M_VertexColor asset that
	// scripts/ue_create_materials.py builds.
	bool bClassifiedMaterial = false;
	// Path to a drape sidecar (<key>_imagery.json beside its PNG) produced
	// and VERIFIED by core/terrain/imagery.py. Non-empty replaces the
	// classification with true-colour satellite imagery on the georeferenced
	// terrain; the sidecar's license, attribution and sha ride into the
	// manifest. Refused if the file or its texture cannot be loaded --
	// falling back to classification silently would mislabel the surface.
	FString ImagerySidecarPath;
	// Exponential height fog density: 0.0025 is Gate 6's clear day; the
	// showcase's "hazy" raises it. Recorded in the manifest.
	float FogDensity = 0.0025f;
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
	// the camera of record in this pipeline. Bias is per-scene (Gate 6's
	// low-sun value is the default) and constant over any one clip.
	static void ApplyManualExposure(USceneCaptureComponent2D* Capture,
	                                float Bias = 11.0f);

	ADirectionalLight* Sun = nullptr;
	double TerrainPeakMetres = 0.0;   // highest elevation of the placed raster
	FString TerrainSha256;            // from the sidecar, for the manifest
	FString TerrainCrs;
	FString TerrainName;
	// Imagery drape provenance, read from its sidecar when a drape is used.
	FString ImageryFile;
	FString ImagerySha256;
	FString ImageryLicense;
	FString ImageryAttribution;
	FString ImageryDataset;
	// World positions (cm) of the raster's peak sample in each instance --
	// the landmarks the harness samples for the extinction measurement. In
	// georeferenced mode only the near (single) instance exists.
	FVector NearPeakWorldCm = FVector::ZeroVector;
	FVector FarPeakWorldCm = FVector::ZeroVector;

private:
	bool BuildTerrainInstance(UWorld* World, const FString& Name,
	                          const FVector2D& OriginMetres, FString& Error);
	bool BuildGeoreferencedTerrain(UWorld* World,
	                               const FFlightSimVisualSceneOptions& Options,
	                               FString& Error);

	// Parsed once, shared by both placements.
	FFlightSimHeightfield Terrain;
};
