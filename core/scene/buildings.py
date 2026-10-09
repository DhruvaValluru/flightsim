"""Buildings from CACHED footprints: LoD1 blocks on a DTM pad (blueprint
section 4, work item W2; CityGML 2.0 LoD1 = extruded footprints).

Nothing is fetched during a run and no OSM is used anywhere. A footprint
set is a file the operator placed in ``assets/buildings/<key>.jsonl``
(one JSON object per line: ``{"id", "polygon" [[lon, lat], ...],
"height_m" | null, "height_source" | null}``) beside a provenance sidecar
``<key>.provenance.json`` (``source``, ``licence``, ``fetched_at``,
``sha256`` of the data file's bytes, ``attribution``, ``synthetic``). The
sidecar's licence must be in :data:`ALLOWED_LICENCES`, whose verdict per
licence (share-alike, attribution, dataset distribution, AI training)
rides into the record; the data file's digest must be the sidecar's; every
id must be a non-empty string stated in the file and stated once.

Refusals by name (``BuildingsError.constraint``):

* ``buildings.uncached`` -- no data file or no sidecar for the key
  (nothing is fetched: the named step is the operator's, on a networked
  machine, and the README in assets/buildings says how the cache is made);
* ``buildings.licence`` -- a licence outside the allow-list, or none
  stated;
* ``buildings.unverified`` -- the data file's sha256 is not the sidecar's,
  or the sidecar lacks one;
* ``buildings.ids`` -- an id missing, not a string, empty, or stated twice
  (an id generated at load time would change between runs, so it is not
  an id).

LoD1, per building (:func:`extrude`): the footprint projected into the
bake's CRS, its area by the shoelace formula, its height from the file
(``height_source`` recorded as stated) or :data:`DEFAULT_HEIGHT_M` = 6 m
with the source ``default`` and the basis stated (no CityGML basis: a
stand-in, not a measurement), and the DTM PAD: the bake is a surface
model (GLO-30 is a DSM; a building's own roof is in it), so extruding
from the bake's height at the footprint would stack a block on its own
roof. The block is seated on the minimum of the bake sampled on a ring
one bake pixel outside the footprint's vertices and at the vertices
(``pad_seat_m``; a stated DTM estimate, not a DTM), and ``pad_depth_m``
= the bake at the centroid minus the seat records how far the seat sits
below the surface model. Volume = area x height (measured on a fixture
in tests/test_buildings.py).

The vintage mismatch (:func:`vintage_mismatch`): WorldCover's classes are
2021, GLO-30's heights 2010-2015, so a built-up pixel may hold no
building in the DSM (built after the survey) or a building the map does
not call built-up. The fraction of built-up pixels whose DSM - DTM < 2 m
(DTM estimated as the local minimum over a (2w+1) x (2w+1) window, w =
:data:`VINTAGE_WINDOW_PX`) is the measured number, recorded, not
reconciled. Measured here on the synthetic fixture; the real-bake
measurement is the networked step (a WorldCover map beside a GLO-30 bake).

What is NOT claimed: LoD1 only (a flat roof at one height per footprint;
no roof shape, no facade, no LoD2); no per-instance ids in the ID image
(the 8-bit stencil holds one ``building:all`` aggregate; the per-building
ids live in this document); no resemblance to the real place beyond the
source's own accuracy; the pad seat is a ring-minimum estimate, not a
terrain model; the 6 m default is a stand-in with no CityGML basis;
nothing engine-side is verified here (the buildings on/off pixel null is
Windows clause 7 of the blueprint).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..records import AppliedVariable, Model, NullTest, records_block

REPO = Path(__file__).resolve().parents[2]
#: Where the operator's cached footprint sets live (no set is committed).
BUILDINGS_DIR = REPO / "assets" / "buildings"

#: CityGML 2.0 LoD1 block height when the source states none: a stated
#: stand-in with NO CityGML basis (the standard prescribes no default;
#: two storeys of ~3 m is the convention this build declares).
DEFAULT_HEIGHT_M = 6.0
DEFAULT_HEIGHT_SOURCE = "default"
DEFAULT_HEIGHT_BASIS = ("6 m stand-in: no CityGML basis (LoD1 prescribes no default height); "
                        "a stated convention, not a measurement")

#: The pad seat's ring: one bake pixel outside each vertex.
PAD_RING_PX = 1.0
#: The vintage-mismatch estimator: the DSM minus the local minimum over a
#: (2 w + 1) square window is "the building's height above its
#: surroundings"; below 2 m the DSM holds no building where the map says
#: built-up.
VINTAGE_WINDOW_PX = 2
VINTAGE_THRESHOLD_M = 2.0
#: WorldCover's built-up class code (core/terrain/landcover.py LEGEND).
BUILT_UP_CODE = 50

#: The licence allow-list, per asset (blueprint section 4: a recorded,
#: refusable fact per asset). Each verdict names what the licence permits
#: for a distributed dataset; ``ai_training_permitted`` is ``None`` where
#: the licence text is silent (recorded as unstated, never as yes).
ALLOWED_LICENCES: Dict[str, Dict[str, Any]] = {
    "CDLA-Permissive-2.0": {
        "name": "Community Data License Agreement - Permissive 2.0",
        "share_alike": False, "attribution_required": False,
        "dataset_distribution_permitted": True, "ai_training_permitted": True,
        "basis": "Microsoft Building Footprints README (verified in the blueprint's "
                 "research session); the CDLA-Permissive-2.0 text itself [unverified here]"},
    "CC-BY-4.0": {
        "name": "Creative Commons Attribution 4.0",
        "share_alike": False, "attribution_required": True,
        "dataset_distribution_permitted": True, "ai_training_permitted": None,
        "basis": "Google Open Buildings is CC BY 4.0 / ODbL [unverified here]; the CC BY 4.0 "
                 "deed requires attribution and is silent on AI training"},
    "ODbL-1.0": {
        "name": "Open Data Commons Open Database License 1.0",
        "share_alike": True, "attribution_required": True,
        "dataset_distribution_permitted": True, "ai_training_permitted": None,
        "basis": "Overture / Google Open Buildings alternative licence [unverified here]; "
                 "share-alike applies to a derived database"},
    "CC0-1.0": {
        "name": "Creative Commons Zero 1.0",
        "share_alike": False, "attribution_required": False,
        "dataset_distribution_permitted": True, "ai_training_permitted": True,
        "basis": "public-domain dedication"},
    "synthetic": {
        "name": "synthetic fixture (no licence needed)",
        "share_alike": False, "attribution_required": False,
        "dataset_distribution_permitted": True, "ai_training_permitted": True,
        "basis": "written by hand as a stand-in; the sidecar says synthetic: true"},
}

#: The sidecar keys a cached set must state.
PROVENANCE_KEYS = ("source", "licence", "fetched_at", "sha256", "attribution")


class BuildingsError(Exception):
    """A footprint-set refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


@dataclass(frozen=True)
class Footprint:
    """One footprint as the cache states it: the ring in (lon, lat)."""

    id: str
    ring: Tuple[Tuple[float, float], ...]
    height_m: Optional[float]
    height_source: Optional[str]


@dataclass(frozen=True)
class FootprintSet:
    key: str
    file: Path
    sha256: str
    provenance: Dict[str, Any]
    footprints: Tuple[Footprint, ...]

    @property
    def licence(self) -> str:
        return str(self.provenance["licence"])

    def verdict(self) -> Dict[str, Any]:
        return licence_verdict(self.licence)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def data_path(key: str, cache_dir=None) -> Path:
    return Path(cache_dir or BUILDINGS_DIR) / f"{key}.jsonl"


def provenance_path(key: str, cache_dir=None) -> Path:
    return Path(cache_dir or BUILDINGS_DIR) / f"{key}.provenance.json"


def licence_verdict(licence: Any) -> Dict[str, Any]:
    """The allow-list's verdict for a licence, or ``buildings.licence``
    by name for one outside it (the licence named in the message)."""
    if not isinstance(licence, str) or licence not in ALLOWED_LICENCES:
        raise BuildingsError(
            "buildings.licence",
            f"licence {licence!r} is not in the allow-list {sorted(ALLOWED_LICENCES)}; "
            f"a footprint set under another licence is refused, never used silently")
    return {"licence": licence, **ALLOWED_LICENCES[licence]}


def read_provenance(key: str, cache_dir=None) -> Dict[str, Any]:
    """The sidecar, checked for its keys; ``buildings.uncached`` when
    absent or unreadable."""
    path = provenance_path(key, cache_dir)
    if not path.is_file():
        raise BuildingsError(
            "buildings.uncached",
            f"no provenance sidecar {path} for footprint set {key!r}; nothing is fetched "
            f"during a run -- cache the set with its sidecar (assets/buildings/README.md)")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BuildingsError("buildings.uncached", f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise BuildingsError("buildings.uncached", f"{path} does not hold a mapping")
    missing = [k for k in PROVENANCE_KEYS if k not in document]
    if missing:
        raise BuildingsError("buildings.uncached",
                             f"{path} lacks the provenance keys {missing}")
    return document


def _parse_footprint(line: str, number: int, where: str) -> Footprint:
    try:
        record = json.loads(line)
    except ValueError as exc:
        raise BuildingsError("buildings.ids",
                             f"{where} line {number}: not a JSON object ({exc})") from exc
    if not isinstance(record, dict):
        raise BuildingsError("buildings.ids", f"{where} line {number}: not a JSON object")
    ident = record.get("id")
    if not isinstance(ident, str) or not ident.strip():
        raise BuildingsError(
            "buildings.ids",
            f"{where} line {number}: no stable id (an id generated at load time would "
            f"change between runs, so it is not an id)")
    ring = record.get("polygon")
    if not isinstance(ring, list) or len(ring) < 3:
        raise BuildingsError("buildings.ids",
                             f"{where} line {number} ({ident}): polygon needs at least "
                             f"three vertices")
    vertices: List[Tuple[float, float]] = []
    for vertex in ring:
        try:
            lon, lat = float(vertex[0]), float(vertex[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise BuildingsError("buildings.ids",
                                 f"{where} line {number} ({ident}): a vertex is not "
                                 f"[lon, lat]") from exc
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise BuildingsError("buildings.ids",
                                 f"{where} line {number} ({ident}): a vertex is not finite")
        vertices.append((lon, lat))
    if vertices[0] == vertices[-1] and len(vertices) > 3:
        vertices = vertices[:-1]                # a closed ring is stored open
    height = record.get("height_m")
    if height is not None:
        try:
            height = float(height)
        except (TypeError, ValueError) as exc:
            raise BuildingsError("buildings.ids",
                                 f"{where} line {number} ({ident}): height_m is not a "
                                 f"number") from exc
        if not math.isfinite(height) or height <= 0.0:
            raise BuildingsError("buildings.ids",
                                 f"{where} line {number} ({ident}): height_m {height!r} "
                                 f"is not positive")
    source = record.get("height_source")
    if height is not None and (not isinstance(source, str) or not source.strip()):
        raise BuildingsError("buildings.ids",
                             f"{where} line {number} ({ident}): a stated height names "
                             f"its source")
    return Footprint(id=ident, ring=tuple(vertices), height_m=height,
                     height_source=source if height is not None else None)


def load_footprints(key: str, cache_dir=None) -> FootprintSet:
    """The cached footprint set for ``key``, refused by name (see the
    module docstring). The sidecar is read first, its licence checked
    second, the data file's digest third, the ids last."""
    provenance = read_provenance(key, cache_dir)
    path = data_path(key, cache_dir)
    if not path.is_file():
        raise BuildingsError(
            "buildings.uncached",
            f"no footprint file {path} for set {key!r}; nothing is fetched during a run")
    licence_verdict(provenance.get("licence"))
    recorded = provenance.get("sha256")
    actual = sha256_of(path)
    if not isinstance(recorded, str) or recorded.lower() != actual:
        raise BuildingsError(
            "buildings.unverified",
            f"{path.name}: sha256 {actual[:16]}... is not the sidecar's "
            f"{str(recorded)[:16]}...; the set was changed after it was cached")
    footprints: List[Footprint] = []
    seen = set()
    with path.open("r", encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            footprint = _parse_footprint(line, number, path.name)
            if footprint.id in seen:
                raise BuildingsError(
                    "buildings.ids",
                    f"{path.name}: id {footprint.id!r} is stated twice (line {number}); "
                    f"one id, one building")
            seen.add(footprint.id)
            footprints.append(footprint)
    if not footprints:
        raise BuildingsError("buildings.ids", f"{path.name} states no footprint")
    return FootprintSet(key=key, file=path, sha256=actual, provenance=provenance,
                        footprints=tuple(footprints))


# -- LoD1 ------------------------------------------------------------------

def polygon_area(xy: Sequence[Tuple[float, float]]) -> float:
    """Shoelace area, metres squared, of a ring in projected metres
    (about the first vertex: UTM northings of 5e6 m would otherwise cost
    the cross products a millimetre-squared of cancellation each)."""
    total = 0.0
    n = len(xy)
    ax, ay = xy[0]
    for i in range(n):
        x0, y0 = xy[i][0] - ax, xy[i][1] - ay
        x1, y1 = xy[(i + 1) % n][0] - ax, xy[(i + 1) % n][1] - ay
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def polygon_centroid(xy: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """The area centroid of a ring (the vertex mean for a degenerate one)."""
    n = len(xy)
    ax, ay = xy[0]                              # about the first vertex, as polygon_area
    twice_area = 0.0
    cx = cy = 0.0
    for i in range(n):
        x0, y0 = xy[i][0] - ax, xy[i][1] - ay
        x1, y1 = xy[(i + 1) % n][0] - ax, xy[(i + 1) % n][1] - ay
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(twice_area) < 1e-12:
        return (sum(p[0] for p in xy) / n, sum(p[1] for p in xy) / n)
    return (ax + cx / (3.0 * twice_area), ay + cy / (3.0 * twice_area))


def point_in_polygon(x: float, y: float, xy: Sequence[Tuple[float, float]]) -> bool:
    """Even-odd rule; a point on an edge counts as inside on one side."""
    inside = False
    n = len(xy)
    for i in range(n):
        x0, y0 = xy[i]
        x1, y1 = xy[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < x_cross:
                inside = not inside
    return inside


def _projector(crs: str):
    if crs.upper() in ("EPSG:4326", "OGC:CRS84"):
        return lambda lon, lat: (float(lon), float(lat))
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    def project(lon, lat):
        x, y = transformer.transform(lon, lat)
        return float(x), float(y)
    return project


@dataclass(frozen=True)
class Lod1Building:
    """One extruded block: the footprint in the bake's CRS, seated on the
    DTM pad, ``height_m`` tall."""

    id: str
    xy: Tuple[Tuple[float, float], ...]
    area_m2: float
    centroid: Tuple[float, float]
    height_m: float
    height_source: str
    height_basis: str
    surface_z_m: float          # the bake (DSM) at the centroid
    pad_seat_m: float           # the ring minimum: where the block sits
    pad_depth_m: float          # surface_z_m - pad_seat_m
    volume_m3: float

    @property
    def top_z_m(self) -> float:
        return self.pad_seat_m + self.height_m

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "polygon_xy": [list(p) for p in self.xy],
            "area_m2": self.area_m2, "centroid_xy": list(self.centroid),
            "height_m": self.height_m, "height_source": self.height_source,
            "height_basis": self.height_basis, "surface_z_m": self.surface_z_m,
            "pad_seat_m": self.pad_seat_m, "pad_depth_m": self.pad_depth_m,
            "top_z_m": self.top_z_m, "volume_m3": self.volume_m3,
        }


def pad_seat(heightfield, xy: Sequence[Tuple[float, float]], centroid: Tuple[float, float],
             ring_px: float = PAD_RING_PX) -> Tuple[float, float]:
    """(the bake at the centroid, the ring minimum): the minimum of the
    bake at each vertex and at each vertex pushed ``ring_px`` bake pixels
    outward from the centroid -- the stated DTM estimate a block is seated
    on. Never above the surface at the centroid: a block never floats."""
    ring_m = float(ring_px) * float(heightfield.georeference.pixel_size_m)
    surface = float(heightfield.elevation_at(centroid[0], centroid[1]))
    samples = [surface]
    for x, y in xy:
        samples.append(float(heightfield.elevation_at(x, y)))
        dx, dy = x - centroid[0], y - centroid[1]
        norm = math.hypot(dx, dy)
        if norm > 0.0:
            samples.append(float(heightfield.elevation_at(x + dx / norm * ring_m,
                                                          y + dy / norm * ring_m)))
    return surface, min(samples)


def extrude(footprints: Sequence[Footprint], heightfield,
            default_height_m: float = DEFAULT_HEIGHT_M,
            ring_px: float = PAD_RING_PX) -> Tuple[List[Lod1Building], List[str]]:
    """LoD1 blocks over the bake: each footprint projected into the bake's
    CRS, seated on its pad, extruded to its recorded height or the
    default (the source recorded either way). A footprint whose centroid
    is off the bake is skipped and its id returned (stated, not dropped
    silently)."""
    project = _projector(heightfield.georeference.crs)
    blocks: List[Lod1Building] = []
    outside: List[str] = []
    for footprint in footprints:
        xy = tuple(project(lon, lat) for lon, lat in footprint.ring)
        centroid = polygon_centroid(xy)
        if not heightfield.contains(centroid[0], centroid[1]):
            outside.append(footprint.id)
            continue
        area = polygon_area(xy)
        surface, seat = pad_seat(heightfield, xy, centroid, ring_px)
        if footprint.height_m is not None:
            height, source = float(footprint.height_m), str(footprint.height_source)
            basis = f"the cached set's stated height (source {source!r})"
        else:
            height, source, basis = float(default_height_m), DEFAULT_HEIGHT_SOURCE, DEFAULT_HEIGHT_BASIS
        blocks.append(Lod1Building(
            id=footprint.id, xy=xy, area_m2=area, centroid=centroid, height_m=height,
            height_source=source, height_basis=basis, surface_z_m=surface, pad_seat_m=seat,
            pad_depth_m=surface - seat, volume_m3=area * height))
    return blocks, outside


def height_source_histogram(blocks: Sequence[Lod1Building]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for block in blocks:
        out[block.height_source] = out.get(block.height_source, 0) + 1
    return dict(sorted(out.items()))


# -- the vintage mismatch ---------------------------------------------------------

def local_minimum(z: np.ndarray, window_px: int = VINTAGE_WINDOW_PX) -> np.ndarray:
    """The minimum over a (2 w + 1) square window per pixel (edges
    clamped): the DTM estimate the vintage measurement uses."""
    z = np.asarray(z, dtype=np.float64)
    w = int(window_px)
    if w <= 0:
        return z.copy()
    padded = np.pad(z, w, mode="edge")
    out = np.full_like(z, np.inf)
    h, wd = z.shape
    for dr in range(2 * w + 1):
        for dc in range(2 * w + 1):
            out = np.minimum(out, padded[dr:dr + h, dc:dc + wd])
    return out


def built_mask_from_blocks(heightfield, blocks: Sequence[Lod1Building]) -> np.ndarray:
    """The bake pixels whose centre lies inside a block's footprint."""
    g = heightfield.georeference
    mask = np.zeros((heightfield.height, heightfield.width), dtype=bool)
    for block in blocks:
        xs = [p[0] for p in block.xy]
        ys = [p[1] for p in block.xy]
        c0 = max(0, int(math.floor((min(xs) - g.origin_x_m) / g.pixel_size_m)) - 1)
        c1 = min(heightfield.width - 1, int(math.ceil((max(xs) - g.origin_x_m) / g.pixel_size_m)) + 1)
        r0 = max(0, int(math.floor((g.origin_y_m - max(ys)) / g.pixel_size_m)) - 1)
        r1 = min(heightfield.height - 1, int(math.ceil((g.origin_y_m - min(ys)) / g.pixel_size_m)) + 1)
        for r in range(r0, r1 + 1):
            y = g.origin_y_m - r * g.pixel_size_m
            for c in range(c0, c1 + 1):
                x = g.origin_x_m + c * g.pixel_size_m
                if point_in_polygon(x, y, block.xy):
                    mask[r, c] = True
    return mask


def built_mask_from_classes(codes: np.ndarray, built_code: int = BUILT_UP_CODE) -> np.ndarray:
    """The built-up pixels of a WorldCover class-code array (the bake-grid
    class map I7 writes): code 50."""
    return np.asarray(codes) == int(built_code)


def vintage_mismatch(heightfield, built_mask: np.ndarray, window_px: int = VINTAGE_WINDOW_PX,
                     threshold_m: float = VINTAGE_THRESHOLD_M, mask_source: str = "") -> Dict[str, Any]:
    """The fraction of built-up pixels whose DSM - DTM(estimate) is below
    ``threshold_m``: where the map says built-up but the surface model
    holds nothing 2 m above its surroundings. Recorded, not reconciled."""
    z = heightfield.elevations()
    built = np.asarray(built_mask, dtype=bool)
    if built.shape != z.shape:
        raise ValueError(f"built mask {built.shape} is not the bake's shape {z.shape}")
    dtm = local_minimum(z, window_px)
    above = (z - dtm)[built]
    count = int(above.size)
    below = int(np.count_nonzero(above < float(threshold_m))) if count else 0
    return {
        "built_up_pixels": count,
        "pixels_below_threshold": below,
        "fraction_below_threshold": (below / count) if count else None,
        "threshold_m": float(threshold_m),
        "dtm_estimate": f"local minimum over a {2 * int(window_px) + 1} x "
                        f"{2 * int(window_px) + 1} pixel window",
        "mask_source": mask_source,
        "basis": "WorldCover 2021 classes against GLO-30 2010-2015 heights: a built-up "
                 "pixel with no 2 m rise in the DSM is the vintage mismatch, measured, "
                 "not reconciled; on a synthetic fixture here, the real bake is the "
                 "networked step",
    }


# -- the document and the record --------------------------------------------------

DOCUMENT_VERSION = 1


def buildings_variable(document: Dict[str, Any]) -> AppliedVariable:
    """The ``scene.buildings`` record: count and the height-source
    histogram, the licence verdict, the pad statistics, the vintage
    fraction. Null test: the count with the cached set against 0 without
    one (no set stated composes no building object), threshold 1 --
    connectivity of the cache to the scene, measured; the pixel null
    (buildings on/off in the ID image) is the engine's, NOT RUN here."""
    count = int(document["count"])
    return AppliedVariable(
        name="scene.buildings", value=count, unit="buildings", source="derived",
        model_name="CityGML 2.0 LoD1: footprints extruded to one height on a DTM pad",
        parameters={
            "key": document["key"], "file": document["file"], "sha256": document["sha256"],
            "licence": document["licence"], "attribution": document["provenance"].get("attribution"),
            "source": document["provenance"].get("source"),
            "fetched_at": document["provenance"].get("fetched_at"),
            "synthetic": bool(document["provenance"].get("synthetic", False)),
            "count": count, "outside_bake": document["outside_bake"],
            "height_sources": document["height_sources"],
            "default_height_m": document["default_height_m"],
            "default_height_basis": DEFAULT_HEIGHT_BASIS,
            "pad": document["pad"], "volume_m3": document["volume_m3"],
            "vintage": document["vintage"], "bake": document["bake"],
            "object_id": "building:all",
        },
        references=("OGC CityGML 2.0 (OGC 12-019) LoD1 [unverified here]",),
        properties_written=(), telemetry_columns=(), frame_keys=(),
        null_test=NullTest(
            quantity="buildings extruded from the cached set", unit="buildings",
            with_value=float(count), without_value=0.0, threshold=1.0, kind="reached",
            note="without = no footprint set stated: no building composed, no building:all "
                 "object; with = the cached set over the bake; the pixel null (buildings "
                 "on/off in the ID image) is Windows clause 7, not run here"),
        model=Model(
            name="CityGML 2.0 LoD1 extrusion", standard="OGC CityGML 2.0 (OGC 12-019)",
            version="LoD1",
            parameters={"default_height_m": document["default_height_m"],
                        "pad_ring_px": document["pad"]["ring_px"],
                        "vintage_window_px": document["vintage"].get("window_px")},
            references=("OGC CityGML 2.0 (OGC 12-019) LoD1 [unverified here]",)),
        frm=f"the cached footprint set {document['key']!r} ({document['licence']})",
        std="OGC CityGML 2.0 LoD1: a footprint extruded to one height",
        not_claimed=(
            "LoD1 only: one flat roof per footprint, no roof shape, no facade",
            "no per-instance ids in the ID image: the 8-bit stencil holds one "
            "building:all aggregate; per-building ids live in this document",
            "the pad seat is a ring-minimum estimate over the surface model, not a DTM",
            f"a default height is a {DEFAULT_HEIGHT_M:g} m stand-in with no CityGML basis",
            "no OSM anywhere; nothing fetched during a run",
            "the vintage mismatch is measured on this fixture and recorded, not reconciled",
            "nothing engine-side is verified here",
        ))


def buildings_document(footprints: FootprintSet, heightfield, bake_stem,
                       blocks: Sequence[Lod1Building], outside: Sequence[str],
                       default_height_m: float = DEFAULT_HEIGHT_M,
                       ring_px: float = PAD_RING_PX,
                       vintage: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The ``<bake>_buildings.json`` document: the set's provenance and
    verdict, every block, the histogram, the pad statistics, the vintage
    fraction and the record."""
    depths = [b.pad_depth_m for b in blocks]
    document: Dict[str, Any] = {
        "document_version": DOCUMENT_VERSION,
        "key": footprints.key,
        "file": str(footprints.file),
        "sha256": footprints.sha256,
        "licence": footprints.licence,
        "licence_verdict": footprints.verdict(),
        "provenance": dict(footprints.provenance),
        "bake": {"stem": str(bake_stem), "name": heightfield.name, "sha256": heightfield.digest(),
                 "crs": heightfield.georeference.crs,
                 "pixel_size_m": heightfield.georeference.pixel_size_m},
        "count": len(blocks),
        "outside_bake": list(outside),
        "height_sources": height_source_histogram(blocks),
        "default_height_m": float(default_height_m),
        "default_height_basis": DEFAULT_HEIGHT_BASIS,
        "pad": {"ring_px": float(ring_px),
                "estimate": "ring minimum: the bake at the vertices and one pixel outside "
                            "each, and at the centroid; the block sits on the least",
                "depth_min_m": min(depths) if depths else None,
                "depth_max_m": max(depths) if depths else None,
                "depth_mean_m": (sum(depths) / len(depths)) if depths else None},
        "volume_m3": float(sum(b.volume_m3 for b in blocks)),
        "vintage": dict(vintage or {"fraction_below_threshold": None,
                                     "basis": "not measured: no built-up mask given"}),
        "buildings": [b.to_dict() for b in blocks],
        "object": {"id": "building:all", "class": "building",
                   "basis": "one aggregate object: the 8-bit stencil carries no per-instance id"},
        "not_claimed": [
            "LoD1 only; no OSM; no per-instance ids; nothing engine-side verified here",
        ],
    }
    document["applied_variables"] = records_block([buildings_variable(document)])
    return document


def document_path_for(bake_stem) -> Path:
    """Where a bake's buildings document lives: ``<stem>_buildings.json``."""
    stem = Path(bake_stem).with_suffix("")
    return stem.with_name(f"{stem.name}_buildings.json")


def write_buildings_document(document: Dict[str, Any], path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return path


def ensure_buildings_document(key: str, bake_stem, cache_dir=None,
                              built_codes: Optional[np.ndarray] = None) -> Path:
    """Load the cached set, extrude it over the bake, measure the vintage
    fraction (against ``built_codes`` -- a WorldCover class-code array on
    the bake grid -- when given, else against the blocks' own footprints,
    stated) and write ``<bake>_buildings.json``. Refuses by name through
    :func:`load_footprints`."""
    from ..terrain.heightfield import Heightfield

    footprints = load_footprints(key, cache_dir)
    field = Heightfield.read(bake_stem)
    blocks, outside = extrude(footprints.footprints, field)
    if built_codes is not None:
        mask = built_mask_from_classes(built_codes)
        source = "WorldCover class map (code 50) on the bake grid"
    else:
        mask = built_mask_from_blocks(field, blocks)
        source = "the footprints themselves rasterised on the bake grid (no class map given)"
    vintage = vintage_mismatch(field, mask, mask_source=source)
    vintage["window_px"] = VINTAGE_WINDOW_PX
    document = buildings_document(footprints, field, bake_stem, blocks, outside, vintage=vintage)
    return write_buildings_document(document, document_path_for(bake_stem))


def read_buildings_document(path) -> Dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("document_version") != DOCUMENT_VERSION:
        raise ValueError(f"{path}: buildings document version "
                         f"{document.get('document_version')!r} is not {DOCUMENT_VERSION}")
    return document


def buildings_records(document_path) -> list:
    """The ``scene.buildings`` record for a manifest, re-typed from the
    document, or [] when the scene names none (absent-canonical)."""
    if document_path is None:
        return []
    path = Path(document_path)
    if not path.is_file():
        return []
    document = read_buildings_document(path)
    records = (document.get("applied_variables") or {}).get("applied_variables") or []
    return [AppliedVariable.from_dict(record) for record in records]


def manifest_scene_block(document_path) -> Optional[Dict[str, Any]]:
    """The capture manifest's ``scene.buildings`` sub-block: key, file,
    sha256, licence, count, the object id -- or None."""
    if document_path is None:
        return None
    path = Path(document_path)
    if not path.is_file():
        return None
    document = read_buildings_document(path)
    return {"key": document["key"], "file": document["file"], "sha256": document["sha256"],
            "licence": document["licence"], "count": document["count"],
            "document": str(path), "document_sha256": sha256_of(path),
            "object_id": "building:all"}


def licence_of_key(key: str, cache_dir=None) -> Optional[str]:
    """The cached set's licence word for ``objects[]``, or None when the
    set is not cached (the refusal is the capture command's)."""
    try:
        return str(read_provenance(key, cache_dir).get("licence"))
    except BuildingsError:
        return None


def write_fixture_set(cache_dir, key: str, footprints: Sequence[Dict[str, Any]],
                      licence: str = "synthetic", source: str = "synthetic fixture",
                      attribution: str = "none: synthetic", fetched_at=None,
                      synthetic: bool = True) -> Tuple[Path, Path]:
    """Write a footprint set and its sidecar (the digest measured from
    the bytes written): the fixture writer tests use; an operator caching
    a real set writes the same two files by hand or by script."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = data_path(key, cache_dir)
    lines = [json.dumps(record, sort_keys=True) for record in footprints]
    data.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sidecar = provenance_path(key, cache_dir)
    sidecar.write_text(json.dumps({
        "key": key, "source": source, "licence": licence, "fetched_at": fetched_at,
        "sha256": sha256_of(data), "sha256_of": f"the data file's bytes ({data.name})",
        "attribution": attribution, "synthetic": bool(synthetic),
    }, indent=1), encoding="utf-8")
    return data, sidecar
