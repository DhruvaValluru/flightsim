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
import math
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


def test_the_beauty_fov_is_written_per_frame_on_beauty_only():
    write = 'Record->SetNumberField(TEXT("beauty_fov_deg"), Capture->FOVAngle);'
    assert write in COMMANDLET
    gate = COMMANDLET.rindex("if (bBeauty)", 0, COMMANDLET.index(write))
    assert COMMANDLET.index(write) - gate < 600
    look = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
    assert 'Echo->SetNumberField(TEXT("fov_deg_unchanged"), Capture->FOVAngle);' in look


def _with_frame_fov(run, offset):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    solver = {Path(str(f["file"])).name: math.degrees(2 * math.atan(f["width_px"] / (2 * f["fx_px"])))
              for f in manifest["frames"] if f.get("camera_id") == "chase"}
    path = run / "frames" / "chase" / "render.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for record in payload["frame_records"]:
        record["beauty_fov_deg"] = solver[record["frame"]] + offset
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_the_commandlets_per_frame_fov_is_compared(bundle):
    _with_frame_fov(bundle, 0.05)
    _, alignment = _grade(bundle, _commandlet_shaped(False, [], {"policy": "none_in_frame"}))
    assert alignment.status == PASS and "frame(s) compared" in alignment.detail, alignment.detail
    _with_frame_fov(bundle, 2.0)
    _, alignment = _grade(bundle, _commandlet_shaped(False, [], {"policy": "none_in_frame"}))
    assert alignment.status == FAIL and "pose solver" in alignment.detail


def test_the_look_dev_records_fov_is_compared(bundle):
    manifest = read_capture_manifest(bundle / "capture_manifest.json")
    frame = next(f for f in manifest["frames"] if f.get("camera_id") == "chase")
    solver = math.degrees(2 * math.atan(frame["width_px"] / (2 * frame["fx_px"])))
    shaped = _commandlet_shaped(False, [], {"policy": "none_in_frame"})
    shaped["beauty_look"]["applied"] = {"camera": {"fov_deg_unchanged": solver + 2.0}}
    _, alignment = _grade(bundle, shaped)
    assert alignment.status == FAIL and "pose solver" in alignment.detail


def test_no_fov_compared_is_not_claimed(bundle):
    _, alignment = _grade(bundle, _commandlet_shaped(False, [], {"policy": "none_in_frame"}))
    assert alignment.status == PASS
    assert "at the pose solver's field of view" not in alignment.detail
    assert "not compared" in alignment.detail


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


# -- the measured cover (2026-11-11): cloud_occlusion graded on beauty -----------

MERGE = _function(COMMANDLET, "void RenderMergeMeasuredCover(")
COVER_SETUP = COMMANDLET[COMMANDLET.index('FString MeasureCoverSwitch = TEXT("on");'):
                         COMMANDLET.index("TArray<TSharedPtr<FJsonValue>> FrameRecords;")]
COVER_FRAME = COMMANDLET[COMMANDLET.index("if (CoverCapture != nullptr && Captured % CoverMeasure.Stride == 0)"):
                         COMMANDLET.index("// S4: under -accumulate the frame's linear file is the accumulation")]


def test_the_measured_cover_is_beauty_raster_only_and_switchable():
    assert 'FParse::Value(*RenderSwitches, TEXT("measure-cover="), MeasureCoverSwitch);' in COVER_SETUP
    assert "render.measure_cover:" in COVER_SETUP
    catalog = (ROOT / "core/messages/catalog.yaml").read_text(encoding="utf-8")
    assert "render.measure_cover:" in catalog
    build = COVER_SETUP.index('NewObject<USceneCaptureComponent2D>(Director, TEXT("CoverCapture"))')
    for gate in ("else if (!bBeautyRaster)", 'else if (MeasureCoverSwitch == TEXT("off"))',
                 "else if (!bLabels)", "if (bPathTrace)"):
        assert COVER_SETUP.index(gate) < build, gate
    # RenderSwitches carries FLIGHTSIM_RENDER_SWITCHES on beauty (the subject meter's channel)
    assert 'GetEnvironmentVariable(TEXT("FLIGHTSIM_RENDER_SWITCHES"))' in COMMANDLET
    # a component of its own: no view state, no TSR, lens-free, pinned flags
    for line in ("CoverCapture->bAlwaysPersistRenderingState = false;",
                 "CoverCapture->ShowFlags.SetTemporalAA(false);",
                 "RenderMakeCoverCapture(CoverCapture);", "RenderPinShowFlags(CoverCapture);"):
        assert line in COVER_SETUP, line
    assert COVER_SETUP.index("RenderPinShowFlags(CoverCapture);") < \
        COVER_SETUP.index("CoverCapture->RegisterComponent();")
    helper = _function(COMMANDLET, "void RenderMakeCoverCapture(")
    assert "RenderMakeLensFree(Cover);" in helper and "WeightedBlendables.Array.Reset();" in helper
    assert "AEM_Manual" in helper


def test_the_measured_cover_never_touches_the_beauty_capture():
    for block in (COVER_SETUP, COVER_FRAME):
        rest = block.replace("CoverCapture->", "")
        assert "Capture->HiddenActors" not in rest.replace("= Capture->HiddenActors;", "")
        assert "Capture->CaptureScene()" not in rest
        assert "ConfigureLabelCapture" not in block
    # shown, then hidden (beauty-only actors and the Cloud flag), then restored
    shown = COVER_FRAME.index("const bool bCoverShown = CoverRead(CoverShown);")
    hide = COVER_FRAME.index("CoverCapture->HiddenActors.Append(CoverBeautyOnly);")
    cloud = COVER_FRAME.index("CoverCapture->ShowFlags.SetCloud(false);")
    hidden = COVER_FRAME.index("CoverRead(CoverHidden)")
    restore = COVER_FRAME.index("CoverCapture->HiddenActors = CoverShownHidden;")
    assert shown < hide < hidden < restore and shown < cloud < hidden
    # after the beauty frame's readback and the labels (the subject mask)
    frame = COMMANDLET.index("if (CoverCapture != nullptr && Captured % CoverMeasure.Stride == 0)")
    assert COMMANDLET.index("!Resource->ReadPixels(Pixels)") < frame
    assert COMMANDLET.index("LabelMaskThisFrame = MoveTemp(Mask);") < frame
    assert "LabelPrimaryIntId" in COVER_FRAME and "RenderCoverRelativeThreshold" in COVER_FRAME


def test_the_merge_writes_measured_only_from_a_measurement():
    assert "RenderMergeMeasuredCover(*Occlusion, *In.Cover);" in CONTRACT
    assert "Contract.Cover = &CoverMeasure;" in COMMANDLET
    measured = MERGE.index('TEXT("basis"), TEXT("measured")')
    assert MERGE.index("if (!Cover.IsMeasured())") < measured
    assert MERGE.index('if (Policy != TEXT("labels_unoccluded"))') < measured
    for key in ("subject_occluded_fraction", "method", "threshold", "capture_px", "frames_measured",
                "modelled_fraction", "modelled_basis", "measured_frames"):
        assert f'TEXT("{key}")' in MERGE, key
    assert 'TEXT("; cover not measured: ")' in MERGE
    # the constants the schema documents
    for line in ("RenderCoverCaptureDivisor = 2;", "RenderCoverRelativeThreshold = 0.10;",
                 "RenderCoverLumaFloorCodes = 3;", "RenderCoverMaskBlockShare = 0.75;",
                 "RenderCoverMaxSampledFrames = 64;"):
        assert line in COMMANDLET, line
    schema = (ROOT / "docs/schemas/render_json_beauty_look.md").read_text(encoding="utf-8")
    assert "-measure-cover=off" in schema and "modelled_fraction" in schema


def _measured_cover(fraction):
    """cloud_occlusion as RenderMergeMeasuredCover writes it for a measured cover."""
    return {
        "policy": "labels_unoccluded", "owner": "world lane", "frames": 1,
        "subject_occluded_fraction": fraction, "basis": "measured",
        "method": "max over the sampled frames of covered / mask pixels",
        "threshold": {"relative_luma": 0.10, "luma_floor_codes": 3, "mask_block_share": 0.75,
                      "basis": "UNCALIBRATED"},
        "capture_px": [960, 540], "frames_measured": 1, "frames_delivered": 1,
        "sample": "every 1 delivered frame(s) from frame 0",
        "measured_frames": [{"frame": "frame_0000.png", "subject_label_pixels": 5000, "mask_pixels": 1200,
                             "changed_pixels": int(round(fraction * 1200)), "fraction": fraction}],
        "modelled_fraction": 0.4, "modelled_basis": "modelled", "modelled_method": "slab model",
        "measured_cover": "-measure-cover=on",
    }


CLOUD = [{"name": "FairCumulus", "source": "world", "hidden_by": "HiddenActors"}]


@pytest.mark.parametrize("fraction,ok", [(0.0, True), (0.02, True), (0.03, True), (0.05, False), (0.4, False)])
def test_a_measured_cover_is_graded_against_the_tolerance(bundle, fraction, ok):
    record, alignment = _grade(bundle, _commandlet_shaped(False, CLOUD, _measured_cover(fraction)))
    assert record.status == PASS, record.detail
    assert (alignment.status == PASS) is ok, alignment.detail
    if not ok:
        assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "cover" in alignment.detail


def test_a_measured_cover_supersedes_the_world_lanes_flagged_frames(bundle):
    shaped = _commandlet_shaped(False, CLOUD, _measured_cover(0.01))
    shaped["look_applied"] = {"world_beauty": {"frames": [
        {"frame": 0, "cloud_occludes_aircraft": True, "cloud_occlusion_complete": False}]}}
    _, alignment = _grade(bundle, shaped)
    assert alignment.status == PASS, alignment.detail


def test_a_cover_that_did_not_run_keeps_the_model_and_is_not_aligned(bundle):
    occlusion = {"policy": "labels_unoccluded", "subject_occluded_fraction": 0.0,
                 "basis": "modelled; cover not measured: -measure-cover=off",
                 "measured_cover": "-measure-cover=off"}
    _, alignment = _grade(bundle, _commandlet_shaped(False, CLOUD, occlusion))
    assert alignment.status == FAIL and alignment.failure == FAIL_LOOK_NOT_ALIGNED
    assert "not measured" in alignment.detail
