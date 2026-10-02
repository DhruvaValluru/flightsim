"""VIIRS night lights, draped over the georeferenced terrain bakes.

At night the imagery drape goes dark with the sun; what a pilot sees are
towns. This module fetches NASA's Black Marble composite (VIIRS Day/Night
Band, 2016 annual cloud-free composite) for a bake's footprint, extracts
the emitted-light component, and writes it on the SAME texel grid as the
bake (one texel per DEM pixel), so the terrain material adds it as
emission with no registration parameters -- the imagery drape's alignment
argument (core/terrain/imagery.py) applies unchanged.

Source, honestly
----------------
NASA GIBS WMS (``gibs.earthdata.nasa.gov``, public, no account), layer
``VIIRS_Black_Marble``: the 2016 Black Marble colour composite, ~500 m
(15 arc-second) native. NASA imagery is public domain; attribution is
requested and carried. It is a decade-old ANNUAL composite: lights built
or switched off since then are wrong, and the product is a visual,
tone-mapped image -- the extraction below is a presentation mapping from
that image to emission, NOT a radiometric conversion of VIIRS radiance,
and every manifest says so.
"""

from __future__ import annotations

import io
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Tuple

import numpy as np

from .glo30 import Location, sha256_of
from .heightfield import Heightfield
from .imagery import TexelGrid, reproject_to_grid

WMS_ENDPOINT = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
LAYER = "VIIRS_Black_Marble"
#: 15 arc-seconds, the composite's native posting.
NATIVE_DEG = 15.0 / 3600.0
LICENSE = "public domain (NASA imagery)"
ATTRIBUTION = ("NASA Earth Observatory / Black Marble 2016, VIIRS Day/Night "
               "Band, via NASA GIBS")
SOURCE_NOTE = ("2016 annual cloud-free composite, ~500 m; tone-mapped "
               "colour product. Emission extracted by a presentation "
               "mapping (luminance above the unlit-land floor), not "
               "radiometric.")

#: Composite luminance (0-255) of unlit land/water; anything at or below
#: reads as no emission. The product paints unlit ground a dim blue-grey.
UNLIT_FLOOR = 28.0
#: Warm sodium/LED mix for the emitted colour (linear RGB, max 1).
LIGHT_COLOUR = (1.0, 0.78, 0.52)
#: Emissive luminance, cd/m^2, of a fully-lit texel as seen from altitude
#: (a town at night averages a few nits over a 30 m texel).
FULL_TEXEL_LUMINANCE_NITS = 4.0


class NightLightsError(RuntimeError):
    pass


def getmap_url(bbox: Tuple[float, float, float, float]) -> Tuple[str, int, int]:
    """WMS 1.3.0 GetMap for a (lat_min, lat_max, lon_min, lon_max) bbox at
    the native posting. EPSG:4326 in 1.3.0 is lat,lon axis order."""
    lat_min, lat_max, lon_min, lon_max = bbox
    # (1e-9: 0.4 deg / 15 arcsec is 96.000000001 in floating point.)
    width = max(8, int(math.ceil((lon_max - lon_min) / NATIVE_DEG - 1e-9)))
    height = max(8, int(math.ceil((lat_max - lat_min) / NATIVE_DEG - 1e-9)))
    query = urllib.parse.urlencode({
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0",
        "LAYERS": LAYER, "STYLES": "", "CRS": "EPSG:4326",
        "BBOX": f"{lat_min},{lon_min},{lat_max},{lon_max}",
        "WIDTH": str(width), "HEIGHT": str(height), "FORMAT": "image/png",
    })
    return f"{WMS_ENDPOINT}?{query}", width, height


def emission_from_composite(rgb: np.ndarray) -> np.ndarray:
    """Composite RGB uint8 -> emission 0..1 (float32), per pixel."""
    rgb = rgb.astype(np.float32)
    # Rounded so an exactly-at-floor grey is exactly zero, not 1e-9.
    luma = np.round(0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1]
                    + 0.0722 * rgb[..., 2], 3)
    return np.clip((luma - UNLIT_FLOOR) / (255.0 - UNLIT_FLOOR), 0.0, 1.0)


def write_source_geotiff(emission: np.ndarray,
                         bbox: Tuple[float, float, float, float],
                         out_path: Path) -> Path:
    """Emission (0..1) as a 3-band uint8 EPSG:4326 GeoTIFF, so the
    imagery module's reprojection applies verbatim."""
    import rasterio
    from rasterio.transform import from_origin

    lat_min, lat_max, lon_min, lon_max = bbox
    height, width = emission.shape
    transform = from_origin(lon_min, lat_max, (lon_max - lon_min) / width,
                            (lat_max - lat_min) / height)
    band = np.round(emission * 255.0).astype(np.uint8)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", driver="GTiff", height=height,
                       width=width, count=3, dtype="uint8",
                       crs="EPSG:4326", transform=transform) as dst:
        for index in range(3):
            dst.write(band, index + 1)
    return out_path


def verify_against_source(texture: np.ndarray, grid: TexelGrid,
                          source_4326: Path, samples: int = 400,
                          seed: int = 20260930) -> Dict:
    """Texel -> projected -> geographic -> source pixel, point by point,
    as the imagery drape is verified. A scene with no lights at all has
    nothing to misplace and passes with that stated."""
    import rasterio
    from pyproj import Transformer

    rng = np.random.default_rng(seed)
    to_geo = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    rows = rng.integers(0, grid.height, samples)
    cols = rng.integers(0, grid.width, samples)
    x = grid.origin_x_m + (cols + 0.5) * grid.texel_size_m
    y = grid.origin_y_m - (rows + 0.5) * grid.texel_size_m
    lon, lat = to_geo.transform(x, y)
    with rasterio.open(source_4326) as src:
        source = src.read(1).astype(np.float32)
        r, c = rasterio.transform.rowcol(src.transform, lon, lat)
    r = np.clip(np.asarray(r), 0, source.shape[0] - 1)
    c = np.clip(np.asarray(c), 0, source.shape[1] - 1)
    baked = texture[rows, cols].astype(np.float32)
    truth = source[r, c]
    if truth.std() < 1.0:
        return {"ok": True, "samples": samples, "note": "no lights in the "
                "footprint; nothing to misplace"}
    corr = float(np.corrcoef(baked, truth)[0, 1])
    # Nearest-neighbour source vs bilinear bake at 500 m -> 30 m: strongly
    # but not perfectly correlated; a flipped or swapped grid decorrelates.
    return {"ok": corr > 0.8, "samples": samples, "correlation": round(corr, 4)}


def drape(location: Location, baked_path, cache_dir, out_dir) -> Path:
    """Fetch, extract, reproject onto the bake's grid, verify, write.

    Returns the sidecar path (``<key>_nightlights.json`` beside its PNG).
    Raises :class:`NightLightsError` on fetch or verification failure --
    an unverified drape must not render by accident.
    """
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    url, width, height = getmap_url(location.bbox)
    raw = cache_dir / f"{location.key}_{LAYER}.png"
    if not raw.is_file():
        try:
            with urllib.request.urlopen(url, timeout=60) as rsp:
                data = rsp.read()
                kind = rsp.headers.get("Content-Type", "")
        except OSError as exc:
            raise NightLightsError(f"GIBS fetch failed: {exc}") from exc
        if "image/png" not in kind:
            raise NightLightsError(
                f"GIBS answered {kind!r}, not a PNG: "
                f"{data[:200]!r}")
        raw.write_bytes(data)
    composite = np.asarray(Image.open(io.BytesIO(raw.read_bytes()))
                           .convert("RGB"))
    if composite.shape[:2] != (height, width):
        raise NightLightsError(
            f"GIBS returned {composite.shape[:2]}, asked {(height, width)}")

    emission = emission_from_composite(composite)
    source = write_source_geotiff(
        emission, location.bbox,
        out_dir / f"{location.key}_nightlights_source_4326.tif")
    baked = Heightfield.read(baked_path)
    grid = TexelGrid.from_bake(baked, texels_per_pixel=1)
    texture = reproject_to_grid(source, grid)[..., 0]
    verification = verify_against_source(texture, grid, source)
    if not verification["ok"]:
        raise NightLightsError(
            f"{location.key}: night-lights texture disagrees with its "
            f"source ({verification}); refusing an unverified drape")

    level = texture.astype(np.float32) / 255.0
    rgb = np.stack([level * channel for channel in LIGHT_COLOUR], axis=-1)
    png = out_dir / f"{location.key}_nightlights.png"
    # Stored as sRGB so the engine's default texture import decodes it
    # back to the linear emission above.
    srgb = np.where(rgb <= 0.0031308, rgb * 12.92,
                    1.055 * np.power(rgb, 1 / 2.4) - 0.055)
    Image.fromarray(np.round(srgb * 255.0).astype(np.uint8)).save(png)

    sidecar = {
        "dataset": f"NASA Black Marble 2016 (GIBS layer {LAYER!r})",
        "license": LICENSE,
        "attribution": ATTRIBUTION,
        "source_note": SOURCE_NOTE,
        "endpoint": WMS_ENDPOINT,
        "request": url,
        "source_sha256": sha256_of(raw),
        "texture": {
            "file": png.name,
            "sha256": sha256_of(png),
            "crs": grid.crs,
            "origin_x_m": grid.origin_x_m, "origin_y_m": grid.origin_y_m,
            "texel_size_m": grid.texel_size_m,
            "width": grid.width, "height": grid.height,
            "aligned_to_bake": str(Path(baked_path).resolve()),
        },
        "full_texel_luminance_nits": FULL_TEXEL_LUMINANCE_NITS,
        "lit_fraction": round(float((texture > 0).mean()), 5),
        "verification_vs_source": verification,
    }
    path = out_dir / f"{location.key}_nightlights.json"
    path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    return path
