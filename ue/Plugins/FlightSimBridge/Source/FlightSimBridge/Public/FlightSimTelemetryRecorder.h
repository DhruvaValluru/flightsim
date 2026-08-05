// Read-only telemetry, in the same schema the headless recorder writes.
//
// The point of the shared schema is Gate 5: an identical scenario run in each
// host must be comparable field by field. Two recorders with different columns
// would make the comparison a data-wrangling exercise and the tolerance a
// negotiation.
//
// Observer tier (§2.1): everything here READS. CommandConsole is called with an
// empty input value, which is a read; nothing in this class writes to the FDM.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FlightSimTelemetryRecorder.generated.h"

class UJSBSimMovementComponent;

UCLASS(ClassGroup = (FlightSim), meta = (BlueprintSpawnableComponent))
class FLIGHTSIMBRIDGE_API UFlightSimTelemetryRecorder : public UActorComponent
{
	GENERATED_BODY()

public:
	UFlightSimTelemetryRecorder();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType,
	                           FActorComponentTickFunction* ThisTickFunction) override;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	UJSBSimMovementComponent* Movement = nullptr;

	// Sampling period. Independent of the tick rate: the FDM always substeps at
	// its own fixed rate, and sampling never changes what is integrated.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	float SampleIntervalSeconds = 0.1f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	FString OutputPath;

	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	void StartRecording(const FString& InOutputPath);

	// Writes the JSON. Named for what it is: until this is called the run has
	// produced nothing, so a crashed run leaves no half-file to be mistaken
	// for a result.
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	bool WriteToDisk();

	UFUNCTION(BlueprintPure, Category = "FlightSim")
	int32 GetSampleCount() const { return Times.Num(); }

private:
	double ReadProperty(const FString& Name);

	bool bRecording = false;
	float TimeSinceLastSample = 0.0f;

	TArray<double> Times;
	TArray<double> AltitudeMetres;
	TArray<double> LatitudeDegrees;
	TArray<double> LongitudeDegrees;
	TArray<double> TrueAirspeedKnots;
	TArray<double> RollDegrees;
	TArray<double> PitchDegrees;
	TArray<double> HeadingDegrees;
	TArray<double> LoadFactor;
	TArray<double> ElevatorPositionRadians;
	TArray<double> AileronPositionRadians;
};
