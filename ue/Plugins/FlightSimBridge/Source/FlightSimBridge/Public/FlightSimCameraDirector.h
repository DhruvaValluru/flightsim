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
class UJSBSimMovementComponent;

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

	// Metres behind and above, for the chase and wingman presets. Both
	// literals are Python's (core/scenario/camera.py FALLBACK_CHASE_OFFSET
	// and WINGMAN_OFFSET); tests/test_gate6_visual.py reads them from this
	// text and pins them to those constants. What each one reaches is
	// different, and stated rather than claimed:
	//
	//  * WingmanOffsetMetres is LIVE: the render commandlet keeps it unless
	//    -wingman-abeam= is given and the interactive host never sets it,
	//    so a wingman preset flies Python's slot.
	//  * ChaseOffsetMetres is a FALLBACK that no shipped host flies. The
	//    render commandlet assigns its shot constant on every preset-mode
	//    run (-170/0/16 m for the terrain shot, -400/0/200 m for the shadow
	//    shot -- the framing Gate 6 was measured at) and then -chase=; the
	//    interactive host assigns -170/0/16 m (FlightSimInteractiveMode.cpp).
	//    Only a caller that spawns this actor and sets nothing gets this
	//    value. Python's chase is per airframe (CHASE_OFFSETS; the fallback
	//    is the B747's), so this literal is the B747's solved chase, not a
	//    rule any rendered preset-mode chase frame obeys.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector ChaseOffsetMetres = FVector(-110.0f, 0.0f, 12.0f);

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim|Camera")
	FVector WingmanOffsetMetres = FVector(-45.0f, 180.0f, 0.0f);

	// Body-frame offset for the cockpit-shoulder preset, metres. Slightly
	// behind and above the cockpit, offset toward the left seat. Applied
	// UNSCALED from the CG (Python's SHOULDER_OFFSET rule); the render
	// commandlet no longer span-scales it.
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
	// its GeoReferencing context). FocalLengthsMm is the solved per-sample
	// lens: the camera phase's intrinsics are part of the recorded label,
	// so the frames must be taken through the lens the manifest names, not
	// through a hardcoded field of view. Refuses tracks shorter than two
	// samples, and any array whose length disagrees with the rest.
	bool SetPoseTrack(TArray<double>&& Times, TArray<FVector>&& Locations,
	                  TArray<FRotator>&& Rotations,
	                  TArray<double>&& FocalLengthsMm, FString& Error);

	bool ConsumingPoses() const { return PoseTimes.Num() > 0; }

	// The first solved instant. The warm-up placement wants THIS, not
	// zero: the recorder's first sample is one step in (t = 1/rate), so
	// asking for t=0 lands outside the track and is refused -- correctly,
	// by a guard that exists to catch a track that does not cover the
	// run. Nothing is being relaxed here; the caller was asking the
	// wrong question.
	double TrackStartSeconds() const
	{
		return PoseTimes.Num() > 0 ? PoseTimes[0] : 0.0;
	}

	// Place the camera exactly where the solved track says it is at
	// SimTimeSeconds. False (with the reason) when no track is set, the
	// time lies outside the track's span, or the pose the engine actually
	// applied differs from the solved one in POSITION or ROTATION beyond
	// the stated tolerances.
	bool ApplyPoseAtTime(double SimTimeSeconds, FString& Error);

	// The two applied-vs-solved tolerances, named rather than spelled
	// inline, so a test can drive the decision at the exact boundary
	// instead of asserting that a magic number appears in the source.
	//
	// 10 cm on a cinema camera is already generous. 0.05 deg is the one
	// that earns its keep: at a kilometre it is 0.9 m of misplaced
	// world, and where the camera LOOKS is most of the label.
	//
	// For scale, this comparison cannot resolve better than ~2e-6 deg
	// -- AngularDistance goes through acos, which is ill-conditioned
	// near an angle of zero, and that is what an identical pose
	// measures against itself. Four orders of magnitude under the
	// tolerance, so 0.05 deg grades displacement and not the
	// arithmetic underneath it.
	static constexpr double PositionToleranceCm = 10.0;
	static constexpr double RotationToleranceDeg = 0.05;

	// Degrees between two orientations. Pure, static and public because
	// it is the guard's actual decision: everything else in
	// ApplyPoseAtTime is placing the camera, and this is the part that
	// says whether the placement took.
	static double RotationErrorDegrees(const FQuat& Applied,
	                                   const FQuat& Solved)
	{
		return FMath::RadiansToDegrees(Applied.AngularDistance(Solved));
	}

	// The solved lens at the last applied time, millimetres. The commandlet
	// sets the capture's field of view from this every frame, so a
	// keyframed focal-length move reaches the pixels instead of only the
	// manifest.
	double GetAppliedFocalLengthMm() const { return AppliedFocalLengthMm; }

	// Where the current preset would put the camera for the target as it
	// stands NOW, and the look from there to the aim point (level for
	// every preset but the body-fixed shoulder) -- what a host that places
	// the camera before the first Tick asks for, so a lagged preset opens
	// where it will settle instead of flying in. Measured from the same
	// point the presets update from (TargetAimPoint: the CG, not the actor
	// origin) with the same arithmetic (HeadingOffsetStation), so the place
	// the camera is put is the place the first Tick's goal is. The render
	// commandlet's settle-in placement computed its own station from the
	// actor origin -- the structural datum, 33.7 m ahead of the B747's CG
	// -- so once the presets moved to the CG every preset-mode chase clip
	// opened 136 m behind the CG and was dragged in to 170 m over the
	// first ~1.5 s (three PositionLagSeconds) of written frames, and the
	// wingman, pre-placed at the CHASE offset, swung ~220 m into its slot.
	// False when there is no Target.
	bool PresetRestingPose(FVector& OutLocation, FRotator& OutLook);

private:
	// The point every preset aims at and measures its offset from: the
	// aircraft's CENTRE OF GRAVITY, not the actor origin. The actor origin
	// is the JSBSim structural datum (33.7 m ahead of the B747's CG), and
	// the Python pose solver (core/capture/poses.py) states every offset
	// from the CG -- the point the telemetry's lat/lon/alt describe -- so
	// a preset that used the actor location framed a point 25-30 m ahead
	// of the airframe (Camera Phase 1 initial run report, the cockpit
	// preset that reported the aircraft out of frame while the mask held
	// 434k aircraft pixels). CGLocalPosition when the target carries a
	// UJSBSimMovementComponent; the actor location otherwise.
	FVector TargetAimPoint(const FTransform& TargetTransform) const;

	// Target is a plain UPROPERTY with no setter, so the component lookup
	// is refreshed whenever the actor it was cached for changes.
	void RefreshTargetMovement();

	// The chase and wingman station: OffsetMetres applied in a HEADING-ONLY
	// frame from the aim point. Yaw is taken from the target so the camera
	// stays behind it through a turn; pitch and roll are discarded. Using
	// the full rotation here is precisely the mistake -- the camera would
	// roll with the aircraft and the roll would vanish. One arithmetic for
	// the two lagged presets and PresetRestingPose.
	static FVector HeadingOffsetStation(const FVector& AimPoint,
	                                    const FTransform& TargetTransform,
	                                    const FVector& OffsetMetres);

	void UpdateLaggedChase(float DeltaSeconds, const FTransform& TargetTransform);
	void UpdateCockpitShoulder(const FTransform& TargetTransform);
	void UpdateFixedPoint(float DeltaSeconds, const FVector& WorldLocation,
	                      const FVector& TargetLocation);
	void UpdateWingman(float DeltaSeconds, const FTransform& TargetTransform);

	UPROPERTY()
	AActor* TargetMovementOwner = nullptr;

	UPROPERTY()
	UJSBSimMovementComponent* TargetMovement = nullptr;

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
	double AppliedFocalLengthMm = 0.0;
};
