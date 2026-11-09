"""experiments/visual_contact_sheet.py and the edge-aliasing number
(experiments/gate6_visual.py): the shot table, the token plumbing, the
composition and the metric, all without the engine."""

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import experiments.visual_contact_sheet as sheet
from experiments import gate6_visual as gate6

ROOT = Path(__file__).resolve().parents[1]
COMMANDLET = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
              "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")


# -- the shot table ---------------------------------------------------------


def test_four_fixed_shots_in_order():
    assert sheet.SHOT_ORDER == ("a", "b", "c", "d")
    assert set(sheet.SHOTS) == set(sheet.SHOT_ORDER)
    assert all(shot.aircraft == "J11" for shot in sheet.SHOTS.values())
    assert (ROOT / "assets/aircraft_config/J11.json").is_file()


def _compiled(shot):
    from core.nl.compiler import compile_prompt

    return compile_prompt(shot.prompt).to_dict()


def _value(block, name):
    entry = block[name]
    return entry["value"] if isinstance(entry, dict) else entry


@pytest.mark.parametrize("key", ["a", "b", "c", "d"])
def test_every_prompt_compiles_offline_to_its_subject_and_camera(key):
    shot = sheet.SHOTS[key]
    spec = _compiled(shot)
    assert _value(spec["aircraft"], "aircraft") == "J11"
    presets = [_value(camera, "preset") for camera in spec["cameras"]]
    assert presets == [shot.camera]


def test_every_shot_validates_through_the_web_app_s_own_compile_handler():
    """The page's path (POST /compile with the shot's environment, still):
    the altitudes clear the terrain at each place (they are MSL; measured
    limits on 2026-11-09: Matterhorn 1890 m, desert preset 1370 m, forest
    preset 1260 m)."""
    client, _server = sheet._client()
    for key in sheet.SHOT_ORDER:
        shot = sheet.SHOTS[key]
        body = {"prompt": shot.prompt, "compiler": "regex", "still": True}
        if shot.environment:
            body["environment"] = shot.environment
        reply = client.post("/compile", json=body)
        assert reply.status_code == 200, key
        assert reply.json()["validation"]["ok"], (key, reply.json()["validation"])


def test_shot_contents_match_the_brief():
    from webapp.runs import ENVIRONMENT_PRESETS

    a, b, c, d = (_compiled(sheet.SHOTS[k]) for k in "abcd")
    assert _value(a["environment"], "time_of_day") == "golden hour"
    assert sheet.SHOTS["b"].environment == "desert" and "desert" in ENVIRONMENT_PRESETS
    assert sheet.SHOTS["c"].environment == "forest" and "forest" in ENVIRONMENT_PRESETS
    assert _value(c["environment"], "precipitation_rate_mmh") > 0.0
    assert sheet.SHOTS["d"].camera == "cockpit"
    # a and d are over real terrain the compiler places (the Matterhorn)
    assert abs(_value(a["initial"], "latitude") - 46.0) < 0.1
    assert sheet.SHOTS["a"].subject == sheet.SHOTS["d"].subject == ("matterhorn", "Matterhorn")


# -- the tokens -------------------------------------------------------------


def test_tokens_for_each_mode():
    assert sheet.render_extra_tokens("beauty", None, False, None) == []
    assert sheet.render_extra_tokens("beauty", 16, False, None) == ["-still-samples=16"]
    tokens = sheet.render_extra_tokens("beauty", None, True, 512)
    assert tokens == ["-quality=pathtrace", sheet.RAY_TRACING_INI_TOKEN, "-pathtrace-spp=512"]


@pytest.mark.parametrize("args", [("measure", 8, False, None), ("beauty", 0, False, None),
                                  ("beauty", 65, False, None), ("beauty", 8, True, None),
                                  ("beauty", None, False, 64), ("beauty", None, True, 0)])
def test_tokens_refuse_by_name(args):
    with pytest.raises(ValueError, match=r"render\.(still_samples|pathtrace)"):
        sheet.render_extra_tokens(*args)


def test_the_commandlet_parses_every_token_the_sheet_sends():
    assert 'TEXT("still-samples=")' in COMMANDLET
    assert 'TEXT("pathtrace-spp=")' in COMMANDLET
    assert 'TEXT("pathtrace")' in COMMANDLET
    assert sheet.RAY_TRACING_INI_TOKEN in COMMANDLET


def test_rewrite_touches_only_the_per_camera_render_pass():
    tokens = ["-quality=pathtrace", "-pathtrace-spp=64"]
    render = ["editor", "proj", "-run=FlightSimBridge.FlightSimRender", "-quality=beauty",
              "-camera-index=0", "-labels"]
    out = sheet.rewrite_render_command(render, tokens)
    assert "-quality=beauty" not in out and out[-2:] == tokens
    solve = ["editor", "proj", "-run=FlightSimBridge.FlightSimRender", "-quality=beauty"]
    assert sheet.rewrite_render_command(solve, tokens) == solve
    telemetry = ["editor", "proj", "-run=FlightSimBridge.FlightSimScenario", "-camera-index=0"]
    assert sheet.rewrite_render_command(telemetry, tokens) == telemetry
    assert sheet.rewrite_render_command(render, []) == render


# -- composition ------------------------------------------------------------


def _png(path: Path, colour, size=(320, 180)):
    Image.new("RGB", size, colour).save(path)
    return path


def test_sheet_composes_present_and_missing_tiles(tmp_path):
    step = tmp_path / "v0"
    step.mkdir()
    _png(step / "a.png", (200, 120, 60))
    _png(step / "c.png", (60, 120, 200), size=(1920, 1080))
    (step / "shots.json").write_text(json.dumps(
        {"shots": {"a": {"quality": "beauty", "commit": "abc"},
                   "b": {"refused": "terrain: no tiles"}}}), encoding="utf-8")
    out = sheet.compose_sheet(step)
    with Image.open(out) as image:
        assert image.size == (2 * sheet.TILE_W + 3 * sheet.GUTTER,
                              40 + 2 * (sheet.TILE_H + sheet.CAPTION_H) + 3 * sheet.GUTTER)
        rgb = np.asarray(image.convert("RGB"))
    # tile a's centre is the orange picture; tile b's is the grey "missing" tile
    ay = 40 + sheet.GUTTER + sheet.TILE_H // 2
    ax = sheet.GUTTER + sheet.TILE_W // 2
    assert tuple(rgb[ay, ax]) == (200, 120, 60)
    bx = 2 * sheet.GUTTER + sheet.TILE_W + sheet.TILE_W // 2
    assert tuple(rgb[ay + 40, bx]) == (60, 62, 66)


def test_compare_is_one_row_per_shot(tmp_path):
    before, after = tmp_path / "v0", tmp_path / "v1"
    for directory, colour in ((before, (10, 10, 10)), (after, (250, 250, 250))):
        directory.mkdir()
        for key in "abcd":
            _png(directory / f"{key}.png", colour)
    out = sheet.compose_compare(before, after, tmp_path / "compare.png")
    with Image.open(out) as image:
        assert image.size[1] == 40 + 4 * (sheet.TILE_H + sheet.CAPTION_H) + 5 * sheet.GUTTER


def test_skip_render_main_composes_and_keeps_the_render_record(tmp_path):
    step = tmp_path / "v0"
    step.mkdir()
    for key in "abcd":
        _png(step / f"{key}.png", (90, 90, 90))
    (step / "shots.json").write_text(json.dumps(
        {"step": "v0", "commit": "deadbeef", "quality": "beauty", "shots": {}}), encoding="utf-8")
    assert sheet.main(["--step", "v0", "--skip-render", "--root", str(tmp_path)]) == 0
    record = json.loads((step / "shots.json").read_text(encoding="utf-8"))
    assert record["commit"] == "deadbeef" and record["quality"] == "beauty"
    assert "composed" in record and (step / "sheet.png").is_file()
    assert sheet.main(["--compare", "v0", "v0", "--root", str(tmp_path)]) == 0
    assert (tmp_path / "compare_v0_vs_v0.png").is_file()


def test_main_refuses_bad_steps_and_tokens(tmp_path, capsys):
    with pytest.raises(ValueError):
        sheet.step_dir("../x")
    assert sheet.main(["--step", "v0", "--still-samples", "4", "--quality", "measure",
                       "--root", str(tmp_path)]) == 2
    assert "REFUSED render.still_samples" in capsys.readouterr().out


# -- rendering, with the web app faked --------------------------------------


class _Reply:
    def __init__(self, code, payload):
        self.status_code, self._payload = code, payload

    def json(self):
        return self._payload


def test_render_shot_bakes_on_unbaked_and_rewrites_only_while_running(tmp_path, monkeypatch):
    import core.render.headless as headless

    seen = []
    monkeypatch.setattr(headless, "run_headless", lambda command, log, *a, **k: seen.append(command))
    original = headless.run_headless
    calls = []

    class Client:
        def __init__(self):
            self.runs = 0

        def post(self, path, json=None):
            calls.append(path)
            if path == "/compile":
                assert json["environment"] == "desert" and json["still"] is True
                return _Reply(200, {"spec": {"dict": {"x": 1}}, "validation": {"ok": True},
                                    "compiler": "regex"})
            if path == "/bake":
                return _Reply(200, {"state": "done"})
            self.runs += 1
            if self.runs == 1:
                return _Reply(409, {"refused": "terrain.unbaked", "latitude": 36.1, "longitude": -112.1})
            # the web app's render pass, inside /run's thread
            headless.run_headless(["e", "-run=FlightSimBridge.FlightSimRender", "-camera-index=0",
                                   "-quality=beauty"], tmp_path / "log")
            return _Reply(200, {"run_id": "r1"})

        def get(self, path):
            return _Reply(200, {"status": "done", "detail": "ok"})

    class Server:
        class manager:
            out_root = tmp_path

    # The unlit shot (the lit path's second compile: tests/test_hero_lighting.py).
    unlit = dataclasses.replace(sheet.SHOTS["b"], lighting=None)
    state = sheet.render_shot(unlit, tokens=["-still-samples=8"],
                              client_factory=lambda: (Client(), Server))
    assert calls == ["/compile", "/run", "/bake", "/run"]
    assert seen and seen[0][-1] == "-still-samples=8"
    assert headless.run_headless is original
    assert state["run_id"] == "r1" and state["run_dir"] == str(tmp_path / "r1")


def test_first_frame_picks_the_camera_frame_and_its_mask(tmp_path):
    camera = tmp_path / "frames" / "chase"
    camera.mkdir(parents=True)
    _png(camera / "frame_0000.png", (1, 2, 3))
    _png(camera / "frame_0000_mask.png", (0, 0, 0))
    _png(camera / "frame_0000_class.png", (0, 0, 0))
    frame, mask = sheet.first_frame(tmp_path, "chase")
    assert frame.name == "frame_0000.png" and mask.name == "frame_0000_mask.png"
    assert sheet.first_frame(tmp_path / "nothing", "chase") == (None, None)


# -- the edge-aliasing number ----------------------------------------------


def _disk(size=128, radius=40.0, supersample=1):
    n = size * supersample
    yy, xx = np.mgrid[0:n, 0:n] / supersample
    inside = ((xx - size / 2 + 0.3) ** 2 + (yy - size / 2 + 0.1) ** 2) < radius ** 2
    cover = inside.reshape(size, supersample, size, supersample).mean(axis=(1, 3))
    grey = 40 + 180 * cover
    return np.stack([grey] * 3).astype(np.int64), cover > 0.5


def test_antialiased_edges_score_lower_than_hard_edges():
    hard, mask = _disk(supersample=1)
    smooth, _ = _disk(supersample=8)
    e_hard = gate6.edge_aliasing_energy(hard, mask)
    e_smooth = gate6.edge_aliasing_energy(smooth, mask)
    assert e_hard is not None and e_smooth is not None
    assert e_smooth < e_hard


def test_the_aliased_control_trips_and_a_blank_frame_is_void():
    smooth, mask = _disk(supersample=8)
    row = gate6.measure_edge_aliasing(smooth, mask)
    assert row["control_energy"] > row["energy"] and row["void"] is False
    flat = np.full((3, 64, 64), 100, dtype=np.int64)
    assert gate6.edge_aliasing_energy(flat, np.zeros((64, 64), bool)) is None
    assert gate6.measure_edge_aliasing(flat, np.zeros((64, 64), bool))["void"] is True


def test_report_edge_aliasing_writes_and_compares(tmp_path):
    smooth, mask = _disk(supersample=8)
    sky = np.full_like(smooth, 40)
    for name, rgb in (("shadow", smooth), ("shadow_hidden", sky)):
        (tmp_path / name).mkdir()
        gate6.write_png_rgb(tmp_path / name / "frame_0000.png", rgb)
    base = tmp_path / "base"
    base.mkdir()
    (base / "aliasing.json").write_text(json.dumps({"energy": 1.0}), encoding="utf-8")
    row = gate6.report_edge_aliasing(tmp_path, base)
    assert row["energy"] is not None and abs(row["change"] - (row["energy"] - 1.0)) < 1e-12
    assert json.loads((tmp_path / "aliasing.json").read_text(encoding="utf-8"))["energy"] == row["energy"]
    assert "[info] edge aliasing (reported, not a gate)" in gate6.edge_aliasing_line(row)
    assert gate6.report_edge_aliasing(tmp_path / "missing") is None


def test_shot_aliasing_reads_a_label_mask(tmp_path):
    smooth, mask = _disk(supersample=8)
    Image.fromarray(np.moveaxis(smooth, 0, 2).astype(np.uint8)).save(tmp_path / "a.png")
    Image.fromarray((mask * 255).astype(np.uint8)).save(tmp_path / "a_mask.png")
    row = sheet.shot_aliasing(tmp_path, "a")
    assert row is not None and row["energy"] is not None
    assert sheet.shot_aliasing(tmp_path, "b") is None


def test_a_void_baseline_gives_no_change(tmp_path):
    smooth, mask = _disk(supersample=8)
    sky = np.full_like(smooth, 40)
    for name, rgb in (("shadow", smooth), ("shadow_hidden", sky)):
        (tmp_path / name).mkdir()
        gate6.write_png_rgb(tmp_path / name / "frame_0000.png", rgb)
    base = tmp_path / "base"
    base.mkdir()
    (base / "aliasing.json").write_text(json.dumps({"energy": 1.0, "void": True}),
                                        encoding="utf-8")
    row = gate6.report_edge_aliasing(tmp_path, base)
    assert "change" not in row and row["change_void"] == "baseline void"
    line = gate6.edge_aliasing_line(row)
    assert "change vs baseline" not in line and "baseline void" in line
    this_void = dict(row, void=True)
    this_void.pop("change_void")
    assert "change vs baseline" not in gate6.edge_aliasing_line(this_void)


# -- fix pass (shots-render, 2026-11-09) --------------------------------------


def _lit_and_framed(key):
    client, _server = sheet._client()
    shot = sheet.SHOTS[key]
    body = {"prompt": shot.prompt, "compiler": "regex", "still": True}
    payload = client.post("/compile", json=body).json()
    payload, lit = sheet.light_shot(client, body, payload, shot.lighting, subject=shot.subject)
    spec, framed = sheet.frame_subject(payload["spec"]["dict"], shot.subject)
    return payload, lit, spec, framed


@pytest.mark.parametrize("key", ["a", "d"])
def test_a_and_d_frame_the_matterhorn_on_the_lens_axis(key):
    """The director's heading is the one flown, and the Matterhorn sits on
    it at the stand-off, inside the matterhorn bake, in a 54 deg lens."""
    from core.scenario.camera import DEFAULT_FOCAL_MM, DEFAULT_SENSOR_H_MM, DEFAULT_SENSOR_W_MM
    from webapp.runs import curated_key_at
    import math

    payload, lit, spec, framed = _lit_and_framed(key)
    assert payload["validation"]["ok"]
    heading = spec["initial"]["heading"]["value"]
    assert heading == lit["heading_compiled_deg"] == framed["heading_deg"]
    half_h = math.degrees(math.atan(DEFAULT_SENSOR_W_MM / 2 / DEFAULT_FOCAL_MM))
    half_v = math.degrees(math.atan(DEFAULT_SENSOR_H_MM / 2 / DEFAULT_FOCAL_MM))
    assert abs(framed["relative_bearing_deg"]) < 1.0 < half_h
    assert 0.0 < framed["subject_elevation_angle_deg"] < half_v
    start = (spec["initial"]["latitude"]["value"], spec["initial"]["longitude"]["value"])
    assert curated_key_at(*start) == "matterhorn"
    assert spec["initial"]["latitude"]["source"] == "inferred"
    assert "SUBJECT_STANDOFF_M" in spec["initial"]["latitude"]["from"]
    # the sun was solved where the flight starts, and still stands where the look wants it
    assert abs(lit["relative_azimuth_error_deg"]) < 1.0


def test_d_looks_at_the_matterhorn_from_the_j11_s_own_cockpit():
    _payload, _lit, spec, _framed = _lit_and_framed("d")
    framing = sheet.camera_framing(spec, "cockpit")
    # the canopy, metres AHEAD of the CG (the old B747 figure sat 6 m aft, over the fins)
    assert 7.0 < framing["offset_forward_m"] < 10.0 and 1.0 < framing["offset_up_m"] < 2.5
    assert "EYEPOINT" in framing["basis"]


def test_the_cockpit_station_comes_from_each_airframe_s_fdm():
    from core.scenario.camera import COCKPIT_EYE_NUDGE_M, SHOULDER_OFFSET, CameraSpec, \
        derive_cockpit_offset

    j11 = derive_cockpit_offset("J11")
    # J11.xml: EYEPOINT (172.45, 0, 38.00) in, CG (517.35, 0, -21.56) in
    expected = ((517.35 - 172.45) * 0.0254 + COCKPIT_EYE_NUDGE_M[0],
                COCKPIT_EYE_NUDGE_M[1], (38.0 + 21.56) * 0.0254 + COCKPIT_EYE_NUDGE_M[2])
    assert j11 == pytest.approx(expected, abs=1e-3)
    camera = CameraSpec.defaulted("cockpit", "cockpit", aircraft="J11")
    assert camera.offset_forward_m.value == pytest.approx(j11[0])
    assert derive_cockpit_offset("no_such_airframe") is None
    fallback = CameraSpec.defaulted("cockpit", "cockpit", aircraft="no_such_airframe")
    assert (fallback.offset_forward_m.value, fallback.offset_right_m.value,
            fallback.offset_up_m.value) == SHOULDER_OFFSET
    assert "SHOULDER_OFFSET" in fallback.offset_forward_m.frm


def test_a_chase_on_the_b747_fallback_refuses_by_name():
    spec = {"cameras": [{"preset": {"value": "chase"},
                         "offset_forward_m": {"value": -110.0, "from": "FALLBACK_CHASE_OFFSET (B747 "
                                              "framing): no mesh manifest for J11"},
                         "offset_right_m": {"value": 0.0}, "offset_up_m": {"value": 12.0}}]}
    with pytest.raises(sheet.ShotRefused, match=r"^shot\.chase_unframed: FALLBACK_CHASE_OFFSET"):
        sheet.camera_framing(spec, "chase")
    spec["cameras"][0]["offset_forward_m"] = {"value": -59.0, "from": "derived from the mesh"}
    assert sheet.camera_framing(spec, "chase")["offset_forward_m"] == -59.0
    assert sheet.camera_framing({"x": 1}, "chase") == {}


def test_the_fallback_chase_says_it_is_the_fallback(monkeypatch, tmp_path):
    import core.scenario.camera as camera

    monkeypatch.setattr(camera, "_MESH_GENERATED_DIR", tmp_path)
    chase = camera.CameraSpec.defaulted("chase", "chase", aircraft="J11")
    assert chase.offset_forward_m.value == camera.FALLBACK_CHASE_OFFSET[0]
    assert chase.offset_forward_m.frm.startswith("FALLBACK_CHASE_OFFSET (B747 framing)")


def test_a_subject_outside_its_bake_refuses_by_name():
    with pytest.raises(sheet.ShotRefused, match=r"^shot\.subject_unframed"):
        sheet.subject_start(("matterhorn", "Matterhorn"), 0.0, standoff_m=30000.0)
    with pytest.raises(sheet.ShotRefused, match=r"^shot\.subject_unframed"):
        sheet.subject_start(("matterhorn", "Eiger"), 0.0)


def test_the_sheet_ranges_are_the_commandlets():
    import re

    def cpp(name):
        return int(re.search(rf"constexpr int32 {name} = (\d+);", COMMANDLET).group(1))

    assert sheet.STILL_SAMPLES_MAX == cpp("RenderBeautyStillSamplesMax")
    assert sheet.PATHTRACE_SPP_MAX == cpp("RenderPathTraceSppMax")
    supersample = (ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
                   "FlightSimSupersample.cpp").read_text(encoding="utf-8")
    assert sheet.SUPERSAMPLE_MAX == int(re.search(r"constexpr int MaxFactor = (\d+);",
                                                  supersample).group(1))
    assert sheet.render_extra_tokens("beauty", sheet.STILL_SAMPLES_MAX, False, None)
    assert sheet.render_extra_tokens("beauty", None, True, sheet.PATHTRACE_SPP_MAX)
    for args in (("beauty", sheet.STILL_SAMPLES_MAX + 1, False, None),
                 ("beauty", None, True, sheet.PATHTRACE_SPP_MAX + 1)):
        with pytest.raises(ValueError):
            sheet.render_extra_tokens(*args)
    assert "is not a whole number from 1 to" in COMMANDLET
    assert "a value is out of range" in COMMANDLET


def test_the_clip_takes_no_still_samples(tmp_path, monkeypatch):
    calls = []

    def fake(shot, *, still=True, clip_seconds=None, tokens=(), **_k):
        calls.append((still, list(tokens)))
        raise sheet.ShotRefused("render: stub")

    monkeypatch.setattr(sheet, "render_shot", fake)
    assert sheet.main(["--step", "v0", "--shots", "a", "--still-samples", "4", "--clip",
                       "--root", str(tmp_path)]) == 0
    assert calls == [(True, ["-supersample=2", "-still-samples=4"]), (False, [])]
