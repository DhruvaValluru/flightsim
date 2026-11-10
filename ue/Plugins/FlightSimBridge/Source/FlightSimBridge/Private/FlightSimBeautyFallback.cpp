#include "FlightSimBeautyFallback.h"

#include "FlightSimRenderCommandlet.h"
#include "FlightSimVisualScene.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyLightComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "HAL/IConsoleManager.h"
#include "Misc/Parse.h"
#include "RHI.h"
#include "RHIFeatureLevel.h"
#include "RHIShaderPlatform.h"
#include "RHIStrings.h"
#include "RenderUtils.h"
#include "SceneManagement.h"

// UNCOMPILED when written: see the header. Every symbol below was read in UE
// 5.7.4: the support queries in RenderCore/Public/RenderUtils.h and
// Engine/Public/SceneManagement.h, GMaxRHIFeatureLevel in
// RHI/Public/RHIFeatureLevel.h, LexToString in RHI/Public/RHIStrings.h, the
// post-process members in Engine/Classes/Engine/Scene.h, the light members in
// Engine/Classes/Components/{LightComponentBase,SkyLightComponent,
// DirectionalLightComponent}.h, and each cvar at its definition.
// scripts/check_bridge_api.sh ("beauty fallback" block) re-checks them.
//
// Every constant is UNCALIBRATED: a starting value chosen by reasoning, set
// by the probe render named beside it (docs/visual/PROBE_LOG.md
// "## no-lumen-fallback"), on the render machine that has no Lumen.

namespace
{
	// Names are per-file unique (unity builds merge anonymous namespaces).

	// SSGI rays (r.SSGI.Quality: 1..4, engine default 4) and SSR quality
	// (r.SSR.Quality 0..4; the post-process ScreenSpaceReflectionQuality
	// 0..100). UNCALIBRATED (probe nl-ssgi: shot b, the canyon's shadow
	// side, at SSGI 2 and 4).
	constexpr float BeautyFallbackSsgiQuality = 4.0f;
	constexpr float BeautyFallbackSsrQuality = 4.0f;
	constexpr float BeautyFallbackSsrPostQuality = 100.0f;

	// Distance-field AO (r.DistanceFieldAO 1; r.AOQuality 2 = high, the
	// engine default, restated). UNCALIBRATED (probe nl-dfao: shot b with
	// and without it).
	constexpr float BeautyFallbackDfaoQuality = 2.0f;

	// The sky light, which is ALL the shadowed side gets without Lumen.
	// Fill: a constant on its intensity, standing in for the multiple bounce
	// Lumen would add off the sunlit ground. Minimum occlusion: the darkest a
	// fully occluded pixel can be under distance-field AO (1 = none), so no
	// shadowed pixel is lit by nothing. UNCALIBRATED (probe nl-fill: shot b
	// shadow-side luma p10 and shot c luma mean against the same shots on the
	// DX12 host with Lumen; the fill is right when they meet).
	constexpr float BeautyFallbackSkyFill = 1.6f;
	constexpr float BeautyFallbackSkyMinOcclusion = 0.2f;

	// Cascaded shadow maps when virtual shadow maps are unavailable. The
	// scene build gives the sun 6 cascades over 20 km (FlightSimVisualScene.cpp);
	// these add cascades, raise the CSM resolution and pack the distribution
	// towards the camera, where the aircraft is. UNCALIBRATED (probe nl-csm:
	// shot a, the aircraft's shadow on itself and the ridge shadow edge).
	constexpr int32 BeautyFallbackCsmCascades = 8;
	constexpr float BeautyFallbackCsmMaxCascades = 10.0f;   // engine cap 10
	constexpr float BeautyFallbackCsmResolution = 4096.0f;  // engine 2048
	constexpr float BeautyFallbackShadowMaxResolution = 4096.0f;
	constexpr float BeautyFallbackCsmDistribution = 4.0f;   // engine 3

	struct FBeautyFallbackState
	{
		bool bApplied = false;
		bool bFallback = false;
		FString Error;
		TSharedPtr<FJsonObject> Record;
		// Round 1 hang (SuspendForSkyCapture): the scene values ApplyScene
		// replaced, and the values held across one sky light capture.
		bool bSkyFilled = false;
		float SkyIntensityBefore = 0.0f;
		float SkyMinOcclusionBefore = 0.0f;
		bool bSunCascaded = false;
		int32 SunCascadesBefore = 0;
		float SunDistributionBefore = 0.0f;
		bool bSuspended = false;
		float SkyIntensityHeld = 0.0f;
		float SkyMinOcclusionHeld = 0.0f;
		int32 SunCascadesHeld = 0;
		float SunDistributionHeld = 0.0f;
	};

	FBeautyFallbackState& BeautyFallbackState()
	{
		static FBeautyFallbackState State;
		return State;
	}

	// Set a renderer cvar at code priority (over the Cinematic scalability
	// level the render-path block applied), recording the value before,
	// what was asked and what reads back.
	void BeautyFallbackCvar(const TCHAR* Name, float Value, TSharedPtr<FJsonObject>& Before,
	                        TSharedPtr<FJsonObject>& Asked, TSharedPtr<FJsonObject>& ReadBack)
	{
		Asked->SetNumberField(Name, Value);
		if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name))
		{
			Before->SetStringField(Name, Variable->GetString());
			Variable->Set(Value, ECVF_SetByCode);
			ReadBack->SetStringField(Name, Variable->GetString());
		}
		else
		{
			ReadBack->SetStringField(Name, TEXT("absent"));
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("beauty fallback: renderer cvar %s not found on this build; recorded absent"), Name);
		}
	}

	FString BeautyFallbackConsole(const TCHAR* Name)
	{
		IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
		return Variable != nullptr ? Variable->GetString() : FString(TEXT("absent"));
	}
}

bool FFlightSimBeautyFallback::TakesFallback(const FString& Mode, bool bLumenGiSupported)
{
	if (Mode == TEXT("force"))
	{
		return true;
	}
	if (Mode == TEXT("off"))
	{
		return false;
	}
	return !bLumenGiSupported;   // auto
}

const FString& FFlightSimBeautyFallback::LastError()
{
	return BeautyFallbackState().Error;
}

TSharedPtr<FJsonObject> FFlightSimBeautyFallback::Record()
{
	return BeautyFallbackState().bApplied ? BeautyFallbackState().Record : nullptr;
}

bool FFlightSimBeautyFallback::ApplyScene(FFlightSimVisualScene& Scene, const TCHAR* CommandLine)
{
	FBeautyFallbackState& State = BeautyFallbackState();
	State.Error.Reset();
	State.bApplied = false;
	State.bFallback = false;
	State.bSkyFilled = false;
	State.bSunCascaded = false;
	State.bSuspended = false;

	FString Mode = TEXT("auto");
	if (CommandLine != nullptr)
	{
		FParse::Value(CommandLine, TEXT("beauty-fallback="), Mode);
	}
	Mode = Mode.ToLower();
	if (Mode != TEXT("auto") && Mode != TEXT("force") && Mode != TEXT("off"))
	{
		// The refusal name is the catalogue's (core/messages/catalog.yaml).
		State.Error = FString::Printf(
			TEXT("render.beauty_fallback_mode: -beauty-fallback=%s is not auto, force or off"), *Mode);
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *State.Error);
		return false;
	}

	// -- what this process can run (the engine's own answers) ---------------
	const EShaderPlatform Platform = GMaxRHIShaderPlatform;
	const bool bLumenGi = DoesPlatformSupportLumenGI(Platform);
	const bool bVsm = DoesPlatformSupportVirtualShadowMaps(Platform);
	const bool bNanite = DoesPlatformSupportNanite(Platform);
	const bool bDistanceFields = DoesPlatformSupportDistanceFields(Platform) && DoesProjectSupportDistanceFields();
	const bool bFallback = TakesFallback(Mode, bLumenGi);

	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("module"), TEXT("FlightSimBeautyFallback.cpp (no-lumen-and-machine lane)"));
	Out->SetStringField(TEXT("mode"), Mode);
	TSharedPtr<FJsonObject> Machine = MakeShared<FJsonObject>();
	Machine->SetStringField(TEXT("rhi"), GDynamicRHI != nullptr ? FString(GDynamicRHI->GetName()) : FString(TEXT("none")));
	Machine->SetStringField(TEXT("feature_level"), LexToString(GMaxRHIFeatureLevel));
	Machine->SetStringField(TEXT("shader_platform"), LexToString(Platform));
	Machine->SetBoolField(TEXT("lumen_gi_supported"), bLumenGi);
	Machine->SetBoolField(TEXT("virtual_shadow_maps_supported"), bVsm);
	Machine->SetBoolField(TEXT("nanite_supported"), bNanite);
	Machine->SetBoolField(TEXT("distance_fields_supported"), bDistanceFields);
	Machine->SetBoolField(TEXT("ray_tracing_enabled"), IsRayTracingEnabled());
	Machine->SetStringField(TEXT("r.Lumen.Supported.SM5"), BeautyFallbackConsole(TEXT("r.Lumen.Supported.SM5")));
	Machine->SetStringField(TEXT("basis"),
		TEXT("DoesPlatformSupportLumenGI / DoesPlatformSupportVirtualShadowMaps / DoesPlatformSupportNanite ")
		TEXT("(RenderUtils.h) and DoesPlatformSupportDistanceFields && DoesProjectSupportDistanceFields ")
		TEXT("(SceneManagement.h) on GMaxRHIShaderPlatform; the cvars reading 1 says nothing about what ran"));
	Out->SetObjectField(TEXT("machine"), Machine);

	TSharedPtr<FJsonObject> Before = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> Asked = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> ReadBack = MakeShared<FJsonObject>();

	if (!bFallback)
	{
		Out->SetStringField(TEXT("path"), bLumenGi ? TEXT("lumen") : TEXT("none (off): Lumen unavailable and no fallback"));
		Out->SetStringField(TEXT("gi"), bLumenGi ? TEXT("Lumen") : TEXT("none: sky light and sun only"));
	}
	else
	{
		Out->SetStringField(TEXT("path"), bLumenGi ? TEXT("fallback (forced; Lumen was available)") : TEXT("fallback"));
		Out->SetStringField(TEXT("gi"), TEXT("SSGI (screen space) plus the sky light"));
		Out->SetStringField(TEXT("gi_note"),
			TEXT("SSGI reads the previous capture's scene colour (ScreenSpaceRayTracing.cpp ")
			TEXT("IsScreenSpaceDiffuseIndirectSupported needs PrevViewInfo), so the first capture of a ")
			TEXT("run has none; a still's accumulation captures and a clip's later frames have it"));
		BeautyFallbackCvar(TEXT("r.SSGI.Quality"), BeautyFallbackSsgiQuality, Before, Asked, ReadBack);
		BeautyFallbackCvar(TEXT("r.SSR.Quality"), BeautyFallbackSsrQuality, Before, Asked, ReadBack);

		// -- distance-field AO: the movable sky light's shadowing ------------
		if (bDistanceFields)
		{
			BeautyFallbackCvar(TEXT("r.DistanceFieldAO"), 1.0f, Before, Asked, ReadBack);
			BeautyFallbackCvar(TEXT("r.AOQuality"), BeautyFallbackDfaoQuality, Before, Asked, ReadBack);
			Out->SetStringField(TEXT("sky_occlusion"), TEXT("distance-field AO"));
		}
		else
		{
			Out->SetStringField(TEXT("sky_occlusion"),
				TEXT("SSGI's screen-space occlusion only: distance fields unsupported on this platform or project"));
		}

		// -- the sky light: filled, never fully occluded ---------------------
		TSharedPtr<FJsonObject> SkyRecord = MakeShared<FJsonObject>();
		if (USkyLightComponent* Sky = Scene.SkyLightComponent)
		{
			const float IntensityBefore = Sky->Intensity;
			State.bSkyFilled = true;
			State.SkyIntensityBefore = IntensityBefore;
			State.SkyMinOcclusionBefore = Sky->MinOcclusion;
			Sky->SetIntensity(IntensityBefore * BeautyFallbackSkyFill);
			Sky->SetMinOcclusion(BeautyFallbackSkyMinOcclusion);
			// Capture-once (a scene capture never runs real-time capture): the
			// commandlet's capture after this call takes these values.
			Sky->SetCaptureIsDirty();
			Sky->MarkRenderStateDirty();
			SkyRecord->SetNumberField(TEXT("intensity_before"), IntensityBefore);
			SkyRecord->SetNumberField(TEXT("min_occlusion_before"), State.SkyMinOcclusionBefore);
			SkyRecord->SetNumberField(TEXT("fill"), BeautyFallbackSkyFill);
			SkyRecord->SetNumberField(TEXT("intensity"), Sky->Intensity);
			SkyRecord->SetNumberField(TEXT("min_occlusion"), Sky->MinOcclusion);
			SkyRecord->SetNumberField(TEXT("occlusion_max_distance_cm"), Sky->OcclusionMaxDistance);
			SkyRecord->SetBoolField(TEXT("cast_shadows"), Sky->CastShadows != 0);
			SkyRecord->SetBoolField(TEXT("real_time_capture"), Sky->IsRealTimeCaptureEnabled());
			SkyRecord->SetStringField(TEXT("recapture"),
				TEXT("marked dirty here; captured by the commandlet before the first frame (per frame when the sun animates)"));
		}
		else
		{
			SkyRecord->SetStringField(TEXT("skipped"), TEXT("the scene has no sky light"));
		}
		Out->SetObjectField(TEXT("sky_light"), SkyRecord);
	}

	// -- shadows: cascaded shadow maps when VSM cannot run ------------------
	// (independent of Lumen: decided on the VSM answer, and only when the
	// fallback is taken or VSM is missing on an auto run).
	TSharedPtr<FJsonObject> ShadowRecord = MakeShared<FJsonObject>();
	const bool bCsm = Mode != TEXT("off") && (!bVsm || Mode == TEXT("force"));
	ShadowRecord->SetStringField(TEXT("method"), bVsm && Mode != TEXT("force")
		? TEXT("virtual shadow maps (hero-lighting lane's quality cvars)")
		: TEXT("cascaded shadow maps"));
	if (bCsm)
	{
		BeautyFallbackCvar(TEXT("r.Shadow.CSM.MaxCascades"), BeautyFallbackCsmMaxCascades, Before, Asked, ReadBack);
		BeautyFallbackCvar(TEXT("r.Shadow.MaxCSMResolution"), BeautyFallbackCsmResolution, Before, Asked, ReadBack);
		BeautyFallbackCvar(TEXT("r.Shadow.MaxResolution"), BeautyFallbackShadowMaxResolution, Before, Asked, ReadBack);
		if (Scene.Sun != nullptr)
		{
			if (UDirectionalLightComponent* SunLight = Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()))
			{
				State.bSunCascaded = true;
				State.SunCascadesBefore = SunLight->DynamicShadowCascades;
				State.SunDistributionBefore = SunLight->CascadeDistributionExponent;
				ShadowRecord->SetNumberField(TEXT("cascades_before"), SunLight->DynamicShadowCascades);
				ShadowRecord->SetNumberField(TEXT("distribution_before"), SunLight->CascadeDistributionExponent);
				SunLight->SetDynamicShadowCascades(BeautyFallbackCsmCascades);
				SunLight->SetCascadeDistributionExponent(BeautyFallbackCsmDistribution);
				ShadowRecord->SetNumberField(TEXT("cascades"), SunLight->DynamicShadowCascades);
				ShadowRecord->SetNumberField(TEXT("distribution_exponent"), SunLight->CascadeDistributionExponent);
				ShadowRecord->SetNumberField(TEXT("distance_movable_cm"), SunLight->DynamicShadowDistanceMovableLight);
			}
		}
		ShadowRecord->SetStringField(TEXT("contact_shadows"),
			TEXT("the hero-lighting lane's (beauty capture show flag and the sun's world-space length)"));
	}
	Out->SetObjectField(TEXT("shadows"), ShadowRecord);
	Out->SetStringField(TEXT("nanite"), bNanite
		? TEXT("supported")
		: TEXT("unsupported: Nanite meshes draw their fallback meshes in every capture (labels too), so labels still match pixels"));

	Out->SetObjectField(TEXT("cvars_before"), Before);
	Out->SetObjectField(TEXT("cvars_asked"), Asked);
	Out->SetObjectField(TEXT("cvars_read_back"), ReadBack);
	Out->SetArrayField(TEXT("pixel_moving_effects"), TArray<TSharedPtr<FJsonValue>>());
	Out->SetStringField(TEXT("labels"),
		TEXT("beauty only: label captures read stencil, depth and GBuffer, which lighting does not change"));
	Out->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED: each constant is set by the probe named in docs/visual/PROBE_LOG.md ")
		TEXT("\"## no-lumen-fallback\""));
	Out->SetStringField(TEXT("capture_post_process"), bFallback
		? TEXT("pending: ApplyCapture sets it on the beauty capture")
		: TEXT("unchanged"));
	State.Record = Out;
	State.bApplied = true;
	State.bFallback = bFallback;
	UE_LOG(LogFlightSimRender, Display, TEXT("beauty fallback: path %s (%s, %s, Lumen GI %s, VSM %s)"),
	       *Out->GetStringField(TEXT("path")), *Machine->GetStringField(TEXT("rhi")),
	       *Machine->GetStringField(TEXT("shader_platform")), bLumenGi ? TEXT("yes") : TEXT("no"),
	       bVsm ? TEXT("yes") : TEXT("no"));
	return true;
}

void FFlightSimBeautyFallback::ApplyCapture(USceneCaptureComponent2D* Beauty)
{
	FBeautyFallbackState& State = BeautyFallbackState();
	if (!State.bApplied || !State.bFallback || Beauty == nullptr || !State.Record.IsValid())
	{
		return;
	}
	// GI and reflections: screen space, per view (the beauty capture only;
	// the project's r.DynamicGlobalIlluminationMethod stays as it is, so a
	// label capture and every measure render are untouched).
	FPostProcessSettings& Settings = Beauty->PostProcessSettings;
	Settings.bOverride_DynamicGlobalIlluminationMethod = true;
	Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::ScreenSpace;
	Settings.bOverride_ReflectionMethod = true;
	Settings.ReflectionMethod = EReflectionMethod::ScreenSpace;
	Settings.bOverride_ScreenSpaceReflectionQuality = true;
	Settings.ScreenSpaceReflectionQuality = BeautyFallbackSsrPostQuality;
	TSharedPtr<FJsonObject> PostRecord = MakeShared<FJsonObject>();
	PostRecord->SetStringField(TEXT("DynamicGlobalIlluminationMethod"), TEXT("ScreenSpace"));
	PostRecord->SetStringField(TEXT("ReflectionMethod"), TEXT("ScreenSpace"));
	PostRecord->SetNumberField(TEXT("ScreenSpaceReflectionQuality"), Settings.ScreenSpaceReflectionQuality);
	State.Record->SetObjectField(TEXT("capture_post_process"), PostRecord);
}

// -- round 1 hang (2026-11-09): ef361bd6's scene state for the sky capture ----
// The constrained GPU (FFlightSimWorldBeauty::ConstrainedGpu) deadlocked in
// the sky light capture. ef361bd6 rendered every shot on that laptop, so for
// the one capture the scene is given back what ef361bd6 had there: the sun's
// cascade count and distribution and the sky light's intensity and minimum
// occlusion as the scene built them. The renderer cvars are NOT touched: the
// fallback asks the same values the Cinematic scalability level (applied after
// ApplyScene, at a lower priority) gives, which ef361bd6 also ran
// (BaseScalability.ini ShadowQuality@Cine, GlobalIlluminationQuality@Cine,
// ReflectionQuality@Cine, EffectsQuality@Cine), so they are ef361bd6's already;
// the record reads each back to show it. The per-view half (ApplyCapture) is the
// beauty capture's only and the cube capture never reads it.
TSharedPtr<FJsonObject> FFlightSimBeautyFallback::SuspendForSkyCapture(FFlightSimVisualScene& Scene)
{
	FBeautyFallbackState& State = BeautyFallbackState();
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	if (!State.bApplied || State.bSuspended)
	{
		Out->SetStringField(TEXT("applied"), State.bSuspended
			? TEXT("nothing: already suspended")
			: TEXT("nothing: the fallback never ran"));
		return Out;
	}
	State.bSuspended = true;
	TArray<TSharedPtr<FJsonValue>> Restored;
	auto Row = [&Restored](const TCHAR* What, double Held, double Capture)
	{
		TSharedPtr<FJsonObject> R = MakeShared<FJsonObject>();
		R->SetStringField(TEXT("what"), What);
		R->SetNumberField(TEXT("frames"), Held);
		R->SetNumberField(TEXT("sky_capture"), Capture);
		Restored.Add(MakeShared<FJsonValueObject>(R));
	};
	if (State.bSkyFilled && Scene.SkyLightComponent != nullptr)
	{
		USkyLightComponent* Sky = Scene.SkyLightComponent;
		State.SkyIntensityHeld = Sky->Intensity;
		State.SkyMinOcclusionHeld = Sky->MinOcclusion;
		Sky->SetIntensity(State.SkyIntensityBefore);
		Sky->SetMinOcclusion(State.SkyMinOcclusionBefore);
		Row(TEXT("sky_light.intensity"), State.SkyIntensityHeld, State.SkyIntensityBefore);
		Row(TEXT("sky_light.min_occlusion"), State.SkyMinOcclusionHeld, State.SkyMinOcclusionBefore);
	}
	UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
		? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
	if (State.bSunCascaded && SunLight != nullptr)
	{
		State.SunCascadesHeld = SunLight->DynamicShadowCascades;
		State.SunDistributionHeld = SunLight->CascadeDistributionExponent;
		SunLight->SetDynamicShadowCascades(State.SunCascadesBefore);
		SunLight->SetCascadeDistributionExponent(State.SunDistributionBefore);
		Row(TEXT("sun.dynamic_shadow_cascades"), State.SunCascadesHeld, State.SunCascadesBefore);
		Row(TEXT("sun.cascade_distribution_exponent"), State.SunDistributionHeld, State.SunDistributionBefore);
	}
	Out->SetArrayField(TEXT("restored"), Restored);
	TSharedPtr<FJsonObject> Cvars = MakeShared<FJsonObject>();
	const TSharedPtr<FJsonObject>* Asked = nullptr;
	if (State.Record.IsValid() && State.Record->TryGetObjectField(TEXT("cvars_asked"), Asked) && Asked != nullptr)
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*Asked)->Values)
		{
			Cvars->SetStringField(Entry.Key, BeautyFallbackConsole(*Entry.Key));
		}
	}
	Out->SetObjectField(TEXT("cvars_at_capture"), Cvars);
	Out->SetStringField(TEXT("cvars_basis"),
		TEXT("kept: each equals the Cinematic scalability level's value (BaseScalability.ini @Cine), which ef361bd6 ran too"));
	Out->SetStringField(TEXT("per_view"), TEXT("the beauty capture's SSGI and SSR only; the cube capture never reads them"));
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("beauty fallback: sky capture takes the scene's own sky light and sun cascades (%d value(s) held)"),
	       Restored.Num());
	return Out;
}

void FFlightSimBeautyFallback::ResumeAfterSkyCapture(FFlightSimVisualScene& Scene)
{
	FBeautyFallbackState& State = BeautyFallbackState();
	if (!State.bSuspended)
	{
		return;
	}
	State.bSuspended = false;
	if (State.bSkyFilled && Scene.SkyLightComponent != nullptr)
	{
		Scene.SkyLightComponent->SetIntensity(State.SkyIntensityHeld);
		Scene.SkyLightComponent->SetMinOcclusion(State.SkyMinOcclusionHeld);
	}
	UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
		? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
	if (State.bSunCascaded && SunLight != nullptr)
	{
		SunLight->SetDynamicShadowCascades(State.SunCascadesHeld);
		SunLight->SetCascadeDistributionExponent(State.SunDistributionHeld);
	}
}
