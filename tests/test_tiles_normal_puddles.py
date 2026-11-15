"""Tiles generation 8 (2026-11-15): tiles_normal.hlsl flattens the detail normal on the
same puddle mask as tiles_base_colour.hlsl and tiles_roughness.hlsl.

Generation 7 (f628f74c) scaled the colour's and roughness's puddles to
PUDDLE_AMOUNT_SCALE of PuddleAmount and faded them out by PUDDLE_FADE_M of range, but
the normal node still flattened across the OLD mask (~41 % of flat ground at Wetness 1,
at every range), so the ground lost its relief where no water was drawn any more. A
Python twin of each shader's mask, built from the constants parsed out of that shader's
own text, shows the three masks equal pixel for pixel, the old normal mask different,
and the dry card untouched."""
import re
from pathlib import Path

import numpy as np

from core.scene import world_beauty as wb

REPO = Path(__file__).resolve().parents[1]
SHADERS = REPO / "assets" / "shaders" / "world"
NAMES = ("tiles_base_colour", "tiles_normal", "tiles_roughness")
TEXT = {name: (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8") for name in NAMES}
SCRIPT = (REPO / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")
PUDDLE_LINE = re.compile(
    r"float puddle = T\.Puddles\(WorldPos, (?:n|normalize\(NormalWS\)), saturate\(PuddleAmount\) \* PUDDLE_AMOUNT_SCALE\)\n"
    r"\s+\* saturate\(1\.0 - rangeM / PUDDLE_FADE_M\);")


def _constants(text):
    return {k: float(v) for k, v in re.findall(r"const float (\w+) = ([0-9.]+);", text)}


def _shared_block(text):
    return text[text.index("// shared: world noise"):text.index("// end shared")]


# -- the twin ---------------------------------------------------------------------------

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


def _puddles(xs_cm, ys_cm, nz, amount):
    """The shaders' shared Puddles(): the level term times the threshold on the two-scale noise."""
    level = np.clip((nz - 0.96) / 0.03, 0, 1)
    n = _value2(xs_cm / 2500.0, ys_cm / 2500.0) * 0.7 + _value2(xs_cm / 600.0, ys_cm / 600.0) * 0.3
    return level * _smoothstep(1.0 - amount, 1.0 - amount + 0.08, n)


def _mask(consts, xs_cm, ys_cm, nz, puddle_amount, range_m):
    """A shader's puddle weight from its own constants: the body's `puddle` line."""
    amount = min(max(puddle_amount, 0.0), 1.0) * consts["PUDDLE_AMOUNT_SCALE"]
    fade = min(max(1.0 - range_m / consts["PUDDLE_FADE_M"], 0.0), 1.0)
    return _puddles(xs_cm, ys_cm, nz, amount) * fade


def _old_normal_mask(xs_cm, ys_cm, nz, puddle_amount):
    """Generation 7's tiles_normal: the full amount, no range fade."""
    return _puddles(xs_cm, ys_cm, nz, min(max(puddle_amount, 0.0), 1.0))


def _normal(detailed, puddle):
    """tiles_normal's last line: lerp toward straight up by the puddle weight, renormalised."""
    up = np.zeros_like(detailed)
    up[..., 2] = 1.0
    out = detailed + (up - detailed) * puddle[..., None]
    return out / np.linalg.norm(out, axis=-1, keepdims=True)


GRID = np.meshgrid(np.linspace(0, 4.0e6, 400), np.linspace(0, 4.0e6, 400))   # 40 km of ground, cm
RNG = np.random.default_rng(2026_11_15)
# the ground's tilt: mostly flat prairie, some of it on the level ramp, some too steep
NZ = np.where(RNG.random(GRID[0].shape) < 0.8, 1.0, RNG.uniform(0.90, 0.99, GRID[0].shape))
STORM = wb.tiles_parameters("storm", 1.0)
RANGES_M = (10.0, 500.0, 1500.0, 2900.0, 3000.0, 5000.0, 30000.0)


# -- the text ---------------------------------------------------------------------------

def test_the_three_shaders_share_one_noise_and_one_threshold():
    blocks = {name: _shared_block(text) for name, text in TEXT.items()}
    assert len(set(blocks.values())) == 1, "the shared world-noise blocks differ"
    assert "smoothstep(1.0 - amount, 1.0 - amount + 0.08, n)" in blocks["tiles_normal"]


def test_the_three_shaders_carry_the_same_scale_and_fade():
    for name, text in TEXT.items():
        consts = _constants(text)
        assert consts["PUDDLE_AMOUNT_SCALE"] == wb.PUDDLE_AMOUNT_SCALE, name
        assert consts["PUDDLE_FADE_M"] == wb.PUDDLE_FADE_M, name
        assert PUDDLE_LINE.search(text), f"{name}: the puddle line is not the shared form"
    # the normal's range comes from the same CameraPos the colour and roughness read
    assert '"tiles_normal": ("WorldPos", "CameraPos", "NormalWS"' in SCRIPT
    assert "float rangeM = length(WorldPos - CameraPos) / 100.0;" in TEXT["tiles_normal"]
    assert "UNCALIBRATED" in TEXT["tiles_normal"]


def test_the_material_generation_is_bumped():
    assert '"M_FlightSimTilesBeauty": "8"' in SCRIPT


# -- the numbers ------------------------------------------------------------------------

def test_the_three_masks_agree_on_where_the_water_is():
    consts = {name: _constants(text) for name, text in TEXT.items()}
    for range_m in RANGES_M:
        for amount in (STORM["PuddleAmount"], 0.25, 1.0):
            masks = [_mask(consts[name], *GRID, NZ, amount, range_m) for name in NAMES]
            assert np.array_equal(masks[0], masks[1]) and np.array_equal(masks[1], masks[2]), (range_m, amount)


def test_the_normal_no_longer_flattens_the_old_mask():
    consts = _constants(TEXT["tiles_normal"])
    flat = np.ones_like(GRID[0])
    old = _old_normal_mask(*GRID, flat, STORM["PuddleAmount"])
    new = _mask(consts, *GRID, flat, STORM["PuddleAmount"], 10.0)
    assert old.mean() > 0.35, old.mean()              # generation 7's normal: ~41 % of the prairie flat
    assert new.mean() < 0.08, new.mean()              # generation 8: the colour's ~4 %
    # wherever the colour and roughness draw no water, the normal keeps all of its relief
    colour = _mask(_constants(TEXT["tiles_base_colour"]), *GRID, flat, STORM["PuddleAmount"], 10.0)
    assert np.all(new[colour == 0.0] == 0.0)
    assert np.sum((old > 0.0) & (new == 0.0)) > 0.3 * old.size   # the ground that gets its detail back
    # beyond the fade the normal is the detailed normal everywhere
    assert _mask(consts, *GRID, flat, STORM["PuddleAmount"], wb.PUDDLE_FADE_M).max() == 0.0
    assert _mask(consts, *GRID, flat, STORM["PuddleAmount"], 30000.0).max() == 0.0


def test_a_dry_card_keeps_the_detailed_normal_exactly():
    consts = _constants(TEXT["tiles_normal"])
    for preset in ("clear", "hazy", "overcast"):
        assert wb.tiles_parameters(preset, 0.0)["PuddleAmount"] == 0.0, preset
    detailed = RNG.normal(size=GRID[0].shape + (3,))
    detailed[..., 2] = np.abs(detailed[..., 2]) + 1.0
    detailed /= np.linalg.norm(detailed, axis=-1, keepdims=True)
    for range_m in RANGES_M:
        puddle = _mask(consts, *GRID, NZ, 0.0, range_m)
        assert puddle.max() == 0.0
        assert np.array_equal(_normal(detailed, puddle), _normal(detailed, np.zeros_like(puddle)))
        assert np.allclose(_normal(detailed, puddle), detailed)


def test_standing_water_is_still_flat_where_the_colour_draws_it():
    consts = _constants(TEXT["tiles_normal"])
    flat = np.ones_like(GRID[0])
    # the camera on the ground: the range fade is exactly 1, so a full puddle is weight 1
    puddle = _mask(consts, *GRID, flat, STORM["PuddleAmount"], 0.0)
    tilted = np.zeros(GRID[0].shape + (3,))
    tilted[..., 0] = 0.3
    tilted[..., 2] = 1.0
    tilted /= np.linalg.norm(tilted, axis=-1, keepdims=True)
    out = _normal(tilted, puddle)
    full = puddle >= 1.0
    assert full.any()
    assert np.allclose(out[full], [0.0, 0.0, 1.0])
    assert np.allclose(out[puddle == 0.0], tilted[puddle == 0.0])
