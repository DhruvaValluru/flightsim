#include "FlightSimDownburst.h"

void FFlightSimDownburst::Init(double InCentreNorthMetres,
                               double InCentreEastMetres,
                               double InCoreRadiusMetres,
                               double InOutflowMaxMps,
                               double InOutflowHeightMetres)
{
	CentreNorthMetres = InCentreNorthMetres;
	CentreEastMetres = InCentreEastMetres;
	CoreRadiusMetres = InCoreRadiusMetres;
	OutflowMaxMps = InOutflowMaxMps;
	OutflowHeightMetres = InOutflowHeightMetres;
	// Downburst.__init__: lambda from the commanded outflow peak. u_r
	// maximises at r = R/sqrt(2), z = zm; the peak zeta is where the shaping's
	// derivative vanishes, ln(c1/c2)/(c2-c1).
	const double PeakZeta =
		FMath::Loge(VicroyC1 / VicroyC2) / (VicroyC2 - VicroyC1);
	const double PeakShaping = Shaping(PeakZeta);
	const double RadialPeak =
		(CoreRadiusMetres / (2.0 * FMath::Sqrt(2.0))) * FMath::Exp(-0.5);
	Lambda = OutflowMaxMps / (RadialPeak * PeakShaping);
}

double FFlightSimDownburst::Shaping(double Zeta)
{
	return FMath::Exp(VicroyC1 * Zeta) - FMath::Exp(VicroyC2 * Zeta);
}

double FFlightSimDownburst::ShapingIntegral(double Zeta)
{
	return (FMath::Exp(VicroyC1 * Zeta) - 1.0) / VicroyC1
	       - (FMath::Exp(VicroyC2 * Zeta) - 1.0) / VicroyC2;
}

double FFlightSimDownburst::RadialOutflowMps(double RadiusMetres,
                                             double AglMetres) const
{
	if (AglMetres <= 0.0)
	{
		return 0.0;
	}
	const double Zeta = AglMetres / OutflowHeightMetres;
	const double Ratio = RadiusMetres / CoreRadiusMetres;
	const double Envelope = FMath::Exp(-(Ratio * Ratio));
	return 0.5 * Lambda * RadiusMetres * Envelope * Shaping(Zeta);
}

double FFlightSimDownburst::VerticalMps(double RadiusMetres,
                                        double AglMetres) const
{
	if (AglMetres <= 0.0)
	{
		return 0.0;
	}
	const double Zeta = AglMetres / OutflowHeightMetres;
	const double RatioSq =
		(RadiusMetres / CoreRadiusMetres) * (RadiusMetres / CoreRadiusMetres);
	const double Integral = OutflowHeightMetres * ShapingIntegral(Zeta);
	return -Lambda * (1.0 - RatioSq) * FMath::Exp(-RatioSq) * Integral;
}

void FFlightSimDownburst::WindNedMps(double NorthMetres, double EastMetres,
                                     double AglMetres, double& OutNorthMps,
                                     double& OutEastMps,
                                     double& OutDownMps) const
{
	const double Dn = NorthMetres - CentreNorthMetres;
	const double De = EastMetres - CentreEastMetres;
	const double Radius = FMath::Sqrt(Dn * Dn + De * De);
	const double Outflow = RadialOutflowMps(Radius, AglMetres);
	if (Radius < 1e-6)
	{
		OutNorthMps = 0.0;
		OutEastMps = 0.0;
	}
	else
	{
		OutNorthMps = Outflow * Dn / Radius;
		OutEastMps = Outflow * De / Radius;
	}
	// NED down positive; the field's w is up-positive.
	OutDownMps = -VerticalMps(Radius, AglMetres);
}
