"""The render.json contract between the C++ lanes and the verifier
(integration of the visual overhaul, 2026-11-09).

The verifier (core/capture/beauty_look.py, core/capture/verify.py
look_record / look_label_alignment) reads five root keys. The render
commandlet writes them (RenderWriteLookContract, FlightSimRenderCommandlet.cpp;
FFlightSimWorldBeauty::CloudOcclusionRecord, FlightSimClouds.cpp;
FFlightSimBeautyLook::Record). Nothing here compiles or renders: these read
the C++ source and check every key, sub-key and name the verifier needs is
the one written, and that a render.json shaped the way the commandlet
writes it is graded the way the schema says.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from core.capture import beauty_look as bl
from core.capture.manifest import read_capture_manifest
from core.capture.verify import (FAIL, FAIL_LOOK_NOT_ALIGNED, PASS,
                                 verify_look_label_alignment, verify_look_record)

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
COMMANDLET = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
CLOUDS = (PRIVATE / "FlightSimClouds.cpp").read_text(encoding="utf-8")
FIXTURE = ROOT / "tests" / "fixtures" / "engine_bundle_min"


def _function(source: str, signature: str) -> str:
    start = source.index(signature)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        depth += {"{": 1, "}": -1}.get(source[i], 0)
        if depth == 0:
            return source[start:i + 1]
    raise AssertionError(f"unterminated {signature}")


CONTRACT = _function(COMMANDLET, "void RenderWriteLookContract(")
OCCLUSION = _function(CLOUDS, "TSharedPtr<FJsonObject> FFlightSimWorldBeauty::CloudOcclusionRecord() const")


def test_every_key_the_verifier_reads_is_written_by_the_commandlet():
    written = set(re.findall(r'Root(?:->|\.)Set\w+Field\(TEXT\("(\w+)"\)', COMMANDLET))
    missing = set(bl.LOOK_KEYS) - written
    assert not missing, f"render.json keys the verifier reads and no C++ writes: {missing}"


def test_the_contract_is_written_on_beauty_only():
    call = COMMANDLET.index("RenderWriteLookContract(*Root, Contract);")
    gate = COMMANDLET.rindex("if (BeautyPath.IsValid())", 0, call)
    assert call - gate < 2000
    # BeautyPath is allocated only inside the beauty gate (render-path lane).
    assert "BeautyPath = MakeShared<FJsonObject>();" in COMMANDLET


def test_every_effect_name_written_is_one_the_verifier_knows():
    names = re.findall(r'RenderPixelEffect\(TEXT\("(\w+)"\)', CONTRACT)
    assert set(names) == set(bl.COMMANDLET_EFFECTS)
    assert set(names) <= set(bl.EFFECT_NAMES)
    # one entry each
    assert len(names) == len(set(names))


def test_an_effect_entry_has_the_fields_the_verifier_reads():
    entry = _function(COMMANDLET, "TSharedPtr<FJsonObject> RenderPixelEffect(")
    for key in ("name", "on", "transform", "max_displacement_px", "displacement_basis"):
        assert f'TEXT("{key}")' in entry, key
    # nothing written claims a measurement the commandlet does not make
    assert '"measured"' not in CONTRACT


def test_beauty_samples_carries_the_verifier_keys():
    for key in ("spatial", "temporal", "path_tracer_spp", "shutter_s"):
        assert f'Samples->Set' in CONTRACT and f'TEXT("{key}")' in CONTRACT, key
    assert 'Root.SetObjectField(TEXT("beauty_samples"), Samples);' in CONTRACT


def test_occlusion_policies_written_are_the_verifiers():
    policies = set(re.findall(r'TEXT\("policy"\), TEXT\("(\w+)"\)', CONTRACT + OCCLUSION))
    assert policies and policies <= set(bl.OCCLUSION_POLICIES)
    for key in ("policy", "subject_occluded_fraction", "basis"):
        assert f'TEXT("{key}")' in OCCLUSION
    # the world lane's fraction is a model, never stated as measured
    assert 'TEXT("basis"), TEXT("modelled")' in OCCLUSION


def test_the_look_dev_record_spellings_are_pixel_moving_keys():
    look = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
    for spelling, effect in (("MotionBlurAmount", "motion_blur"),
                             ("SceneFringeIntensity", "chromatic_aberration")):
        assert spelling in look
        assert bl.PIXEL_MOVING_KEYS[spelling] == effect


# -- a render.json shaped as the commandlet writes it ---------------------------

def _commandlet_shaped(motion_blur_on: bool, actors: list, occlusion: dict) -> dict:
    effects = [{"name": name, "on": name == "motion_blur" and motion_blur_on,
                "transform": None, "max_displacement_px": 19.2 if name == "motion_blur" else None,
                "displacement_basis": "bound: MotionBlurMax percent of the width, by construction; not measured",
                "source": "beauty capture"} for name in bl.COMMANDLET_EFFECTS]
    return {
        "pixel_moving_effects": effects,
        "beauty_samples": {"spatial": 8, "temporal": 1, "still_samples": 8, "tsr_history_samples": 32,
                           "shutter_s": 0.1 if motion_blur_on else 0.0},
        "beauty_only_actors": actors,
        "cloud_occlusion": occlusion,
        "beauty_look": {"plan": {"camera": {"MotionBlurAmount": 0.5 if motion_blur_on else 0.0},
                                 "pixel_effects": {"motion_blur": {"on": motion_blur_on}}}},
    }


@pytest.fixture
def bundle(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    return run


def _grade(run, extra):
    path = run / "frames" / "chase" / "render.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["scene"]["render_quality"] = "beauty"
    payload.update(extra)
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest = read_capture_manifest(run / "capture_manifest.json")
    return verify_look_record(manifest, run), verify_look_label_alignment(manifest, run)


def test_a_lens_free_beauty_with_nothing_beauty_only_is_aligned(bundle):
    record, alignment = _grade(bundle, _commandlet_shaped(False, [], {"policy": "none_in_frame"}))
    assert record.status == PASS, record.detail
    assert alignment.status == PASS, alignment.detail


def test_the_commandlets_motion_blur_record_is_consistent_but_not_label_aligned(bundle):
    actors = [{"name": "Rain", "source": "weather", "hidden_by": "HiddenActors"}]
    occlusion = {"policy": "labels_unoccluded", "subject_occluded_fraction": 0.0, "basis": "modelled"}
    record, alignment = _grade(bundle, _commandlet_shaped(True, actors, occlusion))
    assert record.status == PASS, record.detail
    assert alignment.status == FAIL and alignment.failure == FAIL_LOOK_NOT_ALIGNED
    assert "motion_blur" in alignment.detail and "not measured" in alignment.detail


def test_the_record_with_motion_blur_on_and_unlisted_is_refused(bundle):
    shaped = _commandlet_shaped(True, [], {"policy": "none_in_frame"})
    for entry in shaped["pixel_moving_effects"]:
        entry["on"] = False
    record, _ = _grade(bundle, shaped)
    assert record.status == FAIL


# -- one owner per contested setting (integration item 2) -------------------------

LUMEN_RENDER_PATH = ("LumenReflectionQuality", "LumenFinalGatherQuality", "LumenSceneLightingQuality",
                     "LumenMaxTraceDistance", "LumenSceneViewDistance", "LumenSurfaceCacheResolution")


def test_lumen_quality_has_one_owner_the_render_path():
    from core.scene import beauty_look as look
    look_cpp = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
    for key in LUMEN_RENDER_PATH:
        assert f"Settings.bOverride_{key}" not in look_cpp and f"(Reflections, {key})" not in look_cpp, key
        assert key not in look.REFLECTIONS, key
        assert f"Beauty.bOverride_{key} = true;" in COMMANDLET, key


def test_the_order_of_application_is_written_at_the_call_site_and_recorded():
    block = COMMANDLET[COMMANDLET.index("ONE owner per setting"):
                       COMMANDLET.index("FFlightSimVisualScene::ApplyBeautyPostProcess(Capture);")]
    for step in ("Scene build", "World lane", "Exposure", "Look-dev", "Render-path", "Storm meter", "Per frame"):
        assert step in block, step
    assert 'RenderSettings->SetObjectField(TEXT("beauty_owners"), Owners);' in COMMANDLET


def test_the_world_look_leaves_a_sky_plans_transmittance_alone():
    assert "if (!bPhysicalSkyPlan)\n\t\t{\n\t\t\tSunLight->bPerPixelAtmosphereTransmittance = true;" in CLOUDS
    assert 'FParse::Value(Params, TEXT("sky="), SkyPlanArg)' in CLOUDS
