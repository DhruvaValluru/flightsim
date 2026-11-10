#include "FlightSimBeautyLook.h"

#include "FlightSimRenderCommandlet.h"
#include "FlightSimVisualScene.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"   // round 5 L1: the volumetric fog's albedo
#include "Components/SceneCaptureComponent2D.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "Engine/EngineTypes.h"
#include "Engine/Scene.h"
#include "Engine/TextureRenderTarget2D.h"   // round 5 L1: the frame's aspect for the lens-flare gate
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "HAL/IConsoleManager.h"   // round 5 L1: the engine look's renderer cvars
#include "HAL/PlatformMisc.h"      // round 5 L1: FLIGHTSIM_RENDER_SWITCHES (-look-<name>=)
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "RHIShaderPlatform.h"   // GMaxRHIShaderPlatform (exposure meter: the GI path)
#include "RHIStrings.h"          // LexToString(EShaderPlatform)
#include "RenderUtils.h"         // DoesPlatformSupportLumenGI
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UObjectIterator.h"   // round 5 L1: the world's height fog components

// UNCOMPILED when written: see the header. Every FPostProcessSettings member
// set below was read in UE 5.7.4's Engine/Classes/Engine/Scene.h (with its
// bOverride_ twin), every show flag in Public/ShowFlagsValues.inl, and the
// light members in Classes/Components/{LightComponent,LightComponentBase,
// DirectionalLightComponent}.h; scripts/check_bridge_api.sh re-checks them.
// Round 5 L1 (the engine look): each cvar below was read at its definition
// (ScreenSpaceRayTracing.cpp, PostProcessAmbientOcclusion.cpp,
// ShadowRendering.cpp, ShadowSetup.cpp, SceneRendering.cpp,
// DistanceFieldShadowing.cpp, VolumetricFog.cpp, PostProcessLensFlares.cpp,
// Core's ConsoleManager.cpp), the fog setters in
// ExponentialHeightFogComponent.h, and the engine's default bloom kernel and
// film-grain textures in SceneRendering.cpp (loaded when the post-process
// texture is null); scripts/check_bridge_api.sh ("engine look" block).

namespace
{
	// Names are per-file unique (NEXT.md gotcha 3: unity builds merge
	// anonymous namespaces across files).
	constexpr int32 BeautyLookSupportedVersion = 3;
	constexpr double BeautyLookCmPerMetre = 100.0;
	// core/scene/beauty_look.py LOOK_SWITCH_PREFIX, without the dash FParse
	// does not need: "-look-bloom=off" is found as "look-bloom=".
	const TCHAR* const BeautyLookSwitchPrefix = TEXT("look-");

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
		// Round 2: the exposure meter the commandlet runs before frame 0
		// (ExposureMeter): under a deck, or when Lumen GI does not run.
		bool bMeter = false;
		double MeterTargetP90 = 0.0;
		FString MeterTrigger;
		int32 Frames = 0;
		double FocusMinM = TNumericLimits<double>::Max();
		double FocusMaxM = 0.0;
		double FocalMinMm = TNumericLimits<double>::Max();
		double FocalMaxMm = 0.0;
		// Round 5 L1: the engine look. The plan's block, the record under
		// applied.engine_look, the switch text (command line + environment),
		// and whether the host is the constrained GPU (set by ApplyEngineLook;
		// the early half reads the switches only, no constrained column).
		TSharedPtr<FJsonObject> EngineLook;
		TSharedPtr<FJsonObject> EngineApplied;
		FString SwitchText;
		bool bConstrained = false;
		bool bEngineLate = false;
		// The lens-flare gate: decided on the first frame from the camera axis
		// and the sun, then held for the clip.
		bool bFlareGate = false;
		bool bFlareDecided = false;
		double FlareMarginDeg = 0.0;
		// The still's TSR accumulation the tsr row asks for.
		bool bTsr = false;
		int32 TsrWarmup = 0;
		int32 TsrStillSamples = 0;
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

	// -- round 5 L1: the engine look's switches and rows --------------------

	// The -look-<name>= switch's word, from the command line and then
	// FLIGHTSIM_RENDER_SWITCHES (State.SwitchText): on|off for an effect,
	// auto|on|off for a probe; unstated is "on" / "auto". A word the switch
	// does not take refuses by name (render.look_switch, the catalogue's).
	bool BeautyLookSwitch(const FString& Name, bool bProbe, FString& Mode)
	{
		Mode = bProbe ? TEXT("auto") : TEXT("on");
		FString Value;
		const FString Key = FString(BeautyLookSwitchPrefix) + Name + TEXT("=");
		if (FParse::Value(*BeautyLookState().SwitchText, *Key, Value) && !Value.IsEmpty())
		{
			Mode = Value.ToLower();
		}
		const bool bKnown = Mode == TEXT("on") || Mode == TEXT("off") || (bProbe && Mode == TEXT("auto"));
		if (!bKnown)
		{
			BeautyLookState().Error = FString::Printf(
				TEXT("render.look_switch: -look-%s=%s is not one of %s"), *Name, *Mode,
				bProbe ? TEXT("auto, on, off") : TEXT("on, off"));
			UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *BeautyLookState().Error);
			return false;
		}
		return true;
	}

	// One effect of the sidecar's engine_look (core/scene/beauty_look.py
	// engine_look_for): its switch resolved, its values (the constrained
	// column when the host is the constrained GPU and the row has one), its
	// cvars, and its record under applied.engine_look.<key>.
	struct FBeautyLookEffect
	{
		FString Key;
		FString Switch;
		FString Mode;
		bool bProbe = false;
		bool bOn = false;
		TSharedPtr<FJsonObject> Values;
		TSharedPtr<FJsonObject> Cvars;
		TSharedPtr<FJsonObject> CvarsOff;
		TSharedPtr<FJsonObject> Record;
	};

	bool BeautyLookEffect(const TCHAR* Key, bool bConstrained, FBeautyLookEffect& Out)
	{
		FBeautyLookState& State = BeautyLookState();
		Out = FBeautyLookEffect();
		Out.Key = Key;
		TSharedPtr<FJsonObject> Row;
		if (!BeautyLookObject(State.EngineLook, Key, Row)) { return false; }
		FString SwitchFull;
		if (!Row->TryGetStringField(TEXT("switch"), SwitchFull) || SwitchFull.IsEmpty())
		{
			return BeautyLookFail(FString::Printf(TEXT("engine_look.%s names no switch"), Key));
		}
		Out.Switch = SwitchFull;
		Out.Switch.RemoveFromStart(TEXT("-"));
		Out.Switch.RemoveFromStart(BeautyLookSwitchPrefix);
		Row->TryGetBoolField(TEXT("probe"), Out.bProbe);
		bool bAutoOnConstrained = false;
		Row->TryGetBoolField(TEXT("auto_on_constrained"), bAutoOnConstrained);
		if (!BeautyLookSwitch(Out.Switch, Out.bProbe, Out.Mode)) { return false; }
		// A probe's auto: off on the constrained GPU (the Intel iGPU under
		// D3D11 SM5), on elsewhere, unless the row says its auto is on there
		// too (the fog grid every passing round rendered with).
		Out.bOn = Out.Mode == TEXT("on") ||
			(Out.Mode == TEXT("auto") && (!bConstrained || bAutoOnConstrained));
		const TSharedPtr<FJsonObject>* Found = nullptr;
		if (bConstrained && Row->TryGetObjectField(TEXT("values_constrained"), Found) && Found != nullptr &&
		    Found->IsValid())
		{
			Out.Values = *Found;
		}
		else if (!BeautyLookObject(Row, TEXT("values"), Out.Values))
		{
			return false;
		}
		if (!BeautyLookObject(Row, bConstrained ? TEXT("cvars_constrained") : TEXT("cvars"), Out.Cvars))
		{
			return false;
		}
		if (Row->TryGetObjectField(TEXT("cvars_off"), Found) && Found != nullptr && Found->IsValid())
		{
			Out.CvarsOff = *Found;
		}
		Out.Record = MakeShared<FJsonObject>();
		Out.Record->SetStringField(TEXT("switch"), SwitchFull);
		Out.Record->SetStringField(TEXT("mode"), Out.Mode);
		Out.Record->SetBoolField(TEXT("probe"), Out.bProbe);
		Out.Record->SetBoolField(TEXT("on"), Out.bOn);
		FString OffMeans;
		Row->TryGetStringField(TEXT("off_means"), OffMeans);
		Out.Record->SetStringField(TEXT("off_means"), OffMeans);
		Out.Record->SetBoolField(TEXT("constrained_column"), bConstrained);
		State.EngineApplied->SetObjectField(Key, Out.Record);
		return true;
	}

	// Set every renderer cvar of Cvars at code priority (over the Cinematic
	// scalability level), for this process only, recording before / asked /
	// read back under the effect's record as Label.
	void BeautyLookCvars(const TSharedPtr<FJsonObject>& Cvars, FBeautyLookEffect& Effect, const TCHAR* Label)
	{
		if (!Cvars.IsValid() || !Effect.Record.IsValid())
		{
			return;
		}
		TSharedPtr<FJsonObject> Before = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> Asked = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ReadBack = MakeShared<FJsonObject>();
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : Cvars->Values)
		{
			double Value = 0.0;
			if (!Entry.Value.IsValid() || !Entry.Value->TryGetNumber(Value))
			{
				continue;
			}
			Asked->SetNumberField(Entry.Key, Value);
			if (IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(*Entry.Key))
			{
				Before->SetStringField(Entry.Key, Variable->GetString());
				Variable->Set(static_cast<float>(Value), ECVF_SetByCode);
				ReadBack->SetStringField(Entry.Key, Variable->GetString());
			}
			else
			{
				ReadBack->SetStringField(Entry.Key, TEXT("absent"));
				UE_LOG(LogFlightSimRender, Warning,
				       TEXT("engine look %s: renderer cvar %s not found on this build; recorded absent"),
				       *Effect.Key, *Entry.Key);
			}
		}
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetObjectField(TEXT("before"), Before);
		Out->SetObjectField(TEXT("asked"), Asked);
		Out->SetObjectField(TEXT("read_back"), ReadBack);
		Effect.Record->SetObjectField(Label, Out);
	}

	// A cvar read back as text for the record ("absent" when the build lacks it).
	FString BeautyLookCvarText(const TCHAR* Name)
	{
		IConsoleVariable* Variable = IConsoleManager::Get().FindConsoleVariable(Name);
		return Variable != nullptr ? Variable->GetString() : FString(TEXT("absent"));
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

		// Round 5 L1: the engine look's block and its switches (the command
		// line, then FLIGHTSIM_RENDER_SWITCHES, the channel the round-5 shade
		// probes use). The rows are applied by BeautyLookApplyEngineLook after
		// the other lanes; the local-exposure row is applied below with the
		// rest of the post-process, and reads its switch here.
		if (!BeautyLookObject(Plan, TEXT("engine_look"), State.EngineLook)) { return false; }
		State.EngineApplied = MakeShared<FJsonObject>();
		State.Applied->SetObjectField(TEXT("engine_look"), State.EngineApplied);
		State.SwitchText = FString(CommandLine != nullptr ? CommandLine : TEXT("")) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
		{
			FString LookPreset, LookPresetBasis;
			State.EngineLook->TryGetStringField(TEXT("preset"), LookPreset);
			State.EngineLook->TryGetStringField(TEXT("preset_basis"), LookPresetBasis);
			State.EngineApplied->SetStringField(TEXT("preset"), LookPreset);
			State.EngineApplied->SetStringField(TEXT("preset_basis"), LookPresetBasis);
			State.EngineApplied->SetStringField(TEXT("switch_source"),
				TEXT("-look-<name>= on the command line, then FLIGHTSIM_RENDER_SWITCHES; unstated renders as planned"));
			State.EngineApplied->SetStringField(TEXT("late_half"),
				TEXT("pending: FFlightSimBeautyLook::ApplyEngineLook (after the render-path, hero-lighting and ")
				TEXT("no-lumen-fallback hooks)"));
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
			// Per camera: a camera inside the aircraft (cockpit) would focus on
			// the JSBSim datum a few metres behind it; the plan says "off".
			FString FocusBasis = State.bDepthOfField ? TEXT("subject") : TEXT("off");
			const TArray<TSharedPtr<FJsonValue>>* Focus = nullptr;
			if (CameraJson->TryGetArrayField(TEXT("focus_per_camera"), Focus) && Focus != nullptr)
			{
				if (!Focus->IsValidIndex(CameraIndex) || !(*Focus)[CameraIndex]->TryGetString(FocusBasis))
				{
					return BeautyLookFail(FString::Printf(
						TEXT("camera.focus_per_camera has no entry for -camera-index=%d"), CameraIndex));
				}
				if (FocusBasis == TEXT("off"))
				{
					State.bDepthOfField = false;
				}
			}
			Echo->SetStringField(TEXT("focus_basis"), FocusBasis);
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
			// Round 2, ONE exposure owner: the sidecar's EV100 is the -sky=
			// plan's clear-sky meter moved by the deck and the lighting look
			// (core/scene/beauty_look.py exposure_target). With -sky= on the
			// command line the commandlet never applies a card triple (the two
			// are exclusive there), so the physical camera already set IS the
			// plan's: kept, and only the compensation moves.
			bool bOverSkyPlan = false;
			ExposureJson->TryGetBoolField(TEXT("over_sky_plan"), bOverSkyPlan);
			FString SkyPlanArg;
			const bool bSkyPlanRun = CommandLine != nullptr &&
				FParse::Value(CommandLine, TEXT("sky="), SkyPlanArg) && !SkyPlanArg.IsEmpty();
			if (!bAsked)
			{
				Echo->SetStringField(TEXT("applied"), TEXT("no: the sidecar states no EV100 (the -sky= plan, or a sun not in lux); the exposure stands"));
			}
			else if (!bManual)
			{
				// -AutoExposure (the negative control) or the void tier.
				Echo->SetStringField(TEXT("applied"), TEXT("no: the capture is not under manual exposure"));
			}
			else if (bPhysicalAlready && bOverSkyPlan && bSkyPlanRun)
			{
				const double PlanBias = Settings.AutoExposureBias;
				const double ShutterS = Settings.CameraShutterSpeed > 0.0f
					? 1.0 / static_cast<double>(Settings.CameraShutterSpeed) : 0.0;
				if (!(ShutterS > 0.0) || !(Settings.CameraISO >= 1.0f) || !(Settings.DepthOfFieldFstop > 0.0f))
				{
					return BeautyLookFail(TEXT("the exposure over the -sky= plan: the plan's physical camera ")
					                      TEXT("(f-number, shutter, ISO) is not set on the capture"));
				}
				const double CameraEv = FFlightSimBeautyLook::CameraEv100(
					Settings.DepthOfFieldFstop, ShutterS, Settings.CameraISO);
				Settings.bOverride_AutoExposureBias = true;
				Settings.AutoExposureBias = static_cast<float>(CameraEv - Ev100);
				State.bExposureApplied = true;
				State.Ev100 = Ev100;
				State.ExposureSource = FString::Printf(
					TEXT("-beauty-look= EV100 %.2f over the -sky= plan's camera (f/%g, 1/%.0f s, ISO %g; ")
					TEXT("compensation %.3f, the plan's was %.3f)"),
					Ev100, Settings.DepthOfFieldFstop, Settings.CameraShutterSpeed, Settings.CameraISO,
					Settings.AutoExposureBias, PlanBias);
				Echo->SetStringField(TEXT("applied"), TEXT("yes, over the -sky= plan's camera"));
				Echo->SetNumberField(TEXT("ev100"), Ev100);
				Echo->SetNumberField(TEXT("camera_ev100"), CameraEv);
				Echo->SetNumberField(TEXT("sky_plan_bias"), PlanBias);
				Echo->SetNumberField(TEXT("CameraShutterSpeed"), Settings.CameraShutterSpeed);
				Echo->SetNumberField(TEXT("CameraISO"), Settings.CameraISO);
				Echo->SetNumberField(TEXT("AutoExposureBias"), Settings.AutoExposureBias);
			}
			else if (bPhysicalAlready)
			{
				// A card's exposure triple (or a -sky= plan the sidecar does not
				// claim) wins.
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
			// -- the exposure meter (round 2) -----------------------------
			// The prediction above cannot know how dark the engine's own deck
			// renders, nor how much fill is missing when Lumen GI does not
			// run (the D3D11 / SM5 laptop: shot c at a luma mean of 3.6/255).
			// The commandlet meters the frame once before frame 0 when this
			// look owns the exposure and either holds (ExposureMeter).
			const TSharedPtr<FJsonObject>* MeterJson = nullptr;
			const bool bLumenGi = DoesPlatformSupportLumenGI(GMaxRHIShaderPlatform);
			TSharedPtr<FJsonObject> MeterEcho = MakeShared<FJsonObject>();
			MeterEcho->SetStringField(TEXT("shader_platform"), LexToString(GMaxRHIShaderPlatform));
			MeterEcho->SetBoolField(TEXT("lumen_gi_supported"), bLumenGi);
			MeterEcho->SetStringField(TEXT("lumen_gi_basis"),
				TEXT("DoesPlatformSupportLumenGI(GMaxRHIShaderPlatform) (RenderUtils.h; r.Lumen.Supported, ")
				TEXT("r.Lumen.Supported.SM5): a cvar that reads 1 does not make Lumen run"));
			if (ExposureJson->TryGetObjectField(TEXT("meter"), MeterJson) && MeterJson != nullptr &&
			    MeterJson->IsValid())
			{
				bool bDeck = false;
				double DeckTarget = 0.0, NoLumenTarget = 0.0;
				(*MeterJson)->TryGetBoolField(TEXT("deck"), bDeck);
				if (!BeautyLookNumber(*MeterJson, TEXT("target_p90_luma"), DeckTarget) ||
				    !BeautyLookNumber(*MeterJson, TEXT("no_lumen_gi_target_p90_luma"), NoLumenTarget))
				{
					return false;
				}
				if (!(DeckTarget > 0.0 && DeckTarget < 1.0) || !(NoLumenTarget > 0.0 && NoLumenTarget < 1.0))
				{
					return BeautyLookFail(TEXT("exposure.meter targets must be sRGB luma fractions in (0, 1)"));
				}
				if (!State.bExposureApplied)
				{
					MeterEcho->SetStringField(TEXT("runs"), TEXT("no: this look does not own the exposure"));
				}
				else if (bDeck)
				{
					State.bMeter = true;
					State.MeterTargetP90 = DeckTarget;
					State.MeterTrigger = TEXT("deck");
				}
				else if (!bLumenGi)
				{
					State.bMeter = true;
					State.MeterTargetP90 = NoLumenTarget;
					State.MeterTrigger = TEXT("no_lumen_gi");
				}
				else
				{
					MeterEcho->SetStringField(TEXT("runs"), TEXT("no: no deck, and Lumen GI runs"));
				}
				if (State.bMeter)
				{
					MeterEcho->SetStringField(TEXT("runs"), TEXT("yes"));
					MeterEcho->SetStringField(TEXT("trigger"), State.MeterTrigger);
					MeterEcho->SetNumberField(TEXT("target_p90_luma"), State.MeterTargetP90);
					MeterEcho->SetStringField(TEXT("result"),
						TEXT("look_applied.storm_exposure (the commandlet's meter loop)"));
				}
			}
			else
			{
				MeterEcho->SetStringField(TEXT("runs"), TEXT("no: the sidecar states no meter"));
			}
			Echo->SetObjectField(TEXT("meter"), MeterEcho);
			State.Applied->SetObjectField(TEXT("exposure"), Echo);
		}

		// -- sun (the lux rides the existing -sun-lux= hook) -------------------
		// ONE transmittance model, the physical sky's (core/scene/beauty_look.py):
		// the lux is OUTER-SPACE illuminance and the engine's per-pixel
		// atmosphere transmittance dims and reddens it once. UE 5.7.4
		// DirectionalLightComponent.cpp: with bPerPixelAtmosphereTransmittance
		// the light's illuminance carries no transmittance, and the shader
		// samples the LUT at the pixel's own sun angle (SkyAtmosphereCommon.ush
		// GetAtmosphereTransmittance), past the +90 deg CPU floor. This host
		// never tints the sun: no temperature, no 8-bit colour comparison.
		{
			TSharedPtr<FJsonObject> SunJson;
			if (!BeautyLookObject(Plan, TEXT("sun"), SunJson)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			UDirectionalLightComponent* Sun = BeautyLookFindSun(Capture);
			double PlanLux = 0.0;
			const bool bPlanLux = SunJson->TryGetNumberField(TEXT("lux"), PlanLux);
			FString Transmittance;
			SunJson->TryGetStringField(TEXT("transmittance"), Transmittance);
			Echo->SetStringField(TEXT("colour_owner"),
				TEXT("the engine's per-pixel atmosphere transmittance; the beauty look sets no sun temperature"));
			if (Sun == nullptr)
			{
				Echo->SetStringField(TEXT("sun"), TEXT("no atmosphere sun light in the world"));
			}
			else
			{
				const bool bPerPixel = Sun->bPerPixelAtmosphereTransmittance != 0;
				if (bPlanLux && Transmittance == TEXT("engine_per_pixel") && !bPerPixel)
				{
					// Outer-space lux with only the +90 deg zenith floor would
					// reach the ground undimmed and white at a low sun.
					return BeautyLookFail(TEXT("the sun is in outer-space lux but the atmosphere sun light has ")
						TEXT("bPerPixelAtmosphereTransmittance off: the engine would not dim and redden it"));
				}
				Echo->SetBoolField(TEXT("per_pixel_transmittance"), bPerPixel);
				// Read back as data, never as a decision: another lane's colour
				// (the lighting block's temperature, the X-Plane colours) stands.
				Echo->SetBoolField(TEXT("use_temperature_read_back"), Sun->bUseTemperature != 0);
				Echo->SetStringField(TEXT("light_color_read_back"), FString::Printf(TEXT("%d:%d:%d"),
					Sun->LightColor.R, Sun->LightColor.G, Sun->LightColor.B));
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
			// Round 2b presets-colour: the hue guard (core/scene/beauty_look.py
			// TONEMAP_HUE). FPostProcessSettings::BlueCorrection keeps a saturated
			// sky-blue shadow fill from skewing to violet through the AP1 tone
			// curve (PostProcessCombineLUTs.usf, every RHI incl. D3D11 SM5).
			FLIGHTSIM_BEAUTY_FLOAT(Tonemap, BlueCorrection)
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
			// Round 5 L1: bloom, the lens flare and the film grain are the
			// engine look's, per world preset (BeautyLookApplyEngineLook);
			// the lens keeps the vignette, the fringe, the motion blur caps
			// and the iris.
			FLIGHTSIM_BEAUTY_FLOAT(Lens, VignetteIntensity)
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
			Capture->ShowFlags.SetVignette(Settings.VignetteIntensity > 0.0f);
			// Chromatic aberration moves pixels off the labels: only drawn when
			// the sidecar's pixel_effects names it (Python refuses otherwise).
			Capture->ShowFlags.SetSceneColorFringe(Settings.SceneFringeIntensity > 0.0f);
			Echo->SetStringField(TEXT("bloom_flare_grain_owner"),
				TEXT("ENGINE_LOOK per world preset (applied.engine_look.bloom / bloom_fft / lens_flare / film_grain)"));
			// One owner of lens character on beauty: this lens. Under -sky= the
			// plan's per-camera lens (FFlightSimSky::ApplyPostProcess, applied
			// first) is replaced here, and the record says so.
			Echo->SetStringField(TEXT("lens_character_owner"),
				TEXT("the beauty lens; replaces the -sky= plan's grain, vignette and motion blur when one is set"));
			State.Applied->SetObjectField(TEXT("lens_post"), Echo);
		}
		{
			TSharedPtr<FJsonObject> Local;
			if (!BeautyLookObject(Plan, TEXT("local_exposure"), Local)) { return false; }
			TSharedPtr<FJsonObject> Echo = MakeShared<FJsonObject>();
			Settings.bOverride_LocalExposureMethod = true;
			Settings.LocalExposureMethod = ELocalExposureMethod::Bilateral;
			// Round 5 L1: the row is per world preset (ENGINE_LOOK
			// local_exposure, the plan's local_exposure carries the preset's
			// values); -look-local-exposure=off sets every scale to 1 (the
			// bilateral grid then changes nothing), the A/B control.
			FBeautyLookEffect LocalEffect;
			if (!BeautyLookEffect(TEXT("local_exposure"), false, LocalEffect)) { return false; }
			if (LocalEffect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureHighlightContrastScale)
				FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureShadowContrastScale)
				FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureDetailStrength)
				FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureBlurredLuminanceBlend)
				FLIGHTSIM_BEAUTY_FLOAT(Local, LocalExposureMiddleGreyBias)
			}
			else
			{
				Settings.bOverride_LocalExposureHighlightContrastScale = true;
				Settings.LocalExposureHighlightContrastScale = 1.0f;
				Settings.bOverride_LocalExposureShadowContrastScale = true;
				Settings.LocalExposureShadowContrastScale = 1.0f;
				Settings.bOverride_LocalExposureDetailStrength = true;
				Settings.LocalExposureDetailStrength = 1.0f;
				Echo->SetNumberField(TEXT("LocalExposureHighlightContrastScale"), 1.0);
				Echo->SetNumberField(TEXT("LocalExposureShadowContrastScale"), 1.0);
				Echo->SetNumberField(TEXT("LocalExposureDetailStrength"), 1.0);
			}
			Capture->ShowFlags.SetLocalExposure(true);
			Echo->SetStringField(TEXT("LocalExposureMethod"), TEXT("Bilateral"));
			State.Applied->SetObjectField(TEXT("local_exposure"), Echo);
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : Echo->Values)
			{
				LocalEffect.Record->SetField(Entry.Key, Entry.Value);
			}
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
			// Round 5 L1: the screen-space reflection values are the engine
			// look's, per world preset (applied.engine_look.ssr).
			Echo->SetStringField(TEXT("ssr_owner"), TEXT("ENGINE_LOOK ssr (applied.engine_look.ssr)"));
			FLIGHTSIM_BEAUTY_FLOAT(Reflections, LumenSceneDetail)
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

	// -- round 5 L1: the engine look, applied after the other lanes -----------
	// Order: the render-path block (scalability, TSR, Lumen overrides), the
	// hero-lighting lane (source angle, contact shadows in world space,
	// shafts, fog grid) and the no-lumen fallback (ScreenSpace GI / SSR,
	// cascades) have all run; this reads each value it replaces back first,
	// so render.json shows the lane's value beside the earlier one. The
	// capture is not yet registered (its show flags are pinned after).
	bool BeautyLookApplyEngineLook(FFlightSimVisualScene& Scene, USceneCaptureComponent2D* Capture)
	{
		FBeautyLookState& State = BeautyLookState();
		FPostProcessSettings& Settings = Capture->PostProcessSettings;
		const bool bConstrained = State.bConstrained;
		UDirectionalLightComponent* Sun = Scene.Sun != nullptr
			? Cast<UDirectionalLightComponent>(Scene.Sun->GetLightComponent()) : BeautyLookFindSun(Capture);
		FBeautyLookEffect Effect;
		TSharedPtr<FJsonObject> Echo;

		// 1. Screen-space GI (the stand-in for Lumen's bounce). The METHOD is
		// the earlier lanes' (Lumen where it runs, the fallback's ScreenSpace
		// where it does not); this sets its quality and the indirect intensity.
		if (!BeautyLookEffect(TEXT("ssgi"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			const bool bScreenSpace = Settings.bOverride_DynamicGlobalIlluminationMethod &&
				Settings.DynamicGlobalIlluminationMethod == EDynamicGlobalIlluminationMethod::ScreenSpace;
			const bool bLumen = Settings.bOverride_DynamicGlobalIlluminationMethod &&
				Settings.DynamicGlobalIlluminationMethod == EDynamicGlobalIlluminationMethod::Lumen;
			Echo->SetStringField(TEXT("method_before"), bScreenSpace ? TEXT("ScreenSpace") : bLumen ? TEXT("Lumen") : TEXT("other"));
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, IndirectLightingIntensity)
				if (bScreenSpace)
				{
					BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
				}
				else
				{
					Echo->SetStringField(TEXT("cvars"), TEXT("not set: the GI method is not ScreenSpace (Lumen runs)"));
				}
			}
			else if (bScreenSpace)
			{
				Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::None;
			}
			Echo->SetStringField(TEXT("method"),
				Settings.DynamicGlobalIlluminationMethod == EDynamicGlobalIlluminationMethod::ScreenSpace ? TEXT("ScreenSpace")
				: Settings.DynamicGlobalIlluminationMethod == EDynamicGlobalIlluminationMethod::Lumen ? TEXT("Lumen")
				: Settings.DynamicGlobalIlluminationMethod == EDynamicGlobalIlluminationMethod::None ? TEXT("None") : TEXT("other"));
			Echo->SetStringField(TEXT("r.SSGI.Quality_read_back"), BeautyLookCvarText(TEXT("r.SSGI.Quality")));
		}

		// 2. Screen-space reflections: canopy glass, wet ground, the ocean.
		if (!BeautyLookEffect(TEXT("ssr"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			Echo->SetStringField(TEXT("method_before"),
				Settings.ReflectionMethod == EReflectionMethod::ScreenSpace ? TEXT("ScreenSpace")
				: Settings.ReflectionMethod == EReflectionMethod::Lumen ? TEXT("Lumen") : TEXT("other"));
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, ScreenSpaceReflectionIntensity)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, ScreenSpaceReflectionQuality)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, ScreenSpaceReflectionMaxRoughness)
				BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
				Capture->ShowFlags.SetScreenSpaceReflections(true);
			}
			else
			{
				Settings.bOverride_ReflectionMethod = true;
				Settings.ReflectionMethod = EReflectionMethod::None;
				Settings.bOverride_ScreenSpaceReflectionIntensity = true;
				Settings.ScreenSpaceReflectionIntensity = 0.0f;
				Capture->ShowFlags.SetScreenSpaceReflections(false);
				Echo->SetNumberField(TEXT("ScreenSpaceReflectionIntensity"), 0.0);
			}
			Echo->SetStringField(TEXT("method"),
				Settings.ReflectionMethod == EReflectionMethod::ScreenSpace ? TEXT("ScreenSpace")
				: Settings.ReflectionMethod == EReflectionMethod::Lumen ? TEXT("Lumen")
				: Settings.ReflectionMethod == EReflectionMethod::None ? TEXT("None") : TEXT("other"));
		}

		// 3. SSAO (CompositionLighting.cpp ShouldRenderScreenSpaceAmbientOcclusion:
		// intensity > 0, radius >= 0.1, a sky light or reflection environment
		// active -- the scene has both).
		if (!BeautyLookEffect(TEXT("ssao"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionIntensity)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionRadius)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionQuality)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionPower)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionStaticFraction)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionMipBlend)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, AmbientOcclusionTemporalBlendWeight)
				bool bRadiusWorld = false;
				Effect.Values->TryGetBoolField(TEXT("AmbientOcclusionRadiusInWS"), bRadiusWorld);
				Settings.bOverride_AmbientOcclusionRadiusInWS = true;
				Settings.AmbientOcclusionRadiusInWS = bRadiusWorld ? 1 : 0;
				Echo->SetBoolField(TEXT("AmbientOcclusionRadiusInWS"), bRadiusWorld);
				BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
			}
			else
			{
				Settings.bOverride_AmbientOcclusionIntensity = true;
				Settings.AmbientOcclusionIntensity = 0.0f;
				Echo->SetNumberField(TEXT("AmbientOcclusionIntensity"), 0.0);
			}
			Capture->ShowFlags.SetAmbientOcclusion(true);
			Capture->ShowFlags.SetScreenSpaceAO(Effect.bOn);
		}

		// 4. The sun's cascaded shadows: the cascades over the kilometres the
		// camera resolves, 4096-texel maps, PCSS from the sun's own disc.
		if (!BeautyLookEffect(TEXT("sun_shadows"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Sun == nullptr)
			{
				Echo->SetStringField(TEXT("skipped"), TEXT("the scene has no directional sun"));
			}
			else
			{
				TSharedPtr<FJsonObject> Before = MakeShared<FJsonObject>();
				Before->SetNumberField(TEXT("DynamicShadowCascades"), Sun->DynamicShadowCascades);
				Before->SetNumberField(TEXT("CascadeDistributionExponent"), Sun->CascadeDistributionExponent);
				Before->SetNumberField(TEXT("DynamicShadowDistanceMovableLight_m"),
				                       Sun->DynamicShadowDistanceMovableLight / BeautyLookCmPerMetre);
				Before->SetNumberField(TEXT("ShadowDistanceFadeoutFraction"), Sun->ShadowDistanceFadeoutFraction);
				Before->SetNumberField(TEXT("CascadeTransitionFraction"), Sun->CascadeTransitionFraction);
				Echo->SetObjectField(TEXT("before"), Before);
				if (Effect.bOn)
				{
					double Cascades = 0.0, Exponent = 0.0, DistanceM = 0.0, Fade = 0.0, Transition = 0.0;
					if (!BeautyLookNumber(Effect.Values, TEXT("DynamicShadowCascades"), Cascades) ||
					    !BeautyLookNumber(Effect.Values, TEXT("CascadeDistributionExponent"), Exponent) ||
					    !BeautyLookNumber(Effect.Values, TEXT("DynamicShadowDistanceMovableLight_m"), DistanceM) ||
					    !BeautyLookNumber(Effect.Values, TEXT("ShadowDistanceFadeoutFraction"), Fade) ||
					    !BeautyLookNumber(Effect.Values, TEXT("CascadeTransitionFraction"), Transition))
					{
						return false;
					}
					Sun->SetDynamicShadowCascades(FMath::RoundToInt32(Cascades));
					Sun->SetCascadeDistributionExponent(static_cast<float>(Exponent));
					Sun->SetDynamicShadowDistanceMovableLight(static_cast<float>(DistanceM * BeautyLookCmPerMetre));
					Sun->SetShadowDistanceFadeoutFraction(static_cast<float>(Fade));
					Sun->SetCascadeTransitionFraction(static_cast<float>(Transition));
					// The per-preset cvars ride in the values ("r." keys: the
					// filter method differs under a deck) beside the row's.
					TSharedPtr<FJsonObject> PresetCvars = MakeShared<FJsonObject>();
					for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : Effect.Values->Values)
					{
						if (Entry.Key.StartsWith(TEXT("r.")))
						{
							PresetCvars->SetField(Entry.Key, Entry.Value);
						}
					}
					BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
					BeautyLookCvars(PresetCvars, Effect, TEXT("cvars_per_preset"));
				}
				Echo->SetNumberField(TEXT("DynamicShadowCascades"), Sun->DynamicShadowCascades);
				Echo->SetNumberField(TEXT("CascadeDistributionExponent"), Sun->CascadeDistributionExponent);
				Echo->SetNumberField(TEXT("DynamicShadowDistanceMovableLight_m"),
				                     Sun->DynamicShadowDistanceMovableLight / BeautyLookCmPerMetre);
				Echo->SetNumberField(TEXT("ShadowDistanceFadeoutFraction"), Sun->ShadowDistanceFadeoutFraction);
				Echo->SetNumberField(TEXT("CascadeTransitionFraction"), Sun->CascadeTransitionFraction);
				// The hero-lighting lane's disc, which PCSS widens the penumbra from.
				Echo->SetNumberField(TEXT("LightSourceAngle_deg_read_back"), Sun->LightSourceAngle);
				Echo->SetStringField(TEXT("r.Shadow.FilterMethod_read_back"), BeautyLookCvarText(TEXT("r.Shadow.FilterMethod")));
				Echo->SetStringField(TEXT("r.Shadow.Virtual.Enable_read_back"), BeautyLookCvarText(TEXT("r.Shadow.Virtual.Enable")));
			}
		}

		// 5. Distance-field shadows beyond the cascades (a probe; the project
		// builds mesh distance fields already: DefaultEngine.ini).
		if (!BeautyLookEffect(TEXT("df_shadows"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Sun == nullptr)
			{
				Echo->SetStringField(TEXT("skipped"), TEXT("the scene has no directional sun"));
			}
			else
			{
				Echo->SetBoolField(TEXT("bUseRayTracedDistanceFieldShadows_before"), Sun->bUseRayTracedDistanceFieldShadows);
				Echo->SetNumberField(TEXT("DistanceFieldShadowDistance_m_before"),
				                     Sun->DistanceFieldShadowDistance / BeautyLookCmPerMetre);
				if (Effect.bOn)
				{
					bool bUse = true;
					double DistanceM = 0.0;
					Effect.Values->TryGetBoolField(TEXT("bUseRayTracedDistanceFieldShadows"), bUse);
					if (!BeautyLookNumber(Effect.Values, TEXT("DistanceFieldShadowDistance_m"), DistanceM)) { return false; }
					Sun->SetUseRayTracedDistanceFieldShadows(bUse);
					Sun->DistanceFieldShadowDistance = static_cast<float>(DistanceM * BeautyLookCmPerMetre);
					Sun->MarkRenderStateDirty();
					Capture->ShowFlags.SetRayTracedDistanceFieldShadows(true);
					BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
				}
				else
				{
					Sun->SetUseRayTracedDistanceFieldShadows(false);
				}
				Echo->SetBoolField(TEXT("bUseRayTracedDistanceFieldShadows"), Sun->bUseRayTracedDistanceFieldShadows);
				Echo->SetNumberField(TEXT("DistanceFieldShadowDistance_m"),
				                     Sun->DistanceFieldShadowDistance / BeautyLookCmPerMetre);
				Echo->SetStringField(TEXT("casters"),
					TEXT("static meshes with a mesh distance field (the aircraft); Cesium tiles are runtime meshes with none"));
			}
		}

		// 6. Contact shadows on the sun, in screen space (replacing the
		// hero-lighting lane's world-space length on beauty).
		if (!BeautyLookEffect(TEXT("contact_shadows"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Sun == nullptr)
			{
				Echo->SetStringField(TEXT("skipped"), TEXT("the scene has no directional sun"));
			}
			else
			{
				Echo->SetNumberField(TEXT("ContactShadowLength_before"), Sun->ContactShadowLength);
				Echo->SetBoolField(TEXT("ContactShadowLengthInWS_before"), Sun->ContactShadowLengthInWS != 0);
				if (Effect.bOn)
				{
					double Length = 0.0, Casting = 0.0, NonCasting = 0.0;
					bool bWorld = false;
					if (!BeautyLookNumber(Effect.Values, TEXT("ContactShadowLength"), Length) ||
					    !BeautyLookNumber(Effect.Values, TEXT("ContactShadowCastingIntensity"), Casting) ||
					    !BeautyLookNumber(Effect.Values, TEXT("ContactShadowNonCastingIntensity"), NonCasting))
					{
						return false;
					}
					Effect.Values->TryGetBoolField(TEXT("ContactShadowLengthInWS"), bWorld);
					Sun->ContactShadowLength = static_cast<float>(Length);
					Sun->ContactShadowLengthInWS = bWorld;
					Sun->ContactShadowCastingIntensity = static_cast<float>(Casting);
					Sun->ContactShadowNonCastingIntensity = static_cast<float>(NonCasting);
					Sun->MarkRenderStateDirty();
					Capture->ShowFlags.SetContactShadows(true);
					BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
				}
				Echo->SetNumberField(TEXT("ContactShadowLength"), Sun->ContactShadowLength);
				Echo->SetBoolField(TEXT("ContactShadowLengthInWS"), Sun->ContactShadowLengthInWS != 0);
				Echo->SetNumberField(TEXT("ContactShadowCastingIntensity"), Sun->ContactShadowCastingIntensity);
				Echo->SetNumberField(TEXT("ContactShadowNonCastingIntensity"), Sun->ContactShadowNonCastingIntensity);
			}
		}

		// 7. Bloom: Gaussian (BM_SOG), or the FFT convolution probe with the
		// engine's default kernel (SceneRendering.cpp loads
		// GEngine->DefaultBloomKernelTexture when the texture is null).
		FBeautyLookEffect Fft;
		if (!BeautyLookEffect(TEXT("bloom"), bConstrained, Effect)) { return false; }
		if (!BeautyLookEffect(TEXT("bloom_fft"), bConstrained, Fft)) { return false; }
		{
			Echo = Effect.Record;
			Settings.bOverride_BloomMethod = true;
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, BloomIntensity)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, BloomThreshold)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, BloomSizeScale)
				Capture->ShowFlags.SetBloom(true);
				if (Fft.bOn)
				{
					Settings.BloomMethod = EBloomMethod::BM_FFT;
					Echo = Fft.Record;
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionSize)
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionScatterDispersion)
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionPreFilterMin)
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionPreFilterMax)
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionPreFilterMult)
					FLIGHTSIM_BEAUTY_FLOAT(Fft.Values, BloomConvolutionBufferScale)
					Echo->SetStringField(TEXT("kernel"),
						TEXT("engine default: BloomConvolutionTexture left null, so the renderer loads ")
						TEXT("GEngine->DefaultBloomKernelTexture (/Engine/EngineMaterials/DefaultBloomKernel)"));
					Echo = Effect.Record;
				}
				else
				{
					Settings.BloomMethod = EBloomMethod::BM_SOG;
				}
			}
			else
			{
				Settings.BloomMethod = EBloomMethod::BM_SOG;
				Settings.bOverride_BloomIntensity = true;
				Settings.BloomIntensity = 0.0f;
				Capture->ShowFlags.SetBloom(false);
				Echo->SetNumberField(TEXT("BloomIntensity"), 0.0);
				Fft.Record->SetStringField(TEXT("applied"), TEXT("no: bloom is off"));
			}
			Echo->SetStringField(TEXT("BloomMethod"), Settings.BloomMethod == EBloomMethod::BM_FFT ? TEXT("BM_FFT") : TEXT("BM_SOG"));
		}

		// 8. The lens flare: low, a high threshold, and drawn only with the sun
		// in or just outside the frame (the gate runs on the first frame,
		// UpdatePerFrame, from the camera axis and the sun's direction).
		if (!BeautyLookEffect(TEXT("lens_flare"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			State.bFlareGate = false;
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, LensFlareIntensity)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, LensFlareThreshold)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, LensFlareBokehSize)
				if (!BeautyLookNumber(Effect.Values, TEXT("sun_in_frame_margin_deg"), State.FlareMarginDeg)) { return false; }
				State.bFlareGate = true;
				Capture->ShowFlags.SetLensFlares(true);
				BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
				Echo->SetStringField(TEXT("gate"),
					TEXT("pending: decided on the first frame from the angle between the camera axis and the sun ")
					TEXT("against the frame's half-diagonal plus sun_in_frame_margin_deg, then held for the clip"));
				Echo->SetStringField(TEXT("bokeh_shape"),
					TEXT("engine default (LensFlareBokehShape null: PostProcessLensFlares.cpp keeps its own shape); ")
					TEXT("a hexagonal iris texture is a later import"));
			}
			else
			{
				Settings.bOverride_LensFlareIntensity = true;
				Settings.LensFlareIntensity = 0.0f;
				Capture->ShowFlags.SetLensFlares(false);
				Echo->SetNumberField(TEXT("LensFlareIntensity"), 0.0);
			}
		}

		// 9. Film grain: the engine's grain texture (SceneRendering.cpp loads
		// GEngine->DefaultFilmGrainTexture when FilmGrainTexture is null) at
		// GRAIN_STRENGTH x the preset's and the film stock's scales.
		if (!BeautyLookEffect(TEXT("film_grain"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Effect.bOn)
			{
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainIntensity)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainIntensityShadows)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainIntensityMidtones)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainIntensityHighlights)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainShadowsMax)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainHighlightsMin)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainHighlightsMax)
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, FilmGrainTexelSize)
				double GrainStrength = 0.0, StockScale = 0.0, GrainScale = 0.0;
				Effect.Values->TryGetNumberField(TEXT("GrainStrength"), GrainStrength);
				Effect.Values->TryGetNumberField(TEXT("stock_scale"), StockScale);
				Effect.Values->TryGetNumberField(TEXT("grain_scale"), GrainScale);
				Echo->SetNumberField(TEXT("GrainStrength"), GrainStrength);
				Echo->SetNumberField(TEXT("grain_scale"), GrainScale);
				Echo->SetNumberField(TEXT("stock_scale"), StockScale);
				Echo->SetStringField(TEXT("texture"),
					TEXT("engine default (FilmGrainTexture null: GEngine->DefaultFilmGrainTexture, BaseEngine.ini ")
					TEXT("DefaultFilmGrainTextureName)"));
				Capture->ShowFlags.SetGrain(true);
				BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
			}
			else
			{
				Settings.bOverride_FilmGrainIntensity = true;
				Settings.FilmGrainIntensity = 0.0f;
				Capture->ShowFlags.SetGrain(false);
				Echo->SetNumberField(TEXT("FilmGrainIntensity"), 0.0);
			}
		}

		// 10. The volumetric fog's albedo per weather; the world lane's
		// distribution, extinction and distance and the hero-lighting lane's
		// sun scattering are read back, never set.
		if (!BeautyLookEffect(TEXT("volumetric_fog"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			UWorld* World = Capture->GetWorld();
			TArray<TSharedPtr<FJsonValue>> Rows;
			FColor Albedo = FColor::White;
			if (Effect.bOn)
			{
				const TArray<TSharedPtr<FJsonValue>>* Rgb = nullptr;
				if (!Effect.Values->TryGetArrayField(TEXT("VolumetricFogAlbedo_srgb8"), Rgb) || Rgb == nullptr || Rgb->Num() != 3)
				{
					return BeautyLookFail(TEXT("engine_look.volumetric_fog VolumetricFogAlbedo_srgb8 is not three numbers"));
				}
				double C[3] = {255.0, 255.0, 255.0};
				for (int32 Index = 0; Index < 3; ++Index)
				{
					if (!(*Rgb)[Index].IsValid() || !(*Rgb)[Index]->TryGetNumber(C[Index]))
					{
						return BeautyLookFail(TEXT("engine_look.volumetric_fog VolumetricFogAlbedo_srgb8 is not three numbers"));
					}
				}
				Albedo = FColor(static_cast<uint8>(FMath::Clamp(FMath::RoundToInt32(C[0]), 0, 255)),
				                static_cast<uint8>(FMath::Clamp(FMath::RoundToInt32(C[1]), 0, 255)),
				                static_cast<uint8>(FMath::Clamp(FMath::RoundToInt32(C[2]), 0, 255)), 255);
				BeautyLookCvars(Effect.Cvars, Effect, TEXT("cvars"));
			}
			for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
			{
				UExponentialHeightFogComponent* Fog = *It;
				if (Fog == nullptr || World == nullptr || Fog->GetWorld() != World || !Fog->IsVisible())
				{
					continue;
				}
				TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
				Row->SetStringField(TEXT("albedo_before"), Fog->VolumetricFogAlbedo.ToString());
				if (Effect.bOn)
				{
					Fog->SetVolumetricFogAlbedo(Albedo);
					Fog->MarkRenderStateDirty();
				}
				Row->SetStringField(TEXT("VolumetricFogAlbedo"), Fog->VolumetricFogAlbedo.ToString());
				Row->SetBoolField(TEXT("volumetric_fog"), Fog->bEnableVolumetricFog);
				Row->SetNumberField(TEXT("scattering_distribution_read_back"), Fog->VolumetricFogScatteringDistribution);
				Row->SetNumberField(TEXT("extinction_scale_read_back"), Fog->VolumetricFogExtinctionScale);
				Row->SetNumberField(TEXT("distance_m_read_back"), Fog->VolumetricFogDistance / BeautyLookCmPerMetre);
				Rows.Add(MakeShared<FJsonValueObject>(Row));
			}
			Echo->SetArrayField(TEXT("fog_components"), Rows);
			if (Sun != nullptr)
			{
				Echo->SetNumberField(TEXT("sun_volumetric_scattering_intensity_read_back"), Sun->VolumetricScatteringIntensity);
			}
			Echo->SetStringField(TEXT("owners"),
				TEXT("distribution, extinction and distance: the world lane's row (core/scene/world_beauty.py, incl. the ")
				TEXT("wet rows' extinction scaling); the sun's scattering: the hero-lighting lane; read back here"));
		}

		// 11. The volumetric fog grid: the fine grid (on) or the engine's (off).
		if (!BeautyLookEffect(TEXT("fog_grid"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			BeautyLookCvars(Effect.bOn ? Effect.Cvars : Effect.CvarsOff, Effect, TEXT("cvars"));
			Echo->SetStringField(TEXT("basis"),
				TEXT("per fog voxel, not per cloud-march step; the fine grid is what every passing round rendered with"));
		}

		// 12. Stills: the TSR warm-up and accumulation the commandlet raises
		// its defaults to (StillAccumulation).
		if (!BeautyLookEffect(TEXT("tsr"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			State.bTsr = false;
			if (Effect.bOn)
			{
				double Warmup = 0.0, Samples = 0.0;
				if (!BeautyLookNumber(Effect.Values, TEXT("warmup_captures"), Warmup) ||
				    !BeautyLookNumber(Effect.Values, TEXT("still_samples"), Samples))
				{
					return false;
				}
				State.bTsr = true;
				State.TsrWarmup = FMath::Max(FMath::RoundToInt32(Warmup), 2);
				State.TsrStillSamples = FMath::Max(FMath::RoundToInt32(Samples), 1);
				Echo->SetNumberField(TEXT("warmup_captures"), State.TsrWarmup);
				Echo->SetNumberField(TEXT("still_samples"), State.TsrStillSamples);
				Echo->SetStringField(TEXT("applied_by"),
					TEXT("the commandlet raises its warm-up and still-sample defaults to these (a stated -warmup= or ")
					TEXT("-still-samples= wins); render_settings records the counts it ran"));
			}
			Echo->SetStringField(TEXT("r.TSR.History.ScreenPercentage_read_back"), BeautyLookCvarText(TEXT("r.TSR.History.ScreenPercentage")));
			Echo->SetStringField(TEXT("r.TSR.History.SampleCount_read_back"), BeautyLookCvarText(TEXT("r.TSR.History.SampleCount")));
			Echo->SetStringField(TEXT("internal_resolution"),
				TEXT("unchanged: the render-path lane's supersample cap stands (at most 1920 x 1080 internal on the constrained GPU)"));
		}

		// 13. The filmback: full-frame 36 x 24 mm, no squeeze; the 16:9 frame
		// uses 20.25 mm of the height.
		if (!BeautyLookEffect(TEXT("filmback"), bConstrained, Effect)) { return false; }
		{
			Echo = Effect.Record;
			if (Effect.bOn)
			{
				double WidthMm = 0.0, HeightMm = 0.0;
				if (!BeautyLookNumber(Effect.Values, TEXT("sensor_width_mm"), WidthMm) ||
				    !BeautyLookNumber(Effect.Values, TEXT("sensor_height_mm"), HeightMm))
				{
					return false;
				}
				FLIGHTSIM_BEAUTY_FLOAT(Effect.Values, DepthOfFieldSqueezeFactor)
				Echo->SetNumberField(TEXT("sensor_width_mm"), WidthMm);
				Echo->SetNumberField(TEXT("sensor_height_mm"), HeightMm);
				// The camera row owns the width the focal length is derived from
				// (the card's per-camera sensor); a full-frame plan states 36.
				Echo->SetNumberField(TEXT("DepthOfFieldSensorWidth_read_back"), Settings.DepthOfFieldSensorWidth);
				if (Capture->TextureTarget != nullptr && Capture->TextureTarget->SizeX > 0 && Capture->TextureTarget->SizeY > 0)
				{
					const double Aspect = static_cast<double>(Capture->TextureTarget->SizeX) / Capture->TextureTarget->SizeY;
					Echo->SetNumberField(TEXT("sensor_height_used_mm"), Settings.DepthOfFieldSensorWidth / Aspect);
				}
				Echo->SetStringField(TEXT("crop"),
					TEXT("the frame's aspect crops the 3:2 sensor top and bottom; the FOV is the pose solver's, unchanged"));
			}
		}

		State.bEngineLate = true;
		State.EngineApplied->SetStringField(TEXT("late_half"), TEXT("applied"));
		State.EngineApplied->SetBoolField(TEXT("constrained_gpu"), bConstrained);
		State.EngineApplied->SetStringField(TEXT("labels"),
			TEXT("beauty capture and its lights only: label captures are separate captures of the same frame ")
			TEXT("(lighting and post never reach stencil, depth or the GBuffer)"));
		return true;
	}

#undef FLIGHTSIM_BEAUTY_FLOAT
#undef FLIGHTSIM_BEAUTY_VECTOR
}

bool FFlightSimBeautyLook::ApplyEngineLook(FFlightSimVisualScene& Scene, USceneCaptureComponent2D* Beauty,
                                           bool bConstrainedGpu, const TCHAR* Switches)
{
	FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied || Beauty == nullptr || !State.EngineLook.IsValid() || !State.EngineApplied.IsValid())
	{
		return true;   // no sidecar: exactly the beauty capture the earlier lanes built
	}
	State.bConstrained = bConstrainedGpu;
	// The commandlet's switch text (its params plus FLIGHTSIM_RENDER_SWITCHES)
	// replaces the process command line read in Apply: the same tokens, plus
	// anything a wrapper appended.
	if (Switches != nullptr && *Switches != 0)
	{
		State.SwitchText = FString(Switches) + TEXT(" ") + State.SwitchText;
	}
	if (!BeautyLookApplyEngineLook(Scene, Beauty))
	{
		return false;
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("engine look: applied (constrained gpu %s); switches from -look-<name>= and FLIGHTSIM_RENDER_SWITCHES"),
	       bConstrainedGpu ? TEXT("yes") : TEXT("no"));
	return true;
}

bool FFlightSimBeautyLook::StillAccumulation(int32& WarmupCaptures, int32& StillSamples)
{
	const FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied || !State.bEngineLate || !State.bTsr)
	{
		return false;
	}
	WarmupCaptures = State.TsrWarmup;
	StillSamples = State.TsrStillSamples;
	return true;
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
	// Round 5 L1: the lens-flare gate, decided ONCE on the first frame (the
	// first solved pose) and held, so a clip never flickers at the boundary.
	// The flare is kept when the direction to the sun lies within the frame's
	// half-diagonal field of view plus the plan's margin (the sun in, or just
	// outside, the frame: #05's backlit haze); otherwise the intensity is 0
	// and the show flag off (#04, sun behind the camera, draws none).
	if (State.bFlareGate && !State.bFlareDecided)
	{
		State.bFlareDecided = true;
		TSharedPtr<FJsonObject> Gate = MakeShared<FJsonObject>();
		UDirectionalLightComponent* Sun = BeautyLookFindSun(Capture);
		if (Sun == nullptr)
		{
			Gate->SetStringField(TEXT("decision"), TEXT("kept: no atmosphere sun light to measure against"));
		}
		else
		{
			// ULightComponent::GetDirection is the light's travel direction;
			// the sun lies the other way.
			const FVector ToSun = -Sun->GetDirection();
			const FVector Axis = Capture->GetForwardVector();
			const double AngleDeg = FMath::RadiansToDegrees(
				FMath::Acos(FMath::Clamp(FVector::DotProduct(Axis.GetSafeNormal(), ToSun.GetSafeNormal()), -1.0, 1.0)));
			double Aspect = 16.0 / 9.0;
			if (Capture->TextureTarget != nullptr && Capture->TextureTarget->SizeX > 0 && Capture->TextureTarget->SizeY > 0)
			{
				Aspect = static_cast<double>(Capture->TextureTarget->SizeX) / Capture->TextureTarget->SizeY;
			}
			const double HalfHorizontal = FMath::DegreesToRadians(static_cast<double>(Capture->FOVAngle)) * 0.5;
			const double HalfDiagonalDeg = FMath::RadiansToDegrees(
				FMath::Atan(FMath::Tan(HalfHorizontal) * FMath::Sqrt(1.0 + 1.0 / (Aspect * Aspect))));
			const bool bDraw = AngleDeg <= HalfDiagonalDeg + State.FlareMarginDeg;
			if (!bDraw)
			{
				Capture->PostProcessSettings.bOverride_LensFlareIntensity = true;
				Capture->PostProcessSettings.LensFlareIntensity = 0.0f;
				Capture->ShowFlags.SetLensFlares(false);
			}
			Gate->SetNumberField(TEXT("sun_angle_from_axis_deg"), AngleDeg);
			Gate->SetNumberField(TEXT("half_diagonal_fov_deg"), HalfDiagonalDeg);
			Gate->SetNumberField(TEXT("margin_deg"), State.FlareMarginDeg);
			Gate->SetBoolField(TEXT("drawn"), bDraw);
			Gate->SetStringField(TEXT("decision"), bDraw
				? TEXT("kept: the sun is in or just outside the frame")
				: TEXT("off for the clip: the sun is away from the frame (LensFlareIntensity 0, LensFlares show flag off)"));
		}
		Gate->SetNumberField(TEXT("LensFlareIntensity"), Capture->PostProcessSettings.LensFlareIntensity);
		const TSharedPtr<FJsonObject>* Flare = nullptr;
		if (State.EngineApplied.IsValid() && State.EngineApplied->TryGetObjectField(TEXT("lens_flare"), Flare) &&
		    Flare != nullptr && Flare->IsValid())
		{
			(*Flare)->SetObjectField(TEXT("gate"), Gate);
		}
	}
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

void FFlightSimBeautyLook::ApplyShutterPolicy(USceneCaptureComponent2D* Capture, bool bStill)
{
	if (Capture == nullptr)
	{
		return;
	}
	FBeautyLookState& State = BeautyLookState();
	if (bStill)
	{
		// The owner's round-1 verdict: the jet in a still was a smeared,
		// ghosted blur. A still has no shutter interval to blur over (its
		// sub-captures are one pose at one sim time), so motion blur is off:
		// the show flag (SceneView reads it) AND the amount, so nothing
		// downstream that reads either half sees blur.
		Capture->ShowFlags.SetMotionBlur(false);
		Capture->PostProcessSettings.bOverride_MotionBlurAmount = true;
		Capture->PostProcessSettings.MotionBlurAmount = 0.0f;
	}
	if (!State.bApplied || !State.Applied.IsValid())
	{
		return;
	}
	const TSharedPtr<FJsonObject>* Camera = nullptr;
	if (State.Applied->TryGetObjectField(TEXT("camera"), Camera) && Camera != nullptr && Camera->IsValid())
	{
		(*Camera)->SetNumberField(TEXT("MotionBlurAmount"), Capture->PostProcessSettings.MotionBlurAmount);
		(*Camera)->SetBoolField(TEXT("motion_blur_show_flag"), Capture->ShowFlags.MotionBlur != 0);
		(*Camera)->SetStringField(TEXT("shutter_policy"), bStill
			? TEXT("still: motion blur OFF (one pose, one sim time; the plan's 180-degree shutter is for clips)")
			: TEXT("clip: the plan's 180-degree shutter (MotionBlurAmount over MotionBlurTargetFPS)"));
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

bool FFlightSimBeautyLook::ExposureMeter(double& TargetP90, FString& Trigger)
{
	const FBeautyLookState& State = BeautyLookState();
	if (!State.bApplied || !State.bExposureApplied || !State.bMeter)
	{
		return false;
	}
	TargetP90 = State.MeterTargetP90;
	Trigger = State.MeterTrigger;
	return true;
}

const FString& FFlightSimBeautyLook::LastError()
{
	return BeautyLookState().Error;
}
