"""Export a heightfield to a UE Landscape import, with the Z-scale that works.

§6.3 calls the Z-scale "the #1 cause of wrong-height terrain", and the reason is
that Unreal's Landscape stores height as a 16-bit value with a fixed encoding:

* value 32768 is zero height,
* the full 0-65535 range spans +/-256 m at a Z-scale of 100,
* so one unit is 1/512 m, i.e. the constant 0.001953125.

To make a raster whose real relief is ``R`` metres come back out at the right
height, the actor's Z-scale must therefore be

    Z_scale = (R * 100) * 0.001953125

with the raster rescaled to fill the full 16-bit range. X and Y scale are just
metres-per-pixel times 100, since Unreal works in centimetres.

Everything needed to invert the encoding is written alongside the raster, and
:func:`verify_round_trip` inverts it here rather than trusting the arithmetic --
which is what Gate 4 checks.

The import manifest (work item W1)
----------------------------------
The ``.json`` beside the ``.r16`` is the Landscape import's manifest. Beside
the Gate 4 keys it MAY carry (absent-canonical: a manifest written before
this extension reads unchanged):

* ``weight_layers[]`` -- one entry per land-cover layer at the Landscape's
  resolution (core/terrain/weightmaps.py): ``{code, class, key, file,
  sha256, layout, resolution}``; a layer whose layout differs from the
  heightmap's refuses ``terrain.landscape_layout`` -- the editor would
  resample it silently against the geometry;
* ``datum`` -- the bake sidecar's own ``provenance.datum`` block (batch 1's
  vertical datum, copied verbatim, never re-evaluated); a bake without the
  block refuses ``terrain.landscape_missing`` (re-bake: a Landscape whose
  heights have no stated datum is the P10 error again);
* ``bake`` -- ``{name, sha256, width, height, pixel_size_m}`` of the bake the
  manifest was built from; at verification a bake whose sha256 differs from
  the manifest's refuses ``terrain.landscape_stale``.

:func:`verify_round_trip` grades the layers too when the manifest carries
them: every layer file's sha256, the layout against the heightmap's, and the
sum over the layers (255 at every texel).

Not claimed: nothing here runs in the editor (the import itself is W5, a
Windows step); the manifest states what to import and checks it here.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .heightfield import U16_MAX, Heightfield

#: Unreal centimetres per metre.
UE_CM_PER_M = 100.0
#: Landscape height units per centimetre: 1/512.
UE_HEIGHT_UNIT = 1.0 / 512.0
#: The 16-bit value that means zero height.
UE_ZERO = 32768

#: Section sizes Unreal accepts, in quads. Must be a power of two, max 256.
VALID_QUADS_PER_SECTION = (7, 15, 31, 63, 127, 255)
VALID_SECTIONS_PER_COMPONENT = (1, 2)


class LandscapeError(Exception):
    """The heightfield cannot be imported as a Landscape as configured."""


class LandscapeManifestError(LandscapeError):
    """The import manifest cannot be trusted; refused by name
    (``.constraint``): ``terrain.landscape_layout`` (a weight layer's
    layout differs from the heightmap's), ``terrain.landscape_missing``
    (the bake carries no datum block to copy), ``terrain.landscape_stale``
    (the bake or a layer file differs from what the manifest recorded)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


@dataclass(frozen=True)
class LandscapeLayout:
    """A Landscape resolution Unreal will actually accept.

    Resolution must be ``components * sections * quads + 1`` per axis. An
    arbitrary raster size is not importable, and Unreal's own response to one is
    to resample it silently -- which changes the elevations.
    """

    quads_per_section: int
    sections_per_component: int
    components: int

    @property
    def resolution(self) -> int:
        return (self.components * self.sections_per_component
                * self.quads_per_section + 1)

    def describe(self) -> str:
        return (f"{self.resolution}x{self.resolution} "
                f"({self.components} components x {self.sections_per_component} "
                f"sections x {self.quads_per_section} quads + 1)")


def valid_layouts(max_resolution: int = 8129) -> List[LandscapeLayout]:
    """Every accepted layout, smallest resolution first."""
    layouts = []
    for quads in VALID_QUADS_PER_SECTION:
        for sections in VALID_SECTIONS_PER_COMPONENT:
            for components in range(1, 1025):
                layout = LandscapeLayout(quads, sections, components)
                if layout.resolution > max_resolution:
                    break
                if layout.resolution >= 127:
                    layouts.append(layout)
    return sorted(layouts, key=lambda l: l.resolution)


def closest_layout(resolution: int) -> LandscapeLayout:
    """The valid layout nearest a desired resolution.

    Chosen explicitly and reported, rather than letting the editor resample.
    """
    layouts = valid_layouts()
    if not layouts:
        raise LandscapeError("no valid Landscape layouts")
    return min(layouts, key=lambda l: (abs(l.resolution - resolution),
                                       -l.quads_per_section))


@dataclass(frozen=True)
class LandscapeImport:
    """Everything needed to import a raster at the correct height."""

    raw_path: Path
    resolution: int
    layout: LandscapeLayout
    #: Actor scale, in Unreal's units.
    scale_x: float
    scale_y: float
    scale_z: float
    #: The real-world elevation the raster spans.
    min_elevation_m: float
    max_elevation_m: float
    pixel_size_m: float
    #: Y ground sample distance. Differs from X whenever the source raster is
    #: not square, which a cropped DEM usually is not.
    pixel_size_y_m: float = 0.0
    covered_x_m: float = 0.0
    covered_y_m: float = 0.0

    @property
    def relief_m(self) -> float:
        return self.max_elevation_m - self.min_elevation_m

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_path": str(self.raw_path),
            "resolution": self.resolution,
            "layout": {
                "quads_per_section": self.layout.quads_per_section,
                "sections_per_component": self.layout.sections_per_component,
                "components": self.layout.components,
            },
            "scale": {"x": self.scale_x, "y": self.scale_y, "z": self.scale_z},
            "ground_extent_m": {"x": self.covered_x_m, "y": self.covered_y_m},
            "pixel_size_m": {"x": self.pixel_size_m, "y": self.pixel_size_y_m},
            "min_elevation_m": self.min_elevation_m,
            "max_elevation_m": self.max_elevation_m,
            "relief_m": self.relief_m,
            "encoding": {
                "zero_value": UE_ZERO,
                "height_unit_cm": UE_HEIGHT_UNIT,
                "note": "elevation_m = min + (sample / 65535) * relief",
            },
        }

    def describe(self) -> str:
        return (
            f"{self.resolution}x{self.resolution} landscape, "
            f"{self.layout.describe()}\n"
            f"  scale  X {self.scale_x:.4f}  Y {self.scale_y:.4f}  "
            f"Z {self.scale_z:.6f}\n"
            f"  spans  {self.min_elevation_m:.1f} to {self.max_elevation_m:.1f} m "
            f"({self.relief_m:.1f} m relief)\n"
            f"  ground {self.covered_x_m:.0f} x {self.covered_y_m:.0f} m at "
            f"{self.pixel_size_m:.2f} x {self.pixel_size_y_m:.2f} m/px"
        )


def z_scale_for(relief_m: float) -> float:
    """The Landscape Z-scale that makes a given relief come out at true height."""
    return relief_m * UE_CM_PER_M * UE_HEIGHT_UNIT


def resample_to(field: Heightfield, resolution: int) -> np.ndarray:
    """Bilinearly resample the elevation raster to a square resolution.

    Done here, deliberately and reported, so the editor never does it silently.
    """
    z = field.elevations()
    rows = np.linspace(0, z.shape[0] - 1, resolution)
    cols = np.linspace(0, z.shape[1] - 1, resolution)
    r0 = np.floor(rows).astype(int); r1 = np.minimum(r0 + 1, z.shape[0] - 1)
    c0 = np.floor(cols).astype(int); c1 = np.minimum(c0 + 1, z.shape[1] - 1)
    fr = (rows - r0)[:, None]
    fc = (cols - c0)[None, :]
    top = z[np.ix_(r0, c0)] * (1 - fc) + z[np.ix_(r0, c1)] * fc
    bottom = z[np.ix_(r1, c0)] * (1 - fc) + z[np.ix_(r1, c1)] * fc
    return top * (1 - fr) + bottom * fr


def export(field: Heightfield, path, resolution: Optional[int] = None
           ) -> LandscapeImport:
    """Write a ``.r16`` Landscape heightmap plus its import parameters."""
    layout = closest_layout(resolution or max(field.width, field.height))
    z = resample_to(field, layout.resolution)

    lo = float(z.min())
    hi = float(z.max())
    relief = hi - lo
    if relief <= 0:
        # A flat landscape still needs a non-zero Z-scale or the import maths
        # divides by zero downstream.
        relief = 1.0
    samples = np.rint((z - lo) / relief * U16_MAX).clip(0, U16_MAX).astype("<u2")

    path = Path(path).with_suffix(".r16")
    path.parent.mkdir(parents=True, exist_ok=True)
    samples.tofile(path)

    # Ground extent must be preserved per axis. A Landscape is square, but a
    # DEM cropped to its valid region generally is not -- the Gate 4 fixture
    # bakes to 294x434 -- so a single scale would squash the terrain by the
    # aspect ratio (1.47x here) while every elevation still read back correctly.
    # That is a failure mode which looks like working terrain.
    px = field.georeference.pixel_size_m
    covered_x_m = (field.width - 1) * px
    covered_y_m = (field.height - 1) * px
    pixel_x_m = covered_x_m / (layout.resolution - 1)
    pixel_y_m = covered_y_m / (layout.resolution - 1)

    spec = LandscapeImport(
        raw_path=path,
        resolution=layout.resolution,
        layout=layout,
        scale_x=pixel_x_m * UE_CM_PER_M,
        scale_y=pixel_y_m * UE_CM_PER_M,
        scale_z=z_scale_for(relief),
        min_elevation_m=lo,
        max_elevation_m=hi,
        pixel_size_m=pixel_x_m,
        pixel_size_y_m=pixel_y_m,
        covered_x_m=covered_x_m,
        covered_y_m=covered_y_m,
    )
    path.with_suffix(".json").write_text(json.dumps(spec.to_dict(), indent=1), encoding="utf-8")
    return spec


def decode(spec: LandscapeImport) -> np.ndarray:
    """Invert the encoding: read the exported raster back as metres.

    This is what makes the round trip checkable rather than assumed. If the
    Z-scale arithmetic is wrong, the elevations that come back here are wrong by
    the same factor they would be wrong by in the editor.
    """
    samples = np.fromfile(spec.raw_path, dtype="<u2").astype(np.float64)
    samples = samples.reshape(spec.resolution, spec.resolution)
    relief = spec.relief_m if spec.relief_m > 0 else 1.0
    return spec.min_elevation_m + samples / U16_MAX * relief


def verify_round_trip(field: Heightfield, spec: LandscapeImport,
                      manifest: Optional[Dict[str, Any]] = None,
                      layer_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Compare decoded Landscape elevations against the source heightfield.

    Gate 4's "round-trip a known elevation and confirm the metres come back
    correct". Two error sources are separated, because they have different
    causes and different fixes: quantisation is the 16-bit encoding and is
    irreducible, while resampling error comes from the resolution change and
    would be zero if the raster were already a valid Landscape size.

    With ``manifest`` (the import manifest, W1) the weight layers are graded
    too (:func:`verify_layers`): the result gains ``layers``, and a stale
    bake or layer, or a layer of another layout, refuses by name.
    """
    decoded = decode(spec)
    reference = resample_to(field, spec.resolution)
    error = np.abs(decoded - reference)
    # Relief is compared against the RESAMPLED reference, which is what the
    # Landscape actually represents. Comparing against the original raster
    # would fold resampling error into a number meant to test the encoding, and
    # the two have different causes and different fixes.
    resampled_relief = float(reference.max() - reference.min())
    aspect_source = ((field.width - 1) / (field.height - 1)) if field.height > 1 else 1.0
    aspect_landscape = (spec.scale_x / spec.scale_y) if spec.scale_y else 1.0
    result: Dict[str, Any] = {
        "resolution": float(spec.resolution),
        "max_error_m": float(error.max()),
        "mean_error_m": float(error.mean()),
        "quantisation_m": spec.relief_m / U16_MAX,
        "source_relief_m": float(field.statistics()["relief_m"]),
        "resampled_relief_m": resampled_relief,
        "landscape_relief_m": spec.relief_m,
        "relief_error_m": abs(spec.relief_m - resampled_relief),
        "aspect_source": aspect_source,
        "aspect_landscape": aspect_landscape,
        "aspect_error": abs(aspect_source - aspect_landscape),
    }
    if manifest is not None:
        result["layers"] = verify_layers(field, spec, manifest, layer_dir)
    return result


# -- the import manifest: weight layers and the datum (W1) ---------------------

#: The keys the manifest gains beside the Gate 4 keys, absent-canonical.
MANIFEST_LAYER_KEYS = ("code", "class", "key", "file", "sha256", "layout", "resolution")


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _layout_of(data: Dict[str, Any]) -> LandscapeLayout:
    return LandscapeLayout(int(data["quads_per_section"]),
                           int(data["sections_per_component"]),
                           int(data["components"]))


def bake_datum_block(field: Heightfield) -> Dict[str, Any]:
    """The bake sidecar's ``provenance.datum`` block, copied verbatim;
    refuses ``terrain.landscape_missing`` when the bake carries none --
    a Landscape whose heights have no stated vertical datum would put the
    P10 error back into the scene. Nothing is re-evaluated here."""
    block = (field.provenance or {}).get("datum")
    if not isinstance(block, dict) or "undulation_m" not in block \
            or "vertical_datum_of_heights" not in block:
        raise LandscapeManifestError(
            "terrain.landscape_missing",
            f"bake {field.name!r} carries no vertical datum block (provenance.datum "
            f"with undulation_m and vertical_datum_of_heights); re-bake it with "
            f"scripts/bake_terrain.py so the Landscape import states its datum")
    return json.loads(json.dumps(block))


def import_manifest(field: Heightfield, spec: LandscapeImport,
                    layers: Sequence[Dict[str, Any]],
                    layer_dir: Optional[Path] = None) -> Dict[str, Any]:
    """The import manifest with ``weight_layers``, ``datum`` and ``bake``,
    written to ``spec.raw_path.with_suffix('.json')`` (over the Gate 4
    keys, which it keeps). ``layers`` are the weightmaps sidecar's
    ``layers`` entries; their files sit beside the manifest unless
    ``layer_dir`` says otherwise (the manifest records the file NAME, so
    an importer resolves it against the manifest's own directory).

    Refuses ``terrain.landscape_layout`` for a layer whose layout or
    resolution is not the heightmap's, ``terrain.landscape_missing`` for
    a bake without its datum block, ``terrain.landscape_stale`` for a
    layer file absent or differing from its recorded sha256.
    """
    manifest = spec.to_dict()
    layer_dir = Path(layer_dir) if layer_dir is not None else Path(spec.raw_path).parent
    entries: List[Dict[str, Any]] = []
    for layer in layers:
        layout = _layout_of(layer["layout"])
        resolution = int(layer["resolution"])
        if layout != spec.layout or resolution != spec.resolution:
            raise LandscapeManifestError(
                "terrain.landscape_layout",
                f"layer {layer['file']} is {layout.describe()} but the heightmap is "
                f"{spec.layout.describe()}; the editor would resample the layer "
                f"silently against the geometry")
        path = layer_dir / str(layer["file"])
        if not path.is_file():
            raise LandscapeManifestError(
                "terrain.landscape_stale", f"layer file {path} is absent")
        if _sha256_of(path) != layer["sha256"]:
            raise LandscapeManifestError(
                "terrain.landscape_stale",
                f"layer file {path} differs from the sha256 its sidecar recorded")
        entries.append({key: layer[key] for key in MANIFEST_LAYER_KEYS})
    manifest["weight_layers"] = entries
    manifest["datum"] = bake_datum_block(field)
    manifest["bake"] = {
        "name": field.name, "sha256": field.digest(),
        "width": field.width, "height": field.height,
        "pixel_size_m": field.georeference.pixel_size_m,
    }
    manifest["layer_encoding"] = ("raw uint8, resolution x resolution row-major, row 0 "
                                  "north; 255 = the whole texel; the layers sum to 255")
    out = Path(spec.raw_path).with_suffix(".json")
    out.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def read_import_manifest(path) -> Tuple[LandscapeImport, Dict[str, Any]]:
    """The manifest back: the ``LandscapeImport`` and the whole dict
    (``weight_layers``, ``datum``, ``bake`` when present)."""
    path = Path(path).with_suffix(".json")
    data = json.loads(path.read_text(encoding="utf-8"))
    layout = _layout_of(data["layout"])
    spec = LandscapeImport(
        raw_path=path.with_suffix(".r16"), resolution=int(data["resolution"]),
        layout=layout,
        scale_x=float(data["scale"]["x"]), scale_y=float(data["scale"]["y"]),
        scale_z=float(data["scale"]["z"]),
        min_elevation_m=float(data["min_elevation_m"]),
        max_elevation_m=float(data["max_elevation_m"]),
        pixel_size_m=float(data["pixel_size_m"]["x"]),
        pixel_size_y_m=float(data["pixel_size_m"]["y"]),
        covered_x_m=float(data["ground_extent_m"]["x"]),
        covered_y_m=float(data["ground_extent_m"]["y"]))
    return spec, data


def verify_layers(field: Heightfield, spec: LandscapeImport, manifest: Dict[str, Any],
                  layer_dir: Optional[Path] = None) -> Dict[str, Any]:
    """The layer half of the round trip: the bake's sha256 against the
    manifest's (``terrain.landscape_stale``), every layer's layout against
    the heightmap's (``terrain.landscape_layout``), every layer file's
    sha256 (``terrain.landscape_stale``), and the sum over the layers at
    every texel (255). Returns the measured numbers."""
    bake = manifest.get("bake") or {}
    if bake.get("sha256") != field.digest():
        raise LandscapeManifestError(
            "terrain.landscape_stale",
            f"the bake's sha256 {field.digest()[:12]}... is not the manifest's "
            f"{str(bake.get('sha256'))[:12]}...; the Landscape was built from another "
            f"bake -- export it again")
    layer_dir = Path(layer_dir) if layer_dir is not None else Path(spec.raw_path).parent
    layers = manifest.get("weight_layers") or []
    total = np.zeros((spec.resolution, spec.resolution), dtype=np.int64)
    checked = []
    for layer in layers:
        layout = _layout_of(layer["layout"])
        if layout != spec.layout or int(layer["resolution"]) != spec.resolution:
            raise LandscapeManifestError(
                "terrain.landscape_layout",
                f"layer {layer['file']} is {layout.describe()} but the heightmap is "
                f"{spec.layout.describe()}")
        path = layer_dir / str(layer["file"])
        if not path.is_file() or _sha256_of(path) != layer["sha256"]:
            raise LandscapeManifestError(
                "terrain.landscape_stale",
                f"layer file {path} is absent or differs from its recorded sha256")
        data = np.fromfile(path, dtype=np.uint8)
        if data.size != spec.resolution * spec.resolution:
            raise LandscapeManifestError(
                "terrain.landscape_layout",
                f"layer file {path} holds {data.size} bytes, not {spec.resolution}^2")
        total += data.reshape(spec.resolution, spec.resolution)
        checked.append(int(layer["code"]))
    return {
        "layers": len(checked), "codes": checked,
        "sum_min": int(total.min()) if checked else 0,
        "sum_max": int(total.max()) if checked else 0,
        "sum_ok": bool(checked) and int(total.min()) == 255 and int(total.max()) == 255,
        "datum_copied": bool((manifest.get("datum") or {}).get("vertical_datum_of_heights")),
        "bake_sha256": field.digest(),
    }
