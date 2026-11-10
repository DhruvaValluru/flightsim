// Beauty fallback (visual overhaul round 2, no-lumen-and-machine lane,
// 2026-11-09): the look a -quality=beauty render takes when the process
// cannot run Lumen. VISUAL ONLY, beauty only, never on -quality=pathtrace.
//
// Why: the first real renders (Windows laptop, ef361bd6) ran on Intel
// integrated graphics under D3D11 / PCD3D_SM5. The project asks for Lumen
// GI and reflections, virtual shadow maps and Nanite, and the cvars read
// back 1, but none of them ran: DoesPlatformSupportLumenGI is false on SM5
// unless r.Lumen.Supported.SM5, and DoesPlatformSupportVirtualShadowMaps is
// DoesPlatformSupportNanite. The frames were lit by the sun and a capture-
// once sky light alone: shot b's shadows crushed, shot c almost black.
//
// What ApplyScene / ApplyCapture do (decided once per process, from the engine's own
// queries, never from the cvars):
//   * Lumen GI supported (the DX12 SM6 render host): nothing changes; the
//     record says path "lumen".
//   * Lumen GI NOT supported: the beauty capture's per-view post-process
//     switches GI to Screen Space (SSGI, the engine's standalone screen-
//     space GI, which runs on SM5: ScreenSpaceRayTracing.cpp) and
//     reflections to Screen Space (SSR) at full quality; distance-field AO
//     when the platform and project support distance fields (it is what
//     shadows a movable sky light); the sky light filled up by a constant
//     and given a minimum occlusion so no shadowed pixel is lit by nothing;
//     the capture-once sky light marked dirty so the commandlet's capture
//     (after this) takes the new values.
//   * Virtual shadow maps NOT supported: cascaded shadow maps at their
//     best (more cascades, the larger CSM resolution, the distribution
//     packed towards the camera). Contact shadows stay the hero-lighting
//     lane's (it turns them on for the beauty capture).
//
// -beauty-fallback=auto (default) | force (take the fallback even where
// Lumen runs: the render host's way to probe this path) | off (record
// only). Anything else refuses by name: render.beauty_fallback_mode.
//
// Guarantees: measure renders never reach ApplyScene (the commandlet calls it
// only under -Visual -quality=beauty, not pathtrace); label captures read
// stencil, depth and GBuffer, which none of this changes; nothing here
// moves a pixel's geometry. render.json render_settings.beauty_fallback
// records which path ran, every value asked and read back.
//
// UNCOMPILED when written (the authoring Mac cannot build UE 5.7). Every
// engine symbol was grepped in the UE 5.7.4 headers/sources on that
// machine; scripts/check_bridge_api.sh's "beauty fallback" block re-checks
// them before a build is spent.
#pragma once

#include "CoreMinimal.h"

class FFlightSimVisualScene;
class FJsonObject;
class USceneCaptureComponent2D;

class FFlightSimBeautyFallback
{
public:
	// Decide and apply to the world: renderer cvars, the sky light, the
	// sun's cascades. Called after the scene build and BEFORE the world
	// lane's build, which reads the sky light's intensity as the base of its
	// per-frame lightning pulse (so the fill survives the storm's frames).
	// CommandLine is the commandlet's Params (it reads -beauty-fallback=).
	// Returns false with LastError() set ("render.beauty_fallback_mode: ...")
	// on an unknown mode.
	static bool ApplyScene(FFlightSimVisualScene& Scene, const TCHAR* CommandLine);

	// The per-view half, on the beauty capture once it exists: GI and
	// reflections to screen space. A no-op unless ApplyScene took the
	// fallback.
	static void ApplyCapture(USceneCaptureComponent2D* Beauty);

	// Round 1 hang (2026-11-09), the constrained GPU only (the commandlet's
	// -sky-capture-restore=): for the ONE sky light capture, the scene values
	// ApplyScene replaced go back to the scene's own (ef361bd6's): the sky
	// light's intensity and minimum occlusion, the sun's cascade count and
	// distribution. Resume puts this render's values back right after. The
	// renderer cvars stay (their asks equal the Cinematic level's, which
	// ef361bd6 ran); the returned record reads them back. A no-op before
	// ApplyScene or when already suspended.
	static TSharedPtr<FJsonObject> SuspendForSkyCapture(FFlightSimVisualScene& Scene);
	static void ResumeAfterSkyCapture(FFlightSimVisualScene& Scene);

	// render.json render_settings.beauty_fallback, or null when Apply never ran.
	static TSharedPtr<FJsonObject> Record();

	static const FString& LastError();

	// Pure helper, pinned by tests/test_beauty_fallback.py's source checks:
	// whether the fallback is taken for a mode and the engine's Lumen answer.
	static bool TakesFallback(const FString& Mode, bool bLumenGiSupported);
};
