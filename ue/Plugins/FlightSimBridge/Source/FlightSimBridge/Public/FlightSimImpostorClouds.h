// The pre-rendered impostor clouds (2026-11-14): JangaFX's CC0 cloud VDBs baked ONCE
// in Blender Cycles into octahedral six-way atlases (scripts/bake_cloud_impostors.py),
// drawn in the BEAUTY capture as camera-facing quads (M_FlightSimCloudImpostor /
// cloud_impostor.hlsl). -cloud-impostors=off|pilot|on (off by default; the command
// line or FLIGHTSIM_RENDER_SWITCHES). Beauty only: every quad's actor joins
// VisualScene.BeautyOnlyActors before any label capture is configured, so the ID,
// class, mask, depth and box passes and every measure render are byte-identical.
// The conventions (placement, keep-out, frame basis) are scripts/cloud_impostor_math.py's.

#pragma once

#include "CoreMinimal.h"
#include "FlightSimVisualScene.h"

class AActor;
class UMaterialInstanceDynamic;
class UProceduralMeshComponent;
class UWorld;
class FJsonObject;

struct FFlightSimImpostorCloudOptions
{
	FString Mode = TEXT("off");               // off | pilot | on
	TArray<FFlightSimCloudLayer> Layers;      // the card's cloud layers (heights above the ground datum)
	FVector AircraftCm = FVector::ZeroVector; // the aircraft's first position (the ring's centre)
	int32 Seed = 0;
};

class FLIGHTSIMBRIDGE_API FFlightSimImpostorClouds
{
public:
	// -cloud-impostors=off|pilot|on; another word refuses by name (cloud.impostor_switch).
	static bool ParseMode(const FString& Switches, FString& OutMode, FString& Error);

	// Places the instances (nothing under off). Refuses by name (cloud.impostor_assets)
	// when pilot|on finds no baked instance material.
	bool Build(UWorld* World, const FFlightSimImpostorCloudOptions& Options, FString& Error);

	// Per frame: every quad turned to face the camera in the bake's frame basis, and
	// hidden while it could cover the aircraft (the keep-out).
	void Advance(const FVector& CameraCm, const FVector& AircraftCm, double AircraftRadiusCm);

	bool IsBuilt() const { return bBuilt; }

	TArray<AActor*> BeautyOnlyActors;
	TSharedPtr<FJsonObject> Record;

private:
	struct FInstance
	{
		AActor* Actor = nullptr;
		UProceduralMeshComponent* Quad = nullptr;
		FVector CentreCm = FVector::ZeroVector;
		double RadiusCm = 0.0;
		double Yaw = 0.0;
		bool bHidden = false;
	};
	TArray<FInstance> Instances;
	bool bBuilt = false;
	int32 KeptOutFrames = 0;
};
