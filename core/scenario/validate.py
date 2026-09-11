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
from typing import List, Optional

from ..fdm import FDMError, FlightDynamics, TrimMode
from ..fdm import units as u
from .envelope import ReferenceSpeeds, reference_speeds
from .spec import ScenarioSpec

#: Minimum clearance above terrain for an airborne start.
MIN_CLEARANCE_M = 30.0
#: Commanded speed must exceed the measured stall by this factor.
STALL_MARGIN = 1.05


@dataclass(frozen=True)
class Violation:
    """One failed constraint, named."""

    constraint: str
    message: str
    actual: Optional[float] = None
    limit: Optional[float] = None
    unit: Optional[str] = None

    def render(self) -> str:
        detail = ""
        if self.actual is not None and self.limit is not None:
            unit = f" {self.unit}" if self.unit else ""
            detail = f" (requested {self.actual:g}{unit}, limit {self.limit:g}{unit})"
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
