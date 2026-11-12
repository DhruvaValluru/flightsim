"""Mac bake: aerial-perspective lookup for the alpine scenario. Visual-only.

Integrates transmittance and single-scattered sunlight along view rays through
a Rayleigh + Mie + ozone atmosphere with the ASSUMED constants listed below,
so a render pass could sample three tiny textures instead of ray-marching the
camera aerial-perspective volume every frame. That render pass is a proposal
(INTEGRATION.md); it has not been written.

CONSTANTS ARE ASSUMED, NOT SOURCED. They were typed from memory of Hillaire
2020 and of the engine's SkyAtmosphere defaults; nothing was fetched and
nothing was read from the pinned build. They are also not what this project
renders: FFlightSimWorldBeauty::ApplyAtmosphere sets the Mie scale height,
anisotropy, scattering and absorption per preset and visibility, and
FlightSimDustHaze rewrites the Mie scale again. Re-bake with the values a
Windows run records in render.json before using the textures.

    .venv/bin/python swarm/lanes/atmosphere_clouds/aerial_perspective/alpine/bake_alpine_ap.py

Writes next to this file:
  alpine_ap_a.rgba16f   rgb = Rayleigh in-scatter integral, a = 1
  alpine_ap_b.rgba16f   rgb = transmittance, a = 1
  alpine_ap_c.rgba16f   rgb = Mie in-scatter integral, a = 1
  alpine_ap.json        axes, layout, constants and reference values

Layout of every texture: little-endian float16 RGBA, row-major, width ND,
height NSUN * NALT * NMU; row = (sun * NALT + alt) * NMU + mu.

Radiance of the air in front of a surface at distance d:
    L = E_sun * (pR(cos) * A.rgb + pM(cos) * C.rgb)      [cd/m2, E_sun in lux
    seen = surface * B.rgb + L                            outside the atmosphere]
with pR = 3/(16 pi) (1 + cos^2) and pM = Henyey-Greenstein g = 0.8, cos the
angle between the view ray and the sun. The split is exact for single
scattering from a directional sun because the phase angle is constant along a
straight ray.

MODEL LIMITS (stated, not hidden):
  * single scattering only. Multiple scattering and snow bounce are absent, so
    the in-scatter is a lower bound; `ms_gain` in the JSON is 1.0 and
    UNCALIBRATED until the Windows gate fits it against the engine.
  * terrain shadowing of the air and the planet's shadow are ignored (sun
    elevations baked are 15 deg and above).
Transmittance has none of these limits: it is the model's exact value.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# ASSUMED, per km: typed from memory, unverified (see the module docstring).
RAYLEIGH_SCATTERING = np.array([0.005802, 0.013558, 0.033100])
RAYLEIGH_SCALE_HEIGHT_KM = 8.0
MIE_SCATTERING = 0.003996
MIE_ABSORPTION = 0.000444
MIE_SCALE_HEIGHT_KM = 1.2
MIE_G = 0.8
OZONE_ABSORPTION = np.array([0.000650, 0.001881, 0.000085])
OZONE_CENTRE_KM = 25.0
OZONE_HALF_WIDTH_KM = 15.0
PLANET_RADIUS_KM = 6360.0
ATMOSPHERE_HEIGHT_KM = 60.0

ALTITUDES_M = [2000.0, 3000.0, 4000.0, 5000.0, 6000.0]
SUN_ELEVATIONS_DEG = [15.0, 30.0, 50.0]
NMU = 16            # view-elevation samples, sin(elevation) linear in [-MU_MAX, MU_MAX]
MU_MAX = 0.5
ND = 32             # distance samples, d = D_MAX * (i / (ND - 1))^2
D_MAX_KM = 128.0
SUBSTEPS = 8
OUTPUTS = ("alpine_ap_a.rgba16f", "alpine_ap_b.rgba16f", "alpine_ap_c.rgba16f", "alpine_ap.json")
NOMINAL = {"altitude_m": 5000.0, "sun_elevation_deg": 30.0}


def densities(h_km):
    """Rayleigh, Mie and ozone density (unitless) at altitude h (km, clamped at 0)."""
    h = np.maximum(np.asarray(h_km, dtype=np.float64), 0.0)
    return (np.exp(-h / RAYLEIGH_SCALE_HEIGHT_KM),
            np.exp(-h / MIE_SCALE_HEIGHT_KM),
            np.maximum(0.0, 1.0 - np.abs(h - OZONE_CENTRE_KM) / OZONE_HALF_WIDTH_KM))


def extinction(h_km):
    """RGB extinction per km at altitude h; shape h.shape + (3,)."""
    r, m, o = densities(h_km)
    return (r[..., None] * RAYLEIGH_SCATTERING + m[..., None] * (MIE_SCATTERING + MIE_ABSORPTION)
            + o[..., None] * OZONE_ABSORPTION)


def height_along(h0_km, mu, s_km):
    r0 = PLANET_RADIUS_KM + h0_km
    return np.sqrt(r0 * r0 + s_km * s_km + 2.0 * r0 * s_km * mu) - PLANET_RADIUS_KM


def sun_optical_depth_table(sun_elevation_deg, n_alt=241, n_step=600):
    """RGB optical depth from altitude h to the top of the atmosphere towards the sun."""
    mu_s = math.sin(math.radians(sun_elevation_deg))
    alts = np.linspace(0.0, ATMOSPHERE_HEIGHT_KM, n_alt)
    r0 = PLANET_RADIUS_KM + alts
    rt = PLANET_RADIUS_KM + ATMOSPHERE_HEIGHT_KM
    length = -r0 * mu_s + np.sqrt(np.maximum(r0 * r0 * (mu_s * mu_s - 1.0) + rt * rt, 0.0))
    t = (np.arange(n_step) + 0.5) / n_step
    s = length[:, None] * t[None, :]
    h = height_along(alts[:, None], mu_s, s)
    tau = extinction(h).sum(axis=1) * (length / n_step)[:, None]
    return alts, tau


def march(alt_km, mu, s_edges, sun_table):
    """Cumulative (T rgb, Rayleigh in-scatter rgb, Mie in-scatter rgb) at each s edge."""
    alts, tau_sun = sun_table
    ds = np.diff(s_edges)
    mid = 0.5 * (s_edges[:-1] + s_edges[1:])
    h = height_along(alt_km, mu, mid)
    ext = extinction(h)
    tau_edge = np.concatenate([np.zeros((1, 3)), np.cumsum(ext * ds[:, None], axis=0)])
    t_mid = np.exp(-0.5 * (tau_edge[:-1] + tau_edge[1:]))
    hc = np.clip(h, 0.0, ATMOSPHERE_HEIGHT_KM)
    t_sun = np.exp(-np.stack([np.interp(hc, alts, tau_sun[:, c]) for c in range(3)], axis=1))
    r, m, _ = densities(h)
    common = t_mid * t_sun * ds[:, None]
    zero = np.zeros((1, 3))
    i_r = np.concatenate([zero, np.cumsum(common * r[:, None] * RAYLEIGH_SCATTERING, axis=0)])
    i_m = np.concatenate([zero, np.cumsum(common * m[:, None] * MIE_SCATTERING, axis=0)])
    return np.exp(-tau_edge), i_r, i_m


def phase_rayleigh(cos_theta):
    return 3.0 / (16.0 * math.pi) * (1.0 + cos_theta * cos_theta)


def phase_mie(cos_theta, g=MIE_G):
    return (1.0 - g * g) / (4.0 * math.pi * (1.0 + g * g - 2.0 * g * cos_theta) ** 1.5)


def reference(altitude_m, sun_elevation_deg, view_elevation_deg, distance_km, steps=1024):
    """Exact model values for one ray (not interpolated from the texture)."""
    s = np.linspace(0.0, distance_km, steps + 1)
    t, i_r, i_m = march(altitude_m / 1000.0, math.sin(math.radians(view_elevation_deg)), s,
                        sun_optical_depth_table(sun_elevation_deg))
    return {"transmittance_rgb": t[-1], "rayleigh_inscatter_rgb": i_r[-1], "mie_inscatter_rgb": i_m[-1]}


def distance_axis():
    return D_MAX_KM * (np.arange(ND) / (ND - 1.0)) ** 2


def mu_axis():
    return np.linspace(-MU_MAX, MU_MAX, NMU)


def build():
    j = np.arange((ND - 1) * SUBSTEPS + 1) / ((ND - 1.0) * SUBSTEPS)
    s_edges = D_MAX_KM * j * j
    rows = len(SUN_ELEVATIONS_DEG) * len(ALTITUDES_M) * NMU
    tex_a, tex_b, tex_c = (np.ones((rows, ND, 4)) for _ in range(3))
    for si, sun in enumerate(SUN_ELEVATIONS_DEG):
        table = sun_optical_depth_table(sun)
        for ai, alt in enumerate(ALTITUDES_M):
            for mi, mu in enumerate(mu_axis()):
                t, i_r, i_m = march(alt / 1000.0, float(mu), s_edges, table)
                t, i_r, i_m = t[::SUBSTEPS], i_r[::SUBSTEPS], i_m[::SUBSTEPS]
                row = (si * len(ALTITUDES_M) + ai) * NMU + mi
                tex_a[row, :, :3] = i_r
                tex_b[row, :, :3] = t
                tex_c[row, :, :3] = i_m
    return {"a": tex_a.astype("<f2"), "b": tex_b.astype("<f2"), "c": tex_c.astype("<f2")}


def reference_table():
    out = []
    for d in (5.0, 10.0, 20.0, 40.0, 80.0):
        ref = reference(NOMINAL["altitude_m"], NOMINAL["sun_elevation_deg"], 0.0, d)
        per_lux = phase_rayleigh(0.0) * ref["rayleigh_inscatter_rgb"] + phase_mie(0.0) * ref["mie_inscatter_rgb"]
        out.append({
            "distance_km": d,
            "transmittance_rgb": [round(float(v), 5) for v in ref["transmittance_rgb"]],
            "rayleigh_inscatter_rgb": [round(float(v), 6) for v in ref["rayleigh_inscatter_rgb"]],
            "mie_inscatter_rgb": [round(float(v), 6) for v in ref["mie_inscatter_rgb"]],
            "inscatter_cd_m2_per_lux_at_90deg_rgb": [round(float(v), 7) for v in per_lux],
        })
    return out


def summary(plan):
    return {
        "lane": "atmosphere_clouds.aerial_perspective.alpine",
        "label": "visual-only",
        "model": "single scattering; ASSUMED constants typed from memory of Hillaire 2020, not fetched, not read from the engine, and not the Mie layer this project applies",
        "constants_per_km": {
            "rayleigh_scattering_rgb": RAYLEIGH_SCATTERING.tolist(),
            "rayleigh_scale_height_km": RAYLEIGH_SCALE_HEIGHT_KM,
            "mie_scattering": MIE_SCATTERING, "mie_absorption": MIE_ABSORPTION,
            "mie_scale_height_km": MIE_SCALE_HEIGHT_KM, "mie_g": MIE_G,
            "ozone_absorption_rgb": OZONE_ABSORPTION.tolist(),
            "ozone_centre_km": OZONE_CENTRE_KM, "ozone_half_width_km": OZONE_HALF_WIDTH_KM,
            "planet_radius_km": PLANET_RADIUS_KM, "atmosphere_height_km": ATMOSPHERE_HEIGHT_KM,
        },
        "layout": {
            "format": "RGBA float16 little-endian, row-major",
            "width": ND, "height": int(plan["a"].shape[0]),
            "row": "(sun * n_altitudes + altitude) * n_mu + mu",
            "altitudes_m": ALTITUDES_M, "sun_elevations_deg": SUN_ELEVATIONS_DEG,
            "n_mu": NMU, "mu": "sin(view elevation), linear in [-0.5, 0.5]",
            "distance_km": "128 * (i / 31)^2",
            "a": "rgb Rayleigh in-scatter integral, a 1",
            "b": "rgb transmittance, a 1",
            "c": "rgb Mie in-scatter integral, a 1",
        },
        "ms_gain": 1.0,
        "ms_gain_status": "UNCALIBRATED",
        "constants_status": "ASSUMED",
        "nominal": NOMINAL,
        "nominal_horizontal_reference": reference_table(),
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(out_dir: Path = HERE):
    plan = build()
    (out_dir / "alpine_ap_a.rgba16f").write_bytes(plan["a"].tobytes())
    (out_dir / "alpine_ap_b.rgba16f").write_bytes(plan["b"].tobytes())
    (out_dir / "alpine_ap_c.rgba16f").write_bytes(plan["c"].tobytes())
    (out_dir / "alpine_ap.json").write_text(json.dumps(summary(plan), indent=1, sort_keys=True) + "\n")
    return {name: sha256(out_dir / name) for name in OUTPUTS}


if __name__ == "__main__":
    print(json.dumps(write(), indent=1))
