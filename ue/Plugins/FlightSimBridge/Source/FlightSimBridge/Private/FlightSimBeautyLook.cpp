#include "FlightSimBeautyLook.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "Engine/EngineTypes.h"
#include "Engine/Scene.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

// UNCOMPILED when written: see the header. Every FPostProcessSettings member
// set below was read in UE 5.7.4's Engine/Classes/Engine/Scene.h (with its
// bOverride_ twin), every show flag in Public/ShowFlagsValues.inl, and the
// light members in Classes/Components/{LightComponent,LightComponentBase,
// DirectionalLightComponent}.h; scripts/check_bridge_api.sh re-checks them.

namespace
{
	// Names are per-file unique (NEXT.md gotcha 3: unity builds merge
	// anonymous namespaces across files).
	constexpr int32 BeautyLookSupportedVersion = 1;
	constexpr double BeautyLookCmPerMetre = 100.0;

	struct FBeautyLookState
	{
		bool bApplied = false;
		FString Error;
		TSharedPtr<FJsonObject> Plan;      // the sidecar as read
		TSharedPtr<FJsonObject> Applied;   // what was set / read back
		FString SidecarPath;
		bool bDepthOfField = false;
		double SensorWidthMm = 36.0;
		bool bExposureApplied = false;
		double Ev100 = 0.0;
		FString ExposureSource;
		int32 Frames = 0;
		double FocusMinM = TNumericLimits<double>::Max();
		double FocusMaxM = 0.0;
		double FocalMinMm = TNumericLimits<double>::Max();
		double FocalMaxMm = 0.0;
	};

	FBeautyLookState& BeautyLookState()
	{
		static FBeautyLookState State;
		return State;
	}

	bool BeautyLookFail(const FString& Message)
	{
		// The refusal name is the catalogue's (core/messages/catalog.yaml).
		BeautyLookState().Error = FString::Printf(TEXT("render.beauty_look: %s"), *Message);
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *BeautyLookState().Error);
		return false;
	}

	bool BeautyLookNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out)
	{
		if (!Object.IsValid() || !Object->TryGetNumberField(Key, Out))
		{
			return BeautyLookFail(FString::Printf(TEXT("the sidecar has no number '%s'"), Key));
		}
		return true;
	}

	bool BeautyLookVector4(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, FVector4& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object.IsValid() || !Object->TryGetArrayField(Key, Values) || Values == nullptr ||
		    Values->Num() != 4)
		{
			return BeautyLookFail(FString::Printf(TEXT("'%s' is not four numbers"), Key));
		}
		double V[4] = {0.0, 0.0, 0.0, 0.0};
		for (int32 Index = 0; Index < 4; ++Index)
		{
			if (!(*Values)[Index].IsValid() || !(*Values)[Index]->TryGetNumber(V[Index]))
			{
				return BeautyLookFail(FString::Printf(TEXT("'%s'[%d] is not a number"), Key, Index));
			}
		}
		Out = FVector4(V[0], V[1], V[2], V[3]);
		return true;
	}

	bool BeautyLookObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key,
	                      TSharedPtr<FJsonObject>& Out)
	{
		const TSharedPtr<FJsonObject>* Found = nullptr;
		if (!Object.IsValid() || !Object->TryGetObjectField(Key, Found) || Found == nullptr ||
		    !Found->IsValid())
		{
			return BeautyLookFail(FString::Printf(TEXT("the sidecar has no object '%s'"), Key));
		}
		Out = *Found;
		return true;
	}

	TSharedPtr<FJsonValue> BeautyLookVectorJson(const FVector4& V)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		Values.Add(MakeShared<FJsonValueNumber>(V.X));
		Values.Add(MakeShared<FJsonValueNumber>(V.Y));
		Values.Add(MakeShared<FJsonValueNumber>(V.Z));
		Values.Add(MakeShared<FJsonValueNumber>(V.W));
		return MakeShared<FJsonValueArray>(Values);
	}

	// The scene's atmosphere sun (index 0): the light the beauty sun colour
	// applies to. Found through the capture's world because the capture is
	// the only thing ApplyBeautyPostProcess is handed (its signature is the
	// V0 one, unchanged).
	UDirectionalLightComponent* BeautyLookFindSun(USceneCaptureComponent2D* Capture)
	{
		UWorld* World = Capture != nullptr ? Capture->GetWorld() : nullptr;
		if (World == nullptr)
		{
			return nullptr;
		}
		for (TActorIterator<ADirectionalLight> It(World); It; ++It)
		{
			UDirectionalLightComponent* Light =
				Cast<UDirectionalLightComponent>(It->GetLightComponent());
			if (Light != nullptr && Light->IsUsedAsAtmosphereSunLight() &&
			    Light->GetAtmosphereSunLightIndex() == 0)
			{
				return Light;
			}
		}
		return nullptr;
	}

// Set a float post-process member and its override from Object[Key == Name],
// and echo what the setting now holds.
#define FLIGHTSIM_BEAUTY_FLOAT(Object, Name)                                         \
	{                                                                                \
		double Value_ = 0.0;                                                         \
		if (!BeautyLookNumber(Object, TEXT(#Name), Value_)) { return false; }        \
		Settings.bOverride_##Name = true;                                            \
		Settings.Name = static_cast<float>(Value_);                                  \
		Echo->SetNumberField(TEXT(#Name), Settings.Name);                            \
	}
#define FLIGHTSIM_BEAUTY_VECTOR(Object, Name)                                        \
	{                                                                                \
		FVector4 Value_;                                                             \
		if (!BeautyLookVector4(Object, TEXT(#Name), Value_)) { return false; }       \
		Settings.bOverride_##Name = true;                                            \
		Settings.Name = Value_;                                                      \
		Echo->SetField(TEXT(#Name), BeautyLookVectorJson(Settings.Name));            \
	}

	bool BeautyLookApplyPlan(USceneCaptureComponent2D* Capture, const TCHAR* CommandLine)
	{
		FBeautyLookState& State = BeautyLookState();
		FPostProcessSettings& Settings = Capture->PostProcessSettings;
		const TSharedPtr<FJsonObject>& Plan = State.Plan;
		State.Applied = MakeShared<FJsonObject>();

		double Version = 0.0;
		if (!BeautyLookNumber(Plan, TEXT("beauty_look_version"), Version)) { return false; }
		if (static_cast<int32>(Version) != BeautyLookSupportedVersion)
		{
			return BeautyLookFail(FString::Printf(
				TEXT("sidecar version %g is not the %d this host reads"), Version,
				BeautyLookSupportedVersion));
		}

		// A card's exposure triple or the -sky= plan already meters through a
		// physical camera: its aperture IS part of that exposure (EV100 =
		// log2(N^2 * ShutterSpeed * 100 / ISO)), so the lens below must not
		// change it -- f/4 over a plan's f/N would shift the exposure by
		// 2 log2(4/N) stops with nothing recording it.
		const bool bPhysicalAlready = Settings.bOverride_AutoExposureApplyPhysicalCameraExposure &&
			Settings.AutoExposureApplyPhysicalCameraExposure;

		// -- camera: sensor, aperture, shutter (the FOV is NOT touched) -------
		TSharedPtr<FJsonObject> CameraJson;
		if (!BeautyLookObject(Plan, TEXT("camera"), CameraJson)) { return false; }
		{
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			int32 CameraIndex = 0;
			FParse::Value(CommandLine, TEXT("camera-index="), CameraIndex);
			const TArray<TSharedPtr<FJsonValue>>* Sensors = nullptr;
			if (!CameraJson->TryGetArrayField(TEXT("sensor_width_mm"), Sensors) || Sensors == nullptr ||
			    Sensors->Num() == 0)
			{
				return BeautyLookFail(TEXT("camera.sensor_width_mm is not a list of widths"));
			}
			// A legacy single pass (no -camera-index=) is camera 0; a list
			// shorter than the index is a planning error, refused.
			if (!Sensors->IsValidIndex(CameraIndex) ||
			    !(*Sensors)[CameraIndex]->TryGetNumber(State.SensorWidthMm) ||
			    !(State.SensorWidthMm > 0.0))
			{
				return BeautyLookFail(FString::Printf(
					TEXT("camera.sensor_width_mm has no positive width for -camera-index=%d"),
					CameraIndex));
			}
			if (!CameraJson->TryGetBoolField(TEXT("depth_of_field"), State.bDepthOfField))
			{
				return BeautyLookFail(TEXT("camera.depth_of_field is not true or false"));
			}
			double ApertureF = 0.0, BlurAmount = 0.0, TargetFps = 0.0;
			if (!BeautyLookNumber(CameraJson, TEXT("aperture_f"), ApertureF) ||
			    !BeautyLookNumber(CameraJson, TEXT("MotionBlurAmount"), BlurAmount) ||
			    !BeautyLookNumber(CameraJson, TEXT("MotionBlurTargetFPS"), TargetFps))
			{
				return false;
			}
			// The sensor the depth of field computes its focal length with:
			// UE derives the focal length from FOVAngle and this width, so
			// the same FOV and the same sensor give the manifest's lens.
			Settings.bOverride_DepthOfFieldSensorWidth = true;
			Settings.DepthOfFieldSensorWidth = static_cast<float>(State.SensorWidthMm);
			if (bPhysicalAlready)
			{
				Echo->SetStringField(TEXT("aperture_source"), FString::Printf(
					TEXT("the exposure's (card triple or -sky= plan) f/%g kept; the lens's f/%g not applied"),
					Settings.DepthOfFieldFstop, ApertureF));
			}
			else
			{
				Settings.bOverride_DepthOfFieldFstop = true;
				Settings.DepthOfFieldFstop = static_cast<float>(ApertureF);
				Echo->SetStringField(TEXT("aperture_source"), TEXT("the beauty lens"));
			}
			Settings.bOverride_DepthOfFieldMinFstop = true;
			Settings.DepthOfFieldMinFstop = FMath::Min(1.2f, Settings.DepthOfFieldFstop);
			// Focal distance 0 disables depth of field; a DOF lens gets its
			// distance per frame (UpdatePerFrame).
			Settings.bOverride_DepthOfFieldFocalDistance = true;
			Settings.DepthOfFieldFocalDistance = 0.0f;
			Capture->ShowFlags.SetDepthOfField(State.bDepthOfField);
			// Motion blur from the shutter angle: MotionBlurAmount is the
			// fraction of the frame interval the shutter is open (0.5 =
			// 180 deg), against the clip's own frame rate.
			Settings.bOverride_MotionBlurAmount = true;
			Settings.MotionBlurAmount = static_cast<float>(BlurAmount);
			Settings.bOverride_MotionBlurTargetFPS = true;
			Settings.MotionBlurTargetFPS = FMath::Clamp(FMath::RoundToInt32(TargetFps), 0, 120);
			Capture->ShowFlags.SetMotionBlur(BlurAmount > 0.0);
			const double FocalMm =
				FFlightSimBeautyLook::FocalLengthMm(State.SensorWidthMm, Capture->FOVAngle);
			Echo->SetNumberField(TEXT("camera_index"), CameraIndex);
			Echo->SetNumberField(TEXT("sensor_width_mm"), State.SensorWidthMm);
			Echo->SetNumberField(TEXT("fov_deg_unchanged"), Capture->FOVAngle);
			Echo->SetNumberField(TEXT("focal_length_mm_from_fov"), FocalMm);
			Echo->SetNumberField(TEXT("DepthOfFieldFstop"), Settings.DepthOfFieldFstop);
			Echo->SetBoolField(TEXT("depth_of_field"), State.bDepthOfField);
			Echo->SetNumberField(TEXT("MotionBlurAmount"), Settings.MotionBlurAmount);
			Echo->SetNumberField(TEXT("MotionBlurTargetFPS"), Settings.MotionBlurTargetFPS);
			State.Applied->SetObjectField(TEXT("camera"), Echo);
		}

		// -- exposure: the band's EV100 through the physical camera ------------
		TSharedPtr<FJsonObject> ExposureJson;
		if (!BeautyLookObject(Plan, TEXT("exposure"), ExposureJson)) { return false; }
		{
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			double Ev100 = 0.0;
			const bool bAsked = ExposureJson->TryGetNumberField(TEXT("ev100"), Ev100);
			const bool bManual = Settings.bOverride_AutoExposureMethod &&
				Settings.AutoExposureMethod == EAutoExposureMethod::AEM_Manual;
			if (!bAsked)
			{
				Echo->SetStringField(TEXT("applied"), TEXT("no: the sidecar states no EV100 (the -sky= plan, or a sun not in lux); the exposure stands"));
			}
			else if (!bManual)
			{
				// -AutoExposure (the negative control) or the void tier.
				Echo->SetStringField(TEXT("applied"), TEXT("no: the capture is not under manual exposure"));
			}
			else if (bPhysicalAlready)
			{
				// A card's exposure triple or the physical sky's camera wins.
				Echo->SetStringField(TEXT("applied"),
					TEXT("no: the capture already meters through a physical camera (card triple or -sky= plan)"));
			}
			else
			{
				double ShutterS = 0.0, Iso = 0.0;
				if (!BeautyLookNumber(ExposureJson, TEXT("shutter_s"), ShutterS) ||
				    !BeautyLookNumber(ExposureJson, TEXT("iso"), Iso))
				{
					return false;
				}
				if (!(ShutterS > 0.0) || !(Iso >= 1.0))
				{
					return BeautyLookFail(TEXT("exposure.shutter_s must be positive and exposure.iso at least 1"));
				}
				Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
				Settings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
				Settings.AutoExposureApplyPhysicalCameraExposure = true;
				Settings.bOverride_CameraShutterSpeed = true;
				Settings.CameraShutterSpeed = static_cast<float>(1.0 / ShutterS);
				Settings.bOverride_CameraISO = true;
				Settings.CameraISO = static_cast<float>(Iso);
				// UE 5.7 (PostProcessEyeAdaptation.cpp CalculateManualAutoExposure):
				// camera EV100 = log2(N^2 * ShutterSpeed * 100 / ISO), exposure
				// scaled by 2^AutoExposureBias, so the bias that lands the target
				// is camera EV100 - target.
				const double CameraEv =
					FFlightSimBeautyLook::CameraEv100(Settings.DepthOfFieldFstop, ShutterS, Iso);
				Settings.bOverride_AutoExposureBias = true;
				Settings.AutoExposureBias = static_cast<float>(CameraEv - Ev100);
				State.bExposureApplied = true;
				State.Ev100 = Ev100;
				State.ExposureSource = FString::Printf(
					TEXT("-beauty-look= EV100 %.2f (f/%g, 1/%.0f s, ISO %g, compensation %.3f)"),
					Ev100, Settings.DepthOfFieldFstop, Settings.CameraShutterSpeed, Iso,
					Settings.AutoExposureBias);
				Echo->SetStringField(TEXT("applied"), TEXT("yes"));
				Echo->SetNumberField(TEXT("ev100"), Ev100);
				Echo->SetNumberField(TEXT("camera_ev100"), CameraEv);
				Echo->SetNumberField(TEXT("CameraShutterSpeed"), Settings.CameraShutterSpeed);
				Echo->SetNumberField(TEXT("CameraISO"), Settings.CameraISO);
				Echo->SetNumberField(TEXT("AutoExposureBias"), Settings.AutoExposureBias);
			}
			State.Applied->SetObjectField(TEXT("exposure"), Echo);
		}

		// -- sun colour (the lux rides the existing -sun-lux= hook) ------------
		{
			TSharedPtr<FJsonObject> SunJson;
			if (!BeautyLookObject(Plan, TEXT("sun"), SunJson)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			double TemperatureK = 0.0;
			UDirectionalLightComponent* Sun = BeautyLookFindSun(Capture);
			if (!SunJson->TryGetNumberField(TEXT("temperature_k"), TemperatureK))
			{
				Echo->SetStringField(TEXT("temperature"), TEXT("not asked (the -sky= plan colours the sun)"));
			}
			else if (Sun == nullptr)
			{
				Echo->SetStringField(TEXT("temperature"), TEXT("not applied: no atmosphere sun light in the world"));
			}
			else if (Sun->bUseTemperature || Sun->LightColor != FColor::White)
			{
				// The lighting block's temperature or the X-Plane colours
				// already coloured this sun; tinting on top would count twice.
				Echo->SetStringField(TEXT("temperature"),
					TEXT("not applied: the sun is already coloured (lighting block or X-Plane colours)"));
			}
			else
			{
				Sun->SetUseTemperature(true);
				Sun->SetTemperature(static_cast<float>(TemperatureK));
				Echo->SetNumberField(TEXT("temperature_k"), Sun->Temperature);
			}
			if (Sun != nullptr)
			{
				// What the light holds (lux when -sun-lux= reached it).
				Echo->SetNumberField(TEXT("intensity_read_back"), Sun->Intensity);
			}
			State.Applied->SetObjectField(TEXT("sun"), Echo);
		}

		// -- tonemap, grade, lens, local exposure, reflections -----------------
		{
			TSharedPtr<FJsonObject> Tonemap;
			if (!BeautyLookObject(Plan, TEXT("tonemap"), Tonemap)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, FilmSlope)
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, FilmToe)
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, FilmShoulder)
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, FilmBlackClip)
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, FilmWhiteClip)
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, ToneCurveAmount)
			Capture->ShowFlags.SetTonemapper(true);
			State.Applied->SetObjectField(TEXT("tonemap"), Echo);
		}
		{
			TSharedPtr<FJsonObject> Grade;
			if (!BeautyLookObject(Plan, TEXT("color_grade"), Grade)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			FLIGHTSIM_BEAUTY_VECTOR(Grade, ColorSaturation)
			FLIGHTSIM_BEAUTY_VECTOR(Grade, ColorContrast)
			FLIGHTSIM_BEAUTY_VECTOR(Grade, ColorGamma)
			FLIGHTSIM_BEAUTY_VECTOR(Grade, ColorGain)
			FLIGHTSIM_BEAUTY_VECTOR(Grade, ColorOffset)
			FLIGHTSIM_BEAUTY_FLOAT(Grade, WhiteTemp)
			FLIGHTSIM_BEAUTY_FLOAT(Grade, WhiteTint)
			State.Applied->SetObjectField(TEXT("color_grade"), Echo);
		}
		{
			TSharedPtr<FJsonObject> Lens;
			if (!BeautyLookObject(Plan, TEXT("lens_post"), Lens)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			// Standard (sum-of-Gaussians) bloom: subtle, and image-based like
			// the lens flare's ghosts; convolution bloom needs a kernel
			// texture and costs far more for a glow this faint.
			Settings.bOverride_BloomMethod = true;
			Settings.BloomMethod = EBloomMethod::BM_SOG;
			FLIGHTSIM_BEAUTY_FLOAT(Lens, BloomIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, BloomThreshold)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, LensFlareIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, LensFlareThreshold)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, VignetteIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, FilmGrainIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, SceneFringeIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, MotionBlurMax)
			FLIGHTSIM_BEAUTY_FLOAT(Lens, MotionBlurPerObjectSize)
			{
				double Blades = 0.0;
				if (!BeautyLookNumber(Lens, TEXT("DepthOfFieldBladeCount"), Blades)) { return false; }
				Settings.bOverride_DepthOfFieldBladeCount = true;
				Settings.DepthOfFieldBladeCount = FMath::RoundToInt32(Blades);
				Echo->SetNumberField(TEXT("DepthOfFieldBladeCount"), Settings.DepthOfFieldBladeCount);
			}
			Capture->ShowFlags.SetBloom(Settings.BloomIntensity > 0.0f);
			Capture->ShowFlags.SetLensFlares(Settings.LensFlareIntensity > 0.0f);
			Capture->ShowFlags.SetVignette(Settings.VignetteIntensity > 0.0f);
			Capture->ShowFlags.SetGrain(Settings.FilmGrainIntensity > 0.0f);
			// Chromatic aberration moves pixels off the labels: only drawn when
			// the sidecar's pixel_effects names it (Python refuses otherwise).
			Capture->ShowFlags.SetSceneColorFringe(Settings.SceneFringeIntensity > 0.0f);
			Echo->SetStringField(TEXT("BloomMethod"), TEXT("BM_SOG (standard)"));
			State.Applied->SetObjectField(TEXT("lens_post"), Echo);
		}
		{
			TSharedPtr<FJsonObject> Local;
			if (!BeautyLookObject(Plan, TEXT("local_exposure"), Local)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			Settings.bOverride_LocalExposureMethod = true;
			Settings.LocalExposureMethod = ELocalExposureMethod::Bilateral;
			FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureHighlightContrastScale)
			FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureShadowContrastScale)
			FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureDetailStrength)
			FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureBlurredLuminanceBlend)
			FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureMiddleGreyBias)
			Capture->ShowFlags.SetLocalExposure(true);
			Echo->SetStringField(TEXT("LocalExposureMethod"), TEXT("Bilateral"));
			State.Applied->SetObjectField(TEXT("local_exposure"), Echo);
		}
		{
			TSharedPtr<FJsonObject> Reflections;
			if (!BeautyLookObject(Plan, TEXT("reflections"), Reflections)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			// Integration (2026-11-09): Lumen's quality and distance overrides
			// (reflection / final gather / scene lighting quality, max trace and
			// scene view distance, surface cache) are the render-path lane's,
			// applied after this call and recorded in render_settings.
			// beauty_path.lumen_capture_overrides. Setting them here too was a
			// silent overwrite with a wrong echo; this look sets only the rest.
			Echo->SetStringField(TEXT("lumen_quality_owner"),
				TEXT("render-path lane (render_settings.beauty_path.lumen_capture_overrides)"));
			FLIGHTSIM_BEAUTY_FLOAT(Reflections, LumenSceneDetail)
			FLIGHTSIM_BEAUTY_FLOAT(Reflections, ScreenSpaceReflectionIntensity)
			FLIGHTSIM_BEAUTY_FLOAT(Reflections, ScreenSpaceReflectionQuality)
			FLIGHTSIM_BEAUTY_FLOAT(Reflections, ScreenSpaceReflectionMaxRoughness)
			{
				bool bFrontLayer = false;
				if (!Reflections->TryGetBoolField(TEXT("LumenFrontLayerTranslucencyReflections"), bFrontLayer))
				{
					return BeautyLookFail(TEXT("reflections.LumenFrontLayerTranslucencyReflections is not true or false"));
				}
				Settings.bOverride_LumenFrontLayerTranslucencyReflections = true;
				Settings.LumenFrontLayerTranslucencyReflections = bFrontLayer;
				Echo->SetBoolField(TEXT("LumenFrontLayerTranslucencyReflections"), bFrontLayer);
			}
			Capture->ShowFlags.SetScreenSpaceReflections(true);
			State.Applied->SetObjectField(TEXT("reflections"), Echo);
		}
		return true;
	}

#undef FLIGHTSIM_BEAUTY_FLOAT
#undef FLIGHTSIM_BEAUTY_VECTOR
}

double FFlightSimBeautyLook::CameraEv100(double ApertureF, double ShutterSeconds, double Iso)
{
	// core/scene/beauty_look.py camera_ev100: log2(N^2 / t * 100 / ISO).
	return FMath::Log2((ApertureF * ApertureF / ShutterSeconds) * (100.0 / Iso));
}

double FFlightSimBeautyLook::FocalLengthMm(double SensorWidthMm, double HorizontalFovDeg)
{
	// core/scene/beauty_look.py focal_length_mm: f = w / (2 tan(FOV / 2)).
	return SensorWidthMm / (2.0 * FMath::Tan(FMath::DegreesToRadians(HorizontalFovDeg) * 0.5));
}

void FFlightSimBeautyLook::Apply(USceneCaptureComponent2D* Capture, const TCHAR* CommandLine)
{
	FBeautyLookState& State = BeautyLookState();
	State = FBeautyLookState();
	if (Capture == nullptr)
	{
		return;
	}
	// The V0 beauty overrides (moved here from FlightSimVisualScene.cpp,
	// unchanged): Lumen GI and Lumen reflections as per-view overrides on
	// the camera of record. Whether Lumen runs inside a scene capture on
	// this build is a probe-render question, not a claim this call makes.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_DynamicGlobalIlluminationMethod = true;
	Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::Lumen;
	Settings.bOverride_ReflectionMethod = true;
	Settings.ReflectionMethod = EReflectionMethod::Lumen;

	if (CommandLine == nullptr ||
	    !FParse::Value(CommandLine, TEXT("beauty-look="), State.SidecarPath) ||
	    State.SidecarPath.IsEmpty())
	{
		return;   // no sidecar: exactly the V0 beauty capture
	}
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *State.SidecarPath))
	{
		BeautyLookFail(FString::Printf(TEXT("cannot read the sidecar %s"), *State.SidecarPath));
		return;
	}
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, State.Plan) || !State.Plan.IsValid())
	{
		BeautyLookFail(FString::Printf(TEXT("the sidecar %s is not a JSON object"), *State.SidecarPath));
		return;
	}
	if (!BeautyLookApplyPlan(Capture, CommandLine))
	{
		return;
	}
	State.bApplied = true;
	FString Grade, Lens;
	State.Plan->TryGetStringField(TEXT("grade"), Grade);
	State.Plan->TryGetStringField(TEXT("lens"), Lens);
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("beauty look: grade %s, lens %s, exposure %s, focal length %.1f mm from FOV %.2f deg"),
	       *Grade, *Lens, State.bExposureApplied ? *State.ExposureSource : TEXT("left as it was"),
	       FocalLengthMm(State.SensorWidthMm, Capture->FOVAngle), Capture->FOVAngle);
}

void FFlightSimBeautyLook::UpdatePerFrame(USceneCaptureComponent2D* Capture, const AActor* Subject)
{
	FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied || Capture == nullptr)
	{
		return;
	}
	++State.Frames;
	const double FocalMm = FocalLengthMm(State.SensorWidthMm, Capture->FOVAngle);
	State.FocalMinMm = FMath::Min(State.FocalMinMm, FocalMm);
	State.FocalMaxMm = FMath::Max(State.FocalMaxMm, FocalMm);
	if (State.bDepthOfField && Subject != nullptr)
	{
		// The range the manifest's two poses give: capture to aircraft actor
		// origin (the JSBSim structural datum, NEXT.md gotcha 31: metres
		// from the visual centre, far inside the depth of field at chase
		// range).
		const double RangeCm =
			FVector::Dist(Capture->GetComponentLocation(), Subject->GetActorLocation());
		Capture->PostProcessSettings.DepthOfFieldFocalDistance = static_cast<float>(RangeCm);
		State.FocusMinM = FMath::Min(State.FocusMinM, RangeCm / BeautyLookCmPerMetre);
		State.FocusMaxM = FMath::Max(State.FocusMaxM, RangeCm / BeautyLookCmPerMetre);
	}
}

void FFlightSimBeautyLook::RecordExposure(FString& ExposureMode, FString& ExposureSource,
                                          double& AppliedEv100, bool& bAppliedEv100)
{
	const FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied || !State.bExposureApplied)
	{
		return;
	}
	ExposureMode = TEXT("beauty_ev100");
	ExposureSource = State.ExposureSource;
	AppliedEv100 = State.Ev100;
	bAppliedEv100 = true;
}

TSharedPtr<FJsonObject> FFlightSimBeautyLook::Record()
{
	const FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied)
	{
		return nullptr;
	}
	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("sidecar"), State.SidecarPath);
	Root->SetObjectField(TEXT("plan"), State.Plan);
	Root->SetObjectField(TEXT("applied"), State.Applied);
	TSharedPtr<FJsonObject> Frames = MakeShared<FJsonObject>();
	Frames->SetNumberField(TEXT("frames"), State.Frames);
	if (State.Frames > 0)
	{
		Frames->SetNumberField(TEXT("focal_length_mm_min"), State.FocalMinMm);
		Frames->SetNumberField(TEXT("focal_length_mm_max"), State.FocalMaxMm);
	}
	if (State.bDepthOfField && State.FocusMaxM > 0.0)
	{
		Frames->SetNumberField(TEXT("focus_distance_m_min"), State.FocusMinM);
		Frames->SetNumberField(TEXT("focus_distance_m_max"), State.FocusMaxM);
	}
	Root->SetObjectField(TEXT("per_frame"), Frames);
	Root->SetStringField(TEXT("labels"),
		TEXT("masks, class, depth and boxes are separate captures of the same frame without this look; ")
		TEXT("no visual-only actor is added (nothing occludes the aircraft in beauty that the masks lack)"));
	return Root;
}

const FString& FFlightSimBeautyLook::LastError()
{
	return BeautyLookState().Error;
}
