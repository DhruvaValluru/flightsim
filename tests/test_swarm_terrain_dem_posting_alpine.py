"""Source-level checks for the alpine DEM-posting lane (Mac).

They check the posting arithmetic, the committed bake against PROVENANCE and
against surveyed summits, and the pixel gate's arithmetic on synthetic images.
They are NOT a render or pixel result: that is measured on the Windows laptop
(see the lane's INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "terrain" / "dem_posting" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_dem_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_dem_posting")
gate = _load("measure_dem_posting")
EYE = (bake.CENTRE_LAT - 0.02, bake.CENTRE_LON, bake.EYE_ALT_M)   # 2.2 km south of the summit
HEADING, PITCH = 0.0, -8.0


@pytest.fixture(scope="module")
def ref():
    return gate.load_reference()


@pytest.fixture(scope="module")
def table(ref):
    return gate.skyline_table(ref, *EYE)


def test_ladder_arithmetic_and_committed_json():
    plan = bake.ladder()
    assert plan["camera"]["hfov_deg"] == pytest.approx(54.43, abs=0.01)
    # a 30 m post is exactly one pixel where range * ifov = 30 m
    assert bake.pixel_footprint_m(bake.subpixel_range_m(30.0)) == pytest.approx(30.0)
    assert plan["subpixel_beyond_km"]["glo30_30m"] == pytest.approx(37.3, abs=0.1)
    assert 250.0 < plan["horizon_km"]["sea_level"] < 290.0
    committed = json.loads((LANE / "alpine_dem_posting.json").read_text())
    assert {k: v for k, v in committed.items() if k != "rings"} == json.loads(json.dumps(plan))
    sse = [t["google_tiles_sse"] for t in plan["tiers"]]
    vram = [t["est_vram_mb"] for t in plan["tiers"]]
    assert sse == sorted(sse, reverse=True) and vram == sorted(vram)
    assert vram[0] < 491 * 0.5          # tier 0 estimate leaves half the 491 MB budget free


def test_committed_files_match_provenance():
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["label"] == "visual-only"
    for entry in provenance["generated"]:
        assert hashlib.sha256((LANE / entry["file"]).read_bytes()).hexdigest() == entry["sha256"], entry["file"]
    tiles = json.loads((LANE / "glo90_tiles.json").read_text())
    assert len(tiles) == len(bake.TILE_LATS) * len(bake.TILE_LONS)
    assert all(t.get("missing") or len(t["sha256"]) == 64 for t in tiles)
    for source in provenance["sources"]:
        assert source["licence"] and "non-commercial" not in source["licence"].lower()


def test_ring_layers_are_consistent():
    files = json.loads((LANE / "alpine_dem_posting.json").read_text())["rings"]["files"]
    for t, (_sse, _cache, n_r, n_az) in bake.TIERS.items():
        raw = (LANE / f"alpine_far_ring_t{t}.bin").read_bytes()
        assert len(raw) == n_r * n_az * 8 and files[f"alpine_far_ring_t{t}.bin"]["n_az"] == n_az
        h = np.frombuffer(raw, dtype="<u2", count=2 * n_r * n_az).reshape(2, n_r, n_az)
        assert np.all(h[1] <= h[0])
        assert 4700 < h[0].max() * bake.HEIGHT_SCALE_M < 4830     # Mont Blanc is the highest thing in range


@pytest.mark.parametrize("name,lat,lon,surveyed", [
    ("Dufourspitze", 45.93692, 7.86675, 4634.0),
    ("Dom", 46.09371, 7.85881, 4545.0),
    ("Mont Blanc", 45.83262, 6.86517, 4806.0),
])
def test_reference_grid_holds_the_surveyed_summits(ref, name, lat, lon, surveyed):
    north = math.radians(lat - ref["lat"]) * gate.EARTH_R_M
    east = math.radians(lon - ref["lon"]) * gate.EARTH_R_M * math.cos(math.radians(ref["lat"]))
    i = int(np.argmin(np.abs(np.log(ref["r"] / math.hypot(north, east)))))
    j = int((math.degrees(math.atan2(east, north)) % 360.0) / 360.0 * ref["h"].shape[1])
    near = ref["h"][max(i - 2, 0):i + 3, [(j + dj) % 4096 for dj in range(-4, 5)]].max()
    # A 90 m DSM cell averages a sharp summit: baked 2026-11-12 these read 106, 82
    # and 13 m low. The bound checks position and identity, not summit accuracy.
    assert 0.0 <= surveyed - near < 120.0, (name, near)


def _synthetic(table_row, w=640, h=360):
    """Sky 0.8 above the given skyline, ground 0.3 with a soft ramp below."""
    az, el = gate.pixel_angles(w, h, 54.43, HEADING, PITCH)
    return np.where(el > gate.lookup(table_row, az), 0.8, 0.3)


def test_skyline_table_grows_with_range(table):
    assert np.all(np.diff(table, axis=0) >= 0)
    assert table[-1].max() < 5.0 and table[-1].min() > -30.0


def test_full_skyline_is_matched_and_far(table):
    out = gate.horizon_metrics(_synthetic(table[-1]), table, 54.43, HEADING, PITCH)
    assert out["skyline_match_fraction"] > 0.95
    assert out["horizon_range_km"] > 20.0


def test_truncated_terrain_reads_as_a_shorter_horizon(table):
    cut = int(np.searchsorted(gate.RANGE_EDGES_M, 15_000.0))
    full = gate.horizon_metrics(_synthetic(table[-1]), table, 54.43, HEADING, PITCH)
    short = gate.horizon_metrics(_synthetic(table[cut - 1]), table, 54.43, HEADING, PITCH)
    assert short["horizon_range_km"] <= gate.RANGE_EDGES_M[cut] / 1e3 + 0.05
    assert short["horizon_range_km"] < full["horizon_range_km"]
    assert short["skyline_match_fraction"] < full["skyline_match_fraction"]
    base = {**short, "detail_px": 2.0}
    assert not gate.verdict(base, {**short, "detail_px": 1.0}, 2.0)["pass"]


def _magnified(k, n=256, seed=3):
    rng = np.random.default_rng(seed)
    small = rng.random((n // k + 2, n // k + 2))
    x = np.arange(n) / k
    i, f = x.astype(int), x - x.astype(int)
    rows = small[i] * (1 - f)[:, None] + small[i + 1] * f[:, None]
    return rows[:, i] * (1 - f)[None, :] + rows[:, i + 1] * f[None, :]


def test_detail_px_tracks_texture_magnification():
    d1, d4, d8 = (gate.detail_px(_magnified(k)) for k in (1, 4, 8))
    assert d1 == 1.0
    assert 2.0 <= d4 <= 6.0
    assert d8 > d4 * 1.4


def test_verdict_thresholds():
    base = {"horizon_range_km": 60.0, "skyline_match_fraction": 0.5, "detail_px": 2.0}
    good = {"horizon_range_km": 140.0, "skyline_match_fraction": 0.9, "detail_px": 1.8}
    assert gate.verdict(base, good, 2.0)["pass"]
    assert not gate.verdict(base, {**good, "horizon_range_km": 100.0}, 2.0)["pass"]
    assert not gate.verdict(base, {**good, "detail_px": 3.5}, 2.0)["pass"]
    assert gate.verdict(base, {**good, "detail_px": 3.5}, 4.0)["pass"]
