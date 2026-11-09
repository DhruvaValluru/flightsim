"""The J-11A package in full (visual overhaul, j11-package lane).

What is pinned here, all without the network or the 182 MB package:

* the pins: every package file the conversion reads carries a git blob
  sha1 and a sha256, both checked against the bytes before a convert;
  a changed, missing or malformed file refuses as ``aircraft.package_pin``;
* the slot and texture map: the model XML's livery swap reaches exactly
  the objects it names, two package files sharing one basename refuse,
  the converter records the FlightGear spec / shininess per MTL slot,
  and the look derives roughness (never metallic) from it;
* the label handling: the cockpit interior, seat and pilot are drawn in
  the BODY part (the aircraft's class and int_id, no component, no box of
  their own), leave the measured anchors and the payload component rows
  exactly as they were, and refuse when they would stick out of the hull;
* the J-11A's own config and look: the inventory, the pins and the
  package positions agree with each other.

The synthetic airframe is tests/test_aircraft_assets.py's (a 10 m craft
whose extents are known by construction).
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

from assets_pipeline import importer
from assets_pipeline import package_inventory as inventory
from assets_pipeline import package_pins as pins
from tests.test_aircraft_assets import (
    VRP_80_0_5, _ac_vertex, _convert, _fdm_xml, _point_fdm_at, _write_labelled_config,
)

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import aircraft_look as look  # noqa: E402

J11_CONFIG = REPO / "assets" / "aircraft_config" / "J11.json"
J11_DOC = REPO / "docs" / "visual" / "J11_PACKAGE.md"


# -- a synthetic package ---------------------------------------------------------

def _png(path: Path, width: int = 16, height: int = 16, shade: int = 0) -> None:
    import struct
    import zlib

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))
    rows = b"".join(b"\x00" + bytes([shade]) * width * 3 for _ in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n"
                     + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _obj(name, triangle_actor_m, texture=None, mat=0):
    lines = ["OBJECT poly", f'name "{name}"']
    if texture:
        lines.append(f'texture "{texture}"')
    lines.append("numvert 3")
    lines += [_ac_vertex(p) for p in triangle_actor_m]
    lines += ["numsurf 1", "SURF 0x0", f"mat {mat}", "refs 3", "0 0 0", "1 1 0", "2 0 1", "kids 0"]
    return "\n".join(lines)


#: The test airframe of test_aircraft_assets.py with a textured skin: the
#: fuselage and a canopy frame take skin.png; the fin keeps it (not a
#: livery object). Material 0 is Phong shi 128 (gloss habit), 1 is shi 10.
SKINNED_AC = "\n".join([
    "AC3Db",
    'MATERIAL "paint" rgb 1 1 1  amb 0.2 0.2 0.2  emis 0 0 0  spec 1 1 1  shi 128  trans 0',
    'MATERIAL "cloth" rgb 0.5 0.5 0.5  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  shi 10  trans 0',
    "OBJECT world",
    "kids 5",
    _obj("fuselage", [(5.0, 0.0, 0.0), (-5.0, -1.0, 1.0), (-5.0, 1.0, -1.0)], "skin.png"),
    _obj("Canopy", [(3.0, 0.0, 0.8), (2.0, -0.3, 0.6), (2.0, 0.3, 0.6)], "skin.png"),
    _obj("fin", [(-4.0, 0.0, 0.5), (-4.5, 0.0, 0.9), (-4.8, 0.0, 0.5)], "skin.png"),
    _obj("LeftWheel", [(-1.0, -0.5, -1.2), (-1.0, 0.5, -1.2), (-1.5, 0.0, -1.0)]),
    _obj("aileron", [(-3.0, -2.0, 0.0), (-4.0, -2.0, 0.0), (-3.0, -3.0, 0.0)]),
]) + "\n"

#: A seat-sized interior: one triangle well inside the hull's extents
#: (x -5..5, y -3..1, z -1.2..1 m), its .ac at its own origin.
INTERIOR_AC = "\n".join([
    "AC3Db",
    'MATERIAL "cloth" rgb 0.5 0.5 0.5  amb 0.2 0.2 0.2  emis 0 0 0  spec 0 0 0  shi 10  trans 0',
    "OBJECT world",
    "kids 1",
    _obj("seat", [(0.4, 0.0, 0.0), (0.0, -0.2, 0.2), (0.0, 0.2, 0.2)], "cloth.png"),
]) + "\n"


def _package(tmp_path: Path, monkeypatch, *, interior=True, livery=True, pinned=True,
             interior_offset=(-2.0, 0.0, 0.1), **overrides) -> Path:
    """The labelled synthetic config, extended the way J11.json is."""
    _point_fdm_at(monkeypatch, _fdm_xml(tmp_path, VRP_80_0_5))
    config_path = _write_labelled_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    src = tmp_path / "src"
    (src / "model.ac").write_text(SKINNED_AC, encoding="utf-8")
    _png(src / "skin.png", shade=10)
    _png(src / "Liveries" / "plaaf.png", shade=200)
    files = ["model.ac", "skin.png", "Liveries/plaaf.png"]
    if interior:
        (src / "Interior").mkdir(exist_ok=True)
        (src / "Interior" / "seat.ac").write_text(INTERIOR_AC, encoding="utf-8")
        _png(src / "Interior" / "cloth.png", shade=90)
        files += ["Interior/seat.ac", "Interior/cloth.png"]
        # FG model frame offsets: +x aft, so -2 m aft is 2 m forward.
        config["parts"].append({"file": "Interior/seat.ac", "interior": True,
                                "offset_m": list(interior_offset), "source": "synthetic"})
    if livery:
        config["livery"] = {"name": "plaaf", "texture": "Liveries/plaaf.png",
                            "replaces": "skin.png", "part": "model.ac",
                            "objects": ["fuselage", "Canopy"], "source": "synthetic"}
    if pinned:
        config["package_files"] = [pins.pin_row(src / f, f, "synthetic") for f in files]
    config.update(overrides)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _mtl_textures(mtl: Path):
    """{material name: map_Kd} of an MTL."""
    out, name = {}, None
    for line in mtl.read_text(encoding="utf-8").splitlines():
        if line.startswith("newmtl "):
            name = line.split(None, 1)[1]
            out[name] = None
        elif line.startswith("map_Kd ") and name:
            out[name] = line.split(None, 1)[1]
    return out


def _faces(obj: Path):
    return [line for line in obj.read_text(encoding="utf-8").splitlines() if line.startswith("f ")]


# -- pins ------------------------------------------------------------------------

def test_the_git_blob_sha1_is_gits_own(tmp_path):
    """The tree API lists blob ids; the pin recomputes them from the bytes
    exactly as ``git hash-object`` does (the empty blob is git's constant)."""
    assert pins.git_blob_sha1(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    (tmp_path / "f").write_bytes(b"hello\n")
    row = pins.pin_row(tmp_path / "f", "f", "r")
    assert row["git_blob_sha1"] == "ce013625030ba8dba906f756967f9e9ca394464a"
    assert row["sha256"] == hashlib.sha256(b"hello\n").hexdigest() and row["bytes"] == 6


def test_a_package_file_that_is_not_the_pinned_content_refuses_by_name(tmp_path, monkeypatch):
    from assets_pipeline.convert import ConvertError

    config_path = _package(tmp_path, monkeypatch)
    _convert(tmp_path, config_path)          # the pinned bytes convert
    _png(tmp_path / "src" / "Liveries" / "plaaf.png", shade=201)    # same size, other bytes
    with pytest.raises(ConvertError) as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint == "aircraft.package_pin"
    assert "Liveries/plaaf.png" in str(caught.value)
    (tmp_path / "src" / "Interior" / "cloth.png").unlink()
    with pytest.raises(ConvertError, match="cloth.png is missing"):
        _convert(tmp_path, config_path)


@pytest.mark.parametrize("change, word", [
    ({"git_blob_sha1": "abc"}, "40 hex"),
    ({"sha256": "0" * 63}, "64 hex"),
    ({"file": "../outside.png"}, "not a path inside"),
    ({"role": " "}, "role is empty"),
    ({"bytes": -1}, "non-negative"),
])
def test_a_malformed_pin_refuses_before_any_byte_is_read(tmp_path, change, word):
    (tmp_path / "a.png").write_bytes(b"x")
    row = dict(pins.pin_row(tmp_path / "a.png", "a.png", "r"), **change)
    with pytest.raises(pins.PackagePinError, match=word) as caught:
        pins.verify({"package_files": [row]}, tmp_path)
    assert caught.value.constraint == "aircraft.package_pin"


def test_a_config_without_pins_verifies_nothing_and_keeps_its_manifest_shape(tmp_path, monkeypatch):
    config_path = _package(tmp_path, monkeypatch, interior=False, livery=False, pinned=False)
    manifest, _ = _convert(tmp_path, config_path)
    assert not {"package_files", "livery", "interior", "views"} & set(manifest)
    assert pins.verify({}, tmp_path) == []


def test_the_importer_checks_the_pins_after_the_fetch(tmp_path, monkeypatch):
    config_path = _package(tmp_path, monkeypatch)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    said = []
    assert importer.verify_source_pins(config, tmp_path / "src", said.append) == 5
    assert "5 pinned package file(s) verified" in said[0]
    (tmp_path / "src" / "skin.png").write_bytes(b"not a png")
    with pytest.raises(importer.AircraftAssetError) as caught:
        importer.verify_source_pins(config, tmp_path / "src", said.append)
    assert caught.value.constraint == "aircraft.package_pin"
    assert "skin.png is 9 bytes" in caught.value.message


def test_a_manifest_converted_before_the_pins_is_stale(tmp_path):
    """The render machine's J-11 conversion predates the livery and the
    cockpit: it must be converted again, not imported as it is."""
    config = json.loads(J11_CONFIG.read_text(encoding="utf-8"))
    manifest = {"name": "J11"}
    assert "package file(s)" in importer._package_pins_reason(manifest)
    manifest["package_files"] = [dict(row) for row in config["package_files"]]
    assert importer._package_pins_reason(manifest) is None
    manifest["package_files"][0] = dict(manifest["package_files"][0], sha256="0" * 64)
    assert "1 missing or changed" in importer._package_pins_reason(manifest)
    assert importer._package_pins_reason({"name": "B747"}) is None   # no pins, never stale


# -- slot and texture map -----------------------------------------------------------

def test_the_livery_reaches_exactly_the_objects_the_model_xml_names(tmp_path, monkeypatch):
    manifest, manifest_path = _convert(tmp_path, _package(tmp_path, monkeypatch))
    out = manifest_path.parent
    textures = _mtl_textures(out / "body.mtl")
    assert textures["mat_plaaf"] == "plaaf.png" and textures["mat_skin"] == "skin.png"
    sources = json.loads((out / "material_sources.json").read_text(encoding="utf-8"))["materials"]
    assert sources["mat_plaaf"]["objects"] == ["model.ac:Canopy", "model.ac:fuselage"]
    assert sources["mat_plaaf"]["texture"] == "Liveries/plaaf.png"
    assert sources["mat_skin"]["objects"] == ["model.ac:fin"]          # not a livery object
    assert manifest["livery"]["objects_applied"] == {"Canopy": 1, "fuselage": 1}
    assert {"plaaf.png", "skin.png", "cloth.png"} <= set(manifest["textures"])
    assert (out / "plaaf.png").read_bytes() == (tmp_path / "src/Liveries/plaaf.png").read_bytes()


def test_a_livery_object_without_the_replaced_texture_refuses(tmp_path, monkeypatch):
    from assets_pipeline.convert import ConvertError

    config_path = _package(tmp_path, monkeypatch)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["livery"]["objects"].append("LeftWheel")       # untextured in the .ac
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConvertError, match="LeftWheel") as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint == "aircraft.livery_unmatched"


def test_two_package_textures_sharing_a_basename_refuse(tmp_path, monkeypatch):
    """The converted textures share one folder and Interchange names each
    TEX_<stem>: a second skin.png would silently replace the first."""
    from assets_pipeline.convert import ConvertError

    config_path = _package(tmp_path, monkeypatch, livery=False, pinned=False)
    (tmp_path / "src" / "Interior" / "seat.ac").write_text(
        INTERIOR_AC.replace("cloth.png", "skin.png"), encoding="utf-8")
    _png(tmp_path / "src" / "Interior" / "skin.png", shade=33)
    with pytest.raises(ConvertError) as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint == "aircraft.texture_collision"


def test_the_converter_records_each_slots_flightgear_material(tmp_path, monkeypatch):
    _, manifest_path = _convert(tmp_path, _package(tmp_path, monkeypatch))
    data = json.loads((manifest_path.parent / "material_sources.json").read_text(encoding="utf-8"))
    assert data["magic"] == look.MATERIAL_SOURCES_MAGIC
    cloth = data["materials"]["mat_cloth"]["ac_materials"]
    assert cloth == {"Interior/seat.ac:cloth": {
        "rgb": [0.5, 0.5, 0.5], "specular": [0.0, 0.0, 0.0], "shininess": 10.0,
        "transparency": 0.0, "triangles": 1}}
    # The MTL itself carries no Ks / Ns: the measured path's instances are unchanged.
    mtl = (manifest_path.parent / "body.mtl").read_text(encoding="utf-8")
    assert "\nKs " not in mtl and "\nNs " not in mtl


@pytest.mark.parametrize("shininess, roughness", [(0, 1.0), (10, 0.639), (64, 0.417), (128, 0.352)])
def test_roughness_from_shininess_is_the_phong_lobe_match(shininess, roughness):
    assert look.roughness_from_shininess(shininess) == pytest.approx(roughness, abs=1e-3)
    assert look.roughness_from_shininess(shininess) == pytest.approx(
        math.sqrt(math.sqrt(2.0 / (shininess + 2.0))))


SOURCES = {
    "mat_cloth": {"texture": "Interior/cloth.png", "ac_materials": {
        "seat.ac:a": {"shininess": 0.0, "specular": [0, 0, 0], "triangles": 1},
        "seat.ac:b": {"shininess": 128.0, "specular": [1, 1, 1], "triangles": 3}}},
    "mat_skin": {"texture": "skin.png", "ac_materials": {
        "model.ac:paint": {"shininess": 128.0, "specular": [1, 1, 1], "triangles": 9}}},
}
MTL = "newmtl mat_cloth\nKd 1 1 1\nmap_Kd cloth.png\n\nnewmtl mat_skin\nKd 1 1 1\nmap_Kd skin.png\n"


def test_derived_roughness_is_triangle_weighted_clamped_and_wins_over_the_class_choice():
    config = {"default_class": "paint",
              "slot_rules": [{"match": "mat_cloth", "class": "rubber", "source": "s"}],
              "class_scalars": {"rubber": {"Roughness": 0.9}, "paint": {"Roughness": 0.58}},
              "fg_material": {"parameters": ["Roughness"], "classes": ["rubber"],
                              "roughness_min": 0.5, "roughness_max": 0.95, "source": "s"}}
    plan = look.plan_slots(look.parse_mtl(MTL), config, SOURCES)
    raw = (1.0 * 1 + look.roughness_from_shininess(128) * 3) / 4
    assert plan["mat_cloth"]["scalars"]["Roughness"] == pytest.approx(max(raw, 0.5), abs=1e-4)
    assert plan["mat_cloth"]["derived"]["roughness_from_shininess"] == pytest.approx(raw, abs=1e-4)
    assert "UNCALIBRATED" in plan["mat_cloth"]["derived"]["basis"]
    # paint is not listed: its look choice stands, whatever the .ac says.
    assert plan["mat_skin"]["scalars"]["Roughness"] == 0.58 and plan["mat_skin"]["derived"] is None
    # Metallic is never derived, from any source.
    assert plan["mat_cloth"]["scalars"]["Metallic"] == look.CLASS_SCALARS["rubber"]["Metallic"]
    # Without the converter's record nothing is derived.
    assert look.plan_slots(look.parse_mtl(MTL), config)["mat_cloth"]["scalars"]["Roughness"] == 0.9


@pytest.mark.parametrize("block, word", [
    ({"parameters": ["Metallic"], "classes": [], "source": "s"}, "never derived"),
    ({"parameters": ["Sheen"], "classes": [], "source": "s"}, "not one of"),
    ({"parameters": [], "classes": ["chrome"], "source": "s"}, "not in"),
    ({"parameters": [], "classes": [], "roughness_min": 0.9, "roughness_max": 0.2, "source": "s"},
     "roughness_min"),
    ({"parameters": [], "classes": []}, "no source"),
    ({"parameters": [], "classes": [], "source": "s", "gain": 2}, "unknown keys"),
])
def test_an_fg_material_block_the_look_could_not_use_is_refused(block, word):
    config = {"schema": look.LOOK_SCHEMA, "name": "X", "default_class": "paint",
              "fg_material": block}
    with pytest.raises(look.LookError, match=word):
        look.validate(config)


def test_the_look_instances_read_the_converters_record():
    """ue_aircraft_materials.create_look_instances hands the converter's
    material_sources.json to plan_slots (the editor side is not run here)."""
    text = (REPO / "scripts" / "ue_aircraft_materials.py").read_text(encoding="utf-8")
    assert "look.read_material_sources(mtl_dir)" in text


# -- label handling -------------------------------------------------------------------

def test_the_interior_is_drawn_in_the_body_and_moves_no_label(tmp_path, monkeypatch):
    """The seat lands in body.obj (the aircraft's class and int_id: the
    commandlet stencils every primitive of the aircraft actor), adds no
    part and no component, and every measured anchor and extent is the
    airframe's alone, exactly as without it."""
    (tmp_path / "with").mkdir()
    (tmp_path / "without").mkdir()
    full, full_path = _convert(tmp_path / "with", _package(tmp_path / "with", monkeypatch))
    plain, plain_path = _convert(tmp_path / "without",
                                 _package(tmp_path / "without", monkeypatch, interior=False))
    for key in ("parts", "components", "mesh_extents_actor_cm", "mesh_extent_actor_m",
                "mesh_origin_actor_cm", "vertices_measured", "gear_vertices_measured",
                "origin_measurement"):
        assert full.get(key) == plain.get(key), key
    assert full["triangles"]["body"] == plain["triangles"]["body"] + 1
    assert len(_faces(full_path.parent / "body.obj")) == len(_faces(plain_path.parent / "body.obj")) + 1
    interior = full["interior"]
    assert interior["drawn_in"] == "body" and "class and int_id" in interior["label"]
    assert [row["file"] for row in interior["parts"]] == ["Interior/seat.ac"]
    # About the model origin, like mesh_extent_actor_m: the seat's 0.4 m
    # tip moved 2 m forward (FG +x is aft) and 0.1 m up.
    assert interior["extent_actor_m"]["x"][1] == pytest.approx(2.4)
    assert interior["extent_actor_m"]["z"] == pytest.approx([0.1, 0.3])
    assert interior["vertices"] == 3


@pytest.mark.parametrize("offset", [(-2.0, 0.0, 5.0), (-9.0, 0.0, 0.0), (0.0, 4.0, 0.0)])
def test_an_interior_part_outside_the_hull_refuses_by_name(tmp_path, monkeypatch, offset):
    """It would grow the drawn silhouette past the airframe the labels
    measure, so the conversion stops rather than draw it."""
    from assets_pipeline.convert import ConvertError

    with pytest.raises(ConvertError, match="outside the hull") as caught:
        _convert(tmp_path, _package(tmp_path, monkeypatch, interior_offset=offset))
    assert caught.value.constraint == "aircraft.interior_outside_hull"


def test_an_interior_part_cannot_also_be_a_component(tmp_path, monkeypatch):
    """A component gets a box of its own; an interior part never does. An
    undeclared component is refused by the payload check before the
    interior check is reached; either way nothing converts."""
    from assets_pipeline.convert import ConvertError

    config_path = _package(tmp_path, monkeypatch)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["parts"][-1]["component"] = "seat"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ConvertError) as caught:
        _convert(tmp_path, config_path)
    assert caught.value.constraint in ("aircraft.component_unmatched",
                                       "aircraft.interior_outside_hull")


def test_a_flightgear_pitch_raises_a_forward_point_for_nose_up():
    from assets_pipeline.convert import _pitch_model

    x, y, z = _pitch_model((-1.0, 0.3, 0.0), 10.0)     # 1 m forward (FG +x aft)
    assert z == pytest.approx(math.sin(math.radians(10.0))) and y == 0.3
    assert _pitch_model((1.0, 2.0, 3.0), 0.0) == (1.0, 2.0, 3.0)


def test_the_pilot_eye_view_is_mapped_to_the_actor_frame(tmp_path, monkeypatch):
    views = {"pilot_eye": {"model_m": [1.0, 0.0, 0.5], "pitch_deg": -17.0, "fov_deg": 84.0,
                           "source": "s"}}
    manifest, _ = _convert(tmp_path, _package(tmp_path, monkeypatch, views=views))
    origin = manifest["mesh_origin_actor_cm"]
    assert manifest["views"]["pilot_eye"]["actor_cm"] == pytest.approx(
        [-100.0 + origin[0], origin[1], 50.0 + origin[2]], abs=0.01)


# -- the J-11A's own config, look and inventory ----------------------------------------

def _j11():
    return json.loads(J11_CONFIG.read_text(encoding="utf-8"))


def test_every_file_the_j11_conversion_reads_is_pinned():
    config = _j11()
    assert not pins.validate_rows(config["package_files"])
    pinned = {row["file"] for row in config["package_files"]}
    assert {part["file"] for part in config["parts"]} <= pinned
    assert config["livery"]["texture"] in pinned
    assert config["license"]["file"] in pinned
    for row in config["package_files"]:
        if row["file"] == "LICENSE":    # the licence the owner cleared (decision 3)
            packet = REPO / "docs" / "phase3" / "packets" / "D1-SU-27SK-LICENSE.txt"
            if packet.is_file():
                assert hashlib.sha256(packet.read_bytes()).hexdigest() == row["sha256"]


def test_the_j11_interior_parts_are_the_cockpit_the_model_xml_places():
    interior = [p for p in _j11()["parts"] if p.get("interior")]
    assert [p["file"] for p in interior] == [
        "Models/Interior/panel.ac", "Models/Interior/seat2.ac",
        "Models/Interior/pilot/fighter_default.ac"]
    for part in interior:
        assert part["source"] and "component" not in part
    # panel-zh.xml's own offsets plus J-11A.xml's (0.3, -0.01, 0) m
    assert interior[1]["offset_m"] == pytest.approx([5.3, 0.0, 0.6])
    assert interior[2]["offset_m"] == pytest.approx([5.3, 0.0, 0.95])


def test_the_inventory_lists_every_pin_with_the_same_blob_and_size():
    rows = inventory.parse(J11_DOC.read_text(encoding="utf-8"))
    assert len(rows) >= 700                       # the whole package, not a sample
    config = _j11()
    for pin in config["package_files"]:
        row = rows[pin["file"]]
        assert row["sha"] == pin["git_blob_sha1"], pin["file"]
        assert row["size"] == pin["bytes"], pin["file"]
        assert row["used"], pin["file"]
    assert sum(row["used"] for row in rows.values()) == len(config["package_files"])
    assert config["license"]["commit"] in J11_DOC.read_text(encoding="utf-8")


def test_the_inventory_refuses_a_tree_that_disagrees_with_the_pins():
    config = {"license": {"commit": "c" * 40, "repo": "r"},
              "package_files": [{"file": "a.png", "git_blob_sha1": "1" * 40, "sha256": "2" * 64,
                                 "bytes": 1, "role": "r"}]}
    tree = {"sha": "t", "tree": [{"path": "a.png", "type": "blob", "size": 1, "sha": "3" * 40}]}
    with pytest.raises(ValueError, match="config pins blob"):
        inventory.render(tree, config)
    with pytest.raises(ValueError, match="absent from the tree"):
        inventory.render({"sha": "t", "tree": []}, config)
    good = dict(tree, tree=[dict(tree["tree"][0], sha="1" * 40)])
    assert inventory.parse(inventory.render(good, config))["a.png"]["used"]
    assert inventory.purpose("Models/Liveries/PLAAF2Div.png").startswith("livery: PLAAF")


J11_SLOTS = """newmtl mat_PLAAF2Div
Kd 1 1 1
map_Kd PLAAF2Div.png

newmtl mat_Glass_Cockpit
Kd 1 1 1
map_Kd Glass_Cockpit.png

newmtl mat_transp
Kd 1 1 1
map_Kd transp.png

newmtl mat_fighter_pilot
Kd 1 1 1
map_Kd fighter_pilot.png

newmtl mat_panel_front_tex_2048_bevel
Kd 1 1 1
map_Kd panel-front-tex-2048-bevel.png

newmtl rgb_ff0000
Kd 1 0 0

newmtl rgb_878787
Kd 0.533 0.533 0.533
"""


def test_the_j11_look_classes_its_measured_slots():
    """The slot names the converter wrote from the pinned package
    (2026-11-09): the canopy and visor are glass (the MTL has no d), the
    cockpit, seat and pilot matte, the airframe paint."""
    plan = look.plan_slots(look.parse_mtl(J11_SLOTS), look.load_config("J11"))
    classes = {slot: row["class"] for slot, row in plan.items()}
    assert classes == {"mat_PLAAF2Div": "paint", "mat_Glass_Cockpit": "glass", "mat_transp": "glass",
                       "mat_fighter_pilot": "rubber", "mat_panel_front_tex_2048_bevel": "rubber",
                       "rgb_ff0000": "rubber", "rgb_878787": "paint"}


def test_the_j11_lamps_and_nozzles_sit_where_the_package_puts_them():
    config = look.load_config("J11")
    pinned = {row["file"] for row in _j11()["package_files"]}
    rows = config["lights"] + config["nozzles"]
    package_rows = [r for r in rows if r["anchor"] == "package_model_m"]
    assert len(package_rows) == len(rows) - 1          # the tail lamp alone is measured
    for row in package_rows:
        cited = [f for f in pinned if f.rsplit("/", 1)[-1] in row["source"]]
        assert cited, f"{row['id']}: its source names no pinned package file"
    origin = (0.0078, 0.0, -10.5698)                   # the J-11A conversion, 2026-11-09
    nozzles = {r["id"]: r for r in config["nozzles"]}
    # FG model frame -> actor: x negated, metres -> cm, about the mesh origin.
    assert look.package_model_to_actor_cm(nozzles["engine0"]["package_model_m"], origin) == \
        pytest.approx((-1922.6922, -127.7, -30.1698), abs=1e-3)
    for row in nozzles.values():
        assert isinstance(row["index"], int) and row["afterburner"]   # thrust still from the FDM
    kinds = sorted(r["kind"] for r in config["lights"])
    assert kinds == ["beacon_green", "beacon_red", "landing", "landing", "nav_green",
                     "nav_red", "nav_white"]


def test_a_package_anchor_maps_like_every_converted_vertex():
    """resolve_anchor's package_model_m is the converter's own map:
    model_to_ue (x negated) then the mesh origin."""
    from assets_pipeline.convert import model_to_ue

    origin = (12.5, -3.0, 40.0)
    point = (16.12, -7.5, 0.32)
    ue = model_to_ue(point)
    expected = tuple(ue[i] * 100.0 + origin[i] for i in range(3))
    got, basis = look.resolve_anchor({"anchor": "package_model_m", "package_model_m": list(point),
                                      "source": "LightPack.xml"}, [], None, origin)
    assert got == pytest.approx(expected) and "LightPack.xml" in basis


def test_the_preview_and_label_box_mesh_skips_the_interior_parts(tmp_path, monkeypatch):
    """core/capture/aircraft_mesh.py feeds the engine-less preview and the
    labels' mesh_tight_box_body_m from config parts[], capped at the
    largest TRIANGLE_BUDGET faces. An interior part (inside the hull) must
    not enter it: on the pinned J-11A the cockpit, seat and pilot took 89
    of the 2600 slots from hull faces (skeptic review, 2026-11-09), and
    the seat's pitch_deg is applied only by the converter."""
    from core.capture import aircraft_mesh

    quad = ("AC3Db\nMATERIAL \"m\" rgb 0.5 0.5 0.5 amb 0 0 0 emis 0 0 0 spec 0 0 0 "
            "shi 0 trans 0\nOBJECT world\nkids 1\nOBJECT poly\nname \"{n}\"\nnumvert 4\n"
            "{verts}numsurf 1\nSURF 0x10\nmat 0\nrefs 4\n0 0 0\n1 0 0\n2 0 0\n3 0 0\nkids 0\n")
    big = "0 0 0\n10 0 0\n10 0 10\n0 0 10\n"
    small = "1 0 1\n2 0 1\n2 0 2\n1 0 2\n"
    src = tmp_path / "aircraft_src" / "toy" / "Models"
    src.mkdir(parents=True)
    (src / "hull.ac").write_text(quad.format(n="hull", verts=big), encoding="utf-8")
    (src / "seat.ac").write_text(quad.format(n="seat", verts=small), encoding="utf-8")
    config_dir = tmp_path / "aircraft_config"
    config_dir.mkdir()
    (config_dir / "TOY.json").write_text(json.dumps({
        "name": "TOY", "source_dir": "../aircraft_src/toy",
        "parts": [{"file": "Models/hull.ac"},
                  {"file": "Models/seat.ac", "interior": True, "pitch_deg": -5.0}],
    }), encoding="utf-8")
    monkeypatch.setattr(aircraft_mesh, "CONFIG_DIR", config_dir)
    triangles = aircraft_mesh.load_triangles("TOY")
    assert len(triangles) == 2                                  # the hull quad alone
    (src / "seat.ac").unlink()
    assert aircraft_mesh.available("TOY")       # an interior file is not part of the model
