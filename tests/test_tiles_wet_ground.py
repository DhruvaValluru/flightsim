"""Tiles generation 7 (2026-11-14): the wet ground of #15 / #09 / #10 (heavy rain over
Kansas farmland) drew near-black ground scratched with white glints. A Python twin of
the shaders' shared puddle noise and of the wet roughness / colour shows the cause in
numbers, the fix, and that a dry card (clear, hazy, overcast: #01-#05, #11, #12) renders
exactly as before."""
import re
from pathlib import Path

import numpy as np

from core.scene import world_beauty as wb

SHADERS = Path(__file__).resolve().parents[1] / "assets" / "shaders" / "world"
ROUGH = (SHADERS / "tiles_roughness.hlsl").read_text(encoding="utf-8")
BASE = (SHADERS / "tiles_base_colour.hlsl").read_text(encoding="utf-8")
SCRIPT = (Path(__file__).resolve().parents[1] / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def _hash2(ix, iy):
    q = (ix.astype(np.int64) & 0xFFFFFFFF).astype(np.uint64), (iy.astype(np.int64) & 0xFFFFFFFF).astype(np.uint64)
    m = np.uint64(0xFFFFFFFF)
    h = ((q[0] * np.uint64(1597334677)) & m) ^ ((q[1] * np.uint64(3812015801)) & m)
    h = ((h ^ (h >> np.uint64(16))) * np.uint64(2246822519)) & m
    return ((h ^ (h >> np.uint64(13))) & m).astype(np.float64) / 4294967296.0


def _value2(x, y):
    ix, iy = np.floor(x), np.floor(y)
    fx, fy = x - ix, y - iy
    ux, uy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash2(ix, iy), _hash2(ix + 1, iy)
    c, d = _hash2(ix, iy + 1), _hash2(ix + 1, iy + 1)
    return (a + (b - a) * ux) + ((c + (d - c) * ux) - (a + (b - a) * ux)) * uy


def _smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def _puddles(xs_cm, ys_cm, amount):
    """The shaders' shared Puddles() on flat ground (level 1)."""
    n = _value2(xs_cm / 2500.0, ys_cm / 2500.0) * 0.7 + _value2(xs_cm / 600.0, ys_cm / 600.0) * 0.3
    return _smoothstep(1.0 - amount, 1.0 - amount + 0.08, n)


GRID = np.meshgrid(np.linspace(0, 4.0e6, 400), np.linspace(0, 4.0e6, 400))   # 40 km of flat ground, cm


def test_the_cause_half_the_flat_ground_was_mirror_water():
    old = _puddles(*GRID, 0.5 * 1.0).mean()          # the old share at Wetness 1
    new = _puddles(*GRID, wb.PUDDLE_SHARE_OF_WETNESS * 1.0 * wb.PUDDLE_AMOUNT_SCALE).mean()
    assert old > 0.35, old                          # the old law: ~41 % of the prairie under water
    assert new < 0.08, new                          # generation 7: ~4 %
    assert wb.PUDDLE_SHARE_OF_WETNESS == 0.5 and wb.PUDDLE_AMOUNT_SCALE == 0.5


def _roughness(wet, puddle_amount, range_m, micro=0.0, puddle=None):
    far = min(range_m / wb.WET_SPEC_FADE_M, 1.0)
    r_wet = wb.ROUGHNESS_WET + (wb.ROUGHNESS_WET_FAR - wb.ROUGHNESS_WET) * far
    r = (wb.ROUGHNESS_DRY + micro) + (r_wet - (wb.ROUGHNESS_DRY + micro)) * wet
    p = (puddle if puddle is not None else 0.0) * max(0.0, 1.0 - range_m / wb.PUDDLE_FADE_M)
    r_p = wb.ROUGHNESS_PUDDLE + (r_wet - wb.ROUGHNESS_PUDDLE) * far
    return min(max(r + (r_p - r) * p, 0.0), 1.0)


def test_a_dry_card_is_unchanged():
    for preset in ("clear", "hazy", "overcast"):
        p = wb.tiles_parameters(preset, 0.0)
        assert p["Wetness"] == 0.0 and p["PuddleAmount"] == 0.0, preset
    # PuddleAmount 0 -> the shared threshold smoothstep(1, 1.08, n) is 0 for every n <= 1.
    assert _puddles(*GRID, 0.0).max() == 0.0
    for range_m in (10.0, 800.0, 5000.0, 30000.0):
        for micro in (-0.06, 0.0, 0.06):
            old = min(max(wb.ROUGHNESS_DRY + micro, 0.0), 1.0)
            assert _roughness(0.0, 0.0, range_m, micro) == old


def test_storm_ground_is_a_broad_sheen_not_a_mirror_and_dark_not_black():
    p = wb.tiles_parameters("storm", 1.0)
    assert p["Wetness"] == 1.0 and p["PuddleAmount"] == 0.5
    # Near, on a puddle: a wet-asphalt sheen (0.15), not the old 0.05 mirror.
    assert _roughness(1.0, 0.25, 50.0, puddle=1.0) >= 0.15
    # Far (beyond the fade): the wet specular is broad, and no puddle remains.
    assert _roughness(1.0, 0.25, 5000.0, puddle=1.0) == wb.ROUGHNESS_WET_FAR
    # Colour on a near puddle: 0.70 x 0.70 = 0.49 of the albedo (was 0.70 x 0.45 = 0.315).
    assert (1 - wb.WET_DARKENING) * (1 - wb.PUDDLE_DARKENING) > 0.45


def test_shaders_carry_world_beauty_constants():
    for text, consts in ((ROUGH, ("ROUGHNESS_PUDDLE", "ROUGHNESS_WET_FAR", "WET_SPEC_FADE_M", "PUDDLE_FADE_M",
                                  "PUDDLE_AMOUNT_SCALE")),
                         (BASE, ("PUDDLE_DARKENING", "PUDDLE_FADE_M", "PUDDLE_AMOUNT_SCALE"))):
        found = dict(re.findall(r"const float (\w+) = ([0-9.]+);", text))
        for c in consts:
            assert float(found[c]) == getattr(wb, c), c
    assert "saturate(PuddleAmount) * PUDDLE_AMOUNT_SCALE)" in ROUGH and "saturate(PuddleAmount) * PUDDLE_AMOUNT_SCALE)" in BASE
    assert "* saturate(1.0 - rangeM / PUDDLE_FADE_M);" in ROUGH and "* saturate(1.0 - rangeM / PUDDLE_FADE_M);" in BASE
    assert "//   CameraPos     float3" in BASE
    assert '"tiles_base_colour": ("Albedo", "WorldPos", "CameraPos", "NormalWS"' in SCRIPT
    assert '"M_FlightSimTilesBeauty": "7"' in SCRIPT
