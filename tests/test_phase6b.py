"""Phase 6B: mesh pipeline, real terrain, turbulence/orographic analysis.

Offline counterparts of the measured runs: every guard that decides a Phase 6B
verdict -- the §1.4 mesh pairing refusal, the GLO-30 verification, the
turbulence null test, the orographic port comparison, the honesty labels on
the condition matrix cards -- is exercised here on synthetic inputs so the
mutation checker can prove each one load-bearing without a GPU or a network.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from assets_pipeline.acmodel import (
    ac_to_model, ac_to_ue, model_to_ue, parse_ac, world_vertices,
)
from assets_pipeline.convert import ConvertError, convert
from core.environment.terrain_field import OrographicWind
from core.environment.turbulence import DrydenTurbulence
from core.terrain.dem import write_geotiff
from core.terrain.glo30 import (
    LOCATIONS, Location, check_summits, merge_and_crop, orographic_card_block,
    verify_against_source,
)
from core.terrain.ground import terrain_field_at
from core.terrain.heightfield import Heightfield
from core.terrain import dem
from experiments.gate5_ue_parity import reference_spec, write_run_card
from experiments.orographic_ue import verify_port
from experiments.showcase_matrix import (
    CellUnrenderable, build_cell_card, gust_schedule, microburst_track,
)
from experiments.turbulence_ue import compare_realisations, null_test

REPO = Path(__file__).resolve().parents[1]


# -- the AC3D reader -----------------------------------------------------

AC_FIXTURE = """AC3Db
MATERIAL "white" rgb 0.8 0.8 0.8  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  shi 0  trans 0
MATERIAL "red" rgb 0.7 0.1 0.1  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  shi 0  trans 0
OBJECT world
kids 2
OBJECT poly
name "wing"
numvert 4
0 0 0
1 0 0
1 0 2
0 0 2
numsurf 1
SURF 0x0
mat 0
refs 4
0 0 0
1 1 0
2 1 1
3 0 1
kids 0
OBJECT group
name "pod_group"
loc 10 20 30
kids 1
OBJECT poly
name "pod"
numvert 3
0 0 0
1 0 0
0 1 0
numsurf 1
SURF 0x0
mat 1
refs 3
0 0 0
1 0 0
2 0 0
kids 0
"""


def test_ac_parser_reads_objects_materials_and_nested_loc(tmp_path):
    path = tmp_path / "model.ac"
    path.write_text(AC_FIXTURE)
    model = parse_ac(path)
    assert [m.name for m in model.materials] == ["white", "red"]
    named = {obj.name: verts for obj, verts in world_vertices(model)}
    assert set(named) == {"wing", "pod"}
    # The group's loc translates its child: AC3D nests transforms.
    assert named["pod"][0] == (10.0, 20.0, 30.0)
    assert named["wing"][2] == (1.0, 0.0, 2.0)


def test_frame_conversions_match_the_measured_mapping():
    # Measured against the 747 and c172p hinge lines: model.x = ac.x,
    # model.y = -ac.z, model.z = ac.y; UE negates X.
    assert ac_to_model((1.0, 2.0, 3.0)) == (1.0, -3.0, 2.0)
    assert model_to_ue((1.0, 2.0, 3.0)) == (-1.0, 2.0, 3.0)
    assert ac_to_ue((1.0, 2.0, 3.0)) == (-1.0, -3.0, 2.0)


# -- the converter and §1.4 ----------------------------------------------

def _write_config(tmp_path, fdm="B747", fdm_match=("B747-400",),
                  license_file="COPYING"):
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    (source / "model.ac").write_text(AC_FIXTURE)
    (source / "COPYING").write_text("GNU GENERAL PUBLIC LICENSE\n")
    config = {
        "name": "testcraft",
        "fdm": fdm,
        "fdm_match": list(fdm_match),
        "mesh_airframe": "synthetic test craft",
        "source_dir": "src",
        "license": {"license_name": "GPL-2.0", "file": license_file,
                    "repo": "local", "commit": "0" * 40},
        "parts": [{"file": "model.ac"}],
        "exclude": [],
        "surfaces": {
            "aileron_l": {
                "bone": "aileron_l", "objects": ["pod"],
                "property": "fcs/left-aileron-pos-rad",
                "scale_deg_per_unit": 57.29578,
                "hinge_m": [[0.0, -1.0, 0.0], [0.0, -2.0, 0.0]],
            },
        },
    }
    config_path = tmp_path / "testcraft.json"
    config_path.write_text(json.dumps(config))
    return config_path


def test_converter_writes_parts_and_manifest(tmp_path):
    manifest_path = convert(_write_config(tmp_path), tmp_path / "out", REPO)
    manifest = json.loads(manifest_path.read_text())
    assert manifest["magic"] == "flightsim-aircraft-mesh"
    assert manifest["fdm_config_name"] == "B747-400"
    assert (tmp_path / "out" / "testcraft" / "body.obj").is_file()
    assert (tmp_path / "out" / "testcraft" / "aileron_l.obj").is_file()
    surface = manifest["surfaces"][0]
    # Hinge midpoint in UE cm: model (0, -1.5, 0) -> UE (0, -1.5, 0) * 100.
    assert surface["hinge_mid_cm"] == pytest.approx([0.0, -150.0, 0.0])
    assert surface["axis_ue"] == pytest.approx([0.0, -1.0, 0.0])


def test_converter_refuses_a_mesh_of_a_different_airframe(tmp_path):
    # §1.4: "FDM JSBSIM F16 - MODEL F-15" must be impossible to bake.
    config = _write_config(tmp_path, fdm="B747", fdm_match=("Boeing 707",))
    with pytest.raises(ConvertError, match="REFUSING the pairing"):
        convert(config, tmp_path / "out", REPO)


def test_converter_refuses_a_missing_license(tmp_path):
    config = _write_config(tmp_path, license_file="NO_SUCH_FILE")
    with pytest.raises(ConvertError, match="license"):
        convert(config, tmp_path / "out", REPO)


def test_converter_refuses_an_empty_surface(tmp_path):
    config_path = _write_config(tmp_path)
    config = json.loads(config_path.read_text())
    config["surfaces"]["aileron_l"]["objects"] = ["no_such_object"]
    config_path.write_text(json.dumps(config))
    with pytest.raises(ConvertError, match="matched no geometry"):
        convert(config_path, tmp_path / "out", REPO)


def test_converter_replaces_degenerate_uvs(tmp_path):
    # The fixture's pod triangle carries u=v on a degenerate line; every
    # triangle in the output must have non-zero UV area or MikkTSpace
    # corrupts the whole asset (measured: the 747 body did not render).
    convert(_write_config(tmp_path), tmp_path / "out", REPO)
    text = (tmp_path / "out" / "testcraft" / "aileron_l.obj").read_text()
    uvs, faces = [], []
    for line in text.splitlines():
        if line.startswith("vt "):
            uvs.append(tuple(float(v) for v in line.split()[1:3]))
        elif line.startswith("f "):
            faces.append([int(t.split("/")[1]) - 1 for t in line.split()[1:]])
    for face in faces:
        (u0, v0), (u1, v1), (u2, v2) = (uvs[i] for i in face)
        area = abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0))
        assert area > 1e-9


# -- GLO-30 ingestion and verification -----------------------------------

def _synthetic_tile(tmp_path, name, lat0, lon0, offset=0.0):
    # A 0.2 x 0.2 degree tile at ~30 m-ish posting with one smooth mountain.
    n = 240
    lats = np.linspace(lat0 + 0.2, lat0, n)
    lons = np.linspace(lon0, lon0 + 0.2, n)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    peak_lat, peak_lon = lat0 + 0.1, lon0 + 0.1
    distance = np.hypot((lat_grid - peak_lat) * 111e3,
                        (lon_grid - peak_lon) * 78e3)
    z = 800.0 + 2200.0 * np.exp(-(distance / 6500.0) ** 2) + offset
    return write_geotiff(tmp_path / name, z.astype(np.float32), "EPSG:4326",
                         lon0, lat0 + 0.2, 0.2 / n)


def _synthetic_location():
    return Location(
        key="testpeak", title="synthetic test peak",
        tiles=("X",), bbox=(45.82, 45.98, 7.02, 7.18), crs="EPSG:32632",
        origin_lat=45.9, origin_lon=7.1, snowline_m=2500.0,
        summits=(("Test Peak", 45.9, 7.1, 3000.0),),
    )


def test_glo30_locations_are_well_formed():
    for location in LOCATIONS.values():
        lat_min, lat_max, lon_min, lon_max = location.bbox
        assert lat_min < location.origin_lat < lat_max
        assert lon_min < location.origin_lon < lon_max
        assert location.crs.startswith("EPSG:")
        assert location.tiles and location.summits


def test_ingested_tile_verifies_against_its_source(tmp_path):
    tile = _synthetic_tile(tmp_path, "tile.tif", 45.8, 7.0)
    mosaic = merge_and_crop([tile], (45.82, 45.98, 7.02, 7.18),
                            tmp_path / "mosaic.tif")
    baked = dem.ingest(mosaic, target_crs="EPSG:32632",
                       ground_sample_distance_m=90.0, name="testpeak")
    report = verify_against_source(baked, mosaic, samples=150)
    assert report["ok"], report
    summits = check_summits(baked, _synthetic_location())
    assert summits[0]["ok"], summits


def test_verification_catches_a_datum_shift(tmp_path):
    # A raster 120 m off its source is a broken bake, not a resampling
    # artefact; the verifier must say so.
    tile = _synthetic_tile(tmp_path, "tile.tif", 45.8, 7.0)
    mosaic = merge_and_crop([tile], (45.82, 45.98, 7.02, 7.18),
                            tmp_path / "mosaic.tif")
    baked = dem.ingest(mosaic, target_crs="EPSG:32632",
                       ground_sample_distance_m=90.0, name="testpeak")
    shifted = Heightfield.from_elevations(
        baked.elevations() + 120.0, baked.georeference, name="shifted")
    report = verify_against_source(shifted, mosaic, samples=150)
    assert not report["ok"]


def test_summit_check_catches_the_wrong_mountain(tmp_path):
    tile = _synthetic_tile(tmp_path, "tile.tif", 45.8, 7.0)
    mosaic = merge_and_crop([tile], (45.82, 45.98, 7.02, 7.18),
                            tmp_path / "mosaic.tif")
    baked = dem.ingest(mosaic, target_crs="EPSG:32632",
                       ground_sample_distance_m=90.0, name="testpeak")
    wrong = Location(
        key="wrong", title="wrong", tiles=("X",),
        bbox=(45.82, 45.98, 7.02, 7.18), crs="EPSG:32632",
        origin_lat=45.9, origin_lon=7.1, snowline_m=2500.0,
        summits=(("Imaginary 4k", 45.84, 7.04, 4200.0),),
    )
    assert not all(s["ok"] for s in check_summits(baked, wrong))


def test_orographic_card_block_carries_computed_parameters(tmp_path):
    tile = _synthetic_tile(tmp_path, "tile.tif", 45.8, 7.0)
    mosaic = merge_and_crop([tile], (45.82, 45.98, 7.02, 7.18),
                            tmp_path / "mosaic.tif")
    baked = dem.ingest(mosaic, target_crs="EPSG:32632",
                       ground_sample_distance_m=90.0, name="testpeak")
    baked.write(tmp_path / "baked")
    block = orographic_card_block(tmp_path / "baked", 45.9, 7.1, 25.0, 270.0)
    width_m, _ = baked.extent_m
    assert block["wavelength_m"] == pytest.approx(max(width_m / 8.0, 200.0))
    expected_decay = min(max(block["wavelength_m"] / (2 * math.pi), 80.0), 1500.0)
    assert block["decay_height_m"] == pytest.approx(expected_decay)
    assert block["wind_speed_mps"] == pytest.approx(25.0 * 1852.0 / 3600.0)
    # The origin must project INTO the raster.
    assert baked.contains(block["origin_x_m"], block["origin_y_m"])


# -- the run card's Phase 6B fields --------------------------------------

def test_turbulent_card_carries_the_providers_exact_writes(tmp_path):
    spec = reference_spec("fly the 747 at 3000 m and 250 kt for 30 seconds")
    spec.set("turbulence", "moderate", frm="test")
    spec.set("seed", 777, frm="test")
    card = json.loads(write_run_card(spec, tmp_path / "card.json").read_text())
    assert card["turbulence_properties"] == \
        DrydenTurbulence("moderate", seed=777).configure()


def test_calm_card_is_unchanged_by_the_new_fields(tmp_path):
    spec = reference_spec("fly the 747 at 3000 m and 250 kt for 30 seconds")
    card = json.loads(write_run_card(spec, tmp_path / "card.json").read_text())
    assert "turbulence_properties" not in card
    assert "wind_schedule" not in card
    assert "orographic" not in card


# -- turbulence analysis --------------------------------------------------

def test_turbulence_null_test_requires_a_real_rise():
    calm = [1.0 + 0.0002 * math.sin(i / 7) for i in range(400)]
    turbulent = [1.0 + 0.08 * math.sin(i / 3) for i in range(400)]
    assert null_test(calm, turbulent)["ok"]
    # A "turbulent" run indistinguishable from calm must fail the guard --
    # that is precisely a §1.6 condition that never reached the FDM.
    assert not null_test(calm, calm)["ok"]


def test_same_seed_comparison_verdicts():
    t = [i * 0.1 for i in range(200)]
    nz = [1.0 + 0.05 * math.sin(i / 5) for i in range(200)]
    assert compare_realisations(nz, t, list(nz), list(t))["matches"]
    other = [v + 0.2 * math.sin(i / 3) for i, v in enumerate(nz)]
    assert not compare_realisations(nz, t, other, t)["matches"]


# -- the orographic port check -------------------------------------------

def _orographic_fixture(tmp_path):
    n = 200
    x = np.linspace(0, 6000, n)
    z = 600 + 350 * np.sin(2 * math.pi * x / 3000.0)
    grid = np.tile(z, (n, 1)).T   # a north-south sinusoidal ridge field
    from core.terrain.heightfield import Georeference
    baked = Heightfield.from_elevations(
        grid, Georeference(crs="EPSG:32632", origin_x_m=400000.0,
                           origin_y_m=5100000.0, pixel_size_m=30.0),
        name="ridge")
    baked.write(tmp_path / "ridge")
    block = {
        "terrain": str(tmp_path / "ridge"),
        "wind_speed_mps": 12.0, "wind_from_deg": 0.0,
        "decay_height_m": 500.0, "wavelength_m": 3000.0,
        "origin_x_m": 400000.0 + 3000.0, "origin_y_m": 5100000.0 - 3000.0,
        "lee": True,
    }
    provider = OrographicWind(
        terrain_field_at(baked, block["origin_x_m"], block["origin_y_m"],
                         wavelength_m=block["wavelength_m"]),
        wind_speed_mps=block["wind_speed_mps"],
        wind_from_deg=block["wind_from_deg"],
        decay_height_m=block["decay_height_m"], enable_lee=True)
    field = terrain_field_at(baked, block["origin_x_m"], block["origin_y_m"],
                             wavelength_m=block["wavelength_m"])
    samples = []
    for north in (-900.0, 0.0, 900.0):
        for east in (-900.0, 0.0, 900.0):
            agl = 300.0
            w = -((provider.linear_updraught(north, east)
                   - provider.lee_sink(north, east)) * provider.decay(agl))
            samples.append({"north_m": north, "east_m": east, "agl_m": agl,
                            "elevation_m": field.elevation_m(north, east),
                            "wind_down_mps": w})
    manifest = {"environment": {"orographic_selftest": samples}}
    return manifest, {"orographic": block}


def test_orographic_port_check_accepts_the_original(tmp_path):
    manifest, card = _orographic_fixture(tmp_path)
    assert verify_port(manifest, card)["ok"]


def test_orographic_port_check_catches_a_drifted_port(tmp_path):
    # A port whose lee gain or decay drifted produces different numbers at
    # the same points; the comparison must fail, not shrug.
    manifest, card = _orographic_fixture(tmp_path)
    manifest["environment"]["orographic_selftest"][4]["wind_down_mps"] += 0.05
    assert not verify_port(manifest, card)["ok"]


# -- the condition matrix's honesty labels -------------------------------

def _fake_terrain(tmp_path, base_elevation_m=500.0, rms_slope_deg=20.0):
    from core.terrain.synthesis import TerrainStatistics, generate
    field = generate(size=96, pixel_size_m=30.0,
                     statistics=TerrainStatistics(rms_slope_deg=rms_slope_deg),
                     seed=3, base_elevation_m=base_elevation_m, name="cellridge")
    field.write(tmp_path / "cellridge")
    from pyproj import Transformer
    inverse = Transformer.from_crs(field.georeference.crs, "EPSG:4326",
                                   always_xy=True)
    min_x, min_y, max_x, max_y = field.bounds_m()
    lon, lat = inverse.transform((min_x + max_x) / 2, (min_y + max_y) / 2)
    return {
        "path": tmp_path / "cellridge", "kind": "synthetic",
        "lat": float(lat), "lon": float(lon), "heading": 45.0,
        "ground_m": 500.0, "tiles": {}, "sha256": field.digest(),
        "title": "cell test ridge",
    }


def test_turbulent_cell_is_hands_off_with_recorded_seed(tmp_path):
    terrain = _fake_terrain(tmp_path)
    cell = build_cell_card(tmp_path / "card.json", "c172p", "control",
                           terrain, "turb_moderate", 63123)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["turbulence"] == "moderate"
    assert card["turbulence_properties"]["atmosphere/randomseed"] == 63123.0
    assert card["control_inputs"] == []
    assert "orographic" not in card
    assert cell["turbulence_seed"] == 63123
    assert "visual-only" in cell["wind_note"]


def test_gusty_cell_carries_schedule_and_orographic(tmp_path):
    terrain = _fake_terrain(tmp_path)
    build_cell_card(tmp_path / "card.json", "B747", "control",
                    terrain, "gusty15", 63124)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["wind_speed_kt"] == 15.0
    assert card["wind_direction_deg"] == 45.0     # headwind = heading
    assert len(card["wind_schedule"]) > 1000
    assert card["orographic"]["wind_from_deg"] == 45.0
    assert card["control_inputs"] == []


def test_crosswind_cell_wind_is_heading_plus_ninety(tmp_path):
    terrain = _fake_terrain(tmp_path)
    build_cell_card(tmp_path / "card.json", "B747", "control",
                    terrain, "crosswind25", 63125)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["wind_speed_kt"] == 25.0
    assert card["wind_direction_deg"] == 135.0
    assert card["orographic"]["wind_speed_mps"] == \
        pytest.approx(25.0 * 1852.0 / 3600.0)


def test_combined_cell_carries_every_constituent(tmp_path):
    # crosswind25_turb: steady wind + orographic + Dryden, one card. Each
    # constituent is the machinery already null-tested alone; the honesty
    # labels must survive the combination.
    terrain = _fake_terrain(tmp_path)
    cell = build_cell_card(tmp_path / "card.json", "B747", "control",
                           terrain, "crosswind25_turb", 63200)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["wind_speed_kt"] == 25.0
    assert card["wind_direction_deg"] == 135.0
    assert card["turbulence"] == "moderate"
    assert card["turbulence_properties"]["atmosphere/randomseed"] == 63200.0
    assert "orographic" in card
    assert card["control_inputs"] == []
    assert "visual-only" in cell["wind_note"]


def test_storm_cell_gusts_harder_and_is_severe(tmp_path):
    terrain = _fake_terrain(tmp_path)
    cell = build_cell_card(tmp_path / "card.json", "B747", "control",
                           terrain, "storm25", 63201)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["turbulence"] == "severe"
    assert card["wind_speed_kt"] == 25.0
    assert len(card["wind_schedule"]) > 1000
    assert "orographic" in card
    # The storm's surges must exceed the plain gusty cell's.
    from core.fdm import units as u
    storm_peak = max(math.hypot(r["north_fps"], r["east_fps"])
                     for r in card["wind_schedule"])
    assert storm_peak > u.mps_to_fps(u.kt_to_mps(25.0 + 15.0))
    assert "storm" in cell["wind_note"]


def test_microburst_cell_stages_the_reversal(tmp_path):
    # The classic encounter, checkable from the card alone: low altitude,
    # headwind component surging before the core, tailwind after it, the
    # downdraft peaking near the crossing time, and the honesty label on the
    # note. The field itself is verified in test_downburst; this test checks
    # the STAGING.
    # Gentle terrain: the staging is under test here, not the clearance
    # refusal (that has its own test below).
    terrain = _fake_terrain(tmp_path, rms_slope_deg=5.0)
    cell = build_cell_card(tmp_path / "card.json", "B747", "control",
                           terrain, "microburst", 63300)
    card = json.loads((tmp_path / "card.json").read_text())
    assert card["altitude_m"] == terrain["ground_m"] + 300.0
    assert card["wind_speed_kt"] == 10.0
    assert "orographic" in card
    assert card["control_inputs"] == []
    schedule = card["wind_schedule"]

    import math as m
    heading = m.radians(card["heading_deg"])
    along = [r["north_fps"] * m.cos(heading) + r["east_fps"] * m.sin(heading)
             for r in schedule]
    downs = [r["down_fps"] for r in schedule]
    times = [r["t_s"] for r in schedule]
    # Along-track wind: more negative than ambient alone before the core
    # (headwind blows against the track), positive after it.
    encounter = 11.0
    before = min(a for a, t in zip(along, times) if t < encounter)
    after = max(a for a, t in zip(along, times) if t > encounter)
    assert before < -20.0          # ambient ~-17 fps plus the outflow
    assert after > 5.0             # tailwind despite the ambient headwind
    # Downdraft peaks near the crossing, not at the edges.
    peak_time = times[downs.index(max(downs))]
    assert abs(peak_time - encounter) < 3.0
    assert max(downs) > 20.0       # a real sink, in fps
    assert "NOMINAL track" in cell["wind_note"]


def test_microburst_track_refuses_a_wall(tmp_path):
    # A terrain the flight cannot clear at 300 m AGL in any direction must
    # refuse the cell rather than render an aircraft inside a mountainside.
    # Raise every elevation ~2.3 km above the declared origin ground.
    terrain = _fake_terrain(tmp_path, base_elevation_m=2800.0)
    with pytest.raises(CellUnrenderable):
        microburst_track(terrain, terrain["ground_m"] + 300.0, 128.0)


def test_gust_schedule_reduces_to_steady_wind_between_gusts():
    from core.fdm import units as u

    schedule = gust_schedule(90.0, 15.0, 120.0, 22.0, airspeed_mps=120.0)
    assert [row["t_s"] for row in schedule] == \
        sorted(row["t_s"] for row in schedule)
    steady_fps = u.mps_to_fps(u.kt_to_mps(15.0))
    first = schedule[0]
    # Heading 90: a headwind blows FROM the east, so north ~ 0, east ~ -15 kt.
    assert first["north_fps"] == pytest.approx(0.0, abs=1e-9)
    assert first["east_fps"] == pytest.approx(-steady_fps)
    assert first["down_fps"] == 0.0
    # Mid-gust the speed rises above steady; the vertical gust peaks at 3 m/s.
    surge = max(-row["east_fps"] for row in schedule)
    assert surge > steady_fps * 1.5
    assert max(row["down_fps"] for row in schedule) == \
        pytest.approx(u.mps_to_fps(3.0), rel=1e-6)
