"""Vertex normals for a converted airframe, by the .ac file's own crease
angle (round 2 of the visual overhaul, cockpit-airframe lane).

Why: the converter writes every triangle with its own three vertices and
no ``vn``, so Unreal's import computes one normal per triangle and the
airframe draws as flat facets (shot d's "faceted grey slab", the "toy"
J-11 of shot a) and a sun glint cannot form on a curved canopy or spine
(Gate V specular FAILed on b, c and d). FlightGear draws the same file
smooth: each AC3D surface says whether it is smooth shaded (SURF flag
0x10) and each object states a ``crease`` angle; faces of one object
that meet at a vertex at less than that angle share a normal.

This module reproduces that rule and nothing else:

* a FLAT surface (no 0x10) keeps its face normal on all three corners;
* a SMOOTH surface's corner takes the area-weighted sum of the face
  normals of every smooth triangle of the SAME object that touches the
  same position (welded at :data:`WELD_M`, so a UV seam does not split
  the normal) and whose face normal is within the object's crease angle
  of this one; an object with no ``crease`` line uses
  :data:`DEFAULT_CREASE_DEG`.

Positions are never moved: the triangles, their order and their UVs are
the caller's. So the silhouette, the depth and the label mask of a mesh
written with these normals are those of the mesh written without them;
only the shading changes. Pure Python (numpy for the sums), tested
without the engine.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

Vec = Tuple[float, float, float]

#: AC3D's default crease angle (degrees) for an object without a
#: ``crease`` line. [unverified here: AC3D's own default as remembered;
#: every object of the pinned J-11 files states its crease, so the
#: J-11 never uses it.]
DEFAULT_CREASE_DEG = 61.0
#: Positions closer than this (metres) are one vertex for the normal sum.
WELD_M = 1e-4


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a: Vec) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit(a: Vec, fallback: Optional[Vec] = None) -> Optional[Vec]:
    n = _norm(a)
    if n <= 0.0 or not math.isfinite(n):
        return fallback
    return (a[0] / n, a[1] / n, a[2] / n)


def face_normal(a: Vec, b: Vec, c: Vec) -> Vec:
    """(b - a) x (c - a): the right-handed normal of the triangle a, b, c,
    with length twice its area (the area weight)."""
    return _cross(_sub(b, a), _sub(c, a))


def vertex_normals(triangles: Sequence[Tuple[Vec, Vec, Vec]],
                   groups: Sequence[object],
                   smooth: Sequence[bool],
                   crease_deg: Sequence[Optional[float]],
                   unit_m: float = 1.0) -> List[Tuple[Vec, Vec, Vec]]:
    """One unit normal per corner of every triangle, in the triangles' own
    frame and winding (a right-handed frame: counter-clockwise faces the
    normal). ``groups[i]`` is triangle i's object (normals are shared only
    within one), ``smooth[i]`` its SURF 0x10 flag, ``crease_deg[i]`` its
    object's crease (None: :data:`DEFAULT_CREASE_DEG`). ``unit_m`` is the
    length of one position unit in metres (100 cm: 0.01) for the weld.

    A degenerate (zero-area) triangle takes the normal of the smooth faces
    around its corners when there are any, else +Z, so no corner is ever
    written without a finite unit normal."""
    count = len(triangles)
    if not (len(groups) == len(smooth) == len(crease_deg) == count):
        raise ValueError("triangles, groups, smooth and crease_deg differ in length")
    faces = [face_normal(*tri) for tri in triangles]
    units = [_unit(f) for f in faces]
    weld = WELD_M / unit_m

    def key(group, point: Vec):
        return (group, round(point[0] / weld), round(point[1] / weld), round(point[2] / weld))

    touching: Dict[tuple, List[int]] = defaultdict(list)
    for index, tri in enumerate(triangles):
        if smooth[index]:
            for corner in tri:
                touching[key(groups[index], corner)].append(index)

    up: Vec = (0.0, 0.0, 1.0)
    out: List[Tuple[Vec, Vec, Vec]] = []
    for index, tri in enumerate(triangles):
        own = units[index]
        if not smooth[index]:
            n = own or up
            out.append((n, n, n))
            continue
        crease = crease_deg[index]
        cos_limit = math.cos(math.radians(DEFAULT_CREASE_DEG if crease is None else float(crease)))
        corners = []
        for corner in tri:
            total = [0.0, 0.0, 0.0]
            for other in touching[key(groups[index], corner)]:
                other_unit = units[other]
                if other_unit is None:
                    continue
                if own is not None and (own[0] * other_unit[0] + own[1] * other_unit[1]
                                        + own[2] * other_unit[2]) < cos_limit - 1e-9:
                    continue
                f = faces[other]
                total[0] += f[0]
                total[1] += f[1]
                total[2] += f[2]
            corners.append(_unit(tuple(total), own or up))
        out.append(tuple(corners))
    return out


def flipped(normal: Vec) -> Vec:
    """The normal of the back face of a two-sided surface."""
    return (-normal[0] + 0.0, -normal[1] + 0.0, -normal[2] + 0.0)
