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
};
