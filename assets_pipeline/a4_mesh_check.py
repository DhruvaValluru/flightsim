"""Measure the A-4E .mdl and compare it with the generated flight model.

The exterior .mdl is a P3D "PV44" RIFF file. What is decoded here, verified
by measurement rather than a published spec:

* ``VERB`` holds vertex buffers (``VERT`` chunks). The static buffers use a
  32-byte vertex whose first three floats are x (right), y (up), z (forward)
  in metres, in the model datum frame (the frame aircraft.cfg positions use).
* ``LODT/LODE/PART`` (36 bytes each) lists the draw parts: word 3 is the
  vertex buffer, 4 the first vertex, 5 the vertex count, 8 the animation
  node (0xFFFFFFFF = static).

Only static parts are measured. Three origin-symmetric helper volumes (a
+-1.61 x 1.61 x 7.24 m box, ``symmetric`` below) are not airframe and are
skipped. Animated parts (gear, surfaces) live in node-local space and are not
compared: their placement is what aircraft.cfg supplies.

The measured extents are compared with the FDM structural contacts that
``a4_sync`` generated from the cfg, closing the loop
cfg -> FDM <- mesh.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
MDL = (REPO / "assets/aircraft_models/A4/SimObjects/Airplanes/A-4E/model/"
       "A4E.mdl")
FT = 0.3048
STATIC = 0xFFFFFFFF


def _chunks(d: bytes, off: int, end: int):
    while off + 8 <= end:
        cid = d[off:off + 4]
        size = struct.unpack("<I", d[off + 4:off + 8])[0]
        yield cid, off + 8, size
        off += 8 + size


def _part_vertices(path: Path, index: int) -> np.ndarray:
    """All vertices (metres) of one draw part of the first LOD."""
    d = Path(path).read_bytes()
    sections = {}
    for cid, o, s in _chunks(d, 12, len(d)):
        if cid == b"MDLD":
            for c2, o2, s2 in _chunks(d, o, o + s):
                sections.setdefault(c2, []).append((o2, s2))
    o, s = sections[b"VERB"][0]
    buffers = [d[o3:o3 + s3] for c, o3, s3 in _chunks(d, o, o + s)
               if c == b"VERT"]
    o, s = sections[b"LODT"][0]
    for c2, o2, s2 in _chunks(d, o, o + s):
        parts = [struct.unpack("<9I", d[o3:o3 + 36])
                 for c3, o3, _ in _chunks(d, o2 + 4, o2 + s2) if c3 == b"PART"]
        break
    p = parts[index]
    return np.frombuffer(buffers[p[3]], dtype="<f4").reshape(-1, 8)[
        p[4]:p[4] + p[5], :3]


def _hull(points: np.ndarray) -> np.ndarray:
    pts = sorted(map(tuple, points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def chain(seq):
        out = []
        for q in seq:
            while len(out) >= 2 and cross(out[-2], out[-1], q) <= 0:
                out.pop()
            out.append(q)
        return out[:-1]

    return np.array(chain(pts) + chain(reversed(pts)))


def wing_planform(path: Path, wing_index: int) -> dict:
    """Planform area, MAC and quarter-MAC position from the wing part's hull.

    The hull of the top-view projection of the (mirrored) wing surface. It
    includes the root fairing, so area reads slightly high.
    """
    v = _part_vertices(path, wing_index)
    hull = _hull(np.unique(np.round(np.c_[np.abs(v[:, 0]), v[:, 2]], 3), axis=0))
    stations = np.linspace(0.0, float(np.abs(v[:, 0]).max()) - 0.05, 80)
    chord, lead = [], []
    for y in stations:
        zs = []
        for i in range(len(hull)):
            a, b = hull[i], hull[(i + 1) % len(hull)]
            if a[0] != b[0] and (a[0] - y) * (b[0] - y) <= 0:
                zs.append(a[1] + (y - a[0]) / (b[0] - a[0]) * (b[1] - a[1]))
        chord.append(max(zs) - min(zs) if len(zs) >= 2 else 0.0)
        lead.append(max(zs) if zs else 0.0)
    chord, lead = np.array(chord), np.array(lead)
    area = 2 * np.trapezoid(chord, stations)
    mac = 2 * np.trapezoid(chord ** 2, stations) / area
    le_at_mac = 2 * np.trapezoid(lead * chord, stations) / area
    return {"area_ft2": float(area / FT ** 2), "mac_ft": float(mac / FT),
            "quarter_mac_long_ft": float((le_at_mac - 0.25 * mac) / FT)}


def static_parts(path: Path = MDL, min_vertices: int = 500) -> list:
    """(index, vertex_count, lo_xyz_m, hi_xyz_m) for each measured part."""
    d = Path(path).read_bytes()
    if d[:4] != b"RIFF" or d[8:12] != b"PV44":
        raise ValueError(f"{path} is not a PV44 model")
    sections = {}
    for cid, o, s in _chunks(d, 12, len(d)):
        if cid == b"MDLD":
            for c2, o2, s2 in _chunks(d, o, o + s):
                sections.setdefault(c2, []).append((o2, s2))
    o, s = sections[b"VERB"][0]
    buffers = [d[o3:o3 + s3] for c, o3, s3 in _chunks(d, o, o + s)
               if c == b"VERT"]
    o, s = sections[b"LODT"][0]
    parts = []
    for c2, o2, s2 in _chunks(d, o, o + s):
        for c3, o3, _ in _chunks(d, o2 + 4, o2 + s2):
            if c3 == b"PART":
                parts.append(struct.unpack("<9I", d[o3:o3 + 36]))
        break  # first (highest-detail) LOD only

    out = []
    for i, p in enumerate(parts):
        buf_idx, first, count, anim = p[3], p[4], p[5], p[8]
        buf = buffers[buf_idx]
        if anim != STATIC or count < min_vertices or len(buf) % 32:
            continue
        v = np.frombuffer(buf, dtype="<f4").reshape(-1, 8)[first:first + count, :3]
        if not np.isfinite(v).all() or np.abs(v).max() > 8.0:
            continue
        lo, hi = v.min(0), v.max(0)
        if np.allclose(lo, -hi, atol=1e-3):  # symmetric helper volume
            continue
        out.append((i, count, lo, hi))
    return out


def measure(path: Path = MDL) -> dict:
    """Airframe extents in feet, in the cfg frame (+long fwd, +lat, +vert up)."""
    parts = static_parts(path)
    fuselage = max(parts, key=lambda p: p[1])
    wings = [p for p in parts if (p[3][0] - p[2][0]) >= 8.0]
    tail_end_m = min(p[2][2] for p in wings)  # trailing edge of the tail
    gear = [p for p in parts if p[2][1] < -2.0]
    wing = max(wings, key=lambda p: p[1])  # the main wing surface
    plan = wing_planform(path, wing[0])
    return {
        "wing_area_ft2": float(plan["area_ft2"]),
        "wing_mac_ft": plan["mac_ft"],
        "wing_ac_long_ft": plan["quarter_mac_long_ft"],
        "half_span_ft": float(max(p[3][0] for p in wings) / FT),
        "top_ft": float(fuselage[3][1] / FT),
        "nose_ft": float(fuselage[3][2] / FT),    # includes the fixed probe
        "tail_end_ft": float(tail_end_m / FT),
        "bottom_ft": float(min(p[2][1] for p in gear) / FT),
        "parts": len(parts),
    }


def fdm_reference() -> dict:
    """The same quantities from the FDM's structural/gear contacts (feet)."""
    from . import a4_sync

    pts = a4_sync.read_cfg()["points"]
    return {
        "half_span_ft": pts[4][2],       # right wingtip scrape point
        "top_ft": pts[5][3],             # tail top scrape point
        "nose_ft": pts[7][1],            # nose scrape point (no probe)
        "tail_end_ft": -20.55,           # rear nav light: cfg light.2
        "bottom_ft": pts[1][3],          # main gear contact point
    }


if __name__ == "__main__":
    m, r = measure(), fdm_reference()
    print({k: round(v, 2) for k, v in m.items() if k.startswith("wing_")})
    for k in r:
        print(f"{k:12s} mesh {m[k]:7.2f} ft   fdm/cfg {r[k]:7.2f} ft   "
              f"diff {m[k] - r[k]:+.2f} ft")
