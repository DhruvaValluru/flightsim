// The pre-rendered impostor clouds (2026-11-14). See FlightSimImpostorClouds.h and
// scripts/cloud_impostor_math.py (the conventions; tests/test_cloud_impostors.py
// pins the constants below equal to the Python twin's). UNCOMPILED here (no engine on
// the Mac); every amount UNCALIBRATED until a Windows render is judged.

#include "FlightSimImpostorClouds.h"

#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"
#include "Math/RotationMatrix.h"
#include "Misc/Parse.h"
#include "ProceduralMeshComponent.h"

namespace
{
	// Named distinctly (unity builds merge the anonymous namespaces into one unit).
	const TCHAR* const ImpostorInstancePrefix = TEXT("/Game/FlightSim/MI_FlightSimCloudImpostor_");
	constexpr int32 ImpostorMaxBakedClouds = 16;
	constexpr double ImpostorCmPerMetre = 100.0;
	// cloud_impostor_math.py: CUMULUS_MIN_THICKNESS_M, MIN_COVER, INSTANCES_AT_FULL_COVER,
	// MAX_INSTANCES, RING_INNER_M, RING_OUTER_M, HEIGHT_SHARE, KEEP_OUT_MARGIN_M.
	constexpr double ImpostorCumulusMinThicknessM = 400.0;
	constexpr double ImpostorMinCover = 0.05;
	constexpr int32 ImpostorInstancesAtFullCover = 40;
	constexpr int32 ImpostorMaxInstancesPilot = 12;
	constexpr int32 ImpostorMaxInstancesOn = 40;
	constexpr double ImpostorRingInnerM = 1500.0;
	constexpr double ImpostorRingOuterM = 15000.0;
	constexpr double ImpostorHeightShareMin = 0.6;
	constexpr double ImpostorHeightShareMax = 1.0;
	constexpr double ImpostorKeepOutMarginM = 150.0;
	constexpr int32 ImpostorSeedSalt = 0x51C10D;

	// World (UE: x forward, y right, z up) -> cloud object space (Blender: right-handed,
	// z up): rotate by -Yaw about z, then y -> -y; and back.
	FVector ImpostorWorldToObject(const FVector& V, double Yaw)
	{
		const double C = FMath::Cos(-Yaw);
		const double S = FMath::Sin(-Yaw);
		return FVector(C * V.X - S * V.Y, -(S * V.X + C * V.Y), V.Z);
	}

	FVector ImpostorObjectToWorld(const FVector& V, double Yaw)
	{
		const double X = V.X;
		const double Y = -V.Y;
		const double C = FMath::Cos(Yaw);
		const double S = FMath::Sin(Yaw);
		return FVector(C * X - S * Y, S * X + C * Y, V.Z);
	}

	// cloud_impostor_math.frame_basis: forward -d, up from z (y within 0.001 of a pole).
	void ImpostorFrameBasis(const FVector& D, FVector& OutRight, FVector& OutUp)
	{
		const FVector Forward = -D;
		const FVector UpRef = FMath::Abs(D.Z) > 0.999 ? FVector(0.0, 1.0, 0.0) : FVector(0.0, 0.0, 1.0);
		OutRight = FVector::CrossProduct(Forward, UpRef).GetSafeNormal();
		OutUp = FVector::CrossProduct(OutRight, Forward);
	}

	// cloud_impostor_math.keep_out, in cm.
	bool ImpostorKeptOut(const FVector& Centre, double Radius, const FVector& Camera, const FVector& Aircraft,
	                     double AircraftRadius)
	{
		const FVector Seg = Aircraft - Camera;
		const double Length2 = Seg.SizeSquared();
		const double T = Length2 <= 0.0 ? 0.0 : FMath::Clamp(FVector::DotProduct(Centre - Camera, Seg) / Length2, 0.0, 1.0);
		const FVector Nearest = Camera + T * Seg;
		return FVector::Dist(Centre, Nearest) < Radius + AircraftRadius + ImpostorKeepOutMarginM * ImpostorCmPerMetre;
	}
}

bool FFlightSimImpostorClouds::ParseMode(const FString& Switches, FString& OutMode, FString& Error)
{
	FString Value = TEXT("off");
	FParse::Value(*Switches, TEXT("cloud-impostors="), Value);
	if (Value != TEXT("off") && Value != TEXT("pilot") && Value != TEXT("on"))
	{
		Error = FString::Printf(TEXT("cloud.impostor_switch: -cloud-impostors=%s is not off, pilot or on"), *Value);
		return false;
	}
	OutMode = Value;
	return true;
}

bool FFlightSimImpostorClouds::Build(UWorld* World, const FFlightSimImpostorCloudOptions& Options, FString& Error)
{
	Record = MakeShared<FJsonObject>();
	Record->SetStringField(TEXT("mode"), Options.Mode);
	if (Options.Mode == TEXT("off") || World == nullptr)
	{
		Record->SetStringField(TEXT("drawn"), TEXT("nothing: -cloud-impostors=off"));
		return true;
	}
	// The baked clouds: one instance material per cloud (scripts/ue_create_materials.py).
	TArray<UMaterialInterface*> Baked;
	TArray<double> SphereOverHeight;
	for (int32 I = 0; I < ImpostorMaxBakedClouds; ++I)
	{
		const FString Name = FString::Printf(TEXT("MI_FlightSimCloudImpostor_cloud%02d"), I);
		const FString Path = FString::Printf(TEXT("%scloud%02d.%s"), ImpostorInstancePrefix, I, *Name);
		UMaterialInterface* Instance = LoadObject<UMaterialInterface>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
		if (Instance == nullptr)
		{
			continue;
		}
		float Ratio = 2.0f;
		Instance->GetScalarParameterValue(FHashedMaterialParameterInfo(FName(TEXT("SphereOverHeight"))), Ratio);
		Baked.Add(Instance);
		SphereOverHeight.Add(FMath::Max(1.0, static_cast<double>(Ratio)));
	}
	if (Baked.Num() == 0)
	{
		Error = TEXT("cloud.impostor_assets: -cloud-impostors=") + Options.Mode
			+ TEXT(" found no MI_FlightSimCloudImpostor_cloudNN (bake with scripts/bake_cloud_impostors.py, commit "
			       "assets/looks/clouds/impostors, run scripts/ue_create_materials.py), or render with -cloud-impostors=off");
		return false;
	}
	const int32 Cap = Options.Mode == TEXT("pilot") ? ImpostorMaxInstancesPilot : ImpostorMaxInstancesOn;
	FRandomStream Stream(static_cast<int32>((Options.Seed ^ ImpostorSeedSalt) & 0x7FFFFFFF));
	TArray<TSharedPtr<FJsonValue>> LayerRows;
	for (const FFlightSimCloudLayer& Layer : Options.Layers)
	{
		const double Thickness = Layer.TopMetres - Layer.BaseMetres;
		int32 Count = 0;
		if (Thickness >= ImpostorCumulusMinThicknessM && Layer.CoverFraction >= ImpostorMinCover)
		{
			Count = FMath::Clamp(FMath::RoundToInt(Layer.CoverFraction * ImpostorInstancesAtFullCover), 0, Cap);
		}
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetNumberField(TEXT("cover"), Layer.CoverFraction);
		Row->SetNumberField(TEXT("base_m"), Layer.BaseMetres);
		Row->SetNumberField(TEXT("top_m"), Layer.TopMetres);
		Row->SetNumberField(TEXT("instances"), Count);
		LayerRows.Add(MakeShared<FJsonValueObject>(Row));
		for (int32 K = 0; K < Count && Instances.Num() < Cap; ++K)
		{
			const double A = Stream.FRandRange(0.0, 2.0 * PI);
			const double R = FMath::Sqrt(Stream.FRandRange(ImpostorRingInnerM * ImpostorRingInnerM,
			                                               ImpostorRingOuterM * ImpostorRingOuterM));
			const double HeightM = Thickness * Stream.FRandRange(ImpostorHeightShareMin, ImpostorHeightShareMax);
			const int32 Cloud = FMath::Clamp(Stream.RandRange(0, Baked.Num() - 1), 0, Baked.Num() - 1);
			FInstance Inst;
			Inst.Yaw = Stream.FRandRange(0.0, 2.0 * PI);
			Inst.RadiusCm = 0.5 * SphereOverHeight[Cloud] * HeightM * ImpostorCmPerMetre;
			Inst.CentreCm = FVector(Options.AircraftCm.X + R * FMath::Cos(A) * ImpostorCmPerMetre,
			                        Options.AircraftCm.Y + R * FMath::Sin(A) * ImpostorCmPerMetre,
			                        (Layer.BaseMetres + 0.5 * HeightM) * ImpostorCmPerMetre);
			AActor* Actor = World->SpawnActor<AActor>();
			UProceduralMeshComponent* Quad = NewObject<UProceduralMeshComponent>(
				Actor, *FString::Printf(TEXT("CloudImpostor%02d"), Instances.Num()));
			Actor->SetRootComponent(Quad);
			Quad->SetMobility(EComponentMobility::Movable);
			const double H = Inst.RadiusCm;
			// Local Y = the frame's right, local Z = its up; u right, v down (cloud_impostor.hlsl).
			const TArray<FVector> Vertices = {FVector(0.0, -H, H), FVector(0.0, H, H), FVector(0.0, H, -H),
			                                  FVector(0.0, -H, -H)};
			const TArray<int32> Triangles = {0, 1, 2, 0, 2, 3};
			const TArray<FVector2D> UV0 = {FVector2D(0.0, 0.0), FVector2D(1.0, 0.0), FVector2D(1.0, 1.0),
			                               FVector2D(0.0, 1.0)};
			Quad->CreateMeshSection_LinearColor(0, Vertices, Triangles, {}, UV0, {}, {}, false /* no collision */);
			Quad->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Quad->SetCastShadow(false);
			UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Baked[Cloud], Quad);
			Material->SetScalarParameterValue(TEXT("Yaw"), static_cast<float>(Inst.Yaw));
			Material->SetScalarParameterValue(TEXT("SphereRadiusCm"), static_cast<float>(Inst.RadiusCm));
			Material->SetScalarParameterValue(TEXT("Opacity"), 1.0f);
			Quad->SetMaterial(0, Material);
			Quad->RegisterComponent();
			Actor->SetActorLocation(Inst.CentreCm);
			Actor->Tags.Add(FName(TEXT("FlightSim.cloud_impostor")));
			Inst.Actor = Actor;
			Inst.Quad = Quad;
			BeautyOnlyActors.Add(Actor);
			Instances.Add(Inst);
		}
	}
	Record->SetArrayField(TEXT("layers"), LayerRows);
	Record->SetNumberField(TEXT("instances"), Instances.Num());
	Record->SetNumberField(TEXT("baked_clouds"), Baked.Num());
	Record->SetNumberField(TEXT("cap"), Cap);
	Record->SetStringField(TEXT("drawn"), Instances.Num() > 0
		? TEXT("impostor quads, beauty only (BeautyOnlyActors), keep-out around the camera->aircraft line")
		: TEXT("nothing: no cumulus-like layer (thickness >= 400 m, cover >= 0.05) on this card"));
	Record->SetStringField(TEXT("source"),
		TEXT("JangaFX EmberGen Cloud Pack (CC0), baked once by scripts/bake_cloud_impostors.py; THIRD_PARTY_VISUAL.md"));
	Record->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: SunGain, AmbientGain, fades, placement"));
	bBuilt = true;
	return true;
}

void FFlightSimImpostorClouds::Advance(const FVector& CameraCm, const FVector& AircraftCm, double AircraftRadiusCm)
{
	if (!bBuilt)
	{
		return;
	}
	int32 Hidden = 0;
	for (FInstance& Inst : Instances)
	{
		if (Inst.Quad == nullptr)
		{
			continue;
		}
		const bool bHide = ImpostorKeptOut(Inst.CentreCm, Inst.RadiusCm, CameraCm, AircraftCm, AircraftRadiusCm);
		if (bHide != Inst.bHidden)
		{
			Inst.Quad->SetVisibility(!bHide);
			Inst.bHidden = bHide;
		}
		Hidden += bHide ? 1 : 0;
		const FVector ToCamera = (CameraCm - Inst.CentreCm).GetSafeNormal();
		if (ToCamera.IsNearlyZero())
		{
			continue;
		}
		FVector RightObj;
		FVector UpObj;
		ImpostorFrameBasis(ImpostorWorldToObject(ToCamera, Inst.Yaw).GetSafeNormal(), RightObj, UpObj);
		const FVector Right = ImpostorObjectToWorld(RightObj, Inst.Yaw);
		const FVector Up = ImpostorObjectToWorld(UpObj, Inst.Yaw);
		Inst.Quad->SetWorldRotation(FRotationMatrix::MakeFromYZ(Right, Up).Rotator());
	}
	KeptOutFrames += Hidden > 0 ? 1 : 0;
	if (Record.IsValid())
	{
		Record->SetNumberField(TEXT("frames_with_a_kept_out_instance"), KeptOutFrames);
	}
}
