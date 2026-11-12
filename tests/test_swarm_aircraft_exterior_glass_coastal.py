"""Source-level checks for swarm lane aircraft_exterior.glass.coastal.

These run on the Mac and check the bake's maths and files. They never stand in
for a Windows render or the pixel gate (CLAUDE.md, 2026-11-12).
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

LANE = Path(__file__).resolve().parents[1] / "swarm/lanes/aircraft_exterior/glass/coastal"
OUT = LANE / "out"

_spec = importlib.util.spec_from_file_location("swarm_glass_coastal_bake", LANE / "bake_glass.py")
bake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bake)

DOC = json.loads((OUT / "glass_coastal.json").read_text())
PROV = json.loads((LANE / "PROVENANCE.json").read_text())


def _img(name):
    return np.asarray(Image.open(OUT / name).convert("RGB"), dtype=np.float64)


def test_fresnel_normal_incidence_and_grazing():
    r, single, t = bake.slab_terms(np.array([1.0, 1e-4]))
    f0 = ((bake.GLASS_IOR - 1) / (bake.GLASS_IOR + 1)) ** 2
    assert single[0] == pytest.approx(f0, abs=1e-9)
    assert f0 < r[0] < 2 * f0            # two faces, less the tint absorbed between them
    assert r[1] > 0.99 and t[1] < 0.01


def test_slab_conserves_energy_and_reflectance_rises_to_grazing():
    c = np.linspace(0.01, 1.0, 200)
    r, single, t = bake.slab_terms(c)
    assert np.all(r + t <= 1.0 + 1e-9)
    assert np.all(np.diff(single) <= 1e-9)   # one face: falls as cos rises
    # the slab is not strictly monotone (tint absorption dims the back-face
    # bounce toward grazing) but grazing still far outshines face-on
    assert r[0] > 5 * r[-1] and r[c < 0.3].min() > r[-1]


def test_lut_file_matches_the_maths():
    lut = _img("T_GlassFresnel_LUT.png")[0] / 255.0
    assert lut.shape == (bake.LUT_W, 3)
    c = (np.arange(bake.LUT_W) + 0.5) / bake.LUT_W
    r, single, t = bake.slab_terms(c)
    assert np.abs(lut[:, 0] ** 2 - r).max() < 0.01
    assert np.abs(lut[:, 1] ** 2 - single).max() < 0.01
    assert np.abs(lut[:, 2] - t).max() < 0.004


@pytest.mark.parametrize("w", [64, 128, 256])
def test_env_strip_is_a_low_sun_coast(w):
    env = _img(f"T_GlassEnv_{w}.png")
    h = w // 2
    assert env.shape == (h, w, 3)
    assert env.max() < 255 and env.min() > 0             # nothing clipped, nothing black
    horizon = h // 2 - 1
    assert env[horizon, w // 2].sum() > env[horizon, 0].sum()   # sun side brighter
    zen = env[0].mean(axis=0)
    assert zen[2] > zen[0]                               # zenith is blue
    hz = env[horizon, w // 2]
    assert hz[0] > hz[2]                                 # sun-side horizon is warm
    assert env[h - 1].mean() < env[horizon].mean()       # sea at nadir darker than the haze


@pytest.mark.parametrize("s", [256, 512, 1024])
def test_micro_tiles(s):
    n = _img(f"T_GlassMicro_N_{s}.png") / 255.0
    f = _img(f"T_GlassFilm_M_{s}.png") / 255.0
    assert n.shape == f.shape == (s, s, 3)
    assert np.abs(n[..., :2].mean(axis=(0, 1)) - 0.5).max() < 0.01   # flat on average
    assert n[..., 2].min() > 0.85                                   # no folded normals
    # tileable: the wrap seam is no rougher than an interior column / row
    salt = f[..., 1]
    seam_x = np.abs(salt[:, 0] - salt[:, -1]).mean()
    inner_x = np.abs(np.diff(salt, axis=1)).mean()
    seam_y = np.abs(salt[0] - salt[-1]).mean()
    assert seam_x < 4 * inner_x + 0.01 and seam_y < 4 * inner_x + 0.01
    assert 0.03 < salt.mean() < 0.20                                # mostly clear pane
    assert 0.5 < (salt == 0).mean() < 0.7


def test_albedo_stays_in_range_and_tint_is_the_repository_value():
    lo, hi = bake.ALBEDO_RANGE
    for cov in (0.0, 0.5, 1.0):
        assert all(lo <= a <= hi for a in bake.effective_albedo(cov))
    look = (LANE.parents[3].parent / "scripts/aircraft_look.py").read_text()
    assert "GLASS_IOR = 1.49" in look
    assert '"glass": {"GlassTint": (0.018, 0.022, 0.026, 1.0)}' in look
    assert 'THIN_VECTORS = {"Transmittance": (0.80, 0.84, 0.82, 1.0)}' in look


def test_predicted_canopy_is_never_darker_than_todays_opaque_glass():
    # arithmetic on the bake, NOT a render: the pixel gate decides on Windows
    base = DOC["current_opaque_canopy_srgb_luma_no_reflection"]
    pred = DOC["predicted_opaque_canopy_srgb_luma_by_cos"]
    values = [pred[k] for k in sorted(pred, reverse=True)]          # face-on -> grazing
    assert all(v >= base for v in values)
    assert values == sorted(values)
    assert values[-1] < 250


def test_tiers():
    tiers = DOC["tiers"]
    assert sorted(tiers) == ["0", "1", "2", "3"]
    mb = [tiers[k]["est_vram_mb"] for k in sorted(tiers)]
    assert mb == sorted(mb) and mb[0] < 0.1 and mb[-1] < 8
    assert tiers["0"]["blend"] == tiers["1"]["blend"] == "opaque"   # label-safe, no translucency
    assert tiers["0"]["micro"] == 0
    for k, t in tiers.items():
        assert (OUT / f"T_GlassEnv_{t['env_w']}.png").exists()
        if t["micro"]:
            assert (OUT / f"T_GlassMicro_N_{t['micro']}.png").exists()


def test_provenance_hashes_and_licences():
    assert PROV["fetched_assets"] == [] and PROV["vendored_code"] == []
    assert set(PROV["outputs"]) == set(DOC["files"])
    for name, row in PROV["outputs"].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == row["sha256"]
    text = json.dumps(PROV).lower()
    assert "noncommercial" not in text and "-nc" not in text


def test_nothing_is_claimed_measured():
    assert DOC["measured"] is False and DOC["visual_only"] is True
    assert PROV["measured"] is False
    notes = (LANE / "INTEGRATION.md").read_text()
    assert "UNMEASURED" in notes and "render_ue_scenario.ps1" in notes


def test_rebake_reproduces_the_closed_form_textures(tmp_path):
    bake.bake(tmp_path)
    for name in ("T_GlassFresnel_LUT.png", "T_GlassEnv_64.png"):
        a = np.asarray(Image.open(tmp_path / name), dtype=np.int16)
        b = np.asarray(Image.open(OUT / name), dtype=np.int16)
        assert np.abs(a - b).max() <= 1


def _frame(path, canopy, body):
    rng = np.random.default_rng(1)
    img = np.full((60, 80, 3), body, dtype=np.float64)
    img[10:30, 20:60] = canopy(rng)
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(path)
    return str(path)


def test_gate_arithmetic(tmp_path):
    flat = lambda rng: 40.0
    lit = lambda rng: np.linspace(45, 150, 40)[None, :, None] * np.ones((20, 1, 3))
    ref = _frame(tmp_path / "ref.png", flat, 120)
    good = _frame(tmp_path / "good.png", lit, 120)
    dark = _frame(tmp_path / "dark.png", lit, 100)
    black = _frame(tmp_path / "black.png", lambda rng: np.where(rng.random((20, 40, 1)) < 0.5, 2.0, 140.0), 120)
    rois = dict(canopy_roi=[20, 10, 60, 30], aircraft_roi=[0, 0, 80, 60])
    assert bake.measure(ref, good, **rois)["pass"]
    assert not bake.measure(ref, ref, **rois)["checks"]["canopy_contrast_gain"]
    assert not bake.measure(ref, dark, **rois)["checks"]["no_dark_aircraft_regression"]
    assert not bake.measure(ref, black, **rois)["checks"]["canopy_not_blacked_out"]
