# Visual overhaul probe log

One `## <lane>` section per lane of the 2026-11-09 visual-overhaul session
(flightsim-83, swarm `swarm-1794241474984-rmywk3`): render-path, world,
look-dev, aircraft, verifier-tooling, and the integration that merged them.
Each lane keeps to its own heading, so merges stay trivial.

That session ran on a Mac that cannot build or render (Xcode 27.2 is above
UE 5.7.4's ceiling of 26.9, and Cesium for Unreal is not installed), so
**nothing below has been rendered or measured**. Every look constant is
UNCALIBRATED: a probe render on the render machine sets it. Each section
lists those constants, the probe that sets each one, and the exact command
to see it. The render machine reads this repo copy. The shared record is
ruflo memory, namespace `visual`, key `visual-overhaul/<lane>/<topic>`.

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
9. **Reflections:** LumenSceneDetail is 2, front-layer translucency
   reflections are on, and SSR quality is 100. (Integration: Lumen's
   reflection, final-gather and scene-lighting quality and its trace
   distance are the render-path lane's alone, see `## integration`.)
   Whether Lumen runs inside a scene capture on this build is still a
   probe question.

### Uncalibrated constants and the probe that sets each

All live in `core/scene/beauty_look.py`. Each carries the comment
"UNCALIBRATED: set by probe render on the render machine".

| Constant | Starting value | Probe |
|---|---|---|
| `EV100_BANDS` | 15.0 / 14.5 / 13.9 / 13.0 / 12.0 / 11.0 from >=40 / 25 / 15 / 8 / 4 / below | one clip per band: the sunlit grey card at ~18% of white after the tonemapper, sky unclipped |
| `GRADES` (golden_hour, desert_noon, storm, overcast) | see file; ColorGain neutral, WhiteTemp the one warmth knob | the same frame graded four ways on one contact sheet, a white quad in frame |

(Fix pass 2026-11-09: `UE_ZENITH_TRANSMITTANCE` and `SUN_TEMPERATURE_BANDS`
are gone. The beauty sun is the physical sky's outer-space lux and the
engine's per-pixel transmittance dims and reddens it once.)
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
  `max_material_offset` = Strength/100 x 0.875 (the HLSL's peak) and, in
  `pixel_moving_effects`, the engine's bound in px (x width x 0.00023 /
  tan(hFOV/2), along the diagonal: UE 5.7.4 DistortionCommon.ush; fix pass
  2026-11-09, the old "screen fraction" was not the engine's scale).
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
- `lights`: LightVisualGain, BulbRadiusCm (J-11: 6), StrobePeriodS,
  StrobeFlashS, LandingMaxAglM, LandingConeDeg, NavAttenuationM,
  LandingAttenuationM, BlondelReyS. Probe: dusk and noon beauty of the type
  at chase range. (Candela values are 14 CFR 25.1391 / 25.1401 minimums from
  memory, not uncalibrated look numbers; a flashing lamp is driven at the
  Blondel-Rey peak of its effective minimum.) Fix pass 2026-11-09: the
  bulb's luminance is no longer a constant (BulbEmissivePerCd 2, capped at
  3000, made a 40 cd lamp show under 1 cd): it is the candela over the
  sprite's integrated falloff (`bulb_luminance_nits` per lamp), so the bulb
  and its light are one number under the frame's one exposure.
- `contrail`: MaxTemperatureK 233.15, MinAltitudeM 7500, LifetimeS,
  FormationDelayS, StartWidthM, SpreadMPerS, Opacity, PreseedS. Probe: cruise
  beauty above 9 km, chase and side views.
- `vapour`: MinNz 4, LifetimeS, StartWidthM, SpreadMPerS, Opacity. Probe:
  a 5 g pull-up.
- `afterburner`: PlumeLengthRadii, AfterburnerCandela, GlowGain,
  AttenuationM, Shocks; core/tip HUES in `aircraft_look.py`. The flame's
  luminance is AfterburnerCandela over the plume's emitting area
  (`plume_luminance_nits` per nozzle; fix pass: the old fixed 30 nit core
  was about 1000x dimmer than its own 60000 cd light). Probe: full reheat
  take-off, rear quarter.
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
   (bound: `pixel_moving_effects` heat_haze `max_displacement_px`).

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

## integration

Session flightsim-83, 2026-11-09, after the five lanes merged into
`claude/vibrant-gauss-olema4`. Code only: nothing here has been rendered.

**Read this first on the render machine.** UE 5.7's
`USceneCaptureComponent::OnRegister` calls `UpdateShowFlags()`, which resets
a capture's `ShowFlags` to the class default and re-applies only its
`ShowFlagSettings`. Every flag the commandlet set before `RegisterComponent()`
was being dropped. That explains the owner's fixture
(`tests/fixtures/engine_bundle_min`, `anti_aliasing.labels` = "DEFECT: label
capture anti-aliasing show flag is on"), and it means the beauty's TSR, the
look-dev lens (DOF, motion blur, grain, fringe, local exposure) and the
path tracer's show flag never reached the renderer in any earlier probe.
On beauty and pathtrace, `RenderPinShowFlags` now writes them into
`ShowFlagSettings` for the beauty, every label capture, the calibration
capture and the linear and accumulation captures. Measure keeps its old
registration: its bytes are unchanged and the label defect still stands
there. Fixing measure is the owner's call, because it changes Gate 6's
label bytes. Expect the first beauty frame after this build to look
different from every earlier probe (TSR, DOF and motion blur are now on).

| decision | where | check on the render machine |
|---|---|---|
| render.json gets `pixel_moving_effects`, `beauty_samples`, `beauty_only_actors` and `cloud_occlusion` on beauty and pathtrace (none on measure) | `RenderWriteLookContract`, `FFlightSimWorldBeauty::CloudOcclusionRecord` | `python -m flightsim.verify runs\<id>`: `look_record` PASS; `look_label_alignment` FAIL (beauty-not-label-aligned) until `look_label_check.py` measures motion blur, DOF and the cloud fraction. That FAIL is expected. |
| Lumen quality, trace distance and surface cache: render-path only | `RenderBeautyLumen*`; look-dev no longer sets them | `render_settings.beauty_path.lumen_capture_overrides` is the record. `beauty_look.applied.reflections.lumen_quality_owner` points to it. |
| Order of application: scene, world, exposure, look-dev, render-path, storm meter, per frame | comment block at `ApplyBeautyPostProcess(Capture)` | `render_settings.beauty_owners` (lens values differ by look) |
| The world look leaves a `-sky=` plan's per-pixel transmittance alone | `FFlightSimWorldBeauty::ApplyAtmosphere` | `look_applied.world_beauty.atmosphere.sun_per_pixel_transmittance` |
| Label captures turn every beauty-only flag off by name, and the flags survive registration | `ConfigureLabelCapture`, `RegisterLabelCapture` | `render_settings.label_show_flags` all false; `anti_aliasing.labels` = "none" |
| The linear EXR and the accumulation capture are lens-free | `RenderMakeLensFree` | `render_settings.linear_capture.lens` = "lens_free"; `sensor.json` linear_source says lens-free |
| Unity names unique | `tests/test_unity_names.py` | first clean-clone build |

## tiles-delight

Module tiles-delight (2026-11-09, written on the Mac; nothing rendered).
Google's photogrammetry carries the capture day's cast shadows: dark,
blue (skylight only) and pointing the capture sun's way. Under the
simulated sun at another hour they read wrong and double the engine's own
VSM shadows and Lumen AO. `assets/shaders/world/tiles_delight.hlsl` runs
in `M_FlightSimTilesBeauty` ahead of `tiles_base_colour.hlsl` and lifts
pixels that are darker than `DelightRatioKnee` of the coarse-mip local
mean AND blue-shifted (B/R above 1, times `DelightBlueGate`) toward that
mean, pulling their chroma to the mean's. Python twin
`core/scene/tiles_delight.py` (`delight`, `DELIGHT_DEFAULTS`); tests
`tests/test_tiles_delight.py` pin the HLSL constants, input order, MPC
names and the C++ numbers to it.

Rules it keeps: a per-frame shader op only (Google Map Tiles policy: no
baked texture, no cache, no tool that writes a de-lit image; attribution
untouched); the tiles stay the ground; colour only, no WPO or depth, not
in `PIXEL_MOVING_KEYS`; the label captures never draw this material.

What a render records:

* `look_applied.world_beauty.tiles.delight` -- `amount`, `mip_bias`,
  `ratio_knee`, `blue_gate`, `preset`, `basis` ("shader per frame,
  nothing stored (Google tile policy)"), `pixel_moving: false`,
  `calibration: UNCALIBRATED`, `contact_shading` (a pointer to the
  atmosphere record below). `mip_bias` and `ratio_knee` are the C++
  constants, the values the material is built with; they are not read back
  from `M_FlightSimTilesBeauty`, so a material rebuilt with other defaults
  would not show here (review note, 2026-11-09);
* `tiles.parameters.DelightAmount` / `DelightBlueGate` -- what the MPC got
  (a `_set: NOT SET` beside either means the collection predates this
  module: rebuild `MPC_FlightSimWorld` with
  `FLIGHTSIM_REBUILD_MATERIALS`);
* `world_beauty.atmosphere.contact_shading` -- the read-back of
  `r.Lumen.ScreenProbeGather.ShortRangeAO` and `...ShortRangeAO.HorizonSearch`
  (set to 1 by code; both are `ECVF_Scalability`, default 1 in 5.7.4) and
  the sun's `ContactShadowLength`.

Where it deviates from the brief: the contact shading is set in
`FlightSimClouds.cpp` (the beauty world look, `ApplyAtmosphere`'s sun
block), not through the `-beauty-look=` sidecar, so the look-dev and
render-path files other lanes are editing were not touched. It is still
beauty only (the world look is built only under `-quality=beauty`). Move
it into the sidecar later if that lane wants one place for every cvar.

UNVERIFIED (could not be checked on this Mac):

* that Cesium's per-tile base-colour textures carry mips. If they do not,
  the `MipBias` sample returns the full-resolution texel, `ratio = 1`,
  the shadow weight is 0 and the node is an exact pass-through (fails
  safe, looks unchanged). Probe: the A/B below shows no difference at all.
* that `unreal.TextureMipValueMode.TMVM_MIP_BIAS` is the Python spelling
  of `TMVM_MipBias` (the script's other enums follow the same rule) and
  that two `TextureSampleParameter2D` nodes with the same parameter name
  both receive Cesium's per-primitive texture.
* (review, 2026-11-09) that the coarse mip is a fair "local mean". The
  photogrammetry textures are atlases of UV islands; at +5 mips a texel
  averages neighbouring islands and any padding between them, which can be
  another part of the scene or a fill colour. A dark or black padding
  lowers `Lm`, so true shadows are lifted less (safe); a bright one raises
  `Lm` and can lift pixels that are not shadows at island edges. Probe: in
  the A/B, look for bright fringes along texture seams on roofs and slopes;
  if there are any, lower `DelightMipBias`.

| constant | value | probe that sets it |
|---|---|---|
| `DELIGHT_DEFAULTS` (DelightAmount) | clear/hazy 0.5, overcast/rain/storm 0.2 | A/B below; raise until the baked shadows vanish without the ground going flat |
| `DelightMipBias` | +5 (32x32 texels) | at 300 m AGL, the mean must span a building shadow, not a block; try +4..+7 |
| `DelightRatioKnee` | 0.6 | lowest value that still catches the Zermatt valley-side shadows; too high lifts dark roofs and forest |
| `DelightBlueGate` | 4 | asphalt and dark rock must stay put (B/R ~1); raise if neutral darks lift |
| `ContactShadowLength` | 0.05 (screen share) | aircraft on the runway: a contact line under the gear without self-shadow acne |

PROBE (render machine): the same camera, A/B with `DelightAmount` 0 against
the preset value (via the MPC defaults or a rebuild), over Zermatt and over
Yosemite Valley, at a sun time far from the capture day's (e.g. 08:00 local
against Google's late-morning captures). Pass: no second, wrong-direction
shadow on slopes and building fronts in B; asphalt, water and dark forest
unchanged in mean luma within 2 %; the attribution string unchanged; the
mask, class and depth captures byte-identical between A and B. Record the
frames here and in ruflo under `visual-overhaul/tiles-delight/probe-<date>`.

## sun-shafts-sky-occlusion

Module: `FFlightSimSunShafts` (`Public/FlightSimSunShafts.h`,
`Private/FlightSimSunShafts.cpp`), table `core/scene/sun_shafts.py`, tests
`tests/test_sun_shafts.py`. Written 2026-11-09 on the Mac that cannot compile
or render the bridge. Nothing here has been built or rendered.

### What was built (BEAUTY ONLY, value-only)

`FFlightSimWorldBeauty::Build` calls `SunShafts.Apply` once, right after
`ApplyTiles`, so it runs only under `-quality=beauty` or `-quality=pathtrace`.
It records everything in `look_applied.world_beauty.sun_shafts`.

* Sun (`UDirectionalLightComponent`): light-shaft occlusion on, with mask
  darkness and depth range. Light-shaft bloom only where a sun disc shows
  (clear 0.2, hazy 0.25, rain 0.02, overcast and storm off). Cloud shadow on
  the SkyAtmosphere (clear and hazy 1.0, which gives the crepuscular rays)
  and on surfaces, with the shadow map's extent, resolution and ray samples.
  The cloud fields have no setter in 5.7.4, so they are written directly and
  followed by `MarkRenderStateDirty()`. `bCastShadowsOnAtmosphere` belongs to
  `ApplyAtmosphere` and `bCastCloudShadows` to the scene (Gate 6's cloud
  bracket). This module reads both and writes neither.
* Sky light: cloud ambient occlusion. Overcast, rain and storm are 1.0, so the
  ground goes darker under the deck. Clear is 0.5 and hazy 0.6. The record
  also notes whether the sky light is a real-time capture, because the
  `RealTimeReflectionCapture` cvars only act on one.
* Cvars: each value is saved before it is set. `FFlightSimWorldBeauty::
  RestoreCvars()` puts them back at the commandlet's final teardown. On the
  still tier only (`-still-samples=`, `-accumulate=`, `-quality=pathtrace`,
  or `-sun-shafts-tier=still` / `FLIGHTSIM_SUN_SHAFTS_TIER`), the fog grid
  goes to 4 px x 128 slices. The still tier also sets
  HistoryMissSupersampleCount 16, the cloud shadow map and sky AO,
  HighQualityAerialPerspective, SampleAtmosphericLightShadowmap, the
  sky-light capture (TimeSlice 0, VolumetricCloudResolutionDivider 1,
  ShadowFromOpaque 1), LightShaftQuality 1 and LightShaftDownSampleFactor 1.
  The interactive tier sets only ShadowMap, SkyAO and LightShaftQuality, all
  to 1, which are their engine defaults.
* Dropped: `r.LightShaftNumSamples`, which is `ECVF_ReadOnly` in the 5.7.4
  `LightShaftRendering.cpp`, so a runtime set is refused. Every other name
  was grepped in the 5.7.4 Renderer source and is checked by
  `scripts/check_bridge_api.sh` (block "sun-shafts-sky-occlusion").
* Show flags: `LightShafts` and `VolumetricFog` are forced on the beauty
  capture only, inside the commandlet's beauty block. The accumulate and
  linear captures copy the beauty flags. The calibration capture copies them
  and then turns `LightShafts` off. `ConfigureLabelCapture` turns
  `LightShafts` and volumetric fog off on every label capture (skeptic fix,
  2026-11-09: `RenderLightShaftBloom` in the 5.7.4 DeferredShadingRenderer.cpp
  is gated by the LightShafts flag alone, not Bloom, and adds into SceneColor,
  so with the sun's light-shaft bloom now on it would have run on the label
  views too).
  `render_settings.beauty_show_flags.light_shafts` records the value the
  capture actually had.
* No ephemeris change. `core/environment/sun.py` already applies NOAA
  piecewise refraction.

### Labels

Value-only: radiance changes and no surface moves, so this is not in
`PIXEL_MOVING_KEYS`. The light switches and the cvars are process-wide while
a beauty render runs, so the label captures in that run share them. The label
captures draw no fog, atmosphere, cloud or light shafts, and they read stencil, depth,
normal or base colour through their own post-process materials. Their bytes
should therefore be the same with the module on or off. That is a claim, not
a measurement (probe 5).

The module spec said a Gate V bloom-ceiling check already measures the mean
mask-edge luminance change. **No such clause exists.**
`experiments/gate_v_visual.py` has no bloom metric (grepped 2026-11-09).
`look_label_check`'s mask-edge distance is the nearest existing check.

### UNCALIBRATED constants

Every value in `SHAFT_PRESETS`, `STILL_CVARS` and `INTERACTIVE_CVARS` is
uncalibrated: bloom scale, threshold and max; occlusion darkness and depth
range; cloud-shadow strengths, extent, map resolution and ray samples; sky-AO
strength, extent, map resolution and aperture; fog grid sizes; and the
supersample and downsample counts. They are engine defaults and orders of
magnitude, never taken from a frame.

### Probes (render machine)

1. **Light shafts inside a SceneCapture2D.** `ShouldRenderLightShafts` needs
   `GLightShafts`, the LightShafts and Lighting show flags, and no debug view.
   Nothing in it excludes a scene capture, but this has not been seen.
   Render clear golden hour with the sun just off-frame behind a ridge, then
   A/B `-sun-shafts-tier=still` against a build with the hook commented out.
   Record whether the rays appear.
2. **HighQualityAerialPerspective visible from 3000 m.** Cumulus at 1500 m
   seen from 3000 m AGL, with `r.VolumetricCloud.HighQualityAerialPerspective`
   at 1 and at 0 (console). Record the mean sky-region delta.
3. **TimeSlice=0 cost.** Time per still frame with
   `r.SkyLight.RealTimeReflectionCapture.TimeSlice` at 0 and at 1, still
   tier, 1920x1080. Record ms per capture.
4. **Matterhorn golden-hour A/B (shot a)** and **Yosemite storm A/B
   (shot c)**. The same card with the module on and off, each with a contact
   sheet. These set the bloom and occlusion values (a) and the sky-AO
   strength (c).
5. **Label bytes A/B.** For shots a and c, compare the mask, class and depth
   sha256 with the module on and off. If they are not identical, the
   value-only claim is wrong: move the switch onto the beauty capture or
   record it in `pixel_moving_effects`.

Record each result here and in ruflo under
`visual-overhaul/sun-shafts-sky-occlusion/probe-<date>` before changing any
constant.

## wet-airframe-canopy

Session 2026-11-09, Mac, code only: nothing here has been compiled or
rendered. Wet airframe, airflow rain streaks and canopy micro-scratches (no
pilot).

**What exists.** `assets/shaders/aircraft/aircraft_wet.hlsl` (film darkening
`lerp(albedo, albedo^2, wet*porosity)`, roughness `lerp(r, min(r,
WetRoughness), wet)`, rivulets, beads, the `WetCoat` clear-coat mask as a
Custom-node additional output); `assets/shaders/aircraft/canopy_scratch.hlsl`
(circular-swirl tangent about `CanopyCentreCm`, negative anisotropy so the
highlight smears across the scratches); `scripts/aircraft_wet_layer.py`
(`add_wet_layer`, `add_canopy_scratch`, `WET_DEFAULTS`, the numpy twins);
`FlightSimAircraftWet.cpp/.h` (the wetness integration and the four
per-step scalars `Wetness`, `RainRateMmh`, `AirspeedKts`, `TimeS`).
Tests: `tests/test_aircraft_wet.py`.

**Decisions.**
- Shading only, on the beauty look MIDs. No World Position Offset, every
  master stays opaque (the documented "glass is opaque" decision holds), so
  silhouette, class, mask and depth are those of the dry airframe:
  `render.json aircraft_look.wet.pixel_moving: false`, no
  `pixel_moving_effects` entry. The MakeHuman pilot and a translucent canopy
  are rejected (label-unsafe).
- The graft is Break -> Custom -> Make inserted after the master's own
  attributes, so the class graphs are untouched; `LOOK_GENERATION` is now
  `"2"` so every master rebuilds once with the layer.
- `FFlightSimAircraftFX::ApplyMaterials` now wraps each look instance in a
  MID (the wet scalars are per step). Same parent, same shading at
  Wetness 0.
- The rain rate is read from the weather's public record
  (`Record.rain.rate_mmh`, `rain.beauty_readability_gain`): those fields are
  private in `FlightSimWeather.h`, which stays untouched. The wetness uses the
  physical rate; the rivulets see rate x beauty gain (the drops' own stated
  exaggeration).
- Wetness: target `saturate(rate / WetSaturationMmh)`; wetting immediate,
  drying `exp(-dt / WetDryTauS)` on `simulation/sim-time-sec` (exact, so
  step-size independent); the first step starts at the target.
- Regime: `airflow` at or above `BeadingMaxKts` (lines aft along object -X,
  panned at `StreakSpeedPerKt x airspeed` cm/s), else `gravity` (runs along
  world -Z expressed in the object frame, so the pattern rides the airframe;
  beads, mostly on glass).
- The canopy scratches need `r.AnisotropicMaterials` (1 at
  `ShadingQuality@Cine`, BaseScalability.ini 5.7.4, which the beauty path
  uses) and a world-space tangent: the glass master's `tangent_space_normal`
  is now off with `VertexNormalWS` wired explicitly (an unconnected
  world-space normal would default to +Z). The cvar's value at render time is
  recorded in `aircraft_look.wet.canopy_scratch.r_anisotropic_materials`.
- Storm weather is default-on, so this is on in the default web render with
  no new flag. Without a built weather the airframe stays dry (pointer null).

**Not done / known gaps.**
- The card's own `wetness` (wet ground after the rain stopped) does not wet
  the airframe: `SceneOptions` is out of scope at the aircraft build in the
  commandlet. Only drawn rain does.
- `CanopyCentreCm` defaults to the mesh origin (concentric circles about a
  distant centre read as long curved wipe lines); a per-type centre is a
  probe item.

**Uncalibrated constants** (all of `WET_DEFAULTS`, copied into every look
manifest as group `wet`, and the HLSL literals `GravityRunCmS` 3.0,
`BeadRoughness` 0.3, `RingCm` 0.8): StreakSpeedPerKt 0.5, BeadingMaxKts 60,
WetRoughness 0.08, WetCoatRoughness 0.03, WetSaturationMmh 4, WetDryTauS 90,
Porosity paint/bare metal/glass 0.3/0.12/0 (rubber takes no wet layer), BeadAmount
paint/bare metal/glass 0.3/0/1, StreakPitchCm 2.5, StreakLengthCm 30,
RivuletFullMmh 10, ScratchDensity 0.6, ScratchAnisotropy 0.5,
CanopyCentre (0, 0, 0).

**Probes, on the render machine, in order.**
1. `scripts/check_bridge_api.sh`: the `wet:` lines all ok.
2. Build, then `scripts/ue_create_materials.py` (expect `MATERIAL-REBUILT`
   for every aircraft master, since `LOOK_GENERATION` 2 restamps them all,
   and no `MATERIAL-FAILED`), then
   `ue_fix_aircraft_materials.py` for the look manifests' `wet` group.
3. Storm-weather beauty chase at shot c range (default web render): read
   `aircraft_look.wet` (wetness, regime, mids > 0) and judge the paint
   darkening, the coat and the aft streaks; set WetSaturationMmh, Porosity*,
   WetRoughness, StreakSpeedPerKt, StreakPitchCm/LengthCm.
4. Canopy close-up into the sun (and shot d from outside): judge the beads
   (below BeadingMaxKts) and streaks on the glass and the scratch swirl; set
   BeadAmountGlass, ScratchDensity, ScratchAnisotropy, CanopyCentreCm.
5. `look_label_check` on a storm beauty run: ALIGNED (nothing here may move a
   label edge).

## dust-humidity-haze

Module: dust and humidity haze, an overlay on the world beauty's atmosphere
preset. Written 2026-11-09 on the Mac that cannot compile or render the
bridge. Nothing here has been built or rendered.

### What was built (all BEAUTY ONLY)

`FFlightSimDustHaze` (`FlightSimDustHaze.h/.cpp`) is a member of
`FFlightSimWorldBeauty`. `Build` calls it right after `ApplyAtmosphere`, so
`-quality=measure` never reaches it. It records into `render.json`
`look_applied.world_beauty.dust_haze`. `core/scene/dust_haze.py` is the Python
twin and holds the documentation. `core/scene/world_record.py` puts the
expected values (`spec_parameters`) in the `scene.world` record's parameters
as `dust_haze`.

* Hygroscopic growth (Hanel 1976): the preset's Mie extinction is multiplied by
  f(RH) = (1 - min(RH, 0.95))^-gamma. gamma is 0.3 continental, 0.5 maritime
  (ocean surface) and 0.1 dust. RH comes from the card: `look.rh_pct`, then
  `weather.rh_pct`, then the atmosphere block's stated relative humidity, then
  its stated dew point against 15 degC plus the stated deviation (Magnus).
  With none of these it defaults to 50 %, recorded as `rh_basis: default`.
* Row: `weather.dust` (or `look.dust`) first, then a METAR dust or sand code
  in `look.present_weather` / `weather.present_weather` (DU, SA, BLSA, DS, SS,
  PO), then a `desert` surface (`weather_look.surface`), then HZ / FU / BR,
  which select `haze`. Otherwise `none`. An unknown dust word is refused by
  name in Python (`dust_haze.row`). The C++ records it and draws `none`.
* Dust tint: a warm Mie absorption colour (blue absorbs about 2.2x green, red
  about 0.45x), a tint on the other-absorption layer and a tan volumetric fog
  albedo.
* Boundary-layer cap: the scene fog's second fog
  (`SetSecondFogData`) with its offset at the inversion height (the row's
  default, or `look.inversion_height_m` / `weather.inversion_height_m`). The
  engine fog is exponential, not a slab. At falloff 0.015 the density halves
  every 667 m above the inversion and doubles as fast below it. The "flat top"
  is that steepness.
* Visibility kept: the grown Mie and the second layer's ground extinction are
  taken out of the main fog (`fog_density_ratio`). When together they would
  exceed the haze, both are scaled by one factor (`renormalised`).
  `visibility_model_km` equals the card's to rounding.
* Labels: values only, `pixel_moving: false`. Each frame, the second layer's
  camera-to-aircraft transmittance is a `cloud_path` row
  (`layer: dust_haze_second_fog`). Under 0.5 it is flagged and sets
  `cloud_occludes_aircraft`, the same way a cloud does. The haboob local fog
  volume is out of scope.
* A/B switch: `-dust-haze=off` (or `FLIGHTSIM_DUST_HAZE=off`).

### UNCALIBRATED (set by probe render)

Every `DUST_ROWS` value (absorption colours, other absorption, fog albedo,
second fog density 0 / 0.0002 / 0.0004, falloff 0.015, inversion 1500 /
1500 / 1800 m), `RH_GAMMA`, `DEFAULT_RH_PCT` and `DEFAULT_INVERSION_HEIGHT_M`.

### Probes to run on the render machine

1. Shot b, desert, A/B: the same card with `-dust-haze=off` and with it on, at
   1600-3000 m. Check that the haze top reads as a layer below the camera,
   that the far terrain and the sky near the horizon warm (no magenta, no
   grey-brown mud), and that the subject's contrast at the card's visibility
   matches the off render. Tune `second_fog_density`, `second_fog_falloff` and
   the dust colours.
2. Shot c, humid forest (`look.rh_pct` 85) against the same card at RH 30:
   the aerial perspective should be milkier and brighter toward the sun with
   the same visibility. Tune `RH_GAMMA["continental"]`.
3. Each run: confirm `world_beauty.dust_haze.visibility_model_km` equals
   `visibility_target_km`, and that `look_label_check` is ALIGNED. The overlay
   moves no pixel, so any offset is another module's.

## aces2-display

Offline ACES 2.0 SDR display transform for beauty frames, plus two CC0
show LUTs. Written 2026-11-09 on the Mac, which cannot render. No C++.

### What it does

`core/capture/display.py` reads `frame_NNNN_linear.exr` (the commandlet's
`-linear` pass, `SCS_FinalColorHDR` into an RGBA16f target). It optionally
applies a show LUT and runs OpenColorIO 2.5's built-in config
`ocio://studio-config-v4.0.0_aces-v2.0_ocio-v2.5` (never `ocio://default`)
to display `sRGB - Display`, view `ACES 2.0 - SDR 100 nits (Rec.709)`. It
writes `frame_NNNN_aces2.png` beside the engine PNG. The engine PNG is never
touched. The result is recorded in render.json as `beauty_look.display`.
`r.HDR.Aces.Version` alone does nothing here, because it only reaches HDR
output devices 3-6, not the sRGB LDR beauty capture.

- Web: the look switch `cinematic_aces2` is quality beauty, lens cinematic,
  display aces2. It adds `-linear` to the commandlet and runs the step after
  each camera's pass (`webapp/capture.py render_passes`), and also on the
  camera-less path (`webapp/runs.py`). The page's `<select>` does not offer
  it yet. POST `"look": "cinematic_aces2"` to use it.
- CLI: `python -m core.capture.display <render dir> [--lut warm_print] [--exposure-scale 1.0]`.
- Labels: this is a per-pixel colour transform, so it is not in
  `PIXEL_MOVING_KEYS` and `pixel_moving: false`. It refuses on measure, or
  when no quality is named (`look.display_on_measure`).
- Refusals: `look.display_input` (only the 8-bit PNG exists),
  `look.display_unavailable` (no PyOpenColorIO or OpenEXR, or OCIO < 2.5).
  The web hook records a refusal in render.json (`beauty_look.display.refused`)
  and keeps the engine PNG. There is no fallback.

### Decisions

1. **The source is `Linear Rec.709 (sRGB)`, not the `scene_linear` role.** In
   this config `scene_linear` is ACEScg (AP1). UE's working colour space is
   Rec.709 primaries (ue/Config/DefaultEngine.ini sets none). Measured with
   the pinned wheel, an orange (0.5, 0.2, 0.05) gives (0.581, 0.375, 0.177)
   as Rec.709 and an over-saturated (0.683, 0.343, 0.114) when misread as
   ACEScg. Grey is the same either way. The record names `input_colorspace`.
2. **Show LUTs work on ACEScct code values.** The domain 0..1 covers linear 0
   to about 222. The step converts Rec.709 linear to ACEScct with OCIO,
   applies the cube (tetrahedral, numpy) and then runs the view from ACEScct.
   `scripts/make_show_luts.py` generates `warm_print` and `broadcast_neutral`
   from closed-form curves (33^3, six decimals, deterministic). They are the
   project's own work, CC0-1.0. `looks.json` holds the sha256 values, and
   tests regenerate and compare them.
3. **Pins:** `requirements-display.txt` has opencolorio==2.5.2 (2026-05-13)
   and openexr==3.4.16 (2026-10-03, which still has the legacy
   `InputFile`/`Imath` API that `profile.read_linear_frame` uses). Both are
   BSD-3-Clause (ASWF), with PyPI sha256 values for cp311-313 on macOS,
   manylinux and Windows. Neither is in the base requirements.
4. **Vendored reference:** 0.18 grey (Rec.709 linear) maps to display code
   0.3491875 (8-bit 89), black maps to 0, and 1.0 maps to 0.70668. Computed
   with 2.5.2 on macOS arm64. The test tolerance is 1e-4.

### Engine reading (5.7.4 source, not a measurement)

- `PostProcessTonemap.cpp`: `SCS_FinalColorHDR` gives
  `EDisplayOutputFormat::HDR_LinearNoToneCurve`.
- `PostProcessTonemap.usf:521-524`: scene colour times
  `OneOverPreExposure * GlobalExposure * VignetteMask * LocalExposure`, plus
  bloom, happen before the grading LUT. So the EXR appears to carry exposure,
  vignette, local exposure, bloom and the grade, but no filmic curve and no
  BlueCorrect. `scripts/check_bridge_api.sh` pins these three strings in the
  ACES2-DISPLAY block.

### UNCALIBRATED (probe on the render machine)

- Whether `SCS_FinalColorHDR` really is pre-tonemap scene-linear, with
  exposure and bloom included, as the source reading says. Until it is
  measured, the record says `input_basis: "UNVERIFIED pre-tonemap"`.
- The exposure scale the EXR needs before the view. It is 1.0 until then
  (`exposure_scale_basis: "UNCALIBRATED (1.0 until probed)"`).

Probe: render one `cinematic_aces2` still and run
`python -m core.capture.display <dir>`. Compare a grey card or the sky-free
ground mean against the engine PNG at the same pixels. If the ACES image is
systematically one stop off, record the scale here and in ruflo
`visual-overhaul/aces2-display/exposure-probe`.

## condensation-solver

Humidity-gated condensation on the airframe: wingtip vortex cores, the
upper-wing vapour sheet, LEX vortices (J-11 class) and the transonic vapour
cone. It replaces the old vapour rule (`accelerations/Nz > vapour.MinNz`, no
humidity) in `FlightSimAircraftFX.cpp` Advance. Code only. Nothing has been
compiled or rendered: this Mac cannot build UE 5.7.

### What it does

For each site it finds a local pressure `p_l`, takes the isentropic local
temperature `T_l = T (p_l/p)^0.2857`, and compares the vapour the free
stream carries with what the local air can hold, using JSBSim's Magnus
form (`core/environment/atmosphere.py`). The equilibrium condensate is
`dq = q_v - q_sat(T_l, p_l)` and is recorded. Opacity is
`clamp(OpacityPerGkg x (q_v - q_sat(T_l + OnsetCoolingK, p_l)))`, and
nothing is drawn below `VisibleMinGkg`.

| site | local state |
|---|---|
| tip | `Gamma = Nz W/(rho V b pi/4)`; Lamb-Oseen core `dp = 0.87 rho Gamma^2/(4 pi^2 rc^2)`, `rc = CoreRadiusSpanFraction b` (0.87 = ln 2 x 1.1209^2: rc is the peak-swirl radius) |
| sheet | `CL = Nz W/(qbar S)`, `Cp_min = -(SheetCpMinAtZeroLift + CpMinPerCL CL)`, `p_l = p (1 + 0.7 M^2 Cp_min)` |
| lex | only when `LexEnabled` and `alpha > LexAlphaOnsetDeg`: `Cp = -LexCpPerDeg (alpha - onset)` |
| cone | only when `ConeMachMin <= M <= ConeMachMax`: `T_l/T = (1+0.2M^2)/(1+0.2 ConeLocalMach^2)`, `p_l/p = (T_l/T)^3.5`. The cloud ends at the recompression shock (the cone's sharp aft edge). |

The Python twin is `core/scene/condensation.py`. Its tests are in
`tests/test_condensation.py`, and they pin the C++ constant names and
defaults to it by text.

### Two deliberate departures from the spec (measured with the twin)

* **Sheet zero-lift term.** The spec's `Cp_min = -(1 + k CL)` made the sheet
  fully opaque at 1 g in any humid low-level air, for example M 0.6, RH 80 %,
  sea level: `dq` 6.2 g/kg, as strong as a 5 g tip core. The `1` is now
  the constant `SheetCpMinAtZeroLift`, default 0.3 (a thin wing).
* **Onset margin.** `OnsetCoolingK` (6 K) stands in for the droplet growth
  time over a transit of a few milliseconds. The local air must cool this
  far below its dew point before the cloud shows. `VisibleMinGkg`
  (0.05 g/kg) makes high, dry air give exactly nothing: at 12 km and RH 30 %,
  `q_v` is only 0.03 g/kg.

Twin results (J-11-class numbers): a 5 g pull at M 0.6, RH 80 %, sea level
gives tip and sheet. At 1 g it gives neither. M 0.95 at RH 90 % gives the
cone; M 0.80 gives no cone. RH 0 gives nothing anywhere, and neither does
12 km at RH 30 %.

### Humidity source and fallback (render.json `aircraft_look.condensation`)

1. `-humidity-pct=<0..100>` is a beauty-only override for probes. The
   physics never sees it.
2. When the card states a dew point (`atmosphere_properties`
   `atmosphere/dew-point-R`), the commandlet sets `Humidity.bCardStated`
   and the FDM's `atmosphere/RH` is read every step.
3. Otherwise the old Nz rule runs (`fallback_used`, `fallback_frames`).

A card with no dew point is JSBSim's dry default. That is not a statement
that the day is dry, so it falls back rather than suppressing all vapour.
An FDM read that is NaN, or a read that must be positive and is not, drops
that site and lists it in `dropped`.

### Labels

The condensation draws on its own actors: one attached actor carrying the
sheet, cone and LEX sections, plus two world-space tip ribbons. None of
them is a component of the aircraft actor, and all of them are in
`BeautyOnlyActors`. `M_AircraftCondensation` is translucent: not in mask,
class or depth (the trail convention). It does not refract and has no WPO,
so `pixel_moving: false`.

`Advance` returns true only when the tips condense but this module could
not draw ribbons (no material or no CPU-readable vertices). In that case
the existing wingtip vapour trails carry them.

### Site placement (from LOD 0 vertices, actor frame)

* Tips: the +/-Y vertex extremes.
* Cone collar: the X slice with the largest Y span x Z span. Its radius is
  half that slice's Y span, and the shock sits `ConeLengthBodyFraction` x
  the body length aft.
* Sheet: in 6 span bands from `SheetSpanStartFraction` to
  `SheetSpanEndFraction`, the chord of the X-cluster with the largest
  extent (the wing, not a tailplane), at the 90th-percentile Z.
* LEX: `LexAftOfNoseM`, `LexSpanM` and `LexUpM` from the nose vertex.
  `assets/aircraft_config/look/J11.json` sets `LexEnabled` 1.

### UNCALIBRATED

These are engineering approximations:

* every `CONDENSATION_DEFAULTS` value;
* the 0.87 Lamb-Oseen factor;
* the compressible Cp form;
* Magnus over liquid water at every temperature (no ice phase);
* the material's colour, fade distance (60 cm) and noise scale.

### Probes (render machine)

| probe | sets |
|---|---|
| A humid low pass at M 0.95 (`-humidity-pct=90`, sea level, chase and side views) | `ConeLocalMach`, `ConeLengthBodyFraction`, `OpacityPerGkg`; the shock edge looks sharp; the sheet is present |
| A 5 g pull-up in the forest rain scene (card dew point, or `-humidity-pct=85`) | `CoreRadiusSpanFraction`, `OnsetCoolingK`, `CpMinPerCL`, `SheetCpMinAtZeroLift`, `LifetimeS`, `TipStartWidthM`, `TipSpreadMPerS` |
| A J-11 at alpha 20-25 deg, M 0.4, humid | `LexAlphaOnsetDeg`, `LexCpPerDeg`, the LEX offsets against the mesh |

Check: `aircraft_look.condensation.per_frame` shows the expected sites
(cone only between `ConeMachMin` and `ConeMachMax`), and `fallback_used`
is false when humidity was given.

### Engine symbols

`scripts/check_bridge_api.sh`, block `CONDENSATION (condensation-solver)`:
18 symbols, each grepped in the UE 5.7.4 headers (all present). The
refusal `aircraft_look.condensation` (contradictory or non-finite
constants) is in `core/messages/catalog.yaml`.

## camera-motion-layer

Lane: `core/capture/camera_motion.py`, `tests/test_camera_motion.py`; hooks
in `core/capture/poses.py` (`solve_pose_track` return), `core/scenario/camera.py`
(`CameraSpec.motion`), `webapp/capture.py` (render clock), `webapp/runs.py`
(`LOOK_SWITCHES['cinematic']['camera_motion'] = 'auto'` and one
`apply_look_motion` call before the capture solve), `core/capture/manifest.py`
(one line: the capture manifest's camera block carries `camera_motion`).
Session 2026-11-09, code only, Mac; **nothing rendered**. No C++ changed and no
engine symbol is used, so `scripts/check_bridge_api.sh` gains no block.

### Decisions

1. **Labels are safe by construction.** The motion perturbs the solved pose
   track before it is recorded or shipped; the beauty pass and every label
   capture consume one pose through `ApplyPoseAtTime`. Nothing is added to
   `pixel_moving_effects`.
2. **Profile `none` is the default and returns the input track object** (no
   resample, no subclass), so every existing digest and card is byte-identical
   (tested for chase, ground and cockpit, with and without a render clock).
3. **Two clocks, one pose.** The schedule and the manifest index the track by
   telemetry sample (`schedule.indices` -> `track.sample(i)`), so a motion
   track (`MotionPoseTrack`) keeps its own arrays on the telemetry clock and
   carries the render-clock track in `.dense`; `card_block` ships the dense
   arrays as `poses`. The dense clock is `t0 + k/(fps x accumulate)` UNION the
   telemetry times, and the telemetry-clock arrays are the dense samples at
   those exact times, so the manifest's label pose equals the pose the engine
   applies at each capture time (`label_pose: shutter-centre sample`).
4. **Web render clock = (30 fps, accumulate 1)**: the web passes no
   `-accumulate` (it is dev-only in `core/config_surface.py`).
5. **Noise is a sum of sinusoids evaluated at continuous t** with frequency and
   phase from `sha256(seed|camera_id|axis|k)`; amplitudes normalised to the
   profile's RMS. Rate independence measured at 1e-12 (30 vs 240 Hz).
6. **Roll shake clamp +/- 0.15 deg**, recorded as `roll_bound_deg` (and the
   count of clamped samples). `horizon_roll_tolerance_deg(record)` is the
   tolerance a horizon check may take: exact 0 for none, the bound otherwise.
   `tests/test_gate6_visual.py`'s roll is the AIRCRAFT's frame-record roll, not
   the camera's, so it needed no change; `PresetKeepsHorizonLevel()` (C++) is
   unchanged and still reports the preset.
7. **Aim lag** (camera_ship zeta 0.7 fn 1.5 Hz; tripod_fluid_head zeta 0.8 fn
   1.0 Hz) is an exact first-order-hold second-order step on yaw (unwrapped)
   and pitch, on the dense clock. Overshoot matches exp(-pi zeta/sqrt(1-zeta^2))
   within 1%. Measured on a 100 m/s chase with a 10 deg weave: 0.25 deg
   worst yaw lag.
8. **camera_ship turbulence scale** comes from the camera's own speed (the
   Catmull-Rom derivative of the solved track), not an airspeed column: the
   hook signature carries only the track, and the camera ship is the airframe
   that feels the turbulence. Wind is not included (recorded in the block).
9. **Cinematic look switch**: chase/wingman -> camera_ship 1.0, cockpit ->
   handheld 0.5, ground/tower/explicit -> tripod_fluid_head 1.0 (a deviation
   from "camera_ship for every external preset": a tower camera is not on a
   helicopter). A camera that states a motion block is never moved. The block
   rides in the camera's spec (`motion`, with `source`), so a cinematic run's
   spec digest records it.
10. **Card size measured**: 30 s on the densest clock the commandlet accepts
    (30 fps x 64) is 57,601 samples, 8,241,919 bytes of pose block. The
    commandlet reads the card with `FFileHelper::LoadFileToString` +
    `FJsonSerializer` (no cap below FString's int32), and `SetPoseTrack` takes
    any length >= 2. `ApplyPoseAtTime` searches linearly from index 1 per call,
    so a very dense track costs O(n) per sub-frame (not changed here).

### Uncalibrated

Every profile RMS (handheld 0.035/0.03/0.02 deg; camera_ship 0.03/0.04/0.02;
tripod 0.004/0.003/0.001), translation RMS (4 mm, 20 mm, 0), band edges and
counts, the blade-pass default 19.5 Hz and the 0.5 % line width, the speed
reference 60 m/s and clamp [0.25, 2], both lag zeta/fn pairs, and the
cinematic switch's intensity mapping. None was fit to footage.

### Open

* render.json itself (written by the commandlet) does not yet copy
  `cameras[N].camera_motion`; the record lives in the card's camera block and
  in the Python capture manifest's camera block. A C++ copy is a 3-line follow
  up for the commandlet lane.
* `manifest.camera_angular_rate` (rolling shutter) differentiates the
  telemetry-clock track, so it under-reads shake above 5 Hz.
* `track_violations` checks the telemetry-clock samples; the shake between
  them is millimetres.

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

### j11-package skeptic review (2026-11-09)

Reviewed `git diff claude/vibrant-gauss-olema4...worktree-wf_d78a46c2-467-1`
on the Mac, no engine. What was checked, and what came of it:

- **Pins.** I downloaded all 29 `package_files` from
  raw.githubusercontent.com at 925cb531 into a scratch tree, and
  `package_pins.verify` passed on all 29 (git blob sha1, sha256, bytes).
  The converter ran on that tree alone, so it reads no file outside the
  pins. Every `texture` line of the five parts' .ac files resolves to a
  pinned PNG.
- **New `aircraft.texture_collision` refusal for other airframes.** I
  fetched the texture lines of every part of the A320, B747, c172p, DHC6
  and p51d at their pinned commits. No basename comes from two
  directories, so none of them start to refuse.
- **Interior inside the hull.** The converter's bounding-box check is
  loose, so I also cast a vertical ray from every interior vertex
  against the Su-27.ac triangles. The pilot is fully covered by
  canopy.glass. 9 panel vertices (canopy rail, x 4.6-5.5 m) and 26
  seat vertices (rail height, x 5.83-5.86 m, 1-6 cm from hull
  vertices) have no hull face above them, which looks like the seam
  between the canopy and the sill. They are in the body part, with the
  aircraft's stencil, so pixels and labels still agree. Check at the
  pilot-eye frame.
- **Fixed: the label-box / preview mesh read the interior.**
  `core/capture/aircraft_mesh.py` builds the engine-less preview and
  `labels.mesh_tight_box_body_m` from config `parts[]`, keeping only
  the largest 2600 faces. The interior parts went in (without the
  seat's pitch) and pushed 89 hull faces out of that budget on the
  pinned J-11A. The tight box itself came out the same, but this path
  is not beauty, so interior parts are now skipped there (test:
  `test_the_preview_and_label_box_mesh_skips_the_interior_parts`).
- **Slot classes.** I checked them against the material_sources.json
  written from the real package. mat_Glass_Cockpit comes only from
  Su-27.ac's canopy. Every slot the rubber rule matches comes only
  from panel.ac, seat2.ac or fighter_default.ac. M_AircraftGlass is
  opaque (ue_aircraft_master_materials.py), so the glass canopy keeps
  beauty, mask and depth in agreement.
- **Lamps.** The mesh's span is y ±7.62 m, so the LightPack positions
  at ±7.5 m are inboard of the tip. Beacons flash on the strobe clock.
  Both are beauty-only bulbs and lights in FlightSimAircraftFX, and no
  C++ was changed.
- **Things this lane did not touch.** No engine symbols, no edits to
  RenderCommandlet, verify.py or beauty_look.py, no sun change, and no
  physics change: the FDM and the J11.json mass and loading rows are
  untouched.
- **Licence note for the owner.** `Models/Interior/pilot/Read-Me.txt`
  says the pilot figure was "extracted from the collection of drivers
  for X-Plane conducted by Bertrand AUGRAS" by Emmanuel Baranger. It
  ships inside the GPL-2.0 package that decisions 3 and 20 cleared, and
  it is pinned. Its original author is not the package's, so the
  attribution line for exports should name him too.
- **Tests.** test_platform's utf-8 failure is in tests/test_gate_v_visual.py
  and tests/test_swarm_viz.py, which are not in this branch's diff.
  Commit 43795f40 on the integration branch fixes it.

## hero-lighting

Lane: dramatic, physically plausible light for every shot. Files:
`core/scene/hero_lighting.py`,
`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/{Private,Public}/FlightSimHeroLighting.{cpp,h}`,
`tests/test_hero_lighting.py`. Hooks: `experiments/visual_contact_sheet.py`
(a `lighting` field per shot plus `light_shot`), `webapp/runs.py` (two lines,
both on the beauty look only), `FlightSimRenderCommandlet.cpp` (4 lines),
`scripts/check_bridge_api.sh` (block `BEGIN hero lighting`) and
`core/messages/catalog.yaml` (`hero_lighting.intent`, `.unreachable`,
`.sidecar`).

### What it does

1. **A lighting director per shot.** Each contact-sheet shot names a look
   (`INTENTS`): where the sun should sit relative to the camera, as an
   azimuth off the lens axis and an elevation. The look is realised only
   through the levers a real flight has: the time of day, the date and the
   heading. `solve()` bisects `core.environment.sun.solar_position` for the
   UTC instant at which the apparent sun crosses the wanted elevation. It
   then picks the heading that puts the sun at the wanted relative bearing,
   and re-resolves the sun on exactly the clock string the renderer will
   read. The date is the one the spec already had (the environment preset's,
   or the equinox), so the season is never changed. It is carried as an ISO
   prefix on the clock (`2026-07-15T13:52Z`), never as `weather_date`,
   which would switch on ERA5 winds and so change physics. The heading goes
   into the prompt as `heading NNN` and is recompiled, so the planners see
   it. There is no second sun and no moved light.
2. **The quality of the one sun and the one sky light**, beauty only:
   - the source angle at the true solar disc (0.5357 deg) plus a soft angle,
     unless the run stated `-sun-source-angle=` (the rain look's softening),
     which is kept;
   - VSM: directional LOD bias, page pool, and SMRT ray and sample counts;
   - world-space contact shadows at airframe scale;
   - the sky light with cloud AO, left in the commandlet's capture-once
     mode (skeptic fix: real-time capture never runs for a scene capture,
     so turning it on lit every shadow with nothing; docs/VALIDITY.md),
     and its lower hemisphere set to the ground's radiance from the
     `-hero-lighting=` sidecar (Lambertian: albedo x E_h / pi);
   - Lumen short-range AO and screen traces, and reflections with hardware
     ray-traced hit lighting (LightingMode 2) when `IsRayTracingEnabled()`,
     with a screen-trace and surface-cache fallback otherwise;
   - light-shaft occlusion, plus light-shaft bloom except under overcast;
   - volumetric-fog scattering and volumetric shadow from the sun;
   - the atmosphere's sun disc at physical luminance (scale 1), hidden
     under overcast;
   - the aureole (the world lane's Mie anisotropy) read back and recorded,
     but not set.
   Everything is recorded in render.json `hero_lighting` (asked and
   read-back cvars, the reflection route, the plan). `pixel_moving_effects`
   there is empty because lighting moves no geometry.
3. **Labels and measure.** The commandlet calls `Apply` only under
   `bVisual && bBeauty`. `ExcludeFromLabel` turns light shafts and contact
   shadows off on every label capture, and before `Apply` it does nothing,
   so measure label captures are byte-for-byte as before. The web app
   writes the sidecar and passes the token only when a beauty look exists,
   and measure has none.

### Solved values (2026-11-09, the regex compiler, in-process web app)

| shot | look | time_of_day | heading | sun el / az | rel. az | residual el / rel. az |
|---|---|---|---|---|---|---|
| a | golden_rim_backlight (35 deg, 6 deg, setting) | 2026-03-20T17:03Z | 229 | 5.98 / 263.98 | 34.98 | -0.02 / -0.02 |
| b | desert_cross_relief (90 deg, 16 deg, rising) | 2026-07-15T13:52Z | 345 | 15.98 / 74.77 | 89.77 | -0.02 / -0.24 |
| c | storm_soft_sheen (20 deg, 28 deg, rising) | 2026-06-21T15:13Z | 061 | 28.05 / 80.91 | 19.91 | +0.05 / -0.09 |
| d | cockpit_canopy_glint (150 deg, 35 deg, rising) | 2026-03-20T09:20Z | 347 | 35.04 / 136.74 | 149.74 | +0.04 / -0.26 |

Shot a was "flying east". It now flies 229 because a golden-hour backlight
in the evening needs the western sun ahead of the lens.

### Probes (every value below is UNCALIBRATED until its probe is run)

Run these on the render machine (p3-windows) with the contact sheet:
`experiments/visual_contact_sheet.py`, one tile per shot, read against the
V0 sheet. Record each result here and in ruflo under
`visual-overhaul/hero-lighting/probe-<date>`.

| probe | sets | how to read it |
|---|---|---|
| hl-director | `INTENTS` azimuths and elevations | the four tiles: rim on shot a's airframe edge without disc flare; relief shadows on shot b; sheen on shot c's canopy and wet ground; glints on shot d's coaming and canopy arch |
| hl-penumbra | `HeroLightingSunSoftAngleDeg` 0.5 | shot a, the fin's shadow on the fuselage at 1080p against a reference photograph's penumbra |
| hl-overcast | `HeroLightingOvercastAngleDeg` 2.0, `OVERCAST_ILLUMINANCE_FRACTION` 0.25 | shot c: is the sun disc visible through the storm deck; an incident reading under the deck from the `-calibration` quad |
| hl-vsm | LOD bias -1.5, 8192 pages, 16 rays, 12 samples | shot b: canyon-rim shadow-edge aliasing, against the page-pool overflow warning in the log |
| hl-contact | `HeroLightingContactShadowLengthCm` 150 | shot d (canopy frame, coaming) and shot a (pylons, intakes): no halo on the tiles |
| hl-lumen | max roughness 0.4, downsample 1, LightingMode 2 | shots a and d: canopy and airframe reflection noise and cost, ray tracing on against off |
| hl-shafts | occlusion darkness 0.4, bloom scale 0.12, threshold 6, max 50 | shot a into the low sun through the Matterhorn ridge: no bloom haze across the frame |
| hl-fog | grid pixel size 4, grid Z 128 | shot c: shaft banding in the rain fog |
| hl-skylight | cloud AO strength 1 | shot c, the airframe belly under the deck; shot b, the belly over red rock |
| hl-ground | `GROUND_ALBEDO_RGB` | the belly's luminance over each ground, against the tiles' mean linear colour under the camera (a `-linear` pass) |
| hl-labels | (a check, sets nothing) | label sha256 for mask, class and depth with and without `-hero-lighting=`; they must be identical |

### Open points

- The sun-shafts-sky-occlusion lane (`FlightSimSunShafts.cpp`, branch
  `worktree-wf_6c29a6d7-e69-8`, not merged here) also sets light shafts and
  volumetric fog. Hero lighting runs later in the commandlet, so its
  values win where both touch. At integration, keep one owner per cvar.
- Renderer cvars are process-wide, so label captures share VSM and Lumen
  quality. The claim that label pixels are unchanged rests on the label
  materials reading stencil, depth and the GBuffer; probe hl-labels checks
  it.

## supersample

Lane: cleaner beauty frames through supersampling. Files:
`ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimSupersample.{h,cpp}`,
`core/capture/supersample.py` (the Python mirror), `tests/test_supersample.py`,
three 1-2 line hooks in `FlightSimRenderCommandlet.cpp` (Configure before the
beauty target is made, Downsample right after the beauty read-back, Record
beside the beauty_look record), `experiments/visual_contact_sheet.py`
(`--supersample N`, default 2 on a beauty sheet), a `render.supersample`
refusal in `core/messages/catalog.yaml`, and a marked block in
`scripts/check_bridge_api.sh`.

### What it does

`-supersample=N` (N from 1 to 4, `-quality=beauty` only) makes the beauty
render target N times the output size on each axis. The frame read back from
it is reduced to the output size by an exact N x N box before the PNG is
written. The box works in linear light: each sRGB byte is decoded, the N^2
values are averaged, and the result is encoded to the nearest byte. The
beauty is tonemapped inside the engine (`SCS_FinalColorLDR` into an
`RTF_RGBA8_SRGB` target), and this commandlet has no linear-HDR beauty
readback, so the filter runs on the tonemapped frame. Every label capture
keeps its own `Width x Height` target from the same pose and field of view,
so the labels never see the larger frame. Without the flag the factor is 1
and none of the hooks does anything. Measure and pathtrace renders refuse the
flag by name. The flag is recorded in `render.json beauty_samples` with these
fields: `supersample`, `spatial` = N^2, `supersample_filter` = box,
`internal_width_px`/`internal_height_px`, the output size, the VRAM estimate
and its budget, and `supersample_pixel_moving` = false.

### Decision: box, not Lanczos-3 (measured)

The test draws a synthetic half-plane edge. Each beauty sample is
point-sampled at the internal pixel centres, and the label mask is
point-sampled at the output pixel centres. The test then measures how far
from the edge the reduced frame differs from the mask by more than one 8-bit
step (reach), and where the edge reads back (position). Frame 96 x 64, edge
offset 0.3 px, three angles:

| N | box reach px | box position err px | box overshoot | Lanczos-3 reach px | Lanczos-3 overshoot |
|---|---|---|---|---|---|
| 2 | 0.20-0.34 | <= 0.20 | 0 | 2.20-2.37 | 8-10 % |
| 3 | 0.20-0.44 | <= 0.10 | 0 | 2.20-2.43 | 6-8 % |
| 4 | 0.20-0.50 | <= 0.05 | 0 | 2.20-2.40 | 5-8 % |

The box changes only the output pixels the edge crosses, and it stays well
inside the verifier's `MASK_TOL_PX` (1.0) and `LOOK_ALIGNMENT_TOL_PX`. The
Lanczos-3 changes pixels about 2.4 px away and rings, so it would be a
pixel-moving effect. The box is therefore not listed in
`pixel_moving_effects`. The test also checks that a box shifted by one
internal pixel is caught.

### C++ and Python, number for number

`tests/test_supersample.py` takes the `FLIGHTSIM-SUPERSAMPLE-PURE` block out
of the .cpp, compiles it with the machine's C++ compiler (`-Wall -Werror`)
and compares its output with `core/capture/supersample.py`. The comparison
covers the decode and threshold tables, the encoder, the box (byte for byte,
N 1-4, random data and every byte value), the VRAM estimate and the verdicts.

### Memory (UNCALIBRATED)

The estimate is internal pixels x (112 B for the render-resolution targets +
24 B x (TSR history 200 %/100)^2). The budget is 7168 MiB of the render box's
16 GiB; the Google tiles, Nanite, VSM and Lumen's scene cache keep the rest.
`-supersample-vram-budget-mib=M` overrides the budget. With these numbers,
4K internal (3840x2160: N 2 at 1920x1080, or N 4 at 960x540) is estimated at
1645 MiB. N 3 at 1920x1080 (5760x3240) is 3702 MiB. 8K internal (N 2 at
3840x2160, or N 4 at 1920x1080) is 6581 MiB; all of these pass. N 3 or N 4
at 3840x2160 is over the budget and is refused as `render.supersample`. The internal side must also
fit `GMaxTextureDimensions` (16384 is assumed when the RHI reports nothing).

### Engine symbols

The "supersample lane" block of `scripts/check_bridge_api.sh` checks these
symbols: `GMaxTextureDimensions`, `UTextureRenderTarget2D::InitAutoFormat`,
`RTF_RGBA8_SRGB`, `SCS_FinalColorLDR`, `FRenderTarget::ReadPixels(TArray<FColor>&)`,
`FJsonObject::TryGetObjectField(FStringView, const TSharedPtr<FJsonObject>*&)`,
`FParse::Value(..., int32&)` and `TArray::SetNumUninitialized`. Each was
grepped in the 5.7.4 headers. The C++ is UNCOMPILED (no engine build was
run).

### Open items

* The storm exposure meter and the TSR sub-frames run at the internal
  size. The meter reads luma statistics, which do not depend on the size.
  Wall time grows by about N^2. The Google tiles are NOT selected at the
  internal size: `GoogleTiles.WaitForView` is given the output `Width,
  Height`, so the tiles' screen-space error is measured per output pixel
  and the beauty and every label capture of a step draw the same tile set
  (skeptic correction; pinned by a test).
* The linear EXR (`-linear`) and accumulation (`-accumulate`) captures stay
  at the output size and are NOT supersampled.
* Calibrate the bytes per pixel and the budget on the render box. Use stat
  GPU or `r.DumpRenderTargetPoolMemory` at N 1 and N 2 on shot (a); the
  slope is the per-pixel cost.

## reference-frames

Lane: a path-traced REFERENCE for the look, and the tools that match the
realtime beauty to it. Files: `core/scene/look_match.py` (the pure part:
metrics, suggestions, refusals), `experiments/look_match.py` (the CLI),
`tests/test_look_match.py`, a 4-line hook in the pathtrace branch of
`FlightSimRenderCommandlet.cpp`, one plugin line in `ue/FlightSim.uproject`,
the "reference-frames lane" block in `scripts/check_bridge_api.sh`, three
`look_match.*` names in `core/messages/catalog.yaml`, and runbook step 13.
Session 2026-11-09, on the Mac that cannot build or render. **Nothing below
has been rendered or measured**; every engine symbol was read in the 5.7.4
source and is grepped by the check script's block.

### Decisions

1. **Reference atmosphere and clouds on the pathtrace route.** Without them
   the path tracer has no volumetric sky: `PreparePathTracingCloudMaterial`
   skips the cloud callable unless `UsesReferenceAtmosphere`, so the hero
   still drew the volumetric clouds and the aerial perspective NOT AT ALL
   (refuter memory `visual-overhaul/swarm/refuter1-consts-render-path-refatmo`).
   The branch now sets `bOverride_PathTracingEnableReferenceAtmosphere` and
   `PathTracingEnableReferenceAtmosphere = 1` on the BEAUTY capture's post
   process (the cvar `r.PathTracing.EnableReferenceAtmosphere` defaults to -1,
   which inherits this; PathTracing.cpp `UsesReferenceAtmosphere`), and sets
   `r.PathTracing.EnableReferenceClouds 1` explicitly (its default, stated and
   read back). Under the reference atmosphere the sky light's skydome is
   dropped from the path tracer's light list (`bEnableSkydome =
   !bUseAtmosphere`), so the sky is not counted twice. The raster sky passes
   are skipped for that family only (DeferredShadingRenderer.cpp
   `bPathTracedAtmosphere`). Label captures are separate captures with no
   PathTracing show flag, so they inherit none of it.
2. **Denoiser: NNEDenoiser, made explicit; OpenImageDenoise left off.** Read
   at load: `NNEDenoiser.uplugin` is `"EnabledByDefault": true` and the
   project sets no `bAllowEnginePluginsEnabledByDefault=false`, so it was
   ALREADY loaded in every FlightSim process, measure included (the
   render-path note "neither is enabled" was wrong for this one). Its module
   registers a scene view extension only when `IsRayTracingAllowed()` (it
   is not under measure: `r.RayTracing` stays out of DefaultEngine.ini), and
   the extension activates only on a view family with the PathTracing show
   flag (`BeginRenderViewFamily` timeout counter), and registers a denoiser
   that only `RenderPathTracing` calls, on the last sample. So listing it in
   the uproject changes no module set and no measure pixel; it pins the
   hero denoiser against an engine default change. `OpenImageDenoise` is
   `EnabledByDefault: false` and Win64-only: enabling it would add a module
   load to every process for no gain over NNEDenoiser (the same OIDN 2.3
   network), so it stays off. `r.PathTracing.Denoiser.Name` defaults to
   `NNEDenoiser` and is recorded, as before.
3. **Denoiser quality: `NNEDenoiser.Asset 3`** (OIDN 2.3 High Quality, colour
   + albedo + normal). The project-settings default is Balanced+Alpha. Set
   with `SetBeautyCvar`, so it is in `cvars_asked`/`cvars_read_back`.
4. **Samples: the default stays 256; references use `-Spp 1024`.**
   `RenderPathTraceSppDefault` is the render-path lane's constant, and each
   sample is one `CaptureScene` (a pathtrace clip pays it per frame), so it
   is left alone; the runbook asks for `-Spp 1024` on reference stills,
   because the volumetric clouds converge more slowly than surfaces.
   Denoised 1024 is the starting point; the convergence probe below sets it.
5. **Labels match pixels.** Nothing here moves geometry. The reference
   clouds may hide part of the aircraft in the path-traced frame, which the
   mask (clouds absent, `SetCloud(false)`) still shows: the existing
   visual-only cloud rule, unchanged.
6. **look_match regions** come from the REALTIME run's label bundle (labels
   are rasterised identically under both qualities): sky = depth +inf,
   ground = finite depth, aircraft = the ID mask's `class: aircraft` int_ids
   (default 1). Two depth files that disagree (median relative > 1%, or > 1%
   of pixels switching sky/ground) refuse `look_match.not_same_shot`.
7. **Metrics** are on the display-referred PNGs (sRGB decoded to linear):
   luminance in stops (median), CIEDE2000 (Sharma 2005; tested against its
   reference pairs) of the region means and per pixel, L* interquartile
   contrast, shadow depth log2(median / p05), and the far-ground (depth >=
   p75) L* spread for haze. Because the tonemapper sits between, a PNG stop
   is not a scene stop: every step is damped and clamped, and the runbook
   iterates until `converged`.
8. **Which knob each metric moves, in the files their loaders already read:**
   lit (ground + aircraft) luminance -> `beauty_look.json exposure.ev100`;
   colour cast -> `color_grade.ColorGain` (luminance-preserving);
   chroma -> `ColorSaturation`; mid-tone contrast -> `ColorContrast`; shadow
   depth -> `-sky-light-scale=` (the fill; the flag has no sidecar);
   far-ground contrast -> `world_beauty_overrides.json
   atmosphere.<preset>.aerial_perspective_scale`; sky L* spread (only when
   the reference sky has cloud structure) -> `constants.cloud_extinction_scale`.
   Sky brightness left over after the exposure is REPORTED, not corrected:
   no look constant owns the atmosphere's own scattering.
9. **Applying the overrides** (runbook 13b). The world file goes in through
   `FLIGHTSIM_WORLD_BEAUTY_OVERRIDES`, so the contact sheet picks it up.
   The web app writes its own `-beauty-look=` sidecar on every run, so the
   matched `beauty_look.json` and the `-sky-light-scale=` flag are applied
   by re-running the commandlet command from the realtime run's
   `render.log` with those tokens REPLACED. The engine reads a flag's
   first occurrence, so appending a second one does nothing. A web-app
   input for both is left to the web-app lane.

### Uncalibrated constants (each: UNCALIBRATED, set by probe render on the render machine)

| Constant | Value | Probe that sets it |
|---|---|---|
| `NNEDenoiser.Asset` (commandlet, pathtrace) | 3 (High Quality) | shot (a) at 256 spp, Asset 2 vs 3: residual noise in the sky band against frame time |
| reference spp (runbook `-Spp`) | 1024 | shot (a) at 256, 1024, 4096 denoised: stop when the sky band's L* std changes < 0.5 |
| `look_match.EXPOSURE_GAIN` / `_TOLERANCE_STOPS` / `_STEP_MAX_STOPS` | 0.8 / 0.10 / 2.0 | iterations to converge on shot (a); lower the gain if it overshoots |
| `GAIN_DAMP`, `GAIN_STEP_CLAMP`, `COLOUR_TOLERANCE_DE00` | 0.7, (0.85, 1.15), 2.0 | shot (a) golden hour: the cast after two passes |
| `SATURATION_*`, `CONTRAST_*` | 0.05 / 0.7 / (0.8, 1.25); 0.05 / 0.6 / (0.8, 1.25) | shot (b) desert low pass |
| `SHADOW_TOLERANCE_STOPS`, `SKY_LIGHT_GAIN`, `SKY_LIGHT_STEP_CLAMP` | 0.15, 0.6, (0.5, 2.0) | shot (b), the aircraft's shadow side |
| `HAZE_*`, `FAR_GROUND_PERCENTILE` | 0.08 / 0.7 / (0.7, 1.4); 75 | shot (c) forest in rain, far ridges |
| `CLOUD_SKY_MIN_SPREAD_L`, `CLOUD_*` | 3.0; 0.08 / 0.6 / (0.5, 2.0) | shot (c) storm deck |
| `MIN_REGION_PIXELS` | 64 | none: below it a region is skipped |

### Open risks (not verifiable here)

- The path tracer and the realtime path draw the SAME clouds only if the
  reference clouds trace the cloud material the world lane builds; their
  look may still differ by model (the raster clouds' multiple-scattering
  approximation). The cloud suggestion then tunes the raster clouds toward
  the traced ones, which is the point, but it is a heuristic on L* spread.
- Exposure: the beauty look is manual, so the accumulation does not reset
  (`IsExposureDifferentEnough`). A card that is auto-exposed would.
- The NNE denoiser runs on `NNERuntimeORTDml` (DirectML) by default; on a
  driver without it the denoiser logs "Could not create denoiser" and the
  still is raw. Read the log for `LogNNEDenoiser`.
- Google tiles streaming during the 1024 samples would reset the
  accumulation (render-path risk, unchanged).

### Render-machine commands

```powershell
.venv\Scripts\python -m experiments.visual_contact_sheet --quality beauty                  # -supersample=2 by default
.venv\Scripts\python -m experiments.visual_contact_sheet --quality beauty --supersample 1  # A/B against no supersampling
.venv\Scripts\python -m flightsim.verify runs\webapp\<beauty_id>
```

### Skeptic review (2026-11-09)

A second agent tried to break the lane in a detached worktree. What it
checked, and what it found:

* Engine symbols: every one in the marked block was grepped again in the
  installed 5.7.4 (`Build.version` 5.7.4). `GMaxTextureDimensions` is a
  `#define` for `GRHIGlobals.MaxTextureDimensions`, a `TRHIGlobal<int32>`
  with an implicit `operator int32`, so `int32 MaxSide = GMaxTextureDimensions;`
  compiles. `RHI` and `Json` are already dependencies in
  `FlightSimBridge.Build.cs`. `scripts/check_bridge_api.sh` passes all
  eight supersample lines.
* Labels: all nine `InitAutoFormat` calls other than the beauty's are
  `(Width, Height)` (label depth and id, land cover, passes, linear,
  accumulate, calibration), and the beauty `RenderTarget` is read back only
  by the storm meter (statistics) and the frame read-back (box-filtered
  before anything indexes it). No half-pixel offset: output pixel x is
  internal x*N .. x*N+N-1, whose footprint is exactly output [x, x+1).
  A new test pins every target size and the output-size tile selection.
* Measure path: without the flag Configure returns factor 1 and records
  nothing; `InitAutoFormat(Width * 1, Height * 1)` and a factor-1
  Downsample are the old behaviour. Pathtrace and measure refuse by name.
* No sun, light, physics or asset change; nothing to pin or licence.
* TSR memory: the engine itself drops the history to 1x when 2x the
  internal size would pass `GMaxTextureDimensions` or a 4 GB resource
  (`TemporalSuperResolution.cpp`, HistorySize), so at the largest sizes the
  estimate is conservative rather than low.
* Tests: 34 of 34 in `tests/test_supersample.py`; the only failure in the
  shared set is the pre-existing utf-8 check on `tests/test_gate_v_visual.py`
  and `tests/test_swarm_viz.py`.

.\scripts\render_visual_sheet.ps1 -Step ref_pt -PathTrace -Spp 1024 -Shots a,b,c
.\scripts\render_visual_sheet.ps1 -Step ref_rt -Shots a,b,c
.\.venv\Scripts\python.exe experiments\look_match.py --steps ref_pt ref_rt --shot a
#   then RENDER_RUNBOOK.md step 13b: apply, re-render, match again until "converged"
```

### reference-frames: skeptic review (2026-11-09)

Read `git diff claude/vibrant-gauss-olema4...worktree-wf_d78a46c2-467-4` and tried to break it.

- Engine symbols: the 12 rows of the lane's block in scripts/check_bridge_api.sh were grepped by hand in the
  installed 5.7.4 source (Build.version 5.7.4). `bOverride_PathTracingEnableReferenceAtmosphere` is in
  Scene.h:1391. `NNEDenoiser.Asset` is read on the game thread on every update
  (NNEDenoiserViewExtension.cpp:387 compares the asset name), so a code-priority set takes effect.
- Labels: the hook writes only `Capture->PostProcessSettings` of the beauty capture plus two cvars that only
  the path tracer reads. The copies of that post-process (linear, accumulate, calibration) are refused under
  pathtrace before this point. Under the reference atmosphere the path tracer drops the sky light from its
  light list (PathTracing.cpp:3022). That is not a second sun, and nothing reaches physics.
- Measure: NNEDenoiser is EnabledByDefault and supports Win64/Linux/Mac, so listing it in the uproject loads
  nothing new.
- Fixed: a truncated or mis-sized REFERENCE `_depth.f32` used to raise a bare ValueError (a traceback from the
  CLI). It now refuses as `look_match.inputs`, with a test.
- Not this lane: the utf-8 failure in tests/test_platform.py (tests/test_gate_v_visual.py,
  tests/test_swarm_viz.py) is fixed on claude/vibrant-gauss-olema4 by 43795f40. It clears when the lane merges.

## render-machine

Windows laptop (p3-windows), 2026-11-09. Intel(R) Graphics, driver 32.0.101.7076,
D3D11, 16 GB. UE 5.7.4 CL 51494982. Base 355dae64; head ef361bd6 (the job named
43795f40 first; it also built clean and its step 6 matched; superseded).

- Steps 1-2: branch fetched; check_bridge_api.sh all ok, CesiumRuntime included.
- Step 3, base 355dae64: build_ue OK (54 s). Gate 6 measure into runs/gate6_base: PASS,
  the four measured clauses and the substitute side-by-side; the five look clauses NOT RUN
  (no --look). Base sheet (beauty) and base_measure rendered with HEAD's borrowed
  visual_contact_sheet.py and gate6_visual.py; tree restored clean. Shots a, b, d are
  byte-identical between beauty and measure at the base; only c differs.
- Step 4, head ef361bd6: build_ue OK, 0 errors, 1 warning (C4996
  ULandscapeSubsystem::BuildNanite deprecated, FlightSimLandscapeImporter.cpp:381). No
  compile fixes were needed.
- Step 5: ue_create_materials.py created M_AircraftCondensation and M_FlightSimScatter and
  rebuilt 8 aircraft masters, but kept MPC_FlightSimWorld, M_FlightSimTilesBeauty and
  M_FlightSimCloudLayers as built at 43795f40. FINDING: those have no generation bump,
  so the tiles de-light and the two new MPC scalars (DelightAmount, DelightBlueGate) do
  not arrive on a machine that built the earlier head. FINDING:
  FLIGHTSIM_REBUILD_MATERIALS=MPC_FlightSimWorld fails ("could not create", the asset is
  referenced, delete_asset refuses unattended). Worked round by moving the four .uasset
  files to runs/visual/content_backup_43795f40 with no editor open; the script then
  created all four. ue_fix_aircraft_materials.py: 0 LOOK-PROBLEM lines, 7 look manifests.
- Step 6, measure UNCHANGED: Gate 6 measure at head prints the same clauses and numbers as
  runs/gate6_base (PASS); Gate 10-R --against runs/gate6_base/full runs/gate6/full:
  BIT-IDENTICAL, 110 frames; runs/gate6/full/render.json has no aircraft_look,
  beauty_look, render_settings.beauty_path or look_applied.world_beauty. Note: without
  --look, gate6_visual.py grades look-clause renders it finds in --out; runs/gate6 held
  6 October ones, which FAILed three clauses on the 43795f40 pass; moved to
  runs/gate6_stale_20261006 before the ef361bd6 pass.
- Gate 6 beauty at head: FAIL (reported, not a gate). exposure does not breathe: sky band
  12.51/255 over the roll sweep (threshold 8; it was 5.87 at 43795f40); exposure metric
  discriminates: manual 12.38/255 (must stay under 8). Edge aliasing 0.1831, change vs
  measure -0.0291. beauty_path.temporal_aa_show_flag true, r.AntiAliasingMethod 4,
  scalability 4. Tiles declined (decision 18, synthetic raster).
- Step 7: FINDING: every shot first refused aircraft.package_pin: this laptop's global
  git core.autocrlf=true checked assets/aircraft_src/J11 out with CRLF, so 13 pinned files
  had other bytes. Re-checked out with core.autocrlf=false in that checkout only: 29 pins
  OK. importer.fetch_source should set it. The four-shot render was twice reaped by the
  harness for low memory while idle; rendered one shot per call in the foreground.
  beauty_look exposure on every shot: "no: the sidecar states no EV100 (the -sky= plan,
  or a sun not in lux); the exposure stands". fov unchanged 54.432. Tiles route
  UFunction SetMaterial, generate_smooth_normals true. cloud_occludes_aircraft false.
- Steps 8-9: compare sheet and a 15 s chase clip (4.7 MB, 9 min 46 s).
- Step 10, flightsim.verify on shot a beauty (runs/webapp/6b02ece7a099): exit 1, 36 PASS,
  1 FAIL, 33 NOT RUN. look_record PASS. look_label_alignment FAIL:
  look.beauty_not_label_aligned (motion_blur 12.8 px, uncalibrated), as expected.
- Step 11, look_label_check: NOT ALIGNED (exit 1). Beauty offset 0.85 px (tol 2), edge
  distance median 1.00 p90 6.00 px; measure floor 0.17 px; mask IoU 1.000; control
  recovered 3.00 of 3 px.
- Step 12, gate_v_visual.py --step head --skip-render: a horizon_fill FAIL, exposure PASS,
  specular PASS; b specular FAIL; c exposure FAIL (luma mean 3.6, 52.7 % crushed),
  specular FAIL; d horizon_fill FAIL, specular FAIL. aerial_perspective and texel_detail
  NOT RUN on every shot: "0 ground pixels with depth". Compare JSON in runs/visual/final.
- Step 13, path trace: refused by name, render.pathtrace: the RHI (D3D11) reports no ray
  tracing on this GPU or driver. No hero still. This laptop cannot make it.
- Step 14 not run, as instructed. Ruflo memory not written: no ruflo on this machine.

## no-lumen-fallback

Round 2, no-lumen-and-machine lane (Mac, uncompiled), 2026-11-09. From the render-machine
renders at ef361bd6: render.json render_settings.rhi D3D11, shader_platform PCD3D_SM5, so
DoesPlatformSupportLumenGI is false (SM5 only with r.Lumen.Supported.SM5) and
DoesPlatformSupportVirtualShadowMaps is DoesPlatformSupportNanite. Lumen GI and reflections,
VSM and Nanite did not run although the cvars read back 1: shot b's shadow side crushed,
shot c luma mean 3.6 (52.7 % crushed).

- New FlightSimBeautyFallback.cpp. ApplyScene runs on beauty only, not pathtrace. It runs
  after the scene build and BEFORE the world lane, whose lightning pulse keeps the sky light's
  intensity as its base, so the fill survives the storm frames. ApplyCapture sets the beauty
  capture's per-view post-process. Recorded in render.json render_settings.beauty_fallback:
  machine (rhi, feature level, shader platform, the engine's support answers), path ("lumen" or
  "fallback"), and every cvar before, asked and read back. `-beauty-fallback=auto|force|off`;
  force lets the DX12 host probe this path. An unknown value refuses as
  render.beauty_fallback_mode.
- The look without Lumen: SSGI (DynamicGlobalIlluminationMethod ScreenSpace on the capture;
  r.SSGI.Quality 4) and SSR (ReflectionMethod ScreenSpace, quality 100; r.SSR.Quality 4).
  Distance-field AO (r.DistanceFieldAO 1, r.AOQuality 2) when the platform and project support
  distance fields. Sky light x1.6 with MinOcclusion 0.2, marked dirty before the commandlet's
  capture-once. Without VSM: CSM with r.Shadow.CSM.MaxCascades 10, r.Shadow.MaxCSMResolution
  4096, r.Shadow.MaxResolution 4096, and the sun at 8 cascades with distribution exponent 4.
  Contact shadows stay the hero-lighting lane's.
- Probes, all UNCALIBRATED. nl-fill: shot b shadow-side luma p10 and shot c luma mean,
  against the same shots on the DX12 host with Lumen; the fill is right when they meet.
  nl-ssgi: shot b at SSGI 2 and 4. nl-dfao: shot b with and without DFAO. nl-csm: shot a,
  the aircraft's self-shadow and the ridge shadow edge.
- Limits, not done here: SSGI reads the previous capture, so the first capture of a run has
  none (stills accumulate 8 captures). The fill does not fix exposure. Shot c's darkness is
  also the storm meter's and the exposure owners'. The ghosted aircraft (motion blur and TSR
  history) belongs to other lanes.
- Machine friction fixed: MPC_FlightSimWorld, M_FlightSimTilesBeauty, M_FlightSimCloudLayers
  and M_FlightSimScatter now carry WORLD_GENERATIONS stamps (FlightSimWorldGeneration). A stale
  or FLIGHTSIM_REBUILD_MATERIALS-named one is UPDATED IN PLACE, never deleted. A material has
  its graph cleared and built again on the same asset. The collection's parameters are merged,
  and an existing one keeps its Id. The "could not create" crash is gone, and moving .uasset
  files by hand is no longer needed. importer.fetch_source runs every git call with
  `-c core.autocrlf=false -c core.eol=lf`, stores autocrlf=false in the source repo, and
  re-checks out an earlier CRLF checkout from the index. Gate 6 without --look no longer grades
  an earlier run's look renders: they are named as gate6.stale_look_renders and left NOT RUN.
- Gate V "0 ground pixels with depth": the cause was the mask, not a missing depth. Windows'
  gate found the depth through shots.json's frame path. The label mask gives terrain int_id 2,
  and Gate V took only id 0 (the sky) as ground, so horizon_fill also FAILed on fill 0.0.
  Fixed: visual_contact_sheet.py copies `<shot>_depth.f32/.png`, writes `<shot>_horizon.json`
  from the frame sidecar and `<shot>_ids.json` (the ground ids from render.json objects), and
  removes an earlier sheet's side files first. gate_v_visual.py folds the ground ids into 0,
  read from `_ids.json` or the run's render.json. A head re-grade should now run
  aerial_perspective and texel_detail, and horizon_fill on a and d should be re-read.
