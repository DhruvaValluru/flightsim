#include "FlightSimInteractiveMode.h"

#include "FlightSimCameraDirector.h"
#include "JSBSimMovementComponent.h"

#include "CineCameraComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

AFlightSimInteractiveMode::AFlightSimInteractiveMode()
{
	PrimaryActorTick.bCanEverTick = true;
	// No pawn: the viewer watches through the camera director, exactly like
	// the render commandlet's capture. Flying by keyboard is the 8C stretch
	// goal and arrives with its own recorder labeling.
	DefaultPawnClass = nullptr;
	bStartPlayersAsSpectators = true;
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
		        TEXT("[-probe-seconds=N -report=<out.json>]");
		return false;
	}
	FParse::Value(CommandLine, TEXT("probe-seconds="), ProbeSeconds);
	FParse::Value(CommandLine, TEXT("report="), ReportPath);

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

	// -- visuals -----------------------------------------------------------
	// The full scene the probe must price: georeferenced terrain from the
	// card's raster, the imagery drape when given, sky, fog, sun.
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
	// stand-in. The converted mesh + surface animators join in 8C.1; the
	// probe report records the airframe as placeholder so nobody reads the
	// fps number as covering the real mesh.
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
	CameraDirector =
		GetWorld()->SpawnActor<AFlightSimCameraDirector>();
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
	return true;
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
		if (Scenario.Crashed(SimTimeSeconds, Error))
		{
			FailAndQuit(Error);
			return;
		}
	}

	// -- honesty line on screen -------------------------------------------
	// The full HUD is 8C.2; the probe shows the substep ledger and says when
	// the sim is running behind, because that state must never be silent.
	if (GEngine != nullptr)
	{
		const double Fps = WallDelta > 0.0 ? 1.0 / WallDelta : 0.0;
		GEngine->AddOnScreenDebugMessage(
			0, 0.5f, DeficitSeconds > 0.0 ? FColor::Yellow : FColor::Green,
			FString::Printf(
				TEXT("%s  |  %.0f fps  sim t=%.1f s  substeps %llu  ")
				TEXT("behind %.2f s (%llu caps)  seed %lld turbulence %s ")
				TEXT("(visual-only)"),
				*Card.Aircraft, Fps, SimTimeSeconds, SubstepCount,
				DeficitSeconds, DeficitEvents, Card.TurbulenceSeed,
				*Card.Turbulence));
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

void AFlightSimInteractiveMode::WriteReport(const FString& Outcome)
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
		TEXT("placeholder box; converted-mesh and HUD cost not in this measurement"));

	FString Payload;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Payload);
	FJsonSerializer::Serialize(Report.ToSharedRef(), Writer);
	// ASCII manifests (gotcha 13): every string above is ASCII by
	// construction; the card digest, paths and dataset ids all are.
	FFileHelper::SaveStringToFile(Payload, *ReportPath);
	UE_LOG(LogFlightSimScenario, Display, TEXT("interactive report -> %s"),
	       *ReportPath);
}

void AFlightSimInteractiveMode::FinishAndQuit(const FString& Outcome)
{
	if (bFinished) { return; }
	bFinished = true;
	UE_LOG(LogFlightSimScenario, Display, TEXT("interactive: %s after %.1f s ")
	       TEXT("wall / %.1f s sim, %llu substeps, behind %.3f s"),
	       *Outcome, WallSeconds, SimTimeSeconds, SubstepCount, DeficitSeconds);
	WriteReport(Outcome);
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
	WriteReport(FString::Printf(TEXT("FAILED: %s"), *Why));
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
