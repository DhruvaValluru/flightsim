"""Run the engine (and every other child process) with no screen and
nothing that can wait for a person -- so an overnight campaign cannot
freeze on a dialog nobody is there to click.

What can stop an unattended run, and what this module does about each:

* **The engine's own windows and prompts.** The render flags already ask
  for a windowless, unattended commandlet (core/render/flags.py
  ``LAUNCHER_FLAGS``: ``-unattended -nopause -nosplash -RenderOffScreen``);
  :data:`HEADLESS_FLAGS` adds ``-NoSound`` (no audio device to open or
  fail on) and ``-NoLoadingScreen``. ``-unattended`` is what makes the
  engine answer its own message boxes and asserts with the default
  instead of waiting.
* **Windows' "has stopped working" / "no disk" error boxes.** A crashing
  process shows these from the OS, not from the engine; they wait
  forever. :func:`popen_kwargs` sets the error mode
  (SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX |
  SEM_NOOPENFILEERRORBOX) in this process before launching, which every
  child inherits, and starts the child with no console window
  (CREATE_NO_WINDOW) in its own process group.
* **A prompt on standard input** (ffmpeg's "overwrite? [y/N]", a script's
  question): every launch gets ``stdin=DEVNULL``, so a read returns end of
  file at once instead of waiting.
* **A hang** -- a frozen engine, a crash reporter that never closes, a
  driver stuck: :func:`run_headless` watches the log and the output
  directory; when neither changes for ``stall_seconds`` (or the whole run
  passes ``timeout_seconds``) it kills the WHOLE process tree -- the
  wrapper script, the engine under it and anything the engine spawned --
  and says so by name (``render.stalled`` / ``render.timeout``), so the
  campaign moves on to the next case instead of waiting until morning.

Overrides: ``FLIGHTSIM_STALL_SECONDS`` and ``FLIGHTSIM_RENDER_TIMEOUT_SECONDS``
(0 disables either).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: Added to every engine launch beside LAUNCHER_FLAGS. The engine ignores
#: a switch it does not know, so these never break an older build.
HEADLESS_FLAGS = ("-NoSound", "-NoLoadingScreen")

#: Nothing written to the log or the output folder for this long = hung.
#: The engine's full stdout logging prints continuously (shader compiles
#: included), so fifteen minutes of silence is not a slow frame.
DEFAULT_STALL_SECONDS = 900.0
#: No whole-run ceiling by default (a long clip is legitimate); set
#: FLIGHTSIM_RENDER_TIMEOUT_SECONDS to have one.
DEFAULT_TIMEOUT_SECONDS: Optional[float] = None

# Windows error-mode bits (SetErrorMode) and process-creation flags.
SEM_FAILCRITICALERRORS = 0x0001
SEM_NOGPFAULTERRORBOX = 0x0002
SEM_NOOPENFILEERRORBOX = 0x8000
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def _env_seconds(name: str, default: Optional[float]) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else None


def stall_seconds() -> Optional[float]:
    return _env_seconds("FLIGHTSIM_STALL_SECONDS", DEFAULT_STALL_SECONDS)


def timeout_seconds() -> Optional[float]:
    return _env_seconds("FLIGHTSIM_RENDER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)


def suppress_error_dialogs() -> bool:
    """Windows: stop the OS from showing crash / critical-error boxes for
    this process and every child it starts (the mode is inherited).
    A no-op elsewhere. Returns whether it applied."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        mode = SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
        kernel32.SetErrorMode(kernel32.GetErrorMode() | mode
                              if hasattr(kernel32, "GetErrorMode") else mode)
        return True
    except Exception:
        return False


def popen_kwargs() -> Dict[str, Any]:
    """Keyword arguments every unattended child launch takes: no stdin,
    no console window, its own process group (so the tree can be killed
    as one), and -- on Windows -- no OS error boxes."""
    suppress_error_dialogs()
    kwargs: Dict[str, Any] = {"stdin": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return kwargs


def kill_tree(process: subprocess.Popen) -> None:
    """Kill the process and everything under it."""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           stdin=subprocess.DEVNULL, timeout=60)
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=30)
    except Exception:
        pass


def _newest_write(paths: Sequence[Path]) -> float:
    """The latest modification time (and size, folded in) under ``paths``."""
    newest = 0.0
    for path in paths:
        path = Path(path)
        if path.is_file():
            stat = path.stat()
            newest = max(newest, stat.st_mtime + stat.st_size * 1e-12)
        elif path.is_dir():
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        stat = os.stat(os.path.join(root, name))
                    except OSError:
                        continue
                    newest = max(newest, stat.st_mtime)
    return newest


@dataclass
class HeadlessResult:
    returncode: Optional[int]
    stalled: bool = False
    timed_out: bool = False
    seconds: float = 0.0

    @property
    def refusal(self) -> Optional[str]:
        """The named reason the run was stopped, or None."""
        if self.stalled:
            return "render.stalled"
        if self.timed_out:
            return "render.timeout"
        return None

    def sentence(self) -> Optional[str]:
        if self.stalled:
            return (f"render.stalled: the engine wrote nothing for {stall_seconds():g} s "
                    f"and was stopped (its whole process tree killed) so the run could "
                    f"go on; its log holds its last words")
        if self.timed_out:
            return (f"render.timeout: the engine ran past {timeout_seconds():g} s and was "
                    f"stopped (its whole process tree killed)")
        return None


def run_headless(command: Sequence[str], log: Path, watch: Sequence[Path] = (),
                 stall: Optional[float] = "default",           # type: ignore[assignment]
                 timeout: Optional[float] = "default",         # type: ignore[assignment]
                 cwd: Optional[Path] = None, poll_seconds: float = 1.0,
                 append: bool = False) -> HeadlessResult:
    """Run ``command`` unattended, its output into ``log``, under a
    watchdog: killed (tree and all) when ``log`` and every path in
    ``watch`` stay unchanged for ``stall`` seconds, or the run passes
    ``timeout`` seconds. ``"default"`` takes the environment's / module's
    value; None disables that guard."""
    stall = stall_seconds() if stall == "default" else stall
    timeout = timeout_seconds() if timeout == "default" else timeout
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    watched: List[Path] = [log, *[Path(p) for p in watch]]
    with log.open("a" if append else "w", encoding="utf-8", errors="replace") as sink:
        process = subprocess.Popen(list(command), stdout=sink, stderr=subprocess.STDOUT,
                                   cwd=str(cwd) if cwd else None, **popen_kwargs())
        last_signal = _newest_write(watched)
        last_activity = time.monotonic()
        while True:
            try:
                code = process.wait(timeout=poll_seconds)
                return HeadlessResult(code, seconds=time.monotonic() - started)
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            current = _newest_write(watched)
            if current != last_signal:
                last_signal, last_activity = current, now
            if stall and now - last_activity > float(stall):
                kill_tree(process)
                sink.write(f"\n[flightsim] render.stalled: nothing written for "
                           f"{stall:g} s; process tree killed\n")
                return HeadlessResult(process.returncode, stalled=True,
                                      seconds=now - started)
            if timeout and now - started > float(timeout):
                kill_tree(process)
                sink.write(f"\n[flightsim] render.timeout: past {timeout:g} s; "
                           f"process tree killed\n")
                return HeadlessResult(process.returncode, timed_out=True,
                                      seconds=now - started)
