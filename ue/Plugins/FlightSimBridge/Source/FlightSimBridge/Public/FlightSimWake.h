// The wake-vortex pair in the Unreal host: the same field the headless
// physics flies (P9; the P7 model).
//
// Line-for-line port of core/environment/wake.py -- the Burnham-Hallock
// tangential profile V(r) = Gamma r / (2 pi (r^2 + r_c^2)) per vortex, the
// counter-rotating pair at +-b_0/2 (starboard counter-clockwise seen from
// behind), the uniform-lift strip-theory equivalent roll rate
// p_eq = (12 / b^3) int w_up(y) y dy over the OWN span by 32-point
// Gauss-Legendre (the abscissae and weights below are numpy's leggauss(32),
// written as text to 17 significant digits so both hosts sum the same
// doubles in the same order), the Sarpkaya linear-to-demise decay, and the
// own ship's relative position from the flat-earth displacement since the
// run's first step (the age rule separation_s + t - x_along / V_g, or a held
// age). Every number with a judgment in it (Gamma_0, b_0, r_c, w_0, the
// generator's speed, the offsets, the own span) arrives on the run card's
// ``wake`` block, computed once in Python; this port derives nothing.
//
// Like FlightSimDownburst, the port is not trusted on inspection: the card
// carries five selftest vectors the Python provider evaluated, the host
// evaluates the same five at startup (FFlightSimScenarioWorld::ReadCard) and
// refuses the run by name (card.wake) when any component differs by more
// than 1e-9 m/s (rad/s for p_eq). The host's own vectors ride into
// render.json's environment.wake_selftest[] for core/capture/verify.py's
// check.wake_selftest to grade against the card's.

#pragma once

#include "CoreMinimal.h"

// One selftest vector, in core/environment/wake.py SELFTEST_KEYS order:
// the probe (y right, z UP, the wake's age) and the field there (u along
// the axis -- identically 0 --, v to the right, w NED DOWN, p_eq over the
// own span).
struct FFlightSimWakeVector
{
	double YMetres = 0.0;
	double ZMetres = 0.0;
	double AgeSeconds = 0.0;
	double UMps = 0.0;
	double VMps = 0.0;
	double WMps = 0.0;
	double PEqRadPerSec = 0.0;
};

// Everything the port reads from the card's wake block, verbatim.
struct FFlightSimWakeCard
{
	double Gamma0 = 0.0;                 // gamma_0, m^2/s
	double B0Metres = 0.0;               // b_0 = pi b / 4 of the generator
	double RcMetres = 0.0;               // r_c = 0.035 b of the generator
	FString DecayModel = TEXT("none");   // decay.model: none | sarpkaya
	bool bEpsStar = false;               // decay.eps_star stated
	double EpsStar = 0.0;
	bool bNStar = false;                 // decay.n_star stated
	double NStar = 0.0;
	double LateralOffsetMetres = 0.0;    // geometry.lateral_offset_m
	double VerticalOffsetMetres = 0.0;   // geometry.vertical_offset_m
	bool bAgeHeld = false;               // geometry.age_s stated (held age)
	double AgeHeldSeconds = 0.0;
	double SeparationSeconds = 0.0;      // geometry.separation_s
	double Age0Seconds = 0.0;            // geometry.age_0_s
	double OwnSpanMetres = 0.0;          // geometry.own_span_m
	double HeadingDegrees = 0.0;         // geometry.heading_deg
	double W0Mps = 0.0;                  // geometry.w_0_mps (recorded)
	double GeneratorSpeedMps = 0.0;      // generator.speed_mps (V_g)
	TArray<FFlightSimWakeVector> Selftest;
};

// The pair's field at the own ship for one step: the gust channel's NED
// contribution (m/s), p_eq (rad/s) and the telemetry columns the headless
// provider records (wake_v_mps, wake_w_mps, wake_p_eq_rad_s,
// wake_gamma_m2_s, wake_age_s, wake_lateral_m, wake_vertical_m).
struct FFlightSimWakeSample
{
	double GustNorthMps = 0.0;
	double GustEastMps = 0.0;
	double GustDownMps = 0.0;
	double PEqRadPerSec = 0.0;
	double VMps = 0.0;
	double WMps = 0.0;
	double GammaM2PerSec = 0.0;
	double AgeSeconds = 0.0;
	double LateralMetres = 0.0;
	double VerticalMetres = 0.0;
};

struct FLIGHTSIMBRIDGE_API FFlightSimWake
{
	// wake.py GL_POINTS; the table in the .cpp carries exactly this many.
	static constexpr int32 GaussLegendrePoints = 32;
	// wake.py SARPKAYA_DEMISE_CONSTANT [from memory there, unverified].
	static constexpr double SarpkayaDemiseConstant = 0.7475;
	// wake.py METRES_PER_DEGREE: the runner's flat-earth placement rule.
	static constexpr double MetresPerDegree = 111320.0;
	// The blueprint's selftest bound: 1e-9 m/s (rad/s for p_eq), the same
	// number core/capture/verify.py WAKE_SELFTEST_TOL grades against.
	static constexpr double SelftestTolerance = 1e-9;

	// The closed forms (wake.py, function for function).
	static double BurnhamHallock(double RMetres, double Gamma, double RcMetres);
	static double DescentSpeed(double Gamma, double SpacingMetres);
	static void PairVelocity(double YMetres, double ZMetres, double Gamma,
	                         double SpacingMetres, double RcMetres,
	                         double& OutV, double& OutWUp);
	static double SarpkayaDemiseTime(double InEpsStar, double InNStar);
	static double CirculationAt(double AgeSeconds, double InGamma0,
	                            double SpacingMetres, const FString& Model,
	                            double InEpsStar, double InNStar);
	// p_eq over a level wing of SpanMetres centred at (y, z): (3 / b)
	// sum_i w_i x_i w_up(y + b x_i / 2), i over the 32 abscissae in order.
	static double PEquivalent(double YMetres, double ZMetres, double Gamma,
	                          double SpacingMetres, double RcMetres,
	                          double SpanMetres);
	// The abscissa / weight table, exposed so a caller can count it.
	static int32 GaussLegendreCount();

	void Init(const FFlightSimWakeCard& InCard);

	// WakeVortexPair.circulation / velocity / p_eq.
	double Circulation(double AgeSeconds) const;
	void Velocity(double YMetres, double ZUpMetres, double AgeSeconds,
	              double& OutU, double& OutV, double& OutWDown) const;
	double PEq(double YMetres, double ZUpMetres, double AgeSeconds) const;

	// Evaluates the card's selftest vectors through this port. Returns
	// false with Why set (a sentence, no refusal name: the caller prefixes
	// card.wake) when any component differs from the card's by more than
	// SelftestTolerance. OutHost carries the host's own vectors either way.
	bool Selftest(TArray<FFlightSimWakeVector>& OutHost, double& OutWorst,
	              FString& Why) const;

	// WakeVortexPair.relative_position + evaluate + gust_at: the field at the
	// own ship's CG (geodetic latitude, longitude, altitude MSL) at a run
	// clock time. The first call latches the origin and the clock's start,
	// exactly as the provider does on the run's first step.
	void Evaluate(double LatitudeDeg, double LongitudeDeg, double AltitudeMetres,
	              double RunClockSeconds, FFlightSimWakeSample& Out);

	FFlightSimWakeCard Card;
	bool bOriginLatched = false;
	double OriginLatitudeDeg = 0.0;
	double OriginLongitudeDeg = 0.0;
	double OriginAltitudeMetres = 0.0;
	double StartSeconds = 0.0;
	int32 StepsEvaluated = 0;
	int32 StepsBeforeGenerator = 0;
	double PeakAbsPEq = 0.0;
	double PeakAbsW = 0.0;
};
