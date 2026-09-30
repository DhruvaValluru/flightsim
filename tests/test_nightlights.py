"""VIIRS night lights: request geometry, emission extraction, verification.

No network: the GIBS fetch is exercised on the user's machine by the first
night render; here a synthetic composite with known towns goes through the
same reprojection and verification the real drape does.
"""

import urllib.parse

import numpy as np
import pytest

from core.terrain.imagery import TexelGrid, reproject_to_grid
from core.terrain.nightlights import (
    NATIVE_DEG, UNLIT_FLOOR, emission_from_composite, getmap_url,
    verify_against_source, write_source_geotiff,
)

BBOX = (45.80, 46.20, 7.40, 7.90)   # lat_min, lat_max, lon_min, lon_max


def test_getmap_is_wms130_latlon_order_at_native_posting():
    url, width, height = getmap_url(BBOX)
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert query["VERSION"] == "1.3.0" and query["CRS"] == "EPSG:4326"
    # WMS 1.3.0 + EPSG:4326 is lat,lon axis order -- the classic swap bug.
    assert query["BBOX"] == "45.8,7.4,46.2,7.9"
    assert query["LAYERS"] == "VIIRS_Black_Marble"
    assert width == int(np.ceil(0.5 / NATIVE_DEG))
    assert height == int(np.ceil(0.4 / NATIVE_DEG))


def test_unlit_ground_emits_nothing_and_bright_towns_emit_fully():
    composite = np.zeros((2, 2, 3), dtype=np.uint8)
    composite[0, 0] = int(UNLIT_FLOOR)            # dim blue-grey ground
    composite[0, 1] = 255                         # saturated town
    composite[1, 0] = 140                         # suburb
    emission = emission_from_composite(composite)
    assert emission[0, 0] == 0.0 and emission[1, 1] == 0.0
    assert emission[0, 1] == pytest.approx(1.0)
    assert 0.0 < emission[1, 0] < 1.0


def _scene(tmp_path):
    height = int(np.ceil(0.4 / NATIVE_DEG))
    width = int(np.ceil(0.5 / NATIVE_DEG))
    rng = np.random.default_rng(3)
    emission = np.zeros((height, width), dtype=np.float32)
    for _ in range(25):   # towns: bright blobs a few pixels across
        r, c = rng.integers(3, height - 3), rng.integers(3, width - 3)
        emission[r - 2:r + 3, c - 2:c + 3] = rng.uniform(0.4, 1.0)
    source = write_source_geotiff(emission, BBOX, tmp_path / "src.tif")
    # A UTM-32N grid inside the bbox at 30 m, like a GLO-30 bake.
    grid = TexelGrid(crs="EPSG:32632", origin_x_m=380000.0,
                     origin_y_m=5100000.0, texel_size_m=30.0,
                     width=900, height=900)
    return grid, source


def test_a_correct_drape_verifies_against_its_source(tmp_path):
    grid, source = _scene(tmp_path)
    texture = reproject_to_grid(source, grid)[..., 0]
    report = verify_against_source(texture, grid, source)
    assert report["ok"], report


def test_a_flipped_drape_is_refused(tmp_path):
    grid, source = _scene(tmp_path)
    texture = reproject_to_grid(source, grid)[..., 0]
    report = verify_against_source(texture[::-1, :], grid, source)
    assert not report["ok"], report
