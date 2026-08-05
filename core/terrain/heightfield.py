"""The baked heightfield: one raster format, one query, either kind of terrain.

§3.2 is the decision this module implements, and it is the most important
terrain decision in the project.

Cesium has no synchronous terrain-height query. ``SampleHeightMostDetailed`` is
asynchronous and its answer depends on which LOD happens to be streamed in at
that instant. A flight-dynamics ground callback needs a deterministic,
LOD-independent answer on every physics tick, so the visual terrain and the
ground truth are deliberately different objects:

* Cesium provides the visual terrain and the georeferencing.
* The FDM queries **this** -- a baked raster, by direct array lookup with
  bilinear interpolation.

The second half of §3.2 matters just as much. Procedural terrain is generated
into this same format, with the same georeferencing conventions and the same
16-bit scale/offset metadata as a real DEM, rather than into a separate in-engine
code path. The consequence is the property the research design needs: the ground
callback cannot tell whether it is querying a real mountain or a synthesised
one, so terrain statistics become a controllable independent variable measured
in the same units either way.

Storage
-------
16-bit unsigned samples plus a scale and offset, which is what §6.3's GDAL
pipeline produces and what a UE Landscape import wants. Raw ``.r16`` rather than
PNG, to avoid gamma and colour-space metadata surprises, with a JSON sidecar
carrying the georeferencing.

Quantisation is therefore real and is reported: a 16-bit raster spanning a
3000 m relief resolves about 4.6 cm. :attr:`quantisation_m` states it, and
Gate 4's round-trip tolerance is derived from it rather than guessed.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

#: Full-scale of the unsigned 16-bit sample space.
U16_MAX = 65535


@dataclass(frozen=True)
class Georeference:
    """Where a raster sits in the world, and how big its pixels are.

    A north-up affine transform, the same convention GDAL writes: ``origin`` is
    the *upper-left corner* of the upper-left pixel, and row index increases
    southward.
    """

    crs: str                   #: e.g. "EPSG:32633"
    origin_x_m: float
    origin_y_m: float
    pixel_size_m: float
    #: Set when the raster was produced from a projected DEM, so a query by
    #: longitude/latitude can be refused rather than answered wrongly.
    is_projected: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "crs": self.crs,
            "origin_x_m": self.origin_x_m,
            "origin_y_m": self.origin_y_m,
            "pixel_size_m": self.pixel_size_m,
            "is_projected": self.is_projected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Georeference":
        return cls(**data)


class Heightfield:
    """A baked elevation raster with a deterministic bilinear query.

    Parameters
    ----------
    samples:
        2-D uint16 array, row 0 northernmost.
    scale_m, offset_m:
        Elevation in metres is ``offset_m + sample * scale_m``.
    """

    MAGIC = "flightsim-heightfield"
    VERSION = 1

    def __init__(
        self,
        samples: np.ndarray,
        georeference: Georeference,
        scale_m: float,
        offset_m: float,
        name: str = "heightfield",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        if samples.ndim != 2:
            raise ValueError(f"heightfield must be 2-D, got shape {samples.shape}")
        if samples.dtype != np.uint16:
            raise ValueError(
                f"heightfield samples must be uint16 to match the DEM and "
                f"Landscape conventions, got {samples.dtype}"
            )
        if scale_m <= 0:
            raise ValueError("scale must be positive")
        self.samples = samples
        self.georeference = georeference
        self.scale_m = float(scale_m)
        self.offset_m = float(offset_m)
        self.name = name
        self.provenance = dict(provenance or {})

    # -- geometry -------------------------------------------------------

    @property
    def height(self) -> int:
        return self.samples.shape[0]

    @property
    def width(self) -> int:
        return self.samples.shape[1]

    @property
    def quantisation_m(self) -> float:
        """Smallest elevation difference this raster can represent."""
        return self.scale_m

    @property
    def extent_m(self) -> Tuple[float, float]:
        px = self.georeference.pixel_size_m
        return (self.width - 1) * px, (self.height - 1) * px

    def elevations(self) -> np.ndarray:
        """The whole raster in metres. Allocates; use for statistics, not queries."""
        return self.offset_m + self.samples.astype(np.float64) * self.scale_m

    def bounds_m(self) -> Tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) in the raster's own CRS."""
        g = self.georeference
        width_m, height_m = self.extent_m
        return (g.origin_x_m, g.origin_y_m - height_m,
                g.origin_x_m + width_m, g.origin_y_m)

    # -- the query ------------------------------------------------------

    def _pixel_coords(self, x_m: float, y_m: float) -> Tuple[float, float]:
        g = self.georeference
        col = (x_m - g.origin_x_m) / g.pixel_size_m
        row = (g.origin_y_m - y_m) / g.pixel_size_m     # row increases southward
        return col, row

    def elevation_at(self, x_m: float, y_m: float) -> float:
        """Elevation in metres at a projected coordinate, bilinearly interpolated.

        Queries outside the raster clamp to the edge rather than raising. A
        ground callback is called at every physics tick including during a trim
        excursion, and an exception there would abort a run for a reason that
        has nothing to do with the scenario. :meth:`contains` is available for
        callers that need to know.
        """
        col, row = self._pixel_coords(x_m, y_m)
        col = min(max(col, 0.0), self.width - 1.0)
        row = min(max(row, 0.0), self.height - 1.0)

        c0 = int(math.floor(col))
        r0 = int(math.floor(row))
        c1 = min(c0 + 1, self.width - 1)
        r1 = min(r0 + 1, self.height - 1)
        fc = col - c0
        fr = row - r0

        s = self.samples
        top = s[r0, c0] * (1.0 - fc) + s[r0, c1] * fc
        bottom = s[r1, c0] * (1.0 - fc) + s[r1, c1] * fc
        sample = top * (1.0 - fr) + bottom * fr
        return self.offset_m + sample * self.scale_m

    def contains(self, x_m: float, y_m: float) -> bool:
        col, row = self._pixel_coords(x_m, y_m)
        return 0.0 <= col <= self.width - 1 and 0.0 <= row <= self.height - 1

    def gradient_at(self, x_m: float, y_m: float,
                    span_m: Optional[float] = None) -> Tuple[float, float]:
        """Central-difference terrain gradient (d/dx, d/dy), dimensionless."""
        span = span_m if span_m is not None else self.georeference.pixel_size_m * 2.0
        half = span / 2.0
        dzdx = (self.elevation_at(x_m + half, y_m)
                - self.elevation_at(x_m - half, y_m)) / span
        dzdy = (self.elevation_at(x_m, y_m + half)
                - self.elevation_at(x_m, y_m - half)) / span
        return dzdx, dzdy

    def slope_deg_at(self, x_m: float, y_m: float) -> float:
        dzdx, dzdy = self.gradient_at(x_m, y_m)
        return math.degrees(math.atan(math.hypot(dzdx, dzdy)))

    # -- statistics, the experimental variables (§3.2) -------------------

    def slope_degrees(self) -> np.ndarray:
        """Per-pixel slope, for the distribution Gate 4 checks."""
        z = self.elevations()
        px = self.georeference.pixel_size_m
        dzdy, dzdx = np.gradient(z, px)
        return np.degrees(np.arctan(np.hypot(dzdx, dzdy)))

    def statistics(self) -> Dict[str, float]:
        z = self.elevations()
        slopes = self.slope_degrees()
        return {
            "min_elevation_m": float(z.min()),
            "max_elevation_m": float(z.max()),
            "mean_elevation_m": float(z.mean()),
            "relief_m": float(z.max() - z.min()),
            "rms_height_m": float(z.std()),
            "mean_slope_deg": float(slopes.mean()),
            "p95_slope_deg": float(np.percentile(slopes, 95)),
            "max_slope_deg": float(slopes.max()),
            "quantisation_m": self.quantisation_m,
        }

    # -- persistence ----------------------------------------------------

    def digest(self) -> str:
        """SHA-256 over the raw samples, for the run manifest (§7.4)."""
        return hashlib.sha256(self.samples.tobytes()).hexdigest()

    def metadata(self) -> Dict[str, Any]:
        return {
            "magic": self.MAGIC,
            "version": self.VERSION,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "dtype": "uint16",
            "scale_m": self.scale_m,
            "offset_m": self.offset_m,
            "georeference": self.georeference.to_dict(),
            "sha256": self.digest(),
            "statistics": self.statistics(),
            "provenance": self.provenance,
        }

    def write(self, path) -> Path:
        """Write ``<path>.r16`` plus a ``<path>.json`` sidecar."""
        path = Path(path).with_suffix("")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = path.with_suffix(".r16")
        # Little-endian explicitly: a raster written on one machine and read on
        # another must not silently change elevation.
        self.samples.astype("<u2").tofile(raw)
        path.with_suffix(".json").write_text(json.dumps(self.metadata(), indent=1))
        return raw

    @classmethod
    def read(cls, path) -> "Heightfield":
        path = Path(path).with_suffix("")
        meta = json.loads(path.with_suffix(".json").read_text())
        if meta.get("magic") != cls.MAGIC:
            raise ValueError(f"{path} is not a flightsim heightfield")
        if meta.get("version") != cls.VERSION:
            raise ValueError(
                f"heightfield version {meta.get('version')} is not supported "
                f"(expects {cls.VERSION}); refusing to guess at the layout"
            )
        samples = np.fromfile(path.with_suffix(".r16"), dtype="<u2")
        samples = samples.reshape(meta["height"], meta["width"]).astype(np.uint16)
        field = cls(
            samples=samples,
            georeference=Georeference.from_dict(meta["georeference"]),
            scale_m=meta["scale_m"],
            offset_m=meta["offset_m"],
            name=meta.get("name", "heightfield"),
            provenance=meta.get("provenance", {}),
        )
        if field.digest() != meta["sha256"]:
            raise ValueError(
                f"{path}: sample data does not match the recorded SHA-256. The "
                f"raster has been modified or truncated since it was baked."
            )
        return field

    # -- construction ---------------------------------------------------

    @classmethod
    def from_elevations(
        cls,
        elevations: np.ndarray,
        georeference: Georeference,
        name: str = "heightfield",
        provenance: Optional[Dict[str, Any]] = None,
    ) -> "Heightfield":
        """Quantise a float elevation array into the 16-bit storage format.

        Scale and offset are derived from the data's own range, which is what
        §6.3's ``gdal_translate -scale <min> <max> 0 65535`` does and what makes
        the Landscape Z-scale computable later.
        """
        z = np.asarray(elevations, dtype=np.float64)
        if not np.isfinite(z).all():
            raise ValueError("elevation array contains non-finite values")
        lo = float(z.min())
        hi = float(z.max())
        # A flat raster has no range; give it a scale rather than dividing by 0.
        scale = (hi - lo) / U16_MAX if hi > lo else 1.0 / U16_MAX
        samples = np.rint((z - lo) / scale).clip(0, U16_MAX).astype(np.uint16)
        return cls(samples, georeference, scale_m=scale, offset_m=lo,
                   name=name, provenance=provenance)

    def __repr__(self) -> str:
        stats = self.statistics()
        return (f"Heightfield({self.name!r}, {self.width}x{self.height}, "
                f"{self.georeference.pixel_size_m:g} m/px, relief "
                f"{stats['relief_m']:.0f} m, quantisation "
                f"{self.quantisation_m * 100:.1f} cm)")
