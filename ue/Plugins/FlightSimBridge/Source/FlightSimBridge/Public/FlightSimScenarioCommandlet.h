// Drive one scenario through the Unreal host, headlessly, and write telemetry.
//
// This is the missing half of Gate 5's trajectory clause. The headless host can
// already produce a trajectory from a spec; until this existed the Unreal host
// could only be flown by hand in the editor, which produces no comparable
// record and no reproducible one.
//
// What it is NOT: a second simulator. Every number in the output comes out of
// the same JSBSim build, running the same aircraft file, that the headless core
// runs -- verified byte for byte by scripts/ue_preflight.sh. This commandlet
// builds a world, puts the aircraft in it at the spec's initial conditions, and
// steps the clock. If the two hosts disagree, the disagreement is in the
// integration path, which is exactly what Gate 5 is asking about.
//
// The world it flies in is FFlightSimScenarioWorld, shared with the render
// commandlet so the two cannot drift apart.

#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "FlightSimScenarioCommandlet.generated.h"

UCLASS()
class FLIGHTSIMBRIDGE_API UFlightSimScenarioCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UFlightSimScenarioCommandlet();

	virtual int32 Main(const FString& Params) override;
};
