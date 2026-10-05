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

Caveat: the source simulator has no literal "sea" or "mountain" terrain type. Sea is handled by the water polygons above (plus 10 small `terrain10_SEA` definitions). Mountains are `hill`, `steep`, `hiland`, `cliff`, and `rock` terrain. The category column is a name-prefix guess, not an official classification.

## lighting/
- `sky_colors_<condition>.png`: 256×640 lookup tables for 10 conditions: clean, foggy, hazy, hialt, mount, ocast (overcast), orbit, snowy, socked (low visibility), stratus.
- `sky_palettes.json`: 32 sampled bands per condition from the left gradient panel, top (night) to bottom.
- `lights.txt`: source simulator light definitions (runway, approach, and similar lights).

Caveat: the lookup layout is only partly decoded. The right-hand labels name sun elevation bands (-8° to +6°), plus sun, moon, water, cloud, ambient, and direct light columns. The sampled JSON is a rough summary. The PNGs are the reliable source. The `mount` and `clean` gradients sampled to nearly the same values, so I didn't confirm they differ.

## Source paths
- Water: `Resources/map data/water/`
- Terrain: `Resources/default scenery/1000 world terrain/` (`terrain*`, `textures*`)
- Lighting: `Resources/bitmaps/skycolors/`, `Resources/bitmaps/world/lites/`
