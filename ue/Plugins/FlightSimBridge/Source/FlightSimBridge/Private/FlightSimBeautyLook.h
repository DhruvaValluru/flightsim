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
class FFlightSimVisualScene;
class FJsonObject;
class USceneCaptureComponent2D;

class FFlightSimBeautyLook
{
public:
	// Visual round 5, lane L1 (core/scene/beauty_look.py ENGINE_LOOK): the
	// engine's built-in lighting and post effects, per world preset, each
	// behind a -look-<name>=on|off switch (probes: auto|on|off; auto is off
	// on the constrained GPU) read from the command line and then
	// FLIGHTSIM_RENDER_SWITCHES. Apply() (below) sets the EARLY half on the
	// capture's post-process settings as it reads the sidecar: SSAO, local
	// exposure, bloom (Gaussian; FFT as a probe), the lens flare, the film
	// grain and the filmback. ApplyEngineLook sets the LATE half after the
	// render-path, hero-lighting and no-lumen-fallback hooks, so it is the
	// owner of record of what it touches and reads back what it does not:
	// SSGI / SSR quality and intensities, the sun's cascades, PCSS,
	// distance-field shadows (probe) and contact shadows, the volumetric
	// fog's albedo and grid (probe), and the still's TSR accumulation. A
	// switch with a value it does not take refuses (render.look_switch).
	// Nothing here touches the cloud march. Every value, every mode and
	// every read-back lands in render.json beauty_look.applied.engine_look.
	static bool ApplyEngineLook(FFlightSimVisualScene& Scene, USceneCaptureComponent2D* Beauty,
	                            bool bConstrainedGpu, const TCHAR* Switches);

	// Round 5: the warm-up captures and still samples the look's tsr row
	// asks for (false when no sidecar applied or -look-tsr=off): the
	// commandlet raises its defaults to them, never lowers a stated flag.
	static bool StillAccumulation(int32& WarmupCaptures, int32& StillSamples);

	// The V0 beauty overrides, then the sidecar named by -beauty-look= in
	// CommandLine (if any). A sidecar that cannot be read or applied leaves
	// LastError() set ("render.beauty_look: ..."); the commandlet refuses
	// the render on it rather than drawing half a look.
	static void Apply(USceneCaptureComponent2D* Capture, const TCHAR* CommandLine);

	// Per frame, just before the beauty capture: on a depth-of-field lens,
	// focus at |capture - subject|; on any lens, track the focal length the
	// capture's FOV implies (a keyframed focal move changes the FOV).
	static void UpdatePerFrame(USceneCaptureComponent2D* Capture, const AActor* Subject);

	// aircraft-sharp (visual overhaul round 2): the shutter for this run.
	// A STILL (bStill) is one instant: motion blur off (show flag and
	// MotionBlurAmount 0), so the airframe is tack sharp. A clip keeps the
	// plan's 180-degree shutter. Works with or without a -beauty-look=
	// sidecar (the -sky= plan's motion blur is turned off for a still too)
	// and echoes the decision into the record's applied.camera.
	static void ApplyShutterPolicy(USceneCaptureComponent2D* Capture, bool bStill);

	// The commandlet's exposure record follows an applied beauty EV100 (no
	// change when the sidecar left the exposure alone).
	static void RecordExposure(FString& ExposureMode, FString& ExposureSource,
	                           double& AppliedEv100, bool& bAppliedEv100);

	// Round 2: whether the commandlet meters the beauty frame once before
	// frame 0 (its storm-meter loop), and to what 90th-percentile sRGB luma.
	// True only when this look owns the exposure AND the sidecar's meter row
	// says a deck, or the platform has no Lumen GI. Trigger: "deck" or
	// "no_lumen_gi". Never true without a sidecar (Gate 6 beauty, measure).
	static bool ExposureMeter(double& TargetP90, FString& Trigger);

	// render.json "beauty_look", or null when no sidecar was applied (the
	// manifest then has no such key, as before this lane).
	static TSharedPtr<FJsonObject> Record();

	static const FString& LastError();

	// Pure helpers, pinned by tests/test_beauty_look.py's source checks.
	static double CameraEv100(double ApertureF, double ShutterSeconds, double Iso);
	static double FocalLengthMm(double SensorWidthMm, double HorizontalFovDeg);
};
