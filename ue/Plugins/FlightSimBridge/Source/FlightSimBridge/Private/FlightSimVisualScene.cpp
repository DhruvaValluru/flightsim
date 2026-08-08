#include "FlightSimVisualScene.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GeoReferencingSystem.h"
#include "ImageUtils.h"
#include "MaterialDomain.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	// Named distinctly from the near-identical constant in the sibling
	// files: a unity build merges these anonymous namespaces into one
	// translation unit, where same-named definitions collide.
	constexpr double SceneCmPerMetre = 100.0;

	// Triangle budget for the Gate 6 offset instances: the raster is
	// decimated to at most this many vertices per side. 257^2 verts is ~130k
	// triangles per instance -- and Gate 6's measurements passed on exactly
	// this geometry, so it stays.
	constexpr int32 MaxVerticesPerSide = 257;

	// Budget for the georeferenced instance: a real 1276x905 scene raster at
	// 257 would drop to ~150 m mesh posting and visibly melt the ridgelines.
	// 701 keeps a 30 m GLO-30 raster at stride 2 (60 m posting, ~580k
	// triangles, still comfortable for a static procedural mesh) with
	// normals still computed from the full-resolution data.
	constexpr int32 MaxVerticesPerSideGeoreferenced = 701;

	// Slope/altitude classification (Phase 6B.2). Deliberately simple and
	// stated as approximated in every manifest: rock above the slope limit,
	// snow above the sidecar's snowline where it can settle, scrub in a band
	// below the snowline, valley vegetation under it.
	//
	// The palette was CALIBRATED against rendered frames rather than derived:
	// the mesh sRGB-encodes vertex colours on store, the material reads the
	// bytes back raw, and at 5-20 km the atmosphere and fog add blue
	// in-scatter on top -- so a theoretically-correct albedo rendered navy
	// (measured) and the naive linear palette rendered mint (measured). The
	// values below are the middle that reads as rock / forest / snow in the
	// actual scene, and the classification is labeled approximated in every
	// manifest regardless.
	FLinearColor ClassifyVertex(double ElevationMetres, double SlopeDegrees,
	                            double SnowlineMetres)
	{
		const FLinearColor Snow(0.75f, 0.78f, 0.82f);
		const FLinearColor Rock(0.068f, 0.060f, 0.053f);
		const FLinearColor Scrub(0.058f, 0.068f, 0.034f);
		const FLinearColor Valley(0.030f, 0.078f, 0.022f);

		if (SnowlineMetres > 0.0 && ElevationMetres > SnowlineMetres - 150.0 &&
		    SlopeDegrees < 52.0)
		{
			// Blend across a 300 m band around the snowline so the line is a
			// transition, not a contour cut. A plain linear-space lerp: the
			// HSV route rotated olive-to-white through mint.
			const float Blend = FMath::Clamp(
				static_cast<float>((ElevationMetres - (SnowlineMetres - 150.0)) / 300.0),
				0.0f, 1.0f);
			const FLinearColor Under = SlopeDegrees > 34.0 ? Rock : Scrub;
			return FMath::Lerp(Under, Snow, Blend);
		}
		if (SlopeDegrees > 34.0)
		{
			return Rock;
		}
		if (SnowlineMetres > 0.0 && ElevationMetres > SnowlineMetres - 900.0)
		{
			return Scrub;
		}
		return Valley;
	}
}

bool FFlightSimVisualScene::Build(UWorld* World,
                                  const FFlightSimVisualSceneOptions& Options,
                                  FString& Error)
{
	// -- sun ---------------------------------------------------------------
	// One light. §6.6: Atmosphere Sun Light true, and it must cast shadows --
	// "its absence was a major tell in the old footage" is about the
	// aircraft's shadow specifically.
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
	SunLight->SetDynamicShadowDistanceMovableLight(20000.0f * SceneCmPerMetre);
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
	// milky; a low falloff so the haze reaches flight altitude. Density is an
	// option because the showcase sweeps clear against hazy; both values are
	// recorded in the manifest.
	AExponentialHeightFog* Fog = World->SpawnActor<AExponentialHeightFog>();
	UExponentialHeightFogComponent* FogComponent = Fog->GetComponent();
	FogComponent->SetMobility(EComponentMobility::Movable);
	FogComponent->SetFogDensity(Options.FogDensity);
	FogComponent->SetFogHeightFalloff(0.0002f);
	FogComponent->SetFogMaxOpacity(0.92f);
	FogComponent->SetStartDistance(1500.0f * SceneCmPerMetre);
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
	// Gate 6's scene: the plain the aircraft's shadow lands on, at Z=0.
	// Georeferenced scenes get their backstop plane after the raster loads,
	// below its minimum elevation -- a 100 km plane at the origin's height
	// would bury the real valley floors.
	if (!Options.bGeoreferenced)
	{
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
	}

	// -- terrain -----------------------------------------------------------
	if (Options.TerrainPath.IsEmpty())
	{
		UE_LOG(LogFlightSimRender, Warning,
		       TEXT("no terrain heightfield given; the terrain clauses of "
		            "Gate 6 cannot be met by this render"));
		return true;
	}

	if (!Terrain.Load(Options.TerrainPath, Error))
	{
		return false;
	}
	TerrainSha256 = Terrain.Sha256;
	TerrainCrs = Terrain.Crs;
	TerrainName = Terrain.Name;

	uint16 Peak = 0;
	int32 PeakIndex = 0;
	for (int32 i = 0; i < Terrain.Samples.Num(); ++i)
	{
		if (Terrain.Samples[i] > Peak) { Peak = Terrain.Samples[i]; PeakIndex = i; }
	}
	TerrainPeakMetres = Peak * Terrain.ScaleMetres + Terrain.OffsetMetres;
	const int32 PeakRow = PeakIndex / Terrain.Width;
	const int32 PeakColumn = PeakIndex % Terrain.Width;

	if (Options.bGeoreferenced)
	{
		if (Options.GeoReferencing == nullptr)
		{
			Error = TEXT("georeferenced terrain needs the scenario world's "
			             "AGeoReferencingSystem, and none was passed");
			return false;
		}
		if (Terrain.Crs.IsEmpty() || !Terrain.bProjected)
		{
			Error = FString::Printf(
				TEXT("'%s' carries no projected CRS; it cannot be placed at a ")
				TEXT("true position. Bake it through the DEM pipeline."),
				*Options.TerrainPath);
			return false;
		}
		// The raster peak's true engine position, for the manifest landmark.
		const double PeakX = Terrain.OriginXMetres + PeakColumn * Terrain.PixelSizeMetres;
		const double PeakY = Terrain.OriginYMetres - PeakRow * Terrain.PixelSizeMetres;
		Options.GeoReferencing->ProjectedToEngine(
			FVector(PeakX, PeakY, TerrainPeakMetres), NearPeakWorldCm);
		FarPeakWorldCm = FVector::ZeroVector;
		if (!BuildGeoreferencedTerrain(World, Options, Error))
		{
			return false;
		}

		// Beyond the raster's 40 km the world would otherwise be empty
		// atmosphere, which reads as ocean around an island. A matte plane
		// just under the raster's lowest elevation stands in for the
		// surrounding lowlands -- scenery, labeled as such by the manifest's
		// terrain extent; it carries no collision and no claim.
		UStaticMesh* PlaneMesh = LoadObject<UStaticMesh>(
			nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
		if (PlaneMesh != nullptr)
		{
			AActor* Backstop = World->SpawnActor<AActor>();
			UStaticMeshComponent* BackstopMesh =
				NewObject<UStaticMeshComponent>(Backstop, TEXT("DistantGround"));
			Backstop->SetRootComponent(BackstopMesh);
			BackstopMesh->SetMobility(EComponentMobility::Movable);
			BackstopMesh->SetStaticMesh(PlaneMesh);
			BackstopMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			BackstopMesh->RegisterComponent();
			// Origin altitude is the spec's terrain elevation, so engine Z of
			// an MSL height h is (h - origin altitude), near the origin.
			const double MinElevation = Terrain.OffsetMetres;
			FVector OriginEngine;
			Options.GeoReferencing->GeographicToEngine(
				FGeographicCoordinates(Options.GeoReferencing->OriginLongitude,
				                       Options.GeoReferencing->OriginLatitude,
				                       MinElevation - 40.0),
				OriginEngine);
			Backstop->SetActorLocation(OriginEngine);
			Backstop->SetActorScale3D(FVector(400000.0, 400000.0, 1.0));
		}
	}
	else
	{
		auto PeakWorld = [&](const FVector2D& OriginMetres)
		{
			return FVector((OriginMetres.X + PeakColumn * Terrain.PixelSizeMetres) * SceneCmPerMetre,
			               (OriginMetres.Y + (Terrain.Height - 1 - PeakRow) * Terrain.PixelSizeMetres) * SceneCmPerMetre,
			               TerrainPeakMetres * SceneCmPerMetre);
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
	}
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("terrain %dx%d at %.0f m/px, elevations %.0f..%.0f m, sha %s%s"),
	       Terrain.Width, Terrain.Height, Terrain.PixelSizeMetres,
	       Terrain.OffsetMetres, TerrainPeakMetres, *TerrainSha256.Left(12),
	       Options.bGeoreferenced ? TEXT(" (georeferenced)") : TEXT(""));
	return true;
}

bool FFlightSimVisualScene::BuildTerrainInstance(UWorld* World, const FString& Name,
                                                 const FVector2D& OriginMetres,
                                                 FString& Error)
{
	const int32 Stride = FMath::Max(1,
		FMath::DivideAndRoundUp(FMath::Max(Terrain.Width, Terrain.Height),
		                        MaxVerticesPerSide));
	const int32 Columns = (Terrain.Width - 1) / Stride + 1;
	const int32 Rows = (Terrain.Height - 1) / Stride + 1;

	auto ElevationCm = [this](int32 Row, int32 Column) -> double
	{
		return Terrain.SampleMetres(Row, Column) * SceneCmPerMetre;
	};

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	Vertices.Reserve(Rows * Columns);
	Normals.Reserve(Rows * Columns);
	UV0.Reserve(Rows * Columns);

	// Row 0 of the raster is the northernmost (core/terrain/heightfield.py);
	// engine +Y is north, so row r sits at origin_y + (RasterHeight-1-r)*pixel.
	for (int32 Row = 0; Row < Terrain.Height; Row += Stride)
	{
		for (int32 Column = 0; Column < Terrain.Width; Column += Stride)
		{
			const double X = (OriginMetres.X + Column * Terrain.PixelSizeMetres) * SceneCmPerMetre;
			const double Y = (OriginMetres.Y +
				(Terrain.Height - 1 - Row) * Terrain.PixelSizeMetres) * SceneCmPerMetre;
			Vertices.Add(FVector(X, Y, ElevationCm(Row, Column)));
			UV0.Add(FVector2D(Column / double(Terrain.Width),
			                  Row / double(Terrain.Height)));

			// Central-difference normal from the full-resolution raster, so
			// shading responds to slopes the decimated mesh smooths over.
			const int32 RowN = FMath::Max(Row - Stride, 0);
			const int32 RowS = FMath::Min(Row + Stride, Terrain.Height - 1);
			const int32 ColW = FMath::Max(Column - Stride, 0);
			const int32 ColE = FMath::Min(Column + Stride, Terrain.Width - 1);
			const double DzDx = (ElevationCm(Row, ColE) - ElevationCm(Row, ColW)) /
				((ColE - ColW) * Terrain.PixelSizeMetres * SceneCmPerMetre);
			const double DzDy = (ElevationCm(RowN, Column) - ElevationCm(RowS, Column)) /
				((RowS - RowN) * Terrain.PixelSizeMetres * SceneCmPerMetre);
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

	AActor* TerrainActor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh =
		NewObject<UProceduralMeshComponent>(TerrainActor, *Name);
	TerrainActor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0,
	                                    {}, {}, false /* no collision */);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(true);
	Mesh->SetMaterial(0, UMaterial::GetDefaultMaterial(EMaterialDomain::MD_Surface));
	Mesh->RegisterComponent();
	TerrainActor->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("%s: %d verts, %d triangles (stride %d) at (%.0f, %.0f) m"),
	       *Name, Vertices.Num(), Triangles.Num() / 3, Stride,
	       OriginMetres.X, OriginMetres.Y);
	return true;
}

bool FFlightSimVisualScene::BuildGeoreferencedTerrain(
	UWorld* World, const FFlightSimVisualSceneOptions& Options, FString& Error)
{
	const int32 Stride = FMath::Max(1,
		FMath::DivideAndRoundUp(FMath::Max(Terrain.Width, Terrain.Height),
		                        MaxVerticesPerSideGeoreferenced));
	const int32 Columns = (Terrain.Width - 1) / Stride + 1;
	const int32 Rows = (Terrain.Height - 1) / Stride + 1;

	UMaterialInterface* Material =
		UMaterial::GetDefaultMaterial(EMaterialDomain::MD_Surface);
	const bool bImagery = !Options.ImagerySidecarPath.IsEmpty();
	if (bImagery)
	{
		// True-colour drape (Phase 7 1.1). The sidecar names the verified
		// PNG and carries the provenance the manifest must repeat; a drape
		// that cannot be loaded refuses the run rather than silently
		// rendering the approximated classification under an imagery label.
		FString SidecarText;
		if (!FFileHelper::LoadFileToString(SidecarText, *Options.ImagerySidecarPath))
		{
			Error = FString::Printf(TEXT("imagery sidecar '%s' unreadable"),
			                        *Options.ImagerySidecarPath);
			return false;
		}
		TSharedPtr<FJsonObject> Sidecar;
		const TSharedRef<TJsonReader<>> Reader =
			TJsonReaderFactory<>::Create(SidecarText);
		if (!FJsonSerializer::Deserialize(Reader, Sidecar) || !Sidecar.IsValid())
		{
			Error = FString::Printf(TEXT("imagery sidecar '%s' is not valid JSON"),
			                        *Options.ImagerySidecarPath);
			return false;
		}
		const TSharedPtr<FJsonObject>* TextureInfo = nullptr;
		if (!Sidecar->TryGetObjectField(TEXT("texture"), TextureInfo))
		{
			Error = TEXT("imagery sidecar has no texture block");
			return false;
		}
		ImageryFile = (*TextureInfo)->GetStringField(TEXT("file"));
		ImagerySha256 = (*TextureInfo)->GetStringField(TEXT("sha256"));
		ImageryLicense = Sidecar->GetStringField(TEXT("license"));
		ImageryAttribution = Sidecar->GetStringField(TEXT("attribution"));
		ImageryDataset = Sidecar->GetStringField(TEXT("dataset"));

		const FString PngPath = FPaths::Combine(
			FPaths::GetPath(Options.ImagerySidecarPath), ImageryFile);
		UTexture2D* Texture = FImageUtils::ImportFileAsTexture2D(PngPath);
		if (Texture == nullptr)
		{
			Error = FString::Printf(TEXT("imagery texture '%s' failed to load"),
			                        *PngPath);
			return false;
		}
		UMaterialInterface* ImageryBase = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Game/FlightSim/M_TerrainImagery.M_TerrainImagery"));
		if (ImageryBase == nullptr)
		{
			Error = TEXT(
				"/Game/FlightSim/M_TerrainImagery is missing. Run "
				"scripts/ue_create_materials.py (build-time asset step).");
			return false;
		}
		UMaterialInstanceDynamic* Instance =
			UMaterialInstanceDynamic::Create(ImageryBase, World);
		Instance->SetTextureParameterValue(TEXT("Imagery"), Texture);
		Material = Instance;
	}
	else if (Options.bClassifiedMaterial)
	{
		UMaterialInterface* VertexColour = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Game/FlightSim/M_VertexColor.M_VertexColor"));
		if (VertexColour == nullptr)
		{
			Error = TEXT(
				"/Game/FlightSim/M_VertexColor is missing. Run "
				"scripts/ue_create_materials.py (build-time asset step) -- "
				"falling back silently to the default material would render "
				"the classification invisibly wrong.");
			return false;
		}
		Material = VertexColour;
	}

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	TArray<FLinearColor> Colours;
	Vertices.Reserve(Rows * Columns);
	Normals.Reserve(Rows * Columns);
	UV0.Reserve(Rows * Columns);
	Colours.Reserve(Rows * Columns);

	AGeoReferencingSystem* Geo = Options.GeoReferencing;
	// A calm card never told the scenario world about this raster's CRS (only
	// orographic cards do), so make the projected frame match the terrain
	// here. Placing UTM-32N coordinates through a default CRS would put the
	// Matterhorn in the wrong country with no error message.
	if (Geo->ProjectedCRS != Terrain.Crs)
	{
		Geo->ProjectedCRS = Terrain.Crs;
		Geo->ApplySettings();
	}
	for (int32 Row = 0; Row < Terrain.Height; Row += Stride)
	{
		for (int32 Column = 0; Column < Terrain.Width; Column += Stride)
		{
			const double X = Terrain.OriginXMetres + Column * Terrain.PixelSizeMetres;
			const double Y = Terrain.OriginYMetres - Row * Terrain.PixelSizeMetres;
			const double Elevation = Terrain.SampleMetres(Row, Column);

			// True position: projected CRS -> engine, through the same PROJ
			// context that places the aircraft. Curvature over a 40 km scene
			// is real (~30 m of drop at the edges) and comes out of this
			// transform rather than being approximated away.
			FVector Engine;
			Geo->ProjectedToEngine(FVector(X, Y, Elevation), Engine);
			Vertices.Add(Engine);
			UV0.Add(FVector2D(Column / double(Terrain.Width),
			                  Row / double(Terrain.Height)));

			const int32 RowN = FMath::Max(Row - Stride, 0);
			const int32 RowS = FMath::Min(Row + Stride, Terrain.Height - 1);
			const int32 ColW = FMath::Max(Column - Stride, 0);
			const int32 ColE = FMath::Min(Column + Stride, Terrain.Width - 1);
			const double DzDx =
				(Terrain.SampleMetres(Row, ColE) - Terrain.SampleMetres(Row, ColW)) /
				((ColE - ColW) * Terrain.PixelSizeMetres);
			const double DzDy =
				(Terrain.SampleMetres(RowN, Column) - Terrain.SampleMetres(RowS, Column)) /
				((RowS - RowN) * Terrain.PixelSizeMetres);
			Normals.Add(FVector(-DzDx, -DzDy, 1.0).GetSafeNormal());

			const double SlopeDegrees =
				FMath::RadiansToDegrees(FMath::Atan(FMath::Sqrt(DzDx * DzDx + DzDy * DzDy)));
			Colours.Add(Options.bClassifiedMaterial
				? ClassifyVertex(Elevation, SlopeDegrees, Terrain.SnowlineMetres)
				: FLinearColor::White);
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
			// Same orientation logic as the offset instances: row index
			// increases southward, engine +Y is north.
			Triangles.Append({A, C, B, B, C, D});
		}
	}

	AActor* TerrainActor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh =
		NewObject<UProceduralMeshComponent>(TerrainActor, TEXT("TerrainGeoreferenced"));
	TerrainActor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0,
	                                    Colours, {}, false /* no collision */);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(true);
	Mesh->SetMaterial(0, Material);
	Mesh->RegisterComponent();
	TerrainActor->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("TerrainGeoreferenced: %d verts, %d triangles (stride %d, %s, "
	            "snowline %.0f m, classified %s)"),
	       Vertices.Num(), Triangles.Num() / 3, Stride, *Terrain.Crs,
	       Terrain.SnowlineMetres,
	       Options.bClassifiedMaterial ? TEXT("yes") : TEXT("no"));
	return true;
}

void FFlightSimVisualScene::ApplyManualExposure(USceneCaptureComponent2D* Capture,
                                                float Bias)
{
	// §6.6: manual exposure. Auto-exposure re-metering as the bright-ground /
	// dark-sky ratio changes with bank is exactly the "breathing" Gate 6
	// forbids. The bias is a scene parameter (11.0 suits Gate 6's low sun;
	// noon over snowfields wants less) and is recorded in the manifest; what
	// matters for the gate is that it is CONSTANT over a clip.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = Bias;
}
