// The beauty look (look-dev lane): light, exposure, grade and lens applied to
// the BEAUTY capture of a -quality=beauty render, from the -beauty-look=
// sidecar core/scene/beauty_look.py writes. VISUAL ONLY.
//
// What it guarantees:
//   * measure renders never reach it (FFlightSimVisualScene::
//     ApplyBeautyPostProcess is called only under -Visual -quality=beauty),
//     and a beauty render WITHOUT -beauty-look= gets exactly the V0 beauty
//     overrides (Lumen GI + Lumen reflections) and nothing else, so
//     gate6_visual.py --quality beauty is unchanged;
//   * the field of view is never touched: the focal length is DERIVED from
//     the capture's own FOV and recorded;
//   * label captures (mask, class, depth, boxes) are separate captures of
//     the same frame with their own post-process settings; nothing here is
//     copied onto them, and this adds no visual-only actor (nothing to add
//     to BeautyOnlyActors, no occluder absent from the masks);
//   * every applied value is echoed into render.json "beauty_look", with
//     what was read back off the capture and the sun.
//
// UNCOMPILED when written (the authoring Mac's Xcode is above UE 5.7's
// ceiling). Every engine symbol was checked against the UE 5.7.4 headers on
// that machine; scripts/check_bridge_api.sh's "beauty look" block re-checks
// them before a build is spent.
#pragma once

#include "CoreMinimal.h"

class AActor;
class FJsonObject;
class USceneCaptureComponent2D;

class FFlightSimBeautyLook
{
public:
	// The V0 beauty overrides, then the sidecar named by -beauty-look= in
	// CommandLine (if any). A sidecar that cannot be read or applied leaves
	// LastError() set ("render.beauty_look: ..."); the commandlet refuses
	// the render on it rather than drawing half a look.
	static void Apply(USceneCaptureComponent2D* Capture, const TCHAR* CommandLine);

	// Per frame, just before the beauty capture: on a depth-of-field lens,
	// focus at |capture - subject|; on any lens, track the focal length the
	// capture's FOV implies (a keyframed focal move changes the FOV).
	static void UpdatePerFrame(USceneCaptureComponent2D* Capture, const AActor* Subject);

	// The commandlet's exposure record follows an applied beauty EV100 (no
	// change when the sidecar left the exposure alone).
	static void RecordExposure(FString& ExposureMode, FString& ExposureSource,
	                           double& AppliedEv100, bool& bAppliedEv100);

	// render.json "beauty_look", or null when no sidecar was applied (the
	// manifest then has no such key, as before this lane).
	static TSharedPtr<FJsonObject> Record();

	static const FString& LastError();

	// Pure helpers, pinned by tests/test_beauty_look.py's source checks.
	static double CameraEv100(double ApertureF, double ShutterSeconds, double Iso);
	static double FocalLengthMm(double SensorWidthMm, double HorizontalFovDeg);
};
