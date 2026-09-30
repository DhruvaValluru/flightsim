#include "FlightSimSky.h"

#include "FlightSimRenderCommandlet.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/VolumetricCloudComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/Scene.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "HAL/IConsoleManager.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "ShowFlags.h"

namespace
{
	// Per-file-unique names (gotcha 3: unity builds merge these namespaces).
	constexpr double SkyCmPerKm = 100000.0;
	// Stars sit well beyond the moon so the moon occludes them, not the
	// reverse. Float instance transforms at this range keep ~60 m of
	// precision against discs ~800 km across: far below a pixel.
	constexpr double SkyStarDistanceKm = 1.0e6;
	// /Engine/BasicShapes/Sphere is 100 cm across.
	constexpr double SkyEngineSphereRadiusCm = 50.0;
	constexpr int32 SkySupportedVersion = 1;

	bool SkyNumber(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field,
	               double& Out, FString& Error, const TCHAR* Block)
	{
		if (!Object.IsValid() || !Object->TryGetNumberField(Field, Out))
		{
			Error = FString::Printf(TEXT("sky plan: %s.%s missing"), Block, Field);
			return false;
		}
		return true;
	}

	bool SkyObject(const TSharedPtr<FJsonObject>& Root, const TCHAR* Field,
	               TSharedPtr<FJsonObject>& Out, FString& Error)
	{
		const TSharedPtr<FJsonObject>* Found = nullptr;
		if (!Root->TryGetObjectField(Field, Found) || Found == nullptr)
		{
			Error = FString::Printf(TEXT("sky plan: block '%s' missing"), Field);
			return false;
		}
		Out = *Found;
		return true;
	}

	void SkySetCVar(const TCHAR* Name, int32 Value)
	{
		if (IConsoleVariable* Variable =
		        IConsoleManager::Get().FindConsoleVariable(Name))
		{
			Variable->Set(Value, ECVF_SetByCode);
		}
		else
		{
			UE_LOG(LogFlightSimRender, Warning,
			       TEXT("console variable %s not found; the sky manifest's "
			            "lighting block overstates this build"), Name);
		}
	}
}

FVector FFlightSimSkyPlan::Direction(double AzimuthDeg, double ElevationDeg)
{
	return FRotator(ElevationDeg, AzimuthDeg - 90.0, 0.0).Vector();
}

FRotator FFlightSimSkyPlan::LightRotation(double AzimuthDeg, double ElevationDeg)
{
	return FRotator(-ElevationDeg, AzimuthDeg + 90.0, 0.0);
}

bool FFlightSimSkyPlan::Load(const FString& Path, FFlightSimSkyPlan& Out,
                             FString& Error)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		Error = FString::Printf(TEXT("sky plan '%s' unreadable"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		Error = FString::Printf(TEXT("sky plan '%s' is not valid JSON"), *Path);
		return false;
	}
	double Version = 0.0;
	if (!Root->TryGetNumberField(TEXT("sky_version"), Version) ||
	    static_cast<int32>(Version) != SkySupportedVersion)
	{
		Error = FString::Printf(
			TEXT("sky plan '%s' has sky_version %.0f; this build reads %d. "
			     "Refusing to guess at the schema."),
			*Path, Version, SkySupportedVersion);
		return false;
	}
	Out.SourcePath = Path;
	Root->TryGetStringField(TEXT("instant_utc"), Out.InstantUtc);
	Root->TryGetStringField(TEXT("time_basis"), Out.TimeBasis);

	TSharedPtr<FJsonObject> SunJson, MoonJson, StarsJson, ExposureJson, CameraJson,
		CloudsJson, PostJson;
	if (!SkyObject(Root, TEXT("sun"), SunJson, Error) ||
	    !SkyObject(Root, TEXT("moon"), MoonJson, Error) ||
	    !SkyObject(Root, TEXT("stars"), StarsJson, Error) ||
	    !SkyObject(Root, TEXT("exposure"), ExposureJson, Error) ||
	    !SkyObject(ExposureJson, TEXT("camera"), CameraJson, Error) ||
	    !SkyObject(Root, TEXT("clouds"), CloudsJson, Error) ||
	    !SkyObject(Root, TEXT("post_process"), PostJson, Error))
	{
		return false;
	}
	if (!SkyNumber(SunJson, TEXT("azimuth_deg"), Out.SunAzimuthDeg, Error, TEXT("sun")) ||
	    !SkyNumber(SunJson, TEXT("elevation_deg"), Out.SunElevationDeg, Error, TEXT("sun")) ||
	    !SkyNumber(SunJson, TEXT("illuminance_lux"), Out.SunIlluminanceLux, Error, TEXT("sun")) ||
	    !SkyNumber(SunJson, TEXT("transmittance_min_elevation_deg"),
	               Out.SunTransmittanceMinElevationDeg, Error, TEXT("sun")) ||
	    !SkyNumber(MoonJson, TEXT("azimuth_deg"), Out.MoonAzimuthDeg, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("elevation_deg"), Out.MoonElevationDeg, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("angular_radius_deg"), Out.MoonAngularRadiusDeg, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("distance_km"), Out.MoonDistanceKm, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("illuminance_lux"), Out.MoonIlluminanceLux, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("albedo"), Out.MoonAlbedo, Error, TEXT("moon")) ||
	    !SkyNumber(MoonJson, TEXT("illuminated_fraction"), Out.MoonIlluminatedFraction, Error, TEXT("moon")) ||
	    !SkyNumber(StarsJson, TEXT("angular_radius_deg"), Out.StarAngularRadiusDeg, Error, TEXT("stars")) ||
	    !SkyNumber(ExposureJson, TEXT("ev100"), Out.Ev100, Error, TEXT("exposure")) ||
	    !SkyNumber(ExposureJson, TEXT("bias"), Out.ExposureBias, Error, TEXT("exposure")) ||
	    !SkyNumber(CameraJson, TEXT("fstop"), Out.CameraFstop, Error, TEXT("exposure.camera")) ||
	    !SkyNumber(CameraJson, TEXT("shutter_per_s"), Out.CameraShutterPerSecond, Error, TEXT("exposure.camera")) ||
	    !SkyNumber(CameraJson, TEXT("iso"), Out.CameraIso, Error, TEXT("exposure.camera")) ||
	    !SkyNumber(CloudsJson, TEXT("bottom_km"), Out.CloudBottomKm, Error, TEXT("clouds")) ||
	    !SkyNumber(CloudsJson, TEXT("thickness_km"), Out.CloudThicknessKm, Error, TEXT("clouds")) ||
	    !SkyNumber(PostJson, TEXT("bloom_intensity"), Out.BloomIntensity, Error, TEXT("post_process")) ||
	    !SkyNumber(PostJson, TEXT("lens_flare_intensity"), Out.LensFlareIntensity, Error, TEXT("post_process")) ||
	    !SkyNumber(PostJson, TEXT("vignette_intensity"), Out.VignetteIntensity, Error, TEXT("post_process")) ||
	    !SkyNumber(PostJson, TEXT("film_grain_intensity"), Out.FilmGrainIntensity, Error, TEXT("post_process")) ||
	    !SkyNumber(PostJson, TEXT("chromatic_aberration"), Out.ChromaticAberration, Error, TEXT("post_process")) ||
	    !SkyNumber(PostJson, TEXT("motion_blur_amount"), Out.MotionBlurAmount, Error, TEXT("post_process")))
	{
		return false;
	}
	SunJson->TryGetBoolField(TEXT("per_pixel_transmittance"), Out.bSunPerPixelTransmittance);
	StarsJson->TryGetBoolField(TEXT("drawn"), Out.bStarsDrawn);
	CloudsJson->TryGetBoolField(TEXT("enabled"), Out.bClouds);
	PostJson->TryGetStringField(TEXT("kind"), Out.PostKind);

	const TArray<TSharedPtr<FJsonValue>>* Batches = nullptr;
	if (!StarsJson->TryGetArrayField(TEXT("batches"), Batches) || Batches == nullptr)
	{
		Error = TEXT("sky plan: stars.batches missing");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& BatchValue : *Batches)
	{
		const TSharedPtr<FJsonObject>* BatchObject = nullptr;
		if (!BatchValue->TryGetObject(BatchObject) || BatchObject == nullptr)
		{
			Error = TEXT("sky plan: a star batch is not an object");
			return false;
		}
		FFlightSimStarBatch Batch;
		const TArray<TSharedPtr<FJsonValue>>* Colour = nullptr;
		const TArray<TSharedPtr<FJsonValue>>* Positions = nullptr;
		if (!SkyNumber(*BatchObject, TEXT("luminance_nits"), Batch.LuminanceNits,
		               Error, TEXT("stars.batches[]")) ||
		    !(*BatchObject)->TryGetArrayField(TEXT("color"), Colour) ||
		    Colour == nullptr || Colour->Num() != 3 ||
		    !(*BatchObject)->TryGetArrayField(TEXT("az_el_deg"), Positions) ||
		    Positions == nullptr)
		{
			if (Error.IsEmpty())
			{
				Error = TEXT("sky plan: a star batch lacks color/az_el_deg");
			}
			return false;
		}
		Batch.Color = FLinearColor(static_cast<float>((*Colour)[0]->AsNumber()),
		                           static_cast<float>((*Colour)[1]->AsNumber()),
		                           static_cast<float>((*Colour)[2]->AsNumber()));
		for (const TSharedPtr<FJsonValue>& Position : *Positions)
		{
			const TArray<TSharedPtr<FJsonValue>>& Pair = Position->AsArray();
			if (Pair.Num() != 2)
			{
				Error = TEXT("sky plan: a star position is not [az, el]");
				return false;
			}
			Batch.AzimuthElevationDeg.Add(
				FVector2D(Pair[0]->AsNumber(), Pair[1]->AsNumber()));
		}
		Out.Stars.Add(MoveTemp(Batch));
	}

	const TSharedPtr<FJsonObject>* Night = nullptr;
	if (Root->TryGetObjectField(TEXT("night_lights"), Night) && Night != nullptr)
	{
		(*Night)->TryGetStringField(TEXT("sidecar"), Out.NightLightsSidecarPath);
	}
	return true;
}

void FFlightSimSky::EnableRendererFeatures()
{
	// Lumen GI + reflections and Virtual Shadow Maps. The terrain is a
	// procedural mesh (no Nanite, no distance field), so Lumen lights it
	// through screen traces and the sky light, and VSM shadows it as
	// non-Nanite geometry -- what that does and does not buy is stated in
	// docs/VALIDITY.md, and the sky check measures the result.
	SkySetCVar(TEXT("r.DynamicGlobalIlluminationMethod"), 1);
	SkySetCVar(TEXT("r.ReflectionMethod"), 1);
	SkySetCVar(TEXT("r.Shadow.Virtual.Enable"), 1);
}

bool FFlightSimSky::Build(UWorld* World, const FFlightSimSkyPlan& Plan,
                          ADirectionalLight* Sun,
                          USkyAtmosphereComponent* Atmosphere,
                          UExponentialHeightFogComponent* Fog, FString& Error)
{
	// -- sun -----------------------------------------------------------------
	Sun->SetActorRotation(FFlightSimSkyPlan::LightRotation(
		Plan.SunAzimuthDeg, Plan.SunElevationDeg));
	UDirectionalLightComponent* SunLight =
		Cast<UDirectionalLightComponent>(Sun->GetLightComponent());
	SunLight->SetIntensity(static_cast<float>(Plan.SunIlluminanceLux));
	SunLight->SetAtmosphereSunLight(true);
	SunLight->bPerPixelAtmosphereTransmittance = Plan.bSunPerPixelTransmittance;
	SunLight->MarkRenderStateDirty();

	Atmosphere->TransmittanceMinLightElevationAngle =
		static_cast<float>(Plan.SunTransmittanceMinElevationDeg);
	Atmosphere->MarkRenderStateDirty();

	// Legacy fog carries a constant inscattering colour tuned for the 8-lux
	// sun (gotcha 7); at 120 klx that is black by day and would glow blue
	// at night. The physical sky takes the fog's light from the atmosphere
	// instead, which dims with the sun.
	Fog->SetFogInscatteringColor(FLinearColor::Black);
	Fog->SkyAtmosphereAmbientContributionColorScale = FLinearColor::White;
	Fog->MarkRenderStateDirty();

	UStaticMesh* Sphere = LoadObject<UStaticMesh>(
		nullptr, TEXT("/Engine/BasicShapes/Sphere.Sphere"));
	if (Sphere == nullptr)
	{
		Error = TEXT("/Engine/BasicShapes/Sphere.Sphere did not load");
		return false;
	}

	// -- moon ----------------------------------------------------------------
	UMaterialInterface* MoonBase = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Game/FlightSim/M_Moon.M_Moon"));
	UMaterialInterface* StarBase = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Game/FlightSim/M_StarEmissive.M_StarEmissive"));
	if (MoonBase == nullptr || StarBase == nullptr)
	{
		Error = TEXT("/Game/FlightSim/M_Moon or M_StarEmissive is missing. Run "
		             "scripts/ue_create_materials.py (build-time asset step).");
		return false;
	}

	const double MoonDistanceCm = Plan.MoonDistanceKm * SkyCmPerKm;
	AActor* MoonActor = World->SpawnActor<AActor>();
	UStaticMeshComponent* MoonMesh =
		NewObject<UStaticMeshComponent>(MoonActor, TEXT("Moon"));
	MoonActor->SetRootComponent(MoonMesh);
	MoonMesh->SetMobility(EComponentMobility::Movable);
	MoonMesh->SetStaticMesh(Sphere);
	MoonMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	MoonMesh->SetCastShadow(false);
	UMaterialInstanceDynamic* MoonMaterial =
		UMaterialInstanceDynamic::Create(MoonBase, World);
	MoonMaterial->SetScalarParameterValue(TEXT("Albedo"),
	                                      static_cast<float>(Plan.MoonAlbedo));
	MoonMesh->SetMaterial(0, MoonMaterial);
	MoonMesh->RegisterComponent();
	MoonActor->SetActorLocation(
		FFlightSimSkyPlan::Direction(Plan.MoonAzimuthDeg, Plan.MoonElevationDeg)
		* MoonDistanceCm);
	const double MoonRadiusCm =
		MoonDistanceCm * FMath::Tan(FMath::DegreesToRadians(Plan.MoonAngularRadiusDeg));
	MoonActor->SetActorScale3D(FVector(MoonRadiusCm / SkyEngineSphereRadiusCm));
	bMoonDrawn = Plan.MoonElevationDeg > -Plan.MoonAngularRadiusDeg;

	// Moonlight: atmosphere light 1, its engine-drawn disc hidden (the
	// sphere above is the moon; a second, phase-less disc would not be).
	MoonLight = World->SpawnActor<ADirectionalLight>();
	UDirectionalLightComponent* MoonComponent =
		Cast<UDirectionalLightComponent>(MoonLight->GetLightComponent());
	MoonComponent->SetMobility(EComponentMobility::Movable);
	MoonLight->SetActorRotation(FFlightSimSkyPlan::LightRotation(
		Plan.MoonAzimuthDeg, Plan.MoonElevationDeg));
	MoonComponent->SetIntensity(static_cast<float>(Plan.MoonIlluminanceLux));
	MoonComponent->SetLightColor(FLinearColor(0.93f, 0.95f, 1.0f));
	MoonComponent->SetAtmosphereSunLight(true);
	MoonComponent->AtmosphereSunLightIndex = 1;
	MoonComponent->AtmosphereSunDiskColorScale = FLinearColor::Black;
	MoonComponent->bPerPixelAtmosphereTransmittance = true;
	MoonComponent->SetCastShadows(Plan.MoonElevationDeg > 0.0);
	MoonComponent->MarkRenderStateDirty();

	// -- stars ---------------------------------------------------------------
	StarsDrawn = 0;
	if (Plan.bStarsDrawn)
	{
		const double StarDistanceCm = SkyStarDistanceKm * SkyCmPerKm;
		const double StarScale = StarDistanceCm *
			FMath::Tan(FMath::DegreesToRadians(Plan.StarAngularRadiusDeg)) /
			SkyEngineSphereRadiusCm;
		AActor* StarField = World->SpawnActor<AActor>();
		USceneComponent* StarRoot = NewObject<USceneComponent>(StarField, TEXT("Stars"));
		StarField->SetRootComponent(StarRoot);
		StarRoot->SetMobility(EComponentMobility::Movable);
		StarRoot->RegisterComponent();
		int32 BatchIndex = 0;
		for (const FFlightSimStarBatch& Batch : Plan.Stars)
		{
			UInstancedStaticMeshComponent* Instances =
				NewObject<UInstancedStaticMeshComponent>(
					StarField, *FString::Printf(TEXT("StarBatch%d"), BatchIndex++));
			Instances->SetupAttachment(StarRoot);
			Instances->SetMobility(EComponentMobility::Movable);
			Instances->SetStaticMesh(Sphere);
			Instances->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Instances->SetCastShadow(false);
			UMaterialInstanceDynamic* StarMaterial =
				UMaterialInstanceDynamic::Create(StarBase, World);
			StarMaterial->SetVectorParameterValue(TEXT("Color"), Batch.Color);
			StarMaterial->SetScalarParameterValue(
				TEXT("Luminance"), static_cast<float>(Batch.LuminanceNits));
			Instances->SetMaterial(0, StarMaterial);
			Instances->RegisterComponent();
			for (const FVector2D& AzEl : Batch.AzimuthElevationDeg)
			{
				Instances->AddInstance(FTransform(
					FRotator::ZeroRotator,
					FFlightSimSkyPlan::Direction(AzEl.X, AzEl.Y) * StarDistanceCm,
					FVector(StarScale)));
				++StarsDrawn;
			}
		}
	}

	// -- clouds --------------------------------------------------------------
	bCloudsDrawn = false;
	if (Plan.bClouds)
	{
		UMaterialInterface* CloudMaterial = LoadObject<UMaterialInterface>(nullptr,
			TEXT("/Engine/EngineSky/VolumetricClouds/m_SimpleVolumetricCloud_Inst."
			     "m_SimpleVolumetricCloud_Inst"));
		if (CloudMaterial == nullptr)
		{
			// Clouds are an unrequested, labeled-visual embellishment: their
			// absence is recorded in the manifest, not fatal.
			CloudsNote = TEXT("engine cloud material m_SimpleVolumetricCloud_Inst "
			                  "not found in this engine install; no clouds drawn");
			UE_LOG(LogFlightSimRender, Warning, TEXT("%s"), *CloudsNote);
		}
		else
		{
			AVolumetricCloud* Cloud = World->SpawnActor<AVolumetricCloud>();
			UVolumetricCloudComponent* CloudComponent =
				Cloud->FindComponentByClass<UVolumetricCloudComponent>();
			if (CloudComponent == nullptr)
			{
				CloudsNote = TEXT("AVolumetricCloud spawned without its component");
				UE_LOG(LogFlightSimRender, Warning, TEXT("%s"), *CloudsNote);
			}
			else
			{
				CloudComponent->SetLayerBottomAltitude(
					static_cast<float>(Plan.CloudBottomKm));
				CloudComponent->SetLayerHeight(
					static_cast<float>(Plan.CloudThicknessKm));
				CloudComponent->SetMaterial(CloudMaterial);
				bCloudsDrawn = true;
				CloudsNote = TEXT("UE simple volumetric cloud layer (VISUAL ONLY)");
			}
		}
	}

	UE_LOG(LogFlightSimRender, Display,
	       TEXT("physical sky %s: sun %.1f/%.1f deg, moon %.1f/%.1f deg (%.0f%% lit), "
	            "%d stars, EV100 %.2f, clouds %s"),
	       *Plan.InstantUtc, Plan.SunAzimuthDeg, Plan.SunElevationDeg,
	       Plan.MoonAzimuthDeg, Plan.MoonElevationDeg,
	       Plan.MoonIlluminatedFraction * 100.0, StarsDrawn, Plan.Ev100,
	       bCloudsDrawn ? TEXT("on") : TEXT("off"));
	return true;
}

void FFlightSimSky::ApplyPostProcess(FPostProcessSettings& Settings,
                                     const FFlightSimSkyPlan& Plan)
{
	// Physical camera: f/N, 1/S s, ISO -> EV100, plus the compensation
	// that lands the plan's EV100 (UE: effective EV100 = camera - bias).
	// Constant over the clip, as §6.6 requires of any manual exposure.
	Settings.bOverride_AutoExposureMethod = true;
	Settings.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	Settings.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	Settings.AutoExposureApplyPhysicalCameraExposure = true;
	Settings.bOverride_CameraISO = true;
	Settings.CameraISO = static_cast<float>(Plan.CameraIso);
	Settings.bOverride_CameraShutterSpeed = true;
	Settings.CameraShutterSpeed = static_cast<float>(Plan.CameraShutterPerSecond);
	Settings.bOverride_DepthOfFieldFstop = true;
	Settings.DepthOfFieldFstop = static_cast<float>(Plan.CameraFstop);
	// Focal distance 0 disables depth of field: the f-number here is an
	// exposure term, not a request for bokeh.
	Settings.bOverride_DepthOfFieldFocalDistance = true;
	Settings.DepthOfFieldFocalDistance = 0.0f;
	Settings.bOverride_AutoExposureBias = true;
	Settings.AutoExposureBias = static_cast<float>(Plan.ExposureBias);

	Settings.bOverride_DynamicGlobalIlluminationMethod = true;
	Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::Lumen;
	Settings.bOverride_ReflectionMethod = true;
	Settings.ReflectionMethod = EReflectionMethod::Lumen;

	// Lens character (tonemapper left at UE's filmic default, stated).
	Settings.bOverride_BloomIntensity = true;
	Settings.BloomIntensity = static_cast<float>(Plan.BloomIntensity);
	Settings.bOverride_LensFlareIntensity = true;
	Settings.LensFlareIntensity = static_cast<float>(Plan.LensFlareIntensity);
	Settings.bOverride_VignetteIntensity = true;
	Settings.VignetteIntensity = static_cast<float>(Plan.VignetteIntensity);
	Settings.bOverride_FilmGrainIntensity = true;
	Settings.FilmGrainIntensity = static_cast<float>(Plan.FilmGrainIntensity);
	Settings.bOverride_SceneFringeIntensity = true;
	Settings.SceneFringeIntensity = static_cast<float>(Plan.ChromaticAberration);
	Settings.bOverride_MotionBlurAmount = true;
	Settings.MotionBlurAmount = static_cast<float>(Plan.MotionBlurAmount);
}

void FFlightSimSky::ApplyShowFlags(FEngineShowFlags& Flags)
{
	Flags.SetAtmosphere(true);
	Flags.SetFog(true);
	Flags.SetCloud(true);
	Flags.SetBloom(true);
	Flags.SetLensFlares(true);
	Flags.SetVignette(true);
	Flags.SetGrain(true);
	Flags.SetSceneColorFringe(true);
	Flags.SetLumenGlobalIllumination(true);
	Flags.SetLumenReflections(true);
}
