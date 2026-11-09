// The wet airframe (FlightSimAircraftWet.h says what, why and what it may
// not touch). Visual overhaul, module wet-airframe-canopy. BEAUTY ONLY,
// SHADING ONLY: four scalars on the look MIDs, and a record.
//
// UNCOMPILED when written: the authoring Mac cannot build UE 5.7. Every
// engine symbol below was grepped in the UE 5.7.4 headers on that machine
// (scripts/check_bridge_api.sh, block WET-AIRFRAME-CANOPY). No Cesium API.

#include "FlightSimAircraftWet.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "FlightSimWeather.h"
#include "HAL/IConsoleManager.h"
#include "Materials/MaterialInstanceDynamic.h"

namespace
{
	// Names are file-unique (NEXT.md gotcha 3: unity builds merge anonymous
	// namespaces).
	// scripts/aircraft_wet_layer.py WET_DYNAMIC_PARAMETERS (pinned by
	// tests/test_aircraft_wet.py).
	const TCHAR* const AircraftWetParamWetness = TEXT("Wetness");
	const TCHAR* const AircraftWetParamRainRateMmh = TEXT("RainRateMmh");
	const TCHAR* const AircraftWetParamAirspeedKts = TEXT("AirspeedKts");
	const TCHAR* const AircraftWetParamTimeS = TEXT("TimeS");
	// The look manifest's constants group (aircraft_look.py build_manifest).
	const TCHAR* const AircraftWetGroup = TEXT("wet");
	const TCHAR* const AircraftWetUncalibrated = TEXT("UNCALIBRATED: set by probe render on the render machine");
	// Fallbacks: scripts/aircraft_wet_layer.py WET_DEFAULTS (pinned by test),
	// used only when a look manifest predates the wet group.
	constexpr double AircraftWetDefaultSaturationMmh = 4.0;
	constexpr double AircraftWetDefaultDryTauS = 90.0;
	constexpr double AircraftWetDefaultBeadingMaxKts = 60.0;
	constexpr double AircraftWetDefaultScratchDensity = 0.6;
	constexpr double AircraftWetDefaultScratchAnisotropy = 0.5;

	double AircraftWetConstant(const TSharedPtr<FJsonObject>& Out, const TCHAR* Name, double Fallback)
	{
		const TSharedPtr<FJsonObject>* Constants = nullptr;
		const TSharedPtr<FJsonObject>* Group = nullptr;
		const TSharedPtr<FJsonObject>* Entry = nullptr;
		double Value = Fallback;
		if (Out.IsValid() && Out->TryGetObjectField(TEXT("constants"), Constants) && Constants != nullptr &&
		    (*Constants)->TryGetObjectField(AircraftWetGroup, Group) && Group != nullptr &&
		    (*Group)->TryGetObjectField(Name, Entry) && Entry != nullptr)
		{
			(*Entry)->TryGetNumberField(TEXT("value"), Value);
		}
		return Value;
	}
}

double FFlightSimAircraftWet::TargetWetness(double RainRateMmh, double SaturationMmh)
{
	if (SaturationMmh <= 0.0)
	{
		return RainRateMmh > 0.0 ? 1.0 : 0.0;
	}
	return FMath::Clamp(RainRateMmh / SaturationMmh, 0.0, 1.0);
}

double FFlightSimAircraftWet::DryOff(double InWetness, double Target, double DtS, double TauS)
{
	// Wetting is immediate; drying is the exact exponential toward the
	// target, so N steps over T equal one step of T (frame-rate independent).
	if (Target >= InWetness || TauS <= 0.0)
	{
		return Target;
	}
	return Target + (InWetness - Target) * FMath::Exp(-FMath::Max(DtS, 0.0) / TauS);
}

bool FFlightSimAircraftWet::IsAirflowRegime(double AirspeedKts, double BeadingMaxKts)
{
	// aircraft_wet.hlsl: airflow = AirspeedKts >= BeadingMaxKts.
	return AirspeedKts >= BeadingMaxKts;
}

void FFlightSimAircraftWet::Advance(TArray<UMaterialInstanceDynamic*>& LookMids, const FFlightSimWeather& Weather,
                                    double AirspeedKts, double SimTimeS, TSharedPtr<FJsonObject> Out)
{
	// -- the rain, from the weather's own record (rain.rate_mmh is written
	// only when the rain is drawn; the beauty gain only under -quality=beauty).
	double RainRateMmh = 0.0;
	double BeautyRainGain = 1.0;
	const TSharedPtr<FJsonObject>* Rain = nullptr;
	if (Weather.DrawsRain() && Weather.Record.IsValid() &&
	    Weather.Record->TryGetObjectField(TEXT("rain"), Rain) && Rain != nullptr && Rain->IsValid())
	{
		(*Rain)->TryGetNumberField(TEXT("rate_mmh"), RainRateMmh);
		(*Rain)->TryGetNumberField(TEXT("beauty_readability_gain"), BeautyRainGain);
	}
	RainRateMmh = FMath::Max(RainRateMmh, 0.0);
	BeautyRainGain = FMath::Max(BeautyRainGain, 0.0);

	// -- the wetness on the FDM's time.
	const double SaturationMmh = AircraftWetConstant(Out, TEXT("WetSaturationMmh"), AircraftWetDefaultSaturationMmh);
	const double TauS = AircraftWetConstant(Out, TEXT("WetDryTauS"), AircraftWetDefaultDryTauS);
	const double BeadingMaxKts = AircraftWetConstant(Out, TEXT("BeadingMaxKts"), AircraftWetDefaultBeadingMaxKts);
	const double Target = TargetWetness(RainRateMmh, SaturationMmh);
	if (!bStarted)
	{
		Wetness = Target;
		bStarted = true;
	}
	else
	{
		Wetness = DryOff(Wetness, Target, SimTimeS - LastTimeS, TauS);
	}
	LastTimeS = SimTimeS;
	PeakWetness = FMath::Max(PeakWetness, Wetness);
	const bool bAirflow = IsAirflowRegime(AirspeedKts, BeadingMaxKts);
	++Frames;
	AirflowFrames += bAirflow ? 1 : 0;
	GravityFrames += bAirflow ? 0 : 1;
	const double RivuletRainMmh = RainRateMmh * BeautyRainGain;

	// -- the four scalars on every look MID (shading only).
	int32 Applied = 0;
	for (UMaterialInstanceDynamic* Mid : LookMids)
	{
		if (Mid == nullptr)
		{
			continue;
		}
		Mid->SetScalarParameterValue(FName(AircraftWetParamWetness), static_cast<float>(Wetness));
		Mid->SetScalarParameterValue(FName(AircraftWetParamRainRateMmh), static_cast<float>(RivuletRainMmh));
		Mid->SetScalarParameterValue(FName(AircraftWetParamAirspeedKts), static_cast<float>(AirspeedKts));
		Mid->SetScalarParameterValue(FName(AircraftWetParamTimeS), static_cast<float>(SimTimeS));
		++Applied;
	}

	// -- render.json aircraft_look.wet, current at every step.
	if (!Out.IsValid())
	{
		return;
	}
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	Row->SetNumberField(TEXT("wetness"), Wetness);
	Row->SetNumberField(TEXT("peak_wetness"), PeakWetness);
	Row->SetNumberField(TEXT("rain_rate_mmh"), RainRateMmh);
	Row->SetNumberField(TEXT("rivulet_rain_rate_mmh"), RivuletRainMmh);
	Row->SetNumberField(TEXT("beauty_rain_gain"), BeautyRainGain);
	Row->SetNumberField(TEXT("airspeed_kts"), AirspeedKts);
	Row->SetStringField(TEXT("regime"), bAirflow ? TEXT("airflow") : TEXT("gravity"));
	Row->SetNumberField(TEXT("frames"), Frames);
	Row->SetNumberField(TEXT("airflow_frames"), AirflowFrames);
	Row->SetNumberField(TEXT("gravity_frames"), GravityFrames);
	Row->SetNumberField(TEXT("mids"), Applied);
	TSharedPtr<FJsonObject> Constants = MakeShared<FJsonObject>();
	Constants->SetNumberField(TEXT("WetSaturationMmh"), SaturationMmh);
	Constants->SetNumberField(TEXT("WetDryTauS"), TauS);
	Constants->SetNumberField(TEXT("BeadingMaxKts"), BeadingMaxKts);
	Constants->SetStringField(TEXT("source"), TEXT("aircraft_look.constants.wet (the look manifest; every other wet ")
		TEXT("constant is a master scalar default: scripts/aircraft_wet_layer.py WET_DEFAULTS)"));
	Row->SetObjectField(TEXT("constants"), Constants);
	Row->SetStringField(TEXT("rule"), TEXT("target = saturate(rain_rate_mmh / WetSaturationMmh); wetting immediate, ")
		TEXT("drying exp(-dt / WetDryTauS) on simulation/sim-time-sec; regime airflow at or above BeadingMaxKts ")
		TEXT("(rivulets aft along object -X), else gravity (runs along world -Z, beads on glass)"));
	TSharedPtr<FJsonObject> Scratch = MakeShared<FJsonObject>();
	Scratch->SetNumberField(TEXT("density"),
		AircraftWetConstant(Out, TEXT("ScratchDensity"), AircraftWetDefaultScratchDensity));
	Scratch->SetNumberField(TEXT("anisotropy"),
		AircraftWetConstant(Out, TEXT("ScratchAnisotropy"), AircraftWetDefaultScratchAnisotropy));
	// The anisotropic lobe draws only with r.AnisotropicMaterials on (1 at the
	// Cinematic shading scalability); without it the glass is the plain glass.
	IConsoleVariable* Aniso = IConsoleManager::Get().FindConsoleVariable(TEXT("r.AnisotropicMaterials"));
	Scratch->SetNumberField(TEXT("r_anisotropic_materials"), Aniso != nullptr ? Aniso->GetInt() : -1);
	Row->SetObjectField(TEXT("canopy_scratch"), Scratch);
	Row->SetBoolField(TEXT("pixel_moving"), false);
	Row->SetStringField(TEXT("label_convention"), TEXT("shading only on the beauty look MIDs: no world position ")
		TEXT("offset, every master opaque (the canopy glass included), so silhouette, class, mask and depth are ")
		TEXT("the dry airframe's"));
	Row->SetStringField(TEXT("calibration"), AircraftWetUncalibrated);
	Out->SetObjectField(TEXT("wet"), Row);
}
