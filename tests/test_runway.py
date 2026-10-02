"""W2, the runway (core/scene/runway.py, core/terrain/glo30.py's pad bake,
scripts/bake_runway.py): the geometry refused by name; the Annex 14 5.2
markings raster at 0.1 m / px measured to 1 % of the analytic area with
the threshold stripe count per width read back; the 5.3 light positions
with the photometry named as missing; the flatten pad as a NEW bake (new
key, new sha256, the parent untouched, the statistics in the sidecar),
refused by name on a terrain mismatch; the null test through JSBSim (h_agl
at the threshold with vs without the pad >= 1 m); the spec block runway
absent-canonical, the validator's refusals, the registry entries, the
manifest's scene.runway record, the card's world block; and the verifier's
runway_vs_geometry on synthetic bundles.
"""

import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from core.scene import runway as rw
from core.terrain.heightfield import Georeference, Heightfield

REPO = Path(__file__).resolve().parents[1]
LAT, LON = 45.9, 7.08
CRS = "EPSG:32632"
PX = 30.0
N = 100


def _threshold_xy():
    from pyproj import Transformer

    return Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(LON, LAT)


def write_ridge(directory: Path, name: str = "ridge", slope: float = 0.005) -> Path:
    """A bake with a 4 m, 600 m corrugation along the runway: the threshold
    sits on a crest 4 m above the runway's least-squares plane."""
    from core.terrain.geoid import datum_for_heightfield

    x0, y0 = _threshold_xy()
    ox, oy = x0 - 900.0, y0 + 1500.0
    xs, _ = np.meshgrid(ox + np.arange(N) * PX, oy - np.arange(N) * PX)
    z = 1000.0 + slope * (xs - x0) + 4.0 * np.cos(2.0 * math.pi * (xs - x0) / 600.0)
    field = Heightfield.from_elevations(z, Georeference(CRS, ox, oy, PX), name=name,
                                        provenance={"synthetic": True})
    field.provenance["datum"] = datum_for_heightfield(field)
    return field.write(directory / name).with_suffix("")


def runway(**overrides) -> rw.RunwaySpec:
    fields = dict(designator="09", threshold_lat_deg=LAT, threshold_lon_deg=LON,
                  heading_deg=90.0, length_m=1200.0, width_m=30.0)
    fields.update(overrides)
    return rw.RunwaySpec(**fields)


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """The bake, then scripts/bake_runway.py over it with --null-test: the
    pad bake, the markings PNG, the record (the c172p flown 1 s over the
    pad and over the parent -- the one JSBSim pair in this file)."""
    import importlib.util

    directory = tmp_path_factory.mktemp("runway")
    stem = write_ridge(directory)
    parent_bytes = (_sha(stem.with_suffix(".r16")), _sha(stem.with_suffix(".json")))
    spec_ = importlib.util.spec_from_file_location("bake_runway", REPO / "scripts" / "bake_runway.py")
    module = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(module)
    code = module.main(["--bake", str(stem), "--designator", "09", "--threshold-lat", str(LAT),
                        "--threshold-lon", str(LON), "--heading", "90", "--length", "1200",
                        "--width", "30", "--null-test"])
    assert code == 0
    pad = directory / "ridge_runway_09"
    return {"dir": directory, "stem": stem, "pad": pad, "parent_bytes": parent_bytes,
            "record": rw.document_path_for(pad), "markings": rw.markings_path_for(pad),
            "main": module.main}


# -- the geometry, refused by name --------------------------------------------------------

@pytest.mark.parametrize("overrides, name", [
    (dict(length_m=100.0), "runway.geometry"),
    (dict(length_m=9000.0), "runway.geometry"),
    (dict(width_m=10.0), "runway.geometry"),
    (dict(width_m=120.0), "runway.geometry"),
    (dict(heading_deg=360.0), "runway.geometry"),
    (dict(heading_deg=-5.0), "runway.geometry"),
    (dict(designator="37"), "runway.geometry"),
    (dict(designator="9"), "runway.geometry"),
    (dict(designator="27"), "runway.geometry"),              # does not name heading 90
    (dict(threshold_lat_deg=95.0), "runway.geometry"),
    (dict(threshold_lon_deg="east"), "runway.geometry"),
    (dict(surface="tarmac"), "runway.taxonomy"),
    (dict(markings="fancy"), "runway.markings"),
    (dict(markings=["threshold", "helipad"]), "runway.markings"),
    (dict(width_m=18.0), "runway.markings"),                  # the standard set does not fit
])
def test_a_runway_is_refused_by_name(overrides, name):
    with pytest.raises(rw.RunwayError) as caught:
        runway(**overrides)
    assert caught.value.constraint == name


def test_a_well_formed_runway_and_its_designator_rule():
    spec = runway(designator="09L", surface="concrete")
    assert spec.elements == rw.MARKING_ELEMENTS and spec.to_dict()["markings"] == list(rw.MARKING_ELEMENTS)
    assert rw.designator_number_for_heading(4.0) == 36 and rw.designator_number_for_heading(265.0) == 27
    assert runway(width_m=18.0, length_m=300.0).elements == rw.MARKING_ELEMENTS
    assert runway(width_m=18.0, markings=["threshold", "designator", "centreline"]).width_m == 18.0
    assert rw.RunwaySpec.from_dict(spec.to_dict()) == rw.RunwaySpec(**{
        **spec.to_dict(), "markings": list(rw.MARKING_ELEMENTS)})


# -- the markings raster -----------------------------------------------------------------

@pytest.mark.parametrize("width, length, stripes", [
    (18.0, 300.0, 4), (23.0, 300.0, 6), (30.0, 2400.0, 8), (45.0, 2400.0, 12), (60.0, 3000.0, 16),
    (80.0, 1200.0, 16),
])
def test_the_marking_area_is_the_analytic_to_one_percent_and_the_stripes_count_by_width(width, length, stripes):
    spec = runway(width_m=width, length_m=length)
    raster, rects, counts = rw.markings_raster(spec)
    assert raster.shape == (int(round(length / rw.PX_M)), int(round(width / rw.PX_M))) and rw.PX_M == 0.1
    measured = rw.measure_markings(raster, rects)
    assert measured["relative_error"] <= rw.MARKING_AREA_TOL == 0.01 and measured["within_tolerance"]
    assert measured["painted_area_m2"] == pytest.approx(measured["analytic_area_m2"], rel=0.01)
    assert counts["threshold_stripes"] == stripes == rw.stripe_count_for_width(width)
    assert measured["threshold_stripes_read"] == stripes             # read back off the raster
    assert {"threshold", "designator", "centreline", "aiming_point"} <= set(measured["analytic_by_element_m2"])
    # The stripes are 30 m x 1.8 m each (Annex 14 5.2.4, from memory).
    assert measured["analytic_by_element_m2"]["threshold"] == pytest.approx(stripes * 30.0 * 1.8)


def test_a_marking_set_is_drawn_as_stated_and_none_paints_nothing():
    raster, rects, counts = rw.markings_raster(runway(markings="none"))
    assert not raster.any() and rects == [] and counts == {}
    raster, rects, counts = rw.markings_raster(runway(markings=["centreline"]))
    assert {r.element for r in rects} == {"centreline"} and counts["centreline_stripes"] > 0
    assert rw.measure_markings(raster, rects)["relative_error"] <= rw.MARKING_AREA_TOL


def test_the_light_positions_and_the_photometry_named_as_missing():
    lights, counts = rw.light_positions(runway())
    assert counts["edge"] == 2 * (1200 // 60 + 1) and counts["threshold"] == 30 // 3 + 1
    assert counts["end"] == 30 // 6 + 1 and counts["centreline"] == 1200 // 15 + 1
    assert counts["total"] == len(lights) and counts["centreline_applicable"]
    assert {light["colour"] for light in lights if light["kind"] == "threshold"} == {"green"}
    assert {light["colour"] for light in lights if light["kind"] == "end"} == {"red"}
    assert all(abs(abs(l["t_m"]) - 18.0) < 1e-9 for l in lights if l["kind"] == "edge")
    assert counts["photometry"]["candela"] is None and "NOT transcribed" in counts["photometry"]["basis"]
    _, short = rw.light_positions(runway(length_m=800.0))
    assert short["centreline"] == 0 and not short["centreline_applicable"]


# -- the flatten pad: a new bake ----------------------------------------------------------

def test_the_pad_is_a_new_bake_and_the_parent_is_untouched(world):
    from core.terrain.glo30 import runway_pad_key

    stem, pad_stem = world["stem"], world["pad"]
    assert (_sha(stem.with_suffix(".r16")), _sha(stem.with_suffix(".json"))) == world["parent_bytes"]
    parent, pad = Heightfield.read(stem), Heightfield.read(pad_stem)
    assert pad.name == runway_pad_key("ridge", "09") == "ridge_runway_09"
    assert pad.digest() != parent.digest()
    meta = json.loads(pad_stem.with_suffix(".json").read_text(encoding="utf-8"))
    block = meta["provenance"]["runway_pad"]
    assert block["key"] == "ridge_runway_09" and block["parent"]["sha256"] == parent.digest()
    assert block["spec"] == runway().to_dict() and meta["sha256"] == pad.digest()
    stats = block["statistics"]
    assert stats["footprint_pixels"] >= 3 and stats["shoulder_pixels"] > 0
    assert stats["ends_difference_m"] == pytest.approx(6.0, abs=0.01)     # 0.5 % of 1200 m
    assert stats["tolerance_m"] == pytest.approx(0.02 * 1200.0)
    assert stats["threshold"]["dz_m"] == pytest.approx(-3.9, abs=0.2)     # the crest cut
    # Every footprint pixel holds the plane; every pixel beyond the shoulder is the parent's.
    geometry = rw.RunwayGeometry.for_spec(runway(), CRS)
    g = pad.georeference
    xs, ys = np.meshgrid(g.origin_x_m + np.arange(pad.width) * PX, g.origin_y_m - np.arange(pad.height) * PX)
    s, t = geometry.to_along_across(xs, ys)
    plane = stats["plane"]["a_m"] + stats["plane"]["b_per_m"] * s + stats["plane"]["c_per_m"] * t
    inside = (s >= 0) & (s <= 1200.0) & (np.abs(t) <= 15.0)
    far = np.hypot(np.maximum(0, np.maximum(-s, s - 1200.0)), np.maximum(0, np.abs(t) - 15.0)) > 60.0
    assert np.abs(pad.elevations()[inside] - plane[inside]).max() <= 2 * pad.quantisation_m
    assert np.abs(pad.elevations()[far] - parent.elevations()[far]).max() <= 2 * pad.quantisation_m
    # The datum block rides, the origin's heights re-evaluated on the pad.
    assert "runway pad" in meta["provenance"]["datum"]["note"]


def test_a_terrain_mismatch_is_refused_before_anything_is_written(tmp_path):
    from core.terrain.glo30 import bake_runway_pad

    steep = write_ridge(tmp_path, name="steep", slope=0.03)       # 36 m over 1200 m > 24 m
    with pytest.raises(rw.RunwayError) as caught:
        bake_runway_pad(steep, runway())
    assert caught.value.constraint == "runway.terrain_mismatch"
    assert not (tmp_path / "steep_runway_09.r16").exists()
    off = runway(threshold_lat_deg=46.5, designator="09")         # 65 km north: off the bake
    with pytest.raises(rw.RunwayError) as caught:
        bake_runway_pad(steep, off)
    assert caught.value.constraint == "runway.terrain_mismatch"


def test_the_pad_is_reused_from_its_parent_and_replaced_when_stale(tmp_path):
    from core.terrain.glo30 import ensure_runway_pad

    stem = write_ridge(tmp_path)
    pad = ensure_runway_pad(stem, runway())
    first = _sha(pad.with_suffix(".r16"))
    mtime = pad.with_suffix(".json").stat().st_mtime_ns
    assert ensure_runway_pad(stem, runway()) == pad and pad.with_suffix(".json").stat().st_mtime_ns == mtime
    moved = ensure_runway_pad(stem, runway(length_m=900.0))     # the runway changed: re-baked
    assert moved == pad and _sha(pad.with_suffix(".r16")) != first


# -- the null test through JSBSim and the record -----------------------------------------

def test_the_pad_moves_h_agl_at_the_threshold_by_at_least_a_metre(world):
    document = rw.read_runway_document(world["record"])
    null = document["null_test"]
    assert null["ok"] and abs(null["difference"]) >= rw.PAD_NULL_THRESHOLD_M == 1.0
    assert null["kind"] == "reached" and null["unit"] == "m"
    measured = document["pad"]["null_measurement"]
    assert measured["with_digest"] != measured["without_digest"]
    assert measured["parent_z_at_threshold_m"] - measured["plane_z_at_threshold_m"] == pytest.approx(3.9, abs=0.2)
    records = rw.runway_records(world["record"])
    assert [r.name for r in records] == ["scene.runway"] and records[0].null_test.ok
    assert records[0].parameters["lights"]["counts"]["photometry"]["candela"] is None
    assert document["markings"]["measurement"]["within_tolerance"]
    assert document["markings"]["sha256"] == _sha(world["markings"])
    assert document["markings"]["counts"]["threshold_stripes"] == 8


def test_the_script_refuses_by_name(world, capsys):
    code = world["main"](["--bake", str(world["stem"]), "--designator", "27", "--threshold-lat",
                          str(LAT), "--threshold-lon", str(LON), "--heading", "90",
                          "--length", "1200", "--width", "30", "--out", str(world["dir"] / "x")])
    assert code == 1 and "REFUSED -- runway.geometry:" in capsys.readouterr().out
    assert not (world["dir"] / "x").exists()


# -- the spec block, the validator, the registry, the manifest, the card -----------------

def spec_with_runway(**values):
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    spec.set("hold_state", False, frm="test")
    fields = dict(designator="09", threshold_lat_deg=LAT, threshold_lon_deg=LON,
                  heading_deg=90.0, length_m=1200.0, width_m=30.0)
    fields.update(values)
    for name, value in fields.items():
        spec.set(f"runway.{name}", value, frm="test")
    return spec


def test_the_runway_block_is_absent_canonical_and_validated_by_name():
    from core.nl.compiler import compile_prompt
    from core.registry import REGISTRY, unregistered_fields
    from core.scenario.blocks import RunwayBlockSpec
    from core.scenario.spec import ScenarioSpec
    from core.scenario.validate import validate_world

    plain = compile_prompt("fly the c172p at 1500 m and 100 kt for 1 seconds")
    assert plain.runway.is_default() and "runway" not in plain.to_dict()
    assert RunwayBlockSpec.FIELD_ORDER == ("designator", "threshold_lat_deg", "threshold_lon_deg",
                                           "heading_deg", "length_m", "width_m", "surface", "markings")
    spec = spec_with_runway()
    data = spec.to_dict()
    assert set(data["runway"]) == set(RunwayBlockSpec.FIELD_ORDER)
    again = ScenarioSpec.from_dict(data)
    assert again.digest() == spec.digest() and not again.runway.is_default()
    assert rw.RunwaySpec.from_block(again.runway) == runway()
    assert rw.RunwaySpec.from_block(plain.runway) is None
    assert validate_world(spec) == [] and unregistered_fields(data) == []
    assert {f"runway.{f}" for f in RunwayBlockSpec.FIELD_ORDER} <= set(REGISTRY.spec_fields())
    for values, name in ((dict(length_m=50.0), "runway.geometry"), (dict(surface="ice"), "runway.taxonomy"),
                         (dict(markings=["helipad"]), "runway.markings")):
        assert [v.constraint for v in validate_world(spec_with_runway(**values))] == [name]
    # No designator is no runway (the registry's null): nothing refused.
    nulled = spec_with_runway()
    nulled.set("runway.designator", None, frm="test")
    assert validate_world(nulled) == []
    assert "runway" in {row.split()[0].strip("[]") for row in spec.render_table().splitlines()
                        if row.strip().startswith("[")}


def test_the_manifest_record_and_the_card_world_block(world, tmp_path):
    from core.capture.manifest import world_scene
    from core.scenario.card import write_run_card

    blocks, records = world_scene({"runway_document": str(world["record"])})
    assert list(blocks) == ["runway"] and [r.name for r in records] == ["scene.runway"]
    block = blocks["runway"]
    assert block["designator"] == "09" and block["pad_sha256"] == Heightfield.read(world["pad"]).digest()
    assert block["document_sha256"] == _sha(world["record"]) and block["markings_sha256"] == _sha(world["markings"])
    card_world = rw.world_card_block(world["pad"], Heightfield.read(world["pad"]).digest(),
                                     None, world["record"])
    assert card_world["buildings"] is None and card_world["runway"] == block
    path = write_run_card(spec_with_runway(), tmp_path / "card.json", world=card_world)
    assert json.loads(path.read_text(encoding="utf-8"))["world"] == json.loads(json.dumps(card_world))
    plain = write_run_card(spec_with_runway(), tmp_path / "plain.json")
    assert "world" not in json.loads(plain.read_text(encoding="utf-8"))


# -- the verifier: runway_vs_geometry ----------------------------------------------------

W = H = 400
F = 400.0


def _nadir_record(north, east, alt):
    half = math.radians(-90.0) / 2.0
    return {"camera_id": "nadir", "file": "frames/nadir/frame_0000.png",
            "position_north_m": north, "position_east_m": east, "position_alt_m": alt,
            "quaternion_wxyz": [math.cos(half), 0.0, math.sin(half), 0.0],
            "principal_point_px": [W / 2.0, H / 2.0], "fx_px": F, "fy_px": F,
            "width_px": W, "height_px": H}


@pytest.fixture
def bundle(world, tmp_path):
    """A copy of the record and its raster in a run directory, and a
    manifest with a nadir camera 150 m above the threshold."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    record = run_dir / world["record"].name
    markings = run_dir / world["markings"].name
    shutil.copy(world["markings"], markings)
    document = json.loads(world["record"].read_text(encoding="utf-8"))
    document["markings"]["file"] = str(markings)
    record.write_text(json.dumps(document), encoding="utf-8")
    pad = Heightfield.read(world["pad"])
    x0, y0 = _threshold_xy()
    ox, oy = pad.georeference.origin_x_m, pad.georeference.origin_y_m
    plane_z = document["pad"]["statistics"]["plane"]["a_m"]
    manifest = {
        "manifest_version": 6, "frame": {"crs": CRS, "origin_x_m": ox, "origin_y_m": oy},
        "scene": {"key": "ridge", "terrain": str(world["pad"]), "terrain_sha256": pad.digest(),
                  "runway": rw.manifest_scene_block(record)},
        "frames": [_nadir_record(y0 - oy, x0 - ox, plane_z + 150.0)],
    }
    return run_dir, manifest, record, markings


def _restate(manifest, record, markings):
    manifest["scene"]["runway"]["document_sha256"] = _sha(record)
    manifest["scene"]["runway"]["markings_sha256"] = _sha(markings)


def test_runway_vs_geometry_passes_on_a_correct_bundle(bundle):
    from core.capture.verify import PASS, verify_runway_vs_geometry

    run_dir, manifest, _, _ = bundle
    check = verify_runway_vs_geometry(manifest, run_dir)
    assert check.status == PASS, check.detail
    assert "within 0.00 px" in check.detail and "8 stripes" in check.detail
    assert "engine half NOT RUN" in check.detail


def test_runway_vs_geometry_fails_by_name_on_corruption(bundle):
    from PIL import Image

    from core.capture.verify import FAIL, verify_runway_vs_geometry

    run_dir, manifest, record, markings = bundle
    original = np.array(Image.open(markings))
    # (1) the raster changed after the capture.
    Image.fromarray(np.roll(original, 30, axis=0)).save(markings)
    check = verify_runway_vs_geometry(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.runway_vs_geometry") and "sha256" in check.detail
    # (2) the raster drawn 3 m late (digest re-stated): 8 px at 150 m.
    _restate(manifest, record, markings)
    check = verify_runway_vs_geometry(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.runway_vs_geometry")
    assert "+3.00 m along" in check.detail
    # (3) a stripe erased: the count is not the width's.
    erased = original.copy()
    columns = np.nonzero(erased[int(21.0 / 0.1)])[0]
    erased[:, columns[0]:columns[0] + 18] = 0
    Image.fromarray(erased).save(markings)
    _restate(manifest, record, markings)
    check = verify_runway_vs_geometry(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.runway_vs_geometry") and "7 threshold" in check.detail
    # (4) the document's geometry is not the spec's threshold.
    Image.fromarray(original).save(markings)
    document = json.loads(record.read_text(encoding="utf-8"))
    document["geometry"]["threshold_xy"][0] += 5.0
    record.write_text(json.dumps(document), encoding="utf-8")
    _restate(manifest, record, markings)
    check = verify_runway_vs_geometry(manifest, run_dir)
    assert (check.status, check.failure) == (FAIL, "check.runway_vs_geometry") and "5.00 m" in check.detail


def test_runway_vs_geometry_is_not_run_without_its_evidence(bundle):
    from core.capture.verify import NOT_RUN, verify_runway_vs_geometry

    run_dir, manifest, record, markings = bundle
    no_runway = dict(manifest, scene={"key": "ridge", "terrain": None, "terrain_sha256": None})
    assert verify_runway_vs_geometry(no_runway, run_dir).status == NOT_RUN
    away = dict(manifest, frames=[dict(manifest["frames"][0], position_alt_m=-5000.0)])
    assert verify_runway_vs_geometry(away, run_dir).status == NOT_RUN     # the threshold behind it
    document = json.loads(record.read_text(encoding="utf-8"))
    document["spec"]["markings"] = ["centreline"]
    record.write_text(json.dumps(document), encoding="utf-8")
    _restate(manifest, record, markings)
    assert verify_runway_vs_geometry(manifest, run_dir).status == NOT_RUN
    markings.unlink()
    assert verify_runway_vs_geometry(manifest, run_dir).status == NOT_RUN
