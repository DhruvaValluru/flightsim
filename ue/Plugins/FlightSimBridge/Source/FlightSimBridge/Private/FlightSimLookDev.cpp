// Look-dev harness (scripts/lookdev/): a test scene's beauty set-up built into
// the EDITOR world, so a look lane can tweak materials, look JSON and C++ and
// see a 1280x720 still without a render-commandlet run.
//
// Console commands (editor only; nothing here runs inside a commandlet, and
// the render commandlet's code path is unchanged -- it gains one exported
// wrapper around its own airframe builder, FlightSimLookDevBuildMeshAirframe):
//   FlightSim.LookDev.Build <lookdev.json>   (written by scripts/lookdev/prepare.py)
//   FlightSim.LookDev.Capture <out.png> [width height]
//   FlightSim.LookDev.Clear
// Each writes <the lookdev.json or png>.status.json: {"ok": bool, "error": ...}.
//
// The beauty steps are the commandlet's own classes, called with the SAME
// argument string the commandlet would get (prepare.py records it from the web
// app's render flow): FFlightSimVisualScene::Build, FFlightSimWeather,
// FFlightSimImpostorClouds, FFlightSimGoogleTiles (Enable, ApplyBeautyGround,
// WaitForView), FFlightSimBeautyFallback, the exposure helpers,
// ApplyBeautyPostProcess -> FFlightSimBeautyLook::Apply, FFlightSimHeroLighting,
// FFlightSimBeautyLook::ApplyEngineLook. While a command runs the process
// command line carries those arguments too, because some of those classes read
// FCommandLine::Get(). What it does NOT reproduce is listed in
// scripts/lookdev/README.md.

#include "CoreMinimal.h"
#include "HAL/IConsoleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Engine/World.h"
#include "Engine/Engine.h"
#include "Engine/SceneCapture2D.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Components/SceneCaptureComponent2D.h"
#include "GameFramework/Actor.h"
#include "GeoReferencingSystem.h"
#include "ImageUtils.h"
#include "RenderingThread.h"
#include "Containers/Ticker.h"
#if WITH_FLIGHTSIM_CESIUM
#include "Cesium3DTileset.h"
#include "CesiumCamera.h"
#include "CesiumCameraManager.h"
#endif

#include "FlightSimBeautyFallback.h"
#include "FlightSimBeautyLook.h"
#include "FlightSimCameraDirector.h"
#include "FlightSimClouds.h"
#include "FlightSimGoogleTiles.h"
#include "FlightSimHeightfield.h"
#include "FlightSimHeroLighting.h"
#include "FlightSimImpostorClouds.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimSky.h"
#include "FlightSimVisualScene.h"
#include "FlightSimWeather.h"

// FlightSimRenderCommandlet.cpp: the commandlet's own BuildMeshAirframe.
bool FlightSimLookDevBuildMeshAirframe(AActor* Aircraft, const FString& ManifestPath,
                                       const FString& CardAircraft, const FString& Livery,
                                       int32 StartGearUp, FString& Error);

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimLookDev, Log, All);

namespace
{
	struct FLookDevState
	{
		TWeakObjectPtr<UWorld> World;
		FString Params;                        // the commandlet argument string + switches
		FFlightSimScenarioCard Card;
		TSharedPtr<FJsonObject> CardRoot;
		FFlightSimSkyPlan SkyPlan;
		bool bPhysicalSky = false;
		TUniquePtr<FFlightSimVisualScene> Visual;
		TUniquePtr<FFlightSimWeather> Weather;
		TUniquePtr<FFlightSimImpostorClouds> Impostors;
		TUniquePtr<FFlightSimGoogleTiles> Tiles;
		TUniquePtr<FFlightSimWorldBeauty> WorldBeauty;
		TWeakObjectPtr<AGeoReferencingSystem> GeoReferencing;
		TWeakObjectPtr<AActor> Aircraft;
		TWeakObjectPtr<ASceneCapture2D> Camera;
		TArray<TWeakObjectPtr<AActor>> Spawned;
		FVector CameraLocation = FVector::ZeroVector;
		FRotator CameraRotation = FRotator::ZeroRotator;
		double FovDeg = 54.43;
		double LastMeterStops = 0.0;
	};

	FLookDevState& State()
	{
		static FLookDevState Instance;
		return Instance;
	}

	// The commandlet's arguments on the process command line for the length of
	// one command (FFlightSimBeautyLook::Apply and the tiles read FCommandLine).
	struct FScopedCommandLine
	{
		FString Saved;
		explicit FScopedCommandLine(const FString& Extra)
		{
			Saved = FCommandLine::Get();
			FCommandLine::Set(*(Saved + TEXT(" ") + Extra));
		}
		~FScopedCommandLine() { FCommandLine::Set(*Saved); }
	};

	void WriteStatus(const FString& Path, bool bOk, const FString& Error,
	                 const TSharedPtr<FJsonObject>& Extra = nullptr)
	{
		TSharedPtr<FJsonObject> Root = Extra.IsValid() ? Extra : MakeShared<FJsonObject>();
		Root->SetBoolField(TEXT("ok"), bOk);
		Root->SetStringField(TEXT("error"), Error);
		FString Text;
		const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
		FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
		FFileHelper::SaveStringToFile(Text, *(Path + TEXT(".status.json")));
		if (bOk) { UE_LOG(LogFlightSimLookDev, Display, TEXT("lookdev: ok (%s)"), *Path); }
		else { UE_LOG(LogFlightSimLookDev, Error, TEXT("lookdev: %s (%s)"), *Error, *Path); }
	}

	TSharedPtr<FJsonObject> ReadJson(const FString& Path)
	{
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (FFileHelper::LoadFileToString(Text, *Path))
		{
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root);
		}
		return Root;
	}

	void Clear()
	{
		FLookDevState& S = State();
		for (TWeakObjectPtr<AActor>& Actor : S.Spawned)
		{
			if (Actor.IsValid()) { Actor->Destroy(); }
		}
		S.Spawned.Reset();
		// The scene objects hold raw actor pointers into a world the caller
		// replaces (scripts/lookdev opens a blank map first); dropped, not torn down.
		(void)S.Visual.Release();
		(void)S.Weather.Release();
		(void)S.Impostors.Release();
		(void)S.Tiles.Release();
		if (S.WorldBeauty.IsValid()) { S.WorldBeauty->RestoreCvars(); }
		(void)S.WorldBeauty.Release();
		S.WorldBeauty = MakeUnique<FFlightSimWorldBeauty>();
		S.Visual = MakeUnique<FFlightSimVisualScene>();
		S.Weather = MakeUnique<FFlightSimWeather>();
		S.Impostors = MakeUnique<FFlightSimImpostorClouds>();
		S.Tiles = MakeUnique<FFlightSimGoogleTiles>();
	}

	template <typename T>
	T* Track(T* Actor)
	{
		if (Actor != nullptr) { State().Spawned.Add(Actor); }
		return Actor;
	}

	// The render commandlet's FlightSimRenderCommandlet.cpp RenderGridConvergenceDeg.
	double GridConvergenceDeg(AGeoReferencingSystem* Geo, const FVector& Projected)
	{
		FVector Here, NorthStep, East, North, Up;
		Geo->ProjectedToEngine(Projected, Here);
		Geo->ProjectedToEngine(Projected + FVector(0.0, 100.0, 0.0), NorthStep);
		Geo->GetENUVectorsAtEngineLocation(Here, East, North, Up);
		const FVector Grid = NorthStep - Here;
		return FMath::RadiansToDegrees(FMath::Atan2(FVector::DotProduct(Grid, East),
		                                            FVector::DotProduct(Grid, North)));
	}

	// The card's look block (card.look, else card.randomization.look), as the commandlet reads it.
	TSharedPtr<FJsonObject> CardLook(const TSharedPtr<FJsonObject>& Root)
	{
		const TSharedPtr<FJsonObject>* Field = nullptr;
		const TSharedPtr<FJsonObject>* Randomization = nullptr;
		if (!Root.IsValid()) { return nullptr; }
		if (Root->TryGetObjectField(TEXT("look"), Field) && Field != nullptr && Field->IsValid()) { return *Field; }
		if (Root->TryGetObjectField(TEXT("randomization"), Randomization) && Randomization != nullptr &&
		    (*Randomization)->TryGetObjectField(TEXT("look"), Field) && Field != nullptr && Field->IsValid())
		{
			return *Field;
		}
		return nullptr;
	}

	// The scene options the commandlet derives from its flags and the card
	// (FlightSimRenderCommandlet.cpp, "SceneOptions" block); the subset that
	// shapes a beauty still. Sun animation, the shadow shot and the probe
	// overrides are not mirrored.
	bool SceneOptionsFor(const FString& P, FLookDevState& S, FFlightSimVisualSceneOptions& O, FString& Error)
	{
		const TSharedPtr<FJsonObject> Look = CardLook(S.CardRoot);
		double FogDensity = 0.0012;
		FParse::Value(*P, TEXT("fog-density="), FogDensity);
		FString TerrainPath = !S.Card.CollisionTerrainPath.IsEmpty() ? S.Card.CollisionTerrainPath
		                                                             : S.Card.OrographicTerrainPath;
		FParse::Value(*P, TEXT("terrain="), TerrainPath);
		O.TerrainPath = TerrainPath;
		O.bDynamicShadows = !FParse::Param(*P, TEXT("NoShadows"));
		O.FogDensity = static_cast<float>(FogDensity);
		FParse::Value(*P, TEXT("sun-intensity-scale="), O.SunIntensityScale);
		FParse::Value(*P, TEXT("sky-light-scale="), O.SkyLightScale);
		FParse::Value(*P, TEXT("sun-temperature="), O.SunTemperatureK);
		FParse::Value(*P, TEXT("sun-source-angle="), O.SunSourceAngleDeg);
		int64 TriangleBudget = 0;
		if (FParse::Value(*P, TEXT("triangle-budget="), TriangleBudget) && TriangleBudget > 0)
		{
			O.TerrainTriangleBudget = static_cast<int32>(FMath::Min<int64>(TriangleBudget, MAX_int32));
		}
		{
			FString Direct, Ambient, Horizon;
			const bool bD = FParse::Value(*P, TEXT("xplane-direct="), Direct);
			const bool bA = FParse::Value(*P, TEXT("xplane-ambient="), Ambient);
			const bool bH = FParse::Value(*P, TEXT("xplane-horizon="), Horizon);
			FParse::Value(*P, TEXT("xplane-condition="), O.XPlaneCondition);
			auto Srgb = [](const FString& Text, FColor& Out)
			{
				TArray<FString> Parts;
				Text.ParseIntoArray(Parts, TEXT(":"));
				if (Parts.Num() != 3) { return false; }
				Out = FColor(FCString::Atoi(*Parts[0]), FCString::Atoi(*Parts[1]), FCString::Atoi(*Parts[2]), 255);
				return true;
			};
			if (bD && bA && bH && Srgb(Direct, O.XPlaneDirect) && Srgb(Ambient, O.XPlaneAmbient) &&
			    Srgb(Horizon, O.XPlaneHorizon))
			{
				O.bXPlaneLighting = true;
			}
		}
		double SunElevationDeg = 0.0, SunAzimuthDeg = 0.0;
		bool bSunOverride = FParse::Value(*P, TEXT("sun-elev="), SunElevationDeg) &&
		                    FParse::Value(*P, TEXT("sun-azim="), SunAzimuthDeg);
		double SunLux = 0.0;
		FParse::Value(*P, TEXT("sun-lux="), SunLux);
		if (Look.IsValid())
		{
			double Value = 0.0;
			if (Look->TryGetNumberField(TEXT("engine_fog_density"), Value) && Value > 0.0)
			{
				O.FogDensity = static_cast<float>(Value);
			}
			double LookElevation = 0.0, LookAzimuth = 0.0;
			if (Look->TryGetNumberField(TEXT("sun_elevation_deg"), LookElevation) &&
			    Look->TryGetNumberField(TEXT("engine_sun_azimuth_deg"), LookAzimuth))
			{
				SunElevationDeg = LookElevation;
				SunAzimuthDeg = LookAzimuth;
				bSunOverride = true;
			}
			const TArray<TSharedPtr<FJsonValue>>* Clouds = nullptr;
			if (Look->TryGetArrayField(TEXT("clouds"), Clouds) && Clouds != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& Entry : *Clouds)
				{
					const TSharedPtr<FJsonObject> Layer = Entry.IsValid() ? Entry->AsObject() : nullptr;
					if (!Layer.IsValid()) { continue; }
					FFlightSimCloudLayer Out;
					Layer->TryGetNumberField(TEXT("cover"), Out.CoverFraction);
					Layer->TryGetNumberField(TEXT("base_m"), Out.BaseMetres);
					Layer->TryGetNumberField(TEXT("top_m"), Out.TopMetres);
					O.CloudLayers.Add(Out);
				}
			}
			FString Word;
			if (Look->TryGetStringField(TEXT("precipitation"), Word)) { O.Precipitation = Word; }
			if (Look->TryGetNumberField(TEXT("wetness"), Value)) { O.Wetness = Value; }
			Look->TryGetNumberField(TEXT("cloud_drift_mps"), O.CloudDriftMps);
			Look->TryGetNumberField(TEXT("cloud_drift_from_deg"), O.CloudDriftFromDeg);
			double LookAerosol = 0.0;
			if (Look->TryGetNumberField(TEXT("aerosol"), LookAerosol)) { O.AerosolMieScale = LookAerosol; }
			double CardSunLux = 0.0;
			if (Look->TryGetNumberField(TEXT("sun_lux"), CardSunLux)) { SunLux = CardSunLux; }
		}
		const TSharedPtr<FJsonObject>* WeatherLook = nullptr;
		if (S.CardRoot.IsValid() && S.CardRoot->TryGetObjectField(TEXT("weather_look"), WeatherLook) &&
		    WeatherLook != nullptr && WeatherLook->IsValid())
		{
			FString Storm;
			(*WeatherLook)->TryGetStringField(TEXT("storm"), Storm);
			if (!Storm.IsEmpty() && Storm != TEXT("none") && O.CloudLayers.Num() == 0)
			{
				FFlightSimCloudLayer Layer;
				Layer.CoverFraction = 0.95; Layer.BaseMetres = 1200.0; Layer.TopMetres = 9000.0;
				O.CloudLayers.Add(Layer);
			}
			double RainMmh = 0.0;
			(*WeatherLook)->TryGetNumberField(TEXT("rain_rate_mmh"), RainMmh);
			if (RainMmh >= 4.0 && O.CloudLayers.Num() == 0)
			{
				FFlightSimCloudLayer Layer;
				Layer.CoverFraction = 0.98; Layer.BaseMetres = 800.0; Layer.TopMetres = 3000.0;
				O.CloudLayers.Add(Layer);
			}
			double Wetness = 0.0;
			if ((*WeatherLook)->TryGetNumberField(TEXT("wetness"), Wetness) && Wetness > 0.0 && O.Wetness <= 0.0)
			{
				O.Wetness = FMath::Min(Wetness, 1.0);
			}
		}
		double Aerosol = -1.0;
		if (FParse::Value(*P, TEXT("aerosol="), Aerosol) && Aerosol >= 0.0) { O.AerosolMieScale = Aerosol; }
		FString Precip;
		if (FParse::Value(*P, TEXT("precip="), Precip) && !Precip.IsEmpty())
		{
			O.Precipitation = Precip;
			O.Wetness = Precip == TEXT("rain") ? 1.0 : (Precip == TEXT("snow") ? 0.6 : 0.0);
		}
		if (SunLux > 0.0)
		{
			O.SunLux = SunLux;
			O.SunLuxSource = TEXT("lookdev: -sun-lux / card.look.sun_lux");
		}
		O.Card = S.CardRoot;
		O.StarCataloguePath = FPaths::ConvertRelativePathToFull(
			FPaths::Combine(FPaths::ProjectDir(), TEXT(".."), TEXT("assets"), TEXT("stars"), TEXT("bsc5-short.json")));
		if (FParse::Param(*P, TEXT("GeorefTerrain")))
		{
			O.bGeoreferenced = true;
			O.GeoReferencing = S.GeoReferencing.Get();
			O.bClassifiedMaterial = true;
			FParse::Value(*P, TEXT("imagery="), O.ImagerySidecarPath);
		}
		O.NearTerrainOriginMetres = FVector2D(-8000.0, -21360.0);
		O.FarTerrainOriginMetres = FVector2D(-8000.0, -41360.0);
		O.bHideNearTerrain = FParse::Param(*P, TEXT("HideNearTerrain"));
		O.bCaptureSkyOnce = true;
		O.bNoAerialPerspective = FParse::Param(*P, TEXT("NoAerialPerspective"));
		O.SunRotation = FRotator(-12.0, 180.0, 0.0);
		if (bSunOverride) { O.SunRotation = FRotator(-SunElevationDeg, SunAzimuthDeg + 180.0, 0.0); }
		if (S.bPhysicalSky) { O.SkyPlan = &S.SkyPlan; }
		FString Backend;
		FParse::Value(*P, TEXT("weather-backend="), Backend);
		const TSharedPtr<FJsonObject>* StormWeather = nullptr;
		O.bSkipRainParticles = !Backend.IsEmpty() && Backend != TEXT("off") && S.CardRoot.IsValid() &&
		                       S.CardRoot->HasField(TEXT("weather"));
		O.bSkipStormLook = O.bSkipRainParticles &&
		                   S.CardRoot->TryGetObjectField(TEXT("weather"), StormWeather) && StormWeather != nullptr &&
		                   (*StormWeather)->HasField(TEXT("cell"));
		return true;
	}

	// First pose of the card's consumed camera (cameras[-camera-index=]), in
	// the engine frame, as the commandlet converts it; false when the card
	// carries no pose track (the director preset is used then).
	bool CardCameraPose(const FString& P, FLookDevState& S, FVector& OutLocation, FRotator& OutRotation,
	                    double& OutFovDeg)
	{
		int32 Index = 0;
		FParse::Value(*P, TEXT("camera-index="), Index);
		const TArray<TSharedPtr<FJsonValue>>* Cameras = nullptr;
		if (!S.CardRoot.IsValid() || !S.CardRoot->TryGetArrayField(TEXT("cameras"), Cameras) ||
		    Cameras == nullptr || !Cameras->IsValidIndex(Index))
		{
			return false;
		}
		const TSharedPtr<FJsonObject> Camera = (*Cameras)[Index]->AsObject();
		const TSharedPtr<FJsonObject>* Poses = nullptr;
		double OriginX = 0.0, OriginY = 0.0, SensorMm = 36.0;
		if (!Camera.IsValid() || !Camera->TryGetNumberField(TEXT("origin_x_m"), OriginX) ||
		    !Camera->TryGetNumberField(TEXT("origin_y_m"), OriginY) ||
		    !Camera->TryGetObjectField(TEXT("poses"), Poses))
		{
			return false;
		}
		Camera->TryGetNumberField(TEXT("sensor_width_mm"), SensorMm);
		auto First = [&](const TCHAR* Key, double& Out)
		{
			const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
			if (!(*Poses)->TryGetArrayField(Key, Values) || Values == nullptr || Values->Num() == 0) { return false; }
			Out = (*Values)[0]->AsNumber();
			return true;
		};
		double North, East, Alt, Yaw, Pitch, Roll, Focal;
		if (!First(TEXT("north_m"), North) || !First(TEXT("east_m"), East) || !First(TEXT("alt_m"), Alt) ||
		    !First(TEXT("yaw_deg"), Yaw) || !First(TEXT("pitch_deg"), Pitch) || !First(TEXT("roll_deg"), Roll) ||
		    !First(TEXT("focal_length_mm"), Focal))
		{
			return false;
		}
		const FVector Projected(OriginX + East, OriginY + North, Alt);
		S.GeoReferencing->ProjectedToEngine(Projected, OutLocation);
		OutRotation = FRotator(Pitch, Yaw + GridConvergenceDeg(S.GeoReferencing.Get(), Projected) - 90.0, Roll);
		OutFovDeg = FMath::RadiansToDegrees(2.0 * FMath::Atan(SensorMm / (2.0 * Focal)));
		return true;
	}

	bool Build(UWorld* World, const FString& LookdevPath, TSharedPtr<FJsonObject>& Report, FString& Error)
	{
		FLookDevState& S = State();
		const TSharedPtr<FJsonObject> Lookdev = ReadJson(LookdevPath);
		FString CardPath, Params, Switches;
		if (!Lookdev.IsValid() || !Lookdev->TryGetStringField(TEXT("card"), CardPath) ||
		    !Lookdev->TryGetStringField(TEXT("params"), Params))
		{
			Error = TEXT("lookdev.json unreadable or missing card/params (run scripts/lookdev/prepare.py)");
			return false;
		}
		Lookdev->TryGetStringField(TEXT("switches"), Switches);
		Clear();
		S.World = World;
		S.Params = Params + TEXT(" ") + Switches;
		const FString& P = S.Params;
		FScopedCommandLine CommandLine(P);
		if (!FFlightSimScenarioWorld::ReadCard(CardPath, S.Card, Error)) { return false; }
		S.CardRoot = ReadJson(CardPath);

		// Georeferencing, as FFlightSimScenarioWorld::Populate sets it.
		AGeoReferencingSystem* Geo = Track(World->SpawnActor<AGeoReferencingSystem>());
		if (Geo == nullptr) { Error = TEXT("could not spawn AGeoReferencingSystem"); return false; }
		S.GeoReferencing = Geo;
		Geo->PlanetShape = EPlanetShape::RoundPlanet;
		Geo->bOriginAtPlanetCenter = false;
		Geo->bOriginLocationInProjectedCRS = false;
		Geo->OriginLatitude = S.Card.LatitudeDegrees;
		Geo->OriginLongitude = S.Card.LongitudeDegrees;
		Geo->OriginAltitude = S.Card.TerrainElevationMetres;
		{
			const FString HeightfieldPath = !S.Card.CollisionTerrainPath.IsEmpty() ? S.Card.CollisionTerrainPath
			                              : (S.Card.bOrographic ? S.Card.OrographicTerrainPath : FString());
			FFlightSimHeightfield Heightfield;
			if (!HeightfieldPath.IsEmpty() && Heightfield.Load(HeightfieldPath, Error) && !Heightfield.Crs.IsEmpty())
			{
				Geo->ProjectedCRS = Heightfield.Crs;
			}
			else if (!S.Card.SceneCrs.IsEmpty() || !S.Card.ThermalsCrs.IsEmpty())
			{
				Geo->ProjectedCRS = S.Card.SceneCrs.IsEmpty() ? S.Card.ThermalsCrs : S.Card.SceneCrs;
			}
			Error.Reset();
		}
		Geo->ApplySettings();
		const FString CardCrs = Geo->ProjectedCRS;

		FString SkyPath;
		S.bPhysicalSky = FParse::Value(*P, TEXT("sky="), SkyPath) && !SkyPath.IsEmpty();
		if (S.bPhysicalSky)
		{
			if (!FFlightSimSkyPlan::Load(SkyPath, S.SkyPlan, Error)) { return false; }
			FFlightSimSky::EnableRendererFeatures();
		}

		// The aircraft at the card's initial condition (the CG offset the
		// JSBSim component applies is not modelled: the actor origin sits on
		// the stated point).
		const FRotator Attitude(0.0, S.Card.HeadingDegrees - 90.0, 0.0);
		FVector AircraftLocation;
		Geo->GeographicToEngine(FGeographicCoordinates(S.Card.LongitudeDegrees, S.Card.LatitudeDegrees,
		                                               S.Card.AltitudeMetres), AircraftLocation);
		AActor* Aircraft = Track(World->SpawnActor<AActor>(AActor::StaticClass(), AircraftLocation, Attitude));
		if (Aircraft == nullptr) { Error = TEXT("could not spawn the aircraft actor"); return false; }
		USceneComponent* Root = NewObject<USceneComponent>(Aircraft, TEXT("Root"));
		Aircraft->SetRootComponent(Root);
		Root->RegisterComponent();
		Aircraft->SetActorLocationAndRotation(AircraftLocation, Attitude);
#if WITH_EDITOR
		Aircraft->SetActorLabel(TEXT("LookDev_Aircraft"));
#endif
		S.Aircraft = Aircraft;
		FString MeshManifest;
		if (FParse::Value(*P, TEXT("mesh="), MeshManifest) && !MeshManifest.IsEmpty() &&
		    !FParse::Param(*P, TEXT("HideAircraft")))
		{
			if (!FlightSimLookDevBuildMeshAirframe(Aircraft, MeshManifest, S.Card.Aircraft, S.Card.Livery,
			                                       S.Card.StartGearUp, Error))
			{
				return false;
			}
		}

		FFlightSimVisualSceneOptions Options;
		if (!SceneOptionsFor(P, S, Options, Error)) { return false; }
		if (!S.Visual->Build(World, Options, Error)) { return false; }
		S.Visual->ApplyIceOverlay(Aircraft);

		FString BackendName;
		FParse::Value(*P, TEXT("weather-backend="), BackendName);
		FFlightSimWeatherOptions WeatherOptions;
		if (!FFlightSimWeather::ParseBackend(BackendName, WeatherOptions.Backend, Error)) { return false; }
		WeatherOptions.Card = S.CardRoot;
		WeatherOptions.GeoReferencing = Geo;
		WeatherOptions.ExistingClouds = S.Visual->Clouds;
		if (Options.CloudLayers.Num() > 0)
		{
			WeatherOptions.LayerCover = Options.CloudLayers[0].CoverFraction;
			WeatherOptions.LayerBaseMetres = Options.CloudLayers[0].BaseMetres;
			WeatherOptions.LayerTopMetres = Options.CloudLayers[0].TopMetres;
		}
		WeatherOptions.Sun = S.Visual->Sun;
		WeatherOptions.bAudio = false;
		WeatherOptions.bManualNiagaraTick = false;
		FParse::Value(*P, TEXT("rain-gain="), WeatherOptions.RainGain);
		FParse::Value(*P, TEXT("rain-style="), WeatherOptions.RainStyle);
		if (!FFlightSimWeather::ParseLightningShadows(P, WeatherOptions.bLightningShadows, Error) ||
		    !FFlightSimWeather::ParseBakedSwitch(P, TEXT("rain-layers="), WeatherOptions.bRainLayers, Error) ||
		    !FFlightSimWeather::ParseBakedSwitch(P, TEXT("windscreen-baked="), WeatherOptions.bWindscreenBaked,
		                                         Error, TEXT("on")))
		{
			return false;
		}
		if (!S.Weather->Build(World, WeatherOptions, Error)) { return false; }
		if (S.Weather->DrawsLightning()) { S.Visual->StandDownLookLightning(); }

		FFlightSimImpostorCloudOptions ImpostorOptions;
		if (!FFlightSimImpostorClouds::ParseMode(P, ImpostorOptions.Mode, Error)) { return false; }
		ImpostorOptions.Layers = Options.CloudLayers;
		ImpostorOptions.AircraftCm = AircraftLocation;
		ImpostorOptions.Seed = static_cast<int32>(S.Card.TurbulenceSeed & 0x7FFFFFFF);
		if (!S.Impostors->Build(World, ImpostorOptions, Error)) { return false; }

		// The camera: the card's solved pose track (first pose), else the
		// director preset's resting pose with the -chase= offset.
		FVector CameraLocation;
		FRotator CameraRotation;
		double FovDeg = 55.0;
		FString CameraSource = TEXT("cameras[].poses[0]");
		// The card's frame again before the poses go through it (the editor
		// world measured a frame left at a previous scene's CRS here).
		const FString CrsBeforePose = Geo->ProjectedCRS;
		if (CrsBeforePose != CardCrs)
		{
			UE_LOG(LogFlightSimLookDev, Warning, TEXT("lookdev: projected CRS was %s, set back to the card's %s"),
			       *CrsBeforePose, *CardCrs);
			Geo->ProjectedCRS = CardCrs;
			Geo->ApplySettings();
		}
		if (!CardCameraPose(P, S, CameraLocation, CameraRotation, FovDeg))
		{
			AFlightSimCameraDirector* Director = Track(World->SpawnActor<AFlightSimCameraDirector>());
			Director->Target = Aircraft;
			FString Preset = TEXT("chase"), Chase;
			FParse::Value(*P, TEXT("camera="), Preset);
			Director->Preset = Preset == TEXT("wingman") ? EFlightSimCameraPreset::Wingman
			                 : Preset == TEXT("tower") ? EFlightSimCameraPreset::Tower
			                 : EFlightSimCameraPreset::LaggedChase;
			Director->ChaseOffsetMetres = FVector(-170.0f, 0.0f, 16.0f);
			if (FParse::Value(*P, TEXT("chase="), Chase))
			{
				TArray<FString> Parts;
				Chase.ParseIntoArray(Parts, TEXT(":"));
				if (Parts.Num() == 3)
				{
					Director->ChaseOffsetMetres = FVector(FCString::Atod(*Parts[0]), FCString::Atod(*Parts[1]),
					                                      FCString::Atod(*Parts[2]));
				}
			}
			if (!Director->PresetRestingPose(CameraLocation, CameraRotation))
			{
				Error = TEXT("camera director has no resting pose");
				return false;
			}
			CameraSource = FString::Printf(TEXT("director preset %s"), *Preset);
		}
		S.CameraLocation = CameraLocation;
		S.CameraRotation = CameraRotation;
		S.FovDeg = FovDeg;

		if (FFlightSimGoogleTiles::Requested() && !FParse::Param(*P, TEXT("NoGoogleTiles")))
		{
			double Undulation = 0.0;
			bool bUndulation = false;
			const TSharedPtr<FJsonObject>* Block = nullptr;
			if (S.CardRoot->TryGetObjectField(TEXT("georeference"), Block) && Block != nullptr)
			{
				bUndulation = (*Block)->TryGetNumberField(TEXT("undulation_origin_m"), Undulation);
			}
			if (!bUndulation && S.CardRoot->TryGetObjectField(TEXT("google_tiles"), Block) && Block != nullptr)
			{
				bUndulation = (*Block)->TryGetNumberField(TEXT("geoid_undulation_m"), Undulation);
			}
			if (!bUndulation) { Error = TEXT("google_tiles.undulation_missing on the card"); return false; }
			if (!S.Tiles->Enable(World, Geo, S.Card.LatitudeDegrees, S.Card.LongitudeDegrees,
			                     S.Card.TerrainElevationMetres, Undulation, Error))
			{
				return false;
			}
			S.Tiles->HideOwnTerrain(World);
		}
		if (!FFlightSimBeautyFallback::ApplyScene(*S.Visual, *P)) { Error = FFlightSimBeautyFallback::LastError(); return false; }
		// The world lane's beauty-only look (atmosphere, sun transmittance, ...), as the commandlet builds it.
		if (!S.WorldBeauty->Build(World, *P, S.CardRoot, Aircraft, Geo, *S.Visual, *S.Weather, *S.Tiles, Error))
		{
			return false;
		}
		if (S.Tiles->IsEnabled())
		{
			double SeaRadiusM = 0.0;
			FParse::Value(*P, TEXT("beauty-sea-radius-m="), SeaRadiusM);
			S.Tiles->ApplyBeautyGround(World, CameraLocation.Z / 100.0, SeaRadiusM,
			                           S.Card.WindSpeedKnots * (1852.0 / 3600.0), S.Card.WindFromDegrees,
			                           S.Visual->BeautyOnlyActors);
		}

		// The beauty capture, set up in the commandlet's order.
		ASceneCapture2D* CameraActor = Track(World->SpawnActor<ASceneCapture2D>(CameraLocation, CameraRotation));
#if WITH_EDITOR
		CameraActor->SetActorLabel(TEXT("LookDev_BeautyCamera"));
#endif
		S.Camera = CameraActor;
		USceneCaptureComponent2D* Capture = CameraActor->GetCaptureComponent2D();
		Capture->bCaptureEveryFrame = false;
		Capture->bCaptureOnMovement = false;
		// As the commandlet's capture: without a persistent view state there is no
		// pre-exposure / exposure history and every frame clips to white.
		Capture->bAlwaysPersistRenderingState = true;
		Capture->CaptureSource = ESceneCaptureSource::SCS_FinalColorLDR;
		Capture->FOVAngle = static_cast<float>(FovDeg);
		FString ExposureMode;
		if (S.bPhysicalSky)
		{
			FFlightSimSky::ApplyPostProcess(Capture->PostProcessSettings, S.SkyPlan);
			FFlightSimSky::ApplyShowFlags(Capture->ShowFlags);
			ExposureMode = TEXT("physical_sky");
		}
		else
		{
			int32 Index = 0;
			FParse::Value(*P, TEXT("camera-index="), Index);
			const TArray<TSharedPtr<FJsonValue>>* Cameras = nullptr;
			const TSharedPtr<FJsonObject>* Exposure = nullptr;
			double ApertureF = 0.0, ShutterS = 0.0, Iso = 0.0;
			FString CameraId;
			if (S.CardRoot->TryGetArrayField(TEXT("cameras"), Cameras) && Cameras != nullptr &&
			    Cameras->IsValidIndex(Index))
			{
				const TSharedPtr<FJsonObject> Camera = (*Cameras)[Index]->AsObject();
				Camera->TryGetStringField(TEXT("camera_id"), CameraId);
				if (Camera->TryGetObjectField(TEXT("exposure"), Exposure) && Exposure != nullptr)
				{
					(*Exposure)->TryGetNumberField(TEXT("aperture_f"), ApertureF);
					(*Exposure)->TryGetNumberField(TEXT("shutter_s"), ShutterS);
					(*Exposure)->TryGetNumberField(TEXT("iso"), Iso);
				}
			}
			const TSharedPtr<FJsonObject> Look = CardLook(S.CardRoot);
			const TSharedPtr<FJsonObject>* Ev100 = nullptr;
			double LookEv = 0.0;
			const bool bLookEv = Look.IsValid() && !CameraId.IsEmpty() &&
			                     Look->TryGetObjectField(TEXT("ev100"), Ev100) && Ev100 != nullptr &&
			                     (*Ev100)->TryGetNumberField(CameraId, LookEv);
			if (ApertureF > 0.0 && ShutterS > 0.0 && Iso > 0.0)
			{
				FFlightSimVisualScene::ApplyPhysicalExposure(Capture, ApertureF, ShutterS, Iso);
				ExposureMode = TEXT("manual_ev100 (card camera exposure)");
			}
			else if (bLookEv)
			{
				FFlightSimVisualScene::ApplyPhysicalExposure(Capture, 1.0, FMath::Pow(2.0, -LookEv), 100.0);
				ExposureMode = TEXT("manual_ev100 (look.ev100)");
			}
			else
			{
				double Bias = 0.0;
				FParse::Value(*P, TEXT("exposure-bias="), Bias);
				FFlightSimVisualScene::ApplyManualExposure(Capture, static_cast<float>(Bias));
				ExposureMode = TEXT("manual_bias");
			}
		}
		FFlightSimVisualScene::ApplyBeautyPostProcess(Capture);
		if (!FFlightSimBeautyLook::LastError().IsEmpty()) { Error = FFlightSimBeautyLook::LastError(); return false; }
		if (!FFlightSimHeroLighting::Apply(*S.Visual, Capture, false, *P)) { Error = FFlightSimHeroLighting::LastError(); return false; }
		FFlightSimBeautyFallback::ApplyCapture(Capture);
		if (!FFlightSimBeautyLook::ApplyEngineLook(*S.Visual, Capture, FFlightSimWorldBeauty::ConstrainedGpu(), *P))
		{
			Error = FFlightSimBeautyLook::LastError();
			return false;
		}
		// Beauty-only actors stay visible: this is the beauty camera.
		Report = MakeShared<FJsonObject>();
		Report->SetStringField(TEXT("camera"), CameraSource);
		Report->SetStringField(TEXT("exposure"), ExposureMode);
		Report->SetStringField(TEXT("projected_crs"), Geo->ProjectedCRS);
		Report->SetStringField(TEXT("projected_crs_before_pose"), CrsBeforePose);
		Report->SetNumberField(TEXT("fov_deg"), FovDeg);
		Report->SetBoolField(TEXT("google_tiles"), S.Tiles->IsEnabled());
		Report->SetBoolField(TEXT("physical_sky"), S.bPhysicalSky);
		auto Vec = [](const FVector& V)
		{
			TArray<TSharedPtr<FJsonValue>> A;
			A.Add(MakeShared<FJsonValueNumber>(V.X)); A.Add(MakeShared<FJsonValueNumber>(V.Y)); A.Add(MakeShared<FJsonValueNumber>(V.Z));
			return A;
		};
		Report->SetArrayField(TEXT("camera_location_cm"), Vec(CameraLocation));
		Report->SetArrayField(TEXT("camera_rotation_pyr"), Vec(FVector(CameraRotation.Pitch, CameraRotation.Yaw, CameraRotation.Roll)));
		Report->SetArrayField(TEXT("aircraft_location_cm"), Vec(AircraftLocation));
		return true;
	}

	// The warm-up captures and the PNG, once the tiles report fully loaded.
	bool WriteStill(const FString& PngPath, int32 Width, int32 Height, FString& Error)
	{
		FLookDevState& S = State();
		FScopedCommandLine CommandLine(S.Params);
		USceneCaptureComponent2D* Capture = S.Camera->GetCaptureComponent2D();
		UTextureRenderTarget2D* Target = NewObject<UTextureRenderTarget2D>(GetTransientPackage());
		Target->RenderTargetFormat = RTF_RGBA8_SRGB;
		Target->ClearColor = FLinearColor::Black;
		Target->InitAutoFormat(Width, Height);
		Target->UpdateResourceImmediate(true);
		Capture->TextureTarget = Target;
		// Warm-up captures (temporal history, exposure), as the commandlet's -warmup.
		int32 Warmup = 8;
		FParse::Value(*S.Params, TEXT("warmup="), Warmup);
		for (int32 Index = 0; Index <= Warmup; ++Index)
		{
			if (S.WorldBeauty->IsBuilt() && S.Aircraft.IsValid())
			{
				S.WorldBeauty->Advance(0.0, S.CameraLocation, S.Aircraft->GetActorLocation(), Index);
			}
			if (S.Impostors->IsBuilt() && S.Aircraft.IsValid())
			{
				FVector Origin, Extent;
				S.Aircraft->GetActorBounds(true, Origin, Extent);
				S.Impostors->Advance(S.CameraLocation, S.Aircraft->GetActorLocation(), Extent.Size());
			}
			FFlightSimBeautyLook::UpdatePerFrame(Capture, S.Aircraft.Get());
			S.World->SendAllEndOfFrameUpdates();
			Capture->CaptureScene();
			FlushRenderingCommands();
		}
		// The beauty exposure meter (FlightSimRenderCommandlet.cpp, "BeautyMeter"):
		// open or close AutoExposureBias until the 90th-percentile luma meets
		// the look's target, or close a blown frame toward 0.80.
		double MeterTarget = 0.0;
		FString MeterTrigger;
		const bool bMeter = !S.Weather->DrawsCell() && FFlightSimBeautyLook::ExposureMeter(MeterTarget, MeterTrigger);
		if (bMeter || S.Weather->DrawsCell())
		{
			double MeterP90 = bMeter ? FMath::Clamp(MeterTarget, 0.05, 0.8) : 0.40;
			FParse::Value(*S.Params, TEXT("storm-meter-target="), MeterP90);
			FPostProcessSettings& Settings = Capture->PostProcessSettings;
			Settings.bOverride_AutoExposureBias = true;
			const double BiasBefore = Settings.AutoExposureBias;
			double Opened = 0.0;
			for (int32 Round = 0; Round < 5; ++Round)
			{
				TArray<FColor> MeterPixels;
				FTextureRenderTargetResource* MeterResource = Capture->TextureTarget->GameThread_GetRenderTargetResource();
				if (MeterResource == nullptr || !MeterResource->ReadPixels(MeterPixels) || MeterPixels.Num() == 0) { break; }
				uint32 Histogram[256] = {};
				for (const FColor& Pixel : MeterPixels)
				{
					const double Luma = 0.2126 * Pixel.R + 0.7152 * Pixel.G + 0.0722 * Pixel.B;
					++Histogram[FMath::Clamp(static_cast<int32>(Luma + 0.5), 0, 255)];
				}
				const uint32 Wanted = static_cast<uint32>(0.90 * MeterPixels.Num());
				uint32 Seen = 0;
				int32 Bin = 0;
				for (; Bin < 255 && Seen + Histogram[Bin] < Wanted; ++Bin) { Seen += Histogram[Bin]; }
				const double Bright = Bin / 255.0;
				const bool bBlown = Bright > 0.92;
				if ((!bBlown && FMath::Abs(Bright - MeterP90) <= 0.05) || Round == 4) { break; }
				const double Want = bBlown ? 0.80 : MeterP90;
				double Step = 2.2 * 0.8 * FMath::Log2(Want / FMath::Max(Bright, 1.0 / 255.0));
				if (bBlown && Bright >= 254.0 / 255.0) { Step = FMath::Min(Step, -2.0); }
				const double Lowest = bBlown ? -6.0 : FMath::Min(0.0, Opened);
				const double Next = FMath::Clamp(Opened + Step, Lowest, 8.0);
				if (FMath::IsNearlyEqual(Next, Opened, 0.01)) { break; }
				Opened = Next;
				Settings.AutoExposureBias = static_cast<float>(BiasBefore + Opened);
				for (int32 Settle = 0; Settle < 4; ++Settle)
				{
					S.World->SendAllEndOfFrameUpdates();
					Capture->CaptureScene();
					FlushRenderingCommands();
				}
			}
			S.LastMeterStops = Opened;
		}
		TArray<FColor> Pixels;
		FTextureRenderTargetResource* Resource = Target->GameThread_GetRenderTargetResource();
		const bool bRead = Resource != nullptr && Resource->ReadPixels(Pixels) && Pixels.Num() == Width * Height;
		Capture->TextureTarget = nullptr;
		if (!bRead)
		{
			Error = TEXT("could not read the render target back");
			return false;
		}
		for (FColor& Pixel : Pixels) { Pixel.A = 255; }
		TArray64<uint8> Png;
		FImageUtils::PNGCompressImageArray(Width, Height, Pixels, Png);
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(PngPath), true);
		if (!FFileHelper::SaveArrayToFile(Png, *PngPath))
		{
			Error = FString::Printf(TEXT("could not write %s"), *PngPath);
			return false;
		}
		return true;
	}

	// Asynchronous: the editor keeps ticking (Cesium streams in its own tick,
	// pointed at this camera through the Cesium camera manager) until the
	// tileset reports 100 % for 2 s, or 300 s pass; then the still is written
	// and <png>.status.json appears. FFlightSimGoogleTiles::WaitForView pumps the
	// tileset by hand, which is a commandlet's way and asserts in the editor.
	bool StartCapture(const FString& PngPath, int32 Width, int32 Height, FString& Error)
	{
		FLookDevState& S = State();
		if (!S.Camera.IsValid() || !S.World.IsValid())
		{
			Error = TEXT("no look-dev scene (FlightSim.LookDev.Build first)");
			return false;
		}
		IFileManager::Get().Delete(*(PngPath + TEXT(".status.json")));
		TWeakObjectPtr<AActor> Tileset = S.Tiles->IsEnabled() ? S.Tiles->GetTilesetActor() : nullptr;
#if WITH_FLIGHTSIM_CESIUM
		if (Tileset.IsValid())
		{
			if (ACesiumCameraManager* Cameras = ACesiumCameraManager::GetDefaultCameraManager(S.World.Get()))
			{
				FCesiumCamera Camera;
				Camera.ViewportSize = FVector2D(Width, Height);
				Camera.Location = S.CameraLocation;
				Camera.Rotation = S.CameraRotation;
				Camera.FieldOfViewDegrees = S.FovDeg;
				Cameras->AddCamera(Camera);
			}
		}
#endif
		const double Start = FPlatformTime::Seconds();
		TSharedRef<double> SettledSince = MakeShared<double>(-1.0);
		// A view stuck for 30 s (a failed request Cesium never retries) is
		// reloaded, as FFlightSimGoogleTiles::WaitForView does.
		TSharedRef<TPair<float, double>> LastChange = MakeShared<TPair<float, double>>(-1.0f, Start);
		TSharedRef<int32> Reloads = MakeShared<int32>(0);
		FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda(
			[PngPath, Width, Height, Tileset, Start, SettledSince, LastChange, Reloads](float) -> bool
			{
				const double Now = FPlatformTime::Seconds();
				float Progress = 100.0f;
#if WITH_FLIGHTSIM_CESIUM
				if (ACesium3DTileset* Tiles = Cast<ACesium3DTileset>(Tileset.Get()))
				{
					Progress = Tiles->GetLoadProgress();
					if (!FMath::IsNearlyEqual(Progress, LastChange->Key)) { *LastChange = TPair<float, double>(Progress, Now); }
					else if (Progress < 99.99f && Now - LastChange->Value > 30.0)
					{
						Tiles->RefreshTileset();
						++*Reloads;
						LastChange->Value = Now;
					}
				}
#endif
				*SettledSince = Progress >= 99.99f ? (*SettledSince < 0.0 ? Now : *SettledSince) : -1.0;
				const bool bSettled = *SettledSince >= 0.0 && Now - *SettledSince >= 2.0;
				if (!bSettled && Now - Start < 300.0) { return true; }
				FString CaptureError;
				bool bOk = State().Camera.IsValid() && WriteStill(PngPath, Width, Height, CaptureError);
				if (!State().Camera.IsValid()) { CaptureError = TEXT("the look-dev scene went away"); }
				TSharedPtr<FJsonObject> Extra = MakeShared<FJsonObject>();
				Extra->SetNumberField(TEXT("tiles_load_progress"), Progress);
				Extra->SetNumberField(TEXT("seconds"), Now - Start);
				Extra->SetBoolField(TEXT("tiles_settled"), bSettled);
				Extra->SetNumberField(TEXT("meter_stops"), State().LastMeterStops);
				Extra->SetNumberField(TEXT("tiles_reloads"), *Reloads);
				WriteStatus(PngPath, bOk, CaptureError, Extra);
				return false;
			}), 0.25f);
		return true;
	}

	FAutoConsoleCommandWithWorldAndArgs BuildCommand(
		TEXT("FlightSim.LookDev.Build"),
		TEXT("FlightSim.LookDev.Build <lookdev.json>: build a test scene's beauty set-up in this (editor) world"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (IsRunningCommandlet() || Args.Num() < 1 || World == nullptr) { return; }
			FString Error;
			TSharedPtr<FJsonObject> Report;
			const bool bOk = Build(World, Args[0], Report, Error);
			WriteStatus(Args[0], bOk, Error, Report);
		}));

	FAutoConsoleCommandWithWorldAndArgs CaptureCommand(
		TEXT("FlightSim.LookDev.Capture"),
		TEXT("FlightSim.LookDev.Capture <out.png> [width height]: wait for the tiles, then write the beauty still"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
		{
			if (IsRunningCommandlet() || Args.Num() < 1) { return; }
			const int32 Width = Args.Num() > 2 ? FCString::Atoi(*Args[1]) : 1280;
			const int32 Height = Args.Num() > 2 ? FCString::Atoi(*Args[2]) : 720;
			FString Error;
			if (!StartCapture(Args[0], Width, Height, Error)) { WriteStatus(Args[0], false, Error); }
		}));

	FAutoConsoleCommandWithWorldAndArgs ClearCommand(
		TEXT("FlightSim.LookDev.Clear"),
		TEXT("FlightSim.LookDev.Clear: destroy the look-dev actors"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld*)
		{
			if (!IsRunningCommandlet()) { Clear(); }
		}));
}
