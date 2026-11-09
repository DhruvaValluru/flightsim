// Humidity-gated condensation (FlightSimCondensation.h says what, why and
// what it may not touch). Visual overhaul, module "condensation-solver".
// BEAUTY ONLY.
//
// The physics is core/scene/condensation.py, line for line: the same sites,
// the same formulas, the same constant names and defaults (pinned by
// tests/test_condensation.py). UNCALIBRATED: every constant below, the 0.87
// Lamb-Oseen factor and the compressible Cp form are engineering
// approximations, set by the probe renders docs/visual/PROBE_LOG.md
// "## condensation-solver" names.
//
// UNCOMPILED when written: this Mac cannot build UE 5.7. Every engine symbol
// below was grepped in the UE 5.7.4 headers (scripts/check_bridge_api.sh,
// "CONDENSATION (condensation-solver)" block).

#include "FlightSimCondensation.h"

#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/Parse.h"
#include "ProceduralMeshComponent.h"
#include "StaticMeshResources.h"

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimCondensation, Log, All);

namespace
{
	// Names are file-unique (unity builds merge anonymous namespaces).
	struct FCondensationDefault
	{
		const TCHAR* Name;
		double Value;
	};
	// core/scene/condensation.py CONDENSATION_DEFAULTS, same order.
	const FCondensationDefault CondensationDefaults[] = {
		{TEXT("CpMinPerCL"), 1.2},
		{TEXT("CoreRadiusSpanFraction"), 0.03},
		{TEXT("LexAlphaOnsetDeg"), 12.0},
		{TEXT("ConeLocalMach"), 1.15},
		{TEXT("ConeMachMin"), 0.85},
		{TEXT("ConeMachMax"), 1.05},
		{TEXT("OpacityPerGkg"), 0.6},
		{TEXT("LifetimeS"), 1.2},
		{TEXT("VisibleMinGkg"), 0.05},
		{TEXT("OnsetCoolingK"), 6.0},
		{TEXT("SheetCpMinAtZeroLift"), 0.3},
		{TEXT("LexCpPerDeg"), 0.12},
		{TEXT("LexEnabled"), 0.0},
		{TEXT("LexAftOfNoseM"), 6.0},
		{TEXT("LexSpanM"), 1.2},
		{TEXT("LexUpM"), 0.2},
		{TEXT("LexLengthM"), 6.0},
		{TEXT("ConeLengthBodyFraction"), 0.18},
		{TEXT("SheetSpanStartFraction"), 0.35},
		{TEXT("SheetSpanEndFraction"), 0.9},
		{TEXT("SheetChordFraction"), 0.55},
		{TEXT("TipStartWidthM"), 0.3},
		{TEXT("TipSpreadMPerS"), 1.2},
	};
	const TCHAR* const CondensationGroup = TEXT("condensation");
	// scripts/aircraft_look.py MASTER_ROOT + FX_MASTERS; FX_PARAMETERS.
	const TCHAR* const CondensationMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftCondensation.M_AircraftCondensation");
	const TCHAR* const CondensationParamOpacity = TEXT("Opacity");
	const TCHAR* const CondensationParamShape = TEXT("Shape");
	// assets/shaders/aircraft/condensation_opacity.hlsl Shape codes.
	constexpr double CondensationShapeRibbon = 0.0;
	constexpr double CondensationShapeSheet = 1.0;
	constexpr double CondensationShapeCone = 2.0;
	constexpr double CondensationShapeTube = 3.0;

	// The physics constants (condensation.py).
	constexpr double CondensationLambOseen = 0.87;
	constexpr double CondensationPoisson = 0.2857;
	// R_dry / R_water from JSBSim's molar masses (atmosphere.py R_DRY / R_WATER).
	constexpr double CondensationEpsilon = 18.016 / 28.9645;
	constexpr double CondensationMinPressureRatio = 0.05;
	// JSBSim units -> SI (condensation.py state_from_fdm).
	constexpr double CondensationPaPerPsf = 47.880258980;
	constexpr double CondensationKgm3PerSlugft3 = 515.378818;
	constexpr double CondensationMPerFt = 0.3048;
	constexpr double CondensationMpsPerKt = 0.514444;
	constexpr double CondensationNPerLbf = 4.448221615;
	constexpr double CondensationKelvinPerRankine = 1.0 / 1.8;
	constexpr double CondensationCmPerM = 100.0;
	constexpr int32 CondensationSlices = 40;
	constexpr int32 CondensationSheetStations = 6;
	constexpr int32 CondensationTubeRings = 10;
	constexpr int32 CondensationTubeSides = 20;

	// JSBSim's Magnus form (FGStandardAtmosphere, atmosphere.py), pascals.
	double CondensationSaturationPa(double TK)
	{
		const double C = TK - 273.15;
		return 611.2 * FMath::Exp(17.62 * C / (243.12 + C));
	}

	double CondensationMixing(double EPa, double PPa)
	{
		return EPa >= PPa ? 1.0e30 : CondensationEpsilon * EPa / (PPa - EPa);
	}

	// dq = q_v(RH, T, p) - q_sat(T_l, p_l), g/kg.
	double CondensationDqGkg(double RhPct, double TK, double PPa, double TLocalK, double PLocalPa)
	{
		const double Qv = CondensationMixing(FMath::Max(RhPct, 0.0) / 100.0 * CondensationSaturationPa(TK), PPa);
		const double Qs = CondensationMixing(CondensationSaturationPa(TLocalK), PLocalPa);
		return 1000.0 * (Qv - Qs);
	}

	TSharedPtr<FJsonValue> CondensationNumberOrNull(bool bValid, double Value)
	{
		return bValid ? StaticCastSharedRef<FJsonValue>(MakeShared<FJsonValueNumber>(Value))
		              : StaticCastSharedRef<FJsonValue>(MakeShared<FJsonValueNull>());
	}

	TSharedPtr<FJsonValue> CondensationVectorValue(const FVector& V)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		Values.Add(MakeShared<FJsonValueNumber>(V.X));
		Values.Add(MakeShared<FJsonValueNumber>(V.Y));
		Values.Add(MakeShared<FJsonValueNumber>(V.Z));
		return MakeShared<FJsonValueArray>(Values);
	}

	UProceduralMeshComponent* CondensationMesh(AActor* Owner, const TCHAR* Name)
	{
		UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(Owner, Name);
		Owner->SetRootComponent(Mesh);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		return Mesh;
	}

	// An open tube along actor -X from Start (radius R0, UV.x 0) to LengthCm
	// aft (radius R1, UV.x 1); UV.y runs around it.
	void CondensationTube(TArray<FVector>& V, TArray<int32>& T, TArray<FVector>& N, TArray<FVector2D>& UV,
	                      const FVector& Start, double R0, double R1, double LengthCm)
	{
		const int32 Base = V.Num();
		for (int32 Ring = 0; Ring <= CondensationTubeRings; ++Ring)
		{
			const double F = static_cast<double>(Ring) / CondensationTubeRings;
			const double Radius = FMath::Lerp(R0, R1, F);
			for (int32 Side = 0; Side <= CondensationTubeSides; ++Side)
			{
				const double A = 2.0 * UE_DOUBLE_PI * Side / CondensationTubeSides;
				const FVector Radial(0.0, FMath::Cos(A), FMath::Sin(A));
				V.Add(Start + FVector(-F * LengthCm, 0.0, 0.0) + Radial * Radius);
				N.Add(Radial);
				UV.Add(FVector2D(F, static_cast<double>(Side) / CondensationTubeSides));
			}
		}
		const int32 Stride = CondensationTubeSides + 1;
		for (int32 Ring = 0; Ring < CondensationTubeRings; ++Ring)
		{
			for (int32 Side = 0; Side < CondensationTubeSides; ++Side)
			{
				const int32 A = Base + Ring * Stride + Side;
				const int32 B = A + Stride;
				T.Append({A, B, A + 1, A + 1, B, B + 1});
			}
		}
	}
}

void FFlightSimCondensationHumidity::ParseParams(const FString& Params)
{
	double Pct = 0.0;
	if (FParse::Value(*Params, TEXT("humidity-pct="), Pct) && FMath::IsFinite(Pct))
	{
		bParamStated = true;
		ParamPct = FMath::Clamp(Pct, 0.0, 100.0);
	}
}

double FFlightSimCondensation::Constant(const TCHAR* Name) const
{
	const double* Found = Values.Find(Name);
	return Found != nullptr ? *Found : 0.0;
}

bool FFlightSimCondensation::Build(UWorld* World, AActor* InAircraft, const TSharedPtr<FJsonObject>& LookConstants,
                                   const FFlightSimCondensationHumidity& InHumidity, bool bInDraw,
                                   TArray<AActor*>& BeautyOnlyActors, FString& Error)
{
	Aircraft = InAircraft;
	Humidity = InHumidity;
	bDraw = bInDraw;

	// -- the constants: the twin's defaults, then look_manifest.json's
	// constants.condensation (scripts/aircraft_look.py) where present.
	const TSharedPtr<FJsonObject>* Group = nullptr;
	const bool bGroup = LookConstants.IsValid() && LookConstants->TryGetObjectField(CondensationGroup, Group)
		&& Group != nullptr;
	TSharedPtr<FJsonObject> ConstantsRow = MakeShared<FJsonObject>();
	for (const FCondensationDefault& Default : CondensationDefaults)
	{
		double Value = Default.Value;
		const TSharedPtr<FJsonObject>* Entry = nullptr;
		if (bGroup && (*Group)->TryGetObjectField(Default.Name, Entry) && Entry != nullptr)
		{
			(*Entry)->TryGetNumberField(TEXT("value"), Value);
		}
		if (!FMath::IsFinite(Value))
		{
			Error = FString::Printf(TEXT("aircraft_look.condensation: constant %s is not a finite number; ")
				TEXT("re-run python scripts/aircraft_look.py <NAME>"), Default.Name);
			return false;
		}
		Values.Add(Default.Name, Value);
		ConstantsRow->SetNumberField(Default.Name, Value);
	}
	if (Constant(TEXT("ConeMachMin")) >= Constant(TEXT("ConeMachMax")) ||
	    Constant(TEXT("CoreRadiusSpanFraction")) <= 0.0 || Constant(TEXT("OpacityPerGkg")) < 0.0 ||
	    Constant(TEXT("LifetimeS")) <= 0.0 ||
	    Constant(TEXT("SheetSpanStartFraction")) >= Constant(TEXT("SheetSpanEndFraction")))
	{
		Error = TEXT("aircraft_look.condensation: the condensation constants contradict each other ")
			TEXT("(need ConeMachMin < ConeMachMax, CoreRadiusSpanFraction > 0, OpacityPerGkg >= 0, ")
			TEXT("LifetimeS > 0, SheetSpanStartFraction < SheetSpanEndFraction)");
		return false;
	}

	Out = MakeShared<FJsonObject>();
	Out->SetStringField(TEXT("model"), TEXT("isentropic+Magnus"));
	Out->SetStringField(TEXT("formula"), TEXT("T_l = T (p_l/p)^0.2857; dq = q_v(RH,T,p) - q_sat(T_l,p_l); ")
		TEXT("opacity = clamp(OpacityPerGkg x (q_v - q_sat(T_l + OnsetCoolingK, p_l))), 0 below VisibleMinGkg. ")
		TEXT("tip: Gamma = Nz W/(rho V b pi/4), dp = 0.87 rho Gamma^2/(4 pi^2 rc^2), rc = CoreRadiusSpanFraction b; ")
		TEXT("sheet: CL = Nz W/(qbar S), Cp_min = -(SheetCpMinAtZeroLift + CpMinPerCL CL), p_l = p(1 + 0.7 M^2 Cp_min); ")
		TEXT("lex: alpha > LexAlphaOnsetDeg, Cp = -LexCpPerDeg (alpha - onset); ")
		TEXT("cone: ConeMachMin <= M <= ConeMachMax, T_l/T = (1+0.2M^2)/(1+0.2 ConeLocalMach^2), ")
		TEXT("p_l/p = (T_l/T)^3.5, ending at the recompression shock. Python twin core/scene/condensation.py"));
	Out->SetObjectField(TEXT("constants"), ConstantsRow);
	Out->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: every constant, the 0.87 Lamb-Oseen factor ")
		TEXT("and the compressible Cp form are engineering approximations; set by probe render on the render ")
		TEXT("machine (a humid low pass at M 0.95; a 5 g pull-up in the forest rain scene)"));
	Out->SetStringField(TEXT("label_convention"),
		TEXT("translucent media: not in mask, class or depth (trail convention)"));
	Out->SetBoolField(TEXT("pixel_moving"), false);
	Out->SetStringField(TEXT("humidity"), Humidity.bParamStated
		? FString::Printf(TEXT("-humidity-pct=%.1f (beauty-only override; the physics never sees it)"), Humidity.ParamPct)
		: Humidity.bCardStated ? FString(TEXT("atmosphere/RH (the card states a dew point)"))
		: FString(TEXT("unavailable: the card states no dew point -- the Nz fallback (vapour.MinNz) runs")));
	Out->SetBoolField(TEXT("fallback_used"), false);
	Out->SetArrayField(TEXT("per_frame"), PerFrame);

	if (World == nullptr || Aircraft == nullptr)
	{
		Out->SetStringField(TEXT("sites"), TEXT("absent: no aircraft actor"));
		bBuilt = true;
		return true;
	}

	// -- the sites, from the airframe's own vertices (as the lamps are placed
	// from the mesh's extremes): LOD 0 positions, CPU-resident in an editor
	// build (StaticMesh.cpp: bNeedsCPUAccess = !RequiresCookedData()).
	TArray<FVector> Vertices;
	{
		const FTransform ActorFrame = Aircraft->GetActorTransform();
		TInlineComponentArray<UStaticMeshComponent*> Parts;
		Aircraft->GetComponents(Parts);
		for (UStaticMeshComponent* Part : Parts)
		{
			const UStaticMesh* Mesh = Part != nullptr ? Part->GetStaticMesh().Get() : nullptr;
			const FStaticMeshRenderData* RenderData = Mesh != nullptr ? Mesh->GetRenderData() : nullptr;
			if (RenderData == nullptr || RenderData->LODResources.Num() == 0)
			{
				continue;
			}
			const FPositionVertexBuffer& Positions = RenderData->LODResources[0].VertexBuffers.PositionVertexBuffer;
			if (Positions.GetVertexData() == nullptr)
			{
				continue;
			}
			const FTransform ToActor = Part->GetComponentTransform().GetRelativeTransform(ActorFrame);
			for (uint32 Index = 0; Index < Positions.GetNumVertices(); ++Index)
			{
				Vertices.Add(ToActor.TransformPosition(FVector(Positions.VertexPosition(Index))));
			}
		}
	}
	PlaceSites(Vertices);

	TSharedPtr<FJsonObject> Sites = MakeShared<FJsonObject>();
	Sites->SetNumberField(TEXT("vertices_read"), Vertices.Num());
	if (bSitesPlaced)
	{
		Sites->SetField(TEXT("tip_left_actor_cm"), CondensationVectorValue(TipActorCm[0]));
		Sites->SetField(TEXT("tip_right_actor_cm"), CondensationVectorValue(TipActorCm[1]));
		Sites->SetNumberField(TEXT("cone_collar_station_cm"), CollarStationCm);
		Sites->SetNumberField(TEXT("cone_collar_radius_cm"), CollarRadiusCm);
		Sites->SetNumberField(TEXT("sheet_stations"), SheetStations.Num());
		Sites->SetBoolField(TEXT("lex"), Constant(TEXT("LexEnabled")) >= 0.5);
		Sites->SetStringField(TEXT("placement"), TEXT("tips at the +/-Y vertex extremes; the cone collar at the ")
			TEXT("X slice of largest (Y span x Z span), radius half that slice's Y span, the shock ")
			TEXT("ConeLengthBodyFraction x body length aft; the sheet over the wing chord measured in span bands ")
			TEXT("(the cluster of largest X extent), at the 90th-percentile Z; the LEX at the look config's offsets"));
	}
	else
	{
		Sites->SetStringField(TEXT("placement"), TEXT("absent: no CPU-readable mesh vertices (nothing drawn; ")
			TEXT("the tip vortices fall to the wingtip vapour trails)"));
	}
	Out->SetObjectField(TEXT("sites"), Sites);

	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, CondensationMaterialPath);
	Out->SetStringField(TEXT("material"), Material != nullptr ? CondensationMaterialPath
		: TEXT("absent (run scripts/ue_aircraft_master_materials.py); nothing drawn"));
	if (bDraw && bSitesPlaced && Material != nullptr)
	{
		BuildAttachedSections(World, Material);
		if (Attached != nullptr)
		{
			BeautyOnlyActors.Add(Attached);
		}
		// The tip vortices: world-space ribbons (the trail approach: the
		// cloud stays where the air was), each its own beauty-only actor.
		for (int32 Side = 0; Side < 2; ++Side)
		{
			FTipRibbon Ribbon;
			Ribbon.SourceActorCm = TipActorCm[Side];
			Ribbon.Owner = World->SpawnActor<AActor>();
			if (Ribbon.Owner == nullptr)
			{
				continue;
			}
			Ribbon.Mesh = CondensationMesh(Ribbon.Owner, Side == 0 ? TEXT("TipVortexLeft") : TEXT("TipVortexRight"));
			if (TipMID == nullptr)
			{
				TipMID = SiteInstance(Material, Ribbon.Mesh, CondensationShapeRibbon);
				// Per-sample opacity rides in vertex colour R; the scalar stays 1.
				TipMID->SetScalarParameterValue(FName(CondensationParamOpacity), 1.0f);
			}
			Ribbon.Mesh->SetMaterial(0, TipMID);
			Ribbon.Mesh->RegisterComponent();
			BeautyOnlyActors.Add(Ribbon.Owner);
			Tips.Add(Ribbon);
		}
		bTipsDrawn = Tips.Num() == 2;
	}
	Out->SetBoolField(TEXT("drawn"), Attached != nullptr || bTipsDrawn);
	bBuilt = true;
	UE_LOG(LogFlightSimCondensation, Display, TEXT("condensation: %d vertices, sites %s, %d tip ribbon(s), material %s"),
	       Vertices.Num(), bSitesPlaced ? TEXT("placed") : TEXT("absent"), Tips.Num(),
	       Material != nullptr ? TEXT("present") : TEXT("absent"));
	return true;
}

void FFlightSimCondensation::PlaceSites(const TArray<FVector>& Vertices)
{
	if (Vertices.Num() < 8)
	{
		return;
	}
	double MinX = TNumericLimits<double>::Max(), MaxX = TNumericLimits<double>::Lowest();
	int32 Left = 0, Right = 0, Nose = 0;
	for (int32 i = 0; i < Vertices.Num(); ++i)
	{
		const FVector& P = Vertices[i];
		MinX = FMath::Min(MinX, P.X);
		if (P.X > MaxX) { MaxX = P.X; Nose = i; }
		if (P.Y < Vertices[Left].Y) { Left = i; }
		if (P.Y > Vertices[Right].Y) { Right = i; }
	}
	BodyLengthCm = MaxX - MinX;
	if (BodyLengthCm <= 1.0 || Vertices[Right].Y - Vertices[Left].Y <= 1.0)
	{
		return;
	}
	TipActorCm[0] = Vertices[Left];
	TipActorCm[1] = Vertices[Right];
	NoseActorCm = Vertices[Nose];

	// The X slices: the station of largest cross-section (Y span x Z span).
	TArray<FVector4> Slices;   // min Y, max Y, min Z, max Z
	Slices.Init(FVector4(TNumericLimits<double>::Max(), TNumericLimits<double>::Lowest(),
	                     TNumericLimits<double>::Max(), TNumericLimits<double>::Lowest()), CondensationSlices);
	for (const FVector& P : Vertices)
	{
		const int32 Bin = FMath::Clamp(static_cast<int32>((P.X - MinX) / BodyLengthCm * CondensationSlices),
		                               0, CondensationSlices - 1);
		FVector4& S = Slices[Bin];
		S.X = FMath::Min(S.X, P.Y); S.Y = FMath::Max(S.Y, P.Y);
		S.Z = FMath::Min(S.Z, P.Z); S.W = FMath::Max(S.W, P.Z);
	}
	int32 Best = -1;
	double BestArea = 0.0;
	for (int32 Bin = 0; Bin < CondensationSlices; ++Bin)
	{
		const FVector4& S = Slices[Bin];
		const double Area = S.Y > S.X ? (S.Y - S.X) * (S.W - S.Z) : 0.0;
		if (Area > BestArea) { BestArea = Area; Best = Bin; }
	}
	if (Best < 0)
	{
		return;
	}
	CollarStationCm = MinX + (Best + 0.5) / CondensationSlices * BodyLengthCm;
	CollarCentreZCm = 0.5 * (Slices[Best].Z + Slices[Best].W);
	CollarRadiusCm = 0.5 * (Slices[Best].Y - Slices[Best].X);

	// The sheet: at each span station (both sides), the chord of the
	// cluster of largest X extent within a thin span band (the wing, not a
	// tailplane behind it), its leading edge and 90th-percentile top Z.
	const double Semi = 0.5 * (Vertices[Right].Y - Vertices[Left].Y);
	const double Band = 0.04 * Semi;
	const double Gap = 0.03 * BodyLengthCm;
	for (int32 Side = 0; Side < 2; ++Side)
	{
		const double Sign = Side == 0 ? -1.0 : 1.0;
		for (int32 Station = 0; Station < CondensationSheetStations; ++Station)
		{
			const double F = FMath::Lerp(Constant(TEXT("SheetSpanStartFraction")), Constant(TEXT("SheetSpanEndFraction")),
			                             static_cast<double>(Station) / (CondensationSheetStations - 1));
			const double Y = F * Semi;
			TArray<FVector2D> InBand;   // (X, Z)
			for (const FVector& P : Vertices)
			{
				if (Sign * P.Y > 0.0 && FMath::Abs(FMath::Abs(P.Y) - Y) < Band)
				{
					InBand.Add(FVector2D(P.X, P.Z));
				}
			}
			if (InBand.Num() < 3)
			{
				continue;
			}
			InBand.Sort([](const FVector2D& A, const FVector2D& B) { return A.X > B.X; });
			int32 Start = 0, BestStart = 0, BestEnd = 0;
			double BestExtent = -1.0;
			for (int32 i = 1; i <= InBand.Num(); ++i)
			{
				if (i == InBand.Num() || InBand[i - 1].X - InBand[i].X > Gap)
				{
					const double Extent = InBand[Start].X - InBand[i - 1].X;
					if (Extent > BestExtent) { BestExtent = Extent; BestStart = Start; BestEnd = i; }
					Start = i;
				}
			}
			TArray<double> Zs;
			for (int32 i = BestStart; i < BestEnd; ++i)
			{
				Zs.Add(InBand[i].Y);
			}
			Zs.Sort();
			const double TopZ = Zs[FMath::Clamp(static_cast<int32>(0.9 * (Zs.Num() - 1)), 0, Zs.Num() - 1)];
			if (BestExtent > 1.0)
			{
				SheetStations.Add(FVector4(InBand[BestStart].X, BestExtent, TopZ, Sign * Y));
			}
		}
	}
	bSitesPlaced = true;
}

UMaterialInstanceDynamic* FFlightSimCondensation::SiteInstance(UMaterialInterface* Material,
                                                               UProceduralMeshComponent* Mesh, double Shape)
{
	UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(Material, Mesh);
	Instance->SetScalarParameterValue(FName(CondensationParamShape), static_cast<float>(Shape));
	Instance->SetScalarParameterValue(FName(CondensationParamOpacity), 0.0f);
	return Instance;
}

void FFlightSimCondensation::BuildAttachedSections(UWorld* World, UMaterialInterface* Material)
{
	Attached = World->SpawnActor<AActor>();
	if (Attached == nullptr)
	{
		return;
	}
	AttachedMesh = CondensationMesh(Attached, TEXT("Condensation"));
	const FLinearColor White = FLinearColor::White;   // vertex colour R = 1: the MID scalar alone

	// Section 0: the upper-wing sheet, a flat strip per side LiftCm above
	// the measured top, from the leading edge SheetChordFraction aft.
	{
		TArray<FVector> V; TArray<int32> T; TArray<FVector> N; TArray<FVector2D> UV; TArray<FLinearColor> C;
		const double LiftCm = 3.0;
		const double ChordFraction = Constant(TEXT("SheetChordFraction"));
		for (int32 Side = 0; Side < 2; ++Side)
		{
			TArray<FVector4> Row;
			for (const FVector4& S : SheetStations)
			{
				if ((Side == 0) == (S.W < 0.0)) { Row.Add(S); }
			}
			if (Row.Num() < 2)
			{
				continue;
			}
			const int32 Base = V.Num();
			for (int32 i = 0; i < Row.Num(); ++i)
			{
				const FVector4& S = Row[i];
				const double Span = static_cast<double>(i) / (Row.Num() - 1);
				V.Add(FVector(S.X, S.W, S.Z + LiftCm));
				V.Add(FVector(S.X - ChordFraction * S.Y, S.W, S.Z + LiftCm));
				UV.Add(FVector2D(0.0, Span));
				UV.Add(FVector2D(1.0, Span));
				N.Add(FVector::UpVector); N.Add(FVector::UpVector);
				C.Add(White); C.Add(White);
			}
			for (int32 i = 0; i + 1 < Row.Num(); ++i)
			{
				const int32 A = Base + 2 * i;
				T.Append({A, A + 2, A + 1, A + 1, A + 2, A + 3});
			}
		}
		AttachedMesh->CreateMeshSection_LinearColor(0, V, T, N, UV, C, {}, false);
		SheetMID = SiteInstance(Material, AttachedMesh, CondensationShapeSheet);
		AttachedMesh->SetMaterial(0, SheetMID);
	}
	// Section 1: the vapour cone, narrow at the collar station, widening aft
	// to the recompression shock (UV.x 1, drawn as a sharp edge).
	{
		TArray<FVector> V; TArray<int32> T; TArray<FVector> N; TArray<FVector2D> UV; TArray<FLinearColor> C;
		CondensationTube(V, T, N, UV, FVector(CollarStationCm, 0.0, CollarCentreZCm), 0.35 * CollarRadiusCm,
		                 CollarRadiusCm, Constant(TEXT("ConeLengthBodyFraction")) * BodyLengthCm);
		C.Init(White, V.Num());
		AttachedMesh->CreateMeshSection_LinearColor(1, V, T, N, UV, C, {}, false);
		ConeMID = SiteInstance(Material, AttachedMesh, CondensationShapeCone);
		AttachedMesh->SetMaterial(1, ConeMID);
	}
	// Section 2: the LEX vortex tubes (only on an airframe the look config
	// says has leading-edge extensions).
	if (Constant(TEXT("LexEnabled")) >= 0.5)
	{
		TArray<FVector> V; TArray<int32> T; TArray<FVector> N; TArray<FVector2D> UV; TArray<FLinearColor> C;
		for (int32 Side = 0; Side < 2; ++Side)
		{
			const double Sign = Side == 0 ? -1.0 : 1.0;
			const FVector Apex(NoseActorCm.X - Constant(TEXT("LexAftOfNoseM")) * CondensationCmPerM,
			                   Sign * Constant(TEXT("LexSpanM")) * CondensationCmPerM,
			                   NoseActorCm.Z + Constant(TEXT("LexUpM")) * CondensationCmPerM);
			CondensationTube(V, T, N, UV, Apex, 12.0, 60.0, Constant(TEXT("LexLengthM")) * CondensationCmPerM);
		}
		C.Init(White, V.Num());
		AttachedMesh->CreateMeshSection_LinearColor(2, V, T, N, UV, C, {}, false);
		LexMID = SiteInstance(Material, AttachedMesh, CondensationShapeTube);
		AttachedMesh->SetMaterial(2, LexMID);
	}
	AttachedMesh->RegisterComponent();
	// Its own actor, attached: the stencil loop labels every primitive OF the
	// aircraft actor, and this one must carry no label (BeautyOnlyActors).
	Attached->AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform);
	Attached->SetActorRelativeLocation(FVector::ZeroVector);
}

void FFlightSimCondensation::RebuildRibbon(FTipRibbon& Ribbon, double NowS)
{
	const double Lifetime = Constant(TEXT("LifetimeS"));
	Ribbon.Samples.RemoveAll([&](const FSample& S) { return NowS - S.TimeS > Lifetime; });
	if (Ribbon.Samples.Num() < 2)
	{
		Ribbon.Mesh->ClearMeshSection(0);
		return;
	}
	// A crossed ribbon (two strips at right angles) through every sample,
	// relative to the newest (small numbers in a large world).
	const FVector Anchor = Ribbon.Samples.Last().WorldCm;
	Ribbon.Owner->SetActorLocation(Anchor);
	TArray<FVector> V; TArray<int32> T; TArray<FVector> N; TArray<FVector2D> UV; TArray<FLinearColor> C;
	const int32 Count = Ribbon.Samples.Num();
	const double StartWidthM = Constant(TEXT("TipStartWidthM"));
	const double SpreadMPerS = Constant(TEXT("TipSpreadMPerS"));
	for (int32 Strip = 0; Strip < 2; ++Strip)
	{
		const int32 Base = V.Num();
		for (int32 i = 0; i < Count; ++i)
		{
			const FSample& S = Ribbon.Samples[i];
			const FVector Prev = Ribbon.Samples[FMath::Max(i - 1, 0)].WorldCm;
			const FVector Next = Ribbon.Samples[FMath::Min(i + 1, Count - 1)].WorldCm;
			const FVector Along = (Next - Prev).GetSafeNormal(UE_SMALL_NUMBER, FVector::ForwardVector);
			const FVector Side = FVector::CrossProduct(Along, FVector::UpVector).GetSafeNormal(UE_SMALL_NUMBER,
			                                                                                 FVector::RightVector);
			const FVector Up = FVector::CrossProduct(Side, Along).GetSafeNormal();
			const FVector Across = Strip == 0 ? Side : Up;
			const FVector Normal = Strip == 0 ? Up : Side;
			const double Age = FMath::Max(NowS - S.TimeS, 0.0);
			const double HalfCm = 0.5 * (StartWidthM + SpreadMPerS * Age) * CondensationCmPerM;
			const FVector P = S.WorldCm - Anchor;
			V.Add(P - Across * HalfCm);
			V.Add(P + Across * HalfCm);
			N.Add(Normal); N.Add(Normal);
			const double U = Age / FMath::Max(Lifetime, 0.01);
			UV.Add(FVector2D(U, 0.0));
			UV.Add(FVector2D(U, 1.0));
			const FLinearColor Weight(S.Weight, S.Weight, S.Weight, 1.0f);
			C.Add(Weight); C.Add(Weight);
		}
		for (int32 i = 0; i + 1 < Count; ++i)
		{
			const int32 A = Base + 2 * i;
			T.Append({A, A + 2, A + 1, A + 1, A + 2, A + 3});
		}
	}
	Ribbon.Mesh->CreateMeshSection_LinearColor(0, V, T, N, UV, C, {}, false);
}

bool FFlightSimCondensation::Advance(TFunctionRef<double(const TCHAR*)> ReadProperty,
                                     const TSharedPtr<FJsonObject>& Record)
{
	if (!bBuilt || !Out.IsValid())
	{
		bHumidityNow = false;
		return false;
	}
	const double Now = ReadProperty(TEXT("simulation/sim-time-sec"));

	// -- the humidity -----------------------------------------------------------
	double Rh = 0.0;
	if (Humidity.bParamStated)
	{
		Rh = Humidity.ParamPct;
	}
	else if (Humidity.bCardStated)
	{
		Rh = ReadProperty(TEXT("atmosphere/RH"));
	}
	bHumidityNow = (Humidity.bParamStated || Humidity.bCardStated) && FMath::IsFinite(Rh) && Rh >= 0.0;

	TSharedPtr<FJsonObject> Frame = MakeShared<FJsonObject>();
	Frame->SetNumberField(TEXT("t"), Now);
	double TipOpacity = 0.0, SheetOpacity = 0.0, LexOpacity = 0.0, ConeOpacity = 0.0;
	if (!bHumidityNow)
	{
		++FallbackFrames;
		Frame->SetBoolField(TEXT("fallback"), true);
	}
	else
	{
		++HumidFrames;
		Frame->SetNumberField(TEXT("rh_pct"), Rh);
		// -- the FDM reads (reads only; physics unchanged), in SI. A NaN read is
		// absent; a read that must be positive and is not (an absent property
		// reads 0) is absent too.
		auto Read = [&ReadProperty](const TCHAR* Name, double Scale)
		{
			const double V = ReadProperty(Name);
			return FMath::IsFinite(V) ? V * Scale : TNumericLimits<double>::Lowest();
		};
		const double Nz = Read(TEXT("accelerations/Nz"), 1.0);
		const double TK = Read(TEXT("atmosphere/T-R"), CondensationKelvinPerRankine);
		const double P = Read(TEXT("atmosphere/P-psf"), CondensationPaPerPsf);
		const double Rho = Read(TEXT("atmosphere/rho-slugs_ft3"), CondensationKgm3PerSlugft3);
		const double Mach = Read(TEXT("velocities/mach"), 1.0);
		const double Alpha = Read(TEXT("aero/alpha-deg"), 1.0);
		const double Qbar = Read(TEXT("aero/qbar-psf"), CondensationPaPerPsf);
		const double Vel = Read(TEXT("velocities/vtrue-kts"), CondensationMpsPerKt);
		const double B = Read(TEXT("metrics/bw-ft"), CondensationMPerFt);
		const double S = Read(TEXT("metrics/Sw-sqft"), CondensationMPerFt * CondensationMPerFt);
		const double W = Read(TEXT("inertia/weight-lbs"), CondensationNPerLbf);
		const double Absent = TNumericLimits<double>::Lowest();

		TSharedPtr<FJsonObject> Sites = MakeShared<FJsonObject>();
		// One site: Missing lists the absent inputs; bApplies false when gated
		// off; PLocal/TLocal the local state when it applies.
		auto Emit = [&](const TCHAR* Site, const TArray<FString>& Missing, bool bApplies, double PLocal,
		                double TLocal) -> double
		{
			TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
			const bool bValid = Missing.Num() == 0 && bApplies;
			const double PL = FMath::Max(PLocal, CondensationMinPressureRatio * P);
			const double Dq = bValid ? CondensationDqGkg(Rh, TK, P, TLocal, PL) : 0.0;
			const double Seen = bValid ? CondensationDqGkg(Rh, TK, P, TLocal + Constant(TEXT("OnsetCoolingK")), PL) : 0.0;
			const double Opacity = (bValid && Seen >= Constant(TEXT("VisibleMinGkg")))
				? FMath::Clamp(Constant(TEXT("OpacityPerGkg")) * Seen, 0.0, 1.0) : 0.0;
			Row->SetField(TEXT("dq_gkg"), CondensationNumberOrNull(bValid, Dq));
			Row->SetField(TEXT("dq_visible_gkg"), CondensationNumberOrNull(bValid, Seen));
			Row->SetNumberField(TEXT("opacity"), Opacity);
			if (Missing.Num() > 0)
			{
				TArray<TSharedPtr<FJsonValue>> Dropped;
				for (const FString& Name : Missing)
				{
					Dropped.Add(MakeShared<FJsonValueString>(Name));
				}
				Row->SetArrayField(TEXT("dropped"), Dropped);
			}
			Sites->SetObjectField(Site, Row);
			return Opacity;
		};
		auto Need = [&](TArray<FString>& Missing, const TCHAR* Name, double Value, bool bPositive)
		{
			if (Value == Absent || (bPositive && Value <= 0.0)) { Missing.Add(Name); }
		};
		auto Isentropic = [&](double PLocal) { return TK * FMath::Pow(FMath::Max(PLocal, CondensationMinPressureRatio * P) / P, CondensationPoisson); };

		// (a) the tip vortex cores.
		{
			TArray<FString> M;
			Need(M, TEXT("t_k"), TK, true); Need(M, TEXT("p_pa"), P, true); Need(M, TEXT("nz"), Nz, false);
			Need(M, TEXT("weight_n"), W, true); Need(M, TEXT("rho_kgm3"), Rho, true);
			Need(M, TEXT("v_mps"), Vel, true); Need(M, TEXT("b_m"), B, true);
			double PL = 0.0;
			if (M.Num() == 0)
			{
				const double Gamma = FMath::Abs(Nz) * W / (Rho * Vel * B * UE_DOUBLE_PI / 4.0);
				const double Rc = Constant(TEXT("CoreRadiusSpanFraction")) * B;
				PL = P - CondensationLambOseen * Rho * Gamma * Gamma / (4.0 * UE_DOUBLE_PI * UE_DOUBLE_PI * Rc * Rc);
			}
			TipOpacity = Emit(TEXT("tip"), M, true, PL, M.Num() == 0 ? Isentropic(PL) : 0.0);
		}
		// (b) the upper-wing sheet.
		{
			TArray<FString> M;
			Need(M, TEXT("t_k"), TK, true); Need(M, TEXT("p_pa"), P, true); Need(M, TEXT("nz"), Nz, false);
			Need(M, TEXT("weight_n"), W, true); Need(M, TEXT("qbar_pa"), Qbar, true);
			Need(M, TEXT("s_m2"), S, true); Need(M, TEXT("mach"), Mach, true);
			double PL = 0.0;
			if (M.Num() == 0)
			{
				const double CL = FMath::Abs(Nz) * W / (Qbar * S);
				const double CpMin = -(Constant(TEXT("SheetCpMinAtZeroLift")) + Constant(TEXT("CpMinPerCL")) * CL);
				PL = P * (1.0 + 0.7 * Mach * Mach * CpMin);
			}
			SheetOpacity = Emit(TEXT("sheet"), M, true, PL, M.Num() == 0 ? Isentropic(PL) : 0.0);
		}
		// (c) the LEX vortex (J-11 class).
		{
			TArray<FString> M;
			Need(M, TEXT("t_k"), TK, true); Need(M, TEXT("p_pa"), P, true);
			Need(M, TEXT("alpha_deg"), Alpha, false); Need(M, TEXT("mach"), Mach, true);
			const double Excess = Alpha - Constant(TEXT("LexAlphaOnsetDeg"));
			const bool bApplies = Constant(TEXT("LexEnabled")) >= 0.5 && Excess > 0.0;
			const double PL = P * (1.0 + 0.7 * Mach * Mach * (-Constant(TEXT("LexCpPerDeg")) * Excess));
			LexOpacity = Emit(TEXT("lex"), M, bApplies, PL, (M.Num() == 0 && bApplies) ? Isentropic(PL) : 0.0);
		}
		// (d) the transonic cone, ending at the recompression shock.
		{
			TArray<FString> M;
			Need(M, TEXT("t_k"), TK, true); Need(M, TEXT("p_pa"), P, true); Need(M, TEXT("mach"), Mach, true);
			const bool bApplies = Mach >= Constant(TEXT("ConeMachMin")) && Mach <= Constant(TEXT("ConeMachMax"));
			const double Ml = Constant(TEXT("ConeLocalMach"));
			const double Ratio = (1.0 + 0.2 * Mach * Mach) / (1.0 + 0.2 * Ml * Ml);
			ConeOpacity = Emit(TEXT("cone"), M, bApplies, P * FMath::Pow(Ratio, 3.5), TK * Ratio);
		}
		Frame->SetObjectField(TEXT("sites"), Sites);
	}

	// -- drive the drawn sites (one MID scalar per site) ------------------------
	if (SheetMID != nullptr) { SheetMID->SetScalarParameterValue(FName(CondensationParamOpacity), static_cast<float>(SheetOpacity)); }
	if (ConeMID != nullptr) { ConeMID->SetScalarParameterValue(FName(CondensationParamOpacity), static_cast<float>(ConeOpacity)); }
	if (LexMID != nullptr) { LexMID->SetScalarParameterValue(FName(CondensationParamOpacity), static_cast<float>(LexOpacity)); }
	if (Aircraft != nullptr)
	{
		const FTransform ActorFrame = Aircraft->GetActorTransform();
		for (FTipRibbon& Ribbon : Tips)
		{
			if (TipOpacity > 0.0)
			{
				FSample Sample;
				Sample.WorldCm = ActorFrame.TransformPosition(Ribbon.SourceActorCm);
				Sample.TimeS = Now;
				Sample.Weight = static_cast<float>(TipOpacity);
				Ribbon.Samples.Add(Sample);
			}
			RebuildRibbon(Ribbon, Now);
		}
	}

	// -- the record, current at every step (render.json is written at the end).
	PerFrame.Add(MakeShared<FJsonValueObject>(Frame));
	Out->SetArrayField(TEXT("per_frame"), PerFrame);
	Out->SetBoolField(TEXT("fallback_used"), FallbackFrames > 0);
	Out->SetNumberField(TEXT("fallback_frames"), FallbackFrames);
	Out->SetNumberField(TEXT("humid_frames"), HumidFrames);
	if (Record.IsValid())
	{
		Record->SetObjectField(TEXT("condensation"), Out);
	}
	// The tips condense but no ribbon of ours draws them: the caller's
	// wingtip vapour trails carry them.
	return TipOpacity > 0.0 && !bTipsDrawn;
}
