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
#include "Kismet/GameplayStatics.h"
#include "MaterialDomain.h"
#include "MaterialShared.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"
#include "ProceduralMeshComponent.h"
#include "Sound/SoundWaveProcedural.h"

#include <atomic>

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
	Record = WeatherRecord();
	WorldRef = World;
	Backend = Options.Backend;
	bAudio = Options.bAudio;
	bManualNiagaraTick = Options.bManualNiagaraTick;
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
	Row->SetNumberField(TEXT("ambient_fraction"), AmbientFraction);
	Row->SetNumberField(TEXT("selftest_drops"), Selftest->Num());
	RainActor = World->SpawnActor<AActor>();
	RainActor->Tags.Add(FName(TEXT("FlightSim.weather")));
	BeautyOnlyActors.Add(RainActor);
	if (Backend == EFlightSimWeatherBackend::Niagara)
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
	RainMaterial->SetScalarParameterValue(TEXT("Weight"), static_cast<float>(Weight));
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
	SplashMaterial->SetScalarParameterValue(TEXT("Weight"), static_cast<float>(SplashWeight));
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
		else if (FMaterialResource* Resource = Base->GetMaterialResource(World->GetFeatureLevel()))
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
	StormMaterial->SetVectorParameterValue(TEXT("Drift"),
		FLinearColor(static_cast<float>(Drift[0]), static_cast<float>(Drift[1]), 0.0f, 0.0f));
	// The look's layer inside the storm's material (0 cover: none).
	constexpr double LayerExtinctionPerM = 0.02;   // stated: a stratiform deck's order
	StormMaterial->SetVectorParameterValue(TEXT("Layer"),
		FLinearColor(static_cast<float>(Options.LayerCover), static_cast<float>(Options.LayerBaseMetres),
		             static_cast<float>(Options.LayerTopMetres), static_cast<float>(LayerExtinctionPerM)));
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
	FlashLight->SetCastShadows(true);
	FlashLight->SetVisibility(false);
	FlashLight->RegisterComponent();

	TSharedPtr<FJsonObject> Row = WeatherRecord();
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetNumberField(TEXT("flashes"), Flashes.Num());
	Row->SetNumberField(TEXT("channel_meshes"), Drawn);
	Row->SetStringField(TEXT("material"), WeatherLightningMaterialPath);
	Row->SetNumberField(TEXT("selftest_windows"), Selftest != nullptr ? Selftest->Num() : 0);
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
	const FVector CameraVelocity = Dt > 0.0 ? (View.CameraCm - PreviousCameraCm) / Dt : FVector::ZeroVector;
	if (Dt > 0.0)
	{
		AirDisplacementCm += Wind * Dt;
	}
	PreviousTimeS = T;
	PreviousCameraCm = View.CameraCm;
	const double PixelAngle = 2.0 * FMath::Tan(FMath::DegreesToRadians(View.HorizontalFovDeg) * 0.5)
		/ FMath::Max(1, View.WidthPx);
	const double Shutter = FMath::Max(View.ShutterSeconds, 1.0e-5);

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
				const double DistanceM = FMath::Max(
					1.0, FVector::Distance(View.CameraCm, EnuToEngineCm(Flash.CentroidEnu)) / WeatherCmPerMetre);
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
				FlashLight->SetWorldLocation(EnuToEngineCm(Best->CentroidEnu));
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

	// -- rain ------------------------------------------------------------------
	if (!bRain)
	{
		return;
	}
	const double Share = ShaftShare(CameraEnu);
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
	}
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
	}
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
