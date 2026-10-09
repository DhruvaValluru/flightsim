"""Validate a scenario before it runs.

§5 Phase 1 requires a physically impossible request to be "rejected at
validation with a clear message naming the violated constraint" -- not to fail
obscurely at trim, and certainly not to run and produce a plausible-looking
video of nonsense.

Two kinds of check, deliberately kept apart:

**Analytic checks** are cheap and answer "is this geometrically and
aerodynamically coherent" -- is the aircraft above the ground, is the commanded
speed above the stall. They use reference speeds *measured from the flight
model* (:mod:`core.scenario.envelope`), not published figures, because the
question is whether the thing being simulated can fly the scenario.

**The feasibility check** actually attempts the trim. It is the definitive
answer and costs a fraction of a second. Stock aero tables run out before the
real airframe would, and no analytic rule predicts where; attempting it is
honest, and predicting it would be a guess dressed as a constraint.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Dict, List, Optional

from ..fdm import FDMError, FlightDynamics, TrimMode
from ..fdm import units as u
from .envelope import ReferenceSpeeds, reference_speeds
from .spec import ScenarioSpec

#: Minimum clearance above terrain for an airborne start.
MIN_CLEARANCE_M = 30.0
#: The longest flight that is a scenario: an hour. A capture is minutes
#: of flight at a stated rate; a stated duration above this (the LLM
#: tier or a hand-written YAML can say 120000 s) would integrate and
#: write frames for hours on a number nobody meant, so it is refused by
#: name before any worker starts rather than run to exhaustion.
MAX_DURATION_S = 3600.0
#: Commanded speed must exceed the measured stall by this factor.
STALL_MARGIN = 1.05


@dataclass(frozen=True)
class Violation:
    """One failed constraint, named."""

    constraint: str
    message: str
    #: A number where the constraint is numeric; the randomisation
    #: range clauses pass a string ("1950-2050", "-90..90") and the
    #: renderer shows it verbatim -- it used to crash with "Unknown
    #: format code 'g' for object of type 'str'", so every refused
    #: draw printed a traceback instead of its name.
    actual: Optional[Any] = None
    limit: Optional[Any] = None
    unit: Optional[str] = None
    #: Extra placeholder values for the catalogue's sentence and hint
    #: (core/messages params_of reads a ``detail`` mapping): the trim
    #: refusal's ``suggestion``, the change that would work.
    detail: Optional[Dict[str, Any]] = None

    @staticmethod
    def _shown(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return str(value)
        return f"{value:g}"

    def render(self) -> str:
        detail = ""
        if self.actual is not None and self.limit is not None:
            unit = f" {self.unit}" if self.unit else ""
            detail = (f" (requested {self._shown(self.actual)}{unit}, "
                      f"limit {self._shown(self.limit)}{unit})")
        return f"[{self.constraint}] {self.message}{detail}"


class ValidationError(Exception):
    """A scenario failed validation and will not be run."""

    def __init__(self, report: "ValidationReport") -> None:
        self.report = report
        super().__init__(report.render())


@dataclass
class ValidationReport:
    spec_digest: str
    violations: List[Violation] = dc_field(default_factory=list)
    warnings: List[str] = dc_field(default_factory=list)
    speeds: Optional[ReferenceSpeeds] = None

    @property
    def ok(self) -> bool:
        return not self.violations

    def render(self) -> str:
        lines = []
        if self.ok:
            lines.append(f"scenario {self.spec_digest[:16]} is valid")
        else:
            lines.append(
                f"scenario {self.spec_digest[:16]} REJECTED -- "
                f"{len(self.violations)} constraint"
                f"{'' if len(self.violations) == 1 else 's'} violated:"
            )
            for v in self.violations:
                lines.append(f"  {v.render()}")
        for w in self.warnings:
            lines.append(f"  warning: {w}")
        if self.speeds:
            lines.append(f"  derived: {self.speeds.summary()}")
        return "\n".join(lines)

    def raise_if_invalid(self) -> "ValidationReport":
        if not self.ok:
            raise ValidationError(self)
        return self


def validate(spec: ScenarioSpec, check_feasibility: bool = True) -> ValidationReport:
    """Check a scenario. Returns a report; never raises on a bad scenario."""
    report = ValidationReport(spec_digest=spec.digest())

    altitude = float(spec.altitude.value)
    terrain = float(spec.terrain_elevation.value)
    airspeed = float(spec.airspeed.value)
    aircraft = str(spec.aircraft.value)

    # -- the aircraft must exist, and nothing may substitute one -------
    try:
        fdm = FlightDynamics(aircraft)
        mass_kg = fdm.state().weight_kg
    except FDMError as exc:
        report.violations.append(
            Violation("aircraft.exists", str(exc).split(".")[0])
        )
        return report   # every remaining check depends on the airframe

    # -- geometry ------------------------------------------------------
    clearance = altitude - terrain
    if clearance < MIN_CLEARANCE_M:
        report.violations.append(
            Violation(
                "altitude.terrain_clearance",
                "commanded altitude is below the terrain it flies over"
                if clearance < 0
                else "commanded altitude leaves no clearance above terrain",
                actual=altitude,
                limit=terrain + MIN_CLEARANCE_M,
                unit="m MSL",
            )
        )

    # -- speeds, measured from the model rather than asserted ----------
    try:
        speeds = reference_speeds(aircraft, mass_kg, max(altitude, 0.0))
        report.speeds = speeds
        if speeds.clipped:
            report.warnings.append(
                "CLmax sits at the edge of the alpha sweep, so the stall was "
                "not bracketed and Vs is a lower bound only"
            )
        if airspeed < speeds.vs_kt * STALL_MARGIN:
            report.violations.append(
                Violation(
                    "airspeed.stall_margin",
                    f"commanded airspeed is below {STALL_MARGIN:g} x the "
                    f"measured stall speed for this model at {mass_kg:,.0f} kg",
                    actual=airspeed,
                    limit=speeds.vs_kt * STALL_MARGIN,
                    unit="kt CAS",
                )
            )
        # An approach flown far above Vref is not an approach.
        if "land" in (spec.name or "").lower() or "approach" in (spec.name or "").lower():
            if airspeed > speeds.vref_kt * 1.30:
                report.violations.append(
                    Violation(
                        "airspeed.approach_speed",
                        "commanded approach speed is far above the measured "
                        "reference speed for this model; this is not a landing",
                        actual=airspeed,
                        limit=speeds.vref_kt * 1.30,
                        unit="kt CAS",
                    )
                )
    except (FDMError, ValueError) as exc:
        report.warnings.append(f"reference speeds unavailable: {exc}")

    # -- run parameters ------------------------------------------------
    if float(spec.duration.value) <= 0:
        report.violations.append(
            Violation("run.duration", "duration must be positive",
                      actual=float(spec.duration.value), limit=0.0, unit="s")
        )
    elif float(spec.duration.value) > MAX_DURATION_S:
        report.violations.append(
            Violation("run.duration",
                      "a duration longer than an hour is a session, not a "
                      "scenario: a capture is minutes of flight, and this "
                      "would integrate and write frames for hours",
                      actual=float(spec.duration.value), limit=MAX_DURATION_S,
                      unit="s")
        )
    if float(spec.rate.value) <= 0:
        report.violations.append(
            Violation("run.rate", "integration rate must be positive",
                      actual=float(spec.rate.value), limit=0.0, unit="Hz")
        )
    if float(spec.wind_speed.value) < 0:
        report.violations.append(
            Violation("environment.wind_speed", "wind speed cannot be negative",
                      actual=float(spec.wind_speed.value), limit=0.0, unit="kt")
        )
    direction = float(spec.wind_direction.value)
    if not 0.0 <= direction <= 360.0:
        report.violations.append(
            Violation("environment.wind_direction",
                      "wind direction must lie in [0, 360] degrees",
                      actual=direction, limit=360.0, unit="deg")
        )
    try:
        from ..environment.surface import surface_class

        surface_class(str(spec.surface.value))
    except ValueError as exc:
        # An unmodelled ground cover refuses by name rather than running
        # as if its roughness and thermals were modelled (§1.6).
        report.violations.append(
            Violation("environment.surface", str(exc))
        )
    event = str(spec.weather_event.value)
    if event not in ("none", "thunderstorm", "tornado"):
        report.violations.append(
            Violation("environment.weather_event",
                      f"unknown severe-weather event {event!r}; modelled: "
                      f"thunderstorm (microburst + gust front + severe "
                      f"turbulence composition), tornado (Rankine vortex)")
        )

    # A time of day that cannot happen here (a sunset in polar day) or
    # cannot be read refuses by name rather than rendering some other sky.
    # "none" (unstated) is the default look and has no instant to check.
    from ..sky.plan import SkyError, resolve_instant

    try:
        if str(spec.time_of_day.value) != "none":
            resolve_instant(str(spec.time_of_day.value),
                            str(spec.weather_date.value),
                            float(spec.latitude.value),
                            float(spec.longitude.value))
    except (SkyError, ValueError) as exc:
        report.violations.append(
            Violation("environment.time_of_day", str(exc)))

    # -- cameras: the scene-free half (Camera Phase 1) -----------------
    # Imported here: core.capture.validate produces THIS module's
    # Violation type, so a module-scope import would be a cycle.
    from ..capture.validate import validate_cameras

    report.violations.extend(validate_cameras(spec))
    report.violations.extend(validate_randomization(spec))
    report.violations.extend(validate_prompt_words(spec))
    report.violations.extend(validate_blocks(spec))
    report.violations.extend(validate_policy(spec))
    report.violations.extend(validate_registry(spec))
    report.violations.extend(validate_atmosphere(spec))
    report.violations.extend(validate_datum(spec))
    report.violations.extend(validate_turbulence_model(spec))
    report.violations.extend(validate_wind_profile(spec))
    report.violations.extend(validate_failures(spec))
    report.violations.extend(validate_loading(spec))
    report.violations.extend(validate_dis(spec))
    report.violations.extend(validate_icing(spec))
    report.violations.extend(validate_rain(spec))
    report.violations.extend(validate_wake(spec))
    report.violations.extend(validate_instruments(spec))
    report.violations.extend(validate_record(spec))
    # W2: the cached footprint set and the runway block, refused by name.
    report.violations.extend(validate_world(spec))
    # W3: the night sky and the rain rate, refused by name.
    report.violations.extend(validate_world_look(spec))
    # The render lighting block, refused by name.
    report.violations.extend(validate_lighting(spec))
    # The route block, refused by name (core/control/route.py's list).
    report.violations.extend(validate_route(spec))

    # -- the definitive check: can this actually be trimmed? -----------
    # Skipped when geometry is already impossible, since trimming below ground
    # would fail for a reason that has nothing to do with the aero tables.
    if check_feasibility and report.ok:
        # Imported here rather than at module scope: the runner imports this
        # module for validation, and this is the only edge back the other way.
        from .runner import configure_from_spec

        try:
            configure_from_spec(spec)
        except FDMError as exc:
            suggestion = trim_suggestion(spec)
            # The catalogue's hint reads {suggestion} (core/messages/
            # catalog.yaml): the page says the change, not just "change".
            report.violations.append(Violation(
                "envelope.trim_feasible",
                f"this model cannot be trimmed at the commanded condition; "
                f"its aero tables do not reach here. Underlying error: "
                f"{type(exc).__name__}"
                + (f". {suggestion}" if suggestion else ""),
                detail={"suggestion": suggestion} if suggestion else None,
            ))

    return report


#: The nearby conditions the trim search tries when the commanded one
#: cannot be trimmed: speed steps (kt) at the commanded altitude, then
#: altitude steps (m) at the commanded speed -- one change at a time, the
#: smallest first, so the suggestion is the smallest change that works.
#: Measured: one trim attempt is ~0.05 s, so the search is cheap.
TRIM_SEARCH_SPEED_STEPS_KT = (10.0, -10.0, 20.0, -20.0, 30.0, -30.0, 50.0, -50.0)
TRIM_SEARCH_ALTITUDE_STEPS_M = (-500.0, -1000.0, -2000.0, -3000.0, -5000.0, -7000.0, 500.0, 1000.0)
#: Altitudes tried after the steps, as fractions of the commanded one and
#: a low fallback: a c172 asked for 9000 m is out of its ceiling by far
#: more than any step (measured: no step trimmed; 3000 m does).
TRIM_SEARCH_ALTITUDE_FRACTIONS = (0.5, 0.33)
TRIM_SEARCH_ALTITUDE_FALLBACK_M = 1000.0


def trim_suggestion(spec, keep: Optional[str] = None) -> str:
    """The smallest single change of speed or altitude at which this
    airframe trims, in words ("change the altitude to 4000 m (it trims
    there at 100 kt)"), or "" when none of the nearby conditions trims
    either. The owner's ask (2026-10-09): a refusal should say what small
    change makes it work. The airframe's documented cruise is tried first,
    then the speed steps, then the altitudes; ``keep`` ("altitude" or
    "airspeed") skips changes to that field (the repair layer's kept field)."""
    import copy

    from .runner import configure_from_spec
    from ..nl.compiler import CRUISE_DEFAULT_KT

    speed = float(spec.airspeed.value)
    altitude = float(spec.altitude.value)
    model = str(spec.aircraft.value)

    def trims(new_speed, new_altitude) -> bool:
        trial = copy.deepcopy(spec)
        # set(), not plan(): a stated value may be moved on a trial copy
        # that is thrown away; nothing on the real spec changes.
        if new_speed != speed:
            trial.set("airspeed", new_speed, frm="trim search (a trial copy)")
        if new_altitude != altitude:
            trial.set("altitude", new_altitude, frm="trim search (a trial copy)")
        try:
            configure_from_spec(trial)
            return True
        except Exception:   # any failure to trim is a no, never a crash of the search
            return False

    speeds = []
    cruise = CRUISE_DEFAULT_KT.get(model)
    if cruise is not None and cruise != speed:
        speeds.append(cruise)
    speeds += [speed + step for step in TRIM_SEARCH_SPEED_STEPS_KT if speed + step > 0.0]
    if keep == "airspeed":
        speeds = []
    for candidate in speeds:
        if trims(candidate, altitude):
            return f"change the speed to {candidate:g} kt (it trims there at {altitude:g} m)"
    if keep == "altitude":
        return ""
    altitudes = [altitude + step for step in TRIM_SEARCH_ALTITUDE_STEPS_M]
    altitudes += [altitude * f for f in TRIM_SEARCH_ALTITUDE_FRACTIONS] + [TRIM_SEARCH_ALTITUDE_FALLBACK_M]
    tried = set()
    for candidate in altitudes:
        candidate = round(candidate / 100.0) * 100.0
        if candidate <= 0.0 or candidate == altitude or candidate in tried:
            continue
        tried.add(candidate)
        if trims(speed, candidate):
            return f"change the altitude to {candidate:g} m (it trims there at {speed:g} kt)"
    return ""


def validate_registry(spec) -> List[Violation]:
    """R1: every spec field under a section the variable registry claims
    (core/registry.py; today ``atmosphere``) must be a registered variable,
    so "every introduced variable returns the record" is checked at
    validation rather than discovered in a manifest. A spec that states
    no claimed section (every spec-8 field) yields nothing."""
    from ..registry import unregistered_fields

    return [Violation("record.unregistered",
                      f"{path} is a spec field no registered variable returns the "
                      f"record for; register it in core/registry.py or drop it")
            for path in unregistered_fields(spec.to_dict())]


def validate_prompt_words(spec) -> List[Violation]:
    """Words in the spec's prompt that the spec does not honour, refused by
    name (core/nl/unsupported.py): a thing the simulator does not model
    (``prompt.unsupported``), or a condition it carries that the compiled
    spec left at its default (``prompt.not_set``). A variation phrase the
    vocabulary cannot express is refused here too
    (``randomization.vocabulary``), at review time rather than only when
    the sampler runs. A spec with no prompt (a YAML file) has nothing to
    check."""
    from ..nl.unsupported import unsupported_words

    # ``actual`` carries the prompt's own word, so the plain sentence can
    # say WHICH thing ("the request asks for “birds”"), not only that one.
    out = [Violation(constraint, sentence, actual=word)
           for constraint, sentence, word in unsupported_words(spec.prompt, spec)]
    policy = spec.randomization_policy
    unmapped = policy.detail.get("unmapped") if policy is not None else None
    if unmapped:
        out.append(Violation(
            "randomization.vocabulary",
            "the prompt asks for a variation the vocabulary cannot express: "
            + "; ".join(f'"{s}"' for s in unmapped)
            + " -- the documented phrases are varied weather, different times "
              "of day, dawn and dusk only, varied lighting, different seasons, "
              "across the <range>, mixed traffic, random viewpoints"))
    return out


def validate_randomization(spec) -> List[Violation]:
    """The randomisation block's own constraints, refused by name.

    Ranges must be ranges, the year must be inside the cited solar
    algorithm's stated accuracy, a fog density must be positive (the
    log-uniform draw needs it), a jitter cannot be negative, and the
    switch must be a boolean -- a string "false" is true in Python and
    would randomise a spec whose owner said not to.
    """
    from .randomization import YEAR_MAX, YEAR_MIN

    block = spec.randomization
    out: List[Violation] = []

    def num(name):
        try:
            return float(getattr(block, name).value)
        except (TypeError, ValueError):
            out.append(Violation(f"randomization.{name}",
                                 f"randomization.{name} must be a number, "
                                 f"not {getattr(block, name).value!r}"))
            return None

    if not isinstance(block.enabled.value, bool):
        out.append(Violation(
            "randomization.enabled",
            f"randomization.enabled must be true or false, not "
            f"{block.enabled.value!r} (a string 'false' would be truthy)",
            actual=block.enabled.value))
    year = num("year")
    if year is not None and not (YEAR_MIN <= year <= YEAR_MAX):
        out.append(Violation(
            "randomization.year",
            f"year {year:g} is outside {YEAR_MIN}-{YEAR_MAX}, the range the "
            f"cited solar-position algorithm is stated accurate for",
            actual=year, limit=f"{YEAR_MIN}-{YEAR_MAX}", unit="year"))
    for lo_name, hi_name, lo_lim, hi_lim, unit in (
            ("day_of_year_min", "day_of_year_max", 1, 366, "day"),
            ("hour_utc_min", "hour_utc_max", 0.0, 24.0, "h"),
            ("fog_density_min", "fog_density_max", None, None, "1/m")):
        lo, hi = num(lo_name), num(hi_name)
        if lo is None or hi is None:
            continue
        if lo_lim is not None and not (lo_lim <= lo <= hi_lim and lo_lim <= hi <= hi_lim):
            out.append(Violation(
                f"randomization.{lo_name}",
                f"{lo_name}/{hi_name} must lie in {lo_lim}-{hi_lim} {unit}",
                actual=f"{lo:g}-{hi:g}", limit=f"{lo_lim}-{hi_lim}", unit=unit))
        if lo_lim is None and lo <= 0.0:
            out.append(Violation(
                f"randomization.{lo_name}",
                f"{lo_name} must be positive (the fog draw is log-uniform)",
                actual=lo, limit=0.0, unit=unit))
        if lo > hi:
            out.append(Violation(
                f"randomization.{hi_name}",
                f"{hi_name} ({hi:g}) is below {lo_name} ({lo:g}): not a range",
                actual=hi, limit=lo, unit=unit))
    floor = num("sun_elevation_min_deg")
    if floor is not None and not (-90.0 <= floor <= 90.0):
        out.append(Violation("randomization.sun_elevation_min_deg",
                             "sun_elevation_min_deg must lie in -90..90 deg",
                             actual=floor, limit="-90..90", unit="deg"))
    for name, hi in (("camera_jitter_m", None), ("camera_jitter_deg", 180.0),
                     ("camera_focal_jitter", 0.9)):
        value = num(name)
        if value is None:
            continue
        if value < 0.0 or (hi is not None and value > hi):
            out.append(Violation(
                f"randomization.{name}",
                f"{name} must be in 0..{hi if hi is not None else 'inf'}",
                actual=value, limit=hi, unit=getattr(block, name).unit))
    return out


# -- spec 8 blocks: scene, taxonomy, traffic --------------------------------

def validate_blocks(spec) -> List[Violation]:
    """The spec-8 blocks' own constraints, refused by name.

    ``scene.terrain_source`` must be one of the documented sources and
    ``scene.terrain`` a bake stem or absent (whether the stem IS baked
    is the scene selection's question -- the CLI may supply ``--terrain``
    -- and is refused there, not here); ``taxonomy.classes`` must be a
    non-empty list of distinct class names; each ``traffic`` entry must
    name a configured airframe, one of the three tracks, a positive
    range, and there may be at most two. Nothing here composes, flies
    or renders anything: the fields' meaning is packages A/B's.
    """
    from .blocks import (
        MAX_TRAFFIC, PLACED_TRACKS, TERRAIN_SOURCES, TRAFFIC_TRACKS,
        configured_airframes,
        labelled_airframes,
    )

    out: List[Violation] = []

    source = spec.scene.terrain_source.value
    if source not in TERRAIN_SOURCES:
        out.append(Violation(
            "scene.terrain_source",
            f"scene.terrain_source must be one of {list(TERRAIN_SOURCES)}, "
            f"not {source!r}"))
    stem = spec.scene.terrain.value
    if stem is not None and (not isinstance(stem, str) or not stem.strip()):
        out.append(Violation(
            "scene.terrain",
            f"scene.terrain must be a bake stem (<stem>.r16 + .json) or "
            f"absent, not {stem!r}"))
    # S1: a stated sun is a positive number of lux no brighter than the
    # extraterrestrial one (core/scenario/solar.py, the same sentence the
    # manifest and the render flags refuse with).
    from .solar import sun_lux_problem

    sun_problem = sun_lux_problem(getattr(spec.scene, "sun_lux", None) and spec.scene.sun_lux.value)
    if sun_problem:
        out.append(Violation("sensing.sun_lux", sun_problem,
                             actual=spec.scene.sun_lux.value, limit=133100.0, unit="lx"))

    classes = spec.taxonomy.classes.value
    if (not isinstance(classes, list) or not classes
            or not all(isinstance(c, str) and c.strip() for c in classes)):
        out.append(Violation(
            "taxonomy.classes",
            f"taxonomy.classes must be a non-empty list of class names "
            f"(class_id = position + 1; 0 is sky/none), not {classes!r}"))
    elif len(set(classes)) != len(classes):
        duplicates = sorted({c for c in classes if classes.count(c) > 1})
        out.append(Violation(
            "taxonomy.classes",
            f"taxonomy.classes repeats {duplicates}; a class id must name "
            f"one class"))

    if len(spec.traffic) > MAX_TRAFFIC:
        out.append(Violation(
            "traffic.count",
            f"at most {MAX_TRAFFIC} traffic aircraft are modelled (the "
            f"occlusion geometries are specified for two)",
            actual=len(spec.traffic), limit=MAX_TRAFFIC, unit="aircraft"))
    airframes = configured_airframes()
    labelled = labelled_airframes() if spec.traffic else []
    for index, entry in enumerate(spec.traffic):
        who = f"traffic[{index}]"
        aircraft = str(entry.aircraft.value)
        if aircraft not in airframes:
            out.append(Violation(
                "traffic.aircraft",
                f"{who}: {aircraft!r} is not a configured airframe (one "
                f"of {airframes}; its mesh must be importable like the "
                f"primary's)"))
        elif aircraft not in labelled:
            out.append(Violation(
                "traffic.aircraft",
                f"{who}: {aircraft!r} has no 'labels' block in its aircraft "
                f"config, so its frames cannot be labelled (one of "
                f"{labelled})"))
        track = str(entry.track.value)
        if track not in TRAFFIC_TRACKS and track not in PLACED_TRACKS:
            out.append(Violation(
                "traffic.track",
                f"{who}: track must be one of "
                f"{list(TRAFFIC_TRACKS) + list(PLACED_TRACKS)}, not "
                f"{track!r}"))
        if track in PLACED_TRACKS:
            offsets = {}
            for name in entry.PLACEMENT_FIELDS:
                try:
                    offsets[name] = float(getattr(entry, name).value)
                except (TypeError, ValueError):
                    out.append(Violation(
                        "traffic.placement",
                        f"{who}: {name} must be a number"))
            if len(offsets) == len(entry.PLACEMENT_FIELDS):
                gap = (offsets["ahead_m"] ** 2 + offsets["right_m"] ** 2
                       + offsets["up_m"] ** 2) ** 0.5
                if gap < 1.0:
                    out.append(Violation(
                        "traffic.placement",
                        f"{who}: the second aircraft is placed {gap:.2f} m "
                        f"from the primary; two aircraft cannot occupy one "
                        f"point (state at least 1 m of ahead / right / up)",
                        actual=gap, limit=1.0, unit="m"))
            # a stated offset is the range: the unused default range_m is
            # not judged for a placed track
            continue
        try:
            range_m = float(entry.range_m.value)
        except (TypeError, ValueError):
            range_m = None
        if range_m is None or not range_m > 0.0:
            out.append(Violation(
                "traffic.range_m",
                f"{who}: range_m must be a positive distance",
                actual=entry.range_m.value, limit=0.0, unit="m"))
    return out


# -- the atmosphere block (gap P1) -------------------------------------------

def validate_datum(spec) -> List[Violation]:
    """D1: the datum block's refusals by name (core/terrain/geoid.py
    datum_spec_problems, the one list for the validator and the runner):
    ``datum.physics_frame_unsupported`` for ellipsoidal heights or the
    ellipsoid physics frame, ``datum.model_mismatch`` for a model this
    build does not carry. The match against the bake's model is the
    runner's, where the spec meets the bake."""
    from ..terrain.geoid import datum_spec_problems

    return [Violation(problem.constraint, problem.message)
            for problem in datum_spec_problems(getattr(spec, "datum", None))]


def validate_dis(spec) -> List[Violation]:
    """D2: the dis block's refusals by name (core/interop/dis_stream.py
    dis_spec_problems, the one list for the validator and the exporter):
    ``interop.dis.entity_id`` for a site, application or entity outside
    0..65535, ``dis.force_id`` outside 0..255, ``dis.marking_too_long``
    over 11 ASCII characters, ``dis.timestamp_mode`` for a word other
    than relative or absolute. The epoch an absolute mode needs is the
    exporter's option and is refused there (``dis.timestamp_epoch_missing``)."""
    from ..interop.dis_stream import dis_spec_problems

    block = getattr(spec, "dis", None)
    values = ({name: q.value for name, q in block.quantities()}
              if block is not None and not block.is_default() else None)
    return [Violation(problem.constraint, problem.message)
            for problem in dis_spec_problems(values)]


def validate_atmosphere(spec) -> List[Violation]:
    """The atmosphere block's own constraints, refused by name.

    The ``day`` word must be in the vocabulary (a MIL-HDBK-310 named
    profile is refused ``atmosphere.profile`` until transcribed); every
    numeric field must be a number or absent; the temperature deviation
    lies in -60..+45 degC (``atmosphere.temperature_deviation``), the
    sea-level pressure in 870..1085 hPa (``atmosphere.sea_level_pressure``);
    dew point and relative humidity are not both stated
    (``atmosphere.humidity_conflict``); the humidity lies in 0..100 %,
    the dew point in its range and at or below the modelled air
    temperature at the scene's initial altitude and under the model's
    vapour cap there (``atmosphere.dew_point`` -- the two values JSBSim
    would otherwise cap silently). The checks are the provider's own
    (core.environment.atmosphere.problems), so what validation refuses
    and what the run refuses are one list.
    """
    from ..environment.atmosphere import day_problem, problems

    block = spec.atmosphere
    out: List[Violation] = []
    refused = day_problem(block.day.value)
    if refused is not None:
        out.append(Violation(refused.constraint, refused.message,
                             actual=refused.actual))
    resolved = block.resolved()
    numbers = {}
    names = {"temperature_deviation_c": "atmosphere.temperature_deviation",
             "sea_level_pressure_hpa": "atmosphere.sea_level_pressure",
             "dew_point_c": "atmosphere.dew_point",
             "relative_humidity_pct": "atmosphere.dew_point"}
    for field in block.NUMERIC_FIELDS:
        value = resolved[field].value
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            if value is not None:
                out.append(Violation(
                    names[field],
                    f"atmosphere.{field} must be a number or absent, not "
                    f"{value!r}", actual=value))
            numbers[field] = None
        else:
            numbers[field] = float(value)
    if any(v.constraint != "atmosphere.profile" for v in out):
        return out
    for refused in problems(numbers["temperature_deviation_c"],
                            numbers["sea_level_pressure_hpa"],
                            numbers["dew_point_c"],
                            numbers["relative_humidity_pct"],
                            float(spec.altitude.value)):
        out.append(Violation(refused.constraint, refused.message,
                             actual=refused.actual, limit=refused.limit,
                             unit=refused.unit))
    return out


# -- the turbulence model and the wind profile (P6) ---------------------------

def validate_turbulence_model(spec) -> List[Violation]:
    """The ``turbulence_model`` block's own constraints, refused by name
    (``turbulence.model``): the model is ``dryden`` or ``von_karman``; the
    intensity, when stated, is a turbulence word the providers know or a
    W20 in knots at or above zero (the Dryden path takes the words only:
    a number needs the von Karman model); the seed, when stated, is an
    integer inside the range JSBSim can represent (the Dryden seed) or
    non-negative (the von Karman stream)."""
    from ..environment.turbulence import MAX_JSBSIM_SEED, W20_KT
    from .blocks import TURBULENCE_MODELS

    block = spec.turbulence_model
    out: List[Violation] = []
    model = block.model.value
    if model not in TURBULENCE_MODELS:
        out.append(Violation(
            "turbulence.model",
            f"turbulence_model.model must be one of {list(TURBULENCE_MODELS)}, not {model!r}",
            actual=model))
        return out
    intensity = block.intensity.value
    if intensity is not None:
        if isinstance(intensity, str):
            if intensity not in W20_KT:
                out.append(Violation(
                    "turbulence.model",
                    f"turbulence_model.intensity {intensity!r} is not a turbulence word "
                    f"({sorted(W20_KT)}) or a W20 in knots", actual=intensity))
        elif isinstance(intensity, bool) or not isinstance(intensity, (int, float)):
            out.append(Violation(
                "turbulence.model",
                f"turbulence_model.intensity must be a word or a W20 in knots, not "
                f"{intensity!r}", actual=intensity))
        elif float(intensity) < 0.0:
            out.append(Violation(
                "turbulence.model", "turbulence_model.intensity (W20) cannot be negative",
                actual=float(intensity), limit=0.0, unit="kt"))
        elif model == "dryden":
            out.append(Violation(
                "turbulence.model",
                f"the dryden model takes an intensity word ({sorted(W20_KT)}); a W20 of "
                f"{intensity:g} kt needs the von_karman model", actual=intensity, unit="kt"))
    seed = block.seed.value
    if seed is not None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            out.append(Violation(
                "turbulence.model", f"turbulence_model.seed must be an integer, not {seed!r}",
                actual=seed))
        elif not 0 <= seed < MAX_JSBSIM_SEED:
            out.append(Violation(
                "turbulence.model",
                f"turbulence_model.seed must lie in 0..{MAX_JSBSIM_SEED - 1} (the range "
                f"JSBSim represents; a larger seed saturates)",
                actual=seed, limit=MAX_JSBSIM_SEED - 1, unit="seed"))
    return out


def validate_wind_profile(spec) -> List[Violation]:
    """The ``wind_profile`` block's own constraints, refused by name: the
    kind is one of the four (``wind_profile.kind``); ``layered`` needs
    layers of at least two ascending non-negative
    [altitude_m, speed_kt, direction_deg] triples (``wind_profile.layers``,
    the provider's own list); ``milspec`` needs z0 of 0.15 or 2.0 ft and
    a scene starting 3..1000 ft above ground (``wind_profile.kind``);
    ``nwp`` needs a cached fixture whose digest matches
    (``weather.fixture_missing`` / ``weather.fixture_digest``); a field
    another kind reads, stated beside a non-uniform kind, is refused under
    ``wind_profile.kind`` (one profile at a time); under the uniform kind
    a stated companion field is recorded by the runner as unread, so
    nothing is silently ignored and the null pair of ``kind`` can run."""
    from ..environment.shear import (
        ShearError, layer_problems, load_fixture, milspec_problems,
    )
    from ..fdm import units as u
    from .blocks import WIND_PROFILE_KINDS

    block = spec.wind_profile
    out: List[Violation] = []
    kind = block.kind.value
    if kind not in WIND_PROFILE_KINDS:
        out.append(Violation(
            "wind_profile.kind",
            f"wind_profile.kind must be one of {list(WIND_PROFILE_KINDS)}, not {kind!r}",
            actual=kind))
        return out
    stated = {name: getattr(block, name).value for name in ("layers", "roughness_ft", "fixture")}
    reads = {"uniform": (), "layered": ("layers",), "milspec": ("roughness_ft",),
             "nwp": ("fixture",)}[kind]
    for name, value in stated.items():
        if value is not None and name not in reads and kind != "uniform":
            # Two profiles' fields together (layers with an nwp fixture,
            # a fixture with the milspec z0): a conflict, refused. Under the
            # uniform kind a stated companion field is NOT applied and the
            # runner records it as unread (the null pair of ``kind`` is
            # exactly that spec), never silently.
            out.append(Violation(
                "wind_profile.kind",
                f"wind_profile.{name} is stated but the {kind!r} profile does not read it "
                f"(another kind's field); state one profile", actual=name))
    if kind == "layered":
        if stated["layers"] is None:
            out.append(Violation("wind_profile.layers",
                                 "a layered profile states its layers "
                                 "([altitude_m, speed_kt, direction_deg], at least two)"))
        for problem in layer_problems(stated["layers"]) if stated["layers"] is not None else ():
            out.append(Violation(problem.constraint, problem.message, actual=problem.actual,
                                 limit=problem.limit, unit=problem.unit))
    elif kind == "milspec":
        z0 = stated["roughness_ft"]
        if z0 is not None and (isinstance(z0, bool) or not isinstance(z0, (int, float))):
            out.append(Violation("wind_profile.kind",
                                 f"wind_profile.roughness_ft must be a number, not {z0!r}",
                                 actual=z0))
            z0 = None
        agl_ft = u.m_to_ft(float(spec.altitude.value) - float(spec.terrain_elevation.value))
        for problem in milspec_problems(z0, agl_ft):
            out.append(Violation(problem.constraint, problem.message, actual=problem.actual,
                                 limit=problem.limit, unit=problem.unit))
    elif kind == "nwp":
        name = stated["fixture"]
        try:
            load_fixture(name)
        except ShearError as problem:
            out.append(Violation(problem.constraint, problem.message))
    return out


# -- the loading block (P4) ------------------------------------------------------

def validate_loading(spec) -> List[Violation]:
    """The ``loading`` block's refusals by name (core/scenario/loading.py
    ``LoadingPlan.problems``, the one list for the validator and the
    provider): ``loading.config`` (a stated block on an airframe without
    one, or a malformed block), ``loading.station_unknown``,
    ``loading.station_mass``, ``loading.fuel_range``, ``loading.max_weight``,
    ``loading.cg_envelope`` (where the airframe's arm comparison admits the
    check; elsewhere the check is recorded as not made, never refused --
    the user asked for a loading, not for an envelope). The default block
    yields nothing."""
    from .loading import LoadingError, LoadingPlan

    try:
        plan = LoadingPlan.from_spec(spec)
    except LoadingError as exc:
        return [Violation(exc.constraint, exc.message, actual=exc.actual, limit=exc.limit,
                          unit=exc.unit)]
    if plan is None:
        return []
    return [Violation(problem.constraint, problem.message, actual=problem.actual,
                      limit=problem.limit, unit=problem.unit)
            for problem in plan.problems()]


# -- spec 8 randomization.policy: shape only ---------------------------------

#: The documented distribution forms (contracts §5.2) and the shape of
#: each leaf's argument. The MEANING of a leaf -- which typed field it
#: samples, and the sampling itself -- is package F's and is NOT
#: implemented here; only the shape is refused by name.
POLICY_DISTRIBUTIONS = ("choice", "uniform", "loguniform", "normal",
                        "lognormal", "beta", "weibull", "poisson",
                        "uniform_dates")
#: Modifiers a distribution leaf may carry beside its distribution key.
POLICY_MODIFIERS = ("weights", "clip", "gated_by", "max")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _policy_leaf_problems(path: str, leaf) -> List[str]:
    """Why one distribution leaf is not of a documented form (empty
    when it is)."""
    kinds = [k for k in POLICY_DISTRIBUTIONS if k in leaf]
    if len(kinds) != 1:
        return [f"{path}: a leaf names exactly one distribution of "
                f"{list(POLICY_DISTRIBUTIONS)}, not {kinds or 'none'}"]
    kind = kinds[0]
    arg = leaf[kind]
    problems: List[str] = []
    unknown = set(leaf) - {kind} - set(POLICY_MODIFIERS)
    if unknown:
        problems.append(f"{path}: unknown keys {sorted(unknown)}")
    if kind == "choice":
        if not isinstance(arg, list) or not arg:
            problems.append(f"{path}: choice needs a non-empty list")
        weights = leaf.get("weights")
        if weights is not None and (
                not isinstance(weights, list) or not isinstance(arg, list)
                or len(weights) != len(arg)
                or not all(_is_number(w) and w >= 0 for w in weights)
                or not any(w > 0 for w in weights)):
            problems.append(f"{path}: weights must be non-negative numbers, "
                            f"one per choice, not all zero")
    elif kind in ("uniform", "loguniform", "beta"):
        ok = (isinstance(arg, list) and len(arg) == 2
              and all(_is_number(v) for v in arg))
        if ok and kind == "uniform" and not arg[0] <= arg[1]:
            ok = False
        if ok and kind == "loguniform" and not 0 < arg[0] <= arg[1]:
            ok = False
        if ok and kind == "beta" and not (arg[0] > 0 and arg[1] > 0):
            ok = False
        if not ok:
            problems.append(f"{path}: {kind} needs [lo, hi] numbers"
                            + (" with lo > 0" if kind == "loguniform" else
                               " (both > 0)" if kind == "beta" else
                               " with lo <= hi"))
    elif kind == "normal":
        ok = (isinstance(arg, dict) and _is_number(arg.get("sigma"))
              and arg["sigma"] > 0
              and ("mean" not in arg or _is_number(arg["mean"]))
              and set(arg) <= {"mean", "sigma"})
        if not ok:
            problems.append(f"{path}: normal needs {{sigma > 0, mean?}}")
    elif kind == "lognormal":
        ok = (isinstance(arg, dict) and set(arg) == {"median", "sigma"}
              and _is_number(arg["median"]) and arg["median"] > 0
              and _is_number(arg["sigma"]) and arg["sigma"] > 0)
        if not ok:
            problems.append(f"{path}: lognormal needs {{median > 0, "
                            f"sigma > 0}}")
    elif kind == "weibull":
        ok = (isinstance(arg, dict) and set(arg) == {"k", "lambda"}
              and _is_number(arg["k"]) and arg["k"] > 0
              and _is_number(arg["lambda"]) and arg["lambda"] > 0)
        if not ok:
            problems.append(f"{path}: weibull needs {{k > 0, lambda > 0}}")
    elif kind == "poisson":
        if not (_is_number(arg) and arg >= 0):
            problems.append(f"{path}: poisson needs a rate >= 0")
    elif kind == "uniform_dates":
        ok = (isinstance(arg, list) and len(arg) == 2
              and all(isinstance(v, str) for v in arg))
        if ok:
            from datetime import date
            try:
                lo, hi = (date.fromisoformat(v) for v in arg)
                ok = lo <= hi
            except ValueError:
                ok = False
        if not ok:
            problems.append(f"{path}: uniform_dates needs [\"YYYY-MM-DD\", "
                            f"\"YYYY-MM-DD\"] with the first no later")
    clip = leaf.get("clip")
    if clip is not None and (
            not isinstance(clip, list) or len(clip) != 2
            or not all(_is_number(v) for v in clip) or not clip[0] <= clip[1]):
        problems.append(f"{path}: clip needs [lo, hi] numbers")
    if "gated_by" in leaf and not (isinstance(leaf["gated_by"], str)
                                   and leaf["gated_by"].strip()):
        problems.append(f"{path}: gated_by must be a condition string")
    if "max" in leaf and not (_is_number(leaf["max"]) and leaf["max"] >= 0):
        problems.append(f"{path}: max must be a number >= 0")
    return problems


def policy_problems(policy, path: str = "randomization.policy",
                    nested: bool = False) -> List[str]:
    """Every way a policy mapping departs from the documented forms.

    A mapping that names a distribution is a leaf; any other mapping is
    a group whose values are checked in turn (``cameras: {preset: ...}``);
    a bare number or word at the TOP level is a fixed value
    (``sun_elevation_min_deg: 2``). Inside a group only leaves and
    groups are admitted, so a misspelt distribution
    (``gaussian: {sigma: 1}``) is refused rather than read as a group of
    fixed values.
    """
    if not isinstance(policy, dict):
        return [f"{path}: must be a mapping of leaves, not "
                f"{type(policy).__name__}"]
    problems: List[str] = []
    for key, value in policy.items():
        here = f"{path}.{key}"
        if not isinstance(key, str) or not key.strip():
            problems.append(f"{path}: leaf names must be non-empty strings")
            continue
        if _is_number(value) or isinstance(value, str):
            if nested:
                problems.append(
                    f"{here}: a group holds distribution leaves (one of "
                    f"{list(POLICY_DISTRIBUTIONS)}) or groups, not fixed "
                    f"values")
            continue                      # a top-level fixed value
        if isinstance(value, dict):
            if any(k in value for k in POLICY_DISTRIBUTIONS):
                problems.extend(_policy_leaf_problems(here, value))
            elif not value:
                problems.append(f"{here}: an empty mapping is neither a "
                                f"distribution nor a group")
            else:
                problems.extend(policy_problems(value, here, nested=True))
            continue
        problems.append(f"{here}: a leaf is a number, a string, a "
                        f"distribution mapping or a group, not "
                        f"{type(value).__name__}")
    return problems


def validate_policy(spec) -> List[Violation]:
    """``randomization.policy``, refused by name when its SHAPE is not
    one of the documented distribution forms, or -- the shape sound --
    when a ``gated_by`` is one the sampler could not judge (a number
    compared to a word, words ordered, a word the leaf never draws, a
    leaf not drawn before it: ``randomization.gate_problems``, the
    sampler's own check, so ``validate()`` -- the page's ``/compile``
    verdict -- refuses a bad gate before ``plan()`` does, in the
    sampler's words). Its semantics (which field each leaf samples)
    and the sampling are package F's."""
    policy = spec.randomization_policy
    if policy is None:
        return []
    problems = policy_problems(policy.value)
    if problems:
        return [Violation("randomization.policy",
                          "randomization.policy is not of the documented form: "
                          + "; ".join(problems))]
    from .randomization import gate_problems

    gates = gate_problems(policy.value)
    if not gates:
        return []
    return [Violation("randomization.policy",
                      "randomization.policy has a condition the sampler cannot judge: "
                      + "; ".join(gates))]


def validate_failures(spec) -> List[Violation]:
    """The ``failures`` block's own constraints, refused by name through
    the producer's own list (core.telemetry.failures.problems, so what
    validation refuses is what the schedule refuses): ``failures.kind``
    (an unknown kind or a malformed event), ``failures.target`` (a
    surface outside elevator / aileron / rudder, an engine index the
    airframe lacks), ``failures.time`` (negative, beyond the run, not a
    number, out of order), ``failures.value`` (an authority outside
    0..1, or a value on a kind that takes none), and
    ``failures.actuator_missing`` (a surface failure on an airframe the
    failures injection cannot anchor on). A default block (no events)
    yields nothing."""
    from ..telemetry.failures import problems

    block = getattr(spec, "failures", None)
    if block is None or block.is_default():
        return []
    return [Violation(problem.constraint, problem.message, actual=problem.actual,
                      limit=problem.limit, unit=problem.unit)
            for problem in problems(block.events.value, float(spec.duration.value),
                                    str(spec.aircraft.value))]


# -- the wake block (P7) --------------------------------------------------------------

def validate_wake(spec) -> List[Violation]:
    """The ``wake`` block's own constraints, refused by name through the
    provider's own list (core.environment.wake.problems, so what
    validation refuses is what the provider refuses): ``wake.generator``
    (an airframe that is not configured, or whose model states no span
    or no weight), ``wake.geometry`` (an offset or speed that is not a
    number, neither or both of separation and age, a negative age),
    ``wake.model`` (an unknown decay model), ``wake.decay`` (sarpkaya
    with eps* missing or out of range, N* out of range), and
    ``derivation.anchor_missing`` when the OWN airframe's ROLL axis
    cannot take the gust_rotation injection (the injection's own anchor
    test over the stock XML, nothing written). The default block, and a
    block naming no generator (nothing applied; recorded as unread by
    the runner), yield nothing."""
    from ..environment.wake import problems

    block = getattr(spec, "wake", None)
    if block is None or block.is_default() or block.generator.value is None:
        return []
    out = [Violation(problem.constraint, problem.message, actual=problem.actual,
                     limit=problem.limit, unit=problem.unit)
           for problem in problems(block.generator.value, block.generator_speed_kt.value,
                                   block.lateral_offset_m.value, block.vertical_offset_m.value,
                                   block.separation_s.value, block.age_s.value, block.model.value,
                                   block.eps_star.value, block.n_star.value)]
    from ..control.derive import INJECTIONS, DerivationError
    from ..fdm import aircraft as ac

    try:
        text = ac.resolve(str(spec.aircraft.value)).xml_path.read_text(encoding="utf-8")
        INJECTIONS["gust_rotation"].anchor_test(text)
    except DerivationError as exc:
        out.append(Violation(exc.constraint,
                             f"the wake's equivalent roll rate needs the gust_rotation injection, "
                             f"which this airframe cannot take: {exc}"))
    except Exception:
        pass        # an unknown aircraft is aircraft.exists, refused above
    return out


# -- the icing block (P5) ------------------------------------------------------------

def validate_icing(spec) -> List[Violation]:
    """The ``icing`` block's own constraints, refused by name through the
    provider's own list (core.environment.icing.problems, so what
    validation refuses is what the provider refuses): ``icing.severity``
    (a word outside the stated mapping), ``icing.eta_range`` (eta_max
    outside 0..1, a negative onset or ramp, an alpha shift outside its
    stated bound or not a number), ``icing.envelope`` (an unknown envelope
    word), ``icing.airframe_data`` (a stated block on an airframe with no
    k-table, or a malformed table). The default block (no ice) yields
    nothing."""
    from ..environment.icing import problems

    block = getattr(spec, "icing", None)
    if block is None or block.is_default():
        return []
    resolved = block.resolved()
    return [Violation(problem.constraint, problem.message, actual=problem.actual,
                      limit=problem.limit, unit=problem.unit)
            for problem in problems(block.severity.value, resolved["eta_max"].value,
                                    block.onset_s.value, block.ramp_s.value,
                                    block.alpha_shift_deg.value, block.envelope.value,
                                    str(spec.aircraft.value))]


# -- the rain block ---------------------------------------------------------------------

def validate_rain(spec) -> List[Violation]:
    """The ``rain`` block's own constraints, refused by name through the
    provider's own list (core.environment.rain.problems): ``rain.rate_missing``
    (aerodynamics with no rain rate), ``rain.runway_condition`` (an unknown
    word), ``rain.factor_range`` (a penalty outside its stated bound),
    ``rain.airframe_data`` (no frontal area or tyre pressure for this
    airframe). The default block (no rain physics) yields nothing."""
    from ..environment.rain import problems

    return [Violation(problem.constraint, problem.message, actual=problem.actual,
                      limit=problem.limit, unit=problem.unit)
            for problem in problems(spec)]


# -- the instruments block (R2) -------------------------------------------------------

def validate_instruments(spec) -> List[Violation]:
    """The ``instruments`` block's own constraints, refused by name through
    the observer's own list (core.telemetry.instruments.instrument_problems,
    so what validation refuses is what the runner refuses):
    ``instrument.profile`` (a field that is not a {profile, lever_arm_m}
    mapping, an unknown key, a profile not on file or malformed),
    ``instrument.lever_arm`` (not three finite metres, or longer than
    LEVER_ARM_MAX_M), ``instrument.rate`` (a GPS update rate above the FDM
    rate). The default block (every instrument unstated) yields nothing."""
    from ..telemetry.instruments import instrument_problems

    block = getattr(spec, "instruments", None)
    if block is None or block.is_default():
        return []
    out: List[Violation] = []
    for name, quantity in block.quantities():
        for constraint, message in instrument_problems(name, quantity.value,
                                                       float(spec.rate.value)):
            out.append(Violation(constraint, message))
    return out


# -- the record block (R2) ------------------------------------------------------------

#: The three-rate study's ceiling: above this the FDM steps below JSBSim's
#: own 1/1200 s (a rate the c172p at 60 s takes over a minute of physics
#: here) -- a stated bound, not a measured JSBSim limit.
RATE_MAX_HZ = 1200.0


def convergence_problems(value) -> List[str]:
    """Why a ``record.convergence`` value cannot be run: not a
    ``{rates: [r1, r2, r3]}`` mapping, not three finite positive numbers,
    not strictly ascending, not the study's own refinement ratio twice
    (core/uncertainty.py runs dt, dt/2, dt/4 from the first rate), or a
    rate above RATE_MAX_HZ. Empty when it can."""
    if value is None:
        return []
    if not isinstance(value, dict) or set(value) != {"rates"}:
        return [f"record.convergence must be {{rates: [r1, r2, r3]}} Hz or null, not {value!r}"]
    import math

    rates = value["rates"]
    if not isinstance(rates, list) or len(rates) != 3 or not all(
            isinstance(r, (int, float)) and not isinstance(r, bool) and math.isfinite(r) and r > 0.0
            for r in rates):
        return [f"record.convergence.rates must be three finite positive rates in Hz, "
                f"not {rates!r}"]
    from ..uncertainty import REFINEMENT_RATIO

    out: List[str] = []
    if not (rates[0] < rates[1] < rates[2]):
        out.append(f"record.convergence.rates {rates!r} are not strictly ascending")
    else:
        ratio_a, ratio_b = rates[1] / rates[0], rates[2] / rates[1]
        if abs(ratio_a - REFINEMENT_RATIO) > 1e-9 or abs(ratio_b - REFINEMENT_RATIO) > 1e-9:
            out.append(f"record.convergence.rates {rates!r} do not refine by the study's ratio "
                       f"{REFINEMENT_RATIO:g} twice ({ratio_a:g} then {ratio_b:g}); the three-rate "
                       f"study runs dt, dt/{REFINEMENT_RATIO:g}, dt/{REFINEMENT_RATIO ** 2:g} "
                       f"from the first rate")
    if max(rates) > RATE_MAX_HZ:
        out.append(f"record.convergence.rates {rates!r}: a rate above {RATE_MAX_HZ:g} Hz is "
                   f"one this build does not run")
    return out


def validate_record(spec) -> List[Violation]:
    """The ``record`` block's own constraints, refused by name:
    ``record.convergence`` (rates the three-rate study cannot run, see
    :func:`convergence_problems`; a non-boolean flag is named the same way),
    ``record.uncertainty_basis`` (sensitivity pairs asked for while a
    stated variable's provenance is ``inferred`` and its registry entry
    declares no vocabulary bin width, so no u_x rule exists for it -- the
    rule core/uncertainty.py would refuse to guess at). The default block
    yields nothing."""
    block = getattr(spec, "record", None)
    if block is None or block.is_default():
        return []
    out: List[Violation] = []
    for name in ("null_tests", "sensitivity_pairs"):
        value = getattr(block, name).value
        if not isinstance(value, bool):
            out.append(Violation("record.convergence",
                                 f"record.{name} must be true or false, not {value!r}"))
    problems = convergence_problems(block.convergence.value)
    for message in problems:
        out.append(Violation("record.convergence", message))
    # The uncertainty block (u_input for every stated variable) is what
    # the sensitivity pairs ask for, and what the convergence study
    # feeds: either one asks for a u_x rule per stated variable.
    if block.sensitivity_pairs.value is True or (block.convergence.value is not None
                                                 and not problems):
        out.extend(uncertainty_basis_violations(spec))
    return out


def uncertainty_basis_violations(spec) -> List[Violation]:
    """``record.uncertainty_basis`` for every stated registered variable
    whose provenance is ``inferred`` while its registry entry declares no
    vocabulary bin width -- no u_x rule exists for it (core/uncertainty.py
    u_x would refuse to guess). Called by :func:`validate_record` when the
    block asks for the uncertainty block, and by the capture when the
    ``--uncertainty`` option asks without the block."""
    from ..registry import REGISTRY

    out: List[Violation] = []
    for name, stated in REGISTRY.stated_variables(spec.to_dict()).items():
        if stated.get("value") is None or str(stated.get("source")) != "inferred":
            continue
        entry = REGISTRY.get(name)
        if entry.u_input_rule.bin_width is None:
            out.append(Violation(
                "record.uncertainty_basis",
                f"{name} is inferred and the uncertainty block asks for its u_input, "
                f"but the registry declares no vocabulary bin width for it, so no u_x "
                f"rule exists ({entry.u_input_rule.note or 'no note'})"))
    return out


def validate_world_look(spec) -> List[Violation]:
    """W3: ``scene.night`` and ``environment.precipitation_rate_mmh``,
    refused by name before any run (core/scene/night.py, precipitation.py):
    ``look.moon`` (the block's shape, the moon word, a moment that does
    not parse, or no moment at all -- no utc and no randomisation block to
    draw one), ``look.stars`` (the mode, or a catalogue the mode reads
    that is absent or whose sha256 differs), ``night.sun_units`` (the
    moon's lux on the bias path or beside a unitless sun, the rule in
    night.py) and ``look.precipitation_rate`` (not a positive number of
    mm/h within the MIL-HDBK-310 extreme). Unstated fields yield nothing."""
    out: List[Violation] = []
    night_q = getattr(getattr(spec, "scene", None), "night", None)
    value = None if night_q is None else night_q.value
    if value is not None:
        from ..scene.night import (
            NightError, load_catalogue, night_problems, spec_exposure_path, spec_sun_units,
            sun_units_problem,
        )

        problems = night_problems(value)
        for constraint, message in problems:
            out.append(Violation(constraint, message))
        if not problems:
            if (value.get("utc") is None and not spec.randomization.is_enabled()
                    and spec.randomization_policy is None):
                out.append(Violation("look.moon",
                                     "the moon cannot be placed: scene.night states no utc "
                                     "moment and no randomisation block draws one"))
            problem = sun_units_problem(value.get("moon", "on") == "on", spec_sun_units(spec),
                                        spec_exposure_path(spec))
            if problem:
                out.append(Violation("night.sun_units", problem))
            stars = value.get("stars", "auto")
            if stars in ("catalogue", "auto"):
                try:
                    if load_catalogue() is None and stars == "catalogue":
                        out.append(Violation("look.stars",
                                             "scene.night.stars is catalogue but the star "
                                             "catalogue is not cached (assets/stars/README.md)"))
                except NightError as exc:
                    out.append(Violation(exc.constraint, exc.message))
    rate_q = getattr(spec, "precipitation_rate_mmh", None)
    if rate_q is not None and rate_q.value is not None:
        from ..scene.precipitation import RAIN_RATE_MAX_MMH, rate_problem

        problem = rate_problem(rate_q.value)
        if problem:
            out.append(Violation("look.precipitation_rate", problem, actual=rate_q.value,
                                 limit=RAIN_RATE_MAX_MMH, unit="mm/h"))
    return out


def validate_lighting(spec) -> List[Violation]:
    """The ``lighting`` block: ``lighting.preset`` (a word that is not a
    preset) and ``lighting.range`` (a number outside what the render
    takes, core/scene/lighting.py RANGES -- a sun below the render floor
    among them). The default block yields nothing."""
    block = getattr(spec, "lighting", None)
    if block is None or block.is_default():
        return []
    from ..scene.lighting import problems, stated_values

    out: List[Violation] = []
    for kind, message in problems(stated_values(block)):
        if kind == "preset":
            out.append(Violation("lighting.preset", message))
        else:
            out.append(Violation("lighting.range", message))
    return out


def validate_route(spec) -> List[Violation]:
    """The ``route`` block, refused by name through the route's own list
    (core.control.route.route_problems, so what validation refuses is
    what the run refuses): ``route.shape``, ``route.bank_limit``,
    ``route.time`` (longer than true airspeed x duration -- the planning
    TAS, tas_kt_isa at the spec altitude), ``route.turn``, ``route.climb``;
    and ``route.hold_state`` when a route is stated without the autopilot
    (the route is flown by setpoints, so a run that holds nothing cannot
    fly it). Terrain is the web app's pre-flight, not the validator's.
    The default block (no route drawn) yields nothing."""
    block = getattr(spec, "route", None)
    if block is None or block.is_default():
        return []
    from ..control.route import route_problems, tas_kt_for_spec

    out = [Violation(problem["constraint"], problem["message"], actual=problem.get("actual"),
                     limit=problem.get("limit"), unit=problem.get("unit"))
           for problem in route_problems(block.waypoints.value, block.bank_limit_deg.value,
                                         tas_kt=tas_kt_for_spec(spec),
                                         duration_s=float(spec.duration.value),
                                         altitude0_m=float(spec.altitude.value))]
    if not bool(spec.hold_state.value):
        out.append(Violation(
            "route.hold_state",
            "a route is stated but the run does not hold its state: the route is flown "
            "by the autopilot's setpoints, so hold_state must be true"))
    return out


def validate_world(spec) -> List[Violation]:
    """W2: ``scene.buildings`` and the ``runway`` block, refused by name.

    A stated footprint key is loaded from the cache here, before any run
    (core/scene/buildings.py load_footprints): ``buildings.uncached`` (no
    data file or sidecar, or a key that is not a plain file stem),
    ``buildings.licence``, ``buildings.unverified``, ``buildings.ids``.
    A stated runway is checked by core/scene/runway.py's one ``problems``
    list: ``runway.geometry``, ``runway.taxonomy``, ``runway.markings``
    (``runway.terrain_mismatch`` is the pad bake's, where the runway meets
    the bake). The default scene and runway yield nothing, and so does a
    runway block with no designator (no runway: its fields are unread)."""
    out: List[Violation] = []
    key = getattr(getattr(spec, "scene", None), "buildings", None)
    key = None if key is None else key.value
    if key is not None:
        from ..scene.buildings import BuildingsError, load_footprints

        if (not isinstance(key, str) or not key.strip() or "/" in key or "\\" in key
                or key.startswith(".")):
            out.append(Violation("buildings.uncached",
                                 f"scene.buildings must name a cached set's key (a file stem "
                                 f"under assets/buildings), not {key!r}"))
        else:
            try:
                load_footprints(key)
            except BuildingsError as exc:
                out.append(Violation(exc.constraint, exc.message))
    block = getattr(spec, "runway", None)
    if block is None or block.is_default():
        return out
    from ..scene.runway import problems

    values = {name: q.value for name, q in block.quantities()}
    if values["designator"] is None:
        # No designator is no runway (the registry's null for
        # runway.designator, so the null pair's spec must validate): the
        # block's other fields are carried and unread, as the wake block's
        # are without a generator.
        return out
    for problem in problems(values["designator"], values["threshold_lat_deg"],
                            values["threshold_lon_deg"], values["heading_deg"],
                            values["length_m"], values["width_m"], values["surface"],
                            values["markings"]):
        out.append(Violation(problem.constraint, problem.message))
    return out
