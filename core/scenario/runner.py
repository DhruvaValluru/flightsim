"""Execute a validated scenario spec.

``prompt -> scenario spec -> validate -> run`` (§2.6). This module is the last
arrow. It takes a spec, never a sentence, and refuses to start until validation
has passed.

Determinism
-----------
The output digest is a SHA-256 over the recorded telemetry. Nothing
time-varying, path-dependent or wall-clock-dependent enters it, so two runs from
the same spec produce the same digest -- which is what Gate 1 checks. There is
no RNG anywhere in the current core; when Phase 3 introduces turbulence, its
seed is already a spec field and will feed a per-subsystem generator (§7.4).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from ..fdm import FlightDynamics, TrimMode, mode_for
from ..fdm import units as u
from ..telemetry.recorder import Recorder
from .spec import ScenarioSpec
from .validate import ValidationReport, validate

SURFACES = {
    "elevator_deg": lambda f: math.degrees(f.props.get("fcs/elevator-pos-rad")),
    "aileron_deg": lambda f: math.degrees(f.props.get("fcs/left-aileron-pos-rad")),
    "rudder_deg": lambda f: math.degrees(f.props.get("fcs/rudder-pos-rad")),
    "throttle_cmd": lambda f: f.props.get("fcs/throttle-cmd-norm"),
}


class UnimplementedConditionError(Exception):
    """The spec requests a condition this build does not implement.

    Deliberately fatal. A spec that asks for turbulence and runs without it is
    the previous build's central failure -- conditions advertised and never
    delivered (§1.6, §2.7). Silence here would reproduce it exactly.
    """


@dataclass(frozen=True)
class RunResult:
    spec_digest: str
    output_digest: str
    telemetry: Recorder
    validation: ValidationReport
    manifest: Dict[str, Any]

    def write(self, directory) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.telemetry.write_json(directory / "telemetry.json")
        (directory / "manifest.json").write_text(json.dumps(self.manifest, indent=1))
        return directory


def wind_components_fps(speed_kt: float, from_deg: float):
    """Meteorological direction (the bearing wind blows *from*) to NED, in fps."""
    speed_fps = u.kt_to_fps(speed_kt)
    radians = math.radians(from_deg)
    return (-speed_fps * math.cos(radians), -speed_fps * math.sin(radians))


def configure_from_spec(spec: ScenarioSpec) -> FlightDynamics:
    """Build and trim an FDM from a spec.

    Shared by :func:`run_spec` and the validator's feasibility probe, so that
    validation exercises exactly the configuration the run will use. Two
    separate setup paths would drift, and a validator that passes a scenario the
    runner then fails to trim is worse than no validator.
    """
    turbulence = str(spec.turbulence.value)
    if turbulence not in ("none", "0", "0.0"):
        raise UnimplementedConditionError(
            f"spec requests {turbulence!r} turbulence, which this build does "
            f"not implement (Phase 3). Refusing to run: a spec that asks for "
            f"turbulence and runs in smooth air would report a condition it "
            f"does not have. Set turbulence to 'none' or wait for Phase 3."
        )

    wind_speed = float(spec.wind_speed.value)
    fdm = FlightDynamics(str(spec.aircraft.value), rate_hz=float(spec.rate.value))
    fdm.set_initial_conditions(
        {
            "h-sl-ft": u.m_to_ft(float(spec.altitude.value)),
            "vc-kts": float(spec.airspeed.value),
            "gamma-deg": 0.0,
            "phi-deg": 0.0,
            "psi-true-deg": float(spec.heading.value),
            "beta-deg": 0.0,
            "lat-geod-deg": float(spec.latitude.value),
            "long-gc-deg": float(spec.longitude.value),
            "terrain-elevation-ft": u.m_to_ft(float(spec.terrain_elevation.value)),
        }
    )

    # Environment is written before trim so the aircraft is trimmed *in* the
    # conditions it will fly, not dropped into them afterwards.
    north_fps, east_fps = wind_components_fps(wind_speed, float(spec.wind_direction.value))
    fdm.props.set_many(
        {
            "atmosphere/wind-north-fps": north_fps,
            "atmosphere/wind-east-fps": east_fps,
            "atmosphere/wind-down-fps": 0.0,
            "atmosphere/turb-type": 0.0,
        }
    )

    fdm.start_engines()
    # A crosswind start needs the lateral axes solved as well (§5 Phase 0).
    fdm.trim(mode_for(crosswind=wind_speed > 0.0))
    if bool(spec.mass_held.value):
        fdm.hold_mass(True)
    return fdm


def run_spec(spec: ScenarioSpec, validate_first: bool = True) -> RunResult:
    """Run a scenario. Raises rather than running something it cannot deliver."""
    report = validate(spec) if validate_first else ValidationReport(spec.digest())
    if validate_first:
        report.raise_if_invalid()

    fdm = configure_from_spec(spec)

    recorder = Recorder(fdm, interval_s=0.1, extra=SURFACES)
    recorder.sample(force=True)
    recorder.mark("trimmed")
    recorder.run_for(float(spec.duration.value))

    output_digest = _digest_telemetry(recorder)
    manifest = {
        "spec_digest": spec.digest(),
        "spec": spec.to_dict(),
        "fdm": fdm.provenance(),
        "output_digest": output_digest,
        "samples": len(recorder),
        "validation": {
            "ok": report.ok,
            "warnings": list(report.warnings),
            "derived_speeds": report.speeds.summary() if report.speeds else None,
        },
    }
    return RunResult(spec.digest(), output_digest, recorder, report, manifest)


def _digest_telemetry(recorder: Recorder) -> str:
    """SHA-256 over the recorded columns.

    Floats are formatted with ``repr`` so the digest is exact rather than
    rounded: two runs that differ in the last bit must produce different
    digests, or the reproducibility claim is not being tested.
    """
    h = hashlib.sha256()
    for name in sorted(recorder.columns):
        h.update(name.encode())
        for value in recorder.columns[name]:
            h.update(repr(value).encode())
    return h.hexdigest()
