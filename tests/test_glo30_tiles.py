"""core/terrain/glo30.py: every curated location lists the GLO-30 tiles its
bbox touches (a missing tile is mosaicked as 0 m: the Grand Canyon bake was
half sea level with a cliff at the desert preset's origin)."""

import dataclasses

import pytest

from core.terrain.dem import DEMError
from core.terrain.glo30 import LOCATIONS, require_tiles_cover, tile_footprint, tiles_needed


@pytest.mark.parametrize("key", sorted(LOCATIONS))
def test_every_location_s_tiles_cover_its_bbox(key):
    location = LOCATIONS[key]
    require_tiles_cover(location)
    lat_min, lat_max, lon_min, lon_max = location.bbox
    footprints = [tile_footprint(stem) for stem in location.tiles]
    for lat in (lat_min, lat_max):
        for lon in (lon_min, lon_max):
            assert any(a <= lat <= b and c <= lon <= d for a, b, c, d in footprints), (lat, lon)
    assert location.origin_lat and any(a <= location.origin_lat <= b and c <= location.origin_lon <= d
                                       for a, b, c, d in footprints)


def test_the_grand_canyon_has_its_four_tiles():
    assert set(LOCATIONS["grand_canyon"].tiles) == {
        "N35_00_W112_00", "N35_00_W113_00", "N36_00_W112_00", "N36_00_W113_00"}


def test_a_stem_names_its_south_west_corner():
    assert tile_footprint("N36_00_W112_00") == (36.0, 37.0, -112.0, -111.0)
    assert tile_footprint("N45_00_E007_00") == (45.0, 46.0, 7.0, 8.0)
    assert tiles_needed((36.0, 36.5, -112.0, -111.5)) == ("N36_00_W112_00",)


def test_a_short_tile_list_refuses_by_name():
    short = dataclasses.replace(LOCATIONS["grand_canyon"], tiles=("N36_00_W112_00",))
    with pytest.raises(DEMError, match=r"^terrain\.tiles_uncovered: .*N35_00_W113_00"):
        require_tiles_cover(short)
    with pytest.raises(DEMError, match=r"^terrain\.tiles_uncovered"):
        tile_footprint("n36w112")
