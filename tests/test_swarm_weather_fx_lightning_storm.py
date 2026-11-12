"""weather_fx.lightning.storm: what is checkable on the Mac.

The APSF bake's arithmetic, its determinism, the files' hashes, agreement with
the project's own lightning and storm look, and the pixel gate's arithmetic on
synthetic images. No test here stands in for a rendered frame.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm/lanes/weather_fx/lightning/storm"
BAKED = LANE / "baked"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"swarm_wx_lightning_storm_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate")
measure = _load("measure_frame")
PLAN = gen.build()
ON_DISK = json.loads((BAKED / "lightning_glow.json").read_text())


@pytest.mark.parametrize("t", [1.05, 2.0, 6.5, 16.0])
def test_series_integrates_to_its_closed_form_norm(t):
    theta = np.linspace(0.0, math.pi, 20001)
    numeric = 2.0 * math.pi * np.trapezoid(gen.apsf(t, theta) * np.sin(theta), theta)
    assert numeric == pytest.approx(gen.sphere_norm(t), rel=1e-6)


def test_series_has_converged_and_is_not_negative():
    theta = np.linspace(0.0, math.pi, 2001)
    for t in (gen.T_MIN, 4.0):
        full = gen.legendre.legval(np.cos(theta), gen.apsf_coefficients(t))
        half = gen.legendre.legval(np.cos(theta), gen.apsf_coefficients(t, terms=gen.SERIES_TERMS // 2))
        assert np.max(np.abs(full - half)) <= 1e-4 * full.max()
        assert full.min() > -1e-6 * full.max()


def test_kernels_fall_with_angle_and_scatter_no_more_than_was_removed():
    for name, kernel in PLAN["_kernels"].items():
        assert kernel.shape == (gen.LUT_H, gen.LUT_W)
        assert np.all(kernel > 0.0), name
        assert np.all(np.diff(kernel, axis=1) <= 1e-12), name
    for t in (gen.T_MIN, 3.0, 10.0):
        assert 0.0 < gen.captured_fraction(t, gen.PHI_MAX_RAD) < 1.0


def test_luts_on_disk_decode_to_the_kernels():
    for name in ("line", "point"):
        meta = ON_DISK["lut"][name]
        image = Image.open(BAKED / meta["file"])
        assert image.size == (gen.LUT_W, gen.LUT_H)
        texels = np.asarray(image, dtype=np.uint16)
        assert np.array_equal(texels, PLAN["_encoded"][name]["texels"])
        back = gen.decode(texels, meta["ln_min"], meta["ln_max"])
        step = (meta["ln_max"] - meta["ln_min"]) / 65535.0
        assert np.max(np.abs(np.log(back) - np.log(PLAN["_kernels"][name]))) <= 0.51 * step


def test_bake_is_deterministic_and_matches_the_json_on_disk():
    again = gen.build()
    for key in ("_kernels", "_encoded"):
        again.pop(key)
    plan = {k: v for k, v in PLAN.items() if not k.startswith("_")}
    assert json.loads(json.dumps(again)) == json.loads(json.dumps(plan)) == ON_DISK
    assert (BAKED / "lightning_apsf.hlsl").read_text() == gen.hlsl(PLAN["_encoded"])


def test_provenance_hashes_and_licences():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["fetched_assets"] == [] and prov["vendored"] == []
    listed = {g["path"] for g in prov["generated"]}
    assert listed == {f"baked/{p.name}" for p in BAKED.iterdir()}
    for entry in prov["generated"]:
        assert hashlib.sha256((LANE / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for source in prov["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()


def test_low_thickness_rule_is_continuous_and_dies_at_zero():
    line = PLAN["_kernels"]["line"]
    at = gen.sample(line, gen.T_MIN, 0.1)
    assert gen.sample(line, gen.T_MIN - 1e-9, 0.1) == pytest.approx(at, rel=1e-6)
    assert gen.sample(line, 0.0, 0.1) == 0.0
    assert gen.sample(line, gen.T_MIN, 0.0) == pytest.approx(line[0, 0], rel=1e-9)


def test_agrees_with_the_project_lightning_and_the_storm_look():
    project = gen._project_lightning()
    shared = PLAN["shared_params"]
    assert shared["flash_rate_per_min"] == project.FLASH_RATE_PER_MIN
    assert shared["ic_cg_ratio"] == project.IC_CG_RATIO
    look = json.loads((REPO / "swarm/lanes/lighting_exposure/physical_light_units/storm/baked/storm_plu.json")
                      .read_text())
    theirs = look["shared_params"]
    for key in ("exposure_ev", "assumed_visibility_m", "lightning_colour_temperature_k",
                "sky_horizon_luminance_cd_m2"):
        assert shared[key] == theirs[key], key
    assert gen.AMBIENT_HORIZONTAL_LUX == theirs["horizontal_illuminance_lux"]
    assert gen.CHANNEL_LENGTH_M == look["lightning"]["channel_length_m_assumed"]
    assert gen.SATURATION_CD_M2 == look["exposure"]["saturation_luminance_cd_m2"]


def test_table_is_the_stated_arithmetic():
    project = gen._project_lightning()
    mean = (project.LUMINOUS_EFFICACY_LM_PER_W
            * project.stroke_total_energy(project.FIRST_STROKE_PEAK_W_PER_M) / gen.SHUTTER_S)
    rows = {r["distance_m"]: r for r in PLAN["by_distance"]}
    row = rows[2000.0]
    width = 2.0 * gen.PIXEL_FLOOR * gen.PIXEL_ANGLE_RAD * 2000.0
    assert row["core_luminance_no_rain_cd_m2"] == pytest.approx(
        project.line_luminance(mean / project.LUMINOUS_EFFICACY_LM_PER_W, width), abs=0.06)
    assert row["core_luminance_cd_m2"] == pytest.approx(
        row["core_luminance_no_rain_cd_m2"] * math.exp(-row["optical_thickness"]), rel=2e-3)
    # The findings INTEGRATION.md rests on: at this exposure the flash barely lights the
    # scene and the glow is under one per cent of the sky behind it.
    assert all(r["flash_over_ambient"] < 0.01 for r in rows.values())
    assert all(r["glow_over_sky_horizon"] < 0.01 for r in rows.values())
    assert rows[5000.0]["core_over_sky_horizon"] < 0.01 < rows[3000.0]["core_over_sky_horizon"]


def test_tiers_are_a_ladder_and_tier_zero_has_no_light_actor():
    tiers = PLAN["tiers"]
    assert [t["tier"] for t in tiers] == [0, 1, 2, 3]
    assert [t["est_vram_mb"] for t in tiers] == sorted(t["est_vram_mb"] for t in tiers)
    assert tiers[0]["flash_light"] == "none" and tiers[0]["glow"] == "none"
    assert PLAN["shared_params"]["flash_light_casts_shadows_tier0"] is False
    assert all("shadow-casting" not in t["flash_light"] for t in tiers[:3])
    assert PLAN["status"].startswith("UNMEASURED") and PLAN["visual_only"] is True


def test_hlsl_constants_are_the_json():
    text = (BAKED / "lightning_apsf.hlsl").read_text()
    for token, value in (("FS_APSF_T_MIN", gen.T_MIN), ("FS_APSF_T_MAX", gen.T_MAX),
                         ("FS_APSF_PHI_MAX", gen.PHI_MAX_RAD),
                         ("FS_APSF_LINE_LN_MIN", ON_DISK["lut"]["line"]["ln_min"]),
                         ("FS_APSF_POINT_LN_MAX", ON_DISK["lut"]["point"]["ln_max"])):
        assert f"#define {token} {value!r}" in text


# -- the pixel gate's arithmetic (synthetic frames, not a render) ------------

def _frames(bolt: float, halo: float = 0.0, lift: float = 0.0, count: int = 6):
    rng = np.random.default_rng(7)
    base = np.full((120, 200), 0.2)
    frames = [base + rng.normal(0.0, 0.001, base.shape) for _ in range(count)]
    lit = frames[3] + lift
    lit[10:110, 100] += bolt
    xs = np.abs(np.arange(200) - 100)[None, :]
    lit[10:110, :] += halo * np.exp(-xs / 15.0) * (xs > 0)
    frames[3] = lit
    return frames


def test_gate_finds_the_stroke_frame_and_ignores_the_frame_wide_lift():
    out = measure.measure(_frames(bolt=0.5, lift=0.05))
    assert out["exercised"] and out["stroke_frame_index"] == 3
    assert out["stroke_contrast"] >= measure.STROKE_CONTRAST_MIN
    assert measure.verdict(out, None)["result"] == "PASS"


def test_gate_is_not_exercised_without_a_stroke_and_fails_a_lost_channel():
    none = measure.measure(_frames(bolt=0.0))
    assert not none["exercised"] and measure.verdict(none, None) == {"result": "NOT EXERCISED", "exit": 2}
    reference = measure.measure(_frames(bolt=0.5))
    dim = dict(reference, stroke_contrast=0.5 * reference["stroke_contrast"])
    assert measure.verdict(dim, reference)["result"] == "FAIL"
    assert measure.verdict(reference, reference)["result"] == "PASS"


def test_halo_ratio_rises_with_a_glow_around_the_channel():
    hard = measure.measure(_frames(bolt=0.5))["halo_ratio"]
    soft = measure.measure(_frames(bolt=0.5, halo=0.05))["halo_ratio"]
    assert soft > hard + 0.01
