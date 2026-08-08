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
#include "FlightSimDownburst.h"
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
	// Engine-start mixture, verified sustainable by the headless host at the
	// card's altitude (VENDORED.json local patch 4). 1.0 = full rich.
	double EngineMixture = 1.0;
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

	// -- position-coupled downburst (Phase 7, 2.3) ------------------------
	// The microburst field evaluated at the aircraft's ACTUAL position each
	// step (replacing the labeled nominal-track schedule). Centre and origin
	// are in the same projected-CRS local frame the orographic field uses.
	bool bDownburst = false;
	double DownburstOriginXMetres = 0.0;
	double DownburstOriginYMetres = 0.0;
	double DownburstCentreNorthMetres = 0.0;
	double DownburstCentreEastMetres = 0.0;
	double DownburstCoreRadiusMetres = 0.0;
	double DownburstOutflowMaxMps = 0.0;
	double DownburstOutflowHeightMetres = 0.0;

	// -- lee-rotor turbulence (Phase 7, 1.3) ------------------------------
	// Per-step W20 writes coupled to the orographic lee-sink field. W20
	// ONLY: the seed and the pinned severity are configure()-time writes
	// (JSBSIM_CORRECTIONS §13). Every constant is computed in Python
	// (core/environment/rotor.py) and carried here.
	bool bRotor = false;
	double RotorSigmaGain = 0.0;
	double RotorSigmaPerW20 = 0.0;
	double RotorW20CapFps = 0.0;
	double RotorBackgroundW20Fps = 0.0;

	// -- log-profile surface layer (Phase 7, 2.1) -------------------------
	// u(z) = U_ref ln(z/z0)/ln(z_ref/z0), held above the surface-layer top,
	// zero at and below z0 (core/environment/wind.py LogProfileWind).
	bool bLogProfile = false;
	double LogProfileReferenceSpeedMps = 0.0;
	double LogProfileFromDegrees = 0.0;
	double LogProfileReferenceHeightMetres = 10.0;
	double LogProfileZ0Metres = 0.03;
	double LogProfileSurfaceLayerTopMetres = 300.0;

	// -- convective thermals (Phase 7, 2.2) -------------------------------
	// Allen NASA/TM-2006-214019; every position and scale computed in
	// Python (deterministic from the spec seed) and carried here.
	bool bThermals = false;
	double ThermalsWstarMps = 0.0;
	double ThermalsZiMetres = 0.0;
	double ThermalsAreaNorthMetres = 0.0;
	double ThermalsAreaEastMetres = 0.0;
	// Projected-CRS origin of the local frame the positions are in, exactly
	// like the downburst's.
	double ThermalsOriginXMetres = 0.0;
	double ThermalsOriginYMetres = 0.0;
	TArray<double> ThermalNorthMetres;
	TArray<double> ThermalEastMetres;

	// -- evolving-conditions schedules (Phase 7, 3.1) ---------------------
	// Turbulence intensity over time, delivered as W20 fps ONLY -- the
	// measured-sane route (§13). Entries held until the next time. The seed
	// and pinned severity stay configure()-time.
	TArray<double> TurbulenceScheduleTimes;
	TArray<double> TurbulenceScheduleW20Fps;
	// When true, the orographic forcing wind follows the wind schedule's
	// horizontal vector each step instead of staying at its initial value.
	bool bOrographicFollowSchedule = false;

	// -- real heightfield collision (Phase 7, 1.2) ------------------------
	// Path to the SAME baked raster the visuals draw. When set, the ground
	// query slab is replaced by collision geometry built from this raster
	// (one raster, one sha, both uses), and VerifyTrimmedCondition checks
	// AGL against the raster elevation under the aircraft rather than the
	// spec's flat terrain elevation -- the right claim for real ground.
	FString CollisionTerrainPath;
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

	// The downburst field, when the card enables it -- for the selftest.
	const FFlightSimDownburst* GetDownburst() const
	{
		return bDownburstReady ? &Downburst : nullptr;
	}

	// The rotor W20 at a local scene point, fps -- the exact per-step write,
	// exposed so the commandlet can grid-sample it for the selftest.
	double RotorW20Fps(double NorthMetres, double EastMetres,
	                   double AglMetres) const;
	bool RotorReady() const { return bRotorReady; }

	// The log-profile horizontal speed at a height, m/s -- for the selftest.
	double LogProfileSpeedMps(double AglMetres) const;

	// The thermal field's vertical velocity (positive up, m/s) -- for the
	// selftest. Mirrors AllenThermals.w_at.
	double ThermalWMps(double NorthMetres, double EastMetres,
	                   double AglMetres) const;
	bool ThermalsReady() const { return bThermalsReady; }

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

	// Phase 7 environment couplings, all evaluated at the aircraft's actual
	// position inside Step(). Parameters come verbatim from the card and are
	// copied here at Build so the evaluators need no card reference.
	FFlightSimDownburst Downburst;
	bool bDownburstReady = false;
	bool bRotorReady = false;
	bool bLogProfileReady = false;
	bool bThermalsReady = false;
	int32 TurbulenceScheduleIndex = -1;

	struct
	{
		double SigmaGain = 0.0;
		double SigmaPerW20 = 0.107;
		double W20CapFps = 0.0;
		double BackgroundW20Fps = 0.0;
	} RotorCard;

	struct
	{
		double ReferenceSpeedMps = 0.0;
		double ReferenceHeightMetres = 10.0;
		double Z0Metres = 0.03;
		double SurfaceLayerTopMetres = 300.0;
		// Unit NED components of the meteorological FROM direction.
		double NorthUnit = 0.0;
		double EastUnit = 0.0;
	} LogProfileCard;

	struct
	{
		double WstarMps = 0.0;
		double ZiMetres = 0.0;
		double AreaNorthMetres = 0.0;
		double AreaEastMetres = 0.0;
		double OriginXMetres = 0.0;
		double OriginYMetres = 0.0;
		TArray<double> NorthMetres;
		TArray<double> EastMetres;
	} ThermalsCard;

	// Maps the aircraft's present geographic position into the projected
	// local frame about the given origin. Shared by every position-coupled
	// provider so they cannot disagree about where the aircraft is.
	void LocalSceneCoords(double OriginXMetres, double OriginYMetres,
	                      double& OutNorthMetres, double& OutEastMetres,
	                      double& OutAglMetres) const;

	// Real heightfield collision (Phase 7 1.2): the same baked raster the
	// visuals draw, cooked into query-only collision geometry replacing the
	// flat slab. Kept loaded so VerifyTrimmedCondition can check AGL against
	// the raster elevation under the aircraft.
	bool BuildTerrainCollision(const FFlightSimScenarioCard& Card, FString& Error);
	FFlightSimHeightfield CollisionTerrain;
	bool bCollisionTerrainReady = false;
};
