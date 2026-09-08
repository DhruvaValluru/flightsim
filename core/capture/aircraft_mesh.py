"""The real airframe geometry, loaded from the SAME source the engine uses.

The right way to get a camera view of this simulation is to render it in
Unreal: real meshes, real materials, real lighting, real terrain, the
same host that produces every existing clip. Nothing in Python is a
substitute for that, and ``flightsim.capture --render`` on Windows is
the supported path (docs/CAMERA_WINDOWS.md).

What this module does is remove one specific dishonesty from the
engine-less preview. That preview used to draw a hand-written polygon
airliner -- a shape nobody flies, sized by eye. But the aircraft the
engine renders comes from FlightGear AC3D parts listed in
``assets/aircraft_config/<name>.json``, fetched into
``assets/aircraft_src/`` by ``assets_pipeline/convert.py``, and this
repo already has a reader for them (``assets_pipeline.acmodel``). So
when those sources are present the preview draws the SAME triangles the
engine imports, through the same ``.ac`` -> model-frame mapping, and the
silhouette in a preview is the silhouette in a render.

When they are not present (``assets/aircraft_src/`` is gitignored; it
appears only after the asset pipeline runs) this returns None and the
caller falls back to the parametric model in
:mod:`core.capture.aircraft_model`. The preview caption always says
which one it drew, because "that is the real 747" and "that is a
stand-in" are very different claims.

Frame: body (x forward, y right, z DOWN), metres about the model
origin -- the convention the pose solver, the camera offsets and the
manifest all use. The FlightGear model frame is +X aft, +Y right, +Z
up, so the mapping here is (-x, y, -z) with winding preserved.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO / "assets" / "aircraft_config"
SOURCE_DIR = REPO / "assets" / "aircraft_src"

#: Triangle budget for a preview frame. The 747 is ~150k triangles; a
#: painter's-algorithm rasteriser in Pillow is not going to draw that
#: per frame, and it does not need to -- a few thousand largest faces
#: carry the silhouette and the shading. Selection is by area, and it is
#: deterministic (largest first, ties by vertex order), so the same run
#: draws the same picture twice.
TRIANGLE_BUDGET = 2600


def config_path(aircraft: str) -> Path:
    return CONFIG_DIR / f"{aircraft}.json"


def available(aircraft: str) -> bool:
    """True when the real source mesh for this airframe is on disk."""
    return _parts(aircraft) is not None


def _parts(aircraft: str) -> Optional[List[Dict]]:
    path = config_path(aircraft)
    if not path.is_file():
        return None
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    source = (path.parent / str(config.get("source_dir", ""))).resolve()
    parts = []
    for part in config.get("parts", []):
        mesh = source / str(part.get("file", ""))
        if not mesh.is_file():
            return None                    # partial source is not a model
        parts.append({"path": mesh,
                      "offset_m": tuple(part.get("offset_m", (0.0, 0.0, 0.0)))})
    return parts or None


def _model_to_body(vertex) -> Tuple[float, float, float]:
    """FlightGear model frame (+X aft, +Y right, +Z up) -> body frame
    (+X forward, +Y right, +Z down)."""
    x, y, z = vertex
    return (-x, y, -z)


def load_triangles(aircraft: str,
                   budget: int = TRIANGLE_BUDGET
                   ) -> Optional[List[Tuple[List, Tuple[int, int, int]]]]:
    """The airframe as [(triangle vertices, rgb)] in the body frame, or
    None when the source meshes are not on disk."""
    parts = _parts(aircraft)
    if parts is None:
        return None
    try:
        from assets_pipeline.acmodel import (
            ac_to_model, parse_ac, world_vertices,
        )
    except ImportError:
        return None

    triangles: List[Tuple[List, Tuple[int, int, int], float]] = []
    for part in parts:
        try:
            model = parse_ac(part["path"])
        except Exception:
            return None
        offset = part["offset_m"]
        materials = model.materials
        for obj, verts in world_vertices(model):
            for surface in obj.surfaces:
                if not surface.is_polygon or len(surface.refs) < 3:
                    continue
                material = (materials[surface.material]
                            if 0 <= surface.material < len(materials) else None)
                if material is not None and material.transparency >= 0.9:
                    continue               # glass shells: the engine skips them too
                rgb = ((int(material.rgb[0] * 255), int(material.rgb[1] * 255),
                        int(material.rgb[2] * 255)) if material
                       else (200, 204, 210))
                refs = surface.refs
                for i in range(1, len(refs) - 1):
                    corners = []
                    for ref in (refs[0], refs[i], refs[i + 1]):
                        vm = ac_to_model(verts[ref[0]])
                        vm = (vm[0] + offset[0], vm[1] + offset[1],
                              vm[2] + offset[2])
                        corners.append(_model_to_body(vm))
                    area = _area(corners)
                    if area > 0.0:
                        triangles.append((corners, rgb, area))
    if not triangles:
        return None
    # Largest faces first, capped: the silhouette lives in the big
    # panels, and the budget keeps a preview frame drawable.
    triangles.sort(key=lambda t: -t[2])
    return [(corners, rgb) for corners, rgb, _ in triangles[:budget]]


def _area(corners: Sequence) -> float:
    a, b, c = corners
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (u[1] * v[2] - u[2] * v[1],
         u[2] * v[0] - u[0] * v[2],
         u[0] * v[1] - u[1] * v[0])
    return 0.5 * math.sqrt(sum(x * x for x in n))
