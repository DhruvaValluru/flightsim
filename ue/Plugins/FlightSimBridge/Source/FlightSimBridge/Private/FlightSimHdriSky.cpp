// Poly Haven CC0 HDRI skies for the beauty render (FlightSimHdriSky.h).
// BEAUTY ONLY, VISUAL ONLY. Names in this file are file-unique (NEXT.md gotcha
// 3: unity builds merge anonymous namespaces). Every engine symbol was read in
// the UE 5.7.4 headers (scripts/check_bridge_api.sh "hdri-sky").

#include "FlightSimHdriSky.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/TextureCube.h"
#include "Engine/World.h"
#include "FlightSimVisualScene.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Math/SHMath.h"
#include "Misc/Parse.h"
#include "RenderingThread.h"
#if WITH_EDITOR
#include "TextureCompiler.h"
#endif

#include <cmath>
#include <cstring>

DEFINE_LOG_CATEGORY_STATIC(LogFlightSimHdriSky, Log, All);

// The tables and laws, dependency-free C++17 so tests/test_hdri_sky.py can
// compile this block alone and compare it with core/scene/hdri_sky.py number
// for number. EVERY look value in it is UNCALIBRATED.
// FLIGHTSIM-HDRI-PURE-BEGIN
namespace FlightSimHdriPure
{
	enum : int
	{
		ModeAuto = 0,
		ModeLight = 1,
		ModeOff = 2,
		ModeCount = 3
	};
	enum : int
	{
		SlotNone = -1,
		SlotClear = 0,
		SlotGolden = 1,
		SlotOvercast = 2,
		SlotStorm = 3,
		SlotCount = 4
	};
	// FlightSimWorldPure's preset order.
	enum : int
	{
		HdriPresetClear = 0,
		HdriPresetHazy = 1,
		HdriPresetOvercast = 2,
		HdriPresetRain = 3,
		HdriPresetStorm = 4,
		HdriPresetCount = 5
	};

	constexpr double GoldenMaxSunDeg = 15.0;
	constexpr double NightSunDeg = -4.0;
	constexpr double MinRatio = 1e-4;
	constexpr double MaxRatio = 1e6;
	constexpr double BackdropFullAglM = 600.0;
	constexpr double BackdropNoneAglM = 1000.0;
	constexpr double BackdropHorizonLowDeg = 1.0;
	constexpr double BackdropHorizonHighDeg = 12.0;
	constexpr double BackdropOpacity = 1.0;
	constexpr double BackdropRadiusKm = 8.0;
	// Opaque scene depth beyond which a pixel is sky (the sphere draws over sky only).
	constexpr double BackdropSkyDepthCm = 1.0e8;
	constexpr int BackdropSortPriority = -110;
	constexpr double BackdropGain = 1.0;
	constexpr double SunHoleDeg = 3.0;
	static_assert(BackdropFullAglM < BackdropNoneAglM, "the backdrop fades out going up");
	static_assert(BackdropHorizonLowDeg < BackdropHorizonHighDeg, "the backdrop fades in above the horizon");
	static_assert(BackdropSortPriority < -101, "the backdrop draws behind the cirrus (-101)");

	inline const char* ModeName(int Mode)
	{
		static const char* const Names[ModeCount] = {"auto", "light", "off"};
		return Mode >= 0 && Mode < ModeCount ? Names[Mode] : "";
	}

	// -1 for a word that is not a mode; an empty word is the default (off: Windows r148
	// at b3174986 turned #1 golden hour cold blue and TDRd #9; auto stays opt-in).
	inline int ModeFrom(const char* Word)
	{
		if (Word == nullptr || Word[0] == '\0')
		{
			return ModeOff;
		}
		for (int Mode = 0; Mode < ModeCount; ++Mode)
		{
			if (std::strcmp(Word, ModeName(Mode)) == 0)
			{
				return Mode;
			}
		}
		return -1;
	}

	inline const char* SlotName(int Slot)
	{
		static const char* const Names[SlotCount] = {"clear", "golden", "overcast", "storm"};
		return Slot >= 0 && Slot < SlotCount ? Names[Slot] : "none";
	}

	// The pins (core/scene/hdri_sky.py HDRIS) and their prepared sidecars
	// (assets/hdri/prepared/<name>_skylight_1k.json).
	inline const char* HdriName(int Slot)
	{
		static const char* const Names[SlotCount] = {
			"qwantani_noon_puresky", "syferfontein_6d_clear_puresky",
			"kloofendal_overcast_puresky", "overcast_soil_puresky"};
		return Slot >= 0 && Slot < SlotCount ? Names[Slot] : "";
	}
	inline double HdriSunLongitudeDeg(int Slot)
	{
		static const double Values[SlotCount] = {36.123, 35.7715, 29.4434, -11.8652};
		return Slot >= 0 && Slot < SlotCount ? Values[Slot] : 0.0;
	}
	inline double HdriSunElevationDeg(int Slot)
	{
		static const double Values[SlotCount] = {49.834, 5.8887, 23.1152, 34.7168};
		return Slot >= 0 && Slot < SlotCount ? Values[Slot] : 0.0;
	}
	inline double HdriClampLuminance(int Slot)
	{
		static const double Values[SlotCount] = {3.9512999057769775, 7.015737533569336, 33.60485076904297,
		                                         47.624351501464844};
		return Slot >= 0 && Slot < SlotCount ? Values[Slot] : 0.0;
	}
	inline double HdriNormalise(int Slot)
	{
		static const double Values[SlotCount] = {5.9927665877470275, 2.460338748663215, 0.8317091822545478,
		                                         0.6978695224998357};
		return Slot >= 0 && Slot < SlotCount ? Values[Slot] : 0.0;
	}
	// The sky light's upward irradiance as a share of the captured sky's, per slot.
	inline double SlotFillGain(int Slot)
	{
		static const double Values[SlotCount] = {1.0, 1.0, 1.0, 1.0};
		return Slot >= 0 && Slot < SlotCount ? Values[Slot] : 1.0;
	}

	inline int SlotFor(int Preset, double SunElevationDeg)
	{
		if (SunElevationDeg < NightSunDeg)
		{
			return SlotNone;
		}
		if (Preset == HdriPresetRain || Preset == HdriPresetStorm)
		{
			return SlotStorm;
		}
		if (Preset == HdriPresetOvercast)
		{
			return SlotOvercast;
		}
		return SunElevationDeg < GoldenMaxSunDeg ? SlotGolden : SlotClear;
	}

	inline double WrapDeg(double Value)
	{
		double Out = std::fmod(Value, 360.0);
		if (Out < 0.0)
		{
			Out += 360.0;
		}
		return Out >= 360.0 ? 0.0 : Out;
	}

	// USkyLightComponent::SourceCubemapAngle that puts the photograph's sun (image
	// longitude HdriLongitudeDeg) at the world direction (SunX, SunY), toward the sun.
	inline double CubemapYawDeg(double HdriLongitudeDeg, double SunX, double SunY)
	{
		const double Pi = 3.14159265358979323846;
		return WrapDeg((HdriLongitudeDeg - 90.0) - std::atan2(SunY, SunX) * 180.0 / Pi);
	}

	inline double Ratio(double CapturedUp, double HdriUp)
	{
		if (!(CapturedUp > 0.0 && HdriUp > 0.0) || !std::isfinite(CapturedUp) || !std::isfinite(HdriUp))
		{
			return 0.0;
		}
		const double R = CapturedUp / HdriUp;
		return R >= MinRatio && R <= MaxRatio ? R : 0.0;
	}

	inline double Intensity(double IntensityNow, double RatioValue, int Slot)
	{
		return IntensityNow * RatioValue * SlotFillGain(Slot);
	}

	inline double LowerHemisphereScale(double IntensityNow, double IntensityHdri)
	{
		return IntensityHdri > 0.0 ? IntensityNow / IntensityHdri : 1.0;
	}

	// Under an overcast or storm photograph no sun reaches the ground, so the ground
	// can return at most LowerCapAlbedo of the sky's own upward irradiance: the
	// lower hemisphere's luminance (cube units, after the switch) is capped at
	// LowerCapAlbedo x the HDRI's upward irradiance / pi. Clear and golden keep
	// hero lighting's sunlit ground. Returns the factor on the lower hemisphere's RGB.
	constexpr double LowerCapAlbedo = 0.25;
	inline double LowerHemisphereCap(int Slot, double LowerLuminance, double HdriUpLuminance)
	{
		if (Slot != SlotOvercast && Slot != SlotStorm)
		{
			return 1.0;
		}
		const double Pi = 3.14159265358979323846;
		const double Cap = LowerCapAlbedo * HdriUpLuminance / Pi;
		return LowerLuminance > Cap && LowerLuminance > 0.0 && Cap >= 0.0 ? Cap / LowerLuminance : 1.0;
	}

	inline double HdriSmoothstep(double Edge0, double Edge1, double X)
	{
		double T = (X - Edge0) / (Edge1 - Edge0);
		T = T < 0.0 ? 0.0 : (T > 1.0 ? 1.0 : T);
		return T * T * (3.0 - 2.0 * T);
	}

	inline double BackdropWeight(int Mode, double CameraAglM)
	{
		if (Mode != ModeAuto)
		{
			return 0.0;
		}
		return BackdropOpacity * (1.0 - HdriSmoothstep(BackdropFullAglM, BackdropNoneAglM, CameraAglM));
	}

	inline double BackdropScale(double RatioValue, double Normalise)
	{
		return Normalise * RatioValue * BackdropGain;
	}

	inline double SunHoleFor(int Slot)
	{
		return Slot == SlotClear || Slot == SlotGolden ? SunHoleDeg : 0.0;
	}

	inline double SunSpanFor(int Slot, double SceneSunElevationDeg)
	{
		if (SunHoleFor(Slot) <= 0.0)
		{
			return 0.0;
		}
		const double D = HdriSunElevationDeg(Slot) - SceneSunElevationDeg;
		return D < 0.0 ? -D : D;
	}
}
// FLIGHTSIM-HDRI-PURE-END

namespace
{
	const TCHAR* const HdriSkyBackdropMaterialPath =
		TEXT("/Game/FlightSim/M_FlightSimHdriBackdrop.M_FlightSimHdriBackdrop");
	constexpr double HdriSkyCmPerMetre = 100.0;

	FString HdriSkyAsset(const TCHAR* Prefix, int32 Slot)
	{
		const FString Name = ANSI_TO_TCHAR(FlightSimHdriPure::HdriName(Slot));
		return FString::Printf(TEXT("/Game/FlightSim/Sky/%s%s.%s%s"), Prefix, *Name, Prefix, *Name);
	}

	UTextureCube* HdriSkyLoadCube(const FString& Path)
	{
		UTextureCube* Cube = LoadObject<UTextureCube>(nullptr, *Path);
#if WITH_EDITOR
		if (Cube != nullptr)
		{
			FTextureCompilingManager::Get().FinishCompilation({Cube});
		}
#endif
		return Cube;
	}

	// The sky light's SH (what the engine shades the diffuse sky light with)
	// evaluated for an upward normal: the upper hemisphere's irradiance (a
	// uniform lower hemisphere projects to exactly 0 there at SH order 3).
	FLinearColor HdriSkyUpwardIrradiance(USkyLightComponent* Sky)
	{
		const FSHVectorRGB3 Map = Sky->GetIrradianceEnvironmentMap();
		const FSHVector3 Transfer = FSHVector3::CalcDiffuseTransfer(FVector(0.0, 0.0, 1.0));
		return Dot(Map, Transfer);
	}

	double HdriSkyLuminance(const FLinearColor& C)
	{
		return 0.2126 * C.R + 0.7152 * C.G + 0.0722 * C.B;
	}

	TSharedPtr<FJsonObject> HdriSkyColourJson(const FLinearColor& C)
	{
		TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
		Out->SetNumberField(TEXT("r"), C.R);
		Out->SetNumberField(TEXT("g"), C.G);
		Out->SetNumberField(TEXT("b"), C.B);
		return Out;
	}

	void HdriSkyCapture(UWorld* World, USkyLightComponent* Sky)
	{
		Sky->SetCaptureIsDirty();
		Sky->MarkRenderStateDirty();
		World->SendAllEndOfFrameUpdates();
		USkyLightComponent::UpdateSkyCaptureContents(World);
		FlushRenderingCommands();
	}
}

bool FFlightSimHdriSky::Build(UWorld* World, FFlightSimVisualScene& Scene, int32 Preset, double InSunElevationDeg,
                              const FString& Switches, FString& Error)
{
	using namespace FlightSimHdriPure;
	Record = MakeShared<FJsonObject>();
	bWantsSwitch = false;
	bSwitched = false;
	SunElevationDeg = InSunElevationDeg;
	FString Word;
	FParse::Value(*Switches, TEXT("look-hdri="), Word);
	Mode = ModeFrom(TCHAR_TO_ANSI(*Word));
	if (Mode < 0)
	{
		Error = FString::Printf(TEXT("world_beauty.hdri_sky: -look-hdri=%s is not one of auto, light, off"), *Word);
		return false;
	}
	Record->SetStringField(TEXT("switch"), ANSI_TO_TCHAR(ModeName(Mode)));
	Record->SetStringField(TEXT("calibration"), TEXT("UNCALIBRATED: set by probe render on the render machine"));
	Record->SetStringField(TEXT("measured"), TEXT("UNMEASURED until a Windows render"));
	Record->SetStringField(TEXT("labels"),
		TEXT("the sky light lights the beauty only; the backdrop sphere is in BeautyOnlyActors (every label capture "
		     "hides it), unlit translucent, no depth, custom depth or velocity, no shadow"));
	if (Mode == ModeOff)
	{
		Record->SetStringField(TEXT("sky"), TEXT("the captured scene (-look-hdri=off: nothing built)"));
		return true;
	}
	USkyLightComponent* Sky = Scene.SkyLightComponent;
	if (Sky == nullptr)
	{
		Record->SetStringField(TEXT("sky"), TEXT("no sky light in the scene"));
		return true;
	}
	if (Sky->SourceType == SLS_SpecifiedCubemap)
	{
		Record->SetStringField(TEXT("sky"), TEXT("the sky light already holds a specified cubemap (the -sky-hdri= probe): left alone"));
		return true;
	}
	Slot = SlotFor(Preset, SunElevationDeg);
	Record->SetNumberField(TEXT("sun_elevation_deg"), SunElevationDeg);
	Record->SetNumberField(TEXT("preset_index"), Preset);
	Record->SetStringField(TEXT("slot"), ANSI_TO_TCHAR(SlotName(Slot)));
	if (Slot == SlotNone)
	{
		Record->SetStringField(TEXT("sky"), TEXT("the captured scene: the sun is below NightSunDeg and no pinned photograph is a night sky"));
		return true;
	}
	Record->SetStringField(TEXT("hdri"), ANSI_TO_TCHAR(HdriName(Slot)));
	Record->SetStringField(TEXT("licence"), TEXT("CC0-1.0 (Poly Haven; assets/hdri/README.md)"));
	const FString LightPath = HdriSkyAsset(TEXT("T_HdriLight_"), Slot);
	LightCube.Reset(HdriSkyLoadCube(LightPath));
	Record->SetStringField(TEXT("light_asset"), LightPath);
	if (!LightCube.IsValid())
	{
		Record->SetStringField(TEXT("sky"),
			TEXT("the captured scene: the HDRI cube did not load (run scripts/ue_create_materials.py in the editor)"));
		return true;
	}
	bWantsSwitch = true;
	Record->SetStringField(TEXT("sky"), TEXT("pending: switched to the HDRI right after the sky light's capture"));

	if (Mode != ModeAuto)
	{
		Record->SetStringField(TEXT("backdrop"), TEXT("none (-look-hdri=light)"));
		return true;
	}
	const FString BackdropPath = HdriSkyAsset(TEXT("T_HdriBackdrop_"), Slot);
	BackdropCube.Reset(HdriSkyLoadCube(BackdropPath));
	UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, HdriSkyBackdropMaterialPath);
	UStaticMesh* SphereMesh = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	if (!BackdropCube.IsValid() || Base == nullptr || SphereMesh == nullptr)
	{
		Record->SetStringField(TEXT("backdrop"),
			!BackdropCube.IsValid() ? TEXT("none: the backdrop cube did not load (scripts/ue_create_materials.py)")
			: Base == nullptr ? TEXT("none: M_FlightSimHdriBackdrop did not load (scripts/ue_create_materials.py)")
			                  : TEXT("none: the engine sphere did not load"));
		return true;
	}
	AActor* Actor = World->SpawnActor<AActor>();
	UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(Actor, TEXT("HdriBackdrop"));
	Actor->SetRootComponent(Mesh);
	Mesh->SetMobility(EComponentMobility::Movable);
	Mesh->SetStaticMesh(SphereMesh);
	Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Mesh->SetCastShadow(false);
	Mesh->SetRenderCustomDepth(false);
	Mesh->SetReceivesDecals(false);
	Mesh->SetTranslucentSortPriority(BackdropSortPriority);
	Mesh->bVisibleInReflectionCaptures = false;
	Mesh->bVisibleInRealTimeSkyCaptures = false;
	Mesh->bVisibleInRayTracing = false;
	UMaterialInstanceDynamic* Material = UMaterialInstanceDynamic::Create(Base, Actor);
	Material->SetTextureParameterValue(TEXT("Sky"), BackdropCube.Get());
	Material->SetScalarParameterValue(TEXT("Scale"), 0.0f);
	Material->SetScalarParameterValue(TEXT("Opacity"), 0.0f);
	Material->SetScalarParameterValue(TEXT("ClampLum"), static_cast<float>(HdriClampLuminance(Slot)));
	Material->SetScalarParameterValue(TEXT("HorizonLowDeg"), static_cast<float>(BackdropHorizonLowDeg));
	Material->SetScalarParameterValue(TEXT("HorizonHighDeg"), static_cast<float>(BackdropHorizonHighDeg));
	Material->SetScalarParameterValue(TEXT("SunHoleDeg"), static_cast<float>(SunHoleFor(Slot)));
	Material->SetScalarParameterValue(TEXT("SunSpanDeg"), static_cast<float>(SunSpanFor(Slot, SunElevationDeg)));
	Material->SetScalarParameterValue(TEXT("SkyDepthCm"), static_cast<float>(BackdropSkyDepthCm));
	Mesh->SetMaterial(0, Material);
	Mesh->RegisterComponent();
	// The engine sphere is 1 m across: scale S draws an S m sphere.
	Actor->SetActorScale3D(FVector(2.0 * BackdropRadiusKm * 1000.0));
	Actor->SetActorLocation(FVector::ZeroVector);   // Advance centres it on the camera
	// Hidden until the switch: the sky light's capture must never see it.
	Actor->SetActorHiddenInGame(true);
	Mesh->SetVisibility(false);
	Scene.BeautyOnlyActors.Add(Actor);
	BackdropActor = Actor;
	BackdropMesh = Mesh;
	BackdropMaterial = Material;
	TSharedPtr<FJsonObject> Backdrop = MakeShared<FJsonObject>();
	Backdrop->SetStringField(TEXT("asset"), BackdropPath);
	Backdrop->SetStringField(TEXT("material"), HdriSkyBackdropMaterialPath);
	Backdrop->SetNumberField(TEXT("radius_km"), BackdropRadiusKm);
	Backdrop->SetNumberField(TEXT("sky_depth_cm"), BackdropSkyDepthCm);
	Backdrop->SetStringField(TEXT("placement"),
		TEXT("a sphere at radius_km (a photographed sky's cloud distance), so the height fog and aerial perspective veil "
		     "it as they would those clouds; drawn over sky pixels only (opaque scene depth beyond sky_depth_cm)"));
	Backdrop->SetNumberField(TEXT("sort_priority"), BackdropSortPriority);
	Backdrop->SetNumberField(TEXT("full_below_agl_m"), BackdropFullAglM);
	Backdrop->SetNumberField(TEXT("none_above_agl_m"), BackdropNoneAglM);
	Backdrop->SetNumberField(TEXT("horizon_low_deg"), BackdropHorizonLowDeg);
	Backdrop->SetNumberField(TEXT("horizon_high_deg"), BackdropHorizonHighDeg);
	Backdrop->SetNumberField(TEXT("clamp_luminance"), HdriClampLuminance(Slot));
	Backdrop->SetNumberField(TEXT("sun_hole_deg"), SunHoleFor(Slot));
	Backdrop->SetNumberField(TEXT("sun_span_deg"), SunSpanFor(Slot, SunElevationDeg));
	Backdrop->SetStringField(TEXT("law"),
		TEXT("per frame (frames[].hdri_backdrop_opacity): full below full_below_agl_m of camera height over the card's "
		     "ground (world Z), none above none_above_agl_m, smoothstep between (hdri_sky.backdrop_weight); hidden "
		     "until the sky light's switch"));
	Record->SetObjectField(TEXT("backdrop"), Backdrop);
	return true;
}

double FFlightSimHdriSky::SwitchSkyLight(UWorld* World, FFlightSimVisualScene& Scene)
{
	using namespace FlightSimHdriPure;
	if (!bWantsSwitch || bSwitched || World == nullptr || !Record.IsValid())
	{
		return 1.0;
	}
	bSwitched = true;
	USkyLightComponent* Sky = Scene.SkyLightComponent;
	TSharedPtr<FJsonObject> Out = MakeShared<FJsonObject>();
	Record->SetObjectField(TEXT("switch_result"), Out);
	if (Sky == nullptr || !LightCube.IsValid())
	{
		Record->SetStringField(TEXT("sky"), TEXT("the captured scene: no sky light or cube at the switch"));
		return 1.0;
	}
	if (Sky->GetProcessedSkyTexture() == nullptr)
	{
		Record->SetStringField(TEXT("sky"),
			TEXT("the captured scene: the capture produced no processed texture, so no irradiance to match"));
		return 1.0;
	}
	FlushRenderingCommands();
	const FLinearColor CapturedUp = HdriSkyUpwardIrradiance(Sky);
	const double IntensityNow = Sky->Intensity;
	const FLinearColor LowerNow = Sky->LowerHemisphereColor;
	const float AngleNow = Sky->SourceCubemapAngle;
	Out->SetObjectField(TEXT("captured_upward_irradiance"), HdriSkyColourJson(CapturedUp));
	Out->SetNumberField(TEXT("intensity_before"), IntensityNow);

	// The sun's world direction (toward the sun) for the yaw.
	FVector SunToward(0.0, 0.0, 1.0);
	if (Scene.Sun != nullptr)
	{
		SunToward = -Scene.Sun->GetActorForwardVector();
	}
	const double Yaw = CubemapYawDeg(HdriSunLongitudeDeg(Slot), SunToward.X, SunToward.Y);
	Out->SetNumberField(TEXT("cubemap_yaw_deg"), Yaw);
	Out->SetNumberField(TEXT("hdri_sun_longitude_deg"), HdriSunLongitudeDeg(Slot));
	Out->SetNumberField(TEXT("hdri_sun_elevation_deg"), HdriSunElevationDeg(Slot));
	Out->SetNumberField(TEXT("scene_sun_azimuth_xy_deg"),
	                    FMath::RadiansToDegrees(FMath::Atan2(SunToward.Y, SunToward.X)));

	// The HDRI at the same intensity first: its upward irradiance per unit.
	Sky->SourceType = SLS_SpecifiedCubemap;
	Sky->SetCubemap(LightCube.Get());
	Sky->SetSourceCubemapAngle(static_cast<float>(Yaw));
	HdriSkyCapture(World, Sky);
	const FLinearColor HdriUp = HdriSkyUpwardIrradiance(Sky);
	const double R = Ratio(HdriSkyLuminance(CapturedUp), HdriSkyLuminance(HdriUp));
	Out->SetObjectField(TEXT("hdri_upward_irradiance_per_unit"), HdriSkyColourJson(HdriUp));
	Out->SetNumberField(TEXT("ratio"), R);
	if (R <= 0.0)
	{
		// Put the captured sky back exactly.
		Sky->SourceType = SLS_CapturedScene;
		Sky->SetCubemap(nullptr);
		Sky->SetSourceCubemapAngle(AngleNow);
		HdriSkyCapture(World, Sky);
		Record->SetStringField(TEXT("sky"),
			TEXT("the captured scene: the irradiance ratio was unusable (hdri_sky.hdri_ratio), the capture taken again"));
		return 1.0;
	}
	const double IntensityHdri = Intensity(IntensityNow, R, Slot);
	const double LowerScale = LowerHemisphereScale(IntensityNow, IntensityHdri);
	Sky->SetIntensity(static_cast<float>(IntensityHdri));
	if (Sky->bLowerHemisphereIsBlack)
	{
		// RGB only: the alpha is the capture's lerp weight to the solid colour
		// (1: a full replacement, ReflectionEnvironmentShaders.usf), never scaled.
		FLinearColor Lower = LowerNow * static_cast<float>(LowerScale);
		const double Cap = LowerHemisphereCap(Slot, HdriSkyLuminance(Lower), HdriSkyLuminance(HdriUp));
		Lower = Lower * static_cast<float>(Cap);
		Lower.A = LowerNow.A;
		Sky->SetLowerHemisphereColor(Lower);
		Out->SetNumberField(TEXT("lower_hemisphere_cap"), Cap);
		Out->SetNumberField(TEXT("ground_albedo_implied_before"),
			HdriSkyLuminance(CapturedUp) > 0.0 ? PI * HdriSkyLuminance(LowerNow) / HdriSkyLuminance(CapturedUp) : 0.0);
		UE_LOG(LogFlightSimHdriSky, Display, TEXT("hdri sky: lower hemisphere implied albedo %.3f, cap factor %.3f"),
		       HdriSkyLuminance(CapturedUp) > 0.0 ? PI * HdriSkyLuminance(LowerNow) / HdriSkyLuminance(CapturedUp) : 0.0, Cap);
	}
	HdriSkyCapture(World, Sky);
	const FLinearColor Final = HdriSkyUpwardIrradiance(Sky);
	Out->SetNumberField(TEXT("intensity"), Sky->Intensity);
	Out->SetNumberField(TEXT("fill_gain"), SlotFillGain(Slot));
	Out->SetNumberField(TEXT("lower_hemisphere_scale"), LowerScale);
	Out->SetObjectField(TEXT("lower_hemisphere_before"), HdriSkyColourJson(LowerNow));
	Out->SetObjectField(TEXT("lower_hemisphere"), HdriSkyColourJson(Sky->LowerHemisphereColor));
	Out->SetObjectField(TEXT("final_upward_irradiance_x_intensity"), HdriSkyColourJson(Final * Sky->Intensity));
	Out->SetObjectField(TEXT("captured_upward_irradiance_x_intensity"), HdriSkyColourJson(CapturedUp * IntensityNow));
	Out->SetBoolField(TEXT("processed_texture"), Sky->GetProcessedSkyTexture() != nullptr);
	Out->SetStringField(TEXT("basis"),
		TEXT("intensity = intensity_before x (captured upward irradiance / the HDRI's, luminance, both the sky light's SH "
		     "at +Z) x fill_gain; the lower hemisphere divided by the intensity change (baked into the cube before the "
		     "intensity), and under an overcast or storm photograph capped at LowerCapAlbedo x the sky's upward "
		     "irradiance / pi (no sun reaches that ground: hdri_sky.lower_hemisphere_cap); yaw puts the photograph's sun at the directional light's azimuth (hdri_sky.cubemap_yaw_deg)"));
	Record->SetStringField(TEXT("sky"), TEXT("the HDRI (specified cubemap)"));

	if (BackdropMaterial != nullptr && BackdropActor != nullptr && BackdropMesh != nullptr)
	{
		const double Scale = BackdropScale(R, HdriNormalise(Slot));
		BackdropMaterial->SetScalarParameterValue(TEXT("YawDeg"), static_cast<float>(Yaw));
		BackdropMaterial->SetScalarParameterValue(TEXT("Scale"), static_cast<float>(Scale));
		BackdropActor->SetActorHiddenInGame(false);
		BackdropMesh->SetVisibility(true);
		Out->SetNumberField(TEXT("backdrop_scale"), Scale);
		Out->SetNumberField(TEXT("backdrop_normalise"), HdriNormalise(Slot));
	}
	UE_LOG(LogFlightSimHdriSky, Display, TEXT("hdri sky: %s (%s), yaw %.1f deg, ratio %.4g, intensity %.4g -> %.4g"),
	       ANSI_TO_TCHAR(HdriName(Slot)), ANSI_TO_TCHAR(SlotName(Slot)), Yaw, R, IntensityNow, IntensityHdri);
	return IntensityNow > 0.0 ? IntensityHdri / IntensityNow : 1.0;
}

void FFlightSimHdriSky::Advance(const FVector& CameraCm, const TSharedPtr<FJsonObject>& Frame)
{
	using namespace FlightSimHdriPure;
	if (BackdropActor == nullptr || BackdropMaterial == nullptr)
	{
		return;
	}
	BackdropActor->SetActorLocation(CameraCm);
	const double Weight = bSwitched ? BackdropWeight(Mode, CameraCm.Z / HdriSkyCmPerMetre) : 0.0;
	BackdropMaterial->SetScalarParameterValue(TEXT("Opacity"), static_cast<float>(Weight));
	if (BackdropMesh != nullptr)
	{
		BackdropMesh->SetVisibility(bSwitched && Weight > 0.0);
	}
	if (Frame.IsValid())
	{
		Frame->SetNumberField(TEXT("hdri_backdrop_opacity"), Weight);
	}
}
