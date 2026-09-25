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

**The policy (spec 8, contracts §5; package F).** ``randomization.policy``
is a mapping of distribution leaves over named parameters
(``POLICY_LEAVES``: location, weather_date, hour_local, visibility_km,
cloud_cover, cloud_base_m, precipitation, wind_speed_kt,
wind_direction_deg, turbulence, surface, aircraft, livery,
traffic_count, and the ``cameras`` group). The leaves above are drawn by
the same planner, BEFORE the Phase 10 leaves, and written with
``Source.SAMPLED`` and ``detail = {policy, distribution, seed,
draw_index}``; a sampled field is never re-planned (it is absent from
PLANNABLE). Seeds follow ``core.experiments.seeds``' SeedSequence
discipline: one PCG64 stream per leaf and attempt, spawned from
``SeedSequence(entropy=[draw_index, campaign seed])`` -- the campaign
seed is the block's own seed, the draw index the campaign's case index
(0 for a single run). Every attempt goes through ``validate()``; a
refused draw is recorded as ``{draw_index, attempt, refusal_name,
sampled_values}`` on the block's ``policy_draws`` field and re-drawn,
up to ``MAX_POLICY_ATTEMPTS`` (20), after which the slot is refused by
name (``randomization.infeasible``) with every refusal in the error's
detail. The Phase 10 leaves keep their own sha256 streams so
``examples/randomized.yaml`` samples exactly as before; the policy adds
to them and never re-draws what they drew.

What is NOT claimed: no leaf instantiates ``traffic[]`` entries (the
count is recorded; an entry needs an airframe choice, package B's
shape); the ``location`` leaf moves latitude/longitude/terrain elevation
but not the cameras' per-airframe offsets that were defaulted at
compile time (stated in the report); no distribution outside the nine
documented forms exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..scene import weather_visuals
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

#: The sampler's own copy of the plannable rule (fields.PLANNABLE_SOURCES
#: is the shared statement). Source.SAMPLED is deliberately absent: a
#: drawn value is as fixed as a stated one (contracts §5.1).
PLANNABLE = (Source.DEFAULT, Source.DERIVED, Source.MODEL)
#: Attempts per slot before the policy refuses ``randomization.infeasible``.
MAX_POLICY_ATTEMPTS = 20
#: Where a sampled hour_local writes its UTC hour: local mean time by
#: longitude (no time zones), hour_utc = (hour_local - lon / 15) mod 24.
DEGREES_PER_HOUR = 15.0


class RandomizationError(ValueError):
    """A named refusal from the sampler (``constraint`` is the name).
    ``detail`` carries the structured record where one exists (the
    refused draws behind ``randomization.infeasible``)."""

    def __init__(self, constraint: str, message: str,
                 detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.constraint = constraint
        self.message = message
        self.detail = dict(detail or {})


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
    # -- spec 8 policy leaves (contracts §12): defaulted placeholders,
    # each OMITTED from the block's canonical form while it is the
    # placeholder, so a Phase 10 block keeps its bytes and its digest.
    visibility_km: Quantity = None
    cloud_cover: Quantity = None
    cloud_base_m: Quantity = None
    precipitation: Quantity = None
    hour_local: Quantity = None
    location: Quantity = None
    traffic_count: Quantity = None
    #: The draw record: {draw_index, attempts, max_attempts, refused: [...]}.
    policy_draws: Quantity = None

    FIELD_ORDER = (
        "enabled", "seed", "year",
        "day_of_year_min", "day_of_year_max",
        "hour_utc_min", "hour_utc_max", "sun_elevation_min_deg",
        "fog_density_min", "fog_density_max",
        "camera_jitter_m", "camera_jitter_deg", "camera_focal_jitter",
        "day_of_year", "hour_utc", "sun_elevation_deg", "sun_azimuth_deg",
        "exposure_bias", "fog_density", "livery",
        "visibility_km", "cloud_cover", "cloud_base_m", "precipitation",
        "hour_local", "location", "traffic_count", "policy_draws",
    )
    SAMPLED = ("day_of_year", "hour_utc", "sun_elevation_deg",
               "sun_azimuth_deg", "exposure_bias", "fog_density", "livery")
    #: The spec-8 leaves: optional on read, absent from to_dict() while
    #: at their placeholder (per-field absent-canonical).
    POLICY_FIELDS = ("visibility_km", "cloud_cover", "cloud_base_m",
                     "precipitation", "hour_local", "location",
                     "traffic_count", "policy_draws")
    #: The range fields a policy's top-level fixed scalar may set.
    RANGE_FIELDS = ("year", "day_of_year_min", "day_of_year_max",
                    "hour_utc_min", "hour_utc_max", "sun_elevation_min_deg",
                    "fog_density_min", "fog_density_max", "camera_jitter_m",
                    "camera_jitter_deg", "camera_focal_jitter")

    def __post_init__(self) -> None:
        placeholders = None
        for name in self.POLICY_FIELDS:
            if getattr(self, name) is None:
                if placeholders is None:
                    placeholders = self._policy_placeholders()
                setattr(self, name, placeholders[name])

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
        placeholders = self._policy_placeholders()
        out = {}
        for name, q in self.quantities():
            if name in self.POLICY_FIELDS and q.to_dict() == placeholders[name].to_dict():
                continue        # absent IS the placeholder (spec 8 leaves)
            out[name] = q.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RandomizationSpec":
        if not isinstance(data, dict):
            raise ValueError("spec 'randomization' must be a mapping of "
                             "provenanced fields")
        kwargs = {}
        for name in cls.FIELD_ORDER:
            if name in cls.POLICY_FIELDS and name not in data:
                continue        # the placeholder (__post_init__ fills it)
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

    @staticmethod
    def _policy_placeholders() -> Dict[str, Quantity]:
        """The spec-8 leaves before a policy draws them (omitted from
        the canonical form while they read exactly this)."""
        unsampled = "not drawn (no policy names this leaf)"
        return {
            "visibility_km": _d(0.0, "km", frm=unsampled),
            "cloud_cover": _d(0.0, "fraction", frm=unsampled),
            "cloud_base_m": _d(0.0, "m", frm=unsampled),
            "precipitation": _d("none", frm=unsampled),
            "hour_local": _d(0.0, "h", frm=unsampled),
            "location": _d("none", frm=unsampled),
            "traffic_count": _d(0, "dimensionless", frm=unsampled),
            "policy_draws": _d(None, frm="no policy draw has run"),
        }


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


# -- the policy (spec 8, contracts §5.2) ----------------------------------

#: One PCG64 stream per leaf and attempt (core.experiments.seeds'
#: discipline): SeedSequence(entropy=[draw_index, campaign_seed],
#: spawn_key=(attempt, stable_hash(leaf))). Recorded per draw as the
#: leaf's ``seed`` detail (the folded integer, 1..MAX_SEED).
POLICY_SEED_DERIVATION = ("SeedSequence(entropy=[draw_index, campaign_seed], "
                          "spawn_key=(attempt, stable_hash(leaf))), PCG64; "
                          "seed = 1 + first uint64 mod MAX_SEED")


def policy_stream(campaign_seed: int, draw_index: int, attempt: int,
                  leaf: str):
    """(generator, recorded seed) for one leaf of one attempt of one draw."""
    from ..experiments.seeds import stable_hash

    sequence = np.random.SeedSequence(
        entropy=[int(draw_index), int(campaign_seed)],
        spawn_key=(int(attempt), stable_hash(leaf)))
    seed = 1 + int(sequence.generate_state(1, dtype=np.uint64)[0]) % MAX_SEED
    return np.random.Generator(np.random.PCG64(sequence)), seed


#: Named hour windows a ``hour_local`` choice leaf may draw among
#: (local mean time by longitude); the draw is uniform inside the window.
HOUR_WINDOWS: Dict[str, tuple] = {
    "dawn": (5.5, 8.0), "morning": (8.0, 11.0), "midday": (11.0, 14.0),
    "afternoon": (14.0, 17.0), "dusk": (17.0, 20.0),
}
#: Mountain ranges (and regions) a ``location`` choice may name, and the
#: bakes in ``core.terrain.glo30.LOCATIONS`` that lie in each. A range
#: with no bake refuses ``randomization.location`` by name until one
#: lands -- the Rockies and the Cascades have none today.
LOCATION_RANGES: Dict[str, tuple] = {
    "alps": ("matterhorn",), "sierra_nevada": ("yosemite",),
    "himalayas": ("everest",), "colorado_plateau": ("grand_canyon",),
    "great_plains": ("flint_hills",), "japan": ("fuji",),
    "rockies": (), "cascades": (),
}
PRECIPITATION_WORDS = ("none", "rain", "snow")
TURBULENCE_LEVELS = {"none": 0.0, "light": 15.0, "moderate": 30.0, "severe": 45.0}
TURBULENCE_STD = "MIL-F-8785C Fig.7 (W20, wind speed at 20 ft AGL)"

#: The leaves a policy may name (contracts §5.2), each with the
#: distribution forms it admits, its value type, its bounds (a draw
#: outside them is a refused draw, recorded and re-drawn) and the field
#: it writes. ``core.nl.llm_compiler`` builds its bounded schema from
#: this table and asserts against it at import.
POLICY_LEAVES: Dict[str, Dict[str, Any]] = {
    "location": {"forms": ("choice",), "kind": "word",
                 "target": "block.location",
                 "unit": None, "bounds": None},
    "weather_date": {"forms": ("uniform_dates",), "kind": "date",
                     "target": "spec.weather_date", "unit": None,
                     "bounds": None},
    "hour_local": {"forms": ("uniform", "choice", "normal"), "kind": "number",
                   "target": "block.hour_local", "unit": "h",
                   "bounds": (0.0, 24.0), "words": tuple(HOUR_WINDOWS)},
    "visibility_km": {"forms": ("lognormal", "uniform", "loguniform", "normal"),
                      "kind": "number", "target": "block.visibility_km",
                      "unit": "km", "bounds": (0.05, 400.0)},
    "cloud_cover": {"forms": ("beta", "uniform"), "kind": "number",
                    "target": "block.cloud_cover", "unit": "fraction",
                    "bounds": (0.0, 1.0)},
    "cloud_base_m": {"forms": ("uniform", "loguniform", "normal", "lognormal"),
                     "kind": "number", "target": "block.cloud_base_m",
                     "unit": "m", "bounds": (0.0, 20000.0)},
    "precipitation": {"forms": ("choice",), "kind": "word",
                      "target": "block.precipitation", "unit": None,
                      "bounds": None, "words": PRECIPITATION_WORDS},
    "wind_speed_kt": {"forms": ("weibull", "uniform", "lognormal", "normal"),
                      "kind": "number", "target": "spec.wind_speed",
                      "unit": "kt", "bounds": (0.0, 200.0)},
    "wind_direction_deg": {"forms": ("uniform", "choice", "normal"),
                           "kind": "number", "target": "spec.wind_direction",
                           "unit": "deg", "bounds": (0.0, 360.0)},
    "turbulence": {"forms": ("choice",), "kind": "word",
                   "target": "spec.turbulence", "unit": None, "bounds": None,
                   "words": tuple(TURBULENCE_LEVELS)},
    "surface": {"forms": ("choice",), "kind": "word", "target": "spec.surface",
                "unit": None, "bounds": None,
                "words": ("grassland", "desert", "forest", "city", "ocean")},
    "aircraft": {"forms": ("choice",), "kind": "word",
                 "target": "spec.aircraft", "unit": None, "bounds": None},
    "livery": {"forms": ("choice",), "kind": "word", "target": "block.livery",
               "unit": None, "bounds": None},
    "traffic_count": {"forms": ("poisson", "choice", "uniform"),
                      "kind": "integer", "target": "block.traffic_count",
                      "unit": "dimensionless", "bounds": (0, 2)},
}
#: The ``cameras`` group: applied to EVERY camera of the spec.
POLICY_CAMERA_LEAVES: Dict[str, Dict[str, Any]] = {
    "preset": {"forms": ("choice",), "kind": "word", "unit": None,
               "bounds": None,
               "words": ("chase", "ground", "wingman", "tower", "cockpit")},
    "focal_length_mm": {"forms": ("loguniform", "uniform", "normal",
                                  "lognormal"),
                        "kind": "number", "unit": "mm", "bounds": (1.0, 2000.0)},
    "offset_jitter_m": {"forms": ("normal", "uniform"), "kind": "number",
                        "unit": "m", "bounds": (-500.0, 500.0)},
}
POLICY_GROUPS = ("cameras",)
_GATE = re.compile(r"^\s*([a-z_]+)\s*(>=|<=|==|!=|>|<)\s*([-+]?\d+(?:\.\d+)?|[a-z_]+)\s*$")


def _draw(rng: np.random.Generator, leaf: Dict[str, Any]) -> Any:
    """One value from a distribution leaf (validated for shape by
    core.scenario.validate.policy_problems before this runs)."""
    if "choice" in leaf:
        options = list(leaf["choice"])
        weights = leaf.get("weights")
        if weights is not None:
            total = float(sum(weights))
            p = [float(w) / total for w in weights]
            return options[int(rng.choice(len(options), p=p))]
        return options[int(rng.integers(0, len(options)))]
    if "uniform" in leaf:
        lo, hi = leaf["uniform"]
        return float(rng.uniform(float(lo), float(hi)))
    if "loguniform" in leaf:
        lo, hi = leaf["loguniform"]
        return float(math.exp(rng.uniform(math.log(float(lo)), math.log(float(hi)))))
    if "normal" in leaf:
        arg = leaf["normal"]
        return float(arg.get("mean", 0.0)) + float(arg["sigma"]) * float(rng.standard_normal())
    if "lognormal" in leaf:
        arg = leaf["lognormal"]
        return float(arg["median"]) * math.exp(float(arg["sigma"]) * float(rng.standard_normal()))
    if "beta" in leaf:
        a, b = leaf["beta"]
        return float(rng.beta(float(a), float(b)))
    if "weibull" in leaf:
        arg = leaf["weibull"]
        return float(arg["lambda"]) * float(rng.weibull(float(arg["k"])))
    if "poisson" in leaf:
        value = int(rng.poisson(float(leaf["poisson"])))
        return min(value, int(leaf["max"])) if "max" in leaf else value
    if "uniform_dates" in leaf:
        from datetime import date, timedelta

        lo, hi = (date.fromisoformat(v) for v in leaf["uniform_dates"])
        return (lo + timedelta(days=int(rng.integers(0, (hi - lo).days + 1)))).isoformat()
    raise ValueError(f"no distribution in {sorted(leaf)}")


def _clip(value: Any, leaf: Dict[str, Any]) -> Any:
    clip = leaf.get("clip")
    if clip is None or not isinstance(value, (int, float)):
        return value
    return min(max(value, clip[0]), clip[1])


def _distribution_of(leaf: Dict[str, Any]) -> Dict[str, Any]:
    """The leaf as recorded in a sampled field's detail (JSON-plain)."""
    return json.loads(json.dumps(leaf))


def _gate_open(gate: str, drawn: Dict[str, Any], path: str) -> bool:
    """``"cloud_cover > 0.6"`` against this attempt's drawn values; a
    gate naming an undrawn leaf refuses the policy by name."""
    m = _GATE.match(str(gate))
    if m is None:
        raise RandomizationError(
            "randomization.policy",
            f"{path}: gated_by {gate!r} is not '<leaf> <op> <value>'")
    name, op, rhs = m.groups()
    if name not in drawn:
        raise RandomizationError(
            "randomization.policy",
            f"{path}: gated_by names {name!r}, which is not a leaf drawn "
            f"before it in this policy (order the gated leaf after it)")
    lhs = drawn[name]
    try:
        rhs_value: Any = float(rhs)
        lhs = float(lhs)
    except (TypeError, ValueError):
        rhs_value = rhs
    return {">": lhs > rhs_value, ">=": lhs >= rhs_value, "<": lhs < rhs_value,
            "<=": lhs <= rhs_value, "==": lhs == rhs_value,
            "!=": lhs != rhs_value}[op]


def _leaf_forms(leaf: Dict[str, Any]) -> List[str]:
    return [k for k in ("choice", "uniform", "loguniform", "normal", "lognormal",
                        "beta", "weibull", "poisson", "uniform_dates") if k in leaf]


def _check_leaf_semantics(path: str, spec_entry: Dict[str, Any],
                          leaf: Dict[str, Any]) -> None:
    forms = _leaf_forms(leaf)
    if len(forms) != 1 or forms[0] not in spec_entry["forms"]:
        raise RandomizationError(
            "randomization.policy",
            f"{path}: this leaf admits {list(spec_entry['forms'])}, not "
            f"{forms}")
    words = spec_entry.get("words")
    if "choice" in leaf and words is not None:
        bad = [v for v in leaf["choice"] if v not in words]
        if bad:
            raise RandomizationError(
                "randomization.policy",
                f"{path}: choice {bad} is outside the vocabulary "
                f"{list(words)}")


def _sampled(value: Any, unit: Optional[str], frm: str, leaf_path: str,
             leaf: Dict[str, Any], seed: int, draw_index: int,
             std: Optional[str] = None, **extra) -> Quantity:
    """A Source.SAMPLED Quantity with the contract's detail."""
    return Quantity(value=value, unit=unit, source=Source.SAMPLED, frm=frm,
                    std=std,
                    detail={"policy": leaf_path,
                            "distribution": _distribution_of(leaf),
                            "seed": int(seed), "draw_index": int(draw_index),
                            **extra})


def _stated(q: Quantity) -> bool:
    return q.source not in PLANNABLE and q.source != Source.SAMPLED


def _refuse_stated_target(path: str, field: str, q: Quantity) -> None:
    raise RandomizationError(
        "randomization.policy",
        f"{path} would move {field}, which is {q.source.value}-stated "
        f"({q.value!r}); a stated value is never moved by a draw -- drop "
        f"the leaf or the statement")


def _location_choices(path: str, names: List[str]) -> List[str]:
    """Bake keys for a location choice: a bake key stands for itself, a
    range name for the bakes in it; a range with no bake, or an unknown
    name, refuses ``randomization.location`` by name."""
    from ..terrain.glo30 import LOCATIONS

    keys: List[str] = []
    for name in names:
        word = str(name).lower().replace(" ", "_")
        if word in LOCATIONS:
            keys.append(word)
        elif word in LOCATION_RANGES:
            if not LOCATION_RANGES[word]:
                raise RandomizationError(
                    "randomization.location",
                    f"{path}: no terrain bake in core.terrain.glo30.LOCATIONS "
                    f"lies in the {word.replace('_', ' ')}; the scene cannot "
                    f"be varied over it until one is baked and listed")
            keys.extend(LOCATION_RANGES[word])
        else:
            raise RandomizationError(
                "randomization.location",
                f"{path}: {name!r} is neither a terrain bake "
                f"({sorted(LOCATIONS)}) nor a listed range "
                f"({sorted(LOCATION_RANGES)})")
    return keys


class _DrawRefused(RandomizationError):
    """A refusal that belongs to ONE draw (recorded, re-drawn); the
    policy-level RandomizationError is final."""


def _apply_leaf(spec, path: str, name: str, leaf: Dict[str, Any], value: Any,
                seed: int, draw_index: int, config_dir: Optional[Path],
                gated: Optional[str] = None) -> None:
    """Write one drawn value to its field(s), Source.SAMPLED. ``gated``
    is the shut gate that made this the leaf's first choice."""
    block = spec.randomization
    entry = POLICY_LEAVES[name]
    unit = entry["unit"]
    frm = f"drawn by {path} ({_leaf_forms(leaf)[0]}), draw {draw_index}"
    extra: Dict[str, Any] = {}
    if gated is not None:
        frm = f"{path}: gate {gated!r} shut, first choice {value!r}"
        extra["gated"] = gated
    if entry["kind"] == "number" and not isinstance(value, str):
        value = round(float(value), 4)
    elif entry["kind"] == "integer":
        value = int(round(float(value)))
    bounds = entry["bounds"]
    if bounds is not None and not isinstance(value, str) \
            and not (bounds[0] <= value <= bounds[1]):
        raise _DrawRefused(
            "randomization.policy",
            f"{path} drew {value!r}, outside the leaf's bounds {bounds}")
    target = entry["target"]
    if target.startswith("block."):
        field = target[len("block."):]
        if _stated(getattr(block, field)):
            _refuse_stated_target(path, f"randomization.{field}",
                                  getattr(block, field))
    else:
        field = target[len("spec."):]
        if _stated(getattr(spec, field)):
            _refuse_stated_target(path, field, getattr(spec, field))

    if name == "location":
        from ..nl.llm_compiler import LOCATION_TERRAIN_ELEVATION_M
        from ..terrain.glo30 import LOCATIONS

        place = LOCATIONS[value]
        old_terrain = float(spec.terrain_elevation.value)
        for field, number, u in (("latitude", place.origin_lat, "deg"),
                                 ("longitude", place.origin_lon, "deg"),
                                 ("terrain_elevation",
                                  LOCATION_TERRAIN_ELEVATION_M[value], "m")):
            if _stated(getattr(spec, field)):
                _refuse_stated_target(path, field, getattr(spec, field))
            setattr(spec, field, _sampled(
                float(number), u, f"{frm}: {value} ({place.title})",
                path, leaf, seed, draw_index))
        # The draw moved the ground; a DEFAULTED altitude keeps its height
        # above it (a recorded plan; a stated altitude never moves and
        # validate() then judges the clearance by name).
        new_terrain = float(spec.terrain_elevation.value)
        if spec.altitude.source in PLANNABLE and new_terrain != old_terrain:
            height = float(spec.altitude.value) - old_terrain
            spec.plan("altitude", round(new_terrain + height, 1),
                      frm=f"{height:g} m above the ground {path} drew "
                          f"({value}: {new_terrain:g} m)")
        block.location = _sampled(value, None, frm, path, leaf, seed, draw_index)
        return
    if name == "weather_date":
        from datetime import date

        day = date.fromisoformat(value)
        for field, number, u in (("year", day.year, "year"),
                                 ("day_of_year", day.timetuple().tm_yday, "day")):
            q = getattr(block, field)
            if _stated(q):
                if q.value != number:
                    _refuse_stated_target(path, f"randomization.{field}", q)
                continue            # stated and equal: left as stated
            setattr(block, field, _sampled(number, u, f"{frm}: {value}",
                                           path, leaf, seed, draw_index))
        spec.weather_date = _sampled(value, None, frm, path, leaf, seed,
                                     draw_index)
        return
    if name == "hour_local":
        if isinstance(value, str):
            lo, hi = HOUR_WINDOWS[value]
            rng, _ = policy_stream(seed, draw_index, 0, f"{path}:window")
            hour = round(float(rng.uniform(lo, hi)), 4)
            frm = f"{frm}: window {value!r} = {lo:g}-{hi:g} h local"
        else:
            hour = float(value)
        if _stated(block.hour_utc):
            _refuse_stated_target(path, "randomization.hour_utc", block.hour_utc)
        block.hour_local = _sampled(hour, "h", frm, path, leaf, seed, draw_index)
        utc = round((hour - float(spec.longitude.value) / DEGREES_PER_HOUR) % 24.0, 4)
        block.hour_utc = _sampled(
            utc, "h", f"{frm}; hour_utc = (hour_local - longitude / "
                      f"{DEGREES_PER_HOUR:g}) mod 24 (local mean time)",
            path, leaf, seed, draw_index)
        return
    if name == "visibility_km":
        if _stated(block.fog_density):
            _refuse_stated_target(path, "randomization.fog_density",
                                  block.fog_density)
        block.visibility_km = _sampled(value, "km", frm, path, leaf, seed,
                                       draw_index)
        beta = weather_visuals.fog_extinction_per_m(value)
        block.fog_density = _sampled(
            float(f"{beta:.6g}"), "1/m",
            f"{frm}; Koschmieder beta = {weather_visuals.KOSCHMIEDER_CONSTANT}"
            f" / (1000 V) (core.scene.weather_visuals)",
            path, leaf, seed, draw_index)
        return
    if name == "turbulence":
        spec.turbulence = _sampled(value, None, frm, path, leaf, seed,
                                   draw_index, std=TURBULENCE_STD,
                                   W20_kt=TURBULENCE_LEVELS[value])
        return
    if name == "livery":
        variants = declared_liveries(str(spec.aircraft.value), config_dir)
        if value != DEFAULT_LIVERY and value not in variants:
            raise RandomizationError(
                "randomization.livery",
                f"{path}: {spec.aircraft.value} declares liveries {variants}; "
                f"{value!r} is not one of them")
    setattr(block if target.startswith("block.") else spec, field,
            _sampled(value, unit, frm, path, leaf, seed, draw_index, **extra))


def _note_stated_camera(spec, leaf_path: str, camera_id: str, field: str,
                        q: Quantity) -> None:
    """The Phase 10 jitter's rule for the cameras group: a stated camera
    field is never moved by a draw -- skipped, and the skip is noted
    (a named view stays the view that was named)."""
    note = (f"randomization: {leaf_path} not drawn -- camera {camera_id!r} "
            f"field {field} is {q.source.value}-stated ({q.value!r})")
    if note not in spec.notes:
        spec.notes.append(note)


def _apply_camera_leaf(spec, path: str, name: str, leaf: Dict[str, Any],
                       draw_index: int, attempt: int, seed_base: int) -> None:
    """A cameras-group leaf, applied to EVERY camera with its own stream;
    a camera's stated field is skipped with a note, never moved."""
    from .camera import CameraSpec

    entry = POLICY_CAMERA_LEAVES[name]
    for camera in spec.cameras:
        camera_id = str(camera.camera_id.value)
        leaf_path = f"{path}[{camera_id}]"
        rng, seed = policy_stream(seed_base, draw_index, attempt, leaf_path)
        value = _clip(_draw(rng, leaf), leaf)
        if entry["kind"] == "number":
            value = round(float(value), 4)
        bounds = entry["bounds"]
        if bounds is not None and not (bounds[0] <= value <= bounds[1]):
            raise _DrawRefused(
                "randomization.policy",
                f"{leaf_path} drew {value!r}, outside the leaf's bounds {bounds}")
        frm = f"drawn by {leaf_path} ({_leaf_forms(leaf)[0]}), draw {draw_index}"
        if name == "preset":
            if _stated(camera.preset):
                _note_stated_camera(spec, leaf_path, camera_id, "preset",
                                    camera.preset)
                continue
            fresh = CameraSpec.defaulted(
                camera_id=camera_id, preset=value,
                aircraft=str(spec.aircraft.value),
                terrain_elevation_m=float(spec.terrain_elevation.value),
                frm=f"documented default of the drawn preset {value!r}")
            # The drawn preset's documented placement replaces the
            # previous preset's DEFAULTED placement; stated fields stay.
            for field, q in camera.quantities():
                if field in ("camera_id", "preset"):
                    continue
                if q.source == Source.DEFAULT and JITTER_BASE_KEY not in q.detail:
                    setattr(camera, field, getattr(fresh, field))
            camera.preset = _sampled(value, None, frm, leaf_path, leaf, seed,
                                     draw_index)
        elif name == "focal_length_mm":
            if _stated(camera.focal_length_mm):
                _note_stated_camera(spec, leaf_path, camera_id, "focal_length_mm",
                                    camera.focal_length_mm)
                continue
            camera.focal_length_mm = _sampled(value, "mm", frm, leaf_path, leaf,
                                              seed, draw_index)
        elif name == "offset_jitter_m":
            if str(camera.position_mode.value) != "offset":
                continue            # nothing to jitter on a world-anchored camera
            for k, field in enumerate(("offset_forward_m", "offset_right_m",
                                       "offset_up_m")):
                q = getattr(camera, field)
                if _stated(q):
                    _note_stated_camera(spec, leaf_path, camera_id, field, q)
                    continue        # the Phase 10 jitter's rule: stated stays
                axis_rng, axis_seed = policy_stream(
                    seed_base, draw_index, attempt, f"{leaf_path}:{field}")
                delta = round(float(_clip(_draw(axis_rng, leaf), leaf)), 4)
                base = float(q.detail.get(JITTER_BASE_KEY, q.value))
                setattr(camera, field, _sampled(
                    round(base + delta, 4), "m",
                    f"{base:g} {delta:+.4f} m, {frm}", leaf_path, leaf,
                    axis_seed, draw_index, **{JITTER_BASE_KEY: base}))


def _apply_fixed(spec, path: str, name: str, value: Any) -> None:
    """A top-level fixed scalar (``sun_elevation_min_deg: 2``) sets the
    block's range field of that name."""
    block = spec.randomization
    if name not in RandomizationSpec.RANGE_FIELDS:
        raise RandomizationError(
            "randomization.policy",
            f"{path}: a fixed value may set a range field "
            f"{list(RandomizationSpec.RANGE_FIELDS)}, not {name!r}")
    q = getattr(block, name)
    if _stated(q):
        if q.value != value:
            _refuse_stated_target(path, f"randomization.{name}", q)
        return
    block.plan(name, value, frm=f"fixed by {path}")


def _policy_attempt(spec, policy: Dict[str, Any], seed_base: int,
                    draw_index: int, attempt: int,
                    config_dir: Optional[Path],
                    drawn: Dict[str, Any]) -> Dict[str, Any]:
    """Apply every leaf of one attempt to ``spec`` (a private copy),
    filling ``drawn`` as it goes. Raises _DrawRefused for a refused draw
    and RandomizationError for a policy the machine cannot honour."""
    for name, leaf in policy.items():
        path = f"randomization.policy.{name}"
        if isinstance(leaf, (int, float, str)) and not isinstance(leaf, bool):
            _apply_fixed(spec, path, name, leaf)
            continue
        if name in POLICY_GROUPS:
            if name == "cameras":
                for sub, sub_leaf in leaf.items():
                    if sub not in POLICY_CAMERA_LEAVES:
                        raise RandomizationError(
                            "randomization.policy",
                            f"{path}.{sub}: the cameras group samples "
                            f"{list(POLICY_CAMERA_LEAVES)}, not {sub!r}")
                    _check_leaf_semantics(f"{path}.{sub}",
                                          POLICY_CAMERA_LEAVES[sub], sub_leaf)
                    _apply_camera_leaf(spec, f"{path}.{sub}", sub, sub_leaf,
                                       draw_index, attempt, seed_base)
            continue
        if name not in POLICY_LEAVES:
            raise RandomizationError(
                "randomization.policy",
                f"{path}: no field this build samples is called {name!r}; "
                f"the leaves are {sorted(POLICY_LEAVES)} and the group "
                f"{list(POLICY_GROUPS)}")
        _check_leaf_semantics(path, POLICY_LEAVES[name], leaf)
        if "gated_by" in leaf and not _gate_open(leaf["gated_by"], drawn, path):
            # The gate is shut: a choice leaf takes its first choice (the
            # documented "off" value -- "none" for precipitation), any
            # other leaf is not drawn; both recorded.
            if "choice" in leaf:
                value = leaf["choice"][0]
                drawn[name] = value
                _apply_leaf(spec, path, name, leaf, value, 0, draw_index,
                            config_dir, gated=str(leaf["gated_by"]))
            continue
        if name == "location":
            keys = _location_choices(path, list(leaf["choice"]))
            rng2, seed = policy_stream(seed_base, draw_index, attempt, path)
            weights = leaf.get("weights")
            if weights is not None:
                # weights are per NAMED entry; expand to the bakes each names
                expanded: List[float] = []
                for entry_name, w in zip(leaf["choice"], weights):
                    bakes = _location_choices(path, [entry_name])
                    expanded.extend([float(w) / len(bakes)] * len(bakes))
                total = sum(expanded)
                value = keys[int(rng2.choice(len(keys), p=[w / total for w in expanded]))]
            else:
                value = keys[int(rng2.integers(0, len(keys)))]
        else:
            rng, seed = policy_stream(seed_base, draw_index, attempt, path)
            value = _clip(_draw(rng, leaf), leaf)
        drawn[name] = value
        _apply_leaf(spec, path, name, leaf, value, seed, draw_index, config_dir)
    return drawn


def _new_violations(spec, baseline: set, check_feasibility: bool) -> List[str]:
    """Names of the violations a candidate carries that the un-drawn
    spec did not (validate() is the gate; imported here because
    validate imports the spec)."""
    from .validate import validate

    report = validate(spec, check_feasibility=check_feasibility)
    return sorted({v.constraint for v in report.violations} - baseline)


def enable_for_policy(spec, frm: str) -> None:
    """A stated policy switches the block on, as an INFERRED value
    quoting the phrase (the compilers) -- unless it is already on."""
    block = spec.randomization
    if block.is_enabled():
        return
    if _stated(block.enabled):
        raise RandomizationError(
            "randomization.policy",
            f"randomization.policy is stated but randomization.enabled is "
            f"{block.enabled.source.value}-stated false; drop one")
    block.enabled = Quantity.inferred(True, frm=frm)


def _sample_policy(spec, config_dir: Optional[Path], draw_index: int,
                   check_feasibility: bool) -> None:
    """The policy stage: up to MAX_POLICY_ATTEMPTS attempts, each a
    private copy of the spec that is committed only when validate()
    accepts it; every refused attempt is recorded."""
    policy_q = spec.randomization_policy
    if policy_q is None:
        return
    block = spec.randomization
    if block.policy_draws.source == Source.SAMPLED:
        return                      # drawn already: value-idempotent
    policy = policy_q.value
    if not isinstance(policy, dict):
        raise RandomizationError("randomization.policy",
                                 "randomization.policy is not a mapping")
    from copy import deepcopy

    from .validate import policy_problems

    problems = policy_problems(policy)
    if problems:
        raise RandomizationError(
            "randomization.policy",
            "randomization.policy is not of the documented form: "
            + "; ".join(problems))
    seed_base = int(block.seed.value)
    baseline = set(_new_violations(spec, set(), check_feasibility))
    refused: List[Dict[str, Any]] = []
    for attempt in range(MAX_POLICY_ATTEMPTS):
        candidate = deepcopy(spec)
        drawn: Dict[str, Any] = {}
        try:
            _policy_attempt(candidate, policy, seed_base, draw_index, attempt,
                            config_dir, drawn)
            _sample_phase10_leaves(candidate, config_dir)
            names = _new_violations(candidate, baseline, check_feasibility)
            if names:
                raise _DrawRefused(names[0], "refused by validate(): "
                                   + ", ".join(names))
        except RandomizationError as exc:
            if not (isinstance(exc, _DrawRefused) or exc.constraint in (
                    "randomization.time_of_day", "randomization.livery")):
                raise               # a policy defect is final, not a re-draw
            # A refused draw is COUNTED, then re-drawn (never dropped).
            refused.append({"draw_index": int(draw_index), "attempt": attempt,
                            "refusal_name": exc.constraint,
                            "message": exc.message,
                            "sampled_values": _plain(drawn)})
            continue
        candidate.randomization.policy_draws = Quantity(
            value={"draw_index": int(draw_index), "attempts": attempt + 1,
                   "max_attempts": MAX_POLICY_ATTEMPTS, "refused": refused,
                   "seed_derivation": POLICY_SEED_DERIVATION,
                   "campaign_seed": seed_base},
            source=Source.SAMPLED,
            frm=f"{attempt + 1} attempt(s), {len(refused)} refused")
        spec.__dict__.update(candidate.__dict__)
        return
    raise RandomizationError(
        "randomization.infeasible",
        f"{len(refused)} of {MAX_POLICY_ATTEMPTS} draws of "
        f"randomization.policy were refused ("
        f"{sorted({r['refusal_name'] for r in refused})}); the slot "
        f"(draw {draw_index}, seed {seed_base}) cannot be met -- narrow the "
        f"policy",
        detail={"refused": len(refused), "draws": MAX_POLICY_ATTEMPTS,
                "draw_index": int(draw_index), "refusals": refused})


def _plain(values: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(values, default=str))


def _sample_phase10_leaves(spec, config_dir: Optional[Path]) -> None:
    """The Phase 10 leaves (time of day, fog, livery, camera jitter):
    exactly the streams and outputs they always had."""
    block = spec.randomization
    seed = int(block.seed.value)
    _sample_time_of_day(spec, block, seed)
    _sample_fog(block, seed)
    _sample_livery(spec, block, seed, config_dir)
    for camera in spec.cameras:
        _jitter_camera(spec, camera, seed, block)


def sample_randomization(spec, config_dir: Optional[Path] = None,
                         draw_index: Optional[int] = None,
                         check_feasibility: bool = True) -> None:
    """The planner. No-op when the block is off; otherwise every draw
    is made from the block's seed and written back as ``derived``
    (the Phase 10 leaves) or ``sampled`` (the policy's).
    Value-idempotent: a second pass draws the same numbers.

    ``draw_index`` is the campaign's case index (0 for a single run;
    the recorded one on a second pass); ``check_feasibility`` runs the
    trim check on every policy draw (validate()'s definitive answer;
    a fraction of a second each).
    """
    policy_q = spec.randomization_policy
    if policy_q is not None and policy_q.detail.get("unmapped"):
        # The compiler recorded a variation the vocabulary cannot express
        # (contracts §5.3): refused by name, sentence quoted, on every
        # surface that samples -- never silently defaulted.
        sentences = list(policy_q.detail["unmapped"])
        raise RandomizationError(
            "randomization.vocabulary",
            "the prompt asks for a variation the vocabulary cannot express: "
            + "; ".join(f'"{s}"' for s in sentences)
            + " -- the documented phrases are varied weather, different "
              "times of day, dawn and dusk only, varied lighting, across the "
              "<range>, mixed traffic, random viewpoints")
    block = spec.randomization
    from copy import copy

    untouched = copy(spec.__dict__)
    untouched_block = copy(block.__dict__)
    if policy_q is not None and not block.is_enabled():
        if _stated(block.enabled):
            raise RandomizationError(
                "randomization.policy",
                f"randomization.policy is stated but randomization.enabled "
                f"is {block.enabled.source.value}-stated false; drop one")
        block.plan("enabled", True, frm="a stated randomization.policy "
                                        "switches the block on")
    if not block.is_enabled():
        return
    if block.seed.source in PLANNABLE and int(block.seed.value) == 0:
        block.plan("seed", derive_block_seed(int(spec.seed.value)),
                   frm=f"derived from run seed {int(spec.seed.value)}: "
                       f"sha256('<run seed>:randomization') mod {MAX_SEED}")
    if policy_q is not None:
        if draw_index is None:
            recorded = block.policy_draws.value
            draw_index = int(recorded["draw_index"]) if isinstance(recorded, dict) else 0
        try:
            _sample_policy(spec, config_dir, int(draw_index), check_feasibility)
        except RandomizationError:
            # A refusal is not a run: the spec is exactly as it was
            # given (the block's switch and seed plans above included).
            spec.__dict__.clear()
            spec.__dict__.update(untouched)
            block.__dict__.clear()
            block.__dict__.update(untouched_block)
            raise
    _sample_phase10_leaves(spec, config_dir)


# -- what the render and the record take ---------------------------------

def _sampled_policy_values(spec) -> Dict[str, Any]:
    """{leaf: value} for every block leaf the policy drew."""
    block = spec.randomization
    out: Dict[str, Any] = {}
    for name in RandomizationSpec.POLICY_FIELDS:
        if name == "policy_draws":
            continue
        q = getattr(block, name)
        if q.source == Source.SAMPLED:
            out[name] = q.value
    return out


def render_look(spec) -> Optional[Dict[str, Any]]:
    """The commandlet's look flags from the sampled block, or None when
    the block is off (the harness's own look then applies, byte for
    byte). Refuses an enabled block nobody sampled: a render must not
    guess a sun. The four Phase 10 keys are unchanged; the spec-8 look
    rows (core.scene.weather_visuals) are added beside them."""
    block = spec.randomization
    if not block.is_enabled():
        return None
    if not block.is_sampled():
        raise RandomizationError(
            "randomization.unsampled",
            "the randomization block is enabled but not sampled; run the "
            "planners (sample_randomization) before rendering")
    look: Dict[str, Any] = {
        "sun_elev": float(block.sun_elevation_deg.value),
        "sun_azim": engine_sun_azimuth(float(block.sun_azimuth_deg.value)),
        "exposure_bias": float(block.exposure_bias.value),
        "fog_density": float(block.fog_density.value),
    }
    sampled = _sampled_policy_values(spec)
    values: Dict[str, Any] = {
        "fog_density": look["fog_density"],
        "precipitation": sampled.get("precipitation", "none"),
        "cloud_cover": sampled.get("cloud_cover", 0.0),
        "wind_speed_kt": float(spec.wind_speed.value),
        "wind_direction_deg": float(spec.wind_direction.value),
        "exposures": {str(c.camera_id.value): (float(c.exposure.aperture_f.value),
                                              float(c.exposure.shutter_s.value),
                                              float(c.exposure.iso.value))
                      for c in spec.cameras},
    }
    if "visibility_km" in sampled:
        values["visibility_km"] = float(sampled["visibility_km"])
    if "cloud_base_m" in sampled:
        values["cloud_base_m"] = float(sampled["cloud_base_m"])
    look.update(weather_visuals.look_block(values))
    look["sun_elevation_deg"] = look["sun_elev"]
    look["sun_azimuth_deg"] = float(block.sun_azimuth_deg.value)
    look["engine_sun_azimuth_deg"] = look["sun_azim"]
    return look


def card_block(spec) -> Optional[Dict[str, Any]]:
    """The sampled values for the run card and the manifest: every
    number the render was given, in both conventions, plus each camera
    field the jitter moved and by how much, one entry per sampled
    policy leaf, the draw record and the full ``look`` block."""
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
    out: Dict[str, Any] = {
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
    if spec.randomization_policy is not None:
        out.update(_sampled_policy_values(spec))
        for name in ("wind_speed", "wind_direction", "turbulence", "surface",
                     "aircraft", "weather_date"):
            q = getattr(spec, name)
            if q.source == Source.SAMPLED:
                out[POLICY_LEAF_OF_SPEC_FIELD[name]] = q.value
        if isinstance(block.policy_draws.value, dict):
            out["policy_draws"] = _plain(block.policy_draws.value)
        out["policy"] = _plain(spec.randomization_policy.value)
        out[weather_visuals.CARD_LOOK_KEY] = look
    return out


#: Spec field -> the policy leaf that samples it (the record's key).
POLICY_LEAF_OF_SPEC_FIELD = {
    entry["target"][5:]: name for name, entry in POLICY_LEAVES.items()
    if entry["target"].startswith("spec.")}


# -- the realised distribution (contracts §5.5) ------------------------------

def _load_run_block(run) -> Optional[Dict[str, Any]]:
    """The manifest-shaped record of one run: a dict as given, or the
    run directory's capture_manifest.json."""
    if isinstance(run, dict):
        return run
    path = Path(run)
    if path.is_dir():
        path = path / "capture_manifest.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _requested_support(leaf: Any) -> Optional[tuple]:
    """[lo, hi] a numeric leaf is asked to cover, when it states one."""
    if not isinstance(leaf, dict):
        return None
    if "clip" in leaf:
        return float(leaf["clip"][0]), float(leaf["clip"][1])
    for form in ("uniform", "loguniform"):
        if form in leaf:
            return float(leaf[form][0]), float(leaf[form][1])
    if "beta" in leaf:
        return 0.0, 1.0
    return None


def realised_distribution(runs, policy: Optional[Dict[str, Any]] = None,
                          k: int = 1, bins: int = 8) -> Dict[str, Any]:
    """Histograms of every sampled field over the FRAMES that exported,
    beside the requested distribution, with ``coverage`` = the fraction
    of policy bins holding at least ``k`` frames (contracts §5.5).

    ``runs``: run directories (their ``capture_manifest.json``) or
    manifest-shaped dicts; each contributes its ``randomization`` block
    (the card block above) weighted by its frame count (``frames``: a
    list or an integer). ``policy``: the requested leaves (taken from
    the first run's ``randomization.policy`` record when absent).
    Refusals are counted from each run's ``policy_draws``.
    """
    per_leaf: Dict[str, Dict[Any, int]] = {}
    refusals: Dict[str, int] = {}
    n_runs = n_frames = 0
    requested = dict(policy or {})
    for run in runs:
        record = _load_run_block(run)
        if record is None:
            continue
        block = record.get("randomization")
        if not isinstance(block, dict):
            continue
        frames = record.get("frames", 1)
        weight = len(frames) if isinstance(frames, list) else int(frames)
        n_runs += 1
        n_frames += weight
        if not requested and isinstance(block.get("policy"), dict):
            requested = dict(block["policy"])
        for name in list(POLICY_LEAVES) + [f"cameras.{n}" for n in POLICY_CAMERA_LEAVES]:
            if name in block:
                per_leaf.setdefault(name, {})
                per_leaf[name][block[name]] = per_leaf[name].get(block[name], 0) + weight
        draws = block.get("policy_draws")
        if isinstance(draws, dict):
            for refused in draws.get("refused", []):
                name = str(refused.get("refusal_name"))
                refusals[name] = refusals.get(name, 0) + 1
    fields: Dict[str, Any] = {}
    coverages: List[float] = []
    for name, counts in sorted(per_leaf.items()):
        leaf = requested.get(name)
        numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool)
                      for v in counts)
        if numeric and counts:
            support = _requested_support(leaf) or (min(counts), max(counts))
            lo, hi = support
            width = (hi - lo) / bins if hi > lo else 1.0
            hist = {f"{lo + i * width:g}..{lo + (i + 1) * width:g}": 0
                    for i in range(bins)}
            labels = list(hist)
            for value, n in counts.items():
                i = int((float(value) - lo) / width) if hi > lo else 0
                i = min(max(i, 0), bins - 1)
                hist[labels[i]] += n
            expected_bins = labels
        else:
            hist = {str(v): n for v, n in sorted(counts.items(), key=lambda kv: str(kv[0]))}
            expected_bins = ([str(v) for v in leaf["choice"]]
                             if isinstance(leaf, dict) and "choice" in leaf
                             else list(hist))
            if name == "location" and isinstance(leaf, dict) and "choice" in leaf:
                # a range name stands for the bakes in it: those are the bins
                try:
                    expected_bins = list(dict.fromkeys(
                        _location_choices("realised", list(leaf["choice"]))))
                except RandomizationError:
                    pass
            for label in expected_bins:
                hist.setdefault(label, 0)
        covered = sum(1 for label in expected_bins if hist.get(label, 0) >= k)
        coverage = covered / len(expected_bins) if expected_bins else 0.0
        if leaf is not None:
            coverages.append(coverage)
        fields[name] = {"histogram": hist, "requested": leaf,
                        "bins": len(expected_bins), "coverage": round(coverage, 4),
                        "frames": sum(counts.values())}
    return {
        "runs": n_runs, "frames": n_frames, "k": int(k),
        "fields": fields,
        "coverage": round(sum(coverages) / len(coverages), 4) if coverages else None,
        "refusals": dict(sorted(refusals.items())),
    }
