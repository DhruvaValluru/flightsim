"""Round-2b terrain-ocean lane (2026-11-09): round 0 #06 and #13, beauty only.

#06 (SFO in moderate rain, 3000 m): the rain's extinction drawn as height fog
buried the tiles; the host now thins the haze along a read ray in beauty
(FlightSimGoogleTiles.cpp ApplyBeautyGround). #13 (747 over the open ocean):
the flat card carried cameras but no scene_crs, so the host placed the
Python-solved camera through the GeoReferencing default EPSG:32631, about
4400 km away; a beauty card now declares the frame, the host refuses a
mismatch by name, and the open sea gets a water surface. Measure is unchanged.
The C++ is uncompiled here: its text is pinned, its arithmetic mirrored.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
TILES_CPP = PRIVATE / "FlightSimGoogleTiles.cpp"
COMMANDLET_CPP = PRIVATE / "FlightSimRenderCommandlet.cpp"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _Q:
    def __init__(self, value, source="inferred"):
        self.value, self.source = value, source


class _Spec:
    def __init__(self, lat, lon):
        self.latitude, self.longitude = _Q(lat), _Q(lon)


ATLANTIC = (35.0, -45.0)          # core/terrain/ocean.py OPEN_OCEAN["atlantic"]
SFO = (37.6213, -122.3790)


# -- #13: the camera's frame ---------------------------------------------------

def test_round0_13_cause_reproduced():
    """The Atlantic origin's UTM-23 easting/northing read as EPSG:32631 (the
    plugin default, GeoReferencingSystem.h) is ~4300 km east at 3 E: over
    Algeria, the Earth's curvature tilting the horizon by ~39 degrees --
    round 0's brown land under a ~35 degree horizon and no aircraft."""
    from pyproj import Geod, Transformer

    from core.terrain.glo30 import utm_zone_crs

    lat, lon = ATLANTIC
    crs = utm_zone_crs(lat, lon)
    assert crs == "EPSG:32623"
    x, y = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(lon, lat)
    wrong_lon, wrong_lat = Transformer.from_crs("EPSG:32631", "EPSG:4326",
                                                always_xy=True).transform(x, y)
    _, _, metres = Geod(ellps="WGS84").inv(lon, lat, wrong_lon, wrong_lat)
    assert 4000e3 < metres < 4700e3
    assert 30.0 < math.degrees(metres / 6371e3) < 45.0


def test_beauty_flat_scene_with_cameras_declares_its_frame():
    from webapp.runs import beauty_scene_crs

    flat = {"key": "flat", "terrain": None}
    spec = _Spec(*ATLANTIC)
    assert beauty_scene_crs(spec, flat, True, "beauty") == "EPSG:32623"


@pytest.mark.parametrize("scene,cameras,quality", [
    ({"key": "flat", "terrain": None}, True, "measure"),        # measure: card byte-identical
    ({"key": "flat", "terrain": None}, False, "beauty"),        # no consume-poses camera
    ({"key": "sfo", "terrain": "/bake/sfo"}, True, "beauty"),   # the raster declares its CRS
])
def test_beauty_scene_crs_declares_nothing_elsewhere(scene, cameras, quality):
    from webapp.runs import beauty_scene_crs

    assert beauty_scene_crs(_Spec(*ATLANTIC), scene, cameras, quality) is None


def test_card_arguments_take_the_beauty_frame():
    text = _text(REPO / "webapp/runs.py")
    hook = text.index("scene_crs = scene_crs or beauty_scene_crs(")
    assert hook < text.index("card_arguments = dict(", hook)
    assert "run_render_quality(run.look)" in text[hook:hook + 200]


def test_host_refuses_a_camera_frame_mismatch_in_beauty():
    text = _text(COMMANDLET_CPP)
    start = text.index("round-2b terrain-ocean lane hook")
    block = text[start:text.index("supersample lane hook", start)]
    assert "if (bBeauty && bVisual)" in block
    assert "camera.scene_frame_mismatch: " in block
    assert "ProjectedToEngine" in block and "CameraOriginXMetres" in block
    catalog = _text(REPO / "core/messages/catalog.yaml")
    assert re.search(r"^camera\.scene_frame_mismatch:", catalog, re.M)


# -- #13: the open sea ---------------------------------------------------------

def test_sea_radius_over_the_open_atlantic():
    from webapp.runs import beauty_sea_radius_m

    radius = beauty_sea_radius_m({"terrain": None}, *ATLANTIC, 0.0)
    # 3 land-free cells, the narrowest at 39 N: 3 x 111.2 km x cos 39 x 0.9.
    assert radius == pytest.approx(3 * 111_195.0 * math.cos(math.radians(39.0)) * 0.9, abs=1.0)
    assert 200e3 < radius < 330e3


@pytest.mark.parametrize("scene,lat,lon,datum", [
    ({"terrain": "/bake/sfo"}, *SFO, 4.0),      # a terrain scene: the tiles' land
    ({"terrain": None}, *SFO, 0.0),             # beside land: no open-ocean cells
    ({"terrain": None}, *ATLANTIC, 120.0),      # not a sea-level datum
])
def test_no_sea_where_land_could_be(scene, lat, lon, datum):
    from webapp.runs import beauty_sea_radius_m

    assert beauty_sea_radius_m(scene, lat, lon, datum) is None


def test_sea_flag_is_beauty_only(tmp_path):
    from webapp.runs import beauty_sea_flags

    card = tmp_path / "card.json"
    card.write_text(json.dumps({"latitude_deg": ATLANTIC[0], "longitude_deg": ATLANTIC[1],
                                "terrain_elevation_m": 0.0}), encoding="utf-8")
    assert beauty_sea_flags({"terrain": None}, card, "measure") == []
    flags = beauty_sea_flags({"terrain": None}, card, "beauty")
    assert len(flags) == 1 and flags[0].startswith("-beauty-sea-radius-m=")
    assert "extra += beauty_sea_flags(scene, card, quality)" in _text(REPO / "webapp/runs.py")


def test_sea_cap_is_beauty_only_and_never_hides_the_tiles():
    text = _text(TILES_CPP)
    body = text[text.index("TSharedPtr<FJsonObject> FFlightSimGoogleTiles::ApplyBeautyGround"):]
    assert "BeautyOnlyActors.Add(SeaActor)" in body
    sea = body.split("BeautyOnlyActors.Add(SeaActor)")[0].split("AActor* SeaActor")[1]
    assert "Tags.Add" not in sea      # untagged: HideOwnTerrain never hides it
    # The tiles stay: nothing in the lane turns them off or hides the tileset.
    assert "SetActorHiddenInGame" not in body and "bEnabled = false" not in body


def test_sea_cap_winding_faces_up():
    """The cap's triangles (centre fan and ring quads) are clockwise seen from
    +Z, the winding the scene's own ground faces up with."""
    def cross_z(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    rings, segments, radius = 4, 8, 1000.0
    def vertex(ring, segment):
        if ring == 0:
            return (0.0, 0.0)
        r = radius * (ring / rings) ** 2
        a = 2 * math.pi * (segment % segments) / segments
        return (r * math.cos(a), r * math.sin(a))
    for s in range(segments):
        assert cross_z(vertex(0, 0), vertex(1, s + 1), vertex(1, s)) < 0
        for ring in range(1, rings):
            p0, p1 = vertex(ring, s), vertex(ring, s + 1)
            q0, q1 = vertex(ring + 1, s), vertex(ring + 1, s + 1)
            assert cross_z(p0, p1, q0) < 0 and cross_z(p1, q1, q0) < 0
    text = _text(TILES_CPP)
    assert "Triangles.Append({0, RingVertex(1, Segment + 1), RingVertex(1, Segment)});" in text
    assert "Triangles.Append({P0, P1, Q0, P1, Q1, Q0});" in text
    ground = _text(PRIVATE / "FlightSimVisualScene.cpp")
    assert "const TArray<int32> GroundTriangles = {0, 1, 2, 1, 3, 2};" in ground


# -- #06: the haze the ground is read through ------------------------------------

def _cpp_constant(name: str) -> float:
    match = re.search(rf"constexpr double {name} = ([0-9.eE+-]+);", _text(TILES_CPP))
    assert match, name
    return float(match.group(1))


def test_fog_density_unit_matches_python():
    from core.scene.weather_visuals import ENGINE_FOG_DENSITY_PER_EXTINCTION

    assert _cpp_constant("FogDensityPerExtinctionPerM") == pytest.approx(
        ENGINE_FOG_DENSITY_PER_EXTINCTION, rel=1e-12)


def _read_scale(beta_per_m: float, mie_share: float, mie_cap: float, mie_h_km: float,
                agl_m: float) -> float:
    """ApplyBeautyGround's arithmetic on the world lane's split (MieSplit,
    FlightSimClouds.cpp): fog keeps (haze - Mie) of the Koschmieder beta."""
    k = _cpp_constant("FogDensityPerExtinctionPerM")
    depression = _cpp_constant("ReadDepressionDeg")
    od_max = _cpp_constant("ReadOpticalDepthMax")
    beta_km = beta_per_m * 1000.0
    haze = max(beta_km - 0.0116, 0.0)
    mie = min(mie_share * haze, mie_cap)
    fog_density = beta_per_m * k * (haze - mie) / beta_km
    f = 0.0002 / 10.0                      # FlightSimVisualScene.cpp SetFogHeightFalloff(0.0002f)
    column = (1.0 - 2.0 ** (-f * agl_m)) / (f * math.log(2.0))
    fog_od = fog_density / k * column
    mie_od = mie * mie_h_km * (1.0 - math.exp(-agl_m / 1000.0 / mie_h_km))
    total = (fog_od + mie_od) / math.sin(math.radians(depression))
    return 1.0 if total <= od_max else max(_cpp_constant("MinHazeScale"), od_max / total)


def test_round0_06_rain_haze_is_thinned_and_a_clear_day_is_not():
    from core.scene.weather_visuals import look_block

    rain = look_block({"precipitation_rate_mmh": 4.0})["fog_extinction_per_m"]
    # world lane rain row: Mie share 0.3, cap 0.8 /km, scale height 1.0 km.
    assert _read_scale(rain, 0.3, 0.8, 1.0, 3000.0) < 0.2
    clear = 0.0025 / _cpp_constant("FogDensityPerExtinctionPerM")
    # world lane clear row: Mie share 0.6, cap 0.25 /km, scale height 1.2 km.
    assert _read_scale(clear, 0.6, 0.25, 1.2, 3000.0) == 1.0


def test_haze_thinning_is_beauty_gated_and_after_the_scene():
    text = _text(COMMANDLET_CPP)
    hook = text.index("GoogleTiles.ApplyBeautyGround(")
    gate = text.rindex("if (bBeauty && bVisual)", 0, hook)
    assert hook - gate < 1500
    # After the world lane (which splits the haze) and the consume-poses placement.
    assert text.index("WorldBeauty.Build(") < hook
    assert text.index("Director->ApplyPoseAtTime(Director->TrackStartSeconds(),") < hook
    body = _text(TILES_CPP)
    assert "if (CameraAglM < ReadMinAglM)" in body
    assert "Out->SetObjectField(TEXT(\"beauty_ground\"), BeautyGround);" in body


def test_check_bridge_api_block_is_marked():
    text = _text(REPO / "scripts/check_bridge_api.sh")
    begin = text.index("BEGIN terrain-ocean")
    end = text.index("END terrain-ocean")
    block = text[begin:end]
    for symbol in ("SetSecondFogDensity", "SetMieScatteringScale", "CreateMeshSection_LinearColor",
                   "ProjectedToEngine", "UMaterialInstanceDynamic* Create("):
        assert symbol in block, symbol
