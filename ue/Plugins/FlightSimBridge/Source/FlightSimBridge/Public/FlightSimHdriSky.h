// Poly Haven CC0 HDRI skies for the beauty render (round 148, 2026-11-16).
//
// BEAUTY ONLY. Owned by FFlightSimWorldBeauty (FlightSimClouds.h), which the
// render commandlet builds only under -quality=beauty; a measure render never
// constructs it. -look-hdri=auto|light|off (command line or
// FLIGHTSIM_RENDER_SWITCHES; auto by default; another word refuses by name):
//
// * light and auto: the sky light. The commandlet captures the scene's sky as
//   it always has, then SwitchSkyLight reads the captured sky's upward
//   irradiance back from the sky light's own SH (what the engine shades with),
//   makes the matched photograph (FlightSimHdriPure::SlotFor: clear noon,
//   golden hour, overcast, rain/storm) the SPECIFIED CUBEMAP, turned so its
//   sun azimuth is the directional light's, at the intensity that gives the
//   same upward irradiance, with hero lighting's lower hemisphere divided by
//   the intensity change (the ground bounce kept), and captures again. The
//   exposure path sees the same fill energy; its direction and colour are the
//   photograph's. No Lumen on the Windows iGPU, so this is the shade's light.
// * auto only: the backdrop. A camera low over the card's ground (world Z,
//   FlightSimHdriPure::BackdropWeight) sees the photograph above the horizon on
//   a translucent sphere centred on it (M_FlightSimHdriBackdrop,
//   assets/shaders/world/hdri_backdrop.hlsl), faded into the SkyAtmosphere and
//   the fog at the horizon, clouds and fog drawn over it. Hidden until the
//   switch, so the sky light never captures it. In BeautyOnlyActors: every
//   label capture hides it; it writes no depth, custom depth or velocity.
// * off: nothing is built and nothing is switched (today's frame exactly).
//
// Python twin: core/scene/hdri_sky.py (tests/test_hdri_sky.py compiles the
// pure block and compares). Every look value is UNCALIBRATED; UNMEASURED until
// the Windows laptop renders it.

#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Engine/TextureCube.h"
#include "UObject/StrongObjectPtr.h"

class AActor;
class FFlightSimVisualScene;
class UMaterialInstanceDynamic;
class UStaticMeshComponent;
class UWorld;

class FLIGHTSIMBRIDGE_API FFlightSimHdriSky
{
public:
	// From the world lane's Apply: the switch, the slot (Preset in
	// FlightSimWorldPure's order), the cubes, and the hidden backdrop sphere.
	// False (with Error) only for a switch word that is not auto, light or off.
	// A missing asset is recorded and the captured sky stays.
	bool Build(UWorld* World, FFlightSimVisualScene& Scene, int32 Preset, double SunElevationDeg,
	           const FString& Switches, FString& Error);

	// Right after the sky light's capture-once (commandlet, look-dev). Returns
	// the factor the sky light's intensity was multiplied by (1 when nothing was
	// switched), so the world lane can rescale its lightning pulse base.
	double SwitchSkyLight(UWorld* World, FFlightSimVisualScene& Scene);

	// Per frame: the backdrop follows the camera; its opacity is the camera's
	// height law. Frame gets hdri_backdrop_opacity when a backdrop exists.
	void Advance(const FVector& CameraCm, const TSharedPtr<FJsonObject>& Frame);

	bool WantsSwitch() const { return bWantsSwitch; }

	// look_applied.world_beauty.hdri_sky
	TSharedPtr<FJsonObject> Record;

private:
	int32 Mode = 2;   // FlightSimHdriPure::ModeOff until Build reads the switch
	int32 Slot = -1;
	bool bWantsSwitch = false;
	bool bSwitched = false;
	double SunElevationDeg = 90.0;
	// Held strongly: nothing else references the light cube until the switch.
	TStrongObjectPtr<UTextureCube> LightCube;
	TStrongObjectPtr<UTextureCube> BackdropCube;
	AActor* BackdropActor = nullptr;
	UStaticMeshComponent* BackdropMesh = nullptr;
	UMaterialInstanceDynamic* BackdropMaterial = nullptr;
};
