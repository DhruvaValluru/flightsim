// The baked heightfield, readable in the Unreal host.
//
// One raster format on both sides of the fence (§3.2): this reads exactly what
// core/terrain/heightfield.py writes -- .r16 samples plus a JSON sidecar --
// and answers elevation queries with the same bilinear, edge-clamped lookup
// the Python class uses, so the orographic wind computed here and the one
// computed headless are the same function of the same data. The sidecar's
// sha256 is verified against the samples on load: a raster that does not
// match its own record is refused, not rendered.

#pragma once

#include "CoreMinimal.h"

struct FFlightSimHeightfield
{
	// Reads <path>.r16 + <path>.json (extension on the input is ignored).
	// Fails with a reason if the sidecar is missing, malformed, not a
	// flightsim heightfield, or the samples do not hash to the recorded sha.
	bool Load(const FString& Path, FString& Error);

	// Elevation in metres at a projected coordinate, bilinearly interpolated,
	// clamped to the raster edge outside it -- byte-for-byte the semantics of
	// Heightfield.elevation_at.
	double ElevationAt(double XMetres, double YMetres) const;

	// Central-difference gradient (d/dx, d/dy) over ``SpanMetres``, matching
	// Heightfield.gradient_at / TerrainField.gradient.
	void GradientAt(double XMetres, double YMetres, double SpanMetres,
	                double& OutDzDx, double& OutDzDy) const;

	double SampleMetres(int32 Row, int32 Column) const
	{
		return OffsetMetres + Samples[Row * Width + Column] * ScaleMetres;
	}

	TArray<uint16> Samples;
	int32 Width = 0;
	int32 Height = 0;
	double ScaleMetres = 0.0;
	double OffsetMetres = 0.0;
	// Georeference, as the sidecar records it (GDAL convention: origin is the
	// upper-left corner of the upper-left pixel, row index increases south).
	FString Crs;
	double OriginXMetres = 0.0;
	double OriginYMetres = 0.0;
	double PixelSizeMetres = 0.0;
	bool bProjected = true;
	FString Sha256;
	// Optional provenance fields the visual pass uses; zero when absent.
	double SnowlineMetres = 0.0;
	FString LocationTitle;
	FString Name;
};
