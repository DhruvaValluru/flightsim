// One scenario, one world, one code path.
//
// Two commandlets fly scenarios in the Unreal host: one records telemetry with
// no renderer, one records frames with one. They must put the aircraft in
// exactly the same place, in exactly the same state, or the on-screen evidence
// would be evidence about a different flight from the trajectory evidence.
// Everything they share lives here, so there is nowhere for the two to drift.
//
// Driver tier. This writes to the FDM -- initial conditions, the trimmed
// control state, and any scripted control input the card asks for -- and each
// write is deliberate and logged. UFlightSimTelemetryRecorder remains
// observer-tier and reads only.

#pragma once

#include "CoreMinimal.h"
#include "FlightSimHeightfield.h"
#include "FlightSimOrographic.h"

class AActor;
class AGeoReferencingSystem;
class UJSBSimMovementComponent;
class UWorld;

DECLARE_LOG_CATEGORY_EXTERN(LogFlightSimScenario, Log, All);

// A control input applied at a wall-clock time in the run. Deliberately
// scripted rather than closed-loop: this host has no autopilot, and a scripted
// input is reproducible in a way a controller chasing a target is not.
struct FFlightSimControlInput
{
	double TimeSeconds = 0.0;
	double Aileron = 0.0;
	double Elevator = 0.0;
	double Rudder = 0.0;
};

// One scenario, as much of a core.scenario.spec.ScenarioSpec as this host can
// honour. Fields it cannot honour are not defaulted away: ReadCard refuses the
// run instead (§2.7). A spec that asks for turbulence and gets still air is the
// failure this whole build exists to not repeat.
struct FFlightSimScenarioCard
{
	FString SpecDigest;
	FString Aircraft;
	double AltitudeMetres = 0.0;
	double AirspeedKnots = 0.0;
	double HeadingDegrees = 0.0;
	double LatitudeDegrees = 0.0;
	double LongitudeDegrees = 0.0;
	double TerrainElevationMetres = 0.0;
	double DurationSeconds = 0.0;
	double RateHz = 120.0;
	double SampleIntervalSeconds = 0.1;
	bool bMassHeld = true;
	// Steady wind, meteorological convention: the bearing it blows FROM.
	// Zero speed is still air. Direction must be a whole degree (the plugin's
	// wind initial condition is an int32; ReadCard refuses fractions).
	double WindSpeedKnots = 0.0;
	double WindFromDegrees = 0.0;
	//: Empty for the parity scenario, which is hands off from trim.
	TArray<FFlightSimControlInput> ControlInputs;

	// -- turbulence (Phase 6B.3) ------------------------------------------
	// The intensity word, for the manifest. "none" means still.
	FString Turbulence = TEXT("none");
	// The EXACT property writes core/environment/turbulence.py's configure()
	// produces for this spec (turb-type, randomseed, severity, W20), computed
	// once in Python and carried here so the two hosts cannot derive
	// different numbers from the same word. Written once after trim -- never
	// per step, which would re-seed the generator (docs/JSBSIM_CORRECTIONS).
	TArray<FString> TurbulenceProperties;
	TArray<FString> TurbulenceValues;
	int64 TurbulenceSeed = 0;

	// -- time-varying wind schedule (gusts) -------------------------------
	// Per-step NED wind in fps, precomputed by the headless providers (steady
	// + 1-cosine gusts are pure functions of time), so the host writes the
	// same floats the headless stack writes rather than re-deriving a gust
	// model. Entries are held until the next time, like control inputs.
	TArray<double> WindScheduleTimes;
	TArray<double> WindScheduleNorthFps;
	TArray<double> WindScheduleEastFps;
	TArray<double> WindScheduleDownFps;

	// -- orographic lift over real terrain (Phase 6B.2) -------------------
	bool bOrographic = false;
	FString OrographicTerrainPath;
	double OrographicWindSpeedMps = 0.0;
	double OrographicWindFromDeg = 0.0;
	// Modelling parameters with judgment in them, computed once in Python
	// (terrain_field_from's wavelength, the provider's decay clamp) and
	// carried so both hosts use identical values.
	double OrographicDecayHeightMetres = 0.0;
	double OrographicWavelengthMetres = 0.0;
	bool bOrographicLee = true;
	// Scene origin of the local north/east frame, in the raster's own
	// projected CRS -- projected once in Python from the spec's lat/lon.
	double OrographicOriginXMetres = 0.0;
	double OrographicOriginYMetres = 0.0;
};

class FLIGHTSIMBRIDGE_API FFlightSimScenarioWorld
{
public:
	static bool ReadCard(const FString& Path, FFlightSimScenarioCard& Out, FString& Error);

	// From "no world" to "aircraft placed at the spec's initial conditions,
	// not yet begun play". Split from BeginPlay so a caller can hang visuals
	// off the aircraft before the first frame rather than after it.
	bool Build(const FFlightSimScenarioCard& Card, FString& Error);

	// Dispatches actor BeginPlay, which is where the plugin loads the aircraft
	// for real and trims it -- in calm air.
	bool BeginPlay(FString& Error);

	// If the card commands wind: write it to the FDM and re-trim in it (tFull).
	// Call between BeginPlay and VerifyTrimmedCondition. A no-op in still air.
	// This mirrors the headless configure_from_spec sequence rather than using
	// the plugin's wind initial condition, which measurably corrupts the
	// commanded airspeed (250 kt CAS in, 206 kt out).
	bool TrimInWind(const FFlightSimScenarioCard& Card, FString& Error);

	// Checks that the trimmed aircraft is where the spec said. Every one of
	// these can be wrong without anything failing: a bad actor placement gives
	// the right-looking aircraft at the wrong altitude, and a ground query that
	// finds no geometry reports the aircraft on the deck at 3000 m. Both would
	// produce a full run that is quietly not the commanded scenario.
	bool VerifyTrimmedCondition(const FFlightSimScenarioCard& Card, FString& Error);

	// The plugin re-sends its command struct to the FDM on every tick. Trim
	// leaves the FDM holding control positions the struct has never seen, so
	// without this the first tick overwrites the trimmed state with the
	// struct's defaults -- throttle 0.0 and gear down, neither of which anyone
	// commanded. Copies the trimmed FDM state into the struct so that the
	// per-tick write is a no-op.
	void LatchTrimmedControls(bool bMassHeld);

	// Turbulence configuration: the card's exact property writes, once, after
	// trim and latch, mirroring EnvironmentStack.configure. Never call inside
	// the step loop -- re-seeding per step destroys the correlated noise
	// (measured: 0.40 g peak load factor became 515 g).
	void ConfigureTurbulence(const FFlightSimScenarioCard& Card);

	// The orographic wind field, when the card enables it. Public so the
	// render commandlet can sample it for the manifest's selftest block.
	const FFlightSimOrographicWind* GetOrographic() const
	{
		return bOrographicReady ? &Orographic : nullptr;
	}
	const FFlightSimHeightfield* GetOrographicTerrain() const
	{
		return bOrographicReady ? &OrographicTerrain : nullptr;
	}

	// Applies whichever scripted input is current at ``TimeSeconds``, then
	// advances one fixed frame. Fails on a crash rather than continuing to
	// record a frozen state.
	bool Step(const FFlightSimScenarioCard& Card, double TimeSeconds,
	          double DeltaSeconds, FString& Error);

	void Teardown();

	double ReadProperty(const TCHAR* Name) const;

	UWorld* World = nullptr;
	AGeoReferencingSystem* GeoReferencing = nullptr;
	AActor* Aircraft = nullptr;
	UJSBSimMovementComponent* Movement = nullptr;

private:
	int32 AppliedInputIndex = -1;

	// The exact per-step wind writes, precomputed once from the card with the
	// same conversion chain the headless stack uses. Empty in still air.
	TArray<FString> WindProperties;
	TArray<FString> WindValues;
	// The same steady wind as doubles, for composition with a schedule or an
	// orographic contribution. The still-air steady path keeps writing the
	// precomputed strings above, byte-identical to what Gate 5 measured.
	double SteadyWindNorthFps = 0.0;
	double SteadyWindEastFps = 0.0;
	int32 ScheduleIndex = -1;

	// Real-terrain orographic wind (Phase 6B.2). The heightfield is the same
	// baked raster the visual pass draws and the sha in the manifest names.
	FFlightSimHeightfield OrographicTerrain;
	FFlightSimOrographicWind Orographic;
	bool bOrographicReady = false;
};
