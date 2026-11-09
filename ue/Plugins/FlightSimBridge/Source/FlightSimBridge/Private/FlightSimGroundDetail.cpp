// The ground scatter (FlightSimGroundDetail.h): seeded instances traced onto
// the tiles. BEAUTY ONLY, VISUAL ONLY. UNCOMPILED when written (2026-11-09, a
// Mac whose Xcode is above UE 5.7's cap); the engine symbols are checked by
// scripts/check_bridge_api.sh ("world lane"), the pure block below is compiled
// and checked against core/scene/world_beauty.py by tests/test_world_beauty.py.

#include "FlightSimGroundDetail.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "CollisionQueryParams.h"
#include "Dom/JsonValue.h"
#include "Engine/HitResult.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "FlightSimGoogleTiles.h"
#include "FlightSimVisualScene.h"
#include "GameFramework/Actor.h"
#include "GeoReferencingSystem.h"
#include "Materials/Material.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

#include <cmath>
#include <cstdint>

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimGroundDetail, Log, All);

// The placement law, dependency-free C++17 so tests/test_world_beauty.py can
// compile this block alone and compare it with core/scene/world_beauty.py.
// FLIGHTSIM-SCATTER-PURE-BEGIN
namespace FlightSimScatterPure
{
	// SplitMix64's output function (Steele / Vigna): rain_field.splitmix64.
	inline uint64_t SplitMix64(uint64_t X)
	{
		uint64_t Z = X + 0x9E3779B97F4A7C15ull;
		Z = (Z ^ (Z >> 30)) * 0xBF58476D1CE4E5B9ull;
		Z = (Z ^ (Z >> 27)) * 0x94D049BB133111EBull;
		return Z ^ (Z >> 31);
	}

	// A uniform in [0, 1): rain_field.unit (the weather's own law).
	inline double Unit(uint64_t Seed, uint64_t Index, uint64_t Channel)
	{
		const uint64_t Key = SplitMix64(Index * 8ull + Channel);
		return static_cast<double>(SplitMix64(Seed ^ Key) >> 11) * (1.0 / 9007199254740992.0);
	}

	// One species' stream: splitmix64(seed + index + 1).
	inline uint64_t SpeciesSeed(uint64_t Seed, uint64_t SpeciesIndex)
	{
		return SplitMix64(Seed + SpeciesIndex + 1ull);
	}

	// round(density x area / 1 ha), at most MaxInstances.
	inline int64_t InstanceCount(double DensityPerHa, double HalfEastM, double HalfNorthM,
	                             int64_t MaxInstances)
	{
		const double AreaM2 = 4.0 * (HalfEastM > 0.0 ? HalfEastM : 0.0) * (HalfNorthM > 0.0 ? HalfNorthM : 0.0);
		const double Density = DensityPerHa > 0.0 ? DensityPerHa : 0.0;
		int64_t Count = static_cast<int64_t>(std::floor(Density * AreaM2 / 1.0e4 + 0.5));
		if (Count > MaxInstances)
		{
			Count = MaxInstances;
		}
		return Count > 0 ? Count : 0;
	}

	struct FPlacement
	{
		double EastM;
		double NorthM;
		double YawDeg;
		double Scale;
	};

	// Region-relative east / north, yaw and scale: uniforms 0..3 of the stream.
	inline FPlacement Place(uint64_t Seed, uint64_t SpeciesIndex, uint64_t Index, double HalfEastM,
	                        double HalfNorthM, double ScaleMin, double ScaleMax)
	{
		const uint64_t Key = SpeciesSeed(Seed, SpeciesIndex);
		FPlacement Out;
		Out.EastM = (2.0 * Unit(Key, Index, 0) - 1.0) * HalfEastM;
		Out.NorthM = (2.0 * Unit(Key, Index, 1) - 1.0) * HalfNorthM;
		Out.YawDeg = 360.0 * Unit(Key, Index, 2);
		Out.Scale = ScaleMin + (ScaleMax - ScaleMin) * Unit(Key, Index, 3);
		return Out;
	}

	inline bool Excluded(double EastM, double NorthM, double CentreEastM, double CentreNorthM,
	                     double RadiusM)
	{
		return std::hypot(EastM - CentreEastM, NorthM - CentreNorthM) < RadiusM;
	}

	// A hit whose up-component is under cos(max slope) is too steep to stand on.
	inline bool SlopeAccepted(double NormalZ, double MaxSlopeDeg)
	{
		return NormalZ >= std::cos(MaxSlopeDeg * 3.14159265358979323846 / 180.0);
	}

	// The probe ring's heights (m) spanning more than StepRejectM: a roof or a
	// cliff edge, not ground to stand a tree on.
	inline bool StepAccepted(const double* HeightsM, int Count, double StepRejectM)
	{
		if (Count <= 0)
		{
			return false;
		}
		double Lo = HeightsM[0];
		double Hi = HeightsM[0];
		for (int I = 1; I < Count; ++I)
		{
			Lo = HeightsM[I] < Lo ? HeightsM[I] : Lo;
			Hi = HeightsM[I] > Hi ? HeightsM[I] : Hi;
		}
		return Hi - Lo <= StepRejectM;
	}
}
// FLIGHTSIM-SCATTER-PURE-END

namespace
{
	constexpr double ScatterCmPerMetre = 100.0;
	const TCHAR* const ScatterFormat = TEXT("flightsim.ground_scatter");
	constexpr int32 ScatterVersion = 1;
	// core/scene/world_beauty.py MAX_TOTAL_INSTANCES.
	constexpr int64 ScatterMaxTotalInstances = 100000;
	// A re-snap that moves an instance less than this is not applied (no churn
	// in the render state for sub-centimetre LOD changes).
	constexpr double ScatterResnapToleranceCm = 5.0;
	// The nadir view the region is loaded from before the first trace.
	constexpr double ScatterNadirFovDeg = 60.0;
	constexpr int32 ScatterNadirPixels = 1024;
	// world_beauty.SCATTER_MATERIAL: the master that reads the tiles' Wetness and
	// Saturation (MPC_FlightSimWorld); a species drawn with any other material
	// stays dry and ungraded over wet tiles, recorded so.
	const TCHAR* const ScatterWorldMaterialPath = TEXT("/Game/FlightSim/M_FlightSimScatter.M_FlightSimScatter");
	// world_beauty.SCATTER_DEFAULTS cull_start_share (UNCALIBRATED).
	constexpr double ScatterCullStartShareDefault = 0.7;
	// world_beauty.BIOMES: the surfaces that carry species.
	bool ScatterIsBiome(const FString& Surface)
	{
		return Surface == TEXT("forest") || Surface == TEXT("desert");
	}

	double ScatterNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Key, double Default)
	{
		double Value = Default;
		if (Object.IsValid())
		{
			Object->TryGetNumberField(Key, Value);
		}
		return Value;
	}

	bool ScatterLicenceAllowed(const FString& Licence)
	{
		return Licence == TEXT("CC0-1.0") || Licence == TEXT("CC-BY-4.0");
	}

	bool ScatterIsSha256(const FString& Value)
	{
		if (Value.Len() != 64)
		{
			return false;
		}
		for (const TCHAR Char : Value)
		{
			if (!FChar::IsHexDigit(Char))
			{
				return false;
			}
		}
		return true;
	}

	bool CardNamesVegetation(const TSharedPtr<FJsonObject>& Card)
	{
		const TArray<TSharedPtr<FJsonValue>>* Objects = nullptr;
		if (!Card.IsValid() || !Card->TryGetArrayField(TEXT("objects"), Objects) || Objects == nullptr)
		{
			return false;
		}
		for (const TSharedPtr<FJsonValue>& Value : *Objects)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			FString Id;
			if (Value.IsValid() && Value->TryGetObject(Entry) && Entry != nullptr &&
			    (*Entry)->TryGetStringField(TEXT("id"), Id) && Id == FlightSimWorld::VegetationObjectId)
			{
				return true;
			}
		}
		return false;
	}
}

bool FFlightSimGroundDetail::TraceGround(double XCm, double YCm, double& OutZCm, FVector& OutNormal) const
{
	if (WorldRef == nullptr)
	{
		return false;
	}
	FCollisionQueryParams Params(FName(TEXT("FlightSimScatter")), true);
	Params.AddIgnoredActors(Ignored);
	FHitResult Hit;
	const FVector Start(XCm, YCm, TraceUpCm);
	const FVector End(XCm, YCm, -TraceDownCm);
	if (!WorldRef->LineTraceSingleByChannel(Hit, Start, End, ECC_Visibility, Params))
	{
		return false;
	}
	// The tiles draw: only the tileset's own primitives are ground (UNVERIFIED:
	// Cesium for Unreal 2.x parents its glTF primitive components to the
	// tileset actor, so the hit's actor is the tileset; a first render that
	// records every candidate as "not_tileset" means it does not).
	if (Tileset.IsValid() && Hit.GetActor() != Tileset.Get())
	{
		return false;
	}
	OutZCm = Hit.ImpactPoint.Z;
	OutNormal = Hit.ImpactNormal;
	return true;
}

bool FFlightSimGroundDetail::Build(UWorld* World, const FString& SidecarPath,
                                   const TSharedPtr<FJsonObject>& Card, AActor* Aircraft,
                                   FFlightSimGoogleTiles* Tiles, AGeoReferencingSystem* GeoReferencing,
                                   FString& Error)
{
	Record = MakeShared<FJsonObject>();
	Record->SetStringField(TEXT("sidecar"), SidecarPath);
	Record->SetBoolField(TEXT("visual_only"), true);
	WorldRef = World;
	FString Text;
	TSharedPtr<FJsonObject> Sidecar;
	if (!FFileHelper::LoadFileToString(Text, *SidecarPath) ||
	    !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Sidecar) || !Sidecar.IsValid())
	{
		Error = FString::Printf(TEXT("ground_scatter.sidecar: %s could not be read as JSON"), *SidecarPath);
		return false;
	}
	FString Format;
	Sidecar->TryGetStringField(TEXT("format"), Format);
	if (Format != ScatterFormat || static_cast<int32>(ScatterNumber(Sidecar, TEXT("version"), 0.0)) != ScatterVersion)
	{
		Error = FString::Printf(TEXT("ground_scatter.sidecar: %s is format '%s' version %d, not %s version %d ")
		                        TEXT("(core/scene/world_beauty.py scatter_sidecar writes it)"),
		                        *SidecarPath, *Format, static_cast<int32>(ScatterNumber(Sidecar, TEXT("version"), 0.0)),
		                        ScatterFormat, ScatterVersion);
		return false;
	}
	const TSharedPtr<FJsonObject>* RegionJson = nullptr;
	const TArray<TSharedPtr<FJsonValue>>* SpeciesJson = nullptr;
	if (!Sidecar->TryGetObjectField(TEXT("region"), RegionJson) || RegionJson == nullptr ||
	    !Sidecar->TryGetArrayField(TEXT("species"), SpeciesJson) || SpeciesJson == nullptr)
	{
		Error = FString::Printf(TEXT("ground_scatter.sidecar: %s carries no region or species"), *SidecarPath);
		return false;
	}
	// The biome is the card's surface (weather_look.surface, world_beauty.
	// scatter_biome_for): a forest sidecar on a desert card is refused; a card
	// whose surface carries no species (snow, ocean, city, ...) draws none.
	{
		FString Biome, Surface;
		Sidecar->TryGetStringField(TEXT("biome"), Biome);
		const TSharedPtr<FJsonObject>* WeatherLook = nullptr;
		if (Card.IsValid() && Card->TryGetObjectField(TEXT("weather_look"), WeatherLook) && WeatherLook != nullptr)
		{
			(*WeatherLook)->TryGetStringField(TEXT("surface"), Surface);
		}
		Record->SetStringField(TEXT("biome"), Biome);
		Record->SetStringField(TEXT("card_surface"), Surface);
		if (!Surface.IsEmpty() && !ScatterIsBiome(Surface))
		{
			Record->SetStringField(TEXT("drawn"),
				FString::Printf(TEXT("nothing: the card's surface '%s' carries no scatter species (forest, desert)"),
				                *Surface));
			bBuilt = false;
			return true;
		}
		if (!Surface.IsEmpty() && Biome != Surface)
		{
			Error = FString::Printf(TEXT("ground_scatter.biome: %s is the '%s' biome but the card's surface is '%s' ")
			                        TEXT("(write the sidecar for the card's surface: python -m core.scene.world_beauty ")
			                        TEXT("--biome %s)"), *SidecarPath, *Biome, *Surface, *Surface);
			return false;
		}
		Record->SetStringField(TEXT("biome_basis"), Surface.IsEmpty()
			? TEXT("the sidecar's: the card states no surface")
			: TEXT("the card's surface (weather_look.surface)"));
	}
	const TSharedPtr<FJsonObject> Region = *RegionJson;
	const TSharedPtr<FJsonObject>* ExclusionJson = nullptr;
	Sidecar->TryGetObjectField(TEXT("exclusion"), ExclusionJson);
	const TSharedPtr<FJsonObject> Exclusion = ExclusionJson != nullptr ? *ExclusionJson : nullptr;

	const uint64 Seed = static_cast<uint64>(static_cast<int64>(ScatterNumber(Sidecar, TEXT("seed"), 0.0)));
	const double CentreEastM = ScatterNumber(Region, TEXT("centre_east_m"), 0.0);
	const double CentreNorthM = ScatterNumber(Region, TEXT("centre_north_m"), 0.0);
	const double HalfEastM = ScatterNumber(Region, TEXT("half_east_m"), 0.0);
	const double HalfNorthM = ScatterNumber(Region, TEXT("half_north_m"), 0.0);
	const double MaxSlopeDeg = ScatterNumber(Sidecar, TEXT("max_slope_deg"), 32.0);
	const double StepRejectM = ScatterNumber(Sidecar, TEXT("step_reject_m"), 2.5);
	const double ProbeOffsetCm = ScatterNumber(Sidecar, TEXT("probe_offset_m"), 4.0) * ScatterCmPerMetre;
	SinkCm = ScatterNumber(Sidecar, TEXT("sink_m"), 0.3) * ScatterCmPerMetre;
	const double CullStartShare = FMath::Clamp(
		ScatterNumber(Sidecar, TEXT("cull_start_share"), ScatterCullStartShareDefault), 0.0, 1.0);
	TraceUpCm = ScatterNumber(Sidecar, TEXT("trace_up_m"), 3000.0) * ScatterCmPerMetre;
	TraceDownCm = ScatterNumber(Sidecar, TEXT("trace_down_m"), 3000.0) * ScatterCmPerMetre;

	// The engine's east and north, measured where the georeferencing exists.
	FString FrameBasis = TEXT("assumed east-south-up (no georeferencing)");
	if (GeoReferencing != nullptr && Card.IsValid())
	{
		const double Lat = ScatterNumber(Card, TEXT("latitude_deg"), 0.0);
		const double Lon = ScatterNumber(Card, TEXT("longitude_deg"), 0.0);
		FVector Origin, North, East;
		GeoReferencing->GeographicToEngine(FGeographicCoordinates(Lon, Lat, 0.0), Origin);
		GeoReferencing->GeographicToEngine(FGeographicCoordinates(Lon, Lat + 0.001, 0.0), North);
		GeoReferencing->GeographicToEngine(FGeographicCoordinates(Lon + 0.001, Lat, 0.0), East);
		const FVector NorthDir = FVector(North.X - Origin.X, North.Y - Origin.Y, 0.0).GetSafeNormal();
		const FVector EastDir = FVector(East.X - Origin.X, East.Y - Origin.Y, 0.0).GetSafeNormal();
		if (!NorthDir.IsNearlyZero() && !EastDir.IsNearlyZero())
		{
			NorthCm = NorthDir * ScatterCmPerMetre;
			EastCm = EastDir * ScatterCmPerMetre;
			FrameBasis = TEXT("measured through the georeferencing at the card's origin");
		}
	}
	Record->SetStringField(TEXT("frame_basis"), FrameBasis);

	// Nothing the trace must not stand a tree on: the aircraft, the scene's own
	// (hidden, when the tiles draw) ground.
	Ignored.Reset();
	if (Aircraft != nullptr)
	{
		Ignored.Add(Aircraft);
	}
	const bool bTiles = Tiles != nullptr && Tiles->IsEnabled() && Tiles->GetTilesetActor() != nullptr;
	if (bTiles)
	{
		Tileset = Tiles->GetTilesetActor();
		for (TActorIterator<AActor> It(World); It; ++It)
		{
			if (It->ActorHasTag(FName(TEXT("FlightSim.terrain"))))
			{
				Ignored.Add(*It);
			}
		}
		// The region's tiles, loaded from a nadir view over its centre high
		// enough to see all of it (the near LOD is refined per frame by Resnap).
		const double HalfCm = FMath::Max(HalfEastM, HalfNorthM) * ScatterCmPerMetre;
		const FVector CentreCm = EastCm * CentreEastM + NorthCm * CentreNorthM;
		const double HeightCm = HalfCm / FMath::Tan(FMath::DegreesToRadians(0.5 * ScatterNadirFovDeg));
		if (!Tiles->WaitForView(CentreCm + FVector(0.0, 0.0, HeightCm), FRotator(-90.0, 0.0, 0.0),
		                        ScatterNadirFovDeg, ScatterNadirPixels, ScatterNadirPixels, Error))
		{
			return false;
		}
		Record->SetNumberField(TEXT("nadir_preload_height_m"), HeightCm / ScatterCmPerMetre);
	}
	Record->SetStringField(TEXT("ground"), bTiles ? TEXT("Google tiles (the tileset's own hits)")
	                                              : TEXT("the scene's ground (no tiles drawn)"));

	const bool bVegetation = CardNamesVegetation(Card);
	Record->SetStringField(TEXT("labels"), bVegetation
		? TEXT("in the label passes as the card's vegetation:all (tag FlightSim.vegetation)")
		: TEXT("in the label passes as the ground (the terrain id): the card names no vegetation:all"));
	Record->SetStringField(TEXT("label_basis"),
		TEXT("the instances are in the beauty frame, so they are in the same frame's mask, class and depth; "
		     "a tree in front of the aircraft cuts both"));

	TArray<TSharedPtr<FJsonValue>> SpeciesRows;
	int64 Total = 0;
	for (int32 SpeciesIndex = 0; SpeciesIndex < SpeciesJson->Num(); ++SpeciesIndex)
	{
		const TSharedPtr<FJsonObject>* RowJson = nullptr;
		if (!(*SpeciesJson)[SpeciesIndex]->TryGetObject(RowJson) || RowJson == nullptr)
		{
			continue;
		}
		const TSharedPtr<FJsonObject> Row = *RowJson;
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		FString Id, MeshPath, Licence, Sha256, SourceUrl;
		bool bPinned = false;
		Row->TryGetStringField(TEXT("id"), Id);
		Row->TryGetStringField(TEXT("mesh"), MeshPath);
		Row->TryGetStringField(TEXT("licence"), Licence);
		Row->TryGetStringField(TEXT("sha256"), Sha256);
		Row->TryGetStringField(TEXT("source_url"), SourceUrl);
		Row->TryGetBoolField(TEXT("pinned"), bPinned);
		Out->SetStringField(TEXT("id"), Id);
		Out->SetStringField(TEXT("mesh"), MeshPath);
		Out->SetStringField(TEXT("licence"), Licence);
		Out->SetStringField(TEXT("sha256"), Sha256);
		Out->SetStringField(TEXT("source_url"), SourceUrl);
		SpeciesRows.Add(MakeShared<FJsonValueObject>(Out));
		Species.AddDefaulted();
		if (!bPinned || !ScatterIsSha256(Sha256) || !ScatterLicenceAllowed(Licence) || SourceUrl.IsEmpty())
		{
			Out->SetStringField(TEXT("drawn"),
				TEXT("nothing: the asset is not pinned (source URL, an allowed licence, and every file's sha256; "
				     "scripts/fetch_scatter_assets.py --write-pins)"));
			continue;
		}
		UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *MeshPath);
		if (Mesh == nullptr)
		{
			Out->SetStringField(TEXT("drawn"), TEXT("nothing: the mesh did not load (import the pinned glTF)"));
			continue;
		}
		AActor* Holder = World->SpawnActor<AActor>();
		UInstancedStaticMeshComponent* Instances =
			NewObject<UInstancedStaticMeshComponent>(Holder, *FString::Printf(TEXT("Scatter_%s"), *Id));
		Holder->SetRootComponent(Instances);
		Instances->SetMobility(EComponentMobility::Movable);
		Instances->SetStaticMesh(Mesh);
		Instances->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Instances->SetCastShadow(true);
		const double CullEndCm = ScatterNumber(Row, TEXT("cull_end_m"), 3000.0) * ScatterCmPerMetre;
		// A fade band (M_FlightSimScatter dithers on PerInstanceFadeAmount
		// between the two), not a pop at a fixed range.
		Instances->SetCullDistances(static_cast<int32>(FMath::Min(CullEndCm * CullStartShare, 2.0e9)),
		                            static_cast<int32>(FMath::Min(CullEndCm, 2.0e9)));
		Instances->RegisterComponent();
		Out->SetNumberField(TEXT("cull_start_m"), CullEndCm * CullStartShare / ScatterCmPerMetre);
		Out->SetNumberField(TEXT("cull_end_m"), CullEndCm / ScatterCmPerMetre);
		// The ground state: every material slot an instance of the world
		// scatter master, else this species stays dry over wet tiles.
		bool bWorldMaterial = Mesh->GetStaticMaterials().Num() > 0;
		for (int32 Slot = 0; Slot < Mesh->GetStaticMaterials().Num(); ++Slot)
		{
			UMaterialInterface* SlotMaterial = Mesh->GetMaterial(Slot);
			const UMaterial* SlotBase = SlotMaterial != nullptr ? SlotMaterial->GetBaseMaterial() : nullptr;
			bWorldMaterial = bWorldMaterial && SlotBase != nullptr &&
				SlotBase->GetPathName() == ScatterWorldMaterialPath;
		}
		Out->SetStringField(TEXT("ground_state"), bWorldMaterial
			? TEXT("wet and graded with the tiles (M_FlightSimScatter reads MPC_FlightSimWorld Wetness, Saturation)")
			: TEXT("dry: not the world material (scripts/ue_import_scatter.py parents the import to M_FlightSimScatter)"));
		if (bVegetation)
		{
			Holder->Tags.Add(FName(FlightSimWorld::VegetationTag));
		}
		Ignored.Add(Holder);
		FSpecies& State = Species.Last();
		State.Instances = Instances;
		// Every drawn instance is re-traced onto the level of detail the frame
		// streamed: the re-snap radius is the species' own cull distance.
		State.ResnapRadiusCm = ScatterNumber(Row, TEXT("resnap_radius_m"), CullEndCm / ScatterCmPerMetre) *
			ScatterCmPerMetre;
		Out->SetNumberField(TEXT("resnap_radius_m"), State.ResnapRadiusCm / ScatterCmPerMetre);

		const int64 Budget = FMath::Max<int64>(ScatterMaxTotalInstances - Total, 0);
		const int64 Count = FlightSimScatterPure::InstanceCount(
			ScatterNumber(Row, TEXT("density_per_ha"), 0.0), HalfEastM, HalfNorthM,
			FMath::Min<int64>(static_cast<int64>(ScatterNumber(Row, TEXT("max_instances"),
			                                                   static_cast<double>(ScatterMaxTotalInstances))),
			                  Budget));
		const double ScaleMin = ScatterNumber(Row, TEXT("scale_min"), 1.0);
		const double ScaleMax = ScatterNumber(Row, TEXT("scale_max"), 1.0);
		int32 ExcludedCount = 0, Missed = 0, Steep = 0, Edge = 0;
		for (int64 Index = 0; Index < Count; ++Index)
		{
			const FlightSimScatterPure::FPlacement P = FlightSimScatterPure::Place(
				Seed, static_cast<uint64>(SpeciesIndex), static_cast<uint64>(Index), HalfEastM, HalfNorthM,
				ScaleMin, ScaleMax);
			const double EastM = P.EastM + CentreEastM;
			const double NorthM = P.NorthM + CentreNorthM;
			if (Exclusion.IsValid() &&
			    FlightSimScatterPure::Excluded(EastM, NorthM, ScatterNumber(Exclusion, TEXT("centre_east_m"), 0.0),
			                                   ScatterNumber(Exclusion, TEXT("centre_north_m"), 0.0),
			                                   ScatterNumber(Exclusion, TEXT("radius_m"), 0.0)))
			{
				++ExcludedCount;
				continue;
			}
			const FVector XY = EastCm * EastM + NorthCm * NorthM;
			double ZCm = 0.0;
			FVector Normal = FVector::UpVector;
			if (!TraceGround(XY.X, XY.Y, ZCm, Normal))
			{
				++Missed;
				continue;
			}
			if (!FlightSimScatterPure::SlopeAccepted(Normal.Z, MaxSlopeDeg))
			{
				++Steep;
				continue;
			}
			// The probe ring: four traces ProbeOffset away; a step over
			// StepReject between any of the five is a roof or an edge.
			double Heights[5] = {ZCm / ScatterCmPerMetre, 0.0, 0.0, 0.0, 0.0};
			int32 Probes = 1;
			const FVector2D Ring[4] = {{1.0, 0.0}, {-1.0, 0.0}, {0.0, 1.0}, {0.0, -1.0}};
			for (const FVector2D& Offset : Ring)
			{
				double ProbeZ = 0.0;
				FVector ProbeNormal;
				if (TraceGround(XY.X + Offset.X * ProbeOffsetCm, XY.Y + Offset.Y * ProbeOffsetCm, ProbeZ, ProbeNormal))
				{
					Heights[Probes++] = ProbeZ / ScatterCmPerMetre;
				}
			}
			if (!FlightSimScatterPure::StepAccepted(Heights, Probes, StepRejectM))
			{
				++Edge;
				continue;
			}
			const FTransform Transform(FRotator(0.0, P.YawDeg, 0.0), FVector(XY.X, XY.Y, ZCm - SinkCm),
			                           FVector(P.Scale));
			Instances->AddInstance(Transform, true);
			State.GroundXYCm.Add(FVector2D(XY.X, XY.Y));
			State.Scale.Add(P.Scale);
			State.YawDeg.Add(P.YawDeg);
		}
		Total += State.GroundXYCm.Num();
		Out->SetNumberField(TEXT("candidates"), static_cast<double>(Count));
		Out->SetNumberField(TEXT("placed"), State.GroundXYCm.Num());
		Out->SetNumberField(TEXT("excluded"), ExcludedCount);
		Out->SetNumberField(TEXT("missed_or_not_tileset"), Missed);
		Out->SetNumberField(TEXT("too_steep"), Steep);
		Out->SetNumberField(TEXT("edge_or_roof"), Edge);
		Out->SetStringField(TEXT("drawn"), TEXT("instances of the pinned mesh"));
	}
	Record->SetArrayField(TEXT("species"), SpeciesRows);
	Record->SetNumberField(TEXT("seed"), static_cast<double>(Seed));
	Record->SetNumberField(TEXT("instances"), static_cast<double>(Total));
	Record->SetStringField(TEXT("resnap_radius_m"), TEXT("per species (species[].resnap_radius_m: its cull_end_m)"));
	Record->SetStringField(TEXT("not_claimed"),
		TEXT("no collision (the flight model never sees these); a seeded uniform scatter, not the land "
		     "cover's trees; may stand on flat roofs or water; positions follow the tiles Cesium streamed, "
		     "so a replay is identical only when the same tiles stream"));
	bBuilt = true;
	UE_LOG(LogFlightSimGroundDetail, Display, TEXT("ground scatter: %lld instance(s) from %s"),
	       static_cast<long long>(Total), *SidecarPath);
	return true;
}

void FFlightSimGroundDetail::Resnap(const FVector& CameraCm)
{
	if (!bBuilt)
	{
		return;
	}
	int32 Moved = 0;
	for (FSpecies& State : Species)
	{
		if (State.Instances == nullptr || State.ResnapRadiusCm <= 0.0)
		{
			continue;
		}
		const double RadiusSq = State.ResnapRadiusCm * State.ResnapRadiusCm;
		bool bDirty = false;
		for (int32 Index = 0; Index < State.GroundXYCm.Num(); ++Index)
		{
			const FVector2D& XY = State.GroundXYCm[Index];
			if (FVector2D::DistSquared(XY, FVector2D(CameraCm.X, CameraCm.Y)) > RadiusSq)
			{
				continue;
			}
			double ZCm = 0.0;
			FVector Normal;
			if (!TraceGround(XY.X, XY.Y, ZCm, Normal))
			{
				continue;
			}
			FTransform Current;
			if (!State.Instances->GetInstanceTransform(Index, Current, true) ||
			    FMath::Abs(Current.GetLocation().Z - (ZCm - SinkCm)) < ScatterResnapToleranceCm)
			{
				continue;
			}
			const FTransform Snapped(FRotator(0.0, State.YawDeg[Index], 0.0),
			                         FVector(XY.X, XY.Y, ZCm - SinkCm), FVector(State.Scale[Index]));
			State.Instances->UpdateInstanceTransform(Index, Snapped, true, false, true);
			bDirty = true;
			++Moved;
		}
		if (bDirty)
		{
			State.Instances->MarkRenderStateDirty();
		}
	}
	ResnapMoved += Moved;
	++ResnapFrames;
	if (Record.IsValid())
	{
		Record->SetNumberField(TEXT("resnap_frames"), ResnapFrames);
		Record->SetNumberField(TEXT("resnap_moved_total"), ResnapMoved);
	}
}
