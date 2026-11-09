// Humidity-gated condensation on the airframe (visual overhaul, module
// "condensation-solver"): wingtip vortex cores, the upper-wing vapour sheet,
// LEX vortices (J-11 class) and the transonic vapour cone.
//
// Replaces the vapour rule FlightSimAircraftFX.cpp used to apply
// (accelerations/Nz > vapour.MinNz, no humidity) with a thermodynamic test
// per site: a local pressure p_l, the isentropic local temperature
// T_l = T (p_l / p)^0.2857, and the condensed mixing ratio
// dq = q_v(RH, T, p) - q_sat(T_l, p_l) with JSBSim's Magnus saturation
// (core/environment/atmosphere.py). The Python twin and every formula, with
// what is UNCALIBRATED, is core/scene/condensation.py; tests/test_condensation.py
// pins the constant names and defaults here to it by text.
//
// The old Nz rule stays the fallback when the humidity is unavailable: the
// card states no dew point and no -humidity-pct= was given, or the
// atmosphere/RH read is not finite. render.json records which ran
// (aircraft_look.condensation.fallback_used / fallback_frames).
//
// BEAUTY ONLY. Reads the FDM (physics unchanged), spawns its OWN actors --
// never components of the aircraft actor, whose every primitive the stencil
// loop labels -- and lists each in BeautyOnlyActors, so every label capture
// hides them. Translucent media (the trail convention): not in mask, class
// or depth. Moves no geometry and refracts nothing (pixel_moving: false).
//
// UNCOMPILED when written (this Mac cannot build UE 5.7). Every engine
// symbol was grepped in the UE 5.7.4 headers; the list is in
// scripts/check_bridge_api.sh's "CONDENSATION (condensation-solver)" block.
#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Templates/Function.h"

class AActor;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UProceduralMeshComponent;
class UWorld;

// Where the relative humidity comes from (FFlightSimAircraftFXOptions carries one).
struct FFlightSimCondensationHumidity
{
	// The card's atmosphere_properties states atmosphere/dew-point-R, so the
	// FDM's atmosphere/RH is the stated day's (the commandlet sets this).
	bool bCardStated = false;
	// -humidity-pct=<0..100>: a beauty-only override (a probe's humid day);
	// bParamStated false when absent. The physics never sees it; the record
	// says it ran.
	bool bParamStated = false;
	double ParamPct = 0.0;
	void ParseParams(const FString& Params);
};

class FFlightSimCondensation
{
public:
	// Place the sites on the aircraft's mesh vertices (tips at the +/-Y
	// extremes, the cone collar at the max cross-section X station, the
	// sheet over the wing's measured chord, the LEX at the look config's
	// offsets) and spawn the beauty-only actors. bDraw false (-contrails=off)
	// still evaluates and records, drawing nothing. False (with Error) only for
	// condensation constants that contradict each other.
	bool Build(UWorld* World, AActor* Aircraft, const TSharedPtr<FJsonObject>& LookConstants,
	           const FFlightSimCondensationHumidity& Humidity, bool bDraw,
	           TArray<AActor*>& BeautyOnlyActors, FString& Error);

	// Evaluate every site at the FDM's state this captured step, drive one
	// MID scalar per site, and write Record's "condensation" object. Returns
	// true when the tip vortices condense but this module draws no tip
	// ribbons of its own (no material / no mesh vertices), so the caller's
	// wingtip vapour trails carry them instead.
	bool Advance(TFunctionRef<double(const TCHAR*)> ReadProperty, const TSharedPtr<FJsonObject>& Record);

	// The humidity this step's Advance used was available (else the caller
	// falls back to its Nz rule).
	bool HasHumidity() const { return bHumidityNow; }

private:
	struct FSample
	{
		FVector WorldCm = FVector::ZeroVector;
		double TimeS = 0.0;
		float Weight = 0.0f;
	};
	struct FTipRibbon
	{
		FVector SourceActorCm = FVector::ZeroVector;
		AActor* Owner = nullptr;
		UProceduralMeshComponent* Mesh = nullptr;
		TArray<FSample> Samples;
	};

	double Constant(const TCHAR* Name) const;
	void PlaceSites(const TArray<FVector>& Vertices);
	void BuildAttachedSections(UWorld* World, UMaterialInterface* Material);
	void RebuildRibbon(FTipRibbon& Ribbon, double NowS);
	UMaterialInstanceDynamic* SiteInstance(UMaterialInterface* Material, UProceduralMeshComponent* Mesh,
	                                       double Shape);

	bool bBuilt = false;
	bool bHumidityNow = false;
	bool bDraw = true;
	bool bTipsDrawn = false;
	AActor* Aircraft = nullptr;
	FFlightSimCondensationHumidity Humidity;
	TMap<FString, double> Values;
	TSharedPtr<FJsonObject> Out;
	TArray<TSharedPtr<FJsonValue>> PerFrame;
	int32 FallbackFrames = 0;
	int32 HumidFrames = 0;

	// The sites, actor frame (cm, +X forward, +Y right, +Z up).
	bool bSitesPlaced = false;
	FVector TipActorCm[2] = {FVector::ZeroVector, FVector::ZeroVector};
	double CollarStationCm = 0.0;
	double CollarCentreZCm = 0.0;
	double CollarRadiusCm = 0.0;
	double BodyLengthCm = 0.0;
	FVector NoseActorCm = FVector::ZeroVector;
	// Sheet stations per side: (leading-edge X, chord, top Z, |Y|) in cm.
	TArray<FVector4> SheetStations;

	AActor* Attached = nullptr;
	UProceduralMeshComponent* AttachedMesh = nullptr;
	UMaterialInstanceDynamic* SheetMID = nullptr;
	UMaterialInstanceDynamic* ConeMID = nullptr;
	UMaterialInstanceDynamic* LexMID = nullptr;
	UMaterialInstanceDynamic* TipMID = nullptr;
	TArray<FTipRibbon> Tips;
};
