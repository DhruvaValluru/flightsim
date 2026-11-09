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


def test_the_rain_blendables_are_read_back_off_the_beauty_capture():
    # Both sample the scene at a shifted UV (M_LensDrops mirrored in a
    # cell, M_WindshieldRain through a drop's refraction): found by their
    # base material in the beauty's WeightedBlendables, bounded, not measured.
    assert "Post.WeightedBlendables.Array" in CONTRACT
    for material, effect in (("M_LensDrops", "lens_drops"), ("M_WindshieldRain", "windshield_rain")):
        assert f'FName(TEXT("{material}"))' in CONTRACT, material
        assert f'RenderPixelEffect(TEXT("{effect}")' in CONTRACT, effect
    assert "Contract.Height = Height;" in COMMANDLET
    look = (PRIVATE / "FlightSimWeatherLook.cpp").read_text(encoding="utf-8")
    weather = (PRIVATE / "FlightSimWeather.cpp").read_text(encoding="utf-8")
    assert "/Game/FlightSim/M_LensDrops.M_LensDrops" in look
    assert "WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, LensDropsInstance))" in look
    assert "/Game/FlightSim/M_WindshieldRain.M_WindshieldRain" in weather
    assert "WeightedBlendables.Array.Add(FWeightedBlendable(1.0f, WindshieldMaterial))" in weather


@pytest.mark.parametrize("effect", ["lens_drops", "windshield_rain"])
def test_a_beauty_with_rain_on_the_glass_is_not_label_aligned(bundle, effect):
    shaped = _commandlet_shaped(False, [], {"policy": "none_in_frame"})
    for entry in shaped["pixel_moving_effects"]:
        if entry["name"] == effect:
            entry.update(on=True, max_displacement_px=64.0,
                         displacement_basis="bound: by construction; not measured")
    record, alignment = _grade(bundle, shaped)
    assert record.status == PASS, record.detail
    assert alignment.status == FAIL and alignment.failure == FAIL_LOOK_NOT_ALIGNED
    assert effect in alignment.detail


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


# -- label captures never inherit the beauty look (integration item 3) ------------

LABEL_OFF = ("AntiAliasing", "TemporalAA", "MotionBlur", "DepthOfField", "Bloom", "LensFlares",
             "Grain", "Vignette", "LocalExposure", "SceneColorFringe", "LensDistortion",
             "Refraction", "PathTracing", "EyeAdaptation", "Translucency", "Cloud", "Fog")


def _lambda(name: str) -> str:
    start = COMMANDLET.index(f"auto {name} = [&]")
    end = COMMANDLET.index("\n\t\t};", start)
    return COMMANDLET[start:end]


def test_every_beauty_only_flag_is_off_on_a_label_capture():
    configure = _lambda("ConfigureLabelCapture")
    for flag in LABEL_OFF:
        assert f"Label->ShowFlags.Set{flag}(false);" in configure, flag
    # label captures are fresh components: nothing is copied from the beauty
    assert "Capture->ShowFlags" not in configure and "Capture->PostProcessSettings" not in configure


def test_label_flags_survive_registration_on_beauty():
    register = _lambda("RegisterLabelCapture")
    assert "if (bBeauty)" in register and "RenderPinShowFlags(Label);" in register
    configured = re.findall(r"ConfigureLabelCapture\((\w+)\);", COMMANDLET)
    for name in set(configured):
        assert f"\t{name}->RegisterComponent();" not in COMMANDLET, name
    assert COMMANDLET.count("RegisterLabelCapture(") == len(configured)


def test_the_beauty_capture_pins_its_flags_before_registering():
    register = COMMANDLET.index("\n\tCapture->RegisterComponent();")
    pin = COMMANDLET.rindex("RenderPinShowFlags(Capture);", 0, register)
    assert "if (bBeauty)" in COMMANDLET[pin - 200:pin]
    helper = _function(COMMANDLET, "int32 RenderPinShowFlags(")
    assert "SetShowFlagSettings(Settings);" in helper and "IterateAllFlags" in helper


def test_the_label_flags_are_recorded_and_a_leak_is_not_label_aligned(bundle):
    for flag in ("anti_aliasing", "motion_blur", "depth_of_field", "grain", "path_tracing"):
        assert f'LabelFlags->SetBoolField(TEXT("{flag}")' in COMMANDLET, flag
    path = bundle / "frames" / "chase" / "render.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["render_settings"]["label_show_flags"] = {"anti_aliasing": True, "bloom": False}
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, alignment = _grade(bundle, _commandlet_shaped(False, [], {"policy": "none_in_frame"}))
    assert alignment.status == FAIL and "anti_aliasing" in alignment.detail


# -- the linear EXR and accumulation captures are lens-free (integration item 4) --

def test_linear_and_accumulate_are_made_lens_free_on_beauty():
    helper = _function(COMMANDLET, "void RenderMakeLensFree(")
    for flag in ("DepthOfField", "MotionBlur", "Bloom", "LensFlares", "Grain", "Vignette",
                 "SceneColorFringe", "LocalExposure"):
        assert f"Flags.Set{flag}(false);" in helper, flag
    assert "Post.DepthOfFieldFocalDistance = 0.0f;" in helper and "Post.MotionBlurAmount = 0.0f;" in helper
    for sibling in ("LinearCapture", "AccumulateCapture"):
        register = COMMANDLET.index(f"\t{sibling}->RegisterComponent();")
        before = COMMANDLET[register - 400:register]
        assert f"RenderMakeLensFree({sibling});" in before and f"RenderPinShowFlags({sibling});" in before
        assert "if (bBeauty)" in before
    assert 'TEXT("linear_capture"), RenderLensFreeRecord(LinearCapture)' in COMMANDLET
    assert 'TEXT("accumulate_capture"), RenderLensFreeRecord(AccumulateCapture)' in COMMANDLET


def test_profile_reads_the_linear_exrs_lens(tmp_path):
    from core.capture.profile import linear_exr_lens
    frame = tmp_path / "frame_0000.png"
    assert linear_exr_lens(frame) == ""
    (tmp_path / "render.json").write_text(json.dumps(
        {"render_settings": {"linear_capture": {"lens": "lens_free"}}}), encoding="utf-8")
    assert linear_exr_lens(frame) == "lens_free"
    (tmp_path / "render.json").write_text("{not json", encoding="utf-8")
    assert linear_exr_lens(frame) == ""
