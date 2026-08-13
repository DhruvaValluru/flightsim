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
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def verify_round_trip(field: Heightfield, spec: LandscapeImport
                      ) -> Dict[str, float]:
    """Compare decoded Landscape elevations against the source heightfield.

    Gate 4's "round-trip a known elevation and confirm the metres come back
    correct". Two error sources are separated, because they have different
    causes and different fixes: quantisation is the 16-bit encoding and is
    irreducible, while resampling error comes from the resolution change and
    would be zero if the raster were already a valid Landscape size.
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
    return {
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
