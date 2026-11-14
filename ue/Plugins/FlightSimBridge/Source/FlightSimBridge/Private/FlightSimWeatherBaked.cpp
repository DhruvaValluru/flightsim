// maxpick/rain (2026-11-13): the storm weather's baked tier 0, BEAUTY ONLY.
//
//  * -rain-layers=on: the falling rain as three baked layers in one post-process
//    pass (M_RainLayers, assets/shaders/weather/rain_layers.hlsl) instead of the
//    262,144 particle drops (BuildRain skips the mesh). Swarm lane
//    weather_fx.rain_drops.storm, tier 0; textures assets/looks/rain_layers/.
//  * -windscreen-baked=on: a cockpit camera's glass with the drops' optics baked
//    (M_WindshieldRainBaked, windshield_baked.hlsl: two texture taps, no loop)
//    instead of M_WindshieldRain's hashed loop. Swarm lane
//    weather_fx.windscreen_water.storm, tier 0; textures assets/looks/windscreen_water/.
//
// Both default OFF, read only on a beauty run (the command line or
// FLIGHTSIM_RENDER_SWITCHES, FlightSimRenderCommandlet.cpp). Both are post-process
// blendables on the BEAUTY capture only: no label capture receives a look blendable
// (ConfigureLabelCapture copies nothing from the beauty; tests/test_beauty_label_isolation.py),
// the particle drops they replace were beauty-only actors, so mask, class and depth are
// byte-identical with either switch on or off. Recorded in look_applied.weather.
//
// The constants below are the bakes' (assets/looks/rain_layers/rain_layers.json,
// assets/looks/windscreen_water/windscreen_water_storm.json), pinned by
// tests/test_rain_layers_windscreen_baked.py. UNCOMPILED here (no engine on the Mac);
// UNMEASURED: no frame rendered.

#include "FlightSimWeather.h"

#include "Components/SceneCaptureComponent2D.h"
#include "Dom/JsonObject.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/Parse.h"

namespace
{
	// Named distinctly from the sibling files' constants (unity builds merge the
	// anonymous namespaces into one translation unit).
	const TCHAR* const WeatherBakedRainLayersPath = TEXT("/Game/FlightSim/M_RainLayers.M_RainLayers");
	const TCHAR* const WeatherBakedWindscreenPath =
		TEXT("/Game/FlightSim/M_WindshieldRainBaked.M_WindshieldRainBaked");
	constexpr double WeatherBakedCmPerMetre = 100.0;

	// -- the rain layers (rain_layers.json) ---------------------------------------
	// bins[].sweep_m: the D0 drop's sweep each channel was baked at (R, G, B, A).
	constexpr double WeatherBakedBinSweepM[4] = {0.007074202, 0.052478989, 0.471613455, 1.886453821};
	// layers[].tile_height_m: one tile's length along the axis at rho_k.
	constexpr double WeatherBakedTileHeightM[3] = {1.813799, 5.130199, 13.246118};
	// physics.density_drawn_per_m3: the drops per m^3 the bake drew (50 mm/h at 2000 m).
	constexpr double WeatherBakedDensityPerM3 = 691.476949423;
	// Axis within 1 degree of vertical: AxisRight is the local east (cos 1 deg).
	constexpr double WeatherBakedVerticalCos = 0.999847695;

	// -- the windscreen (windscreen_water_storm.json, make_windscreen_water.host_wet) --
	constexpr double WeatherBakedTanMax = 0.881413;           // optics.tan_max
	constexpr double WeatherBakedTileM = 0.134715063;         // geometry.tile_mm / 1000
	constexpr double WeatherBakedMeanCapAreaM2 = 3.4038649146791016e-06;   // drops.mean_cap_area_m2
	constexpr double WeatherBakedMaxCover = 0.3;              // drops.max_cover
	constexpr double WeatherBakedASpan = 0.75;                // shader.a_span
	constexpr double WeatherBakedVShedMps = 22.0;             // law.v_shed_mps (rain_field.V_SHED_MPS)
	// FlightSimWeather.cpp WeatherGlassStaticLifeS: the static lifetime the glass already has.
	constexpr double WeatherBakedGlassLifeS = 6.0;
	// drops.density_to_cover: (Density, the share of the glass it shows), 16 rows.
	constexpr int32 WeatherBakedCoverRows = 16;
	constexpr double WeatherBakedCoverDensity[WeatherBakedCoverRows] = {
		0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75};
	constexpr double WeatherBakedCoverShare[WeatherBakedCoverRows] = {
		0.0, 0.00445, 0.0191, 0.03615, 0.05173, 0.06797, 0.0867, 0.10664, 0.12592, 0.14579,
		0.1658, 0.1873, 0.21098, 0.23486, 0.26071, 0.28931};

	FLinearColor WeatherBakedColour(const FVector& V, double W = 0.0)
	{
		return FLinearColor(static_cast<float>(V.X), static_cast<float>(V.Y), static_cast<float>(V.Z),
		                    static_cast<float>(W));
	}

	// numpy.interp over the cover table: the Density that shows Cover (clamped at the ends).
	double WeatherBakedDensityForCover(double Cover)
	{
		if (Cover <= WeatherBakedCoverShare[0])
		{
			return WeatherBakedCoverDensity[0];
		}
		for (int32 I = 1; I < WeatherBakedCoverRows; ++I)
		{
			if (Cover <= WeatherBakedCoverShare[I])
			{
				const double Span = WeatherBakedCoverShare[I] - WeatherBakedCoverShare[I - 1];
				const double T = Span > 0.0 ? (Cover - WeatherBakedCoverShare[I - 1]) / Span : 0.0;
				return WeatherBakedCoverDensity[I - 1]
					+ T * (WeatherBakedCoverDensity[I] - WeatherBakedCoverDensity[I - 1]);
			}
		}
		return WeatherBakedCoverDensity[WeatherBakedCoverRows - 1];
	}
}

bool FFlightSimWeather::ParseBakedSwitch(const FString& Switches, const TCHAR* Key, bool& bOut, FString& Error)
{
	FString Value = TEXT("off");
	FParse::Value(*Switches, Key, Value);
	if (Value != TEXT("on") && Value != TEXT("off"))
	{
		Error = FString::Printf(TEXT("weather.baked_switch: -%s%s is not on or off"), Key, *Value);
		return false;
	}
	bOut = Value == TEXT("on");
	return true;
}

bool FFlightSimWeather::ApplyRainLayers(USceneCaptureComponent2D* Beauty, FString& Error)
{
	if (!bRainLayers || !bRain || Beauty == nullptr)
	{
		return true;
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherBakedRainLayersPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.rain_layers: %s (scripts/ue_create_materials.py "
		                             "create_rain_layers) did not load; -rain-layers=on draws the baked "
		                             "layers or refuses (run the materials prep, or -rain-layers=off)"),
		                        WeatherBakedRainLayersPath);
		return false;
	}
	RainLayersMaterial = UMaterialInstanceDynamic::Create(Material, Beauty);
	RainLayersMaterial->SetScalarParameterValue(TEXT("Opacity"), 0.0f);   // Advance sets the frame's
	Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, RainLayersMaterial));
	RainLayersPhase = FVector::ZeroVector;
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("material"), WeatherBakedRainLayersPath);
	Row->SetStringField(TEXT("applied_to"), TEXT("beauty (a post-process blendable; no label capture)"));
	Row->SetStringField(TEXT("tier"), TEXT("0: no particles, three baked 512x1024 layers (0.5-10 m)"));
	Row->SetStringField(TEXT("textures"), TEXT("assets/looks/rain_layers (scripts/make_rain_layers.py, PIN.json)"));
	Row->SetNumberField(TEXT("lift"), 0.35);
	Row->SetStringField(TEXT("status"), TEXT("UNMEASURED: the A/B against the particle drops is on the render box"));
	if (Record.IsValid())
	{
		Record->SetObjectField(TEXT("rain_layers"), Row);
	}
	UE_LOG(LogTemp, Display, TEXT("weather: -rain-layers=on, M_RainLayers on the beauty capture (no particles)"));
	return true;
}

void FFlightSimWeather::StepRainLayers(const FVector& Wind, const FVector& CamVel, double Share, double Shutter,
                                       double Dt, double PixelAngle)
{
	if (RainLayersMaterial == nullptr)
	{
		return;
	}
	// The D0 drop relative to the camera (engine cm/s): the wind, its fall, the camera's
	// motion as Advance passes it (the cinematic share of it).
	const double FallCmps = TerminalVelocityMps(D0Mm) * FallSpeedFactor * WeatherBakedCmPerMetre;
	const FVector Relative = Wind - FVector(0.0, 0.0, FallCmps) - CamVel;
	const double SpeedMps = Relative.Size() / WeatherBakedCmPerMetre;
	const FVector Axis = SpeedMps > 1.0e-6 ? Relative.GetSafeNormal() : FVector(0.0, 0.0, -1.0);
	FVector Right = FMath::Abs(Axis.Z) > WeatherBakedVerticalCos ? EastAxis
		: FVector::CrossProduct(Axis, FVector(0.0, 0.0, 1.0)).GetSafeNormal();
	if (Right.IsNearlyZero())
	{
		Right = FVector(1.0, 0.0, 0.0);
	}
	// The bin nearest the sweep in log, and the residual stretch (make_rain_layers.py bins).
	const double SweepM = FMath::Max(SpeedMps * Shutter, 1.0e-5);
	int32 Nearest = 0;
	double Best = TNumericLimits<double>::Max();
	for (int32 Bin = 0; Bin < 4; ++Bin)
	{
		const double Distance = FMath::Abs(FMath::Log2(SweepM / WeatherBakedBinSweepM[Bin]));
		if (Distance < Best)
		{
			Best = Distance;
			Nearest = Bin;
		}
	}
	const double Stretch = SweepM / WeatherBakedBinSweepM[Nearest];
	// Each layer's travel in its own tiles, wrapped: deterministic in the sim clock.
	if (Dt > 0.0)
	{
		for (int32 K = 0; K < 3; ++K)
		{
			RainLayersPhase[K] = FMath::Frac(RainLayersPhase[K] + SpeedMps * Dt / (WeatherBakedTileHeightM[K] * Stretch));
		}
	}
	// The card's drawn drops per m^3 over the bake's: the layers' coverage at the card's rate.
	const double BoxM3 = 8.0 * BoxHalfM.X * BoxHalfM.Y * BoxHalfM.Z;
	const double DensityRatio = BoxM3 > 0.0 ? Particles * Weight / BoxM3 / WeatherBakedDensityPerM3 : 1.0;
	const double Opacity = FMath::Clamp(RainGain * BeautyRainGain * Share * DensityRatio, 0.0, 100.0);
	FLinearColor Sel(0.0f, 0.0f, 0.0f, 0.0f);
	Sel.Component(Nearest) = 1.0f;
	RainLayersMaterial->SetVectorParameterValue(TEXT("Axis"), WeatherBakedColour(Axis));
	RainLayersMaterial->SetVectorParameterValue(TEXT("AxisRight"), WeatherBakedColour(Right));
	RainLayersMaterial->SetVectorParameterValue(TEXT("Sel"), Sel);
	RainLayersMaterial->SetScalarParameterValue(TEXT("Stretch"), static_cast<float>(Stretch));
	RainLayersMaterial->SetVectorParameterValue(TEXT("Phase"), WeatherBakedColour(RainLayersPhase));
	RainLayersMaterial->SetScalarParameterValue(TEXT("PixelAngle"), static_cast<float>(PixelAngle));
	RainLayersMaterial->SetScalarParameterValue(TEXT("Opacity"), static_cast<float>(Opacity));
	const TSharedPtr<FJsonObject>* Row = nullptr;
	if (Record.IsValid() && Record->TryGetObjectField(TEXT("rain_layers"), Row) && Row != nullptr && Row->IsValid())
	{
		(*Row)->SetNumberField(TEXT("density_ratio"), DensityRatio);
		(*Row)->SetNumberField(TEXT("last_opacity"), Opacity);
		(*Row)->SetNumberField(TEXT("last_sweep_m"), SweepM);
		(*Row)->SetNumberField(TEXT("last_bin"), Nearest);
		(*Row)->SetNumberField(TEXT("last_stretch"), Stretch);
	}
}

bool FFlightSimWeather::ApplyWindscreenBaked(USceneCaptureComponent2D* Beauty, double AirspeedMps, FString& Error)
{
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, WeatherBakedWindscreenPath);
	if (Material == nullptr)
	{
		Error = FString::Printf(TEXT("weather.windscreen_baked: %s (scripts/ue_create_materials.py "
		                             "create_windshield_rain_baked) did not load; -windscreen-baked=on draws "
		                             "the baked glass or refuses (run the materials prep, or -windscreen-baked=off)"),
		                        WeatherBakedWindscreenPath);
		return false;
	}
	// make_windscreen_water.host_wet on the card's glass numbers (rain_field.windshield): standing
	// drops a Poisson cover, capped, thinned above the shedding speed; the share shed feeds the tracks.
	const double V = FMath::Max(AirspeedMps, 0.0);
	const double Hold = V <= WeatherBakedVShedMps ? 1.0 : WeatherBakedVShedMps / V;
	const double Wetted = 1.0 - FMath::Exp(-WindshieldImpinge * WeatherBakedMeanCapAreaM2 * WeatherBakedGlassLifeS);
	const double Cover = FMath::Min(WeatherBakedMaxCover, Wetted) * Hold;
	const double DropDensity = WeatherBakedDensityForCover(Cover);
	const double TrackDensity = WeatherBakedASpan * (1.0 - Hold) * FMath::Min(1.0, Wetted / WeatherBakedMaxCover);
	const double HeadRate = WindshieldRunoffMps / WeatherBakedTileM;
	WindscreenWet = FVector(DropDensity, TrackDensity, HeadRate);
	WindscreenBakedMaterial = UMaterialInstanceDynamic::Create(Material, Beauty);
	WindscreenBakedMaterial->SetScalarParameterValue(TEXT("Time"), 0.0f);
	StepWindscreenBaked(0.0, 1.0e-3, Beauty->FOVAngle);
	Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, WindscreenBakedMaterial));
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("drawn_as"), TEXT("baked"));
	Row->SetStringField(TEXT("drawn_as"), TEXT("baked"));   // the A/B key (MAXPICK r87); "material" otherwise
	Row->SetStringField(TEXT("material"), WeatherBakedWindscreenPath);
	Row->SetStringField(TEXT("applied_to"), TEXT("beauty"));
	Row->SetNumberField(TEXT("impinge_per_m2_s"), WindshieldImpinge);
	Row->SetNumberField(TEXT("runoff_mps"), WindshieldRunoffMps);
	Row->SetNumberField(TEXT("airspeed_mps"), AirspeedMps);
	Row->SetNumberField(TEXT("standing_cover"), Cover);
	Row->SetNumberField(TEXT("drop_density"), DropDensity);
	Row->SetNumberField(TEXT("rivulet_density"), TrackDensity);
	Row->SetNumberField(TEXT("head_rate_tiles_per_s"), HeadRate);
	Row->SetStringField(TEXT("basis"),
		TEXT("-windscreen-baked=on: tier 0 of swarm lane weather_fx.windscreen_water.storm (256 maps, ")
		TEXT("assets/looks/windscreen_water); host_wet's law on the card's impingement and run-off; no water ")
		TEXT("film; UNMEASURED"));
	if (Record.IsValid())
	{
		Record->SetObjectField(TEXT("windshield"), Row);
	}
	return true;
}

void FFlightSimWeather::StepWindscreenBaked(double TimeS, double Shutter, double HorizontalFovDeg)
{
	if (WindscreenBakedMaterial == nullptr)
	{
		return;
	}
	// The trail from the shutter, a quarter tile at least (host_wet trail_tiles).
	const double Trail = FMath::Clamp(WindshieldRunoffMps * FMath::Max(Shutter, 0.0) / WeatherBakedTileM, 0.25, 1.0);
	const double HalfTan = FMath::Tan(FMath::DegreesToRadians(FMath::Clamp(HorizontalFovDeg, 1.0, 170.0)) * 0.5);
	WindscreenBakedMaterial->SetScalarParameterValue(TEXT("Time"), static_cast<float>(TimeS));
	WindscreenBakedMaterial->SetVectorParameterValue(TEXT("Wet"), WeatherBakedColour(WindscreenWet, Trail));
	WindscreenBakedMaterial->SetScalarParameterValue(TEXT("LensH"),
	                                                 static_cast<float>(WeatherBakedTanMax / (2.0 * HalfTan)));
}
