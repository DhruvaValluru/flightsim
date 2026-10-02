"""The spec-8 blocks: ``scene``, ``taxonomy``, ``traffic[]``, and the
physics additions' ``atmosphere``, ``datum``, ``turbulence_model``,
``wind_profile``, ``loading`` and ``wake``.

Phase 2 (contracts §2.1, §2.2, §12) adds three top-level blocks to the
scenario spec. Each is serialised like the randomisation block, NOT
like the camera list: an absent block IS the documented default and is
omitted from the canonical form, so the digest of a spec that states
none of them is unchanged by construction (pinned by a test that reads
the committed version-7 examples). Every field is a provenanced
:class:`Quantity`, addressable through the spec's own ``set()`` /
``plan()`` front door (``scene.terrain_source``, ``taxonomy.classes``,
``traffic[0].range_m``), and a user-stated field is never silently
moved.

What each block means -- and what this module does NOT do:

* ``scene.terrain_source`` (``auto`` | ``flat`` | ``synthesised`` |
  ``baked``) names the terrain the flight is over. ``auto`` is exactly
  today's behaviour (the web app's ``pick_scene``; the CLI's
  ``--terrain`` / ``--synth-terrain`` flags); ``flat`` forces the spec's
  datum; ``synthesised`` synthesises the deterministic ridge centred on
  the spec's own origin; ``baked`` uses the bake ``scene.terrain`` (or
  the CLI's ``--terrain``) names and refuses by name when none is baked.
  The honouring lives in ``flightsim/capture.py`` and
  ``webapp/runs.py``; this module only carries and validates the field.
* ``taxonomy.classes`` is the ordered class list (``class_id`` =
  position + 1; 0 is reserved for sky/none). Only the list is carried
  here: object composition and the ID image are package B's.
* ``traffic[]`` states up to two scripted traffic aircraft (airframe,
  track kind, range, livery). Only the fields are carried and validated;
  no traffic is composed, flown or rendered by this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fields import PLANNABLE_SOURCES, Quantity, Source

#: The terrain sources a spec may name (contracts §12).
TERRAIN_SOURCES = ("auto", "flat", "synthesised", "baked")
#: The documented class list (contracts §2.1). ``cloud`` is a class in
#: the visibility record only: volumetrics write no ID.
DEFAULT_CLASSES = ("aircraft", "terrain", "building", "vegetation",
                   "water", "cloud")
#: The three traffic tracks that produce object-object occlusion
#: (brainstorm §3.4).
TRAFFIC_TRACKS = ("formation", "crossing", "overtaking")
#: Documented traffic defaults (contracts §2.2).
DEFAULT_TRAFFIC_RANGE_M = 400.0
DEFAULT_TRAFFIC_TRACK = "crossing"
DEFAULT_TRAFFIC_LIVERY = "default"
#: At most this many traffic entries (contracts §5.2 ``traffic_count
#: max: 2``; the render's Populate holds one FDM actor plus N scripted
#: mesh actors and two is what the occlusion checks are specified for).
MAX_TRAFFIC = 2

#: Where a "configured airframe" is declared: one JSON per airframe the
#: asset pipeline can convert and import (the same directory the
#: randomisation block reads liveries from).
CONFIG_DIR = Path(__file__).resolve().parents[2] / "assets" / "aircraft_config"

#: The atmosphere's ``day`` vocabulary (gap P1): each word is a STATED
#: choice of numbers, not a transcription of a climatic standard. A word
#: fills a numeric field only while that field is at its default; a
#: stated number always wins. ``humid`` states relative humidity (at the
#: scene's initial altitude) and leaves the temperature alone.
DAY_WORDS: Dict[str, Dict[str, float]] = {
    "isa": {},
    "isa_plus_15": {"temperature_deviation_c": 15.0},
    "isa_plus_20": {"temperature_deviation_c": 20.0},
    "hot_day": {"temperature_deviation_c": 30.0},
    "cold_day": {"temperature_deviation_c": -40.0},
    "humid": {"relative_humidity_pct": 90.0},
}
#: What each word rests on, in the spec's ``std`` field.
DAY_STANDARDS: Dict[str, str] = {
    "isa": "US Standard Atmosphere 1976 (ISA): no deviation [unverified here]",
    "isa_plus_15": "ISA +15 degC: the conventional 'hot' certification day "
                   "(a stated choice)",
    "isa_plus_20": "ISA +20 degC: the conventional 'very hot' day (a stated "
                   "choice)",
    "hot_day": "+30 degC over ISA: a stated choice inside MIL-HDBK-310's 1 % "
               "hot column as remembered [unverified here]; not the handbook's "
               "profile",
    "cold_day": "-40 degC over ISA: a stated choice for a cold day; not "
                "MIL-HDBK-310's cold profile",
    "humid": "90 % relative humidity at the scene: a stated choice for a humid "
             "day; not MIL-HDBK-310's humidity profile",
}
#: MIL-HDBK-310 named profiles: recognised so they are refused by name
#: (``atmosphere.profile``) rather than guessed, until transcribed with
#: provenance.
NAMED_PROFILES = ("mil_hdbk_310_hot", "mil_hdbk_310_cold", "mil_hdbk_310_humid",
                  "mil_hdbk_310_high_altitude")
#: The ranges the atmosphere accepts (validate.py refuses outside them):
#: temperature deviation -60..+45 degC, sea-level pressure 870..1085 hPa
#: (the recorded extremes: 870 hPa in Typhoon Tip 1979, 1085 hPa at
#: Tosontsengel 2001 [unverified here]), relative humidity 0..100 %, dew
#: point -90..60 degC (colder than any surface air on record; hotter than
#: the Magnus fit's stated range).
ATMOSPHERE_RANGES: Dict[str, tuple] = {
    "temperature_deviation_c": (-60.0, 45.0),
    "sea_level_pressure_hpa": (870.0, 1085.0),
    "relative_humidity_pct": (0.0, 100.0),
    "dew_point_c": (-90.0, 60.0),
}
#: ISA sea-level pressure in the spec's unit.
ISA_SEA_LEVEL_PRESSURE_HPA = 1013.25

#: The datum block's vocabulary (blueprint section 5, D1). ``vertical``
#: names the datum of the heights the run works in: ``orthometric`` is
#: the branch as built (GLO-30 heights are EGM2008 orthometric and are
#: fed to JSBSim unchanged); ``ellipsoidal`` is recognised so it is
#: refused by name (``datum.physics_frame_unsupported``) rather than
#: guessed. ``physics_frame`` names the frame the physics flies in:
#: ``orthometric`` (C2: the internal frame stays and is named, the geoid
#: is applied where a coordinate leaves the system) or ``ellipsoid``
#: (C3: refused by the same name until the physics frame handles it).
#: ``geoid_model`` declares which model the bake must carry (``EGM2008``
#: or ``EGM96``); null accepts the bake's own, a mismatch refuses
#: ``datum.model_mismatch`` where the spec meets the bake.
DATUM_VERTICALS = ("orthometric", "ellipsoidal")
DATUM_PHYSICS_FRAMES = ("orthometric", "ellipsoid")
DATUM_GEOID_MODELS = ("EGM2008", "EGM96")
DATUM_STANDARDS: Dict[str, str] = {
    "orthometric": "heights above the geoid (EGM2008 for GLO-30, EPSG:3855); JSBSim "
                   "h-sl carries the number unchanged and ECEF is formed at export "
                   "as altitude + undulation (WGS 84 / EGM2008 per the blueprint)",
    "ellipsoidal": "heights above the WGS 84 ellipsoid (EPSG:4979); not flown until "
                   "the physics frame handles it (refused by name)",
    "physics_frame": "the blueprint's C2: orthometric core, geoid at every ellipsoid "
                     "boundary; C3 (the ellipsoid frame) documented and refused",
    "EGM2008": "Pavlis et al. 2012 (unverified here); GeographicLib egm2008-5 grid",
    "EGM96": "Lemoine et al. 1998 (unverified here); GeographicLib egm96-15 grid",
}


#: P6: the turbulence models a spec may name. ``dryden`` is today's path
#: (JSBSim's own Dryden filters, core/environment/turbulence.py), the
#: default and absent-canonical; ``von_karman`` is the Python-realised
#: MIL-F-8785C von Karman field delivered through the gust channel
#: (core/environment/von_karman.py). Any other word refuses
#: ``turbulence.model``.
TURBULENCE_MODELS = ("dryden", "von_karman")
TURBULENCE_MODEL_STANDARDS: Dict[str, str] = {
    "dryden": "MIL-F-8785C Dryden spectra through JSBSim 1.2.4 FGWinds ttTustin "
              "(the branch's measured path)",
    "von_karman": "MIL-F-8785C 3.7.2.1 von Karman spectra, Shinozuka-Jan sum of "
                  "cosines, delivered through atmosphere/gust-*-fps [unverified here]",
}
#: P6: the wind profile kinds. ``uniform`` is today's path (the spec's
#: wind_speed / wind_direction everywhere, or the surface-class log
#: profile), the default and absent-canonical; ``layered`` states
#: ``layers`` of [altitude_m, speed_kt, direction_deg]; ``milspec`` is the
#: MIL-F-8785C 3.7.3.2 log law with W20 = the spec's wind speed and
#: ``roughness_ft`` 0.15 or 2.0; ``nwp`` names a cached ``fixture`` under
#: assets/nwp. Any other word refuses ``wind_profile.kind``.
WIND_PROFILE_KINDS = ("uniform", "layered", "milspec", "nwp")
WIND_PROFILE_STANDARDS: Dict[str, str] = {
    "uniform": "the spec's wind everywhere (the branch as built)",
    "layered": "piecewise-linear speed and direction between stated layers, held "
               "beyond the first and last (a stated interpolation)",
    "milspec": "MIL-F-8785C 3.7.3.2 log law u(h) = W20 ln(h/z0)/ln(20/z0), z0 0.15 or "
               "2.0 ft, 3 ft <= h <= 1000 ft [unverified here]",
    "nwp": "a cached NWP profile at the standard-atmosphere height of each level "
           "pressure (stated)",
}


#: P4: what each ``loading`` field rests on, in the spec's ``std`` field.
#: The stations and tanks are the loaded JSBSim model's own (the XML's
#: point masses and tanks at the XML's arms); the handbook numbers the
#: aircraft_config block carries beside them are marked there.
LOADING_STANDARDS: Dict[str, str] = {
    "payload": "JSBSim FGMassBalance point masses: inertia/pointmass-weight-lbs[i] at the "
               "XML's own arm (inertia/pointmass-location-X-inches[i]), the station named "
               "as assets/aircraft_config/<fdm>.json lists it; written once before the trim",
    "fuel_kg": "JSBSim FGTank contents: propulsion/tank[i]/contents-lbs, the stated mass "
               "shared between the tanks in proportion to their capacities (a stated fill "
               "rule); written once before the trim",
    "fuel_fraction": "JSBSim FGTank contents: every tank filled to the stated fraction of "
                     "its capacity (capacity from the XML through the aircraft_config "
                     "block); written once before the trim",
}


def configured_airframes(config_dir: Optional[Path] = None) -> List[str]:
    """Every airframe with an asset-pipeline config -- the ones a
    traffic entry may name (its mesh must be importable like the
    primary's; contracts §2.2)."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def labelled_airframes(config_dir: Optional[Path] = None) -> List[str]:
    """The configured airframes whose config carries a ``labels`` block
    (core.capture.airframe.load_airframe's requirement): the only ones
    whose frames can be labelled, as a traffic aircraft's must be. A
    traffic entry naming any other was measured to stop the headless
    capture with a traceback (DHC6, 2026-10-02) instead of a refusal."""
    import json

    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    out: List[str] = []
    for name in configured_airframes(directory):
        config = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
        if isinstance(config.get("labels"), dict):
            out.append(name)
    return out


class ProvenancedBlock:
    """A block of provenanced fields with the spec's own edit doctrine.

    Subclasses are dataclasses whose every field is a :class:`Quantity`,
    listed in ``FIELD_ORDER``; ``BLOCK`` names the block in messages and
    in ``from_dict`` refusals.
    """

    FIELD_ORDER: tuple = ()
    BLOCK = "block"

    def quantities(self):
        """(name, Quantity) in canonical order."""
        for name in self.FIELD_ORDER:
            yield name, getattr(self, name)

    def set(self, name: str, value: Any, frm: str = "edited by hand") -> None:
        """Override a field, recording that a human did it."""
        current = self._field(name)
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.USER, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def plan(self, name: str, value: Any, frm: str) -> None:
        """Move a field the SYSTEM chose. Same doctrine as the spec's,
        the camera's and the randomisation block's: only a defaulted /
        derived / model field moves; a stated one refuses by name."""
        current = self._field(name)
        if current.source not in PLANNABLE_SOURCES:
            raise ValueError(
                f"plan() only moves defaulted/derived/model fields; "
                f"{self.BLOCK}.{name} is {current.source.value!r} -- a "
                f"stated value is never silently moved")
        setattr(self, name, Quantity(value=value, unit=current.unit,
                                     source=Source.DERIVED, frm=frm,
                                     std=current.std,
                                     detail=dict(current.detail)))

    def _field(self, name: str) -> Quantity:
        if name not in self.FIELD_ORDER:
            raise ValueError(f"{name!r} is not a {self.BLOCK} field")
        return getattr(self, name)

    # -- serialisation --------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {name: q.to_dict() for name, q in self.quantities()}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        if not isinstance(data, dict):
            raise ValueError(f"spec '{cls.BLOCK}' must be a mapping of "
                             f"provenanced fields")
        kwargs = {}
        for name in cls.FIELD_ORDER:
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"{cls.BLOCK} is missing required field {name}") from exc
        unknown = set(data) - set(cls.FIELD_ORDER)
        if unknown:
            raise ValueError(
                f"{cls.BLOCK} carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        return cls(**kwargs)

    def is_default(self) -> bool:
        """The documented default, field for field, source for source
        -- the one spelling the canonical spec omits."""
        return self.to_dict() == self.defaulted().to_dict()

    @classmethod
    def defaulted(cls):
        raise NotImplementedError


@dataclass
class SceneSpec(ProvenancedBlock):
    """``scene``: where the terrain under the flight comes from."""

    terrain_source: Quantity
    #: A bake stem (as the CLI's ``--terrain``: ``<stem>.r16`` +
    #: ``.json``), required when ``terrain_source`` is ``baked``; None
    #: otherwise.
    terrain: Quantity

    #: S1: the sun's direct normal illuminance in lux the render is
    #: handed (-sun-lux=), or None = unstated (the engine's own sun, 8.0
    #: unitless today, stands; the capture manifest then carries the
    #: clear-sky model's value with provenance model). Refused
    #: ``sensing.sun_lux`` outside (0, 133 100] lx (core/scenario/solar.py).
    sun_lux: Quantity

    #: W2: the cached footprint set's key (assets/buildings/<key>.jsonl
    #: + <key>.provenance.json), or None = no buildings. Nothing is
    #: fetched; core/scene/buildings.py refuses buildings.uncached,
    #: .licence, .unverified and .ids where the capture loads it.
    buildings: Quantity

    #: W3: the night sky, a mapping {moon: on|off, stars: auto|catalogue|
    #: procedural|off, utc: optional ISO moment}, or None = no night look.
    #: core/scene/night.py computes it (look.moon, look.stars,
    #: night.sun_units refused by name there and in the validator).
    night: Quantity

    FIELD_ORDER = ("terrain_source", "terrain", "sun_lux", "buildings", "night")
    #: The fields a scene block may LEAVE OUT: each is filled from the
    #: default when absent and omitted when at it, so a block written
    #: before the field existed keeps its canonical form and digest
    #: (examples/cameras_mountain_refusal.yaml states a scene block).
    OPTIONAL_FIELDS = ("sun_lux", "buildings", "night")
    BLOCK = "scene"

    @classmethod
    def defaulted(cls) -> "SceneSpec":
        return cls(
            terrain_source=Quantity.default(
                "auto", frm="today's scene selection: the web app's "
                            "pick_scene; the CLI's --terrain / "
                            "--synth-terrain flags"),
            terrain=Quantity.default(
                None, frm="no bake stem stated; required when "
                          "terrain_source is baked"),
            sun_lux=Quantity.default(
                None, "lx", frm="no sun stated: the engine's own sun stands; the "
                                "capture manifest carries the clear-sky model's "
                                "value (source model)"),
            buildings=Quantity.default(
                None, frm="no footprint set stated: no buildings composed, no "
                          "building:all object"),
            night=Quantity.default(
                None, frm="no night sky stated: no moon light, no starfield"),
        )

    def to_dict(self) -> Dict[str, Any]:
        defaults = self.defaulted()
        out: Dict[str, Any] = {}
        for name, q in self.quantities():
            if name in self.OPTIONAL_FIELDS and q.to_dict() == getattr(defaults, name).to_dict():
                continue
            out[name] = q.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSpec":
        if not isinstance(data, dict):
            raise ValueError(f"spec '{cls.BLOCK}' must be a mapping of "
                             f"provenanced fields")
        defaults = cls.defaulted()
        kwargs = {}
        for name in cls.FIELD_ORDER:
            if name in cls.OPTIONAL_FIELDS and name not in data:
                kwargs[name] = getattr(defaults, name)
                continue
            try:
                kwargs[name] = Quantity.from_dict(data[name])
            except KeyError as exc:
                raise ValueError(
                    f"{cls.BLOCK} is missing required field {name}") from exc
        unknown = set(data) - set(cls.FIELD_ORDER)
        if unknown:
            raise ValueError(
                f"{cls.BLOCK} carries unknown fields {sorted(unknown)}; "
                f"refusing to guess at their meaning")
        return cls(**kwargs)


@dataclass
class TaxonomySpec(ProvenancedBlock):
    """``taxonomy``: the ordered class list a dataset's categories come
    from (never from what happened to be in the scene)."""

    classes: Quantity

    FIELD_ORDER = ("classes",)
    BLOCK = "taxonomy"

    @classmethod
    def defaulted(cls) -> "TaxonomySpec":
        return cls(classes=Quantity.default(
            list(DEFAULT_CLASSES), frm="the documented class list"))


@dataclass
class AtmosphereSpec(ProvenancedBlock):
    """``atmosphere``: the day the flight is in (gap P1). Every field a
    provenanced Quantity; absent-canonical (the ISA day is the default
    and is omitted from the canonical form, so a spec that states
    nothing keeps its digest). A stated dew point and a stated relative
    humidity together are refused by name at validation
    (``atmosphere.humidity_conflict``); the ranges are ATMOSPHERE_RANGES."""

    temperature_deviation_c: Quantity
    sea_level_pressure_hpa: Quantity
    dew_point_c: Quantity
    relative_humidity_pct: Quantity
    day: Quantity

    FIELD_ORDER = ("temperature_deviation_c", "sea_level_pressure_hpa",
                   "dew_point_c", "relative_humidity_pct", "day")
    BLOCK = "atmosphere"
    NUMERIC_FIELDS = ("temperature_deviation_c", "sea_level_pressure_hpa",
                      "dew_point_c", "relative_humidity_pct")

    @classmethod
    def defaulted(cls) -> "AtmosphereSpec":
        return cls(
            temperature_deviation_c=Quantity.default(
                0.0, "degC", frm="the standard day: no deviation from ISA",
                std=DAY_STANDARDS["isa"]),
            sea_level_pressure_hpa=Quantity.default(
                ISA_SEA_LEVEL_PRESSURE_HPA, "hPa",
                frm="the standard day: ISA sea-level pressure",
                std=DAY_STANDARDS["isa"]),
            dew_point_c=Quantity.default(
                None, "degC", frm="dry air: no water vapour"),
            relative_humidity_pct=Quantity.default(
                None, "%", frm="dry air: no water vapour"),
            day=Quantity.default("isa", frm="the standard day"),
        )

    def resolved(self) -> Dict[str, Quantity]:
        """The effective numeric fields once the ``day`` word has filled
        the ones left at their default: a stated number is never moved
        by a word; a word's humidity fills nothing when either humidity
        field is stated. Each filled field is ``inferred`` from the word
        with the word's citation. An unknown word fills nothing here (it
        is refused by name at validation)."""
        out = {name: getattr(self, name) for name in self.NUMERIC_FIELDS}
        word = self.day.value
        implied = DAY_WORDS.get(word, {}) if isinstance(word, str) else {}
        humidity_stated = any(
            out[name].source is not Source.DEFAULT
            for name in ("dew_point_c", "relative_humidity_pct"))
        for name, value in implied.items():
            if out[name].source is not Source.DEFAULT:
                continue
            if name == "relative_humidity_pct" and humidity_stated:
                continue
            out[name] = Quantity.inferred(value, out[name].unit,
                                          frm=f"day: {word}",
                                          std=DAY_STANDARDS[word])
        return out


@dataclass
class DatumSpec(ProvenancedBlock):
    """``datum``: the vertical datum the run declares (gap P10, D1).
    Absent-canonical: the orthometric frame is the default and is
    omitted from the canonical form, so every committed spec-8 example
    keeps its digest. Only the defaults are flown today: ``ellipsoidal``
    heights and the ``ellipsoid`` physics frame refuse by name
    (``datum.physics_frame_unsupported``); a declared ``geoid_model`` is
    checked against the bake's block by the runner
    (``datum.model_mismatch``). The block declares and checks; it
    converts no height and moves no trajectory (measured: the output
    digest is identical with and without it)."""

    vertical: Quantity
    physics_frame: Quantity
    geoid_model: Quantity

    FIELD_ORDER = ("vertical", "physics_frame", "geoid_model")
    BLOCK = "datum"

    @classmethod
    def defaulted(cls) -> "DatumSpec":
        return cls(
            vertical=Quantity.default(
                "orthometric", frm="the heights as built: orthometric numbers in "
                                   "JSBSim's ellipsoidal slot",
                std=DATUM_STANDARDS["orthometric"]),
            physics_frame=Quantity.default(
                "orthometric", frm="the physics frame as built (C2)",
                std=DATUM_STANDARDS["physics_frame"]),
            geoid_model=Quantity.default(
                None, frm="no model declared: the bake's own model is accepted"),
        )


@dataclass
class TurbulenceModelSpec(ProvenancedBlock):
    """``turbulence_model`` (P6): which continuous-turbulence spectrum the
    flight is in. Absent-canonical: ``dryden`` with the environment's own
    turbulence word and the run seed is the default and is omitted, so
    every committed spec-8 example keeps its digest. ``intensity`` is an
    existing turbulence word (light / moderate / severe / none) or a W20
    in knots; null means the environment's ``turbulence`` word applies.
    ``seed`` null means the run's ``seed``. The validator refuses an
    unknown model (``turbulence.model``); the registry claims every
    field (``record.unregistered`` otherwise)."""

    model: Quantity
    intensity: Quantity
    seed: Quantity

    FIELD_ORDER = ("model", "intensity", "seed")
    BLOCK = "turbulence_model"

    @classmethod
    def defaulted(cls) -> "TurbulenceModelSpec":
        return cls(
            model=Quantity.default(
                "dryden", frm="today's path: JSBSim's own Dryden filters",
                std=TURBULENCE_MODEL_STANDARDS["dryden"]),
            intensity=Quantity.default(
                None, frm="unstated: the environment's turbulence word applies"),
            seed=Quantity.default(
                None, frm="unstated: the run's seed applies"),
        )


@dataclass
class WindProfileSpec(ProvenancedBlock):
    """``wind_profile`` (P6): how the horizontal wind varies with height.
    Absent-canonical: ``uniform`` is the default and is omitted, so every
    committed spec-8 example keeps its digest. ``layers`` is a list of
    [altitude_m, speed_kt, direction_deg] for ``layered`` (at least two,
    ascending, none negative: ``wind_profile.layers``); ``roughness_ft``
    is the milspec z0 (0.15 or 2.0 ft; null = 0.15); ``fixture`` names a
    cached profile under assets/nwp for ``nwp`` (``weather.fixture_missing``
    / ``weather.fixture_digest``)."""

    kind: Quantity
    layers: Quantity
    roughness_ft: Quantity
    fixture: Quantity

    FIELD_ORDER = ("kind", "layers", "roughness_ft", "fixture")
    BLOCK = "wind_profile"

    @classmethod
    def defaulted(cls) -> "WindProfileSpec":
        return cls(
            kind=Quantity.default(
                "uniform", frm="today's path: the spec's wind everywhere",
                std=WIND_PROFILE_STANDARDS["uniform"]),
            layers=Quantity.default(
                None, frm="unstated: no layers (the kind is not layered)"),
            roughness_ft=Quantity.default(
                None, "ft", frm="unstated: the milspec z0 of 0.15 ft when the kind is milspec"),
            fixture=Quantity.default(
                None, frm="unstated: no cached profile (the kind is not nwp)"),
        )


@dataclass
class LoadingSpec(ProvenancedBlock):
    """``loading`` (P4): the payload stations and the fuel the flight
    starts with. Absent-canonical: the XML's own loading (its point
    masses and tank contents as shipped) is the default and is omitted,
    so every committed spec-8 example keeps its digest. ``payload`` is a
    mapping {station name: kg} over the stations the airframe's
    aircraft_config ``loading`` block names (an unknown or unloadable
    station refuses ``loading.station_unknown``; a negative mass or one
    over the station's maximum ``loading.station_mass``); ``fuel_kg`` is
    the total fuel mass, shared between the tanks in proportion to
    capacity, ``fuel_fraction`` fills every tank to that fraction of its
    capacity -- one of the two, never both (``loading.fuel_range``, also
    for a negative mass, one over the tanks' capacity or a fraction
    outside 0..1). The sum over the airframe's maximum takeoff weight
    refuses ``loading.max_weight``; a CG outside the handbook polygon
    ``loading.cg_envelope`` where the airframe's datum comparison admits
    the check. The writes, the hand calculation and the read-back are
    core/scenario/loading.py's."""

    payload: Quantity
    fuel_kg: Quantity
    fuel_fraction: Quantity

    FIELD_ORDER = ("payload", "fuel_kg", "fuel_fraction")
    BLOCK = "loading"

    @classmethod
    def defaulted(cls) -> "LoadingSpec":
        return cls(
            payload=Quantity.default(
                None, "kg per station",
                frm="unstated: the XML's own point-mass weights stand",
                std=LOADING_STANDARDS["payload"]),
            fuel_kg=Quantity.default(
                None, "kg", frm="unstated: the XML's own tank contents stand",
                std=LOADING_STANDARDS["fuel_kg"]),
            fuel_fraction=Quantity.default(
                None, "1", frm="unstated: the XML's own tank contents stand",
                std=LOADING_STANDARDS["fuel_fraction"]),
        )


#: P3: the failure kinds a schedule may name (core/telemetry/failures.py
#: KINDS) and what each rests on, in the spec's ``std`` field. Every kind is
#: JSBSim 1.2.4's own control, measured here; none is a statement about an
#: aeroplane.
FAILURE_KINDS = ("engine_out", "control_jam", "hardover", "float", "authority_loss")
FAILURE_STANDARDS: Dict[str, str] = {
    "none": "no failure: every engine and surface as the JSBSim model ships it",
    "engine_out": "JSBSim 1.2.4 FGPropulsion cutoff_cmd (turbine, FGTurbine::Off) or "
                  "magneto_cmd 0 (piston, FGPiston::doEngineStartup), for the target engine; "
                  "measured on the A320 and the c172p",
    "control_jam": "JSBSim 1.2.4 FGActuator fail_stuck on the injected failure chain (P2): "
                   "the actuator holds the previous step's output; measured on the c172p",
    "hardover": "JSBSim 1.2.4 FGActuator fail_hardover: the input replaced by the clip limit "
                "of its sign (-1 / +1); measured on the c172p",
    "float": "JSBSim 1.2.4 FGActuator fail_zero: the input replaced by 0; measured on the c172p",
    "authority_loss": "the injected failure chain's gain failure/<surface>/authority (P2, "
                      "blueprint correction 1): value x command held; measured on the c172p",
}


@dataclass
class FailuresSpec(ProvenancedBlock):
    """``failures`` (P3): the failure schedule. One field, ``events``, a
    list of ``{kind, target, at_s, value}`` mappings in time order: kind
    in FAILURE_KINDS, target a surface (elevator / aileron / rudder) for
    the surface kinds or an engine index for ``engine_out``, ``at_s``
    seconds after the run's first step (the write lands at the first
    step at or past it), ``value`` the remaining authority in 0..1 for
    ``authority_loss`` and null otherwise. Absent-canonical: the empty
    list is the default and is omitted, so every committed spec-8
    example keeps its digest. The validator refuses ``failures.kind``,
    ``failures.target``, ``failures.time``, ``failures.value`` and
    ``failures.actuator_missing`` (core/telemetry/failures.py problems);
    the registry claims the field (``record.unregistered`` otherwise).
    A surface failure makes the runner derive the airframe with the
    failures injection; an engine-out alone needs no derivation."""

    events: Quantity

    FIELD_ORDER = ("events",)
    BLOCK = "failures"

    @classmethod
    def defaulted(cls) -> "FailuresSpec":
        return cls(events=Quantity.default(
            [], frm="no failure scheduled", std=FAILURE_STANDARDS["none"]))


#: P5: the icing block's vocabulary. The severity WORDS are a STATED
#: mapping to Bragg's eta (core/environment/icing.py SEVERITY_WORDS: trace
#: 0.05, light 0.10, moderate 0.20, severe 0.30); the AIM 7-1-19 words are
#: pilot reports of an accretion rate, not values of eta. The envelope
#: words (14 CFR Part 25 Appendix C / O) are recorded as metadata and
#: applied nowhere. ``eta_max`` in 0..1; ``onset_s`` and ``ramp_s`` on the
#: run clock (seconds since the run's first step); ``alpha_shift_deg`` the
#: stated linear stall-onset cue at full eta.
ICING_SEVERITY_WORDS: Dict[str, float] = {"trace": 0.05, "light": 0.10, "moderate": 0.20,
                                          "severe": 0.30}
ICING_ENVELOPE_WORDS = ("appendix_c", "appendix_o")
ICING_STANDARDS: Dict[str, str] = {
    "severity": "a stated mapping of the AIM 7-1-19 pilot-report words to Bragg et al. 2000's "
                "eta (trace 0.05, light 0.10, moderate 0.20, severe 0.30) [unverified here]",
    "eta_max": "Bragg et al. 2000 (AIAA 2000-0360): C_A,iced = (1 + eta k_A) C_A per axis, "
               "through the icing injection's six factors [unverified here]",
    "onset_s": "the run-clock time (seconds since the run's first step) at which eta begins "
               "to rise: a stated schedule, not an accretion model",
    "ramp_s": "eta(t) = eta_max clamp((t - onset_s) / ramp_s, 0, 1): a stated linear ramp; "
              "0 is a step",
    "alpha_shift_deg": "the stall-onset cue 14 CFR Part 60 FSTD Directive 2 asks for, as a "
                       "stated linear shift of the LIFT table's alpha (alpha_shift_deg eta / "
                       "eta_max) through the icing_alpha injection [unverified here]",
    "envelope": "14 CFR Part 25 Appendix C (continuous / intermittent maximum) or Appendix O "
                "(supercooled large drops): recorded as metadata, applied nowhere "
                "[unverified here]",
}


@dataclass
class IcingSpec(ProvenancedBlock):
    """``icing`` (P5): the severity ramp the flight is iced with. Absent-
    canonical: no ice (the stock airframe) is the default and is omitted,
    so every committed spec-8 example keeps its digest. ``severity`` is a
    word (``icing.severity`` otherwise) that fills ``eta_max`` while the
    number is at its default -- a stated number always wins (the day
    word's doctrine); ``eta_max`` in 0..1, ``onset_s`` and ``ramp_s`` at or
    above 0, ``alpha_shift_deg`` within a stated bound (``icing.eta_range``
    otherwise); ``envelope`` a word (``icing.envelope`` otherwise), metadata
    only. A stated block flies the airframe derived with the ``icing`` and
    ``icing_alpha`` injections and needs the airframe's k-table
    (``icing.airframe_data`` otherwise); the writes, the read-back and the
    records are core/environment/icing.py's."""

    severity: Quantity
    eta_max: Quantity
    onset_s: Quantity
    ramp_s: Quantity
    alpha_shift_deg: Quantity
    envelope: Quantity

    FIELD_ORDER = ("severity", "eta_max", "onset_s", "ramp_s", "alpha_shift_deg", "envelope")
    BLOCK = "icing"

    @classmethod
    def defaulted(cls) -> "IcingSpec":
        return cls(
            severity=Quantity.default(
                None, frm="unstated: no severity word", std=ICING_STANDARDS["severity"]),
            eta_max=Quantity.default(
                None, "1", frm="unstated: no ice (eta 0) unless a severity word says",
                std=ICING_STANDARDS["eta_max"]),
            onset_s=Quantity.default(
                0.0, "s", frm="the run's first step", std=ICING_STANDARDS["onset_s"]),
            ramp_s=Quantity.default(
                0.0, "s", frm="a step to eta_max at the onset", std=ICING_STANDARDS["ramp_s"]),
            alpha_shift_deg=Quantity.default(
                0.0, "deg", frm="no stall-onset cue", std=ICING_STANDARDS["alpha_shift_deg"]),
            envelope=Quantity.default(
                None, frm="unstated: no envelope named", std=ICING_STANDARDS["envelope"]),
        )

    def resolved(self) -> Dict[str, Quantity]:
        """The effective ``eta_max``: a stated number wins; else the
        severity word's value (``inferred`` from the word); else 0 (no
        ice, ``inferred`` from the absence). An unknown word fills nothing
        here (it is refused by name at validation)."""
        eta = self.eta_max
        word = self.severity.value
        if eta.source is Source.DEFAULT or eta.value is None:
            if isinstance(word, str) and word in ICING_SEVERITY_WORDS:
                eta = Quantity.inferred(ICING_SEVERITY_WORDS[word], "1",
                                        frm=f"severity: {word}", std=ICING_STANDARDS["severity"])
            elif eta.value is None:
                eta = Quantity.inferred(0.0, "1", frm="no severity and no eta_max stated: no ice",
                                        std=ICING_STANDARDS["eta_max"])
        return {"eta_max": eta}


#: D2 (blueprint section 5): the ``dis`` block's vocabulary. The entity
#: identifier is the standard's site / application / entity triple, each
#: 0..65535 (``interop.dis.entity_id`` outside); ``force_id`` is the 8-bit
#: force enumeration, 0 Other the default (``dis.force_id`` outside 0..255);
#: ``marking`` is the 11-character ASCII entity marking, '' meaning the
#: airframe key derived at export (``dis.marking_too_long`` beyond 11 or
#: outside ASCII); ``timestamp_mode`` is ``relative`` (simulation time past
#: the hour, LSB 0) or ``absolute`` (a stated UTC epoch plus the sample
#: time, LSB 1; the epoch is the exporter's option and is refused by name,
#: ``dis.timestamp_epoch_missing``, when absent). The block labels the
#: export; it moves no trajectory.
DIS_TIMESTAMP_MODES = ("relative", "absolute")
DIS_STANDARDS: Dict[str, str] = {
    "entity_id": "IEEE 1278.1-2012 Entity Identifier record: site, application, entity, "
                 "16 bits each [cited from memory]",
    "force_id": "IEEE 1278.1-2012 Entity State PDU force id with SISO-REF-010's force "
                "enumeration (0 Other, 1 Friendly, 2 Opposing, 3 Neutral) [from memory, "
                "unverified here]",
    "marking": "IEEE 1278.1-2012 Entity Marking record: character set 1 (ASCII), 11 "
               "characters, NUL padded [cited from memory]",
    "timestamp_mode": "IEEE 1278.1-2012 timestamp: 31 bits of 3600 / 2^31 s past the hour, "
                      "LSB 1 absolute / 0 relative [cited from memory]",
}


@dataclass
class DisSpec(ProvenancedBlock):
    """``dis`` (D2): how the run's Entity State PDU log is labelled --
    the entity identifier triple, the force id, the marking and the
    timestamp mode. Absent-canonical: the documented defaults (1:1:1,
    force 0, the airframe key as marking, relative timestamps) are
    omitted from the canonical form, so every committed spec-8 example
    keeps its digest. The validator refuses ``interop.dis.entity_id``,
    ``dis.force_id``, ``dis.marking_too_long`` and ``dis.timestamp_mode``
    (core/interop/dis_stream.py dis_spec_problems, the one list for the
    validator and the exporter); the registry claims every field
    (``record.unregistered`` otherwise). Nothing here is applied to the
    flight: the block is read by the exporter after it, and the
    ``dis.entity_state`` record carries what was written."""

    site: Quantity
    application: Quantity
    entity: Quantity
    force_id: Quantity
    marking: Quantity
    timestamp_mode: Quantity

    FIELD_ORDER = ("site", "application", "entity", "force_id", "marking", "timestamp_mode")
    BLOCK = "dis"

    @classmethod
    def defaulted(cls) -> "DisSpec":
        return cls(
            site=Quantity.default(1, frm="the documented default entity identifier 1:1:1",
                                  std=DIS_STANDARDS["entity_id"]),
            application=Quantity.default(1, frm="the documented default entity identifier 1:1:1",
                                         std=DIS_STANDARDS["entity_id"]),
            entity=Quantity.default(1, frm="the documented default entity identifier 1:1:1",
                                    std=DIS_STANDARDS["entity_id"]),
            force_id=Quantity.default(0, frm="force id 0, Other: no side is stated",
                                      std=DIS_STANDARDS["force_id"]),
            marking=Quantity.default("", frm="no marking stated: the airframe key is derived "
                                             "at export",
                                     std=DIS_STANDARDS["marking"]),
            timestamp_mode=Quantity.default("relative", frm="relative timestamps: simulation "
                                                            "time past the hour, LSB 0",
                                            std=DIS_STANDARDS["timestamp_mode"]),
        )


#: P7: the wake block's vocabulary. ``model`` names the circulation decay:
#: ``none`` (Gamma_0 held; the age is recorded either way) or ``sarpkaya``
#: (Sarpkaya 2000 with ``eps_star`` and ``n_star`` as declared inputs);
#: any other word refuses ``wake.model``. The generator is a configured
#: airframe whose flight model states a weight and a span
#: (``wake.generator`` otherwise); the geometry is the own ship's offset
#: from the pair's centreline (right, up) and the wake's age there --
#: ``separation_s`` (the generator passed that many seconds before the
#: run's first step) or a held ``age_s``, one of the two (``wake.geometry``
#: otherwise). The physics is core/environment/wake.py's.
WAKE_DECAY_MODELS = ("none", "sarpkaya")
WAKE_STANDARDS: Dict[str, str] = {
    "generator": "the generating airframe's weight W (inertia/weight-lbs as the JSBSim model "
                 "ships) and span b (metrics/bw-ft): Gamma_0 = W / (rho V b_0), b_0 = pi b / 4, "
                 "r_c = 0.035 b (Proctor's convention) [unverified here]",
    "generator_speed_kt": "the generator's true airspeed V in Gamma_0 = W / (rho V b_0); null = "
                          "the own ship's true airspeed at the initial conditions (a stated choice)",
    "lateral_offset_m": "the own CG's offset to the right of the pair's centreline at the run's "
                        "first step (positive right, in the frame of the own initial heading)",
    "vertical_offset_m": "the own CG's height above the pair's centreline at the run's first "
                         "step (positive up)",
    "separation_s": "the wake's age at the own ship's position at the run's first step; along "
                    "the run the age is separation_s + t - x_along / V_g (a stated kinematic rule)",
    "age_s": "the wake's age held constant along the run (the generator and the own ship taken "
             "as flying the same speed: a stated choice)",
    "model": "Burnham & Hallock (1982) tangential profile V(r) = Gamma/(2 pi r) r^2/(r^2 + r_c^2) "
             "per vortex, the pair summed; 'none' holds Gamma_0 [unverified here]",
    "sarpkaya": "Sarpkaya, J. Aircraft 37(1) 2000: T = t w_0/b_0, demise at T_d = "
                "(0.7475/eps*)^(4/3) with a stated N* bound; the history taken linear to demise "
                "[from memory, unverified here]",
    "eps_star": "the non-dimensional eddy dissipation rate (eps b_0)^(1/3) / w_0, a declared "
                "input of the sarpkaya decay, 0 < eps* <= 1 [unverified here]",
    "n_star": "the non-dimensional Brunt-Vaisala frequency N b_0 / w_0, a declared input of the "
              "sarpkaya decay, 0..1 (a stated bound on the demise) [unverified here]",
}


@dataclass
class WakeSpec(ProvenancedBlock):
    """``wake`` (P7): the wake-vortex encounter. Absent-canonical: no wake
    (no generator) is the default and is omitted, so every committed
    spec-8 example keeps its digest. ``generator`` names the generating
    airframe (``wake.generator`` when it is not configured or states no
    span or weight); ``generator_speed_kt`` its speed (null = the own
    ship's); ``lateral_offset_m`` / ``vertical_offset_m`` the own CG's
    offset from the pair's centreline (right, up); ``separation_s`` or a
    held ``age_s`` the wake's age (``wake.geometry`` for neither, both, a
    negative age or a non-number); ``model`` the decay (``wake.model``);
    ``eps_star`` / ``n_star`` the sarpkaya inputs (``wake.decay`` when
    missing or out of range; carried, not applied, beside ``none``). A
    stated generator flies the own airframe derived with the
    ``gust_rotation`` injection; the field, the read-back and the records
    are core/environment/wake.py's. A block with no generator applies
    nothing and the runner records its stated fields as unread."""

    generator: Quantity
    generator_speed_kt: Quantity
    lateral_offset_m: Quantity
    vertical_offset_m: Quantity
    separation_s: Quantity
    age_s: Quantity
    model: Quantity
    eps_star: Quantity
    n_star: Quantity

    FIELD_ORDER = ("generator", "generator_speed_kt", "lateral_offset_m", "vertical_offset_m",
                   "separation_s", "age_s", "model", "eps_star", "n_star")
    BLOCK = "wake"

    @classmethod
    def defaulted(cls) -> "WakeSpec":
        return cls(
            generator=Quantity.default(
                None, frm="unstated: no wake (no generating aircraft)",
                std=WAKE_STANDARDS["generator"]),
            generator_speed_kt=Quantity.default(
                None, "kt", frm="unstated: the own ship's true airspeed at the initial conditions",
                std=WAKE_STANDARDS["generator_speed_kt"]),
            lateral_offset_m=Quantity.default(
                0.0, "m", frm="centred on the pair's centreline",
                std=WAKE_STANDARDS["lateral_offset_m"]),
            vertical_offset_m=Quantity.default(
                0.0, "m", frm="at the height of the pair's centreline",
                std=WAKE_STANDARDS["vertical_offset_m"]),
            separation_s=Quantity.default(
                None, "s", frm="unstated: an encounter states separation_s or age_s",
                std=WAKE_STANDARDS["separation_s"]),
            age_s=Quantity.default(
                None, "s", frm="unstated: an encounter states separation_s or age_s",
                std=WAKE_STANDARDS["age_s"]),
            model=Quantity.default(
                "none", frm="no decay: the initial circulation held",
                std=WAKE_STANDARDS["model"]),
            eps_star=Quantity.default(
                None, "1", frm="unstated: no sarpkaya decay", std=WAKE_STANDARDS["eps_star"]),
            n_star=Quantity.default(
                None, "1", frm="unstated: no stratification bound", std=WAKE_STANDARDS["n_star"]),
        )


#: R2: the instruments block's vocabulary. Each instrument names a profile
#: (assets/instrument_profiles/<name>.json, the batch-1 shape) and a lever
#: arm in metres in body axes (x forward, y right, z down) from the CG to
#: the sensor. The IMU's arm enters the specific force through the
#: rotational terms omega x (omega x r) + omega_dot x r; the GPS antenna's
#: arm enters the position; the pitot-static and magnetometer arms are
#: carried and recorded (no lever-arm physics is modelled for them, said
#: in the record). An unstated instrument is the ideal profile at the CG:
#: the recorded channel IS the measurement.
INSTRUMENT_NAMES = ("imu", "gps", "pitot_static", "magnetometer")
INSTRUMENT_STANDARDS: Dict[str, str] = {
    "imu": "IEEE Std 952-2020 Annex C Allan-variance terms (N, B, K, b0) at the FDM rate; "
           "specific force f = g0 (N_x, N_y, -N_z) + omega_dot x r + omega x (omega x r) in "
           "body axes, FGAuxiliary's vPilotAccel form (JSBSim 1.2.4, read here) [standard "
           "unverified here]",
    "gps": "GPS SPS Performance Standard 5th ed. (2020) receiver-class white sigmas; Groves "
           "(2013) ch. 14 antenna lever arm; fixes on the receiver's clock, held between "
           "[unverified here]",
    "pitot_static": "Gracey NASA RP-1046; 14 CFR 25.1323: first-order lags and a position-error "
                    "table (default zero, stated) [unverified here]",
    "magnetometer": "IGRF-13 degree-1 coefficients g10 -29404.8, g11 -1450.9, h11 4652.5 nT at "
                    "2020.0 (verified here from the fetched IGRF13.shc): a tilted dipole, hard "
                    "iron per Caruso 2000; not IGRF/WMM",
}


@dataclass
class InstrumentsSpec(ProvenancedBlock):
    """``instruments`` (R2): the instrument models run at the FDM rate,
    one field per instrument -- ``imu``, ``gps``, ``pitot_static``,
    ``magnetometer`` -- each a mapping ``{profile: <name>, lever_arm_m:
    [x, y, z]}`` or null (the ideal profile at the CG: the recorded
    channel is the measurement). Absent-canonical: every field null is
    the default and is omitted, so every committed spec-8 example keeps
    its digest. The validator refuses ``instrument.profile`` (a profile
    not on file, or a field that is not such a mapping),
    ``instrument.lever_arm`` (not three finite metres, or longer than
    LEVER_ARM_MAX_M) and ``instrument.rate`` (a GPS update rate above the
    FDM rate); the registry claims every field (``record.unregistered``
    otherwise). The models, the meas_* columns, instruments.npz and the
    records are core/telemetry/instruments.py's."""

    imu: Quantity
    gps: Quantity
    pitot_static: Quantity
    magnetometer: Quantity

    FIELD_ORDER = INSTRUMENT_NAMES
    BLOCK = "instruments"

    @classmethod
    def defaulted(cls) -> "InstrumentsSpec":
        return cls(**{name: Quantity.default(
            None, frm=f"unstated: the ideal {name} at the CG (the recorded channel is the "
                      f"measurement)", std=INSTRUMENT_STANDARDS[name])
            for name in INSTRUMENT_NAMES})


#: R2: the record block's vocabulary -- the spec's own way to ask for the
#: null pairs, the three-rate convergence study and the sensitivity pairs
#: flightsim/capture.py opts into with --null-tests / --uncertainty.
RECORD_STANDARDS: Dict[str, str] = {
    "null_tests": "core/record_null.py: the identical run with each stated registered variable "
                  "at its null value, the effect per channel against the V9 floors",
    "convergence": "Roache 1994 (GCI); ASME V&V 20-2009 solution verification: three rates "
                   "dt, dt/r, dt/r^2 with turbulence off, the observed order p per SRQ "
                   "[unverified here]",
    "sensitivity_pairs": "GUM JCGM 100:2008 eq. 10: u_input by central pairs x +- u_x per "
                         "stated variable (core/uncertainty.py) [unverified here]",
}


@dataclass
class RecordSpec(ProvenancedBlock):
    """``record`` (R2): what the run measures about itself beyond the
    flight -- ``null_tests`` (bool: fly the null pair of every stated
    registered variable), ``convergence`` (``{rates: [r1, r2, r3]}`` Hz
    for the three-rate study whose observed order feeds u_num, or null),
    ``sensitivity_pairs`` (bool: the central +-u_x pairs for u_input).
    Absent-canonical: false / null / false is the default and is omitted,
    so every committed spec-8 example keeps its digest. The validator
    refuses ``record.convergence`` (rates the FDM cannot run: not three
    positive numbers, not strictly ascending, not a constant refinement
    ratio, above RATE_MAX_HZ) and ``record.uncertainty_basis``
    (sensitivity pairs asked for a stated inferred variable whose registry
    entry declares no bin width, so no u_x rule exists); the runner
    refuses ``record.readback`` when a registered write reads back outside
    its tolerance. The CLI options stay; the block is read by the capture
    beside them (either asks, both are honoured)."""

    null_tests: Quantity
    convergence: Quantity
    sensitivity_pairs: Quantity

    FIELD_ORDER = ("null_tests", "convergence", "sensitivity_pairs")
    BLOCK = "record"

    @classmethod
    def defaulted(cls) -> "RecordSpec":
        return cls(
            null_tests=Quantity.default(
                False, frm="unstated: no null pair flown (the --null-tests option still asks)",
                std=RECORD_STANDARDS["null_tests"]),
            convergence=Quantity.default(
                None, frm="unstated: no three-rate study; u_num assumes order 1 with Fs = 3",
                std=RECORD_STANDARDS["convergence"]),
            sensitivity_pairs=Quantity.default(
                False, frm="unstated: no central pair flown (the --uncertainty option still asks)",
                std=RECORD_STANDARDS["sensitivity_pairs"]),
        )

    def asks(self, null_tests: bool = False, uncertainty: bool = False) -> Dict[str, Any]:
        """What the capture runs beyond the recorded flight: the block's
        asks OR-ed with the CLI's (``--null-tests`` / ``--uncertainty``),
        and the three-rate study's first rate when ``convergence`` states
        one (its observed order then feeds u_num). Either side asking is
        honoured; the answer says which asked."""
        rates = None
        value = self.convergence.value
        if isinstance(value, dict) and isinstance(value.get("rates"), list) and value["rates"]:
            rates = [float(r) for r in value["rates"]]
        return {
            "null_tests": bool(self.null_tests.value) or bool(null_tests),
            "uncertainty": bool(self.sensitivity_pairs.value) or bool(uncertainty) or rates is not None,
            "convergence_rates_hz": rates,
            "asked_by": {
                "null_tests": ("spec" if self.null_tests.value else "") + ("+cli" if null_tests else ""),
                "uncertainty": ("spec" if self.sensitivity_pairs.value else "")
                               + ("+convergence" if rates is not None else "")
                               + ("+cli" if uncertainty else ""),
            },
        }


#: W2: what each ``runway`` field rests on, in the spec's ``std`` field.
RUNWAY_STANDARDS: Dict[str, str] = {
    "designator": "ICAO Annex 14 Vol I 5.2.2.4: the whole number nearest one tenth of the "
                  "heading, NN or NN[LRC] (checked against the stated heading; no magnetic "
                  "variation is modelled) [unverified here]",
    "threshold": "the runway threshold, WGS 84 latitude and longitude (the centreline at "
                 "the threshold)",
    "heading_deg": "the runway's true heading from the threshold along the centreline, "
                   "[0, 360) degrees; the grid heading is taken as this (no convergence)",
    "dimensions": "length 300..5500 m and width 18..80 m: the range the marking raster "
                  "and the flatten pad draw (a stated bound, not an Annex 14 table)",
    "surface": "a word of core/scene/runway.py SURFACES; scene dressing and a record, no "
               "friction model",
    "markings": "ICAO Annex 14 Vol I 5.2 elements (threshold, designator, centreline, "
                "aiming point, touchdown zone): standard = all five, none, or a list "
                "[dimensions unverified here]",
}


@dataclass
class RunwayBlockSpec(ProvenancedBlock):
    """``runway`` (W2): one runway in the scene -- ``designator``, the
    threshold's ``threshold_lat_deg`` / ``threshold_lon_deg``,
    ``heading_deg``, ``length_m``, ``width_m``, ``surface`` and
    ``markings``. Absent-canonical: no designator (no runway) is the
    default and is omitted, so every committed spec-8 example keeps its
    digest. The validator refuses ``runway.geometry`` (a designator that
    is not NN[LRC] or does not name the heading, a threshold that is not a
    coordinate pair, a length, width or heading out of range),
    ``runway.taxonomy`` (a surface word outside the taxonomy) and
    ``runway.markings`` (a marking set the raster cannot draw) through
    core/scene/runway.py's one ``problems`` list; ``runway.terrain_mismatch``
    is the pad bake's, where the runway meets the bake. The markings
    raster, the light positions, the flatten pad and the ``scene.runway``
    record are core/scene/runway.py's."""

    designator: Quantity
    threshold_lat_deg: Quantity
    threshold_lon_deg: Quantity
    heading_deg: Quantity
    length_m: Quantity
    width_m: Quantity
    surface: Quantity
    markings: Quantity

    FIELD_ORDER = ("designator", "threshold_lat_deg", "threshold_lon_deg", "heading_deg",
                   "length_m", "width_m", "surface", "markings")
    BLOCK = "runway"

    @classmethod
    def defaulted(cls) -> "RunwayBlockSpec":
        return cls(
            designator=Quantity.default(
                None, frm="unstated: no runway in the scene", std=RUNWAY_STANDARDS["designator"]),
            threshold_lat_deg=Quantity.default(
                None, "deg", frm="unstated: no runway", std=RUNWAY_STANDARDS["threshold"]),
            threshold_lon_deg=Quantity.default(
                None, "deg", frm="unstated: no runway", std=RUNWAY_STANDARDS["threshold"]),
            heading_deg=Quantity.default(
                None, "deg", frm="unstated: no runway", std=RUNWAY_STANDARDS["heading_deg"]),
            length_m=Quantity.default(
                None, "m", frm="unstated: no runway", std=RUNWAY_STANDARDS["dimensions"]),
            width_m=Quantity.default(
                None, "m", frm="unstated: no runway", std=RUNWAY_STANDARDS["dimensions"]),
            surface=Quantity.default(
                "asphalt", frm="the documented default surface word",
                std=RUNWAY_STANDARDS["surface"]),
            markings=Quantity.default(
                "standard", frm="the documented default: the five Annex 14 elements",
                std=RUNWAY_STANDARDS["markings"]),
        )


@dataclass
class TrafficSpec(ProvenancedBlock):
    """One scripted traffic aircraft (contracts §2.2)."""

    aircraft: Quantity
    track: Quantity
    range_m: Quantity
    livery: Quantity

    FIELD_ORDER = ("aircraft", "track", "range_m", "livery")
    BLOCK = "traffic"

    @classmethod
    def defaulted(cls, aircraft: str, track: str = DEFAULT_TRAFFIC_TRACK,
                  frm: str = "documented traffic default") -> "TrafficSpec":
        """A traffic entry for a stated airframe; the airframe is the
        one field with no documented default, so it is ``user``."""
        return cls(
            aircraft=Quantity.user(aircraft, frm=f"traffic: {aircraft}"),
            track=Quantity.default(track, frm=frm),
            range_m=Quantity.default(DEFAULT_TRAFFIC_RANGE_M, "m", frm=frm),
            livery=Quantity.default(DEFAULT_TRAFFIC_LIVERY, frm=frm),
        )
