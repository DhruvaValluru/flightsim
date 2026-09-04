"""Camera Phase 1, package I: the instructor commands, end to end.

python -m flightsim.capture / flightsim.verify over the committed
examples, on the real headless flight dynamics -- the off-mac
demonstration path, exercised as a test so it cannot rot.
"""

import json
from pathlib import Path

import pytest

from core.scenario.camera import CameraSpec
from core.scenario.spec import ScenarioSpec
from flightsim.capture import main as capture_main
from flightsim.verify import main as verify_main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    # --render none: the headless demonstration path on every platform
    # (the default is the richest choice the machine supports, which on
    # a Mac CI leg would be the engine pass).
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(out), "--max-previews", "3",
                         "--render", "none"])
    assert code == 0
    return out


def test_capture_writes_manifest_previews_and_telemetry(demo_run):
    manifest = json.loads(
        (demo_run / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert len(manifest["frames"]) == 48          # 24 per camera, exact
    assert (demo_run / "telemetry.json").is_file()
    assert (demo_run / "scenario.yaml").is_file()
    previews = list((demo_run / "previews").rglob("*.png"))
    assert len(previews) == 3                     # capped by the flag
    # The manifest's digests are the run's own.
    run = json.loads((demo_run / "run.json").read_text(encoding="utf-8"))
    assert manifest["spec_digest"] == run["spec_digest"]
    assert manifest["output_digest"] == run["output_digest"]


def test_verify_passes_on_the_demo_run(demo_run, capsys):
    assert verify_main([str(demo_run)]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "cross_view_consistency" in out


def test_two_camera_sets_align_in_time(demo_run, tmp_path, capsys):
    """The phase's headline property on REAL telemetry: the same
    simulation captured with a different camera set aligns
    frame-for-frame, proven by the alignment check itself."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    cockpit = CameraSpec.defaulted(camera_id="shoulder", preset="cockpit",
                                   aircraft="B747")
    cockpit.set("capture_count", 24, frm="same count, different view")
    spec.cameras = [cockpit]
    variant_spec = tmp_path / "variant.yaml"
    spec.write(variant_spec)
    variant_out = tmp_path / "variant"
    assert capture_main([str(variant_spec), "--out", str(variant_out),
                         "--max-previews", "0", "--render", "none"]) == 0
    assert verify_main([str(variant_out), "--against",
                        str(demo_run)]) == 0
    assert "temporal_alignment" in capsys.readouterr().out


def test_refusal_example_refuses_by_name(tmp_path, capsys):
    code = capture_main([str(EXAMPLES / "cameras_refusal.yaml"),
                         "--out", str(tmp_path / "refused")])
    assert code == 2
    out = capsys.readouterr().out
    assert "camera.terrain_clearance" in out
    assert not (tmp_path / "refused" / "capture_manifest.json").exists()


def test_card_carries_the_solved_pose_tracks(tmp_path):
    """python -m flightsim.capture --card: the run card's cameras block
    is the pose solver's own output, verbatim (the consume-verbatim
    contract's producing half)."""
    out = tmp_path / "carded"
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(out), "--max-previews", "0",
                         "--card", "--render", "none"]) == 0
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert card["spec_digest"] == manifest["spec_digest"]
    assert len(card["cameras"]) == 2
    block = card["cameras"][0]
    assert block["camera_id"] == "chase0"
    poses = block["poses"]
    n = len(poses["t_s"])
    assert n == manifest["frames"][0]["sample_index"] + len(
        json.loads((out / "telemetry.json").read_text(
            encoding="utf-8"))["columns"]["t"]) - manifest["frames"][0][
                "sample_index"]
    for key in ("north_m", "east_m", "alt_m", "yaw_deg", "pitch_deg",
                "roll_deg", "focal_length_mm"):
        assert len(poses[key]) == n
    # Strictly increasing times: the commandlet refuses anything else.
    assert all(b > a for a, b in zip(poses["t_s"], poses["t_s"][1:]))
    # The capture times are the schedule's, sample-aligned.
    assert len(block["capture_times_s"]) == 24
    assert block["origin_x_m"] == manifest["frame"]["origin_x_m"]
    # Flat scene: the card declares the projected frame.
    assert card["scene_crs"] == manifest["frame"]["crs"]


# -- --render frames|clip|none: the same three words the page offers ----

def parse_flag(command, name):
    for arg in command:
        if arg.startswith(f"-{name}="):
            return arg.split("=", 1)[1]
    return None


def honest_cli_engine(calls, short_for=None, fail_for=None):
    """A run_render_pass stub behaving like the consume-poses pass: it
    reads -scenario= and -camera-index= off the argv exactly as the
    commandlet does, and writes the PNGs and render.json the contract
    specifies -- the aircraft DRAWN at the manifest's labelled pixel and
    the engine's own measurement of that pixel recorded."""
    from core.capture.verify import labelled_pixel

    from tests.test_camera_verify import engine_pixel_fields, honest_frame

    def fake_pass(command, frames, log):
        command = list(command)
        index = parse_flag(command, "camera-index")
        index = int(index) if index is not None else None
        calls.append({"command": command, "frames": Path(frames),
                      "log": Path(log), "camera_index": index})
        if fail_for is not None and index == fail_for:
            return False
        card_path = Path(parse_flag(command, "scenario"))
        card = json.loads(card_path.read_text(encoding="utf-8"))
        # An honest engine draws the aircraft where its own FDM is; for
        # a stub that is where the manifest beside the card says.
        manifest = json.loads((card_path.parent / "capture_manifest.json")
                              .read_text(encoding="utf-8"))
        block = card["cameras"][index]
        poses, times = block["poses"], block["capture_times_s"]
        if short_for is not None and index == short_for:
            times = times[:-1]
        frames = Path(frames)
        frames.mkdir(parents=True, exist_ok=True)
        records = []
        for i, t in enumerate(times):
            k = poses["t_s"].index(t)
            labelled = next(r for r in manifest["frames"]
                            if r["camera_id"] == block["camera_id"]
                            and r["index"] == i)
            drawn = labelled["aircraft"]
            records.append({
                "frame_index": i, "t_scheduled_s": t,
                "t_applied_s": poses["t_s"][k], "t_pose_s": t,
                "camera_applied_north_m": poses["north_m"][k],
                "camera_applied_east_m": poses["east_m"][k],
                "camera_applied_alt_m": poses["alt_m"][k],
                "camera_applied_yaw_deg": poses["yaw_deg"][k],
                "camera_applied_pitch_deg": poses["pitch_deg"][k],
                "camera_applied_roll_deg": poses["roll_deg"][k],
                "aircraft_applied_north_m": drawn["north_m"],
                "aircraft_applied_east_m": drawn["east_m"],
                "aircraft_applied_alt_m": drawn["alt_m"],
                **engine_pixel_fields(labelled)})
            u, v, depth = labelled_pixel(labelled)
            honest_frame(frames / f"{i:04d}.png", block["width_px"],
                         block["height_px"],
                         pixel=(u, v) if depth > 0 else None)
        (frames / "render.json").write_text(json.dumps({
            "width": block["width_px"], "height": block["height_px"],
            "step_s": 1.0 / 120.0,
            "frames_scheduled": len(block["capture_times_s"]),
            "frames_captured": len(times), "frame_records": records,
            # The pass stops after the last scheduled instant.
            "steps_taken": int(round(times[-1] * 120.0)),
            "stepped_s": times[-1],
        }), encoding="utf-8")
        return True
    return fake_pass


@pytest.fixture()
def cli_engine(monkeypatch):
    """The engine gate held open and every engine-side piece stubbed, so
    --render frames|clip can be exercised on a machine with none of it."""
    import core.util.platform as plat
    import flightsim.capture as cli
    import webapp.runs as runs_module

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_unavailable_reason", lambda: None)
    monkeypatch.setattr(plat, "find_ffmpeg", lambda: Path("ffmpeg"))
    monkeypatch.setattr(runs_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    encoded = []

    def fake_encode(ffmpeg, frames_dir, times, clip, lead_in_s=None):
        encoded.append({"frames_dir": Path(frames_dir), "times": list(times)})
        Path(clip).write_bytes(b"mp4")
        return True

    monkeypatch.setattr(cli, "encode_scheduled_clip", fake_encode)
    return {"monkeypatch": monkeypatch, "encoded": encoded}


def test_render_default_is_the_richest_this_machine_supports(monkeypatch):
    import core.util.platform as plat
    from core.capture.render_pass import render_choice_default

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    assert render_choice_default() == "none"
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    assert render_choice_default() == "frames"


def test_render_none_says_scheduled_not_captured(tmp_path, capsys):
    """The headless summary distinguishes what it did: frames were
    SCHEDULED and previews written; nothing was captured or rendered."""
    out = tmp_path / "headless"
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "2",
                         "--render", "none"]) == 0
    text = capsys.readouterr().out
    assert "scheduled 48 frames across 2 camera(s)" in text
    assert "2 geometry preview(s)" in text and "not frames" in text
    assert "captured:" not in text and "rendered 48" not in text
    assert not (out / "card.json").exists()          # only with --card


def test_a_headless_run_verifies_and_never_says_refused(tmp_path, capsys,
                                                         monkeypatch):
    """--render none on a machine without the engine did exactly what
    was asked: exit 0, the verifier's own table printed before the final
    line (five PASS lines and engine parity AWAITING, in those words),
    the engine's absence stated by reason in a non-refusal register, and
    the word REFUSED nowhere -- REFUSED is exit 2's word. On a machine
    WITH the engine the same run says headless was a choice."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this OS: the render half needs "
                                "macOS, or Windows with Unreal Engine 5.5")
    out = tmp_path / "headless"
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "2",
                         "--render", "none"]) == 0
    text = capsys.readouterr().out
    for check in ("manifest_version", "fields_finite", "geometry_recovery",
                  "cross_view_consistency", "count_exactness"):
        assert f"[PASS] {check}" in text, check
    assert "[AWAITING] engine_parity: awaiting engine frames" in text
    assert "verification PASSED (5/5 checks; 1 awaiting engine frames" in text
    assert "REFUSED" not in text
    assert ("engine absent: no engine on this OS: the render half needs "
            "macOS, or Windows with Unreal Engine 5.5; frames not rendered "
            "(--render frames where the engine exists)") in text
    lines = text.strip().splitlines()
    assert lines[-1].startswith("done: manifest, 2 previews and verification "
                                "for 48 scheduled frames under ")
    assert lines[-1].endswith("(no pixels)")
    # The table precedes the final line: verification is not a claim.
    assert text.index("[AWAITING] engine_parity") < text.index("engine absent:")
    # Verifiable from the directory, exactly as printed.
    assert verify_main([str(out)]) == 0
    assert "[AWAITING] engine_parity" in capsys.readouterr().out

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_unavailable_reason", lambda: None)
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(tmp_path / "chosen"), "--max-previews", "0",
                         "--render", "none"]) == 0
    text = capsys.readouterr().out
    assert "render: none (headless by choice" in text
    assert "REFUSED" not in text and "engine absent" not in text
    assert "verification PASSED (5/5 checks" in text


def test_a_manifest_that_fails_its_own_verification_fails_the_run(
        tmp_path, capsys, monkeypatch):
    """The headless run does not stop at 'written': a manifest the
    verifier fails is a failed run, by name (capture.verification, exit
    2), with the failing table printed."""
    from core.capture.verify import VerificationReport

    def failing(run_dir, other_run_dir=None):
        report = VerificationReport()
        report.add("manifest_version", True, "manifest_version 1")
        report.add("geometry_recovery", False,
                   "stub: 3 aimed frames without the aircraft in frame")
        return report

    monkeypatch.setattr("core.capture.verify.verify_run", failing)
    out = tmp_path / "unverified"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "0", "--render", "none"])
    text = capsys.readouterr().out
    assert code == 2, text
    assert "[FAIL] geometry_recovery: stub: 3 aimed frames" in text
    assert "FAILED capture.verification: the manifest just written did not verify (1 of 2 checks passed)" in text
    assert "done:" not in text


def test_an_engine_choice_without_an_engine_refuses_by_name(tmp_path, capsys,
                                                             monkeypatch):
    """--render frames|clip on a machine without the engine: exit 2 with
    the ue.platform refusal and the reason, BEFORE any flight -- never a
    silent headless run."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this machine: set UE_ROOT")
    for word in ("frames", "clip"):
        out = tmp_path / word
        assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                             str(out), "--render", word]) == 2
        text = capsys.readouterr().out
        assert "ue.platform" in text
        assert "no engine on this machine: set UE_ROOT" in text
        assert f"--render {word}" in text
        assert not (out / "capture_manifest.json").exists()
        # The refusal speaks of frames, the phase's deliverable, and of
        # what DOES run here -- not of "rendered clips" alone.
        assert "REFUSED ue.platform: rendered frames and clips require" in text
        assert "the capture manifest, previews and" in text


def test_a_turbulent_spec_refuses_frames_by_name(tmp_path, capsys,
                                                  cli_engine):
    """--render frames on a turbulent spec: REFUSED render.host_parity
    before any flight (host parity is measured and refused for
    turbulence realisations), no engine pass, no manifest. The same
    spec runs headlessly (--render none) and as a clip."""
    import flightsim.capture as cli

    calls = []
    cli_engine["monkeypatch"].setattr(cli, "run_render_pass",
                                      honest_cli_engine(calls))
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    spec.set("turbulence", "moderate", frm="test: a turbulence realisation")
    turbulent = tmp_path / "turbulent.yaml"
    spec.write(turbulent)
    out = tmp_path / "frames"
    code = capture_main([str(turbulent), "--out", str(out),
                         "--max-previews", "0", "--render", "frames"])
    text = capsys.readouterr().out
    assert code == 2, text
    assert "REFUSED render.host_parity: turbulence 'moderate'" in text
    assert "host parity" in text and "Clip only" in text
    assert calls == []
    assert not (out / "capture_manifest.json").exists()
    # The same spec is NOT refused headlessly or as a clip: the refusal is
    # the engine's, decided before any flight. Asserted on the refusal
    # function itself rather than by flying the turbulent spec, whose
    # seeded Dryden realisation is the platform C library's (CI measured
    # its closure 0.02 kt outside tolerance on Windows and inside on
    # Linux), so a flight would test the platform, not the refusal.
    from core.capture.render_pass import frames_host_parity_refusal

    assert frames_host_parity_refusal(spec) is not None
    calm = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    assert frames_host_parity_refusal(calm) is None
    # The calm spec flies headlessly with no host-parity refusal (the
    # turbulent one is not flown: its closure is the platform's).
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(tmp_path / "none"), "--max-previews", "0",
                         "--render", "none"]) == 0
    assert "REFUSED render.host_parity" not in capsys.readouterr().out


def test_render_frames_runs_the_engine_once_per_camera(tmp_path, capsys,
                                                       cli_engine):
    import flightsim.capture as cli

    calls = []
    cli_engine["monkeypatch"].setattr(cli, "run_render_pass",
                                      honest_cli_engine(calls))
    out = tmp_path / "frames"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "0",
                         "--render", "frames"])
    text = capsys.readouterr().out
    assert code == 0, text
    # One pass per camera, by index, into frames/<camera_id>, on the card
    # written without --card, with no preset words.
    assert [c["camera_index"] for c in calls] == [0, 1]
    assert [c["frames"] for c in calls] == [out / "frames" / "chase0",
                                            out / "frames" / "tower0"]
    for call in calls:
        assert parse_flag(call["command"], "scenario") == str(out / "card.json")
        assert parse_flag(call["command"], "frames") == str(call["frames"])
        assert parse_flag(call["command"], "camera") is None
        assert parse_flag(call["command"], "chase") is None
        assert "-AllowCommandletRendering" in call["command"]
    assert parse_flag(calls[0]["command"], "telemetry") is not None
    assert parse_flag(calls[1]["command"], "telemetry") is None
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert [b["camera_id"] for b in card["cameras"]] == ["chase0", "tower0"]
    # 24 PNGs per camera named by manifest index, where the manifest says.
    for camera_id in ("chase0", "tower0"):
        names = sorted(p.name for p in (out / "frames" / camera_id).glob("*.png"))
        assert names == [f"{i:04d}.png" for i in range(24)]
    assert "scheduled 48 frames across 2 camera(s)" in text
    assert "rendered 48 frames across 2 camera(s) (48 verified by engine parity)" in text
    assert "[PASS] engine_parity" in text
    assert cli_engine["encoded"][0]["frames_dir"] == out / "frames" / "chase0"
    assert len(cli_engine["encoded"][0]["times"]) == 24
    # What each pass cost and what the clip was expected to be, said and
    # recorded beside the run's digests.
    last = card["cameras"][0]["capture_times_s"][-1]
    assert f"(engine stepped {last:.3f} s in {int(round(last * 120))} steps)" in text
    assert f"{last + 1.0:.3f} s = black to t=" in text
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert [p["camera_id"] for p in run["render_passes"]] == ["chase0", "tower0"]
    assert run["render_passes"][0]["stepped_s"] == last
    assert run["render_passes"][0]["steps_taken"] == int(round(last * 120))
    assert run["clip_encoded"] is True
    assert run["clip_seconds"] == pytest.approx(last + 1.0)
    # The frames verify from the directory, as the instructor would run it.
    assert verify_main([str(out)]) == 0
    assert "[PASS] engine_parity: 48 frames" in capsys.readouterr().out


def test_render_frames_fails_by_name_on_a_short_pass(tmp_path, capsys,
                                                     cli_engine):
    import flightsim.capture as cli

    calls = []
    cli_engine["monkeypatch"].setattr(
        cli, "run_render_pass", honest_cli_engine(calls, short_for=1))
    out = tmp_path / "short"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "0",
                         "--render", "frames"])
    text = capsys.readouterr().out
    assert code == 2
    assert "FAILED render.frames: camera 'tower0'" in text
    assert "captured 23 of 24 scheduled" in text
    assert "rendered 23 of 24 scheduled frames" in text
    assert "rendered 48 frames" not in text
    assert not cli_engine["encoded"]

    calls.clear()
    cli_engine["monkeypatch"].setattr(
        cli, "run_render_pass", honest_cli_engine(calls, fail_for=0))
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(tmp_path / "dead"), "--max-previews", "0",
                         "--render", "frames"])
    text = capsys.readouterr().out
    assert code == 2 and "FAILED render.frames" in text
    assert "wrote no render.json" in text and len(calls) == 1


def test_render_clip_is_the_single_preset_pass(tmp_path, capsys, cli_engine):
    import flightsim.capture as cli

    calls = []

    def preset_pass(command, frames, log):
        calls.append(list(command))
        Path(frames).mkdir(parents=True, exist_ok=True)
        (Path(frames) / "render.json").write_text("{}", encoding="utf-8")
        return True

    cli_engine["monkeypatch"].setattr(cli, "run_render_pass", preset_pass)
    encoded = []
    cli_engine["monkeypatch"].setattr(
        "experiments.showcase_matrix.encode_clip",
        lambda frames, clip: encoded.append(frames) or bool(
            clip.write_bytes(b"x")) or True)
    out = tmp_path / "clip"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "0",
                         "--render", "clip"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert len(calls) == 1
    assert parse_flag(calls[0], "camera") == "chase"
    assert parse_flag(calls[0], "camera-index") is None
    assert "rendered clip:" in text
    assert "0 frames rendered as a frame set" in text
    assert not (out / "frames").exists()
    # The clip mode verified the manifest it wrote, before the pass.
    assert "[AWAITING] engine_parity" in text
    assert "verification PASSED (5/5 checks" in text
    assert text.index("verification PASSED") < text.index("engine pass:")
    clip_card = json.loads((out / "clip_card.json").read_text(encoding="utf-8"))
    assert "cameras" not in clip_card


def test_run_json_records_the_render_choice_and_verify_json_in_every_mode(
        tmp_path, capsys, cli_engine, monkeypatch):
    """The CLI's own record agrees with the webapp's: run.json carries
    the render choice (word, label, the engine's availability and
    reason) and verify.json -- the verifier's report, the JSON the page
    serves -- sits beside the manifest in all three modes, matching what
    flightsim.verify prints without re-running."""
    import core.util.platform as plat
    import flightsim.capture as cli
    from core.capture.render_pass import RENDER_WORDS

    def run(word, out, **extra):
        code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                             str(out), "--max-previews", "0",
                             "--render", word])
        text = capsys.readouterr().out
        assert code == 0, text
        run_json = json.loads((out / "run.json").read_text(encoding="utf-8"))
        assert run_json["render"]["choice"] == word
        assert run_json["render"]["label"] == RENDER_WORDS[word]
        for key, value in extra.items():
            assert run_json["render"][key] == value, key
        verify = json.loads((out / "verify.json").read_text(encoding="utf-8"))
        assert verify["ok"] is True
        assert [c["name"] for c in verify["checks"]] == [
            "manifest_version", "fields_finite", "geometry_recovery",
            "cross_view_consistency", "count_exactness", "engine_parity"]
        # The file says what the table said.
        for check in verify["checks"]:
            assert f"[{check['status']}] {check['name']}: " in text, check
        return run_json, verify

    # Headless on a machine without the engine: the reason is recorded.
    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this OS (test)")
    _, verify = run("none", tmp_path / "none", engine_available=False,
                    engine_unavailable_reason="no engine on this OS (test)")
    engine = verify["checks"][-1]
    assert engine["status"] == "AWAITING" and engine["ok"] is None
    assert verify["awaiting"] == ["engine_parity"] and verify["ran"] == 5
    assert engine["data"]["cameras"]["chase0"] == {
        "scheduled": 24, "rendered": 0, "verified": 0}
    # flightsim.verify over the directory prints exactly the file's checks.
    assert verify_main([str(tmp_path / "none")]) == 0
    printed = capsys.readouterr().out
    for check in verify["checks"]:
        assert f"[{check['status']}] {check['name']}: {check['detail']}" in printed

    # Frames: verify.json is rewritten AFTER the passes, engine parity graded.
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_unavailable_reason", lambda: None)
    calls = []
    cli_engine["monkeypatch"].setattr(cli, "run_render_pass",
                                      honest_cli_engine(calls))
    run_json, verify = run("frames", tmp_path / "frames",
                           engine_available=True,
                           engine_unavailable_reason=None)
    engine = verify["checks"][-1]
    assert engine["status"] == "PASS"
    assert engine["data"]["cameras"]["tower0"] == {
        "scheduled": 24, "rendered": 24, "verified": 24}
    assert verify["awaiting"] == [] and verify["ran"] == 6
    assert [p["camera_id"] for p in run_json["render_passes"]] == ["chase0", "tower0"]

    # Clip: the choice is recorded and the manifest verified (parity awaiting).
    def preset_pass(command, frames, log):
        Path(frames).mkdir(parents=True, exist_ok=True)
        (Path(frames) / "render.json").write_text("{}", encoding="utf-8")
        return True

    cli_engine["monkeypatch"].setattr(cli, "run_render_pass", preset_pass)
    cli_engine["monkeypatch"].setattr(
        "experiments.showcase_matrix.encode_clip",
        lambda frames, clip: bool(clip.write_bytes(b"x")) or True)
    _, verify = run("clip", tmp_path / "clip", engine_available=True)
    assert verify["checks"][-1]["status"] == "AWAITING"


# -- the geometry preview through the CLI (package I, done properly) ------

def test_previews_are_full_resolution_scaled_from_the_fdm_and_timed(demo_run):
    """The default preview is the record's own 1280x720; run.json
    records the scale, the resolution, the MEASURED seconds per frame
    (under the 0.5 s budget) and the contact sheet; the manifest carries
    the airframe metrics the body is scaled by, read from the FDM
    (metrics/bw-ft: the B747's 211.5 ft span)."""
    from PIL import Image

    from core.capture.preview import RENDER_BUDGET_S_PER_FRAME

    manifest = json.loads(
        (demo_run / "capture_manifest.json").read_text(encoding="utf-8"))
    metrics = manifest["aircraft_metrics"]
    assert metrics["span_source"] == "metrics/bw-ft"
    assert metrics["span_m"] == pytest.approx(64.4652, abs=1e-3)
    assert metrics["length_m"] > 0 and metrics["height_m"] > 0
    previews = sorted((demo_run / "previews").rglob("preview_*.png"))
    assert len(previews) == 3
    record = manifest["frames"][0]
    assert Image.open(previews[0]).size == (record["width_px"],
                                            record["height_px"])
    run = json.loads((demo_run / "run.json").read_text(encoding="utf-8"))
    block = run["previews"]
    assert block["count"] == 3 and block["scale"] == 1
    assert block["resolution"] == [record["width_px"], record["height_px"]]
    assert 0.0 < block["s_per_frame"] < RENDER_BUDGET_S_PER_FRAME
    # The flown track is the run's own telemetry, not the schedule's
    # chords, at the rate MEASURED from its samples (the recorder steps
    # 13 fixed steps, 0.1083 s, between samples: 9.23 Hz, not a nominal
    # 10) and undecimated below TRACK_TARGET_HZ.
    import numpy as np

    telemetry = json.loads((demo_run / "telemetry.json").read_text(encoding="utf-8"))
    t = telemetry["columns"]["t"]
    rate = 1.0 / float(np.median(np.diff(t)))
    assert 9.0 < rate < 10.0
    assert block["track_source"] == (f"track: telemetry {rate:g} Hz ({len(t)} points, "
                                     f"no decimation)")
    assert block["contact_sheets"] == {"chase0": "contact_sheets/chase0.png"}
    assert (demo_run / "contact_sheets" / "chase0.png").is_file()


def test_the_preview_scale_flag_is_optional_and_refuses_a_bad_value(
        tmp_path, capsys):
    from PIL import Image

    out = tmp_path / "half"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "1", "--render", "none",
                         "--preview-scale", "2"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "1 geometry preview(s) at 640x360, 1/2 scale, " in text
    assert " s/frame under " in text and "not frames" in text
    assert "contact sheets: 1 (contact_sheets/<camera_id>.png" in text
    assert Image.open(out / "previews" / "chase0" / "preview_00000.png").size \
        == (640, 360)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["previews"]["scale"] == 2
    assert run["previews"]["resolution"] == [640, 360]
    # A scale the preview cannot draw at exactly refuses BY NAME before
    # any flight: no run directory, no manifest.
    for bad in ("0", "-2"):
        code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                             str(tmp_path / "bad"), "--render", "none",
                             "--preview-scale", bad])
        text = capsys.readouterr().out
        assert code == 2
        assert "REFUSED -- preview.scale:" in text
        assert not (tmp_path / "bad").exists()


def test_render_frames_overlays_the_reprojected_geometry_on_every_frame(
        tmp_path, capsys, cli_engine):
    """After the engine passes every rendered PNG gets an overlay named
    by the same index, the frame's own size, with the manifest's
    aircraft drawn at the labelled pixel; the count and its measured
    time are said and recorded in run.json."""
    from PIL import Image

    import flightsim.capture as cli
    from core.capture.verify import labelled_pixel

    calls = []
    cli_engine["monkeypatch"].setattr(cli, "run_render_pass",
                                      honest_cli_engine(calls))
    out = tmp_path / "frames"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                         str(out), "--max-previews", "0",
                         "--render", "frames"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "overlays: 48 reprojected-geometry overlay(s) over the rendered " \
           "frames under" in text
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    for camera_id in ("chase0", "tower0"):
        names = sorted(p.name for p in (out / "overlays" / camera_id).glob("*.png"))
        assert names == [f"{i:04d}.png" for i in range(24)]
    record = next(r for r in manifest["frames"]
                  if r["camera_id"] == "chase0" and r["index"] == 5)
    frame = Image.open(out / record["file"])
    overlay = Image.open(out / "overlays" / "chase0" / "0005.png")
    assert overlay.size == frame.size
    u, v, depth = labelled_pixel(record)
    assert depth > 0
    # The body's wing line crosses the labelled pixel: the overlay differs
    # from the stub's frame there, and matches it far from any geometry.
    assert overlay.getpixel((int(round(u)), int(round(v)))) != \
        frame.getpixel((int(round(u)), int(round(v))))
    assert overlay.getpixel((20, 200)) == frame.getpixel((20, 200))
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["overlays"]["count"] == 48
    assert 0.0 < run["overlays"]["s_per_frame"] < 0.5
