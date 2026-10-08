// The weather look: what the run card's weather_look block draws
// (core/scene/weather_look.py writes it; VISUAL ONLY -- nothing here
// reaches the flight model).
//
// * the flat scene's ground: M_Ground_<Surface> for the spec's surface word
//   (scripts/ue_create_materials.py: procedural, or the Poly Haven textures
//   scripts/fetch_ground_textures.py fetched), its Wetness scalar from the
//   block's wetness (puddles and ripples). A georeferenced scene keeps its
//   imagery: the word is recorded as drawing nothing there.
// * a thunderstorm: three rain shafts (M_RainShaft on open tapered cones
//   from the cloud base to the ground) ahead of the start along the card's
//   heading, and a lightning bolt (M_Lightning on a jagged double ribbon)
//   with a point light, flashing on LightningFlash's schedule. Every one
//   is a beauty-only actor (BeautyOnlyActors): the label captures never
//   see them, so the label passes are unchanged by the storm's look.
// * rain on the lens: M_LensDrops as a post-process blendable on the
//   BEAUTY capture only, DropAmount from the block's rain rate.
// * ice: M_IceOverlay as the overlay material of every static mesh part of
//   the airframe, IceAmount = eta(t) / 0.30 from the card's icing_schedule
//   ramp on the FDM's time (core/scene/weather_look.py ICE_FULL_ETA).
//
// A missing material is RECORDED as absent in look_applied.weather_look,
// never refused: the weather look is visual only and the run it decorates
// is still the run. The placement of the shafts assumes the aircraft
// starts over the engine origin (the scene's own convention: the
// georeference's origin is the card's start), engine X east / Y north.
//
// UNCOMPILED when written (no engine on the authoring machine): the first
// Windows build verifies it; tests/test_weather_look.py pins its text.

#include "FlightSimVisualScene.h"
#include "Components/PointLightComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"
#include "ProceduralMeshComponent.h"

namespace
{
	constexpr double WeatherCmPerMetre = 100.0;

	struct FGroundMaterialRow
	{
		const TCHAR* Surface;
		const TCHAR* Path;
	};
	// core/environment/surface.py SURFACE_CLASSES -> the script's GROUND_SURFACES.
	const FGroundMaterialRow GroundMaterials[] = {
		{TEXT("desert"), TEXT("/Game/FlightSim/M_Ground_Desert.M_Ground_Desert")},
		{TEXT("forest"), TEXT("/Game/FlightSim/M_Ground_Forest.M_Ground_Forest")},
		{TEXT("grassland"), TEXT("/Game/FlightSim/M_Ground_Grassland.M_Ground_Grassland")},
		{TEXT("snow"), TEXT("/Game/FlightSim/M_Ground_Snow.M_Ground_Snow")},
		{TEXT("bare"), TEXT("/Game/FlightSim/M_Ground_Bare.M_Ground_Bare")},
		{TEXT("city"), TEXT("/Game/FlightSim/M_Ground_City.M_Ground_City")},
		{TEXT("ocean"), TEXT("/Game/FlightSim/M_Ground_Ocean.M_Ground_Ocean")},
	};
	const TCHAR* const LensDropsPath = TEXT("/Game/FlightSim/M_LensDrops.M_LensDrops");
	const TCHAR* const RainShaftPath = TEXT("/Game/FlightSim/M_RainShaft.M_RainShaft");
	const TCHAR* const LightningPath = TEXT("/Game/FlightSim/M_Lightning.M_Lightning");
	const TCHAR* const IceOverlayPath = TEXT("/Game/FlightSim/M_IceOverlay.M_IceOverlay");
	// The parameter names scripts/ue_create_materials.py exposes
	// (WET_GROUND_PARAMETER, WEATHER_PARAMETERS).
	const TCHAR* const WeatherWetParameter = TEXT("Wetness");
	const TCHAR* const WeatherDropParameter = TEXT("DropAmount");
	const TCHAR* const WeatherShaftParameter = TEXT("ShaftOpacity");
	const TCHAR* const WeatherFlashParameter = TEXT("FlashIntensity");
	const TCHAR* const WeatherIceParameter = TEXT("IceAmount");

	// The lightning schedule: one flash every FlashPeriodSeconds, phase from
	// the seed, FlashSeconds long with a strike, a dip and a return stroke.
	// Stated choices, not a model of charge.
	constexpr double FlashPeriodSeconds = 6.5;
	constexpr double FlashSeconds = 0.18;
	constexpr double LightningCandela = 3.0e8;
	constexpr double LightningRadiusM = 30000.0;
	// The shafts: ahead of the start, alternating sides, 2 km apart.
	constexpr int32 ShaftCount = 3;
	constexpr int32 ShaftSegments = 32;
	constexpr double ShaftBottomRadiusM = 900.0;
	constexpr double ShaftTopRadiusM = 1400.0;
	constexpr double DefaultCloudBaseM = 1200.0;
	// Shaft opacity and lens drops at the thunderstorm's 40 mm/h visual rate.
	constexpr double WeatherReferenceRateMmh = 40.0;
	constexpr double ShaftOpacityAtReference = 0.55;
	// eta at which the ice is fully drawn (icing's "severe" word).
	constexpr double IceFullEta = 0.30;

	double NumberOr(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double Default)
	{
		double Value = Default;
		if (Object.IsValid() && Object->TryGetNumberField(Key, Value))
		{
			return Value;
		}
		return Default;
	}

	FString StringOr(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key)
	{
		FString Value;
		if (Object.IsValid())
		{
			Object->TryGetStringField(Key, Value);
		}
		return Value;
	}

	UProceduralMeshComponent* NewWeatherMesh(AActor* Owner, const TCHAR* Name)
	{
		UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Owner, Name);
		Owner->SetRootComponent(Mesh);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		return Mesh;
	}

	// An open cone from the cloud base (V 0) to the ground (V 1): the
	// material fades it toward the cloud and softens it at the ground.
	void BuildShaftSection(UProceduralMeshComponent* Mesh, double HeightM)
	{
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		for (int32 Index = 0; Index <= ShaftSegments; ++Index)
		{
			const double Angle = 2.0 * PI * Index / ShaftSegments;
			const FVector Out(FMath::Cos(Angle), FMath::Sin(Angle), 0.0);
			const double U = static_cast<double>(Index) / ShaftSegments;
			Vertices.Add(Out * ShaftTopRadiusM * WeatherCmPerMetre +
			             FVector(0.0, 0.0, HeightM * WeatherCmPerMetre));
			Vertices.Add(Out * ShaftBottomRadiusM * WeatherCmPerMetre);
			Normals.Add(Out);
			Normals.Add(Out);
			UV0.Add(FVector2D(U, 0.0));
			UV0.Add(FVector2D(U, 1.0));
		}
		for (int32 Index = 0; Index < ShaftSegments; ++Index)
		{
			const int32 Top = Index * 2;
			Triangles.Append({Top, Top + 2, Top + 1, Top + 1, Top + 2, Top + 3});
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}

	// A jagged bolt from the cloud base to the ground: a random walk of 24
	// segments (60 m lateral jitter each), drawn as two crossed 6 m ribbons
	// so it reads from any camera.
	void BuildBoltSection(UProceduralMeshComponent* Mesh, double HeightM, FRandomStream& Random)
	{
		constexpr int32 Segments = 24;
		constexpr double JitterM = 60.0;
		constexpr double HalfWidthM = 3.0;
		TArray<FVector> Points;
		FVector Point(0.0, 0.0, HeightM);
		for (int32 Index = 0; Index <= Segments; ++Index)
		{
			Points.Add(Point * WeatherCmPerMetre);
			Point += FVector(Random.FRandRange(-JitterM, JitterM), Random.FRandRange(-JitterM, JitterM),
			                 -HeightM / Segments);
		}
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		for (const FVector& Side : {FVector(HalfWidthM, 0.0, 0.0), FVector(0.0, HalfWidthM, 0.0)})
		{
			const int32 Base = Vertices.Num();
			const FVector Normal = FVector::CrossProduct(Side, FVector::UpVector).GetSafeNormal();
			for (const FVector& P : Points)
			{
				Vertices.Add(P - Side * WeatherCmPerMetre);
				Vertices.Add(P + Side * WeatherCmPerMetre);
				Normals.Add(Normal);
				Normals.Add(Normal);
			}
			for (int32 Index = 0; Index < Segments; ++Index)
			{
				const int32 A = Base + Index * 2;
				Triangles.Append({A, A + 1, A + 2, A + 1, A + 3, A + 2});
			}
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, {}, {}, {}, false);
	}
}

double FFlightSimVisualScene::LightningFlash(double TimeSeconds, int32 Seed)
{
	const double Offset = static_cast<double>(static_cast<uint32>(Seed) % 1000u) / 1000.0 *
	                      FlashPeriodSeconds;
	const double Cycle = FMath::Fmod(FMath::Max(TimeSeconds, 0.0) + Offset, FlashPeriodSeconds);
	if (Cycle >= FlashSeconds)
	{
		return 0.0;
	}
	// The strike, a dip, the return stroke.
	if (Cycle < 0.4 * FlashSeconds)
	{
		return 1.0;
	}
	return Cycle < 0.6 * FlashSeconds ? 0.2 : 0.8;
}

bool FFlightSimVisualScene::ApplyWeatherLook(UWorld* World,
                                             const FFlightSimVisualSceneOptions& Options,
                                             FString& Error)
{
	WeatherLook.Reset();
	LensDropsInstance = nullptr;
	IceInstance = nullptr;
	LightningInstance = nullptr;
	LightningLight = nullptr;
	IceEtaMax = 0.0;
	IceOnsetSeconds = 0.0;
	IceRampSeconds = 0.0;
	WeatherSeed = 0;
	const TSharedPtr<FJsonObject>* Block = nullptr;
	if (!Options.Card.IsValid() ||
	    !Options.Card->TryGetObjectField(TEXT("weather_look"), Block) || Block == nullptr ||
	    !Block->IsValid())
	{
		return true;   // no weather_look on the card: nothing is drawn or recorded
	}
	WeatherLook = *Block;
	const FString Surface = StringOr(WeatherLook, TEXT("surface"));
	const FString Storm = StringOr(WeatherLook, TEXT("storm"));
	const double RainRate = NumberOr(WeatherLook, TEXT("rain_rate_mmh"), 0.0);
	const double Wetness = FMath::Clamp(NumberOr(WeatherLook, TEXT("wetness"), 0.0), 0.0, 1.0);
	IceEtaMax = FMath::Max(NumberOr(WeatherLook, TEXT("ice_eta_max"), 0.0), 0.0);
	WeatherSeed = static_cast<int32>(NumberOr(WeatherLook, TEXT("seed"), 0.0));
	const TSharedPtr<FJsonObject>* Icing = nullptr;
	if (Options.Card->TryGetObjectField(TEXT("icing_schedule"), Icing) && Icing != nullptr)
	{
		IceOnsetSeconds = NumberOr(*Icing, TEXT("onset_s"), 0.0);
		IceRampSeconds = NumberOr(*Icing, TEXT("ramp_s"), 0.0);
	}

	TSharedPtr<FJsonObject> Record = MakeShared<FJsonObject>();
	Record->SetBoolField(TEXT("asked"), true);
	Record->SetStringField(TEXT("source"), TEXT("card weather_look (core/scene/weather_look.py)"));

	// -- the ground ---------------------------------------------------------
	TSharedPtr<FJsonObject> GroundRow = MakeShared<FJsonObject>();
	GroundRow->SetStringField(TEXT("surface"), Surface.IsEmpty() ? TEXT("unspecified") : *Surface);
	GroundRow->SetNumberField(TEXT("wetness"), Wetness);
	if (Surface.IsEmpty())
	{
		GroundRow->SetStringField(TEXT("drawn"), TEXT("nothing: no surface word"));
	}
	else if (FlatGround == nullptr)
	{
		GroundRow->SetStringField(TEXT("drawn"),
			TEXT("nothing: the georeferenced terrain keeps its imagery"));
	}
	else
	{
		const TCHAR* GroundPath = nullptr;
		for (const FGroundMaterialRow& Row : GroundMaterials)
		{
			if (Surface == Row.Surface)
			{
				GroundPath = Row.Path;
			}
		}
		UMaterialInterface* GroundMaterial =
			GroundPath != nullptr ? LoadObject<UMaterialInterface>(nullptr, GroundPath) : nullptr;
		if (GroundMaterial == nullptr)
		{
			GroundRow->SetStringField(TEXT("drawn"), TEXT("nothing: the material is absent"));
			GroundRow->SetStringField(TEXT("material"),
				GroundPath != nullptr ? GroundPath : TEXT("no material for this word"));
		}
		else
		{
			UMaterialInstanceDynamic* GroundInstance =
				UMaterialInstanceDynamic::Create(GroundMaterial, FlatGround);
			GroundInstance->SetScalarParameterValue(FName(WeatherWetParameter),
			                                        static_cast<float>(Wetness));
			FlatGround->SetMaterial(0, GroundInstance);
			GroundRow->SetStringField(TEXT("drawn"), TEXT("the flat ground's material"));
			GroundRow->SetStringField(TEXT("material"), GroundPath);
		}
	}
	Record->SetObjectField(TEXT("ground"), GroundRow);

	// -- the storm: rain shafts and lightning (beauty-only) -------------------
	TSharedPtr<FJsonObject> StormRow = MakeShared<FJsonObject>();
	StormRow->SetStringField(TEXT("storm"), Storm.IsEmpty() ? TEXT("none") : *Storm);
	if (Storm == TEXT("thunderstorm"))
	{
		const double CloudBaseM = Options.CloudLayers.Num() > 0 && Options.CloudLayers[0].BaseMetres > 0.0
			? Options.CloudLayers[0].BaseMetres : DefaultCloudBaseM;
		const double HeadingRad = FMath::DegreesToRadians(NumberOr(Options.Card, TEXT("heading_deg"), 0.0));
		const FVector2D Forward(FMath::Sin(HeadingRad), FMath::Cos(HeadingRad));
		const FVector2D Right(FMath::Cos(HeadingRad), -FMath::Sin(HeadingRad));
		FRandomStream Random(WeatherSeed);
		const double ShaftOpacity = FMath::Clamp(
			ShaftOpacityAtReference * FMath::Max(RainRate, 1.0) / WeatherReferenceRateMmh, 0.15, 0.75);
		UMaterialInterface* ShaftMaterial = LoadObject<UMaterialInterface>(nullptr, RainShaftPath);
		TArray<TSharedPtr<FJsonValue>> Shafts;
		FVector FirstShaft = FVector::ZeroVector;
		for (int32 Index = 0; Index < ShaftCount; ++Index)
		{
			const double AheadM = 3000.0 + 2000.0 * Index + Random.FRandRange(-500.0, 500.0);
			const double SideM = (Index % 2 == 0 ? -1.0 : 1.0) * Random.FRandRange(800.0, 2200.0);
			const FVector2D At = Forward * AheadM + Right * SideM;
			const FVector Location(At.X * WeatherCmPerMetre, At.Y * WeatherCmPerMetre, 0.0);
			if (Index == 0)
			{
				FirstShaft = Location;
			}
			if (ShaftMaterial == nullptr)
			{
				continue;
			}
			AActor* Shaft = World->SpawnActor<AActor>();
			UProceduralMeshComponent* ShaftMesh = NewWeatherMesh(Shaft, TEXT("RainShaft"));
			BuildShaftSection(ShaftMesh, CloudBaseM);
			UMaterialInstanceDynamic* ShaftInstance = UMaterialInstanceDynamic::Create(ShaftMaterial, ShaftMesh);
			ShaftInstance->SetScalarParameterValue(FName(WeatherShaftParameter),
			                                       static_cast<float>(ShaftOpacity));
			ShaftMesh->SetMaterial(0, ShaftInstance);
			ShaftMesh->RegisterComponent();
			Shaft->SetActorLocation(Location);
			BeautyOnlyActors.Add(Shaft);
			TSharedPtr<FJsonObject> ShaftRow = MakeShared<FJsonObject>();
			ShaftRow->SetNumberField(TEXT("ahead_m"), AheadM);
			ShaftRow->SetNumberField(TEXT("right_m"), SideM);
			Shafts.Add(MakeShared<FJsonValueObject>(ShaftRow));
		}
		StormRow->SetArrayField(TEXT("rain_shafts"), Shafts);
		StormRow->SetStringField(TEXT("rain_shaft_material"),
			ShaftMaterial != nullptr ? RainShaftPath : TEXT("absent"));
		StormRow->SetNumberField(TEXT("rain_shaft_opacity"), ShaftOpacity);
		StormRow->SetNumberField(TEXT("cloud_base_m"), CloudBaseM);

		UMaterialInterface* BoltMaterial = LoadObject<UMaterialInterface>(nullptr, LightningPath);
		if (BoltMaterial != nullptr)
		{
			AActor* Bolt = World->SpawnActor<AActor>();
			UProceduralMeshComponent* BoltMesh = NewWeatherMesh(Bolt, TEXT("LightningBolt"));
			BuildBoltSection(BoltMesh, CloudBaseM, Random);
			LightningInstance = UMaterialInstanceDynamic::Create(BoltMaterial, BoltMesh);
			LightningInstance->SetScalarParameterValue(FName(WeatherFlashParameter), 0.0f);
			BoltMesh->SetMaterial(0, LightningInstance);
			BoltMesh->RegisterComponent();
			LightningLight = NewObject<UPointLightComponent>(Bolt, TEXT("LightningLight"));
			LightningLight->SetMobility(EComponentMobility::Movable);
			LightningLight->SetupAttachment(BoltMesh);
			LightningLight->SetRelativeLocation(FVector(0.0, 0.0, 0.5 * CloudBaseM * WeatherCmPerMetre));
			LightningLight->SetIntensityUnits(ELightUnits::Candelas);
			LightningLight->SetIntensity(0.0f);
			LightningLight->SetAttenuationRadius(static_cast<float>(LightningRadiusM * WeatherCmPerMetre));
			LightningLight->SetCastShadows(false);
			LightningLight->RegisterComponent();
			Bolt->SetActorLocation(FirstShaft);
			BeautyOnlyActors.Add(Bolt);
		}
		StormRow->SetStringField(TEXT("lightning_material"),
			BoltMaterial != nullptr ? LightningPath : TEXT("absent"));
		StormRow->SetNumberField(TEXT("lightning_period_s"), FlashPeriodSeconds);
		StormRow->SetNumberField(TEXT("lightning_flash_s"), FlashSeconds);
		StormRow->SetStringField(TEXT("not_claimed"),
			TEXT("the shafts are not a model of the rain field and the flashes are a stated "
			     "schedule, not a model of charge; both are beauty-only"));
	}
	else if (Storm == TEXT("tornado"))
	{
		StormRow->SetStringField(TEXT("drawn"),
			TEXT("the funnel is the scenario world's (FlightSimScenarioWorld.cpp); no shafts"));
	}
	Record->SetObjectField(TEXT("storm"), StormRow);

	// -- rain and ice: applied later, recorded as asked here -----------------
	Record->SetNumberField(TEXT("rain_rate_mmh"), RainRate);
	Record->SetStringField(TEXT("lens_drops"), RainRate > 0.0 ? TEXT("asked") : TEXT("no rain rate"));
	Record->SetNumberField(TEXT("ice_eta_max"), IceEtaMax);
	Record->SetStringField(TEXT("ice_overlay"), IceEtaMax > 0.0 ? TEXT("asked") : TEXT("no ice"));
	LookApplied->SetObjectField(TEXT("weather_look"), Record);
	return true;
}

void FFlightSimVisualScene::ApplyLensDropsToBeauty(USceneCaptureComponent2D* Beauty)
{
	const double RainRate = NumberOr(WeatherLook, TEXT("rain_rate_mmh"), 0.0);
	if (Beauty == nullptr || !WeatherLook.IsValid() || RainRate <= 0.0)
	{
		return;
	}
	const TSharedPtr<FJsonObject>* Record = nullptr;
	LookApplied->TryGetObjectField(TEXT("weather_look"), Record);
	UMaterialInterface* DropsMaterial = LoadObject<UMaterialInterface>(nullptr, LensDropsPath);
	if (DropsMaterial == nullptr)
	{
		if (Record != nullptr && Record->IsValid())
		{
			(*Record)->SetStringField(TEXT("lens_drops"), TEXT("absent: M_LensDrops did not load"));
		}
		return;
	}
	const double Amount = FMath::Clamp(RainRate / WeatherReferenceRateMmh, 0.1, 1.0);
	LensDropsInstance = UMaterialInstanceDynamic::Create(DropsMaterial, Beauty);
	LensDropsInstance->SetScalarParameterValue(FName(WeatherDropParameter), static_cast<float>(Amount));
	// The beauty capture only: the label captures receive no look blendable.
	Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, LensDropsInstance));
	if (Record != nullptr && Record->IsValid())
	{
		(*Record)->SetStringField(TEXT("lens_drops"), TEXT("beauty capture"));
		(*Record)->SetNumberField(TEXT("lens_drop_amount"), Amount);
	}
}

void FFlightSimVisualScene::ApplyIceOverlay(AActor* Airframe)
{
	if (Airframe == nullptr || IceEtaMax <= 0.0)
	{
		return;
	}
	const TSharedPtr<FJsonObject>* Record = nullptr;
	LookApplied->TryGetObjectField(TEXT("weather_look"), Record);
	UMaterialInterface* IceMaterial = LoadObject<UMaterialInterface>(nullptr, IceOverlayPath);
	if (IceMaterial == nullptr)
	{
		if (Record != nullptr && Record->IsValid())
		{
			(*Record)->SetStringField(TEXT("ice_overlay"), TEXT("absent: M_IceOverlay did not load"));
		}
		return;
	}
	IceInstance = UMaterialInstanceDynamic::Create(IceMaterial, Airframe);
	IceInstance->SetScalarParameterValue(FName(WeatherIceParameter), 0.0f);
	TInlineComponentArray<UStaticMeshComponent*> Parts;
	Airframe->GetComponents(Parts);
	for (UStaticMeshComponent* Part : Parts)
	{
		Part->SetOverlayMaterial(IceInstance);
	}
	if (Record != nullptr && Record->IsValid())
	{
		(*Record)->SetStringField(TEXT("ice_overlay"), TEXT("overlay material on the airframe"));
		(*Record)->SetNumberField(TEXT("ice_parts"), Parts.Num());
		(*Record)->SetNumberField(TEXT("ice_full_eta"), IceFullEta);
	}
}

void FFlightSimVisualScene::AdvanceWeather(double TimeSeconds)
{
	if (LightningInstance != nullptr)
	{
		const double Flash = LightningFlash(TimeSeconds, WeatherSeed);
		LightningInstance->SetScalarParameterValue(FName(WeatherFlashParameter), static_cast<float>(Flash));
		if (LightningLight != nullptr)
		{
			LightningLight->SetIntensity(static_cast<float>(Flash * LightningCandela));
		}
	}
	if (IceInstance != nullptr)
	{
		// icing's ramp on the FDM's time: eta_max clamp((t - onset) / ramp, 0, 1).
		const double Fraction = IceRampSeconds <= 0.0
			? (TimeSeconds >= IceOnsetSeconds ? 1.0 : 0.0)
			: FMath::Clamp((TimeSeconds - IceOnsetSeconds) / IceRampSeconds, 0.0, 1.0);
		IceInstance->SetScalarParameterValue(FName(WeatherIceParameter),
			static_cast<float>(FMath::Clamp(IceEtaMax * Fraction / IceFullEta, 0.0, 1.0)));
	}
}
