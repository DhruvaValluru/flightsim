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

# Visual overhaul probe log

Each lane keeps its own `## <lane>` section (merges stay trivial). The render
machine reads this file: every constant below was chosen without a frame and
is set by the probe named beside it.

## world

Lane: atmosphere, clouds, ground, weather look. Written 2026-11-09 on the Mac
(flightsim-83) that cannot compile or render the bridge (Xcode 27.2 above UE
5.7's 26.9 cap; no Cesium for Unreal). Nothing here has been built or rendered.

### What was built (all BEAUTY ONLY)

`FFlightSimWorldBeauty` (`FlightSimClouds.h/.cpp`) is constructed and called by
the render commandlet only under `-quality=beauty`; `-quality=measure` (every
render Gate 6 passed on) never reaches it. It records everything in
`render.json` `look_applied.world_beauty`.

* Atmosphere depth: one preset per card (`clear / hazy / overcast / rain /
  storm`). A share of the card's haze (Koschmieder beta from
  `look.visibility_km`) moves from the height fog into the sky atmosphere's
  Mie layer; the fog density is multiplied by `fog_factor` so the ground
  extinction is counted once. Mie scale height and anisotropy, aerial
  perspective scale, planet ground albedo (the horizon fill beyond the tiles),
  volumetric fog, sun shadows on atmosphere and clouds, per-pixel
  transmittance. `-NoAerialPerspective` is respected (a hidden atmosphere is
  left alone); `bCastCloudShadows` is never touched (Gate 6's cloud bracket),
  except by the stated `-beauty-clouds=fair` layer, which turns it on and records
  it (`clouds.fair_layer_sun_cast_cloud_shadows`, with the value before).
* Clouds: every cloud on the engine's `m_SimpleVolumetricCloud` material
  (the look's layer, the physical sky's) is redrawn with
  `M_FlightSimCloudLayers` (seeded layered value noise, four shapes). The
  storm's `M_StormCell` is never touched. `-beauty-clouds=fair` (or
  `FLIGHTSIM_BEAUTY_CLOUDS=fair`) adds a fair-weather cumulus layer when the
  card states none; `engine` leaves clouds as built; `card` is the default.
* Tiles look: `M_FlightSimTilesBeauty` on the Cesium tileset plus Cesium's
  smooth normals, both by reflection by name, driven by `MPC_FlightSimWorld`
  (de-haze, saturation, near-field detail normal and micro-roughness faded by
  range, wet darkening and roughness drop, puddles on flat ground). The tiles
  stay the ground; nothing here can turn them off.
* Rain and storm: the storm weather's drawn drops' weight times the preset's
  `rain_readability_gain`; the lightning as a sky-light pulse; both lightning
  schedules (the weather look's `LightningFlash` and the storm weather's flash
  lux) recorded per frame in `world_beauty.frames[]`.
* Ground scatter: `FFlightSimGroundDetail` (`FlightSimGroundDetail.h/.cpp`),
  `-ground-scatter=<sidecar>` (or `FLIGHTSIM_GROUND_SCATTER`), sidecar from
  `python -m core.scene.world_beauty --biome forest --seed 7 --out <path>`.

### Decisions

* **Clouds and labels.** Volumetric clouds write no depth or stencil, so the
  mask, class and depth never see them. Clouds stay where the card puts them;
  each frame records the camera-to-aircraft path through every layer, its
  estimated transmittance and `cloud_occludes_aircraft` (transmittance under
  `occlusion_flag_transmittance`, 0.5). A consumer drops or down-weights those
  frames. The mask is not edited. The fair layer is a beauty-only actor.
  Only the clouds redrawn with `M_FlightSimCloudLayers` are modelled: with the
  storm's `M_StormCell`, another material's cloud, `-beauty-clouds=engine` or the
  material missing, `clouds.unmodelled_clouds` > 0 and every frame carries
  `cloud_occlusion_complete: false` (`cloud_occludes_aircraft` is then a lower
  bound, never a clear).
* **Scatter and labels.** The instances are in the beauty frame, so they are
  NOT beauty-only: they are in the same frame's mask, class and depth (a tree in
  front of the aircraft cuts its mask as it cuts its pixels), labelled
  `vegetation:all` when the card names it (tag `FlightSim.vegetation`), else as
  the ground (the terrain id). No collision; the flight model never sees them.
* **Haze split.** Moving haze into Mie instead of adding Mie on top avoids the
  double count `weather_visuals.py` warns of; the `-aerosol=` probe wins when
  given.
* **Cesium.** No Cesium headers here, so no new Cesium symbol is compiled:
  `SetMaterial` (UFunction) else `Material` (UPROPERTY), and the bool
  `GenerateSmoothNormals`, found by name; applied only on Cesium for Unreal 2.x+
  (VersionName read from the installed `.uplugin`). The record lists the
  tileset's own property names so the next probe can reach the real ones.
  UNVERIFIED: the per-primitive parameter names `baseColorTexture` /
  `baseColorFactor` the tiles material exposes, that the tileset's primitives
  are owned by the tileset actor (scatter traces), and that they block
  `ECC_Visibility` (Cesium physics meshes on).
* **Assets.** Ten Poly Haven CC0 models pinned in
  `assets/scatter/polyhaven_pins.json`; every root glTF md5-checked and
  sha256-pinned; five small assets fully pinned (shrub_02, rock_moss_set_01,
  grass_medium_01, namaqualand_boulder_02, wild_rooibos_bush). Big trees not
  downloaded (unpinned, drawn as nothing). **TODO:** an import script
  (`scripts/ue_import_scatter.py`) that brings the fetched glTFs to
  `/Game/FlightSim/Scatter/<id>/<id>` with Nanite on at import time (gotcha 5);
  until then every species records "the mesh did not load".
* **Not done:** a land-cover mask for the scatter (trees can stand on flat roofs
  or water the tiles carry); the weather look's rain particles (default
  backend off) get no readability gain; webapp flags for the new options (they
  ride environment variables instead).

### UNCALIBRATED constants and the probe that sets each

All live in `core/scene/world_beauty.py` (Python) and the pure block of
`FlightSimClouds.cpp` (C++), pinned equal by `tests/test_world_beauty.py`. Any of
them can be swept WITHOUT a rebuild through
`FLIGHTSIM_WORLD_BEAUTY_OVERRIDES=<json>` / `-world-beauty-overrides=<json>`
(schema: `world_beauty.validate_overrides`), and `world_beauty.overridden`
records what was swept.

| Constant | Value | Probe that sets it |
|---|---|---|
| `ATMOSPHERE[*].mie_share`, `mie_cap_per_km` | 0.3-0.6, 0.25-0.8 /km | far-ridge contrast at 10 / 30 km vs Koschmieder for the card's visibility (Gate 6 extinction clause under beauty) |
| `mie_scale_height_km`, `mie_anisotropy` | 1.0-1.8 km, 0.65-0.80 | sun-side vs anti-sun horizon luminance ratio in a golden-hour beauty frame |
| `aerial_perspective_scale` | 1.0 / 1.15 hazy | the same far-ridge probe |
| `ground_albedo_*` | sRGB 52-110 | horizon band with tiles at max SSE: the below-horizon fill must not read as a seam |
| `vfog_*` | 4-8 km, g 0.3-0.75 | god-ray visibility vs noise at 1080p, render time |
| `cloud_bottom_occlusion` | 0.5-0.9 | overcast ground luminance vs the sky-light-only reference |
| `rain_readability_gain` | 1.5 rain/storm | WX.2 chase-cam streak visibility at 1080p (with -rain-gain=4) |
| `wetness_floor` | 0.6 rain, 0.85 storm | wet-ground darkening vs a rain photo reference |
| `tiles_dehaze`, `tiles_saturation` | 0.03-0.10, 0.90-1.10 | the tiles' mean chroma and dark-object level in a clear noon nadir frame |
| `tiles_detail_strength`, `DetailFadeM`, `DetailScaleM` | 0.5-0.6, 1500 m, 2 m | 300 m AGL chase frame: detail visible, no tiling, no shimmer under TSR |
| `PUDDLE_SHARE_OF_WETNESS`, `ROUGHNESS_PUDDLE`, `MICRO_VARIATION`, `HAZE_RGB`, `WET_DARKENING`, `PUDDLE_DARKENING` (HLSL) | 0.5, 0.05, 0.06, (0.20,0.24,0.30), 0.30, 0.55 | storm-look ground frame |
| `CLOUDS[*]` (extinction, shape/detail scale, erosion, softness, rounding, contrast, default cover) | see table | rendered sky cloud fraction vs card cover within 15 % (V6 clause); base height in a level shot |
| `CLOUD_EXTINCTION_SCALE` | 1.0 | the WX.4-style transmittance probe (engine extinction unit) |
| cloud component `ViewSampleCountScale 2`, shadow 1, tracing 80 km, shadow 15 km, stop 0.005 | | render time vs cloud noise |
| `OCCLUSION_FLAG_TRANSMITTANCE` | 0.5 | a frame with the aircraft behind a deck: flag vs visible silhouette |
| `lightning_sky_gain` 3.0, `LIGHTNING_REFERENCE_LUX` 50 | | storm clip: flash frames vs neighbours' mean luma |
| selection thresholds (`HAZY_VISIBILITY_KM` 15, `OVERCAST_COVER` 0.75, cloud shape thresholds) | | a matrix of cards through the preset table |
| scatter `BIOMES` densities, sizes, cull distances; `SCATTER_DEFAULTS` | | V4 nadir density probe vs WorldCover tree fraction; 300 m chase for float/bury |

### Engine symbols verified (UE 5.7.4 headers on this Mac)

All listed in `scripts/check_bridge_api.sh` "world lane" block (every one `ok`
on 2026-11-09): SkyAtmosphere `SetMieScatteringScale / SetMieAbsorptionScale /
SetMieExponentialDistribution / SetMieAnisotropy /
SetAerialPespectiveViewDistanceScale / SetGroundAlbedo`; height fog `FogDensity,
SetVolumetricFog, SetVolumetricFogDistance / ScatteringDistribution /
ExtinctionScale`; directional light `bCastShadowsOnClouds,
bCastShadowsOnAtmosphere, bCastCloudShadows, bPerPixelAtmosphereTransmittance`,
`bCastVolumetricShadow`, `Intensity`, sky light `SetIntensity`; volumetric cloud
`Material` (TSoftObjectPtr), `LayerBottomAltitude`, and the setters for
per-sample transmittance, bottom occlusion, view / shadow sample scale,
shadow tracing, tracing max, stop threshold, ground albedo;
`UMaterialExpressionCloudSampleAttribute` and its `NormAltitudeInLayer` pin;
`UMaterialParameterCollectionInstance::SetScalarParameterValue`,
`UWorld::GetParameterCollectionInstance` (lazy-creates; flushed by
`SendAllEndOfFrameUpdates`, which the commandlet calls every frame);
`UWorld::LineTraceSingleByChannel`, `FCollisionQueryParams::AddIgnoredActors`;
ISM `AddInstance / GetInstanceTransform / UpdateInstanceTransform /
SetCullDistances`; reflection `FindFProperty`, `FObjectProperty::
SetObjectPropertyValue_InContainer`, `FBoolProperty::SetPropertyValue_InContainer`,
`UFunction::ParmsSize`, `UObject::ProcessEvent`; engine `WhiteSquareTexture`.

### Hooks in other lanes' files

* `FlightSimRenderCommandlet.cpp`: four commented lines ("world lane hook"):
  the include, the `FFlightSimWorldBeauty WorldBeauty;` member beside
  `GoogleTiles`, `if (bBeauty && !WorldBeauty.Build(...))` after the tiles are
  enabled (before the label groups and the cloud-material check), and
  `if (WorldBeauty.IsBuilt()) WorldBeauty.Advance(...)` after the weather's
  per-frame Advance.
* `tests/test_ue_materials.py`: the `_world_beauty_material` regex and the two
  new names in `ALL_CREATED`.
* `NOTICE.md`: the Poly Haven models credit. `.gitignore`: `data/scatter/`.

### On the render machine, in this order

```
bash scripts/check_bridge_api.sh                        # world lane block all ok
./scripts/build_ue.sh                                   # or .\scripts\build_ue.ps1
UnrealEditor-Cmd <abs>/ue/FlightSim.uproject -run=pythonscript -script=<abs>/scripts/ue_create_materials.py
#   expect MATERIAL-CREATED for MPC_FlightSimWorld, M_FlightSimCloudLayers, M_FlightSimTilesBeauty
python experiments/gate6_visual.py                      # measure: must pass unchanged
python experiments/gate6_visual.py --quality beauty     # read runs/gate6_beauty/full/render.json look_applied.world_beauty
# the web app, storm and clear looks (the world look rides FLIGHTSIM_RENDER_QUALITY=beauty):
FLIGHTSIM_RENDER_QUALITY=beauty   # then "fly the c172 over yosemite at golden hour"
FLIGHTSIM_RENDER_QUALITY=beauty   # then "fly the 747 towards a thunderstorm 5 km ahead"
# a probe sweep without a rebuild:
FLIGHTSIM_WORLD_BEAUTY_OVERRIDES=<abs>/probe.json      # e.g. {"atmosphere": {"clear": {"mie_share": 0.4}}}
# the scatter (after the import TODO):
python scripts/fetch_scatter_assets.py --write-pins
python -m core.scene.world_beauty --biome forest --seed 7 --out <abs>/scatter.json
FLIGHTSIM_GROUND_SCATTER=<abs>/scatter.json
```

Read first in each `render.json`: `look_applied.world_beauty.tiles`
(`material_route`, `generate_smooth_normals`, `tileset_properties`: the real
Cesium names), `look_applied.cloud_materials` (the new cloud material passes
the engine's check), `world_beauty.frames[].cloud_occludes_aircraft`. A tiles
frame that comes out white means the Cesium base-colour parameter names are
not `baseColorTexture` / `baseColorFactor`: fix `CESIUM_BASE_COLOUR_*` in the
material script and rebuild that one material
(`FLIGHTSIM_REBUILD_MATERIALS=M_FlightSimTilesBeauty`).

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

# Visual overhaul probe log

Each lane keeps its own `## <lane>` section. Everything below was written
on 2026-11-09 on a Mac that cannot compile or render UE 5.7.4 (Xcode above
the engine's cap, no Cesium): nothing here has been rendered or measured.
Every look constant is UNCALIBRATED: set by probe render on the render
machine.

## aircraft

**What exists (code only).** Look configs `assets/aircraft_config/look/<NAME>.json`
(all seven airframes), resolved by `scripts/aircraft_look.py` into
`assets/generated/<NAME>/look_manifest.json`; master materials built by
`scripts/ue_aircraft_master_materials.py` (called from the aircraft block of
`scripts/ue_create_materials.py`); per-model look instances
`/Game/Aircraft/<NAME>/Look/MI_<slot>` made at import
(`scripts/ue_aircraft_materials.py create_look_instances`, called by
`ue_import_aircraft.py` and `ue_fix_aircraft_materials.py`); the beauty-only
C++ `FlightSimAircraftFX.cpp/.h`; candidate model table
`scripts/fetch_aircraft_models.py`. Tests: `tests/test_aircraft_look.py`.

**Decisions.**
- Look config lives in its own folder, not in `<NAME>.json`: that file's
  sha256 is label provenance in every run manifest, and a look tweak must
  not move it.
- Everything is gated on `-Visual -quality=beauty` with a mesh airframe
  drawn and no `-HideAircraft`. `-quality=measure` constructs nothing, so
  Gate 6's path and its `render.json` are byte-identical (`aircraft_look` is
  absent there).
- The imported Interchange instances (what measure draws) are never edited;
  beauty swaps each slot to `Look/MI_<slot>`. A card livery other than
  `default` is kept, not repainted (recorded).
- Legacy shading only (Substrate off, gotcha 32). `M_AircraftPaint` is Clear
  Coat through `MakeMaterialAttributes` (the 5.7 Python hides
  `MP_CUSTOM_DATA0/1`: UMETA(Hidden) in SceneTypes.h, and M_AirframePaint's note records the miss on the owner's machine); bare metal, glass and
  rubber are Default Lit. Normals are world space (MikkTSpace is off on these
  meshes, gotcha 5).
- Paint metallic is 0.15, not 0.6-0.9: a painted panel is a dielectric under
  a clear coat. The 0.6-0.9 band is the `bare_metal` class (0.9; the P-51D
  defaults to it).
- **Glass is opaque.** The label captures draw no translucency and a
  translucent canopy writes no custom depth, so translucent glass would show
  sky where the mask says aircraft. Opaque dark glass keeps beauty, mask,
  class and depth on one silhouette. (In beauty the canopy is therefore IN
  the mask; if an imported glass slot was translucent before, measure masks
  had a hole there that beauty masks do not.)
- No master uses World Position Offset; custom depth/stencil is set per
  component by the commandlet after the swap; every class master is opaque.
  So the label passes see the beauty's geometry.
- Nanite stays OFF for airframes (`ue_import_aircraft.py` comment): the asset
  is shared with measure, the capture drew the fallback when it was on, VSM
  shadows non-Nanite meshes, and these meshes are too small to gain. The
  `FinishAllCompilation` guard (gotcha 4) is untouched.
- FX are separate actors attached to the aircraft and listed in
  `BeautyOnlyActors`, never components of the aircraft actor (the stencil loop
  labels every primitive of that actor). Lights move no geometry; bulbs and
  the afterburner plume are additive (hide nothing); trails are translucent
  media, which by the clouds/rain convention do not occlude in masks (a
  trail in front of the aircraft leaves the mask as aircraft; recorded in
  `render.json aircraft_look.contrail.label_convention`).
- Heat haze refracts (moves pixels): OFF unless `-heat-haze=on`, beauty
  only, recorded as `aircraft_look.heat_haze.pixel_moving: true` with
  `max_offset_screen_fraction` = Strength/100.
- All FX run on the FDM's time (strobe phase, trails, reheat glow, haze
  phase): replay-identical.
- Lamps sit on measured body-vertex extremes (wingtips at -y/+y, tail at
  -x) plus a stated `offset_m`; nozzles are the FDM thruster line (y, z) with
  x snapped to the aftmost body vertex within `snap_radius_m` and 4 m aft
  (without the window the B747 outboard snap took the wing trailing edge,
  6.1 m aft, measured here on the converted model).
- J-11 slot names were not measurable here (source not fetched on this
  machine); its glass/rubber come from the automatic rules (MTL `d` < 0.95,
  untextured Kd <= 0.06).

**Uncalibrated constants and the probe that should set each** (values in
`scripts/aircraft_look.py`, copied into every look manifest and into
`render.json aircraft_look.constants`):
- class scalars/vectors (`CLASS_SCALARS`, `CLASS_VECTORS`, per-aircraft
  overrides in the look configs): roughness, clear coat, panel pitch / width /
  depth, wear, grime, glass tint. Probe: V7 side-by-side of each type against
  a reference photo at matched sun (reader's judgment).
- `lights`: LightVisualGain, BulbRadiusCm, BulbEmissivePerCd,
  BulbEmissiveMax, StrobePeriodS, StrobeFlashS, LandingMaxAglM,
  LandingConeDeg, NavAttenuationM, LandingAttenuationM. Probe: dusk and noon
  beauty of the type at chase range. (Candela values are 14 CFR 25.1391 /
  25.1401 minimums from memory, not uncalibrated look numbers.)
- `contrail`: MaxTemperatureK 233.15, MinAltitudeM 7500, LifetimeS,
  FormationDelayS, StartWidthM, SpreadMPerS, Opacity, PreseedS. Probe: cruise
  beauty above 9 km, chase and side views.
- `vapour`: MinNz 4, LifetimeS, StartWidthM, SpreadMPerS, Opacity. Probe:
  a 5 g pull-up.
- `afterburner`: PlumeLengthRadii, AfterburnerCandela, GlowGain,
  AttenuationM; core/tip colours in `M_AircraftAfterburner`. Probe: full
  reheat take-off, rear quarter.
- `heat_haze`: LengthRadii, Strength. Probe: `-heat-haze=on` at idle, rear
  view.
- `GLASS_MAX_DISSOLVE` 0.95, `RUBBER_MAX_KD` 0.06, `SNAP_MAX_AFT_M` 4.0,
  and each look config's `snap_radius_m` / `radius_m` / `offset_m`.

**Engine symbols verified** against the UE 5.7.4 headers on the Mac
(`scripts/check_bridge_api.sh`, block "AIRCRAFT LANE"; all ok on 2026-11-09,
the only FAIL is the pre-existing CesiumRuntime module). Python enum
spellings (`RM_2D_OFFSET`, `TLM_VOLUMETRIC_NON_DIRECTIONAL`,
`MP_MATERIAL_ATTRIBUTES`, `CMOT_FLOAT2/4`) are tried and a miss raises with
the engine's own names. No Cesium API is used by this lane.

**Hooks in other lanes' files.**
- `ue/.../FlightSimRenderCommandlet.cpp`: one `#include`; the build block
  after `ApplyIceOverlay` (gated `bVisual && bBeauty && MeshAirframe.bLoaded
  && !bHideAircraft`, appends to `BeautyOnlyActors` before the label captures
  are configured); a 4-line per-step `AircraftFX.Advance(...)` before the
  weather view; the `render.json aircraft_look` record (absent unless built).
  All marked `AIRCRAFT LANE`.
- `scripts/ue_create_materials.py`: the `AIRCRAFT LANE` block (one creator
  that imports `ue_aircraft_master_materials.build_all`) and its call.
- `scripts/check_bridge_api.sh`: the `AIRCRAFT LANE` block.
- `core/messages/catalog.yaml`: one entry, `aircraft_look.manifest` (a look manifest that exists but cannot be read).

**Model candidates** (`python scripts/fetch_aircraft_models.py --list`):
Su-27 by andertan on Sketchfab, CC-BY-4.0, 28.8k triangles (J-11 parent;
sha256 not pinnable without an account download); FlightGear FGAddon
Sukhoi-Su-33 by helijah, GPLv2+, SVN r18942 (J-15 parent; tree sha256 not
pinned, nothing downloaded; needs a J-15 FDM to be a J-15 subject). No
redistributable J-35/FC-31 model was found. Nothing is usable until pinned.

**Render-machine commands, in order** (Windows is the maintained render
platform; the `.sh` twins take the same arguments):
1. `scripts/check_bridge_api.sh` (the AIRCRAFT LANE block must be all ok).
2. `scripts\build_ue.ps1` (first compile of `FlightSimAircraftFX.cpp`).
3. `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script=scripts/ue_create_materials.py`
   (expect `MATERIAL-CREATED: /Game/FlightSim/Aircraft/M_Aircraft*` and no
   `MATERIAL-FAILED`).
4. `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script="scripts/ue_fix_aircraft_materials.py J11 B747 A320 c172p DHC6 p51d A4"`
   (writes `Look/MI_*` and `assets/generated/<NAME>/look_manifest.json`;
   read `runs/fix_aircraft_materials.txt` for `LOOK-PROBLEM` lines).
5. `python experiments/gate6_visual.py` -- must pass unchanged (measure
   untouched), and its `render.json` must carry no `aircraft_look` key.
6. Beauty probes: web app with `FLIGHTSIM_RENDER_QUALITY=beauty`, prompts
   "fly the J-11 at 3000 m" (materials, nav/strobe lamps), "fly the J-11 at
   10000 m" (contrails), and the B747 at cruise. Read
   `runs/<id>/.../render.json` `aircraft_look` (slots_applied, slots_absent,
   contrail_frames, peak_glow, constants) and look at the frames.
7. Heat haze, once: re-render a beauty run's card with
   `scripts\render_ue_scenario.ps1 <runs\<id>\card.json> <out> -Visual -quality=beauty -mesh=<abs path to assets\generated\J11\mesh_manifest.json> -heat-haze=on`
   and compare mask edges behind the nozzles against the beauty frame
   (bound: `aircraft_look.heat_haze.max_offset_screen_fraction`).

# Visual overhaul probe log

Each lane keeps its own `## <lane>` section, so merges stay trivial. Every
entry is either code that has not been rendered yet (session flightsim-83,
2026-11-09, Mac, code only) or a number a probe render on the render
machine has set. The shared record is ruflo memory, namespace `visual`, key
`visual-overhaul/<lane>/<topic>`. The render machine reads this repo copy.

## verifier-tooling

Session flightsim-83, 2026-11-09. Code only: nothing here has been
rendered. Schema: `docs/schemas/render_json_beauty_look.md`.

### What was built

- `core/capture/beauty_look.py` (new) reads the render.json keys
  `scene.render_quality` (measure|beauty|pathtrace), `beauty_look`,
  `pixel_moving_effects`, `beauty_samples`, `beauty_only_actors`,
  `cloud_occlusion` and the per-frame `beauty_window_s`.
- `core/capture/verify.py` gets two new checks, run by `flightsim.verify`
  and by every batch and campaign verify:
  - `look_record` checks quality, that measure is left alone, the sample
    counts, the occlusion decision, and that every pixel-moving key is
    listed.
  - `look_label_alignment` checks the transform or measured displacement
    of each pixel-moving effect, a cloud over the subject, the FOV against
    the pose solver, and that labels come from the same frame and instant.

  On failure the run is refused by name: `look.quality`,
  `look.measure_altered`, `look.pixel_moving_unrecorded`, `look.record`,
  `look.beauty_not_label_aligned`. These have catalogue entries in
  `core/messages/catalog.yaml`. Old bundles stay valid: their look checks
  are PASS (quality only) or NOT RUN, never FAIL.
- `experiments/look_label_check.py` (new) measures the mask-edge offset
  against the luminance-gradient silhouette in a measure bundle and a
  beauty bundle of the same card and frame. It includes a self-validation
  control (a 3 px shift must be recovered, or the result is VOID).
  Unit-tested on synthetic pictures in `tests/test_look_label_check.py`.

### Decisions

- A pixel-moving effect is label-aligned only with a recorded transform,
  or with a **measured** displacement of at most `LOOK_ALIGNMENT_TOL_PX` =
  `MASK_TOL_PX_MESH` = 2.0 px. That is the gate tolerance, not a new
  constant. An uncalibrated displacement is not evidence. Anything else
  fails as `look.beauty_not_label_aligned` and export refuses it.
- A beauty-only cloud or contrail in front of the subject is a label error.
  The `cloud_occlusion.policy` options:
  - `kept_clear` (by construction)
  - `none_in_frame`
  - `labels_unoccluded`, which needs a **measured**
    `subject_occluded_fraction` of at most `VISIBILITY_TOL_FRACTION` =
    0.03. Otherwise the bundle is refused.
- On measure, the look must be absent or `{"applied": false}`, with no
  pixel-moving effect and `beauty_samples.temporal` = 1. Otherwise it
  fails as `look.measure_altered`.
- The beauty FOV must equal the pose solver's (2 atan(w/2fx)) within
  `APPLIED_FOV_TOL_DEG` = 0.1 deg. This is the existing applied_intrinsics
  tolerance.
- Not treated as pixel-moving: depth of field, bloom, grain, vignette,
  tonemapping and the colour grade. These change values, not positions.
  Depth of field on an out-of-focus subject would spread its edge.
  `look_label_check` reads that as edge distance, not offset.

### UNCALIBRATED constants (experiments/look_label_check.py)

Each is set by a probe render on the render machine:

| constant | value now | the probe render that sets it |
|---|---|---|
| `SEARCH_RADIUS_PX` | 6 | The beauty chase frame with the look-dev lens distortion on. The largest recorded corner displacement must fit inside it. |
| `EDGE_PERCENTILE` | 80 | The measure chase frame. Its p90 edge distance should sit near 1 px. |
| `CONTROL_SHIFT_PX` | 3 | The measure chase frame. The control must recover the shift. |
| `CONTROL_SLACK_PX` | 1.0 | The same probe. Widen it only if the measure control is VOID on a picture known to be aligned. |

### Engine symbols

None added. This lane wrote no C++, so `scripts/check_bridge_api.sh` is
unchanged.

### Hooks other lanes must write (render host, render-path / look-dev)

The commandlet does not write the new keys yet. Until it does,
`look_label_alignment` is NOT RUN on every bundle. When a lane turns a
pixel-moving effect on, it must write `pixel_moving_effects`. When it
writes `VisualScene.BeautyOnlyActors` names into render.json, it must also
write `cloud_occlusion`. The verify gate does not ask for anything beyond
those two.

### Render-machine commands

Render the same card twice from the web app on Windows, so the masks
come from the labelled path:

```powershell
$env:FLIGHTSIM_RENDER_QUALITY = "measure"; .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008   # capture card X -> runs\webapp\<measure_id>, stop the server
$env:FLIGHTSIM_RENDER_QUALITY = "beauty";  .\.venv\Scripts\python.exe -m uvicorn webapp.server:app --port 8008   # capture the SAME card X -> runs\webapp\<beauty_id>
.venv\Scripts\python -m flightsim.verify runs\webapp\<beauty_id>
.venv\Scripts\python -m experiments.look_label_check --measure runs\webapp\<measure_id> --beauty runs\webapp\<beauty_id> --camera chase --out runs\visual\look_label_check.json
```

`look_label_check` exits 0 for ALIGNED, 1 for NOT ALIGNED and 2 for VOID.
Record each run's offsets here, and in ruflo under
`visual-overhaul/verifier-tooling/probe-<date>`, before changing any
constant above.

## j11-package

**What exists (code only, 2026-11-09, Mac; nothing rendered).** The J-11A
now converts from much more of github.com/yanes19/SU-27SK @ 925cb531 than
`Models/Su-27.ac` and the R-27R:
- `docs/visual/J11_PACKAGE.md`: all 701 files of the package (path, bytes,
  git blob sha1, purpose, used), generated from the GitHub tree API by
  `python -m assets_pipeline.package_inventory <tree.json> assets/aircraft_config/J11.json docs/visual/J11_PACKAGE.md`.
- `assets/aircraft_config/J11.json package_files`: 29 pinned files (git
  blob sha1 + sha256 + bytes), checked by `assets_pipeline/package_pins.py`
  after `fetch_source` and again before every convert; refusal
  `aircraft.package_pin`. A manifest converted before the pins is stale
  (`importer._package_pins_reason`), so the render machine re-converts and
  re-imports the J-11 on its next run with no manual step.
- Converter (`assets_pipeline/convert.py`): the model XML's livery material
  animation, object by object (`livery`: PLAAF2Div onto the ten objects
  J-11A.xml names; every other object keeps Su-27_Flanker_P01.png);
  `interior` parts (panel.ac, seat2.ac, the pilot) with the summed
  panel-zh.xml offsets and the seat's -5 deg pitch; `views.pilot_eye` from
  J-11A-set.xml; `material_sources.json` beside the OBJs (the .ac
  rgb/spec/shi/trans per MTL slot). Refusals `aircraft.livery_unmatched`,
  `aircraft.interior_outside_hull`, `aircraft.texture_collision`
  (core/messages/catalog.yaml).
- Look (`scripts/aircraft_look.py`, `assets/aircraft_config/look/J11.json`):
  `fg_material` derives per-slot roughness from the .ac shininess,
  r = (2 / (shi + 2)) ** 0.25, triangle-weighted, clamped; the
  `package_model_m` anchor puts lamps and nozzles where the package's model
  XML puts them. `ue_aircraft_materials.create_look_instances` passes the
  converter's record through.
- Tests: `tests/test_j11_package.py` (40), plus the mechanism test in
  `tests/test_aircraft_look.py` now on an inline config.

**Measured on the Mac from the pinned files (converter run, no engine).**
- 25 MTL slots; textures PLAAF2Div 4096x2048, Su-27_Flanker_P01 4096x2048,
  su-27gears 1024, Glass_Cockpit 1024x512, R-27R 512, panel front 2048,
  panel.wcs 1024x652 -> 1024x512 (the converter's power-of-two resample),
  seat/pilot 128-512. All ten livery objects matched once.
- Body triangles 9,577 -> 35,068 (panel 2,426, seat 19,489, pilot 3,576).
  `parts`, `components` (the R-27R boxes), `mesh_extents_actor_cm`,
  `mesh_extent_actor_m`, `mesh_origin_actor_cm` (0.0078, 0, -10.57) cm and
  the measured vertex counts are byte-identical with and without the
  interior/livery/pins.
- Interior extents (actor, about the model origin): x -6.55..-3.86 m,
  y -0.60..0.65 m, z 0.21..1.58 m; inside the hull and under the canopy.
- The package carries NO normal, specular, metalness or light maps (one AO
  map, for an instrument not imported); `glass.eff` has normal maps off.
  So metallic is never derived and no normal map is bound; the masters'
  procedural panel normals stay the only normal detail.
- Nozzles: the old `fdm_thruster` anchors (J11.xml y +-20 in = +-0.51 m)
  snapped to the TAIL STING at x 21.5 m: the beauty afterburner plume came
  out of the tail cone. The package's petal rings (J-11A.xml Nozzles.xml
  offset + NozzleL.xml) centre at (19.227, -1.277 / +1.263, -0.196) m; the
  hull's own nozzle exits measure x 19.19 m, rim radius 0.45-0.58 m about
  those lines. The FX nozzles now sit there (radius 0.5 m kept); thrust
  still comes from the FDM engine index.
- Lamps: LightPack.xml nav red/green at (16.12, -+7.5, 0.32) m (12 cm from
  the nearest hull vertex), beacons (flashing, 400 cd) at the same points,
  two landing lamps at (7.65, -+0.13, -0.48) m. The package's strobes and
  tail light are commented out; the strobes are dropped, the tail lamp
  stays on the measured aft vertex (stated as not from the package). The
  taxi lamp has no FX kind and is not drawn.

**Decisions.**
- Interior, seat and pilot are drawn IN THE BODY PART: they take the
  aircraft's class and int_id (the commandlet stencils every primitive of
  the aircraft actor), get no component and no box, and must lie inside
  the hull's extents (else `aircraft.interior_outside_hull`), so they can
  never grow the silhouette the labels measure. They are kept out of the
  extents that set the origin and anchors. No C++ change was needed
  (no engine symbols used; nothing added to check_bridge_api.sh).
- Glass and visor are class `glass` by slot rule (the MTL has no `d`, so
  before this lane the canopy was PAINTED with Glass_Cockpit.png). The
  cockpit, seat and pilot slots are class `rubber` (matte Default Lit, no
  clear coat, no panel lines). Airframe paint roughness is NOT derived:
  every Su-27.ac paint material is shi 128 spec 1 (an authoring habit,
  roughness 0.35), which would make matte PLAAF grey glossy.
- Not imported, recorded: the 85 animated instrument / console meshes
  (Nasal / canvas), the stick, throttle and pedals, the nozzle petals
  (throttle-animated, and J-11A.xml's second Nozzles.xml places one ring
  3.2 m off the airframe), the other 13 liveries, the R-27ER / R-73 /
  countermeasure stores (not in the FDM loadout), FlightGear's particle
  effects (the FX lane draws its own).

**Open, needs the render machine.**
- Measure path: the interior is part of the shared body asset, so measure
  draws it too. From outside it is hidden by the opaque canopy and the
  hull (silhouette unchanged); a camera INSIDE the canopy now sees a
  cockpit labelled as aircraft (it is aircraft). Check
  `python experiments/gate6_visual.py` passes unchanged after the J-11
  re-import.
- Glass is opaque (aircraft lane decision), so the cockpit-shoulder shot
  (SHOULDER_OFFSET 6 m behind the CG, outside the canopy) will NOT show
  the pilot or panel through it. The interior shows from the pilot-eye
  station (`mesh_manifest.json views.pilot_eye`, actor (-523, 0, 134) cm)
  only if the single-sided canopy faces point outward (unverified: looked
  at from inside they would then be culled). Probe: a J-11 render with an
  explicit camera at the pilot-eye station, and the contact sheet's shot d.
- The seat's pitch sign (`_pitch_model`, FG nose-up positive, from memory)
  and the pilot sitting in the seat: look at the pilot-eye frame.
- UNCALIBRATED: `fg_material` roughness_min 0.5 / max 0.95; beacon 400 cd;
  the 0.5 m nozzle radius against the measured 0.45-0.58 m rim.

**Render-machine steps.**
1. Pull; the next J-11 render (webapp/runs.py ensure_aircraft_model -> importer.ensure_model)
   finds the manifest stale, verifies the 29 pins, re-converts and
   re-imports. Expect "29 pinned package file(s) verified".
2. `UnrealEditor-Cmd ue/FlightSim.uproject -run=pythonscript -script="scripts/ue_fix_aircraft_materials.py J11"`;
   `assets/generated/J11/look_manifest.json` must list mat_Glass_Cockpit
   as glass and the cockpit slots with a `derived` roughness.
3. `python experiments/gate6_visual.py` (measure unchanged).
4. `python experiments/visual_contact_sheet.py` shots a and d; look at the
   livery, the nozzle plume origin and the nav/beacon lamps at the tips.
