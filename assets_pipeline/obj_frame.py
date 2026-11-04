"""The ONE axis convention every OBJ this pipeline writes follows.

Both converters (``convert.py`` for the FlightGear ``.ac`` airframes,
``a4_mdl_convert.py`` for the P3D ``.mdl``) work in the UE actor frame
(+X forward, +Y right, +Z up, centimetres), which is LEFT-handed. The OBJ
format carries no handedness of its own, and Unreal's Interchange OBJ
importer treats the file as RIGHT-handed: it negates Y on import. Measured
on the A-4 (decision 19, packet C4-1, 2026-11-04): an OBJ written straight
in the actor frame came back as its mirror image (body y [-411.99, 412.8]
cm became [-412.8, 412.0]; the port store at y [-2.30, -1.48] m drew to
starboard at [148.3, 230.0] cm), so the drawn airframe was mirrored and the
manifest's hulls sat on the other side of the pixels.

So an OBJ is written as a standard OBJ exporter from a left-handed source
writes it: ``obj = (actor X, -actor Y, actor Z)`` for positions AND
normals, and every face's winding reversed (the map has determinant -1,
so the triangle's geometric normal would otherwise flip inward). The
importer's own standard mirror then lands the asset exactly in the
actor frame the manifest measures in. The manifest's numbers
(``bounds_cm``, ``mesh_origin_actor_cm``, ``mesh_extent_actor_m``,
``mesh_origin_actor_cm`` of every component row) stay in the ACTOR frame:
the OBJ is the only artefact in the OBJ frame, and the manifest says so
with ``obj_frame``.

``importer.stale_manifest_reason`` refuses a manifest without this exact
``obj_frame`` stamp, so every conversion written before the fix is
re-converted and re-imported by A7's rule (a left-handed OBJ already
imported is a mirror image on disk).
"""

from __future__ import annotations

from typing import Sequence, Tuple, TypeVar

#: The stamp a manifest carries for the OBJs beside it. Exact-match: a
#: different convention gets a different string.
OBJ_FRAME = "right-handed: obj = (actor X, -actor Y, actor Z), faces rewound"
#: The manifest key the stamp lives under.
OBJ_FRAME_KEY = "obj_frame"

T = TypeVar("T")


def actor_to_obj(point: Sequence[float]) -> Tuple[float, float, float]:
    """UE actor frame (left-handed) -> the OBJ's right-handed frame:
    negate Y. Works for positions (any unit) and for unit normals. The
    ``+ 0.0`` keeps a negated 0.0 from printing as ``-0.0``."""
    x, y, z = point
    return (float(x), -float(y) + 0.0, float(z))


def actor_to_obj_array(points):
    """:func:`actor_to_obj` over an ``(n, 3)`` numpy array."""
    import numpy as np

    out = np.array(points, dtype=float, copy=True)
    out[:, 1] = -out[:, 1] + 0.0
    return out


def obj_winding(indices: Sequence[T]) -> Tuple[T, ...]:
    """The face order to WRITE for a triangle wound outward in the actor
    frame: reversed, because :func:`actor_to_obj` has determinant -1 and
    a mirrored triangle written in its original order would face inward.
    Reverse, not rotate: the first vertex changes but the cycle is the
    same triangle."""
    return tuple(reversed(tuple(indices)))


def signed_volume(vertices: Sequence[Sequence[float]],
                  faces: Sequence[Sequence[int]]) -> float:
    """Sum over faces of det(a, b, c) / 6 for 0-based vertex indices: the
    signed volume a closed, outward-wound mesh encloses (positive in a
    right-handed frame). Written for the tests of both converters, so
    the sign check is one function, not two."""
    total = 0.0
    for face in faces:
        a, b, c = (vertices[i] for i in face)
        total += (a[0] * (b[1] * c[2] - b[2] * c[1])
                  - a[1] * (b[0] * c[2] - b[2] * c[0])
                  + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return total
