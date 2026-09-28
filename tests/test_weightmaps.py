"""Land-cover weight layers at the Landscape's resolution (W1,
core/terrain/weightmaps.py) and the import manifest (core/terrain/landscape.py).

The claims under test: one uint8 layer per class at the layout the
heightmap export chooses, summing to exactly 255 at every texel; the
argmax round trip reproducing the bake's dominant class; the taxonomy map
as stated, a foreign code refused by name; the import manifest carrying
the layers, the bake's datum block and sha256, with the three named
refusals. Synthetic fixtures are hand-derivable; the two real bakes
(Yosemite, Grand Canyon) are measured when present and skipped by name
otherwise -- the measured numbers are in docs/ADVANCEMENTS_REPORT.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from core.messages import name_of
from core.terrain import landscape, weightmaps
from core.terrain.heightfield import Georeference, Heightfield
from core.terrain.landcover import LEGEND, LEGEND_CODES, WEIGHT_KEYS, LandcoverError, rasterise
from core.terrain.landscape import LandscapeManifestError
from core.terrain.weightmaps import (
    CLASS_OF_COVER, LandcoverLegendError, alignment_check, argmax_codes, argmax_round_trip,
    cover_class, export_layers, quantise_to_255, read_bake_weights, read_layers,
    resample_fractions, sample_positions,
)
from tests.test_landcover import LAT0, LON0, PIXEL_DEG, SIZE, quadrant_source, write_bake  # noqa: F401

REPO = Path(__file__).resolve().parents[1]

#: The taxonomy as the blueprint states it (section 4, models and parameters).
TAXONOMY_AS_STATED = {10: "vegetation", 20: "vegetation", 95: "vegetation", 50: "building",
                      80: "water", 90: "water", 30: "terrain", 40: "terrain", 60: "terrain",
                      70: "terrain", 100: "terrain"}


def real_bake_dir() -> Path:
    """Where the real bakes sit: FLIGHTSIM_BAKE_DIR, else runs/terrain."""
    return Path(os.environ.get("FLIGHTSIM_BAKE_DIR") or (REPO / "runs" / "terrain"))


def real_scene(key: str) -> Path:
    scene = real_bake_dir() / f"{key}_landcover"
    if not (scene / "landcover.json").is_file() or not (real_bake_dir() / f"{key}.r16").is_file():
        pytest.skip(f"real bake {key!r} with land cover is not at {real_bake_dir()} "
                    f"(scripts/bake_terrain.py then scripts/bake_landcover.py); nothing "
                    f"measured here")
    return scene


@pytest.fixture
def quadrant_scene(tmp_path, quadrant_source):
    """The I7 pipeline on the aligned 20 x 20 bake: pure quadrant cells
    of 10 / 30 / 60 / 80 (NW, NE, SW, SE), with the datum block."""
    cells = SIZE // 3
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0,
                      3 * PIXEL_DEG, cells, cells, datum=True)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path, source_4326=quadrant_source)
    return bake, scene_dir, doc


# -- the taxonomy ---------------------------------------------------------------

def test_the_taxonomy_map_is_the_stated_one_over_the_whole_legend():
    assert CLASS_OF_COVER == TAXONOMY_AS_STATED
    assert set(CLASS_OF_COVER) == set(LEGEND_CODES)
    for code, word in TAXONOMY_AS_STATED.items():
        assert cover_class(code) == word


def test_a_code_outside_the_legend_refuses_landcover_legend_by_name():
    for code in (0, 37, 110, 255):
        with pytest.raises(LandcoverLegendError) as err:
            cover_class(code)
        assert name_of(err.value) == "landcover.legend"
        assert str(code) in err.value.message


# -- the arithmetic, hand-derivable -----------------------------------------------

def test_resampling_samples_the_heightmaps_positions_and_blends_linearly():
    """A 2 x 2 bake of two classes: the texel halfway between two cells
    carries half of each; the corners carry the cells exactly; the sum
    is preserved everywhere before rounding."""
    stack = np.zeros((12, 2, 2), dtype=np.uint8)
    stack[0, :, 0] = 255          # class 10 down the west column
    stack[2, :, 1] = 255          # class 30 down the east column
    out = resample_fractions(stack, 3)
    rows, cols = sample_positions(2, 2, 3)
    assert list(rows) == [0.0, 0.5, 1.0] and list(cols) == [0.0, 0.5, 1.0]
    assert out[0, 0, 0] == 255 and out[0, 0, 2] == 0
    assert out[0, 1, 1] == pytest.approx(127.5) and out[2, 1, 1] == pytest.approx(127.5)
    assert np.allclose(out.sum(axis=0), 255.0)
    # The same positions the heightmap export resamples on.
    field = Heightfield.from_elevations(np.array([[0.0, 10.0], [20.0, 30.0]]),
                                        Georeference("EPSG:32611", 0.0, 0.0, 30.0))
    z = landscape.resample_to(field, 3)
    assert z[1, 1] == pytest.approx(15.0) and z[0, 1] == pytest.approx(5.0)


def test_largest_remainder_rounding_sums_to_exactly_255_and_stays_within_one_count():
    rng = np.random.default_rng(20260928)
    raw = rng.random((12, 40, 40))
    fractions = raw / raw.sum(axis=0, keepdims=True) * 255.0
    layers = quantise_to_255(fractions)
    assert layers.dtype == np.uint8
    assert np.all(layers.astype(np.int64).sum(axis=0) == 255)
    assert np.abs(layers.astype(np.float64) - fractions).max() < 1.0
    with pytest.raises(ValueError, match="sum to 255"):
        quantise_to_255(fractions * 0.5)


def test_argmax_ties_by_legend_order_and_nodata_only_where_nothing_else_is():
    layers = np.zeros((12, 1, 3), dtype=np.uint8)
    layers[0, 0, 0] = 100; layers[2, 0, 0] = 100        # tie 10 vs 30 -> 10 (legend order)
    layers[7, 0, 1] = 200; layers[0, 0, 1] = 55         # water wins
    layers[11, 0, 2] = 255                              # nodata only
    assert list(argmax_codes(layers)[0]) == [10, 80, 0]


def test_the_round_trip_and_alignment_on_a_hand_built_bake():
    """A 3 x 3 bake resampled to 5 x 5: the odd texels sit on cells
    (exact), the even ones halfway; the argmax at every exact texel is
    the cell's class; at a blended texel between two different classes
    the tie goes by legend order."""
    stack = np.zeros((12, 3, 3), dtype=np.uint8)
    stack[0, :, :2] = 255          # 10 in the two west columns
    stack[7, :, 2] = 255           # 80 in the east column
    majority = np.array([[10, 10, 80]] * 3, dtype=np.uint8)
    layers = quantise_to_255(resample_fractions(stack, 5))
    align = alignment_check(layers, stack)
    assert align["exact_texels"] == 9 and align["ok"] and align["max_count_difference"] == 0
    rt = argmax_round_trip(layers, majority)
    # Column 3 (position 1.5) blends 10 and 80 half and half; the tie goes
    # to 10 while the nearest cell (rint(1.5) = 2) is 80: 5 disagreeing
    # texels of 25.
    assert rt["texels"] == 25 and rt["agreement"] == pytest.approx(20 / 25)
    assert rt["per_class"]["permanent_water"]["agreement"] == pytest.approx(5 / 10)


# -- the export on the synthetic scene -----------------------------------------------

def test_export_writes_one_layer_per_class_at_the_heightmaps_layout(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    field = Heightfield.read(bake)
    spec = landscape.export(field, scene_dir / "aligned_landscape")
    assert layers["layout"]["resolution"] == spec.resolution == 127
    assert (layers["layout"]["quads_per_section"], layers["layout"]["sections_per_component"],
            layers["layout"]["components"]) == (spec.layout.quads_per_section,
                                                spec.layout.sections_per_component,
                                                spec.layout.components)
    assert [entry["code"] for entry in layers["layers"]] == [c.code for c in LEGEND] + [0]
    assert [entry["key"] for entry in layers["layers"]] == list(WEIGHT_KEYS)
    for entry in layers["layers"]:
        path = scene_dir / entry["file"]
        assert entry["file"] == f"aligned_landcover_{entry['code']}.u8"
        assert path.stat().st_size == 127 * 127
        assert entry["class"] == (CLASS_OF_COVER[entry["code"]] if entry["code"] else "nodata")
    assert layers["sum_per_texel"] == {"min": 255, "max": 255, "expected": 255}
    assert layers["alignment"]["ok"] and layers["alignment"]["exact_texels"] == 4
    assert layers["attribution"] == doc["attribution"] and layers["license"] == "CC BY 4.0"
    assert layers["taxonomy"] == {str(k): v for k, v in CLASS_OF_COVER.items()}
    assert layers["source"]["bake_sha256"] == field.digest()
    # Read back with the digests checked: sums exact, quadrant centres pure.
    document, arrays = read_layers(sidecar)
    total = sum(a.astype(np.int64) for a in arrays.values())
    assert total.min() == 255 and total.max() == 255
    q = 127 // 4
    assert arrays[10][q, q] == 255 and arrays[30][q, 3 * q] == 255
    assert arrays[60][3 * q, q] == 255 and arrays[80][3 * q, 3 * q] == 255
    assert arrays[0].max() == 0                               # no nodata anywhere


def test_the_argmax_round_trip_reproduces_the_quadrants_except_at_the_blended_boundary(quadrant_scene):
    """Bilinear blending moves the argmax only on the texels straddling
    the class boundary: agreement below 1 (measured, stated in the
    sidecar) and above 0.9; every quadrant centre reproduces its class."""
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    rt = layers["argmax_round_trip"]
    assert rt["texels"] == 127 * 127
    assert 0.9 < rt["agreement"] < 1.0
    for key in ("tree_cover", "grassland", "bare_sparse", "permanent_water"):
        assert 0.85 < rt["per_class"][key]["agreement"] <= 1.0
    _, arrays = read_layers(sidecar)
    stack = np.stack([arrays[c.code] for c in LEGEND] + [arrays[0]])
    codes = argmax_codes(stack)
    q = 127 // 4
    assert (codes[q, q], codes[q, 3 * q], codes[3 * q, q], codes[3 * q, 3 * q]) == (10, 30, 60, 80)


def test_a_stale_bake_grid_map_refuses_terrain_landcover(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    png = scene_dir / "tree_cover_weight.png"
    png.write_bytes(png.read_bytes()[:-8] + b"\x00" * 8)
    with pytest.raises(LandcoverError) as err:
        read_bake_weights(scene_dir)
    assert name_of(err.value) == "terrain.landcover"


def test_a_class_code_outside_the_legend_in_the_document_refuses_landcover_legend(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    path = scene_dir / "landcover.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["classes"].append({"code": 37, "key": "lava", "title": "Lava", "rgb": [0, 0, 0],
                                "file": "tree_cover_weight.png", "fraction": 0.0})
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(LandcoverLegendError) as err:
        export_layers(scene_dir)
    assert name_of(err.value) == "landcover.legend"


def test_a_layer_file_that_no_longer_matches_its_sidecar_refuses(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    path = scene_dir / layers["layers"][0]["file"]
    data = np.fromfile(path, dtype=np.uint8)
    data[0] ^= 1
    data.tofile(path)
    with pytest.raises(LandcoverError) as err:
        read_layers(sidecar)
    assert name_of(err.value) == "terrain.landcover"


# -- the import manifest ------------------------------------------------------------

def test_the_import_manifest_carries_the_layers_the_datum_and_the_bake_digest(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    field = Heightfield.read(bake)
    spec = landscape.export(field, scene_dir / "aligned_landscape")
    manifest = landscape.import_manifest(field, spec, layers["layers"])
    written = json.loads(spec.raw_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert written == manifest
    assert manifest["datum"] == field.provenance["datum"]           # copied verbatim
    assert manifest["bake"]["sha256"] == field.digest()
    assert [entry["code"] for entry in manifest["weight_layers"]] == [c.code for c in LEGEND] + [0]
    assert set(manifest["weight_layers"][0]) == {"code", "class", "key", "file", "sha256",
                                                 "layout", "resolution"}
    # Gate 4's keys are kept: the Gate 4 round trip still reads the manifest.
    for key in ("resolution", "layout", "scale", "min_elevation_m", "max_elevation_m", "encoding"):
        assert key in manifest
    read_spec, read_manifest = landscape.read_import_manifest(spec.raw_path)
    assert read_spec == spec and read_manifest["datum"] == manifest["datum"]
    result = landscape.verify_round_trip(field, spec, manifest)
    assert result["layers"]["sum_ok"] and result["layers"]["layers"] == 12
    assert result["layers"]["datum_copied"] is True
    assert result["max_error_m"] < 4.0 * result["quantisation_m"]
    assert "layers" not in landscape.verify_round_trip(field, spec)   # the 2-arg form unchanged


def test_a_bake_without_a_datum_block_refuses_terrain_landscape_missing(tmp_path, quadrant_source):
    cells = SIZE // 3
    bake = write_bake(tmp_path, "aligned", "EPSG:4326", LON0, LAT0, 3 * PIXEL_DEG, cells, cells)
    scene_dir, doc = rasterise(bake, tmp_path / "cache", tmp_path, source_4326=quadrant_source)
    sidecar, layers = export_layers(scene_dir)
    field = Heightfield.read(bake)
    assert "datum" not in field.provenance
    spec = landscape.export(field, scene_dir / "aligned_landscape")
    with pytest.raises(LandscapeManifestError) as err:
        landscape.import_manifest(field, spec, layers["layers"])
    assert name_of(err.value) == "terrain.landscape_missing"
    assert not spec.raw_path.with_suffix(".json").read_text(encoding="utf-8").count("weight_layers")


def test_a_layer_of_another_layout_refuses_terrain_landscape_layout(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    field = Heightfield.read(bake)
    spec = landscape.export(field, scene_dir / "aligned_landscape")
    other = landscape.closest_layout(300)
    assert other != spec.layout
    wrong = [dict(entry) for entry in layers["layers"]]
    wrong[3]["layout"] = {"quads_per_section": other.quads_per_section,
                          "sections_per_component": other.sections_per_component,
                          "components": other.components}
    wrong[3]["resolution"] = other.resolution
    with pytest.raises(LandscapeManifestError) as err:
        landscape.import_manifest(field, spec, wrong)
    assert name_of(err.value) == "terrain.landscape_layout"
    manifest = landscape.import_manifest(field, spec, layers["layers"])
    manifest["weight_layers"][3]["layout"] = wrong[3]["layout"]
    with pytest.raises(LandscapeManifestError) as err:
        landscape.verify_round_trip(field, spec, manifest)
    assert name_of(err.value) == "terrain.landscape_layout"


def test_a_bake_or_layer_that_differs_from_the_manifest_refuses_terrain_landscape_stale(quadrant_scene):
    bake, scene_dir, doc = quadrant_scene
    sidecar, layers = export_layers(scene_dir)
    field = Heightfield.read(bake)
    spec = landscape.export(field, scene_dir / "aligned_landscape")
    manifest = landscape.import_manifest(field, spec, layers["layers"])
    # Another bake: one sample moved, a different digest.
    samples = field.samples.copy()
    samples[0, 0] ^= 1
    other = Heightfield(samples, field.georeference, field.scale_m, field.offset_m,
                        name=field.name, provenance=field.provenance)
    assert other.digest() != field.digest()
    with pytest.raises(LandscapeManifestError) as err:
        landscape.verify_round_trip(other, spec, manifest)
    assert name_of(err.value) == "terrain.landscape_stale"
    # A layer file rewritten after the manifest.
    path = scene_dir / manifest["weight_layers"][0]["file"]
    data = np.fromfile(path, dtype=np.uint8)
    data[0] ^= 1
    data.tofile(path)
    with pytest.raises(LandscapeManifestError) as err:
        landscape.verify_round_trip(field, spec, manifest)
    assert name_of(err.value) == "terrain.landscape_stale"
    # And a manifest built on a layer that is already stale.
    with pytest.raises(LandscapeManifestError) as err:
        landscape.import_manifest(field, spec, layers["layers"])
    assert name_of(err.value) == "terrain.landscape_stale"


def test_the_verifier_never_imports_the_weightmap_producer():
    text = (REPO / "core" / "capture" / "verify.py").read_text(encoding="utf-8")
    assert "weightmaps" not in text and "landscape" not in text


# -- the real bakes, measured when present ---------------------------------------------

@pytest.mark.parametrize("key,dominant,agreement_floor", [
    ("yosemite", "tree_cover", 0.95), ("grand_canyon", "tree_cover", 0.95)])
def test_the_real_bakes_export_layers_that_round_trip(tmp_path, key, dominant, agreement_floor):
    """Measured here on 2026-09-28: Yosemite 1149 x 1149 (164 x 1 x 7 + 1),
    argmax agreement 0.9601, sums 255..255, 6 exact texels; Grand Canyon
    806 x 806 (115 x 1 x 7 + 1), agreement 0.9572, 1612 exact texels."""
    scene_dir = real_scene(key)
    out = tmp_path / f"{key}_landcover"
    sidecar, layers = export_layers(scene_dir, out)
    doc = json.loads((scene_dir / "landcover.json").read_text(encoding="utf-8"))
    assert doc["dominant_class"] == dominant
    assert layers["sum_per_texel"] == {"min": 255, "max": 255, "expected": 255}
    assert layers["alignment"]["ok"]
    assert layers["argmax_round_trip"]["agreement"] >= agreement_floor
    field = Heightfield.read(real_bake_dir() / key)
    spec = landscape.export(field, out / f"{key}_landscape")
    assert layers["layout"]["resolution"] == spec.resolution
    manifest = landscape.import_manifest(field, spec, layers["layers"], layer_dir=out)
    assert manifest["datum"]["vertical_datum_of_heights"] == "EGM2008 orthometric (GLO-30)"
    assert isinstance(manifest["datum"]["undulation_m"], float)
    result = landscape.verify_round_trip(field, spec, manifest, out)
    assert result["layers"]["sum_ok"]
    print(f"{key}: {spec.layout.describe()}, argmax agreement "
          f"{layers['argmax_round_trip']['agreement']:.4f}, per class "
          f"{ {k: round(v['agreement'], 4) for k, v in layers['argmax_round_trip']['per_class'].items()} }, "
          f"exact texels {layers['alignment']['exact_texels']}, N {manifest['datum']['undulation_m']:.3f} m")
