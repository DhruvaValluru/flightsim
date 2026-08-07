#include "FlightSimScenarioCommandlet.h"

#include "FlightSimScenarioWorld.h"
#include "FlightSimTelemetryRecorder.h"
#include "JSBSimMovementComponent.h"

#include "Engine/World.h"
#include "Misc/Parse.h"

UFlightSimScenarioCommandlet::UFlightSimScenarioCommandlet()
{
	IsClient = false;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
	ShowErrorCount = true;
}

int32 UFlightSimScenarioCommandlet::Main(const FString& Params)
{
	FString ScenarioPath;
	FString TelemetryPath;
	if (!FParse::Value(*Params, TEXT("scenario="), ScenarioPath) ||
	    !FParse::Value(*Params, TEXT("telemetry="), TelemetryPath))
	{
		UE_LOG(LogFlightSimScenario, Error,
		       TEXT("usage: -run=FlightSimBridge.FlightSimScenario ")
		       TEXT("-scenario=<run-card.json> -telemetry=<out.json>"));
		return 1;
	}

	FFlightSimScenarioCard Card;
	FString Error;
	if (!FFlightSimScenarioWorld::ReadCard(ScenarioPath, Card, Error))
	{
		UE_LOG(LogFlightSimScenario, Error, TEXT("%s"), *Error);
		return 1;
	}

	// The headless reference this trajectory is compared against is hands off
	// from trim. A card with scripted inputs describes a different flight, and
	// comparing the two would attribute a control input to the integration.
	if (Card.ControlInputs.Num() > 0)
	{
		UE_LOG(LogFlightSimScenario, Error,
		       TEXT("this run card carries %d scripted control inputs. The ")
		       TEXT("headless reference has none, so the two hosts would not be ")
		       TEXT("flying the same scenario. Use the render commandlet for a ")
		       TEXT("scenario with control inputs."), Card.ControlInputs.Num());
		return 1;
	}

	UE_LOG(LogFlightSimScenario, Display, TEXT("scenario %s"), *Card.SpecDigest);
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("  %s at %.1f m / %.1f kt CAS, heading %.1f, %.6f/%.6f, %.1f s at %.0f Hz"),
	       *Card.Aircraft, Card.AltitudeMetres, Card.AirspeedKnots, Card.HeadingDegrees,
	       Card.LatitudeDegrees, Card.LongitudeDegrees, Card.DurationSeconds, Card.RateHz);

	FFlightSimScenarioWorld Scenario;
	UFlightSimTelemetryRecorder* Recorder = nullptr;
	auto Fail = [&Scenario](const FString& Why) -> int32
	{
		UE_LOG(LogFlightSimScenario, Error, TEXT("%s"), *Why);
		Scenario.Teardown();
		return 1;
	};

	if (!Scenario.Build(Card, Error)) { return Fail(Error); }

	Recorder = NewObject<UFlightSimTelemetryRecorder>(Scenario.Aircraft, TEXT("Recorder"));
	Recorder->Movement = Scenario.Movement;
	Recorder->SampleIntervalSeconds = static_cast<float>(Card.SampleIntervalSeconds);
	Recorder->RegisterComponent();

	if (!Scenario.BeginPlay(Error)) { return Fail(Error); }
	if (!Scenario.TrimInWind(Card, Error)) { return Fail(Error); }
	if (!Scenario.VerifyTrimmedCondition(Card, Error)) { return Fail(Error); }

	UE_LOG(LogFlightSimScenario, Display, TEXT("latching trimmed controls"));
	Scenario.LatchTrimmedControls(Card.bMassHeld);

	Recorder->StartRecording(TelemetryPath);

	const double DeltaSeconds = 1.0 / Card.RateHz;
	const int32 Steps = FMath::RoundToInt(Card.DurationSeconds * Card.RateHz);
	UE_LOG(LogFlightSimScenario, Display,
	       TEXT("stepping %d frames of %.6f s"), Steps, DeltaSeconds);

	for (int32 Step = 0; Step < Steps; ++Step)
	{
		if (!Scenario.Step(Card, Step * DeltaSeconds, DeltaSeconds, Error))
		{
			return Fail(Error + TEXT("; no telemetry written"));
		}
	}

	const int32 Samples = Recorder->GetSampleCount();
	if (!Recorder->WriteToDisk())
	{
		return Fail(FString::Printf(TEXT("could not write telemetry to '%s' (%d samples)"),
		                            *TelemetryPath, Samples));
	}
	UE_LOG(LogFlightSimScenario, Display, TEXT("wrote %s (%d samples)"),
	       *TelemetryPath, Samples);

	Scenario.Teardown();
	return 0;
}
