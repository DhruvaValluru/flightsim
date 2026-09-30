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
| Engine | UE 5.5, render via `UnrealEditor-Cmd` commandlet into a `USceneCaptureComponent2D`, `SCS_FinalColorLDR`, RGBA8 sRGB target | `FlightSimRenderCommandlet.cpp:782-808` |
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
| Google Photorealistic 3D Tiles / Cesium ion World Terrain + Bing | Commercial ToS (caching and offline use restricted) | **Owner decision. Default: refused.** |

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
the spec digest (reproducible). Spawn as **Nanite foliage** (UE 5.5
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

1. **Photogrammetry** (Google 3D Tiles / Cesium ion): biggest single jump
   toward MSFS in cities, but proprietary ToS. Default: refused.
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

> You are working in the `flightsim` repo (UE 5.5 render host plus a Python
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

| Phase | State | What exists | Verified how |
|---|---|---|---|
| V0 | **Code written, not yet built or rendered** | `-quality=measure\|beauty`, `-warmup=N`, `-sun-lux=` on the render commandlet; Lumen GI/reflections as capture post-process overrides plus TSR/VSM cvars, read back into `render.json`; `FLIGHTSIM_RENDER_QUALITY=beauty` for the web app; `gate6_visual.py --quality beauty` | Python side: `tests/test_render_quality.py`. C++: **needs a build and a Gate 6 run on the render machine** |
| V1 | **Python side done; the renderer consumes it through existing flags** | `core/environment/sun.py`, `environment.time_of_day` (SPEC_VERSION 7), both compilers, webapp sun look plus exposure interpolation, named refusals | `tests/test_sun.py`: pinned to NREL SPA (pvlib) within 0.02°, events, polar refusal, night refusal, compilers, command flags |
| V1 remainder | Not started | Physical-lux sun with EV100 recalibration (the `-sun-lux` hook exists), moon and stars, weather-driven aerosols, pole-shadow azimuth clause | — |
| V2 to V9 | Not started | — | — |

**Deviation from §4 V0, on purpose:** the renderer settings are applied
**per capture at runtime** when `-quality=beauty`, not in
`DefaultEngine.ini`. A project-wide ini change would alter every
`measure` render that Gate 6 passed on. Nanite and mesh distance fields
are startup-only project settings, so they arrive with V2, the first
phase that has Nanite meshes to use them.

**Next step on the render machine:**
1. `./scripts/build_ue.sh` (or `.\scripts\build_ue.ps1`).
2. `python experiments/gate6_visual.py`. It must still pass unchanged,
   which proves `measure` is untouched.
3. `python experiments/gate6_visual.py --quality beauty`. Read
   `runs/gate6_beauty/full/render.json` (`cvar_*`, `gi_reflections`)
   and look at the frames.
4. Try `FLIGHTSIM_RENDER_QUALITY=beauty` with a prompt like "fly the
   c172 over yosemite at golden hour".
