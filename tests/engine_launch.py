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
        # A stub that returns nothing stands for a pass that exited 0.
        return headless.HeadlessResult(getattr(completed, "returncode", 0))

    monkeypatch.setattr(headless, "run_headless", run_headless)
