"""The scene's own sky and ground in the airframe and canopy mirrors
(LOOK_GENERATION 16, lane aircraft-refl, 2026-11-15). BEAUTY ONLY, Emissive only.

Cause (read in code; no frame rendered on this Mac): the paint / bare-metal
mirror (scripts/aircraft_paint_reflect.py) and the canopy mirror
(scripts/aircraft_glass_reflect.py) both look up ONE baked strip, the coastal
lane's 64x32 clear-sky-over-sea picture (T_GlassEnv_64), tinted by the
-xplane-horizon hue when a render carries it. So a 747 over a sunset sea, a
C172 under the #9 storm deck and a Cessna over Kansas farmland all mirror the
same blue coastal noon sky above and the same sea below: the reflection's
colour is a constant, not the scene. A real airframe mirrors what is around
it: an orange horizon at sunset, a grey deck under a storm, green-brown
farmland under the belly.

What this adds (switch ``-scene-mirror=``, ON by default; ``off`` keeps
generation 13's strip exactly, the A/B):

* ABOVE the horizon the mirror reads the scene's own SkyAtmosphere along the
  reflected ray (UE's SkyAtmosphereViewLuminance node: one sample of the
  view's Sky View LUT, the same radiance the sky dome draws, aureole and
  sunset band included; sun disk excluded, so the sharp sun highlight stays
  the directional light's own GGX lobe). Under cloud cover c it goes toward
  the CIE standard overcast sky (Moon & Spencer 1942, CIE S 011/E:2003 sky
  type 1): achromatic, L(e) = Lz (1 + 2 sin e) / 3, the horizon a third of
  the zenith, with Lz = OvercastShare x the clear zenith (OvercastShare =
  1 - aircraft_glass_reflect.OVERCAST_DIM, the gain rule's own number).
* BELOW the horizon it reads the scene's ground: the sky light's lower
  hemisphere colour (core/scene/hero_lighting.py: albedo x E_h / pi, cd/m2)
  x the sky light's colour and intensity (the capture multiplies it by both),
  seen through the air under the aircraft, L = L_g exp(-tau / |r.z|) +
  L_inscatter, where L_inscatter is the same Sky View LUT sample (UE builds
  it with Ground = false: in-scatter only, SkyAtmosphere.usf
  RenderSkyViewLutCS) and tau the vertical optical depth below the aircraft
  from the scene's own atmosphere: sum over Rayleigh and Mie of
  sigma x H x (1 - exp(-h / H)) (the exponential profiles of
  USkyAtmosphereComponent; UE's defaults give tau_R(green) 0.108, against the
  0.0973 Bucholtz 1995 tabulates for 550 nm at sea level).
* The horizon line is blurred by the surface's GGX lobe: the blend is
  smoothstep(-w, w, r.z) with w = 2 alpha, alpha = roughness^2 (Walter et
  al. 2007: the reflected lobe's half-width is about 2 x the half-vector's,
  whose width is alpha): a wet coat (0.03) shows a knife-edge horizon, a
  0.4 paint a soft gradient.
* Level: SceneShare 0.5 = aircraft_glass_reflect.SKY_HORIZON_SHARE (0.10)
  over CLEAR_HORIZON_SHARE (0.2, the same comment's clear-sky horizon share
  of E / pi): the scene path lands at the strip path's level, kept half of
  physical on purpose because the engine's specular IBL already mirrors the
  captured sky (the canopy lane's double count). Not a new number.

Fallback, per pixel: a zenith sample below VALID_ZENITH (the Sky View LUT is
not drawn in this view: no SkyAtmosphere, a capture without it) or SceneScale
0 (switch off, a generation-13 master, an interior canopy view) draws the
strip exactly as generation 13 did.

Labels: Emissive only, on masters that stay opaque with no World Position
Offset; nothing else of the material changes, so ID, depth, stencil, mask,
SCS_Normal and SCS_BaseColor see the same surface. A measure render builds no
aircraft look. GPU: two LUT fetches and about forty ALU per airframe pixel,
no loop, no march (the iGPU TDR budget).

Stdlib only (imported by aircraft_look.py, which also runs inside the
editor's Python). UNCALIBRATED: no frame has been rendered with it.
"""

from __future__ import annotations

import math

UNCALIBRATED = "UNCALIBRATED: set by probe render on the render machine"

#: The host's switch (FFlightSimAircraftFXOptions::ParseParams; one of
#: aircraft_look.FX_SWITCHES): on by default, -scene-mirror=off draws
#: generation 13's strip on the paint, bare metal and canopy.
SWITCH_KEY = "scene-mirror="
SWITCH_DEFAULT = True

#: The two Custom-node bodies (assets/shaders/aircraft/<name>.hlsl), merged
#: into aircraft_look.SHADER_INPUTS.
SCENE_SKY_SHADER_INPUTS = {
    "scene_sky_dir": ("EnvUv", "SunDir"),
    "scene_sky_env": ("SkyView", "SkyZenith", "Ground", "GroundTau", "Dir", "Roughness",
                      "Cover", "OvercastShare", "SceneScale"),
}

#: Literals inside scene_sky_env.hlsl (pinned to the text by test).
#: Rec. 709 luminance weights (ITU-R BT.709-6).
LUMA = (0.2126, 0.7152, 0.0722)
#: cd/m2: a zenith below this is "the Sky View LUT is not drawn here" (a clear
#: day's zenith is ~10^3, civil twilight's ~1; Kittler & Darula / CIE S 011).
VALID_ZENITH = 1.0e-4
#: The ground transmittance's |r.z| floor: about 3 deg below the horizon, so a
#: grazing ray's exp(-tau / |r.z|) cannot divide by zero.
MIN_DOWN = 0.05
#: The horizon blend half-width, w = clamp(2 alpha, MIN_W, 1).
MIN_W = 0.01

#: The clear sky's horizon luminance as a share of E / pi (the comment above
#: aircraft_glass_reflect.SKY_HORIZON_SHARE), and the level the scene path is
#: drawn at: SKY_HORIZON_SHARE / CLEAR_HORIZON_SHARE.
CLEAR_HORIZON_SHARE = 0.2
SKY_HORIZON_SHARE = 0.10
SCENE_SHARE = SKY_HORIZON_SHARE / CLEAR_HORIZON_SHARE
#: The CIE overcast zenith as a share of the clear zenith: 1 - OVERCAST_DIM.
OVERCAST_DIM = 0.75
OVERCAST_SHARE = 1.0 - OVERCAST_DIM

#: Fallback vertical optical depth to the ground (per channel) when the scene
#: has no SkyAtmosphere component: the UE 5.7 defaults' Rayleigh column at
#: sea level (RayleighScattering (0.175287, 0.409607, 1) x 0.0331 /km x 8 km)
#: plus its Mie extinction column ((0.003996 + 0.000444) /km x 1.2 km).
UE_DEFAULT_RAYLEIGH_PER_KM = tuple(c * 0.0331 for c in (0.175287, 0.409607, 1.0))
UE_DEFAULT_RAYLEIGH_H_KM = 8.0
UE_DEFAULT_MIE_PER_KM = (0.003996 + 0.000444,) * 3
UE_DEFAULT_MIE_H_KM = 1.2
#: Bucholtz 1995 (Appl. Opt. 34, 2765), Rayleigh optical depth, 550 nm, sea level.
BUCHOLTZ_TAU_R_550 = 0.0973

#: Parameter suffixes the host sets on each MID (prefix "Paint" or "Glass").
SCENE_SCALE = "EnvSceneScale"
GROUND = "SkyGround"
GROUND_TAU = "GroundTau"
COVER = "SkyCover"
OVERCAST = "OvercastShare"


def parameters(prefix):
    """{name: default} of the scalars and vectors one master carries. The
    SceneScale default 0 is the point: the master draws the strip (generation
    13) until the host sets it."""
    return {
        "scalars": {f"{prefix}{SCENE_SCALE}": 0.0, f"{prefix}{COVER}": 0.0,
                    f"{prefix}{OVERCAST}": OVERCAST_SHARE},
        "vectors": {f"{prefix}{GROUND}": (0.0, 0.0, 0.0, 0.0),
                    f"{prefix}{GROUND_TAU}": tuple(ground_tau(0.0)) + (0.0,)},
    }


def parse_scene_sky(params):
    """Twin of the host's switch: True unless -scene-mirror=off (or -aircraft-look=off)."""
    import aircraft_look as look
    return look.parse_fx_switches(params)[SWITCH_KEY[:-1]]


# -- host-side twins (FlightSimAircraftFX.cpp) ----------------------------------

def column(sigma_per_km, scale_height_km, altitude_km):
    """Optical depth of an exponential layer between the ground and h:
    sigma x H x (1 - exp(-h / H)); 0 at the ground, sigma x H far above it."""
    h = max(float(altitude_km), 0.0)
    big_h = max(float(scale_height_km), 1.0e-3)
    return max(float(sigma_per_km), 0.0) * big_h * (1.0 - math.exp(-h / big_h))


def ground_tau(altitude_km, rayleigh_per_km=UE_DEFAULT_RAYLEIGH_PER_KM,
               rayleigh_h_km=UE_DEFAULT_RAYLEIGH_H_KM, mie_per_km=UE_DEFAULT_MIE_PER_KM,
               mie_h_km=UE_DEFAULT_MIE_H_KM):
    """Per-channel vertical optical depth from the aircraft down to the
    ground (FFlightSimAircraftFX::SceneSkyGroundTau)."""
    return tuple(column(r, rayleigh_h_km, altitude_km) + column(m, mie_h_km, altitude_km)
                 for r, m in zip(rayleigh_per_km, mie_per_km))


def ground_radiance(lower_hemisphere, light_color, intensity):
    """What the sky light draws below the horizon: LowerHemisphereColor x
    LightColor x Intensity (the capture multiplies the solid lower hemisphere
    by both; hero_lighting.plan_sidecar divides a stated fill back out)."""
    i = max(float(intensity), 0.0)
    return tuple(max(a, 0.0) * max(b, 0.0) * i for a, b in zip(lower_hemisphere, light_color))


def scene_scale(enabled, interior=False):
    """SceneScale the host sets: SCENE_SHARE on, 0 off or seen from inside."""
    return SCENE_SHARE if enabled and not interior else 0.0


# -- numpy-free twins of the shader bodies (tests/test_aircraft_scene_sky.py) ---

def sky_dir(env_uv, sun_dir):
    """Twin of scene_sky_dir.hlsl: the reflected ray back from the strip uv."""
    sl = math.hypot(sun_dir[0], sun_dir[1])
    sd = (sun_dir[0] / sl, sun_dir[1] / sl) if sl > 1.0e-4 else (1.0, 0.0)
    azim = (env_uv[0] - 0.5) * 2.0 * math.pi
    elev = (0.5 - env_uv[1]) * math.pi
    ca, sa = math.cos(azim), math.sin(azim)
    hx, hy = sd[0] * ca + sd[1] * sa, -sd[0] * sa + sd[1] * ca
    ce = math.cos(elev)
    return (hx * ce, hy * ce, math.sin(elev))


def _smoothstep(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def _y(rgb):
    return sum(w * c for w, c in zip(LUMA, rgb))


def overcast(zenith_luminance, sin_elev):
    """CIE overcast (Moon & Spencer 1942): Lz (1 + 2 sin e) / 3, e >= 0."""
    return zenith_luminance * (1.0 + 2.0 * min(max(sin_elev, 0.0), 1.0)) / 3.0


def horizon_width(roughness):
    a = min(max(roughness, 0.0), 1.0) ** 2
    return min(max(2.0 * a, MIN_W), 1.0)


def sky_env(sky_view, sky_zenith, ground, tau, direction, roughness, cover,
            overcast_share=OVERCAST_SHARE, scale=SCENE_SHARE):
    """Twin of scene_sky_env.hlsl: (r, g, b, use)."""
    yz = _y(sky_zenith)
    use = 1.0 if (scale > 0.0 and yz > VALID_ZENITH) else 0.0
    c = min(max(cover, 0.0), 1.0)
    rz = min(max(direction[2], -1.0), 1.0)
    view = tuple(max(v, 0.0) for v in sky_view)
    ovc = overcast(yz * max(overcast_share, 0.0), rz)
    sky = tuple(v + (ovc - v) * c for v in view)
    down = max(-rz, MIN_DOWN)
    # overcast: the in-scatter below the horizon dims to the overcast horizon (Lz / 3)
    ovh = yz * max(overcast_share, 0.0) / 3.0
    below = tuple(max(g, 0.0) * math.exp(-max(t, 0.0) / down) + (v + (ovh - v) * c)
                  for g, t, v in zip(ground, tau, view))
    w = horizon_width(roughness)
    up = _smoothstep(-w, w, rz)
    s = max(scale, 0.0)
    return tuple((b + (k - b) * up) * s * use for b, k in zip(below, sky)) + (use,)


def mix(strip_env, scene):
    """Both reflect bodies: lerp(strip, scene.rgb, scene.a)."""
    a = min(max(scene[3], 0.0), 1.0)
    return tuple(e + (s - e) * a for e, s in zip(strip_env, scene[:3]))


# -- the master-graph builder (only this touches unreal) ----------------------

def add_scene_sky(material, lib, prefix, uv, sun, roughness, roughness_out, x, y):
    """The scene-sky Custom node of one reflect master: the reflected ray back
    from ``uv`` (paint_env_uv / glass_reflect_uv; its zw), the scene's Sky
    View LUT along it and at the zenith, and the host's ground. Returns the
    float4 node the reflect body's ``Scene`` input takes."""
    unreal = lib._u()
    params = parameters(prefix)
    scalars = {name: lib._scalar(material, name, value, x, y + 1200 + 100 * i)
               for i, (name, value) in enumerate(params["scalars"].items())}
    vectors = {name: lib._mask(material, lib._vector(material, name, value, x - 200, y + 1500 + 100 * i),
                               "rgb", x, y + 1500 + 100 * i)
               for i, (name, value) in enumerate(params["vectors"].items())}
    direction = lib._custom(material, "scene_sky_dir", "CMOT_FLOAT3", {
        "EnvUv": (lib._mask(material, uv, "ba", x + 1200, y + 1200), ""), "SunDir": (sun, "")},
        x + 1350, y + 1200)
    view = lib._node(material, unreal.MaterialExpressionSkyAtmosphereViewLuminance, x + 1500, y + 1200)
    lib._link(direction, "", view, ("WorldDirection", "World Direction", ""))
    zenith = lib._node(material, unreal.MaterialExpressionSkyAtmosphereViewLuminance, x + 1500, y + 1300)
    lib._link(lib._const3(material, (0.0, 0.0, 1.0), x + 1350, y + 1300), "", zenith,
              ("WorldDirection", "World Direction", ""))
    return lib._custom(material, "scene_sky_env", "CMOT_FLOAT4", {
        "SkyView": (view, ""), "SkyZenith": (zenith, ""),
        "Ground": (vectors[f"{prefix}{GROUND}"], ""), "GroundTau": (vectors[f"{prefix}{GROUND_TAU}"], ""),
        "Dir": (direction, ""), "Roughness": (roughness, roughness_out),
        "Cover": (scalars[f"{prefix}{COVER}"], ""), "OvercastShare": (scalars[f"{prefix}{OVERCAST}"], ""),
        "SceneScale": (scalars[f"{prefix}{SCENE_SCALE}"], "")}, x + 1700, y + 1200)
