"""The aircraft look (visual overhaul V7, aircraft lane): the look configs,
the slot -> class mapping, the anchor resolution behind the look manifest,
and the contracts between the Python, the HLSL bodies and the beauty-only
C++ (FlightSimAircraftFX.cpp), all without an engine.

Nothing here is a measurement of a rendered frame: every look number is
UNCALIBRATED until a probe render on the render machine sets it, and these
tests pin that it says so.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import aircraft_look as look  # noqa: E402
import fetch_aircraft_models as models  # noqa: E402

BRIDGE = REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source" / "FlightSimBridge"
FX_CPP = BRIDGE / "Private" / "FlightSimAircraftFX.cpp"
FX_H = BRIDGE / "Public" / "FlightSimAircraftFX.h"
COMMANDLET = BRIDGE / "Private" / "FlightSimRenderCommandlet.cpp"
MASTERS = REPO / "scripts" / "ue_aircraft_master_materials.py"
CREATE_MATERIALS = REPO / "scripts" / "ue_create_materials.py"
IMPORT = REPO / "scripts" / "ue_import_aircraft.py"
CONFIGS = sorted((REPO / "assets" / "aircraft_config").glob("*.json"))
LOOKS = sorted((REPO / "assets" / "aircraft_config" / "look").glob("*.json"))
J11_FDM = REPO / "assets" / "fdm_root" / "aircraft" / "J11" / "J11.xml"


# -- the configs ----------------------------------------------------------------

def test_every_aircraft_config_has_a_look_config_and_each_validates():
    assert {p.stem for p in CONFIGS} == {p.stem for p in LOOKS}
    for path in LOOKS:
        config = look.load_config(path.stem)
        assert config["name"] == path.stem


def test_the_look_lives_outside_the_label_provenance_config():
    """The aircraft config's sha256 is label provenance in every manifest
    (core/capture/manifest.py asset_digests): no look key may sit in it."""
    look_only = {"slot_rules", "class_scalars", "class_vectors", "lights", "nozzles",
                 "default_class", "contrail", "vapour"}
    for path in CONFIGS:
        config = json.loads(path.read_text(encoding="utf-8"))
        assert not look_only & set(config), (path.name, look_only & set(config))


@pytest.mark.parametrize("change, word", [
    ({"schema": "x"}, "schema"),
    ({"default_class": "chrome"}, "default_class"),
    ({"surprise": 1}, "unknown keys"),
    ({"slot_rules": [{"match": "rgb_.*", "class": "paint"}]}, "no source"),
    ({"slot_rules": [{"match": "(", "class": "paint", "source": "s"}]}, "bad regex"),
    ({"class_scalars": {"paint": {"Shininess": 1.0}}}, "not a parameter"),
    ({"lights": [{"id": "a", "kind": "laser", "anchor": "mesh_extreme", "axis": "-y"}]}, "kind"),
    ({"lights": [{"id": "a", "kind": "strobe", "anchor": "mesh_extreme", "axis": "up"}]}, "axis"),
    ({"lights": [{"id": "a", "kind": "strobe", "anchor": "structural_in",
                  "structural_in": [1, 2, 3]}]}, "source"),
    ({"nozzles": [{"id": "n", "anchor": "fdm_thruster", "index": 0, "radius_m": 0}]}, "radius_m"),
])
def test_a_look_config_the_importer_could_not_use_is_refused_by_name(change, word):
    config = {"schema": look.LOOK_SCHEMA, "name": "X", "default_class": "paint"}
    config.update(change)
    with pytest.raises(look.LookError, match=word):
        look.validate(config)


# -- slot classes ---------------------------------------------------------------

MTL = """newmtl mat_BOE
Kd 0.8000 0.8000 0.8000
map_Kd BOE.png

newmtl rgb_6b6b6b
Kd 0.4200 0.4200 0.4200
d 0.200

newmtl rgb_000000
Kd 0.0000 0.0000 0.0000

newmtl mat_747_400_tire1
Kd 0.8 0.8 0.8
map_Kd 747-400_tire1.png

newmtl rgb_c0c0c0
Kd 0.7529 0.7529 0.7529
"""


def test_slots_take_the_config_rule_then_glass_by_dissolve_then_rubber_then_default():
    config = {"default_class": "paint",
              "slot_rules": [{"match": "mat_747_400_tire.*", "class": "rubber", "source": "s"}]}
    plan = look.plan_slots(look.parse_mtl(MTL), config)
    assert plan["mat_747_400_tire1"]["class"] == "rubber"
    assert plan["mat_747_400_tire1"]["rule"].startswith("slot_rules")
    assert plan["rgb_6b6b6b"]["class"] == "glass"
    assert plan["rgb_000000"]["class"] == "rubber"
    assert plan["rgb_c0c0c0"]["class"] == "paint"
    assert plan["mat_BOE"]["class"] == "paint"
    assert plan["mat_BOE"]["master"] == "/Game/FlightSim/Aircraft/M_AircraftPaint"
    assert plan["mat_BOE"]["instance"] == "MI_mat_BOE"


def test_the_look_instance_keeps_the_imported_materials_texture_wiring():
    """The same texture / colour / weight as ue_aircraft_materials.plan, so a
    look instance draws the livery the measured path draws."""
    import ue_aircraft_materials as imported
    mine = look.plan_slots(look.parse_mtl(MTL), {"default_class": "paint"})
    theirs = imported.plan(imported.parse_mtl(MTL))
    for slot, row in theirs.items():
        assert mine[slot]["texture"] == row["texture"], slot
        assert mine[slot]["base_color"] == row["base_color"], slot
        assert mine[slot]["weight"] == row["weight"], slot


def test_config_overrides_reach_only_their_class_and_paint_is_not_chrome():
    config = look.load_config("J11")
    plan = look.plan_slots(look.parse_mtl(MTL), config)
    assert plan["mat_BOE"]["scalars"]["Roughness"] == 0.58
    assert plan["rgb_000000"]["scalars"]["Roughness"] == look.CLASS_SCALARS["rubber"]["Roughness"]
    # A painted panel is a dielectric under a clear coat; 0.6-0.9 is bare metal's.
    assert look.CLASS_SCALARS["paint"]["Metallic"] < 0.3
    assert 0.6 <= look.CLASS_SCALARS["bare_metal"]["Metallic"] <= 0.9


# -- frames and anchors ---------------------------------------------------------

def test_structural_to_actor_negates_x_only():
    assert look.structural_to_actor_cm((100.0, -20.0, 5.0)) == (-254.0, -50.8, 12.7)


def _write_model(tmp_path, vertices_actor_about_origin, origin):
    lines = ["mtllib body.mtl"]
    for x, y, z in vertices_actor_about_origin:
        lines.append(f"v {x:.6f} {-y:.6f} {z:.6f}")    # obj = (x, -y, z)
    (tmp_path / "body.obj").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "body.mtl").write_text(MTL, encoding="utf-8")
    (tmp_path / "mesh_manifest.json").write_text(json.dumps({
        "magic": "flightsim-aircraft-mesh", "version": 3, "name": "J11", "parts": ["body"],
        "asset_path_root": "/Game/Aircraft/J11", "mesh_origin_actor_cm": list(origin)}),
        encoding="utf-8")


def test_the_manifest_puts_lamps_on_measured_extremes_and_snaps_nozzles(tmp_path):
    origin = (-100.0, 0.0, 10.0)
    thruster = look.structural_to_actor_cm((802.25, -20.0, 0.0))     # J11.xml engine 0
    about = lambda p: (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])  # noqa: E731
    verts = [
        about((0.0, 0.0, 0.0)),                        # the nose
        about((-1500.0, -700.0, 20.0)),                # left wingtip
        about((-1500.0, 700.0, 20.0)),                 # right wingtip
        about((-2700.0, 0.0, 30.0)),                   # the tail stinger
        about((thruster[0] - 60.0, thruster[1], thruster[2])),   # nozzle 0 exit
        about((thruster[0] - 450.0, thruster[1], thruster[2])),  # beyond the window
    ]
    _write_model(tmp_path, verts, origin)
    manifest = look.build_manifest("J11", look.load_config("J11"), str(tmp_path), str(J11_FDM))
    lamps = {row["id"]: row for row in manifest["lights"]}
    # offset_m: 5 cm inward on y; the strobes 15 cm aft too.
    assert lamps["nav_left"]["actor_cm"] == [-1500.0, -695.0, 20.0]
    assert lamps["nav_right"]["actor_cm"] == [-1500.0, 695.0, 20.0]
    assert lamps["tail"]["actor_cm"] == [-2695.0, 0.0, 30.0]
    assert lamps["strobe_left"]["actor_cm"] == [-1515.0, -695.0, 20.0]
    assert lamps["nav_left"]["basis"].startswith("measured from vertices")
    assert lamps["landing"]["actor_cm"] == [-785.0, 0.0, -150.0]
    nozzles = {row["id"]: row for row in manifest["nozzles"]}
    assert nozzles["engine0"]["actor_cm"][0] == pytest.approx(thruster[0] - 60.0, abs=0.01)
    assert nozzles["engine0"]["actor_cm"][1:] == [pytest.approx(thruster[1], abs=0.01), pytest.approx(thruster[2], abs=0.01)]
    assert "snapped" in nozzles["engine0"]["basis"]
    # engine 1's line has no vertex: the FDM station, said so.
    assert "not snapped" in nozzles["engine1"]["basis"]
    assert nozzles["engine0"]["afterburner"] is True
    assert (nozzles["engine0"]["mil_thrust_lbs"], nozzles["engine0"]["max_thrust_lbs"]) == (17849.1, 26773.7)
    assert nozzles["engine0"]["thrust_property"] == "propulsion/engine[0]/thrust-lbs"
    assert manifest["slots"]["rgb_6b6b6b"]["class"] == "glass"
    assert manifest["instance_root"] == "/Game/Aircraft/J11/Look"


def test_every_look_constant_says_it_is_uncalibrated_and_names_its_probe(tmp_path):
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0)], (0.0, 0.0, 0.0))
    manifest = look.build_manifest("J11", look.load_config("J11"), str(tmp_path), str(J11_FDM))
    groups = manifest["constants"]
    assert set(groups) == {"lights", "contrail", "vapour", "afterburner", "heat_haze",
                           "condensation"}  # condensation-solver
    for group in groups.values():
        for entry in group.values():
            assert entry["calibration"] == look.UNCALIBRATED
            assert "UNCALIBRATED" in entry["calibration"] and entry["probe"]


def test_a_commented_out_engine_is_not_read():
    """J11.xml carries a commented-out GTDE-117 starter engine: two thrusters, not three."""
    fdm = look.read_fdm(str(J11_FDM))
    assert len(fdm["thrusters"]) == 2 and fdm["engines"] == ["Saturn-AL-31", "Saturn-AL-31"]


def test_the_nozzle_snap_window_keeps_a_trailing_edge_out():
    station = (-1000.0, 0.0, 0.0)
    assert look.snap_nozzle([(-1600.0, 0.0, 0.0)], station, 50.0) is None
    assert look.snap_nozzle([(-1100.0, 10.0, 0.0), (-1600.0, 0.0, 0.0)], station, 50.0) == (-1100.0, 10.0, 0.0)


def test_write_manifest_writes_only_where_it_is_told(tmp_path):
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0)], (0.0, 0.0, 0.0))
    out = look.write_manifest("J11", generated_dir=str(tmp_path))
    assert Path(out).parent == tmp_path
    data = json.loads(Path(out).read_text(encoding="ascii"))
    assert data["magic"] == look.LOOK_MANIFEST_MAGIC and data["version"] == look.LOOK_MANIFEST_VERSION


# -- shaders, masters, C++ ------------------------------------------------------

def test_every_shader_body_exists_and_documents_exactly_its_inputs():
    for name, inputs in look.SHADER_INPUTS.items():
        text = (REPO / look.SHADER_DIR / f"{name}.hlsl").read_text(encoding="utf-8")
        documented = re.findall(r"^//\s{2,}(\w+)\s+float", text, re.M)
        assert tuple(documented) == inputs, (name, documented)
        assert "return" in text


def test_the_panel_groove_twin_is_one_on_a_line_and_zero_between():
    import ue_aircraft_master_materials as masters
    assert masters.panel_groove(0.0, 100.0, 0.4) == pytest.approx(1.0, abs=1e-3)
    assert masters.panel_groove(100.0, 100.0, 0.4) == pytest.approx(1.0, abs=1e-3)
    assert masters.panel_groove(50.0, 100.0, 0.4) == 0.0
    # a pixel wider than twice the groove fades it out (no aliasing)
    assert masters.panel_groove(0.0, 100.0, 0.4, footprint_cm=0.8) == 0.0


def _masters_tree():
    return ast.parse(MASTERS.read_text(encoding="utf-8"))


def test_the_master_module_builds_exactly_the_class_and_fx_masters():
    tree = _masters_tree()
    created = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(getattr(t, "id", "") == "CREATED" for t in node.targets))
    names = tuple(ast.literal_eval(created))
    assert set(names) == set(look.CLASS_MASTERS.values()) | set(look.FX_MASTERS)
    text = MASTERS.read_text(encoding="utf-8")
    for name in names:
        assert f'"{name}"' in text


def test_no_master_moves_a_vertex_and_the_glass_is_opaque():
    """Labels match pixels: no world position offset anywhere, and the canopy
    glass draws in the label passes (which draw no translucency)."""
    text = MASTERS.read_text(encoding="utf-8")
    assert "WORLD_POSITION_OFFSET" not in text and "WorldPositionOffset" not in text
    glass = text[text.index("def create_aircraft_glass"):text.index("def create_aircraft_rubber")]
    assert "blend_mode" not in glass and "TRANSLUCENT" not in glass
    for cls in ("_surface", "def create_aircraft_rubber"):
        body = text[text.index(cls):]
        assert "blend_mode" not in body[:body.index("_finish(")]


def test_the_masters_stay_out_of_the_world_materials_contract():
    """tests/test_ue_materials.py pins every /Game/FlightSim/M_* path the C++
    loads to ue_create_materials.py: the aircraft masters live one folder down
    and are built from their own module, so that contract is untouched."""
    assert look.MASTER_ROOT == "/Game/FlightSim/Aircraft"
    text = CREATE_MATERIALS.read_text(encoding="utf-8")
    begin = text.index("# ==== AIRCRAFT LANE (visual overhaul V7) -- begin")
    end = text.index("# ==== AIRCRAFT LANE -- end")
    block = text[begin:end]
    assert "from ue_aircraft_master_materials import build_all" in block
    assert re.search(r"^create_aircraft_masters\(\)", text, re.M)
    assert not re.search(r'new_material\("M_Aircraft', text)


def test_the_cpp_loads_the_fx_masters_and_sets_the_parameters_the_masters_expose():
    # M_AircraftCondensation is loaded and driven by FlightSimCondensation.cpp
    # (condensation-solver), which FlightSimAircraftFX.cpp owns a member of.
    text = FX_CPP.read_text(encoding="utf-8") + (
        FX_CPP.parent / "FlightSimCondensation.cpp").read_text(encoding="utf-8")
    for name in look.FX_MASTERS:
        assert f'TEXT("{look.MASTER_ROOT}/{name}.{name}")' in text, name
    for names in look.FX_PARAMETERS.values():
        for parameter in names:
            if parameter in ("CoreColour", "TipColour", "Shocks"):
                continue    # left at the master's defaults (not set per frame)
            assert f'TEXT("{parameter}")' in text, parameter
    assert f'TEXT("{look.LOOK_INSTANCE_FOLDER}")' in text
    assert f'TEXT("{look.LOOK_INSTANCE_PREFIX}")' in text
    assert f'TEXT("{look.LOOK_MANIFEST_NAME}")' in text
    assert f'TEXT("{look.LOOK_MANIFEST_MAGIC}")' in text


def test_every_fx_actor_is_its_own_beauty_only_actor_never_an_aircraft_component():
    text = FX_CPP.read_text(encoding="utf-8")
    assert "NewObject<UPointLightComponent>(Aircraft" not in text
    assert not re.search(r"NewObject<\w+>\(\s*Aircraft\b", text)
    assert text.count("BeautyOnlyActors.Add(") >= 2
    assert "AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform)" in text
    # no wall clock: every time-varying element runs on the FDM's time
    assert "FPlatformTime" not in text and "GetTimeSeconds" not in text
    assert 'ReadProperty(TEXT("simulation/sim-time-sec"))' in text


def test_heat_haze_is_off_unless_asked_and_recorded_as_pixel_moving():
    header = FX_H.read_text(encoding="utf-8")
    text = FX_CPP.read_text(encoding="utf-8")
    assert "bool bHeatHaze = false;" in header
    assert 'AircraftFxSwitch(Params, TEXT("heat-haze="), false)' in text
    assert 'SetBoolField(TEXT("pixel_moving"), true)' in text


def test_the_commandlet_builds_the_look_only_in_beauty_and_before_the_labels():
    text = COMMANDLET.read_text(encoding="utf-8")
    assert '#include "FlightSimAircraftFX.h"' in text
    gate = "if (bVisual && bBeauty && MeshAirframe.bLoaded && !bHideAircraft)"
    assert text.count(gate) == 1
    build = text.index(gate)
    append = text.index("VisualScene.BeautyOnlyActors.Append(AircraftFX.BeautyOnlyActors);")
    labels = text.index("Label->HiddenActors.Append(VisualScene.BeautyOnlyActors);")
    assert build < append < labels
    assert "if (AircraftFX.IsBuilt())" in text
    assert 'Root->SetObjectField(TEXT("aircraft_look"), AircraftFX.Record);' in text


def test_the_properties_the_fx_reads_are_ones_the_bridge_already_reads():
    """No guessed JSBSim names (NEXT.md gotcha 22): each property the FX reads
    is read elsewhere in the bridge already (the thrust under its [n] index)."""
    text = FX_CPP.read_text(encoding="utf-8")
    rest = "".join(p.read_text(encoding="utf-8") for p in (BRIDGE / "Private").glob("*.cpp")
                   if p.name != FX_CPP.name)
    for name in re.findall(r'ReadProperty\(TEXT\("([^"]+)"\)\)', text):
        assert f'"{name}"' in rest, name
    assert '"propulsion/engine[1]/thrust-lbs"' in rest


def test_nanite_stays_off_at_import_and_the_compile_guard_stays():
    text = IMPORT.read_text(encoding="utf-8")
    assert '"build_nanite", False' in text
    assert "KEEPS Nanite off for every airframe" in text
    assert "FAssetCompilingManager::Get().FinishAllCompilation();" in COMMANDLET.read_text(encoding="utf-8")


# -- model candidates -----------------------------------------------------------

def test_no_candidate_with_a_forbidden_licence_is_redistributable():
    for candidate in models.CANDIDATES:
        if "NC" in candidate["licence"].split("-") or "store" in candidate["licence"]:
            assert not models.licence_ok(candidate["licence"]), candidate["id"]
        assert candidate["url"].startswith("https://")
    assert models.licence_ok("CC-BY-4.0") and models.licence_ok("GPL-2.0-or-later")
    assert not models.licence_ok("CC-BY-NC-4.0")


def test_a_candidate_is_usable_only_with_a_licence_a_provenance_and_a_pin():
    for candidate in models.CANDIDATES:
        assert models.usable(candidate) == (models.licence_ok(candidate["licence"])
                                            and candidate.get("provenance") == "ok"
                                            and bool(candidate.get("sha256")))
        if candidate.get("sha256"):
            assert re.fullmatch(r"[0-9a-f]{64}", candidate["sha256"]), candidate["id"]
        if candidate["id"].endswith("_rejected"):
            assert not models.usable(candidate), candidate["id"]
    # 2026-11-09 pin audit: only the FGAddon Su-33 tree was fetched (WebDAV at
    # r18942) and digested; every Sketchfab model needs an account token.
    assert {c["id"] for c in models.CANDIDATES if models.usable(c)} == {"su33_fgaddon_helijah"}
    # an uploader who says the model is not theirs cannot grant its CC label
    by_id = {c["id"]: c for c in models.CANDIDATES}
    assert models.licence_ok(by_id["j15_42manako_sketchfab_rejected"]["licence"])
    assert not models.provenance_ok(by_id["j15_42manako_sketchfab_rejected"])


def test_a_fetch_refuses_an_unpinned_unredistributable_or_unprovenanced_candidate(tmp_path):
    by_id = {c["id"]: c for c in models.CANDIDATES}
    with pytest.raises(SystemExit, match="not redistributable"):
        models.fetch(by_id["su30mki_sketchfab_rejected"], tmp_path / "x", record_pin=False)
    with pytest.raises(SystemExit, match="no sha256 pinned"):
        models.fetch(by_id["j11_rhinelab_sketchfab"], tmp_path / "y", record_pin=False)
    with pytest.raises(SystemExit, match="provenance"):
        models.fetch(by_id["j11_42manako_sketchfab_rejected"], tmp_path / "z", record_pin=False)


def test_the_webdav_fetch_writes_nothing_outside_the_pinned_folder(tmp_path, monkeypatch):
    candidate = {"id": "t", "dav_root": "https://example.invalid", "dav_path": "/p/!svn/bc/1/A/"}
    monkeypatch.setattr(models, "_dav_list", lambda root, path: ["/p/!svn/bc/2/B/evil.txt"])
    monkeypatch.setattr(models.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("fetched a file outside the pin"))
    with pytest.raises(SystemExit, match="not under"):
        models.fetch_svn_dav(candidate, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_tree_digest_is_order_and_content_sensitive(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_text("1", encoding="utf-8")
    first = models.tree_sha256(tmp_path)
    (tmp_path / "a" / "x.txt").write_text("2", encoding="utf-8")
    assert models.tree_sha256(tmp_path) != first
