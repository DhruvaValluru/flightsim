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

from ..control.autopilot import Autopilot, ClosureReport, ClosureTolerance
from ..environment.stack import EnvironmentStack
from ..environment.turbulence import DrydenTurbulence
from ..environment.wind import SteadyWind
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
    # Ground track, named to match the UE recorder's columns so Gate 5's host
    # comparison can hold position as well as attitude. Position is the channel
    # that catches a wind acting in one host and not the other -- a uniform
    # wind changes no air-relative quantity, only where the aircraft ends up.
    "lat_deg": lambda f: f.props.get("position/lat-geod-deg"),
    "lon_deg": lambda f: f.props.get("position/long-gc-deg"),
}


class UnimplementedConditionError(Exception):
    """The spec requests a condition this build does not implement.

    Deliberately fatal. A spec that asks for a condition and runs without it is
    the previous build's central failure -- conditions advertised and never
    delivered (§1.6, §2.7). Silence here would reproduce it exactly.
    """


def environment_for(spec: ScenarioSpec) -> EnvironmentStack:
    """Build the provider stack a spec asks for.

    Turbulence is a real provider from Phase 3 onward, so it is no longer
    refused -- but an intensity word the provider does not know still is,
    rather than being quietly rounded to something it does know.
    """
    stack = EnvironmentStack()
    from ..environment.surface import surface_class

    surface = surface_class(str(spec.surface.value))
    wind_speed = float(spec.wind_speed.value)
    if surface is not None and wind_speed > 0.0:
        # The surface-layer log profile CARRIES the whole horizontal wind
        # (reference at the layer top): at and above 300 m AGL it is held at
        # exactly the spec's wind, so cruise flight is unchanged; below, the
        # wind honestly decays toward the class's roughness length. Trim
        # still happens in the spec wind (configure_from_spec) -- correct at
        # cruise, a stated approximation below 300 m (BRIEF_PHASE9 9.1).
        from ..environment.wind import LogProfileWind

        stack.add(LogProfileWind(
            u.kt_to_mps(wind_speed), float(spec.wind_direction.value),
            reference_height_m=LogProfileWind.SURFACE_LAYER_TOP_M,
            terrain=surface.roughness))
    elif wind_speed > 0.0:
        stack.add(SteadyWind(u.kt_to_mps(wind_speed),
                             float(spec.wind_direction.value)))
    if surface is not None and surface.thermals is not None:
        # Thermal forcing is buoyancy: it works in calm air too. (w*, zi)
        # and their basis (a stated TM Table 2 anchor or proxy) come from
        # the class table; the ocean's None attaches nothing.
        from ..environment.thermals import AllenThermals

        wstar, zi = surface.thermals
        stack.add(AllenThermals(
            wstar_mps=wstar, zi_m=zi,
            area_north_m=4000.0, area_east_m=4000.0,
            origin_north_m=-2000.0, origin_east_m=-2000.0,
            seed=int(spec.seed.value)))

    event = str(spec.weather_event.value)
    if event in ("thunderstorm", "tornado"):
        # Phase 9.2/9.3: the severe-weather feature placed ahead on the
        # track (45% of the still-air run) exactly as the webapp places its
        # card blocks -- the headless host honours the spec's event rather
        # than flying without it (§1.6). Frame: the provider's own
        # tangent-plane scene coords about the geographic origin.
        import math as _math

        metres_per_degree = 111_320.0
        lat = float(spec.latitude.value)
        lon = float(spec.longitude.value)
        n0 = lat * metres_per_degree
        e0 = (lon * metres_per_degree * _math.cos(_math.radians(lat)))
        seconds = float(spec.duration.value)
        ahead = 0.45 * u.kt_to_mps(float(spec.airspeed.value)) * seconds
        hdg = _math.radians(float(spec.heading.value))
        centre_n = n0 + ahead * _math.cos(hdg)
        centre_e = e0 + ahead * _math.sin(hdg)
        if event == "tornado":
            from ..environment.tornado import R_CORE_M, TornadoVortex

            aim = str(spec.weather_event.detail.get("aim", "abeam"))
            offset = 0.0 if aim == "core" else 2.5 * R_CORE_M
            stack.add(TornadoVortex(
                centre_n + offset * _math.cos(hdg + _math.pi / 2),
                centre_e + offset * _math.sin(hdg + _math.pi / 2)))
        else:
            from ..environment.downburst import Downburst

            stack.add(Downburst(centre_n, centre_e))

    intensity = str(spec.turbulence.value)
    try:
        stack.add(DrydenTurbulence(intensity, seed=int(spec.seed.value)))
    except ValueError as exc:
        raise UnimplementedConditionError(
            f"spec requests {intensity!r} turbulence, which no provider "
            f"implements: {exc}"
        ) from exc
    return stack


@dataclass(frozen=True)
class RunResult:
    spec_digest: str
    output_digest: str
    telemetry: Recorder
    validation: ValidationReport
    manifest: Dict[str, Any]
    closure: Optional[ClosureReport] = None

    def write(self, directory) -> Path:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.telemetry.write_json(directory / "telemetry.json")
        (directory / "manifest.json").write_text(json.dumps(self.manifest, indent=1), encoding="utf-8")
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
    wind_speed = float(spec.wind_speed.value)
    # A spec that commands a state needs the controller; one that only sets an
    # initial condition does not. Building the derived airframe unconditionally
    # would change the model hash of every run for no reason.
    build = (FlightDynamics.with_tecs if bool(spec.hold_state.value)
             else FlightDynamics)
    fdm = build(str(spec.aircraft.value), rate_hz=float(spec.rate.value))
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

    # Steady wind is written before trim so the aircraft is trimmed *in* the
    # conditions it will fly rather than dropped into them afterwards.
    # Turbulence is deliberately NOT active during trim: a stochastic
    # disturbance makes the trim solver chase noise.
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


def run_spec(spec: ScenarioSpec, validate_first: bool = True,
             assert_closure: bool = True, terrain_ground=None) -> RunResult:
    """Run a scenario. Raises rather than running something it cannot deliver.

    ``terrain_ground`` (Phase 7 1.2): a :class:`core.terrain.ground.
    TerrainGround` gives the FDM real elevation under the aircraft every
    step, replacing the spec's flat terrain elevation exactly as the UE
    host's heightfield collision replaces its slab -- both answer from the
    same baked raster.
    """
    report = validate(spec) if validate_first else ValidationReport(spec.digest())
    if validate_first:
        report.raise_if_invalid()

    fdm = configure_from_spec(spec)
    contact = None
    if terrain_ground is not None:
        # The wings feel the terrain, not just the CG (core.terrain.contact):
        # span stations from the FDM's own metrics/bw-ft, checked every step.
        # A station below the surface raises TerrainImpactError -- an impact
        # is a crash, and a crash produces no clean telemetry.
        from ..terrain.contact import AirframeContact, TerrainImpactError

        contact = AirframeContact.from_fdm(terrain_ground, fdm)
        # The trimmed initial state is checked before the first step: a run
        # that BEGINS with a wing inside the mountain refuses immediately
        # rather than integrating one step of ground-reaction chaos first.
        impact = contact.check(fdm.state(), 0.0)
        if impact is not None:
            raise TerrainImpactError(impact)
    environment = environment_for(spec)
    # Turbulence seeds a stochastic process, so it is configured once, after
    # trim and before stepping. Re-writing it inside the loop would re-seed the
    # generator every frame and destroy the correlated noise.
    environment.configure(fdm)

    autopilot = None
    if bool(spec.hold_state.value):
        autopilot = Autopilot(fdm)
        autopilot.engage()

    recorder = Recorder(fdm, interval_s=0.1, extra=SURFACES)
    recorder.sample(force=True)
    recorder.mark("trimmed" if autopilot is None else "trimmed, autopilot engaged")
    if autopilot is None and terrain_ground is None:
        environment.run_for(fdm, float(spec.duration.value), recorder)
    else:
        # Guidance runs at 2 Hz; the control laws run at FDM rate inside JSBSim.
        steps = int(round(float(spec.duration.value) * fdm.rate_hz))
        every = max(1, int(round(0.5 * fdm.rate_hz)))
        for i in range(steps):
            environment.apply(fdm)
            if terrain_ground is not None:
                terrain_ground.apply(fdm)
            fdm.step()
            if contact is not None:
                impact = contact.check(fdm.state(), (i + 1) / fdm.rate_hz)
                if impact is not None:
                    from ..terrain.contact import TerrainImpactError

                    raise TerrainImpactError(impact)
            if autopilot is not None and i % every == 0:
                autopilot.update()
            recorder.sample()

    # The closure assertion (§2.8). A run that did not reach what it was
    # commanded produces no output, rather than a clean recording of a failure.
    closure: Optional[ClosureReport] = None
    if autopilot is not None:
        closure = autopilot.closure(
            recorder.series("altitude_m"),
            recorder.series("tas_kt"),
            recorder.series("heading_deg"),
            recorder.series("climb_rate_mps"),
        )
        if assert_closure:
            closure.raise_if_failed()

    output_digest = _digest_telemetry(recorder)
    manifest = {
        "spec_digest": spec.digest(),
        "spec": spec.to_dict(),
        "fdm": fdm.provenance(),
        "environment": environment.provenance(),
        "physics_ground": ("flat slab (spec terrain elevation)"
                           if terrain_ground is None
                           else terrain_ground.provenance()),
        "airframe_contact": (None if contact is None
                             else contact.provenance()),
        "output_digest": output_digest,
        "samples": len(recorder),
        "validation": {
            "ok": report.ok,
            "warnings": list(report.warnings),
            "derived_speeds": report.speeds.summary() if report.speeds else None,
        },
        "closure": None if closure is None else {
            "ok": closure.ok,
            "checks": [
                {"name": c.name, "commanded": c.commanded, "achieved": c.achieved,
                 "tolerance": c.tolerance, "unit": c.unit, "ok": c.ok}
                for c in closure.checks
            ],
        },
    }
    if fdm.derived is not None:
        manifest["fdm"]["derivation"] = fdm.derived.provenance()
    if autopilot is not None:
        manifest["control"] = {
            "signs": autopilot.signs.as_properties(),
            "gains": autopilot.gains(),
        }
    return RunResult(spec.digest(), output_digest, recorder, report, manifest,
                     closure)


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
