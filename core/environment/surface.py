"""Surface classes: what the ground cover does to the air, by the book.

A surface word in the spec ("over grasslands", "over the ocean") changes the
air in exactly the two ways this repository already models, and no others:

* **Roughness** -- the neutral surface-layer log profile
  (:class:`~core.environment.wind.LogProfileWind`), with z0 from the
  Davenport-Wieringa classes (Stull 1988 Table 9-6). Wind decays honestly
  toward the ground below the 300 m surface-layer top and is HELD at the
  spec's own wind above it, so cruise flight over any surface flies the
  spec's stated wind.
* **Thermal forcing** -- Allen's convective updraft model
  (NASA/TM-2006-214019), with (w*, zi) anchored on the TM's OWN Table 2
  monthly climatology for Desert Rock NV. Desert uses the July mean
  directly -- the TM's site is desert. Every other land class borrows a
  monthly mean AS A STATED PROXY (the basis string says so); the ocean
  gets no thermals at all rather than an invented weak value.

What a surface class deliberately does NOT claim: no ground-cover visuals
(a flat scene still renders the labeled slab until a measured visual pass
exists -- see BRIEF_PHASE9), no building-resolved flow for "city" (z0 is
the only aerodynamic statement about buildings; the urban heat island is
NOT separately modelled and the basis string says so), no stability
corrections (LogProfileWind is neutral-layer by construction, stated in
its own docstring).

The roughness inference (blueprint section 4, work item W1)
-----------------------------------------------------------
A georeferenced run whose bake carries land cover (core/terrain/landcover.py,
``landcover.json``) and whose spec states NO surface (``unspecified`` with
provenance ``default``) infers ROUGHNESS ONLY from the dominant WorldCover
class: :func:`surface_from_landcover` maps 10 -> forest, 20/30/40/100 ->
grassland (z0 'open'), 60 -> bare, 70 -> snow, 50 -> city, 80/90/95 ->
ocean (z0 'water'), through the rows of :data:`ROUGHNESS_OF_COVER`, each
a Davenport-Wieringa class in Stull 1988 Table 9-6. The dominant class
must hold at least :data:`DOMINANCE_THRESHOLD` = 0.5 of the scene (a
stated threshold: a scene that is half one thing is not "over" it), else
``landcover.surface_inference`` is refused by name; so is a dominant code
with no row. The inferred class carries ``thermals None`` whatever the
table says for its word -- the thermals, the season, the vegetation and
anything visual stay untouched (a glacier scene must not fly desert
updrafts because a word matched). A surface the user stated is never
overridden: provenance ``user`` (and ``inferred`` from the prompt) beats
the inference, which runs only for the default.

The two new classes: ``snow`` and ``bare`` take z0 'smooth' (0.005 m, the
table's featureless-land row: "desert, beaches, ice"). Stull's Table 9-6
has NO snow row; 'smooth' is a STATED choice for snow and ice, not a
measurement, and both classes attach no thermals rather than borrowing
the desert's July anchor.

The record ``environment.surface`` (:class:`InferredRoughnessWind`, a
LogProfileWind that returns its own ``AppliedVariable``): value the
roughness key the log profile uses, unit 'word', source 'inferred', from
the tile, the dominant fraction and the map row, std the Stull citation,
the JSBSim wind properties the stack writes every step, the effect
channels the recorder writes, a readback of the z0 the profile uses, and
a null test measured on the run itself: the wind the profile wrote at
the aircraft against the spec's wind (what the unstated surface's steady
provider writes), peak over the run, threshold 0.5 kt. The two-flight
null pair (core/record_null.run_null_pair) is measured in
tests/test_surface_inference.py and reported.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from .base import Position, WindNED
from .thermals import SEASON_TABLE
from .wind import LogProfileWind


@dataclass(frozen=True)
class SurfaceClass:
    word: str                 # the spec vocabulary word
    roughness: str            # LogProfileWind.ROUGHNESS_M key
    z0_m: float               # copied out for display/provenance
    #: (w*, zi) for AllenThermals, or None for "no thermals modelled".
    thermals: Optional[Tuple[float, float]]
    thermal_basis: str
    description: str


def _z0(key: str) -> float:
    return LogProfileWind.ROUGHNESS_M[key]


_TM = "NASA/TM-2006-214019 Table 2 (Desert Rock NV climatology)"

SURFACE_CLASSES: Dict[str, SurfaceClass] = {
    "grassland": SurfaceClass(
        "grassland", "open", _z0("open"), SEASON_TABLE["spring"],
        f"{_TM} April mean as a stated proxy for temperate grassland",
        "open flat terrain, grass"),
    "desert": SurfaceClass(
        "desert", "smooth", _z0("smooth"), SEASON_TABLE["summer"],
        f"{_TM} July mean; the TM's own site is desert",
        "featureless arid land"),
    "ocean": SurfaceClass(
        "ocean", "water", _z0("water"), None,
        "no convective thermals modelled over water (rather than an "
        "invented weak value)",
        "open water"),
    "forest": SurfaceClass(
        "forest", "forest", _z0("forest"), SEASON_TABLE["autumn"],
        f"{_TM} October mean as a stated proxy for forest canopy",
        "closed forest canopy"),
    "city": SurfaceClass(
        "city", "city", _z0("city"), SEASON_TABLE["spring"],
        f"{_TM} April mean as a stated proxy; the urban heat island is "
        f"NOT separately modelled",
        "centres of large towns and cities"),
    # W1: the two classes the land cover inference needs. z0 'smooth' is a
    # STATED choice for both -- Stull 1988 Table 9-6 has no snow row; its
    # 'smooth' row is featureless land (desert, beaches, ice) -- and neither
    # borrows the desert's July thermal anchor: a glacier scene must not
    # fly desert updrafts.
    "snow": SurfaceClass(
        "snow", "smooth", _z0("smooth"), None,
        "no convective thermals modelled over snow and ice (the desert's "
        "July anchor is not borrowed for a surface it does not describe)",
        "snow and ice; z0 'smooth' (0.005 m) is a stated choice: Stull 1988 "
        "Table 9-6 has no snow row, and 'smooth' is its featureless-land row "
        "(desert, beaches, ice)"),
    "bare": SurfaceClass(
        "bare", "smooth", _z0("smooth"), None,
        "no convective thermals modelled over bare or sparsely vegetated ground "
        "(the desert's July anchor is a desert site's, not this one's)",
        "bare or sparsely vegetated ground; z0 'smooth' (0.005 m) as the "
        "table's featureless-land row, a stated choice"),
}

#: The spec default: no ground cover stated, no surface coupling attached.
UNSPECIFIED = "unspecified"


def surface_class(word: str) -> Optional[SurfaceClass]:
    """The class for a spec word, or None for the default. Raises on an
    unknown word -- the validator turns that into a named refusal rather
    than letting an unmodelled surface run as if it were modelled."""
    if word == UNSPECIFIED:
        return None
    if word not in SURFACE_CLASSES:
        raise ValueError(
            f"unknown surface {word!r}; modelled classes: "
            f"{sorted(SURFACE_CLASSES)} (or {UNSPECIFIED!r})")
    return SURFACE_CLASSES[word]


# -- the roughness inference from land cover (W1) ---------------------------

#: WorldCover legend code -> surface word (a key of SURFACE_CLASSES) --
#: the map rows the blueprint states. Only the roughness of the word is
#: taken; its thermals are dropped (roughness only).
ROUGHNESS_OF_COVER: Dict[int, str] = {
    10: "forest",
    20: "grassland", 30: "grassland", 40: "grassland", 100: "grassland",
    60: "bare",
    70: "snow",
    50: "city",
    80: "ocean", 90: "ocean", 95: "ocean",
}

#: The dominant class must hold at least this fraction of the scene.
DOMINANCE_THRESHOLD = 0.5

STULL_TABLE = ("Stull, R. B. (1988), An Introduction to Boundary Layer Meteorology, "
               "Table 9-6 (Davenport-Wieringa roughness classes, z0 in m)")

#: The null test's threshold at the aircraft, in knots (a stated choice:
#: five times the null-pair speed floor of 0.1 kt).
NULL_WIND_THRESHOLD_KT = 0.5
MPS_PER_KT = 1852.0 / 3600.0

#: The recorder's wind channels the inferred roughness moves (checked
#: against a real run's telemetry.columns in tests/test_surface_inference.py).
EFFECT_CHANNELS = ("wind_speed_mps", "wind_north_mps", "wind_east_mps")
JSBSIM_WIND_PROPERTIES = ("atmosphere/wind-north-fps", "atmosphere/wind-east-fps",
                          "atmosphere/wind-down-fps")


class SurfaceInferenceError(Exception):
    """No roughness can be inferred from the scene's land cover; refused
    by name (``landcover.surface_inference``): the dominant class holds
    less than the threshold, or has no map row, or the land cover file
    cannot be read."""

    constraint = "landcover.surface_inference"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"landcover.surface_inference: {message}")


@dataclass(frozen=True)
class InferredSurface:
    """The roughness inferred from a scene's dominant land cover, with
    its provenance. ``surface.thermals`` is None by construction."""

    surface: SurfaceClass
    word: str
    code: int
    key: str
    fraction: float
    tile: str
    landcover_json: str
    sha256: str
    frm: str
    source: str = "inferred"
    std: str = STULL_TABLE
    threshold: float = DOMINANCE_THRESHOLD

    def provenance(self) -> Dict[str, Any]:
        return {"surface": self.word, "roughness": self.surface.roughness,
                "z0_m": self.surface.z0_m, "source": self.source, "from": self.frm,
                "std": self.std, "dominant_code": self.code, "dominant_class": self.key,
                "dominant_fraction": self.fraction, "threshold": self.threshold,
                "tile": self.tile, "landcover_json": self.landcover_json,
                "landcover_sha256": self.sha256,
                "thermals": None,
                "roughness_only": "the season, the thermals, the vegetation and anything "
                                  "visual are not inferred"}


def roughness_only(cls: SurfaceClass) -> SurfaceClass:
    """The class with its thermals removed: the inference infers z0 and
    nothing else, whatever the table says for the word."""
    return replace(cls, thermals=None,
                   thermal_basis="not inferred: the land cover inference infers roughness "
                                 "only (no convective thermals attached)")


def surface_from_landcover(landcover_json) -> InferredSurface:
    """The roughness class of a scene from its ``landcover.json``
    (core/terrain/landcover.py): the dominant legend class, its fraction,
    the map row. Refuses ``landcover.surface_inference`` when the file
    is unreadable, the dominant fraction is below
    :data:`DOMINANCE_THRESHOLD`, or the dominant code has no row."""
    path = Path(landcover_json)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SurfaceInferenceError(f"{path} is not readable land cover: {exc}") from exc
    classes = document.get("classes") or []
    fractions = document.get("fractions") or {}
    if not classes or not fractions:
        raise SurfaceInferenceError(f"{path} carries no classes or fractions")
    by_key = {str(c["key"]): int(c["code"]) for c in classes}
    dominant = str(document.get("dominant_class") or "")
    if dominant not in fractions or dominant not in by_key:
        raise SurfaceInferenceError(f"{path} names no dominant class in its legend")
    fraction = float(fractions[dominant])
    if fraction < DOMINANCE_THRESHOLD:
        raise SurfaceInferenceError(
            f"the dominant land cover class {dominant!r} holds {fraction:.4f} of the "
            f"scene, below the stated threshold {DOMINANCE_THRESHOLD}; no one roughness "
            f"describes this scene -- state a surface in the spec")
    code = by_key[dominant]
    word = ROUGHNESS_OF_COVER.get(code)
    if word is None or word not in SURFACE_CLASSES:
        raise SurfaceInferenceError(
            f"land cover code {code} ({dominant!r}) has no roughness row")
    base = SURFACE_CLASSES[word]
    tiles = ", ".join(sorted((document.get("source") or {}).get("tiles") or {})) or "local source"
    frm = (f"WorldCover tile {tiles}: dominant class {dominant!r} (code {code}) at "
           f"{fraction:.4f} of the scene (threshold {DOMINANCE_THRESHOLD}); map row "
           f"{code} -> {word!r} -> z0 {base.roughness!r} = {base.z0_m} m")
    return InferredSurface(
        surface=roughness_only(base), word=word, code=code, key=dominant,
        fraction=fraction, tile=tiles, landcover_json=str(path),
        sha256=str(document.get("sha256") or ""), frm=frm)


def infer_surface_for_spec(spec, landcover_json) -> Optional[InferredSurface]:
    """The runner's gate: infer only when the spec's surface is the
    unstated default (``unspecified`` with provenance ``default``) and a
    ``landcover.json`` is at hand; a surface the user or the prompt
    stated -- including a stated ``unspecified`` -- is never overridden.
    None when nothing is inferred."""
    if landcover_json is None:
        return None
    quantity = spec.surface
    if str(quantity.value) != UNSPECIFIED or str(quantity.source) != "default":
        return None
    return surface_from_landcover(landcover_json)


class InferredRoughnessWind(LogProfileWind):
    """The surface-layer log profile with an INFERRED roughness, carrying
    the whole horizontal wind (reference at the layer top, as the runner
    attaches it for a stated surface) and returning the
    ``environment.surface`` record with the null measurement it takes on
    the run: at every step the wind it wrote at the aircraft's height
    against the spec's wind (what the steady provider of an unstated
    surface would write)."""

    name = "log_profile_wind"

    def __init__(self, inferred: InferredSurface, reference_speed_mps: float,
                 from_deg: float,
                 reference_height_m: float = LogProfileWind.SURFACE_LAYER_TOP_M) -> None:
        super().__init__(reference_speed_mps, from_deg,
                         reference_height_m=reference_height_m,
                         terrain=inferred.surface.roughness)
        self.inferred = inferred
        self.samples = 0
        self.first_agl_m: Optional[float] = None
        self.peak: Optional[Dict[str, float]] = None

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        with_mps = self.speed_at(position.agl_m)
        without_mps = self.reference_speed_mps
        self.samples += 1
        if self.first_agl_m is None:
            self.first_agl_m = float(position.agl_m)
        diff = abs(with_mps - without_mps)
        if self.peak is None or diff > self.peak["difference_mps"]:
            self.peak = {"agl_m": float(position.agl_m), "time_s": float(time_s),
                         "with_mps": float(with_mps), "without_mps": float(without_mps),
                         "difference_mps": float(diff)}
        return WindNED.from_meteorological(with_mps, self.from_deg)

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(), "inferred_surface": self.inferred.provenance()}

    def applied_variables(self) -> List[AppliedVariable]:
        return [self.applied_variable()]

    def applied_variable(self) -> AppliedVariable:
        """The record. Refuses to record a run that was never stepped: a
        null test without a measurement would assert, not measure."""
        if self.peak is None:
            raise ValueError("InferredRoughnessWind.wind_at was never called; there is "
                             "no measurement at the aircraft to record")
        inf = self.inferred
        table_z0 = LogProfileWind.ROUGHNESS_M[inf.surface.roughness]
        readback = Readback(
            property="log_profile_wind.z0_m", value=float(self.z0_m), written=float(table_z0),
            tolerance=0.0, tolerance_kind="absolute",
            basis=("the z0 the log profile USES (LogProfileWind.z0_m, set from the class's "
                   "roughness key at construction) against the Davenport-Wieringa table "
                   "value for that key; grades the provider's store, not JSBSim's -- the "
                   "wind properties the stack writes every step read back exact before and "
                   "after a step (measured on the c172p, tests/test_surface_inference.py)"))
        peak = self.peak
        null_test = NullTest(
            quantity="horizontal wind at the aircraft, inferred roughness against the "
                     "spec's wind (the unstated surface's steady provider), at the sample "
                     "of peak difference",
            unit="kt", with_value=peak["with_mps"] / MPS_PER_KT,
            without_value=peak["without_mps"] / MPS_PER_KT,
            threshold=NULL_WIND_THRESHOLD_KT, kind="reached",
            note=(f"measured on this run at every step: with = the log profile's wind at the "
                  f"aircraft's AGL (z0 {self.z0_m} m, reference {self.reference_speed_mps:.3f} "
                  f"m/s at {self.reference_height_m:g} m); without = the spec's wind, which is "
                  f"what the steady provider writes when no surface is stated; peak at "
                  f"{peak['agl_m']:.1f} m AGL, t = {peak['time_s']:.2f} s, over {self.samples} "
                  f"steps (first sample {self.first_agl_m:.1f} m AGL); the two-flight pair "
                  f"through core/record_null.run_null_pair is measured in "
                  f"tests/test_surface_inference.py"))
        model = Model(
            name="neutral surface-layer log wind profile with an inferred roughness",
            standard=LogProfileWind.STANDARD, version="Stull 1988 Table 9-6",
            parameters={"z0_m": self.z0_m, "roughness": inf.surface.roughness,
                        "reference_height_m": self.reference_height_m,
                        "reference_speed_mps": self.reference_speed_mps,
                        "surface_layer_top_m": self.SURFACE_LAYER_TOP_M,
                        "dominance_threshold": inf.threshold},
            references=(STULL_TABLE,
                        "ESA WorldCover 10 m 2021 v200 (the dominant class; CC BY 4.0)"))
        return AppliedVariable(
            name="environment.surface",
            value=inf.surface.roughness, unit="word", source=inf.source,
            model=model.name,
            parameters={"surface_word": inf.word, "z0_m": self.z0_m,
                        "dominant_code": inf.code, "dominant_class": inf.key,
                        "dominant_fraction": inf.fraction, "threshold": inf.threshold,
                        "tile": inf.tile, "landcover_json": inf.landcover_json,
                        "landcover_sha256": inf.sha256,
                        "map_row": f"{inf.code} -> {inf.word} -> {inf.surface.roughness}",
                        "roughness_map": {str(k): v for k, v in sorted(ROUGHNESS_OF_COVER.items())},
                        "thermals": None,
                        "peak": dict(peak), "samples": self.samples},
            references=model.references,
            properties_written=JSBSIM_WIND_PROPERTIES,
            telemetry_columns=EFFECT_CHANNELS,
            frame_keys=(),
            null_test=null_test,
            not_claimed=(
                "roughness only: no thermal forcing, season, vegetation, building or "
                "visual is inferred from the land cover; the thermals a stated word "
                "would attach are deliberately not attached",
                "the dominant class is WorldCover's estimate (76.7 % overall accuracy "
                "per its manual) over the whole bake, not the cover under the track",
                "z0 'smooth' for snow and bare is a stated choice, not a table row",
                "the readback grades the provider's z0, not a per-step JSBSim readback of "
                "the wind property (measured exact once, not every step)",
                "the trim is solved in the spec's wind (configure_from_spec), a stated "
                "approximation below the 300 m layer top",
            ),
            frm=inf.frm, std=inf.std, readback=readback,
            jsbsim_writes=tuple(JsbsimWrite(p, "every step (the stack sums the wind "
                                                "providers and writes the total)")
                                for p in JSBSIM_WIND_PROPERTIES),
            model_block=model)
