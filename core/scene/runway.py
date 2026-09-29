"""The runway scene family (blueprint section 4, work item W2): the
geometry refused by name, the ICAO Annex 14 section 5.2 markings raster,
the section 5.3 light positions with the photometry named as missing, and
the ``flatten_pad`` -- a NEW bake whose heightfield holds the runway's
plane over its footprint plus a graded shoulder.

:class:`RunwaySpec` is the resolved runway: ``designator`` (``09``,
``27L``), the threshold's latitude and longitude, ``heading_deg`` (true,
as the spec states headings; no magnetic variation is modelled, so the
designator is checked against this heading directly -- stated),
``length_m``, ``width_m``, ``surface`` (a word of :data:`SURFACES`) and
``markings`` (``standard`` = the five Annex 14 elements, ``none``, or a
list of element words). :func:`problems` is the ONE list the validator
(``validate_runway``, a patch) and the constructor refuse from:

* ``runway.geometry`` -- length outside :data:`LENGTH_RANGE_M`, width
  outside :data:`WIDTH_RANGE_M`, heading outside [0, 360), a threshold
  that is not a coordinate pair, a designator that is not ``NN[LRC]``, or
  a designator whose number is not the heading's nearest tenth (Annex 14
  5.2.2.4 [unverified here]);
* ``runway.taxonomy`` -- a surface word outside :data:`SURFACES`;
* ``runway.markings`` -- a marking set the raster cannot draw: an element
  word outside :data:`MARKING_ELEMENTS`, or a width below the threshold
  stripe table's first row (18 m) with threshold stripes asked;
* ``runway.terrain_mismatch`` (:func:`flatten_pad`) -- the runway's two
  ends differ in bake height by more than the pad's tolerance
  (:data:`MAX_LONGITUDINAL_SLOPE` x length, Annex 14 3.1.13's 2 %
  [unverified here]) before flattening, or the runway does not lie on the
  bake.

The markings raster (:func:`markings_raster`) is drawn at
:data:`PX_M` = 0.1 m per pixel, row 0 the threshold, column 0 the left
edge looking along the heading, one byte per pixel (1 = painted), from a
list of axis-aligned rectangles that never overlap, so the analytic area
is their sum and the raster's painted area is measured against it
(:func:`measure_markings`; the relative error is held to
:data:`MARKING_AREA_TOL` = 1 %). The elements and their dimensions --
threshold stripes by runway width (Annex 14 5.2.4: 4/6/8/12/16 stripes at
18/23/30/45/60 m), the designator (9 m numerals of 1.5 m stroke, block
glyphs here, NOT the Figure 5-3 form), the centreline (0.9 m wide, 30 m
stripes with 20 m gaps), the aiming point (Table 5-1 by runway length) and
the touchdown zone (22.5 x 3 m pairs at 150 m intervals, count by length)
-- are transcribed from memory and marked ``[unverified here]``
throughout; a pair whose extent would overlap the aiming point is omitted
(stated).

The lights (:func:`light_positions`, Annex 14 5.3): edge lights in two
rows 3 m outside the edges at 60 m intervals, threshold lights across the
threshold at 3 m, end lights at 6 m, centreline lights at 15 m where the
runway is at least :data:`CENTRELINE_LIGHTS_MIN_LENGTH_M` long (a stated
choice for "where applicable"); each light carries a position, a kind and
a colour word, and :data:`PHOTOMETRY` names the Appendix 2 isocandela
values as NOT transcribed -- the missing photometry, never invented.

What is NOT claimed: taxiways, aprons, signage, photometry, stopways,
displaced thresholds, magnetic variation; the Annex 14 numbers beyond
memory; ground-roll validation (P8 stays open: nothing here flies a
landing); nothing engine-side (the runway mesh, the draped raster, the
lights' rendering and the ID pass are Windows steps). The pad changes the
heights the physics ground callback reads; it changes no physics model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..records import AppliedVariable, Model, NullTest, records_block

#: Resolution of the markings raster, metres per pixel.
PX_M = 0.1
#: The raster's painted area is held to this relative error of the
#: rectangles' analytic sum (edges snap to the 0.1 m grid).
MARKING_AREA_TOL = 0.01

#: Geometry ranges (Annex 14 gives no single range; these bound what the
#: raster and the pad can draw: a 300 m strip to the longest civil runways).
LENGTH_RANGE_M = (300.0, 5500.0)
#: 18 m is the threshold stripe table's first row; 80 m bounds the raster.
WIDTH_RANGE_M = (18.0, 80.0)
#: Annex 14 3.1.13: the longitudinal slope limit (2 % for code 1 and 2
#: [unverified here]); the pad's end-to-end tolerance is this times the length.
MAX_LONGITUDINAL_SLOPE = 0.02
#: The graded shoulder outside the footprint over which the pad blends
#: back into the bake (a stated choice: two GLO-30 pixels).
DEFAULT_SHOULDER_M = 60.0
#: The pad's null test: h_agl at the threshold, with against without the
#: pad, must move at least this (twice the altitude floor 0.5 m; the
#: measured pair in tests/test_runway.py moves 3.18 m).
PAD_NULL_THRESHOLD_M = 1.0

#: The surface taxonomy: a word the spec may state. Friction is NOT
#: modelled from it (the gear model is JSBSim's own); the word is a
#: scene-dressing and a record.
SURFACES: Dict[str, str] = {
    "asphalt": "paved, dark; markings white",
    "concrete": "paved, light; markings white",
    "grass": "unpaved turf; markings as stated, no lights implied",
    "gravel": "unpaved aggregate",
    "dirt": "unpaved earth",
}

#: The five Annex 14 section 5.2 elements this raster draws.
MARKING_ELEMENTS = ("threshold", "designator", "centreline", "aiming_point", "touchdown_zone")
MARKING_WORDS = ("standard", "none")

#: Annex 14 section 5.2 dimensions, transcribed from memory [unverified here].
THRESHOLD_STRIPE_START_M = 6.0
THRESHOLD_STRIPE_LENGTH_M = 30.0
THRESHOLD_STRIPE_WIDTH_M = 1.8
THRESHOLD_EDGE_MARGIN_M = 3.0
#: (runway width, stripe count): the count of the largest row not above
#: the width (5.2.4.6).
THRESHOLD_STRIPES_BY_WIDTH = ((18.0, 4), (23.0, 6), (30.0, 8), (45.0, 12), (60.0, 16))
DESIGNATOR_GAP_AFTER_STRIPES_M = 12.0
DESIGNATOR_HEIGHT_M = 9.0
DESIGNATOR_GLYPH_WIDTH_M = 6.0
DESIGNATOR_STROKE_M = 1.5
DESIGNATOR_GLYPH_GAP_M = 1.5
CENTRELINE_GAP_AFTER_DESIGNATOR_M = 12.0
CENTRELINE_WIDTH_M = 0.9
CENTRELINE_STRIPE_M = 30.0
CENTRELINE_GAP_M = 20.0
#: Table 5-1 rows (min runway length, distance from threshold, stripe
#: length, stripe width, lateral spacing between inner edges).
AIMING_POINT_TABLE = ((0.0, 150.0, 30.0, 4.0, 6.0), (800.0, 250.0, 30.0, 4.0, 6.0),
                      (1200.0, 300.0, 45.0, 6.0, 9.0), (2400.0, 400.0, 45.0, 6.0, 9.0))
TOUCHDOWN_ZONE_INTERVAL_M = 150.0
TOUCHDOWN_ZONE_LENGTH_M = 22.5
TOUCHDOWN_ZONE_WIDTH_M = 3.0
TOUCHDOWN_ZONE_SPACING_M = 18.0
#: (min runway length, number of stripe pairs) (5.2.7.4).
TOUCHDOWN_ZONE_PAIRS = ((0.0, 1), (900.0, 2), (1200.0, 3), (1500.0, 4), (2400.0, 6))

#: Annex 14 section 5.3 light spacings [unverified here].
EDGE_LIGHT_SPACING_M = 60.0
EDGE_LIGHT_OFFSET_M = 3.0
THRESHOLD_LIGHT_SPACING_M = 3.0
END_LIGHT_SPACING_M = 6.0
CENTRELINE_LIGHT_SPACING_M = 15.0
CENTRELINE_LIGHTS_MIN_LENGTH_M = 1200.0
#: The photometry, named as missing: Appendix 2's isocandela diagrams
#: give the intensity per light; none is transcribed here and none is invented.
PHOTOMETRY: Dict[str, Any] = {
    "candela": None,
    "basis": "ICAO Annex 14 Vol I Appendix 2 isocandela diagrams: NOT transcribed; the "
             "intensity of every light is the missing photometry (positions and colours "
             "only are stated)",
}

DESIGNATOR_RE = re.compile(r"^(0[1-9]|[12][0-9]|3[0-6])([LRC])?$")
DOCUMENT_VERSION = 1


class RunwayError(Exception):
    """A runway refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


def _number(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def designator_number_for_heading(heading_deg: float) -> int:
    """Annex 14 5.2.2.4: the whole number nearest one tenth of the
    azimuth, 36 for a heading rounding to 0 [unverified here]. A half
    rounds up (265 -> 27), never to even as Python's round() would."""
    number = int(math.floor(float(heading_deg) / 10.0 + 0.5)) % 36
    return 36 if number == 0 else number


def marking_elements(markings) -> Tuple[str, ...]:
    """The element words a ``markings`` value names (``standard`` = all
    five, ``none`` = none, a list = those). Refuses ``runway.markings``."""
    if markings is None or markings == "standard":
        return MARKING_ELEMENTS
    if markings == "none":
        return ()
    if isinstance(markings, str):
        raise RunwayError("runway.markings",
                          f"marking set {markings!r} is not one of {list(MARKING_WORDS)} "
                          f"or a list of {list(MARKING_ELEMENTS)}")
    if not isinstance(markings, (list, tuple)):
        raise RunwayError("runway.markings", f"marking set {markings!r} is not a word or a list")
    out: List[str] = []
    for word in markings:
        if word not in MARKING_ELEMENTS:
            raise RunwayError("runway.markings",
                              f"marking element {word!r} is not one this raster draws "
                              f"({list(MARKING_ELEMENTS)})")
        if word not in out:
            out.append(word)
    return tuple(out)


def stripe_count_for_width(width_m: float) -> int:
    """The threshold stripe count for a runway width (the largest table
    row not above it); ``runway.markings`` below the first row."""
    count = None
    for row_width, row_count in THRESHOLD_STRIPES_BY_WIDTH:
        if float(width_m) >= row_width:
            count = row_count
    if count is None:
        raise RunwayError("runway.markings",
                          f"a {width_m:g} m wide runway has no threshold stripe row "
                          f"(the table starts at {THRESHOLD_STRIPES_BY_WIDTH[0][0]:g} m)")
    return count


def problems(designator, threshold_lat_deg, threshold_lon_deg, heading_deg, length_m,
             width_m, surface, markings="standard") -> List[RunwayError]:
    """Every refusal a runway's stated values earn, in one list."""
    out: List[RunwayError] = []
    if not isinstance(designator, str) or not DESIGNATOR_RE.match(designator):
        out.append(RunwayError("runway.geometry",
                               f"designator {designator!r} is not NN or NN[LRC] with NN in 01..36"))
    lat, lon = _number(threshold_lat_deg), _number(threshold_lon_deg)
    if lat is None or lon is None or not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        out.append(RunwayError("runway.geometry",
                               f"threshold ({threshold_lat_deg!r}, {threshold_lon_deg!r}) is not "
                               f"a latitude, longitude pair"))
    heading = _number(heading_deg)
    if heading is None or not (0.0 <= heading < 360.0):
        out.append(RunwayError("runway.geometry",
                               f"heading {heading_deg!r} is not in [0, 360) degrees"))
    elif isinstance(designator, str) and DESIGNATOR_RE.match(designator):
        number = int(designator[:2])
        expected = designator_number_for_heading(heading)
        if number != expected:
            out.append(RunwayError(
                "runway.geometry",
                f"designator {designator!r} does not name the heading {heading:g} deg "
                f"(its nearest tenth is {expected:02d}; no magnetic variation is modelled)"))
    length = _number(length_m)
    if length is None or not (LENGTH_RANGE_M[0] <= length <= LENGTH_RANGE_M[1]):
        out.append(RunwayError("runway.geometry",
                               f"length {length_m!r} m is outside {LENGTH_RANGE_M}"))
    width = _number(width_m)
    if width is None or not (WIDTH_RANGE_M[0] <= width <= WIDTH_RANGE_M[1]):
        out.append(RunwayError("runway.geometry",
                               f"width {width_m!r} m is outside {WIDTH_RANGE_M}"))
    if surface not in SURFACES:
        out.append(RunwayError("runway.taxonomy",
                               f"surface {surface!r} is not one of {sorted(SURFACES)}"))
    try:
        elements = marking_elements(markings)
        if "threshold" in elements and width is not None:
            stripe_count_for_width(width)
        if not out:
            # The whole set drawn once: an element that does not fit the
            # runway (a touchdown-zone pair wider than a narrow runway) is
            # refused here, not at the raster.
            marking_rectangles(RunwaySpec.__new__(RunwaySpec), designator=designator,
                               length_m=length, width_m=width, elements=elements)
    except RunwayError as exc:
        out.append(exc)
    return out


@dataclass(frozen=True)
class RunwaySpec:
    """The resolved runway; refuses by name in the constructor."""

    designator: str
    threshold_lat_deg: float
    threshold_lon_deg: float
    heading_deg: float
    length_m: float
    width_m: float
    surface: str = "asphalt"
    markings: Any = "standard"

    def __post_init__(self) -> None:
        found = problems(self.designator, self.threshold_lat_deg, self.threshold_lon_deg,
                         self.heading_deg, self.length_m, self.width_m, self.surface,
                         self.markings)
        if found:
            raise found[0]

    @property
    def elements(self) -> Tuple[str, ...]:
        return marking_elements(self.markings)

    def to_dict(self) -> Dict[str, Any]:
        return {"designator": self.designator, "threshold_lat_deg": float(self.threshold_lat_deg),
                "threshold_lon_deg": float(self.threshold_lon_deg),
                "heading_deg": float(self.heading_deg), "length_m": float(self.length_m),
                "width_m": float(self.width_m), "surface": self.surface,
                "markings": list(self.elements)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RunwaySpec":
        return cls(designator=data["designator"], threshold_lat_deg=data["threshold_lat_deg"],
                   threshold_lon_deg=data["threshold_lon_deg"], heading_deg=data["heading_deg"],
                   length_m=data["length_m"], width_m=data["width_m"],
                   surface=data.get("surface", "asphalt"), markings=data.get("markings", "standard"))

    @classmethod
    def from_block(cls, block) -> Optional["RunwaySpec"]:
        """From the spec's ``runway`` ProvenancedBlock (None when no
        designator is stated: no runway)."""
        if block is None or block.designator.value is None:
            return None
        return cls(designator=block.designator.value,
                   threshold_lat_deg=block.threshold_lat_deg.value,
                   threshold_lon_deg=block.threshold_lon_deg.value,
                   heading_deg=block.heading_deg.value, length_m=block.length_m.value,
                   width_m=block.width_m.value, surface=block.surface.value,
                   markings=block.markings.value)


# -- geometry in the bake's CRS ------------------------------------------------------

@dataclass(frozen=True)
class RunwayGeometry:
    """The runway as a rotated rectangle in a projected CRS: threshold
    ``(x0, y0)``, unit vector ``along`` from the heading (grid north; the
    grid convergence is not applied, stated), ``across`` to the right."""

    crs: str
    x0: float
    y0: float
    along: Tuple[float, float]
    across: Tuple[float, float]
    length_m: float
    width_m: float

    @classmethod
    def for_spec(cls, spec: RunwaySpec, crs: str) -> "RunwayGeometry":
        if crs.upper() in ("EPSG:4326", "OGC:CRS84"):
            raise RunwayError("runway.terrain_mismatch",
                              "the bake is not in a projected CRS; a runway needs metres")
        from pyproj import Transformer

        forward = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        x0, y0 = forward.transform(float(spec.threshold_lon_deg), float(spec.threshold_lat_deg))
        h = math.radians(float(spec.heading_deg))
        along = (math.sin(h), math.cos(h))
        across = (math.cos(h), -math.sin(h))
        return cls(crs=str(crs), x0=float(x0), y0=float(y0), along=along, across=across,
                   length_m=float(spec.length_m), width_m=float(spec.width_m))

    def to_along_across(self, x, y):
        """(s along from the threshold, t across from the centreline),
        vectorised over numpy arrays or scalars."""
        dx, dy = np.asarray(x, dtype=float) - self.x0, np.asarray(y, dtype=float) - self.y0
        s = dx * self.along[0] + dy * self.along[1]
        t = dx * self.across[0] + dy * self.across[1]
        return s, t

    def point(self, s_m: float, t_m: float) -> Tuple[float, float]:
        return (self.x0 + s_m * self.along[0] + t_m * self.across[0],
                self.y0 + s_m * self.along[1] + t_m * self.across[1])

    def corners(self) -> List[Tuple[float, float]]:
        hw = self.width_m / 2.0
        return [self.point(0.0, -hw), self.point(0.0, hw),
                self.point(self.length_m, hw), self.point(self.length_m, -hw)]

    def to_dict(self) -> Dict[str, Any]:
        return {"crs": self.crs, "threshold_xy": [self.x0, self.y0],
                "along": list(self.along), "across": list(self.across),
                "length_m": self.length_m, "width_m": self.width_m,
                "corners_xy": [list(c) for c in self.corners()],
                "end_xy": list(self.point(self.length_m, 0.0)),
                "convergence": "grid heading = stated heading (the grid convergence is not applied)"}


# -- markings -------------------------------------------------------------------------

def snap(value_m: float, px_m: float = PX_M) -> float:
    """A coordinate snapped to the raster grid (the nearest multiple of
    the pixel size), so a rectangle's analytic area IS its painted area
    and the measurement grades the rasteriser, not the rounding of edges
    that fall between pixels (measured: unsnapped 1.8 m stripes at a gap
    of 1.68 m cost 3 % of the area at 60 m width)."""
    return round(float(value_m) / px_m) * px_m


@dataclass(frozen=True)
class Rect:
    """An axis-aligned painted rectangle: ``s`` along from the threshold,
    ``t`` across from the centreline (right positive), in metres; the
    origin corner snapped to the grid, the size kept exact."""

    element: str
    s0: float
    s1: float
    t0: float
    t1: float

    @classmethod
    def at(cls, element: str, s0: float, length: float, t0: float, width: float) -> "Rect":
        s0, t0 = snap(s0), snap(t0)
        return cls(element, s0, s0 + float(length), t0, t0 + float(width))

    @property
    def area_m2(self) -> float:
        return (self.s1 - self.s0) * (self.t1 - self.t0)

    def overlaps(self, other: "Rect") -> bool:
        return (self.s0 < other.s1 and other.s0 < self.s1
                and self.t0 < other.t1 and other.t0 < self.t1)

    def to_dict(self) -> Dict[str, Any]:
        return {"element": self.element, "s0": self.s0, "s1": self.s1,
                "t0": self.t0, "t1": self.t1}


#: Block glyphs on a 7-segment frame (a, b, c, d, e, f, g = top,
#: upper-right, lower-right, bottom, lower-left, upper-left, middle), plus
#: L, R, C. NOT the Annex 14 Figure 5-3 form (stated).
_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg",
    "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
    "L": "def", "C": "adef", "R": "abefg",
}


def glyph_rects(char: str, s_top: float, t_left: float, height: float = DESIGNATOR_HEIGHT_M,
                width: float = DESIGNATOR_GLYPH_WIDTH_M, stroke: float = DESIGNATOR_STROKE_M,
                element: str = "designator") -> List[Rect]:
    """The non-overlapping rectangles of one block glyph: horizontals span
    the full width, verticals run between them, so the union's area is
    the sum. ``s_top`` is the glyph's top (nearest the threshold); a
    glyph reads correctly for a pilot on the threshold looking along."""
    segs = _SEGMENTS[char]
    s_top, t_left = snap(s_top), snap(t_left)
    h_mid_top = snap(s_top + (height - stroke) / 2.0)
    rects: List[Rect] = []
    # Horizontal bars: a (top), g (middle), d (bottom).
    if "a" in segs:
        rects.append(Rect(element, s_top, s_top + stroke, t_left, t_left + width))
    if "g" in segs:
        rects.append(Rect(element, h_mid_top, h_mid_top + stroke, t_left, t_left + width))
    if "d" in segs:
        rects.append(Rect(element, s_top + height - stroke, s_top + height, t_left, t_left + width))
    # Vertical bars between the horizontals' extents (never overlapping them).
    upper = (s_top + (stroke if "a" in segs else 0.0),
             h_mid_top if "g" in segs else (s_top + height - (stroke if "d" in segs else 0.0)))
    lower = (h_mid_top + stroke if "g" in segs else (s_top + (stroke if "a" in segs else 0.0)),
             s_top + height - (stroke if "d" in segs else 0.0))
    if "g" not in segs:
        # No middle bar: a side's two verticals are one full-height bar.
        if "f" in segs or "e" in segs:
            rects.append(Rect(element, upper[0], upper[1], t_left, t_left + stroke))
        if "b" in segs or "c" in segs:
            rects.append(Rect(element, upper[0], upper[1], t_left + width - stroke, t_left + width))
        return rects
    if "f" in segs:
        rects.append(Rect(element, upper[0], upper[1], t_left, t_left + stroke))
    if "b" in segs:
        rects.append(Rect(element, upper[0], upper[1], t_left + width - stroke, t_left + width))
    if "e" in segs:
        rects.append(Rect(element, lower[0], lower[1], t_left, t_left + stroke))
    if "c" in segs or char == "R":
        # For R the leg: a stroke from the middle bar to the bottom on the right.
        rects.append(Rect(element, lower[0], lower[1], t_left + width - stroke, t_left + width))
    return rects


def _designator_end(width_m: float) -> float:
    return THRESHOLD_STRIPE_START_M + THRESHOLD_STRIPE_LENGTH_M + DESIGNATOR_GAP_AFTER_STRIPES_M + DESIGNATOR_HEIGHT_M


def marking_rectangles(spec: Optional[RunwaySpec], designator: Optional[str] = None,
                       length_m: Optional[float] = None, width_m: Optional[float] = None,
                       elements: Optional[Tuple[str, ...]] = None) -> Tuple[List[Rect], Dict[str, Any]]:
    """Every painted rectangle of the runway's marking set, and the
    counts (stripes per element) the raster is measured against. The
    keyword form lets :func:`problems` draw a set before a RunwaySpec
    exists."""
    if designator is None:
        designator = spec.designator
        length_m, width_m, elements = spec.length_m, spec.width_m, spec.elements
    L, W = float(length_m), float(width_m)
    rects: List[Rect] = []
    counts: Dict[str, Any] = {}
    if "threshold" in elements:
        n = stripe_count_for_width(W)
        span = W - 2.0 * THRESHOLD_EDGE_MARGIN_M
        gap = (span - n * THRESHOLD_STRIPE_WIDTH_M) / (n - 1)
        for i in range(n):
            t0 = -span / 2.0 + i * (THRESHOLD_STRIPE_WIDTH_M + gap)
            rects.append(Rect.at("threshold", THRESHOLD_STRIPE_START_M, THRESHOLD_STRIPE_LENGTH_M,
                                 t0, THRESHOLD_STRIPE_WIDTH_M))
        counts["threshold_stripes"] = n
    designator_end = THRESHOLD_STRIPE_START_M + THRESHOLD_STRIPE_LENGTH_M
    if "designator" in elements:
        s_top = THRESHOLD_STRIPE_START_M + THRESHOLD_STRIPE_LENGTH_M + DESIGNATOR_GAP_AFTER_STRIPES_M
        chars = list(designator[:2])
        total = len(chars) * DESIGNATOR_GLYPH_WIDTH_M + (len(chars) - 1) * DESIGNATOR_GLYPH_GAP_M
        t = -total / 2.0
        for char in chars:
            rects.extend(glyph_rects(char, s_top, t))
            t += DESIGNATOR_GLYPH_WIDTH_M + DESIGNATOR_GLYPH_GAP_M
        designator_end = s_top + DESIGNATOR_HEIGHT_M
        if len(designator) == 3:
            # The letter beyond the numerals, further from the threshold.
            s_letter = designator_end + DESIGNATOR_GLYPH_GAP_M
            rects.extend(glyph_rects(designator[2], s_letter, -DESIGNATOR_GLYPH_WIDTH_M / 2.0))
            designator_end = s_letter + DESIGNATOR_HEIGHT_M
        counts["designator_glyphs"] = len(designator)
    if "centreline" in elements:
        margin = designator_end + CENTRELINE_GAP_AFTER_DESIGNATOR_M
        s = margin
        stripes = 0
        while s + CENTRELINE_STRIPE_M <= L - margin:
            rects.append(Rect.at("centreline", s, CENTRELINE_STRIPE_M,
                                 -CENTRELINE_WIDTH_M / 2.0, CENTRELINE_WIDTH_M))
            stripes += 1
            s += CENTRELINE_STRIPE_M + CENTRELINE_GAP_M
        counts["centreline_stripes"] = stripes
    aiming = None
    if "aiming_point" in elements:
        row = AIMING_POINT_TABLE[0]
        for candidate in AIMING_POINT_TABLE:
            if L >= candidate[0]:
                row = candidate
        _, start, length, width, spacing = row
        if start + length <= L:
            for sign in (-1.0, 1.0):
                inner = spacing / 2.0
                t0, t1 = (inner, inner + width) if sign > 0 else (-inner - width, -inner)
                rects.append(Rect.at("aiming_point", start, length, t0, t1 - t0))
            aiming = (start, start + length)
            counts["aiming_point_stripes"] = 2
        else:
            counts["aiming_point_stripes"] = 0
    if "touchdown_zone" in elements:
        pairs = TOUCHDOWN_ZONE_PAIRS[0][1]
        for min_length, count in TOUCHDOWN_ZONE_PAIRS:
            if L >= min_length:
                pairs = count
        drawn = 0
        k = 1
        while drawn < pairs:
            s0 = k * TOUCHDOWN_ZONE_INTERVAL_M
            s1 = s0 + TOUCHDOWN_ZONE_LENGTH_M
            k += 1
            if s1 > L - THRESHOLD_STRIPE_START_M:
                break
            if aiming is not None and s0 < aiming[1] and aiming[0] < s1:
                continue                    # the aiming point takes this pair's place
            inner = TOUCHDOWN_ZONE_SPACING_M / 2.0
            rects.append(Rect.at("touchdown_zone", s0, TOUCHDOWN_ZONE_LENGTH_M, inner,
                                 TOUCHDOWN_ZONE_WIDTH_M))
            rects.append(Rect.at("touchdown_zone", s0, TOUCHDOWN_ZONE_LENGTH_M,
                                 -inner - TOUCHDOWN_ZONE_WIDTH_M, TOUCHDOWN_ZONE_WIDTH_M))
            drawn += 1
        counts["touchdown_zone_pairs"] = drawn
        counts["touchdown_zone_pairs_table"] = pairs
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if a.overlaps(b):
                raise ValueError(f"marking rectangles overlap: {a} and {b}")
    half = W / 2.0
    for rect in rects:
        if rect.t0 < -half or rect.t1 > half or rect.s0 < 0.0 or rect.s1 > L:
            raise RunwayError(
                "runway.markings",
                f"the {rect.element} marking does not fit a {L:g} x {W:g} m runway "
                f"(it reaches s {rect.s0:g}..{rect.s1:g} m, t {rect.t0:g}..{rect.t1:g} m); "
                f"state a marking set without it")
    return rects, counts


def markings_raster(spec: RunwaySpec, px_m: float = PX_M) -> Tuple[np.ndarray, List[Rect], Dict[str, Any]]:
    """The raster (rows along the runway from the threshold, columns
    across from the left edge), its rectangles and their counts."""
    rects, counts = marking_rectangles(spec)
    rows = int(round(float(spec.length_m) / px_m))
    cols = int(round(float(spec.width_m) / px_m))
    raster = np.zeros((rows, cols), dtype=np.uint8)
    half = float(spec.width_m) / 2.0
    for rect in rects:
        r0 = int(round(rect.s0 / px_m))
        r1 = int(round(rect.s1 / px_m))
        c0 = int(round((rect.t0 + half) / px_m))
        c1 = int(round((rect.t1 + half) / px_m))
        raster[max(r0, 0):min(r1, rows), max(c0, 0):min(c1, cols)] = 1
    return raster, rects, counts


def measure_markings(raster: np.ndarray, rects: Sequence[Rect], px_m: float = PX_M) -> Dict[str, Any]:
    """The painted area against the analytic sum, and the threshold
    stripe count read back from the raster itself (runs of painted
    columns across the stripes' middle row)."""
    painted = int(np.count_nonzero(raster))
    painted_area = painted * px_m * px_m
    analytic = float(sum(r.area_m2 for r in rects))
    error = abs(painted_area - analytic) / analytic if analytic > 0.0 else 0.0
    per_element: Dict[str, float] = {}
    for rect in rects:
        per_element[rect.element] = per_element.get(rect.element, 0.0) + rect.area_m2
    row = int(round((THRESHOLD_STRIPE_START_M + THRESHOLD_STRIPE_LENGTH_M / 2.0) / px_m))
    stripes_read = count_runs(raster[row]) if 0 <= row < raster.shape[0] else 0
    return {
        "painted_px": painted, "painted_area_m2": painted_area,
        "analytic_area_m2": analytic, "relative_error": error,
        "tolerance": MARKING_AREA_TOL, "within_tolerance": error <= MARKING_AREA_TOL,
        "analytic_by_element_m2": per_element,
        "threshold_stripes_read": stripes_read,
        "px_m": px_m, "shape": [int(raster.shape[0]), int(raster.shape[1])],
    }


def count_runs(row: np.ndarray) -> int:
    """The number of painted runs along one raster row."""
    values = np.asarray(row) != 0
    if values.size == 0:
        return 0
    starts = values & ~np.concatenate(([False], values[:-1]))
    return int(np.count_nonzero(starts))


def markings_block(spec: RunwaySpec, png_path, counts: Dict[str, Any],
                   measurement: Dict[str, Any]) -> Dict[str, Any]:
    """The document's ``markings`` block: the raster file and its sha256,
    the elements, the counts, the measurement, and the threshold stripe
    placement the verifier reads the raster against."""
    png_path = Path(png_path)
    return {"file": str(png_path), "sha256": sha256_of(png_path), "elements": list(spec.elements),
            "counts": counts, "measurement": measurement,
            "threshold_stripe_start_m": THRESHOLD_STRIPE_START_M,
            "threshold_stripe_length_m": THRESHOLD_STRIPE_LENGTH_M,
            "row_0": "the threshold; columns across from the left edge looking along the heading",
            "dimensions_basis": "ICAO Annex 14 Vol I section 5.2, Table 5-1, from memory "
                                "[unverified here]; block glyphs, not Figure 5-3; rectangle "
                                "origins snapped to the 0.1 m grid (stated)"}


def write_markings_png(raster: np.ndarray, path) -> Path:
    """The raster as an 8-bit grey PNG (0 / 255): what the engine drapes
    and what the verifier reads back."""
    from PIL import Image

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.asarray(raster, dtype=np.uint8) * 255).astype(np.uint8)).save(path)
    return path


# -- lights ------------------------------------------------------------------------------

def light_positions(spec: RunwaySpec) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Section 5.3 positions in (s, t) metres with kind and colour, and
    the counts; the photometry is :data:`PHOTOMETRY` (missing, named)."""
    L, W = float(spec.length_m), float(spec.width_m)
    lights: List[Dict[str, Any]] = []
    n_edge = int(math.floor(L / EDGE_LIGHT_SPACING_M)) + 1
    for i in range(n_edge):
        s = min(i * EDGE_LIGHT_SPACING_M, L)
        for sign in (-1.0, 1.0):
            lights.append({"kind": "edge", "s_m": s, "t_m": sign * (W / 2.0 + EDGE_LIGHT_OFFSET_M),
                           "colour": "white"})
    n_threshold = int(math.floor(W / THRESHOLD_LIGHT_SPACING_M)) + 1
    for i in range(n_threshold):
        t = -W / 2.0 + i * THRESHOLD_LIGHT_SPACING_M
        lights.append({"kind": "threshold", "s_m": 0.0, "t_m": t, "colour": "green"})
    n_end = int(math.floor(W / END_LIGHT_SPACING_M)) + 1
    for i in range(n_end):
        t = -W / 2.0 + i * END_LIGHT_SPACING_M
        lights.append({"kind": "end", "s_m": L, "t_m": t, "colour": "red"})
    centreline_applicable = L >= CENTRELINE_LIGHTS_MIN_LENGTH_M
    n_centre = 0
    if centreline_applicable:
        n_centre = int(math.floor(L / CENTRELINE_LIGHT_SPACING_M)) + 1
        for i in range(n_centre):
            lights.append({"kind": "centreline", "s_m": min(i * CENTRELINE_LIGHT_SPACING_M, L),
                           "t_m": 0.0, "colour": "white"})
    counts = {"edge": 2 * n_edge, "threshold": n_threshold, "end": n_end,
              "centreline": n_centre, "total": len(lights),
              "centreline_applicable": centreline_applicable,
              "centreline_basis": f"centreline lights where the runway is at least "
                                  f"{CENTRELINE_LIGHTS_MIN_LENGTH_M:g} m long (a stated choice "
                                  f"for Annex 14's 'where applicable')",
              "spacings_m": {"edge": EDGE_LIGHT_SPACING_M, "threshold": THRESHOLD_LIGHT_SPACING_M,
                             "end": END_LIGHT_SPACING_M, "centreline": CENTRELINE_LIGHT_SPACING_M},
              "photometry": dict(PHOTOMETRY)}
    return lights, counts


# -- the flatten pad --------------------------------------------------------------------

def flatten_pad(heightfield, spec: RunwaySpec, shoulder_m: float = DEFAULT_SHOULDER_M,
                tolerance_m: Optional[float] = None, name: Optional[str] = None):
    """A NEW heightfield: the runway's least-squares plane over its
    footprint, blended back into the bake over ``shoulder_m`` outside it
    (smoothstep), every other pixel the bake's own. Refuses
    ``runway.terrain_mismatch`` when the two ends' bake heights differ by
    more than ``tolerance_m`` (default MAX_LONGITUDINAL_SLOPE x length)
    BEFORE anything is flattened, or when the footprint holds fewer than
    three bake pixels. Returns ``(field, statistics)``; the parent is
    never modified (a new key, a new sha256)."""
    from ..terrain.heightfield import Heightfield

    geometry = RunwayGeometry.for_spec(spec, heightfield.georeference.crs)
    L, W = geometry.length_m, geometry.width_m
    tol = float(tolerance_m) if tolerance_m is not None else MAX_LONGITUDINAL_SLOPE * L
    x_thr, y_thr = geometry.point(0.0, 0.0)
    x_end, y_end = geometry.point(L, 0.0)
    if not (heightfield.contains(x_thr, y_thr) and heightfield.contains(x_end, y_end)):
        raise RunwayError("runway.terrain_mismatch",
                          f"runway {spec.designator} does not lie on the bake "
                          f"{heightfield.name!r} (an end is off the raster)")
    z_thr = float(heightfield.elevation_at(x_thr, y_thr))
    z_end = float(heightfield.elevation_at(x_end, y_end))
    if abs(z_end - z_thr) > tol:
        raise RunwayError(
            "runway.terrain_mismatch",
            f"the bake differs by {abs(z_end - z_thr):.1f} m between the ends of runway "
            f"{spec.designator} ({z_thr:.1f} m at the threshold, {z_end:.1f} m at the end); "
            f"the pad tolerance is {tol:.1f} m ({MAX_LONGITUDINAL_SLOPE:.0%} of {L:g} m)")
    g = heightfield.georeference
    z = heightfield.elevations()
    cols = g.origin_x_m + np.arange(heightfield.width, dtype=float) * g.pixel_size_m
    rows = g.origin_y_m - np.arange(heightfield.height, dtype=float) * g.pixel_size_m
    xs, ys = np.meshgrid(cols, rows)
    s, t = geometry.to_along_across(xs, ys)
    inside = (s >= 0.0) & (s <= L) & (np.abs(t) <= W / 2.0)
    n_inside = int(np.count_nonzero(inside))
    if n_inside < 3:
        raise RunwayError("runway.terrain_mismatch",
                          f"runway {spec.designator} covers {n_inside} bake pixel(s); a plane "
                          f"needs at least three")
    a_mat = np.column_stack([np.ones(n_inside), s[inside], t[inside]])
    coefficients, _, _, _ = np.linalg.lstsq(a_mat, z[inside], rcond=None)
    a, b, c = (float(v) for v in coefficients)
    plane = a + b * s + c * t
    ds = np.maximum(0.0, np.maximum(-s, s - L))
    dt = np.maximum(0.0, np.abs(t) - W / 2.0)
    d = np.hypot(ds, dt)
    shoulder = (~inside) & (d <= float(shoulder_m)) & (float(shoulder_m) > 0.0)
    u = np.clip(d / float(shoulder_m), 0.0, 1.0) if float(shoulder_m) > 0.0 else np.ones_like(d)
    weight = u * u * (3.0 - 2.0 * u)          # 0 at the footprint edge, 1 at the shoulder's end
    new = z.copy()
    new[inside] = plane[inside]
    new[shoulder] = plane[shoulder] + (z[shoulder] - plane[shoulder]) * weight[shoulder]
    field = Heightfield.from_elevations(
        new, g, name=name or f"{heightfield.name}_runway_{spec.designator}",
        provenance=dict(heightfield.provenance))
    dz = new - z
    touched = inside | shoulder
    requantised = field.elevations() - new
    cell = g.pixel_size_m * g.pixel_size_m
    plane_thr = a
    plane_end = a + b * L
    statistics = {
        "plane": {"a_m": a, "b_per_m": b, "c_per_m": c,
                  "longitudinal_slope": b, "cross_slope": c,
                  "fit": "least squares over the footprint's bake pixels (z = a + b s + c t)"},
        "footprint_pixels": n_inside, "shoulder_pixels": int(np.count_nonzero(shoulder)),
        "shoulder_m": float(shoulder_m), "blend": "smoothstep over the shoulder distance",
        "tolerance_m": tol, "tolerance_basis": f"{MAX_LONGITUDINAL_SLOPE:.0%} of the length "
                                              f"(Annex 14 3.1.13 [unverified here])",
        "threshold": {"bake_z_m": z_thr, "plane_z_m": plane_thr, "dz_m": plane_thr - z_thr},
        "end": {"bake_z_m": z_end, "plane_z_m": plane_end, "dz_m": plane_end - z_end},
        "ends_difference_m": abs(z_end - z_thr),
        "max_cut_m": float(-dz[touched].min()) if touched.any() else 0.0,
        "max_fill_m": float(dz[touched].max()) if touched.any() else 0.0,
        "mean_abs_dz_footprint_m": float(np.abs(dz[inside]).mean()),
        "cut_volume_m3": float(-dz[touched][dz[touched] < 0].sum() * cell) if touched.any() else 0.0,
        "fill_volume_m3": float(dz[touched][dz[touched] > 0].sum() * cell) if touched.any() else 0.0,
        "requantisation_max_m": float(np.abs(requantised).max()),
        "quantisation_m": {"parent": heightfield.quantisation_m, "pad": field.quantisation_m},
        "untouched_pixels_moved_m": float(np.abs(requantised[~touched]).max()) if (~touched).any() else 0.0,
    }
    return field, statistics


# -- the null test, measured through JSBSim --------------------------------------------------

def measure_pad_null(pad_stem, parent_stem, spec: RunwaySpec, aircraft: str = "c172p",
                     seconds: float = 1.0, agl_m: float = 50.0, airspeed_kt: float = 90.0) -> Dict[str, Any]:
    """The record's null test: the same short flight over the pad bake and
    over its parent, the aircraft trimmed above the threshold; the peak
    |h_agl(with) - h_agl(without)| over the recorded samples against
    :data:`PAD_NULL_THRESHOLD_M`. The first sample holds the initial
    condition's terrain (the spec's), the bake's from the second (the
    ground callback writes before each step; measured in tests)."""
    import contextlib
    import io

    from ..nl.compiler import compile_prompt
    from ..scenario.runner import run_spec
    from ..terrain.ground import TerrainGround
    from ..terrain.heightfield import Heightfield

    pad = Heightfield.read(pad_stem)
    parent = Heightfield.read(parent_stem)
    geometry = RunwayGeometry.for_spec(spec, pad.georeference.crs)
    x, y = geometry.point(0.0, 0.0)
    plane_z = float(pad.elevation_at(x, y))
    altitude = plane_z + float(agl_m)

    def fly(field):
        scenario = compile_prompt(f"fly the {aircraft} at {altitude:.0f} m and "
                                  f"{airspeed_kt:g} kt for {max(1, int(round(seconds)))} seconds")
        scenario.set("hold_state", False, frm="runway pad null test")
        scenario.set("latitude", float(spec.threshold_lat_deg), frm="the runway threshold")
        scenario.set("longitude", float(spec.threshold_lon_deg), frm="the runway threshold")
        scenario.set("terrain_elevation", plane_z, frm="the pad plane at the threshold")
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_spec(scenario, terrain_ground=TerrainGround(field), assert_closure=False)
        return result

    with_result = fly(pad)
    without_result = fly(parent)
    a = np.asarray(with_result.telemetry.columns["agl_m"], dtype=float)
    b = np.asarray(without_result.telemetry.columns["agl_m"], dtype=float)
    n = min(a.size, b.size)
    diff = a[:n] - b[:n]
    k = int(np.argmax(np.abs(diff)))
    test = NullTest(
        quantity="h_agl above the runway threshold at the sample of peak |with - without|",
        unit="m", with_value=float(a[k]), without_value=float(b[k]),
        threshold=PAD_NULL_THRESHOLD_M, kind="reached",
        note=f"with = the {aircraft} over the pad bake, without = the same flight over the "
             f"parent bake; {n} samples compared, peak at sample {k}; output digests "
             f"{'differ' if with_result.output_digest != without_result.output_digest else 'are equal'}")
    return {"null_test": test.to_dict(), "samples": n, "peak_index": k,
            "with_digest": with_result.output_digest, "without_digest": without_result.output_digest,
            "aircraft": aircraft, "seconds": seconds, "agl_m": agl_m,
            "plane_z_at_threshold_m": plane_z,
            "parent_z_at_threshold_m": float(parent.elevation_at(x, y))}


# -- the document and the record --------------------------------------------------------------

def sha256_of(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def runway_variable(document: Dict[str, Any]) -> AppliedVariable:
    """The ``scene.runway`` record: the spec, the marking measurement, the
    stripe counts, the light counts with the photometry named missing,
    the pad statistics; the null test the pad measured through JSBSim
    (None, with the reason, when the document was written without it)."""
    spec = document["spec"]
    null = document.get("null_test")
    return AppliedVariable(
        name="scene.runway", value=spec["designator"], unit="word", source="user",
        model="ICAO Annex 14 Vol I sections 5.2 (markings) and 5.3 (lights); a least-squares "
              "runway plane flattened into a new bake with a graded shoulder",
        parameters={
            "spec": spec, "geometry": document["geometry"],
            "markings": document["markings"], "lights": document["lights"],
            "pad": document["pad"], "surface_note": SURFACES.get(spec["surface"]),
            "null_test_basis": (document.get("null_test_basis")
                                or "measured through JSBSim (measure_pad_null)"),
        },
        references=("ICAO Annex 14 Vol I, Aerodromes, ch. 5.2 and 5.3, Table 5-1, Appendix 2 "
                    "[unverified here]",),
        properties_written=(), telemetry_columns=("agl_m",), frame_keys=("state.agl_m",),
        null_test=None if null is None else NullTest.from_dict(null),
        model_block=Model(
            name="Annex 14 runway markings, lights and flatten pad",
            standard="ICAO Annex 14 Vol I ch. 5.2 / 5.3 [unverified here]", version="W2",
            parameters={"px_m": PX_M, "area_tolerance": MARKING_AREA_TOL,
                        "shoulder_m": document["pad"].get("statistics", {}).get("shoulder_m"),
                        "max_longitudinal_slope": MAX_LONGITUDINAL_SLOPE},
            references=("ICAO Annex 14 Vol I [unverified here]",)),
        frm=f"the spec's runway block: {spec['designator']} at ({spec['threshold_lat_deg']}, "
            f"{spec['threshold_lon_deg']}), {spec['length_m']:g} x {spec['width_m']:g} m",
        std="ICAO Annex 14 Vol I ch. 5.2, 5.3 (dimensions from memory, unverified here)",
        not_claimed=(
            "no taxiways, aprons, signage or stopways; no displaced threshold",
            "no photometry: Appendix 2's candela values are named as missing, never invented",
            "the Annex 14 dimensions are transcribed from memory and marked unverified",
            "no magnetic variation: the designator is checked against the stated heading",
            "no ground-roll validation (P8 stays open); the pad changes the ground height "
            "the physics reads and no physics model",
            "the grid convergence is not applied: the grid heading is the stated heading",
            "nothing engine-side is verified here (mesh, drape, lights, ID pass: Windows)",
        ))


def runway_document(spec: RunwaySpec, geometry: RunwayGeometry, markings: Dict[str, Any],
                    lights: Dict[str, Any], pad: Dict[str, Any],
                    null_test: Optional[Dict[str, Any]] = None,
                    null_test_basis: Optional[str] = None) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "document_version": DOCUMENT_VERSION,
        "spec": spec.to_dict(),
        "geometry": geometry.to_dict(),
        "markings": markings, "lights": lights, "pad": pad,
        "null_test": None if null_test is None else dict(null_test),
        "null_test_basis": null_test_basis or ("measured through JSBSim (measure_pad_null)"
                                               if null_test is not None else
                                               "not measured: the document was written "
                                               "without --null-test"),
        "not_claimed": ["no taxiways, aprons, signage, photometry; no ground-roll validation; "
                        "nothing engine-side verified here"],
    }
    document["applied_variables"] = records_block([runway_variable(document)])
    return document


def document_path_for(pad_stem) -> Path:
    """``<pad stem>_record.json`` beside the pad bake (the bake's own
    sidecar is ``<pad stem>.json``)."""
    stem = Path(pad_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_record.json")


def markings_path_for(pad_stem) -> Path:
    stem = Path(pad_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_markings.png")


def write_runway_document(document: Dict[str, Any], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path


def read_runway_document(path) -> Dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("document_version") != DOCUMENT_VERSION:
        raise ValueError(f"{path}: runway document version "
                         f"{document.get('document_version')!r} is not {DOCUMENT_VERSION}")
    return document


def runway_records(document_path) -> list:
    """The ``scene.runway`` record for a manifest, re-typed from the
    document, or [] when the scene names none (absent-canonical)."""
    if document_path is None:
        return []
    path = Path(document_path)
    if not path.is_file():
        return []
    document = read_runway_document(path)
    records = (document.get("applied_variables") or {}).get("applied_variables") or []
    return [AppliedVariable.from_dict(record) for record in records]


def manifest_scene_block(document_path) -> Optional[Dict[str, Any]]:
    """The capture manifest's ``scene.runway`` sub-block, or None."""
    if document_path is None:
        return None
    path = Path(document_path)
    if not path.is_file():
        return None
    document = read_runway_document(path)
    pad = document["pad"]
    return {"designator": document["spec"]["designator"], "pad": pad.get("stem"),
            "pad_sha256": pad.get("sha256"), "parent_sha256": pad.get("parent_sha256"),
            "document": str(path), "document_sha256": sha256_of(path),
            "markings": document["markings"].get("file"),
            "markings_sha256": document["markings"].get("sha256")}


def world_card_block(terrain_stem, terrain_sha256: Optional[str],
                     buildings_document=None, runway_document_path=None) -> Dict[str, Any]:
    """The run card's ``world`` block: the terrain the host draws, the
    buildings document and the runway document with their sha256s
    (sidecars + digests, blueprint section 4). Members are null when a
    scene states none; nothing here is derived by the host."""
    from .buildings import manifest_scene_block as buildings_block

    return {
        "terrain": None if terrain_stem is None else str(terrain_stem),
        "terrain_sha256": terrain_sha256,
        "buildings": buildings_block(buildings_document),
        "runway": manifest_scene_block(runway_document_path),
    }
