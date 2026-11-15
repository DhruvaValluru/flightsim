"""The pure maths of the pre-rendered impostor clouds (2026-11-14), no bpy, no engine.

The owner's choice for the most visually appealing clouds that are instant on the
render machine's Intel iGPU (D3D11 SM5): JangaFX's CC0 Cloud Pack (static cloud
VDBs) rendered ONCE in Blender Cycles at film quality (multiple scattering, strong
forward scattering) into octahedral impostors with six-way lighting, then drawn in
the beauty capture as camera-facing quads that pick and blend the three nearest
baked views and relight them for the scene's sun.

Three users share this module, so they can never disagree:
  * scripts/bake_cloud_impostors.py (inside Blender): the view directions, the
    camera basis per view, the atlas packing, the per-cloud JSON and PIN.json;
  * assets/shaders/world/cloud_impostor.hlsl: the same octahedral map, frame
    basis, blend and six-way weights, written again in HLSL (tests pin the twin);
  * FlightSimImpostorClouds.cpp: the same placement and keep-out (tests pin the
    constants and the Python twin of each).

Frames and conventions (stated once, here):
  * CLOUD OBJECT SPACE is Blender's: right-handed, x east, y north, z up, the
    cloud's bounding-box centre at the origin. UE world is left-handed (x
    forward, y right, z up); an instance turned by Yaw (radians, about z) maps
    world -> object as rotate by -Yaw about z, then y -> -y (WORLD_TO_OBJECT).
  * A VIEW DIRECTION d is the unit vector from the cloud's centre TOWARD the
    camera. Full-sphere octahedral map (clouds are seen from below and above):
    VIEWS x VIEWS frames on the grid's VERTICES, frame (i, j) at
    oct_decode(i / (VIEWS - 1), j / (VIEWS - 1)).
  * A frame's camera looks along -d, up from world z (y near the poles); its
    image is an orthographic square of side 2 x the FRAME SPHERE's radius,
    u to the right, v DOWN (texture convention). The frame sphere is fitted to
    the DENSITY (voxels above FRAME_DENSITY_FRACTION of the cloud's peak, plus
    FRAME_MARGIN), not to the VDB grid: the grid pads the cloud with empty
    voxels and a grid fit left the first bake's clouds in a third of each frame.
    The JSON's bounds are that density's box (its height is what the engine
    scales to the layer), sphere_radius is the frame's half-side, and
    sphere_over_height = 2 x sphere_radius / height sizes the quad.
  * SIX-WAY LIGHTING: six renders per frame, a white sun from each object-space
    axis direction (+x, +y, +z, -x, -y, -z: the direction the light COMES FROM),
    packed as POS.rgb = (+x, +y, +z), NEG.rgb = (-x, -y, -z); POS.a = opacity
    (1 - transmittance), NEG.a = depth offset (0.5 + 0.5 x signed offset of the
    density's front surface from the frame's centre plane, in sphere radii).
    Volume scattering is linear in the light, so a sun toward L lights the
    cloud as sum_i w_i(L) x channel_i with w = max(+/-L, 0) per axis.
  * Light channels are stored straight (un-premultiplied) and gamma-2.2 encoded
    over the cloud's LIGHT_SCALE (its 99.5th percentile), so 8 bits keep the
    shadowed side; the shader decodes pow(c, 2.2) x LightScale.
Every amount here is UNCALIBRATED until a Windows render is judged.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]

#: The pilot bake (tier 0): 8 x 8 octahedral views of 256 px -> 2048 px atlases
#: (two 8-bit RGBA PNGs per cloud, ~16 MB each uncompressed in the GPU; 128 px was
#: too soft once the frame was fitted to the density).
DEFAULT_VIEWS = 8
DEFAULT_PX = 256
ATLAS_MAX_PX = 2048
#: Framing: voxels above this share of the cloud's peak density count as cloud, and
#: the frame's half-side is their enclosing sphere's radius x (1 + FRAME_MARGIN) plus
#: one voxel (so the surface's own softness is not clipped).
FRAME_DENSITY_FRACTION = 0.01
FRAME_MARGIN = 0.04
PILOT_CLOUDS = 4
GAMMA = 2.2
LIGHT_PERCENTILE = 99.5
#: The channel layout every JSON states and the shader reads.
CHANNEL_LAYOUT = {
    "pos": {"r": "+x", "g": "+y", "b": "+z", "a": "opacity"},
    "neg": {"r": "-x", "g": "-y", "b": "-z", "a": "depth_offset"},
    "light_encoding": f"straight, pow(value / light_scale, 1/{GAMMA}); decode pow(c, {GAMMA}) * light_scale",
    "depth_offset_encoding": "0.5 + 0.5 * clamp(offset / sphere_radius, -1, 1); 0.5 where empty",
}
LICENCE = "CC0-1.0 (JangaFX EmberGen free VDB simulations: 'licensed as CC0 (Public Domain)')"

# -- placement and keep-out (FlightSimImpostorClouds.cpp mirrors these) --------------
#: A layer at least this thick (m) is cumulus-like and gets impostors; thinner
#: layers (stratus) stay the volumetric layer's alone.
CUMULUS_MIN_THICKNESS_M = 400.0
#: Below this cover a layer draws none.
MIN_COVER = 0.05
#: Instances at full cover, and the cap per mode.
INSTANCES_AT_FULL_COVER = 40
MAX_INSTANCES = {"pilot": 12, "on": 40}
#: The ring around the aircraft's first position the instances fill (m).
RING_INNER_M = 1500.0
RING_OUTER_M = 15000.0
#: A cloud's height is this share of the layer's thickness (uniform in range).
HEIGHT_SHARE = (0.6, 1.0)
#: The keep-out margin beyond the aircraft's bound (m).
KEEP_OUT_MARGIN_M = 150.0


def _norm(v: Sequence[float]) -> Vec:
    n = math.sqrt(sum(c * c for c in v))
    if n <= 0.0:
        raise ValueError("zero vector")
    return (v[0] / n, v[1] / n, v[2] / n)


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sign(x: float) -> float:
    return 1.0 if x >= 0.0 else -1.0


def oct_encode(d: Sequence[float]) -> Tuple[float, float]:
    """A unit direction -> octahedral (u, v) in [0, 1]^2 (full sphere)."""
    x, y, z = _norm(d)
    s = abs(x) + abs(y) + abs(z)
    px, py = x / s, y / s
    if z < 0.0:
        px, py = (1.0 - abs(py)) * _sign(px), (1.0 - abs(px)) * _sign(py)
    return px * 0.5 + 0.5, py * 0.5 + 0.5


def oct_decode(u: float, v: float) -> Vec:
    """Octahedral (u, v) in [0, 1]^2 -> the unit direction (oct_encode's inverse)."""
    px, py = u * 2.0 - 1.0, v * 2.0 - 1.0
    z = 1.0 - abs(px) - abs(py)
    if z < 0.0:
        px, py = (1.0 - abs(py)) * _sign(px), (1.0 - abs(px)) * _sign(py)
    return _norm((px, py, z))


def frame_dir(i: int, j: int, views: int = DEFAULT_VIEWS) -> Vec:
    """Frame (i, j)'s view direction (centre -> camera), on the grid's vertices."""
    return oct_decode(i / (views - 1), j / (views - 1))


def frame_basis(d: Sequence[float]) -> Tuple[Vec, Vec, Vec]:
    """(right, up, forward) of the camera seeing the cloud from direction d
    (forward = -d; up from z, from y within 0.001 of a pole). Right-handed:
    right = forward x up_ref, up = right x forward."""
    d = _norm(d)
    forward = (-d[0], -d[1], -d[2])
    up_ref = (0.0, 1.0, 0.0) if abs(d[2]) > 0.999 else (0.0, 0.0, 1.0)
    right = _norm(_cross(forward, up_ref))
    up = _cross(right, forward)
    return right, up, forward


def blend_frames(d: Sequence[float], views: int = DEFAULT_VIEWS) -> List[Tuple[Tuple[int, int], float]]:
    """The three frames whose triangle on the octahedral grid holds d, with
    barycentric weights summing to 1."""
    u, v = oct_encode(d)
    fx, fy = u * (views - 1), v * (views - 1)
    bx = min(int(math.floor(fx)), views - 2)
    by = min(int(math.floor(fy)), views - 2)
    rx, ry = fx - bx, fy - by
    if rx + ry < 1.0:
        out = [((bx, by), 1.0 - rx - ry), ((bx + 1, by), rx), ((bx, by + 1), ry)]
    else:
        out = [((bx + 1, by + 1), rx + ry - 1.0), ((bx + 1, by), 1.0 - ry), ((bx, by + 1), 1.0 - rx)]
    return out


def frame_uv(point_obj: Sequence[float], d: Sequence[float], sphere_radius: float) -> Tuple[float, float]:
    """Where an object-space point lands in frame d's image (u right, v down)."""
    right, up, _ = frame_basis(d)
    side = 2.0 * sphere_radius
    return 0.5 + _dot(point_obj, right) / side, 0.5 - _dot(point_obj, up) / side


def six_way_weights(to_sun: Sequence[float]) -> Tuple[float, ...]:
    """(+x, +y, +z, -x, -y, -z) weights of a sun toward to_sun (object space)."""
    lx, ly, lz = _norm(to_sun)
    return (max(lx, 0.0), max(ly, 0.0), max(lz, 0.0), max(-lx, 0.0), max(-ly, 0.0), max(-lz, 0.0))


def world_to_object(v: Sequence[float], yaw_rad: float) -> Vec:
    """A UE world vector -> cloud object space (rotate by -yaw about z, then y -> -y)."""
    c, s = math.cos(-yaw_rad), math.sin(-yaw_rad)
    x, y = c * v[0] - s * v[1], s * v[0] + c * v[1]
    return (x, -y, v[2])


def object_to_world(v: Sequence[float], yaw_rad: float) -> Vec:
    """world_to_object's inverse."""
    x, y, z = v[0], -v[1], v[2]
    c, s = math.cos(yaw_rad), math.sin(yaw_rad)
    return (c * x - s * y, s * x + c * y, z)


def keep_out(centre: Sequence[float], radius: float, camera: Sequence[float],
             aircraft: Sequence[float], aircraft_radius: float,
             margin: float = KEEP_OUT_MARGIN_M) -> bool:
    """True when the instance (a sphere) comes within aircraft_radius + margin of
    the segment camera -> aircraft: it could cover the labelled aircraft, so it
    is hidden for this frame. Units are the caller's (m here, cm in the C++)."""
    seg = tuple(aircraft[i] - camera[i] for i in range(3))
    rel = tuple(centre[i] - camera[i] for i in range(3))
    length2 = _dot(seg, seg)
    t = 0.0 if length2 <= 0.0 else max(0.0, min(1.0, _dot(rel, seg) / length2))
    nearest = tuple(camera[i] + t * seg[i] for i in range(3))
    gap = math.sqrt(sum((centre[i] - nearest[i]) ** 2 for i in range(3)))
    return gap < radius + aircraft_radius + margin


class _Lcg:
    """A small deterministic stream (the C++ uses FRandomStream; the twin pins
    only the counts, ranges and keep-out, not the exact draws)."""

    def __init__(self, seed: int) -> None:
        self.state = (seed & 0x7FFFFFFF) or 1

    def uniform(self, lo: float, hi: float) -> float:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return lo + (hi - lo) * (self.state / 0x7FFFFFFF)


def instance_count(cover: float, thickness_m: float, mode: str) -> int:
    """How many impostors a layer gets (0 for a thin or near-clear layer)."""
    if mode not in MAX_INSTANCES or thickness_m < CUMULUS_MIN_THICKNESS_M or cover < MIN_COVER:
        return 0
    return max(0, min(MAX_INSTANCES[mode], int(round(cover * INSTANCES_AT_FULL_COVER))))


def placement(seed: int, layers: Iterable[Dict[str, float]], aircraft_xy: Tuple[float, float],
              mode: str, clouds: int) -> List[Dict[str, float]]:
    """Every instance: cloud index, centre (x, y, z m about the ground datum),
    height m and yaw. Layers are {cover, base_m, top_m}; the total across layers
    is capped at MAX_INSTANCES[mode]."""
    if clouds <= 0:
        return []
    rng = _Lcg(seed)
    out: List[Dict[str, float]] = []
    for layer in layers:
        thickness = float(layer["top_m"]) - float(layer["base_m"])
        for _ in range(instance_count(float(layer["cover"]), thickness, mode)):
            if len(out) >= MAX_INSTANCES.get(mode, 0):
                return out
            a = rng.uniform(0.0, 2.0 * math.pi)
            r = math.sqrt(rng.uniform(RING_INNER_M ** 2, RING_OUTER_M ** 2))   # uniform over the ring's area
            h = thickness * rng.uniform(*HEIGHT_SHARE)
            out.append({"cloud": int(rng.uniform(0.0, clouds - 1e-6)),
                        "x": aircraft_xy[0] + r * math.cos(a), "y": aircraft_xy[1] + r * math.sin(a),
                        "z": float(layer["base_m"]) + 0.5 * h, "height_m": h,
                        "yaw": rng.uniform(0.0, 2.0 * math.pi)})
    return out


# -- the bake's numbers ---------------------------------------------------------------

def atlas_px(views: int, px: int) -> int:
    size = views * px
    if size > ATLAS_MAX_PX:
        raise ValueError(f"{views} views x {px} px = {size} px exceeds the {ATLAS_MAX_PX} px atlas budget")
    return size


def density_threshold(peak_density: float, fraction: float = FRAME_DENSITY_FRACTION,
                      floor: float = 1e-6) -> float:
    """The framing threshold: a share of the peak, never below floor."""
    return max(floor, fraction * float(peak_density))


def bisect_peak(nonempty, start: float = 1.0, steps: int = 10, cap: float = 4096.0) -> float:
    """The peak of a field known only through nonempty(threshold) -> bool ("some value
    exceeds threshold"; in the bake, "the Volume to Mesh iso-surface has vertices").
    Doubles from start until empty (or cap), then bisects: the result is a lower bound of
    the peak within (hi - lo) / 2 ** steps, 0.0 when nothing exceeds 0."""
    lo, hi = 0.0, float(start)
    while nonempty(hi):
        lo, hi = hi, hi * 2.0
        if hi > cap:
            return lo
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        if nonempty(mid):
            lo = mid
        else:
            hi = mid
    return lo


def dense_points(samples: Iterable[Sequence[float]], threshold: float) -> List[Vec]:
    """(x, y, z, density) samples -> the positions whose density exceeds threshold."""
    return [(float(s[0]), float(s[1]), float(s[2])) for s in samples if s[3] > threshold]


def tight_fit(points: Sequence[Sequence[float]], margin: float = FRAME_MARGIN,
              extra: float = 0.0) -> Optional[Dict[str, object]]:
    """The frame fitted to the cloud's points (voxel centres above the threshold, or
    the iso-surface's vertices): their box (min, max, size, centre) and the frame
    sphere about the box's centre, radius = the farthest point x (1 + margin) + extra.
    None when there are no points."""
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for p in points:
        for i in range(3):
            v = float(p[i])
            if v < lo[i]:
                lo[i] = v
            if v > hi[i]:
                hi[i] = v
    if lo[0] == math.inf:
        return None
    centre = [0.5 * (lo[i] + hi[i]) for i in range(3)]
    far2 = 0.0
    for p in points:
        d2 = sum((float(p[i]) - centre[i]) ** 2 for i in range(3))
        if d2 > far2:
            far2 = d2
    radius = math.sqrt(far2) * (1.0 + margin) + extra
    return {"min": lo, "max": hi, "size": [hi[i] - lo[i] for i in range(3)], "centre": centre,
            "radius": radius}


def frame_fill(size: Sequence[float], sphere_radius: float) -> float:
    """The share of a frame's side the cloud's longest extent spans (1 = edge to edge)."""
    return max(float(v) for v in size) / (2.0 * sphere_radius) if sphere_radius > 0 else 0.0


def frame_origin(i: int, j: int, px: int) -> Tuple[int, int]:
    """The atlas pixel (column, row from the top) of frame (i, j)'s top-left: column i,
    row j (the shader's frame -> atlas map: (i + u, j + v) / views)."""
    return i * px, j * px


def straighten(rgb: Sequence[float], alpha: float, eps: float = 1e-4) -> Vec:
    """Premultiplied (Cycles' film-transparent output) -> straight."""
    if alpha <= eps:
        return (0.0, 0.0, 0.0)
    return (rgb[0] / alpha, rgb[1] / alpha, rgb[2] / alpha)


def encode_light(value: float, light_scale: float) -> float:
    if light_scale <= 0.0:
        return 0.0
    return max(0.0, min(1.0, value / light_scale)) ** (1.0 / GAMMA)


def decode_light(code: float, light_scale: float) -> float:
    return (max(0.0, min(1.0, code)) ** GAMMA) * light_scale


def encode_depth_offset(offset: Optional[float], sphere_radius: float) -> float:
    if offset is None or sphere_radius <= 0.0:
        return 0.5
    return 0.5 + 0.5 * max(-1.0, min(1.0, offset / sphere_radius))


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (nearest rank) of the non-zero values (0 when none)."""
    vs = sorted(v for v in values if v > 0.0)
    if not vs:
        return 0.0
    k = max(0, min(len(vs) - 1, int(math.ceil(q / 100.0 * len(vs))) - 1))
    return vs[k]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cloud_record(cloud_id: str, source_vdb: str, source_sha256: str, bounds_min: Sequence[float],
                 bounds_max: Sequence[float], views: int, px: int, light_scale: float,
                 atlases: Dict[str, str], render: Dict[str, object],
                 sphere_radius: Optional[float] = None,
                 framing: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """One cloud's JSON (assets/looks/clouds/impostors/<id>.json). The bounds are the
    density's box; sphere_radius is the frame's half-side (tight_fit's radius; the box's
    half-diagonal when None); framing says how the fit was found."""
    size = [float(bounds_max[i]) - float(bounds_min[i]) for i in range(3)]
    radius = float(sphere_radius) if sphere_radius is not None else 0.5 * math.sqrt(sum(s * s for s in size))
    return {
        "magic": "flightsim-cloud-impostor", "version": 1, "id": cloud_id,
        "source_vdb": source_vdb, "source_sha256": source_sha256, "licence": LICENCE,
        "bounds_vdb_units": {"min": [float(v) for v in bounds_min], "max": [float(v) for v in bounds_max],
                             "size": size},
        "sphere_radius_vdb_units": radius,
        "sphere_over_height": (2.0 * radius / size[2]) if size[2] > 0 else None,
        "scale_basis": ("VDB units are EmberGen's; bounds are the density's box (above the framing "
                        "threshold), sphere_radius the frame's half-side; the engine scales each "
                        "instance so the cloud's height is its layer's share (sphere_over_height "
                        "sizes the quad)"),
        "framing": framing if framing is not None else {"method": "box half-diagonal"},
        "views": views, "px": px, "atlas_px": atlas_px(views, px), "octahedral": "full sphere, grid vertices",
        "light_scale": light_scale, "channels": CHANNEL_LAYOUT, "atlases": atlases, "render": render,
        "calibration": "UNCALIBRATED until a Windows render is judged",
    }


def write_json(path: Path, doc: Dict[str, object]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def pin_json(folder: Path, files: Iterable[str]) -> Dict[str, object]:
    """PIN.json over every atlas (paths relative to the repo's assets/ parent)."""
    folder = Path(folder)
    rows = {}
    for name in sorted(files):
        rows[name] = {"path": f"assets/looks/clouds/impostors/{name}", "sha256": sha256_file(folder / name)}
    return {"magic": "flightsim-pin", "licence": LICENCE, "files": rows}
