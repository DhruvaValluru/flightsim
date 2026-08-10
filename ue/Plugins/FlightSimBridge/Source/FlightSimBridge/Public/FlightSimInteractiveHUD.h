// The interactive window's honesty layer (Phase 8C.2).
//
// The showcase clips print their honesty labels on every frame of every clip
// rather than keeping them in a file nobody opens; the live window follows
// the same principle. This HUD draws the telemetry panel's honesty core:
// commanded vs achieved state, the wind actually inside the FDM, the
// turbulence seed with its visual-only label, the physics-ground label
// (heightfield vs slab), AGL, the camera preset (and whether it inherits
// roll), and the substep/deficit ledger with an explicit RUNNING BEHIND
// state. Everything drawn is read from the card or the FDM each frame;
// nothing is recomputed physics.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "FlightSimInteractiveHUD.generated.h"

UCLASS()
class FLIGHTSIMBRIDGE_API AFlightSimInteractiveHUD : public AHUD
{
	GENERATED_BODY()

public:
	virtual void DrawHUD() override;
};
