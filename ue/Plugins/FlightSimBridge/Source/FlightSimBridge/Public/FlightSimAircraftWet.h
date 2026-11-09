// The wet airframe (visual overhaul, module wet-airframe-canopy): the
// weather's rain wets the airframe's look materials -- darker paint and
// metal, a smoother film, a wet clear coat, rain rivulets that run aft in
// the airstream and by gravity below BeadingMaxKts, beads on the glass --
// and the canopy carries anisotropic micro-scratches (the master's own
// defaults; nothing per step).
//
// BEAUTY ONLY, SHADING ONLY. FFlightSimAircraftFX (built only under
// -Visual -quality=beauty) owns the look MIDs this sets four scalars on
// (scripts/aircraft_wet_layer.py WET_DYNAMIC_PARAMETERS: Wetness,
// RainRateMmh, AirspeedKts, TimeS). The masters use no World Position
// Offset and stay opaque, so silhouette, class, mask and depth are those of
// the dry airframe and render.json needs no pixel_moving_effects entry
// (recorded: aircraft_look.wet.pixel_moving false).
//
// The wetness: target = saturate(rain rate / WetSaturationMmh); wetting is
// immediate, drying the exact exponential toward the target with time
// constant WetDryTauS on the FDM's time (simulation/sim-time-sec), so a
// replay and any frame rate give the same wetness. The first step starts
// at the target (a storm run is wet from its first frame).
//
// The rain rate is the weather's own record (FFlightSimWeather::Record
// rain.rate_mmh, rain.beauty_readability_gain): RainRateMmh and
// BeautyRainGain are private to FFlightSimWeather and the record carries
// both verbatim, so this reads them there and FlightSimWeather.h is
// untouched. The wetness uses the physical rate; the rivulets see
// rate x beauty gain (the same stated exaggeration the drawn drops use).
//
// Constants: render.json aircraft_look.constants.wet (the look manifest's
// "wet" group, each UNCALIBRATED); the fallbacks in the .cpp are the same
// numbers (pinned by tests/test_aircraft_wet.py).
//
// UNCOMPILED when written (the authoring Mac cannot build UE 5.7). Engine
// symbols grepped in the 5.7.4 headers: scripts/check_bridge_api.sh block
// "WET-AIRFRAME-CANOPY".
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class FFlightSimWeather;
class UMaterialInstanceDynamic;

class FFlightSimAircraftWet
{
public:
	// One captured step: integrate the wetness to SimTimeS, set the four
	// scalars on every look MID, and write Out->wet (Out is render.json
	// aircraft_look; its "constants" object is read for the wet group).
	void Advance(TArray<UMaterialInstanceDynamic*>& LookMids, const FFlightSimWeather& Weather,
	             double AirspeedKts, double SimTimeS, TSharedPtr<FJsonObject> Out);

	// -- the closed forms (scripts/aircraft_wet_layer.py twins) --------------
	static double TargetWetness(double RainRateMmh, double SaturationMmh);
	static double DryOff(double Wetness, double Target, double DtS, double TauS);
	static bool IsAirflowRegime(double AirspeedKts, double BeadingMaxKts);

	double GetWetness() const { return Wetness; }

private:
	double Wetness = 0.0;
	double PeakWetness = 0.0;
	double LastTimeS = 0.0;
	bool bStarted = false;
	int32 Frames = 0;
	int32 AirflowFrames = 0;
	int32 GravityFrames = 0;
};
