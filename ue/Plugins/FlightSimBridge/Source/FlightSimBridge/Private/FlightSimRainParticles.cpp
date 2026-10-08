// The rain the camera sees: the run card's rain_particles block
// (core/scene/rain_particles.py writes it; VISUAL ONLY -- nothing here
// reaches the flight model).
//
// Real 3-D drops, not a screen overlay: one instance of the engine's
// cylinder per drop in a single UInstancedStaticMeshComponent, M_RainDrop
// (lit translucent water, scripts/ue_create_materials.py) on it. Being
// geometry in the scene, the drops are occluded by the aircraft and the
// ground, lit by the sun and the sky, fogged and depth-of-field blurred
// at their range like everything else the beauty capture draws.
//
// * the drops: a world-aligned cube box_m a side, centred half a side
//   ahead of the camera along its view, recentred every frame. Each drop
//   has a seeded origin in the box, a diameter from the truncated
//   Marshall-Palmer law (RainDropDiameterMm, the inverse CDF the Python
//   module states) and an Atlas fall speed; at the FDM's time t it is at
//   origin - v t z, wrapped into the box (RainWrap), so the field is
//   fixed in the world and the camera flies through it.
// * the streak: the drop's motion relative to the camera over the block's
//   streak exposure, as the cylinder's axis and length (a drop slower than
//   its own width is drawn as a dot). The width is the drop's diameter,
//   floored at min_width_px of the pixel footprint at its range; the
//   per-instance custom float 0 (the material's opacity factor) is the
//   share of that width the drop covers, so a sub-pixel drop adds only the
//   light it physically would.
// * beauty-only: the rain actor is in BeautyOnlyActors, so the label
//   captures (ConfigureLabelCapture hides them) and the stencil loop never
//   see it: masks, classes and depths are unchanged by the rain.
//
// A missing mesh or material is RECORDED in look_applied.rain_particles,
// never refused: the rain is visual only and the run it decorates is
// still the run.
//
// UNCOMPILED when written (no engine on the authoring machine): the first
// Windows build verifies it; tests/test_rain_particles.py pins its text.

#include "FlightSimVisualScene.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"

namespace
{
	constexpr double RainCmPerMetre = 100.0;
	constexpr double RainCmPerMm = 0.1;
	// /Engine/BasicShapes/Cylinder: 100 cm across, 100 cm along local Z,
	// pivot at its centre.
	const TCHAR* const RainDropMeshPath = TEXT("/Engine/BasicShapes/Cylinder.Cylinder");
	constexpr double RainMeshSizeCm = 100.0;
	// A drop not drawn this frame (behind the camera, or nearer than near_m):
	// shrunk to nothing and given no opacity.
	constexpr double RainHiddenScale = 1.0e-4;
	const TCHAR* const RainDropMaterialPath = TEXT("/Game/FlightSim/M_RainDrop.M_RainDrop");
	// The parameter scripts/ue_create_materials.py exposes (RAIN_DROP_PARAMETERS).
	const TCHAR* const RainDropOpacityParameter = TEXT("DropOpacity");

	double RainNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double Default)
	{
		double Value = Default;
		if (Object.IsValid() && Object->TryGetNumberField(Key, Value))
		{
			return Value;
		}
		return Default;
	}
}

double FFlightSimVisualScene::RainDropDiameterMm(double U, double LambdaPerMm, double DMinMm,
                                                 double DMaxMm)
{
	const double Span = 1.0 - FMath::Exp(-LambdaPerMm * (DMaxMm - DMinMm));
	return DMinMm - FMath::Loge(1.0 - U * Span) / LambdaPerMm;
}

double FFlightSimVisualScene::RainWrap(double Value, double Half)
{
	const double Period = 2.0 * Half;
	return Value - Period * FMath::FloorToDouble((Value + Half) / Period);
}

bool FFlightSimVisualScene::ApplyRainParticles(UWorld* World,
                                               const FFlightSimVisualSceneOptions& Options,
                                               FString& Error)
{
	RainDrops = nullptr;
	RainOriginsCm.Reset();
	RainDiametersMm.Reset();
	RainFallCmPerS.Reset();
	RainTransforms.Reset();
	RainCoverage.Reset();
	const TSharedPtr<FJsonObject>* Found = nullptr;
	if (!Options.Card.IsValid() ||
	    !Options.Card->TryGetObjectField(TEXT("rain_particles"), Found) || Found == nullptr ||
	    !Found->IsValid())
	{
		return true;   // no rain_particles on the card: nothing is drawn or recorded
	}
	const TSharedPtr<FJsonObject> Block = *Found;
	TSharedPtr<FJsonObject> Record = MakeShared<FJsonObject>();
	Record->SetBoolField(TEXT("asked"), true);
	Record->SetStringField(TEXT("source"), TEXT("card rain_particles (core/scene/rain_particles.py)"));
	LookApplied->SetObjectField(TEXT("rain_particles"), Record);

	const int32 Count = static_cast<int32>(RainNumber(Block, TEXT("count"), 0.0));
	const double LambdaPerMm = RainNumber(Block, TEXT("lambda_per_mm"), 0.0);
	const double DMinMm = RainNumber(Block, TEXT("d_min_mm"), 0.0);
	const double DMaxMm = RainNumber(Block, TEXT("d_max_mm"), 0.0);
	const double Opacity = FMath::Clamp(RainNumber(Block, TEXT("opacity"), 0.0), 0.0, 1.0);
	const int32 Seed = static_cast<int32>(RainNumber(Block, TEXT("seed"), 0.0));
	RainBoxCm = RainNumber(Block, TEXT("box_m"), 0.0) * RainCmPerMetre;
	RainNearCm = RainNumber(Block, TEXT("near_m"), 0.0) * RainCmPerMetre;
	RainExposureS = RainNumber(Block, TEXT("streak_exposure_s"), 0.0);
	RainMinWidthPx = RainNumber(Block, TEXT("min_width_px"), 1.0);
	const TArray<TSharedPtr<FJsonValue>>* Law = nullptr;
	if (Count <= 0 || !(LambdaPerMm > 0.0) || !(DMaxMm > DMinMm) || !(DMinMm > 0.0) ||
	    !(RainBoxCm > 0.0) || !(RainExposureS > 0.0) ||
	    !Block->TryGetArrayField(TEXT("fall_speed_law"), Law) || Law == nullptr || Law->Num() != 3)
	{
		Record->SetStringField(TEXT("drawn"),
			TEXT("nothing: the block lacks count, lambda_per_mm, d_min_mm < d_max_mm, box_m, ")
			TEXT("streak_exposure_s or the three fall_speed_law coefficients"));
		return true;
	}
	// Atlas, Srivastava & Sekhon 1973: v(D) = a - b exp(-c D), m/s, D in mm.
	const double LawA = (*Law)[0]->AsNumber();
	const double LawB = (*Law)[1]->AsNumber();
	const double LawC = (*Law)[2]->AsNumber();

	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, RainDropMeshPath);
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, RainDropMaterialPath);
	Record->SetStringField(TEXT("mesh"), Mesh != nullptr ? RainDropMeshPath : TEXT("absent"));
	Record->SetStringField(TEXT("material"), Material != nullptr ? RainDropMaterialPath
	                                                             : TEXT("absent: run scripts/ue_create_materials.py"));
	if (Mesh == nullptr || Material == nullptr)
	{
		Record->SetStringField(TEXT("drawn"), TEXT("nothing: the mesh or the material is absent"));
		return true;
	}

	// The drops: seeded origins in the box, diameters and fall speeds.
	FRandomStream Random(Seed);
	const double Half = 0.5 * RainBoxCm;
	double DiameterSum = 0.0;
	double FallSum = 0.0;
	RainOriginsCm.Reserve(Count);
	RainDiametersMm.Reserve(Count);
	RainFallCmPerS.Reserve(Count);
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const double X = Random.FRandRange(-Half, Half);
		const double Y = Random.FRandRange(-Half, Half);
		const double Z = Random.FRandRange(-Half, Half);
		RainOriginsCm.Add(FVector(X, Y, Z));
		const double DiameterMm = RainDropDiameterMm(Random.FRand(), LambdaPerMm, DMinMm, DMaxMm);
		const double FallMps = FMath::Max(LawA - LawB * FMath::Exp(-LawC * DiameterMm), 0.0);
		RainDiametersMm.Add(DiameterMm);
		RainFallCmPerS.Add(FallMps * RainCmPerMetre);
		DiameterSum += DiameterMm;
		FallSum += FallMps;
	}
	// Every drop hidden until AdvanceRain places it around the first frame's camera.
	RainTransforms.Init(FTransform(FQuat::Identity, FVector::ZeroVector, FVector(RainHiddenScale)), Count);
	RainCoverage.Init(0.0f, Count);

	AActor* Rain = World->SpawnActor<AActor>();
	RainDrops = NewObject<UInstancedStaticMeshComponent>(Rain, TEXT("RainDrops"));
	Rain->SetRootComponent(RainDrops);
	RainDrops->SetMobility(EComponentMobility::Movable);
	RainDrops->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	RainDrops->SetCastShadow(false);
	RainDrops->SetStaticMesh(Mesh);
	UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(Material, RainDrops);
	Instance->SetScalarParameterValue(FName(RainDropOpacityParameter), static_cast<float>(Opacity));
	RainDrops->SetMaterial(0, Instance);
	RainDrops->SetNumCustomDataFloats(1);
	RainDrops->RegisterComponent();
	Rain->SetActorLocation(FVector::ZeroVector);
	RainDrops->AddInstances(RainTransforms, false, true);
	BeautyOnlyActors.Add(Rain);

	Record->SetStringField(TEXT("drawn"), TEXT("3-D drops on the beauty capture"));
	Record->SetStringField(TEXT("applied_to"),
		TEXT("beauty (a beauty-only actor: the label captures hide it)"));
	Record->SetNumberField(TEXT("count"), Count);
	Record->SetNumberField(TEXT("box_m"), RainBoxCm / RainCmPerMetre);
	Record->SetNumberField(TEXT("near_m"), RainNearCm / RainCmPerMetre);
	Record->SetNumberField(TEXT("streak_exposure_s"), RainExposureS);
	Record->SetNumberField(TEXT("min_width_px"), RainMinWidthPx);
	Record->SetNumberField(TEXT("opacity"), Opacity);
	Record->SetNumberField(TEXT("mean_diameter_mm"), DiameterSum / Count);
	Record->SetNumberField(TEXT("mean_fall_mps"), FallSum / Count);
	Record->SetStringField(TEXT("not_claimed"),
		TEXT("a thinned sample of the visible drops, not the physical count; no wind advection; ")
		TEXT("the streak exposure is a stated look choice, not the card's shutter; no splashes ")
		TEXT("or accumulation; the drop's optics are a lit translucent material"));
	return true;
}

void FFlightSimVisualScene::AdvanceRain(double TimeSeconds, const FVector& CameraLocationCm,
                                        const FRotator& CameraRotation,
                                        const FVector& CameraVelocityCmPerS,
                                        double HorizontalFovDeg, int32 WidthPx)
{
	const int32 Count = RainOriginsCm.Num();
	if (RainDrops == nullptr || Count == 0)
	{
		return;
	}
	const FVector Forward = CameraRotation.Vector();
	const double Half = 0.5 * RainBoxCm;
	// The box, centred half a side ahead of the camera along its view.
	const FVector Centre = CameraLocationCm + Forward * Half;
	// The pixel footprint per centimetre of range.
	const double PixelPerRange =
		2.0 * FMath::Tan(FMath::DegreesToRadians(0.5 * HorizontalFovDeg)) / FMath::Max(WidthPx, 1);
	int32 Drawn = 0;
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const double FallCmPerS = RainFallCmPerS[Index];
		const FVector Fallen = RainOriginsCm[Index] - FVector(0.0, 0.0, FallCmPerS * TimeSeconds);
		const FVector Position = Centre + FVector(RainWrap(Fallen.X - Centre.X, Half),
		                                          RainWrap(Fallen.Y - Centre.Y, Half),
		                                          RainWrap(Fallen.Z - Centre.Z, Half));
		const FVector FromCamera = Position - CameraLocationCm;
		const double Range = FromCamera.Size();
		if (Range < RainNearCm || FVector::DotProduct(FromCamera, Forward) <= 0.0)
		{
			RainTransforms[Index] = FTransform(FQuat::Identity, Position, FVector(RainHiddenScale));
			RainCoverage[Index] = 0.0f;
			continue;
		}
		// The streak: the drop's velocity relative to the camera over the exposure.
		const FVector Streak = (FVector(0.0, 0.0, -FallCmPerS) - CameraVelocityCmPerS) * RainExposureS;
		const double DiameterCm = RainDiametersMm[Index] * RainCmPerMm;
		const double WidthCm = FMath::Max(DiameterCm, RainMinWidthPx * PixelPerRange * Range);
		const double LengthCm = FMath::Max(Streak.Size(), WidthCm);
		const FVector Axis = Streak.SizeSquared() > 0.0 ? Streak.GetUnsafeNormal() : FVector::UpVector;
		RainTransforms[Index] = FTransform(FRotationMatrix::MakeFromZ(Axis).ToQuat(), Position,
			FVector(WidthCm / RainMeshSizeCm, WidthCm / RainMeshSizeCm, LengthCm / RainMeshSizeCm));
		RainCoverage[Index] = static_cast<float>(DiameterCm / WidthCm);
		++Drawn;
	}
	// Teleported: a wrapped drop is not motion, so the velocity buffer and
	// the motion blur never streak it across the box.
	RainDrops->BatchUpdateInstancesTransforms(0, RainTransforms, true, false, true);
	for (int32 Index = 0; Index < Count; ++Index)
	{
		RainDrops->SetCustomDataValue(Index, 0, RainCoverage[Index], false);
	}
	RainDrops->MarkRenderStateDirty();
	const TSharedPtr<FJsonObject>* Record = nullptr;
	if (LookApplied.IsValid() && LookApplied->TryGetObjectField(TEXT("rain_particles"), Record) &&
	    Record != nullptr && Record->IsValid())
	{
		(*Record)->SetNumberField(TEXT("last_t_s"), TimeSeconds);
		(*Record)->SetNumberField(TEXT("last_drawn"), Drawn);
		(*Record)->SetNumberField(TEXT("last_camera_speed_mps"),
		                          CameraVelocityCmPerS.Size() / RainCmPerMetre);
	}
}
