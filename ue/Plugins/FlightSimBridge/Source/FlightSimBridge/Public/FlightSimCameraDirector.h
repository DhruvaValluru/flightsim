// Cameras that are NOT rigidly parented to the aircraft.
//
// This file is the direct fix for ASSUMPTIONS §1.5, which is worth quoting
// because the failure is so easy to reproduce by accident:
//
//   "A chase camera rigidly parented to the aircraft, so every attitude change
//    happened to the aircraft and the camera simultaneously and cancelled out
//    visually. The aircraft appeared motionless in frame for the entire clip.
//    Real roll of +7 deg -> -7 deg was invisible."
//
// A camera welded to the airframe's rotation is a camera in the aircraft's body
// frame. In that frame the aircraft is, by construction, never moving. Every
// preset here therefore either decouples rotation from the aircraft entirely,
// or lags it, and at least one keeps the horizon in shot so that attitude is
// legible as attitude rather than as the world sliding about.

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "FlightSimCameraDirector.generated.h"

class UCineCameraComponent;

UENUM(BlueprintType)
enum class EFlightSimCameraPreset : uint8
{
	// Follows position with a spring lag and looks AT the aircraft. Never
	// inherits roll, so a roll input rotates the aircraft against a fixed
	// horizon instead of rotating the world around a static aircraft.
	LaggedChase      UMETA(DisplayName = "Lagged chase"),

	// Fixed to the world. The aircraft flies past. Nothing about the aircraft's
	// attitude can cancel out, because the camera has no knowledge of it beyond
	// where to point.
	GroundObserver   UMETA(DisplayName = "Ground observer"),

	// Station-keeping alongside, in the aircraft's heading frame but level.
	// Reads as another aircraft in formation, which is a real vantage point.
	Wingman          UMETA(DisplayName = "Wingman"),

	// Fixed high point, slow pan. The classic tower view.
	Tower            UMETA(DisplayName = "Tower"),

	// Over the pilot's shoulder, body-fixed: the ONE preset that inherits
	// roll, and it says so -- PresetKeepsHorizonLevel() is false and the
	// manifest records camera_inherits_roll=true for any clip using it
	// (§1.5: never inherited silently). In this frame the aircraft is by
	// construction static and the WORLD banks; that is the honest meaning
	// of a cockpit view and must never be graded as aircraft motion.
	CockpitShoulder  UMETA(DisplayName = "Cockpit shoulder"),
};

UCLASS(Blueprintable)
class FLIGHTSIMBRIDGE_API AFlightSimCameraDirector : public AActor
{
	GENERATED_BODY()

public:
	AFlightSimCameraDirector();

	virtual void Tick(float DeltaSeconds) override;

	// The aircraft to observe. Deliberately a soft association: the camera
	// reads the aircraft's transform, it is never attached to it.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	AActor* Target = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	EFlightSimCameraPreset Preset = EFlightSimCameraPreset::LaggedChase;

	// Metres behind and above, for the chase and wingman presets.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector ChaseOffsetMetres = FVector(-60.0f, 0.0f, 12.0f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector WingmanOffsetMetres = FVector(-15.0f, 25.0f, 0.0f);

	// Body-frame offset for the cockpit-shoulder preset, metres. Slightly
	// behind and above the cockpit, offset toward the left seat.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector ShoulderOffsetMetres = FVector(-6.0f, -0.5f, 1.6f);

	// Spring-arm lag. Larger is looser; zero would weld the camera to the
	// aircraft's motion and reintroduce the failure this class exists to avoid.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera",
		meta = (ClampMin = "0.05"))
	float PositionLagSeconds = 0.45f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera",
		meta = (ClampMin = "0.05"))
	float AimLagSeconds = 0.25f;

	// World location for the fixed presets, in metres relative to the origin.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector ObserverLocationMetres = FVector(0.0f, 1500.0f, 30.0f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector TowerLocationMetres = FVector(-800.0f, 900.0f, 80.0f);

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "FlightSim|Camera")
	UCineCameraComponent* Camera = nullptr;

	// True when the current preset keeps the world horizon level in frame.
	// Gate 5 requires at least one preset for which this holds, because a
	// commanded roll is only legible against a stable horizon.
	UFUNCTION(BlueprintPure, Category = "FlightSim|Camera")
	bool PresetKeepsHorizonLevel() const;

	// The camera's roll, in degrees. Asserted to stay at zero for the presets
	// above: any non-zero value means the camera has started inheriting the
	// aircraft's roll, which is exactly how the previous build made a 14-degree
	// roll reversal invisible.
	UFUNCTION(BlueprintPure, Category = "FlightSim|Camera")
	float GetCameraRollDegrees() const;

	// -- consume-poses mode (Camera Phase 1) -------------------------------
	// The run card can carry a Python-solved pose track (the wind-schedule
	// discipline applied to cameras: computed once in core/capture/poses.py,
	// consumed verbatim here). When a track is set, Tick() computes NOTHING
	// -- the commandlet drives the camera by simulation time through
	// ApplyPoseAtTime, which interpolates the track (linear position, slerp
	// rotation) and REFUSES, with the reason, any time the track does not
	// cover: a camera that extrapolated would be applying a pose nobody
	// solved or validated. The preset machinery above is untouched and
	// remains the interactive host's.

	// Times are simulation seconds; locations engine units (cm); rotations
	// engine rotators (the caller owns the scene-frame conversion, next to
	// its GeoReferencing context). Refuses tracks shorter than two samples.
	bool SetPoseTrack(TArray<double>&& Times, TArray<FVector>&& Locations,
	                  TArray<FRotator>&& Rotations, FString& Error);

	bool ConsumingPoses() const { return PoseTimes.Num() > 0; }

	// Place the camera exactly where the solved track says it is at
	// SimTimeSeconds. False (with the reason) when no track is set or the
	// time lies outside the track's span.
	bool ApplyPoseAtTime(double SimTimeSeconds, FString& Error);

	// Optional per-sample focal length (mm) beside the track, for cards
	// whose keyframed moves vary the lens. Must match the track's length;
	// set AFTER SetPoseTrack.
	bool SetPoseFocalLengths(TArray<double>&& FocalLengthsMm, FString& Error);

	// What the last ApplyPoseAtTime interpolated from the track (the
	// SOLVED pose the applied one was compared to) and the focal length
	// it interpolated (0 when the track carries none) -- for the
	// per-frame record, so the Python verifier grades applied against
	// solved from one file.
	FVector GetSolvedLocation() const { return LastSolvedLocation; }
	FRotator GetSolvedRotation() const { return LastSolvedRotation; }
	double GetAppliedFocalLengthMm() const { return LastAppliedFocalLengthMm; }
	double GetTrackStartSeconds() const
	{
		return PoseTimes.Num() > 0 ? PoseTimes[0] : 0.0;
	}
	double GetTrackEndSeconds() const
	{
		return PoseTimes.Num() > 0 ? PoseTimes.Last() : 0.0;
	}

	// Applied-vs-solved parity, both FAILING ApplyPoseAtTime (never a
	// warning): 10 cm of position and 0.1 deg of orientation.
	static constexpr double PoseParityPositionCm = 10.0;
	static constexpr double PoseParityAngleDegrees = 0.1;

private:
	void UpdateLaggedChase(float DeltaSeconds, const FTransform& TargetTransform);
	void UpdateCockpitShoulder(const FTransform& TargetTransform);
	void UpdateFixedPoint(float DeltaSeconds, const FVector& WorldLocation,
	                      const FVector& TargetLocation);
	void UpdateWingman(float DeltaSeconds, const FTransform& TargetTransform);

	// Aim is smoothed here rather than by attaching to the target, so the
	// camera lags the aircraft instead of moving with it.
	FVector SmoothedLocation = FVector::ZeroVector;
	FVector SmoothedAimPoint = FVector::ZeroVector;
	bool bInitialised = false;

	// The consumed pose track (empty = preset mode).
	TArray<double> PoseTimes;
	TArray<FVector> PoseLocations;
	TArray<FRotator> PoseRotations;
	TArray<double> PoseFocalLengthsMm;
	FVector LastSolvedLocation = FVector::ZeroVector;
	FRotator LastSolvedRotation = FRotator::ZeroRotator;
	double LastAppliedFocalLengthMm = 0.0;
};
