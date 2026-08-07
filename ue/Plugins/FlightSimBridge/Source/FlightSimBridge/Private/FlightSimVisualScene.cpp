#include "FlightSimVisualScene.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "MaterialDomain.h"
#include "Materials/Material.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	constexpr double CmPerMetre = 100.0;

	// Triangle budget: the raster is decimated to at most this many vertices
	// per side. 257^2 verts is ~130k triangles per instance -- comfortably
	// renderable, and the decimation stride is recorded in the log so nobody
	// mistakes the rendered relief for the full-resolution physics raster.
	constexpr int32 MaxVerticesPerSide = 257;
}

bool FFlightSimVisualScene::Build(UWorld* World,
                                  const FFlightSimVisualSceneOptions& Options,
                                  FString& Error)
{
	// -- sun ---------------------------------------------------------------
	// One light, low, from the north-west (see header). §6.6: Atmosphere Sun
	// Light true, and it must cast shadows -- "its absence was a major tell
	// in the old footage" is about the aircraft's shadow specifically.
	Sun = World->SpawnActor<ADirectionalLight>();
	Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
	Sun->SetActorRotation(Options.SunRotation);
	UDirectionalLightComponent* SunLight =
		Cast<UDirectionalLightComponent>(Sun->GetLightComponent());
	SunLight->SetIntensity(8.0f);
	SunLight->SetAtmosphereSunLight(true);
	SunLight->SetCastShadows(Options.bDynamicShadows);
	// No Nanite in a procedural-mesh scene, so per §6.6's own fallback this
	// is plain dynamic CSM rather than Virtual Shadow Maps. Push the dynamic
	// shadow range far enough to cover the near ridge.
	SunLight->SetDynamicShadowDistanceMovableLight(20000.0f * CmPerMetre);
	SunLight->SetDynamicShadowCascades(6);

	// -- atmosphere --------------------------------------------------------
	AActor* AtmosphereActor = World->SpawnActor<AActor>();
	USkyAtmosphereComponent* Atmosphere =
		NewObject<USkyAtmosphereComponent>(AtmosphereActor, TEXT("SkyAtmosphere"));
	AtmosphereActor->SetRootComponent(Atmosphere);
	Atmosphere->SetMobility(EComponentMobility::Movable);
	// §6.6 gotcha 2: Planet Top at Component Transform, with the component at
	// actual ground level, so the haze transition does not cut a hard line.
	Atmosphere->TransformMode =
		ESkyAtmosphereTransformMode::PlanetTopAtComponentTransform;
	AtmosphereActor->SetActorLocation(FVector::ZeroVector);
	// §6.6: real Earth values -- a shrunk planet makes altitude falloff wrong.
	Atmosphere->BottomRadius = 6360.0f;      // km
	Atmosphere->AtmosphereHeight = 60.0f;    // km
	// §6.6: multiscattering on; sky going black away from the sun is a tell.
	Atmosphere->MultiScatteringFactor = 1.0f;
	// §6.6 gotcha 1: transmittance evaluated from the camera's position, or
	// the ground blacks out at altitude from georeferenced origins.
	Atmosphere->TransmittanceMinLightElevationAngle = 90.0f;
	Atmosphere->RegisterComponent();

	// -- height fog --------------------------------------------------------
	// §6.6: the primary long-range haze. Max opacity below 1 so distant
	// terrain keeps faint detail; a start distance so the foreground is not
	// milky; a low falloff so the haze reaches flight altitude.
	AExponentialHeightFog* Fog = World->SpawnActor<AExponentialHeightFog>();
	UExponentialHeightFogComponent* FogComponent = Fog->GetComponent();
	FogComponent->SetMobility(EComponentMobility::Movable);
	FogComponent->SetFogDensity(0.0025f);
	FogComponent->SetFogHeightFalloff(0.0002f);
	FogComponent->SetFogMaxOpacity(0.92f);
	FogComponent->SetStartDistance(1500.0f * CmPerMetre);
	Fog->SetActorLocation(FVector(0, 0, 0));

	// -- sky light ---------------------------------------------------------
	ASkyLight* Sky = World->SpawnActor<ASkyLight>();
	USkyLightComponent* SkyComponent = Sky->GetLightComponent();
	SkyComponent->SetMobility(EComponentMobility::Movable);
	// Real Time Capture per §6.6, so the sky light follows the atmosphere
	// rather than a flat ambient term.
	SkyComponent->SetRealTimeCapture(true);
	SkyComponent->SetIntensity(1.0f);

	// -- visible ground ----------------------------------------------------
	// The plain the aircraft's shadow lands on. Visual only: the physics
	// ground is the invisible query slab the scenario world spawned, and the
	// two coincide at Z = 0 by the same georeferencing origin.
	UStaticMesh* PlaneMesh = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
	if (PlaneMesh == nullptr)
	{
		Error = TEXT("/Engine/BasicShapes/Plane.Plane did not load");
		return false;
	}
	AActor* Ground = World->SpawnActor<AActor>();
	UStaticMeshComponent* GroundMesh =
		NewObject<UStaticMeshComponent>(Ground, TEXT("VisibleGround"));
	Ground->SetRootComponent(GroundMesh);
	GroundMesh->SetMobility(EComponentMobility::Movable);
	GroundMesh->SetStaticMesh(PlaneMesh);
	GroundMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	GroundMesh->RegisterComponent();
	Ground->SetActorLocation(FVector(0.0, 0.0, 0.0));
	// The engine plane is 1 m; 100 km on a side reaches past the far ridge.
	Ground->SetActorScale3D(FVector(100000.0, 100000.0, 1.0));

	// -- terrain -----------------------------------------------------------
	if (Options.TerrainPath.IsEmpty())
	{
		UE_LOG(LogFlightSimRender, Warning,
		       TEXT("no terrain heightfield given; the terrain clauses of "
		            "Gate 6 cannot be met by this render"));
		return true;
	}

	const FString Base = FPaths::ChangeExtension(Options.TerrainPath, TEXT(""));
	FString SidecarText;
	if (!FFileHelper::LoadFileToString(SidecarText, *(Base + TEXT(".json"))))
	{
		Error = FString::Printf(TEXT("cannot read heightfield sidecar '%s.json'"), *Base);
		return false;
	}
	TSharedPtr<FJsonObject> Sidecar;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(SidecarText);
	if (!FJsonSerializer::Deserialize(Reader, Sidecar) || !Sidecar.IsValid())
	{
		Error = FString::Printf(TEXT("'%s.json' is not valid JSON"), *Base);
		return false;
	}
	FString Magic;
	Sidecar->TryGetStringField(TEXT("magic"), Magic);
	if (Magic != TEXT("flightsim-heightfield"))
	{
		Error = FString::Printf(
			TEXT("'%s.json' is not a flightsim heightfield sidecar (magic '%s'). ")
			TEXT("The rendered terrain must come from the same baked raster the ")
			TEXT("physics pipeline produces, not from an arbitrary file."),
			*Base, *Magic);
		return false;
	}
	RasterWidth = Sidecar->GetIntegerField(TEXT("width"));
	RasterHeight = Sidecar->GetIntegerField(TEXT("height"));
	ScaleMetres = Sidecar->GetNumberField(TEXT("scale_m"));
	OffsetMetres = Sidecar->GetNumberField(TEXT("offset_m"));
	Sidecar->TryGetStringField(TEXT("sha256"), TerrainSha256);
	const TSharedPtr<FJsonObject>* Geo = nullptr;
	if (Sidecar->TryGetObjectField(TEXT("georeference"), Geo))
	{
		PixelSizeMetres = (*Geo)->GetNumberField(TEXT("pixel_size_m"));
	}
	if (RasterWidth < 2 || RasterHeight < 2 || PixelSizeMetres <= 0.0)
	{
		Error = TEXT("heightfield sidecar is missing its dimensions");
		return false;
	}

	TArray<uint8> Raw;
	if (!FFileHelper::LoadFileToArray(Raw, *(Base + TEXT(".r16"))))
	{
		Error = FString::Printf(TEXT("cannot read heightfield raster '%s.r16'"), *Base);
		return false;
	}
	if (Raw.Num() != RasterWidth * RasterHeight * 2)
	{
		Error = FString::Printf(
			TEXT("'%s.r16' is %d bytes; the sidecar promises %d (%dx%d uint16). ")
			TEXT("Refusing to render a raster that disagrees with its own record."),
			*Base, Raw.Num(), RasterWidth * RasterHeight * 2,
			RasterWidth, RasterHeight);
		return false;
	}
	Samples.SetNumUninitialized(RasterWidth * RasterHeight);
	FMemory::Memcpy(Samples.GetData(), Raw.GetData(), Raw.Num());

	uint16 Peak = 0;
	int32 PeakIndex = 0;
	for (int32 i = 0; i < Samples.Num(); ++i)
	{
		if (Samples[i] > Peak) { Peak = Samples[i]; PeakIndex = i; }
	}
	TerrainPeakMetres = Peak * ScaleMetres + OffsetMetres;
	const int32 PeakRow = PeakIndex / RasterWidth;
	const int32 PeakColumn = PeakIndex % RasterWidth;
	auto PeakWorld = [&](const FVector2D& OriginMetres)
	{
		return FVector((OriginMetres.X + PeakColumn * PixelSizeMetres) * CmPerMetre,
		               (OriginMetres.Y + (RasterHeight - 1 - PeakRow) * PixelSizeMetres) * CmPerMetre,
		               TerrainPeakMetres * CmPerMetre);
	};
	NearPeakWorldCm = PeakWorld(Options.NearTerrainOriginMetres);
	FarPeakWorldCm = PeakWorld(Options.FarTerrainOriginMetres);

	if (!BuildTerrainInstance(World, TEXT("TerrainNear"),
	                          Options.NearTerrainOriginMetres, Error) ||
	    !BuildTerrainInstance(World, TEXT("TerrainFar"),
	                          Options.FarTerrainOriginMetres, Error))
	{
		return false;
	}
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("terrain %dx%d at %.0f m/px, elevations %.0f..%.0f m, sha %s"),
	       RasterWidth, RasterHeight, PixelSizeMetres, OffsetMetres,
	       TerrainPeakMetres, *TerrainSha256.Left(12));
	return true;
}

bool FFlightSimVisualScene::BuildTerrainInstance(UWorld* World, const FString& Name,
                                                 const FVector2D& OriginMetres,
                                                 FString& Error)
{
	const int32 Stride = FMath::Max(1,
		FMath::DivideAndRoundUp(FMath::Max(RasterWidth, RasterHeight),
		                        MaxVerticesPerSide));
	const int32 Columns = (RasterWidth - 1) / Stride + 1;
	const int32 Rows = (RasterHeight - 1) / Stride + 1;

	auto ElevationCm = [this](int32 Row, int32 Column) -> double
	{
		const uint16 Sample = Samples[Row * RasterWidth + Column];
		return (Sample * ScaleMetres + OffsetMetres) * CmPerMetre;
	};

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	Vertices.Reserve(Rows * Columns);
	Normals.Reserve(Rows * Columns);
	UV0.Reserve(Rows * Columns);

	// Row 0 of the raster is the northernmost (core/terrain/heightfield.py);
	// engine +Y is north, so row r sits at origin_y + (RasterHeight-1-r)*pixel.
	for (int32 Row = 0; Row < RasterHeight; Row += Stride)
	{
		for (int32 Column = 0; Column < RasterWidth; Column += Stride)
		{
			const double X = (OriginMetres.X + Column * PixelSizeMetres) * CmPerMetre;
			const double Y = (OriginMetres.Y +
				(RasterHeight - 1 - Row) * PixelSizeMetres) * CmPerMetre;
			Vertices.Add(FVector(X, Y, ElevationCm(Row, Column)));
			UV0.Add(FVector2D(Column / double(RasterWidth),
			                  Row / double(RasterHeight)));

			// Central-difference normal from the full-resolution raster, so
			// shading responds to slopes the decimated mesh smooths over.
			const int32 RowN = FMath::Max(Row - Stride, 0);
			const int32 RowS = FMath::Min(Row + Stride, RasterHeight - 1);
			const int32 ColW = FMath::Max(Column - Stride, 0);
			const int32 ColE = FMath::Min(Column + Stride, RasterWidth - 1);
			const double DzDx = (ElevationCm(Row, ColE) - ElevationCm(Row, ColW)) /
				((ColE - ColW) * PixelSizeMetres * CmPerMetre);
			const double DzDy = (ElevationCm(RowN, Column) - ElevationCm(RowS, Column)) /
				((RowS - RowN) * PixelSizeMetres * CmPerMetre);
			Normals.Add(FVector(-DzDx, -DzDy, 1.0).GetSafeNormal());
		}
	}

	TArray<int32> Triangles;
	Triangles.Reserve((Rows - 1) * (Columns - 1) * 6);
	for (int32 Row = 0; Row < Rows - 1; ++Row)
	{
		for (int32 Column = 0; Column < Columns - 1; ++Column)
		{
			const int32 A = Row * Columns + Column;
			const int32 B = A + 1;
			const int32 C = A + Columns;
			const int32 D = C + 1;
			// Wound so the face normal comes out +Z: row index increases
			// SOUTHWARD (raster row 0 is northernmost), so the naive A,B,C
			// order faces down and the terrain is invisible from above --
			// which is exactly how the first probe frame came out.
			Triangles.Append({A, C, B, B, C, D});
		}
	}

	AActor* Terrain = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh =
		NewObject<UProceduralMeshComponent>(Terrain, *Name);
	Terrain->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0,
	                                    {}, {}, false /* no collision */);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(true);
	Mesh->SetMaterial(0, UMaterial::GetDefaultMaterial(EMaterialDomain::MD_Surface));
	Mesh->RegisterComponent();
	Terrain->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("%s: %d verts, %d triangles (stride %d) at (%.0f, %.0f) m"),
	       *Name, Vertices.Num(), Triangles.Num() / 3, Stride,
	       OriginMetres.X, OriginMetres.Y);
	return true;
}

void FFlightSimVisualScene::ApplyManualExposure(USceneCaptureComponent2D* Capture)
{
	// §6.6: manual exposure. Auto-exposure re-metering as the bright-ground /
	// dark-sky ratio changes with bank is exactly the "breathing" Gate 6
	// forbids. The bias is tuned for this scene's sun and recorded in the
	// manifest; what matters for the gate is that it is CONSTANT.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = 11.0f;
}
