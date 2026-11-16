"""Open water on the Google tiles, one colour across tile edges (#06's quilted bay).

Round 147, 2026-11-16, scene #06 "A320 over SFO, moderate rain". BEAUTY ONLY: the
law runs in ``assets/shaders/world/tiles_water_unify.hlsl`` inside
M_FlightSimTilesBeauty, which only ``FFlightSimWorldBeauty`` (-quality=beauty) puts on
the tileset; a label capture never draws it. Colour only: no geometry, depth or label
pixel moves.

Why. Windows r146 (9ef62483) and r14622 drew San Francisco Bay as a quilt of
straight-edged quads and wedges, each one flat colour, neighbours about 10 sRGB levels
apart (24/45/93, 30/54/101, 41/64/104 at the same range), the edges straight across
open water: tile edges. Google's photogrammetry colours each tile's water from its
own capture and, at range, its own LOD's texture; and tiles_delight's local mean (the
same texture at mip +5) is per texture, so a tile that holds shore lifts its water
toward the land while its all-water neighbour does not. Both are a step in the
tile's MEAN colour that is constant over the tile.

The law (``water_unify``): a texel is open water by its weight
``level x dark x blue x calm`` -- a level face (the face normal from the world
position's derivatives, as tiles_shade_neutral), a dark local mean (AlbedoLow's luma
under WATER_DARK_LO..HI), a blue-or-teal local mean (B over R by WATER_BR_MIN, B not
under WATER_BG_MIN of G) and little texture contrast against that mean. There the
tile's mean is replaced by one WATER_MEAN for every tile and the texel keeps its own
detail as its luma ratio to the mean (clamped):
``out = lerp(a, WATER_MEAN x clamp(L / Lm, lo, hi), weight x amount)``.

Amount per world preset: under a deck (overcast, rain, storm) the water is a grey
sheet and the quilt is the defect; under a drawn sun (clear, hazy) the tile's own
water colour is kept until a Windows A/B says otherwise. ``-tiles-water-unify=off``
(or a number 0..1, the amount) is the A/B. Amount 0 is an exact pass-through.
UNCALIBRATED: every number (docs/visual PROBE_LOG, round 147).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: The Custom node's inputs, in order (scripts/ue_create_materials.py WORLD_TILES_INPUTS).
WATER_INPUTS: Tuple[str, ...] = ("Albedo", "AlbedoLow", "WorldPos", "WaterUnifyAmount")
WATER_LUMA: Tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
WATER_EPS = 1e-4
#: The one open-water mean every tile is moved to (linear; sRGB ~39/56/66, a slate
#: bay under cloud). UNCALIBRATED.
WATER_MEAN: Tuple[float, float, float] = (0.020, 0.040, 0.055)
#: Face slope (1 - |n.z|): level below LO, not water above HI (tiles_shade_neutral's).
WATER_LEVEL: Tuple[float, float] = (0.005, 0.02)
#: The local mean's luma: water below LO, land above HI.
WATER_DARK: Tuple[float, float] = (0.07, 0.12)
WATER_BR_MIN = 1.1
WATER_BR_GAIN = 3.0
WATER_BG_MIN = 0.85
WATER_BG_GAIN = 6.0
#: Texture contrast |L / Lm - 1| kept whole up to KEEP, gone KEEP + SPAN on.
WATER_FLAT_KEEP = 0.15
WATER_FLAT_SPAN = 0.30
WATER_RATIO: Tuple[float, float] = (0.6, 1.6)

#: WaterUnifyAmount per world preset (FlightSimClouds.cpp FlightSimTilesWater::Amounts).
WATER_UNIFY_DEFAULTS: Dict[str, float] = {"clear": 0.0, "hazy": 0.0, "overcast": 1.0, "rain": 1.0, "storm": 1.0}

SWITCH_FLAG = "tiles-water-unify="
SWITCH_DEFAULT = "on"
BASIS = ("open water (a level face, dark blue-or-teal local mean, little texture contrast) moved from its "
         "tile's own mean colour to one WATER_MEAN, keeping its luma ratio to that mean; shader per frame, "
         "nothing stored (Google tile policy)")
UNCALIBRATED: Tuple[str, ...] = ("WATER_MEAN", "WATER_LEVEL", "WATER_DARK", "WATER_BR_MIN", "WATER_BR_GAIN",
                                 "WATER_BG_MIN", "WATER_BG_GAIN", "WATER_FLAT_KEEP", "WATER_FLAT_SPAN",
                                 "WATER_RATIO", "WATER_UNIFY_DEFAULTS")

_SWITCH_RE = re.compile(r"(?:^|\s)-?" + re.escape(SWITCH_FLAG) + r"(\S*)")


def _number(text: str) -> Optional[float]:
    return float(text) if re.fullmatch(r"\d+(?:\.\d*)?|\.\d+", text or "") else None


def parse_switch(text: Optional[str]) -> str:
    """The switch's value in a command line: ``off``, a number, else ``on``."""
    m = _SWITCH_RE.search(text or "")
    if m and m.group(1) == "off":
        return "off"
    if m and _number(m.group(1)) is not None:
        return m.group(1)
    return "on"


def amount_for(preset: str, switch: str = SWITCH_DEFAULT) -> float:
    """WaterUnifyAmount the host sets (FlightSimTilesWater::AmountFor)."""
    if switch == "off":
        return 0.0
    number = _number(switch)
    if number is not None:
        return min(max(number, 0.0), 1.0)
    return float(WATER_UNIFY_DEFAULTS.get(preset, 0.0))


def _smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def water_weight(albedo: Any, albedo_low: Any, face_up: Any = 1.0) -> np.ndarray:
    """How much each texel is open water, 0..1 (before the amount)."""
    a = np.maximum(np.asarray(albedo, dtype=np.float64), 0.0)
    m = np.maximum(np.asarray(albedo_low, dtype=np.float64), 0.0)
    luma = np.asarray(WATER_LUMA)
    L = a @ luma
    Lm = np.maximum(m @ luma, WATER_EPS)
    level = 1.0 - _smoothstep(*WATER_LEVEL, 1.0 - np.clip(np.abs(np.asarray(face_up, dtype=np.float64)), 0.0, 1.0))
    dark = 1.0 - _smoothstep(*WATER_DARK, Lm)
    blue = (np.clip((m[..., 2] / np.maximum(m[..., 0], WATER_EPS) - WATER_BR_MIN) * WATER_BR_GAIN, 0.0, 1.0)
            * np.clip((m[..., 2] / np.maximum(m[..., 1], WATER_EPS) - WATER_BG_MIN) * WATER_BG_GAIN, 0.0, 1.0))
    calm = np.clip(1.0 - (np.abs(L / Lm - 1.0) - WATER_FLAT_KEEP) / WATER_FLAT_SPAN, 0.0, 1.0)
    return level * dark * blue * calm


def water_unify(albedo: Any, albedo_low: Any, face_up: Any = 1.0, amount: float = 1.0) -> np.ndarray:
    """tiles_water_unify.hlsl on arrays (..., 3), linear. Amount 0 returns ``albedo``."""
    if not np.isfinite(float(amount)):
        raise ValueError(f"amount {amount!r} is not a finite number")
    a0 = np.asarray(albedo, dtype=np.float64)
    amount = min(max(float(amount), 0.0), 1.0)
    if amount <= 0.0:
        return a0
    a = np.maximum(a0, 0.0)
    m = np.maximum(np.asarray(albedo_low, dtype=np.float64), 0.0)
    luma = np.asarray(WATER_LUMA)
    ratio = (a @ luma) / np.maximum(m @ luma, WATER_EPS)
    target = np.asarray(WATER_MEAN) * np.clip(ratio, *WATER_RATIO)[..., None]
    w = (water_weight(a, m, face_up) * amount)[..., None]
    return a + (target - a) * w


def water_record(preset: str, switch: str = SWITCH_DEFAULT) -> Dict[str, Any]:
    """render.json ``world_beauty.tiles.water_unify`` as FlightSimClouds.cpp writes it."""
    return {
        "amount": amount_for(preset, switch),
        "preset_amount": float(WATER_UNIFY_DEFAULTS.get(preset, 0.0)),
        "switch": switch if switch == "off" or _number(switch) is not None else "on",
        "water_mean": list(WATER_MEAN),
        "basis": BASIS,
        "pixel_moving": False,
    }
