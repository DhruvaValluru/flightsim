"""Execute a validated scenario spec.

``prompt -> scenario spec -> validate -> run`` (§2.6). This module is the last
arrow. It takes a spec, never a sentence, and refuses to start until validation
has passed.

Determinism
-----------
The output digest is a SHA-256 over the recorded telemetry. Nothing
time-varying, path-dependent or wall-clock-dependent enters it, so two runs from
the same spec produce the same digest -- which is what Gate 1 checks. Every
stochastic subsystem -- Dryden turbulence, the gust front, Allen thermals and
the randomisation block -- draws from a stream seeded from the spec
(``spec.seed`` and the block's own seed; ``core/experiments/seeds.py``
derives per-subsystem streams), never from global or wall-clock state (§7.4).
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
from ..records import AppliedVariable, Readback, records_block
from ..fdm.modes import modes_block
from ..telemetry.limits import monitor_run
from ..telemetry.recorder import Recorder
from ..terrain.geoid import (
    TELEMETRY_COLUMNS as DATUM_COLUMNS, check_model_declared, datum_for_heightfield,
    datum_spec_problems, flat_datum_block, undulation_variable,
)
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

    # Gap P1: the stated day (temperature deviation, sea-level pressure,
    # humidity), written before the trim (stack.prepare) and every step.
    # The standard day adds no provider and records no variable.
    atmosphere = atmosphere_for(spec)
    if atmosphere is not None:
        stack.add(atmosphere)

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


def atmosphere_for(spec: ScenarioSpec):
    """The non-standard atmosphere a spec asks for, or None for ISA."""
    from ..environment.atmosphere import NonStandardAtmosphere

    return NonStandardAtmosphere.from_spec(spec)


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


def configure_from_spec(spec: ScenarioSpec,
                        environment: Optional[EnvironmentStack] = None) -> FlightDynamics:
    """Build and trim an FDM from a spec.

    Shared by :func:`run_spec` and the validator's feasibility probe, so that
    validation exercises exactly the configuration the run will use. Two
    separate setup paths would drift, and a validator that passes a scenario the
    runner then fails to trim is worse than no validator.

    ``environment`` is the stack the run will step with; its pre-trim hook
    (``EnvironmentStack.prepare``) runs between the initial conditions and
    the trim so the trim solver sees the stated day (gap P1: a hot day
    written after the trim would leave the trim in ISA air, measured as a
    different throttle). The feasibility probe passes none and gets a
    stack holding the atmosphere alone.
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
    # The pre-trim hook: the atmosphere (and any later pre-trim provider)
    # is written now, between the initial conditions and the trim.
    if environment is None:
        atmosphere = atmosphere_for(spec)
        environment = EnvironmentStack([atmosphere] if atmosphere is not None else [])
    environment.prepare(fdm)

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
    # Gap P10 (D1): a datum block this build cannot fly (ellipsoidal
    # heights, the ellipsoid physics frame, an unknown model) is refused
    # by name BEFORE the flight, whether or not the validator ran.
    refuse_datum_spec(spec)
    # The scene's datum block and the spec's declaration against it are
    # resolved BEFORE the flight: a bake without its block or a model the
    # bake does not carry refuses by name here, not after the flight.
    scene_datum = scene_datum_for(spec, terrain_ground)

    environment = environment_for(spec)
    fdm = configure_from_spec(spec, environment)
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

    # The digest covers the RECORDED telemetry (the docstring's claim), so
    # it is taken before any observer annotates the columns: the limit
    # flags below are derived from these columns and a change to a
    # placard value must not change the digest of a flight it did not
    # touch.
    output_digest = _digest_telemetry(recorder)
    # Gap P10 (D1): the two datum channels appended AFTER the digest so no
    # digest moves (measured: the recorded columns re-digest identically),
    # with the readback and the record.
    datum_record = datum_run(spec, recorder, scene_datum, output_digest)
    # Limit monitoring (gap P5): the run graded against the airframe's
    # stated envelope, flags written beside the recorded columns so every
    # per-frame consumer (core.capture.manifest.frame_state) carries them.
    # An airframe with no stated limits is recorded unmonitored; a
    # malformed table refuses by name (limits.config).
    limits_block, limits_record = monitor_run(recorder, str(spec.aircraft.value))
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
        "limits": limits_block,
        "datum": scene_datum,
        # Modal analysis (gap M2, row A5): a RESULT about the trim, computed
        # on its own FDM so the recorded flight is untouched (measured:
        # linearising an executive disturbs it; the digest above is unchanged
        # with this block computed). A refusal is recorded by name here,
        # not raised: a result about a run never aborts the run.
        "modes": modes_block(spec),
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
    if limits_record is not None:
        attach_record(manifest, limits_record)
    # Gap P1: one record per stated atmosphere variable, with the pre-trim
    # read-back and null measurement and the per-step read-back.
    for record in environment.applied_variables():
        attach_record(manifest, record)
    # Gap P10 (D1): the datum record, with the appended channels' readback
    # and the measured invariance.
    attach_record(manifest, datum_record)
    return RunResult(spec.digest(), output_digest, recorder, report, manifest,
                     closure)


def refuse_datum_spec(spec: ScenarioSpec) -> None:
    """Refuse by name (``datum.physics_frame_unsupported``,
    ``datum.model_mismatch``) a spec datum block this build cannot fly;
    the first problem is raised (the validator lists them all)."""
    problems = datum_spec_problems(getattr(spec, "datum", None))
    if problems:
        raise problems[0]


def scene_datum_for(spec: ScenarioSpec, terrain_ground) -> Dict[str, Any]:
    """The scene's datum block for a run, and the spec's declaration
    checked against it (gap P10, D1). The block is the bake's recorded
    one when the run flies over a georeferenced heightfield (a bake
    whose sidecar carries none refuses ``datum.sidecar_without_datum``:
    re-bake), the synthesised block over a ridge that is no real place,
    the flat block otherwise. A ``datum.geoid_model`` the spec declares
    must be the bake's (``datum.model_mismatch``)."""
    heightfield = getattr(terrain_ground, "heightfield", None)
    if heightfield is None:
        block = flat_datum_block(float(spec.terrain_elevation.value))
    else:
        block = datum_for_heightfield(heightfield, require_block=True)
    declared = spec.datum.geoid_model.value if hasattr(spec, "datum") else None
    check_model_declared(declared, block)
    return block


def datum_run(spec: ScenarioSpec, recorder: Recorder, block: Dict[str, Any],
              output_digest: str) -> AppliedVariable:
    """The run's datum channels and record (gap P10, blueprint section 5,
    D1). AFTER the output digest was taken, ``undulation_m`` (N at the
    scene origin, constant; 0 where no geoid applies, by the frame's
    definition -- the block keeps null) and ``hae_m`` (altitude_m +
    undulation_m) are annotated as derived columns, the appended column
    is read back, and the recorded columns are re-digested to show the
    digest did not move. Returns the ``scene.geoid_undulation_m`` record.
    """
    declared = spec.datum.geoid_model.value if hasattr(spec, "datum") else None
    n = block.get("undulation_m")
    applied = isinstance(n, (int, float))
    n_column = float(n) if applied else 0.0
    altitude = recorder.series("altitude_m")
    recorder.annotate(DATUM_COLUMNS[0], [n_column] * len(altitude))
    recorder.annotate(DATUM_COLUMNS[1], [float(a) + n_column for a in altitude])
    # Readback of the appended column from the recorder's own store (not
    # JSBSim's: nothing is written to the FDM), graded exact.
    hae = recorder.series(DATUM_COLUMNS[1])
    readback = Readback(
        property=f"telemetry.{DATUM_COLUMNS[1]}[0]", value=float(hae[0]),
        written=float(altitude[0]) + n_column, tolerance=0.0, tolerance_kind="absolute",
        basis="the recorder's annotate stores the list given and refuses to shadow a "
              "recorded channel; read back from recorder.columns after the run "
              "(measured exact on the c172p and A320); this grades the recorder's "
              "store, not JSBSim's property store, to which nothing is written")
    # The invariance: the RECORDED columns (every column not derived)
    # re-digest to the output digest taken before the channels existed.
    recorded = {name: values for name, values in recorder.columns.items()
                if name not in recorder.derived}
    after = _digest_columns(recorded)
    invariance = {
        "quantity": "recorded telemetry columns changed by appending the datum channels",
        "unit": "columns", "with": 0.0 if after == output_digest else 1.0, "without": 0.0,
        "difference": 0.0 if after == output_digest else 1.0, "threshold": 0.0,
        "kind": "bounded", "ok": after == output_digest,
        "output_digest": output_digest, "recorded_digest_after_channels": after,
        "derived_columns": list(recorder.derived),
        "note": ("the channels ride beside the recorded columns as derived ones and are "
                 "not in output_digest; the two-run form (digest identical with and "
                 "without the spec datum block, exported ECEF radial difference = N0) "
                 "is experiments/datum_null_test.py"),
    }
    run = {
        "readback": readback,
        "invariance": invariance,
        "spec_datum": {name: {"value": q.value, "source": str(q.source), "from": q.frm}
                       for name, q in spec.datum.quantities()} if hasattr(spec, "datum") else None,
        "declared_model": declared,
        "applied": applied,
        "samples": len(altitude),
    }
    return undulation_variable(block, run=run)


def attach_record(manifest: Dict[str, Any], record: AppliedVariable) -> None:
    """Add one ``AppliedVariable`` to the manifest's ``applied_variables``
    block (ADVANCEMENTS_CONTRACTS rule 0), creating the block when it is absent. A name
    already in the block is refused: one variable, one record."""
    block = manifest.get("applied_variables")
    if block is None:
        manifest["applied_variables"] = records_block([record])
        return
    names = [r["name"] for r in block["applied_variables"]]
    if record.name in names:
        raise ValueError(f"applied variable {record.name!r} is already recorded")
    block["applied_variables"].append(record.to_dict())


def _digest_telemetry(recorder: Recorder) -> str:
    """SHA-256 over the recorded columns.

    Floats are formatted with ``repr`` so the digest is exact rather than
    rounded: two runs that differ in the last bit must produce different
    digests, or the reproducibility claim is not being tested.
    """
    return _digest_columns(recorder.columns)


def _digest_columns(columns: Dict[str, Any]) -> str:
    """The same digest over a mapping of columns (the runner's own
    re-check that appended channels moved nothing)."""
    h = hashlib.sha256()
    for name in sorted(columns):
        h.update(name.encode())
        for value in columns[name]:
            h.update(repr(value).encode())
    return h.hexdigest()
