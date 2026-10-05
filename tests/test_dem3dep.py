"""USGS 3DEP as a second elevation source: the tile naming, the coverage
refusal and the GDAL environment -- nothing here touches the network."""

import pytest

from core.terrain.dem import DEMError
from core.terrain.dem3dep import (
    BUCKET, bake, covers, crop_path, gdal_env, tile_stems, tile_url,
)
from core.terrain.glo30 import LOCATIONS


def test_tile_stems_name_the_north_and_west_edges():
    # Yosemite: 37.60..37.85 N, 119.80..119.40 W -> the one tile 37..38 N, 120..119 W
    assert tile_stems(LOCATIONS["yosemite"].bbox) == ("n38w120",)
    # the Grand Canyon box crosses 36 N and 112 W: four tiles
    assert tile_stems(LOCATIONS["grand_canyon"].bbox) == (
        "n36w113", "n36w112", "n37w113", "n37w112")
    # a box on an exact degree edge stays in one tile
    assert tile_stems((37.0, 38.0, -120.0, -119.0)) == ("n38w120",)
    assert tile_url("n38w120") == f"{BUCKET}/n38w120/USGS_13_n38w120.tif"


def test_coverage_is_the_united_states():
    assert covers(LOCATIONS["yosemite"].bbox)
    assert covers(LOCATIONS["grand_canyon"].bbox)
    assert covers(LOCATIONS["flint_hills"].bbox)
    assert not covers(LOCATIONS["matterhorn"].bbox)
    assert not covers(LOCATIONS["everest"].bbox)
    assert not covers(LOCATIONS["fuji"].bbox)


def test_a_place_outside_the_coverage_is_refused_before_any_fetch(tmp_path):
    with pytest.raises(DEMError, match="3DEP covers the United States"):
        bake(LOCATIONS["matterhorn"], tmp_path / "cache", tmp_path / "out")


def test_crop_path_encodes_the_box_without_dots_or_signs(tmp_path):
    path = crop_path(tmp_path, "n38w120", LOCATIONS["yosemite"].bbox)
    assert path.name == "USGS_13_n38w120_37p600_37p850_m119p800_m119p400.tif"


def test_gdal_env_carries_the_machines_proxy_and_ca_bundle(tmp_path, monkeypatch):
    ca = tmp_path / "ca.pem"
    ca.write_text("x")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("GIT_SSL_CAINFO", str(ca))
    monkeypatch.delenv("GDAL_CURL_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    env = gdal_env()
    assert env["GDAL_HTTP_PROXY"] == "http://127.0.0.1:9"
    assert env["GDAL_CURL_CA_BUNDLE"] == str(ca)
    assert env["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] == ".tif"
    monkeypatch.delenv("HTTPS_PROXY")
    monkeypatch.delenv("https_proxy", raising=False)
    assert "GDAL_HTTP_PROXY" not in gdal_env()
