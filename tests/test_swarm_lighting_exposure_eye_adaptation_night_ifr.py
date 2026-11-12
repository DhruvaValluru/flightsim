"""lighting_exposure.eye_adaptation.night_ifr: what is checkable on the Mac.

Run with the repo venv (numpy is needed by core.sky.plan):

    .venv/bin/python -m pytest tests/test_swarm_lighting_exposure_eye_adaptation_night_ifr.py

``core.sky.plan`` is imported at module level ON PURPOSE: without it there is
no outside anchor, so the module fails to collect rather than skipping.

Nothing here stands in for a rendered frame (the pixel gate runs on Windows).
The tone curves below are stand-ins written for the test, not the engine's.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import random
from pathlib import Path

import pytest

from core.scene import runway as project_runway
from core.sky import astro as project_astro
from core.sky import plan as project_plan

LANE = Path(__file__).resolve().parents[1] / "swarm/lanes/lighting_exposure/eye_adaptation/night_ifr"
GATE_EV = 0.3   # the task's gate, stated here and not read from the lane


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"swarm_eye_night_ifr_{name}", LANE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load("generate")
measure = _load("measure_frame")
gate_tool = _load("gate_tool")
BAKED_JSON = json.loads((LANE / "baked/night_ifr_eye.json").read_text(encoding="utf-8"))
with open(LANE / "baked/night_ifr_eye_curve.csv", encoding="utf-8") as _handle:
    BAKED_ROWS = list(csv.DictReader(_handle))


# -- the outside anchor: the project's own night exposure ----------------------

def test_restated_rule_equals_the_projects():
    assert gen.DAYLIGHT_LUX == project_plan.DAYLIGHT_LUX
    assert gen.NIGHT_SKY_LUX == project_plan.NIGHT_SKY_LUX
    assert gen.CAMERA_EV100 == pytest.approx(project_plan.CAMERA_EV100)
    assert tuple(gen.EV100_RANGE) == tuple(project_plan.EV100_RANGE)
    for lux in (5e-4, 0.01, 0.174, 3.4, 399.0, 400.0, 12000.0):
        assert gen.ev100_for(lux) == pytest.approx(project_plan.ev100_for(lux))


@pytest.mark.parametrize("when, date", [("midnight", "2026-11-24"), ("00:30", "2026-01-03"),
                                        ("midnight", "2026-11-09")])
def test_look_equals_what_plan_sky_writes_for_a_real_night(when, date):
    """The whole project path (ephemeris, moon phase, the 0.27 lx constant,
    the half-rate rule), not the lane's copy of it."""
    sky = project_plan.plan_sky(when, date, 37.62, -122.38, 600.0, 4.0)
    moon = sky["moon"]
    rel = project_astro.moon_relative_brightness(moon["phase_angle_deg"])
    lux = gen.look_lux(rel, moon["elevation_deg"])
    assert lux == pytest.approx(sky["exposure"]["horizontal_illuminance_lux"], abs=2e-4)
    assert gen.ev100_for(lux) == pytest.approx(sky["exposure"]["ev100"], abs=2e-3)
    assert gen.CAMERA_EV100 - gen.ev100_for(lux) == pytest.approx(sky["exposure"]["bias"], abs=2e-3)


def test_the_shipped_bytes_sit_inside_the_gate_of_the_projects_look():
    """Reads the files the laptop would consume and judges them against
    core.sky.plan, with the gate stated in this file. The band is a design
    invariant (a 0.25 EV clamp), so this guards the shipped numbers against
    drift; it is not evidence about a frame."""
    scn = BAKED_JSON["scenario"]
    lux = 0.27 * scn["moon_relative_brightness"] * math.sin(math.radians(scn["moon_elevation_deg"])) \
        + project_plan.NIGHT_SKY_LUX
    look = project_plan.ev100_for(lux)
    assert BAKED_JSON["calibrated_look"]["ev100"] == pytest.approx(look, abs=1e-3)
    assert len(BAKED_ROWS) == BAKED_JSON["curve_summary"]["rows"] > 100
    for row in BAKED_ROWS:
        assert abs(float(row["ev100"]) - look) <= GATE_EV
        assert float(row["ue_exposure_bias"]) == pytest.approx(
            project_plan.CAMERA_EV100 - float(row["ev100"]), abs=2e-4)
    for tier in BAKED_JSON["tiers"][1:3]:
        assert look - GATE_EV < tier["ue"]["AutoExposureMinBrightness"] < look
        assert look < tier["ue"]["AutoExposureMaxBrightness"] < look + GATE_EV
    assert [t["tier"] for t in BAKED_JSON["tiers"]] == [0, 1, 2, 3]


# -- the clamp is what does the work, and the check can fail --------------------

def _bright_field(cd: float):
    """A SYNTHETIC row of lights for the tests. Not photometry."""
    return [{"x": 60.0 * i, "y": y, "cd": cd} for i in range(50) for y in (-22.5, 22.5)]


def test_without_the_clamp_the_curve_leaves_the_gate(monkeypatch):
    look = gen.ev100_for(gen.look_lux())
    monkeypatch.setattr(gen, "MAX_EXCURSION_EV", 9.0)
    assert max(abs(r["ev100"] - look) for r in gen.curve()) > GATE_EV            # the deck alone
    assert max(r["ev100"] - look for r in gen.curve(_bright_field(1e5))) > GATE_EV


@pytest.mark.parametrize("cd", [0.0, 1.0, 1e3, 1e6, 1e9])
def test_with_the_clamp_no_light_intensity_takes_it_out(cd):
    look = gen.ev100_for(gen.look_lux())
    rows = gen.curve(_bright_field(cd))
    assert max(abs(r["ev100"] - look) for r in rows) <= gen.MAX_EXCURSION_EV + 1e-4 < GATE_EV


def test_the_step_never_overshoots_at_any_frame_time():
    rng = random.Random(7)
    for dt in (1 / 240, 1 / 30, 0.5, 3.0, 60.0):
        x = 0.0
        for _ in range(400):
            target = rng.uniform(-gen.MAX_EXCURSION_EV, gen.MAX_EXCURSION_EV)
            lo, hi = min(x, target), max(x, target)
            x = gen.step(x, target, dt)
            assert lo - 1e-12 <= x <= hi + 1e-12


def test_closing_is_faster_than_opening_and_frame_rate_independent():
    assert gen.step(0.0, 0.25, 1.0) > -gen.step(0.0, -0.25, 1.0)
    assert gen.step(0.1, 0.1, 1.0) == pytest.approx(0.1)
    x = 0.0
    for _ in range(30):
        x = gen.step(x, 0.25, 1.0 / 30.0)
    assert x == pytest.approx(gen.step(0.0, 0.25, 1.0))


# -- what the bake does and does not contain -------------------------------------

def test_the_bake_opens_in_cloud_and_carries_no_light_term():
    assert BAKED_ROWS[0]["phase"] == "above_deck" and float(BAKED_ROWS[0]["offset_ev"]) == 0.0
    in_cloud = [r for r in BAKED_ROWS if r["phase"] == "in_cloud"]
    assert in_cloud and any(r["phase"] == "below_deck" for r in BAKED_ROWS)
    assert float(in_cloud[-1]["offset_ev"]) == pytest.approx(-0.25, abs=1e-3)
    assert all(float(r["eye_lux_lights"]) == 0.0 for r in BAKED_ROWS)
    assert BAKED_JSON["curve_summary"]["light_term"] == "none"


def test_no_light_intensity_is_shipped_while_the_project_has_none():
    """core/scene/runway.py names its candela as missing, never invented.
    If that changes, this lane should take the project's numbers: fail then."""
    assert project_runway.PHOTOMETRY["candela"] is None
    assert not hasattr(gen, "EDGE_PEAK_CD") and not hasattr(gen, "lights")
    text = json.dumps(BAKED_JSON)
    assert "close_clamp_reached_at_distance_m" not in text and '"edge_cd"' not in text
    for name in ("INTEGRATION.md", "PROVENANCE.json"):
        body = (LANE / name).read_text(encoding="utf-8")
        assert "1 164" not in body and "1164" not in body and "10 000 cd" not in body


def test_closing_thresholds_follow_from_the_target_alone():
    ref = gen.look_lux()
    lights = BAKED_JSON["runway_lights"]
    under = ref * gen.DECK_TRANSMITTANCE
    assert gen.target_offset_ev(under + lights["eye_lux_from_lights_to_return_to_the_look"], ref) \
        == pytest.approx(0.0, abs=1e-5)
    edge = lights["eye_lux_from_lights_to_reach_the_close_clamp"]
    assert gen.target_offset_ev(under + edge * 1.001, ref) == gen.MAX_EXCURSION_EV
    assert gen.target_offset_ev(under + edge * 0.99, ref) < gen.MAX_EXCURSION_EV


def test_allard_and_extinction():
    sigma = gen.extinction_per_m(2400.0)
    assert math.exp(-sigma * 2400.0) == pytest.approx(0.05)
    one = [{"x": 0.0, "y": 0.0, "cd": 1000.0}]
    assert gen.eye_lux_from_lights(1000.0, 0.0, 0.0, one) == pytest.approx(1e-3)
    assert gen.eye_lux_from_lights(1000.0, 0.0, sigma, one) == pytest.approx(1e-3 * math.exp(-sigma * 1000.0))
    assert gen.eye_lux_from_lights(-10.0, 0.0, 0.0, one) == 0.0  # behind the eye
    near = [r["offset_ev"] for r in gen.curve(_bright_field(1e5))]
    far = [r["offset_ev"] for r in gen.curve(_bright_field(1e3))]
    assert all(a >= b - 1e-9 for a, b in zip(near, far)) and near != far  # more light, more closed


def test_bake_is_deterministic_and_pinned():
    digests = gen.write()
    prov = json.loads((LANE / "PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["fetched_assets"] == []
    pinned = {Path(g["path"]).name: g["sha256"] for g in prov["generated"]}
    assert digests == pinned
    for name, digest in pinned.items():
        assert hashlib.sha256((LANE / "baked" / name).read_bytes()).hexdigest() == digest


# -- the pixel gate's arithmetic, through tone curves it does not know ----------
# The metric decodes sRGB and interpolates between rendered brackets. These
# stand-in "renderers" put an S-curve between the scene and the code value, so
# the frames are NOT built from the model the metric inverts.

def _filmic(x: float) -> float:
    """Narkowicz's ACES fit (2015), then a 2.2 gamma. A stand-in S-curve."""
    y = x * (2.51 * x + 0.03) / (x * (2.43 * x + 0.59) + 0.14)
    return min(max(y, 0.0), 1.0) ** (1 / 2.2)


def _contrasty(x: float) -> float:
    """A second, steeper curve: x^1.6 / (x^1.6 + 0.18^1.6)."""
    return x ** 1.6 / (x ** 1.6 + 0.18 ** 1.6)


def _scene(n: int = 6000, lo: float = -9.0, hi: float = 2.0):
    rng = random.Random(11)
    return [2.0 ** rng.uniform(lo, hi) for _ in range(n)]


def _render(scene, curve, offset_ev: float):
    """offset_ev positive = exposed darker, as the eye's."""
    return [int(round(255.0 * curve(v * 2.0 ** -offset_ev))) for v in scene]


@pytest.mark.parametrize("curve", [_filmic, _contrasty])
@pytest.mark.parametrize("lo, hi", [(-9.0, 2.0), (-11.0, -2.0)])   # full range; a dark, night-like frame
def test_bracketed_metric_recovers_a_known_offset_through_an_unknown_tone_curve(curve, lo, hi):
    scene = _scene(lo=lo, hi=hi)
    ref, dark, bright = (_render(scene, curve, e) for e in (0.0, 0.3, -0.3))
    for true in (0.25, 0.1, 0.0, -0.1, -0.25):
        got = measure.compare(_render(scene, curve, true), ref, dark, bright,
                              expected=true if abs(true) >= 0.1 else None)
        assert got["ev_offset"] == pytest.approx(true, abs=0.04), (true, got)
        assert got["pass"], got
    for true in (0.4, -0.4, 1.0):
        got = measure.compare(_render(scene, curve, true), ref, dark, bright)
        assert abs(got["ev_offset"]) > GATE_EV and not got["pass"], (true, got)
    wrong = measure.compare(_render(scene, curve, -0.25), ref, dark, bright, expected=0.25)
    assert not wrong["pass"]


def test_the_two_frame_log_ratio_is_not_a_gate():
    """Why the brackets exist: through a contrasty curve the plain display
    ratio reads a 0.25 EV change as more than the 0.3 EV gate."""
    scene = _scene()
    ref, dark, bright = (_render(scene, _contrasty, e) for e in (0.0, 0.3, -0.3))
    got = measure.compare(_render(scene, _contrasty, 0.25), ref, dark, bright)
    assert got["display_ev_offset"] > GATE_EV
    assert got["ev_offset"] == pytest.approx(0.25, abs=0.04)


def test_pixel_gate_refuses_what_it_cannot_meter():
    black = measure.compare([0] * 1000, [0] * 1000, [0] * 1000, [0] * 1000)
    assert black["ev_offset"] is None and not black["pass"]
    flat = [120] * 1000   # brackets that did not move the frame
    assert not measure.compare(flat, flat, flat, flat)["pass"]
    with pytest.raises(ValueError):
        measure.compare([1, 2], [1], [1], [1])
    assert measure.main(["--frame", "a.png"]) == 2


# -- the helper that makes the gate runnable today -------------------------------

def test_gate_tool_writes_brightness_edits_the_project_accepts(tmp_path):
    from core.scene import lighting as project_lighting

    assert "brightness_ev" in project_lighting.KNOBS
    pinned = {"prompt": "p", "compiler": "regex", "notes": [],
              "spec": {"lighting": {"brightness_ev": {"value": 0.0, "source": "default", "unit": "EV"},
                                    "preset": {"value": "natural", "source": "default"}}}}
    src = tmp_path / "reference" / "06.json"
    src.parent.mkdir()
    src.write_text(json.dumps(pinned), encoding="utf-8")
    written = gate_tool.write_specs(src, tmp_path)
    values = {name: json.loads(Path(path).read_text())["spec"]["lighting"]["brightness_ev"]
              for name, path in written.items()}
    # brightness_ev is positive = brighter; the eye's offset is positive = darker
    assert {n: v["value"] for n, v in values.items()} == {
        "eye_closed": -0.25, "eye_open": 0.25, "bracket_dark": -0.3, "bracket_bright": 0.3}
    assert all(v["source"] == "user" for v in values.values())
    assert all(Path(p).name == "06.json" for p in written.values())
    assert json.loads(src.read_text())["spec"]["lighting"]["brightness_ev"]["value"] == 0.0
    assert not project_lighting.problems({"brightness_ev": -0.3})
    assert not project_lighting.problems({"brightness_ev": 0.3})


def test_gate_tool_stashes_the_last_runs_first_frame(tmp_path):
    runs = tmp_path / "webapp"
    cam = runs / "r1" / "frames" / "chase"
    cam.mkdir(parents=True)
    (cam / "frame_0000.png").write_bytes(b"first")
    (cam / "frame_0000_beauty_post.png").write_bytes(b"not this one")
    summary = tmp_path / "test_scenarios.json"
    summary.write_text(json.dumps([{"number": 6, "run_id": "r1", "outcome": "done"}]), encoding="utf-8")
    out = gate_tool.stash("reference", summary, runs, tmp_path / "eye_gate")
    assert out.name == "reference.png" and out.read_bytes() == b"first"
    summary.write_text(json.dumps([{"number": 6, "run_id": "r1", "outcome": "failed", "why": "device lost"}]),
                       encoding="utf-8")
    with pytest.raises(SystemExit):
        gate_tool.stash("reference", summary, runs, tmp_path / "eye_gate")


def test_the_gate_command_uses_only_flags_and_scenarios_that_exist():
    runner = (LANE.parents[4] / "scripts/run_test_scenarios.py").read_text(encoding="utf-8")
    for flag in ('"--only"', '"--still"', '"--spec-dir"'):
        assert flag in runner
    assert "a320 over sfo heading south, moderate rain" in runner   # scenario 6
    doc = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    assert "--only 6 --still --spec-dir" in doc and "--only 16" not in doc
