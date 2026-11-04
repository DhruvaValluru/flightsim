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
        (Path(__file__).resolve().parents[1] / "core/messages/catalog.yaml").read_text(encoding="utf-8"))
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


def test_cli_render_path_refuses_when_one_camera_drew_nothing(tmp_path, capsys,
                                                              monkeypatch):
    """Drives capture --render itself: the stub render writes frames for
    the first card camera only, so the post-render check must refuse."""
    import json

    import assets_pipeline.importer as importer_module
    import core.render.headless as headless
    import core.util.platform as platform_module
    from flightsim.capture import main as capture_main

    def one_camera_only(command, log, **kwargs):
        parts = [str(p) for p in command]
        for i, part in enumerate(parts[:-1]):
            if part.endswith("card.json") and Path(part).is_file():
                cameras = json.loads(Path(part).read_text(encoding="utf-8"))["cameras"]
                first = Path(parts[i + 1]) / str(cameras[0]["camera_id"])
                first.mkdir(parents=True, exist_ok=True)
                (first / "frame_0000.png").write_bytes(b"x")
                break
        return headless.HeadlessResult(0)

    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    monkeypatch.setattr(headless, "run_headless", one_camera_only)
    spec = Path(__file__).resolve().parents[1] / "examples" / "cameras_multi.yaml"
    code = capture_main([str(spec), "--out", str(tmp_path / "o"),
                         "--max-previews", "0", "--render", "--no-host-flight"])
    assert code == 2
    assert "render.camera_empty" in capsys.readouterr().out
