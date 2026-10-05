# Logic reports

Decompiled listings of the local simulator's binary, cut by subsystem: for
each report, `functions.txt` (one line per function: address, two spaces,
demangled name) and `code.c` (the decompiled bodies, each headed
`// <address>  <name>`). The reports were cut by NAME MATCH on the binary's
symbols, so each carries unrelated hits beside the logic it is named for
(the lighting dump matched "flight" on "light"; the physics dump matched
G1000/GNS430 page classes). `core/xplane/physical.py` (`REPORTS`) names,
per report, what it governs, the committed render assets its code reads
(`assets/physical_renders/Resources/`), the terrain-drape roles those
feed, the functions worth reading first and the caveat.

| report | governs | render assets | drape roles |
| --- | --- | --- | --- |
| `terrain_ocean` | DSF terrain loading, the terrain and water shaders, beaches, the per-location season table | `bitmaps/world/water`, `bitmaps/Snow Cover`, `bitmaps/Earth Orbit Textures`, `bitmaps/earth1/2` | valley, scrub, rock, cliff, snow, water |
| `lighting` | sky-colour and ambient lookups, HDR / exposure fusion, ground lights | `brdf_lookup`, `bitmaps/world/lites`, `bitmaps/world/moon*` (+ the sky tables in `assets/xplane/lighting/`) | water (colour) |
| `render_quality` | terrain shader setup, weather decals, clouds, volumetric fog, FSR, overlays | `shaders`, `effects`, `bitmaps/world/{clouds,weather,overlays,maps}` | snow |
| `physics` | atmosphere and fog parameters, rain-on-surface forces, ground contact | none (code only) | - |

## What the bodies actually contain (read 2026-10-05)

Each `code.c` holds exactly 400 decompiled bodies; `functions.txt` lists
thousands of names WITHOUT bodies (887 / 5,598 / 4,526 / 3,290 lines).
Every body in the groups below was read in full by a reader agent and
each extracted rule was then handed to an adversarial second reader
(`tests` were not run; the readers were read-only).

* **terrain_ocean (44,009 lines)** is the one report with build logic:
  the DSF loader (`DSF_AcceptTerrainDef` and its async twin,
  `DSF_AcceptPolygonDef`, `DSF_AcceptProperty`, `DSF_AcceptRasterDef`,
  `read_DSF_file`, `return_latlon_str_dsf`), the CPU side of the water
  shader (`REN_degree::create_water_shader`, the mixdown graph, the
  water quadtree culling, `sim_objects::is_water` / `xyz_if_open_ocean`,
  `flt_class::drag_point_in_water`), beach placement by season, the DEM
  lookups (`ATCUtilsGetTerrainAltForPoint`, `flt_class::terrain_ele_cg`),
  the terrain grid / LOD bias, and the 2D map terrain layer
  (`Map::terrain_layer_desktop`, `Map::terrain_tile`), which is where the
  Earth Orbit Textures are consumed.
* **lighting (23,484 lines)** holds NO lighting logic: its three
  non-accessor bodies are the loading screen (`plot_init_lights_v11`,
  `MACIBM_push_v11_init_lights_screen` -- "init lights" is the loading
  screen's name) and a `flight_spec` copy constructor. The sky /
  ambient / exposure / ground-light functions it lists
  (`scattering_state::compute_sky_ambient`, `sky_stat::get_for_now`,
  `get_sun_position`, `OGL_build_sky_*`, `tonemap_*`, `OBJ_lights_*`)
  are names only; two relatives do have bodies in OTHER reports
  (`scattering_state::render_atmosphere_sky` in physics -- it binds the
  sky draw's inputs and shows no table lookup -- and the exposure-fusion
  pass in render_quality).
* **render_quality (21,284 lines)**: the HDR/tonemap constant block
  (`OGL_hdr_setup_shader`: bloom strength 2^s_bloom1, mip range), the
  exposure-fusion block (EV100 multiplier, Rec.709 luma, sigma^2), the
  FSR scale table, the rain / droplet / debug shader interfaces.
  `OGL_terrain_shader_*` and `REN_degree_dem_table::total_season_for_
  location` are names only.
* **physics (44,397 lines)**: `atmo_params::set_fog_params`
  (Koschmieder extinction split two ways), `set_turbidity` (Mie linear
  in turbidity - 1, albedo split), `scattering_state::render_atmosphere_
  sky` (the sky draw's inputs), the rain-on-surface force field and
  `flt_gear_class::handle_contact_tire` (tire footprint rays, surface
  type from the centre ray, two-stage spring, slip-ratio friction).
  The surface-class -> friction table (`yter_class::surface_ret_fric_
  cos`) has no body and is not even listed.

The compiled shaders beside the reports (`assets/physical_renders/
Resources/shaders/bin/spv/*.xsa`, 96 archives, 6,662 SPIR-V modules)
kept their debug names and were DISASSEMBLED where it mattered (the
verifiers decoded instruction streams, not just names), which is the
only source for the GPU side:

* the terrain shader mixes a seasonal texture per layer by the per-draw
  `u_imm_a_season.x` (`rgb = mix(base, seasonal, s)`, 1,250 variants);
* it writes a luminance snow KEY into a G-buffer channel
  (`key = dot(u_material_snow_luma_coef mixed with the per-draw
  coefficient, linear rgb + alpha)`, encoded `luma * 0.5 + 0.5`) and
  colours nothing itself -- the earlier reading "the terrain shader
  whitens by luminance" was REFUTED by the bytecode;
* `weather_apply` then decodes `key = 2 z - 1`, forms `w0 = smoothstep(L
  - a, L + a, key + j (2 noise - 1))` against the global snow level
  `L = u_weather.z`, multiplies by a LINEAR ramp in cos(slope) between
  `u_snow_slope.x/.y`, turns it into `cov = saturate(2 w - 1 + snow_ALB.a)`
  and composites the dedicated `snow_ALB/NML/DCL` textures (ice the
  same without the slope term; rain darkens/wets);
* night is an additive `tex_nite * night_level.x * night_level.y`
  gated on `x >= 0`, selected by `NITE_MODE` (the default 4 draws none);
* terrain fog in the decoded variant is `mix(u_fog_rgb, lit, exp(-dist *
  u_fog_scale))`: one extinction per metre, the shape the harness's
  `fog_density` already has;
* `ocean_meta_data` samples the per-degree water PNG as base colour and
  turns its ALPHA into depth attenuation, `opacity = 1 - exp(-0.1 *
  10^(2 alpha) * thickness)`; `u_turbidity` is a dead member;
* exposure fusion weights by `exp(-0.5 * u_sigma2 * (L - 0.5)^2)` (an
  inverse variance) over Rec.709 luma; the sky is a Bruneton-type
  scattering precomputation and no shader consumes a sun-elevation
  colour table, so the `sky_colors_*.png` rows are decoded on the CPU
  (`sky_stat`, a name only).

The uniform VALUES (`u_weather.z`, `u_snow_slope`, `u_snow_area`, the
luma coefficients, scales) are in no module.

**Verification.** Every rule the readers extracted (107) was handed to
an adversarial reader with the same spans; 98 survived (61 of them
unportable facts passed through unverified), 9 were refuted. The
refutations that changed code: the terrain-shader whitening (above);
"season is a cache key" (it is a constructor argument on a path-keyed
cache); "water contact reads wave height in a separate step" (the
readback handle is passed INTO the terrain query); the sky-lighting
dataflow (names only). Corrections attached to survivors are folded
into the docstrings they cite (B1, A1-A5, A7-A9, C1-C3, D1-D2, E1-E2,
F1/F4/F10, RQ-01/02, I-03/04/05, K1/K3/K4/K7).

## Rules built into the code

Each cites its function and lines in `<report>/code.c`.

| rule | source | where it lives now |
| --- | --- | --- |
| Per-degree water tile path `world/water/+LL+LLL/+ll+lll.png`, 10-degree folder floored the simulator's way; a missing/empty tile falls back to ONE global texture (`REN_water_get_fallback_water_color`, no body; the committed `water/any.png` is its unverified candidate); the tile's alpha is the ocean pass's depth attenuation `k = 0.1 * 10^(2 alpha)` | `create_water_shader` 19871-19959; SPIR-V `ocean_meta_data` | `core.xplane.physical.floor10`, `water_tile_relpath`, `WaterTiles.fallback_colour` / `depth_attenuation`, `WATER_FALLBACK_NOTE`; `drape.water_colour_for` |
| Tile naming `+30-130/+37-122.dsf` (bucket then tile, explicit sign, `+00`) | `return_latlon_str_dsf` 39482-39686 | `physical.tile_name` |
| TERRAIN_DEF classification: `water` / `terrain_Water` = water shader, no texture file; `terrain_VirtualOrtho00..11` = photo-ortho; else `.ter`; `unknown token` -> `lib/terrain/rock_gray.ter` (the fallback ground is ROCK) | `DSF_AcceptTerrainDef` 18536-19013, 19187-19668 | `physical.classify_terrain_def`, `TERRAIN_DEF_FALLBACK_ROLE` |
| The eleven DSF rasters: elevation, sea_level, soundscape, spr1/2, sum1/2, fal1/2, win1/2 | `DSF_AcceptRasterDef` 21989-22086 | `physical.DSF_RASTER_NAMES`, `SEASONS` |
| Four seasons: `idx = clamp(floor(s), 0, 3)`, `blend = s - floor(s)`, mask `1 << idx`; season fixed at asset load | `build_placement<REN_beach_def>` 30893-30910; `UTL_art_asset_vram::load_sync` 16077-16163 | `physical.season_split`; `season_for` is the month stand-in for `total_season_for_location` (no body) and says so; the drape sidecar's `season` block |
| Earth Orbit Textures: three 10-degree rasters per tile, lat then lon floored to 10; the `-ele.png` axis (sea level texel 243, ~117 ft/texel, a fit) | `Map::terrain_tile::terrain_tile` 7424-7565; `Map::terrain_layer_desktop::draw` 8716-8717 | `physical.EarthOrbitTiles`, `ele_png_to_metres` |
| Weather snow: the terrain shader's luminance key, thresholded against a snow level with noise jitter, a linear cos-slope ramp, `cov = saturate(2 coverage - 1 + snow_ALB.a)`, the dedicated snow albedo mixed in by `cov` | SPIR-V `terrain` (key), `weather_apply` (composite), disassembled | `drape.weather_snow_cov`, `classify(...)["snow_cover"/"snow_slope"]`, the committed `weather/snow_ALB.png` + `noise.png`; the satellite cover drives the level; band, jitter, slope values, scales and the key coefficients are this repository's (listed under `assumed` in the sidecar); decal modulation taken as 0 |
| Season reaches the ground as `mix(base, seasonal texture, u_imm_a_season.x)` per layer | SPIR-V `terrain` 1,250 variants | not yet: one texture per role is extracted; `scripts/extract_xplane.py` must pull each `.ter`'s per-season texture on the owner's machine |
| Fog extinction `k = -ln(threshold) / visibility * scale`, split two ways | `atmo_params::set_fog_params` 5227-5236 | already in `core.scene.weather_visuals.fog_extinction_per_m` (Koschmieder); cross-referenced |
| Exposure-fusion multiplier `ISO / (K 2^EV100)`; Rec.709 luma literals | render_quality 4051-4064 | `core.capture.exposure.linear_exposure`, `REC709_LUMA` |

Read but NOT ported, with the reason: the DEM nearest-sample lookup with
an ISA fallback (`ATCUtilsGetTerrainAltForPoint` 1025-1125: the Python
query is deliberately bilinear for physics); the open-ocean test
(`xyz_if_open_ocean` 37592-37650: outside loaded tiles AND |ele| within
an unreadable tolerance AND a large nav-safe radius -- the thresholds are
globals); the tire footprint-max and wing-AGL rules (`handle_contact_tire`
15457-15637, `ret_agl_wing_mtrs` 11043-11137: the Python airframe check
samples four span stations with bilinear heights, stricter than the
simulator's single ground elevation, and `core/terrain/contact.py` is
mirrored line for line in the UE host); Mie extinction linear in
(turbidity - 1) (`set_turbidity` 5174-5207: every coefficient is a
global); the bloom / FSR / rain constants (globals).

## Not buildable from these reports

The functions a second decompilation pass should target, because the
owner's goal ("the logic had the entire instructions on how to build the
environment") stops at their missing bodies:

1. `io_read_terrain` (terrain_ocean 0164bf10) -- the `.ter` parser: the
   real land-class -> texture rule the drape approximates by slope/height.
2. `REN_degree_dem_table::total_season_for_location` (render_quality
   00d17b80) -- the per-location season value.
3. `REN_water_get_fallback_water_color` (terrain_ocean 01666a20).
4. `sky_stat::get_for_now` / `sky_stat::sky_stat` (lighting 003d3790 /
   003d8220) -- the sky-table lookup; the function that would confirm or
   refute the -12 / +10 degree anchors assumed in `core/xplane/__init__.py`.
5. `scattering_state::compute_sky_ambient` / `update_sky_view` (lighting
   003c27e0 / 003c3170) and `get_sun_position` (003d3560).
6. `tonemap_get_exposure_ev100` / `tonemap_update_exposure_per_frame_from_
   past_data` / `skyc_class::auto_atten_for_ref_nits` (lighting).
7. `OGL_terrain_shader_write_material_data` / `OGL_terrain_shader_setup`
   (terrain_ocean 0173be90 / 01739650) -- the material block, the only
   CPU place a season or snow weight is written.
8. `OBJ_command_builder::set_texture_weather(_decal)` (render_quality).
9. `yter_class::surface_ret_fric_cos` -- the surface-class friction table
   (not listed at all).
10. `REN_water_height::read_height` / `yter_class::terrain_is_water_hs`
    (terrain_ocean) -- water contact height for the flight model.

The `shaders/` folder this tree once carried was a byte-identical copy of
`assets/physical_renders/Resources/shaders/` and was dropped on merge into
`phase-2-testing` (2026-10-05); the one copy lives there.
