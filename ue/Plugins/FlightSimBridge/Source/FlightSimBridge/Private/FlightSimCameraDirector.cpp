#include "FlightSimCameraDirector.h"

#include "CineCameraComponent.h"
#include "JSBSimMovementComponent.h"

namespace
{
	// Unreal works in centimetres.
	constexpr float CmPerMetre = 100.0f;

	// Critically-damped-ish exponential smoothing. Frame-rate independent, so
	// the lag is a time constant rather than a per-frame fraction -- which
	// would change the camera's behaviour with the tick rate and make a
	// recorded shot depend on how fast the machine was.
	FVector SmoothTowards(const FVector& Current, const FVector& Goal,
	                      float DeltaSeconds, float TimeConstant)
	{
		if (TimeConstant <= KINDA_SMALL_NUMBER)
		{
			return Goal;
		}
		const float Alpha = 1.0f - FMath::Exp(-DeltaSeconds / TimeConstant);
		return FMath::Lerp(Current, Goal, Alpha);
	}
}

AFlightSimCameraDirector::AFlightSimCameraDirector()
{
	PrimaryActorTick.bCanEverTick = true;
	// Tick after the aircraft has moved, so the camera reacts to this frame's
	// state rather than last frame's.
	PrimaryActorTick.TickGroup = TG_PostPhysics;

	Camera = CreateDefaultSubobject<UCineCameraComponent>(TEXT("Camera"));
	RootComponent = Camera;
}

bool AFlightSimCameraDirector::PresetKeepsHorizonLevel() const
{
	// Every preset here is horizon-stable. The enum deliberately contains no
	// cockpit or body-fixed option: those belong to a presentation layer that
	// is off in research mode, not to the observer tier.
	switch (Preset)
	{
	case EFlightSimCameraPreset::LaggedChase:
	case EFlightSimCameraPreset::GroundObserver:
	case EFlightSimCameraPreset::Wingman:
	case EFlightSimCameraPreset::Tower:
		return true;
	case EFlightSimCameraPreset::CockpitShoulder:
		// The declared exception (§1.5): body-fixed, roll inherited ON
		// PURPOSE, and the manifest must say so for any clip that uses it.
		return false;
	default:
		return false;
	}
}

float AFlightSimCameraDirector::GetCameraRollDegrees() const
{
	return GetActorRotation().Roll;
}

void AFlightSimCameraDirector::RefreshTargetMovement()
{
	if (Target == TargetMovementOwner)
	{
		return;
	}
	TargetMovementOwner = Target;
	TargetMovement = Target != nullptr
		? Target->FindComponentByClass<UJSBSimMovementComponent>()
		: nullptr;
}

FVector AFlightSimCameraDirector::TargetAimPoint(const FTransform& TargetTransform) const
{
	// CGLocalPosition is in the actor frame (cm), so the actor transform
	// carries it into the world -- the same arithmetic the scenario world
	// inverts to place the actor (Origin = TargetCG - R * CGLocalPosition).
	if (TargetMovement != nullptr)
	{
		return TargetTransform.TransformPosition(TargetMovement->CGLocalPosition);
	}
	return TargetTransform.GetLocation();
}

FVector AFlightSimCameraDirector::HeadingOffsetStation(const FVector& AimPoint,
                                                       const FTransform& TargetTransform,
                                                       const FVector& OffsetMetres)
{
	const FRotator TargetRotation = TargetTransform.GetRotation().Rotator();
	const FRotator HeadingOnly(0.0f, TargetRotation.Yaw, 0.0f);
	return AimPoint + HeadingOnly.RotateVector(OffsetMetres * CmPerMetre);
}

bool AFlightSimCameraDirector::PresetRestingPose(FVector& OutLocation,
                                                 FRotator& OutLook)
{
	if (Target == nullptr)
	{
		return false;
	}
	RefreshTargetMovement();
	const FTransform TargetTransform = Target->GetActorTransform();
	// Rest where the presets update from: the CG, never the datum.
	const FVector RestAimPoint = TargetAimPoint(TargetTransform);
	switch (Preset)
	{
	case EFlightSimCameraPreset::GroundObserver:
		OutLocation = ObserverLocationMetres * CmPerMetre;
		break;
	case EFlightSimCameraPreset::Tower:
		OutLocation = TowerLocationMetres * CmPerMetre;
		break;
	case EFlightSimCameraPreset::Wingman:
		OutLocation = HeadingOffsetStation(RestAimPoint, TargetTransform,
		                                   WingmanOffsetMetres);
		break;
	case EFlightSimCameraPreset::CockpitShoulder:
		// Body-fixed, exactly the placement UpdateCockpitShoulder makes:
		// full rotation, roll inherited by declaration.
		OutLocation = RestAimPoint + TargetTransform.GetRotation().RotateVector(
			ShoulderOffsetMetres * CmPerMetre);
		OutLook = TargetTransform.GetRotation().Rotator();
		return true;
	case EFlightSimCameraPreset::LaggedChase:
	default:
		OutLocation = HeadingOffsetStation(RestAimPoint, TargetTransform,
		                                   ChaseOffsetMetres);
		break;
	}
	OutLook = (RestAimPoint - OutLocation).Rotation();
	OutLook.Roll = 0.0f;              // never inherit roll
	return true;
}

bool AFlightSimCameraDirector::SetPoseTrack(TArray<double>&& Times,
                                            TArray<FVector>&& Locations,
                                            TArray<FRotator>&& Rotations,
                                            TArray<double>&& FocalLengthsMm,
                                            FString& Error)
{
	if (Times.Num() < 2)
	{
		Error = FString::Printf(
			TEXT("consume-poses: a track of %d sample(s) is not a track; "
			     "refusing to fly a camera nobody solved"), Times.Num());
		return false;
	}
	if (Times.Num() != Locations.Num() || Times.Num() != Rotations.Num() ||
	    Times.Num() != FocalLengthsMm.Num())
	{
		Error = FString::Printf(
			TEXT("consume-poses: %d times against %d locations, %d "
			     "rotations and %d focal lengths; refusing a misaligned "
			     "track"),
			Times.Num(), Locations.Num(), Rotations.Num(),
			FocalLengthsMm.Num());
		return false;
	}
	for (int32 i = 0; i < FocalLengthsMm.Num(); ++i)
	{
		if (!(FocalLengthsMm[i] > 0.0))
		{
			Error = FString::Printf(
				TEXT("consume-poses: solved focal length %.4f mm at sample "
				     "%d is not a lens; refusing to guess a field of view"),
				FocalLengthsMm[i], i);
			return false;
		}
	}
	for (int32 i = 1; i < Times.Num(); ++i)
	{
		if (Times[i] <= Times[i - 1])
		{
			Error = TEXT("consume-poses: track times must be strictly "
			             "increasing");
			return false;
		}
	}
	PoseTimes = MoveTemp(Times);
	PoseLocations = MoveTemp(Locations);
	PoseRotations = MoveTemp(Rotations);
	PoseFocalLengthsMm = MoveTemp(FocalLengthsMm);
	AppliedFocalLengthMm = PoseFocalLengthsMm[0];
	return true;
}

bool AFlightSimCameraDirector::ApplyPoseAtTime(double SimTimeSeconds,
                                               FString& Error)
{
	if (PoseTimes.Num() == 0)
	{
		Error = TEXT("consume-poses: no pose track is set");
		return false;
	}
	// Refuse, never extrapolate: a time outside the solved span would put
	// the camera at a pose that was never validated against the scene.
	const double Slack = 1.0e-6;
	if (SimTimeSeconds < PoseTimes[0] - Slack ||
	    SimTimeSeconds > PoseTimes.Last() + Slack)
	{
		Error = FString::Printf(
			TEXT("consume-poses: t=%.6f s lies outside the solved track "
			     "[%.6f, %.6f]; the track does not cover the run"),
			SimTimeSeconds, PoseTimes[0], PoseTimes.Last());
		return false;
	}
	int32 Upper = 1;
	while (Upper < PoseTimes.Num() - 1 && PoseTimes[Upper] < SimTimeSeconds)
	{
		++Upper;
	}
	const int32 Lower = Upper - 1;
	const double Span = PoseTimes[Upper] - PoseTimes[Lower];
	const double Fraction = Span > 0.0
		? FMath::Clamp((SimTimeSeconds - PoseTimes[Lower]) / Span, 0.0, 1.0)
		: 0.0;
	const FVector Location = FMath::Lerp(PoseLocations[Lower],
	                                     PoseLocations[Upper],
	                                     Fraction);
	const FQuat Rotation = FQuat::Slerp(
		PoseRotations[Lower].Quaternion(),
		PoseRotations[Upper].Quaternion(),
		static_cast<float>(Fraction));
	AppliedFocalLengthMm = FMath::Lerp(PoseFocalLengthsMm[Lower],
	                                   PoseFocalLengthsMm[Upper],
	                                   Fraction);
	// Sweep-free teleport: the camera is an observer, never a collider.
	SetActorLocationAndRotation(Location, Rotation, false, nullptr,
	                            ETeleportType::TeleportPhysics);
	// Solved-vs-applied parity, the gate5 discipline: anything that moved
	// the camera away from the solved pose (a clamp, a collision handler,
	// an attachment) FAILS LOUDLY here rather than rendering frames whose
	// recorded geometry is quietly wrong. 10 cm on a cinema camera is
	// already generous.
	const FVector Applied = GetActorLocation();
	if (!Applied.Equals(Location, PositionToleranceCm))
	{
		Error = FString::Printf(
			TEXT("consume-poses: applied camera position (%.1f, %.1f, %.1f) "
			     "differs from the solved pose (%.1f, %.1f, %.1f) by more "
			     "than %.3g cm at t=%.3f s; refusing to record geometry "
			     "the frames do not have"),
			Applied.X, Applied.Y, Applied.Z,
			Location.X, Location.Y, Location.Z,
			PositionToleranceCm, SimTimeSeconds);
		return false;
	}
	// Position parity alone let a rotation divergence through, and where
	// the camera LOOKS is most of the label: a tenth of a degree at a
	// kilometre is nearly two metres of misplaced world. Same doctrine,
	// same loudness.
	const double RotationErrorDeg =
		RotationErrorDegrees(GetActorQuat(), Rotation);
	if (RotationErrorDeg > RotationToleranceDeg)
	{
		Error = FString::Printf(
			TEXT("consume-poses: applied camera rotation differs from the "
			     "solved pose by %.4f deg at t=%.3f s (tolerance %.3g "
			     "deg); refusing to record an orientation the frames do "
			     "not have"),
			RotationErrorDeg, SimTimeSeconds, RotationToleranceDeg);
		return false;
	}
	return true;
}

void AFlightSimCameraDirector::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (ConsumingPoses())
	{
		// Consume-poses mode: the commandlet drives this actor by
		// simulation time (ApplyPoseAtTime); computing a preset here
		// would fight the solved track frame by frame.
		return;
	}

	if (Target == nullptr || DeltaSeconds <= 0.0f)
	{
		return;
	}

	RefreshTargetMovement();
	const FTransform TargetTransform = Target->GetActorTransform();
	// Every preset aims at, and offsets from, the CG (see TargetAimPoint).
	const FVector AimPoint = TargetAimPoint(TargetTransform);

	if (!bInitialised)
	{
		SmoothedLocation = GetActorLocation();
		SmoothedAimPoint = AimPoint;
		bInitialised = true;
	}

	switch (Preset)
	{
	case EFlightSimCameraPreset::GroundObserver:
		UpdateFixedPoint(DeltaSeconds, ObserverLocationMetres * CmPerMetre,
		                 AimPoint);
		break;
	case EFlightSimCameraPreset::Tower:
		UpdateFixedPoint(DeltaSeconds, TowerLocationMetres * CmPerMetre,
		                 AimPoint);
		break;
	case EFlightSimCameraPreset::Wingman:
		UpdateWingman(DeltaSeconds, TargetTransform);
		break;
	case EFlightSimCameraPreset::CockpitShoulder:
		UpdateCockpitShoulder(TargetTransform);
		break;
	case EFlightSimCameraPreset::LaggedChase:
	default:
		UpdateLaggedChase(DeltaSeconds, TargetTransform);
		break;
	}
}

void AFlightSimCameraDirector::UpdateLaggedChase(float DeltaSeconds,
                                                 const FTransform& TargetTransform)
{
	// Offset from the CG, as the Python solver states it -- not from the
	// actor origin, which is the structural datum -- in the heading-only
	// frame (HeadingOffsetStation: yaw kept, pitch and roll discarded).
	const FVector AimPoint = TargetAimPoint(TargetTransform);
	const FVector Goal = HeadingOffsetStation(AimPoint, TargetTransform,
	                                          ChaseOffsetMetres);

	SmoothedLocation = SmoothTowards(SmoothedLocation, Goal, DeltaSeconds,
	                                 PositionLagSeconds);
	SmoothedAimPoint = SmoothTowards(SmoothedAimPoint, AimPoint,
	                                 DeltaSeconds, AimLagSeconds);

	SetActorLocation(SmoothedLocation);

	FRotator Look = (SmoothedAimPoint - SmoothedLocation).Rotation();
	Look.Roll = 0.0f;                 // never inherit roll
	SetActorRotation(Look);
}

void AFlightSimCameraDirector::UpdateCockpitShoulder(
	const FTransform& TargetTransform)
{
	// Body-fixed, no smoothing: the camera IS part of the airframe for this
	// preset, so lagging it would invent relative motion that does not
	// exist. Full rotation applied -- roll inherited, BY DECLARATION
	// (PresetKeepsHorizonLevel() is false; the manifest records it). In this
	// frame the aircraft never moves and the world banks; nothing recorded
	// from this camera may be graded as aircraft motion.
	const FQuat Rotation = TargetTransform.GetRotation();
	// Body-frame offset from the CG (the solver's origin), not the datum.
	SetActorLocation(TargetAimPoint(TargetTransform)
	                 + Rotation.RotateVector(ShoulderOffsetMetres * CmPerMetre));
	SetActorRotation(Rotation);
}

void AFlightSimCameraDirector::UpdateFixedPoint(float DeltaSeconds,
                                                const FVector& WorldLocation,
                                                const FVector& TargetLocation)
{
	// World-anchored: the camera does not move at all. Everything seen is the
	// aircraft actually moving, which is the strongest possible answer to
	// "did the attitude change or did the camera?".
	SetActorLocation(WorldLocation);

	SmoothedAimPoint = SmoothTowards(SmoothedAimPoint, TargetLocation,
	                                 DeltaSeconds, AimLagSeconds);
	FRotator Look = (SmoothedAimPoint - WorldLocation).Rotation();
	Look.Roll = 0.0f;
	SetActorRotation(Look);
}

void AFlightSimCameraDirector::UpdateWingman(float DeltaSeconds,
                                             const FTransform& TargetTransform)
{
	const FVector AimPoint = TargetAimPoint(TargetTransform);
	const FVector Goal = HeadingOffsetStation(AimPoint, TargetTransform,
	                                          WingmanOffsetMetres);

	// Station-keeping is tighter than a chase: a wingman holds position.
	SmoothedLocation = SmoothTowards(SmoothedLocation, Goal, DeltaSeconds,
	                                 PositionLagSeconds * 0.5f);
	SmoothedAimPoint = SmoothTowards(SmoothedAimPoint, AimPoint,
	                                 DeltaSeconds, AimLagSeconds);

	SetActorLocation(SmoothedLocation);
	FRotator Look = (SmoothedAimPoint - SmoothedLocation).Rotation();
	Look.Roll = 0.0f;
	SetActorRotation(Look);
}
