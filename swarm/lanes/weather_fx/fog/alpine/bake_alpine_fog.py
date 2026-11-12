"""Offline bake for the alpine valley-fog lane (weather_fx.fog.alpine). Mac side.

VISUAL-ONLY. Standard library only, deterministic. Writes next to itself:

    alpine_fog.json      the fog model, the engine numbers per tier, check tables
    alpine_fog_top.png   256x256 RGBA8 tileable fog-top relief for tiers 1-2
                         (R,G normal xy; B height; A ambient occlusion)

    python swarm/lanes/weather_fx/fog/alpine/bake_alpine_fog.py

The look: a shallow radiation-fog layer filling the valley under the peaks (a
"sea of fog"), seen from above by the 5000 m chase camera. Density is one
exponential in height, which is the only profile UE's ExponentialHeightFog
draws, so tier 0 costs no new pass, no texture and no memory:

    sigma(z) = (1 / H) * exp(-(z - z_top) / H)        [1/m]

z_top is the height where the vertical optical depth from above is exactly 1
(the surface the eye reads as the fog's top). Nothing here is a render result.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANE = "weather_fx.fog.alpine"

# ---- look choices (UNCALIBRATED: no frame has been rendered) ---------------
FOG_TOP_M = 1900.0          # tau = 1 surface, about 300 m above the valley floor
SCALE_HEIGHT_M = 200.0      # e-folding height of the density
VALLEY_FLOOR_M = 1600.0     # round value, the same floor the exposure lane uses
GROUND_ALBEDO_VALLEY = 0.35  # mixed snow / forest / village under the fog
FOG_ASYMMETRY_G = 0.85      # Henyey-Greenstein g of water droplets, visible
MAX_OPACITY = 0.92          # what FlightSimVisualScene.cpp sets on the fog today
DIRECTIONAL_EXPONENT = 16.0  # tiers 1+: broad forward glow (look choice)
DIRECTIONAL_GAIN = 0.5      # tiers 1+: of the base in-scatter (look choice)

# ---- named constants -------------------------------------------------------
KOSCHMIEDER = 3.912         # ln(1/0.02): Koschmieder 1924, 2 % contrast threshold
# core/scene/weather_visuals.py ENGINE_FOG_DENSITY_PER_EXTINCTION, read there on
# the UE 5.7.4 sources: extinction [1/m] = FogDensity * 0.1 * ln(2)^2.
ENGINE_FOG_DENSITY_PER_EXTINCTION = 1.0 / (0.1 * math.log(2.0) ** 2)
# The engine's height term is exp2(-(FogHeightFalloff / 1000) * dz_cm), so
# H [m] = 10 / (FogHeightFalloff * ln 2)  (FlightSimGoogleTiles.cpp FogColumnM).
ENGINE_FALLOFF_TIMES_SCALE_HEIGHT_M = 10.0 / math.log(2.0)
# Rayleigh scattering per km and scale height: the same SkyAtmosphere defaults
# the alpine aerial-perspective lane bakes with (Hillaire 2020, table 1).
RAYLEIGH_PER_KM = (0.005802, 0.013558, 0.0331)
RAYLEIGH_SCALE_HEIGHT_KM = 8.0
LUMA = (0.2126, 0.7152, 0.0722)  # Rec. 709 luminance weights
# Nominal light at the fog top, sun 30 deg: the exposure lane's rows
# (lighting_exposure.physical_light_units.alpine) at 1600 m and 3000 m,
# interpolated linearly to FOG_TOP_M. Model values, not measurements.
NOMINAL_SUN_ELEVATION_DEG = 30.0
_PLU_30 = {1600.0: (86478.6, 9694.0), 3000.0: (88118.5, 8137.1)}
SNOW_ALBEDO = 0.9           # the exposure lane's constant

TEX_N = 256
TEX_TILE_M = 4000.0         # one tile of the relief on the ground
TEX_AMPLITUDE_M = 60.0      # peak-to-trough of the fog top's relief
TEX_SEED = 1911


def _r(x: float, digits: int = 6) -> float:
    return float(f"{x:.{digits}g}")


# ---- the density model -----------------------------------------------------
def sigma_per_m(z_m: float, top_m: float = FOG_TOP_M, h_m: float = SCALE_HEIGHT_M) -> float:
    return math.exp(-(z_m - top_m) / h_m) / h_m


def vertical_tau(z_m: float, top_m: float = FOG_TOP_M, h_m: float = SCALE_HEIGHT_M) -> float:
    """Optical depth of the whole column above z."""
    return math.exp(-(z_m - top_m) / h_m)


def slant_tau(camera_m: float, ground_m: float, depression_deg: float,
              top_m: float = FOG_TOP_M, h_m: float = SCALE_HEIGHT_M) -> float:
    """Optical depth from a camera down to ground it sees at this depression
    below the horizon (flat-earth; fine for the few tens of km in frame)."""
    s = math.sin(math.radians(depression_deg))
    if s <= 0.0 or camera_m <= ground_m:
        raise ValueError("needs a camera above the ground point and a downward ray")
    return (vertical_tau(ground_m, top_m, h_m) - vertical_tau(camera_m, top_m, h_m)) / s


def transmittance(tau: float, max_opacity: float = MAX_OPACITY) -> float:
    """What the engine draws: exp(-tau), floored by FogMaxOpacity."""
    return max(math.exp(-tau), 1.0 - max_opacity)


def visibility_m(z_m: float) -> float:
    return KOSCHMIEDER / sigma_per_m(z_m)


def engine_fog(top_m: float = FOG_TOP_M, h_m: float = SCALE_HEIGHT_M) -> dict:
    """UExponentialHeightFogComponent numbers for the layer, referenced at z_top."""
    return {
        "FogDensity": sigma_per_m(top_m, top_m, h_m) * ENGINE_FOG_DENSITY_PER_EXTINCTION,
        "FogHeightFalloff": ENGINE_FALLOFF_TIMES_SCALE_HEIGHT_M / h_m,
        "reference_height_m_amsl": top_m,
    }


# ---- the fog's brightness --------------------------------------------------
def two_stream_albedo(tau: float, g: float = FOG_ASYMMETRY_G) -> float:
    """Diffuse reflectance of a non-absorbing layer, two-stream
    (Bohren 1987, Am. J. Phys. 55, 524): (1-g) tau / (2 + (1-g) tau)."""
    x = (1.0 - g) * tau
    return x / (2.0 + x)


def layer_over_ground_albedo(layer: float, ground: float) -> float:
    """Layer plus a Lambertian ground under it, all inter-reflections
    (adding method): A + (1-A)^2 Ag / (1 - A Ag)."""
    return layer + (1.0 - layer) ** 2 * ground / (1.0 - layer * ground)


def fog_albedo() -> float:
    return layer_over_ground_albedo(
        two_stream_albedo(vertical_tau(VALLEY_FLOOR_M)), GROUND_ALBEDO_VALLEY)


def sun_tint(sun_elevation_deg: float, z_m: float = FOG_TOP_M) -> tuple:
    """Linear Rec. 709 colour of the direct sun at the fog top, luminance 1.
    Rayleigh only, plane-parallel air mass; Mie and ozone are left out."""
    air_mass = 1.0 / math.sin(math.radians(sun_elevation_deg))
    column = RAYLEIGH_SCALE_HEIGHT_KM * math.exp(-z_m / 1000.0 / RAYLEIGH_SCALE_HEIGHT_KM)
    rgb = [math.exp(-b * column * air_mass) for b in RAYLEIGH_PER_KM]
    y = sum(w * c for w, c in zip(LUMA, rgb))
    return tuple(c / y for c in rgb)


def sun_inscatter_cd_m2(sun_normal_lux: float, sun_elevation_deg: float) -> float:
    """The sun's share of the fog's luminance, added as FogInscatteringColor.
    The sky's share is the engine's (SkyAtmosphereAmbientContributionColorScale)."""
    return fog_albedo() * sun_normal_lux * math.sin(math.radians(sun_elevation_deg)) / math.pi


def nominal_light() -> dict:
    (z0, (s0, k0)), (z1, (s1, k1)) = sorted(_PLU_30.items())
    f = (FOG_TOP_M - z0) / (z1 - z0)
    return {"sun_direct_normal_lux": s0 + (s1 - s0) * f,
            "sky_diffuse_horizontal_lux": k0 + (k1 - k0) * f}


# ---- the fog-top relief texture (tiers 1-2) --------------------------------
def _lattice(ix: int, iy: int, period: int, seed: int) -> float:
    h = ((ix % period) * 374761393 + (iy % period) * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    h ^= h >> 16
    return h / 4294967296.0


def _value_noise(x: float, y: float, period: int, seed: int) -> float:
    ix, iy = int(math.floor(x)), int(math.floor(y))
    fx, fy = x - ix, y - iy
    ux, uy = fx * fx * (3.0 - 2.0 * fx), fy * fy * (3.0 - 2.0 * fy)
    a = _lattice(ix, iy, period, seed)
    b = _lattice(ix + 1, iy, period, seed)
    c = _lattice(ix, iy + 1, period, seed)
    d = _lattice(ix + 1, iy + 1, period, seed)
    return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy


def relief_height(n: int = TEX_N, seed: int = TEX_SEED) -> list:
    """Tileable fractal height in 0..1, row-major list of n*n floats."""
    periods = (4, 8, 16, 32, 64)
    out = []
    for y in range(n):
        for x in range(n):
            v, amp = 0.0, 0.5
            for k, p in enumerate(periods):
                v += amp * _value_noise(x * p / n, y * p / n, p, seed + k)
                amp *= 0.5
            out.append(v)
    lo, hi = min(out), max(out)
    return [(v - lo) / (hi - lo) for v in out]


def relief_rgba(n: int = TEX_N) -> bytes:
    h = relief_height(n)
    texel = TEX_TILE_M / n
    at = lambda x, y: h[(y % n) * n + (x % n)]  # noqa: E731
    dirs = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))
    q = lambda v: max(0, min(255, int(v * 255.0 + 0.5)))  # noqa: E731
    out = bytearray()
    for y in range(n):
        for x in range(n):
            here = at(x, y)
            dx = (at(x + 1, y) - at(x - 1, y)) * TEX_AMPLITUDE_M / (2.0 * texel)
            dy = (at(x, y + 1) - at(x, y - 1)) * TEX_AMPLITUDE_M / (2.0 * texel)
            inv = 1.0 / math.sqrt(dx * dx + dy * dy + 1.0)
            # occlusion: mean positive slope to the neighbours at 3 and 8 texels
            occ = 0.0
            for r in (3, 8):
                for ax, ay in dirs:
                    dist = r * texel * math.sqrt(ax * ax + ay * ay)
                    occ += max(0.0, (at(x + ax * r, y + ay * r) - here) * TEX_AMPLITUDE_M / dist)
            ao = 1.0 / (1.0 + 4.0 * occ / 16.0)
            out += bytes((q(-dx * inv * 0.5 + 0.5), q(-dy * inv * 0.5 + 0.5), q(here), q(ao)))
    return bytes(out)


def png_bytes(rgba: bytes, n: int) -> bytes:
    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    raw = b"".join(b"\x00" + rgba[y * n * 4:(y + 1) * n * 4] for y in range(n))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---- the card --------------------------------------------------------------
def build(rgba: bytes | None = None) -> dict:
    eng = engine_fog()
    light = nominal_light()
    albedo = fog_albedo()
    sun_lum = sun_inscatter_cd_m2(light["sun_direct_normal_lux"], NOMINAL_SUN_ELEVATION_DEG)
    snow_lum = SNOW_ALBEDO * (light["sun_direct_normal_lux"] * 0.5
                              + light["sky_diffuse_horizontal_lux"]) / math.pi
    tiers = [
        {"tier": 0, "est_vram_mb": 0.0,
         "summary": "analytic only: the valley layer in ExponentialHeightFog's second fog "
                    "slot, sun in-scatter as one constant colour; no texture, no new pass",
         "cvars": {"r.Fog": 1, "r.VolumetricFog": 0},
         "directional_inscattering": False, "top_card_shells": 0},
        {"tier": 1, "est_vram_mb": 0.1,
         "summary": "tier 0 + one unlit translucent card at the fog top sampling "
                    "alpine_fog_top.png (relief shading, depth-faded shoreline) and the "
                    "broad sun-side glow",
         "cvars": {"r.Fog": 1, "r.VolumetricFog": 0},
         "directional_inscattering": True, "top_card_shells": 1},
        {"tier": 2, "est_vram_mb": 0.1,
         "summary": "tier 1 with four stacked shells 30 m apart for parallax in the relief; "
                    "same texture, up to four translucent layers over the valley pixels",
         "cvars": {"r.Fog": 1, "r.VolumetricFog": 0},
         "directional_inscattering": True, "top_card_shells": 4},
        {"tier": 3, "est_vram_mb": 6.0,
         "summary": "tier 1 + UE volumetric fog (froxels) for peak shadows in the fog; only "
                    "pays off for a camera inside the valley, the 5000 m camera is beyond "
                    "the froxel range",
         "cvars": {"r.Fog": 1, "r.VolumetricFog": 1, "r.VolumetricFog.GridPixelSize": 16,
                   "r.VolumetricFog.GridSizeZ": 32,
                   "r.VolumetricFog.HistoryMissSupersampleCount": 1},
         "directional_inscattering": True, "top_card_shells": 1},
    ]
    card = {
        "lane": LANE,
        "label": "visual-only; every value is a MODEL value, UNMEASURED on the render machine",
        "model": {
            "profile": "sigma(z) = exp(-(z - fog_top_m) / scale_height_m) / scale_height_m  [1/m]",
            "fog_top_m_amsl": FOG_TOP_M,
            "scale_height_m": SCALE_HEIGHT_M,
            "valley_floor_m_amsl": VALLEY_FLOOR_M,
            "asymmetry_g": FOG_ASYMMETRY_G,
            "ground_albedo_valley": GROUND_ALBEDO_VALLEY,
            "max_opacity": MAX_OPACITY,
            "koschmieder_constant": KOSCHMIEDER,
            "uncalibrated": ["fog_top_m_amsl", "scale_height_m", "ground_albedo_valley",
                             "fog_albedo (two-stream)", "directional glow"],
        },
        "engine": {
            "slot": "UExponentialHeightFogComponent::SecondFogData",
            "FogDensity": _r(eng["FogDensity"]),
            "FogHeightFalloff": _r(eng["FogHeightFalloff"]),
            "reference_height_m_amsl": FOG_TOP_M,
            "FogDensity_per_extinction_per_m": _r(ENGINE_FOG_DENSITY_PER_EXTINCTION, 9),
            "fog_albedo": _r(albedo),
            "inscatter_formula": "FogInscatteringColor [cd/m2] = sun_tint_rgb * fog_albedo * "
                                 "sun_direct_normal_lux * sin(sun_elevation) / pi",
            "directional_exponent": DIRECTIONAL_EXPONENT,
            "directional_gain_of_inscatter": DIRECTIONAL_GAIN,
        },
        "sun_tint_rgb": [{"sun_elevation_deg": e, "rgb": [_r(c) for c in sun_tint(e)]}
                         for e in (15.0, 30.0, 50.0)],
        "nominal": {
            "sun_elevation_deg": NOMINAL_SUN_ELEVATION_DEG,
            "sun_direct_normal_lux": _r(light["sun_direct_normal_lux"]),
            "sky_diffuse_horizontal_lux": _r(light["sky_diffuse_horizontal_lux"]),
            "sun_inscatter_cd_m2": _r(sun_lum),
            "flat_sunlit_snow_cd_m2": _r(snow_lum),
            "sun_inscatter_over_flat_sunlit_snow": _r(sun_lum / snow_lum),
        },
        "column": [{"altitude_m": z, "vertical_tau": _r(vertical_tau(z)),
                    "visibility_m": _r(visibility_m(z))}
                   for z in (1600.0, 1750.0, 1900.0, 2100.0, 2300.0, 2700.0, 4478.0, 5000.0)],
        "from_5000_m": [{"depression_deg": d, "ground_m": g,
                         "transmittance": _r(transmittance(slant_tau(5000.0, g, d)))}
                        for g in (1600.0, 1900.0, 2300.0, 2700.0, 3500.0)
                        for d in (10.0, 20.0, 30.0, 45.0)],
        "top_relief": {
            "file": "alpine_fog_top.png", "size": TEX_N, "tile_m": TEX_TILE_M,
            "amplitude_m": TEX_AMPLITUDE_M, "seed": TEX_SEED,
            "channels": "R,G tangent normal xy (0.5 = flat); B height 0..1; A ambient occlusion",
            "import": "linear (sRGB off), mips on; BC7 estimated 0.09 MB with mips",
            "rgba_sha256": hashlib.sha256(rgba if rgba is not None else relief_rgba()).hexdigest(),
        },
        "tiers": tiers,
    }
    return card


def main() -> None:
    rgba = relief_rgba()
    (HERE / "alpine_fog_top.png").write_bytes(png_bytes(rgba, TEX_N))
    text = json.dumps(build(rgba), indent=1, sort_keys=True) + "\n"
    (HERE / "alpine_fog.json").write_text(text, encoding="utf-8")
    for name in ("alpine_fog.json", "alpine_fog_top.png"):
        print(name, hashlib.sha256((HERE / name).read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
