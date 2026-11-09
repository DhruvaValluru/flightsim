// Dust and humidity haze (FlightSimDustHaze.h). BEAUTY ONLY: reached only from
// FFlightSimWorldBeauty::Build, which the commandlet calls under
// -quality=beauty.
//
// UNCOMPILED when written (2026-11-09, a Mac that cannot build UE 5.7): every
// engine symbol below was read in the UE 5.7.4 headers and is listed in
// scripts/check_bridge_api.sh ("dust-humidity-haze" block); the pure block is
// pinned to core/scene/dust_haze.py by tests/test_dust_haze.py (the table by
// text, the laws compiled and run where a C++ compiler exists). Names here are
// file-unique (unity builds merge anonymous namespaces).

#include "FlightSimDustHaze.h"

#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "FlightSimVisualScene.h"
#include "HAL/PlatformMisc.h"
#include "Misc/Parse.h"
#include "UObject/UObjectIterator.h"

#include <cmath>

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimDustHaze, Log, All);

// The table and laws, dependency-free C++17. EVERY value is UNCALIBRATED: set
// by probe render on the render machine (docs/visual/PROBE_LOG.md
// ## dust-humidity-haze); core/scene/dust_haze.py is the documented twin.
// FLIGHTSIM-DUSTHAZE-PURE-BEGIN
namespace FlightSimDustHazePure
{
	enum : int
	{
		DustRowNone = 0,
		DustRowHaze = 1,
		DustRowDust = 2,
		DustRowCount = 3
	};
	enum : int
	{
		AerosolContinental = 0,
		AerosolMaritime = 1,
		AerosolDust = 2,
		AerosolCount = 3
	};

	inline const char* DustRowName(int Row)
	{
		static const char* const Names[DustRowCount] = {"none", "haze", "dust"};
		return Row >= 0 && Row < DustRowCount ? Names[Row] : "none";
	}

	inline const char* AerosolName(int Aerosol)
	{
		static const char* const Names[AerosolCount] = {"continental", "maritime", "dust"};
		return Aerosol >= 0 && Aerosol < AerosolCount ? Names[Aerosol] : "continental";
	}

	// core/scene/dust_haze.py DUST_FIELDS, in order.
	constexpr int DustFieldCount = 13;
	enum : int
	{
		DhMieAbsR = 0, DhMieAbsG, DhMieAbsB, DhOtherAbsR, DhOtherAbsG, DhOtherAbsB, DhOtherAbsScale,
		DhAlbedoR, DhAlbedoG, DhAlbedoB, DhSecondDensity, DhSecondFalloff, DhInversionM
	};

	// UNCALIBRATED: set by probe render on the render machine (every number).
	// The none row's other absorption is the engine's own ozone default
	// (0.000650, 0.001881, 0.000085) as colour / green and scale = green.
	inline double DustDefault(int Row, int Field)
	{
		static const double Rows[DustRowCount][DustFieldCount] = {
			// none
			{1.0, 1.0, 1.0, 0.000650 / 0.001881, 1.0, 0.000085 / 0.001881, 0.001881, 255, 255, 255, 0.0, 0.015, 1500.0},
			// haze
			{0.9, 1.0, 1.1, 0.000650 / 0.001881, 1.0, 0.000085 / 0.001881, 0.001881, 245, 245, 245, 0.0002, 0.015, 1500.0},
			// dust
			{0.45, 1.0, 2.2, 0.45, 1.0, 0.30, 0.0024, 222, 196, 160, 0.0004, 0.015, 1800.0},
		};
		return Row >= 0 && Row < DustRowCount && Field >= 0 && Field < DustFieldCount ? Rows[Row][Field] : 0.0;
	}

	// Hanel's gamma by aerosol (dust_haze.RH_GAMMA). UNCALIBRATED.
	inline double RhGamma(int Aerosol)
	{
		static const double Gammas[AerosolCount] = {0.3, 0.5, 0.1};
		return Aerosol >= 0 && Aerosol < AerosolCount ? Gammas[Aerosol] : 0.3;
	}

	constexpr double DustRhCap = 0.95;
	constexpr double DustDefaultRhPct = 50.0;
	constexpr double DustKoschmieder = 3.912;
	constexpr double DustRayleighGreenPerKm = 0.013558;
	constexpr double DustMieSingleScatterAlbedo = 0.9;
	// 1 / weather_visuals.ENGINE_FOG_DENSITY_PER_EXTINCTION = 0.1 x ln(2)^2.
	constexpr double DustExtinctionPerMPerDensity = 0.1 * 0.69314718055994531 * 0.69314718055994531;
	constexpr double DustFalloffToPerM = 0.1;

	inline double DustGrowthFactor(double Rh, double Gamma)
	{
		double R = Rh < 0.0 ? 0.0 : Rh;
		R = R > DustRhCap ? DustRhCap : R;
		return std::pow(1.0 - R, -(Gamma > 0.0 ? Gamma : 0.0));
	}

	inline double DustSecondExtinctionPerM(double Density, double Falloff, double OffsetM, double ZM)
	{
		if (!(Density > 0.0))
		{
			return 0.0;
		}
		return Density * DustExtinctionPerMPerDensity * std::pow(2.0, -Falloff * DustFalloffToPerM * (ZM - OffsetM));
	}

	inline double DustSecondTau(double Density, double Falloff, double OffsetM, double AZM, double BZM,
	                            double LengthM)
	{
		if (!(Density > 0.0) || !(LengthM > 0.0))
		{
			return 0.0;
		}
		const double K = Falloff * DustFalloffToPerM * 0.69314718055994531;
		const double BetaA = DustSecondExtinctionPerM(Density, Falloff, OffsetM, AZM);
		const double X = K * (BZM - AZM);
		if (std::fabs(X) < 1e-9)
		{
			return BetaA * LengthM;
		}
		return BetaA * LengthM * (1.0 - std::exp(-X)) / X;
	}

	// The length (m) of a straight segment from height a to height b that lies
	// inside [base, top] (core/scene/world_beauty.py slab_path_m).
	inline double DustSlabPathM(double AZM, double BZM, double LengthM, double BaseM, double TopM)
	{
		if (!(TopM > BaseM) || !(LengthM > 0.0))
		{
			return 0.0;
		}
		if (AZM == BZM)
		{
			return BaseM <= AZM && AZM <= TopM ? LengthM : 0.0;
		}
		const double T0 = (BaseM - AZM) / (BZM - AZM);
		const double T1 = (TopM - AZM) / (BZM - AZM);
		double Lo = T0 < T1 ? T0 : T1;
		double Hi = T0 < T1 ? T1 : T0;
		Lo = Lo > 0.0 ? Lo : 0.0;
		Hi = Hi < 1.0 ? Hi : 1.0;
		return Hi > Lo ? (Hi - Lo) * LengthM : 0.0;
	}

	struct FDustRenorm
	{
		double MieAfter;
		double SecondGroundPerKm;
		double SecondDensity;
		double FogFactorAfter;
		double Scale;
		double VisibilityModelKm;
	};

	// The grown Mie and the second layer's ground extinction, renormalised so
	// the ground extinction stays Beta: both scaled by one factor when they
	// would exceed the haze (Beta less Rayleigh); the main fog keeps the rest.
	inline FDustRenorm DustRenormalise(double Beta, double MieBefore, double FogFactorBefore, double FRh,
	                                   double DensityRow, double GroundPerKmRow)
	{
		FDustRenorm Out;
		double Haze = Beta - DustRayleighGreenPerKm;
		Haze = Haze > 0.0 ? Haze : 0.0;
		const double Grown = MieBefore * FRh;
		const double Want = Grown + GroundPerKmRow;
		double Scale = 1.0;
		if (Want > 0.0 && Haze / Want < 1.0)
		{
			Scale = Haze / Want;
		}
		Out.Scale = Scale;
		Out.MieAfter = Grown * Scale;
		Out.SecondGroundPerKm = GroundPerKmRow * Scale;
		Out.SecondDensity = DensityRow * Scale;
		double Ff = Beta > 0.0 ? FogFactorBefore - (Out.MieAfter - MieBefore + Out.SecondGroundPerKm) / Beta : 0.0;
		Out.FogFactorAfter = Ff > 0.0 ? Ff : 0.0;
		const double Total = Out.MieAfter + Out.SecondGroundPerKm + Out.FogFactorAfter * Beta;
		Out.VisibilityModelKm = Total > 0.0 ? DustKoschmieder / Total : 0.0;
		return Out;
	}
}
// FLIGHTSIM-DUSTHAZE-PURE-END

namespace
{
	TSharedPtr<FJsonObject> DustHazeObject(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
	{
		const TSharedPtr<FJsonObject>* Out = nullptr;
		if (Object.IsValid() && Object->TryGetObjectField(Key, Out) && Out != nullptr)
		{
			return *Out;
		}
		return nullptr;
	}

	bool DustHazeNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double& Out)
	{
		return Object.IsValid() && Object->HasTypedField<EJson::Number>(Key) && Object->TryGetNumberField(Key, Out);
	}

	// The METAR present-weather words without their intensity, proximity or
	// descriptor prefixes (+, -, VC, BL, DR), upper case.
	TArray<FString> DustHazeCodes(const TSharedPtr<FJsonObject>& Look, const TSharedPtr<FJsonObject>& Weather)
	{
		TArray<FString> Raw;
		for (const TSharedPtr<FJsonObject>& From : {Look, Weather})
		{
			// The first block that names present_weather is used, even when empty
			// (dust_haze.card_inputs: look's, else weather's).
			if (!From.IsValid() || !From->HasField(TEXT("present_weather")))
			{
				continue;
			}
			const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
			FString Text;
			if (From->TryGetArrayField(TEXT("present_weather"), Array) && Array != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& V : *Array)
				{
					FString Word;
					if (V.IsValid() && V->TryGetString(Word))
					{
						Raw.Add(Word);
					}
				}
			}
			else if (From->TryGetStringField(TEXT("present_weather"), Text))
			{
				Text.ParseIntoArrayWS(Raw);
			}
			break;
		}
		TArray<FString> Out;
		static const TCHAR* const Prefixes[] = {TEXT("+"), TEXT("-"), TEXT("VC"), TEXT("BL"), TEXT("DR")};
		for (FString Word : Raw)
		{
			Word = Word.TrimStartAndEnd().ToUpper();
			bool bChanged = true;
			while (bChanged)
			{
				bChanged = false;
				for (const TCHAR* Prefix : Prefixes)
				{
					const int32 Len = FCString::Strlen(Prefix);
					if (Word.StartsWith(Prefix, ESearchCase::CaseSensitive) && Word.Len() > Len)
					{
						Word = Word.RightChop(Len);
						bChanged = true;
					}
				}
			}
			Out.Add(Word);
		}
		return Out;
	}

	bool DustHazeAnyCode(const TArray<FString>& Words, std::initializer_list<const TCHAR*> Codes)
	{
		for (const FString& Word : Words)
		{
			for (const TCHAR* Code : Codes)
			{
				if (Word.StartsWith(Code, ESearchCase::CaseSensitive))
				{
					return true;
				}
			}
		}
		return false;
	}

	double DustHazeMagnusRhPct(double TemperatureC, double DewPointC)
	{
		auto Es = [](double T) { return 6.112 * std::exp(17.62 * T / (243.12 + T)); };
		const double Rh = 100.0 * Es(FMath::Min(DewPointC, TemperatureC)) / Es(TemperatureC);
		return FMath::Min(Rh, 100.0);
	}

	TArray<TSharedPtr<FJsonValue>> DustHazeTriple(double A, double B, double C)
	{
		return {MakeShared<FJsonValueNumber>(A), MakeShared<FJsonValueNumber>(B), MakeShared<FJsonValueNumber>(C)};
	}
}

void FFlightSimDustHaze::Apply(UWorld* World, FFlightSimVisualScene& Scene, const TCHAR* Params,
                               const TSharedPtr<FJsonObject>& Card, double VisibilityKm,
                               const TSharedPtr<FJsonObject>& AtmosphereRecord, TSharedPtr<FJsonObject>& Out)
{
	// Function-local: unity builds merge anonymous namespaces.
	using namespace FlightSimDustHazePure;
	Out = MakeShared<FJsonObject>();
	bSecondLayer = false;
	Out->SetBoolField(TEXT("pixel_moving"), false);
	Out->SetStringField(TEXT("calibration"),
		TEXT("UNCALIBRATED: every DUST_ROWS value, RH_GAMMA, the inversion height and the second fog "
		     "density are set by probe render on the render machine (docs/visual/PROBE_LOG.md "
		     "## dust-humidity-haze; core/scene/dust_haze.py is the table)"));

	// -dust-haze=off (or FLIGHTSIM_DUST_HAZE=off): the probe's A/B switch.
	FString Switch;
	if (!FParse::Value(Params, TEXT("dust-haze="), Switch) || Switch.IsEmpty())
	{
		Switch = FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_DUST_HAZE")).TrimStartAndEnd();
	}
	if (Switch.Equals(TEXT("off"), ESearchCase::IgnoreCase))
	{
		Out->SetStringField(TEXT("applied"), TEXT("nothing: -dust-haze=off"));
		return;
	}
	USkyAtmosphereComponent* Atmosphere = Scene.Atmosphere;
	if (World == nullptr || Atmosphere == nullptr || !Atmosphere->IsVisible())
	{
		Out->SetStringField(TEXT("applied"), TEXT("nothing: no visible sky atmosphere (-NoAerialPerspective)"));
		return;
	}

	// -- the card (core/scene/dust_haze.py card_inputs, the same order) -------
	TSharedPtr<FJsonObject> Look = DustHazeObject(Card, TEXT("look"));
	if (!Look.IsValid())
	{
		Look = DustHazeObject(DustHazeObject(Card, TEXT("randomization")), TEXT("look"));
	}
	const TSharedPtr<FJsonObject> Weather = DustHazeObject(Card, TEXT("weather"));
	const TSharedPtr<FJsonObject> Stated = DustHazeObject(DustHazeObject(Card, TEXT("atmosphere_properties")),
	                                                      TEXT("stated"));
	double RhPct = 0.0;
	FString RhBasis = TEXT("card");
	if (!DustHazeNumber(Look, TEXT("rh_pct"), RhPct) && !DustHazeNumber(Weather, TEXT("rh_pct"), RhPct) &&
	    !DustHazeNumber(DustHazeObject(Stated, TEXT("relative_humidity_pct")), TEXT("value"), RhPct))
	{
		double DewC = 0.0, DeltaC = 0.0;
		if (DustHazeNumber(DustHazeObject(Stated, TEXT("dew_point_c")), TEXT("value"), DewC))
		{
			DustHazeNumber(DustHazeObject(Stated, TEXT("temperature_deviation_c")), TEXT("value"), DeltaC);
			RhPct = DustHazeMagnusRhPct(15.0 + DeltaC, DewC);
		}
		else
		{
			RhPct = DustDefaultRhPct;
			RhBasis = TEXT("default");
		}
	}
	FString Surface;
	const TSharedPtr<FJsonObject> WeatherLook = DustHazeObject(Card, TEXT("weather_look"));
	if (WeatherLook.IsValid())
	{
		WeatherLook->TryGetStringField(TEXT("surface"), Surface);
	}
	const TArray<FString> Codes = DustHazeCodes(Look, Weather);

	// The row: weather.dust (or look.dust) first, then a dust code, a desert
	// surface, a haze code; else none.
	int32 Row = DustRowNone;
	FString RowBasis = TEXT("none of the card's words select dust or haze");
	TSharedPtr<FJsonObject> DustFrom = Weather.IsValid() && Weather->HasField(TEXT("dust")) ? Weather
		: (Look.IsValid() && Look->HasField(TEXT("dust")) ? Look : nullptr);
	// A null dust is unstated (dust_haze.card_inputs: weather.get("dust") is
	// None): the codes and the surface decide.
	if (DustFrom.IsValid() && DustFrom->HasTypedField<EJson::Null>(TEXT("dust")))
	{
		DustFrom = nullptr;
	}
	if (DustFrom.IsValid())
	{
		bool bDust = false;
		FString Word;
		if (DustFrom->TryGetBoolField(TEXT("dust"), bDust))
		{
			Row = bDust ? DustRowDust : DustRowNone;
		}
		else if (DustFrom->TryGetStringField(TEXT("dust"), Word))
		{
			Word = Word.TrimStartAndEnd().ToLower();
			Row = Word == TEXT("dust") ? DustRowDust : (Word == TEXT("haze") ? DustRowHaze : DustRowNone);
			if (Word != TEXT("dust") && Word != TEXT("haze") && Word != TEXT("none"))
			{
				Out->SetStringField(TEXT("unknown_dust_word"), Word);
			}
		}
		RowBasis = TEXT("the card's dust word");
	}
	else if (DustHazeAnyCode(Codes, {TEXT("DU"), TEXT("SA"), TEXT("DS"), TEXT("SS"), TEXT("PO")}))
	{
		Row = DustRowDust;
		RowBasis = TEXT("a METAR dust or sand code");
	}
	else if (Surface.Equals(TEXT("desert"), ESearchCase::IgnoreCase))
	{
		Row = DustRowDust;
		RowBasis = TEXT("the desert surface");
	}
	else if (DustHazeAnyCode(Codes, {TEXT("HZ"), TEXT("FU"), TEXT("BR")}))
	{
		Row = DustRowHaze;
		RowBasis = TEXT("a METAR haze, smoke or mist code");
	}
	const int32 Aerosol = Row == DustRowDust ? AerosolDust
		: (Surface.Equals(TEXT("ocean"), ESearchCase::IgnoreCase) ? AerosolMaritime : AerosolContinental);
	const double Rh = FMath::Clamp(RhPct / 100.0, 0.0, 1.0);
	const double Gamma = RhGamma(Aerosol);
	const double FRh = DustGrowthFactor(Rh, Gamma);
	double InversionM = DustDefault(Row, DhInversionM);
	if (!DustHazeNumber(Look, TEXT("inversion_height_m"), InversionM))
	{
		DustHazeNumber(Weather, TEXT("inversion_height_m"), InversionM);
	}

	Out->SetStringField(TEXT("row"), ANSI_TO_TCHAR(DustRowName(Row)));
	Out->SetStringField(TEXT("row_basis"), RowBasis);
	Out->SetStringField(TEXT("aerosol"), ANSI_TO_TCHAR(AerosolName(Aerosol)));
	Out->SetNumberField(TEXT("rh"), Rh);
	Out->SetNumberField(TEXT("rh_pct"), RhPct);
	Out->SetStringField(TEXT("rh_basis"), RhBasis);
	Out->SetNumberField(TEXT("gamma"), Gamma);
	Out->SetNumberField(TEXT("f_rh"), FRh);
	Out->SetNumberField(TEXT("inversion_height_m"), InversionM);

	// The fog the scene built (FlightSimVisualScene.cpp spawns one): the second
	// layer goes on the first visible one; the density ratio on every one the
	// preset's split scaled.
	TArray<UExponentialHeightFogComponent*> Fogs;
	for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
	{
		UExponentialHeightFogComponent* Fog = *It;
		if (Fog != nullptr && Fog->GetWorld() == World && Fog->IsVisible())
		{
			Fogs.Add(Fog);
		}
	}
	const double FogZM = Fogs.Num() > 0 ? Fogs[0]->GetComponentLocation().Z / 100.0 : 0.0;
	const double OffsetM = InversionM - FogZM;
	const double DensityRow = DustDefault(Row, DhSecondDensity);
	const double Falloff = DustDefault(Row, DhSecondFalloff);
	// The ground is the scene datum, world Z 0 (as the cloud layers' heights).
	const double GroundPerKmRow = 1000.0 * DustSecondExtinctionPerM(DensityRow, Falloff, OffsetM, -FogZM);

	// -- the Mie: grown and renormalised to the card's visibility ------------
	double Beta = 0.0, MieScat = 0.0, MieAbs = 0.0, FogFactorBefore = 0.0;
	const bool bSplit = VisibilityKm > 0.0 &&
		DustHazeNumber(AtmosphereRecord, TEXT("koschmieder_beta_per_km"), Beta) &&
		DustHazeNumber(AtmosphereRecord, TEXT("mie_scattering_scale_per_km"), MieScat) &&
		DustHazeNumber(AtmosphereRecord, TEXT("mie_absorption_scale_per_km"), MieAbs) &&
		DustHazeNumber(AtmosphereRecord, TEXT("fog_factor"), FogFactorBefore);
	double SecondDensityOut = DensityRow;
	double SecondGroundPerKm = GroundPerKmRow;
	double FogRatio = 1.0;
	double MieAbsorptionGreen = Atmosphere->MieAbsorptionScale;
	if (bSplit)
	{
		const double MieBefore = MieScat + MieAbs;
		const FDustRenorm R = DustRenormalise(Beta, MieBefore, FogFactorBefore, FRh, DensityRow, GroundPerKmRow);
		Atmosphere->SetMieScatteringScale(static_cast<float>(R.MieAfter * DustMieSingleScatterAlbedo));
		MieAbsorptionGreen = R.MieAfter * (1.0 - DustMieSingleScatterAlbedo);
		SecondDensityOut = R.SecondDensity;
		SecondGroundPerKm = R.SecondGroundPerKm;
		FogRatio = FogFactorBefore > 0.0 ? R.FogFactorAfter / FogFactorBefore : 0.0;
		Out->SetNumberField(TEXT("visibility_target_km"), VisibilityKm);
		Out->SetNumberField(TEXT("visibility_model_km"), R.VisibilityModelKm);
		Out->SetNumberField(TEXT("koschmieder_beta_per_km"), Beta);
		Out->SetNumberField(TEXT("mie_before"), MieBefore);
		Out->SetNumberField(TEXT("mie_after"), R.MieAfter);
		Out->SetNumberField(TEXT("fog_factor_before"), FogFactorBefore);
		Out->SetNumberField(TEXT("fog_factor_after"), R.FogFactorAfter);
		Out->SetNumberField(TEXT("renormalised"), R.Scale);
		Out->SetStringField(TEXT("mie_basis"), TEXT("grown by f(RH), renormalised to the card's visibility"));
	}
	else
	{
		Out->SetField(TEXT("visibility_target_km"), MakeShared<FJsonValueNull>());
		Out->SetField(TEXT("visibility_model_km"), MakeShared<FJsonValueNull>());
		Out->SetNumberField(TEXT("mie_before"), Atmosphere->MieScatteringScale + Atmosphere->MieAbsorptionScale);
		Out->SetNumberField(TEXT("mie_after"), Atmosphere->MieScatteringScale + Atmosphere->MieAbsorptionScale);
		Out->SetStringField(TEXT("mie_basis"),
			TEXT("kept: no visibility_km on the card, or the -aerosol= probe set the Mie scale"));
	}
	Out->SetNumberField(TEXT("fog_density_ratio"), FogRatio);

	// -- the dust tint: warm Mie absorption, other absorption, fog albedo ----
	// The colour's green keeps the visibility-matched amount; the colour is
	// normalised to its largest channel and the scale carries the rest.
	const double AbsR = DustDefault(Row, DhMieAbsR) / DustDefault(Row, DhMieAbsG);
	const double AbsB = DustDefault(Row, DhMieAbsB) / DustDefault(Row, DhMieAbsG);
	const double AbsMax = FMath::Max3(AbsR, 1.0, AbsB);
	if (Row != DustRowNone || bSplit)
	{
		Atmosphere->SetMieAbsorption(FLinearColor(static_cast<float>(AbsR / AbsMax), static_cast<float>(1.0 / AbsMax),
		                                          static_cast<float>(AbsB / AbsMax)));
		Atmosphere->SetMieAbsorptionScale(static_cast<float>(MieAbsorptionGreen * AbsMax));
	}
	Out->SetArrayField(TEXT("mie_absorption_rgb"), DustHazeTriple(AbsR, 1.0, AbsB));
	Out->SetNumberField(TEXT("mie_absorption_green_per_km"), MieAbsorptionGreen);
	const FColor Albedo(static_cast<uint8>(DustDefault(Row, DhAlbedoR)), static_cast<uint8>(DustDefault(Row, DhAlbedoG)),
	                    static_cast<uint8>(DustDefault(Row, DhAlbedoB)));
	if (Row != DustRowNone)
	{
		Atmosphere->SetOtherAbsorption(FLinearColor(static_cast<float>(DustDefault(Row, DhOtherAbsR)),
		                                            static_cast<float>(DustDefault(Row, DhOtherAbsG)),
		                                            static_cast<float>(DustDefault(Row, DhOtherAbsB))));
		Atmosphere->SetOtherAbsorptionScale(static_cast<float>(DustDefault(Row, DhOtherAbsScale)));
		Out->SetArrayField(TEXT("other_absorption_rgb"),
			DustHazeTriple(DustDefault(Row, DhOtherAbsR), DustDefault(Row, DhOtherAbsG), DustDefault(Row, DhOtherAbsB)));
		Out->SetNumberField(TEXT("other_absorption_scale"), DustDefault(Row, DhOtherAbsScale));
	}
	else
	{
		Out->SetStringField(TEXT("other_absorption"), TEXT("kept: the none row tints nothing"));
	}

	// -- the fogs: the main fog gives up what the overlay took; the second
	// layer sits at the inversion ---------------------------------------------
	TArray<TSharedPtr<FJsonValue>> FogRows;
	for (int32 Index = 0; Index < Fogs.Num(); ++Index)
	{
		UExponentialHeightFogComponent* Fog = Fogs[Index];
		TSharedPtr<FJsonObject> FogRow = MakeShared<FJsonObject>();
		FogRow->SetNumberField(TEXT("fog_density_before"), Fog->FogDensity);
		Fog->SetFogDensity(static_cast<float>(Fog->FogDensity * FogRatio));
		FogRow->SetNumberField(TEXT("fog_density_after"), Fog->FogDensity);
		if (Row != DustRowNone)
		{
			Fog->SetVolumetricFogAlbedo(Albedo);
			FogRow->SetStringField(TEXT("volumetric_fog_albedo_srgb"),
				FString::Printf(TEXT("%d,%d,%d"), Albedo.R, Albedo.G, Albedo.B));
		}
		if (Index == 0 && SecondDensityOut > 0.0)
		{
			FExponentialHeightFogData Second;
			Second.FogDensity = static_cast<float>(SecondDensityOut);
			Second.FogHeightFalloff = static_cast<float>(Falloff);
			Second.FogHeightOffset = static_cast<float>(OffsetM * 100.0);
			Fog->SetSecondFogData(Second);
			bSecondLayer = true;
			SecondDensity = SecondDensityOut;
			SecondFalloff = Falloff;
			InversionZM = FogZM + OffsetM;
			FogBaseZM = FogZM;
		}
		FogRows.Add(MakeShared<FJsonValueObject>(FogRow));
	}
	Out->SetArrayField(TEXT("height_fog"), FogRows);
	{
		TSharedPtr<FJsonObject> Second = MakeShared<FJsonObject>();
		Second->SetNumberField(TEXT("density"), bSecondLayer ? SecondDensityOut : 0.0);
		Second->SetNumberField(TEXT("falloff"), Falloff);
		Second->SetNumberField(TEXT("offset_m"), OffsetM);
		Second->SetNumberField(TEXT("fog_z_m"), FogZM);
		Second->SetNumberField(TEXT("ground_extinction_per_km"), bSecondLayer ? SecondGroundPerKm : 0.0);
		Second->SetBoolField(TEXT("drawn"), bSecondLayer);
		Second->SetStringField(TEXT("shape"),
			TEXT("the engine's exponential fog, not a slab: density doubles every 1/(falloff x 0.1) m below the "
			     "inversion and halves as fast above it"));
		Out->SetObjectField(TEXT("second_fog"), Second);
	}
	Out->SetStringField(TEXT("subject_transmittance"),
		bSecondLayer ? TEXT("per frame: world_beauty.frames[].cloud_path, layer dust_haze_second_fog")
		             : TEXT("1: no second layer is drawn"));
	Out->SetStringField(TEXT("labels"),
		TEXT("values only: nothing moves a pixel; the second layer's camera-to-aircraft transmittance is a "
		     "cloud_path row each frame, flagged (cloud_occludes_aircraft) under the occlusion threshold"));
	Out->SetBoolField(TEXT("applied"), true);
	UE_LOG(LogFlightSimDustHaze, Display, TEXT("dust haze: row %s, RH %.0f%% f(RH) %.3f, second layer %s"),
	       ANSI_TO_TCHAR(DustRowName(Row)), RhPct, FRh, bSecondLayer ? TEXT("on") : TEXT("off"));
}

TSharedPtr<FJsonObject> FFlightSimDustHaze::FrameRow(const FVector& CameraCm, const FVector& AircraftCm,
                                                     double FlagTransmittance, bool& bFlagged) const
{
	// Function-local: unity builds merge anonymous namespaces.
	using namespace FlightSimDustHazePure;
	bFlagged = false;
	if (!bSecondLayer)
	{
		return nullptr;
	}
	const double AZ = CameraCm.Z / 100.0;
	const double BZ = AircraftCm.Z / 100.0;
	const double LengthM = FVector::Distance(CameraCm, AircraftCm) / 100.0;
	const double Tau = DustSecondTau(SecondDensity, SecondFalloff, InversionZM, AZ, BZ, LengthM);
	const double Transmittance = std::exp(-Tau);
	bFlagged = Transmittance < FlagTransmittance;
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	Row->SetStringField(TEXT("layer"), TEXT("dust_haze_second_fog"));
	// The path below the inversion, from the fog actor (or the lower end) up:
	// core/scene/dust_haze.py subject_occlusion's path_m, the clouds' key.
	Row->SetNumberField(TEXT("path_m"),
		DustSlabPathM(AZ, BZ, LengthM, FMath::Min3(AZ, BZ, FogBaseZM), InversionZM));
	Row->SetNumberField(TEXT("tau"), Tau);
	Row->SetNumberField(TEXT("transmittance"), Transmittance);
	Row->SetBoolField(TEXT("flagged"), bFlagged);
	return Row;
}
