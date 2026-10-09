#include "FlightSimWake.h"

#include <cmath>

namespace
{
	// Python's math.pi and math.radians' factor, as doubles: the port's
	// angles must be the provider's angles to the last bit, so neither
	// UE_PI (a float literal) nor FMath::DegreesToRadians is used here.
	constexpr double WakePi = 3.141592653589793;
	constexpr double WakeDegToRad = WakePi / 180.0;

	// numpy.polynomial.legendre.leggauss(32): abscissa, weight -- in
	// numpy's (ascending) order, each the shortest text that round-trips
	// the double numpy computed (repr), so the port sums the same terms in
	// the same order as core/environment/wake.py p_equivalent.
	const double GWakeGaussLegendre[][2] = {
		{-0.9972638618494816, 0.007018610009469298},
		{-0.9856115115452684, 0.016274394730905965},
		{-0.9647622555875064, 0.025392065309262427},
		{-0.9349060759377397, 0.034273862913021626},
		{-0.8963211557660522, 0.042835898022226426},
		{-0.84936761373257, 0.050998059262376244},
		{-0.7944837959679424, 0.058684093478535704},
		{-0.7321821187402897, 0.06582222277636175},
		{-0.6630442669302152, 0.07234579410884845},
		{-0.5877157572407623, 0.07819389578707031},
		{-0.5068999089322294, 0.08331192422694685},
		{-0.42135127613063533, 0.08765209300440391},
		{-0.33186860228212767, 0.09117387869576386},
		{-0.23928736225213706, 0.09384439908080457},
		{-0.1444719615827965, 0.09563872007927483},
		{-0.04830766568773831, 0.09654008851472781},
		{0.04830766568773831, 0.09654008851472781},
		{0.1444719615827965, 0.09563872007927483},
		{0.23928736225213706, 0.09384439908080457},
		{0.33186860228212767, 0.09117387869576386},
		{0.42135127613063533, 0.08765209300440391},
		{0.5068999089322294, 0.08331192422694685},
		{0.5877157572407623, 0.07819389578707031},
		{0.6630442669302152, 0.07234579410884845},
		{0.7321821187402897, 0.06582222277636175},
		{0.7944837959679424, 0.058684093478535704},
		{0.84936761373257, 0.050998059262376244},
		{0.8963211557660522, 0.042835898022226426},
		{0.9349060759377397, 0.034273862913021626},
		{0.9647622555875064, 0.025392065309262427},
		{0.9856115115452684, 0.016274394730905965},
		{0.9972638618494816, 0.007018610009469298},
	};
	static_assert(static_cast<int32>(UE_ARRAY_COUNT(GWakeGaussLegendre)) == FFlightSimWake::GaussLegendrePoints,
	              "the Gauss-Legendre table must carry exactly GL_POINTS rows");
}

int32 FFlightSimWake::GaussLegendreCount()
{
	return static_cast<int32>(UE_ARRAY_COUNT(GWakeGaussLegendre));
}

// -- the closed forms (wake.py, function for function) ----------------------

double FFlightSimWake::BurnhamHallock(double RMetres, double Gamma, double RcMetres)
{
	// burnham_hallock: Gamma r / (2 pi (r^2 + r_c^2)) -- 0 at the centre,
	// Gamma / (4 pi r_c) at r = r_c.
	return Gamma * RMetres / (2.0 * WakePi * (RMetres * RMetres + RcMetres * RcMetres));
}

double FFlightSimWake::DescentSpeed(double Gamma, double SpacingMetres)
{
	// descent_speed: w_0 = Gamma / (2 pi b_0).
	return Gamma / (2.0 * WakePi * SpacingMetres);
}

void FFlightSimWake::PairVelocity(double YMetres, double ZMetres, double Gamma,
                                  double SpacingMetres, double RcMetres,
                                  double& OutV, double& OutWUp)
{
	// pair_velocity: the starboard vortex (+b_0/2, sign +1, counter-
	// clockwise seen from behind) then the port one (-b_0/2, sign -1); the
	// counter-clockwise tangential direction is (-dz, dy) / r.
	const double Centres[2][2] = {{0.5 * SpacingMetres, 1.0}, {-0.5 * SpacingMetres, -1.0}};
	double V = 0.0;
	double W = 0.0;
	for (int32 Vortex = 0; Vortex < 2; ++Vortex)
	{
		const double Dy = YMetres - Centres[Vortex][0];
		const double Dz = ZMetres;
		const double R = std::hypot(Dy, Dz);
		if (R == 0.0)
		{
			continue;
		}
		const double Speed = BurnhamHallock(R, Gamma, RcMetres);
		V += Centres[Vortex][1] * Speed * (-Dz / R);
		W += Centres[Vortex][1] * Speed * (Dy / R);
	}
	OutV = V;
	OutWUp = W;
}

double FFlightSimWake::SarpkayaDemiseTime(double InEpsStar, double InNStar)
{
	// sarpkaya_demise_time: T_d = (0.7475 / eps*)^(4/3), bounded by
	// pi / (2 N*) when N* > 0 (the provider's stated bound).
	double Demise = std::pow(SarpkayaDemiseConstant / InEpsStar, 4.0 / 3.0);
	if (InNStar > 0.0)
	{
		Demise = FMath::Min(Demise, WakePi / (2.0 * InNStar));
	}
	return Demise;
}

double FFlightSimWake::CirculationAt(double AgeSeconds, double InGamma0,
                                     double SpacingMetres, const FString& Model,
                                     double InEpsStar, double InNStar)
{
	// circulation_at: 0 before the generator has passed; Gamma_0 for none;
	// Gamma_0 max(0, 1 - T / T_d), T = age w_0 / b_0, for sarpkaya.
	if (AgeSeconds < 0.0)
	{
		return 0.0;
	}
	if (Model == TEXT("none"))
	{
		return InGamma0;
	}
	const double W0 = DescentSpeed(InGamma0, SpacingMetres);
	const double TimeScale = SpacingMetres / W0;
	const double Demise = SarpkayaDemiseTime(InEpsStar, InNStar);
	const double Fraction = FMath::Max(0.0, 1.0 - (AgeSeconds / TimeScale) / Demise);
	return InGamma0 * Fraction;
}

double FFlightSimWake::PEquivalent(double YMetres, double ZMetres, double Gamma,
                                   double SpacingMetres, double RcMetres,
                                   double SpanMetres)
{
	// p_equivalent: (3 / b) sum_i w_i x_i w_up(b x_i / 2), the upwash
	// taken at the span station y + b x_i / 2 of the pair centred where
	// the probe is.
	double Total = 0.0;
	for (int32 Node = 0; Node < GaussLegendrePoints; ++Node)
	{
		const double Abscissa = GWakeGaussLegendre[Node][0];
		const double Weight = GWakeGaussLegendre[Node][1];
		double StationV = 0.0;
		double StationWUp = 0.0;
		PairVelocity(YMetres + 0.5 * SpanMetres * Abscissa, ZMetres, Gamma,
		             SpacingMetres, RcMetres, StationV, StationWUp);
		Total += Weight * Abscissa * StationWUp;
	}
	return 3.0 / SpanMetres * Total;
}

// -- the provider --------------------------------------------------------------

void FFlightSimWake::Init(const FFlightSimWakeCard& InCard)
{
	Card = InCard;
	bOriginLatched = false;
	StepsEvaluated = 0;
	StepsBeforeGenerator = 0;
	PeakAbsPEq = 0.0;
	PeakAbsW = 0.0;
}

double FFlightSimWake::Circulation(double AgeSeconds) const
{
	return CirculationAt(AgeSeconds, Card.Gamma0, Card.B0Metres, Card.DecayModel,
	                     Card.EpsStar, Card.bNStar ? Card.NStar : 0.0);
}

void FFlightSimWake::Velocity(double YMetres, double ZUpMetres, double AgeSeconds,
                              double& OutU, double& OutV, double& OutWDown) const
{
	// velocity: (0, v, -w_up) -- the pair induces no axial velocity.
	double WUp = 0.0;
	PairVelocity(YMetres, ZUpMetres, Circulation(AgeSeconds), Card.B0Metres,
	             Card.RcMetres, OutV, WUp);
	OutU = 0.0;
	OutWDown = -WUp;
}

double FFlightSimWake::PEq(double YMetres, double ZUpMetres, double AgeSeconds) const
{
	return PEquivalent(YMetres, ZUpMetres, Circulation(AgeSeconds), Card.B0Metres,
	                   Card.RcMetres, Card.OwnSpanMetres);
}

bool FFlightSimWake::Selftest(TArray<FFlightSimWakeVector>& OutHost,
                              double& OutWorst, FString& Why) const
{
	// The downburst precedent: the card's vectors are the Python
	// provider's own evaluation (WakeVortexPair.selftest_vectors); the
	// port evaluates the same probes and must land within 1e-9.
	OutHost.Reset();
	OutWorst = 0.0;
	int32 WorstIndex = -1;
	for (int32 Index = 0; Index < Card.Selftest.Num(); ++Index)
	{
		const FFlightSimWakeVector& Expected = Card.Selftest[Index];
		FFlightSimWakeVector Host;
		Host.YMetres = Expected.YMetres;
		Host.ZMetres = Expected.ZMetres;
		Host.AgeSeconds = Expected.AgeSeconds;
		Velocity(Expected.YMetres, Expected.ZMetres, Expected.AgeSeconds,
		         Host.UMps, Host.VMps, Host.WMps);
		Host.PEqRadPerSec = PEq(Expected.YMetres, Expected.ZMetres, Expected.AgeSeconds);
		const double Differences[4] = {
			FMath::Abs(Host.UMps - Expected.UMps),
			FMath::Abs(Host.VMps - Expected.VMps),
			FMath::Abs(Host.WMps - Expected.WMps),
			FMath::Abs(Host.PEqRadPerSec - Expected.PEqRadPerSec)};
		for (const double Difference : Differences)
		{
			// A NaN never compares greater: it is the worst there is.
			if (!(Difference <= OutWorst))
			{
				OutWorst = FMath::IsFinite(Difference) ? Difference : TNumericLimits<double>::Max();
				WorstIndex = Index;
			}
		}
		OutHost.Add(Host);
	}
	if (OutWorst > SelftestTolerance)
	{
		Why = FString::Printf(
			TEXT("the host's port of the vortex pair differs from the card's selftest ")
			TEXT("vector %d by %.3e, beyond the %.0e bound; the host would fly a ")
			TEXT("different field than the one the card describes"),
			WorstIndex, OutWorst, SelftestTolerance);
		return false;
	}
	return true;
}

void FFlightSimWake::Evaluate(double LatitudeDeg, double LongitudeDeg,
                              double AltitudeMetres, double RunClockSeconds,
                              FFlightSimWakeSample& Out)
{
	// relative_position: the origin and the clock latched at the first
	// call; the flat-earth displacement since then rotated into the wake
	// frame (along the heading, across to the right).
	if (!bOriginLatched)
	{
		bOriginLatched = true;
		OriginLatitudeDeg = LatitudeDeg;
		OriginLongitudeDeg = LongitudeDeg;
		OriginAltitudeMetres = AltitudeMetres;
		StartSeconds = RunClockSeconds;
	}
	const double DNorth = (LatitudeDeg - OriginLatitudeDeg) * MetresPerDegree;
	const double DEast = (LongitudeDeg - OriginLongitudeDeg) * MetresPerDegree
	                     * std::cos(OriginLatitudeDeg * WakeDegToRad);
	const double Psi = Card.HeadingDegrees * WakeDegToRad;
	const double Along = DNorth * std::cos(Psi) + DEast * std::sin(Psi);
	const double Across = -DNorth * std::sin(Psi) + DEast * std::cos(Psi);
	const double RunSeconds = RunClockSeconds - StartSeconds;
	const double Age = Card.bAgeHeld
		? Card.AgeHeldSeconds
		: Card.SeparationSeconds + RunSeconds - Along / Card.GeneratorSpeedMps;
	const double Y = Card.LateralOffsetMetres + Across;
	const double Z = Card.VerticalOffsetMetres + (AltitudeMetres - OriginAltitudeMetres);

	// evaluate: the CG velocity, p_eq over the own span, the circulation.
	double U = 0.0;
	double V = 0.0;
	double WDown = 0.0;
	Velocity(Y, Z, Age, U, V, WDown);
	const double PEqNow = PEq(Y, Z, Age);
	if (Age < 0.0)
	{
		++StepsBeforeGenerator;
	}
	++StepsEvaluated;
	PeakAbsPEq = FMath::Max(PeakAbsPEq, FMath::Abs(PEqNow));
	PeakAbsW = FMath::Max(PeakAbsW, FMath::Abs(WDown));

	// gust_at: v along the wake frame's right axis (heading + 90 deg).
	Out.GustNorthMps = -V * std::sin(Psi);
	Out.GustEastMps = V * std::cos(Psi);
	Out.GustDownMps = WDown;
	Out.PEqRadPerSec = PEqNow;
	Out.VMps = V;
	Out.WMps = WDown;
	Out.GammaM2PerSec = Circulation(Age);
	Out.AgeSeconds = Age;
	Out.LateralMetres = Y;
	Out.VerticalMetres = Z;
}
