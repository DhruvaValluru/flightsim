"""Phase 10, package 4: render reproducibility is measured, not asserted.

The comparison is exercised on synthetic frame sets of the exact layout
the render commandlet writes; the experiment's engine-less path is
shown to report NOT RUN by name and exit nonzero rather than invent a
number; and the frame-integrity check is shown to fail on a replaced
frame.
"""

import hashlib
import json

import numpy as np
import pytest
from PIL import Image

from core.capture.repro import (
    BIT_IDENTICAL, BOUNDED, INCOMPLETE, compare_frame_sets, describe,
    engine_digests, frame_names, frame_sha256,
)
from core.capture.verify import FAIL, NOT_RUN, PASS, verify_frame_integrity


def _frames(directory, n=3, width=32, height=16, tweak=None, record=True):
    """A render directory: n frames, a render.json with sha256 per frame."""
    directory.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(n):
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        rgb[:, :, 0] = np.arange(width, dtype=np.uint8) * 7
        rgb[:, :, 1] = i * 40
        if tweak and tweak[0] == i:
            y, x, delta = tweak[1], tweak[2], tweak[3]
            rgb[y, x, 2] = delta
        name = f"frame_{i:04d}.png"
        Image.fromarray(rgb, mode="RGB").save(directory / name)
        records.append({"frame": name,
                        "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()})
    # Files with suffixes are not frames of the comparison.
    (directory / "frame_0000_mask.png").write_bytes(b"not a frame")
    if record:
        (directory / "render.json").write_text(
            json.dumps({"frames": n, "frame_records": records}), encoding="utf-8")
    return directory


def test_frame_names_are_the_plain_frames_only(tmp_path):
    _frames(tmp_path / "a")
    assert frame_names(tmp_path / "a") == ["frame_0000.png", "frame_0001.png",
                                           "frame_0002.png"]


def test_identical_renders_are_bit_identical(tmp_path):
    a, b = _frames(tmp_path / "a"), _frames(tmp_path / "b")
    report = compare_frame_sets(a, b)
    assert report["verdict"] == BIT_IDENTICAL
    assert report["frames_identical"] == report["frames_compared"] == 3
    assert report["max_abs_per_pixel"] == 0
    assert report["engine_digests_agree_with_files"] is True
    assert "BIT-IDENTICAL" in describe(report)


def test_one_pixel_one_bit_is_bounded_with_its_numbers(tmp_path):
    """No rounding, no forgiving: a single-channel difference of 1 in
    one pixel of one frame is 'bounded', max 1, fraction 1/N."""
    a = _frames(tmp_path / "a")
    b = _frames(tmp_path / "b", tweak=(1, 5, 9, 1))
    report = compare_frame_sets(a, b)
    assert report["verdict"] == BOUNDED
    assert report["frames_differing"] == 1
    assert report["max_abs_per_pixel"] == 1
    assert report["max_fraction_differing"] == pytest.approx(1.0 / (32 * 16))
    differing = [f for f in report["frames"] if f["status"] == BOUNDED]
    assert differing[0]["frame"] == "frame_0001.png"
    assert differing[0]["difference"]["comparable"]
    assert "BOUNDED" in describe(report) and "1 of 255" in describe(report)


def test_a_missing_frame_is_incomplete_not_ignored(tmp_path):
    a = _frames(tmp_path / "a", n=3)
    b = _frames(tmp_path / "b", n=2)
    report = compare_frame_sets(a, b)
    assert report["verdict"] == INCOMPLETE
    assert report["frames_missing"] == 1
    assert "INCOMPLETE" in describe(report)


def test_a_replaced_frame_is_reported_apart_from_a_render_difference(tmp_path):
    """The engine recorded one digest; the file on disk has another.
    That is a replaced frame, flagged as such, not a pixel difference."""
    a = _frames(tmp_path / "a")
    b = _frames(tmp_path / "b")
    Image.fromarray(np.full((16, 32, 3), 9, dtype=np.uint8), mode="RGB").save(
        b / "frame_0002.png")
    report = compare_frame_sets(a, b)
    assert report["engine_digests_agree_with_files"] is False
    assert any(f.get("engine_record_disagrees") for f in report["frames"])


def test_engine_digests_read_the_record_and_tolerate_its_absence(tmp_path):
    a = _frames(tmp_path / "a")
    assert engine_digests(a)["frame_0001.png"] == frame_sha256(a / "frame_0001.png")
    assert engine_digests(_frames(tmp_path / "none", record=False)) == {}
    assert compare_frame_sets(_frames(tmp_path / "x", record=False),
                              _frames(tmp_path / "y", record=False)
                              )["engine_digests_agree_with_files"] is None


# -- the experiment ----------------------------------------------------------

def test_the_gate_compares_two_directories_and_writes_a_report(tmp_path):
    from experiments.gate10_render_repro import main

    a = _frames(tmp_path / "a")
    b = _frames(tmp_path / "b", tweak=(0, 1, 1, 3))
    code = main(["--against", str(a), str(b), "--out", str(tmp_path / "gate")])
    assert code == 0
    report = json.loads((tmp_path / "gate" / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == BOUNDED
    assert report["max_abs_per_pixel"] == 3
    assert report["source"]["mode"] == "against"
    assert "BOUNDED" in report["statement"]


def test_the_gate_reports_not_run_by_name_with_no_engine(tmp_path, monkeypatch):
    """No engine: NOT RUN, ue.platform, exit 2, a report that says so --
    and no number anywhere in it."""
    import experiments.gate10_render_repro as gate

    monkeypatch.setattr(gate, "ue_available", lambda: False)
    card = tmp_path / "card.json"
    card.write_text("{}", encoding="utf-8")
    code = gate.main(["--card", str(card), "--out", str(tmp_path / "gate")])
    assert code == 2
    report = json.loads((tmp_path / "gate" / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "NOT RUN" and report["reason"] == "ue.platform"
    assert "max_abs_per_pixel" not in report


def test_the_gate_renders_with_the_deterministic_pins(tmp_path, monkeypatch):
    """When it renders, both passes go through the same wrapper with
    -Visual and -deterministic, and the report records exactly that."""
    import experiments.gate10_render_repro as gate

    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        frames = tmp_path / "gate" / ("render_A" if len(commands) == 1 else "render_B")
        _frames(frames)
        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr(gate, "ue_available", lambda: True)
    monkeypatch.setattr(gate, "ue_runner_command", lambda repo, stem: ["wrapper", stem])
    monkeypatch.setattr("subprocess.run", fake_run)
    card = tmp_path / "card.json"
    card.write_text("{}", encoding="utf-8")
    code = gate.main(["--card", str(card), "--out", str(tmp_path / "gate")])
    assert code == 0
    assert len(commands) == 2
    for command in commands:
        assert "-deterministic" in command and "-Visual" in command
    assert commands[0][:3] == commands[1][:3]
    report = json.loads((tmp_path / "gate" / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == BIT_IDENTICAL
    assert "-deterministic" in report["source"]["wrapper_arguments"]


# -- the verifier -----------------------------------------------------------

def _manifest_for(frames_dir, camera="chase0", n=3):
    return {"frames": [{"camera_id": camera, "file": f"frames/{camera}/frame_{i:04d}.png"}
                       for i in range(n)]}


def test_frame_integrity_passes_and_fails_on_a_replaced_frame(tmp_path):
    frames = _frames(tmp_path / "frames" / "chase0")
    manifest = _manifest_for(frames)
    assert verify_frame_integrity(manifest, tmp_path).status == PASS
    Image.fromarray(np.full((16, 32, 3), 1, dtype=np.uint8), mode="RGB").save(
        frames / "frame_0001.png")
    check = verify_frame_integrity(manifest, tmp_path)
    assert check.status == FAIL and "frame_0001.png" in check.detail
    # A frame the manifest names that the engine never recorded.
    manifest["frames"].append({"camera_id": "chase0",
                               "file": "frames/chase0/frame_0007.png"})
    assert "not in the engine's record" in verify_frame_integrity(manifest, tmp_path).detail


def test_frame_integrity_is_not_run_without_digests(tmp_path):
    frames = _frames(tmp_path / "frames" / "chase0", record=False)
    assert verify_frame_integrity(_manifest_for(frames), tmp_path).status == NOT_RUN
    assert verify_frame_integrity(_manifest_for(frames), None).status == NOT_RUN


# -- the engine's applied pose, graded Python-side ---------------------------

def _applied_manifest(tmp_path, n=3, camera="chase0"):
    frames = _frames(tmp_path / "frames" / camera, n=n)
    manifest = {"frames": []}
    records = []
    for i in range(n):
        pose = {"position_north_m": 100.0 + i, "position_east_m": -5.0,
                "position_alt_m": 3000.0, "yaw_deg": 10.0, "pitch_deg": -2.0,
                "roll_deg": 0.0}
        manifest["frames"].append({"camera_id": camera,
                                   "file": f"frames/{camera}/frame_{i:04d}.png", **pose})
        records.append({"frame": f"frame_{i:04d}.png",
                        "camera_applied_north_m": pose["position_north_m"],
                        "camera_applied_east_m": pose["position_east_m"],
                        "camera_applied_alt_m": pose["position_alt_m"],
                        "camera_applied_yaw_deg": pose["yaw_deg"],
                        "camera_applied_pitch_deg": pose["pitch_deg"],
                        "camera_applied_roll_deg": pose["roll_deg"]})
    (frames / "render.json").write_text(json.dumps({"frame_records": records}),
                                        encoding="utf-8")
    return manifest, frames / "render.json"


def test_applied_pose_passes_fails_and_is_not_run(tmp_path):
    from core.capture.verify import verify_applied_pose

    manifest, render_json = _applied_manifest(tmp_path)
    assert verify_applied_pose(manifest, tmp_path).status == PASS
    payload = json.loads(render_json.read_text(encoding="utf-8"))
    payload["frame_records"][1]["camera_applied_east_m"] += 0.2     # 20 cm off
    render_json.write_text(json.dumps(payload), encoding="utf-8")
    check = verify_applied_pose(manifest, tmp_path)
    assert check.status == FAIL and "frame_0001.png" in check.detail
    payload["frame_records"][1]["camera_applied_east_m"] -= 0.2
    payload["frame_records"][2]["camera_applied_yaw_deg"] += 0.1     # 0.1 deg off
    render_json.write_text(json.dumps(payload), encoding="utf-8")
    check = verify_applied_pose(manifest, tmp_path)
    assert check.status == FAIL and "frame_0002.png" in check.detail
    del payload["frame_records"][2]["camera_applied_yaw_deg"]
    payload["frame_records"] = payload["frame_records"][:2]
    render_json.write_text(json.dumps(payload), encoding="utf-8")
    assert "recorded no applied pose" in verify_applied_pose(manifest, tmp_path).detail
    render_json.unlink()
    assert verify_applied_pose(manifest, tmp_path).status == NOT_RUN
    assert verify_applied_pose(manifest, None).status == NOT_RUN
