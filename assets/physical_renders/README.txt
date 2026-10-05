Physical render assets: copies (originals untouched) of the local simulator's
render resources, in its own Resources/ layout. Committed so a machine without
the simulator install renders the same terrain look. The decompiled code that
CONSUMES each folder is in assets/logic_reports/<report>/ (see the README there),
and core/xplane/physical.py is the index tying the two together (REPORTS) plus
the readers for the rasters the terrain drape uses.

Resources/shaders            compiled shader set: bin/spv, bin/msl, bin/*.xsv
                             mappings, font.glsl         (report: render_quality)
Resources/effects            particle systems (.pss) and sprites
                                                         (report: render_quality)
Resources/brdf_lookup        the BRDF lookup table       (report: lighting)
bitmaps/world/clouds         cirrus density, smoke puff  (report: render_quality)
bitmaps/world/weather        snow/ice decals: _ALB, _NML, _DCL, noise
                                                         (report: render_quality)
bitmaps/world/overlays       prop/rotor discs, strikes, wake, windshield 2D
                                                         (report: render_quality)
bitmaps/world/maps           map-display rasters         (report: render_quality)
bitmaps/world/lites          1000_lights_close.png       (report: lighting)
bitmaps/world/moon*          moon albedo + normal        (report: lighting)
bitmaps/world/water          15,281 per-1-degree water textures in 10-degree
                             folders, the exact path REN_degree::create_water_shader
                             loads; read by core.xplane.physical.WaterTiles as the
                             location's water colour    (report: terrain_ocean)
bitmaps/Snow Cover           NASA NEO MOD10C1 monthly snow cover, 2025-01..12,
                             3600x1800 palette PNG (index 255 = no data); read by
                             core.xplane.physical.SnowCover to season the drape's
                             snow class                  (report: terrain_ocean)
bitmaps/Earth Orbit Textures five 10-degree tiles: .dds albedo, -ele.png
                             (8-bit height), -nrm.png (normals); catalogued, no
                             consumer yet                (report: terrain_ocean)
bitmaps/earth1/2 (.dds, -nrm.png)
                             the orbital globe           (report: terrain_ocean)

Deduplicated on merge into phase-2-testing (2026-10-05): the shader set that
assets/logic_reports/shaders/ also carried (byte-identical) lives only here;
bitmaps/skycolors/sky_colors_*.png and bitmaps/world/lites/lights.txt are NOT
repeated here because the extractor's own copies in assets/xplane/lighting/ are
the ones the code decodes (sky_tables.json, sky_palettes.json) -- one copy each.

Not copied: UI/cockpit/interface bitmaps.
