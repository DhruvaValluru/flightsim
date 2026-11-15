"""The airframe's sky reflection (item "aircraft", 2026-11-14): the paint and
bare-metal masters mirror the baked sky/sea strip. BEAUTY ONLY, Emissive only.

Cause (read in code, no frame rendered on this machine): in chase views
(#06, #09, #13, #15) the airframe reads as flat grey plastic because nothing
in the scene gives a glossy or wet panel a MIRROR image of its surroundings.
On the render laptop (Intel iGPU, D3D11 SM5) there is no Lumen and no
hardware ray tracing; FlightSimBeautyLook.cpp's ``ssr`` effect is off on the
constrained GPU (ReflectionMethod None, ScreenSpaceReflectionIntensity 0);
and no file of the bridge spawns a reflection capture. What remains is the
sky light's one low-resolution cubemap through the engine's specular IBL,
whose lower hemisphere is black: a 4 % dielectric (paint F0 0.04) under it
shows no sky, and a wet panel (the wet layer takes roughness to 0.08 and the
coat to 1) has nothing to reflect, so the rain sheen never appears. The
canopy lane met the same wall and answered it with a baked strip on Emissive
(scripts/aircraft_glass_reflect.py); this module does the same for the
paint, physically shaped:

* Emissive += Fresnel(N.V) x L_strip(reflect(V, N)) x Gain x Tint x Amount
  (paint_env_reflect.hlsl). F0 is UE's own: lerp(0.08 x Specular, BaseColor,
  Metallic), so paint mirrors at 0.04, a worn edge and the bare-metal master
  at the measured metal's F0, each with the grazing term capped by
  (1 - roughness). The clear coat is a second n 1.5 layer on top (its own
  mirror by CoatAmount; the base sees 1 - coat Fresnel). Each layer's mirror
  fades as (1 - roughness / 0.5)^2: a matte PLAAF grey (coat 0, roughness
  0.5) adds NOTHING dry, a gloss airliner (coat 1 at 0.08) mirrors the sky,
  and under rain the wet layer's coat 1 / WetCoatRoughness 0.03 make the same
  matte panel mirror it: the sheen follows the weather with no new switch.
* The lookup normal is leaned by the wet layer's rivulet bulge
  (aircraft_wet.hlsl's WetLean additional output, object frame) x StreakLean,
  so a streak mirrors a different patch of sky than the paint around it (a
  thin bright or dark line). The material's Normal output is untouched.
* Gain is the canopy's rule (aircraft_glass_reflect.canopy_reflect_gain:
  0.10 x sun Intensity / pi, faded out below 8 deg of sun, dimmed by cloud
  cover), set per step by the host on the paint / bare-metal MIDs under
  ``-paint-reflect=on`` (the default; ``off`` is the A/B: gain stays the
  master's 0 and the master adds exactly nothing). Exposure: the gain is in
  scene nits per unit of strip radiance, proportional to the sun, so the
  mirrored sky sits in the same exposure as the sunlit paint beside it.

Labels match pixels: the graft is Emissive only. Every class master stays
OPAQUE with no World Position Offset; BaseColor, Metallic, Specular,
Roughness, Normal, AO and the coat pass straight through (PASS_THROUGH), so
the ID / depth / stencil passes and the SCS_Normal / SCS_BaseColor passes see
the same surface with the switch on or off. A measure render builds no look.

Textures: the canopy lane's own T_GlassEnv_64 (64x32 lat-long strip,
swarm/lanes/aircraft_exterior/glass/coastal, sha256 in its PROVENANCE.json),
imported under MASTER_ROOT/Glass by aircraft_glass_reflect.import_textures.
No new asset.

Stdlib only (imported by scripts/aircraft_look.py, which also runs inside
UnrealEditor's Python). Every number here is UNCALIBRATED: no frame has been
rendered (probe: #06 SFO rain chase, #09 / #13 / #15 chase at shot c range,
with -paint-reflect=off beside it). UNCOMPILED when written.
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import aircraft_glass_reflect as _glass  # noqa: E402
import aircraft_scene_sky as _scene  # noqa: E402  (generation 14: the scene's sky and ground)

UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"

#: The host's switch (FFlightSimAircraftFXOptions::ParseParams; one of
#: aircraft_look.FX_SWITCHES): on by default, -paint-reflect=off is the A/B.
SWITCH_KEY = "paint-reflect="
SWITCH_DEFAULT = True

#: The classes whose master takes the graft (the coat exists on the first only).
CLASSES = ("paint", "bare_metal")
COATED_CLASSES = ("paint",)

#: Parameter names the host sets on the paint / bare-metal MIDs.
GAIN_PARAMETER = "PaintEnvGain"
TINT_PARAMETER = "PaintEnvTint"
SUN_PARAMETER = "PaintSunAzimuthDir"
#: Generation 14: the scene-sky parameters' prefix (aircraft_scene_sky.parameters).
SCENE_PREFIX = "Paint"
#: The strip texture parameter (the canopy lane's tier-0 strip).
ENV_TEXTURE_PARAMETER = "PaintEnv"
ENV_TEXTURE_NAME = _glass.TIER_TEXTURES[0]["GlassEnv"]

#: The look constants of this module (the look manifest's ``paint_reflect``
#: group, each UNCALIBRATED). Amount: the class's share of the mirror, the
#: double-count hedge against the engine's own specular IBL (the canopy lane's
#: INTEGRATION.md): bare metal already mirrors the sky light at F0 0.92, so it
#: takes half. StreakLean: how far a rivulet's flank leans the lookup normal.
DEFAULTS = {
    "AmountPaint": 1.0,
    "AmountBareMetal": 0.5,
    "StreakLean": 0.6,
}
#: Literals inside paint_env_reflect.hlsl (pinned to the text by test).
HLSL_ROUGH_CUTOFF = 0.5
HLSL_COAT_F0 = 0.04

#: The master scalars the graft adds, with the DEFAULTS key (or value) each
#: defaults to; {cls} is the class suffix. PaintEnvGain 0 is the point: the
#: master adds nothing until the host sets a gain.
MASTER_SCALARS = {
    GAIN_PARAMETER: 0.0,
    "PaintEnvEncodeScale": _glass.ENV_ENCODE_SCALE,
    "PaintEnvAmount": "Amount{cls}",
    "PaintStreakLean": "StreakLean",
}
MASTER_VECTORS = {TINT_PARAMETER: (1.0, 1.0, 1.0, 1.0), SUN_PARAMETER: (1.0, 0.0, 0.0, 0.0)}
CLASS_KEYS = {"paint": "Paint", "bare_metal": "BareMetal"}

#: The Custom-node bodies (assets/shaders/aircraft/<name>.hlsl) and their
#: inputs, in order; merged into aircraft_look.SHADER_INPUTS.
PAINT_REFLECT_SHADER_INPUTS = {
    "paint_env_uv": ("NormalWS", "CameraVec", "SunDir", "Lean", "LeanStrength",
                     "AxisX", "AxisY", "AxisZ"),
    "paint_env_reflect": ("Env", "EnvScale", "Gain", "Tint", "Scene", "NdotV", "F0", "Roughness",
                          "CoatAmount", "CoatRoughness", "Amount"),
}

#: Every attribute the paint / bare-metal master's last graft (the wet layer)
#: wires, taken straight from Break: the reflection changes Emissive only.
PASS_THROUGH = ("BaseColor", "Metallic", "Specular", "Roughness", "Normal", "AmbientOcclusion")
COAT_PASS_THROUGH = ("ClearCoat", "ClearCoatRoughness")


def class_default(template, cls):
    """MASTER_SCALARS default for one class: a DEFAULTS key template or a number."""
    if cls not in CLASS_KEYS:
        raise ValueError(f"slot class {cls!r} is not one of {tuple(CLASS_KEYS)}")
    if isinstance(template, str):
        return float(DEFAULTS[template.format(cls=CLASS_KEYS[cls])])
    return float(template)


def constants_group(probe="the #06 SFO rain chase and the #09 / #13 / #15 chase views at shot c "
                          "range, each beside -paint-reflect=off"):
    """The look manifest's ``paint_reflect`` constants group."""
    return {key: {"value": float(value), "calibration": UNCALIBRATED, "probe": probe}
            for key, value in DEFAULTS.items()}


def parse_paint_reflect(params):
    """Twin of the host's switch: True unless -paint-reflect=off (or -aircraft-look=off)."""
    import aircraft_look as look
    return look.parse_fx_switches(params)[SWITCH_KEY[:-1]]


# -- numpy-free twins of the shader bodies (tests/test_paint_reflect.py) ------

def _norm(a):
    length = math.sqrt(sum(x * x for x in a))
    return tuple(x / length for x in a)


def env_uv(normal, camera_vec, sun_dir, lean=(0.0, 0.0, 0.0), strength=0.0,
           axes=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))):
    """Twin of paint_env_uv.hlsl: (ndv, 0, env_u, env_v)."""
    ax, ay, az = (_norm(a) for a in axes)
    n = _norm(normal)
    s = min(max(strength, 0.0), 1.0)
    lean_ws = tuple(lean[0] * ax[i] + lean[1] * ay[i] + lean[2] * az[i] for i in range(3))
    n = _norm(tuple(n[i] + s * lean_ws[i] for i in range(3)))
    v = _norm(camera_vec)
    vn = sum(v[i] * n[i] for i in range(3))
    ndv = min(max(vn, 0.0), 1.0)
    r = tuple(-v[i] + 2.0 * vn * n[i] for i in range(3))
    sl = math.hypot(sun_dir[0], sun_dir[1])
    sd = (sun_dir[0] / sl, sun_dir[1] / sl) if sl > 1.0e-4 else (1.0, 0.0)
    azim = math.atan2(r[0] * sd[1] - r[1] * sd[0], r[0] * sd[0] + r[1] * sd[1])
    env_v = 0.5 - math.asin(min(max(r[2], -1.0), 1.0)) / math.pi
    lo, hi = 0.0078125, 0.9921875
    return (ndv, 0.0, azim / (2.0 * math.pi) + 0.5, min(max(env_v, lo), hi))


def gloss(roughness, cutoff=HLSL_ROUGH_CUTOFF):
    """(1 - roughness / cutoff)^2, 0 at the cutoff and above."""
    g = min(max(1.0 - min(max(roughness, 0.0), 1.0) / cutoff, 0.0), 1.0)
    return g * g


def schlick(f0, ndv, roughness):
    """Schlick's Fresnel about f0 with the grazing term capped by 1 - roughness."""
    fw = (1.0 - min(max(ndv, 0.0), 1.0)) ** 5
    return f0 + (max(1.0 - roughness, f0) - f0) * fw


def mirror(ndv, f0, roughness, coat=0.0, coat_roughness=1.0):
    """The scalar mirror share of paint_env_reflect.hlsl for one F0 channel."""
    rough = min(max(roughness, 0.0), 1.0)
    f_base = schlick(min(max(f0, 0.0), 1.0), ndv, rough)
    g_base = gloss(rough)
    c = min(max(coat, 0.0), 1.0)
    cr = min(max(coat_roughness, 0.0), 1.0)
    f_coat = schlick(HLSL_COAT_F0, ndv, cr)
    g_coat = gloss(cr)
    return min(max(c * f_coat * g_coat + (1.0 - c * f_coat) * f_base * g_base, 0.0), 1.0)


def reflect_emissive(env_rgb, env_scale, gain, tint, ndv, f0_rgb, roughness,
                     coat=0.0, coat_roughness=1.0, amount=1.0, scene=(0.0, 0.0, 0.0, 0.0)):
    """Twin of paint_env_reflect.hlsl (``scene``: scene_sky_env's float4;
    the default a = 0 is generation 13's strip)."""
    a = min(max(amount, 0.0), 1.0)
    strip = [max(e * env_scale, 0.0) * max(gain, 0.0) * max(t, 0.0) for e, t in zip(env_rgb, tint)]
    envs = _scene.mix(strip, (max(scene[0], 0.0), max(scene[1], 0.0), max(scene[2], 0.0), scene[3]))
    return tuple(env * mirror(ndv, f0, roughness, coat, coat_roughness) * a
                 for env, f0 in zip(envs, f0_rgb))


def ue_f0(base_rgb, specular, metallic):
    """UE's F0: lerp(0.08 x Specular, BaseColor, Metallic), per channel."""
    m = min(max(metallic, 0.0), 1.0)
    return tuple(0.08 * specular + (c - 0.08 * specular) * m for c in base_rgb)


def rivulet_lean(across, width):
    """Twin of aircraft_wet.hlsl's per-line lean: clamp(a / w, -1, 1) x
    profile x 2, where profile = saturate(1 - |a| / w); 0 on the crest and off
    the line, largest at mid-flank."""
    w = max(width, 1.0e-6)
    profile = min(max(1.0 - abs(across) / w, 0.0), 1.0)
    return min(max(across / w, -1.0), 1.0) * profile * 2.0


# -- the master-graph builder (only this touches unreal) ----------------------

def _env_texture(lib):
    """The canopy lane's tier-0 strip: loaded if a build already imported it
    under MASTER_ROOT/Glass, else imported by the lane's own importer (the
    glass reflect masters, built later, re-import it in place: same object)."""
    unreal = lib._u()
    sampler = _glass.texture_import(ENV_TEXTURE_NAME)[-1]
    texture = unreal.load_asset(_glass.texture_path(lib.look.MASTER_ROOT, ENV_TEXTURE_NAME))
    if texture is None:
        texture = _glass.import_textures(lib, 0)["GlassEnv"][0]
    return texture, sampler


def add_reflection(material, lib, slot_class, wet_layer, wet_node):
    """Graft the sky reflection onto a built paint / bare-metal master, after
    the wet layer (``wet_node`` is add_wet_layer's Custom node: its WetLean
    output leans the lookup) and before _finish: Break -> (+ Emissive) ->
    Make. Everything else passes straight through."""
    if slot_class not in CLASSES:
        raise ValueError(f"paint reflect: class {slot_class!r} is not one of {CLASSES}")
    unreal = lib._u()
    x, y = 3400, 1600
    texture, sampler = _env_texture(lib)
    brk, make = wet_layer._graft(material, lib, x, y)
    s = {name: lib._scalar(material, name, class_default(default, slot_class), x, y + 300 + 100 * i)
         for i, (name, default) in enumerate(MASTER_SCALARS.items())}
    tint = lib._mask(material, lib._vector(material, TINT_PARAMETER, MASTER_VECTORS[TINT_PARAMETER],
                                           x - 200, y + 900), "rgb", x, y + 900)
    sun = lib._mask(material, lib._vector(material, SUN_PARAMETER, MASTER_VECTORS[SUN_PARAMETER],
                                          x - 200, y + 1000), "rgb", x, y + 1000)
    normal = lib._node(material, unreal.MaterialExpressionVertexNormalWS, x, y - 300)
    camera = lib._node(material, unreal.MaterialExpressionCameraVectorWS, x, y - 200)
    axes = {name: lib._local_axis(material, name[-1].lower(), x + 200, y - 700 + 100 * i)
            for i, name in enumerate(("AxisX", "AxisY", "AxisZ"))}
    uv = lib._custom(material, "paint_env_uv", "CMOT_FLOAT4", {
        "NormalWS": (normal, ""), "CameraVec": (camera, ""), "SunDir": (sun, ""),
        "Lean": (wet_node, wet_layer.WET_LEAN_OUTPUT), "LeanStrength": (s["PaintStreakLean"], ""),
        "AxisX": (axes["AxisX"], ""), "AxisY": (axes["AxisY"], ""), "AxisZ": (axes["AxisZ"], "")},
        x + 1000, y)
    env = _glass._texture_parameter(material, lib, ENV_TEXTURE_PARAMETER, texture, sampler,
                                    lib._mask(material, uv, "ba", x + 1200, y + 100), x + 1350, y + 100)
    # UE's F0: lerp(0.08 x Specular, BaseColor, Metallic), from the surface as
    # the wet layer left it (a worn edge is Metallic 1 at the aluminium F0).
    f0 = lib._lerp(material, lib._mul(material, brk, lib._const(material, 0.08, x + 1000, y + 400),
                                      x + 1150, y + 400, a_out="Specular"),
                   brk, brk, x + 1300, y + 400, b_out="BaseColor", alpha_out="Metallic")
    if slot_class in COATED_CLASSES:
        coat, coat_out = brk, "ClearCoat"
        coat_rough, coat_rough_out = brk, "ClearCoatRoughness"
        # the horizon blur follows the glossier (mirroring) layer: the coat
        blur, blur_out = lib._min(material, brk, brk, x + 1200, y + 1100,
                                  a_out="Roughness", b_out="ClearCoatRoughness"), ""
    else:
        coat, coat_out = lib._const(material, 0.0, x + 1000, y + 600), ""
        coat_rough, coat_rough_out = lib._const(material, 1.0, x + 1000, y + 700), ""
        blur, blur_out = brk, "Roughness"
    # Generation 14: the scene's own sky and ground (aircraft_scene_sky.py).
    scene = _scene.add_scene_sky(material, lib, SCENE_PREFIX, uv, sun, blur, blur_out, x, y)
    reflection = lib._custom(material, "paint_env_reflect", "CMOT_FLOAT3", {
        "Env": (env, ""), "EnvScale": (s["PaintEnvEncodeScale"], ""),
        "Gain": (s[GAIN_PARAMETER], ""), "Tint": (tint, ""), "Scene": (scene, ""),
        "NdotV": (lib._mask(material, uv, "r", x + 1200, y - 100), ""),
        "F0": (f0, ""), "Roughness": (brk, "Roughness"),
        "CoatAmount": (coat, coat_out), "CoatRoughness": (coat_rough, coat_rough_out),
        "Amount": (s["PaintEnvAmount"], "")}, x + 1600, y)
    emissive = lib._add(material, brk, reflection, x + 1800, y - 100, a_out="EmissiveColor")
    for name in PASS_THROUGH:
        lib._link(brk, name, make, wet_layer._pin(name))
    if slot_class in COATED_CLASSES:
        for name in COAT_PASS_THROUGH:
            lib._link(brk, name, make, wet_layer._pin(name))
    lib._link(emissive, "", make, wet_layer._pin("EmissiveColor"))
    wet_layer._commit(lib, material, make)
    return reflection
