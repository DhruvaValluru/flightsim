"""no-lumen-and-machine lane (visual overhaul round 2, 2026-11-09).

The first real renders (Windows laptop, ef361bd6) ran under D3D11 /
PCD3D_SM5: no Lumen, no VSM, no Nanite, though the cvars read back 1. This
pins, without an engine:
  * FlightSimBeautyFallback.cpp: detected from the engine's own support
    queries, applied on beauty only (never measure, never pathtrace),
    BEFORE the world lane reads the sky light's intensity, recorded under
    render.json render_settings.beauty_fallback, every engine symbol in
    scripts/check_bridge_api.sh;
  * the render-machine friction: the world look's assets are version-stamped
    and updated in place (never deleted), the model source is checked out
    byte-for-byte (core.autocrlf=false), Gate 6 never grades an earlier
    run's look renders;
  * Gate V gets the depth label and knows terrain's mask id is ground.
"""

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
FALLBACK = (PRIVATE / "FlightSimBeautyFallback.cpp").read_text(encoding="utf-8")
FALLBACK_H = (PRIVATE / "FlightSimBeautyFallback.h").read_text(encoding="utf-8")
CHECK = (ROOT / "scripts/check_bridge_api.sh").read_text(encoding="utf-8")
MATERIALS = (ROOT / "scripts/ue_create_materials.py").read_text(encoding="utf-8")


# -- the no-Lumen fallback (C++ source) --------------------------------------


def test_the_scene_half_runs_on_beauty_only_before_the_world_lane():
    call = COMMANDLET.index("FFlightSimBeautyFallback::ApplyScene(VisualScene, *Params)")
    line = COMMANDLET[COMMANDLET.rindex("\n", 0, call):COMMANDLET.index("\n", call)]
    assert "bBeauty && !bPathTrace" in line and "return Fail(FFlightSimBeautyFallback::LastError())" in line
    # the world lane keeps the sky light's intensity as its lightning-pulse base
    assert call < COMMANDLET.index("if (bBeauty && !WorldBeauty.Build(")
    # and the sky-light capture-once comes after, so it takes the fill
    assert call < COMMANDLET.index("VisualScene.SkyLightComponent->SetCaptureIsDirty();")


def test_the_capture_half_runs_on_the_beauty_capture_before_registration():
    call = COMMANDLET.index("FFlightSimBeautyFallback::ApplyCapture(Capture);")
    line = COMMANDLET[COMMANDLET.rindex("\n", 0, call):COMMANDLET.index("\n", call)]
    assert "bVisual && bBeauty && !bPathTrace" in line
    assert call < COMMANDLET.index("\n\tCapture->RegisterComponent();")
    assert COMMANDLET.count("FFlightSimBeautyFallback::Apply") == 2


def test_the_record_is_written_on_beauty_only_as_render_settings_beauty_fallback():
    write = COMMANDLET.index('RenderSettings->SetObjectField(TEXT("beauty_fallback"), Fallback);')
    gate = COMMANDLET.rindex("if (BeautyPath.IsValid())", 0, write)
    assert write - gate < 800
    assert "FFlightSimBeautyFallback::Record()" in COMMANDLET[gate:write]


def test_detection_is_the_engines_own_queries_not_the_cvars():
    for query in ("DoesPlatformSupportLumenGI(Platform)", "DoesPlatformSupportVirtualShadowMaps(Platform)",
                  "DoesPlatformSupportNanite(Platform)", "DoesPlatformSupportDistanceFields(Platform)",
                  "DoesProjectSupportDistanceFields()", "GMaxRHIShaderPlatform", "GMaxRHIFeatureLevel"):
        assert query in FALLBACK, query
    for key in ("rhi", "feature_level", "shader_platform", "lumen_gi_supported",
                "virtual_shadow_maps_supported", "nanite_supported", "distance_fields_supported"):
        assert f'TEXT("{key}")' in FALLBACK, key
    for path in ('TEXT("lumen")', 'TEXT("fallback")'):
        assert path in FALLBACK


def _takes_fallback(mode, lumen):
    """FFlightSimBeautyFallback::TakesFallback, mirrored from its source."""
    body = FALLBACK[FALLBACK.index("bool FFlightSimBeautyFallback::TakesFallback"):]
    body = body[:body.index("\n}\n")]
    assert 'Mode == TEXT("force")' in body and 'Mode == TEXT("off")' in body
    assert "return !bLumenGiSupported;   // auto" in body
    return True if mode == "force" else False if mode == "off" else not lumen


@pytest.mark.parametrize("mode,lumen,taken", [
    ("auto", False, True), ("auto", True, False), ("force", True, True),
    ("force", False, True), ("off", False, False), ("off", True, False)])
def test_the_fallback_is_taken_where_lumen_cannot_run(mode, lumen, taken):
    assert _takes_fallback(mode, lumen) is taken


def test_the_fallback_look_is_ssgi_ssr_dfao_sky_fill_and_csm():
    capture = FALLBACK[FALLBACK.index("void FFlightSimBeautyFallback::ApplyCapture"):]
    for line in ("Settings.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::ScreenSpace;",
                 "Settings.ReflectionMethod = EReflectionMethod::ScreenSpace;",
                 "Settings.bOverride_DynamicGlobalIlluminationMethod = true;",
                 "Settings.bOverride_ReflectionMethod = true;"):
        assert line in capture, line
    assert "if (!State.bApplied || !State.bFallback" in capture
    for cvar in ("r.SSGI.Quality", "r.SSR.Quality", "r.DistanceFieldAO", "r.AOQuality",
                 "r.Shadow.CSM.MaxCascades", "r.Shadow.MaxCSMResolution", "r.Shadow.MaxResolution"):
        assert f'BeautyFallbackCvar(TEXT("{cvar}")' in FALLBACK, cvar
    for call in ("Sky->SetIntensity(IntensityBefore * BeautyFallbackSkyFill);",
                 "Sky->SetMinOcclusion(BeautyFallbackSkyMinOcclusion);", "Sky->SetCaptureIsDirty();",
                 "SunLight->SetDynamicShadowCascades(BeautyFallbackCsmCascades);",
                 "SunLight->SetCascadeDistributionExponent(BeautyFallbackCsmDistribution);"):
        assert call in FALLBACK, call
    # every constant says it is uncalibrated, and the probe log section is named
    assert "UNCALIBRATED" in FALLBACK and "## no-lumen-fallback" in FALLBACK


def test_an_unknown_mode_refuses_by_its_catalogue_name():
    assert 'TEXT("render.beauty_fallback_mode: -beauty-fallback=%s' in FALLBACK
    catalog = (ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    assert "\nrender.beauty_fallback_mode:\n" in catalog


def test_every_engine_symbol_is_in_the_bridge_check_block():
    block = CHECK[CHECK.index("BEGIN beauty fallback"):CHECK.index("END beauty fallback")]
    for symbol in ("DoesPlatformSupportLumenGI", "DoesPlatformSupportVirtualShadowMaps",
                   "DoesPlatformSupportNanite", "IsRayTracingEnabled", "DoesPlatformSupportDistanceFields",
                   "DoesProjectSupportDistanceFields", "GMaxRHIFeatureLevel", "GMaxRHIShaderPlatform",
                   "LexToString(ERHIFeatureLevel", "LexToString(EShaderPlatform",
                   "bOverride_DynamicGlobalIlluminationMethod", "bOverride_ReflectionMethod",
                   "bOverride_ScreenSpaceReflectionQuality", "ScreenSpaceReflectionQuality;",
                   "SetMinOcclusion", "float MinOcclusion;", "float OcclusionMaxDistance;",
                   "SetDynamicShadowCascades", "SetCascadeDistributionExponent",
                   "int32 DynamicShadowCascades;", "float CascadeDistributionExponent;",
                   "float DynamicShadowDistanceMovableLight;", "uint32 CastShadows:1;"):
        assert symbol in block, symbol
    cvars = set(re.findall(r'TEXT\("(r\.[\w.]+)"\)', FALLBACK))
    checked = set(re.findall(r"^bf_cvar (\S+) ", block, re.M))
    assert cvars <= checked, cvars - checked


def test_the_bridge_check_still_parses():
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts/check_bridge_api.sh")]).returncode == 0


def test_the_header_says_measure_never_reaches_it():
    assert "measure renders never reach ApplyScene" in FALLBACK_H
    assert "static bool ApplyScene(" in FALLBACK_H and "static void ApplyCapture(" in FALLBACK_H


# -- the world look's assets: stamped, updated in place ----------------------


def _function(name):
    tree = ast.parse(MATERIALS)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(MATERIALS, node)
    raise AssertionError(name)


def test_the_three_unstamped_world_assets_carry_a_generation():
    generations = ast.literal_eval(MATERIALS.split("WORLD_GENERATIONS = ", 1)[1].split("\nWORLD_", 1)[0])
    for name in ("MPC_FlightSimWorld", "M_FlightSimTilesBeauty", "M_FlightSimCloudLayers"):
        assert int(generations[name]) >= 2, name
    assert "M_FlightSimScatter" in generations
    assert "unreal.EditorAssetLibrary.set_metadata_tag(material, WORLD_GENERATION_TAG" in _function("finish")


def test_a_stale_world_asset_is_updated_in_place_never_deleted():
    material = _function("_world_beauty_material")
    collection = _function("create_world_collection")
    for body in (material, collection):
        assert ".delete_asset(" not in body
        assert "world_update_wanted(" in body
    assert "delete_all_material_expressions(material)" in material
    assert "set_metadata_tag(collection, WORLD_GENERATION_TAG" in collection
    assert "if graph_stale(name):" not in _function("world_stale")


class _Entry:
    def __init__(self, name=None, default=0.0, ident=None):
        self.props = {"parameter_name": name, "default_value": default}
        self.ident = ident

    def get_editor_property(self, key):
        return self.props[key]

    def set_editor_property(self, key, value):
        self.props[key] = value


def test_the_collection_merge_keeps_each_existing_parameters_identity():
    namespace = {}
    scalars = ast.literal_eval(MATERIALS.split("WORLD_COLLECTION_SCALARS = ", 1)[1].split("\n}", 1)[0] + "\n}")
    namespace["WORLD_COLLECTION_SCALARS"] = scalars
    exec(_function("merged_collection_scalars"), namespace)
    old_wetness = _Entry("Wetness", 0.7, ident="guid-wet")
    extra = _Entry("Legacy", 3.0, ident="guid-legacy")
    merged = namespace["merged_collection_scalars"]([old_wetness, extra], _Entry)
    names = [e.get_editor_property("parameter_name") for e in merged]
    assert names[:len(scalars)] == list(scalars) and names[-1] == "Legacy"
    assert merged[0] is old_wetness and old_wetness.get_editor_property("default_value") == 0.0
    assert "DelightAmount" in names and "DelightBlueGate" in names


# -- the model source: byte-for-byte on every platform -----------------------


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def lf_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("no git on PATH")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    _git("init", "-q", cwd=upstream)
    _git("config", "user.email", "t@example.invalid", cwd=upstream)
    _git("config", "user.name", "t", cwd=upstream)
    (upstream / "model.txt").write_bytes(b"line one\nline two\n")
    _git("add", ".", cwd=upstream)
    _git("-c", "core.autocrlf=false", "commit", "-q", "-m", "x", cwd=upstream)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream, capture_output=True,
                            text=True, check=True).stdout.strip()
    crlf_config = tmp_path / "gitconfig"
    crlf_config.write_text("[core]\n\tautocrlf = true\n", encoding="utf-8")
    return upstream, commit, crlf_config


def _config(tmp_path, upstream, commit):
    config_path = tmp_path / "aircraft" / "x.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    return {"source_dir": "src", "license": {"repo": upstream.as_uri(), "commit": commit}}, config_path


def test_fetch_source_checks_out_the_committed_bytes_under_a_crlf_global(tmp_path, lf_repo, monkeypatch):
    from assets_pipeline import importer
    upstream, commit, crlf_config = lf_repo
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(crlf_config))
    config, config_path = _config(tmp_path, upstream, commit)
    source = importer.fetch_source(config, config_path, report=lambda _: None)
    assert (source / "model.txt").read_bytes() == b"line one\nline two\n"


def test_fetch_source_repairs_an_earlier_crlf_checkout(tmp_path, lf_repo, monkeypatch):
    from assets_pipeline import importer
    upstream, commit, crlf_config = lf_repo
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(crlf_config))
    config, config_path = _config(tmp_path, upstream, commit)
    source = config_path.parent / "src"
    subprocess.run(["git", "clone", "-q", str(upstream), str(source)], check=True, capture_output=True)
    assert (source / "model.txt").read_bytes() == b"line one\r\nline two\r\n"   # the laptop's state
    lines = []
    importer.fetch_source(config, config_path, report=lines.append)
    assert (source / "model.txt").read_bytes() == b"line one\nline two\n"
    assert any("committed bytes" in line for line in lines)
    lines.clear()
    importer.fetch_source(config, config_path, report=lines.append)   # idempotent
    assert any("already at" in line for line in lines)


def test_every_git_call_in_fetch_source_carries_the_byte_flags():
    source = (ROOT / "assets_pipeline/importer.py").read_text(encoding="utf-8")
    body = source[source.index("def fetch_source("):source.index("def verify_source_pins(")]
    assert '"git", "-C"' not in body
    assert 'GIT_BYTES = ("-c", "core.autocrlf=false"' in source


# -- Gate 6 never grades an earlier run's look renders -----------------------


def test_gate6_without_look_does_not_grade_stale_look_renders(tmp_path):
    from experiments import gate6_visual as g6
    for name in ("cloud_above", "cloud_below", "cloud_control", "night"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "render.json").write_text("{}", encoding="utf-8")
    clauses = g6.ungraded_look_clauses(tmp_path)
    assert all(clause.status == "NOT RUN" for clause in clauses)
    assert all(g6.STALE_LOOK_RULE in clause.detail for clause in clauses)
    assert "cloud_above" in clauses[0].detail
    assert g6.stale_look_renders(tmp_path) == ["cloud_above", "cloud_below", "cloud_control", "night"]


def test_gate6_without_look_and_nothing_stale_prints_the_usual_lines(tmp_path):
    from experiments import gate6_visual as g6
    assert g6.ungraded_look_clauses(tmp_path) == g6.look_clauses(tmp_path)


def test_gate6_main_grades_look_clauses_only_under_look():
    source = (ROOT / "experiments/gate6_visual.py").read_text(encoding="utf-8")
    assert "looks = look_clauses(out) if args.look else ungraded_look_clauses(out)" in source


# -- Gate V: the depth label beside the sheet, terrain as ground -------------


def test_the_contact_sheet_copies_what_gate_v_reads(tmp_path):
    from experiments import visual_contact_sheet as vcs
    frames = tmp_path / "run" / "frames" / "chase"
    frames.mkdir(parents=True)
    frame = frames / "frame_0000.png"
    frame.write_bytes(b"png")
    (frames / "frame_0000_depth.f32").write_bytes(b"\0" * 16)
    (frames / "frame_0000.json").write_text(json.dumps(
        {"frame": {"labels": {"horizon": {"polyline_px": [[0, 5], [10, 6]]}}}}), encoding="utf-8")
    (frames / "render.json").write_text(json.dumps({"objects": [
        {"int_id": 1, "class": "aircraft", "role": "primary"},
        {"int_id": 2, "class": "terrain", "role": "scene"},
        {"int_id": 64, "class": "payload", "role": "component"}]}), encoding="utf-8")
    step = tmp_path / "step"
    step.mkdir()
    (step / "a_depth.png").write_bytes(b"stale")   # an earlier sheet's
    written = vcs.copy_gate_v_labels(frame, step, "a")
    assert set(written) == {"a_depth.f32", "a_horizon.json", "a_ids.json"}
    assert (step / "a_depth.f32").read_bytes() == b"\0" * 16
    assert not (step / "a_depth.png").exists()
    assert json.loads((step / "a_horizon.json").read_text(encoding="utf-8"))["polyline_px"] == [[0, 5], [10, 6]]
    assert json.loads((step / "a_ids.json").read_text(encoding="utf-8"))["ground_ids"] == [0, 2]
    sheet = (ROOT / "experiments/visual_contact_sheet.py").read_text(encoding="utf-8")
    assert "gate_v_labels=copy_gate_v_labels(frame, directory, key)" in sheet


def test_gate_v_grades_terrain_labelled_ground(tmp_path):
    """The first renders' failure: terrain is id 2 in the mask, so id 0 alone
    was only the sky -- 0 ground pixels with depth. With the ids file the
    hazy ramp is graded (and passes); without it, NOT RUN as before."""
    from experiments import gate_v_visual as gv
    from tests.test_gate_v_visual import HORIZON, W, scene
    rgb, ids, depth = scene()
    ids = np.where(ids == 0, 0, ids)
    ids[(np.arange(ids.shape[0])[:, None] > HORIZON) & (ids == 0)] = 2   # terrain, as rendered
    step = tmp_path / "head"
    step.mkdir()
    Image.fromarray(np.rint(rgb).astype(np.uint8)).save(step / "a.png")
    Image.fromarray(ids.astype(np.uint8)).save(step / "a_mask.png")
    depth.astype("<f4").tofile(step / "a_depth.f32")
    (step / "a_horizon.json").write_text(json.dumps({"polyline_px": [[0, HORIZON], [W, HORIZON]]}),
                                         encoding="utf-8")
    before = gv.measure_tree(step)["shots"]["a"]["clauses"]
    assert before["aerial_perspective"]["status"] == "NOT RUN"
    (step / "a_ids.json").write_text(json.dumps({"ground_ids": [0, 2]}), encoding="utf-8")
    shot = gv.measure_tree(step)["shots"]["a"]
    assert shot["ground_ids"] == [0, 2] and shot["ground_ids_source"] == "a_ids.json"
    assert shot["clauses"]["aerial_perspective"]["status"] == gv.PASS
    assert shot["clauses"]["horizon_fill"]["status"] == gv.PASS
    assert shot["clauses"]["texel_detail"]["status"] == gv.PASS
    assert shot["clauses"]["specular"]["status"] == gv.PASS   # the airframe is untouched


def test_gate_v_reads_ground_ids_from_the_runs_render_json(tmp_path):
    from experiments import gate_v_visual as gv
    run = tmp_path / "frames"
    run.mkdir()
    (run / "render.json").write_text(json.dumps({"objects": [
        {"int_id": 1, "class": "aircraft", "role": "primary"},
        {"int_id": 2, "class": "terrain", "role": "scene"}]}), encoding="utf-8")
    ids, source = gv._ground_ids(tmp_path / "a.png", run / "frame_0000.png")
    assert ids == (0, 2) and source.endswith("render.json")
    assert gv._ground_ids(tmp_path / "b.png", None) == ((0,), "id 0 only")
