#include "FlightSimSurfaceAnimator.h"

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
		Binding.DeflectionDegrees = Binding.CurrentValue * Binding.DegreesPerUnit;
		PeakDeflection = FMath::Max(PeakDeflection,
		                            FMath::Abs(Binding.DeflectionDegrees));
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
