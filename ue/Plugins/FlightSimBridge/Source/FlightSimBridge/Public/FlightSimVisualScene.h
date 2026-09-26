// The Phase 6 scene: atmosphere, fog, shadows, terrain, manual exposure --
// and, since Phase 2's Look lane, volumetric clouds, aerosol, precipitation
// wetness and physical exposure, every parameter of which is RECORDED in
// LookApplied for render.json.
//
// Everything here follows docs/BRIEF_PHASE6.md, which quotes §6.6 of the brief
// verbatim -- real Earth atmosphere values, multiscattering on, the two
// documented SkyAtmosphere gotchas, height fog with max opacity below 1, and a
// sun that actually casts shadows. Deviations (no Nanite on the procedural
// terrain, no MRQ) are recorded in docs/VALIDITY.md, not silently absorbed.
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
//   Phase 2 (contracts §10): TILED procedural sections at native posting up
//   to a stated triangle budget, one component per tile, instead of one
//   section capped at 701 vertices per side; the achieved posting is
//   recorded (TerrainPostingMetres) rather than assumed.
//
// The visual terrain carries NO collision in either mode. The flown scenario
// is the spec's -- flat terrain at the spec's elevation, answered by the
// invisible query slab. What IS coupled to the real raster in windy scenarios
// is the wind field (FlightSimOrographic); docs/VALIDITY.md states exactly
// which coupling exists and which does not.
//
// What the Look lane does NOT claim (docs/PHASE2_CONTRACTS.md §5.4): no
// precipitation particles (a wetness scalar only), no moon, no stars, no
// cloud drift per tick (recorded, not applied), no sea state, no foliage.
// UNCOMPILED here (no engine in the build container); the first Windows
// build verifies.

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "FlightSimHeightfield.h"

class AActor;
class ADirectionalLight;
class AGeoReferencingSystem;
class UMaterialInterface;
class UProceduralMeshComponent;
class USceneCaptureComponent2D;
class USkyAtmosphereComponent;
class UVolumetricCloudComponent;
class UWorld;

// One cloud layer as the card's look block states it
// (core/scene/weather_visuals.py cloud_layers: {cover, base_m, top_m}).
// Heights are metres above the scene's ground datum (engine Z = 0, the
// spec's terrain_elevation_m) -- stated here, measured by Gate 6's cloud
// base clause.
struct FFlightSimCloudLayer
{
	double CoverFraction = 0.0;   // 0..1
	double BaseMetres = 0.0;
	double TopMetres = 0.0;
};

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
	// showcase's "hazy" raises it. Recorded in the manifest. When the card
	// carries a look block this is its fog_extinction_per_m (Koschmieder
	// 3.912 / V); whether FogDensity IS a per-metre extinction is Gate 6's
	// extinction clause to measure, not this file's to claim.
	float FogDensity = 0.0025f;

	// -- Phase 2 Look lane (contracts §5.4, §10) ----------------------------
	// Cloud layers from the card's look.clouds (or the -cloud-* probe flags).
	// Empty = no volumetric cloud component is spawned (byte-identical to
	// the Phase 10 scene). One UVolumetricCloudComponent draws ONE layer;
	// only the first layer is drawn and the rest are recorded as not drawn.
	TArray<FFlightSimCloudLayer> CloudLayers;
	// Sky Atmosphere Mie scattering scale. Negative = leave the engine's
	// default (1.0) untouched. The card's look.aerosol is RECORDED but not
	// applied by default: it carries the same extinction the fog already
	// carries (weather_visuals.py says driving both double counts), and for
	// the Phase 10 default fog it evaluates to hundreds -- a sky-whitening
	// value. Only the -aerosol= probe flag applies one.
	double AerosolMieScale = -1.0;
	// Precipitation word ("none" | "rain" | "snow") and its 0..1 wetness
	// scalar (weather_visuals.WETNESS). This phase sets a "Wetness" scalar on
	// the georeferenced terrain's material instance and records whether the
	// material exposes it. No particle system is drawn.
	FString Precipitation = TEXT("none");
	double Wetness = 0.0;
	// Cloud drift from the wind: recorded, NOT applied (no per-tick material
	// offset exists on the engine's default cloud material and the render
	// loop is not ticked by this file).
	double CloudDriftMps = 0.0;
	double CloudDriftFromDeg = 0.0;
	// -stars / -moon were asked for: recorded as not modelled.
	bool bStarsRequested = false;
	bool bMoonRequested = false;
	// Triangle budget for the georeferenced terrain (contracts §10: native
	// posting up to a STATED budget). The stride is the smallest that fits.
	int32 TerrainTriangleBudget = 4000000;
};

class FLIGHTSIMBRIDGE_API FFlightSimVisualScene
{
public:
	// Spawns atmosphere, fog, sun, sky light, visible ground, terrain and
	// (when the options carry a layer) clouds into the world. Returns false
	// with a reason if the heightfield cannot be read or fails its integrity
	// check, or a look parameter cannot be applied at all (refused by name,
	// never applied silently to nothing).
	bool Build(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	           FString& Error);

	// §6.6: manual exposure. Applied to the capture, because the capture is
	// the camera of record in this pipeline. Bias is per-scene (Gate 6's
	// low-sun value is the default) and constant over any one clip. The
	// Phase 10 path, byte-identical when no camera exposure is on the card.
	static void ApplyManualExposure(USceneCaptureComponent2D* Capture,
	                                float Bias = 11.0f);

	// Phase 2 (contracts §5.4, brainstorm §9.7): physical exposure. Manual
	// metering at the EV100 the triple implies -- the engine's own physical
	// camera formula from CameraShutterSpeed (1/t), CameraISO and
	// DepthOfFieldFstop with AutoExposureApplyPhysicalCameraExposure on and
	// the bias pinned to zero. Returns the EV100 this file computes for the
	// manifest; that the engine's number agrees is what the manual-vs-
	// physical Gate 6 probe measures. Constant over a clip like the bias.
	static double ApplyPhysicalExposure(USceneCaptureComponent2D* Capture,
	                                    double ApertureF, double ShutterSeconds,
	                                    double Iso);

	// EV100 = log2(N^2 / t * 100 / ISO). Mirrors core/capture/exposure.py
	// (the Python side is the reference; tests/test_exposure.py hand-computes
	// f/8, 1/500 s, ISO 100 -> 14.966 and pins this file's expression).
	static double ExposureValue100(double ApertureF, double ShutterSeconds,
	                               double Iso);

	ADirectionalLight* Sun = nullptr;
	USkyAtmosphereComponent* Atmosphere = nullptr;
	UVolumetricCloudComponent* Clouds = nullptr;
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

	// -- Phase 2: what the georeferenced terrain build ACHIEVED ------------
	// Posting = raster pixel size * stride actually used (0 when no
	// georeferenced terrain was built); tiles and triangles as counted from
	// the sections created, for render.json scene.terrain_*.
	double TerrainPostingMetres = 0.0;
	int32 TerrainStride = 0;
	int32 TerrainTiles = 0;
	int32 TerrainTriangles = 0;

	// -- Phase 2: every look parameter applied, for render.json look_applied.
	// Built by Build(); each row says what was set on which component, or
	// that it was recorded and NOT applied and why. Valid after Build().
	TSharedPtr<FJsonObject> LookApplied;

private:
	bool BuildTerrainInstance(UWorld* World, const FString& Name,
	                          const FVector2D& OriginMetres, FString& Error);
	bool BuildGeoreferencedTerrain(UWorld* World,
	                               const FFlightSimVisualSceneOptions& Options,
	                               FString& Error);
	bool BuildClouds(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	                 FString& Error);
	// Sets the terrain material's "Wetness" scalar when the material exposes
	// one, and records either way. Returns the material to draw with (a
	// dynamic instance when a scalar was set).
	UMaterialInterface* ApplyWetness(UWorld* World, UMaterialInterface* Material,
	                                 const FFlightSimVisualSceneOptions& Options);

	// Parsed once, shared by both placements.
	FFlightSimHeightfield Terrain;
};
