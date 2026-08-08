"""Sentinel-2 imagery drape: tile arithmetic, alignment, and the verifier.

No network: tile fetches are experiment-time. What the suite pins down is
the arithmetic that places tiles on the earth, the texel grid's construction
from the bake (alignment is by construction, so the construction must be
right), the provenance constants a manifest will carry, and that the
round-trip verifier actually catches a mis-draped texture.
"""

import numpy as np
import pytest

from core.terrain.heightfield import Georeference, Heightfield
from core.terrain.imagery import (
    ATTRIBUTION,
    LICENSE,
    TexelGrid,
    tile_indices,
    tile_range,
    tile_span_deg,
    tile_url,
    verify_drape,
)


# -- WGS84 tile arithmetic ----------------------------------------------


def test_tile_grid_corners():
    """The WGS84 matrix at zoom z is 2^(z+1) x 2^z tiles from (90, -180)."""
    assert tile_indices(90.0, -180.0, 5) == (0, 0)
    # Just inside the south-east corner lands on the last tile.
    row, col = tile_indices(-90.0 + 1e-9, 180.0 - 1e-9, 5)
    assert (row, col) == (2 ** 5 - 1, 2 ** 6 - 1)


def test_tile_span_halves_per_zoom():
    assert tile_span_deg(0) == 180.0
    assert tile_span_deg(13) == pytest.approx(180.0 / 8192)


def test_tile_indices_round_trip():
    """A tile's north-west corner maps back to the same tile."""
    zoom = 13
    span = tile_span_deg(zoom)
    row, col = tile_indices(46.0, 7.72, zoom)
    lat_nw = 90.0 - row * span
    lon_nw = -180.0 + col * span
    assert lat_nw >= 46.0 > lat_nw - span
    assert lon_nw <= 7.72 < lon_nw + span


def test_tile_range_covers_the_bbox():
    bbox = (45.85, 46.10, 7.45, 7.95)   # the Matterhorn scene
    zoom = 13
    rows, cols = tile_range(bbox, zoom)
    r_nw, c_nw = tile_indices(bbox[1], bbox[2], zoom)
    r_se, c_se = tile_indices(bbox[0] + 1e-9, bbox[3] - 1e-9, zoom)
    assert rows[0] <= r_nw and rows[-1] >= r_se
    assert cols[0] <= c_nw and cols[-1] >= c_se


def test_tile_url_names_the_cc_by_sa_layer():
    url = tile_url(13, 100, 200)
    assert "/s2cloudless/" in url, (
        "the 2016 release (layer 's2cloudless') is the CC-BY-SA one; "
        "year-suffixed layers are CC-BY-NC-SA and must not be fetched")
    assert url.endswith("13/100/200.jpg")


def test_provenance_constants():
    assert LICENSE == "CC-BY-SA 4.0"
    assert "EOX" in ATTRIBUTION and "Copernicus Sentinel" in ATTRIBUTION


# -- the texel grid is the bake's frame ---------------------------------


def bake_fixture(width=64, height=48, pixel_m=30.0):
    return Heightfield(
        samples=np.zeros((height, width), dtype=np.uint16),
        georeference=Georeference(crs="EPSG:32632", origin_x_m=400000.0,
                                  origin_y_m=5100000.0, pixel_size_m=pixel_m),
        scale_m=0.1, offset_m=0.0, name="fixture",
    )


def test_texel_grid_shares_the_bake_frame():
    baked = bake_fixture()
    grid = TexelGrid.from_bake(baked)
    assert grid.crs == baked.georeference.crs
    assert grid.origin_x_m == baked.georeference.origin_x_m
    assert grid.origin_y_m == baked.georeference.origin_y_m
    assert grid.width == baked.width * 3
    assert grid.height == baked.height * 3
    assert grid.texel_size_m * 3 == baked.georeference.pixel_size_m


def test_texel_grid_respects_the_texture_cap():
    baked = bake_fixture(width=4000, height=3000)
    grid = TexelGrid.from_bake(baked)
    assert max(grid.width, grid.height) <= 8192
    # Still an integer subdivision: alignment survives the cap.
    ratio = baked.georeference.pixel_size_m / grid.texel_size_m
    assert ratio == pytest.approx(round(ratio))


# -- the verifier must catch a mis-drape --------------------------------


def _flat_scene(tmp_path):
    """A tiny 4326 source with a gradient, and its correctly draped texture."""
    import rasterio
    from rasterio.transform import from_origin

    from core.terrain.imagery import reproject_to_grid

    height = width = 128
    lat0, lon0 = 46.1, 7.4
    pixel_deg = 0.5 / width
    rgb = np.zeros((3, height, width), dtype=np.uint8)
    ramp = np.linspace(20, 235, width, dtype=np.uint8)
    rgb[0] = ramp[np.newaxis, :]
    rgb[1] = ramp[::-1][np.newaxis, :]
    rgb[2] = np.linspace(20, 235, height, dtype=np.uint8)[:, np.newaxis]
    source = tmp_path / "source_4326.tif"
    with rasterio.open(
        source, "w", driver="GTiff", height=height, width=width, count=3,
        dtype="uint8", crs="EPSG:4326",
        transform=from_origin(lon0, lat0, pixel_deg, pixel_deg),
    ) as dst:
        dst.write(rgb)

    grid = TexelGrid(crs="EPSG:32632", origin_x_m=380000.0,
                     origin_y_m=5098000.0, texel_size_m=200.0,
                     width=96, height=96)
    return source, grid, reproject_to_grid(source, grid)


def test_verifier_passes_a_correct_drape(tmp_path):
    source, grid, texture = _flat_scene(tmp_path)
    report = verify_drape(texture, grid, source, samples=200)
    assert report["ok"], report


def test_verifier_catches_a_row_flip(tmp_path):
    """The failure mode alignment-by-construction cannot rule out on its own:
    an axis flip between raster and texture conventions."""
    source, grid, texture = _flat_scene(tmp_path)
    report = verify_drape(np.flipud(texture).copy(), grid, source, samples=200)
    assert not report["ok"], report


def test_verifier_catches_a_shifted_drape(tmp_path):
    source, grid, texture = _flat_scene(tmp_path)
    shifted = np.roll(texture, 12, axis=1)
    report = verify_drape(shifted, grid, source, samples=200)
    assert not report["ok"], report
