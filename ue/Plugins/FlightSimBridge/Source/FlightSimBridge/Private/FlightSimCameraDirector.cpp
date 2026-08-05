#include "FlightSimCameraDirector.h"

#include "CineCameraComponent.h"

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
	default:
		return false;
	}
}

float AFlightSimCameraDirector::GetCameraRollDegrees() const
{
	return GetActorRotation().Roll;
}

void AFlightSimCameraDirector::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (Target == nullptr || DeltaSeconds <= 0.0f)
	{
		return;
	}

	const FTransform TargetTransform = Target->GetActorTransform();

	if (!bInitialised)
	{
		SmoothedLocation = GetActorLocation();
		SmoothedAimPoint = TargetTransform.GetLocation();
		bInitialised = true;
	}

	switch (Preset)
	{
	case EFlightSimCameraPreset::GroundObserver:
		UpdateFixedPoint(DeltaSeconds, ObserverLocationMetres * CmPerMetre,
		                 TargetTransform.GetLocation());
		break;
	case EFlightSimCameraPreset::Tower:
		UpdateFixedPoint(DeltaSeconds, TowerLocationMetres * CmPerMetre,
		                 TargetTransform.GetLocation());
		break;
	case EFlightSimCameraPreset::Wingman:
		UpdateWingman(DeltaSeconds, TargetTransform);
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
	// The offset is applied in a HEADING-ONLY frame: yaw is taken from the
	// aircraft so the camera stays behind it through a turn, but pitch and roll
	// are discarded. Using the full rotation here is precisely the mistake --
	// the camera would roll with the aircraft and the roll would vanish.
	const FRotator TargetRotation = TargetTransform.GetRotation().Rotator();
	const FRotator HeadingOnly(0.0f, TargetRotation.Yaw, 0.0f);

	const FVector Goal = TargetTransform.GetLocation()
		+ HeadingOnly.RotateVector(ChaseOffsetMetres * CmPerMetre);

	SmoothedLocation = SmoothTowards(SmoothedLocation, Goal, DeltaSeconds,
	                                 PositionLagSeconds);
	SmoothedAimPoint = SmoothTowards(SmoothedAimPoint,
	                                 TargetTransform.GetLocation(),
	                                 DeltaSeconds, AimLagSeconds);

	SetActorLocation(SmoothedLocation);

	FRotator Look = (SmoothedAimPoint - SmoothedLocation).Rotation();
	Look.Roll = 0.0f;                 // never inherit roll
	SetActorRotation(Look);
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
	const FRotator TargetRotation = TargetTransform.GetRotation().Rotator();
	const FRotator HeadingOnly(0.0f, TargetRotation.Yaw, 0.0f);

	const FVector Goal = TargetTransform.GetLocation()
		+ HeadingOnly.RotateVector(WingmanOffsetMetres * CmPerMetre);

	// Station-keeping is tighter than a chase: a wingman holds position.
	SmoothedLocation = SmoothTowards(SmoothedLocation, Goal, DeltaSeconds,
	                                 PositionLagSeconds * 0.5f);
	SmoothedAimPoint = SmoothTowards(SmoothedAimPoint,
	                                 TargetTransform.GetLocation(),
	                                 DeltaSeconds, AimLagSeconds);

	SetActorLocation(SmoothedLocation);
	FRotator Look = (SmoothedAimPoint - SmoothedLocation).Rotation();
	Look.Roll = 0.0f;
	SetActorRotation(Look);
}
