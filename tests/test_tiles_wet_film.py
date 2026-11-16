"""Tiles generation 11 (2026-11-15): wet ground in #09 / #10 drew near black. Live in the
editor, the far wet ground went from 13 to 40 (8-bit, sky band 66) when the wet
roughness was dropped from generation 7's ROUGHNESS_WET_FAR to a mirror: the far
widening hid the sky at grazing angles. Generation 11 (WET_GROUND_MODEL 1): Lekner & Dorf
1988's water-film darkening and the wet lobe kept at ROUGHNESS_WET with a specular AA
term, opt-in (FLIGHTSIM_WET_GROUND=film) until the Windows A/B; the default
WET_GROUND_MODEL 0 is generation 10's law."""
import re
from pathlib import Path

import numpy as np

from core.scene import world_beauty as wb

ROOT = Path(__file__).resolve().parents[1]
SHADERS = ROOT / "assets" / "shaders" / "world"
ROUGH = (SHADERS / "tiles_roughness.hlsl").read_text(encoding="utf-8")
BASE = (SHADERS / "tiles_base_colour.hlsl").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts" / "ue_create_materials.py").read_text(encoding="utf-8")


def _consts(text):
    return {k: float(v) for k, v in re.findall(r"const float (\w+) = ([0-9.]+);", text)}


def test_lekner_dorf_film_matches_measured_wet_albedo():
    # r_i = 1 - (1 - r_e) / n^2 for water (n 1.333, r_e 0.066): 0.474.
    assert abs(wb.WET_FILM_RI - 0.474) < 1e-9
    ratio = {a: wb.wet_film_albedo(a) / a for a in (0.08, 0.20, 0.35)}
    assert abs(ratio[0.08] - 0.511) < 0.005    # wet asphalt
    assert abs(ratio[0.20] - 0.543) < 0.005    # wet soil
    assert abs(ratio[0.35] - 0.589) < 0.005    # pale gravel road
    # Measured order at saturation 0.5-0.7 (Twomey 1986; Lobell & Asner 2002); darker
    # surfaces darken more in ratio, never to black.
    assert all(0.5 <= r <= 0.7 for r in ratio.values())
    assert ratio[0.08] < ratio[0.20] < ratio[0.35]


def test_shaders_carry_the_constants():
    base, rough = _consts(BASE), _consts(ROUGH)
    assert base["WET_FILM_RE"] == wb.WET_FILM_RE and base["WET_FILM_RI"] == wb.WET_FILM_RI
    assert rough["WET_SPEC_AA_MAX"] == wb.WET_SPEC_AA_MAX
    assert "(1.0 - WET_FILM_RE) * (1.0 - WET_FILM_RI) * c / (1.0 - WET_FILM_RI * saturate(c))" in BASE


def _roughness(model, wetness, range_m, kernel=0.0):
    """The shader's wet roughness (no puddle, micro 0)."""
    far = 0.0 if model else min(range_m / wb.WET_SPEC_FADE_M, 1.0)
    r_wet = wb.ROUGHNESS_WET + (wb.ROUGHNESS_WET_FAR - wb.ROUGHNESS_WET) * far
    r_wet = (r_wet ** 4 + (min(kernel, wb.WET_SPEC_AA_MAX) if model else 0.0)) ** 0.25
    return wb.ROUGHNESS_DRY + (r_wet - wb.ROUGHNESS_DRY) * wetness


def test_far_wet_ground_keeps_the_sky_lobe():
    # Generation 10: 0.55 beyond 2.5 km (the black). Generation 11: 0.25 on a flat field.
    assert _roughness(0, 1.0, 5000.0) == wb.ROUGHNESS_WET_FAR
    assert abs(_roughness(1, 1.0, 5000.0) - wb.ROUGHNESS_WET) < 1e-12
    # Sub-pixel facets (normal varying pixel to pixel) widen it, bounded by the clamp.
    worst = _roughness(1, 1.0, 5000.0, kernel=10.0)
    assert abs(worst - (wb.ROUGHNESS_WET ** 4 + wb.WET_SPEC_AA_MAX) ** 0.25) < 1e-12
    assert 0.35 < worst < 0.42   # a sheen, never generation 7's 0.55


def test_dry_and_legacy_are_unchanged():
    for model in (0, 1):
        assert _roughness(model, 0.0, 800.0, kernel=1.0) == wb.ROUGHNESS_DRY
    assert "float3 wetLegacy = c * (1.0 - WET_DARKENING * saturate(Wetness));" in BASE
    assert "WET_GROUND_MODEL > 0.5 ? lerp(c, film, saturate(Wetness)) : wetLegacy;" in BASE
    assert "float kernel = film ? min(" in ROUGH and "float farSpec = film ? 0.0 : " in ROUGH


def test_script_wires_the_switch_and_bumps_the_generation():
    assert int(re.search(r'"M_FlightSimTilesBeauty": "(\d+)"', SCRIPT).group(1)) >= 11
    # opt-in, default off until the Windows A/B on #09 / #10 / #15 (review)
    assert 'WET_GROUND_CONST = "const float WET_GROUND_MODEL = 0.0;"' in SCRIPT
    assert '"const float WET_GROUND_MODEL = 1.0;"' in SCRIPT
    assert 'WET_GROUND_ENV = "FLIGHTSIM_WET_GROUND"' in SCRIPT and '"-film-wet"' in SCRIPT
    assert '== "film" else 0.0' in SCRIPT and "assert code.count(WET_GROUND_CONST) == 1" in SCRIPT
    assert wb.WET_GROUND_MODEL == 0.0
    for hlsl in (BASE, ROUGH):
        assert hlsl.count("const float WET_GROUND_MODEL = 0.0;") == 1


def test_detail_consts_are_static_for_metal():
    for name in ("tiles_detail_surface", "tiles_detail_normal"):
        text = (SHADERS / f"{name}.hlsl").read_text(encoding="utf-8")
        assert not re.search(r"^const ", text, re.M), name
        assert "static const float DETAIL_TEXEL_PX = 2.5;" in text
