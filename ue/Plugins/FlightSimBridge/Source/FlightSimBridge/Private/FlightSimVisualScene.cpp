#include "FlightSimVisualScene.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Components/SceneComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GeoReferencingSystem.h"
#include "ImageUtils.h"
#include "MaterialDomain.h"
#include "Materials/Material.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
// W5: the scene level, its Landscape, the starfield texture.
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PrimitiveComponent.h"
#include "Engine/Level.h"
#include "Engine/LevelStreamingDynamic.h"
#include "Engine/Texture2D.h"
#include "HAL/IConsoleManager.h"
#include "Landscape.h"
#include "LandscapeInfo.h"
#include "LandscapeProxy.h"
#include "Math/Float16Color.h"
#include "Math/RandomStream.h"
#include "Misc/Parse.h"
#include "PixelFormat.h"

namespace
{
	// Named distinctly from the near-identical constant in the sibling
	// files: a unity build merges these anonymous namespaces into one
	// translation unit, where same-named definitions collide.
	constexpr double SceneCmPerMetre = 100.0;

	// S4: the sun. Every Gate 6 clause was tuned on a sun of 8.0 with no
	// unit anyone chose (light_units "unitless"); a sun in lux is recorded
	// as light_units "physical" -- the word core/capture/radiometry.py
	// PHYSICAL_LIGHT_UNITS reads back before its chain means anything.
	constexpr double SceneEngineSunUnitless = 8.0;
	const TCHAR* const ScenePhysicalLightUnits = TEXT("physical");
	const TCHAR* const SceneUnitlessLightUnits = TEXT("unitless");

	// Triangle budget for the Gate 6 offset instances: the raster is
	// decimated to at most this many vertices per side. 257^2 verts is ~130k
	// triangles per instance -- and Gate 6's measurements passed on exactly
	// this geometry, so it stays.
	constexpr int32 MaxVerticesPerSide = 257;

	// Phase 2 (contracts §10): the georeferenced instance is no longer one
	// section capped at 701 vertices per side (stride 2 on a 30 m GLO-30
	// raster = 60 m posting). It is TILED: one UProceduralMeshComponent per
	// tile of at most this many vertices a side (255 quads, ~130k
	// triangles), at the smallest stride whose triangle count fits the
	// options' budget (4 M by default: a 1276x905 raster at stride 1 is
	// 2.3 M triangles, so native 30 m posting). One component per tile,
	// not one section per tile, so each tile has its own bounds and the
	// renderer can frustum-cull it. The achieved stride and posting are
	// RECORDED (TerrainPostingMetres), never assumed.
	constexpr int32 SceneTerrainTileVerticesPerSide = 256;

	// The engine's default volumetric cloud material, the one the
	// component's own constructor loads; named here so a component that
	// came up without it can be refused BY NAME rather than drawing nothing.
	const TCHAR* const SceneDefaultCloudMaterialPath =
		TEXT("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst.m_SimpleVolumetricCloud_Inst");

	// Slope/altitude classification (Phase 6B.2). Deliberately simple and
	// stated as approximated in every manifest: rock above the slope limit,
	// snow above the sidecar's snowline where it can settle, scrub in a band
	// below the snowline, valley vegetation under it.
	//
	// The palette was CALIBRATED against rendered frames rather than derived:
	// the mesh sRGB-encodes vertex colours on store, the material reads the
	// bytes back raw, and at 5-20 km the atmosphere and fog add blue
	// in-scatter on top -- so a theoretically-correct albedo rendered navy
	// (measured) and the naive linear palette rendered mint (measured). The
	// values below are the middle that reads as rock / forest / snow in the
	// actual scene, and the classification is labeled approximated in every
	// manifest regardless.
	FLinearColor ClassifyVertex(double ElevationMetres, double SlopeDegrees,
	                            double SnowlineMetres)
	{
		const FLinearColor Snow(0.75f, 0.78f, 0.82f);
		const FLinearColor Rock(0.068f, 0.060f, 0.053f);
		const FLinearColor Scrub(0.058f, 0.068f, 0.034f);
		const FLinearColor Valley(0.030f, 0.078f, 0.022f);

		if (SnowlineMetres > 0.0 && ElevationMetres > SnowlineMetres - 150.0 &&
		    SlopeDegrees < 52.0)
		{
			// Blend across a 300 m band around the snowline so the line is a
			// transition, not a contour cut. A plain linear-space lerp: the
			// HSV route rotated olive-to-white through mint.
			const float Blend = FMath::Clamp(
				static_cast<float>((ElevationMetres - (SnowlineMetres - 150.0)) / 300.0),
				0.0f, 1.0f);
			const FLinearColor Under = SlopeDegrees > 34.0 ? Rock : Scrub;
			return FMath::Lerp(Under, Snow, Blend);
		}
		if (SlopeDegrees > 34.0)
		{
			return Rock;
		}
		if (SnowlineMetres > 0.0 && ElevationMetres > SnowlineMetres - 900.0)
		{
			return Scrub;
		}
		return Valley;
	}

	// The first scalar parameter of a material whose name contains (or,
	// when bExact, equals) Needle, case-insensitively. NAME_None when the
	// material exposes no such parameter -- the caller records "absent"
	// rather than setting a scalar that drives nothing and calling it
	// applied.
	FName FindScalarParameter(const UMaterialInterface* Material,
	                          const TCHAR* Needle, bool bExact)
	{
		if (Material == nullptr)
		{
			return NAME_None;
		}
		TArray<FMaterialParameterInfo> Infos;
		TArray<FGuid> Ids;
		Material->GetAllScalarParameterInfo(Infos, Ids);
		for (const FMaterialParameterInfo& Info : Infos)
		{
			const FString Name = Info.Name.ToString();
			const bool bMatch = bExact
				? Name.Equals(Needle, ESearchCase::IgnoreCase)
				: Name.Contains(Needle, ESearchCase::IgnoreCase);
			if (bMatch)
			{
				return Info.Name;
			}
		}
		return NAME_None;
	}

	TSharedPtr<FJsonObject> NewRecord()
	{
		return MakeShared<FJsonObject>();
	}

	// -- W5: the world engine side ------------------------------------------
	// Every /Game path here is created by scripts/ue_create_materials.py
	// (tests/test_ue_materials.py pins the two lists to each other).
	constexpr const TCHAR* SceneLandscapeMaterialPath =
		TEXT("/Game/FlightSim/M_Landscape.M_Landscape");
	constexpr const TCHAR* SceneStarfieldMaterialPath =
		TEXT("/Game/FlightSim/M_Starfield.M_Starfield");
	constexpr const TCHAR* SceneRainMaterialPath =
		TEXT("/Game/FlightSim/M_RainStreaks.M_RainStreaks");
	constexpr const TCHAR* SceneAirframePaintMaterialPath =
		TEXT("/Game/FlightSim/M_AirframePaint.M_AirframePaint");
	constexpr const TCHAR* SceneRunwayMaterialPath =
		TEXT("/Game/FlightSim/M_Runway.M_Runway");
	constexpr const TCHAR* SceneLandcoverMaterialPath =
		TEXT("/Game/FlightSim/M_LandcoverID.M_LandcoverID");
	// The parameter names the script exposes (its STARFIELD_* / RAIN_*
	// constants, pinned equal by test).
	constexpr const TCHAR* SceneStarMapParameter = TEXT("StarMap");
	constexpr const TCHAR* SceneStarIntensityParameter = TEXT("StarIntensity");
	constexpr const TCHAR* SceneRainLengthParameter = TEXT("StreakLengthPx");
	constexpr const TCHAR* SceneRainDirectionParameter = TEXT("StreakDirection");
	constexpr const TCHAR* SceneRainDensityParameter = TEXT("StreakDensity");
	constexpr const TCHAR* SceneRainPhaseParameter = TEXT("StreakPhase");
	// The cloud drift: the first VECTOR parameter of the cloud material whose
	// name contains this (the engine's material, not ours: its names are the
	// engine's); none -> look.cloud_drift_parameter by name.
	constexpr const TCHAR* SceneCloudDriftNeedle = TEXT("Wind");
	// core/scene/night.py CATALOGUE_SHA256 and the procedural law
	// (PROCEDURAL_COUNT, STAR_LIMITING_MAG, STAR_BRIGHTEST_MAG,
	// PROCEDURAL_SLOPE), restated and pinned equal by test.
	constexpr const TCHAR* SceneStarCatalogueSha256 =
		TEXT("94b0581379ef9ea49f1ce664734a06d2fbbff2d7487f926acad3e9ef0960e0d8");
	constexpr int32 SceneStarProceduralCount = 9000;
	constexpr double SceneStarLimitingMag = 6.5;
	constexpr double SceneStarBrightestMag = -1.46;
	constexpr double SceneStarProceduralSlope = 0.5;
	// A V = 0 star's illuminance above the atmosphere, lux (the usual
	// photometric zero point, 2.54e-6 lx [unverified here]); a texel holds
	// the luminance E / (texel solid angle) in cd/m^2, so StarIntensity 1
	// means one emissive unit = 1 cd/m^2 (the calibration frame measures it).
	constexpr double SceneStarZeroPointLux = 2.54e-6;
	constexpr int32 SceneStarMapWidth = 2048;
	constexpr int32 SceneStarMapHeight = 1024;
	// The sphere: 500 km, far beyond every scene and inside the atmosphere's
	// ground-to-space span only as a direction (aerial perspective applies).
	constexpr double SceneStarfieldRadiusMetres = 500000.0;
	// No moon is brighter: K&S's full moon at the zenith is 0.267 lx.
	constexpr double SceneMoonLuxMax = 1.0;

	// FIPS 180-4 SHA-256 as hex (the third per-file copy: unity builds merge
	// anonymous namespaces, so the name is this file's own).
	FString SceneSha256Hex(const uint8* Data, int64 Length)
	{
		static const uint32 K[64] = {
			0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
			0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
			0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
			0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
			0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
			0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
			0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
			0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
		uint32 H[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
		               0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
		const uint64 Bits = static_cast<uint64>(Length) * 8u;
		const int64 Padded = ((Length + 8) / 64 + 1) * 64;
		TArray<uint8> Buffer;
		Buffer.SetNumZeroed(Padded);
		FMemory::Memcpy(Buffer.GetData(), Data, Length);
		Buffer[Length] = 0x80;
		for (int32 i = 0; i < 8; ++i)
		{
			Buffer[Padded - 1 - i] = static_cast<uint8>(Bits >> (8 * i));
		}
		auto Rotr = [](uint32 X, uint32 N) { return (X >> N) | (X << (32 - N)); };
		for (int64 Chunk = 0; Chunk < Padded; Chunk += 64)
		{
			uint32 W[64];
			for (int32 i = 0; i < 16; ++i)
			{
				const uint8* P = Buffer.GetData() + Chunk + i * 4;
				W[i] = (uint32(P[0]) << 24) | (uint32(P[1]) << 16) | (uint32(P[2]) << 8) | uint32(P[3]);
			}
			for (int32 i = 16; i < 64; ++i)
			{
				const uint32 S0 = Rotr(W[i-15], 7) ^ Rotr(W[i-15], 18) ^ (W[i-15] >> 3);
				const uint32 S1 = Rotr(W[i-2], 17) ^ Rotr(W[i-2], 19) ^ (W[i-2] >> 10);
				W[i] = W[i-16] + S0 + W[i-7] + S1;
			}
			uint32 A=H[0],B=H[1],C=H[2],D=H[3],E=H[4],F=H[5],G=H[6],Hh=H[7];
			for (int32 i = 0; i < 64; ++i)
			{
				const uint32 S1 = Rotr(E,6) ^ Rotr(E,11) ^ Rotr(E,25);
				const uint32 Ch = (E & F) ^ (~E & G);
				const uint32 T1 = Hh + S1 + Ch + K[i] + W[i];
				const uint32 S0 = Rotr(A,2) ^ Rotr(A,13) ^ Rotr(A,22);
				const uint32 Maj = (A & B) ^ (A & C) ^ (B & C);
				Hh=G; G=F; F=E; E=D+T1; D=C; C=B; B=A; A=T1+S0+Maj;
			}
			H[0]+=A; H[1]+=B; H[2]+=C; H[3]+=D; H[4]+=E; H[5]+=F; H[6]+=G; H[7]+=Hh;
		}
		FString Hex;
		for (int32 i = 0; i < 8; ++i)
		{
			Hex += FString::Printf(TEXT("%08x"), H[i]);
		}
		return Hex;
	}

	TSharedPtr<FJsonObject> SceneReadJson(const FString& Path)
	{
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (FFileHelper::LoadFileToString(Text, *Path))
		{
			const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
			FJsonSerializer::Deserialize(Reader, Root);
		}
		return Root;
	}

	// A sexagesimal field of the BSC5 conversion ("06h 45m 08.9s", and the
	// declination's degree, minute and second marks, which are not ASCII
	// in that file): the three numbers in it, whatever separates them
	// (core/scene/night.py _sexagesimal's rule), signed by the first
	// character. False when the field does not hold three numbers.
	bool SceneSexagesimal(const FString& Text, bool bHours, double& Out)
	{
		TArray<double> Parts;
		FString Token;
		auto Flush = [&]()
		{
			if (!Token.IsEmpty())
			{
				Parts.Add(FCString::Atod(*Token));
				Token.Reset();
			}
		};
		for (const TCHAR Char : Text)
		{
			if (FChar::IsDigit(Char) || Char == TEXT('.'))
			{
				Token.AppendChar(Char);
			}
			else
			{
				Flush();
			}
		}
		Flush();
		if (Parts.Num() != 3)
		{
			return false;
		}
		const double Sign = Text.TrimStart().StartsWith(TEXT("-")) ? -1.0 : 1.0;
		Out = Sign * (Parts[0] + Parts[1] / 60.0 + Parts[2] / 3600.0) * (bHours ? 15.0 : 1.0);
		return true;
	}

	// Whether an actor carries a tag (a component's own tags count too for
	// the aggregate tags, so a PCG-generated component tagged by its graph is
	// found as well as one under a tagged actor).
	bool SceneHasTag(const AActor* Actor, const TCHAR* Tag)
	{
		return Actor != nullptr && Actor->ActorHasTag(FName(Tag));
	}
}

double FFlightSimVisualScene::ExposureValue100(double ApertureF, double ShutterSeconds,
                                               double Iso)
{
	// EV100 = log2(N^2 / t * 100 / ISO): core/capture/exposure.py's formula,
	// re-implemented, not imported (the test pins this expression).
	return FMath::Log2((ApertureF * ApertureF / ShutterSeconds) * (100.0 / Iso));
}

bool FFlightSimVisualScene::Build(UWorld* World,
                                  const FFlightSimVisualSceneOptions& Options,
                                  FString& Error)
{
	LookApplied = NewRecord();
	// W5: every world row starts as "not asked" and is overwritten by what
	// the scene and the world look actually drew.
	WorldApplied = NewRecord();
	BeautyOnlyActors.Reset();
	{
		for (const TCHAR* Key : {TEXT("landscape"), TEXT("imagery"), TEXT("land_cover"),
		                         TEXT("vegetation"), TEXT("buildings"), TEXT("runway"),
		                         TEXT("night"), TEXT("precipitation"), TEXT("cloud_drift")})
		{
			TSharedPtr<FJsonObject> Row = NewRecord();
			Row->SetBoolField(TEXT("asked"), false);
			Row->SetBoolField(TEXT("drawn"), false);
			WorldApplied->SetObjectField(Key, Row);
		}
		// Which of the six world materials this build has (loaded by path,
		// "loaded" or "absent"); a row that draws with one says so itself.
		TSharedPtr<FJsonObject> Materials = NewRecord();
		for (const TCHAR* Path : {SceneLandscapeMaterialPath, SceneLandcoverMaterialPath,
		                          SceneStarfieldMaterialPath, SceneRainMaterialPath,
		                          SceneAirframePaintMaterialPath, SceneRunwayMaterialPath})
		{
			Materials->SetStringField(Path,
				LoadObject<UMaterialInterface>(nullptr, Path) != nullptr ? TEXT("loaded") : TEXT("absent"));
		}
		WorldApplied->SetObjectField(TEXT("materials"), Materials);
	}

	// -- sun ---------------------------------------------------------------
	// One light. §6.6: Atmosphere Sun Light true, and it must cast shadows --
	// "its absence was a major tell in the old footage" is about the
	// aircraft's shadow specifically.
	Sun = World->SpawnActor<ADirectionalLight>();
	Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
	Sun->SetActorRotation(Options.SunRotation);
	UDirectionalLightComponent* SunLight =
		Cast<UDirectionalLightComponent>(Sun->GetLightComponent());
	// S4: the sun in lux when the card (or -sun-lux=) states one; else the
	// unitless 8.0 of every Gate 6 measurement, byte-identical.
	const bool bPhysicalSun = Options.SunLux > 0.0;
	const double SunIntensity = bPhysicalSun ? Options.SunLux : SceneEngineSunUnitless;
	SunLight->SetIntensity(static_cast<float>(SunIntensity));
	SunLight->SetAtmosphereSunLight(true);
	SunLight->SetCastShadows(Options.bDynamicShadows);
	// The procedural terrain is a Movable non-Nanite mesh, so the cascade
	// settings below are what shadow it when virtual shadow maps are off
	// (VALIDITY §2.13); with r.Shadow.Virtual.Enable=1 (DefaultEngine.ini,
	// Look lane part 1) the renderer decides, and render.json's
	// render_settings records which value it found. Push the dynamic
	// shadow range far enough to cover the near ridge.
	SunLight->SetDynamicShadowDistanceMovableLight(20000.0f * SceneCmPerMetre);
	SunLight->SetDynamicShadowCascades(6);
	{
		TSharedPtr<FJsonObject> SunRecord = NewRecord();
		SunRecord->SetNumberField(TEXT("sun_elevation_deg"), -Options.SunRotation.Pitch);
		SunRecord->SetNumberField(TEXT("engine_sun_yaw_deg"), Options.SunRotation.Yaw);
		SunRecord->SetStringField(TEXT("component"), TEXT("ADirectionalLight (existing sun)"));
		SunRecord->SetBoolField(TEXT("cast_shadows"), Options.bDynamicShadows);
		// S4: what the light was set to, and in which unit.
		SunRecord->SetNumberField(TEXT("intensity"), SunIntensity);
		SunRecord->SetStringField(TEXT("light_units"),
		                          bPhysicalSun ? ScenePhysicalLightUnits : SceneUnitlessLightUnits);
		if (bPhysicalSun)
		{
			SunRecord->SetNumberField(TEXT("lux"), Options.SunLux);
			SunRecord->SetStringField(TEXT("lux_source"), Options.SunLuxSource);
			SunRecord->SetStringField(TEXT("set_by"),
				TEXT("UDirectionalLightComponent::SetIntensity(lux): a directional light's intensity is lux"));
			SunRecord->SetStringField(TEXT("old_exposure_bias_scale"),
				TEXT("-exposure-bias 9.5 / 10.5 / 11.0 were tuned on the unitless 8.0 sun: the OLD scale, ")
				TEXT("re-pinned on the box with Gate 6's four exposure clauses"));
			SunRecord->SetStringField(TEXT("not_claimed"),
				TEXT("the illuminance at the surface after the sky atmosphere's transmittance (applied on ")
				TEXT("top of the stated lux by an atmosphere sun light): the calibration frame measures the ")
				TEXT("chain with it off"));
		}
		else
		{
			SunRecord->SetStringField(TEXT("note"),
				TEXT("the unitless 8.0 sun every Gate 6 clause was tuned on; no luminance chain describes it"));
		}
		LookApplied->SetObjectField(TEXT("sun"), SunRecord);
	}

	// -- atmosphere --------------------------------------------------------
	AActor* AtmosphereActor = World->SpawnActor<AActor>();
	Atmosphere =
		NewObject<USkyAtmosphereComponent>(AtmosphereActor, TEXT("SkyAtmosphere"));
	AtmosphereActor->SetRootComponent(Atmosphere);
	Atmosphere->SetMobility(EComponentMobility::Movable);
	// §6.6 gotcha 2: Planet Top at Component Transform, with the component at
	// actual ground level, so the haze transition does not cut a hard line.
	Atmosphere->TransformMode =
		ESkyAtmosphereTransformMode::PlanetTopAtComponentTransform;
	AtmosphereActor->SetActorLocation(FVector::ZeroVector);
	// §6.6: real Earth values -- a shrunk planet makes altitude falloff wrong.
	Atmosphere->BottomRadius = 6360.0f;      // km
	Atmosphere->AtmosphereHeight = 60.0f;    // km
	// §6.6: multiscattering on; sky going black away from the sun is a tell.
	Atmosphere->MultiScatteringFactor = 1.0f;
	// §6.6 gotcha 1: transmittance evaluated from the camera's position, or
	// the ground blacks out at altitude from georeferenced origins.
	Atmosphere->TransmittanceMinLightElevationAngle = 90.0f;
	// Phase 2 aerosol (contracts §5.4 row 1): the Mie scattering scale,
	// applied ONLY when the options carry one (the -aerosol= probe). The
	// card's look.aerosol is recorded by the commandlet and left unapplied:
	// the fog row already carries that extinction (double count), and the
	// value it takes for the Phase 10 default fog is in the hundreds.
	{
		TSharedPtr<FJsonObject> AerosolRecord = NewRecord();
		AerosolRecord->SetStringField(TEXT("component"),
			TEXT("USkyAtmosphereComponent::MieScatteringScale"));
		if (Options.AerosolMieScale >= 0.0)
		{
			Atmosphere->SetMieScatteringScale(static_cast<float>(Options.AerosolMieScale));
			AerosolRecord->SetNumberField(TEXT("mie_scattering_scale"), Options.AerosolMieScale);
			AerosolRecord->SetBoolField(TEXT("applied"), true);
		}
		else
		{
			AerosolRecord->SetNumberField(TEXT("mie_scattering_scale"), 1.0);
			AerosolRecord->SetBoolField(TEXT("applied"), false);
			AerosolRecord->SetStringField(TEXT("note"),
				TEXT("engine default 1.0; the fog row carries the extinction "
				     "(applying look.aerosol as well double counts)"));
		}
		LookApplied->SetObjectField(TEXT("aerosol"), AerosolRecord);
	}
	Atmosphere->RegisterComponent();

	// -- height fog --------------------------------------------------------
	// §6.6: the primary long-range haze. Max opacity below 1 so distant
	// terrain keeps faint detail; a start distance so the foreground is not
	// milky; a low falloff so the haze reaches flight altitude. Density is an
	// option because the showcase sweeps clear against hazy; both values are
	// recorded in the manifest.
	AExponentialHeightFog* Fog = World->SpawnActor<AExponentialHeightFog>();
	UExponentialHeightFogComponent* FogComponent = Fog->GetComponent();
	FogComponent->SetMobility(EComponentMobility::Movable);
	FogComponent->SetFogDensity(Options.FogDensity);
	FogComponent->SetFogHeightFalloff(0.0002f);
	FogComponent->SetFogMaxOpacity(0.92f);
	FogComponent->SetStartDistance(1500.0f * SceneCmPerMetre);
	Fog->SetActorLocation(FVector(0, 0, 0));
	{
		TSharedPtr<FJsonObject> FogRecord = NewRecord();
		FogRecord->SetNumberField(TEXT("fog_density"), Options.FogDensity);
		FogRecord->SetStringField(TEXT("component"),
			TEXT("UExponentialHeightFogComponent::FogDensity"));
		FogRecord->SetNumberField(TEXT("fog_height_falloff"), 0.0002);
		FogRecord->SetNumberField(TEXT("fog_max_opacity"), 0.92);
		FogRecord->SetNumberField(TEXT("start_distance_m"), 1500.0);
		LookApplied->SetObjectField(TEXT("fog"), FogRecord);
	}

	// -- physical sky ------------------------------------------------------
	// Everything above stays as §6.6 built it; the plan only re-aims and
	// re-lights it and adds the night sky. Legacy renders never get here.
	if (Options.SkyPlan != nullptr &&
	    !PhysicalSky.Build(World, *Options.SkyPlan, Sun, Atmosphere, FogComponent, Error))
	{
		return false;
	}

	// -- sky light ---------------------------------------------------------
	ASkyLight* Sky = World->SpawnActor<ASkyLight>();
	USkyLightComponent* SkyComponent = Sky->GetLightComponent();
	SkyComponent->SetMobility(EComponentMobility::Movable);
	// Real Time Capture per §6.6, so the sky light follows the atmosphere
	// rather than a flat ambient term.
	SkyComponent->SetRealTimeCapture(true);
	SkyComponent->SetIntensity(1.0f);

	// -- clouds (Phase 2, contracts §5.4 row 2) ------------------------------
	if (!BuildClouds(World, Options, Error))
	{
		return false;
	}

	// -- what this phase does NOT draw: recorded, not silent ---------------
	{
		TSharedPtr<FJsonObject> DriftRecord = NewRecord();
		DriftRecord->SetNumberField(TEXT("cloud_drift_mps"), Options.CloudDriftMps);
		DriftRecord->SetNumberField(TEXT("cloud_drift_from_deg"), Options.CloudDriftFromDeg);
		DriftRecord->SetBoolField(TEXT("applied"), false);
		DriftRecord->SetStringField(TEXT("note"),
			TEXT("not modelled this phase: no per-tick wind offset is written to "
			     "the cloud material"));
		LookApplied->SetObjectField(TEXT("cloud_drift"), DriftRecord);

		TSharedPtr<FJsonObject> NightRecord = NewRecord();
		NightRecord->SetBoolField(TEXT("stars_requested"), Options.bStarsRequested);
		NightRecord->SetBoolField(TEXT("moon_requested"), Options.bMoonRequested);
		NightRecord->SetStringField(TEXT("stars"), TEXT("not modelled"));
		NightRecord->SetStringField(TEXT("moon"), TEXT("not modelled"));
		NightRecord->SetStringField(TEXT("night_sky"),
			TEXT("the existing sun below the horizon only (sky atmosphere twilight)"));
		LookApplied->SetObjectField(TEXT("night"), NightRecord);

		TArray<TSharedPtr<FJsonValue>> NotClaimed;
		for (const TCHAR* Name : {TEXT("precipitation_particles"), TEXT("moon"),
		                          TEXT("stars"), TEXT("cloud_drift"), TEXT("sea_state"),
		                          TEXT("foliage_sway")})
		{
			NotClaimed.Add(MakeShared<FJsonValueString>(Name));
		}
		LookApplied->SetArrayField(TEXT("not_claimed"), NotClaimed);
	}

	// -- W5: the world look the card asks for (the moon, the stars, the cloud
	// drift); overwrites the rows above that it draws. A card without a look
	// block leaves them exactly as they were.
	if (!BuildWorldLook(World, Options, Error))
	{
		return false;
	}

	// -- visible ground ----------------------------------------------------
	// Gate 6's scene: the plain the aircraft's shadow lands on, at Z=0.
	// Georeferenced scenes get their backstop plane after the raster loads,
	// below its minimum elevation -- a 100 km plane at the origin's height
	// would bury the real valley floors.
	if (!Options.bGeoreferenced)
	{
		UStaticMesh* PlaneMesh = LoadObject<UStaticMesh>(
			nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
		if (PlaneMesh == nullptr)
		{
			Error = TEXT("/Engine/BasicShapes/Plane.Plane did not load");
			return false;
		}
		AActor* Ground = World->SpawnActor<AActor>();
		UStaticMeshComponent* GroundMesh =
			NewObject<UStaticMeshComponent>(Ground, TEXT("VisibleGround"));
		Ground->SetRootComponent(GroundMesh);
		GroundMesh->SetMobility(EComponentMobility::Movable);
		GroundMesh->SetStaticMesh(PlaneMesh);
		GroundMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		GroundMesh->RegisterComponent();
		Ground->SetActorLocation(FVector(0.0, 0.0, 0.0));
		// The engine plane is 1 m; 100 km on a side reaches past the far ridge.
		Ground->SetActorScale3D(FVector(100000.0, 100000.0, 1.0));
	}

	// Precipitation is applied to the georeferenced terrain material below;
	// until (and unless) that runs, the record says it drove nothing.
	{
		TSharedPtr<FJsonObject> PrecipRecord = NewRecord();
		PrecipRecord->SetStringField(TEXT("precipitation"), Options.Precipitation);
		PrecipRecord->SetNumberField(TEXT("wetness"), Options.Wetness);
		PrecipRecord->SetBoolField(TEXT("particles"), false);
		PrecipRecord->SetStringField(TEXT("particles_note"),
			TEXT("not drawn this phase: no Niagara rain/snow asset exists in ue/Content"));
		PrecipRecord->SetStringField(TEXT("wetness_parameter"), TEXT("absent"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"),
			TEXT("nothing: no terrain material instance in this scene"));
		LookApplied->SetObjectField(TEXT("precipitation"), PrecipRecord);
	}

	// -- terrain -----------------------------------------------------------
	// W5: a scene document names its own bake (bake.stem); -terrain= given
	// beside it must be the same bake, which the sha checks below enforce.
	FString TerrainPath = Options.TerrainPath;
	SceneDocument.Reset();
	if (!Options.SceneDocumentPath.IsEmpty())
	{
		if (!Options.bGeoreferenced)
		{
			Error = FString::Printf(
				TEXT("world.scene_missing: -scene=%s loads a Landscape at its true position, which ")
				TEXT("only the georeferenced visual scene has (-Visual -GeorefTerrain)"),
				*Options.SceneDocumentPath);
			return false;
		}
		SceneDocument = SceneReadJson(Options.SceneDocumentPath);
		const TSharedPtr<FJsonObject>* Bake = nullptr;
		FString BakeStem;
		if (!SceneDocument.IsValid() ||
		    !SceneDocument->TryGetObjectField(TEXT("bake"), Bake) || Bake == nullptr ||
		    !(*Bake)->TryGetStringField(TEXT("stem"), BakeStem))
		{
			Error = FString::Printf(
				TEXT("world.scene_missing: the scene document %s is absent or names no bake ")
				TEXT("(scripts/ue_build_scene.py writes it beside the scene level)"),
				*Options.SceneDocumentPath);
			return false;
		}
		if (TerrainPath.IsEmpty())
		{
			TerrainPath = BakeStem;
		}
	}
	if (TerrainPath.IsEmpty())
	{
		UE_LOG(LogFlightSimRender, Warning,
		       TEXT("no terrain heightfield given; the terrain clauses of "
		            "Gate 6 cannot be met by this render"));
		return true;
	}

	if (!Terrain.Load(TerrainPath, Error))
	{
		return false;
	}
	TerrainSha256 = Terrain.Sha256;
	TerrainCrs = Terrain.Crs;
	TerrainName = Terrain.Name;

	uint16 Peak = 0;
	int32 PeakIndex = 0;
	for (int32 i = 0; i < Terrain.Samples.Num(); ++i)
	{
		if (Terrain.Samples[i] > Peak) { Peak = Terrain.Samples[i]; PeakIndex = i; }
	}
	TerrainPeakMetres = Peak * Terrain.ScaleMetres + Terrain.OffsetMetres;
	const int32 PeakRow = PeakIndex / Terrain.Width;
	const int32 PeakColumn = PeakIndex % Terrain.Width;

	if (Options.bGeoreferenced)
	{
		if (Options.GeoReferencing == nullptr)
		{
			Error = TEXT("georeferenced terrain needs the scenario world's "
			             "AGeoReferencingSystem, and none was passed");
			return false;
		}
		if (Terrain.Crs.IsEmpty() || !Terrain.bProjected)
		{
			Error = FString::Printf(
				TEXT("'%s' carries no projected CRS; it cannot be placed at a ")
				TEXT("true position. Bake it through the DEM pipeline."),
				*TerrainPath);
			return false;
		}
		// W5: the scene level's Landscape in place of the procedural tiles.
		if (SceneDocument.IsValid() ? !LoadSceneLevel(World, Options, Error)
		                            : !BuildGeoreferencedTerrain(World, Options, Error))
		{
			return false;
		}
		// The raster peak's true engine position, for the manifest landmark.
		// Projected AFTER the terrain build, which is what aligns the
		// georeferencing system's projected CRS with the raster's -- a calm
		// card never told the scenario world the CRS, and projecting through
		// the default put the landmark tens of kilometres wrong (measured:
		// the summit landmark of a calm Matterhorn card reported bearings no
		// 4000er occupies).
		const double PeakX = Terrain.OriginXMetres + PeakColumn * Terrain.PixelSizeMetres;
		const double PeakY = Terrain.OriginYMetres - PeakRow * Terrain.PixelSizeMetres;
		Options.GeoReferencing->ProjectedToEngine(
			FVector(PeakX, PeakY, TerrainPeakMetres), NearPeakWorldCm);
		FarPeakWorldCm = FVector::ZeroVector;

		// Beyond the raster's 40 km the world would otherwise be empty
		// atmosphere, which reads as ocean around an island. A matte plane
		// just under the raster's lowest elevation stands in for the
		// surrounding lowlands -- scenery, labeled as such by the manifest's
		// terrain extent; it carries no collision and no claim.
		UStaticMesh* PlaneMesh = LoadObject<UStaticMesh>(
			nullptr, TEXT("/Engine/BasicShapes/Plane.Plane"));
		if (PlaneMesh != nullptr)
		{
			AActor* Backstop = World->SpawnActor<AActor>();
			UStaticMeshComponent* BackstopMesh =
				NewObject<UStaticMeshComponent>(Backstop, TEXT("DistantGround"));
			Backstop->SetRootComponent(BackstopMesh);
			BackstopMesh->SetMobility(EComponentMobility::Movable);
			BackstopMesh->SetStaticMesh(PlaneMesh);
			BackstopMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			BackstopMesh->RegisterComponent();
			// Origin altitude is the spec's terrain elevation, so engine Z of
			// an MSL height h is (h - origin altitude), near the origin.
			const double MinElevation = Terrain.OffsetMetres;
			FVector OriginEngine;
			Options.GeoReferencing->GeographicToEngine(
				FGeographicCoordinates(Options.GeoReferencing->OriginLongitude,
				                       Options.GeoReferencing->OriginLatitude,
				                       MinElevation - 40.0),
				OriginEngine);
			Backstop->SetActorLocation(OriginEngine);
			Backstop->SetActorScale3D(FVector(400000.0, 400000.0, 1.0));
		}
	}
	else
	{
		auto PeakWorld = [&](const FVector2D& OriginMetres)
		{
			return FVector((OriginMetres.X + PeakColumn * Terrain.PixelSizeMetres) * SceneCmPerMetre,
			               (OriginMetres.Y + (Terrain.Height - 1 - PeakRow) * Terrain.PixelSizeMetres) * SceneCmPerMetre,
			               TerrainPeakMetres * SceneCmPerMetre);
		};
		NearPeakWorldCm = PeakWorld(Options.NearTerrainOriginMetres);
		FarPeakWorldCm = PeakWorld(Options.FarTerrainOriginMetres);

		if (!BuildTerrainInstance(World, TEXT("TerrainNear"),
		                          Options.NearTerrainOriginMetres, Error) ||
		    !BuildTerrainInstance(World, TEXT("TerrainFar"),
		                          Options.FarTerrainOriginMetres, Error))
		{
			return false;
		}
	}
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("terrain %dx%d at %.0f m/px, elevations %.0f..%.0f m, sha %s%s"),
	       Terrain.Width, Terrain.Height, Terrain.PixelSizeMetres,
	       Terrain.OffsetMetres, TerrainPeakMetres, *TerrainSha256.Left(12),
	       Options.bGeoreferenced ? TEXT(" (georeferenced)") : TEXT(""));
	return true;
}

bool FFlightSimVisualScene::BuildClouds(UWorld* World,
                                        const FFlightSimVisualSceneOptions& Options,
                                        FString& Error)
{
	TSharedPtr<FJsonObject> CloudRecord = NewRecord();
	CloudRecord->SetStringField(TEXT("component"),
		TEXT("UVolumetricCloudComponent (LayerBottomAltitude / LayerHeight; "
		     "coverage through the cloud material)"));
	CloudRecord->SetNumberField(TEXT("layers_requested"), Options.CloudLayers.Num());
	if (Options.CloudLayers.Num() == 0)
	{
		// No cloud component at all: the scene is byte-identical to Phase
		// 10's for every card without a cloud layer.
		CloudRecord->SetBoolField(TEXT("drawn"), false);
		LookApplied->SetObjectField(TEXT("clouds"), CloudRecord);
		return true;
	}

	const FFlightSimCloudLayer& Layer = Options.CloudLayers[0];
	if (!(Layer.CoverFraction >= 0.0 && Layer.CoverFraction <= 1.0) ||
	    !(Layer.TopMetres > Layer.BaseMetres))
	{
		Error = FString::Printf(
			TEXT("look.clouds: layer cover %.3f (0..1) with base %.0f m and top %.0f m ")
			TEXT("(top must exceed base) cannot be drawn"),
			Layer.CoverFraction, Layer.BaseMetres, Layer.TopMetres);
		return false;
	}

	AActor* CloudActor = World->SpawnActor<AActor>();
	Clouds = NewObject<UVolumetricCloudComponent>(CloudActor, TEXT("VolumetricCloud"));
	CloudActor->SetRootComponent(Clouds);
	Clouds->SetMobility(EComponentMobility::Movable);
	CloudActor->SetActorLocation(FVector::ZeroVector);
	// Layer geometry in km above the planet surface -- the atmosphere's
	// planet top sits at this scene's Z = 0 (PlanetTopAtComponentTransform,
	// spec terrain_elevation_m), so base_m is height above that datum.
	Clouds->SetLayerBottomAltitude(static_cast<float>(Layer.BaseMetres / 1000.0));
	Clouds->SetLayerHeight(static_cast<float>((Layer.TopMetres - Layer.BaseMetres) / 1000.0));

	// The engine's default cloud material: the component's constructor
	// loads it; a build where it did not is refused by name, because a
	// cloud component with no material draws nothing while "clouds: on"
	// would be recorded.
	UMaterialInterface* CloudMaterial = Clouds->Material;
	if (CloudMaterial == nullptr)
	{
		CloudMaterial = LoadObject<UMaterialInterface>(nullptr, SceneDefaultCloudMaterialPath);
	}
	if (CloudMaterial == nullptr)
	{
		Error = FString::Printf(
			TEXT("look.clouds: the engine's default volumetric cloud material %s did not ")
			TEXT("load; refusing to record a cloud layer that draws nothing"),
			SceneDefaultCloudMaterialPath);
		return false;
	}
	// Coverage goes through the material. The default material's parameter
	// names are the engine's, not this file's: the first scalar parameter
	// whose name contains "cover" is set to the layer's cover fraction and
	// its name recorded; when the material exposes none, that is recorded
	// as "absent" and only the layer geometry is applied -- stated, so the
	// Gate 6 cover clause grades a known state rather than a guess.
	const FName CoverParameter = FindScalarParameter(CloudMaterial, TEXT("cover"), false);
	UMaterialInstanceDynamic* CloudInstance = UMaterialInstanceDynamic::Create(CloudMaterial, World);
	if (CoverParameter != NAME_None)
	{
		CloudInstance->SetScalarParameterValue(CoverParameter,
		                                       static_cast<float>(Layer.CoverFraction));
		CloudRecord->SetStringField(TEXT("cover_parameter"), CoverParameter.ToString());
	}
	else
	{
		CloudRecord->SetStringField(TEXT("cover_parameter"), TEXT("absent"));
		UE_LOG(LogFlightSimRender, Warning,
		       TEXT("look.clouds: the cloud material %s exposes no scalar parameter named ")
		       TEXT("*cover*; the layer geometry is applied, the cover fraction is NOT"),
		       *CloudMaterial->GetPathName());
	}
	Clouds->SetMaterial(CloudInstance);
	Clouds->RegisterComponent();
	// W5: the instance and its drift parameter are kept for AdvanceWorld: the
	// first VECTOR parameter whose name contains SceneCloudDriftNeedle (the
	// engine material's own name, recorded); NAME_None when it exposes none,
	// which BuildWorldLook refuses (look.cloud_drift_parameter) only when the
	// card asks for a drift.
	CloudMaterialInstance = CloudInstance;
	CloudDriftParameter = NAME_None;
	{
		TArray<FMaterialParameterInfo> VectorInfos;
		TArray<FGuid> VectorIds;
		CloudMaterial->GetAllVectorParameterInfo(VectorInfos, VectorIds);
		for (const FMaterialParameterInfo& Info : VectorInfos)
		{
			if (Info.Name.ToString().Contains(SceneCloudDriftNeedle, ESearchCase::IgnoreCase))
			{
				CloudDriftParameter = Info.Name;
				break;
			}
		}
		CloudRecord->SetStringField(TEXT("drift_parameter"),
			CloudDriftParameter != NAME_None ? CloudDriftParameter.ToString() : FString(TEXT("absent")));
	}

	// Cloud shadows on the directional light (contracts §5.4: "cloud shadows
	// on"): the sun's own cloud shadow map, so the terrain darkens under the
	// layer. Whether it does is the Gate 6 cloud clause's measurement.
	UDirectionalLightComponent* SunLight =
		Sun != nullptr ? Cast<UDirectionalLightComponent>(Sun->GetLightComponent()) : nullptr;
	if (SunLight != nullptr)
	{
		SunLight->SetCastCloudShadows(true);
		SunLight->SetCloudShadowStrength(1.0f);
	}

	CloudRecord->SetBoolField(TEXT("drawn"), true);
	CloudRecord->SetNumberField(TEXT("cover"), Layer.CoverFraction);
	CloudRecord->SetNumberField(TEXT("base_m"), Layer.BaseMetres);
	CloudRecord->SetNumberField(TEXT("top_m"), Layer.TopMetres);
	CloudRecord->SetNumberField(TEXT("layer_bottom_altitude_km"), Layer.BaseMetres / 1000.0);
	CloudRecord->SetNumberField(TEXT("layer_height_km"),
	                            (Layer.TopMetres - Layer.BaseMetres) / 1000.0);
	CloudRecord->SetStringField(TEXT("base_datum"),
		TEXT("engine Z=0 (the spec's terrain_elevation_m; planet top at the "
		     "atmosphere component)"));
	CloudRecord->SetStringField(TEXT("material"), CloudMaterial->GetPathName());
	CloudRecord->SetBoolField(TEXT("cloud_shadows"), SunLight != nullptr);
	CloudRecord->SetNumberField(TEXT("layers_drawn"), 1);
	if (Options.CloudLayers.Num() > 1)
	{
		CloudRecord->SetStringField(TEXT("note"),
			TEXT("one UVolumetricCloudComponent draws one layer; layers beyond the "
			     "first are recorded, not drawn"));
	}
	LookApplied->SetObjectField(TEXT("clouds"), CloudRecord);
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("clouds: cover %.2f, base %.0f m, top %.0f m, cover parameter %s, ")
	       TEXT("cloud shadows on"),
	       Layer.CoverFraction, Layer.BaseMetres, Layer.TopMetres,
	       CoverParameter != NAME_None ? *CoverParameter.ToString() : TEXT("absent"));
	return true;
}

UMaterialInterface* FFlightSimVisualScene::ApplyWetness(
	UWorld* World, UMaterialInterface* Material,
	const FFlightSimVisualSceneOptions& Options)
{
	TSharedPtr<FJsonObject> PrecipRecord = NewRecord();
	PrecipRecord->SetStringField(TEXT("precipitation"), Options.Precipitation);
	PrecipRecord->SetNumberField(TEXT("wetness"), Options.Wetness);
	PrecipRecord->SetBoolField(TEXT("particles"), false);
	PrecipRecord->SetStringField(TEXT("particles_note"),
		TEXT("not drawn this phase: no Niagara rain/snow asset exists in ue/Content"));
	PrecipRecord->SetStringField(TEXT("component"),
		TEXT("Wetness scalar on the georeferenced terrain material instance"));

	UMaterialInterface* Result = Material;
	if (Options.Wetness <= 0.0)
	{
		// Dry: the material is untouched (byte-identical to Phase 10).
		PrecipRecord->SetStringField(TEXT("wetness_parameter"), TEXT("not set (dry)"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"), TEXT("nothing (wetness 0)"));
	}
	else
	{
		// A scalar set on a material that exposes no such parameter drives
		// nothing; that state is recorded as "absent", never as applied.
		const FName Parameter = FindScalarParameter(Material, TEXT("Wetness"), true);
		UMaterialInstanceDynamic* Instance = Cast<UMaterialInstanceDynamic>(Material);
		if (Instance == nullptr)
		{
			Instance = UMaterialInstanceDynamic::Create(Material, World);
		}
		Instance->SetScalarParameterValue(TEXT("Wetness"), static_cast<float>(Options.Wetness));
		Result = Instance;
		PrecipRecord->SetStringField(TEXT("wetness_parameter"),
			Parameter != NAME_None ? *Parameter.ToString() : TEXT("absent"));
		PrecipRecord->SetStringField(TEXT("wetness_applied_to"),
			Parameter != NAME_None
				? TEXT("TerrainGeoreferenced material instance")
				: TEXT("TerrainGeoreferenced material instance, which exposes no "
				       "Wetness parameter: the scalar drives nothing"));
		if (Parameter == NAME_None)
		{
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("precipitation '%s': the terrain material %s exposes no 'Wetness' ")
			       TEXT("scalar; wetness %.2f was set on the instance and drives nothing"),
			       *Options.Precipitation, *Material->GetPathName(), Options.Wetness);
		}
	}
	LookApplied->SetObjectField(TEXT("precipitation"), PrecipRecord);
	return Result;
}

bool FFlightSimVisualScene::BuildTerrainInstance(UWorld* World, const FString& Name,
                                                 const FVector2D& OriginMetres,
                                                 FString& Error)
{
	const int32 Stride = FMath::Max(1,
		FMath::DivideAndRoundUp(FMath::Max(Terrain.Width, Terrain.Height),
		                        MaxVerticesPerSide));
	const int32 Columns = (Terrain.Width - 1) / Stride + 1;
	const int32 Rows = (Terrain.Height - 1) / Stride + 1;

	auto ElevationCm = [this](int32 Row, int32 Column) -> double
	{
		return Terrain.SampleMetres(Row, Column) * SceneCmPerMetre;
	};

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	Vertices.Reserve(Rows * Columns);
	Normals.Reserve(Rows * Columns);
	UV0.Reserve(Rows * Columns);

	// Row 0 of the raster is the northernmost (core/terrain/heightfield.py);
	// engine +Y is north, so row r sits at origin_y + (RasterHeight-1-r)*pixel.
	for (int32 Row = 0; Row < Terrain.Height; Row += Stride)
	{
		for (int32 Column = 0; Column < Terrain.Width; Column += Stride)
		{
			const double X = (OriginMetres.X + Column * Terrain.PixelSizeMetres) * SceneCmPerMetre;
			const double Y = (OriginMetres.Y +
				(Terrain.Height - 1 - Row) * Terrain.PixelSizeMetres) * SceneCmPerMetre;
			Vertices.Add(FVector(X, Y, ElevationCm(Row, Column)));
			UV0.Add(FVector2D(Column / double(Terrain.Width),
			                  Row / double(Terrain.Height)));

			// Central-difference normal from the full-resolution raster, so
			// shading responds to slopes the decimated mesh smooths over.
			const int32 RowN = FMath::Max(Row - Stride, 0);
			const int32 RowS = FMath::Min(Row + Stride, Terrain.Height - 1);
			const int32 ColW = FMath::Max(Column - Stride, 0);
			const int32 ColE = FMath::Min(Column + Stride, Terrain.Width - 1);
			const double DzDx = (ElevationCm(Row, ColE) - ElevationCm(Row, ColW)) /
				((ColE - ColW) * Terrain.PixelSizeMetres * SceneCmPerMetre);
			const double DzDy = (ElevationCm(RowN, Column) - ElevationCm(RowS, Column)) /
				((RowS - RowN) * Terrain.PixelSizeMetres * SceneCmPerMetre);
			Normals.Add(FVector(-DzDx, -DzDy, 1.0).GetSafeNormal());
		}
	}

	TArray<int32> Triangles;
	Triangles.Reserve((Rows - 1) * (Columns - 1) * 6);
	for (int32 Row = 0; Row < Rows - 1; ++Row)
	{
		for (int32 Column = 0; Column < Columns - 1; ++Column)
		{
			const int32 A = Row * Columns + Column;
			const int32 B = A + 1;
			const int32 C = A + Columns;
			const int32 D = C + 1;
			// Wound so the face normal comes out +Z: row index increases
			// SOUTHWARD (raster row 0 is northernmost), so the naive A,B,C
			// order faces down and the terrain is invisible from above --
			// which is exactly how the first probe frame came out.
			Triangles.Append({A, C, B, B, C, D});
		}
	}

	AActor* TerrainActor = World->SpawnActor<AActor>();
	UProceduralMeshComponent* Mesh =
		NewObject<UProceduralMeshComponent>(TerrainActor, *Name);
	TerrainActor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UV0,
	                                    {}, {}, false /* no collision */);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(true);
	Mesh->SetMaterial(0, UMaterial::GetDefaultMaterial(EMaterialDomain::MD_Surface));
	Mesh->RegisterComponent();
	TerrainActor->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("%s: %d verts, %d triangles (stride %d) at (%.0f, %.0f) m"),
	       *Name, Vertices.Num(), Triangles.Num() / 3, Stride,
	       OriginMetres.X, OriginMetres.Y);
	return true;
}

bool FFlightSimVisualScene::BuildGeoreferencedTerrain(
	UWorld* World, const FFlightSimVisualSceneOptions& Options, FString& Error)
{
	if (Terrain.Width < 2 || Terrain.Height < 2)
	{
		Error = FString::Printf(TEXT("terrain raster %dx%d has no quads to triangulate"),
		                        Terrain.Width, Terrain.Height);
		return false;
	}
	// Phase 2 (contracts §10): the smallest stride whose triangle count fits
	// the stated budget -- native posting (stride 1) on every raster the
	// budget admits, and the ACHIEVED stride recorded, never the intended.
	const int32 Budget = FMath::Max(1, Options.TerrainTriangleBudget);
	int32 Stride = 1;
	for (;; ++Stride)
	{
		const int64 StrideColumns = (Terrain.Width - 1) / Stride + 1;
		const int64 StrideRows = (Terrain.Height - 1) / Stride + 1;
		const int64 StrideTriangles = (StrideColumns - 1) * (StrideRows - 1) * 2;
		if (StrideTriangles <= Budget || Stride >= FMath::Max(Terrain.Width, Terrain.Height))
		{
			break;
		}
	}
	const int32 Columns = (Terrain.Width - 1) / Stride + 1;
	const int32 Rows = (Terrain.Height - 1) / Stride + 1;
	TerrainStride = Stride;
	TerrainPostingMetres = Stride * Terrain.PixelSizeMetres;

	UMaterialInterface* Material =
		UMaterial::GetDefaultMaterial(EMaterialDomain::MD_Surface);
	const bool bImagery = !Options.ImagerySidecarPath.IsEmpty();
	if (bImagery)
	{
		// True-colour drape (Phase 7 1.1). The sidecar names the verified
		// PNG and carries the provenance the manifest must repeat; a drape
		// that cannot be loaded refuses the run rather than silently
		// rendering the approximated classification under an imagery label.
		FString SidecarText;
		if (!FFileHelper::LoadFileToString(SidecarText, *Options.ImagerySidecarPath))
		{
			Error = FString::Printf(TEXT("imagery sidecar '%s' unreadable"),
			                        *Options.ImagerySidecarPath);
			return false;
		}
		TSharedPtr<FJsonObject> Sidecar;
		const TSharedRef<TJsonReader<>> Reader =
			TJsonReaderFactory<>::Create(SidecarText);
		if (!FJsonSerializer::Deserialize(Reader, Sidecar) || !Sidecar.IsValid())
		{
			Error = FString::Printf(TEXT("imagery sidecar '%s' is not valid JSON"),
			                        *Options.ImagerySidecarPath);
			return false;
		}
		const TSharedPtr<FJsonObject>* TextureInfo = nullptr;
		if (!Sidecar->TryGetObjectField(TEXT("texture"), TextureInfo))
		{
			Error = TEXT("imagery sidecar has no texture block");
			return false;
		}
		ImageryFile = (*TextureInfo)->GetStringField(TEXT("file"));
		ImagerySha256 = (*TextureInfo)->GetStringField(TEXT("sha256"));
		ImageryLicense = Sidecar->GetStringField(TEXT("license"));
		ImageryAttribution = Sidecar->GetStringField(TEXT("attribution"));
		ImageryDataset = Sidecar->GetStringField(TEXT("dataset"));

		const FString PngPath = FPaths::Combine(
			FPaths::GetPath(Options.ImagerySidecarPath), ImageryFile);
		UTexture2D* Texture = FImageUtils::ImportFileAsTexture2D(PngPath);
		if (Texture == nullptr)
		{
			Error = FString::Printf(TEXT("imagery texture '%s' failed to load"),
			                        *PngPath);
			return false;
		}
		UMaterialInterface* ImageryBase = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Game/FlightSim/M_TerrainImagery.M_TerrainImagery"));
		if (ImageryBase == nullptr)
		{
			Error = TEXT(
				"/Game/FlightSim/M_TerrainImagery is missing. Run "
				"scripts/ue_create_materials.py (build-time asset step).");
			return false;
		}
		// Night lights (physical sky only): the same drape material plus
		// an emissive VIIRS layer on the same UV grid. An unrequested
		// embellishment, so a missing piece is recorded and the plain drape
		// renders -- never a silent swap of what the surface IS.
		UTexture2D* NightTexture = nullptr;
		double NightLuminance = 0.0;
		if (Options.SkyPlan != nullptr)
		{
			const FString& NightSidecar = Options.SkyPlan->NightLightsSidecarPath;
			if (NightSidecar.IsEmpty())
			{
				NightLightsNote = TEXT("none in the sky plan");
			}
			else
			{
				NightTexture = LoadNightLights(NightSidecar, NightLuminance);
				if (NightTexture != nullptr)
				{
					UMaterialInterface* NightBase = LoadObject<UMaterialInterface>(nullptr,
						TEXT("/Game/FlightSim/M_TerrainImageryNight.M_TerrainImageryNight"));
					if (NightBase == nullptr)
					{
						NightLightsNote = TEXT("/Game/FlightSim/M_TerrainImageryNight "
						                       "missing (re-run scripts/ue_create_materials.py); "
						                       "drape rendered without lights");
						NightTexture = nullptr;
					}
					else
					{
						ImageryBase = NightBase;
					}
				}
			}
			if (!NightLightsNote.IsEmpty())
			{
				UE_LOG(LogFlightSimRender, Warning, TEXT("night lights: %s"),
				       *NightLightsNote);
			}
		}
		UMaterialInstanceDynamic* Instance =
			UMaterialInstanceDynamic::Create(ImageryBase, World);
		Instance->SetTextureParameterValue(TEXT("Imagery"), Texture);
		if (NightTexture != nullptr)
		{
			Instance->SetTextureParameterValue(TEXT("NightLights"), NightTexture);
			Instance->SetScalarParameterValue(TEXT("NightLuminance"),
			                                  static_cast<float>(NightLuminance));
		}
		Material = Instance;
	}
	else if (Options.bClassifiedMaterial)
	{
		UMaterialInterface* VertexColour = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Game/FlightSim/M_VertexColor.M_VertexColor"));
		if (VertexColour == nullptr)
		{
			Error = TEXT(
				"/Game/FlightSim/M_VertexColor is missing. Run "
				"scripts/ue_create_materials.py (build-time asset step) -- "
				"falling back silently to the default material would render "
				"the classification invisibly wrong.");
			return false;
		}
		Material = VertexColour;
	}
	// Phase 2: the precipitation wetness scalar, on whichever material the
	// terrain draws with (a dynamic instance is made when needed); recorded.
	Material = ApplyWetness(World, Material, Options);

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<FVector2D> UV0;
	TArray<FLinearColor> Colours;
	Vertices.Reserve(Rows * Columns);
	Normals.Reserve(Rows * Columns);
	UV0.Reserve(Rows * Columns);
	Colours.Reserve(Rows * Columns);

	AGeoReferencingSystem* Geo = Options.GeoReferencing;
	// A calm card never told the scenario world about this raster's CRS (only
	// orographic cards do), so make the projected frame match the terrain
	// here. Placing UTM-32N coordinates through a default CRS would put the
	// Matterhorn in the wrong country with no error message.
	if (Geo->ProjectedCRS != Terrain.Crs)
	{
		Geo->ProjectedCRS = Terrain.Crs;
		Geo->ApplySettings();
	}
	for (int32 Row = 0; Row < Terrain.Height; Row += Stride)
	{
		for (int32 Column = 0; Column < Terrain.Width; Column += Stride)
		{
			const double X = Terrain.OriginXMetres + Column * Terrain.PixelSizeMetres;
			const double Y = Terrain.OriginYMetres - Row * Terrain.PixelSizeMetres;
			const double Elevation = Terrain.SampleMetres(Row, Column);

			// True position: projected CRS -> engine, through the same PROJ
			// context that places the aircraft. Curvature over a 40 km scene
			// is real (~30 m of drop at the edges) and comes out of this
			// transform rather than being approximated away.
			FVector Engine;
			Geo->ProjectedToEngine(FVector(X, Y, Elevation), Engine);
			Vertices.Add(Engine);
			UV0.Add(FVector2D(Column / double(Terrain.Width),
			                  Row / double(Terrain.Height)));

			const int32 RowN = FMath::Max(Row - Stride, 0);
			const int32 RowS = FMath::Min(Row + Stride, Terrain.Height - 1);
			const int32 ColW = FMath::Max(Column - Stride, 0);
			const int32 ColE = FMath::Min(Column + Stride, Terrain.Width - 1);
			const double DzDx =
				(Terrain.SampleMetres(Row, ColE) - Terrain.SampleMetres(Row, ColW)) /
				((ColE - ColW) * Terrain.PixelSizeMetres);
			const double DzDy =
				(Terrain.SampleMetres(RowN, Column) - Terrain.SampleMetres(RowS, Column)) /
				((RowS - RowN) * Terrain.PixelSizeMetres);
			Normals.Add(FVector(-DzDx, -DzDy, 1.0).GetSafeNormal());

			const double SlopeDegrees =
				FMath::RadiansToDegrees(FMath::Atan(FMath::Sqrt(DzDx * DzDx + DzDy * DzDy)));
			Colours.Add(Options.bClassifiedMaterial
				? ClassifyVertex(Elevation, SlopeDegrees, Terrain.SnowlineMetres)
				: FLinearColor::White);
		}
	}

	// Tiles: the decimated grid cut into blocks of at most
	// SceneTerrainTileVerticesPerSide vertices a side, neighbours sharing
	// their edge row/column (so there is no seam), one procedural mesh
	// component per tile under one scene root. Normals were computed from
	// the full raster above, so shading is continuous across tile edges.
	AActor* TerrainActor = World->SpawnActor<AActor>();
	USceneComponent* Root =
		NewObject<USceneComponent>(TerrainActor, TEXT("TerrainGeoreferenced"));
	TerrainActor->SetRootComponent(Root);
	Root->SetMobility(EComponentMobility::Movable);
	Root->RegisterComponent();

	const int32 TileSpan = SceneTerrainTileVerticesPerSide - 1;   // quads per tile side
	const int32 TileRows = FMath::DivideAndRoundUp(Rows - 1, TileSpan);
	const int32 TileColumns = FMath::DivideAndRoundUp(Columns - 1, TileSpan);
	TerrainTiles = 0;
	TerrainTriangles = 0;
	for (int32 TileRow = 0; TileRow < TileRows; ++TileRow)
	{
		for (int32 TileColumn = 0; TileColumn < TileColumns; ++TileColumn)
		{
			const int32 Row0 = TileRow * TileSpan;
			const int32 Row1 = FMath::Min(Row0 + TileSpan, Rows - 1);        // inclusive
			const int32 Col0 = TileColumn * TileSpan;
			const int32 Col1 = FMath::Min(Col0 + TileSpan, Columns - 1);     // inclusive
			const int32 TileRowCount = Row1 - Row0 + 1;
			const int32 TileColumnCount = Col1 - Col0 + 1;
			if (TileRowCount < 2 || TileColumnCount < 2)
			{
				continue;
			}

			TArray<FVector> TileVertices;
			TArray<FVector> TileNormals;
			TArray<FVector2D> TileUV0;
			TArray<FLinearColor> TileColours;
			TileVertices.Reserve(TileRowCount * TileColumnCount);
			TileNormals.Reserve(TileRowCount * TileColumnCount);
			TileUV0.Reserve(TileRowCount * TileColumnCount);
			TileColours.Reserve(TileRowCount * TileColumnCount);
			for (int32 Row = Row0; Row <= Row1; ++Row)
			{
				for (int32 Column = Col0; Column <= Col1; ++Column)
				{
					const int32 Index = Row * Columns + Column;
					TileVertices.Add(Vertices[Index]);
					TileNormals.Add(Normals[Index]);
					TileUV0.Add(UV0[Index]);
					TileColours.Add(Colours[Index]);
				}
			}

			TArray<int32> TileTriangles;
			TileTriangles.Reserve((TileRowCount - 1) * (TileColumnCount - 1) * 6);
			for (int32 Row = 0; Row < TileRowCount - 1; ++Row)
			{
				for (int32 Column = 0; Column < TileColumnCount - 1; ++Column)
				{
					const int32 A = Row * TileColumnCount + Column;
					const int32 B = A + 1;
					const int32 C = A + TileColumnCount;
					const int32 D = C + 1;
					// Same orientation logic as the offset instances: row index
					// increases southward, engine +Y is north.
					TileTriangles.Append({A, C, B, B, C, D});
				}
			}

			UProceduralMeshComponent* Mesh = NewObject<UProceduralMeshComponent>(
				TerrainActor, *FString::Printf(TEXT("TerrainTile_r%d_c%d"), TileRow, TileColumn));
			Mesh->SetupAttachment(Root);
			Mesh->SetMobility(EComponentMobility::Movable);
			Mesh->CreateMeshSection_LinearColor(0, TileVertices, TileTriangles, TileNormals,
			                                    TileUV0, TileColours, {},
			                                    false /* no collision */);
			Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Mesh->SetCastShadow(true);
			Mesh->SetMaterial(0, Material);
			Mesh->RegisterComponent();
			++TerrainTiles;
			TerrainTriangles += TileTriangles.Num() / 3;
		}
	}
	TerrainActor->SetActorLocation(FVector::ZeroVector);

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("TerrainGeoreferenced: %d verts, %d triangles in %d tiles (stride %d = ")
	       TEXT("%.0f m posting, budget %d, %s, snowline %.0f m, classified %s)"),
	       Vertices.Num(), TerrainTriangles, TerrainTiles, Stride, TerrainPostingMetres,
	       Budget, *Terrain.Crs, Terrain.SnowlineMetres,
	       Options.bClassifiedMaterial ? TEXT("yes") : TEXT("no"));
	return true;
}

UTexture2D* FFlightSimVisualScene::LoadNightLights(const FString& SidecarPath,
                                                   double& LuminanceNits)
{
	FString Text;
	TSharedPtr<FJsonObject> Sidecar;
	const TSharedPtr<FJsonObject>* TextureInfo = nullptr;
	FString File;
	if (!FFileHelper::LoadFileToString(Text, *SidecarPath) ||
	    !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Sidecar) ||
	    !Sidecar.IsValid() ||
	    !Sidecar->TryGetObjectField(TEXT("texture"), TextureInfo) ||
	    !(*TextureInfo)->TryGetStringField(TEXT("file"), File) ||
	    !Sidecar->TryGetNumberField(TEXT("full_texel_luminance_nits"), LuminanceNits))
	{
		NightLightsNote = FString::Printf(
			TEXT("sidecar '%s' unreadable or incomplete; no lights drawn"),
			*SidecarPath);
		return nullptr;
	}
	(*TextureInfo)->TryGetStringField(TEXT("sha256"), NightLightsSha256);
	Sidecar->TryGetStringField(TEXT("attribution"), NightLightsAttribution);
	const FString PngPath = FPaths::Combine(FPaths::GetPath(SidecarPath), File);
	UTexture2D* Texture = FImageUtils::ImportFileAsTexture2D(PngPath);
	if (Texture == nullptr)
	{
		NightLightsNote = FString::Printf(
			TEXT("texture '%s' failed to load; no lights drawn"), *PngPath);
		NightLightsSha256.Empty();
	}
	return Texture;
}

void FFlightSimVisualScene::ApplyManualExposure(USceneCaptureComponent2D* Capture,
                                                float Bias)
{
	// §6.6: manual exposure. Auto-exposure re-metering as the bright-ground /
	// dark-sky ratio changes with bank is exactly the "breathing" Gate 6
	// forbids. The bias is a scene parameter (11.0 suits Gate 6's low sun;
	// noon over snowfields wants less) and is recorded in the manifest; what
	// matters for the gate is that it is CONSTANT over a clip.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = Bias;
}

double FFlightSimVisualScene::ApplyPhysicalExposure(USceneCaptureComponent2D* Capture,
                                                    double ApertureF,
                                                    double ShutterSeconds, double Iso)
{
	// Manual metering from the physical camera: the engine computes
	// EV100 = log2(N^2 / t * 100 / ISO) from these three when
	// AutoExposureApplyPhysicalCameraExposure is on, and the bias is pinned
	// to zero so nothing is added to it. Like the bias path this is constant
	// over a clip; unlike it, the number is the card's, not a probe's. The
	// extended luminance range (r.DefaultFeature.AutoExposure.
	// ExtendDefaultLuminanceRange, DefaultEngine.ini) sets the calibration
	// this EV100 is interpreted against; the commandlet reads that CVar back
	// into render.json rather than assuming it here.
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	Settings.AutoExposureApplyPhysicalCameraExposure = 1.0f;
	Settings.bOverride_CameraShutterSpeed = true;
	Settings.CameraShutterSpeed = static_cast<float>(1.0 / ShutterSeconds);
	Settings.bOverride_CameraISO = true;
	Settings.CameraISO = static_cast<float>(Iso);
	Settings.bOverride_DepthOfFieldFstop = true;
	Settings.DepthOfFieldFstop = static_cast<float>(ApertureF);
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = 0.0f;
	return ExposureValue100(ApertureF, ShutterSeconds, Iso);
}

// -- W5: the world engine side -------------------------------------------------
// UNCOMPILED here (no engine in the build container); pinned by
// tests/test_ue_world_source.py; the first Windows build verifies. Every
// refusal below names a catalogue entry (core/messages/catalog.yaml).

FRotator FFlightSimVisualScene::MoonRotation(double ElevationDeg, double CompassAzimuthDeg)
{
	// The sun's rule (core/scenario/randomization.py engine_sun_azimuth): the
	// yaw TOWARD a compass bearing b is 90 - b, and the light travels 180
	// degrees from it, pitched down by the elevation.
	return FRotator(-ElevationDeg, (90.0 - CompassAzimuthDeg) + 180.0, 0.0);
}

FVector FFlightSimVisualScene::CloudDriftOffsetMetres(double Mps, double FromDeg, double Seconds)
{
	// FROM FromDeg (meteorological): the air moves toward FromDeg + 180. A
	// compass bearing b points along (sin b, cos b) in engine X east / Y north.
	const double Toward = FMath::DegreesToRadians(FromDeg + 180.0);
	const double Distance = Mps * Seconds;
	return FVector(Distance * FMath::Sin(Toward), Distance * FMath::Cos(Toward), 0.0);
}

FQuat FFlightSimVisualScene::StarfieldRotation(double LatitudeDeg, double LocalSiderealDeg)
{
	// Engine X east, Y north, Z up. The celestial pole stands at the
	// latitude's elevation due north; the equator crosses the meridian at
	// (0, -sin lat, cos lat); hour angle grows westward. Right ascension 0h
	// sits at hour angle theta (the local sidereal angle), 6h at theta - 90:
	// local X = RA 0h, local Y = RA 6h, local Z = the pole (X x Y = Z).
	const double Lat = FMath::DegreesToRadians(LatitudeDeg);
	const double Theta = FMath::DegreesToRadians(LocalSiderealDeg);
	const FVector Pole(0.0, FMath::Cos(Lat), FMath::Sin(Lat));
	const FVector Meridian(0.0, -FMath::Sin(Lat), FMath::Cos(Lat));
	const FVector West(-1.0, 0.0, 0.0);
	const FVector RaZero = Meridian * FMath::Cos(Theta) + West * FMath::Sin(Theta);
	const FVector RaSix = Meridian * FMath::Sin(Theta) - West * FMath::Cos(Theta);
	return FQuat(FMatrix(RaZero, RaSix, Pole, FVector::ZeroVector));
}

UTexture2D* FFlightSimVisualScene::BuildStarTexture(const FString& Mode,
                                                    const FFlightSimVisualSceneOptions& Options,
                                                    int32& StarCount, FString& Source,
                                                    FString& Error)
{
	struct FStar { double RaDeg; double DecDeg; double V; };
	TArray<FStar> Stars;
	if (Mode == TEXT("catalogue"))
	{
		// The cached BSC5 conversion, its sha256 checked on every load
		// (core/scene/night.py load_catalogue's rule): a corrupt cache never
		// becomes a sky.
		TArray<uint8> Bytes;
		if (Options.StarCataloguePath.IsEmpty() ||
		    !FFileHelper::LoadFileToArray(Bytes, *Options.StarCataloguePath))
		{
			Error = FString::Printf(
				TEXT("look.stars: the card asks for the catalogue starfield and the star catalogue ")
				TEXT("is not cached at '%s' on this machine (assets/stars/README.md is the fetch ")
				TEXT("step)"), *Options.StarCataloguePath);
			return nullptr;
		}
		const FString Digest = SceneSha256Hex(Bytes.GetData(), Bytes.Num());
		if (!Digest.Equals(SceneStarCatalogueSha256, ESearchCase::IgnoreCase))
		{
			Error = FString::Printf(
				TEXT("look.stars: the cached star catalogue '%s' has sha256 %s..., not the %s... ")
				TEXT("the code checks; refusing to draw a sky from another file"),
				*Options.StarCataloguePath, *Digest.Left(12),
				*FString(SceneStarCatalogueSha256).Left(12));
			return nullptr;
		}
		FString Text;
		FFileHelper::BufferToString(Text, Bytes.GetData(), Bytes.Num());
		TArray<TSharedPtr<FJsonValue>> Entries;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Entries))
		{
			Error = TEXT("look.stars: the cached star catalogue does not parse as the BSC5 conversion");
			return nullptr;
		}
		for (const TSharedPtr<FJsonValue>& Entry : Entries)
		{
			const TSharedPtr<FJsonObject> Row = Entry.IsValid() ? Entry->AsObject() : nullptr;
			FString Ra, Dec, VText;
			double V = 0.0;
			if (!Row.IsValid() || !Row->TryGetStringField(TEXT("RA"), Ra) ||
			    !Row->TryGetStringField(TEXT("Dec"), Dec))
			{
				continue;
			}
			if (Row->TryGetStringField(TEXT("V"), VText))
			{
				VText.TrimStartAndEndInline();
				if (VText.IsEmpty())
				{
					continue;   // the few entries without a V magnitude (night.py skips them)
				}
				V = FCString::Atod(*VText);
			}
			else if (!Row->TryGetNumberField(TEXT("V"), V))
			{
				continue;
			}
			FStar Star;
			Star.V = V;
			if (!SceneSexagesimal(Ra, true, Star.RaDeg) || !SceneSexagesimal(Dec, false, Star.DecDeg))
			{
				Error = FString::Printf(
					TEXT("look.stars: a catalogue entry's position ('%s', '%s') is not three ")
					TEXT("sexagesimal fields"), *Ra, *Dec);
				return nullptr;
			}
			Stars.Add(Star);
		}
		Source = FString::Printf(
			TEXT("catalogue: Yale BSC5 (the cached conversion, sha256 %s), %d stars with a V magnitude"),
			SceneStarCatalogueSha256, Stars.Num());
	}
	else
	{
		// The procedural law of core/scene/night.py procedural_field: RA
		// uniform, sin(Dec) uniform, V = V_lim + log10(u) / slope clamped at
		// the brightest -- drawn by the ENGINE's generator seeded from the
		// card's spec digest, so the rows are not the Python rows (numpy's
		// generator is not reproduced here; the record says so).
		FString Digest;
		if (Options.Card.IsValid())
		{
			Options.Card->TryGetStringField(TEXT("spec_digest"), Digest);
		}
		const int32 Seed = static_cast<int32>(FParse::HexNumber(*Digest.Left(8)) & 0x7fffffff);
		FRandomStream Stream(Seed);
		for (int32 i = 0; i < SceneStarProceduralCount; ++i)
		{
			FStar Star;
			Star.RaDeg = Stream.FRandRange(0.0f, 360.0f);
			Star.DecDeg = FMath::RadiansToDegrees(FMath::Asin(Stream.FRandRange(-1.0f, 1.0f)));
			const double U = 1.0 - Stream.GetFraction();    // (0, 1]
			Star.V = FMath::Max(SceneStarLimitingMag + FMath::LogX(10.0, U) / SceneStarProceduralSlope,
			                    SceneStarBrightestMag);
			Stars.Add(Star);
		}
		Source = FString::Printf(
			TEXT("procedural (the engine's generator, seed %d from the spec digest): the law of ")
			TEXT("core/scene/night.py procedural_field, %d isotropic stars to V %.1f, NOT its rows"),
			Seed, SceneStarProceduralCount, SceneStarLimitingMag);
	}

	// Equirectangular, right ascension across (u = RA / 360), declination
	// down (v = (90 - Dec) / 180); a texel holds luminance in cd/m^2: the
	// star's illuminance over the texel's solid angle at its declination.
	TArray<float> Luminance;
	Luminance.SetNumZeroed(SceneStarMapWidth * SceneStarMapHeight);
	const double TexelSteradians = (2.0 * PI / SceneStarMapWidth) * (PI / SceneStarMapHeight);
	for (const FStar& Star : Stars)
	{
		const int32 Column = FMath::Clamp(
			FMath::FloorToInt(FMath::Fmod(Star.RaDeg + 360.0, 360.0) / 360.0 * SceneStarMapWidth),
			0, SceneStarMapWidth - 1);
		const int32 Row = FMath::Clamp(
			FMath::FloorToInt((90.0 - Star.DecDeg) / 180.0 * SceneStarMapHeight),
			0, SceneStarMapHeight - 1);
		const double Solid = TexelSteradians *
			FMath::Max(FMath::Cos(FMath::DegreesToRadians(Star.DecDeg)), 1.0e-3);
		const double Lux = SceneStarZeroPointLux * FMath::Pow(10.0, -0.4 * Star.V);
		Luminance[Row * SceneStarMapWidth + Column] += static_cast<float>(Lux / Solid);
	}
	TArray<FFloat16Color> Pixels;
	Pixels.SetNum(Luminance.Num());
	for (int32 i = 0; i < Luminance.Num(); ++i)
	{
		Pixels[i] = FFloat16Color(FLinearColor(Luminance[i], Luminance[i], Luminance[i], 1.0f));
	}
	UTexture2D* Texture = UTexture2D::CreateTransient(SceneStarMapWidth, SceneStarMapHeight, PF_FloatRGBA);
	if (Texture == nullptr)
	{
		Error = TEXT("look.stars: the starfield texture could not be created");
		return nullptr;
	}
	Texture->SRGB = false;
	Texture->Filter = TF_Nearest;
	Texture->CompressionSettings = TC_HDR;
	FTexture2DMipMap& Mip = Texture->GetPlatformData()->Mips[0];
	void* Data = Mip.BulkData.Lock(LOCK_READ_WRITE);
	FMemory::Memcpy(Data, Pixels.GetData(), Pixels.Num() * sizeof(FFloat16Color));
	Mip.BulkData.Unlock();
	Texture->UpdateResource();
	StarCount = Stars.Num();
	return Texture;
}

bool FFlightSimVisualScene::BuildWorldLook(UWorld* World,
                                           const FFlightSimVisualSceneOptions& Options,
                                           FString& Error)
{
	TSharedPtr<FJsonObject> Look;
	const TSharedPtr<FJsonObject>* LookJson = nullptr;
	if (Options.Card.IsValid() && Options.Card->TryGetObjectField(TEXT("look"), LookJson) &&
	    LookJson != nullptr && LookJson->IsValid())
	{
		Look = *LookJson;
	}
	if (!Look.IsValid())
	{
		return true;   // no world look on the card: every row stays "not asked"
	}

	// -- the night: the moon light and the starfield ------------------------
	const TSharedPtr<FJsonObject>* NightJson = nullptr;
	if (Look->TryGetObjectField(TEXT("night"), NightJson) && NightJson != nullptr &&
	    NightJson->IsValid())
	{
		const TSharedPtr<FJsonObject>& Night = *NightJson;
		double MoonElevation = 0.0, MoonAzimuth = 0.0, Phase = 0.0, MoonLux = 0.0;
		FString StarsMode, SunUnits;
		// core/scene/night.py CARD_KEYS, every one required.
		if (!Night->TryGetNumberField(TEXT("moon_elevation_deg"), MoonElevation) ||
		    !Night->TryGetNumberField(TEXT("moon_azimuth_deg"), MoonAzimuth) ||
		    !Night->TryGetNumberField(TEXT("phase"), Phase) ||
		    !Night->TryGetNumberField(TEXT("illuminance_lux"), MoonLux) ||
		    !Night->TryGetStringField(TEXT("stars_mode"), StarsMode) ||
		    !Night->TryGetStringField(TEXT("sun_units"), SunUnits))
		{
			Error = TEXT("look.moon: the card's look.night lacks one of moon_elevation_deg, ")
			        TEXT("moon_azimuth_deg, phase, illuminance_lux, stars_mode, sun_units; the night ")
			        TEXT("sky is drawn from all of them or not at all");
			return false;
		}
		TSharedPtr<FJsonObject> Row = NewRecord();
		Row->SetBoolField(TEXT("asked"), true);
		TSharedPtr<FJsonObject> MoonRow = NewRecord();
		if (MoonLux > 0.0)
		{
			// night.sun_units, re-checked here: the moon's lux beside a sun
			// that is not in lux is 0.27 lx next to 8.0 of nothing.
			if (SunUnits != TEXT("physical") || !(Options.SunLux > 0.0))
			{
				Error = FString::Printf(
					TEXT("night.sun_units: the moon's %.6g lux needs the sun in lux (the card says ")
					TEXT("sun_units '%s', the render's sun is %s); refusing a moonlight that means ")
					TEXT("nothing beside it"), MoonLux, *SunUnits,
					Options.SunLux > 0.0 ? TEXT("in lux") : TEXT("the unitless 8.0"));
				return false;
			}
			if (!(MoonLux <= SceneMoonLuxMax) || !(MoonElevation > -90.0 && MoonElevation <= 90.0))
			{
				Error = FString::Printf(
					TEXT("look.moon: a moon of %.6g lux at %.3f deg elevation cannot be drawn; no ")
					TEXT("moon is brighter than %.1f lux"), MoonLux, MoonElevation, SceneMoonLuxMax);
				return false;
			}
			// The SECOND directional light: AtmosphereSunLightIndex 1, so the
			// sky atmosphere draws its disc and scatters its light; lux, the
			// sun's unit (a directional light's intensity is lux).
			Moon = World->SpawnActor<ADirectionalLight>();
			UDirectionalLightComponent* MoonLight =
				Cast<UDirectionalLightComponent>(Moon->GetLightComponent());
			MoonLight->SetMobility(EComponentMobility::Movable);
			MoonLight->SetAtmosphereSunLight(true);
			MoonLight->SetAtmosphereSunLightIndex(1);
			MoonLight->SetIntensity(static_cast<float>(MoonLux));
			MoonLight->SetCastShadows(Options.bDynamicShadows);
			Moon->SetActorRotation(MoonRotation(MoonElevation, MoonAzimuth));
			MoonRow->SetBoolField(TEXT("drawn"), true);
			MoonRow->SetStringField(TEXT("component"),
				TEXT("ADirectionalLight, the second (UDirectionalLightComponent::SetAtmosphereSunLightIndex)"));
			// Read back from the component, not restated from the card.
			MoonRow->SetNumberField(TEXT("atmosphere_sun_light_index"),
			                        MoonLight->GetAtmosphereSunLightIndex());
			MoonRow->SetNumberField(TEXT("intensity_lux"), MoonLight->Intensity);
			MoonRow->SetStringField(TEXT("light_units"), TEXT("physical"));
			MoonRow->SetNumberField(TEXT("elevation_deg"), MoonElevation);
			MoonRow->SetNumberField(TEXT("azimuth_deg"), MoonAzimuth);
			MoonRow->SetNumberField(TEXT("phase"), Phase);
			const FRotator Applied = Moon->GetActorRotation();
			MoonRow->SetNumberField(TEXT("rotation_pitch_deg"), Applied.Pitch);
			MoonRow->SetNumberField(TEXT("rotation_yaw_deg"), Applied.Yaw);
		}
		else
		{
			MoonRow->SetBoolField(TEXT("drawn"), false);
			MoonRow->SetStringField(TEXT("note"),
				TEXT("illuminance 0 on the card: the moon is off or below the horizon"));
		}
		Row->SetObjectField(TEXT("moon"), MoonRow);

		TSharedPtr<FJsonObject> StarsRow = NewRecord();
		StarsRow->SetStringField(TEXT("mode"), StarsMode);
		if (StarsMode == TEXT("catalogue") || StarsMode == TEXT("procedural"))
		{
			UMaterialInterface* StarMaterial =
				LoadObject<UMaterialInterface>(nullptr, SceneStarfieldMaterialPath);
			UStaticMesh* SphereMesh =
				LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere"));
			if (StarMaterial == nullptr || SphereMesh == nullptr)
			{
				Error = FString::Printf(
					TEXT("look.stars: the starfield needs %s (scripts/ue_create_materials.py) and the ")
					TEXT("engine sphere; %s did not load"), SceneStarfieldMaterialPath,
					StarMaterial == nullptr ? SceneStarfieldMaterialPath : TEXT("/Engine/BasicShapes/Sphere"));
				return false;
			}
			int32 StarCount = 0;
			FString StarSource;
			UTexture2D* StarMap = BuildStarTexture(StarsMode, Options, StarCount, StarSource, Error);
			if (StarMap == nullptr)
			{
				return false;
			}
			double LatitudeDeg = 0.0;
			Options.Card->TryGetNumberField(TEXT("latitude_deg"), LatitudeDeg);
			double SiderealDeg = 0.0;
			const bool bSidereal = Night->TryGetNumberField(TEXT("local_sidereal_deg"), SiderealDeg);
			Starfield = World->SpawnActor<AActor>();
			Starfield->Tags.Add(FName(TEXT("FlightSim.look")));
			UStaticMeshComponent* Sphere = NewObject<UStaticMeshComponent>(Starfield, TEXT("Starfield"));
			Starfield->SetRootComponent(Sphere);
			Sphere->SetMobility(EComponentMobility::Movable);
			Sphere->SetStaticMesh(SphereMesh);
			Sphere->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Sphere->SetCastShadow(false);
			UMaterialInstanceDynamic* StarInstance = UMaterialInstanceDynamic::Create(StarMaterial, Starfield);
			StarInstance->SetTextureParameterValue(SceneStarMapParameter, StarMap);
			StarInstance->SetScalarParameterValue(SceneStarIntensityParameter, 1.0f);
			Sphere->SetMaterial(0, StarInstance);
			Sphere->RegisterComponent();
			// The engine sphere is 1 m across: scale S draws an S m sphere.
			Starfield->SetActorLocation(FVector::ZeroVector);
			Starfield->SetActorScale3D(FVector(2.0 * SceneStarfieldRadiusMetres));
			Starfield->SetActorRotation(StarfieldRotation(LatitudeDeg, SiderealDeg));
			// The label captures never see it (ConfigureLabelCapture hides
			// BeautyOnlyActors; the stencil loop skips them).
			BeautyOnlyActors.Add(Starfield);
			StarsRow->SetBoolField(TEXT("drawn"), true);
			StarsRow->SetNumberField(TEXT("count"), StarCount);
			StarsRow->SetStringField(TEXT("source"), StarSource);
			StarsRow->SetStringField(TEXT("material"), SceneStarfieldMaterialPath);
			StarsRow->SetNumberField(TEXT("radius_m"), SceneStarfieldRadiusMetres);
			StarsRow->SetNumberField(TEXT("latitude_deg"), LatitudeDeg);
			StarsRow->SetNumberField(TEXT("local_sidereal_deg"), SiderealDeg);
			StarsRow->SetStringField(TEXT("orientation"), bSidereal
				? TEXT("the pole at the latitude, right ascension 0h at the card's local sidereal angle")
				: TEXT("the pole at the latitude; the card carries no local sidereal angle, so right ")
				  TEXT("ascension 0h is placed on the meridian: the catalogue's pattern, not the moment's ")
				  TEXT("rotation about the pole"));
			StarsRow->SetStringField(TEXT("texel"),
				TEXT("luminance cd/m^2 = the star's illuminance (2.54e-6 lx at V 0) over the texel's ")
				TEXT("solid angle; nearest-filtered, one texel per star"));
			StarsRow->SetStringField(TEXT("label_captures"), TEXT("hidden"));
		}
		else
		{
			StarsRow->SetBoolField(TEXT("drawn"), false);
			StarsRow->SetStringField(TEXT("note"), TEXT("stars off on the card"));
		}
		Row->SetObjectField(TEXT("stars"), StarsRow);
		Row->SetBoolField(TEXT("drawn"), Moon != nullptr || Starfield != nullptr);
		WorldApplied->SetObjectField(TEXT("night"), Row);
		// The Look lane's night row now says what was drawn.
		TSharedPtr<FJsonObject> LookNight = NewRecord();
		LookNight->SetStringField(TEXT("moon"), Moon != nullptr ? TEXT("drawn (world_applied.night)") : TEXT("not drawn"));
		LookNight->SetStringField(TEXT("stars"), Starfield != nullptr ? TEXT("drawn (world_applied.night)") : TEXT("not drawn"));
		LookApplied->SetObjectField(TEXT("night"), LookNight);
	}

	// -- the rain: its row is written when the beauty capture exists ---------
	const TSharedPtr<FJsonObject>* PrecipitationJson = nullptr;
	if (Look->TryGetObjectField(TEXT("precipitation"), PrecipitationJson) &&
	    PrecipitationJson != nullptr && PrecipitationJson->IsValid())
	{
		CardPrecipitation = *PrecipitationJson;
	}

	// -- the cloud drift: the material's offset per tick ---------------------
	const TSharedPtr<FJsonObject>* DriftJson = nullptr;
	if (Look->TryGetObjectField(TEXT("cloud_drift"), DriftJson) && DriftJson != nullptr &&
	    DriftJson->IsValid())
	{
		TSharedPtr<FJsonObject> Row = NewRecord();
		Row->SetBoolField(TEXT("asked"), true);
		double BaseM = 0.0;
		FString DriftSource;
		(*DriftJson)->TryGetNumberField(TEXT("mps"), DriftMps);
		(*DriftJson)->TryGetNumberField(TEXT("from_deg"), DriftFromDeg);
		(*DriftJson)->TryGetNumberField(TEXT("base_m"), BaseM);
		(*DriftJson)->TryGetStringField(TEXT("source"), DriftSource);
		Row->SetNumberField(TEXT("mps"), DriftMps);
		Row->SetNumberField(TEXT("from_deg"), DriftFromDeg);
		Row->SetNumberField(TEXT("base_m"), BaseM);
		Row->SetStringField(TEXT("source"), DriftSource);
		if (!(DriftMps > 0.0))
		{
			Row->SetBoolField(TEXT("drawn"), false);
			Row->SetStringField(TEXT("note"), TEXT("calm at the cloud base: nothing to drift"));
		}
		else if (Clouds == nullptr || CloudMaterialInstance == nullptr)
		{
			Row->SetBoolField(TEXT("drawn"), false);
			Row->SetStringField(TEXT("note"), TEXT("no cloud layer is drawn: nothing to drift"));
		}
		else if (CloudDriftParameter == NAME_None)
		{
			Error = FString::Printf(
				TEXT("look.cloud_drift_parameter: the card asks for a %.3f m/s cloud drift and the ")
				TEXT("cloud material exposes no vector parameter named *%s*; refusing to record a ")
				TEXT("drift that moves nothing"), DriftMps, SceneCloudDriftNeedle);
			return false;
		}
		else
		{
			Row->SetBoolField(TEXT("drawn"), true);
			Row->SetStringField(TEXT("parameter"), CloudDriftParameter.ToString());
			Row->SetStringField(TEXT("rule"),
				TEXT("offset_m = mps * t downwind (engine X east, Y north), written before every ")
				TEXT("capture at the FDM's own time; the parameter's own unit convention is the ")
				TEXT("drift doublet's Windows measurement"));
			TSharedPtr<FJsonObject> LookDrift = NewRecord();
			LookDrift->SetNumberField(TEXT("cloud_drift_mps"), DriftMps);
			LookDrift->SetNumberField(TEXT("cloud_drift_from_deg"), DriftFromDeg);
			LookDrift->SetBoolField(TEXT("applied"), true);
			LookDrift->SetStringField(TEXT("parameter"), CloudDriftParameter.ToString());
			LookApplied->SetObjectField(TEXT("cloud_drift"), LookDrift);
		}
		WorldApplied->SetObjectField(TEXT("cloud_drift"), Row);
	}

	// The Look lane's not-claimed list loses what this build now draws (the
	// rain leaves it in ApplyRainToBeauty).
	{
		const bool bDrifting = CloudMaterialInstance != nullptr && CloudDriftParameter != NAME_None &&
		                       DriftMps > 0.0;
		TArray<TSharedPtr<FJsonValue>> NotClaimed;
		for (const TCHAR* Name : {TEXT("precipitation_particles"), TEXT("moon"), TEXT("stars"),
		                          TEXT("cloud_drift"), TEXT("sea_state"), TEXT("foliage_sway")})
		{
			const FString Word(Name);
			const bool bDrawn = (Word == TEXT("moon") && Moon != nullptr) ||
			                    (Word == TEXT("stars") && Starfield != nullptr) ||
			                    (Word == TEXT("cloud_drift") && bDrifting);
			if (!bDrawn)
			{
				NotClaimed.Add(MakeShared<FJsonValueString>(Word));
			}
		}
		LookApplied->SetArrayField(TEXT("not_claimed"), NotClaimed);
	}
	return true;
}

bool FFlightSimVisualScene::ApplyRainToBeauty(USceneCaptureComponent2D* Beauty,
                                              const FString& CameraId, FString& Error)
{
	if (!CardPrecipitation.IsValid() || WorldApplied == nullptr)
	{
		return true;   // no rain rate on the card: nothing is added to any capture
	}
	TSharedPtr<FJsonObject> Row = NewRecord();
	Row->SetBoolField(TEXT("asked"), true);
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, SceneRainMaterialPath);
	if (Material == nullptr || Beauty == nullptr)
	{
		Error = FString::Printf(
			TEXT("look.precipitation_particles: the rain streaks need %s (scripts/")
			TEXT("ue_create_materials.py) on the beauty capture; it did not load"),
			SceneRainMaterialPath);
		return false;
	}
	const TSharedPtr<FJsonObject>* Streaks = nullptr;
	const TSharedPtr<FJsonObject>* Streak = nullptr;
	double LengthPx = 0.0;
	const TArray<TSharedPtr<FJsonValue>>* Vector = nullptr;
	FString StreakCamera = CameraId;
	if (CardPrecipitation->TryGetObjectField(TEXT("streak_px"), Streaks) && Streaks != nullptr &&
	    StreakCamera.IsEmpty() && (*Streaks)->Values.Num() == 1)
	{
		// A preset pass consumes no camera: the card's only streak is its own.
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Streaks)->Values)
		{
			StreakCamera = Pair.Key;
		}
	}
	if (StreakCamera.IsEmpty() || Streaks == nullptr ||
	    !(*Streaks)->TryGetObjectField(StreakCamera, Streak) || Streak == nullptr ||
	    !(*Streak)->TryGetNumberField(TEXT("relative_px"), LengthPx) ||
	    !(*Streak)->TryGetArrayField(TEXT("relative_vector_px"), Vector) || Vector == nullptr ||
	    Vector->Num() != 2)
	{
		Error = TEXT("look.precipitation_particles: the card's look.precipitation carries no ")
		        TEXT("streak for this camera (streak_px[camera].relative_px and relative_vector_px); ")
		        TEXT("the streak length is never derived here");
		return false;
	}
	double Density = 0.0, RateMmh = 0.0;
	CardPrecipitation->TryGetNumberField(TEXT("density"), Density);
	CardPrecipitation->TryGetNumberField(TEXT("rate_mmh"), RateMmh);
	FVector2D Direction((*Vector)[0]->AsNumber(), (*Vector)[1]->AsNumber());
	if (!Direction.Normalize())
	{
		Direction = FVector2D(0.0, 1.0);   // no relative motion across the frame: straight down
	}
	RainInstance = UMaterialInstanceDynamic::Create(Material, Beauty);
	RainInstance->SetScalarParameterValue(SceneRainLengthParameter, static_cast<float>(LengthPx));
	RainInstance->SetVectorParameterValue(SceneRainDirectionParameter,
		FLinearColor(static_cast<float>(Direction.X), static_cast<float>(Direction.Y), 0.0f, 0.0f));
	RainInstance->SetScalarParameterValue(SceneRainDensityParameter, static_cast<float>(Density));
	RainInstance->SetScalarParameterValue(SceneRainPhaseParameter, 0.0f);
	// The world look's ONE blendable, on the beauty capture only: the label
	// captures (ConfigureLabelCapture in the commandlet) never receive it,
	// so mask, class and depth are byte-identical with the rain on and off.
	Beauty->PostProcessSettings.WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, RainInstance));
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("applied_to"), TEXT("beauty"));
	Row->SetStringField(TEXT("label_captures"), TEXT("none: the label captures carry no look blendable"));
	Row->SetStringField(TEXT("material"), SceneRainMaterialPath);
	Row->SetNumberField(TEXT("rate_mmh"), RateMmh);
	Row->SetNumberField(TEXT("streak_length_px"), LengthPx);
	TArray<TSharedPtr<FJsonValue>> DirectionJson;
	DirectionJson.Add(MakeShared<FJsonValueNumber>(Direction.X));
	DirectionJson.Add(MakeShared<FJsonValueNumber>(Direction.Y));
	Row->SetArrayField(TEXT("streak_direction"), DirectionJson);
	Row->SetNumberField(TEXT("density_per_m3"), Density);
	Row->SetStringField(TEXT("not_claimed"),
		TEXT("screen-space streaks with the card's relative length; no volumetric rain, splashes ")
		TEXT("or accumulation; the linear and accumulation captures carry no streaks"));
	WorldApplied->SetObjectField(TEXT("precipitation"), Row);
	// The streaks are drawn now: the Look lane's not-claimed list drops them.
	const TArray<TSharedPtr<FJsonValue>>* NotClaimed = nullptr;
	if (LookApplied.IsValid() && LookApplied->TryGetArrayField(TEXT("not_claimed"), NotClaimed) &&
	    NotClaimed != nullptr)
	{
		TArray<TSharedPtr<FJsonValue>> Kept;
		for (const TSharedPtr<FJsonValue>& Value : *NotClaimed)
		{
			if (Value.IsValid() && Value->AsString() != TEXT("precipitation_particles"))
			{
				Kept.Add(Value);
			}
		}
		LookApplied->SetArrayField(TEXT("not_claimed"), Kept);
	}
	return true;
}

void FFlightSimVisualScene::AdvanceWorld(double TimeSeconds)
{
	if (CloudMaterialInstance != nullptr && CloudDriftParameter != NAME_None && DriftMps > 0.0)
	{
		const FVector Offset = CloudDriftOffsetMetres(DriftMps, DriftFromDeg, TimeSeconds);
		CloudMaterialInstance->SetVectorParameterValue(CloudDriftParameter,
			FLinearColor(static_cast<float>(Offset.X), static_cast<float>(Offset.Y), 0.0f, 0.0f));
		const TSharedPtr<FJsonObject>* Row = nullptr;
		if (WorldApplied.IsValid() && WorldApplied->TryGetObjectField(TEXT("cloud_drift"), Row) &&
		    Row != nullptr && Row->IsValid())
		{
			(*Row)->SetNumberField(TEXT("last_t_s"), TimeSeconds);
			(*Row)->SetNumberField(TEXT("last_offset_east_m"), Offset.X);
			(*Row)->SetNumberField(TEXT("last_offset_north_m"), Offset.Y);
		}
	}
	if (RainInstance != nullptr)
	{
		// The streak pattern's phase is the FDM's time: deterministic per step.
		RainInstance->SetScalarParameterValue(SceneRainPhaseParameter, static_cast<float>(TimeSeconds));
	}
}

bool FFlightSimVisualScene::LoadSceneLevel(UWorld* World,
                                           const FFlightSimVisualSceneOptions& Options,
                                           FString& Error)
{
	const TSharedPtr<FJsonObject>& Doc = SceneDocument;
	TSharedPtr<FJsonObject> Row = NewRecord();
	Row->SetBoolField(TEXT("asked"), true);
	Row->SetStringField(TEXT("scene_document"), Options.SceneDocumentPath);
	FString SceneLevel, DocSha, NorthAxis = TEXT("+Y");
	Doc->TryGetStringField(TEXT("scene_level"), SceneLevel);
	Doc->TryGetStringField(TEXT("terrain_sha256"), DocSha);
	Doc->TryGetStringField(TEXT("north_axis"), NorthAxis);
	Row->SetStringField(TEXT("scene_level"), SceneLevel);
	WorldApplied->SetObjectField(TEXT("landscape"), Row);
	auto Stale = [&Error](const FString& Why)
	{
		Error = TEXT("world.scene_stale: ") + Why;
		return false;
	};

	// 1. The bake this render loaded is the scene's own.
	if (!DocSha.Equals(Terrain.Sha256, ESearchCase::IgnoreCase))
	{
		return Stale(FString::Printf(
			TEXT("the scene %s was built from a bake with sha256 %s..., the render loaded %s...; ")
			TEXT("build the scene again from this bake (scripts/ue_build_scene.py)"),
			*SceneLevel, *DocSha.Left(12), *Terrain.Sha256.Left(12)));
	}

	// 2. The card's world block: terrain sha, scene level, sidecars, layers.
	FString CardSha;
	const TSharedPtr<FJsonObject>* CardWorld = nullptr;
	if (Options.Card.IsValid() && Options.Card->TryGetObjectField(TEXT("world"), CardWorld) &&
	    CardWorld != nullptr && CardWorld->IsValid())
	{
		FString CardLevel;
		(*CardWorld)->TryGetStringField(TEXT("terrain_sha256"), CardSha);
		(*CardWorld)->TryGetStringField(TEXT("scene_level"), CardLevel);
		if (!CardSha.IsEmpty() && !CardSha.Equals(DocSha, ESearchCase::IgnoreCase))
		{
			return Stale(FString::Printf(
				TEXT("the card's world.terrain_sha256 %s... is not the scene's %s..."),
				*CardSha.Left(12), *DocSha.Left(12)));
		}
		if (!CardLevel.IsEmpty() && CardLevel != SceneLevel)
		{
			return Stale(FString::Printf(TEXT("the card names the scene level %s, the document %s"),
			                             *CardLevel, *SceneLevel));
		}
		// Every sidecar the card and the scene both name carries one digest.
		const TSharedPtr<FJsonObject>* CardSidecars = nullptr;
		const TSharedPtr<FJsonObject>* DocSidecars = nullptr;
		if ((*CardWorld)->TryGetObjectField(TEXT("sidecars"), CardSidecars) && CardSidecars != nullptr &&
		    Doc->TryGetObjectField(TEXT("sidecars"), DocSidecars) && DocSidecars != nullptr)
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*CardSidecars)->Values)
			{
				const TSharedPtr<FJsonObject> CardEntry = Pair.Value.IsValid() ? Pair.Value->AsObject() : nullptr;
				const TSharedPtr<FJsonObject>* DocEntry = nullptr;
				FString CardDigest, DocDigest;
				if (!CardEntry.IsValid() || !CardEntry->TryGetStringField(TEXT("sha256"), CardDigest) ||
				    !(*DocSidecars)->TryGetObjectField(Pair.Key, DocEntry) || DocEntry == nullptr)
				{
					continue;
				}
				(*DocEntry)->TryGetStringField(TEXT("sha256"), DocDigest);
				if (!CardDigest.Equals(DocDigest, ESearchCase::IgnoreCase))
				{
					return Stale(FString::Printf(TEXT("the sidecar '%s' is %s... on the card and %s... in the scene"),
					                             *Pair.Key, *CardDigest.Left(12), *DocDigest.Left(12)));
				}
			}
		}
		// The land-cover layers: the same codes with the same digests.
		const TArray<TSharedPtr<FJsonValue>>* CardLayers = nullptr;
		const TArray<TSharedPtr<FJsonValue>>* DocLayers = nullptr;
		if ((*CardWorld)->TryGetArrayField(TEXT("layers"), CardLayers) && CardLayers != nullptr)
		{
			TMap<int32, FString> Wanted;
			for (const TSharedPtr<FJsonValue>& Value : *CardLayers)
			{
				const TSharedPtr<FJsonObject> Layer = Value.IsValid() ? Value->AsObject() : nullptr;
				double Code = 0.0;
				FString Digest;
				if (Layer.IsValid() && Layer->TryGetNumberField(TEXT("code"), Code))
				{
					Layer->TryGetStringField(TEXT("sha256"), Digest);
					Wanted.Add(static_cast<int32>(Code), Digest);
				}
			}
			TMap<int32, FString> Have;
			if (Doc->TryGetArrayField(TEXT("layers"), DocLayers) && DocLayers != nullptr)
			{
				for (const TSharedPtr<FJsonValue>& Value : *DocLayers)
				{
					const TSharedPtr<FJsonObject> Layer = Value.IsValid() ? Value->AsObject() : nullptr;
					double Code = 0.0;
					FString Digest;
					if (Layer.IsValid() && Layer->TryGetNumberField(TEXT("code"), Code))
					{
						Layer->TryGetStringField(TEXT("sha256"), Digest);
						Have.Add(static_cast<int32>(Code), Digest);
					}
				}
			}
			bool bSame = Wanted.Num() == Have.Num();
			for (const TPair<int32, FString>& Pair : Wanted)
			{
				const FString* Digest = Have.Find(Pair.Key);
				bSame = bSame && Digest != nullptr && Digest->Equals(Pair.Value, ESearchCase::IgnoreCase);
			}
			if (!bSame)
			{
				return Stale(FString::Printf(
					TEXT("the card's %d land-cover layers are not the scene's %d (codes or digests differ)"),
					Wanted.Num(), Have.Num()));
			}
		}
	}
	{
		const TArray<TSharedPtr<FJsonValue>>* DocLayers = nullptr;
		if (Doc->TryGetArrayField(TEXT("layers"), DocLayers) && DocLayers != nullptr)
		{
			SceneLayers = *DocLayers;
		}
	}

	// 3. The axes the scene was built for, measured through the
	// georeferencing: one bake cell east must be +X, one north must be the
	// document's north_axis. A mirrored world is refused, never drawn.
	const TArray<TSharedPtr<FJsonValue>>* OriginJson = nullptr;
	if (!Doc->TryGetArrayField(TEXT("landscape_origin_xy"), OriginJson) || OriginJson == nullptr ||
	    OriginJson->Num() != 2)
	{
		Error = TEXT("world.scene_missing: the scene document carries no landscape_origin_xy (the ")
		        TEXT("projected position of the Landscape's first sample)");
		return false;
	}
	const double OriginX = (*OriginJson)[0]->AsNumber();
	const double OriginY = (*OriginJson)[1]->AsNumber();
	const double Pixel = Terrain.PixelSizeMetres;
	FVector Origin, East, North;
	Options.GeoReferencing->ProjectedToEngine(FVector(OriginX, OriginY, 0.0), Origin);
	Options.GeoReferencing->ProjectedToEngine(FVector(OriginX + Pixel, OriginY, 0.0), East);
	Options.GeoReferencing->ProjectedToEngine(FVector(OriginX, OriginY + Pixel, 0.0), North);
	const bool bEastPlusX = East.X > Origin.X;
	const bool bNorthPlusY = North.Y > Origin.Y;
	const FString Measured = bNorthPlusY ? TEXT("+Y") : TEXT("-Y");
	Row->SetStringField(TEXT("north_axis_scene"), NorthAxis);
	Row->SetStringField(TEXT("north_axis_measured"), Measured);
	if (!bEastPlusX || Measured != NorthAxis)
	{
		return Stale(FString::Printf(
			TEXT("the georeferencing puts east along %s X and north along %s; the scene was built ")
			TEXT("with north along %s -- build it again with --north-axis=%s"),
			bEastPlusX ? TEXT("+") : TEXT("-"), *Measured, *NorthAxis, *Measured));
	}

	// 4. The level, streamed into this world at the engine position of MSL 0
	// under the Landscape's first sample (the level holds MSL heights in cm).
	bool bLoaded = false;
	ULevelStreamingDynamic* Streaming = ULevelStreamingDynamic::LoadLevelInstance(
		World, SceneLevel, Origin, FRotator::ZeroRotator, bLoaded);
	if (!bLoaded || Streaming == nullptr)
	{
		Error = FString::Printf(
			TEXT("world.scene_missing: the scene level %s did not load (scripts/ue_build_scene.py ")
			TEXT("builds it in the editor)"), *SceneLevel);
		return false;
	}
	World->FlushLevelStreaming(EFlushLevelStreamingType::Full);
	ULevel* Level = Streaming->GetLoadedLevel();
	if (Level == nullptr)
	{
		Error = FString::Printf(TEXT("world.scene_missing: the scene level %s streamed in empty"),
		                        *SceneLevel);
		return false;
	}

	// 5. The Landscape, its tag, and what the level carries.
	FString TagSha;
	for (AActor* Actor : Level->Actors)
	{
		if (Actor == nullptr)
		{
			continue;
		}
		if (ALandscapeProxy* Proxy = Cast<ALandscapeProxy>(Actor))
		{
			if (SceneHasTag(Proxy, FlightSimWorld::TerrainTag))
			{
				SceneLandscape = Proxy;
				for (const FName& Tag : Proxy->Tags)
				{
					const FString Text = Tag.ToString();
					if (Text.StartsWith(FlightSimWorld::TerrainSha256TagPrefix))
					{
						TagSha = Text.RightChop(FCString::Strlen(FlightSimWorld::TerrainSha256TagPrefix));
					}
				}
			}
		}
		TInlineComponentArray<UPrimitiveComponent*> Primitives;
		Actor->GetComponents(Primitives);
		for (UPrimitiveComponent* Primitive : Primitives)
		{
			if (SceneHasTag(Actor, FlightSimWorld::VegetationTag))
			{
				++VegetationComponents;
				if (const UInstancedStaticMeshComponent* Instanced = Cast<UInstancedStaticMeshComponent>(Primitive))
				{
					VegetationInstances += Instanced->GetInstanceCount();
				}
			}
			else if (SceneHasTag(Actor, FlightSimWorld::BuildingTag))
			{
				++BuildingComponents;
			}
			else if (SceneHasTag(Actor, FlightSimWorld::RunwayTag))
			{
				++RunwayComponents;
			}
		}
		// A PCG component is not a primitive: counted by class name so this
		// module needs no PCG dependency.
		TInlineComponentArray<UActorComponent*> All;
		Actor->GetComponents(All);
		for (UActorComponent* Component : All)
		{
			if (Component != nullptr && !Component->IsA<UPrimitiveComponent>() &&
			    Component->GetClass()->GetName() == TEXT("PCGComponent"))
			{
				++PcgComponents;
			}
		}
	}
	if (SceneLandscape == nullptr)
	{
		Error = FString::Printf(
			TEXT("world.scene_missing: the scene level %s holds no Landscape tagged %s"),
			*SceneLevel, FlightSimWorld::TerrainTag);
		return false;
	}
	if (!TagSha.Equals(Terrain.Sha256, ESearchCase::IgnoreCase) ||
	    (!CardSha.IsEmpty() && !TagSha.Equals(CardSha, ESearchCase::IgnoreCase)))
	{
		return Stale(FString::Printf(
			TEXT("the Landscape's sha256 tag %s... is not the bake's %s...%s"),
			TagSha.IsEmpty() ? TEXT("(none)") : *TagSha.Left(12), *Terrain.Sha256.Left(12),
			CardSha.IsEmpty() ? TEXT("") : *FString::Printf(TEXT(" / the card's %s..."), *CardSha.Left(12))));
	}
#if WITH_EDITORONLY_DATA
	// 6. Every layer the scene document names is a layer of the Landscape.
	{
		TSet<FString> Names;
		if (ULandscapeInfo* Info = SceneLandscape->GetLandscapeInfo())
		{
			for (const FLandscapeInfoLayerSettings& Layer : Info->Layers)
			{
				Names.Add(Layer.GetLayerName().ToString());
			}
		}
		for (const TSharedPtr<FJsonValue>& Value : SceneLayers)
		{
			const TSharedPtr<FJsonObject> Layer = Value.IsValid() ? Value->AsObject() : nullptr;
			FString Key;
			if (Layer.IsValid() && Layer->TryGetStringField(TEXT("key"), Key) && !Names.Contains(Key))
			{
				return Stale(FString::Printf(TEXT("the Landscape carries no layer '%s' of the scene's %d"),
				                             *Key, SceneLayers.Num()));
			}
		}
		Row->SetNumberField(TEXT("layers_on_landscape"), Names.Num());
	}
#endif

	// 7. Vegetation: the biome graph the level's PCG component uses must still
	// exist, and the instances loaded must be the ones the build generated.
	const TSharedPtr<FJsonObject>* Vegetation = nullptr;
	TSharedPtr<FJsonObject> VegetationRow = NewRecord();
	VegetationRow->SetBoolField(TEXT("asked"), false);
	if (Doc->TryGetObjectField(TEXT("vegetation"), Vegetation) && Vegetation != nullptr &&
	    Vegetation->IsValid())
	{
		FString Biome;
		double Expected = -1.0;
		(*Vegetation)->TryGetStringField(TEXT("biome_graph"), Biome);
		(*Vegetation)->TryGetNumberField(TEXT("instances"), Expected);
		VegetationRow->SetBoolField(TEXT("asked"), !Biome.IsEmpty());
		if (!Biome.IsEmpty() && LoadObject<UObject>(nullptr, *Biome) == nullptr)
		{
			Error = FString::Printf(
				TEXT("vegetation.biome_asset: the scene's vegetation was generated by the PCG graph %s, ")
				TEXT("which does not load on this machine"), *Biome);
			return false;
		}
		if (!Biome.IsEmpty() && Expected >= 0.0 && static_cast<int32>(Expected) != VegetationInstances)
		{
			Error = FString::Printf(
				TEXT("vegetation.count_mismatch: the scene's build generated %d vegetation instances ")
				TEXT("and the loaded level holds %d; build the scene again"),
				static_cast<int32>(Expected), VegetationInstances);
			return false;
		}
		VegetationRow->SetStringField(TEXT("biome_graph"), Biome);
	}
	VegetationRow->SetBoolField(TEXT("drawn"), VegetationComponents > 0);
	VegetationRow->SetNumberField(TEXT("components"), VegetationComponents);
	VegetationRow->SetNumberField(TEXT("instances"), VegetationInstances);
	VegetationRow->SetNumberField(TEXT("pcg_components"), PcgComponents);
	VegetationRow->SetStringField(TEXT("object_id"), FlightSimWorld::VegetationObjectId);
	VegetationRow->SetStringField(TEXT("placement"), TEXT("synthetic: densities are scene dressing"));
	WorldApplied->SetObjectField(TEXT("vegetation"), VegetationRow);

	// 8. Buildings and the runway: counted, their documents' digests recorded
	// (matched against the card's world block's by the sidecar clause above).
	for (const TCHAR* Key : {TEXT("buildings"), TEXT("runway")})
	{
		const bool bBuildings = FCString::Strcmp(Key, TEXT("buildings")) == 0;
		TSharedPtr<FJsonObject> Entry = NewRecord();
		const TSharedPtr<FJsonObject>* Block = nullptr;
		FString Digest;
		const bool bAsked = Doc->TryGetObjectField(Key, Block) && Block != nullptr && Block->IsValid();
		if (bAsked)
		{
			(*Block)->TryGetStringField(TEXT("document_sha256"), Digest);
		}
		const int32 Components = bBuildings ? BuildingComponents : RunwayComponents;
		Entry->SetBoolField(TEXT("asked"), bAsked);
		Entry->SetBoolField(TEXT("drawn"), Components > 0);
		Entry->SetNumberField(TEXT("components"), Components);
		Entry->SetStringField(TEXT("document_sha256"), Digest);
		if (bBuildings)
		{
			Entry->SetStringField(TEXT("object_id"), FlightSimWorld::BuildingObjectId);
		}
		else
		{
			Entry->SetStringField(TEXT("stencil"), TEXT("the terrain's int_id (the runway is ground)"));
			Entry->SetStringField(TEXT("material"), SceneRunwayMaterialPath);
		}
		WorldApplied->SetObjectField(Key, Entry);
	}

	// 9. The land-cover ID pass's registration: the class-code raster shares
	// the bake grid, so its NW cell and its steps are measured through the
	// same georeferencing (never assumed).
	const TSharedPtr<FJsonObject>* ClassMap = nullptr;
	TSharedPtr<FJsonObject> LandcoverRow = NewRecord();
	LandcoverRow->SetBoolField(TEXT("asked"), false);
	if (Doc->TryGetObjectField(TEXT("class_map"), ClassMap) && ClassMap != nullptr && ClassMap->IsValid())
	{
		double MapWidth = 0.0, MapHeight = 0.0;
		(*ClassMap)->TryGetStringField(TEXT("asset"), Landcover.ClassMapAsset);
		(*ClassMap)->TryGetStringField(TEXT("sha256"), Landcover.ClassMapSha256);
		(*ClassMap)->TryGetNumberField(TEXT("width"), MapWidth);
		(*ClassMap)->TryGetNumberField(TEXT("height"), MapHeight);
		if (static_cast<int32>(MapWidth) != Terrain.Width || static_cast<int32>(MapHeight) != Terrain.Height)
		{
			return Stale(FString::Printf(
				TEXT("the class map is %dx%d and the bake %dx%d; the class map shares the bake's grid"),
				static_cast<int32>(MapWidth), static_cast<int32>(MapHeight), Terrain.Width, Terrain.Height));
		}
		Landcover.ClassMap = LoadObject<UTexture>(nullptr, *Landcover.ClassMapAsset);
		FVector NorthWest, OneEast, OneSouth;
		Options.GeoReferencing->ProjectedToEngine(
			FVector(Terrain.OriginXMetres, Terrain.OriginYMetres, 0.0), NorthWest);
		Options.GeoReferencing->ProjectedToEngine(
			FVector(Terrain.OriginXMetres + Pixel, Terrain.OriginYMetres, 0.0), OneEast);
		Options.GeoReferencing->ProjectedToEngine(
			FVector(Terrain.OriginXMetres, Terrain.OriginYMetres - Pixel, 0.0), OneSouth);
		Landcover.OriginCm = NorthWest;
		Landcover.CellXCm = OneEast.X - NorthWest.X;
		Landcover.CellYCm = OneSouth.Y - NorthWest.Y;
		Landcover.SkewCm = FMath::Abs(OneEast.Y - NorthWest.Y) + FMath::Abs(OneSouth.X - NorthWest.X);
		Landcover.GridWidth = Terrain.Width;
		Landcover.GridHeight = Terrain.Height;
		Landcover.bReady = Landcover.ClassMap != nullptr;
		LandcoverRow->SetBoolField(TEXT("asked"), true);
		LandcoverRow->SetStringField(TEXT("class_map_asset"), Landcover.ClassMapAsset);
		LandcoverRow->SetStringField(TEXT("class_map_sha256"), Landcover.ClassMapSha256);
		LandcoverRow->SetBoolField(TEXT("class_map_loaded"), Landcover.ClassMap != nullptr);
		LandcoverRow->SetNumberField(TEXT("cell_x_cm"), Landcover.CellXCm);
		LandcoverRow->SetNumberField(TEXT("cell_y_cm"), Landcover.CellYCm);
		LandcoverRow->SetNumberField(TEXT("skew_cm"), Landcover.SkewCm);
		LandcoverRow->SetNumberField(TEXT("grid_width"), Landcover.GridWidth);
		LandcoverRow->SetNumberField(TEXT("grid_height"), Landcover.GridHeight);
		LandcoverRow->SetNumberField(TEXT("layers"), SceneLayers.Num());
		LandcoverRow->SetStringField(TEXT("material"), SceneLandcoverMaterialPath);
		LandcoverRow->SetStringField(TEXT("sampling"),
			TEXT("the class-code raster (the bake grid's majority code) as an 8-bit nearest-filtered, ")
			TEXT("no-mip, non-sRGB texture at the pixel's world position; not an argmax of blended ")
			TEXT("Landscape weights"));
	}
	WorldApplied->SetObjectField(TEXT("land_cover"), LandcoverRow);

	// 10. The imagery drape on the Landscape (M_Landscape's Imagery
	// parameter), and whether its texture streams as a virtual texture.
	const TSharedPtr<FJsonObject>* Imagery = nullptr;
	TSharedPtr<FJsonObject> ImageryRow = NewRecord();
	ImageryRow->SetBoolField(TEXT("asked"), false);
	ImageryRow->SetBoolField(TEXT("drawn"), false);
	if (Doc->TryGetObjectField(TEXT("imagery"), Imagery) && Imagery != nullptr && Imagery->IsValid())
	{
		FString Asset, Digest;
		(*Imagery)->TryGetStringField(TEXT("asset"), Asset);
		(*Imagery)->TryGetStringField(TEXT("sha256"), Digest);
		const UTexture2D* Drape = LoadObject<UTexture2D>(nullptr, *Asset);
		ImageryRow->SetBoolField(TEXT("asked"), true);
		ImageryRow->SetBoolField(TEXT("drawn"), Drape != nullptr);
		ImageryRow->SetStringField(TEXT("asset"), Asset);
		ImageryRow->SetStringField(TEXT("sha256"), Digest);
		ImageryRow->SetBoolField(TEXT("virtual_texture"), Drape != nullptr && Drape->VirtualTextureStreaming);
		ImageryRow->SetStringField(TEXT("route"), TEXT("the Landscape's material (M_Landscape Imagery)"));
	}
	WorldApplied->SetObjectField(TEXT("imagery"), ImageryRow);

	// The row itself: what was loaded and where.
	Row->SetBoolField(TEXT("drawn"), true);
	Row->SetStringField(TEXT("sha256_tag"), TagSha);
	Row->SetStringField(TEXT("bake_sha256"), Terrain.Sha256);
	Row->SetStringField(TEXT("card_terrain_sha256"), CardSha);
	Row->SetBoolField(TEXT("matched"), true);
	Row->SetStringField(TEXT("actor"), SceneLandscape->GetName());
	Row->SetBoolField(TEXT("nanite_enabled"), SceneLandscape->IsNaniteEnabled());
	Row->SetNumberField(TEXT("components"), SceneLandscape->LandscapeComponents.Num());
	const TSharedPtr<FJsonObject>* LandscapeBlock = nullptr;
	if (Doc->TryGetObjectField(TEXT("landscape"), LandscapeBlock) && LandscapeBlock != nullptr)
	{
		double Posting = 0.0, Resolution = 0.0;
		(*LandscapeBlock)->TryGetNumberField(TEXT("posting_m"), Posting);
		(*LandscapeBlock)->TryGetNumberField(TEXT("resolution"), Resolution);
		Row->SetNumberField(TEXT("posting_m"), Posting);
		Row->SetNumberField(TEXT("resolution"), Resolution);
	}
	TArray<TSharedPtr<FJsonValue>> OffsetJson;
	OffsetJson.Add(MakeShared<FJsonValueNumber>(Origin.X));
	OffsetJson.Add(MakeShared<FJsonValueNumber>(Origin.Y));
	OffsetJson.Add(MakeShared<FJsonValueNumber>(Origin.Z));
	Row->SetArrayField(TEXT("level_offset_cm"), OffsetJson);
	Row->SetStringField(TEXT("placement"),
		TEXT("rigid: the level's MSL heights offset by the engine position of MSL 0 under the ")
		TEXT("Landscape's first sample; no planet curvature (the procedural route projects every ")
		TEXT("vertex instead)"));
	TerrainPostingMetres = 0.0;
	if (LandscapeBlock != nullptr)
	{
		(*LandscapeBlock)->TryGetNumberField(TEXT("posting_m"), TerrainPostingMetres);
	}
	UE_LOG(LogFlightSimRender, Display,
	       TEXT("scene level %s: Landscape %s (sha tag %s...), %d vegetation / %d building / %d runway ")
	       TEXT("component(s), %d PCG component(s), class map %s"),
	       *SceneLevel, *SceneLandscape->GetName(), *TagSha.Left(12), VegetationComponents,
	       BuildingComponents, RunwayComponents, PcgComponents,
	       Landcover.bReady ? TEXT("loaded") : TEXT("absent"));
	return true;
}

void FFlightSimVisualScene::ApplyBeautyPostProcess(USceneCaptureComponent2D* Capture)
{
	FPostProcessSettings& Settings = Capture->PostProcessSettings;
	Settings.bOverride_DynamicGlobalIlluminationMethod = true;
	Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::Lumen;
	Settings.bOverride_ReflectionMethod = true;
	Settings.ReflectionMethod = EReflectionMethod::Lumen;
}
