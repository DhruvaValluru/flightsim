"""The tiles' baked sky-shade, neutralised under a drawn sun (#02's blue shade).

2026-11-11, scene #02 "same, super bright preset" (the A-4 over Yosemite with
the sun relit to 72 deg). BEAUTY ONLY: the law runs in
``assets/shaders/world/tiles_shade_neutral.hlsl`` inside M_FlightSimTilesBeauty,
which only ``FFlightSimWorldBeauty`` (-quality=beauty) puts on the tileset; a
measure render never draws it. It moves no geometry and no pixel of a label:
it changes the albedo's colour only.

Why. The Google photogrammetry is a photograph: a texel the capture day's sun
missed is the rock's albedo times that day's SKY, so the baked shade is
violet-blue (B well above R and G). The beauty frame lights the tiles with
its own sun, so that baked sky colour is drawn as if it were the rock's.
Under #01's 6 deg sun (deep orange) the orange light hid it (shade +20 B - R);
under #02's near-white 72 deg sun, 1.7 stops over the meter, it is the frame:
shade 51/56/122 sRGB, the darkest 5 % of the cliffs 1/3/45, while the
scatter trees beside them (their own albedo, the same light, the same
distance) floor at 3/2/19 and the A-4 is neutral. The round-5 probes had
already taken the light away from every other suspect: the sky light red or
black, the aerial perspective 0, the fog grid off, and round 56's fog
ambient tint: the shade stayed blue each time. What stays with the pixel
through all of them is the texture. ``tiles_delight`` lifts a shadow darker
than its 32-texel neighbourhood only, so a wall wholly in shade (Yosemite's)
is its own neighbourhood and keeps its blue.

The law (``shade_neutral``): a texel's sky-shade weight is how much bluer it
is than its larger of R and G (``SHADE_BLUE_GATE`` on B / max(R, G) - 1),
times how dark it is in absolute terms (1 - luma / ``SHADE_LUMA_KNEE``),
times ``ShadeNeutralAmount`` (the collection's, per world preset); the texel
moves that share of the way to the grey of its own luma (Rec. 709, so its
brightness stays). Open water is spared: a level surface (its FACE normal,
cross(ddx, ddy) of the world position, within about 6-11 deg of up,
``SHADE_LEVEL_SLOPE``) keeps its colour. Not the vertex normal: Cesium draws
the Google tiles (KHR_materials_unlit) with every vertex normal the
ellipsoid's up, so the first version's vertex-normal test called every texel
water and moved no pixel (rounds 58/59: the A/B pixel-identical, amount 1
recorded). A sunlit texel (luma
above the knee) and a warm or green one (B not above R and G) are untouched.

Amount 0 is an exact pass-through (the shader returns its input under a
``[branch]``): ``-tiles-shade-neutral=off`` on the command line or in
``FLIGHTSIM_RENDER_SWITCHES`` sets 0 for the A/B (the frame before this
change). A city card (surface ``city``) gets 0 too: blue glass and painted
roofs are colour, and #03's facades were not the defect. UNCALIBRATED: the
amounts and the knee are set by probe render on the render machine
(docs/visual/PROBE_LOG.md ## #02 blue: the tiles' baked sky-shade).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: The Custom node's inputs, in order (scripts/ue_create_materials.py
#: WORLD_TILES_INPUTS["tiles_shade_neutral"] and the .hlsl's comment block).
SHADE_INPUTS: Tuple[str, ...] = ("Albedo", "WorldPos", "ShadeNeutralAmount")
#: Rec. 709 luma weights (the .hlsl's SHADE_LUMA; tiles_delight's too).
SHADE_LUMA: Tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
#: The divide guard (the .hlsl's SHADE_EPS).
SHADE_EPS = 1e-4
#: Linear albedo luma at and above which a texel is lit, never baked shade.
#: UNCALIBRATED.
SHADE_LUMA_KNEE = 0.30
#: Gain on B / max(R, G) - 1: a texel whose blue is 25 % above its larger
#: other channel counts fully. UNCALIBRATED.
SHADE_BLUE_GATE = 4.0
#: The level test, on slope = 1 - |face normal z|: below the first a texel counts as
#: open water (kept), above the second as ground. UNCALIBRATED.
SHADE_LEVEL_SLOPE: Tuple[float, float] = (0.005, 0.02)

#: ShadeNeutralAmount per world preset (core/scene/world_beauty.PRESETS order:
#: FlightSimClouds.cpp FlightSimTilesShade::ShadeNeutralAmounts). Under a
#: drawn direct sun (clear, hazy) the baked sky colour is wrong; under a deck
#: (overcast, rain, storm) the frame's own light is the sky's and the bake is
#: left as it was. UNCALIBRATED.
SHADE_NEUTRAL_DEFAULTS: Dict[str, float] = {
    "clear": 1.0,
    "hazy": 1.0,
    "overcast": 0.0,
    "rain": 0.0,
    "storm": 0.0,
}
#: The card surface that never takes it (the collection's TerrainDetailScale
#: uses the same word).
CITY_SURFACE = "city"

#: The A/B switch: ``-tiles-shade-neutral=on|off`` (command line, then
#: FLIGHTSIM_RENDER_SWITCHES). Anything but ``off`` draws as ``on``, the way
#: the host reads it (FlightSimClouds.cpp TilesShadeSwitch).
SWITCH_FLAG = "tiles-shade-neutral="
SWITCHES: Tuple[str, ...] = ("on", "off")
SWITCH_DEFAULT = "on"

#: The render.json record (world_beauty.tiles.shade_neutral) basis line.
BASIS = ("the photogrammetry's baked sky-shade (violet-blue, darker than the knee, not level) moved toward "
         "the grey of its own luma under a drawn sun; shader per frame, nothing stored (Google tile policy)")

#: How the level test finds the surface (the record's level_basis).
LEVEL_BASIS = ("the triangle's face normal from the world position's screen derivatives; the tiles' vertex "
               "normals are the ellipsoid's up (Cesium, KHR_materials_unlit)")

UNCALIBRATED: Tuple[str, ...] = ("SHADE_NEUTRAL_DEFAULTS", "SHADE_LUMA_KNEE", "SHADE_BLUE_GATE",
                                 "SHADE_LEVEL_SLOPE")

_SWITCH_RE = re.compile(r"(?:^|\s)-?" + re.escape(SWITCH_FLAG) + r"(\S*)")


def parse_switch(text: Optional[str]) -> str:
    """The switch's value in ``text`` (a command line or the environment
    variable), the host's way: the first match, anything but ``off`` is ``on``."""
    m = _SWITCH_RE.search(text or "")
    return "off" if m and m.group(1) == "off" else "on"


def amount_for(preset: str, surface: str = "", switch: str = SWITCH_DEFAULT) -> float:
    """ShadeNeutralAmount the host sets: the preset's, 0 over a city card or
    with the switch off, 0 for an unknown preset."""
    if switch == "off" or surface == CITY_SURFACE:
        return 0.0
    return float(SHADE_NEUTRAL_DEFAULTS.get(preset, 0.0))


def shade_weight(albedo: Any, face_up: Any = 0.0) -> np.ndarray:
    """How much each texel reads as baked sky-shade, 0..1 (before the amount).
    ``face_up`` is |z| of the unit face normal (1 level, 0 a vertical wall)."""
    a = np.maximum(np.asarray(albedo, dtype=np.float64), 0.0)
    if a.ndim < 1 or a.shape[-1] != 3:
        raise ValueError(f"albedo {a.shape} must end in 3 (RGB)")
    luma = a @ np.asarray(SHADE_LUMA)
    rg = np.maximum(np.maximum(a[..., 0], a[..., 1]), SHADE_EPS)
    violet = np.clip((a[..., 2] / rg - 1.0) * SHADE_BLUE_GATE, 0.0, 1.0)
    dark = np.clip(1.0 - luma / SHADE_LUMA_KNEE, 0.0, 1.0)
    slope = 1.0 - np.clip(np.abs(np.asarray(face_up, dtype=np.float64)), 0.0, 1.0)
    lo, hi = SHADE_LEVEL_SLOPE
    t = np.clip((slope - lo) / (hi - lo), 0.0, 1.0)
    water = 1.0 - t * t * (3.0 - 2.0 * t)   # HLSL smoothstep
    return violet * dark * (1.0 - water)


def shade_neutral(albedo: Any, face_up: Any = 0.0, amount: float = 1.0) -> np.ndarray:
    """tiles_shade_neutral.hlsl on arrays of shape (..., 3), linear 0..1.
    ``face_up`` is the face normal's |z| (broadcast). Amount 0
    (or below) returns ``albedo`` unchanged."""
    if not np.isfinite(float(amount)):
        raise ValueError(f"amount {amount!r} is not a finite number")
    a0 = np.asarray(albedo, dtype=np.float64)
    amount = min(max(float(amount), 0.0), 1.0)
    if amount <= 0.0:
        return a0
    a = np.maximum(a0, 0.0)
    luma = (a @ np.asarray(SHADE_LUMA))[..., None]
    w = (shade_weight(a, face_up) * amount)[..., None]
    return a + (luma - a) * w


def shade_record(preset: str, surface: str = "", switch: str = SWITCH_DEFAULT) -> Dict[str, Any]:
    """render.json ``world_beauty.tiles.shade_neutral`` as FlightSimClouds.cpp writes it."""
    return {
        "amount": amount_for(preset, surface, switch),
        "preset_amount": float(SHADE_NEUTRAL_DEFAULTS.get(preset, 0.0)),
        "switch": switch,
        "luma_knee": SHADE_LUMA_KNEE,
        "blue_gate": SHADE_BLUE_GATE,
        "level_basis": LEVEL_BASIS,
        "basis": BASIS,
        "pixel_moving": False,
        "calibration": "UNCALIBRATED",
    }
