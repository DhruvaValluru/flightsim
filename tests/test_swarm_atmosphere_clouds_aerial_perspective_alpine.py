"""Source-level checks for the alpine aerial-perspective lane (Mac).

What these can show: the bake agrees with closed-form values of its own
model, the measurement's arithmetic behaves on synthetic images, and the repo
hooks the Windows commands rely on exist in source. What they cannot show:
anything about engine output. The model's constants are ASSUMED, and no
synthetic image stands in for a rendered frame; that is measured on the
Windows laptop (the lane's INTEGRATION.md).
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
LANE = REPO / "swarm" / "lanes" / "atmosphere_clouds" / "aerial_perspective" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_ap_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_ap")
gate = _load("measure_aerial_perspective")


@pytest.fixture(scope="module")
def plan():
    return bake.build()


def _tile(tex, sun, alt):
    row = (bake.SUN_ELEVATIONS_DEG.index(sun) * len(bake.ALTITUDES_M) + bake.ALTITUDES_M.index(alt)) * bake.NMU
    return tex[row:row + bake.NMU].astype(np.float64)


def test_committed_bake_is_reproducible_and_matches_provenance(tmp_path):
    fresh = bake.write(tmp_path)
    provenance = json.loads((LANE / "PROVENANCE.json").read_text())
    recorded = {g["file"]: g["sha256"] for g in provenance["generated"]}
    assert set(recorded) == set(bake.OUTPUTS)
    for name in bake.OUTPUTS:
        on_disk = hashlib.sha256((LANE / name).read_bytes()).hexdigest()
        assert on_disk == fresh[name] == recorded[name], name
    assert provenance["label"] == "visual-only"
    assert provenance["vendored"] == []


def test_texture_shape_and_size(plan):
    rows = len(bake.SUN_ELEVATIONS_DEG) * len(bake.ALTITUDES_M) * bake.NMU
    for key in "abc":
        assert plan[key].shape == (rows, bake.ND, 4)
        assert plan[key].dtype == np.dtype("<f2")
        assert np.isfinite(plan[key].astype(np.float64)).all()
    # three textures, well under 1 MB together: the tier-0 VRAM estimate rests on this
    assert sum(plan[k].nbytes for k in "abc") < 256 * 1024


def test_transmittance_matches_closed_form_on_a_short_level_ray():
    # 5 km at 5000 m: the ray climbs 2 m, so T = exp(-extinction(h) * d) to 4 digits
    ref = bake.reference(5000.0, 30.0, 0.0, 5.0)
    expected = np.exp(-bake.extinction(np.array(5.0)) * 5.0)
    assert np.allclose(ref["transmittance_rgb"], expected, rtol=2e-4)
    # and the per-km value is the bake's assumed constants at that height
    rayleigh_green = 0.013558 * math.exp(-5.0 / 8.0)
    mie = (0.003996 + 0.000444) * math.exp(-5.0 / 1.2)
    assert bake.extinction(np.array(5.0))[1] == pytest.approx(rayleigh_green + mie, rel=1e-9)


def test_vertical_optical_depth_matches_the_analytic_column():
    # overhead sun from sea level: Rayleigh column = beta * H * (1 - exp(-60/H)) plus Mie and ozone
    _, tau = bake.sun_optical_depth_table(90.0)
    h_r, h_m = bake.RAYLEIGH_SCALE_HEIGHT_KM, bake.MIE_SCALE_HEIGHT_KM
    top = bake.ATMOSPHERE_HEIGHT_KM
    expected = (bake.RAYLEIGH_SCATTERING * h_r * (1 - math.exp(-top / h_r))
                + (bake.MIE_SCATTERING + bake.MIE_ABSORPTION) * h_m * (1 - math.exp(-top / h_m))
                + bake.OZONE_ABSORPTION * bake.OZONE_HALF_WIDTH_KM)
    assert np.allclose(tau[0], expected, rtol=2e-3)


def test_texture_agrees_with_the_exact_ray(plan):
    d = bake.distance_axis()
    mu = bake.mu_axis()
    for mi in (0, 7, 15):
        for di in (5, 17, 31):
            ref = bake.reference(5000.0, 30.0, math.degrees(math.asin(mu[mi])), float(d[di]))
            assert np.allclose(_tile(plan["b"], 30.0, 5000.0)[mi, di, :3], ref["transmittance_rgb"], rtol=5e-3, atol=2e-4)
            assert np.allclose(_tile(plan["a"], 30.0, 5000.0)[mi, di, :3], ref["rayleigh_inscatter_rgb"], rtol=1e-2, atol=1e-5)
            assert np.allclose(_tile(plan["c"], 30.0, 5000.0)[mi, di, :3], ref["mie_inscatter_rgb"], rtol=1e-2, atol=1e-6)


def test_physical_ordering_and_energy_bound(plan):
    t = plan["b"].astype(np.float64)[..., :3]
    scattered = plan["a"].astype(np.float64)[..., :3] + plan["c"].astype(np.float64)[..., :3]
    assert np.all(t[:, 0] == 1.0) and np.all(scattered[:, 0] == 0.0)
    # never brighter with distance; flat only where a climbing ray has left the air
    assert np.all(np.diff(t, axis=1) <= 0) and np.all(np.diff(scattered, axis=1) >= 0)
    level = slice(bake.NMU // 2 - 1, None, bake.NMU)   # the ray just below the horizon, every tile
    assert np.all(np.diff(t[level], axis=1) < 0)
    # blue is extinguished most, red least
    assert np.all(t[:, 1:, 2] < t[:, 1:, 1]) and np.all(t[:, 1:, 1] < t[:, 1:, 0])
    # light scattered towards the eye cannot exceed light removed from the beam
    assert np.all(scattered <= (1.0 - t) + 2e-3)


def test_thin_air_higher_camera_sees_further(plan):
    level = bake.NMU // 2
    low = _tile(plan["b"], 30.0, 2000.0)[level, -1, :3]
    high = _tile(plan["b"], 30.0, 6000.0)[level, -1, :3]
    assert np.all(high > low)


def test_phase_functions_integrate_to_one():
    cos = np.linspace(-1.0, 1.0, 200001)
    for phase in (bake.phase_rayleigh, bake.phase_mie):
        y = phase(cos)
        integral = 2.0 * math.pi * float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(cos)))
        assert integral == pytest.approx(1.0, abs=2e-3)


def _encode(linear):
    v = np.clip(linear, 0.0, 1.0)
    return np.round(np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055) * 255.0).astype(np.uint8)


def _aces(x):
    return (x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14)


def _boxes(t_near, t_far, curve=lambda x: x, exposure=1.0, clear_light=1.6):
    """Synthetic near and far boxes. The clear frame is lit ``clear_light``
    times brighter, as a frame with the atmosphere hidden would be."""
    rng = np.random.default_rng(11)
    albedo = rng.uniform(0.08, 0.5, size=(64, 64, 3))
    haze = np.array([0.02, 0.035, 0.06])
    make = lambda t, s, light: gate.srgb_to_linear(_encode(curve(exposure * (albedo * light * np.asarray(t) + s))))
    return (make(1.0, 0.0, clear_light), make(t_near, haze * 0.125, 1.0),
            make(1.0, 0.0, clear_light), make(t_far, haze, 1.0))


T_NEAR = bake.reference(5000.0, 30.0, 0.0, 5.0)["transmittance_rgb"]
T_FAR = bake.reference(5000.0, 30.0, 0.0, 40.0)["transmittance_rgb"]


def test_ratio_metric_cancels_the_lighting_change_of_the_clear_frame():
    result = gate.evaluate(*_boxes(T_NEAR, T_FAR), T_NEAR, T_FAR)
    assert result["ap_log_t_ratio_error"] < 0.01
    # one box alone would be wrong by the lighting ratio: slope = T / 1.6
    assert result["near"]["slope_rgb"][1] == pytest.approx(T_NEAR[1] / 1.6, rel=0.02)
    assert result["threshold_status"].startswith("PROVISIONAL")


def test_metric_sees_an_atmosphere_that_is_not_the_model():
    wrong_far = np.asarray(T_FAR) ** 2          # twice the optical depth
    result = gate.evaluate(*_boxes(T_NEAR, wrong_far), T_NEAR, T_FAR)
    assert result["ap_log_t_ratio_error"] > gate.PROVISIONAL_THRESHOLD
    assert result["at_or_under_provisional_threshold"] is False


def test_filmic_curve_bias_is_a_large_part_of_the_provisional_threshold():
    """Sizes the bias on a stand-in curve (not the engine's). It shows the
    0.15 threshold is not validated: the bias alone reaches about half of it."""
    errors = [gate.evaluate(*_boxes(T_NEAR, T_FAR, _aces, e, light), T_NEAR, T_FAR)["ap_log_t_ratio_error"]
              for e in (0.5, 1.0, 2.0) for light in (1.0, 1.6)]
    print("synthetic ACES-fit bias of ap_log_t_ratio_error:", [round(e, 3) for e in errors])
    assert max(errors) > 0.05                      # not negligible against 0.15
    assert max(errors) < gate.PROVISIONAL_THRESHOLD


def test_refuses_flat_boxes_and_frames_that_do_not_line_up():
    flat = np.full((64, 64, 3), 0.2)
    with pytest.raises(gate.Refused) as flat_error:
        gate.fit(flat, flat)
    assert flat_error.value.rule == "ap_gate.box_unusable"
    rng = np.random.default_rng(3)
    with pytest.raises(gate.Refused) as shuffled:
        gate.fit(rng.uniform(0.05, 0.5, (64, 64, 3)), rng.uniform(0.05, 0.5, (64, 64, 3)))
    assert shuffled.value.rule == "ap_gate.frames_misaligned"


CLEAR_DOC = {"scene": {"aerial_perspective_off": True},
             "look_applied": {"world": {"atmosphere": {"applied": "nothing: no visible sky atmosphere (-NoAerialPerspective)"}}}}
HAZED_DOC = {"scene": {"aerial_perspective_off": False},
             "look_applied": {"world": {"atmosphere": {
                 "mie_scattering_scale_per_km": 0.0021, "mie_absorption_scale_per_km": 0.00023,
                 "mie_scale_height_km": 1.5, "aerial_perspective_view_distance_scale": 1.0}}}}


def test_clear_frame_must_be_recorded_clear_by_the_run_itself():
    gate.check_runs(CLEAR_DOC, HAZED_DOC)
    # the switch on the command line without the atmosphere pass confirming it is not enough
    with pytest.raises(gate.Refused) as arrived_only:
        gate.check_runs({"scene": {"aerial_perspective_off": True}}, HAZED_DOC)
    assert arrived_only.value.rule == "ap_gate.clear_frame_not_clear"
    with pytest.raises(gate.Refused):
        gate.check_runs(HAZED_DOC, HAZED_DOC)
    with pytest.raises(gate.Refused) as both_clear:
        gate.check_runs(CLEAR_DOC, CLEAR_DOC)
    assert both_clear.value.rule == "ap_gate.hazed_frame_has_no_atmosphere"


def test_model_takes_the_mie_layer_the_run_recorded_and_names_what_is_assumed():
    overrides, scale, origin = gate.model_constants(HAZED_DOC)
    assert overrides == {"MIE_SCATTERING": 0.0021, "MIE_ABSORPTION": 0.00023, "MIE_SCALE_HEIGHT_KM": 1.5}
    assert scale == 1.0 and origin["MIE_SCATTERING"].startswith("render.json")
    assert origin["RAYLEIGH_SCATTERING"].startswith("ASSUMED")
    recorded = gate.model_transmittance(overrides, scale, 5000.0, 0.0, 40.0)
    assumed = gate.model_transmittance({}, 1.0, 5000.0, 0.0, 40.0)
    assert not np.allclose(recorded, assumed, rtol=1e-4)
    expected = np.exp(-(bake.RAYLEIGH_SCATTERING * math.exp(-5.0 / 8.0)
                        + (0.0021 + 0.00023) * math.exp(-5.0 / 1.5)) * 5.0)
    assert np.allclose(gate.model_transmittance(overrides, 1.0, 5000.0, 0.0, 5.0), expected, rtol=1e-3)
    # a run that recorded nothing falls back to the bake and says so
    _, _, bare = gate.model_constants({})
    assert all(v.startswith("ASSUMED") for v in bare.values())


def test_stash_copies_the_scenario_frame_and_render_json(tmp_path):
    runs = tmp_path / "runs"
    camera = runs / "webapp" / "abc" / "frames" / "chase"
    camera.mkdir(parents=True)
    (camera / "frame_0000.png").write_bytes(b"png")
    (camera / "frame_0000_beauty_post.png").write_bytes(b"post")
    (runs / "webapp" / "abc" / "frames" / "render.json").write_text("{}")
    (runs / "test_scenarios.json").write_text(json.dumps([{"number": 11, "name": "x", "run_id": "abc"}]))
    assert gate.REPO == REPO
    out = gate.stash(11, "clear", runs_dir=runs)
    assert Path(out["frame"]).read_bytes() == b"png" and Path(out["render_json"]).is_file()
    with pytest.raises(gate.Refused):
        gate.stash(4, "clear", runs_dir=runs)


def test_repo_hooks_the_windows_commands_rely_on_exist_in_source():
    """Source-level only: shows the names exist, not that a render honours them."""
    import ast
    tree = ast.parse((REPO / "scripts" / "run_test_scenarios.py").read_text(encoding="utf-8"))
    scenarios = next(ast.literal_eval(n.value) for n in tree.body
                     if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "SCENARIOS")
    name, prompt = scenarios[11 - 1][0], scenarios[11 - 1][1]     # --only is 1-based
    assert "matterhorn" in name.lower() and "5000 m" in prompt
    runner = (REPO / "scripts" / "run_test_scenarios.py").read_text(encoding="utf-8")
    assert "enumerate(SCENARIOS, 1)" in runner or "enumerate(SCENARIOS, start=1)" in runner
    assert 'RUNS = REPO / "runs" / "webapp"' in runner
    assert "FLIGHTSIM_RENDER_SWITCHES" in (REPO / "webapp" / "runs.py").read_text(encoding="utf-8")
    assert "$env:FLIGHTSIM_RENDER_SWITCHES = $Switches" in (REPO / "scripts" / "visual_fix_round.ps1").read_text(encoding="utf-8")
    private = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge" / "Private"
    commandlet = (private / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8", errors="replace")
    assert 'TEXT("aerial_perspective_off"), FParse::Param(*Params, TEXT("NoAerialPerspective"))' in commandlet
    clouds = (private / "FlightSimClouds.cpp").read_text(encoding="utf-8", errors="replace")
    assert gate.NO_ATMOSPHERE_PREFIX in clouds
    for key in list(gate.RENDER_JSON_CONSTANTS) + [gate.DISTANCE_SCALE_KEY]:
        assert f'TEXT("{key}")' in clouds, key


def test_lane_documents_do_not_overclaim():
    integration = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    summary = json.loads((LANE / "alpine_ap.json").read_text())
    assert summary["constants_status"] == "ASSUMED" and "ASSUMED" in summary["model"]
    for name in ("FLIGHTSIM_NO_AERIAL_PERSPECTIVE", "FLIGHTSIM_ALPINE_AP"):
        assert name not in integration, name       # variables that never existed
    assert "UNMEASURED" in integration and "NOT WRITTEN" in integration
    assert "PROVISIONAL" in integration
