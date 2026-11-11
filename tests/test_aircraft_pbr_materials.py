"""Visual round 5, lane L4: physically calibrated aircraft materials.

The vendored Physically Based API database (CC0, pinned by sha256), the
measured constants the class masters take from it, the exhaust soot (HLSL
and its Python twin), the Thin Translucent canopy master and the -labels
gate that keeps every labelled frame on the opaque, depth-writing glass,
all without an engine. Nothing here is a measurement of a rendered frame:
every look number stays UNCALIBRATED until a probe render sets it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import aircraft_look as look  # noqa: E402
import physically_based as pb  # noqa: E402
import ue_aircraft_materials as importer  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_CPP = (BRIDGE / "Private" / "FlightSimAircraftFX.cpp").read_text(encoding="utf-8")
FX_H = (BRIDGE / "Public" / "FlightSimAircraftFX.h").read_text(encoding="utf-8")
MASTERS = (REPO / "scripts" / "ue_aircraft_master_materials.py").read_text(encoding="utf-8")
IMPORTER = (REPO / "scripts" / "ue_aircraft_materials.py").read_text(encoding="utf-8")
API_CHECK = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
SOOT_HLSL = (REPO / look.SHADER_DIR / "exhaust_soot.hlsl").read_text(encoding="utf-8")
VENDORED = REPO / "assets" / "looks" / "physically_based"
LOOKS = sorted((REPO / "assets" / "aircraft_config" / "look").glob("*.json"))
J11_FDM = REPO / "assets" / "fdm_root" / "aircraft" / "J11" / "J11.xml"

MTL = """newmtl mat_BOE
Kd 0.8 0.8 0.8
map_Kd BOE.png

newmtl rgb_6b6b6b
Kd 0.42 0.42 0.42
d 0.200

newmtl rgb_000000
Kd 0.0 0.0 0.0

newmtl mat_nozzle
Kd 0.5 0.5 0.5
"""


def _body(text, name):
    start = text.index(f"def {name}(")
    rest = text[start + 1:]
    match = re.search(r"^(def |#: |[A-Z_]+ = )", rest, re.M)
    return text[start:start + 1 + (match.start() if match else len(rest))]


# -- the vendored database ------------------------------------------------------

def test_the_vendored_database_is_the_pinned_upstream_file_and_cc0():
    pin = json.loads((VENDORED / "PIN.json").read_text(encoding="utf-8"))
    assert pin["licence"] == "CC0-1.0"
    assert re.fullmatch(r"[0-9a-f]{40}", pin["commit"])
    for name, entry in pin["files"].items():
        digest = hashlib.sha256((VENDORED / name).read_bytes()).hexdigest()
        assert digest == entry["sha256"], name
        assert entry["url"].startswith("https://raw.githubusercontent.com/AntonPalmqvist/physically-based-api/"
                                       + pin["commit"] + "/")
    assert (VENDORED / "LICENSE").read_text(encoding="utf-8").startswith("CC0 1.0 Universal")
    rows = pb.load()
    for name in pin["materials_used"]:
        assert name in rows, name
    attribution = (REPO / "THIRD_PARTY_VISUAL.md").read_text(encoding="utf-8")
    assert pin["commit"] in attribution and pin["files"]["materials.json"]["sha256"] in attribution


def test_an_edited_database_is_refused_by_name(tmp_path):
    copy = tmp_path / "pb"
    shutil.copytree(VENDORED, copy)
    path = copy / "materials.json"
    path.write_text(path.read_text(encoding="utf-8").replace("0.916", "0.5"), encoding="utf-8")
    with pytest.raises(pb.PhysicallyBasedError, match="sha256 .* is not the pinned"):
        pb.load(str(copy))


def test_the_metal_f0s_and_the_tyre_are_the_database_rows():
    assert look.ALUMINIUM_F0 == pb.linear_color(pb.material("Aluminum")) == (0.916, 0.923, 0.924)
    assert look.TITANIUM_F0 == pb.linear_color(pb.material("Titanium")) == (0.441, 0.4, 0.361)
    assert look.STEEL_F0 == pb.linear_color(pb.material("Stainless Steel"))
    assert look.TIRE_ALBEDO == (0.023, 0.023, 0.023) and look.TIRE_ROUGHNESS == 0.7 and look.TIRE_IOR == 1.5
    assert look.PAINT_IOR == 1.5
    with pytest.raises(pb.PhysicallyBasedError, match="not a metal"):
        pb.metal_f0("Tire")
    with pytest.raises(pb.PhysicallyBasedError, match="not in the vendored database"):
        pb.material("Unobtainium")


def test_f0_and_specular_follow_the_ior():
    assert pb.f0_from_ior(1.5) == pytest.approx(0.04)
    assert pb.specular_from_ior(1.5) == pytest.approx(0.5)
    assert pb.f0_from_ior(1.0) == 0.0


# -- the class defaults ----------------------------------------------------------

def test_paint_is_a_dielectric_bare_metal_a_metal_and_rubber_the_measured_tyre():
    paint, metal, rubber = (look.CLASS_SCALARS[c] for c in ("paint", "bare_metal", "rubber"))
    assert paint["Metallic"] == 0.0 and paint["Specular"] == 0.5
    assert 0.8 <= paint["AlbedoMax"] <= 0.92
    assert metal["Metallic"] == 1.0
    # the brief's 0.25-0.45 band: the mean +- half the breakup's noise swing
    assert metal["Roughness"] - metal["RoughnessBreakup"] / 2 >= 0.25 - 1e-9
    assert metal["Roughness"] + metal["RoughnessBreakup"] / 2 <= 0.45 + 1e-9
    assert look.CLASS_VECTORS["bare_metal"]["MetalF0"][:3] == look.ALUMINIUM_F0
    assert rubber["Roughness"] == look.TIRE_ROUGHNESS
    assert rubber["Specular"] == pytest.approx(pb.specular_from_ior(look.TIRE_IOR))
    assert look.CLASS_VECTORS["rubber"]["RubberFloor"][:3] == look.TIRE_ALBEDO
    # the panel lines stay a hint (round 5 lowered them)
    for cls in ("paint", "bare_metal"):
        assert look.CLASS_SCALARS[cls]["PanelDepth"] <= 0.25
        assert look.CLASS_SCALARS[cls]["PanelDarkening"] <= 0.15
    # slot binding is untouched: the same four classes, in the same order
    assert look.SLOT_CLASSES == ("paint", "bare_metal", "glass", "rubber")
    assert look.THIN_CLASS not in look.CLASS_MASTERS


def test_the_thin_canopy_is_glass_at_ior_1_5():
    assert look.THIN_GLASS_IOR == 1.5
    assert look.THIN_SCALARS["Specular"] == pytest.approx(0.5)
    assert look.THIN_SCALARS["Roughness"] == pytest.approx(0.02, abs=0.01)
    assert look.THIN_SCALARS["Metallic"] == 0.0
    t = look.THIN_VECTORS["Transmittance"]
    assert all(0.5 < c < 1.0 for c in t[:3])
    assert look.thin_instance_name("mat_Glass_Cockpit") == "MI_mat_Glass_Cockpit_thin"
    assert look.THIN_INSTANCE_SUFFIX == "_thin"


def test_fighters_are_matte_and_airliners_clear_coated_and_no_config_adds_metallic_to_paint():
    by_name = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in LOOKS}
    paint = {name: c.get("class_scalars", {}).get("paint", {}) for name, c in by_name.items()}
    assert paint["J11"]["ClearCoat"] == 0.0
    for airliner in ("A320", "B747", "c172p"):
        assert paint[airliner]["ClearCoat"] == 1.0, airliner
        assert paint[airliner]["ClearCoatRoughness"] <= 0.15, airliner
    for name, scalars in paint.items():
        assert "Metallic" not in scalars, name
    assert by_name["J11"]["class_vectors"][look.THIN_CLASS]["Transmittance"][:3] != list(
        look.THIN_VECTORS["Transmittance"][:3])
    for name in by_name:
        look.load_config(name)   # every config still validates


# -- slots: the thin twin, the named metal, the nozzle vectors ---------------------

def test_a_glass_slot_plans_its_thin_twin_and_a_rule_may_name_the_metal():
    config = {"default_class": "paint", "slot_rules": [
        {"match": "mat_nozzle", "class": "bare_metal", "metal": "titanium", "source": "test"}]}
    plan = look.plan_slots(look.parse_mtl(MTL), config)
    glass = plan["rgb_6b6b6b"]
    assert glass["class"] == "glass" and glass["instance"] == "MI_rgb_6b6b6b"
    assert glass["thin"]["instance"] == "MI_rgb_6b6b6b_thin"
    assert glass["thin"]["master"] == f"{look.MASTER_ROOT}/{look.THIN_GLASS_MASTER}"
    assert glass["thin"]["scalars"] == look.THIN_SCALARS
    assert "thin" not in plan["mat_BOE"] and "thin" not in plan["rgb_000000"]
    nozzle = plan["mat_nozzle"]
    assert nozzle["class"] == "bare_metal" and nozzle["metal"] == "titanium"
    assert nozzle["vectors"]["MetalF0"][:3] == look.TITANIUM_F0
    for name in look.SOOT_NOZZLE_PARAMETERS:
        assert plan["mat_BOE"]["vectors"][name] == look.NO_NOZZLE
        assert nozzle["vectors"][name] == look.NO_NOZZLE
        assert name not in plan["rgb_000000"]["vectors"]


@pytest.mark.parametrize("change, word", [
    ({"slot_rules": [{"match": "x", "class": "paint", "metal": "titanium", "source": "s"}]},
     "metal is a bare_metal choice"),
    ({"slot_rules": [{"match": "x", "class": "bare_metal", "metal": "adamantium", "source": "s"}]},
     "not in"),
    ({"class_vectors": {"paint": {"Nozzle0": [0, 0, 0, 1]}}}, "set from the manifest's nozzles"),
    ({"class_scalars": {"glass_thin": {"Shininess": 1.0}}}, "not a parameter of M_AircraftGlassThin"),
])
def test_the_validator_refuses_a_bad_metal_or_nozzle_or_thin_override(change, word):
    config = json.loads((REPO / "assets" / "aircraft_config" / "look" / "J11.json").read_text(encoding="utf-8"))
    config.update(change)
    with pytest.raises(look.LookError, match=word):
        look.validate(config)


def test_nozzle_vectors_are_the_manifest_rows_in_the_mesh_frame():
    rows = [{"id": f"n{i}", "actor_cm": [-1900.0, 120.0 * i, -20.0], "radius_cm": 50.0} for i in range(5)]
    out = look.nozzle_vectors(rows, (100.0, 0.0, 10.0))
    assert tuple(out) == look.SOOT_NOZZLE_PARAMETERS
    assert out["Nozzle0"] == (-2000.0, 0.0, -30.0, 50.0)
    assert out["Nozzle3"] == (-2000.0, 360.0, -30.0, 50.0)
    assert look.nozzle_vectors_overflow(rows) == ["n4"]
    assert look.nozzle_vectors([], (0, 0, 0)) == {n: look.NO_NOZZLE for n in look.SOOT_NOZZLE_PARAMETERS}


def _write_model(tmp_path, vertices, origin):
    lines = ["mtllib body.mtl"] + [f"v {x:.6f} {-y:.6f} {z:.6f}" for x, y, z in vertices]
    (tmp_path / "body.obj").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "body.mtl").write_text(MTL, encoding="utf-8")
    (tmp_path / "mesh_manifest.json").write_text(json.dumps({
        "magic": "flightsim-aircraft-mesh", "version": 3, "name": "J11", "parts": ["body"],
        "asset_path_root": "/Game/Aircraft/J11", "mesh_origin_actor_cm": list(origin)}), encoding="utf-8")


def test_the_manifest_carries_the_soot_nozzles_and_the_thin_glass_rule(tmp_path):
    origin = (50.0, 0.0, -10.0)
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0), (-30, 0, 0)], origin)
    config = look.load_config("J11")
    manifest = look.build_manifest("J11", config, str(tmp_path), str(J11_FDM))
    nozzles = manifest["nozzles"]
    assert len(nozzles) == 2
    soot = manifest["soot_nozzles_local_cm"]
    for name, row in zip(look.SOOT_NOZZLE_PARAMETERS, nozzles):
        x, y, z = row["actor_cm"]
        assert soot[name] == [pytest.approx(x - origin[0]), pytest.approx(y - origin[1]),
                              pytest.approx(z - origin[2]), row["radius_cm"]]
    assert soot["Nozzle2"] == list(look.NO_NOZZLE) and manifest["soot_nozzles_left_out"] == []
    thin = manifest["thin_glass"]
    assert thin["master"].endswith(look.THIN_GLASS_MASTER) and thin["suffix"] == "_thin"
    assert thin["slots"] == ["rgb_6b6b6b"] and thin["instances"] == ["MI_rgb_6b6b6b_thin"]
    assert "-labels" in thin["rule"]
    assert manifest["slots"]["rgb_6b6b6b"]["thin_instance"] == "MI_rgb_6b6b6b_thin"
    assert "thin_instance" not in manifest["slots"]["mat_BOE"]


# -- the soot: HLSL and twin ---------------------------------------------------------

def test_the_soot_twin_lies_aft_of_the_exit_fades_along_and_needs_a_nozzle():
    nozzle = (-1900.0, 0.0, 0.0, 50.0)
    on_axis_exit = look.soot_mask((-1900.0, 0.0, 0.0), [nozzle], 10.0)
    assert 0.85 < on_axis_exit <= 1.0
    # ahead of the exit by more than half a radius: nothing
    assert look.soot_mask((-1900.0 + 26.0, 0.0, 0.0), [nozzle], 10.0) == 0.0
    # aft: monotone fade to zero at LengthRadii radii
    values = [look.soot_mask((-1900.0 - d, 60.0, 0.0), [nozzle], 10.0) for d in (0, 100, 200, 400, 499)]
    assert all(a > b for a, b in zip(values, values[1:])) and values[-1] < 0.02
    assert look.soot_mask((-1900.0 - 600.0, 0.0, 0.0), [nozzle], 10.0) == 0.0
    # lateral: Gaussian in a lobe two radii wide at the exit
    assert look.soot_mask((-1900.0, 100.0, 0.0), [nozzle], 10.0) == pytest.approx(
        on_axis_exit * math.exp(-1.0), rel=1e-3)
    # no nozzle, no soot; the noise only scales
    assert look.soot_mask((-1900.0, 0.0, 0.0), [look.NO_NOZZLE], 10.0) == 0.0
    assert look.soot_mask((-1900.0, 0.0, 0.0), [nozzle], 10.0, noise=0.0) == pytest.approx(0.6 * on_axis_exit)
    # the fifth nozzle is not read (four vectors)
    five = [look.NO_NOZZLE] * 4 + [nozzle]
    assert look.soot_mask((-1900.0, 0.0, 0.0), five, 10.0) == 0.0


def test_the_soot_hlsl_matches_its_twin_line_for_line():
    squash = lambda s: re.sub(r"\s+", " ", s)  # noqa: E731
    hlsl = squash(SOOT_HLSL)
    for line in ("float aft = c.x - LocalPos.x;", "float lengthCm = max(LengthRadii, 0.5) * r;",
                 "float along = saturate((aft + 0.5 * r) / (lengthCm + 0.5 * r));",
                 "float width = r * (2.0 + max(aft, 0.0) / (3.0 * r));",
                 "float lobe = exp(-(lateral * lateral) / (width * width));",
                 "float fade = (1.0 - along) * (1.0 - along);", "float gate = step(-0.5 * r, aft);",
                 "return soot * lerp(0.6, 1.0, saturate(Noise));"):
        assert line in hlsl, line
    assert "WorldPositionOffset" not in SOOT_HLSL
    assert look.SHADER_INPUTS["exhaust_soot"] == ("LocalPos", "Nozzle0", "Nozzle1", "Nozzle2", "Nozzle3",
                                                  "LengthRadii", "Noise")


# -- the masters module -----------------------------------------------------------

def test_the_masters_rebuild_at_generation_9_with_the_measured_graph():
    assert re.search(r'^LOOK_GENERATION = "9"$', MASTERS, re.M)   # round 25: in place, sentinel, coat
    surface = _body(MASTERS, "_surface")
    assert '_custom(material, "exhaust_soot", "CMOT_FLOAT1"' in surface
    assert '_min(material, base, s["AlbedoMax"]' in surface
    assert 'v["MetalF0"]' in surface and 's["MetalColourWeight"]' in surface
    assert "_const(material, 1.0, -300, 450), edge" in surface   # the wear exposes Metallic 1
    assert 's["SootAmount"]' in surface and 's["SootLengthRadii"]' in surface
    rubber = _body(MASTERS, "create_aircraft_rubber")
    assert '"RubberFloor"' in rubber and "_max(material, _base_colour" in rubber
    assert "WORLD_POSITION_OFFSET" not in MASTERS and "WorldPositionOffset" not in MASTERS


def test_the_thin_canopy_master_is_thin_translucent_forward_lit_with_ssr_and_no_refraction():
    thin = _body(MASTERS, "create_aircraft_glass_thin")
    assert "BLEND_TRANSLUCENT" in thin and "MSM_THIN_TRANSLUCENT" in thin
    assert "TLM_SURFACE_PER_PIXEL_LIGHTING" in thin
    assert '"screen_space_reflections"' in thin
    assert '"allow_translucent_custom_depth_writes"' in thin
    assert "MaterialExpressionThinTranslucentMaterialOutput" in thin and '"TransmittanceColor"' in thin
    assert '"RM_NONE"' in thin and "RM_2D" not in thin and "RM_INDEX" not in thin
    assert 'set_editor_property("two_sided", False)' in thin
    assert 'add_wet_layer(material, sys.modules[__name__], "glass")' in thin
    assert "add_canopy_scratch" not in thin   # anisotropy stays on the opaque, deferred glass
    assert "create_aircraft_glass_thin" in MASTERS[MASTERS.index("CREATORS = ("):MASTERS.index("CREATED = (")]
    assert f'"{look.THIN_GLASS_MASTER}"' in MASTERS[MASTERS.index("CREATED = ("):MASTERS.index("def build_all")]


# -- the importer: both instances per glass slot, the soot vectors per instance -------

class _Recorder:
    """A fake ``unreal`` that keeps every parameter value set on each instance."""

    def __init__(self, existing):
        self.existing = set(existing)
        self.values = {}     # instance path -> {parameter: value}
        self.parents = {}
        self.created = []
        rec = self

        class _Asset:
            def __init__(self, path):
                self.path = path

        class EditorAssetLibrary:
            does_asset_exist = staticmethod(lambda path: path in rec.existing)
            load_asset = staticmethod(lambda path: _Asset(path))
            save_loaded_asset = staticmethod(lambda asset, only_if_is_dirty=True: True)

        class MaterialEditingLibrary:
            @staticmethod
            def set_material_instance_parent(instance, master):
                rec.parents[instance.path] = master.path

            @staticmethod
            def set_material_instance_texture_parameter_value(instance, name, texture):
                rec.values.setdefault(instance.path, {})[name] = texture.path

            @staticmethod
            def set_material_instance_vector_parameter_value(instance, name, value):
                rec.values.setdefault(instance.path, {})[name] = tuple(value)

            @staticmethod
            def set_material_instance_scalar_parameter_value(instance, name, value):
                rec.values.setdefault(instance.path, {})[name] = value

            update_material_instance = staticmethod(lambda instance: None)

        class Tools:
            @staticmethod
            def create_asset(name, folder, cls, factory):
                path = f"{folder}/{name}"
                rec.created.append(path)
                rec.existing.add(path)
                return _Asset(path)

        class AssetToolsHelpers:
            get_asset_tools = staticmethod(lambda: Tools())

        self.EditorAssetLibrary = EditorAssetLibrary
        self.MaterialEditingLibrary = MaterialEditingLibrary
        self.AssetToolsHelpers = AssetToolsHelpers
        self.MaterialInstanceConstant = object
        self.MaterialInstanceConstantFactoryNew = lambda: None
        self.LinearColor = lambda *rgba: tuple(rgba)


def test_create_look_instances_makes_the_thin_twin_and_sets_the_soot_vectors(tmp_path, monkeypatch):
    origin = (50.0, 0.0, -10.0)
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0), (-30, 0, 0)], origin)
    root = "/Game/Aircraft/J11"
    masters = [f"{look.MASTER_ROOT}/{m}" for m in look.CLASS_MASTERS.values()]
    masters.append(f"{look.MASTER_ROOT}/{look.THIN_GLASS_MASTER}")
    fake = _Recorder({f"{root}/mat_BOE", f"{root}/rgb_6b6b6b", f"{root}/rgb_000000", f"{root}/TEX_BOE",
                      *masters})
    monkeypatch.setitem(sys.modules, "unreal", fake)
    made, problems = importer.create_look_instances(root, str(tmp_path), "J11", say=lambda *_: None)
    assert problems == [] and made == 4
    assert set(fake.created) == {f"{root}/Look/MI_mat_BOE", f"{root}/Look/MI_rgb_6b6b6b",
                                 f"{root}/Look/MI_rgb_6b6b6b_thin", f"{root}/Look/MI_rgb_000000"}
    assert fake.parents[f"{root}/Look/MI_rgb_6b6b6b_thin"] == f"{look.MASTER_ROOT}/{look.THIN_GLASS_MASTER}"
    assert fake.parents[f"{root}/Look/MI_rgb_6b6b6b"] == f"{look.MASTER_ROOT}/M_AircraftGlass"
    manifest = json.loads((tmp_path / "look_manifest.json").read_text(encoding="ascii"))
    paint = fake.values[f"{root}/Look/MI_mat_BOE"]
    for name in look.SOOT_NOZZLE_PARAMETERS:
        assert paint[name] == tuple(manifest["soot_nozzles_local_cm"][name]), name
    assert paint["Nozzle0"][3] > 0 and paint["Nozzle1"][3] > 0 and paint["Nozzle2"] == look.NO_NOZZLE
    assert "Nozzle0" not in fake.values[f"{root}/Look/MI_rgb_000000"]
    thin = fake.values[f"{root}/Look/MI_rgb_6b6b6b_thin"]
    assert thin["Transmittance"] == tuple(look.load_config("J11")["class_vectors"]["glass_thin"]["Transmittance"])
    assert thin["Specular"] == look.THIN_SCALARS["Specular"] and "Nozzle0" not in thin
    assert thin["BaseColor"] == fake.values[f"{root}/Look/MI_rgb_6b6b6b"]["BaseColor"]


def test_the_importer_binds_soot_only_to_paint_and_bare_metal_and_never_reorders_slots():
    assert 'if row["class"] in ("paint", "bare_metal"):' in IMPORTER
    assert "vectors.update(soot)" in IMPORTER
    # the slot check and the import record are untouched by the look: the
    # beauty copy's slots must still be the measured part's, name for name
    rows = [("body", 0, "a", "a"), ("body", 1, "b", "b"), ("body_beauty", 0, "b", "b"), ("body_beauty", 1, "a", "a")]
    report = importer.classify_slots(rows, ["a", "b"])
    assert importer.beauty_slot_mismatches(report, {"body": {"part": "body_beauty"}})


# -- the C++: the -labels gate -----------------------------------------------------

def test_the_cpp_applies_the_thin_canopy_only_without_labels():
    assert "bool bLabels = false;" in FX_H
    parse = FX_CPP[FX_CPP.index("void FFlightSimAircraftFXOptions::ParseParams"):]
    parse = parse[:parse.index("\n}\n")]
    assert 'bLabels = FParse::Param(*Params, TEXT("labels"));' in parse
    assert f'AircraftFxThinSuffix = TEXT("{look.THIN_INSTANCE_SUFFIX}");' in FX_CPP
    apply = FX_CPP[FX_CPP.index("void FFlightSimAircraftFX::ApplyMaterials"):]
    apply = apply[:apply.index("\n}\n")]
    gate = apply.index("if (!Options.bLabels)")
    thin_load = apply.index("LoadObject<UMaterialInterface>(nullptr, *ThinPath)")
    opaque_load = apply.index("LoadObject<UMaterialInterface>(nullptr, *Path)")
    assert gate < thin_load < opaque_load
    assert "InstanceName + AircraftFxThinSuffix" in apply
    for field in ("slots_thin_translucent", "slots_thin", "thin_glass", "labels"):
        assert f'TEXT("{field}")' in apply, field
    # the commandlet reads the same word
    commandlet = (BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
    assert 'FParse::Param(*Params, TEXT("labels"))' in commandlet


@pytest.mark.parametrize("params, labels", [
    ("", False), ("-labels", True), ("-Visual -quality=beauty -labels", True), ("/labels", True),
    ("-labelsx", False), ("-nolabels", False), ("-labels=on", False), ("-quality=beauty -labels -scene=x", True),
])
def test_the_labels_twin_reads_the_word_the_cpp_reads(params, labels):
    assert look.labels_requested(params) is labels


def test_the_bridge_api_check_pins_the_thin_translucent_engine_surface():
    for needle in ("MSM_ThinTranslucent", "TLM_SurfacePerPixelLighting",
                   "bSupportsDualSourceBlending=true", "FExpressionInput TransmittanceColor;",
                   "uint8 bScreenSpaceReflections : 1;", "uint8 AllowTranslucentCustomDepthWrites : 1;",
                   "class UMaterialExpressionMin : public UMaterialExpression",
                   "class UMaterialExpressionMax : public UMaterialExpression",
                   "static CORE_API bool Param( const TCHAR* Stream, const TCHAR* Param );"):
        assert needle in API_CHECK, needle
