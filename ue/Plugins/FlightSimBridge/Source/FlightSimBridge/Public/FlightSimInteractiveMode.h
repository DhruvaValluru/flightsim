// The windowed interactive host (Phase 8).
//
// The third driver of FFlightSimScenarioWorld, after the telemetry and render
// commandlets: same card format, same world population, same step writes.
// What is new is only the clock. The commandlets step the world by hand at
// exactly 1/120 s per frame and let a slow frame cost wall time; a window
// cannot, so this mode accumulates the WALL clock (never the engine's frame
// delta, which DefaultEngine.ini pins for the offline hosts) and steps the
// FDM in WHOLE 1/120 s substeps, remainder carried. JSBSim never sees any
// other dt: the movement component's own tick is disabled at spawn and every
// substep goes through the one stepping path.
//
// Catch-up is capped. When a frame arrives owing more substeps than the cap
// allows, the excess is DROPPED from the accumulator and COUNTED -- the sim
// clock falls behind the wall clock (time dilation) rather than the FDM ever
// being fed a stretched dt. The deficit ledger is in the manifest and on the
// HUD; RUNNING BEHIND is an explicit on-screen state, never silent.
//
// Every session records. The recorder is the same component the telemetry
// commandlet uses, stamping the FDM's own clock, and the session manifest
// carries the spec digest, seed, scene provenance and honesty labels -- the
// claim-bearing artifact of an interactive session is its recorded card,
// which the headless host re-flies deterministically (Gate 8.2's replay
// clause). The window is a viewport; claims come from the replay.
//
// With -probe-seconds=N this mode doubles as Phase 8B.0's fps probe.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "FlightSimCameraDirector.h"
#include "FlightSimScenarioWorld.h"
#include "FlightSimVisualScene.h"
#include "FlightSimInteractiveMode.generated.h"

class UFlightSimTelemetryRecorder;

// One HUD line: text plus the colour that says how to read it.
USTRUCT()
struct FFlightSimHudLine
{
	GENERATED_BODY()

	FString Text;
	FLinearColor Colour = FLinearColor::White;
};

UCLASS()
class FLIGHTSIMBRIDGE_API AFlightSimInteractiveMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AFlightSimInteractiveMode();

	virtual void StartPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	// The honesty core the HUD draws each frame; composed here so the HUD
	// stays a dumb painter. Reads the card and the FDM; recomputes nothing.
	TArray<FFlightSimHudLine> HudLines() const;

	// Camera preset keys (1-4). CockpitShoulder stays the ONE preset that
	// inherits roll, and the HUD says so while it is active.
	void SelectCameraChase();
	void SelectCameraWingman();
	void SelectCameraTower();
	void SelectCameraShoulder();

private:
	bool SetupScenario(FString& Error);
	void FailAndQuit(const FString& Why);
	void FinishAndQuit(const FString& Outcome);
	void WriteProbeReport(const FString& Outcome);
	// The session manifest: digest, seed, scene provenance, honesty labels,
	// the substep/deficit ledger, and where the telemetry landed. ASCII only
	// (gotcha 13); the prompt lives in the web app's UTF-8 sidecar.
	void WriteManifest(const FString& Outcome);
	void ApplyCameraPreset(EFlightSimCameraPreset Preset, const TCHAR* Name);

	FFlightSimScenarioCard Card;
	FFlightSimScenarioWorld Scenario;
	FFlightSimVisualScene Visual;

	UPROPERTY()
	AFlightSimCameraDirector* CameraDirector = nullptr;

	UPROPERTY()
	UFlightSimTelemetryRecorder* Recorder = nullptr;

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
	double LastCapWallTime = -1.0;

	// -- session bookkeeping -----------------------------------------------
	double ProbeSeconds = 0.0;         // 0: fly the card's full duration
	FString ReportPath;
	FString TelemetryPath;
	FString ManifestPath;
	FString CameraPresetName = TEXT("chase");
	// Wall time measured with FPlatformTime, NOT the engine's DeltaSeconds:
	// DefaultEngine.ini pins bUseFixedFrameRate=120 for the offline hosts'
	// reproducibility, which makes DeltaSeconds a constant 1/120 whatever
	// the frames actually cost. The interactive clock is the wall clock.
	double LastWallTime = -1.0;
	double WallSeconds = 0.0;
	TArray<float> FrameSeconds;        // every rendered frame's wall delta
	// -screenshot-at=a:b:c -- wall seconds at which a with-UI screenshot is
	// captured (Gate 8.2's on-screen clauses read these back).
	TArray<double> ScreenshotAtSeconds;
	int32 NextScreenshotIndex = 0;
	FString ScreenshotDirectory;
	bool bRunning = false;
	bool bFinished = false;
};
