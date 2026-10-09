# Extracted terrain, sea, and lighting data

Generated from `Resources/` by the extraction script. Re-run it if the install changes.

## water/
- `water_polygons.geojson`: 5,201 water polygons from the 55 shapefiles in `Resources/map data/water/`. Each feature has a `tile` property (e.g. `+40+010`) giving its 1°×1° source tile. Coordinates are lon/lat.
- `water_tiles.csv`: one row per tile with shape count and bounding box.

Caveat: some shapefiles have no `.dbf`, so there are no per-polygon attributes (sea vs. lake vs. river). The geometry is still complete.

## terrain/
- `terrain_catalog.csv`: all 9,848 `.ter` terrain definitions (folder, name, category guess, base texture path).
- `category_counts.csv`: counts by the name-prefix category.
- `mountain_sea_snow_terrain.csv`: 3,699 entries whose names match mountain, hill, steep, snow, ice, cliff, rock, lake, or similar.
- `drape/<role>.png` + `drape/drape_textures.json`: the five ground textures the drape (`core/xplane/drape.py`) and the terrain material (`M_TerrainImagery`, via the drape sidecar) tile over a bake -- valley (`grass_cld_dry_fl.ter`), scrub (`shrb_cld_sdry_hill.ter`), rock and cliff (`rock_cld_dry_steep.ter`: its `BASE_TEX` and its `AUTO_SLOPE_CLIFF` texture), snow (`ice_cld_dry_hill.ter`) -- each with the ground size the simulator projects it at (`metres_x`/`metres_y`, the `.ter`'s own numbers). The committed PNGs are a 512 px pull; the extractor's cap is 2048 px since 2026-10-05, so the next run on the machine with the install replaces them at up to 2048 px (the longer side). That re-pull is not free: sixteen times the texels turns these five PNGs (and any map pulled beside them) from under a megabyte into tens of MB that git keeps for good -- whether to commit it is the owner's call -- and it moves three constants `scripts/ue_create_materials.py` pins to the committed PNGs (`TERRAIN_DETAIL_NEUTRAL`, each tile's linear mean; `TERRAIN_DEFAULT_TEXTURES`, the flat fallback texels; `TERRAIN_DETAIL_ASPECT`, width / height), which must be re-measured before the next asset build. Per role the index also records, since the same date: `directives`, every texture- or decal-naming line of the `.ter` (token, arguments, the file as written, and the pulled `drape/<role>_<kind>.png` when that file was on disk and decoded; the directive names vary by simulator version, so the match is by name shape and by image extension; a `.dcl` decal library is recorded, not parsed); `normal`, the pulled normal map when a `NORMAL` / `_NRM` directive resolved (a name relative to `drape/`, resolved to an absolute path by the drape before it reaches the sidecar); and `library_lines`, the lines of the terrain `library.txt` files that name the `.ter`, with the `REGION` selector in force at each. The committed index predates these fields: it has no `directives`, no normal map and no library lines, and no seasonal texture is extracted yet (the library lines are the input a per-season resolution will be built from). The weather bitmaps the snow composite reads (`snow_ALB/NML/DCL`, `ice_*`, `noise`) are not extracted here: they are committed under `assets/physical_renders/Resources/bitmaps/world/weather/`, the only place `core/xplane/physical.py` reads them, and the drape records one that tree lacks as absent.

- `drape/<role>_nrm_derived.png`: stand-in normal maps derived from each texture by `scripts/derive_drape_normals.py` (`core/xplane/normals.py`): luminance high-passed and read as height, scaled to a per-role mean tilt (rock 14°, cliff 18°, scrub 7°, snow 5°, valley 4°), DirectX green. The drape uses one only when the extraction recorded no real normal for that role; rerun the script after re-pulling the textures.

Caveat: the source simulator has no literal "sea" or "mountain" terrain type. Sea is handled by the water polygons above (plus 10 small `terrain10_SEA` definitions). Mountains are `hill`, `steep`, `hiland`, `cliff`, and `rock` terrain. The category column is a name-prefix guess, not an official classification.

## lighting/
- `sky_colors_<condition>.png`: 256×640 lookup tables for 10 conditions: clean, foggy, hazy, hialt, mount, ocast (overcast), orbit, snowy, socked (low visibility), stratus.
- `sky_palettes.json`: 32 sampled bands per condition from the left gradient panel, top (night) to bottom.
- `lights.txt`: source simulator light definitions (runway, approach, and similar lights).

Caveat: the lookup layout is only partly decoded. The right-hand labels name sun elevation bands (-8° to +6°), plus sun, moon, water, cloud, ambient, and direct light columns. The sampled JSON is a rough summary. The PNGs are the reliable source. The `mount` and `clean` gradients sampled to nearly the same values, so I didn't confirm they differ.

## Beside this folder
- `assets/physical_renders/Resources/`: the simulator's render assets in its own layout (water tiles, monthly snow cover, shaders, clouds, weather decals, lights, moon, globe). The drape reads the per-tile water colour and the month's snow cover from there (`core/xplane/physical.py`).
- `assets/logic_reports/`: the decompiled function listings and code of the subsystems that consume those assets; `core.xplane.physical.REPORTS` is the index.

The `sky_colors_*.png` tables and `lights.txt` here are the single committed copies (the render tree does not repeat them).

## Source paths
- Water: `Resources/map data/water/`
- Terrain: `Resources/default scenery/1000 world terrain/` (`terrain*`, `textures*`)
- Lighting: `Resources/bitmaps/skycolors/`, `Resources/bitmaps/world/lites/`
