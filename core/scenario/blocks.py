"""The spec-8 blocks: ``scene``, ``taxonomy``, ``traffic[]``, and the
physics additions' ``atmosphere``, ``datum``, ``turbulence_model`` and
``wind_profile``.

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


def configured_airframes(config_dir: Optional[Path] = None) -> List[str]:
    """Every airframe with an asset-pipeline config -- the ones a
    traffic entry may name (its mesh must be importable like the
    primary's; contracts §2.2)."""
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    if not directory.is_dir():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


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

    FIELD_ORDER = ("terrain_source", "terrain")
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
        )


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
