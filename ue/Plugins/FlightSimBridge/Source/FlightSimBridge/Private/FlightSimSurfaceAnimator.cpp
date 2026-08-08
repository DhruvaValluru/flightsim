#include "FlightSimSurfaceAnimator.h"

#include "Components/SceneComponent.h"
#include "JSBSimMovementComponent.h"

UFlightSimSurfaceAnimator::UFlightSimSurfaceAnimator()
{
	PrimaryComponentTick.bCanEverTick = true;
	// After the FDM has stepped, so the surfaces show this frame's state.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
	ApplyDefaultBindings();
}

void UFlightSimSurfaceAnimator::ApplyDefaultBindings()
{
	Bindings.Empty();

	auto Add = [this](const TCHAR* Property, const TCHAR* Bone,
	                  float Scale, const FVector& Axis)
	{
		FFlightSimSurfaceBinding Binding;
		Binding.PropertyName = Property;
		Binding.BoneName = FName(Bone);
		Binding.DegreesPerUnit = Scale;
		Binding.RotationAxis = Axis;
		Bindings.Add(Binding);
	};

	constexpr float RadToDeg = 57.2957795f;
	Add(TEXT("fcs/elevator-pos-rad"),       TEXT("elevator"),   RadToDeg, FVector(0, 1, 0));
	Add(TEXT("fcs/left-aileron-pos-rad"),   TEXT("aileron_l"),  RadToDeg, FVector(0, 1, 0));
	Add(TEXT("fcs/right-aileron-pos-rad"),  TEXT("aileron_r"),  RadToDeg, FVector(0, 1, 0));
	Add(TEXT("fcs/rudder-pos-rad"),         TEXT("rudder"),     RadToDeg, FVector(0, 0, 1));
	// Flap and gear are already in engineering units, so they map 1:1.
	Add(TEXT("fcs/flap-pos-deg"),           TEXT("flap"),       1.0f,     FVector(0, 1, 0));
	Add(TEXT("gear/gear-pos-norm"),         TEXT("gear"),       90.0f,    FVector(0, 1, 0));
}

void UFlightSimSurfaceAnimator::AddBinding(const FString& Property, FName Bone,
                                           float DegreesPerUnit, const FVector& Axis,
                                           bool bContinuous)
{
	FFlightSimSurfaceBinding Binding;
	Binding.PropertyName = Property;
	Binding.BoneName = Bone;
	Binding.DegreesPerUnit = DegreesPerUnit;
	Binding.RotationAxis = Axis;
	Binding.bContinuous = bContinuous;
	Bindings.Add(Binding);
}

void UFlightSimSurfaceAnimator::TickComponent(
	float DeltaTime, ELevelTick TickType,
	FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

	if (Movement == nullptr)
	{
		return;
	}

	PeakDeflection = 0.0f;
	for (FFlightSimSurfaceBinding& Binding : Bindings)
	{
		FString Value;
		// CommandConsole with an empty input value is a READ (§3.1). Observers
		// do not write to the FDM.
		Movement->CommandConsole(Binding.PropertyName, FString(), Value);
		if (Value.IsEmpty())
		{
			// The property does not exist on this airframe. Left at zero and
			// skipped rather than defaulted to something that would animate.
			continue;
		}
		Binding.CurrentValue = FCString::Atof(*Value);
		if (Binding.bContinuous)
		{
			// A rate, integrated: rpm x (deg/s per rpm) x dt, wrapped so the
			// float never grows without bound over a long clip.
			Binding.AccumulatedDegrees = FMath::Fmod(
				Binding.AccumulatedDegrees
					+ Binding.CurrentValue * Binding.DegreesPerUnit * DeltaTime,
				360.0f);
			Binding.DeflectionDegrees = Binding.AccumulatedDegrees;
		}
		else
		{
			Binding.DeflectionDegrees = Binding.CurrentValue * Binding.DegreesPerUnit;
		}
		Binding.PeakDeflectionDegrees = FMath::Max(Binding.PeakDeflectionDegrees,
		                                           FMath::Abs(Binding.DeflectionDegrees));
		// Continuous bindings do not participate in the peak-deflection
		// clause: a spinning propeller must not let a frozen elevator pass
		// the something-moved check.
		if (!Binding.bContinuous)
		{
			PeakDeflection = FMath::Max(PeakDeflection,
			                            FMath::Abs(Binding.DeflectionDegrees));
		}

		// The line that makes this an animator rather than a meter. Everything
		// above reads; this is the only write, and it writes to the scene, not
		// to the FDM.
		if (Binding.TargetComponent != nullptr)
		{
			const FQuat Hinge(Binding.RotationAxis.GetSafeNormal(),
			                  FMath::DegreesToRadians(Binding.DeflectionDegrees));
			Binding.TargetComponent->SetRelativeRotation(
				Binding.NeutralRotation.Quaternion() * Hinge);
		}
	}

	if (PeakDeflection > 0.01f)
	{
		bAnySurfaceMoved = true;
	}
}

float UFlightSimSurfaceAnimator::GetPeakDeflectionDegrees() const
{
	return PeakDeflection;
}

bool UFlightSimSurfaceAnimator::BindSurfaceComponent(FName Surface,
                                                     USceneComponent* Component)
{
	for (FFlightSimSurfaceBinding& Binding : Bindings)
	{
		if (Binding.BoneName == Surface)
		{
			Binding.TargetComponent = Component;
			Binding.NeutralRotation =
				Component ? Component->GetRelativeRotation() : FRotator::ZeroRotator;
			return true;
		}
	}
	return false;
}

int32 UFlightSimSurfaceAnimator::GetBoundSurfaceCount() const
{
	int32 Count = 0;
	for (const FFlightSimSurfaceBinding& Binding : Bindings)
	{
		if (Binding.TargetComponent != nullptr)
		{
			++Count;
		}
	}
	return Count;
}
