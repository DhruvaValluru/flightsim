"""experiments/gate_v_visual.py on synthetic frames: each clause must pass
a frame built to have the property, fail one built without it, and its
self-validation control must trip (plan §5: "or the pass is void")."""

import json

import numpy as np
import pytest
from PIL import Image

from experiments import gate_v_visual as gv

H, W = 240, 320
HORIZON = 80
SKY = np.array([95.0, 145.0, 225.0])
GROUND = np.array([95.0, 110.0, 60.0])


def scene(*, haze=True, fill=True, clouds=0.0, airframe=True, specular=True,
          texture=True, gain=1.0, seed=1):
    """A camera over flat ground: sky above HORIZON, ground below with depth
    rising toward the horizon, Koschmieder-style haze, an airframe ellipse
    (ID 1) with or without a highlight, and optional cloud blobs."""
    rng = np.random.default_rng(seed)
    rgb = np.zeros((H, W, 3))
    depth = np.full((H, W), np.inf)
    rows = np.arange(H)[:, None].repeat(W, axis=1).astype(float)
    ground = rows > HORIZON
    depth[ground] = 300.0 * 120.0 / (rows[ground] - HORIZON)
    rgb[:] = SKY
    noise = rng.normal(0.0, 30.0 if texture else 0.0, size=(H, W))
    base = GROUND[None, None, :] + noise[..., None]
    t = np.exp(-depth / 15000.0) if haze else np.ones((H, W))
    mixed = base * t[..., None] + SKY * (1.0 - t[..., None])
    rgb[ground] = mixed[ground]
    if not fill:
        # the 40 km island: the first 20 rows under the horizon are empty sky
        empty = ground & (rows <= HORIZON + 20)
        rgb[empty] = SKY
        depth[empty] = np.inf
    if clouds > 0:
        sky_rows = HORIZON - 1
        n = int(round(clouds * sky_rows))
        rgb[:n, :] = (215.0, 215.0, 220.0)
    ids = np.zeros((H, W), dtype=np.int64)
    if airframe:
        yy, xx = np.mgrid[0:H, 0:W]
        body = ((xx - 160) / 70.0) ** 2 + ((yy - 170) / 22.0) ** 2 <= 1.0
        ids[body] = 1
        rgb[body] = (110.0, 112.0, 118.0)
        depth[body] = 40.0
        if specular:
            spot = ((xx - 150) / 10.0) ** 2 + ((yy - 162) / 4.0) ** 2 <= 1.0
            rgb[spot & body] = (250.0, 250.0, 250.0)
    rgb = np.clip(rgb * gain, 0.0, 255.0)
    return rgb, ids, depth


def level(row=HORIZON):
    return np.full(W, float(row))


# -- aerial perspective ------------------------------------------------------


def test_aerial_perspective_passes_a_hazy_ramp_and_its_shuffle_control_trips():
    rgb, ids, depth = scene()
    clause = gv.measure_aerial_perspective(rgb, depth, ids)
    assert clause.status == gv.PASS, clause.values
    assert clause.values["blue_slope_per_decade"] > gv.AP_MIN_BLUE_SLOPE
    assert clause.values["contrast_ratio_far_near"] < gv.AP_MAX_CONTRAST_RATIO
    assert clause.control["note"] == "the control tripped"


def test_aerial_perspective_fails_without_haze():
    rgb, ids, depth = scene(haze=False)
    assert gv.measure_aerial_perspective(rgb, depth, ids).status == gv.FAIL


def test_aerial_perspective_is_not_run_without_depth():
    rgb, ids, _ = scene()
    clause = gv.measure_aerial_perspective(rgb, None, ids)
    assert clause.status == gv.NOT_RUN and "depth" in clause.basis


# -- horizon -----------------------------------------------------------------


def test_horizon_fill_passes_a_filled_horizon_and_fails_the_island():
    rgb, ids, depth = scene()
    good = gv.measure_horizon_fill(rgb, depth, ids, level(), "test")
    assert good.status == gv.PASS, good.values
    assert good.control["note"] == "the control tripped"
    rgb, ids, depth = scene(fill=False)
    bad = gv.measure_horizon_fill(rgb, depth, ids, level(), "test")
    assert bad.status == gv.FAIL and bad.values["fill"] < gv.HORIZON_MIN_FILL


def test_horizon_fill_without_depth_reads_sky_coloured_pixels_as_empty():
    rgb, ids, _ = scene(fill=False)
    clause = gv.measure_horizon_fill(rgb, None, ids, level(), "test")
    assert clause.status == gv.FAIL
    assert clause.values["fill_source"].startswith("colour")


def test_a_heuristic_horizon_is_reported_never_graded():
    rgb, ids, depth = scene()
    clause = gv.measure_horizon_fill(rgb, depth, ids, level(), "heuristic")
    assert clause.status == gv.NOT_RUN and "fill" in clause.values


def test_heuristic_horizon_finds_the_sky_ground_step():
    rgb, ids, _ = scene(haze=False)
    row = gv.heuristic_horizon_row(rgb, ids)
    assert abs(row - (HORIZON + 1)) <= 2


def test_polyline_interpolates_per_column():
    rows = gv.horizon_rows_from_polyline([[0, 10], [100, 30]], 101)
    assert rows[0] == pytest.approx(10.1) and rows[-1] == pytest.approx(30.0)


# -- clouds ------------------------------------------------------------------


@pytest.mark.parametrize("cover", [0.0, 0.5, 0.9])
def test_cloud_fraction_tracks_the_expected_cover(cover):
    rgb, ids, depth = scene(clouds=cover)
    clause = gv.measure_cloud(rgb, depth, ids, level(), cover, "test")
    assert clause.status == gv.PASS, clause.values
    assert clause.values["cloud_fraction"] == pytest.approx(cover, abs=0.05)
    assert clause.control["note"] == "the control tripped"


def test_cloud_fraction_fails_a_clear_sky_under_an_overcast_forecast():
    rgb, ids, depth = scene(clouds=0.0)
    assert gv.measure_cloud(rgb, depth, ids, level(), 0.8, "test").status == gv.FAIL


def test_cloud_fraction_without_an_expected_cover_reports_and_does_not_grade():
    rgb, ids, depth = scene(clouds=0.3)
    clause = gv.measure_cloud(rgb, depth, ids, level(), None, "none")
    assert clause.status == gv.NOT_RUN
    assert clause.values["cloud_fraction"] == pytest.approx(0.3, abs=0.05)


# -- exposure ----------------------------------------------------------------


def test_exposure_passes_a_normal_frame_and_fails_a_blown_one():
    rgb, _, _ = scene(clouds=0.3)
    good = gv.measure_exposure(rgb)
    assert good.status == gv.PASS, good.values
    assert good.control["note"] == "the control tripped"
    blown = gv.measure_exposure(scene(gain=3.0)[0])
    assert blown.status == gv.FAIL
    assert blown.values["clipped_fraction"] > gv.EXPOSURE_MAX_CLIP_FRACTION


def test_exposure_fails_a_dark_frame():
    assert gv.measure_exposure(scene(gain=0.3)[0]).status == gv.FAIL


# -- texel detail ------------------------------------------------------------


def test_texel_detail_passes_texture_and_fails_a_smooth_ground():
    rgb, ids, depth = scene()
    good = gv.measure_texel_detail(rgb, depth, ids)
    assert good.status == gv.PASS, good.values
    assert good.control["note"] == "the control tripped"
    rgb, ids, depth = scene(texture=False)
    assert gv.measure_texel_detail(rgb, depth, ids).status == gv.FAIL


# -- specular ----------------------------------------------------------------


def test_specular_needs_a_highlight_on_the_airframe():
    rgb, ids, _ = scene()
    good = gv.measure_specular(rgb, ids)
    assert good.status == gv.PASS, good.values
    assert good.control["note"] == "the control tripped"
    rgb, ids, _ = scene(specular=False)
    assert gv.measure_specular(rgb, ids).status == gv.FAIL


def test_specular_is_not_run_without_a_mask():
    rgb, _, _ = scene()
    assert gv.measure_specular(rgb, None).status == gv.NOT_RUN


# -- control voiding ---------------------------------------------------------


def test_a_control_that_passes_voids_the_clause():
    def always(**_):
        return {"passed": True, "x": 1.0}

    clause = gv._graded("demo", always, {}, {}, "basis")
    assert clause.status == gv.VOID


def test_a_passing_control_never_hides_a_fail():
    # p90 luma ~37: far under EXPOSURE_P90_MIN; its x4 control lands in band.
    rgb = np.random.default_rng(0).uniform(5.0, 45.0, (200, 200, 3))
    clause = gv.measure_exposure(rgb)
    assert clause.status == gv.FAIL, clause.control
    assert "FAIL stands" in clause.control["note"]


# -- edge aliasing is Gate 6's number ---------------------------------------


def test_edge_aliasing_is_gate6_s_measurement():
    from experiments.gate6_visual import measure_edge_aliasing

    rgb, ids, _ = scene()
    clause = gv.measure_aliasing(rgb, ids)
    expected = measure_edge_aliasing(np.moveaxis(np.rint(rgb).astype(np.int64), 2, 0), ids > 0)
    assert clause.values["energy"] == pytest.approx(expected["energy"])
    assert clause.status in (gv.INFO, gv.VOID)


# -- the tree, the CLI and --compare ----------------------------------------


def write_step(directory, *, haze=True, clouds=0.4, with_depth=True):
    directory.mkdir(parents=True, exist_ok=True)
    rgb, ids, depth = scene(haze=haze, clouds=clouds)
    Image.fromarray(np.rint(rgb).astype(np.uint8)).save(directory / "a.png")
    Image.fromarray(ids.astype(np.uint8)).save(directory / "a_mask.png")
    if with_depth:
        depth.astype("<f4").tofile(directory / "a_depth.f32")
    (directory / "a_horizon.json").write_text(
        json.dumps({"polyline_px": [[0, HORIZON], [W, HORIZON]]}), encoding="utf-8")
    (directory / "shots.json").write_text(
        json.dumps({"shots": {"a": {"expected_cloud_cover": clouds}}}), encoding="utf-8")


def test_measure_tree_reads_the_contact_sheet_layout(tmp_path):
    write_step(tmp_path / "v0")
    report = gv.measure_tree(tmp_path / "v0")
    shot = report["shots"]["a"]
    assert shot["depth"].endswith("a_depth.f32")
    assert shot["horizon"] == "a_horizon.json"
    assert shot["expected_cloud"] == "shots.json expected_cloud_cover"
    statuses = {name: c["status"] for name, c in shot["clauses"].items()}
    for name in ("aerial_perspective", "horizon_fill", "cloud_fraction", "exposure",
                 "texel_detail", "specular"):
        assert statuses[name] == gv.PASS, (name, shot["clauses"][name])
    assert set(report["thresholds"]) == set(gv.UNCALIBRATED)


def test_bundle_layout_is_discovered(tmp_path):
    rgb, _, _ = scene()
    Image.fromarray(np.rint(rgb).astype(np.uint8)).save(tmp_path / "frame_0000.png")
    Image.fromarray(np.zeros((H, W), np.uint8)).save(tmp_path / "frame_0000_mask.png")
    assert [k for k, _ in gv.discover_shots(tmp_path)] == ["frame_0000"]


def test_cli_skip_render_and_compare(tmp_path, capsys):
    write_step(tmp_path / "before", haze=False)
    write_step(tmp_path / "after", haze=True)
    assert gv.main(["--step", "after", "--skip-render", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "after" / gv.REPORT_NAME).is_file()
    assert "UNCALIBRATED" in capsys.readouterr().out
    assert gv.main(["--compare", "before", "after", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "aerial_perspective" in out and "FAIL -> PASS" in out
    comparison = json.loads((tmp_path / "gate_v_compare_before_vs_after.json").read_text())
    delta = comparison["shots"]["a"]["aerial_perspective"]["delta"]
    assert delta["blue_slope_per_decade"]["delta"] > 0


def test_cli_overrides_the_expected_cloud(tmp_path):
    write_step(tmp_path / "v0", clouds=0.0)
    assert gv.main(["--step", "v0", "--skip-render", "--root", str(tmp_path),
                    "--expect-cloud", "a=0.9"]) == 0
    report = json.loads((tmp_path / "v0" / gv.REPORT_NAME).read_text())
    assert report["shots"]["a"]["clauses"]["cloud_fraction"]["status"] == gv.FAIL


def test_missing_step_is_not_run(tmp_path, capsys):
    assert gv.main(["--step", "nope", "--skip-render", "--root", str(tmp_path)]) == 2
    assert "NOT RUN" in capsys.readouterr().out


def test_every_threshold_is_named_uncalibrated_in_the_source():
    source = open(gv.__file__, encoding="utf-8").read()
    for name in gv.UNCALIBRATED:
        line = next(l for l in source.splitlines() if l.startswith(f"{name} ="))
        assert "UNCALIBRATED" in line or name == "CLOUD_TOLERANCE", line
