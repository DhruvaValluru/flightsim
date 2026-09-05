"""Camera Phase 1, package I: the instructor commands, end to end.

python -m flightsim.capture / flightsim.verify over the committed
examples, on the real headless flight dynamics -- the off-mac
demonstration path, exercised as a test so it cannot rot.
"""

import contextlib
import io
import json
import re
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
    rows = verification_rows(text)
    for check in ("manifest_version", "fields_finite", "geometry_recovery",
                  "cross_view_consistency", "count_exactness",
                  "flight_fidelity", "schedule_fidelity", "pose_fidelity",
                  "aim_fidelity"):
        assert rows[check][0] == "PASS", check
        assert f"[PASS] {check}" not in text, check   # rendered once
    assert "[AWAITING] engine_parity: awaiting engine frames" in text
    assert "verification PASSED (9/9 checks; 1 awaiting engine frames" in text
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
    assert "verification PASSED (9/9 checks" in text


def test_a_manifest_that_fails_its_own_verification_fails_the_run(
        tmp_path, capsys, monkeypatch):
    """The headless run does not stop at 'written': a manifest the
    verifier fails is a failed run, by name (capture.verification, exit
    1 -- the shared table's word for a verification FAILED, the same
    code flightsim.verify gives the same manifest), with the failing
    table printed."""
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
    assert code == 1, text
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
    assert verification_rows(text)["engine_parity"][0] == "PASS"
    assert "[PASS]" not in text and "detail:" not in text   # every row passed
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
    rows = verification_rows(capsys.readouterr().out)
    assert rows["engine_parity"][0] == "PASS"
    assert rows["engine_parity"][1].startswith("pos 0.")
    assert rows["engine_parity"][3].startswith("48 of 48 frames verified")


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
    assert "verification PASSED (9/9 checks" in text
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
            "cross_view_consistency", "count_exactness", "flight_fidelity",
            "schedule_fidelity", "pose_fidelity", "aim_fidelity",
            "engine_parity"]
        # The file says what the table said: a PASS is its row, once;
        # anything else has its detail line too.
        rows = verification_rows(text)
        for check in verify["checks"]:
            assert rows[check["name"]][0] == check["status"], check
            if check["status"] == "PASS":
                assert f"[PASS] {check['name']}" not in text, check
            else:
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
    assert verify["awaiting"] == ["engine_parity"] and verify["ran"] == 9
    assert engine["data"]["cameras"]["chase0"] == {
        "scheduled": 24, "rendered": 0, "verified": 0}
    # flightsim.verify over the directory prints exactly the file's checks.
    assert verify_main([str(tmp_path / "none")]) == 0
    printed = capsys.readouterr().out
    rows = verification_rows(printed)
    for check in verify["checks"]:
        assert rows[check["name"]][0] == check["status"]
        if check["status"] != "PASS":
            assert (f"[{check['status']}] {check['name']}: "
                    f"{check['detail']}") in printed
        else:
            assert rows[check["name"]][1:3] == (check["measured_text"],
                                                check["tolerance_text"])

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
    assert verify["awaiting"] == [] and verify["ran"] == 10
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
    # any flight: no run directory, no manifest. 3 does not divide the
    # example's 1280x720 (426.67x240): refused from the spec's cameras,
    # never floored to 426x240.
    for bad in ("0", "-2", "3"):
        code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                             str(tmp_path / "bad"), "--render", "none",
                             "--preview-scale", bad])
        text = capsys.readouterr().out
        assert code == 2
        assert "REFUSED -- preview.scale:" in text
        assert not (tmp_path / "bad").exists()
        if bad == "3":
            assert "3 does not divide 1280x720 exactly (426.67x240)" in text
            assert "(camera chase0)" in text
            assert "running headlessly" not in text            # before the flight


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


# -- Commands round 1: the report a person wants to read ------------------
# -- (header, schedule table, verification table, verdict, --json,
# -- --corrupt, exit codes, no JSBSim banner on stdout)

COCKPIT = EXAMPLES / "cameras_multi_cockpit.yaml"


def capture_text(argv):
    """(exit code, stdout) of flightsim.capture, stdout collected at the
    Python level -- JSBSim's C++ banner goes through file descriptor 1
    and would bypass this collector if it were not routed to the log."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = capture_main(argv)
    return code, buffer.getvalue()


@pytest.fixture(scope="module")
def report_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("report")
    code, text = capture_text([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                               str(out), "--max-previews", "0",
                               "--render", "none"])
    assert code == 0, text
    return out, text


def verification_rows(text):
    """The verification table's rows, parsed from the printed report:
    {check: (status, measured, tolerance, where)}."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.split() == ["CHECK", "STATUS", "MEASURED",
                                     "TOLERANCE", "WHERE"])
    head = lines[start]
    columns = [head.index(word) for word in ("CHECK", "STATUS", "MEASURED",
                                              "TOLERANCE", "WHERE")]
    rows = {}
    for line in lines[start + 1:]:
        # The table ends at the detail block (rows that did not PASS)
        # or, when every row passed, at the summary line.
        if line.strip() == "detail:" or not line.startswith("  "):
            break
        cells = [line[a:b].strip() for a, b in zip(columns, columns[1:])]
        cells.append(line[columns[-1]:].strip())
        rows[cells[0]] = tuple(cells[1:])
    return rows


def schedule_rows_printed(text, camera_id):
    """The printed schedule rows of one camera: [(idx, t_s, sample)]."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith(f"  {camera_id}: ") and "scheduled instant"
                 in line)
    rows = []
    for line in lines[start + 2:]:
        match = re.match(r"\s+(\d+)\s+([\d.]+)\s+(\d+)\s+", line)
        if not match:
            break
        rows.append((int(match.group(1)), float(match.group(2)),
                     int(match.group(3))))
    return rows


def test_stdout_carries_no_jsbsim_text_and_the_log_holds_it(report_run):
    """The startup banner JSBSim prints from C++ on every model
    construction is routed to <out>/jsbsim.log at the descriptor level,
    counted, and named in one line; stdout carries none of it."""
    out, text = report_run
    assert "JSBSim startup" not in text
    assert "JSBSim Flight Dynamics Model" not in text
    log = out / "jsbsim.log"
    assert log.is_file()
    banners = log.read_text(encoding="utf-8").count("JSBSim startup beginning")
    assert banners >= 1
    match = re.search(r"^JSBSim output: (.+) \((\d+) model loads; nothing of "
                      r"JSBSim's on stdout\)$", text, re.M)
    assert match, text
    assert Path(match.group(1)) == log
    assert int(match.group(2)) == banners
    # One stamp before every routed load: what was built and who asked,
    # so fourteen identical banners read as fourteen named loads.
    stamps = re.findall(r"^# load (\d+): (\S+) called from ([\w.]+)$",
                        log.read_text(encoding="utf-8"), re.M)
    assert len(stamps) == banners
    assert [int(n) for n, _, _ in stamps] == list(range(1, banners + 1))
    assert stamps[0][1] == "FlightDynamics(B747)"
    assert all(label.startswith("FlightDynamics(") for _, label, _ in stamps)
    assert all(caller.startswith("core.") for _, _, caller in stamps)
    assert all(not caller.startswith("core.fdm.") for _, _, caller in stamps)
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["jsbsim_log"] == str(log)
    # verify constructs no FDM: nothing of JSBSim's, not even the line.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out)]) == 0
    assert "JSBSim" not in buffer.getvalue()


def test_the_cards_engine_start_probe_prints_nothing_on_stdout(tmp_path, capfd):
    """--card and --render frames write the run card, whose engine-start
    mixture probe (core.scenario.card.discovered_engine_mixture) builds
    a JSBSim model at debug level 1 and runs it to trim: run_ic prints
    the Mass Properties Report from C++ AFTER the startup banner. The
    whole probe is routed through the console sink, so under FILE
    DESCRIPTOR capture (capfd, the level the bytes leave at) stdout
    carries none of it and the log holds the report, stamped as the
    probe's own load. Measured before the fix: twelve coloured lines
    on stdout between the header and "card:"."""
    from core.fdm.console import jsbsim_console
    from core.scenario.card import _MIXTURE_CACHE, write_run_card

    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    _MIXTURE_CACHE.clear()       # force the probe: the cache is per process
    log = tmp_path / "jsbsim.log"
    capfd.readouterr()
    with jsbsim_console(log) as sink:
        write_run_card(spec, tmp_path / "card.json")
    out, err = capfd.readouterr()
    assert out == "" and err == "", (out, err)
    text = log.read_text(encoding="utf-8")
    assert "Mass Properties Report" in text
    assert "End of vehicle configuration loading" in text
    assert "JSBSim startup beginning" in text
    assert sink.loads == 1
    assert sink.labels == ["FGFDMExec(B747, mixture probe) called from "
                           "core.scenario.card.attempt"]
    assert text.startswith("# load 1: FGFDMExec(B747, mixture probe) called "
                           "from core.scenario.card.attempt\n")


def test_the_report_opens_with_a_header(report_run):
    out, text = report_run
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    lines = text.splitlines()
    assert lines[0] == f"spec {manifest['spec_digest'][:16]} valid; running headlessly..."
    assert lines[1] == f"run:         {out}"
    assert lines[2] == (f"spec         {manifest['spec_digest'][:16]}   "
                        f"simulation {manifest['simulation_digest'][:16]}   "
                        f"output {manifest['output_digest'][:16]}")
    assert lines[3] == "scene        flat (no raster)   crs EPSG:32631"
    # The flight line states the window the schedule lives in, from the
    # record itself, beside the spec's duration.
    telemetry = json.loads(
        (out / "telemetry.json").read_text(encoding="utf-8"))["columns"]["t"]
    gaps = sorted(b - a for a, b in zip(telemetry, telemetry[1:]))
    assert lines[4] == (
        f"flight       B747, 12 s at 120 Hz (step 0.008333 s); telemetry t "
        f"{telemetry[0]:.3f}..{telemetry[-1]:.3f} s ({len(telemetry)} "
        f"samples, {gaps[len(gaps) // 2]:.3f} s apart); span 64.5 m")
    assert lines[4].startswith("flight       B747, 12 s at 120 Hz (step "
                               "0.008333 s); telemetry t 0.008..11.992 s "
                               "(115 samples, 0.108 s apart); span 64.5 m")
    assert lines[5] == "cameras      2"
    assert lines[6] == ("  chase0  chase/offset  aim aircraft (lag 0.25 s: "
                        "the pixel trails the aircraft)  1280x720  "
                        "35.0 mm (fx 1244.4 px)  24 captures, interval")
    assert lines[7] == ("  tower0  tower/scene  aim aircraft (lag 0.25 s: "
                        "the pixel trails the aircraft)  1280x720  "
                        "35.0 mm (fx 1244.4 px)  24 captures, interval")
    # flightsim.verify prints the same header from the manifest alone.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out)]) == 0
    printed = buffer.getvalue().splitlines()
    assert printed[:7] == lines[1:8]


def test_the_schedule_table_lists_every_instant(report_run):
    out, text = report_run
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert "scheduled 48 frames across 2 camera(s)" in text
    for block in manifest["cameras"]:
        rows = schedule_rows_printed(text, block["camera_id"])
        records = [r for r in manifest["frames"]
                   if r["camera_id"] == block["camera_id"]]
        assert len(rows) == block["capture_count"] == len(records)
        assert [r[0] for r in rows] == list(range(block["capture_count"]))
        for (idx, t_s, sample), record in zip(rows, records):
            assert t_s == pytest.approx(record["t_s"], abs=5e-4)
            assert sample == record["sample_index"]
    # The camera's own line names the schedule basis.
    assert ("  chase0: 24 scheduled instant(s) (count 24 spread over "
            "[0.00833333, 11.9917] s, endpoints included)") in text
    # --brief collapses each camera to one honest line: this count
    # schedule is sample-snapped, so no period is claimed.
    code, brief = capture_text([str(EXAMPLES / "cameras_multi.yaml"), "--out",
                                str(out.parent / "brief"), "--max-previews",
                                "0", "--render", "none", "--brief"])
    assert code == 0
    assert schedule_rows_printed(brief, "chase0") == []
    assert re.search(r"^    0\.\.23 spaced 0\.\d{3}\.\.0\.\d{3} s "
                     r"\(sample-snapped, not uniform\) from 0\.008 s to "
                     r"11\.992 s \(samples 0\.\.114\)$", brief, re.M)


def test_the_flight_line_and_brief_name_the_window_and_the_trigger(tmp_path):
    """cameras_waypoint: a 30 s spec whose record runs 4.900..34.858 s
    (the c172p's trim and engine start ran the clock first) and whose
    last instant is t=33.017 s -- the flight line says so; --brief words
    the spacing from the distance trigger, never as sample snapping."""
    out = tmp_path / "waypoint"
    code, text = capture_text([str(EXAMPLES / "cameras_waypoint.yaml"),
                               "--out", str(out), "--max-previews", "0",
                               "--render", "none", "--brief"])
    assert code == 0, text
    telemetry = json.loads(
        (out / "telemetry.json").read_text(encoding="utf-8"))["columns"]["t"]
    assert telemetry[0] > 1.0                  # the clock ran before the record
    flight = next(line for line in text.splitlines()
                  if line.startswith("flight "))
    assert flight == (
        f"flight       c172p, 30 s at 120 Hz (step 0.008333 s); telemetry t "
        f"{telemetry[0]:.3f}..{telemetry[-1]:.3f} s ({len(telemetry)} samples, "
        f"0.108 s apart), the clock at {telemetry[0]:.3f} s when the record "
        f"began (trim and engine start); span 10.9 m")
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    times = [r["t_s"] for r in manifest["frames"]]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert re.search(
        rf"^    0\.\.4 every 400 m of track; instants {min(gaps):.3f}\.\."
        rf"{max(gaps):.3f} s apart from {times[0]:.3f} s to {times[-1]:.3f} s "
        rf"\(samples 0\.\.{manifest['frames'][-1]['sample_index']}\)$",
        text, re.M), text
    assert "sample-snapped" not in text
    # flightsim.verify prints the same flight line from telemetry.json.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--brief"]) == 0
    printed = buffer.getvalue()
    assert flight in printed.splitlines()
    assert "every 400 m of track; instants" in printed


def off_aim_printed(text, camera_id):
    """The printed off-aim column of one camera: [float or None]."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines)
                 if line.startswith(f"  {camera_id}: ") and "scheduled instant"
                 in line)
    assert lines[start + 1].rstrip().endswith("aircraft px (u, v)  off-aim px")
    values = []
    for line in lines[start + 2:]:
        match = re.match(r"\s+\d+\s+[\d.]+\s+\d+\s+.*\)\s+(-|[\d.]+)$", line)
        if not match:
            break
        values.append(None if match.group(1) == "-" else float(match.group(1)))
    return values


def test_the_header_states_the_aim_reference_and_the_table_its_miss(
        report_run, tmp_path):
    """cameras_multi_cockpit's shoulder camera says 'aim aircraft' and
    shows the aircraft 332 px below centre in every frame: the cockpit
    preset looks along the body axis, so the header says where the cg
    is and which pixel that is, and the off-aim column measures the
    table's pixel against THAT promise (0.0 px), while the chase and
    tower cameras' off-aim is their distance from the centre -- the aim
    lag the header names."""
    out, text = report_run
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    for camera_id in ("chase0", "tower0"):
        values = off_aim_printed(text, camera_id)
        assert len(values) == 24
        records = [r for r in manifest["frames"] if r["camera_id"] == camera_id]
        for value, record in zip(values, records):
            u, v = record["principal_point_px"]
            from core.capture.verify import project_point

            pu, pv, _ = project_point(record, (
                record["aircraft"]["north_m"], record["aircraft"]["east_m"],
                record["aircraft"]["alt_m"]))
            assert value == pytest.approx(
                ((pu - u) ** 2 + (pv - v) ** 2) ** 0.5, abs=0.06)
        assert values[0] == 0.0 and 0.0 < max(values) < 30.0
    cockpit = tmp_path / "cockpit"
    code, printed = capture_text([str(COCKPIT), "--out", str(cockpit),
                                  "--max-previews", "0", "--render", "none"])
    assert code == 0, printed
    lines = printed.splitlines()
    camera = next(i for i, line in enumerate(lines)
                  if line.startswith("  shoulder  cockpit/offset  "))
    assert lines[camera] == ("  shoulder  cockpit/offset  aim body axis  "
                             "1280x720  35.0 mm (fx 1244.4 px)  24 captures, "
                             "interval")
    assert lines[camera + 1] == (
        "            (aim_mode aircraft is not applied by the cockpit preset: "
        "the view is along the body axis; the cg sits 6 m ahead, 1.6 m below "
        "and 0.5 m right of the lens, so its pixel is (743.7, 691.9), "
        "(+103.7, +331.9) px from the image centre)")
    values = off_aim_printed(printed, "shoulder")
    assert len(values) == 24 and max(values) < 0.05
    rows = schedule_rows_printed(printed, "shoulder")
    assert len(rows) == 24
    assert re.search(r"^\s+0\s+0\.008\s+0\s+.*\(743\.7, 691\.9\)\s+0\.0$",
                     printed, re.M), printed
    # verify prints the same header words from the manifest alone, and
    # --json carries the reference as data.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(cockpit), "--json"]) == 0
    doc = json.loads(buffer.getvalue())
    reference = doc["header"]["cameras"][0]["aim_reference"]
    assert reference["kind"] == "body-axis"
    assert reference["predicted_offset_px"] == pytest.approx(
        [103.7, 331.9], abs=0.05)
    assert lines[camera + 1] in doc["text"]
    assert doc["schedule"]["columns"][-1] == "off-aim px"
    assert all(r["off_aim_px"] < 0.05 and r["aim_kind"] == "body-axis"
               for r in doc["schedule"]["cameras"]["shoulder"])


def test_the_verification_table_has_measured_tolerance_status_and_where(
        report_run):
    out, text = report_run
    rows = verification_rows(text)
    verify = json.loads((out / "verify.json").read_text(encoding="utf-8"))
    assert list(rows) == [c["name"] for c in verify["checks"]]
    for check in verify["checks"]:
        status, measured, tolerance, where = rows[check["name"]]
        assert status == check["status"]
        if check["ok"] is None:
            assert measured == "-" and tolerance == "-"
        else:
            assert measured == check["measured_text"]
            assert tolerance == check["tolerance_text"]
            assert where == check["where"]
    assert rows["geometry_recovery"][1:3] == (
        verify["checks"][2]["measured_text"], "0.5 px")
    assert rows["geometry_recovery"][3].startswith("worst ")
    assert rows["cross_view_consistency"][2] == "0.5 m"
    assert rows["cross_view_consistency"][3].startswith(
        "24 two-view instants; worst sample ")
    assert rows["count_exactness"][1:] == (
        "48 frames = 24 + 24", "exactly 48", "chase0 24/24, tower0 24/24")
    assert rows["engine_parity"][0] == "AWAITING"
    # The detail block (rows that did not PASS: engine parity AWAITING
    # here) follows, then the summary, then the verdict; every PASS is
    # rendered once, in the table.
    lines = text.splitlines()
    assert "  detail:" in lines
    assert [line for line in lines if line.startswith("  [")] == [
        "  [AWAITING] engine_parity: " + verify["checks"][-1]["detail"]]
    assert "[PASS]" not in text
    assert "verification PASSED (9/9 checks; 1 awaiting engine frames: " \
           "engine_parity)" in lines
    assert lines[-1].startswith("done: ")


def test_json_gives_the_same_document_as_the_text(tmp_path):
    out = tmp_path / "json"
    code, printed = capture_text([str(EXAMPLES / "cameras_waypoint.yaml"),
                                  "--out", str(out), "--max-previews", "0",
                                  "--render", "none", "--json"])
    assert code == 0
    doc = json.loads(printed)             # nothing but the document
    assert doc["verdict"] == "done" and doc["exit_code"] == 0
    assert doc["command"] == "python -m flightsim.capture"
    for key in ("header", "schedule", "previews", "verification",
                "artefacts", "render", "jsbsim", "text"):
        assert key in doc, key
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert doc["header"]["spec_digest"] == manifest["spec_digest"]
    assert doc["header"]["cameras"][0]["camera_id"] == "survey"
    assert doc["header"]["cameras"][0]["capture_count"] == 5
    rows = doc["schedule"]["cameras"]["survey"]
    assert [r["t_s"] for r in rows] == [r["t_s"] for r in manifest["frames"]]
    assert doc["verification"] == json.loads(
        (out / "verify.json").read_text(encoding="utf-8"))
    assert doc["verification"]["skipped"] == [
        {"name": "cross_view_consistency", "reason": "single camera"}]
    assert doc["render"]["choice"] == "none"
    assert doc["jsbsim"]["log"] == str(out / "jsbsim.log")
    assert doc["artefacts"]["manifest"] == str(out / "capture_manifest.json")
    # The text lines are the report the numbers were rendered into.
    assert any(line.startswith("done: manifest, 0 previews")
               for line in doc["text"])
    assert not any("JSBSim startup" in line for line in doc["text"])
    # verify --json: the same verification document, as data.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--json"]) == 0
    verified = json.loads(buffer.getvalue())
    assert verified["verdict"] == "verified" and verified["exit_code"] == 0
    assert verified["verification"]["checks"] == doc["verification"]["checks"]
    assert verified["header"]["cameras"] == doc["header"]["cameras"]
    assert verified["artefacts"]["verify_json"] == str(out / "verify.json")
    # Every check carries the table's numbers as fields.
    for check in verified["verification"]["checks"]:
        for key in ("measured", "tolerance", "unit", "measured_text",
                    "tolerance_text", "where", "skipped_reason"):
            assert key in check, (check["name"], key)


#: Every check each corruption fails, exactly: the named one first, and
#: the checks that see the same damage from their own side (a clock
#: shifted on every record is not the telemetry's clock AND not the
#: spec's schedule; one instant moved a step is seen by the flight, the
#: schedule and the sibling run).
CORRUPT_FAILS_EXACTLY = {
    # A twisted quaternion is seen by the Euler cross-check, by the ray
    # cast from the true pose through the twisted label (18 m), and by
    # the pose recomputed from the spec.
    "quaternion": ["geometry_recovery", "cross_view_consistency",
                   "pose_fidelity", "aim_fidelity"],
    "aircraft": ["cross_view_consistency", "flight_fidelity"],
    "time": ["flight_fidelity", "schedule_fidelity", "temporal_alignment"],
    "count": ["count_exactness", "schedule_fidelity"],
    "clock": ["flight_fidelity", "schedule_fidelity"],
    # Round 3: the cross-view rays are cast from the recomputed poses
    # against the telemetry's aircraft, so the labels of both views
    # triangulating 50 m from the flight fail that row too.
    "flight": ["cross_view_consistency", "flight_fidelity"],
    "schedule": ["schedule_fidelity"],
    # A moved camera's promise is computed from where the record says
    # it stands, so its orientation no longer matches the promise either.
    "pose": ["cross_view_consistency", "pose_fidelity", "aim_fidelity"],
    "lens": ["cross_view_consistency", "pose_fidelity"],
    "aim": ["cross_view_consistency", "pose_fidelity", "aim_fidelity"],
}


@pytest.mark.parametrize("kind, check, offender", [
    ("quaternion", "geometry_recovery", "worst chase0 #3 t=1.608 s"),
    ("aircraft", "cross_view_consistency",
     "24 two-view instants; worst sample 0 t=0.008 s (chase0 #0 with tower0 #0)"
     "; rays from the poses recomputed from the spec through each record's "
     "own label, against the telemetry's aircraft"),
    ("time", "temporal_alignment",
     "25 instants in report0_corrupt_time vs 24 in report0; only in "
     "report0_corrupt_time: t=1.616667 s"),
    ("count", "count_exactness", "chase0 23/24, tower0 24/24"),
    ("clock", "flight_fidelity",
     re.compile(r"instant differs from the telemetry by 0\.500000 s at "
                r"chase0 #\d+ t=\d+\.\d{3} s \(telemetry t=\d+\.\d{6} s "
                r"at sample \d+\)")),
    ("flight", "flight_fidelity",
     re.compile(r"aircraft position differs from the telemetry by 50\.000 m "
                r"at chase0 #\d+ t=\d+\.\d{3} s \(recorded aircraft "
                r"-?\d+\.\d{3} N, -?\d+\.\d{3} E, \d+\.\d{3} m; telemetry "
                r"-?\d+\.\d{3} N, -?\d+\.\d{3} E, \d+\.\d{3} m at sample "
                r"\d+\)")),
    ("schedule", "schedule_fidelity",
     "2 of 48 instants differ from the spec's schedule; worst chase0 #12 at "
     "sample 60 t=6.283 s where the spec schedules sample 59 t=6.183 s"),
    ("pose", "pose_fidelity",
     re.compile(r"camera position differs from the spec's track by 5\.000 m "
                r"at tower0 #\d+ t=\d+\.\d{3} s \(recorded 900\.000 N, "
                r"-795\.000 E, 80\.000 m; the spec's track 900\.000 N, "
                r"-800\.000 E, 80\.000 m at sample \d+\)")),
    ("lens", "pose_fidelity",
     re.compile(r"lens differs from the spec's camera by 622\.222 px "
                r"\(17\.500 mm\) at chase0 #\d+ t=\d+\.\d{3} s \(recorded fx "
                r"1866\.667, fy 1866\.667 px, focal 52\.500 mm; the spec's "
                r"camera fx 1244\.444, fy 1244\.444 px, focal 35\.000 mm\)")),
    ("aim", "aim_fidelity",
     re.compile(r"the aircraft's pixel is 21\.675 px from where the camera's "
                r"promise puts it at chase0 #\d+ t=\d+\.\d{3} s \(aircraft at "
                r"\(\d+\.\d, \d+\.\d\) px, promised \(\d+\.\d, \d+\.\d\) px: "
                r"aircraft-lagged, off-aim \d+\.\d px against a predicted "
                r"\d+\.\d\)")),
])
def test_corrupt_fails_the_named_check_with_exit_1(report_run, kind, check,
                                                    offender):
    """--corrupt KIND: one named edit on a copy, the same verifier, and
    the named check FAILS with its offender in the WHERE column."""
    out, _ = report_run
    before = sorted(p.name for p in out.iterdir())
    copy = out.parent / f"{out.name}_corrupt_{kind}"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = verify_main([str(out), "--corrupt", kind])
    text = buffer.getvalue()
    assert code == 1, text
    lines = text.splitlines()
    assert lines[0].startswith(f"corrupt {kind}: manifest copied to "
                               f"{copy}; corrupted ")
    assert lines[1] == f"  expected: [FAIL] {check}, exit 1"
    rows = verification_rows(text)
    assert rows[check][0] == "FAIL"
    if isinstance(offender, str):
        assert rows[check][3] == offender.replace("report0", out.name), \
            rows[check]
    else:
        assert offender.fullmatch(rows[check][3]), rows[check]
    failed = [name for name, row in rows.items() if row[0] == "FAIL"]
    assert failed == CORRUPT_FAILS_EXACTLY[kind]
    if kind == "flight":
        # The two views still agree with EACH OTHER (a records-only grade
        # would pass); the rays cast from the recomputed poses meet 50 m
        # from the flight, and the row says which it graded.
        assert rows["cross_view_consistency"][0] == "FAIL"
        assert rows["cross_view_consistency"][1] == "50.0 m"
        assert rows["cross_view_consistency"][3].endswith(
            "; rays from the poses recomputed from the spec through each "
            "record's own label, against the telemetry's aircraft")
    if kind == "schedule":
        # The moved records ARE the flight, and the spec's pose, at
        # their new sample.
        assert rows["flight_fidelity"][0] == "PASS"
        assert rows["cross_view_consistency"][0] == "PASS"
        assert rows["pose_fidelity"][0] == "PASS"
    if kind in ("pose", "lens", "aim"):
        # The records agree with themselves and with the flight; only
        # the pose recomputed from the spec tells (and the ray cast
        # from it, and the promise recomputed over the telemetry).
        assert rows["geometry_recovery"][0] == "PASS"
        assert rows["flight_fidelity"][0] == "PASS"
        assert rows["schedule_fidelity"][0] == "PASS"
    if kind == "lens":
        # Both the measured and the promised pixel go through the
        # record's own lens: the promise scales with it.
        assert rows["aim_fidelity"][0] == "PASS"
    assert f"[FAIL] {check}:" in text
    also = CORRUPT_FAILS_EXACTLY[kind][:]
    also.remove(check)
    assert lines[-1].startswith(
        f"FAILED verification: as expected for --corrupt {kind}, {check} "
        f"FAILED" + (f" (also: {', '.join(also)})" if also else "") + "; ")
    assert (copy / "capture_manifest.json").is_file()
    assert (copy / "verify.json").is_file()
    assert lines[-1].endswith(f"; {copy / 'capture_manifest.json'} graded, "
                              f"report {copy / 'verify.json'}")
    # The original is untouched -- the copy is a SIBLING, the run's own
    # tree holds exactly what capture wrote -- and it still verifies.
    assert sorted(p.name for p in out.iterdir()) == before
    assert not any(p.name.startswith("corrupt_") for p in out.iterdir())
    with contextlib.redirect_stdout(io.StringIO()):
        assert verify_main([str(out)]) == 0


def test_corrupt_measures_the_damage(report_run):
    out, _ = report_run
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "quaternion"])
    rows = verification_rows(buffer.getvalue())
    measured = float(rows["geometry_recovery"][1].split()[0])
    assert measured > 100.0 and rows["geometry_recovery"][1].endswith(" px")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "aircraft"])
    rows = verification_rows(buffer.getvalue())
    measured = float(rows["cross_view_consistency"][1].split()[0])
    assert 5.0 <= measured < 6.0
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "time"])
    rows = verification_rows(buffer.getvalue())
    assert rows["temporal_alignment"][1:3] == ("25 vs 24 instants", "1e-09 s")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "count"])
    text = buffer.getvalue()
    rows = verification_rows(text)
    assert rows["count_exactness"][1:3] == ("47 frames = 23 + 24",
                                            "exactly 48")
    assert "(missing index 23)" in text
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "clock"])
    rows = verification_rows(buffer.getvalue())
    assert rows["flight_fidelity"][1:3] == ("t 0.5 s, pos 0 m, att 0 deg",
                                            "1e-09 s, 1e-06 m, 1e-06 deg")
    assert rows["schedule_fidelity"][1:3] == ("48 of 48 instants differ",
                                              "0 differ")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "flight"])
    rows = verification_rows(buffer.getvalue())
    assert rows["flight_fidelity"][1] == "t 0 s, pos 50 m, att 0 deg"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "schedule"])
    rows = verification_rows(buffer.getvalue())
    assert rows["schedule_fidelity"][1:3] == ("2 of 48 instants differ",
                                              "0 differ")
    assert rows["flight_fidelity"][1] == "t 0 s, pos 0 m, att 0 deg"
    assert rows["pose_fidelity"][1] == "pos 0 m, ang 0 deg, lens 0 px"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "pose"])
    rows = verification_rows(buffer.getvalue())
    assert rows["pose_fidelity"][1:3] == ("pos 5 m, ang 0 deg, lens 0 px",
                                          "1e-06 m, 1e-06 deg, 1e-06 px")
    measured = float(rows["cross_view_consistency"][1].split()[0])
    assert 2.0 <= measured < 3.0                # 2.4705 m measured here
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "lens"])
    rows = verification_rows(buffer.getvalue())
    assert rows["pose_fidelity"][1] == "pos 0 m, ang 0 deg, lens 622.222 px"
    assert rows["geometry_recovery"][0] == "PASS"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        verify_main([str(out), "--corrupt", "aim"])
    rows = verification_rows(buffer.getvalue())
    assert rows["aim_fidelity"][1:3] == ("gap 21.7 px", "1e-06 px, 1e-06 deg")
    assert rows["geometry_recovery"][0] == "PASS"
    assert rows["pose_fidelity"][1] == "pos 0 m, ang 1 deg, lens 0 px"
    # The honest run's own aim row: the off-aim column, graded.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out)]) == 0
    rows = verification_rows(buffer.getvalue())
    assert rows["aim_fidelity"][0] == "PASS"
    assert rows["aim_fidelity"][3] == (
        "48 records; chase0 aircraft-lagged: off-aim up to 22.2 px, "
        "predicted 22.2; tower0 aircraft-lagged: off-aim up to 13.7 px, "
        "predicted 13.7")
    assert float(rows["aim_fidelity"][1].split()[1]) < 1e-9


def test_the_verifier_reads_the_flight_not_only_the_manifest(report_run,
                                                              tmp_path):
    """The judge's demonstration against round 1, now a test: a manifest
    that disagrees with telemetry.json or with the spec's schedule
    FAILS its own verification, with no sibling run to align against.
    Round 1 passed all three 5/5."""
    import shutil

    out, _ = report_run
    # (1) every record's aircraft north += 50 m, both cameras.
    moved = tmp_path / "moved"
    shutil.copytree(out, moved, ignore=shutil.ignore_patterns("corrupt_*"))
    manifest = json.loads(
        (moved / "capture_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["frames"]:
        record["aircraft"]["north_m"] += 50.0
    (moved / "capture_manifest.json").write_text(json.dumps(manifest),
                                                 encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(moved)]) == 1
    rows = verification_rows(buffer.getvalue())
    assert rows["flight_fidelity"][0] == "FAIL"
    assert rows["cross_view_consistency"][0] == "FAIL"      # round 3
    assert rows["pose_fidelity"][0] == "PASS"
    # (2) every t_s += 0.5 s, sample_index untouched.
    late = tmp_path / "late"
    shutil.copytree(out, late, ignore=shutil.ignore_patterns("corrupt_*"))
    manifest = json.loads(
        (late / "capture_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["frames"]:
        record["t_s"] += 0.5
    (late / "capture_manifest.json").write_text(json.dumps(manifest),
                                                encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(late)]) == 1
    rows = verification_rows(buffer.getvalue())
    assert rows["flight_fidelity"][0] == "FAIL"
    assert rows["schedule_fidelity"][0] == "FAIL"
    # (3) the --corrupt time copy, verified ALONE (no --against).
    with contextlib.redirect_stdout(io.StringIO()):
        verify_main([str(out), "--corrupt", "time"])
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out.parent / f"{out.name}_corrupt_time")]) == 1
    rows = verification_rows(buffer.getvalue())
    assert rows["flight_fidelity"][0] == "FAIL"
    assert "temporal_alignment" not in rows
    # A telemetry.json that is not this flight's is named by digest.
    swapped = tmp_path / "swapped"
    shutil.copytree(out, swapped, ignore=shutil.ignore_patterns("corrupt_*"))
    telemetry = json.loads(
        (swapped / "telemetry.json").read_text(encoding="utf-8"))
    telemetry["columns"]["altitude_m"][-1] += 1.0
    (swapped / "telemetry.json").write_text(json.dumps(telemetry),
                                            encoding="utf-8")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(swapped)]) == 1
    text = buffer.getvalue()
    assert "telemetry.json digests to " in text
    assert "not the manifest's output_digest" in text


def test_a_corruption_the_verifier_misses_is_unexpected_not_caught(
        report_run, monkeypatch):
    """--corrupt reports FAILED only when the NAMED check failed; a
    verifier that lets the corruption through is UNEXPECTED (exit 4),
    never a FAILED the instructor would read as 'caught'."""
    from core.capture.verify import VerificationReport

    out, _ = report_run

    def blind(run_dir, other_run_dir=None):
        report = VerificationReport()
        report.add("manifest_version", True, "stub")
        report.add("count_exactness", True, "stub: the drop went unnoticed")
        return report

    monkeypatch.setattr("core.capture.verify.verify_run", blind)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = verify_main([str(out), "--corrupt", "count"])
    text = buffer.getvalue()
    assert code == 4, text
    assert text.splitlines()[-1] == (
        "UNEXPECTED: --corrupt count did not fail count_exactness (FAILED: "
        "none); the verifier cannot be trusted to catch this corruption")
    assert "FAILED verification: as expected" not in text


def test_corrupt_dir_is_honoured_and_never_inside_the_run(report_run,
                                                           tmp_path):
    out, _ = report_run
    elsewhere = tmp_path / "elsewhere" / "copy"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--corrupt", "count",
                            "--corrupt-dir", str(elsewhere)]) == 1
    text = buffer.getvalue()
    assert text.splitlines()[0].startswith(
        f"corrupt count: manifest copied to {elsewhere}; ")
    assert (elsewhere / "capture_manifest.json").is_file()
    assert (elsewhere / "telemetry.json").is_file()
    assert (elsewhere / "scenario.yaml").is_file()
    assert (elsewhere / "verify.json").is_file()
    assert not (out / "corrupt_count").exists()
    # A copy inside the run is refused by usage: the run stays what
    # capture wrote.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--corrupt", "count",
                            "--corrupt-dir", str(out / "corrupt_count")]) == 3
    assert buffer.getvalue().splitlines()[-1].startswith(
        f"USAGE: --corrupt-dir {out / 'corrupt_count'} lies inside the run ")
    assert not (out / "corrupt_count").exists()


def test_corrupt_aircraft_needs_two_cameras(tmp_path):
    out = tmp_path / "solo"
    code, _ = capture_text([str(EXAMPLES / "cameras_waypoint.yaml"), "--out",
                            str(out), "--max-previews", "0", "--render",
                            "none"])
    assert code == 0
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--corrupt", "aircraft"]) == 3
    assert buffer.getvalue().startswith(
        f"USAGE: {out}: --corrupt aircraft needs a two-camera run")


def test_the_committed_cockpit_example_aligns_with_cameras_multi(report_run,
                                                                  tmp_path):
    """examples/cameras_multi_cockpit.yaml: the same flight, a different
    camera set, committed -- the temporal-alignment check's exercise an
    instructor runs from the tree."""
    out, _ = report_run
    other = tmp_path / "demo_b"
    code, text = capture_text([str(COCKPIT), "--out", str(other),
                               "--max-previews", "0", "--render", "none"])
    assert code == 0, text
    a = json.loads((out / "capture_manifest.json").read_text(encoding="utf-8"))
    b = json.loads((other / "capture_manifest.json").read_text(encoding="utf-8"))
    assert a["simulation_digest"] == b["simulation_digest"]
    assert a["output_digest"] == b["output_digest"]
    assert [c["camera_id"] for c in b["cameras"]] == ["shoulder"]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(other), "--against", str(out)]) == 0
    text = buffer.getvalue()
    assert f"against:     {out} (temporal alignment)" in text
    rows = verification_rows(text)
    assert rows["temporal_alignment"] == (
        "PASS", "0 s", "1e-09 s", "24 instants in both runs; worst gap 0 s")
    assert rows["cross_view_consistency"][0] == "SKIPPED"
    assert rows["pose_fidelity"][0] == "PASS"
    assert rows["aim_fidelity"][0] == "PASS"
    assert rows["aim_fidelity"][3] == ("24 records; shoulder body-axis: "
                                       "off-aim up to 347.7 px, predicted "
                                       "347.7")
    assert ("verification PASSED (9/9 checks; 1 skipped: "
            "cross_view_consistency (single camera); 1 awaiting engine "
            "frames: engine_parity)") in text
    assert text.splitlines()[-1].startswith(
        f"verified: {other / 'capture_manifest.json'} (24 frame records, "
        f"1 camera(s)); report {other / 'verify.json'}")


def test_exit_codes_share_one_table_and_the_verdict_line_names_them(
        report_run, tmp_path, monkeypatch):
    """0 done/verified, 1 FAILED, 2 REFUSED, 3 USAGE, 4 UNEXPECTED -- on
    both commands, and the last stdout line starts with the word."""
    out, text = report_run
    assert text.splitlines()[-1].startswith("done: ")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out)]) == 0
    assert buffer.getvalue().splitlines()[-1].startswith(
        f"verified: {out / 'capture_manifest.json'} (48 frame records, "
        f"2 camera(s)); report {out / 'verify.json'}")
    # 1: the verifier failed the artefact.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--corrupt", "count"]) == 1
    assert buffer.getvalue().splitlines()[-1].startswith("FAILED verification:")
    with contextlib.redirect_stdout(io.StringIO()):
        assert verify_main([str(out.parent / f"{out.name}_corrupt_count")]) == 1
    # 2: refused by name, before anything is produced.
    code, refused = capture_text([str(EXAMPLES / "cameras_refusal.yaml"),
                                  "--out", str(tmp_path / "refused"),
                                  "--render", "none"])
    assert code == 2
    lines = refused.splitlines()
    # The header from the spec alone comes first (round 3), then the
    # violations by name.
    assert lines[0] == f"run:         {tmp_path / 'refused'}"
    assert lines[1].startswith("spec         ") and lines[1].endswith(
        "   output -")
    assert lines[4] == "cameras      1"
    assert lines[6] == "REFUSED -- by name:"
    assert lines[-1] == ("REFUSED [camera.terrain_clearance]: nothing "
                         "produced (the run directory holds jsbsim.log only)")
    assert sorted(p.name for p in (tmp_path / "refused").iterdir()) == \
        ["jsbsim.log"]
    assert "JSBSim startup" not in refused
    # 3: usage -- the command line, or nothing to verify.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(tmp_path / "nowhere")]) == 3
    assert buffer.getvalue().splitlines()[-1].startswith(
        f"USAGE: {tmp_path / 'nowhere'} holds no capture_manifest.json")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out), "--bogus"]) == 3
    assert buffer.getvalue().splitlines()[-1] == (
        "USAGE: python -m flightsim.verify: unrecognized arguments: --bogus")
    code, usage = capture_text([str(EXAMPLES / "cameras_multi.yaml")])
    assert code == 3 and usage.splitlines()[-1].startswith(
        "USAGE: python -m flightsim.capture: the following arguments are "
        "required: --out")
    # 4: unexpected -- an exception, named, traceback on stderr.
    def boom(run_dir, other_run_dir=None):
        raise RuntimeError("stub: the verifier blew up")

    monkeypatch.setattr("core.capture.verify.verify_run", boom)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert verify_main([str(out)]) == 4
    assert buffer.getvalue().splitlines()[-1] == (
        "UNEXPECTED RuntimeError: stub: the verifier blew up (traceback on "
        "stderr)")
    # --help lists the table, once, for both commands.
    from flightsim.capture import build_parser as capture_parser
    from flightsim.verify import build_parser as verify_parser

    for parser in (capture_parser(), verify_parser()):
        help_text = parser.format_help()
        for code, word in ((0, "done"), (1, "FAILED"), (2, "REFUSED"),
                           (3, "USAGE"), (4, "UNEXPECTED")):
            assert re.search(rf"^  {code}  .*{word}", help_text, re.M), word


def test_a_missing_spec_is_usage_and_the_usage_line_prints_once(tmp_path,
                                                                  capsys):
    """A spec path that does not exist exits 3 with "USAGE: <path>: no
    such file" -- the table's own words, no traceback -- and every
    usage error names itself ONCE, on stdout where the verdict lives;
    stderr carries argparse's usage text alone."""
    nope = EXAMPLES / "nope.yaml"
    assert capture_main([str(nope), "--out", str(tmp_path / "x")]) == 3
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == f"USAGE: {nope}: no such file"
    assert captured.out.count("USAGE:") == 1
    assert "Traceback" not in captured.err and "USAGE:" not in captured.err
    assert not (tmp_path / "x").exists()
    # --json: the same verdict as data.
    assert capture_main([str(nope), "--out", str(tmp_path / "x"),
                         "--json"]) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc["exit_code"] == 3 and doc["verdict"] == "USAGE"
    assert doc["text"] == [f"USAGE: {nope}: no such file"]
    # An argparse error: once on stdout, argparse's usage on stderr.
    assert verify_main([str(tmp_path), "--bogus"]) == 3
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "USAGE: python -m flightsim.verify: unrecognized arguments: --bogus"]
    assert captured.err.startswith("usage: python -m flightsim.verify")
    assert "USAGE:" not in captured.err
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml")]) == 3
    captured = capsys.readouterr()
    assert captured.out.count("USAGE:") == 1 and "USAGE:" not in captured.err
    assert captured.err.startswith("usage: python -m flightsim.capture")


def test_the_documents_expected_output_matches_a_fresh_run(tmp_path):
    """docs/CAMERA_PHASE1_REPORT.md carries every example's output
    verbatim from a dated run (scripts/examples_expected.py). A fresh
    run here must reproduce each block: on the platform the document
    was measured on EXACTLY -- every digest, check number, pixel
    coordinate and camera position at its printed precision, only the
    wall-clock seconds per frame and the machine-worded engine line
    masked -- and on another platform (the CI legs, whose JSBSim build
    differs by bits) with numbers and digests masked as well, so the
    words, columns, check names, statuses and exit codes still count."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "examples_expected",
        Path(__file__).resolve().parents[1] / "scripts" / "examples_expected.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    doc_text = module.DOC.read_text(encoding="utf-8")
    doc = module.doc_blocks(doc_text)
    exact = module.measured_platform(doc_text) == module.this_platform()
    assert module.measured_platform(doc_text) is not None
    fresh = module.generate(tmp_path / "runs_root")
    assert [b["command"] for b in doc] == [r["command"] for r in fresh]
    assert len(doc) == len(module.COMMANDS) == 16
    for expected, actual in zip(doc, fresh):
        assert expected["code"] == actual["code"], expected["command"]
        want = module.shape(expected["text"], exact=exact)
        got = module.shape(actual["text"], exact=exact)
        assert want == got, (expected["command"], "exact" if exact else
                             "masked (another platform)",
                             [pair for pair in zip(want, got)
                              if pair[0] != pair[1]][:3])
    if exact:
        # The exact comparison really compares numbers: a digest and a
        # measured value are in the compared text verbatim.
        text = "\n".join(module.shape(doc[6]["text"], exact=True))
        assert "124.7076 px" in text
        assert re.search(r"^spec +[0-9a-f]{16} +simulation [0-9a-f]{16}", text,
                         re.M)
        first = "\n".join(module.shape(doc[0]["text"], exact=True))
        assert re.search(r"\d+\.\d+ s/frame", doc[0]["text"])
        assert "<s/frame>" in first and not re.search(r"\d s/frame", first)
    # The blocks say what they are: exit codes 0/0/0/0/0/2 then ten 1s.
    assert [b["code"] for b in doc] == [0, 0, 0, 0, 0, 2] + [1] * 10


def test_a_refusal_prints_the_header_from_the_spec(tmp_path):
    """A refused capture still says WHAT it refused: the header -- run,
    spec and simulation digests (output '-': nothing was flown), scene
    and CRS, flight, one line per camera with fx computed from the
    spec's focal length, sensor width and resolution -- printed from
    the spec alone before the violation, the JSBSim line and the
    REFUSED verdict; --json carries the same 'header' block."""
    from core.capture.manifest import simulation_digest

    spec = ScenarioSpec.read(EXAMPLES / "cameras_refusal.yaml")
    out = tmp_path / "refused"
    code, text = capture_text([str(EXAMPLES / "cameras_refusal.yaml"),
                               "--out", str(out), "--render", "none"])
    assert code == 2, text
    lines = text.splitlines()
    camera = spec.cameras[0]
    fx = (float(camera.focal_length_mm.value) * int(camera.width_px.value)
          / float(camera.sensor_width_mm.value))
    count = int(camera.capture_count.value)
    captures = (f"{count} captures, interval" if count else
                f"every {float(camera.period_s.value):g} s, interval")
    assert lines[:7] == [
        f"run:         {out}",
        f"spec         {spec.digest()[:16]}   simulation "
        f"{simulation_digest(spec)[:16]}   output -",
        "scene        flat (no raster)   crs EPSG:32631",
        f"flight       {spec.aircraft.value}, {float(spec.duration.value):g} "
        f"s at 120 Hz (step 0.008333 s)",
        "cameras      1",
        f"  buried  explicit/scene  aim aircraft (exact)  "
        f"{int(camera.width_px.value)}x{int(camera.height_px.value)}  "
        f"{float(camera.focal_length_mm.value):.1f} mm (fx {fx:.1f} px)  "
        f"{captures}",
        "REFUSED -- by name:",
    ]
    assert "camera.terrain_clearance" in lines[7]
    assert lines[-1] == ("REFUSED [camera.terrain_clearance]: nothing "
                         "produced (the run directory holds jsbsim.log only)")
    assert "JSBSim startup" not in text
    # --json: the same header as data, on the refusal path.
    code, printed = capture_text([str(EXAMPLES / "cameras_refusal.yaml"),
                                  "--out", str(tmp_path / "refused_json"),
                                  "--render", "none", "--json"])
    assert code == 2
    doc = json.loads(printed)
    assert doc["verdict"] == "REFUSED" and doc["exit_code"] == 2
    assert doc["header"]["spec_digest"] == spec.digest()
    assert doc["header"]["simulation_digest"] == simulation_digest(spec)
    assert doc["header"]["output_digest"] is None
    assert doc["header"]["scene"] == {"key": "flat", "terrain": None,
                                      "terrain_sha256": None,
                                      "crs": "EPSG:32631"}
    assert [c["camera_id"] for c in doc["header"]["cameras"]] == ["buried"]
    assert doc["header"]["cameras"][0]["fx_px"] == pytest.approx(fx)
    assert doc["header"]["cameras"][0]["flown"] is False
    assert doc["refusals"][0]["constraint"] == "camera.terrain_clearance"
    assert doc["text"][0] == f"run:         {tmp_path / 'refused_json'}"
    assert doc["text"][1:7] == lines[1:7]
    # A camera whose count the flight decides says so instead of a
    # number that was not computed.
    from flightsim.report import captures_words

    assert captures_words({"capture_count": 24, "trigger": "interval",
                           "flown": False}) == "24 captures, interval"
    assert captures_words({"capture_count": 0, "trigger": "interval",
                           "period_s": 1.0, "flown": False}) == \
        "every 1 s, interval"
    assert captures_words({"capture_count": 0, "trigger": "distance",
                           "flown": False}) == \
        "captures set by the flight, distance"
    assert captures_words({"capture_count": 5, "trigger": "distance",
                           "flown": True}) == "5 captures, distance"
