"""The Google tiles lit by the frame's own sun (r147, scenes #01 / #02).

BEAUTY ONLY: ``FFlightSimGoogleTiles::ApplyBeautyLook`` (FlightSimGoogleTiles.cpp),
whose one caller is ``-quality=beauty``, is the host; this module is its twin.

Why. Google's photogrammetry tiles carry ``KHR_materials_unlit``. Cesium for
Unreal (CesiumGltfComponent.cpp) then gives every vertex the ELLIPSOID's up as
its normal (``setUnlitNormals``; the tileset's GenerateSmoothNormals never runs
for an unlit primitive) and sets the tile's ``bCastDynamicShadow`` false. Our
beauty material is default-lit, so the drawn sun's N.L was sin(elevation) on
every texel alike: 0.10 for #01's ~6-8 deg golden-hour sun, so the blue sky
light lit the frame and the rock read grey-violet; and no tile cast a shadow, so
no long golden-hour shadows could exist whatever the sun's colour, angle or the
exposure (round 1461's -sky-capture-veil=off moved the luma 0.178 -> 0.185 only).
Under #02's 72 deg sun every wall took the full sun flat on, so the frame was the
texture's baked violet shade, over-lit.

The fix: ``ACesium3DTileset::SetIgnoreKhrMaterialsUnlit(true)``. Cesium then
generates normals for the tiles and lets them cast shadows: the sun's angle
shades the cliffs (the sun-facing walls take the warm key, the rest the sky) and
the ridges throw long shadows at a low sun. Geometry is unchanged (the same
triangles; IDs, depth and the label passes are the same pixels). A requested
``-passes=normal`` in a beauty run now reads the tiles' real normals.

``-tiles-lit=off`` (command line, then ``FLIGHTSIM_RENDER_SWITCHES``) is the
A/B: the round-146 frame. Anything but ``off`` is ``on``, the host's way.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

SWITCH_FLAG = "tiles-lit="
SWITCHES: Tuple[str, ...] = ("on", "off")
SWITCH_DEFAULT = "on"
#: The Cesium for Unreal setter the host calls (Cesium3DTileset.h, 2.x).
CESIUM_SETTER = "SetIgnoreKhrMaterialsUnlit"
#: render.json: world_beauty ... google_tiles beauty record key.
RECORD_KEY = "tiles_lit"

BASIS_ON = ("KHR_materials_unlit ignored: Cesium's generated smooth normals and tile shadows, "
            "so the sun's angle shades the terrain")
BASIS_OFF = "-tiles-lit=off: the unlit tiles (the ellipsoid's up as every normal, no tile shadow)"

# FParse::Value: a case-insensitive find, the value stopping at a space or a comma.
_SWITCH_RE = re.compile(r"(?:^|\s)-?" + re.escape(SWITCH_FLAG) + r"([^\s,]*)", re.IGNORECASE)


def parse_switch(*texts: Optional[str]) -> str:
    """The switch from the command line then the environment variable joined,
    as the host reads it (FParse::Value: the first match); only ``off`` is off,
    in any case (FString's != ignores case)."""
    m = _SWITCH_RE.search(" ".join(t or "" for t in texts))
    return "off" if m and m.group(1).lower() == "off" else "on"


def ignore_unlit(switch: str = SWITCH_DEFAULT) -> bool:
    """IgnoreKhrMaterialsUnlit as the host sets it."""
    return switch.lower() != "off"


def lit_fraction(sun_elevation_deg: float, face_normal: Any = (0.0, 0.0, 1.0),
                 sun_azimuth_dir: Any = (1.0, 0.0), switch: str = SWITCH_DEFAULT) -> float:
    """The direct sun's Lambert N.L on a face (unit normal, z up) for a sun at
    ``sun_elevation_deg`` coming from the horizontal unit direction
    ``sun_azimuth_dir``: what the host draws. With the switch off every face
    has the ellipsoid's up as its normal, so the answer is sin(elevation) for
    every face, the round-146 defect."""
    import math
    e = math.radians(float(sun_elevation_deg))
    ax, ay = sun_azimuth_dir
    to_sun = (math.cos(e) * ax, math.cos(e) * ay, math.sin(e))
    n = (0.0, 0.0, 1.0) if not ignore_unlit(switch) else tuple(float(c) for c in face_normal)
    return max(0.0, sum(a * b for a, b in zip(n, to_sun)))


def record(switch: str = SWITCH_DEFAULT, before: bool = False) -> Dict[str, Any]:
    """The host's render.json ``tiles_lit`` record."""
    lit = ignore_unlit(switch)
    return {
        "switch": "on" if lit else "off",
        "before": bool(before),
        "ignore_khr_materials_unlit": lit or bool(before),
        "basis": BASIS_ON if lit else BASIS_OFF,
    }
