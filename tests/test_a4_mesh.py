"""The A-4E exterior model: decoded, converted, and tied to the flight model.

The .mdl layout was worked out by measurement (assets_pipeline/mdl_scene.py),
so these tests pin the measured facts: if a decode assumption is wrong the
geometry stops agreeing with the cfg/FDM numbers and something here fails.
"""

import json
import re
from pathlib import Path

import numpy as np
import pytest

from assets_pipeline import a4_mdl_convert, a4_mesh_check as mc, importer
from assets_pipeline.mdl_scene import MdlScene, evaluate

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "assets" / "aircraft_config" / "A4.json"


@pytest.fixture(scope="module")
def scene():
    return MdlScene(mc.MDL)


def test_scene_decodes_a_complete_visible_airframe(scene):
    parts = scene.parts()
    assert 100 < len(parts) < 200
    lo = np.min([p.positions.min(0) for p in parts], axis=0)
    hi = np.max([p.positions.max(0) for p in parts], axis=0)
    # x right, y up, z forward, metres: an 8.3 m span, ~13 m long, 4 m tall
    assert 8.0 < hi[0] - lo[0] < 8.6
    assert 12.5 < hi[2] - lo[2] < 13.5
    assert 3.5 < hi[1] - lo[1] < 4.5


def test_horizontal_tail_is_found_where_the_fdm_expects_it():
    tail = mc.horizontal_tail()
    assert tail["parts"] == 4                       # 2 stabilizer + 2 elevator
    assert 40 < tail["area_ft2"] < 47
    assert 14 < tail["arm_ft"] < 16.5


def test_fdm_tail_metrics_and_pitch_terms_follow_the_mesh():
    from core.fdm import FlightDynamics
    from assets_pipeline import a4_sync

    tail = mc.horizontal_tail()
    fdm = FlightDynamics("A4")
    assert abs(fdm.props.get("metrics/Sh-sqft") - tail["area_ft2"]) < 0.01
    assert abs(fdm.props.get("metrics/lh-ft") - tail["arm_ft"]) < 0.01
    text = (REPO / "assets/fdm_root/aircraft/A4/A4.xml").read_text(encoding="utf-8")
    volume = (tail["area_ft2"] * tail["arm_ft"]) / (
        a4_sync.STOCK_HTAIL_AREA_FT2 * a4_sync.STOCK_HTAIL_ARM_FT)
    stock_cmde_row = -0.5                            # Aeromatic Cmde, mach 0
    assert f"{stock_cmde_row * volume:.4f}" in text


def test_stores_are_hidden_and_gear_is_stowed_at_rest(scene):
    # nothing hangs below the wing in the rest configuration
    assert min(p.positions[:, 1].min() for p in scene.parts()) > -1.2


def test_visibility_expressions():
    assert evaluate("(L:CustomVisibility87, bool)", {}) is False
    assert evaluate("(L:CustomVisibility87, bool)",
                    {"CustomVisibility87": 1}) is True
    assert evaluate("(L:STA2_LOAD, enum) 4 ==", {"STA2_LOAD": 4}) is True
    assert evaluate("(L:ElecticalPowerAvailable, bool) !", {}) is True
    # control flow is not evaluated, and says so rather than guessing
    assert evaluate("(A:X, bool) if{ 1 } els{ 0 }", {}) is None


def test_conversion_writes_a_valid_manifest_and_obj(tmp_path):
    manifest_path = a4_mdl_convert.convert(CONFIG, tmp_path, REPO)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["magic"] == "flightsim-aircraft-mesh"
    assert manifest["fdm"] == "A4" and manifest["fdm_config_name"] == "A-4"
    assert manifest["parts"] == ["body"] and manifest["surfaces"] == []
    assert manifest["articulated"] is False
    assert manifest["source"]["license_first_line"].startswith("A-4 Skyhawk")

    root = manifest_path.parent
    v = vt = vn = 0
    max_face = 0
    faces = 0
    for line in (root / "body.obj").read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            v += 1
        elif line.startswith("vt "):
            vt += 1
        elif line.startswith("vn "):
            vn += 1
        elif line.startswith("f "):
            faces += 1
            max_face = max(max_face, *(int(t.split("/")[0])
                                       for t in line.split()[1:]))
    assert v == vt == vn and max_face == v
    assert faces == manifest["triangles"]["body"]
    for texture in manifest["textures"]:
        assert (root / texture).is_file()
    assert "map_Kd A4E_1.png" in (root / "body.mtl").read_text(encoding="utf-8")


def test_converted_bounds_agree_with_the_flight_models_geometry(tmp_path):
    """UE frame (+X fwd, +Y right, +Z up), cm, origin at the CG datum."""
    manifest = json.loads(
        a4_mdl_convert.convert(CONFIG, tmp_path, REPO).read_text(encoding="utf-8"))
    lo, hi = manifest["bounds_cm"]["min"], manifest["bounds_cm"]["max"]
    ref = mc.fdm_reference()
    ft = 30.48
    assert abs(hi[1] / ft - ref["half_span_ft"]) < 0.3        # right wingtip
    assert abs(lo[1] / ft + ref["half_span_ft"]) < 0.3        # left wingtip
    assert abs(hi[2] / ft - ref["top_ft"]) < 0.3              # fin top
    assert abs(lo[0] / ft - ref["tail_end_ft"]) < 1.0         # tail end
    assert hi[0] / ft > ref["nose_ft"]                        # nose + probe


def test_importer_builds_a_local_model_without_fetching(monkeypatch, tmp_path):
    assert "A4" in importer.configured_aircraft()
    calls = []

    class Done:
        returncode = 0

    monkeypatch.setattr(importer.subprocess, "run",
                        lambda cmd, **kw: calls.append([str(c) for c in cmd])
                        or Done())
    monkeypatch.setattr(importer, "GENERATED", tmp_path)
    manifest = tmp_path / "A4" / "mesh_manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "A4", "parts": ["body"],
                                    "asset_path_root": "/Game/Aircraft/A4"}),
                        encoding="utf-8")
    importer.convert(CONFIG, report=lambda line: None)
    assert any("a4_mdl_convert.py" in part for cmd in calls for part in cmd)
    assert not any("git" in cmd[0] for cmd in calls)


def test_unreal_host_gear_list_matches_the_repo_owned_airframes():
    cpp = (REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/"
           "FlightSimScenarioWorld.cpp").read_text(encoding="utf-8")
    listed = set(re.findall(
        r'RepoOwnedAirframes\[\] = \{([^}]*)\}', cpp)[0].replace(
            "TEXT(", "").replace(")", "").replace('"', "").replace(
            " ", "").split(","))
    owned = {p.name for p in (REPO / "assets/fdm_root/aircraft").iterdir()
             if p.is_dir()}
    assert listed == owned
