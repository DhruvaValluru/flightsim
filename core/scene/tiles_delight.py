"""Tile de-lighting: lift the photogrammetry's baked shadows, per frame, in the shader.

Visual overhaul, module tiles-delight (2026-11-09). BEAUTY ONLY.

Google Photorealistic 3D Tiles are photogrammetry: their texture is the
capture day's light, cast shadows included, and those shadows are darker
than their surroundings and blue (only the skylight lit them). Under the
simulated sun at another hour they point the wrong way and double the
engine's own shadowing (virtual shadow maps and Lumen's short-range AO).
``assets/shaders/world/tiles_delight.hlsl`` runs in
``M_FlightSimTilesBeauty`` ahead of the existing grade
(``tiles_base_colour.hlsl``) and lifts what it judges to be a baked shadow
toward the local mean, neutralising its blue cast. This module is its
Python twin, number for number (``tests/test_tiles_delight.py`` pins the
HLSL's constants and input order to it).

What the law is (``delight``):

* ``L`` and ``Lm`` are the Rec. 709 luma of the pixel and of the same
  texture at a coarse mip (``DelightMipBias``, about +5: the local mean);
* ``shadow = saturate((knee - L/Lm) / knee) * saturate((B/R - 1) * gate)``:
  darker than ``knee`` of the neighbourhood AND bluer than red. A dark but
  neutral pixel (asphalt, a black roof) has B/R near 1 and is left almost
  alone;
* ``w = shadow * amount``; the pixel is scaled toward the mean's luma by
  ``w`` and its chroma pulled toward the mean's chroma by the same ``w``;
* clamped to [0, 1] and, channel by channel, never above the larger of the
  pixel and the mean: a lift never overshoots its neighbourhood, and a pixel
  that is not a candidate (``w = 0``) comes back exactly as it went in.

What it may not do (the rules it is written under):

* Google's Map Tiles policy forbids storing derived content: this is a
  shader operation per frame. There is no baked texture, no cache and no
  tool that writes a de-lit image; this module holds the law for tests and
  the probe only. The Google attribution is untouched.
* The tiles stay the ground of every terrain render (the owner's rule);
  nothing here can disable them.
* Colour only, on the tile surface only: no world-position offset, no depth
  change, no pixel moves. The label captures never draw
  ``M_FlightSimTilesBeauty`` (it is the beauty material, set only by the
  beauty look), so class, mask and depth are untouched by construction. It
  is not a ``PIXEL_MOVING_KEYS`` entry.

Every number here is UNCALIBRATED: set by probe render on the render
machine (docs/visual/PROBE_LOG.md ``## tiles-delight``).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

#: The refusal name for a de-light call the law cannot run (the catalogue's;
#: the raise sites spell it out so tests/test_messages.py's scanner sees it).
CONSTRAINT = "world_beauty.tiles_delight"


class TilesDelightError(ValueError):
    """A de-light call with arrays or parameters the law cannot use."""

    def __init__(self, constraint: str, message: str):
        super().__init__(f"{constraint}: {message}")
        self.constraint = constraint


#: The Custom node's inputs, in order (scripts/ue_create_materials.py
#: WORLD_TILES_INPUTS["tiles_delight"] and the .hlsl's comment block).
DELIGHT_INPUTS: Tuple[str, ...] = ("Albedo", "AlbedoLow", "DelightAmount", "DelightRatioKnee",
                                   "DelightBlueGate")

#: Rec. 709 luma weights (the .hlsl's DELIGHT_LUMA; tiles_base_colour.hlsl's too).
DELIGHT_LUMA: Tuple[float, float, float] = (0.2126, 0.7152, 0.0722)
#: The divide guard (the .hlsl's DELIGHT_EPS).
DELIGHT_EPS = 1e-4

#: The coarse mip's bias: +5 is a 32x32 texel neighbourhood. A material scalar
#: parameter (scripts/ue_create_materials.py WORLD_TILES_DELIGHT_SCALARS).
#: UNCALIBRATED: the probe sets it against the tiles' texel density at 300 m AGL.
DELIGHT_MIP_BIAS = 5.0
#: A pixel under this share of its neighbourhood's luma is a shadow candidate.
#: A material scalar parameter. UNCALIBRATED.
DELIGHT_RATIO_KNEE = 0.6
#: Gain on (B/R - 1): at 4, a pixel 25 % bluer than red counts fully.
#: MPC_FlightSimWorld.DelightBlueGate. UNCALIBRATED.
DELIGHT_BLUE_GATE = 4.0
#: The sun's screen-space contact shadow length (ULightComponent::ContactShadowLength,
#: a share of the screen; 0 = off). UNCALIBRATED.
CONTACT_SHADOW_LENGTH = 0.05
#: Lumen's short-range AO, set by code for the beauty render (both default 1 in
#: 5.7.4, LumenScreenProbeGather.cpp and LumenScreenSpaceBentNormal.cpp; ECVF_Scalability,
#: so pinned here rather than left to the scalability level). Read back into render.json.
CONTACT_CVARS: Dict[str, int] = {
    "r.Lumen.ScreenProbeGather.ShortRangeAO": 1,
    "r.Lumen.ScreenProbeGather.ShortRangeAO.HorizonSearch": 1,
}

#: DelightAmount per world preset (core/scene/world_beauty.PRESETS). Under a
#: direct sun (clear, hazy) the baked shadows read wrong and are lifted harder;
#: under diffuse light (overcast, rain, storm) the capture's soft occlusion is
#: close to what the sky would give and most of it is kept. UNCALIBRATED.
DELIGHT_DEFAULTS: Dict[str, float] = {
    "clear": 0.5,
    "hazy": 0.5,
    "overcast": 0.2,
    "rain": 0.2,
    "storm": 0.2,
}

#: The render.json basis line (world_beauty.tiles.delight.basis; the C++ says it too).
BASIS = "shader per frame, nothing stored (Google tile policy)"

#: Where the record points for the contact shading that replaces the lifted
#: shadows (FlightSimClouds.cpp writes it under world_beauty.atmosphere).
CONTACT_SHADING_RECORD = "world_beauty.atmosphere.contact_shading"

#: The names a probe render must set.
UNCALIBRATED: Tuple[str, ...] = ("DELIGHT_DEFAULTS", "DELIGHT_MIP_BIAS", "DELIGHT_RATIO_KNEE",
                                 "DELIGHT_BLUE_GATE", "CONTACT_SHADOW_LENGTH")


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.asarray(DELIGHT_LUMA, dtype=rgb.dtype)


def shadow_weight(albedo: Any, albedo_lowmip: Any, ratio_knee: float = DELIGHT_RATIO_KNEE,
                  blue_gate: float = DELIGHT_BLUE_GATE) -> np.ndarray:
    """How much each pixel reads as a baked shadow, 0..1 (before ``amount``)."""
    a, m = _arrays(albedo, albedo_lowmip)
    knee = max(float(ratio_knee), DELIGHT_EPS)
    ratio = _luma(a) / np.maximum(_luma(m), DELIGHT_EPS)
    darker = np.clip((knee - ratio) / knee, 0.0, 1.0)
    bluer = np.clip((a[..., 2] / np.maximum(a[..., 0], DELIGHT_EPS) - 1.0) * float(blue_gate), 0.0, 1.0)
    return darker * bluer


def delight(albedo: Any, albedo_lowmip: Any, amount: float, ratio_knee: float = DELIGHT_RATIO_KNEE,
            blue_gate: float = DELIGHT_BLUE_GATE) -> np.ndarray:
    """The de-lit albedo: tiles_delight.hlsl on arrays of shape (..., 3), linear 0..1.

    ``albedo_lowmip`` is the coarse-mip sample at each pixel (same shape).
    ``amount`` 0 returns ``albedo`` unchanged (for values in [0, 1])."""
    a, m = _arrays(albedo, albedo_lowmip)
    for name, value in (("amount", amount), ("ratio_knee", ratio_knee), ("blue_gate", blue_gate)):
        if not np.isfinite(float(value)):
            raise TilesDelightError("world_beauty.tiles_delight", f"{name} {value!r} is not a finite number")
    if float(ratio_knee) <= 0.0 or float(blue_gate) < 0.0:
        raise TilesDelightError("world_beauty.tiles_delight",
                                f"ratio_knee {ratio_knee!r} must be above 0 and "
                                f"blue_gate {blue_gate!r} at least 0")
    L = _luma(a)
    Lm = _luma(m)
    w = (shadow_weight(a, m, ratio_knee, blue_gate) * min(max(float(amount), 0.0), 1.0))[..., None]
    gain = Lm / np.maximum(L, DELIGHT_EPS)
    lifted = a * (1.0 + (gain[..., None] - 1.0) * w)
    pulled = m / np.maximum(Lm, DELIGHT_EPS)[..., None] * _luma(lifted)[..., None]
    c = lifted + (pulled - lifted) * w
    return np.minimum(np.clip(c, 0.0, 1.0), np.maximum(a, m))


def _arrays(albedo: Any, albedo_lowmip: Any) -> Tuple[np.ndarray, np.ndarray]:
    a = np.maximum(np.asarray(albedo, dtype=np.float64), 0.0)
    m = np.maximum(np.asarray(albedo_lowmip, dtype=np.float64), 0.0)
    if a.shape != m.shape or a.ndim < 1 or a.shape[-1] != 3:
        raise TilesDelightError("world_beauty.tiles_delight",
                                f"albedo {a.shape} and its low mip {m.shape} must be "
                                f"the same shape, ending in 3 (RGB)")
    return a, m


def amount_for(preset: str) -> float:
    """DelightAmount for a world preset (0, a pass-through, for an unknown one)."""
    return float(DELIGHT_DEFAULTS.get(preset, 0.0))


def delight_record(preset: str) -> Dict[str, Any]:
    """render.json ``world_beauty.tiles.delight`` as FlightSimClouds.cpp writes it."""
    return {
        "amount": amount_for(preset),
        "mip_bias": DELIGHT_MIP_BIAS,
        "ratio_knee": DELIGHT_RATIO_KNEE,
        "blue_gate": DELIGHT_BLUE_GATE,
        "preset": preset,
        "basis": BASIS,
        "pixel_moving": False,
        "calibration": "UNCALIBRATED",
        "contact_shading": CONTACT_SHADING_RECORD,
    }
