"""The vertical datum: the geoid undulation N (EGM2008, EGM96) and the
datum blocks (bake sidecar, run card, capture manifest, spec).

The measured fact this module answers (docs/PHASE3_GAP_ANALYSIS.md P10):
the GLO-30 bakes' heights are EGM2008 orthometric, JSBSim's sea level is
the WGS 84 ellipsoid (measured here: ``position/radius-to-vehicle-ft``
equals the WGS 84 ellipsoid radius plus ``h-sl`` to 0.1 ft at three
latitudes), and nothing on the branch accounted for the separation N
between the two -- +52.52 m at the Matterhorn scene, -25.94 m at
Yosemite, +41.47 m at Fuji, -29.84 m at Everest, -23.40 m at the Grand
Canyon, -30.54 m at the Flint Hills (EGM96, bilinear; EGM2008 bilinear
+54.76, -25.43, +42.41, -28.97, -23.42, -30.30 m).

What this module does
---------------------
* :func:`load_grid` reads GeographicLib's ``egm96-15.pgm`` from
  ``assets/geoid`` and REFUSES BY NAME (``terrain.geoid``) when the file
  is absent or its SHA-256 is not the committed one: a geoid grid that
  is not the one the tests measured is not a geoid grid.
* :func:`load_egm2008` reads GeographicLib's ``egm2008-5.pgm`` from the
  bake cache (``data/geoid``; NOT committed, 18.7 MB; fetched by
  :func:`fetch_egm2008` from the recorded tarball) and refuses by name
  ``geoid.grid_missing`` (absent) / ``geoid.grid_digest`` (a sha256 other
  than the recorded one, for the tarball or the grid). EGM2008 is the
  bakes' own datum model; when its grid is present a bake uses it, else
  EGM96 with the difference stated (:func:`grid_for_model`).
* :meth:`GeoidGrid.undulation` evaluates N(lat, lon) by bilinear
  interpolation on the four surrounding nodes (kept as landed: the
  verifier re-evaluates it with its own reader);
  :meth:`GeoidGrid.undulation_cubic` by GeographicLib's 12-point cubic
  least-squares fit -- the ``Geoid`` class's DEFAULT (``cubic = true``),
  transcribed from GeographicLib 2.3 ``Geoid.cpp`` fetched here (tarball
  sha256 3114847839453ee6bbe2228e41dc73cad6de6160055442b747adc9c76f0a3198)
  and re-derived in tests/test_geoid.py from the stencil weights. The
  file's own header bounds each interpolation (``MaxBilinearError``,
  ``MaxCubicError``: 0.478 / 0.294 m for egm2008-5, 1.152 / 0.169 m for
  egm96-15). EGM2008 blocks are cubic; EGM96 blocks stay bilinear.
* :func:`write_gtx` writes a NODE-ALIGNED crop of a grid around a scene
  bbox as a NOAA ``.gtx`` (floor / ceil of the bbox in whole nodes with a
  one-node margin; the alignment is recorded) so an independent
  evaluator (PROJ ``+inv +proj=vgridshift``) can re-measure N from the
  bake's own file; :func:`write_geoid_samples` records the origin and
  100 interior points evaluated from the FULL grid beside it.
* :func:`datum_block` assembles the block the bake sidecar, the run card
  and the capture manifest carry (every in-tree key kept): which datum
  the heights are in, which geoid model and interpolation, N at the
  scene origin (and its bilinear companion) with the grid's sha256, the
  interpolation and model-difference bounds, N's range over the scene
  bbox, the ``.gtx`` crop, the declared model uncertainty, the tide
  system, the physics frame, and the ellipsoidal height of the origin.
* :func:`dted_block` and :func:`cdb_descriptor_block` are the terrain
  sidecar's DTED (MIL-PRF-89020B DSI/ACC-style fields) and CDB
  descriptor documentation; :func:`datum_spec_problems` the spec
  ``datum`` block's refusals; :func:`undulation_variable` the
  ``AppliedVariable`` record for ``scene.geoid_undulation_m``.

Refusals by name: ``terrain.geoid`` (in tree), ``geoid.grid_missing``,
``geoid.grid_digest``, ``datum.outside_grid`` (a crop that would leave
the grid, or a point outside a crop), ``datum.sidecar_without_datum``,
``datum.model_mismatch``, ``datum.physics_frame_unsupported``,
``dted.metadata_incomplete`` (:class:`DatumError`, ``.constraint``).

What is NOT claimed
-------------------
* The heights are not converted. JSBSim's ``h-sl`` stays ellipsoidal by
  definition and the orthometric heights fed to it are unchanged, so a
  JSBSim altitude on this branch equals an orthometric height; the block
  records N so a consumer can form the ellipsoidal height (the runner's
  ``hae_m`` channel does so at export: ``altitude_m + undulation_m``),
  and nothing inside the simulation is moved. Relative geometry within a
  scene never depended on N and still does not.
* EGM96 is not EGM2008. The bakes' datum is EGM2008; the committed grid
  is EGM96 (2 MB, versus 19 MB for the coarsest EGM2008 grid). The
  difference was MEASURED here from GeographicLib's ``egm2008-5.pgm``
  at every EGM96 grid node: 11.985 m at most (28.5 N, 94.5 E), 0.72 m
  RMS, and at the six curated origins the values in
  :data:`EGM2008_MINUS_EGM96_AT_ORIGIN_M`. The stated bound
  :data:`MODEL_DIFFERENCE_BOUND_M` adds both grids' bilinear error
  bounds to the node maximum; between nodes nothing finer was measured.
  A bake made with the EGM2008 grid carries no model difference.
* An interpolation bound is the header's, not the model's error against
  the true geoid; the model uncertainty is DECLARED (``u_model_m`` 0.10 m
  for EGM2008: Pavlis et al. 2012's 5-10 cm against GPS/levelling,
  unverified here; for EGM96 the model-difference bound is the binding
  term). The tide system of the grids is not verified here. N is taken at
  the scene ORIGIN for the whole flight; its range over the scene bbox is
  recorded so the error of that choice is bounded, not hidden.
* The DTED and CDB blocks are documentation in the sidecar: no DTED cell
  and no CDB tile is written; MIL-PRF-89020B and OGC CDB could not be
  fetched here, so every field named from them is marked unverified.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import struct
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from core.records import AppliedVariable, Model, NullTest, Readback

REPO = Path(__file__).resolve().parents[2]

#: The committed grid and the digests the loader checks it against.
GRID_PATH = REPO / "assets" / "geoid" / "egm96-15.pgm"
GRID_SHA256 = "2a12f13b6df65cdea52432c7fa1b43f34b007148eb817bf032af5af710905caa"
TARBALL_SHA256 = "8b1ebad1ebae0a045502d0edb9cc51553da1d3914f01e07470c11b3bed75048e"
TARBALL_URL = ("https://sourceforge.net/projects/geographiclib/files/"
               "geoids-distrib/egm96-15.tar.bz2/download")

MODEL_NAME = "EGM96 15-minute grid (GeographicLib egm96-15)"
INTERPOLATION = "bilinear"
CUBIC = "cubic"
INTERPOLATIONS = (CUBIC, INTERPOLATION)

#: The EGM2008 grid: fetched into the bake cache (not committed) from the
#: recorded tarball; both digests measured here 2026-09-28.
GEOID_CACHE_DIR = REPO / "data" / "geoid"
EGM2008_GRID_PATH = GEOID_CACHE_DIR / "egm2008-5.pgm"
EGM2008_TARBALL_PATH = GEOID_CACHE_DIR / "egm2008-5.tar.bz2"
EGM2008_GRID_SHA256 = "96d55e88db186ddae892b00c5f8cc42a37cdac8ddb69b6de00af8c75dffb34a3"
EGM2008_TARBALL_SHA256 = "9a57c14330ac609132d324906822a9da9de265ad9b9087779793eb7080852970"
EGM2008_TARBALL_URL = ("https://sourceforge.net/projects/geographiclib/files/"
                       "geoids-distrib/egm2008-5.tar.bz2/download")
EGM2008_TARBALL_MEMBER = "geoids/egm2008-5.pgm"
EGM2008_MODEL_NAME = "EGM2008 5-minute grid (GeographicLib egm2008-5)"

#: The two models by key, and what each block carries for them.
MODEL_EGM96 = "EGM96"
MODEL_EGM2008 = "EGM2008"
MODEL_KEYS = (MODEL_EGM2008, MODEL_EGM96)
MODEL_NAMES = {MODEL_EGM96: MODEL_NAME, MODEL_EGM2008: EGM2008_MODEL_NAME}
#: EGM2008 blocks use GeographicLib's default (cubic); EGM96 blocks stay
#: bilinear as landed (the in-tree verifier clause re-evaluates them).
MODEL_INTERPOLATION = {MODEL_EGM96: INTERPOLATION, MODEL_EGM2008: CUBIC}
#: The declared model uncertainty (u_model_m, metres, one sigma as
#: declared): EGM2008 against GPS/levelling 5-10 cm (Pavlis et al. 2012,
#: unverified here) -> 0.10 m stated; EGM96 is not the bakes' model, so
#: its binding term is the model-difference bound.
U_MODEL_M = {MODEL_EGM2008: 0.10, MODEL_EGM96: 13.7}
U_MODEL_BASIS = {
    MODEL_EGM2008: ("declared: EGM2008 against GPS/levelling 5-10 cm (Pavlis et al. "
                    "2012, unverified here); 0.10 m stated as one sigma"),
    MODEL_EGM96: ("declared: EGM96 is not the bakes' datum model; the binding term is "
                  "the EGM2008-EGM96 difference bound (13.7 m stated), not the "
                  "model's own accuracy"),
}
TIDE_SYSTEM = "not verified here"
#: Where the EGM2008 grid was obtained from and how (the fetch step).
GRID_SOURCE_URLS = {MODEL_EGM96: TARBALL_URL, MODEL_EGM2008: EGM2008_TARBALL_URL}
GRID_TARBALL_SHA256 = {MODEL_EGM96: TARBALL_SHA256, MODEL_EGM2008: EGM2008_TARBALL_SHA256}

#: The physics frame (blueprint section 5, C2): the internal frame stays
#: and is named; N is applied where a coordinate leaves the system.
PHYSICS_FRAME_ORTHOMETRIC = "orthometric"
PHYSICS_FRAME_ELLIPSOID = "ellipsoid"
PHYSICS_FRAMES = (PHYSICS_FRAME_ORTHOMETRIC, PHYSICS_FRAME_ELLIPSOID)
VERTICAL_ORTHOMETRIC = "orthometric"
VERTICAL_ELLIPSOIDAL = "ellipsoidal"
VERTICAL_DATUMS = (VERTICAL_ORTHOMETRIC, VERTICAL_ELLIPSOIDAL)
PHYSICS_FRAME_NOTE = (
    "orthometric heights are passed to JSBSim h-sl (its ellipsoidal slot) "
    "unchanged, so JSBSim altitude equals orthometric height and JSBSim's "
    "own ECEF is radially low by the undulation; the geoid is applied where "
    "a coordinate leaves the system (hae_m = altitude_m + undulation_m at "
    "export); the ellipsoid frame (flying at HAE with the atmosphere kept "
    "on the geoid) is refused by name until the physics frame handles it")

#: The gtx crop: one node of margin beyond the floor/ceil of the bbox.
GTX_MARGIN_NODES = 1
GTX_SAMPLE_COUNT = 100
GTX_SAMPLE_SEED = 20260928
GTX_FORMAT = ("NOAA .gtx: big-endian header of four float64 (south latitude, "
              "west longitude, latitude step, longitude step) and two int32 "
              "(rows, columns), then float32 undulations row-major from the "
              "SOUTH row northward, west to east")
GTX_SIGN_NOTE = ("the grid holds +N (ellipsoidal = orthometric + N); PROJ's "
                 "forward vgridshift SUBTRACTS the grid from a height, so an "
                 "evaluator uses '+inv +proj=vgridshift' to read +N")

#: The datum the GLO-30 bakes' heights are in (glo30.py provenance).
BAKE_DATUM = "EGM2008 orthometric (GLO-30)"
#: The datum of a scene with no georeferenced heights.
FLAT_DATUM = "flat slab, spec terrain_elevation"
SYNTHESISED_DATUM = ("synthesised heightfield, spec terrain_elevation "
                     "(not a real place)")

DATUM_NOTE = ("JSBSim h-sl is ellipsoidal; heights fed to the FDM are "
              "orthometric, so JSBSim altitude equals orthometric height "
              "here; ellipsoidal = altitude + undulation_m")
FLAT_NOTE = ("no georeferenced heights: the ground is the spec's "
             "terrain_elevation, fed to JSBSim as an ellipsoidal height; "
             "no geoid undulation applies and none was evaluated")

#: EGM2008 minus EGM96 (metres) at the curated scene origins, MEASURED
#: 2026-09-28 from GeographicLib egm2008-5.pgm (tarball sha256
#: 9a57c14330ac609132d324906822a9da9de265ad9b9087779793eb7080852970, grid
#: sha256 96d55e88db186ddae892b00c5f8cc42a37cdac8ddb69b6de00af8c75dffb34a3)
#: against the committed EGM96 grid, both bilinear. Not committed: 18.7 MB.
EGM2008_MINUS_EGM96_AT_ORIGIN_M: Dict[str, float] = {
    "matterhorn": 2.231,
    "yosemite": 0.507,
    "fuji": 0.943,
    "everest": 0.870,
    "grand_canyon": -0.016,
    "flint_hills": 0.232,
}
#: |EGM2008 - EGM96| at every one of the 1,038,240 EGM96 grid nodes,
#: measured as above: 11.985 m at most (28.5 N, 94.5 E), 0.722 m RMS.
MODEL_DIFFERENCE_MAX_AT_NODES_M = 11.985
#: The bound the datum block states: the node maximum plus both grids'
#: header bilinear error bounds (1.152 m EGM96-15, 0.478 m EGM2008-5),
#: since between nodes nothing finer was measured.
MODEL_DIFFERENCE_BOUND_M = 13.7
MODEL_DIFFERENCE_BASIS = (
    "measured 2026-09-28: max |EGM2008-5 - EGM96-15| over all 1,038,240 "
    "EGM96 grid nodes is 11.985 m (28.5 N, 94.5 E), RMS 0.722 m; the "
    "bound adds both grids' bilinear error bounds (1.152 + 0.478 m). "
    "Pavlis et al. 2012 (J. Geophys. Res. 117, B04406) is the EGM2008 "
    "reference, unverified here")

REFERENCES = (
    "Lemoine et al. 1998, NASA/TP-1998-206861, EGM96 (unverified here)",
    "Pavlis, Holmes, Kenyon, Factor 2012, J. Geophys. Res. 117, B04406, "
    "EGM2008 (unverified here)",
    "GeographicLib geoid datasets, egm96-15.tar.bz2, header "
    "MaxBilinearError 1.152 (the committed file's own header)",
    "GeographicLib geoid datasets, egm2008-5.tar.bz2, header MaxBilinearError "
    "0.478 / MaxCubicError 0.294 (the cached file's own header; not committed)",
    "GeographicLib 2.3 Geoid.cpp (Karney, MIT/X11): the 12-point cubic transfer "
    "matrices, fetched here and re-derived in the tests",
)


class GeoidError(Exception):
    """The geoid grid cannot be used; refused by name (``terrain.geoid``)."""

    constraint = "terrain.geoid"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"terrain.geoid: {message}")


class DatumError(Exception):
    """A datum refusal by name (``.constraint``): ``geoid.grid_missing``,
    ``geoid.grid_digest``, ``datum.outside_grid``,
    ``datum.sidecar_without_datum``, ``datum.model_mismatch``,
    ``datum.physics_frame_unsupported``, ``dted.metadata_incomplete``."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


_HEADER = re.compile(
    rb"P5\s*(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s*(?:#[^\n]*\n\s*)*(\d+)\s")

# -- GeographicLib's cubic interpolation ----------------------------------------
#
# The transfer matrices of GeographicLib 2.3 Geoid.cpp (Charles Karney,
# MIT/X11; fetched here from sourceforge, tarball sha256
# 3114847839453ee6bbe2228e41dc73cad6de6160055442b747adc9c76f0a3198): a
# weighted least-squares cubic (ten terms 1, x, y, x^2, xy, y^2, x^3,
# x^2 y, x y^2, y^3) over the 12-point stencil below, weight 2 on the
# four inner nodes and 1 on the eight outer ones (Lesh 1959). C3 is the
# interior matrix; C3N drops the x, x^2, x^3 terms so the fit is
# independent of longitude at the north pole row (iy == 0), C3S is C3N
# under y -> 1 - y for the south pole row (iy == height - 2). Each
# matrix is stored [stencil point][term] over a common denominator.
# tests/test_geoid.py re-derives all three from the stencil and weights.
CUBIC_STENCIL: Tuple[Tuple[int, int], ...] = (
    (0, -1), (1, -1),
    (-1, 0), (0, 0), (1, 0), (2, 0),
    (-1, 1), (0, 1), (1, 1), (2, 1),
    (0, 2), (1, 2),
)
CUBIC_WEIGHTS: Tuple[int, ...] = (1, 1, 1, 2, 2, 1, 1, 2, 2, 1, 1, 1)
CUBIC_TERMS: Tuple[Tuple[int, int], ...] = (
    (0, 0), (1, 0), (0, 1), (2, 0), (1, 1), (0, 2), (3, 0), (2, 1), (1, 2), (0, 3))
CUBIC_C0 = 240
CUBIC_C3: Tuple[int, ...] = (
    9, -18, -88, 0, 96, 90, 0, 0, -60, -20,
    -9, 18, 8, 0, -96, 30, 0, 0, 60, -20,
    9, -88, -18, 90, 96, 0, -20, -60, 0, 0,
    186, -42, -42, -150, -96, -150, 60, 60, 60, 60,
    54, 162, -78, 30, -24, -90, -60, 60, -60, 60,
    -9, -32, 18, 30, 24, 0, 20, -60, 0, 0,
    -9, 8, 18, 30, -96, 0, -20, 60, 0, 0,
    54, -78, 162, -90, -24, 30, 60, -60, 60, -60,
    -54, 78, 78, 90, 144, 90, -60, -60, -60, -60,
    9, -8, -18, -30, -24, 0, 20, 60, 0, 0,
    -9, 18, -32, 0, 24, 30, 0, 0, -60, 20,
    9, -18, -8, 0, -24, -30, 0, 0, 60, 20,
)
CUBIC_C0N = 372
CUBIC_C3N: Tuple[int, ...] = (
    0, 0, -131, 0, 138, 144, 0, 0, -102, -31,
    0, 0, 7, 0, -138, 42, 0, 0, 102, -31,
    62, 0, -31, 0, 0, -62, 0, 0, 0, 31,
    124, 0, -62, 0, 0, -124, 0, 0, 0, 62,
    124, 0, -62, 0, 0, -124, 0, 0, 0, 62,
    62, 0, -31, 0, 0, -62, 0, 0, 0, 31,
    0, 0, 45, 0, -183, -9, 0, 93, 18, 0,
    0, 0, 216, 0, 33, 87, 0, -93, 12, -93,
    0, 0, 156, 0, 153, 99, 0, -93, -12, -93,
    0, 0, -45, 0, -3, 9, 0, 93, -18, 0,
    0, 0, -55, 0, 48, 42, 0, 0, -84, 31,
    0, 0, -7, 0, -48, -42, 0, 0, 84, 31,
)
CUBIC_C0S = 372
CUBIC_C3S: Tuple[int, ...] = (
    18, -36, -122, 0, 120, 135, 0, 0, -84, -31,
    -18, 36, -2, 0, -120, 51, 0, 0, 84, -31,
    36, -165, -27, 93, 147, -9, 0, -93, 18, 0,
    210, 45, -111, -93, -57, -192, 0, 93, 12, 93,
    162, 141, -75, -93, -129, -180, 0, 93, -12, 93,
    -36, -21, 27, 93, 39, 9, 0, -93, -18, 0,
    0, 0, 62, 0, 0, 31, 0, 0, 0, -31,
    0, 0, 124, 0, 0, 62, 0, 0, 0, -62,
    0, 0, 124, 0, 0, 62, 0, 0, 0, -62,
    0, 0, 62, 0, 0, 31, 0, 0, 0, -31,
    -18, 36, -64, 0, 66, 51, 0, 0, -102, 31,
    18, -36, 2, 0, -66, -51, 0, 0, 102, 31,
)
_C3 = np.asarray(CUBIC_C3, dtype=np.float64).reshape(12, 10) / CUBIC_C0
_C3N = np.asarray(CUBIC_C3N, dtype=np.float64).reshape(12, 10) / CUBIC_C0N
_C3S = np.asarray(CUBIC_C3S, dtype=np.float64).reshape(12, 10) / CUBIC_C0S


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class GeoidGrid:
    """A GeographicLib PGM geoid grid: origin 90N 0E, rows southward,
    columns eastward over 0..360 deg (no wrap column), N = offset +
    scale * value."""

    values: np.ndarray            # (height, width) uint16, host order
    offset_m: float
    scale_m: float
    max_bilinear_error_m: float
    rms_bilinear_error_m: float
    description: str
    sha256: str
    path: str
    #: Record 2 additions (defaulted so every in-tree construction still
    #: works): the header's cubic bounds and the model the description
    #: names (``EGM2008`` | ``EGM96``).
    max_cubic_error_m: float = float("nan")
    rms_cubic_error_m: float = float("nan")
    model_key: str = MODEL_EGM96

    @property
    def width(self) -> int:
        return int(self.values.shape[1])

    @property
    def height(self) -> int:
        return int(self.values.shape[0])

    @property
    def posting_deg(self) -> float:
        """The node spacing (the same in both axes for GeographicLib's
        grids: 360 / width east-west, 180 / (height - 1) north-south)."""
        return 360.0 / self.width

    @property
    def model_name(self) -> str:
        return MODEL_NAMES[self.model_key]

    def undulation(self, lat_deg: float, lon_deg: float) -> float:
        """N at one point, bilinear on the four surrounding nodes."""
        lat = float(lat_deg)
        lon = float(lon_deg)
        if not (-90.0 <= lat <= 90.0) or not np.isfinite(lon):
            raise GeoidError(f"({lat}, {lon}) is not a usable coordinate pair")
        fy = (90.0 - lat) * (self.height - 1) / 180.0
        fx = (lon % 360.0) * self.width / 360.0
        iy = min(int(np.floor(fy)), self.height - 2)
        ix = int(np.floor(fx)) % self.width
        dy = fy - iy
        dx = fx - ix
        ix1 = (ix + 1) % self.width
        v = self.values
        value = (float(v[iy, ix]) * (1.0 - dx) * (1.0 - dy)
                 + float(v[iy, ix1]) * dx * (1.0 - dy)
                 + float(v[iy + 1, ix]) * (1.0 - dx) * dy
                 + float(v[iy + 1, ix1]) * dx * dy)
        return self.offset_m + self.scale_m * value

    def _raw(self, ix: int, iy: int) -> float:
        """A node value with GeographicLib's wrapping: columns wrap
        around the globe; a row beyond a pole reflects through it with
        the longitude turned by 180 degrees (``Geoid::rawval``)."""
        width, height = self.width, self.height
        ix = ix % width
        if iy < 0 or iy >= height:
            iy = -iy if iy < 0 else 2 * (height - 1) - iy
            ix = (ix + (width // 2 if ix < width // 2 else -(width // 2))) % width
        return float(self.values[iy, ix])

    def undulation_cubic(self, lat_deg: float, lon_deg: float) -> float:
        """N at one point by GeographicLib's default: the 12-point cubic
        least-squares fit of ``Geoid::height`` (``cubic = true``), with
        the polar-row matrices at the first and last row pairs. The
        header's ``MaxCubicError`` bounds it (0.294 m for egm2008-5)."""
        lat = float(lat_deg)
        lon = float(lon_deg)
        if not (-90.0 <= lat <= 90.0) or not np.isfinite(lon):
            raise GeoidError(f"({lat}, {lon}) is not a usable coordinate pair")
        fy = (90.0 - lat) * (self.height - 1) / 180.0
        fx = (lon % 360.0) * self.width / 360.0
        iy = min(int(np.floor(fy)), self.height - 2)
        ix = int(np.floor(fx)) % self.width
        ty = fy - iy
        tx = fx - ix
        stencil = np.array([self._raw(ix + dx, iy + dy) for dx, dy in CUBIC_STENCIL])
        matrix = _C3N if iy == 0 else (_C3S if iy == self.height - 2 else _C3)
        t = stencil @ matrix
        value = (t[0] + tx * (t[1] + tx * (t[3] + tx * t[6]))
                 + ty * (t[2] + tx * (t[4] + tx * t[7])
                         + ty * (t[5] + tx * t[8] + ty * t[9])))
        return self.offset_m + self.scale_m * float(value)

    def undulation_at(self, lat_deg: float, lon_deg: float,
                      interpolation: Optional[str] = None) -> float:
        """N by the named interpolation (the model's own when None)."""
        method = interpolation or MODEL_INTERPOLATION[self.model_key]
        if method == CUBIC:
            return self.undulation_cubic(lat_deg, lon_deg)
        if method == INTERPOLATION:
            return self.undulation(lat_deg, lon_deg)
        raise ValueError(f"interpolation {method!r} is not one of {INTERPOLATIONS}")

    def interpolation_bound_m(self, interpolation: Optional[str] = None) -> float:
        """The header's own bound for the named interpolation."""
        method = interpolation or MODEL_INTERPOLATION[self.model_key]
        return float(self.max_cubic_error_m if method == CUBIC else self.max_bilinear_error_m)

    def source(self, interpolation: Optional[str] = None) -> Dict[str, Any]:
        """Provenance of every N this grid returns."""
        return {
            # POSIX form on every platform: the record is compared across
            # machines, and a Windows producer must write what a Linux one does.
            "file": (Path(self.path).relative_to(REPO).as_posix()
                     if str(self.path).startswith(str(REPO)) else str(self.path)),
            "sha256": self.sha256,
            "tarball_sha256": GRID_TARBALL_SHA256[self.model_key],
            "tarball_url": GRID_SOURCE_URLS[self.model_key],
            "description": self.description,
            "interpolation": interpolation or MODEL_INTERPOLATION[self.model_key],
            "grid": [self.width, self.height],
            "model": self.model_key,
            "posting_deg": self.posting_deg,
            "max_bilinear_error_m": float(self.max_bilinear_error_m),
            "max_cubic_error_m": float(self.max_cubic_error_m),
        }


def parse_pgm(data: bytes, sha256: str, path: str) -> GeoidGrid:
    """The grid out of the PGM bytes; refuses by name a file that is not
    a GeographicLib geoid PGM (no Offset/Scale, wrong sample count)."""
    match = _HEADER.match(data)
    if match is None:
        raise GeoidError(f"{path}: not a binary PGM (P5) file")
    header = data[:match.end()].decode("ascii", errors="replace")
    width, height, maxval = (int(g) for g in match.groups())
    if maxval != 65535:
        raise GeoidError(f"{path}: maxval {maxval} is not the 16-bit grid's")
    offset = re.search(r"# Offset (\S+)", header)
    scale = re.search(r"# Scale (\S+)", header)
    origin = re.search(r"# Origin (\S+) (\S+)", header)
    if offset is None or scale is None:
        raise GeoidError(f"{path}: header carries no Offset/Scale")
    if origin is None or origin.groups() != ("90N", "0E"):
        raise GeoidError(f"{path}: origin is not 90N 0E as the reader assumes")
    expected = width * height * 2
    if len(data) - match.end() != expected:
        raise GeoidError(f"{path}: {len(data) - match.end()} sample bytes "
                         f"where {width}x{height} needs {expected}")
    values = np.frombuffer(data, dtype=">u2", offset=match.end(),
                           count=width * height).reshape(height, width)
    values = values.astype(np.uint16)
    max_err = re.search(r"# MaxBilinearError (\S+)", header)
    rms_err = re.search(r"# RMSBilinearError (\S+)", header)
    max_cubic = re.search(r"# MaxCubicError (\S+)", header)
    rms_cubic = re.search(r"# RMSCubicError (\S+)", header)
    desc = re.search(r"# Description ([^\n]*)", header)
    description = desc.group(1).strip() if desc else ""
    # The header values are DATA: the model is what the description names.
    model_key = MODEL_EGM2008 if "EGM2008" in description else MODEL_EGM96
    return GeoidGrid(
        values=values,
        offset_m=float(offset.group(1)), scale_m=float(scale.group(1)),
        max_bilinear_error_m=float(max_err.group(1)) if max_err else float("nan"),
        rms_bilinear_error_m=float(rms_err.group(1)) if rms_err else float("nan"),
        description=description,
        sha256=sha256, path=str(path),
        max_cubic_error_m=float(max_cubic.group(1)) if max_cubic else float("nan"),
        rms_cubic_error_m=float(rms_cubic.group(1)) if rms_cubic else float("nan"),
        model_key=model_key)


def load_grid(path=GRID_PATH, expected_sha256: Optional[str] = GRID_SHA256) -> GeoidGrid:
    """Read and check the grid. ``expected_sha256`` None skips the digest
    check (for a grid a test writes itself); the committed grid is always
    checked, and a mismatch or an absent file refuses by name."""
    path = Path(path)
    if not path.is_file():
        raise GeoidError(
            f"the geoid grid {path} is absent; see assets/geoid/README.md "
            f"for its source ({TARBALL_URL})")
    digest = sha256_of(path)
    if expected_sha256 is not None and digest != expected_sha256:
        raise GeoidError(
            f"the geoid grid {path} has sha256 {digest[:16]}..., not the "
            f"committed {expected_sha256[:16]}...; a grid that is not the "
            f"one measured is refused, not interpolated")
    return parse_pgm(path.read_bytes(), digest, str(path))


def load_egm2008(path=EGM2008_GRID_PATH,
                 expected_sha256: Optional[str] = EGM2008_GRID_SHA256) -> GeoidGrid:
    """The EGM2008 5-minute grid from the bake cache, checked. Refuses by
    name: ``geoid.grid_missing`` when the file is absent (it is not
    committed; :func:`fetch_egm2008` fetches it), ``geoid.grid_digest``
    when its sha256 is not the recorded one or its header does not name
    EGM2008. ``expected_sha256`` None skips the digest check (a grid a
    test writes itself); the cached grid is always checked."""
    path = Path(path)
    if not path.is_file():
        raise DatumError(
            "geoid.grid_missing",
            f"the EGM2008 geoid grid {path} is absent from the bake cache; fetch it "
            f"with core.terrain.geoid.fetch_egm2008 (tarball {EGM2008_TARBALL_URL}, "
            f"sha256 {EGM2008_TARBALL_SHA256[:16]}...) or bake with EGM96")
    digest = sha256_of(path)
    if expected_sha256 is not None and expected_sha256 != digest:
        raise DatumError(
            "geoid.grid_digest",
            f"the EGM2008 geoid grid {path} has sha256 {digest[:16]}..., not the "
            f"recorded {expected_sha256[:16]}...; a grid that is not the one "
            f"measured is refused, not interpolated")
    grid = parse_pgm(path.read_bytes(), digest, str(path))
    if grid.model_key != MODEL_EGM2008:
        raise DatumError("geoid.grid_digest",
                         f"{path} describes itself as {grid.description!r}, not an "
                         f"EGM2008 grid")
    return grid


def fetch_egm2008(cache_dir=GEOID_CACHE_DIR, url: str = EGM2008_TARBALL_URL,
                  timeout_s: float = 600.0) -> Path:
    """Fetch GeographicLib's egm2008-5 tarball into the bake cache, check
    its sha256 against the recorded one (``geoid.grid_digest`` otherwise),
    extract the grid and check ITS sha256 (:func:`load_egm2008`). A grid
    already in the cache with the recorded digest is not fetched again.
    Returns the grid path. Network: sourceforge.net (through the proxy)."""
    import urllib.request

    cache_dir = Path(cache_dir)
    grid_path = cache_dir / EGM2008_GRID_PATH.name
    if grid_path.is_file() and sha256_of(grid_path) == EGM2008_GRID_SHA256:
        return grid_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    tarball = cache_dir / EGM2008_TARBALL_PATH.name
    if not (tarball.is_file() and sha256_of(tarball) == EGM2008_TARBALL_SHA256):
        with urllib.request.urlopen(url, timeout=timeout_s) as response, \
                tarball.open("wb") as out:
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    digest = sha256_of(tarball)
    if digest != EGM2008_TARBALL_SHA256:
        raise DatumError(
            "geoid.grid_digest",
            f"the fetched tarball {tarball} has sha256 {digest[:16]}..., not the "
            f"recorded {EGM2008_TARBALL_SHA256[:16]}...; refusing to extract a grid "
            f"from a tarball that is not the one measured")
    with tarfile.open(tarball, "r:bz2") as archive:
        member = archive.getmember(EGM2008_TARBALL_MEMBER)
        with archive.extractfile(member) as src, grid_path.open("wb") as dst:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                dst.write(chunk)
    load_egm2008(grid_path)
    return grid_path


@functools.lru_cache(maxsize=1)
def default_grid() -> GeoidGrid:
    """The committed grid, read and checked once per process."""
    return load_grid()


@functools.lru_cache(maxsize=1)
def egm2008_grid() -> GeoidGrid:
    """The cached EGM2008 grid, read and checked once per process
    (``geoid.grid_missing`` / ``geoid.grid_digest`` by name)."""
    return load_egm2008()


def egm2008_available(path=EGM2008_GRID_PATH) -> bool:
    """Whether the EGM2008 grid is in the bake cache (its digest is
    checked on load, not here)."""
    return Path(path).is_file()


def grid_for_model(model: str = "auto") -> GeoidGrid:
    """The grid a bake evaluates with: ``EGM2008`` (refuses by name when
    the cache lacks it), ``EGM96`` (the committed grid), or ``auto`` --
    EGM2008 when its grid is in the cache, else EGM96 with the model
    difference stated in the block."""
    if model == MODEL_EGM2008:
        return egm2008_grid()
    if model == MODEL_EGM96:
        return default_grid()
    if model == "auto":
        return egm2008_grid() if egm2008_available() else default_grid()
    raise ValueError(f"geoid model {model!r} is not one of {MODEL_KEYS + ('auto',)}")


def undulation(lat_deg: float, lon_deg: float,
               grid: Optional[GeoidGrid] = None) -> float:
    """EGM96 geoid undulation N (m) at a point: ellipsoidal = orthometric + N."""
    return (grid or default_grid()).undulation(lat_deg, lon_deg)


# -- the .gtx crop -------------------------------------------------------------

def gtx_crop_nodes(grid: GeoidGrid, bbox: Sequence[float],
                   margin_nodes: int = GTX_MARGIN_NODES) -> Dict[str, Any]:
    """The node-aligned crop around a scene bbox ``(lat_min, lat_max,
    lon_min, lon_max)``: floor / ceil of each edge in whole nodes of the
    grid's posting, then ``margin_nodes`` more on every side. Refuses
    ``datum.outside_grid`` when the crop would reach beyond a pole (a
    crop that is not a crop of the grid cannot be node-aligned)."""
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in bbox)
    if not (lat_min < lat_max and lon_min < lon_max):
        raise ValueError(f"bbox {tuple(bbox)} is not (lat_min, lat_max, lon_min, lon_max)")
    step = grid.posting_deg
    south = int(np.floor(lat_min / step + 1e-9)) - margin_nodes
    north = int(np.ceil(lat_max / step - 1e-9)) + margin_nodes
    west = int(np.floor(lon_min / step + 1e-9)) - margin_nodes
    east = int(np.ceil(lon_max / step - 1e-9)) + margin_nodes
    if south * step < -90.0 or north * step > 90.0:
        raise DatumError(
            "datum.outside_grid",
            f"a node-aligned crop of the bbox {tuple(bbox)} with a {margin_nodes}-node "
            f"margin would reach latitude {south * step:.4f}..{north * step:.4f}, "
            f"beyond the grid's poles; the scene cannot be cropped from this grid")
    return {"south_node": south, "north_node": north, "west_node": west, "east_node": east,
            "posting_deg": step, "margin_nodes": int(margin_nodes),
            "rows": north - south + 1, "cols": east - west + 1,
            "lat_south": south * step, "lat_north": north * step,
            "lon_west": west * step, "lon_east": east * step}


def write_gtx(grid: GeoidGrid, bbox: Sequence[float], path,
              margin_nodes: int = GTX_MARGIN_NODES) -> Dict[str, Any]:
    """Write the node-aligned crop of ``grid`` around ``bbox`` as a NOAA
    ``.gtx`` (:data:`GTX_FORMAT`; +N, :data:`GTX_SIGN_NOTE`) and return
    its record: the file's name and sha256, the alignment in whole nodes
    (so a reader can see the corner IS a node: ``lat_south / posting_deg``
    integral), the bounds, and the raw node values' min and max. The
    values are the grid's nodes verbatim (offset + scale * sample), NOT
    interpolated: the crop carries the data, and the evaluator brings
    the interpolation."""
    crop = gtx_crop_nodes(grid, bbox, margin_nodes)
    step = crop["posting_deg"]
    rows, cols = crop["rows"], crop["cols"]
    values = np.empty((rows, cols), dtype=">f4")
    for r in range(rows):
        # Row r is the SOUTH-most first (GTX order); the grid's row index
        # counts from 90N.
        lat = (crop["south_node"] + r) * step
        iy = int(round((90.0 - lat) / step))
        for c in range(cols):
            ix = (crop["west_node"] + c) % grid.width
            values[r, c] = grid.offset_m + grid.scale_m * float(grid.values[iy, ix])
    header = struct.pack(">ddddii", crop["lat_south"], crop["lon_west"], step, step, rows, cols)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + values.tobytes())
    return {
        "file": path.name,
        "sha256": sha256_of(path),
        "bytes": int(path.stat().st_size),
        "format": GTX_FORMAT,
        "sign": GTX_SIGN_NOTE,
        "grid_sha256": grid.sha256,
        "model": grid.model_key,
        "posting_deg": step,
        "rows": rows, "cols": cols,
        "lat_south": crop["lat_south"], "lat_north": crop["lat_north"],
        "lon_west": crop["lon_west"], "lon_east": crop["lon_east"],
        "alignment": {"south_node": crop["south_node"], "west_node": crop["west_node"],
                      "north_node": crop["north_node"], "east_node": crop["east_node"],
                      "node_aligned": True,
                      "rule": ("floor / ceil of the scene bbox in whole nodes of "
                               "posting_deg, plus margin_nodes on every side")},
        "margin_nodes": int(margin_nodes),
        "scene_bbox_deg": [float(v) for v in bbox],
        "node_value_min_m": float(values.min()), "node_value_max_m": float(values.max()),
        "evaluator": "+inv +proj=vgridshift +grids=<file> (PROJ; bilinear on the nodes)",
    }


@dataclass(frozen=True)
class GtxCrop:
    """A ``.gtx`` crop read back: nodes from the south row northward."""

    values: np.ndarray      # (rows, cols) float64, row 0 = lat_south
    lat_south: float
    lon_west: float
    dlat: float
    dlon: float
    sha256: str
    path: str

    @property
    def rows(self) -> int:
        return int(self.values.shape[0])

    @property
    def cols(self) -> int:
        return int(self.values.shape[1])

    @property
    def lat_north(self) -> float:
        return self.lat_south + (self.rows - 1) * self.dlat

    @property
    def lon_east(self) -> float:
        return self.lon_west + (self.cols - 1) * self.dlon

    def undulation(self, lat_deg: float, lon_deg: float) -> float:
        """N bilinear on the crop's nodes; refuses ``datum.outside_grid``
        beyond the node extent (where PROJ answers inf)."""
        lat, lon = float(lat_deg), float(lon_deg)
        fy = (lat - self.lat_south) / self.dlat
        fx = (lon - self.lon_west) / self.dlon
        if not (0.0 <= fy <= self.rows - 1 and 0.0 <= fx <= self.cols - 1):
            raise DatumError(
                "datum.outside_grid",
                f"({lat}, {lon}) lies outside the geoid crop {self.path} "
                f"({self.lat_south}..{self.lat_north} N, {self.lon_west}..{self.lon_east} E); "
                f"no undulation is interpolated beyond the nodes")
        iy = min(int(np.floor(fy)), self.rows - 2)
        ix = min(int(np.floor(fx)), self.cols - 2)
        wy, wx = fy - iy, fx - ix
        v = self.values
        return float(v[iy, ix] * (1 - wx) * (1 - wy) + v[iy, ix + 1] * wx * (1 - wy)
                     + v[iy + 1, ix] * (1 - wx) * wy + v[iy + 1, ix + 1] * wx * wy)


def read_gtx(path) -> GtxCrop:
    """Read a ``.gtx`` written by :func:`write_gtx` (or any NOAA gtx)."""
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 40:
        raise DatumError("datum.outside_grid", f"{path} is too short to be a .gtx file")
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">ddddii", data[:40])
    if len(data) != 40 + 4 * rows * cols:
        raise DatumError("datum.outside_grid",
                         f"{path}: {len(data) - 40} value bytes where {rows}x{cols} needs "
                         f"{4 * rows * cols}")
    values = np.frombuffer(data, dtype=">f4", offset=40, count=rows * cols)
    return GtxCrop(values=values.reshape(rows, cols).astype(np.float64),
                   lat_south=lat0, lon_west=lon0, dlat=dlat, dlon=dlon,
                   sha256=hashlib.sha256(data).hexdigest(), path=str(path))


def interior_samples(grid: GeoidGrid, gtx_record: Dict[str, Any],
                     count: int = GTX_SAMPLE_COUNT, seed: int = GTX_SAMPLE_SEED) -> Dict[str, Any]:
    """``count`` points strictly inside the crop's node extent (a
    quarter node in from every edge), evaluated from the FULL grid both
    ways, so an independent evaluator of the crop can be compared
    against the grid the crop was cut from (a crop cut from the wrong
    nodes disagrees; measured 0.058 m for a one-node misalignment)."""
    rng = np.random.default_rng(seed)
    step = gtx_record["posting_deg"]
    lat_lo, lat_hi = gtx_record["lat_south"] + 0.25 * step, gtx_record["lat_north"] - 0.25 * step
    lon_lo, lon_hi = gtx_record["lon_west"] + 0.25 * step, gtx_record["lon_east"] - 0.25 * step
    lats = rng.uniform(lat_lo, lat_hi, size=count)
    lons = rng.uniform(lon_lo, lon_hi, size=count)
    return {
        "count": int(count), "seed": int(seed),
        "rule": "uniform inside the crop's node extent, a quarter node in from each edge",
        "lat_deg": [round(float(v), 9) for v in lats],
        "lon_deg": [round(float(v), 9) for v in lons],
        "undulation_bilinear_m": [round(grid.undulation(la, lo), 6) for la, lo in zip(lats, lons)],
        "undulation_cubic_m": [round(grid.undulation_cubic(la, lo), 6) for la, lo in zip(lats, lons)],
    }


def write_geoid_samples(grid: GeoidGrid, gtx_record: Dict[str, Any],
                        origin_lat_deg: float, origin_lon_deg: float, path) -> Dict[str, Any]:
    """The crop's companion ``<key>_geoid.json``: the gtx record, the
    origin's undulation both ways and the interior samples, all from the
    full grid. Returns ``{file, sha256, count}`` for the datum block."""
    document = {
        "geoid_samples_version": 1,
        "gtx": dict(gtx_record),
        "grid": grid.source(),
        "origin": {"lat_deg": float(origin_lat_deg), "lon_deg": float(origin_lon_deg),
                   "undulation_bilinear_m": grid.undulation(origin_lat_deg, origin_lon_deg),
                   "undulation_cubic_m": grid.undulation_cubic(origin_lat_deg, origin_lon_deg)},
        "interior": interior_samples(grid, gtx_record),
        "note": ("every value here is the FULL grid's; an evaluator of the .gtx crop "
                 "(PROJ vgridshift, bilinear) must agree with undulation_bilinear_m "
                 "at every point, which checks the crop's nodes and alignment "
                 "independently of this module's interpolation code"),
    }
    path = Path(path)
    path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return {"file": path.name, "sha256": sha256_of(path), "count": document["interior"]["count"]}


def write_gtx_bundle(grid: GeoidGrid, bbox: Sequence[float], out_dir, key: str,
                     origin_lat_deg: float, origin_lon_deg: float) -> Dict[str, Any]:
    """The bake's two geoid files beside the raster: ``<key>_geoid.gtx``
    and ``<key>_geoid.json``; returns the gtx record extended with the
    samples file (the datum block's ``gtx`` sub-block)."""
    out_dir = Path(out_dir)
    record = write_gtx(grid, bbox, out_dir / f"{key}_geoid.gtx")
    samples = write_geoid_samples(grid, record, origin_lat_deg, origin_lon_deg,
                                  out_dir / f"{key}_geoid.json")
    record["samples_file"] = samples["file"]
    record["samples_sha256"] = samples["sha256"]
    record["samples_count"] = samples["count"]
    return record


def undulation_range(grid: GeoidGrid, bbox: Sequence[float],
                     interpolation: Optional[str] = None,
                     steps_per_node: int = 4) -> Dict[str, Any]:
    """N's min / max over the scene bbox on a lattice of a quarter node
    (the bbox corners included), by the model's interpolation: the bound
    on taking the origin's N for the whole scene."""
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in bbox)
    step = grid.posting_deg / steps_per_node
    lats = np.arange(lat_min, lat_max + step * 0.5, step)
    lons = np.arange(lon_min, lon_max + step * 0.5, step)
    lats = np.unique(np.clip(np.append(lats, lat_max), -90.0, 90.0))
    lons = np.unique(np.append(lons, lon_max))
    values = [grid.undulation_at(la, lo, interpolation) for la in lats for lo in lons]
    return {"scene_bbox_deg": [lat_min, lat_max, lon_min, lon_max],
            "lattice_step_deg": step, "samples": len(values),
            "undulation_min_m": float(min(values)), "undulation_max_m": float(max(values)),
            "undulation_range_m": float(max(values) - min(values)),
            "note": ("N is taken at the scene origin for the whole flight; the range "
                     "bounds the error of that choice anywhere in the bbox")}


def physics_frame_block(frame: str = PHYSICS_FRAME_ORTHOMETRIC) -> Dict[str, Any]:
    """The frame the physics flies in, named (C2 of the blueprint)."""
    if frame not in PHYSICS_FRAMES:
        raise ValueError(f"physics frame {frame!r} is not one of {PHYSICS_FRAMES}")
    return {
        "frame": frame,
        "jsbsim_h_sl": "orthometric height in the ellipsoidal slot (unchanged)",
        "jsbsim_ecef": "radially low by undulation_m (JSBSim's own position/ecef-*)",
        "export": "hae_m = altitude_m + undulation_m (the runner's appended channel; DIS reads it)",
        "atmosphere": "evaluated at the orthometric number (on the geoid), as before",
        "ellipsoid_frame": ("refused by name (datum.physics_frame_unsupported): flying at HAE "
                            "with the atmosphere kept on the geoid needs the uniform "
                            "delta-T / P-sl recipe measured in the blueprint, not applied here"),
        "note": PHYSICS_FRAME_NOTE,
    }


def datum_block(origin_lat_deg: float, origin_lon_deg: float,
                orthometric_height_m: float,
                location_key: Optional[str] = None,
                grid: Optional[GeoidGrid] = None,
                vertical_datum_of_heights: str = BAKE_DATUM,
                bbox: Optional[Sequence[float]] = None,
                gtx: Optional[Dict[str, Any]] = None,
                interpolation: Optional[str] = None,
                physics_frame: str = PHYSICS_FRAME_ORTHOMETRIC) -> Dict[str, Any]:
    """The datum block a georeferenced scene carries (sidecar, card,
    manifest). Every number is computed here; consumers copy it.

    ``grid`` defaults to the committed EGM96 grid (as landed; a bake
    chooses through :func:`grid_for_model`). ``interpolation`` defaults
    to the model's own (EGM2008 cubic, EGM96 bilinear); ``undulation_m``
    is by that interpolation and ``undulation_bilinear_m`` always by the
    bilinear one (what an evaluator of the ``.gtx`` crop reproduces).
    ``bbox`` adds N's range over the scene; ``gtx`` the crop record from
    :func:`write_gtx_bundle`. Every in-tree key is kept.
    """
    grid = grid or default_grid()
    key = grid.model_key
    method = interpolation or MODEL_INTERPOLATION[key]
    n = float(grid.undulation_at(origin_lat_deg, origin_lon_deg, method))
    n_bilinear = float(grid.undulation(origin_lat_deg, origin_lon_deg))
    if key == MODEL_EGM96:
        difference = EGM2008_MINUS_EGM96_AT_ORIGIN_M.get(str(location_key))
        bound = MODEL_DIFFERENCE_BOUND_M
        basis = MODEL_DIFFERENCE_BASIS
        # The curated table's value at THIS origin (as landed: measured at
        # the six curated keys, else null, never extrapolated); the live
        # difference (bilinear on both, when both grids are present) rides
        # beside it as egm2008_minus_egm96_at_origin_m.
        live = _egm2008_minus_egm96(origin_lat_deg, origin_lon_deg, egm96=grid)
    else:
        difference = 0.0
        bound = 0.0
        basis = ("the geoid model is the bakes' own (EGM2008); no model difference "
                 "applies; the EGM96 fallback would differ here by "
                 "egm2008_minus_egm96_at_origin_m")
        live = _egm2008_minus_egm96(origin_lat_deg, origin_lon_deg, egm2008=grid)
    block = {
        "vertical_datum_of_heights": vertical_datum_of_heights,
        "geoid_model": grid.model_name,
        "origin_lat_deg": float(origin_lat_deg),
        "origin_lon_deg": float(origin_lon_deg),
        "undulation_m": n,
        "undulation_source": grid.source(method),
        "bilinear_error_bound_m": float(grid.max_bilinear_error_m),
        "model_difference_bound_m": bound,
        "model_difference_basis": basis,
        # EGM2008 - EGM96 at THIS origin where it was measured (the
        # curated locations, or live when both grids are present), else
        # null: not extrapolated. Zero for an EGM2008 block by construction.
        "model_difference_at_origin_m": difference,
        "orthometric_height_of_origin_m": float(orthometric_height_m),
        "ellipsoidal_height_of_origin_m": float(orthometric_height_m) + n,
        "note": DATUM_NOTE,
        # -- D1: the EGM2008 extension (absent-canonical for older readers) --
        "geoid_model_key": key,
        "grid_sha256": grid.sha256,
        "interpolation": method,
        "interpolation_error_bound_m": grid.interpolation_bound_m(method),
        "cubic_error_bound_m": float(grid.max_cubic_error_m),
        "undulation_bilinear_m": n_bilinear,
        "egm2008_minus_egm96_at_origin_m": live,
        "bounds": (undulation_range(grid, bbox, method) if bbox is not None else None),
        "gtx": dict(gtx) if gtx is not None else None,
        "u_model_m": U_MODEL_M[key],
        "u_model_basis": U_MODEL_BASIS[key],
        "tide_system": TIDE_SYSTEM,
        "physics_frame": physics_frame_block(physics_frame),
    }
    return block


def _egm2008_minus_egm96(lat_deg: float, lon_deg: float,
                         egm96: Optional[GeoidGrid] = None,
                         egm2008: Optional[GeoidGrid] = None) -> Optional[float]:
    """EGM2008 - EGM96 at a point, bilinear on both, when both grids can
    be read here; None when the EGM2008 grid is absent (never guessed)."""
    try:
        egm2008 = egm2008 or (egm2008_grid() if egm2008_available() else None)
    except DatumError:
        egm2008 = None
    if egm2008 is None:
        return None
    egm96 = egm96 or default_grid()
    return float(egm2008.undulation(lat_deg, lon_deg) - egm96.undulation(lat_deg, lon_deg))


def model_key_of(block: Dict[str, Any]) -> Optional[str]:
    """The model a datum block was evaluated with (``EGM2008`` |
    ``EGM96`` | None for no geoid), from its key or, for a block written
    before the key existed, from the model's name."""
    key = block.get("geoid_model_key")
    if key in MODEL_KEYS:
        return key
    name = block.get("geoid_model")
    if not isinstance(name, str):
        return None
    return MODEL_EGM2008 if "EGM2008" in name else (MODEL_EGM96 if "EGM96" in name else None)


def flat_datum_block(terrain_elevation_m: float,
                     vertical_datum_of_heights: str = FLAT_DATUM) -> Dict[str, Any]:
    """The block for a scene with no georeferenced heights: says so, with
    the undulation null, so a reader never mistakes absence for zero."""
    return {
        "vertical_datum_of_heights": vertical_datum_of_heights,
        "geoid_model": None,
        "undulation_m": None,
        "terrain_elevation_m": float(terrain_elevation_m),
        "note": FLAT_NOTE,
        "geoid_model_key": None,
        "physics_frame": physics_frame_block(),
    }


def datum_for_heightfield(heightfield, grid: Optional[GeoidGrid] = None,
                          require_block: bool = False) -> Dict[str, Any]:
    """The datum block for a baked heightfield: the sidecar's own when it
    carries one; evaluated from the provenance origin (a bake from before
    the block existed) when it does not -- or, with ``require_block``,
    refused ``datum.sidecar_without_datum`` (a georeferenced RUN takes
    the bake's recorded block, never one evaluated on the fly: re-bake);
    the synthesised block when the heightfield names no real place."""
    provenance = dict(getattr(heightfield, "provenance", {}) or {})
    block = provenance.get("datum")
    if isinstance(block, dict) and "undulation_m" in block:
        return dict(block)
    lat = provenance.get("origin_lat_deg")
    lon = provenance.get("origin_lon_deg")
    if lat is None or lon is None:
        return flat_datum_block(float(heightfield.offset_m),
                                vertical_datum_of_heights=SYNTHESISED_DATUM)
    if require_block:
        raise DatumError(
            "datum.sidecar_without_datum",
            f"the bake {getattr(heightfield, 'name', '?')!r} names a real place "
            f"({lat}, {lon}) but its sidecar carries no datum block (baked before the "
            f"geoid landed); a georeferenced run takes the bake's recorded block, so "
            f"re-bake it (scripts/bake_terrain.py) rather than evaluating one on the fly")
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", heightfield.georeference.crs,
                                       always_xy=True)
    x, y = transformer.transform(float(lon), float(lat))
    orthometric = float(heightfield.elevation_at(x, y))
    return datum_block(float(lat), float(lon), orthometric,
                       location_key=getattr(heightfield, "name", None), grid=grid)


def bake_datum(previous: Dict[str, Any], grid: GeoidGrid, bbox: Sequence[float],
               gtx: Dict[str, Any], location_key: Optional[str] = None) -> Dict[str, Any]:
    """The bake's datum block: the block ``datum_for_heightfield`` wrote
    from the provenance origin, re-evaluated with the bake's chosen grid
    (EGM2008 when cached, else EGM96), the scene bbox and the crop
    record. The origin and its orthometric height are the previous
    block's own, so the two cannot disagree."""
    return datum_block(float(previous["origin_lat_deg"]), float(previous["origin_lon_deg"]),
                       float(previous["orthometric_height_of_origin_m"]),
                       location_key=location_key, grid=grid,
                       vertical_datum_of_heights=previous.get("vertical_datum_of_heights", BAKE_DATUM),
                       bbox=bbox, gtx=gtx)


# -- the terrain sidecar's DTED and CDB documentation --------------------------

#: The GLO-30 accuracies as DECLARED by the Copernicus DEM Product
#: Handbook (unverified here: the handbook could not be fetched), taken
#: as u_D; LE90 -> one sigma by the Gaussian 1.6449 factor.
GLO30_ACCURACY = {
    "absolute_vertical_le90_m": 4.0,
    "absolute_horizontal_ce90_m": 6.0,
    "relative_vertical_le90_m": {"slope_below_20_pct": 2.0, "slope_above_20_pct": 4.0},
    "basis": ("Copernicus DEM Product Handbook, GLO-30 specification: absolute vertical "
              "LE90 < 4 m, absolute horizontal CE90 < 6 m, relative vertical < 2 m (slope "
              "< 20 %) / < 4 m (> 20 %) [unverified here]"),
}
LE90_TO_SIGMA = 1.0 / 1.6449
DTED_REQUIRED = ("origin_lat_deg", "origin_lon_deg", "bbox_deg", "tiles",
                 "verification_vs_source", "vertical_datum")
UNVERIFIED = "[unverified here]"


def dted_block(heightfield, provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """MIL-PRF-89020B DSI/ACC-style metadata for a bake, as documentation
    in the sidecar: the field names follow the standard's Data Set
    Identification and Accuracy records as remembered (the standard
    could not be fetched; every such field is marked unverified), the
    values come from the bake itself, and the GLO-30 accuracies are the
    declared u_D. Refuses ``dted.metadata_incomplete`` when the bake's
    provenance lacks what the fields need. No DTED cell is written."""
    provenance = dict(provenance if provenance is not None
                      else getattr(heightfield, "provenance", {}) or {})
    missing = [key for key in DTED_REQUIRED if provenance.get(key) is None]
    if missing:
        raise DatumError(
            "dted.metadata_incomplete",
            f"the bake's provenance lacks {missing}, so the DTED-style metadata cannot "
            f"name its origin, extent, source tiles, datum or verification; a block "
            f"with blanks would document nothing")
    lat_min, lat_max, lon_min, lon_max = (float(v) for v in provenance["bbox_deg"])
    g = heightfield.georeference
    sigma = GLO30_ACCURACY["absolute_vertical_le90_m"] * LE90_TO_SIGMA
    return {
        "standard": f"MIL-PRF-89020B DSI/ACC-style fields {UNVERIFIED}; documentation only",
        "not_a_dted_file": True,
        "dsi": {
            "security_code": "U",
            "unique_reference": getattr(heightfield, "name", "heightfield"),
            "product_level": (f"posting {g.pixel_size_m:g} m in {g.crs} (DTED level 2 class, "
                              f"1 arc-second, would be the nearest) {UNVERIFIED}"),
            "data_edition": 1,
            "match_merge_version": "A",
            "maintenance_date": None,
            "producer_code": "flightsim glo30 bake (not an NGA producer code)",
            "product_specification": f"MIL-PRF-89020B {UNVERIFIED}",
            "vertical_datum": (f"{provenance['vertical_datum']}; the standard's code E96 "
                               f"names EGM96 and predates EGM2008 {UNVERIFIED}"),
            "horizontal_datum": "WGS84 (the bake's CRS is a UTM zone on WGS 84)",
            "digitizing_collection_system": (f"Copernicus GLO-30 DSM (WorldDEM-30, TanDEM-X) "
                                             f"{UNVERIFIED}"),
            "compilation_date": "source acquisitions 2010-2015 (per the attribution)",
            "origin_lat_deg": lat_min, "origin_lon_deg": lon_min,
            "sw_corner": [lat_min, lon_min], "nw_corner": [lat_max, lon_min],
            "ne_corner": [lat_max, lon_max], "se_corner": [lat_min, lon_max],
            "orientation_angle_deg": 0.0,
            "source_interval_arcsec": 1.0,
            "bake_posting_m": float(g.pixel_size_m),
            "lines": int(heightfield.height), "samples": int(heightfield.width),
            "partial_cell_indicator": "00 (whole crop covered; a nodata fill is counted in the bake)",
            "coverage_bbox_deg": [lat_min, lat_max, lon_min, lon_max],
        },
        "acc": {
            "absolute_horizontal_accuracy_m": GLO30_ACCURACY["absolute_horizontal_ce90_m"],
            "absolute_vertical_accuracy_m": GLO30_ACCURACY["absolute_vertical_le90_m"],
            "relative_horizontal_accuracy_m": None,
            "relative_vertical_accuracy_m": GLO30_ACCURACY["relative_vertical_le90_m"],
            "accuracy_outline_flag": 0,
            "basis": GLO30_ACCURACY["basis"],
            "u_D": {"vertical_le90_m": GLO30_ACCURACY["absolute_vertical_le90_m"],
                    "vertical_sigma_m": sigma,
                    "horizontal_ce90_m": GLO30_ACCURACY["absolute_horizontal_ce90_m"],
                    "form": "declared (the product's own statement), not measured here"},
            "bake_verification_vs_source": dict(provenance["verification_vs_source"]),
        },
        "source_tiles": dict(provenance["tiles"]),
        "not_claimed": ("no DTED cell is written; the field names are from memory of "
                        "MIL-PRF-89020B and the accuracies are the product's declarations; "
                        "the bake's own verification is against its source mosaic, not "
                        "against ground truth"),
    }


def cdb_descriptor_block(heightfield, provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """An OGC CDB-style descriptor for the bake, documentation only: what
    a CDB elevation dataset would say about these heights. No CDB
    datastore or tile is written; the CDB conventions are from memory
    and marked unverified."""
    provenance = dict(provenance if provenance is not None
                      else getattr(heightfield, "provenance", {}) or {})
    lat = provenance.get("origin_lat_deg")
    lon = provenance.get("origin_lon_deg")
    geocell = (None if lat is None or lon is None
               else [int(np.floor(float(lat))), int(np.floor(float(lon)))])
    return {
        "standard": f"OGC CDB 1.x {UNVERIFIED}; documentation only",
        "dataset": f"001 Elevation, component selector 1 (primary terrain elevation) {UNVERIFIED}",
        "geocell": geocell,
        "horizontal_reference": "WGS 84 geographic (EPSG:4326) tiles; this bake is a UTM raster",
        "vertical_reference": (f"CDB elevations are orthometric (EGM96 by the standard's "
                               f"convention {UNVERIFIED}); these heights are "
                               f"{provenance.get('vertical_datum')}"),
        "posting_m": float(heightfield.georeference.pixel_size_m),
        "lod_note": f"a 30 m posting is near CDB LOD 5-6 {UNVERIFIED}",
        "datastore_written": False,
        "not_claimed": "no CDB datastore, tile or metadata file is written; a descriptor only",
    }


# -- the spec's datum block -------------------------------------------------------

def _word(field) -> Any:
    return getattr(field, "value", field)


def datum_spec_problems(datum) -> List[DatumError]:
    """The refusals a spec ``datum`` block meets, in field order (the
    same list for the validator and the runner). ``datum`` is a
    DatumSpec or a dict of its fields (each a Quantity or a value):
    ``vertical`` must be ``orthometric`` (``ellipsoidal`` is refused
    ``datum.physics_frame_unsupported`` until the physics frame handles
    it, as is any other word), ``physics_frame`` must be ``orthometric``
    (``ellipsoid`` likewise), ``geoid_model`` null or one of the two
    models (``datum.model_mismatch`` otherwise; a match against the
    bake's model is the runner's, at the point the spec meets the bake).
    Empty for the default block."""
    if datum is None:
        return []
    get = (lambda name: datum.get(name)) if isinstance(datum, dict) else (
        lambda name: getattr(datum, name, None))
    out: List[DatumError] = []
    vertical = _word(get("vertical"))
    if vertical != VERTICAL_ORTHOMETRIC:
        out.append(DatumError(
            "datum.physics_frame_unsupported",
            f"datum.vertical {vertical!r}: the physics frame flies orthometric numbers "
            f"(JSBSim h-sl) and applies the geoid at export; ellipsoidal heights are "
            f"not handled until the physics frame does (the C3 recipe in the "
            f"blueprint); state 'orthometric' or omit the block"))
    frame = _word(get("physics_frame"))
    if frame != PHYSICS_FRAME_ORTHOMETRIC:
        out.append(DatumError(
            "datum.physics_frame_unsupported",
            f"datum.physics_frame {frame!r}: only the orthometric frame is flown "
            f"(the ellipsoid frame needs the atmosphere kept on the geoid by the "
            f"delta-T / P-sl recipe, measured but not applied); state "
            f"'orthometric' or omit the block"))
    model = _word(get("geoid_model"))
    if model is not None and model not in MODEL_KEYS:
        out.append(DatumError(
            "datum.model_mismatch",
            f"datum.geoid_model {model!r} is not a geoid model this build carries "
            f"({', '.join(MODEL_KEYS)}); the bake's model is checked against the "
            f"declared one, never substituted"))
    return out


def check_model_declared(declared: Optional[str], block: Dict[str, Any]) -> None:
    """The spec's declared model against the bake's block: refuses
    ``datum.model_mismatch`` when they differ, or when a model is
    declared for a scene that carries none (a flat slab, a synthesised
    ridge). A null declaration accepts whatever the bake carries."""
    if declared is None:
        return
    actual = model_key_of(block)
    if actual is None:
        raise DatumError(
            "datum.model_mismatch",
            f"the spec declares geoid model {declared!r} but the scene carries no geoid "
            f"({block.get('vertical_datum_of_heights')}); a declaration about a model "
            f"the scene does not use cannot be honoured")
    if actual != declared:
        raise DatumError(
            "datum.model_mismatch",
            f"the spec declares geoid model {declared!r} but the bake's datum block was "
            f"evaluated with {actual!r} ({block.get('geoid_model')}); re-bake with the "
            f"declared model or declare the bake's")


#: The channels the runner appends after the output digest (contract:
#: core/scenario/runner.py datum_run) and their per-frame keys.
TELEMETRY_COLUMNS = ("undulation_m", "hae_m")
FRAME_KEYS = ("state.undulation_m", "state.hae_m")
VARIABLE_NAME = "scene.geoid_undulation_m"
STANDARDS = {MODEL_EGM96: "EGM96 (Lemoine et al. 1998)",
             MODEL_EGM2008: "EGM2008 (Pavlis et al. 2012)"}


def undulation_variable(datum: Dict[str, Any],
                        run: Optional[Dict[str, Any]] = None) -> AppliedVariable:
    """The ``scene.geoid_undulation_m`` record for a run's datum block.

    Null test: N at the origin against 0 -- the difference is the datum
    error the branch carried before the block; the threshold is the
    grid's own interpolation error bound (a shift under the
    interpolation error would not be distinguishable). A flat scene
    records the variable as not applied: value null, no null test, and
    says why. ``run`` (the runner's) adds what only a flight measures:
    the appended channels' readback, the bounded invariance (the
    recorded columns' digest re-taken after the channels were
    appended), and the spec's declarations.

    The model is the block's: ``EGM2008 cubic`` (the bakes' own datum,
    GeographicLib's default interpolation) or ``EGM96 bilinear`` (the
    fallback, its difference to EGM2008 bounded in the block).
    """
    n = datum.get("undulation_m")
    georeferenced = isinstance(n, (int, float))
    key = model_key_of(datum) or MODEL_EGM96
    method = datum.get("interpolation") or INTERPOLATION
    model_name = f"{key} {method}"
    bound = datum.get("interpolation_error_bound_m", datum.get("bilinear_error_bound_m"))
    gtx = datum.get("gtx") or {}
    parameters = {
        "vertical_datum_of_heights": datum.get("vertical_datum_of_heights"),
        "origin_lat_deg": datum.get("origin_lat_deg"),
        "origin_lon_deg": datum.get("origin_lon_deg"),
        "interpolation": method,
        "bilinear_error_bound_m": datum.get("bilinear_error_bound_m"),
        "model_difference_bound_m": datum.get("model_difference_bound_m"),
        "model_difference_at_origin_m": datum.get("model_difference_at_origin_m"),
        "grid_sha256": (datum.get("undulation_source") or {}).get("sha256"),
        "ellipsoidal_height_of_origin_m": datum.get("ellipsoidal_height_of_origin_m"),
        # D1: the model, its bounds, the crop, the frame.
        "model": key,
        "interpolation_error_bound_m": bound,
        "undulation_bilinear_m": datum.get("undulation_bilinear_m"),
        "bounds": datum.get("bounds"),
        "gtx_file": gtx.get("file"),
        "gtx_sha256": gtx.get("sha256"),
        "physics_frame": (datum.get("physics_frame") or {}).get("frame", PHYSICS_FRAME_ORTHOMETRIC),
        "u_model_m": datum.get("u_model_m"),
        "tide_system": datum.get("tide_system"),
        "channels": {"undulation_m": ("N at the scene origin, constant over the flight; 0 "
                                      "on a scene with no geoid (the frame's definition, "
                                      "not an evaluation: the datum block keeps null)"),
                     "hae_m": "altitude_m + undulation_m: the height above the WGS 84 ellipsoid"},
    }
    if run is not None:
        parameters.update({k: v for k, v in run.items() if k != "readback"})
    null_test = None
    if georeferenced:
        null_test = NullTest(
            quantity="geoid undulation applied at the scene origin",
            unit="m", with_value=float(n), without_value=0.0,
            threshold=float(bound or 0.0),
            note="without = the branch before the datum block (N taken as 0); "
                 "the difference is the datum error every georeferenced "
                 "scene carried")
    readback = None
    if run is not None and isinstance(run.get("readback"), Readback):
        readback = run["readback"]
    uncertainty = None
    if georeferenced and datum.get("u_model_m") is not None:
        uncertainty = {
            "u_input": {"value": float(datum["u_model_m"]), "unit": "m",
                        "rule": f"declared model spread ({datum.get('u_model_basis')}); "
                                f"GUM eq. 10 with sensitivity 1 on hae_m",
                        "sensitivity": {"hae_m": 1.0}},
            "u_num": None,
        }
    return AppliedVariable(
        name=VARIABLE_NAME,
        value=float(n) if georeferenced else None,
        unit="m", source="derived",
        model_name=model_name if georeferenced else f"{model_name} (not applied: no georeferenced heights)",
        parameters=parameters,
        references=REFERENCES,
        properties_written=(),
        telemetry_columns=TELEMETRY_COLUMNS,
        frame_keys=FRAME_KEYS,
        null_test=null_test,
        # Record 2: the structured model beside the string, the provenance
        # text and the citation. Nothing is written to JSBSim, so there is
        # no jsbsim_writes; the readback (when a run supplies it) grades
        # the recorder's appended column, not JSBSim's property store.
        model=Model(
            name=model_name, standard=STANDARDS[key],
            version=MODEL_NAMES[key],
            parameters={"interpolation": method,
                        "interpolation_error_bound_m": bound,
                        "bilinear_error_bound_m": datum.get("bilinear_error_bound_m"),
                        "applied": georeferenced},
            references=REFERENCES),
        frm=(f"the scene origin's undulation, {method} on the {key} grid"
             if georeferenced else "no georeferenced heights: not evaluated"),
        std=(f"GeographicLib {'egm2008-5' if key == MODEL_EGM2008 else 'egm96-15'} header "
             f"({'MaxCubicError' if method == CUBIC else 'MaxBilinearError'} {bound})"),
        readback=readback,
        uncertainty=uncertainty,
        not_claimed=(
            "no height is converted: JSBSim h-sl stays ellipsoidal and the "
            "orthometric heights fed to it are unchanged, so JSBSim altitude "
            "equals orthometric height; ellipsoidal = altitude + undulation_m",
            ("EGM96 is not EGM2008 (the bakes' datum); the difference is "
             "bounded by model_difference_bound_m and measured only at the "
             "curated origins" if key == MODEL_EGM96 else
             "the model uncertainty is declared (u_model_m), not measured here; "
             "the tide system is not verified"),
            f"the interpolation is {method} on a {'5' if key == MODEL_EGM2008 else '15'}-minute "
            f"grid; its error bound is the header's, not the model's error against the geoid",
            "N is the origin's for the whole flight; its range over the scene bbox "
            "(parameters.bounds) is the bound on that choice, not a per-sample evaluation",
        ) if georeferenced else (
            "no georeferenced heights in this scene, so no undulation was "
            "evaluated; the spec's terrain_elevation is fed to JSBSim as an "
            "ellipsoidal height and is whatever the spec says it is",
            "the undulation_m channel carries 0 by the frame's definition (hae_m = "
            "altitude_m), never an evaluated undulation; the block's undulation_m is null",
        ),
    )
