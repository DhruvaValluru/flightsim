// The windowed interactive host (Phase 8).
//
// The third driver of FFlightSimScenarioWorld, after the telemetry and render
// commandlets: same card format, same world population, same step writes.
// What is new is only the clock. The commandlets step the world by hand at
// exactly 1/120 s per frame and let a slow frame cost wall time; a window
// cannot, so this mode accumulates the engine's wall delta and steps the FDM
// in WHOLE 1/120 s substeps, remainder carried. JSBSim never sees any other
// dt: the movement component's own tick is disabled at spawn and every
// substep goes through the one stepping path.
//
// Catch-up is capped. When a frame arrives owing more substeps than the cap
// allows, the excess is DROPPED from the accumulator and COUNTED -- the sim
// clock falls behind the wall clock (time dilation) rather than the FDM ever
// being fed a stretched dt. The deficit total is in the probe report and, in
// the full host, the manifest; an on-screen line shows when the sim is
// running behind.
//
// With -probe-seconds=N this mode is Phase 8B.0's fps probe: it flies the
// card hands-off for N wall seconds over the full scene and writes a JSON
// report of frame statistics and substep accounting, then quits. The report
// is the go/no-go number for the interactive tier -- measured, not assumed.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimVisualScene.h"
#include "FlightSimInteractiveMode.generated.h"

class AFlightSimCameraDirector;

UCLASS()
class FLIGHTSIMBRIDGE_API AFlightSimInteractiveMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AFlightSimInteractiveMode();

	virtual void StartPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	// Card in, world populated, trimmed, verified, visuals up, camera live.
	// Any failure logs the reason, writes it into the report and quits --
	// a window showing something other than the card's scenario is the §1.6
	// failure with a frame rate.
	bool SetupScenario(FString& Error);
	void FailAndQuit(const FString& Why);
	void FinishAndQuit(const FString& Outcome);
	void WriteReport(const FString& Outcome);

	FFlightSimScenarioCard Card;
	FFlightSimScenarioWorld Scenario;
	FFlightSimVisualScene Visual;

	UPROPERTY()
	AFlightSimCameraDirector* CameraDirector = nullptr;

	// -- fixed-substep accounting (Gate 8.2's substep clause) --------------
	double SubstepSeconds = 1.0 / 120.0;
	double Accumulator = 0.0;
	double SimTimeSeconds = 0.0;
	uint64 SubstepCount = 0;
	// Whole substeps a single frame may owe before the excess is dropped and
	// counted. ~250 ms: a hitch beyond this becomes time dilation, never a
	// stretched dt.
	double CatchUpCapSeconds = 0.25;
	uint64 DeficitEvents = 0;
	double DeficitSeconds = 0.0;

	// -- probe bookkeeping -------------------------------------------------
	double ProbeSeconds = 0.0;         // 0: fly the card's full duration
	FString ReportPath;
	FString CameraPresetName = TEXT("chase");
	double WallSeconds = 0.0;
	// Wall time measured with FPlatformTime, NOT the engine's DeltaSeconds:
	// DefaultEngine.ini pins bUseFixedFrameRate=120 for the offline hosts'
	// reproducibility, which makes DeltaSeconds a constant 1/120 whatever
	// the frames actually cost. The interactive clock is the wall clock.
	double LastWallTime = -1.0;
	TArray<float> FrameSeconds;        // every rendered frame's wall delta
	bool bRunning = false;
	bool bFinished = false;
};
