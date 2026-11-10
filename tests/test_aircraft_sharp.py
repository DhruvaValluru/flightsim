"""aircraft-sharp (visual overhaul round 2): a tack-sharp airframe in a still.

Round 1's stills drew the J-11 as a smeared, ghosted blur. Engine source
(5.7.4) reading: only FEngineLoop::Tick calls FScene::StartFrame, the one
place a primitive's previous transform is rolled forward, and a commandlet
never runs it -- so the airframe's motion vector was its displacement since
spawn. These tests pin the fix's shape (the C++ is uncompiled on this Mac)
and its Python halves; measure and the path tracer must stay untouched.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.capture import camera_motion as cm
from core.capture.beauty_look import look_effects_on
from core.scenario.camera import CameraSpec
from core.scene import beauty_look as bl

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
LOOK_H = (PRIVATE / "FlightSimBeautyLook.h").read_text(encoding="utf-8")
CHECK = REPO / "scripts" / "check_bridge_api.sh"


def _camera(preset="chase", count=0):
    cam = CameraSpec.defaulted(camera_id="cam0", preset=preset)
    cam.set("capture_count", count, frm="test")
    return cam


# -- camera-motion layer: off for stills --------------------------------------


def test_look_motion_skips_a_still_camera_and_keeps_a_clip_camera():
    look = {"switch": "cinematic", "camera_motion": "auto"}

    class Spec:
        cameras = [_camera("chase", 1)]

    assert cm.is_still_camera(Spec.cameras[0])
    assert cm.apply_look_motion(Spec, look) == []
    assert Spec.cameras[0].motion is None             # the plain solve, byte-identical

    class Clip:
        cameras = [_camera("chase", 0)]

    assert not cm.is_still_camera(Clip.cameras[0])
    assert cm.apply_look_motion(Clip, look) == ["cam0"]
    assert Clip.cameras[0].motion["profile"] == "camera_ship"


def test_is_still_camera_reads_defensively():
    class Bare:
        pass

    assert not cm.is_still_camera(Bare())
    assert cm.is_still_camera(type("C", (), {"capture_count": 1})())
    assert not cm.is_still_camera(type("C", (), {"capture_count": "x"})())


# -- the beauty look: the shutter is for clips ---------------------------------


def test_the_plan_states_the_shutter_policy():
    plan = bl.plan_beauty_look(30.0, fps=30.0, width_px=1280)
    policy = plan["camera"]["shutter_policy"]
    assert set(policy) == {"clip", "still", "host"}
    assert "off" in policy["still"] and "180" in policy["clip"]
    assert "ApplyShutterPolicy" in policy["host"]
    assert plan["pixel_effects"]["motion_blur"]["stills"].startswith("off")
    # The clip shutter itself is unchanged (MotionBlurAmount = 180/360).
    assert plan["camera"]["MotionBlurAmount"] == 0.5
    # No policy key is mistaken for a pixel-moving switch.
    assert not any(key.startswith("camera.shutter_policy") for key, _ in look_effects_on(
        {"plan": plan, "applied": {"camera": {"MotionBlurAmount": 0.0}}}))


def test_a_still_record_with_the_shutter_off_lists_no_motion_blur():
    record = {"plan": bl.plan_beauty_look(30.0, fps=30.0, width_px=1280),
              "applied": {"camera": {"MotionBlurAmount": 0.0, "motion_blur_show_flag": False,
                                     "shutter_policy": "still: motion blur OFF"}}}
    assert [name for _, name in look_effects_on(record)] == []
    clip = {"plan": record["plan"], "applied": {"camera": {"MotionBlurAmount": 0.5}}}
    assert [name for _, name in look_effects_on(clip)] == ["motion_blur"]


# -- the host: velocity frame, still policy, beauty only -----------------------


def test_the_host_declares_and_defines_the_shutter_policy():
    assert "static void ApplyShutterPolicy(USceneCaptureComponent2D* Capture, bool bStill);" in LOOK_H
    body = LOOK_CPP.split("void FFlightSimBeautyLook::ApplyShutterPolicy", 1)[1].split("\n}\n", 1)[0]
    assert "SetMotionBlur(false)" in body and "MotionBlurAmount = 0.0f" in body
    assert 'TEXT("shutter_policy")' in body


def test_the_velocity_frame_is_the_engine_loops_own_call():
    helper = RENDER_CPP.split("void RenderBeautyStartSceneFrame(UWorld* World)", 1)[1].split("\n\t}\n", 1)[0]
    assert "World->Scene" in helper
    assert "ENQUEUE_RENDER_COMMAND(FlightSimBeautyStartSceneFrame)" in helper
    assert "SceneInterface->StartFrame();" in helper
    assert '#include "SceneInterface.h"' in RENDER_CPP


def test_every_hook_is_beauty_raster_only():
    """Measure (Gate 6 / Gate 10-R) and the path tracer never reach a hook."""
    assert "const bool bBeautyRaster = bVisual && bBeauty && !bPathTrace;" in RENDER_CPP
    assert ("const bool bBeautyStill = bBeautyRaster && DeliveredFrames <= "
            "RenderBeautyStillMaxFrames;") in RENDER_CPP
    calls = [m.start() for m in re.finditer(r"RenderBeautyStartSceneFrame\(World\);", RENDER_CPP)]
    assert len(calls) == 3
    for at in calls:
        guard = RENDER_CPP[max(0, at - 400):at]
        assert ("if (bVisual && bBeauty && !bPathTrace)" in guard or "if (bBeautyStill)" in guard
                or "if (bBeautyRaster)" in guard), RENDER_CPP[at - 200:at]
    assert "FFlightSimBeautyLook::ApplyShutterPolicy(Capture, bBeautyStill);" in RENDER_CPP


def test_the_still_rolls_the_frame_and_cuts_before_its_sub_captures():
    at = RENDER_CPP.index("FFlightSimBeautyLook::UpdatePerFrame(Capture, Scenario.Aircraft);")
    block = RENDER_CPP[at:at + 2400]
    still = block.index("if (bBeautyStill)")
    cut = block.index("Capture->bCameraCutThisFrame = true;")
    loop = block.index("for (int32 SubFrame = 1; SubFrame < BeautySubFrames; ++SubFrame)")
    after = block.index("if (bBeautyRaster)")
    assert still < cut < loop < after
    # Nothing steps or moves between the sub-captures (one sim time, one pose).
    sub = block[loop:after]
    assert "Step(" not in sub and "ApplyPoseAtTime" not in sub and "SetActor" not in sub


def test_the_render_record_names_what_ran():
    for key in ("aircraft_sharp", "motion_blur_rule", "velocity_frame", "still_sub_captures",
                "aircraft_writes_velocity", "aircraft_primitives_movable", "platform_supports_tsr",
                "capture_realtime", "resolved"):
        assert f'TEXT("{key}")' in RENDER_CPP, key
    assert "SupportsTSR(GMaxRHIShaderPlatform)" in RENDER_CPP


# -- the engine surface is checked before a build ------------------------------


def test_the_check_script_block_is_present_and_valid():
    text = CHECK.read_text(encoding="utf-8")
    block = text.split("# -- aircraft-sharp (visual overhaul round 2", 1)[1].split(
        "# -- aircraft-sharp -- end", 1)[0]
    for needle in ("virtual void StartFrame() {}", "bCameraCutThisFrame", "SupportsTSR",
                   "ENQUEUE_RENDER_COMMAND(FScene_StartFrame)",
                   "VelocityData.PreviousLocalToWorld = VelocityData.LocalToWorld;"):
        assert needle in block, needle
    assert subprocess.run(["bash", "-n", str(CHECK)]).returncode == 0


# -- the contact sheet says what the render did --------------------------------


def test_the_contact_sheet_caption_reads_the_record():
    from experiments.visual_contact_sheet import sharpness_caption

    assert sharpness_caption(None) is None
    assert sharpness_caption({"beauty_path": {}, "anti_aliasing": {"beauty": "TSR"}}) is None
    still = {"motion_blur": False, "beauty_path": {"aircraft_sharp": {
        "kind": "still", "motion_blur": False, "tsr": {"resolved": "TSR"}}}}
    assert sharpness_caption(still) == "still, no motion blur, TSR"
    old = {"motion_blur": True, "beauty_path": {}}
    assert sharpness_caption(old) == "motion blur ON"
    fell = {"beauty_path": {"aircraft_sharp": {
        "kind": "clip", "motion_blur": True,
        "tsr": {"resolved": "FXAA (TSR fell back: see the three conditions)"}}}}
    assert sharpness_caption(fell) == "clip, motion blur ON, FXAA"
