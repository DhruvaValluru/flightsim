#include "FlightSimWeather.h"

#include "Components/AudioComponent.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/VolumetricCloudComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/DirectionalLight.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "GeoReferencingSystem.h"
#include "HAL/PlatformMisc.h"
#include "Kismet/GameplayStatics.h"
#include "MaterialDomain.h"
#include "MaterialShared.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"
#include "Misc/Parse.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"
#include "ProceduralMeshComponent.h"
#include "RHI.h"
#include "Sound/SoundWaveProcedural.h"
#include "UObject/UObjectIterator.h"

#include <atomic>

// Material resources are keyed by shader platform on UE 5.7 and later (the
// feature-level overload is gone there) and by feature level on 5.5 (Phase 3
// pin). One macro, both overloads; the argument not used is not evaluated.
#include "Runtime/Launch/Resources/Version.h"
#if ENGINE_MAJOR_VERSION > 5 || (ENGINE_MAJOR_VERSION == 5 && ENGINE_MINOR_VERSION >= 7)
#define FLIGHTSIM_GET_MATERIAL_RESOURCE(Base, World, Platform) ((Base)->GetMaterialResource(Platform))
#else
#define FLIGHTSIM_GET_MATERIAL_RESOURCE(Base, World, Platform) ((Base)->GetMaterialResource((World)->GetFeatureLevel()))
#endif

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimWeather, Log, All);

// The rain noise the interactive window plays: band-limited noise at the
// card's level (core/scene/thunder.py rain_noise), generated on the audio
// thread as the procedural wave asks for samples. The level is the only
// state the game thread writes.
struct FFlightSimRainNoise
{
	std::atomic<float> RmsPa{0.0f};
	FRandomStream Random;
	double HighPass = 0.0;
	double Low = 0.0;
	double Smooth = 0.0;
	double LowPassAlpha = 0.0;
	double HighPassAlpha = 0.0;
	double FullScalePa = 100.0;
	// The filtered noise's own RMS for unit-variance input (measured once
	// at construction over a second of samples, as thunder.py normalises).
	double UnitRms = 1.0;

	double Next()
	{
		const double X = Random.GetFraction() * 2.0 - 1.0;   // uniform, variance 1/3
		Low += HighPassAlpha * (X - Low);
		Smooth += LowPassAlpha * ((X - Low) - Smooth);
		return Smooth;
	}
};

namespace
{
	// Named distinctly from the sibling files' constants (unity builds merge
	// the anonymous namespaces into one translation unit).
	constexpr double WeatherCmPerMetre = 100.0;
	constexpr double WeatherPi = 3.14159265358979323846;

	// core/scene/precipitation.py: Atlas, Srivastava & Sekhon 1973.
	constexpr double WeatherAtlasA = 9.65;
	constexpr double WeatherAtlasB = 10.3;
	constexpr double WeatherAtlasC = 0.6;
	// core/scene/thunder.py.
	constexpr double WeatherThunderRMinM = 10.0;
	constexpr double WeatherThunderTailTimeConstants = 5.0;
	// core/scene/thunder.py RAIN_*: the rain's level and band.
	constexpr double WeatherRainSplDbAt1Mmh = 50.0;
	constexpr double WeatherRainBandLowHz = 500.0;
	constexpr double WeatherRainBandHighHz = 8000.0;
	constexpr double WeatherPRefSpl = 20.0e-6;
	// The glass: the windshield's visible area and height (stated; the
	// card's impingement is per m^2 of glass, the material's per screen).
	constexpr double WeatherGlassViewM2 = 1.0;
	constexpr double WeatherGlassViewHeightM = 0.8;
	constexpr double WeatherGlassStaticLifeS = 6.0;
	constexpr double WeatherGlassCells = 18.0;
	// The lightning channel's luminous radius (cm) and the point light's reach.
	constexpr double WeatherChannelRadiusCm = 5.0;
	constexpr double WeatherFlashLightRadiusCm = 3.0e6;
	// A channel above the cloud base is inside the cloud: not drawn as a line
	// (the cloud's glow carries its light), this far above the base allowed.
	constexpr double WeatherChannelAboveBaseM = 100.0;
	// The selftests' tolerance (the card's numbers carry 12 digits).
	constexpr double WeatherSelftestTolerance = 1.0e-9;

	const TCHAR* const WeatherRainMaterialPath = TEXT("/Game/FlightSim/M_RainDrops.M_RainDrops");
	const TCHAR* const WeatherSplashMaterialPath = TEXT("/Game/FlightSim/M_RainSplash.M_RainSplash");
	const TCHAR* const WeatherLightningMaterialPath =
		TEXT("/Game/FlightSim/M_LightningChannel.M_LightningChannel");
	const TCHAR* const WeatherStormMaterialPath = TEXT("/Game/FlightSim/M_StormCell.M_StormCell");
	const TCHAR* const WeatherWindshieldMaterialPath =
		TEXT("/Game/FlightSim/M_WindshieldRain.M_WindshieldRain");
	// Lane D: the beauty rain veil's materials (core/scene/rain_veil.py).
	const TCHAR* const WeatherCurtainMaterialPath = TEXT("/Game/FlightSim/M_RainCurtain.M_RainCurtain");
	const TCHAR* const WeatherScudMaterialPath = TEXT("/Game/FlightSim/M_ScudCard.M_ScudCard");
	const TCHAR* const WeatherNiagaraRainPath =
		TEXT("/Game/FlightSim/Weather/NS_FlightSimRain.NS_FlightSimRain");

	TSharedPtr<FJsonObject> WeatherRecord()
	{
		return MakeShared<FJsonObject>();
	}

	bool WeatherNumber(const TSharedPtr<FJsonObject>& Json, const TCHAR* Key, double& Out,
	                   const TCHAR* Block, FString& Error)
	{
		if (!Json.IsValid() || !Json->TryGetNumberField(Key, Out))
		{
			Error = FString::Printf(TEXT("weather.card: %s lacks the number '%s'; the weather is ")
			                        TEXT("drawn from the card's numbers or not at all"), Block, Key);
			return false;
		}
		return true;
	}

	bool WeatherVector(const TSharedPtr<FJsonObject>& Json, const TCHAR* Key, int32 Count,
	                   TArray<double>& Out, const TCHAR* Block, FString& Error)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Json.IsValid() || !Json->TryGetArrayField(Key, Values) || Values == nullptr ||
		    Values->Num() != Count)
		{
			Error = FString::Printf(TEXT("weather.card: %s lacks '%s' as %d numbers"), Block, Key,
			                        Count);
			return false;
		}
		Out.Reset();
		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			Out.Add(Value->AsNumber());
		}
		return true;
	}

	bool WeatherClose(double A, double B)
	{
		return FMath::Abs(A - B) <= WeatherSelftestTolerance * FMath::Max(1.0, FMath::Abs(B));
	}

	double WeatherSmoothstep(double E0, double E1, double X)
	{
		if (E0 == E1)
		{
			return X < E0 ? 0.0 : 1.0;
		}
		const double T = FMath::Clamp((X - E0) / (E1 - E0), 0.0, 1.0);
		return T * T * (3.0 - 2.0 * T);
	}

	double WeatherWrap(double V, double Half)
	{
		const double Span = 2.0 * Half;
		return V - Span * FMath::FloorToDouble((V + Half) / Span);
	}

	FLinearColor WeatherColour(const FVector& V, double W = 0.0)
	{
		return FLinearColor(static_cast<float>(V.X), static_cast<float>(V.Y),
		                    static_cast<float>(V.Z), static_cast<float>(W));
	}

	TArray<TSharedPtr<FJsonValue>> WeatherJsonVector(const FVector& V)
	{
		TArray<TSharedPtr<FJsonValue>> Out;
		Out.Add(MakeShared<FJsonValueNumber>(V.X));
		Out.Add(MakeShared<FJsonValueNumber>(V.Y));
		Out.Add(MakeShared<FJsonValueNumber>(V.Z));
		return Out;
	}

	FVector WeatherPoint(const TSharedPtr<FJsonValue>& Value)
	{
		const TArray<TSharedPtr<FJsonValue>>& P = Value->AsArray();
		return P.Num() == 3 ? FVector(P[0]->AsNumber(), P[1]->AsNumber(), P[2]->AsNumber())
		                    : FVector::ZeroVector;
	}

	double WeatherExpIntegral(double Tau, double A, double B)
	{
		return Tau * (FMath::Exp(-A / Tau) - FMath::Exp(-B / Tau));
	}

	double WeatherOverlap(double A, double B, double Lo, double Hi)
	{
		return FMath::Max(0.0, FMath::Min(B, Hi) - FMath::Max(A, Lo));
	}
}

// -- the closed forms ----------------------------------------------------------

// Round 12 follow-up (rain_veil.BEAUTY_CAMERA_MOTION_SHARE, BEAUTY_REFERENCE_PIXEL_RAD):
// read by the beauty rain shape below and by Advance.
namespace FlightSimRainVeil
{
	constexpr double BeautyCameraMotionShare = 0.15;
	// 2 tan(27 deg) / 1280: the pixel angle of 54 deg over 1280 px.
	constexpr double BeautyReferencePixelRad = 0.000796133514835045;
}

void FFlightSimWeather::ApplyBeautyRainReadability(double Gain)
{
	// Visual overhaul, world lane (2026-11-09): BEAUTY ONLY (FFlightSimWorldBeauty
	// is the only caller). A stated exaggeration on top of -rain-gain=, never
	// the physics; recorded beside the gain it multiplies.
	BeautyRainGain = FMath::Clamp(Gain, 0.0, 100.0);
	if (RainMaterial != nullptr)
	{
		RainMaterial->SetScalarParameterValue(TEXT("Weight"),
		                                      static_cast<float>(Weight * RainGain * BeautyRainGain));
	}
	if (SplashMaterial != nullptr)
	{
		SplashMaterial->SetScalarParameterValue(TEXT("Weight"),
		                                        static_cast<float>(SplashWeight * RainGain * BeautyRainGain));
	}
	if (NiagaraRain != nullptr)
	{
		NiagaraRain->SetVariableFloat(TEXT("User.Weight"), static_cast<float>(Weight * BeautyRainGain));
	}
	// round-2b weather-fx: the rain a camera shows, not a sheet (round 0 #07: a
	// full-frame wall of vertical streaks). Beauty only, like the gain above:
	// M_RainDrops's defaults are the measure path's shader.
	const FFlightSimBeautyRainShape Shape = BeautyRainShape(RainRateMmh, Particles);
	if (RainMaterial != nullptr)
	{
		RainMaterial->SetScalarParameterValue(TEXT("Density"), static_cast<float>(Shape.DensityShare));
		RainMaterial->SetScalarParameterValue(TEXT("NearThin"),
		                                      static_cast<float>(Shape.NearThinM * WeatherCmPerMetre));
		// The streak cap is set per frame in Advance, scaled by the lens (round 9's #07).
		BeautyMaxStreakRad = Shape.MaxStreakRad;
		RainMaterial->SetScalarParameterValue(TEXT("MaxCoverage"), static_cast<float>(Shape.MaxCoverage));
		RainMaterial->SetScalarParameterValue(TEXT("DepthFade"),
		                                      static_cast<float>(Shape.DepthFadeM * WeatherCmPerMetre));
		// Lane D: soft, varied streaks lit as the mean of their surroundings.
		RainMaterial->SetScalarParameterValue(TEXT("Soft"), static_cast<float>(Shape.Softness));
		RainMaterial->SetScalarParameterValue(TEXT("Vary"), static_cast<float>(Shape.Variation));
		RainMaterial->SetScalarParameterValue(TEXT("SkyRadianceScale"), static_cast<float>(Shape.Radiance));
	}
	if (RainMaterial != nullptr || bRainLayers)
	{
		// Round 12's #15: the cinematic streaks keep a share of the camera's motion
		// (maxpick/rain: the baked layers, -rain-layers=on, keep the same share).
		BeautyCameraShare = FlightSimRainVeil::BeautyCameraMotionShare;
	}
	const TSharedPtr<FJsonObject>* Row = nullptr;
	if (Record.IsValid() && Record->TryGetObjectField(TEXT("rain"), Row) && Row != nullptr && Row->IsValid())
	{
		(*Row)->SetNumberField(TEXT("beauty_readability_gain"), BeautyRainGain);
		(*Row)->SetStringField(TEXT("beauty_readability_basis"),
			TEXT("-quality=beauty: the drawn drops' opacity x this on top of the gain, so the streaks read on "
			     "camera (a stated exaggeration, UNCALIBRATED; core/scene/world_beauty.py ATMOSPHERE)"));
		TSharedPtr<FJsonObject> ShapeRow = MakeShared<FJsonObject>();
		ShapeRow->SetNumberField(TEXT("density_share"), Shape.DensityShare);
		ShapeRow->SetNumberField(TEXT("drawn_drops"), FMath::RoundToDouble(Shape.DensityShare * Particles));
		ShapeRow->SetNumberField(TEXT("near_thin_m"), Shape.NearThinM);
		ShapeRow->SetNumberField(TEXT("max_streak_rad"), Shape.MaxStreakRad);
		ShapeRow->SetNumberField(TEXT("max_streak_reference_pixel_rad"), FlightSimRainVeil::BeautyReferencePixelRad);
		ShapeRow->SetNumberField(TEXT("camera_motion_share"), BeautyCameraShare);
		ShapeRow->SetNumberField(TEXT("max_coverage"), Shape.MaxCoverage);
		ShapeRow->SetNumberField(TEXT("depth_fade_m"), Shape.DepthFadeM);
		ShapeRow->SetNumberField(TEXT("softness"), Shape.Softness);
		ShapeRow->SetNumberField(TEXT("variation"), Shape.Variation);
		ShapeRow->SetNumberField(TEXT("radiance"), Shape.Radiance);
		ShapeRow->SetStringField(TEXT("applied_to"), RainMaterial != nullptr
			? TEXT("M_RainDrops (the procedural backend's drops)")
			: bRainLayers ? TEXT("nothing: -rain-layers=on draws no drops (the camera share only)")
			: TEXT("nothing: the Niagara backend's system exposes no shape parameters"));
		ShapeRow->SetStringField(TEXT("basis"),
			TEXT("core/scene/weather_look.py beauty_rain_shape: the drawn count follows the rate, the streak's "
			     "angular length is capped, the drops near the lens thinned, one streak's coverage capped and "
			     "faded with range; each streak soft (Gaussian across, tapered), varied in length and brightness "
			     "by its own hash, and lit at radiance x the scene's light; mean light is NOT conserved (a stated "
			     "look, UNCALIBRATED)"));
		(*Row)->SetObjectField(TEXT("beauty_shape"), ShapeRow);
	}
}

FFlightSimBeautyRainShape FFlightSimWeather::BeautyRainShape(double RateMmh, int32 Particles)
{
	// core/scene/weather_look.py BEAUTY_RAIN_* (pinned by tests/test_weather_fx.py).
	constexpr double WeatherBeautyRainDropsPerMmh = 4000.0;
	constexpr double WeatherBeautyRainMinShare = 0.01;
	constexpr double WeatherBeautyRainNearThinM = 4.0;
	constexpr double WeatherBeautyRainStreakRadLight = 0.012;
	constexpr double WeatherBeautyRainStreakRadHeavy = 0.045;
	constexpr double WeatherBeautyRainLightMmh = 1.0;
	constexpr double WeatherBeautyRainHeavyMmh = 50.0;
	constexpr double WeatherBeautyRainMaxCoverage = 0.22;
	constexpr double WeatherBeautyRainDepthFadeM = 12.0;
	constexpr double WeatherBeautyRainSoftness = 1.0;
	constexpr double WeatherBeautyRainVariation = 0.8;
	constexpr double WeatherBeautyRainRadiance = 0.7;
	const double Rate = FMath::Max(RateMmh, 0.0);
	const double Count = static_cast<double>(FMath::Max(Particles, 1));
	FFlightSimBeautyRainShape Shape;
	Shape.DensityShare = FMath::Min(1.0, FMath::Max(WeatherBeautyRainMinShare,
	                                                WeatherBeautyRainDropsPerMmh * Rate / Count));
	double T = 0.0;
	if (Rate >= WeatherBeautyRainHeavyMmh)
	{
		T = 1.0;
	}
	else if (Rate > WeatherBeautyRainLightMmh)
	{
		T = FMath::Loge(Rate / WeatherBeautyRainLightMmh)
			/ FMath::Loge(WeatherBeautyRainHeavyMmh / WeatherBeautyRainLightMmh);
	}
	Shape.NearThinM = WeatherBeautyRainNearThinM;
	Shape.MaxStreakRad = WeatherBeautyRainStreakRadLight
		+ T * (WeatherBeautyRainStreakRadHeavy - WeatherBeautyRainStreakRadLight);
	Shape.MaxCoverage = WeatherBeautyRainMaxCoverage;
	Shape.DepthFadeM = WeatherBeautyRainDepthFadeM;
	Shape.Softness = WeatherBeautyRainSoftness;
	Shape.Variation = WeatherBeautyRainVariation;
	Shape.Radiance = WeatherBeautyRainRadiance;
	return Shape;
}

// -- lane D (2026-11-11): the beauty rain veil ------------------------------------------
// core/scene/rain_veil.py VEIL_* / SCUD_* (pinned by tests/test_lane_d_storm.py).
// BEAUTY ONLY: FFlightSimWorldBeauty is the only caller; both actors are in
// BeautyOnlyActors. UNCALIBRATED: set by probe render on the render machine.
namespace FlightSimRainVeil
{
	constexpr double VeilShellRadiusNearM = 25.0;
	constexpr double VeilShellRadiusMidM = 80.0;
	constexpr double VeilShellRadiusFarM = 250.0;
	constexpr int32 VeilSegments = 24;
	constexpr double VeilHeightRadii = 1.5;
	constexpr double VeilBetaA = 0.35;
	constexpr double VeilBetaB = 0.66;
	constexpr double VeilStreakPixels = 2.0;
	constexpr double VeilShadeUnderDeck = 0.85;
	constexpr double VeilShadeOpen = 1.0;
	constexpr double VeilVary = 0.6;
	// Round 47: the curtain cells' scale is never above this (the wide-lens cells).
	constexpr double VeilVaryScaleMax = 1.0;
	// Round 82 (r69's #15 black blotches; rain_veil.SCUD_TONE_*): grey rags, not holes.
	constexpr double ScudToneUnderDeck = 0.75;
	constexpr double ScudToneOpen = 0.85;
	constexpr double VeilStreakDensityA = 0.08;
	constexpr double VeilStreakDensityMax = 0.6;
	constexpr double VeilStreakAlpha = 0.25;
	constexpr int32 ScudCards = 40;
	constexpr double ScudBoxHalfM = 2500.0;
	constexpr double ScudBandBelowM = 300.0;
	constexpr double ScudDeckGapM = 50.0;
	constexpr double ScudNoDeckTopM = 400.0;
	constexpr double ScudWidthMinM = 150.0;
	constexpr double ScudWidthMaxM = 450.0;
	constexpr double ScudAspectMin = 0.3;
	constexpr double ScudAspectMax = 0.6;
	constexpr double ScudAlphaMin = 0.35;
	constexpr double ScudAlphaMax = 0.75;
	constexpr double ScudCameraClearM = 120.0;
	constexpr double ScudEdgeShare = 0.15;
	constexpr double ScudMinRainMmh = 8.0;
	constexpr uint64 ScudSeedSalt = 0x5C0D;
	// rain_veil.BEAUTY_WINDSHIELD_FILM: the windscreen water film's strength.
	constexpr double BeautyWindshieldFilm = 1.0;

	// rain_veil.rain_extinction_per_km
	inline double RainExtinctionPerKm(double RateMmh)
	{
		return RateMmh > 0.0 ? VeilBetaA * FMath::Pow(RateMmh, VeilBetaB) : 0.0;
	}
	// rain_veil.shell_veil_alpha
	inline double ShellVeilAlpha(double RateMmh, double InnerM, double OuterM)
	{
		return 1.0 - FMath::Exp(-RainExtinctionPerKm(RateMmh) * (OuterM - InnerM) / 1000.0);
	}
	// rain_veil.streak_density
	inline double StreakDensity(double RateMmh)
	{
		return FMath::Min(VeilStreakDensityMax, VeilStreakDensityA * FMath::Sqrt(FMath::Max(RateMmh, 0.0)));
	}
	inline double Wrap(double V, double Half)
	{
		return V - 2.0 * Half * FMath::FloorToDouble((V + Half) / (2.0 * Half));
	}
	inline double Smooth(double E0, double E1, double X)
	{
		if (E0 == E1)
		{
			return X < E0 ? 0.0 : 1.0;
		}
		const double T = FMath::Clamp((X - E0) / (E1 - E0), 0.0, 1.0);
		return T * T * (3.0 - 2.0 * T);
	}
}

void FFlightSimWeather::RainHazeFog(double RateMmh, double CameraAboveFogM, double ColumnM, double FogDensity,
                                    double FogFalloff, double& OutDensity, double& OutFalloff)
{
	// rain_veil.FOG_BETA_PER_DENSITY (0.1 ln(2)^2), RAIN_HAZE_FALLOFF_COLUMN, RAIN_HAZE_MIN_COLUMN_M.
	constexpr double RainHazeFogBetaPerDensity = 0.048045301391820145;
	constexpr double RainHazeFalloffColumn = 1.0;
	constexpr double RainHazeMinColumnM = 1000.0;
	const double Column = FMath::Max(ColumnM, RainHazeMinColumnM);
	OutFalloff = FMath::Min(FogFalloff, 10.0 * RainHazeFalloffColumn / Column);
	const double BetaPerM = FlightSimRainVeil::RainExtinctionPerKm(RateMmh) / 1000.0;
	const double Density = BetaPerM / RainHazeFogBetaPerDensity
		* FMath::Pow(2.0, OutFalloff / 10.0 * FMath::Max(CameraAboveFogM, 0.0));
	OutDensity = FMath::Max(FogDensity, Density);
}

bool FFlightSimWeather::ApplyBeautyRainVeil(UWorld* World, const FVector& AircraftCm, double AircraftUpM,
                                            bool bStorm, bool bDeck, double DeckBaseM, const FString& Mode,
                                            FString& Error)
{
	using namespace FlightSimRainVeil;
	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetStringField(TEXT("mode"), Mode);
	Row->SetStringField(TEXT("labels"),
		TEXT("both actors in BeautyOnlyActors: every label capture hides them (ConfigureLabelCapture)"));
	Row->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED: core/scene/rain_veil.py is the table; set by probe render on the render machine"));
	if (Record.IsValid())
	{
		Record->SetObjectField(TEXT("rain_veil"), Row);
	}
	if (Mode == TEXT("off") || !bRain || World == nullptr || RainRateMmh <= 0.0)
	{
		Row->SetStringField(TEXT("drawn"), Mode == TEXT("off")
			? TEXT("nothing: -rain-veil=off")
			: TEXT("nothing: the storm weather draws no rain here"));
		return true;
	}
	// The windscreen's water film (a cockpit camera's beauty glass, M_WindshieldRain 3):
	// FlightSimRainVeil::BeautyWindshieldFilm, applied per frame with the glass's Time.
	BeautyFilm = FlightSimRainVeil::BeautyWindshieldFilm;
	Row->SetNumberField(TEXT("windshield_film"), BeautyFilm);
	Row->SetStringField(TEXT("windshield_film_source"),
		TEXT("ambientCG Leaking 019 C (CC0-1.0), scripts/fetch_weather_textures.py; THIRD_PARTY_VISUAL.md"));
	UMaterialInterface* CurtainBase = LoadObject<UMaterialInterface>(nullptr, WeatherCurtainMaterialPath);
	if (CurtainBase == nullptr)
	{
		Error = FString::Printf(TEXT("weather.rain_veil: %s (scripts/ue_create_materials.py) did not load; the "
		                             "beauty rain veil is drawn by it or refused (-rain-veil=off to render without)"),
		                        WeatherCurtainMaterialPath);
		return false;
	}
	// -- the curtain: three open cylinders round the camera (moved per frame) ----
	const double Radii[3] = {VeilShellRadiusNearM, VeilShellRadiusMidM, VeilShellRadiusFarM};
	VeilActor = World->SpawnActor<AActor>();
	VeilActor->Tags.Add(FName(TEXT("FlightSim.weather")));
	BeautyOnlyActors.Add(VeilActor);
	USceneComponent* VeilRoot = NewObject<USceneComponent>(VeilActor, TEXT("RainVeilRoot"));
	VeilActor->SetRootComponent(VeilRoot);
	VeilRoot->SetMobility(EComponentMobility::Movable);
	VeilRoot->RegisterComponent();
	// Round 12: the veil and the scud in the deck's shade (rain_veil.veil_shade).
	VeilShade = bDeck && DeckBaseM > AircraftUpM ? VeilShadeUnderDeck : VeilShadeOpen;
	Row->SetNumberField(TEXT("shade"), VeilShade);
	const double D0 = FMath::Max(D0Mm, 0.5);
	const double FallCmps = TerminalVelocityMps(D0) * FallSpeedFactor * WeatherCmPerMetre;
	TArray<TSharedPtr<FJsonValue>> Shells;
	for (int32 Shell = 0; Shell < 3; ++Shell)
	{
		const double R = Radii[Shell] * WeatherCmPerMetre;
		const double H = Radii[Shell] * VeilHeightRadii * WeatherCmPerMetre;
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector2D> UV0;
		for (int32 K = 0; K <= VeilSegments; ++K)
		{
			const double A = 2.0 * PI * K / VeilSegments;
			const FVector Ring(R * FMath::Cos(A), R * FMath::Sin(A), 0.0);
			Vertices.Add(Ring + FVector(0.0, 0.0, -H));
			Vertices.Add(Ring + FVector(0.0, 0.0, H));
			UV0.Add(FVector2D(static_cast<double>(K) / VeilSegments, 0.0));
			UV0.Add(FVector2D(static_cast<double>(K) / VeilSegments, 1.0));
			if (K < VeilSegments)
			{
				const int32 B = 2 * K;
				Triangles.Append({B, B + 1, B + 2, B + 1, B + 3, B + 2});
			}
		}
		UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(
			VeilActor, *FString::Printf(TEXT("RainCurtain%d"), Shell));
		Mesh->SetupAttachment(VeilRoot);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, UV0, {}, {}, false /* no collision */);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(CurtainBase, VeilActor);
		const double Inner = Shell > 0 ? Radii[Shell - 1] : 0.0;
		const double Veil = ShellVeilAlpha(RainRateMmh, Inner, Radii[Shell]);
		Material->SetScalarParameterValue(TEXT("Radius"), static_cast<float>(R));
		Material->SetScalarParameterValue(TEXT("Shade"), static_cast<float>(VeilShade));
		Material->SetScalarParameterValue(TEXT("VeilVary"), static_cast<float>(VeilVary));
		Material->SetScalarParameterValue(TEXT("StreakDensity"), static_cast<float>(StreakDensity(RainRateMmh)));
		Material->SetScalarParameterValue(TEXT("StreakAlpha"), static_cast<float>(VeilStreakAlpha));
		Material->SetScalarParameterValue(TEXT("Veil"), static_cast<float>(Veil));
		Material->SetScalarParameterValue(TEXT("FallCmps"), static_cast<float>(FallCmps));
		Material->SetScalarParameterValue(TEXT("Seed"), static_cast<float>((RainSeed + Shell) & 0xFFFFFF));
		Mesh->SetMaterial(0, Material);
		Mesh->RegisterComponent();
		VeilShellMaterials.Add(Material);
		VeilShellRadiiM.Add(Radii[Shell]);
		TSharedPtr<FJsonObject> ShellRow = WeatherRecord();
		ShellRow->SetNumberField(TEXT("radius_m"), Radii[Shell]);
		ShellRow->SetNumberField(TEXT("veil"), Veil);
		Shells.Add(MakeShared<FJsonValueObject>(ShellRow));
	}
	Row->SetArrayField(TEXT("curtain_shells"), Shells);
	Row->SetNumberField(TEXT("rain_rate_mmh"), RainRateMmh);
	Row->SetNumberField(TEXT("extinction_per_km"), RainExtinctionPerKm(RainRateMmh));
	Row->SetNumberField(TEXT("streak_density"), StreakDensity(RainRateMmh));
	Row->SetBoolField(TEXT("vary_lens_cells"), bBeautyVeilLensCells);
	Row->SetStringField(TEXT("vary_lens_cells_basis"), bBeautyVeilLensCells
		? TEXT("round 47: the falling-curtain cells x min(1, pixel angle / 2 tan(27 deg) / 1280) per frame "
		       "(VaryScale; #07's 250 mm lens drew one cell wider than the frame); -veil-lens-cells=off is the A/B")
		: TEXT("-veil-lens-cells=off: generation 5's cells (a fifth of the radius across at every lens)"));
	Row->SetStringField(TEXT("curtain_basis"),
		TEXT("rain_veil: each shell the grey veil 1 - exp(-beta x its slab), beta = 0.35 R^0.66 /km (a STATED fit "
		     "of visibility in rain), and streaks falling along the drops' path in the wind at one angular size on "
		     "every shell; lit by the translucency volume like the drops"));

	// -- the scud: torn cards under the deck, carried by the wind -----------------
	const bool bScud = bStorm || RainRateMmh >= ScudMinRainMmh;
	Row->SetBoolField(TEXT("scud_drawn"), bScud);
	if (!bScud)
	{
		Row->SetStringField(TEXT("scud"), TEXT("not drawn: neither a storm preset nor rain of 8 mm/h or more"));
		return true;
	}
	UMaterialInterface* ScudBase = LoadObject<UMaterialInterface>(nullptr, WeatherScudMaterialPath);
	if (ScudBase == nullptr)
	{
		Error = FString::Printf(TEXT("weather.rain_veil: %s (scripts/ue_create_materials.py) did not load"),
		                        WeatherScudMaterialPath);
		return false;
	}
	ScudBandBottomM = AircraftUpM - ScudBandBelowM;
	ScudBandTopM = (bDeck && DeckBaseM > AircraftUpM) ? DeckBaseM - ScudDeckGapM : AircraftUpM + ScudNoDeckTopM;
	ScudBandTopM = FMath::Max(ScudBandTopM, ScudBandBottomM + 1.0);
	ScudDatumZCm = AircraftCm.Z - AircraftUpM * WeatherCmPerMetre;
	ScudSeed = RainSeed ^ ScudSeedSalt;
	ScudActor = World->SpawnActor<AActor>();
	ScudActor->Tags.Add(FName(TEXT("FlightSim.weather")));
	BeautyOnlyActors.Add(ScudActor);
	ScudMesh = NewObject<UProceduralMeshComponent>(ScudActor, TEXT("ScudCards"));
	ScudActor->SetRootComponent(ScudMesh);
	ScudMesh->SetMobility(EComponentMobility::Movable);
	{
		// Placeholder quads at the origin; StepBeautyRainVeil places every card.
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector2D> UV0, UV1;
		for (int32 I = 0; I < ScudCards; ++I)
		{
			const int32 B = Vertices.Num();
			for (int32 C = 0; C < 4; ++C)
			{
				Vertices.Add(FVector::ZeroVector);
				UV0.Add(FVector2D(C & 1, C >> 1));
				UV1.Add(FVector2D(0.0, 0.0));
			}
			Triangles.Append({B, B + 2, B + 1, B + 1, B + 2, B + 3});
		}
		ScudMesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, UV0, UV1, {}, {}, {}, {},
		                                        false /* no collision */);
	}
	ScudMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	ScudMesh->SetCastShadow(false);
	ScudMaterial = UMaterialInstanceDynamic::Create(ScudBase, ScudActor);
	// Round 19: M_ScudCard 3 is MODULATE; Shade is its tone (rain_veil.scud_tone).
	const double ScudTone = bDeck && DeckBaseM > AircraftUpM ? ScudToneUnderDeck : ScudToneOpen;
	ScudMaterial->SetScalarParameterValue(TEXT("Shade"), static_cast<float>(ScudTone));
	Row->SetNumberField(TEXT("scud_tone"), ScudTone);
	ScudMesh->SetMaterial(0, ScudMaterial);
	ScudMesh->RegisterComponent();
	Row->SetNumberField(TEXT("scud_cards"), ScudCards);
	Row->SetNumberField(TEXT("scud_band_bottom_m"), ScudBandBottomM);
	Row->SetNumberField(TEXT("scud_band_top_m"), ScudBandTopM);
	Row->SetBoolField(TEXT("scud_under_deck"), bDeck && DeckBaseM > AircraftUpM);
	Row->SetStringField(TEXT("scud_basis"),
		TEXT("rain_veil.scud_card: camera-facing torn cards (scud_card.hlsl) in a 5 km box round the camera carried "
		     "by the wind at the camera, from 300 m under the aircraft to 50 m under the drawn deck, none within "
		     "120 m (+ half a card) of the lens; a pure function of (seed, index, run time)"));
	return true;
}

double FFlightSimWeather::VeilVaryScale(double PixelAngle, bool bLensCells)
{
	// rain_veil.veil_vary_scale: the streak cap's rule (streak_cap_rad) for the curtains.
	if (!bLensCells || PixelAngle <= 0.0)
	{
		return FlightSimRainVeil::VeilVaryScaleMax;
	}
	return FMath::Min(FlightSimRainVeil::VeilVaryScaleMax, PixelAngle / FlightSimRainVeil::BeautyReferencePixelRad);
}

void FFlightSimWeather::StepBeautyRainVeil(const FFlightSimWeatherView& View, const FVector& Wind,
                                           const FVector& CamVel, double Share, double PixelAngle)
{
	using namespace FlightSimRainVeil;
	if (VeilActor != nullptr)
	{
		VeilActor->SetActorLocation(View.CameraCm);
		const double Rate = RainRateMmh * FMath::Clamp(Share, 0.0, 1.0);
		for (int32 Shell = 0; Shell < VeilShellMaterials.Num(); ++Shell)
		{
			UMaterialInstanceDynamic* Material = VeilShellMaterials[Shell];
			const double Inner = Shell > 0 ? VeilShellRadiiM[Shell - 1] : 0.0;
			Material->SetScalarParameterValue(TEXT("Time"), static_cast<float>(View.TimeSeconds));
			// The drops' path as the beauty's streaks draw it (the cinematic share of the camera's motion).
			Material->SetVectorParameterValue(TEXT("WindVel"), WeatherColour(Wind - CamVel));
			Material->SetScalarParameterValue(TEXT("StreakRad"), static_cast<float>(VeilStreakPixels * PixelAngle));
			Material->SetScalarParameterValue(TEXT("VaryScale"),
				static_cast<float>(VeilVaryScale(PixelAngle, bBeautyVeilLensCells)));
			Material->SetScalarParameterValue(TEXT("GroundRelZ"), static_cast<float>(View.GroundZCm - View.CameraCm.Z));
			Material->SetScalarParameterValue(TEXT("Veil"),
				static_cast<float>(ShellVeilAlpha(Rate, Inner, VeilShellRadiiM[Shell])));
			Material->SetScalarParameterValue(TEXT("StreakDensity"), static_cast<float>(StreakDensity(Rate)));
		}
	}
	if (ScudMesh == nullptr)
	{
		return;
	}
	// rain_veil.scud_card, card for card (the box round the camera).
	const double T = View.TimeSeconds;
	const FVector CameraEnu = EngineToEnu(View.CameraCm);
	const double CameraUpM = (View.CameraCm.Z - ScudDatumZCm) / WeatherCmPerMetre;
	const FVector Up(0.0, 0.0, 1.0);
	TArray<FVector> Vertices;
	TArray<FVector2D> UV0, UV1;
	Vertices.Reserve(ScudCards * 4);
	UV0.Reserve(ScudCards * 4);
	UV1.Reserve(ScudCards * 4);
	const double Half = ScudBoxHalfM;
	for (int32 I = 0; I < ScudCards; ++I)
	{
		const uint64 Index = static_cast<uint64>(I);
		const double E0 = (2.0 * Unit(ScudSeed, Index, 0) - 1.0) * Half + WindEnuMps.X * T;
		const double N0 = (2.0 * Unit(ScudSeed, Index, 1) - 1.0) * Half + WindEnuMps.Y * T;
		const double DE = Wrap(E0 - CameraEnu.X, Half);
		const double DN = Wrap(N0 - CameraEnu.Y, Half);
		const double UpM = ScudBandBottomM + (ScudBandTopM - ScudBandBottomM) * Unit(ScudSeed, Index, 2);
		const double WidthM = ScudWidthMinM + (ScudWidthMaxM - ScudWidthMinM) * Unit(ScudSeed, Index, 3);
		const double HeightM = WidthM * (ScudAspectMin + (ScudAspectMax - ScudAspectMin) * Unit(ScudSeed, Index, 4));
		double Alpha = ScudAlphaMin + (ScudAlphaMax - ScudAlphaMin) * Unit(ScudSeed, Index, 5);
		const double Edge = Half * ScudEdgeShare;
		Alpha *= Smooth(Half, Half - Edge, FMath::Abs(DE)) * Smooth(Half, Half - Edge, FMath::Abs(DN));
		const double ToCameraM = FMath::Sqrt(DE * DE + DN * DN + (UpM - CameraUpM) * (UpM - CameraUpM));
		const double Clear = ScudCameraClearM + 0.5 * WidthM;
		Alpha *= Smooth(Clear, Clear * 1.5, ToCameraM);
		FVector Centre = View.CameraCm + (EastAxis * DE + NorthAxis * DN) * WeatherCmPerMetre;
		Centre.Z = ScudDatumZCm + UpM * WeatherCmPerMetre;
		const FVector ToCam = (View.CameraCm - Centre).GetSafeNormal();
		FVector Right = FVector::CrossProduct(Up, ToCam).GetSafeNormal();
		if (Right.IsNearlyZero())
		{
			Right = EastAxis;
		}
		const FVector CardUp = FVector::CrossProduct(ToCam, Right);
		const FVector W = Right * (0.5 * WidthM * WeatherCmPerMetre);
		const FVector Hh = CardUp * (0.5 * HeightM * WeatherCmPerMetre);
		const FVector2D Card(Alpha, Unit(ScudSeed, Index, 6));
		Vertices.Append({Centre - W - Hh, Centre + W - Hh, Centre - W + Hh, Centre + W + Hh});
		UV0.Append({FVector2D(0.0, 0.0), FVector2D(1.0, 0.0), FVector2D(0.0, 1.0), FVector2D(1.0, 1.0)});
		UV1.Append({Card, Card, Card, Card});
	}
	ScudMesh->UpdateMeshSection_LinearColor(0, Vertices, {}, UV0, UV1, {}, {}, {}, {});
	if (ScudMaterial != nullptr)
	{
		ScudMaterial->SetScalarParameterValue(TEXT("Time"), static_cast<float>(T));
	}
}

// -- visual round 2 (weather scenes, 2026-11-10): the beauty storm vantage ---------
// core/scene/storm_cell.py BEAUTY_VANTAGE_CLEARANCE_M, BEAUTY_RAIN_SHARE_FLOOR,
// TOWER_FLARE, EDGE_M (pinned by tests/test_weather_scenes.py). UNCALIBRATED: set
// by probe render on the render machine.
double FFlightSimWeather::BeautyVantageShiftM(double StartEastM, double StartNorthM, double HeadingDeg,
                                              double TrackM, double AircraftUpM, double CloudBaseM, double CloudTopM,
                                              double CloudOvershootM, double CloudTowerRadiusM, double ClearanceM)
{
	constexpr double WeatherVantageTowerFlare = 0.25;
	constexpr double WeatherVantageEdgeM = 250.0;
	if (!(CloudTowerRadiusM > 0.0) || !(CloudTopM > CloudBaseM) || AircraftUpM < CloudBaseM - WeatherVantageEdgeM ||
	    AircraftUpM > CloudTopM + FMath::Max(CloudOvershootM, 0.0) + WeatherVantageEdgeM)
	{
		return 0.0;   // under the base (the shaft's rain, no cloud) or over the top
	}
	// The tower's radius at the aircraft's height (storm_cell.shapes: flaring upward).
	const double F = FMath::Clamp((AircraftUpM - CloudBaseM) / (CloudTopM - CloudBaseM), 0.0, 1.0);
	const double Radius = CloudTowerRadiusM * (1.0 - WeatherVantageTowerFlare * 0.5 + WeatherVantageTowerFlare * F);
	const double Need = Radius + FMath::Max(ClearanceM, 0.0);
	const double H = FMath::DegreesToRadians(HeadingDeg);
	const double DirE = FMath::Sin(H);
	const double DirN = FMath::Cos(H);
	const double Track = FMath::Max(TrackM, 0.0);
	// The cell centre (the ENU origin) seen from the start: along and across the track.
	const double Along = -(StartEastM * DirE + StartNorthM * DirN);
	const double Across = FMath::Abs(StartNorthM * DirE - StartEastM * DirN);
	if (Across >= Need)
	{
		return 0.0;
	}
	const double HalfChord = FMath::Sqrt(Need * Need - Across * Across);
	if (Along - HalfChord >= Track || Along + HalfChord <= 0.0)
	{
		return 0.0;   // the track never comes within Need of the centre
	}
	// Ahead until the tower's near edge (at this offset) is past the clip's end.
	return Track + HalfChord - Along;
}

bool FFlightSimWeather::BeautyStormLayer(double& OutBaseM, double& OutTopM) const
{
	OutBaseM = LayerBaseDrawnMetres;
	OutTopM = LayerTopDrawnMetres;
	return bCell && LayerCoverDrawn > 0.0 && LayerTopDrawnMetres > LayerBaseDrawnMetres;
}

void FFlightSimWeather::ApplyBeautyStormVantage(const FVector& AircraftCm, const FVector& AircraftForward,
                                                double TrackM, double LayerBaseM, double LayerTopM,
                                                bool bLayerMoved)
{
	constexpr double WeatherBeautyVantageClearanceM = 2500.0;
	constexpr double WeatherBeautyRainShareFloor = 0.3;
	// Visual round 3: core/scene/storm_cell.py BEAUTY_RAGGED, BEAUTY_EROSION
	// (pinned by tests/test_weather_scenes.py). UNCALIBRATED. Round 4: the
	// warp over a 5 km noise, unclamped, and soft_m-wide ramps (round 3's
	// 1.8 km clamped warp and eroded 400 m deck base drew as hatched contour
	// lines at the constrained GPU's ~400 m march step; storm_cell.hlsl).
	constexpr double WeatherRaggedWarpM = 800.0;
	constexpr double WeatherRaggedBaseM = 300.0;
	constexpr double WeatherRaggedScaleM = 5000.0;
	constexpr double WeatherRaggedSoftM = 1000.0;
	constexpr double WeatherBeautyErosion = 0.6;
	// Visual round 6: core/scene/storm_cell.py BEAUTY_SHAFT (round 4's #09 drew
	// the rain shaft as a smooth glowing cylinder). The streaks, the eroded rim
	// and the density floor ride the Ragged gate in storm_cell.hlsl; the albedo
	// is the material's ShaftAlbedo parameter (storm_shaft_albedo.hlsl; its
	// default 1 is the measure path's albedo, value for value). UNCALIBRATED.
	constexpr double WeatherBeautyShaftStreakScale = 0.35;
	constexpr double WeatherBeautyShaftRimErosion = 0.5;
	constexpr double WeatherBeautyShaftDensityFloor = 0.25;
	constexpr double WeatherBeautyShaftAlbedo = 0.55;
	// Lane D (2026-11-11): core/scene/storm_cell.py BEAUTY_CURTAIN (round 4's #09: a
	// hard ring over a glowing cylinder). The material's Curtain parameter (default
	// 0: generation 5's shader): the shaft flares, softens and thins toward the
	// ground, and ragged scud hangs under the base and the deck. UNCALIBRATED.
	constexpr double WeatherBeautyCurtainFlare = 0.8;
	constexpr double WeatherBeautyCurtainGroundThin = 0.5;
	// Round 19: 0 (storm_cell.BEAUTY_CURTAIN): the band's slices drew rings in #09.
	constexpr double WeatherBeautyScudDepthM = 0.0;
	constexpr double WeatherBeautyScudCover = 0.5;
	const TSharedPtr<FJsonObject>* CellRow = nullptr;
	if (!bCell || StormMaterial == nullptr || !Record.IsValid() ||
	    !Record->TryGetObjectField(TEXT("cell"), CellRow) || CellRow == nullptr || !CellRow->IsValid())
	{
		return;
	}
	TSharedPtr<FJsonObject> Row = WeatherRecord();
	const FVector StartEnu = EngineToEnu(AircraftCm);
	const double ForwardE = FVector::DotProduct(AircraftForward, EastAxis);
	const double ForwardN = FVector::DotProduct(AircraftForward, NorthAxis);
	Row->SetNumberField(TEXT("clearance_m"), WeatherBeautyVantageClearanceM);
	Row->SetNumberField(TEXT("track_m"), TrackM);
	Row->SetArrayField(TEXT("aircraft_start_enu_m"), WeatherJsonVector(StartEnu));
	double ShiftM = 0.0;
	if (FMath::Sqrt(ForwardE * ForwardE + ForwardN * ForwardN) > 1.0e-3)
	{
		const double HeadingDeg = FMath::RadiansToDegrees(FMath::Atan2(ForwardE, ForwardN));
		ShiftM = BeautyVantageShiftM(StartEnu.X, StartEnu.Y, HeadingDeg, TrackM, StartEnu.Z, BaseM, CellTopM,
		                             CellOvershootM, CellTowerRadiusM, WeatherBeautyVantageClearanceM);
		Row->SetNumberField(TEXT("heading_deg"), HeadingDeg);
		const double H = FMath::DegreesToRadians(HeadingDeg);
		BeautyCellOffsetCm = EnuVectorToEngine(FVector(ShiftM * FMath::Sin(H), ShiftM * FMath::Cos(H), 0.0))
			* WeatherCmPerMetre;
	}
	else
	{
		Row->SetStringField(TEXT("heading_deg"),
			TEXT("none: no aircraft, or its forward vector has no horizontal part; the cell is not moved"));
	}
	Row->SetNumberField(TEXT("shift_m"), ShiftM);
	Row->SetArrayField(TEXT("drawn_offset_cm"), WeatherJsonVector(BeautyCellOffsetCm));
	if (!BeautyCellOffsetCm.IsZero())
	{
		// The tower, its anvil and shaft (the material's frame), the bolts and the
		// flash light move together; the microburst the physics flies does not.
		StormMaterial->SetVectorParameterValue(TEXT("CellCentreCm"), WeatherColour(CentreEngineCm + BeautyCellOffsetCm));
		if (LightningActor != nullptr)
		{
			LightningActor->SetActorLocation(LightningActor->GetActorLocation() + BeautyCellOffsetCm);
		}
	}
	// The look's deck: the world lane's slab (kept clear of the aircraft).
	if (bLayerMoved && LayerCoverDrawn > 0.0)
	{
		StormMaterial->SetVectorParameterValue(TEXT("Layer"),
			FLinearColor(static_cast<float>(LayerCoverDrawn), static_cast<float>(LayerBaseM),
			             static_cast<float>(LayerTopM), static_cast<float>(LayerExtinctionDrawn)));
	}
	// Visual round 3 (round 2's #09: the tower a hard-walled drum with a flat
	// base, the deck a flat slab with 100 m edges): the material's Ragged
	// block warps the tower's wall by up to WeatherRaggedWarpM, lifts its base
	// and the deck's unevenly (upward only, so the clearance above holds),
	// softens the wall (inward), the base and the deck's base (upward) over
	// WeatherRaggedSoftM, and every edge erodes harder.
	StormMaterial->SetVectorParameterValue(TEXT("Ragged"),
		FLinearColor(static_cast<float>(WeatherRaggedWarpM), static_cast<float>(WeatherRaggedBaseM),
		             static_cast<float>(WeatherRaggedScaleM), static_cast<float>(WeatherRaggedSoftM)));
	StormMaterial->SetVectorParameterValue(TEXT("Noise"),
		FLinearColor(NoiseDrawn.R, NoiseDrawn.G, static_cast<float>(WeatherBeautyErosion), NoiseDrawn.A));
	// Round 6: the rain shaft's albedo (the streaks, rim and floor are the
	// shader's own constants under the Ragged gate set above).
	StormMaterial->SetScalarParameterValue(TEXT("ShaftAlbedo"), static_cast<float>(WeatherBeautyShaftAlbedo));
	StormMaterial->SetVectorParameterValue(TEXT("Curtain"),
		FLinearColor(static_cast<float>(WeatherBeautyCurtainFlare), static_cast<float>(WeatherBeautyCurtainGroundThin),
		             static_cast<float>(WeatherBeautyScudDepthM), static_cast<float>(WeatherBeautyScudCover)));
	{
		TSharedPtr<FJsonObject> Curtain = WeatherRecord();
		Curtain->SetNumberField(TEXT("flare"), WeatherBeautyCurtainFlare);
		Curtain->SetNumberField(TEXT("ground_thin"), WeatherBeautyCurtainGroundThin);
		Curtain->SetNumberField(TEXT("scud_depth_m"), WeatherBeautyScudDepthM);
		Curtain->SetNumberField(TEXT("scud_cover"), WeatherBeautyScudCover);
		Curtain->SetStringField(TEXT("basis"),
			TEXT("storm_cell.BEAUTY_CURTAIN: the shaft hangs from the lifted base, flares toward the ground, its "
			     "edge the wall's warped radius (no circle) softened over 75 % of it, thinning toward the ground "
			     "(the column's water kept); ragged scud in a band under the base and the deck, drifting at half "
			     "the anvil's drift. Visual only; UNCALIBRATED"));
		Row->SetObjectField(TEXT("curtain"), Curtain);
	}
	{
		TSharedPtr<FJsonObject> Shaft = WeatherRecord();
		Shaft->SetNumberField(TEXT("streak_scale"), WeatherBeautyShaftStreakScale);
		Shaft->SetNumberField(TEXT("rim_erosion"), WeatherBeautyShaftRimErosion);
		Shaft->SetNumberField(TEXT("density_floor"), WeatherBeautyShaftDensityFloor);
		Shaft->SetNumberField(TEXT("albedo_scale"), WeatherBeautyShaftAlbedo);
		Shaft->SetStringField(TEXT("basis"),
			TEXT("storm_cell.BEAUTY_SHAFT: the curtain noise sampled finer across (vertical streaks), the rim "
			     "eroded by it (inward only), the density floor opened, the albedo scaled in the shaft "
			     "(storm_shaft_albedo.hlsl): grey rain, not a luminous cylinder. Evaluated inside the measure "
			     "shaft's volume only; visual only; UNCALIBRATED"));
		Row->SetObjectField(TEXT("shaft"), Shaft);
	}
	{
		TSharedPtr<FJsonObject> Ragged = WeatherRecord();
		Ragged->SetNumberField(TEXT("warp_m"), WeatherRaggedWarpM);
		Ragged->SetNumberField(TEXT("base_m"), WeatherRaggedBaseM);
		Ragged->SetNumberField(TEXT("scale_m"), WeatherRaggedScaleM);
		Ragged->SetNumberField(TEXT("soft_m"), WeatherRaggedSoftM);
		Ragged->SetNumberField(TEXT("erosion"), WeatherBeautyErosion);
		Ragged->SetNumberField(TEXT("erosion_card"), NoiseDrawn.B);
		Ragged->SetStringField(TEXT("basis"),
			TEXT("storm_cell.BEAUTY_RAGGED: the tower's wall warped by one octave of value noise (slope under 1: "
			     "no folds), its base and the deck's lifted unevenly (upward only), the wall, the base and the "
			     "deck's base softened over soft_m (no erosion on the deck's base): a soft cloud base, not a slab, "
			     "and no contour lines at the march's step. Visual only; UNCALIBRATED"));
		Row->SetObjectField(TEXT("ragged"), Ragged);
	}
	Row->SetBoolField(TEXT("deck_moved"), bLayerMoved);
	Row->SetNumberField(TEXT("deck_base_m"), bLayerMoved ? LayerBaseM : LayerBaseDrawnMetres);
	Row->SetNumberField(TEXT("deck_top_m"), bLayerMoved ? LayerTopM : LayerTopDrawnMetres);
	// Rain at the aircraft: above the base only the ambient fraction falls (0 for
	// a storm with no stated rate), so round 1's 747 flew in dry cloud.
	if (bRain)
	{
		BeautyRainShareFloor = WeatherBeautyRainShareFloor;
	}
	Row->SetNumberField(TEXT("rain_share_floor"), BeautyRainShareFloor);
	Row->SetStringField(TEXT("basis"),
		TEXT("-quality=beauty: the cell is DRAWN shift_m ahead along the aircraft's track so the clip's track "
		     "stays clearance_m outside the tower (storm_cell.beauty_vantage_shift_m); the look's deck at the "
		     "world lane's slab (world_beauty.aircraft_clear_layer); the drawn rain at least rain_share_floor of "
		     "the shaft's. VISUAL ONLY: the downburst, the wind and every physics number stand; UNCALIBRATED"));
	(*CellRow)->SetObjectField(TEXT("beauty_vantage"), Row);
}

uint64 FFlightSimWeather::SplitMix64(uint64 X)
{
	uint64 Z = X + 0x9E3779B97F4A7C15ull;
	Z = (Z ^ (Z >> 30)) * 0xBF58476D1CE4E5B9ull;
	Z = (Z ^ (Z >> 27)) * 0x94D049BB133111EBull;
	return Z ^ (Z >> 31);
}

double FFlightSimWeather::Unit(uint64 Seed, uint64 Index, uint64 Channel)
{
	const uint64 Key = SplitMix64(Index * 8ull + Channel);
	return static_cast<double>(SplitMix64(Seed ^ Key) >> 11) * (1.0 / 9007199254740992.0);
}

double FFlightSimWeather::TerminalVelocityMps(double DiameterMm)
{
	return WeatherAtlasA - WeatherAtlasB * FMath::Exp(-WeatherAtlasC * DiameterMm);
}

double FFlightSimWeather::SampleDiameterMm(double U, double Lambda, double DMinMm, double DMaxMm)
{
	const double Span = 1.0 - FMath::Exp(-Lambda * (DMaxMm - DMinMm));
	return DMinMm - FMath::Loge(1.0 - U * Span) / Lambda;
}

double FFlightSimWeather::AxisRatio(double DiameterMm)
{
	const double D = DiameterMm / 10.0;   // Beard & Chuang: centimetres
	return 1.0048 + 0.0057 * D - 2.628 * D * D + 3.682 * D * D * D - 1.677 * D * D * D * D;
}

double FFlightSimWeather::PresentedWidthMm(double DiameterMm)
{
	return DiameterMm * FMath::Pow(AxisRatio(DiameterMm), -1.0 / 3.0);
}

double FFlightSimWeather::StrokeEnergy(const FFlightSimLightCurve& C, double Peak, double A, double B)
{
	A = FMath::Max(0.0, A);
	B = FMath::Max(0.0, B);
	if (B <= A)
	{
		return 0.0;
	}
	return Peak * (C.PeakNorm * (WeatherExpIntegral(C.FallS, A, B) - WeatherExpIntegral(C.RiseS, A, B))
	               + C.GlowFraction * WeatherExpIntegral(C.GlowS, A, B));
}

FFlightSimFlashPower FFlightSimWeather::WindowPower(const FFlightSimLightCurve& C,
                                                    const FFlightSimFlash& Flash, double A, double B)
{
	FFlightSimFlashPower Out;
	const double Span = B - A;
	if (!(Span > 0.0))
	{
		return Out;
	}
	double Main = 0.0;
	double Branch = 0.0;
	for (int32 K = 0; K < Flash.Strokes.Num(); ++K)
	{
		const double T0 = Flash.Strokes[K].TimeS;
		const double Energy = StrokeEnergy(C, Flash.Strokes[K].PeakWPerM, A - T0, B - T0);
		Main += Energy;
		if (K == 0)
		{
			Branch += C.BranchStrokeShare * Energy;
		}
	}
	if (Flash.bContinuing)
	{
		Main += Flash.ContinuingWPerM * WeatherOverlap(A, B, Flash.ContinuingStartS,
		                                               Flash.ContinuingStartS + Flash.ContinuingDurationS);
	}
	double Progress = 0.0;
	if (Flash.bLeader)
	{
		const double Lit = C.LeaderWPerM * WeatherOverlap(A, B, Flash.LeaderStartS, Flash.LeaderEndS);
		Main += Lit;
		Branch += Lit;
		Progress = FMath::Clamp((B - Flash.LeaderStartS) / (Flash.LeaderEndS - Flash.LeaderStartS),
		                        0.0, 1.0);
	}
	else
	{
		Progress = B >= Flash.TimeS ? 1.0 : 0.0;
	}
	Out.MainWPerM = Main / Span;
	Out.BranchWPerM = Branch / Span;
	Out.LeaderProgress = Progress;
	return Out;
}

double FFlightSimWeather::IntensityCd(const FFlightSimLightCurve& C, const FFlightSimFlash& Flash,
                                      const FFlightSimFlashPower& Power)
{
	double MainLength = 0.0;
	double BranchLength = 0.0;
	for (const FFlightSimChannel& Channel : Flash.Channels)
	{
		(Channel.bBranch ? BranchLength : MainLength) += Channel.LengthM;
	}
	const double Lumens = C.EfficacyLmPerW * (Power.MainWPerM * MainLength
	                                          + Power.BranchWPerM * BranchLength);
	return Lumens / (4.0 * WeatherPi);
}

double FFlightSimWeather::SynthesiseThunder(const FFlightSimThunderConstants& K,
                                            const FFlightSimFlash& Flash, const FVector& Listener,
                                            int32 SampleRateHz, TArray<double>& OutSamples)
{
	// core/scene/thunder.py synthesise, step for step (its docstring states
	// the sample loop); the order of accumulation is the Python's.
	struct FPlanned
	{
		int64 N0;
		int64 Count;
		int64 Tail;
		double Amplitude;
		double Half;
		double Corner;
	};
	TArray<FPlanned> Plan;
	const double Fs = static_cast<double>(SampleRateHz);
	const double Peak0 = Flash.Strokes.Num() > 0 ? Flash.Strokes[0].PeakWPerM : 1.0;
	int64 End = 0;
	double First = TNumericLimits<double>::Max();
	for (int32 StrokeIndex = 0; StrokeIndex < Flash.Strokes.Num(); ++StrokeIndex)
	{
		const FFlightSimStroke& Stroke = Flash.Strokes[StrokeIndex];
		for (const FFlightSimChannel& Channel : Flash.Channels)
		{
			if (Channel.bBranch && StrokeIndex > 0)
			{
				continue;
			}
			for (int32 I = 0; I + 1 < Channel.PointsEnu.Num(); ++I)
			{
				const FVector& Pa = Channel.PointsEnu[I];
				const FVector& Pb = Channel.PointsEnu[I + 1];
				const FVector D = Pb - Pa;
				const double Length = FMath::Sqrt(D.X * D.X + D.Y * D.Y + D.Z * D.Z);
				if (Length <= 0.0)
				{
					continue;
				}
				const FVector Mid(0.5 * (Pa.X + Pb.X), 0.5 * (Pa.Y + Pb.Y), 0.5 * (Pa.Z + Pb.Z));
				const FVector Dir(D.X / Length, D.Y / Length, D.Z / Length);
				const FVector Rel(Listener.X - Mid.X, Listener.Y - Mid.Y, Listener.Z - Mid.Z);
				const double R = FMath::Max(WeatherThunderRMinM,
				                            FMath::Sqrt(Rel.X * Rel.X + Rel.Y * Rel.Y + Rel.Z * Rel.Z));
				const double Cos = FMath::Abs(Rel.X * Dir.X + Rel.Y * Dir.Y + Rel.Z * Dir.Z) / R;
				const double Sin = FMath::Sqrt(FMath::Max(0.0, 1.0 - Cos * Cos));
				const double Directivity = K.DirectivityFloor + (1.0 - K.DirectivityFloor) * Sin;
				const double Lengthen = 1.0 + K.Lengthening
					* FMath::Loge(FMath::Max(R, K.RelaxationRadiusM) / K.RelaxationRadiusM);
				const double Half = K.T0S * FMath::Sqrt(Lengthen);
				double Audibility = 1.0;
				if (R >= K.AudibleMaxM)
				{
					Audibility = 0.0;
				}
				else if (R > K.AudibleFullM)
				{
					const double X = (K.AudibleMaxM - R) / (K.AudibleMaxM - K.AudibleFullM);
					Audibility = X * X * (3.0 - 2.0 * X);
				}
				const double Amplitude = K.PressureRefPaM * Length / R * Directivity
					* FMath::Sqrt(Stroke.PeakWPerM / Peak0) / FMath::Sqrt(Lengthen) * Audibility;
				if (Amplitude <= 0.0)
				{
					continue;
				}
				const double Corner = K.AbsorptionF0Hz / (1.0 + R / K.AbsorptionRM);
				const double Arrival = Stroke.TimeS - Flash.TimeS + R / K.SoundSpeedMps;
				FPlanned Entry;
				Entry.N0 = static_cast<int64>(FMath::RoundHalfToEven(Arrival * Fs));
				Entry.Count = static_cast<int64>(FMath::CeilToDouble(2.0 * Half * Fs));
				Entry.Tail = static_cast<int64>(FMath::CeilToDouble(
					WeatherThunderTailTimeConstants * Fs / (2.0 * WeatherPi * Corner)));
				Entry.Amplitude = Amplitude;
				Entry.Half = Half;
				Entry.Corner = Corner;
				Plan.Add(Entry);
				End = FMath::Max(End, Entry.N0 + Entry.Count + Entry.Tail);
				First = FMath::Min(First, Arrival);
			}
		}
	}
	OutSamples.Reset();
	OutSamples.SetNumZeroed(static_cast<int32>(FMath::Max<int64>(End, 0)));
	for (const FPlanned& Entry : Plan)
	{
		const double Alpha = 1.0 - FMath::Exp(-2.0 * WeatherPi * Entry.Corner / Fs);
		const double Inverse = 1.0 / (Fs * Entry.Half);
		double Y = 0.0;
		for (int64 J = 0; J < Entry.Count + Entry.Tail; ++J)
		{
			const double X = J < Entry.Count ? Entry.Amplitude * (1.0 - J * Inverse) : 0.0;
			Y += Alpha * (X - Y);
			const int64 Index = Entry.N0 + J;
			if (Index >= 0 && Index < OutSamples.Num())
			{
				OutSamples[static_cast<int32>(Index)] += Y;
			}
		}
	}
	return Plan.Num() > 0 ? First : -1.0;
}

bool FFlightSimWeather::ParseFlash(const TSharedPtr<FJsonObject>& Json, FFlightSimFlash& Out,
                                   FString& Error)
{
	double Index = 0.0;
	FString Kind;
	if (!WeatherNumber(Json, TEXT("t_s"), Out.TimeS, TEXT("a flash"), Error))
	{
		return false;
	}
	Json->TryGetNumberField(TEXT("index"), Index);
	Out.Index = static_cast<int32>(Index);
	Json->TryGetStringField(TEXT("kind"), Kind);
	Out.bCloudToGround = Kind == TEXT("cg");
	const TArray<TSharedPtr<FJsonValue>>* Leader = nullptr;
	if (Json->TryGetArrayField(TEXT("leader"), Leader) && Leader != nullptr && Leader->Num() == 2)
	{
		Out.bLeader = true;
		Out.LeaderStartS = (*Leader)[0]->AsNumber();
		Out.LeaderEndS = (*Leader)[1]->AsNumber();
	}
	const TArray<TSharedPtr<FJsonValue>>* Strokes = nullptr;
	if (!Json->TryGetArrayField(TEXT("strokes"), Strokes) || Strokes == nullptr || Strokes->Num() == 0)
	{
		Error = TEXT("weather.card: a flash carries no strokes");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Strokes)
	{
		FFlightSimStroke Stroke;
		const TSharedPtr<FJsonObject> StrokeJson = Value->AsObject();
		if (!WeatherNumber(StrokeJson, TEXT("t_s"), Stroke.TimeS, TEXT("a stroke"), Error) ||
		    !WeatherNumber(StrokeJson, TEXT("peak_w_per_m"), Stroke.PeakWPerM, TEXT("a stroke"), Error))
		{
			return false;
		}
		Out.Strokes.Add(Stroke);
	}
	const TSharedPtr<FJsonObject>* Continuing = nullptr;
	if (Json->TryGetObjectField(TEXT("continuing"), Continuing) && Continuing != nullptr &&
	    Continuing->IsValid())
	{
		Out.bContinuing = true;
		if (!WeatherNumber(*Continuing, TEXT("t_s"), Out.ContinuingStartS, TEXT("continuing"), Error) ||
		    !WeatherNumber(*Continuing, TEXT("duration_s"), Out.ContinuingDurationS, TEXT("continuing"),
		                   Error) ||
		    !WeatherNumber(*Continuing, TEXT("w_per_m"), Out.ContinuingWPerM, TEXT("continuing"), Error))
		{
			return false;
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* Channels = nullptr;
	if (!Json->TryGetArrayField(TEXT("channels"), Channels) || Channels == nullptr)
	{
		Error = TEXT("weather.card: a flash carries no channels");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Channels)
	{
		const TSharedPtr<FJsonObject> ChannelJson = Value->AsObject();
		FFlightSimChannel Channel;
		FString ChannelKind;
		ChannelJson->TryGetStringField(TEXT("kind"), ChannelKind);
		Channel.bBranch = ChannelKind == TEXT("branch");
		ChannelJson->TryGetNumberField(TEXT("length_m"), Channel.LengthM);
		const TArray<TSharedPtr<FJsonValue>>* Points = nullptr;
		if (!ChannelJson->TryGetArrayField(TEXT("points"), Points) || Points == nullptr)
		{
			Error = TEXT("weather.card: a channel carries no points");
			return false;
		}
		for (const TSharedPtr<FJsonValue>& Point : *Points)
		{
			Channel.PointsEnu.Add(WeatherPoint(Point));
		}
		Out.Channels.Add(MoveTemp(Channel));
	}
	const TArray<TSharedPtr<FJsonValue>>* Centroid = nullptr;
	if (Json->TryGetArrayField(TEXT("centroid_enu_m"), Centroid) && Centroid != nullptr &&
	    Centroid->Num() == 3)
	{
		Out.CentroidEnu = FVector((*Centroid)[0]->AsNumber(), (*Centroid)[1]->AsNumber(),
		                          (*Centroid)[2]->AsNumber());
	}
	return true;
}

bool FFlightSimWeather::ParseBackend(const FString& Name, EFlightSimWeatherBackend& Out,
                                     FString& Error)
{
	if (Name == TEXT("procedural"))
	{
		Out = EFlightSimWeatherBackend::Procedural;
	}
	else if (Name == TEXT("niagara"))
	{
		Out = EFlightSimWeatherBackend::Niagara;
	}
	else if (Name.IsEmpty() || Name == TEXT("off"))
	{
		Out = EFlightSimWeatherBackend::Off;
	}
	else
	{
		Error = FString::Printf(TEXT("weather.backend: '%s' is not one of procedural, niagara, off"),
		                        *Name);
		return false;
	}
	return true;
}

bool FFlightSimWeather::ParseLightningShadows(const FString& Params, bool& bOut, FString& Error)
{
	// The command line first, then FLIGHTSIM_RENDER_SWITCHES (what
	// visual_fix_round.ps1 -Switches sets), as -deck-shadow= is read.
	const FString Switches = Params + TEXT(" ")
		+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
	FString Word = TEXT("off");
	FParse::Value(*Switches, TEXT("lightning-shadows="), Word);
	if (Word == TEXT("on"))
	{
		bOut = true;
	}
	else if (Word == TEXT("off"))
	{
		bOut = false;
	}
	else
	{
		Error = FString::Printf(TEXT("weather.lightning_shadows: -lightning-shadows=%s is not on or off"), *Word);
		return false;
	}
	return true;
}

// -- every cloud in the world, before the first frame --------------------------------

bool FFlightSimWeather::VerifyCloudMaterials(UWorld* World, FString& Error,
                                             TArray<FString>* OutReport)
{
	// The engine's volumetric cloud passes (VolumetricCloudRendering.cpp)
	// walk the material's fallback chain and ASSERT when it ends at a
	// non-Volume material -- a crash, not a refusal. This mirrors their
	// test on the game thread for every registered cloud component and
	// refuses by name (clouds.material) with the component, its material,
	// the domain, the usage flag and the compiler's errors, so a bad cloud
	// is a readable line in the log rather than a callstack.
	bool bOk = true;
	const EShaderPlatform Platform = GShaderPlatformForFeatureLevel[World->GetFeatureLevel()];
	for (TObjectIterator<UVolumetricCloudComponent> It; It; ++It)
	{
		UVolumetricCloudComponent* Cloud = *It;
		if (Cloud->GetWorld() != World || !Cloud->IsRegistered())
		{
			continue;
		}
		const FString Owner = Cloud->GetOwner() != nullptr ? Cloud->GetOwner()->GetName() : TEXT("(no owner)");
		UMaterialInterface* Material = Cloud->GetMaterial();
		FString Line = FString::Printf(TEXT("cloud %s (%s): "), *Cloud->GetName(), *Owner);
		FString Why;
		if (Material == nullptr)
		{
			Line += TEXT("no material (draws nothing)");
		}
		else
		{
			UMaterial* Base = Material->GetMaterial();
			Line += Material->GetPathName();
			if (Base == nullptr)
			{
				Why = TEXT("has no base material");
			}
			else
			{
				Line += FString::Printf(TEXT(", domain %d, used_with_volumetric_cloud %s"),
				                        static_cast<int32>(Base->MaterialDomain),
				                        Base->GetUsageByFlag(MATUSAGE_VolumetricCloud) ? TEXT("yes") : TEXT("NO"));
				if (Base->MaterialDomain != MD_Volume)
				{
					Why = TEXT("is not a Volume material");
				}
				else if (!Base->GetUsageByFlag(MATUSAGE_VolumetricCloud))
				{
					Why = TEXT("is not flagged 'Used with Volumetric Cloud' (no cloud shaders)");
				}
				else if (FMaterialResource* Resource = FLIGHTSIM_GET_MATERIAL_RESOURCE(Base, World, Platform))
				{
					Resource->FinishCompilation();
					if (Resource->GetCompileErrors().Num() > 0)
					{
						Why = TEXT("failed to compile: ") + FString::Join(Resource->GetCompileErrors(), TEXT(" | "));
					}
					else if (Resource->GetGameThreadShaderMap() == nullptr)
					{
						Why = TEXT("has no shader map after compiling");
					}
					else
					{
						Line += TEXT(", compiled");
					}
				}
				else
				{
					Why = TEXT("has no material resource for this shader platform");
				}
			}
		}
		if (!Why.IsEmpty())
		{
			Line += TEXT(" -- ") + Why;
			if (bOk)   // the first bad cloud names the refusal
			{
				Error = FString::Printf(TEXT("clouds.material: the volumetric cloud %s of %s carries %s, which %s; ")
				                        TEXT("the engine would assert on it, so the render refuses instead"),
				                        *Cloud->GetName(), *Owner,
				                        Material != nullptr ? *Material->GetPathName() : TEXT("nothing"), *Why);
			}
			bOk = false;
		}
		UE_LOG(LogFlightSimWeather, Display, TEXT("%s"), *Line);
		if (OutReport != nullptr)
		{
			OutReport->Add(Line);
		}
	}
	return bOk;
}

// -- the frame -------------------------------------------------------------------

FVector FFlightSimWeather::EnuVectorToEngine(const FVector& Enu) const
{
	return EastAxis * Enu.X + NorthAxis * Enu.Y + FVector(0.0, 0.0, 1.0) * Enu.Z;
}

FVector FFlightSimWeather::EnuToEngineCm(const FVector& Enu) const
{
	return CentreEngineCm + EnuVectorToEngine(Enu) * WeatherCmPerMetre;
}

FVector FFlightSimWeather::EngineToEnu(const FVector& EngineCm) const
{
	const FVector Rel = (EngineCm - CentreEngineCm) / WeatherCmPerMetre;
	return FVector(FVector::DotProduct(Rel, EastAxis), FVector::DotProduct(Rel, NorthAxis), Rel.Z);
}

bool FFlightSimWeather::MeasureFrame(const FFlightSimWeatherOptions& Options, FString& Error)
{
	AGeoReferencingSystem* Geo = Options.GeoReferencing;
	if (Geo == nullptr)
	{
		Error = TEXT("weather.frame: the weather is placed through the georeferencing system the ")
		        TEXT("scenario built; none was given");
		return false;
	}
	double Datum = 0.0;
	Options.Card->TryGetNumberField(TEXT("terrain_elevation_m"), Datum);
	FVector CentreProjected;
	const TSharedPtr<FJsonObject>* DownburstJson = nullptr;
	if (Options.Card->TryGetObjectField(TEXT("downburst"), DownburstJson) && DownburstJson != nullptr)
	{
		double OriginX = 0.0, OriginY = 0.0, CoreRadius = 0.0, OutflowMax = 0.0, OutflowHeight = 0.0;
		if (!WeatherNumber(*DownburstJson, TEXT("origin_x_m"), OriginX, TEXT("downburst"), Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("origin_y_m"), OriginY, TEXT("downburst"), Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("centre_north_m"), CentreNorthMetres, TEXT("downburst"),
		                   Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("centre_east_m"), CentreEastMetres, TEXT("downburst"),
		                   Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("core_radius_m"), CoreRadius, TEXT("downburst"), Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("outflow_max_mps"), OutflowMax, TEXT("downburst"), Error) ||
		    !WeatherNumber(*DownburstJson, TEXT("outflow_height_m"), OutflowHeight, TEXT("downburst"),
		                   Error))
		{
			return false;
		}
		Downburst.Init(CentreNorthMetres, CentreEastMetres, CoreRadius, OutflowMax, OutflowHeight);
		bDownburst = true;
		CentreProjected = FVector(OriginX + CentreEastMetres, OriginY + CentreNorthMetres, Datum);
	}
	else
	{
		// No storm centre on the card: the frame is the engine origin's.
		Geo->EngineToProjected(FVector::ZeroVector, CentreProjected);
		CentreProjected.Z = Datum;
	}
	FVector East, North;
	Geo->ProjectedToEngine(CentreProjected, CentreEngineCm);
	Geo->ProjectedToEngine(CentreProjected + FVector(1.0, 0.0, 0.0), East);
	Geo->ProjectedToEngine(CentreProjected + FVector(0.0, 1.0, 0.0), North);
	EastAxis = (East - CentreEngineCm).GetSafeNormal();
	NorthAxis = (North - CentreEngineCm).GetSafeNormal();
	// Measured, not assumed: the georeferencing's own axes (engine Y is
	// south on the plugin's convention; whichever it is, it is read here).
	TSharedPtr<FJsonObject> Frame = WeatherRecord();
	Frame->SetArrayField(TEXT("centre_engine_cm"), WeatherJsonVector(CentreEngineCm));
	Frame->SetArrayField(TEXT("east_axis"), WeatherJsonVector(EastAxis));
	Frame->SetArrayField(TEXT("north_axis"), WeatherJsonVector(NorthAxis));
	Frame->SetStringField(TEXT("centre"), bDownburst ? TEXT("the card's downburst block")
	                                                 : TEXT("the engine origin (no downburst block)"));
	Record->SetObjectField(TEXT("frame"), Frame);
	return true;
}

FVector FFlightSimWeather::WindEngineCmPerS(const FVector& CameraEnu) const
{
	FVector Enu = WindEnuMps;
	if (bDownburst)
	{
		double North = 0.0, East = 0.0, Down = 0.0;
		Downburst.WindNedMps(CentreNorthMetres + CameraEnu.Y, CentreEastMetres + CameraEnu.X,
		                     FMath::Max(0.0, CameraEnu.Z), North, East, Down);
		Enu += FVector(East, North, -Down);
	}
	return EnuVectorToEngine(Enu) * WeatherCmPerMetre;
}

double FFlightSimWeather::ShaftShare(const FVector& CameraEnu) const
{
	if (!bCell)
	{
		return 1.0;
	}
	if (CameraEnu.Z > BaseM)
	{
		return AmbientFraction;   // above the base only the ambient rain falls
	}
	const double R = FMath::Sqrt(CameraEnu.X * CameraEnu.X + CameraEnu.Y * CameraEnu.Y);
	return AmbientFraction + (1.0 - AmbientFraction)
		* WeatherSmoothstep(ShaftRadiusM, 0.6 * ShaftRadiusM, R);
}

// -- build -----------------------------------------------------------------------

bool FFlightSimWeather::Build(UWorld* World, const FFlightSimWeatherOptions& Options, FString& Error)
{
	RainGain = FMath::Clamp(Options.RainGain, 0.0, 100.0);
	bCinematicRain = Options.RainStyle.Equals(TEXT("cinematic"), ESearchCase::IgnoreCase);
	Record = WeatherRecord();
	WorldRef = World;
	Backend = Options.Backend;
	bAudio = Options.bAudio;
	bManualNiagaraTick = Options.bManualNiagaraTick;
	bFlashShadows = Options.bLightningShadows;
	// maxpick/rain: the baked tier 0 (beauty only, default off; the host sets these).
	bRainLayers = Options.bRainLayers;
	bWindscreenBaked = Options.bWindscreenBaked;
	const TSharedPtr<FJsonObject>* WeatherJson = nullptr;
	if (!Options.Card.IsValid() || !Options.Card->TryGetObjectField(TEXT("weather"), WeatherJson) ||
	    WeatherJson == nullptr || !WeatherJson->IsValid())
	{
		Record->SetBoolField(TEXT("asked"), false);
		return true;   // no weather on the card: nothing is spawned
	}
	Record->SetBoolField(TEXT("asked"), true);
	const TCHAR* BackendName = Backend == EFlightSimWeatherBackend::Niagara ? TEXT("niagara")
		: Backend == EFlightSimWeatherBackend::Off ? TEXT("off") : TEXT("procedural");
	Record->SetStringField(TEXT("backend"), BackendName);
	if (Backend == EFlightSimWeatherBackend::Off)
	{
		Record->SetStringField(TEXT("note"), TEXT("-weather-backend=off: nothing drawn"));
		return true;
	}
	if (!MeasureFrame(Options, Error))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>& Weather = *WeatherJson;

	// The cell first: the rain reads its shaft.
	const TSharedPtr<FJsonObject>* CellJson = nullptr;
	if (Weather->TryGetObjectField(TEXT("cell"), CellJson) && CellJson != nullptr)
	{
		if (!bDownburst)
		{
			TSharedPtr<FJsonObject> Row = WeatherRecord();
			Row->SetBoolField(TEXT("drawn"), false);
			Row->SetStringField(TEXT("why"), TEXT("the card carries no downburst block: the storm has ")
			                                 TEXT("no place (its centre is the microburst's)"));
			Record->SetObjectField(TEXT("cell"), Row);
		}
		else if (!BuildCell(World, *CellJson, Options, Error))
		{
			return false;
		}
	}
	const TSharedPtr<FJsonObject>* RainJson = nullptr;
	if (Weather->TryGetObjectField(TEXT("rain"), RainJson) && RainJson != nullptr &&
	    !BuildRain(World, *RainJson, Options, Error))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* ThunderJson = nullptr;
	if (Weather->TryGetObjectField(TEXT("thunder"), ThunderJson) && ThunderJson != nullptr &&
	    !ReadThunder(*ThunderJson, Error))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* LightningJson = nullptr;
	if (Weather->TryGetObjectField(TEXT("lightning"), LightningJson) && LightningJson != nullptr)
	{
		if (!bCell)
		{
			TSharedPtr<FJsonObject> Row = WeatherRecord();
			Row->SetBoolField(TEXT("drawn"), false);
			Row->SetStringField(TEXT("why"), TEXT("no cell drawn: the channels are in its frame"));
			Record->SetObjectField(TEXT("lightning"), Row);
		}
		else if (!BuildLightning(World, *LightningJson, Error))
		{
			return false;
		}
	}
	TArray<TSharedPtr<FJsonValue>> NotClaimed;
	for (const TCHAR* Line : {
	         TEXT("drops are advected by the wind at the camera, not their own"),
	         TEXT("splashes only on the ground plane under the camera (the scene datum)"),
	         TEXT("the cell does not grow or decay; no mammatus, wall cloud or hail"),
	         TEXT("whether the volumetric cloud reads Extinction per metre is a Windows measurement"),
	         TEXT("lightning: the leader drawn as a smooth descent; the channel inside the cloud as glow"),
	         TEXT("thunder is heard only in the interactive window; the render records its schedule")})
	{
		NotClaimed.Add(MakeShared<FJsonValueString>(Line));
	}
	Record->SetArrayField(TEXT("not_claimed"), NotClaimed);
	StartRainNoise();
	Record->SetBoolField(TEXT("rain_audio"), RainVoice != nullptr);
	bBuilt = true;
	UE_LOG(LogFlightSimWeather, Display,
	       TEXT("weather: backend %s, rain %s (%d drops, weight %.2f), cell %s, %d flashes"),
	       BackendName, bRain ? TEXT("on") : TEXT("off"), Particles, Weight,
	       bCell ? TEXT("on") : TEXT("off"), Flashes.Num());
	return true;
}

bool FFlightSimWeather::BuildRain(UWorld* World, const TSharedPtr<FJsonObject>& Rain,
                                  const FFlightSimWeatherOptions& Options, FString& Error)
{
	TArray<double> Box, Wind;
	double ParticlesD = 0.0, SeedD = 0.0, RateMmh = 0.0;
	if (!WeatherNumber(Rain, TEXT("lambda"), RainLambda, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("d_render_min_mm"), RainDMinMm, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("d_max_mm"), RainDMaxMm, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("particles"), ParticlesD, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("weight"), Weight, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("ambient_fraction"), AmbientFraction, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("fall_speed_factor"), FallSpeedFactor, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("seed"), SeedD, TEXT("weather.rain"), Error) ||
	    !WeatherNumber(Rain, TEXT("rate_mmh"), RateMmh, TEXT("weather.rain"), Error) ||
	    !WeatherVector(Rain, TEXT("box_half_m"), 3, Box, TEXT("weather.rain"), Error) ||
	    !WeatherVector(Rain, TEXT("wind_enu_mps"), 3, Wind, TEXT("weather.rain"), Error))
	{
		return false;
	}
	// The card masks the seed to 53 bits, so the JSON number carries it
	// exactly; the selftest below would catch one that did not survive.
	RainSeed = static_cast<uint64>(SeedD);
	RainRateMmh = RateMmh;
	Particles = static_cast<int32>(ParticlesD);
	BoxHalfM = FVector(Box[0], Box[1], Box[2]);
	WindEnuMps = FVector(Wind[0], Wind[1], Wind[2]);
	if (!bCell)
	{
		AmbientFraction = 1.0;   // no shaft: the stated rain falls everywhere
	}
	D0Mm = 3.67 / RainLambda;    // precipitation.py MEDIAN_VOLUME_FACTOR

	// The selftest: the first drops, exactly as rain_field.py drew them.
	const TArray<TSharedPtr<FJsonValue>>* Selftest = nullptr;
	if (!Rain->TryGetArrayField(TEXT("selftest"), Selftest) || Selftest == nullptr || Selftest->Num() == 0)
	{
		Error = TEXT("weather.selftest: weather.rain carries no selftest drops; the drop sampler is ")
		        TEXT("checked against the card or not used");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Selftest)
	{
		const TSharedPtr<FJsonObject> Drop = Value->AsObject();
		double IndexD = 0.0, DMm = 0.0, WidthMm = 0.0, Vt = 0.0, Phase = 0.0;
		TArray<double> P0;
		if (!WeatherNumber(Drop, TEXT("index"), IndexD, TEXT("a selftest drop"), Error) ||
		    !WeatherNumber(Drop, TEXT("d_mm"), DMm, TEXT("a selftest drop"), Error) ||
		    !WeatherNumber(Drop, TEXT("width_mm"), WidthMm, TEXT("a selftest drop"), Error) ||
		    !WeatherNumber(Drop, TEXT("v_t_mps"), Vt, TEXT("a selftest drop"), Error) ||
		    !WeatherNumber(Drop, TEXT("phase"), Phase, TEXT("a selftest drop"), Error) ||
		    !WeatherVector(Drop, TEXT("p0_m"), 3, P0, TEXT("a selftest drop"), Error))
		{
			return false;
		}
		const uint64 Index = static_cast<uint64>(IndexD);
		const double D = SampleDiameterMm(Unit(RainSeed, Index, 3), RainLambda, RainDMinMm, RainDMaxMm);
		bool bOk = WeatherClose(D, DMm) && WeatherClose(PresentedWidthMm(D), WidthMm) &&
		           WeatherClose(TerminalVelocityMps(D) * FallSpeedFactor, Vt) &&
		           WeatherClose(Unit(RainSeed, Index, 4), Phase);
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			bOk = bOk && WeatherClose((2.0 * Unit(RainSeed, Index, static_cast<uint64>(Axis)) - 1.0) * BoxHalfM[Axis], P0[Axis]);
		}
		if (!bOk)
		{
			Error = FString::Printf(
				TEXT("weather.selftest: drop %llu drawn here (D %.12f mm) is not the card's (D %.12f mm); ")
				TEXT("the port of rain_field.py disagrees with its reference"), Index, D, DMm);
			return false;
		}
	}

	// The splashes and the glass.
	const TSharedPtr<FJsonObject>* Splash = nullptr;
	if (Rain->TryGetObjectField(TEXT("splash"), Splash) && Splash != nullptr)
	{
		double Slots = 0.0;
		if (!WeatherNumber(*Splash, TEXT("period_s"), SplashPeriodS, TEXT("weather.rain.splash"), Error) ||
		    !WeatherNumber(*Splash, TEXT("lifetime_s"), SplashLifetimeS, TEXT("weather.rain.splash"), Error) ||
		    !WeatherNumber(*Splash, TEXT("radius_m"), SplashHalfSideM, TEXT("weather.rain.splash"), Error) ||
		    !WeatherNumber(*Splash, TEXT("slots"), Slots, TEXT("weather.rain.splash"), Error) ||
		    !WeatherNumber(*Splash, TEXT("weight"), SplashWeight, TEXT("weather.rain.splash"), Error) ||
		    !WeatherNumber(*Splash, TEXT("max_agl_m"), SplashMaxAglM, TEXT("weather.rain.splash"), Error))
		{
			return false;
		}
		SplashSlots = static_cast<int32>(Slots);
	}
	const TSharedPtr<FJsonObject>* Glass = nullptr;
	if (Rain->TryGetObjectField(TEXT("windshield"), Glass) && Glass != nullptr)
	{
		(*Glass)->TryGetNumberField(TEXT("impinge_per_m2_s"), WindshieldImpinge);
		(*Glass)->TryGetNumberField(TEXT("runoff_mps"), WindshieldRunoffMps);
	}

	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetNumberField(TEXT("rate_mmh"), RateMmh);
	Row->SetNumberField(TEXT("particles"), Particles);
	Row->SetNumberField(TEXT("weight"), Weight);
	Row->SetNumberField(TEXT("gain"), RainGain);
	Row->SetStringField(TEXT("style"), bCinematicRain ? TEXT("cinematic") : TEXT("physical"));
	Row->SetStringField(TEXT("style_basis"), bCinematicRain
		? TEXT("the rain an observer sees: the drops' fall and the wind over a 1/15 s exposure, the "
		       "camera's own motion left out (a stated stylisation, as film shows rain)")
		: TEXT("the streaks a camera on the aircraft records over its exposure (Garg & Nayar)"));
	Row->SetStringField(TEXT("gain_basis"), RainGain == 1.0
		? TEXT("1: the streak coverage of Garg & Nayar, unexaggerated")
		: TEXT("a stated exaggeration of the drops' opacity (-rain-gain=): the rain is shown, not measured"));
	Row->SetNumberField(TEXT("ambient_fraction"), AmbientFraction);
	Row->SetNumberField(TEXT("selftest_drops"), Selftest->Num());
	RainActor = World->SpawnActor<AActor>();
	RainActor->Tags.Add(FName(TEXT("FlightSim.weather")));
	BeautyOnlyActors.Add(RainActor);
	if (bRainLayers)
	{
		// maxpick/rain: -rain-layers=on draws no particles (262,144 drops lose the
		// integrated GPU); ApplyRainLayers puts the baked layers on the beauty capture.
		Row->SetStringField(TEXT("drops"), TEXT("none: -rain-layers=on (M_RainLayers, three baked layers)"));
		Row->SetStringField(TEXT("determinism"),
			TEXT("the layers' phase integrated from the sim clock: deterministic in the step"));
	}
	else if (Backend == EFlightSimWeatherBackend::Niagara)
	{
		if (!BuildNiagaraRain(World, Options, Error))
		{
			return false;
		}
		Row->SetStringField(TEXT("drops"), WeatherNiagaraRainPath);
		Row->SetStringField(TEXT("determinism"),
			TEXT("GPU-simulated: a replay is NOT byte-identical (the procedural backend is)"));
	}
	else
	{
		if (!BuildRainMesh(World, Error))
		{
			return false;
		}
		Row->SetStringField(TEXT("drops"), WeatherRainMaterialPath);
		Row->SetStringField(TEXT("determinism"),
			TEXT("every drop a pure function of (index, seed, run time): deterministic in the step"));
	}
	if (SplashSlots > 0 && !BuildSplashMesh(World, Error))
	{
		return false;
	}
	Row->SetNumberField(TEXT("splash_slots"), SplashSlots);
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("label_captures"), TEXT("hidden (BeautyOnlyActors)"));
	Row->SetStringField(TEXT("drawn_as"), bRainLayers ? TEXT("baked_layers") : TEXT("particles"));
	Record->SetObjectField(TEXT("rain"), Row);
	bRain = true;
	return true;
}

bool FFlightSimWeather::BuildRainMesh(UWorld* World, FString& Error)
{
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherRainMaterialPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.rain_material: %s (scripts/ue_create_materials.py) did ")
		                        TEXT("not load; the drops are drawn by it or not at all"),
		                        WeatherRainMaterialPath);
		return false;
	}
	// Four vertices per drop, all at the drop's seed position in the box
	// (engine axes, cm): the material moves each to its place and stretches
	// the quad into the streak. UV0 the corner, UV1 (D mm, fall speed m/s),
	// UV2 (presented width mm, phase), UV3 (index / count).
	TArray<FVector> Vertices;
	TArray<int32> Triangles;
	TArray<FVector2D> UV0, UV1, UV2, UV3;
	Vertices.Reserve(Particles * 4);
	Triangles.Reserve(Particles * 6);
	UV0.Reserve(Particles * 4);
	UV1.Reserve(Particles * 4);
	UV2.Reserve(Particles * 4);
	UV3.Reserve(Particles * 4);
	const FVector2D Corners[4] = {FVector2D(0.0, 0.0), FVector2D(1.0, 0.0), FVector2D(0.0, 1.0),
	                              FVector2D(1.0, 1.0)};
	for (int32 I = 0; I < Particles; ++I)
	{
		const uint64 Index = static_cast<uint64>(I);
		const FVector P0((2.0 * Unit(RainSeed, Index, 0) - 1.0) * BoxHalfM.X * WeatherCmPerMetre,
		                 (2.0 * Unit(RainSeed, Index, 1) - 1.0) * BoxHalfM.Y * WeatherCmPerMetre,
		                 (2.0 * Unit(RainSeed, Index, 2) - 1.0) * BoxHalfM.Z * WeatherCmPerMetre);
		const double D = SampleDiameterMm(Unit(RainSeed, Index, 3), RainLambda, RainDMinMm, RainDMaxMm);
		const FVector2D Drop(D, TerminalVelocityMps(D) * FallSpeedFactor);
		const FVector2D Extra(PresentedWidthMm(D), Unit(RainSeed, Index, 4));
		const FVector2D Order(static_cast<double>(I) / FMath::Max(1, Particles), 0.0);
		const int32 Base = Vertices.Num();
		for (const FVector2D& Corner : Corners)
		{
			Vertices.Add(P0);
			UV0.Add(Corner);
			UV1.Add(Drop);
			UV2.Add(Extra);
			UV3.Add(Order);
		}
		Triangles.Append({Base, Base + 2, Base + 1, Base + 1, Base + 2, Base + 3});
	}
	RainMesh = NewObject<UProceduralMeshComponent>(RainActor, TEXT("RainDrops"));
	RainActor->SetRootComponent(RainMesh);
	RainMesh->SetMobility(EComponentMobility::Movable);
	RainMesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, UV0, UV1, UV2, UV3, {}, {},
	                                        false /* no collision */);
	RainMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	RainMesh->SetCastShadow(false);
	// The offset moves a drop anywhere in the box and a streak a little past
	// it: the bounds are the box's, inflated.
	RainMesh->SetBoundsScale(2.0f);
	RainMaterial = UMaterialInstanceDynamic::Create(Material, RainActor);
	RainMaterial->SetVectorParameterValue(TEXT("BoxHalf"), WeatherColour(BoxHalfM * WeatherCmPerMetre));
	RainMaterial->SetScalarParameterValue(TEXT("Weight"), static_cast<float>(Weight * RainGain));
	RainMesh->SetMaterial(0, RainMaterial);
	RainMesh->RegisterComponent();
	return true;
}

bool FFlightSimWeather::BuildSplashMesh(UWorld* World, FString& Error)
{
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherSplashMaterialPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.rain_material: %s did not load"), WeatherSplashMaterialPath);
		return false;
	}
	TArray<FVector> Vertices;
	TArray<int32> Triangles;
	TArray<FVector2D> UV0, UV1;
	const FVector2D Corners[4] = {FVector2D(0.0, 0.0), FVector2D(1.0, 0.0), FVector2D(0.0, 1.0),
	                              FVector2D(1.0, 1.0)};
	const double Half = SplashHalfSideM * WeatherCmPerMetre;
	for (int32 Slot = 0; Slot < SplashSlots; ++Slot)
	{
		// The vertices' own places only set the bounds (the material places
		// every crown): spread over the square and the box's height.
		const FVector Where((2.0 * Unit(RainSeed + 1, static_cast<uint64>(Slot), 0) - 1.0) * Half,
		                    (2.0 * Unit(RainSeed + 1, static_cast<uint64>(Slot), 1) - 1.0) * Half,
		                    (Slot % 2 == 0 ? -1.0 : 1.0) * BoxHalfM.Z * WeatherCmPerMetre);
		const FVector2D SlotUV(static_cast<double>(Slot % 64), static_cast<double>(Slot / 64));
		const int32 Base = Vertices.Num();
		for (const FVector2D& Corner : Corners)
		{
			Vertices.Add(Where);
			UV0.Add(Corner);
			UV1.Add(SlotUV);
		}
		Triangles.Append({Base, Base + 2, Base + 1, Base + 1, Base + 2, Base + 3});
	}
	SplashMesh = NewObject<UProceduralMeshComponent>(RainActor, TEXT("RainSplash"));
	SplashMesh->SetupAttachment(RainActor->GetRootComponent());
	SplashMesh->SetMobility(EComponentMobility::Movable);
	SplashMesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, UV0, UV1, {}, {}, {}, {},
	                                          false /* no collision */);
	SplashMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SplashMesh->SetCastShadow(false);
	SplashMesh->SetBoundsScale(1.5f);
	SplashMaterial = UMaterialInstanceDynamic::Create(Material, RainActor);
	SplashMaterial->SetVectorParameterValue(TEXT("Splash"),
		FLinearColor(static_cast<float>(SplashPeriodS), static_cast<float>(SplashLifetimeS),
		             static_cast<float>(Half), static_cast<float>(SplashSlots)));
	SplashMaterial->SetScalarParameterValue(TEXT("Weight"), static_cast<float>(SplashWeight * RainGain));
	SplashMaterial->SetScalarParameterValue(TEXT("DropMm"), static_cast<float>(D0Mm));
	SplashMesh->SetMaterial(0, SplashMaterial);
	SplashMesh->RegisterComponent();
	if (RainActor->GetRootComponent() == nullptr)
	{
		RainActor->SetRootComponent(SplashMesh);
	}
	return true;
}

bool FFlightSimWeather::BuildNiagaraRain(UWorld* World, const FFlightSimWeatherOptions& Options,
                                         FString& Error)
{
	UNiagaraSystem* System = LoadObject<UNiagaraSystem>(nullptr, WeatherNiagaraRainPath);
	if (System == nullptr)
	{
		Error = FString::Printf(
			TEXT("weather.niagara_asset: -weather-backend=niagara needs %s, built by hand from the ")
			TEXT("recipe in docs/WEATHER.md; it did not load (the procedural backend needs no asset)"),
			WeatherNiagaraRainPath);
		return false;
	}
	NiagaraRain = UNiagaraFunctionLibrary::SpawnSystemAtLocation(
		World, System, FVector::ZeroVector, FRotator::ZeroRotator, FVector(1.0),
		/*bAutoDestroy=*/false, /*bAutoActivate=*/true, ENCPoolMethod::None, /*bPreCullCheck=*/false);
	if (NiagaraRain == nullptr)
	{
		Error = TEXT("weather.niagara_asset: the rain system did not spawn");
		return false;
	}
	NiagaraRain->SetRandomSeedOffset(static_cast<int32>(RainSeed & 0x7FFFFFFF));
	// The numbers the system is built against (docs/WEATHER.md): set once
	// here, the per-frame ones in Advance.
	NiagaraRain->SetVariableVec3(TEXT("User.BoxHalfCm"), BoxHalfM * WeatherCmPerMetre);
	NiagaraRain->SetVariableFloat(TEXT("User.Lambda"), static_cast<float>(RainLambda));
	NiagaraRain->SetVariableFloat(TEXT("User.DMinMm"), static_cast<float>(RainDMinMm));
	NiagaraRain->SetVariableFloat(TEXT("User.DMaxMm"), static_cast<float>(RainDMaxMm));
	NiagaraRain->SetVariableFloat(TEXT("User.FallSpeedFactor"), static_cast<float>(FallSpeedFactor));
	NiagaraRain->SetVariableFloat(TEXT("User.Weight"), static_cast<float>(Weight));
	NiagaraRain->SetVariableInt(TEXT("User.Particles"), Particles);
	if (AActor* Owner = NiagaraRain->GetOwner())
	{
		BeautyOnlyActors.Add(Owner);
	}
	return true;
}

bool FFlightSimWeather::BuildCell(UWorld* World, const TSharedPtr<FJsonObject>& Cell,
                                  const FFlightSimWeatherOptions& Options, FString& Error)
{
	double Top = 0.0, Over = 0.0, Tower = 0.0, AnvilR = 0.0, AnvilBottom = 0.0, Updraft = 0.0;
	double SigmaCore = 0.0, SigmaAnvil = 0.0, Albedo = 0.0, Glow = 0.0;
	double ShaftSigma = 0.0, Seed = 0.0, Billow = 0.0, Erosion = 0.0;
	TArray<double> Offset, Drift;
	const TSharedPtr<FJsonObject>* Shaft = nullptr;
	const TSharedPtr<FJsonObject>* Noise = nullptr;
	if (!WeatherNumber(Cell, TEXT("base_m"), BaseM, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("top_m"), Top, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("overshoot_m"), Over, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("tower_radius_m"), Tower, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("anvil_radius_m"), AnvilR, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("anvil_bottom_m"), AnvilBottom, TEXT("weather.cell"), Error) ||
	    !WeatherVector(Cell, TEXT("anvil_offset_enu_m"), 3, Offset, TEXT("weather.cell"), Error) ||
	    !WeatherVector(Cell, TEXT("anvil_drift_enu_mps"), 2, Drift, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("updraft_mps"), Updraft, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("extinction_core_per_m"), SigmaCore, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("extinction_anvil_per_m"), SigmaAnvil, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("albedo"), Albedo, TEXT("weather.cell"), Error) ||
	    !WeatherNumber(Cell, TEXT("glow_diffusion_m"), Glow, TEXT("weather.cell"), Error) ||
	    !Cell->TryGetObjectField(TEXT("shaft"), Shaft) || Shaft == nullptr ||
	    !Cell->TryGetObjectField(TEXT("noise"), Noise) || Noise == nullptr ||
	    !WeatherNumber(*Shaft, TEXT("radius_m"), ShaftRadiusM, TEXT("weather.cell.shaft"), Error) ||
	    !WeatherNumber(*Shaft, TEXT("extinction_per_m"), ShaftSigma, TEXT("weather.cell.shaft"), Error) ||
	    !WeatherNumber(*Noise, TEXT("seed"), Seed, TEXT("weather.cell.noise"), Error) ||
	    !WeatherNumber(*Noise, TEXT("billow_m"), Billow, TEXT("weather.cell.noise"), Error) ||
	    !WeatherNumber(*Noise, TEXT("erosion"), Erosion, TEXT("weather.cell.noise"), Error))
	{
		if (Error.IsEmpty())
		{
			Error = TEXT("weather.card: weather.cell lacks its shaft or noise block");
		}
		return false;
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherStormMaterialPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.storm_material: %s (scripts/ue_create_materials.py) did ")
		                        TEXT("not load; the storm is drawn by it or not at all"),
		                        WeatherStormMaterialPath);
		return false;
	}
	// The volumetric cloud renderer asserts that its material is a Volume
	// material (VolumetricCloudRendering.cpp; measured on the owner's
	// machine: "Assertion failed: Material->GetMaterialDomain() == MD_Volume"
	// while the shaders were still compiling for the first time). A material
	// whose shader map is not ready, or failed to compile, renders as the
	// engine's default SURFACE material -- so the storm's material is
	// compiled to completion here, and one that is not a compiled Volume
	// material leaves the storm undrawn (recorded, with the compiler's
	// errors) instead of crashing the render.
	{
		UMaterial* Base = Material->GetMaterial();
		FString Why;
		if (Base == nullptr || Base->MaterialDomain != MD_Volume)
		{
			Why = TEXT("its material domain is not Volume (re-run scripts/ue_create_materials.py)");
		}
		// "Used with Volumetric Cloud": the engine compiles a material's
		// cloud shaders only under this usage flag. Without it the material
		// IS a compiled Volume material with no cloud shaders, the cloud
		// shadow mesh pass finds none, falls back to the default surface
		// material and asserts MD_Volume (VolumetricCloudRendering.cpp;
		// measured on the owner's machine, 2026-10-08). CheckMaterialUsage
		// sets it in the editor (and recompiles; FinishCompilation below
		// waits); a material that still lacks it is refused, never drawn.
		else if (!Base->GetUsageByFlag(MATUSAGE_VolumetricCloud) &&
		         (!Base->CheckMaterialUsage(MATUSAGE_VolumetricCloud) ||
		          !Base->GetUsageByFlag(MATUSAGE_VolumetricCloud)))
		{
			Why = TEXT("it is not flagged 'Used with Volumetric Cloud' (no cloud shaders; the engine ")
			      TEXT("asserts on it): re-run scripts/ue_create_materials.py, which sets the flag");
		}
		// UE 5.7 keys material resources by shader platform (measured: the
		// feature-level overload is gone); 5.5 keys them by feature level
		// (see FLIGHTSIM_GET_MATERIAL_RESOURCE above).
		else if (FMaterialResource* Resource = FLIGHTSIM_GET_MATERIAL_RESOURCE(
		             Base, World, GShaderPlatformForFeatureLevel[World->GetFeatureLevel()]))
		{
			Resource->FinishCompilation();
			if (Resource->GetCompileErrors().Num() > 0)
			{
				Why = TEXT("its shaders failed to compile: ")
					+ FString::Join(Resource->GetCompileErrors(), TEXT(" | "));
			}
			else if (Resource->GetGameThreadShaderMap() == nullptr)
			{
				Why = TEXT("its shader map is not ready after compiling");
			}
		}
		else
		{
			Why = TEXT("it has no material resource at this feature level");
		}
		if (!Why.IsEmpty())
		{
			UE_LOG(LogFlightSimWeather, Error, TEXT("weather.storm_material: %s not drawn: %s"),
			       WeatherStormMaterialPath, *Why);
			TSharedPtr<FJsonObject> Skipped = WeatherRecord();
			Skipped->SetBoolField(TEXT("drawn"), false);
			Skipped->SetStringField(TEXT("why"),
				FString::Printf(TEXT("%s: %s"), WeatherStormMaterialPath, *Why));
			Record->SetObjectField(TEXT("cell"), Skipped);
			return true;   // the rain and the rest still draw; bCell stays false
		}
	}
	TSharedPtr<FJsonObject> Row = WeatherRecord();
	StormClouds = Options.ExistingClouds;
	if (StormClouds != nullptr)
	{
		Row->SetStringField(TEXT("component"),
			TEXT("the look's UVolumetricCloudComponent, taken over (one component draws one cloud "
			     "field); the look's layer drawn by M_StormCell's Layer term"));
	}
	else
	{
		AActor* CloudActor = World->SpawnActor<AActor>();
		StormClouds = NewObject<UVolumetricCloudComponent>(CloudActor, TEXT("StormCell"));
		CloudActor->SetRootComponent(StormClouds);
		StormClouds->SetMobility(EComponentMobility::Movable);
		Row->SetStringField(TEXT("component"), TEXT("UVolumetricCloudComponent, spawned for the storm"));
		if (Options.Sun != nullptr)
		{
			if (UDirectionalLightComponent* SunLight =
			        Cast<UDirectionalLightComponent>(Options.Sun->GetLightComponent()))
			{
				SunLight->bCastCloudShadows = true;
				SunLight->CloudShadowStrength = 1.0f;
				SunLight->MarkRenderStateDirty();
			}
		}
	}
	// The layer from the ground (the shaft) to the overshooting top.
	StormClouds->SetLayerBottomAltitude(0.0f);
	StormClouds->SetLayerHeight(static_cast<float>((Top + Over + 500.0) / 1000.0));
	StormMaterial = UMaterialInstanceDynamic::Create(Material, StormClouds);
	StormMaterial->SetVectorParameterValue(TEXT("CellCentreCm"), WeatherColour(CentreEngineCm));
	StormMaterial->SetVectorParameterValue(TEXT("EastAxis"), WeatherColour(EastAxis));
	StormMaterial->SetVectorParameterValue(TEXT("NorthAxis"), WeatherColour(NorthAxis));
	StormMaterial->SetVectorParameterValue(TEXT("Geo1"),
		FLinearColor(static_cast<float>(BaseM), static_cast<float>(Top), static_cast<float>(Over),
		             static_cast<float>(Tower)));
	StormMaterial->SetVectorParameterValue(TEXT("Geo2"),
		FLinearColor(static_cast<float>(AnvilR), static_cast<float>(AnvilBottom),
		             static_cast<float>(Offset[0]), static_cast<float>(Offset[1])));
	StormMaterial->SetVectorParameterValue(TEXT("Sigma"),
		FLinearColor(static_cast<float>(SigmaCore), static_cast<float>(SigmaAnvil),
		             static_cast<float>(ShaftSigma), static_cast<float>(ShaftRadiusM)));
	StormMaterial->SetVectorParameterValue(TEXT("Noise"),
		FLinearColor(static_cast<float>(Seed), static_cast<float>(Billow), static_cast<float>(Erosion),
		             static_cast<float>(Updraft)));
	// Kept for the beauty's ragged edges (ApplyBeautyStormVantage); "Ragged"
	// stays at the material's default 0 here, so this draw is the measure one.
	NoiseDrawn = FLinearColor(static_cast<float>(Seed), static_cast<float>(Billow), static_cast<float>(Erosion),
	                          static_cast<float>(Updraft));
	StormMaterial->SetVectorParameterValue(TEXT("Drift"),
		FLinearColor(static_cast<float>(Drift[0]), static_cast<float>(Drift[1]), 0.0f, 0.0f));
	// The look's layer inside the storm's material (0 cover: none). Its depth
	// is capped: the storm look states a deck from 1200 m to 9000 m, which at
	// a stratiform deck's extinction is 156 optical depths of water -- no
	// light leaves it, and the owner's first storm frame (2026-10-08) was
	// black. It is drawn as a nimbostratus LayerDepthMaxM deep from its base
	// (a real deck's order; optical depth 30: dark grey, not black). The
	// look's top is where its clear sky starts, recorded beside what is drawn.
	constexpr double LayerExtinctionPerM = 0.02;   // stated: a stratiform deck's order
	constexpr double LayerDepthMaxM = 1500.0;      // stated: a nimbostratus deck's order
	const double LayerTopDrawnM =
		FMath::Min(Options.LayerTopMetres, Options.LayerBaseMetres + LayerDepthMaxM);
	StormMaterial->SetVectorParameterValue(TEXT("Layer"),
		FLinearColor(static_cast<float>(Options.LayerCover), static_cast<float>(Options.LayerBaseMetres),
		             static_cast<float>(LayerTopDrawnM), static_cast<float>(LayerExtinctionPerM)));
	// Kept for the beauty vantage (ApplyBeautyStormVantage); nothing else reads them.
	CellTopM = Top;
	CellOvershootM = Over;
	CellTowerRadiusM = Tower;
	LayerCoverDrawn = Options.LayerCover;
	LayerBaseDrawnMetres = Options.LayerBaseMetres;
	LayerTopDrawnMetres = LayerTopDrawnM;
	LayerExtinctionDrawn = LayerExtinctionPerM;
	GlowDiffusionM = Glow;
	CellAlbedo = Albedo;
	StormMaterial->SetVectorParameterValue(TEXT("Flash"),
		FLinearColor(0.0f, static_cast<float>(Glow), static_cast<float>(Albedo), 0.0f));
	StormMaterial->SetScalarParameterValue(TEXT("Albedo"), static_cast<float>(Albedo));
	StormMaterial->SetScalarParameterValue(TEXT("ExtinctionScale"), 1.0f);
	StormMaterial->SetScalarParameterValue(TEXT("Time"), 0.0f);
	StormClouds->SetMaterial(StormMaterial);
	if (!StormClouds->IsRegistered())
	{
		StormClouds->RegisterComponent();
	}
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("material"), WeatherStormMaterialPath);
	Row->SetNumberField(TEXT("base_m"), BaseM);
	Row->SetNumberField(TEXT("top_m"), Top);
	Row->SetNumberField(TEXT("tower_radius_m"), Tower);
	Row->SetNumberField(TEXT("anvil_radius_m"), AnvilR);
	Row->SetNumberField(TEXT("extinction_core_per_m"), SigmaCore);
	Row->SetNumberField(TEXT("shaft_extinction_per_m"), ShaftSigma);
	Row->SetNumberField(TEXT("layer_bottom_altitude_km"), 0.0);
	Row->SetNumberField(TEXT("layer_height_km"), (Top + Over + 500.0) / 1000.0);
	Row->SetNumberField(TEXT("look_layer_cover"), Options.LayerCover);
	Row->SetNumberField(TEXT("look_layer_base_m"), Options.LayerBaseMetres);
	Row->SetNumberField(TEXT("look_layer_top_m"), Options.LayerTopMetres);
	Row->SetNumberField(TEXT("look_layer_top_drawn_m"), LayerTopDrawnM);
	Row->SetNumberField(TEXT("look_layer_extinction_per_m"), LayerExtinctionPerM);
	Row->SetStringField(TEXT("look_layer_depth"),
		FString::Printf(TEXT("drawn at most %.0f m deep from its base (a nimbostratus deck's order, ")
		                TEXT("optical depth %.0f): the look's full depth would let no light through"),
		                LayerDepthMaxM, LayerDepthMaxM * LayerExtinctionPerM));
	Row->SetStringField(TEXT("lighting"),
		TEXT("the material's VolumetricAdvancedMaterialOutput (scripts/ue_create_materials.py ")
		TEXT("STORM_SCATTERING): dual-lobe Henyey-Greenstein, two multiple-scattering octaves, ")
		TEXT("the ground's albedo on the bottoms; the exposure under the cell is metered again ")
		TEXT("(look_applied.storm_exposure)"));
	Row->SetStringField(TEXT("extinction_unit"),
		TEXT("the shader's 1/m into the Extinction output at ExtinctionScale 1: whether the engine ")
		TEXT("reads it per metre is WX.4's measurement"));
	Record->SetObjectField(TEXT("cell"), Row);
	bCell = true;
	return true;
}

bool FFlightSimWeather::BuildLightning(UWorld* World, const TSharedPtr<FJsonObject>& Lightning,
                                       FString& Error)
{
	const TSharedPtr<FJsonObject>* CurveJson = nullptr;
	if (!Lightning->TryGetObjectField(TEXT("light_curve"), CurveJson) || CurveJson == nullptr ||
	    !WeatherNumber(*CurveJson, TEXT("rise_s"), Curve.RiseS, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("fall_s"), Curve.FallS, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("peak_norm"), Curve.PeakNorm, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("glow_fraction"), Curve.GlowFraction, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("glow_s"), Curve.GlowS, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("leader_w_per_m"), Curve.LeaderWPerM, TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("branch_stroke_share"), Curve.BranchStrokeShare,
	                   TEXT("light_curve"), Error) ||
	    !WeatherNumber(*CurveJson, TEXT("luminous_efficacy_lm_per_w"), Curve.EfficacyLmPerW,
	                   TEXT("light_curve"), Error))
	{
		if (Error.IsEmpty())
		{
			Error = TEXT("weather.card: weather.lightning lacks its light_curve");
		}
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* FlashList = nullptr;
	if (!Lightning->TryGetArrayField(TEXT("flashes"), FlashList) || FlashList == nullptr)
	{
		Error = TEXT("weather.card: weather.lightning lacks its flashes");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *FlashList)
	{
		FFlightSimFlash Flash;
		if (!ParseFlash(Value->AsObject(), Flash, Error))
		{
			return false;
		}
		Flashes.Add(MoveTemp(Flash));
	}
	// The selftest: window_power and the intensity at the card's exposures.
	const TArray<TSharedPtr<FJsonValue>>* Selftest = nullptr;
	if (Lightning->TryGetArrayField(TEXT("selftest"), Selftest) && Selftest != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Selftest)
		{
			const TSharedPtr<FJsonObject> Entry = Value->AsObject();
			double FlashIndex = 0.0, A = 0.0, B = 0.0, Main = 0.0, Branch = 0.0, Progress = 0.0, Cd = 0.0;
			if (!WeatherNumber(Entry, TEXT("flash"), FlashIndex, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("a_s"), A, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("b_s"), B, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("main_w_per_m"), Main, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("branch_w_per_m"), Branch, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("leader_progress"), Progress, TEXT("lightning.selftest"), Error) ||
			    !WeatherNumber(Entry, TEXT("intensity_cd"), Cd, TEXT("lightning.selftest"), Error))
			{
				return false;
			}
			const FFlightSimFlash* Flash = Flashes.FindByPredicate(
				[&](const FFlightSimFlash& F) { return F.Index == static_cast<int32>(FlashIndex); });
			if (Flash == nullptr)
			{
				Error = TEXT("weather.selftest: the lightning selftest names a flash the card lacks");
				return false;
			}
			const FFlightSimFlashPower Power = WindowPower(Curve, *Flash, A, B);
			if (!WeatherClose(Power.MainWPerM, Main) || !WeatherClose(Power.BranchWPerM, Branch) ||
			    !WeatherClose(Power.LeaderProgress, Progress) ||
			    !WeatherClose(IntensityCd(Curve, *Flash, Power), Cd))
			{
				Error = FString::Printf(
					TEXT("weather.selftest: flash %d over [%.6f, %.6f] s gives %.9g W/m here, the card ")
					TEXT("%.9g; the port of lightning.py window_power disagrees"),
					Flash->Index, A, B, Power.MainWPerM, Main);
				return false;
			}
		}
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherLightningMaterialPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.lightning_material: %s did not load"),
		                        WeatherLightningMaterialPath);
		return false;
	}
	LightningActor = World->SpawnActor<AActor>();
	LightningActor->Tags.Add(FName(TEXT("FlightSim.weather")));
	BeautyOnlyActors.Add(LightningActor);
	USceneComponent* Root = NewObject<USceneComponent>(LightningActor, TEXT("LightningRoot"));
	LightningActor->SetRootComponent(Root);
	Root->SetMobility(EComponentMobility::Movable);
	Root->RegisterComponent();
	int32 Drawn = 0;
	for (const FFlightSimFlash& Flash : Flashes)
	{
		// One ribbon mesh per flash, every channel of it, the part above the
		// cloud base left to the glow. Vertices relative to the flash's
		// centroid (small numbers); UV0 (side, arc), UV1 (kind, 0); the
		// normal is the channel's direction there.
		TArray<FVector> Vertices, Normals;
		TArray<int32> Triangles;
		TArray<FVector2D> UV0, UV1;
		const FVector Anchor = EnuToEngineCm(Flash.CentroidEnu);
		for (const FFlightSimChannel& Channel : Flash.Channels)
		{
			const int32 Count = Channel.PointsEnu.Num();
			if (Count < 2 || !Flash.bCloudToGround)
			{
				continue;   // an intra-cloud channel is drawn as the cloud's glow only
			}
			double Total = 0.0;
			for (int32 I = 0; I + 1 < Count; ++I)
			{
				Total += FVector::Distance(Channel.PointsEnu[I], Channel.PointsEnu[I + 1]);
			}
			double Run = 0.0;
			int32 Previous = INDEX_NONE;
			for (int32 I = 0; I < Count; ++I)
			{
				if (I > 0)
				{
					Run += FVector::Distance(Channel.PointsEnu[I - 1], Channel.PointsEnu[I]);
				}
				const FVector& P = Channel.PointsEnu[I];
				if (P.Z > BaseM + WeatherChannelAboveBaseM)
				{
					Previous = INDEX_NONE;
					continue;
				}
				const FVector Ahead = Channel.PointsEnu[FMath::Min(I + 1, Count - 1)];
				const FVector Behind = Channel.PointsEnu[FMath::Max(I - 1, 0)];
				const FVector Dir = EnuVectorToEngine(Ahead - Behind).GetSafeNormal();
				const FVector Where = EnuToEngineCm(P) - Anchor;
				const double Arc = Total > 0.0 ? Run / Total : 0.0;
				const int32 Base = Vertices.Num();
				for (const double Side : {-1.0, 1.0})
				{
					Vertices.Add(Where);
					Normals.Add(Dir);
					UV0.Add(FVector2D(Side, Arc));
					UV1.Add(FVector2D(Channel.bBranch ? 1.0 : 0.0, 0.0));
				}
				if (Previous != INDEX_NONE)
				{
					Triangles.Append({Previous, Base, Previous + 1, Previous + 1, Base, Base + 1});
				}
				Previous = Base;
			}
		}
		UProceduralMeshComponent* Mesh = nullptr;
		UMaterialInstanceDynamic* Instance = nullptr;
		if (Triangles.Num() > 0)
		{
			Mesh = NewObject<UProceduralMeshComponent>(LightningActor,
				*FString::Printf(TEXT("Flash%03d"), Flash.Index));
			Mesh->SetupAttachment(Root);
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, UV1, {}, {}, {}, {},
			                                    false /* no collision */);
			Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Mesh->SetCastShadow(false);
			Mesh->SetBoundsScale(1.5f);
			Instance = UMaterialInstanceDynamic::Create(Material, LightningActor);
			Instance->SetScalarParameterValue(TEXT("RadiusCm"), static_cast<float>(WeatherChannelRadiusCm));
			Mesh->SetMaterial(0, Instance);
			Mesh->SetWorldLocation(Anchor);
			Mesh->SetVisibility(false);
			Mesh->RegisterComponent();
			++Drawn;
		}
		FlashMeshes.Add(Mesh);
		FlashMaterials.Add(Instance);
	}
	// The flash's light on the scene: one point source at the brightest
	// active flash's centroid, in candela (lightning.py intensity_cd).
	FlashLight = NewObject<UPointLightComponent>(LightningActor, TEXT("FlashLight"));
	FlashLight->SetupAttachment(Root);
	FlashLight->SetMobility(EComponentMobility::Movable);
	FlashLight->SetIntensityUnits(ELightUnits::Candelas);
	FlashLight->SetIntensity(0.0f);
	FlashLight->SetAttenuationRadius(static_cast<float>(WeatherFlashLightRadiusCm));
	FlashLight->SetLightColor(FLinearColor(0.86f / 0.913f, 0.92f / 0.913f, 1.0f / 0.913f));
	// Scene #09 stability: unshadowed unless -lightning-shadows=on (the
	// cube shadow pass lost the iGPU; the light is under 1 % of the scene's).
	FlashLight->SetCastShadows(bFlashShadows);
	FlashLight->SetVisibility(false);
	FlashLight->RegisterComponent();

	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetNumberField(TEXT("flashes"), Flashes.Num());
	Row->SetNumberField(TEXT("channel_meshes"), Drawn);
	Row->SetStringField(TEXT("material"), WeatherLightningMaterialPath);
	Row->SetNumberField(TEXT("selftest_windows"), Selftest != nullptr ? Selftest->Num() : 0);
	Row->SetStringField(TEXT("flash_light"), bFlashShadows
		? TEXT("shadowed (-lightning-shadows=on)")
		: TEXT("unshadowed (the default; -lightning-shadows=on is the shadowed light)"));
	Row->SetStringField(TEXT("exposure"),
		TEXT("each frame draws the flash's mean power over its own exposure (window_power): a ")
		TEXT("shutter that misses a stroke shows no bolt"));
	Record->SetObjectField(TEXT("lightning"), Row);
	bLightning = true;
	return true;
}

bool FFlightSimWeather::ReadThunder(const TSharedPtr<FJsonObject>& Json, FString& Error)
{
	double Rate = 0.0;
	if (!WeatherNumber(Json, TEXT("sound_speed_mps"), Thunder.SoundSpeedMps, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("relaxation_radius_m"), Thunder.RelaxationRadiusM, TEXT("weather.thunder"),
	                   Error) ||
	    !WeatherNumber(Json, TEXT("t0_s"), Thunder.T0S, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("lengthening"), Thunder.Lengthening, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("directivity_floor"), Thunder.DirectivityFloor, TEXT("weather.thunder"),
	                   Error) ||
	    !WeatherNumber(Json, TEXT("pressure_ref_pa_m"), Thunder.PressureRefPaM, TEXT("weather.thunder"),
	                   Error) ||
	    !WeatherNumber(Json, TEXT("absorption_f0_hz"), Thunder.AbsorptionF0Hz, TEXT("weather.thunder"),
	                   Error) ||
	    !WeatherNumber(Json, TEXT("absorption_r_m"), Thunder.AbsorptionRM, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("audible_full_m"), Thunder.AudibleFullM, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("audible_max_m"), Thunder.AudibleMaxM, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("full_scale_pa"), Thunder.FullScalePa, TEXT("weather.thunder"), Error) ||
	    !WeatherNumber(Json, TEXT("sample_rate_hz"), Rate, TEXT("weather.thunder"), Error))
	{
		return false;
	}
	Thunder.SampleRateHz = static_cast<int32>(Rate);
	// The selftest: the fixed flash at the reduced rate, sample for sample.
	const TSharedPtr<FJsonObject>* Selftest = nullptr;
	if (!Json->TryGetObjectField(TEXT("selftest"), Selftest) || Selftest == nullptr)
	{
		Error = TEXT("weather.selftest: weather.thunder carries no selftest");
		return false;
	}
	const TSharedPtr<FJsonObject>* FlashJson = nullptr;
	TArray<double> Listener;
	double SelftestRate = 0.0, Length = 0.0;
	FFlightSimFlash Flash;
	if (!(*Selftest)->TryGetObjectField(TEXT("flash"), FlashJson) || FlashJson == nullptr ||
	    !ParseFlash(*FlashJson, Flash, Error) ||
	    !WeatherVector(*Selftest, TEXT("listener_enu_m"), 3, Listener, TEXT("thunder.selftest"), Error) ||
	    !WeatherNumber(*Selftest, TEXT("sample_rate_hz"), SelftestRate, TEXT("thunder.selftest"), Error) ||
	    !WeatherNumber(*Selftest, TEXT("length"), Length, TEXT("thunder.selftest"), Error))
	{
		if (Error.IsEmpty())
		{
			Error = TEXT("weather.selftest: weather.thunder.selftest lacks its flash");
		}
		return false;
	}
	TArray<double> Samples;
	SynthesiseThunder(Thunder, Flash, FVector(Listener[0], Listener[1], Listener[2]),
	                  static_cast<int32>(SelftestRate), Samples);
	const TArray<TSharedPtr<FJsonValue>>* Picks = nullptr;
	if (Samples.Num() != static_cast<int32>(Length) ||
	    !(*Selftest)->TryGetArrayField(TEXT("samples"), Picks) || Picks == nullptr)
	{
		Error = FString::Printf(TEXT("weather.selftest: the thunder selftest is %d samples here, %d on ")
		                        TEXT("the card"), Samples.Num(), static_cast<int32>(Length));
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Pick : *Picks)
	{
		const TArray<TSharedPtr<FJsonValue>>& Pair = Pick->AsArray();
		const int32 Index = Pair.Num() == 2 ? static_cast<int32>(Pair[0]->AsNumber()) : -1;
		if (!Samples.IsValidIndex(Index) || !WeatherClose(Samples[Index], Pair[1]->AsNumber()))
		{
			Error = FString::Printf(TEXT("weather.selftest: thunder sample %d is %.12g Pa here, the card's ")
			                        TEXT("%.12g; the port of thunder.py synthesise disagrees"),
			                        Index, Samples.IsValidIndex(Index) ? Samples[Index] : 0.0,
			                        Pair.Num() == 2 ? Pair[1]->AsNumber() : 0.0);
			return false;
		}
	}
	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetBoolField(TEXT("played"), bAudio);
	Row->SetNumberField(TEXT("sound_speed_mps"), Thunder.SoundSpeedMps);
	Row->SetNumberField(TEXT("selftest_samples"), Picks->Num());
	Row->SetStringField(TEXT("note"), bAudio ? TEXT("synthesised per flash at the camera when it strikes")
	                                         : TEXT("the render records no audio (scripts/storm_soundtrack.py)"));
	Record->SetObjectField(TEXT("thunder"), Row);
	bThunder = true;
	return true;
}

void FFlightSimWeather::StartRainNoise()
{
	if (!bAudio || WorldRef == nullptr || !bRain)
	{
		return;
	}
	// The rain's hiss, generated on the audio thread at the level Advance sets.
	RainNoise = MakeShared<FFlightSimRainNoise, ESPMode::ThreadSafe>();
	RainNoise->Random.Initialize(static_cast<int32>(RainSeed & 0x7FFFFFFF));
	RainNoise->FullScalePa = Thunder.FullScalePa;
	const double Fs = static_cast<double>(Thunder.SampleRateHz);
	RainNoise->HighPassAlpha = 1.0 - FMath::Exp(-2.0 * WeatherPi * WeatherRainBandLowHz / Fs);
	RainNoise->LowPassAlpha = 1.0 - FMath::Exp(-2.0 * WeatherPi * WeatherRainBandHighHz / Fs);
	double Sum = 0.0;
	const int32 Probe = Thunder.SampleRateHz;
	for (int32 I = 0; I < Probe; ++I)
	{
		const double V = RainNoise->Next();
		Sum += V * V;
	}
	RainNoise->UnitRms = FMath::Max(1.0e-9, FMath::Sqrt(Sum / Probe));
	USoundWaveProcedural* Wave = NewObject<USoundWaveProcedural>();
	Wave->SetSampleRate(Thunder.SampleRateHz);
	Wave->NumChannels = 1;
	Wave->Duration = INDEFINITELY_LOOPING_DURATION;
	Wave->SoundGroup = SOUNDGROUP_Default;
	Wave->bLooping = false;
	TWeakPtr<FFlightSimRainNoise, ESPMode::ThreadSafe> Weak = RainNoise;
	Wave->OnSoundWaveProceduralUnderflow = FOnSoundWaveProceduralUnderflow::CreateLambda(
		[Weak](USoundWaveProcedural* InWave, int32 SamplesRequired)
		{
			TSharedPtr<FFlightSimRainNoise, ESPMode::ThreadSafe> Noise = Weak.Pin();
			if (!Noise.IsValid())
			{
				return;
			}
			TArray<int16> Pcm;
			Pcm.SetNumUninitialized(SamplesRequired);
			const double Gain = Noise->RmsPa.load() / Noise->UnitRms / Noise->FullScalePa * 32767.0;
			for (int32 I = 0; I < SamplesRequired; ++I)
			{
				Pcm[I] = static_cast<int16>(FMath::Clamp(Noise->Next() * Gain, -32768.0, 32767.0));
			}
			InWave->QueueAudio(reinterpret_cast<const uint8*>(Pcm.GetData()), Pcm.Num() * sizeof(int16));
		});
	RainVoice = UGameplayStatics::SpawnSound2D(WorldRef, Wave, 1.0f, 1.0f, 0.0f, nullptr, false, false);
}

// -- per frame ---------------------------------------------------------------------

void FFlightSimWeather::PlayThunder(UWorld* World, const FFlightSimFlash& Flash,
                                    const FVector& ListenerEnu, double NowSeconds)
{
	TArray<double> Samples;
	if (SynthesiseThunder(Thunder, Flash, ListenerEnu, Thunder.SampleRateHz, Samples) < 0.0)
	{
		return;   // out of earshot
	}
	// The clip's sample 0 is the flash's instant; this frame is a little past it.
	const int32 Skip = FMath::Clamp(
		static_cast<int32>((NowSeconds - Flash.TimeS) * Thunder.SampleRateHz), 0, Samples.Num());
	TArray<int16> Pcm;
	Pcm.SetNumUninitialized(Samples.Num() - Skip);
	for (int32 I = Skip; I < Samples.Num(); ++I)
	{
		Pcm[I - Skip] = static_cast<int16>(FMath::Clamp(
			FMath::RoundToDouble(Samples[I] / Thunder.FullScalePa * 32767.0), -32768.0, 32767.0));
	}
	USoundWaveProcedural* Wave = NewObject<USoundWaveProcedural>();
	Wave->SetSampleRate(Thunder.SampleRateHz);
	Wave->NumChannels = 1;
	Wave->Duration = static_cast<float>(Pcm.Num()) / Thunder.SampleRateHz;
	Wave->SoundGroup = SOUNDGROUP_Default;
	Wave->bLooping = false;
	Wave->QueueAudio(reinterpret_cast<const uint8*>(Pcm.GetData()), Pcm.Num() * sizeof(int16));
	if (UAudioComponent* Voice = UGameplayStatics::SpawnSound2D(World, Wave))
	{
		ThunderVoices.Add(Voice);
	}
}

void FFlightSimWeather::Advance(const FFlightSimWeatherView& View)
{
	if (!bBuilt)
	{
		return;
	}
	const double T = View.TimeSeconds;
	const double Dt = PreviousTimeS >= 0.0 ? T - PreviousTimeS : 0.0;
	const FVector CameraEnu = EngineToEnu(View.CameraCm);
	const FVector Wind = WindEngineCmPerS(CameraEnu);
	// The camera's velocity for the streaks: the warm-up's step from the
	// settle position to the first solved pose is not a motion (measured:
	// metre-long streaks on frame 0 alone, 2026-10-09), so a step faster
	// than any aircraft (WeatherMaxCameraMps) keeps the previous velocity;
	// the cinematic style leaves the camera's motion out altogether.
	FVector CameraVelocity = Dt > 0.0 ? (View.CameraCm - PreviousCameraCm) / Dt : FVector::ZeroVector;
	constexpr double WeatherMaxCameraMps = 400.0;
	if (CameraVelocity.Size() > WeatherMaxCameraMps * WeatherCmPerMetre)
	{
		CameraVelocity = PreviousCameraVelocity;
	}
	PreviousCameraVelocity = CameraVelocity;
	if (bCinematicRain)
	{
		// BeautyCameraShare is 0 but on the beauty path (rain_veil.BEAUTY_CAMERA_MOTION_SHARE).
		CameraVelocity = CameraVelocity * BeautyCameraShare;
	}
	if (Dt > 0.0)
	{
		AirDisplacementCm += Wind * Dt;
	}
	PreviousTimeS = T;
	PreviousCameraCm = View.CameraCm;
	const double PixelAngle = 2.0 * FMath::Tan(FMath::DegreesToRadians(View.HorizontalFovDeg) * 0.5)
		/ FMath::Max(1, View.WidthPx);
	// The cinematic style's exposure: 1/15 s, the long exposure film shows
	// rain with (stated); the physical style's is the view's.
	constexpr double WeatherCinematicShutterS = 1.0 / 15.0;
	const double Shutter = bCinematicRain ? WeatherCinematicShutterS : FMath::Max(View.ShutterSeconds, 1.0e-5);

	// -- lightning: the flashes this exposure integrates ----------------------
	double FlashLux = 0.0;
	if (bLightning)
	{
		double BestCd = 0.0;
		const FFlightSimFlash* Best = nullptr;
		for (int32 I = 0; I < Flashes.Num(); ++I)
		{
			const FFlightSimFlash& Flash = Flashes[I];
			const FFlightSimFlashPower Power = WindowPower(Curve, Flash, T - Shutter, T);
			const bool bLit = Power.MainWPerM > 0.0;
			if (FlashMeshes[I] != nullptr)
			{
				FlashMeshes[I]->SetVisibility(bLit);
				if (bLit)
				{
					FlashMaterials[I]->SetVectorParameterValue(TEXT("Power"), FLinearColor(
						static_cast<float>(Curve.EfficacyLmPerW * Power.MainWPerM),
						static_cast<float>(Curve.EfficacyLmPerW * Power.BranchWPerM),
						static_cast<float>(Power.LeaderProgress), 0.0f));
					FlashMaterials[I]->SetScalarParameterValue(TEXT("PixelAngle"),
					                                           static_cast<float>(PixelAngle));
				}
			}
			if (bLit)
			{
				const double Cd = IntensityCd(Curve, Flash, Power);
				// The flash where it is DRAWN (BeautyCellOffsetCm: zero but on the beauty vantage).
				const double DistanceM = FMath::Max(
					1.0, FVector::Distance(View.CameraCm, EnuToEngineCm(Flash.CentroidEnu) + BeautyCellOffsetCm)
						/ WeatherCmPerMetre);
				FlashLux += Cd / (DistanceM * DistanceM);
				if (Cd > BestCd)
				{
					BestCd = Cd;
					Best = &Flash;
				}
			}
			if (bThunder && bAudio && WorldRef != nullptr && T >= Flash.TimeS &&
			    !ThunderStarted.Contains(Flash.Index))
			{
				ThunderStarted.Add(Flash.Index);
				PlayThunder(WorldRef, Flash, CameraEnu, T);
			}
		}
		if (FlashLight != nullptr)
		{
			FlashLight->SetVisibility(Best != nullptr);
			FlashLight->SetIntensity(static_cast<float>(BestCd));
			if (Best != nullptr)
			{
				FlashLight->SetWorldLocation(EnuToEngineCm(Best->CentroidEnu) + BeautyCellOffsetCm);
			}
		}
		if (StormMaterial != nullptr)
		{
			const FVector FlashRel = Best != nullptr ? EnuToEngineCm(Best->CentroidEnu) - CentreEngineCm
			                                         : FVector::ZeroVector;
			StormMaterial->SetVectorParameterValue(TEXT("FlashRelCm"), WeatherColour(FlashRel));
			StormMaterial->SetVectorParameterValue(TEXT("Flash"), FLinearColor(
				static_cast<float>(BestCd), static_cast<float>(GlowDiffusionM),
				static_cast<float>(CellAlbedo), 0.0f));
		}
	}
	if (StormMaterial != nullptr)
	{
		StormMaterial->SetScalarParameterValue(TEXT("Time"), static_cast<float>(T));
	}
	// Visual overhaul (world lane): kept for the beauty's sky pulse and its
	// per-frame record (LastFlashLux); nothing here reads it back.
	LastFlashLuxValue = FlashLux;

	// -- rain ------------------------------------------------------------------
	if (!bRain)
	{
		return;
	}
	// BeautyRainShareFloor is 0 but on the beauty storm vantage (the deck above the aircraft rains).
	const double Share = FMath::Max(ShaftShare(CameraEnu), BeautyRainShareFloor);
	const FVector BoxHalfCm = BoxHalfM * WeatherCmPerMetre;
	const FVector Shift(WeatherWrap(AirDisplacementCm.X - View.CameraCm.X, BoxHalfCm.X),
	                    WeatherWrap(AirDisplacementCm.Y - View.CameraCm.Y, BoxHalfCm.Y),
	                    WeatherWrap(AirDisplacementCm.Z - View.CameraCm.Z, BoxHalfCm.Z));
	const double GroundRelZ = View.GroundZCm - View.CameraCm.Z;
	const bool bGroundInReach = (View.CameraCm.Z - View.GroundZCm) < SplashMaxAglM * WeatherCmPerMetre;
	if (RainActor != nullptr)
	{
		RainActor->SetActorLocation(View.CameraCm);
	}
	if (RainMaterial != nullptr)
	{
		RainMaterial->SetVectorParameterValue(TEXT("Shift"), WeatherColour(Shift));
		RainMaterial->SetScalarParameterValue(TEXT("FallTime"), static_cast<float>(T));
		RainMaterial->SetVectorParameterValue(TEXT("WindVel"), WeatherColour(Wind));
		RainMaterial->SetVectorParameterValue(TEXT("CamVel"), WeatherColour(CameraVelocity));
		RainMaterial->SetScalarParameterValue(TEXT("Shutter"), static_cast<float>(Shutter));
		RainMaterial->SetScalarParameterValue(TEXT("PixelAngle"), static_cast<float>(PixelAngle));
		RainMaterial->SetScalarParameterValue(TEXT("Active"), static_cast<float>(Share));
		RainMaterial->SetScalarParameterValue(TEXT("GroundRelZ"), static_cast<float>(GroundRelZ));
		RainMaterial->SetScalarParameterValue(TEXT("FlashLux"), static_cast<float>(FlashLux));
		if (BeautyMaxStreakRad > 0.0)
		{
			// rain_veil.streak_cap_rad: the cap at the reference pixel, scaled down with a longer lens.
			RainMaterial->SetScalarParameterValue(TEXT("MaxStreak"), static_cast<float>(
				BeautyMaxStreakRad * FMath::Min(1.0, PixelAngle / FlightSimRainVeil::BeautyReferencePixelRad)));
		}
	}
	// maxpick/rain: the baked rain layers (nothing unless -rain-layers=on put them on).
	StepRainLayers(Wind, CameraVelocity, Share, Shutter, Dt, PixelAngle);
	// Lane D: the beauty rain veil (nothing unless FFlightSimWorldBeauty built it).
	StepBeautyRainVeil(View, Wind, CameraVelocity, Share, PixelAngle);
	if (NiagaraRain != nullptr)
	{
		NiagaraRain->SetWorldLocation(View.CameraCm);
		NiagaraRain->SetVariableVec3(TEXT("User.WindVelCm"), Wind);
		NiagaraRain->SetVariableVec3(TEXT("User.CamVelCm"), CameraVelocity);
		NiagaraRain->SetVariableFloat(TEXT("User.Shutter"), static_cast<float>(Shutter));
		NiagaraRain->SetVariableFloat(TEXT("User.Active"), static_cast<float>(Share));
		NiagaraRain->SetVariableFloat(TEXT("User.GroundZCm"), static_cast<float>(View.GroundZCm));
		NiagaraRain->SetVariableFloat(TEXT("User.FlashLux"), static_cast<float>(FlashLux));
		NiagaraRain->SetVariableFloat(TEXT("User.PixelAngle"), static_cast<float>(PixelAngle));
		if (bManualNiagaraTick && Dt > 0.0)
		{
			NiagaraRain->AdvanceSimulation(1, static_cast<float>(Dt));
		}
	}
	if (SplashMaterial != nullptr)
	{
		const double HalfCm = SplashHalfSideM * WeatherCmPerMetre;
		SplashMaterial->SetScalarParameterValue(TEXT("Time"), static_cast<float>(T));
		SplashMaterial->SetVectorParameterValue(TEXT("GroundShift"), FLinearColor(
			static_cast<float>(WeatherWrap(-View.CameraCm.X, HalfCm)),
			static_cast<float>(WeatherWrap(-View.CameraCm.Y, HalfCm)), 0.0f, 0.0f));
		SplashMaterial->SetScalarParameterValue(TEXT("GroundRelZ"), static_cast<float>(GroundRelZ));
		SplashMaterial->SetScalarParameterValue(TEXT("Active"),
		                                        static_cast<float>(bGroundInReach ? Share : 0.0));
		SplashMaterial->SetScalarParameterValue(TEXT("FlashLux"), static_cast<float>(FlashLux));
	}
	if (WindshieldMaterial != nullptr)
	{
		WindshieldMaterial->SetScalarParameterValue(TEXT("Time"), static_cast<float>(T));
		// Lane D: the beauty water film (BeautyFilm is 0 unless ApplyBeautyRainVeil ran),
		// scrolled up the glass at the run-off (screen heights / s over the film's tiles).
		WindshieldMaterial->SetScalarParameterValue(TEXT("Film"), static_cast<float>(BeautyFilm));
		WindshieldMaterial->SetScalarParameterValue(TEXT("FilmV"),
			static_cast<float>(BeautyFilm > 0.0 ? WindshieldRunoffMps / WeatherGlassViewHeightM * T * 1.5 : 0.0));
	}
	// maxpick/rain: the baked glass (nothing unless -windscreen-baked=on put it on).
	StepWindscreenBaked(T, View.ShutterSeconds, View.HorizontalFovDeg);
	if (RainNoise.IsValid())
	{
		// The hiss at the rain falling HERE (the shaft's share of the drops).
		const double Level = WeatherRainSplDbAt1Mmh
			+ 10.0 * FMath::LogX(10.0, FMath::Max(RainRateMmh * Share, 1.0e-6));
		RainNoise->RmsPa.store(Share > 0.0 ? static_cast<float>(WeatherPRefSpl * FMath::Pow(10.0, Level / 20.0))
		                                   : 0.0f);
	}
}

bool FFlightSimWeather::ApplyWindshield(USceneCaptureComponent2D* Beauty, double AirspeedMps,
                                        FString& Error)
{
	if (!bRain || Beauty == nullptr)
	{
		return true;
	}
	if (bWindscreenBaked)
	{
		// maxpick/rain: -windscreen-baked=on, the baked glass in M_WindshieldRain's place.
		return ApplyWindscreenBaked(Beauty, AirspeedMps, Error);
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherWindshieldMaterialPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.windshield: %s (scripts/ue_create_materials.py) did not ")
		                        TEXT("load; a cockpit camera in the rain draws its glass or refuses"),
		                        WeatherWindshieldMaterialPath);
		return false;
	}
	// The card's glass numbers at ITS airspeed; the material's per screen
	// (the stated visible glass area and height).
	WindshieldMaterial = UMaterialInstanceDynamic::Create(Material, Beauty);
	WindshieldMaterial->SetVectorParameterValue(TEXT("Glass"), FLinearColor(
		static_cast<float>(WindshieldImpinge * WeatherGlassViewM2),
		static_cast<float>(WindshieldRunoffMps / WeatherGlassViewHeightM),
		static_cast<float>(WeatherGlassStaticLifeS), static_cast<float>(WeatherGlassCells)));
	WindshieldMaterial->SetScalarParameterValue(TEXT("Seed"), static_cast<float>(RainSeed & 0xFFFFFF));
	WindshieldMaterial->SetScalarParameterValue(TEXT("Time"), 0.0f);
	Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, WindshieldMaterial));
	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("applied_to"), TEXT("beauty"));
	Row->SetNumberField(TEXT("impinge_per_m2_s"), WindshieldImpinge);
	Row->SetNumberField(TEXT("runoff_mps"), WindshieldRunoffMps);
	Row->SetNumberField(TEXT("airspeed_mps"), AirspeedMps);
	Row->SetStringField(TEXT("basis"),
		TEXT("the card's impingement and run-off (rain_field.py windshield; the run-off law ")
		TEXT("stated, not measured) over a stated 1 m^2, 0.8 m high visible glass"));
	Record->SetObjectField(TEXT("windshield"), Row);
	return true;
}
