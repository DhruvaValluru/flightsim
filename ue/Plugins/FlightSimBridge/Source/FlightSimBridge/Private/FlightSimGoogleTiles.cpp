#include "FlightSimGoogleTiles.h"

#include "Async/TaskGraphInterfaces.h"
#include "Containers/Ticker.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "GeoReferencingSystem.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
// The beauty look (ApplyBeautyLook, visual overhaul world lane): the plugin's
// .uplugin read for its version, and Cesium reached by reflection.
#include "Dom/JsonValue.h"
#include "HAL/FileManager.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UnrealType.h"
// round-2b terrain-ocean (ApplyBeautyGround, beauty only): the haze it thins
// and the sea cap it draws.
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "ProceduralMeshComponent.h"
#include "UObject/UObjectIterator.h"

#ifndef WITH_FLIGHTSIM_CESIUM
#define WITH_FLIGHTSIM_CESIUM 0
#endif

#if WITH_FLIGHTSIM_CESIUM
#include "Cesium3DTileset.h"
#include "CesiumCamera.h"
#include "CesiumCameraManager.h"
#include "CesiumGeoreference.h"
#endif

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimGoogleTiles, Log, All);

namespace
{
	const TCHAR* GoogleTilesRootUrl = TEXT("https://tile.googleapis.com/v1/3dtiles/root.json");
	// The same Google Photorealistic 3D Tiles, served through Cesium ion
	// (asset 2275207): a Cesium ion access token instead of a Google key.
	constexpr int64 GoogleTilesIonAssetId = 2275207;
	const TCHAR* TerrainTag = TEXT("FlightSim.terrain");
	// Pump interval and how long the view must stay fully loaded: Cesium
	// refines in steps (a loaded parent selects its children next tick), so
	// one 100 % reading can precede the next level's requests.
	constexpr float PumpSeconds = 1.0f / 30.0f;
	constexpr int32 SettledPumps = 15;
	// Cesium never retries a tile whose request failed (a dropped
	// connection leaves the view stuck short of 100 % for good), so a view
	// whose progress has not moved for this long is reloaded from scratch,
	// at most MaxTileRefreshes times per frame. Long enough that a slow
	// but live download of one large tile is not thrown away.
	constexpr double StallRefreshSeconds = 30.0;
	constexpr int32 MaxTileRefreshes = 4;

	double EnvNumber(const TCHAR* Name, double Default)
	{
		const FString Value = FPlatformMisc::GetEnvironmentVariable(Name).TrimStartAndEnd();
		if (Value.IsEmpty() || !Value.IsNumeric())
		{
			return Default;
		}
		return FCString::Atod(*Value);
	}
}

bool FFlightSimGoogleTiles::Requested()
{
	// Every terrain render draws Google's tiles -- the owner's rule
	// (2026-10-09): on unless FLIGHTSIM_GOOGLE_TILES says off (the same
	// words core/scenario/card.py google_tiles_requested reads).
	const FString Value =
		FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_GOOGLE_TILES")).TrimStartAndEnd().ToLower();
	return !(Value == TEXT("0") || Value == TEXT("off") || Value == TEXT("false") || Value == TEXT("no"));
}

bool FFlightSimGoogleTiles::Available()
{
	return WITH_FLIGHTSIM_CESIUM != 0;
}

bool FFlightSimGoogleTiles::Enable(UWorld* World, AGeoReferencingSystem* GeoReferencing,
                                   double LatitudeDeg, double LongitudeDeg,
                                   double OrthometricHeightM, double InUndulationM,
                                   FString& Error)
{
#if WITH_FLIGHTSIM_CESIUM
	const FString Key =
		FPlatformMisc::GetEnvironmentVariable(TEXT("GOOGLE_MAPS_API_KEY")).TrimStartAndEnd();
	FString IonToken =
		FPlatformMisc::GetEnvironmentVariable(TEXT("CESIUM_ION_TOKEN")).TrimStartAndEnd();
	if (IonToken.IsEmpty())
	{
		IonToken = TEXT("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6IkZmOFBzdC1nc1pubFhMNDEiLCJqdGkiOiIyNjBkNDZmOC1kM2JhLTQ2Y2ItODU0NC1kMDY2MzE5NGNjNTMiLCJpZCI6NTE2NzAwLCJzdWIiOiJkanJ1dmEgdiIsImlzcyI6Imh0dHBzOi8vYXBpLmNlc2l1bS5jb20iLCJhdWQiOiJmbGlnaHRzaW0tbGFwdG9wIiwiaWF0IjoxNzkxMzgzNTMzfQ.iakg-iH34fdz6M_lWu169f67PznF-d2v-QGN2CN3qyo");
	}
	if (Key.IsEmpty() && IonToken.IsEmpty())
	{
		Error = TEXT("terrain.google_tiles: every terrain render draws Google's tiles, but neither ")
		        TEXT("GOOGLE_MAPS_API_KEY (a Google Maps Platform key with the Map Tiles API) nor ")
		        TEXT("CESIUM_ION_TOKEN (a Cesium ion access token) is set; set one, or ")
		        TEXT("FLIGHTSIM_GOOGLE_TILES=off for the baked ground");
		return false;
	}
	// A Google key is used directly; otherwise the ion token reaches the
	// same tiles through Cesium ion.
	bViaIon = Key.IsEmpty();
	if (World == nullptr || GeoReferencing == nullptr)
	{
		Error = TEXT("terrain.google_tiles: no world or georeference to place the tiles in");
		return false;
	}
	// Cesium places tiles east-south-up in the engine frame. The scene's
	// frame is the GeoReferencing plugin's; MEASURE its axes rather than
	// assume them, and refuse a frame the tiles would be mirrored in.
	FVector Origin, North, East;
	GeoReferencing->GeographicToEngine(
		FGeographicCoordinates(LongitudeDeg, LatitudeDeg, OrthometricHeightM), Origin);
	GeoReferencing->GeographicToEngine(
		FGeographicCoordinates(LongitudeDeg, LatitudeDeg + 0.001, OrthometricHeightM), North);
	GeoReferencing->GeographicToEngine(
		FGeographicCoordinates(LongitudeDeg + 0.001, LatitudeDeg, OrthometricHeightM), East);
	if (!(North.Y < Origin.Y) || !(East.X > Origin.X))
	{
		Error = FString::Printf(
			TEXT("terrain.google_tiles: the scene frame is not east-south-up (north moves Y by %.1f, ")
			TEXT("east moves X by %.1f); Cesium's tiles would be mirrored in it"),
			North.Y - Origin.Y, East.X - Origin.X);
		return false;
	}

	MaximumScreenSpaceError = FMath::Clamp(EnvNumber(TEXT("FLIGHTSIM_GOOGLE_TILES_SSE"), 8.0), 1.0, 64.0);
	TimeoutSeconds = FMath::Max(10.0, EnvNumber(TEXT("FLIGHTSIM_GOOGLE_TILES_TIMEOUT"), 180.0));
	OriginLatitudeDeg = LatitudeDeg;
	OriginLongitudeDeg = LongitudeDeg;
	UndulationM = InUndulationM;
	// Engine Z=0 is the orthometric terrain elevation at the origin; the
	// tiles are in WGS84 ellipsoidal heights, so the same point sits the
	// undulation higher on the ellipsoid.
	OriginEllipsoidHeightM = OrthometricHeightM + InUndulationM;

	ACesiumGeoreference* Georeference = ACesiumGeoreference::GetDefaultGeoreference(World);
	if (Georeference == nullptr)
	{
		Error = TEXT("terrain.google_tiles: Cesium did not provide a georeference");
		return false;
	}
	Georeference->SetOriginLongitudeLatitudeHeight(
		FVector(LongitudeDeg, LatitudeDeg, OriginEllipsoidHeightM));

	ACesium3DTileset* Tiles = World->SpawnActor<ACesium3DTileset>();
	if (Tiles == nullptr)
	{
		Error = TEXT("terrain.google_tiles: could not spawn the Cesium 3D tileset");
		return false;
	}
	Tiles->SetGeoreference(TSoftObjectPtr<ACesiumGeoreference>(Georeference));
	if (bViaIon)
	{
		Tiles->SetTilesetSource(ETilesetSource::FromCesiumIon);
		Tiles->SetIonAssetID(GoogleTilesIonAssetId);
		Tiles->SetIonAccessToken(IonToken);
	}
	else
	{
		Tiles->SetTilesetSource(ETilesetSource::FromUrl);
		Tiles->SetUrl(FString::Printf(TEXT("%s?key=%s"), GoogleTilesRootUrl, *Key));
	}
	Tiles->SetMaximumScreenSpaceError(MaximumScreenSpaceError);
	Tileset = Tiles;

	ACesiumCameraManager* Cameras = ACesiumCameraManager::GetDefaultCameraManager(World);
	if (Cameras == nullptr)
	{
		Error = TEXT("terrain.google_tiles: Cesium did not provide a camera manager");
		return false;
	}
	CameraManager = Cameras;
	FCesiumCamera Camera;
	Camera.ViewportSize = FVector2D(1280.0, 720.0);
	Camera.Location = FVector::ZeroVector;
	Camera.Rotation = FRotator::ZeroRotator;
	Camera.FieldOfViewDegrees = 60.0;
	CameraId = Cameras->AddCamera(Camera);

	bEnabled = true;
	UE_LOG(LogFlightSimGoogleTiles, Display,
	       TEXT("google tiles: origin %.6f, %.6f at %.1f m ellipsoidal (%.1f m orthometric + %.1f m ")
	       TEXT("undulation), maximum screen-space error %.1f"),
	       LatitudeDeg, LongitudeDeg, OriginEllipsoidHeightM, OrthometricHeightM, InUndulationM,
	       MaximumScreenSpaceError);
	return true;
#else
	Error = TEXT("terrain.google_tiles: every terrain render draws Google's tiles, but this build has no Cesium ")
	        TEXT("for Unreal plugin; install it into the engine (Fab: \"Cesium for Unreal\") and ")
	        TEXT("rebuild with scripts\\build_ue.ps1, or FLIGHTSIM_GOOGLE_TILES=off for the baked ground");
	return false;
#endif
}

int32 FFlightSimGoogleTiles::HideOwnTerrain(UWorld* World)
{
	HiddenActors = 0;
	if (World == nullptr)
	{
		return 0;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->ActorHasTag(FName(TerrainTag)))
		{
			It->SetActorHiddenInGame(true);
			++HiddenActors;
		}
	}
	UE_LOG(LogFlightSimGoogleTiles, Display,
	       TEXT("google tiles: hid %d actor(s) of the scene's own ground"), HiddenActors);
	return HiddenActors;
}

bool FFlightSimGoogleTiles::WaitForView(const FVector& Location, const FRotator& Rotation,
                                        double FieldOfViewDeg, int32 Width, int32 Height,
                                        FString& Error)
{
#if WITH_FLIGHTSIM_CESIUM
	ACesium3DTileset* Tiles = Cast<ACesium3DTileset>(Tileset.Get());
	ACesiumCameraManager* Cameras = Cast<ACesiumCameraManager>(CameraManager.Get());
	if (!bEnabled || Tiles == nullptr || Cameras == nullptr)
	{
		Error = TEXT("terrain.google_tiles: the tileset is gone");
		return false;
	}
	FCesiumCamera Camera;
	Camera.ViewportSize = FVector2D(static_cast<double>(Width), static_cast<double>(Height));
	Camera.Location = Location;
	Camera.Rotation = Rotation;
	Camera.FieldOfViewDegrees = FieldOfViewDeg;
	Cameras->UpdateCamera(CameraId, Camera);

	const double Start = FPlatformTime::Seconds();
	int32 Settled = 0;
	float Progress = 0.0f;
	float LastProgress = -1.0f;
	double LastMove = Start;
	int32 Refreshes = 0;
	while (true)
	{
		// What a running engine loop does for the plugin each frame: the
		// core ticker (the HTTP manager's completions), the game thread's
		// queued tasks (Cesium's main-thread continuations) and the
		// tileset's own tick (tile selection, loads, component creation).
		FTSTicker::GetCoreTicker().Tick(PumpSeconds);
		FTaskGraphInterface::Get().ProcessThreadUntilIdle(ENamedThreads::GameThread);
		Tiles->Tick(PumpSeconds);
		Progress = Tiles->GetLoadProgress();
		Settled = Progress >= 99.99f ? Settled + 1 : 0;
		if (Settled >= SettledPumps)
		{
			break;
		}
		const double Now = FPlatformTime::Seconds();
		if (Progress > LastProgress + 0.01f)
		{
			LastProgress = Progress;
			LastMove = Now;
		}
		else if (Progress < 99.99f && Now - LastMove > StallRefreshSeconds &&
		         Refreshes < MaxTileRefreshes)
		{
			++Refreshes;
			++TileRefreshes;
			UE_LOG(LogFlightSimGoogleTiles, Warning,
			       TEXT("google tiles: the view has been stuck at %.1f %% for %.0f s (a failed ")
			       TEXT("request is never retried by Cesium); reloading the tileset (%d of %d)"),
			       Progress, Now - LastMove, Refreshes, MaxTileRefreshes);
			Tiles->RefreshTileset();
			LastProgress = -1.0f;
			LastMove = Now;
		}
		const double Waited = Now - Start;
		if (Waited > TimeoutSeconds)
		{
			Error = FString::Printf(
				TEXT("terrain.google_tiles: the view was still %.1f %% loaded after %.0f s ")
				TEXT("(FLIGHTSIM_GOOGLE_TILES_TIMEOUT) and %d reload(s); check the key, the Map ")
				TEXT("Tiles API and the network, or raise the timeout"), Progress, Waited, Refreshes);
			return false;
		}
		FPlatformProcess::Sleep(0.005f);
	}
	const double Waited = FPlatformTime::Seconds() - Start;
	++FramesWaited;
	TotalWaitSeconds += Waited;
	LongestWaitSeconds = FMath::Max(LongestWaitSeconds, Waited);
	return true;
#else
	Error = TEXT("terrain.google_tiles: this build has no Cesium for Unreal plugin");
	return false;
#endif
}

TSharedPtr<FJsonObject> FFlightSimGoogleTiles::Record() const
{
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetBoolField(TEXT("enabled"), bEnabled);
	if (BeautyGround.IsValid())
	{
		// round-2b terrain-ocean: what the beauty render did so the ground reads.
		Out->SetObjectField(TEXT("beauty_ground"), BeautyGround);
	}
	if (!DeclinedReason.IsEmpty())
	{
		// Not drawn: the reason, and nothing claimed for tiles that were never
		// placed (no route, origin, waits or attribution).
		Out->SetStringField(TEXT("declined"), DeclinedReason);
		return Out;
	}
	Out->SetStringField(TEXT("source"), TEXT("Google Photorealistic 3D Tiles via Cesium for Unreal"));
	// Never the key or the token.
	Out->SetStringField(TEXT("route"), bViaIon ? TEXT("Cesium ion") : TEXT("Google Map Tiles API"));
	if (bViaIon)
	{
		Out->SetNumberField(TEXT("ion_asset_id"), static_cast<double>(GoogleTilesIonAssetId));
	}
	else
	{
		Out->SetStringField(TEXT("url"), GoogleTilesRootUrl);
	}
	Out->SetNumberField(TEXT("maximum_screen_space_error"), MaximumScreenSpaceError);
	Out->SetNumberField(TEXT("origin_lat_deg"), OriginLatitudeDeg);
	Out->SetNumberField(TEXT("origin_lon_deg"), OriginLongitudeDeg);
	Out->SetNumberField(TEXT("origin_ellipsoidal_height_m"), OriginEllipsoidHeightM);
	Out->SetNumberField(TEXT("undulation_used_m"), UndulationM);
	Out->SetNumberField(TEXT("hidden_scene_ground_actors"), HiddenActors);
	Out->SetNumberField(TEXT("frames_waited"), FramesWaited);
	Out->SetNumberField(TEXT("longest_wait_s"), LongestWaitSeconds);
	Out->SetNumberField(TEXT("total_wait_s"), TotalWaitSeconds);
	Out->SetNumberField(TEXT("tileset_reloads"), TileRefreshes);
	Out->SetStringField(TEXT("attribution"),
		TEXT("Imagery and 3D data: Google. Per-tile data-provider credits are shown by Cesium on ")
		TEXT("screen and are not drawn into these frames; the Google Maps Platform terms govern ")
		TEXT("display, attribution, caching and any derived use of these images."));
	Out->SetStringField(TEXT("not_claimed"),
		TEXT("the tiles' surface agrees with the baked heightfield the physics and the labels' ")
		TEXT("geometry use; the ground in the pixels is Google's, the ground the checks use is the bake"));
	return Out;
}

// -- visual overhaul, world lane (2026-11-09): the beauty look ----------------
// BEAUTY ONLY: FFlightSimWorldBeauty (FlightSimClouds.cpp) is the only caller
// and only -quality=beauty builds it. UNVERIFIED against Cesium for Unreal:
// its headers are not on the authoring machine, so nothing below names a
// Cesium symbol the existing code does not already use (ACesium3DTileset,
// RefreshTileset); the material and the smooth normals are reached through
// the engine's reflection by NAME, and the record says what was found.

FString FFlightSimGoogleTiles::CesiumPluginVersion()
{
	TArray<FString> Roots;
	Roots.Add(FPaths::ProjectPluginsDir());
	Roots.Add(FPaths::Combine(FPaths::EnginePluginsDir(), TEXT("Marketplace")));
	for (const FString& Root : Roots)
	{
		if (!IFileManager::Get().DirectoryExists(*Root))
		{
			continue;
		}
		TArray<FString> Found;
		IFileManager::Get().FindFilesRecursive(Found, *Root, TEXT("CesiumForUnreal.uplugin"), true, false);
		for (const FString& Path : Found)
		{
			FString Text;
			TSharedPtr<FJsonObject> Descriptor;
			FString VersionName;
			if (FFileHelper::LoadFileToString(Text, *Path) &&
			    FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Descriptor) &&
			    Descriptor.IsValid() && Descriptor->TryGetStringField(TEXT("VersionName"), VersionName))
			{
				return VersionName;
			}
		}
	}
	return FString();
}

TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyLook(UMaterialInterface* Material)
{
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	const FString Version = CesiumPluginVersion();
	Out->SetStringField(TEXT("cesium_version"), Version.IsEmpty() ? FString(TEXT("not found")) : Version);
	Out->SetStringField(TEXT("api_basis"),
		TEXT("UNVERIFIED: Cesium for Unreal reached by reflection by name (no Cesium headers on the ")
		TEXT("authoring machine); found/not found below is the render machine's answer"));
#if WITH_FLIGHTSIM_CESIUM
	ACesium3DTileset* Tiles = Cast<ACesium3DTileset>(Tileset.Get());
	if (!bEnabled || Tiles == nullptr)
	{
		Out->SetStringField(TEXT("applied"), TEXT("nothing: the tileset is not drawn"));
		return Out;
	}
	// "2.30.0" -> 2: the UE 5 material-layer generation of the plugin, the one
	// whose per-primitive material instances read the glTF parameters a
	// custom tileset material exposes (UNVERIFIED).
	const int32 Major = Version.IsEmpty() ? 0 : FCString::Atoi(*Version);
	if (Major < 2)
	{
		Out->SetStringField(TEXT("applied"),
			TEXT("nothing: the installed Cesium for Unreal is not 2.x or later (or was not found)"));
		return Out;
	}
	UClass* Class = Tiles->GetClass();
	bool bChanged = false;

	// The material: the setter when the class has one (it refreshes what it
	// must), else the property.
	FString MaterialRoute =
		TEXT("absent: M_FlightSimTilesBeauty did not load (run scripts/ue_create_materials.py)");
	if (Material != nullptr)
	{
		MaterialRoute = FString::Printf(TEXT("not found: no SetMaterial function or Material property on %s"),
		                                *Class->GetName());
		UFunction* Setter = Tiles->FindFunction(FName(TEXT("SetMaterial")));
		FObjectProperty* SetterParam = nullptr;
		if (Setter != nullptr && Setter->NumParms == 1)
		{
			for (TFieldIterator<FProperty> It(Setter); It; ++It)
			{
				SetterParam = CastField<FObjectProperty>(*It);
				break;
			}
		}
		if (SetterParam != nullptr && Material->IsA(SetterParam->PropertyClass))
		{
			TArray<uint8> Parms;
			Parms.SetNumZeroed(Setter->ParmsSize);
			SetterParam->SetObjectPropertyValue_InContainer(Parms.GetData(), Material);
			Tiles->ProcessEvent(Setter, Parms.GetData());
			MaterialRoute = TEXT("UFunction SetMaterial");
			bChanged = true;
		}
		else if (FObjectProperty* Property = FindFProperty<FObjectProperty>(Class, TEXT("Material")))
		{
			if (Material->IsA(Property->PropertyClass))
			{
				Property->SetObjectPropertyValue_InContainer(Tiles, Material);
				MaterialRoute = TEXT("UPROPERTY Material");
				bChanged = true;
			}
		}
		Out->SetStringField(TEXT("material"), Material->GetPathName());
	}
	Out->SetStringField(TEXT("material_route"), MaterialRoute);

	// Smooth normals: photogrammetry meshes carry no normals and Cesium's
	// flat ones facet the sun's shading.
	if (FBoolProperty* Smooth = FindFProperty<FBoolProperty>(Class, TEXT("GenerateSmoothNormals")))
	{
		Smooth->SetPropertyValue_InContainer(Tiles, true);
		Out->SetBoolField(TEXT("generate_smooth_normals"), true);
		bChanged = true;
	}
	else
	{
		Out->SetStringField(TEXT("generate_smooth_normals"), TEXT("not found: no bool GenerateSmoothNormals"));
	}
	// Lane B (2026-11-11): the beauty's finer tile selection. The non-urban
	// photogrammetry is the coarse LODs smeared over a slope; one step finer
	// is about 1.8x the tiles (UNCALIBRATED on the iGPU's shared memory: the
	// load wait and the frame's memory are in render.json). A stated
	// FLIGHTSIM_GOOGLE_TILES_SSE wins (the measure's setting, unchanged).
	{
		const bool bStated = !FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_GOOGLE_TILES_SSE"))
			.TrimStartAndEnd().IsEmpty();
		const double BeautySse = FMath::Clamp(EnvNumber(TEXT("FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE"), 6.0), 1.0, 64.0);
		TSharedPtr<FJsonObject> Sse = MakeShared<FJsonObject>();
		Sse->SetNumberField(TEXT("before"), MaximumScreenSpaceError);
		if (!bStated && BeautySse < MaximumScreenSpaceError)
		{
			MaximumScreenSpaceError = BeautySse;
			Tiles->SetMaximumScreenSpaceError(MaximumScreenSpaceError);
			bChanged = true;
			Sse->SetStringField(TEXT("applied"), TEXT("the beauty's (FLIGHTSIM_GOOGLE_TILES_BEAUTY_SSE, default 6)"));
		}
		else
		{
			Sse->SetStringField(TEXT("applied"), bStated
				? TEXT("nothing: FLIGHTSIM_GOOGLE_TILES_SSE states the error")
				: TEXT("nothing: the beauty's is not finer"));
		}
		Sse->SetNumberField(TEXT("after"), MaximumScreenSpaceError);
		Out->SetObjectField(TEXT("maximum_screen_space_error"), Sse);
	}
	if (bChanged)
	{
		// Rebuilds the loaded tiles with the new settings; every frame's
		// WaitForView then loads them again before any capture.
		Tiles->RefreshTileset();
	}
	Out->SetBoolField(TEXT("refreshed"), bChanged);
	// The class's own properties, so the render machine's record names the
	// real settings the next probe can reach.
	TArray<TSharedPtr<FJsonValue>> Names;
	for (TFieldIterator<FProperty> It(Class, EFieldIterationFlags::None); It; ++It)
	{
		Names.Add(MakeShared<FJsonValueString>(FString::Printf(TEXT("%s:%s"), *It->GetName(),
		                                                        *It->GetCPPType())));
	}
	Out->SetArrayField(TEXT("tileset_properties"), Names);
	Out->SetStringField(TEXT("applied"), bChanged ? TEXT("the beauty look") : TEXT("nothing was found to set"));
#else
	(void)Material;
	Out->SetStringField(TEXT("applied"), TEXT("nothing: this build has no Cesium for Unreal plugin"));
#endif
	return Out;
}

// -- round-2b terrain-ocean (2026-11-09): the beauty ground --------------------
// BEAUTY ONLY: the commandlet's one caller is gated on -quality=beauty. Every
// constant below is UNCALIBRATED (stated, set for a probe render on the render
// machine) and recorded. Nothing here moves a pixel the labels describe: the
// haze is not geometry, and the sea cap is a beauty-only actor no label pass
// draws, at the sea level the tiles' own ocean already stands at.

namespace FlightSimBeautyGroundPure
{
	// The read ray: from the camera's height down at this depression (the
	// lower third of a level 16:9 frame); its optical depth is capped.
	constexpr double ReadDepressionDeg = 10.0;
	constexpr double ReadOpticalDepthMax = 1.5;     // transmittance 0.22
	constexpr double ReadMinAglM = 1000.0;          // below: the haze is the near field's, left alone
	constexpr double MinHazeScale = 0.05;
	// core/scene/weather_visuals.py ENGINE_FOG_DENSITY_PER_EXTINCTION: the
	// FogDensity that draws 1 /m of extinction, 1 / (0.1 ln(2)^2).
	constexpr double FogDensityPerExtinctionPerM = 20.813689810056077;
	constexpr double EarthRadiusM = 6371008.8;      // the mean radius (IUGG)
	constexpr double SeaLiftM = 2.0;                // above the tiles' geoid sea; the sea departs ~1 m from it
	// Lane B, round 19 (2026-11-11): #13 drew Google's matte ocean with the
	// cap showing only as four light lines along its radial edges: the cap's
	// flat triangles sag below the sphere (a 15 km chord at 233 km with 96
	// segments: 4.4 m) and the tiles' own ocean stood above it everywhere but
	// at the edges. Finer (256 segments, 128 rings: the widest chord ~5.7 km,
	// sag ~0.7 m) and lifted with the camera's height (0.2 % of it, 2..40 m:
	// 20 m from 10 km, a fraction of a pixel there), so the cap is the sea
	// the camera sees. The tiles stay drawn under it.
	constexpr double SeaLiftPerAglM = 0.002;
	constexpr double SeaLiftMaxM = 40.0;
	constexpr int32 SeaRings = 128;
	constexpr int32 SeaSegments = 256;
	constexpr double CmPerM = 100.0;

	// The vertical column (metres, density-ratio weighted) of an exp2 height
	// fog layer between the ground (Z 0) and the camera's height: UE draws
	// Density * 2^(-Falloff (z - FogHeight)) with Falloff per cm =
	// FogHeightFalloff / 1000 (SceneCore.cpp, HeightFogCommon.ush), so per
	// metre FogHeightFalloff / 10.
	inline double FogColumnM(double FogHeightFalloff, double FogHeightM, double TopM)
	{
		const double F = FMath::Max(FogHeightFalloff, 0.0) / 10.0;
		const double AtGround = FMath::Pow(2.0, F * FogHeightM);
		if (F * TopM < 1.0e-6)
		{
			return AtGround * TopM;
		}
		return AtGround * (1.0 - FMath::Pow(2.0, -F * TopM)) / (F * FMath::Loge(2.0));
	}
}

TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround(UWorld* World, double CameraAglM,
                                                                 double SeaRadiusM,
                                                                 TArray<AActor*>& BeautyOnlyActors)
{
	using namespace FlightSimBeautyGroundPure;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("lane"), TEXT("round-2b terrain-ocean; beauty only; UNCALIBRATED"));
	Out->SetBoolField(TEXT("tiles_drawn"), bEnabled);
	BeautyGround = Out;
	HazeFogRows.Reset();
	HazeMieRows.Reset();
	bHazeSuspended = false;
	if (World == nullptr)
	{
		Out->SetStringField(TEXT("applied"), TEXT("nothing: no world"));
		return Out;
	}

	// -- the haze the ground is read through ---------------------------------
	TSharedPtr<FJsonObject> Haze = MakeShared<FJsonObject>();
	Out->SetObjectField(TEXT("haze"), Haze);
	Haze->SetNumberField(TEXT("camera_agl_m"), CameraAglM);
	Haze->SetNumberField(TEXT("read_depression_deg"), ReadDepressionDeg);
	Haze->SetNumberField(TEXT("read_optical_depth_max"), ReadOpticalDepthMax);
	Haze->SetNumberField(TEXT("read_min_agl_m"), ReadMinAglM);
	if (CameraAglM < ReadMinAglM)
	{
		Haze->SetStringField(TEXT("applied"),
			TEXT("nothing: the camera is below read_min_agl_m; the ground is near and the haze is the near field's"));
	}
	else
	{
		const double SinRead = FMath::Sin(FMath::DegreesToRadians(ReadDepressionDeg));
		TArray<UExponentialHeightFogComponent*> Fogs;
		double FogDepth = 0.0;   // vertical optical depth of every visible fog layer, ground to camera
		for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
		{
			UExponentialHeightFogComponent* Fog = *It;
			if (Fog == nullptr || Fog->GetWorld() != World || !Fog->IsVisible())
			{
				continue;
			}
			Fogs.Add(Fog);
			const double FogHeightM = Fog->GetComponentLocation().Z / CmPerM;
			FogDepth += Fog->FogDensity / FogDensityPerExtinctionPerM
				* FogColumnM(Fog->FogHeightFalloff, FogHeightM, CameraAglM);
			FogDepth += Fog->SecondFogData.FogDensity / FogDensityPerExtinctionPerM
				* FogColumnM(Fog->SecondFogData.FogHeightFalloff,
				             FogHeightM + Fog->SecondFogData.FogHeightOffset / CmPerM, CameraAglM);
		}
		TArray<USkyAtmosphereComponent*> Atmospheres;
		double MieDepth = 0.0;   // vertical optical depth of the Mie layer, ground to camera
		for (TObjectIterator<USkyAtmosphereComponent> It; It; ++It)
		{
			USkyAtmosphereComponent* Atmosphere = *It;
			if (Atmosphere == nullptr || Atmosphere->GetWorld() != World || !Atmosphere->IsVisible())
			{
				continue;
			}
			Atmospheres.Add(Atmosphere);
			// 1/km at the ground (the coefficient colour times its scale; green),
			// falling as exp(-h / H) with H = MieExponentialDistribution km.
			const double SigmaPerKm = Atmosphere->MieScatteringScale * Atmosphere->MieScattering.G
				+ Atmosphere->MieAbsorptionScale * Atmosphere->MieAbsorption.G;
			const double ScaleKm = FMath::Max(static_cast<double>(Atmosphere->MieExponentialDistribution), 0.001);
			MieDepth += SigmaPerKm * ScaleKm * (1.0 - FMath::Exp(-(CameraAglM / 1000.0) / ScaleKm));
		}
		const double ReadDepth = (FogDepth + MieDepth) / SinRead;
		Haze->SetNumberField(TEXT("read_distance_m"), CameraAglM / SinRead);
		Haze->SetNumberField(TEXT("fog_optical_depth_before"), FogDepth / SinRead);
		Haze->SetNumberField(TEXT("mie_optical_depth_before"), MieDepth / SinRead);
		const double Scale = ReadDepth > ReadOpticalDepthMax
			? FMath::Clamp(ReadOpticalDepthMax / ReadDepth, MinHazeScale, 1.0) : 1.0;
		Haze->SetNumberField(TEXT("scale"), Scale);
		if (Scale < 1.0)
		{
			TArray<TSharedPtr<FJsonValue>> FogRows;
			for (UExponentialHeightFogComponent* Fog : Fogs)
			{
				TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
				Row->SetNumberField(TEXT("fog_density_before"), Fog->FogDensity);
				Row->SetNumberField(TEXT("second_fog_density_before"), Fog->SecondFogData.FogDensity);
				FHazeFogRow& Held = HazeFogRows.AddDefaulted_GetRef();
				Held.Fog = Fog;
				Held.DensityBefore = Fog->FogDensity;
				Held.SecondDensityBefore = Fog->SecondFogData.FogDensity;
				Fog->SetFogDensity(static_cast<float>(Fog->FogDensity * Scale));
				Fog->SetSecondFogDensity(static_cast<float>(Fog->SecondFogData.FogDensity * Scale));
				Row->SetNumberField(TEXT("fog_density_after"), Fog->FogDensity);
				Row->SetNumberField(TEXT("second_fog_density_after"), Fog->SecondFogData.FogDensity);
				FogRows.Add(MakeShared<FJsonValueObject>(Row));
			}
			Haze->SetArrayField(TEXT("height_fog"), FogRows);
			TArray<TSharedPtr<FJsonValue>> MieRows;
			for (USkyAtmosphereComponent* Atmosphere : Atmospheres)
			{
				TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
				Row->SetNumberField(TEXT("mie_scattering_scale_before"), Atmosphere->MieScatteringScale);
				Row->SetNumberField(TEXT("mie_absorption_scale_before"), Atmosphere->MieAbsorptionScale);
				FHazeMieRow& Held = HazeMieRows.AddDefaulted_GetRef();
				Held.Atmosphere = Atmosphere;
				Held.ScatteringBefore = Atmosphere->MieScatteringScale;
				Held.AbsorptionBefore = Atmosphere->MieAbsorptionScale;
				Atmosphere->SetMieScatteringScale(static_cast<float>(Atmosphere->MieScatteringScale * Scale));
				Atmosphere->SetMieAbsorptionScale(static_cast<float>(Atmosphere->MieAbsorptionScale * Scale));
				Row->SetNumberField(TEXT("mie_scattering_scale_after"), Atmosphere->MieScatteringScale);
				Row->SetNumberField(TEXT("mie_absorption_scale_after"), Atmosphere->MieAbsorptionScale);
				MieRows.Add(MakeShared<FJsonValueObject>(Row));
			}
			Haze->SetArrayField(TEXT("mie"), MieRows);
			Haze->SetNumberField(TEXT("read_optical_depth_after"), ReadDepth * Scale);
			Haze->SetStringField(TEXT("applied"),
				TEXT("the height fog and the Mie layer scaled by one factor so the ground reads along the read ray"));
		}
		else
		{
			Haze->SetStringField(TEXT("applied"), TEXT("nothing: the read ray's optical depth is within the cap"));
		}
		Haze->SetStringField(TEXT("not_claimed"),
			TEXT("the card's visibility: the physics never reads the fog, and the near-field rain is the drops' "
			     "(look_applied.rain_particles / weather), not this haze"));
	}

	// -- the open sea's surface ----------------------------------------------
	TSharedPtr<FJsonObject> Sea = MakeShared<FJsonObject>();
	Out->SetObjectField(TEXT("sea"), Sea);
	Sea->SetNumberField(TEXT("radius_m"), SeaRadiusM);
	// Lane B (2026-11-11): the beauty sea (M_FlightSimOceanBeauty: Phillips
	// waves, Cox-Munk glitter, whitecaps); M_Ground_Ocean, the flat scene's
	// measure ground, only when it has not been built.
	const TCHAR* const OceanBeautyPath = TEXT("/Game/FlightSim/M_FlightSimOceanBeauty.M_FlightSimOceanBeauty");
	const TCHAR* const OceanGroundPath = TEXT("/Game/FlightSim/M_Ground_Ocean.M_Ground_Ocean");
	UMaterialInterface* OceanBase = SeaRadiusM > 0.0 ? LoadObject<UMaterialInterface>(nullptr, OceanBeautyPath) : nullptr;
	const bool bOceanBeauty = OceanBase != nullptr;
	if (SeaRadiusM > 0.0 && OceanBase == nullptr)
	{
		OceanBase = LoadObject<UMaterialInterface>(nullptr, OceanGroundPath);
	}
	if (SeaRadiusM <= 0.0)
	{
		Sea->SetStringField(TEXT("drawn"), TEXT("nothing: no -beauty-sea-radius-m (not an open-ocean beauty render)"));
	}
	else if (OceanBase == nullptr)
	{
		Sea->SetStringField(TEXT("drawn"),
			TEXT("nothing: neither M_FlightSimOceanBeauty nor M_Ground_Ocean loaded (run scripts/ue_create_materials.py)"));
	}
	else
	{
		// A spherical cap at sea level about the origin: the engine frame is
		// the local tangent plane there (Z 0 = orthometric 0 = the geoid the
		// tiles' ocean stands on), so the sea falls R - sqrt(R^2 - r^2) below
		// it at distance r and its horizon is the tiles' horizon.
		const double RadiusM = FMath::Min(SeaRadiusM, 0.5 * EarthRadiusM);
		const double LiftM = FMath::Clamp(SeaLiftPerAglM * CameraAglM, SeaLiftM, SeaLiftMaxM);
		TArray<FVector> Vertices;
		TArray<FVector> Normals;
		TArray<FProcMeshTangent> Tangents;
		TArray<FVector2D> UV;
		TArray<FLinearColor> Colours;
		TArray<int32> Triangles;
		auto AddVertex = [&](double Rm, double Angle)
		{
			const double X = Rm * FMath::Cos(Angle);
			const double Y = Rm * FMath::Sin(Angle);
			const double Drop = EarthRadiusM - FMath::Sqrt(EarthRadiusM * EarthRadiusM - Rm * Rm);
			Vertices.Add(FVector(X, Y, LiftM - Drop) * CmPerM);
			Normals.Add(FVector(X, Y, EarthRadiusM - Drop).GetSafeNormal());
			Tangents.Add(FProcMeshTangent(FVector(-FMath::Sin(Angle), FMath::Cos(Angle), 0.0), false));
			UV.Add(FVector2D(X / 1000.0, Y / 1000.0));
			Colours.Add(FLinearColor::White);
		};
		AddVertex(0.0, 0.0);   // 0: the centre
		for (int32 Ring = 1; Ring <= SeaRings; ++Ring)
		{
			// Finer near the camera: r = R (ring / rings)^2.
			const double Fraction = static_cast<double>(Ring) / SeaRings;
			for (int32 Segment = 0; Segment < SeaSegments; ++Segment)
			{
				AddVertex(RadiusM * Fraction * Fraction, 2.0 * PI * Segment / SeaSegments);
			}
		}
		auto RingVertex = [](int32 Ring, int32 Segment)
		{
			return 1 + (Ring - 1) * SeaSegments + (Segment % SeaSegments);
		};
		// Wound clockwise seen from above (+Z), the winding the scene's own
		// ground faces up with (FlightSimVisualScene.cpp: A, B, C / B, D, C).
		for (int32 Segment = 0; Segment < SeaSegments; ++Segment)
		{
			Triangles.Append({0, RingVertex(1, Segment + 1), RingVertex(1, Segment)});
		}
		for (int32 Ring = 1; Ring < SeaRings; ++Ring)
		{
			for (int32 Segment = 0; Segment < SeaSegments; ++Segment)
			{
				const int32 P0 = RingVertex(Ring, Segment);
				const int32 P1 = RingVertex(Ring, Segment + 1);
				const int32 Q0 = RingVertex(Ring + 1, Segment);
				const int32 Q1 = RingVertex(Ring + 1, Segment + 1);
				Triangles.Append({P0, P1, Q0, P1, Q1, Q0});
			}
		}
		AActor* SeaActor = World->SpawnActor<AActor>();
		UProceduralMeshComponent* SeaMesh = NewObject<UProceduralMeshComponent>(SeaActor, TEXT("BeautySea"));
		SeaActor->SetRootComponent(SeaMesh);
		SeaMesh->SetMobility(EComponentMobility::Movable);
		SeaMesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV, Colours, Tangents,
		                                       false /* no collision */);
		SeaMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		SeaMesh->SetCastShadow(false);
		UMaterialInstanceDynamic* SeaMaterial = UMaterialInstanceDynamic::Create(OceanBase, SeaMesh);
		// The calm sea: the ground material's wet-ground puddles off.
		SeaMaterial->SetScalarParameterValue(FName(TEXT("Wetness")), 0.0f);
		SeaMesh->SetMaterial(0, SeaMaterial);
		SeaMesh->RegisterComponent();
		SeaActor->SetActorLocation(FVector::ZeroVector);
		// NOT tagged FlightSim.terrain (HideOwnTerrain would hide it); beauty
		// only, so the label, depth and mask passes never draw it.
		BeautyOnlyActors.Add(SeaActor);
		Sea->SetStringField(TEXT("drawn"),
			TEXT("a spherical cap of the sea material at sea level over the tiles' ocean (beauty-only actor)"));
		Sea->SetStringField(TEXT("material"), OceanBase->GetPathName());
		Sea->SetStringField(TEXT("material_basis"), bOceanBeauty
			? TEXT("M_FlightSimOceanBeauty (lane B, generation 2): its own sky reflection (Fresnel, horizon to "
			       "zenith) and Cox-Munk sun glint as emissive from the atmosphere nodes, the Phillips wave normal only "
			       "where resolved, deep-sea body colour, Monahan whitecaps at WindSpeedMS 7 (UNCALIBRATED)")
			: TEXT("M_Ground_Ocean: M_FlightSimOceanBeauty did not load (run scripts/ue_create_materials.py)"));
		Sea->SetNumberField(TEXT("lift_m"), LiftM);
		Sea->SetStringField(TEXT("lift_basis"),
			TEXT("max(2 m, 0.2 % of the camera's height), at most 40 m: above the tiles' own ocean and the cap's "
			     "chord sag, so the tiles' matte ocean never shows through (round 19's #13 lines)"));
		{
			const double WidestChordM = 2.0 * PI * RadiusM / SeaSegments;
			Sea->SetNumberField(TEXT("max_chord_sag_m"), WidestChordM * WidestChordM / (8.0 * EarthRadiusM));
		}
		Sea->SetNumberField(TEXT("earth_radius_m"), EarthRadiusM);
		Sea->SetNumberField(TEXT("rings"), SeaRings);
		Sea->SetNumberField(TEXT("segments"), SeaSegments);
		Sea->SetNumberField(TEXT("edge_drop_m"),
			EarthRadiusM - FMath::Sqrt(EarthRadiusM * EarthRadiusM - RadiusM * RadiusM));
		Sea->SetStringField(TEXT("reflection"), bOceanBeauty
			? TEXT("the material's own emissive (water's F0 0.02, the sky shaped from SkyLum, the sun's GGX glint); "
			       "the engine specular is off (Specular 0), so no screen-space reflection draws on the sea")
			: TEXT("the material's own (roughness 0.04, specular 0.5): screen-space reflections and the sky "
			       "light, both drawn on D3D11 / SM5 without Lumen"));
		Sea->SetStringField(TEXT("not_claimed"),
			TEXT("the sea state of the card (the waves are the material's stated 7 m/s sea), tides"));
	}
	return Out;
}

// -- round 1 hang (2026-11-09): ef361bd6's haze for the sky light capture ----
// The constrained GPU deadlocked in the sky light capture; ef361bd6 (which had
// no ApplyBeautyGround) rendered every shot there. For that one capture the
// haze ApplyBeautyGround scaled is the scene's own again; the frames keep it.
TSharedPtr<FJsonObject> FFlightSimGoogleTiles::SuspendBeautyHaze()
{
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	if (bHazeSuspended || (HazeFogRows.Num() == 0 && HazeMieRows.Num() == 0))
	{
		Out->SetStringField(TEXT("applied"), bHazeSuspended
			? TEXT("nothing: already suspended")
			: TEXT("nothing: ApplyBeautyGround scaled no haze on this render"));
		return Out;
	}
	bHazeSuspended = true;
	int32 Held = 0;
	for (FHazeFogRow& Row : HazeFogRows)
	{
		if (UExponentialHeightFogComponent* Fog = Row.Fog.Get())
		{
			Row.DensityHeld = Fog->FogDensity;
			Row.SecondDensityHeld = Fog->SecondFogData.FogDensity;
			Fog->SetFogDensity(Row.DensityBefore);
			Fog->SetSecondFogDensity(Row.SecondDensityBefore);
			++Held;
		}
	}
	for (FHazeMieRow& Row : HazeMieRows)
	{
		if (USkyAtmosphereComponent* Atmosphere = Row.Atmosphere.Get())
		{
			Row.ScatteringHeld = Atmosphere->MieScatteringScale;
			Row.AbsorptionHeld = Atmosphere->MieAbsorptionScale;
			Atmosphere->SetMieScatteringScale(Row.ScatteringBefore);
			Atmosphere->SetMieAbsorptionScale(Row.AbsorptionBefore);
			++Held;
		}
	}
	Out->SetNumberField(TEXT("components_held"), Held);
	Out->SetStringField(TEXT("applied"),
		TEXT("the height fog and the Mie layer at their values before ApplyBeautyGround, for the sky capture only"));
	return Out;
}

void FFlightSimGoogleTiles::ResumeBeautyHaze()
{
	if (!bHazeSuspended)
	{
		return;
	}
	bHazeSuspended = false;
	for (const FHazeFogRow& Row : HazeFogRows)
	{
		if (UExponentialHeightFogComponent* Fog = Row.Fog.Get())
		{
			Fog->SetFogDensity(Row.DensityHeld);
			Fog->SetSecondFogDensity(Row.SecondDensityHeld);
		}
	}
	for (const FHazeMieRow& Row : HazeMieRows)
	{
		if (USkyAtmosphereComponent* Atmosphere = Row.Atmosphere.Get())
		{
			Atmosphere->SetMieScatteringScale(Row.ScatteringHeld);
			Atmosphere->SetMieAbsorptionScale(Row.AbsorptionHeld);
		}
	}
}
