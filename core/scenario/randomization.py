"""Domain randomisation as a spec block: sampled once, recorded, replayable.

A dataset wants variety the prompt did not ask for -- the sun where it
would be at some hour of some day, haze between clear and hazy, the
camera a little off its preset, a different livery -- and it wants
every one of those choices RECORDED so the frame can be reproduced and
the label can say what it labels. This block is how the spec carries
that: a provenanced ``randomization`` section (optional; absent is the
documented default, "off") with its own seed, the ranges the sampler
draws from, and the drawn values written back as ``derived``
Quantities beside the ranges. The sampler is a planner like every
other: it runs before the digest is answered, it moves only fields
the user did not state, it is value-idempotent (the same seed draws
the same numbers on every pass), and it refuses by name when a draw
cannot satisfy the stated window.

What is sampled, and by what:

* **time of day** -- a day of the year and a UTC hour, uniform in the
  stated windows; the sun's elevation and azimuth follow from the
  spec's own latitude/longitude by the cited solar-position algorithm
  (core.scenario.solar). Draws whose sun is below ``sun_elevation_min_deg``
  are rejected and redrawn (at most MAX_DAYLIGHT_DRAWS, then a named
  refusal): the render's exposure is calibrated only for daylight.
* **exposure** -- NOT sampled: interpolated between the two
  probe-calibrated look points the harness already uses (dawn 8 deg ->
  10.5, noon 50 deg -> 9.5; NEXT.md gotcha 7), clamped outside them. A
  palette nobody rendered is not invented here (gotcha 6).
* **fog** -- log-uniform between ``fog_density_min`` and ``_max``,
  whose defaults are the harness's calibrated clear and hazy values.
* **camera jitter** -- per camera, each plannable placement field
  moves by a uniform draw within ``camera_jitter_m`` (metres) or
  ``camera_jitter_deg`` (degrees); focal length by a uniform fraction.
  A user-stated camera field is never moved (skipped, and the skip is
  noted). The un-jittered value is kept in the field's ``detail`` so a
  second planner pass lands on the same number rather than jittering
  the jitter.
* **livery** -- a uniform choice among the variants the aircraft's
  config declares (``liveries: [...]`` in assets/aircraft_config); an
  airframe that declares none keeps ``"default"``, stated as such.

Every stream is its own: sha256 over ``"<seed>:randomization:<label>"``
(the sensor model's convention, core.capture.profile.frame_seed), so
adding a camera does not change the sun, and the block's seed derives
from the run seed when the user gave none.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .fields import Quantity, Source
from .solar import SOURCE as SOLAR_SOURCE, solar_position

CONFIG_DIR = Path(__file__).resolve().parents[2] / "assets" / "aircraft_config"

#: The two look points the harness renders with, probe-calibrated
#: (experiments/showcase_matrix.TIME_OF_DAY, NEXT.md gotcha 7):
#: (sun elevation deg, exposure bias). Exposure is interpolated between
#: them and clamped beyond -- never extrapolated into a look nobody has
#: rendered. A test pins these to the harness table.
EXPOSURE_CALIBRATION = ((8.0, 10.5), (50.0, 9.5))
#: The harness's calibrated fog densities (showcase_matrix.VISIBILITY).
FOG_CLEAR = 0.0012
FOG_HAZY = 0.010
#: Draws rejected for a sun below the floor before the sampler refuses.
MAX_DAYLIGHT_DRAWS = 64
#: Largest seed any consumer represents (core.experiments.seeds.MAX_SEED).
MAX_SEED = 2 ** 31 - 2
DEFAULT_LIVERY = "default"
#: Years the cited solar algorithm is stated accurate for.
YEAR_MIN, YEAR_MAX = 1950, 2050
#: Where a jittered camera field keeps its un-jittered value.
JITTER_BASE_KEY = "randomization_base"

PLANNABLE = (Source.DEFAULT, Source.DERIVED, Source.MODEL)


class RandomizationError(ValueError):
    """A named refusal from the sampler (``constraint`` is the name)."""

    def __init__(self, constraint: str, message: str):
        super().__init__(message)
        self.constraint = constraint
        self.message = message


def _d(value, unit=None, frm="documented randomisation default", **detail):
    return Quantity.default(value, unit, frm=frm, **detail)


@dataclass
class RandomizationSpec:
    """The block. Ranges first, then the sampled values (``derived``
    once the sampler has run; ``default`` placeholders before)."""

    enabled: Quantity
    seed: Quantity
    year: Quantity
    day_of_year_min: Quantity
    day_of_year_max: Quantity
    hour_utc_min: Quantity
    hour_utc_max: Quantity
    sun_elevation_min_deg: Quantity
    fog_density_min: Quantity
    fog_density_max: Quantity
    camera_jitter_m: Quantity
    camera_jitter_deg: Quantity
    camera_focal_jitter: Quantity
    # -- sampled -------------------------------------------------------
    day_of_year: Quantity
    hour_utc: Quantity
    sun_elevation_deg: Quantity
    sun_azimuth_deg: Quantity
    exposure_bias: Quantity
    fog_density: Quantity
    livery: Quantity

    FIELD_ORDER = (
        "enabled", "seed", "year",
        "day_of_year_min", "day_of_year_max",
        "hour_utc_min", "hour_utc_max", "sun_elevation_min_deg",
        "fog_density_min", "fog_density_max",
        "camera_jitter_m", "camera_jitter_deg", "camera_focal_jitter",
        "day_of_year", "hour_utc", "sun_elevation_deg", "sun_azimuth_deg",
        "exposure_bias", "fog_density", "livery",
    )
    SAMPLED = ("day_of_year", "hour_utc", "sun_elevation_deg",
               "sun_azimuth_deg", "exposure_bias", "fog_density", "livery")

    # -- access ---------------------------------------------------------

    def quantities(self):
        for name in self.FIELD_ORDER:
            yield name, getattr(self, name)

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        current = getattr(self, name)
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.USER, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Same doctrine as the spec's and the camera's: only a
        defaulted/derived/model field moves; a stated one refuses by
        name."""
        current = getattr(self, name)
        if current.source not in PLANNABLE:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; "
                f"randomization.{name} is {current.source.value!r} -- a "
                f"stated value is never silently moved")
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.DERIVED, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def is_enabled(self) -> bool:
        return bool(self.enabled.value)

    def is_sampled(self) -> bool:
        """Every sampled field has been drawn (or stated)."""
        return all(getattr(self, name).source != Source.DEFAULT
                   for name in self.SAMPLED)

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {name: q.to_dict() for name, q in self.quantities()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RandomizationSpec":
        if not isinstance(data, dict):
            raise ValueError("spec 'randomization' must be a mapping of "
                             "provenanced fields")
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"randomization is missing required field {name}") from exc
        unknown = set(data) - set(cls.FIELD_ORDER)
        if unknown:
            raise ValueError(
                f"randomization carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        return cls(**kwargs)

    def is_default(self) -> bool:
        """The documented default, field for field, source for source
        -- the one spelling the canonical spec omits."""
        return self.to_dict() == self.defaulted().to_dict()

    # -- construction ---------------------------------------------------

    @classmethod
    def defaulted(cls) -> "RandomizationSpec":
        unsampled = "not sampled yet (the sampler draws it when enabled)"
        return cls(
            enabled=_d(False, frm="off: the spec renders exactly as stated"),
            seed=_d(0, "dimensionless",
                    frm="0 = derive from the run seed when enabled"),
            year=_d(2024, "year", frm="a leap year, so day 366 exists; "
                                      "inside the solar algorithm's "
                                      "stated 1950-2050"),
            day_of_year_min=_d(1, "day"),
            day_of_year_max=_d(366, "day"),
            hour_utc_min=_d(0.0, "h"),
            hour_utc_max=_d(24.0, "h"),
            sun_elevation_min_deg=_d(
                8.0, "deg", frm="the dawn look point: exposure is "
                                "calibrated from 8 deg up (gotcha 7)"),
            fog_density_min=_d(FOG_CLEAR, "1/m",
                               frm="the harness's calibrated 'clear'"),
            fog_density_max=_d(FOG_HAZY, "1/m",
                               frm="the harness's calibrated 'hazy'"),
            camera_jitter_m=_d(1.0, "m"),
            camera_jitter_deg=_d(2.0, "deg"),
            camera_focal_jitter=_d(0.10, "fraction"),
            day_of_year=_d(0, "day", frm=unsampled),
            hour_utc=_d(0.0, "h", frm=unsampled),
            sun_elevation_deg=_d(0.0, "deg", frm=unsampled),
            sun_azimuth_deg=_d(0.0, "deg", frm=unsampled),
            exposure_bias=_d(0.0, "EV", frm=unsampled),
            fog_density=_d(0.0, "1/m", frm=unsampled),
            livery=_d(DEFAULT_LIVERY, frm=unsampled),
        )


# -- streams -----------------------------------------------------------

def derive_block_seed(run_seed: int) -> int:
    """The block's seed from the run's: sha256 over ``"<run seed>:
    randomization"``, inside MAX_SEED. Stated so a batch that varies the
    run seed varies the draws, and nothing else does."""
    digest = hashlib.sha256(f"{int(run_seed)}:randomization".encode()).digest()
    return int.from_bytes(digest[:8], "big") % MAX_SEED


def stream(seed: int, label: str) -> np.random.Generator:
    """One generator per aspect, from the block seed and the aspect's
    name. Adding a camera cannot move the sun."""
    digest = hashlib.sha256(f"{int(seed)}:randomization:{label}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


# -- the pure parts ----------------------------------------------------

def exposure_for_elevation(sun_elevation_deg: float) -> float:
    """Linear between the two calibrated look points, clamped beyond."""
    (e0, b0), (e1, b1) = EXPOSURE_CALIBRATION
    if sun_elevation_deg <= e0:
        return b0
    if sun_elevation_deg >= e1:
        return b1
    f = (sun_elevation_deg - e0) / (e1 - e0)
    return b0 + f * (b1 - b0)


def engine_sun_azimuth(compass_azimuth_deg: float) -> float:
    """The commandlet's ``-sun-azim`` from a compass azimuth.

    The scene frame is X east, Y north (poses.py: ``origin_x + east``),
    and an Unreal rotator's yaw ``psi`` points along ``(cos psi, sin
    psi)`` in (X, Y) -- so a yaw is measured from east toward north,
    and the compass bearing it points along is ``90 - psi``. The
    commandlet sets the light to travel along ``sun_azim + 180``, i.e.
    it takes ``sun_azim`` as the yaw TOWARD the sun; the yaw toward a
    compass bearing ``b`` is ``90 - b``."""
    return (90.0 - float(compass_azimuth_deg)) % 360.0


def declared_liveries(aircraft: str, config_dir: Optional[Path] = None
                      ) -> List[str]:
    """The livery variants an airframe's config declares; [] when it
    declares none (the documented case today -- no shipped airframe
    carries a variant material)."""
    path = Path(config_dir or CONFIG_DIR) / f"{aircraft}.json"
    if not path.is_file():
        return []
    config = json.loads(path.read_text(encoding="utf-8"))
    liveries = config.get("liveries") or []
    if not isinstance(liveries, list) or not all(
            isinstance(name, str) and name for name in liveries):
        raise RandomizationError(
            "randomization.livery",
            f"{path.name} 'liveries' must be a list of non-empty variant "
            f"names")
    return [str(name) for name in liveries]


# -- the sampler (a planner) --------------------------------------------

def _plan_unless_stated(block: RandomizationSpec, name: str, value: Any,
                        frm: str) -> None:
    if getattr(block, name).source in PLANNABLE:
        block.plan(name, value, frm=frm)


def _sample_time_of_day(spec, block: RandomizationSpec, seed: int) -> None:
    rng = stream(seed, "time_of_day")
    year = int(block.year.value)
    doy_stated = block.day_of_year.source not in PLANNABLE
    hour_stated = block.hour_utc.source not in PLANNABLE
    lo_d, hi_d = int(block.day_of_year_min.value), int(block.day_of_year_max.value)
    lo_h, hi_h = float(block.hour_utc_min.value), float(block.hour_utc_max.value)
    floor = float(block.sun_elevation_min_deg.value)
    lat, lon = float(spec.latitude.value), float(spec.longitude.value)
    draws = 1 if (doy_stated and hour_stated) else MAX_DAYLIGHT_DRAWS
    for attempt in range(draws):
        doy = (int(block.day_of_year.value) if doy_stated
               else int(rng.integers(lo_d, hi_d + 1)))
        hour = (float(block.hour_utc.value) if hour_stated
                else float(rng.uniform(lo_h, hi_h)))
        position = solar_position(lat, lon, year, doy, hour)
        if position.elevation_deg >= floor:
            break
    else:
        raise RandomizationError(
            "randomization.time_of_day",
            f"no draw of {draws} in day {lo_d}-{hi_d} x {lo_h:g}-{hi_h:g} h "
            f"UTC at ({lat:.3f}, {lon:.3f}) put the sun at or above "
            f"{floor:g} deg; the exposure is calibrated for daylight only "
            f"-- narrow the window or lower sun_elevation_min_deg")
    frm = (f"drawn from the time-of-day stream of seed {seed} (attempt "
           f"{attempt + 1}), sun above {floor:g} deg")
    _plan_unless_stated(block, "day_of_year", doy, frm)
    _plan_unless_stated(block, "hour_utc", round(hour, 4), frm)
    solar_frm = (f"solar position at ({lat:.3f}, {lon:.3f}), {year} day "
                 f"{doy} {hour:.2f} h UTC -- {SOLAR_SOURCE}")
    _plan_unless_stated(block, "sun_elevation_deg",
                        round(position.elevation_deg, 3), solar_frm)
    _plan_unless_stated(block, "sun_azimuth_deg",
                        round(position.azimuth_deg, 3),
                        solar_frm + "; compass, clockwise from north")
    _plan_unless_stated(
        block, "exposure_bias",
        round(exposure_for_elevation(float(block.sun_elevation_deg.value)), 3),
        f"interpolated between the calibrated look points "
        f"{EXPOSURE_CALIBRATION} at the sampled sun elevation (gotcha 7); "
        f"clamped beyond them")


def _sample_fog(block: RandomizationSpec, seed: int) -> None:
    rng = stream(seed, "fog")
    lo, hi = float(block.fog_density_min.value), float(block.fog_density_max.value)
    density = math.exp(rng.uniform(math.log(lo), math.log(hi)))
    _plan_unless_stated(block, "fog_density", float(f"{density:.6g}"),
                        f"log-uniform in [{lo:g}, {hi:g}] 1/m from the fog "
                        f"stream of seed {seed}")


def _sample_livery(spec, block: RandomizationSpec, seed: int,
                   config_dir: Optional[Path]) -> None:
    aircraft = str(spec.aircraft.value)
    variants = declared_liveries(aircraft, config_dir)
    if not variants:
        _plan_unless_stated(block, "livery", DEFAULT_LIVERY,
                            f"{aircraft} declares no livery variants "
                            f"(assets/aircraft_config 'liveries'); the "
                            f"mesh's own materials")
        return
    rng = stream(seed, "livery")
    choice = variants[int(rng.integers(0, len(variants)))]
    _plan_unless_stated(block, "livery", choice,
                        f"uniform over {variants} from the livery stream "
                        f"of seed {seed}")


#: Which camera fields a jitter may move, by the camera's mode, and
#: which draw feeds each (metres / degrees / focal fraction).
_POSITION_FIELDS = {
    "offset": ("offset_forward_m", "offset_right_m", "offset_up_m"),
    "scene": ("position_north_m", "position_east_m", "position_alt_m"),
    # geographic placements are in degrees: a metre jitter would need a
    # conversion that the record cannot state simply; not jittered.
    "geographic": (),
}
_AIM_FIELDS = {
    "bearing": ("aim_bearing_deg", "aim_elevation_deg"),
    "point": ("aim_north_m", "aim_east_m", "aim_alt_m"),
    "aircraft": (),
}


def _jitter_camera(spec, camera, seed: int, block: RandomizationSpec) -> None:
    camera_id = str(camera.camera_id.value)
    rng = stream(seed, f"camera:{camera_id}")
    jm = float(block.camera_jitter_m.value)
    jd = float(block.camera_jitter_deg.value)
    jf = float(block.camera_focal_jitter.value)
    mode = str(camera.position_mode.value)
    aim = str(camera.aim_mode.value)
    plan: List[tuple] = []
    for name in _POSITION_FIELDS.get(mode, ()):
        plan.append((name, float(rng.uniform(-jm, jm)), "additive"))
    for name in _AIM_FIELDS.get(aim, ()):
        span = jd if name.endswith("_deg") else jm
        plan.append((name, float(rng.uniform(-span, span)), "additive"))
    plan.append(("focal_length_mm", float(rng.uniform(-jf, jf)), "fraction"))
    # Every draw above is taken whether or not its field moves, so a
    # stated field does not shift the draws of the others.
    for name, draw, kind in plan:
        q = getattr(camera, name)
        if q.source not in PLANNABLE:
            note = (f"randomization: camera {camera_id!r} field {name} is "
                    f"{q.source.value}-stated; not jittered")
            if note not in spec.notes:
                spec.notes.append(note)
            continue
        base = float(q.detail.get(JITTER_BASE_KEY, q.value))
        if kind == "fraction":
            value = base * (1.0 + draw)
            frm = (f"{base:g} x (1 {draw:+.4f}) from the camera stream of "
                   f"seed {seed} (focal jitter +/-{jf:g})")
        else:
            value = base + draw
            frm = (f"{base:g} {draw:+.4f} from the camera stream of seed "
                   f"{seed} (jitter +/-{jm:g} m / +/-{jd:g} deg)")
        setattr(camera, name, replace(
            q, value=round(value, 4), source=Source.DERIVED, frm=frm,
            detail={**q.detail, JITTER_BASE_KEY: base}))


def sample_randomization(spec, config_dir: Optional[Path] = None) -> None:
    """The planner. No-op when the block is off; otherwise every draw
    is made from the block's seed and written back as ``derived``.
    Value-idempotent: a second pass draws the same numbers."""
    block = spec.randomization
    if not block.is_enabled():
        return
    if block.seed.source in PLANNABLE and int(block.seed.value) == 0:
        block.plan("seed", derive_block_seed(int(spec.seed.value)),
                   frm=f"derived from run seed {int(spec.seed.value)}: "
                       f"sha256('<run seed>:randomization') mod {MAX_SEED}")
    seed = int(block.seed.value)
    _sample_time_of_day(spec, block, seed)
    _sample_fog(block, seed)
    _sample_livery(spec, block, seed, config_dir)
    for camera in spec.cameras:
        _jitter_camera(spec, camera, seed, block)


# -- what the render and the record take ---------------------------------

def render_look(spec) -> Optional[Dict[str, float]]:
    """The commandlet's look flags from the sampled block, or None when
    the block is off (the harness's own look then applies, byte for
    byte). Refuses an enabled block nobody sampled: a render must not
    guess a sun."""
    block = spec.randomization
    if not block.is_enabled():
        return None
    if not block.is_sampled():
        raise RandomizationError(
            "randomization.unsampled",
            "the randomization block is enabled but not sampled; run the "
            "planners (sample_randomization) before rendering")
    return {
        "sun_elev": float(block.sun_elevation_deg.value),
        "sun_azim": engine_sun_azimuth(float(block.sun_azimuth_deg.value)),
        "exposure_bias": float(block.exposure_bias.value),
        "fog_density": float(block.fog_density.value),
    }


def card_block(spec) -> Optional[Dict[str, Any]]:
    """The sampled values for the run card and the manifest: every
    number the render was given, in both conventions, plus each camera
    field the jitter moved and by how much."""
    look = render_look(spec)
    if look is None:
        return None
    block = spec.randomization
    jitter: Dict[str, Dict[str, float]] = {}
    for camera in spec.cameras:
        moved = {}
        for name, q in camera.quantities():
            if JITTER_BASE_KEY in q.detail:
                base = float(q.detail[JITTER_BASE_KEY])
                moved[name] = {"base": base, "value": float(q.value),
                               "delta": round(float(q.value) - base, 6)}
        if moved:
            jitter[str(camera.camera_id.value)] = moved
    return {
        "seed": int(block.seed.value),
        "year": int(block.year.value),
        "day_of_year": int(block.day_of_year.value),
        "hour_utc": float(block.hour_utc.value),
        "sun_elevation_deg": look["sun_elev"],
        "sun_azimuth_deg": float(block.sun_azimuth_deg.value),
        "engine_sun_azimuth_deg": look["sun_azim"],
        "exposure_bias": look["exposure_bias"],
        "fog_density": look["fog_density"],
        "livery": str(block.livery.value),
        "solar_source": SOLAR_SOURCE,
        "camera_jitter": jitter,
    }
