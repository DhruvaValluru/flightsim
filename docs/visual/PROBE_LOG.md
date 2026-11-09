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
