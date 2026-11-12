"""weather_fx.rain_drops.storm: what is checkable on the Mac.

Arithmetic, determinism and agreement with the project's own rain model. No
test here stands in for a rendered frame (the pixel gate runs on Windows).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import precipitation as rain_model
from core.scene import rain_field

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm/lanes/weather_fx/rain_drops/storm"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"swarm_rain_drops_storm_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate")
measure = _load("measure_frame")
run_gate = _load("run_gate")
PHYS = gen.physics()
PLAN = gen.build()


def test_drops_are_the_projects_own_sample():
    drops = gen.layer_drops(0, PHYS)
    for i in (0, 7, drops["count"] - 1):
        d = rain_field.sample_diameter_mm(rain_field.unit(drops["seed"], i, 3), PHYS["lambda_per_mm"])
        assert drops["d_mm"][i] == d
        assert gen.v_t_np(np.array([d]), 1.0)[0] == pytest.approx(rain_model.terminal_velocity_mps(d), rel=1e-12)
        assert gen.width_np(np.array([d]))[0] == pytest.approx(rain_field.presented_width_mm(d), rel=1e-12)
    assert rain_field.D_RENDER_MIN_MM <= drops["d_mm"].min() and drops["d_mm"].max() <= rain_field.D_MAX_MM


def test_wx1_mean_streak_length_within_30_percent_of_d0():
    for ratio in PLAN["wx1_mean_length_ratio"].values():
        assert 0.7 <= ratio <= 1.3


def test_splat_conserves_light_and_tiles():
    # One streak across both seams: 2.5 texels wide, 1.5 tiles long.
    img = gen.splat(np.array([gen.NU - 0.5]), np.array([gen.NV - 3.25]), np.array([2.5]),
                    np.array([1.5 * gen.NV]), np.array([0.2]))
    assert img.sum() == pytest.approx(0.2 * 2.5 * 1.5 * gen.NV, rel=1e-9)
    assert img.min() >= -1e-12
    # Column 0 is the wrapped edge (0.75 of a texel covered), overlapped twice in v.
    assert img[:, 0].max() == pytest.approx(0.2 * 0.75 * 2)
    assert img[:, 5].max() == 0.0


def test_every_bin_keeps_the_mean_light():
    for layer in PLAN["layers"]:
        for b in layer["bins"]:
            assert b["mean_alpha_splat"] == pytest.approx(b["mean_alpha_analytic"], rel=1e-6)
            # 8-bit storage and the 99.9th-percentile clip lose at most 5 %.
            assert b["mean_alpha_stored"] == pytest.approx(b["mean_alpha_analytic"], rel=0.05)
        means = [b["mean_alpha_analytic"] for b in layer["bins"]]
        # Coverage n D^2 does not depend on the sweep while D / L < 1.
        assert max(means) == pytest.approx(min(means), rel=1e-6)


def test_committed_bake_matches_a_fresh_one():
    baked = json.loads((LANE / "baked/rain_layers.json").read_text())
    assert baked == json.loads(json.dumps(PLAN))
    for k, layer in enumerate(PLAN["layers"]):
        rgba, record = gen.bake_layer(k, PHYS)
        data = (LANE / "baked" / layer["file"]).read_bytes()
        assert data == gen.tga_bytes(rgba)
        assert record["pixels_sha256"] == layer["pixels_sha256"]


def test_provenance_hashes_and_no_fetched_assets():
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    assert prov["fetched_assets"] == [] and prov["vendored"] == []
    for entry in prov["generated"]:
        assert hashlib.sha256((LANE / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    assert {e["path"] for e in prov["generated"]} == {f"baked/{p.name}" for p in (LANE / "baked").iterdir()}


def test_tiers_are_estimates_and_rise_in_particles():
    tiers = PLAN["tiers"]
    assert [t["tier"] for t in tiers] == [0, 1, 2, 3]
    assert tiers[0]["particles"] is None and tiers[0]["est_vram_mb"] < 16
    counts = [t["particles"]["particles"] for t in tiers[1:]]
    assert counts == sorted(counts) and counts[-1] == rain_field.PARTICLE_BUDGET
    for t in tiers[1:]:
        p = t["particles"]
        assert p["weight"] == pytest.approx(p["expected_in_box"] / p["particles"], rel=1e-3)


def test_shader_constants_match_the_bake():
    text = (LANE / "RainLayers.ush").read_text()
    for name, value in (("RL_NU", gen.NU), ("RL_NV", gen.NV), ("RL_NREP", gen.NREP)):
        assert float(re.search(rf"{name} = ([0-9.]+)", text).group(1)) == value
    assert f"smoothstep({gen.POLE_FADE[0]}, {gen.POLE_FADE[1]}, SinT)" in text
    assert "ddx" not in text and "for (" not in text


def test_shared_params_agree_with_the_project():
    s = PLAN["shared_params"]
    assert s["rain_rate_mmh"] == 50.0 and s["rain_gain"] == 4.0 and s["rain_style"] == "cinematic"
    assert s["rain_meteorological_range_m"] == pytest.approx(3.912 / s["rain_extinction_per_m"], abs=0.1)
    assert s["exposure_ev"] == 12.5


def _frames(transpose: bool = False):
    """A synthetic pair from the bake itself: ARITHMETIC only, not a render."""
    rgba, _ = gen.bake_layer(1, PHYS)
    a = rgba[:512, :, 2].astype(float) / 255.0          # rest_cinematic
    if transpose:
        a = a.T
    off = np.full((512, 512, 3), 77, dtype=np.uint8)
    on = np.clip(77 + 150 * a, 0, 255).astype(np.uint8)[..., None].repeat(3, axis=2)
    return on, off


def test_gate_arithmetic_on_synthetic_streaks():
    on, off = _frames()
    result = measure.verdict(measure.measure(on, off), expected_deg=0.0)
    assert result["orientation_error_deg"] < 2.0 and result["checks"]["coherence"]
    sideways = measure.verdict(measure.measure(*_frames(transpose=True)), expected_deg=0.0)
    assert sideways["orientation_error_deg"] > 80.0 and not sideways["passed"]
    none = measure.verdict(measure.measure(off, off), expected_deg=0.0)
    assert not none["passed"]
    # A uniform lift (haze, exposure) is not a streak: it lands in veil_delta.
    lifted = measure.measure(np.clip(on.astype(int) + 20, 0, 255).astype(np.uint8), off)
    assert lifted["veil_delta"] > measure.measure(on, off)["veil_delta"] + 0.05
    assert lifted["coherence"] == pytest.approx(measure.measure(on, off)["coherence"], abs=0.02)


def test_gate_assumes_no_angle():
    on, off = _frames()
    m = measure.measure(on, off)
    alone = measure.verdict(m)
    assert alone["checks"]["orientation"] is None and not alone["passed"] and not alone["complete"]
    against = measure.verdict(m, reference=m)
    assert against["expected_deg"] == m["streak_angle_deg"] and against["passed"]
    turned = measure.verdict(measure.measure(*_frames(transpose=True)), reference=m)
    assert turned["complete"] and not turned["passed"]


def _write_pair(out, role, transpose=False, drawn_as=None, gain_off=0.0):
    from PIL import Image
    on, off = _frames(transpose)
    for leg, image, gain in (("on", on, 4.0), ("off", off, gain_off)):
        d = run_gate.frames_dir(out, role, leg)
        d.mkdir(parents=True)
        for n in (0, 4):
            Image.fromarray(image).save(d / f"frame_{n:04d}.png")
        rain = {"gain": gain, **({"drawn_as": drawn_as} if drawn_as else {})}
        (d / "render.json").write_text(json.dumps({"world_applied": {"weather": {"rain": rain}}}))
    Image.fromarray(on).save(run_gate.frames_dir(out, role, "on") / "frame_0009.png")   # no partner


def test_run_gate_is_one_command_with_no_blanks():
    doc = run_gate.__doc__ + (LANE / "INTEGRATION.md").read_text() + measure.__doc__
    assert "<rain on" not in doc and "<reference on" not in doc and "<ref on" not in doc
    assert "thunderstorm at 2000 m" in run_gate.scenario_prompt() and "747" in run_gate.scenario_prompt()
    command = run_gate.leg_command(Path("o"), "reference", "off", "p")
    assert (REPO / "scripts/debug_storm_render.py").is_file() and command[1].endswith("debug_storm_render.py")
    assert command[command.index("--rain-gain") + 1] == "0"
    assert run_gate.leg_command(Path("o"), "candidate", "on", "p")[command.index("--rain-gain") + 1] == "4"
    # The flags the gate passes exist in the script it calls.
    text = (REPO / "scripts/debug_storm_render.py").read_text()
    for flag in ("--backend", "--prompt", "--seconds", "--rain-gain", "--rain-style", "--out"):
        assert f'"{flag}"' in text


def test_run_gate_verdicts(tmp_path):
    calls = []
    render = lambda out, role, leg, prompt, tier: calls.append((role, leg, tier)) or 0
    # Today's build: the candidate legs render, but nothing says baked_layers.
    a = tmp_path / "a"
    _write_pair(a, "reference"); _write_pair(a, "candidate")
    result = run_gate.gate(a, render=render, prompt="p")
    assert calls == [("reference", "off", 3), ("reference", "on", 3), ("candidate", "off", 0), ("candidate", "on", 0)]
    assert result["exit"] == 3 and result["verdict"].startswith("NOT INTEGRATED")
    assert result["reference"]["frame"] == "frame_0004.png" and (a / "reference.json").is_file()
    # Integrated, streaks along the reference's: pass. Across them: fail.
    b = tmp_path / "b"
    _write_pair(b, "reference"); _write_pair(b, "candidate", drawn_as="baked_layers")
    assert run_gate.gate(b, measure_only=True)["exit"] == 0
    c = tmp_path / "c"
    _write_pair(c, "reference"); _write_pair(c, "candidate", transpose=True, drawn_as="baked_layers")
    assert run_gate.gate(c, measure_only=True)["exit"] == 1
    # No reference and no stated angle: not measurable, never a pass.
    d = tmp_path / "d"
    _write_pair(d, "candidate", drawn_as="baked_layers")
    assert run_gate.gate(d, measure_only=True)["exit"] == 3
    assert run_gate.gate(d, expected_deg=0.0, measure_only=True)["exit"] == 0
    # An off leg the build did not draw at gain 0 is a problem, not a frame.
    e = tmp_path / "e"
    _write_pair(e, "reference", gain_off=4.0)
    only = run_gate.gate(e, only="reference", measure_only=True)
    assert only["exit"] == 3 and "not 0" in only["reference"]["problems"][0]
