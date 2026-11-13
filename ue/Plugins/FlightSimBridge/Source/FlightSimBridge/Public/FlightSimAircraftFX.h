// The airframe's beauty look (visual overhaul V7, aircraft lane): PBR look
// instances on the mesh's slots, real nav / strobe / landing lights with
// glowing bulbs, contrails and wingtip vapour, the afterburner plume, and
// (only when asked) the heat haze behind the nozzles.
//
// BEAUTY ONLY. The render commandlet builds it under -Visual -quality=beauty
// with a mesh airframe drawn (not -HideAircraft); a -quality=measure render
// never constructs one, so every measured frame, label and record is
// byte-identical to before (Gate 6 passed on that path).
//
// What it reads (scripts/aircraft_look.py writes both inputs):
//   * <mesh manifest dir>/look_manifest.json -- the lights and nozzles in
//     the ACTOR frame (cm, about the JSBSim structural datum, the frame
//     BuildMeshAirframe hangs the mesh in), each with how it was measured,
//     and every look constant with its UNCALIBRATED stamp;
//   * <asset_path_root>/Look/MI_<slot> -- one look instance per imported
//     material slot (scripts/ue_aircraft_materials.py create_look_instances).
// Either missing is RECORDED (render.json aircraft_look), never refused: the
// look decorates a run that is complete without it. A look manifest that
// exists but does not parse IS refused (aircraft_look.manifest): a broken
// file must not pass as "no look".
//
// Labels match pixels:
//   * the material swap changes shading only: no master uses world position
//     offset, every class master is opaque (the canopy glass included), and
//     custom depth / stencil are per-component settings the commandlet makes
//     after this runs, so mask, class and depth see the same silhouette the
//     beauty draws;
//   * every FX element is its OWN actor attached to the aircraft and listed
//     in BeautyOnlyActors -- never a component of the aircraft actor, whose
//     every primitive the stencil loop labels as the aircraft. The label
//     captures hide them;
//   * point and spot lights move no geometry. The bulbs and the plume are
//     additive (they hide nothing); the trails are translucent media (like
//     the clouds and rain the label captures already omit, a trail in front
//     of the aircraft does not remove it from the mask); the heat haze
//     refracts (pixel-moving) and is OFF unless -heat-haze=on, and the record
//     says so with its bound.
//
// Deterministic: every time-varying element (strobe phase, trail history,
// afterburner glow, haze phase) is driven by the FDM's own state at the
// captured step, never by wall-clock time (replay-identical: Gate 10-R).
//
// UNCOMPILED when written (the authoring Mac's Xcode is above UE 5.7's cap).
// Every engine symbol was grepped in the UE 5.7.4 headers there; the list is
// in scripts/check_bridge_api.sh's aircraft-lane block.
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "FlightSimAircraftWet.h"  // wet-airframe-canopy

#include "FlightSimCondensation.h"  // condensation-solver
#include "FlightSimVisualScene.h"  // FFlightSimCloudLayer (fix pass: contrails in cloud)
#include "Templates/Function.h"

class AActor;
class ADirectionalLight;
class FFlightSimWeather;
class UMaterialInstanceDynamic;
class UPointLightComponent;
class UProceduralMeshComponent;
class USpotLightComponent;
class UWorld;

struct FFlightSimAircraftFXOptions
{
	AActor* Aircraft = nullptr;
	// The -mesh= manifest the airframe was drawn from (its directory holds
	// look_manifest.json; its asset_path_root holds the Look instances).
	FString MeshManifestPath;
	// The card's livery: a livery other than "default" keeps its own material
	// on every slot (the record names that livery; the look does not repaint it).
	FString Livery = TEXT("default");
	// Per-element switches (-aircraft-look=off disables all; -aircraft-lights=,
	// -contrails=, -afterburner=, -heat-haze= one each). Heat haze defaults OFF:
	// it moves pixels.
	bool bMaterials = true;
	bool bLights = true;
	bool bContrails = true;
	bool bAfterburner = true;
	bool bHeatHaze = false;
	// Round 47 (#13's four light lines): the contrail forms over contrail.FormationRampS
	// (on) or over generation 6's 0.04 of its lifetime (off, -contrail-formation-ramp=off).
	bool bContrailFormationRamp = true;
	// The canopy reflection (scripts/aircraft_glass_reflect.py; swarm lane
	// aircraft_exterior.glass.coastal, its opaque tiers 0-1 only): OFF unless
	// -canopy-reflect=on, so a round can A/B it. On, a glass slot that draws
	// its OPAQUE look instance draws the tier's opaque reflect master instead
	// (-canopy-reflect-tier=0, the default: LUT + 64x32 strip; 1: + micro
	// scratches, 128x64 strip). A slot on its thin instance keeps it.
	bool bCanopyReflect = false;
	int32 CanopyReflectTier = 0;
	// The look's X-Plane horizon colour (-xplane-horizon=R:G:B, sRGB8) when the
	// render carries it: the strip's hue follows it. And -xplane-condition=.
	bool bHorizonKnown = false;
	FColor Horizon = FColor::White;
	FString SkyCondition;
	// The scene's sun (FFlightSimVisualScene::Sun; the commandlet sets it):
	// the strip's azimuth and the reflection's gain, read each step.
	ADirectionalLight* Sun = nullptr;
	// round 5 (L4): the render carries -labels. The Thin Translucent canopy
	// instance (Look/MI_<slot>_thin) is applied only when it does not: a
	// translucent pane writes no depth and the ID / depth label captures draw
	// no translucency, so a labelled frame keeps the opaque MI_<slot>.
	bool bLabels = false;
	// Round 23 (2026-11-11): the bisect probes inside the look masters,
	// -aircraft-probe=<comma list> of nocoat, noao, nonormal, nowear, flat,
	// measured-mesh (scripts/aircraft_look.py AIRCRAFT_PROBES, the twin).
	// Effective only with -aircraft-materials=on; recorded in render.json
	// aircraft_look.materials.probes either way.
	TArray<FString> Probes;
	// wet-airframe-canopy: the built weather (its rain wets the airframe), or null.
	const FFlightSimWeather* Weather = nullptr;
	// fix pass: the scene's cloud layers (heights above the ground datum,
	// engine Z = 0, the convention FFlightSimCloudLayer states): a contrail
	// drawn inside a layer fades by its cover (the trail is in the cloud).
	TArray<FFlightSimCloudLayer> CloudLayers;
	// fix pass: a switch word ParseParams could not read (on/1/true or
	// off/0/false only), "" when every switch parsed; Build refuses it by
	// name (aircraft_look.switch) -- a pixel-moving effect fails closed.
	FString SwitchError;

	// condensation-solver: where the vapour test's humidity comes from
	// (-humidity-pct=; the commandlet sets bCardStated from the card).
	FFlightSimCondensationHumidity Humidity;
	// Read the switches above from the commandlet's parameters.
	void ParseParams(const FString& Params);
};

class FFlightSimAircraftFX
{
public:
	// Swap the slots to their look instances and spawn every FX actor. False
	// (with Error) only for a look manifest that exists and cannot be read.
	bool Build(UWorld* World, const FFlightSimAircraftFXOptions& Options, FString& Error);

	// Advance the time-varying elements to the FDM's state at this captured
	// step: ReadProperty is the scenario's property reader (JSBSim names).
	void Advance(TFunctionRef<double(const TCHAR*)> ReadProperty);

	bool IsBuilt() const { return bBuilt; }

	// The engine's bound on how far heat_haze.hlsl moves a pixel (px, along
	// the diagonal) for its peak material offset (render.json
	// aircraft_look.heat_haze.max_material_offset): UE 5.7.4
	// DistortionCommon.ush scales a 2D offset by width x 0.00023 x
	// 1/tan(hFOV/2), the same pixel count per unit on both axes. Twin of
	// scripts/aircraft_look.py heat_haze_max_displacement_px.
	static double HeatHazeMaxDisplacementPx(double MaterialOffset, double WidthPx, double HeightPx, double HFovDeg);

	// The canopy reflection's GlassEnvGain (scene luminance per unit of strip
	// radiance): the strip's anti-sun horizon at 0.10 x SunIntensity / pi,
	// faded out as the sun sets and dimmed by cloud cover; 0 for an interior
	// camera. Twin of scripts/aircraft_glass_reflect.py canopy_reflect_gain.
	static double CanopyReflectGain(double SunIntensity, double SunElevationDeg, double Cover, bool bInterior);

	// The camera of this run looks out through the pane from inside (the
	// card camera's "cockpit" preset, the legacy "shoulder"): the reflect
	// MIDs' gain goes to 0 (the inside of a pane mirrors the cabin, not the
	// sky). Recorded in render.json aircraft_look.materials.canopy_reflect.
	void SetCanopyReflectCamera(bool bInterior, const FString& Preset);

	// Every actor drawn only in the beauty capture (the commandlet appends them
	// to FFlightSimVisualScene::BeautyOnlyActors before any label capture).
	TArray<AActor*> BeautyOnlyActors;
	// render.json "aircraft_look" (absent from a render that built nothing).
	TSharedPtr<FJsonObject> Record;

private:
	struct FLamp
	{
		FString Id;
		FString Kind;
		FVector ActorCm = FVector::ZeroVector;
		double Candela = 0.0;
		bool bStrobe = false;
		bool bLanding = false;
		UPointLightComponent* Point = nullptr;
		USpotLightComponent* Spot = nullptr;
		UMaterialInstanceDynamic* Bulb = nullptr;
		double BulbNits = 0.0;  // the bulb's core luminance, cd/m2 (from its candela)
	};
	struct FNozzle
	{
		FString Id;
		FVector ActorCm = FVector::ZeroVector;
		double RadiusCm = 50.0;
		bool bAfterburner = false;
		FString ThrustProperty;
		double MilThrustLbs = 0.0;
		double MaxThrustLbs = 0.0;
		UMaterialInstanceDynamic* Plume = nullptr;
		UPointLightComponent* PlumeLight = nullptr;
		UMaterialInstanceDynamic* Haze = nullptr;
		double PlumeLuminanceNits = 0.0;  // the look manifest's, 0 when it predates it
	};
	struct FTrailSample
	{
		FVector WorldCm = FVector::ZeroVector;
		double TimeS = 0.0;
	};
	struct FTrail
	{
		FVector SourceActorCm = FVector::ZeroVector;
		AActor* Owner = nullptr;
		UProceduralMeshComponent* Mesh = nullptr;
		UMaterialInstanceDynamic* Instance = nullptr;
		double BaseOpacity = 0.0;
		TArray<FTrailSample> Samples;
		bool bVapour = false;
		bool bEverDrawn = false;
	};

	void ApplyMaterials(const FString& AssetRoot, const FFlightSimAircraftFXOptions& Options);
	void BuildLamp(UWorld* World, const TSharedPtr<FJsonObject>& Row);
	void BuildNozzle(UWorld* World, const TSharedPtr<FJsonObject>& Row, const FFlightSimAircraftFXOptions& Options);
	AActor* SpawnAttached(UWorld* World, const FVector& ActorCm, const TCHAR* Name);
	void RebuildTrail(FTrail& Trail, double NowS, double LifetimeS, double StartWidthM,
	                  double SpreadMPerS, double FormationS);
	double Constant(const TCHAR* Group, const TCHAR* Name, double Fallback) const;
	// The reflect MIDs' sun direction and gain from the sun as it is now.
	void UpdateCanopyReflect();

	bool bBuilt = false;
	bool bFirstAdvance = true;
	AActor* Aircraft = nullptr;
	TSharedPtr<FJsonObject> Constants;
	TArray<FLamp> Lamps;
	TArray<FNozzle> Nozzles;
	TArray<FTrail> Trails;
	// condensation-solver: the humidity-gated vapour sites (FlightSimCondensation.h).
	FFlightSimCondensation Condensation;
	int32 ContrailFrames = 0;
	int32 ContrailInCloudFrames = 0;
	TArray<FFlightSimCloudLayer> CloudLayers;
	int32 VapourFrames = 0;
	double PeakAfterburner = 0.0;
	int32 StrobeOnFrames = 0;
	int32 LandingOnFrames = 0;
	// wet-airframe-canopy: one MID per look slot (the wet scalars), the weather, the wetness.
	TArray<UMaterialInstanceDynamic*> LookMids;
	// The canopy reflection: the reflect MIDs (also in LookMids), what drives
	// their gain, and render.json's aircraft_look.materials.canopy_reflect.
	TArray<UMaterialInstanceDynamic*> ReflectMids;
	ADirectionalLight* ReflectSun = nullptr;
	double ReflectCover = 0.0;
	bool bReflectInterior = false;
	TSharedPtr<FJsonObject> ReflectRow;
	// cockpit-airframe (round 2): mesh manifest beauty_parts, measured part name
	// -> its beauty-only copy's asset name (body -> body_beauty: the same
	// triangles with the .ac crease normals and two-sided back faces).
	TMap<FString, FString> BeautyMeshes;
	const FFlightSimWeather* Weather = nullptr;
	FFlightSimAircraftWet Wet;
};
