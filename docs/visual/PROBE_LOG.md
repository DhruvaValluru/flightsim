# Visual overhaul probe log

One section per lane of the 2026-11-09 visual-overhaul session (swarm
`swarm-1794241474984-rmywk3`). That session ran on a Mac that cannot build or
render (Xcode 27.2 is above UE 5.7.4's ceiling of 26.9, and Cesium for Unreal
is not installed), so **nothing below has been rendered**. Each section lists
the constants a probe render on the render machine must set, the probe that
sets each one, and the exact command to see it. Keep to your own `## <lane>`
heading so merges stay trivial.

## look-dev

Lane: light, exposure, post, camera feel. Files:
`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimBeautyLook.{h,cpp}`,
`core/scene/beauty_look.py`, `webapp/runs.py` (`write_beauty_look_plan`,
`beauty_look_render_flags`), `tests/test_beauty_look.py`.

### What it does

On `-quality=beauty` only, the web app writes `runs/<id>/beauty_look.json`
and passes `-beauty-look=<abs path>` plus `-sun-lux=<lux>`. The commandlet
applies the sidecar to the beauty capture, refuses by name
(`render.beauty_look`) if it cannot, and writes what it applied into
`render.json` under `beauty_look` (`plan`, `applied` with read-backs,
`per_frame` focal-length and focus ranges). If `-beauty-look=` is absent,
`ApplyBeautyPostProcess` sets exactly the V0 overrides (Lumen GI and Lumen
reflections) and nothing else, so `gate6_visual.py --quality beauty` is
unchanged. Measure renders never get the flag.

### Decisions (with the reasons)

1. **Sun lux = clear-sky direct normal / engine zenith transmittance.** The
   direct normal comes from Bird & Hulstrom 1981 (`core/scenario/solar.py`):
   about 101 klx at the zenith and about 96 klx at 50 deg, falling with air
   mass. The UE 5.7 source shows an atmosphere sun light's intensity is
   outer-space illuminance, multiplied by the sky atmosphere's transmittance
   (`DirectionalLightComponent.cpp`, `GetOuterSpaceIlluminance() *
   GetAtmosphereTransmittanceTowardSun()`). This scene pins
   `TransmittanceMinLightElevationAngle = 90`, so the engine always applies
   the **zenith** transmittance. That means the air-mass falloff has to come
   from the lux we set, and only the zenith factor is divided out. A stated
   `scene.sun_lux` goes on the light unchanged.
2. **Sun colour from elevation.** The pinned zenith transmittance keeps a
   low sun white, so the beauty sun gets a temperature per elevation band.
   It is skipped when the lighting block or the X-Plane colours already
   coloured the sun (`bUseTemperature` set, or `LightColor` not white).
3. **Manual EV100 per sun-elevation band, not auto exposure.** Beauty clips
   carry labels too, and auto exposure re-meters as bank changes the
   bright-ground fraction, which is the "breathing" Gate 6 forbids. Local
   Exposure (bilateral) handles the shadowed valleys instead. A sunlit
   scene sits at EV100 14 to 15. Each band is test-guarded to within 1.5
   stops of the incident meter (C = 250) on the modelled clear-sky
   horizontal illuminance (direct beam plus IES RP-21 clear-sky diffuse).
   The exposure goes through the physical camera (lens f-number, a
   180-degree shutter at the clip's fps, ISO 100) with
   `AutoExposureBias = cameraEV100 - target`. That formula was read in
   `PostProcessEyeAdaptation.cpp CalculateManualAutoExposure`. A card's
   exposure triple, the `-sky=` plan and `-AutoExposure` all win over the
   band; the host records which one did.
4. **Tonemap:** UE's filmic (ACES-fitted) curve with the 5.7 constructor
   defaults set explicitly (FilmSlope 0.88, Toe 0.55, Shoulder 0.26,
   BlackClip 0, WhiteClip 0.04, ToneCurveAmount 1), read from
   `Engine/Private/Scene.cpp`. These are the engine's own values, stated,
   not uncalibrated.
5. **Grade in post-process settings, not a LUT texture.** No asset to author
   on the render machine, and every number is in the record. There are
   three grades: `golden_hour`, `desert_noon` and `storm`. Each run's grade
   is chosen automatically: storm weather or rain gives `storm`, a sun
   below 15 deg gives `golden_hour`, anything else `desert_noon`.
6. **No new environment switch.** The `FLIGHTSIM_*` surface is frozen at 23
   names (`core/config_surface.py`, E1, enforced by
   `tests/test_config_surface.py`). The web app uses the automatic grade and
   the `standard` lens. `cinematic` and a forced grade are available through
   `plan_beauty_look(lens=..., grade=...)` or
   `write_beauty_look_plan(..., grade=, lens=)`.
7. **Lens: the FOV is never changed.** The focal length is derived from
   `Capture->FOVAngle` and the card's sensor width (one per camera pass,
   picked by `-camera-index=`), and `DepthOfFieldSensorWidth` is set to
   that sensor so the engine's focal length matches the manifest's. Depth
   of field is used only on `cinematic`, focused each frame at
   |capture - aircraft actor| (the two poses the manifest records; the
   actor origin is the JSBSim datum, gotcha 31). Motion blur is
   `MotionBlurAmount 0.5` (180 deg) at `MotionBlurTargetFPS` = clip fps,
   with the smear capped by `MotionBlurMax`. Bloom is standard (SOG) and
   subtle, lens flare is image-based and subtle, and grain is light. The
   vignette is 0 on `standard` because the owner rejected edge shading on
   2026-10-11; `cinematic` has a light 0.2 vignette.
8. **Labels match pixels.** No lens distortion and no chromatic aberration
   (`SceneFringeIntensity` 0). `pixel_effects` in the sidecar marks each
   effect as moves, softens or none, plus `pixel_moving` (empty for both
   presets). Motion blur records its maximum smear in pixels. The mask,
   class, depth and box passes are separate captures of the same frame
   that never get these settings. This lane adds **no visual-only actor**,
   so there is no occluder the masks lack. Bloom can lighten pixels just
   outside the mask; that is recorded.
9. **Reflections:** Lumen reflection, final-gather and scene-lighting
   quality are 2, LumenSceneDetail is 2, LumenMaxTraceDistance is 2 km,
   front-layer translucency reflections are on, and SSR quality is 100.
   Whether Lumen runs inside a scene capture on this build is still a
   probe question.

### Uncalibrated constants and the probe that sets each

All live in `core/scene/beauty_look.py`. Each carries the comment
"UNCALIBRATED: set by probe render on the render machine".

| Constant | Starting value | Probe |
|---|---|---|
| `UE_ZENITH_TRANSMITTANCE` | 0.90 | `-calibration` white quad, sky atmosphere on vs off, sun 50 deg: the ratio of the two quad luminances |
| `EV100_BANDS` | 15.0 / 14.7 / 14.2 / 13.4 / 12.6 from >=40 / 25 / 15 / 8 / below | one clip per band: the sunlit grey card at ~18% of white after the tonemapper, sky unclipped |
| `SUN_TEMPERATURE_BANDS` | 5600 / 5200 / 4700 / 4000 / 3300 K | golden-hour and noon probes: hue of the sunlit side of a white quad |
| `GRADES` (golden_hour, desert_noon, storm) | see file | the same frame graded three ways on one contact sheet |
| `GOLDEN_HOUR_BELOW_DEG` | 15 | probe series at sun 10 / 15 / 20 deg |
| `LENSES` (standard, cinematic) | bloom 0.35/0.45, flare 0.12/0.18, grain 0.02/0.035, vignette 0/0.2, MotionBlurMax 1 % | the same clip through both lenses, with the sun in frame |
| `LOCAL_EXPOSURE` | highlight 0.85, shadow 0.8 | Matterhorn north face: valley floor and snowfield in one frame |
| `REFLECTIONS` | Lumen qualities 2, trace 2 km, SSR 100 | lake or runway at 300 m AGL: reflections and frame time |

### Engine symbols verified (UE 5.7.4 headers on the authoring Mac)

All FPostProcessSettings members set in `FlightSimBeautyLook.cpp`, each with
its `bOverride_` twin (`Engine/Classes/Engine/Scene.h`); `EBloomMethod::BM_SOG`;
`ELocalExposureMethod::Bilateral`; `UDirectionalLightComponent::
IsUsedAsAtmosphereSunLight / GetAtmosphereSunLightIndex`; `ULightComponent::
bUseTemperature / SetUseTemperature / SetTemperature / Temperature`;
`ULightComponentBase::LightColor / Intensity`; `FCommandLine::Get`; show flags
MotionBlur, DepthOfField, Bloom, LensFlares, Tonemapper, LocalExposure,
ScreenSpaceReflections (plus the already-checked Grain, Vignette,
SceneColorFringe); and the three premises above (lux times transmittance, the
transmittance floor, the physical-camera EV100 formula). All are re-checked
by `scripts/check_bridge_api.sh` ("engine surface the beauty look assumes").
No Cesium API is used.

### Hooks in other lanes' files

- `FlightSimRenderCommandlet.cpp`: `#include "FlightSimBeautyLook.h"`; after
  `ApplyBeautyPostProcess(Capture)` there is a two-line refusal and the
  exposure-record hook; before the beauty `Capture->CaptureScene()` there is
  `UpdatePerFrame`; after `Root->SetObjectField("scene")` there is one line
  writing `beauty_look`.
- `FlightSimVisualScene.cpp`: the body of `ApplyBeautyPostProcess` (owned by
  this lane) and two includes.
- `core/messages/catalog.yaml`: the `render.beauty_look` entry.
- `scripts/check_bridge_api.sh`: the beauty-look block.

### Render-machine commands (Windows, from the repo root)

```powershell
# 0. API surface, then build (gotcha 27 order)
bash scripts/check_bridge_api.sh
.\scripts\build_ue.ps1

# 1. Measure must be untouched, and sidecar-less beauty is the V0 one
python experiments/gate6_visual.py
python experiments/gate6_visual.py --quality beauty

# 2. The beauty look through the web app (sidecar written automatically)
$env:FLIGHTSIM_RENDER_QUALITY = "beauty"
#    then in the web app: "fly the c172 over yosemite at golden hour"
#    read runs\<id>\beauty_look.json and runs\<id>\frames\render.json -> beauty_look
#    (applied.exposure.applied must be "yes"; applied.camera.fov_deg_unchanged
#    must equal the manifest's FOV; render.log has "beauty look: grade ...")

# 3. Probe another grade or lens on the same run: rewrite the sidecar in place,
#    then re-run the commandlet line from that run's render.log unchanged
python -c "from core.scene.beauty_look import plan_beauty_look as p, write_beauty_look as w; w(p(8.0, fps=30, width_px=1920, grade='storm', lens='cinematic'), r'runs\<id>\beauty_look.json')"
```
