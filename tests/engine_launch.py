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
            try:
                cameras = json.loads(Path(part).read_text()).get("cameras") or []
            except ValueError:
                return
            for camera in cameras:
                folder = frames / str(camera.get("id") or camera.get("camera_id"))
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "frame_0000.png").write_bytes(b"x")
            return


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
