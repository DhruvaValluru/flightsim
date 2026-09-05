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
back is a banner lost.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import sys
from pathlib import Path
from typing import Iterator, Optional


class JSBSimConsole:
    """The active sink: where the console output goes and how many
    model constructions were routed there."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.loads = 0

    def __repr__(self) -> str:
        return f"JSBSimConsole({str(self.path)!r}, loads={self.loads})"


_ACTIVE: Optional[JSBSimConsole] = None


def active_console() -> Optional[JSBSimConsole]:
    """The sink in force, or None when the banner goes to the terminal."""
    return _ACTIVE


@contextlib.contextmanager
def jsbsim_console(path) -> Iterator[JSBSimConsole]:
    """Route every JSBSim console line produced inside the block to
    ``path`` (appended). Yields the sink; ``sink.loads`` afterwards is
    the number of model constructions that were routed."""
    global _ACTIVE
    path = Path(path)
    if str(path) == os.devnull:
        raise ValueError("the JSBSim console log cannot be os.devnull: "
                         "the output is routed, never dropped")
    previous = _ACTIVE
    sink = JSBSimConsole(path)
    _ACTIVE = sink
    try:
        yield sink
    finally:
        _ACTIVE = previous


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
    try:
        if os.name == "nt":
            # CDLL(None) is a POSIX idiom (dlopen of the running
            # process); on Windows it raises TypeError. The C runtime
            # JSBSim's stdio lives in is msvcrt (or the UCRT that the
            # same name resolves to).
            libc = ctypes.cdll.msvcrt
        else:
            libc = ctypes.CDLL(None)
        libc.fflush(None)
    except (OSError, AttributeError, TypeError, ImportError):
        pass


@contextlib.contextmanager
def captured_console() -> Iterator[Optional[JSBSimConsole]]:
    """Redirect fds 1 and 2 to the active sink for the block; a no-op
    when no sink is active."""
    sink = _ACTIVE
    if sink is None:
        yield None
        return
    sink.loads += 1
    sink.path.parent.mkdir(parents=True, exist_ok=True)
    _flush_python_streams()
    log_fd = os.open(str(sink.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                     0o644)
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
