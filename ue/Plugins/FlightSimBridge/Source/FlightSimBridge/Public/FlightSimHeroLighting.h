// Hero lighting (visual overhaul, hero-lighting lane, 2026-11-09): the
// QUALITY of the one sun and the one sky light on a -quality=beauty render.
// VISUAL ONLY, beauty only.
//
// The DIRECTION of the light is not decided here. It comes from the
// scenario's time of day, date and flight heading (core/scene/
// hero_lighting.py solves those per shot with core/environment/sun.py);
// this module never adds a light, never moves the sun and never adds a
// second sun. What it does to the scene's existing sun and sky light:
//   * the sun's source angle at the true solar disc (0.5357 deg) with a
//     small soft angle, so the VSM's SMRT penumbrae are physically soft --
//     unless the run already stated -sun-source-angle= (the rain look's
//     overcast softening), which is kept;
//   * VSM quality cvars (directional resolution bias, page pool, SMRT ray
//     and sample counts);
//   * world-space contact shadows short enough to act only at airframe
//     scale (panel lines, canopy frame, pylons);
//   * the sky light as a REAL-TIME capture, time slicing off, with cloud
//     ambient occlusion, and the lower hemisphere replaced by the ground's
//     radiance from the -hero-lighting= sidecar (albedo x horizontal
//     illuminance / pi, decided in Python);
//   * Lumen: short-range AO and screen traces; reflections with hit
//     lighting when ray tracing is enabled in this process, a screen-trace
//     software fallback otherwise;
//   * light shafts: occlusion and bloom on the sun, volumetric-fog
//     scattering from it;
//   * the atmosphere's sun disc at physical luminance (colour scale 1),
//     hidden (scale 0) when the source angle says the sun is behind
//     overcast. The aureole is the atmosphere's Mie forward lobe, which the
//     world lane owns; its anisotropy is read back and recorded.
//
// Guarantees: measure renders never reach Apply (the commandlet calls it
// only under -Visual -quality=beauty); nothing here moves a pixel's
// geometry, so render.json "hero_lighting" lists no pixel-moving effect;
// ExcludeFromLabel turns light shafts and contact shadows off on every
// label capture once Apply has run (a no-op before, so measure label
// captures are untouched).
//
// UNCOMPILED when written (the authoring Mac cannot build UE 5.7). Every
// engine symbol was grepped in the UE 5.7.4 headers/sources on that
// machine; scripts/check_bridge_api.sh's "hero lighting" block re-checks
// them before a build is spent.
#pragma once

#include "CoreMinimal.h"

class FFlightSimVisualScene;
class FJsonObject;
class USceneCaptureComponent2D;

class FFlightSimHeroLighting
{
public:
	// Apply to the scene's sun and sky light and this process's renderer
	// cvars. CommandLine is the commandlet's Params (it reads
	// -hero-lighting=<sidecar> and -sun-source-angle=). Returns false, with
	// LastError() set ("hero_lighting.sidecar: ..."), when a named sidecar
	// cannot be read; the commandlet refuses the render on it.
	static bool Apply(FFlightSimVisualScene& Scene, USceneCaptureComponent2D* Beauty,
	                  bool bPathTrace, const TCHAR* CommandLine);

	// Called from the commandlet's ConfigureLabelCapture: light shafts and
	// contact shadows off on a label capture once Apply has run.
	static void ExcludeFromLabel(USceneCaptureComponent2D* Label);

	// render.json "hero_lighting", or null when Apply never ran.
	static TSharedPtr<FJsonObject> Record();

	static const FString& LastError();

	// Pure helpers, pinned by tests/test_hero_lighting.py's source checks.
	// Whether a source angle (deg) is wider than a clear-sky sun can be.
	static bool IsOvercastSourceAngle(double SourceAngleDeg);
};
