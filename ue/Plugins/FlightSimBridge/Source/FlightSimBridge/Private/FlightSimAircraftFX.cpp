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
#include "Engine/StaticMesh.h"  // cockpit-airframe: the beauty body swap
#include "Engine/World.h"
#include "HAL/PlatformMisc.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/Material.h"           // round 23: GetBaseMaterial()->GetName() (probe slots)
#include "Materials/MaterialInterface.h"
#include "Engine/Texture.h"               // round 23: the flat probe copies BaseColorMap
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
	// round-2b weather-fx (2026-11-09): the lamps' volumetric scattering
	// (the engine's default is 1, a lit solid cone in fog). Fallbacks for a
	// manifest without lights.LandingVolumetricScattering / NavVolumetricScattering;
	// UNCALIBRATED, set by probe render (docs/visual/PROBE_LOG.md ## round-2b weather-fx).
	constexpr double AircraftFxLandingVolumetricScattering = 0.3;
	constexpr double AircraftFxNavVolumetricScattering = 0.5;
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
	// Round 23: -aircraft-probe=flat (scripts/aircraft_look.py PROBE_FLAT_MASTER).
	const TCHAR* const AircraftFxProbeFlatMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftProbeFlat.M_AircraftProbeFlat");
	// Round 24: -aircraft-probe=defaultlit (scripts/aircraft_look.py PROBE_DEFAULT_LIT_MASTER).
	const TCHAR* const AircraftFxProbeDefaultLitMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftPaintDefaultLit.M_AircraftPaintDefaultLit");
	// Round 24: -aircraft-probe=tangentnormal (aircraft_look.PROBE_TANGENT_NORMAL_MASTER).
	const TCHAR* const AircraftFxProbeTangentNormalMaterialPath =
		TEXT("/Game/FlightSim/Aircraft/M_AircraftPaintTangentNormal.M_AircraftPaintTangentNormal");
	// scripts/aircraft_look.py FX_PARAMETERS (pinned by tests/test_aircraft_look.py).
	const TCHAR* const AircraftFxParamLightColour = TEXT("LightColour");
	const TCHAR* const AircraftFxParamIntensity = TEXT("Intensity");
	const TCHAR* const AircraftFxParamStrobe = TEXT("Strobe");
	const TCHAR* const AircraftFxParamOpacity = TEXT("Opacity");
	const TCHAR* const AircraftFxParamFormation = TEXT("Formation");
	const TCHAR* const AircraftFxParamFormationRamp = TEXT("FormationRamp");
	// contrail_opacity.hlsl generation 6's fixed ramp (an age fraction).
	constexpr double AircraftFxLegacyFormationRamp = 0.04;
	const TCHAR* const AircraftFxParamTime = TEXT("TimeS");
	const TCHAR* const AircraftFxParamStrength = TEXT("Strength");
	const TCHAR* const AircraftFxParamBeamDirection = TEXT("BeamDirection");
	const TCHAR* const AircraftFxParamBeamCos = TEXT("BeamCos");
	const TCHAR* const AircraftFxParamCoreColour = TEXT("CoreColour");
	const TCHAR* const AircraftFxParamTipColour = TEXT("TipColour");
	const TCHAR* const AircraftFxParamShocks = TEXT("Shocks");
	// scripts/aircraft_look.py nav_bulb_area_factor(): nav_bulb.hlsl's falloff
	// integrated over one quad, per half-size squared (pinned by test). Used
	// only for a look manifest that predates bulb_luminance_nits.
	constexpr double AircraftFxNavBulbAreaFactor = 0.32715038;
	// scripts/aircraft_look.py OMNI_BEAM_COS: no beam (drawn from every side).
	constexpr double AircraftFxOmniBeamCos = -2.0;
	// heat_haze.hlsl's envelope peak, (1 - u) x saturate(8 u) at u = 1/8
	// (aircraft_look.py HEAT_HAZE_FADE_PEAK).
	constexpr double AircraftFxHeatHazeFadePeak = 0.875;
	// UE 5.7.4 Shaders/Private/DistortionCommon.ush OffsetFudgeFactor
	// (check_bridge_api.sh pins it; aircraft_look.py UE_DISTORTION_OFFSET_FUDGE).
	constexpr double AircraftFxDistortionOffsetFudge = 0.00023;
	// The look instances: <asset_path_root>/Look/MI_<slot> (aircraft_look.py
	// LOOK_INSTANCE_FOLDER / LOOK_INSTANCE_PREFIX).
	const TCHAR* const AircraftFxLookFolder = TEXT("Look");
	const TCHAR* const AircraftFxLookPrefix = TEXT("MI_");
	// round 5 (L4): the Thin Translucent canopy instance beside a glass slot's
	// opaque one (aircraft_look.THIN_INSTANCE_SUFFIX), applied without -labels only.
	const TCHAR* const AircraftFxThinSuffix = TEXT("_thin");

	// on/1/true or off/0/false; any other word is refused by name (it was
	// read as "on", so -heat-haze=no turned the pixel-moving haze ON). Twin of
	// scripts/aircraft_look.py parse_fx_switches.
	bool AircraftFxSwitch(const FString& Params, const TCHAR* Key, bool Default, FString& Error)
	{
		FString Word;
		if (!FParse::Value(*Params, Key, Word))
		{
			return Default;
		}
		if (Word == TEXT("on") || Word == TEXT("1") || Word == TEXT("true"))
		{
			return true;
		}
		if (Word == TEXT("off") || Word == TEXT("0") || Word == TEXT("false"))
		{
			return false;
		}
		if (Error.IsEmpty())
		{
			Error = FString::Printf(TEXT("aircraft_look.switch: -%s%s is not on/1/true or off/0/false"), Key, *Word);
		}
		return Default;
	}

	bool AircraftFxPair(const TSharedPtr<FJsonObject>& Row, const TCHAR* Field, FVector2D& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Row.IsValid() && Row->TryGetArrayField(Field, Values) && Values != nullptr && Values->Num() == 2)
		{
			Out = FVector2D((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber());
			return true;
		}
		return false;
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

void FFlightSimAircraftFXOptions::ParseParams(const FString& CommandLine)
{
	SwitchError.Reset();
	// Rounds 13-18: the A/B channel (FLIGHTSIM_RENDER_SWITCHES, what
	// visual_fix_round.ps1 -Switches sets) was never read here, so
	// -aircraft-materials=off rendered identical frames. The command line,
	// then the environment, as the world look reads them.
	const FString Params = CommandLine + TEXT(" ")
		+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
	const bool bAll = AircraftFxSwitch(Params, TEXT("aircraft-look="), true, SwitchError);
	// Every switch is parsed (no short-circuit), so a bad word is refused
	// even under -aircraft-look=off.
	// Round 22 (2026-11-11): OFF by default. With the gen-4 look instances the
	// A-4 drew tan (111/98/84 in its mask, #4) and the C172 near-black under
	// overcast (27/18/17, #8); -aircraft-materials=off drew them white
	// (167/155/147) and lit grey (89/82/92). The imported materials stand until
	// a bisect inside the masters finds the cause; -aircraft-materials=on is the
	// probe. Labels never depended on them.
	// Final sweep: ON again, with the flat paint master by default (below,
	// -aircraft-probe= absent). Off (round 22's default) blacked out #12's canopy.
	const bool bMaterialsSwitch = AircraftFxSwitch(Params, TEXT("aircraft-materials="), true, SwitchError);
	const bool bLightsSwitch = AircraftFxSwitch(Params, TEXT("aircraft-lights="), true, SwitchError);
	const bool bContrailsSwitch = AircraftFxSwitch(Params, TEXT("contrails="), true, SwitchError);
	const bool bAfterburnerSwitch = AircraftFxSwitch(Params, TEXT("afterburner="), true, SwitchError);
	// Pixel-moving: off unless asked for by name.
	const bool bHeatHazeSwitch = AircraftFxSwitch(Params, TEXT("heat-haze="), false, SwitchError);
	const bool bFormationRampSwitch = AircraftFxSwitch(Params, TEXT("contrail-formation-ramp="), true, SwitchError);
	bMaterials = bAll && bMaterialsSwitch;
	bLights = bAll && bLightsSwitch;
	bContrails = bAll && bContrailsSwitch;
	bAfterburner = bAll && bAfterburnerSwitch;
	bHeatHaze = bAll && bHeatHazeSwitch;
	bContrailFormationRamp = bAll && bFormationRampSwitch;
	// round 5 (L4): the same -labels word the commandlet reads (aircraft_look.labels_requested).
	bLabels = FParse::Param(*Params, TEXT("labels"));
	// Round 23: the master bisect probes (aircraft_look.parse_aircraft_probes).
	// bShouldStopOnSeparator false: the value is a comma list.
	Probes.Reset();
	FString ProbeList;
	if (FParse::Value(*Params, TEXT("aircraft-probe="), ProbeList, false))
	{
		TArray<FString> Words;
		ProbeList.ParseIntoArray(Words, TEXT(","), true);
		for (FString Word : Words)
		{
			Word.TrimStartAndEndInline();
			if (Word.IsEmpty() || Word == TEXT("none"))
			{
				continue;
			}
			const bool bKnown = Word == TEXT("nocoat") || Word == TEXT("noao") || Word == TEXT("nonormal") ||
				Word == TEXT("nowear") || Word == TEXT("flat") || Word == TEXT("measured-mesh") ||
				// round 24 (LOOK_GENERATION 6)
				Word == TEXT("nowet") || Word == TEXT("rawbase") || Word == TEXT("defaultlit") ||
				Word == TEXT("basecolor-debug") || Word == TEXT("tangentnormal");
			if (!bKnown)
			{
				if (SwitchError.IsEmpty())
				{
					SwitchError = FString::Printf(TEXT("aircraft_look.switch: -aircraft-probe=%s: '%s' is not one of ")
						TEXT("nocoat, noao, nonormal, nowear, flat, measured-mesh, nowet, rawbase, defaultlit, ")
						TEXT("basecolor-debug, tangentnormal"), *ProbeList, *Word);
				}
				continue;
			}
			Probes.AddUnique(Word);
		}
	}
	else
	{
		// Final sweep (round 44): the default paint is the flat master. The
		// bisect (r27-r40) found the gen-4..6 paint and bare-metal masters
		// darken the aircraft (C172 12/10/10 vs 89/82/92 under overcast) while
		// M_AircraftProbeFlat on the same instance inputs matched the imported
		// materials exactly; glass and rubber keep their look instances, so the
		// cockpit canopy stays the thin translucent glass (#12 went 75 % black
		// with every look instance off). -aircraft-probe=none: the full masters.
		Probes.Add(TEXT("flat"));
	}
	Humidity.ParseParams(Params);  // condensation-solver: -humidity-pct=
}

double FFlightSimAircraftFX::HeatHazeMaxDisplacementPx(double MaterialOffset, double WidthPx, double HeightPx,
                                                        double HFovDeg)
{
	const double TanHalf = FMath::Tan(FMath::DegreesToRadians(FMath::Clamp(HFovDeg, 1.0, 179.0)) * 0.5);
	return MaterialOffset * WidthPx * AircraftFxDistortionOffsetFudge / TanHalf *
		FMath::Sqrt(WidthPx * WidthPx + HeightPx * HeightPx);
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
	Weather = Options.Weather;  // wet-airframe-canopy
	CloudLayers = Options.CloudLayers;
	Record = MakeShared<FJsonObject>();
	if (!Options.SwitchError.IsEmpty())
	{
		Error = Options.SwitchError;
		return false;
	}
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
				// cockpit-airframe (round 2): assets_pipeline/convert.py
				// _write_beauty_mesh, {"body": {"part": "body_beauty", ...}}.
				const TSharedPtr<FJsonObject>* BeautyParts = nullptr;
				if (MeshManifest->TryGetObjectField(TEXT("beauty_parts"), BeautyParts) && BeautyParts != nullptr)
				{
					for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*BeautyParts)->Values)
					{
						const TSharedPtr<FJsonObject> Row = Entry.Value.IsValid() ? Entry.Value->AsObject() : nullptr;
						FString BeautyPart;
						if (Row.IsValid() && Row->TryGetStringField(TEXT("part"), BeautyPart))
						{
							BeautyMeshes.Add(Entry.Key, BeautyPart);
						}
					}
				}
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
		// The mesh manifest the anchors were measured on. Not compared here
		// (no hashing in this file): a reader compares it with render.json's
		// own mesh manifest sha256, and a mismatch means the lamps and
		// nozzles were placed on an earlier conversion of the mesh (re-run
		// python scripts/aircraft_look.py <NAME> or the import step).
		FString MeshSha;
		if (Look->TryGetStringField(TEXT("mesh_manifest_sha256"), MeshSha))
		{
			Record->SetStringField(TEXT("look_mesh_manifest_sha256"), MeshSha);
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
		if (Options.Probes.Num() > 0)
		{
			// Round 23: a probe needs the look instances to act on.
			Record->SetStringField(TEXT("materials_probes"), FString::Printf(
				TEXT("ignored: -aircraft-probe=%s needs -aircraft-materials=on"),
				*FString::Join(Options.Probes, TEXT(","))));
		}
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
			Row->SetNumberField(TEXT("bulb_luminance_nits"), Lamp.BulbNits);
			Row->SetBoolField(TEXT("bulb_drawn"), Lamp.Bulb != nullptr);
			LightRows.Add(MakeShared<FJsonValueObject>(Row));
		}
	}
	Record->SetArrayField(TEXT("lights"), LightRows);
	Record->SetStringField(TEXT("lights_note"), TEXT("point/spot lights move no geometry; the bulbs are additive ")
		TEXT("(they hide nothing), beauty-only actors the label captures hide"));
	Record->SetNumberField(TEXT("landing_volumetric_scattering"),
		Constant(TEXT("lights"), TEXT("LandingVolumetricScattering"), AircraftFxLandingVolumetricScattering));
	Record->SetNumberField(TEXT("nav_volumetric_scattering"),
		Constant(TEXT("lights"), TEXT("NavVolumetricScattering"), AircraftFxNavVolumetricScattering));

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
		Trail.Instance = Instance;
		Trail.BaseOpacity = Constant(Group, TEXT("Opacity"), bVapour ? 0.35 : 0.55);
		Instance->SetScalarParameterValue(FName(AircraftFxParamOpacity), static_cast<float>(Trail.BaseOpacity));
		const double Lifetime = Constant(Group, TEXT("LifetimeS"), bVapour ? 0.8 : 25.0);
		const double Formation = bVapour ? 0.0 : Constant(TEXT("contrail"), TEXT("FormationDelayS"), 0.15);
		Instance->SetScalarParameterValue(FName(AircraftFxParamFormation),
			static_cast<float>(Formation / FMath::Max(Lifetime, 0.01)));
		// Round 47 (#13): the ramp in seconds (LOOK_GENERATION 7's FormationRamp); off,
		// generation 6's 0.04 of the lifetime (1 s, 250 m at cruise: the four lines).
		const double Ramp = !bVapour && Options.bContrailFormationRamp
			? Constant(TEXT("contrail"), TEXT("FormationRampS"), 0.25) / FMath::Max(Lifetime, 0.01)
			: AircraftFxLegacyFormationRamp;
		Instance->SetScalarParameterValue(FName(AircraftFxParamFormationRamp), static_cast<float>(Ramp));
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
	ContrailRow->SetBoolField(TEXT("formation_ramp_on"), Options.bContrailFormationRamp);
	ContrailRow->SetStringField(TEXT("formation_ramp_basis"), Options.bContrailFormationRamp
		? TEXT("round 47: the trail forms over contrail.FormationRampS after FormationDelayS (FormationRamp = "
		       "FormationRampS / LifetimeS); -contrail-formation-ramp=off is the A/B")
		: TEXT("-contrail-formation-ramp=off: generation 6's ramp, 0.04 of LifetimeS (1 s at 25 s: #13's four "
		       "faint lines that read as marks on the sea)"));
	ContrailRow->SetStringField(TEXT("rule"), TEXT("drawn while atmosphere/T-R is below contrail.MaxTemperatureK ")
		TEXT("and position/h-sl-meters above contrail.MinAltitudeM (Schmidt-Appleman threshold, no humidity ")
		TEXT("modelled); wingtip vapour from the humidity test (aircraft_look.condensation), or while ")
		TEXT("accelerations/Nz exceeds vapour.MinNz when the humidity is unavailable; vapour_frames counts ")
		TEXT("only the frames these wingtip vapour trails drew (the humidity-gated tip ribbons' frames are in ")
		TEXT("aircraft_look.condensation.per_frame)"));
	ContrailRow->SetStringField(TEXT("in_cloud"), TEXT("a contrail's opacity x (1 - cover) of every cloud layer ")
		TEXT("the aircraft is inside (base..top above the ground datum); contrail_in_cloud_frames counts them"));
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
			// heat_haze.hlsl: each offset component is at most Strength / 100 x
			// the fade's peak (0.875) in REFRACTION units, not of the screen: the
			// engine scales it by the view (HeatHazeMaxDisplacementPx), which the
			// commandlet applies with the capture's width, height and FOV
			// (render.json pixel_moving_effects heat_haze.max_displacement_px).
			HazeRow->SetNumberField(TEXT("max_material_offset"),
				Constant(TEXT("heat_haze"), TEXT("Strength"), 0.6) * 0.01 * AircraftFxHeatHazeFadePeak);
			HazeRow->SetNumberField(TEXT("engine_offset_fudge"), AircraftFxDistortionOffsetFudge);
			HazeRow->SetStringField(TEXT("bound_formula"), TEXT("px = max_material_offset x W x 0.00023 / ")
				TEXT("tan(hFOV/2) x sqrt(W^2 + H^2) (UE 5.7.4 DistortionCommon.ush, along the diagonal)"));
		}
	}
	Record->SetObjectField(TEXT("heat_haze"), HazeRow);
	// condensation-solver: the humidity-gated vapour sites, own beauty-only actors.
	if (!Condensation.Build(World, Aircraft, Constants, Options.Humidity, Options.bContrails, BeautyOnlyActors, Error)) { return false; }
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
	// cockpit-airframe (round 2): a part with a beauty copy (mesh manifest
	// beauty_parts) draws the copy on this beauty render: the same triangles at
	// the same positions with the .ac crease normals and two-sided back faces,
	// so the silhouette, custom depth and stencil (component settings, kept by
	// SetStaticMesh) are the measured part's. Swapped only when the copy's
	// slots are the measured part's slots, name for name, so the look
	// instances below land on the same materials.
	TArray<TSharedPtr<FJsonValue>> BeautyRows;
	// Round 23: -aircraft-probe=measured-mesh keeps the measured mesh (the
	// round-22 A/B swapped the mesh AND the materials together: the beauty
	// copy is swapped only here).
	const bool bProbeMeasuredMesh = Options.Probes.Contains(TEXT("measured-mesh"));
	Row->SetBoolField(TEXT("beauty_mesh_swap"), !bProbeMeasuredMesh);
	for (UStaticMeshComponent* Part : bProbeMeasuredMesh ? TInlineComponentArray<UStaticMeshComponent*>() : Parts)
	{
		UStaticMesh* Measured = Part != nullptr ? Part->GetStaticMesh().Get() : nullptr;
		const FString* BeautyName = Measured != nullptr ? BeautyMeshes.Find(Measured->GetName()) : nullptr;
		if (BeautyName == nullptr)
		{
			continue;
		}
		const FString BeautyPath = FString::Printf(TEXT("%s/%s.%s"), *AssetRoot, **BeautyName, **BeautyName);
		UStaticMesh* BeautyMesh = LoadObject<UStaticMesh>(nullptr, *BeautyPath);
		FString Reason;
		if (BeautyMesh == nullptr)
		{
			Reason = TEXT("not imported (run the import step: assets_pipeline/importer.py)");
		}
		else
		{
			const TArray<FStaticMaterial>& From = Measured->GetStaticMaterials();
			const TArray<FStaticMaterial>& To = BeautyMesh->GetStaticMaterials();
			bool bSameSlots = From.Num() == To.Num();
			for (int32 Slot = 0; bSameSlots && Slot < From.Num(); ++Slot)
			{
				bSameSlots = From[Slot].MaterialSlotName == To[Slot].MaterialSlotName;
			}
			if (!bSameSlots)
			{
				Reason = TEXT("its material slots differ from the measured part's; the measured mesh is kept");
			}
			else if (!Part->SetStaticMesh(BeautyMesh))
			{
				Reason = TEXT("SetStaticMesh refused (component mobility); the measured mesh is kept");
			}
		}
		TSharedPtr<FJsonObject> BeautyRow = MakeShared<FJsonObject>();
		BeautyRow->SetStringField(TEXT("part"), Measured->GetName());
		BeautyRow->SetStringField(TEXT("beauty_mesh"), BeautyPath);
		BeautyRow->SetBoolField(TEXT("swapped"), Reason.IsEmpty());
		if (!Reason.IsEmpty())
		{
			BeautyRow->SetStringField(TEXT("reason"), Reason);
		}
		BeautyRows.Add(MakeShared<FJsonValueObject>(BeautyRow));
	}
	Row->SetArrayField(TEXT("beauty_meshes"), BeautyRows);
	int32 Applied = 0;
	int32 Unbound = 0;
	int32 ThinApplied = 0;
	// Round 23: the probes in force (recorded below) and the flat master.
	int32 ProbedSlots = 0;
	UMaterialInterface* ProbeFlat = Options.Probes.Contains(TEXT("flat"))
		? LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeFlatMaterialPath) : nullptr;
	UMaterialInterface* ProbeDefaultLit = Options.Probes.Contains(TEXT("defaultlit"))
		? LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeDefaultLitMaterialPath) : nullptr;
	UMaterialInterface* ProbeTangentNormal = Options.Probes.Contains(TEXT("tangentnormal"))
		? LoadObject<UMaterialInterface>(nullptr, AircraftFxProbeTangentNormalMaterialPath) : nullptr;
	{
		TArray<TSharedPtr<FJsonValue>> ProbeWords;
		for (const FString& Word : Options.Probes)
		{
			ProbeWords.Add(MakeShared<FJsonValueString>(Word));
		}
		Row->SetArrayField(TEXT("probes"), ProbeWords);
		if (Options.Probes.Contains(TEXT("defaultlit")) && ProbeDefaultLit == nullptr)
		{
			Row->SetStringField(TEXT("probe_defaultlit"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 6); the look ")
				TEXT("instances stand"), AircraftFxProbeDefaultLitMaterialPath));
		}
		if (Options.Probes.Contains(TEXT("tangentnormal")) && ProbeTangentNormal == nullptr)
		{
			Row->SetStringField(TEXT("probe_tangentnormal"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 6); the look ")
				TEXT("instances stand"), AircraftFxProbeTangentNormalMaterialPath));
		}
		if (Options.Probes.Contains(TEXT("flat")) && ProbeFlat == nullptr)
		{
			Row->SetStringField(TEXT("probe_flat"), FString::Printf(
				TEXT("absent: %s not found (run scripts/ue_create_materials.py: LOOK_GENERATION 5); the look ")
				TEXT("instances stand"), AircraftFxProbeFlatMaterialPath));
		}
	}
	// Slot names without a look instance, once each (AddUnique on the JSON
	// values would compare pointers and never deduplicate a slot that several
	// parts share).
	TArray<FString> AbsentNames;
	TArray<FString> ThinNames;
	for (UStaticMeshComponent* Part : Parts)
	{
		for (int32 Slot = 0; Slot < Part->GetNumMaterials(); ++Slot)
		{
			UMaterialInterface* Current = Part->GetMaterial(Slot);
			if (Current == nullptr)
			{
				++Unbound;  // cockpit-airframe: counted, was skipped silently
				continue;
			}
			const FString SlotName = Current->GetName();
			const FString InstanceName = FString::Printf(TEXT("%s%s"), AircraftFxLookPrefix, *SlotName);
			const FString Path = FString::Printf(TEXT("%s/%s/%s.%s"), *AssetRoot, AircraftFxLookFolder,
			                                     *InstanceName, *InstanceName);
			// round 5 (L4): the Thin Translucent canopy, MI_<slot>_thin, where
			// one exists and the render carries no -labels; otherwise (a
			// labelled frame, or a slot that is not glass) the opaque MI_<slot>.
			UMaterialInterface* LookInstance = nullptr;
			bool bThin = false;
			if (!Options.bLabels)
			{
				const FString ThinName = InstanceName + AircraftFxThinSuffix;
				const FString ThinPath = FString::Printf(TEXT("%s/%s/%s.%s"), *AssetRoot, AircraftFxLookFolder,
				                                         *ThinName, *ThinName);
				LookInstance = LoadObject<UMaterialInterface>(nullptr, *ThinPath);
				bThin = LookInstance != nullptr;
			}
			if (LookInstance == nullptr)
			{
				LookInstance = LoadObject<UMaterialInterface>(nullptr, *Path);
			}
			if (LookInstance == nullptr)
			{
				AbsentNames.AddUnique(SlotName);
				continue;
			}
			// Round 23: the bisect probes, on the paint and bare-metal slots only
			// (aircraft_look.PROBE_MASTERS); glass and rubber keep their instances.
			const UMaterial* ProbeBase = LookInstance->GetBaseMaterial();
			const FString ProbeBaseName = ProbeBase != nullptr ? ProbeBase->GetName() : FString();
			const bool bProbeSlot = Options.Probes.Num() > 0 &&
				(ProbeBaseName == TEXT("M_AircraftPaint") || ProbeBaseName == TEXT("M_AircraftBareMetal"));
			if (bProbeSlot && Options.Probes.Contains(TEXT("flat")) && ProbeFlat != nullptr)
			{
				// A plain lit dielectric with the instance's own colour and texture.
				UMaterialInstanceDynamic* FlatMid = UMaterialInstanceDynamic::Create(ProbeFlat, Part);
				if (FlatMid != nullptr)
				{
					FLinearColor ProbeColour = FLinearColor::White;
					UTexture* ProbeTexture = nullptr;
					float ProbeWeight = 0.0f;
					if (LookInstance->GetVectorParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColor"))), ProbeColour))
					{
						FlatMid->SetVectorParameterValue(TEXT("BaseColor"), ProbeColour);
					}
					if (LookInstance->GetTextureParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColorMap"))), ProbeTexture)
					    && ProbeTexture != nullptr)
					{
						FlatMid->SetTextureParameterValue(TEXT("BaseColorMap"), ProbeTexture);
					}
					if (LookInstance->GetScalarParameterValue(FHashedMaterialParameterInfo(FName(TEXT("BaseColorMapWeight"))), ProbeWeight))
					{
						FlatMid->SetScalarParameterValue(TEXT("BaseColorMapWeight"), ProbeWeight);
					}
					Part->SetMaterial(Slot, FlatMid);
					++Applied;
					++ProbedSlots;
					continue;
				}
			}
			// wet-airframe-canopy: a MID of the look instance, so the wet scalars can be set per step.
			UMaterialInstanceDynamic* LookMid = nullptr;
			UMaterialInstance* LookMic = Cast<UMaterialInstance>(LookInstance);
			// Round 24: a paint slot onto a twin master (the paint graph on
			// MSM_DEFAULT_LIT, or with a tangent-space normal), with this
			// instance's overrides; defaultlit wins if both are asked.
			UMaterialInterface* PaintTwin = Options.Probes.Contains(TEXT("defaultlit")) ? ProbeDefaultLit
				: (Options.Probes.Contains(TEXT("tangentnormal")) ? ProbeTangentNormal : nullptr);
			if (bProbeSlot && PaintTwin != nullptr && ProbeBaseName == TEXT("M_AircraftPaint") && LookMic != nullptr)
			{
				LookMid = UMaterialInstanceDynamic::Create(PaintTwin, Part);
				if (LookMid != nullptr)
				{
					LookMid->CopyParameterOverrides(LookMic);
				}
			}
			if (LookMid == nullptr)
			{
				LookMid = UMaterialInstanceDynamic::Create(LookInstance, Part);
			}
			if (bProbeSlot && LookMid != nullptr)
			{
				// Round 24 (aircraft_wet_layer.PROBE_SCALARS on the gen-6 masters).
				if (Options.Probes.Contains(TEXT("nowet")))
				{
					LookMid->SetScalarParameterValue(TEXT("WetLayerAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("rawbase")))
				{
					LookMid->SetScalarParameterValue(TEXT("RawBaseAmount"), 1.0f);
				}
				if (Options.Probes.Contains(TEXT("basecolor-debug")))
				{
					LookMid->SetScalarParameterValue(TEXT("BaseDebug"), 1.0f);
				}
				// Scalar overrides on the gen-5/6 masters' own parameters
				// (aircraft_look.AIRCRAFT_PROBES); a parameter a master lacks
				// (ClearCoat on bare metal) is a no-op.
				if (Options.Probes.Contains(TEXT("nocoat")))
				{
					LookMid->SetScalarParameterValue(TEXT("ClearCoat"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("noao")))
				{
					LookMid->SetScalarParameterValue(TEXT("PanelAoAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("nonormal")))
				{
					LookMid->SetScalarParameterValue(TEXT("PanelNormalAmount"), 0.0f);
				}
				if (Options.Probes.Contains(TEXT("nowear")))
				{
					LookMid->SetScalarParameterValue(TEXT("WearAmount"), 0.0f);
					LookMid->SetScalarParameterValue(TEXT("GrimeAmount"), 0.0f);
					LookMid->SetScalarParameterValue(TEXT("SootAmount"), 0.0f);
				}
				++ProbedSlots;
			}
			Part->SetMaterial(Slot, LookMid != nullptr ? static_cast<UMaterialInterface*>(LookMid) : LookInstance);
			if (LookMid != nullptr) { LookMids.Add(LookMid); }
			++Applied;
			if (bThin)
			{
				++ThinApplied;
				ThinNames.AddUnique(SlotName);
			}
		}
	}
	Row->SetStringField(TEXT("state"), TEXT("look instances on the mesh's slots (shading only: no world position ")
		TEXT("offset; every class master opaque but the thin canopy, which is applied only without -labels, ")
		TEXT("so the label silhouette is the beauty's)"));
	Row->SetStringField(TEXT("instance_root"), AssetRoot + TEXT("/") + AircraftFxLookFolder);
	Row->SetNumberField(TEXT("slots_applied"), Applied);
	Row->SetNumberField(TEXT("slots_without_material"), Unbound);
	Row->SetNumberField(TEXT("slots_thin_translucent"), ThinApplied);
	Row->SetNumberField(TEXT("slots_probed"), ProbedSlots);
	Row->SetBoolField(TEXT("labels"), Options.bLabels);
	Row->SetStringField(TEXT("thin_glass"), Options.bLabels
		? TEXT("label-safe opaque glass kept: -labels (the ID and depth captures draw no translucency)")
		: TEXT("MI_<slot>_thin (Thin Translucent, Surface ForwardShading) where it exists: beauty without labels"));
	TArray<TSharedPtr<FJsonValue>> Thin;
	for (const FString& Name : ThinNames)
	{
		Thin.Add(MakeShared<FJsonValueString>(Name));
	}
	Row->SetArrayField(TEXT("slots_thin"), Thin);
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
		const double RadiusCm = Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0);
		AircraftFxBulbSection(Mesh, RadiusCm);
		Lamp.Bulb = UMaterialInstanceDynamic::Create(BulbMaterial, Mesh);
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamLightColour), Linear);
		// The bulb's luminance is the lamp's own candela over the sprite's
		// effective area (aircraft_look.py bulb_luminance_nits): the light the
		// lamp throws and the lamp the camera sees are one number, metered by
		// the frame's one exposure. No cap.
		if (!Row->TryGetNumberField(TEXT("bulb_luminance_nits"), Lamp.BulbNits))
		{
			const double RadiusM = FMath::Max(RadiusCm, 0.01) / AircraftFxCmPerMetre;
			Lamp.BulbNits = Lamp.Candela * Gain / (AircraftFxNavBulbAreaFactor * RadiusM * RadiusM);
		}
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamIntensity), static_cast<float>(Lamp.BulbNits));
		Lamp.Bulb->SetScalarParameterValue(FName(AircraftFxParamStrobe), Lamp.bStrobe ? 0.0f : 1.0f);
		// A landing lamp is a beam: its bulb fades outside the spot's own cone.
		FVector2D BeamCos(AircraftFxOmniBeamCos, AircraftFxOmniBeamCos);
		AircraftFxPair(Row, TEXT("beam_cos"), BeamCos);
		FVector BeamDirection = AircraftFxVector(Row, TEXT("direction_actor"));
		if (BeamDirection.IsNearlyZero())
		{
			BeamDirection = FVector(1.0, 0.0, 0.0);
		}
		BeamDirection = BeamDirection.GetSafeNormal();
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamBeamDirection),
			FLinearColor(BeamDirection.X, BeamDirection.Y, BeamDirection.Z, 0.0f));
		Lamp.Bulb->SetVectorParameterValue(FName(AircraftFxParamBeamCos),
			FLinearColor(BeamCos.X, BeamCos.Y, 0.0f, 0.0f));
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
		// round-2b weather-fx: in fog or rain a lamp at full volumetric
		// scattering draws its whole cone as a lit solid (round 0 #09: hard-edged
		// cones under the 747). A stated fraction, UNCALIBRATED; the falloff
		// between the inner and outer cone keeps its edge soft.
		Lamp.Spot->SetVolumetricScatteringIntensity(static_cast<float>(
			Constant(TEXT("lights"), TEXT("LandingVolumetricScattering"), AircraftFxLandingVolumetricScattering)));
		Lamp.Spot->SetSourceRadius(static_cast<float>(Constant(TEXT("lights"), TEXT("BulbRadiusCm"), 18.0)));
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
		// round-2b weather-fx: a halo in the fog, not a lit ball (UNCALIBRATED).
		Lamp.Point->SetVolumetricScatteringIntensity(static_cast<float>(
			Constant(TEXT("lights"), TEXT("NavVolumetricScattering"), AircraftFxNavVolumetricScattering)));
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
			// The flame's luminance from AfterburnerCandela, the plume light's
			// own (aircraft_look.py plume_luminance): hue x core luminance.
			const FVector Core = AircraftFxVector(Row, TEXT("plume_core_colour"));
			const FVector Tip = AircraftFxVector(Row, TEXT("plume_tip_colour"));
			Row->TryGetNumberField(TEXT("plume_luminance_nits"), Nozzle.PlumeLuminanceNits);
			if (!Core.IsNearlyZero())
			{
				Nozzle.Plume->SetVectorParameterValue(FName(AircraftFxParamCoreColour),
					FLinearColor(Core.X, Core.Y, Core.Z, 1.0f));
				Nozzle.Plume->SetVectorParameterValue(FName(AircraftFxParamTipColour),
					FLinearColor(Tip.X, Tip.Y, Tip.Z, 1.0f));
			}
			Nozzle.Plume->SetScalarParameterValue(FName(AircraftFxParamShocks),
				static_cast<float>(Constant(TEXT("afterburner"), TEXT("Shocks"), 5.0)));
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
	// condensation-solver: the humidity test per site; the old Nz rule only when RH is unavailable.
	const bool bVapour = Condensation.Advance(ReadProperty, Record) ||
		(!Condensation.HasHumidity() && ReadProperty(TEXT("accelerations/Nz")) > Constant(TEXT("vapour"), TEXT("MinNz"), 4.0));
	const double SpeedCmS = ReadProperty(TEXT("velocities/vtrue-kts")) * AircraftFxMpsPerKnot * AircraftFxCmPerMetre;
	ContrailFrames += bContrail ? 1 : 0;
	// A contrail inside a cloud layer is inside the cloud: its opacity x
	// (1 - cover) of every layer the aircraft is in (heights above the
	// ground datum, engine Z = 0, as FFlightSimCloudLayer states).
	const double AircraftZM = Aircraft->GetActorLocation().Z / AircraftFxCmPerMetre;
	double CloudClear = 1.0;
	for (const FFlightSimCloudLayer& Layer : CloudLayers)
	{
		if (AircraftZM >= Layer.BaseMetres && AircraftZM <= Layer.TopMetres)
		{
			CloudClear *= 1.0 - FMath::Clamp(Layer.CoverFraction, 0.0, 1.0);
		}
	}
	ContrailInCloudFrames += (bContrail && CloudClear < 1.0) ? 1 : 0;
	VapourFrames += bVapour ? 1 : 0;
	for (FTrail& Trail : Trails)
	{
		const TCHAR* Group = Trail.bVapour ? TEXT("vapour") : TEXT("contrail");
		const bool bActive = Trail.bVapour ? bVapour : bContrail;
		if (!Trail.bVapour && Trail.Instance != nullptr)
		{
			Trail.Instance->SetScalarParameterValue(FName(AircraftFxParamOpacity),
				static_cast<float>(Trail.BaseOpacity * CloudClear));
		}
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
		(*ContrailRow)->SetNumberField(TEXT("contrail_in_cloud_frames"), ContrailInCloudFrames);
	}
	TSharedPtr<FJsonObject> Afterburner = MakeShared<FJsonObject>();
	Afterburner->SetNumberField(TEXT("peak_glow"), PeakAfterburner);
	double PlumeNits = 0.0;
	for (const FNozzle& Nozzle : Nozzles)
	{
		PlumeNits = FMath::Max(PlumeNits, Nozzle.PlumeLuminanceNits);
	}
	Afterburner->SetNumberField(TEXT("plume_luminance_nits_at_full_glow"), PlumeNits);
	Afterburner->SetStringField(TEXT("rule"), TEXT("glow = saturate((thrust/max - mil/max) / (1 - mil/max)) x GlowGain, ")
		TEXT("static sea-level ratings from the engine file; additive plume, hides nothing"));
	Record->SetObjectField(TEXT("afterburner"), Afterburner);
	Record->SetNumberField(TEXT("strobe_on_frames"), StrobeOnFrames);
	Record->SetNumberField(TEXT("landing_light_on_frames"), LandingOnFrames);
	// wet-airframe-canopy: the weather's wetness on the look MIDs (shading only).
	if (Weather != nullptr) { Wet.Advance(LookMids, *Weather, ReadProperty(TEXT("velocities/vtrue-kts")), ReadProperty(TEXT("simulation/sim-time-sec")), Record); }
}
