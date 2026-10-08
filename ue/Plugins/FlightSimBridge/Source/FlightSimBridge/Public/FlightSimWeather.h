// The weather a render draws as weather: the card's ``weather`` block
// (core/scene/storm_weather.py) -- rain as drops in the air, splashes on the
// ground, drops on a cockpit's glass, the thunderstorm's cumulonimbus with its
// anvil and rain shaft, its lightning and (in the interactive window) its
// thunder.
//
// Everything with a judgment in it is on the card, computed once in Python:
// the drop-size distribution and the particle budget, the cell's geometry
// and extinction, every flash's time, strokes and channel. This file derives
// only the per-frame state -- where the camera is, how fast it moves, what
// the exposure integrates -- and ports four closed forms, each checked at
// Build against the card's own selftest and refused (weather.selftest) when
// it disagrees:
//
//  * SplitMix64 and the drop sampler (core/scene/rain_field.py drop);
//  * the Atlas fall speed (core/scene/precipitation.py);
//  * the stroke light curve integrated over an exposure
//    (core/scene/lightning.py window_power);
//  * the thunder synthesis (core/scene/thunder.py synthesise).
//
// OPT-IN beside the weather look (FlightSimWeatherLook.cpp) and its rain
// particles (FlightSimRainParticles.cpp): -weather-backend=off, the
// default, draws nothing here and leaves those exactly as before. Asked
// for, these drops replace the rain particles (the scene's
// bSkipRainParticles) and the glass replaces the lens drops on a cockpit
// camera. Two ways to draw the rain (-weather-backend=):
//
//  * procedural: one procedural mesh of four vertices per
//    drop, every drop's place a pure function of its index, the card's seed
//    and the run time, evaluated in M_RainDrops's world position offset
//    (assets/shaders/weather/rain_drop_offset.hlsl). Deterministic in the
//    step (Gate 10-R), no simulation state anywhere;
//  * niagara: the hand-built NS_FlightSimRain system (docs/WEATHER.md lists
//    its user parameters), fed the same numbers per frame. GPU-simulated,
//    so a replay is NOT byte-identical; recorded so.
//
// The cell, the lightning, the splashes and the glass are the same in both.
//
// Every element drawn is beauty-only: the actors go into BeautyOnlyActors,
// which the label captures hide, so mask, class and depth are byte-identical
// with the weather on and off.
//
// UNCOMPILED here (no engine in the build container): pinned by
// tests/test_ue_weather_source.py, verified by the first Windows build
// (docs/WEATHER.md, clauses WX.1-WX.6).

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "FlightSimDownburst.h"

class AActor;
class ADirectionalLight;
class AGeoReferencingSystem;
class UAudioComponent;
class UMaterialInstanceDynamic;
class UNiagaraComponent;
class UPointLightComponent;
class UProceduralMeshComponent;
class USceneCaptureComponent2D;
class UVolumetricCloudComponent;
class UWorld;
struct FFlightSimRainNoise;

enum class EFlightSimWeatherBackend : uint8
{
	Procedural,
	Niagara,
	Off,
};

struct FFlightSimWeatherOptions
{
	// The whole run card (its "weather" and "downburst" blocks are read).
	TSharedPtr<FJsonObject> Card;
	// The georeferencing that placed everything else: the cell's centre and
	// the engine's east / north axes are measured through it.
	AGeoReferencingSystem* GeoReferencing = nullptr;
	EFlightSimWeatherBackend Backend = EFlightSimWeatherBackend::Off;
	// The scene's volumetric cloud component, when the look built one: the
	// storm takes it over (one component draws one cloud field) and draws
	// the look's layer inside its own material.
	UVolumetricCloudComponent* ExistingClouds = nullptr;
	double LayerCover = 0.0;
	double LayerBaseMetres = 0.0;
	double LayerTopMetres = 0.0;
	// The sun, so a storm the weather spawns casts cloud shadows.
	ADirectionalLight* Sun = nullptr;
	// The interactive window plays thunder and rain; the render does not.
	bool bAudio = false;
	// The render commandlet drives no world tick: the Niagara system is
	// advanced by hand, one frame per Advance.
	bool bManualNiagaraTick = false;
};

// What one frame looks through.
struct FFlightSimWeatherView
{
	double TimeSeconds = 0.0;
	FVector CameraCm = FVector::ZeroVector;
	double HorizontalFovDeg = 90.0;
	int32 WidthPx = 1920;
	// The exposure: the drops' streak length and the lightning's window.
	double ShutterSeconds = 1.0 / 60.0;
	// The ground under the camera, engine Z (cm); the scene datum by default.
	double GroundZCm = 0.0;
};

struct FFlightSimLightCurve
{
	double RiseS = 2.0e-6;
	double FallS = 6.0e-5;
	double PeakNorm = 1.0;
	double GlowFraction = 0.02;
	double GlowS = 1.0e-3;
	double LeaderWPerM = 600.0;
	double BranchStrokeShare = 0.25;
	double EfficacyLmPerW = 80.0;
};

struct FFlightSimStroke
{
	double TimeS = 0.0;
	double PeakWPerM = 0.0;
};

struct FFlightSimChannel
{
	bool bBranch = false;
	double LengthM = 0.0;
	TArray<FVector> PointsEnu;   // metres, east / north / up of the cell centre
};

struct FFlightSimFlash
{
	int32 Index = 0;
	double TimeS = 0.0;
	bool bCloudToGround = false;
	bool bLeader = false;
	double LeaderStartS = 0.0;
	double LeaderEndS = 0.0;
	TArray<FFlightSimStroke> Strokes;
	bool bContinuing = false;
	double ContinuingStartS = 0.0;
	double ContinuingDurationS = 0.0;
	double ContinuingWPerM = 0.0;
	TArray<FFlightSimChannel> Channels;
	FVector CentroidEnu = FVector::ZeroVector;
};

struct FFlightSimFlashPower
{
	double MainWPerM = 0.0;
	double BranchWPerM = 0.0;
	double LeaderProgress = 0.0;
};

struct FFlightSimThunderConstants
{
	double SoundSpeedMps = 340.0;
	double RelaxationRadiusM = 1.0;
	double T0S = 0.004;
	double Lengthening = 0.5;
	double DirectivityFloor = 0.15;
	double PressureRefPaM = 400.0;
	double AbsorptionF0Hz = 3000.0;
	double AbsorptionRM = 800.0;
	double AudibleFullM = 15000.0;
	double AudibleMaxM = 25000.0;
	double FullScalePa = 100.0;
	int32 SampleRateHz = 48000;
};

class FLIGHTSIMBRIDGE_API FFlightSimWeather
{
public:
	// "procedural" | "niagara" | "off" (empty: off, the default -- the
	// storm weather is opt-in beside the weather look); anything else
	// refused by name.
	static bool ParseBackend(const FString& Name, EFlightSimWeatherBackend& Out, FString& Error);

	// Reads the card's weather block, runs the selftests, spawns what it
	// draws. A card without the block builds nothing and records so. A
	// thunderstorm whose card carries no downburst block draws its rain and
	// records the cell and the lightning as not drawn (they have no place).
	bool Build(UWorld* World, const FFlightSimWeatherOptions& Options, FString& Error);

	// Per frame, before the captures: the drops' shift, the camera's
	// velocity, the shaft's share, the flashes in this exposure, the cell's
	// time, the thunder that has started. Deterministic in View.TimeSeconds
	// on the procedural backend.
	void Advance(const FFlightSimWeatherView& View);

	// Drops on the glass of a cockpit camera's beauty capture (a post-process
	// blendable, the label captures never see it). Refused weather.windshield
	// when the material is absent.
	bool ApplyWindshield(USceneCaptureComponent2D* Beauty, double AirspeedMps, FString& Error);

	bool DrawsRain() const { return bRain; }
	bool IsBuilt() const { return bBuilt; }

	// Every registered volumetric cloud in the world checked the way the
	// engine's cloud passes check it (a Volume material, flagged "Used with
	// Volumetric Cloud", compiled without errors), each logged; false with
	// clouds.material naming the first bad one. Call before the first frame
	// of any host that draws clouds: the engine asserts where this refuses.
	static bool VerifyCloudMaterials(UWorld* World, FString& Error,
	                                 TArray<FString>* OutReport = nullptr);

	// render.json look_applied.weather: what was drawn, with what, and what
	// was not and why. Valid after Build().
	TSharedPtr<FJsonObject> Record;
	// Hidden from every label capture.
	TArray<AActor*> BeautyOnlyActors;

	// -- the closed forms, public for the selftests --------------------------
	static uint64 SplitMix64(uint64 X);
	static double Unit(uint64 Seed, uint64 Index, uint64 Channel);
	static double TerminalVelocityMps(double DiameterMm);
	static double SampleDiameterMm(double U, double Lambda, double DMinMm, double DMaxMm);
	static double AxisRatio(double DiameterMm);
	static double PresentedWidthMm(double DiameterMm);
	static double StrokeEnergy(const FFlightSimLightCurve& Curve, double Peak, double A, double B);
	static FFlightSimFlashPower WindowPower(const FFlightSimLightCurve& Curve,
	                                        const FFlightSimFlash& Flash, double A, double B);
	static double IntensityCd(const FFlightSimLightCurve& Curve, const FFlightSimFlash& Flash,
	                          const FFlightSimFlashPower& Power);
	// Thunder at Listener (ENU metres of the cell centre), sample 0 at the
	// flash's time; returns the first arrival (s) or a negative number when
	// nothing is heard.
	static double SynthesiseThunder(const FFlightSimThunderConstants& Constants,
	                                const FFlightSimFlash& Flash, const FVector& Listener,
	                                int32 SampleRateHz, TArray<double>& OutSamples);
	static bool ParseFlash(const TSharedPtr<FJsonObject>& Json, FFlightSimFlash& Out,
	                       FString& Error);

private:
	bool BuildRain(UWorld* World, const TSharedPtr<FJsonObject>& Rain,
	               const FFlightSimWeatherOptions& Options, FString& Error);
	bool BuildRainMesh(UWorld* World, FString& Error);
	bool BuildSplashMesh(UWorld* World, FString& Error);
	bool BuildNiagaraRain(UWorld* World, const FFlightSimWeatherOptions& Options, FString& Error);
	bool BuildCell(UWorld* World, const TSharedPtr<FJsonObject>& Cell,
	               const FFlightSimWeatherOptions& Options, FString& Error);
	bool BuildLightning(UWorld* World, const TSharedPtr<FJsonObject>& Lightning, FString& Error);
	bool ReadThunder(const TSharedPtr<FJsonObject>& Thunder, FString& Error);
	bool MeasureFrame(const FFlightSimWeatherOptions& Options, FString& Error);

	FVector EnuToEngineCm(const FVector& Enu) const;
	FVector EnuVectorToEngine(const FVector& Enu) const;
	FVector EngineToEnu(const FVector& EngineCm) const;
	FVector WindEngineCmPerS(const FVector& CameraEnu) const;
	double ShaftShare(const FVector& CameraEnu) const;
	void StartRainNoise();
	void PlayThunder(UWorld* World, const FFlightSimFlash& Flash, const FVector& ListenerEnu,
	                 double NowSeconds);

	bool bBuilt = false;
	bool bRain = false;
	bool bCell = false;
	bool bLightning = false;
	bool bThunder = false;
	EFlightSimWeatherBackend Backend = EFlightSimWeatherBackend::Off;
	UWorld* WorldRef = nullptr;

	// The frame: the cell centre (or the georeferencing origin without a
	// cell) and the engine directions of local east and north, measured.
	FVector CentreEngineCm = FVector::ZeroVector;
	FVector EastAxis = FVector(1.0, 0.0, 0.0);
	FVector NorthAxis = FVector(0.0, 1.0, 0.0);
	// The downburst's local frame (projected minus origin) at the cell centre.
	double CentreNorthMetres = 0.0;
	double CentreEastMetres = 0.0;
	bool bDownburst = false;
	FFlightSimDownburst Downburst;

	// -- rain --------------------------------------------------------------
	double RainLambda = 0.0;
	double RainRateMmh = 0.0;
	double RainDMinMm = 1.0;
	double RainDMaxMm = 6.0;
	FVector BoxHalfM = FVector(10.0, 10.0, 8.0);
	int32 Particles = 0;
	double Weight = 1.0;
	double AmbientFraction = 1.0;
	double FallSpeedFactor = 1.0;
	FVector WindEnuMps = FVector::ZeroVector;
	uint64 RainSeed = 0;
	double D0Mm = 1.0;
	double SplashPeriodS = 0.06;
	double SplashLifetimeS = 0.06;
	double SplashHalfSideM = 10.0;
	int32 SplashSlots = 0;
	double SplashWeight = 1.0;
	double SplashMaxAglM = 8.0;
	double WindshieldImpinge = 0.0;
	double WindshieldRunoffMps = 0.0;
	UProceduralMeshComponent* RainMesh = nullptr;
	UProceduralMeshComponent* SplashMesh = nullptr;
	UMaterialInstanceDynamic* RainMaterial = nullptr;
	UMaterialInstanceDynamic* SplashMaterial = nullptr;
	UMaterialInstanceDynamic* WindshieldMaterial = nullptr;
	UNiagaraComponent* NiagaraRain = nullptr;
	bool bManualNiagaraTick = false;
	AActor* RainActor = nullptr;
	// The air's displacement since t = 0 (engine cm), integrated per Advance.
	FVector AirDisplacementCm = FVector::ZeroVector;
	FVector PreviousCameraCm = FVector::ZeroVector;
	double PreviousTimeS = -1.0;

	// -- the cell ------------------------------------------------------------
	double BaseM = 1000.0;
	double ShaftRadiusM = 1000.0;
	double GlowDiffusionM = 1500.0;
	double CellAlbedo = 0.98;
	UVolumetricCloudComponent* StormClouds = nullptr;
	UMaterialInstanceDynamic* StormMaterial = nullptr;

	// -- lightning -----------------------------------------------------------
	FFlightSimLightCurve Curve;
	TArray<FFlightSimFlash> Flashes;
	TArray<UProceduralMeshComponent*> FlashMeshes;
	TArray<UMaterialInstanceDynamic*> FlashMaterials;
	UPointLightComponent* FlashLight = nullptr;
	AActor* LightningActor = nullptr;

	// -- thunder -------------------------------------------------------------
	FFlightSimThunderConstants Thunder;
	TSet<int32> ThunderStarted;
	TArray<UAudioComponent*> ThunderVoices;
	UAudioComponent* RainVoice = nullptr;
	TSharedPtr<FFlightSimRainNoise, ESPMode::ThreadSafe> RainNoise;
	bool bAudio = false;
};
