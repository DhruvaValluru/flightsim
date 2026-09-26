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
from typing import Any, List, Optional

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

    # -- cameras: the scene-free half (Camera Phase 1) -----------------
    # Imported here: core.capture.validate produces THIS module's
    # Violation type, so a module-scope import would be a cycle.
    from ..capture.validate import validate_cameras

    report.violations.extend(validate_cameras(spec))
    report.violations.extend(validate_randomization(spec))
    report.violations.extend(validate_blocks(spec))
    report.violations.extend(validate_policy(spec))

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
            report.violations.append(
                Violation(
                    "envelope.trim_feasible",
                    f"this model cannot be trimmed at the commanded condition; "
                    f"its aero tables do not reach here. Underlying error: "
                    f"{type(exc).__name__}",
                )
            )

    return report


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
        MAX_TRAFFIC, TERRAIN_SOURCES, TRAFFIC_TRACKS, configured_airframes,
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
    for index, entry in enumerate(spec.traffic):
        who = f"traffic[{index}]"
        aircraft = str(entry.aircraft.value)
        if aircraft not in airframes:
            out.append(Violation(
                "traffic.aircraft",
                f"{who}: {aircraft!r} is not a configured airframe (one "
                f"of {airframes}; its mesh must be importable like the "
                f"primary's)"))
        track = str(entry.track.value)
        if track not in TRAFFIC_TRACKS:
            out.append(Violation(
                "traffic.track",
                f"{who}: track must be one of {list(TRAFFIC_TRACKS)}, not "
                f"{track!r}"))
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
    one of the documented distribution forms. Its semantics (which
    field each leaf samples) and the sampling are package F's."""
    policy = spec.randomization_policy
    if policy is None:
        return []
    problems = policy_problems(policy.value)
    if not problems:
        return []
    return [Violation("randomization.policy",
                      "randomization.policy is not of the documented form: "
                      + "; ".join(problems))]
