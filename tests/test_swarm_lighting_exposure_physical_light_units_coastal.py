"""Source-level checks for the coastal physical-light-units lane (Mac).

These check the bake's arithmetic, its agreement with the repo's own light
model and the pixel gate's maths on synthetic images. They are NOT a render
or pixel result: that is measured on the Windows laptop (see the lane's
INTEGRATION.md).
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
LANE = REPO / "swarm" / "lanes" / "lighting_exposure" / "physical_light_units" / "coastal"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"coastal_plu_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_coastal_plu")
gate = _load("measure_exposure")


@pytest.fixture(scope="module")
def plan():
    return bake.build()


def test_committed_bake_is_reproducible_and_matches_provenance(tmp_path):
    digests = bake.write(tmp_path)
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    recorded = {g["file"]: g["sha256"] for g in provenance["generated"]}
    for name, digest in digests.items():
        assert hashlib.sha256((LANE / name).read_bytes()).hexdigest() == digest, name
        assert recorded[name] == digest, name


def test_provenance_ships_nothing_fetched_and_no_noncommercial_licence():
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    assert provenance["label"] == "visual-only"
    assert provenance["vendored"] == []
    for source in provenance["sources"]:
        assert source["name"] and source["licence"]
        assert "non-commercial" not in source["licence"].lower()
        assert "-nc" not in source["licence"].lower()


def test_constants_agree_with_the_repo():
    from core.scene import beauty_look
    from core.sky import plan as sky_plan

    assert bake.METER_C == beauty_look.METER_CALIBRATION_C
    assert bake.IES_CLEAR_DIFFUSE_KLX == beauty_look.IES_CLEAR_DIFFUSE_KLX
    assert bake.SUN_OUTER_SPACE_LUX == sky_plan.SUN_ILLUMINANCE_LUX
    assert bake.GATE_EV == 0.3


def test_table_is_complete_and_physically_ordered(plan):
    assert len(plan["rows"]) == len(bake.VISIBILITIES_KM) * len(bake.ELEVATIONS_DEG)
    grid = {(r["visibility_km"], r["sun_elevation_deg"]): r for r in plan["rows"]}
    for vis in bake.VISIBILITIES_KM:
        column = [grid[(vis, e)] for e in bake.ELEVATIONS_DEG]
        for lo, hi in zip(column, column[1:]):
            # A higher sun is a brighter scene and a higher EV100.
            assert hi["global_horizontal_lux"] > lo["global_horizontal_lux"]
            assert hi["meter_ev100"] > lo["meter_ev100"]
            assert hi["target_ev100"] > lo["target_ev100"]
    for e in bake.ELEVATIONS_DEG:
        across = [grid[(v, e)] for v in bake.VISIBILITIES_KM]
        for hazy, clear in zip(across, across[1:]):
            # Haze takes light out of the beam and puts part of it in the sky.
            assert clear["sun_direct_normal_lux"] > hazy["sun_direct_normal_lux"]
            assert clear["sky_diffuse_horizontal_lux"] <= hazy["sky_diffuse_horizontal_lux"]
            assert clear["sun_to_sky_ratio"] > hazy["sun_to_sky_ratio"]
    for r in plan["rows"]:
        assert 0.0 < r["sun_direct_normal_lux"] < bake.SUN_OUTER_SPACE_LUX
        assert 0.0 <= r["white_protect_ev"] <= bake.WHITE_PROTECT_MAX_EV
        assert r["target_ev100"] == pytest.approx(r["meter_ev100"] + r["white_protect_ev"], abs=2e-3)
        # The grey card lands on 18 % / (1.2 * 2.5 * pi / ... ) = the meter's constant.
        expected_grey = 0.18 * bake.METER_C / 100.0 / (math.pi * bake.SENSOR_K) / 2 ** r["white_protect_ev"]
        assert r["expected_scene_linear"]["grey_18_flat"] == pytest.approx(expected_grey, abs=2e-3)
        assert r["expected_scene_linear"]["white_sun_facing"] <= bake.WHITE_SUN_FACING_CEILING * 2.0


def test_white_guard_holds_the_ceiling_where_it_is_not_capped(plan):
    for r in plan["rows"]:
        if 0.0 < r["white_protect_ev"] < bake.WHITE_PROTECT_MAX_EV:
            assert r["expected_scene_linear"]["white_sun_facing"] == pytest.approx(
                bake.WHITE_SUN_FACING_CEILING, abs=5e-3)


def test_haze_model():
    h = bake.haze(15.0)
    assert h["extinction_550_per_km"] == pytest.approx(3.912 / 15.0)
    assert h["aod_550"] == pytest.approx((3.912 / 15.0 - 0.0116) * 1.2)
    assert h["aod_380"] > h["aod_500"] > h["aod_550"]
    # No aerosol left once visibility reaches the Rayleigh limit (about 337 km).
    assert bake.haze(400.0)["aod_550"] == 0.0


def test_clear_end_of_the_table_stays_near_the_repo_meter(plan):
    """Forward scatter keeps most of the light: the meter moves little with
    haze. The table must stay within the repo band guard of the repo model."""
    from core.scene import beauty_look

    for r in plan["rows"]:
        repo = beauty_look.meter_ev100(beauty_look.clear_sky_horizontal_lux(r["sun_elevation_deg"]))
        assert r["repo_model_meter_ev100"] == pytest.approx(repo, abs=2e-3)
        assert abs(r["meter_ev100"] - repo) < 0.3
        assert abs(r["target_ev100"] - repo) < beauty_look.EV100_METER_TOLERANCE_STOPS


def test_fresnel_and_glitter():
    assert bake.fresnel_unpolarised(1.0) == pytest.approx(((1.34 - 1) / (1.34 + 1)) ** 2)
    assert bake.fresnel_unpolarised(1e-6) == pytest.approx(1.0, abs=1e-3)
    assert bake.glitter_peak_luminance(30000.0, 12.0) > 0.0
    # Never brighter than the sun's own disc.
    assert bake.glitter_peak_luminance(30000.0, 0.01) <= 30000.0 / 6.8e-5


def test_lookup_hits_rows_interpolates_and_clamps(plan):
    grid = {(r["visibility_km"], r["sun_elevation_deg"]): r for r in plan["rows"]}
    assert bake.lookup(plan, 15.0, 12.0)["target_ev100"] == pytest.approx(
        grid[(15.0, 12.0)]["target_ev100"])
    mid = bake.lookup(plan, 20.0, 11.0)["target_ev100"]
    corners = [grid[(v, e)]["target_ev100"] for v in (15.0, 30.0) for e in (10.0, 12.0)]
    assert min(corners) <= mid <= max(corners)
    assert bake.lookup(plan, 1.0, -5.0) == bake.lookup(plan, 8.0, 1.0)
    assert bake.lookup(plan, 500.0, 80.0) == bake.lookup(plan, 60.0, 40.0)
    assert plan["nominal"]["target_ev100"] == pytest.approx(grid[(15.0, 12.0)]["target_ev100"])


def _frame(gain: float, clipped_rows: int = 0) -> Image.Image:
    """A synthetic linear ramp, sRGB-encoded: arithmetic fixture, not a render."""
    lin = np.tile(np.linspace(0.01, 0.6, 256), (64, 1)) * gain
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.clip(lin, 0, 1) ** (1 / 2.4) - 0.055)
    img = np.repeat((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8)[..., None], 3, axis=2)
    img[:clipped_rows] = 255
    return Image.fromarray(img)


def test_gate_maths_on_synthetic_frames():
    base = _frame(1.0)
    # Half a stop darker than the baseline, as the table asked: passes.
    good = gate.measure(base, _frame(2 ** -0.5), baseline_ev100=13.0, target_ev100=13.5)
    assert good["pass"] and abs(good["ev_error_stops"]) < 0.05
    # The frame did not move though the table asked for half a stop: fails.
    bad = gate.measure(base, base, baseline_ev100=13.0, target_ev100=13.5)
    assert not bad["ev_pass"] and bad["ev_error_stops"] == pytest.approx(0.5, abs=0.02)
    # Right exposure, but a tenth of the frame newly blown out: fails on clip.
    blown = gate.measure(base, _frame(2 ** -0.5, clipped_rows=8), 13.0, 13.5)
    assert blown["ev_pass"] and not blown["clip_pass"] and not blown["pass"]
    # Too few mid-tones is a refusal, not a pass.
    black = Image.new("RGB", (64, 64))
    assert "refused" in gate.measure(black, black, 13.0, 13.0)


def test_gate_reads_its_target_from_the_table(plan):
    assert gate.table_target_ev100(12.0, 15.0) == pytest.approx(plan["nominal"]["target_ev100"])


def test_lane_documents_carry_the_required_labels():
    text = (LANE / "INTEGRATION.md").read_text()
    for needle in ("UNMEASURED", "visual-only", "measure_exposure.py", "Google tiles",
                   "render_visual_sheet.ps1"):
        assert needle.lower() in text.lower(), needle


# -- coastal_gate.py: the one gate command, on the repo's own file shapes ----
# Fixtures, not renders: shots.json is written by the sheet runner's own
# write_shots, the sidecars by the repo's own plan_beauty_look.

coastal_gate = _load("coastal_gate")
COASTAL_BASIS = "coastal physical-light-units table v1 (MODEL, UNCALIBRATED)"


def _step(root: Path, step: str, look: dict, frame: Image.Image, shot: str = "e", **row):
    sys.path.insert(0, str(REPO))
    from experiments.visual_contact_sheet import write_shots

    run_dir = root / "runs_web" / step
    run_dir.mkdir(parents=True)
    (run_dir / "beauty_look.json").write_text(json.dumps(look))
    directory = root / step
    directory.mkdir()
    frame.save(directory / f"{shot}.png")
    write_shots(directory, {shot: {"run_dir": str(run_dir), **row}}, {"step": step})


def _looks(sun: float = 8.0):
    from core.scene.beauty_look import plan_beauty_look

    base = plan_beauty_look(sun, fps=30, width_px=1280)
    cand = json.loads(json.dumps(base))
    table_ev = gate.table_target_ev100(sun, 15.0)
    # What the proposed beauty_look change writes: the base and its basis.
    cand["exposure"]["ev100"] += table_ev - cand["exposure"]["base_ev100"]
    cand["exposure"]["base_ev100"] = table_ev
    cand["exposure"]["basis"] = COASTAL_BASIS
    return base, cand


def test_coastal_gate_passes_and_fails_on_real_file_shapes(tmp_path, capsys):
    base, cand = _looks()
    shift = base["exposure"]["ev100"] - cand["exposure"]["ev100"]
    # Ramps at half gain so the brighter candidate does not clip the fixture.
    _step(tmp_path, "ref", base, _frame(0.5))
    _step(tmp_path, "t0", cand, _frame(0.5 * 2.0 ** shift))
    _step(tmp_path, "stuck", cand, _frame(0.5))  # sidecar moved, pixels did not
    result = coastal_gate.gate(tmp_path, "ref", "t0", "e", 15.0)
    assert result["pass"] and result["table_base_pass"] and abs(result["ev_error_stops"]) < 0.05
    assert result["sun_elevation_deg"] == 8.0 and "coastal" in result["candidate_basis"]
    assert abs(shift) > 0.5  # at 8 deg the table is well clear of the band
    stuck = coastal_gate.gate(tmp_path, "ref", "stuck", "e", 15.0)
    assert not stuck["pass"] and not stuck["ev_pass"]
    # A base that is not the table's fails the sidecar check.
    off = json.loads(json.dumps(cand))
    off["exposure"]["base_ev100"] += 0.2
    _step(tmp_path, "off", off, _frame(0.5 * 2.0 ** shift))
    assert not coastal_gate.gate(tmp_path, "ref", "off", "e", 15.0)["table_base_pass"]
    args = ["--root", str(tmp_path), "--baseline-step", "ref", "--shot", "e", "--candidate-step"]
    assert coastal_gate.main(args + ["t0"]) == 0
    assert coastal_gate.main(args + ["stuck"]) == 1
    assert coastal_gate.main(args + ["nowhere"]) == 2
    assert "REFUSED shots.missing" in capsys.readouterr().out


def test_coastal_gate_refuses_by_name_instead_of_guessing(tmp_path):
    from core.scene.beauty_look import plan_beauty_look

    base, cand = _looks()
    _step(tmp_path, "ref", base, _frame(1.0))
    _step(tmp_path, "t0", cand, _frame(1.0))
    # The repo's two null-EV100 sidecars: physical sky with no plan EV100, sun down.
    _step(tmp_path, "sky", plan_beauty_look(8.0, fps=30, width_px=1280, physical_sky=True), _frame(1.0))
    _step(tmp_path, "night", plan_beauty_look(-2.0, fps=30, width_px=1280), _frame(1.0))
    _step(tmp_path, "dusk", plan_beauty_look(4.0, fps=30, width_px=1280), _frame(1.0))
    _step(tmp_path, "refused", cand, _frame(1.0), refused="terrain.unbaked")
    (tmp_path / "bare").mkdir()
    (tmp_path / "bare" / "e.png").write_bytes((tmp_path / "ref" / "e.png").read_bytes())
    (tmp_path / "bare" / "shots.json").write_text(json.dumps({"shots": {"e": {"run_dir": str(tmp_path / "none")}}}))
    cases = {
        ("sky", "t0"): "exposure.ev100_null", ("ref", "night"): "exposure.ev100_null",
        ("ref", "ref"): "candidate.not_coastal_base",  # an unmerged tree, or an inland shot
        ("dusk", "t0"): "sun.mismatch", ("t0", "t0"): "exposure.unchanged",
        ("ref", "refused"): "shot.refused", ("ref", "bare"): "sidecar.missing",
        ("ref", "absent"): "shots.missing",
    }
    # The nominal 12 deg row is 0.17 stop from the band: a stuck frame would pass.
    base12, cand12 = _looks(12.0)
    _step(tmp_path, "ref12", base12, _frame(1.0))
    _step(tmp_path, "t12", cand12, _frame(1.0))
    cases[("ref12", "t12")] = "exposure.shift_below_gate"
    for (a, b), name in cases.items():
        with pytest.raises(coastal_gate.Refused, match=name.replace(".", r"\.")):
            coastal_gate.gate(tmp_path, a, b, "e", 15.0)
    with pytest.raises(coastal_gate.Refused, match=r"shot\.missing"):
        coastal_gate.gate(tmp_path, "ref", "t0", "a", 15.0)


def test_gate_claims_match_the_tree():
    """The gate is documented as blocked for exactly as long as it is."""
    sys.path.insert(0, str(REPO))
    from core.terrain.glo30 import LOCATIONS
    from experiments.visual_contact_sheet import SHOTS

    text = (LANE / "INTEGRATION.md").read_text()
    assert "coastal_gate.py --baseline-step" in text and "BLOCKED" in text
    assert "shots.a.run_dir" not in text and "--baseline-ev100 $ev" not in text
    # The blocker the document states: no coastal place, four inland shots.
    assert sorted(LOCATIONS) == ["everest", "flint_hills", "fuji", "grand_canyon",
                                 "matterhorn", "yosemite"]
    assert sorted(SHOTS) == ["a", "b", "c", "d"]
