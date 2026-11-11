// Visual push lane C (2026-11-11): the tornado in BEAUTY.
//
// Round 5 (f7232cc7) drew #10's tornado as a tan cone on a faceted octagonal
// base filling the frame: the scenario world's markers (FlightSimScenarioWorld.cpp,
// 24 segments x 20 rings, a solid 2.2-core-radius dust cone, a 1.35 km lens of a
// wall cloud), lit opaque. Those meshes are drawn on EVERY render quality and the
// measure renders must stay byte-identical, so this file never touches Build: the
// render commandlet calls FFlightSimScenarioWorld::BuildBeautyTornado under
// -quality=beauty only, and it
//
//  * rebuilds the funnel's and the wall cloud's mesh section 0 IN PLACE (same
//    actors, same component names, same spin from SIM time) with smooth,
//    high-resolution geometry: a tapered funnel with seeded multi-octave ragged
//    radii (section 0, the core) and a soft outer sheath (section 1), and a broad,
//    flatter wall-cloud underside whose rim rises and thins into the storm deck.
//    UV0.x carries each vertex's COVERAGE (1 solid .. 0 gone) and UV0.y its height
//    share; M_TornadoFunnel (generation 4, scripts/ue_create_materials.py) clips the
//    core where coverage x the grazing fade, moved by an erosion noise, falls below
//    0.5 (a torn edge, no dither: round 7 rendered generation 3's dither as a
//    stipple), and the sheath takes M_TornadoFunnelSoft (translucent: the soft edge);
//  * adds two beauty-only actors of camera-facing smoke puffs (Kenney's CC0 puffs,
//    assets/looks/tornado/, through M_TornadoPuff): the low swirling dust cloud at
//    the ground contact (replacing the solid cone, which the refined funnel mesh no
//    longer carries) and dark scud under the wall cloud's base, each spun at the
//    Rankine rate at its own radius.
//
// Labels: the funnel and the wall cloud stay DEPTH-WRITING (BLEND_MASKED): a pixel
// the beauty shows as funnel is funnel in the label depth captures too, so the
// funnel occludes the aircraft in the labels exactly where it is solid. The core's
// clip is deterministic (no dither, no temporal term), so the label captures see the
// beauty's core silhouette pixel for pixel. The sheath is TRANSLUCENT (no depth): a
// soft, thin condensation edge, like a cloud, is not an occluder in the labels. The
// puffs are TRANSLUCENT (no depth) too, and listed in
// BeautyOnlyActors, the policy every cloud in this project already follows
// (FlightSimClouds.cpp): thin smoke is not an occluder in the labels. Physics is
// untouched: no wind, no vortex placement, no flight state is read or written here
// beyond the card's tornado constants. Every number is UNCALIBRATED (probe #10 on
// the render machine); core/scene/weather_look.py BEAUTY_TORNADO_* is the Python
// twin, pinned constant for constant by tests/test_tornado_look.py.

#include "FlightSimScenarioWorld.h"

#include "Components/MaterialBillboardComponent.h"
#include "Components/SceneComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "GeoReferencingSystem.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/RandomStream.h"
#include "ProceduralMeshComponent.h"

namespace FlightSimTornadoBeautyLocal
{
	// The markers' shares (FlightSimScenarioWorld.cpp; weather_look.FUNNEL_TOP_SHARE..).
	constexpr double TornadoBeautyFunnelTopShare = 0.5;
	constexpr double TornadoBeautyFunnelTopRadii = 1.3;
	constexpr double TornadoBeautyWallTopShare = 0.8;

	// The funnel: smooth (BeautyFunnelSegments around, BeautyFunnelRings up), its
	// radius RCore x (BaseRadii + (TopRadii - BaseRadii) x F^TaperPower): a narrow
	// rope low down flaring into the wall cloud. Coverage rises from
	// GroundCoverage at the ground to 1 at ContactShare of its height (the
	// condensation thins toward the ground; the dust cloud hides the contact).
	// The sheath: a second shell SheathScale x the radius + SheathPadRadii,
	// SheathCoverage x the core's coverage (a soft halo around the condensation).
	constexpr int32 BeautyFunnelSegments = 64;
	constexpr int32 BeautyFunnelRings = 96;
	constexpr double BeautyFunnelBaseRadii = 0.16;
	constexpr double BeautyFunnelTaperPower = 2.6;
	constexpr double BeautyFunnelGroundCoverage = 0.25;
	constexpr double BeautyFunnelContactShare = 0.12;
	constexpr double BeautyFunnelBendRadii = 0.12;
	constexpr double BeautySheathScale = 1.35;
	constexpr double BeautySheathPadRadii = 0.08;
	constexpr double BeautySheathCoverage = 0.4;

	// The wall cloud's underside, from the funnel's top outward and up into the
	// deck: {height share of the wall's depth, radius in core radii, coverage,
	// ragged}. The rim's coverage falls to 0 (it dissolves into the storm deck
	// instead of ending on a hard lens edge); the top closes over it.
	constexpr int32 BeautyWallSegments = 64;
	constexpr int32 BeautyWallRows = 10;
	constexpr double BeautyWallProfile[BeautyWallRows][4] = {
		{0.00, 1.30, 1.00, 0.3},
		{0.04, 2.00, 1.00, 0.6},
		{0.10, 2.90, 1.00, 1.0},
		{0.18, 3.70, 0.90, 1.4},
		{0.28, 4.40, 0.60, 1.8},
		{0.40, 5.00, 0.30, 2.2},
		{0.55, 5.40, 0.00, 2.5},
		{0.75, 4.20, 0.00, 1.0},
		{1.00, 2.50, 1.00, 0.8},
		{1.06, 0.40, 1.00, 0.3},
	};
	// The underside's lumps, as a share of the wall's depth per unit ragged.
	constexpr double BeautyWallLumpShare = 0.03;

	// The puffs: {count, radius range (core radii), size range (m), opacity range}.
	// Dust at the ground contact, a few debris puffs up the funnel's foot, scud
	// in a band about the wall cloud's base.
	// Round 7 (lane C fix): round 7 drew the dust as one beige blob wider than the
	// funnel is tall (36 puffs of 60-200 m out to 2.4 core radii). The dust is now
	// a low, ragged, darker WHIRL: many small puffs on BeautyDustArms log-spiral
	// arms (BeautyDustSpiralTurns turns from the core out to BeautyDustRadiiMax),
	// jittered by BeautyDustJitterRadii, their centres within BeautyDustTopM of
	// the ground; a few debris puffs up the funnel's foot.
	constexpr int32 BeautyDustPuffs = 64;
	constexpr int32 BeautyDustArms = 3;
	constexpr double BeautyDustSpiralTurns = 0.75;
	constexpr double BeautyDustJitterRadii = 0.18;
	constexpr double BeautyDustRadiiMin = 0.15;
	constexpr double BeautyDustRadiiMax = 1.3;
	constexpr double BeautyDustSizeMinM = 22.0;
	constexpr double BeautyDustSizeMaxM = 70.0;
	constexpr double BeautyDustTopM = 35.0;
	constexpr double BeautyDustOpacityMin = 0.35;
	constexpr double BeautyDustOpacityMax = 0.70;
	constexpr int32 BeautyDebrisPuffs = 10;
	constexpr double BeautyDebrisRadiiMin = 0.2;
	constexpr double BeautyDebrisRadiiMax = 0.5;
	constexpr double BeautyDebrisShareMin = 0.02;
	constexpr double BeautyDebrisShareMax = 0.06;
	constexpr double BeautyDebrisSizeMinM = 18.0;
	constexpr double BeautyDebrisSizeMaxM = 40.0;
	constexpr int32 BeautyScudPuffs = 28;
	constexpr double BeautyScudRadiiMin = 1.6;
	constexpr double BeautyScudRadiiMax = 5.0;
	constexpr double BeautyScudBandM = 40.0;
	constexpr double BeautyScudSizeMinM = 120.0;
	constexpr double BeautyScudSizeMaxM = 260.0;
	constexpr double BeautyScudOpacityMin = 0.50;
	constexpr double BeautyScudOpacityMax = 0.85;
	// The dust cloud spins at the Rankine exterior rate at this radius
	// (omega / radii^2, weather_look.wall_cloud_omega_scale's law).
	constexpr double BeautyDustSpinRadii = 1.0;
	constexpr float BeautyDustColourR = 0.15f;
	constexpr float BeautyDustColourG = 0.125f;
	constexpr float BeautyDustColourB = 0.10f;
	// The sheath's colour (M_TornadoFunnelSoft's FunnelColour): the funnel's grey.
	constexpr float BeautySheathColourR = 0.24f;
	constexpr float BeautySheathColourG = 0.245f;
	constexpr float BeautySheathColourB = 0.26f;
	constexpr float BeautyScudColourR = 0.09f;
	constexpr float BeautyScudColourG = 0.09f;
	constexpr float BeautyScudColourB = 0.10f;
	constexpr int32 BeautyPuffSeedSalt = 0x70A2D0;

	const TCHAR* const TornadoPuffPath = TEXT("/Game/FlightSim/M_TornadoPuff.M_TornadoPuff");
	const TCHAR* const TornadoFunnelSoftPath = TEXT("/Game/FlightSim/M_TornadoFunnelSoft.M_TornadoFunnelSoft");

	double TornadoBeautySmooth01(double X)
	{
		const double T = FMath::Clamp(X, 0.0, 1.0);
		return T * T * (3.0 - 2.0 * T);
	}

	// Seeded multi-octave raggedness of a ring's radius at angle A and height
	// share F (deterministic trigonometry, like Build's).
	double TornadoBeautyRagged(double A, double F, double Phase)
	{
		return 0.070 * FMath::Sin(3.0 * A + 7.0 * F + Phase)
		     + 0.045 * FMath::Sin(5.0 * A - 11.0 * F)
		     + 0.030 * FMath::Sin(11.0 * A + 23.0 * F + 2.0 * Phase)
		     + 0.020 * FMath::Sin(17.0 * A - 37.0 * F + 0.5 * Phase);
	}

	// One smooth closed mesh of rings: positions relative to the axis point,
	// UV0 = (coverage, height share), normals averaged from the faces and
	// turned away from each vertex's reference point (the ring's own centre).
	struct FTornadoBeautyRingMesh
	{
		int32 Segments = 0;
		TArray<FVector> Vertices;
		TArray<FVector> References;
		TArray<FVector2D> UV0;
		TArray<int32> Triangles;

		void Stitch(int32 RingA, int32 RingB)
		{
			for (int32 Segment = 0; Segment < Segments; ++Segment)
			{
				const int32 A = RingA * Segments + Segment;
				const int32 B = RingA * Segments + (Segment + 1) % Segments;
				const int32 C = RingB * Segments + Segment;
				const int32 D = RingB * Segments + (Segment + 1) % Segments;
				Triangles.Append({A, B, C, B, D, C});
			}
		}

		// Both windings (reads from every side, as Build's markers), with
		// normals from the first winding only.
		void Finish(TArray<FVector>& OutNormals, TArray<int32>& OutTriangles) const
		{
			OutNormals.Init(FVector::ZeroVector, Vertices.Num());
			for (int32 T = 0; T + 2 < Triangles.Num(); T += 3)
			{
				const int32 A = Triangles[T], B = Triangles[T + 1], C = Triangles[T + 2];
				const FVector Face = FVector::CrossProduct(Vertices[B] - Vertices[A],
				                                           Vertices[C] - Vertices[A]);
				OutNormals[A] += Face; OutNormals[B] += Face; OutNormals[C] += Face;
			}
			for (int32 V = 0; V < Vertices.Num(); ++V)
			{
				FVector N = OutNormals[V].GetSafeNormal();
				if (FVector::DotProduct(N, Vertices[V] - References[V]) < 0.0)
				{
					N = -N;
				}
				OutNormals[V] = N;
			}
			OutTriangles = Triangles;
			for (int32 T = 0; T + 2 < Triangles.Num(); T += 3)
			{
				OutTriangles.Append({Triangles[T], Triangles[T + 2], Triangles[T + 1]});
			}
		}
	};
}

bool FFlightSimScenarioWorld::BuildBeautyTornado(const FFlightSimScenarioCard& Card,
                                                 TArray<AActor*>& BeautyOnlyActors,
                                                 const TSharedPtr<FJsonObject>& Record)
{
	using namespace FlightSimTornadoBeautyLocal;
	if (!Card.bTornado || TornadoFunnel == nullptr || TornadoWallCloud == nullptr
		|| GeoReferencing == nullptr || World == nullptr)
	{
		if (Record.IsValid())
		{
			Record->SetStringField(TEXT("tornado_beauty"),
				TEXT("not drawn: no tornado markers in this world"));
		}
		return false;
	}
	UProceduralMeshComponent* FunnelMesh =
		Cast<UProceduralMeshComponent>(TornadoFunnel->GetRootComponent());
	UProceduralMeshComponent* WallMesh =
		Cast<UProceduralMeshComponent>(TornadoWallCloud->GetRootComponent());
	if (FunnelMesh == nullptr || WallMesh == nullptr)
	{
		if (Record.IsValid())
		{
			Record->SetStringField(TEXT("tornado_beauty"),
				TEXT("not drawn: the markers carry no procedural mesh"));
		}
		return false;
	}

	const double RCore = Card.TornadoRCoreMetres;
	const double TopM = Card.TornadoTopMetres;
	const double Phase = TornadoShapePhase;
	const double FunnelTopMetres = TornadoBeautyFunnelTopShare * TopM;
	const double WallTopMetres = TornadoBeautyWallTopShare * TopM;
	const double WallDepthMetres = WallTopMetres - FunnelTopMetres;
	const FVector Centre = TornadoCentreProjected;
	const double Ground = TornadoGroundMetres;
	auto ToEngine = [&](double X, double Y, double Z) -> FVector
	{
		FVector Out;
		GeoReferencing->ProjectedToEngine(
			FVector(Centre.X + X, Centre.Y + Y, Ground + Z), Out);
		return Out - TornadoAxisEngine;
	};
	// Adds one ring: Radius x (1 + RaggedAmp x Ragged) about (OffX, OffY) at
	// ElevationM, every vertex with (Coverage, HeightShare) and the reference
	// point RefZ metres up the ring's own centre line.
	auto AddRing = [&](FTornadoBeautyRingMesh& Mesh, double Radius, double ElevationM, double OffX,
	                   double OffY, double RaggedAmp, double Coverage, double HeightShare,
	                   double RefZ)
	{
		const FVector Reference = ToEngine(OffX, OffY, RefZ);
		for (int32 Segment = 0; Segment < Mesh.Segments; ++Segment)
		{
			const double A = 2.0 * PI * Segment / Mesh.Segments;
			const double R = Radius * (1.0 + RaggedAmp * TornadoBeautyRagged(A, HeightShare, Phase));
			Mesh.Vertices.Add(ToEngine(OffX + R * FMath::Cos(A), OffY + R * FMath::Sin(A),
			                         ElevationM));
			Mesh.References.Add(Reference);
			Mesh.UV0.Add(FVector2D(Coverage, HeightShare));
		}
	};

	// -- the funnel: the core (section 0, masked, depth-writing) and the sheath
	// (section 1, translucent M_TornadoFunnelSoft: the soft condensation edge) --
	FTornadoBeautyRingMesh FunnelCore;
	FTornadoBeautyRingMesh FunnelSheath;
	FunnelCore.Segments = BeautyFunnelSegments;
	FunnelSheath.Segments = BeautyFunnelSegments;
	for (int32 Shell = 0; Shell < 2; ++Shell)
	{
		FTornadoBeautyRingMesh& Funnel = Shell == 0 ? FunnelCore : FunnelSheath;
		const int32 First = 0;
		for (int32 Ring = 0; Ring < BeautyFunnelRings; ++Ring)
		{
			const double F = static_cast<double>(Ring) / (BeautyFunnelRings - 1);
			double Radius = RCore * (BeautyFunnelBaseRadii
				+ (TornadoBeautyFunnelTopRadii - BeautyFunnelBaseRadii)
				  * FMath::Pow(F, BeautyFunnelTaperPower));
			double Coverage = BeautyFunnelGroundCoverage
				+ (1.0 - BeautyFunnelGroundCoverage) * TornadoBeautySmooth01(F / BeautyFunnelContactShare);
			if (Shell == 1)
			{
				Radius = BeautySheathScale * Radius + BeautySheathPadRadii * RCore;
				Coverage *= BeautySheathCoverage;
			}
			// Build's sinuous axis (0.35 RCore x F) plus a gentle S-bend.
			const double Wobble = 0.35 * RCore * F;
			const double OffX = Wobble * FMath::Sin(2.2 * PI * F * TornadoBeautyFunnelTopShare + Phase)
				+ BeautyFunnelBendRadii * RCore * FMath::Sin(3.0 * PI * F + Phase);
			const double OffY = Wobble * FMath::Cos(1.7 * PI * F * TornadoBeautyFunnelTopShare + Phase * 0.7)
				+ BeautyFunnelBendRadii * RCore * FMath::Cos(2.0 * PI * F + 0.5 * Phase);
			const double Elevation = F * FunnelTopMetres;
			AddRing(Funnel, Radius, Elevation, OffX, OffY, 1.0, Coverage, F, Elevation);
			if (Ring > 0)
			{
				Funnel.Stitch(First + Ring - 1, First + Ring);
			}
		}
	}

	// -- the wall cloud's underside, rim and top ------------------------------
	FTornadoBeautyRingMesh Wall;
	Wall.Segments = BeautyWallSegments;
	const double WallMidMetres = FunnelTopMetres + 0.5 * WallDepthMetres;
	for (int32 Row = 0; Row < BeautyWallRows; ++Row)
	{
		const double Share = BeautyWallProfile[Row][0];
		const double RaggedAmp = BeautyWallProfile[Row][3];
		const double Lump = BeautyWallLumpShare * WallDepthMetres * RaggedAmp
			* FMath::Sin(4.0 * Share * PI + Phase);
		AddRing(Wall, BeautyWallProfile[Row][1] * RCore,
		        FunnelTopMetres + Share * WallDepthMetres + Lump, 0.0, 0.0,
		        RaggedAmp, BeautyWallProfile[Row][2], Share, WallMidMetres);
		if (Row > 0)
		{
			Wall.Stitch(Row - 1, Row);
		}
	}

	auto Replace = [](UProceduralMeshComponent* Mesh, int32 Section, const FTornadoBeautyRingMesh& Ring)
	{
		TArray<FVector> Normals;
		TArray<int32> Triangles;
		Ring.Finish(Normals, Triangles);
		if (Section == 0)
		{
			Mesh->ClearAllMeshSections();
		}
		// No vertex colours (NEXT.md gotcha 26): the material reads UV0 only.
		Mesh->CreateMeshSection_LinearColor(Section, Ring.Vertices, Triangles, Normals, Ring.UV0,
		                                    TArray<FLinearColor>(), TArray<FProcMeshTangent>(),
		                                    false);
		return Triangles.Num() / 3;
	};
	int32 FunnelTriangles = Replace(FunnelMesh, 0, FunnelCore);
	const int32 WallTriangles = Replace(WallMesh, 0, Wall);
	// The sheath: drawn only when its translucent material loads (never the
	// opaque default: a second opaque shell would fatten the silhouette).
	UMaterialInterface* SoftMaterial = LoadObject<UMaterialInterface>(nullptr, TornadoFunnelSoftPath);
	FString SheathNote = TEXT("not drawn: M_TornadoFunnelSoft did not load (run scripts/ue_create_materials.py)");
	if (SoftMaterial != nullptr)
	{
		FunnelTriangles += Replace(FunnelMesh, 1, FunnelSheath);
		UMaterialInstanceDynamic* Soft = UMaterialInstanceDynamic::Create(SoftMaterial, FunnelMesh);
		Soft->SetVectorParameterValue(FName(TEXT("FunnelColour")),
			FLinearColor(BeautySheathColourR, BeautySheathColourG, BeautySheathColourB, 1.0f));
		FunnelMesh->SetMaterial(1, Soft);
		SheathNote = TEXT("drawn: translucent, no depth (the labels see the core only)");
	}

	// -- the puffs (beauty-only, translucent) ---------------------------------
	UMaterialInterface* PuffMaterial = LoadObject<UMaterialInterface>(nullptr, TornadoPuffPath);
	FRandomStream Stream(static_cast<int32>((Card.TurbulenceSeed ^ BeautyPuffSeedSalt) & 0x7FFFFFFF));
	int32 PuffCount = 0;
	auto SpawnPuffActor = [&](const TCHAR* Name) -> AActor*
	{
		AActor* Actor = World->SpawnActor<AActor>();
		USceneComponent* Root = NewObject<USceneComponent>(Actor, Name);
		Root->SetMobility(EComponentMobility::Movable);
		Actor->SetRootComponent(Root);
		Root->RegisterComponent();
		Actor->SetActorLocation(TornadoAxisEngine);
		BeautyOnlyActors.Add(Actor);
		return Actor;
	};
	auto AddPuff = [&](AActor* Actor, const FString& Name, double RadiusM, double ElevationM,
	                   double SizeM, double Opacity, const FLinearColor& Colour, double Angle = -1.0)
	{
		const double A = Angle >= 0.0 ? Angle : Stream.FRandRange(0.0, 2.0 * PI);
		UMaterialBillboardComponent* Puff = NewObject<UMaterialBillboardComponent>(Actor, *Name);
		Puff->SetupAttachment(Actor->GetRootComponent());
		Puff->SetMobility(EComponentMobility::Movable);
		Puff->SetRelativeLocation(ToEngine(RadiusM * FMath::Cos(A), RadiusM * FMath::Sin(A), ElevationM));
		Puff->SetCastShadow(false);
		Puff->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(PuffMaterial, Puff);
		const float Shade = static_cast<float>(Stream.FRandRange(0.85, 1.1));
		Instance->SetVectorParameterValue(FName(TEXT("PuffColour")),
			FLinearColor(Colour.R * Shade, Colour.G * Shade, Colour.B * Shade, 1.0f));
		Instance->SetScalarParameterValue(FName(TEXT("PuffOpacity")), static_cast<float>(Opacity));
		Instance->SetScalarParameterValue(FName(TEXT("PuffTile")), static_cast<float>(PuffCount % 4));
		Instance->SetScalarParameterValue(FName(TEXT("PuffSpin")),
		                                  static_cast<float>(Stream.FRandRange(0.0, 2.0 * PI)));
		const float SizeCm = static_cast<float>(SizeM * 100.0);
		Puff->AddElement(Instance, nullptr, false, SizeCm, SizeCm, nullptr);
		Puff->RegisterComponent();
		++PuffCount;
	};
	FString PuffNote = TEXT("drawn");
	if (PuffMaterial == nullptr)
	{
		PuffNote = TEXT("not drawn: M_TornadoPuff did not load (run scripts/ue_create_materials.py)");
	}
	else
	{
		TornadoDust = SpawnPuffActor(TEXT("TornadoDust"));
		TornadoDustOmegaDegPerSec = TornadoOmegaDegPerSec / (BeautyDustSpinRadii * BeautyDustSpinRadii);
		const FLinearColor Dust(BeautyDustColourR, BeautyDustColourG, BeautyDustColourB, 1.0f);
		for (int32 I = 0; I < BeautyDustPuffs; ++I)
		{
			// Along arm (I % arms), U from the core out; a log-spiral: the angle
			// grows with ln(radius), so the arms trail like inflow bands.
			const double U = (static_cast<double>(I / BeautyDustArms) + Stream.FRand())
				/ FMath::CeilToDouble(static_cast<double>(BeautyDustPuffs) / BeautyDustArms);
			const double Radii = BeautyDustRadiiMin * FMath::Pow(BeautyDustRadiiMax / BeautyDustRadiiMin, U);
			const double Angle = FMath::Fmod(2.0 * PI * (static_cast<double>(I % BeautyDustArms) / BeautyDustArms
				+ BeautyDustSpiralTurns * U) + Phase + 4.0 * PI, 2.0 * PI);
			const double RadiusM = RCore * FMath::Max(0.05, Radii + Stream.FRandRange(-BeautyDustJitterRadii,
			                                                                          BeautyDustJitterRadii));
			// Bigger puffs near the core (the debris column), smaller at the arms' ends.
			const double SizeM = FMath::Lerp(BeautyDustSizeMaxM, BeautyDustSizeMinM,
			                                 0.6 * U + 0.4 * Stream.FRand());
			const double ElevationM = 0.25 * SizeM + Stream.FRand() * BeautyDustTopM * (1.0 - 0.6 * U);
			AddPuff(TornadoDust, FString::Printf(TEXT("TornadoDustPuff_%d"), I), RadiusM, ElevationM,
			        SizeM, FMath::Lerp(BeautyDustOpacityMin, BeautyDustOpacityMax, Stream.FRand()), Dust,
			        Angle);
		}
		for (int32 I = 0; I < BeautyDebrisPuffs; ++I)
		{
			const double RadiusM = RCore * Stream.FRandRange(BeautyDebrisRadiiMin, BeautyDebrisRadiiMax);
			const double ElevationM = TopM * Stream.FRandRange(BeautyDebrisShareMin, BeautyDebrisShareMax);
			AddPuff(TornadoDust, FString::Printf(TEXT("TornadoDebrisPuff_%d"), I), RadiusM, ElevationM,
			        Stream.FRandRange(BeautyDebrisSizeMinM, BeautyDebrisSizeMaxM),
			        0.7 * FMath::Lerp(BeautyDustOpacityMin, BeautyDustOpacityMax, Stream.FRand()), Dust);
		}
		TornadoScud = SpawnPuffActor(TEXT("TornadoScud"));
		TornadoScudOmegaDegPerSec = TornadoWallOmegaDegPerSec;
		const FLinearColor Scud(BeautyScudColourR, BeautyScudColourG, BeautyScudColourB, 1.0f);
		for (int32 I = 0; I < BeautyScudPuffs; ++I)
		{
			const double RadiusM = RCore * Stream.FRandRange(BeautyScudRadiiMin, BeautyScudRadiiMax);
			const double ElevationM = FunnelTopMetres + Stream.FRandRange(-BeautyScudBandM, BeautyScudBandM);
			AddPuff(TornadoScud, FString::Printf(TEXT("TornadoScudPuff_%d"), I), RadiusM, ElevationM,
			        Stream.FRandRange(BeautyScudSizeMinM, BeautyScudSizeMaxM),
			        FMath::Lerp(BeautyScudOpacityMin, BeautyScudOpacityMax, Stream.FRand()), Scud);
		}
	}

	if (Record.IsValid())
	{
		TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
		Row->SetNumberField(TEXT("funnel_triangles"), FunnelTriangles);
		Row->SetStringField(TEXT("funnel_sheath"), SheathNote);
		Row->SetNumberField(TEXT("wall_cloud_triangles"), WallTriangles);
		Row->SetStringField(TEXT("puffs"), PuffNote);
		Row->SetNumberField(TEXT("puff_count"), PuffCount);
		Row->SetNumberField(TEXT("dust_spin_deg_s"), TornadoDustOmegaDegPerSec);
		Row->SetNumberField(TEXT("scud_spin_deg_s"), TornadoScudOmegaDegPerSec);
		Row->SetStringField(TEXT("labels"),
			TEXT("funnel core and wall cloud depth-writing (BLEND_MASKED, plain clip: the labels see the "
			     "beauty's silhouette); the puffs translucent and in BeautyOnlyActors, as every cloud"));
		Row->SetStringField(TEXT("not_claimed"),
			TEXT("a visual marker of the modelled core, not condensation or debris physics; UNCALIBRATED"));
		Record->SetObjectField(TEXT("tornado_beauty"), Row);
	}
	UE_LOG(LogTemp, Display,
	       TEXT("tornado beauty: funnel %d and wall cloud %d triangles rebuilt; %d puffs (%s)"),
	       FunnelTriangles, WallTriangles, PuffCount, *PuffNote);
	return true;
}
