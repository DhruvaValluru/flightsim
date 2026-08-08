#include "FlightSimScenarioWorld.h"

#include "JSBSimMovementComponent.h"

#include "Async/TaskGraphInterfaces.h"
#include "Components/BoxComponent.h"
#include "Components/SceneComponent.h"
#include "Containers/Ticker.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/WorldSettings.h"
#include "GeoReferencingSystem.h"
#include "HAL/ThreadManager.h"
#include "Misc/FileHelper.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY(LogFlightSimScenario);

namespace
{
	constexpr double MetresToCentimetres = 100.0;
	constexpr double KnotsToMetresPerSecond = 0.514444;
	constexpr double RadiansToDegrees = 57.29577951308232;
	constexpr double FeetToMetres = 0.3048;

	// Achieved-condition tolerances. These are not comparison tolerances -- they
	// check that the aircraft was placed where the spec said, and they are far
	// tighter than the parity tolerances in experiments/gate5_ue_parity.py on
	// purpose. Getting the placement wrong by more than this and then comparing
	// trajectories would measure the placement error and call it physics.
	constexpr double AltitudeCheckMetres = 1.0;
	constexpr double AirspeedCheckKnots = 0.5;
	constexpr double AngleCheckDegrees = 0.5;
	constexpr double PositionCheckDegrees = 1e-4;   // ~11 m at the equator
	constexpr double AboveGroundCheckMetres = 10.0;

	bool ReadNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key,
	                double& Out, FString& Error)
	{
		if (!Object->TryGetNumberField(Key, Out))
		{
			Error = FString::Printf(TEXT("run card has no numeric field '%s'"), Key);
			return false;
		}
		return true;
	}

	bool ReadString(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key,
	                FString& Out, FString& Error)
	{
		if (!Object->TryGetStringField(Key, Out))
		{
			Error = FString::Printf(TEXT("run card has no string field '%s'"), Key);
			return false;
		}
		return true;
	}

	// Degrees, compared on the circle. 359.9 and 0.1 differ by 0.2, not 359.8.
	double AngleDifference(double A, double B)
	{
		double Difference = FMath::Fmod(A - B, 360.0);
		if (Difference > 180.0) { Difference -= 360.0; }
		if (Difference < -180.0) { Difference += 360.0; }
		return FMath::Abs(Difference);
	}
}

double FFlightSimScenarioWorld::ReadProperty(const TCHAR* Name) const
{
	if (Movement == nullptr)
	{
		return 0.0;
	}
	FString Value;
	Movement->CommandConsole(Name, FString(), Value);
	return Value.IsEmpty() ? 0.0 : FCString::Atod(*Value);
}

bool FFlightSimScenarioWorld::ReadCard(const FString& Path,
                                       FFlightSimScenarioCard& Out, FString& Error)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		Error = FString::Printf(TEXT("cannot read run card '%s'"), *Path);
		return false;
	}

	TSharedPtr<FJsonObject> Root;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		Error = FString::Printf(TEXT("run card '%s' is not valid JSON"), *Path);
		return false;
	}

	if (!ReadString(Root, TEXT("spec_digest"), Out.SpecDigest, Error)) { return false; }
	if (!ReadString(Root, TEXT("aircraft"), Out.Aircraft, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("altitude_m"), Out.AltitudeMetres, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("airspeed_kt"), Out.AirspeedKnots, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("heading_deg"), Out.HeadingDegrees, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("latitude_deg"), Out.LatitudeDegrees, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("longitude_deg"), Out.LongitudeDegrees, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("terrain_elevation_m"), Out.TerrainElevationMetres, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("duration_s"), Out.DurationSeconds, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("rate_hz"), Out.RateHz, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("sample_interval_s"), Out.SampleIntervalSeconds, Error)) { return false; }

	if (!Root->TryGetBoolField(TEXT("mass_held"), Out.bMassHeld))
	{
		Error = TEXT("run card has no boolean field 'mass_held'");
		return false;
	}

	// Optional: the engine-start mixture, computed and VERIFIED by the
	// headless host (the card builder cranks the same JSBSim at the card's
	// altitude and records a mixture that sustains combustion). Absent means
	// full rich, which is only correct near sea level for pistons -- see
	// VENDORED.json local patch 4.
	Out.EngineMixture = 1.0;
	Root->TryGetNumberField(TEXT("engine_mixture"), Out.EngineMixture);
	if (Out.EngineMixture <= 0.0 || Out.EngineMixture > 1.0)
	{
		Error = FString::Printf(
			TEXT("engine_mixture %.3f is outside (0, 1]"), Out.EngineMixture);
		return false;
	}

	// Conditions this host does not implement. Each one is refused rather than
	// approximated: a spec that asks for turbulence and silently gets still air
	// would make the parity comparison a comparison of two different scenarios,
	// which is worse than no comparison (§2.7).
	FString AirspeedKind;
	if (!ReadString(Root, TEXT("airspeed_kind"), AirspeedKind, Error)) { return false; }
	if (AirspeedKind != TEXT("cas"))
	{
		Error = FString::Printf(
			TEXT("spec commands %s airspeed. The UE plugin's only speed initial ")
			TEXT("condition is InitialCalibratedAirSpeedKts, so this host can set ")
			TEXT("calibrated airspeed and nothing else."), *AirspeedKind);
		return false;
	}

	// Turbulence (Phase 6B.3). A card asking for it must carry the exact
	// property writes the headless provider produced -- this host applies the
	// same floats rather than re-deriving them from the intensity word.
	// Whether a given commandlet ACCEPTS a turbulent card is that
	// commandlet's policy (the parity path refuses what parity has not been
	// established for); the card format itself is shared.
	if (!ReadString(Root, TEXT("turbulence"), Out.Turbulence, Error)) { return false; }
	if (Out.Turbulence != TEXT("none"))
	{
		const TSharedPtr<FJsonObject>* TurbulenceWrites = nullptr;
		if (!Root->TryGetObjectField(TEXT("turbulence_properties"), TurbulenceWrites)
		    || TurbulenceWrites == nullptr)
		{
			Error = FString::Printf(
				TEXT("spec requests %s turbulence but the card carries no ")
				TEXT("turbulence_properties block. This host refuses to derive ")
				TEXT("Dryden parameters from a word: the headless provider is the ")
				TEXT("single source of those numbers."), *Out.Turbulence);
			return false;
		}
		// Fixed write order, matching DrydenTurbulence.configure()'s dict
		// exactly. Iterating the JSON map would make the order an accident of
		// container internals, and property write order against a stateful
		// model is not something to leave to accident.
		const TCHAR* OrderedKeys[] = {
			TEXT("atmosphere/turb-type"),
			TEXT("atmosphere/randomseed"),
			TEXT("atmosphere/turbulence/milspec/severity"),
			TEXT("atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps"),
		};
		if ((*TurbulenceWrites)->Values.Num() != UE_ARRAY_COUNT(OrderedKeys))
		{
			Error = FString::Printf(
				TEXT("turbulence_properties carries %d entries; this host knows ")
				TEXT("exactly the 4 the Dryden provider writes. An extra or ")
				TEXT("missing property would be silently un-applied."),
				(*TurbulenceWrites)->Values.Num());
			return false;
		}
		for (const TCHAR* Key : OrderedKeys)
		{
			double Value = 0.0;
			if (!(*TurbulenceWrites)->TryGetNumberField(Key, Value))
			{
				Error = FString::Printf(
					TEXT("turbulence_properties is missing '%s'"), Key);
				return false;
			}
			Out.TurbulenceProperties.Add(Key);
			Out.TurbulenceValues.Add(FString::Printf(TEXT("%.17g"), Value));
			if (FCString::Strcmp(Key, TEXT("atmosphere/randomseed")) == 0)
			{
				Out.TurbulenceSeed = static_cast<int64>(Value);
			}
		}
		// The seed-saturation guard, re-checked at the door: JSBSim stores the
		// seed as a double and casts to int, so anything at or above INT_MAX
		// saturates and different seeds silently produce identical noise.
		if (Out.TurbulenceSeed < 0 || Out.TurbulenceSeed >= 2147483647LL)
		{
			Error = FString::Printf(
				TEXT("turbulence seed %lld is outside what JSBSim can represent ")
				TEXT("(0 to INT_MAX-1); values at the cap saturate and alias."),
				Out.TurbulenceSeed);
			return false;
		}
	}

	// Steady wind is implemented, not refused. The refusal this replaced said
	// "the headless host re-applies its wind provider every step; this host
	// would set it once as an initial condition" -- so now this host does both
	// things the headless host does: the plugin's wind IC makes the aircraft
	// trim *in* the wind, and Step() re-writes the same NED wind properties
	// the headless stack writes, every step, from the same conversion.
	if (!ReadNumber(Root, TEXT("wind_speed_kt"), Out.WindSpeedKnots, Error)) { return false; }
	if (!ReadNumber(Root, TEXT("wind_direction_deg"), Out.WindFromDegrees, Error)) { return false; }
	if (Out.WindSpeedKnots < 0.0)
	{
		Error = FString::Printf(TEXT("wind speed cannot be negative: %.3f kt"),
		                        Out.WindSpeedKnots);
		return false;
	}
	if (Out.WindSpeedKnots > 0.0 &&
	    Out.WindFromDegrees != FMath::RoundToDouble(Out.WindFromDegrees))
	{
		// The plugin's WindHeading initial condition is an int32, so a
		// fractional direction would be silently truncated at trim and then
		// flown exactly at run time -- two subtly different winds in one run.
		Error = FString::Printf(
			TEXT("wind direction %.4f deg is not a whole degree. The plugin's ")
			TEXT("wind initial condition is integral, so the trim would quietly ")
			TEXT("use a different direction than the run."), Out.WindFromDegrees);
		return false;
	}

	// Optional per-step wind schedule (gusts). The values are the headless
	// providers' own output -- steady wind plus 1-cosine gusts are pure
	// functions of time, so precomputing them in Python and writing the same
	// floats here means there is exactly one gust model, not two.
	const TArray<TSharedPtr<FJsonValue>>* Schedule = nullptr;
	if (Root->TryGetArrayField(TEXT("wind_schedule"), Schedule) && Schedule != nullptr)
	{
		double PreviousTime = -1.0;
		for (const TSharedPtr<FJsonValue>& Value : *Schedule)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if (!Value->TryGetObject(Entry) || Entry == nullptr)
			{
				Error = TEXT("wind_schedule must be a list of objects");
				return false;
			}
			double T = 0.0, N = 0.0, E = 0.0, D = 0.0;
			if (!ReadNumber(*Entry, TEXT("t_s"), T, Error) ||
			    !ReadNumber(*Entry, TEXT("north_fps"), N, Error) ||
			    !ReadNumber(*Entry, TEXT("east_fps"), E, Error) ||
			    !ReadNumber(*Entry, TEXT("down_fps"), D, Error))
			{
				return false;
			}
			if (T <= PreviousTime)
			{
				Error = TEXT("wind_schedule times must be strictly increasing");
				return false;
			}
			PreviousTime = T;
			Out.WindScheduleTimes.Add(T);
			Out.WindScheduleNorthFps.Add(N);
			Out.WindScheduleEastFps.Add(E);
			Out.WindScheduleDownFps.Add(D);
		}
	}

	// Optional orographic block (Phase 6B.2): wind over a real baked ridge
	// produces the updraughts and sink the headless physics models. All the
	// modelling parameters arrive computed; this host derives none of them.
	const TSharedPtr<FJsonObject>* Orographic = nullptr;
	if (Root->TryGetObjectField(TEXT("orographic"), Orographic) && Orographic != nullptr)
	{
		Out.bOrographic = true;
		if (!ReadString(*Orographic, TEXT("terrain"), Out.OrographicTerrainPath, Error) ||
		    !ReadNumber(*Orographic, TEXT("wind_speed_mps"), Out.OrographicWindSpeedMps, Error) ||
		    !ReadNumber(*Orographic, TEXT("wind_from_deg"), Out.OrographicWindFromDeg, Error) ||
		    !ReadNumber(*Orographic, TEXT("decay_height_m"), Out.OrographicDecayHeightMetres, Error) ||
		    !ReadNumber(*Orographic, TEXT("wavelength_m"), Out.OrographicWavelengthMetres, Error) ||
		    !ReadNumber(*Orographic, TEXT("origin_x_m"), Out.OrographicOriginXMetres, Error) ||
		    !ReadNumber(*Orographic, TEXT("origin_y_m"), Out.OrographicOriginYMetres, Error))
		{
			return false;
		}
		(*Orographic)->TryGetBoolField(TEXT("lee"), Out.bOrographicLee);
	}

	// Optional downburst block (Phase 7 2.3): the microburst field evaluated
	// at the aircraft's actual position, replacing the labeled nominal-track
	// delivery. Same projected local frame as the orographic field.
	const TSharedPtr<FJsonObject>* DownburstJson = nullptr;
	if (Root->TryGetObjectField(TEXT("downburst"), DownburstJson) && DownburstJson != nullptr)
	{
		Out.bDownburst = true;
		if (!ReadNumber(*DownburstJson, TEXT("origin_x_m"), Out.DownburstOriginXMetres, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("origin_y_m"), Out.DownburstOriginYMetres, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("centre_north_m"), Out.DownburstCentreNorthMetres, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("centre_east_m"), Out.DownburstCentreEastMetres, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("core_radius_m"), Out.DownburstCoreRadiusMetres, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("outflow_max_mps"), Out.DownburstOutflowMaxMps, Error) ||
		    !ReadNumber(*DownburstJson, TEXT("outflow_height_m"), Out.DownburstOutflowHeightMetres, Error))
		{
			return false;
		}
	}

	// Optional rotor block (Phase 7 1.3): per-step W20 coupled to the lee
	// sink. Requires the orographic block -- the rotor is ITS lee field.
	const TSharedPtr<FJsonObject>* RotorJson = nullptr;
	if (Root->TryGetObjectField(TEXT("rotor"), RotorJson) && RotorJson != nullptr)
	{
		Out.bRotor = true;
		if (!ReadNumber(*RotorJson, TEXT("sigma_gain"), Out.RotorSigmaGain, Error) ||
		    !ReadNumber(*RotorJson, TEXT("sigma_per_w20"), Out.RotorSigmaPerW20, Error) ||
		    !ReadNumber(*RotorJson, TEXT("w20_cap_fps"), Out.RotorW20CapFps, Error) ||
		    !ReadNumber(*RotorJson, TEXT("background_w20_fps"), Out.RotorBackgroundW20Fps, Error))
		{
			return false;
		}
		if (!Out.bOrographic)
		{
			Error = TEXT("rotor block without an orographic block: the rotor "
			             "is the orographic field's lee turbulence and cannot "
			             "exist without it");
			return false;
		}
	}

	// Optional log-profile block (Phase 7 2.1).
	const TSharedPtr<FJsonObject>* LogProfileJson = nullptr;
	if (Root->TryGetObjectField(TEXT("log_profile"), LogProfileJson) && LogProfileJson != nullptr)
	{
		Out.bLogProfile = true;
		if (!ReadNumber(*LogProfileJson, TEXT("reference_speed_mps"), Out.LogProfileReferenceSpeedMps, Error) ||
		    !ReadNumber(*LogProfileJson, TEXT("from_deg"), Out.LogProfileFromDegrees, Error) ||
		    !ReadNumber(*LogProfileJson, TEXT("reference_height_m"), Out.LogProfileReferenceHeightMetres, Error) ||
		    !ReadNumber(*LogProfileJson, TEXT("z0_m"), Out.LogProfileZ0Metres, Error) ||
		    !ReadNumber(*LogProfileJson, TEXT("surface_layer_top_m"), Out.LogProfileSurfaceLayerTopMetres, Error))
		{
			return false;
		}
	}

	// Optional thermals block (Phase 7 2.2): Allen's field, every position
	// drawn in Python from the spec seed and carried verbatim.
	const TSharedPtr<FJsonObject>* ThermalsJson = nullptr;
	if (Root->TryGetObjectField(TEXT("thermals"), ThermalsJson) && ThermalsJson != nullptr)
	{
		Out.bThermals = true;
		if (!ReadNumber(*ThermalsJson, TEXT("wstar_mps"), Out.ThermalsWstarMps, Error) ||
		    !ReadNumber(*ThermalsJson, TEXT("zi_m"), Out.ThermalsZiMetres, Error) ||
		    !ReadNumber(*ThermalsJson, TEXT("area_north_m"), Out.ThermalsAreaNorthMetres, Error) ||
		    !ReadNumber(*ThermalsJson, TEXT("area_east_m"), Out.ThermalsAreaEastMetres, Error) ||
		    !ReadNumber(*ThermalsJson, TEXT("origin_x_m"), Out.ThermalsOriginXMetres, Error) ||
		    !ReadNumber(*ThermalsJson, TEXT("origin_y_m"), Out.ThermalsOriginYMetres, Error))
		{
			return false;
		}
		const TArray<TSharedPtr<FJsonValue>>* Positions = nullptr;
		if (!(*ThermalsJson)->TryGetArrayField(TEXT("positions_m"), Positions) ||
		    Positions == nullptr || Positions->Num() == 0)
		{
			Error = TEXT("thermals block has no positions_m array");
			return false;
		}
		for (const TSharedPtr<FJsonValue>& Value : *Positions)
		{
			const TArray<TSharedPtr<FJsonValue>>* Pair = nullptr;
			if (!Value->TryGetArray(Pair) || Pair == nullptr || Pair->Num() != 2)
			{
				Error = TEXT("thermals positions_m entries must be [north, east] pairs");
				return false;
			}
			Out.ThermalNorthMetres.Add((*Pair)[0]->AsNumber());
			Out.ThermalEastMetres.Add((*Pair)[1]->AsNumber());
		}
	}

	// Optional W20 schedule (Phase 7 3.1). W20 fps ONLY: mid-run severity
	// changes deliver 2-5x the commanded sigma_w on this JSBSim build, and
	// per-step seed writes are the 515 g failure (JSBSIM_CORRECTIONS §9/§13).
	const TSharedPtr<FJsonObject>* TurbSchedule = nullptr;
	if (Root->TryGetObjectField(TEXT("turbulence_schedule"), TurbSchedule) && TurbSchedule != nullptr)
	{
		const TArray<TSharedPtr<FJsonValue>>* Times = nullptr;
		const TArray<TSharedPtr<FJsonValue>>* W20 = nullptr;
		if (!(*TurbSchedule)->TryGetArrayField(TEXT("times_s"), Times) || Times == nullptr ||
		    !(*TurbSchedule)->TryGetArrayField(TEXT("w20_fps"), W20) || W20 == nullptr ||
		    Times->Num() == 0 || Times->Num() != W20->Num())
		{
			Error = TEXT("turbulence_schedule needs equal-length times_s and w20_fps arrays");
			return false;
		}
		for (int32 i = 0; i < Times->Num(); ++i)
		{
			Out.TurbulenceScheduleTimes.Add((*Times)[i]->AsNumber());
			Out.TurbulenceScheduleW20Fps.Add((*W20)[i]->AsNumber());
		}
		if (Out.bRotor)
		{
			Error = TEXT("a card cannot carry both a rotor coupling and a W20 "
			             "schedule: both drive the same property");
			return false;
		}
	}
	Root->TryGetBoolField(TEXT("orographic_follow_schedule"), Out.bOrographicFollowSchedule);
	if (Out.bOrographicFollowSchedule &&
	    (!Out.bOrographic || Out.WindScheduleTimes.Num() == 0))
	{
		Error = TEXT("orographic_follow_schedule needs both an orographic block "
		             "and a wind schedule to follow");
		return false;
	}

	// Optional real heightfield collision (Phase 7 1.2).
	Root->TryGetStringField(TEXT("collision_terrain"), Out.CollisionTerrainPath);

	bool bHoldState = false;
	if (!Root->TryGetBoolField(TEXT("hold_state"), bHoldState))
	{
		Error = TEXT("run card has no boolean field 'hold_state'");
		return false;
	}
	if (bHoldState)
	{
		Error = TEXT(
			"spec commands a held state. The headless host closes that loop with "
			"the TECS autopilot in core/control; this host has no autopilot and "
			"flies open loop from trim. Running one host closed-loop and the "
			"other open-loop would compare a controller against no controller.");
		return false;
	}

	// Optional. The parity scenario has none; the on-screen scenario needs a
	// roll input, because a roll nobody commanded is not evidence that a
	// commanded roll is visible.
	const TArray<TSharedPtr<FJsonValue>>* Inputs = nullptr;
	if (Root->TryGetArrayField(TEXT("control_inputs"), Inputs) && Inputs != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Inputs)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if (!Value->TryGetObject(Entry) || Entry == nullptr)
			{
				Error = TEXT("control_inputs must be a list of objects");
				return false;
			}
			FFlightSimControlInput Input;
			if (!ReadNumber(*Entry, TEXT("t_s"), Input.TimeSeconds, Error)) { return false; }
			(*Entry)->TryGetNumberField(TEXT("aileron"), Input.Aileron);
			(*Entry)->TryGetNumberField(TEXT("elevator"), Input.Elevator);
			(*Entry)->TryGetNumberField(TEXT("rudder"), Input.Rudder);
			Out.ControlInputs.Add(Input);
		}
		// Applied by scanning forward, so out-of-order entries would silently
		// be skipped rather than reordered.
		for (int32 i = 1; i < Out.ControlInputs.Num(); ++i)
		{
			if (Out.ControlInputs[i].TimeSeconds < Out.ControlInputs[i - 1].TimeSeconds)
			{
				Error = TEXT("control_inputs must be in increasing order of t_s");
				return false;
			}
		}
	}

	if (Out.DurationSeconds <= 0.0 || Out.RateHz <= 0.0 || Out.SampleIntervalSeconds <= 0.0)
	{
		Error = TEXT("duration, rate and sample interval must all be positive");
		return false;
	}
	return true;
}

bool FFlightSimScenarioWorld::Build(const FFlightSimScenarioCard& Card, FString& Error)
{
	// A Game world with a game instance, so that SetGameMode can dispatch actor
	// BeginPlay. Without a game mode nothing in the level ever begins play and
	// the movement component never loads its aircraft.
	UGameInstance* GameInstance = NewObject<UGameInstance>(GEngine);
	World = UWorld::CreateWorld(EWorldType::Game, false);
	if (World == nullptr)
	{
		Error = TEXT("UWorld::CreateWorld returned null");
		return false;
	}
	World->SetShouldTick(false);   // ticked by hand, at a fixed step
	World->AddToRoot();

	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.OwningGameInstance = GameInstance;
	World->SetGameInstance(GameInstance);
	Context.SetCurrentWorld(World);
	GameInstance->Init();

	// -- georeferencing ----------------------------------------------------
	// Round planet with the UE origin pinned at the spec's ground point, so
	// engine Z=0 is the spec's terrain elevation and the engine frame is the
	// local tangent frame. The plugin derives every initial condition from the
	// actor's transform through this actor, so it has to exist first.
	GeoReferencing = World->SpawnActor<AGeoReferencingSystem>();
	if (GeoReferencing == nullptr)
	{
		Error = TEXT("could not spawn AGeoReferencingSystem");
		return false;
	}
	GeoReferencing->PlanetShape = EPlanetShape::RoundPlanet;
	GeoReferencing->bOriginAtPlanetCenter = false;
	GeoReferencing->bOriginLocationInProjectedCRS = false;
	GeoReferencing->OriginLatitude = Card.LatitudeDegrees;
	GeoReferencing->OriginLongitude = Card.LongitudeDegrees;
	GeoReferencing->OriginAltitude = Card.TerrainElevationMetres;

	// Real-terrain cards work in the raster's own projected CRS: the
	// orographic wind queries it per step and the visual pass places terrain
	// through ProjectedToEngine. Both go through this one PROJ context, so
	// the mountain the wind comes off and the mountain on screen cannot be
	// two different projections of the data.
	if (Card.bOrographic)
	{
		if (!OrographicTerrain.Load(Card.OrographicTerrainPath, Error))
		{
			return false;
		}
		if (OrographicTerrain.Crs.IsEmpty() || !OrographicTerrain.bProjected)
		{
			Error = FString::Printf(
				TEXT("orographic terrain '%s' carries no projected CRS; the ")
				TEXT("aircraft's position cannot be mapped onto it honestly."),
				*Card.OrographicTerrainPath);
			return false;
		}
		GeoReferencing->ProjectedCRS = OrographicTerrain.Crs;
	}
	if (!Card.CollisionTerrainPath.IsEmpty())
	{
		if (!CollisionTerrain.Load(Card.CollisionTerrainPath, Error))
		{
			return false;
		}
		if (CollisionTerrain.Crs.IsEmpty() || !CollisionTerrain.bProjected)
		{
			Error = FString::Printf(
				TEXT("collision terrain '%s' carries no projected CRS; the ")
				TEXT("ground cannot be placed honestly."),
				*Card.CollisionTerrainPath);
			return false;
		}
		if (Card.bOrographic && CollisionTerrain.Crs != OrographicTerrain.Crs)
		{
			Error = TEXT("collision and orographic terrain disagree about the "
			             "CRS; refusing two different grounds");
			return false;
		}
		GeoReferencing->ProjectedCRS = CollisionTerrain.Crs;
	}
	GeoReferencing->ApplySettings();

	if (Card.bOrographic)
	{
		Orographic.Init(&OrographicTerrain,
		                Card.OrographicWindSpeedMps, Card.OrographicWindFromDeg,
		                Card.OrographicDecayHeightMetres,
		                Card.OrographicWavelengthMetres, Card.bOrographicLee,
		                Card.OrographicOriginXMetres, Card.OrographicOriginYMetres);
		bOrographicReady = true;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("orographic wind over '%s' (%s): %.1f m/s from %.0f deg, ")
		       TEXT("decay %.0f m, wavelength %.0f m, lee %s"),
		       *OrographicTerrain.Name, *OrographicTerrain.Crs,
		       Card.OrographicWindSpeedMps, Card.OrographicWindFromDeg,
		       Card.OrographicDecayHeightMetres, Card.OrographicWavelengthMetres,
		       Card.bOrographicLee ? TEXT("on") : TEXT("off"));
	}

	// Phase 7 environment couplings. Each one needs only the parameters the
	// card carries; the projection context is the one that placed the terrain.
	if (Card.bDownburst)
	{
		Downburst.Init(Card.DownburstCentreNorthMetres,
		               Card.DownburstCentreEastMetres,
		               Card.DownburstCoreRadiusMetres,
		               Card.DownburstOutflowMaxMps,
		               Card.DownburstOutflowHeightMetres);
		bDownburstReady = true;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("downburst at local (%.0f, %.0f) m: core %.0f m, outflow ")
		       TEXT("%.1f m/s peaking at %.0f m AGL -- POSITION-COUPLED"),
		       Card.DownburstCentreNorthMetres, Card.DownburstCentreEastMetres,
		       Card.DownburstCoreRadiusMetres, Card.DownburstOutflowMaxMps,
		       Card.DownburstOutflowHeightMetres);
	}
	if (Card.bRotor)
	{
		RotorCard.SigmaGain = Card.RotorSigmaGain;
		RotorCard.SigmaPerW20 = Card.RotorSigmaPerW20;
		RotorCard.W20CapFps = Card.RotorW20CapFps;
		RotorCard.BackgroundW20Fps = Card.RotorBackgroundW20Fps;
		bRotorReady = true;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("lee-rotor turbulence: W20 = clamp(gain %.2f x lee sink / ")
		       TEXT("%.3f, background %.1f fps, cap %.1f fps), written per step ")
		       TEXT("-- W20 only, seed and severity stay configure-time (§13)"),
		       Card.RotorSigmaGain, Card.RotorSigmaPerW20,
		       Card.RotorBackgroundW20Fps, Card.RotorW20CapFps);
	}
	if (Card.bLogProfile)
	{
		LogProfileCard.ReferenceSpeedMps = Card.LogProfileReferenceSpeedMps;
		LogProfileCard.ReferenceHeightMetres = Card.LogProfileReferenceHeightMetres;
		LogProfileCard.Z0Metres = Card.LogProfileZ0Metres;
		LogProfileCard.SurfaceLayerTopMetres = Card.LogProfileSurfaceLayerTopMetres;
		const double Radians = FMath::DegreesToRadians(Card.LogProfileFromDegrees);
		LogProfileCard.NorthUnit = -FMath::Cos(Radians);
		LogProfileCard.EastUnit = -FMath::Sin(Radians);
		bLogProfileReady = true;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("log-profile surface layer: %.1f m/s at %.0f m ref, z0 %.4f m, ")
		       TEXT("held above %.0f m AGL"),
		       Card.LogProfileReferenceSpeedMps,
		       Card.LogProfileReferenceHeightMetres, Card.LogProfileZ0Metres,
		       Card.LogProfileSurfaceLayerTopMetres);
	}
	if (Card.bThermals)
	{
		ThermalsCard.WstarMps = Card.ThermalsWstarMps;
		ThermalsCard.ZiMetres = Card.ThermalsZiMetres;
		ThermalsCard.AreaNorthMetres = Card.ThermalsAreaNorthMetres;
		ThermalsCard.AreaEastMetres = Card.ThermalsAreaEastMetres;
		ThermalsCard.OriginXMetres = Card.ThermalsOriginXMetres;
		ThermalsCard.OriginYMetres = Card.ThermalsOriginYMetres;
		ThermalsCard.NorthMetres = Card.ThermalNorthMetres;
		ThermalsCard.EastMetres = Card.ThermalEastMetres;
		bThermalsReady = true;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("thermals (Allen TM-2006-214019): %d updrafts, w* %.2f m/s, ")
		       TEXT("zi %.0f m over %.0f x %.0f m"),
		       Card.ThermalNorthMetres.Num(), Card.ThermalsWstarMps,
		       Card.ThermalsZiMetres, Card.ThermalsAreaNorthMetres,
		       Card.ThermalsAreaEastMetres);
	}

	// -- ground ------------------------------------------------------------
	// The plugin answers JSBSim's ground queries with a line trace against
	// world geometry (UEGroundCallback). With nothing to hit it reports height
	// above terrain 0.0 everywhere, which puts a cruising aircraft's landing
	// gear in permanent ground contact.
	if (!Card.CollisionTerrainPath.IsEmpty())
	{
		// Phase 7 1.2: real heightfield collision, built from the SAME baked
		// raster the visuals draw and the orographic field samples -- one
		// raster, one sha, all three uses. Replaces the flat slab entirely
		// for this card; VerifyTrimmedCondition checks against the raster.
		if (!BuildTerrainCollision(Card, Error))
		{
			return false;
		}
	}
	else
	{
		// A query-only slab is the smallest thing that makes the ground
		// model tell the truth over abstract terrain.
		const double TrackMetres = Card.AirspeedKnots * KnotsToMetresPerSecond * Card.DurationSeconds;
		const double HalfExtentCm = (5000.0 + 2.0 * TrackMetres) * MetresToCentimetres;
		const double HalfThicknessCm = 500.0 * MetresToCentimetres;

		AActor* Ground = World->SpawnActor<AActor>();
		UBoxComponent* Slab = NewObject<UBoxComponent>(Ground, TEXT("GroundSlab"));
		Ground->SetRootComponent(Slab);
		Slab->SetBoxExtent(FVector(HalfExtentCm, HalfExtentCm, HalfThicknessCm), false);
		Slab->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
		Slab->SetCollisionObjectType(ECC_WorldStatic);
		Slab->SetCollisionResponseToAllChannels(ECR_Block);
		Slab->RegisterComponent();
		// Top face at engine Z = 0, which the georeferencing origin puts at
		// the spec's terrain elevation.
		Ground->SetActorLocation(FVector(0.0, 0.0, -HalfThicknessCm));
	}

	// -- the aircraft ------------------------------------------------------
	Aircraft = World->SpawnActor<AActor>();
	USceneComponent* Root = NewObject<USceneComponent>(Aircraft, TEXT("Root"));
	Aircraft->SetRootComponent(Root);
	Root->SetMobility(EComponentMobility::Movable);
	Root->RegisterComponent();

	Movement = NewObject<UJSBSimMovementComponent>(Aircraft, TEXT("Movement"));
	Movement->AircraftModel = Card.Aircraft;
	Movement->DrawDebug = false;
	Movement->StartOnGround = false;
	Movement->bStartWithGearDown = true;   // matches the headless host, which
	                                       // leaves JSBSim's gear default alone
	Movement->bStartWithEngineRunning = true;
	// The card's verified mixture: full rich kills a force-started piston at
	// altitude (VENDORED.json local patch 4; measured on c172p at 3600 m).
	Movement->InitialMixture = Card.EngineMixture;
	Movement->FlapPositionAtStart = 0.0;
	Movement->InitialCalibratedAirSpeedKts = Card.AirspeedKnots;
	// Deliberately NOT the plugin's wind initial condition. Measured on this
	// build, SetWindMagKtsIC re-derives the velocity state and a commanded
	// 250 kt CAS comes out of RunIC at 206 kt -- the same family of silent IC
	// interaction the headless host's _IC_PRIORITY exists for. Wind is instead
	// introduced the way the headless runner introduces it: written to the
	// FGWinds properties after a calm RunIC, followed by a full re-trim in the
	// wind (TrimInWind), then re-written every step.
	Movement->WindHeading = 0;
	Movement->WindIntensityKts = 0.0;
	Movement->ControlFDMAtmosphere = false;   // JSBSim's own standard atmosphere,
	                                          // which is what the headless host uses
	Movement->FuelFreeze = Card.bMassHeld;
	Movement->RegisterComponent();

	// The plugin derives the initial condition from where the aircraft's centre
	// of gravity ends up, not from where the actor origin is. Loading here is
	// what makes CGLocalPosition available before the actor is placed; BeginPlay
	// loads again for real, and PrepareJSBSim then reads exactly this value, so
	// the placement below and the plugin's reading of it cannot disagree.
	Movement->LoadAircraft(true);
	const FString ScreenName = Movement->GetAircraftScreenName();
	if (ScreenName.IsEmpty())
	{
		Error = FString::Printf(
			TEXT("aircraft '%s' did not load. Check that it is staged in the ")
			TEXT("plugin's Resources/JSBSim/aircraft."), *Card.Aircraft);
		return false;
	}
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("loaded '%s' as \"%s\"; centre of gravity at (%.1f, %.1f, %.1f) cm "
	            "in the actor frame"),
	       *Card.Aircraft, *ScreenName, Movement->CGLocalPosition.X,
	       Movement->CGLocalPosition.Y, Movement->CGLocalPosition.Z);

	// -- placement ---------------------------------------------------------
	// UE yaw 0 points east; JSBSim heading 0 points north, and the plugin adds
	// the 90 degrees back when it reads the actor (PrepareJSBSim).
	const FRotator Attitude(0.0, Card.HeadingDegrees - 90.0, 0.0);
	FVector TargetCentreOfGravity;
	GeoReferencing->GeographicToEngine(
		FGeographicCoordinates(Card.LongitudeDegrees, Card.LatitudeDegrees, Card.AltitudeMetres),
		TargetCentreOfGravity);
	// Solve for the actor origin that puts the CG on the commanded point.
	const FVector Origin =
		TargetCentreOfGravity - Attitude.RotateVector(Movement->CGLocalPosition);
	Aircraft->SetActorLocationAndRotation(Origin, Attitude.Quaternion());

	// -- per-step wind -----------------------------------------------------
	// Precomputed with the same conversion chain the headless stack uses
	// (SteadyWind: kt -> m/s via 1852/3600, then components, then m/s -> ft/s
	// via 1/0.3048), so the two hosts write not just the same wind but the
	// same floating-point numbers. Meteorological convention: the direction
	// is the bearing the wind blows FROM, hence the negations.
	if (Card.WindSpeedKnots > 0.0)
	{
		const double SpeedMps = Card.WindSpeedKnots * (1852.0 / 3600.0);
		const double Radians = FMath::DegreesToRadians(Card.WindFromDegrees);
		const double NorthFps = (-SpeedMps * FMath::Cos(Radians)) / 0.3048;
		const double EastFps = (-SpeedMps * FMath::Sin(Radians)) / 0.3048;
		SteadyWindNorthFps = NorthFps;
		SteadyWindEastFps = EastFps;
		WindProperties = {TEXT("atmosphere/wind-north-fps"),
		                  TEXT("atmosphere/wind-east-fps"),
		                  TEXT("atmosphere/wind-down-fps")};
		WindValues = {FString::Printf(TEXT("%.17g"), NorthFps),
		              FString::Printf(TEXT("%.17g"), EastFps),
		              TEXT("0")};
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("steady wind %.1f kt from %.0f deg -> NED fps (%.6f, %.6f, 0)"),
		       Card.WindSpeedKnots, Card.WindFromDegrees, NorthFps, EastFps);
	}
	return true;
}

void FFlightSimScenarioWorld::ConfigureTurbulence(const FFlightSimScenarioCard& Card)
{
	if (Card.TurbulenceProperties.Num() == 0)
	{
		return;
	}
	// Once, after trim and latch, exactly as EnvironmentStack.configure does
	// headless. The batch is the provider's own writes in the provider's own
	// order; nothing here decides what turbulence means.
	TArray<FString> Unused;
	Movement->CommandConsoleBatch(Card.TurbulenceProperties,
	                              Card.TurbulenceValues, Unused);
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("turbulence '%s' configured once after trim (seed %lld); the ")
	       TEXT("seed is never re-written inside the step loop"),
	       *Card.Turbulence, Card.TurbulenceSeed);
}

bool FFlightSimScenarioWorld::BeginPlay(FString& Error)
{
	FURL URL;
	World->SetGameMode(URL);
	if (World->GetAuthGameMode() == nullptr)
	{
		Error = TEXT("no game mode was created; actor BeginPlay would never run");
		return false;
	}
	World->InitializeActorsForPlay(URL);
	World->BeginPlay();
	if (!World->HasBegunPlay())
	{
		Error = TEXT("world did not begin play");
		return false;
	}
	return true;
}

bool FFlightSimScenarioWorld::TrimInWind(const FFlightSimScenarioCard& Card,
                                         FString& Error)
{
	if (WindProperties.Num() == 0)
	{
		return true;   // still air: the trim BeginPlay produced stands
	}

	// The headless sequence, reproduced: calm RunIC (done, in BeginPlay), wind
	// written to FGWinds directly, then a FULL trim in the wind. FULL rather
	// than longitudinal for the same reason mode_for(crosswind=True) chooses
	// it -- a crosswind start needs the lateral axes solved too.
	TArray<FString> Unused;
	Movement->CommandConsoleBatch(WindProperties, WindValues, Unused);
	FString Out;
	Movement->CommandConsole(TEXT("atmosphere/turb-type"), TEXT("0"), Out);

	// JSBSim's own trim entry point, through the property tree. 1 = tFull,
	// the same enum value core.fdm.trim.TrimMode.FULL pins against the 1.2.4
	// do_trim docstring. On failure JSBSim logs and carries partial state --
	// which is exactly what VerifyTrimmedCondition exists to catch, so a
	// failed trim here cannot produce a quiet wrong run.
	Movement->CommandConsole(TEXT("simulation/do_simple_trim"), TEXT("1"), Out);
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("re-trimmed in %.1f kt wind from %.0f deg (tFull)"),
	       Card.WindSpeedKnots, Card.WindFromDegrees);
	return true;
}

bool FFlightSimScenarioWorld::VerifyTrimmedCondition(const FFlightSimScenarioCard& Card,
                                                     FString& Error)
{
	const double AchievedAltitude = ReadProperty(TEXT("position/h-sl-meters"));
	const double AchievedAirspeed = ReadProperty(TEXT("velocities/vc-kts"));
	const double AchievedHeading = ReadProperty(TEXT("attitude/psi-rad")) * RadiansToDegrees;
	const double AchievedLatitude = ReadProperty(TEXT("position/lat-geod-deg"));
	const double AchievedLongitude = ReadProperty(TEXT("position/long-gc-deg"));
	const double AchievedAboveGround = ReadProperty(TEXT("position/h-agl-ft")) * FeetToMetres;
	// Over real collision terrain the RIGHT claim is height above the raster
	// under the aircraft, not above the spec's flat elevation: an aircraft
	// trimmed at 3600 m MSL over rising ground has a different AGL at every
	// point, and checking the flat number would either fail correct runs or
	// pass wrong ones depending on where the flight starts (Phase 7 1.2).
	double ExpectedAboveGround = Card.AltitudeMetres - Card.TerrainElevationMetres;
	if (bCollisionTerrainReady)
	{
		FVector Projected;
		GeoReferencing->GeographicToProjected(
			FGeographicCoordinates(Card.LongitudeDegrees, Card.LatitudeDegrees, 0.0),
			Projected);
		const double RasterElevation =
			CollisionTerrain.ElevationAt(Projected.X, Projected.Y);
		ExpectedAboveGround = Card.AltitudeMetres - RasterElevation;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("AGL check against the collision raster: elevation under ")
		       TEXT("the start point %.1f m (spec's flat value %.1f m)"),
		       RasterElevation, Card.TerrainElevationMetres);
	}

	UE_LOG(LogFlightSimScenario, Display, TEXT("trimmed state"));
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("  altitude %.3f m  CAS %.3f kt  heading %.3f deg  AGL %.1f m  %.6f/%.6f"),
	       AchievedAltitude, AchievedAirspeed, AchievedHeading, AchievedAboveGround,
	       AchievedLatitude, AchievedLongitude);

	TArray<FString> Wrong;
	if (FMath::Abs(AchievedAltitude - Card.AltitudeMetres) > AltitudeCheckMetres)
	{
		Wrong.Add(FString::Printf(TEXT("altitude %.3f m, commanded %.3f m"),
		                          AchievedAltitude, Card.AltitudeMetres));
	}
	if (FMath::Abs(AchievedAirspeed - Card.AirspeedKnots) > AirspeedCheckKnots)
	{
		Wrong.Add(FString::Printf(TEXT("CAS %.3f kt, commanded %.3f kt"),
		                          AchievedAirspeed, Card.AirspeedKnots));
	}
	if (AngleDifference(AchievedHeading, Card.HeadingDegrees) > AngleCheckDegrees)
	{
		Wrong.Add(FString::Printf(TEXT("heading %.3f deg, commanded %.3f deg"),
		                          AchievedHeading, Card.HeadingDegrees));
	}
	if (FMath::Abs(AchievedLatitude - Card.LatitudeDegrees) > PositionCheckDegrees ||
	    FMath::Abs(AchievedLongitude - Card.LongitudeDegrees) > PositionCheckDegrees)
	{
		Wrong.Add(FString::Printf(TEXT("position %.6f/%.6f, commanded %.6f/%.6f"),
		                          AchievedLatitude, AchievedLongitude,
		                          Card.LatitudeDegrees, Card.LongitudeDegrees));
	}
	if (FMath::Abs(AchievedAboveGround - ExpectedAboveGround) > AboveGroundCheckMetres)
	{
		Wrong.Add(FString::Printf(
			TEXT("height above terrain %.1f m, expected %.1f m -- the ground query ")
			TEXT("is not finding the world geometry, so the gear and ground ")
			TEXT("reaction model are running against a fiction"),
			AchievedAboveGround, ExpectedAboveGround));
	}
	if (Wrong.Num() > 0)
	{
		Error = FString::Printf(
			TEXT("the trimmed aircraft is not at the commanded condition: %s"),
			*FString::Join(Wrong, TEXT("; ")));
		return false;
	}
	return true;
}

void FFlightSimScenarioWorld::LatchTrimmedControls(bool bMassHeld)
{
	auto Read = [this](const TCHAR* Name) -> double { return ReadProperty(Name); };

	// Signs follow UJSBSimMovementComponent::CopyToJSBSim, which negates rudder
	// and yaw trim on the way in. Latching the raw value would flip them.
	Movement->Commands.Aileron = Read(TEXT("fcs/aileron-cmd-norm"));
	Movement->Commands.Elevator = Read(TEXT("fcs/elevator-cmd-norm"));
	Movement->Commands.Rudder = -Read(TEXT("fcs/rudder-cmd-norm"));
	Movement->Commands.RollTrim = Read(TEXT("fcs/roll-trim-cmd-norm"));
	Movement->Commands.PitchTrim = Read(TEXT("fcs/pitch-trim-cmd-norm"));
	Movement->Commands.YawTrim = -Read(TEXT("fcs/yaw-trim-cmd-norm"));
	Movement->Commands.Flap = Read(TEXT("fcs/flap-cmd-norm"));
	Movement->Commands.SpeedBrake = Read(TEXT("fcs/speedbrake-cmd-norm"));
	Movement->Commands.Spoiler = Read(TEXT("fcs/spoiler-cmd-norm"));
	Movement->Commands.GearDown = Read(TEXT("gear/gear-cmd-norm"));

	Movement->FuelFreeze = bMassHeld;

	for (int32 i = 0; i < Movement->EngineCommands.Num(); ++i)
	{
		const double Throttle = Read(*FString::Printf(TEXT("fcs/throttle-cmd-norm[%d]"), i));
		const double Mixture = Read(*FString::Printf(TEXT("fcs/mixture-cmd-norm[%d]"), i));
		Movement->EngineCommands[i].Throttle = Throttle;
		Movement->EngineCommands[i].Mixture = Mixture;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("  engine %d  throttle %.6f  mixture %.6f"), i, Throttle, Mixture);
	}

	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("  latched  elevator %.6f  pitch trim %.6f  aileron %.6f  rudder %.6f  gear %.1f"),
	       Movement->Commands.Elevator, Movement->Commands.PitchTrim,
	       Movement->Commands.Aileron, Movement->Commands.Rudder,
	       Movement->Commands.GearDown);
}

bool FFlightSimScenarioWorld::BuildTerrainCollision(
	const FFlightSimScenarioCard& Card, FString& Error)
{
	// The same vertex chain as the VISUAL terrain (projected CRS ->
	// ProjectedToEngine through the one PROJ context), so the ground the
	// gear feels and the ground on screen cannot be two projections of the
	// data. Stride 1: collision carries the raster's FULL 30 m grid (the
	// render mesh's stride 2 is presentation), so the only parity gap left
	// against the headless bilinear lookup is triangle-vs-bilinear
	// interpolation inside a cell -- and the AGL parity measurement
	// quantifies that rather than assuming it away.
	const int32 Stride = 1;
	const int32 Columns = (CollisionTerrain.Width - 1) / Stride + 1;
	const int32 Rows = (CollisionTerrain.Height - 1) / Stride + 1;

	TArray<FVector> Vertices;
	Vertices.Reserve(Rows * Columns);
	for (int32 Row = 0; Row < CollisionTerrain.Height; Row += Stride)
	{
		for (int32 Column = 0; Column < CollisionTerrain.Width; Column += Stride)
		{
			const double X = CollisionTerrain.OriginXMetres
			                 + Column * CollisionTerrain.PixelSizeMetres;
			const double Y = CollisionTerrain.OriginYMetres
			                 - Row * CollisionTerrain.PixelSizeMetres;
			const double Elevation = CollisionTerrain.SampleMetres(Row, Column);
			FVector Engine;
			GeoReferencing->ProjectedToEngine(FVector(X, Y, Elevation), Engine);
			Vertices.Add(Engine);
		}
	}
	TArray<int32> Triangles;
	Triangles.Reserve((Rows - 1) * (Columns - 1) * 6);
	for (int32 Row = 0; Row < Rows - 1; ++Row)
	{
		for (int32 Column = 0; Column < Columns - 1; ++Column)
		{
			const int32 A = Row * Columns + Column;
			const int32 B = A + 1;
			const int32 C = A + Columns;
			const int32 D = C + 1;
			Triangles.Append({A, C, B, B, C, D});
		}
	}

	AActor* Ground = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh =
		NewObject<UProceduralMeshComponent>(Ground, TEXT("TerrainCollision"));
	Ground->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->bUseComplexAsSimpleCollision = true;
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, {}, {},
	                                    {}, true /* collision */);
	Mesh->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
	Mesh->SetCollisionObjectType(ECC_WorldStatic);
	Mesh->SetCollisionResponseToAllChannels(ECR_Block);
	Mesh->SetVisibility(false);          // physics geometry, not scenery
	Mesh->SetCastShadow(false);
	Mesh->RegisterComponent();
	Ground->SetActorLocation(FVector::ZeroVector);

	bCollisionTerrainReady = true;
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("terrain collision from '%s' (%s, sha %s): %d verts, %d ")
	       TEXT("triangles at stride %d -- the flat slab is GONE for this run"),
	       *CollisionTerrain.Name, *CollisionTerrain.Crs,
	       *CollisionTerrain.Sha256.Left(12), Vertices.Num(),
	       Triangles.Num() / 3, Stride);
	return true;
}

void FFlightSimScenarioWorld::LocalSceneCoords(double OriginXMetres,
                                               double OriginYMetres,
                                               double& OutNorthMetres,
                                               double& OutEastMetres,
                                               double& OutAglMetres) const
{
	const double Latitude = ReadProperty(TEXT("position/lat-geod-deg"));
	const double Longitude = ReadProperty(TEXT("position/long-gc-deg"));
	OutAglMetres = ReadProperty(TEXT("position/h-agl-ft")) * FeetToMetres;
	FVector Projected;
	GeoReferencing->GeographicToProjected(
		FGeographicCoordinates(Longitude, Latitude, 0.0), Projected);
	OutEastMetres = Projected.X - OriginXMetres;
	OutNorthMetres = Projected.Y - OriginYMetres;
}

double FFlightSimScenarioWorld::RotorW20Fps(double NorthMetres,
                                            double EastMetres,
                                            double AglMetres) const
{
	// core/environment/rotor.py w20_kt_at, in fps end to end: sigma_w =
	// gain x local (height-decayed) lee sink; W20 = sigma_w / 0.107;
	// floor at the background word, cap at "severe". All four constants
	// arrive in the card; this host derives none of them.
	const double SinkMps = Orographic.LeeSinkMps(NorthMetres, EastMetres)
	                       * Orographic.Decay(AglMetres);
	const double SigmaFps = RotorCard.SigmaGain * SinkMps / 0.3048;
	const double RotorFps = SigmaFps / RotorCard.SigmaPerW20;
	return FMath::Min(FMath::Max(RotorCard.BackgroundW20Fps, RotorFps),
	                  RotorCard.W20CapFps);
}

double FFlightSimScenarioWorld::LogProfileSpeedMps(double AglMetres) const
{
	// LogProfileWind.speed_at, line for line.
	const double Z = FMath::Min(FMath::Max(AglMetres, 0.0),
	                            LogProfileCard.SurfaceLayerTopMetres);
	if (Z <= LogProfileCard.Z0Metres)
	{
		return 0.0;
	}
	return LogProfileCard.ReferenceSpeedMps
	       * FMath::Loge(Z / LogProfileCard.Z0Metres)
	       / FMath::Loge(LogProfileCard.ReferenceHeightMetres
	                     / LogProfileCard.Z0Metres);
}

double FFlightSimScenarioWorld::ThermalWMps(double NorthMetres,
                                            double EastMetres,
                                            double AglMetres) const
{
	// AllenThermals.w_at, line for line (NASA/TM-2006-214019 Appendix B).
	if (AglMetres <= 0.0)
	{
		return 0.0;
	}
	const double Zi = ThermalsCard.ZiMetres;
	const double Zzi = AglMetres / Zi;

	int32 Nearest = 0;
	double BestSq = TNumericLimits<double>::Max();
	for (int32 i = 0; i < ThermalsCard.NorthMetres.Num(); ++i)
	{
		const double Dn = NorthMetres - ThermalsCard.NorthMetres[i];
		const double De = EastMetres - ThermalsCard.EastMetres[i];
		const double DistSq = Dn * Dn + De * De;
		if (DistSq < BestSq)
		{
			BestSq = DistSq;
			Nearest = i;
		}
	}
	const double Dist = FMath::Sqrt(BestSq);

	// eq 12, floored at 10 m.
	double R2 = 10.0;
	if (Zzi > 0.0)
	{
		R2 = FMath::Max(10.0, 0.102 * FMath::Pow(Zzi, 1.0 / 3.0)
		                      * (1.0 - 0.25 * Zzi) * Zi);
	}
	const double R1R2 = R2 < 600.0 ? 0.0011 * R2 + 0.14 : 0.8;
	const double R1 = R1R2 * R2;
	// eq 11.
	const double WBar = Zzi <= 0.0 ? 0.0
		: ThermalsCard.WstarMps * FMath::Pow(Zzi, 1.0 / 3.0) * (1.0 - 1.1 * Zzi);
	const double Wc = (3.0 * WBar * (R2 * R2 * R2 - R2 * R2 * R1))
	                  / (R2 * R2 * R2 - R1 * R1 * R1);
	const double Rr2 = Dist / R2;

	// eq 16 with the Appendix B constants (columns 1-4; the paper's Table 3
	// disagrees with its own code -- the code's values are the check case).
	static const double R1R2Shape[7] =
		{0.14, 0.25, 0.36, 0.47, 0.58, 0.69, 0.80};
	static const double KShape[7][4] = {
		{1.5352, 2.5826, -0.0113, -0.1950},
		{1.5265, 3.6054, -0.0176, -0.1265},
		{1.4866, 4.8356, -0.0320, -0.0818},
		{1.2042, 7.7904, 0.0848, -0.0445},
		{0.8816, 13.9720, 0.3404, -0.0216},
		{0.7067, 23.9940, 0.5689, -0.0099},
		{0.6189, 42.7965, 0.7157, -0.0033}};
	double Ws = 0.0;
	if (Zzi < 1.0)
	{
		int32 Row = 6;
		for (int32 i = 0; i < 6; ++i)
		{
			if (R1R2 < 0.5 * (R1R2Shape[i] + R1R2Shape[i + 1]))
			{
				Row = i;
				break;
			}
		}
		const double K1 = KShape[Row][0], K2 = KShape[Row][1];
		const double K3 = KShape[Row][2], K4 = KShape[Row][3];
		Ws = 1.0 / (1.0 + FMath::Pow(FMath::Abs(K1 * Rr2 + K3), K2)) + K4 * Rr2;
		Ws = FMath::Max(Ws, 0.0);
	}

	// eqs 17-18: the toroidal edge downdraft, never positive.
	double W1 = 0.0;
	if (Dist > R1 && Rr2 < 2.0)
	{
		W1 = (PI / 6.0) * FMath::Sin(PI * Rr2);
	}
	double Swd = 0.0, Wd = 0.0;
	if (Zzi > 0.5 && Zzi <= 0.9)
	{
		Swd = 2.5 * (Zzi - 0.5);
		Wd = FMath::Min(Swd * W1, 0.0);
	}
	const double W2 = Ws * Wc + Wd * WBar;

	// eq 21: environment sink, never positive.
	const double Area = ThermalsCard.AreaNorthMetres * ThermalsCard.AreaEastMetres;
	const double At = ThermalsCard.NorthMetres.Num() * PI * R2 * R2;
	const double We = FMath::Min(-(At * WBar * (1.0 - Swd)) / (Area - At), 0.0);

	// eq 23: blend to the sink outside the core.
	if (Dist > R1 && Wc != 0.0)
	{
		return W2 * (1.0 - We / Wc) + We;
	}
	return W2;
}

bool FFlightSimScenarioWorld::Step(const FFlightSimScenarioCard& Card,
                                   double TimeSeconds, double DeltaSeconds,
                                   FString& Error)
{
	// Scripted control input. Held until the next entry, so the aircraft is
	// flying a step input rather than an impulse, and applied as an offset on
	// top of the latched trim rather than replacing it -- replacing it would
	// also throw away the trimmed pitch, which is not what "roll left" means.
	int32 Current = AppliedInputIndex;
	for (int32 i = 0; i < Card.ControlInputs.Num(); ++i)
	{
		if (Card.ControlInputs[i].TimeSeconds <= TimeSeconds)
		{
			Current = i;
		}
	}
	if (Current != AppliedInputIndex)
	{
		AppliedInputIndex = Current;
		const FFlightSimControlInput& Input = Card.ControlInputs[Current];
		Movement->Commands.Aileron = Input.Aileron;
		Movement->Commands.Elevator += Input.Elevator;
		// CopyToJSBSim negates this on the way in.
		Movement->Commands.Rudder = -Input.Rudder;
		UE_LOG(LogFlightSimScenario, Display,
		       TEXT("t=%.2f s  control input: aileron %.3f  elevator %+.3f  rudder %.3f"),
		       TimeSeconds, Input.Aileron, Input.Elevator, Input.Rudder);
	}

	// Wind is re-written every step, exactly as the headless stack does in
	// EnvironmentStack.apply. For a steady wind the values never change, so
	// this looks redundant -- until something inside JSBSim (a future gust or
	// turbulence hook, a re-trim) rewrites the wind state and one host keeps
	// flying it while the other corrects it.
	const bool bComposedWind =
		Card.WindScheduleTimes.Num() > 0 || bOrographicReady
		|| bDownburstReady || bLogProfileReady || bThermalsReady;
	if (bComposedWind)
	{
		// Base horizontal wind: the schedule entry current at this time
		// (held until the next, like control inputs), or the steady wind.
		double NorthFps = SteadyWindNorthFps;
		double EastFps = SteadyWindEastFps;
		double DownFps = 0.0;
		if (Card.WindScheduleTimes.Num() > 0)
		{
			int32 Current = ScheduleIndex < 0 ? 0 : ScheduleIndex;
			while (Current + 1 < Card.WindScheduleTimes.Num() &&
			       Card.WindScheduleTimes[Current + 1] <= TimeSeconds)
			{
				++Current;
			}
			ScheduleIndex = Current;
			NorthFps = Card.WindScheduleNorthFps[Current];
			EastFps = Card.WindScheduleEastFps[Current];
			DownFps = Card.WindScheduleDownFps[Current];
		}

		// Orographic contribution from the aircraft's ACTUAL position this
		// step -- not a precomputed track, because the whole point is that
		// the response is emergent. Position maps into the raster's CRS
		// through the same PROJ context that placed the terrain.
		if (bOrographicReady)
		{
			// Evolving conditions (Phase 7 3.1): when the card says so, the
			// orographic forcing wind follows the schedule's horizontal
			// vector rather than staying at its initial value -- otherwise a
			// building storm would blow over the ridge while the ridge kept
			// answering for the dawn calm.
			if (Card.bOrographicFollowSchedule)
			{
				const double SpeedMps =
					FMath::Sqrt(NorthFps * NorthFps + EastFps * EastFps) * 0.3048;
				const double FromDeg = FMath::RadiansToDegrees(
					FMath::Atan2(-EastFps, -NorthFps));
				Orographic.Init(&OrographicTerrain, SpeedMps, FromDeg,
				                Orographic.DecayHeightMetres,
				                Orographic.WavelengthMetres,
				                Orographic.bEnableLee,
				                Orographic.OriginXMetres,
				                Orographic.OriginYMetres);
			}
			double North = 0.0, East = 0.0, AglMetres = 0.0;
			LocalSceneCoords(Orographic.OriginXMetres, Orographic.OriginYMetres,
			                 North, East, AglMetres);
			DownFps += Orographic.WindDownMps(North, East, AglMetres) / 0.3048;
		}

		// Downburst from the actual position (Phase 7 2.3): the nominal-track
		// label comes off because the field is now spatial in this host too.
		if (bDownburstReady)
		{
			double North = 0.0, East = 0.0, AglMetres = 0.0;
			LocalSceneCoords(Card.DownburstOriginXMetres,
			                 Card.DownburstOriginYMetres, North, East, AglMetres);
			double BurstNorthMps = 0.0, BurstEastMps = 0.0, BurstDownMps = 0.0;
			Downburst.WindNedMps(North, East, AglMetres,
			                     BurstNorthMps, BurstEastMps, BurstDownMps);
			NorthFps += BurstNorthMps / 0.3048;
			EastFps += BurstEastMps / 0.3048;
			DownFps += BurstDownMps / 0.3048;
		}

		// Log-profile shear (Phase 7 2.1): horizontal wind from the aircraft's
		// height above ground, the surface-layer law.
		if (bLogProfileReady)
		{
			const double AglMetres =
				ReadProperty(TEXT("position/h-agl-ft")) * FeetToMetres;
			const double SpeedMps = LogProfileSpeedMps(AglMetres);
			NorthFps += SpeedMps * LogProfileCard.NorthUnit / 0.3048;
			EastFps += SpeedMps * LogProfileCard.EastUnit / 0.3048;
		}

		// Thermals (Phase 7 2.2): Allen's field at the actual position. The
		// thermal frame's origin is in the same projected local frame.
		if (bThermalsReady)
		{
			double North = 0.0, East = 0.0, AglMetres = 0.0;
			LocalSceneCoords(ThermalsCard.OriginXMetres,
			                 ThermalsCard.OriginYMetres, North, East, AglMetres);
			DownFps += -ThermalWMps(North, East, AglMetres) / 0.3048;
		}

		const TArray<FString> Properties = {TEXT("atmosphere/wind-north-fps"),
		                                    TEXT("atmosphere/wind-east-fps"),
		                                    TEXT("atmosphere/wind-down-fps")};
		const TArray<FString> Values = {
			FString::Printf(TEXT("%.17g"), NorthFps),
			FString::Printf(TEXT("%.17g"), EastFps),
			FString::Printf(TEXT("%.17g"), DownFps)};
		TArray<FString> Unused;
		Movement->CommandConsoleBatch(Properties, Values, Unused);
	}
	else if (WindProperties.Num() > 0)
	{
		TArray<FString> Unused;
		Movement->CommandConsoleBatch(WindProperties, WindValues, Unused);
	}

	// Per-step turbulence INTENSITY (Phase 7 1.3 / 3.1): W20 only, exactly
	// as TurbulenceProvider.step_writes documents -- never the seed (§9's
	// 515 g failure), never the POE severity (§13's 2-5x overshoot).
	{
		double W20Fps = -1.0;
		if (bRotorReady)
		{
			double North = 0.0, East = 0.0, AglMetres = 0.0;
			LocalSceneCoords(Orographic.OriginXMetres, Orographic.OriginYMetres,
			                 North, East, AglMetres);
			W20Fps = RotorW20Fps(North, East, AglMetres);
		}
		else if (Card.TurbulenceScheduleTimes.Num() > 0)
		{
			int32 Current = TurbulenceScheduleIndex < 0 ? 0 : TurbulenceScheduleIndex;
			while (Current + 1 < Card.TurbulenceScheduleTimes.Num() &&
			       Card.TurbulenceScheduleTimes[Current + 1] <= TimeSeconds)
			{
				++Current;
			}
			TurbulenceScheduleIndex = Current;
			W20Fps = Card.TurbulenceScheduleW20Fps[Current];
		}
		if (W20Fps >= 0.0)
		{
			FString Out;
			Movement->CommandConsole(
				TEXT("atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps"),
				FString::Printf(TEXT("%.17g"), W20Fps), Out);
		}
	}

	World->Tick(LEVELTICK_All, static_cast<float>(DeltaSeconds));
	GFrameCounter++;
	FTSTicker::GetCoreTicker().Tick(static_cast<float>(DeltaSeconds));
	FThreadManager::Get().Tick();
	FTaskGraphInterface::Get().ProcessThreadUntilIdle(ENamedThreads::GameThread);

	// The plugin suspends integration on a crash and keeps ticking. Without
	// this a recorder would keep sampling a frozen state and the output would
	// look like a completed run.
	if (Movement->AircraftState.Crashed)
	{
		Error = FString::Printf(TEXT("aircraft crashed at %.3f s"), TimeSeconds);
		return false;
	}
	return true;
}

void FFlightSimScenarioWorld::Teardown()
{
	if (World == nullptr)
	{
		return;
	}
	World->BeginTearingDown();
	World->EndPlay(EEndPlayReason::Quit);
	World->RemoveFromRoot();
	if (World->GetGameInstance() != nullptr)
	{
		World->GetGameInstance()->Shutdown();
	}
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	World = nullptr;
	Aircraft = nullptr;
	Movement = nullptr;
	GeoReferencing = nullptr;
}
