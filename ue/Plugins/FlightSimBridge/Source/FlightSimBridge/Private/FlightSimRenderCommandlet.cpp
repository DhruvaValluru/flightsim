#include "FlightSimRenderCommandlet.h"

#include "FlightSimCameraDirector.h"
#include "FlightSimOrographic.h"
#include "FlightSimVisualScene.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimTelemetryRecorder.h"
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
#include "GeoReferencingSystem.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "AssetCompilingManager.h"
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
	constexpr double RenderCmPerMetre = 100.0;   // unity-unique name
	constexpr double RenderRadiansToDegrees = 57.29577951308232;   // unity-unique name

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
		Box->SetRelativeLocation(CentreMetres * RenderCmPerMetre);
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
		Hinge->SetRelativeLocation(HingeMetres * RenderCmPerMetre);
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

	// A real aircraft mesh, assembled from the converter's manifest: one
	// static mesh for the body and one per control surface, each surface
	// under a hinge scene component at the hinge line the FlightGear model
	// XML states -- the same attach pattern the placeholder boxes use, so
	// UFlightSimSurfaceAnimator drives real geometry through the identical
	// code path Gate 5 measured.
	struct FMeshAirframe
	{
		bool bLoaded = false;
		FString Name;
		FString FdmName;
		FString MeshAirframe;
		FString License;
		FString Repo;
		FString Commit;
	};

	bool BuildMeshAirframe(AActor* Aircraft, UFlightSimSurfaceAnimator* Animator,
	                       const FString& ManifestPath, const FString& CardAircraft,
	                       FMeshAirframe& Out, FString& Error)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *ManifestPath))
		{
			Error = FString::Printf(TEXT("cannot read mesh manifest '%s'"), *ManifestPath);
			return false;
		}
		TSharedPtr<FJsonObject> Manifest;
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Manifest) || !Manifest.IsValid())
		{
			Error = FString::Printf(TEXT("'%s' is not valid JSON"), *ManifestPath);
			return false;
		}
		FString Magic;
		Manifest->TryGetStringField(TEXT("magic"), Magic);
		if (Magic != TEXT("flightsim-aircraft-mesh"))
		{
			Error = FString::Printf(TEXT("'%s' is not an aircraft mesh manifest"),
			                        *ManifestPath);
			return false;
		}

		// §1.4, enforced where the pairing actually happens: the mesh's FDM
		// must be the FDM this card flies. "FDM JSBSIM F16 - MODEL F-15" is
		// the failure this repository exists to prevent, and it is prevented
		// here, not in a comment.
		Manifest->TryGetStringField(TEXT("fdm"), Out.FdmName);
		Manifest->TryGetStringField(TEXT("name"), Out.Name);
		Manifest->TryGetStringField(TEXT("mesh_airframe"), Out.MeshAirframe);
		if (Out.FdmName != CardAircraft)
		{
			Error = FString::Printf(
				TEXT("REFUSING the pairing: mesh manifest '%s' is for FDM '%s' ")
				TEXT("but this card flies '%s'. One mesh per airframe flown."),
				*ManifestPath, *Out.FdmName, *CardAircraft);
			return false;
		}
		const TSharedPtr<FJsonObject>* Source = nullptr;
		if (Manifest->TryGetObjectField(TEXT("source"), Source))
		{
			(*Source)->TryGetStringField(TEXT("license_name"), Out.License);
			(*Source)->TryGetStringField(TEXT("repo"), Out.Repo);
			(*Source)->TryGetStringField(TEXT("commit"), Out.Commit);
		}
		if (Out.License.IsEmpty())
		{
			Error = FString::Printf(
				TEXT("mesh manifest '%s' records no license (§3.3); refusing to ")
				TEXT("render an asset whose terms are unrecorded"), *ManifestPath);
			return false;
		}

		FString AssetRoot;
		Manifest->TryGetStringField(TEXT("asset_path_root"), AssetRoot);
		USceneComponent* Root = Aircraft->GetRootComponent();

		auto LoadPart = [&](const FString& Part) -> UStaticMesh*
		{
			const FString Path = FString::Printf(TEXT("%s/%s.%s"), *AssetRoot, *Part, *Part);
			return LoadObject<UStaticMesh>(nullptr, *Path);
		};

		UStaticMesh* Body = LoadPart(TEXT("body"));
		if (Body == nullptr)
		{
			Error = FString::Printf(
				TEXT("mesh asset %s/body did not load. Run the import step ")
				TEXT("(scripts/ue_import_aircraft.py) -- a missing asset must not ")
				TEXT("fall back to the placeholder boxes silently."), *AssetRoot);
			return false;
		}
		UStaticMeshComponent* BodyComponent =
			NewObject<UStaticMeshComponent>(Aircraft, TEXT("MeshBody"));
		BodyComponent->SetupAttachment(Root);
		BodyComponent->SetMobility(EComponentMobility::Movable);
		BodyComponent->SetStaticMesh(Body);
		BodyComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		BodyComponent->RegisterComponent();

		// A manifest airframe replaces the whole binding table: its bones are
		// its own (both elevators, split ailerons), and mixing them with the
		// stock table would make bone lookup ambiguous.
		Animator->ClearBindings();

		const TArray<TSharedPtr<FJsonValue>>* Surfaces = nullptr;
		if (!Manifest->TryGetArrayField(TEXT("surfaces"), Surfaces) || Surfaces == nullptr)
		{
			Error = FString::Printf(TEXT("'%s' has no surfaces"), *ManifestPath);
			return false;
		}
		for (const TSharedPtr<FJsonValue>& Value : *Surfaces)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if (!Value->TryGetObject(Entry) || Entry == nullptr)
			{
				Error = TEXT("surfaces must be objects");
				return false;
			}
			FString Bone, Part, Property;
			(*Entry)->TryGetStringField(TEXT("bone"), Bone);
			(*Entry)->TryGetStringField(TEXT("part"), Part);
			(*Entry)->TryGetStringField(TEXT("property"), Property);
			double Scale = 0.0;
			(*Entry)->TryGetNumberField(TEXT("scale_deg_per_unit"), Scale);
			const TArray<TSharedPtr<FJsonValue>>* Hinge = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Axis = nullptr;
			if (!(*Entry)->TryGetArrayField(TEXT("hinge_mid_cm"), Hinge) ||
			    !(*Entry)->TryGetArrayField(TEXT("axis_ue"), Axis) ||
			    Hinge->Num() != 3 || Axis->Num() != 3)
			{
				Error = FString::Printf(TEXT("surface '%s' lacks hinge/axis"), *Bone);
				return false;
			}
			const FVector HingeMid((*Hinge)[0]->AsNumber(), (*Hinge)[1]->AsNumber(),
			                       (*Hinge)[2]->AsNumber());
			const FVector RotationAxis((*Axis)[0]->AsNumber(), (*Axis)[1]->AsNumber(),
			                           (*Axis)[2]->AsNumber());

			UStaticMesh* SurfaceMesh = LoadPart(Part);
			if (SurfaceMesh == nullptr)
			{
				Error = FString::Printf(TEXT("mesh asset %s/%s did not load"),
				                        *AssetRoot, *Part);
				return false;
			}
			USceneComponent* HingeComponent = NewObject<USceneComponent>(
				Aircraft, *FString::Printf(TEXT("%sHinge"), *Bone));
			HingeComponent->SetupAttachment(Root);
			HingeComponent->SetMobility(EComponentMobility::Movable);
			HingeComponent->RegisterComponent();
			HingeComponent->SetRelativeLocation(HingeMid);

			UStaticMeshComponent* SurfaceComponent = NewObject<UStaticMeshComponent>(
				Aircraft, *FString::Printf(TEXT("%sMesh"), *Bone));
			SurfaceComponent->SetupAttachment(HingeComponent);
			SurfaceComponent->SetMobility(EComponentMobility::Movable);
			SurfaceComponent->SetStaticMesh(SurfaceMesh);
			SurfaceComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			SurfaceComponent->RegisterComponent();
			// The surface OBJ is exported in place (actor frame); parenting it
			// to a hinge at HingeMid means offsetting it back by the same.
			SurfaceComponent->SetRelativeLocation(-HingeMid);

			bool bContinuous = false;
			(*Entry)->TryGetBoolField(TEXT("continuous"), bContinuous);
			Animator->AddBinding(Property, FName(*Bone),
			                     static_cast<float>(Scale), RotationAxis,
			                     bContinuous);
			Animator->BindSurfaceComponent(FName(*Bone), HingeComponent);
		}
		Out.bLoaded = true;
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("mesh airframe '%s' (%s) [%s, %s@%s]: %d surfaces bound"),
		       *Out.Name, *Out.MeshAirframe, *Out.License, *Out.Repo,
		       *Out.Commit.Left(12), Surfaces->Num());
		return true;
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
	// Full-run telemetry through the SHARED recorder (the same component
	// the telemetry commandlet and the interactive host use), stamping the
	// FDM's own clock. The web app's aero panel reads this file verbatim.
	FString RunTelemetryPath;
	FParse::Value(*Params, TEXT("telemetry="), RunTelemetryPath);

	// -- Phase 6B controls -------------------------------------------------
	// A real aircraft mesh manifest; absent means the placeholder boxes,
	// byte-for-byte as Gate 5 measured them.
	FString MeshManifestPath;
	FParse::Value(*Params, TEXT("mesh="), MeshManifestPath);
	// Georeferenced single-instance terrain at its true position.
	const bool bGeorefTerrain = FParse::Param(*Params, TEXT("GeorefTerrain"));
	// Sun as a time-of-day parameter (dawn / noon / low sun are elevation and
	// azimuth choices made by the harness and recorded in the manifest).
	double SunElevationDeg = 0.0, SunAzimuthDeg = 0.0;
	const bool bSunOverride =
		FParse::Value(*Params, TEXT("sun-elev="), SunElevationDeg) &&
		FParse::Value(*Params, TEXT("sun-azim="), SunAzimuthDeg);
	// Sun ANIMATION (Phase 7 3.1): end-of-clip elevation/azimuth. The sun
	// interpolates linearly over the clip -- a presentation parameter like
	// the static sun, recorded start and end in the manifest. Requires the
	// static override as the start point.
	double SunElevationEndDeg = 0.0, SunAzimuthEndDeg = 0.0;
	const bool bSunAnimated = bSunOverride &&
		FParse::Value(*Params, TEXT("sun-elev-end="), SunElevationEndDeg) &&
		FParse::Value(*Params, TEXT("sun-azim-end="), SunAzimuthEndDeg);
	double FogDensity = 0.0025;
	FParse::Value(*Params, TEXT("fog-density="), FogDensity);
	// True-colour imagery drape (Phase 7 1.1): path to the drape sidecar
	// produced and verified by core/terrain/imagery.py. Replaces the
	// approximated classification for the real locations.
	FString ImagerySidecar;
	FParse::Value(*Params, TEXT("imagery="), ImagerySidecar);
	double ExposureBias = 11.0;
	FParse::Value(*Params, TEXT("exposure-bias="), ExposureBias);
	// Chase offset override, metres: a 747 framed at -170 m puts a Cessna
	// eleven pixels wide; the harness knows the airframe, so it chooses.
	FString ChaseSpec;
	FParse::Value(*Params, TEXT("chase="), ChaseSpec);
	// The orographic null-test control: same card, coupling severed.
	const bool bNoOrographic = FParse::Param(*Params, TEXT("NoOrographic"));

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
	if (bNoOrographic)
	{
		// The null-test control severs the terrain-wind coupling and nothing
		// else. Recorded in the manifest so the control run cannot be quoted
		// as the coupled one.
		Card.bOrographic = false;
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
		SceneOptions.FogDensity = static_cast<float>(FogDensity);
		if (bGeorefTerrain)
		{
			SceneOptions.bGeoreferenced = true;
			SceneOptions.GeoReferencing = Scenario.GeoReferencing;
			SceneOptions.bClassifiedMaterial = true;
			SceneOptions.ImagerySidecarPath = ImagerySidecar;
		}
		else if (!ImagerySidecar.IsEmpty())
		{
			return Fail(TEXT("-imagery requires -GeorefTerrain: the drape is "
			                 "aligned to the georeferenced raster grid"));
		}
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
		if (bSunOverride)
		{
			// Time of day as a parameter: pitch is -elevation, yaw is the
			// direction the LIGHT TRAVELS (sun azimuth + 180), both recorded
			// in the manifest as the approximation they are.
			SceneOptions.SunRotation =
				FRotator(-SunElevationDeg, SunAzimuthDeg + 180.0, 0.0);
		}
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

	UFlightSimSurfaceAnimator* Animator =
		NewObject<UFlightSimSurfaceAnimator>(Scenario.Aircraft, TEXT("Surfaces"));
	Animator->Movement = Scenario.Movement;
	Animator->RegisterComponent();

	FMeshAirframe MeshAirframe;
	if (!MeshManifestPath.IsEmpty())
	{
		if (!BuildMeshAirframe(Scenario.Aircraft, Animator, MeshManifestPath,
		                       Card.Aircraft, MeshAirframe, Error))
		{
			return Fail(Error);
		}
	}
	else
	{
		const FPlaceholderAirframe Frame = BuildAirframe(Scenario.Aircraft, Cube);
		Animator->BindSurfaceComponent(TEXT("elevator"), Frame.ElevatorHinge);
		Animator->BindSurfaceComponent(TEXT("aileron_l"), Frame.LeftAileronHinge);
		Animator->BindSurfaceComponent(TEXT("aileron_r"), Frame.RightAileronHinge);
		Animator->BindSurfaceComponent(TEXT("rudder"), Frame.RudderHinge);
	}
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
	// Camera preset (Phase 7 3.3). Every preset keeps the §1.5 rule: the
	// camera never inherits roll unless the preset SAYS it does, and the
	// manifest records which one flew and whether roll was inherited.
	FString CameraPreset = TEXT("chase");
	FParse::Value(*Params, TEXT("camera="), CameraPreset);
	if (CameraPreset == TEXT("wingman"))
	{
		Director->Preset = EFlightSimCameraPreset::Wingman;
		// -wingman-abeam=<metres>: the default 25 m formation slot sits
		// INSIDE a tornado funnel during a core transit (measured: 2 of
		// 660 frames blank, floor refused). A wider slot keeps the
		// camera following the aircraft from outside the vortex; the
		// behind distance scales with it so the aircraft stays framed.
		double AbeamMetres = 0.0;
		if (FParse::Value(*Params, TEXT("wingman-abeam="), AbeamMetres)
		    && AbeamMetres > 0.0)
		{
			Director->WingmanOffsetMetres.Y = AbeamMetres;
			Director->WingmanOffsetMetres.X =
				-FMath::Max(15.0, AbeamMetres * 0.25);
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("wingman abeam widened to %.0f m (behind %.0f m)"),
			       Director->WingmanOffsetMetres.Y,
			       -Director->WingmanOffsetMetres.X);
		}
	}
	else if (CameraPreset == TEXT("tower"))
	{
		Director->Preset = EFlightSimCameraPreset::Tower;
	}
	else if (CameraPreset == TEXT("shoulder"))
	{
		Director->Preset = EFlightSimCameraPreset::CockpitShoulder;
		// The default shoulder offset is B747-scale; on a c172p it sat
		// INSIDE the fuselage and recorded overexposed paint
		// (probe-measured). Scale by the model's own span, with a floor
		// so small airframes keep the camera above the cabin roof.
		const double SpanMetres =
			Scenario.ReadProperty(TEXT("metrics/bw-ft")) * 0.3048;
		const double Scale = FMath::Clamp(SpanMetres / 64.4, 0.3, 1.0);
		Director->ShoulderOffsetMetres.X *= Scale;
		Director->ShoulderOffsetMetres.Y *= Scale;
		Director->ShoulderOffsetMetres.Z =
			FMath::Max(Director->ShoulderOffsetMetres.Z * Scale, 1.3);
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("shoulder camera scaled by span %.1f m: offset ")
		       TEXT("(%.2f, %.2f, %.2f) m"), SpanMetres,
		       Director->ShoulderOffsetMetres.X,
		       Director->ShoulderOffsetMetres.Y,
		       Director->ShoulderOffsetMetres.Z);
	}
	else if (CameraPreset != TEXT("chase"))
	{
		return Fail(FString::Printf(
			TEXT("unknown camera preset '%s' (chase|wingman|tower|shoulder)"),
			*CameraPreset));
	}
	Director->ChaseOffsetMetres = bShadowShot
		? FVector(-400.0f, 0.0f, 200.0f)    // high, looking down at the ground
		: FVector(-170.0f, 0.0f, 16.0f);    // level, terrain and sky in shot
	if (!ChaseSpec.IsEmpty())
	{
		// Colon-separated because FParse::Value stops at a comma (measured:
		// "-chase=-170,0,16" arrives here as "-170").
		TArray<FString> Parts;
		ChaseSpec.ParseIntoArray(Parts, TEXT(":"));
		if (Parts.Num() == 3)
		{
			Director->ChaseOffsetMetres = FVector(
				FCString::Atod(*Parts[0]), FCString::Atod(*Parts[1]),
				FCString::Atod(*Parts[2]));
		}
		else
		{
			return Fail(FString::Printf(
				TEXT("-chase expects x:y:z metres, got '%s'"), *ChaseSpec));
		}
	}
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
			HeadingOnly.RotateVector(FVector(Director->ChaseOffsetMetres) * RenderCmPerMetre);
		FRotator Look = (Scenario.Aircraft->GetActorLocation() - Station).Rotation();
		Look.Roll = 0.0;
		Director->SetActorLocationAndRotation(Station, Look.Quaternion());
	}

	// -- consume-poses mode (Camera Phase 1) -------------------------------
	// A card carrying a "cameras" block was solved in Python
	// (core/capture/poses.py): per-sample positions in local scene metres
	// about the block's own projected origin, aerospace yaw/pitch/roll.
	// This pass consumes ONE camera's track verbatim (-camera-index=N; the
	// harness runs one invocation per camera, each with its own -frames=
	// directory); the presets above keep flying cards without the block,
	// byte-identically. Conversion here is the plugin's own established
	// mapping: ProjectedToEngine for position, actor yaw = true heading
	// - 90 (the aircraft placement convention), pitch/roll as-is.
	bool bConsumePoses = false;
	int32 ConsumedCameraIndex = 0;
	double CameraOriginXMetres = 0.0;
	double CameraOriginYMetres = 0.0;
	{
		FParse::Value(*Params, TEXT("camera-index="), ConsumedCameraIndex);
		FString CardText;
		TSharedPtr<FJsonObject> CardRoot;
		if (FFileHelper::LoadFileToString(CardText, *ScenarioPath))
		{
			const TSharedRef<TJsonReader<>> CardReader =
				TJsonReaderFactory<>::Create(CardText);
			FJsonSerializer::Deserialize(CardReader, CardRoot);
		}
		const TArray<TSharedPtr<FJsonValue>>* CamerasJson = nullptr;
		if (CardRoot.IsValid() &&
		    CardRoot->TryGetArrayField(TEXT("cameras"), CamerasJson) &&
		    CamerasJson != nullptr && CamerasJson->Num() > 0)
		{
			if (!CamerasJson->IsValidIndex(ConsumedCameraIndex))
			{
				return Fail(FString::Printf(
					TEXT("-camera-index=%d but the card carries %d camera(s)"),
					ConsumedCameraIndex, CamerasJson->Num()));
			}
			const TSharedPtr<FJsonObject> CameraJson =
				(*CamerasJson)[ConsumedCameraIndex]->AsObject();
			const TSharedPtr<FJsonObject>* PosesJson = nullptr;
			if (!CameraJson.IsValid() ||
			    !CameraJson->TryGetNumberField(TEXT("origin_x_m"), CameraOriginXMetres) ||
			    !CameraJson->TryGetNumberField(TEXT("origin_y_m"), CameraOriginYMetres) ||
			    !CameraJson->TryGetObjectField(TEXT("poses"), PosesJson))
			{
				return Fail(TEXT("cameras block is missing origin_x_m/"
				                 "origin_y_m/poses; refusing to guess the frame"));
			}
			const TArray<TSharedPtr<FJsonValue>>* Times = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Norths = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Easts = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Alts = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Yaws = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Pitches = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Rolls = nullptr;
			if (!(*PosesJson)->TryGetArrayField(TEXT("t_s"), Times) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("north_m"), Norths) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("east_m"), Easts) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("alt_m"), Alts) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("yaw_deg"), Yaws) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("pitch_deg"), Pitches) ||
			    !(*PosesJson)->TryGetArrayField(TEXT("roll_deg"), Rolls))
			{
				return Fail(TEXT("camera pose track is missing one of "
				                 "t_s/north_m/east_m/alt_m/yaw_deg/pitch_deg/"
				                 "roll_deg"));
			}
			const int32 Count = Times->Num();
			if (Norths->Num() != Count || Easts->Num() != Count ||
			    Alts->Num() != Count || Yaws->Num() != Count ||
			    Pitches->Num() != Count || Rolls->Num() != Count)
			{
				return Fail(TEXT("camera pose track arrays disagree about "
				                 "their length; refusing a misaligned track"));
			}
			TArray<double> TrackTimes;
			TArray<FVector> TrackLocations;
			TArray<FRotator> TrackRotations;
			TrackTimes.Reserve(Count);
			TrackLocations.Reserve(Count);
			TrackRotations.Reserve(Count);
			for (int32 i = 0; i < Count; ++i)
			{
				TrackTimes.Add((*Times)[i]->AsNumber());
				const FVector Projected(
					CameraOriginXMetres + (*Easts)[i]->AsNumber(),
					CameraOriginYMetres + (*Norths)[i]->AsNumber(),
					(*Alts)[i]->AsNumber());
				FVector Engine;
				Scenario.GeoReferencing->ProjectedToEngine(Projected, Engine);
				TrackLocations.Add(Engine);
				TrackRotations.Add(FRotator(
					(*Pitches)[i]->AsNumber(),
					(*Yaws)[i]->AsNumber() - 90.0,
					(*Rolls)[i]->AsNumber()));
			}
			if (!Director->SetPoseTrack(MoveTemp(TrackTimes),
			                            MoveTemp(TrackLocations),
			                            MoveTemp(TrackRotations), Error))
			{
				return Fail(Error);
			}
			bConsumePoses = true;
			UE_LOG(LogFlightSimRender, Display,
			       TEXT("consume-poses: camera %d of %d, %d solved samples"),
			       ConsumedCameraIndex, CamerasJson->Num(), Count);
			// Place the camera at its first solved pose before the warm-up
			// captures, replacing the chase settle-in placement above.
			if (!Director->ApplyPoseAtTime(0.0, Error))
			{
				return Fail(Error);
			}
		}
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
		FFlightSimVisualScene::ApplyManualExposure(Capture,
			static_cast<float>(ExposureBias));
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
	// After trim and latch, once, mirroring EnvironmentStack.configure. The
	// render path accepts turbulence (the seed goes in the manifest); the
	// PARITY path's policy lives in the telemetry commandlet and the harness.
	Scenario.ConfigureTurbulence(Card);

	// The orographic cross-implementation check: sample the C++ field at a
	// fixed grid around the origin and write the values into the manifest.
	// The Python harness recomputes the same points through the original
	// provider over the same raster; a port that drifted fails there.
	TArray<TSharedPtr<FJsonValue>> OrographicSelftest;
	if (const FFlightSimOrographicWind* Orographic = Scenario.GetOrographic())
	{
		const double Offsets[] = {-6000.0, -3000.0, -900.0, 0.0, 900.0, 3000.0, 6000.0};
		const double Agls[] = {120.0, 600.0, 1800.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("elevation_m"),
				                       Orographic->ElevationMetres(North, East));
				Sample->SetNumberField(TEXT("wind_down_mps"),
				                       Orographic->WindDownMps(North, East, Agl));
				OrographicSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	// The same cross-implementation discipline for every Phase 7 port: grid
	// samples of the C++ field into the manifest, recomputed by the original
	// Python provider in the harness. A port that drifts fails there.
	TArray<TSharedPtr<FJsonValue>> DownburstSelftest;
	if (const FFlightSimDownburst* Burst = Scenario.GetDownburst())
	{
		const double Radii[] = {0.0, 300.0, 700.0, 1000.0, 1400.0, 2500.0};
		const double Agls[] = {30.0, 150.0, 300.0, 600.0};
		for (double Radius : Radii)
		{
			for (double Agl : Agls)
			{
				// Sample along north from the centre; axisymmetry is the
				// field's own claim and the Python recompute checks the full
				// NED vector at these points.
				double NorthMps = 0.0, EastMps = 0.0, DownMps = 0.0;
				Burst->WindNedMps(Burst->CentreNorthMetres + Radius,
				                  Burst->CentreEastMetres, Agl,
				                  NorthMps, EastMps, DownMps);
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("radius_m"), Radius);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("north_mps"), NorthMps);
				Sample->SetNumberField(TEXT("east_mps"), EastMps);
				Sample->SetNumberField(TEXT("down_mps"), DownMps);
				DownburstSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> RotorSelftest;
	if (Scenario.RotorReady())
	{
		const double Offsets[] = {-3000.0, -900.0, 0.0, 900.0, 3000.0};
		const double Agls[] = {60.0, 150.0, 280.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("w20_fps"),
				                       Scenario.RotorW20Fps(North, East, Agl));
				RotorSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	TArray<TSharedPtr<FJsonValue>> LogProfileSelftest;
	if (Card.bLogProfile)
	{
		const double Agls[] = {0.0, 5.0, 10.0, 30.0, 100.0, 200.0, 300.0, 500.0};
		for (double Agl : Agls)
		{
			TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
			Sample->SetNumberField(TEXT("agl_m"), Agl);
			Sample->SetNumberField(TEXT("speed_mps"),
			                       Scenario.LogProfileSpeedMps(Agl));
			LogProfileSelftest.Add(MakeShared<FJsonValueObject>(Sample));
		}
	}

	TArray<TSharedPtr<FJsonValue>> ThermalsSelftest;
	if (Scenario.ThermalsReady())
	{
		const double Offsets[] = {-900.0, -300.0, 0.0, 150.0, 300.0, 900.0};
		const double Agls[] = {150.0, 400.0, 900.0};
		int32 Index = 0;
		for (double North : Offsets)
		{
			for (double East : Offsets)
			{
				const double Agl = Agls[Index++ % UE_ARRAY_COUNT(Agls)];
				TSharedPtr<FJsonObject> Sample = MakeShared<FJsonObject>();
				Sample->SetNumberField(TEXT("north_m"), North);
				Sample->SetNumberField(TEXT("east_m"), East);
				Sample->SetNumberField(TEXT("agl_m"), Agl);
				Sample->SetNumberField(TEXT("w_up_mps"),
				                       Scenario.ThermalWMps(North, East, Agl));
				ThermalsSelftest.Add(MakeShared<FJsonValueObject>(Sample));
			}
		}
	}

	if (GShaderCompilingManager != nullptr)
	{
		UE_LOG(LogFlightSimRender, Display, TEXT("waiting for shader compilation"));
		GShaderCompilingManager->FinishAllCompilation();
	}
	// Static meshes above a size threshold build their render data
	// asynchronously, and a commandlet never ticks the compiling manager --
	// so a large imported mesh stays "compiling" forever and draws NOTHING
	// while every capture reports success (measured: the 747 body was absent
	// from every frame while its 26-triangle ailerons rendered fine). Finish
	// the builds before the first capture, exactly as with shaders above.
	FAssetCompilingManager::Get().FinishAllCompilation();

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

	// -- Phase 8B.0: the real-time probe loop ------------------------------
	// The interactive host cannot run under a locked console session (both
	// editor binaries park -game mode in the AppKit event loop; sampled), so
	// the go/no-go frame cost is measured HERE: the same scene, the same
	// stepping path, a wall-clock substep accumulator identical to the
	// interactive host's, and one CaptureScene per iteration with NO pixel
	// readback and NO png encode. FlushRenderingCommands serializes the GPU
	// into the measurement, so the number is conservative. What it excludes
	// -- window compositing, slate/HUD draw -- is stated in the report.
	double ProbeWallSeconds = 0.0;
	FParse::Value(*Params, TEXT("probe-wall-seconds="), ProbeWallSeconds);
	if (ProbeWallSeconds > 0.0)
	{
		FString ProbeReportPath;
		FParse::Value(*Params, TEXT("probe-report="), ProbeReportPath);
		// Replay-parity outputs (Gate 8.2, locked-session path): the same
		// recorder the telemetry commandlet uses, sampling on the FDM's own
		// clock while THIS loop paces the FDM by the wall clock -- the
		// stepping and clocking the interactive host uses, minus the window.
		FString ProbeTelemetryPath, ProbeManifestPath;
		FParse::Value(*Params, TEXT("probe-telemetry="), ProbeTelemetryPath);
		FParse::Value(*Params, TEXT("probe-manifest="), ProbeManifestPath);
		UFlightSimTelemetryRecorder* ProbeRecorder = nullptr;
		if (!ProbeTelemetryPath.IsEmpty())
		{
			ProbeRecorder = NewObject<UFlightSimTelemetryRecorder>(
				Scenario.Aircraft, TEXT("ProbeRecorder"));
			ProbeRecorder->Movement = Scenario.Movement;
			ProbeRecorder->SampleIntervalSeconds =
				static_cast<float>(Card.SampleIntervalSeconds);
			ProbeRecorder->RegisterComponent();
			// hazard 1: refuse rather than record NaN forever.
			if (!ProbeRecorder->SelftestProperties(Error))
			{
				return Fail(Error);
			}
			ProbeRecorder->StartRecording(ProbeTelemetryPath);
		}
		const double SubstepSeconds = 1.0 / Card.RateHz;
		const double CatchUpCapSeconds = 0.25;
		double Accumulator = 0.0;
		double SimTime = 0.0;
		double DeficitSeconds = 0.0;
		uint64 Substeps = 0, DeficitEvents = 0;
		TArray<float> ProbeFrameSeconds;
		double WallStart = FPlatformTime::Seconds();
		double LastFrame = WallStart;
		UE_LOG(LogFlightSimRender, Display,
		       TEXT("probe: real-time loop for %.0f s wall at %dx%d"),
		       ProbeWallSeconds, Width, Height);
		while (FPlatformTime::Seconds() - WallStart < ProbeWallSeconds
		       && SimTime < Card.DurationSeconds)
		{
			const double Now = FPlatformTime::Seconds();
			const double WallDelta = Now - LastFrame;
			LastFrame = Now;
			ProbeFrameSeconds.Add(static_cast<float>(WallDelta));
			Accumulator += WallDelta;
			if (Accumulator > CatchUpCapSeconds)
			{
				DeficitEvents += 1;
				DeficitSeconds += Accumulator - CatchUpCapSeconds;
				Accumulator = CatchUpCapSeconds;
			}
			while (Accumulator >= SubstepSeconds)
			{
				if (!Scenario.Step(Card, SimTime, SubstepSeconds, Error))
				{
					return Fail(Error + TEXT("; probe aborted"));
				}
				SimTime += SubstepSeconds;
				Accumulator -= SubstepSeconds;
				++Substeps;
			}
			World->SendAllEndOfFrameUpdates();
			FlushRenderingCommands();
			Capture->CaptureScene();
			FlushRenderingCommands();
		}
		const double WallTotal = FPlatformTime::Seconds() - WallStart;
		if (ProbeRecorder != nullptr && !ProbeRecorder->WriteToDisk())
		{
			return Fail(TEXT("probe telemetry did not write"));
		}
		if (!ProbeManifestPath.IsEmpty())
		{
			TSharedPtr<FJsonObject> Manifest = MakeShared<FJsonObject>();
			Manifest->SetStringField(TEXT("host"),
				TEXT("interactive-equivalent (commandlet wall-clock loop; ")
				TEXT("locked-session path -- no window)"));
			Manifest->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
			Manifest->SetStringField(TEXT("aircraft"), Card.Aircraft);
			Manifest->SetStringField(TEXT("turbulence"), Card.Turbulence);
			Manifest->SetNumberField(TEXT("turbulence_seed"),
			                         static_cast<double>(Card.TurbulenceSeed));
			Manifest->SetNumberField(TEXT("sim_seconds"), SimTime);
			Manifest->SetNumberField(TEXT("wall_seconds"), WallTotal);
			Manifest->SetNumberField(TEXT("substeps"),
			                         static_cast<double>(Substeps));
			Manifest->SetNumberField(TEXT("substep_rate_hz"), Card.RateHz);
			Manifest->SetNumberField(TEXT("deficit_events"),
			                         static_cast<double>(DeficitEvents));
			Manifest->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
			Manifest->SetStringField(TEXT("telemetry"), ProbeTelemetryPath);
			FString ManifestPayload;
			const TSharedRef<TJsonWriter<>> ManifestWriter =
				TJsonWriterFactory<>::Create(&ManifestPayload);
			FJsonSerializer::Serialize(Manifest.ToSharedRef(), ManifestWriter);
			FFileHelper::SaveStringToFile(ManifestPayload, *ProbeManifestPath);
		}
		if (!ProbeReportPath.IsEmpty() && ProbeFrameSeconds.Num() > 0)
		{
			TArray<float> Sorted = ProbeFrameSeconds;
			Sorted.Sort();
			auto Percentile = [&Sorted](double P) -> double
			{
				const int32 Index = FMath::Clamp(
					static_cast<int32>(P * (Sorted.Num() - 1)), 0, Sorted.Num() - 1);
				return static_cast<double>(Sorted[Index]);
			};
			TSharedPtr<FJsonObject> Probe = MakeShared<FJsonObject>();
			Probe->SetStringField(TEXT("outcome"), TEXT("probe complete"));
			Probe->SetStringField(TEXT("spec_digest"), Card.SpecDigest);
			Probe->SetStringField(TEXT("aircraft"), Card.Aircraft);
			Probe->SetNumberField(TEXT("frames"), ProbeFrameSeconds.Num());
			Probe->SetNumberField(TEXT("wall_seconds"), WallTotal);
			Probe->SetNumberField(TEXT("fps_mean"),
			                      ProbeFrameSeconds.Num() / WallTotal);
			Probe->SetNumberField(TEXT("frame_ms_p50"), Percentile(0.50) * 1000.0);
			Probe->SetNumberField(TEXT("frame_ms_p95"), Percentile(0.95) * 1000.0);
			Probe->SetNumberField(TEXT("frame_ms_max"),
			                      static_cast<double>(Sorted.Last()) * 1000.0);
			Probe->SetNumberField(TEXT("sim_seconds"), SimTime);
			Probe->SetNumberField(TEXT("substeps"), static_cast<double>(Substeps));
			Probe->SetNumberField(TEXT("substep_rate_hz"), Card.RateHz);
			Probe->SetNumberField(TEXT("deficit_events"),
			                      static_cast<double>(DeficitEvents));
			Probe->SetNumberField(TEXT("deficit_seconds"), DeficitSeconds);
			Probe->SetStringField(TEXT("terrain"), VisualScene.TerrainName);
			Probe->SetStringField(TEXT("terrain_sha256"), VisualScene.TerrainSha256);
			Probe->SetStringField(TEXT("imagery_dataset"), VisualScene.ImageryDataset);
			Probe->SetStringField(TEXT("display"),
				TEXT("offscreen commandlet loop: SceneCapture per frame, no ")
				TEXT("readback; window compositing and HUD draw excluded"));
			Probe->SetStringField(TEXT("airframe"),
				TEXT("as rendered by this commandlet (mesh if -mesh was given)"));
			FString Payload;
			const TSharedRef<TJsonWriter<>> Writer =
				TJsonWriterFactory<>::Create(&Payload);
			FJsonSerializer::Serialize(Probe.ToSharedRef(), Writer);
			FFileHelper::SaveStringToFile(Payload, *ProbeReportPath);
			UE_LOG(LogFlightSimRender, Display, TEXT("probe report -> %s"),
			       *ProbeReportPath);
		}
		Scenario.Teardown();
		return 0;
	}

	// -- the run -----------------------------------------------------------
	UFlightSimTelemetryRecorder* RunRecorder = nullptr;
	if (!RunTelemetryPath.IsEmpty())
	{
		RunRecorder = NewObject<UFlightSimTelemetryRecorder>(
			Scenario.Aircraft, TEXT("RunRecorder"));
		RunRecorder->Movement = Scenario.Movement;
		RunRecorder->SampleIntervalSeconds =
			static_cast<float>(Card.SampleIntervalSeconds);
		RunRecorder->RegisterComponent();
		// hazard 1: refuse rather than record NaN forever.
		if (!RunRecorder->SelftestProperties(Error))
		{
			return Fail(Error);
		}
		RunRecorder->StartRecording(RunTelemetryPath);
	}
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

		// The animated sun (Phase 7 3.1): linear in time across the clip,
		// same convention as the static override (pitch = -elevation, yaw =
		// direction the light TRAVELS).
		if (bSunAnimated && VisualScene.Sun != nullptr && Duration > 0.0)
		{
			const double Fraction = FMath::Clamp(Time / Duration, 0.0, 1.0);
			const double Elev = FMath::Lerp(SunElevationDeg, SunElevationEndDeg, Fraction);
			const double Azim = FMath::Lerp(SunAzimuthDeg, SunAzimuthEndDeg, Fraction);
			VisualScene.Sun->SetActorRotation(FRotator(-Elev, Azim + 180.0, 0.0));
		}

		// Consume-poses: drive the camera by SIMULATION time before the
		// render-state flush, so the capture sees the solved pose for this
		// exact frame. A track that does not cover the run fails loudly
		// here (never extrapolated), as does any applied-vs-solved drift.
		if (bConsumePoses)
		{
			if (!Director->ApplyPoseAtTime(
				Scenario.ReadProperty(TEXT("simulation/sim-time-sec")),
				Error))
			{
				return Fail(Error);
			}
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
		                       Scenario.ReadProperty(TEXT("attitude/phi-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("pitch_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/theta-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("aileron_cmd"), Scenario.Movement->Commands.Aileron);
		Record->SetNumberField(TEXT("camera_roll_deg"), Director->GetCameraRollDegrees());
		if (bConsumePoses)
		{
			// Additive Camera Phase 1 fields (ASCII only -- gotcha 13; the
			// camera's id string stays in the Python-written manifest): the
			// pose ACTUALLY APPLIED, expressed back in the card's own local
			// frame so the Python verifier grades applied-vs-solved without
			// knowing engine units. The inverse of the placement mapping
			// above: EngineToProjected, then true heading = engine yaw + 90.
			FVector AppliedProjected;
			Scenario.GeoReferencing->EngineToProjected(
				Director->GetActorLocation(), AppliedProjected);
			const FRotator AppliedRotation = Director->GetActorRotation();
			Record->SetNumberField(TEXT("camera_index"),
			                       static_cast<double>(ConsumedCameraIndex));
			Record->SetNumberField(TEXT("camera_applied_north_m"),
			                       AppliedProjected.Y - CameraOriginYMetres);
			Record->SetNumberField(TEXT("camera_applied_east_m"),
			                       AppliedProjected.X - CameraOriginXMetres);
			Record->SetNumberField(TEXT("camera_applied_alt_m"),
			                       AppliedProjected.Z);
			Record->SetNumberField(TEXT("camera_applied_yaw_deg"),
			                       FMath::Fmod(AppliedRotation.Yaw + 90.0 + 360.0, 360.0));
			Record->SetNumberField(TEXT("camera_applied_pitch_deg"),
			                       AppliedRotation.Pitch);
			Record->SetNumberField(TEXT("camera_applied_roll_deg"),
			                       AppliedRotation.Roll);
		}
		Record->SetNumberField(TEXT("lit_pixels"), Lit);
		// Load factor and the wind actually inside the FDM this frame -- the
		// null tests (turbulence reached the FDM; the ridge's wind reached
		// the FDM) read these, not the scene.
		Record->SetNumberField(TEXT("n_z"),
		                       Scenario.ReadProperty(TEXT("accelerations/Nz")));
		Record->SetNumberField(TEXT("wind_down_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-down-fps")));
		// Phase 7 evidence channels: the turbulence realisation the FDM
		// integrated and the W20 the intensity coupling wrote.
		Record->SetNumberField(TEXT("turb_down_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/turb-down-fps")));
		Record->SetNumberField(TEXT("w20_fps"),
		                       Scenario.ReadProperty(
		                           TEXT("atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps")));
		// The flight-state channels the telemetry panel draws: what the FDM
		// actually did, per frame, to stand next to what the spec commanded.
		// Read from the FDM like everything else here -- never derived from
		// the scene.
		Record->SetNumberField(TEXT("altitude_m"),
		                       Scenario.ReadProperty(TEXT("position/h-sl-meters")));
		Record->SetNumberField(TEXT("cas_kt"),
		                       Scenario.ReadProperty(TEXT("velocities/vc-kts")));
		Record->SetNumberField(TEXT("tas_kt"),
		                       Scenario.ReadProperty(TEXT("velocities/vtrue-kts")));
		Record->SetNumberField(TEXT("heading_deg"),
		                       Scenario.ReadProperty(TEXT("attitude/psi-rad")) * RenderRadiansToDegrees);
		Record->SetNumberField(TEXT("agl_m"),
		                       Scenario.ReadProperty(TEXT("position/h-agl-ft")) * 0.3048);
		Record->SetNumberField(TEXT("wind_north_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-north-fps")));
		Record->SetNumberField(TEXT("wind_east_fps"),
		                       Scenario.ReadProperty(TEXT("atmosphere/wind-east-fps")));

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
	if (MeshAirframe.bLoaded)
	{
		Root->SetStringField(TEXT("airframe"),
		                     FString::Printf(TEXT("%s (FDM %s)"),
		                                     *MeshAirframe.MeshAirframe,
		                                     *MeshAirframe.FdmName));
		TSharedPtr<FJsonObject> Mesh = MakeShared<FJsonObject>();
		Mesh->SetStringField(TEXT("name"), MeshAirframe.Name);
		Mesh->SetStringField(TEXT("mesh_airframe"), MeshAirframe.MeshAirframe);
		Mesh->SetStringField(TEXT("fdm"), MeshAirframe.FdmName);
		Mesh->SetStringField(TEXT("license"), MeshAirframe.License);
		Mesh->SetStringField(TEXT("repo"), MeshAirframe.Repo);
		Mesh->SetStringField(TEXT("commit"), MeshAirframe.Commit);
		Root->SetObjectField(TEXT("mesh"), Mesh);
	}
	else
	{
		Root->SetStringField(TEXT("airframe"), TEXT("placeholder boxes, not a visual asset"));
	}
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
	// Camera Phase 1, additive: which solved camera this pass consumed
	// (numbers only -- gotcha 13; camera id strings live in the
	// Python-written capture manifest).
	Root->SetBoolField(TEXT("camera_consume_poses"), bConsumePoses);
	if (bConsumePoses)
	{
		Root->SetNumberField(TEXT("camera_index"),
		                     static_cast<double>(ConsumedCameraIndex));
	}
	TSharedPtr<FJsonObject> Scene = MakeShared<FJsonObject>();
	Scene->SetBoolField(TEXT("visual"), bVisual);
	Scene->SetStringField(TEXT("shot"), Shot);
	Scene->SetBoolField(TEXT("dynamic_shadows"), !bNoShadows);
	Scene->SetBoolField(TEXT("aircraft_hidden"), bHideAircraft);
	Scene->SetStringField(TEXT("exposure"), (bVisual && !bAutoExposure)
		? *FString::Printf(TEXT("manual, AutoExposureBias %.1f"), ExposureBias)
		: TEXT("auto (default metering)"));
	if (bVisual && !TerrainPath.IsEmpty())
	{
		Scene->SetStringField(TEXT("terrain_sha256"), VisualScene.TerrainSha256);
		Scene->SetNumberField(TEXT("terrain_peak_m"), VisualScene.TerrainPeakMetres);
		Scene->SetBoolField(TEXT("terrain_georeferenced"), bGeorefTerrain);
		if (bGeorefTerrain)
		{
			Scene->SetStringField(TEXT("terrain_crs"), VisualScene.TerrainCrs);
			Scene->SetStringField(TEXT("terrain_name"), VisualScene.TerrainName);
			if (!VisualScene.ImagerySha256.IsEmpty())
			{
				Scene->SetStringField(TEXT("terrain_material"),
					TEXT("true-colour satellite imagery drape (see imagery_* "
					     "fields; acquisition-date and resolution limits in "
					     "VALIDITY.md)"));
				Scene->SetStringField(TEXT("imagery_dataset"), VisualScene.ImageryDataset);
				Scene->SetStringField(TEXT("imagery_file"), VisualScene.ImageryFile);
				Scene->SetStringField(TEXT("imagery_sha256"), VisualScene.ImagerySha256);
				Scene->SetStringField(TEXT("imagery_license"), VisualScene.ImageryLicense);
				Scene->SetStringField(TEXT("imagery_attribution"), VisualScene.ImageryAttribution);
			}
			else
			{
				Scene->SetStringField(TEXT("terrain_material"),
					TEXT("slope/altitude classified vertex colours (approximated)"));
			}
			// Honesty label carried per clip: the mountains on screen are the
			// real raster, the ground the GEAR model feels is still the
			// spec's flat slab. Wind coupling is separate and stated below.
			Scene->SetStringField(TEXT("physics_ground"),
				TEXT("flat slab at spec terrain_elevation; visual terrain "
				     "carries no collision"));
		}
	}
	if (bVisual)
	{
		Scene->SetNumberField(TEXT("fog_density"), FogDensity);
		if (bSunOverride)
		{
			Scene->SetNumberField(TEXT("sun_elevation_deg"), SunElevationDeg);
			Scene->SetNumberField(TEXT("sun_azimuth_deg"), SunAzimuthDeg);
		}
		Scene->SetBoolField(TEXT("sun_animated"), bSunAnimated);
		if (bSunAnimated)
		{
			Scene->SetNumberField(TEXT("sun_elevation_end_deg"), SunElevationEndDeg);
			Scene->SetNumberField(TEXT("sun_azimuth_end_deg"), SunAzimuthEndDeg);
		}
	}
	Scene->SetStringField(TEXT("camera_preset"), CameraPreset);
	Scene->SetBoolField(TEXT("camera_inherits_roll"),
	                    !Director->PresetKeepsHorizonLevel());
	Root->SetObjectField(TEXT("scene"), Scene);

	// Environmental couplings, stated per run rather than assumed.
	TSharedPtr<FJsonObject> Environment = MakeShared<FJsonObject>();
	Environment->SetStringField(TEXT("turbulence"), Card.Turbulence);
	if (Card.Turbulence != TEXT("none"))
	{
		Environment->SetNumberField(TEXT("turbulence_seed"),
		                            static_cast<double>(Card.TurbulenceSeed));
		Environment->SetStringField(TEXT("turbulence_parity"),
			TEXT("visual/telemetry run; host parity for turbulence is decided "
			     "by the harness, not assumed here"));
	}
	Environment->SetNumberField(TEXT("wind_speed_kt"), Card.WindSpeedKnots);
	Environment->SetNumberField(TEXT("wind_from_deg"), Card.WindFromDegrees);
	Environment->SetBoolField(TEXT("wind_schedule"),
	                          Card.WindScheduleTimes.Num() > 0);
	Environment->SetBoolField(TEXT("orographic"), Card.bOrographic);
	if (bNoOrographic)
	{
		Environment->SetStringField(TEXT("orographic_note"),
			TEXT("null-test control: card's orographic coupling severed by "
			     "-NoOrographic"));
	}
	if (OrographicSelftest.Num() > 0)
	{
		Environment->SetArrayField(TEXT("orographic_selftest"), OrographicSelftest);
	}
	Environment->SetBoolField(TEXT("downburst"), Card.bDownburst);
	if (Card.bDownburst)
	{
		Environment->SetStringField(TEXT("downburst_delivery"),
			TEXT("position-coupled: field evaluated at the aircraft's actual "
			     "position each step (the nominal-track label is obsolete for "
			     "this clip)"));
		Environment->SetNumberField(TEXT("downburst_core_radius_m"),
		                            Card.DownburstCoreRadiusMetres);
		Environment->SetNumberField(TEXT("downburst_outflow_max_mps"),
		                            Card.DownburstOutflowMaxMps);
		Environment->SetNumberField(TEXT("downburst_outflow_height_m"),
		                            Card.DownburstOutflowHeightMetres);
		Environment->SetArrayField(TEXT("downburst_selftest"), DownburstSelftest);
	}
	Environment->SetBoolField(TEXT("rotor"), Card.bRotor);
	if (Card.bRotor)
	{
		Environment->SetStringField(TEXT("rotor_delivery"),
			TEXT("per-step W20 from the lee-sink field; seed and pinned "
			     "severity written once (JSBSIM_CORRECTIONS section 13); coupling "
			     "valid below 300 m AGL"));
		Environment->SetArrayField(TEXT("rotor_selftest"), RotorSelftest);
	}
	Environment->SetBoolField(TEXT("log_profile"), Card.bLogProfile);
	if (Card.bLogProfile)
	{
		Environment->SetArrayField(TEXT("log_profile_selftest"), LogProfileSelftest);
	}
	Environment->SetBoolField(TEXT("thermals"), Card.bThermals);
	if (Card.bThermals)
	{
		Environment->SetNumberField(TEXT("thermals_count"),
		                            Card.ThermalNorthMetres.Num());
		Environment->SetArrayField(TEXT("thermals_selftest"), ThermalsSelftest);
	}
	Environment->SetBoolField(TEXT("turbulence_schedule"),
	                          Card.TurbulenceScheduleTimes.Num() > 0);
	if (Card.TurbulenceScheduleTimes.Num() > 0)
	{
		Environment->SetStringField(TEXT("turbulence_schedule_delivery"),
			TEXT("per-step W20 only, held until the next entry; the seed and "
			     "the pinned severity are written exactly once (section 13)"));
	}
	Environment->SetBoolField(TEXT("orographic_follow_schedule"),
	                          Card.bOrographicFollowSchedule);
	Root->SetObjectField(TEXT("environment"), Environment);
	Root->SetArrayField(TEXT("frame_records"), FrameRecords);

	if (RunRecorder != nullptr && !RunRecorder->WriteToDisk())
	{
		return Fail(FString::Printf(TEXT("run telemetry did not write to '%s'"),
		                            *RunTelemetryPath));
	}
	if (RunRecorder != nullptr)
	{
		Root->SetStringField(TEXT("telemetry"), RunTelemetryPath);
	}

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
