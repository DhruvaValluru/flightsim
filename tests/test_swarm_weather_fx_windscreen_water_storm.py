"""Source-level checks for swarm lane weather_fx.windscreen_water.storm.

These run on the Mac and check the bake's maths and files. They never stand in
for a Windows render or the pixel gate (CLAUDE.md, 2026-11-12).
"""
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm/lanes/weather_fx/windscreen_water/storm"
BAKED = LANE / "baked"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, LANE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load("swarm_wsw_storm_generate", "generate.py")
gate = _load("swarm_wsw_storm_measure", "measure_glass.py")
DOC = json.loads((BAKED / "windscreen_water_storm.json").read_text())
PROV = json.loads((LANE / "PROVENANCE.json").read_text())


def _tex(name):
    return np.asarray(Image.open(BAKED / name), dtype=np.float64) / 255.0


def test_face_optics_snell_fresnel_and_tir():
    tan_d, trans = gen.face_optics(np.array([0.0, 0.5, 0.7499, 0.76, 1.0]))
    assert tan_d[0] == 0.0
    assert trans[0] == pytest.approx(1 - ((gen.N_WATER - 1) / (gen.N_WATER + 1)) ** 2, abs=1e-12)
    assert tan_d[1] == pytest.approx(math.tan(math.asin(0.5 * 1.333) - math.asin(0.5)), abs=1e-12)
    assert np.all(np.diff(tan_d[:3]) > 0) and np.all(np.diff(trans[:3]) < 0)
    assert trans[3] == 0.0 and trans[4] == 0.0 and tan_d[4] == pytest.approx(gen.TAN_MAX)
    assert gen.TAN_MAX == pytest.approx(math.sqrt(gen.N_WATER ** 2 - 1), abs=1e-12)


def test_cap_holds_the_drop_volume():
    for d in (1.0, 2.5, 6.0):
        a = gen.cap_base_radius_mm(d)
        assert gen.cap_volume_mm3(a) == pytest.approx(math.pi * d ** 3 / 6, rel=1e-12)
    # a hemisphere of the same volume: a^3 = D^3 / 4
    assert gen.cap_base_radius_mm(2.0, 90.0) == pytest.approx((8 / 4) ** (1 / 3), rel=1e-12)


def test_diameters_follow_truncated_marshall_palmer():
    lam = gen.marshall_palmer_lambda(gen.RATE_MMH)
    assert lam == pytest.approx(4.1 * 25 ** -0.21)
    assert gen.sample_diameter_mm(0.0, lam) == pytest.approx(gen.D_MIN_MM)
    assert gen.sample_diameter_mm(1.0, lam) == pytest.approx(gen.D_MAX_MM)
    u = (np.arange(20000) + 0.5) / 20000
    mean = np.mean([gen.sample_diameter_mm(x, lam) for x in u])
    a, b = gen.D_MIN_MM, gen.D_MAX_MM
    ea, eb = math.exp(-lam * a), math.exp(-lam * b)
    assert mean == pytest.approx(((a + 1 / lam) * ea - (b + 1 / lam) * eb) / (ea - eb), rel=1e-4)


def test_constants_match_the_projects_rain_field():
    from core.scene import rain_field
    assert gen.V_SHED_MPS == rain_field.V_SHED_MPS
    assert gen.RUNOFF_GAIN == rain_field.RUNOFF_GAIN
    assert gen.WINDSHIELD_COS == rain_field.WINDSHIELD_COS
    assert (gen.D_MIN_MM, gen.D_MAX_MM) == (rain_field.D_RENDER_MIN_MM, rain_field.D_MAX_MM)
    assert gen.splitmix64(1) == rain_field.splitmix64(1)
    w = rain_field.windshield(476.0, 51.44)
    wet = gen.host_wet(51.44, w["impinge_per_m2_s"], 5.0, DOC["drops"]["mean_cap_area_m2"],
                       DOC["drops"]["density_to_cover"])
    assert wet["runoff_mps"] == pytest.approx(w["runoff_mps"], abs=1e-3)


def test_drops_do_not_overlap_and_cover_the_target():
    rng = gen.Rng(gen.SEED)
    xs, ys, rs = gen.place_drops(rng, gen.marshall_palmer_lambda(gen.RATE_MMH))
    assert len(rs) == DOC["drops"]["count"]
    cover = float(np.sum(math.pi * rs * rs)) / gen.TILE_MM ** 2
    assert gen.MAX_DROP_COVER <= cover < gen.MAX_DROP_COVER + 0.01
    dx = np.abs(xs[:, None] - xs[None, :]); dx = np.minimum(dx, gen.TILE_MM - dx)
    dy = np.abs(ys[:, None] - ys[None, :]); dy = np.minimum(dy, gen.TILE_MM - dy)
    gap = np.sqrt(dx * dx + dy * dy) - (rs[:, None] + rs[None, :])
    np.fill_diagonal(gap, 1.0)
    assert gap.min() > 0.0


@pytest.mark.parametrize("n", gen.SIZES)
def test_textures_are_the_baked_optics(n):
    d, r = _tex(f"T_WSDrops_{n}.png"), _tex(f"T_WSRivulets_{n}.png")
    assert d.shape == r.shape == (n, n, 4)
    off = d[..., 3] == 0.0
    assert 0.5 < off.mean() < 0.72                       # 1 - cover, less the filtered edges
    assert np.abs(d[off][:, :2] - 0.5).max() < 0.003 and d[off][:, 2].min() == 1.0
    on = d[..., 3] > 0.2
    assert d[on][:, 2].min() >= gen.RIM_FLOOR - 0.003
    # the deflection points at the drop's axis, so it sums to nothing over the tile
    assert abs((d[..., 0] - 0.5).mean()) < 0.003 and abs((d[..., 1] - 0.5).mean()) < 0.003
    assert r[..., 3].max() <= 1.0 and 0.1 < (r[..., 3] > 0.2).mean() < 0.45
    assert r[r[..., 3] == 0.0][:, 1].min() == 1.0


def test_rivulet_tile_is_periodic_and_tracks_keep_one_offset():
    r = gen.bake_rivulets(gen.rivulet_tracks(gen.Rng(7)), 256)
    # the bake is evaluated at texel centres of a periodic function: rows 0 and n-1 are neighbours
    assert np.abs(r[0, :, 3] - r[-1, :, 3]).mean() < 0.05
    offsets = {t["offset"] for t in gen.rivulet_tracks(gen.Rng(7))}
    inside = r[..., 3] > 0
    assert set(np.unique(r[inside][:, 2])) <= offsets


def test_shader_twin_density_trail_and_inversion():
    d, r = _tex("T_WSDrops_256.png"), _tex("T_WSRivulets_256.png")
    v = ((np.arange(256) + 0.5) / 256)[:, None] * np.ones((1, 256))
    lens = gen.lens_scale()
    du, dv, mask, shade = gen.shade_texels(d, r, v, 0.0, (0.0, 0.0, 0.0, 0.25), lens, 16 / 9)
    assert mask.max() == 0.0 and np.all(shade == 1.0) and np.all(du == 0.0) and np.all(dv == 0.0)
    covers = [gen.shade_texels(d, r, v, 0.0, (x, 0.0, 0.0, 0.25), lens, 1.0)[2].mean()
              for x in (0.1, 0.3, 0.5, 0.75)]
    assert np.all(np.diff(covers) > 0) and covers[-1] == pytest.approx(
        DOC["drops"]["density_to_cover"][-1][1], abs=1e-4)
    # a track's wet share is its trail's share of the tile, and the head moves with time
    full = gen.shade_texels(d, r, v, 0.0, (0.0, 0.75, 1.0, 1.0), lens, 1.0)[2]
    part = gen.shade_texels(d, r, v, 0.0, (0.0, 0.75, 1.0, 0.25), lens, 1.0)[2]
    later = gen.shade_texels(d, r, v, 0.37, (0.0, 0.75, 1.0, 0.25), lens, 1.0)[2]
    assert part.sum() < 0.3 * full.sum() and np.abs(later - part).max() > 0.5
    assert later.sum() == pytest.approx(part.sum(), rel=0.05)
    # a drop is a converging lens: above its centre it looks further down the screen
    _, dv, mask, _ = gen.shade_texels(d, r, v, 0.0, (0.75, 0.0, 0.0, 0.25), lens, 1.0)
    assert np.abs(dv).max() <= lens + 1e-9
    xs, ys, rs = gen.place_drops(gen.Rng(gen.SEED), gen.marshall_palmer_lambda(gen.RATE_MMH))
    i = int(np.argmax(rs)); px = 256 / gen.TILE_MM
    cx, cy, a = int(xs[i] * px), int(ys[i] * px), rs[i] * px
    assert dv[int(cy - 0.5 * a) % 256, cx % 256] > 0 > dv[int(cy + 0.5 * a) % 256, cx % 256]


def test_hlsl_is_the_twin_and_has_no_loop():
    text = (LANE / "windshield_baked.hlsl").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("//"))
    assert code.count(f"* {gen.EDGE_GAIN:.1f})") == 2
    assert not re.search(r"\b(for|while|if)\b|asuint|Pcg", code)
    assert f"{DOC['geometry']['lens_scale']:.6f}" in text
    assert "return float4(du / Aspect, dv, max(dropOn, rivOn), shade);" in code


def test_host_wet_follows_the_shedding_law():
    table, area = DOC["drops"]["density_to_cover"], DOC["drops"]["mean_cap_area_m2"]
    still = gen.host_wet(10.0, 3000.0, 5.0, area, table)
    fast = gen.host_wet(60.0, 3000.0, 5.0, area, table)
    assert still["rivulet_density"] == 0.0 and still["head_rate_tiles_per_s"] == 0.0
    assert fast["rivulet_density"] > 0 and fast["drop_density"] < still["drop_density"]
    assert fast["runoff_mps"] == pytest.approx(0.35 * (60 - 22))
    assert gen.host_wet(60.0, 0.0, 5.0, area, table)["drop_density"] == 0.0
    assert gen.host_wet(60.0, 1e9, 5.0, area, table)["rivulet_density"] <= gen.A_SPAN


def test_gate_metric_rises_with_drop_contrast_and_holds_its_thresholds():
    flat = Image.new("RGB", (320, 180), (96, 98, 102))
    assert gate.bandpass_rms(flat) == 0.0
    arr = np.full((180, 320, 3), 97, dtype=np.uint8)
    arr[40:46, 60:66] = 30
    assert gate.bandpass_rms(Image.fromarray(arr)) > 0.5
    ref = {"glass_bandpass_rms": 2.0, "p90_luma": 93.0, "device_loss_lines": 0}
    good = {"glass_bandpass_rms": 2.6, "p90_luma": 95.0, "device_loss_lines": 0}
    assert gate.verdict(good, ref)["pass"]
    assert not gate.verdict({**good, "glass_bandpass_rms": 2.2}, ref)["pass"]
    assert not gate.verdict({**good, "glass_bandpass_rms": 20.0}, ref)["pass"]
    assert not gate.verdict({**good, "p90_luma": 110.0}, ref)["pass"]
    assert not gate.verdict({**good, "device_loss_lines": 1}, ref)["pass"]


def test_provenance_pins_every_baked_file_and_fetches_nothing():
    assert PROV["fetched_assets"] == [] and PROV["vendored"] == []
    listed = {g["path"]: g["sha256"] for g in PROV["generated"]}
    on_disk = {f"baked/{p.name}" for p in BAKED.iterdir()}
    assert set(listed) == on_disk
    for path, digest in listed.items():
        assert hashlib.sha256((LANE / path).read_bytes()).hexdigest() == digest, path
    for name, digest in DOC["files"].items():
        assert listed[f"baked/{name}"] == digest
    assert "UNMEASURED" in PROV["status"] and DOC["visual_only"] is True
    for source in PROV["sources"]:
        assert "non-commercial" not in source["licence"].lower()


def test_bake_is_deterministic(tmp_path):
    gen.main(["--out", str(tmp_path)])
    for name, digest in DOC["files"].items():
        if name.endswith(("_256.png", "_512.png")):
            assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
