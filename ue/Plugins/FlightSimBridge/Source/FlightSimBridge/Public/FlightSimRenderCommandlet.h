// Render frames of a scenario, headlessly, and write them to disk.
//
// The two clauses of Gate 5 that FlightSimScenarioCommandlet cannot answer are
// about what a viewer sees: "control surfaces visibly articulate" and
// "commanded roll is visible on screen". Neither is a claim about the FDM. Both
// need pixels, and pixels need a real RHI -- which is why this is a separate
// commandlet from the telemetry one rather than a flag on it. UCommandlet::
// IsClient is read off the class default object before the engine initialises,
// so a commandlet either brings up the renderer or it does not.
//
// Run it with -RenderOffScreen (and NOT -nullrhi): scripts/render_ue_scenario.sh.

#pragma once

#include "CoreMinimal.h"
#include "Commandlets/Commandlet.h"
#include "FlightSimRenderCommandlet.generated.h"

DECLARE_LOG_CATEGORY_EXTERN(LogFlightSimRender, Log, All);

UCLASS()
class FLIGHTSIMBRIDGE_API UFlightSimRenderCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UFlightSimRenderCommandlet();

	virtual int32 Main(const FString& Params) override;
};
