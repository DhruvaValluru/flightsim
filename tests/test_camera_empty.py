"""A camera whose render pass wrote no frames is refused by name."""
from pathlib import Path

import pytest
import yaml

from core.capture.frames import (camera_empty_message, empty_camera_ids,
                                 frames_by_camera)


def _run_dir(tmp_path: Path, counts: dict) -> Path:
    frames = tmp_path / "frames"
    for cam, n in counts.items():
        (frames / cam).mkdir(parents=True)
        for i in range(n):
            (frames / cam / f"frame_{i:04d}.png").write_bytes(b"x")
        # labelled companions must not count
        if n:
            (frames / cam / "frame_0000_mask.png").write_bytes(b"x")
    return frames


def test_empty_camera_dir_named(tmp_path):
    frames = _run_dir(tmp_path, {"cam_a": 3, "cam_b": 0})
    assert frames_by_camera(frames, ["cam_a", "cam_b"]) == {"cam_a": 3, "cam_b": 0}
    assert empty_camera_ids(frames, ["cam_a", "cam_b"]) == ["cam_b"]
    assert camera_empty_message("cam_b") == "render.camera_empty: cam_b"
    assert empty_camera_ids(frames, ["cam_a", "cam_missing"]) == ["cam_missing"]


def test_all_cameras_filled_passes(tmp_path):
    frames = _run_dir(tmp_path, {"cam_a": 3, "cam_b": 3})
    assert empty_camera_ids(frames, ["cam_a", "cam_b"]) == []


def test_catalog_has_render_camera_empty():
    entries = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "core/messages/catalog.yaml").read_text())
    entry = entries["render.camera_empty"]
    assert entry["sentence"] and entry["hint"]


def test_run_refuses_one_empty_camera(tmp_path):
    from webapp.capture import CaptureError
    from webapp.runs import check_cameras_drew_frames

    frames = _run_dir(tmp_path, {"cam_a": 3, "cam_b": 0})
    with pytest.raises(CaptureError) as caught:
        check_cameras_drew_frames(frames, ["cam_a", "cam_b"])
    assert caught.value.constraint == "render.camera_empty"
    assert caught.value.message == "cam_b"
    ok = _run_dir(tmp_path / "ok", {"cam_a": 3, "cam_b": 3})
    check_cameras_drew_frames(ok, ["cam_a", "cam_b"])


def test_cli_refuses_one_empty_camera(tmp_path, capsys):
    from core.scenario.validate import Violation
    from flightsim.capture import _refuse

    frames = _run_dir(tmp_path, {"cam_a": 3, "cam_b": 0})
    empty = empty_camera_ids(frames, ["cam_a", "cam_b"])
    assert _refuse([Violation("render.camera_empty", empty[0])]) == 2
    out = capsys.readouterr().out
    assert "render.camera_empty" in out and "cam_b" in out
