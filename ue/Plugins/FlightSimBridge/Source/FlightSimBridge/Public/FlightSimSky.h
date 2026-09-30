// The physical sky: sun, moon, stars, clouds and the physical camera, from
// the sky.json sidecar core/sky/plan.py writes (-sky=<path>).
//
// Nothing here chooses a value. Positions, illuminances, EV100, cloud
// placement and post-processing are all computed in Python, pinned by
// tests/test_sky.py, and recorded in the render manifest; this file only
// turns them into engine objects. Without -sky the calibrated legacy
// scene (FFlightSimVisualScene, gotcha 7) renders byte-for-byte as before.
//
// Engine frame (GeoReferencing, and the plugin's actor yaw = heading - 90):
// +X east, +Y SOUTH, +Z up. A body at compass azimuth A, elevation E lies
// along FRotator(E, A - 90, 0); its light travels along FRotator(-E, A + 90, 0).
// (The legacy -sun-azim flag's "azimuth + 180" yaw predates this and is
// kept only for the calibrated renders; see docs/VALIDITY.md.)
//
// What each object is:
// * Sun: the scene's one directional light at 120 klx, atmosphere light 0,
//   per-pixel atmosphere transmittance.
// * Moon: a sphere of the moon's true angular size at its true distance,
//   lit BY THE SUN LIGHT, so its phase and terminator come from geometry;
//   plus a second directional light (atmosphere light 1, disc hidden)
//   carrying the moonlight to the scene.
// * Stars: Hipparcos stars as unlit emissive discs one pixel across, far
//   beyond the moon, luminance conserving each star's illuminance. Opaque,
//   so the atmosphere's aerial perspective and the clouds occlude them.
// * Clouds: UE's volumetric cloud layer, VISUAL ONLY.

#pragma once

#include "CoreMinimal.h"

class ADirectionalLight;
class UExponentialHeightFogComponent;
class USkyAtmosphereComponent;
class UWorld;
struct FEngineShowFlags;
struct FPostProcessSettings;

struct FFlightSimStarBatch
{
	double LuminanceNits = 0.0;
	FLinearColor Color = FLinearColor::White;
	TArray<FVector2D> AzimuthElevationDeg;
};

struct FLIGHTSIMBRIDGE_API FFlightSimSkyPlan
{
	FString SourcePath;
	FString InstantUtc;
	FString TimeBasis;

	double SunAzimuthDeg = 180.0;
	double SunElevationDeg = 45.0;
	double SunIlluminanceLux = 120000.0;
	double SunTransmittanceMinElevationDeg = 90.0;
	bool bSunPerPixelTransmittance = true;

	double MoonAzimuthDeg = 0.0;
	double MoonElevationDeg = -90.0;
	double MoonAngularRadiusDeg = 0.259;
	double MoonDistanceKm = 384400.0;
	double MoonIlluminanceLux = 0.0;
	double MoonAlbedo = 0.12;
	double MoonIlluminatedFraction = 0.0;

	bool bStarsDrawn = false;
	double StarAngularRadiusDeg = 0.043;
	TArray<FFlightSimStarBatch> Stars;

	double Ev100 = 14.0;
	double ExposureBias = 0.0;
	double CameraFstop = 4.0;
	double CameraShutterPerSecond = 60.0;
	double CameraIso = 100.0;

	bool bClouds = false;
	double CloudBottomKm = 2.0;
	double CloudThicknessKm = 3.0;

	FString PostKind = TEXT("external");
	double BloomIntensity = 0.5;
	double LensFlareIntensity = 0.15;
	double VignetteIntensity = 0.3;
	double FilmGrainIntensity = 0.0;
	double ChromaticAberration = 0.0;
	double MotionBlurAmount = 0.0;

	// Verified VIIRS night-lights sidecar (core/terrain/nightlights.py), or
	// empty when the plan records none.
	FString NightLightsSidecarPath;

	// Reads and checks the sidecar. Any missing field is an error by name:
	// a half-read plan would render a sky nobody computed.
	static bool Load(const FString& Path, FFlightSimSkyPlan& Out, FString& Error);

	// Unit vector toward a body, engine frame (see the header comment).
	static FVector Direction(double AzimuthDeg, double ElevationDeg);
	// Rotation of a directional light shining FROM that body.
	static FRotator LightRotation(double AzimuthDeg, double ElevationDeg);
};

class FLIGHTSIMBRIDGE_API FFlightSimSky
{
public:
	// Configures the existing sun, atmosphere and fog, and spawns the moon,
	// its light, the star field and the cloud layer. Fails with a reason if
	// a required engine or project asset is missing.
	bool Build(UWorld* World, const FFlightSimSkyPlan& Plan,
	           ADirectionalLight* Sun, USkyAtmosphereComponent* Atmosphere,
	           UExponentialHeightFogComponent* Fog, FString& Error);

	// Project-wide renderer switches the physical sky needs: Lumen GI and
	// reflections, Virtual Shadow Maps. Set by code for this process only;
	// the calibrated legacy path never calls this.
	static void EnableRendererFeatures();

	// Physical camera (EV100), Lumen, and the preset's lens character.
	static void ApplyPostProcess(FPostProcessSettings& Settings,
	                             const FFlightSimSkyPlan& Plan);
	static void ApplyShowFlags(FEngineShowFlags& Flags);

	int32 StarsDrawn = 0;
	bool bMoonDrawn = false;
	bool bCloudsDrawn = false;
	FString CloudsNote;
	ADirectionalLight* MoonLight = nullptr;
};
