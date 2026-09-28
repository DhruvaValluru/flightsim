"""The vertical datum: the EGM96 geoid undulation N, and the datum block.

The measured fact this module answers (docs/PHASE3_GAP_ANALYSIS.md P10):
the GLO-30 bakes' heights are EGM2008 orthometric, JSBSim's sea level is
the WGS 84 ellipsoid (measured here: ``position/radius-to-vehicle-ft``
equals the WGS 84 ellipsoid radius plus ``h-sl`` to 0.1 ft at three
latitudes), and nothing on the branch accounted for the separation N
between the two -- +52.52 m at the Matterhorn scene, -25.94 m at
Yosemite, +41.47 m at Fuji, -29.84 m at Everest, -23.40 m at the Grand
Canyon, -30.54 m at the Flint Hills.

What this module does
---------------------
* :func:`load_grid` reads GeographicLib's ``egm96-15.pgm`` from
  ``assets/geoid`` and REFUSES BY NAME (``terrain.geoid``) when the file
  is absent or its SHA-256 is not the committed one: a geoid grid that
  is not the one the tests measured is not a geoid grid.
* :func:`undulation` evaluates N(lat, lon) by bilinear interpolation on
  the grid, the way GeographicLib's ``Geoid`` class does at its default
  setting; the file's own header bounds the interpolation error
  (``MaxBilinearError 1.152`` m, carried as ``bilinear_error_bound_m``).
* :func:`datum_block` assembles the block the bake sidecar, the run card
  and the capture manifest carry: which datum the heights are in, which
  geoid model was used, N at the scene origin with its source, the
  interpolation and model-difference bounds, and the ellipsoidal height
  of the origin (= orthometric + N).
* :func:`undulation_variable` is the ``AppliedVariable`` record
  (core/records.py) for ``scene.geoid_undulation_m``: its null test is N
  at the origin against 0, because that difference IS the datum error
  the branch had before this module.

What is NOT claimed
-------------------
* The heights are not converted. JSBSim's ``h-sl`` stays ellipsoidal by
  definition and the orthometric heights fed to it are unchanged, so a
  JSBSim altitude on this branch equals an orthometric height; the block
  records N so a consumer can form the ellipsoidal height, and nothing
  downstream is moved. Relative geometry within a scene never depended
  on N and still does not.
* EGM96 is not EGM2008. The bakes' datum is EGM2008; the committed grid
  is EGM96 (2 MB, versus 19 MB for the coarsest EGM2008 grid). The
  difference was MEASURED here from GeographicLib's ``egm2008-5.pgm``
  (not committed) at every EGM96 grid node: 11.985 m at most (28.5 N,
  94.5 E), 0.72 m RMS, and at the six curated origins the values in
  :data:`EGM2008_MINUS_EGM96_AT_ORIGIN_M`. The stated bound
  :data:`MODEL_DIFFERENCE_BOUND_M` adds both grids' bilinear error
  bounds to the node maximum; between nodes nothing finer was measured.
  Pavlis et al. 2012 (the EGM2008 paper) could not be fetched here and
  is cited unverified.
* Bilinear on a 15-minute grid: the header's own bound of 1.152 m is
  the interpolation error, not the model's error against the true geoid.
"""

from __future__ import annotations

import functools
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from core.records import AppliedVariable, Model, NullTest

REPO = Path(__file__).resolve().parents[2]

#: The committed grid and the digests the loader checks it against.
GRID_PATH = REPO / "assets" / "geoid" / "egm96-15.pgm"
GRID_SHA256 = "2a12f13b6df65cdea52432c7fa1b43f34b007148eb817bf032af5af710905caa"
TARBALL_SHA256 = "8b1ebad1ebae0a045502d0edb9cc51553da1d3914f01e07470c11b3bed75048e"
TARBALL_URL = ("https://sourceforge.net/projects/geographiclib/files/"
               "geoids-distrib/egm96-15.tar.bz2/download")

MODEL_NAME = "EGM96 15-minute grid (GeographicLib egm96-15)"
INTERPOLATION = "bilinear"

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
)


class GeoidError(Exception):
    """The geoid grid cannot be used; refused by name (``terrain.geoid``)."""

    constraint = "terrain.geoid"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"terrain.geoid: {message}")


_HEADER = re.compile(
    rb"P5\s*(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s*(?:#[^\n]*\n\s*)*(\d+)\s")


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

    @property
    def width(self) -> int:
        return int(self.values.shape[1])

    @property
    def height(self) -> int:
        return int(self.values.shape[0])

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

    def source(self) -> Dict[str, Any]:
        """Provenance of every N this grid returns."""
        return {
            "file": str(Path(self.path).relative_to(REPO)
                        if str(self.path).startswith(str(REPO)) else self.path),
            "sha256": self.sha256,
            "tarball_sha256": TARBALL_SHA256,
            "tarball_url": TARBALL_URL,
            "description": self.description,
            "interpolation": INTERPOLATION,
            "grid": [self.width, self.height],
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
    desc = re.search(r"# Description ([^\n]*)", header)
    return GeoidGrid(
        values=values,
        offset_m=float(offset.group(1)), scale_m=float(scale.group(1)),
        max_bilinear_error_m=float(max_err.group(1)) if max_err else float("nan"),
        rms_bilinear_error_m=float(rms_err.group(1)) if rms_err else float("nan"),
        description=desc.group(1).strip() if desc else "",
        sha256=sha256, path=str(path))


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


@functools.lru_cache(maxsize=1)
def default_grid() -> GeoidGrid:
    """The committed grid, read and checked once per process."""
    return load_grid()


def undulation(lat_deg: float, lon_deg: float,
               grid: Optional[GeoidGrid] = None) -> float:
    """EGM96 geoid undulation N (m) at a point: ellipsoidal = orthometric + N."""
    return (grid or default_grid()).undulation(lat_deg, lon_deg)


def datum_block(origin_lat_deg: float, origin_lon_deg: float,
                orthometric_height_m: float,
                location_key: Optional[str] = None,
                grid: Optional[GeoidGrid] = None,
                vertical_datum_of_heights: str = BAKE_DATUM) -> Dict[str, Any]:
    """The datum block a georeferenced scene carries (sidecar, card,
    manifest). Every number is computed here; consumers copy it."""
    grid = grid or default_grid()
    n = float(grid.undulation(origin_lat_deg, origin_lon_deg))
    difference = EGM2008_MINUS_EGM96_AT_ORIGIN_M.get(str(location_key))
    return {
        "vertical_datum_of_heights": vertical_datum_of_heights,
        "geoid_model": MODEL_NAME,
        "origin_lat_deg": float(origin_lat_deg),
        "origin_lon_deg": float(origin_lon_deg),
        "undulation_m": n,
        "undulation_source": grid.source(),
        "bilinear_error_bound_m": float(grid.max_bilinear_error_m),
        "model_difference_bound_m": MODEL_DIFFERENCE_BOUND_M,
        "model_difference_basis": MODEL_DIFFERENCE_BASIS,
        # EGM2008 - EGM96 at THIS origin where it was measured (the
        # curated locations), else null: not extrapolated.
        "model_difference_at_origin_m": difference,
        "orthometric_height_of_origin_m": float(orthometric_height_m),
        "ellipsoidal_height_of_origin_m": float(orthometric_height_m) + n,
        "note": DATUM_NOTE,
    }


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
    }


def datum_for_heightfield(heightfield, grid: Optional[GeoidGrid] = None) -> Dict[str, Any]:
    """The datum block for a baked heightfield: the sidecar's own when it
    carries one; evaluated from the provenance origin (a bake from before
    the block existed) when it does not; the synthesised block when the
    heightfield names no real place."""
    provenance = dict(getattr(heightfield, "provenance", {}) or {})
    block = provenance.get("datum")
    if isinstance(block, dict) and "undulation_m" in block:
        return dict(block)
    lat = provenance.get("origin_lat_deg")
    lon = provenance.get("origin_lon_deg")
    if lat is None or lon is None:
        return flat_datum_block(float(heightfield.offset_m),
                                vertical_datum_of_heights=SYNTHESISED_DATUM)
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", heightfield.georeference.crs,
                                       always_xy=True)
    x, y = transformer.transform(float(lon), float(lat))
    orthometric = float(heightfield.elevation_at(x, y))
    return datum_block(float(lat), float(lon), orthometric,
                       location_key=getattr(heightfield, "name", None), grid=grid)


def undulation_variable(datum: Dict[str, Any]) -> AppliedVariable:
    """The ``scene.geoid_undulation_m`` record for a run's datum block.

    Null test: N at the origin against 0 -- the difference is the datum
    error the branch carried before the block; the threshold is the
    grid's own bilinear error bound (a shift under the interpolation
    error would not be distinguishable). A flat scene records the
    variable as not applied: value null, no null test, and says why.
    """
    n = datum.get("undulation_m")
    georeferenced = isinstance(n, (int, float))
    parameters = {
        "vertical_datum_of_heights": datum.get("vertical_datum_of_heights"),
        "origin_lat_deg": datum.get("origin_lat_deg"),
        "origin_lon_deg": datum.get("origin_lon_deg"),
        "interpolation": INTERPOLATION,
        "bilinear_error_bound_m": datum.get("bilinear_error_bound_m"),
        "model_difference_bound_m": datum.get("model_difference_bound_m"),
        "model_difference_at_origin_m": datum.get("model_difference_at_origin_m"),
        "grid_sha256": (datum.get("undulation_source") or {}).get("sha256"),
        "ellipsoidal_height_of_origin_m": datum.get("ellipsoidal_height_of_origin_m"),
    }
    null_test = None
    if georeferenced:
        null_test = NullTest(
            quantity="geoid undulation applied at the scene origin",
            unit="m", with_value=float(n), without_value=0.0,
            threshold=float(datum.get("bilinear_error_bound_m") or 0.0),
            note="without = the branch before the datum block (N taken as 0); "
                 "the difference is the datum error every georeferenced "
                 "scene carried")
    return AppliedVariable(
        name="scene.geoid_undulation_m",
        value=float(n) if georeferenced else None,
        unit="m", source="derived",
        model="EGM96 bilinear" if georeferenced else "EGM96 bilinear (not applied: no georeferenced heights)",
        parameters=parameters,
        references=REFERENCES,
        properties_written=(),
        telemetry_columns=(),
        frame_keys=(),
        null_test=null_test,
        # Record 2: the structured model beside the string, the provenance
        # text and the citation. Nothing is written to JSBSim, so there is
        # no readback and no jsbsim_writes (an honest absence, not a gap).
        model_block=Model(
            name="EGM96 bilinear", standard="EGM96 (Lemoine et al. 1998)",
            version=MODEL_NAME,
            parameters={"interpolation": INTERPOLATION,
                        "bilinear_error_bound_m": datum.get("bilinear_error_bound_m"),
                        "applied": georeferenced},
            references=REFERENCES),
        frm=("the scene origin's undulation, bilinear on the committed grid"
             if georeferenced else "no georeferenced heights: not evaluated"),
        std="GeographicLib egm96-15 header (MaxBilinearError 1.152)",
        not_claimed=(
            "no height is converted: JSBSim h-sl stays ellipsoidal and the "
            "orthometric heights fed to it are unchanged, so JSBSim altitude "
            "equals orthometric height; ellipsoidal = altitude + undulation_m",
            "EGM96 is not EGM2008 (the bakes' datum); the difference is "
            "bounded by model_difference_bound_m and measured only at the "
            "curated origins",
            "the interpolation is bilinear on a 15-minute grid; its error "
            "bound is the header's, not the model's error against the geoid",
        ) if georeferenced else (
            "no georeferenced heights in this scene, so no undulation was "
            "evaluated; the spec's terrain_elevation is fed to JSBSim as an "
            "ellipsoidal height and is whatever the spec says it is",
        ),
    )
