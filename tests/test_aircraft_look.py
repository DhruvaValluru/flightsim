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
import math
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


def _measured_anchor_look():
    """The J-11 look as it stood before the j11-package lane moved its lamps
    and nozzles to the package's own positions: every measured anchor
    (mesh_extreme, fdm_thruster) at once, so the mechanism stays pinned."""
    config = dict(look.load_config("J11"))
    side = lambda i, k, a, o: {"id": i, "kind": k, "anchor": "mesh_extreme",  # noqa: E731
                               "axis": a, "offset_m": o}
    config["lights"] = [
        side("nav_left", "nav_red", "-y", [0.0, 0.05, 0.0]),
        side("nav_right", "nav_green", "+y", [0.0, -0.05, 0.0]),
        side("tail", "nav_white", "-x", [0.05, 0.0, 0.0]),
        side("strobe_left", "strobe", "-y", [-0.15, 0.05, 0.0]),
        side("strobe_right", "strobe", "+y", [-0.15, -0.05, 0.0]),
        side("landing", "landing", "+x", [-7.85, 0.0, -1.5]),
    ]
    config["nozzles"] = [
        {"id": f"engine{i}", "anchor": "fdm_thruster", "index": i, "snap_radius_m": 0.35,
         "radius_m": 0.5, "afterburner": True} for i in (0, 1)]
    return look.validate(config)


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
    manifest = look.build_manifest("J11", _measured_anchor_look(), str(tmp_path), str(J11_FDM))
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
    # "wet": the wet-airframe-canopy module (scripts/aircraft_wet_layer.py WET_DEFAULTS);
    # "condensation": the condensation-solver module.
    assert set(groups) == {"lights", "contrail", "vapour", "afterburner", "heat_haze", "wet",
                           "condensation"}
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


def test_the_glass_is_acrylic_face_on_and_its_fresnel_boost_is_never_clamped_away():
    """F0 = 0.08 x Specular (UE): the canopy's Specular gives acrylic's F0
    (n 1.49, 0.039); the Fresnel node's own 0.04 base is zeroed so face-on
    adds nothing; Specular + ReflectionBoost <= 1, so the saturate never
    swallows the boost (it did at Specular 1.0)."""
    glass = look.CLASS_SCALARS["glass"]
    f0 = look.UE_F0_PER_SPECULAR * glass["Specular"]
    assert f0 == pytest.approx(look.GLASS_F0, abs=0.003)
    assert look.GLASS_F0 == pytest.approx(0.039, abs=0.001)
    assert 0.0 < glass["ReflectionBoost"] <= 1.0 - glass["Specular"]
    text = MASTERS.read_text(encoding="utf-8")
    body = text[text.index("def create_aircraft_glass"):text.index("def create_aircraft_rubber")]
    assert 'fresnel.set_editor_property("base_reflect_fraction", 0.0)' in body
    assert 's["ReflectionBoost"]' in body
    for path in LOOKS:
        overrides = json.loads(path.read_text(encoding="utf-8")).get("class_scalars", {}).get("glass", {})
        assert "Specular" not in overrides and "ReflectionBoost" not in overrides, path.name


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
            # every one, the plume's colours and shocks included (set at build
            # from the look manifest: the flame's luminance is its candela's)
            assert f'TEXT("{parameter}")' in text, parameter
    assert f'TEXT("{look.LOOK_INSTANCE_FOLDER}")' in text
    assert f'TEXT("{look.LOOK_INSTANCE_PREFIX}")' in text
    assert f'TEXT("{look.LOOK_MANIFEST_NAME}")' in text
    assert f'TEXT("{look.LOOK_MANIFEST_MAGIC}")' in text


def test_every_fx_actor_is_its_own_beauty_only_actor_never_an_aircraft_component():
    text = FX_CPP.read_text(encoding="utf-8")
    assert "NewObject<UPointLightComponent>(Aircraft" not in text
    assert not re.search(r"NewObject<\w+>\(\s*Aircraft\b", text)
    # Every actor spawned is listed, in the function that spawns it (the
    # condensation sites: in the same file, their spawn helper returns to the
    # loop that lists them). A new FX actor spawned without being listed
    # would be drawn AND stencilled in the label passes.
    condensation = (FX_CPP.parent / "FlightSimCondensation.cpp").read_text(encoding="utf-8")
    for source, per_function in ((text, True), (condensation, False)):
        spawns = [m for m in re.finditer(r"([\w.]+) = World->SpawnActor<", source)]
        assert len(spawns) == source.count("SpawnActor<") >= 2
        assert source.count("BeautyOnlyActors.Add(") == len(spawns)
        for match in spawns:
            name = match.group(1)
            scope = source
            if per_function:
                start = source.rfind("\n}\n", 0, match.start())
                end = source.find("\n}\n", match.start())
                scope = source[start:end]
            assert f"BeautyOnlyActors.Add({name})" in scope, name
    assert "AttachToActor(Aircraft, FAttachmentTransformRules::KeepRelativeTransform)" in text
    # no wall clock: every time-varying element runs on the FDM's time
    assert "FPlatformTime" not in text and "GetTimeSeconds" not in text
    assert 'ReadProperty(TEXT("simulation/sim-time-sec"))' in text


def test_heat_haze_is_off_unless_asked_and_recorded_as_pixel_moving():
    header = FX_H.read_text(encoding="utf-8")
    text = FX_CPP.read_text(encoding="utf-8")
    assert "bool bHeatHaze = false;" in header
    assert 'AircraftFxSwitch(Params, TEXT("heat-haze="), false, SwitchError)' in text
    assert 'SetBoolField(TEXT("pixel_moving"), true)' in text


@pytest.mark.parametrize("params, haze", [
    ("", False), ("-heat-haze=on", True), ("-heat-haze=1", True), ("-heat-haze=true", True),
    ("-heat-haze=off", False), ("-aircraft-look=off -heat-haze=on", False),
])
def test_the_switch_twin_reads_on_and_off_and_the_aircraft_look_master_switch(params, haze):
    assert look.parse_fx_switches(params)["heat-haze"] is haze


@pytest.mark.parametrize("params", ["-heat-haze=no", "-heat-haze=none", "-contrails=yes",
                                    "-aircraft-look=nah -heat-haze=off"])
def test_a_switch_word_that_is_neither_on_nor_off_is_refused_by_name(params):
    """It used to read as ON: -heat-haze=no drew the pixel-moving haze."""
    with pytest.raises(look.LookError, match=r"^aircraft_look\.switch: "):
        look.parse_fx_switches(params)


def test_the_switch_twin_is_the_cpp_parse():
    text = FX_CPP.read_text(encoding="utf-8")
    body = text[text.index("bool AircraftFxSwitch("):text.index("bool AircraftFxPair(")]
    for word in look.SWITCH_ON + look.SWITCH_OFF:
        assert f'Word == TEXT("{word}")' in body, word
    assert 'TEXT("aircraft_look.switch: ' in body
    parse = text[text.index("void FFlightSimAircraftFXOptions::ParseParams"):]
    parse = parse[:parse.index("\n}\n")]
    for key, default in look.FX_SWITCHES:
        assert f'AircraftFxSwitch(Params, TEXT("{key}"), {str(default).lower()}, SwitchError)' in parse, key
    assert "if (!Options.SwitchError.IsEmpty())" in text
    catalog = (REPO / "core" / "messages" / "catalog.yaml").read_text(encoding="utf-8")
    assert re.search(r"^aircraft_look\.switch:$", catalog, re.M)


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


# -- fix pass: the lamps, the plume and the haze in physical units ---------------

NAV_BULB = REPO / look.SHADER_DIR / "nav_bulb.hlsl"
AFTERBURNER = REPO / look.SHADER_DIR / "afterburner_glow.hlsl"
HEAT_HAZE = REPO / look.SHADER_DIR / "heat_haze.hlsl"


def _squash(text):
    return re.sub(r"\s+", " ", text)


def test_the_bulb_area_is_the_hlsl_falloff_integrated_and_the_cpp_fallback_agrees():
    text = NAV_BULB.read_text(encoding="utf-8")
    assert f"float core = exp(-r2 * {look.NAV_BULB_CORE_K:.1f});" in text
    assert f"float halo = exp(-r2 * {look.NAV_BULB_HALO_K:.1f}) * {look.NAV_BULB_HALO_WEIGHT};" in text
    assert "float2 c = UV * 2.0 - 1.0;" in text
    # an independent midpoint integral of the HLSL formula over the quad
    n = 400
    total = 0.0
    for i in range(n):
        x = -1.0 + (i + 0.5) * 2.0 / n
        for j in range(n):
            y = -1.0 + (j + 0.5) * 2.0 / n
            r2 = x * x + y * y
            total += math.exp(-r2 * 18.0) + 0.15 * math.exp(-r2 * 3.0)
    assert look.nav_bulb_area_factor() == pytest.approx(total * (2.0 / n) ** 2, rel=1e-4)
    cpp = re.search(r"AircraftFxNavBulbAreaFactor = ([\d.]+);", FX_CPP.read_text(encoding="utf-8"))
    assert float(cpp.group(1)) == pytest.approx(look.nav_bulb_area_factor(), rel=1e-6)


def _look_manifest(tmp_path, name="J11"):
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0), (-30, 0, 0)], (0.0, 0.0, 0.0))
    return look.build_manifest(name, look.load_config(name), str(tmp_path), str(J11_FDM))


def test_every_bulb_shows_the_candela_its_light_throws(tmp_path):
    """Face-on, one quad at the bulb's luminance emits L x area: the lamp's
    own candela x gain (no cap, no per-cd fudge): the light on the airframe
    and the lamp the camera sees are one number."""
    manifest = _look_manifest(tmp_path)
    constants = {k: v["value"] for k, v in manifest["constants"]["lights"].items()}
    assert "BulbEmissivePerCd" not in constants and "BulbEmissiveMax" not in constants
    radius_m = constants["BulbRadiusCm"] / 100.0
    area = look.nav_bulb_area_factor() * radius_m ** 2
    assert manifest["lights"]
    for lamp in manifest["lights"]:
        intensity = lamp["bulb_luminance_nits"] * area
        assert intensity == pytest.approx(lamp["candela"] * constants["LightVisualGain"], rel=1e-4), lamp["id"]
    # a 40 cd nav lamp at the J-11's 6 cm bulb: tens of thousands of nits,
    # near white at a noon EV100 15 (1.2 x 2^15 = 39322 cd/m2), as a real one
    nav = next(lamp for lamp in manifest["lights"] if lamp["kind"] == "nav_red")
    assert 2.0e4 < nav["bulb_luminance_nits"] < 6.0e4


def test_a_flashing_lamp_is_driven_at_the_blondel_rey_peak_of_its_effective_minimum(tmp_path):
    manifest = _look_manifest(tmp_path)
    constants = {k: v["value"] for k, v in manifest["constants"]["lights"].items()}
    t, a = constants["StrobeFlashS"], constants["BlondelReyS"]
    flashing = [lamp for lamp in manifest["lights"] if lamp["strobe"]]
    assert flashing
    for lamp in flashing:
        assert lamp["effective_candela"] == look.LIGHT_KINDS[lamp["kind"]][1]
        # the flash the eye integrates: I t / (a + t) is the regulatory minimum
        assert lamp["candela"] * t / (a + t) == pytest.approx(lamp["effective_candela"], rel=1e-4)
    assert look.strobe_peak_candela(400.0, 0.12, 0.2) == pytest.approx(1066.67, abs=0.01)
    for lamp in manifest["lights"]:
        if not lamp["strobe"]:
            assert "effective_candela" not in lamp and lamp["candela"] == look.LIGHT_KINDS[lamp["kind"]][1]


def _cie_y(rgb):
    """CIE 1931 y of a linear sRGB colour (the sRGB / D65 matrix)."""
    r, g, b = rgb
    x = 0.4124 * r + 0.3576 * g + 0.1805 * b
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = 0.0193 * r + 0.1192 * g + 0.9505 * b
    return y / (x + y + z)


def test_the_red_lamps_are_aviation_red():
    """14 CFR 25.1397(a), from memory: aviation red y <= 0.335."""
    for kind in ("nav_red", "beacon_red"):
        assert _cie_y(look.LIGHT_KINDS[kind][0]) <= 0.335, kind


def test_the_landing_bulb_is_a_beam_with_the_spot_lights_own_cone(tmp_path):
    manifest = _look_manifest(tmp_path)
    cone = manifest["constants"]["lights"]["LandingConeDeg"]["value"]
    for lamp in manifest["lights"]:
        if lamp["kind"] == "landing":
            assert lamp["beam_cos"] == [pytest.approx(math.cos(math.radians(0.5 * cone)), abs=1e-6),
                                        pytest.approx(math.cos(math.radians(cone)), abs=1e-6)]
        else:
            assert lamp["beam_cos"] == list(look.OMNI_BEAM_COS)
    text = FX_CPP.read_text(encoding="utf-8")
    assert "Lamp.Spot->SetInnerConeAngle(0.5f * Cone);" in text and "Lamp.Spot->SetOuterConeAngle(Cone);" in text
    hlsl = _squash(NAV_BULB.read_text(encoding="utf-8"))
    assert "BeamCos.y <= -1.0 ? 1.0" in hlsl and "dot(CameraDir, BeamDir)" in hlsl
    masters = MASTERS.read_text(encoding="utf-8")
    assert "MaterialExpressionCameraVectorWS" in masters


def test_the_flame_and_its_light_are_one_number_at_full_glow(tmp_path):
    """The plume's side-on intensity (its luminance over its emitting area,
    both faces of the additive cone) is AfterburnerCandela, the plume light's."""
    manifest = _look_manifest(tmp_path)
    constants = {k: v["value"] for k, v in manifest["constants"]["afterburner"].items()}
    rows = [n for n in manifest["nozzles"] if n["afterburner"]]
    assert rows
    for row in rows:
        assert row["plume_luminance_nits"] * row["plume_effective_area_m2"] == pytest.approx(
            constants["AfterburnerCandela"], rel=1e-3)
        assert 1.0e4 <= row["plume_luminance_nits"] <= 1.0e6
        assert row["plume_core_colour"] == [pytest.approx(c * row["plume_luminance_nits"], rel=1e-3)
                                            for c in look.AFTERBURNER_CORE_HUE]
    assert look._luminance(look.AFTERBURNER_CORE_HUE) == pytest.approx(1.0, abs=1e-3)
    # the integral follows the HLSL and the C++ cone it is drawn on
    hlsl = AFTERBURNER.read_text(encoding="utf-8")
    for line in ("float body = (1.0 - along) * (1.0 - along);",
                 "float diamonds = 0.7 + 0.3 * pow(abs(cos(along * Shocks * 3.14159265)), 6.0);",
                 "float3 colour = lerp(CoreColour, TipColour, along);",
                 "return colour * (Intensity * body * diamonds);"):
        assert line in hlsl, line
    r0, r1 = look.AFTERBURNER_CONE_RADII
    assert (f"AircraftFxConeSection(Mesh, {r0} * Nozzle.RadiusCm, {r1} * Nozzle.RadiusCm, Length);"
            in FX_CPP.read_text(encoding="utf-8"))
    # a thin cylinder of uniform unit luminance: 4 r L of emitting area side-on
    saved = look.AFTERBURNER_CONE_RADII, look.AFTERBURNER_CORE_HUE, look.AFTERBURNER_TIP_HUE
    try:
        look.AFTERBURNER_CONE_RADII = (1.0, 1.0)
        look.AFTERBURNER_CORE_HUE = look.AFTERBURNER_TIP_HUE = (1.0, 1.0, 1.0)
        # body (1 - u)^2 integrates to 1/3; shocks 0 make the diamonds 1.0
        assert look.afterburner_effective_area_m2(100.0, 3.0, 0.0) == pytest.approx(4.0 * 3.0 / 3.0, rel=1e-4)
    finally:
        look.AFTERBURNER_CONE_RADII, look.AFTERBURNER_CORE_HUE, look.AFTERBURNER_TIP_HUE = saved


def _haze_offset(u, local, time_s, strength):
    """heat_haze.hlsl, line for line."""
    fade = (1.0 - min(max(u, 0.0), 1.0)) * min(max(u * 8.0, 0.0), 1.0)
    p = (local[0] / 25.0 + time_s * 6.0, local[1] / 25.0, local[2] / 25.0 + time_s * 1.5)
    a = math.sin(p[0] * 1.7 + math.sin(p[1] * 2.3)) * math.cos(p[2] * 1.9 + p[0] * 0.4)
    b = math.cos(p[1] * 1.3 + math.sin(p[2] * 2.9)) * math.sin(p[0] * 2.1 - p[2] * 0.6)
    return a * strength * 0.01 * fade, b * strength * 0.01 * fade


def test_the_recorded_haze_bound_covers_the_hlsl_envelope_and_the_engine_scale():
    text = HEAT_HAZE.read_text(encoding="utf-8")
    for line in ("float fade = (1.0 - saturate(UV.x)) * saturate(UV.x * 8.0);",
                 "float3 p = LocalPos / 25.0 + float3(TimeS * 6.0, 0.0, TimeS * 1.5);",
                 "return float2(a, b) * (Strength * 0.01 * fade);"):
        assert line in text, line
    strength = look.HEAT_HAZE_DEFAULTS["Strength"]
    bound = look.heat_haze_max_material_offset(strength)
    peak = 0.0
    for i in range(41):
        for j in range(9):
            for k in range(9):
                ox, oy = _haze_offset(i / 40.0, (j * 37.0, k * 23.0 - 90.0, j * k * 3.0), 0.37 * (i + j), strength)
                peak = max(peak, abs(ox), abs(oy))
    assert 0.0 < peak <= bound
    # the engine (DistortionCommon.ush): UV_x = v W k / tan(hFOV/2), UV_y = v W k / tan of the height
    for width, height, fov in ((1920, 1080, 60.0), (3840, 2160, 40.0), (1280, 720, 90.0)):
        scale = width * look.UE_DISTORTION_OFFSET_FUDGE / math.tan(math.radians(fov) / 2.0)
        px = math.hypot(bound * scale * width, bound * scale * height)
        assert look.heat_haze_max_displacement_px(bound, width, height, fov) == pytest.approx(px)
    # 1920 px at 55 degrees: about 8.6 px on x (the old record said 11.5 px of
    # "screen fraction" that was not a bound of anything)
    assert look.heat_haze_max_displacement_px(bound, 1920, 0, 55.0) == pytest.approx(8.55, abs=0.05)
    fx = FX_CPP.read_text(encoding="utf-8")
    assert "max_offset_screen_fraction" not in fx
    assert 'SetNumberField(TEXT("max_material_offset")' in fx
    assert "constexpr double AircraftFxHeatHazeFadePeak = 0.875;" in fx
    assert f"constexpr double AircraftFxDistortionOffsetFudge = {look.UE_DISTORTION_OFFSET_FUDGE};" in fx
    commandlet = COMMANDLET.read_text(encoding="utf-8")
    assert "FFlightSimAircraftFX::HeatHazeMaxDisplacementPx(" in commandlet
    assert 'TryGetNumberField(TEXT("max_material_offset"), HazeOffset)' in commandlet
    api = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")
    assert '"const float OffsetFudgeFactor = 0.00023;"' in api


def test_a_contrail_inside_a_cloud_layer_fades_by_its_cover():
    text = FX_CPP.read_text(encoding="utf-8")
    assert "CloudClear *= 1.0 - FMath::Clamp(Layer.CoverFraction, 0.0, 1.0);" in text
    assert "Trail.BaseOpacity * CloudClear" in text
    assert "AircraftFXOptions.CloudLayers = AircraftCloudLayers;" in COMMANDLET.read_text(encoding="utf-8")


def test_chipped_paint_shows_aluminium_not_iron():
    for cls in ("paint", "bare_metal"):
        r, g, b, _ = look.CLASS_VECTORS[cls]["WearColour"]
        assert min(r, g, b) >= 0.88, cls


def test_no_airliner_sized_lamp_on_the_j11(tmp_path):
    """The 18 cm default bulb is an airliner's wingtip lens and glare."""
    manifest = _look_manifest(tmp_path)
    radius = manifest["constants"]["lights"]["BulbRadiusCm"]["value"]
    assert radius < look.LIGHT_DEFAULTS["BulbRadiusCm"] and radius <= 8.0


# -- fix pass: record and label honesty ------------------------------------------

def test_every_constant_the_fx_reads_is_one_the_manifest_carries_with_the_same_fallback():
    text = FX_CPP.read_text(encoding="utf-8")
    groups = {"lights": look.LIGHT_DEFAULTS, "contrail": look.CONTRAIL_DEFAULTS,
              "vapour": look.VAPOUR_DEFAULTS, "afterburner": look.AFTERBURNER_DEFAULTS,
              "heat_haze": look.HEAT_HAZE_DEFAULTS}
    number = r"([\d.]+(?:e[+-]?\d+)?)"
    plain = re.findall(r'Constant\(TEXT\("(\w+)"\), TEXT\("(\w+)"\), ' + number + r"\)", text)
    assert len(plain) >= 15
    for group, name, fallback in plain:
        assert name in groups[group], (group, name)
        assert float(fallback) == groups[group][name], (group, name)
    ternary = re.findall(r'Constant\(Group, TEXT\("(\w+)"\), (?:Trail\.)?bVapour \? ' + number + " : "
                         + number + r"\)", text)
    assert len(ternary) >= 5
    for name, vapour, contrail in ternary:
        assert float(vapour) == look.VAPOUR_DEFAULTS[name], name
        assert float(contrail) == look.CONTRAIL_DEFAULTS[name], name


def test_a_sampled_livery_is_kept_not_repainted():
    text = FX_CPP.read_text(encoding="utf-8")
    body = text[text.index("void FFlightSimAircraftFX::ApplyMaterials"):]
    body = body[:body.index("\n}\n")]
    branch = body.index('Options.Livery != TEXT("default")')
    assert branch < body.index("Part->SetMaterial(")
    assert "return;" in body[branch:body.index("TInlineComponentArray")]
    assert "AircraftFXOptions.Livery = MeshAirframe.Livery;" in COMMANDLET.read_text(encoding="utf-8")


def test_the_fx_masters_that_hide_nothing_are_additive_and_the_media_translucent():
    text = MASTERS.read_text(encoding="utf-8")
    for name in ("M_NavLightEmissive", "M_AircraftAfterburner"):
        assert re.search(rf'_fx\("{name}", "BLEND_ADDITIVE"', text), name
    for name in ("M_AircraftContrail", "M_AircraftHeatHaze"):
        assert re.search(rf'_fx\("{name}", "BLEND_TRANSLUCENT"', text), name


def test_the_look_config_digest_is_the_named_files(tmp_path):
    _write_model(tmp_path, [(0, 0, 0), (-10, -5, 0), (-10, 5, 0)], (0.0, 0.0, 0.0))
    data = json.loads(Path(look.write_manifest("J11", generated_dir=str(tmp_path))).read_text(encoding="ascii"))
    assert data["look_config"] == "assets/aircraft_config/look/J11.json"
    assert data["look_config_sha256"] == look.sha256_file(look.look_config_path("J11"))
    assert data["look_config_canonical_json_sha256"] == look.sha256_text(
        json.dumps(look.load_config("J11"), sort_keys=True))


def test_the_look_keys_stay_out_of_every_aircraft_config():
    """The aircraft config's sha256 is label provenance in every manifest
    (core/capture/manifest.py asset_digests): no look key may sit in it.
    The set is derived from the look schema (not a hand list), so a look
    key moved into the provenance config fails here."""
    look_only = look.KNOWN_KEYS - {"name", "note", "schema"}
    assert {"light_constants", "condensation", "fg_material"} <= look_only
    for path in CONFIGS:
        config = json.loads(path.read_text(encoding="utf-8"))
        assert not look_only & set(config), (path.name, look_only & set(config))


def test_the_panel_groove_twin_matches_the_hlsl_lines():
    text = _squash((REPO / look.SHADER_DIR / "panel_lines.hlsl").read_text(encoding="utf-8"))
    for line in ("float p = max(pitches[i], 1.0);", "float d = (frac(coords[i] / p + 0.5) - 0.5) * p;",
                 "float w = max(WidthCm, 0.01);", "float halfWidth = 0.5 * w + fw;",
                 "float g = saturate(1.0 - abs(d) / halfWidth);", "g *= saturate(1.0 - fw / (2.0 * w));"):
        assert line in text, line
    import ue_aircraft_master_materials as masters
    twin = _squash(ast.get_source_segment(MASTERS.read_text(encoding="utf-8"), next(
        n for n in _masters_tree().body if isinstance(n, ast.FunctionDef) and n.name == "panel_groove")))
    for line in ("p = max(pitch_cm, 1.0)", "w = max(width_cm, 0.01)", "half = 0.5 * w + fw",
                 "g = min(max(1.0 - abs(d) / half, 0.0), 1.0)", "min(max(1.0 - fw / (2.0 * w), 0.0), 1.0)"):
        assert line in twin, line
    assert masters.panel_groove(10.0, 100.0, 0.4) == 0.0


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
