"""Canopy reflection, tiers 0-1 of swarm lane aircraft_exterior.glass.coastal
(beauty only, OFF unless -canopy-reflect=on).

The lane (swarm/lanes/aircraft_exterior/glass/coastal: bake_glass.py,
PROVENANCE.json, INTEGRATION.md) bakes a Fresnel LUT and a sky/sea lat-long
strip. This module turns its two OPAQUE tiers into two masters beside the
opaque glass master, never instead of it:

* M_AircraftGlassReflect     tier 0: M_AircraftGlass's graph exactly (wet
  layer and canopy scratches included) plus Emissive = the strip x the slab
  reflectance x GlassEnvGain x GlassEnvTint. Two taps (LUT, 64x32 strip).
* M_AircraftGlassReflectFine tier 1: tier 0 plus a tiled micro-scratch
  normal that leans the lookup (not the material's Normal) and a film mask
  that adds roughness; 128x64 strip. Four taps.

Tiers 2-3 (Thin Translucent with SSR) are NOT built: translucency and SSR are
the risky passes on the render laptop's Intel iGPU (D3D11 SM5, device hangs).

What the host does (FlightSimAircraftFX.cpp ApplyMaterials):

* -canopy-reflect absent or off: nothing. M_AircraftGlass and its MI_<slot>
  draw as before, byte for byte; this master is not even loaded.
* -canopy-reflect=on: a glass slot that draws its OPAQUE look instance (a
  -labels render, which every web-app render is, or a slot without
  MI_<slot>_thin) draws a MID of the tier's master with the instance's
  overrides copied. A slot on MI_<slot>_thin keeps it (round 46's C172
  canopy), and the -labels rule that keeps the opaque instance is unchanged:
  both masters are opaque Default Lit and write depth, and the reflection is
  Emissive only, which no label pass reads (the ID / depth / stencil passes
  replace the tonemapper from scene textures; SCS_Normal and SCS_BaseColor
  read the GBuffer, whose normal and base colour this graph never changes).
* GlassEnvGain is the master's 0 until the host sets it from the scene's
  sun each step (:func:`canopy_reflect_gain`); an interior camera (cockpit,
  shoulder) sets 0: the inside of a pane mirrors the cabin, not the sky.
* GlassEnvTint follows the scene's horizon colour when the render carries
  -xplane-horizon= (the look's own X-Plane horizon, :func:`horizon_tint`);
  otherwise the strip's baked hue stands, recorded as such.

Stdlib only: this module is imported by scripts/aircraft_look.py, which also
runs inside UnrealEditor's Python. The builders (only they touch ``unreal``)
take ``lib`` = scripts/ue_aircraft_master_materials.py, as
scripts/aircraft_wet_layer.py does. UNCOMPILED and UNRENDERED when written:
no engine runs on the authoring machine.
"""

import json
import math
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANE = "aircraft_exterior.glass.coastal"
LANE_DIR = os.path.join(REPO, "swarm", "lanes", "aircraft_exterior", "glass", "coastal")
LANE_OUT = os.path.join(LANE_DIR, "out")
BAKE_JSON = os.path.join(LANE_OUT, "glass_coastal.json")
PROVENANCE_JSON = os.path.join(LANE_DIR, "PROVENANCE.json")

#: The host's switches (FFlightSimAircraftFXOptions::ParseParams). The first
#: is one of scripts/aircraft_look.py FX_SWITCHES (on/off, default OFF, off
#: under -aircraft-look=off); the tier word is 0 or 1, anything else refused
#: by name (aircraft_look.switch).
SWITCH_KEY = "canopy-reflect="
SWITCH_DEFAULT = False
TIER_KEY = "canopy-reflect-tier="
TIERS = (0, 1)
DEFAULT_TIER = 0

#: The masters, by tier (built under aircraft_look.MASTER_ROOT).
MASTERS = {0: "M_AircraftGlassReflect", 1: "M_AircraftGlassReflectFine"}
#: The opaque glass master whose slots may take a reflect master.
OPAQUE_GLASS_MASTER = "M_AircraftGlass"
#: Textures import under MASTER_ROOT/<this>.
TEXTURE_FOLDER = "Glass"

#: Texture parameter -> the lane file each tier samples (glass_coastal.json tiers).
TIER_TEXTURES = {
    0: {"GlassFresnelLUT": "T_GlassFresnel_LUT", "GlassEnv": "T_GlassEnv_64"},
    1: {"GlassFresnelLUT": "T_GlassFresnel_LUT", "GlassEnv": "T_GlassEnv_128",
        "GlassMicroN": "T_GlassMicro_N_256", "GlassFilmM": "T_GlassFilm_M_256"},
}
#: How each lane file imports: (sRGB, compression, mips, address U, address V,
#: the sampler a parameter on it needs). The micro normal imports as linear
#: data (uncompressed, decoded xy = 2 c - 1 in glass_reflect_uv.hlsl), not
#: TC_Normalmap as the lane suggested: it only leans a lookup vector, and the
#: Normal sampler's derived z would be one more thing nobody has compiled.
#: The LUT and the strip take no mips (the strip's atan2 seam would pick the
#: smallest mip along one column otherwise).
TEXTURE_IMPORT = {
    "T_GlassFresnel_LUT": (False, "TC_VECTOR_DISPLACEMENTMAP", False, "TA_CLAMP", "TA_CLAMP",
                           "SAMPLERTYPE_LINEAR_COLOR"),
    "T_GlassEnv_": (True, "TC_EDITOR_ICON", False, "TA_WRAP", "TA_CLAMP", "SAMPLERTYPE_COLOR"),
    "T_GlassMicro_N_": (False, "TC_VECTOR_DISPLACEMENTMAP", True, "TA_WRAP", "TA_WRAP",
                        "SAMPLERTYPE_LINEAR_COLOR"),
    "T_GlassFilm_M_": (False, "TC_MASKS", True, "TA_WRAP", "TA_WRAP", "SAMPLERTYPE_MASKS"),
}


def texture_import(name):
    """TEXTURE_IMPORT's row for one lane file name (prefix match)."""
    for prefix, row in TEXTURE_IMPORT.items():
        if name == prefix or (prefix.endswith("_") and name.startswith(prefix)):
            return row
    raise KeyError(f"{name} is not a canopy-reflect texture")


#: The shader bodies (assets/shaders/aircraft/<name>.hlsl) and their inputs,
#: merged into aircraft_look.SHADER_INPUTS.
GLASS_REFLECT_SHADER_INPUTS = {
    "glass_reflect_uv": ("NormalWS", "CameraVec", "SunDir", "MicroN", "MicroStrength",
                         "AxisX", "AxisY", "AxisZ"),
    "glass_reflect": ("Lut", "Env", "EnvScale", "Gain", "Tint"),
    "glass_micro_uv": ("LocalPos", "NormalWS", "AxisX", "AxisY", "AxisZ", "TileCm"),
}

#: Parameter names the host sets on the reflect MIDs.
GAIN_PARAMETER = "GlassEnvGain"
TINT_PARAMETER = "GlassEnvTint"
SUN_PARAMETER = "GlassSunAzimuthDir"


def load_bake(path=BAKE_JSON):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


_BAKE = load_bake()
_SHARED = _BAKE["shared_params"]
#: linear radiance = decoded strip x this (bake_glass.py SHARED env_encode_scale)
ENV_ENCODE_SCALE = float(_SHARED["env_encode_scale"])
#: The strip's anti-sun horizon colour (linear) and its luminance (Rec. 709).
STRIP_HORIZON_LINEAR = tuple(float(c) for c in _SHARED["haze_horizon_linear_rgb"])


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


STRIP_HORIZON_LUMINANCE = luminance(STRIP_HORIZON_LINEAR)

#: Master scalar / vector defaults. GlassEnvGain 0 is the lane's own default:
#: the master adds nothing until the host sets a gain (only under the switch).
MASTER_SCALARS = {
    GAIN_PARAMETER: 0.0,
    "GlassEnvEncodeScale": ENV_ENCODE_SCALE,
    # tier 1 only
    "GlassMicroTileCm": float(_BAKE["glass"]["micro_tile_m"]) * 100.0,
    "GlassMicroStrength": float(_BAKE["glass"]["micro_normal_strength"]["1"]),
    "GlassFilmRoughnessAdd": float(_BAKE["glass"]["roughness_add_max"]),
}
TIER0_SCALARS = (GAIN_PARAMETER, "GlassEnvEncodeScale")
MASTER_VECTORS = {TINT_PARAMETER: (1.0, 1.0, 1.0, 1.0), SUN_PARAMETER: (1.0, 0.0, 0.0, 0.0)}

# -- the gain the host sets (twin of FFlightSimAircraftFX::CanopyReflectGain) ---
#: The sky's horizon luminance as a share of a white Lambertian surface under
#: the sun (E / pi). A clear sky's horizon is about 0.2 of it; 0.10 is half
#: that, CONSERVATIVE on purpose: the opaque master's specular lobe already
#: mirrors the sky light, and the strip adds to it (INTEGRATION.md's double
#: count). UNCALIBRATED: the A/B round on the laptop sets it.
SKY_HORIZON_SHARE = 0.10
#: The reflection fades out as the sun sets (smoothstep over these degrees of
#: sun elevation): the strip is a daytime sky.
NIGHT_FADE_DEG = (-2.0, 8.0)
#: Overcast dims it: x (1 - this x cover), the largest cloud layer cover (1
#: under an X-Plane "ocast" condition): a deck's sky is dim and has no glow.
OVERCAST_DIM = 0.75
#: The tint follows the scene's horizon hue within these bounds per channel.
TINT_BOUNDS = (0.25, 4.0)
#: Camera presets that look out through the pane from inside (the
#: commandlet's storm-glass rule: "cockpit" under consume-poses, the legacy
#: "shoulder"): GlassEnvGain 0.
INTERIOR_PRESETS = ("cockpit", "shoulder")


def _smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def canopy_reflect_gain(sun_intensity, sun_elevation_deg, cover=0.0, interior=False):
    """GlassEnvGain: scene luminance per unit of strip radiance, so that the
    strip's anti-sun horizon (STRIP_HORIZON_LUMINANCE) lands at
    SKY_HORIZON_SHARE x sun_intensity / pi, faded at night and under cloud.
    ``sun_intensity`` is the sun light's Intensity as the scene set it (lux
    on the physical sky; the unitless legacy sun scales the same way, since
    that scene's exposure is set for it)."""
    if interior:
        return 0.0
    day = _smoothstep(NIGHT_FADE_DEG[0], NIGHT_FADE_DEG[1], float(sun_elevation_deg))
    sky = 1.0 - OVERCAST_DIM * min(max(float(cover), 0.0), 1.0)
    horizon_nits = SKY_HORIZON_SHARE * max(float(sun_intensity), 0.0) / math.pi * day * sky
    return horizon_nits / STRIP_HORIZON_LUMINANCE


def _srgb8_to_linear(c):
    c = float(c) / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def parse_srgb8(word):
    """``R:G:B`` (0..255 each, webapp.runs.xplane_lighting_flags) -> tuple, or None."""
    match = re.fullmatch(r"\s*(\d{1,3}):(\d{1,3}):(\d{1,3})\s*", word or "")
    if match is None:
        return None
    values = tuple(int(v) for v in match.groups())
    return values if all(v <= 255 for v in values) else None


def horizon_tint(srgb8):
    """(tint, source): the scene's horizon hue over the strip's own, each at
    unit luminance (the gain sets the level, the tint only the hue), clamped
    to TINT_BOUNDS. None or a black horizon: white (the baked hue)."""
    if srgb8 is None:
        return (1.0, 1.0, 1.0), "baked (no -xplane-horizon on this render)"
    lin = tuple(_srgb8_to_linear(c) for c in srgb8)
    lum = luminance(lin)
    if not lum > 1.0e-4:
        return (1.0, 1.0, 1.0), "baked (the -xplane-horizon colour is black)"
    tint = tuple(min(max((c / lum) / (s / STRIP_HORIZON_LUMINANCE), TINT_BOUNDS[0]), TINT_BOUNDS[1])
                 for c, s in zip(lin, STRIP_HORIZON_LINEAR))
    return tint, "-xplane-horizon (the look's X-Plane horizon colour, hue only)"


def parse_canopy_reflect(params):
    """Twin of the host: (on, tier). ``on`` is aircraft_look.parse_fx_switches'
    canopy-reflect; the tier word must be 0 or 1 (LookError
    "aircraft_look.switch: ..." otherwise, refused even with the switch off,
    as the host does)."""
    import aircraft_look as look
    on = look.parse_fx_switches(params)[SWITCH_KEY[:-1]]
    match = re.search(re.escape(TIER_KEY) + r'"?([^\s"]*)', params)
    tier = DEFAULT_TIER
    if match is not None:
        word = match.group(1)
        if word not in tuple(str(t) for t in TIERS):
            raise look.LookError(f"aircraft_look.switch: -{TIER_KEY}{word} is not 0 or 1 "
                                 f"(tiers 2-3 are translucent and not built)")
        tier = int(word)
    return on, tier


# -- numpy-free twins of the shader bodies (tests/test_canopy_reflect.py) -----

def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    length = math.sqrt(_dot(a, a))
    return tuple(x / length for x in a)


def _dominant_plane(normal, axes):
    """(t, b) axes of the plane the shader projects on: the local axis the
    normal leans on most is dropped (x -> yz, y -> xz, else xy)."""
    ax, ay, az = (_norm(a) for a in axes)
    ln = [abs(_dot(normal, a)) for a in (ax, ay, az)]
    if ln[0] >= ln[1] and ln[0] >= ln[2]:
        return ay, az, (1, 2)
    if ln[1] >= ln[2]:
        return ax, az, (0, 2)
    return ax, ay, (0, 1)


def reflect_uv(normal, camera_vec, sun_dir, micro=(0.5, 0.5, 1.0), strength=0.0,
               axes=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
    """Twin of glass_reflect_uv.hlsl: (lut_u, lut_v, env_u, env_v)."""
    n = _norm(normal)
    t, b, _ = _dominant_plane(n, axes)
    m = (micro[0] * 2.0 - 1.0, micro[1] * 2.0 - 1.0)
    s = min(max(strength, 0.0), 1.0)
    n = _norm(tuple(n[i] + s * (m[0] * t[i] + m[1] * b[i]) for i in range(3)))
    v = _norm(camera_vec)
    ndv = min(max(_dot(n, v), 0.0), 1.0)
    r = tuple(-v[i] + 2.0 * _dot(v, n) * n[i] for i in range(3))   # reflect(-v, n)
    sl = math.hypot(sun_dir[0], sun_dir[1])
    sd = (sun_dir[0] / sl, sun_dir[1] / sl) if sl > 1.0e-4 else (1.0, 0.0)
    azim = math.atan2(r[0] * sd[1] - r[1] * sd[0], r[0] * sd[0] + r[1] * sd[1])
    env_v = 0.5 - math.asin(min(max(r[2], -1.0), 1.0)) / math.pi
    lo, hi = 0.0078125, 0.9921875
    return (min(max(ndv, lo), hi), 0.5, azim / (2.0 * math.pi) + 0.5, min(max(env_v, lo), hi))


def micro_uv(local_pos_cm, normal, tile_cm,
             axes=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
    """Twin of glass_micro_uv.hlsl."""
    _, _, (i, j) = _dominant_plane(_norm(normal), axes)
    scale = max(float(tile_cm), 1.0)
    return local_pos_cm[i] / scale, local_pos_cm[j] / scale


def reflect_emissive(lut_rgb, env_rgb, env_scale, gain, tint=(1.0, 1.0, 1.0)):
    """Twin of glass_reflect.hlsl."""
    rs = lut_rgb[0] * lut_rgb[0]
    return tuple(max(e * env_scale * rs * max(gain, 0.0) * max(t, 0.0), 0.0) for e, t in zip(env_rgb, tint))


# -- the master-graph builders (only these touch unreal) ----------------------

def texture_path(master_root, name):
    return f"{master_root}/{TEXTURE_FOLDER}/{name}"


def import_textures(lib, tier):
    """Import the tier's lane PNGs under MASTER_ROOT/Glass (replacing what is
    there: the lane's PROVENANCE.json sha256 is the version); returns
    {texture parameter: (texture, sampler type name)}."""
    unreal = lib._u()
    root = f"{lib.look.MASTER_ROOT}/{TEXTURE_FOLDER}"
    out = {}
    for parameter, name in TIER_TEXTURES[tier].items():
        source = os.path.join(LANE_OUT, f"{name}.png")
        if not os.path.isfile(source):
            raise RuntimeError(f"canopy reflect: {source} is missing (run {LANE_DIR}/bake_glass.py bake)")
        srgb, compression, mips, address_u, address_v, sampler = texture_import(name)
        full = f"{root}/{name}"
        # Imported afresh on every build (a few KB each): a re-bake lands.
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", source)
        task.set_editor_property("destination_path", root)
        task.set_editor_property("destination_name", name)
        task.set_editor_property("automated", True)
        task.set_editor_property("replace_existing", True)
        task.set_editor_property("save", False)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        texture = unreal.load_asset(full)
        if texture is None:
            raise RuntimeError(f"canopy reflect: {source} did not import as {full}")
        texture.set_editor_property("srgb", bool(srgb))
        texture.set_editor_property("compression_settings",
                                    lib._enum(unreal.TextureCompressionSettings, compression))
        if not mips:
            texture.set_editor_property("mip_gen_settings",
                                        lib._enum(unreal.TextureMipGenSettings, "TMGS_NO_MIPMAPS"))
        texture.set_editor_property("address_x", lib._enum(unreal.TextureAddress, address_u))
        texture.set_editor_property("address_y", lib._enum(unreal.TextureAddress, address_v))
        unreal.EditorAssetLibrary.save_asset(full)
        out[parameter] = (texture, sampler)
    return out


def _texture_parameter(material, lib, name, texture, sampler, coords, x, y):
    """A TextureSampleParameter2D whose default is the imported texture (a
    texture parameter compiles only with a default of its sampler's class)."""
    unreal = lib._u()
    node = lib._node(material, unreal.MaterialExpressionTextureSampleParameter2D, x, y)
    node.set_editor_property("parameter_name", name)
    node.set_editor_property("sampler_type", lib._enum(unreal.MaterialSamplerType, sampler))
    node.set_editor_property("texture", texture)
    lib._link(coords, "", node, ("Coordinates", "UVs"))
    return node


#: Every attribute the glass master's last graft (add_canopy_scratch) wires;
#: the reflection's Make takes each straight from Break, Roughness and
#: EmissiveColor excepted.
PASS_THROUGH = ("BaseColor", "Metallic", "Specular", "Normal", "Tangent", "Anisotropy", "AmbientOcclusion")


def add_reflection(material, lib, tier, wet_layer):
    """Graft the reflection onto a built opaque glass graph (after
    add_canopy_scratch, before _finish): Break -> (+ Emissive, tier 1: +
    Roughness) -> Make. ``wet_layer`` is scripts/aircraft_wet_layer.py (its
    _graft / _commit / _pin)."""
    if tier not in TIERS:
        raise ValueError(f"canopy reflect tier {tier!r} is not one of {TIERS}")
    unreal = lib._u()
    x, y = 3400, 1600
    textures = import_textures(lib, tier)
    brk, make = wet_layer._graft(material, lib, x, y)
    s = {name: lib._scalar(material, name, MASTER_SCALARS[name], x, y + 300 + 100 * i)
         for i, name in enumerate(TIER0_SCALARS if tier == 0 else MASTER_SCALARS)}
    tint = lib._mask(material, lib._vector(material, TINT_PARAMETER, MASTER_VECTORS[TINT_PARAMETER],
                                           x - 200, y + 900), "rgb", x, y + 900)
    sun = lib._mask(material, lib._vector(material, SUN_PARAMETER, MASTER_VECTORS[SUN_PARAMETER],
                                          x - 200, y + 1000), "rgb", x, y + 1000)
    normal = lib._node(material, unreal.MaterialExpressionVertexNormalWS, x, y - 300)
    camera = lib._node(material, unreal.MaterialExpressionCameraVectorWS, x, y - 200)
    axes = {name: lib._local_axis(material, name[-1].lower(), x + 200, y - 700 + 100 * i)
            for i, name in enumerate(("AxisX", "AxisY", "AxisZ"))}
    if tier == 0:
        micro, micro_out = lib._const3(material, (0.5, 0.5, 1.0), x, y - 100), ""
        strength = lib._const(material, 0.0, x, y)
        roughness, roughness_out = brk, "Roughness"
    else:
        local = lib._node(material, unreal.MaterialExpressionLocalPosition, x, y - 400)
        uv_micro = lib._custom(material, "glass_micro_uv", "CMOT_FLOAT2", {
            "LocalPos": (local, ""), "NormalWS": (normal, ""),
            "AxisX": (axes["AxisX"], ""), "AxisY": (axes["AxisY"], ""), "AxisZ": (axes["AxisZ"], ""),
            "TileCm": (s["GlassMicroTileCm"], "")}, x + 450, y - 500)
        tex, sampler = textures["GlassMicroN"]
        micro, micro_out = _texture_parameter(material, lib, "GlassMicroN", tex, sampler, uv_micro,
                                              x + 700, y - 500), ""
        tex, sampler = textures["GlassFilmM"]
        film = _texture_parameter(material, lib, "GlassFilmM", tex, sampler, uv_micro, x + 700, y - 300)
        strength = s["GlassMicroStrength"]
        roughness = lib._saturate(material, lib._add(material, brk, lib._mul(
            material, film, s["GlassFilmRoughnessAdd"], x + 950, y - 300, a_out="R"),
            x + 1050, y - 250, a_out="Roughness"), x + 1150, y - 250)
        roughness_out = ""
    uv = lib._custom(material, "glass_reflect_uv", "CMOT_FLOAT4", {
        "NormalWS": (normal, ""), "CameraVec": (camera, ""), "SunDir": (sun, ""),
        "MicroN": (micro, micro_out), "MicroStrength": (strength, ""),
        "AxisX": (axes["AxisX"], ""), "AxisY": (axes["AxisY"], ""), "AxisZ": (axes["AxisZ"], "")},
        x + 1000, y)
    tex, sampler = textures["GlassFresnelLUT"]
    lut = _texture_parameter(material, lib, "GlassFresnelLUT", tex, sampler,
                             lib._mask(material, uv, "rg", x + 1200, y - 100), x + 1350, y - 100)
    tex, sampler = textures["GlassEnv"]
    env = _texture_parameter(material, lib, "GlassEnv", tex, sampler,
                             lib._mask(material, uv, "ba", x + 1200, y + 100), x + 1350, y + 100)
    reflection = lib._custom(material, "glass_reflect", "CMOT_FLOAT3", {
        "Lut": (lut, ""), "Env": (env, ""), "EnvScale": (s["GlassEnvEncodeScale"], ""),
        "Gain": (s[GAIN_PARAMETER], ""), "Tint": (tint, "")}, x + 1600, y)
    emissive = lib._add(material, brk, reflection, x + 1800, y - 100, a_out="EmissiveColor")
    for name in PASS_THROUGH:
        lib._link(brk, name, make, wet_layer._pin(name))
    lib._link(roughness, roughness_out, make, "Roughness")
    lib._link(emissive, "", make, wet_layer._pin("EmissiveColor"))
    wet_layer._commit(lib, material, make)
    return reflection
