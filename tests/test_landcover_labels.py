"""W4: land-cover labels per frame and the aggregate objects.

A synthetic bake (UTM 11 N, 40 x 40 cells of 30 m) carries a synthetic
WorldCover class map written by hand: a forest strip along the north
edge, a 4-cell checkerboard of tree cover / grassland / built-up / water
below it, and a nodata column on the east edge. A nadir camera 300 m up
sees it through a fabricated depth (the ground plane: planar depth 300 m
everywhere), so the class under each pixel is known in closed form and
the land-cover image is compared EXACTLY; the engine's land-cover ID pass
(W5, a Windows step) is fabricated as the image itself (agreement 1) and
shifted (agreement falls); the verifier's own unprojection passes the
fixture and fails a shifted image, a changed class map and a code off the
legend, by name. No engine exists in this container and none is claimed.
"""

import copy
import hashlib
import json
import math

import numpy as np
import pytest
from PIL import Image

from core.capture.labels import (
    AGGREGATE_RECORDS, LANDCOVER_AGREEMENT_MIN, LANDCOVER_SUFFIX, LandcoverLabelError,
    aggregate_from_landcover, attach_engine_labels, camera_axes, landcover_agreement,
    landcover_class_from_depth, landcover_fractions, manifest_landcover_block,
)
from core.capture.manifest import read_capture_manifest, write_capture_manifest
from core.terrain.heightfield import Georeference, Heightfield
from core.terrain.landcover import LEGEND, scene_dir_for

CRS = "EPSG:32611"
GX, GY = 500000.0, 4200000.0          # the bake's upper-left corner
CELL = 30.0
N = 40
GROUND = 1000.0
ALTITUDE = GROUND + 300.0
W = H = 64
F = 64.0                               # a 90 degree field: 4.6875 m per pixel at 300 m
FOREST, GRASS, BUILT, WATER = 10, 30, 50, 80
CHECKER = (FOREST, GRASS, BUILT, WATER)
FOREST_ROWS = 12
#: The scene frame's projected origin: the bake's centre.
OX, OY = GX + N * CELL / 2.0, GY - N * CELL / 2.0


# -- fixtures -------------------------------------------------------------------

def class_grid() -> np.ndarray:
    rows, cols = np.mgrid[0:N, 0:N]
    grid = np.array(CHECKER, dtype=np.uint8)[((rows // 4) + (cols // 4)) % 4]
    grid[:FOREST_ROWS, :] = FOREST
    grid[:, N - 1] = 0                                    # a nodata column
    return grid


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_world(directory):
    """The synthetic bake and its land cover in landcover.json's shape."""
    field = Heightfield.from_elevations(np.full((N, N), GROUND), Georeference(CRS, GX, GY, CELL),
                                        name="lcbake", provenance={"synthetic": True})
    stem = field.write(directory / "lcbake").with_suffix("")
    scene_dir = scene_dir_for(stem)
    scene_dir.mkdir(parents=True, exist_ok=True)
    grid = class_grid()
    Image.fromarray(grid).save(scene_dir / "class_map.png")
    fractions = {c.key: float(np.count_nonzero(grid == c.code)) / grid.size for c in LEGEND}
    document = {
        "dataset": "ESA WorldCover 10 m 2021 v200 (synthetic fixture)",
        "license": "CC BY 4.0",
        "attribution": "(c) ESA WorldCover project 2021 / Contains modified Copernicus "
                       "Sentinel data (2021) processed by ESA WorldCover consortium",
        "citation": "synthetic", "sha256": "0" * 64,
        "source": {"tiles": {}, "crop": {"file": "synthetic", "note": "written by hand"}},
        "class_map": {"file": "class_map.png", "sha256": _sha(scene_dir / "class_map.png"),
                      "encoding": "legend code per bake cell; 0 = nodata"},
        "grid": {"crs": CRS, "origin_x_m": GX, "origin_y_m": GY, "cell_size_m": CELL,
                 "width": N, "height": N, "bake_sha256": field.digest()},
        "fractions": fractions,
        "dominant_class": max(fractions, key=fractions.get),
    }
    path = scene_dir / "landcover.json"
    path.write_text(json.dumps(document, indent=1), encoding="utf-8")
    return stem, path, grid


def nadir(north, east, alt=ALTITUDE):
    half = math.radians(-90.0) / 2.0
    return {"camera_id": "nadir", "index": 0, "file": "frames/nadir/frame_0000.png",
            "position_north_m": float(north), "position_east_m": float(east),
            "position_alt_m": float(alt),
            "quaternion_wxyz": [math.cos(half), 0.0, math.sin(half), 0.0],
            "principal_point_px": [W / 2.0, H / 2.0], "fx_px": F, "fy_px": F,
            "width_px": W, "height_px": H}


def expected_image(record, depth, grid, exclude=None):
    """The class under each pixel in closed form for a north-up nadir
    camera: east = (u + 0.5 - cx) / f * z, north = -(v + 0.5 - cy) / f * z."""
    out = np.zeros((H, W), dtype=np.uint8)
    for v in range(H):
        for u in range(W):
            z = float(depth[v, u])
            if not math.isfinite(z) or z <= 0.0 or (exclude is not None and exclude[v, u]):
                continue
            east = record["position_east_m"] + (u + 0.5 - W / 2.0) / F * z
            north = record["position_north_m"] - (v + 0.5 - H / 2.0) / F * z
            col = math.floor((OX + east - GX) / CELL)
            row = math.floor((GY - (OY + north)) / CELL)
            if 0 <= col < N and 0 <= row < N:
                out[v, u] = grid[row, col]
    return out


GRID = {"origin_x_m": GX, "origin_y_m": GY, "cell_size_m": CELL, "width": N, "height": N}


# -- the image, exactly -------------------------------------------------------------

def test_the_nadir_camera_is_north_up_as_the_closed_form_assumes():
    forward, right, up = camera_axes(nadir(0.0, 0.0)["quaternion_wxyz"])
    assert np.allclose(forward, (0.0, 0.0, -1.0), atol=1e-12)
    assert np.allclose(right, (0.0, 1.0, 0.0), atol=1e-12)
    assert np.allclose(up, (1.0, 0.0, 0.0), atol=1e-12)


def test_the_image_is_the_class_grid_under_each_pixel_with_nodata_for_sky_off_bake_and_aircraft():
    grid = class_grid()
    # Over the checkerboard, well inside the bake.
    record = nadir(-300.0, 300.0)
    depth = np.full((H, W), 300.0)
    image = landcover_class_from_depth(depth, record, GRID, grid, (OX, OY))
    assert image.dtype == np.uint8 and image.shape == (H, W)
    assert np.array_equal(image, expected_image(record, depth, grid))
    assert set(np.unique(image)) == set(CHECKER)                        # all four in view
    # Sky rows, an aircraft rectangle: nodata.
    depth[:5, :] = np.inf
    depth[5:7, :] = 0.0
    aircraft = np.zeros((H, W), dtype=bool)
    aircraft[30:40, 20:44] = True
    image = landcover_class_from_depth(depth, record, GRID, grid, (OX, OY), exclude=aircraft)
    assert np.array_equal(image, expected_image(record, depth, grid, aircraft))
    assert not image[:7].any() and not image[aircraft].any() and image[7:30].all()
    # At the east edge: the nodata column and the cells off the bake read 0.
    edge = nadir(-300.0, 560.0)
    depth = np.full((H, W), 300.0)
    image = landcover_class_from_depth(depth, edge, GRID, grid, (OX, OY))
    assert np.array_equal(image, expected_image(edge, depth, grid))
    east_of = (OX + 560.0 + (np.arange(W) + 0.5 - W / 2.0) / F * 300.0 - GX) / CELL
    assert not image[:, east_of >= N - 1].any() and image[:, east_of < N - 1].all()


def test_fractions_in_view_and_a_frame_over_forest_reads_forest():
    grid = class_grid()
    depth = np.full((H, W), 300.0)
    forest = landcover_fractions(landcover_class_from_depth(
        depth, nadir(450.0, -200.0), GRID, grid, (OX, OY)))
    assert forest["dominant"] == "tree_cover" and forest["fractions"]["tree_cover"] == 1.0
    assert forest["taxonomy_fractions"]["vegetation"] == 1.0 and forest["nodata_fraction"] == 0.0
    mixed = landcover_fractions(landcover_class_from_depth(
        depth, nadir(-300.0, 560.0), GRID, grid, (OX, OY)))
    assert 0.0 < mixed["nodata_fraction"] < 1.0
    assert sum(mixed["fractions"].values()) + mixed["nodata_fraction"] == pytest.approx(1.0)
    assert sum(mixed["taxonomy_fractions"].values()) + mixed["nodata_fraction"] == pytest.approx(1.0)
    assert mixed["taxonomy_fractions"]["building"] == mixed["fractions"]["built_up"]
    assert mixed["taxonomy_fractions"]["water"] == mixed["fractions"]["permanent_water"]
    assert mixed["dominant"] in {"tree_cover", "grassland", "built_up", "permanent_water"}
    # Nothing labelled: no dominant class. A code off the legend refuses by name.
    assert landcover_fractions(np.zeros((4, 4), np.uint8))["dominant"] is None
    with pytest.raises(LandcoverLabelError) as caught:
        landcover_fractions(np.full((4, 4), 7, np.uint8))
    assert caught.value.constraint == "annotation.landcover"


def test_the_engine_agreement_is_exact_on_itself_and_falls_when_shifted():
    grid = class_grid()
    image = landcover_class_from_depth(np.full((H, W), 300.0), nadir(-300.0, 300.0), GRID,
                                       grid, (OX, OY))
    same = landcover_agreement(image, image.copy())
    assert same["agreement"] == 1.0 and same["ok"] and same["compared"] == W * H
    shifted = landcover_agreement(image, np.roll(image, 7, axis=1))
    assert shifted["agreement"] < LANDCOVER_AGREEMENT_MIN and shifted["ok"] is False
    blank = landcover_agreement(image, np.zeros_like(image))     # an engine 0 is disagreement
    assert blank["agreement"] == 0.0


# -- the aggregate objects ----------------------------------------------------------

def spec_for():
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    spec.set("hold_state", False, frm="test")
    return spec


def test_the_aggregates_are_one_id_each_after_the_terrain_and_stable():
    from core.capture.objects import (
        AGGREGATE_CLASSES, aggregate_objects, compose_objects, objects_block,
    )

    spec = spec_for()
    plain = compose_objects(spec)
    objects = compose_objects(spec, landcover=True)
    assert [o.id for o in plain] == ["aircraft:c172p:0", "terrain"]
    assert [o.id for o in objects] == ["aircraft:c172p:0", "terrain", "building:all",
                                       "vegetation:all"]
    assert [o.int_id for o in objects] == [1, 2, 3, 4]
    assert objects_block(objects[:2]) == objects_block(plain)          # earlier ids unmoved
    assert objects_block(compose_objects(spec, landcover=True)) == objects_block(objects)
    classes = list(spec.taxonomy.classes.value)
    for obj in objects[2:]:
        assert obj.class_name == AGGREGATE_CLASSES[obj.id] and obj.role == "scene"
        assert obj.class_id == classes.index(obj.class_name) + 1 and obj.instance == 0
    assert [o["id"] for o in aggregate_objects(objects)] == ["building:all", "vegetation:all"]
    # A trimmed taxonomy composes only what it names, and refuses nothing.
    spec.set("taxonomy.classes", ["aircraft", "terrain", "vegetation"], frm="test")
    assert [o.id for o in compose_objects(spec, landcover=True)][2:] == ["vegetation:all"]
    spec.set("taxonomy.classes", ["aircraft", "terrain"], frm="test")
    assert [o.id for o in compose_objects(spec, landcover=True)] == ["aircraft:c172p:0", "terrain"]


def test_the_aggregate_record_names_its_codes_and_the_stencil_limit():
    from core.capture.labels import object_label_record
    from core.capture.objects import compose_objects
    from core.terrain.weightmaps import CLASS_OF_COVER

    objects = {o.id: o for o in compose_objects(spec_for(), landcover=True)}
    record = nadir(0.0, 0.0)
    axes = camera_axes(record["quaternion_wxyz"])
    for object_id, word in (("vegetation:all", "vegetation"), ("building:all", "building")):
        entry = object_label_record(objects[object_id], record, None, None, axes, GROUND)
        aggregate = entry["aggregate"]
        assert aggregate["codes"] == sorted(c for c, w in CLASS_OF_COVER.items() if w == word)
        assert aggregate["per_instance_ids"].startswith("none")
        assert "8-bit" in aggregate["per_instance_ids"]
    assert entry["bbox_2d"] is None and entry["bbox_2d_tight"] is None
    terrain = object_label_record(objects["terrain"], record, None, None, axes, GROUND)
    assert "aggregate" not in terrain
    assert set(AGGREGATE_RECORDS) == {"building:all", "vegetation:all"}
    image = np.zeros((6, 8), np.uint8)
    image[1:3, 2:5] = 10
    image[4, 7] = 95
    image[5, 0] = 50
    vegetation = aggregate_from_landcover(image, [10, 20, 95])
    assert vegetation == {"landcover_bbox_2d": [2.0, 1.0, 8.0, 5.0], "landcover_pixels": 7,
                          "landcover_fraction": 7 / 48}
    assert aggregate_from_landcover(image, [50])["landcover_bbox_2d"] == [0.0, 5.0, 1.0, 6.0]
    assert aggregate_from_landcover(image, [80])["landcover_bbox_2d"] is None


# -- the bundle: attach, the manifest block, the record ------------------------------

OBJECTS = [
    {"id": "aircraft:c172p:0", "int_id": 1, "class": "aircraft", "class_id": 1, "role": "primary"},
    {"id": "terrain", "int_id": 2, "class": "terrain", "class_id": 2, "role": "scene"},
    {"id": "building:all", "int_id": 3, "class": "building", "class_id": 3, "role": "scene"},
    {"id": "vegetation:all", "int_id": 4, "class": "vegetation", "class_id": 4, "role": "scene"},
]
AIRCRAFT_RECT = (slice(28, 36), slice(28, 36))


def make_run(tmp_path, record, engine=None):
    """A run directory: the hand-built manifest (the landcover block from
    the synthetic document) and the fabricated bundle -- an ID image
    (terrain, an aircraft rectangle), the ground-plane depth (the
    aircraft 150 m nearer), optionally the engine's land-cover pass."""
    stem, document, grid = write_world(tmp_path)
    run_dir = tmp_path / "run"
    folder = run_dir / "frames" / "nadir"
    folder.mkdir(parents=True)
    frame = dict(record, labels={"objects": [
        {"id": o["id"], "int_id": o["int_id"], "class_id": o["class_id"]} for o in OBJECTS]})
    manifest = {"manifest_version": 6,
                "frame": {"crs": CRS, "origin_x_m": OX, "origin_y_m": OY},
                "objects": copy.deepcopy(OBJECTS), "frames": [frame],
                "landcover": manifest_landcover_block(document)}
    write_capture_manifest(manifest, run_dir)
    mask = np.full((H, W), 2, dtype=np.uint8)
    mask[AIRCRAFT_RECT] = 1
    depth = np.full((H, W), 300.0, dtype=np.float32)
    depth[AIRCRAFT_RECT] = 150.0
    Image.fromarray(mask).save(folder / "frame_0000_mask.png")
    depth.astype("<f4").tofile(folder / "frame_0000_depth.f32")
    labels = {"mask": "frame_0000_mask.png", "depth_f32": "frame_0000_depth.f32", "objects": []}
    if engine is not None:
        Image.fromarray(engine).save(folder / "frame_0000_landcover_id.png")
        labels["landcover_png"] = "frame_0000_landcover_id.png"
    (folder / "render.json").write_text(json.dumps(
        {"frames": 1, "frame_records": [{"frame": "frame_0000.png", "labels": labels}]}),
        encoding="utf-8")
    return run_dir, grid, depth, mask


def own_image(record, grid, depth, mask):
    return landcover_class_from_depth(depth, record, GRID, grid, (OX, OY), exclude=mask == 1)


def test_the_manifest_block_carries_the_legend_the_class_map_and_the_grid(tmp_path):
    stem, document, grid = write_world(tmp_path)
    block = manifest_landcover_block(document)
    assert manifest_landcover_block(None) is None
    assert manifest_landcover_block(tmp_path / "absent.json") is None
    legend = {entry["code"]: entry for entry in block["legend"]}
    assert set(legend) == {0} | {c.code for c in LEGEND}
    assert legend[0]["key"] == "nodata" and legend[0]["taxonomy"] is None
    assert legend[10]["taxonomy"] == "vegetation" and legend[50]["taxonomy"] == "building"
    assert legend[80]["taxonomy"] == "water" and legend[30]["taxonomy"] == "terrain"
    assert block["nodata"] == 0 and block["image"]["suffix"] == LANDCOVER_SUFFIX
    assert block["class_map"]["sha256"] == _sha(scene_dir_for(stem) / "class_map.png")
    assert block["grid"]["crs"] == CRS and block["grid"]["width"] == N
    assert block["document_sha256"] == _sha(document)
    assert block["aggregates"] == {"building:all": [50], "vegetation:all": [10, 20, 95]}
    assert block["engine_pass"]["key"] == "landcover_png"
    assert any("W5" in line for line in block["not_claimed"])


def test_attach_writes_the_image_the_fractions_the_aggregates_and_the_record(tmp_path):
    record = nadir(-300.0, 300.0)
    run_dir, grid, depth, mask = make_run(tmp_path, record)
    summary = attach_engine_labels(run_dir)
    assert summary["landcover"] == {"frames": 1, "agreements": 0}
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    frame = manifest["frames"][0]
    block = frame["labels"]["landcover"]
    path = run_dir / "frames" / "nadir" / block["file"]
    assert block["file"] == "frame_0000" + LANDCOVER_SUFFIX and block["sha256"] == _sha(path)
    written = np.asarray(Image.open(path))
    expected = own_image(record, grid, depth.astype(np.float64), mask)
    assert np.array_equal(written, expected)
    assert np.array_equal(written, expected_image(record, depth, grid, mask == 1))
    assert not written[AIRCRAFT_RECT].any()                     # an airframe is not ground cover
    assert block["nodata_fraction"] == pytest.approx(64 / (W * H))
    assert block["agreement"] is None and "W5" in block["agreement_basis"]
    objects = {o["id"]: o for o in frame["labels"]["objects"]}
    for object_id, codes in (("vegetation:all", [10, 20, 95]), ("building:all", [50])):
        hit = np.isin(written, codes)
        ys, xs = np.nonzero(hit)
        assert objects[object_id]["landcover_bbox_2d"] == [
            float(xs.min()), float(ys.min()), float(xs.max()) + 1.0, float(ys.max()) + 1.0]
        assert objects[object_id]["landcover_pixels"] == int(hit.sum())
        assert objects[object_id]["landcover_mask"]["codes"] == codes
    assert "landcover_bbox_2d" not in objects["terrain"]
    (lc,) = [r for r in manifest["applied_variables"]["applied_variables"]
             if r["name"] == "labels.landcover"]
    assert lc["source"] == "derived" and lc["parameters"]["frames"] == 1
    assert lc["parameters"]["bake_dominant"] == "tree_cover"
    null = lc["null_test"]
    # The frame sees the checkerboard: most of it is NOT the bake's forest.
    assert null["without"] == 0.0 and null["with"] > 0.5 and null["ok"] is True
    # Attaching again changes nothing.
    attach_engine_labels(run_dir)
    assert read_capture_manifest(run_dir / "capture_manifest.json") == manifest


def test_the_engine_pass_agreement_is_recorded_when_the_bundle_declares_it(tmp_path):
    record = nadir(-300.0, 300.0)
    grid = class_grid()
    mask = np.full((H, W), 2, np.uint8)
    mask[AIRCRAFT_RECT] = 1
    depth = np.full((H, W), 300.0)
    depth[AIRCRAFT_RECT] = 150.0
    image = own_image(record, grid, depth, mask)
    run_dir, *_ = make_run(tmp_path / "same", record, engine=image)
    attach_engine_labels(run_dir)
    block = read_capture_manifest(run_dir / "capture_manifest.json")["frames"][0]["labels"]["landcover"]
    assert block["agreement"]["agreement"] == 1.0 and block["agreement"]["ok"] is True
    run_dir, *_ = make_run(tmp_path / "shifted", record, engine=np.roll(image, 7, axis=1))
    attach_engine_labels(run_dir)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    block = manifest["frames"][0]["labels"]["landcover"]
    assert block["agreement"]["agreement"] < LANDCOVER_AGREEMENT_MIN
    assert block["agreement"]["ok"] is False
    (lc,) = [r for r in manifest["applied_variables"]["applied_variables"]
             if r["name"] == "labels.landcover"]
    assert lc["parameters"]["agreement"]["min"] < LANDCOVER_AGREEMENT_MIN


def test_a_changed_class_map_refuses_by_name_in_the_frame_record(tmp_path):
    record = nadir(-300.0, 300.0)
    run_dir, grid, *_ = make_run(tmp_path, record)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    class_map = manifest["landcover"]["class_map"]["file"]
    changed = grid.copy()
    changed[20, 20] = WATER if changed[20, 20] != WATER else GRASS
    Image.fromarray(changed).save(class_map)
    summary = attach_engine_labels(run_dir)
    assert summary["landcover"]["refused"] == "annotation.landcover"
    frame = read_capture_manifest(run_dir / "capture_manifest.json")["frames"][0]
    assert frame["labels"]["landcover"]["refused"] == "annotation.landcover"
    assert "sha256" in frame["labels"]["landcover"]["reason"]


# -- the verifier: landcover_vs_geometry ------------------------------------------------

def _restate(run_dir, manifest, image):
    path = run_dir / "frames" / "nadir" / manifest["frames"][0]["labels"]["landcover"]["file"]
    Image.fromarray(image).save(path)
    manifest["frames"][0]["labels"]["landcover"]["sha256"] = _sha(path)


def test_landcover_vs_geometry_passes_the_fixture_and_fails_by_name_on_corruption(tmp_path):
    from core.capture.verify import FAIL, PASS, verify_landcover_vs_geometry

    record = nadir(-300.0, 300.0)
    run_dir, grid, *_ = make_run(tmp_path, record)
    attach_engine_labels(run_dir)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    check = verify_landcover_vs_geometry(manifest, run_dir)
    assert check.status == PASS, check.detail
    assert "worst 100.0%" in check.detail and "engine half NOT RUN" in check.detail
    image = np.asarray(Image.open(
        run_dir / "frames" / "nadir" / manifest["frames"][0]["labels"]["landcover"]["file"])).copy()
    # (1) the image shifted 7 px east (its digest re-stated): agreement falls.
    shifted = copy.deepcopy(manifest)
    _restate(run_dir, shifted, np.roll(image, 7, axis=1))
    check = verify_landcover_vs_geometry(shifted, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.landcover_vs_geometry")
    assert "agrees with the checker's own unprojection" in check.detail
    # (2) the image changed after the record named it.
    check = verify_landcover_vs_geometry(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.landcover_vs_geometry")
    assert "sha256" in check.detail
    # (3) a code off the legend.
    stray = copy.deepcopy(manifest)
    bad = image.copy()
    bad[0, 0] = 7
    _restate(run_dir, stray, bad)
    check = verify_landcover_vs_geometry(stray, run_dir)
    assert check.failure == "check.landcover_vs_geometry" and "legend" in check.detail
    # (4) the class map changed after the capture.
    _restate(run_dir, manifest, image)
    assert verify_landcover_vs_geometry(manifest, run_dir).status == PASS
    class_map = manifest["landcover"]["class_map"]["file"]
    Image.fromarray(np.flipud(grid)).save(class_map)
    check = verify_landcover_vs_geometry(manifest, run_dir)
    assert check.failure == "check.landcover_vs_geometry" and "changed after" in check.detail
    # (5) the grid in another CRS than the frame.
    Image.fromarray(grid).save(class_map)
    other = copy.deepcopy(manifest)
    other["landcover"]["grid"]["crs"] = "EPSG:32612"
    assert verify_landcover_vs_geometry(other, run_dir).failure == "check.landcover_vs_geometry"


def test_landcover_vs_geometry_grades_the_engine_pass_where_declared(tmp_path):
    from core.capture.verify import FAIL, PASS, verify_landcover_vs_geometry

    record = nadir(-300.0, 300.0)
    grid = class_grid()
    mask = np.full((H, W), 2, np.uint8)
    mask[AIRCRAFT_RECT] = 1
    depth = np.full((H, W), 300.0)
    depth[AIRCRAFT_RECT] = 150.0
    image = own_image(record, grid, depth, mask)
    run_dir, *_ = make_run(tmp_path / "same", record, engine=image)
    attach_engine_labels(run_dir)
    check = verify_landcover_vs_geometry(
        read_capture_manifest(run_dir / "capture_manifest.json"), run_dir)
    assert check.status == PASS and "engine's land-cover ID pass agrees" in check.detail
    run_dir, *_ = make_run(tmp_path / "shifted", record, engine=np.roll(image, 7, axis=1))
    attach_engine_labels(run_dir)
    check = verify_landcover_vs_geometry(
        read_capture_manifest(run_dir / "capture_manifest.json"), run_dir)
    assert (check.status, check.failure) == (FAIL, "check.landcover_vs_geometry")
    assert "engine's land-cover ID pass" in check.detail


def test_landcover_vs_geometry_is_not_run_without_its_evidence(tmp_path):
    from core.capture.verify import NOT_RUN, verify_landcover_vs_geometry

    record = nadir(-300.0, 300.0)
    run_dir, *_ = make_run(tmp_path, record)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    assert verify_landcover_vs_geometry({k: v for k, v in manifest.items()
                                         if k != "landcover"}, run_dir).status == NOT_RUN
    # A bundle but no land-cover image attached yet: nothing to grade.
    assert verify_landcover_vs_geometry(manifest, run_dir).status == NOT_RUN
    attach_engine_labels(run_dir)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    assert verify_landcover_vs_geometry(manifest, tmp_path / "elsewhere").status == NOT_RUN
    gone = copy.deepcopy(manifest)
    gone["landcover"]["class_map"]["file"] = str(tmp_path / "nowhere" / "class_map.png")
    assert verify_landcover_vs_geometry(gone, run_dir).status == NOT_RUN


# -- the manifest builder: the block, the aggregates, the licences -----------------------

def test_the_manifest_builder_carries_land_cover_only_when_the_scene_has_it(tmp_path):
    from core.capture.manifest import SIDECAR_CONTEXT_KEYS, build_capture_manifest
    from core.capture.poses import solve_pose_track
    from core.capture.schedule import solve_schedule
    from core.scenario.camera import CameraSpec
    from tests.test_camera_poses import FRAME, make_columns

    spec = spec_for()
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase", aircraft="c172p")
    camera.set("capture_count", 2, frm="test")
    spec.cameras = [camera]
    columns = make_columns(duration_s=6.0)
    tracks = [solve_pose_track(columns, camera, FRAME)]
    schedules = [solve_schedule(columns, camera, FRAME)]

    def build(scene):
        return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                      output_digest="0" * 64, scene=scene)

    flat = build({"key": "flat", "terrain": None})
    assert "landcover" not in flat and "licences" not in flat
    assert [o["id"] for o in flat["objects"]] == ["aircraft:c172p:0", "terrain"]
    stem, document, _ = write_world(tmp_path)
    manifest = build({"key": "terrain", "terrain": str(stem)})       # found beside the bake
    assert manifest["landcover"] == manifest_landcover_block(document)
    assert [o["id"] for o in manifest["objects"]] == ["aircraft:c172p:0", "terrain",
                                                      "building:all", "vegetation:all"]
    assert manifest["objects"][:2] == flat["objects"]
    for frame in manifest["frames"]:
        entries = {e["id"]: e for e in frame["labels"]["objects"]}
        assert entries["vegetation:all"]["aggregate"]["codes"] == [10, 20, 95]
        assert "aggregate" not in entries["terrain"]
    licences = {r["kind"]: r for r in manifest["licences"]}
    assert set(licences) == {"terrain", "land_cover"}
    assert licences["land_cover"]["spdx"] == "CC-BY-4.0" and licences["land_cover"]["reaches"] == ["labels"]
    assert licences["terrain"]["spdx"] == "LicenseRef-flightsim-own"
    assert "landcover" in SIDECAR_CONTEXT_KEYS and "licences" in SIDECAR_CONTEXT_KEYS
    # Named explicitly (the runway pad's case: the land cover is the parent's).
    named = build({"key": "terrain", "terrain": None, "landcover_document": str(document)})
    assert named["landcover"] == manifest["landcover"]
