"""DEM ingestion: real elevation data into the same raster a synthesiser writes.

The pipeline follows §6.3, and the ordering of its first two steps is the part
that matters:

1. **Reproject to a metric CRS.** A UE Landscape has no concept of degree-based
   pixel spacing, and neither does a ground callback that wants metres. A DEM
   left in EPSG:4326 has pixels whose ground size changes with latitude.
2. **Resample to a target ground sample distance**, so the raster has one
   pixel size everywhere.
3. **Quantise to 16-bit with a recorded scale and offset**, which is what
   ``gdal_translate -scale <min> <max> 0 65535`` does and what makes the
   Landscape Z-scale computable afterwards.

Step 3 is where "my mountain is the wrong height" comes from: the scale and
offset have to survive to the Landscape import, and if they are recomputed or
guessed anywhere in between the elevations come back wrong. They are written
into the sidecar and carried through.

Nodata
------
Void pixels are real in SRTM and appear as steep-sided pits that a ground
callback would happily fly an aircraft into. They are filled by nearest-valid
interpolation and the count is recorded, rather than being silently passed
through as -32768.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .heightfield import Georeference, Heightfield


class DEMError(Exception):
    """A DEM could not be ingested."""


def _require_rasterio():
    try:
        import rasterio  # noqa: F401
        from rasterio.warp import Resampling, calculate_default_transform, reproject
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DEMError(
            "DEM ingestion needs rasterio (which bundles GDAL): "
            "pip install rasterio"
        ) from exc
    return rasterio, calculate_default_transform, reproject, Resampling


def fill_voids(z: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Fill masked pixels from the nearest valid sample.

    Returns the filled array and the number of pixels filled. A DEM void is not
    a low place; it is missing data, and treating it as elevation puts a pit in
    the terrain that the FDM will fly into.
    """
    void_count = int(mask.sum())
    if void_count == 0:
        return z, 0
    if mask.all():
        raise DEMError("every pixel in the DEM is nodata")

    from scipy import ndimage  # type: ignore

    indices = ndimage.distance_transform_edt(
        mask, return_distances=False, return_indices=True
    )
    return z[tuple(indices)], void_count


def _fill_voids_numpy(z: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Void fill without SciPy: iterative dilation of valid neighbours.

    Slower than a distance transform but keeps the dependency list short, and a
    DEM is ingested once and baked.
    """
    void_count = int(mask.sum())
    if void_count == 0:
        return z, 0
    if mask.all():
        raise DEMError("every pixel in the DEM is nodata")

    filled = z.copy()
    missing = mask.copy()
    while missing.any():
        neighbours = np.zeros_like(filled)
        counts = np.zeros(filled.shape, dtype=np.int32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            shifted_z = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
            shifted_valid = ~np.roll(np.roll(missing, dy, axis=0), dx, axis=1)
            neighbours += np.where(shifted_valid, shifted_z, 0.0)
            counts += shifted_valid.astype(np.int32)
        can_fill = missing & (counts > 0)
        if not can_fill.any():
            break
        filled = np.where(can_fill, neighbours / np.maximum(counts, 1), filled)
        missing = missing & ~can_fill
    return filled, void_count


def largest_valid_rectangle(valid: np.ndarray) -> Tuple[int, int, int, int]:
    """Largest axis-aligned all-valid rectangle, as (row0, row1, col0, col1).

    Standard largest-rectangle-in-histogram, run per row over a running column
    height. Linear in the number of pixels.
    """
    height, width = valid.shape
    heights = np.zeros(width, dtype=np.int64)
    best = (0, 0, 0, 0)
    best_area = 0

    for r in range(height):
        heights = np.where(valid[r], heights + 1, 0)
        stack: list = []            # (start column, height)
        for c in range(width + 1):
            current = heights[c] if c < width else 0
            start = c
            while stack and stack[-1][1] >= current:
                start, h = stack.pop()
                area = h * (c - start)
                if area > best_area:
                    best_area = area
                    best = (r - h + 1, r + 1, start, c)
            stack.append((start, current))
    return best


def ingest(
    path,
    target_crs: str = "EPSG:32633",
    ground_sample_distance_m: float = 30.0,
    resampling: str = "cubic",
    name: Optional[str] = None,
    crop_to_valid: bool = True,
) -> Heightfield:
    """Read a DEM and bake it to a :class:`Heightfield`.

    The return type is the whole point: identical to what
    :func:`core.terrain.synthesis.generate` produces, so nothing downstream can
    tell a real mountain from a synthesised one (§3.2).
    """
    rasterio, calculate_default_transform, reproject, Resampling = _require_rasterio()
    path = Path(path)
    if not path.is_file():
        raise DEMError(f"no DEM at {path}")

    try:
        mode = getattr(Resampling, resampling)
    except AttributeError as exc:
        raise DEMError(f"unknown resampling mode {resampling!r}") from exc

    with rasterio.open(path) as src:
        if src.crs is None:
            raise DEMError(
                f"{path} declares no CRS. Refusing to guess: an unreferenced "
                f"raster cannot be placed on the Earth, and assuming one would "
                f"put the terrain somewhere plausible and wrong."
            )
        # Reproject to a metric CRS at the requested ground sample distance.
        transform, width, height = calculate_default_transform(
            src.crs, target_crs, src.width, src.height, *src.bounds,
            resolution=(ground_sample_distance_m, ground_sample_distance_m),
        )
        destination = np.zeros((height, width), dtype=np.float32)
        nodata = src.nodata if src.nodata is not None else -32768.0
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=target_crs,
            dst_nodata=nodata,
            resampling=mode,
        )
        source_crs = str(src.crs)
        source_nodata = src.nodata

    z = destination.astype(np.float64)
    # SRTM voids are typically -32768; anything implausibly low is treated as
    # missing rather than as a very deep valley.
    mask = ~np.isfinite(z) | (z <= max(float(nodata), -1000.0))

    # Reprojecting a lat/lon rectangle into a metric CRS produces a rotated
    # parallelogram inside an axis-aligned bounding box, so the corners hold no
    # data at all. Filling them extends the nearest real elevation outward and
    # leaves a cliff along the seam -- fabricated terrain that the FDM will
    # happily fly into. Measured on the Gate 4 fixture: 10781 pixels, 7% of the
    # raster, producing slopes up to 84.9 degrees where p99 of the real data is
    # 23.3. So the raster is cropped to the largest all-valid rectangle, and
    # only genuine interior voids are filled.
    row0 = col0 = 0
    cropped_away = 0
    if crop_to_valid and mask.any():
        row0, row1, col0, col1 = largest_valid_rectangle(~mask)
        if (row1 - row0) < 8 or (col1 - col0) < 8:
            raise DEMError(
                f"{path}: after reprojection to {target_crs} the largest "
                f"rectangle of real data is only {row1 - row0}x{col1 - col0} "
                f"pixels. Choose a CRS suited to this DEM's location."
            )
        cropped_away = int(z.size - (row1 - row0) * (col1 - col0))
        z = z[row0:row1, col0:col1]
        mask = mask[row0:row1, col0:col1]

    z, voids = _fill_voids_numpy(z, mask)

    georeference = Georeference(
        crs=str(target_crs),
        origin_x_m=float(transform.c) + col0 * float(ground_sample_distance_m),
        origin_y_m=float(transform.f) - row0 * float(ground_sample_distance_m),
        pixel_size_m=float(ground_sample_distance_m),
    )
    return Heightfield.from_elevations(
        z, georeference, name=name or path.stem,
        provenance={
            "producer": "dem ingestion",
            "source": str(path),
            "source_crs": source_crs,
            "source_nodata": source_nodata,
            "target_crs": str(target_crs),
            "ground_sample_distance_m": ground_sample_distance_m,
            "resampling": resampling,
            "voids_filled": voids,
            "pixels_cropped_as_outside_source": cropped_away,
        },
    )


def write_geotiff(
    path,
    elevations: np.ndarray,
    crs: str,
    origin_x: float,
    origin_y: float,
    pixel_size: float,
    nodata: Optional[float] = None,
) -> Path:
    """Write a GeoTIFF. Used to build fixtures that exercise the real reader.

    Testing ingestion against a hand-built numpy array would skip the parts most
    likely to be wrong -- the CRS handling and the reprojection -- so the tests
    write a real georeferenced file and read it back through GDAL.
    """
    rasterio, _, _, _ = _require_rasterio()
    from rasterio.transform import from_origin

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    z = np.asarray(elevations, dtype=np.float32)
    profile = {
        "driver": "GTiff", "height": z.shape[0], "width": z.shape[1],
        "count": 1, "dtype": "float32", "crs": crs,
        "transform": from_origin(origin_x, origin_y, pixel_size, pixel_size),
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(z, 1)
    return path
