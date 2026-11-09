// Sun shafts and sky occlusion (visual overhaul, module
// sun-shafts-sky-occlusion, 2026-11-09).
//
// BEAUTY ONLY. FFlightSimWorldBeauty::Build (FlightSimClouds.cpp) calls Apply
// once, right after the world presets; the render commandlet builds the world
// beauty only under -quality=beauty or -quality=pathtrace, so -quality=measure
// never reaches this file and is byte-identical to the build before it.
//
// What it sets, each value recorded in render.json
// look_applied.world_beauty.sun_shafts:
//
// * the sun's light-shaft occlusion and light-shaft bloom (screen-space
//   crepuscular rays past ridges and the airframe; the bloom only where a sun
//   disc is visible, i.e. clear and hazy);
// * the sun's cloud shadow on the SkyAtmosphere (true crepuscular rays under
//   cumulus and at golden hour) and on surfaces, its extent and map
//   resolution. bCastShadowsOnAtmosphere is ApplyAtmosphere's (left alone);
//   the bCastCloudShadows switch is the scene's (Gate 6's cloud bracket turns
//   it off) and is read, never written;
// * cloud ambient occlusion on the SkyLight (a darker ground under overcast);
// * cvars: a deterministic, full-resolution real-time sky capture and, on the
//   still tier only, a finer volumetric-fog grid. Each previous value is saved
//   and put back by Restore() at commandlet teardown.
//
// VALUE-ONLY: radiance changes, no surface moves (not a pixel-moving effect).
// A missing sun, sky light or cvar is recorded as "skipped: <reason>", never
// refused: this is a look, not a rule. Every number is UNCALIBRATED
// (core/scene/sun_shafts.py is the table; docs/visual/PROBE_LOG.md
// ## sun-shafts-sky-occlusion names the probes).
//
// UNCOMPILED when written (a Mac whose Xcode is above UE 5.7's cap): every
// engine symbol was read in the 5.7.4 headers and is listed in
// scripts/check_bridge_api.sh ("sun-shafts-sky-occlusion" block).

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class FFlightSimVisualScene;
class UWorld;

class FLIGHTSIMBRIDGE_API FFlightSimSunShafts
{
public:
	// The cost tier from the command line: still when the frame accumulates
	// (-still-samples=, -accumulate=, -quality=pathtrace) or when
	// -sun-shafts-tier=still (env FLIGHTSIM_SUN_SHAFTS_TIER) says so;
	// -sun-shafts-tier=interactive forces engine defaults. The basis is kept
	// for the record.
	bool ResolveStillTier(const TCHAR* Params);

	// Everything above. PresetIndex is FlightSimWorldPure's (clear 0, hazy 1,
	// overcast 2, rain 3, storm 4). Out is replaced with the record.
	void Apply(UWorld* World, FFlightSimVisualScene& Scene, int32 PresetIndex, bool bStill,
	           TSharedPtr<FJsonObject>& Out);

	// Every cvar Apply wrote, back to the value it had before. Idempotent.
	void Restore();

private:
	struct FSavedCvar
	{
		FString Name;
		FString Before;
	};
	TArray<FSavedCvar> Saved;
	FString TierBasis;
};
