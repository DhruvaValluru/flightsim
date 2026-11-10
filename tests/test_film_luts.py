"""The film-stock LUTs (round 5, lane L2): the shipped .cube files match their
recorded sha256, neutral grey stays neutral within 2 % (no global tint: the
round-2 #02 blue cast must not come back through a LUT), each grade names a
stock that exists, the attribution file credits the generator, and the
UE strip converter maps an identity cube to the neutral strip within one
code value."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from core.capture.display import read_cube, tetrahedral
from core.scene import beauty_look as bl

REPO = Path(__file__).resolve().parents[1]
FILM = REPO / "assets" / "looks" / "film"
INDEX = json.loads((FILM / "film_luts.json").read_text(encoding="utf-8"))
LUTS = {entry["stock"]: entry for entry in INDEX["luts"]}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- the shipped files ------------------------------------------------------------------

def test_the_index_pins_the_generator_and_every_file():
    generator = INDEX["generator"]
    assert generator["name"] == "spectral_film_lut"
    assert generator["licence"] == "MIT"
    assert len(generator["commit"]) == 40 and generator["tag"] == "v0.18.14"
    assert generator["url"].startswith("https://github.com/JanLohse/spectral_film_lut")
    assert len(LUTS) >= 3
    for entry in LUTS.values():
        assert entry["licence"] == "CC0-1.0"
        assert entry["size"] == 33
        assert entry["grey_axis_neutralised"] is True
        assert "scene_recovery" in entry and "params" in entry and "negative" in entry
        assert "sRGB" in entry["space_in"] and "sRGB" in entry["space_out"]


@pytest.mark.parametrize("stock", sorted(LUTS))
def test_each_cube_matches_its_recorded_sha256(stock):
    entry = LUTS[stock]
    data = (FILM / entry["file"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"], stock
    head = data[:400].decode("ascii")
    assert "LUT_3D_SIZE 33" in head and "CC0-1.0" in head and "make_film_luts.py" in head


@pytest.mark.parametrize("stock", sorted(LUTS))
def test_neutral_grey_stays_neutral_within_two_percent(stock):
    """A grey ramp through the LUT: every output within 2 % of its channel
    mean (or one 8-bit code value in the toe, where 2 % of near-black is
    below the pixel's resolution). Black stays black, white stays white, and
    the curve climbs monotonically."""
    table, lo, hi = read_cube(FILM / LUTS[stock]["file"])
    greys = np.linspace(0.0, 1.0, 101)
    out = tetrahedral(np.stack([greys, greys, greys], axis=-1), table, lo, hi)
    mean = out.mean(axis=-1)
    dev = np.abs(out - mean[:, None]).max(axis=-1)
    tolerance = np.maximum(0.02 * mean, 1.0 / 255.0)
    worst = int(np.argmax(dev - tolerance))
    assert np.all(dev <= tolerance), (stock, greys[worst], out[worst])
    assert mean[0] <= 1.0 / 255.0 and mean[-1] >= 1.0 - 1.0 / 255.0
    assert np.all(np.diff(mean) >= -1e-9), stock
    # The stock reshapes the curve a little, it does not re-expose the frame:
    # mid-grey comes back within 0.06 of itself.
    assert abs(float(np.interp(0.5, greys, mean)) - 0.5) < 0.06, stock


def test_the_luts_are_not_identity_and_differ_from_each_other():
    colours = np.array([[0.8, 0.2, 0.2], [0.2, 0.8, 0.2], [0.2, 0.2, 0.8], [0.9, 0.7, 0.3]])
    outs = {}
    for stock, entry in LUTS.items():
        table, lo, hi = read_cube(FILM / entry["file"])
        outs[stock] = tetrahedral(colours, table, lo, hi)
        assert np.abs(outs[stock] - colours).max() > 0.02, stock
    names = sorted(outs)
    for a, b in zip(names, names[1:]):
        assert np.abs(outs[a] - outs[b]).max() > 0.01, (a, b)


# -- the look's choice ----------------------------------------------------------------

def test_every_grade_names_a_shipped_stock():
    assert set(bl.FILM_STOCKS) == set(bl.GRADE_NAMES)
    for grade in bl.GRADE_NAMES:
        record = bl.film_stock_for(grade)
        assert record["stock"] == bl.FILM_STOCKS[grade]
        assert (REPO / record["cube"]).is_file()
        assert record["sha256"] == LUTS[record["stock"]]["sha256"]
        assert record["grain_in_engine"] == bl.FILM_GRAIN_IN_ENGINE
    assert bl.film_stock_for(" Storm ")["stock"] == "kodak_vision3_250d_2383"
    assert bl.FILM_STOCKS["desert_noon"] != bl.FILM_STOCKS["golden_hour"]
    with pytest.raises(bl.BeautyLookError):
        bl.film_stock_for("teal_orange")
    assert "FILM_STOCKS" in bl.UNCALIBRATED


def test_the_plan_records_the_stock_and_the_host_ignores_it():
    plan = bl.plan_beauty_look(40.0, fps=30, width_px=1920)
    assert plan["film_stock"]["stock"] == bl.FILM_STOCKS[plan["grade"]]
    assert plan["film_stock"]["cube"].startswith("assets/looks/film/")
    storm = bl.plan_beauty_look(40.0, fps=30, width_px=1920, world_preset="storm")
    assert storm["film_stock"]["stock"] == bl.FILM_STOCKS["storm"]
    cpp = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
           "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
    assert "film_stock" not in cpp, "the host must not apply the LUT twice"


def test_the_attribution_file_credits_the_generator_and_the_tools():
    text = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    assert INDEX["generator"]["commit"] in text and "MIT" in text
    for entry in LUTS.values():
        assert entry["file"] in text, entry["file"]
    beauty_post = _load("beauty_post")
    for tool in beauty_post.TOOLS.values():
        assert tool["url"] in text, tool["url"]
        assert tool["sha256"] in text, tool["sha256"]


# -- the generator (its pure parts, no library) -----------------------------------------

def test_the_generator_neutralises_a_cast_and_keeps_the_curve():
    make = _load("make_film_luts")
    ramp = np.linspace(0.0, 1.0, 65)
    # A film whose greys are warm (red up, blue down) with a lifted toe.
    curve = 0.03 + 0.9 * ramp ** 1.1
    film_grey = np.stack([curve * 1.08, curve, curve * 0.9], axis=-1)
    nodes = np.stack([ramp, ramp, ramp], axis=-1)
    out, record = make.neutralise(film_grey.copy(), nodes, film_grey, ramp)
    assert record["grey_axis_neutralised"] and record["raw_grey_cast_max_pct"] > 5
    assert np.abs(out - out.mean(axis=-1, keepdims=True)).max() < 1e-9
    assert out[0].max() == 0.0 and out[-1].min() == 1.0
    x = make.inverse_aces_fit(make.aces_fit(np.array([0.05, 0.18, 1.0, 4.0])))
    assert np.allclose(x, [0.05, 0.18, 1.0, 4.0], rtol=1e-6)


def test_write_cube_is_the_order_the_reader_expects(tmp_path):
    make = _load("make_film_luts")
    n = 5
    r, g, b = np.meshgrid(*(np.linspace(0, 1, n),) * 3, indexing="ij")
    table = np.stack([r, g, b], axis=-1)
    path = tmp_path / "identity.cube"
    make.write_cube(table, path, "identity", "test")
    back, lo, hi = read_cube(path)
    probe = np.array([[0.1, 0.5, 0.9], [0.7, 0.2, 0.3]])
    assert np.allclose(tetrahedral(probe, back, lo, hi), probe, atol=1e-6)


# -- the UE strip -------------------------------------------------------------------------

def test_an_identity_cube_converts_to_the_neutral_strip_within_one_code_value(tmp_path):
    make = _load("make_film_luts")
    convert = _load("cube_to_ue_lut")
    n = 17
    r, g, b = np.meshgrid(*(np.linspace(0, 1, n),) * 3, indexing="ij")
    cube = tmp_path / "identity.cube"
    make.write_cube(np.stack([r, g, b], axis=-1), cube, "identity", "test")
    strip = convert.cube_to_strip(cube)
    assert strip.shape == (16, 256, 3) and strip.dtype == np.uint8
    neutral = convert.neutral_strip()
    assert np.abs(strip.astype(int) - neutral.astype(int)).max() <= 1
    # The layout: red across a tile, green down, blue by tile.
    assert tuple(neutral[0, 0]) == (0, 0, 0)
    assert tuple(neutral[0, 15]) == (255, 0, 0)
    assert tuple(neutral[15, 0]) == (0, 255, 0)
    assert tuple(neutral[0, 240]) == (0, 0, 255)
    png = convert.write_strip(cube, tmp_path / "strip.png")
    from PIL import Image

    with Image.open(png) as image:
        assert image.size == (256, 16)


def test_a_real_stock_strip_follows_its_cube(tmp_path):
    convert = _load("cube_to_ue_lut")
    stock = LUTS[bl.FILM_STOCKS["golden_hour"]]
    table, lo, hi = read_cube(FILM / stock["file"])
    strip = convert.cube_to_strip(FILM / stock["file"])
    expect = tetrahedral(convert.strip_nodes(), table, lo, hi) * 255.0
    assert np.abs(strip.astype(float) - expect).max() <= 0.5 + 1e-6
