"""Create the material assets the render commandlet loads. Runs inside UE:

    UnrealEditor-Cmd <project> -run=pythonscript -script=scripts/ue_create_materials.py

Build-time asset step, command-line only. Two assets:

* /Game/FlightSim/M_VertexColor -- vertex colour into base colour, constant
  high roughness. The georeferenced terrain writes its slope/altitude
  classification into vertex colours; this is the material that shows them,
  and the commandlet refuses to render classified terrain without it rather
  than falling back to the default material silently.

* /Game/FlightSim/M_TerrainImagery -- the terrain surface: the drape
  ("Imagery", sampled by UV0, the macro albedo) textured by the
  simulator's own ground textures and snowed by its weather rule (the
  terrain-surface section at the end of this comment; the parameter
  names, TERRAIN_TEXTURE_PARAMETERS / TERRAIN_SCALAR_PARAMETERS, are the
  contract core/xplane/drape.py writes into the drape sidecar's
  "material" block and FlightSimVisualScene.cpp sets on the dynamic
  instance). What "Imagery" carries: the drape's BASE image when the
  host has it -- the sidecar's material.textures.imagery
  (<bake>_xplane_base.png, written by core/xplane/drape.py beside the
  composite: the per-texel role blend with every role's tile replaced
  by its mean colour, the permanent snow role included, the mapped
  water painted exactly as the composite paints it, and no weather-snow
  pass; each role's mean is the mean of the committed drape/<role>.png's
  8-bit sRGB texels, composited as the sRGB texel it is, while
  TERRAIN_DETAIL_NEUTRAL below is the same tile's mean in LINEAR light,
  the one the detail modulation divides by: one measurement in two
  spaces, not one number) -- so the detail and the weather snow are
  applied ONCE, by this material; the composite (the sidecar's
  texture.file, the drape with the tiles and the weather snow already
  in it) when the host or the sidecar has no base image, the fallback a
  material without the block always had. FlightSimVisualScene.cpp
  ApplyDrapeMaterial sets "Imagery" from material.textures.imagery when
  it is present and loads, from the composite otherwise, and records
  which ("imagery_source"). The terrain mesh's UV0 is the raster grid
  normalised (col/width, row/height) and the draped texture and its
  maps share the bake's CRS/origin/extent by construction
  (core/terrain/imagery.py), so the drape-grid samplers have no
  registration parameters to get wrong: the alignment lives in the
  data, and the landmark-projection check on a rendered frame verifies
  it. The detail, the normals and the snow tile in WORLD metres
  (AbsoluteWorldPosition / the *Metres scalars), not on the grid.

* /Game/FlightSim/M_VertexColorUnlit -- made for the tornado funnel, which
  does NOT use it: the funnel rendered black under it too, so it ships on
  the engine's default material (FlightSimScenarioWorld.cpp). Kept for the
  open question in NEXT.md gotcha 26; nothing loads it.

M_VertexColor and the three terrain surfaces (M_TerrainImagery,
M_TerrainImageryNight, M_Landscape) expose one scalar parameter,
"Wetness" (default 0), the name FlightSimVisualScene.cpp ApplyWetness
sets from the card's precipitation: the only wet-surface coupling. It
lerps roughness from the surface's own dry value (0.92 for
M_VertexColor, the per-role blend for the terrain surfaces) toward 0.25
(wet) and darkens the base colour by up to 30 %; dry (0) is the look
the materials have without it. The node and pin names below are the UE
Python API's; nothing here is run without an engine, so the Windows
build is where they are checked.

* /Game/FlightSim/M_CustomStencilID -- Phase 2 (packages B + C): the
  post-process material the -labels ID pass renders through. It REPLACES
  the tonemapper and emits SceneTexture:CustomStencil as a flat float, so
  the render commandlet's SCS_FinalColorHDR capture reads each pixel's
  custom-stencil value (= the card's object int_id, set on every labelled
  mesh component) back as a raw number, anti-aliasing off. The commandlet
  refuses -labels by name when this asset is absent rather than writing
  an ID image it did not measure.

* /Game/FlightSim/M_WorldNormalPass, M_VelocityPass, M_BaseColorPass --
  I6 (gap S3): the three ground-truth passes -passes=normal,velocity,
  albedo render through, built on the M_CustomStencilID pattern (post-
  process domain, replacing the tonemapper, one SceneTexture node into
  emissive). The SceneTexture ids are the UE 5.7 ESceneTextureId values
  PPI_WorldNormal, PPI_Velocity and PPI_BaseColor (Python enum spellings
  PPI_WORLD_NORMAL, PPI_VELOCITY, PPI_BASE_COLOR). The normal and the
  velocity are SIGNED, and whether a tonemapper-replacing emissive keeps
  a negative value through the FinalColorHDR readback is not established
  here, so both are offset in the material (value * 0.5 + 0.5,
  SIGNED_SCALE / SIGNED_OFFSET below) and decoded back in the commandlet;
  base colour is already in [0, 1]. What the Velocity node's output IS
  (the decoded clip-space delta, x right, y up, from the previous scene
  frame) is engine source reading, verified on Windows by the verifier's
  flow_vs_motion check on the first rendered bundle -- not here. The
  commandlet refuses each pass by name (labels.pass_material) when its
  asset is absent.

* /Game/FlightSim/M_WorldNormal, M_Velocity -- S4 (the sensing engine
  side): the same post-process shape (replacing the tonemapper, one
  SceneTexture node into emissive) with NO offset encoding, table
  LINEAR_MATERIALS. M_WorldNormal is the fallback normal source of the
  linear .f32 normal pass (-normal-source=material, when the box shows the
  SCS_Normal capture in neither encoding). M_Velocity is the velocity
  cross-check (-velocity-check): its capture keeps
  bAlwaysPersistRenderingState true in the commandlet (the previous view
  matrices live in the view state), and it is a READ-BACK beside the
  Python flow, never the truth. Whether a negative emissive survives the
  FinalColorHDR readback is exactly what its record's
  negative_raw_values count measures on Windows.

* /Game/FlightSim/M_GreyCard -- S4: the calibration frame's card (the
  -calibration flag). Lit, fully rough (1.0), non-metallic, specular 0 --
  a Lambertian -- with two scalar parameters the commandlet sets per quad
  through a dynamic instance: "Reflectance" into base colour (default
  0.18, the grey card) and "Luminance" into emissive, stated in cd/m^2
  (default 0). The emissive grey quad is Reflectance 0 / Luminance L; the
  white Lambertian quad Reflectance 0.9 / Luminance 0.

* W5 (the world engine side) -- six more, each parameter under the name
  the C++ sets (pinned equal by tests/test_ue_world_source.py and
  tests/test_ue_materials.py):

  - /Game/FlightSim/M_Landscape: the scene level's Landscape material:
    the terrain surface (below) on the Landscape's paint layers.
    LandscapeLayerBlends over the land-cover layers (LANDSCAPE_LAYERS,
    the weight keys of core/terrain/landcover.py, weight-blended: the
    layers sum to 255 per texel), each layer taking a drape role's
    ground texture, normal and roughness (LANDSCAPE_LAYER_ROLES: tree
    cover is scrub under "TintTreeCover", cropland valley under
    "TintCropland", built-up rock under "TintBuiltUp", the wetlands and
    mangroves scrub under "TintWetland", moss valley under
    "TintMossLichen"; permanent water the drape's water colour at
    RoughnessWater, nodata the drape alone; the tints scene dressing,
    not a measurement). The blend is the land-cover albedo, lerped
    toward the imagery drape ("Imagery" sampled across the whole
    Landscape by "LandscapeTexels", flipped by "ImageryFlipV" when the
    rows were written north-up, weighted by "ImageryWeight", 0.0 by
    default -- no drape is the land-cover textures alone -- and 1.0
    when scripts/ue_build_scene.py has a drape), the detail modulation
    scaled by the same weight (where the drape is not the base the
    blend IS the detail), then the weather snow ("SnowCover"
    on the drape UV), the water (the permanent_water layer's weight)
    and the "Wetness" coupling every terrain material has. Its instance
    is built by scripts/ue_build_scene.py, which sets the drape and the
    layers only: the detail, normal and snow samplers stay at this
    script's defaults (the committed bitmaps, below) until that script
    sets them -- not claimed here.
  - /Game/FlightSim/M_LandcoverID: the land-cover ID pass (post-process,
    replacing the tonemapper, the M_CustomStencilID shape). Each pixel's
    world position (reconstructed from depth) goes onto the bake grid by
    the registration the render measures -- col = (X - OriginX) / CellX,
    row = (Y - OriginY) / CellY, uv = (col / GridWidth, row / GridHeight),
    the cell FLOOR as the verifier's own unprojection takes it -- and the
    class-code raster "ClassMap" (8-bit, nearest, no mips, non-sRGB,
    imported by scripts/ue_build_scene.py) gives the code, emitted where
    the custom stencil is "TerrainStencil" and 0 elsewhere or off the grid.
  - /Game/FlightSim/M_Starfield: the starfield sphere (unlit, additive,
    two-sided): the direction from the sphere's centre, in the sphere's
    own frame, as right ascension / declination into the equirectangular
    "StarMap" (luminance in cd/m^2 per texel, built by the render), times
    "StarIntensity".
  - /Game/FlightSim/M_RainStreaks: the rain streaks (post-process, before
    the tonemapper, the BEAUTY capture only): screen-space columns across
    "StreakDirection", a streak of "StreakLengthPx" along it per occupied
    column, occupancy from "StreakDensity" (drops per m^3) through the
    stated STREAK_CELL_VOLUME_M3, moving with "StreakPhase" (seconds).
  - /Game/FlightSim/M_AirframePaint: a clear-coat paint (lit, the clear
    coat shading model, which Substrate converts to a slab with a coat):
    "PaintColour", "Roughness", "Metallic", "ClearCoat",
    "ClearCoatRoughness".
  - /Game/FlightSim/M_Runway: the runway plane: "Markings" (the Annex 14
    raster of core/scene/runway.py, row 0 at the threshold) lerps
    "SurfaceColour" to "PaintColour", then the "Wetness" coupling.

  /Game/FlightSim/T_LinearDefault is the non-sRGB default the W5 linear
  samplers are created with (a texture parameter needs a default of its
  own sampler class to compile); what the engine's factory fills it with
  is not read anywhere.

The terrain surface (M_TerrainImagery, M_TerrainImageryNight and the
Landscape route's M_Landscape share it: terrain_role_samples /
terrain_surface below) is the simulator's own terrain shader structure,
read from its compiled SPIR-V (assets/logic_reports/README.md): a base
albedo, detail decals keyed by distance, a bump texture, per-material
roughness, weather snow by a thresholded level times a linear ramp in
cos(slope), night as an additive texture. Here:

  roles     "Roles" (linear RGBA on UV0: R valley, G scrub, B rock,
            A cliff; snow = saturate(1 - R - G - B - A)) weights the
            five ground textures (assets/xplane/terrain/drape/<role>.png,
            the simulator's, each tiled at its PROJECTED ground size:
            "DetailMetres<Role>" from drape_textures.json, the shorter
            axis, across the tile's height, and TERRAIN_DETAIL_ASPECT
            times that -- the PNG's width / height, 2 for scrub, 4 for
            cliff -- across its width, so a 512 x 256 tile is not
            squeezed square) into a detail albedo "Detail<Role>", a
            tangent normal "Normal<Role>" and a roughness
            "Roughness<Role>". M_Landscape weights them by its paint
            layers instead.
  detail    colour = Imagery * lerp(1, detail / neutral, DetailStrength
            * fade), fade = 1 - saturate((PixelDepth - DetailFadeStartM
            * 100) / ((DetailFadeEndM - DetailFadeStartM) * 100)): the
            decal distance key, in the engine's centimetres. "neutral"
            is each role's MEASURED per-channel linear mean
            (TERRAIN_DETAIL_NEUTRAL, from the committed PNGs on this
            machine, not on Windows): the design's constant 2 (neutral
            at linear 0.5) would halve the drape over valleys, whose
            texture averages linear 0.065. The detail modulates; the
            drape colours. Over a pure role of the base image, Imagery
            is that role's sRGB-texel mean, so at full strength the
            surface is the tile scaled by decode(sRGB mean) / linear
            mean -- 0.77 .. 0.96 per channel on the committed tiles,
            measured here -- near the tile, not the tile.
  snow      "SnowCover" (linear R on UV0, the month's cover 0..1):
            w0 = saturate((SnowCover - 0.5 + SnowBand * (Noise - 0.5))
            / SnowBand + 0.5), coverage = w0 * saturate((VertexNormalWS.z
            - SnowSlopeLowCos) / (SnowSlopeHighCos - SnowSlopeLowCos)),
            cov = saturate(2 * coverage - 1 + SnowAlbedo.a); colour,
            normal and roughness lerp to "SnowAlbedo" (snow_ALB.png,
            RGBA: alpha the per-texel threshold), "SnowNormal"
            (snow_NML.png) and "RoughnessSnow" by cov. SnowAlbedo and
            SnowNormal tile at "SnowMetres", "Noise" (noise.png, R) at
            "NoiseMetres", world metres both.
  water     "WaterMask" (linear R on UV0): colour = Imagery (the drape
            carries the water colour), roughness = RoughnessWater, the
            normal flat. Specular stays the engine's default 0.5
            everywhere; nothing is wired to it.
  then      the "Wetness" coupling, and in M_TerrainImageryNight the
            "NightLights" x "NightLuminance" emissive.

Normal maps: the simulator's NML bitmaps pack x, y in R, G and keep
metalness and gloss in B, A (snow_NML.png measured here: B one constant
value, A varying, R and G centred on 128 and reconstructing to z ~ 1),
so every normal sampler is the engine's Normal type, whose unpack
derives z from R, G and ignores B, A. The C++ must import an NML as a
normal map (TC_Normalmap, sRGB off) and the data maps (Roles, SnowCover,
WaterMask, Noise) with sRGB OFF: the samplers decode nothing, the
texture's own flag does, and an sRGB-flagged weight map arrives
gamma-decoded (0.5 -> 0.21). Not checked here. The normals are
tangent-space, so the tile mesh must carry tangents for a role normal
to mean anything; no role normal is extracted yet (every "normal" in
the sidecar's detail entries is null), so today only the snow normal is
ever set.

Defaults: every terrain sampler the C++ may leave unset defaults to a
texture this script imports (TERRAIN_DEFAULT_TEXTURES, default_texture):
the committed bitmap itself when the checkout has it (the five ground
textures, snow_ALB / snow_NML / noise), else a 4 x 4 texture of ONE
known texel written here as a PNG (no engine API writes texels from
Python; an import does) -- Roles = valley everywhere, SnowCover and
WaterMask = 0, Noise = 0.5, every role normal flat, a missing Detail<Role>
its own neutral (the modulation is then exactly 1) -- so an absent map
reads a KNOWN value rather than the engine's checker. A sidecar without
a "material" block therefore renders as the drape textured by valley,
and M_Landscape textures its layers from the committed bitmaps with no
help from the scene script.
"""

import math

import unreal

PATH = "/Game/FlightSim"

#: I6: a signed scene texture (world normal, velocity) is written to the
#: pass target as value * SIGNED_SCALE + SIGNED_OFFSET, so [-1, 1] lands
#: in [0, 1]; the commandlet inverts it (FlightSimRenderCommandlet.cpp
#: RenderPassSignedScale / RenderPassSignedOffset, pinned equal by test).
SIGNED_SCALE = 0.5
SIGNED_OFFSET = 0.5

#: The three pass materials and their scene texture, by pass word.
PASS_MATERIALS = {
    "normal": ("M_WorldNormalPass", "PPI_WORLD_NORMAL", True),
    "velocity": ("M_VelocityPass", "PPI_VELOCITY", True),
    "albedo": ("M_BaseColorPass", "PPI_BASE_COLOR", False),
}

#: S4: the two unencoded post-process materials, by what they serve:
#: ("M_Name", "PPI_SCENE_TEXTURE"). Built by create_pass_material with no
#: offset (the signed flag False: the texel goes straight to emissive).
LINEAR_MATERIALS = {
    "normal_fallback": ("M_WorldNormal", "PPI_WORLD_NORMAL"),
    "velocity_check": ("M_Velocity", "PPI_VELOCITY"),
}

#: S4: the calibration card's parameters, by the names the commandlet sets
#: (FlightSimRenderCommandlet.cpp RenderGreyCardLuminanceParameter /
#: RenderGreyCardReflectanceParameter, pinned equal by test).
GREY_CARD_LUMINANCE_PARAMETER = "Luminance"
GREY_CARD_REFLECTANCE_PARAMETER = "Reflectance"
GREY_CARD_REFLECTANCE_DEFAULT = 0.18
GREY_CARD_ROUGHNESS = 1.0
GREY_CARD_METALLIC = 0.0
GREY_CARD_SPECULAR = 0.0

#: The parameter ApplyWetness looks up by this exact name
#: (FlightSimVisualScene.cpp FindScalarParameter(Material, TEXT("Wetness"))).
WETNESS_PARAMETER = "Wetness"
ROUGHNESS_DRY = 0.92
ROUGHNESS_WET = 0.25
WET_DARKENING = 0.3

# -- the terrain surface's parameters (the module comment) ----------------------

#: The five drape roles, core/xplane/drape.py ROLES (pinned equal by
#: tests/test_ue_materials.py), in the Roles map's channel order R, G, B,
#: A, then the remainder.
TERRAIN_ROLES = ("valley", "scrub", "rock", "cliff", "snow")
#: Every texture parameter of the terrain surface -> its sampler: "srgb"
#: (a colour), "linear" (data: the sampler decodes nothing) or "normal"
#: (the engine's Normal sampler: x, y from R, G, z derived). The names are
#: the contract with the drape sidecar's "material" block
#: (core/xplane/drape.py material_block: "roles" -> Roles, "snow_cover" ->
#: SnowCover, "water_mask" -> WaterMask, detail.<role>.file -> Detail<Role>,
#: detail.<role>.normal -> Normal<Role>, "snow_albedo" -> SnowAlbedo,
#: "snow_normal" -> SnowNormal, "noise" -> Noise) and with
#: FlightSimVisualScene.cpp, which sets each one it finds and records it
#: applied or absent.
TERRAIN_TEXTURE_PARAMETERS = {
    "Imagery": "srgb",         # the base image, else the composite, UV0 (M_Landscape: the drape UV)
    "Roles": "linear",         # RGBA = valley, scrub, rock, cliff; snow = 1 - sum
    "SnowCover": "linear",     # R = the month's snow cover 0..1
    "WaterMask": "linear",     # R = 1 on mapped water
    "DetailValley": "srgb", "DetailScrub": "srgb", "DetailRock": "srgb",
    "DetailCliff": "srgb", "DetailSnow": "srgb",
    "NormalValley": "normal", "NormalScrub": "normal", "NormalRock": "normal",
    "NormalCliff": "normal", "NormalSnow": "normal",
    "SnowAlbedo": "srgb",      # snow_ALB.png; alpha = the per-texel threshold
    "SnowNormal": "normal",    # snow_NML.png
    "Noise": "linear",         # noise.png, R
}
#: Every scalar parameter of the terrain surface -> its default, in the
#: sidecar block's order (core/xplane/drape.py MATERIAL_SCALAR_NAMES, pinned
#: equal, with these values, by test). The detail sizes are the simulator's
#: PROJECTED ground sizes (drape_textures.json; the shorter axis, metres_y,
#: one scalar per role: the longer axis is that times TERRAIN_DETAIL_ASPECT
#: below, so scrub and cliff tile 2:1 and 4:1 here as they do there); the
#: snow and noise sizes, the detail strength and fade, the slope ramp (cos
#: 38 deg .. cos 30 deg), the band and every roughness are this
#: repository's (the simulator's are uniforms no module carries). "Wetness"
#: and "NightLuminance" are the scene's, deliberately not here.
TERRAIN_SCALAR_PARAMETERS = {
    "DetailMetresValley": 1277.0, "DetailMetresScrub": 1222.0, "DetailMetresRock": 1111.0,
    "DetailMetresCliff": 708.0, "DetailMetresSnow": 2840.0,
    "SnowMetres": 64.0, "NoiseMetres": 512.0,
    "DetailStrength": 0.6, "DetailFadeStartM": 3000.0, "DetailFadeEndM": 12000.0,
    "SnowSlopeLowCos": 0.788, "SnowSlopeHighCos": 0.866, "SnowBand": 0.25,
    "RoughnessValley": 0.85, "RoughnessScrub": 0.8, "RoughnessRock": 0.75,
    "RoughnessCliff": 0.7, "RoughnessSnow": 0.55, "RoughnessWater": 0.08,
}
#: Each role's detail ASPECT: the committed texture's width / height
#: (assets/xplane/terrain/drape/<role>.png: 512 x 512, 512 x 256, 512 x 512,
#: 512 x 128, 512 x 512, measured on this machine; pinned to the PNGs by
#: test), which is also drape_textures.json's metres_x / metres_y. The
#: tile's height spans DetailMetres<Role> on the ground, its width aspect
#: times that (detail_uv); the contract stays the one scalar per role.
TERRAIN_DETAIL_ASPECT = {
    "valley": 1.0, "scrub": 2.0, "rock": 1.0, "cliff": 4.0, "snow": 1.0,
}
#: Each role's detail NEUTRAL: the per-channel linear mean of its committed
#: texture (assets/xplane/terrain/drape/<role>.png, measured on this
#: machine 2026-10-05, not on Windows; pinned to the PNGs by test), the
#: texel at which the modulation detail / neutral is 1. A re-extracted
#: texture moves it.
TERRAIN_DETAIL_NEUTRAL = {
    "valley": (0.0780, 0.0799, 0.0369), "scrub": (0.0917, 0.0903, 0.0557),
    "rock": (0.1490, 0.1390, 0.1190), "cliff": (0.1794, 0.1663, 0.1355),
    "snow": (0.5043, 0.5563, 0.5704),
}
#: The terrain samplers' default textures by asset name (default_texture):
#: (the committed bitmap, repository-relative, imported when the checkout
#: has it, or None; the 4 x 4 flat RGBA texel 0-255 used instead; sRGB;
#: normal map). The flat detail texels are the neutrals sRGB-encoded.
#: T_RolesValley is a ZERO-ALPHA PNG (cliff = A = 0): the engine's PNG
#: import rewrites zero-alpha texels unless told not to, so that one goes
#: through a TextureFactory with fill_png_zero_alpha off (import_texture);
#: that the imported texture reads (255, 0, 0, 0) untouched is the first
#: Windows check of these defaults.
TERRAIN_DEFAULT_TEXTURES = {
    "T_DetailValley": ("assets/xplane/terrain/drape/valley.png", (79, 80, 54, 255), True, False),
    "T_DetailScrub": ("assets/xplane/terrain/drape/scrub.png", (85, 85, 67, 255), True, False),
    "T_DetailRock": ("assets/xplane/terrain/drape/rock.png", (108, 104, 97, 255), True, False),
    "T_DetailCliff": ("assets/xplane/terrain/drape/cliff.png", (117, 113, 103, 255), True, False),
    "T_DetailSnow": ("assets/xplane/terrain/drape/snow.png", (188, 197, 199, 255), True, False),
    "T_SnowAlbedo": ("assets/physical_renders/Resources/bitmaps/world/weather/snow_ALB.png",
                     (233, 233, 233, 128), True, False),
    "T_SnowNormal": ("assets/physical_renders/Resources/bitmaps/world/weather/snow_NML.png",
                     (128, 128, 255, 255), False, True),
    "T_Noise": ("assets/physical_renders/Resources/bitmaps/world/weather/noise.png",
                (128, 128, 128, 255), False, False),
    "T_FlatNormal": (None, (128, 128, 255, 255), False, True),
    "T_RolesValley": (None, (255, 0, 0, 0), False, False),
    "T_Black": (None, (0, 0, 0, 255), False, False),
    "T_ImageryGrey": (None, (128, 128, 128, 255), True, False),
}
#: Which default each terrain sampler is created with. "Imagery" has none
#: in the tile materials (the C++ always sets it; a failed drape is a
#: refused render) and T_ImageryGrey in M_Landscape, where no drape is a
#: real case (at ImageryWeight 0 the grey reaches only the water and
#: nodata layers, whose albedo is the drape itself).
TERRAIN_TEXTURE_DEFAULTS = {
    "Roles": "T_RolesValley", "SnowCover": "T_Black", "WaterMask": "T_Black",
    "DetailValley": "T_DetailValley", "DetailScrub": "T_DetailScrub",
    "DetailRock": "T_DetailRock", "DetailCliff": "T_DetailCliff", "DetailSnow": "T_DetailSnow",
    "NormalValley": "T_FlatNormal", "NormalScrub": "T_FlatNormal", "NormalRock": "T_FlatNormal",
    "NormalCliff": "T_FlatNormal", "NormalSnow": "T_FlatNormal",
    "SnowAlbedo": "T_SnowAlbedo", "SnowNormal": "T_SnowNormal", "Noise": "T_Noise",
}
#: M_TerrainImageryNight's two, by the names FlightSimVisualScene.cpp sets.
NIGHT_LIGHTS_PARAMETER = "NightLights"
NIGHT_LUMINANCE_PARAMETER = "NightLuminance"

# -- W5: the world materials' names and parameters ----------------------------

#: Every world material, by name (one /Game/FlightSim path each).
WORLD_MATERIALS = ("M_Landscape", "M_LandcoverID", "M_Starfield", "M_RainStreaks",
                   "M_AirframePaint", "M_Runway")
#: The Landscape's paint layers: core/terrain/landcover.py WEIGHT_KEYS (the
#: legend's class keys, nodata last), pinned equal by test; the layer names
#: FlightSimBridgeEditor's ImportLandscape gives the layers.
LANDSCAPE_LAYERS = ("tree_cover", "shrubland", "grassland", "cropland", "built_up",
                    "bare_sparse", "snow_ice", "permanent_water", "herbaceous_wetland",
                    "mangroves", "moss_lichen", "nodata")
#: The legend colours (sRGB 0-255, core/terrain/landcover.py LEGEND, pinned
#: equal by test): the land-cover ID pass's legend, kept here as the
#: reference the layer list is read against. M_Landscape no longer paints
#: them: each layer takes a drape role's ground texture (next table).
LANDSCAPE_TINTS = {
    "tree_cover": (0, 100, 0), "shrubland": (255, 187, 34), "grassland": (255, 255, 76),
    "cropland": (240, 150, 255), "built_up": (250, 0, 0), "bare_sparse": (180, 180, 180),
    "snow_ice": (240, 240, 240), "permanent_water": (0, 100, 200),
    "herbaceous_wetland": (0, 150, 160), "mangroves": (0, 207, 117),
    "moss_lichen": (250, 230, 160), "nodata": (0, 0, 0),
}
#: Each paint layer -> (the drape role whose ground texture, normal and
#: roughness it takes, the tint parameter multiplied over it or None).
#: "water" is the drape's water colour at RoughnessWater and "imagery" the
#: drape alone (a neutral detail, a flat normal, the valley roughness).
LANDSCAPE_LAYER_ROLES = {
    "tree_cover": ("scrub", "TintTreeCover"), "shrubland": ("scrub", None),
    "grassland": ("valley", None), "cropland": ("valley", "TintCropland"),
    "built_up": ("rock", "TintBuiltUp"), "bare_sparse": ("rock", None),
    "snow_ice": ("snow", None), "permanent_water": ("water", None),
    "herbaceous_wetland": ("scrub", "TintWetland"), "mangroves": ("scrub", "TintWetland"),
    "moss_lichen": ("valley", "TintMossLichen"), "nodata": ("imagery", None),
}
#: The tints' defaults (linear RGB multipliers over the role's texture):
#: scene dressing, not a measurement -- trees darker and greener than the
#: scrub they stand on, crops warmer than grass, the built-up greyer than
#: rock, the wetlands darker and bluer, moss yellower.
LANDSCAPE_TINT_DEFAULTS = {
    "TintTreeCover": (0.45, 0.55, 0.40), "TintCropland": (1.10, 1.00, 0.80),
    "TintBuiltUp": (0.70, 0.70, 0.72), "TintWetland": (0.60, 0.75, 0.70),
    "TintMossLichen": (1.00, 0.95, 0.75),
}
#: "ImageryWeight" where the scene script sets nothing: 0, the land-cover
#: textures alone -- no drape is no drape, not half of a grey default --
#: and the modulation, scaled by the same weight, off with it (the blend IS
#: the detail there). scripts/ue_build_scene.py sets 1.0 when it has a drape.
LANDSCAPE_IMAGERY_WEIGHT = 0.0
#: M_Landscape's own parameters; it also exposes every terrain-surface
#: parameter (TERRAIN_TEXTURE_PARAMETERS / TERRAIN_SCALAR_PARAMETERS) but
#: "Roles" and "WaterMask", which its paint layers replace.
LANDSCAPE_PARAMETERS = ("Imagery", "ImageryWeight", "LandscapeTexels", "ImageryFlipV", "Wetness",
                        "TintTreeCover", "TintCropland", "TintBuiltUp", "TintWetland",
                        "TintMossLichen")
#: M_LandcoverID's parameters, by the names FlightSimRenderCommandlet.cpp sets.
LANDCOVER_PARAMETERS = ("ClassMap", "OriginX", "OriginY", "CellX", "CellY", "GridWidth",
                        "GridHeight", "TerrainStencil")
#: M_Starfield's, by the names FlightSimVisualScene.cpp sets.
STARFIELD_MAP_PARAMETER = "StarMap"
STARFIELD_INTENSITY_PARAMETER = "StarIntensity"
#: M_RainStreaks's, by the names FlightSimVisualScene.cpp sets.
RAIN_PARAMETERS = ("StreakLengthPx", "StreakDirection", "StreakDensity", "StreakPhase")
#: The streak pattern's stated constants: one column every STREAK_SPACING_PX
#: across the fall, STREAK_WIDTH_FRACTION of it lit; a column holds a streak
#: with probability density x STREAK_CELL_VOLUME_M3 (the drops a column of the
#: view samples, a stated choice); each streak repeats every
#: STREAK_PERIOD_FACTOR lengths along the fall, moving STREAK_SPEED_PX_S; a lit
#: streak raises the scene colour by STREAK_GAIN (screen-space rain with a
#: physical length, nothing more).
STREAK_SPACING_PX = 6.0
STREAK_WIDTH_FRACTION = 0.25
STREAK_CELL_VOLUME_M3 = 0.5
STREAK_PERIOD_FACTOR = 4.0
STREAK_SPEED_PX_S = 600.0
STREAK_GAIN = 0.35
#: M_AirframePaint's.
AIRFRAME_PAINT_PARAMETERS = ("PaintColour", "Roughness", "Metallic", "ClearCoat",
                             "ClearCoatRoughness")
AIRFRAME_PAINT_DEFAULTS = {"Roughness": 0.35, "Metallic": 0.0, "ClearCoat": 1.0,
                           "ClearCoatRoughness": 0.1}
#: M_Runway's.
RUNWAY_PARAMETERS = ("Markings", "SurfaceColour", "PaintColour", "Wetness")
#: The non-sRGB default of the linear texture parameters (created below).
LINEAR_DEFAULT_TEXTURE = "T_LinearDefault"

# -- the storm-weather materials (core/scene/storm_weather.py; FlightSimWeather.cpp)

#: Every storm-weather material, by name (one /Game/FlightSim path each).
STORM_MATERIALS = ("M_RainDrops", "M_RainSplash", "M_LightningChannel", "M_StormCell",
                     "M_WindshieldRain")
#: The Custom node bodies, committed as HLSL beside the Python twins they
#: mirror (tests/test_weather.py pins their constants to core/scene/*.py).
WEATHER_SHADER_DIR = "assets/shaders/weather"
#: The parameters FlightSimWeather.cpp sets, by material. A vector
#: parameter carries four floats where its shader input is a float4.
DROPS_PARAMETERS = ("Shift", "FallTime", "BoxHalf", "WindVel", "CamVel", "Shutter",
                        "PixelAngle", "Active", "Weight", "GroundRelZ", "SkyRadianceScale",
                        "FlashLux")
SPLASH_PARAMETERS = ("Time", "Splash", "GroundShift", "GroundRelZ", "DropMm", "Active",
                     "Weight", "SkyRadianceScale", "FlashLux")
LIGHTNING_PARAMETERS = ("PixelAngle", "RadiusCm", "Power")
STORM_PARAMETERS = ("CellCentreCm", "EastAxis", "NorthAxis", "Geo1", "Geo2", "Sigma", "Noise",
                    "Drift", "Layer", "Time", "FlashRelCm", "Flash", "ExtinctionScale")
WINDSHIELD_PARAMETERS = ("Time", "Glass", "Seed")
#: The vector parameters whose shader input is a float4 (RGB appended with A).
WEATHER_FLOAT4_PARAMETERS = ("Splash", "Power", "Geo1", "Geo2", "Sigma", "Noise", "Drift",
                             "Layer", "Flash", "Glass")
#: The storm's albedo default (core/scene/storm_cell.py ALBEDO; the host sets
#: the card's into Flash.z, the material's base colour reads this parameter).
STORM_ALBEDO_PARAMETER = "Albedo"
STORM_ALBEDO_DEFAULT = 0.98
#: The usage flag a volumetric cloud's material MUST carry: the engine
#: compiles a material's cloud shaders (the view pass and the cloud SHADOW
#: pass) only for materials flagged "Used with Volumetric Cloud". Without
#: it the material compiles as a Volume material with no cloud shaders, the
#: cloud shadow mesh pass finds none, falls back to the default SURFACE
#: material and asserts GetMaterialDomain() == MD_Volume
#: (VolumetricCloudRendering.cpp; measured on the owner's 5.7, 2026-10-08:
#: every thunderstorm render crashed there). The engine's own
#: m_SimpleVolumetricCloud carries it; ensure_volumetric_cloud_usage sets
#: it on an M_StormCell built before this line existed.
STORM_USAGE_PROPERTY = "used_with_volumetric_cloud"
#: The light inside the cloud: the VolumetricAdvancedMaterialOutput node's
#: constants. Without that node the engine lights a cloud by single
#: scattering alone -- the far side and the UNDERSIDE of a thick cloud get
#: nothing, so a thunderstorm's base under an 11 km tower renders black
#: (the owner's first storm frame, 2026-10-08: nothing visible). The
#: dual-lobe Henyey-Greenstein phase of water droplets (g 0.8 forward,
#: -0.5 back, blended half and half: Hillaire 2016, Frostbite's clouds)
#: and the multiple-scattering approximation of Wrenninge et al. 2013
#: (two octaves, each attenuating extinction, scattering and the phase's
#: eccentricity by 0.5), the engine's own convention; the ground's albedo
#: lights the bottoms (GroundContribution). Stated, not measured here.
STORM_SCATTERING = {"phase_g": 0.8, "phase_g2": -0.5, "phase_blend": 0.5, "octaves": 2,
                    "contribution": 0.5, "occlusion": 0.5, "eccentricity": 0.5}
#: The node's editor properties, by STORM_SCATTERING key (UE 5.7's
#: MaterialExpressionVolumetricAdvancedMaterialOutput; a name the engine
#: does not know is a RuntimeError naming the node's real ones).
STORM_SCATTERING_PROPERTIES = {
    "phase_g": "const_phase_g", "phase_g2": "const_phase_g2", "phase_blend": "const_phase_blend",
    "octaves": "multi_scattering_approximation_octave_count",
    "contribution": "const_multi_scattering_contribution",
    "occlusion": "const_multi_scattering_occlusion",
    "eccentricity": "const_multi_scattering_eccentricity"}
#: The generation of each storm material this script builds, stamped on
#: the asset as metadata: an existing asset stamped with an older one (or
#: none) is set aside and built again, so a change to a storm material's
#: graph reaches a machine that built the storm before it without anyone
#: remembering FLIGHTSIM_REBUILD_MATERIALS. Bump a material's number with
#: every change to its graph or its shader body -- its own only: a rebuilt
#: M_StormCell recompiles its cloud shaders for a quarter of an hour
#: (measured 2026-10-09), so the rain's change must not cost the cloud's.
#: M_StormCell 2: STORM_SCATTERING (2026-10-08). M_RainDrops 3: the near
#: fade shortened to 30 cm (rain_drop_opacity.hlsl, 2026-10-09); 4 and
#: M_RainSplash 3: lit by the scene instead of a black sky sample (drop_lit).
STORM_GENERATIONS = {"M_RainDrops": "4", "M_RainSplash": "3", "M_LightningChannel": "2",
                     "M_StormCell": "2", "M_WindshieldRain": "2"}
STORM_GENERATION_TAG = "FlightSimStormGeneration"


def add_wetness(material, lib, base_colour_node, base_output, x,
                dry_roughness=None, dry_output=""):
    """The one wet-surface coupling: a scalar parameter "Wetness" (default
    0, the name FlightSimVisualScene.cpp ApplyWetness sets) lerps roughness
    from the dry value -- the constant 0.92, or the surface's own
    roughness node when the caller passes one (the terrain surfaces' per-
    role blend) -- toward 0.25 (wet) and darkens base colour by up to
    30 %. Wires MP_BASE_COLOR and MP_ROUGHNESS; the caller wires nothing
    else to those two."""
    wet = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, x, 400)
    wet.set_editor_property("parameter_name", WETNESS_PARAMETER)
    wet.set_editor_property("default_value", 0.0)
    if dry_roughness is None:
        dry_r = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, x, 250)
        dry_r.set_editor_property("r", ROUGHNESS_DRY)
        dry_output = ""
    else:
        dry_r = dry_roughness
    wet_r = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, x, 300)
    wet_r.set_editor_property("r", ROUGHNESS_WET)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionLinearInterpolate, x + 200, 250)
    lib.connect_material_expressions(dry_r, dry_output, rough, "A")
    lib.connect_material_expressions(wet_r, "", rough, "B")
    lib.connect_material_expressions(wet, "", rough, "Alpha")
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    darken = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, x, 500)
    darken.set_editor_property("r", WET_DARKENING)
    scale = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, x + 200, 450)
    lib.connect_material_expressions(wet, "", scale, "A")
    lib.connect_material_expressions(darken, "", scale, "B")
    one_minus = lib.create_material_expression(
        material, unreal.MaterialExpressionOneMinus, x + 350, 450)
    lib.connect_material_expressions(scale, "", one_minus, "")
    colour = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, x + 500, 0)
    lib.connect_material_expressions(base_colour_node, base_output, colour, "A")
    lib.connect_material_expressions(one_minus, "", colour, "B")
    lib.connect_material_property(colour, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)


def create_vertex_colour():
    full = f"{PATH}/M_VertexColor"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_VertexColor", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    vertex = lib.create_material_expression(
        material, unreal.MaterialExpressionVertexColor, -350, 0)
    add_wetness(material, lib, vertex, "", -350)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_terrain_imagery():
    """The terrain surface (the module comment): the drape textured by the
    roles' ground textures, snowed, watered, then the wetness coupling,
    which owns the base colour and the roughness. Not run without an
    engine: the node and pin names are the UE Python API's, checked on
    Windows."""
    full = f"{PATH}/M_TerrainImagery"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_TerrainImagery", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    colour, roughness = terrain_imagery_graph(material, lib)
    add_wetness(material, lib, colour, "", 1200, dry_roughness=roughness)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")




def create_vertex_colour_unlit():
    """Made for the tornado funnel: a MARKER must read from every side
    under any sun, so it is UNLIT -- vertex colour straight into emissive.
    (Measured: the lit vertex-colour material rendered the funnel black
    whenever the camera faced its unlit side, i.e. most of every chase
    shot in the storm look's low sun.) This one rendered it black as well
    (NEXT.md gotcha 26), so the funnel ships on the engine's default
    material and nothing loads this; it stays for that open question."""
    full = f"{PATH}/M_VertexColorUnlit"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_VertexColorUnlit", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("shading_model",
                                 unreal.MaterialShadingModel.MSM_UNLIT)
    lib = unreal.MaterialEditingLibrary
    vertex = lib.create_material_expression(
        material, unreal.MaterialExpressionVertexColor, -350, 0)
    lib.connect_material_property(vertex, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_custom_stencil_id():
    """The ID pass's post-process material (Phase 2, contracts section 1).

    Post-process domain, blendable location "Replacing the Tonemapper",
    one SceneTexture expression reading CustomStencil into emissive
    colour. Nothing else: no tonemapping, no exposure, no dither, so the
    value that reaches the RTF_R32f target is the stencil integer the
    commandlet assigned (verified on Windows by the first -labels frame:
    render.json labels.non_integer_id_pixels == 0 and numpy.unique of
    frame_0000_mask.png is a subset of the card's objects[].int_id + 0).
    """
    full = f"{PATH}/M_CustomStencilID"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_CustomStencilID", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("material_domain",
                                 unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property(
        "blendable_location",
        unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    stencil = lib.create_material_expression(
        material, unreal.MaterialExpressionSceneTexture, -400, 0)
    stencil.set_editor_property("scene_texture_id",
                                unreal.SceneTextureId.PPI_CUSTOM_STENCIL)
    lib.connect_material_property(stencil, "Color",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_pass_material(name, scene_texture_id, signed):
    """One ground-truth pass material (I6): the M_CustomStencilID shape
    -- post-process domain, blendable location "Replacing the
    Tonemapper", one SceneTexture node into emissive colour -- with, for
    a SIGNED texture, the offset encoding value * SIGNED_SCALE +
    SIGNED_OFFSET wired through a Multiply and an Add so the readback
    never depends on a negative emissive surviving the chain. Nothing
    tone-maps, exposes or dithers the value. Not run without an engine:
    the node and pin names are the UE Python API's, checked on Windows.
    """
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    material.set_editor_property("material_domain",
                                 unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property(
        "blendable_location",
        unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    texture = lib.create_material_expression(
        material, unreal.MaterialExpressionSceneTexture, -600, 0)
    texture.set_editor_property("scene_texture_id",
                                getattr(unreal.SceneTextureId, scene_texture_id))
    if signed:
        scale = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -600, 200)
        scale.set_editor_property("r", SIGNED_SCALE)
        offset = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -400, 200)
        offset.set_editor_property("r", SIGNED_OFFSET)
        scaled = lib.create_material_expression(
            material, unreal.MaterialExpressionMultiply, -400, 0)
        lib.connect_material_expressions(texture, "Color", scaled, "A")
        lib.connect_material_expressions(scale, "", scaled, "B")
        encoded = lib.create_material_expression(
            material, unreal.MaterialExpressionAdd, -200, 0)
        lib.connect_material_expressions(scaled, "", encoded, "A")
        lib.connect_material_expressions(offset, "", encoded, "B")
        lib.connect_material_property(encoded, "",
                                      unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    else:
        lib.connect_material_property(texture, "Color",
                                      unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_world_normal_pass():
    create_pass_material(*PASS_MATERIALS["normal"])


def create_velocity_pass():
    create_pass_material(*PASS_MATERIALS["velocity"])


def create_base_colour_pass():
    create_pass_material(*PASS_MATERIALS["albedo"])


def create_world_normal_fallback():
    """S4: M_WorldNormal, SceneTexture:WorldNormal straight into emissive."""
    name, scene_texture_id = LINEAR_MATERIALS["normal_fallback"]
    create_pass_material(name, scene_texture_id, False)


def create_velocity_check():
    """S4: M_Velocity, SceneTexture:Velocity straight into emissive."""
    name, scene_texture_id = LINEAR_MATERIALS["velocity_check"]
    create_pass_material(name, scene_texture_id, False)


def create_grey_card():
    """S4: the calibration frame's card. Lit (the default shading model),
    roughness 1, metallic 0, specular 0 -- a Lambertian with no specular
    lobe -- with the "Reflectance" scalar into base colour and the
    "Luminance" scalar (cd/m^2) into emissive. Not run without an engine:
    the node and pin names are the UE Python API's, checked on Windows."""
    full = f"{PATH}/M_GreyCard"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        print(f"MATERIAL-EXISTS: {full}")
        return

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset("M_GreyCard", PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit("could not create material asset")

    lib = unreal.MaterialEditingLibrary
    reflectance = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 0)
    reflectance.set_editor_property("parameter_name", GREY_CARD_REFLECTANCE_PARAMETER)
    reflectance.set_editor_property("default_value", GREY_CARD_REFLECTANCE_DEFAULT)
    lib.connect_material_property(reflectance, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    luminance = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 200)
    luminance.set_editor_property("parameter_name", GREY_CARD_LUMINANCE_PARAMETER)
    luminance.set_editor_property("default_value", 0.0)
    lib.connect_material_property(luminance, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    for value, prop, y in ((GREY_CARD_ROUGHNESS, unreal.MaterialProperty.MP_ROUGHNESS, 400),
                           (GREY_CARD_METALLIC, unreal.MaterialProperty.MP_METALLIC, 500),
                           (GREY_CARD_SPECULAR, unreal.MaterialProperty.MP_SPECULAR, 600)):
        constant = lib.create_material_expression(
            material, unreal.MaterialExpressionConstant, -400, y)
        constant.set_editor_property("r", value)
        lib.connect_material_property(constant, "", prop)
    lib.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


# -- W5: the world materials -----------------------------------------------------

def after_tonemapping():
    """Where the beauty capture's screen-space looks (M_RainStreaks,
    M_LensDrops) run: after the tonemapper, at the output resolution. They
    ran at BL_SCENE_COLOR_AFTER_DOF -- the render resolution, before TSR
    and bloom -- and the owner's rain frames (2026-10-08) carried a blurred
    tan border all round the image. Suspected, not measured: such a pass
    writes only the view rect of a pooled texture larger than it, and TSR
    and bloom blur the stale band beyond inward. After the tonemapper the
    pass reads and writes the final image itself. UE 5.x names the
    location BL_SCENE_COLOR_AFTER_TONEMAPPING; the old name is the fallback."""
    return (getattr(unreal.BlendableLocation, "BL_SCENE_COLOR_AFTER_TONEMAPPING", None)
            or getattr(unreal.BlendableLocation, "BL_AFTER_TONEMAPPING"))


def move_after_tonemapping(name):
    """True when /Game/FlightSim/<name> already exists: its graph is kept
    and only its blendable location is moved to after_tonemapping() in
    place (this script otherwise skips existing assets, so a machine that
    built the material before the move would keep the old location)."""
    full = f"{PATH}/{name}"
    if not unreal.EditorAssetLibrary.does_asset_exist(full) or rebuild_requested(name):
        return False   # absent, or FLIGHTSIM_REBUILD_MATERIALS: built again below
    material = unreal.EditorAssetLibrary.load_asset(full)
    location = after_tonemapping()
    if material.get_editor_property("blendable_location") == location:
        print(f"MATERIAL-EXISTS: {full}")
        return True
    material.set_editor_property("blendable_location", location)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-UPDATED: {full} (blendable location: after the tonemapper)")
    return True


def rebuild_requested(name):
    """FLIGHTSIM_REBUILD_MATERIALS=all or a comma list of names: an existing
    asset is deleted and built again (the script otherwise skips what
    exists, so a material built by an older script keeps its old graph)."""
    import os
    wanted = os.environ.get("FLIGHTSIM_REBUILD_MATERIALS", "").strip()
    if not wanted:
        return False
    names = {token.strip() for token in wanted.split(",")}
    return "all" in names or name in names


def new_material(name):
    """Create /Game/FlightSim/<name> once; None when it already exists
    (unless rebuild_requested: then it is deleted and built again)."""
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        if rebuild_requested(name) and unreal.EditorAssetLibrary.delete_asset(full):
            print(f"MATERIAL-REBUILT: {full} (deleted on FLIGHTSIM_REBUILD_MATERIALS)")
        else:
            print(f"MATERIAL-EXISTS: {full}")
            return None
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit(f"could not create material asset {name}")
    return material


def finish(material, name):
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(f"{PATH}/{name}")
    print(f"MATERIAL-CREATED: {PATH}/{name}")


def linear_default_texture():
    """The non-sRGB default of the linear texture parameters: a texture
    parameter compiles only with a default of its own sampler class."""
    full = f"{PATH}/{LINEAR_DEFAULT_TEXTURE}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        return unreal.load_asset(full)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    texture = tools.create_asset(LINEAR_DEFAULT_TEXTURE, PATH, unreal.Texture2D,
                                 unreal.Texture2DFactoryNew())
    texture.set_editor_property("srgb", False)
    texture.set_editor_property("compression_settings",
                                unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    unreal.EditorAssetLibrary.save_asset(full)
    return texture


def scalar(material, lib, name, default, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionScalarParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", default)
    return node


def vector(material, lib, name, default, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionVectorParameter, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("default_value", unreal.LinearColor(*default))
    return node


def texture_parameter(material, lib, name, linear, x, y, default=None, normal_map=False):
    """A TextureSampleParameter2D: sRGB colour, or linear colour with the
    non-sRGB default (codes, markings and luminance are data, not colour),
    or a normal map (the engine's Normal sampler: x, y from R, G, z
    derived). A default texture given replaces the sampler class's own
    (a texture parameter compiles only with a default of its sampler's
    class: the terrain defaults are made to match)."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionTextureSampleParameter2D,
                                          x, y)
    node.set_editor_property("parameter_name", name)
    if normal_map:
        node.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL)
    elif linear:
        node.set_editor_property("sampler_type", unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR)
        node.set_editor_property("texture", linear_default_texture())
    if default is not None:
        node.set_editor_property("texture", default)
    return node


def binary(material, lib, kind, a, b, x, y, a_out="", b_out=""):
    node = lib.create_material_expression(material, kind, x, y)
    lib.connect_material_expressions(a, a_out, node, "A")
    lib.connect_material_expressions(b, b_out, node, "B")
    return node


def constant(material, lib, value, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionConstant, x, y)
    node.set_editor_property("r", value)
    return node


def mask(material, lib, source, channel, x, y, source_out=""):
    """A ComponentMask of one channel ("r") or several ("rg")."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionComponentMask, x, y)
    for flag in ("r", "g", "b", "a"):
        node.set_editor_property(flag, flag in channel)
    lib.connect_material_expressions(source, source_out, node, "")
    return node


def unary(material, lib, kind, source, x, y, source_out=""):
    """A one-input node (OneMinus, Saturate, Normalize) over source."""
    node = lib.create_material_expression(material, kind, x, y)
    lib.connect_material_expressions(source, source_out, node, "")
    return node


def lerp(material, lib, a, b, alpha, x, y, a_out="", b_out="", alpha_out=""):
    node = lib.create_material_expression(material, unreal.MaterialExpressionLinearInterpolate, x, y)
    lib.connect_material_expressions(a, a_out, node, "A")
    lib.connect_material_expressions(b, b_out, node, "B")
    lib.connect_material_expressions(alpha, alpha_out, node, "Alpha")
    return node


def constant3(material, lib, rgb, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, x, y)
    node.set_editor_property("constant", unreal.LinearColor(rgb[0], rgb[1], rgb[2], 1.0))
    return node


#: The If node's three result pins, by the names an engine may give them
#: (measured on the owner's 5.7, 2026-10-08: "A>B" connected NOTHING --
#: connect_material_expressions returned False silently -- and every
#: material built on it failed to compile with "Missing If AGreaterThanB
#: input", drawing the default material). Each pin is tried under every
#: name until the engine accepts one, and a pin no name connects is an
#: error naming the pins the engine actually has.
IF_PIN_NAMES = (("A > B", "A>B", "AGreaterThanB"), ("A == B", "A==B", "AEqualsB"),
                ("A < B", "A<B", "ALessThanB"))


def connect(lib, source, source_out, node, names):
    """Connect ``source`` to the first of ``names`` the node accepts; the
    names it does have on failure (never a silent no-op)."""
    if isinstance(names, str):
        names = (names,)
    for name in names:
        if lib.connect_material_expressions(source, source_out, node, name):
            return name
    have = []
    try:
        lib.get_inputs_for_material_expression(node, have)
    except Exception:   # an engine without the lister: the names stay unknown
        have = ["(unlisted)"]
    raise RuntimeError(f"no input named {list(names)} on {node.get_class().get_name()}; "
                       f"its inputs are {list(have)}")


def select_if(material, lib, a, b, greater, equal, less, x, y):
    """1/0 from an If node: A > B -> greater, A == B -> equal, A < B -> less."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionIf, x, y)
    connect(lib, a, "", node, "A")
    connect(lib, b, "", node, "B")
    for names, value in zip(IF_PIN_NAMES, (greater, equal, less)):
        connect(lib, constant(material, lib, value, x - 150, y), "", node, names)
    return node


def in_unit_interval(material, lib, value, x, y):
    """1 where 0 <= value < 1, else 0 (off the grid is no class)."""
    zero = constant(material, lib, 0.0, x - 300, y)
    one = constant(material, lib, 1.0, x - 300, y + 60)
    low = select_if(material, lib, value, zero, 1.0, 1.0, 0.0, x, y)
    high = select_if(material, lib, value, one, 0.0, 0.0, 1.0, x, y + 120)
    return binary(material, lib, unreal.MaterialExpressionMultiply, low, high, x + 200, y)


# -- the terrain surface: M_TerrainImagery, M_TerrainImageryNight, M_Landscape --

def _flat_png(name, texel):
    """A 4 x 4 8-bit RGBA PNG of one texel, written with the standard
    library (the engine's Python has no imaging library) into a scratch
    directory; its path. The one way this script makes a texture whose
    content it KNOWS."""
    import struct
    import tempfile
    import zlib
    from pathlib import Path
    size = 4
    raw = b"".join(b"\x00" + bytes(texel) * size for _ in range(size))

    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    path = Path(tempfile.mkdtemp(prefix="flightsim_materials_")) / f"{name}.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw))
                     + chunk(b"IEND", b""))
    return path


def _repo_file(relative):
    """A committed file by its repository-relative path: under this
    script's parent directory (the checkout it runs from) or the working
    directory; None when neither has it."""
    from pathlib import Path
    roots = []
    try:
        roots.append(Path(__file__).resolve().parents[1])
    except NameError:   # the engine ran the text without a __file__
        pass
    roots.append(Path.cwd())
    for root in roots:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    return None


def import_texture(source, name, srgb, normal_map, flat, zero_alpha=False):
    """Import one PNG as /Game/FlightSim/<name> (scripts/ue_build_scene.py's
    _import_texture idiom): an sRGB colour, a linear data map (no sRGB
    curve, uncompressed 8 bits) or a normal map (TC_Normalmap, whose
    Normal sampler unpacks x, y from R, G). A flat texel takes no mips;
    a bitmap keeps the texture group's. A zero_alpha PNG (T_RolesValley,
    (255, 0, 0, 0)) goes through its own TextureFactory with the
    importer's zero-alpha fill off, so its texels arrive as written; an
    engine whose Python has no such option is told so and imports it
    through the default factory, and whether that leaves the texels
    untouched is the first Windows check of these defaults. A failed
    import is a RuntimeError the creator guard reports by name, not an
    exit: the other materials still build."""
    task = unreal.AssetImportTask()
    task.set_editor_property("filename", str(source))
    task.set_editor_property("destination_path", PATH)
    task.set_editor_property("destination_name", name)
    task.set_editor_property("automated", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("save", False)
    if zero_alpha:
        try:
            factory = unreal.TextureFactory()
            factory.set_editor_property("fill_png_zero_alpha", False)
        except Exception:   # not this engine's name: said, not hidden
            print(f"MATERIAL-NOTE: {name} is a zero-alpha PNG and this engine's Python has no "
                  f"TextureFactory.fill_png_zero_alpha; whether the default import leaves its "
                  f"texels untouched is the first Windows check")
        else:
            task.set_editor_property("factory", factory)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    full = f"{PATH}/{name}"
    texture = unreal.load_asset(full)
    if texture is None:
        raise RuntimeError(f"{source} did not import as {full}")
    texture.set_editor_property("srgb", bool(srgb))
    if normal_map:
        texture.set_editor_property("compression_settings",
                                    unreal.TextureCompressionSettings.TC_NORMALMAP)
    elif not srgb:
        texture.set_editor_property("compression_settings",
                                    unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP)
    if flat:
        texture.set_editor_property("mip_gen_settings",
                                    unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
    unreal.EditorAssetLibrary.save_asset(full)
    return texture


def default_texture(name):
    """/Game/FlightSim/<name> once (TERRAIN_DEFAULT_TEXTURES): the committed
    bitmap when the checkout has it, else the flat known texel, said so."""
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        return unreal.load_asset(full)
    committed, texel, srgb, normal_map = TERRAIN_DEFAULT_TEXTURES[name]
    source = _repo_file(committed) if committed else None
    flat = source is None
    if flat:
        if committed:
            print(f"MATERIAL-NOTE: {committed} is not on this checkout; {name} is the flat "
                  f"texel {texel}")
        source = _flat_png(name, texel)
    return import_texture(source, name, srgb, normal_map, flat, zero_alpha=flat and texel[3] == 0)


def terrain_texture(material, lib, name, x, y, default=None):
    """One terrain sampler by its contract name: the sampler type from
    TERRAIN_TEXTURE_PARAMETERS, the default from TERRAIN_TEXTURE_DEFAULTS
    (or the asset name given)."""
    kind = TERRAIN_TEXTURE_PARAMETERS[name]
    default_name = default or TERRAIN_TEXTURE_DEFAULTS.get(name)
    return texture_parameter(material, lib, name, kind == "linear", x, y,
                             default=default_texture(default_name) if default_name else None,
                             normal_map=kind == "normal")


def terrain_scalar(material, lib, name, x, y):
    return scalar(material, lib, name, TERRAIN_SCALAR_PARAMETERS[name], x, y)


def world_metres_uv(material, lib, world_xy, metres, x, y):
    """Square world-metre tiling: AbsoluteWorldPosition.xy / (metres * 100),
    the engine's centimetres -- the snow and the noise (square bitmaps)
    tile on the ground, not on the drape grid. The detail tiles through
    detail_uv, which has an aspect."""
    centimetres = binary(material, lib, unreal.MaterialExpressionMultiply, metres,
                         constant(material, lib, 100.0, x, y + 60), x + 150, y)
    return binary(material, lib, unreal.MaterialExpressionDivide, world_xy, centimetres, x + 300, y)


def detail_uv(material, lib, world_xy, metres, aspect, x, y):
    """A role's detail tiling, AppendVector(x / (metres * 100 * aspect),
    y / (metres * 100)): the tile's height spans "DetailMetres<Role>" on
    the ground (one scalar per role, the sidecar's contract) and its
    width aspect times that (TERRAIN_DETAIL_ASPECT, the PNG's
    width / height), so a 512 x 256 tile is not squeezed square."""
    centimetres = binary(material, lib, unreal.MaterialExpressionMultiply, metres,
                         constant(material, lib, 100.0, x, y + 60), x + 150, y)
    wide = binary(material, lib, unreal.MaterialExpressionMultiply, centimetres,
                  constant(material, lib, aspect, x + 150, y + 120), x + 300, y + 60)
    u = binary(material, lib, unreal.MaterialExpressionDivide,
               mask(material, lib, world_xy, "r", x + 300, y - 60), wide, x + 450, y)
    v = binary(material, lib, unreal.MaterialExpressionDivide,
               mask(material, lib, world_xy, "g", x + 300, y + 180), centimetres, x + 450, y + 120)
    return binary(material, lib, unreal.MaterialExpressionAppendVector, u, v, x + 600, y + 60)


def terrain_role_samples(material, lib, world_xy, x, y):
    """Per role (TERRAIN_ROLES), at the role's world-metre tiling
    "DetailMetres<Role>" by TERRAIN_DETAIL_ASPECT (detail_uv): the detail
    albedo "Detail<Role>" (RGB), its neutral (TERRAIN_DETAIL_NEUTRAL, a
    constant), the tangent normal "Normal<Role>" (RGB) and the roughness
    "Roughness<Role>"."""
    samples = {}
    for index, role in enumerate(TERRAIN_ROLES):
        title = role.capitalize()
        row = y + index * 320
        metres = terrain_scalar(material, lib, f"DetailMetres{title}", x, row)
        uv = detail_uv(material, lib, world_xy, metres, TERRAIN_DETAIL_ASPECT[role], x + 150, row)
        detail = terrain_texture(material, lib, f"Detail{title}", x + 950, row)
        lib.connect_material_expressions(uv, "", detail, "UVs")
        normal = terrain_texture(material, lib, f"Normal{title}", x + 950, row + 160)
        lib.connect_material_expressions(uv, "", normal, "UVs")
        samples[role] = {
            "detail": detail,
            "neutral": constant3(material, lib, TERRAIN_DETAIL_NEUTRAL[role], x + 1200, row),
            "normal": normal,
            "roughness": terrain_scalar(material, lib, f"Roughness{title}", x + 1200, row + 100),
        }
    return samples


def weighted_sum(material, lib, terms, x, y):
    """sum of weight * value over (weight, weight_out, value, value_out)."""
    total = None
    for index, (weight, weight_out, value, value_out) in enumerate(terms):
        term = binary(material, lib, unreal.MaterialExpressionMultiply, weight, value,
                      x, y + index * 80, a_out=weight_out, b_out=value_out)
        total = term if total is None else binary(
            material, lib, unreal.MaterialExpressionAdd, total, term, x + 150, y + index * 80)
    return total


def terrain_surface(material, lib, samples, base, base_out, imagery, imagery_out,
                    detail, neutral, normal, roughness, water, water_out,
                    snow_cover, snow_out, world_xy, x, y, detail_scale=None):
    """The terrain graph after the role blend (the module comment): the
    distance-faded detail modulation, the weather snow, the water
    override, the normal into MP_NORMAL. Returns (colour, roughness) for
    add_wetness, which owns the base colour and the roughness.

    base / imagery: the macro albedo the detail modulates and the drape
    the water takes (one node in the tile materials); detail, neutral,
    normal, roughness: the role-weighted sums (RGB, RGB, RGB, scalar; the
    default output); water, snow_cover: the masks 0..1; detail_scale: an
    extra factor on the modulation (M_Landscape's ImageryWeight) or
    None."""
    multiply, add, subtract, divide = (unreal.MaterialExpressionMultiply, unreal.MaterialExpressionAdd,
                                       unreal.MaterialExpressionSubtract, unreal.MaterialExpressionDivide)
    # fade = 1 - saturate((PixelDepth - start * 100) / ((end - start) * 100)).
    depth = lib.create_material_expression(material, unreal.MaterialExpressionPixelDepth, x, y)
    start = terrain_scalar(material, lib, "DetailFadeStartM", x, y + 100)
    end = terrain_scalar(material, lib, "DetailFadeEndM", x, y + 160)
    hundred = constant(material, lib, 100.0, x, y + 220)
    fade = unary(material, lib, unreal.MaterialExpressionOneMinus,
                 unary(material, lib, unreal.MaterialExpressionSaturate,
                       binary(material, lib, divide,
                              binary(material, lib, subtract, depth,
                                     binary(material, lib, multiply, start, hundred, x + 150, y + 100),
                                     x + 300, y),
                              binary(material, lib, multiply,
                                     binary(material, lib, subtract, end, start, x + 150, y + 160),
                                     hundred, x + 300, y + 160),
                              x + 450, y),
                       x + 600, y),
                 x + 750, y)
    strength = binary(material, lib, multiply,
                      terrain_scalar(material, lib, "DetailStrength", x + 750, y + 100),
                      fade, x + 900, y)
    if detail_scale is not None:
        strength = binary(material, lib, multiply, strength, detail_scale, x + 1050, y)
    # colour = base * lerp(1, detail / neutral, strength).
    modulation = lerp(material, lib, constant(material, lib, 1.0, x + 1050, y + 200),
                      binary(material, lib, divide, detail, neutral, x + 1050, y + 260),
                      strength, x + 1200, y + 200)
    colour = binary(material, lib, multiply, base, modulation, x + 1350, y + 200, a_out=base_out)
    # The weather snow: a thresholded level with noise jitter, times the
    # linear ramp in cos(slope), through the albedo's own threshold.
    sy = y + 500
    up = mask(material, lib,
              lib.create_material_expression(material, unreal.MaterialExpressionVertexNormalWS, x, sy),
              "b", x + 150, sy)
    low = terrain_scalar(material, lib, "SnowSlopeLowCos", x, sy + 100)
    high = terrain_scalar(material, lib, "SnowSlopeHighCos", x, sy + 160)
    ramp = unary(material, lib, unreal.MaterialExpressionSaturate,
                 binary(material, lib, divide,
                        binary(material, lib, subtract, up, low, x + 300, sy),
                        binary(material, lib, subtract, high, low, x + 300, sy + 100),
                        x + 450, sy),
                 x + 600, sy)
    noise = terrain_texture(material, lib, "Noise", x + 450, sy + 250)
    lib.connect_material_expressions(
        world_metres_uv(material, lib, world_xy,
                        terrain_scalar(material, lib, "NoiseMetres", x, sy + 250), x + 100, sy + 250),
        "", noise, "UVs")
    band = terrain_scalar(material, lib, "SnowBand", x, sy + 400)
    half = constant(material, lib, 0.5, x, sy + 460)
    jitter = binary(material, lib, multiply, band,
                    binary(material, lib, subtract, noise, half, x + 650, sy + 250, a_out="R"),
                    x + 800, sy + 250)
    w0 = unary(material, lib, unreal.MaterialExpressionSaturate,
               binary(material, lib, add,
                      binary(material, lib, divide,
                             binary(material, lib, add,
                                    binary(material, lib, subtract, snow_cover, half,
                                           x + 650, sy + 400, a_out=snow_out),
                                    jitter, x + 950, sy + 300),
                             band, x + 1100, sy + 300),
                      half, x + 1250, sy + 300),
               x + 1400, sy + 300)
    coverage = binary(material, lib, multiply, w0, ramp, x + 1550, sy)
    snow_uv = world_metres_uv(material, lib, world_xy,
                              terrain_scalar(material, lib, "SnowMetres", x, sy + 600), x + 100, sy + 600)
    snow_albedo = terrain_texture(material, lib, "SnowAlbedo", x + 450, sy + 600)
    lib.connect_material_expressions(snow_uv, "", snow_albedo, "UVs")
    snow_normal = terrain_texture(material, lib, "SnowNormal", x + 450, sy + 800)
    lib.connect_material_expressions(snow_uv, "", snow_normal, "UVs")
    # cov = saturate(2 * coverage - 1 + SnowAlbedo.a).
    cov = unary(material, lib, unreal.MaterialExpressionSaturate,
                binary(material, lib, add,
                       binary(material, lib, subtract,
                              binary(material, lib, multiply, coverage,
                                     constant(material, lib, 2.0, x + 1550, sy + 100), x + 1700, sy),
                              constant(material, lib, 1.0, x + 1700, sy + 100), x + 1850, sy),
                       snow_albedo, x + 2000, sy, b_out="A"),
                x + 2150, sy)
    colour = lerp(material, lib, colour, snow_albedo, cov, x + 2300, y + 200, b_out="RGB")
    normal = lerp(material, lib, normal, snow_normal, cov, x + 2300, y + 400, b_out="RGB")
    roughness = lerp(material, lib, roughness, samples["snow"]["roughness"], cov, x + 2300, y + 600)
    # The water override: the drape's own colour, near-mirror, flat.
    colour = lerp(material, lib, colour, imagery, water, x + 2500, y + 200,
                  b_out=imagery_out, alpha_out=water_out)
    roughness = lerp(material, lib, roughness,
                     terrain_scalar(material, lib, "RoughnessWater", x + 2300, y + 700),
                     water, x + 2500, y + 600, alpha_out=water_out)
    normal = lerp(material, lib, normal, constant3(material, lib, (0.0, 0.0, 1.0), x + 2300, y + 500),
                  water, x + 2500, y + 400, alpha_out=water_out)
    lib.connect_material_property(
        unary(material, lib, unreal.MaterialExpressionNormalize, normal, x + 2700, y + 400), "",
        unreal.MaterialProperty.MP_NORMAL)
    return colour, roughness


def terrain_imagery_graph(material, lib):
    """The graph M_TerrainImagery and M_TerrainImageryNight share (the
    module comment): the drape on UV0, the Roles map's weights over the
    role samples, the masks on UV0, then terrain_surface. Returns
    (colour, roughness) for add_wetness."""
    imagery = terrain_texture(material, lib, "Imagery", -2600, 0)
    roles = terrain_texture(material, lib, "Roles", -2600, 300)
    weights = {}
    # The sampler's default output is RGB, a float3 with no A to mask: the
    # four channels come off its RGBA pin.
    for index, (role, channel) in enumerate(zip(TERRAIN_ROLES[:4], "rgba")):
        weights[role] = mask(material, lib, roles, channel, -2400, 300 + index * 80,
                             source_out="RGBA")
    # snow = saturate(1 - R - G - B - A): the remainder.
    used = binary(material, lib, unreal.MaterialExpressionAdd,
                  binary(material, lib, unreal.MaterialExpressionAdd,
                         weights["valley"], weights["scrub"], -2250, 300),
                  binary(material, lib, unreal.MaterialExpressionAdd,
                         weights["rock"], weights["cliff"], -2250, 460),
                  -2100, 380)
    weights["snow"] = unary(material, lib, unreal.MaterialExpressionSaturate,
                            unary(material, lib, unreal.MaterialExpressionOneMinus, used, -1950, 380),
                            -1800, 380)
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -2600, 700)
    world_xy = mask(material, lib, world, "rg", -2450, 700)
    samples = terrain_role_samples(material, lib, world_xy, -2300, 800)
    blend = {}
    for index, (quantity, out) in enumerate((("detail", "RGB"), ("neutral", ""),
                                             ("normal", "RGB"), ("roughness", ""))):
        blend[quantity] = weighted_sum(
            material, lib, [(weights[role], "", samples[role][quantity], out) for role in TERRAIN_ROLES],
            -1000, index * 450)
    snow_cover = terrain_texture(material, lib, "SnowCover", -2600, 2600)
    water = terrain_texture(material, lib, "WaterMask", -2600, 2850)
    return terrain_surface(material, lib, samples, imagery, "RGB", imagery, "RGB",
                           blend["detail"], blend["neutral"], blend["normal"], blend["roughness"],
                           water, "R", snow_cover, "R", world_xy, -400, 0)


def create_landscape():
    """W5: M_Landscape -- the terrain surface on the Landscape's paint
    layers (the module comment): five LandscapeLayerBlends (the land-
    cover albedo, the detail and its neutral, the normal, the roughness),
    each layer's inputs a drape role's samples under its tint
    (LANDSCAPE_LAYER_ROLES); the albedo lerped toward the drape by
    "ImageryWeight" (LANDSCAPE_IMAGERY_WEIGHT, 0: the layers alone until
    the scene script sets 1.0 with a drape), the modulation scaled by
    it; the permanent_water layer's weight as the water mask; then the
    weather snow and the wetness coupling as the tile materials."""
    material = new_material("M_Landscape")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -3300, 0)
    world_xy = mask(material, lib, world, "rg", -3150, 0)
    samples = terrain_role_samples(material, lib, world_xy, -3000, 200)
    tints = {name: vector(material, lib, name, LANDSCAPE_TINT_DEFAULTS[name] + (1.0,), -3000, 1900 + i * 100)
             for i, name in enumerate(LANDSCAPE_TINT_DEFAULTS)}
    blends = {}
    for index, quantity in enumerate(("albedo", "detail", "neutral", "normal", "roughness")):
        blend = lib.create_material_expression(material, unreal.MaterialExpressionLandscapeLayerBlend,
                                               -1200, index * 300)
        inputs = []
        for key in LANDSCAPE_LAYERS:
            layer = unreal.LayerBlendInput()
            layer.set_editor_property("layer_name", key)
            layer.set_editor_property("blend_type", unreal.LandscapeLayerBlendType.LB_WEIGHT_BLEND)
            inputs.append(layer)
        blend.set_editor_property("layers", inputs)
        blends[quantity] = blend
    # The drape across the whole Landscape: LandscapeLayerCoords / the
    # texel count, the rows flipped when written north-up; the snow cover
    # on the same UV.
    coords = lib.create_material_expression(material, unreal.MaterialExpressionLandscapeLayerCoords,
                                            -2200, 2600)
    texels = scalar(material, lib, "LandscapeTexels", 1.0, -2200, 2700)
    uv = binary(material, lib, unreal.MaterialExpressionDivide, coords, texels, -2000, 2600)
    u = mask(material, lib, uv, "r", -1850, 2600)
    v = mask(material, lib, uv, "g", -1850, 2700)
    flip = scalar(material, lib, "ImageryFlipV", 0.0, -1850, 2800)
    v_used = lerp(material, lib, v, unary(material, lib, unreal.MaterialExpressionOneMinus, v, -1700, 2750),
                  flip, -1550, 2700)
    drape_uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v_used, -1400, 2650)
    imagery = terrain_texture(material, lib, "Imagery", -1200, 2600, default="T_ImageryGrey")
    lib.connect_material_expressions(drape_uv, "", imagery, "UVs")
    snow_cover = terrain_texture(material, lib, "SnowCover", -1200, 2850)
    lib.connect_material_expressions(drape_uv, "", snow_cover, "UVs")
    one = constant3(material, lib, (1.0, 1.0, 1.0), -1700, 0)
    flat = constant3(material, lib, (0.0, 0.0, 1.0), -1700, 100)
    for index, key in enumerate(LANDSCAPE_LAYERS):
        role, tint_name = LANDSCAPE_LAYER_ROLES[key]
        row = 200 + index * 120
        if role in samples:
            sample = samples[role]
            albedo, albedo_out = sample["detail"], "RGB"
            neutral = sample["neutral"]
            if tint_name is not None:
                albedo = binary(material, lib, unreal.MaterialExpressionMultiply, tints[tint_name],
                                sample["detail"], -1550, row, b_out="RGB")
                albedo_out = ""
                neutral = binary(material, lib, unreal.MaterialExpressionMultiply, tints[tint_name],
                                 sample["neutral"], -1550, row + 60)
            inputs = (("albedo", albedo, albedo_out), ("detail", albedo, albedo_out),
                      ("neutral", neutral, ""), ("normal", sample["normal"], "RGB"),
                      ("roughness", sample["roughness"], ""))
        else:
            # Water and nodata: the drape itself as the albedo, a neutral
            # detail (1 / 1), a flat normal, the valley roughness (the
            # water override sets water's own).
            inputs = (("albedo", imagery, "RGB"), ("detail", one, ""), ("neutral", one, ""),
                      ("normal", flat, ""), ("roughness", samples["valley"]["roughness"], ""))
        for quantity, node, out in inputs:
            lib.connect_material_expressions(node, out, blends[quantity], f"Layer {key}")
    water = lib.create_material_expression(material, unreal.MaterialExpressionLandscapeLayerSample,
                                           -1200, 1600)
    water.set_editor_property("parameter_name", "permanent_water")
    weight = scalar(material, lib, "ImageryWeight", LANDSCAPE_IMAGERY_WEIGHT, -900, 2600)
    base = lerp(material, lib, blends["albedo"], imagery, weight, -700, 2500, b_out="RGB")
    colour, roughness = terrain_surface(material, lib, samples, base, "", imagery, "RGB",
                                        blends["detail"], blends["neutral"], blends["normal"],
                                        blends["roughness"], water, "", snow_cover, "R",
                                        world_xy, -500, 0, detail_scale=weight)
    add_wetness(material, lib, colour, "", 2500, dry_roughness=roughness)
    finish(material, "M_Landscape")


def create_landcover_id():
    """W5: M_LandcoverID -- the land-cover ID pass (see the module comment):
    post-process, replacing the tonemapper, the class code where the
    custom stencil is the terrain's, 0 elsewhere and off the grid."""
    material = new_material("M_LandcoverID")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location",
                                 unreal.BlendableLocation.BL_REPLACING_TONEMAPPER)
    lib = unreal.MaterialEditingLibrary
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -1500, 0)
    wx = mask(material, lib, world, "r", -1350, 0)
    wy = mask(material, lib, world, "g", -1350, 100)
    origin_x = scalar(material, lib, "OriginX", 0.0, -1350, 200)
    origin_y = scalar(material, lib, "OriginY", 0.0, -1350, 300)
    cell_x = scalar(material, lib, "CellX", 1.0, -1350, 400)
    cell_y = scalar(material, lib, "CellY", 1.0, -1350, 500)
    width = scalar(material, lib, "GridWidth", 1.0, -1350, 600)
    height = scalar(material, lib, "GridHeight", 1.0, -1350, 700)
    col = binary(material, lib, unreal.MaterialExpressionDivide,
                 binary(material, lib, unreal.MaterialExpressionSubtract, wx, origin_x, -1200, 0),
                 cell_x, -1050, 0)
    row = binary(material, lib, unreal.MaterialExpressionDivide,
                 binary(material, lib, unreal.MaterialExpressionSubtract, wy, origin_y, -1200, 150),
                 cell_y, -1050, 150)
    u = binary(material, lib, unreal.MaterialExpressionDivide, col, width, -900, 0)
    v = binary(material, lib, unreal.MaterialExpressionDivide, row, height, -900, 150)
    uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v, -750, 50)
    class_map = texture_parameter(material, lib, "ClassMap", True, -600, 0)
    lib.connect_material_expressions(uv, "", class_map, "UVs")
    code = lib.create_material_expression(material, unreal.MaterialExpressionRound, -300, 0)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, class_map,
               constant(material, lib, 255.0, -600, 250), -450, 0, a_out="R"), "", code, "")
    stencil = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -600, 500)
    stencil.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_CUSTOM_STENCIL)
    stencil_r = mask(material, lib, stencil, "r", -450, 500, source_out="Color")
    terrain = scalar(material, lib, "TerrainStencil", 2.0, -450, 600)
    is_terrain = select_if(material, lib, stencil_r, terrain, 0.0, 1.0, 0.0, -300, 500)
    on_grid = binary(material, lib, unreal.MaterialExpressionMultiply,
                     in_unit_interval(material, lib, u, -600, 800),
                     in_unit_interval(material, lib, v, -600, 1100), -200, 800)
    keep = binary(material, lib, unreal.MaterialExpressionMultiply, is_terrain, on_grid, -100, 600)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, code, keep, 50, 200)
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_LandcoverID")


def create_starfield():
    """W5: M_Starfield -- unlit, additive, two-sided: the direction from the
    sphere's centre in its own frame as (RA / 360, (90 - Dec) / 180) into
    StarMap, times StarIntensity."""
    material = new_material("M_Starfield")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    material.set_editor_property("two_sided", True)
    lib = unreal.MaterialEditingLibrary
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -1400, 0)
    centre = lib.create_material_expression(material, unreal.MaterialExpressionObjectPositionWS,
                                            -1400, 150)
    offset = binary(material, lib, unreal.MaterialExpressionSubtract, world, centre, -1250, 0)
    direction = lib.create_material_expression(material, unreal.MaterialExpressionNormalize, -1100, 0)
    lib.connect_material_expressions(offset, "", direction, "")
    local = lib.create_material_expression(material, unreal.MaterialExpressionTransform, -950, 0)
    local.set_editor_property("transform_source_type",
                              unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
    local.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_LOCAL)
    lib.connect_material_expressions(direction, "", local, "")
    x = mask(material, lib, local, "r", -800, 0)
    y = mask(material, lib, local, "g", -800, 100)
    z = mask(material, lib, local, "b", -800, 200)
    ra = lib.create_material_expression(material, unreal.MaterialExpressionArctangent2, -650, 0)
    lib.connect_material_expressions(y, "", ra, "Y")
    lib.connect_material_expressions(x, "", ra, "X")
    u = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -350, 0)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionDivide, ra,
               constant(material, lib, 6.283185307179586, -650, 100), -500, 0), "", u, "")
    polar = lib.create_material_expression(material, unreal.MaterialExpressionArccosine, -650, 200)
    lib.connect_material_expressions(z, "", polar, "")
    v = binary(material, lib, unreal.MaterialExpressionDivide, polar,
               constant(material, lib, 3.141592653589793, -650, 300), -500, 200)
    uv = binary(material, lib, unreal.MaterialExpressionAppendVector, u, v, -250, 100)
    stars = texture_parameter(material, lib, STARFIELD_MAP_PARAMETER, True, -100, 0)
    lib.connect_material_expressions(uv, "", stars, "UVs")
    intensity = scalar(material, lib, STARFIELD_INTENSITY_PARAMETER, 1.0, -100, 300)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, stars, intensity, 100, 100,
                 a_out="RGB")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_Starfield")


def create_rain_streaks():
    """W5: M_RainStreaks -- post-process after the tonemapper (see
    after_tonemapping), the scene colour raised by STREAK_GAIN where a
    streak lies (see the constants)."""
    if move_after_tonemapping("M_RainStreaks"):
        return
    material = new_material("M_RainStreaks")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", after_tonemapping())
    lib = unreal.MaterialEditingLibrary
    length, direction, density, phase = RAIN_PARAMETERS
    screen = lib.create_material_expression(material, unreal.MaterialExpressionScreenPosition, -1600, 0)
    size = lib.create_material_expression(material, unreal.MaterialExpressionViewSize, -1600, 150)
    pixel = binary(material, lib, unreal.MaterialExpressionMultiply, screen, size, -1450, 0,
                   a_out="ViewportUV")
    fall = vector(material, lib, direction, (0.0, 1.0, 0.0, 0.0), -1600, 300)
    dx = mask(material, lib, fall, "r", -1450, 300)
    dy = mask(material, lib, fall, "g", -1450, 400)
    px = mask(material, lib, pixel, "r", -1300, 0)
    py = mask(material, lib, pixel, "g", -1300, 100)
    along = binary(material, lib, unreal.MaterialExpressionAdd,
                   binary(material, lib, unreal.MaterialExpressionMultiply, px, dx, -1150, 0),
                   binary(material, lib, unreal.MaterialExpressionMultiply, py, dy, -1150, 100),
                   -1000, 0)
    across = binary(material, lib, unreal.MaterialExpressionSubtract,
                    binary(material, lib, unreal.MaterialExpressionMultiply, py, dx, -1150, 250),
                    binary(material, lib, unreal.MaterialExpressionMultiply, px, dy, -1150, 350),
                    -1000, 250)
    spacing = constant(material, lib, STREAK_SPACING_PX, -1000, 400)
    lanes = binary(material, lib, unreal.MaterialExpressionDivide, across, spacing, -850, 250)
    lane = lib.create_material_expression(material, unreal.MaterialExpressionFloor, -700, 250)
    lib.connect_material_expressions(lanes, "", lane, "")
    within = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -700, 350)
    lib.connect_material_expressions(lanes, "", within, "")
    lit_width = select_if(material, lib, within, constant(material, lib, STREAK_WIDTH_FRACTION, -700, 450),
                          0.0, 0.0, 1.0, -550, 350)
    # A per-lane hash: frac(sin(lane) * 43758.5453), twice.
    sine = lib.create_material_expression(material, unreal.MaterialExpressionSine, -550, 250)
    lib.connect_material_expressions(lane, "", sine, "")
    hash_one = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -250, 250)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, sine,
               constant(material, lib, 43758.5453, -550, 150), -400, 250), "", hash_one, "")
    hash_two = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -100, 150)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, hash_one,
               constant(material, lib, 7.13, -250, 150), -175, 150), "", hash_two, "")
    drops = scalar(material, lib, density, 0.0, -400, 500)
    occupancy = lib.create_material_expression(material, unreal.MaterialExpressionSaturate, -250, 500)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionMultiply, drops,
               constant(material, lib, STREAK_CELL_VOLUME_M3, -400, 600), -325, 500), "", occupancy, "")
    occupied = select_if(material, lib, hash_two, occupancy, 0.0, 0.0, 1.0, -50, 400)
    streak = scalar(material, lib, length, 0.0, -1000, 600)
    period = binary(material, lib, unreal.MaterialExpressionMultiply, streak,
                    constant(material, lib, STREAK_PERIOD_FACTOR, -1000, 700), -850, 600)
    seconds = scalar(material, lib, phase, 0.0, -1000, 800)
    travel = binary(material, lib, unreal.MaterialExpressionMultiply, seconds,
                    constant(material, lib, STREAK_SPEED_PX_S, -1000, 900), -850, 800)
    position = binary(material, lib, unreal.MaterialExpressionAdd,
                      binary(material, lib, unreal.MaterialExpressionSubtract, along, travel, -700, 700),
                      binary(material, lib, unreal.MaterialExpressionMultiply, hash_one, period, -700, 800),
                      -550, 700)
    cycle = lib.create_material_expression(material, unreal.MaterialExpressionFrac, -250, 700)
    lib.connect_material_expressions(
        binary(material, lib, unreal.MaterialExpressionDivide, position, period, -400, 700), "", cycle, "")
    on_streak = select_if(material, lib, cycle,
                          constant(material, lib, 1.0 / STREAK_PERIOD_FACTOR, -250, 800),
                          0.0, 0.0, 1.0, -100, 700)
    lit = binary(material, lib, unreal.MaterialExpressionMultiply,
                 binary(material, lib, unreal.MaterialExpressionMultiply, lit_width, occupied, 50, 400),
                 on_streak, 200, 500)
    gain = binary(material, lib, unreal.MaterialExpressionAdd,
                  constant(material, lib, 1.0, 200, 650),
                  binary(material, lib, unreal.MaterialExpressionMultiply, lit,
                         constant(material, lib, STREAK_GAIN, 200, 750), 350, 600), 500, 600)
    scene = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, 350, 0)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    out = binary(material, lib, unreal.MaterialExpressionMultiply, scene, gain, 650, 200, a_out="Color")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_RainStreaks")


def _storm_material(name):
    """A storm-weather material (STORM_MATERIALS), made by its own helper so
    the W5 world list stays exactly the world's; None when it already exists
    at its STORM_GENERATIONS number (an older generation is set aside and
    built again)."""
    if name not in STORM_MATERIALS:
        raise RuntimeError(f"{name} is not one of STORM_MATERIALS")
    full = f"{PATH}/{name}"
    if storm_material_stale(name):
        # Kept ASIDE, not deleted, until finish_storm has saved the new one:
        # a build that raises (a property name the engine refuses) puts it
        # back (restore_storm_materials), so the storm never loses its
        # material to a rebuild. Measured on the owner's machine,
        # 2026-10-09: a delete-then-build left no M_StormCell at all and
        # every storm render was refused.
        aside = f"{PATH}/{name}{STORM_ASIDE_SUFFIX}"
        if unreal.EditorAssetLibrary.does_asset_exist(aside):
            unreal.EditorAssetLibrary.delete_asset(aside)
        if not unreal.EditorAssetLibrary.rename_asset(full, aside):
            raise RuntimeError(f"{full} was built by an older generation of this script "
                               f"(this one is {STORM_GENERATIONS[name]}) and could not be set aside")
        _ASIDE[name] = aside
        print(f"MATERIAL-REBUILT: {full} (built by an older generation of this script; "
              f"this one is {STORM_GENERATIONS[name]}; the old asset is kept at {aside} until "
              f"the new one is saved)")
    return new_material(name)


#: Storm materials set aside for a rebuild, by name -> the aside path.
_ASIDE = {}
STORM_ASIDE_SUFFIX = "_prev"


def restore_storm_materials():
    """A rebuild that raised: the new, unsaved asset (if any) is removed and
    the old one put back at its path. Called by _guard after any creator
    fails; a no-op when nothing is aside."""
    for name, aside in list(_ASIDE.items()):
        full = f"{PATH}/{name}"
        if unreal.EditorAssetLibrary.does_asset_exist(full):
            unreal.EditorAssetLibrary.delete_asset(full)
        if unreal.EditorAssetLibrary.rename_asset(aside, full):
            print(f"MATERIAL-RESTORED: {full} (the old asset put back; the rebuild failed)")
        else:
            print(f"MATERIAL-RESTORE-FAILED: {aside} could not be put back at {full}")
        del _ASIDE[name]


def storm_material_stale(name):
    """True when /Game/FlightSim/<name> exists but was built by an older
    generation of this script (its STORM_GENERATION_TAG metadata is not
    STORM_GENERATIONS[name]): its graph is not the one this script describes."""
    full = f"{PATH}/{name}"
    if not unreal.EditorAssetLibrary.does_asset_exist(full):
        return False
    stamped = unreal.EditorAssetLibrary.get_metadata_tag(
        unreal.EditorAssetLibrary.load_asset(full), STORM_GENERATION_TAG)
    return str(stamped) != STORM_GENERATIONS[name]


def finish_storm(material, name):
    """finish() with the material's STORM_GENERATIONS stamp saved on the
    asset; the old asset set aside for this rebuild (if any) is deleted only now."""
    unreal.EditorAssetLibrary.set_metadata_tag(material, STORM_GENERATION_TAG, STORM_GENERATIONS[name])
    finish(material, name)
    aside = _ASIDE.pop(name, None)
    if aside is not None and unreal.EditorAssetLibrary.does_asset_exist(aside):
        unreal.EditorAssetLibrary.delete_asset(aside)


def storm_scattering(material, lib, x, y):
    """The VolumetricAdvancedMaterialOutput node (STORM_SCATTERING): the
    phase function and the multiple-scattering approximation the cloud is
    lit with, the ground's albedo lighting its bottoms. A property name the
    engine refuses is reported with the node's own list, never skipped: a
    cloud lit by single scattering is the black frame this node is for."""
    node = lib.create_material_expression(
        material, unreal.MaterialExpressionVolumetricAdvancedMaterialOutput, x, y)
    settings = [(STORM_SCATTERING_PROPERTIES[key], value) for key, value in STORM_SCATTERING.items()]
    # The node's own options (per-sample atmospheric light transmittance is
    # the cloud COMPONENT's switch, not the node's: measured on the owner's
    # machine, 2026-10-09, the name was refused and M_StormCell lost).
    settings += [("ground_contribution", True), ("gray_scale_material", False)]
    refused = []
    for prop, value in settings:
        try:
            node.set_editor_property(prop, value)
        except Exception as error:  # the engine's naming decides; reported, not skipped
            refused.append(f"{prop} = {value!r}: {error}")
    if refused:
        raise RuntimeError("VolumetricAdvancedMaterialOutput refused " + "; ".join(refused)
                           + f"\nthe node's editor properties on this engine:\n{type(node).__doc__}")
    return node


def weather_shader(name):
    """A committed Custom node body (WEATHER_SHADER_DIR/<name>.hlsl)."""
    source = _repo_file(f"{WEATHER_SHADER_DIR}/{name}.hlsl")
    if source is None:
        raise RuntimeError(f"{WEATHER_SHADER_DIR}/{name}.hlsl is not in this checkout")
    return source.read_text(encoding="utf-8")


def custom(material, lib, name, output_type, inputs, x, y):
    """A Custom node running WEATHER_SHADER_DIR/<name>.hlsl. ``inputs`` maps
    each shader input name, in order, to (node, output pin)."""
    node = lib.create_material_expression(material, unreal.MaterialExpressionCustom, x, y)
    node.set_editor_property("code", weather_shader(name))
    node.set_editor_property("description", name)
    node.set_editor_property("output_type", output_type)
    pins = []
    for pin in inputs:
        entry = unreal.CustomInput()
        entry.set_editor_property("input_name", pin)
        pins.append(entry)
    node.set_editor_property("inputs", pins)
    for pin, (source, source_out) in inputs.items():
        lib.connect_material_expressions(source, source_out, node, pin)
    return node


def weather_parameter(material, lib, name, x, y, default=0.0):
    """A weather parameter as the shader reads it: a scalar, a float3 vector
    (the parameter's RGB) or a float4 (RGB appended with A,
    WEATHER_FLOAT4_PARAMETERS). Returns (node, output pin)."""
    vectors = {"Shift", "BoxHalf", "WindVel", "CamVel", "GroundShift", "CellCentreCm",
               "EastAxis", "NorthAxis", "FlashRelCm"}
    if name in WEATHER_FLOAT4_PARAMETERS:
        param = vector(material, lib, name, (0.0, 0.0, 0.0, 0.0), x, y)
        node = lib.create_material_expression(material, unreal.MaterialExpressionAppendVector,
                                              x + 200, y)
        lib.connect_material_expressions(param, "", node, "A")
        lib.connect_material_expressions(param, "A", node, "B")
        return node, ""
    if name in vectors:
        return vector(material, lib, name, (0.0, 0.0, 0.0, 0.0), x, y), ""
    return scalar(material, lib, name, default, x, y), ""


def uv_channel(material, lib, index, channel, x, y):
    """One or two channels of a texture coordinate set (the weather meshes
    carry their per-drop data in UV0..UV3)."""
    coords = lib.create_material_expression(material, unreal.MaterialExpressionTextureCoordinate, x, y)
    coords.set_editor_property("coordinate_index", index)
    return mask(material, lib, coords, channel, x + 150, y), ""


def relative_position(material, lib, x, y, exclude_offsets, minus):
    """The world position minus the object's ("object") or the camera's
    ("camera"): small numbers out of large-world ones, before any Custom node."""
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, x, y)
    if exclude_offsets:
        world.set_editor_property("world_position_shader_offset",
                                  unreal.WorldPositionIncludedOffsets.WPT_EXCLUDE_ALL_SHADER_OFFSETS)
    other_kind = (unreal.MaterialExpressionObjectPositionWS if minus == "object"
                  else unreal.MaterialExpressionCameraPositionWS)
    other = lib.create_material_expression(material, other_kind, x, y + 120)
    return binary(material, lib, unreal.MaterialExpressionSubtract, world, other, x + 200, y), ""


#: A drop's albedo as a lit surface: a water drop refracts and reflects
#: nearly all the light that reaches it (Garg & Nayar: its radiance is close
#: to the mean radiance of its surroundings), so it is drawn as a white
#: diffuse surface of this albedo lit by the scene -- the engine's sky
#: light and shadowed sun at the drop are that mean. Stated.
DROP_ALBEDO = 0.9


def drop_lit(material, lib, x, y):
    """A drop's radiance as the engine lights it (Garg & Nayar: the mean of
    its surroundings): the material is a lit translucent surface, base
    colour DROP_ALBEDO x "SkyRadianceScale", lit per vertex from the
    translucency lighting volume (the sky light's ambient, the sun through
    its cloud shadows), plus the lightning flash's "FlashLux" / pi as
    emissive. Measured on the owner's machine (2026-10-09): the unlit
    version, its emissive a sample of the sky light's environment map,
    drew every streak BLACK -- that node reads nothing from a real-time-
    captured sky light -- so the rain darkened the sky instead of catching
    its light."""
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_DEFAULT_LIT)
    lighting = getattr(unreal.TranslucencyLightingMode, "TLM_VOLUMETRIC_PER_VERTEX_NON_DIRECTIONAL",
                       None)
    if lighting is not None:
        material.set_editor_property("translucency_lighting_mode", lighting)
    scale = scalar(material, lib, "SkyRadianceScale", 1.0, x, y + 150)
    base = binary(material, lib, unreal.MaterialExpressionMultiply,
                  constant(material, lib, DROP_ALBEDO, x, y), scale, x + 200, y)
    lib.connect_material_property(base, "", unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(constant(material, lib, 1.0, x, y + 80), "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    flash = scalar(material, lib, "FlashLux", 0.0, x, y + 250)
    glow = binary(material, lib, unreal.MaterialExpressionMultiply, flash,
                  constant(material, lib, 1.0 / 3.14159265, x, y + 350), x + 200, y + 250)
    lib.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)


def _translucent_unlit(material, blend):
    material.set_editor_property("blend_mode", blend)
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("two_sided", True)


def _translucent_lit(material):
    """Translucent, two-sided, lit (drop_lit sets the shading model and the
    lighting mode; the blend here)."""
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    material.set_editor_property("two_sided", True)


def create_rain_drops():
    """M_RainDrops: the rain box's drops as shutter-length streaks
    (rain_drop_offset.hlsl into the world position offset,
    rain_drop_opacity.hlsl into the opacity), lit by the scene (drop_lit)."""
    material = _storm_material("M_RainDrops")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    _translucent_lit(material)
    params = {name: weather_parameter(material, lib, name, -1800, -600 + 110 * i,
                                      default=1.0 if name in ("Weight", "SkyRadianceScale") else 0.0)
              for i, name in enumerate(DROPS_PARAMETERS) if name not in ("SkyRadianceScale",
                                                                             "FlashLux")}
    p0 = relative_position(material, lib, -1800, 900, True, "object")
    offset = custom(material, lib, "rain_drop_offset", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "P0": p0, "Corner": uv_channel(material, lib, 0, "rg", -1800, 1100),
        "Drop": uv_channel(material, lib, 1, "rg", -1800, 1250),
        "Extra": uv_channel(material, lib, 2, "rg", -1800, 1400),
        "Index": uv_channel(material, lib, 3, "r", -1800, 1550),
        "Shift": params["Shift"], "FallTime": params["FallTime"], "BoxHalf": params["BoxHalf"],
        "WindVel": params["WindVel"], "CamVel": params["CamVel"], "Shutter": params["Shutter"],
        "PixelAngle": params["PixelAngle"], "Active": params["Active"]}, -900, 0)
    lib.connect_material_property(offset, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    rel = relative_position(material, lib, -1800, 1700, False, "object")
    opacity = custom(material, lib, "rain_drop_opacity", unreal.CustomMaterialOutputType.CMOT_FLOAT1, {
        "Rel": rel, "Drop": uv_channel(material, lib, 1, "rg", -1500, 1250),
        "Extra": uv_channel(material, lib, 2, "rg", -1500, 1400),
        "Index": uv_channel(material, lib, 3, "r", -1500, 1550),
        "WindVel": params["WindVel"], "CamVel": params["CamVel"], "Shutter": params["Shutter"],
        "PixelAngle": params["PixelAngle"], "Weight": params["Weight"], "Active": params["Active"],
        "BoxHalf": params["BoxHalf"], "GroundRelZ": params["GroundRelZ"]}, -900, 400)
    lib.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
    drop_lit(material, lib, -900, 800)
    finish_storm(material, "M_RainDrops")


def create_rain_splash():
    """M_RainSplash: the splash slots' crowns on the ground under the camera."""
    material = _storm_material("M_RainSplash")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    _translucent_lit(material)
    params = {name: weather_parameter(material, lib, name, -1800, -600 + 110 * i,
                                      default=1.0 if name == "Weight" else 0.0)
              for i, name in enumerate(SPLASH_PARAMETERS) if name not in ("SkyRadianceScale",
                                                                          "FlashLux")}
    p0 = relative_position(material, lib, -1800, 600, True, "object")
    corner = uv_channel(material, lib, 0, "rg", -1800, 800)
    slot = uv_channel(material, lib, 1, "rg", -1800, 950)
    offset = custom(material, lib, "rain_splash_offset", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "P0": p0, "Corner": corner, "SlotUV": slot, "Time": params["Time"],
        "Splash": params["Splash"], "GroundShift": params["GroundShift"],
        "GroundRelZ": params["GroundRelZ"], "DropMm": params["DropMm"],
        "Active": params["Active"]}, -900, 0)
    lib.connect_material_property(offset, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    opacity = custom(material, lib, "rain_splash_opacity", unreal.CustomMaterialOutputType.CMOT_FLOAT1, {
        "Corner": uv_channel(material, lib, 0, "rg", -1500, 800),
        "SlotUV": uv_channel(material, lib, 1, "rg", -1500, 950), "Time": params["Time"],
        "Splash": params["Splash"], "Weight": params["Weight"]}, -900, 400)
    lib.connect_material_property(opacity, "", unreal.MaterialProperty.MP_OPACITY)
    drop_lit(material, lib, -900, 800)
    finish_storm(material, "M_RainSplash")


def create_lightning_channel():
    """M_LightningChannel: the bolt as a camera-facing, pixel-floored line
    source (lightning_offset.hlsl, lightning_emissive.hlsl), additive."""
    material = _storm_material("M_LightningChannel")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    _translucent_unlit(material, unreal.BlendMode.BLEND_ADDITIVE)
    pixel = weather_parameter(material, lib, "PixelAngle", -1800, -300)
    radius = weather_parameter(material, lib, "RadiusCm", -1800, -150, default=5.0)
    power = weather_parameter(material, lib, "Power", -1800, 0)
    normal = lib.create_material_expression(material, unreal.MaterialExpressionVertexNormalWS,
                                            -1800, 200)
    offset = custom(material, lib, "lightning_offset", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "Side": uv_channel(material, lib, 0, "r", -1800, 350), "Dir": (normal, ""),
        "Rel": relative_position(material, lib, -1800, 500, True, "camera"),
        "PixelAngle": pixel, "RadiusCm": radius}, -900, 0)
    lib.connect_material_property(offset, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    depth = lib.create_material_expression(material, unreal.MaterialExpressionPixelDepth, -1800, 800)
    emissive = custom(material, lib, "lightning_emissive", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "Side": uv_channel(material, lib, 0, "r", -1500, 350),
        "Arc": uv_channel(material, lib, 0, "g", -1500, 500),
        "Kind": uv_channel(material, lib, 1, "r", -1500, 650), "Depth": (depth, ""),
        "PixelAngle": pixel, "RadiusCm": radius, "Power": power}, -900, 400)
    lib.connect_material_property(emissive, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish_storm(material, "M_LightningChannel")


def ensure_volumetric_cloud_usage(name):
    """True when /Game/FlightSim/<name> already exists: its graph is kept
    and STORM_USAGE_PROPERTY is set in place when it was not (then
    recompiled and saved), so a machine that built the storm before the
    flag existed does not keep a cloud material with no cloud shaders."""
    full = f"{PATH}/{name}"
    if (not unreal.EditorAssetLibrary.does_asset_exist(full) or rebuild_requested(name)
            or storm_material_stale(name)):
        return False   # absent, a rebuild asked for, or an older generation: built again
    material = unreal.EditorAssetLibrary.load_asset(full)
    if material.get_editor_property(STORM_USAGE_PROPERTY):
        print(f"MATERIAL-EXISTS: {full}")
        return True
    material.set_editor_property(STORM_USAGE_PROPERTY, True)
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-UPDATED: {full} ({STORM_USAGE_PROPERTY} set: the cloud shaders compile)")
    return True


def create_storm_cell():
    """M_StormCell: the volumetric cloud material of a thunderstorm cell
    (Volume domain, additive, flagged for the volumetric cloud -- see
    STORM_USAGE_PROPERTY): albedo "Albedo", extinction storm_cell.hlsl x
    "ExtinctionScale" (1: the shader's 1/m, the engine's unit the first
    Windows measurement), emissive storm_glow.hlsl, lit by STORM_SCATTERING
    (storm_scattering: the phase and the multiple scattering without which
    the base is black)."""
    if ensure_volumetric_cloud_usage("M_StormCell"):
        return
    material = _storm_material("M_StormCell")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_VOLUME)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    material.set_editor_property(STORM_USAGE_PROPERTY, True)
    params = {name: weather_parameter(material, lib, name, -1800, -800 + 110 * i,
                                      default=1.0 if name == "ExtinctionScale" else 0.0)
              for i, name in enumerate(STORM_PARAMETERS)}
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition,
                                           -1800, 800)
    rel = (binary(material, lib, unreal.MaterialExpressionSubtract, world,
                  params["CellCentreCm"][0], -1600, 800), "")
    extinction = custom(material, lib, "storm_cell", unreal.CustomMaterialOutputType.CMOT_FLOAT1, {
        "Rel": rel, "EastAxis": params["EastAxis"], "NorthAxis": params["NorthAxis"],
        "Geo1": params["Geo1"], "Geo2": params["Geo2"], "Sigma": params["Sigma"],
        "Noise": params["Noise"], "Drift": params["Drift"], "Layer": params["Layer"],
        "Time": params["Time"]}, -900, 0)
    scaled = binary(material, lib, unreal.MaterialExpressionMultiply, extinction,
                    params["ExtinctionScale"][0], -600, 0)
    lib.connect_material_property(scaled, "", unreal.MaterialProperty.MP_SUBSURFACE_COLOR)
    albedo = scalar(material, lib, STORM_ALBEDO_PARAMETER, STORM_ALBEDO_DEFAULT, -600, 200)
    lib.connect_material_property(albedo, "", unreal.MaterialProperty.MP_BASE_COLOR)
    glow = custom(material, lib, "storm_glow", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "Rel": rel, "FlashRel": params["FlashRelCm"], "Flash": params["Flash"],
        "Extinction": (extinction, "")}, -600, 400)
    lib.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    storm_scattering(material, lib, -600, 700)
    finish_storm(material, "M_StormCell")


def create_windshield_rain():
    """M_WindshieldRain: drops on the glass (windshield.hlsl), post-process
    after the tonemapper (the M_LensDrops rule: on the final image, so no
    stale border is blurred in) on a cockpit camera's beauty capture only:
    the scene sampled through each drop's refraction offset, lerped in by
    its mask."""
    if not storm_material_stale("M_WindshieldRain") and move_after_tonemapping("M_WindshieldRain"):
        return   # an older generation falls through: _storm_material builds it again
    material = _storm_material("M_WindshieldRain")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", after_tonemapping())
    lib = unreal.MaterialEditingLibrary
    screen = lib.create_material_expression(material, unreal.MaterialExpressionScreenPosition, -1800, 0)
    size = lib.create_material_expression(material, unreal.MaterialExpressionViewSize, -1800, 200)
    aspect = binary(material, lib, unreal.MaterialExpressionDivide,
                    mask(material, lib, size, "r", -1600, 200),
                    mask(material, lib, size, "g", -1600, 300), -1400, 200)
    params = {name: weather_parameter(material, lib, name, -1800, 400 + 110 * i)
              for i, name in enumerate(WINDSHIELD_PARAMETERS)}
    drops = custom(material, lib, "windshield", unreal.CustomMaterialOutputType.CMOT_FLOAT3, {
        "UV": (screen, "ViewportUV"), "Aspect": (aspect, ""), "Time": params["Time"],
        "Glass": params["Glass"], "Seed": params["Seed"]}, -1100, 0)
    shifted = binary(material, lib, unreal.MaterialExpressionAdd,
                     mask(material, lib, screen, "rg", -900, -150, source_out="ViewportUV"),
                     mask(material, lib, drops, "rg", -900, 0), -700, -100)
    behind = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -500, -100)
    behind.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    lib.connect_material_expressions(shifted, "", behind, "UVs")
    scene = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -500, 150)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    # A drop passes ~90 % of the light behind it (two surfaces, stated).
    seen = binary(material, lib, unreal.MaterialExpressionMultiply, behind,
                  constant(material, lib, 0.9, -500, 0), -300, -100, a_out="Color")
    out = lerp(material, lib, scene, seen, mask(material, lib, drops, "b", -500, 300), -100, 0,
               a_out="Color")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish_storm(material, "M_WindshieldRain")


def create_airframe_paint():
    """W5: M_AirframePaint -- a clear-coat paint, lit (Substrate converts
    the clear-coat model to a slab with a coat when r.Substrate is on)."""
    material = new_material("M_AirframePaint")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_CLEAR_COAT)
    lib = unreal.MaterialEditingLibrary
    paint, roughness, metallic, coat, coat_roughness = AIRFRAME_PAINT_PARAMETERS
    colour = vector(material, lib, paint, (0.8, 0.8, 0.8, 1.0), -400, 0)
    lib.connect_material_property(colour, "", unreal.MaterialProperty.MP_BASE_COLOR)
    # The clear-coat inputs: MP_CUSTOM_DATA0/1 on older engines; UE 5.7's
    # Python no longer exposes those names (measured on the owner's
    # machine), so the clear-coat names are tried too. A pin no name
    # reaches keeps its parameter node unconnected and the engine's default
    # coat (said so below), rather than failing the whole material.
    def material_property(*names):
        for candidate in names:
            value = getattr(unreal.MaterialProperty, candidate, None)
            if value is not None:
                return value
        return None

    pins = ((roughness, unreal.MaterialProperty.MP_ROUGHNESS),
            (metallic, unreal.MaterialProperty.MP_METALLIC),
            (coat, material_property("MP_CUSTOM_DATA0", "MP_CLEAR_COAT")),
            (coat_roughness, material_property("MP_CUSTOM_DATA1", "MP_CLEAR_COAT_ROUGHNESS")))
    for index, (name, prop) in enumerate(pins):
        node = scalar(material, lib, name, AIRFRAME_PAINT_DEFAULTS[name], -400, 150 + 100 * index)
        if prop is None:
            print(f"MATERIAL-NOTE: M_AirframePaint {name} has no material pin this engine's "
                  f"Python exposes; left unconnected (the engine's default coat)")
            continue
        lib.connect_material_property(node, "", prop)
    finish(material, "M_AirframePaint")


def create_runway():
    """W5: M_Runway -- the markings raster lerps the surface colour to the
    paint colour, then the wetness coupling."""
    material = new_material("M_Runway")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    markings_name, surface_name, paint_name, _ = RUNWAY_PARAMETERS
    markings = texture_parameter(material, lib, markings_name, True, -700, 0)
    surface = vector(material, lib, surface_name, (0.05, 0.05, 0.05, 1.0), -700, 250)
    paint = vector(material, lib, paint_name, (0.75, 0.75, 0.75, 1.0), -700, 400)
    colour = lib.create_material_expression(material, unreal.MaterialExpressionLinearInterpolate,
                                            -450, 200)
    lib.connect_material_expressions(surface, "", colour, "A")
    lib.connect_material_expressions(paint, "", colour, "B")
    lib.connect_material_expressions(markings, "R", colour, "Alpha")
    add_wetness(material, lib, colour, "", -300)
    finish(material, "M_Runway")


# -- physical sky (-sky=, FLIGHTSIM_SKY=physical; core/sky/plan.py) --------

def _sky_material(name):
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        if rebuild_requested(name) and unreal.EditorAssetLibrary.delete_asset(full):
            print(f"MATERIAL-REBUILT: {full} (deleted on FLIGHTSIM_REBUILD_MATERIALS)")
        else:
            print(f"MATERIAL-EXISTS: {full}")
            return None, full
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material,
                                  unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit(f"could not create material asset {full}")
    return material, full


def _save(material, full):
    unreal.MaterialEditingLibrary.recompile_material(material)
    unreal.EditorAssetLibrary.save_asset(full)
    print(f"MATERIAL-CREATED: {full}")


def create_moon():
    """Physical sky: the moon sphere. LIT, grey, fully rough -- the sun
    light shading it IS the phase, so it must not be unlit. "Albedo" is
    the plan's 0.12 (the moon's mean visual albedo)."""
    material, full = _sky_material("M_Moon")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    albedo = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -400, 0)
    albedo.set_editor_property("parameter_name", "Albedo")
    albedo.set_editor_property("default_value", 0.12)
    lib.connect_material_property(albedo, "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    rough = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -400, 200)
    rough.set_editor_property("r", 1.0)
    lib.connect_material_property(rough, "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    spec = lib.create_material_expression(
        material, unreal.MaterialExpressionConstant, -400, 300)
    spec.set_editor_property("r", 0.0)
    lib.connect_material_property(spec, "",
                                  unreal.MaterialProperty.MP_SPECULAR)
    _save(material, full)


def create_star_emissive():
    """Physical sky: one star disc. UNLIT, OPAQUE: "Color" (max channel 1)
    times "Luminance" (cd/m^2, computed per magnitude bin by
    core/sky/plan.py) into emissive. Opaque so clouds and the
    atmosphere's aerial perspective apply to stars like to any surface."""
    material, full = _sky_material("M_StarEmissive")
    if material is None:
        return
    material.set_editor_property("shading_model",
                                 unreal.MaterialShadingModel.MSM_UNLIT)
    lib = unreal.MaterialEditingLibrary
    colour = lib.create_material_expression(
        material, unreal.MaterialExpressionVectorParameter, -600, 0)
    colour.set_editor_property("parameter_name", "Color")
    colour.set_editor_property("default_value",
                               unreal.LinearColor(1.0, 1.0, 1.0, 1.0))
    lum = lib.create_material_expression(
        material, unreal.MaterialExpressionScalarParameter, -600, 200)
    lum.set_editor_property("parameter_name", "Luminance")
    lum.set_editor_property("default_value", 0.0)
    mul = lib.create_material_expression(
        material, unreal.MaterialExpressionMultiply, -300, 100)
    lib.connect_material_expressions(colour, "", mul, "A")
    lib.connect_material_expressions(lum, "", mul, "B")
    lib.connect_material_property(mul, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    _save(material, full)


def create_terrain_imagery_night():
    """Physical sky: M_TerrainImagery's terrain surface (the same graph,
    terrain_imagery_graph, the same wetness coupling) plus emission.
    "NightLights" is the verified VIIRS drape (core/terrain/nightlights.py)
    on the SAME UV grid as "Imagery"; "NightLuminance" scales it to
    cd/m^2. A separate asset so the plain drape renders carry no
    emissive path."""
    material, full = _sky_material("M_TerrainImageryNight")
    if material is None:
        return
    lib = unreal.MaterialEditingLibrary
    colour, roughness = terrain_imagery_graph(material, lib)
    add_wetness(material, lib, colour, "", 1200, dry_roughness=roughness)
    lights = texture_parameter(material, lib, NIGHT_LIGHTS_PARAMETER, False, 1200, 700)
    scale = scalar(material, lib, NIGHT_LUMINANCE_PARAMETER, 0.0, 1200, 950)
    mul = binary(material, lib, unreal.MaterialExpressionMultiply, lights, scale, 1500, 800,
                 a_out="RGB")
    lib.connect_material_property(mul, "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    _save(material, full)


# One material that fails (an engine API rename, measured on 5.7) must not
# stop the ones after it: every creator runs, each failure is printed with
# its traceback, and the script exits non-zero at the end if any failed.
# -- the weather look (FlightSimVisualScene.cpp ApplyWeatherLook) -------------
#
# The materials the card's weather_look block draws with (core/scene/
# weather_look.py). All procedural, so a machine without any download
# renders every one; a ground surface whose Poly Haven textures were
# fetched (scripts/fetch_ground_textures.py -> data/textures/polyhaven/
# <surface>/{diffuse,normal,rough}.jpg) samples them instead of its
# procedural pattern. Written without an engine (no build on the authoring
# machine): the node names are this file's own idioms, the looks are not
# measured against a photograph, and the first Windows run is their check.
#
# * M_Ground_<Surface> -- the flat scene's ground per surface word, world-
#   aligned (the 100 km engine plane's own UVs would stretch one tile over
#   the whole scene), a large-scale tint noise against tiling seen from the
#   air, and the wet-ground coupling (WET_GROUND_PARAMETER; puddles in the
#   low noise and ripples on them). The ocean is procedural water: two
#   travelling waves' analytic normal, low roughness, no texture.
# * M_LensDrops -- post-process on the beauty capture: rain on the lens,
#   cells of the screen holding a drop that refracts the scene through
#   itself; DropAmount 0 is the scene unchanged.
# * M_RainShaft -- translucent, unlit, two-sided: the grey curtain under a
#   storm cell, streaked and faded at its top and at the ground.
# * M_Lightning -- unlit additive: the bolt, black (invisible) at
#   FlashIntensity 0.
# * M_IceOverlay -- translucent overlay (UMeshComponent::SetOverlayMaterial)
#   on the airframe: frost on the forward-facing surfaces, IceAmount 0..1.
# * M_RainDrop -- the 3-D rain (FlightSimRainParticles.cpp): lit translucent
#   water on the instanced drop cylinders, its opacity DropOpacity x the
#   instance's custom float 0 (the share of the drawn width the drop
#   covers), so a sub-pixel drop adds only its own light.

WET_GROUND_PARAMETER = "Wetness"
GROUND_TILE_M = 12.0
GROUND_MACRO_M = 900.0
#: surface -> (material, dry colour A, dry colour B, roughness, metres of the
#: procedural pattern). The palettes are stated choices, not measurements.
GROUND_SURFACES = {
    "desert": ("M_Ground_Desert", (0.62, 0.48, 0.31), (0.78, 0.64, 0.44), 0.85, 60.0),
    "forest": ("M_Ground_Forest", (0.05, 0.11, 0.04), (0.11, 0.19, 0.07), 0.9, 25.0),
    "grassland": ("M_Ground_Grassland", (0.20, 0.30, 0.09), (0.36, 0.40, 0.14), 0.9, 40.0),
    "snow": ("M_Ground_Snow", (0.80, 0.84, 0.90), (0.93, 0.95, 0.98), 0.6, 80.0),
    "bare": ("M_Ground_Bare", (0.30, 0.27, 0.23), (0.47, 0.43, 0.37), 0.92, 30.0),
    "city": ("M_Ground_City", (0.24, 0.24, 0.25), (0.42, 0.41, 0.39), 0.8, 90.0),
    "ocean": ("M_Ground_Ocean", (0.01, 0.06, 0.10), (0.02, 0.12, 0.17), 0.04, 0.0),
}
#: The ocean's two travelling waves: (direction x, direction y, wavelength m,
#: amplitude m, speed m/s). Deep-water speed sqrt(g L / 2 pi) for each.
OCEAN_WAVES = ((1.0, 0.3, 40.0, 0.35, 7.9), (-0.4, 1.0, 13.0, 0.12, 4.5))
WEATHER_PARAMETERS = {"drops": "DropAmount", "shaft": "ShaftOpacity",
                      "flash": "FlashIntensity", "ice": "IceAmount"}
#: M_RainDrop's parameters, by the names FlightSimRainParticles.cpp sets.
RAIN_DROP_PARAMETERS = ("DropOpacity",)
#: The drop's water: a pale grey-blue base, nearly mirror-smooth (stated).
RAIN_DROP_COLOUR = (0.62, 0.66, 0.70)
RAIN_DROP_ROUGHNESS = 0.08


def _weather_material(name):
    """/Game/FlightSim/<name> once; None when it already exists (the world
    list stays exactly the world's, like the sky's helper)."""
    full = f"{PATH}/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        if rebuild_requested(name) and unreal.EditorAssetLibrary.delete_asset(full):
            print(f"MATERIAL-REBUILT: {full} (deleted on FLIGHTSIM_REBUILD_MATERIALS)")
        else:
            print(f"MATERIAL-EXISTS: {full}")
            return None
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    material = tools.create_asset(name, PATH, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise SystemExit(f"could not create material asset {full}")
    return material


def _world_xy_metres(material, lib, metres, x, y):
    """The absolute world position's xy in units of `metres` (cm / 100 / m)."""
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, x, y)
    xy = mask(material, lib, world, "rg", x + 150, y)
    return binary(material, lib, unreal.MaterialExpressionDivide, xy,
                  constant(material, lib, metres * 100.0, x + 150, y + 80), x + 300, y)


def _noise(material, lib, feature_m, x, y, levels=4):
    """A 0..1 noise over world position with features of about `feature_m`."""
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, x, y)
    node = lib.create_material_expression(material, unreal.MaterialExpressionNoise, x + 150, y)
    node.set_editor_property("scale", 1.0 / (feature_m * 100.0))
    node.set_editor_property("levels", levels)
    node.set_editor_property("output_min", 0.0)
    node.set_editor_property("output_max", 1.0)
    lib.connect_material_expressions(world, "", node, "Position")
    return node


def _wave_normal(material, lib, waves, x, y):
    """The tangent-space normal of a sum of travelling sine waves h = sum A
    sin(k (d . p) - w t): n = normalize(-dh/dx, -dh/dy, 1), dh/dx = sum A k
    d_x cos(...). Positions in metres, time from the Time node."""
    time = lib.create_material_expression(material, unreal.MaterialExpressionTime, x, y + 400)
    slope_x = None
    slope_y = None
    for index, (dx, dy, wavelength, amplitude, speed) in enumerate(waves):
        norm = math.hypot(dx, dy)
        dx, dy = dx / norm, dy / norm
        row = y + index * 200
        p = _world_xy_metres(material, lib, 1.0, x, row)
        along = lib.create_material_expression(material, unreal.MaterialExpressionDotProduct,
                                               x + 450, row)
        lib.connect_material_expressions(p, "", along, "A")
        direction = lib.create_material_expression(material, unreal.MaterialExpressionConstant2Vector,
                                                   x + 300, row + 100)
        direction.set_editor_property("r", dx)
        direction.set_editor_property("g", dy)
        lib.connect_material_expressions(direction, "", along, "B")
        travelled = binary(material, lib, unreal.MaterialExpressionSubtract, along,
                           binary(material, lib, unreal.MaterialExpressionMultiply, time,
                                  constant(material, lib, speed, x + 450, row + 150), x + 600, row + 100),
                           x + 750, row)
        cosine = lib.create_material_expression(material, unreal.MaterialExpressionCosine, x + 900, row)
        cosine.set_editor_property("period", wavelength)
        lib.connect_material_expressions(travelled, "", cosine, "")
        k = 2.0 * math.pi / wavelength
        sx = binary(material, lib, unreal.MaterialExpressionMultiply, cosine,
                    constant(material, lib, -amplitude * k * dx, x + 900, row + 100), x + 1050, row)
        sy = binary(material, lib, unreal.MaterialExpressionMultiply, cosine,
                    constant(material, lib, -amplitude * k * dy, x + 900, row + 150), x + 1050, row + 80)
        slope_x = sx if slope_x is None else binary(material, lib, unreal.MaterialExpressionAdd,
                                                    slope_x, sx, x + 1200, row)
        slope_y = sy if slope_y is None else binary(material, lib, unreal.MaterialExpressionAdd,
                                                    slope_y, sy, x + 1200, row + 80)
    xy = binary(material, lib, unreal.MaterialExpressionAppendVector, slope_x, slope_y, x + 1350, y)
    xyz = binary(material, lib, unreal.MaterialExpressionAppendVector, xy,
                 constant(material, lib, 1.0, x + 1350, y + 100), x + 1500, y)
    return unary(material, lib, unreal.MaterialExpressionNormalize, xyz, x + 1650, y)


def _ground_textures(surface):
    """The fetched Poly Haven maps for a surface, imported once as
    T_Ground_<Surface>_{D,N,R}; None when the checkout has none."""
    files = {}
    for key, file in (("D", "diffuse.jpg"), ("N", "normal.jpg"), ("R", "rough.jpg")):
        path = _repo_file(f"data/textures/polyhaven/{surface}/{file}")
        if path is None:
            return None
        files[key] = path
    name = f"T_Ground_{surface.capitalize()}"
    return {"D": import_texture(files["D"], f"{name}_D", True, False, False),
            "N": import_texture(files["N"], f"{name}_N", False, True, False),
            "R": import_texture(files["R"], f"{name}_R", False, False, False)}


def _sample(material, lib, texture, uv, sampler, x, y):
    node = lib.create_material_expression(material, unreal.MaterialExpressionTextureSample, x, y)
    node.set_editor_property("texture", texture)
    node.set_editor_property("sampler_type", sampler)
    lib.connect_material_expressions(uv, "", node, "UVs")
    return node


def add_wet_ground(material, lib, colour, roughness, normal, x, colour_out="", rough_out="",
                   normal_out=""):
    """The wet ground: WET_GROUND_PARAMETER (0 dry) darkens the colour by up
    to 35 %, lerps roughness to 0.25, and opens puddles where a 30 m noise
    falls below the wetness -- mirror-smooth (0.03), darker, their normal
    flat and rippled by small fast waves (the drops landing). Wires base
    colour, roughness and normal."""
    wet = scalar(material, lib, WET_GROUND_PARAMETER, 0.0, x, 600)
    darken = unary(material, lib, unreal.MaterialExpressionOneMinus,
                   binary(material, lib, unreal.MaterialExpressionMultiply, wet,
                          constant(material, lib, 0.35, x, 700), x + 150, 650), x + 300, 650)
    wet_colour = binary(material, lib, unreal.MaterialExpressionMultiply, colour, darken,
                        x + 450, 0, a_out=colour_out)
    wet_rough = lerp(material, lib, roughness, constant(material, lib, 0.25, x, 800), wet,
                     x + 450, 200, a_out=rough_out)
    low = _noise(material, lib, 30.0, x - 300, 900, levels=3)
    # puddle = saturate((wetness - noise) * 6): none dry, the low ground first.
    puddle = unary(material, lib, unreal.MaterialExpressionSaturate,
                   binary(material, lib, unreal.MaterialExpressionMultiply,
                          binary(material, lib, unreal.MaterialExpressionSubtract,
                                 binary(material, lib, unreal.MaterialExpressionMultiply, wet,
                                        constant(material, lib, 0.75, x, 1000), x + 150, 950),
                                 low, x + 300, 950),
                          constant(material, lib, 6.0, x + 300, 1050), x + 450, 950), x + 600, 950)
    colour_out_node = lerp(material, lib, wet_colour,
                           binary(material, lib, unreal.MaterialExpressionMultiply, wet_colour,
                                  constant(material, lib, 0.55, x + 450, 100), x + 600, 50),
                           puddle, x + 750, 0)
    rough_out_node = lerp(material, lib, wet_rough, constant(material, lib, 0.03, x + 600, 250),
                          puddle, x + 750, 200)
    ripples = _wave_normal(material, lib, ((1.0, 0.0, 0.35, 0.004, 0.6),
                                           (0.0, 1.0, 0.23, 0.003, 0.5)), x - 1800, 1300)
    normal_node = lerp(material, lib, normal, ripples, puddle, x + 750, 400, a_out=normal_out)
    lib.connect_material_property(colour_out_node, "", unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(rough_out_node, "", unreal.MaterialProperty.MP_ROUGHNESS)
    lib.connect_material_property(normal_node, "", unreal.MaterialProperty.MP_NORMAL)


def create_ground(surface, material):
    """One flat-scene ground (GROUND_SURFACES[surface]); material is None
    when the asset already exists."""
    if material is None:
        return
    name, colour_a, colour_b, roughness, pattern_m = GROUND_SURFACES[surface]
    lib = unreal.MaterialEditingLibrary
    macro = _noise(material, lib, GROUND_MACRO_M, -2400, -400, levels=3)
    tint = lerp(material, lib, constant(material, lib, 0.8, -2100, -300),
                constant(material, lib, 1.15, -2100, -250), macro, -1950, -350)
    if surface == "ocean":
        water = lerp(material, lib, constant3(material, lib, colour_a, -1800, 0),
                     constant3(material, lib, colour_b, -1800, 80), macro, -1650, 0)
        normal = _wave_normal(material, lib, OCEAN_WAVES, -3600, 400)
        material.set_editor_property("two_sided", False)
        lib.connect_material_property(constant(material, lib, 0.5, -1300, 300), "",
                                      unreal.MaterialProperty.MP_SPECULAR)
        add_wet_ground(material, lib, water, constant(material, lib, roughness, -1300, 200),
                       normal, -1100)
        finish(material, name)
        return
    textures = _ground_textures(surface)
    if textures is not None:
        uv = _world_xy_metres(material, lib, GROUND_TILE_M, -2400, 0)
        base = _sample(material, lib, textures["D"], uv,
                       unreal.MaterialSamplerType.SAMPLERTYPE_COLOR, -2000, 0)
        nrm = _sample(material, lib, textures["N"], uv,
                      unreal.MaterialSamplerType.SAMPLERTYPE_NORMAL, -2000, 300)
        rough = _sample(material, lib, textures["R"], uv,
                        unreal.MaterialSamplerType.SAMPLERTYPE_LINEAR_COLOR, -2000, 600)
        colour = binary(material, lib, unreal.MaterialExpressionMultiply, base, tint, -1700, 0,
                        a_out="RGB")
        rough_r = mask(material, lib, rough, "r", -1700, 600, source_out="RGB")
        add_wet_ground(material, lib, colour, rough_r, nrm, -1300, normal_out="RGB")
        print(f"MATERIAL-NOTE: {name} samples the fetched Poly Haven textures (CC0)")
    else:
        detail = _noise(material, lib, pattern_m, -2400, 0, levels=5)
        colour = lerp(material, lib, constant3(material, lib, colour_a, -2000, 0),
                      constant3(material, lib, colour_b, -2000, 80), detail, -1850, 0)
        if surface == "city":
            # Street grid every 120 m: a darker band where frac(p) < 0.12 on x or y.
            grid = _world_xy_metres(material, lib, 120.0, -2400, 300)
            cell = unary(material, lib, unreal.MaterialExpressionFrac, grid, -2000, 300)
            street_x = select_if(material, lib, mask(material, lib, cell, "r", -1900, 300),
                                 constant(material, lib, 0.12, -1900, 380), 0.0, 0.0, 1.0, -1750, 300)
            street_y = select_if(material, lib, mask(material, lib, cell, "g", -1900, 450),
                                 constant(material, lib, 0.12, -1900, 530), 0.0, 0.0, 1.0, -1750, 450)
            street = unary(material, lib, unreal.MaterialExpressionSaturate,
                           binary(material, lib, unreal.MaterialExpressionAdd, street_x, street_y,
                                  -1600, 350), -1450, 350)
            colour = lerp(material, lib, colour, constant3(material, lib, (0.08, 0.08, 0.09),
                                                           -1600, 450), street, -1300, 100)
        colour = binary(material, lib, unreal.MaterialExpressionMultiply, colour, tint, -1150, 0)
        flat = constant3(material, lib, (0.0, 0.0, 1.0), -1300, 500)
        add_wet_ground(material, lib, colour, constant(material, lib, roughness, -1300, 200),
                       flat, -1000)
    finish(material, name)


def create_ground_surfaces():
    """The seven flat-scene grounds, one asset per surface word."""
    create_ground("desert", _weather_material("M_Ground_Desert"))
    create_ground("forest", _weather_material("M_Ground_Forest"))
    create_ground("grassland", _weather_material("M_Ground_Grassland"))
    create_ground("snow", _weather_material("M_Ground_Snow"))
    create_ground("bare", _weather_material("M_Ground_Bare"))
    create_ground("city", _weather_material("M_Ground_City"))
    create_ground("ocean", _weather_material("M_Ground_Ocean"))


def create_lens_drops():
    """M_LensDrops: post-process (after the tonemapper: after_tonemapping). The
    screen is cut into cells of 1/18 of its height; a cell holds a drop
    when its hash is below DropAmount * 0.45, and inside the drop's disc
    the scene is sampled mirrored about the drop's centre (a lens of
    water inverts what is behind it), darkened 15 % at the rim."""
    if move_after_tonemapping("M_LensDrops"):
        return
    material = _weather_material("M_LensDrops")
    if material is None:
        return
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_POST_PROCESS)
    material.set_editor_property("blendable_location", after_tonemapping())
    lib = unreal.MaterialEditingLibrary
    amount = scalar(material, lib, WEATHER_PARAMETERS["drops"], 0.0, -1600, 600)
    screen = lib.create_material_expression(material, unreal.MaterialExpressionScreenPosition, -1600, 0)
    uv = mask(material, lib, screen, "rg", -1450, 0, source_out="ViewportUV")
    cells = binary(material, lib, unreal.MaterialExpressionMultiply, uv,
                   constant(material, lib, 18.0, -1450, 100), -1300, 0)
    cell = unary(material, lib, unreal.MaterialExpressionFloor, cells, -1150, 0)
    within = unary(material, lib, unreal.MaterialExpressionFrac, cells, -1150, 100)
    # hash = frac(sin(dot(cell, (12.9898, 78.233))) * 43758.5453)
    seed = lib.create_material_expression(material, unreal.MaterialExpressionConstant2Vector, -1150, 200)
    seed.set_editor_property("r", 12.9898)
    seed.set_editor_property("g", 78.233)
    dot = binary(material, lib, unreal.MaterialExpressionDotProduct, cell, seed, -1000, 150)
    sine = unary(material, lib, unreal.MaterialExpressionSine, dot, -850, 150)
    hashed = unary(material, lib, unreal.MaterialExpressionFrac,
                   binary(material, lib, unreal.MaterialExpressionMultiply, sine,
                          constant(material, lib, 43758.5453, -850, 250), -700, 150), -550, 150)
    present = select_if(material, lib, hashed,
                        binary(material, lib, unreal.MaterialExpressionMultiply, amount,
                               constant(material, lib, 0.45, -850, 650), -700, 600),
                        0.0, 0.0, 1.0, -400, 300)
    centred = binary(material, lib, unreal.MaterialExpressionSubtract, within,
                     constant(material, lib, 0.5, -1000, 350), -850, 350)
    radius = lib.create_material_expression(material, unreal.MaterialExpressionLength, -700, 350)
    lib.connect_material_expressions(centred, "", radius, "")
    size = binary(material, lib, unreal.MaterialExpressionAdd,
                  constant(material, lib, 0.18, -700, 450),
                  binary(material, lib, unreal.MaterialExpressionMultiply, hashed,
                         constant(material, lib, 0.5, -700, 500), -550, 450), -400, 450)
    inside = select_if(material, lib, radius, size, 0.0, 0.0, 1.0, -250, 400)
    drop = binary(material, lib, unreal.MaterialExpressionMultiply, inside, present, -100, 350)
    # The mirrored sample: uv - 2 (within - 0.5) / 18 * 0.6.
    mirror = binary(material, lib, unreal.MaterialExpressionSubtract, uv,
                    binary(material, lib, unreal.MaterialExpressionMultiply, centred,
                           constant(material, lib, 2.0 * 0.6 / 18.0, -850, 450), -700, 500),
                    -550, 550)
    scene = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -400, -200)
    scene.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    seen = lib.create_material_expression(material, unreal.MaterialExpressionSceneTexture, -400, 700)
    seen.set_editor_property("scene_texture_id", unreal.SceneTextureId.PPI_POST_PROCESS_INPUT0)
    lib.connect_material_expressions(mirror, "", seen, "UVs")
    rim = unary(material, lib, unreal.MaterialExpressionOneMinus,
                binary(material, lib, unreal.MaterialExpressionMultiply,
                       binary(material, lib, unreal.MaterialExpressionDivide, radius, size, -250, 600),
                       constant(material, lib, 0.15, -250, 700), -100, 650), 50, 650)
    refracted = binary(material, lib, unreal.MaterialExpressionMultiply, seen, rim, 200, 650,
                       a_out="Color")
    out = lerp(material, lib, scene, refracted, drop, 400, 200, a_out="Color")
    lib.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_LensDrops")


def create_rain_shaft():
    """M_RainShaft: translucent unlit two-sided grey; opacity =
    ShaftOpacity x vertical streaks (a noise stretched 40:1 in height) x
    the mesh's V (1 at the cloud base, 0 at the ground: UV0.y) faded,
    softened where it meets the ground (DepthFade)."""
    material = _weather_material("M_RainShaft")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    material.set_editor_property("two_sided", True)
    lib = unreal.MaterialEditingLibrary
    opacity = scalar(material, lib, WEATHER_PARAMETERS["shaft"], 0.0, -1200, 300)
    world = lib.create_material_expression(material, unreal.MaterialExpressionWorldPosition, -1500, 0)
    stretch = lib.create_material_expression(material, unreal.MaterialExpressionConstant3Vector, -1500, 100)
    stretch.set_editor_property("constant", unreal.LinearColor(1.0, 1.0, 0.025, 1.0))
    streaked = binary(material, lib, unreal.MaterialExpressionMultiply, world, stretch, -1350, 0)
    streaks = lib.create_material_expression(material, unreal.MaterialExpressionNoise, -1200, 0)
    streaks.set_editor_property("scale", 1.0 / 800.0)
    streaks.set_editor_property("levels", 3)
    streaks.set_editor_property("output_min", 0.35)
    streaks.set_editor_property("output_max", 1.0)
    lib.connect_material_expressions(streaked, "", streaks, "Position")
    uv = lib.create_material_expression(material, unreal.MaterialExpressionTextureCoordinate, -1200, 200)
    height = mask(material, lib, uv, "g", -1050, 200)
    alpha = binary(material, lib, unreal.MaterialExpressionMultiply,
                   binary(material, lib, unreal.MaterialExpressionMultiply, opacity, streaks, -900, 100),
                   height, -750, 150)
    fade = lib.create_material_expression(material, unreal.MaterialExpressionDepthFade, -550, 150)
    fade.set_editor_property("fade_distance_default", 20000.0)
    lib.connect_material_expressions(alpha, "", fade, "Opacity")
    lib.connect_material_property(constant3(material, lib, (0.30, 0.33, 0.37), -550, 0), "",
                                  unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    lib.connect_material_property(fade, "", unreal.MaterialProperty.MP_OPACITY)
    finish(material, "M_RainShaft")


def create_lightning():
    """M_Lightning: unlit additive two-sided, emissive (0.75, 0.8, 1.0) x
    FlashIntensity x 60; black, so invisible, at 0."""
    material = _weather_material("M_Lightning")
    if material is None:
        return
    material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    material.set_editor_property("two_sided", True)
    lib = unreal.MaterialEditingLibrary
    flash = scalar(material, lib, WEATHER_PARAMETERS["flash"], 0.0, -600, 200)
    glow = binary(material, lib, unreal.MaterialExpressionMultiply,
                  constant3(material, lib, (0.75, 0.8, 1.0), -600, 0),
                  binary(material, lib, unreal.MaterialExpressionMultiply, flash,
                         constant(material, lib, 60.0, -600, 300), -450, 250), -300, 100)
    lib.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    finish(material, "M_Lightning")


def create_rain_drop():
    """M_RainDrop: translucent, lit per pixel (the sun's glint and the
    sky's fill reach each drop), used with instanced static meshes;
    base colour RAIN_DROP_COLOUR, roughness RAIN_DROP_ROUGHNESS, opacity =
    DropOpacity x PerInstanceCustomData[0] (1 where a mesh carries none)."""
    material = _weather_material("M_RainDrop")
    if material is None:
        return
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    lighting = getattr(unreal.TranslucencyLightingMode, "TLM_SURFACE_PER_PIXEL_LIGHTING", None)
    if lighting is not None:
        material.set_editor_property("translucency_lighting_mode", lighting)
    material.set_editor_property("used_with_instanced_static_meshes", True)
    lib = unreal.MaterialEditingLibrary
    lib.connect_material_property(constant3(material, lib, RAIN_DROP_COLOUR, -600, 0), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(constant(material, lib, RAIN_DROP_ROUGHNESS, -600, 150), "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    opacity = scalar(material, lib, RAIN_DROP_PARAMETERS[0], 0.55, -900, 300)
    coverage = lib.create_material_expression(
        material, unreal.MaterialExpressionPerInstanceCustomData, -900, 450)
    coverage.set_editor_property("data_index", 0)
    try:
        coverage.set_editor_property("const_default_value", 1.0)
    except Exception:   # an engine without the property: every drop sets the float anyway
        print("M_RainDrop: PerInstanceCustomData has no const_default_value; left at its default")
    lib.connect_material_property(
        binary(material, lib, unreal.MaterialExpressionMultiply, opacity, coverage, -600, 350),
        "", unreal.MaterialProperty.MP_OPACITY)
    finish(material, "M_RainDrop")


def create_ice_overlay():
    """M_IceOverlay: translucent, lit, rough-ish blue-white frost; opacity =
    IceAmount x (0.25 + 0.75 x the forward-facing share of the surface: the
    vertex normal in the airframe's own frame, x forward, saturated) x a
    4 cm frost noise. Drawn as each airframe part's overlay material."""
    material = _weather_material("M_IceOverlay")
    if material is None:
        return
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    lib = unreal.MaterialEditingLibrary
    ice = scalar(material, lib, WEATHER_PARAMETERS["ice"], 0.0, -1200, 400)
    normal = lib.create_material_expression(material, unreal.MaterialExpressionVertexNormalWS, -1500, 0)
    local = lib.create_material_expression(material, unreal.MaterialExpressionTransform, -1350, 0)
    local.set_editor_property("transform_source_type",
                              unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD)
    local.set_editor_property("transform_type", unreal.MaterialVectorCoordTransform.TRANSFORM_LOCAL)
    lib.connect_material_expressions(normal, "", local, "")
    forward = unary(material, lib, unreal.MaterialExpressionSaturate,
                    mask(material, lib, local, "r", -1200, 0), -1050, 0)
    facing = binary(material, lib, unreal.MaterialExpressionAdd,
                    constant(material, lib, 0.25, -1050, 100),
                    binary(material, lib, unreal.MaterialExpressionMultiply, forward,
                           constant(material, lib, 0.75, -1050, 150), -900, 50), -750, 50)
    frost = _noise(material, lib, 0.04, -1350, 200, levels=4)
    alpha = binary(material, lib, unreal.MaterialExpressionMultiply,
                   binary(material, lib, unreal.MaterialExpressionMultiply, ice, facing, -600, 200),
                   frost, -450, 200)
    lib.connect_material_property(constant3(material, lib, (0.82, 0.9, 0.97), -450, 0), "",
                                  unreal.MaterialProperty.MP_BASE_COLOR)
    lib.connect_material_property(constant(material, lib, 0.35, -450, 100), "",
                                  unreal.MaterialProperty.MP_ROUGHNESS)
    lib.connect_material_property(alpha, "", unreal.MaterialProperty.MP_OPACITY)
    finish(material, "M_IceOverlay")


_FAILED = []


def _guard(creator):
    def run():
        try:
            creator()
        except Exception:   # reported below, never swallowed
            import traceback
            traceback.print_exc()
            print(f"MATERIAL-FAILED: {creator.__name__}")
            _FAILED.append(creator.__name__)
            restore_storm_materials()   # a storm rebuild that failed: the old asset back
    return run


import inspect  # noqa: E402

# Only the top-level creators (no parameters); helpers such as
# create_pass_material(name, ...) are called by them and stay unwrapped.
for _name in [n for n in list(globals()) if n.startswith("create_")
              and callable(globals()[n])
              and not inspect.signature(globals()[n]).parameters]:
    globals()[_name] = _guard(globals()[_name])


create_vertex_colour()
create_terrain_imagery()
create_vertex_colour_unlit()
create_custom_stencil_id()
create_world_normal_pass()
create_velocity_pass()
create_base_colour_pass()
create_world_normal_fallback()
create_velocity_check()
create_grey_card()
create_landscape()
create_landcover_id()
create_starfield()
create_rain_streaks()
create_airframe_paint()
create_runway()
create_moon()
create_star_emissive()
create_terrain_imagery_night()
create_ground_surfaces()
create_lens_drops()
create_rain_shaft()
create_lightning()
create_ice_overlay()
create_rain_drop()
create_rain_drops()
create_rain_splash()
create_lightning_channel()
create_storm_cell()
create_windshield_rain()
if _FAILED:
    raise SystemExit(f"materials not created: {', '.join(_FAILED)}")
