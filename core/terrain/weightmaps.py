"""Land-cover weight layers at the Landscape's own resolution (blueprint
section 4, work item W1).

core/terrain/landcover.py rasterises ESA WorldCover onto the BAKE grid
(one 8-bit PNG per legend class, 255 x the fraction of 10 m cells in each
bake cell, summing to exactly 255 with nodata). The engine's Landscape
does not sample the bake grid: core/terrain/landscape.py resamples the
heightmap to a square resolution Unreal accepts (``closest_layout``), so
a weight layer painted at the bake grid would sit one resampling away
from the geometry it is meant to cover. This module makes the layers at
the Landscape's resolution, on the heightmap's OWN sample positions.

The discipline, by construction then verified
---------------------------------------------
* The layout is the one ``landscape.export`` chooses for the bake with no
  resolution given: ``closest_layout(max(width, height))``. A layer whose
  layout differs from the heightmap's is refused at import
  (``terrain.landscape_layout``, landscape.py).
* Landscape texel ``(i, j)`` samples the bake grid at ``(rows[i], cols[j])``
  with ``rows = linspace(0, height - 1, R)`` and ``cols = linspace(0,
  width - 1, R)`` -- the SAME positions ``landscape.resample_to`` uses for
  the elevations, so the class under a Landscape vertex is the class
  under its height. The fractions are interpolated bilinearly (a fraction
  is a quantity and blends; a class code would not) and the 12 fractions
  at a texel are rounded by the largest remainder to sum to exactly 255,
  as the bake-grid maps are.
* Verified, not assumed: (1) the sum over every layer is 255 at every
  texel; (2) at every texel whose sample position lands exactly on a bake
  cell (the four corners always; every position where the linspace hits
  an integer) the layer value equals the bake-grid weight to the count;
  (3) the ARGMAX ROUND TRIP: the largest layer at each texel, mapped back
  to the nearest bake cell, is compared with the bake's majority class
  map (``class_map.png``) over the whole grid and the agreement is
  reported (blending across a class boundary can move the argmax at the
  boundary texels; the fraction says how many).

The files
---------
One raw ``uint8`` file per class, ``<key>_landcover_<code>.u8`` (row-major,
R x R, row 0 north, the same axis order as the ``.r16`` heightmap; a
uint8 has no byte order), plus ``<key>_landcover_0.u8`` for nodata so the
sum stays 255 where the source had no data. One file per class rather
than one interleaved file so an importer can hand each layer to the
Landscape by name without a stride convention; the reader is
:func:`read_layers`. The sidecar ``<key>_landcover_layers.json`` carries
the attribution line (CC BY 4.0), the class list with the taxonomy word
of each, the layout, and the sha256 of every layer file.

The taxonomy
------------
:data:`CLASS_OF_COVER` maps a legend code to the scene taxonomy the
labels use: {10, 20, 95} vegetation, 50 building, {80, 90} water, every
other legend code terrain. A code outside the legend refuses
``landcover.legend`` by name: an unknown class is never guessed into a
taxonomy word.

Not claimed: nothing engine-side reads these layers (the Landscape layer
import in the editor is W5, a Windows step); the layers are painted
weights, not vegetation or buildings; the argmax agreement is a
statement about resampling, not about WorldCover's accuracy (76.7 % per
its manual); a fraction interpolated between two bake cells is not a
measurement at the texel; nodata is a layer so the sum is exact, not a
class.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .glo30 import sha256_of
from .landcover import (
    ATTRIBUTION, CITATION, DATASET, LEGEND, LEGEND_CODES, LICENSE, LICENSE_URL,
    NODATA, NODATA_KEY, WEIGHT_KEYS, LandcoverError,
)
from .landscape import LandscapeLayout, closest_layout

#: The scene taxonomy words a legend class maps to (the labels' classes).
TAXONOMY: Tuple[str, ...] = ("vegetation", "building", "water", "terrain")

#: Legend code -> taxonomy word. Stated in the blueprint (section 4,
#: "Models and parameters"): tree cover, shrubland and mangroves are
#: vegetation; built-up is building; permanent water and herbaceous
#: wetland are water; grassland, cropland, bare/sparse, snow/ice and
#: moss/lichen are terrain.
CLASS_OF_COVER: Dict[int, str] = {
    10: "vegetation", 20: "vegetation", 95: "vegetation",
    50: "building",
    80: "water", 90: "water",
    30: "terrain", 40: "terrain", 60: "terrain", 70: "terrain", 100: "terrain",
}

#: The nodata layer's word: not a class, kept so the sum is exact.
NODATA_CLASS = "nodata"

LAYERS_VERSION = 1
LAYER_SUFFIX = ".u8"


class LandcoverLegendError(Exception):
    """A land cover code outside the WorldCover legend has no taxonomy
    word; refused by name (``landcover.legend``) rather than guessed."""

    constraint = "landcover.legend"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"landcover.legend: {message}")


def cover_class(code: int) -> str:
    """The taxonomy word of a legend code; ``landcover.legend`` for a
    code the legend does not carry."""
    code = int(code)
    if code not in LEGEND_CODES:
        raise LandcoverLegendError(
            f"code {code} is not in the WorldCover legend {list(LEGEND_CODES)}; "
            f"no taxonomy class is assigned to a code the legend does not carry")
    return CLASS_OF_COVER[code]


@dataclass(frozen=True)
class WeightLayer:
    """One class layer at the Landscape's resolution, as the sidecar
    records it."""

    code: int
    key: str
    cover_class: str
    file: str
    sha256: str
    layout: LandscapeLayout
    resolution: int

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "key": self.key, "class": self.cover_class,
                "file": self.file, "sha256": self.sha256,
                "layout": {"quads_per_section": self.layout.quads_per_section,
                           "sections_per_component": self.layout.sections_per_component,
                           "components": self.layout.components},
                "resolution": self.resolution}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeightLayer":
        layout = data["layout"]
        return cls(code=int(data["code"]), key=str(data["key"]),
                   cover_class=str(data["class"]), file=str(data["file"]),
                   sha256=str(data["sha256"]),
                   layout=LandscapeLayout(int(layout["quads_per_section"]),
                                          int(layout["sections_per_component"]),
                                          int(layout["components"])),
                   resolution=int(data["resolution"]))


# -- the bake-grid maps -------------------------------------------------------


def read_bake_weights(scene_dir) -> Tuple[Dict[str, Any], np.ndarray, np.ndarray]:
    """The bake-grid maps back out of ``<key>_landcover/``: the
    ``landcover.json`` document, the weight stack (12, H, W) uint8 in
    ``WEIGHT_KEYS`` order and the majority class map (H, W). Every PNG's
    sha256 is checked against the document's; a map that no longer
    matches refuses ``terrain.landcover`` (a layer built on a stale map
    would carry the wrong provenance)."""
    from PIL import Image

    scene_dir = Path(scene_dir)
    path = scene_dir / "landcover.json"
    if not path.is_file():
        raise LandcoverError(f"no landcover.json in {scene_dir}", reason="unreachable")
    document = json.loads(path.read_text(encoding="utf-8"))
    maps = []
    for key in WEIGHT_KEYS:
        entry = (document.get("weightmaps") or {}).get(key)
        if not entry:
            raise LandcoverError(f"{path} names no weightmap for {key!r}")
        file = scene_dir / entry["file"]
        if not file.is_file():
            raise LandcoverError(f"{file} is absent", reason="unreachable")
        if sha256_of(file) != entry["sha256"]:
            raise LandcoverError(
                f"{file} does not match the sha256 landcover.json recorded for it; "
                f"refusing to build layers on a map whose provenance no longer holds")
        maps.append(np.asarray(Image.open(file), dtype=np.uint8))
    stack = np.stack(maps)
    class_entry = document.get("class_map") or {}
    class_path = scene_dir / class_entry.get("file", "class_map.png")
    if not class_path.is_file() or sha256_of(class_path) != class_entry.get("sha256"):
        raise LandcoverError(f"{class_path} is absent or does not match its recorded sha256")
    majority = np.asarray(Image.open(class_path), dtype=np.uint8)
    if majority.shape != stack.shape[1:]:
        raise LandcoverError(f"class map {majority.shape} and weightmaps {stack.shape[1:]} disagree")
    return document, stack, majority


# -- resampling to the Landscape ------------------------------------------------


def sample_positions(height: int, width: int, resolution: int) -> Tuple[np.ndarray, np.ndarray]:
    """The bake-grid positions the Landscape texels sample: the linspace
    ``landscape.resample_to`` uses for the elevations, per axis."""
    rows = np.linspace(0, height - 1, resolution)
    cols = np.linspace(0, width - 1, resolution)
    return rows, cols


def resample_fractions(stack: np.ndarray, resolution: int) -> np.ndarray:
    """Bilinear resampling of the (n, H, W) weight stack to (n, R, R) on
    the heightmap's sample positions. Linear in the weights, so the sum
    over the layers is preserved at every texel (255 in, 255 out, before
    rounding)."""
    n, h, w = stack.shape
    rows, cols = sample_positions(h, w, resolution)
    r0 = np.floor(rows).astype(int)
    r1 = np.minimum(r0 + 1, h - 1)
    c0 = np.floor(cols).astype(int)
    c1 = np.minimum(c0 + 1, w - 1)
    fr = (rows - r0)[None, :, None]
    fc = (cols - c0)[None, None, :]
    z = stack.astype(np.float64)
    top = z[:, r0][:, :, c0] * (1 - fc) + z[:, r0][:, :, c1] * fc
    bottom = z[:, r1][:, :, c0] * (1 - fc) + z[:, r1][:, :, c1] * fc
    return top * (1 - fr) + bottom * fr


def quantise_to_255(fractions: np.ndarray) -> np.ndarray:
    """(n, R, R) non-negative reals summing to 255 at every texel ->
    uint8 by the largest remainder, so the integer sum is exactly 255
    everywhere (plain rounding of twelve terms misses by several)."""
    total = fractions.sum(axis=0)
    if not np.allclose(total, 255.0, atol=1e-6):
        raise ValueError(f"fractions do not sum to 255 at every texel "
                         f"(min {total.min():.6f}, max {total.max():.6f})")
    base = np.floor(fractions + 1e-9)
    remainder = np.rint(255.0 - base.sum(axis=0)).astype(np.int64)
    frac = fractions - base
    order = np.argsort(-frac, axis=0, kind="stable")
    rank = np.argsort(order, axis=0, kind="stable")
    extra = (rank < remainder[None, :, :]).astype(np.float64)
    return (base + extra).astype(np.uint8)


def argmax_codes(layers: np.ndarray) -> np.ndarray:
    """The legend code with the largest weight per texel, ties by legend
    order (the bake's majority rule); nodata (0) only where every legend
    layer is zero."""
    legend = layers[:len(LEGEND)]
    best = np.argmax(legend, axis=0)
    codes = np.array([c.code for c in LEGEND], dtype=np.uint8)
    out = codes[best]
    out[legend.max(axis=0) == 0] = NODATA
    return out


def argmax_round_trip(layers: np.ndarray, majority: np.ndarray) -> Dict[str, Any]:
    """The argmax of the Landscape layers, mapped back to the NEAREST
    bake cell, against the bake's majority class map, over every texel.
    Per class: the agreement over the texels whose bake class is that
    class, so a rare class's disagreement is not hidden by a common one."""
    h, w = majority.shape
    resolution = layers.shape[1]
    rows, cols = sample_positions(h, w, resolution)
    ri = np.rint(rows).astype(int)
    ci = np.rint(cols).astype(int)
    expected = majority[ri][:, ci]
    got = argmax_codes(layers)
    agree = got == expected
    per_class = {}
    for entry in LEGEND:
        mask = expected == entry.code
        count = int(mask.sum())
        if count:
            per_class[entry.key] = {"texels": count,
                                    "agreement": float(agree[mask].sum()) / count}
    return {"texels": int(agree.size), "agreement": float(agree.mean()),
            "per_class": per_class,
            "rule": "argmax over the legend layers at each Landscape texel, ties by legend "
                    "order, against class_map.png at the nearest bake cell"}


def alignment_check(layers: np.ndarray, stack: np.ndarray) -> Dict[str, Any]:
    """Every texel whose sample position lands exactly on a bake cell
    (the corners always) must carry the bake cell's weights to the
    count: the interpolation is the identity there, and the rounding
    of an integer is the integer."""
    n, h, w = stack.shape
    resolution = layers.shape[1]
    rows, cols = sample_positions(h, w, resolution)
    exact_r = np.flatnonzero(np.abs(rows - np.rint(rows)) < 1e-9)
    exact_c = np.flatnonzero(np.abs(cols - np.rint(cols)) < 1e-9)
    ri = np.rint(rows[exact_r]).astype(int)
    ci = np.rint(cols[exact_c]).astype(int)
    got = layers[:, exact_r][:, :, exact_c].astype(np.int64)
    want = stack[:, ri][:, :, ci].astype(np.int64)
    diff = np.abs(got - want)
    return {"exact_texels": int(len(exact_r) * len(exact_c)),
            "max_count_difference": int(diff.max()) if diff.size else 0,
            "ok": bool(diff.size and diff.max() == 0),
            "rule": "texels whose linspace position is an integer bake cell carry that "
                    "cell's weights exactly (the four corners always)"}


# -- export and read -----------------------------------------------------------


def bake_key(document: Dict[str, Any], scene_dir) -> str:
    """The bake's file stem, the name every layer file carries: the
    sidecar landcover.json aligned to (its stem), else the scene dir's
    name without ``_landcover`` (scene_dir_for's rule)."""
    aligned = (document.get("grid") or {}).get("aligned_to_bake")
    if aligned:
        return Path(str(aligned)).stem
    name = Path(scene_dir).name
    return name[:-len("_landcover")] if name.endswith("_landcover") else name


def layer_name(key: str, code: int) -> str:
    return f"{key}_landcover_{int(code)}{LAYER_SUFFIX}"


def sidecar_name(key: str) -> str:
    return f"{key}_landcover_layers.json"


def export_layers(scene_dir, out_dir=None, resolution: Optional[int] = None
                  ) -> Tuple[Path, Dict[str, Any]]:
    """From ``<key>_landcover/`` (the bake-grid maps), the Landscape-
    resolution layers and their sidecar, written to ``out_dir`` (default:
    the scene dir itself). Returns the sidecar path and its document.

    The layout is ``closest_layout(resolution or max(width, height))``,
    the rule ``landscape.export`` applies to the bake, so the layers and
    the heightmap agree by construction; the sidecar then carries the
    three verifications (sum, exact texels, argmax round trip) measured
    on what was written. Refuses ``terrain.landcover`` when a bake-grid
    map is absent or stale, ``landcover.legend`` when the document
    carries a class code outside the legend.
    """
    scene_dir = Path(scene_dir)
    out_dir = Path(out_dir) if out_dir is not None else scene_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    document, stack, majority = read_bake_weights(scene_dir)
    key = bake_key(document, scene_dir)
    n, height, width = stack.shape
    layout = closest_layout(resolution or max(width, height))
    r = layout.resolution

    codes = {c.key: c.code for c in LEGEND}
    for entry in document.get("classes", ()):
        cover_class(int(entry["code"]))            # a foreign code refuses by name
    fractions = resample_fractions(stack, r)
    layers = quantise_to_255(fractions)
    sums = layers.astype(np.int64).sum(axis=0)
    alignment = alignment_check(layers, stack)
    round_trip = argmax_round_trip(layers, majority)

    written = []
    for index, weight_key in enumerate(WEIGHT_KEYS):
        code = NODATA if weight_key == NODATA_KEY else codes[weight_key]
        word = NODATA_CLASS if weight_key == NODATA_KEY else cover_class(code)
        path = out_dir / layer_name(key, code)
        layers[index].tofile(path)
        written.append(WeightLayer(code=code, key=weight_key, cover_class=word,
                                   file=path.name, sha256=sha256_of(path),
                                   layout=layout, resolution=r))
    titles = {c.key: c.title for c in LEGEND}
    fractions_doc = document.get("fractions") or {}
    sidecar = {
        "layers_version": LAYERS_VERSION,
        "dataset": DATASET,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "citation": CITATION,
        "key": key,
        "source": {"landcover_json": "landcover.json",
                   "landcover_json_sha256": sha256_of(scene_dir / "landcover.json"),
                   "worldcover_sha256": document.get("sha256"),
                   "bake_sha256": document.get("grid", {}).get("bake_sha256"),
                   "bake_grid": {k: document["grid"][k] for k in ("width", "height", "cell_size_m", "crs")
                                 if k in document.get("grid", {})}},
        "layout": {"quads_per_section": layout.quads_per_section,
                   "sections_per_component": layout.sections_per_component,
                   "components": layout.components, "resolution": r,
                   "rule": "closest_layout(max(width, height)) -- the heightmap's own"},
        "resampling": ("bilinear over the bake-grid fractions at the heightmap's sample "
                       "positions (rows = linspace(0, H-1, R), cols = linspace(0, W-1, R)); "
                       "largest-remainder rounded to sum to 255 per texel"),
        "encoding": ("one raw uint8 file per class, R x R row-major, row 0 north (the .r16 "
                     "heightmap's axis order); value = 255 x the class fraction at the texel; "
                     "the layers sum to 255 at every texel with the nodata layer"),
        "taxonomy": {str(code): word for code, word in sorted(CLASS_OF_COVER.items())},
        "classes": [{"code": layer.code, "key": layer.key,
                     "title": titles.get(layer.key, "no data"),
                     "class": layer.cover_class,
                     "fraction": float(fractions_doc.get(layer.key, document.get("nodata_fraction", 0.0)))}
                    for layer in written],
        "layers": [layer.to_dict() for layer in written],
        "sum_per_texel": {"min": int(sums.min()), "max": int(sums.max()), "expected": 255},
        "alignment": alignment,
        "argmax_round_trip": round_trip,
        "not_claimed": [
            "nothing engine-side reads these layers: the Landscape layer import in the "
            "editor is W5 (a Windows step); no vegetation or building is placed",
            "a fraction interpolated between two bake cells is not a measurement at the "
            "texel; the argmax agreement measures the resampling, not WorldCover's accuracy",
            "nodata is a layer so the sum is exact, not a class",
        ],
    }
    path = out_dir / sidecar_name(key)
    path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return path, sidecar


def read_layers(sidecar_path) -> Tuple[Dict[str, Any], Dict[int, np.ndarray]]:
    """The layers back out of their sidecar: {code: (R, R) uint8}, every
    file's sha256 checked against the sidecar's (a mismatch refuses
    ``terrain.landcover``: a layer is trusted only with its provenance)."""
    sidecar_path = Path(sidecar_path)
    document = json.loads(sidecar_path.read_text(encoding="utf-8"))
    out: Dict[int, np.ndarray] = {}
    for entry in document["layers"]:
        layer = WeightLayer.from_dict(entry)
        path = sidecar_path.parent / layer.file
        if not path.is_file():
            raise LandcoverError(f"layer {path} is absent", reason="unreachable")
        if sha256_of(path) != layer.sha256:
            raise LandcoverError(f"layer {path} does not match the sha256 its sidecar records")
        data = np.fromfile(path, dtype=np.uint8)
        if data.size != layer.resolution * layer.resolution:
            raise LandcoverError(
                f"layer {path} holds {data.size} bytes, not {layer.resolution}^2")
        out[layer.code] = data.reshape(layer.resolution, layer.resolution)
    return document, out


def layers_from_sidecar(document: Dict[str, Any]) -> Tuple[WeightLayer, ...]:
    return tuple(WeightLayer.from_dict(entry) for entry in document["layers"])
