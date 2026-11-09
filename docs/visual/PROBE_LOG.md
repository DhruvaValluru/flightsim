## render-path

Lane: render path (FlightSimRenderCommandlet.cpp beauty section,
ue/Config/DefaultEngine.ini, experiments/gate6_visual.py,
experiments/visual_contact_sheet.py, scripts/render_visual_sheet.{ps1,sh}).
Session 2026-11-09, code only: written on a Mac that cannot build or render
(Xcode 27.2 above UE 5.7.4's 26.9 cap, no Cesium). **Nothing below has been
rendered or measured.** Every engine symbol was read in the 5.7.4 source
under `/Users/Shared/Epic Games/UE_5.7/Engine/Source` and is grepped by
`scripts/check_bridge_api.sh` (the "render-path lane" block).

### Decisions

1. **TSR never ran in beauty (V0 audit finding).** `USceneCaptureComponent2D`'s
   constructor sets `ShowFlags.TemporalAA = false`, and
   `FSceneView::SetupAntiAliasingMethod` falls back from TSR to FXAA when that
   flag is clear. `r.AntiAliasingMethod=4` on its own gave the beauty capture
   FXAA. Beauty now calls `Capture->ShowFlags.SetTemporalAA(true)`. TSR history
   and Lumen both need a view state; the capture has one because
   `bAlwaysPersistRenderingState` is set, which also makes the view family
   realtime (`SceneCaptureRendering.cpp`).
2. **Lumen inside the capture** works only through the capture's
   post-process override, which `ApplyBeautyPostProcess` already sets. On top
   of that, beauty raises the capture's surface cache from half resolution
   (the scene-capture default) to 1.0 and sets the Lumen quality and
   distance overrides.
3. **Measure keeps its behaviour.** Every new line is gated on
   `bVisual && bBeauty`. `BeautySubFrames` is 1 on measure, so the frame loop
   is the one Gate 6 passed on. `render_settings.beauty_path` is written only
   on beauty and pathtrace, so a measure `render.json` gains no field.
4. **Startup-only settings in DefaultEngine.ini.** `r.Nanite.ProjectEnabled`,
   `r.GenerateMeshDistanceFields` and `r.Lumen.HardwareRayTracing=False`
   were already in the file (Phase 2 B4), so measure already runs with them.
   They stay. **`r.RayTracing` is deliberately left out**, because
   `IsRayTracingEnabled()` is read in `BasePassRendering.cpp`,
   `VelocityRendering.cpp` and `Lumen.cpp`, so turning it on could change
   measure pixels. Pathtrace turns it on for its own process only, with
   `-ini:Engine:[/Script/Engine.RendererSettings]:r.RayTracing=True`. If
   `r.RayTracing` is ever added to the ini, re-run all of Gate 6 under measure
   and Gate 10-R's digest comparison.
5. **Still accumulation** (`-still-samples=N`, beauty only, 1 to 64) captures
   one pose N times and lets the engine's own temporal accumulation average
   the result: TSR's jittered history and Lumen's radiance cache. It is not a
   hand-rolled linear-HDR mean, for two reasons. A scene capture has no jitter
   API short of a custom projection matrix. And this way the tonemapper sees
   the converged scene. Labels render once, after the last sub-capture, from
   the same pose with AA and TAA off, so they have no jitter.
6. **Path tracer** (`-quality=pathtrace`) uses the scene capture route, not
   the game viewport. In 5.7.4 the path tracer keeps its accumulation in the
   view state (`PathTracing.cpp GetPathTracingStateFromView`), and
   `SceneCaptureRendering.cpp` has no exclusion for path tracing. Each
   `CaptureScene` adds one sample. The path is refused by name
   (`render.pathtrace`) in these cases: off Windows, when the RHI has no ray
   tracing, when the shader platform has no path tracing, when
   `IsRayTracingEnabled()` is false, when `r.PathTracing` is 0, without
   `-Visual`, or together with `-accumulate`, `-linear` or `-calibration`
   (those copy the beauty show flags into their own capture).
7. **Labels match pixels.** No change here moves geometry. TSR reconstructs
   to the unjittered pose. The path tracer's pixel filter
   (`r.PathTracing.FilterWidth` 3, a Gaussian with a sigma of about 0.5 px)
   softens silhouettes by less than a pixel. Volumetric clouds stay absent
   from every label capture (`ConfigureLabelCapture` calls
   `SetCloud(false)`), as before. A cloud in front of the aircraft is
   therefore in beauty but not in the mask. This is the existing,
   already-recorded visual-only rule, and this lane does not change it.
8. **Edge aliasing** is reported, not a gate. The number is the RMS of
   luminance minus its 3x3 box mean, within 2 px of the aircraft silhouette,
   divided by the edge contrast. Gate 6 prints it as `[info]` and writes
   `aliasing.json`. A point-sampled control must score higher, or the number
   is marked void. The contact sheet computes it per shot when a label mask
   exists.

### Uncalibrated constants (each: UNCALIBRATED, set by probe render on the render machine)

| Constant (FlightSimRenderCommandlet.cpp) | Value | Probe that sets it |
|---|---|---|
| RenderBeautyScalabilityLevel | 4 (Cinematic) | sheet at 3 vs 4 |
| RenderBeautyTsrHistorySamples | 32 | shot (a) edge aliasing at 16 vs 32 |
| RenderBeautyTsrHistoryScreenPercentage | 200 | shot (a) at 100 vs 200, aliasing and frame time |
| RenderBeautyLumenSceneLightingQuality / FinalGatherQuality / ReflectionQuality | 2 / 2 / 2 | shot (b), the shadow side at 1 vs 2 |
| RenderBeautyLumenSurfaceCacheResolution | 1.0 | shot (a) at 0.5 vs 1.0 |
| RenderBeautyLumenSceneViewDistanceCm / MaxTraceDistanceCm | 400000 / 400000 | shot (b) at 200 m, 1 km and 4 km against frame time |
| RenderBeautySkySampleCountMax | 64 | shot (a), horizon band |
| RenderBeautyAerialPerspectiveSamplesPerSlice | 8 | shot (a), horizon band |
| RenderBeautyVolumetricRenderTargetMode | 3 | shot (c), cloud edges |
| RenderBeautyStillSamplesDefault (still: at most RenderBeautyStillMaxFrames = 1 frame) | 8 | shot (a) at 1, 8 and 32, edge aliasing |
| RenderPathTraceSppDefault / BouncesDefault / DenoiseDefault | 256 / 8 / 1 | shot (a) at 64, 256 and 1024 spp |
| sky and cloud switches: FastSkyLUT 0, AerialPerspectiveLUT.FastApplyOnOpaque 0, MultiScatteringLUT.HighQuality 1, LUT32 1, VolumetricCloud.HighQualityAerialPerspective 1 | on | shot (a), and Gate 6 `--quality beauty` extinction |

Every value is recorded in `render.json`, under
`render_settings.beauty_path.cvars_asked` (what was asked) and
`cvars_read_back` (what the engine reported back).

### Hooks in other lanes' files

- `core/messages/catalog.yaml` gains two entries, `render.still_samples` and
  `render.pathtrace`, placed after `render.quality`. The refusal-catalogue
  test requires every refusal name to be catalogued.

### Open risks (not verifiable here)

- The `-ini:` override of `r.RayTracing` is read by `ConfigCacheIni.cpp`.
  Nobody has confirmed that the RHI's ray-tracing mode picks it up from the
  override. If `IsRayTracingEnabled()` is still false, the pathtrace render
  refuses by name.
- The path tracer's denoiser needs a denoiser plugin, and the engine ships
  NNEDenoiser and OpenImageDenoise. Neither is enabled in
  `FlightSim.uproject`. The manifest records `r.PathTracing.Denoiser.Name`.
- Google tiles streaming during a path-traced accumulation would reset it.
  Ray-tracing geometry for Cesium meshes is unverified, because the Cesium
  headers are not on this Mac.
- Calling `Scalability::SetQualityLevels` inside a commandlet is assumed to
  work. `beauty_path.scalability_applied` records what the engine reported.
- Review, 2026-11-09. These are recorded in render.json and not measured:
  - The path tracer traces each Nanite mesh's fallback mesh
    (`r.RayTracing.Nanite.Mode` 0, now read back into
    `beauty_path.path_tracer`). The labels rasterise the full Nanite mesh,
    so a path-traced Nanite silhouette can sit off the mask.
  - With one capture per frame (a clip), TSR carries history across the
    camera move, and a moving silhouette can ghost where the masks show
    nothing (`accumulation.history_across_frames`).
  - The `-linear` capture copies beauty's show flags, so it now runs TSR, but
    it captures once per frame and is not accumulated
    (`accumulation.linear_capture`).
  - The path tracer resets its accumulation when the exposure changes more
    than 16x between samples (PathTracing.cpp `IsExposureDifferentEnough`).
    If beauty's exposure is automatic, a still can restart part-way through.
    Check that `accumulation.captures_per_frame` converged on the first
    pathtrace sheet.

### Render-machine commands (Windows box, in order)

```
.\scripts\build_ue.ps1
.\scripts\check_bridge_api.sh                         # (Git Bash) render-path block all ok
python experiments\gate6_visual.py                    # measure: must still PASS unchanged; writes runs\gate6\aliasing.json
python experiments\gate6_visual.py --quality beauty --aliasing-baseline runs\gate6
#   read runs\gate6_beauty\shadow\render.json render_settings.beauty_path:
#   temporal_aa_show_flag true, cvars_read_back, scalability_applied; the [info] aliasing change should be negative
.\scripts\render_visual_sheet.ps1 -Step v0_measure -Quality measure
.\scripts\render_visual_sheet.ps1 -Step v0_beauty
.\scripts\render_visual_sheet.ps1 -Compare v0_measure,v0_beauty
.\scripts\render_visual_sheet.ps1 -Step v0_ss1 -StillSamples 1 -Shots a
.\scripts\render_visual_sheet.ps1 -Step v0_ss32 -StillSamples 32 -Shots a
.\scripts\render_visual_sheet.ps1 -Step v0_pt -PathTrace -Spp 256 -Shots a
.\scripts\render_visual_sheet.ps1 -Step v0_beauty -Clip
```
