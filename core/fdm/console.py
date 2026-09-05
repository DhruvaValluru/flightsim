"""Where JSBSim's own console output goes.

JSBSim prints a three-line startup banner to the process's stdout from
C++ on every ``FGFDMExec`` construction, BEFORE ``set_debug_level`` can
run (measured on the pinned build: ``FGJSBBase.debug_lvl = 0`` gates
later diagnostics only). Python-level redirection (``sys.stdout``,
``contextlib.redirect_stdout``) cannot touch it: the bytes leave through
file descriptor 1. A run that constructs fourteen models therefore
prints fourteen banners into a report a person is trying to read.

This module routes that output at the FILE DESCRIPTOR level, and only
while a caller has asked for it:

* :func:`jsbsim_console` -- the caller (the capture CLI) names a log
  file for the duration of a block; every model constructed inside the
  block appends its console output there, and the sink counts the
  constructions so the caller can say "14 model loads" from a number it
  measured;
* :func:`captured_console` -- used by :class:`core.fdm.fdm.FlightDynamics`
  around the construction itself: fds 1 and 2 are ``dup2``'d onto the
  log for exactly that call and restored afterwards, the Python streams
  flushed on both sides so no line of OUR output is swallowed or
  reordered. With no sink active it is a no-op and the banner goes
  where it always went, so a bare ``run_spec`` in a test or the webapp
  is unchanged.

The output is routed, never dropped: the log is opened for append, and
the sink refuses ``os.devnull`` by name -- a banner nobody can read
back is a banner lost. Every routed construction is preceded in the
log by a one-line stamp, ``# load 3: FlightDynamics(B747) called from
core.scenario.runner.build_fdm``, so fourteen identical banners read
as fourteen named loads (the label is the constructor's, the caller is
the first frame outside this module and the wrapper that asked).

The sink is one slot PER THREAD (a ``threading.local``): the CLI
enters it around its whole run; the page's run thread enters the run's
own sink around its flow and each request handler thread enters the
server's planning sink around its pre-run planning (webapp.runs.
RunManager.planning_console), so a request that plans while a run is
flying neither steals the run's slot nor loses its own. The descriptor
redirection itself is process-wide for the milliseconds a construction
takes: two threads constructing at the same instant could land one
banner in the other's log -- in a log, never on the console.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
import threading
from pathlib import Path
from typing import Iterator, Optional


class JSBSimConsole:
    """The active sink: where the console output goes and how many
    model constructions were routed there."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.loads = 0
        #: One stamp per routed load, in order: what was constructed and
        #: who asked (the same text the log carries).
        self.labels: list = []

    def __repr__(self) -> str:
        return f"JSBSimConsole({str(self.path)!r}, loads={self.loads})"


_SLOT = threading.local()


def active_console() -> Optional[JSBSimConsole]:
    """The sink in force on THIS thread, or None when the banner goes to
    the terminal."""
    return getattr(_SLOT, "active", None)


@contextlib.contextmanager
def jsbsim_console(path) -> Iterator[JSBSimConsole]:
    """Route every JSBSim console line produced inside the block to
    ``path`` (appended). Yields the sink; ``sink.loads`` afterwards is
    the number of model constructions that were routed."""
    path = Path(path)
    if str(path) == os.devnull:
        raise ValueError("the JSBSim console log cannot be os.devnull: "
                         "the output is routed, never dropped")
    previous = active_console()
    sink = JSBSimConsole(path)
    _SLOT.active = sink
    try:
        yield sink
    finally:
        _SLOT.active = previous


def _flush_python_streams() -> None:
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        try:
            stream.flush()
        except (AttributeError, ValueError, OSError):
            pass


def _flush_c_streams() -> None:
    """Flush the C library's stdio buffers so anything JSBSim wrote
    through them lands in the log BEFORE the descriptors are restored
    (``std::cout`` is synchronised with stdio by default)."""
    if os.name == "nt":
        # CDLL(None) is a POSIX idiom (dlopen of the running process);
        # on Windows it raises TypeError. Python and the JSBSim wheel
        # both link the Universal CRT, so its stdout buffer (fully
        # buffered when fd 1 is a pipe, as under CI's capture) is where
        # a banner waits: flush ucrtbase, and the legacy msvcrt as well
        # for a build that links that one. Measured on the Windows CI
        # leg before this: msvcrt alone left the banner's tail in the
        # UCRT buffer, and it reached stdout after the descriptors were
        # restored.
        names = ("ucrtbase", "msvcrt")
    else:
        names = (None,)
    for name in names:
        try:
            libc = ctypes.CDLL(name)
            libc.fflush(None)
        except (OSError, AttributeError, TypeError, ImportError):
            pass


def _caller_words() -> str:
    """``module.function`` of the first frame outside this module and
    the FDM wrappers that construct through it -- the code that asked
    for the model."""
    own = {__name__, "core.fdm.fdm", "contextlib"}
    frame = sys._getframe(1)
    while frame is not None:
        module = frame.f_globals.get("__name__", "?")
        if module not in own:
            return f"{module}.{frame.f_code.co_name}"
        frame = frame.f_back
    return "?"


@contextlib.contextmanager
def captured_console(label: Optional[str] = None
                     ) -> Iterator[Optional[JSBSimConsole]]:
    """Redirect fds 1 and 2 to the active sink for the block; a no-op
    when no sink is active. ``label`` names what is being constructed
    ("FlightDynamics(B747)"); the stamp written to the log before the
    routed output adds who asked."""
    sink = active_console()
    if sink is None:
        yield None
        return
    sink.loads += 1
    words = f"{label or 'FGFDMExec'} called from {_caller_words()}"
    sink.labels.append(words)
    stamp = f"# load {sink.loads}: {words}\n"
    sink.path.parent.mkdir(parents=True, exist_ok=True)
    # Everything already written to the real streams goes out first, so
    # nothing of the caller's ends up in the log.
    _flush_python_streams()
    _flush_c_streams()
    log_fd = os.open(str(sink.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                     0o644)
    os.write(log_fd, stamp.encode("utf-8"))
    saved_out, saved_err = os.dup(1), os.dup(2)
    try:
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        yield sink
    finally:
        _flush_c_streams()
        _flush_python_streams()
        os.dup2(saved_out, 1)
        os.dup2(saved_err, 2)
        for fd in (saved_out, saved_err, log_fd):
            os.close(fd)
