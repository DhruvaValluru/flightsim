// Sun shafts and sky occlusion (FlightSimSunShafts.h). BEAUTY ONLY: reached
// from FFlightSimWorldBeauty::Build, which the render commandlet calls only
// under -quality=beauty / -quality=pathtrace.
//
// UNCOMPILED when written (2026-11-09, a Mac whose Xcode is above UE 5.7's
// cap): every engine symbol below was read in the UE 5.7.4 headers and is
// listed in scripts/check_bridge_api.sh ("sun-shafts-sky-occlusion"); every
// cvar name was grepped in the 5.7.4 Renderer source. The pure block is
// parsed and compiled by tests/test_sun_shafts.py against
// core/scene/sun_shafts.py. Names here are file-unique (unity builds merge
// anonymous namespaces).

#include "FlightSimSunShafts.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "Engine/World.h"
#include "FlightSimVisualScene.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformMisc.h"
#include "Misc/Parse.h"

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimSunShafts, Log, All);

// The table, dependency-free C++17 so tests/test_sun_shafts.py can compile
// this block alone and compare it with core/scene/sun_shafts.py row for row.
// EVERY value is UNCALIBRATED (docs/visual/PROBE_LOG.md
// ## sun-shafts-sky-occlusion).
// FLIGHTSIM-SUNSHAFTS-PURE-BEGIN
namespace FlightSimSunShaftsPure
{
	enum : int
	{
		PresetCount = 5
	};
	enum : int
	{
		FieldShaftOcclusionDarkness = 0,
		FieldShaftOcclusionDepthRangeM = 1,
		FieldShaftBloomScale = 2,
		FieldShaftBloomThreshold = 3,
		FieldShaftBloomMax = 4,
		FieldCloudShadowOnAtmosphere = 5,
		FieldCloudShadowOnSurface = 6,
		FieldCloudShadowExtentKm = 7,
		FieldCloudShadowMapResScale = 8,
		FieldCloudShadowRaySampleScale = 9,
		FieldSkyAoStrength = 10,
		FieldSkyAoExtentKm = 11,
		FieldSkyAoMapResScale = 12,
		FieldSkyAoApertureScale = 13,
		FieldVfogGridPx = 14,
		FieldVfogGridZ = 15,
		FieldCount = 16
	};

	inline const char* PresetName(int Preset)
	{
		static const char* const Names[PresetCount] = {"clear", "hazy", "overcast", "rain", "storm"};
		return Preset >= 0 && Preset < PresetCount ? Names[Preset] : "clear";
	}

	// darkness, depth_m, bloom scale, threshold, max, shadow atm, surface, extent_km,
	// map res, ray samples, sky AO, AO extent_km, AO map res, AO aperture, fog px, fog z
	constexpr double Rows[PresetCount][FieldCount] = {
		/* clear */    {0.4, 20000.0, 0.2, 8.0, 100.0, 1.0, 1.0, 150.0, 2.0, 2.0, 0.5, 150.0, 2.0, 0.05, 4.0, 128.0},
		/* hazy */     {0.3, 20000.0, 0.25, 6.0, 100.0, 1.0, 1.0, 150.0, 2.0, 2.0, 0.6, 150.0, 2.0, 0.05, 4.0, 128.0},
		/* overcast */ {0.6, 5000.0, 0.0, 16.0, 10.0, 0.6, 0.8, 100.0, 2.0, 2.0, 1.0, 100.0, 2.0, 0.1, 4.0, 128.0},
		/* rain */     {0.6, 5000.0, 0.02, 16.0, 10.0, 0.5, 0.8, 80.0, 2.0, 2.0, 1.0, 80.0, 2.0, 0.1, 4.0, 128.0},
		/* storm */    {0.7, 5000.0, 0.0, 16.0, 10.0, 0.5, 0.9, 80.0, 2.0, 2.0, 1.0, 80.0, 2.0, 0.1, 4.0, 128.0},
	};

	inline double Value(int Preset, int Field)
	{
		const int P = Preset >= 0 && Preset < PresetCount ? Preset : 0;
		return Field >= 0 && Field < FieldCount ? Rows[P][Field] : 0.0;
	}

	struct FCvarRow
	{
		const char* Name;
		double Value;
	};

	// Fed from the preset row; still tier only.
	constexpr const char* FogGridPixelCvar = "r.VolumetricFog.GridPixelSize";
	constexpr const char* FogGridZCvar = "r.VolumetricFog.GridSizeZ";

	// Still tier (the frame accumulates). LightShaftNumSamples was asked for
	// and dropped: ECVF_ReadOnly in the 5.7.4 LightShaftRendering.cpp.
	constexpr FCvarRow StillCvars[] = {
		{"r.VolumetricFog.HistoryMissSupersampleCount", 16.0},
		{"r.VolumetricCloud.ShadowMap", 1.0},
		{"r.VolumetricCloud.SkyAO", 1.0},
		{"r.VolumetricCloud.HighQualityAerialPerspective", 1.0},
		{"r.VolumetricCloud.Shadow.SampleAtmosphericLightShadowmap", 1.0},
		{"r.SkyLight.RealTimeReflectionCapture.TimeSlice", 0.0},
		{"r.SkyLight.RealTimeReflectionCapture.VolumetricCloudResolutionDivider", 1.0},
		{"r.SkyLight.RealTimeReflectionCapture.ShadowFromOpaque", 1.0},
		{"r.LightShaftQuality", 1.0},
		{"r.LightShaftDownSampleFactor", 1.0},
	};
	constexpr int StillCvarCount = static_cast<int>(sizeof(StillCvars) / sizeof(StillCvars[0]));

	// Interactive tier: engine defaults, pinned against a scalability group.
	constexpr FCvarRow InteractiveCvars[] = {
		{"r.VolumetricCloud.ShadowMap", 1.0},
		{"r.VolumetricCloud.SkyAO", 1.0},
		{"r.LightShaftQuality", 1.0},
	};
	constexpr int InteractiveCvarCount =
		static_cast<int>(sizeof(InteractiveCvars) / sizeof(InteractiveCvars[0]));
}
// FLIGHTSIM-SUNSHAFTS-PURE-END

bool FFlightSimSunShafts::ResolveStillTier(const TCHAR* Params)
{
	const FString ParamString = Params != nullptr ? FString(Params) : FString();
	FString Word;
	if (!FParse::Value(*ParamString, TEXT("sun-shafts-tier="), Word))
	{
		Word = FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_SUN_SHAFTS_TIER"));
	}
	Word = Word.TrimStartAndEnd().ToLower();
	if (Word == TEXT("still"))
	{
		TierBasis = TEXT("-sun-shafts-tier=still (or FLIGHTSIM_SUN_SHAFTS_TIER), stated");
		return true;
	}
	if (Word == TEXT("interactive"))
	{
		TierBasis = TEXT("-sun-shafts-tier=interactive (or FLIGHTSIM_SUN_SHAFTS_TIER), stated");
		return false;
	}
	FString Quality;
	FParse::Value(*ParamString, TEXT("quality="), Quality);
	FString Unused;
	const bool bStill = Quality == TEXT("pathtrace")
		|| FParse::Value(*ParamString, TEXT("still-samples="), Unused)
		|| FParse::Value(*ParamString, TEXT("accumulate="), Unused);
	TierBasis = bStill
		? TEXT("derived: the frame accumulates (-still-samples=, -accumulate= or -quality=pathtrace)")
		: TEXT("derived: no accumulation flag, engine defaults for per-frame cost");
	if (!Word.IsEmpty())
	{
		TierBasis += FString::Printf(TEXT("; tier word '%s' is not still or interactive, ignored"), *Word);
	}
	return bStill;
}

void FFlightSimSunShafts::Apply(UWorld* World, FFlightSimVisualScene& Scene, int32 PresetIndex, bool bStill,
                                TSharedPtr<FJsonObject>& Out)
{
	// Function-local: unity builds merge anonymous namespaces.
	using namespace FlightSimSunShaftsPure;
	constexpr double SunShaftsCmPerMetre = 100.0;
	const int P = PresetIndex >= 0 && PresetIndex < PresetCount ? PresetIndex : 0;
	Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("preset"), ANSI_TO_TCHAR(PresetName(P)));
	Out->SetStringField(TEXT("tier"), bStill ? TEXT("still") : TEXT("interactive"));
	Out->SetStringField(TEXT("tier_basis"), TierBasis.IsEmpty() ? TEXT("passed by the caller") : *TierBasis);

	// -- the sun -------------------------------------------------------------
	TSharedPtr<FJsonObject> SunRow = MakeShared<FJsonObject>();
	UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
		? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
	if (SunLight == nullptr)
	{
		SunRow->SetStringField(TEXT("applied"), TEXT("skipped: the scene has no directional sun"));
	}
	else
	{
		const double BloomScale = Value(P, FieldShaftBloomScale);
		SunLight->SetEnableLightShaftOcclusion(true);
		SunLight->SetOcclusionMaskDarkness(static_cast<float>(Value(P, FieldShaftOcclusionDarkness)));
		SunLight->SetOcclusionDepthRange(
			static_cast<float>(Value(P, FieldShaftOcclusionDepthRangeM) * SunShaftsCmPerMetre));
		SunLight->SetEnableLightShaftBloom(BloomScale > 0.0);
		SunLight->SetBloomScale(static_cast<float>(BloomScale));
		SunLight->SetBloomThreshold(static_cast<float>(Value(P, FieldShaftBloomThreshold)));
		SunLight->SetBloomMaxBrightness(static_cast<float>(Value(P, FieldShaftBloomMax)));
		// Setter-less in 5.7.4: written, then the render state re-sent.
		SunLight->CloudShadowOnAtmosphereStrength = static_cast<float>(Value(P, FieldCloudShadowOnAtmosphere));
		SunLight->CloudShadowOnSurfaceStrength = static_cast<float>(Value(P, FieldCloudShadowOnSurface));
		SunLight->CloudShadowExtent = static_cast<float>(Value(P, FieldCloudShadowExtentKm));
		SunLight->CloudShadowMapResolutionScale = static_cast<float>(Value(P, FieldCloudShadowMapResScale));
		SunLight->CloudShadowRaySampleCountScale = static_cast<float>(Value(P, FieldCloudShadowRaySampleScale));
		SunLight->MarkRenderStateDirty();
		SunRow->SetStringField(TEXT("applied"), TEXT("yes"));
		SunRow->SetBoolField(TEXT("light_shaft_occlusion"), true);
		SunRow->SetNumberField(TEXT("occlusion_mask_darkness"), Value(P, FieldShaftOcclusionDarkness));
		SunRow->SetNumberField(TEXT("occlusion_depth_range_m"), Value(P, FieldShaftOcclusionDepthRangeM));
		SunRow->SetBoolField(TEXT("light_shaft_bloom"), BloomScale > 0.0);
		SunRow->SetNumberField(TEXT("bloom_scale"), BloomScale);
		SunRow->SetNumberField(TEXT("bloom_threshold"), Value(P, FieldShaftBloomThreshold));
		SunRow->SetNumberField(TEXT("bloom_max_brightness"), Value(P, FieldShaftBloomMax));
		SunRow->SetNumberField(TEXT("cloud_shadow_on_atmosphere_strength"), Value(P, FieldCloudShadowOnAtmosphere));
		SunRow->SetNumberField(TEXT("cloud_shadow_on_surface_strength"), Value(P, FieldCloudShadowOnSurface));
		SunRow->SetNumberField(TEXT("cloud_shadow_extent_km"), Value(P, FieldCloudShadowExtentKm));
		SunRow->SetNumberField(TEXT("cloud_shadow_map_resolution_scale"), Value(P, FieldCloudShadowMapResScale));
		SunRow->SetNumberField(TEXT("cloud_shadow_ray_sample_count_scale"), Value(P, FieldCloudShadowRaySampleScale));
		// Read, never written: the scene's switches (ApplyAtmosphere sets the
		// atmosphere one; Gate 6's cloud bracket owns the cloud-shadow one).
		SunRow->SetBoolField(TEXT("cast_shadows_on_atmosphere"), SunLight->bCastShadowsOnAtmosphere != 0);
		SunRow->SetBoolField(TEXT("cast_cloud_shadows"), SunLight->bCastCloudShadows != 0);
		if (SunLight->bCastCloudShadows == 0)
		{
			SunRow->SetStringField(TEXT("cloud_shadow_note"),
				TEXT("the sun casts no cloud shadow in this scene: the cloud-shadow strengths are recorded "
				     "but have no effect (the switch is the scene's, not this module's)"));
		}
	}
	Out->SetObjectField(TEXT("sun"), SunRow);

	// -- the sky light -------------------------------------------------------
	TSharedPtr<FJsonObject> SkyRow = MakeShared<FJsonObject>();
	USkyLightComponent* Sky = Scene.SkyLightComponent;
	if (Sky == nullptr)
	{
		SkyRow->SetStringField(TEXT("applied"), TEXT("skipped: the scene has no sky light"));
	}
	else
	{
		const double AoStrength = Value(P, FieldSkyAoStrength);
		Sky->bCloudAmbientOcclusion = AoStrength > 0.0 ? 1 : 0;
		Sky->CloudAmbientOcclusionStrength = static_cast<float>(AoStrength);
		Sky->CloudAmbientOcclusionExtent = static_cast<float>(Value(P, FieldSkyAoExtentKm));
		Sky->CloudAmbientOcclusionMapResolutionScale = static_cast<float>(Value(P, FieldSkyAoMapResScale));
		Sky->CloudAmbientOcclusionApertureScale = static_cast<float>(Value(P, FieldSkyAoApertureScale));
		Sky->MarkRenderStateDirty();
		SkyRow->SetStringField(TEXT("applied"), TEXT("yes"));
		SkyRow->SetBoolField(TEXT("cloud_ambient_occlusion"), AoStrength > 0.0);
		SkyRow->SetNumberField(TEXT("cloud_ambient_occlusion_strength"), AoStrength);
		SkyRow->SetNumberField(TEXT("cloud_ambient_occlusion_extent_km"), Value(P, FieldSkyAoExtentKm));
		SkyRow->SetNumberField(TEXT("cloud_ambient_occlusion_map_resolution_scale"), Value(P, FieldSkyAoMapResScale));
		SkyRow->SetNumberField(TEXT("cloud_ambient_occlusion_aperture_scale"), Value(P, FieldSkyAoApertureScale));
		// The RealTimeReflectionCapture cvars below act only on a real-time
		// sky light (FlightSimVisualScene: on unless -capture-sky-once).
		SkyRow->SetBoolField(TEXT("real_time_capture"), Sky->bRealTimeCapture);
	}
	Out->SetObjectField(TEXT("sky_light"), SkyRow);

	// -- the cvars -----------------------------------------------------------
	TSharedPtr<FJsonObject> CvarRow = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Skipped;
	auto SetSunShaftsCvar = [&](const char* AnsiName, double NewValue)
	{
		const FString Name = ANSI_TO_TCHAR(AnsiName);
		IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(*Name);
		if (Variable == nullptr)
		{
			Skipped.Add(MakeShared<FJsonValueString>(FString::Printf(TEXT("skipped: %s is not registered"), *Name)));
			return;
		}
		const FString Before = Variable->GetString();
		bool bAlreadySaved = false;
		for (const FSavedCvar& Entry : Saved)
		{
			bAlreadySaved |= Entry.Name == Name;
		}
		if (!bAlreadySaved)
		{
			Saved.Add({Name, Before});
		}
		Variable->Set(*FString::SanitizeFloat(NewValue, 0), ECVF_SetByCode);
		TArray<TSharedPtr<FJsonValue>> Pair;
		Pair.Add(MakeShared<FJsonValueString>(Before));
		Pair.Add(MakeShared<FJsonValueString>(Variable->GetString()));
		CvarRow->SetArrayField(Name, Pair);
	};
	if (bStill)
	{
		SetSunShaftsCvar(FogGridPixelCvar, Value(P, FieldVfogGridPx));
		SetSunShaftsCvar(FogGridZCvar, Value(P, FieldVfogGridZ));
		for (int i = 0; i < StillCvarCount; ++i)
		{
			SetSunShaftsCvar(StillCvars[i].Name, StillCvars[i].Value);
		}
	}
	else
	{
		for (int i = 0; i < InteractiveCvarCount; ++i)
		{
			SetSunShaftsCvar(InteractiveCvars[i].Name, InteractiveCvars[i].Value);
		}
	}
	Out->SetObjectField(TEXT("cvars"), CvarRow);
	Out->SetArrayField(TEXT("cvars_skipped"), Skipped);
	Out->SetStringField(TEXT("cvars_dropped"),
		TEXT("LightShaftNumSamples: ECVF_ReadOnly in the 5.7.4 LightShaftRendering.cpp, a runtime set is refused"));
	Out->SetStringField(TEXT("cvars_scope"),
		TEXT("process-wide while the beauty render runs (label captures in the same run share them, but draw "
		     "no fog, atmosphere or cloud and read stencil / depth / normal / base colour); put back at teardown"));

	// -- the show flags (set on the beauty capture by the commandlet) ---------
	{
		TSharedPtr<FJsonObject> Flags = MakeShared<FJsonObject>();
		Flags->SetBoolField(TEXT("light_shafts"), true);
		Flags->SetBoolField(TEXT("volumetric_fog"), true);
		Flags->SetStringField(TEXT("where"),
			TEXT("the beauty capture only (FlightSimRenderCommandlet.cpp beauty block); the label captures' "
			     "flags are untouched; the measured value is render_settings.beauty_show_flags"));
		Out->SetObjectField(TEXT("show_flags"), Flags);
	}

	Out->SetBoolField(TEXT("pixel_moving"), false);
	Out->SetStringField(TEXT("basis"), TEXT("value-only: radiance, no surface moves"));
	Out->SetStringField(TEXT("labels"),
		TEXT("not in PIXEL_MOVING_KEYS; no Gate V bloom-ceiling clause exists (gate_v_visual.py has no bloom "
		     "metric): look_label_check's mask-edge distance covers it, and the probe log asks for a "
		     "label-bytes A/B with the module on and off"));
	Out->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED: every value is set by probe render on the render machine "
		     "(docs/visual/PROBE_LOG.md ## sun-shafts-sky-occlusion; core/scene/sun_shafts.py is the table)"));
	UE_LOG(LogFlightSimSunShafts, Display, TEXT("sun shafts: preset %s, tier %s, sun %s, sky light %s, %d cvar(s)"),
	       ANSI_TO_TCHAR(PresetName(P)), bStill ? TEXT("still") : TEXT("interactive"),
	       SunLight != nullptr ? TEXT("set") : TEXT("absent"), Sky != nullptr ? TEXT("set") : TEXT("absent"),
	       CvarRow->Values.Num());
	(void)World;
}

void FFlightSimSunShafts::Restore()
{
	for (int32 i = Saved.Num() - 1; i >= 0; --i)
	{
		if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(*Saved[i].Name))
		{
			Variable->Set(*Saved[i].Before, ECVF_SetByCode);
		}
	}
	Saved.Reset();
}
