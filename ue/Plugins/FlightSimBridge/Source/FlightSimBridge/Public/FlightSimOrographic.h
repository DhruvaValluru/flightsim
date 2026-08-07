// Orographic wind in the Unreal host: the same field the headless physics flies.
//
// This is a line-for-line port of core/environment/terrain_field.py's
// OrographicWind -- linearised ridge lift w = U . grad(h) (Smith 1979 eq. 2.3),
// saturated above slope 0.35, exponential decay with height, and the explicit
// lee-sink term anchored to the windward ascent (FAA AC 00-57; Doyle & Durran
// 2002). Same constants, same scan, same clamps.
//
// Two implementations of one model is exactly the kind of drift §1.4 exists to
// catch, so this one does not get trusted on inspection: the render commandlet
// samples this field at a grid of points at startup and writes the values into
// the manifest, and the Python harness recomputes the same points through the
// original provider over the same baked raster and compares. A port that
// drifts fails the comparison, not the viewer.
//
// Every parameter with a modelling judgment in it (decay height, terrain
// wavelength) is computed ONCE, in Python, and carried in the run card -- this
// class derives nothing, so the two hosts cannot derive differently.

#pragma once

#include "CoreMinimal.h"
#include "FlightSimHeightfield.h"

struct FFlightSimOrographicWind
{
	// Constants mirrored from terrain_field.py. If you change one there,
	// the selftest comparison fails until you change it here -- by design.
	static constexpr double LinearSlopeValid = 0.35;
	static constexpr double LeeSinkGain = 1.3;
	static constexpr double LeeDecayRidgeHeights = 4.0;
	static constexpr int32 LeeScanPoints = 12;
	static constexpr double LeeProminenceRefMetres = 120.0;

	void Init(const FFlightSimHeightfield* InTerrain,
	          double InWindSpeedMps, double InWindFromDeg,
	          double InDecayHeightMetres, double InWavelengthMetres,
	          bool bInEnableLee,
	          double InOriginXMetres, double InOriginYMetres);

	// w = U . grad(h), positive UP, saturated on steep slopes.
	double LinearUpdraughtMps(double NorthMetres, double EastMetres) const;

	// Downward velocity from separation behind an upstream crest, m/s.
	double LeeSinkMps(double NorthMetres, double EastMetres) const;

	// exp(-z/H) vertical decay of the terrain perturbation.
	double Decay(double AglMetres) const;

	// The vertical contribution, NED down positive (an updraught is negative
	// down), matching OrographicWind.wind_at.
	double WindDownMps(double NorthMetres, double EastMetres, double AglMetres) const;

	// Terrain elevation in local scene metres about the origin, matching the
	// terrain_field_from adapter: elevation(north, east) = raster(origin_x +
	// east, origin_y + north).
	double ElevationMetres(double NorthMetres, double EastMetres) const;

	void Gradient(double NorthMetres, double EastMetres,
	              double& OutDhDn, double& OutDhDe) const;

	const FFlightSimHeightfield* Terrain = nullptr;
	double WindSpeedMps = 0.0;
	double WindFromDeg = 0.0;
	double DecayHeightMetres = 300.0;
	double WavelengthMetres = 1600.0;
	bool bEnableLee = true;
	double OriginXMetres = 0.0;
	double OriginYMetres = 0.0;
	// Horizontal wind components (m/s, NED), precomputed like the provider's
	// _wn/_we from the meteorological convention.
	double WindNorthMps = 0.0;
	double WindEastMps = 0.0;
};
