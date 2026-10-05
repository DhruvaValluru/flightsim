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

Two findings the code already acts on:

* `REN_degree::create_water_shader` (terrain_ocean) loads
  `"%sworld/water/%+03d%+04d/%+03d%+04d.png"`: the 10-degree folder is the
  floored degree, the file the 1-degree tile. `core.xplane.physical.
  water_tile_relpath` is that formula; the drape takes the tile's colour
  for mapped water.
* `REN_degree_dem_table::total_season_for_location` (render_quality) and
  the `dsf_season` loaders (terrain_ocean) are where the simulator seasons
  its terrain per location. The drape's equivalent is the MODIS monthly
  snow cover read for the scene's month (`core.xplane.physical.SnowCover`).

The `shaders/` folder this tree once carried was a byte-identical copy of
`assets/physical_renders/Resources/shaders/` and was dropped on merge into
`phase-2-testing` (2026-10-05); the one copy lives there.
