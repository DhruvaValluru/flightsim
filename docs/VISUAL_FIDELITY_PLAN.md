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
**Verify path (sky step 8):** `.\scripts\sky_compare_round.ps1 -Round N -Scene 3 -CompareWith M`
renders clear / cumulus / stratocumulus / overcast at one camera and lays them out
against round M in `docs/visual/sky_compare/round_N/` (§8 "Sky step 8"; UNMEASURED
until the Windows laptop runs it).

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

**Sky step 1 (the owner's X-Plane-12 brief, 2026-11-14; docs/visual/XPLANE_SKY_DESIGN.md §3): wispy
edges, cauliflower tops, thin-edge light, beauty scattering.** The brief's reference photo has
ragged, partly transparent cloud edges, fine cauliflower lobes on the tops, soft grey-blue bellies
and light coming through thin edges; r95's #03/#13 have smooth rounded blobs with dark flat
undersides. Written on the Mac, NOT built or rendered: everything below is UNMEASURED and every
amount UNCALIBRATED. Behind `-look-cloud-wisp=on|off` (on by default; off = round 95 bit for bit),
cumulus and stratocumulus layers only (overcast and nimbostratus keep their veils), beauty only:
- `M_FlightSimCloudLayers` / `cloud_layers.hlsl` gains five Custom inputs with OFF defaults
  (`WispAmount` 1, `CurlStrength` 0.6, `EdgeThinPower` 1.6, `TopDetailGain` 0.6, `BoundaryErosion`
  0.5 when on): a view sample reads the erosion noise at a flow-warped point (two gradient noises
  at half the detail cell: lobes stretch into wisps; not a divergence-free curl, stated in the
  shader), a third finer Worley octave (4.1x, zero-mean) is added towards the top of the layer and
  faded out by half the far LOD (cauliflower), the erosion is x (1 + 0.5 x (1 - density)) so it
  bites the outline and spares the core, and the density is raised to the 1.6 after the erosion so
  the soft band is optically thin (pow(0, p) = 0: the drawn cover is unchanged). Shadow samples add
  no hash (they read the undistorted detail or its mean, as round 52) and do get the thinning,
  which is what lets the sun through a rim. Cost: up to +43 lattice hashes on an in-cloud view
  sample within 13 km, none in clear air, none on the shadow march; no march sample added.
- the material is now built with its own `VolumetricAdvancedMaterialOutput` constants
  (`CLOUD_SCATTERING`: g 0.85 / -0.3 blend 0.3, 2 octaves, contribution 0.7, occlusion 0.25,
  eccentricity 0.4, ground contribution on; the storm's `M_StormCell` keeps `STORM_SCATTERING`
  0.5/0.5/0.5 and is not rebuilt), so bodies and undersides are lit by more wrapped multi-scatter;
  albedo stays 0.98. The sky light's cloud-bottom occlusion is CAPPED at 0.45 where the wisp
  applies (round 82 raised it to 0.8: a belly got a fifth of the sky).
- the distant sheet's `BaseDarkening` 0.55 -> 0.70, `BaseSunShare` 0.15 -> 0.25, `SilverLining`
  0.6 -> 0.8 (parameters only; its shader and generation are unchanged).
- the owner's `Coverage, Density, DetailStrength, NoiseScale, Wind` are documented aliases of
  `Coverage, ExtinctionPerM, DetailErosion, ShapeScaleKm, WindOffsetM` (recorded; no second input).
Material generations: clouds graph 7 -> 8, world 9 -> 10 (Windows rebuilds it at the round's prep
step; distant unchanged). render.json: `look_applied.world_beauty.clouds.material` (path,
`graph_generation_expected` 8, the asset's stamped `graph_generation` read back, `scattering`,
`albedo`, `owner_aliases`) and per layer `cloud_wisp`, `cloud_wisp_applied`, the five scalars by
name, `sky_light_cloud_bottom_occlusion_before_belly_cap`, `belly_occlusion_cap`. Pinned by
`tests/test_cloud_wisp.py` (C++ == Python == HLSL == material script), `test_cloud_tiers.py` (the
shader body compiled as C++ against the Python twin with the wisp on and off), `test_cloud_billow.py`,
`test_distant_clouds.py`. Measure it on the Windows laptop with
`.\scripts\visual_fix_round.ps1 -Round 100 -Scenes "3,13" -CompareWith 95` (on) and
`.\scripts\visual_fix_round.ps1 -Round 101 -Scenes "3,13" -Switches "-look-cloud-wisp=off" -CompareWith 100`
(the A/B; 101 must be r95 pixel for pixel but for the scattering constants and the sheet's three
numbers, which are not switched). Kill criterion: `887a0006` (TDR) in the log -> render with
`-look-cloud-wisp=off` and file it. Unknown until rendered: whether 0.6 cells of flow reads as
wisps or smear, whether 1.6 lets the rim glow or hollows the cloud, the in-cloud cost on the iGPU.

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

### Update 2026-11-14: `-cloud-volumetric-scale`, the impostor A/B hook

A beauty-only render switch for judging p3-mac's impostor cloud cards (`0deddc6d`,
`-cloud-impostors=off|pilot|on`) against the volumetric layers without doubled
clouds. `-cloud-volumetric-scale=<0..1>` (1 by default; read from the command line
and `FLIGHTSIM_RENDER_SWITCHES` like `-look-cloud-billow=`) multiplies every
volumetric layer's drawn cover (the material's `Coverage`, so also the deck
shadow and the occlusion rows). The distant sheet ignores the scale: it continues
the layer's unscaled cover (`distant_sheet_cover`), so the horizon stays under an
impostor-only frame. At 0 the
layer's component is hidden (`SetVisibility(false)`), not left at `Coverage 0`: an
invisible cloud component has no render state, so the frame has no per-pixel
cloud march, no cloud shadow map and no cloud-on-fog pass, the cheapest form for
the iGPU; `Coverage 0` would keep all three and march the slab to find nothing.
Not a number, or outside 0..1, refuses by name
(`world_beauty.clouds: -cloud-volumetric-scale=... is not a number in 0..1`).
`render.json look_applied.clouds.layers[]` records `volumetric_scale`,
`volumetric_scale_applied`, `cover_before_volumetric_scale` and
`volumetric_hidden`. Measure renders are untouched (the code is in `ApplyClouds`,
reached only under `-quality=beauty`). `core/scene/world_beauty.py`
`cloud_volumetric_coverage` is the twin; `tests/test_cloud_volumetric_scale.py`
pins the two. **UNMEASURED**: written on the Mac, never compiled or rendered.
The Windows A/B (impostors on, volumetric hidden, against a reference round):

```
.\scripts\visual_fix_round.ps1 -Round N -Scenes "13,3" -Switches "-cloud-volumetric-scale=0" -CompareWith <ref>
```

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

### Sky step 2 (2026-11-14): the beauty host reads the sky plan's cloud fields

The owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md, design
docs/visual/XPLANE_SKY_DESIGN.md §4). Nothing here was rendered.

**What it draws.** Nothing new by itself. Under `-quality=beauty`,
`FFlightSimWorldBeauty::ApplyClouds` (FlightSimClouds.cpp) now receives the `-sky=`
plan (`FFlightSimSkyPlan`, passed by the commandlet at the one beauty `Build` site,
nullptr without a plan) and reads the `clouds` block's new, optional fields
`cloud_type`, `coverage`, `density`, `detail`, `cirrus_coverage`, `coverage_source`,
`seed` (FlightSimSky.cpp `Load`, `TryGet*` after the mandatory reads; a v1 plan
without them loads and the header's defaults are recorded: type "" and coverage -1
= not stated, density 1 and detail 1 = the row; `SKY_VERSION` stays 1). Step 5
writes them; today's `plan.py` writes none, so every current render records
`clouds.plan.fields_source: none ...` and draws round 95 exactly. Per layer one law,
`FlightSimWorldPure::LayerSource` (Python `world_beauty.layer_source`), picks the
cover and the shape: `-cloud-type=` (the owner's probe) > the card's `look.clouds[0]`
or the stated fair layer (dataset truth) > the plan (not under the rain and storm
presets: the deck stands) > the shape's default. The owner's parameter names land
on M_FlightSimCloudLayers as: Coverage -> `Coverage` (the cover decided); Density ->
`ExtinctionPerM` x the plan's density (clamped 0.5..1.5); DetailStrength ->
`DetailErosion` x the plan's detail (saturated); NoiseScale -> the row's
`ShapeScaleKm`; Wind -> `WindOffsetM` (Advance, unchanged). `clear` and `cirrus`
hide the volumetric layer (`SetVisibility(false)`; step 6 draws the cirrus sheet);
altocumulus draws the stratocumulus row until step 5 adds its own. With a plan AND a
card layer, two components exist and FScene draws the last registered (the card's):
the plan's is recorded `engine_stack_shadowed`, left out of the sky capture
(`SetVisibleInRealTimeSkyCaptures(false)`) and the layer bookkeeping, and
re-materialled all the same. The occlusion row reads the extinction drawn.

**The switch.** `-cloud-type=clear|cumulus|stratocumulus|altocumulus|cirrus|overcast|nimbostratus`
(empty = not given); another word refuses `world_beauty.clouds: -cloud-type=...`.
The existing `-cloud-cover=` probe builds a CARD layer, the wrong component for this.

**Record** (`look_applied.world_beauty.clouds`): `plan` {fields_source, cloud_type,
cloud_type_known, coverage, density, detail, cirrus_coverage, coverage_source, seed,
seed_stated, card_seed, seed_matches_card, cloud_type_switch, precedence,
owner_parameters, exposure_sees_plan_clouds: false, measure_path, calibration}; per
layer `cloud_type_source` (switch | card | plan | shape default), `cloud_type_applied`,
`cloud_type_requested`, `component_source` (sky plan | card look.clouds | fair),
`engine_stack_shadowed`, `plan_density`, `plan_density_scale`, `plan_detail`,
`extinction_per_m_applied`, `detail_erosion_applied`, the extended `cover_basis`;
`hidden_layers[]` {component, component_source, cloud_type_source, reason};
`plan_component_shadowed_by_card`, `engine_stack_basis`. A measure render.json
gains no field: the commandlet's `scene.sky` was NOT extended (the design's §4 said
to; this section's "a measure render.json gains no field" wins).

**Unchanged.** FlightSimSky.cpp `Build` (the measure host: the stock
`m_SimpleVolumetricCloud_Inst`, its missing-material note) byte for byte, pinned;
`FFlightSimWeather::VerifyCloudMaterials` (no material changed in this step: Volume
domain and the usage flag stand); labels (volumetric clouds write no depth or
stencil; no new actor); exposure (`plan.py` untouched, the fields are never read into
`ev100`); flight dynamics; the round-95 lowering, which keys on stated HEIGHTS (card
or fair layer), not on the plan's type: a plan cumulus over a 10 km cruise is still
drawn as the 1.5-2.7 km fair slab (c641a8c4), the camera stays clear.

**UNCALIBRATED.** Which row a type word draws (`world_beauty.PLAN_CLOUD_SHAPES`), the
density clamp 0.5..1.5, the detail saturation: look values, never from a frame.

**UNMEASURED.** Everything above: that a Windows build compiles it, that the host
applies the switch's and the plan's type, that the card's component and not the
plan's is the one drawn (read in UE 5.7 VolumetricCloudRendering.cpp
`AddVolumetricCloud`, not witnessed), that `SetVisibility(false)` empties the sky
(read in VolumetricCloudComponent.cpp `CreateRenderState_Concurrent`). The exact
Windows measurement, after `scripts/ue_create_materials.py` has rebuilt the materials
and with `FLIGHTSIM_SKY=physical` set in the shell:

    .\scripts\visual_fix_round.ps1 -Round 98 -Scenes 3 -Switches "-cloud-type=stratocumulus" -CompareWith 95
    .\scripts\visual_fix_round.ps1 -Round 99 -Scenes 3 -Switches "-cloud-type=clear" -CompareWith 98

Read `look_applied.world_beauty.clouds.layers[0].cloud_type_source` (expect
`switch`), `cloud_type_applied`, `cover_basis` and `plan.fields_source` in round 98's
render.json; round 99 must record `hidden_layers[0]` and draw no cloud. A plan-fed
render (`cloud_type_source: plan`) needs step 5; until then `plan.fields_source` says
none. Tests: `tests/test_cloud_type.py` (the C++ laws compiled and compared with the
Python, the header defaults, the parser, the precedence table, the record keys, the
untouched measure `Build`, the single beauty call site). API: `scripts/check_bridge_api.sh`
gains `SetVisibleInRealTimeSkyCaptures` and `SceneComponent::SetVisibility`.

### Sky step 3 (2026-11-15): march and sky-LUT quality, tiered, recorded, restored

Step 3 of the owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md; design
docs/visual/XPLANE_SKY_DESIGN.md §5, with the "Built" note there for where the code
proved it wrong). Nothing here was rendered.

**What it draws.** Nothing new on the render laptop by default. Under `-quality=beauty`,
`FFlightSimWorldBeauty::ApplyClouds` (FlightSimClouds.cpp) resolves a march TIER
(`FlightSimWorldPure::CloudMarchFor`) and applies the tier's cloud component march
(`CloudMarch`: `SetViewSampleCountScale`, `SetShadowViewSampleCountScale`,
`SetTracingMaxDistance`; the per-layer `SetShadowTracingDistance` is unchanged) and the
tier's thirteen renderer cvars (`CloudCvar` / `CloudCvarName`), each set at code priority
through `SetWorldCvar`, saved once (`SaveWorldCvar`, `WorldCvarsBefore`, the fog-on-all-pixel
cvar now saved the same way) and put back at the commandlet's teardown by `RestoreCvars`,
which walks the array in reverse. The tiers (Python twins `world_beauty.CLOUD_MARCH`,
`CLOUD_CVARS`, `CLOUD_CVAR_NAMES`, `ENGINE_CLOUD_CVAR_DEFAULTS`, `CINEMATIC_SKY_CVARS`;
`tests/test_sky_step3_cvars.py` compiles the C++ and compares):

| field (record key) | cvar | constrained (the laptop; in force today) | probe | discrete |
|---|---|---|---|---|
| march: view x96 / shadow x10 / trace | component setters | 2 / 1 / 80 km (192, 10) | 3 / 2 / 80 km (288, 20) | 8 / 8 / 50 km (768, 80: the caps) |
| view_ray_sample_max | `r.VolumetricCloud.ViewRaySampleMaxCount` | 768 | 768 | 768 |
| shadow_ray_sample_max | `r.VolumetricCloud.Shadow.ViewRaySampleMaxCount` | 80 | 80 | 80 |
| distance_to_sample_max_km | `r.VolumetricCloud.DistanceToSampleMaxCount` | 15 | **8** | 8 |
| sample_min_count | `r.VolumetricCloud.SampleMinCount` | 2 | 2 | 2 |
| shadowmap_ray_sample_max | `r.VolumetricCloud.ShadowMap.RaySampleMaxCount` | 128 | 128 | 256 |
| shadowmap_max_resolution | `r.VolumetricCloud.ShadowMap.MaxResolution` | 2048 | 2048 | 4096 |
| skyao_trace_samples | `r.VolumetricCloud.SkyAO.TraceSampleCount` | 10 | 10 | 20 |
| ap_lut_depth_km | `r.SkyAtmosphere.AerialPerspectiveLUT.Depth` | 96 | 96 | 160 |
| ap_lut_depth_resolution | `r.SkyAtmosphere.AerialPerspectiveLUT.DepthResolution` | 32 (Cinematic) | 32 | 64 |
| ap_lut_width | `r.SkyAtmosphere.AerialPerspectiveLUT.Width` | 32 | 32 | 64 |
| transmittance_lut_samples | `r.SkyAtmosphere.TransmittanceLUT.SampleCount` | 30 (Cinematic) | 30 | 40 |
| multiscatter_lut_samples | `r.SkyAtmosphere.MultiScatteringLUT.SampleCount` | 20 (Cinematic) | 20 | 30 |
| sky_distance_to_sample_max_km | `r.SkyAtmosphere.DistanceToSampleCountMax` | 150 | 150 | 100 |

The CONSTRAINED row (the Intel iGPU, D3D11 SM5: `CloudConstrainedGpu`) is exactly what
every beauty render has drawn with since the beauty path existed: the engine's
registration default (UE 5.7 VolumetricCloudRendering.cpp, SkyAtmosphereRendering.cpp;
`scripts/check_bridge_api.sh` pins each line with its default) where the Cinematic
scalability group is silent, and that group's value where it speaks
(BaseScalability.ini `[EffectsQuality@Cine]`, applied by the render path AFTER this lane
at scalability priority, which cannot lower a code-priority set). Setting it is a recorded
no-op: the march row is still ef361bd6's (192 / 10 / 80, the r87 pin), and the sky-light
capture's sample caps (`SetReflectionViewSampleCountScale`,
`r.VolumetricCloud.ReflectionRaySampleMaxCount`) remain the commandlet's to set. The PROBE
row is the constrained class's opt-in raise: 288 view / 20 shadow samples and
`DistanceToSampleMaxCount` 8 km (the engine spreads the sample cap over that distance,
samples = cap x saturate(in-layer path / distance), so a short in-layer path gets up to
twice the samples). That cvar is NOT confined to the main view: UE 5.7
VolumetricCloudRendering.cpp sets `CloudGlobalShaderParams.InvDistanceToSampleCountMax`
once, from it, for every trace, and its `bIsReflectionRendering` block re-derives only
`SampleCountMax` / `ShadowSampleCountMax` (the commandlet's reflection caps), so the probe
also lengthens the sky-light capture's march (up to 15/8 x per short in-layer path, under
those caps) in the submission that hung r87 (`887a0006`); the Windows TDR is the probe's
pass or fail. Pinned: `tests/test_sky_step3_cvars.py` reads the engine's reflection block
and `scripts/check_bridge_api.sh` the `InvDistanceToSampleCountMax` line (repair round 1:
the first record said the capture was "not this table's", which was false for the probe
and discrete tiers; no value changed). The DISCRETE row is the offline quality for a
discrete GPU, of which the project has none: set for one, never rendered.

**The switch.** `-cloud-march=auto|constrained|discrete|probe` (auto by default: the GPU
class, as before this step); a named tier is the owner's measurement on any GPU; another
word refuses `world_beauty.clouds: -cloud-march=...`. Registered in core/config_surface.py
(`render_switches`) and the catalogue's `world_beauty.clouds` hint.

**Record** (`look_applied.world_beauty.clouds.march`, beside the existing `path`,
`view_samples_max`, `shadow_samples`, `banding_basis`): `tier`, `switch`, `tier_basis`,
`cvars {name: [before, read_back]}`, `cvars_skipped[]` ("skipped: <name> is not
registered"), `cvar_fields {field: name}`, `cvars_basis`, `render_path_owned[]` (the
commandlet's nine sky and cloud cvars, named, never set here: their final values are
`render_settings.beauty_path.read_back`), `render_path_owned_basis`. `before` is read when
this lane runs, ahead of the Cinematic pass, so for the three Cinematic fields it is the
registration default (16 / 10 / 15) and `read_back` the value the captures draw with.
`distant_clouds.volumetric_trace` gains `march_tier` and `distance_to_sample_max_km`.
One owner per cvar (the commandlet's ledger names the world lane's new set):
`tests/test_sky_step3_cvars.py` reads the sun-shafts, hero-lighting and render-path tables.

**Unchanged.** Measure renders (FlightSimSky.cpp, FlightSimVisualScene.cpp,
FlightSimWeather.cpp name none of these cvars; pinned); labels (process-wide cvars, but no
label capture draws cloud, fog or atmosphere); dataset formats; flight dynamics; exposure
(plan.py untouched); the constrained march row and shadow march (`{2.0, 1.0, 80.0}`, 6 km:
the r87 pins in tests/test_world_beauty.py and tests/test_cloud_jitter_blue_noise.py hold);
the commandlet's `SetBeautyCvar` set (the jitter test's pin); `MultiScatteringFactor` still
off on the constrained class (step 4's `-sky-multi-scatter=`); the materials (no rebuild).

**UNCALIBRATED.** Every discrete and probe value, the probe march row, the 8 km distance:
look and cost values, never from a frame.

**UNMEASURED.** Everything above: that a Windows build compiles it; that the constrained
row is the no-op it claims; whether the probe row renders on the iGPU or stalls it
(887a0006); every discrete value (no discrete GPU). The exact Windows measurements, with
`FLIGHTSIM_SKY=physical` set in the shell:

    .\scripts\visual_fix_round.ps1 -Round 100 -Scenes 3 -CompareWith 95
    .\scripts\visual_fix_round.ps1 -Round 101 -Scenes 3 -Switches "-cloud-march=probe" -CompareWith 100
    .\scripts\visual_fix_round.ps1 -Round 102 -Scenes 3 -Switches "-cloud-type=cumulus -cloud-march=probe" -CompareWith 98

Round 100 is the no-op check: the compare against round 95 must report no change beyond
the still's own noise, and `march.tier` must read `integrated` with every `cvars` pair's
`read_back` equal to the table above; a structured difference means the constrained row is
not the laptop's own values. Round 101 is the probe: pass = the log has no `887a0006` and
the frame completes; read ROUND.json's wall seconds against round 100's and
`march.cvars["r.VolumetricCloud.DistanceToSampleMaxCount"]` (expect `["15", "8"]`).
Round 102 is the design's probe-with-cumulus compare against step 2's round 98. If round
101 renders clean, step 4's rounds may carry `-cloud-march=probe`; a one-line follow-up
would then move the constrained row (both tests' pins updated with the measured reason).
Tests: `tests/test_sky_step3_cvars.py`; `tests/test_world_beauty.py` (the march test gains
the probe row, its docstring says why). API: `scripts/check_bridge_api.sh` pins the
thirteen registrations with their defaults, the three Cinematic lines and
`ECVF_SetByCode` in ConsoleManager.cpp.

### Sky step 5 (2026-11-15): the sky plan's cloud fields, the altocumulus row, ERA5 cloud cover

Step 5 of the owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md; design
docs/visual/XPLANE_SKY_DESIGN.md §7, with the "Built" note there for where the code
narrowed it). Nothing here was rendered.

**What it draws.** Nothing by itself. `core/sky/plan.py plan_sky` now writes the
BEAUTY-ONLY cloud fields step 2's host reads (`FFlightSimSkyPlan::Load`, `FFlightSimWorldBeauty::ApplyClouds`
under `-quality=beauty`) into `sky.json` "clouds", beside the unchanged `enabled` /
`bottom_km` / `thickness_km` / `basis` (the measure host reads only those, so a measure
render is byte-identical; pinned): `cloud_type` (clear | cumulus | stratocumulus |
altocumulus | cirrus | overcast | nimbostratus), `coverage` 0..1, `density` 1.0 and
`detail` 1.0 (multipliers of the type's `world_beauty.CLOUDS` row: one source of truth
per type), `cirrus_coverage` (step 6 draws it), `coverage_source`, `cover_inputs`
`{low, mid, high, total}` or null, `cloud_type_basis` (the threshold that fired),
`volumetric_row`, `seed` and `seed_source` (the spec's seed, else CRC-32 of the instant,
place and altitude), `march_tier` "auto" (the step 3 cvar set the plan asks for) and
`march_tier_basis`, `fields_basis`. Pure: same inputs, same bytes (`core/sky/clouds.py`).

**Where the type comes from.** With a `weather_date` over a real place and no SAMPLED
cloud cover, the web app (`webapp/runs.py historical_cloud_cover`, called by
`write_sky_plan`) fetches `core/environment/era5.py fetch_reanalysis_cloud_cover`: the
ERA5 archive's hourly `cloud_cover_low/mid/high` (percent -> fractions) at the plan
INSTANT's UTC date AND UTC hour (`instant_utc`; the wind keeps its noon convention), source
string stated. Not `weather_date` at that hour: `weather_date` is the spec's LOCAL date, and
the instant is the next UTC day for a local evening west of Greenwich (20:00 at New York on
2024-01-15 is 2024-01-16T00:56Z, so the archive is asked for 2024-01-16 00Z) and the previous
one for a local morning east of it (02:00 at Tokyo is 2024-01-14T16:41Z). The first cut
passed the hour alone and fetched `weather_date` at it, 24 h off in every such case; repair
round 1 passes the instant and `coverage_source` stamps the UTC day actually fetched
(`..., 2024-01-16T00Z, ...`); pinned in `tests/test_webapp.py` (New York and San Francisco
evenings, a Tokyo morning) and `tests/test_sky_clouds.py`. The type
law (`core/sky/clouds.py cloud_type_from_cover`, thresholds UNCALIBRATED): storm spec ->
nimbostratus 0.98; `max(low, mid) >= 0.85` -> overcast; `low >= 0.5` -> stratocumulus;
`mid >= 0.3 and mid > low` -> altocumulus; `low >= 0.1` -> cumulus; `high >= 0.2` ->
cirrus (no volumetric layer); else clear. Without a date, offline, over a synthesised
ridge, or when the policy drew a cover (the card's layer stands above the plan in the
host anyway): the stated default `cumulus` at the row's 0.35 (`nimbostratus` 0.98 for a
storm), recorded under `coverage_source` as `default (<reason>): CLOUDS[<type>].default_cover`.
The default plan therefore draws round 95's frame by construction. Clouds are VISUAL ONLY:
an unreachable archive never refuses the run and never edits the spec (unlike the wind).
The web app's weather stays ON by default; nothing became opt-in. `run.conditions["sky"]`
names the type, cover and source.

**The altocumulus row** (design D3): `CLOUDS["altocumulus"]` =
{extinction 0.03 /m, shape 1.2 km, detail 0.12 km, erosion 0.4, bottom softness 0.15, top
rounding 0.5, coverage contrast 1.1, default cover 0.5}, `CLOUD_MAX_THICKNESS_M` 900 m,
appended at index 4 on both sides (`CloudAltocumulus = 4`, `CloudCount = 5`, `CloudName`,
`CloudDefault`, `CloudMaxThicknessM`; every earlier index and overrides file stands;
`-world-beauty-overrides=` may name the row). `CloudShapeForPlanType` case 3 now returns it
(step 2 drew stratocumulus until the row existed). `select_cloud` never picks it: the
plan's mid-level law does. UNCALIBRATED, never rendered.

**The march tier, plan -> host.** `FFlightSimSkyPlan::Load` reads `march_tier` with
`TryGetStringField`; `FFlightSimWorldBeauty::Build` resolves the word in force
(`FlightSimWorldPure::CloudMarchWordInForce`, twin `world_beauty.cloud_march_word`):
`-cloud-march=<word other than auto>` > the plan's `march_tier` when it is a known word >
`auto` (the GPU class). The plan writes "auto", so the default render is unchanged by
construction; a hand-edited `sky.json` may ask for `probe`. Recorded under
`look_applied.world_beauty.clouds.march`: `switch` (the word in force), `switch_given`,
`plan_march_tier`, `word_source`; `clouds.plan.march_tier`.

**Unchanged.** `SKY_VERSION` 1 == `SkySupportedVersion` 1 (additive keys, TryGet*; pinned on
both sides); `FFlightSimSky::Build` (measure); the exposure block (pinned byte-identical with
and without a cover); `relight` (the clouds block survives it byte-identical); `enabled` /
`bottom_km` (>= 1 km above the flight; 1.2 km floor in storms) / `thickness_km` for every
positional caller (pinned literals); the c641a8c4 beauty exception that lowers a DEFAULT
cumulus layer below a high cruise (the camera stays clear); labels, dataset formats, flight
dynamics, materials (no rebuild: no shader or graph change); the step 2 and step 3 pins.

**UNCALIBRATED.** Every type-law threshold (the two Open-Meteo endpoints disagree hour by
hour on the level fractions), the altocumulus row and its 900 m cap, the default cover.

**UNMEASURED.** Everything above: that a Windows build compiles the row and the march-word
block; that an altocumulus plan draws a translucent mid-level sheet rather than a second
stratocumulus; that the ERA5 fractions for a dated spec reproduce that day's sky (never
claimed). The exact Windows measurements, with `FLIGHTSIM_SKY=physical` set in the shell:

    .\scripts\visual_fix_round.ps1 -Round 104 -Scenes 3 -Switches "-cloud-type=altocumulus" -CompareWith 98
    .\scripts\visual_fix_round.ps1 -Round 105 -Scenes 3 -Switches "-cloud-type=stratocumulus" -CompareWith 104

Round 104 draws the new row under the switch (read `look_applied.world_beauty.clouds.layers[0].cloud_type_applied`
== `altocumulus`, `shape` == `altocumulus`); round 105 is the A/B against the row it used
to draw. Both rounds BYPASS this step's own path (`-cloud-type=` stands above the plan), so
the plan path, ERA5 -> `sky.json` -> `FFlightSimSkyPlan::Load` -> `ApplyClouds`, has its
own measurement. `scripts/run_test_scenarios.py` has no dated scene (adding one moves the
pinned scene count and a swarm lane's "scene 16" wording, so none was added here); the
exact command is the web app's own, the same `/compile` and `/run` calls
`run_test_scenarios.py` makes, from `C:\Users\kanth\flightsim` in Windows PowerShell 5.1
with the app started as `visual_fix_round.ps1` starts it:

    $env:FLIGHTSIM_SKY = "physical"; $env:FLIGHTSIM_RENDER_QUALITY = "beauty"; $env:FLIGHTSIM_BEAUTY_POST = "on"
    Start-Process .venv\Scripts\python.exe -ArgumentList "-m","uvicorn","webapp.server:app","--port","8008" -WindowStyle Hidden
    $c = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8008/compile -ContentType "application/json" -Body (@{ prompt = "chase view of the 747 over new york at 9000 m at 14:00 on 2024-01-15 for 6 seconds"; compiler = "regex"; still = $true } | ConvertTo-Json)
    $r = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8008/run -ContentType "application/json" -Body (@{ spec = $c.spec.dict; provenance = @{ compiler = "regex" } } | ConvertTo-Json -Depth 32)
    do { Start-Sleep 10; $s = Invoke-RestMethod http://127.0.0.1:8008/runs/$($r.run_id) } until ($s.status -in "done","failed")
    Get-Content runs\webapp\$($r.run_id)\sky.json | ConvertFrom-Json | % { $_.instant_utc; $_.clouds.cloud_type; $_.clouds.coverage; $_.clouds.coverage_source }
    (Get-Content runs\webapp\$($r.run_id)\frames\render.json | ConvertFrom-Json).look_applied.world_beauty.clouds | % { $_.plan.cloud_type; $_.layers[0].cloud_type_source; $_.march.word_source }

(A 409 `terrain.unbaked` answer from `/run` means the New York bake is absent: `POST /bake`
with the `latitude` / `longitude` it names, then `POST /run` again, as
`run_test_scenarios.py run_spec` does. Rounds 1-95 rendered scene 3 over New York, so the
bake is normally present.) Read: `sky.json` `instant_utc` `2024-01-15T18:56:...Z`,
`clouds.coverage_source` starting `ERA5` (online) or `default (fetch failed: ...)`
(offline; the frame is then round 95's cumulus by construction), `clouds.cloud_type` one
of the seven words; `render.json` `look_applied.world_beauty.clouds.plan.cloud_type` ==
`sky.json`'s, `layers[0].cloud_type_source` == `plan`, `march.word_source` == `default auto`.
14:00 is daylight for the frame; to see the UTC-day rule itself no render is needed: the
same lines with `at 20:00` write `instant_utc` `2024-01-16T00:56:...Z` and a
`coverage_source` stamped `2024-01-16T00Z` (the old code stamped `2024-01-15T00Z`).
What a correct frame looks like is UNMEASURED; this measures only that the fetched type
reaches the host. Tests:
`tests/test_sky_clouds.py` (determinism, ranges, defaults, the type-law table including
every threshold boundary, measure byte-identity, SKY_VERSION, the provider with a stubbed
archive, the row on both sides by regex and g++, the march word law by g++, these docs);
`tests/test_webapp.py` (stubbed fetch: applied and sourced, sampled cover wins, unreachable
archive records the default, undated and synthesised specs never fetch);
`tests/test_cloud_type.py` and `tests/test_world_beauty.py` (the altocumulus pins and the
fifth row, reasons in their docstrings). API: `scripts/check_bridge_api.sh` (no new engine
symbol).

### Sky step 7 (2026-11-15): tests and the suite

Step 7 of the owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md; design
docs/visual/XPLANE_SKY_DESIGN.md §9, with the "Built" note there). Tests only: no shader,
material, C++ or Python-under-test change, so nothing here draws and nothing here was
rendered.

**What the branch carried.** Steps 0, 2, 3 and 5. Steps 1, 4 and 6 were on their own
branches and not yet merged into claude/xplane-sky, so their shader / material / atmosphere
/ cirrus pins are not in this step (they land with those steps), and the design's "tests
that legitimately move" entries for them did not apply. Step 7 itself moved no test; the
only existing test moved on the branch is test_world_beauty.py 784
(`test_the_cloud_march_and_the_sky_are_the_python_ones`), by steps 3 and 5 with the reasons
in their docstrings (design §9, Built note, which also records why the list's 170 / 629 /
640 and 454 did not need to move). No test was weakened, skipped or deleted.

**What `tests/test_sky_step7_suite.py` pins** (beyond test_sky_clouds.py, test_cloud_type.py
and test_sky_step3_cvars.py, which landed with their steps):
- the plan's "clouds" block as a GOLDEN, byte for byte and in key order (the web app
  writes `json.dumps(plan, indent=1)` without `sort_keys`, so the order is part of
  `sky.json`), for one covered dated input and for the undated default (round 95's frame
  by construction); ASCII-clean;
- the derived seed as a CRC-32 literal (864852549 for the pinned inputs), the 6-decimal /
  0.1 m quantisation, `seed=0` recorded as the spec's seed, a float seed stored as int;
- EV100 unchanged by every cloud input: by source order in `core/sky/plan.py` (the
  exposure dict precedes the clouds block, `plan_cloud_block` takes exactly its nine
  keywords, `core/sky/clouds.py` never names the exposure) and by value over a grid of
  covers, notes and seeds; the host records `exposure_sees_plan_clouds: false`;
- four-place rounding of the cover inputs, the coverage equal to the level that named the
  type, `total` recorded but never deciding, the caller's dict untouched, a missing level
  read as 0, NaN or a non-number refused;
- the ERA5 provider: percent outside 0..100 clamped, a negative hour and a missing hourly
  field refused by name (`WeatherUnavailableError`), the dict carrying every key the plan
  reads plus `source` / `date` / `hour_utc`, the field order the archive is asked for;
- render.json: every "clouds" key `FFlightSimSkyPlan::Load` reads is recorded by
  `ApplyClouds` under `look_applied.world_beauty.clouds.plan`, whose key set is exactly
  `fields_source, cloud_type, cloud_type_known, coverage, density, detail, cirrus_coverage,
  coverage_source, seed, seed_stated, march_tier, card_seed, seed_matches_card,
  cloud_type_switch, precedence, owner_parameters, exposure_sees_plan_clouds, measure_path,
  calibration`; the web app's `run.conditions["sky"]` names the type, cover and source and
  `write_sky_plan` passes the spec's seed and the fetched cover;
- `FFlightSimWeather::VerifyCloudMaterials`: `M_FlightSimCloudLayers` is built to pass it
  (MD_VOLUME, `used_with_volumetric_cloud`, additive, the multiple-scattering node) at the
  path the host loads; the commandlet runs the check AFTER `WorldBeauty.Build` (it sees the
  swapped material) and before the warm-up captures, records every line under
  `look_applied.cloud_materials` and refuses by name (`clouds.material`) on a bad material;
  the interactive host runs it before its first frame; a MISSING beauty material is not a
  refusal: `ApplyClouds` keeps the stock material, records "did not load" and returns before
  any `SetMaterial`; the check's order is the engine's (no material = draws nothing; Volume
  domain; usage flag; compile errors; shader map).

**Suite results on the Mac (code-level only; never a visual result).** Targeted set
first (test_sky_clouds, test_cloud_type, test_sky_step3_cvars, test_world_beauty, test_sky,
test_cloud_billow, test_cloud_tiers, test_distant_clouds, test_cloud_jitter_blue_noise,
test_cpp_brace_balance, test_render_json_contract, test_ue_weather_source,
test_check_bridge_api): 341 passed. Full suite, `-n auto`, first run: 1 failed
(`tests/test_mutation_targets.py`: step 5's `historical_cloud_cover` repeated the wind's
line `if pick_scene(spec)["key"] in SYNTHESISED_SCENE_KEYS:`, so mutation guard 318 had two
targets; fixed in step 5's commit by spelling the new line with a local, behaviour
unchanged). Full suite after the fix: 5831 passed, 14 skipped, 0 failed (7 min 03 s);
re-run on the committed tree after the repair-2 amend: 5831 passed, 14 skipped, 0 failed
(7 min 05 s, exit 0), with
`python -m pytest -q -o addopts="" -m "not gate" -p no:cacheprovider -W ignore -n auto tests/`.
That `-o addopts=""` matters: pytest.ini already carries `-q -m "not gate"`, so the plain
`-q` command runs at `-qq` and prints only dots, no `N passed` line; two reviewers counting
that dot stream on the same tree reported 5837 passed / 15 skipped. The passed figure is
explained by the tree: `-m "not gate"` deselects exactly six tests
(tests/test_phase3_gates.py::test_gate_A..F; `pytest --collect-only -q -o addopts="" -m "not
gate" tests/` -> 5844/5850 collected, 6 deselected, and `-m gate` -> 6 passed), so 5837 is a
run WITHOUT the gate filter: `-o addopts=""` drops pytest.ini's filter unless `-m "not gate"`
is given again, and the full suite re-run that way on this tree prints `5837 passed, 14
skipped in 429.79s`, exit 0. The skipped figure is not explained: the summary line says 14
with and without the gate filter, and the one collection-time skip the gate run also reports
(tests/test_sun_vs_spa.py:15, pvlib not installed) is already inside the 14 under either
filter, so the reviewers' 15 is a dot-stream count this tree does not reproduce. Use the
summary-line figure (5831 / 14 with the project's gate filter, 5837 / 14 without it).
`bash scripts/check_bridge_api.sh`: API surface matches (it is not a
compile). No existing test was weakened, skipped or deleted.

**UNMEASURED.** Every pin above is a source or Python pin; none says what a frame looks
like. The Windows commands that would measure the steps these tests guard are the ones in
"Sky step 2", "Sky step 3" and "Sky step 5" above, with `FLIGHTSIM_SKY=physical` in the
shell. Step 7 adds NO round of its own: the plan path end to end is read off step 5's
round 104 (the same command as in "Sky step 5", repeated here so the reader does not have
to scroll; render it once, not twice):

    .\scripts\visual_fix_round.ps1 -Round 104 -Scenes 3 -Switches "-cloud-type=altocumulus" -CompareWith 98

then, in that round's output, read `sky.json` `clouds` (it must equal the golden's shape:
the same keys in the same order), `look_applied.world_beauty.clouds.plan` (the nineteen
keys above) and `look_applied.cloud_materials` (one line per cloud component, each ending
`compiled`). If round 104 has already run for step 5, read these from its existing output.

### Sky step 8 (2026-11-15): the owner's four-frame verify path

Step 8 of the owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md; design
docs/visual/XPLANE_SKY_DESIGN.md §10, with the "Built" note there). Scripts and docs
only: no shader, material, C++ or plan change, so nothing here draws, no render.json field
is added (the sheet READS step 2's and step 3's records), and nothing here was rendered.

**What it does.** `scripts/sky_compare_round.ps1 -Round N -Scene S -CompareWith M
[-Switches "<extra>"] [-NoPush]` (Windows PowerShell 5.1, run from C:\Users\kanth\flightsim
like visual_fix_round.ps1) first checks the branch (below), sets `FLIGHTSIM_SKY=physical` when
the shell has not, then runs
`.\scripts\visual_fix_round.ps1 -Round N+k -Scenes S -Switches "-cloud-type=<word> <extra>"
-CompareWith M -Branch B` for k = 0..3 over the words clear, cumulus, stratocumulus, overcast: four
fixed frames of ONE scene at the SAME camera (the pinned spec in runs\visual\specs\NN.json
replays), each its own round folder `docs/visual/round_<N+k>/` with ROUND.json and the pixel
report against round M, pushed to vis-windows as every round is. Then
`scripts/sky_contact_sheet.py --rounds N,N+1,N+2,N+3 --scene S --old M` (numpy + PIL) writes
`docs/visual/sky_compare/round_<N>/sheet.jpg` (row 1: round M's frame of the scene, the
"old look"; row 2: the four, each captioned with the word REQUESTED, the shape the host says
it APPLIED from `look_applied.world_beauty.clouds.layers[0].cloud_type_applied` /
`cloud_type_source` (`clear` leaves the layer in `hidden_layers`: "no layer", a match),
`MISMATCH` when they disagree, `applied unknown` when the record names no shape at all (a host
before sky step 2, `-beauty-clouds=engine`, a cloud material that did not load: FlightSimClouds.cpp's
early returns write only `clouds.drawn`), `-cloud-type= not parsed` when the record does not
carry the word asked in `clouds.plan.cloud_type_switch` (the switch string the host parsed),
`clouds.march.tier` and `atmosphere.multi_scattering_factor`) and `compare.json` (per tile:
those fields plus `switch_seen` and the `root` the frame came from, visual_compare's
mean_abs_change / moved_share / mean luma against the old frame, frame_metrics' blank / clipped /
crushed health with its UNCALIBRATED thresholds, the round's commit and switches,
`FLIGHTSIM_SKY`, round M's `old_commit` / `old_switches` / `old_root`; the lists `mismatches`,
`unknown`, `switch_not_seen`, `no_record`, `missing` and the `reading_rule`). Round folders live
on branch vis-windows, so every one (round M included) is looked up under `docs/visual` and then
`runs/vis-windows-wt/docs/visual`, the two places visual_fix_round.ps1 step 4b reads, in its
order. A missing frame is a `MISSING` tile and a row with `found: false`, never a gap. A report,
never a gate. docs/visual/sky_compare/README.md has the location and how to read it.

**Which code the frames render (the precondition).** visual_fix_round.ps1 step 1 checks out a
branch and fast-forwards it FROM ORIGIN before every round; the branch was hard-coded
`claude/vibrant-gauss-olema4` and is now its `-Branch` parameter with that default (every
existing call unchanged). sky_compare_round.ps1 passes `-Branch` (default: the branch of the
current checkout) and refuses by name, `compare.wrong_branch`, before round 1 unless
`origin/<branch>` carries `scripts/sky_contact_sheet.py` and `PLAN_CLOUD_SHAPES` in
`core/scene/world_beauty.py`. So the four frames render the sky steps ONLY after
claude/xplane-sky has been pushed (run from that checkout), or merged into
`claude/vibrant-gauss-olema4` and pushed; until then the laptop would have rendered fbcbaa5d,
where `-cloud-type=` is not parsed and silently ignored, and the four frames would be one look.
Nothing was pushed when this was written. The ps1 also refuses a round number whose folder
already exists under either root (`compare.round_exists`: visual_fix_round.ps1 would overwrite it
in vis-windows) and a `-Switches` value carrying `-cloud-type=` (`compare.switch_dup`:
FParse::Value takes the first).

**The switch.** None new to the host: `-cloud-type=` (step 2) does the work; `-Switches` passes
any extra switch to all four rounds (an A/B set is its own `-Round`); `-Branch` (new on both
scripts) names the branch rendered. `-Scene` defaults to 3 (the A320
over New York, 600 m, 18 mm: the design's primary camera, bellies and rims against the sky);
13 (the 747 at 10 km over the ocean) is the secondary. `-CompareWith` is required and refused
by name when missing (`compare.no_old`).

**Tested on the Mac (code only).** tests/test_sky_contact_sheet.py: synthetic frames and
render.json stubs (sheet size, every row including a missing round, clear as a match, a
MISMATCH, an fbcbaa5d-shaped record and an engine-mode record as `unknown` / `switch_not_seen`
and never a match, a parsed-but-different word, a frame without a record, the old frame only in
the fallback root, the flat frames/render.json, a taller old frame, the pixel and health
numbers, byte-identical re-runs, the CLI and its refusals); pins of the four words against
`world_beauty.PLAN_CLOUD_TYPES`, of the layout constants by value, of the render.json keys the
sheet reads against the C++ `TEXT(...)` writers and the `cloud-type=` parse, of both ps1s'
branch handling, calls, refusals and 5.1 guards, of the round numbers against steps 2/3/5's, and
of these docs. tests/test_powershell_scripts.py lints both ps1s' syntax. The PowerShell itself
was not run (no PowerShell here). Targeted set (test_sky_contact_sheet, test_powershell_scripts,
test_platform, test_frame_metrics, test_visual_compare, test_stress_ladder): 197 passed, 0 failed, exit 0.
Full suite on the committed tree, `-o addopts="" -m "not gate" -n auto`: 5859 passed, 14 skipped, 0 failed (7 min 01 s, exit 0; the repaired step's new tests on top of step 7's).
`bash scripts/check_bridge_api.sh`: API surface matches (not a compile). No existing test was
weakened, skipped or deleted.

**UNMEASURED.** Every frame; both ps1s end to end (the `-Branch` passthrough included);
whether round 95's #03 and #13 frames are in the laptop's `docs\visual\round_95` or
`runs\vis-windows-wt\docs\visual\round_95` (the old look, the two places the sheet reads;
`-CompareWith` another round if neither has it). Steps 1, 4 and 6 of the brief are not on
claude/xplane-sky yet, so the design's rounds 97, 102 and 104 (their switches) do not apply until
they merge; the compare itself does. The round numbers are 110-113 (scene 3) and 115-118 (scene
13) because steps 2, 3 and 5 above reserved 98-105. The exact Windows commands, from
C:\Users\kanth\flightsim, AFTER claude/xplane-sky is pushed (run from its checkout) or merged
into claude/vibrant-gauss-olema4 and pushed (run from that checkout, or add `-Branch
claude/vibrant-gauss-olema4`); run before that, the script refuses `compare.wrong_branch` and
renders nothing:

    $env:FLIGHTSIM_SKY = "physical"
    .\scripts\sky_compare_round.ps1 -Round 110 -Scene 3 -CompareWith 95
    .\scripts\sky_compare_round.ps1 -Round 115 -Scene 13 -CompareWith 95

then open `docs\visual\sky_compare\round_110\sheet.jpg` and `round_115\sheet.jpg`, read
`compare.json`: `mismatches`, `unknown`, `switch_not_seen`, `no_record` and `missing` must ALL
be empty and every tile's `applied` must be a shape word or "no layer" (each word drew its own
shape on a host that saw the switch; `unknown` or `switch_not_seen` non-empty means the host
never parsed `-cloud-type=` and the four frames are one look), and judge the four against row 1
and the reference photo. Frames: `docs/visual/round_110..113/03_*.jpg` and
`docs/visual/round_115..118/13_*.jpg`. On scene 13 the stratocumulus and overcast tiles show a
deck above the 747 (the plan layer keeps bottom = AGL + 1 km; only an unstated cumulus layer is
lowered, c641a8c4): the rule, not a defect.
