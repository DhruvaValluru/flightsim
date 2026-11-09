"""core/scene/look_match.py and experiments/look_match.py on synthetic frames
(reference-frames lane, 2026-11-09). No engine: every frame here is drawn."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.scene import beauty_look, look_match as lm, world_beauty

ROOT = Path(__file__).resolve().parents[1]
H, W = 96, 128


# -- colour science ------------------------------------------------------------


@pytest.mark.parametrize("lab1, lab2, expected", [
    # Sharma, Wu & Dalal (2005), Table 1, pairs 1-4.
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, -1.3802, -84.2814), (50.0, 0.0, -82.7485), 1.0000),
    # pair 17 and 25 (hue wrap and a neutral)
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
])
def test_ciede2000_matches_sharma_reference_pairs(lab1, lab2, expected):
    assert lm.ciede2000(lab1, lab2) == pytest.approx(expected, abs=1e-4)
    assert lm.ciede2000(lab2, lab1) == pytest.approx(expected, abs=1e-4)


def test_srgb_white_and_grey_in_lab():
    lab = lm.srgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [119, 119, 119]], dtype=np.uint8))
    assert lab[0] == pytest.approx([100.0, 0.0, 0.0], abs=0.01)
    assert lab[1] == pytest.approx([0.0, 0.0, 0.0], abs=0.01)
    assert lab[2][0] == pytest.approx(50.0, abs=0.5) and abs(lab[2][1]) < 0.01
    # a float array is already 0..1, an integer one is 8-bit
    assert lm.srgb_to_linear(np.array([1.0])) == pytest.approx([1.0])
    assert lm.srgb_to_linear(np.array([1], dtype=np.uint8)) == pytest.approx([1 / 255 / 12.92])


# -- a synthetic shot ----------------------------------------------------------


def _scene(seed=0):
    """(linear rgb (h, w, 3), ID mask, depth): sky above row 36, textured
    ground below with depth falling toward the horizon, a grey aircraft."""
    rng = np.random.default_rng(seed)
    rows = np.arange(H)[:, None] * np.ones((1, W))
    sky = rows < 36
    depth = np.where(sky, np.inf, 200.0 + 30000.0 / np.maximum(rows - 30.0, 1.0))
    lin = np.zeros((H, W, 3))
    lin[sky] = [0.25, 0.35, 0.6]
    # cloud streaks in the sky: brighter bands
    cloud = sky & (np.sin(np.arange(W)[None, :] / 6.0 + rows / 5.0) > 0.5)
    lin[cloud] = [0.7, 0.7, 0.72]
    texture = 0.05 + 0.25 * rng.random((H, W))
    shade = np.where(rng.random((H, W)) < 0.25, 0.15, 1.0)  # a quarter in shadow
    ground = ~sky
    lin[ground] = np.stack([texture, texture * 0.9, texture * 0.6], -1)[ground] * shade[ground][:, None]
    ids = np.zeros((H, W), dtype=np.uint8)
    ids[50:62, 50:80] = 1
    lin[ids == 1] = [0.3, 0.3, 0.32]
    return lin, ids, depth


def _encode(linear):
    v = np.clip(linear, 0.0, 1.0)
    s = np.where(v <= 0.0031308, 12.92 * v, 1.055 * v ** (1 / 2.4) - 0.055)
    return np.round(s * 255.0).astype(np.uint8)


def _current(**extra):
    plan = beauty_look.plan_beauty_look(30.0, fps=30.0, width_px=W)
    current = lm.current_look({"look_applied": {"world_beauty": {"preset": "clear"}}}, plan)
    current.update(extra)
    return current


def _suggest(ref_lin, rt_lin, ids, depth, **extra):
    masks = lm.region_masks(ids, depth)
    comparison = lm.compare(_encode(ref_lin), _encode(rt_lin), masks, depth)
    return comparison, lm.suggest(comparison, _current(**extra))


def _constants(result):
    return {row["constant"]: row for row in result["suggestions"]}


def test_regions_split_sky_ground_aircraft():
    _, ids, depth = _scene()
    masks = lm.region_masks(ids, depth)
    assert set(masks) == {"sky", "ground", "aircraft"}
    assert masks["sky"].sum() == 36 * W
    assert masks["aircraft"].sum() == 12 * 30
    assert not (masks["sky"] & masks["ground"]).any()
    assert (masks["sky"] | masks["ground"] | masks["aircraft"]).all()
    no_depth = lm.region_masks(ids, None)
    assert set(no_depth) == {"aircraft", "scene"}


def test_identical_frames_converge_with_no_suggestion():
    lin, ids, depth = _scene()
    comparison, result = _suggest(lin, lin, ids, depth)
    assert result["suggestions"] == []
    for row in comparison["regions"].values():
        assert row["diff"]["luminance_stops"] == pytest.approx(0.0)
        assert row["diff"]["delta_e00_per_pixel_mean"] == pytest.approx(0.0)
    assert any(line.startswith("exposure") for line in result["within_tolerance"])


def test_a_brighter_realtime_frame_raises_the_ev100():
    lin, ids, depth = _scene()
    _, result = _suggest(lin, lin * 2.0, ids, depth)  # one stop over, before the clip
    row = _constants(result)["beauty_look.exposure.ev100"]
    stops = row["metric"]["lit_luminance_stops"]
    assert 0.6 < stops <= 1.05
    assert row["to"] == pytest.approx(row["from"] + lm.EXPOSURE_GAIN * stops, abs=1e-3)
    assert result["beauty_look"]["exposure"]["ev100"] == row["to"]
    # a darker one lowers it
    _, result = _suggest(lin, lin * 0.5, ids, depth)
    row = _constants(result)["beauty_look.exposure.ev100"]
    assert row["to"] < row["from"]


def test_a_colour_cast_moves_color_gain_toward_the_reference():
    lin, ids, depth = _scene()
    warm = lin * np.array([1.25, 1.0, 0.75])
    _, result = _suggest(lin, warm, ids, depth)
    row = _constants(result)["beauty_look.color_grade.ColorGain"]
    before, after = row["from"], row["to"]
    assert after[0] < before[0] and after[2] > before[2]   # cool the warm frame
    assert after[3] == before[3]
    assert result["color_grade"]["ColorGain"] == after
    for b, a in zip(before[:3], after[:3]):
        assert lm.GAIN_STEP_CLAMP[0] - 1e-9 <= a / b <= lm.GAIN_STEP_CLAMP[1] + 1e-9


def test_a_desaturated_frame_raises_color_saturation():
    lin, ids, depth = _scene()
    grey = lm.luminance(lin)[..., None]
    flat = grey + 0.5 * (lin - grey)
    _, result = _suggest(lin, flat, ids, depth)
    row = _constants(result)["beauty_look.color_grade.ColorSaturation"]
    assert row["to"][3] > row["from"][3]


def test_deeper_shadows_raise_the_sky_light():
    lin, ids, depth = _scene()
    rng = np.random.default_rng(0)
    rng.random((H, W))  # the texture draw
    shadow = rng.random((H, W)) < 0.25
    darker = lin.copy()
    ground = np.isfinite(depth) & (ids == 0)
    darker[shadow & ground] *= 0.4    # the same shadows, a stop and a third deeper
    _, result = _suggest(lin, darker, ids, depth)
    row = _constants(result)["-sky-light-scale"]
    assert row["metric"]["lit_shadow_depth_stops"] > lm.SHADOW_TOLERANCE_STOPS
    assert row["to"] > row["from"] == 1.0
    assert result["command_flags"] == [f"-sky-light-scale={row['to']:g}"]


def test_a_crisper_far_ground_asks_for_more_aerial_perspective():
    lin, ids, depth = _scene()
    far = lm.far_ground_mask(lm.region_masks(ids, depth)["ground"], depth)
    ref = lin.copy()
    haze = np.array([0.3, 0.33, 0.4])
    ref[far] = 0.5 * ref[far] + 0.5 * haze      # the reference's far ground is hazier
    _, result = _suggest(ref, lin, ids, depth)
    key = "world_beauty.atmosphere.clear.aerial_perspective_scale"
    row = _constants(result)[key]
    assert row["from"] == world_beauty.ATMOSPHERE["clear"]["aerial_perspective_scale"]
    assert row["to"] > row["from"]
    assert result["world_overrides"]["atmosphere"]["clear"]["aerial_perspective_scale"] == row["to"]
    assert world_beauty.validate_overrides(result["world_overrides"]) == []


def test_flatter_clouds_raise_the_cloud_extinction():
    lin, ids, depth = _scene()
    flat = lin.copy()
    sky = ~np.isfinite(depth)
    mean = flat[sky].mean(axis=0)
    flat[sky] = mean + 0.4 * (flat[sky] - mean)
    _, result = _suggest(lin, flat, ids, depth)
    row = _constants(result)["world_beauty.constants.cloud_extinction_scale"]
    assert row["to"] > row["from"] == world_beauty.CLOUD_EXTINCTION_SCALE
    assert world_beauty.validate_overrides(result["world_overrides"]) == []


def test_a_uniform_sky_is_not_judged_for_clouds():
    lin, ids, depth = _scene()
    lin[~np.isfinite(depth)] = [0.25, 0.35, 0.6]
    _, result = _suggest(lin, lin, ids, depth)
    assert any(line.startswith("clouds: the reference sky is uniform") for line in result["not_judged"])


def test_shapes_must_match():
    lin, ids, depth = _scene()
    masks = lm.region_masks(ids, depth)
    with pytest.raises(lm.LookMatchError) as err:
        lm.compare(_encode(lin), _encode(lin)[:, :-1], masks, depth)
    assert err.value.constraint == "look_match.not_same_shot"


# -- the bundle on disk and the CLI ----------------------------------------------


def _bundle(directory: Path, linear, ids, depth, quality, extra=None):
    directory.mkdir(parents=True, exist_ok=True)
    frame = directory / "frame_0000.png"
    Image.fromarray(_encode(linear)).save(frame)
    Image.fromarray(ids).save(directory / "frame_0000_mask.png")
    depth.astype("<f4").tofile(directory / "frame_0000_depth.f32")
    render = {"scene": {"render_quality": quality},
              "objects": [{"int_id": 1, "class": "aircraft"}],
              "look_applied": {"world_beauty": {"preset": "clear"},
                               "lighting": {"sky_light_scale": 1.0}}}
    if quality == "beauty":
        render["beauty_look"] = {"plan": beauty_look.plan_beauty_look(30.0, fps=30.0, width_px=W)}
    render.update(extra or {})
    (directory / "render.json").write_text(json.dumps(render), encoding="utf-8")
    return frame


def test_match_on_disk_writes_files_the_loaders_accept(tmp_path):
    lin, ids, depth = _scene()
    ref = _bundle(tmp_path / "pt", lin, ids, depth, "pathtrace")
    rt = _bundle(tmp_path / "rt", lin * np.array([1.6, 1.3, 1.0]), ids, depth, "beauty")
    report = lm.match(ref, rt)
    assert report["format"] == lm.LOOK_MATCH_FORMAT
    assert report["labels"]["aircraft_int_ids"] == [1]
    assert not report["converged"]
    written = lm.write_outputs(report, tmp_path / "out")
    plan = json.loads(Path(written["beauty_look"]).read_text(encoding="ascii"))
    assert plan["beauty_look_version"] == beauty_look.BEAUTY_LOOK_VERSION
    assert plan["exposure"]["ev100"] > beauty_look.plan_beauty_look(30.0, fps=30.0, width_px=W)["exposure"]["ev100"]
    overrides = json.loads(Path(written["world_beauty_overrides"]).read_text(encoding="utf-8"))
    assert world_beauty.validate_overrides(overrides) == []
    json.loads(Path(written["report"]).read_text(encoding="utf-8"))


def test_match_refuses_the_wrong_qualities_and_another_pose(tmp_path):
    lin, ids, depth = _scene()
    ref = _bundle(tmp_path / "a", lin, ids, depth, "beauty")
    rt = _bundle(tmp_path / "b", lin, ids, depth, "beauty")
    with pytest.raises(lm.LookMatchError) as err:
        lm.match(ref, rt)
    assert err.value.constraint == "look_match.quality"
    ref = _bundle(tmp_path / "c", lin, ids, depth * 1.5, "pathtrace")
    with pytest.raises(lm.LookMatchError) as err:
        lm.match(ref, rt)
    assert err.value.constraint == "look_match.not_same_shot"
    (tmp_path / "b" / "frame_0000_mask.png").unlink()
    (tmp_path / "c" / "frame_0000_mask.png").unlink()
    with pytest.raises(lm.LookMatchError) as err:
        lm.match(tmp_path / "c" / "frame_0000.png", rt)
    assert err.value.constraint in ("look_match.inputs", "look_match.not_same_shot")


def test_a_truncated_reference_depth_refuses_by_name(tmp_path):
    lin, ids, depth = _scene()
    ref = _bundle(tmp_path / "ref", lin, ids, depth, "pathtrace")
    rt = _bundle(tmp_path / "rt", lin, ids, depth, "beauty")
    raw = (tmp_path / "ref" / "frame_0000_depth.f32").read_bytes()
    (tmp_path / "ref" / "frame_0000_depth.f32").write_bytes(raw[: len(raw) // 2])
    with pytest.raises(lm.LookMatchError) as err:
        lm.match(ref, rt)
    assert err.value.constraint == "look_match.inputs"


def test_existing_world_overrides_are_merged(tmp_path):
    lin, ids, depth = _scene()
    ref = _bundle(tmp_path / "pt", lin, ids, depth, "pathtrace")
    rt = _bundle(tmp_path / "rt", lin, ids, depth, "beauty")
    existing = tmp_path / "probe.json"
    existing.write_text(json.dumps({"atmosphere": {"clear": {"mie_share": 0.4}}}), encoding="utf-8")
    report = lm.match(ref, rt, world_overrides_path=existing)
    assert report["world_beauty_overrides"]["atmosphere"]["clear"]["mie_share"] == 0.4
    assert report["converged"]


def test_cli_from_contact_sheet_steps(tmp_path, monkeypatch, capsys):
    import experiments.look_match as cli

    lin, ids, depth = _scene()
    ref = _bundle(tmp_path / "runs" / "pt", lin, ids, depth, "pathtrace")
    rt = _bundle(tmp_path / "runs" / "rt", lin * 1.8, ids, depth, "beauty")
    for step, frame in (("head_pt", ref), ("head", rt)):
        (tmp_path / "visual" / step).mkdir(parents=True)
        (tmp_path / "visual" / step / "shots.json").write_text(
            json.dumps({"shots": {"a": {"frame": str(frame)}}}), encoding="utf-8")
    monkeypatch.setattr(cli, "VISUAL_ROOT", tmp_path / "visual")
    assert cli.main(["--steps", "head_pt", "head", "--shot", "a", "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "suggest beauty_look.exposure.ev100" in out
    assert (tmp_path / "o" / "beauty_look.json").is_file()
    assert cli.main(["--reference", str(tmp_path / "nope.png"), "--realtime", str(rt)]) == 3
    assert "REFUSED -- look_match.inputs:" in capsys.readouterr().out


def test_every_constant_is_listed_uncalibrated():
    source = (ROOT / "core" / "scene" / "look_match.py").read_text(encoding="utf-8")
    block = source[source.index("# -- the constants"):source.index("UNCALIBRATED: Tuple")]
    names = re.findall(r"^([A-Z][A-Z0-9_]+) = ", block, re.M)
    assert names and set(names) == set(lm.UNCALIBRATED)
