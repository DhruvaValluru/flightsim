"""Bake the storm windscreen's water for an integrated GPU (swarm lane
weather_fx.windscreen_water.storm).

The laptop cannot afford M_WindshieldRain's per-pixel loop of hashed drops, and a
drop that only offsets a fog-grey scene is invisible. So the Mac bakes the optics
once and the render path only samples them:

  T_WSDrops_<n>.png     sessile drops pinned on the glass (tileable)
      R,G  where to look instead: the screen-space shift of a ray leaving the
           drop's curved face, as tan(deflection) / TAN_MAX, 0.5 = none
      B    shade: unpolarised Fresnel transmittance water -> air on that face,
           RIM_FLOOR in the ring of total internal reflection; 1 off the drop
      A    appearance threshold: the drop shows when A > 1 - Density; 0 off it
  T_WSRivulets_<n>.png  run-off tracks up the glass (tileable both ways)
      R    the sideways shift across the track (same optics, a cylinder cap)
      G    shade, as B above
      B    the track's head offset (constant per track, filled to the nearest
           track so filtering never mixes a wrapped phase)
      A    appearance threshold, 0 off the track

Sizes come from the Marshall-Palmer distribution the project's drops use, each
drop a spherical cap of the same volume at a STATED contact angle. Nothing here
is a rendered frame: visual-only, UNMEASURED until the Windows pixel gate runs.

Run:  python generate.py            (writes baked/, deterministic)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

LANE = Path(__file__).resolve().parent
OUT = LANE / "baked"

# --- optics (published constants) -------------------------------------------
N_WATER = 1.333
ALPHA_TIR = math.asin(1.0 / N_WATER)                 # 48.6 deg
TAN_MAX = math.tan(math.pi / 2.0 - ALPHA_TIR)        # deflection at the TIR edge, 0.8815

# --- stated, not measured (visual-only) -------------------------------------
CONTACT_ANGLE_DEG = 70.0     # water on aged acrylic / coated glass
RIM_FLOOR = 0.15             # what the TIR ring shows: the dim cabin, as a share of the scene
GLASS_DISTANCE_M = 0.35      # eye to glass along the view axis
VFOV_DEG = 60.0              # the cockpit camera's vertical field of view (host overrides Lens)
TILES = 3.0                  # texture tiles per screen height
MAX_DROP_COVER = 0.30        # the most of the glass standing drops hold
EDGE_GAIN = 16.0             # threshold sharpness in the shader
A_SPAN = 0.75                # thresholds run 1 .. 1 - A_SPAN; Density = A_SPAN shows all
RIVULETS = 14                # tracks per tile
RIV_HALF_MM = (1.0, 2.2)     # a track's half width

# --- the scenario and the project's own laws (copied; the test cross-checks) --
RATE_MMH = 25.0              # scripts/debug_storm_render.py DEFAULT_PROMPT
D_MIN_MM, D_MAX_MM = 1.0, 6.0        # core/scene/rain_field.py
V_SHED_MPS, RUNOFF_GAIN = 22.0, 0.35  # core/scene/rain_field.py (stated there too)
WINDSHIELD_COS = 0.5

SEED = 0x57A7E5
MASTER = 2048
SIZES = (256, 512, 1024, 2048)       # tier 0..3

#: one tile's side on the glass, mm
TILE_MM = 2.0 * math.tan(math.radians(VFOV_DEG) / 2.0) * GLASS_DISTANCE_M * 1000.0 / TILES


def marshall_palmer_lambda(rate_mmh: float) -> float:
    """Marshall & Palmer 1948: Lambda = 4.1 R^-0.21 per mm."""
    return 4.1 * float(rate_mmh) ** -0.21


def splitmix64(x: int) -> int:
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return z ^ (z >> 31)


class Rng:
    """A counter stream on splitmix64: the same bytes on every numpy."""

    def __init__(self, seed: int):
        self.state = seed & 0xFFFFFFFFFFFFFFFF

    def u(self) -> float:
        self.state = (self.state + 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
        return (splitmix64(self.state) >> 11) / float(1 << 53)


def sample_diameter_mm(u: float, lam: float) -> float:
    """Inverse CDF of exp(-lam D) truncated to [D_MIN, D_MAX]."""
    a, b = math.exp(-lam * D_MIN_MM), math.exp(-lam * D_MAX_MM)
    return -math.log(a - u * (a - b)) / lam


def cap_base_radius_mm(diameter_mm: float, theta_deg: float = CONTACT_ANGLE_DEG) -> float:
    """Base radius of the spherical cap holding a sphere of ``diameter_mm``'s
    volume at contact angle theta: V = pi a^3 (2 - 3c + c^3) / (3 s^3)."""
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    volume = math.pi * diameter_mm ** 3 / 6.0
    return (3.0 * volume * s ** 3 / (math.pi * (2.0 - 3.0 * c + c ** 3))) ** (1.0 / 3.0)


def cap_volume_mm3(base_radius_mm: float, theta_deg: float = CONTACT_ANGLE_DEG) -> float:
    t = math.radians(theta_deg)
    c, s = math.cos(t), math.sin(t)
    return math.pi * base_radius_mm ** 3 * (2.0 - 3.0 * c + c ** 3) / (3.0 * s ** 3)


def face_optics(sin_alpha):
    """A ray along the glass normal meets the water's curved face at incidence
    alpha. Returns (tan of its deflection, transmittance); past total internal
    reflection: (TAN_MAX, 0)."""
    sa = np.clip(np.asarray(sin_alpha, dtype=np.float64), 0.0, 1.0)
    sb = N_WATER * sa
    tir = sb >= 1.0
    sb = np.where(tir, 1.0, sb)
    ca, cb = np.sqrt(1.0 - sa * sa), np.sqrt(1.0 - sb * sb)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = (N_WATER * ca - cb) / (N_WATER * ca + cb)
        rp = (ca - N_WATER * cb) / (ca + N_WATER * cb)
        trans = 1.0 - 0.5 * (rs * rs + rp * rp)
        tan_d = np.tan(np.arcsin(sb) - np.arcsin(sa))
    trans = np.where(tir, 0.0, trans)
    tan_d = np.where(tir, TAN_MAX, np.minimum(tan_d, TAN_MAX))
    return tan_d, trans


def place_drops(rng: Rng, lam: float):
    """Dart-throw non-overlapping caps on the torus until MAX_DROP_COVER."""
    xs, ys, rs = [], [], []
    area, target = 0.0, MAX_DROP_COVER * TILE_MM * TILE_MM
    for _ in range(60000):
        if area >= target:
            break
        a = cap_base_radius_mm(sample_diameter_mm(rng.u(), lam))
        x, y = rng.u() * TILE_MM, rng.u() * TILE_MM
        if xs:
            dx = np.abs(np.asarray(xs) - x)
            dy = np.abs(np.asarray(ys) - y)
            dx = np.minimum(dx, TILE_MM - dx)
            dy = np.minimum(dy, TILE_MM - dy)
            if np.any(dx * dx + dy * dy < (np.asarray(rs) + a + 0.15) ** 2):
                continue
        xs.append(x), ys.append(y), rs.append(a)
        area += math.pi * a * a
    return np.asarray(xs), np.asarray(ys), np.asarray(rs)


def bake_drops(xs, ys, rs, n: int = MASTER) -> np.ndarray:
    """float RGBA in 0..1 at n x n."""
    img = np.zeros((n, n, 4))
    img[..., 0:2] = 0.5
    img[..., 2] = 1.0
    px = n / TILE_MM
    sin_theta = math.sin(math.radians(CONTACT_ANGLE_DEG))
    count = len(xs)
    for i in range(count):
        cx, cy, a = xs[i] * px, ys[i] * px, rs[i] * px
        r = int(math.ceil(a)) + 1
        ix, iy = int(math.floor(cx)), int(math.floor(cy))
        gx = np.arange(ix - r, ix + r + 1)
        gy = np.arange(iy - r, iy + r + 1)
        dx = (gx + 0.5 - cx)[None, :] / a
        dy = (gy + 0.5 - cy)[:, None] / a
        rr = np.sqrt(dx * dx + dy * dy)
        inside = rr < 1.0
        tan_d, trans = face_optics(rr * sin_theta)      # sin(alpha) = r / R = (r/a) sin(theta)
        with np.errstate(divide="ignore", invalid="ignore"):
            ux = np.where(rr > 0, dx / rr, 0.0)
            uy = np.where(rr > 0, dy / rr, 0.0)
        k = -tan_d / TAN_MAX                            # a converging lens: toward the axis
        patch = np.stack([0.5 + 0.5 * k * ux, 0.5 + 0.5 * k * uy,
                          np.maximum(trans, RIM_FLOOR),
                          np.full_like(rr, 1.0 - A_SPAN * (i + 0.5) / count)], axis=-1)
        yy, xx = np.ix_(gy % n, gx % n)
        img[yy, xx] = np.where(inside[..., None], patch, img[yy, xx])
    return img


def rivulet_tracks(rng: Rng):
    """Per track: slot centre (tile units), meander terms, half width, bead
    term, head offset. Integer frequencies keep the tile periodic in v."""
    tracks = []
    slot = 1.0 / RIVULETS
    order = list(range(RIVULETS))
    for i in range(RIVULETS - 1, 0, -1):               # Fisher-Yates: the order they appear in
        j = int(rng.u() * (i + 1))
        order[i], order[j] = order[j], order[i]
    for i in range(RIVULETS):
        half = (RIV_HALF_MM[0] + (RIV_HALF_MM[1] - RIV_HALF_MM[0]) * rng.u()) / TILE_MM
        room = max(slot * 0.5 - half * 1.3, 0.0)
        terms = [(room * w * (0.4 + 0.6 * rng.u()), f, 2.0 * math.pi * rng.u())
                 for w, f in ((0.55, 1 + int(rng.u() * 2)), (0.30, 3 + int(rng.u() * 3)),
                              (0.15, 6 + int(rng.u() * 5)))]
        tracks.append({"x0": (i + 0.5) * slot, "terms": terms, "half": half,
                       "bead": (0.25, 3 + int(rng.u() * 7), 2.0 * math.pi * rng.u()),
                       "offset": rng.u(), "rank": order[i]})
    return tracks


def bake_rivulets(tracks, n: int = MASTER) -> np.ndarray:
    img = np.zeros((n, n, 4))
    img[..., 0] = 0.5
    img[..., 1] = 1.0
    u = ((np.arange(n) + 0.5) / n)[None, :]
    v = ((np.arange(n) + 0.5) / n)[:, None]
    sin_theta = math.sin(math.radians(CONTACT_ANGLE_DEG))
    nearest = np.full((n, n), np.inf)
    for t in tracks:
        centre = t["x0"] + sum(a * np.sin(2.0 * math.pi * f * v + p) for a, f, p in t["terms"])
        amp, f, p = t["bead"]
        half = t["half"] * (1.0 + amp * np.sin(2.0 * math.pi * f * v + p))
        d = (u - centre + 0.5) % 1.0 - 0.5              # signed, wrapped in u
        q = d / half
        inside = np.abs(q) < 1.0
        tan_d, trans = face_optics(np.abs(q) * sin_theta)
        img[..., 0] = np.where(inside, 0.5 - 0.5 * np.sign(q) * tan_d / TAN_MAX, img[..., 0])
        img[..., 1] = np.where(inside, np.maximum(trans, RIM_FLOOR), img[..., 1])
        img[..., 3] = np.where(inside, 1.0 - A_SPAN * (t["rank"] + 0.5) / len(tracks), img[..., 3])
        closer = np.abs(d) < nearest
        img[..., 2] = np.where(closer, t["offset"], img[..., 2])
        nearest = np.where(closer, np.abs(d), nearest)
    return img


def downsample(img: np.ndarray, n: int) -> np.ndarray:
    f = img.shape[0] // n
    return img.reshape(n, f, n, f, img.shape[2]).mean(axis=(1, 3))


def to_u8(img: np.ndarray) -> np.ndarray:
    return np.clip(np.rint(img * 255.0), 0, 255).astype(np.uint8)


# --- the shader's twin (windshield_baked.hlsl), for the tests and the tables --
def lens_scale(vfov_deg: float = VFOV_DEG) -> float:
    """Screen heights per unit of encoded shift, for a scene at infinity."""
    return TAN_MAX / (2.0 * math.tan(math.radians(vfov_deg) / 2.0))


def shade_texels(drop, riv, riv_v, time_s, wet, lens, aspect):
    """drop, riv: float RGBA 0..1 (..., 4). wet = (drop density, rivulet density,
    head rate in tiles/s, trail length in tiles). Returns (du, dv, mask, shade)."""
    drop_on = np.clip((drop[..., 3] - (1.0 - wet[0])) * EDGE_GAIN, 0.0, 1.0)
    riv_on = np.clip((riv[..., 3] - (1.0 - wet[1])) * EDGE_GAIN, 0.0, 1.0)
    s = np.mod(riv_v + riv[..., 2] + time_s * wet[2], 1.0)
    riv_on = riv_on * np.clip(1.0 - s / max(wet[3], 1.0e-3), 0.0, 1.0)
    d_drop_x = (drop[..., 0] * 2.0 - 1.0) * lens
    d_drop_y = (drop[..., 1] * 2.0 - 1.0) * lens
    d_riv_x = (riv[..., 0] * 2.0 - 1.0) * lens * riv_on
    du = d_riv_x + (d_drop_x - d_riv_x) * drop_on
    dv = d_drop_y * drop_on
    shade = 1.0 + (riv[..., 1] - 1.0) * riv_on
    shade = shade + (drop[..., 2] - shade) * drop_on
    return du / aspect, dv, np.maximum(drop_on, riv_on), shade


def host_wet(airspeed_mps: float, impinge_per_m2_s: float, lifetime_s: float,
             mean_cap_area_m2: float, drop_table, shutter_s: float = 1.0e-3):
    """What the host puts in ``Wet`` (visual-only mapping onto the project's
    stated run-off law). Standing drops: a Poisson cover 1 - exp(-n A tau),
    capped, thinned above the shedding speed as V_SHED / V; the share shed feeds
    the tracks."""
    v = max(float(airspeed_mps), 0.0)
    hold = 1.0 if v <= V_SHED_MPS else V_SHED_MPS / v
    cover = min(MAX_DROP_COVER, 1.0 - math.exp(-impinge_per_m2_s * mean_cap_area_m2 * lifetime_s))
    cover *= hold
    dens = float(np.interp(cover, [c for _, c in drop_table], [d for d, _ in drop_table]))
    wetted = 1.0 - math.exp(-impinge_per_m2_s * mean_cap_area_m2 * lifetime_s)
    riv = A_SPAN * (1.0 - hold) * min(1.0, wetted / MAX_DROP_COVER)
    runoff = RUNOFF_GAIN * (v - V_SHED_MPS) if v > V_SHED_MPS else 0.0
    tile_m = TILE_MM / 1000.0
    return {"drop_density": round(dens, 4), "rivulet_density": round(riv, 4),
            "head_rate_tiles_per_s": round(runoff / tile_m, 3),
            "trail_tiles": round(min(1.0, max(0.25, runoff * shutter_s / tile_m)), 4),
            "runoff_mps": round(runoff, 4), "standing_cover": round(cover, 4)}


def coverage_table(drop256: np.ndarray):
    out = []
    for dens in np.linspace(0.0, A_SPAN, 16):
        on = np.clip((drop256[..., 3] - (1.0 - dens)) * EDGE_GAIN, 0.0, 1.0)
        out.append((round(float(dens), 4), round(float(on.mean()), 5)))
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    lam = marshall_palmer_lambda(RATE_MMH)
    rng = Rng(SEED)
    xs, ys, rs = place_drops(rng, lam)
    drops = bake_drops(xs, ys, rs)
    tracks = rivulet_tracks(rng)
    rivs = bake_rivulets(tracks)
    files = {}
    small = None
    for n in SIZES:
        d = to_u8(drops if n == MASTER else downsample(drops, n))
        r = to_u8(rivs if n == MASTER else downsample(rivs, n))
        if n == SIZES[0]:
            small = d.astype(np.float64) / 255.0
        for name, arr in ((f"T_WSDrops_{n}.png", d), (f"T_WSRivulets_{n}.png", r)):
            Image.fromarray(arr).save(args.out / name, optimize=False, compress_level=9)
            files[name] = sha256(args.out / name)
    table = coverage_table(small)
    mean_area_m2 = float(np.mean(math.pi * rs * rs)) * 1.0e-6
    # Example only: Marshall-Palmer N0 = 8000 /m^3/mm above D_MIN, 100 kt, a 5 s hold.
    # The host uses the card's own impingement (rain_field.windshield) and lifetime.
    n_per_m3 = 8000.0 / lam * math.exp(-lam * D_MIN_MM)
    impinge = n_per_m3 * 51.44 * WINDSHIELD_COS
    doc = {
        "item": "weather_fx.windscreen_water.storm",
        "status": "UNMEASURED: baked on the Mac, no frame rendered",
        "visual_only": True,
        "optics": {"n_water": N_WATER, "tir_incidence_deg": round(math.degrees(ALPHA_TIR), 4),
                   "tan_max": round(TAN_MAX, 6), "contact_angle_deg": CONTACT_ANGLE_DEG,
                   "rim_floor": RIM_FLOOR,
                   "tir_ring_from_radius_fraction": round(
                       1.0 / (N_WATER * math.sin(math.radians(CONTACT_ANGLE_DEG))), 4)},
        "geometry": {"glass_distance_m": GLASS_DISTANCE_M, "vfov_deg": VFOV_DEG, "tiles": TILES,
                     "tile_mm": round(TILE_MM, 3), "lens_scale": round(lens_scale(), 6)},
        "rain": {"rate_mmh": RATE_MMH, "lambda_per_mm": round(lam, 5),
                 "d_min_mm": D_MIN_MM, "d_max_mm": D_MAX_MM},
        "drops": {"count": int(len(rs)), "mean_base_radius_mm": round(float(rs.mean()), 4),
                  "max_base_radius_mm": round(float(rs.max()), 4),
                  "mean_cap_area_m2": mean_area_m2, "max_cover": MAX_DROP_COVER,
                  "density_to_cover": table},
        "rivulets": {"count": RIVULETS, "half_width_mm": list(RIV_HALF_MM)},
        "shader": {"edge_gain": EDGE_GAIN, "a_span": A_SPAN},
        "law": {"v_shed_mps": V_SHED_MPS, "runoff_gain": RUNOFF_GAIN,
                "windshield_cos": WINDSHIELD_COS},
        "example_impinge_per_m2_s_at_100kt": round(impinge, 1),
        "example_wet_at_100kt": host_wet(51.44, impinge, 5.0, mean_area_m2, table),
        "example_wet_at_15mps_taxi": host_wet(15.0, impinge * 15.0 / 51.44, 5.0, mean_area_m2, table),
        "stated_not_measured": ["contact_angle_deg", "rim_floor", "glass_distance_m", "vfov_deg",
                                "tiles", "max_cover", "rivulet count and widths",
                                "host_wet's split between standing drops and tracks",
                                "v_shed_mps and runoff_gain (the project's, stated there)"],
        "files": files,
    }
    path = args.out / "windscreen_water_storm.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(rs)} drops, {RIVULETS} tracks, tile {TILE_MM:.1f} mm -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
