"""Source-level checks for the alpine terrain detail-normals lane (Mac).

These check the bake (tileability, unit normals, slope targets, the BC5/DDS
encoding, the fade arithmetic, the committed hashes) and the pixel gate's
arithmetic on synthetic images. They are NOT a render or pixel result: that
is measured on the Windows laptop (see the lane's INTEGRATION.md).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import struct
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[1]
LANE = REPO / "swarm" / "lanes" / "terrain" / "detail_normals" / "alpine"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"alpine_dn_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


bake = _load("bake_alpine_detail_normals")
gate = _load("measure_detail_gsd")
runner = _load("run_gate")


@pytest.fixture(scope="module")
def layers():
    return {name: bake.bake_layer(name, bake.TIERS[0][name]) for name in ("rock", "snow")}


def test_normals_are_unit_and_hit_the_slope_target(layers):
    for name, baked in layers.items():
        n = baked["normals"]
        assert np.allclose(np.linalg.norm(n, axis=-1), 1.0, atol=1e-9)
        assert (n[..., 2] > 0.0).all()
        slope = np.hypot(n[..., 0], n[..., 1]) / n[..., 2]
        assert math.sqrt(float(np.mean(slope ** 2))) == pytest.approx(bake.LAYERS[name]["rms_slope"], rel=1e-6)
        # flat sunlit ground darkens by 1 - mean(N.z): small, and reported
        assert 1.0 - baked["mean_nz"] < 0.5 * bake.LAYERS[name]["rms_slope"] ** 2 + 1e-3


def test_maps_tile_without_a_seam(layers):
    for baked in layers.values():
        n = baked["normals"][..., :2]
        wrap_x = np.abs(n[:, 0] - n[:, -1]).mean()
        inner_x = np.abs(np.diff(n, axis=1)).mean()
        wrap_y = np.abs(n[0] - n[-1]).mean()
        inner_y = np.abs(np.diff(n, axis=0)).mean()
        assert wrap_x < 1.5 * inner_x and wrap_y < 1.5 * inner_y


def test_layers_are_anisotropic_the_way_the_json_says(layers):
    # snow: sastrugi run along +U, so it varies slowly along U and fast along V
    snow = layers["snow"]["normals"]
    assert np.abs(snow[..., 0]).mean() < 0.5 * np.abs(snow[..., 1]).mean()
    rock = layers["rock"]["normals"]
    assert np.abs(rock[..., 1]).mean() < np.abs(rock[..., 0]).mean()


def test_every_resolution_carries_the_same_surface():
    lo = bake.synth_height(256, bake.LAYERS["snow"])
    hi = bake.synth_height(512, bake.LAYERS["snow"])
    assert np.corrcoef(lo.ravel(), hi[::2, ::2].ravel())[0, 1] > 0.999


def test_bc5_round_trip_is_close(layers):
    for baked in layers.values():
        top = baked["mips_xy"][0]
        back = bake.bc5_decode(bake.bc5_encode(top), *top.shape[:2])
        err = back.astype(float) - top.astype(float)
        assert math.sqrt(float(np.mean(err ** 2))) < 2.0  # 8-bit levels
        assert np.abs(err).max() <= 24


def test_bc5_flat_and_small_blocks():
    flat = np.full((4, 4, 2), 128, dtype=np.uint8)
    assert (bake.bc5_decode(bake.bc5_encode(flat), 4, 4) == 128).all()
    one = np.array([[[10, 200]]], dtype=np.uint8)
    data = bake.bc5_encode(one)
    assert len(data) == 16
    assert (bake.bc5_decode(data, 1, 1) == one).all()


def test_dds_header_and_size(layers):
    for name, baked in layers.items():
        dds, edge = baked["dds"], baked["edge"]
        assert dds[:4] == b"DDS "
        size, _flags, hgt, wid, linear, _depth, mips = struct.unpack_from("<7I", dds, 4)
        assert (size, hgt, wid) == (124, edge, edge)
        assert mips == int(math.log2(edge)) + 1 == len(baked["mips_xy"])
        assert dds[84:88] == b"DX10"
        assert struct.unpack_from("<5I", dds, 128) == (83, 3, 0, 1, 0)
        payload = sum(max(1, (edge >> m) // 4 or 1) ** 2 * 16 for m in range(mips))
        assert linear == (edge // 4) ** 2 * 16
        assert len(dds) == 148 + payload


def test_mips_flatten_toward_the_far_field(layers):
    for baked in layers.values():
        lengths = baked["mip_normal_length"]
        assert lengths[0] == 1.0 and max(lengths) <= 1.0 and min(lengths) < 1.0
        last = baked["mips_xy"][-1].astype(int)
        assert np.abs(last - 128).max() <= 2  # the 1x1 mip is a flat normal


def test_fade_distances_follow_the_capture():
    foot = bake.footprint_m_per_px(1000.0)
    assert foot == pytest.approx(2000.0 * math.tan(math.radians(27.2)) / 1280)
    fade = bake.fade_distances(48.0, (8.0, 64.0))
    # at fade_end the longest wavelength spans exactly two pixels
    assert bake.footprint_m_per_px(fade["fade_end_m"]) * 2.0 == pytest.approx(6.0, rel=1e-3)
    assert fade["fade_start_m"] == pytest.approx(fade["fade_end_m"] / 4.0, abs=0.1)


def test_tiers_grow_and_tier0_is_small():
    plans = [bake.tier_plan(t) for t in sorted(bake.TIERS)]
    vram = [p["est_vram_mb"] for p in plans]
    taps = [p["texture_taps_per_pixel"] for p in plans]
    assert vram == sorted(vram) and taps == sorted(taps)
    assert vram[0] < 1.0 and taps[0] == 2
    assert vram[-1] < 0.05 * 491  # even tier 3 is a sliver of the 491 MB pool
    assert "rock_far" not in plans[0]["layers"] and "rock_far" in plans[1]["layers"]


def test_committed_outputs_match_the_generator(tmp_path):
    plan = bake.build(0, tmp_path)
    committed = json.loads((LANE / "out" / "alpine_detail_t0.json").read_text())
    assert plan == committed
    prov = json.loads((LANE / "PROVENANCE.json").read_text())
    listed = {g["file"]: g["sha256"] for g in prov["generated"]}
    for fname, sha in plan["files_sha256"].items():
        on_disk = hashlib.sha256((LANE / "out" / fname).read_bytes()).hexdigest()
        assert on_disk == sha == listed[f"out/{fname}"]
    assert prov["label"] == "visual-only" and prov["vendored"] == []
    for source in prov["sources"]:
        assert "non-commercial" not in source["licence"].lower()


# ------------------------------------------------------------ the pixel gate
# Synthetic frames only: these check the gate's arithmetic and its refusals.
# They say nothing about a rendered frame.
HGT, WID = 320, 480
NEAR_MAX, FAR_MIN = 1868.0, 7471.8


def _blur(field, passes):
    for _ in range(passes):
        field = (field + np.roll(field, 1, 0) + np.roll(field, 1, 1) + np.roll(field, (1, 1), (0, 1))) / 4.0
    return field / field.std()


def _depth(near_m: float = 700.0, airframe: bool = True):
    """Sky above row 60, ground from 20 km at the skyline down to ``near_m``
    at the bottom row, and an airframe 40 m away in the middle."""
    depth = np.full((HGT, WID), np.inf, dtype=np.float32)
    depth[60:] = np.geomspace(20000.0, near_m, HGT - 60, dtype=np.float32)[:, None]
    if airframe:
        depth[130:190, 200:280] = 40.0
    return depth


def _frame(relief: float = 0.0, noise: float = 0.0, far_gain: float = 0.0, shift: int = 0, seed: int = 3,
           jitter: float = 0.0):
    """Blurred ground under a flat sky. ``relief``: fine but multi-pixel
    texture in the near rows; ``noise``: per-pixel noise there instead."""
    rng = np.random.default_rng(seed)
    lum = 120.0 + 50.0 * _blur(rng.normal(size=(HGT, WID)), 8)
    white = np.random.default_rng(seed + 1).normal(size=(HGT, WID))
    lum[200:] += relief * _blur(white, 1)[200:] + noise * white[200:]
    lum[60:110] += far_gain * white[60:110]
    lum += jitter * np.random.default_rng(seed + 2).normal(size=(HGT, WID))
    lum[: 60 + shift] = 215.0
    return np.repeat(np.clip(lum, 0, 255).astype(np.uint8)[..., None], 3, axis=2)


def _gate(candidate, repeat=None, depth=None):
    return gate.gate(_frame(), _frame() if repeat is None else repeat, candidate,
                     _depth() if depth is None else depth, NEAR_MAX, FAR_MIN)


def test_gate_picks_its_own_regions_from_depth():
    result = _gate(_frame(relief=10.0))
    x0, y0, x1, y1 = result["near_box"]
    assert (x1 - x0, y1 - y0) == (gate.BOX_PX, gate.BOX_PX) and y1 == HGT   # the nearest ground is the bottom
    assert 700.0 <= result["near_range_m"] <= NEAR_MAX
    assert result["far_pixels"] > gate.FAR_MIN_PIXELS and result["skyline_columns"] == WID
    assert result["not_checked"] == []


def test_gate_passes_provisionally_on_coherent_near_relief():
    result = _gate(_frame(relief=10.0))
    assert result["gsd_ratio"] < gate.GSD_RATIO_MAX
    assert result["diff_coherence"] > 0.3
    assert result["far_mean_abs"] == 0.0 and result["skyline_shift"] == 0.0
    assert result["status"] == "provisional_pass" and result["thresholds_provisional"]
    assert gate.EXIT[result["status"]] == 0


def test_gate_fails_per_pixel_noise_that_raises_f95():
    result = _gate(_frame(noise=10.0))
    assert result["gsd_ratio"] < gate.GSD_RATIO_MAX          # f95 alone would have passed it
    assert not result["checks"]["diff_coherence"] and result["status"] == "fail"


def test_gate_names_an_unwired_switch():
    result = _gate(_frame())
    assert result["status"] == "fail" and result["reason"].startswith("no_effect")
    assert gate.EXIT[result["status"]] == 1


def test_gate_is_not_applicable_when_the_ground_is_too_far():
    result = _gate(_frame(relief=10.0), depth=_depth(near_m=3000.0))
    assert result["status"] == "not_applicable" and "beyond 1868 m" in result["reason"]
    assert gate.EXIT[result["status"]] == 2


def test_gate_is_not_applicable_when_the_off_frames_disagree():
    result = _gate(_frame(relief=10.0), repeat=_frame(jitter=6.0))
    assert result["status"] == "not_applicable" and "detail-off frames differ" in result["reason"]


def test_gate_never_takes_the_airframe_for_ground():
    depth = _depth()
    depth[HGT - 110:, :] = 40.0                               # everything near is airframe
    x0, y0, x1, y1 = _gate(_frame(relief=10.0), depth=depth)["near_box"]
    assert y1 <= HGT - 110


def test_gate_fails_when_the_far_field_changes():
    result = _gate(_frame(relief=10.0, far_gain=12.0))
    assert not result["checks"]["far_mean_abs"] and result["status"] == "fail"


def test_gate_fails_when_the_skyline_moves():
    result = _gate(_frame(relief=10.0, shift=3))
    assert result["skyline_shift"] == 3.0 and result["status"] == "fail"


def test_far_checks_are_listed_when_the_frame_has_no_far_ground():
    depth = np.minimum(_depth(), 5000.0).astype(np.float32)   # no sky, nothing beyond 5 km
    result = _gate(_frame(relief=10.0), depth=depth)
    assert set(result["not_checked"]) == {"far_contrast", "far_mean_abs", "skyline_shift"}


def test_default_ranges_come_from_the_bake_json():
    assert gate.default_ranges() == (NEAR_MAX, FAR_MIN)


def test_slant_range_grows_off_axis():
    rng_m = gate.slant_range_m(np.full((800, 1280), 1000.0, dtype=np.float32))
    assert rng_m[400, 640] == pytest.approx(1000.0, abs=0.5)
    assert rng_m[400, 0] == pytest.approx(1000.0 / math.cos(math.radians(27.2)), rel=2e-3)


def test_effective_gsd_scales_with_footprint_and_frequency():
    yy, xx = np.mgrid[0:128, 0:128]
    slow = 128.0 + 40.0 * np.sin(2 * math.pi * xx * 8 / 128)
    fast = 128.0 + 40.0 * np.sin(2 * math.pi * xx * 32 / 128)
    assert gate.f95_cycles_per_px(slow) == pytest.approx(8 / 128, abs=1.5 / 128)
    assert gate.f95_cycles_per_px(fast) == pytest.approx(32 / 128, abs=1.5 / 128)
    assert gate.effective_gsd_m(fast, 0.5) == pytest.approx(0.5 / (2 * 0.25), rel=0.06)
    assert gate.footprint_m_per_px(600.0, 1280) == pytest.approx(0.4818, abs=1e-3)


def test_gate_cli_reads_png_and_f32_and_returns_the_status_code(tmp_path, capsys):
    Image = pytest.importorskip("PIL.Image")
    for name, frame in (("b", _frame()), ("r", _frame()), ("c", _frame(relief=10.0))):
        Image.fromarray(frame).save(tmp_path / f"{name}.png")
    _depth().astype("<f4").tofile(tmp_path / "d.f32")
    argv = ["--baseline", str(tmp_path / "b.png"), "--repeat", str(tmp_path / "r.png"),
            "--candidate", str(tmp_path / "c.png"), "--depth", str(tmp_path / "d.f32"),
            "--crops", str(tmp_path / "crops.png")]
    assert gate.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "provisional_pass"
    assert (tmp_path / "crops.png").is_file()
    argv[5] = str(tmp_path / "b.png")                          # candidate = baseline
    assert gate.main(argv) == 1


# ------------------------------------------------------------ the Windows runner
def test_runner_refuses_by_name_while_the_switch_is_not_in_the_engine(capsys):
    """Today no engine file reads the switch, so the runner must stop before
    rendering. When the integrator wires it this test's first branch ends."""
    assert runner.REPO == REPO and runner.ENGINE_SOURCE.is_dir()   # it searched the real engine source
    if runner.switch_is_wired():
        pytest.skip("the switch is wired; the refusal no longer applies")
    assert runner.main([]) == runner.EXIT_REFUSED
    assert "NOT WIRED" in capsys.readouterr().out


def test_runner_sets_the_switch_exactly_and_renders_off_twice():
    assert runner.variants(0) == [("baseline", "off"), ("repeat", "off"), ("candidate", "0")]
    env = runner.app_env("off", base={})
    assert env == {runner.SWITCH: "off"}                       # no trailing space, no quoting
    assert runner.app_command(8008)[1:4] == ["-m", "uvicorn", "webapp.server:app"]


def test_runner_drives_one_pinned_still_with_flags_the_driver_has():
    command = runner.driver_command(11, 8008, Path("specs"))
    driver = (REPO / "scripts" / "run_test_scenarios.py").read_text(encoding="utf-8")
    for flag in (word for word in command if word.startswith("--")):
        assert f'"{flag}"' in driver
    assert command[command.index("--only") + 1] == "11"
    assert 'REPO / "runs" / "webapp"' in driver and 'REPO / "runs" / "test_scenarios.json"' in driver
    assert "matterhorn" in driver.lower()


def test_runner_picks_one_frame_not_a_glob(tmp_path):
    camera = tmp_path / "runs" / "abc" / "frames" / "chase"
    camera.mkdir(parents=True)
    for name in ("frame_0000.png", "frame_0000_beauty_post.png", "frame_0000_beauty_4k.png",
                 "frame_0000_normal.png", "frame_0001.png"):
        (camera / name).write_bytes(b"")
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps([{"number": 11, "outcome": "done", "run_id": "abc"}]))
    run_dir = runner.finished_run(11, summary, tmp_path / "runs")
    assert runner.frame_of_run(run_dir).name == "frame_0000.png"
    summary.write_text(json.dumps([{"number": 11, "outcome": "failed", "why": "device lost"}]))
    with pytest.raises(RuntimeError, match="device lost"):
        runner.finished_run(11, summary, tmp_path / "runs")


def test_integration_notes_carry_no_unfilled_gate_argument():
    text = (LANE / "INTEGRATION.md").read_text(encoding="utf-8")
    gate_section = text[text.index("## Pixel gate"):]
    assert "<x0" not in gate_section and "set FLIGHTSIM" not in gate_section and "11_*" not in gate_section
    assert "run_gate.py" in gate_section and "PROVISIONAL" in gate_section
