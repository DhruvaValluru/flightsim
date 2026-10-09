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
	const FString IonToken =
		FPlatformMisc::GetEnvironmentVariable(TEXT("CESIUM_ION_TOKEN")).TrimStartAndEnd();
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
