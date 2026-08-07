#include "FlightSimOrographic.h"

void FFlightSimOrographicWind::Init(const FFlightSimHeightfield* InTerrain,
                                    double InWindSpeedMps, double InWindFromDeg,
                                    double InDecayHeightMetres,
                                    double InWavelengthMetres, bool bInEnableLee,
                                    double InOriginXMetres, double InOriginYMetres)
{
	Terrain = InTerrain;
	WindSpeedMps = InWindSpeedMps;
	WindFromDeg = FMath::Fmod(InWindFromDeg, 360.0);
	if (WindFromDeg < 0.0) { WindFromDeg += 360.0; }
	DecayHeightMetres = InDecayHeightMetres;
	WavelengthMetres = InWavelengthMetres;
	bEnableLee = bInEnableLee;
	OriginXMetres = InOriginXMetres;
	OriginYMetres = InOriginYMetres;
	// WindNED.from_meteorological: the bearing the wind blows FROM.
	const double Radians = FMath::DegreesToRadians(WindFromDeg);
	WindNorthMps = -WindSpeedMps * FMath::Cos(Radians);
	WindEastMps = -WindSpeedMps * FMath::Sin(Radians);
}

double FFlightSimOrographicWind::ElevationMetres(double NorthMetres,
                                                 double EastMetres) const
{
	return Terrain->ElevationAt(OriginXMetres + EastMetres,
	                            OriginYMetres + NorthMetres);
}

void FFlightSimOrographicWind::Gradient(double NorthMetres, double EastMetres,
                                        double& OutDhDn, double& OutDhDe) const
{
	// TerrainField.gradient: span = max(wavelength / 16, 5).
	const double Span = FMath::Max(WavelengthMetres / 16.0, 5.0);
	const double Half = Span / 2.0;
	OutDhDn = (ElevationMetres(NorthMetres + Half, EastMetres)
	           - ElevationMetres(NorthMetres - Half, EastMetres)) / Span;
	OutDhDe = (ElevationMetres(NorthMetres, EastMetres + Half)
	           - ElevationMetres(NorthMetres, EastMetres - Half)) / Span;
}

double FFlightSimOrographicWind::LinearUpdraughtMps(double NorthMetres,
                                                    double EastMetres) const
{
	double DhDn = 0.0, DhDe = 0.0;
	Gradient(NorthMetres, EastMetres, DhDn, DhDe);
	const double Slope = FMath::Sqrt(DhDn * DhDn + DhDe * DhDe);
	double W = WindNorthMps * DhDn + WindEastMps * DhDe;
	if (Slope > LinearSlopeValid)
	{
		W *= LinearSlopeValid / Slope;
	}
	return W;
}

double FFlightSimOrographicWind::Decay(double AglMetres) const
{
	return AglMetres <= 0.0 ? 1.0 : FMath::Exp(-AglMetres / DecayHeightMetres);
}

double FFlightSimOrographicWind::LeeSinkMps(double NorthMetres,
                                            double EastMetres) const
{
	if (!bEnableLee || WindSpeedMps < 0.5)
	{
		return 0.0;
	}
	const double Un = -WindNorthMps / WindSpeedMps;
	const double Ue = -WindEastMps / WindSpeedMps;
	const double Fetch = FMath::Max(DecayHeightMetres * 6.0, WavelengthMetres * 1.5);

	const double Here = ElevationMetres(NorthMetres, EastMetres);
	double BestAscent = 0.0;
	double BestProminence = 0.0;
	double BestDistance = 0.0;
	for (int32 i = 1; i <= LeeScanPoints; ++i)
	{
		const double Distance = Fetch * i / LeeScanPoints;
		const double N = NorthMetres + Un * Distance;
		const double E = EastMetres + Ue * Distance;
		const double Prominence = ElevationMetres(N, E) - Here;
		if (Prominence <= 0.0)
		{
			continue;
		}
		const double Ascent = LinearUpdraughtMps(N, E);
		if (Ascent > BestAscent)
		{
			BestAscent = Ascent;
			BestProminence = Prominence;
			BestDistance = Distance;
		}
	}
	if (BestAscent <= 0.0)
	{
		return 0.0;
	}

	const double ProminenceFactor =
		FMath::Min(BestProminence / LeeProminenceRefMetres, 1.0);
	const double DecayLength =
		FMath::Max(BestProminence * LeeDecayRidgeHeights, 1.0);
	const double Strength =
		ProminenceFactor * FMath::Exp(-BestDistance / DecayLength);
	return LeeSinkGain * BestAscent * Strength;
}

double FFlightSimOrographicWind::WindDownMps(double NorthMetres, double EastMetres,
                                             double AglMetres) const
{
	const double Updraught = LinearUpdraughtMps(NorthMetres, EastMetres);
	const double Sink = LeeSinkMps(NorthMetres, EastMetres);
	const double WUp = (Updraught - Sink) * Decay(AglMetres);
	return -WUp;
}
