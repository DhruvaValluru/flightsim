// High-sky effects lane (2026-11-15): the beauty-only rainbow
// (FFlightSimVisualScene::ApplyBeautySkyFx) and the switches of both sky effects.
// The pure laws are FlightSimSkyFx.h's (core/sky/sky_fx.py's twin); the in-cloud
// lightning flash itself is set in FlightSimWeather.cpp (Advance), where the
// storm cell's material lives.
#include "FlightSimSkyFx.h"
#include "FlightSimVisualScene.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/PlatformMisc.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

namespace
{
	const TCHAR* const SkyFxRainbowMaterialPath = TEXT("/Game/FlightSim/M_FlightSimRainbow.M_FlightSimRainbow");
	constexpr double SkyFxCmPerMetre = 100.0;

	FString SkyFxSwitches()
	{
		// The command line first, then FLIGHTSIM_RENDER_SWITCHES (what
		// visual_fix_round.ps1 -Switches sets), as -look-cirrus= is read.
		return FString(FCommandLine::Get()) + TEXT(" ")
			+ FPlatformMisc::GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"));
	}
}

bool FlightSimSkyFx::ParseRainbow(bool& bOutOn, FString& Error)
{
	FString Word = TEXT("on");
	FParse::Value(*SkyFxSwitches(), TEXT("look-rainbow="), Word);
	if (Word == TEXT("on") || Word == TEXT("off"))
	{
		bOutOn = Word == TEXT("on");
		return true;
	}
	Error = FString::Printf(TEXT("sky_fx.rainbow: -look-rainbow=%s is not on or off"), *Word);
	return false;
}

bool FlightSimSkyFx::ParseRainbowShade(bool& bOutCover, FString& Error)
{
	FString Word = TEXT("cover");
	FParse::Value(*SkyFxSwitches(), TEXT("look-rainbow-shade="), Word);
	if (Word == TEXT("cover") || Word == TEXT("off"))
	{
		bOutCover = Word == TEXT("cover");
		return true;
	}
	Error = FString::Printf(TEXT("sky_fx.rainbow_shade: -look-rainbow-shade=%s is not cover or off"), *Word);
	return false;
}

bool FlightSimSkyFx::ParseCloudFlash(int& OutMode, FString& Error)
{
	FString Word = TEXT("schedule");
	FParse::Value(*SkyFxSwitches(), TEXT("look-cloud-flash="), Word);
	if (Word == TEXT("off"))
	{
		OutMode = FlightSimSkyFxPure::CloudFlashOff;
	}
	else if (Word == TEXT("schedule"))
	{
		OutMode = FlightSimSkyFxPure::CloudFlashSchedule;
	}
	else if (Word == TEXT("on"))
	{
		OutMode = FlightSimSkyFxPure::CloudFlashOn;
	}
	else
	{
		Error = FString::Printf(TEXT("sky_fx.cloud_flash: -look-cloud-flash=%s is not off, schedule or on"), *Word);
		return false;
	}
	return true;
}

void FFlightSimVisualScene::ApplyBeautySkyFx(UWorld* World, const TSharedPtr<FJsonObject>& Beauty)
{
	using namespace FlightSimSkyFxPure;
	TSharedPtr<FJsonObject> Row = MakeShared<FJsonObject>();
	if (Beauty.IsValid())
	{
		Beauty->SetObjectField(TEXT("sky_fx"), Row);
	}
	if (AActor* Old = RainbowActor.Get(); IsValid(Old))
	{
		BeautyOnlyActors.Remove(Old);
		Old->Destroy();
	}
	RainbowActor.Reset();
	// The beauty look is visual only: a bad word is recorded, never refused
	// (the label passes cannot depend on it).
	bool bOn = true;
	FString Error;
	if (!FlightSimSkyFx::ParseRainbow(bOn, Error))
	{
		Row->SetStringField(TEXT("rainbow"), Error);
		bOn = false;
	}
	double RateMmh = 0.0;
	if (WeatherLook.IsValid())
	{
		WeatherLook->TryGetNumberField(TEXT("rain_rate_mmh"), RateMmh);
	}
	// The light travels along the sun actor's forward axis; the sun is opposite.
	const double SunElevationDeg = Sun != nullptr
		? FMath::RadiansToDegrees(FMath::Asin(FMath::Clamp(-Sun->GetActorForwardVector().Z, -1.0, 1.0)))
		: -90.0;
	// The bow is lit by direct sun only (SkyAtmosphereLightIlluminance is the
	// clear-sky beam): dim it by the clear share of the sun's line of sight
	// through the card's layers (the storm's 0.95 deck leaves 5 %).
	bool bShade = true;
	FString ShadeError;
	if (!FlightSimSkyFx::ParseRainbowShade(bShade, ShadeError))
	{
		Row->SetStringField(TEXT("rainbow_shade"), ShadeError);
	}
	const double SunTransmittance = bShade
		? RainbowSunTransmittance(SkyFxCloudCovers.GetData(), SkyFxCloudCovers.Num()) : 1.0;
	const double Strength = RainbowStrength(bOn, RateMmh, SunElevationDeg) * SunTransmittance;
	Row->SetBoolField(TEXT("rainbow_shade_cover"), bShade);
	Row->SetNumberField(TEXT("rainbow_sun_transmittance"), SunTransmittance);
	Row->SetBoolField(TEXT("rainbow_switch_on"), bOn);
	Row->SetNumberField(TEXT("rainbow_rain_rate_mmh"), RateMmh);
	Row->SetNumberField(TEXT("rainbow_sun_elevation_deg"), SunElevationDeg);
	Row->SetNumberField(TEXT("rainbow_strength"), Strength);
	if (Strength <= 0.0 || World == nullptr)
	{
		Row->SetStringField(TEXT("rainbow"), !bOn ? TEXT("off") : RateMmh <= 0.0 ? TEXT("no rain on the weather look")
		                                     : SunElevationDeg <= 0.0 ? TEXT("the sun is at or below the horizon")
		                                     : TEXT("no direct sun through the cloud cover"));
		return;
	}
	UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, SkyFxRainbowMaterialPath);
	UStaticMesh* SphereMesh = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	if (Material == nullptr || SphereMesh == nullptr)
	{
		Row->SetStringField(TEXT("rainbow"), Material == nullptr ? TEXT("M_FlightSimRainbow absent (scripts/ue_create_materials.py)")
		                                                       : TEXT("the engine sphere did not load"));
		return;
	}
	const double RainTopM = SkyFxRainTopM > 0.0 ? SkyFxRainTopM : RainbowDefaultRainTopM;
	AActor* Bow = World->SpawnActor<AActor>();
	RainbowActor = Bow;
	UStaticMeshComponent* Sphere = NewObject<UStaticMeshComponent>(Bow, TEXT("Rainbow"));
	Bow->SetRootComponent(Sphere);
	Sphere->SetMobility(EComponentMobility::Movable);
	Sphere->SetStaticMesh(SphereMesh);
	Sphere->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Sphere->SetCastShadow(false);
	Sphere->SetRenderCustomDepth(false);
	UMaterialInstanceDynamic* Instance = UMaterialInstanceDynamic::Create(Material, Bow);
	Instance->SetScalarParameterValue(TEXT("Strength"), static_cast<float>(Strength));
	Instance->SetScalarParameterValue(TEXT("PrimaryPeak"), static_cast<float>(RainbowPrimaryPeak));
	Instance->SetScalarParameterValue(TEXT("InnerGlow"), static_cast<float>(RainbowInnerGlow));
	Instance->SetScalarParameterValue(TEXT("InnerFoldDeg"), static_cast<float>(RainbowInnerFoldDeg));
	Instance->SetScalarParameterValue(TEXT("RainTopCm"), static_cast<float>(RainTopM * SkyFxCmPerMetre));
	Instance->SetScalarParameterValue(TEXT("TopFadeCm"), static_cast<float>(RainbowTopFadeM * SkyFxCmPerMetre));
	Sphere->SetMaterial(0, Instance);
	Sphere->RegisterComponent();
	// The engine sphere is 1 m across: scale S draws an S m sphere, about the
	// scene origin (the aircraft's start, where the weather look's shafts stand).
	Bow->SetActorLocation(FVector::ZeroVector);
	Bow->SetActorScale3D(FVector(2.0 * RainbowRadiusKm * 1000.0));
	BeautyOnlyActors.Add(Bow);
	Row->SetStringField(TEXT("rainbow"), TEXT("drawn"));
	Row->SetNumberField(TEXT("rainbow_rain_top_m"), RainTopM);
	Row->SetNumberField(TEXT("rainbow_radius_km"), RainbowRadiusKm);
	Row->SetStringField(TEXT("basis"),
		TEXT("core/sky/sky_fx.py: Descartes bows over water n(lambda) (Hale & Querry 1973), CIE 1931, secondary "
		     "0.43 of the primary (Lee 1998), gain 1 - exp(-0.25 R^0.63 * 2 km); PrimaryPeak UNCALIBRATED"));
}
