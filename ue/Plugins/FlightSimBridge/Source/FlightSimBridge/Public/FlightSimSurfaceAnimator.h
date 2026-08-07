// Drive control surfaces from JSBSim's own state, every frame.
//
// ASSUMPTIONS §1.5: "No control surface moved anywhere in the clip." A viewer
// reads moving surfaces as "something is being flown" and static surfaces as
// "this is an animation", so this is not decoration -- it is the difference
// between showing a simulation and showing a recording of one.
//
// The values are READ from the FDM (§2.1). Nothing here computes a deflection;
// if a surface is not moving on screen it is because the aircraft is not
// commanding it, and that is information rather than a rendering bug.

#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "FlightSimSurfaceAnimator.generated.h"

class UJSBSimMovementComponent;

// One surface: which JSBSim property drives it, and how that maps to a bone.
USTRUCT(BlueprintType)
struct FFlightSimSurfaceBinding
{
	GENERATED_BODY()

	// e.g. "fcs/left-aileron-pos-rad". Positions, not commands: a command is
	// what was asked for, a position is where the actuator actually is, and
	// actuator lag is part of what makes motion read as mechanical.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	FString PropertyName;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	FName BoneName;

	// Degrees of bone rotation per unit of the property. Radian-valued
	// properties want ~57.3; normalised ones want the full travel.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	float DegreesPerUnit = 57.2957795f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	FVector RotationAxis = FVector(0.0f, 1.0f, 0.0f);

	// Latest value read from the FDM, for inspection and for the burn-in.
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "FlightSim")
	float CurrentValue = 0.0f;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "FlightSim")
	float DeflectionDegrees = 0.0f;

	// The thing that actually moves on screen. A binding with no target and no
	// skeletal mesh computes a number and rotates nothing, which is precisely
	// the failure §1.5 describes -- so the animator counts how many bindings
	// are attached to something and the burn-in checks it.
	UPROPERTY(Transient, VisibleAnywhere, BlueprintReadOnly, Category = "FlightSim")
	TObjectPtr<USceneComponent> TargetComponent = nullptr;

	// Where the surface sits at zero deflection. Deflection is applied as an
	// offset from here, so a surface mounted at an angle stays mounted at it.
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	FRotator NeutralRotation = FRotator::ZeroRotator;

	// Largest absolute deflection this binding has reached over the run.
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "FlightSim")
	float PeakDeflectionDegrees = 0.0f;
};

UCLASS(ClassGroup = (FlightSim), meta = (BlueprintSpawnableComponent))
class FLIGHTSIMBRIDGE_API UFlightSimSurfaceAnimator : public UActorComponent
{
	GENERATED_BODY()

public:
	UFlightSimSurfaceAnimator();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType,
	                           FActorComponentTickFunction* ThisTickFunction) override;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	UJSBSimMovementComponent* Movement = nullptr;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "FlightSim")
	TArray<FFlightSimSurfaceBinding> Bindings;

	// The stock set. Every one is a position property (§6.1).
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	void ApplyDefaultBindings();

	// Replace the stock set with an empty table. A real aircraft mesh brings
	// its own binding table from its manifest (several surfaces can share one
	// property -- both elevators, inner and outer ailerons); mixing that with
	// the defaults would leave same-named bones ambiguous.
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	void ClearBindings() { Bindings.Empty(); }

	// One binding from a mesh manifest: which property, which bone, how many
	// degrees per unit (sign carries the FG model's hinge sense), about which
	// axis. Axis is in the actor frame, as the manifest states it.
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	void AddBinding(const FString& Property, FName Bone, float DegreesPerUnit,
	                const FVector& Axis);

	// Largest absolute deflection across all surfaces this frame. The burn-in
	// asserts this is non-zero over a run: a clip in which no surface ever
	// moved is the §1.5 failure, and it is silent unless something looks.
	UFUNCTION(BlueprintPure, Category = "FlightSim")
	float GetPeakDeflectionDegrees() const;

	UFUNCTION(BlueprintPure, Category = "FlightSim")
	bool AnySurfaceHasMoved() const { return bAnySurfaceMoved; }

	// Attach a binding to something that will be drawn. Named by the bone name
	// the binding already carries, so the same binding table serves a skeletal
	// mesh and a component-built airframe.
	UFUNCTION(BlueprintCallable, Category = "FlightSim")
	bool BindSurfaceComponent(FName Surface, USceneComponent* Component);

	// How many bindings will move something on screen. Zero means the animator
	// is computing deflections into the void.
	UFUNCTION(BlueprintPure, Category = "FlightSim")
	int32 GetBoundSurfaceCount() const;

private:
	bool bAnySurfaceMoved = false;
	float PeakDeflection = 0.0f;
};
