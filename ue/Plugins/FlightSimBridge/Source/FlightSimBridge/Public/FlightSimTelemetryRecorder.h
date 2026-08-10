// Read-only telemetry, in the same schema the headless recorder writes.
//
// The point of the shared schema is Gate 5: an identical scenario run in each
// host must be comparable field by field. Two recorders with different columns
// would make the comparison a data-wrangling exercise and the tolerance a
// negotiation.
//
// Observer tier (§2.1): everything here READS. CommandConsole is called with an
// empty input value, which is a read; nothing in this class writes to the FDM.
//
// The aero block (Phase 8 panel) records what the air is doing TO the
// aircraft -- the FDM's own aerodynamic state (alpha/beta, qbar, body- and
// wind-axis aero forces, flight-path angle, the total wind and NED velocity).
// JSBSim is coefficient tables, not CFD: no flow field exists and none is
// recorded. Every property name in the channel table was verified against
// the live property catalog of the pinned JSBSim (hazard 1,
// docs/JSBSIM_CORRECTIONS.md §3: reading an unknown property fails SILENTLY
// with an empty result) -- and SelftestProperties() re-verifies at host
// startup so a renamed property fails the run loudly instead of recording
// NaN forever.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FlightSimTelemetryRecorder.generated.h"

class UJSBSimMovementComponent;

// One recorded channel: a JSON column, the JSBSim property it reads, and a
// pure unit-conversion scale. bRequired channels must exist on every
// airframe; optional ones (surface positions a model may not define) are
// sampled as NaN when absent, which keeps a missing channel visibly missing.
struct FFlightSimTelemetryChannel
{
	const TCHAR* Column;
	const TCHAR* Property;
	double Scale;
	bool bRequired;
};

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

	// The full channel table. Sampling, the selftest and the writer all
	// iterate THIS, so a channel cannot be sampled without being selftested
	// and cannot be selftested without being written.
	static TArrayView<const FFlightSimTelemetryChannel> ChannelTable();

	// hazard 1: read every required channel once and demand a finite value.
	// Hosts call this after trim, before recording, and REFUSE the run on
	// failure -- a missing property must never record zeros/NaN forever.
	bool SelftestProperties(FString& Error);

	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	void StartRecording(const FString& InOutputPath);

	// Writes the JSON. Named for what it is: until this is called the run has
	// produced nothing, so a crashed run leaves no half-file to be mistaken
	// for a result.
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	bool WriteToDisk();

	UFUNCTION(BlueprintPure, Category = "FlightSim")
	int32 GetSampleCount() const
	{
		return Columns.Num() > 0 ? Columns[0].Num() : 0;
	}

private:
	double ReadProperty(const FString& Name);

	bool bRecording = false;
	float TimeSinceLastSample = 0.0f;

	// One array per channel, parallel to ChannelTable().
	TArray<TArray<double>> Columns;
};
