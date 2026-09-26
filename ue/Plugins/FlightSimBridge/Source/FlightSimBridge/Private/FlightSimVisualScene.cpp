#include "FlightSimVisualScene.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SceneComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Dom/JsonObject.h"
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

	// Phase 2 (contracts §10): the georeferenced instance is no longer one
	// section capped at 701 vertices per side (stride 2 on a 30 m GLO-30
	// raster = 60 m posting). It is TILED: one UProceduralMeshComponent per
	// tile of at most this many vertices a side (255 quads, ~130k
	// triangles), at the smallest stride whose triangle count fits the
	// options' budget (4 M by default: a 1276x905 raster at stride 1 is
	// 2.3 M triangles, so native 30 m posting). One component per tile,
	// not one section per tile, so each tile has its own bounds and the
	// renderer can frustum-cull it. The achieved stride and posting are
	// RECORDED (TerrainPostingMetres), never assumed.
	constexpr int32 SceneTerrainTileVerticesPerSide = 256;

	// The engine's default volumetric cloud material, the one the
	// component's own constructor loads; named here so a component that
	// came up without it can be refused BY NAME rather than drawing nothing.
	const TCHAR* const SceneDefaultCloudMaterialPath =
		TEXT("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.m_SimpleVolumetricCloud_Inst");

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

	// The first scalar parameter of a material whose name contains (or,
	// when bExact, equals) Needle, case-insensitively. NAME_None when the
	// material exposes no such parameter -- the caller records "absent"
	// rather than setting a scalar that drives nothing and calling it
	// applied.
	FName FindScalarParameter(const UMaterialInterface* Material,
	                          const TCHAR* Needle, bool bExact)
	{
		if (Material == nullptr)
		{
			return NAME_None;
		}
		TArray<FMaterialParameterInfo> Infos;
		TArray<FGuid> Ids;
		Material->GetAllScalarParameterInfo(Infos, Ids);
		for (const FMaterialParameterInfo& Info : Infos)
		{
			const FString Name = Info.Name.ToString();
			const bool bMatch = bExact
				? Name.Equals(Needle, ESearchCase::IgnoreCase)
				: Name.Contains(Needle, ESearchCase::IgnoreCase);
			if (bMatch)
			{
				return Info.Name;
			}
		}
		return NAME_None;
	}

	TSharedPtr<FJsonObject> NewRecord()
	{
		return MakeShared<FJsonObject>();
	}
}

double FFlightSimVisualScene::ExposureValue100(double ApertureF, double ShutterSeconds,
                                               double Iso)
{
	// EV100 = log2(N^2 / t * 100 / ISO): core/capture/exposure.py's formula,
	// re-implemented, not imported (the test pins this expression).
	return FMath::Log2((ApertureF * ApertureF / ShutterSeconds) * (100.0 / Iso));
}

bool FFlightSimVisualScene::Build(UWorld* World,
                                  const FFlightSimVisualSceneOptions& Options,
                                  FString& Error)
{
	LookApplied = NewRecord();

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
	// The procedural terrain is a Movable non-Nanite mesh, so the cascade
	// settings below are what shadow it when virtual shadow maps are off
	// (VALIDITY §2.13); with r.Shadow.Virtual.Enable=1 (DefaultEngine.ini,
	// Look lane part 1) the renderer decides, and render.json's
	// render_settings records which value it found. Push the dynamic
	// shadow range far enough to cover the near ridge.
	SunLight->SetDynamicShadowDistanceMovableLight(20000.0f * SceneCmPerMetre);
	SunLight->SetDynamicShadowCascades(6);
	{
		TSharedPtr<FJsonObject> SunRecord = NewRecord();
		SunRecord->SetNumberField(TEXT("sun_elevation_deg"), -Options.SunRotation.Pitch);
		SunRecord->SetNumberField(TEXT("engine_sun_yaw_deg"), Options.SunRotation.Yaw);
		SunRecord->SetStringField(TEXT("component"), TEXT("ADirectionalLight (existing sun)"));
		SunRecord->SetBoolField(TEXT("cast_shadows"), Options.bDynamicShadows);
		LookApplied->SetObjectField(TEXT("sun"), SunRecord);
	}

	// -- atmosphere --------------------------------------------------------
	AActor* AtmosphereActor = World->SpawnActor<AActor>();
	Atmosphere =
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
	// Phase 2 aerosol (contracts §5.4 row 1): the Mie scattering scale,
	// applied ONLY when the options carry one (the -aerosol= probe). The
	// card's look.aerosol is recorded by the commandlet and left unapplied:
	// the fog row already carries that extinction (double count), and the
	// value it takes for the Phase 10 default fog is in the hundreds.
	{
		TSharedPtr<FJsonObject> AerosolRecord = NewRecord();
		AerosolRecord->SetStringField(TEXT("component"),
			TEXT("USkyAtmosphereComponent::MieScatteringScale"));
		if (Options.AerosolMieScale >= 0.0)
		{
			Atmosphere->SetMieScatteringScale(static_cast<float>(Options.AerosolMieScale));
			AerosolRecord->SetNumberField(TEXT("mie_scattering_scale"), Options.AerosolMieScale);
			AerosolRecord->SetBoolField(TEXT("applied"), true);
		}
		else
		{
			AerosolRecord->SetNumberField(TEXT("mie_scattering_scale"), 1.0);
			AerosolRecord->SetBoolField(TEXT("applied"), false);
			AerosolRecord->SetStringField(TEXT("note"),
				TEXT("engine default 1.0; the fog row carries the extinction "
				     "(applying look.aerosol as well double counts)"));
		}
		LookApplied->SetObjectField(TEXT("aerosol"), AerosolRecord);
	}
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
	{
		TSharedPtr<FJsonObject> FogRecord = NewRecord();
		FogRecord->SetNumberField(TEXT("fog_density"), Options.FogDensity);
		FogRecord->SetStringField(TEXT("component"),
			TEXT("UExponentialHeightFogComponent::FogDensity"));
		FogRecord->SetNumberField(TEXT("fog_height_falloff"), 0.0002);
		FogRecord->SetNumberField(TEXT("fog_max_opacity"), 0.92);
		FogRecord->SetNumberField(TEXT("start_distance_m"), 1500.0);
		LookApplied->SetObjectField(TEXT("fog"), FogRecord);
	}

	// -- sky light ---------------------------------------------------------
	ASkyLight* Sky = World->SpawnActor<ASkyLight>();
	USkyLightComponent* SkyComponent = Sky->GetLightComponent();
	SkyComponent->SetMobility(EComponentMobility::Movable);
	// Real Time Capture per §6.6, so the sky light follows the atmosphere
	// rather than a flat ambient term.
	SkyComponent->SetRealTimeCapture(true);
	SkyComponent->SetIntensity(1.0f);

	// -- clouds (Phase 2, contracts §5.4 row 2) ------------------------------
	if (!BuildClouds(World, Options, Error))
	{
		return false;
	}

	// -- what this phase does NOT draw: recorded, not silent ---------------
	{
		TSharedPtr<FJsonObject> DriftRecord = NewRecord();
		DriftRecord->SetNumberField(TEXT("cloud_drift_mps"), Options.CloudDriftMps);
		DriftRecord->SetNumberField(TEXT("cloud_drift_from_deg"), Options.CloudDriftFromDeg);
		DriftRecord->SetBoolField(TEXT("applied"), false);
		DriftRecord->SetStringField(TEXT("note"),
			TEXT("not modelled this phase: no per-tick wind offset is written to "
			     "the cloud material"));
		LookApplied->SetObjectField(TEXT("cloud_drift"), DriftRecord);

		TSharedPtr<FJsonObject> NightRecord = NewRecord();
		NightRecord->SetBoolField(TEXT("stars_requested"), Options.bStarsRequested);
		NightRecord->SetBoolField(TEXT("moon_requested"), Options.bMoonRequested);
		NightRecord->SetStringField(TEXT("stars"), TEXT("not modelled"));
		NightRecord->SetStringField(TEXT("moon"), TEXT("not modelled"));
		NightRecord->SetStringField(TEXT("night_sky"),
			TEXT("the existing sun below the horizon only (sky atmosphere twilight)"));
		LookApplied->SetObjectField(TEXT("night"), NightRecord);

		TArray<TSharedPtr<FJsonValue>> NotClaimed;
		for (const TCHAR* Name : {TEXT("precipitation_particles"), TEXT("moon"),
		                          TEXT("stars"), TEXT("cloud_drift"), TEXT("sea_state"),
		                          TEXT("foliage_sway")})
		{
			NotClaimed.Add(MakeShared<FJsonValueString>(Name));
		}
		LookApplied->SetArrayField(TEXT("not_claimed"), NotClaimed);
	}

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

	// Precipitation is applied to the georeferenced terrain material below;
	// until (and unless) that runs, the record says it drove nothing.
	{
		TSharedPtr<FJsonObject> PrecipRecord = NewRecord();
		PrecipRecord->SetStringField(TEXT("precipitation"), Options.Precipitation);
		PrecipRecord->SetNumberField(TEXT("wetness"), Options.Wetness);
		PrecipRecord->SetBoolField(TEXT("particles"), false);
		PrecipRecord->SetStringField(TEXT("particles_note"),
			TEXT("not drawn this phase: no Niagara rain/snow asset exists in ue/Content"));
		PrecipRecord->SetStringField(TEXT("wetness_parameter"), TEXT("absent"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"),
			TEXT("nothing: no terrain material instance in this scene"));
		LookApplied->SetObjectField(TEXT("precipitation"), PrecipRecord);
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
		if (!BuildGeoreferencedTerrain(World, Options, Error))
		{
			return false;
		}
		// The raster peak's true engine position, for the manifest landmark.
		// Projected AFTER the terrain build, which is what aligns the
		// georeferencing system's projected CRS with the raster's -- a calm
		// card never told the scenario world the CRS, and projecting through
		// the default put the landmark tens of kilometres wrong (measured:
		// the summit landmark of a calm Matterhorn card reported bearings no
		// 4000er occupies).
		const double PeakX = Terrain.OriginXMetres + PeakColumn * Terrain.PixelSizeMetres;
		const double PeakY = Terrain.OriginYMetres - PeakRow * Terrain.PixelSizeMetres;
		Options.GeoReferencing->ProjectedToEngine(
			FVector(PeakX, PeakY, TerrainPeakMetres), NearPeakWorldCm);
		FarPeakWorldCm = FVector::ZeroVector;

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

bool FFlightSimVisualScene::BuildClouds(UWorld* World,
                                        const FFlightSimVisualSceneOptions& Options,
                                        FString& Error)
{
	TSharedPtr<FJsonObject> CloudRecord = NewRecord();
	CloudRecord->SetStringField(TEXT("component"),
		TEXT("UVolumetricCloudComponent (LayerBottomAltitude / LayerHeight; "
		     "coverage through the cloud material)"));
	CloudRecord->SetNumberField(TEXT("layers_requested"), Options.CloudLayers.Num());
	if (Options.CloudLayers.Num() == 0)
	{
		// No cloud component at all: the scene is byte-identical to Phase
		// 10's for every card without a cloud layer.
		CloudRecord->SetBoolField(TEXT("drawn"), false);
		LookApplied->SetObjectField(TEXT("clouds"), CloudRecord);
		return true;
	}

	const FFlightSimCloudLayer& Layer = Options.CloudLayers[0];
	if (!(Layer.CoverFraction >= 0.0 && Layer.CoverFraction <= 1.0) ||
	    !(Layer.TopMetres > Layer.BaseMetres))
	{
		Error = FString::Printf(
			TEXT("look.clouds: layer cover %.3f (0..1) with base %.0f m and top %.0f m ")
			TEXT("(top must exceed base) cannot be drawn"),
			Layer.CoverFraction, Layer.BaseMetres, Layer.TopMetres);
		return false;
	}

	AActor* CloudActor = World->SpawnActor<AActor>();
	Clouds = NewObject<UVolumetricCloudComponent>(CloudActor, TEXT("VolumetricCloud"));
	CloudActor->SetRootComponent(Clouds);
	Clouds->SetMobility(EComponentMobility::Movable);
	CloudActor->SetActorLocation(FVector::ZeroVector);
	// Layer geometry in km above the planet surface -- the atmosphere's
	// planet top sits at this scene's Z = 0 (PlanetTopAtComponentTransform,
	// spec terrain_elevation_m), so base_m is height above that datum.
	Clouds->SetLayerBottomAltitude(static_cast<float>(Layer.BaseMetres / 1000.0));
	Clouds->SetLayerHeight(static_cast<float>((Layer.TopMetres - Layer.BaseMetres) / 1000.0));

	// The engine's default cloud material: the component's constructor
	// loads it; a build where it did not is refused by name, because a
	// cloud component with no material draws nothing while "clouds: on"
	// would be recorded.
	UMaterialInterface* CloudMaterial = Clouds->Material;
	if (CloudMaterial == nullptr)
	{
		CloudMaterial = LoadObject<UMaterialInterface>(nullptr, SceneDefaultCloudMaterialPath);
	}
	if (CloudMaterial == nullptr)
	{
		Error = FString::Printf(
			TEXT("look.clouds: the engine's default volumetric cloud material %s did not ")
			TEXT("load; refusing to record a cloud layer that draws nothing"),
			SceneDefaultCloudMaterialPath);
		return false;
	}
	// Coverage goes through the material. The default material's parameter
	// names are the engine's, not this file's: the first scalar parameter
	// whose name contains "cover" is set to the layer's cover fraction and
	// its name recorded; when the material exposes none, that is recorded
	// as "absent" and only the layer geometry is applied -- stated, so the
	// Gate 6 cover clause grades a known state rather than a guess.
	const FName CoverParameter = FindScalarParameter(CloudMaterial, TEXT("cover"), false);
	UMaterialInstanceDynamic* CloudInstance = UMaterialInstanceDynamic::Create(CloudMaterial, World);
	if (CoverParameter != NAME_None)
	{
		CloudInstance->SetScalarParameterValue(CoverParameter,
		                                       static_cast<float>(Layer.CoverFraction));
		CloudRecord->SetStringField(TEXT("cover_parameter"), CoverParameter.ToString());
	}
	else
	{
		CloudRecord->SetStringField(TEXT("cover_parameter"), TEXT("absent"));
		UE_LOG(LogFlightSimRender, Warning,
		       TEXT("look.clouds: the cloud material %s exposes no scalar parameter named ")
		       TEXT("*cover*; the layer geometry is applied, the cover fraction is NOT"),
		       *CloudMaterial->GetPathName());
	}
	Clouds->SetMaterial(CloudInstance);
	Clouds->RegisterComponent();

	// Cloud shadows on the directional light (contracts §5.4: "cloud shadows
	// on"): the sun's own cloud shadow map, so the terrain darkens under the
	// layer. Whether it does is the Gate 6 cloud clause's measurement.
	UDirectionalLightComponent* SunLight =
		Sun != nullptr ? Cast<UDirectionalLightComponent>(Sun->GetLightComponent()) : nullptr;
	if (SunLight != nullptr)
	{
		SunLight->SetCastCloudShadows(true);
		SunLight->SetCloudShadowStrength(1.0f);
	}

	CloudRecord->SetBoolField(TEXT("drawn"), true);
	CloudRecord->SetNumberField(TEXT("cover"), Layer.CoverFraction);
	CloudRecord->SetNumberField(TEXT("base_m"), Layer.BaseMetres);
	CloudRecord->SetNumberField(TEXT("top_m"), Layer.TopMetres);
	CloudRecord->SetNumberField(TEXT("layer_bottom_altitude_km"), Layer.BaseMetres / 1000.0);
	CloudRecord->SetNumberField(TEXT("layer_height_km"),
	                            (Layer.TopMetres - Layer.BaseMetres) / 1000.0);
	CloudRecord->SetStringField(TEXT("base_datum"),
		TEXT("engine Z=0 (the spec's terrain_elevation_m; planet top at the "
		     "atmosphere component)"));
	CloudRecord->SetStringField(TEXT("material"), CloudMaterial->GetPathName());
	CloudRecord->SetBoolField(TEXT("cloud_shadows"), SunLight != nullptr);
	CloudRecord->SetNumberField(TEXT("layers_drawn"), 1);
	if (Options.CloudLayers.Num() > 1)
	{
		CloudRecord->SetStringField(TEXT("note"),
			TEXT("one UVolumetricCloudComponent draws one layer; layers beyond the "
			     "first are recorded, not drawn"));
	}
	LookApplied->SetObjectField(TEXT("clouds"), CloudRecord);
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("clouds: cover %.2f, base %.0f m, top %.0f m, cover parameter %s, ")
	       TEXT("cloud shadows on"),
	       Layer.CoverFraction, Layer.BaseMetres, Layer.TopMetres,
	       CoverParameter != NAME_None ? *CoverParameter.ToString() : TEXT("absent"));
	return true;
}

UMaterialInterface* FFlightSimVisualScene::ApplyWetness(
	UWorld* World, UMaterialInterface* Material,
	const FFlightSimVisualSceneOptions& Options)
{
	TSharedPtr<FJsonObject> PrecipRecord = NewRecord();
	PrecipRecord->SetStringField(TEXT("precipitation"), Options.Precipitation);
	PrecipRecord->SetNumberField(TEXT("wetness"), Options.Wetness);
	PrecipRecord->SetBoolField(TEXT("particles"), false);
	PrecipRecord->SetStringField(TEXT("particles_note"),
		TEXT("not drawn this phase: no Niagara rain/snow asset exists in ue/Content"));
	PrecipRecord->SetStringField(TEXT("component"),
		TEXT("Wetness scalar on the georeferenced terrain material instance"));

	UMaterialInterface* Result = Material;
	if (Options.Wetness <= 0.0)
	{
		// Dry: the material is untouched (byte-identical to Phase 10).
		PrecipRecord->SetStringField(TEXT("wetness_parameter"), TEXT("not set (dry)"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"), TEXT("nothing (wetness 0)"));
	}
	else
	{
		// A scalar set on a material that exposes no such parameter drives
		// nothing; that state is recorded as "absent", never as applied.
		const FName Parameter = FindScalarParameter(Material, TEXT("Wetness"), true);
		UMaterialInstanceDynamic* Instance = Cast<UMaterialInstanceDynamic>(Material);
		if (Instance == nullptr)
		{
			Instance = UMaterialInstanceDynamic::Create(Material, World);
		}
		Instance->SetScalarParameterValue(TEXT("Wetness"), static_cast<float>(Options.Wetness));
		Result = Instance;
		PrecipRecord->SetStringField(TEXT("wetness_parameter"),
			Parameter != NAME_None ? *Parameter.ToString() : TEXT("absent"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"),
			Parameter != NAME_None
				? TEXT("TerrainGeoreferenced material instance")
				: TEXT("TerrainGeoreferenced material instance, which exposes no "
				       "Wetness parameter: the scalar drives nothing"));
		if (Parameter == NAME_None)
		{
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("precipitation '%s': the terrain material %s exposes no 'Wetness' ")
			       TEXT("scalar; wetness %.2f was set on the instance and drives nothing"),
			       *Options.Precipitation, *Material->GetPathName(), Options.Wetness);
		}
	}
	LookApplied->SetObjectField(TEXT("precipitation"), PrecipRecord);
	return Result;
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
	if (Terrain.Width < 2 || Terrain.Height < 2)
	{
		Error = FString::Printf(TEXT("terrain raster %dx%d has no quads to triangulate"),
		                        Terrain.Width, Terrain.Height);
		return false;
	}
	// Phase 2 (contracts §10): the smallest stride whose triangle count fits
	// the stated budget -- native posting (stride 1) on every raster the
	// budget admits, and the ACHIEVED stride recorded, never the intended.
	const int32 Budget = FMath::Max(1, Options.TerrainTriangleBudget);
	int32 Stride = 1;
	for (;; ++Stride)
	{
		const int64 StrideColumns = (Terrain.Width - 1) / Stride + 1;
		const int64 StrideRows = (Terrain.Height - 1) / Stride + 1;
		const int64 StrideTriangles = (StrideColumns - 1) * (StrideRows - 1) * 2;
		if (StrideTriangles <= Budget || Stride >= FMath::Max(Terrain.Width, Terrain.Height))
		{
			break;
		}
	}
	const int32 Columns = (Terrain.Width - 1) / Stride + 1;
	const int32 Rows = (Terrain.Height - 1) / Stride + 1;
	TerrainStride = Stride;
	TerrainPostingMetres = Stride * Terrain.PixelSizeMetres;

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
	// Phase 2: the precipitation wetness scalar, on whichever material the
	// terrain draws with (a dynamic instance is made when needed); recorded.
	Material = ApplyWetness(World, Material, Options);

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

	// Tiles: the decimated grid cut into blocks of at most
	// SceneTerrainTileVerticesPerSide vertices a side, neighbours sharing
	// their edge row/column (so there is no seam), one procedural mesh
	// component per tile under one scene root. Normals were computed from
	// the full raster above, so shading is continuous across tile edges.
	AActor* TerrainActor = World->SpawnActor<AActor>();
	USceneComponent* Root =
		NewObject<USceneComponent>(TerrainActor, TEXT("TerrainGeoreferenced"));
	TerrainActor->SetRootComponent(Root);
	Root->SetMobility(EComponentMobility::Movable);
	Root->RegisterComponent();

	const int32 TileSpan = SceneTerrainTileVerticesPerSide - 1;   // quads per tile side
	const int32 TileRows = FMath::DivideAndRoundUp(Rows - 1, TileSpan);
	const int32 TileColumns = FMath::DivideAndRoundUp(Columns - 1, TileSpan);
	TerrainTiles = 0;
	TerrainTriangles = 0;
	for (int32 TileRow = 0; TileRow < TileRows; ++TileRow)
	{
		for (int32 TileColumn = 0; TileColumn < TileColumns; ++TileColumn)
		{
			const int32 Row0 = TileRow * TileSpan;
			const int32 Row1 = FMath::Min(Row0 + TileSpan, Rows - 1);        // inclusive
			const int32 Col0 = TileColumn * TileSpan;
			const int32 Col1 = FMath::Min(Col0 + TileSpan, Columns - 1);     // inclusive
			const int32 TileRowCount = Row1 - Row0 + 1;
			const int32 TileColumnCount = Col1 - Col0 + 1;
			if (TileRowCount < 2 || TileColumnCount < 2)
			{
				continue;
			}

			TArray<FVector> TileVertices;
			TArray<FVector> TileNormals;
			TArray<FVector2D> TileUV0;
			TArray<FLinearColor> TileColours;
			TileVertices.Reserve(TileRowCount * TileColumnCount);
			TileNormals.Reserve(TileRowCount * TileColumnCount);
			TileUV0.Reserve(TileRowCount * TileColumnCount);
			TileColours.Reserve(TileRowCount * TileColumnCount);
			for (int32 Row = Row0; Row <= Row1; ++Row)
			{
				for (int32 Column = Col0; Column <= Col1; ++Column)
				{
					const int32 Index = Row * Columns + Column;
					TileVertices.Add(Vertices[Index]);
					TileNormals.Add(Normals[Index]);
					TileUV0.Add(UV0[Index]);
					TileColours.Add(Colours[Index]);
				}
			}

			TArray<int32> TileTriangles;
			TileTriangles.Reserve((TileRowCount - 1) * (TileColumnCount - 1) * 6);
			for (int32 Row = 0; Row < TileRowCount - 1; ++Row)
			{
				for (int32 Column = 0; Column < TileColumnCount - 1; ++Column)
				{
					const int32 A = Row * TileColumnCount + Column;
					const int32 B = A + 1;
					const int32 C = A + TileColumnCount;
					const int32 D = C + 1;
					// Same orientation logic as the offset instances: row index
					// increases southward, engine +Y is north.
					TileTriangles.Append({A, C, B, B, C, D});
				}
			}

			UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(
				TerrainActor, *FString::Printf(TEXT("TerrainTile_r%d_c%d"), TileRow, TileColumn));
			Mesh->SetupAttachment(Root);
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->CreateMeshSection_LinearColor(0, TileVertices, TileTriangles, TileNormals,
			                                    TileUV0, TileColours, {},
			                                    false /* no collision */);
			Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Mesh->SetCastShadow(true);
			Mesh->SetMaterial(0, Material);
			Mesh->RegisterComponent();
			++TerrainTiles;
			TerrainTriangles += TileTriangles.Num() / 3;
		}
	}
	TerrainActor->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("TerrainGeoreferenced: %d verts, %d triangles in %d tiles (stride %d = ")
	       TEXT("%.0f m posting, budget %d, %s, snowline %.0f m, classified %s)"),
	       Vertices.Num(), TerrainTriangles, TerrainTiles, Stride, TerrainPostingMetres,
	       Budget, *Terrain.Crs, Terrain.SnowlineMetres,
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

double FFlightSimVisualScene::ApplyPhysicalExposure(USceneCaptureComponent2D* Capture,
                                                    double ApertureF,
                                                    double ShutterSeconds, double Iso)
{
	// Manual metering from the physical camera: the engine computes
	// EV100 = log2(N^2 / t * 100 / ISO) from these three when
	// AutoExposureApplyPhysicalCameraExposure is on, and the bias is pinned
	// to zero so nothing is added to it. Like the bias path this is constant
	// over a clip; unlike it, the number is the card's, not a probe's. The
	// extended luminance range (r.DefaultFeature.AutoExposure.
	// ExtendDefaultLuminanceRange, DefaultEngine.ini) sets the calibration
	// this EV100 is interpreted against; the commandlet reads that CVar back
	// into render.json rather than assuming it here.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	Settings.AutoExposureApplyPhysicalCameraExposure = 1.0f;
	Settings.bOverride_CameraShutterSpeed = true;
	Settings.CameraShutterSpeed = static_cast<float>(1.0 / ShutterSeconds);
	Settings.bOverride_CameraISO = true;
	Settings.CameraISO = static_cast<float>(Iso);
	Settings.bOverride_DepthOfFieldFstop = true;
	Settings.DepthOfFieldFstop = static_cast<float>(ApertureF);
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = 0.0f;
	return ExposureValue100(ApertureF, ShutterSeconds, Iso);
}
