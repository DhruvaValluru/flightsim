Copies (originals untouched) of physical render assets matching ~/render_reports.
Paths mirror the local simulator Resources/ layout.

render_reports/shaders        -> Resources/shaders (spv, msl, xsv mappings, font.glsl)
render_reports/render_quality -> Resources/shaders, Resources/effects, bitmaps/world/{clouds,weather,overlays,maps}
render_reports/lighting       -> Resources/brdf_lookup, bitmaps/skycolors, bitmaps/world/{lites,moon*}
render_reports/terrain_ocean  -> bitmaps/world/water, bitmaps/earth1/2 (+nrm), Earth Orbit Textures, Snow Cover
render_reports/physics        -> no render assets (code only)

Not copied: UI/cockpit/interface bitmaps.
