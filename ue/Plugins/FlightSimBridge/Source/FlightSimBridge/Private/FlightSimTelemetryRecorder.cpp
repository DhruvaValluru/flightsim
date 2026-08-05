#include "FlightSimTelemetryRecorder.h"

#include "JSBSimMovementComponent.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

UFlightSimTelemetryRecorder::UFlightSimTelemetryRecorder()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

void UFlightSimTelemetryRecorder::StartRecording(const FString& InOutputPath)
{
	OutputPath = InOutputPath;
	bRecording = true;
	TimeSinceLastSample = SampleIntervalSeconds;   // sample immediately
	Times.Reset();
	AltitudeMetres.Reset();
	LatitudeDegrees.Reset();
	LongitudeDegrees.Reset();
	TrueAirspeedKnots.Reset();
	RollDegrees.Reset();
	PitchDegrees.Reset();
	HeadingDegrees.Reset();
	LoadFactor.Reset();
	ElevatorPositionRadians.Reset();
	AileronPositionRadians.Reset();
}

double UFlightSimTelemetryRecorder::ReadProperty(const FString& Name)
{
	if (Movement == nullptr)
	{
		return 0.0;
	}
	FString Value;
	Movement->CommandConsole(Name, FString(), Value);
	// An empty result means the property does not exist. Returning NaN rather
	// than 0.0 keeps a missing channel visibly missing: a zero would compare
	// plausibly against the headless run and hide the gap.
	return Value.IsEmpty() ? NAN : FCString::Atod(*Value);
}

void UFlightSimTelemetryRecorder::TickComponent(
	float DeltaTime, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (!bRecording || Movement == nullptr)
	{
		return;
	}

	TimeSinceLastSample += DeltaTime;
	if (TimeSinceLastSample < SampleIntervalSeconds)
	{
		return;
	}
	TimeSinceLastSample = 0.0f;

	Times.Add(ReadProperty(TEXT("simulation/sim-time-sec")));
	AltitudeMetres.Add(ReadProperty(TEXT("position/h-sl-meters")));
	LatitudeDegrees.Add(ReadProperty(TEXT("position/lat-geod-deg")));
	LongitudeDegrees.Add(ReadProperty(TEXT("position/long-gc-deg")));
	TrueAirspeedKnots.Add(ReadProperty(TEXT("velocities/vtrue-kts")));
	RollDegrees.Add(ReadProperty(TEXT("attitude/phi-rad")) * 57.2957795);
	PitchDegrees.Add(ReadProperty(TEXT("attitude/theta-rad")) * 57.2957795);
	HeadingDegrees.Add(ReadProperty(TEXT("attitude/psi-rad")) * 57.2957795);
	// Accelerometer, never finite-differenced (§1.3).
	LoadFactor.Add(ReadProperty(TEXT("accelerations/Nz")));
	ElevatorPositionRadians.Add(ReadProperty(TEXT("fcs/elevator-pos-rad")));
	AileronPositionRadians.Add(ReadProperty(TEXT("fcs/left-aileron-pos-rad")));
}

bool UFlightSimTelemetryRecorder::WriteToDisk()
{
	if (OutputPath.IsEmpty() || Times.Num() == 0)
	{
		return false;
	}

	TSharedPtr<FJsonObject> Columns = MakeShared<FJsonObject>();
	auto AddColumn = [&Columns](const FString& Name, const TArray<double>& Values)
	{
		TArray<TSharedPtr<FJsonValue>> Array;
		Array.Reserve(Values.Num());
		for (double Value : Values)
		{
			Array.Add(MakeShared<FJsonValueNumber>(Value));
		}
		Columns->SetArrayField(Name, Array);
	};

	// Column names match core/telemetry/recorder.py exactly.
	AddColumn(TEXT("t"), Times);
	AddColumn(TEXT("altitude_m"), AltitudeMetres);
	AddColumn(TEXT("lat_deg"), LatitudeDegrees);
	AddColumn(TEXT("lon_deg"), LongitudeDegrees);
	AddColumn(TEXT("tas_kt"), TrueAirspeedKnots);
	AddColumn(TEXT("roll_deg"), RollDegrees);
	AddColumn(TEXT("pitch_deg"), PitchDegrees);
	AddColumn(TEXT("heading_deg"), HeadingDegrees);
	AddColumn(TEXT("n_z"), LoadFactor);
	AddColumn(TEXT("elevator_pos_rad"), ElevatorPositionRadians);
	AddColumn(TEXT("aileron_pos_rad"), AileronPositionRadians);

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("host"), TEXT("unreal"));
	Root->SetNumberField(TEXT("samples"), Times.Num());
	Root->SetNumberField(TEXT("interval_s"), SampleIntervalSeconds);
	Root->SetObjectField(TEXT("columns"), Columns);

	FString Output;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
	return FFileHelper::SaveStringToFile(Output, *OutputPath);
}
