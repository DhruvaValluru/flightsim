#include "FlightSimInteractiveMode.h"

#include "FlightSimInteractiveHUD.h"
#include "FlightSimTelemetryRecorder.h"
#include "JSBSimMovementComponent.h"

#include "CineCameraComponent.h"
#include "Components/InputComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UnrealClient.h"

AFlightSimInteractiveMode::AFlightSimInteractiveMode()
{
	PrimaryActorTick.bCanEverTick = true;
	// No pawn: the viewer watches through the camera director, exactly like
	// the render commandlet's capture. Flying by keyboard is the 8C stretch
	// goal and arrives with its own human-in-loop recorder labeling.
	DefaultPawnClass = nullptr;
	bStartPlayersAsSpectators = true;
	HUDClass = AFlightSimInteractiveHUD::StaticClass();
}

void AFlightSimInteractiveMode::StartPlay()
{
	Super::StartPlay();

	// DefaultEngine.ini pins bUseFixedFrameRate=120 so the OFFLINE hosts'
	// engine-driven ticking is reproducible. In a window that setting would
	// stretch or shrink sim time against the wall clock silently -- the
	// interactive host's fixed 1/120 comes from its OWN substep accumulator
	// below, never from pinning frame deltas. Runtime override; the config
	// value (and both commandlet hosts) stay untouched.
	if (GEngine != nullptr && GEngine->bUseFixedFrameRate)
	{
		GEngine->bUseFixedFrameRate = false;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("interactive: fixed frame rate disabled for windowed ")
		       TEXT("play; the FDM substep clock is the wall clock"));
	}

	FString Error;
	if (!SetupScenario(Error))
	{
		FailAndQuit(Error);
		return;
	}
	bRunning = true;
}

bool AFlightSimInteractiveMode::SetupScenario(FString& Error)
{
	const TCHAR* CommandLine = FCommandLine::Get();

	FString CardPath;
	if (!FParse::Value(CommandLine, TEXT("card="), CardPath))
	{
		Error = TEXT("usage: -game -card=<run-card.json> [-imagery=<sidecar>] ")
		        TEXT("[-camera=chase|wingman|tower|shoulder] ")
		        TEXT("[-telemetry=<out.json>] [-manifest=<out.json>] ")
		        TEXT("[-screenshot-at=a:b:c -screenshot-dir=<dir>] ")
		        TEXT("[-probe-seconds=N -report=<out.json>]");
		return false;
	}
	FParse::Value(CommandLine, TEXT("probe-seconds="), ProbeSeconds);
	FParse::Value(CommandLine, TEXT("report="), ReportPath);
	FParse::Value(CommandLine, TEXT("telemetry="), TelemetryPath);
	FParse::Value(CommandLine, TEXT("manifest="), ManifestPath);
	FParse::Value(CommandLine, TEXT("screenshot-dir="), ScreenshotDirectory);
	FString ScreenshotSpec;
	FParse::Value(CommandLine, TEXT("screenshot-at="), ScreenshotSpec);
	if (!ScreenshotSpec.IsEmpty())
	{
		TArray<FString> Parts;
		// Colon-separated: FParse::Value stops at a comma (measured on the
		// render commandlet's -chase argument).
		ScreenshotSpec.ParseIntoArray(Parts, TEXT(":"));
		for (const FString& Part : Parts)
		{
			ScreenshotAtSeconds.Add(FCString::Atod(*Part));
		}
		ScreenshotAtSeconds.Sort();
	}

	if (!FFlightSimScenarioWorld::ReadCard(CardPath, Card, Error))
	{
		return false;
	}
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("interactive: scenario %s -- %s at %.1f m / %.1f kt, %.1f s"),
	       *Card.SpecDigest, *Card.Aircraft, Card.AltitudeMetres,
	       Card.AirspeedKnots, Card.DurationSeconds);

	// Same population, trim and verification ladder as the commandlets, in
	// the engine's live world.
	if (!Scenario.BuildInto(GetWorld(), Card, Error)) { return false; }
	if (!Scenario.TrimInWind(Card, Error)) { return false; }
	if (!Scenario.VerifyTrimmedCondition(Card, Error)) { return false; }
	Scenario.LatchTrimmedControls(Card.bMassHeld);
	Scenario.ConfigureTurbulence(Card);

	// The same recorder the telemetry commandlet uses, stamping the FDM's
	// own clock -- the replay comparison runs on that recorded clock.
	if (!TelemetryPath.IsEmpty())
	{
		Recorder = NewObject<UFlightSimTelemetryRecorder>(Scenario.Aircraft,
		                                                  TEXT("Recorder"));
		Recorder->Movement = Scenario.Movement;
		Recorder->SampleIntervalSeconds =
			static_cast<float>(Card.SampleIntervalSeconds);
		Recorder->RegisterComponent();
		// hazard 1: a channel property missing from this model refuses the
		// session loudly, never records NaN forever.
		if (!Recorder->SelftestProperties(Error)) { return false; }
		Recorder->StartRecording(TelemetryPath);
	}

	// -- visuals -----------------------------------------------------------
	FString TerrainPath = !Card.CollisionTerrainPath.IsEmpty()
		? Card.CollisionTerrainPath : Card.OrographicTerrainPath;
	FParse::Value(CommandLine, TEXT("terrain="), TerrainPath);
	if (!TerrainPath.IsEmpty())
	{
		FFlightSimVisualSceneOptions SceneOptions;
		SceneOptions.TerrainPath = TerrainPath;
		SceneOptions.bGeoreferenced = true;
		SceneOptions.GeoReferencing = Scenario.GeoReferencing;
		SceneOptions.bClassifiedMaterial = true;
		FParse::Value(CommandLine, TEXT("imagery="),
		              SceneOptions.ImagerySidecarPath);
		double FogDensity = 0.0012;   // showcase clear-day value
		FParse::Value(CommandLine, TEXT("fog-density="), FogDensity);
		SceneOptions.FogDensity = static_cast<float>(FogDensity);
		// Time of day as a parameter, same convention as the render
		// commandlet: pitch is -elevation, yaw the direction light travels.
		double SunElevationDeg = 35.0, SunAzimuthDeg = 160.0;
		FParse::Value(CommandLine, TEXT("sun-elev="), SunElevationDeg);
		FParse::Value(CommandLine, TEXT("sun-azim="), SunAzimuthDeg);
		SceneOptions.SunRotation =
			FRotator(-SunElevationDeg, SunAzimuthDeg + 180.0, 0.0);
		if (!Visual.Build(GetWorld(), SceneOptions, Error))
		{
			return false;
		}
	}

	// Placeholder airframe so the camera has a subject: one box, the Gate 5
	// stand-in. The converted mesh + surface animators join later; every
	// artifact this session writes records the airframe as placeholder so
	// nobody reads the session as covering the real mesh.
	if (UStaticMesh* Cube = LoadObject<UStaticMesh>(
	        nullptr, TEXT("/Engine/BasicShapes/Cube.Cube")))
	{
		UStaticMeshComponent* Body = NewObject<UStaticMeshComponent>(
			Scenario.Aircraft, TEXT("PlaceholderBody"));
		Body->SetStaticMesh(Cube);
		Body->SetRelativeScale3D(FVector(30.0, 3.0, 3.0));   // ~30 m fuselage
		Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Body->AttachToComponent(Scenario.Aircraft->GetRootComponent(),
		                        FAttachmentTransformRules::KeepRelativeTransform);
		Body->RegisterComponent();
	}

	// -- camera ------------------------------------------------------------
	CameraDirector = GetWorld()->SpawnActor<AFlightSimCameraDirector>();
	CameraDirector->Target = Scenario.Aircraft;
	CameraDirector->Preset = EFlightSimCameraPreset::LaggedChase;
	FParse::Value(CommandLine, TEXT("camera="), CameraPresetName);
	if (CameraPresetName == TEXT("wingman"))
	{
		CameraDirector->Preset = EFlightSimCameraPreset::Wingman;
	}
	else if (CameraPresetName == TEXT("tower"))
	{
		CameraDirector->Preset = EFlightSimCameraPreset::Tower;
	}
	else if (CameraPresetName == TEXT("shoulder"))
	{
		CameraDirector->Preset = EFlightSimCameraPreset::CockpitShoulder;
	}
	else if (CameraPresetName != TEXT("chase"))
	{
		Error = FString::Printf(
			TEXT("unknown camera preset '%s' (chase|wingman|tower|shoulder)"),
			*CameraPresetName);
		return false;
	}
	CameraDirector->ChaseOffsetMetres = FVector(-170.0, 0.0, 16.0);

	// §6.6 manual exposure, on the live camera's post process rather than a
	// capture component -- the viewport camera is the camera of record here.
	double ExposureBias = 9.5;
	FParse::Value(CommandLine, TEXT("exposure-bias="), ExposureBias);
	if (CameraDirector->Camera != nullptr)
	{
		FPostProcessSettings& Post = CameraDirector->Camera->PostProcessSettings;
		Post.bOverride_AutoExposureMethod = true;
		Post.AutoExposureMethod = AEM_Manual;
		Post.bOverride_AutoExposureBias = true;
		Post.AutoExposureBias = static_cast<float>(ExposureBias);
	}

	APlayerController* Controller = GetWorld()->GetFirstPlayerController();
	if (Controller == nullptr)
	{
		Error = TEXT("no player controller; nothing would ever see the scene");
		return false;
	}
	Controller->SetViewTarget(CameraDirector);

	// Camera preset keys. The number keys mirror the -camera argument; the
	// HUD names the active preset (and its roll-inheritance) either way.
	if (Controller->InputComponent != nullptr)
	{
		Controller->InputComponent->BindKey(
			EKeys::One, IE_Pressed, this,
			&AFlightSimInteractiveMode::SelectCameraChase);
		Controller->InputComponent->BindKey(
			EKeys::Two, IE_Pressed, this,
			&AFlightSimInteractiveMode::SelectCameraWingman);
		Controller->InputComponent->BindKey(
			EKeys::Three, IE_Pressed, this,
			&AFlightSimInteractiveMode::SelectCameraTower);
		Controller->InputComponent->BindKey(
			EKeys::Four, IE_Pressed, this,
			&AFlightSimInteractiveMode::SelectCameraShoulder);
	}
	return true;
}

void AFlightSimInteractiveMode::ApplyCameraPreset(EFlightSimCameraPreset Preset,
                                                  const TCHAR* Name)
{
	if (CameraDirector != nullptr)
	{
		CameraDirector->Preset = Preset;
		CameraPresetName = Name;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("interactive: camera preset -> %s"), Name);
	}
}

void AFlightSimInteractiveMode::SelectCameraChase()
{
	ApplyCameraPreset(EFlightSimCameraPreset::LaggedChase, TEXT("chase"));
}

void AFlightSimInteractiveMode::SelectCameraWingman()
{
	ApplyCameraPreset(EFlightSimCameraPreset::Wingman, TEXT("wingman"));
}

void AFlightSimInteractiveMode::SelectCameraTower()
{
	ApplyCameraPreset(EFlightSimCameraPreset::Tower, TEXT("tower"));
}

void AFlightSimInteractiveMode::SelectCameraShoulder()
{
	ApplyCameraPreset(EFlightSimCameraPreset::CockpitShoulder, TEXT("shoulder"));
}

void AFlightSimInteractiveMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!bRunning || bFinished)
	{
		return;
	}

	// Wall delta from the platform clock, immune to any engine time
	// pinning or dilation (the fixed-frame-rate config, slomo, etc.).
	const double Now = FPlatformTime::Seconds();
	const double WallDelta =
		LastWallTime > 0.0 ? Now - LastWallTime
		                   : static_cast<double>(DeltaSeconds);
	LastWallTime = Now;

	WallSeconds += WallDelta;
	FrameSeconds.Add(static_cast<float>(WallDelta));

	// -- the fixed-substep clock ------------------------------------------
	Accumulator += WallDelta;
	if (Accumulator > CatchUpCapSeconds)
	{
		// Time dilation over dt-stretching, always: the excess is dropped
		// from the accumulator and counted, so the sim clock falls behind
		// the wall clock and JSBSim still only ever sees whole 1/120 steps.
		DeficitEvents += 1;
		DeficitSeconds += Accumulator - CatchUpCapSeconds;
		Accumulator = CatchUpCapSeconds;
		LastCapWallTime = Now;
	}
	FString Error;
	while (Accumulator >= SubstepSeconds)
	{
		Scenario.ApplyStepWrites(Card, SimTimeSeconds);
		// One whole fixed step through the ONE stepping path. The component
		// pins JSBSim's dt at 1/120 internally; handing it exactly one
		// substep of wall time makes its loop run exactly once.
		Scenario.Movement->TickComponent(
			static_cast<float>(SubstepSeconds), LEVELTICK_All, nullptr);
		SimTimeSeconds += SubstepSeconds;
		Accumulator -= SubstepSeconds;
		++SubstepCount;
		if (Scenario.Crashed(SimTimeSeconds, Error)
		    || Scenario.AirframeImpact(SimTimeSeconds, Error))
		{
			FailAndQuit(Error);
			return;
		}
	}

	// -- scheduled with-UI screenshots (Gate 8.2 on-screen clauses) -------
	if (NextScreenshotIndex < ScreenshotAtSeconds.Num()
	    && WallSeconds >= ScreenshotAtSeconds[NextScreenshotIndex])
	{
		const FString Directory = ScreenshotDirectory.IsEmpty()
			? FPaths::ProjectSavedDir() / TEXT("Screenshots")
			: ScreenshotDirectory;
		const FString Name = Directory / FString::Printf(
			TEXT("interactive_%02d.png"), NextScreenshotIndex);
		FScreenshotRequest::RequestScreenshot(Name, /*bInShowUI=*/true,
		                                      /*bAddFilenameSuffix=*/false);
		++NextScreenshotIndex;
	}

	if (ProbeSeconds > 0.0 && WallSeconds >= ProbeSeconds)
	{
		FinishAndQuit(TEXT("probe complete"));
	}
	else if (ProbeSeconds <= 0.0 && SimTimeSeconds >= Card.DurationSeconds)
	{
		FinishAndQuit(TEXT("scenario complete"));
	}
}

TArray<FFlightSimHudLine> AFlightSimInteractiveMode::HudLines() const
{
	TArray<FFlightSimHudLine> Lines;
	if (!bRunning || Scenario.Movement == nullptr)
	{
		return Lines;
	}
	const FLinearColor Grey(0.75f, 0.78f, 0.80f);
	const FLinearColor Green(0.45f, 0.85f, 0.50f);
	const FLinearColor Yellow(0.95f, 0.80f, 0.25f);

	auto Read = [this](const TCHAR* Name) -> double
	{
		return Scenario.ReadProperty(Name);
	};

	// Commanded vs achieved -- the panel's first row, live.
	const double AltitudeM = Read(TEXT("position/h-sl-meters"));
	const double CasKt = Read(TEXT("velocities/vc-kts"));
	const double HeadingDeg = Read(TEXT("attitude/psi-deg"));
	const double AglM = Read(TEXT("position/h-agl-ft")) * 0.3048;
	Lines.Add({FString::Printf(
		TEXT("%s  |  alt %6.0f m (cmd %6.0f)  cas %5.1f kt (cmd %5.1f)  ")
		TEXT("hdg %5.1f (cmd %5.1f)  agl %6.0f m"),
		*Card.Aircraft, AltitudeM, Card.AltitudeMetres, CasKt,
		Card.AirspeedKnots, HeadingDeg, Card.HeadingDegrees, AglM), Grey});

	// The wind actually inside the FDM, not the wind anyone asked for.
	const double WindNorth = Read(TEXT("atmosphere/wind-north-fps"));
	const double WindEast = Read(TEXT("atmosphere/wind-east-fps"));
	const double WindDown = Read(TEXT("atmosphere/wind-down-fps"));
	Lines.Add({FString::Printf(
		TEXT("wind in FDM (NED fps): %+7.2f %+7.2f %+7.2f"),
		WindNorth, WindEast, WindDown), Grey});

	// The aero block: what the air is doing TO the aircraft -- the FDM's own
	// aerodynamic state (JSBSim is coefficient tables, not CFD; no flow
	// field exists and none is claimed). Same live property reads as every
	// line here, display-only -- the recorder stays the evidence path.
	// Lift/drag are the FDM's OWN wind-axis force outputs
	// (forces/fw{z,x}-aero-lbs), not a transform done on screen.
	const double AlphaDeg = Read(TEXT("aero/alpha-deg"));
	const double BetaDeg = Read(TEXT("aero/beta-deg"));
	const double QbarPa = Read(TEXT("aero/qbar-psf")) * 47.880259;
	const double LiftKn = Read(TEXT("forces/fwz-aero-lbs")) * 4.4482216153e-3;
	const double DragKn = Read(TEXT("forces/fwx-aero-lbs")) * 4.4482216153e-3;
	const double LoadG = Read(TEXT("accelerations/Nz"));
	Lines.Add({FString::Printf(
		TEXT("aero (FDM state): alpha %+6.2f deg  beta %+6.2f deg  ")
		TEXT("qbar %6.0f Pa  lift %8.1f kN  drag %7.1f kN  n_z %5.2f g"),
		AlphaDeg, BetaDeg, QbarPa, LiftKn, DragKn, LoadG), Grey});
	if (Card.ReferenceVsKnots > 0.0)
	{
		// Stall margin against THIS model's measured Vs (§2.4): the basis
		// travels on the card so the provenance is on screen, and a card
		// without the block shows nothing rather than a generic number.
		const double MarginKt = CasKt - Card.ReferenceVsKnots;
		Lines.Add({FString::Printf(
			TEXT("stall margin: cas %5.1f kt vs Vs %5.1f kt (%+5.1f kt) -- %s"),
			CasKt, Card.ReferenceVsKnots, MarginKt, *Card.ReferenceBasis),
			MarginKt < 0.15 * Card.ReferenceVsKnots ? Yellow : Grey});
	}

	// Honesty labels: turbulence seed + verdict, physics ground, camera.
	if (Card.Turbulence != TEXT("none"))
	{
		Lines.Add({FString::Printf(
			TEXT("turbulence '%s' seed %lld -- VISUAL-ONLY (measured: ")
			TEXT("same-seed realisations differ between hosts)"),
			*Card.Turbulence, Card.TurbulenceSeed), Yellow});
	}
	Lines.Add({Card.CollisionTerrainPath.IsEmpty()
		? FString::Printf(TEXT("physics ground: flat slab at %.1f m ")
		                  TEXT("(visual terrain is scenery)"),
		                  Card.TerrainElevationMetres)
		: FString(TEXT("physics ground: heightfield raster ")
		          TEXT("(AGL parity measured)")), Grey});
	const bool bInheritsRoll = CameraDirector != nullptr
		&& !CameraDirector->PresetKeepsHorizonLevel();
	Lines.Add({FString::Printf(
		TEXT("camera [1-4]: %s%s"), *CameraPresetName,
		bInheritsRoll
			? TEXT("  -- INHERITS ROLL: the world banks, not the aircraft")
			: TEXT("  (horizon-stable; roll on screen is aircraft roll)")),
		bInheritsRoll ? Yellow : Grey});

	// The substep ledger, with RUNNING BEHIND as an explicit state.
	const bool bRecentCap =
		LastCapWallTime > 0.0
		&& FPlatformTime::Seconds() - LastCapWallTime < 2.0;
	Lines.Add({FString::Printf(
		TEXT("sim t %7.2f s  wall %7.2f s  substeps %llu @ %.0f Hz  ")
		TEXT("behind %+.3f s (%llu caps)%s"),
		SimTimeSeconds, WallSeconds, SubstepCount, 1.0 / SubstepSeconds,
		DeficitSeconds, DeficitEvents,
		bRecentCap ? TEXT("  << SIM RUNNING BEHIND") : TEXT("")),
		(bRecentCap || DeficitSeconds > 0.0) ? Yellow : Green});
	return Lines;
}

void AFlightSimInteractiveMode::WriteProbeReport(const FString& Outcome)
{
	if (ReportPath.IsEmpty() || FrameSeconds.Num() == 0)
	{
		return;
	}
	TArray<float> Sorted = FrameSeconds;
	Sorted.Sort();
	auto Percentile = [&Sorted](double P) -> double
	{
		const int32 Index = FMath::Clamp(
			static_cast<int32>(P * (Sorted.Num() - 1)), 0, Sorted.Num() - 1);
		return static_cast<double>(Sorted[Index]);
	};
	double Sum = 0.0;
	for (const float Dt : FrameSeconds) { Sum += Dt; }

	TSharedPtr<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetStringField(TEXT("outcome"), Outcome);
	Report->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
	Report->SetStringField(TEXT("aircraft"), Card.Aircraft);
	Report->SetStringField(TEXT("camera_preset"), CameraPresetName);
	Report->SetNumberField(TEXT("frames"), FrameSeconds.Num());
	Report->SetNumberField(TEXT("wall_seconds"), WallSeconds);
	Report->SetNumberField(TEXT("fps_mean"),
	                       Sum > 0.0 ? FrameSeconds.Num() / Sum : 0.0);
	Report->SetNumberField(TEXT("frame_ms_p50"), Percentile(0.50) * 1000.0);
	Report->SetNumberField(TEXT("frame_ms_p95"), Percentile(0.95) * 1000.0);
	Report->SetNumberField(TEXT("frame_ms_max"),
	                       static_cast<double>(Sorted.Last()) * 1000.0);
	Report->SetNumberField(TEXT("sim_seconds"), SimTimeSeconds);
	Report->SetNumberField(TEXT("substeps"), static_cast<double>(SubstepCount));
	Report->SetNumberField(TEXT("substep_rate_hz"), 1.0 / SubstepSeconds);
	Report->SetNumberField(TEXT("deficit_events"),
	                       static_cast<double>(DeficitEvents));
	Report->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
	Report->SetStringField(TEXT("terrain"), Visual.TerrainName);
	Report->SetStringField(TEXT("terrain_sha256"), Visual.TerrainSha256);
	Report->SetStringField(TEXT("imagery_dataset"), Visual.ImageryDataset);
	// What this number does NOT cover, stated in the artifact itself.
	Report->SetStringField(
		TEXT("airframe"),
		TEXT("placeholder box; converted-mesh cost not in this measurement"));

	FString Payload;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Payload);
	FJsonSerializer::Serialize(Report.ToSharedRef(), Writer);
	// ASCII manifests (gotcha 13): every string above is ASCII by
	// construction; the card digest, paths and dataset ids all are.
	FFileHelper::SaveStringToFile(Payload, *ReportPath);
	UE_LOG(LogFlightSimScenario, Display, TEXT("interactive report -> %s"),
	       *ReportPath);
}

void AFlightSimInteractiveMode::WriteManifest(const FString& Outcome)
{
	if (ManifestPath.IsEmpty())
	{
		return;
	}
	TSharedPtr<FJsonObject> Manifest = MakeShared<FJsonObject>();
	Manifest->SetStringField(TEXT("host"), TEXT("interactive"));
	Manifest->SetStringField(TEXT("outcome"), Outcome);
	Manifest->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
	Manifest->SetStringField(TEXT("aircraft"), Card.Aircraft);
	Manifest->SetStringField(
		TEXT("airframe_visual"),
		TEXT("placeholder box (converted mesh not yet wired in this host)"));
	Manifest->SetStringField(TEXT("camera_preset"), CameraPresetName);
	Manifest->SetBoolField(TEXT("camera_inherits_roll"),
	                       CameraDirector != nullptr
	                       && !CameraDirector->PresetKeepsHorizonLevel());
	Manifest->SetStringField(TEXT("turbulence"), Card.Turbulence);
	if (Card.Turbulence != TEXT("none"))
	{
		Manifest->SetNumberField(TEXT("turbulence_seed"),
		                         static_cast<double>(Card.TurbulenceSeed));
		Manifest->SetStringField(
			TEXT("turbulence_parity"),
			TEXT("visual-only (measured; see runs/turbulence_ue/report.json)"));
	}
	Manifest->SetStringField(
		TEXT("physics_ground"),
		Card.CollisionTerrainPath.IsEmpty()
			? TEXT("flat slab at the spec elevation")
			: TEXT("heightfield raster (AGL parity measured)"));
	Manifest->SetStringField(TEXT("terrain"), Visual.TerrainName);
	Manifest->SetStringField(TEXT("terrain_sha256"), Visual.TerrainSha256);
	Manifest->SetStringField(TEXT("imagery_dataset"), Visual.ImageryDataset);
	Manifest->SetStringField(TEXT("imagery_sha256"), Visual.ImagerySha256);
	Manifest->SetStringField(TEXT("imagery_license"), Visual.ImageryLicense);
	Manifest->SetNumberField(TEXT("sim_seconds"), SimTimeSeconds);
	Manifest->SetNumberField(TEXT("wall_seconds"), WallSeconds);
	Manifest->SetNumberField(TEXT("substeps"),
	                         static_cast<double>(SubstepCount));
	Manifest->SetNumberField(TEXT("substep_rate_hz"), 1.0 / SubstepSeconds);
	Manifest->SetNumberField(TEXT("deficit_events"),
	                         static_cast<double>(DeficitEvents));
	Manifest->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
	Manifest->SetStringField(TEXT("telemetry"), TelemetryPath);
	FString Payload;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Payload);
	FJsonSerializer::Serialize(Manifest.ToSharedRef(), Writer);
	FFileHelper::SaveStringToFile(Payload, *ManifestPath);   // ASCII only
	UE_LOG(LogFlightSimScenario, Display, TEXT("interactive manifest -> %s"),
	       *ManifestPath);
}

void AFlightSimInteractiveMode::FinishAndQuit(const FString& Outcome)
{
	if (bFinished) { return; }
	bFinished = true;
	UE_LOG(LogFlightSimScenario, Display, TEXT("interactive: %s after %.1f s ")
	       TEXT("wall / %.1f s sim, %llu substeps, behind %.3f s"),
	       *Outcome, WallSeconds, SimTimeSeconds, SubstepCount, DeficitSeconds);
	if (Recorder != nullptr && !Recorder->WriteToDisk())
	{
		UE_LOG(LogFlightSimScenario, Error,
		       TEXT("interactive: telemetry did NOT write to '%s'"),
		       *TelemetryPath);
	}
	WriteProbeReport(Outcome);
	WriteManifest(Outcome);
	if (GEngine != nullptr)
	{
		GEngine->Exec(GetWorld(), TEXT("QUIT"));
	}
}

void AFlightSimInteractiveMode::FailAndQuit(const FString& Why)
{
	if (bFinished) { return; }
	bFinished = true;
	bRunning = false;
	UE_LOG(LogFlightSimScenario, Error, TEXT("interactive: %s"), *Why);
	WriteProbeReport(FString::Printf(TEXT("FAILED: %s"), *Why));
	WriteManifest(FString::Printf(TEXT("FAILED: %s"), *Why));
	if (GEngine != nullptr)
	{
		GEngine->Exec(GetWorld(), TEXT("QUIT"));
	}
}

void AFlightSimInteractiveMode::EndPlay(const EEndPlayReason::Type Reason)
{
	Scenario.Teardown();
	Super::EndPlay(Reason);
}
