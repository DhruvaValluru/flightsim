# Visual fidelity plan: closing the gap to Microsoft Flight Simulator

Written 2026-09-30. Target look: **Microsoft Flight Simulator 2024**, the
current shipping title (no "Flight Simulator 2026" exists as of this
writing; if one ships, the gap analysis below still holds, because the
same pipeline drives it).

This is a plan and a set of prompts, not a claim. Nothing here has been
rendered yet. Every phase ends in a measurement that
`experiments/gate6_visual.py` (or a sibling) reads back from the pixels,
the same way Gate 6 does. The project's rules still apply to every step:
named sources, sha256 on every fetched asset, license in the manifest, no
NC licenses, no placeholder airframes, visual-only work labeled visual-only,
and calibration done by probe render rather than theory (NEXT.md gotchas
6/7).

---

## 1. Where the renderer is today (audited from the code)

| Area | Current implementation | Where |
|---|---|---|
| Engine | UE 5.7 (written when the pin was 5.5), render via `UnrealEditor-Cmd` commandlet into a `USceneCaptureComponent2D`, `SCS_FinalColorLDR`, RGBA8 sRGB target | `FlightSimRenderCommandlet.cpp:782-808` |
| Resolution / FOV | 960 px wide by default, FOV 55° (visual) | `FlightSimRenderCommandlet.cpp:355, 797` |
| Engine rendering config | **None.** `DefaultEngine.ini` only sets the fixed 120 Hz tick. Lumen, Nanite, Virtual Shadow Maps, TSR, and physical light units are never set explicitly. | `ue/Config/DefaultEngine.ini` |
| Sun | One directional light, intensity **8.0** (an arbitrary value, not physical lux), rotation hard-coded per shot or passed in as `-sun-elev/-sun-azim`. Not derived from date, time, or location. | `FlightSimVisualScene.cpp:98-114`, `RenderCommandlet.cpp:509-519`, `webapp/runs.py:1044` |
| Shadows | Dynamic CSM, 6 cascades, 20 km. VSM isn't used because the terrain isn't Nanite. | `FlightSimVisualScene.cpp:111-113`, `VALIDITY.md` Phase 6 |
| Sky | SkyAtmosphere with Earth radius, multiscattering 1.0, planet-top transform. Rayleigh and Mie are at defaults, not driven by weather. | `FlightSimVisualScene.cpp:116-135` |
| Haze | Exponential height fog, density per scene, max opacity 0.92, start at 1.5 km | `FlightSimVisualScene.cpp:137-149` |
| Ambient | SkyLight with real-time capture, intensity 1 | `FlightSimVisualScene.cpp:151-159` |
| Exposure | Manual, `AutoExposureBias` 11.0 (9.5 for noon, 9.6 for storm), hand-calibrated | `FlightSimVisualScene.cpp:574-584`, `showcase_matrix.py:109` |
| Terrain geometry | `UProceduralMeshComponent`, a single section built from a GLO-30 (30 m) DEM decimated to at most **701 verts/side** (~60 m posting), about 40 km across. No LOD, no Nanite, no displacement, no distance fields. | `FlightSimVisualScene.cpp:44, 396-519` |
| Beyond the raster | A flat 4000 km² matte `Plane` 40 m under the raster minimum, so the horizon is empty | `FlightSimVisualScene.cpp:274-300` |
| Terrain surface | Either (a) **one** 10 m Sentinel-2 cloudless **2016** mosaic texture, capped at 8192 px, into `M_TerrainImagery` with base colour and roughness 0.92 only (no normals, no detail, no specular variation), or (b) 4 hard-coded vertex colours by slope and altitude | `imagery.py`, `ue_create_materials.py`, `FlightSimVisualScene.cpp:62-89` |
| Vegetation / buildings / water / roads / airports | **None** | — |
| Clouds / precipitation | **None.** Planned as "task 12" (volumetric clouds + Niagara, visual-only) | `NEXT.md:170` |
| Aircraft | FlightGear `.ac` models (GPL), imported via Interchange, Nanite off, animated control surfaces. Materials come from the conversion, not authored PBR. | `assets/aircraft_config/*.json`, `scripts/ue_import_aircraft.py` |
| Post | Engine defaults. No deliberate tonemap, bloom, lens, or motion-blur choices. No MRQ (recorded deviation). | `VALIDITY.md` Phase 6 |

**Bottom line:** the atmosphere setup is already correct in principle (the
§6.6 SkyAtmosphere work is the same technique MSFS uses). The gap is almost
entirely in these areas: **(1) terrain resolution and horizon, (2) surface
material detail, (3) everything that sits on the ground, (4) clouds,
(5) physically based light and exposure, (6) output quality (resolution,
AA, capture path)**.

---

## 2. How MSFS gets its look, and what each piece maps to here

| MSFS 2024 feature | How MSFS does it | Our equivalent | Gap |
|---|---|---|---|
| Ground texture | Bing aerial imagery, ~0.3 to 1 m/px, streamed worldwide | S2 cloudless 10 m, 2016, one 8k texture | **Huge** |
| Terrain mesh | Global DEM plus local high-res data, continuous quadtree LOD to the horizon, curvature | 60 m posting, 40 km island, flat plane beyond | **Huge** |
| Horizon | Real terrain to 100+ km through aerial perspective | Empty fog | **Huge** |
| Surface detail up close | Tiling detail textures and normals blended under the imagery by land class | None | Large |
| Vegetation | Procedural trees placed from land-class ML over imagery, millions of instances | None | **Huge** |
| Buildings | Photogrammetry cities (Bing 3D) plus autogen from OSM footprints | None | Large |
| Water | Masked water with a wave shader, reflections, shoreline | None | Large |
| Airports | Hand-built and procedural from real data | None | Medium (not needed for chase-cam clips) |
| Sky / atmosphere | Physically based scattering with real sun/moon/stars ephemeris | SkyAtmosphere ✔, but no ephemeris | Small |
| Clouds | Volumetric raymarched clouds from live weather (Meteoblue) | None | **Huge** |
| Lighting units | Physical (sun ~100 klux, EV-based exposure, eye adaptation) | Arbitrary intensity 8 plus a hand bias | Medium |
| Seasons / snow | Seasonal imagery tint, snow cover from weather | 2016 composite, whatever snow it has | Medium |
| AA / upscaling | TAA/DLSS/FSR at 1440p to 4K | Scene capture at 960 px, default AA | Large for perceived quality |
| Aircraft | High-poly PBR models, authored materials, glass, decals | FlightGear meshes, converted materials | Medium to large |

MSFS streams petabytes from Azure and holds licenses we can't get. We
don't try to match it globally. **We match it at the curated locations
(Matterhorn, Yosemite, and anything baked on demand) using open,
redistributable data at higher resolution than Bing where national
agencies publish it (Switzerland, US).**

---

## 3. Where the changes come from (sources and licenses)

Everything below is either free and redistributable, or explicitly marked
as an **owner decision**. Every fetch goes through the same pipeline as
`glo30.py` and `imagery.py`: pinned source URL, sha256 per tile, license
and attribution in the sidecar and in every manifest, and verification
against the source before rendering.

### 3.1 Elevation
| Source | Resolution | Coverage | License | Use |
|---|---|---|---|---|
| Copernicus GLO-30 (have) | 30 m | Global | Copernicus DEM licence (free) | Default, mid-field |
| **Copernicus GLO-90** | 90 m | Global | Same | **Far-field ring to 150 to 300 km (horizon)** |
| **swisstopo swissALTI3D** | 0.5 / 2 m | Switzerland | swisstopo OGD, free with attribution | Matterhorn near-field |
| **USGS 3DEP** (1 m lidar / 1/3″) | 1 to 10 m | USA | Public domain | Yosemite near-field |
| IGN RGE ALTI, Kartverket DTM, etc. | 1 to 5 m | FR, NO… | Etalab / CC-BY 4.0 | On-demand bakes where available |

### 3.2 Surface imagery
| Source | Resolution | License | Use |
|---|---|---|---|
| **swisstopo SWISSIMAGE** | 10 cm (resample to 0.5 m) | swisstopo OGD, free with attribution | Matterhorn |
| **USDA NAIP** | 0.6 m | Public domain | Yosemite / any US scene |
| **Sentinel-2 L2A** (Copernicus Data Space / AWS Earth Search COGs) | 10 m, **date-matched** | Copernicus free licence | Global fallback, **seasons and snow matched to `weather_date`** |
| S2 cloudless 2016 (have) | 10 m | CC-BY-SA 4.0 | Last-resort fallback |
| ~~Bing / Google / Esri / Mapbox~~ | — | Proprietary ToS | **Refused** (consistent with the project's WRF/trueSKY refusals) |

### 3.3 Land cover, vegetation, and buildings
| Source | License | Drives |
|---|---|---|
| **ESA WorldCover 10 m** (2021) | CC-BY 4.0 | Material layer masks, tree/grass/rock/snow/water/urban classes |
| **Meta/WRI High-Res Canopy Height 1 m** or **ETH Global Canopy Height 10 m** | CC-BY 4.0 | Tree density and **real tree heights** |
| **OpenStreetMap** (Geofabrik extracts) | ODbL | Roads, water polygons, building footprints, land use, airports |
| **Overture Maps buildings** / MS Global ML Footprints / Google Open Buildings | ODbL / CDLA / CC-BY 4.0 | Footprints and heights where OSM is thin |
| **swisstopo swissBUILDINGS3D** | swisstopo OGD | Real 3D buildings (Zermatt) |
| **JRC Global Surface Water** | Free with attribution (verify) | Water mask |
| **OurAirports** | Public domain | Runway positions and headings |
| Google Photorealistic 3D Tiles / Cesium ion World Terrain + Bing | Commercial ToS (caching and offline use restricted) | **Owner decision 2026-11-10/11: approved, streamed through the Cesium ion token, including for the labelled dataset.** |

### 3.4 Material and model assets
| Source | License | Use |
|---|---|---|
| **Poly Haven**, **ambientCG** | CC0 | Tiling PBR detail sets (rock, scree, grass, forest floor, snow, asphalt), HDRIs for aircraft look-dev |
| Quixel Megascans via Fab | Fab license (verify current terms, UE-only) | Optional upgrade; not required |
| Trees: Poly Haven / ambientCG CC0 trees, or UE PCG procedural trees | CC0 / engine | Nanite foliage |
| Aircraft: higher-detail FlightGear variants (GPL) or bought models with a redistributable license | Per model | Only with a verified license file (the §3.3 rule still holds) |

### 3.5 Weather and sun
| Source | License | Drives |
|---|---|---|
| Open-Meteo archive (have) / ERA5 | CC-BY 4.0 | `cloud_cover_low/mid/high`, cloud base, visibility, precipitation, snow depth into clouds, fog, rain, snow |
| **NREL SPA** (Reda & Andreas 2004) via `pvlib` (BSD) | Open | Sun (and moon) elevation and azimuth from lat/lon/date/time. The commandlet already accepts `-sun-elev/-sun-azim`. |

---

## 4. The phased plan

Each phase lists **what changes, where, how, and how it's measured**. Order
matters: V0 and V1 change how every later probe looks, so all
calibration after them must be redone against the new baseline. Don't
calibrate materials under the old exposure.

### V0: Render foundation (engine config and output quality)
**Where:** `ue/Config/DefaultEngine.ini`, `FlightSimRenderCommandlet.cpp`
(capture setup, ~l.780-810), `FlightSimInteractiveMode.cpp`.
**How:**
1. Add an explicit `[/Script/Engine.RendererSettings]` block:
   `r.DynamicGlobalIlluminationMethod=1` (Lumen), `r.ReflectionMethod=1`,
   `r.Shadow.Virtual.Enable=1`, `r.Nanite.ProjectEnabled=True`,
   `r.AntiAliasingMethod=4` (TSR), `r.GenerateMeshDistanceFields=True`,
   `r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange=True`
   (so exposure is in EV100), `r.SkyAtmosphere.*` LUT quality up,
   `r.VolumetricCloud` enabled.
2. Default output 1920×1080 (keep `-width/-height` overrides). Add
   `-quality=beauty|measure`: *measure* keeps today's deterministic
   settings for the gates, *beauty* enables everything above.
3. TSR and Lumen need history. Render N warm-up captures per cut, not just
   the two discarded today, and keep `bAlwaysPersistRenderingState`.
   Verify Lumen actually runs inside the scene capture on 5.5 by
   A/B probe; if not, fall back to rendering the game viewport with
   `-RenderOffScreen` and grabbing the backbuffer (interactive mode
   already owns a viewport).
4. Record every cvar in `render.json` (the manifest already records
   exposure; extend it).
**Measure:** Gate 6's four clauses still pass under `measure` *and*
`beauty`. New clause: edge-aliasing metric (high-frequency energy along the
aircraft silhouette) drops against today's baseline.

### V1: Physically based sun, sky, and exposure
**Where:** `FlightSimVisualScene.cpp` (sun, sky light, exposure),
`webapp/runs.py` (`STORM_LOOK`, sun plumbing), `core/scenario/spec.py`
(new `environment.time_of_day`), new `core/environment/sun.py`,
`experiments/showcase_matrix.py:109`.
**How:**
1. Sun intensity in lux: **~120,000 lux** directional, SkyLight at
   physical defaults, and manual exposure recalibrated to **EV100 ≈ 14 to 15**
   in sun (replacing bias 11 / 9.5 / 9.6). One constant per look,
   probe-calibrated, recorded.
2. `core/environment/sun.py`: NREL SPA through `pvlib`, turning
   (lat, lon, weather_date, time_of_day, UTC offset) into elevation/azimuth,
   passed on the existing `-sun-elev/-sun-azim` flags. Spec field with
   provenance (stated / derived / default). The deterministic NL parser
   learns "at dawn", "at 17:40", "golden hour".
3. Twilight and night: moon from the same ephemeris (second directional
   light, `AtmosphereSunLightIndex=1`), star field on a sky sphere,
   exposure presets per sun elevation band.
4. Aerosols: drive SkyAtmosphere Mie scattering and absorption plus fog
   density from Open-Meteo visibility, instead of a hand-picked fog
   density. Keep manual exposure for measured clips (the Gate 6 no-breathing
   clause). Enable **Local Exposure** (5.1+) for shadowed valleys under
   bright snow.
**Measure:** (a) shadow direction on a rendered frame matches SPA azimuth
within 2° (project a vertical pole's shadow); (b) sky luminance ratio
zenith-to-horizon inside a documented band; (c) Gate 6 exposure clause
still ≤ 8/255.

### V2: Terrain geometry, from a 40 km island to the horizon
**Where:** `FlightSimVisualScene.cpp` (`BuildGeoreferencedTerrain`,
backstop plane), `core/terrain/glo30.py`, new `core/terrain/lidar.py`,
`core/terrain/heightfield.py`, `scripts/bake_terrain.py`.
**How:**
1. **Chunked Nanite static meshes** instead of one procedural section: split
   the raster into ~2 km tiles, build each as a `UStaticMesh` in the
   commandlet (editor build path, Nanite on, distance fields on), and cache
   them as assets keyed by the raster sha256 so the second render is
   instant. Full 30 m posting, no decimation (Nanite owns LOD). This
   unlocks **VSM** (retiring the recorded CSM deviation) and Lumen
   distance fields.
2. **Near-field high-res patch**: swissALTI3D 2 m / 3DEP 1 m over ~8×8 km
   around the flight path, blended at the seam into GLO-30 (feathered
   heights so there's no step). Physics keeps using the 30 m raster unless
   the spec opts in, and the parity rule (`ElevationAt` mirrors Python)
   still holds for whichever raster physics uses.
3. **Far-field ring**: GLO-90 from the raster edge out to 200 to 300 km,
   coarse Nanite tiles, placed through the same `ProjectedToEngine`
   transform so **earth curvature comes out for free** (at 200 km it's
   ~3 km of drop and visible). Delete the flat backstop plane.
4. Alternative considered: UE Landscape (the Z-scale export already exists
   in `core/terrain/landscape.py`). Rejected as default because Landscape
   creation is editor-API only, resamples non-conforming sizes, and gains
   nothing over Nanite for a static scene. Cesium for Unreal is the
   alternative if we ever want global streaming.
**Measure:** Gate 4 round-trip still exact; the landmark projection test
(`experiments/imagery_drape.py`) still lands the summit; new
**horizon clause**: in a level frame, the band just under the geometric
horizon has terrain-vs-sky contrast > 0 at 100+ km (today: none).

### V3: Terrain surface (imagery plus a layered material)
**Where:** `core/terrain/imagery.py` (new providers), new
`core/terrain/landcover.py`, `scripts/ue_create_materials.py`
(new `M_TerrainLayered`), `FlightSimVisualScene.cpp` material binding.
**How:**
1. **Imagery providers** behind the existing sidecar format: SWISSIMAGE
   (0.5 m), NAIP (0.6 m), Sentinel-2 L2A date-matched (10 m), S2 cloudless
   as fallback. Same verify-against-source and landmark checks.
2. **Break the 8192 cap**: per-tile textures matching the V2 mesh tiles (for
   example 4096² per 2 km tile = 0.5 m/texel), or Streaming Virtual Texture
   import. Keep texel-to-DEM alignment by construction.
3. **Imagery grading**: satellite imagery carries baked haze, a blue cast,
   and baked shadows. Apply a per-source, *recorded* grade (dehaze by
   dark-object subtraction, white balance, albedo scaled so grass ≈ 0.1
   and snow ≈ 0.8). Calibrate by probe render (gotcha 7).
4. **`M_TerrainLayered`**: imagery for macro colour, then detail layers
   (Poly Haven/ambientCG CC0: rock, scree, alpine grass, forest floor, snow,
   gravel) masked by **WorldCover class + slope + altitude**, with
   detail normals, triplanar projection on slopes > 45° (no stretched
   cliffs), distance-faded so detail shows only below ~2 km, and
   macro-variation noise to kill tiling. Snow layer driven by ERA5 snow
   depth for the date.
5. Keep the classified vertex-colour path for the synthesized control
   ridge, labeled approximated as today.
**Measure:** texel-density clause (≥ 1 texel per screen pixel at 300 m AGL
in the chase frame); **tiling clause** (2D autocorrelation of a
near-field crop has no secondary peak above threshold); A/B against
the S2-only drape at identical camera.

### V4: Vegetation
**Where:** new `core/terrain/vegetation.py` (bake), new
`FlightSimVegetation.cpp`, PCG graph asset, `ue_create_materials.py`.
**How:** bake a sidecar of tree instances from WorldCover tree class ×
canopy-height raster (1 m Meta/WRI or 10 m ETH), with seeded jitter from
the spec digest (reproducible). Spawn as **Nanite foliage** (UE 5.7
Nanite supports masked and WPO foliage) via HISM, cull by distance, with
impostor cards or RVT tree-colour darkening past ~5 km. 3 to 5 species per
biome (conifer, broadleaf, alpine shrub). Labeled **visual-only scenery**
in the manifest: no collision, no claim.
**Measure:** instance count and density vs WorldCover tree fraction
per km² (±10%); rendered forest pixels over the WorldCover tree mask
overlap > 80% in a nadir probe.

### V5: Buildings, roads, water, airports
**Where:** new `core/terrain/osm.py`, `FlightSimScenery.cpp`, materials.
**How:**
1. OSM/Overture footprints extruded to height (tag or level count × 3 m,
   else a class default), with gable/hip/flat roofs by type (MSFS autogen
   does the same). swissBUILDINGS3D where available. Instanced by type,
   Nanite.
2. Roads and rails rendered into a **Runtime Virtual Texture** layered
   onto the terrain (no z-fighting), width by highway class.
3. Water: OSM/JRC water mask, then a water material (normal-mapped
   waves, Lumen/SSR reflection, depth colour, shoreline foam), or the
   UE Water plugin for lakes and rivers.
4. Runways from OurAirports and OSM `aeroway=runway`: flattened pads
   plus asphalt, markings, and edge-light material.
5. This feeds the planned 9.4 city building collision (physics side);
   the visual side stays labeled until collision exists.
**Measure:** footprint-projection check (building corner landmarks land
within N px on a rendered frame, same method as the imagery landmark
test).

### V6: Clouds, precipitation, weather look (NEXT.md task 12)
**Where:** `FlightSimVisualScene.cpp`, new `FlightSimWeatherVisual.cpp`,
`core/environment/era5.py`, `webapp/runs.py` (`STORM_LOOK` becomes derived).
**How:**
1. `UVolumetricCloudComponent` with a layered material: three layers
   (low/mid/high) whose coverage, base, and thickness come from
   Open-Meteo/ERA5 `cloud_cover_low/mid/high` and cloud base for
   `weather_date`, and cumulus vs stratus shape by layer. Seeded noise
   for reproducibility. Shadows onto terrain enabled (cloud shadows are
   a big part of the MSFS look).
2. Storm: cumulonimbus preset replaces the hand-picked `STORM_LOOK`;
   tornado funnel gets a proper volumetric/Niagara treatment (this also
   routes around gotcha 26's black vertex-colour funnel).
3. Niagara rain and snow sized by precipitation rate, wet-surface
   roughness on terrain and aircraft, visibility turned into fog.
4. **Labeled VISUAL-ONLY in every manifest**: the physics weather stays the
   card's wind/turbulence blocks. This matches NEXT.md.
**Measure:** rendered sky cloud fraction (thresholded sky band) vs input
total cloud cover within ±15%; Gate 6 extinction clause still passes
under overcast.

### V7: Aircraft
**Where:** `scripts/ue_import_aircraft.py`, `scripts/import_aircraft.py`,
`assets/aircraft_config/*.json`, new material templates.
**How:** a post-import material pass: PBR master materials (painted metal,
bare aluminium, glass with refraction and reflection, rubber, prop blade),
per-model livery textures, authored roughness/metallic, and
ambient-occlusion bake. Nanite on for the airframe (VSM self-shadowing).
Rotating-prop disc material by RPM (from telemetry). Nav/strobe/landing
lights as real light components at night. Higher-detail source models
only with a verified license file (the §3.3 rule is unchanged).
**Measure:** side-by-side panel vs a reference photo of the type under
matched sun angle (reader's judgment, labeled as such), plus the existing
Gate 6 aircraft-shadow clause.

### V8: Camera, post, and the beauty capture path
**Where:** `FlightSimCameraDirector.cpp`, render commandlet post settings.
**How:** physical cine camera (focal length and sensor instead of raw FOV,
matching how MSFS's drone/showcase cams read), filmic tonemapper with
explicit, recorded settings, subtle bloom, **no** fake lens flare, per-shot
motion blur (off for measurement clips, on for beauty), heat haze behind
jet engines. Optional `-Beauty` path through **Movie Render Queue** with
temporal sub-sampling and high-res tiles for hero stills (closes the
recorded MRQ deviation for beauty output only).

### V9: Performance and the interactive tier
Scalability presets (`Low/Med/High/Cinematic`) mapped to V0 to V8 features,
and an FPS budget measured by `experiments/fps_probe.py` per preset. The
interactive host (`FlightSimInteractiveMode.cpp`) gets the same scene
builder, so offline and interactive look identical.

---

## 5. New visual clauses (a "Gate V" alongside Gate 6)

Extend `experiments/gate6_visual.py` (or add `gate_v_visual.py`) so every
phase is closed by pixels, never by opinion:

| Clause | Phase | Measurement |
|---|---|---|
| Output quality | V0 | Silhouette aliasing energy below baseline |
| Sun correct | V1 | Pole-shadow azimuth vs SPA ≤ 2° |
| Exposure stable | V1 | Existing ≤ 8/255 sky drift, now at EV100 |
| Horizon exists | V2 | Terrain/sky contrast at ≥ 100 km > threshold |
| Drape on geometry | V3 | Existing landmark projection, new imagery |
| No visible tiling | V3 | Autocorrelation secondary peak < threshold |
| Texel density | V3 | ≥ 1 texel/px at 300 m AGL |
| Forest where forest is | V4 | Rendered forest vs WorldCover overlap > 80% |
| Buildings where buildings are | V5 | Footprint landmark projection |
| Clouds match weather | V6 | Rendered cloud fraction vs input ± 15% |
| Look likeness | all | Side-by-side vs an MSFS 2024 screenshot at the same place, sun, and camera: **reader's judgment, labeled as such** |

Each clause gets a **self-validation control** the way Gate 6 does
(for example, the tiling metric must trip on a deliberately tiled texture,
and the horizon metric must trip with the far-field ring disabled), or the pass
is void.

---

## 6. Owner decisions needed

1. **Photogrammetry** (Google 3D Tiles / Cesium ion): **decided.** The owner
   approved it on 2026-11-10 and again on 2026-11-11 ("the cesium token like
   policy allows it too"), including for the labelled dataset. The tiles are
   always on (CLAUDE.md).
2. **Megascans/Fab** assets vs CC0-only.
3. **Physics raster**: does the high-res near-field DEM (V2.2) also feed
   collision/AGL, or stay scenery? (Parity tests must be re-run if yes.)
4. **Capture path**: keep scene capture (measurable, deterministic) as the
   default and treat MRQ/viewport as the beauty-only path? Recommended: yes.
5. Hardware: V2 to V6 at 1080p beauty wants a GPU with ≥ 12 GB VRAM.
   Calibrations were measured on Metal only; Windows needs its own
   Gate 6/V run (NEXT.md).

Recommended order and rough effort: **V0 → V1 (1 to 2 sessions) → V2
(3 to 4) → V3 (3 to 4) → V6 (2 to 3) → V4 (2 to 3) → V5 (3 to 5) → V7 (2) → V8/V9 (2)**.
V2, V3, and V6 alone close most of the perceived gap.

---

## 7. The prompts

### 7.1 Master prompt (paste into a new Claude Code session, on the render machine)

> You are working in the `flightsim` repo (UE 5.7 render host plus a Python
> core). Read, in order: `docs/CONTEXT_PHASE8B_SESSION.md`, `NEXT.md`
> (all gotchas), `docs/VALIDITY.md` §Phase 6, and
> `docs/VISUAL_FIDELITY_PLAN.md`. The goal is to raise render fidelity
> toward Microsoft Flight Simulator 2024 at the curated locations
> (Matterhorn, Yosemite, and on-demand bakes) following the plan's phases
> V0 to V9 **in order**.
>
> Non-negotiable rules from this repo:
> - Every fetched dataset or asset: pinned URL, sha256, license and
>   attribution in the sidecar **and** in every `render.json`; NC and
>   proprietary-ToS sources are refused by name (mutation-guarded like the
>   S2 cloudless year-suffix refusal).
> - Physics is untouched unless the phase says so. Anything visual-only is
>   labeled visual-only in the manifest.
> - No placeholder airframes, ever.
> - Calibration is by probe render, never theory (gotchas 6/7). You can
>   Read rendered PNGs; do so after every probe.
> - Renders: absolute paths, `-stdout -FullStdOutLogOutput
>   -RenderOffScreen -AllowCommandletRendering`; long renders in the
>   background (gotcha 16). Use `experiments/gate6_visual.py` `render()` as
>   the subprocess pattern.
> - A phase is done only when its Gate V clause from the plan's §5 passes
>   **and** its self-validation control trips, **and** Gate 6's four
>   existing clauses still pass, **and** `pytest` is green. Record the
>   numbers in `docs/VALIDITY.md` and the state in `NEXT.md`.
>
> Start with **Phase V0** (below). Before writing code, run
> `scripts/ue_preflight.sh` (or `.ps1`) and render one baseline Gate 6
> set so every later measurement has a before. Work one phase per PR.

### 7.2 Per-phase prompts (append one to the master prompt)

**V0.** "Implement plan §4 V0. Add the explicit renderer settings block to
`ue/Config/DefaultEngine.ini`, a `-quality=measure|beauty` switch in
`FlightSimRenderCommandlet.cpp` (measure = today's behaviour
byte-for-byte), a 1920×1080 default, and configurable warm-up captures.
Prove by A/B probe whether Lumen and TSR actually run inside the
`USceneCaptureComponent2D` on 5.5; if not, implement the viewport-grab
fallback for beauty only. Write every cvar into `render.json`. Add the
silhouette-aliasing clause and its control to the gate script."

**V1.** "Implement plan §4 V1. Add `core/environment/sun.py` (NREL SPA
via pvlib, pinned in requirements) and a provenanced
`environment.time_of_day` spec field (bump SPEC_VERSION, teach the
deterministic parser and the LLM schema). Pipe elevation/azimuth through
the existing `-sun-elev/-sun-azim` flags. Convert the sun to physical lux,
enable extended luminance range, and recalibrate manual exposure in EV100
per look by probe render (replace the bias constants in
`showcase_matrix.py` and `STORM_LOOK`). Add moon and stars for night.
Add the pole-shadow azimuth clause with its control."

**V2.** "Implement plan §4 V2. Replace the single procedural section with
~2 km Nanite `UStaticMesh` tiles built in the commandlet and cached by raster
sha256, at full raster posting; enable VSM and distance fields. Add a
GLO-90 far-field ring to 250 km through `ProjectedToEngine` (curvature
included) and delete the flat backstop plane. Add a swissALTI3D/3DEP
near-field provider (`core/terrain/lidar.py`) with the same
verify-against-source discipline and a feathered seam. Physics stays on the
30 m raster. Re-run Gate 4, the imagery landmark test, and add the horizon
clause with the ring-disabled control."

**V3.** "Implement plan §4 V3. Add SWISSIMAGE, NAIP and date-matched
Sentinel-2 L2A providers behind the existing imagery sidecar, tiled to
match the V2 mesh tiles (break the 8192 cap). Add a recorded per-source
grade (dehaze, white balance, albedo scale), probe-calibrated. Build
`M_TerrainLayered` in `scripts/ue_create_materials.py`: imagery macro,
CC0 detail layers (Poly Haven/ambientCG, sha256'd, licenses recorded)
masked by ESA WorldCover + slope + altitude, triplanar on steep slopes,
distance fade, macro-variation, ERA5 snow depth. Add the texel-density and
tiling clauses with controls."

**V4.** "Implement plan §4 V4. Bake tree instances from WorldCover ×
canopy height with seeds from the spec digest; spawn as Nanite foliage in
HISMs with distance culling and far-field tree darkening; label as
visual-only scenery. Add the forest-overlap clause with a control."

**V5.** "Implement plan §4 V5. OSM/Overture/swissBUILDINGS3D buildings
(extruded + roof types, instanced, Nanite), roads into an RVT, a water
material over an OSM/JRC mask, runways from OurAirports. ODbL attribution
in every manifest. Add the building-footprint landmark clause."

**V6.** "Implement plan §4 V6 (NEXT.md task 12). Three-layer
`UVolumetricCloudComponent` driven by Open-Meteo/ERA5 low/mid/high cover
and cloud base for `weather_date`, seeded; cloud shadows on; storm preset
replaces `STORM_LOOK`; volumetric/Niagara tornado funnel (sidesteps
gotcha 26); Niagara rain/snow and wet surfaces. All labeled VISUAL-ONLY.
Add the cloud-fraction clause with a control."

**V7.** "Implement plan §4 V7. Post-import PBR material pass for every
configured airframe, livery textures, glass, prop disc by RPM, lights;
Nanite on. License rule unchanged. Produce a side-by-side vs a
reference photo under matched sun, labeled as reader's judgment."

**V8/V9.** "Implement plan §4 V8 and V9: physical cine camera, explicit
tonemap/bloom/motion-blur settings recorded per shot, optional MRQ beauty
path with temporal samples, scalability presets, and `fps_probe.py`
budgets per preset. Interactive host uses the same scene builder."

---

## 8. Status

### Update 2026-11-11: rendered rounds 5 to 40 on the Windows laptop

Everything below was rendered on the Windows render box (Intel iGPU, D3D11 SM5, UE 5.7.4,
Cesium + Google Photorealistic 3D Tiles) from branch `claude/vibrant-gauss-olema4`, round by
round through `scripts/visual_fix_round.ps1` (`docs/visual/FIX_ROUND_PROTOCOL.md`). Frames and
`ROUND.json` per round are on branch `vis-windows` under `docs/visual/round_N/`; reviews are on
`phase-2-final` `docs/visual/`. Numbers are mean RGB measured on the frames.

**Settled by measurement**

| Problem | Cause (proved by) | Fix |
|---|---|---|
| #1 Yosemite deep blue at golden hour, A-4 brown | fair-weather cumulus shadows blanketed the ground and aircraft (r17 vs r10: frame 40/51/113 -> 87/74/93) | fair-weather cloud shadows opt-in (`-fair-cloud-shadows=on`), `9cffdc84` |
| A-4 see-through checkerboard | the subject meter's aircraft-hidden captures poisoned TSR history | full warm-up again after metering, `089d086b` |
| Frames bleached | subject meter opened up to 2 stops | at most 1 stop, `089d086b` |
| Aircraft tan / near-black (A-4 111/98/84, C172 27/18/17) | the gen-4/5 aircraft look masters (r22 off: 167/155/147, 89/82/92; r29 plain probe master on the same inputs matches off exactly) | look materials **off by default** `bfb04c34`; `-aircraft-materials=on` + `-aircraft-probe=` bisect the masters (see below) |
| #10 green tornado scene | the rain veil, a lit translucent surface taking the prairie-green ground bounce (r31 veil off: sky 98/101/114 neutral; r32 fog off: still green) | unlit veil toned from the scene behind it, `029ead47` |
| #9 ring arcs under the storm cell | volumetric scud band between the iGPU's fixed altitude slices | band off; modulate scud cards, `21d98e9c` |
| #15 white popcorn scud, pale frame | lit translucent scud under a deck the cloud shadow cannot reach; fog lit by the clear sky above the deck | modulate unlit scud, deck-lit fog, low deck, `0e69e89a` / `21d98e9c` / `029ead47` |
| #13 blocky cumulus rows | hard Voronoi cells on axis-aligned grids | rounded, warped, rotated cells with a far LOD, `be749d6a` |
| #13 refused (stall) on some compiles | the LLM marked an unstated 250 kt "inferred", which planners may not move | unstated speeds are model guesses, `697c4ca6` |
| A/B switches that did nothing (r13-r18) | `FLIGHTSIM_RENDER_SWITCHES` never reached the engine argv | every switch rides the argv ahead of the planned flags, `85b5457c` |
| Cross-round A/Bs compared different shots | each round re-compiled prompts with the LLM | each scene's compile pinned at `runs/visual/specs/<NN>.json`, `spec_sha256` per row, `04093d48` |

**Kept from the rounds:** CC0 terrain detail on the tiles (Poly Haven, lane B), soft rounded
cumulus with self-shadowed bases (#3 and #12 judged good in r19), the sharper Yosemite forest and
rock, the beauty ocean over open water, dense soft rain streaks, the windscreen film (ambientCG
CC0), the tornado's smooth funnel and close hazard framing. Every third-party asset is pinned by
URL and sha256 in `THIRD_PARTY_VISUAL.md`.

**Final sweep (round 44, `7c017618`, vis-windows `ef44ace6`, `docs/visual/final/`):** 14 of 15
scenes rendered (#14 the hurricane refusal, by design); the chase clip `chase_clip.mp4` (15 s,
J-11 at golden hour over real terrain); head shots round 5 -> 44: 4 better, 0 same, 0 worse
(p3-mac's review, phase-2-final `e4aae905` `docs/visual/final/REVIEW.md`). Judged good: #1, #3, #4,
#6, #9 (domed cell and shaft), #11 (Matterhorn), #15 (dark storm). The aircraft paint default after
the sweep is the flat master (`1e5ba438`, look instances on for glass and rubber; round 46 checks
it: round 46, vis-windows `6692c1d6`: #12's canopy clear again (black pixels 86.9 % -> 13.1 %), the
exterior aircraft identical to materials-off: A-4 #4 167/153/143, C172 #8 90/83/93 in their masks).

**Labels (verify on every round-44 run): 0 of 14 pass.** Every beauty run fails
`look.beauty_not_label_aligned` (the beauty-only actors' cover over the subject is modelled, never
measured, so the clause cannot pass) -- **no beauty frame is certified label-aligned until that
measurement exists.** Also failing: `annotation.component_box` on #1 and #2 (`store_sta2` 3.4 px off
its hull; manifest, CG and pose ruled out; `hull_vs_pixels_px` diagnostic recorded per component),
`annotation.tight_box_null` on #10 and #13, `annotation.mask_offset` and `annotation.depth_range` on
#12 (the cockpit camera sits inside the aircraft's hull, so hull corners and the tail project behind
it: a limit of those two checks for an interior camera, not a pixel fault; still failing in round 46). Full text `docs/visual/final/verify_round44.txt`. The labels pair with
the BEAUTY frame on the web-app path (`-labels` in the same commandlet run as `-quality=beauty`); the
CLI `flightsim capture` renders measure frames only.

**Open (not fixed):**
- #10 green tornado scene: neither the veil nor the volumetric fog (r45: green with the veil off at
  the same commit); the funnel material or another sky source.
- #13 four straight light lines on the sea (present since round 5; not the tiles: tiles at z 0 under
  the cap at 20 m; not the distant-cloud disc).
- #2 super-bright preset: blue cast (sky light and aerial perspective excluded in round 5).
- #7 tower view in heavy rain: a flat grey field around the readable A320.
- The gen-4..6 aircraft paint masters darken the aircraft (flat master on the same inputs is right;
  coat, AO, normal, wear, wet, raw-base and Default Lit probes did not move the gen-6 pixels -- the
  probe plumbing itself is suspect). Paint uses the flat master until found.
  Round 25 (PROBE_LOG "## round 25"): rounds 37-39 are byte-identical frames and the texture is
  gone -- the default material of a master that fails to compile. The host now compile-checks
  the masters and falls back to M_AircraftPaintCoat (clear coat, no Custom node), then flat;
  the default is the masters again, -aircraft-probe=flat / coat the A/B. #12's panel: the c172p
  interior .ac as a beauty-only part of body_beauty. Both await a Windows round.
- A ghost check inside verify (the round summary has one: `ghost.score`, all < 0.6 in round 44).

**Owner decision 2026-11-11: gear-up cruise.** Retractable-gear airframes airborne above 100 ft AGL
start gear-up unless the prompt says landing, approach, final, take-off or gear down (core/fdm/gear.py,
6dda3f70; the run card's start_gear_up carries it to UE). The owner approved the moved physics baselines:
A320 trim thrust 11943 -> 6541.6 lbf, the engine-out altitude effect 3.1 -> 1.72 m, and the Global 5000
trimming 300 kt at 10 km.


### Update 2026-11-12: rounds 47 to 81 on the Windows laptop

Same machine and protocol as above; frames on `vis-windows` under `docs/visual/round_N/`.
Shade = the frame's lower-right quadrant, sRGB means; B-R is its blue minus red.

**Settled by measurement**

| Problem | Cause (proved by) | Fix |
|---|---|---|
| `look.beauty_not_label_aligned` failed every beauty run (0/14) | the beauty-only actors' cover was modelled, never measured | measured cover (`CoverCapture`, half-size shown/hidden captures inside the label mask; `3680856c`); gone from every run from round 47 |
| #09 DXGI_ERROR_DEVICE_HUNG, 12 of 12 attempts, also on round-44 code | the laptop's GPU state, not the code | a reboot; #09 renders and passes verify from round 68 |
| The tiles drew Cesium's own material, so every tiles shader (de-light, detail, grade, shade neutraliser) never ran (r63-r65: all 5260 primitives `M_CesiumBaseMaterial`, `Material` read back null) | Cesium 2.30 `SetMaterial` destroys the tileset and the tile load copies `GetMaterial()`; the reflected property set was not it | `ACesium3DTileset::SetMaterial` directly, read back, re-asserted before each view wait (`552c9ab5`); from round 66 every primitive draws `M_FlightSimTilesBeauty` |
| #01/#02 sepia once the tiles material drew (r69: #02 shade B-R -50, #01 -77; r66's every-texel-grey probe still orange-brown) | two corrections stacked: round 4's neutral stated fill (sky light 1/0.50/0.25, set to cancel the photograph's blue while the material never ran) and the now-working shade neutraliser. #02 A/B r70-r74: neutraliser off +34, fill off -20, aerial perspective off -61, fog off -48 | the stated fill keeps the sky's colour (share 0; r76 #02 -18, grey-tan rock, grey-green forest) and the neutraliser is scaled by the sun, x0.5 at <= 10 deg to x1 at >= 40 deg (r77 #01 at 0.5: -42, golden hour; a global 0.6, r79, fits neither) (`af3ac2a3`; round 80 confirmed it on #01, #02, #04 and #05: #01 golden, #02 neutral, the desert pair unchanged) |
| #10 green under the storm deck | the storm deck look keyed on world_preset only | a storm weather event takes the deck look (`41bfb115`); r57 neutral grey 39/37/42 |
| #13 four sea lines | the contrails (r54: gone with `-contrails=off`) | a look question, not a defect; contrails kept (`FormationRamp`, `-contrail-formation-ramp=`) |
| #12 no instrument panel | the c172p interior was never converted | the interior `.ac` as a beauty-only part (r51: panel drawn) |
| Gear down at cruise | (owner decision 2026-11-11) | `MeshGear` hidden while gear-pos-norm < 0.01; verifier excludes the gear when retracted (`2df64b35`; r51 #13 steps_hidden 359) |
| Paint masters fell back (`float4 nozzles[4]` 12 of 16 elements) | the soot Custom node's array literal | `_rgba` Append(RGB, A) (`434ba7e6`); r53 M_AircraftPaint compiles, A-4 white 169/156/145 |
| Cloud-layer blocks and grain at the horizon | footprint shadow samples on a fixed grid | stratified IGN dither and a march fade under the distant sheet (`fa56ba4d`, `1ef9bcae`); r58-r62 blocks gone, faint steps on #13's upper-right bases |

**Final sweep:** round 81 (`af3ac2a3`) was abandoned (the laptop slept during #9; a hung #10 then locked the plugin DLLs until a reboot). Round 83 (`b915b591`, 2026-11-13, vis-windows `d2863b3d`/`f379bb12`): 14 of 15 rendered, #14 refused as designed (`prompt.unsupported`, hurricane), 0 failed, no device loss, no tiles timeouts, capture 71-276 s per scene.

**Labels (`flightsim.verify`, round 69 at `552c9ab5`): 8 of 14 pass** (#03, #04, #05, #06, #07, #09,
#11, #15). Still failing: `component_boxes` on #01 and #02 (`store_sta2`), `mask_vs_geometry` on #08
(14.6 %), `tight_box_present` on #10 and #13, `depth_vs_geometry` and `mask_vs_geometry` on #12 (the
cockpit camera inside the hull, a limit of those checks for an interior camera). Round 83 at `b915b591`: the same 8 of 14 pass, with the same failures.

**Cloud realism (round 82, the owner 2026-11-13: "the clouds dont look that realistic").** r69's
#03/#13 cumulus were flat, smeared, soft-edged blobs without lit tops or dark bases; #11/#12/#13's
distant sheet a stack of hard horizontal bands; #15's scud black blotches on the deck. Within the
iGPU budget (no sample, no hash added), behind `-look-cloud-billow=on|off` (off = round 81):
- cumulus only: coverage contrast x2.5 (the soft edge was over one sigma of the field wide), the
  erosion noise at 0.15 km eroding 0.5 (was 0.35 km, 0.35), a thin base under a dense body
  (`HeightDensity` 0.6: density x 0.4 at the base rising to 1 at 0.7 of the layer), sky-light
  cloud-bottom occlusion at least 0.8 (was 0.5 in clear and hazy);
- the distant sheet: below 0.3 of vertical its derivative relief fades out and its edge widens
  up to 4x (`GrazingSoften`);
- scud tone 0.75 under a deck, 0.85 in the open (was 0.5, 0.7; not switched).
Material generations: clouds 8 (graph 7), distant 5, so Windows rebuilds both.
Round 82 (on) vs 182 (off) at `b915b591` (vis-windows `92a4e643`/`da14bdc4`), 5/5 each: the
records read as stated (#15 is not cumulus: billow false both ways). On is slightly better (crisper,
finer edges; darker bases, brighter tops on #03/#12/#13; 9-37 % of pixels differ, SSIM 0.97), so it
stays on. NOT fixed: the #11/#13 slabs with vertical walls, the soft step on #12's far band and
#15's dark patches (the scud tone is not switched, so the A/B cannot show it).
Round 92 (`c7f9686a`, vis-windows `e24bbce5`): with the billow on the cut also rises over the
whole layer (`HeightDensity` x `DOME_TAPER` 1.0 x h^1.5 of the way to the top cut; clouds
generation 9). #03 and #13 now read as heaped cumulus (Windows and p3-mac agree), though #13's
flat-bottomed steps at the horizon remain and #11's horizon is still a streaky sheet. The scud tone
went to 0.9 / 0.95, but #15 came out pixel-identical to r82, so the scud cards are not what draws its
dark patches (round 93 tests `-rain-veil=off`).
Post pipeline: the yellow-green contours (r82 #03/#11) and r83's purple/green sky rings (#05) and
fringes (#04/#06/#08) all came from the halation step. ffmpeg n8.1.3's `blend=all_mode=screen` on
gbrp16le is not the identity over an all-black layer (51/67/90 went to 74/90/110); halation off or
an 8-bit blend gives the raw frame's 0.00 %. Fixed in `5a4d0173` (beauty_post v2: `format=gbrp`
before the split). The same commit fades #13's contrails in with camera distance
(camera fade 30 m + 120 m; LOOK_GENERATION 12). Round 93 measures both.
Round 93/193 (vis-windows `f709fa45`/`c33c1328`, on `6fe12218`, after a reboot cleared a stuck
editor; the camera fade is PixelDepth math because UE 5.7 Python has no CameraDepthFade class):
prep built with 0 MATERIAL-FAILED. #13's contrails now fade in and are softer, though still
straight; they stay as they are. #15 with `-rain-veil=off` changes every pixel: the grey murk and the
"patches" are the rain veil in front of the far fog band, and veil-off's bright blue sea under a
storm deck is the less real frame, so the veil stays on and the patches item is closed.
**#13 reads as night at noon.** The raw sea (lower 55 %, mean RGB) was [20,66,131] through r60
(`fa56ba4d` with `-look-cloud-tiers=off`), [15,47,111] in r58 (tiers on) and [12,34,95] from r61
(`1ef9bcae`) on. The v1 halation bug's lift hid this; with v2 the Ektachrome cube, which darkens
saturated blue (as slide film does; its grey axis is neutral, so a luma tie changes nothing),
takes the post to [11,19,60]. Round 94/194 A/B (`-look-cloud-tiers=off`, `-sky-capture-clouds=0`)
isolates the raw drop. Note that from 10 km the near cumulus are not drawn over the sea, only at
the horizon.
Rounds 94/194 (`5ff76626`/`333f1554`): `-look-cloud-tiers=off` brings #13's sea back to 17/59/122
and `-sky-capture-clouds=0` changes nothing. The render record shows why: the only layer was the
sky plan's default at 11-14 km (core/sky/plan.py lifts it >= 1 km above the flight), ABOVE the 747,
and the sky light's cloud AO under it darkened the whole sea. Cumulus never form there.
`c641a8c4` (beauty only): a default cumulus layer whose base is above 4000 m is drawn as the fair
slab (1500-2700 m); stated heights are kept (record: `lowered_below_cruise`, `plan_base_m`).
Round 95 (`e4a78e2f`): #13's raw sea is 50/84/136 (post 48/68/104), with scattered cumulus below
the 747 to the horizon; the night-at-noon look is gone. The #03 control is unchanged (max diff 9).
Left on #13: from 8 km above, the cumulus read flat (white tops, little side shading, no shadows on
the sea), and the horizon lacks the pale haze band a real cruise view has.
Next in this lane: M_StormCell's weather map and noise (the storm tiers).

**Open (not fixed):**
- `store_sta2`'s component box on #01/#02, 3.4 px off its hull (manifest, CG and pose ruled out).
- #08's mask 14.6 % off its geometry; #10 and #13 tight boxes.
- #12's two geometry clauses need an interior-camera form.
- #07 shows rain streaks rather than bands; faint steps on #13's cloud bases.
- #11's horizon streaks; #13's flat-bottomed steps at the horizon; #13's cumulus read flat from above; #13's horizon has no haze band.
- #12's see-through instrument faces: p3-mac's `955a4694`, rendering in p3-mac's round 84.
- #06's ocean shade reads blue (+49), probably the water itself.
- Every tiles amount stays UNCALIBRATED (`SUN_LOW_DEG`, `SUN_HIGH_DEG`, `SUN_LOW_SCALE`,
  `STATED_FILL_NEUTRAL_SHARE` among them); `-stated-fill-share=` and a numeric `-tiles-shade-neutral=`
  are the A/B switches.

**Updated 2026-11-09, after the visual-overhaul session.** Mac session
flightsim-83, swarm `swarm-1794241474984-rmywk3`, branch
`claude/vibrant-gauss-olema4`, base commit `355dae64`, five look lanes
merged at `ae836a29`. That Mac cannot compile or render: Xcode 27.2 is
above UE 5.7.4's maximum of 26.9, and Cesium for Unreal is not installed.
Every row that says **code written and reviewed, not built or rendered**
means exactly that. The C++ has never been compiled, no frame has been
rendered with it, and every look constant is UNCALIBRATED (set by probe
render on the render machine).

Each row lists its evidence: the commits (in `git log 355dae64..ae836a29`),
the Python tests that pin the Python twin of each table, and the matching
block of `scripts/check_bridge_api.sh`. On the Mac that script reports 226
engine symbols `ok` against the UE 5.7.4 headers. Its one FAIL,
`module CesiumRuntime`, was there before the session, because Cesium is not
installed on the Mac. The per-lane decisions, constants and probes are in
`docs/visual/PROBE_LOG.md`. The exact Windows sequence is in
`docs/visual/RENDER_RUNBOOK.md`, and the paste-in job for the Windows
session is `docs/visual/WINDOWS_JOB.md`.

| Phase | State | What exists | Evidence |
|---|---|---|---|
| V0 render foundation | **Code written and reviewed, not built or rendered** | Earlier: `-quality=measure\|beauty`, `-warmup=N`, `-sun-lux=`, Lumen GI and reflections as capture overrides. This session (render-path lane): TSR really on in beauty (the scene capture clears `ShowFlags.TemporalAA`, so `r.AntiAliasingMethod=4` alone gave FXAA); Lumen surface cache 1.0 and quality overrides in the capture; Cinematic scalability; still accumulation `-still-samples=N` (1 to 64); path-traced hero stills `-quality=pathtrace` with a one-process `r.RayTracing` ini override (never in `DefaultEngine.ini`, where it would move measure pixels); everything asked and read back under `render_settings.beauty_path`; an edge-aliasing number in Gate 6 (reported, never a gate, with a point-sampled control); the four-shot contact sheet `experiments/visual_contact_sheet.py` with `scripts/render_visual_sheet.{ps1,sh}` | `ab548ac6`, `0c41c3f1`, `b76705b1`, `31e99409`, `e034ea30`, `8b91a41c`; `tests/test_render_path_beauty.py` (10 tests), `tests/test_visual_contact_sheet.py` (18), `tests/test_render_quality.py`; check_bridge_api "render-path lane" block |
| V1 sun, sky, exposure | **Code written and reviewed, not built or rendered** (the earlier ephemeris half is pinned to NREL SPA by tests) | Earlier: `core/environment/sun.py`, `environment.time_of_day`. This session (look-dev lane): `FlightSimBeautyLook` applies the `-beauty-look=` sidecar that the web app writes on every beauty run. Sun lux is the Bird and Hulstrom clear-sky direct normal divided by the engine's zenith transmittance. The sun's colour temperature is set per elevation band. Exposure is a manual EV100 per sun-elevation band through the physical camera (no auto exposure, so no breathing), with Local Exposure on top. The filmic tonemap uses the engine's stated defaults. There are three grades: golden_hour, desert_noon and storm. Moon and stars are the earlier physical sky (NEXT.md gotcha 27, also never rendered). Moving haze into the sky atmosphere's Mie layer is the world lane's work (V6 row) | `44eae98d`, `501f634b`, `eaa26608`; `tests/test_beauty_look.py` (37 tests; each EV100 band is within 1.5 stops of the incident meter on the modelled illuminance); `tests/test_sun.py`; check_bridge_api "engine surface the beauty look assumes" |
| V2 terrain geometry | **Not started as planned; partly superseded** | Google Photorealistic 3D Tiles are the ground of every terrain render (owner rule, CLAUDE.md), so the plan's Nanite chunks and far-field ring are not the route. The world lane added one thing here: the sky atmosphere's planet ground albedo fills the horizon beyond the tiles | `cd02c0d4` (`ground_albedo_*` in `core/scene/world_beauty.py`) |
| V3 terrain surface | **Code written and reviewed, not built or rendered** (re-scoped from the imagery drape to the tiles) | `M_FlightSimTilesBeauty` on the Cesium tileset, plus Cesium smooth normals, both set by reflection by name and driven by `MPC_FlightSimWorld`. It applies de-haze and saturation, a near-field detail normal and micro-roughness that fade with range, wet darkening, and puddles on flat ground. The tiles stay the ground: nothing here can turn them off. The Cesium per-primitive parameter names (`baseColorTexture`, `baseColorFactor`) are UNVERIFIED; a white tiles frame means they are wrong | `cd02c0d4`, `c4807002`, `9ba19f05`; `tests/test_world_beauty.py` (25 tests; pins the C++ pure blocks to the Python); `tests/test_ue_materials.py` |
| V4 vegetation | **Code written and reviewed, not built or rendered; assets incomplete** | `FFlightSimGroundDetail` places ground scatter from a seeded sidecar (`python -m core.scene.world_beauty --biome ... --seed ... --out ...`). The scatter is in the same frame's mask, class and depth (labelled `vegetation:all` when the card names it) and has no collision. Ten Poly Haven CC0 models are pinned in `assets/scatter/polyhaven_pins.json`, five of them fully. Still missing: the import script `scripts/ue_import_scatter.py` (until it exists, every species records "the mesh did not load"); the big trees, which were not downloaded and are drawn as nothing; and a land-cover mask, without which trees can stand on roofs or water | `02575abd`, `cd02c0d4`; `tests/test_world_beauty.py` |
| V5 buildings, roads, water, airports | **Not started** | Buildings and roads appear only as part of the tiles' photogrammetry | — |
| V6 clouds, precipitation, weather look | **Code written and reviewed, not built or rendered** | `FFlightSimWorldBeauty`. One atmosphere preset per card (clear, hazy, overcast, rain, storm) moves a share of the card's haze into the Mie layer, so the haze is counted once. `M_FlightSimCloudLayers` (seeded layered noise, four shapes) replaces the material on every engine-default cloud; the storm's `M_StormCell` is untouched. `-beauty-clouds=fair` adds an optional fair-weather layer. The storm weather's rain drops get a readability gain, and lightning becomes a sky-light pulse. Each frame records cloud occlusion with a completeness flag (`cloud_occlusion_complete: false` when a cloud is not modelled). All of it is beauty only: measure never constructs it. Storm weather stays on by default | `cd02c0d4`, `a7f18fbf`, `c4807002`, `0b1169cc`, `d35f877c`, `f408e40f`; `tests/test_world_beauty.py` |
| V7 aircraft | **Code written and reviewed, not built or rendered** | Look configs for all seven airframes (`assets/aircraft_config/look/`), resolved into `look_manifest.json`. Master materials (paint as Clear Coat, bare metal, glass, rubber) and per-model `Look/MI_<slot>` instances. Beauty-only FX actors in `FlightSimAircraftFX`: nav, strobe and landing lights, contrails, vapour, afterburner, and heat haze (OFF unless `-heat-haze=on`). Two deviations from §4, on purpose: glass is opaque, because translucent glass would show sky where the mask says aircraft, and Nanite stays off for airframes. Higher-detail candidates for the J-11 and J-15 are listed behind a licence gate, but none is pinned, so none is usable. No redistributable J-35 model was found | `be8a77d5`, `9c0da7a6`, `0492fc61`, `46bc3838`, `e2abc9ba`, `301a03f2`, `0059185d`, `f64ee666`; `tests/test_aircraft_look.py` (27 tests); check_bridge_api "AIRCRAFT LANE" block |
| V8 camera, post, beauty capture | **Code written and reviewed, not built or rendered** | The look-dev lens. Focal length is derived from the capture's FOV and the card's sensor; the FOV itself is never changed. Depth of field is on `cinematic` only, focused each frame on the aircraft. Motion blur is 180 degrees at the clip's fps. Bloom, image-based flare and grain are subtle. There is no vignette on `standard` (owner, 2026-10-11), and no lens distortion or chromatic aberration, so labels match pixels. Deviation: hero stills come from the path tracer through the scene capture, not from Movie Render Queue | `44eae98d`, `501f634b`, `ab548ac6`; `tests/test_beauty_look.py` |
| V9 performance tiers | **Not started** | — | — |
| Verifier (labels match pixels) | **Code written and reviewed, not run on a render** | `flightsim.verify` gains two checks, `look_record` and `look_label_alignment`. Their refusals are `look.quality`, `look.measure_altered`, `look.pixel_moving_unrecorded`, `look.record` and `look.beauty_not_label_aligned`. `experiments/look_label_check.py` measures the mask-edge offset in a measure bundle against a beauty bundle, with a 3 px self-validation control. The commandlet does not yet write `pixel_moving_effects` or `cloud_occlusion` (an integration step is in progress); until it does, `look_label_alignment` is NOT RUN on every bundle | `aa04c0a6`, `0db77323`, `bdaa0509`, `38c76b39`, `2b6bdf7d`, `521906f7`; `tests/test_look_verify.py` (32 tests), `tests/test_look_label_check.py` (8); `docs/schemas/render_json_beauty_look.md` |
| Gate V (§5) | **Not on this branch yet** | Another lane is adding `experiments/gate_v_visual.py`. Until it lands, no §5 clause has a script | — |

**Nothing above has been measured.** None of this work has a contact
sheet, clip, Gate 6 beauty run or label-alignment number yet. The first
measurements come from the runbook:

- Gate 6 under measure, unchanged against the base commit;
- the base and HEAD contact sheets;
- the compare sheet in `runs/visual/final/`;
- the chase clip;
- `flightsim.verify` and `look_label_check` on a labelled beauty render;
- the path-traced hero still.

**Deviation from §4 V0, on purpose:** the renderer settings are applied
**per capture at runtime** when `-quality=beauty`, not in
`DefaultEngine.ini`. A project-wide ini change would alter every
`measure` render that Gate 6 passed on. `r.Nanite.ProjectEnabled`,
`r.GenerateMeshDistanceFields` and `r.Lumen.HardwareRayTracing=False`
were already in the ini (Phase 2 B4), so measure already runs with them.
`r.RayTracing` is deliberately left out of the ini.

**Measure is untouched by construction.** Every new C++ line is gated on
`-Visual -quality=beauty` (or `pathtrace`), a measure `render.json` gains
no field, and the physics is unchanged. That claim is the first thing the
render machine checks: Gate 6 under measure, then Gate 10-R comparing its
frames with the base commit's Gate 6 frames.

**Next step on the render machine:** follow
`docs/visual/RENDER_RUNBOOK.md` in order.
