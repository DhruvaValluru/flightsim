// Downburst in the Unreal host: the same divergence-free field the headless
// physics flies.
//
// Line-for-line port of core/environment/downburst.py -- Vicroy's vertical
// shaping (NASA TM-104053: e^{c1 z/zm} - e^{c2 z/zm}), a Gaussian radial
// envelope, and the vertical component DERIVED from incompressible continuity
// so div(u) = 0 identically. Same constants, same lambda derivation from the
// commanded outflow peak.
//
// Like FlightSimOrographic, this port is not trusted on inspection: the render
// commandlet samples the field at a fixed (r, z) grid at startup and writes
// the NED components into the manifest; the Python harness recomputes the same
// points through the original provider and compares. Every parameter with a
// judgment in it (centre, radius, magnitudes) is computed once in Python and
// carried in the run card -- this struct derives nothing but the closed-form
// lambda, whose derivation the selftest pins.

#pragma once

#include "CoreMinimal.h"

struct FFlightSimDownburst
{
	// Vicroy vertical shaping constants, mirrored from downburst.py. A change
	// there fails the selftest until it is changed here -- by design.
	static constexpr double VicroyC1 = -0.15;
	static constexpr double VicroyC2 = -3.2175;

	void Init(double InCentreNorthMetres, double InCentreEastMetres,
	          double InCoreRadiusMetres, double InOutflowMaxMps,
	          double InOutflowHeightMetres);

	// Vicroy's p(z/zm): zero at the ground, ~1 at zeta = 1.
	static double Shaping(double Zeta);
	// Closed-form integral of the shaping from 0 to zeta (in zeta units).
	static double ShapingIntegral(double Zeta);

	// u_r: positive away from the axis, m/s. Zero at ground and axis.
	double RadialOutflowMps(double RadiusMetres, double AglMetres) const;
	// w, positive UP: the continuity-derived downdraft / updraft ring.
	double VerticalMps(double RadiusMetres, double AglMetres) const;

	// The full NED contribution at a local scene point (same north/east frame
	// as the orographic field: projected CRS about the card's origin).
	void WindNedMps(double NorthMetres, double EastMetres, double AglMetres,
	                double& OutNorthMps, double& OutEastMps,
	                double& OutDownMps) const;

	double CentreNorthMetres = 0.0;
	double CentreEastMetres = 0.0;
	double CoreRadiusMetres = 1000.0;
	double OutflowMaxMps = 12.0;
	double OutflowHeightMetres = 150.0;
	double Lambda = 0.0;
};
