"""Engine launches a test can intercept by stubbing ``subprocess.run``.

Every engine pass goes through the unattended launcher,
core.render.headless.run_headless, which starts the child with
``subprocess.Popen`` under its stall watchdog. A test that pins the
render COMMAND stubs ``subprocess.run``; :func:`launch_through_run`
makes the launcher hand its command to ``subprocess.run`` (looked up at
call time, so the test's stub sees it) instead of starting a process.
Without it the stub is never called, Popen tries to start the real
editor, and the pin checks nothing. The launcher's own watchdog is
tested in test_headless.py.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _draw_one_frame_per_camera(command) -> None:
    """The wrapper's stand-in drew pictures: one frame in each card
    camera's directory (the render.camera_empty guard reads them). Only
    the whole-wrapper call (``<card.json> <frames dir>``); a per-camera
    pass (-camera-index=N) is the web path's and writes its own."""
    import json

    parts = [str(p) for p in command]
    if any(p.startswith("-camera-index=") for p in parts):
        return
    for i, part in enumerate(parts[:-1]):
        if part.endswith("card.json") and Path(part).is_file():
            frames = Path(parts[i + 1])
            if _write_minimal_bundle(frames.parent):
                return
            try:
                cameras = json.loads(Path(part).read_text()).get("cameras") or []
            except ValueError:
                return
            for camera in cameras:
                folder = frames / str(camera.get("id") or camera.get("camera_id"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "frame_0000.png").write_bytes(b"x")
            return


def _write_minimal_bundle(run_dir: Path) -> bool:
    """For the manifest the capture wrote before the render: every frame
    it lists, plus the minimal real label bundle ``attach_engine_labels``
    accepts (``render.json`` with a ``labels`` block, a mask and a depth
    at frame size, one alone image per declared object). Returns False
    when there is no such manifest."""
    import json

    import numpy as np
    from PIL import Image

    path = run_dir / "capture_manifest.json"
    if not path.is_file():
        return False
    try:
        frames = json.loads(path.read_text(encoding="utf-8")).get("frames") or []
    except ValueError:
        return False
    records = {}
    for frame in frames:
        folder = run_dir / "frames" / str(frame["camera_id"])
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(str(frame["file"])).name
        stem = name[:-4]
        width, height = int(frame["width_px"]), int(frame["height_px"])
        (folder / name).write_bytes(b"x")
        Image.fromarray(np.zeros((height, width), dtype=np.uint8), mode="L").save(
            folder / f"{stem}_mask.png")
        np.full((height, width), 1000.0, dtype="<f4").tofile(folder / f"{stem}_depth.f32")
        objects = []
        for entry in (frame.get("labels") or {}).get("objects") or []:
            alone = f"{stem}_alone_{int(entry['int_id'])}.png"
            Image.fromarray(np.zeros((height, width), dtype=np.uint8), mode="L").save(
                folder / alone)
            objects.append({"int_id": int(entry["int_id"]), "alone_png": alone})
        records.setdefault(str(frame["camera_id"]), []).append({
            "frame": name,
            "labels": {"mask": f"{stem}_mask.png", "depth_f32": f"{stem}_depth.f32",
                       "objects": objects}})
    for camera, rows in records.items():
        (run_dir / "frames" / camera / "render.json").write_text(
            json.dumps({"frame_records": rows}), encoding="utf-8")
    return True


def launch_through_run(monkeypatch) -> None:
    import core.render.headless as headless

    def run_headless(command, log, watch=(), stall="default", timeout="default",
                     cwd=None, poll_seconds=1.0, append=False):
        log = Path(log)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a" if append else "w", encoding="utf-8") as sink:
            completed = subprocess.run(list(command), stdout=sink,
                                       stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL,
                                       cwd=str(cwd) if cwd else None)
        _draw_one_frame_per_camera(command)
        # A stub that returns nothing stands for a pass that exited 0.
        return headless.HeadlessResult(getattr(completed, "returncode", 0))

    monkeypatch.setattr(headless, "run_headless", run_headless)
