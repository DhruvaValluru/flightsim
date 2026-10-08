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
//
// W5 (the world engine side, docs/ADVANCEMENTS_BLUEPRINT.md section 4;
// UNCOMPILED here, pinned by tests/test_ue_world_source.py, verified by the
// first Windows build):
//
//  * -scene=<scene document> (scripts/ue_build_scene.py): the Landscape
//    scene level, built in the editor by FlightSimBridgeEditor's
//    ImportLandscape from W1's import manifest, is loaded into the
//    georeferenced world IN PLACE of the procedural terrain, at the
//    engine position of the bake's south-west sample. The Landscape
//    actor's sha256 tag must equal the card's world.terrain_sha256 (and the
//    bake's own digest); the scene level and the land-cover layers must be
//    the card's; the georeferencing's axes must be the ones the scene was
//    built for. Anything else is refused world.scene_stale by name; a
//    scene that cannot be loaded at all world.scene_missing.
//  * the moon: a SECOND directional light, AtmosphereSunLightIndex 1, in
//    lux, from the card's look.night (refused look.moon / night.sun_units);
//  * the starfield: a sphere drawn with M_Starfield from the card's
//    stars_mode (the cached BSC5, its sha256 checked, or the procedural
//    law; refused look.stars), hidden from every label capture;
//  * rain: the M_RainStreaks blendable on the BEAUTY capture only, never a
//    label capture (refused look.precipitation_particles);
//  * cloud drift: the cloud material's wind offset advanced per tick from
//    the card's look.cloud_drift (refused look.cloud_drift_parameter);
//  * world_applied{landscape, imagery, land_cover, vegetation, buildings,
//    runway, night, precipitation, cloud_drift, materials} for render.json,
//    graded by core/capture/verify.py check.world_record where present.
//
// The drape material (core/xplane/drape.py material_block; UNCOMPILED here,
// pinned by tests/test_ue_materials.py and tests/test_ue_world_source.py,
// verified by the first Windows build): a drape sidecar with a "material"
// block also drives M_TerrainImagery's role weights, weather snow level and
// water mask (maps on the composite's own UV grid), the simulator's ground
// textures as world-tiled detail albedos (and their normals, once the
// extractor pulls any), the weather snow albedo and normal, the noise, and
// every scalar the block carries; and it hands "Imagery" the block's BASE
// image (material.textures.imagery: the role blend with each tile replaced
// by its mean colour, the water as the composite paints it, no weather
// snow) in place of the composite, so detail and weather snow are applied
// once, by the material. Each parameter is looked up on the instance FIRST
// and recorded applied / absent / not in the sidecar, a named file that is
// not there recorded missing -- never a refused render: a sidecar without
// the block, or a material without the parameters, draws the composite
// alone, as every measured render before the block, and a block without
// the base image, or whose image does not load, keeps the composite
// (texture.file) on "Imagery"; the record says which (imagery_source;
// look_applied.terrain_material, ImageryMaterial for the commandlet's
// scene record). The georeferenced tiles carry tangents (the raster's east
// direction lying in the surface; the bitangent +V, its flip MEASURED
// through the georeferencing, not assumed) so the normal maps have a basis.

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "FlightSimHeightfield.h"
#include "FlightSimSky.h"

class AActor;
class ADirectionalLight;
class AGeoReferencingSystem;
class ALandscapeProxy;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UInstancedStaticMeshComponent;
class UPointLightComponent;
class UProceduralMeshComponent;
class USceneCaptureComponent2D;
class USkyAtmosphereComponent;
class UTexture;
class UStaticMeshComponent;
class UTexture2D;
class UVolumetricCloudComponent;
class UWorld;

// W5: the actor tags a scene level carries. FlightSimBridgeEditor's
// ImportLandscape writes the terrain pair, scripts/ue_build_scene.py the
// rest (its TAG_* constants, pinned equal by tests/test_ue_world_source.py);
// the render reads them and nothing else identifies a scene actor.
namespace FlightSimWorld
{
	// The Landscape actor of a scene level.
	inline constexpr const TCHAR* TerrainTag = TEXT("FlightSim.Terrain");
	// "FlightSim.TerrainSha256=<the bake's sha256>": the digest the Landscape
	// was imported from (W1's manifest bake.sha256, the bake sidecar's own).
	inline constexpr const TCHAR* TerrainSha256TagPrefix = TEXT("FlightSim.TerrainSha256=");
	// The actors whose primitives carry the card's vegetation:all /
	// building:all int_id in the ID pass (the 8-bit stencil's aggregates).
	inline constexpr const TCHAR* VegetationTag = TEXT("FlightSim.vegetation");
	inline constexpr const TCHAR* BuildingTag = TEXT("FlightSim.building");
	// The runway plane and its lights: ground, stencilled as the terrain.
	inline constexpr const TCHAR* RunwayTag = TEXT("FlightSim.runway");
	// The object ids the two aggregate tags answer to (core/capture/objects.py).
	inline constexpr const TCHAR* VegetationObjectId = TEXT("vegetation:all");
	inline constexpr const TCHAR* BuildingObjectId = TEXT("building:all");
}

// W5: the land-cover ID pass's registration, measured at scene load (never
// assumed): the engine position of the bake grid's north-west cell and the
// signed engine step of one cell east (X) and one row south (Y), both
// through the georeferencing system, so M_LandcoverID maps a pixel's world
// position to the class-code raster cell exactly as the verifier's own
// unprojection maps it to the bake's affine.
struct FFlightSimLandcoverPass
{
	bool bReady = false;
	UTexture* ClassMap = nullptr;
	FString ClassMapAsset;
	FString ClassMapSha256;
	FVector OriginCm = FVector::ZeroVector;    // the NW cell (row 0, col 0), engine cm
	double CellXCm = 0.0;                      // one column east, engine X cm
	double CellYCm = 0.0;                      // one row south, engine Y cm (signed)
	double SkewCm = 0.0;                       // the cross terms, recorded
	int32 GridWidth = 0;
	int32 GridHeight = 0;
};

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
	// S4: the sun's illuminance in LUX (light_units 'physical'), from the
	// card's look.sun_lux or -sun-lux= (the commandlet resolves and refuses
	// it). 0 keeps the unitless SceneEngineSunUnitless sun every Gate 6
	// clause was tuned on, byte-identical. A directional light's intensity
	// IS lux in this engine; what the number MEANS at the surface once the
	// sky atmosphere's transmittance is applied on top is the calibration
	// frame's measurement, not this file's claim.
	double SunLux = 0.0;
	FString SunLuxSource;

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
	// Its optional "material" block (core/xplane/drape.py) drives the drape
	// material's maps, detail textures and scalars; a missing piece there
	// is recorded, never refused (the file comment).
	FString ImagerySidecarPath;
	// Exponential height fog density: 0.0025 is Gate 6's clear day; the
	// showcase's "hazy" raises it. Recorded in the manifest. When the card
	// carries a look block this is its fog_extinction_per_m (Koschmieder
	// 3.912 / V); whether FogDensity IS a per-metre extinction is Gate 6's
	// extinction clause to measure, not this file's to claim.
	float FogDensity = 0.0025f;

	// X-Plane lighting colours (-xplane-direct / -xplane-ambient /
	// -xplane-horizon, from webapp.runs.xplane_lighting_flags): the sun's
	// light colour, the sky light's colour and the height fog's
	// inscattering colour, read from X-Plane's own sky lookup for the
	// look's sun position and sky condition. COLOURS only: intensities,
	// exposure and fog density are untouched. False = nothing is applied
	// and the scene is exactly the one built without the flags. Recorded
	// in look_applied.xplane_lighting. UNCOMPILED when written (no engine
	// on the authoring machine); the first build verifies.
	bool bXPlaneLighting = false;
	FString XPlaneCondition;
	FColor XPlaneDirect = FColor::White;
	FColor XPlaneAmbient = FColor::White;
	FColor XPlaneHorizon = FColor::White;

	// The lighting block's engine knobs (core/scene/lighting.py, through
	// -sun-intensity-scale= -sky-light-scale= -sun-temperature=
	// -sun-source-angle=, core/render/flags.py LIGHTING_FLAGS): a factor on
	// the sun's intensity and on the sky light's, the sun's colour
	// temperature in kelvin, and the sun disc's angular diameter in degrees
	// (shadow-edge softness). Negative (zero for the temperature) = not
	// stated: the scene is exactly the one built without the flags. Applied
	// after the physical sky and the X-Plane colours; recorded in
	// look_applied.lighting. Preset values are uncalibrated against Gate 6.
	// UNCOMPILED when written (no engine on the authoring machine).
	double SunIntensityScale = -1.0;
	double SkyLightScale = -1.0;
	double SunTemperatureK = 0.0;
	double SunSourceAngleDeg = -1.0;

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

	// -- W5: the world engine side ------------------------------------------
	// -scene=<scene document> (scripts/ue_build_scene.py writes it beside the
	// bake): the Landscape scene level loaded in place of the procedural
	// terrain. Empty = the procedural route, byte-identical to before.
	FString SceneDocumentPath;
	// The run card as parsed JSON: its world block (terrain_sha256,
	// scene_level, layers[]) is what the scene is matched against at load,
	// its look block (night, precipitation, cloud_drift) what the world look
	// draws, its latitude_deg what the starfield's pole is tilted by. Null =
	// no card-driven world look (every W5 row recorded as not asked).
	TSharedPtr<FJsonObject> Card;
	// Where the cached star catalogue lives (assets/stars/bsc5-short.json);
	// only read for stars_mode catalogue.
	FString StarCataloguePath;
	// -- physical sky (-sky=, core/sky/plan.py) ---------------------------
	// Null renders the calibrated legacy scene exactly as before. Non-null
	// replaces the sun's direction and intensity, the fog's light source
	// and adds moon, stars and clouds (FFlightSimSky); SunRotation is then
	// ignored. On an imagery drape its verified night-lights sidecar, if
	// the plan names one, is added as emission.
	const FFlightSimSkyPlan* SkyPlan = nullptr;
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
	// S4: the bias values on record -- 9.5 (noon), 10.5 (dawn), 11.0 (the
	// default, Gate 6's low sun) -- are the OLD scale, tuned against the
	// unitless 8.0 sun. With the sun in lux they over-expose by
	// log2(lux / 8) stops (render.json look_applied.sun.bias_overexposure_
	// stops) until Gate 6's four exposure clauses are re-pinned on the box.
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

	// Visual plan V0, "beauty" quality: Lumen global illumination and
	// Lumen reflections as per-view post-process overrides on the capture
	// (the camera of record), so the project-wide defaults -- and every
	// "measure" render Gate 6 passed on -- stay exactly as they were.
	// Whether Lumen actually runs inside a scene capture on this engine
	// build is a probe-render question, not a claim this call makes.
	static void ApplyBeautyPostProcess(USceneCaptureComponent2D* Capture);

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
	// The drape material's record (the file comment): {"version",
	// "imagery_source", "applied", "absent", "missing_files",
	// "not_in_sidecar", "textures", "scalars", "north_axis_measured",
	// "flip_tangent_y", ...}; {"version": 0} for a sidecar without the
	// block. The same object as LookApplied.terrain_material, kept here for
	// the commandlet's scene record beside the imagery_* fields. Valid after
	// Build() on the imagery route (null otherwise).
	TSharedPtr<FJsonObject> ImageryMaterial;
	// The physical sky's objects and what it managed to draw.
	FFlightSimSky PhysicalSky;
	// Night-lights drape provenance, or why none was drawn.
	FString NightLightsSha256;
	FString NightLightsAttribution;
	FString NightLightsNote;
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

	// -- W5: the world engine side ------------------------------------------
	// The card's look rows the world look draws: the moon (the second
	// directional light), the starfield sphere and the cloud drift; refused by
	// name (look.moon, night.sun_units, look.stars, look.cloud_drift_parameter)
	// when they cannot be drawn exactly. Called by Build after the clouds.
	bool BuildWorldLook(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	                    FString& Error);

	// The rain: M_RainStreaks as a post-process blendable on the BEAUTY
	// capture only (the label captures never see it: their ConfigureLabelCapture
	// adds no blendable of the look), streak length and direction from the
	// card's look.precipitation.streak_px[CameraId]. A card without a rain
	// rate adds nothing. Refused look.precipitation_particles when the
	// material is absent or the card carries no streak for this camera.
	bool ApplyRainToBeauty(USceneCaptureComponent2D* Beauty, const FString& CameraId,
	                       FString& Error);

	// Per tick, before the captures: the cloud material's wind offset at the
	// FDM's own time (the drift vector parameter), and the rain streaks'
	// phase. Deterministic in TimeSeconds (Gate 10-R).
	void AdvanceWorld(double TimeSeconds);

	// -- the weather look (FlightSimWeatherLook.cpp) ------------------------
	// The card's weather_look block (core/scene/weather_look.py): the flat
	// ground's material from the surface word, the storm's rain shafts and
	// lightning (beauty-only actors), recorded in look_applied.weather_look.
	// A card without the block changes nothing. Missing materials are
	// recorded as absent, never refused: the look is visual only.
	// Called by Build after the flat ground exists.
	bool ApplyWeatherLook(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	                      FString& Error);
	// M_LensDrops on the BEAUTY capture only, scaled by the block's rain
	// rate; nothing without a rate.
	void ApplyLensDropsToBeauty(USceneCaptureComponent2D* Beauty);
	// M_IceOverlay as the overlay material of every static mesh part of the
	// airframe; its IceAmount follows the card's icing_schedule eta(t)
	// (AdvanceWorld). Nothing without ice on the block.
	void ApplyIceOverlay(AActor* Airframe);
	// The lightning schedule and the ice ramp at the FDM's time (from
	// AdvanceWorld): deterministic in TimeSeconds and the block's seed.
	void AdvanceWeather(double TimeSeconds);
	// The flash on/off law, pure (pinned by test): 0..1 at TimeSeconds for
	// a storm seeded with Seed.
	static double LightningFlash(double TimeSeconds, int32 Seed);

	// -- the rain the camera sees (FlightSimRainParticles.cpp) ---------------
	// The card's rain_particles block (core/scene/rain_particles.py): real
	// 3-D drops, one instanced thin cylinder each, in a world-aligned box
	// ahead of the camera, drawn on the beauty capture only (a beauty-only
	// actor: the label captures never see it). Each drop's diameter is drawn
	// from the block's truncated Marshall-Palmer law with the block's seed,
	// its fall speed from the Atlas law. A card without the block changes
	// nothing; a missing mesh or material is recorded, never refused.
	// Called by Build after the weather look.
	bool ApplyRainParticles(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	                        FString& Error);
	// Per captured frame, after the camera is placed: every drop at the
	// FDM's time (world-fixed, falling, wrapped into the box around this
	// camera), drawn as its motion relative to the camera over the block's
	// streak exposure, at least MinWidthPx wide at its range with its
	// opacity scaled by the share of that width the drop covers.
	// Deterministic in TimeSeconds and the camera's pose and velocity.
	void AdvanceRain(double TimeSeconds, const FVector& CameraLocationCm,
	                 const FRotator& CameraRotation, const FVector& CameraVelocityCmPerS,
	                 double HorizontalFovDeg, int32 WidthPx);
	bool DrawsRainParticles() const { return RainDrops != nullptr; }
	// The truncated exponential's inverse CDF (core/scene/rain_particles.py
	// diameter_mm, pinned by test): U in [0, 1) -> D in [DMinMm, DMaxMm].
	static double RainDropDiameterMm(double U, double LambdaPerMm, double DMinMm, double DMaxMm);
	// Value wrapped into [-Half, Half): the box's toroidal wrap.
	static double RainWrap(double Value, double Half);

	// The moon light's rotation from the card's elevation and COMPASS azimuth:
	// the sun's convention (core/scenario/randomization.py engine_sun_azimuth:
	// the yaw toward a compass bearing b is 90 - b; the light travels 180
	// degrees from it), so FRotator(-elevation, 270 - azimuth, 0).
	static FRotator MoonRotation(double ElevationDeg, double CompassAzimuthDeg);

	// The cloud offset after Seconds of drift at Mps FROM FromDeg (the
	// meteorological direction): downwind, metres, engine X east / Y north.
	static FVector CloudDriftOffsetMetres(double Mps, double FromDeg, double Seconds);

	// The starfield sphere's orientation: local Z the celestial pole (tilted
	// to the latitude), local X the direction of right ascension 0h at the
	// local sidereal angle, in the engine frame X east / Y north / Z up.
	static FQuat StarfieldRotation(double LatitudeDeg, double LocalSiderealDeg);

	// Everything the world look and the scene level applied, for render.json
	// world_applied (the ten keys; a row the card did not ask for says so).
	TSharedPtr<FJsonObject> WorldApplied;
	// Actors the label captures must not see (the starfield sphere): the
	// label passes are byte-identical with the world look on and off.
	TArray<AActor*> BeautyOnlyActors;
	// The scene level's Landscape (null on the procedural route).
	ALandscapeProxy* SceneLandscape = nullptr;
	ADirectionalLight* Moon = nullptr;
	AActor* Starfield = nullptr;
	// The land-cover ID pass's registration (bReady only on a scene with a
	// class map).
	FFlightSimLandcoverPass Landcover;
	// The scene document's layers [{code, key, sha256}] as loaded.
	TArray<TSharedPtr<FJsonValue>> SceneLayers;
	// Components the scene level tagged, counted at load (the stencil loop
	// gives them their aggregate ids).
	int32 VegetationComponents = 0;
	int32 VegetationInstances = 0;
	int32 PcgComponents = 0;
	int32 BuildingComponents = 0;
	int32 RunwayComponents = 0;
	// The card's look.precipitation row (null without a rain rate).
	TSharedPtr<FJsonObject> CardPrecipitation;

private:
	// W5: the scene level in place of the procedural terrain (see the file
	// comment). Called by Build on the georeferenced route when the options
	// carry a scene document.
	bool LoadSceneLevel(UWorld* World, const FFlightSimVisualSceneOptions& Options,
	                    FString& Error);
	// W5: the transient star texture for the sphere, from the catalogue or the
	// procedural law; returns the star count drawn.
	UTexture2D* BuildStarTexture(const FString& Mode, const FFlightSimVisualSceneOptions& Options,
	                             int32& StarCount, FString& Source, FString& Error);
	// W5: the cloud material instance and its drift parameter (NAME_None when
	// the material exposes none), kept for AdvanceWorld.
	UMaterialInstanceDynamic* CloudMaterialInstance = nullptr;
	FName CloudDriftParameter;
	double DriftMps = 0.0;
	double DriftFromDeg = 0.0;
	UMaterialInstanceDynamic* RainInstance = nullptr;
	// The weather look's state (FlightSimWeatherLook.cpp).
	TSharedPtr<FJsonObject> WeatherLook;
	UStaticMeshComponent* FlatGround = nullptr;
	UMaterialInstanceDynamic* LensDropsInstance = nullptr;
	UMaterialInstanceDynamic* IceInstance = nullptr;
	UMaterialInstanceDynamic* LightningInstance = nullptr;
	UPointLightComponent* LightningLight = nullptr;
	double IceEtaMax = 0.0;
	double IceOnsetSeconds = 0.0;
	double IceRampSeconds = 0.0;
	int32 WeatherSeed = 0;
	// The rain particles' state (FlightSimRainParticles.cpp).
	UInstancedStaticMeshComponent* RainDrops = nullptr;
	TArray<FVector> RainOriginsCm;
	TArray<double> RainDiametersMm;
	TArray<double> RainFallCmPerS;
	TArray<FTransform> RainTransforms;
	TArray<float> RainCoverage;
	double RainBoxCm = 0.0;
	double RainNearCm = 0.0;
	double RainExposureS = 0.0;
	double RainMinWidthPx = 1.0;
	// W5: the scene document (-scene=), parsed once in Build.
	TSharedPtr<FJsonObject> SceneDocument;

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

	// Night-lights texture + its luminance scale from a verified sidecar;
	// null (with NightLightsNote set) when it cannot be used.
	class UTexture2D* LoadNightLights(const FString& SidecarPath,
	                                  double& LuminanceNits);

	// The drape sidecar's "material" block onto the drape's dynamic
	// instance: every texture and scalar it names that the material
	// exposes, each looked up first (FindTextureParameter /
	// FindScalarParameter) and recorded, the base image replacing the
	// composite on "Imagery" when it loads; a missing optional file is
	// recorded, never a failure. bNorthPlusY is the caller's measurement of
	// the engine's north axis (the tiles' bitangent flip), recorded with
	// the tangent basis. Writes ImageryMaterial and
	// LookApplied.terrain_material. UNCOMPILED here.
	void ApplyDrapeMaterial(UMaterialInstanceDynamic* Instance,
	                        const TSharedPtr<FJsonObject>& Sidecar,
	                        const FString& SidecarPath, bool bNorthPlusY);

	// Parsed once, shared by both placements.
	FFlightSimHeightfield Terrain;
};
