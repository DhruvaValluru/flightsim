// The airframe's beauty look (FlightSimAircraftFX.h says what, why and what
// it may not touch). Visual overhaul V7, aircraft lane. BEAUTY ONLY.
//
// UNCOMPILED when written: the authoring Mac's Xcode is above UE 5.7's cap.
// Every engine symbol below was grepped in the UE 5.7.4 headers on that
// machine (scripts/check_bridge_api.sh, aircraft-lane block); no Cesium API
// is used here. Every look constant is read from look_manifest.json, where
// scripts/aircraft_look.py stamps each one "UNCALIBRATED: set by probe render
// on the render machine"; the fallbacks below are the same numbers, used only
// when a manifest predates a constant.

#include "FlightSimAircraftFX.h"

#include "Components/LightComponent.h"       // canopy reflection: the sun's Intensity
#include "Components/PointLightComponent.h"
#include "Components/SkyAtmosphereComponent.h"  // generation 16: the scene's atmosphere column
#include "Components/SkyLightComponent.h"       // generation 16: the scene's ground (lower hemisphere)
#include "Components/SpotLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"         // canopy reflection: the scene's sun
#include "Engine/Scene.h"
#include "Engine/StaticMesh.h"  // cockpit-airframe: the beauty body swap
#include "Engine/World.h"
#include "HAL/PlatformMisc.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"           // round 23: GetBaseMaterial()->GetName() (probe slots)
#include "Materials/MaterialInterface.h"
#include "Engine/Texture.h"               // round 23: the flat probe copies BaseColorMap
#include "MaterialShared.h"               // round 25: FMaterialResource (the masters' compile check)
#include "RHI.h"                          // round 25: GShaderPlatformForFeatureLevel
#include "Runtime/Launch/Resources/Version.h"
#include "Math/RotationMatrix.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimAircraftFX, Log, All);

// Round 25: material resources are keyed by shader platform on UE 5.7 and
// later and by feature level before (FlightSimWeather.cpp's twin, its own
// name: unity builds merge the two files).
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 7)
#define FLIGHTSIM_AIRCRAFT_MATERIAL_RESOURCE(Base, World, Platform) ((Base)->GetMaterialResource(Platform))
#else
#define FLIGHTSIM_AIRCRAFT_MATERIAL_RESOURCE(Base, World, Platform) ((Base)->GetMaterialResource((World)->GetFeatureLevel()))
#endif

namespace
{
	// Names are file-unique (NEXT.md gotcha 3: unity builds merge anonymous
	// namespaces).
	constexpr double AircraftFxCmPerMetre = 100.0;
	constexpr double AircraftFxMpsPerKnot = 0.514444;
	constexpr double AircraftFxKelvinPerRankine = 5.0 / 9.0;
	constexpr int32 AircraftFxConeRings = 8;
	constexpr int32 AircraftFxConeSides = 16;
	// round-2b weather-fx (2026-11-09): the lamps' volumetric scattering
	// (the engine's default is 1, a lit solid cone in fog). Fallbacks for a
	// manifest without lights.LandingVolumetricScattering / NavVolumetricScattering;
	// UNCALIBRATED, set by probe render (docs/visual/PROBE_LOG.md ## round-2b weather-fx).
	constexpr double AircraftFxLandingVolumetricScattering = 0.3;
	constexpr double AircraftFxNavVolumetricScattering = 0.5;
	const TCHAR* const AircraftFxLookManifestName = TEXT("look_manifest.json");
	const TCHAR* const AircraftFxLookManifestMagic = TEXT("flightsim-aircraft-look-manifest");
	// scripts/aircraft_look.py MASTER_ROOT + FX_MASTERS.
	const TCHAR* const AircraftFxNavMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_NavLightEmissive.M_NavLightEmissive");
	const TCHAR* const AircraftFxContrailMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftContrail.M_AircraftContrail");
	const TCHAR* const AircraftFxAfterburnerMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftAfterburner.M_AircraftAfterburner");
	const TCHAR* const AircraftFxHeatHazeMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftHeatHaze.M_AircraftHeatHaze");
	// Round 23: -aircraft-probe=flat (scripts/aircraft_look.py PROBE_FLAT_MASTER).
	const TCHAR* const AircraftFxProbeFlatMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftProbeFlat.M_AircraftProbeFlat");
	// Round 24: -aircraft-probe=defaultlit (scripts/aircraft_look.py PROBE_DEFAULT_LIT_MASTER).
	const TCHAR* const AircraftFxProbeDefaultLitMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftPaintDefaultLit.M_AircraftPaintDefaultLit");
	// Round 24: -aircraft-probe=tangentnormal (aircraft_look.PROBE_TANGENT_NORMAL_MASTER).
	const TCHAR* const AircraftFxProbeTangentNormalMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftPaintTangentNormal.M_AircraftPaintTangentNormal");
	// Round 25: -aircraft-probe=coat and the compile fallback (aircraft_look.PROBE_COAT_MASTER).
	const TCHAR* const AircraftFxProbeCoatMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftPaintCoat.M_AircraftPaintCoat");
	// Round 25: scripts/ue_aircraft_master_materials.py LOOK_GENERATION_PARAMETER.
	const TCHAR* const AircraftFxLookGenerationParam = TEXT("LookGeneration");
	// The canopy reflection (scripts/aircraft_glass_reflect.py MASTERS, by
	// tier; LOOK_GENERATION 11), drawn only under -canopy-reflect=on.
	const TCHAR* const AircraftFxGlassReflectMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftGlassReflect.M_AircraftGlassReflect");
	const TCHAR* const AircraftFxGlassReflectFineMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftGlassReflectFine.M_AircraftGlassReflectFine");
	// aircraft_glass_reflect.OPAQUE_GLASS_MASTER: the slots a reflect master may take.
	const TCHAR* const AircraftFxOpaqueGlassMaster = TEXT("M_AircraftGlass");
	// aircraft_glass_reflect.py SKY_HORIZON_SHARE, NIGHT_FADE_DEG, OVERCAST_DIM,
	// STRIP_HORIZON_LUMINANCE (Rec. 709 of glass_coastal.json
	// haze_horizon_linear_rgb 0.74, 0.70, 0.62), STRIP_HORIZON_LINEAR, TINT_BOUNDS.
	constexpr double AircraftFxReflectSkyShare = 0.10;
	constexpr double AircraftFxReflectNightFadeLoDeg = -2.0;
	constexpr double AircraftFxReflectNightFadeHiDeg = 8.0;
	constexpr double AircraftFxReflectOvercastDim = 0.75;
	constexpr double AircraftFxReflectStripHorizonLuminance = 0.702728;
	constexpr double AircraftFxReflectStripHorizon[3] = {0.74, 0.70, 0.62};
	constexpr double AircraftFxReflectTintMin = 0.25;
	constexpr double AircraftFxReflectTintMax = 4.0;
	// The airframe's sky reflection (scripts/aircraft_paint_reflect.py
	// GAIN_PARAMETER / TINT_PARAMETER / SUN_PARAMETER; LOOK_GENERATION 13).
	const TCHAR* const AircraftFxPaintEnvGainParam = TEXT("PaintEnvGain");
	const TCHAR* const AircraftFxPaintEnvTintParam = TEXT("PaintEnvTint");
	const TCHAR* const AircraftFxPaintSunParam = TEXT("PaintSunAzimuthDir");
	// LOOK_GENERATION 16 (scripts/aircraft_scene_sky.py parameters(): the
	// "Paint" / "Glass" prefix + these suffixes; SCENE_SHARE, OVERCAST_SHARE and
	// the UE 5.7 default atmosphere's columns for a scene without one).
	const TCHAR* const AircraftFxSceneScaleSuffix = TEXT("EnvSceneScale");
	const TCHAR* const AircraftFxSceneGroundSuffix = TEXT("SkyGround");
	const TCHAR* const AircraftFxSceneTauSuffix = TEXT("GroundTau");
	const TCHAR* const AircraftFxSceneCoverSuffix = TEXT("SkyCover");
	const TCHAR* const AircraftFxSceneOvercastSuffix = TEXT("OvercastShare");
	// SKY_HORIZON_SHARE 0.10 over the clear sky's horizon share of E / pi, 0.2:
	// the scene path at the strip path's level (half physical: the engine's own
	// specular IBL already mirrors the captured sky, the canopy lane's double count).
	constexpr double AircraftFxSceneSkyShare = 0.10 / 0.2;
	// CIE overcast (Moon & Spencer 1942) zenith over the clear one: 1 - OVERCAST_DIM.
	constexpr double AircraftFxSceneOvercastShare = 1.0 - 0.75;
	// USkyAtmosphereComponent's constructor defaults (UE 5.7): Rayleigh
	// (0.005802, 0.013558, 0.0331) /km over 8 km; Mie extinction 0.003996 +
	// 0.000444 /km over 1.2 km. The green column, 0.108, is near Bucholtz
	// 1995's 0.0973 (Rayleigh optical depth, 550 nm, sea level).
	constexpr double AircraftFxDefaultRayleighPerKm[3] = {0.005802, 0.013558, 0.0331};
	constexpr double AircraftFxDefaultRayleighHKm = 8.0;
	constexpr double AircraftFxDefaultMiePerKm = 0.003996 + 0.000444;
	constexpr double AircraftFxDefaultMieHKm = 1.2;

	// Round 25: why a material would draw the engine's default material on
	// this render (it failed to compile for the world's shader platform, or
	// has no shader map), or empty when it compiled. Rounds 37-40 drew
	// byte-identical frames under five different -aircraft-probe= words and
	// basecolor-debug drew a lit, untextured airframe: the default material
	// a failed compile draws, which no probe could reach. The same check as
	// FlightSimWeather.cpp's cloud materials.
	FString AircraftFxCompileProblem(UMaterialInterface* Material, UWorld* World)
	{
		if (Material == nullptr)
		{
			return TEXT("absent");
		}
		if (World == nullptr)
		{
			return FString();   // nothing to check against; drawn as before
		}
		UMaterial* Base = Material->GetMaterial();
		if (Base == nullptr)
		{
			return TEXT("has no base material");
		}
		const EShaderPlatform Platform = GShaderPlatformForFeatureLevel[World->GetFeatureLevel()];
		FMaterialResource* Resource = FLIGHTSIM_AIRCRAFT_MATERIAL_RESOURCE(Base, World, Platform);
		if (Resource == nullptr)
		{
			return TEXT("has no material resource for this shader platform");
		}
		Resource->FinishCompilation();
		if (Resource->GetCompileErrors().Num() > 0)
		{
			return TEXT("failed to compile: ") + FString::Join(Resource->GetCompileErrors(), TEXT(" | "));
		}
		if (Resource->GetGameThreadShaderMap() == nullptr)
		{
			return TEXT("has no shader map after compiling");
		}
		return FString();
	}
	// scripts/aircraft_look.py FX_PARAMETERS (pinned by tests/test_aircraft_look.py).
	const TCHAR* const AircraftFxParamLightColour = TEXT("LightColour");
	const TCHAR* const AircraftFxParamIntensity = TEXT("Intensity");
	const TCHAR* const AircraftFxParamStrobe = TEXT("Strobe");
	const TCHAR* const AircraftFxParamOpacity = TEXT("Opacity");
	const TCHAR* const AircraftFxParamFormation = TEXT("Formation");
	const TCHAR* const AircraftFxParamFormationRamp = TEXT("FormationRamp");
	// contrail_opacity.hlsl generation 6's fixed ramp (an age fraction).
	constexpr double AircraftFxLegacyFormationRamp = 0.04;
	// LOOK_GENERATION 13 (hyperreal contrails): the break-up strength the C++ sets.
	const TCHAR* const AircraftFxParamPuff = TEXT("Puff");
	// LOOK_GENERATION 14: the per-strip view weight's switch (1 on, 0 off).
	const TCHAR* const AircraftFxParamViewWeight = TEXT("ViewWeight");
	// LOOK_GENERATION 15: the camera-facing ribbon's switch (1 on, 0 off).
	const TCHAR* const AircraftFxParamFacing = TEXT("Facing");
	// The persistence gate: e_sat,water / e_sat,ice by Sonntag (1990)'s Magnus
	// forms (water b 17.62 c 243.12: core/environment/atmosphere.py MAGNUS_B/C;
	// ice b 22.46 c 272.62: aircraft_look.MAGNUS_ICE_B/C). The a cancels. From
	// memory, UNCALIBRATED; 1.62 at -50 degC. The twin is
	// aircraft_look.ice_over_water_saturation_ratio.
	constexpr double AircraftFxMagnusWaterB = 17.62;
	constexpr double AircraftFxMagnusWaterC = 243.12;
	constexpr double AircraftFxMagnusIceB = 22.46;
	constexpr double AircraftFxMagnusIceC = 272.62;
	double AircraftFxIceOverWaterSaturation(double TemperatureK)
	{
		const double T = TemperatureK - 273.15;
		return FMath::Exp(AircraftFxMagnusWaterB * T / (AircraftFxMagnusWaterC + T)
		                  - AircraftFxMagnusIceB * T / (AircraftFxMagnusIceC + T));
	}
	const TCHAR* const AircraftFxParamTime = TEXT("TimeS");
	const TCHAR* const AircraftFxParamStrength = TEXT("Strength");
	const TCHAR* const AircraftFxParamBeamDirection = TEXT("BeamDirection");
	const TCHAR* const AircraftFxParamBeamCos = TEXT("BeamCos");
	const TCHAR* const AircraftFxParamCoreColour = TEXT("CoreColour");
	const TCHAR* const AircraftFxParamTipColour = TEXT("TipColour");
	const TCHAR* const AircraftFxParamShocks = TEXT("Shocks");
	// scripts/aircraft_look.py nav_bulb_area_factor(): nav_bulb.hlsl's falloff
	// integrated over one quad, per half-size squared (pinned by test). Used
	// only for a look manifest that predates bulb_luminance_nits.
	constexpr double AircraftFxNavBulbAreaFactor = 0.32715038;
	// scripts/aircraft_look.py OMNI_BEAM_COS: no beam (drawn from every side).
	constexpr double AircraftFxOmniBeamCos = -2.0;
	// heat_haze.hlsl's envelope peak, (1 - u) x saturate(8 u) at u = 1/8
	// (aircraft_look.py HEAT_HAZE_FADE_PEAK).
	constexpr double AircraftFxHeatHazeFadePeak = 0.875;
	// UE 5.7.4 Shaders/Private/DistortionCommon.ush OffsetFudgeFactor
	// (check_bridge_api.sh pins it; aircraft_look.py UE_DISTORTION_OFFSET_FUDGE).
	constexpr double AircraftFxDistortionOffsetFudge = 0.00023;
	// The look instances: <asset_path_root>/Look/MI_<slot> (aircraft_look.py
	// LOOK_INSTANCE_FOLDER / LOOK_INSTANCE_PREFIX).
	const TCHAR* const AircraftFxLookFolder = TEXT("Look");
	const TCHAR* const AircraftFxLookPrefix = TEXT("MI_");
	// round 5 (L4): the Thin Translucent canopy instance beside a glass slot's
	// opaque one (aircraft_look.THIN_INSTANCE_SUFFIX), applied without -labels only.
	const TCHAR* const AircraftFxThinSuffix = TEXT("_thin");
	// Storm wet paint A/B: -wet-porosity=low (aircraft_wet_layer.WET_POROSITY_LOW).
	constexpr float AircraftFxWetPorosityLowPaint = 0.05f;
	constexpr float AircraftFxWetPorosityLowBareMetal = 0.0f;

	// on/1/true or off/0/false; any other word is refused by name (it was
	// read as "on", so -heat-haze=no turned the pixel-moving haze ON). Twin of
	// scripts/aircraft_look.py parse_fx_switches.
	bool AircraftFxSwitch(const FString& Params, const TCHAR* Key, bool Default, FString& Error)
	{
		FString Word;
		if (!FParse::Value(*Params, Key, Word))
		{
			return Default;
		}
		if (Word == TEXT("on") || Word == TEXT("1") || Word == TEXT("true"))
		{
			return true;
		}
		if (Word == TEXT("off") || Word == TEXT("0") || Word == TEXT("false"))
		{
			return false;
		}
		if (Error.IsEmpty())
		{
			Error = FString::Printf(TEXT("aircraft_look.switch: -%s%s is not on/1/true or off/0/false"), Key, *Word);
		}
		return Default;
	}

	bool AircraftFxPair(const TSharedPtr<FJsonObject>& Row, const TCHAR* Field, FVector2D& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Row.IsValid() && Row->TryGetArrayField(Field, Values) && Values != nullptr && Values->Num() == 2)
		{
			Out = FVector2D((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber());
			return true;
		}
		return false;
	}

	FVector AircraftFxVector(const TSharedPtr<FJsonObject>& Row, const TCHAR* Field)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Row.IsValid() && Row->TryGetArrayField(Field, Values) && Values != nullptr && Values->Num() == 3)
		{
			return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
		}
		return FVector::ZeroVector;
	}

	TSharedPtr<FJsonValue> AircraftFxVectorValue(const FVector& V)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		Values.Add(MakeShared<FJsonValueNumber>(V.X));
		Values.Add(MakeShared<FJsonValueNumber>(V.Y));
		Values.Add(MakeShared<FJsonValueNumber>(V.Z));
		return MakeShared<FJsonValueArray>(Values);
	}

	UProceduralMeshComponent* AircraftFxMesh(AActor* Owner, const TCHAR* Name)
	{
		UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Owner, Name);
		Owner->SetRootComponent(Mesh);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		return Mesh;
	}

	// Three crossed quads (XY, XZ, YZ), RadiusCm half-size, UV 0..1 across each:
	// a lamp's glow seen from any side (nav_bulb.hlsl draws the falloff).
	void AircraftFxBulbSection(UProceduralMeshComponent* Mesh, double RadiusCm)
	{
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		const FVector Axes[3][2] = {
			{FVector(1, 0, 0), FVector(0, 1, 0)},
			{FVector(1, 0, 0), FVector(0, 0, 1)},
			{FVector(0, 1, 0), FVector(0, 0, 1)},
		};
		for (const auto& Pair : Axes)
		{
			const int32 Base = Vertices.Num();
			const FVector U = Pair[0] * RadiusCm;
			const FVector V = Pair[1] * RadiusCm;
			Vertices.Add(-U - V);
			Vertices.Add(U - V);
			Vertices.Add(U + V);
			Vertices.Add(-U + V);
			UV0.Add(FVector2D(0, 0));
			UV0.Add(FVector2D(1, 0));
			UV0.Add(FVector2D(1, 1));
			UV0.Add(FVector2D(0, 1));
			const FVector N = FVector::CrossProduct(Pair[0], Pair[1]);
			for (int32 i = 0; i < 4; ++i)
			{
				Normals.Add(N);
			}
			Triangles.Append({Base, Base + 1, Base + 2, Base, Base + 2, Base + 3});
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}

	// An open cone along actor -X from the nozzle (radius R0, UV.x 0) to
	// LengthCm aft (radius R1, UV.x 1); UV.y runs around it.
	void AircraftFxConeSection(UProceduralMeshComponent* Mesh, double R0, double R1, double LengthCm)
	{
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		for (int32 Ring = 0; Ring <= AircraftFxConeRings; ++Ring)
		{
			const double T = static_cast<double>(Ring) / AircraftFxConeRings;
			const double Radius = FMath::Lerp(R0, R1, T);
			for (int32 Side = 0; Side <= AircraftFxConeSides; ++Side)
			{
				const double A = 2.0 * UE_DOUBLE_PI * Side / AircraftFxConeSides;
				const FVector Radial(0.0, FMath::Cos(A), FMath::Sin(A));
				Vertices.Add(FVector(-T * LengthCm, 0.0, 0.0) + Radial * Radius);
				Normals.Add(Radial);
				UV0.Add(FVector2D(T, static_cast<double>(Side) / AircraftFxConeSides));
			}
		}
		const int32 Stride = AircraftFxConeSides + 1;
		for (int32 Ring = 0; Ring < AircraftFxConeRings; ++Ring)
		{
			for (int32 Side = 0; Side < AircraftFxConeSides; ++Side)
			{
				const int32 A = Ring * Stride + Side;
				const int32 B = A + Stride;
				Triangles.Append({A, B, A + 1, A + 1, B, B + 1});
			}
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}
}

void FFlightSimAircraftFXOptions::ParseParams(const FString& CommandLine)
{
	SwitchError.Reset();
	// Rounds 13-18: the A/B channel (FLIGHTSIM_RENDER_SWITCHES, what
	// visual_fix_round.ps1 -Switches sets) was never read here, so
	// -aircraft-materials=off rendered identical frames. The command line,
	// then the environment, as the world look reads them.
	const FString Params = CommandLine + TEXT(" ")
		+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
	const bool bAll = AircraftFxSwitch(Params, TEXT("aircraft-look="), true, SwitchError);
	// Every switch is parsed (no short-circuit), so a bad word is refused
	// even under -aircraft-look=off.
	// Round 22 (2026-11-11): OFF by default. With the gen-4 look instances the
	// A-4 drew tan (111/98/84 in its mask, #4) and the C172 near-black under
	// overcast (27/18/17, #8); -aircraft-materials=off drew them white
	// (167/155/147) and lit grey (89/82/92). The imported materials stand until
	// a bisect inside the masters finds the cause; -aircraft-materials=on is the
	// probe. Labels never depended on them.
	// Final sweep: ON again, with the flat paint master by default (below,
	// -aircraft-probe= absent). Off (round 22's default) blacked out #12's canopy.
	const bool bMaterialsSwitch = AircraftFxSwitch(Params, TEXT("aircraft-materials="), true, SwitchError);
	const bool bLightsSwitch = AircraftFxSwitch(Params, TEXT("aircraft-lights="), true, SwitchError);
	const bool bContrailsSwitch = AircraftFxSwitch(Params, TEXT("contrails="), true, SwitchError);
	const bool bAfterburnerSwitch = AircraftFxSwitch(Params, TEXT("afterburner="), true, SwitchError);
	// Pixel-moving: off unless asked for by name.
	const bool bHeatHazeSwitch = AircraftFxSwitch(Params, TEXT("heat-haze="), false, SwitchError);
	const bool bFormationRampSwitch = AircraftFxSwitch(Params, TEXT("contrail-formation-ramp="), true, SwitchError);
	// LOOK_GENERATION 13: the trail's break-up into puffs with age (the A/B).
	const bool bPuffsSwitch = AircraftFxSwitch(Params, TEXT("contrail-puffs="), true, SwitchError);
	// LOOK_GENERATION 14: the crossed ribbon's per-strip view weight (the A/B).
	const bool bViewWeightSwitch = AircraftFxSwitch(Params, TEXT("contrail-view-weight="), true, SwitchError);
	// LOOK_GENERATION 15: one camera-facing ribbon with a tube's normal (the A/B).
	const bool bFacingSwitch = AircraftFxSwitch(Params, TEXT("contrail-facing="), true, SwitchError);
	// The canopy reflection: off unless asked for by name (the A/B).
	const bool bCanopyReflectSwitch = AircraftFxSwitch(Params, TEXT("canopy-reflect="), false, SwitchError);
	// The airframe's sky reflection: on unless asked off by name (the A/B).
	const bool bPaintReflectSwitch = AircraftFxSwitch(Params, TEXT("paint-reflect="), true, SwitchError);
	// LOOK_GENERATION 16: those mirrors read the scene's sky and ground; off is the A/B (the strip).
	const bool bSceneSkySwitch = AircraftFxSwitch(Params, TEXT("scene-mirror="), true, SwitchError);
	bMaterials = bAll && bMaterialsSwitch;
	bLights = bAll && bLightsSwitch;
	bContrails = bAll && bContrailsSwitch;
	bAfterburner = bAll && bAfterburnerSwitch;
	bHeatHaze = bAll && bHeatHazeSwitch;
	bContrailFormationRamp = bAll && bFormationRampSwitch;
	bContrailPuffs = bAll && bPuffsSwitch;
	bContrailViewWeight = bAll && bViewWeightSwitch;
	bContrailFacing = bAll && bFacingSwitch;
	bCanopyReflect = bAll && bCanopyReflectSwitch;
	bPaintReflect = bAll && bPaintReflectSwitch;
	bReflectSceneSky = bAll && bSceneSkySwitch;
	// Tiers 0-1 only (both opaque); 2-3 are translucent and not built. A bad
	// word is refused even with the switch off (aircraft_glass_reflect.parse_canopy_reflect).
	CanopyReflectTier = 0;
	{
		FString TierWord;
		if (FParse::Value(*Params, TEXT("canopy-reflect-tier="), TierWord))
		{
			if (TierWord == TEXT("0") || TierWord == TEXT("1"))
			{
				CanopyReflectTier = TierWord == TEXT("1") ? 1 : 0;
			}
			else if (SwitchError.IsEmpty())
			{
				SwitchError = FString::Printf(TEXT("aircraft_look.switch: -canopy-reflect-tier=%s is not 0 or 1 ")
					TEXT("(tiers 2-3 are translucent and not built)"), *TierWord);
			}
		}
	}
	// The look's X-Plane horizon (webapp.runs.xplane_lighting_flags: R:G:B,
	// sRGB8) and sky condition, when the render carries them: the strip's hue.
	bHorizonKnown = false;
	{
		FString HorizonWord;
		TArray<FString> Channels;
		if (FParse::Value(*Params, TEXT("xplane-horizon="), HorizonWord) &&
		    HorizonWord.ParseIntoArray(Channels, TEXT(":"), false) == 3 &&
		    Channels[0].IsNumeric() && Channels[1].IsNumeric() && Channels[2].IsNumeric())
		{
			const int32 R = FCString::Atoi(*Channels[0]);
			const int32 G = FCString::Atoi(*Channels[1]);
			const int32 B = FCString::Atoi(*Channels[2]);
			if (R >= 0 && R <= 255 && G >= 0 && G <= 255 && B >= 0 && B <= 255)
			{
				Horizon = FColor(static_cast<uint8>(R), static_cast<uint8>(G), static_cast<uint8>(B));
				bHorizonKnown = true;
			}
		}
		SkyCondition.Reset();
		FParse::Value(*Params, TEXT("xplane-condition="), SkyCondition);
	}
	// round 5 (L4): the same -labels word the commandlet reads (aircraft_look.labels_requested).
	bLabels = FParse::Param(*Params, TEXT("labels"));
	// Round 23: the master bisect probes (aircraft_look.parse_aircraft_probes).
	// bShouldStopOnSeparator false: the value is a comma list.
	Probes.Reset();
	FString ProbeList;
	if (FParse::Value(*Params, TEXT("aircraft-probe="), ProbeList, false))
	{
		TArray<FString> Words;
		ProbeList.ParseIntoArray(Words, TEXT(","), true);
		for (FString Word : Words)
		{
			Word.TrimStartAndEndInline();
			if (Word.IsEmpty() || Word == TEXT("none"))
			{
				continue;
			}
			const bool bKnown = Word == TEXT("nocoat") || Word == TEXT("noao") || Word == TEXT("nonormal") ||
				Word == TEXT("nowear") || Word == TEXT("flat") || Word == TEXT("measured-mesh") ||
				// round 24 (LOOK_GENERATION 6)
				Word == TEXT("nowet") || Word == TEXT("rawbase") || Word == TEXT("defaultlit") ||
				Word == TEXT("basecolor-debug") || Word == TEXT("tangentnormal") ||
				// round 25 (LOOK_GENERATION 7)
				Word == TEXT("coat");
			if (!bKnown)
			{
				if (SwitchError.IsEmpty())
				{
					SwitchError = FString::Printf(TEXT("aircraft_look.switch: -aircraft-probe=%s: '%s' is not one of ")
						TEXT("nocoat, noao, nonormal, nowear, flat, measured-mesh, nowet, rawbase, defaultlit, ")
						TEXT("basecolor-debug, tangentnormal, coat"), *ProbeList, *Word);
				}
				continue;
			}
			Probes.AddUnique(Word);
		}
	}
	// Round 25: -aircraft-probe= absent draws the class masters (gen 7),
	// each compile-checked on the render's shader platform, falling back to
	// M_AircraftPaintCoat, then to M_AircraftProbeFlat (ApplyMaterials;
	// aircraft_look.MASTER_FALLBACK_ORDER). The final sweep's default
	// (round 44, 1e5ba438: every paint slot on the flat master) is
	// -aircraft-probe=flat; -aircraft-probe=coat forces the coat master.
	// Storm wet paint A/B: -wet-porosity=default|low (aircraft_look.parse_wet_porosity).
	WetPorosity = TEXT("low");     // round 85: low is the default
	FParse::Value(*Params, TEXT("wet-porosity="), WetPorosity);
	if (WetPorosity != TEXT("default") && WetPorosity != TEXT("low"))
	{
		if (SwitchError.IsEmpty())
		{
			SwitchError = FString::Printf(TEXT("aircraft_look.switch: -wet-porosity=%s is not one of default, low"),
			                              *WetPorosity);
		}
		WetPorosity = TEXT("low");
	}
	Humidity.ParseParams(Params);  // condensation-solver: -humidity-pct=
}

double FFlightSimAircraftFX::HeatHazeMaxDisplacementPx(double MaterialOffset, double WidthPx, double HeightPx,
                                                        double HFovDeg)
{
	const double TanHalf = FMath::Tan(FMath::DegreesToRadians(FMath::Clamp(HFovDeg, 1.0, 179.0)) * 0.5);
	return MaterialOffset * WidthPx * AircraftFxDistortionOffsetFudge / TanHalf *
		FMath::Sqrt(WidthPx * WidthPx + HeightPx * HeightPx);
}

double FFlightSimAircraftFX::Constant(const TCHAR* Group, const TCHAR* Name, double Fallback) const
{
	const TSharedPtr<FJsonObject>* GroupObject = nullptr;
	const TSharedPtr<FJsonObject>* Entry = nullptr;
	double Value = Fallback;
	if (Constants.IsValid() && Constants->TryGetObjectField(Group, GroupObject) && GroupObject != nullptr &&
	    (*GroupObject)->TryGetObjectField(Name, Entry) && Entry != nullptr)
	{
		(*Entry)->TryGetNumberField(TEXT("value"), Value);
	}
	return Value;
}

AActor* FFlightSimAircraftFX::SpawnAttached(UWorld* World, const FVector& ActorCm, const TCHAR* Name)
{
	AActor* Actor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh = AircraftFxMesh(Actor, Name);
	Mesh->RegisterComponent();
	// Its own actor, attached: the stencil loop labels every primitive OF the
	// aircraft actor, and this one must carry no label (BeautyOnlyActors).
	Actor->AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform);
	Actor->SetActorRelativeLocation(ActorCm);
	BeautyOnlyActors.Add(Actor);
	return Actor;
}

bool FFlightSimAircraftFX::Build(UWorld* World, const FFlightSimAircraftFXOptions& Options, FString& Error)
{
	Aircraft = Options.Aircraft;
	Weather = Options.Weather;  // wet-airframe-canopy
	CloudLayers = Options.CloudLayers;
	Record = MakeShared<FJsonObject>();
	if (!Options.SwitchError.IsEmpty())
	{
		Error = Options.SwitchError;
		return false;
	}
	Record->SetStringField(TEXT("drawn_in"), TEXT("beauty capture only (-quality=beauty); every element is a ")
		TEXT("beauty-only actor or a shading-only material swap, so mask, class and depth are those of the ")
		TEXT("same frame's geometry"));
	if (World == nullptr || Aircraft == nullptr)
	{
		Record->SetStringField(TEXT("look_manifest"), TEXT("absent: no aircraft actor"));
		return true;
	}

	// -- the look manifest (scripts/aircraft_look.py) -------------------------
	FString AssetRoot;
	{
		FString MeshText;
		TSharedPtr<FJsonObject> MeshManifest;
		if (FFileHelper::LoadFileToString(MeshText, *Options.MeshManifestPath))
		{
			TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(MeshText);
			if (FJsonSerializer::Deserialize(Reader, MeshManifest) && MeshManifest.IsValid())
			{
				MeshManifest->TryGetStringField(TEXT("asset_path_root"), AssetRoot);
				// cockpit-airframe (round 2): assets_pipeline/convert.py
				// _write_beauty_mesh, {"body": {"part": "body_beauty", ...}}.
				const TSharedPtr<FJsonObject>* BeautyParts = nullptr;
				if (MeshManifest->TryGetObjectField(TEXT("beauty_parts"), BeautyParts) && BeautyParts != nullptr)
				{
					for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*BeautyParts)->Values)
					{
						const TSharedPtr<FJsonObject> Row = Entry.Value.IsValid() ? Entry.Value->AsObject() : nullptr;
						FString BeautyPart;
						if (Row.IsValid() && Row->TryGetStringField(TEXT("part"), BeautyPart))
						{
							BeautyMeshes.Add(Entry.Key, BeautyPart);
						}
					}
				}
			}
		}
	}
	const FString LookPath = FPaths::Combine(FPaths::GetPath(Options.MeshManifestPath), AircraftFxLookManifestName);
	TSharedPtr<FJsonObject> Look;
	FString LookText;
	if (FFileHelper::LoadFileToString(LookText, *LookPath))
	{
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(LookText);
		FString Magic;
		if (!FJsonSerializer::Deserialize(Reader, Look) || !Look.IsValid() ||
		    !Look->TryGetStringField(TEXT("magic"), Magic) || Magic != AircraftFxLookManifestMagic)
		{
			Error = FString::Printf(
				TEXT("aircraft_look.manifest: %s exists but is not a look manifest (magic %s); re-run ")
				TEXT("python scripts/aircraft_look.py <NAME> or the import step"),
				*LookPath, AircraftFxLookManifestMagic);
			return false;
		}
		Record->SetStringField(TEXT("look_manifest"), LookPath);
		FString ConfigSha;
		if (Look->TryGetStringField(TEXT("look_config_sha256"), ConfigSha))
		{
			Record->SetStringField(TEXT("look_config_sha256"), ConfigSha);
		}
		// The mesh manifest the anchors were measured on. Not compared here
		// (no hashing in this file): a reader compares it with render.json's
		// own mesh manifest sha256, and a mismatch means the lamps and
		// nozzles were placed on an earlier conversion of the mesh (re-run
		// python scripts/aircraft_look.py <NAME> or the import step).
		FString MeshSha;
		if (Look->TryGetStringField(TEXT("mesh_manifest_sha256"), MeshSha))
		{
			Record->SetStringField(TEXT("look_mesh_manifest_sha256"), MeshSha);
		}
		const TSharedPtr<FJsonObject>* ConstantsObject = nullptr;
		if (Look->TryGetObjectField(TEXT("constants"), ConstantsObject) && ConstantsObject != nullptr)
		{
			Constants = *ConstantsObject;
			// Every constant with its UNCALIBRATED stamp and the probe that
			// should set it, verbatim.
			Record->SetObjectField(TEXT("constants"), Constants);
		}
	}
	else
	{
		Record->SetStringField(TEXT("look_manifest"), FString::Printf(
			TEXT("absent: %s (no lights, nozzles or trails; run the import step)"), *LookPath));
	}

	// -- the materials ---------------------------------------------------------
	if (Options.bMaterials && !AssetRoot.IsEmpty())
	{
		ApplyMaterials(AssetRoot, Options);
	}
	else
	{
		Record->SetStringField(TEXT("materials"), Options.bMaterials
			? TEXT("absent: the mesh manifest names no asset_path_root")
			: TEXT("off (-aircraft-look=off or -aircraft-materials=off)"));
		if (Options.Probes.Num() > 0)
		{
			// Round 23: a probe needs the look instances to act on.
			Record->SetStringField(TEXT("materials_probes"), FString::Printf(
				TEXT("ignored: -aircraft-probe=%s needs -aircraft-materials=on"),
				*FString::Join(Options.Probes, TEXT(","))));
		}
	}

	// -- lights, nozzles, trails ---------------------------------------------
	TArray<TSharedPtr<FJsonValue>> LightRows;
	const TArray<TSharedPtr<FJsonValue>>* Lights = nullptr;
	if (Look.IsValid() && Options.bLights && Look->TryGetArrayField(TEXT("lights"), Lights) && Lights != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Lights)
		{
			BuildLamp(World, Value->AsObject());
		}
		for (const FLamp& Lamp : Lamps)
		{
			TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
			Row->SetStringField(TEXT("id"), Lamp.Id);
			Row->SetStringField(TEXT("kind"), Lamp.Kind);
			Row->SetField(TEXT("actor_cm"), AircraftFxVectorValue(Lamp.ActorCm));
			Row->SetNumberField(TEXT("candela"), Lamp.Candela);
			Row->SetNumberField(TEXT("bulb_luminance_nits"), Lamp.BulbNits);
			Row->SetBoolField(TEXT("bulb_drawn"), Lamp.Bulb != nullptr);
			LightRows.Add(MakeShared<FJsonValueObject>(Row));
		}
	}
	Record->SetArrayField(TEXT("lights"), LightRows);
	Record->SetStringField(TEXT("lights_note"), TEXT("point/spot lights move no geometry; the bulbs are additive ")
		TEXT("(they hide nothing), beauty-only actors the label captures hide"));
	Record->SetNumberField(TEXT("landing_volumetric_scattering"),
		Constant(TEXT("lights"), TEXT("LandingVolumetricScattering"), AircraftFxLandingVolumetricScattering));
	Record->SetNumberField(TEXT("nav_volumetric_scattering"),
		Constant(TEXT("lights"), TEXT("NavVolumetricScattering"), AircraftFxNavVolumetricScattering));

	const TArray<TSharedPtr<FJsonValue>>* NozzleRows = nullptr;
	if (Look.IsValid() && Look->TryGetArrayField(TEXT("nozzles"), NozzleRows) && NozzleRows != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *NozzleRows)
		{
			BuildNozzle(World, Value->AsObject(), Options);
		}
	}
	// Trails: one contrail per nozzle (Options.bContrails), one vapour trail
	// per wingtip nav lamp. World-space, NOT attached (a trail stays where the
	// air was), each its own beauty-only actor.
	UMaterialInterface* ContrailMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxContrailMaterialPath);
	// LOOK_GENERATION 13: the semi-span from the wingtip nav lamps (the look
	// config anchors them at the mesh's +/-Y extremes); 0 with none, and then
	// no roll-up (VortexOffsetM 0: the plumes stay behind their engines).
	SemiSpanCm = 0.0;
	for (const FLamp& Lamp : Lamps)
	{
		if (Lamp.Kind == TEXT("nav_red") || Lamp.Kind == TEXT("nav_green"))
		{
			SemiSpanCm = FMath::Max(SemiSpanCm, FMath::Abs(Lamp.ActorCm.Y));
		}
	}
	auto AddTrail = [&](const FVector& SourceActorCm, bool bVapour, const TCHAR* Name)
	{
		FTrail Trail;
		Trail.SourceActorCm = SourceActorCm;
		Trail.bVapour = bVapour;
		if (!bVapour && SemiSpanCm > 0.0)
		{
			// Towards this side's vortex core at VortexSpanFraction x the semi-span
			// (an engine on the centreline goes right). Twin: aircraft_look.contrail_wake_offset_m.
			const double NozzleYM = SourceActorCm.Y / AircraftFxCmPerMetre;
			const double CoreYM = (NozzleYM < 0.0 ? -1.0 : 1.0)
				* Constant(TEXT("contrail"), TEXT("VortexSpanFraction"), 0.785) * SemiSpanCm / AircraftFxCmPerMetre;
			Trail.VortexOffsetM = CoreYM - NozzleYM;
		}
		Trail.Owner = World->SpawnActor<AActor>();
		Trail.Mesh = AircraftFxMesh(Trail.Owner, Name);
		UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(ContrailMaterial, Trail.Mesh);
		const TCHAR* Group = bVapour ? TEXT("vapour") : TEXT("contrail");
		Trail.Instance = Instance;
		Trail.BaseOpacity = Constant(Group, TEXT("Opacity"), bVapour ? 0.35 : 0.55);
		Instance->SetScalarParameterValue(FName(AircraftFxParamOpacity), static_cast<float>(Trail.BaseOpacity));
		const double Lifetime = Constant(Group, TEXT("LifetimeS"), bVapour ? 0.8 : 25.0);
		const double Formation = bVapour ? 0.0 : Constant(TEXT("contrail"), TEXT("FormationDelayS"), 0.15);
		Instance->SetScalarParameterValue(FName(AircraftFxParamFormation),
			static_cast<float>(Formation / FMath::Max(Lifetime, 0.01)));
		// Round 47 (#13): the ramp in seconds (LOOK_GENERATION 7's FormationRamp); off,
		// generation 6's 0.04 of the lifetime (1 s, 250 m at cruise: the four lines).
		const double Ramp = !bVapour && Options.bContrailFormationRamp
			? Constant(TEXT("contrail"), TEXT("FormationRampS"), 0.25) / FMath::Max(Lifetime, 0.01)
			: AircraftFxLegacyFormationRamp;
		Instance->SetScalarParameterValue(FName(AircraftFxParamFormationRamp), static_cast<float>(Ramp));
		// LOOK_GENERATION 13: the break-up into puffs with age (a wingtip vapour
		// trail lives 0.8 s and never ages into puffs: 0).
		const double Puff = !bVapour && Options.bContrailPuffs
			? Constant(TEXT("contrail"), TEXT("PuffBreakup"), 0.6) : 0.0;
		Instance->SetScalarParameterValue(FName(AircraftFxParamPuff), static_cast<float>(Puff));
		// LOOK_GENERATION 14: weight each strip by how face-on it is (RebuildTrail
		// writes the axis and strip on UV1 / UV2); 0 is generation 13's both-full.
		Instance->SetScalarParameterValue(FName(AircraftFxParamViewWeight),
			Options.bContrailViewWeight ? 1.0f : 0.0f);
		// LOOK_GENERATION 15: strip 0 turned to face the camera, strip 1 folded away
		// (contrail_facing.hlsl; RebuildTrail writes the half width on UV3).
		Instance->SetScalarParameterValue(FName(AircraftFxParamFacing),
			Options.bContrailFacing ? 1.0f : 0.0f);
		Trail.Mesh->SetMaterial(0, Instance);
		Trail.Mesh->RegisterComponent();
		BeautyOnlyActors.Add(Trail.Owner);
		Trails.Add(Trail);
	};
	if (ContrailMaterial != nullptr)
	{
		if (Options.bContrails)
		{
			for (const FNozzle& Nozzle : Nozzles)
			{
				AddTrail(Nozzle.ActorCm, false, TEXT("Contrail"));
			}
			for (const FLamp& Lamp : Lamps)
			{
				if (Lamp.Kind == TEXT("nav_red") || Lamp.Kind == TEXT("nav_green"))
				{
					AddTrail(Lamp.ActorCm, true, TEXT("WingtipVapour"));
				}
			}
		}
	}
	TSharedPtr<FJsonObject> ContrailRow = MakeShared<FJsonObject>();
	ContrailRow->SetStringField(TEXT("material"), ContrailMaterial != nullptr
		? AircraftFxContrailMaterialPath : TEXT("absent"));
	ContrailRow->SetBoolField(TEXT("enabled"), Options.bContrails);
	ContrailRow->SetBoolField(TEXT("formation_ramp_on"), Options.bContrailFormationRamp);
	ContrailRow->SetStringField(TEXT("formation_ramp_basis"), Options.bContrailFormationRamp
		? TEXT("round 47: the trail forms over contrail.FormationRampS after FormationDelayS (FormationRamp = "
		       "FormationRampS / LifetimeS); -contrail-formation-ramp=off is the A/B")
		: TEXT("-contrail-formation-ramp=off: generation 6's ramp, 0.04 of LifetimeS (1 s at 25 s: #13's four "
		       "faint lines that read as marks on the sea)"));
	ContrailRow->SetStringField(TEXT("rule"), TEXT("drawn while atmosphere/T-R is below contrail.MaxTemperatureK ")
		TEXT("and position/h-sl-meters above contrail.MinAltitudeM (Schmidt-Appleman threshold, no humidity ")
		TEXT("modelled); wingtip vapour from the humidity test (aircraft_look.condensation), or while ")
		TEXT("accelerations/Nz exceeds vapour.MinNz when the humidity is unavailable; vapour_frames counts ")
		TEXT("only the frames these wingtip vapour trails drew (the humidity-gated tip ribbons' frames are in ")
		TEXT("aircraft_look.condensation.per_frame)"));
	ContrailRow->SetStringField(TEXT("in_cloud"), TEXT("a contrail's opacity x (1 - cover) of every cloud layer ")
		TEXT("the aircraft is inside (base..top above the ground datum); contrail_in_cloud_frames counts them"));
	ContrailRow->SetStringField(TEXT("label_convention"), TEXT("a trail is a translucent medium like the clouds ")
		TEXT("and rain the label captures already omit: where it crosses in front of the aircraft the mask ")
		TEXT("still says aircraft"));
	// LOOK_GENERATION 13 (hyperreal contrails; #13's four bright runway stripes).
	ContrailRow->SetStringField(TEXT("width_model"), TEXT("width(age) = StartWidthM + JetSpreadM x (1 - exp(-age / ")
		TEXT("JetMixS)) + SpreadMPerS x age (the jet regime's saturating spread, then slow diffusion; twin ")
		TEXT("aircraft_look.contrail_width_m); UNCALIBRATED"));
	ContrailRow->SetStringField(TEXT("wake_rollup"), SemiSpanCm > 0.0
		? FString::Printf(TEXT("each engine plume is drawn to its side's wingtip vortex core (+/- VortexSpanFraction x ")
		                       TEXT("the %.1f m semi-span from the nav lamps) over VortexRollupS and the pair sinks at ")
		                       TEXT("WakeSinkMPerS (twin aircraft_look.contrail_wake_offset_m); UNCALIBRATED"),
		                  SemiSpanCm / AircraftFxCmPerMetre)
		: FString(TEXT("none: no wingtip nav lamp measured a semi-span, the plumes stay behind their engines")));
	ContrailRow->SetBoolField(TEXT("puffs_on"), Options.bContrailPuffs);
	ContrailRow->SetBoolField(TEXT("view_weight_on"), Options.bContrailViewWeight);
	ContrailRow->SetBoolField(TEXT("facing_on"), Options.bContrailFacing);
	ContrailRow->SetStringField(TEXT("facing"), Options.bContrailFacing
		? TEXT("LOOK_GENERATION 15: one camera-facing ribbon (contrail_facing.hlsl World Position Offset turns strip 0 "
		       "about the axis to across = cross(a, v), strip 1 folds onto the axis), the chord profile across and "
		       "the tube's world normal (contrail_normal.hlsl): a circular tube from any azimuth, sun side lit, far "
		       "side sky-lit; -contrail-facing=off is the A/B. Twins aircraft_look.contrail_facing_offset, "
		       "contrail_tube_normal")
		: TEXT("-contrail-facing=off: generation 14's crossed ribbon with the per-strip view weight"));
	ContrailRow->SetStringField(TEXT("view_weight"), Options.bContrailViewWeight
		? TEXT("LOOK_GENERATION 14: each strip of the crossed ribbon x (n.v)^2 / (1 - (a.v)^2) (n its plane normal, "
		       "a the axis on UV1/UV2, v CameraVectorWS); the two sum to 1 at every view, as a cylinder's projection "
		       "is the same from every azimuth; -contrail-view-weight=off is the A/B. Twin "
		       "aircraft_look.contrail_view_weight")
		: TEXT("-contrail-view-weight=off: generation 13, both strips at full strength (the edge-on strip draws a "
		       "hard core line from a chase camera)"));
	ContrailRow->SetStringField(TEXT("puffs"), TEXT("contrail_opacity.hlsl: a cylinder's chord across, two octaves of ")
		TEXT("world-space value noise whose cell coarsens with age, the cut rising with the sample's Life (vertex ")
		TEXT("colour R = age / its own lifetime); Puff = PuffBreakup, 0 under -contrail-puffs=off (the A/B)"));
	ContrailRow->SetStringField(TEXT("lighting"), TEXT("lit translucent, Volumetric Directional, half-cylinder normals: ")
		TEXT("a sun side and a shadow side (the material build falls back to NonDirectional when the Python lacks ")
		TEXT("the name; the master's property says which)"));
	TSharedPtr<FJsonObject> PersistenceRow = MakeShared<FJsonObject>();
	PersistenceRow->SetStringField(TEXT("rule"), TEXT("RHi = RH x e_sat,water / e_sat,ice (Sonntag 1990 Magnus forms); ")
		TEXT("factor = saturate((RHi - PersistenceRhiOnsetPct) / PersistenceRhiSpanPct); a sample's lifetime = ")
		TEXT("LifetimeS + factor x (PersistentLifetimeS - LifetimeS), fixed at emission (the air it is in); no ")
		TEXT("humidity (no dew point on the card, no -humidity-pct=): factor 0, LifetimeS. Twin ")
		TEXT("aircraft_look.contrail_persistence; UNCALIBRATED"));
	PersistenceRow->SetStringField(TEXT("humidity"), Options.Humidity.bParamStated
		? TEXT("-humidity-pct=") : Options.Humidity.bCardStated
		? TEXT("atmosphere/RH (the card states a dew point)") : TEXT("none: the persistence factor is 0"));
	ContrailRow->SetObjectField(TEXT("persistence"), PersistenceRow);
	Record->SetObjectField(TEXT("contrail"), ContrailRow);

	TSharedPtr<FJsonObject> HazeRow = MakeShared<FJsonObject>();
	HazeRow->SetBoolField(TEXT("drawn"), false);
	HazeRow->SetBoolField(TEXT("pixel_moving"), true);
	HazeRow->SetStringField(TEXT("switch"), TEXT("-heat-haze=on (off by default; never on in a measured shot)"));
	for (const FNozzle& Nozzle : Nozzles)
	{
		if (Nozzle.Haze != nullptr)
		{
			HazeRow->SetBoolField(TEXT("drawn"), true);
			// heat_haze.hlsl: each offset component is at most Strength / 100 x
			// the fade's peak (0.875) in REFRACTION units, not of the screen: the
			// engine scales it by the view (HeatHazeMaxDisplacementPx), which the
			// commandlet applies with the capture's width, height and FOV
			// (render.json pixel_moving_effects heat_haze.max_displacement_px).
			HazeRow->SetNumberField(TEXT("max_material_offset"),
				Constant(TEXT("heat_haze"), TEXT("Strength"), 0.6) * 0.01 * AircraftFxHeatHazeFadePeak);
			HazeRow->SetNumberField(TEXT("engine_offset_fudge"), AircraftFxDistortionOffsetFudge);
			HazeRow->SetStringField(TEXT("bound_formula"), TEXT("px = max_material_offset x W x 0.00023 / ")
				TEXT("tan(hFOV/2) x sqrt(W^2 + H^2) (UE 5.7.4 DistortionCommon.ush, along the diagonal)"));
		}
	}
	Record->SetObjectField(TEXT("heat_haze"), HazeRow);
	// condensation-solver: the humidity-gated vapour sites, own beauty-only actors.
	if (!Condensation.Build(World, Aircraft, Constants, Options.Humidity, Options.bContrails, BeautyOnlyActors, Error)) { return false; }
	Record->SetNumberField(TEXT("beauty_only_actors"), BeautyOnlyActors.Num());
	bBuilt = true;
	UE_LOG(LogFlightSimAircraftFX, Display,
	       TEXT("aircraft look: %d lamp(s), %d nozzle(s), %d trail(s), %d beauty-only actor(s) (%s)"),
	       Lamps.Num(), Nozzles.Num(), Trails.Num(), BeautyOnlyActors.Num(), *LookPath);
	return true;
}

void FFlightSimAircraftFX::ApplyMaterials(const FString& AssetRoot, const FFlightSimAircraftFXOptions& Options)
{
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	if (!Options.Livery.IsEmpty() && Options.Livery != TEXT("default"))
	{
		// The sampled livery is a record the label manifest carries; it keeps
		// its own material on every slot rather than being repainted.
		Row->SetStringField(TEXT("state"), FString::Printf(TEXT("livery '%s' kept; look instances not applied"),
		                                                   *Options.Livery));
		Record->SetObjectField(TEXT("materials"), Row);
		return;
	}
	TInlineComponentArray<UStaticMeshComponent*> Parts;
	Aircraft->GetComponents(Parts);
	// cockpit-airframe (round 2): a part with a beauty copy (mesh manifest
	// beauty_parts) draws the copy on this beauty render: the same triangles at
	// the same positions with the .ac crease normals and two-sided back faces,
	// so the silhouette, custom depth and stencil (component settings, kept by
	// SetStaticMesh) are the measured part's. Swapped only when the copy's
	// slots are the measured part's slots, name for name, so the look
	// instances below land on the same materials.
	TArray<TSharedPtr<FJsonValue>> BeautyRows;
	// Round 23: -aircraft-probe=measured-mesh keeps the measured mesh (the
	// round-22 A/B swapped the mesh AND the materials together: the beauty
	// copy is swapped only here).
	const bool bProbeMeasuredMesh = Options.Probes.Contains(TEXT("measured-mesh"));
	Row->SetBoolField(TEXT("beauty_mesh_swap"), !bProbeMeasuredMesh);
	for (UStaticMeshComponent* Part : bProbeMeasuredMesh ? TInlineComponentArray<UStaticMeshComponent*>() : Parts)
	{
		UStaticMesh* Measured = Part != nullptr ? Part->GetStaticMesh().Get() : nullptr;
		const FString* BeautyName = Measured != nullptr ? BeautyMeshes.Find(Measured->GetName()) : nullptr;
		if (BeautyName == nullptr)
		{
			continue;
		}
		const FString BeautyPath = FString::Printf(TEXT("%s/%s.%s"), *AssetRoot, **BeautyName, **BeautyName);
		UStaticMesh* BeautyMesh = LoadObject<UStaticMesh>(nullptr, *BeautyPath);
		FString Reason;
		if (BeautyMesh == nullptr)
		{
			Reason = TEXT("not imported (run the import step: assets_pipeline/importer.py)");
		}
		else
		{
			const TArray<FStaticMaterial>& From = Measured->GetStaticMaterials();
			const TArray<FStaticMaterial>& To = BeautyMesh->GetStaticMaterials();
			// Round 25 (scene #12): the copy may carry beauty-only slots AFTER
			// the measured part's (a beauty_only interior part, the c172p's
			// instrument panel: assets_pipeline/convert.py), so the measured
			// slots must be the copy's first ones, name for name, in order
			// (ue_aircraft_materials.beauty_slot_mismatches, the twin).
			bool bSameSlots = From.Num() <= To.Num();
			for (int32 Slot = 0; bSameSlots && Slot < From.Num(); ++Slot)
			{
				bSameSlots = From[Slot].MaterialSlotName == To[Slot].MaterialSlotName;
			}
			if (!bSameSlots)
			{
				Reason = TEXT("its first material slots are not the measured part's; the measured mesh is kept");
			}
			else if (!Part->SetStaticMesh(BeautyMesh))
			{
				Reason = TEXT("SetStaticMesh refused (component mobility); the measured mesh is kept");
			}
		}
		TSharedPtr<FJsonObject> BeautyRow = MakeShared<FJsonObject>();
		BeautyRow->SetStringField(TEXT("part"), Measured->GetName());
		BeautyRow->SetStringField(TEXT("beauty_mesh"), BeautyPath);
		BeautyRow->SetBoolField(TEXT("swapped"), Reason.IsEmpty());
		if (BeautyMesh != nullptr)
		{
			// Round 25: slots only the beauty copy has (a beauty_only interior).
			BeautyRow->SetNumberField(TEXT("beauty_only_slots"), FMath::Max(
				0, BeautyMesh->GetStaticMaterials().Num() - Measured->GetStaticMaterials().Num()));
		}
		if (!Reason.IsEmpty())
		{
			BeautyRow->SetStringField(TEXT("reason"), Reason);
		}
		BeautyRows.Add(MakeShared<FJsonValueObject>(BeautyRow));
	}
	Row->SetArrayField(TEXT("beauty_meshes"), BeautyRows);
	int32 Applied = 0;
	int32 Unbound = 0;
	int32 ThinApplied = 0;
	// Round 23: the probes in force (recorded below) and the flat master.
	int32 ProbedSlots = 0;
	int32 WetPorositySlots = 0;
	// The airframe's sky reflection: the paint / bare-metal MIDs given a gain,
	// and the slots whose drawn master predates PaintEnvGain (generation 13).
	int32 PaintReflectSlots = 0;
	int32 PaintReflectStale = 0;
	// Round 25: the flat and coat masters are loaded on every beauty render:
	// they are the compile fallback of a class master (below).
	UMaterialInterface* ProbeFlat = LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeFlatMaterialPath);
	UMaterialInterface* ProbeCoat = LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeCoatMaterialPath);
	UWorld* const CompileWorld = Aircraft != nullptr ? Aircraft->GetWorld() : nullptr;
	// Round 25: each master's compile result on this shader platform, once
	// (empty = compiled), its LookGeneration sentinel, the slots that fell
	// back and the probe parameters the drawn master lacks.
	TMap<FString, FString> MasterProblems;
	TMap<FString, double> MasterGenerations;
	TArray<FString> MissingProbeParameters;
	TMap<FString, int32> FallbackSlots;
	auto CompileProblemOf = [&MasterProblems, CompileWorld](UMaterialInterface* Material) -> FString
	{
		if (Material == nullptr)
		{
			return TEXT("absent");
		}
		const UMaterial* Base = Material->GetMaterial();
		const FString Key = Base != nullptr ? Base->GetName() : Material->GetName();
		if (const FString* Known = MasterProblems.Find(Key))
		{
			return *Known;
		}
		const FString Problem = AircraftFxCompileProblem(Material, CompileWorld);
		MasterProblems.Add(Key, Problem);
		if (!Problem.IsEmpty())
		{
			UE_LOG(LogFlightSimAircraftFX, Warning, TEXT("aircraft look: %s %s"), *Key, *Problem);
		}
		return Problem;
	};
	UMaterialInterface* ProbeDefaultLit = Options.Probes.Contains(TEXT("defaultlit"))
		? LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeDefaultLitMaterialPath) : nullptr;
	UMaterialInterface* ProbeTangentNormal = Options.Probes.Contains(TEXT("tangentnormal"))
		? LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeTangentNormalMaterialPath) : nullptr;
	{
		TArray<TSharedPtr<FJsonValue>> ProbeWords;
		for (const FString& Word : Options.Probes)
		{
			ProbeWords.Add(MakeShared<FJsonValueString>(Word));
		}
		Row->SetArrayField(TEXT("probes"), ProbeWords);
		if (Options.Probes.Contains(TEXT("defaultlit")) && ProbeDefaultLit == nullptr)
		{
			Row->SetStringField(TEXT("probe_defaultlit"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 6); the look ")
				TEXT("instances stand"), AircraftFxProbeDefaultLitMaterialPath));
		}
		if (Options.Probes.Contains(TEXT("tangentnormal")) && ProbeTangentNormal == nullptr)
		{
			Row->SetStringField(TEXT("probe_tangentnormal"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 6); the look ")
				TEXT("instances stand"), AircraftFxProbeTangentNormalMaterialPath));
		}
		if (ProbeFlat == nullptr)
		{
			Row->SetStringField(TEXT("probe_flat"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 5); the look ")
				TEXT("instances stand"), AircraftFxProbeFlatMaterialPath));
		}
		if (ProbeCoat == nullptr)
		{
			Row->SetStringField(TEXT("probe_coat"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 7); no coat ")
				TEXT("fallback, the flat master is the only one"), AircraftFxProbeCoatMaterialPath));
		}
	}
	// The canopy reflection (-canopy-reflect=on; aircraft_glass_reflect.py):
	// the tier's OPAQUE master, compile-checked on this shader platform like
	// the class masters. Absent or failed: every glass slot keeps its look
	// instance (recorded). Off: nothing is loaded and nothing changes.
	UMaterialInterface* GlassReflect = nullptr;
	FString GlassReflectProblem;
	int32 ReflectSlots = 0;
	int32 ReflectThinKept = 0;
	TArray<FString> ReflectNames;
	FLinearColor ReflectTint = FLinearColor::White;
	FString ReflectTintSource = TEXT("baked (no -xplane-horizon on this render)");
	ReflectRow = MakeShared<FJsonObject>();
	ReflectMids.Reset();
	PaintReflectRow = MakeShared<FJsonObject>();
	PaintReflectMids.Reset();
	ReflectSun = Options.Sun;
	ReflectCover = 0.0;
	// LOOK_GENERATION 16: the scene's own sky and ground in both mirrors.
	bSceneSky = Options.bReflectSceneSky && (Options.bPaintReflect || Options.bCanopyReflect);
	SceneSkyLight = Options.SkyLight;
	SceneAtmosphere = Options.Atmosphere;
	SceneSkyStale = 0;
	SceneSkyRow = MakeShared<FJsonObject>();
	// The horizon tint and the cloud cover serve both the canopy and the
	// airframe reflection (the same strip, the same gain rule).
	if (Options.bCanopyReflect || Options.bPaintReflect)
	{
		if (Options.bCanopyReflect)
		{
			const TCHAR* const ReflectPath = Options.CanopyReflectTier == 1
				? AircraftFxGlassReflectFineMaterialPath : AircraftFxGlassReflectMaterialPath;
			GlassReflect = LoadObject<UMaterialInterface>(nullptr, ReflectPath);
			GlassReflectProblem = CompileProblemOf(GlassReflect);
			if (!GlassReflectProblem.IsEmpty())
			{
				GlassReflect = nullptr;
			}
			ReflectRow->SetStringField(TEXT("master"), ReflectPath);
		}
		// Hue only (aircraft_glass_reflect.horizon_tint): the gain sets the level.
		if (Options.bHorizonKnown)
		{
			const FLinearColor Lin(Options.Horizon);  // sRGB8 -> linear
			const double Lum = 0.2126 * Lin.R + 0.7152 * Lin.G + 0.0722 * Lin.B;
			if (Lum > 1.0e-4)
			{
				const double Channel[3] = {Lin.R, Lin.G, Lin.B};
				double Tint[3];
				for (int32 C = 0; C < 3; ++C)
				{
					Tint[C] = FMath::Clamp((Channel[C] / Lum) /
						(AircraftFxReflectStripHorizon[C] / AircraftFxReflectStripHorizonLuminance),
						AircraftFxReflectTintMin, AircraftFxReflectTintMax);
				}
				ReflectTint = FLinearColor(static_cast<float>(Tint[0]), static_cast<float>(Tint[1]),
				                           static_cast<float>(Tint[2]), 1.0f);
				ReflectTintSource = TEXT("-xplane-horizon (the look's X-Plane horizon colour, hue only)");
			}
			else
			{
				ReflectTintSource = TEXT("baked (the -xplane-horizon colour is black)");
			}
		}
		for (const FFlightSimCloudLayer& Layer : Options.CloudLayers)
		{
			ReflectCover = FMath::Max(ReflectCover, FMath::Clamp(Layer.CoverFraction, 0.0, 1.0));
		}
		if (Options.SkyCondition.Contains(TEXT("ocast")))
		{
			ReflectCover = 1.0;
		}
	}
	// Slot names without a look instance, once each (AddUnique on the JSON
	// values would compare pointers and never deduplicate a slot that several
	// parts share).
	TArray<FString> AbsentNames;
	TArray<FString> ThinNames;
	for (UStaticMeshComponent* Part : Parts)
	{
		for (int32 Slot = 0; Slot < Part->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Current = Part->GetMaterial(Slot);
			if (Current == nullptr)
			{
				++Unbound;  // cockpit-airframe: counted, was skipped silently
				continue;
			}
			const FString SlotName = Current->GetName();
			const FString InstanceName = FString::Printf(TEXT("%s%s"), AircraftFxLookPrefix, *SlotName);
			const FString Path = FString::Printf(TEXT("%s/%s/%s.%s"), *AssetRoot, AircraftFxLookFolder,
			                                     *InstanceName, *InstanceName);
			// round 5 (L4): the Thin Translucent canopy, MI_<slot>_thin, where
			// one exists and the render carries no -labels; otherwise (a
			// labelled frame, or a slot that is not glass) the opaque MI_<slot>.
			UMaterialInterface* LookInstance = nullptr;
			bool bThin = false;
			if (!Options.bLabels)
			{
				const FString ThinName = InstanceName + AircraftFxThinSuffix;
				const FString ThinPath = FString::Printf(TEXT("%s/%s/%s.%s"), *AssetRoot, AircraftFxLookFolder,
				                                         *ThinName, *ThinName);
				LookInstance = LoadObject<UMaterialInterface>(nullptr, *ThinPath);
				bThin = LookInstance != nullptr;
			}
			if (LookInstance == nullptr)
			{
				LookInstance = LoadObject<UMaterialInterface>(nullptr, *Path);
			}
			if (LookInstance == nullptr)
			{
				AbsentNames.AddUnique(SlotName);
				continue;
			}
			// Round 23: the bisect probes, on the paint and bare-metal slots only
			// (aircraft_look.PROBE_MASTERS); glass and rubber keep their instances.
			const UMaterial* ProbeBase = LookInstance->GetBaseMaterial();
			const FString ProbeBaseName = ProbeBase != nullptr ? ProbeBase->GetName() : FString();
			// Round 25: every paint / bare-metal slot, probes or not (the
			// compile fallback below acts on all of them).
			const bool bProbeSlot =
				(ProbeBaseName == TEXT("M_AircraftPaint") || ProbeBaseName == TEXT("M_AircraftBareMetal"));
			UMaterialInstance* LookMic = Cast<UMaterialInstance>(LookInstance);
			// Round 24: a paint slot onto a twin master (the paint graph on
			// MSM_DEFAULT_LIT, or with a tangent-space normal), with this
			// instance's overrides; defaultlit wins if both are asked.
			UMaterialInterface* PaintTwin = Options.Probes.Contains(TEXT("defaultlit")) ? ProbeDefaultLit
				: (Options.Probes.Contains(TEXT("tangentnormal")) ? ProbeTangentNormal : nullptr);
			if (!(bProbeSlot && ProbeBaseName == TEXT("M_AircraftPaint") && LookMic != nullptr))
			{
				PaintTwin = nullptr;
			}
			// Round 25: the plain master this slot draws instead of its class
			// master: -aircraft-probe=flat, -aircraft-probe=coat, or the class
			// master (or its twin) failed to compile on this shader platform
			// (it would draw the engine's default material: rounds 37-40),
			// then the coat master if it compiled, else the flat one.
			UMaterialInterface* Plain = nullptr;
			if (bProbeSlot)
			{
				if (Options.Probes.Contains(TEXT("flat")) && ProbeFlat != nullptr)
				{
					Plain = ProbeFlat;
				}
				else if (Options.Probes.Contains(TEXT("coat")) && ProbeCoat != nullptr && LookMic != nullptr)
				{
					Plain = ProbeCoat;
				}
				else
				{
					UMaterialInterface* Drawn = PaintTwin != nullptr ? PaintTwin : LookInstance;
					if (!CompileProblemOf(Drawn).IsEmpty())
					{
						Plain = (ProbeCoat != nullptr && LookMic != nullptr && CompileProblemOf(ProbeCoat).IsEmpty())
							? ProbeCoat : ProbeFlat;
						if (Plain != nullptr)
						{
							FallbackSlots.FindOrAdd(Plain->GetName()) += 1;
						}
					}
				}
			}
			if (Plain != nullptr && Plain == ProbeCoat)
			{
				// Round 25: the clear-coat paint with no Custom node, every
				// override of the look instance (colour, texture, roughness, coat).
				UMaterialInstanceDynamic* CoatMid = UMaterialInstanceDynamic::Create(ProbeCoat, Part);
				if (CoatMid != nullptr)
				{
					CoatMid->CopyParameterOverrides(LookMic);
					Part->SetMaterial(Slot, CoatMid);
					++Applied;
					++ProbedSlots;
					continue;
				}
			}
			if (Plain != nullptr && Plain == ProbeFlat)
			{
				// A plain lit dielectric with the instance's own colour and texture.
				UMaterialInstanceDynamic* FlatMid = UMaterialInstanceDynamic::Create(ProbeFlat, Part);
				if (FlatMid != nullptr)
				{
					FLinearColor ProbeColour = FLinearColor::White;
					UTexture* ProbeTexture = nullptr;
					float ProbeWeight = 0.0f;
					if (LookInstance->GetVectorParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColor"))), ProbeColour))
					{
						FlatMid->SetVectorParameterValue(TEXT("BaseColor"), ProbeColour);
					}
					if (LookInstance->GetTextureParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColorMap"))), ProbeTexture)
					    && ProbeTexture != nullptr)
					{
						FlatMid->SetTextureParameterValue(TEXT("BaseColorMap"), ProbeTexture);
					}
					if (LookInstance->GetScalarParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColorMapWeight"))), ProbeWeight))
					{
						FlatMid->SetScalarParameterValue(TEXT("BaseColorMapWeight"), ProbeWeight);
					}
					Part->SetMaterial(Slot, FlatMid);
					++Applied;
					++ProbedSlots;
					continue;
				}
			}
			// wet-airframe-canopy: a MID of the look instance, so the wet scalars can be set per step.
			UMaterialInstanceDynamic* LookMid = nullptr;
			if (PaintTwin != nullptr)
			{
				LookMid = UMaterialInstanceDynamic::Create(PaintTwin, Part);
				if (LookMid != nullptr)
				{
					LookMid->CopyParameterOverrides(LookMic);
				}
			}
			// The canopy reflection: a glass slot on its OPAQUE look instance
			// (a -labels render, or no MI_<slot>_thin) draws the reflect master
			// with the instance's overrides; a slot on its thin instance keeps
			// it (round 46's C172 canopy), and the -labels rule above is untouched.
			if (Options.bCanopyReflect && bThin)
			{
				++ReflectThinKept;
			}
			else if (Options.bCanopyReflect && GlassReflect != nullptr && LookMic != nullptr &&
			         ProbeBaseName == AircraftFxOpaqueGlassMaster)
			{
				LookMid = UMaterialInstanceDynamic::Create(GlassReflect, Part);
				if (LookMid != nullptr)
				{
					LookMid->CopyParameterOverrides(LookMic);
					LookMid->SetVectorParameterValue(TEXT("GlassEnvTint"), ReflectTint);
					LookMid->SetScalarParameterValue(TEXT("GlassEnvGain"), 0.0f);  // UpdateCanopyReflect sets it
					ReflectMids.Add(LookMid);
					float SceneScale = 0.0f;
					if (bSceneSky && !LookMid->GetScalarParameterValue(FHashedMaterialParameterInfo(
						FName(FString(TEXT("Glass")) + AircraftFxSceneScaleSuffix)), SceneScale))
					{
						++SceneSkyStale;
					}
					++ReflectSlots;
					ReflectNames.AddUnique(SlotName);
				}
			}
			if (LookMid == nullptr)
			{
				LookMid = UMaterialInstanceDynamic::Create(LookInstance, Part);
			}
			if (bProbeSlot && LookMid != nullptr)
			{
				// Round 25: which graph this slot draws (the master's
				// LookGeneration sentinel; absent = built before generation 7).
				{
					float Generation = 0.0f;
					const UMaterial* DrawnBase = LookMid->GetMaterial();
					const FString DrawnName = DrawnBase != nullptr ? DrawnBase->GetName() : LookMid->GetName();
					MasterGenerations.Add(DrawnName, LookMid->GetScalarParameterValue(
						FHashedMaterialParameterInfo(FName(AircraftFxLookGenerationParam)), Generation)
						? static_cast<double>(Generation) : -1.0);
				}
				// Storm wet paint A/B: the low porosity on the paint and bare-metal
				// MIDs (aircraft_wet_layer.WET_POROSITY_LOW); a master without the
				// wet layer has no WetPorosity and this is a no-op.
				if (Options.WetPorosity == TEXT("low"))
				{
					LookMid->SetScalarParameterValue(TEXT("WetPorosity"),
						ProbeBaseName == TEXT("M_AircraftPaint") ? AircraftFxWetPorosityLowPaint
						                                         : AircraftFxWetPorosityLowBareMetal);
					++WetPorositySlots;
				}
				// The airframe's sky reflection (aircraft_paint_reflect.py): a
				// generation-13 paint / bare-metal MID takes the horizon tint and
				// a gain UpdateCanopyReflect sets from the sun each step; a master
				// built before generation 13 has no PaintEnvGain and is counted
				// stale (the switch is then inert on it, recorded). Off: the
				// master's own 0 stands and nothing is added.
				if (Options.bPaintReflect)
				{
					float PaintGain = 0.0f;
					if (LookMid->GetScalarParameterValue(
						FHashedMaterialParameterInfo(FName(AircraftFxPaintEnvGainParam)), PaintGain))
					{
						LookMid->SetVectorParameterValue(FName(AircraftFxPaintEnvTintParam), ReflectTint);
						LookMid->SetScalarParameterValue(FName(AircraftFxPaintEnvGainParam), 0.0f);
						PaintReflectMids.Add(LookMid);
						++PaintReflectSlots;
						// A master built before generation 16 has no scene-sky
						// scalar: it keeps the strip (counted, recorded).
						float SceneScale = 0.0f;
						if (bSceneSky && !LookMid->GetScalarParameterValue(FHashedMaterialParameterInfo(
							FName(FString(TEXT("Paint")) + AircraftFxSceneScaleSuffix)), SceneScale))
						{
							++SceneSkyStale;
						}
					}
					else
					{
						++PaintReflectStale;
					}
				}
				// Round 24 (aircraft_wet_layer.PROBE_SCALARS on the gen-6 masters).
				if (Options.Probes.Contains(TEXT("nowet")))
				{
					LookMid->SetScalarParameterValue(TEXT("WetLayerAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("rawbase")))
				{
					LookMid->SetScalarParameterValue(TEXT("RawBaseAmount"), 1.0f);
				}
				if (Options.Probes.Contains(TEXT("basecolor-debug")))
				{
					LookMid->SetScalarParameterValue(TEXT("BaseDebug"), 1.0f);
				}
				// Scalar overrides on the gen-5/6 masters' own parameters
				// (aircraft_look.AIRCRAFT_PROBES); a parameter a master lacks
				// (ClearCoat on bare metal) is a no-op.
				if (Options.Probes.Contains(TEXT("nocoat")))
				{
					LookMid->SetScalarParameterValue(TEXT("ClearCoat"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("noao")))
				{
					LookMid->SetScalarParameterValue(TEXT("PanelAoAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("nonormal")))
				{
					LookMid->SetScalarParameterValue(TEXT("PanelNormalAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("nowear")))
				{
					LookMid->SetScalarParameterValue(TEXT("WearAmount"), 0.0f);
					LookMid->SetScalarParameterValue(TEXT("GrimeAmount"), 0.0f);
					LookMid->SetScalarParameterValue(TEXT("SootAmount"), 0.0f);
				}
				// Round 25: a probe whose parameter the drawn master lacks is
				// inert (a master built before its generation); recorded by name.
				{
					TArray<const TCHAR*> Wanted;
					if (Options.Probes.Contains(TEXT("nowet"))) { Wanted.Add(TEXT("WetLayerAmount")); }
					if (Options.Probes.Contains(TEXT("rawbase"))) { Wanted.Add(TEXT("RawBaseAmount")); }
					if (Options.Probes.Contains(TEXT("basecolor-debug"))) { Wanted.Add(TEXT("BaseDebug")); }
					if (Options.Probes.Contains(TEXT("noao"))) { Wanted.Add(TEXT("PanelAoAmount")); }
					if (Options.Probes.Contains(TEXT("nonormal"))) { Wanted.Add(TEXT("PanelNormalAmount")); }
					if (Options.Probes.Contains(TEXT("nowear"))) { Wanted.Add(TEXT("WearAmount")); }
					for (const TCHAR* Name : Wanted)
					{
						float Value = 0.0f;
						if (!LookMid->GetScalarParameterValue(FHashedMaterialParameterInfo(FName(Name)), Value))
						{
							MissingProbeParameters.AddUnique(FString(Name));
						}
					}
				}
				if (Options.Probes.Num() > 0)
				{
					++ProbedSlots;
				}
			}
			Part->SetMaterial(Slot, LookMid != nullptr ? static_cast<UMaterialInterface*>(LookMid) : LookInstance);
			if (LookMid != nullptr) { LookMids.Add(LookMid); }
			++Applied;
			if (bThin)
			{
				++ThinApplied;
				ThinNames.AddUnique(SlotName);
			}
		}
	}
	Row->SetStringField(TEXT("state"), TEXT("look instances on the mesh's slots (shading only: no world position ")
		TEXT("offset; every class master opaque but the thin canopy, which is applied only without -labels, ")
		TEXT("so the label silhouette is the beauty's)"));
	Row->SetStringField(TEXT("instance_root"), AssetRoot + TEXT("/") + AircraftFxLookFolder);
	Row->SetNumberField(TEXT("slots_applied"), Applied);
	Row->SetNumberField(TEXT("slots_without_material"), Unbound);
	Row->SetNumberField(TEXT("slots_thin_translucent"), ThinApplied);
	Row->SetNumberField(TEXT("slots_probed"), ProbedSlots);
	{
		TSharedPtr<FJsonObject> Porosity = MakeShared<FJsonObject>();
		Porosity->SetStringField(TEXT("switch"), Options.WetPorosity);
		Porosity->SetNumberField(TEXT("slots"), WetPorositySlots);
		if (Options.WetPorosity == TEXT("low"))
		{
			Porosity->SetNumberField(TEXT("paint"), AircraftFxWetPorosityLowPaint);
			Porosity->SetNumberField(TEXT("bare_metal"), AircraftFxWetPorosityLowBareMetal);
		}
		else
		{
			Porosity->SetStringField(TEXT("applied"), TEXT("the masters' own WetPorosity (WET_DEFAULTS)"));
		}
		Row->SetObjectField(TEXT("wet_porosity"), Porosity);
	}
	// The airframe's sky reflection's record (aircraft_paint_reflect.py; the
	// gain and sun fields are written by UpdateCanopyReflect each step).
	PaintReflectRow->SetStringField(TEXT("switch"), Options.bPaintReflect
		? TEXT("on (the default; -paint-reflect=off is the A/B)") : TEXT("off (-paint-reflect=off)"));
	PaintReflectRow->SetNumberField(TEXT("slots"), PaintReflectSlots);
	PaintReflectRow->SetNumberField(TEXT("slots_stale_master"), PaintReflectStale);
	PaintReflectRow->SetStringField(TEXT("rule"), TEXT("Emissive += Fresnel(N.V; F0 = lerp(0.08 Specular, BaseColor, ")
		TEXT("Metallic), coat F0 0.04) x (1 - roughness / 0.5)^2 x baked sky strip(reflect(V, N leaned by the ")
		TEXT("rivulets)) x PaintEnvGain x PaintEnvTint x PaintEnvAmount; the gain is the canopy's (canopy_reflect, ")
		TEXT("gain_rule), never 0 for an exterior panel seen from inside; UNCALIBRATED"));
	PaintReflectRow->SetStringField(TEXT("tint_source"), ReflectTintSource);
	PaintReflectRow->SetNumberField(TEXT("cloud_cover"), ReflectCover);
	PaintReflectRow->SetStringField(TEXT("labels"), TEXT("unchanged: the paint and bare-metal masters stay opaque ")
		TEXT("with no world position offset; the reflection is Emissive only, which no label pass reads"));
	Row->SetObjectField(TEXT("paint_reflect"), PaintReflectRow);
	// LOOK_GENERATION 16's record (the ground, tau and scale fields are written
	// by UpdateCanopyReflect each step).
	SceneSkyRow->SetStringField(TEXT("switch"), Options.bReflectSceneSky
		? TEXT("on (the default; -scene-mirror=off draws generation 13's strip)")
		: TEXT("off (-scene-mirror=off: the coastal strip)"));
	SceneSkyRow->SetBoolField(TEXT("active"), bSceneSky);
	SceneSkyRow->SetNumberField(TEXT("slots_stale_master"), SceneSkyStale);
	SceneSkyRow->SetStringField(TEXT("rule"), TEXT("above the horizon: SkyAtmosphereViewLuminance(reflect(V, N)) ")
		TEXT("toward the CIE overcast sky Lz (1 + 2 sin e) / 3 by cloud cover; below: ground x exp(-tau / |r.z|) + ")
		TEXT("the Sky View LUT's in-scatter; horizon blur smoothstep(-2 alpha, 2 alpha, r.z); x 0.5 (0.10 / 0.2, the ")
		TEXT("strip path's level); the strip per pixel where the LUT is not drawn (aircraft_scene_sky.py; UNCALIBRATED)"));
	SceneSkyRow->SetStringField(TEXT("ground_source"), SceneSkyLight != nullptr
		? TEXT("the sky light's lower hemisphere x its colour x intensity (hero lighting: albedo x E / pi)")
		: TEXT("absent: no sky light, ground black (the LUT's in-scatter only)"));
	SceneSkyRow->SetStringField(TEXT("tau_source"), SceneAtmosphere != nullptr
		? TEXT("the scene's SkyAtmosphere (Rayleigh + Mie exponential columns below the aircraft)")
		: TEXT("UE 5.7's default atmosphere's columns (no SkyAtmosphere in the scene)"));
	SceneSkyRow->SetStringField(TEXT("labels"), TEXT("unchanged: Emissive only on opaque masters with no world ")
		TEXT("position offset"));
	Row->SetObjectField(TEXT("scene_sky"), SceneSkyRow);
	// Round 25: the class masters' compile results on this shader platform,
	// the slots that fell back to a plain master, the graph generations drawn
	// and any probe parameter the drawn master lacks.
	{
		TSharedPtr<FJsonObject> Compile = MakeShared<FJsonObject>();
		for (const TPair<FString, FString>& Entry : MasterProblems)
		{
			Compile->SetStringField(Entry.Key, Entry.Value.IsEmpty() ? FString(TEXT("compiled")) : Entry.Value);
		}
		Row->SetObjectField(TEXT("master_compile"), Compile);
		TSharedPtr<FJsonObject> Fallback = MakeShared<FJsonObject>();
		for (const TPair<FString, int32>& Entry : FallbackSlots)
		{
			Fallback->SetNumberField(Entry.Key, Entry.Value);
		}
		Row->SetObjectField(TEXT("slots_fallback"), Fallback);
		TSharedPtr<FJsonObject> Generations = MakeShared<FJsonObject>();
		for (const TPair<FString, double>& Entry : MasterGenerations)
		{
			if (Entry.Value < 0.0)
			{
				Generations->SetStringField(Entry.Key, TEXT("absent: built before LOOK_GENERATION 7 (run ")
					TEXT("scripts/ue_create_materials.py)"));
			}
			else
			{
				Generations->SetNumberField(Entry.Key, Entry.Value);
			}
		}
		Row->SetObjectField(TEXT("master_generation"), Generations);
		TArray<TSharedPtr<FJsonValue>> Missing;
		for (const FString& Name : MissingProbeParameters)
		{
			Missing.Add(MakeShared<FJsonValueString>(Name));
		}
		Row->SetArrayField(TEXT("probe_parameters_missing"), Missing);
		Row->SetStringField(TEXT("fallback_rule"), TEXT("a paint / bare-metal slot draws its class master when it ")
			TEXT("compiled on this shader platform, else M_AircraftPaintCoat (no Custom node), else ")
			TEXT("M_AircraftProbeFlat; -aircraft-probe=flat / coat force one (aircraft_look.MASTER_FALLBACK_ORDER)"));
	}
	Row->SetBoolField(TEXT("labels"), Options.bLabels);
	Row->SetStringField(TEXT("thin_glass"), Options.bLabels
		? TEXT("label-safe opaque glass kept: -labels (the ID and depth captures draw no translucency)")
		: TEXT("MI_<slot>_thin (Thin Translucent, Surface ForwardShading) where it exists: beauty without labels"));
	TArray<TSharedPtr<FJsonValue>> Thin;
	for (const FString& Name : ThinNames)
	{
		Thin.Add(MakeShared<FJsonValueString>(Name));
	}
	Row->SetArrayField(TEXT("slots_thin"), Thin);
	TArray<TSharedPtr<FJsonValue>> Absent;
	for (const FString& Name : AbsentNames)
	{
		Absent.Add(MakeShared<FJsonValueString>(Name));
	}
	Row->SetArrayField(TEXT("slots_absent"), Absent);
	// The canopy reflection's record (aircraft_glass_reflect.py; the gain, sun
	// and camera fields are written by UpdateCanopyReflect / SetCanopyReflectCamera).
	ReflectRow->SetStringField(TEXT("switch"), Options.bCanopyReflect
		? TEXT("on (-canopy-reflect=on)") : TEXT("off (the default; -canopy-reflect=on is the A/B)"));
	ReflectRow->SetStringField(TEXT("lane"), TEXT("swarm/lanes/aircraft_exterior/glass/coastal (tiers 0-1 only: ")
		TEXT("opaque, no translucency, no SSR)"));
	if (Options.bCanopyReflect)
	{
		ReflectRow->SetNumberField(TEXT("tier"), Options.CanopyReflectTier);
		ReflectRow->SetStringField(TEXT("compile"), GlassReflectProblem.IsEmpty()
			? FString(TEXT("compiled")) : GlassReflectProblem);
		ReflectRow->SetNumberField(TEXT("slots"), ReflectSlots);
		ReflectRow->SetNumberField(TEXT("slots_thin_kept"), ReflectThinKept);
		TArray<TSharedPtr<FJsonValue>> Names;
		for (const FString& Name : ReflectNames)
		{
			Names.Add(MakeShared<FJsonValueString>(Name));
		}
		ReflectRow->SetArrayField(TEXT("slot_names"), Names);
		TArray<TSharedPtr<FJsonValue>> TintValues;
		TintValues.Add(MakeShared<FJsonValueNumber>(ReflectTint.R));
		TintValues.Add(MakeShared<FJsonValueNumber>(ReflectTint.G));
		TintValues.Add(MakeShared<FJsonValueNumber>(ReflectTint.B));
		ReflectRow->SetArrayField(TEXT("tint"), TintValues);
		ReflectRow->SetStringField(TEXT("tint_source"), ReflectTintSource);
		ReflectRow->SetNumberField(TEXT("cloud_cover"), ReflectCover);
		ReflectRow->SetStringField(TEXT("sky_condition"), Options.SkyCondition);
		ReflectRow->SetStringField(TEXT("gain_rule"), TEXT("GlassEnvGain = 0.10 x sun Intensity / pi x ")
			TEXT("smoothstep(-2, 8, sun elevation deg) x (1 - 0.75 x cloud cover) / 0.702728; 0 for an interior ")
			TEXT("camera (aircraft_glass_reflect.canopy_reflect_gain; UNCALIBRATED)"));
		ReflectRow->SetStringField(TEXT("labels"), TEXT("unchanged: the reflect masters are opaque and write ")
			TEXT("depth; the reflection is Emissive only, which no label pass reads"));
	}
	Row->SetObjectField(TEXT("canopy_reflect"), ReflectRow);
	UpdateCanopyReflect();
	Record->SetObjectField(TEXT("materials"), Row);
	UE_LOG(LogFlightSimAircraftFX, Display, TEXT("aircraft look: %d slot(s) on look instances, %d absent"),
	       Applied, Absent.Num());
}

double FFlightSimAircraftFX::SceneSkyColumn(double SigmaPerKm, double ScaleHeightKm, double AltitudeKm)
{
	const double H = FMath::Max(ScaleHeightKm, 1.0e-3);
	return FMath::Max(SigmaPerKm, 0.0) * H * (1.0 - FMath::Exp(-FMath::Max(AltitudeKm, 0.0) / H));
}

double FFlightSimAircraftFX::CanopyReflectGain(double SunIntensity, double SunElevationDeg, double Cover,
                                               bool bInterior)
{
	if (bInterior)
	{
		return 0.0;
	}
	const double Day = FMath::SmoothStep(AircraftFxReflectNightFadeLoDeg, AircraftFxReflectNightFadeHiDeg,
	                                     SunElevationDeg);
	const double Sky = 1.0 - AircraftFxReflectOvercastDim * FMath::Clamp(Cover, 0.0, 1.0);
	return AircraftFxReflectSkyShare * FMath::Max(SunIntensity, 0.0) / UE_DOUBLE_PI * Day * Sky /
		AircraftFxReflectStripHorizonLuminance;
}

void FFlightSimAircraftFX::UpdateCanopyReflect()
{
	if (ReflectMids.Num() == 0 && PaintReflectMids.Num() == 0)
	{
		return;
	}
	FVector ToSun(1.0, 0.0, 0.0);
	double Intensity = 0.0;
	const bool bSun = ReflectSun != nullptr && ReflectSun->GetLightComponent() != nullptr;
	if (bSun)
	{
		// A directional light shines along its forward vector: the sun is behind it.
		ToSun = -ReflectSun->GetActorForwardVector();
		Intensity = ReflectSun->GetLightComponent()->Intensity;
	}
	const double ElevationDeg = FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(ToSun.Z, -1.0, 1.0)));
	const double Gain = bSun ? CanopyReflectGain(Intensity, ElevationDeg, ReflectCover, bReflectInterior) : 0.0;
	for (UMaterialInstanceDynamic* Mid : ReflectMids)
	{
		if (Mid != nullptr)
		{
			Mid->SetScalarParameterValue(TEXT("GlassEnvGain"), static_cast<float>(Gain));
			Mid->SetVectorParameterValue(TEXT("GlassSunAzimuthDir"),
			                             FLinearColor(static_cast<float>(ToSun.X), static_cast<float>(ToSun.Y), 0.0f, 0.0f));
		}
	}
	// The airframe's sky reflection: the same sun, the same gain rule, but an
	// exterior panel mirrors the sky from any camera (no interior zero).
	const double PaintGain = bSun ? CanopyReflectGain(Intensity, ElevationDeg, ReflectCover, false) : 0.0;
	for (UMaterialInstanceDynamic* Mid : PaintReflectMids)
	{
		if (Mid != nullptr)
		{
			Mid->SetScalarParameterValue(FName(AircraftFxPaintEnvGainParam), static_cast<float>(PaintGain));
			Mid->SetVectorParameterValue(FName(AircraftFxPaintSunParam),
			                             FLinearColor(static_cast<float>(ToSun.X), static_cast<float>(ToSun.Y), 0.0f, 0.0f));
		}
	}
	// LOOK_GENERATION 16: the scene's ground and the air it is seen through,
	// this step (the sky light's intensity and the aircraft's height may move).
	if (bSceneSky)
	{
		FLinearColor Ground = FLinearColor::Black;
		if (SceneSkyLight != nullptr && SceneSkyLight->bLowerHemisphereIsBlack)
		{
			const FLinearColor Lower = SceneSkyLight->LowerHemisphereColor;
			const FLinearColor Light = SceneSkyLight->GetLightColor();
			const float SkyIntensity = FMath::Max(SceneSkyLight->Intensity, 0.0f);
			Ground = FLinearColor(FMath::Max(Lower.R, 0.0f) * Light.R * SkyIntensity,
			                      FMath::Max(Lower.G, 0.0f) * Light.G * SkyIntensity,
			                      FMath::Max(Lower.B, 0.0f) * Light.B * SkyIntensity, 0.0f);
		}
		// Engine Z = 0 is the ground datum (FFlightSimCloudLayer's convention); cm -> km.
		const double AltitudeKm = Aircraft != nullptr ? FMath::Max(Aircraft->GetActorLocation().Z, 0.0) / 1.0e5 : 0.0;
		double Rayleigh[3] = {AircraftFxDefaultRayleighPerKm[0], AircraftFxDefaultRayleighPerKm[1],
		                      AircraftFxDefaultRayleighPerKm[2]};
		double Mie[3] = {AircraftFxDefaultMiePerKm, AircraftFxDefaultMiePerKm, AircraftFxDefaultMiePerKm};
		double RayleighH = AircraftFxDefaultRayleighHKm;
		double MieH = AircraftFxDefaultMieHKm;
		if (SceneAtmosphere != nullptr)
		{
			const FLinearColor R = SceneAtmosphere->RayleighScattering * SceneAtmosphere->RayleighScatteringScale;
			const FLinearColor M = SceneAtmosphere->MieScattering * SceneAtmosphere->MieScatteringScale +
				SceneAtmosphere->MieAbsorption * SceneAtmosphere->MieAbsorptionScale;
			Rayleigh[0] = R.R; Rayleigh[1] = R.G; Rayleigh[2] = R.B;
			Mie[0] = M.R; Mie[1] = M.G; Mie[2] = M.B;
			RayleighH = SceneAtmosphere->RayleighExponentialDistribution;
			MieH = SceneAtmosphere->MieExponentialDistribution;
		}
		double Tau[3];
		for (int32 C = 0; C < 3; ++C)
		{
			Tau[C] = SceneSkyColumn(Rayleigh[C], RayleighH, AltitudeKm) + SceneSkyColumn(Mie[C], MieH, AltitudeKm);
		}
		const FLinearColor TauColor(static_cast<float>(Tau[0]), static_cast<float>(Tau[1]),
		                            static_cast<float>(Tau[2]), 0.0f);
		auto ApplyScene = [&](UMaterialInstanceDynamic* Mid, const TCHAR* Prefix, double Scale)
		{
			const FString P(Prefix);
			Mid->SetScalarParameterValue(FName(P + AircraftFxSceneScaleSuffix), static_cast<float>(Scale));
			Mid->SetVectorParameterValue(FName(P + AircraftFxSceneGroundSuffix), Ground);
			Mid->SetVectorParameterValue(FName(P + AircraftFxSceneTauSuffix), TauColor);
			Mid->SetScalarParameterValue(FName(P + AircraftFxSceneCoverSuffix), static_cast<float>(ReflectCover));
			Mid->SetScalarParameterValue(FName(P + AircraftFxSceneOvercastSuffix),
			                             static_cast<float>(AircraftFxSceneOvercastShare));
		};
		// An exterior panel mirrors the scene from any camera; the canopy seen
		// from inside takes 0 (the strip, whose gain is 0 there too).
		const double GlassScale = bReflectInterior ? 0.0 : AircraftFxSceneSkyShare;
		for (UMaterialInstanceDynamic* Mid : PaintReflectMids)
		{
			if (Mid != nullptr)
			{
				ApplyScene(Mid, TEXT("Paint"), AircraftFxSceneSkyShare);
			}
		}
		for (UMaterialInstanceDynamic* Mid : ReflectMids)
		{
			if (Mid != nullptr)
			{
				ApplyScene(Mid, TEXT("Glass"), GlassScale);
			}
		}
		if (SceneSkyRow.IsValid())
		{
			TArray<TSharedPtr<FJsonValue>> GroundValues;
			TArray<TSharedPtr<FJsonValue>> TauValues;
			for (int32 C = 0; C < 3; ++C)
			{
				GroundValues.Add(MakeShared<FJsonValueNumber>(C == 0 ? Ground.R : (C == 1 ? Ground.G : Ground.B)));
				TauValues.Add(MakeShared<FJsonValueNumber>(Tau[C]));
			}
			SceneSkyRow->SetArrayField(TEXT("ground_radiance_rgb"), GroundValues);
			SceneSkyRow->SetArrayField(TEXT("ground_tau_rgb"), TauValues);
			SceneSkyRow->SetNumberField(TEXT("altitude_km"), AltitudeKm);
			SceneSkyRow->SetNumberField(TEXT("scene_scale_paint"), AircraftFxSceneSkyShare);
			SceneSkyRow->SetNumberField(TEXT("scene_scale_glass"), GlassScale);
			SceneSkyRow->SetNumberField(TEXT("cloud_cover"), ReflectCover);
		}
	}
	if (PaintReflectRow.IsValid())
	{
		PaintReflectRow->SetNumberField(TEXT("gain"), PaintGain);
		PaintReflectRow->SetStringField(TEXT("sun"), bSun ? TEXT("the scene's sun (its Intensity and direction, each step)")
			: TEXT("absent: no scene sun, PaintEnvGain 0"));
		PaintReflectRow->SetNumberField(TEXT("sun_elevation_deg"), ElevationDeg);
	}
	if (ReflectRow.IsValid())
	{
		// The values of the latest step (the sun may be animated).
		ReflectRow->SetNumberField(TEXT("gain"), Gain);
		ReflectRow->SetStringField(TEXT("sun"), bSun ? TEXT("the scene's sun (its Intensity and direction, each step)")
			: TEXT("absent: no scene sun, GlassEnvGain 0"));
		ReflectRow->SetNumberField(TEXT("sun_intensity"), Intensity);
		ReflectRow->SetNumberField(TEXT("sun_elevation_deg"), ElevationDeg);
	}
}

void FFlightSimAircraftFX::SetCanopyReflectCamera(bool bInterior, const FString& Preset)
{
	bReflectInterior = bInterior;
	if (ReflectRow.IsValid())
	{
		ReflectRow->SetStringField(TEXT("camera_preset"), Preset);
		ReflectRow->SetBoolField(TEXT("interior_camera"), bInterior);
	}
	UpdateCanopyReflect();
}

void FFlightSimAircraftFX::BuildLamp(UWorld* World, const TSharedPtr<FJsonObject>& Row)
{
	if (!Row.IsValid())
	{
		return;
	}
	FLamp Lamp;
	Row->TryGetStringField(TEXT("id"), Lamp.Id);
	Row->TryGetStringField(TEXT("kind"), Lamp.Kind);
	Row->TryGetNumberField(TEXT("candela"), Lamp.Candela);
	Row->TryGetBoolField(TEXT("strobe"), Lamp.bStrobe);
	Lamp.bLanding = Lamp.Kind == TEXT("landing");
	Lamp.ActorCm = AircraftFxVector(Row, TEXT("actor_cm"));
	const FVector Colour = AircraftFxVector(Row, TEXT("colour"));
	const FLinearColor Linear(Colour.X, Colour.Y, Colour.Z, 1.0f);
	const double Gain = Constant(TEXT("lights"), TEXT("LightVisualGain"), 1.0);

	AActor* Actor = SpawnAttached(World, Lamp.ActorCm, *FString::Printf(TEXT("Lamp_%s"), *Lamp.Id));
	UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
	UMaterialInterface* BulbMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxNavMaterialPath);
	if (Mesh != nullptr && BulbMaterial != nullptr)
	{
		const double RadiusCm = Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0);
		AircraftFxBulbSection(Mesh, RadiusCm);
		Lamp.Bulb = UMaterialInstanceDynamic::Create(BulbMaterial, Mesh);
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamLightColour), Linear);
		// The bulb's luminance is the lamp's own candela over the sprite's
		// effective area (aircraft_look.py bulb_luminance_nits): the light the
		// lamp throws and the lamp the camera sees are one number, metered by
		// the frame's one exposure. No cap.
		if (!Row->TryGetNumberField(TEXT("bulb_luminance_nits"), Lamp.BulbNits))
		{
			const double RadiusM = FMath::Max(RadiusCm, 0.01) / AircraftFxCmPerMetre;
			Lamp.BulbNits = Lamp.Candela * Gain / (AircraftFxNavBulbAreaFactor * RadiusM * RadiusM);
		}
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamIntensity), static_cast<float>(Lamp.BulbNits));
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), Lamp.bStrobe ? 0.0f : 1.0f);
		// A landing lamp is a beam: its bulb fades outside the spot's own cone.
		FVector2D BeamCos(AircraftFxOmniBeamCos, AircraftFxOmniBeamCos);
		AircraftFxPair(Row, TEXT("beam_cos"), BeamCos);
		FVector BeamDirection = AircraftFxVector(Row, TEXT("direction_actor"));
		if (BeamDirection.IsNearlyZero())
		{
			BeamDirection = FVector(1.0, 0.0, 0.0);
		}
		BeamDirection = BeamDirection.GetSafeNormal();
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamBeamDirection),
			FLinearColor(BeamDirection.X, BeamDirection.Y, BeamDirection.Z, 0.0f));
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamBeamCos),
			FLinearColor(BeamCos.X, BeamCos.Y, 0.0f, 0.0f));
		Mesh->SetMaterial(0, Lamp.Bulb);
	}
	if (Lamp.bLanding)
	{
		Lamp.Spot = NewObject<USpotLightComponent>(Actor, TEXT("LandingLight"));
		Lamp.Spot->SetMobility(EComponentMobility::Movable);
		Lamp.Spot->SetupAttachment(Actor->GetRootComponent());
		FVector Direction = AircraftFxVector(Row, TEXT("direction_actor"));
		if (Direction.IsNearlyZero())
		{
			Direction = FVector(1.0, 0.0, -0.08);
		}
		Lamp.Spot->SetRelativeRotation(FRotationMatrix::MakeFromX(Direction.GetSafeNormal()).Rotator());
		Lamp.Spot->SetIntensityUnits(ELightUnits::Candelas);
		Lamp.Spot->SetIntensity(0.0f);
		Lamp.Spot->SetLightColor(Linear);
		const float Cone = static_cast<float>(Constant(TEXT("lights"), TEXT("LandingConeDeg"), 12.0));
		Lamp.Spot->SetInnerConeAngle(0.5f * Cone);
		Lamp.Spot->SetOuterConeAngle(Cone);
		Lamp.Spot->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("lights"), TEXT("LandingAttenuationM"), 900.0) * AircraftFxCmPerMetre));
		// round-2b weather-fx: in fog or rain a lamp at full volumetric
		// scattering draws its whole cone as a lit solid (round 0 #09: hard-edged
		// cones under the 747). A stated fraction, UNCALIBRATED; the falloff
		// between the inner and outer cone keeps its edge soft.
		Lamp.Spot->SetVolumetricScatteringIntensity(static_cast<float>(
			Constant(TEXT("lights"), TEXT("LandingVolumetricScattering"), AircraftFxLandingVolumetricScattering)));
		Lamp.Spot->SetSourceRadius(static_cast<float>(Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0)));
		Lamp.Spot->SetCastShadows(false);
		Lamp.Spot->RegisterComponent();
	}
	else
	{
		Lamp.Point = NewObject<UPointLightComponent>(Actor, TEXT("NavLight"));
		Lamp.Point->SetMobility(EComponentMobility::Movable);
		Lamp.Point->SetupAttachment(Actor->GetRootComponent());
		Lamp.Point->SetIntensityUnits(ELightUnits::Candelas);
		Lamp.Point->SetIntensity(Lamp.bStrobe ? 0.0f : static_cast<float>(Lamp.Candela * Gain));
		Lamp.Point->SetLightColor(Linear);
		Lamp.Point->SetSourceRadius(static_cast<float>(Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0)));
		Lamp.Point->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("lights"), TEXT("NavAttenuationM"), 40.0) * AircraftFxCmPerMetre));
		// round-2b weather-fx: a halo in the fog, not a lit ball (UNCALIBRATED).
		Lamp.Point->SetVolumetricScatteringIntensity(static_cast<float>(
			Constant(TEXT("lights"), TEXT("NavVolumetricScattering"), AircraftFxNavVolumetricScattering)));
		Lamp.Point->SetCastShadows(false);
		Lamp.Point->RegisterComponent();
	}
	Lamps.Add(Lamp);
}

void FFlightSimAircraftFX::BuildNozzle(UWorld* World, const TSharedPtr<FJsonObject>& Row,
                                       const FFlightSimAircraftFXOptions& Options)
{
	if (!Row.IsValid())
	{
		return;
	}
	FNozzle Nozzle;
	Row->TryGetStringField(TEXT("id"), Nozzle.Id);
	Row->TryGetNumberField(TEXT("radius_cm"), Nozzle.RadiusCm);
	Row->TryGetBoolField(TEXT("afterburner"), Nozzle.bAfterburner);
	Row->TryGetStringField(TEXT("thrust_property"), Nozzle.ThrustProperty);
	Row->TryGetNumberField(TEXT("mil_thrust_lbs"), Nozzle.MilThrustLbs);
	Row->TryGetNumberField(TEXT("max_thrust_lbs"), Nozzle.MaxThrustLbs);
	Nozzle.ActorCm = AircraftFxVector(Row, TEXT("actor_cm"));
	const bool bReheat = Options.bAfterburner && Nozzle.bAfterburner && Nozzle.MaxThrustLbs > Nozzle.MilThrustLbs
		&& Nozzle.MilThrustLbs > 0.0;
	if (bReheat)
	{
		UMaterialInterface* PlumeMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxAfterburnerMaterialPath);
		AActor* Actor = SpawnAttached(World, Nozzle.ActorCm, *FString::Printf(TEXT("Plume_%s"), *Nozzle.Id));
		UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
		if (Mesh != nullptr && PlumeMaterial != nullptr)
		{
			const double Length = Constant(TEXT("afterburner"), TEXT("PlumeLengthRadii"), 7.0) * Nozzle.RadiusCm;
			AircraftFxConeSection(Mesh, 0.85 * Nozzle.RadiusCm, 0.3 * Nozzle.RadiusCm, Length);
			Nozzle.Plume = UMaterialInstanceDynamic::Create(PlumeMaterial, Mesh);
			Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamIntensity), 0.0f);
			// The flame's luminance from AfterburnerCandela, the plume light's
			// own (aircraft_look.py plume_luminance): hue x core luminance.
			const FVector Core = AircraftFxVector(Row, TEXT("plume_core_colour"));
			const FVector Tip = AircraftFxVector(Row, TEXT("plume_tip_colour"));
			Row->TryGetNumberField(TEXT("plume_luminance_nits"), Nozzle.PlumeLuminanceNits);
			if (!Core.IsNearlyZero())
			{
				Nozzle.Plume->SetVectorParameterValue(FName(AircraftFxParamCoreColour),
					FLinearColor(Core.X, Core.Y, Core.Z, 1.0f));
				Nozzle.Plume->SetVectorParameterValue(FName(AircraftFxParamTipColour),
					FLinearColor(Tip.X, Tip.Y, Tip.Z, 1.0f));
			}
			Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamShocks),
				static_cast<float>(Constant(TEXT("afterburner"), TEXT("Shocks"), 5.0)));
			Mesh->SetMaterial(0, Nozzle.Plume);
		}
		Nozzle.PlumeLight = NewObject<UPointLightComponent>(Actor, TEXT("AfterburnerLight"));
		Nozzle.PlumeLight->SetMobility(EComponentMobility::Movable);
		Nozzle.PlumeLight->SetupAttachment(Actor->GetRootComponent());
		Nozzle.PlumeLight->SetRelativeLocation(FVector(-1.5 * Nozzle.RadiusCm, 0.0, 0.0));
		Nozzle.PlumeLight->SetIntensityUnits(ELightUnits::Candelas);
		Nozzle.PlumeLight->SetIntensity(0.0f);
		Nozzle.PlumeLight->SetLightColor(FLinearColor(1.0f, 0.55f, 0.25f, 1.0f));
		Nozzle.PlumeLight->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("afterburner"), TEXT("AttenuationM"), 25.0) * AircraftFxCmPerMetre));
		Nozzle.PlumeLight->SetCastShadows(false);
		Nozzle.PlumeLight->RegisterComponent();
	}
	if (Options.bHeatHaze)
	{
		UMaterialInterface* HazeMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxHeatHazeMaterialPath);
		if (HazeMaterial != nullptr)
		{
			AActor* Actor = SpawnAttached(World, Nozzle.ActorCm, *FString::Printf(TEXT("Haze_%s"), *Nozzle.Id));
			UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
			const double Length = Constant(TEXT("heat_haze"), TEXT("LengthRadii"), 14.0) * Nozzle.RadiusCm;
			AircraftFxConeSection(Mesh, Nozzle.RadiusCm, 2.0 * Nozzle.RadiusCm, Length);
			Nozzle.Haze = UMaterialInstanceDynamic::Create(HazeMaterial, Mesh);
			Nozzle.Haze->SetScalarParameterValue(FName(AircraftFxParamStrength),
				static_cast<float>(Constant(TEXT("heat_haze"), TEXT("Strength"), 0.6)));
			Mesh->SetMaterial(0, Nozzle.Haze);
		}
	}
	Nozzles.Add(Nozzle);
}

void FFlightSimAircraftFX::RebuildTrail(FTrail& Trail, double NowS, double LifetimeS, const FTrailShape& Shape)
{
	// Expire what has faded (each sample by its OWN lifetime: the persistence
	// gate stretched it where the air was ice-supersaturated), then a crossed
	// ribbon (two strips at right angles) through every sample: no camera
	// needed, seen from any side.
	Trail.Samples.RemoveAll([&](const FTrailSample& S) { return NowS - S.TimeS > FMath::Max(S.LifetimeS, 0.01); });
	if (Trail.Samples.Num() < 2)
	{
		Trail.Mesh->ClearMeshSection(0);
		return;
	}
	const int32 Count = Trail.Samples.Num();
	// LOOK_GENERATION 13 (hyperreal contrails): where each sample's air is NOW.
	// The wake vortex roll-up draws the plume sideways to its side's vortex
	// core (a smoothstep over VortexRollupS) and the pair sinks at
	// WakeSinkMPerS; a vapour trail has neither (VortexOffsetM 0, VortexRollupS 0).
	// Twin: aircraft_look.contrail_wake_offset_m.
	TArray<FVector> Displaced;
	Displaced.Reserve(Count);
	for (int32 i = 0; i < Count; ++i)
	{
		const FTrailSample& S = Trail.Samples[i];
		const double Age = FMath::Max(NowS - S.TimeS, 0.0);
		double Lateral = 0.0;
		if (Shape.VortexRollupS > 0.0)
		{
			const double T = FMath::Min(Age / Shape.VortexRollupS, 1.0);
			Lateral = Trail.VortexOffsetM * T * T * (3.0 - 2.0 * T);
		}
		const double Sink = Shape.WakeSinkMPerS * Age;
		Displaced.Add(S.WorldCm + S.RightWorld * (Lateral * AircraftFxCmPerMetre)
		              - FVector::UpVector * (Sink * AircraftFxCmPerMetre));
	}
	// Vertices relative to the newest sample (small numbers in a large world).
	const FVector Anchor = Displaced.Last();
	Trail.Owner->SetActorLocation(Anchor);
	TArray<FVector> Vertices;
	TArray<int32> Triangles;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	// LOOK_GENERATION 14: UV1 the ribbon's unit axis x, y; UV2 its z and the strip
	// index (contrail_opacity.hlsl's per-strip view weight; the owner actor is
	// never rotated, so the local axis is the world axis).
	TArray<FVector2D> UV1;
	TArray<FVector2D> UV2;
	// LOOK_GENERATION 15: UV3 x the half width, cm (contrail_facing.hlsl).
	TArray<FVector2D> UV3;
	TArray<FLinearColor> Colours;
	for (int32 Strip = 0; Strip < 2; ++Strip)
	{
		const int32 Base = Vertices.Num();
		for (int32 i = 0; i < Count; ++i)
		{
			const FTrailSample& S = Trail.Samples[i];
			const FVector Prev = Displaced[FMath::Max(i - 1, 0)];
			const FVector Next = Displaced[FMath::Min(i + 1, Count - 1)];
			const FVector Along = (Next - Prev).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
			FVector Side = FVector::CrossProduct(Along, FVector::UpVector).GetSafeNormal(UE_SMALL_NUMBER,
			                                                                           FVector::RightVector);
			const FVector Up = FVector::CrossProduct(Side, Along).GetSafeNormal();
			const FVector Across = Strip == 0 ? Side : Up;
			const FVector Normal = Strip == 0 ? Up : Side;
			const double Age = FMath::Max(NowS - S.TimeS, 0.0);
			// Width: the jet regime's saturating spread plus the slow diffusion
			// (twin aircraft_look.contrail_width_m). Generation 12's StartWidthM +
			// SpreadMPerS x age alone grew 1.2 m to 1.6 m over a chase frame's 110 m.
			const double WidthM = Shape.StartWidthM
				+ Shape.JetSpreadM * (1.0 - FMath::Exp(-Age / FMath::Max(Shape.JetMixS, 0.001)))
				+ Shape.SpreadMPerS * Age;
			const double HalfCm = 0.5 * WidthM * AircraftFxCmPerMetre;
			const FVector P = Displaced[i] - Anchor;
			Vertices.Add(P - Across * HalfCm);
			Vertices.Add(P + Across * HalfCm);
			// Half-cylinder normals: the rim leans outward, so under directional
			// translucency lighting the tube has a sun side and a shadow side.
			Normals.Add((Normal - Across).GetSafeNormal(UE_SMALL_NUMBER, Normal));
			Normals.Add((Normal + Across).GetSafeNormal(UE_SMALL_NUMBER, Normal));
			// UV.x: the formation clock, age / the trail's base lifetime (the
			// material's Formation / FormationRamp are fractions of it).
			const double U = Age / FMath::Max(LifetimeS, 0.01);
			UV0.Add(FVector2D(U, 0.0));
			UV0.Add(FVector2D(U, 1.0));
			UV1.Add(FVector2D(Along.X, Along.Y));
			UV1.Add(FVector2D(Along.X, Along.Y));
			UV2.Add(FVector2D(Along.Z, static_cast<double>(Strip)));
			UV2.Add(FVector2D(Along.Z, static_cast<double>(Strip)));
			UV3.Add(FVector2D(HalfCm, 0.0));
			UV3.Add(FVector2D(HalfCm, 0.0));
			// Vertex colour R: Life, age / this sample's own lifetime (the fade,
			// the rim softening and the puff cut run on it; contrail_opacity.hlsl).
			const float Life = static_cast<float>(FMath::Clamp(Age / FMath::Max(S.LifetimeS, 0.01), 0.0, 1.0));
			const FLinearColor Colour(Life, 1.0f, 1.0f, 1.0f);
			Colours.Add(Colour);
			Colours.Add(Colour);
		}
		for (int32 i = 0; i + 1 < Count; ++i)
		{
			const int32 A = Base + 2 * i;
			Triangles.Append({A, A + 2, A + 1, A + 1, A + 2, A + 3});
		}
	}
	Trail.Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, UV1, UV2, UV3,
	                                          Colours, TArray<FProcMeshTangent>(), false);
	Trail.bEverDrawn = true;
}

void FFlightSimAircraftFX::Advance(TFunctionRef<double(const TCHAR*)> ReadProperty)
{
	if (!bBuilt || Aircraft == nullptr)
	{
		return;
	}
	const double Now = ReadProperty(TEXT("simulation/sim-time-sec"));
	const FTransform Frame = Aircraft->GetActorTransform();

	// -- lamps: steady nav lamps, the strobe on the FDM's clock, the landing
	// lamp below LandingMaxAglM.
	const double Gain = Constant(TEXT("lights"), TEXT("LightVisualGain"), 1.0);
	const double Period = FMath::Max(Constant(TEXT("lights"), TEXT("StrobePeriodS"), 1.0), 0.05);
	const double Flash = Constant(TEXT("lights"), TEXT("StrobeFlashS"), 0.12);
	const bool bStrobeOn = FMath::Fmod(FMath::Max(Now, 0.0), Period) < Flash;
	const double AglM = ReadProperty(TEXT("position/h-agl-ft")) * 0.3048;
	const bool bLandingOn = AglM < Constant(TEXT("lights"), TEXT("LandingMaxAglM"), 450.0);
	for (FLamp& Lamp : Lamps)
	{
		if (Lamp.bStrobe)
		{
			if (Lamp.Point != nullptr)
			{
				Lamp.Point->SetIntensity(bStrobeOn ? static_cast<float>(Lamp.Candela * Gain) : 0.0f);
			}
			if (Lamp.Bulb != nullptr)
			{
				Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), bStrobeOn ? 1.0f : 0.0f);
			}
		}
		if (Lamp.bLanding)
		{
			if (Lamp.Spot != nullptr)
			{
				Lamp.Spot->SetIntensity(bLandingOn ? static_cast<float>(Lamp.Candela * Gain) : 0.0f);
			}
			if (Lamp.Bulb != nullptr)
			{
				Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), bLandingOn ? 1.0f : 0.0f);
			}
		}
	}
	StrobeOnFrames += bStrobeOn ? 1 : 0;
	LandingOnFrames += bLandingOn ? 1 : 0;

	// -- the afterburner: glow from the engine's thrust above its military
	// rating (static sea-level ratings from the engine file).
	const double GlowGain = Constant(TEXT("afterburner"), TEXT("GlowGain"), 1.0);
	const double PlumeCandela = Constant(TEXT("afterburner"), TEXT("AfterburnerCandela"), 6.0e4);
	for (FNozzle& Nozzle : Nozzles)
	{
		if (Nozzle.Plume != nullptr || Nozzle.PlumeLight != nullptr)
		{
			const double Thrust = ReadProperty(*Nozzle.ThrustProperty);
			const double MilFraction = Nozzle.MilThrustLbs / Nozzle.MaxThrustLbs;
			const double Glow = GlowGain * FMath::Clamp(
				(Thrust / Nozzle.MaxThrustLbs - MilFraction) / FMath::Max(1.0 - MilFraction, 0.01), 0.0, 1.0);
			PeakAfterburner = FMath::Max(PeakAfterburner, Glow);
			if (Nozzle.Plume != nullptr)
			{
				Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamIntensity), static_cast<float>(Glow));
			}
			if (Nozzle.PlumeLight != nullptr)
			{
				Nozzle.PlumeLight->SetIntensity(static_cast<float>(Glow * PlumeCandela));
			}
		}
		if (Nozzle.Haze != nullptr)
		{
			Nozzle.Haze->SetScalarParameterValue(FName(AircraftFxParamTime), static_cast<float>(Now));
		}
	}

	// -- trails ---------------------------------------------------------------
	const double TemperatureK = ReadProperty(TEXT("atmosphere/T-R")) * AircraftFxKelvinPerRankine;
	const double AltitudeM = ReadProperty(TEXT("position/h-sl-meters"));
	const bool bContrail = TemperatureK < Constant(TEXT("contrail"), TEXT("MaxTemperatureK"), 233.15)
		&& AltitudeM > Constant(TEXT("contrail"), TEXT("MinAltitudeM"), 7500.0);
	// condensation-solver: the humidity test per site; the old Nz rule only when RH is unavailable.
	const bool bVapour = Condensation.Advance(ReadProperty, Record) ||
		(!Condensation.HasHumidity() && ReadProperty(TEXT("accelerations/Nz")) > Constant(TEXT("vapour"), TEXT("MinNz"), 4.0));
	const double SpeedCmS = ReadProperty(TEXT("velocities/vtrue-kts")) * AircraftFxMpsPerKnot * AircraftFxCmPerMetre;
	ContrailFrames += bContrail ? 1 : 0;
	// A contrail inside a cloud layer is inside the cloud: its opacity x
	// (1 - cover) of every layer the aircraft is in (heights above the
	// ground datum, engine Z = 0, as FFlightSimCloudLayer states).
	const double AircraftZM = Aircraft->GetActorLocation().Z / AircraftFxCmPerMetre;
	double CloudClear = 1.0;
	for (const FFlightSimCloudLayer& Layer : CloudLayers)
	{
		if (AircraftZM >= Layer.BaseMetres && AircraftZM <= Layer.TopMetres)
		{
			CloudClear *= 1.0 - FMath::Clamp(Layer.CoverFraction, 0.0, 1.0);
		}
	}
	ContrailInCloudFrames += (bContrail && CloudClear < 1.0) ? 1 : 0;
	VapourFrames += bVapour ? 1 : 0;
	// LOOK_GENERATION 13: the persistence gate (the stated physics, where the
	// humidity exists). A contrail persists only in ice-supersaturated air:
	// RHi = RH x e_sat,water / e_sat,ice; the factor lifts a NEW sample's
	// lifetime from LifetimeS towards PersistentLifetimeS. No humidity: 0, as
	// before. Twin: aircraft_look.contrail_persistence.
	const double ContrailLifetimeS = Constant(TEXT("contrail"), TEXT("LifetimeS"), 25.0);
	ContrailRhiPct = 0.0;
	ContrailPersistence = 0.0;
	if (Condensation.HasHumidity())
	{
		ContrailRhiPct = Condensation.RelativeHumidityPct() * AircraftFxIceOverWaterSaturation(TemperatureK);
		ContrailPersistence = FMath::Clamp(
			(ContrailRhiPct - Constant(TEXT("contrail"), TEXT("PersistenceRhiOnsetPct"), 100.0))
			/ FMath::Max(Constant(TEXT("contrail"), TEXT("PersistenceRhiSpanPct"), 20.0), 0.001), 0.0, 1.0);
	}
	ContrailLifetimeNowS = ContrailLifetimeS + ContrailPersistence
		* (Constant(TEXT("contrail"), TEXT("PersistentLifetimeS"), 240.0) - ContrailLifetimeS);
	PersistentFrames += (bContrail && ContrailPersistence > 0.0) ? 1 : 0;
	const FVector RightWorld = Frame.GetUnitAxis(EAxis::Y).GetSafeNormal(UE_SMALL_NUMBER, FVector::RightVector);
	for (FTrail& Trail : Trails)
	{
		const TCHAR* Group = Trail.bVapour ? TEXT("vapour") : TEXT("contrail");
		const bool bActive = Trail.bVapour ? bVapour : bContrail;
		if (!Trail.bVapour && Trail.Instance != nullptr)
		{
			Trail.Instance->SetScalarParameterValue(FName(AircraftFxParamOpacity),
				static_cast<float>(Trail.BaseOpacity * CloudClear));
		}
		const FVector Source = Frame.TransformPosition(Trail.SourceActorCm);
		const double BaseLifetime = Constant(Group, TEXT("LifetimeS"), Trail.bVapour ? 0.8 : 25.0);
		const double SampleLifetime = Trail.bVapour ? BaseLifetime : ContrailLifetimeNowS;
		if (bActive)
		{
			// First frame in the regime: a trail as long as PreseedS of the
			// current flight path already behind the aircraft (a straight
			// extrapolation along its nose, stated), so frame 0 of a cruise
			// clip is not a trail just starting.
			if (bFirstAdvance && !Trail.bVapour)
			{
				const double Preseed = Constant(TEXT("contrail"), TEXT("PreseedS"), 8.0);
				const FVector Back = -Frame.GetUnitAxis(EAxis::X) * SpeedCmS;
				for (double Ago = Preseed; Ago > 0.0; Ago -= 0.5)
				{
					FTrailSample Seed;
					Seed.WorldCm = Source + Back * Ago;
					Seed.TimeS = Now - Ago;
					Seed.RightWorld = RightWorld;
					Seed.LifetimeS = SampleLifetime;
					Trail.Samples.Add(Seed);
				}
			}
			FTrailSample Sample;
			Sample.WorldCm = Source;
			Sample.TimeS = Now;
			Sample.RightWorld = RightWorld;
			Sample.LifetimeS = SampleLifetime;
			Trail.Samples.Add(Sample);
		}
		FTrailShape Shape;
		Shape.StartWidthM = Constant(Group, TEXT("StartWidthM"), Trail.bVapour ? 0.25 : 1.2);
		Shape.SpreadMPerS = Constant(Group, TEXT("SpreadMPerS"), Trail.bVapour ? 1.5 : 0.9);
		if (!Trail.bVapour)
		{
			Shape.JetSpreadM = Constant(TEXT("contrail"), TEXT("JetSpreadM"), 10.0);
			Shape.JetMixS = Constant(TEXT("contrail"), TEXT("JetMixS"), 1.5);
			Shape.VortexRollupS = Constant(TEXT("contrail"), TEXT("VortexRollupS"), 12.0);
			Shape.WakeSinkMPerS = Constant(TEXT("contrail"), TEXT("WakeSinkMPerS"), 1.5);
		}
		RebuildTrail(Trail, Now, BaseLifetime, Shape);
	}
	bFirstAdvance = false;

	// The record, current at every step (render.json is written at the end).
	const TSharedPtr<FJsonObject>* ContrailRow = nullptr;
	if (Record->TryGetObjectField(TEXT("contrail"), ContrailRow) && ContrailRow != nullptr)
	{
		(*ContrailRow)->SetNumberField(TEXT("contrail_frames"), ContrailFrames);
		(*ContrailRow)->SetNumberField(TEXT("vapour_frames"), VapourFrames);
		(*ContrailRow)->SetNumberField(TEXT("contrail_in_cloud_frames"), ContrailInCloudFrames);
		const TSharedPtr<FJsonObject>* PersistenceRow = nullptr;
		if ((*ContrailRow)->TryGetObjectField(TEXT("persistence"), PersistenceRow) && PersistenceRow != nullptr)
		{
			(*PersistenceRow)->SetNumberField(TEXT("rhi_pct"), ContrailRhiPct);
			(*PersistenceRow)->SetNumberField(TEXT("factor"), ContrailPersistence);
			(*PersistenceRow)->SetNumberField(TEXT("lifetime_now_s"), ContrailLifetimeNowS);
			(*PersistenceRow)->SetNumberField(TEXT("persistent_frames"), PersistentFrames);
		}
	}
	TSharedPtr<FJsonObject> Afterburner = MakeShared<FJsonObject>();
	Afterburner->SetNumberField(TEXT("peak_glow"), PeakAfterburner);
	double PlumeNits = 0.0;
	for (const FNozzle& Nozzle : Nozzles)
	{
		PlumeNits = FMath::Max(PlumeNits, Nozzle.PlumeLuminanceNits);
	}
	Afterburner->SetNumberField(TEXT("plume_luminance_nits_at_full_glow"), PlumeNits);
	Afterburner->SetStringField(TEXT("rule"), TEXT("glow = saturate((thrust/max - mil/max) / (1 - mil/max)) x GlowGain, ")
		TEXT("static sea-level ratings from the engine file; additive plume, hides nothing"));
	Record->SetObjectField(TEXT("afterburner"), Afterburner);
	Record->SetNumberField(TEXT("strobe_on_frames"), StrobeOnFrames);
	Record->SetNumberField(TEXT("landing_light_on_frames"), LandingOnFrames);
	// wet-airframe-canopy: the weather's wetness on the look MIDs (shading only).
	UpdateCanopyReflect();  // the canopy reflection: the sun as it is this step
	if (Weather != nullptr) { Wet.Advance(LookMids, *Weather, ReadProperty(TEXT("velocities/vtrue-kts")), ReadProperty(TEXT("simulation/sim-time-sec")), Record); }
}
