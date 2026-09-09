"""The UE host's own flight, read back as a solve source.

Why this exists
---------------
The capture pipeline used to fly the scenario TWICE. ``flightsim.capture``
flew it headlessly through the ``jsbsim`` Python package and solved every
camera pose over that telemetry; then the Unreal host flew the same card
again through ITS vendored JSBSim and rendered the frames. Two builds
stepping one scenario do not agree: measured on
``examples/cameras_multi.yaml``, **1.38 m worst at t≈1.5 s**. The camera
poses were exact -- the host consumes those verbatim -- but the AIRCRAFT
state in every frame record described the pre-run's flight while the
pixels showed the host's. That is P10, and for labelled training data it
is the defect that matters: the camera is where the label says, and the
thing in front of it is up to a metre and a half from where the label
says.

The fix this module serves is to stop solving over the wrong flight.
The host flies the card FIRST (the telemetry-only commandlet, no
renderer), this module reads that telemetry back, and the poses,
schedules and manifest are all solved over it. The render passes then
re-fly the same card -- and because the host is bit-deterministic
(measured: two passes, byte-identical across 30 columns and 120 samples,
SHA-256 ``4e5a7334…``, worst per-sample difference exactly 0) they fly
the identical flight. Manifest and pixels then describe one flight by
construction rather than to a tolerance.

What licenses it, and what keeps checking
-----------------------------------------
Determinism is the whole licence, so it is not assumed: every run under
this scheme records at least two host flights (the solve pass plus one
render pass per camera), and ``verify_host_determinism`` compares their
digests. If the host ever stops being reproducible -- an engine upgrade,
different hardware, a nondeterministic subsystem -- that check fails and
says the scheme's premise is gone. It is the same discipline the rest of
the phase runs on: a conditional decision has to keep checking its
condition or it becomes an assumption again.

This module reads; it does not fly. Driving the commandlet is
``flightsim.capture``'s job, because that is where the platform refusal
and the wrapper live.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Sequence

#: The channels the pose solver needs. Deliberately the same tuple
#: ``core.capture.poses`` requires: if the host ever stops recording one
#: of them this refuses by name here rather than failing inside the
#: solver with a KeyError.
REQUIRED_CHANNELS = ("t", "lat_deg", "lon_deg", "altitude_m",
                     "roll_deg", "pitch_deg", "heading_deg")

#: The directory a run keeps the host's solve flight in, under the run
#: root. Reserved against camera ids in ``core.capture.validate``.
HOST_FLIGHT_DIR = "host_flight"
HOST_TELEMETRY_NAME = "host_telemetry.json"


class HostFlightError(Exception):
    """The host's flight cannot be used to solve poses. Named, like
    every other refusal in the capture path."""

    constraint = "capture.host_flight"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def render(self) -> str:
        return f"[{self.constraint}] {self.message}"


def host_telemetry_path(run_dir) -> Path:
    """Where the solve pass writes, and where the solver reads."""
    return Path(run_dir) / HOST_FLIGHT_DIR / HOST_TELEMETRY_NAME


def read_host_columns(path) -> Dict[str, List[float]]:
    """The host's recorded telemetry as solver columns.

    Accepts both shapes the recorders write: the UE side nests the
    columns under ``"columns"``, the headless side's ``to_dict`` does
    too, and a bare mapping is taken as the columns themselves.
    """
    path = Path(path)
    if not path.is_file():
        raise HostFlightError(
            f"the host recorded no telemetry at {path}: the scenario "
            f"pass did not run, or it wrote nothing. Poses cannot be "
            f"solved over a flight that does not exist")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HostFlightError(
            f"the host telemetry at {path} could not be read ({exc})"
        ) from exc
    columns = payload.get("columns", payload) if isinstance(payload, dict) \
        else None
    if not isinstance(columns, dict) or not columns:
        raise HostFlightError(
            f"the host telemetry at {path} carries no columns object")

    missing = [name for name in REQUIRED_CHANNELS if name not in columns]
    if missing:
        raise HostFlightError(
            f"the host telemetry at {path} is missing {missing}; the "
            f"pose solver needs {list(REQUIRED_CHANNELS)} and will not "
            f"interpolate channels the host did not record")

    out: Dict[str, List[float]] = {}
    for name in REQUIRED_CHANNELS:
        try:
            out[name] = [float(v) for v in columns[name]]
        except (TypeError, ValueError) as exc:
            raise HostFlightError(
                f"the host telemetry column {name!r} is not numeric "
                f"({exc})") from exc
    length = len(out["t"])
    if length < 2:
        raise HostFlightError(
            f"the host flight has {length} sample(s); a pose track "
            f"needs a flight to solve over, not a single instant")
    ragged = [name for name, values in out.items() if len(values) != length]
    if ragged:
        raise HostFlightError(
            f"the host telemetry columns {ragged} do not have the "
            f"{length} samples t has; refusing to pair states that were "
            f"not recorded together")
    return out


def read_all_host_columns(path) -> Dict[str, List[float]]:
    """EVERY column the host recorded, not just the solver's seven.

    ``read_host_columns`` narrows to what the pose solver indexes, which
    is right for solving and wrong for digesting: a manifest's
    ``output_digest`` is documented as covering "the recorded telemetry
    columns", and the headless pre-run's digest covers all thirty of
    them. Digesting seven here would quietly give one field two
    meanings depending on ``solve_source`` -- and it did, visibly: the
    capture printed fc328800... for a file that verify_host_determinism,
    reading the same bytes, digested as 1c8acba2...
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HostFlightError(
            f"the host telemetry at {path} could not be read ({exc})"
        ) from exc
    columns = payload.get("columns", payload) if isinstance(payload, dict) \
        else None
    if not isinstance(columns, dict) or not columns:
        raise HostFlightError(
            f"the host telemetry at {path} carries no columns object")
    out: Dict[str, List[float]] = {}
    for name, values in columns.items():
        try:
            out[str(name)] = [float(v) for v in values]
        except (TypeError, ValueError):
            continue          # a non-numeric column is not part of the flight
    if not out:
        raise HostFlightError(
            f"the host telemetry at {path} has no numeric columns")
    return out


def digest_columns(columns: Dict[str, Sequence[float]]) -> str:
    """SHA-256 over the columns, EXACTLY as ``run_spec`` digests its own.

    ``repr`` rather than a rounded format, for the reason the runner
    gives: two flights differing in the last bit must produce different
    digests or the reproducibility claim is not being tested. Same
    algorithm on both sides so a manifest's ``output_digest`` means the
    same thing whichever flight it describes.
    """
    h = hashlib.sha256()
    for name in sorted(columns):
        h.update(name.encode())
        for value in columns[name]:
            h.update(repr(float(value)).encode())
    return h.hexdigest()
