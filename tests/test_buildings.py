"""W2, the buildings (core/scene/buildings.py): a cached footprint set with
its provenance sidecar, refused by name (uncached, licence, unverified,
ids); LoD1 blocks seated on the DTM pad with the height source recorded
and the 6 m default's basis stated; volume = area x height measured on a
fixture; the vintage mismatch measured on the synthetic fixture; the spec
field scene.buildings absent-canonical, the validator's refusals, the
registry entry, building:all in objects[], the manifest's scene.buildings
record, and the verifier's building_vs_footprint on synthetic bundles
(PASS, FAIL by name on corruption, NOT RUN without evidence).
"""

import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

from core.scene import buildings as bd
from core.terrain.heightfield import Georeference, Heightfield

REPO = Path(__file__).resolve().parents[1]
CRS = "EPSG:32632"
OX, OY = 350000.0, 5085000.0          # the bake's upper-left node
PX = 5.0
N = 60
KEY = "fixture_town"

#: Footprints in local (east, south) metres from the bake origin, offset
#: 2.5 m from the node lines so no node sits on an edge.
RINGS = {
    "a": [(97.5, 147.5), (122.5, 147.5), (122.5, 157.5), (97.5, 157.5)],            # 25 x 10
    "b": [(197.5, 87.5), (212.5, 87.5), (212.5, 97.5), (197.5, 97.5)],              # 15 x 10
    "c": [(147.5, 202.5), (177.5, 202.5), (177.5, 192.5), (157.5, 192.5),
          (157.5, 177.5), (147.5, 177.5)],                                          # an L, 450 m2
}
AREAS = {"a": 250.0, "b": 150.0, "c": 450.0}
HEIGHTS = {"a": (12.0, "survey"), "b": (None, None), "c": (9.0, "lidar")}
#: The DSM rise over each footprint: b was built after the survey.
RISE = {"a": 10.0, "b": 0.0, "c": 8.0}
GROUND = 500.0


def _inside(e, s, ring):
    inside = False
    for i in range(len(ring)):
        (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
        if (y0 > s) != (y1 > s) and e < x0 + (s - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def _nodes(ring):
    return [(r, c) for r in range(N) for c in range(N) if _inside(c * PX, r * PX, ring)]


def _to_lonlat():
    from pyproj import Transformer

    back = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    return lambda e, s: back.transform(OX + e, OY - s)


def write_bake(tmp_path) -> Path:
    from core.terrain.geoid import datum_for_heightfield

    z = np.full((N, N), GROUND)
    for name, ring in RINGS.items():
        for r, c in _nodes(ring):
            z[r, c] += RISE[name]
    field = Heightfield.from_elevations(z, Georeference(CRS, OX, OY, PX), name="town",
                                        provenance={"synthetic": True})
    field.provenance["datum"] = datum_for_heightfield(field)
    return field.write(tmp_path / "town").with_suffix("")


def footprint_records():
    to_ll = _to_lonlat()
    out = []
    for name, ring in RINGS.items():
        height, source = HEIGHTS[name]
        out.append({"id": f"bldg-{name}", "polygon": [list(to_ll(e, s)) for e, s in ring],
                    "height_m": height, "height_source": source})
    return out


@pytest.fixture
def cache(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    bd.write_fixture_set(directory, KEY, footprint_records())
    monkeypatch.setattr(bd, "BUILDINGS_DIR", directory)
    return directory


# -- the cache and its refusals -------------------------------------------------------

def test_a_cached_set_loads_with_its_provenance_and_nothing_is_committed(cache):
    loaded = bd.load_footprints(KEY)
    assert [f.id for f in loaded.footprints] == ["bldg-a", "bldg-b", "bldg-c"]
    assert loaded.sha256 == bd.sha256_of(cache / f"{KEY}.jsonl") == loaded.provenance["sha256"]
    assert loaded.verdict()["licence"] == "synthetic"
    for key in bd.PROVENANCE_KEYS:
        assert key in loaded.provenance
    # No footprint set is committed: the folder holds the README only.
    committed = sorted(p.name for p in (REPO / "assets" / "buildings").iterdir())
    assert committed == ["README.md"]
    readme = (REPO / "assets" / "buildings" / "README.md").read_text(encoding="utf-8")
    assert "Nothing is fetched during a run" in readme and "no OSM" in readme


def _refusal(key, directory):
    with pytest.raises(bd.BuildingsError) as caught:
        bd.load_footprints(key, directory)
    return caught.value


def test_the_four_refusals_by_name(tmp_path):
    directory = tmp_path / "c"
    # uncached: nothing there; then a sidecar without its data file.
    assert _refusal("nowhere", directory).constraint == "buildings.uncached"
    data, sidecar = bd.write_fixture_set(directory, "set", footprint_records())
    data.unlink()
    assert _refusal("set", directory).constraint == "buildings.uncached"
    # licence: outside the allow-list (named in the message), or none stated.
    data, sidecar = bd.write_fixture_set(directory, "nc", footprint_records(), licence="CC-BY-NC-4.0")
    refused = _refusal("nc", directory)
    assert refused.constraint == "buildings.licence" and "CC-BY-NC-4.0" in refused.message
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["licence"] = None
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    assert _refusal("nc", directory).constraint == "buildings.licence"
    for allowed in ("CDLA-Permissive-2.0", "CC-BY-4.0", "ODbL-1.0", "CC0-1.0"):
        bd.write_fixture_set(directory, "ok", footprint_records(), licence=allowed)
        assert bd.load_footprints("ok", directory).licence == allowed
    assert bd.licence_verdict("CC-BY-4.0")["ai_training_permitted"] is None   # unstated, never yes
    assert bd.licence_verdict("ODbL-1.0")["share_alike"] is True
    # unverified: one byte changed after caching.
    data, _ = bd.write_fixture_set(directory, "tampered", footprint_records())
    data.write_text(data.read_text(encoding="utf-8").replace("12.0", "13.0"), encoding="utf-8")
    assert _refusal("tampered", directory).constraint == "buildings.unverified"
    # ids: stated twice, missing, empty, not a string.
    records = footprint_records()
    for bad in ([records[0], dict(records[1], id=records[0]["id"])],
                [dict(records[0], id=None)], [dict(records[0], id="  ")],
                [dict(records[0], id=7)]):
        bd.write_fixture_set(directory, "ids", bad)
        assert _refusal("ids", directory).constraint == "buildings.ids"


# -- LoD1 on the DTM pad ----------------------------------------------------------------

def test_lod1_blocks_sit_on_the_dtm_pad_with_the_height_source_and_volume(tmp_path, cache):
    stem = write_bake(tmp_path)
    field = Heightfield.read(stem)
    blocks, outside = bd.extrude(bd.load_footprints(KEY).footprints, field)
    assert outside == []
    by = {b.id: b for b in blocks}
    for name, area in AREAS.items():
        block = by[f"bldg-{name}"]
        assert block.area_m2 == pytest.approx(area, abs=1e-3)       # shoelace through the projection
        assert block.volume_m3 == block.area_m2 * block.height_m    # volume = area x height
    a, b, c = by["bldg-a"], by["bldg-b"], by["bldg-c"]
    # The DSM holds a's roof (+10 m): the block is seated on the ring
    # minimum (the ground), not stacked on its own roof.
    assert a.surface_z_m == pytest.approx(GROUND + 10.0, abs=1e-6)
    assert a.pad_seat_m == pytest.approx(GROUND, abs=1e-6)
    assert a.pad_depth_m == pytest.approx(10.0, abs=1e-6)
    assert a.top_z_m == pytest.approx(GROUND + 12.0, abs=1e-6)       # not 522
    assert c.pad_seat_m == pytest.approx(GROUND, abs=1e-6) and c.top_z_m == pytest.approx(509.0, abs=1e-6)
    # Height sources: a measured height as stated, else the 6 m default
    # with its basis (no CityGML basis) stated.
    assert (a.height_m, a.height_source) == (12.0, "survey")
    assert (c.height_m, c.height_source) == (9.0, "lidar")
    assert (b.height_m, b.height_source) == (6.0, "default") and bd.DEFAULT_HEIGHT_M == 6.0
    assert "no CityGML basis" in b.height_basis and b.pad_depth_m == pytest.approx(0.0, abs=1e-6)
    assert bd.height_source_histogram(blocks) == {"default": 1, "lidar": 1, "survey": 1}


def test_the_vintage_mismatch_is_measured_on_the_fixture_and_named_as_the_real_bake_step(tmp_path, cache):
    stem = write_bake(tmp_path)
    field = Heightfield.read(stem)
    codes = np.full((N, N), 10, dtype=np.uint8)
    counts = {}
    for name, ring in RINGS.items():
        nodes = _nodes(ring)
        counts[name] = len(nodes)
        for r, c in nodes:
            codes[r, c] = bd.BUILT_UP_CODE
    assert counts == {"a": 10, "b": 6, "c": 18}
    measured = bd.vintage_mismatch(field, bd.built_mask_from_classes(codes))
    assert measured["built_up_pixels"] == 34 and measured["pixels_below_threshold"] == 6
    assert measured["fraction_below_threshold"] == pytest.approx(6 / 34)
    assert "networked step" in measured["basis"] and measured["threshold_m"] == 2.0
    # The footprints rasterised on the bake grid are the same 34 pixels.
    blocks, _ = bd.extrude(bd.load_footprints(KEY).footprints, field)
    assert np.array_equal(bd.built_mask_from_blocks(field, blocks), codes == bd.BUILT_UP_CODE)


def test_the_document_and_the_scene_buildings_record(tmp_path, cache):
    stem = write_bake(tmp_path)
    path = bd.ensure_buildings_document(KEY, stem)
    assert path == bd.document_path_for(stem) and path.name == "town_buildings.json"
    document = bd.read_buildings_document(path)
    assert document["count"] == 3 and document["height_sources"] == {"default": 1, "lidar": 1, "survey": 1}
    assert document["licence_verdict"]["licence"] == "synthetic"
    assert document["vintage"]["fraction_below_threshold"] == pytest.approx(6 / 34)
    assert document["volume_m3"] == pytest.approx(250 * 12 + 150 * 6 + 450 * 9, abs=0.1)
    assert document["pad"]["depth_max_m"] == pytest.approx(10.0, abs=1e-6)
    records = bd.buildings_records(path)
    assert [r.name for r in records] == ["scene.buildings"]
    record = records[0]
    assert record.value == 3 and record.null_test.ok and record.null_test.kind == "reached"
    assert record.parameters["default_height_basis"] == bd.DEFAULT_HEIGHT_BASIS
    assert record.parameters["object_id"] == "building:all"
    block = bd.manifest_scene_block(path)
    assert block["count"] == 3 and block["sha256"] == bd.sha256_of(cache / f"{KEY}.jsonl")
    assert block["document_sha256"] == bd.sha256_of(path) and block["object_id"] == "building:all"
    assert bd.buildings_records(None) == [] and bd.manifest_scene_block(None) is None


# -- the spec field, the validator, the registry, objects[], the manifest ----------------

def spec_for():
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    spec.set("hold_state", False, frm="test")
    return spec


def test_scene_buildings_is_absent_canonical_and_refused_by_name_at_validation(cache):
    from core.registry import REGISTRY, unregistered_fields
    from core.scenario.spec import ScenarioSpec
    from core.scenario.validate import validate_world

    spec = spec_for()
    before = spec.digest()
    assert spec.scene.buildings.value is None and "scene" not in spec.to_dict()
    assert validate_world(spec) == []
    spec.set("scene.buildings", KEY, frm="test")
    assert spec.digest() != before and spec.to_dict()["scene"]["buildings"]["value"] == KEY
    again = ScenarioSpec.from_dict(spec.to_dict())
    assert again.digest() == spec.digest() and again.scene.buildings.value == KEY
    assert validate_world(spec) == [] and unregistered_fields(spec.to_dict()) == []
    assert REGISTRY.get("scene.buildings").spec_path == "scene.buildings"
    for key, name in (("not_cached", "buildings.uncached"), ("../escape", "buildings.uncached")):
        spec.set("scene.buildings", key, frm="test")
        assert [v.constraint for v in validate_world(spec)] == [name]
    bd.write_fixture_set(cache, "nc", footprint_records(), licence="CC-BY-NC-4.0")
    spec.set("scene.buildings", "nc", frm="test")
    assert [v.constraint for v in validate_world(spec)] == ["buildings.licence"]


def test_building_all_is_one_aggregate_object_after_the_terrain(cache):
    from core.capture.objects import TaxonomyError, compose_objects

    spec = spec_for()
    plain = compose_objects(spec)
    assert [o.id for o in plain] == ["aircraft:c172p:0", "terrain"]
    spec.set("scene.buildings", KEY, frm="test")
    objects = compose_objects(spec)
    assert [o.id for o in objects] == ["aircraft:c172p:0", "terrain", "building:all"]
    building = objects[-1]
    assert building.int_id == 3 and building.class_name == "building" and building.role == "scene"
    assert building.class_id == list(spec.taxonomy.classes.value).index("building") + 1
    assert building.licence == "synthetic"
    assert building.mesh_sha256 == bd.sha256_of(cache / f"{KEY}.jsonl")
    assert [o.int_id for o in objects[:2]] == [o.int_id for o in plain]       # earlier ids unmoved
    spec.set("taxonomy.classes", ["aircraft", "terrain"], frm="test")
    with pytest.raises(TaxonomyError):
        compose_objects(spec)


def test_the_manifest_carries_scene_buildings_only_when_the_scene_names_it(tmp_path, cache):
    from core.capture.manifest import world_scene

    assert world_scene(None) == ({}, []) and world_scene({"key": "flat"}) == ({}, [])
    path = bd.ensure_buildings_document(KEY, write_bake(tmp_path))
    blocks, records = world_scene({"buildings_document": str(path)})
    assert list(blocks) == ["buildings"] and blocks["buildings"] == bd.manifest_scene_block(path)
    assert [r.name for r in records] == ["scene.buildings"]


def test_the_catalogue_names_every_w2_refusal_and_check_in_plain_sentences():
    from core.messages import catalogue, is_catalogued

    names = ("buildings.uncached", "buildings.licence", "buildings.unverified", "buildings.ids",
             "runway.geometry", "runway.taxonomy", "runway.terrain_mismatch", "runway.markings",
             "check.building_vs_footprint", "check.runway_vs_geometry")
    identifier = re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z_]+\.[a-z_]+\b")
    entries = catalogue()
    for name in names:
        assert is_catalogued(name), name
        for key in ("sentence", "hint"):
            text = entries[name].get(key) or ""
            assert not identifier.findall(text), (name, key)
        assert entries[name]["sentence"].rstrip().endswith(".")


# -- the verifier: building_vs_footprint on synthetic bundles ----------------------------

TERRAIN_ID, BUILDING_ID = 2, 3
W = H = 200
F = 200.0
CAM_ALT = 800.0


def _boxes(document):
    """Each block as axis-aligned boxes in manifest (north, east, alt)
    metres: the L split in two. Written from RINGS, not the document."""
    by = {b["id"]: b for b in document["buildings"]}
    out = []
    for name, parts in (("a", [RINGS["a"]]), ("b", [RINGS["b"]]),
                        ("c", [[(147.5, 192.5), (177.5, 202.5)], [(147.5, 177.5), (157.5, 192.5)]])):
        block = by[f"bldg-{name}"]
        for part in parts:
            es = [p[0] for p in part]
            ss = [p[1] for p in part]
            out.append(((-max(ss), -min(ss)), (min(es), max(es)),
                        (block["pad_seat_m"], block["top_z_m"])))
    return out


def _render(document, camera_east, camera_north, draw_buildings=True):
    """A nadir camera's ID image and camera-z depth by ray casting the
    blocks and the flat ground: pixel centres, image up = north."""
    cols, rows = np.meshgrid(np.arange(W), np.arange(H))
    d = (cols + 0.5 - W / 2.0) / F
    e = (rows + 0.5 - H / 2.0) / F
    direction = (-e, d, -np.ones_like(d))            # forward (0,0,-1), right east, up north
    origin = (camera_north, camera_east, CAM_ALT)
    depth = np.full(d.shape, (CAM_ALT - GROUND))
    mask = np.full(d.shape, TERRAIN_ID, dtype=np.uint8)
    if draw_buildings:
        for box in _boxes(document):
            t_in = np.full(d.shape, -np.inf)
            t_out = np.full(d.shape, np.inf)
            for axis, (lo, hi) in enumerate(box):
                with np.errstate(divide="ignore", invalid="ignore"):
                    t0 = (lo - origin[axis]) / direction[axis]
                    t1 = (hi - origin[axis]) / direction[axis]
                parallel = direction[axis] == 0
                inside = (origin[axis] >= lo) & (origin[axis] <= hi)
                t0 = np.where(parallel, np.where(inside, -np.inf, np.inf), t0)
                t1 = np.where(parallel, np.where(inside, np.inf, -np.inf), t1)
                t_in = np.maximum(t_in, np.minimum(t0, t1))
                t_out = np.minimum(t_out, np.maximum(t0, t1))
            hit = (t_out >= t_in) & (t_in > 0) & (t_in < depth)
            depth = np.where(hit, t_in, depth)
            mask = np.where(hit, BUILDING_ID, mask)
    return mask, depth.astype("<f4")


def _nadir_quaternion():
    half = math.radians(-90.0) / 2.0
    return [math.cos(half), 0.0, math.sin(half), 0.0]


def write_bundle(run_dir, document_path, mask, depth, camera_east, camera_north,
                 objects=None, scene=None):
    from PIL import Image

    folder = run_dir / "frames" / "nadir"
    folder.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask).save(folder / "frame_0000_mask.png")
    depth.tofile(folder / "frame_0000_depth.f32")
    (folder / "render.json").write_text(json.dumps({"frame_records": [{
        "frame": "frame_0000.png",
        "labels": {"mask": "frame_0000_mask.png", "depth_f32": "frame_0000_depth.f32"}}]}),
        encoding="utf-8")
    manifest = {
        "manifest_version": 6,
        "frame": {"crs": CRS, "origin_x_m": OX, "origin_y_m": OY},
        "scene": scene if scene is not None else {
            "key": "town", "terrain": None, "terrain_sha256": None,
            "buildings": bd.manifest_scene_block(document_path)},
        "objects": objects if objects is not None else [
            {"id": "aircraft:c172p:0", "int_id": 1, "class": "aircraft", "class_id": 1},
            {"id": "terrain", "int_id": TERRAIN_ID, "class": "terrain", "class_id": 2},
            {"id": "building:all", "int_id": BUILDING_ID, "class": "building", "class_id": 3}],
        "frames": [{
            "camera_id": "nadir", "file": "frames/nadir/frame_0000.png", "labels": {},
            "position_north_m": camera_north, "position_east_m": camera_east,
            "position_alt_m": CAM_ALT, "quaternion_wxyz": _nadir_quaternion(),
            "principal_point_px": [W / 2.0, H / 2.0], "fx_px": F, "fy_px": F,
            "width_px": W, "height_px": H}],
    }
    return manifest


@pytest.fixture
def bundle(tmp_path, cache):
    path = bd.ensure_buildings_document(KEY, write_bake(tmp_path))
    document = bd.read_buildings_document(path)
    camera = (140.0, -150.0)          # (east, north): over the town
    mask, depth = _render(document, *camera)
    run_dir = tmp_path / "run"
    manifest = write_bundle(run_dir, path, mask, depth, *camera)
    return run_dir, manifest, path, document, camera


def test_building_vs_footprint_passes_on_a_correct_bundle(bundle):
    from core.capture.verify import PASS, verify_building_vs_footprint

    run_dir, manifest, _, _, _ = bundle
    check = verify_building_vs_footprint(manifest, run_dir)
    assert check.status == PASS, check.detail
    assert "3 footprint prisms" in check.detail and "roof centre" in check.detail


def test_building_vs_footprint_fails_by_name_on_corruption(bundle, tmp_path):
    from core.capture.verify import FAIL, verify_building_vs_footprint

    run_dir, manifest, path, document, camera = bundle
    # (1) the document changed after the capture: its sha256 is not the manifest's.
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace('"bldg-a"', '"bldg-x"'), encoding="utf-8")
    check = verify_building_vs_footprint(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.building_vs_footprint")
    assert "sha256" in check.detail
    # (2) the footprints moved 30 m east (the manifest's digest re-stated):
    # the ID image's building pixels land outside every prism.
    moved = json.loads(original)
    for block in moved["buildings"]:
        block["polygon_xy"] = [[x + 30.0, y] for x, y in block["polygon_xy"]]
        block["centroid_xy"] = [block["centroid_xy"][0] + 30.0, block["centroid_xy"][1]]
    path.write_text(json.dumps(moved), encoding="utf-8")
    manifest["scene"]["buildings"]["document_sha256"] = bd.sha256_of(path)
    check = verify_building_vs_footprint(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.building_vs_footprint")
    assert "outside every footprint prism" in check.detail
    path.write_text(original, encoding="utf-8")
    manifest["scene"]["buildings"]["document_sha256"] = bd.sha256_of(path)
    # (3) the buildings drawn but not labelled: visible roofs without the id.
    mask, depth = _render(document, *camera)
    write_bundle(run_dir, path, np.where(mask == BUILDING_ID, TERRAIN_ID, mask).astype(np.uint8),
                 depth, *camera)
    check = verify_building_vs_footprint(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.building_vs_footprint")
    assert "does not carry building:all" in check.detail
    # (4) labelled but not drawn: the depth sees past the roofs.
    _, flat = _render(document, *camera, draw_buildings=False)
    write_bundle(run_dir, path, mask, flat, *camera)
    check = verify_building_vs_footprint(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.building_vs_footprint")
    assert "not drawn" in check.detail
    # (5) a stated set with no building:all object.
    write_bundle(run_dir, path, mask, depth, *camera)
    stripped = dict(manifest, objects=manifest["objects"][:2])
    check = verify_building_vs_footprint(stripped, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.building_vs_footprint")


def test_building_vs_footprint_is_not_run_without_its_evidence(bundle, tmp_path):
    from core.capture.verify import NOT_RUN, verify_building_vs_footprint

    run_dir, manifest, _, _, _ = bundle
    no_set = dict(manifest, scene={"key": "town", "terrain": None, "terrain_sha256": None})
    assert verify_building_vs_footprint(no_set, run_dir).status == NOT_RUN
    assert verify_building_vs_footprint(manifest, tmp_path / "no_render").status == NOT_RUN
    gone = json.loads(json.dumps(manifest))
    gone["scene"]["buildings"]["document"] = str(tmp_path / "elsewhere" / "missing.json")
    assert verify_building_vs_footprint(gone, run_dir).status == NOT_RUN
