#include "FlightSimHeroLighting.h"

#include "FlightSimRenderCommandlet.h"
#include "FlightSimVisualScene.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "HAL/IConsoleManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "RenderUtils.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

// UNCOMPILED when written: see the header. Every member and setter below was
// read in UE 5.7.4's Classes/Components/{LightComponent,LightComponentBase,
// DirectionalLightComponent,SkyLightComponent,SkyAtmosphereComponent}.h, every
// cvar name at its definition in Renderer/Private (or Core's ConsoleManager.cpp
// for r.ContactShadows), and the show flags in
// Public/ShowFlagsValues.inl. scripts/check_bridge_api.sh re-checks them.
//
// Every constant here is UNCALIBRATED unless it says physics: a starting
// value chosen by reasoning, set by the probe render named beside it
// (docs/visual/PROBE_LOG.md "## hero-lighting").

namespace
{
	// Names are per-file unique (unity builds merge anonymous namespaces).
	constexpr int32 HeroLightingSidecarVersion = 1;

	// PHYSICS: the sun's mean angular diameter seen from Earth (2 x
	// atan(696,000 km / 1 AU) = 0.533 deg; UE's own default, 0.5357, is the
	// same disc). LightSourceAngle is a DIAMETER in UE.
	constexpr float HeroLightingSunDiscAngleDeg = 0.5357f;
	// UNCALIBRATED (probe hl-penumbra: golden-hour shot a, the fin's shadow
	// on the fuselage at 1080p vs a reference photo's penumbra width): the
	// circumsolar aureole's share of the penumbra.
	constexpr float HeroLightingSunSoftAngleDeg = 0.5f;
	// A clear-sky sun cannot be wider than this; a stated -sun-source-angle=
	// above it is the overcast/rain softening, and the disc is then hidden.
	// UNCALIBRATED (probe hl-overcast: shot c, sun disc visible through the
	// storm deck or not).
	constexpr double HeroLightingOvercastAngleDeg = 2.0;

	// VSM. UNCALIBRATED (probe hl-vsm: shot b at 1080p, canyon-rim shadow
	// edge aliasing vs the page-pool overflow warning in the log).
	constexpr float HeroLightingVsmLodBiasDirectional = -1.5f;   // engine 0
	constexpr float HeroLightingVsmMaxPhysicalPages = 8192.0f;   // engine 2048
	constexpr float HeroLightingSmrtRayCountDirectional = 16.0f; // engine 7
	constexpr float HeroLightingSmrtSamplesPerRay = 12.0f;       // engine 8

	// Contact shadows in WORLD units, short enough that only airframe-scale
	// detail is affected. UNCALIBRATED (probe hl-contact: shot d, canopy
	// frame and coaming; shot a, pylons and intakes; no halo on the tiles).
	constexpr float HeroLightingContactShadowLengthCm = 150.0f;

	// Lumen. UNCALIBRATED (probe hl-lumen: shot a/d canopy and airframe
	// reflection noise and cost, RT on vs off on the Windows box).
	constexpr float HeroLightingReflectionMaxRoughness = 0.4f;
	constexpr float HeroLightingReflectionDownsample = 1.0f;
	// r.Lumen.HardwareRayTracing.LightingMode 2: hit lighting for
	// reflections only (the cvar's own help text, LumenHardwareRayTracingCommon.cpp).
	constexpr float HeroLightingHitLightingReflectionsOnly = 2.0f;

	// Light shafts. UNCALIBRATED (probe hl-shafts: shot a into the low sun
	// through the Matterhorn's ridge; no bloom haze across the frame).
	constexpr float HeroLightingShaftOcclusionDarkness = 0.4f;
	constexpr float HeroLightingShaftBloomScale = 0.12f;
	constexpr float HeroLightingShaftBloomThreshold = 6.0f;
	constexpr float HeroLightingShaftBloomMaxBrightness = 50.0f;
	// PHYSICS default: the sun's in-scattering into volumetric fog at 1.
	constexpr float HeroLightingFogScattering = 1.0f;
	// UNCALIBRATED (probe hl-fog: shot c, shaft banding in the rain fog).
	constexpr float HeroLightingFogGridPixelSize = 4.0f;          // engine 8
	constexpr float HeroLightingFogGridSizeZ = 128.0f;            // engine 64

	// Sky light. UNCALIBRATED (probe hl-skylight: shot c airframe belly
	// under the storm deck; shot b belly over the red rock).
	constexpr float HeroLightingCloudAoStrength = 1.0f;
	// PHYSICS: the sun disc at its true luminance (outer-space illuminance
	// over the disc's solid angle, SkyAtmosphereRendering.cpp).
	constexpr float HeroLightingSunDiskScale = 1.0f;

	struct FHeroLightingState
	{
		bool bApplied = false;
		FString Error;
		TSharedPtr<FJsonObject> Record;
	};

	FHeroLightingState& HeroLightingState()
	{
		static FHeroLightingState State;
		return State;
	}

	bool HeroLightingFail(const FString& Message)
	{
		// The refusal name is the catalogue's (core/messages/catalog.yaml).
		HeroLightingState().Error = FString::Printf(TEXT("hero_lighting.sidecar: %s"), *Message);
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *HeroLightingState().Error);
		return false;
	}

	// Set a renderer cvar at code priority (over the Cinematic scalability
	// level render-path applied), recording what was asked and read back.
	void HeroLightingCvar(const TCHAR* Name, float Value, TSharedPtr<FJsonObject>& Asked,
	                      TSharedPtr<FJsonObject>& ReadBack)
	{
		Asked->SetNumberField(Name, Value);
		if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name))
		{
			Variable->Set(Value, ECVF_SetByCode);
			ReadBack->SetStringField(Name, Variable->GetString());
		}
		else
		{
			ReadBack->SetStringField(Name, TEXT("absent"));
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("hero lighting: renderer cvar %s not found on this build; recorded absent"), Name);
		}
	}

	bool HeroLightingReadRgb(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, FLinearColor& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object.IsValid() || !Object->TryGetArrayField(Key, Values) || Values == nullptr ||
		    Values->Num() != 3)
		{
			return HeroLightingFail(FString::Printf(TEXT("'%s' is not three numbers"), Key));
		}
		double V[3] = {0.0, 0.0, 0.0};
		for (int32 Index = 0; Index < 3; ++Index)
		{
			if (!(*Values)[Index].IsValid() || !(*Values)[Index]->TryGetNumber(V[Index]) ||
			    !FMath::IsFinite(V[Index]) || V[Index] < 0.0)
			{
				return HeroLightingFail(FString::Printf(
					TEXT("'%s'[%d] is not a non-negative number"), Key, Index));
			}
		}
		Out = FLinearColor(static_cast<float>(V[0]), static_cast<float>(V[1]),
		                   static_cast<float>(V[2]), 1.0f);
		return true;
	}

	TSharedPtr<FJsonObject> HeroLightingColorJson(const FLinearColor& Color)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("r"), Color.R);
		Out->SetNumberField(TEXT("g"), Color.G);
		Out->SetNumberField(TEXT("b"), Color.B);
		Out->SetNumberField(TEXT("a"), Color.A);
		return Out;
	}
}

bool FFlightSimHeroLighting::IsOvercastSourceAngle(double SourceAngleDeg)
{
	return SourceAngleDeg > HeroLightingOvercastAngleDeg;
}

const FString& FFlightSimHeroLighting::LastError()
{
	return HeroLightingState().Error;
}

TSharedPtr<FJsonObject> FFlightSimHeroLighting::Record()
{
	return HeroLightingState().bApplied ? HeroLightingState().Record : nullptr;
}

void FFlightSimHeroLighting::ExcludeFromLabel(USceneCaptureComponent2D* Label)
{
	// Before Apply (every measure render) this does nothing at all.
	if (!HeroLightingState().bApplied || Label == nullptr)
	{
		return;
	}
	Label->ShowFlags.SetLightShafts(false);
	Label->ShowFlags.SetContactShadows(false);
}

bool FFlightSimHeroLighting::Apply(FFlightSimVisualScene& Scene, USceneCaptureComponent2D* Beauty,
                                   bool bPathTrace, const TCHAR* CommandLine)
{
	FHeroLightingState& State = HeroLightingState();
	State.Error.Reset();
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> Asked = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> ReadBack = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("module"), TEXT("FlightSimHeroLighting.cpp (hero-lighting lane)"));
	Out->SetStringField(TEXT("direction"),
		TEXT("the sun's direction is the scenario's time of day, date and heading (core/scene/")
		TEXT("hero_lighting.py solves them per shot); nothing here adds or moves a light"));

	// -- the sidecar (optional): the ground's radiance and the run's basis ---
	FString SidecarPath;
	TSharedPtr<FJsonObject> Plan;
	if (CommandLine != nullptr && FParse::Value(CommandLine, TEXT("hero-lighting="), SidecarPath) &&
	    !SidecarPath.IsEmpty())
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *SidecarPath))
		{
			return HeroLightingFail(FString::Printf(TEXT("cannot read the sidecar %s"), *SidecarPath));
		}
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Plan) || !Plan.IsValid())
		{
			return HeroLightingFail(FString::Printf(TEXT("the sidecar %s is not a JSON object"), *SidecarPath));
		}
		int32 Version = 0;
		if (!Plan->TryGetNumberField(TEXT("hero_lighting_version"), Version) ||
		    Version != HeroLightingSidecarVersion)
		{
			return HeroLightingFail(FString::Printf(
				TEXT("the sidecar %s is not hero_lighting_version %d"), *SidecarPath,
				HeroLightingSidecarVersion));
		}
		Out->SetStringField(TEXT("sidecar"), SidecarPath);
		Out->SetObjectField(TEXT("plan"), Plan);
	}

	// -- the sun -------------------------------------------------------------
	UDirectionalLightComponent* SunLight = Scene.Sun != nullptr
		? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : nullptr;
	TSharedPtr<FJsonObject> SunRecord = MakeShared<FJsonObject>();
	if (SunLight != nullptr)
	{
		double StatedAngle = -1.0;
		const bool bStatedAngle = CommandLine != nullptr &&
			FParse::Value(CommandLine, TEXT("sun-source-angle="), StatedAngle) && StatedAngle >= 0.0;
		if (!bStatedAngle)
		{
			SunLight->SetLightSourceAngle(HeroLightingSunDiscAngleDeg);
			SunLight->SetLightSourceSoftAngle(HeroLightingSunSoftAngleDeg);
			SunRecord->SetStringField(TEXT("source_angle_basis"),
				TEXT("the true solar disc (physics) plus an UNCALIBRATED soft angle"));
		}
		else
		{
			SunRecord->SetStringField(TEXT("source_angle_basis"),
				TEXT("kept: the run stated -sun-source-angle= (the lighting block / rain look)"));
		}
		const bool bOvercast = IsOvercastSourceAngle(SunLight->LightSourceAngle);
		SunRecord->SetNumberField(TEXT("source_angle_deg"), SunLight->LightSourceAngle);
		SunRecord->SetNumberField(TEXT("source_soft_angle_deg"), SunLight->LightSourceSoftAngle);
		SunRecord->SetBoolField(TEXT("overcast"), bOvercast);

		// Contact shadows, world space, airframe scale.
		SunLight->ContactShadowLength = HeroLightingContactShadowLengthCm;
		SunLight->ContactShadowLengthInWS = true;
		SunLight->ContactShadowCastingIntensity = 1.0f;
		SunLight->ContactShadowNonCastingIntensity = 0.0f;
		SunRecord->SetNumberField(TEXT("contact_shadow_length_cm_world"), SunLight->ContactShadowLength);

		// Light shafts: bloom (the shafts themselves) only. Round 2
		// (exposure-storm, 2026-11-09): the SCREEN-SPACE occlusion is off.
		// Its mask is the frame's own depth, blurred radially toward the
		// sun's projected position (5.7.4 LightShaftRendering.cpp, run
		// whenever the sun is in front of the camera, W > 0), and it darkens
		// the height fog's in-scatter, which covers the horizon sky
		// (FogRendering.cpp OcclusionTexture). When the aircraft banks, the
		// terrain swings through that mask and the sky band's brightness
		// moves with it: Gate 6 beauty's "exposure does not breathe" went
		// from 5.87 to 12.51/255 when this lane turned it on for every beauty
		// render. The shafts behind a ridge stay, from world-space shadows
		// that do not depend on what is on screen: the volumetric fog's
		// volumetric shadow (below) and the atmosphere's shadowing. This
		// call runs after the world lane's sun-shafts row, so it is the
		// owner of record for occlusion; that row's darkness is inert.
		SunLight->SetEnableLightShaftOcclusion(false);
		SunLight->SetOcclusionMaskDarkness(HeroLightingShaftOcclusionDarkness);
		SunLight->SetEnableLightShaftBloom(!bOvercast);
		SunLight->SetBloomScale(HeroLightingShaftBloomScale);
		SunLight->SetBloomThreshold(HeroLightingShaftBloomThreshold);
		SunLight->SetBloomMaxBrightness(HeroLightingShaftBloomMaxBrightness);
		SunRecord->SetBoolField(TEXT("light_shaft_occlusion"), false);
		SunRecord->SetStringField(TEXT("light_shaft_occlusion_basis"),
			TEXT("off: screen-space, so it re-tones the horizon sky as the bank moves the terrain on ")
			TEXT("screen (Gate 6 beauty breathing); overrides the world lane's sun-shafts row; shafts ")
			TEXT("come from the volumetric fog's and the atmosphere's world-space shadows"));
		SunRecord->SetBoolField(TEXT("light_shaft_bloom"), !bOvercast);
		SunRecord->SetNumberField(TEXT("light_shaft_bloom_scale"), HeroLightingShaftBloomScale);
		SunRecord->SetNumberField(TEXT("light_shaft_bloom_threshold"), HeroLightingShaftBloomThreshold);

		// Volumetric fog shafts from the sun.
		SunLight->SetVolumetricScatteringIntensity(HeroLightingFogScattering);
		SunLight->SetCastVolumetricShadow(true);
		SunRecord->SetNumberField(TEXT("volumetric_scattering_intensity"), HeroLightingFogScattering);

		// The sun disc: physical luminance, or hidden behind overcast (a
		// 25 deg "disc" drawn through a storm deck is not a sun anyone sees).
		const float DiskScale = bOvercast ? 0.0f : HeroLightingSunDiskScale;
		SunLight->SetAtmosphereSunDiskColorScale(FLinearColor(DiskScale, DiskScale, DiskScale, 1.0f));
		SunRecord->SetNumberField(TEXT("sun_disk_color_scale"), DiskScale);
		SunLight->MarkRenderStateDirty();
	}
	else
	{
		SunRecord->SetStringField(TEXT("skipped"), TEXT("the scene has no directional sun"));
	}
	Out->SetObjectField(TEXT("sun"), SunRecord);

	// -- the aureole: the world lane's Mie lobe, read back --------------------
	if (Scene.Atmosphere != nullptr)
	{
		TSharedPtr<FJsonObject> Aureole = MakeShared<FJsonObject>();
		Aureole->SetNumberField(TEXT("mie_anisotropy"), Scene.Atmosphere->MieAnisotropy);
		Aureole->SetStringField(TEXT("owner"), TEXT("world lane (FlightSimClouds.cpp); read back, not set"));
		Out->SetObjectField(TEXT("aureole"), Aureole);
	}

	// -- the sky light -------------------------------------------------------
	TSharedPtr<FJsonObject> SkyRecord = MakeShared<FJsonObject>();
	if (USkyLightComponent* Sky = Scene.SkyLightComponent)
	{
		// NOT real-time capture: a scene capture never runs it (FScene::
		// AllocateAndCaptureFrameSkyEnvMap returns for bIsSceneCapture) and
		// UpdateSkyCaptureContents skips a real-time sky light, so turning it
		// on would light every beauty frame's shadows with nothing (5.7.4,
		// docs/VALIDITY.md: 1.8/255 vs 172). The commandlet's capture-once
		// (after this runs) picks up the settings below.
		Sky->bCloudAmbientOcclusion = true;
		Sky->CloudAmbientOcclusionStrength = HeroLightingCloudAoStrength;
		SkyRecord->SetBoolField(TEXT("real_time_capture"), Sky->IsRealTimeCaptureEnabled());
		SkyRecord->SetStringField(TEXT("capture"),
			TEXT("captured once by the commandlet before the first frame (and per frame when the sun animates)"));
		SkyRecord->SetBoolField(TEXT("cloud_ambient_occlusion"), true);
		FLinearColor Lower = FLinearColor::Black;
		const TSharedPtr<FJsonObject>* Ground = nullptr;
		if (Plan.IsValid() && Plan->TryGetObjectField(TEXT("ground"), Ground) && Ground != nullptr)
		{
			if (!HeroLightingReadRgb(*Ground, TEXT("lower_hemisphere_luminance_rgb"), Lower))
			{
				return false;
			}
			// The capture replaces the lower hemisphere with this colour (alpha 1:
			// a full lerp in ReflectionEnvironmentShaders.usf's copy to the cube face).
			Sky->bLowerHemisphereIsBlack = true;
			Sky->SetLowerHemisphereColor(Lower);
			SkyRecord->SetStringField(TEXT("lower_hemisphere_basis"),
				TEXT("ground albedo x horizontal illuminance / pi, from the sidecar"));
		}
		else
		{
			SkyRecord->SetStringField(TEXT("lower_hemisphere_basis"),
				TEXT("unchanged: no -hero-lighting= sidecar named a ground"));
		}
		SkyRecord->SetObjectField(TEXT("lower_hemisphere_color"), HeroLightingColorJson(Sky->LowerHemisphereColor));
		// Round 3 (core/scene/hero_lighting.py stated_fill_tint): a fill the
		// lighting block STATES (super bright's x1.35) is lit as a fill, not as
		// more of the captured blue sky. Only the COLOUR is set here (peak 1: the
		// light's 8-bit colour); this lane never changes an intensity. The factor
		// that keeps the fill's luminance rides the lighting block's own
		// -sky-light-scale= (webapp.runs _render folds it in), so the scene's
		// knob, the no-Lumen fallback's x1.6 and it multiply as one product.
		// Absent: the sky light's colour is untouched.
		// Round 4: the colour is the model sky's moved ALL the way to grey
		// (STATED_FILL_NEUTRAL_SHARE 1, a neutral fill), already 8-bit exact
		// (hero_lighting.srgb8_stored), and the ground's lower-hemisphere
		// luminance above arrives divided by this colour and intensity_scale
		// (hero_lighting.plan_sidecar), because the light's colour multiplies
		// both hemispheres of the capture: the drawn ground stays albedo x E / pi.
		const TSharedPtr<FJsonObject>* SkyFill = nullptr;
		if (Plan.IsValid() && Plan->TryGetObjectField(TEXT("sky_light"), SkyFill) && SkyFill != nullptr)
		{
			FLinearColor FillColor = FLinearColor::White;
			double FillScale = 0.0;
			if (!HeroLightingReadRgb(*SkyFill, TEXT("color_linear_rgb"), FillColor))
			{
				return false;
			}
			if (!(*SkyFill)->TryGetNumberField(TEXT("intensity_scale"), FillScale) ||
			    !FMath::IsFinite(FillScale) || FillScale <= 0.0 ||
			    FillColor.R > 1.0f || FillColor.G > 1.0f || FillColor.B > 1.0f)
			{
				return HeroLightingFail(TEXT("sky_light: color_linear_rgb must lie in [0, 1] and ")
				                        TEXT("intensity_scale must be a positive number"));
			}
			// USkyLightComponent::SetLightColor stores FColor(ToFColor(true)): sRGB 8-bit.
			Sky->SetLightColor(FillColor);
			TSharedPtr<FJsonObject> FillRecord = MakeShared<FJsonObject>();
			FillRecord->SetObjectField(TEXT("color_linear"), HeroLightingColorJson(FillColor));
			FillRecord->SetNumberField(TEXT("intensity_scale"), FillScale);
			FillRecord->SetStringField(TEXT("intensity_scale_applied_by"),
				TEXT("-sky-light-scale= (webapp.runs _render multiplies the lighting block's fill by it)"));
			FillRecord->SetNumberField(TEXT("intensity"), Sky->Intensity);
			FillRecord->SetStringField(TEXT("basis"),
				TEXT("a stated sky fill lit as a neutral fill: the model sky's blue moved to grey, ")
				TEXT("its luminance kept, the ground hemisphere compensated ")
				TEXT("(core/scene/hero_lighting.py stated_fill_tint, plan_sidecar; UNCALIBRATED)"));
			SkyRecord->SetObjectField(TEXT("stated_fill"), FillRecord);
		}
		Sky->SetCaptureIsDirty();
		Sky->MarkRenderStateDirty();
	}
	else
	{
		SkyRecord->SetStringField(TEXT("skipped"), TEXT("the scene has no sky light"));
	}
	Out->SetObjectField(TEXT("sky_light"), SkyRecord);

	// -- renderer cvars (this process only; a commandlet run is one render) --
	HeroLightingCvar(TEXT("r.Shadow.Virtual.ResolutionLodBiasDirectional"), HeroLightingVsmLodBiasDirectional, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Shadow.Virtual.MaxPhysicalPages"), HeroLightingVsmMaxPhysicalPages, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Shadow.Virtual.SMRT.RayCountDirectional"), HeroLightingSmrtRayCountDirectional, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Shadow.Virtual.SMRT.SamplesPerRayDirectional"), HeroLightingSmrtSamplesPerRay, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.ContactShadows"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.LightShaftQuality"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.VolumetricFog"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.VolumetricFog.GridPixelSize"), HeroLightingFogGridPixelSize, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.VolumetricFog.GridSizeZ"), HeroLightingFogGridSizeZ, Asked, ReadBack);
	// Lumen final gather: render-path owns LumenFinalGatherQuality (the
	// capture's post-process override); these add the full-resolution AO
	// and the screen traces in front of the probes.
	HeroLightingCvar(TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Lumen.ScreenProbeGather.ScreenTraces"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Lumen.Reflections.ScreenTraces"), 1.0f, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Lumen.Reflections.MaxRoughnessToTrace"), HeroLightingReflectionMaxRoughness, Asked, ReadBack);
	HeroLightingCvar(TEXT("r.Lumen.Reflections.DownsampleFactor"), HeroLightingReflectionDownsample, Asked, ReadBack);
	const bool bRayTracing = IsRayTracingEnabled();
	TSharedPtr<FJsonObject> Reflections = MakeShared<FJsonObject>();
	if (bRayTracing)
	{
		// Hit lighting on the airframe and canopy: the full material and
		// shadowed lighting at every reflection hit.
		HeroLightingCvar(TEXT("r.Lumen.HardwareRayTracing"), 1.0f, Asked, ReadBack);
		HeroLightingCvar(TEXT("r.Lumen.Reflections.HardwareRayTracing"), 1.0f, Asked, ReadBack);
		HeroLightingCvar(TEXT("r.Lumen.HardwareRayTracing.LightingMode"), HeroLightingHitLightingReflectionsOnly, Asked, ReadBack);
		HeroLightingCvar(TEXT("r.Lumen.ScreenProbeGather.ShortRangeAO.HardwareRayTracing"), 1.0f, Asked, ReadBack);
		Reflections->SetStringField(TEXT("route"), TEXT("hardware ray tracing with hit lighting (LightingMode 2)"));
	}
	else
	{
		Reflections->SetStringField(TEXT("route"),
			TEXT("software fallback: ray tracing is not enabled in this process; screen traces then ")
			TEXT("the surface cache"));
	}
	Reflections->SetBoolField(TEXT("ray_tracing_enabled"), bRayTracing);
	Out->SetObjectField(TEXT("reflections"), Reflections);

	if (Beauty != nullptr)
	{
		Beauty->ShowFlags.SetLightShafts(true);
		Beauty->ShowFlags.SetContactShadows(true);
	}
	Out->SetBoolField(TEXT("path_tracer"), bPathTrace);
	if (bPathTrace)
	{
		Out->SetStringField(TEXT("path_tracer_note"),
			TEXT("the path tracer uses the sun's source angle and the sky light; the raster-only ")
			TEXT("cvars above (VSM, contact shadows, Lumen, light shafts) do not reach its pixels"));
	}
	Out->SetObjectField(TEXT("cvars_asked"), Asked);
	Out->SetObjectField(TEXT("cvars_read_back"), ReadBack);
	Out->SetArrayField(TEXT("pixel_moving_effects"), TArray<TSharedPtr<FJsonValue>>());
	Out->SetStringField(TEXT("labels"),
		TEXT("beauty only: label captures read stencil, depth, GBuffer and velocity, which lighting ")
		TEXT("does not change, and ExcludeFromLabel turns light shafts and contact shadows off on them"));
	Out->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED except the solar disc and the unit scales: each value is set by the probe ")
		TEXT("named in docs/visual/PROBE_LOG.md \"## hero-lighting\""));
	State.Record = Out;
	State.bApplied = true;
	return true;
}
