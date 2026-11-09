// Dust and humidity haze (visual overhaul, module dust-humidity-haze,
// 2026-11-09). BEAUTY ONLY: an overlay on the world beauty's atmosphere
// preset, applied by FFlightSimWorldBeauty::Build right after
// ApplyAtmosphere; the measure quality never constructs FFlightSimWorldBeauty,
// so Gate 6's renders are byte-identical.
//
// What it does, all from the run card (core/scene/dust_haze.py is the Python
// twin and the documentation):
// * hygroscopic growth: the preset's Mie extinction x f(RH) = (1 - min(RH,
//   0.95))^-gamma (Hanel 1976), gamma by aerosol kind;
// * dust (desert surface, a METAR dust or sand code, or weather.dust): a warm
//   Mie absorption colour, an other-absorption tint and a tan volumetric fog
//   albedo;
// * a second exponential fog whose offset is the inversion height (the
//   flat-topped boundary-layer haze seen from 1600-3000 m).
// The card's visibility is kept: the grown Mie and the second layer's ground
// extinction come out of the main height fog (Koschmieder, counted once).
// Nothing moves a pixel; the second layer's camera-to-aircraft transmittance
// is a per-frame cloud_path row beside the clouds' (flagged under 0.5).
//
// UNCOMPILED when written (a Mac that cannot build UE 5.7): every engine
// symbol was read in the 5.7.4 headers and is listed in
// scripts/check_bridge_api.sh ("dust-humidity-haze" block).

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class FFlightSimVisualScene;
class UExponentialHeightFogComponent;
class UWorld;

class FLIGHTSIMBRIDGE_API FFlightSimDustHaze
{
public:
	// After ApplyAtmosphere. AtmosphereRecord is world_beauty.atmosphere (the
	// Mie split it applied: koschmieder_beta_per_km, mie_*_scale_per_km,
	// fog_factor), read so the overlay renormalises the numbers actually in
	// force (overrides included). Out is world_beauty.dust_haze. Never
	// refuses: an unknown weather.dust word is recorded and drawn as "none"
	// (the Python card path refuses it by name, dust_haze.row).
	void Apply(UWorld* World, FFlightSimVisualScene& Scene, const TCHAR* Params,
	           const TSharedPtr<FJsonObject>& Card, double VisibilityKm,
	           const TSharedPtr<FJsonObject>& AtmosphereRecord, TSharedPtr<FJsonObject>& Out);

	// Per frame: the camera-to-aircraft row through the second fog, in the
	// clouds' cloud_path row shape (layer, path_m, tau, transmittance,
	// flagged); null when no second layer is drawn. bFlagged is true when the
	// transmittance is under FlagTransmittance.
	TSharedPtr<FJsonObject> FrameRow(const FVector& CameraCm, const FVector& AircraftCm,
	                                 double FlagTransmittance, bool& bFlagged) const;

private:
	bool bSecondLayer = false;
	double SecondDensity = 0.0;
	double SecondFalloff = 0.0;
	// The second fog's height (m, world Z): the fog actor's Z + its offset.
	double InversionZM = 0.0;
	// The fog actor's Z (m): the base of the path_m slab, as in the Python twin.
	double FogBaseZM = 0.0;
};
