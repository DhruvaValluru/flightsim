"""A solid aircraft, so a preview frame shows an aircraft.

The Phase 2 preview drew the aircraft as four line segments through its
recorded attitude. That was already better than the circle it replaced
-- roll became visible -- but it still read as a diagram, not as a view
out of a camera, and "is this camera framed correctly?" is a question
you answer by looking at an aircraft, not at a cross.

So this builds a low-poly airframe -- lofted fuselage, swept wings,
tailplane, fin, engine nacelles -- in the BODY frame (x forward, y
right, z down, the same convention the offsets and the pose solver
use), at the real dimensions of the airframe that flew. The preview
transforms it through the recorded attitude, shades each face against
the scene's sun, depth-sorts, and fills. The same faces flattened onto
the ground give a shadow, which is what actually tells a viewer how
high the aircraft is.

This is still not a render: no textures, no materials, no global
illumination, no engine. It is a solid-shaded viewport of the recorded
geometry -- enough to judge framing, attitude and altitude, and no more
than that. Photographic frames come from the Unreal host on Windows
(docs/CAMERA_WINDOWS.md); nothing here is a substitute for them.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

#: Real dimensions, metres. Length and span drive the whole model, so a
#: Cessna is a Cessna and a 747 is a 747 rather than one silhouette
#: scaled by eye. Unlisted airframes fall back to the airliner.
AIRFRAMES: Dict[str, Dict[str, float]] = {
    "B747": {"length_m": 70.6, "span_m": 64.4, "engines": 4,
             "sweep": 0.42, "high_wing": False},
    "A320": {"length_m": 37.6, "span_m": 35.8, "engines": 2,
             "sweep": 0.32, "high_wing": False},
    "c172p": {"length_m": 8.3, "span_m": 11.0, "engines": 0,
              "sweep": 0.0, "high_wing": True},
    "DHC6": {"length_m": 15.8, "span_m": 19.8, "engines": 0,
             "sweep": 0.0, "high_wing": True},
    "p51d": {"length_m": 9.8, "span_m": 11.3, "engines": 0,
             "sweep": 0.08, "high_wing": False},
}
FALLBACK = "B747"

#: Face colours: a light upper surface and a darker underside read as an
#: aircraft even untextured, and make bank angle unmistakable.
UPPER = (222, 226, 232)
LOWER = (150, 156, 166)
FIN = (196, 202, 212)
NACELLE = (120, 126, 136)


def dimensions(aircraft: str) -> Dict[str, float]:
    return AIRFRAMES.get(str(aircraft), AIRFRAMES[FALLBACK])


def _ring(x: float, radius: float, z_centre: float,
          sides: int = 8) -> List[Tuple[float, float, float]]:
    """A fuselage cross-section: `sides` points around a circle in the
    body y-z plane at station x."""
    points = []
    for i in range(sides):
        theta = 2.0 * math.pi * i / sides
        points.append((x, radius * math.sin(theta),
                       z_centre + radius * math.cos(theta)))
    return points


def _quad_strip(ring_a, ring_b, colour):
    """Faces between two fuselage rings."""
    faces = []
    n = len(ring_a)
    for i in range(n):
        j = (i + 1) % n
        faces.append(([ring_a[i], ring_a[j], ring_b[j], ring_b[i]], colour))
    return faces


def body_faces(aircraft: str) -> List[Tuple[List[Tuple[float, float, float]],
                                            Tuple[int, int, int]]]:
    """The airframe as (vertices, colour) faces in the BODY frame:
    x forward from the centre of gravity, y right, z DOWN, metres."""
    spec = dimensions(aircraft)
    length = spec["length_m"]
    span = spec["span_m"]
    radius = length * 0.055
    high_wing = bool(spec["high_wing"])
    sweep = float(spec["sweep"])

    nose = length * 0.55
    tail = -length * 0.45
    faces = []

    # -- fuselage: a lofted tube, tapered at both ends ------------------
    stations = [(nose, 0.02), (nose - length * 0.10, 0.65),
                (nose - length * 0.22, 1.0), (tail + length * 0.30, 1.0),
                (tail + length * 0.12, 0.62), (tail, 0.18)]
    rings = [_ring(x, radius * scale, 0.0) for x, scale in stations]
    for a, b in zip(rings, rings[1:]):
        # Upper half light, lower half dark: the shading model alone
        # cannot separate them on a cylinder lit from above.
        for index, (quad, _) in enumerate(_quad_strip(a, b, UPPER)):
            centre_z = sum(v[2] for v in quad) / 4.0
            faces.append((quad, UPPER if centre_z <= 0 else LOWER))

    # -- wings ----------------------------------------------------------
    half = span / 2.0
    root_x = length * 0.02
    root_chord = length * 0.26
    tip_chord = root_chord * 0.34
    wing_z = -radius * 0.55 if high_wing else radius * 0.35
    dihedral = span * 0.035
    for side in (-1.0, 1.0):
        tip_x = root_x - sweep * half
        quad = [
            (root_x + root_chord * 0.5, side * radius * 0.9, wing_z),
            (tip_x + tip_chord * 0.5, side * half, wing_z - dihedral),
            (tip_x - tip_chord * 0.5, side * half, wing_z - dihedral),
            (root_x - root_chord * 0.5, side * radius * 0.9, wing_z),
        ]
        faces.append((quad, UPPER))

    # -- tailplane ------------------------------------------------------
    tail_span = span * 0.38
    tail_root_x = tail + length * 0.10
    tail_chord = root_chord * 0.42
    for side in (-1.0, 1.0):
        quad = [
            (tail_root_x + tail_chord * 0.5, side * radius * 0.8, -radius * 0.1),
            (tail_root_x - sweep * tail_span * 0.5 + tail_chord * 0.25,
             side * tail_span / 2.0, -radius * 0.25),
            (tail_root_x - sweep * tail_span * 0.5 - tail_chord * 0.25,
             side * tail_span / 2.0, -radius * 0.25),
            (tail_root_x - tail_chord * 0.5, side * radius * 0.8, -radius * 0.1),
        ]
        faces.append((quad, UPPER))

    # -- fin ------------------------------------------------------------
    fin_height = span * 0.20
    faces.append(([
        (tail_root_x + tail_chord * 0.9, 0.0, -radius * 0.6),
        (tail_root_x + tail_chord * 0.1, 0.0, -radius * 0.6 - fin_height),
        (tail_root_x - tail_chord * 0.7, 0.0, -radius * 0.6 - fin_height),
        (tail_root_x - tail_chord * 0.8, 0.0, -radius * 0.6),
    ], FIN))

    # -- engine nacelles ------------------------------------------------
    count = int(spec["engines"])
    if count:
        pylons = ([0.32, 0.62] if count >= 4 else [0.36])
        nacelle_r = radius * 0.42
        for side in (-1.0, 1.0):
            for fraction in pylons:
                y = side * half * fraction
                x = root_x - sweep * half * fraction + root_chord * 0.35
                z = wing_z + radius * 0.5
                front = _ring(x, nacelle_r, z, sides=6)
                back = _ring(x - length * 0.07, nacelle_r, z, sides=6)
                faces.extend(
                    ([(vx, vy + y, vz) for vx, vy, vz in quad], NACELLE)
                    for quad, _ in _quad_strip(front, back, NACELLE))
    return faces


def body_to_world(vertex, roll_deg: float, pitch_deg: float,
                  heading_deg: float, origin) -> Tuple[float, float, float]:
    """Body (forward, right, down) -> world (north, east, up), the same
    aerospace DCM the pose solver uses."""
    r, p, y = (math.radians(roll_deg), math.radians(pitch_deg),
               math.radians(heading_deg))
    cr, sr, cp, sp, cy, sy = (math.cos(r), math.sin(r), math.cos(p),
                              math.sin(p), math.cos(y), math.sin(y))
    bx, by, bz = vertex
    north = ((cp * cy) * bx + (sr * sp * cy - cr * sy) * by
             + (cr * sp * cy + sr * sy) * bz)
    east = ((cp * sy) * bx + (sr * sp * sy + cr * cy) * by
            + (cr * sp * sy - sr * cy) * bz)
    down = (-sp) * bx + (sr * cp) * by + (cr * cp) * bz
    return (origin[0] + north, origin[1] + east, origin[2] - down)


def world_faces(aircraft: str, state: Dict) -> List[Tuple[List, Tuple]]:
    """The airframe placed and oriented in world coordinates for one
    recorded aircraft state."""
    origin = (state["north_m"], state["east_m"], state["alt_m"])
    return [([body_to_world(v, state["roll_deg"], state["pitch_deg"],
                            state["heading_deg"], origin) for v in quad],
             colour)
            for quad, colour in body_faces(aircraft)]


def face_normal(vertices: Sequence) -> Tuple[float, float, float]:
    """Unit normal of a planar face in (north, east, up)."""
    a, b, c = vertices[0], vertices[1], vertices[2]
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1],
         u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    length = math.sqrt(sum(x * x for x in n)) or 1.0
    return tuple(x / length for x in n)
