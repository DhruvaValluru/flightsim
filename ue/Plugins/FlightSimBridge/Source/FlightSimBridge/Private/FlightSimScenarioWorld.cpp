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

	FString Turbulence;
	if (!ReadString(Root, TEXT("turbulence"), Turbulence, Error)) { return false; }
	if (Turbulence != TEXT("none"))
	{
		Error = FString::Printf(
			TEXT("spec requests %s turbulence. The headless host runs its own ")
			TEXT("Dryden provider (core/environment/turbulence.py); this host has ")
			TEXT("no equivalent, and the plugin's built-in turbulence is a ")
			TEXT("different stochastic process. Comparing them would compare two ")
			TEXT("noise realisations."), *Turbulence);
		return false;
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
	GeoReferencing->ApplySettings();

	// -- ground ------------------------------------------------------------
	// The plugin answers JSBSim's ground queries with a line trace against
	// world geometry (UEGroundCallback). With nothing to hit it reports height
	// above terrain 0.0 everywhere, which puts a cruising aircraft's landing
	// gear in permanent ground contact. A query-only slab is the smallest thing
	// that makes the ground model tell the truth.
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
	// Top face at engine Z = 0, which the georeferencing origin puts at the
	// spec's terrain elevation.
	Ground->SetActorLocation(FVector(0.0, 0.0, -HalfThicknessCm));

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
	const double ExpectedAboveGround = Card.AltitudeMetres - Card.TerrainElevationMetres;

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
	if (WindProperties.Num() > 0)
	{
		TArray<FString> Unused;
		Movement->CommandConsoleBatch(WindProperties, WindValues, Unused);
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
