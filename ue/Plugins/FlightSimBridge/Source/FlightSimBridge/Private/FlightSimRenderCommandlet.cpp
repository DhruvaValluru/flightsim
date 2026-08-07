#include "FlightSimRenderCommandlet.h"

#include "FlightSimCameraDirector.h"
#include "FlightSimVisualScene.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimSurfaceAnimator.h"
#include "JSBSimMovementComponent.h"

#include "CineCameraComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Engine.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "RenderingThread.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "ShaderCompiler.h"
#include "TextureResource.h"

DEFINE_LOG_CATEGORY(LogFlightSimRender);

namespace
{
	// The engine's unit cube is 100 cm across, so a scale of N gives an N-metre
	// box and every size below reads directly in metres.
	constexpr double CmPerMetre = 100.0;
	constexpr double RadiansToDegrees = 57.29577951308232;

	// A placeholder airframe: boxes, roughly 747-shaped, with real hinges.
	//
	// This is NOT visual realism -- that is Phase 6 and there is no aircraft
	// asset in this project. It exists to answer one question that a number in
	// a telemetry file cannot: does a JSBSim surface position actually move
	// something a viewer would see? A box that rotates when the FDM says the
	// aileron moved answers it; a photoreal mesh that does not, does not.
	struct FPlaceholderAirframe
	{
		USceneComponent* ElevatorHinge = nullptr;
		USceneComponent* LeftAileronHinge = nullptr;
		USceneComponent* RightAileronHinge = nullptr;
		USceneComponent* RudderHinge = nullptr;
	};

	UStaticMeshComponent* AddBox(AActor* Owner, USceneComponent* Parent,
	                             const TCHAR* Name, UStaticMesh* Cube,
	                             const FVector& CentreMetres, const FVector& SizeMetres)
	{
		UStaticMeshComponent* Box = NewObject<UStaticMeshComponent>(Owner, Name);
		Box->SetupAttachment(Parent);
		Box->SetMobility(EComponentMobility::Movable);
		Box->SetStaticMesh(Cube);
		Box->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Box->RegisterComponent();
		Box->SetRelativeLocation(CentreMetres * CmPerMetre);
		Box->SetRelativeScale3D(SizeMetres);
		return Box;
	}

	// A hinge is a bare scene component at the hinge line, with the surface
	// mesh offset aft of it. Rotating the mesh about its own centre would
	// swing the leading edge forward as well, which is not what a hinge does
	// and would read as a mistake on screen.
	USceneComponent* AddHingedSurface(AActor* Owner, USceneComponent* Parent,
	                                  const TCHAR* HingeName, const TCHAR* MeshName,
	                                  UStaticMesh* Cube, const FVector& HingeMetres,
	                                  const FVector& SizeMetres, const FVector& OffsetMetres)
	{
		USceneComponent* Hinge = NewObject<USceneComponent>(Owner, HingeName);
		Hinge->SetupAttachment(Parent);
		Hinge->SetMobility(EComponentMobility::Movable);
		Hinge->RegisterComponent();
		Hinge->SetRelativeLocation(HingeMetres * CmPerMetre);
		AddBox(Owner, Hinge, MeshName, Cube, OffsetMetres, SizeMetres);
		return Hinge;
	}

	// World -> pixel through the capture's own transform and FOV, so the
	// harness can sample known landmarks instead of guessing regions by eye.
	bool ProjectToPixel(const USceneCaptureComponent2D* Capture, int32 Width,
	                    int32 Height, const FVector& WorldCm, FVector2D& OutPixel)
	{
		OutPixel = FVector2D(-1.0, -1.0);   // defined even when not visible,
		                                    // so the manifest never carries NaN
		const FVector Local =
			Capture->GetComponentTransform().InverseTransformPosition(WorldCm);
		if (Local.X <= 1.0)
		{
			return false;   // behind the camera
		}
		const double HalfWidthTan = FMath::Tan(FMath::DegreesToRadians(Capture->FOVAngle * 0.5));
		const double HalfHeightTan = HalfWidthTan * Height / double(Width);
		OutPixel.X = Width * 0.5 * (1.0 + (Local.Y / Local.X) / HalfWidthTan);
		OutPixel.Y = Height * 0.5 * (1.0 - (Local.Z / Local.X) / HalfHeightTan);
		return OutPixel.X >= 0 && OutPixel.X < Width &&
		       OutPixel.Y >= 0 && OutPixel.Y < Height;
	}

	FPlaceholderAirframe BuildAirframe(AActor* Aircraft, UStaticMesh* Cube)
	{
		USceneComponent* Root = Aircraft->GetRootComponent();
		FPlaceholderAirframe Frame;

		// Roughly to 747-400 scale: 70 m long, 64 m span, tail 30 m aft.
		AddBox(Aircraft, Root, TEXT("Fuselage"), Cube,
		       FVector(0.0, 0.0, 0.0), FVector(70.0, 6.0, 6.0));
		AddBox(Aircraft, Root, TEXT("Wing"), Cube,
		       FVector(-2.0, 0.0, -1.0), FVector(10.0, 64.0, 1.2));
		AddBox(Aircraft, Root, TEXT("Tailplane"), Cube,
		       FVector(-30.0, 0.0, 1.0), FVector(6.0, 22.0, 1.0));
		AddBox(Aircraft, Root, TEXT("Fin"), Cube,
		       FVector(-29.0, 0.0, 6.0), FVector(7.0, 1.0, 10.0));

		// Ailerons hinge about the span axis, outboard on the trailing edge.
		Frame.LeftAileronHinge = AddHingedSurface(
			Aircraft, Root, TEXT("AileronLeftHinge"), TEXT("AileronLeft"), Cube,
			FVector(-7.0, -22.0, -1.0), FVector(3.0, 14.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.RightAileronHinge = AddHingedSurface(
			Aircraft, Root, TEXT("AileronRightHinge"), TEXT("AileronRight"), Cube,
			FVector(-7.0, 22.0, -1.0), FVector(3.0, 14.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.ElevatorHinge = AddHingedSurface(
			Aircraft, Root, TEXT("ElevatorHinge"), TEXT("Elevator"), Cube,
			FVector(-33.0, 0.0, 1.0), FVector(3.0, 22.0, 0.8),
			FVector(-1.5, 0.0, 0.0));
		Frame.RudderHinge = AddHingedSurface(
			Aircraft, Root, TEXT("RudderHinge"), TEXT("Rudder"), Cube,
			FVector(-32.5, 0.0, 6.0), FVector(3.0, 0.9, 10.0),
			FVector(-1.5, 0.0, 0.0));
		return Frame;
	}
}

UFlightSimRenderCommandlet::UFlightSimRenderCommandlet()
{
	// The whole point of this class. Without it the engine comes up with a null
	// RHI and every capture writes a blank frame -- which would look like
	// evidence and be nothing of the kind.
	IsClient = true;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
	ShowErrorCount = true;
}

int32 UFlightSimRenderCommandlet::Main(const FString& Params)
{
	FString ScenarioPath;
	FString OutputDirectory;
	if (!FParse::Value(*Params, TEXT("scenario="), ScenarioPath) ||
	    !FParse::Value(*Params, TEXT("frames="), OutputDirectory))
	{
		UE_LOG(LogFlightSimRender, Error,
		       TEXT("usage: -run=FlightSimBridge.FlightSimRender ")
		       TEXT("-scenario=<run-card.json> -frames=<out-dir> [-fps=5] "
		            "[-width=960] [-height=540]"));
		return 1;
	}
	double FramesPerSecond = 5.0;
	int32 Width = 960;
	int32 Height = 540;
	FParse::Value(*Params, TEXT("fps="), FramesPerSecond);
	FParse::Value(*Params, TEXT("width="), Width);
	FParse::Value(*Params, TEXT("height="), Height);

	// Gate 6 controls. -Visual builds the §6.6 scene; the A/B switches exist
	// so the harness can null-test shadows and the aircraft's presence, and
	// -seconds shortens the run for pixel-aligned stills (physics is
	// deterministic per spec, so equal-length runs land frame-for-frame).
	const bool bVisual = FParse::Param(*Params, TEXT("Visual"));
	// Two framings, because no single camera holds both Gate 6 shadow
	// clauses: the ridge and its shadow band live kilometres ahead, and the
	// aircraft's own shadow lands hundreds of metres from the aircraft --
	// visible only from a high chase looking down. Which sun goes with which
	// shot is part of the framing, and both are recorded in the manifest.
	FString Shot = TEXT("terrain");
	FParse::Value(*Params, TEXT("shot="), Shot);
	const bool bShadowShot = Shot == TEXT("shadow");
	const bool bNoShadows = FParse::Param(*Params, TEXT("NoShadows"));
	const bool bHideAircraft = FParse::Param(*Params, TEXT("HideAircraft"));
	// The exposure clause's negative control: render with the default
	// auto-exposure so the harness can prove its metric actually catches
	// metering that responds to the scene. A metric no failure can trip is
	// not a measurement (§1.7).
	const bool bAutoExposure = FParse::Param(*Params, TEXT("AutoExposure"));
	FString TerrainPath;
	FParse::Value(*Params, TEXT("terrain="), TerrainPath);
	double SecondsOverride = 0.0;
	FParse::Value(*Params, TEXT("seconds="), SecondsOverride);

	if (GDynamicRHI == nullptr || !FApp::CanEverRender())
	{
		UE_LOG(LogFlightSimRender, Error,
		       TEXT("the engine came up without a renderer. Run with "
		            "-RenderOffScreen -AllowCommandletRendering, and without "
		            "-nullrhi. A capture taken now would write a blank frame "
		            "that looks exactly like evidence."));
		return 1;
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("RHI: %s"), GDynamicRHI->GetName());

	FFlightSimScenarioCard Card;
	FString Error;
	if (!FFlightSimScenarioWorld::ReadCard(ScenarioPath, Card, Error))
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *Error);
		return 1;
	}

	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (Cube == nullptr)
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("/Engine/BasicShapes/Cube.Cube did not load"));
		return 1;
	}

	FFlightSimScenarioWorld Scenario;
	auto Fail = [&Scenario](const FString& Why) -> int32
	{
		UE_LOG(LogFlightSimRender, Error, TEXT("%s"), *Why);
		Scenario.Teardown();
		return 1;
	};
	if (!Scenario.Build(Card, Error)) { return Fail(Error); }
	UWorld* World = Scenario.World;

	// -- what makes it visible ---------------------------------------------
	// Two scene tiers. Gate 5's is a deliberately black void: the silhouette
	// measurements depend on it, so it stays byte-for-byte as it was. Gate 6's
	// is the §6.6 scene, behind -Visual.
	FFlightSimVisualScene VisualScene;
	if (bVisual)
	{
		FFlightSimVisualSceneOptions SceneOptions;
		SceneOptions.TerrainPath = TerrainPath;
		SceneOptions.bDynamicShadows = !bNoShadows;
		// The aircraft flies toward -Y in the engine frame (measured off the
		// first probe's landmark projections; heading north maps there through
		// the plugin's yaw-90 convention). The ridge goes ahead of it, and the
		// far copy at extinction distance beyond.
		SceneOptions.NearTerrainOriginMetres = FVector2D(-8000.0, -21360.0);
		SceneOptions.FarTerrainOriginMetres = FVector2D(-8000.0, -41360.0);
		// Terrain shot: sun beyond the ridge, so the peaks throw their shadow
		// band back across the plain toward the camera. Shadow shot: sun high
		// behind the camera's right shoulder, so the aircraft's shadow lands
		// a few hundred metres ahead-left, inside the downward framing.
		// Terrain shot: side light (from +X), so slopes are lit and every
		// peak throws a measurable shadow across the valley beside it --
		// backlighting turned the whole range into silhouette and there was
		// nothing for the shadow A/B to measure. Shadow shot: sun almost
		// astern, so the aircraft's shadow lands near-centre ahead.
		SceneOptions.SunRotation = bShadowShot
			? FRotator(-40.0, -140.0, 0.0)
			: FRotator(-12.0, 180.0, 0.0);   // low sun: long cast shadows
		if (!VisualScene.Build(World, SceneOptions, Error)) { return Fail(Error); }
	}
	else
	{
		ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>();
		Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Sun->SetActorRotation(FRotator(-35.0, 140.0, 0.0));
		Sun->GetLightComponent()->SetIntensity(8.0f);

		ASkyLight* Sky = World->SpawnActor<ASkyLight>();
		Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
		Sky->GetLightComponent()->SetIntensity(1.1f);
	}

	const FPlaceholderAirframe Frame = BuildAirframe(Scenario.Aircraft, Cube);

	UFlightSimSurfaceAnimator* Animator =
		NewObject<UFlightSimSurfaceAnimator>(Scenario.Aircraft, TEXT("Surfaces"));
	Animator->Movement = Scenario.Movement;
	Animator->RegisterComponent();
	Animator->BindSurfaceComponent(TEXT("elevator"), Frame.ElevatorHinge);
	Animator->BindSurfaceComponent(TEXT("aileron_l"), Frame.LeftAileronHinge);
	Animator->BindSurfaceComponent(TEXT("aileron_r"), Frame.RightAileronHinge);
	Animator->BindSurfaceComponent(TEXT("rudder"), Frame.RudderHinge);
	if (Animator->GetBoundSurfaceCount() == 0)
	{
		return Fail(TEXT("no surface binding is attached to anything; the animator "
		                 "would compute deflections and move nothing"));
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("%d control surfaces bound to geometry"),
	       Animator->GetBoundSurfaceCount());

	// A lagged chase that never inherits roll (§1.5). The previous build welded
	// the camera to the airframe, which put the camera in the body frame, in
	// which the aircraft is by construction never moving.
	AFlightSimCameraDirector* Director = World->SpawnActor<AFlightSimCameraDirector>();
	Director->Target = Scenario.Aircraft;
	Director->Preset = EFlightSimCameraPreset::LaggedChase;
	Director->ChaseOffsetMetres = bShadowShot
		? FVector(-400.0f, 0.0f, 200.0f)    // high, looking down at the ground
		: FVector(-170.0f, 0.0f, 16.0f);    // level, terrain and sky in shot
	// Start it where it will settle. A spring-lagged camera that begins at the
	// world origin -- three kilometres below the aircraft -- spends its first
	// seconds catching up, and those frames are of empty sky. They would be
	// written, counted, and prove nothing.
	// Aimed as well as placed: the capture component's transform is pushed to
	// the render thread once per frame, so whatever the camera is pointing at
	// when the first capture goes out is what the first frame shows. Left at
	// the default rotation that is empty sky.
	{
		const FRotator HeadingOnly(0.0, Scenario.Aircraft->GetActorRotation().Yaw, 0.0);
		const FVector Station = Scenario.Aircraft->GetActorLocation() +
			HeadingOnly.RotateVector(FVector(Director->ChaseOffsetMetres) * CmPerMetre);
		FRotator Look = (Scenario.Aircraft->GetActorLocation() - Station).Rotation();
		Look.Roll = 0.0;
		Director->SetActorLocationAndRotation(Station, Look.Quaternion());
	}

	UTextureRenderTarget2D* RenderTarget = NewObject<UTextureRenderTarget2D>();
	RenderTarget->RenderTargetFormat = RTF_RGBA8_SRGB;
	RenderTarget->ClearColor = FLinearColor::Black;
	RenderTarget->bAutoGenerateMips = false;
	RenderTarget->InitAutoFormat(Width, Height);
	RenderTarget->UpdateResourceImmediate(true);

	USceneCaptureComponent2D* Capture =
		NewObject<USceneCaptureComponent2D>(Director, TEXT("Capture"));
	Capture->SetupAttachment(Director->Camera);
	Capture->SetMobility(EComponentMobility::Movable);
	Capture->TextureTarget = RenderTarget;
	Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
	Capture->bCaptureEveryFrame = false;
	Capture->bCaptureOnMovement = false;
	Capture->bAlwaysPersistRenderingState = true;
	// The void scene frames a silhouette tightly; the visual scene needs the
	// terrain and sky in shot, and §6.6's manual exposure so the image does
	// not re-meter as the bright-ground fraction changes with bank.
	Capture->FOVAngle = bVisual ? 55.0f : 24.0f;
	if (bVisual && !bAutoExposure)
	{
		FFlightSimVisualScene::ApplyManualExposure(Capture);
	}
	if (bNoShadows)
	{
		Capture->ShowFlags.SetDynamicShadows(false);
	}
	if (bHideAircraft)
	{
		Capture->HiddenActors.Add(Scenario.Aircraft);
	}
	Capture->RegisterComponent();

	if (!Scenario.BeginPlay(Error)) { return Fail(Error); }
	if (!Scenario.TrimInWind(Card, Error)) { return Fail(Error); }
	if (!Scenario.VerifyTrimmedCondition(Card, Error)) { return Fail(Error); }
	Scenario.LatchTrimmedControls(Card.bMassHeld);

	if (GShaderCompilingManager != nullptr)
	{
		UE_LOG(LogFlightSimRender, Display, TEXT("waiting for shader compilation"));
		GShaderCompilingManager->FinishAllCompilation();
	}

	// Discarded warm-up captures. The first CaptureScene after the component is
	// registered resolves nothing -- the scene proxies exist, but the capture's
	// own rendering state is allocated by the call itself, and measured on this
	// build it takes two calls before a frame comes back with anything in it.
	// Keeping them would put black rectangles at t=0 of every run. They are
	// discarded rather than tolerated: a blank frame in the output is a failure
	// below, and it has to stay one.
	for (int32 i = 0; i < 2; ++i)
	{
		World->SendAllEndOfFrameUpdates();
		FlushRenderingCommands();
		Capture->CaptureScene();
		FlushRenderingCommands();
	}

	// -- the run -----------------------------------------------------------
	const double DeltaSeconds = 1.0 / Card.RateHz;
	const double Duration = SecondsOverride > 0.0
		? FMath::Min(SecondsOverride, Card.DurationSeconds)
		: Card.DurationSeconds;
	const int32 Steps = FMath::RoundToInt(Duration * Card.RateHz);
	const int32 StepsPerFrame = FMath::Max(1, FMath::RoundToInt(Card.RateHz / FramesPerSecond));
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("stepping %d frames of %.6f s, capturing every %d (%.1f Hz) at %dx%d"),
	       Steps, DeltaSeconds, StepsPerFrame, Card.RateHz / StepsPerFrame, Width, Height);

	TArray<TSharedPtr<FJsonValue>> FrameRecords;
	TArray<FColor> Pixels;
	int32 Captured = 0;
	int32 BlankFrames = 0;

	for (int32 Step = 0; Step < Steps; ++Step)
	{
		const double Time = Step * DeltaSeconds;
		if (!Scenario.Step(Card, Time, DeltaSeconds, Error))
		{
			return Fail(Error + TEXT("; frames written so far are not a complete run"));
		}
		if (Step % StepsPerFrame != 0)
		{
			continue;
		}

		// Component render-state updates are queued and flushed at end of
		// frame. A hand-driven loop has to flush them itself, or the capture
		// sees the scene from before the aircraft and its surfaces moved.
		World->SendAllEndOfFrameUpdates();
		FlushRenderingCommands();
		Capture->CaptureScene();
		FlushRenderingCommands();

		FTextureRenderTargetResource* Resource =
			RenderTarget->GameThread_GetRenderTargetResource();
		if (Resource == nullptr || !Resource->ReadPixels(Pixels) || Pixels.Num() == 0)
		{
			return Fail(TEXT("could not read the render target back"));
		}

		int32 Lit = 0;
		for (FColor& Pixel : Pixels)
		{
			Pixel.A = 255;
			if (Pixel.R > 24 || Pixel.G > 24 || Pixel.B > 24)
			{
				++Lit;
			}
		}
		if (Lit == 0)
		{
			++BlankFrames;
		}

		const FString FrameName = FString::Printf(TEXT("frame_%04d.png"), Captured);
		TArray64<uint8> Png;
		FImageUtils::PNGCompressImageArray(Width, Height, Pixels, Png);
		if (!FFileHelper::SaveArrayToFile(Png, *FPaths::Combine(OutputDirectory, FrameName)))
		{
			return Fail(FString::Printf(TEXT("could not write %s"), *FrameName));
		}

		TSharedPtr<FJsonObject> Record = MakeShared<FJsonObject>();
		Record->SetStringField(TEXT("frame"), FrameName);
		Record->SetNumberField(TEXT("t"), Scenario.ReadProperty(TEXT("simulation/sim-time-sec")));
		Record->SetNumberField(TEXT("roll_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/phi-rad")) * RadiansToDegrees);
		Record->SetNumberField(TEXT("pitch_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/theta-rad")) * RadiansToDegrees);
		Record->SetNumberField(TEXT("aileron_cmd"), Scenario.Movement->Commands.Aileron);
		Record->SetNumberField(TEXT("camera_roll_deg"), Director->GetCameraRollDegrees());
		Record->SetNumberField(TEXT("lit_pixels"), Lit);

		// What the animator actually applied to geometry, read back off the
		// bindings rather than recomputed -- so a binding that computed a
		// deflection and moved nothing shows up as a surface that never moved.
		TSharedPtr<FJsonObject> Surfaces = MakeShared<FJsonObject>();
		for (const FFlightSimSurfaceBinding& Binding : Animator->Bindings)
		{
			if (Binding.TargetComponent == nullptr)
			{
				continue;
			}
			// Measured off the scene component, as the angle it has actually
			// been rotated away from its neutral pose -- not recomputed from
			// the property. A binding that read a deflection and moved nothing
			// therefore reports zero here, which is the failure worth catching.
			const FQuat Applied =
				Binding.NeutralRotation.Quaternion().Inverse() *
				Binding.TargetComponent->GetRelativeRotation().Quaternion();
			FVector Axis;
			float Angle = 0.0f;
			Applied.ToAxisAndAngle(Axis, Angle);
			const double Sign =
				FMath::Sign(Axis | Binding.RotationAxis.GetSafeNormal());
			Surfaces->SetNumberField(Binding.BoneName.ToString(),
			                         FMath::RadiansToDegrees(Angle) * Sign);
		}
		Record->SetObjectField(TEXT("surface_component_deg"), Surfaces);

		// Landmarks, projected through the camera of record, so the harness
		// samples known world points instead of guessing regions by eye. The
		// aircraft ground point is its position dropped to the visual ground.
		if (bVisual)
		{
			TSharedPtr<FJsonObject> Landmarks = MakeShared<FJsonObject>();
			auto AddLandmark = [&](const TCHAR* LandmarkName, const FVector& WorldCm)
			{
				FVector2D Pixel;
				const bool bVisible =
					ProjectToPixel(Capture, Width, Height, WorldCm, Pixel);
				TSharedPtr<FJsonObject> Entry = MakeShared<FJsonObject>();
				Entry->SetBoolField(TEXT("visible"), bVisible);
				Entry->SetNumberField(TEXT("px"), Pixel.X);
				Entry->SetNumberField(TEXT("py"), Pixel.Y);
				Landmarks->SetObjectField(LandmarkName, Entry);
			};
			AddLandmark(TEXT("near_peak"), VisualScene.NearPeakWorldCm);
			AddLandmark(TEXT("far_peak"), VisualScene.FarPeakWorldCm);
			// The plain between aircraft and ridge, where the terrain shot's
			// shadow band falls.
			AddLandmark(TEXT("valley"),
			            FVector(VisualScene.NearPeakWorldCm.X, -520000.0, 0.0));
			const FVector AircraftLocation = Scenario.Aircraft->GetActorLocation();
			AddLandmark(TEXT("aircraft_ground"),
			            FVector(AircraftLocation.X, AircraftLocation.Y, 0.0));
			Record->SetObjectField(TEXT("landmarks"), Landmarks);
		}
		FrameRecords.Add(MakeShared<FJsonValueObject>(Record));
		++Captured;
	}

	if (Captured == 0)
	{
		return Fail(TEXT("no frames were captured"));
	}
	if (BlankFrames > 0)
	{
		return Fail(FString::Printf(
			TEXT("%d of %d frames contain nothing above the background. A file "
			     "that exists is not a frame that shows something."),
			BlankFrames, Captured));
	}

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("host"), TEXT("unreal"));
	Root->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
	Root->SetStringField(TEXT("airframe"), TEXT("placeholder boxes, not a visual asset"));
	Root->SetNumberField(TEXT("width"), Width);
	Root->SetNumberField(TEXT("height"), Height);
	Root->SetNumberField(TEXT("frames"), Captured);
	Root->SetNumberField(TEXT("bound_surfaces"), Animator->GetBoundSurfaceCount());
	// Peaks over the bindings that are attached to geometry only. Including the
	// unattached ones would report the gear binding's 90 degrees, which nothing
	// on screen ever did.
	TSharedPtr<FJsonObject> Peaks = MakeShared<FJsonObject>();
	for (const FFlightSimSurfaceBinding& Binding : Animator->Bindings)
	{
		if (Binding.TargetComponent != nullptr)
		{
			Peaks->SetNumberField(Binding.BoneName.ToString(),
			                      Binding.PeakDeflectionDegrees);
		}
	}
	Root->SetObjectField(TEXT("surface_peak_deg"), Peaks);
	Root->SetStringField(TEXT("camera_preset"), TEXT("LaggedChase"));
	Root->SetBoolField(TEXT("camera_keeps_horizon_level"), Director->PresetKeepsHorizonLevel());
	TSharedPtr<FJsonObject> Scene = MakeShared<FJsonObject>();
	Scene->SetBoolField(TEXT("visual"), bVisual);
	Scene->SetStringField(TEXT("shot"), Shot);
	Scene->SetBoolField(TEXT("dynamic_shadows"), !bNoShadows);
	Scene->SetBoolField(TEXT("aircraft_hidden"), bHideAircraft);
	Scene->SetStringField(TEXT("exposure"), (bVisual && !bAutoExposure)
		? TEXT("manual, AutoExposureBias 11.0")
		: TEXT("auto (default metering)"));
	if (bVisual && !TerrainPath.IsEmpty())
	{
		Scene->SetStringField(TEXT("terrain_sha256"), VisualScene.TerrainSha256);
		Scene->SetNumberField(TEXT("terrain_peak_m"), VisualScene.TerrainPeakMetres);
	}
	Root->SetObjectField(TEXT("scene"), Scene);
	Root->SetArrayField(TEXT("frame_records"), FrameRecords);

	FString Output;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
	const FString ManifestPath = FPaths::Combine(OutputDirectory, TEXT("render.json"));
	if (!FFileHelper::SaveStringToFile(Output, *ManifestPath))
	{
		return Fail(FString::Printf(TEXT("could not write %s"), *ManifestPath));
	}
	UE_LOG(LogFlightSimRender, Display, TEXT("wrote %d frames and %s"),
	       Captured, *ManifestPath);

	Scenario.Teardown();
	return 0;
}
