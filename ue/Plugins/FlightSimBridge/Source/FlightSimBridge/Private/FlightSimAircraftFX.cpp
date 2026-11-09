// The airframe's beauty look (FlightSimAircraftFX.h says what, why and what
// it may not touch). Visual overhaul V7, aircraft lane. BEAUTY ONLY.
//
// UNCOMPILED when written: the authoring Mac's Xcode is above UE 5.7's cap.
// Every engine symbol below was grepped in the UE 5.7.4 headers on that
// machine (scripts/check_bridge_api.sh, aircraft-lane block); no Cesium API
// is used here. Every look constant is read from look_manifest.json, where
// scripts/aircraft_look.py stamps each one "UNCALIBRATED: set by probe render
// on the render machine"; the fallbacks below are the same numbers, used only
// when a manifest predates a constant.

#include "FlightSimAircraftFX.h"

#include "Components/PointLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/Scene.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RotationMatrix.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimAircraftFX, Log, All);

namespace
{
	// Names are file-unique (NEXT.md gotcha 3: unity builds merge anonymous
	// namespaces).
	constexpr double AircraftFxCmPerMetre = 100.0;
	constexpr double AircraftFxMpsPerKnot = 0.514444;
	constexpr double AircraftFxKelvinPerRankine = 5.0 / 9.0;
	constexpr int32 AircraftFxConeRings = 8;
	constexpr int32 AircraftFxConeSides = 16;
	const TCHAR* const AircraftFxLookManifestName = TEXT("look_manifest.json");
	const TCHAR* const AircraftFxLookManifestMagic = TEXT("flightsim-aircraft-look-manifest");
	// scripts/aircraft_look.py MASTER_ROOT + FX_MASTERS.
	const TCHAR* const AircraftFxNavMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_NavLightEmissive.M_NavLightEmissive");
	const TCHAR* const AircraftFxContrailMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftContrail.M_AircraftContrail");
	const TCHAR* const AircraftFxAfterburnerMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftAfterburner.M_AircraftAfterburner");
	const TCHAR* const AircraftFxHeatHazeMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftHeatHaze.M_AircraftHeatHaze");
	// scripts/aircraft_look.py FX_PARAMETERS (pinned by tests/test_aircraft_look.py).
	const TCHAR* const AircraftFxParamLightColour = TEXT("LightColour");
	const TCHAR* const AircraftFxParamIntensity = TEXT("Intensity");
	const TCHAR* const AircraftFxParamStrobe = TEXT("Strobe");
	const TCHAR* const AircraftFxParamOpacity = TEXT("Opacity");
	const TCHAR* const AircraftFxParamFormation = TEXT("Formation");
	const TCHAR* const AircraftFxParamTime = TEXT("TimeS");
	const TCHAR* const AircraftFxParamStrength = TEXT("Strength");
	// The look instances: <asset_path_root>/Look/MI_<slot> (aircraft_look.py
	// LOOK_INSTANCE_FOLDER / LOOK_INSTANCE_PREFIX).
	const TCHAR* const AircraftFxLookFolder = TEXT("Look");
	const TCHAR* const AircraftFxLookPrefix = TEXT("MI_");

	bool AircraftFxSwitch(const FString& Params, const TCHAR* Key, bool Default)
	{
		FString Word;
		if (!FParse::Value(*Params, Key, Word))
		{
			return Default;
		}
		return !(Word == TEXT("off") || Word == TEXT("0") || Word == TEXT("false"));
	}

	FVector AircraftFxVector(const TSharedPtr<FJsonObject>& Row, const TCHAR* Field)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Row.IsValid() && Row->TryGetArrayField(Field, Values) && Values != nullptr && Values->Num() == 3)
		{
			return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
		}
		return FVector::ZeroVector;
	}

	TSharedPtr<FJsonValue> AircraftFxVectorValue(const FVector& V)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		Values.Add(MakeShared<FJsonValueNumber>(V.X));
		Values.Add(MakeShared<FJsonValueNumber>(V.Y));
		Values.Add(MakeShared<FJsonValueNumber>(V.Z));
		return MakeShared<FJsonValueArray>(Values);
	}

	UProceduralMeshComponent* AircraftFxMesh(AActor* Owner, const TCHAR* Name)
	{
		UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Owner, Name);
		Owner->SetRootComponent(Mesh);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		return Mesh;
	}

	// Three crossed quads (XY, XZ, YZ), RadiusCm half-size, UV 0..1 across each:
	// a lamp's glow seen from any side (nav_bulb.hlsl draws the falloff).
	void AircraftFxBulbSection(UProceduralMeshComponent* Mesh, double RadiusCm)
	{
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		const FVector Axes[3][2] = {
			{FVector(1, 0, 0), FVector(0, 1, 0)},
			{FVector(1, 0, 0), FVector(0, 0, 1)},
			{FVector(0, 1, 0), FVector(0, 0, 1)},
		};
		for (const auto& Pair : Axes)
		{
			const int32 Base = Vertices.Num();
			const FVector U = Pair[0] * RadiusCm;
			const FVector V = Pair[1] * RadiusCm;
			Vertices.Add(-U - V);
			Vertices.Add(U - V);
			Vertices.Add(U + V);
			Vertices.Add(-U + V);
			UV0.Add(FVector2D(0, 0));
			UV0.Add(FVector2D(1, 0));
			UV0.Add(FVector2D(1, 1));
			UV0.Add(FVector2D(0, 1));
			const FVector N = FVector::CrossProduct(Pair[0], Pair[1]);
			for (int32 i = 0; i < 4; ++i)
			{
				Normals.Add(N);
			}
			Triangles.Append({Base, Base + 1, Base + 2, Base, Base + 2, Base + 3});
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}

	// An open cone along actor -X from the nozzle (radius R0, UV.x 0) to
	// LengthCm aft (radius R1, UV.x 1); UV.y runs around it.
	void AircraftFxConeSection(UProceduralMeshComponent* Mesh, double R0, double R1, double LengthCm)
	{
		TArray<FVector> Vertices;
		TArray<int32> Triangles;
		TArray<FVector> Normals;
		TArray<FVector2D> UV0;
		for (int32 Ring = 0; Ring <= AircraftFxConeRings; ++Ring)
		{
			const double T = static_cast<double>(Ring) / AircraftFxConeRings;
			const double Radius = FMath::Lerp(R0, R1, T);
			for (int32 Side = 0; Side <= AircraftFxConeSides; ++Side)
			{
				const double A = 2.0 * UE_DOUBLE_PI * Side / AircraftFxConeSides;
				const FVector Radial(0.0, FMath::Cos(A), FMath::Sin(A));
				Vertices.Add(FVector(-T * LengthCm, 0.0, 0.0) + Radial * Radius);
				Normals.Add(Radial);
				UV0.Add(FVector2D(T, static_cast<double>(Side) / AircraftFxConeSides));
			}
		}
		const int32 Stride = AircraftFxConeSides + 1;
		for (int32 Ring = 0; Ring < AircraftFxConeRings; ++Ring)
		{
			for (int32 Side = 0; Side < AircraftFxConeSides; ++Side)
			{
				const int32 A = Ring * Stride + Side;
				const int32 B = A + Stride;
				Triangles.Append({A, B, A + 1, A + 1, B, B + 1});
			}
		}
		Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	}
}

void FFlightSimAircraftFXOptions::ParseParams(const FString& Params)
{
	const bool bAll = AircraftFxSwitch(Params, TEXT("aircraft-look="), true);
	bMaterials = bAll && AircraftFxSwitch(Params, TEXT("aircraft-materials="), true);
	bLights = bAll && AircraftFxSwitch(Params, TEXT("aircraft-lights="), true);
	bContrails = bAll && AircraftFxSwitch(Params, TEXT("contrails="), true);
	bAfterburner = bAll && AircraftFxSwitch(Params, TEXT("afterburner="), true);
	// Pixel-moving: off unless asked for by name.
	bHeatHaze = bAll && AircraftFxSwitch(Params, TEXT("heat-haze="), false);
}

double FFlightSimAircraftFX::Constant(const TCHAR* Group, const TCHAR* Name, double Fallback) const
{
	const TSharedPtr<FJsonObject>* GroupObject = nullptr;
	const TSharedPtr<FJsonObject>* Entry = nullptr;
	double Value = Fallback;
	if (Constants.IsValid() && Constants->TryGetObjectField(Group, GroupObject) && GroupObject != nullptr &&
	    (*GroupObject)->TryGetObjectField(Name, Entry) && Entry != nullptr)
	{
		(*Entry)->TryGetNumberField(TEXT("value"), Value);
	}
	return Value;
}

AActor* FFlightSimAircraftFX::SpawnAttached(UWorld* World, const FVector& ActorCm, const TCHAR* Name)
{
	AActor* Actor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh = AircraftFxMesh(Actor, Name);
	Mesh->RegisterComponent();
	// Its own actor, attached: the stencil loop labels every primitive OF the
	// aircraft actor, and this one must carry no label (BeautyOnlyActors).
	Actor->AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform);
	Actor->SetActorRelativeLocation(ActorCm);
	BeautyOnlyActors.Add(Actor);
	return Actor;
}

bool FFlightSimAircraftFX::Build(UWorld* World, const FFlightSimAircraftFXOptions& Options, FString& Error)
{
	Aircraft = Options.Aircraft;
	Record = MakeShared<FJsonObject>();
	Record->SetStringField(TEXT("drawn_in"), TEXT("beauty capture only (-quality=beauty); every element is a ")
		TEXT("beauty-only actor or a shading-only material swap, so mask, class and depth are those of the ")
		TEXT("same frame's geometry"));
	if (World == nullptr || Aircraft == nullptr)
	{
		Record->SetStringField(TEXT("look_manifest"), TEXT("absent: no aircraft actor"));
		return true;
	}

	// -- the look manifest (scripts/aircraft_look.py) -------------------------
	FString AssetRoot;
	{
		FString MeshText;
		TSharedPtr<FJsonObject> MeshManifest;
		if (FFileHelper::LoadFileToString(MeshText, *Options.MeshManifestPath))
		{
			TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(MeshText);
			if (FJsonSerializer::Deserialize(Reader, MeshManifest) && MeshManifest.IsValid())
			{
				MeshManifest->TryGetStringField(TEXT("asset_path_root"), AssetRoot);
			}
		}
	}
	const FString LookPath = FPaths::Combine(FPaths::GetPath(Options.MeshManifestPath), AircraftFxLookManifestName);
	TSharedPtr<FJsonObject> Look;
	FString LookText;
	if (FFileHelper::LoadFileToString(LookText, *LookPath))
	{
		TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(LookText);
		FString Magic;
		if (!FJsonSerializer::Deserialize(Reader, Look) || !Look.IsValid() ||
		    !Look->TryGetStringField(TEXT("magic"), Magic) || Magic != AircraftFxLookManifestMagic)
		{
			Error = FString::Printf(
				TEXT("aircraft_look.manifest: %s exists but is not a look manifest (magic %s); re-run ")
				TEXT("python scripts/aircraft_look.py <NAME> or the import step"),
				*LookPath, AircraftFxLookManifestMagic);
			return false;
		}
		Record->SetStringField(TEXT("look_manifest"), LookPath);
		FString ConfigSha;
		if (Look->TryGetStringField(TEXT("look_config_sha256"), ConfigSha))
		{
			Record->SetStringField(TEXT("look_config_sha256"), ConfigSha);
		}
		const TSharedPtr<FJsonObject>* ConstantsObject = nullptr;
		if (Look->TryGetObjectField(TEXT("constants"), ConstantsObject) && ConstantsObject != nullptr)
		{
			Constants = *ConstantsObject;
			// Every constant with its UNCALIBRATED stamp and the probe that
			// should set it, verbatim.
			Record->SetObjectField(TEXT("constants"), Constants);
		}
	}
	else
	{
		Record->SetStringField(TEXT("look_manifest"), FString::Printf(
			TEXT("absent: %s (no lights, nozzles or trails; run the import step)"), *LookPath));
	}

	// -- the materials ---------------------------------------------------------
	if (Options.bMaterials && !AssetRoot.IsEmpty())
	{
		ApplyMaterials(AssetRoot, Options);
	}
	else
	{
		Record->SetStringField(TEXT("materials"), Options.bMaterials
			? TEXT("absent: the mesh manifest names no asset_path_root")
			: TEXT("off (-aircraft-look=off or -aircraft-materials=off)"));
	}

	// -- lights, nozzles, trails ---------------------------------------------
	TArray<TSharedPtr<FJsonValue>> LightRows;
	const TArray<TSharedPtr<FJsonValue>>* Lights = nullptr;
	if (Look.IsValid() && Options.bLights && Look->TryGetArrayField(TEXT("lights"), Lights) && Lights != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *Lights)
		{
			BuildLamp(World, Value->AsObject());
		}
		for (const FLamp& Lamp : Lamps)
		{
			TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
			Row->SetStringField(TEXT("id"), Lamp.Id);
			Row->SetStringField(TEXT("kind"), Lamp.Kind);
			Row->SetField(TEXT("actor_cm"), AircraftFxVectorValue(Lamp.ActorCm));
			Row->SetNumberField(TEXT("candela"), Lamp.Candela);
			Row->SetBoolField(TEXT("bulb_drawn"), Lamp.Bulb != nullptr);
			LightRows.Add(MakeShared<FJsonValueObject>(Row));
		}
	}
	Record->SetArrayField(TEXT("lights"), LightRows);
	Record->SetStringField(TEXT("lights_note"), TEXT("point/spot lights move no geometry; the bulbs are additive ")
		TEXT("(they hide nothing), beauty-only actors the label captures hide"));

	const TArray<TSharedPtr<FJsonValue>>* NozzleRows = nullptr;
	if (Look.IsValid() && Look->TryGetArrayField(TEXT("nozzles"), NozzleRows) && NozzleRows != nullptr)
	{
		for (const TSharedPtr<FJsonValue>& Value : *NozzleRows)
		{
			BuildNozzle(World, Value->AsObject(), Options);
		}
	}
	// Trails: one contrail per nozzle (Options.bContrails), one vapour trail
	// per wingtip nav lamp. World-space, NOT attached (a trail stays where the
	// air was), each its own beauty-only actor.
	UMaterialInterface* ContrailMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxContrailMaterialPath);
	auto AddTrail = [&](const FVector& SourceActorCm, bool bVapour, const TCHAR* Name)
	{
		FTrail Trail;
		Trail.SourceActorCm = SourceActorCm;
		Trail.bVapour = bVapour;
		Trail.Owner = World->SpawnActor<AActor>();
		Trail.Mesh = AircraftFxMesh(Trail.Owner, Name);
		UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(ContrailMaterial, Trail.Mesh);
		const TCHAR* Group = bVapour ? TEXT("vapour") : TEXT("contrail");
		Instance->SetScalarParameterValue(FName(AircraftFxParamOpacity),
			static_cast<float>(Constant(Group, TEXT("Opacity"), bVapour ? 0.35 : 0.55)));
		const double Lifetime = Constant(Group, TEXT("LifetimeS"), bVapour ? 0.8 : 25.0);
		const double Formation = bVapour ? 0.0 : Constant(TEXT("contrail"), TEXT("FormationDelayS"), 0.15);
		Instance->SetScalarParameterValue(FName(AircraftFxParamFormation),
			static_cast<float>(Formation / FMath::Max(Lifetime, 0.01)));
		Trail.Mesh->SetMaterial(0, Instance);
		Trail.Mesh->RegisterComponent();
		BeautyOnlyActors.Add(Trail.Owner);
		Trails.Add(Trail);
	};
	if (ContrailMaterial != nullptr)
	{
		if (Options.bContrails)
		{
			for (const FNozzle& Nozzle : Nozzles)
			{
				AddTrail(Nozzle.ActorCm, false, TEXT("Contrail"));
			}
			for (const FLamp& Lamp : Lamps)
			{
				if (Lamp.Kind == TEXT("nav_red") || Lamp.Kind == TEXT("nav_green"))
				{
					AddTrail(Lamp.ActorCm, true, TEXT("WingtipVapour"));
				}
			}
		}
	}
	TSharedPtr<FJsonObject> ContrailRow = MakeShared<FJsonObject>();
	ContrailRow->SetStringField(TEXT("material"), ContrailMaterial != nullptr
		? AircraftFxContrailMaterialPath : TEXT("absent"));
	ContrailRow->SetBoolField(TEXT("enabled"), Options.bContrails);
	ContrailRow->SetStringField(TEXT("rule"), TEXT("drawn while atmosphere/T-R is below contrail.MaxTemperatureK ")
		TEXT("and position/h-sl-meters above contrail.MinAltitudeM (Schmidt-Appleman threshold, no humidity ")
		TEXT("modelled); wingtip vapour while accelerations/Nz exceeds vapour.MinNz"));
	ContrailRow->SetStringField(TEXT("label_convention"), TEXT("a trail is a translucent medium like the clouds ")
		TEXT("and rain the label captures already omit: where it crosses in front of the aircraft the mask ")
		TEXT("still says aircraft"));
	Record->SetObjectField(TEXT("contrail"), ContrailRow);

	TSharedPtr<FJsonObject> HazeRow = MakeShared<FJsonObject>();
	HazeRow->SetBoolField(TEXT("drawn"), false);
	HazeRow->SetBoolField(TEXT("pixel_moving"), true);
	HazeRow->SetStringField(TEXT("switch"), TEXT("-heat-haze=on (off by default; never on in a measured shot)"));
	for (const FNozzle& Nozzle : Nozzles)
	{
		if (Nozzle.Haze != nullptr)
		{
			HazeRow->SetBoolField(TEXT("drawn"), true);
			// heat_haze.hlsl: the offset never exceeds Strength / 100 of the screen.
			HazeRow->SetNumberField(TEXT("max_offset_screen_fraction"),
				Constant(TEXT("heat_haze"), TEXT("Strength"), 0.6) * 0.01);
		}
	}
	Record->SetObjectField(TEXT("heat_haze"), HazeRow);
	Record->SetNumberField(TEXT("beauty_only_actors"), BeautyOnlyActors.Num());
	bBuilt = true;
	UE_LOG(LogFlightSimAircraftFX, Display,
	       TEXT("aircraft look: %d lamp(s), %d nozzle(s), %d trail(s), %d beauty-only actor(s) (%s)"),
	       Lamps.Num(), Nozzles.Num(), Trails.Num(), BeautyOnlyActors.Num(), *LookPath);
	return true;
}

void FFlightSimAircraftFX::ApplyMaterials(const FString& AssetRoot, const FFlightSimAircraftFXOptions& Options)
{
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	if (!Options.Livery.IsEmpty() && Options.Livery != TEXT("default"))
	{
		// The sampled livery is a record the label manifest carries; it keeps
		// its own material on every slot rather than being repainted.
		Row->SetStringField(TEXT("state"), FString::Printf(TEXT("livery '%s' kept; look instances not applied"),
		                                                   *Options.Livery));
		Record->SetObjectField(TEXT("materials"), Row);
		return;
	}
	TInlineComponentArray<UStaticMeshComponent*> Parts;
	Aircraft->GetComponents(Parts);
	int32 Applied = 0;
	// Slot names without a look instance, once each (AddUnique on the JSON
	// values would compare pointers and never deduplicate a slot that several
	// parts share).
	TArray<FString> AbsentNames;
	for (UStaticMeshComponent* Part : Parts)
	{
		for (int32 Slot = 0; Slot < Part->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Current = Part->GetMaterial(Slot);
			if (Current == nullptr)
			{
				continue;
			}
			const FString SlotName = Current->GetName();
			const FString InstanceName = FString::Printf(TEXT("%s%s"), AircraftFxLookPrefix, *SlotName);
			const FString Path = FString::Printf(TEXT("%s/%s/%s.%s"), *AssetRoot, AircraftFxLookFolder,
			                                     *InstanceName, *InstanceName);
			UMaterialInterface* LookInstance = LoadObject<UMaterialInterface>(nullptr, *Path);
			if (LookInstance == nullptr)
			{
				AbsentNames.AddUnique(SlotName);
				continue;
			}
			Part->SetMaterial(Slot, LookInstance);
			++Applied;
		}
	}
	Row->SetStringField(TEXT("state"), TEXT("look instances on the mesh's slots (shading only: no world position ")
		TEXT("offset, every class master opaque, so the label silhouette is the beauty's)"));
	Row->SetStringField(TEXT("instance_root"), AssetRoot + TEXT("/") + AircraftFxLookFolder);
	Row->SetNumberField(TEXT("slots_applied"), Applied);
	TArray<TSharedPtr<FJsonValue>> Absent;
	for (const FString& Name : AbsentNames)
	{
		Absent.Add(MakeShared<FJsonValueString>(Name));
	}
	Row->SetArrayField(TEXT("slots_absent"), Absent);
	Record->SetObjectField(TEXT("materials"), Row);
	UE_LOG(LogFlightSimAircraftFX, Display, TEXT("aircraft look: %d slot(s) on look instances, %d absent"),
	       Applied, Absent.Num());
}

void FFlightSimAircraftFX::BuildLamp(UWorld* World, const TSharedPtr<FJsonObject>& Row)
{
	if (!Row.IsValid())
	{
		return;
	}
	FLamp Lamp;
	Row->TryGetStringField(TEXT("id"), Lamp.Id);
	Row->TryGetStringField(TEXT("kind"), Lamp.Kind);
	Row->TryGetNumberField(TEXT("candela"), Lamp.Candela);
	Row->TryGetBoolField(TEXT("strobe"), Lamp.bStrobe);
	Lamp.bLanding = Lamp.Kind == TEXT("landing");
	Lamp.ActorCm = AircraftFxVector(Row, TEXT("actor_cm"));
	const FVector Colour = AircraftFxVector(Row, TEXT("colour"));
	const FLinearColor Linear(Colour.X, Colour.Y, Colour.Z, 1.0f);
	const double Gain = Constant(TEXT("lights"), TEXT("LightVisualGain"), 1.0);

	AActor* Actor = SpawnAttached(World, Lamp.ActorCm, *FString::Printf(TEXT("Lamp_%s"), *Lamp.Id));
	UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
	UMaterialInterface* BulbMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxNavMaterialPath);
	if (Mesh != nullptr && BulbMaterial != nullptr)
	{
		AircraftFxBulbSection(Mesh, Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0));
		Lamp.Bulb = UMaterialInstanceDynamic::Create(BulbMaterial, Mesh);
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamLightColour), Linear);
		const double Emissive = FMath::Min(Lamp.Candela * Gain * Constant(TEXT("lights"), TEXT("BulbEmissivePerCd"), 2.0),
		                                   Constant(TEXT("lights"), TEXT("BulbEmissiveMax"), 3000.0));
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamIntensity), static_cast<float>(Emissive));
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), Lamp.bStrobe ? 0.0f : 1.0f);
		Mesh->SetMaterial(0, Lamp.Bulb);
	}
	if (Lamp.bLanding)
	{
		Lamp.Spot = NewObject<USpotLightComponent>(Actor, TEXT("LandingLight"));
		Lamp.Spot->SetMobility(EComponentMobility::Movable);
		Lamp.Spot->SetupAttachment(Actor->GetRootComponent());
		FVector Direction = AircraftFxVector(Row, TEXT("direction_actor"));
		if (Direction.IsNearlyZero())
		{
			Direction = FVector(1.0, 0.0, -0.08);
		}
		Lamp.Spot->SetRelativeRotation(FRotationMatrix::MakeFromX(Direction.GetSafeNormal()).Rotator());
		Lamp.Spot->SetIntensityUnits(ELightUnits::Candelas);
		Lamp.Spot->SetIntensity(0.0f);
		Lamp.Spot->SetLightColor(Linear);
		const float Cone = static_cast<float>(Constant(TEXT("lights"), TEXT("LandingConeDeg"), 12.0));
		Lamp.Spot->SetInnerConeAngle(0.5f * Cone);
		Lamp.Spot->SetOuterConeAngle(Cone);
		Lamp.Spot->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("lights"), TEXT("LandingAttenuationM"), 900.0) * AircraftFxCmPerMetre));
		Lamp.Spot->SetCastShadows(false);
		Lamp.Spot->RegisterComponent();
	}
	else
	{
		Lamp.Point = NewObject<UPointLightComponent>(Actor, TEXT("NavLight"));
		Lamp.Point->SetMobility(EComponentMobility::Movable);
		Lamp.Point->SetupAttachment(Actor->GetRootComponent());
		Lamp.Point->SetIntensityUnits(ELightUnits::Candelas);
		Lamp.Point->SetIntensity(Lamp.bStrobe ? 0.0f : static_cast<float>(Lamp.Candela * Gain));
		Lamp.Point->SetLightColor(Linear);
		Lamp.Point->SetSourceRadius(static_cast<float>(Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0)));
		Lamp.Point->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("lights"), TEXT("NavAttenuationM"), 40.0) * AircraftFxCmPerMetre));
		Lamp.Point->SetCastShadows(false);
		Lamp.Point->RegisterComponent();
	}
	Lamps.Add(Lamp);
}

void FFlightSimAircraftFX::BuildNozzle(UWorld* World, const TSharedPtr<FJsonObject>& Row,
                                       const FFlightSimAircraftFXOptions& Options)
{
	if (!Row.IsValid())
	{
		return;
	}
	FNozzle Nozzle;
	Row->TryGetStringField(TEXT("id"), Nozzle.Id);
	Row->TryGetNumberField(TEXT("radius_cm"), Nozzle.RadiusCm);
	Row->TryGetBoolField(TEXT("afterburner"), Nozzle.bAfterburner);
	Row->TryGetStringField(TEXT("thrust_property"), Nozzle.ThrustProperty);
	Row->TryGetNumberField(TEXT("mil_thrust_lbs"), Nozzle.MilThrustLbs);
	Row->TryGetNumberField(TEXT("max_thrust_lbs"), Nozzle.MaxThrustLbs);
	Nozzle.ActorCm = AircraftFxVector(Row, TEXT("actor_cm"));
	const bool bReheat = Options.bAfterburner && Nozzle.bAfterburner && Nozzle.MaxThrustLbs > Nozzle.MilThrustLbs
		&& Nozzle.MilThrustLbs > 0.0;
	if (bReheat)
	{
		UMaterialInterface* PlumeMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxAfterburnerMaterialPath);
		AActor* Actor = SpawnAttached(World, Nozzle.ActorCm, *FString::Printf(TEXT("Plume_%s"), *Nozzle.Id));
		UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
		if (Mesh != nullptr && PlumeMaterial != nullptr)
		{
			const double Length = Constant(TEXT("afterburner"), TEXT("PlumeLengthRadii"), 7.0) * Nozzle.RadiusCm;
			AircraftFxConeSection(Mesh, 0.85 * Nozzle.RadiusCm, 0.3 * Nozzle.RadiusCm, Length);
			Nozzle.Plume = UMaterialInstanceDynamic::Create(PlumeMaterial, Mesh);
			Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamIntensity), 0.0f);
			Mesh->SetMaterial(0, Nozzle.Plume);
		}
		Nozzle.PlumeLight = NewObject<UPointLightComponent>(Actor, TEXT("AfterburnerLight"));
		Nozzle.PlumeLight->SetMobility(EComponentMobility::Movable);
		Nozzle.PlumeLight->SetupAttachment(Actor->GetRootComponent());
		Nozzle.PlumeLight->SetRelativeLocation(FVector(-1.5 * Nozzle.RadiusCm, 0.0, 0.0));
		Nozzle.PlumeLight->SetIntensityUnits(ELightUnits::Candelas);
		Nozzle.PlumeLight->SetIntensity(0.0f);
		Nozzle.PlumeLight->SetLightColor(FLinearColor(1.0f, 0.55f, 0.25f, 1.0f));
		Nozzle.PlumeLight->SetAttenuationRadius(static_cast<float>(
			Constant(TEXT("afterburner"), TEXT("AttenuationM"), 25.0) * AircraftFxCmPerMetre));
		Nozzle.PlumeLight->SetCastShadows(false);
		Nozzle.PlumeLight->RegisterComponent();
	}
	if (Options.bHeatHaze)
	{
		UMaterialInterface* HazeMaterial = LoadObject<UMaterialInterface>(nullptr, AircraftFxHeatHazeMaterialPath);
		if (HazeMaterial != nullptr)
		{
			AActor* Actor = SpawnAttached(World, Nozzle.ActorCm, *FString::Printf(TEXT("Haze_%s"), *Nozzle.Id));
			UProceduralMeshComponent* Mesh = Cast<UProceduralMeshComponent>(Actor->GetRootComponent());
			const double Length = Constant(TEXT("heat_haze"), TEXT("LengthRadii"), 14.0) * Nozzle.RadiusCm;
			AircraftFxConeSection(Mesh, Nozzle.RadiusCm, 2.0 * Nozzle.RadiusCm, Length);
			Nozzle.Haze = UMaterialInstanceDynamic::Create(HazeMaterial, Mesh);
			Nozzle.Haze->SetScalarParameterValue(FName(AircraftFxParamStrength),
				static_cast<float>(Constant(TEXT("heat_haze"), TEXT("Strength"), 0.6)));
			Mesh->SetMaterial(0, Nozzle.Haze);
		}
	}
	Nozzles.Add(Nozzle);
}

void FFlightSimAircraftFX::RebuildTrail(FTrail& Trail, double NowS, double LifetimeS, double StartWidthM,
                                        double SpreadMPerS, double FormationS)
{
	// Expire what has faded, then a crossed ribbon (two strips at right
	// angles) through every sample: no camera needed, seen from any side.
	Trail.Samples.RemoveAll([&](const FTrailSample& S) { return NowS - S.TimeS > LifetimeS; });
	if (Trail.Samples.Num() < 2)
	{
		Trail.Mesh->ClearMeshSection(0);
		return;
	}
	// Vertices relative to the newest sample (small numbers in a large world).
	const FVector Anchor = Trail.Samples.Last().WorldCm;
	Trail.Owner->SetActorLocation(Anchor);
	TArray<FVector> Vertices;
	TArray<int32> Triangles;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	const int32 Count = Trail.Samples.Num();
	for (int32 Strip = 0; Strip < 2; ++Strip)
	{
		const int32 Base = Vertices.Num();
		for (int32 i = 0; i < Count; ++i)
		{
			const FTrailSample& S = Trail.Samples[i];
			const FVector Prev = Trail.Samples[FMath::Max(i - 1, 0)].WorldCm;
			const FVector Next = Trail.Samples[FMath::Min(i + 1, Count - 1)].WorldCm;
			const FVector Along = (Next - Prev).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
			FVector Side = FVector::CrossProduct(Along, FVector::UpVector).GetSafeNormal(UE_SMALL_NUMBER,
			                                                                           FVector::RightVector);
			const FVector Up = FVector::CrossProduct(Side, Along).GetSafeNormal();
			const FVector Across = Strip == 0 ? Side : Up;
			const FVector Normal = Strip == 0 ? Up : Side;
			const double Age = FMath::Max(NowS - S.TimeS, 0.0);
			const double HalfCm = 0.5 * (StartWidthM + SpreadMPerS * Age) * AircraftFxCmPerMetre;
			const FVector P = S.WorldCm - Anchor;
			Vertices.Add(P - Across * HalfCm);
			Vertices.Add(P + Across * HalfCm);
			Normals.Add(Normal);
			Normals.Add(Normal);
			const double U = Age / FMath::Max(LifetimeS, 0.01);
			UV0.Add(FVector2D(U, 0.0));
			UV0.Add(FVector2D(U, 1.0));
		}
		for (int32 i = 0; i + 1 < Count; ++i)
		{
			const int32 A = Base + 2 * i;
			Triangles.Append({A, A + 2, A + 1, A + 1, A + 2, A + 3});
		}
	}
	Trail.Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0, {}, {}, false);
	Trail.bEverDrawn = true;
}

void FFlightSimAircraftFX::Advance(TFunctionRef<double(const TCHAR*)> ReadProperty)
{
	if (!bBuilt || Aircraft == nullptr)
	{
		return;
	}
	const double Now = ReadProperty(TEXT("simulation/sim-time-sec"));
	const FTransform Frame = Aircraft->GetActorTransform();

	// -- lamps: steady nav lamps, the strobe on the FDM's clock, the landing
	// lamp below LandingMaxAglM.
	const double Gain = Constant(TEXT("lights"), TEXT("LightVisualGain"), 1.0);
	const double Period = FMath::Max(Constant(TEXT("lights"), TEXT("StrobePeriodS"), 1.0), 0.05);
	const double Flash = Constant(TEXT("lights"), TEXT("StrobeFlashS"), 0.12);
	const bool bStrobeOn = FMath::Fmod(FMath::Max(Now, 0.0), Period) < Flash;
	const double AglM = ReadProperty(TEXT("position/h-agl-ft")) * 0.3048;
	const bool bLandingOn = AglM < Constant(TEXT("lights"), TEXT("LandingMaxAglM"), 450.0);
	for (FLamp& Lamp : Lamps)
	{
		if (Lamp.bStrobe)
		{
			if (Lamp.Point != nullptr)
			{
				Lamp.Point->SetIntensity(bStrobeOn ? static_cast<float>(Lamp.Candela * Gain) : 0.0f);
			}
			if (Lamp.Bulb != nullptr)
			{
				Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), bStrobeOn ? 1.0f : 0.0f);
			}
		}
		if (Lamp.bLanding)
		{
			if (Lamp.Spot != nullptr)
			{
				Lamp.Spot->SetIntensity(bLandingOn ? static_cast<float>(Lamp.Candela * Gain) : 0.0f);
			}
			if (Lamp.Bulb != nullptr)
			{
				Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), bLandingOn ? 1.0f : 0.0f);
			}
		}
	}
	StrobeOnFrames += bStrobeOn ? 1 : 0;
	LandingOnFrames += bLandingOn ? 1 : 0;

	// -- the afterburner: glow from the engine's thrust above its military
	// rating (static sea-level ratings from the engine file).
	const double GlowGain = Constant(TEXT("afterburner"), TEXT("GlowGain"), 1.0);
	const double PlumeCandela = Constant(TEXT("afterburner"), TEXT("AfterburnerCandela"), 6.0e4);
	for (FNozzle& Nozzle : Nozzles)
	{
		if (Nozzle.Plume != nullptr || Nozzle.PlumeLight != nullptr)
		{
			const double Thrust = ReadProperty(*Nozzle.ThrustProperty);
			const double MilFraction = Nozzle.MilThrustLbs / Nozzle.MaxThrustLbs;
			const double Glow = GlowGain * FMath::Clamp(
				(Thrust / Nozzle.MaxThrustLbs - MilFraction) / FMath::Max(1.0 - MilFraction, 0.01), 0.0, 1.0);
			PeakAfterburner = FMath::Max(PeakAfterburner, Glow);
			if (Nozzle.Plume != nullptr)
			{
				Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamIntensity), static_cast<float>(Glow));
			}
			if (Nozzle.PlumeLight != nullptr)
			{
				Nozzle.PlumeLight->SetIntensity(static_cast<float>(Glow * PlumeCandela));
			}
		}
		if (Nozzle.Haze != nullptr)
		{
			Nozzle.Haze->SetScalarParameterValue(FName(AircraftFxParamTime), static_cast<float>(Now));
		}
	}

	// -- trails ---------------------------------------------------------------
	const double TemperatureK = ReadProperty(TEXT("atmosphere/T-R")) * AircraftFxKelvinPerRankine;
	const double AltitudeM = ReadProperty(TEXT("position/h-sl-meters"));
	const bool bContrail = TemperatureK < Constant(TEXT("contrail"), TEXT("MaxTemperatureK"), 233.15)
		&& AltitudeM > Constant(TEXT("contrail"), TEXT("MinAltitudeM"), 7500.0);
	const bool bVapour = ReadProperty(TEXT("accelerations/Nz")) > Constant(TEXT("vapour"), TEXT("MinNz"), 4.0);
	const double SpeedCmS = ReadProperty(TEXT("velocities/vtrue-kts")) * AircraftFxMpsPerKnot * AircraftFxCmPerMetre;
	ContrailFrames += bContrail ? 1 : 0;
	VapourFrames += bVapour ? 1 : 0;
	for (FTrail& Trail : Trails)
	{
		const TCHAR* Group = Trail.bVapour ? TEXT("vapour") : TEXT("contrail");
		const bool bActive = Trail.bVapour ? bVapour : bContrail;
		const FVector Source = Frame.TransformPosition(Trail.SourceActorCm);
		if (bActive)
		{
			// First frame in the regime: a trail as long as PreseedS of the
			// current flight path already behind the aircraft (a straight
			// extrapolation along its nose, stated), so frame 0 of a cruise
			// clip is not a trail just starting.
			if (bFirstAdvance && !Trail.bVapour)
			{
				const double Preseed = Constant(TEXT("contrail"), TEXT("PreseedS"), 8.0);
				const FVector Back = -Frame.GetUnitAxis(EAxis::X) * SpeedCmS;
				for (double Ago = Preseed; Ago > 0.0; Ago -= 0.5)
				{
					FTrailSample Seed;
					Seed.WorldCm = Source + Back * Ago;
					Seed.TimeS = Now - Ago;
					Trail.Samples.Add(Seed);
				}
			}
			FTrailSample Sample;
			Sample.WorldCm = Source;
			Sample.TimeS = Now;
			Trail.Samples.Add(Sample);
		}
		RebuildTrail(Trail, Now, Constant(Group, TEXT("LifetimeS"), Trail.bVapour ? 0.8 : 25.0),
		             Constant(Group, TEXT("StartWidthM"), Trail.bVapour ? 0.25 : 1.2),
		             Constant(Group, TEXT("SpreadMPerS"), Trail.bVapour ? 1.5 : 0.9),
		             Trail.bVapour ? 0.0 : Constant(TEXT("contrail"), TEXT("FormationDelayS"), 0.15));
	}
	bFirstAdvance = false;

	// The record, current at every step (render.json is written at the end).
	const TSharedPtr<FJsonObject>* ContrailRow = nullptr;
	if (Record->TryGetObjectField(TEXT("contrail"), ContrailRow) && ContrailRow != nullptr)
	{
		(*ContrailRow)->SetNumberField(TEXT("contrail_frames"), ContrailFrames);
		(*ContrailRow)->SetNumberField(TEXT("vapour_frames"), VapourFrames);
	}
	TSharedPtr<FJsonObject> Afterburner = MakeShared<FJsonObject>();
	Afterburner->SetNumberField(TEXT("peak_glow"), PeakAfterburner);
	Afterburner->SetStringField(TEXT("rule"), TEXT("glow = saturate((thrust/max - mil/max) / (1 - mil/max)) x GlowGain, ")
		TEXT("static sea-level ratings from the engine file; additive plume, hides nothing"));
	Record->SetObjectField(TEXT("afterburner"), Afterburner);
	Record->SetNumberField(TEXT("strobe_on_frames"), StrobeOnFrames);
	Record->SetNumberField(TEXT("landing_light_on_frames"), LandingOnFrames);
}
