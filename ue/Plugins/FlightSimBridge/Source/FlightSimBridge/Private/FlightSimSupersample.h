// Supersampled beauty (visual overhaul, supersample lane, 2026-11-09).
//
// -supersample=N (N in 1..4, -quality=beauty only): the BEAUTY render
// target is N times the output size on each axis, and the frame read back
// from it is reduced to the output size by an exact N x N box filter in
// linear light (sRGB decode, mean, sRGB encode) before the PNG is written.
// The beauty is tonemapped inside the engine (SCS_FinalColorLDR into an
// RGBA8_SRGB target); this commandlet has no linear-HDR beauty readback, so
// the filter runs on the tonemapped 8-bit frame, decoded to linear light.
//
// Why a box and not a Lanczos-3 (measured in tests/test_supersample.py):
// the box keeps each output pixel the exact mean of the N x N internal
// pixels whose centres average to that output pixel's centre, so an edge
// changes only the output pixels it crosses and its 50 % crossing stays on
// the geometric edge to 1/(2N) px. A Lanczos-3 rings: it changes pixels up
// to about 2.5 output px away from an edge, which a label mask would not
// show. The box is therefore NOT a pixel-moving effect; it is recorded in
// render.json beauty_samples (supersample, filter, internal size).
//
// Labels: every label capture keeps its own target at the output size,
// from the same pose and field of view (same aspect), so nothing here
// reaches them. The measure path never takes the flag (refused by name)
// and, without the flag, renders exactly as before (factor 1, no call does
// anything).
//
// Memory: the render-resolution targets scale with N^2 and TSR's history
// with N^2 times its own screen percentage squared. Configure estimates
// the VRAM those targets take and refuses by name above a budget
// (render.supersample).
//
// UNCOMPILED when written (the authoring Mac cannot build UE 5.7). Every
// engine symbol was grepped in the 5.7.4 headers; the "supersample lane"
// block of scripts/check_bridge_api.sh re-checks them before a build.
#pragma once

#include "CoreMinimal.h"

class FJsonObject;

class FFlightSimSupersample
{
public:
	// Reads -supersample=N (and -supersample-vram-budget-mib=M) from Params.
	// Absent: OutFactor = 1 and nothing is recorded. Present: refused by
	// name ("render.supersample: ...") unless Quality is "beauty", N is a
	// whole number from 1 to 4, the internal size fits the RHI's texture
	// limit and the VRAM estimate is within the budget.
	// TsrHistoryScreenPercentage is the commandlet's r.TSR.History.
	// ScreenPercentage for beauty (it enters the estimate).
	static bool Configure(const TCHAR* Params, const FString& Quality, int32 OutputWidth,
	                      int32 OutputHeight, float TsrHistoryScreenPercentage,
	                      int32& OutFactor, FString& OutError);

	// Pixels holds (OutputWidth*Factor) x (OutputHeight*Factor) texels read
	// back from the beauty target; on return it holds OutputWidth x
	// OutputHeight, box-filtered in linear light. Factor 1 is a no-op.
	static bool Downsample(TArray<FColor>& Pixels, int32 OutputWidth, int32 OutputHeight,
	                       int32 Factor, FString& OutError);

	// Adds the supersample record to Root's "beauty_samples" (merged into
	// an existing object). Writes nothing unless -supersample was stated.
	static void Record(const TSharedPtr<FJsonObject>& Root);
};
