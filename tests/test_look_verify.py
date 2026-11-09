"""The beauty look's record and label honesty (core/capture/verify.py
look_record, look_label_alignment; core/capture/beauty_look.py).

Graded on a copy of the engine bundle fixture (a real -quality=beauty
render.json from before the record existed) with the new keys written
into it the way the schema (docs/schemas/render_json_beauty_look.md)
states them."""

import json
import shutil
from pathlib import Path

import pytest

from core.capture import beauty_look as bl
from core.capture.verify import (
    FAIL, FAIL_LOOK_MEASURE_ALTERED, FAIL_LOOK_NOT_ALIGNED, FAIL_LOOK_QUALITY,
    FAIL_LOOK_RECORD, FAIL_LOOK_UNRECORDED, LOOK_ALIGNMENT_TOL_PX, NOT_RUN, PASS,
    verify_look_label_alignment, verify_look_record, verify_run,
)
from core.capture.manifest import read_capture_manifest

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "engine_bundle_min"


@pytest.fixture
def bundle(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(FIXTURE, run)
    return run


def render_json(run):
    return run / "frames" / "chase" / "render.json"


def edit(run, change):
    path = render_json(run)
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def grade(run):
    manifest = read_capture_manifest(run / "capture_manifest.json")
    return verify_look_record(manifest, run), verify_look_label_alignment(manifest, run)


def set_quality(q):
    def change(p):
        p["scene"]["render_quality"] = q
    return change


# -- an old bundle stays valid ---------------------------------------------------

def test_an_old_bundle_grades_its_quality_and_leaves_alignment_not_run(bundle):
    record, alignment = grade(bundle)
    assert record.status == PASS and "older build" in record.detail
    assert alignment.status == NOT_RUN


def test_no_render_is_not_run(tmp_path):
    manifest = read_capture_manifest(FIXTURE / "capture_manifest.json")
    assert verify_look_record(manifest, tmp_path).status == NOT_RUN
    assert verify_look_label_alignment(manifest, tmp_path).status == NOT_RUN
    assert verify_look_record(manifest, None).status == NOT_RUN


def test_verify_run_on_the_fixture_has_no_look_failure():
    by_name = {c.name: c for c in verify_run(FIXTURE).checks}
    assert by_name["look_record"].status == PASS
    assert by_name["look_label_alignment"].status == NOT_RUN


# -- quality ------------------------------------------------------------------------

@pytest.mark.parametrize("quality", ["measure", "beauty"])
def test_known_qualities_pass(bundle, quality):
    edit(bundle, set_quality(quality))
    assert grade(bundle)[0].status == PASS


def test_pathtrace_must_state_its_samples(bundle):
    edit(bundle, set_quality("pathtrace"))
    record, _ = grade(bundle)
    assert record.status == FAIL and record.failure == FAIL_LOOK_RECORD
    edit(bundle, lambda p: p.update(beauty_samples={"path_tracer_spp": 2048}))
    assert grade(bundle)[0].status == PASS


def test_an_unknown_quality_is_refused_by_name(bundle):
    edit(bundle, set_quality("cinematic"))
    record, _ = grade(bundle)
    assert record.failure == FAIL_LOOK_QUALITY


def test_root_quality_is_read_when_scene_lacks_it():
    assert bl.quality_of({"quality": "pathtrace"}) == "pathtrace"
    assert bl.quality_of({"scene": {"render_quality": "measure"}, "quality": "beauty"}) == "measure"
    assert bl.quality_of({}) is None


# -- measure stays measure -------------------------------------------------------------

def test_measure_with_a_look_is_refused(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, lambda p: p.update(beauty_look={"tonemapper": "aces", "bloom": 0.2}))
    assert grade(bundle)[0].failure == FAIL_LOOK_MEASURE_ALTERED


def test_measure_with_a_look_that_applies_nothing_passes(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, lambda p: p.update(beauty_look={"applied": False, "note": "measure"}))
    assert grade(bundle)[0].status == PASS


def test_measure_with_a_pixel_moving_effect_is_refused(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, lambda p: p.update(pixel_moving_effects=["lens_distortion"]))
    assert grade(bundle)[0].failure == FAIL_LOOK_MEASURE_ALTERED


def test_measure_with_temporal_samples_is_refused(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, lambda p: p.update(beauty_samples={"temporal": 8, "shutter_s": 0.0}))
    assert grade(bundle)[0].failure == FAIL_LOOK_MEASURE_ALTERED


# -- the record lists what moves pixels ------------------------------------------------

def test_a_pixel_moving_look_key_must_be_listed(bundle):
    edit(bundle, lambda p: p.update(beauty_look={"post": {"chromatic_aberration": 0.4}}))
    record, _ = grade(bundle)
    assert record.failure == FAIL_LOOK_UNRECORDED and "post.chromatic_aberration" in record.detail
    edit(bundle, lambda p: p.update(pixel_moving_effects=[
        {"name": "chromatic_aberration", "on": True,
         "transform": {"kind": "radial_channel_scale", "red": 1.0004, "blue": 0.9996}}]))
    record, alignment = grade(bundle)
    assert record.status == PASS
    assert alignment.status == PASS and "radial_channel_scale" in alignment.detail


def test_temporal_accumulation_over_a_shutter_is_motion_blur(bundle):
    edit(bundle, lambda p: p.update(beauty_samples={"spatial": 1, "temporal": 16, "shutter_s": 1 / 60}))
    assert grade(bundle)[0].failure == FAIL_LOOK_UNRECORDED
    edit(bundle, lambda p: p.update(pixel_moving_effects=[
        {"name": "motion_blur", "max_displacement_px": 0.8, "displacement_basis": "measured"}]))
    record, alignment = grade(bundle)
    assert record.status == PASS and alignment.status == PASS


@pytest.mark.parametrize("samples", [{"temporal": 0}, {"spatial": 2.5}, {"path_tracer_spp": True},
                                     {"shutter_s": -1}])
def test_bad_sample_counts_are_a_malformed_record(bundle, samples):
    edit(bundle, lambda p: p.update(beauty_samples=samples))
    assert grade(bundle)[0].failure == FAIL_LOOK_RECORD


def test_beauty_only_actors_need_an_occlusion_decision(bundle):
    edit(bundle, lambda p: p.update(beauty_only_actors=["StormCloudVolume", "Starfield"]))
    assert grade(bundle)[0].failure == FAIL_LOOK_RECORD
    edit(bundle, lambda p: p.update(cloud_occlusion={"policy": "kept_clear"}))
    record, alignment = grade(bundle)
    assert record.status == PASS and alignment.status == PASS


# -- label alignment -------------------------------------------------------------------

def test_an_effect_with_nothing_recorded_is_beauty_not_label_aligned(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=[{"name": "heat_haze", "on": True}]))
    _, alignment = grade(bundle)
    assert alignment.status == FAIL and alignment.failure == FAIL_LOOK_NOT_ALIGNED
    assert alignment.detail.startswith("beauty-not-label-aligned")


def test_an_uncalibrated_displacement_is_not_evidence(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=[
        {"name": "lens_distortion", "max_displacement_px": 0.3, "displacement_basis": "uncalibrated"}]))
    assert grade(bundle)[1].failure == FAIL_LOOK_NOT_ALIGNED


def test_a_measured_displacement_over_the_tolerance_is_not_aligned(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=[
        {"name": "lens_distortion", "max_displacement_px": LOOK_ALIGNMENT_TOL_PX + 0.5,
         "displacement_basis": "measured"}]))
    assert grade(bundle)[1].failure == FAIL_LOOK_NOT_ALIGNED


def test_an_effect_that_is_off_is_not_graded(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=[{"name": "heat_haze", "on": False}]))
    assert grade(bundle)[1].status == PASS


def test_a_transform_without_a_kind_is_not_a_transform(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=[{"name": "overscan", "transform": {"scale": 1.1}}]))
    assert grade(bundle)[1].failure == FAIL_LOOK_NOT_ALIGNED


@pytest.mark.parametrize("occlusion,ok", [
    ({"policy": "labels_unoccluded", "subject_occluded_fraction": 0.01, "basis": "measured"}, True),
    ({"policy": "labels_unoccluded", "subject_occluded_fraction": 0.2, "basis": "measured"}, False),
    ({"policy": "labels_unoccluded", "subject_occluded_fraction": None}, False),
    ({"policy": "none_in_frame"}, True),
])
def test_a_cloud_over_the_subject(bundle, occlusion, ok):
    edit(bundle, lambda p: p.update(beauty_only_actors=["StormCloudVolume"], cloud_occlusion=occlusion))
    _, alignment = grade(bundle)
    assert (alignment.status == PASS) is ok, alignment.detail


def test_the_beauty_fov_must_be_the_pose_solvers(bundle):
    manifest = read_capture_manifest(bundle / "capture_manifest.json")
    import math
    frame = manifest["frames"][0]
    solver = math.degrees(2 * math.atan(frame["width_px"] / (2 * frame["fx_px"])))
    edit(bundle, lambda p: p.update(beauty_look={"camera": {"fov_deg": solver + 0.05}}))
    assert grade(bundle)[1].status == PASS
    edit(bundle, lambda p: p.update(beauty_look={"camera": {"fov_deg": solver + 2.0}}))
    _, alignment = grade(bundle)
    assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "pose solver" in alignment.detail


def test_labels_from_another_frame_or_instant_are_not_aligned(bundle):
    def other_frame(p):
        p["beauty_look"] = {}
        p["frame_records"][0]["labels"]["mask"] = "frame_00001_mask.png"
    edit(bundle, other_frame)
    _, alignment = grade(bundle)
    assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "frame_00001_mask.png" in alignment.detail


def test_the_labels_instant_must_be_inside_the_beauty_window(bundle):
    def window(lo, hi):
        def change(p):
            p["frame_records"][0]["beauty_window_s"] = [lo, hi]
        return change
    t = json.loads(render_json(bundle).read_text(encoding="utf-8"))["frame_records"][0]["t"]
    edit(bundle, window(t - 0.01, t + 0.01))
    assert grade(bundle)[1].status == PASS
    edit(bundle, window(t + 0.01, t + 0.02))
    assert grade(bundle)[1].failure == FAIL_LOOK_NOT_ALIGNED


def test_verify_run_refuses_a_misaligned_beauty_by_name(bundle):
    edit(bundle, lambda p: p.update(pixel_moving_effects=["lens_distortion"]))
    report = verify_run(bundle)
    assert not report.ok
    assert FAIL_LOOK_NOT_ALIGNED in {c.failure for c in report.failures()}


# -- the pure helpers ------------------------------------------------------------------

@pytest.mark.parametrize("key,value,on", [
    ("motion_blur", True, True), ("motion_blur", 0.0, False), ("motion_blur_amount", 0.5, True),
    ("lens_distortion", {"k1": -0.02}, True), ("lens_distortion", {"enabled": False, "k1": 1}, False),
    ("heat_haze", "off", False), ("heat_haze", "on", True),
    ("screen_percentage", 100, False), ("screen_percentage", 0, False), ("screen_percentage", 66.7, True),
    ("screen_percentage", "absent", False),
])
def test_is_on(key, value, on):
    assert bl.is_on(key, value) is on


def test_look_effects_on_finds_nested_keys():
    found = bl.look_effects_on({"post": {"motion_blur_amount": 0.3, "bloom": 1.0},
                                "panini_d": 0.0, "upscale": True})
    assert sorted(found) == [("post.motion_blur_amount", "motion_blur"), ("upscale", "upscale")]


def test_normalise_effects_reports_nameless_entries():
    effects, problems = bl.normalise_effects(["a", {"name": "b", "on": False}, {"on": True}])
    assert [e["name"] for e in effects] == ["a", "b"] and effects[1]["on"] is False
    assert problems and "[2]" in problems[0]
    assert bl.normalise_effects("x")[1]


# -- review fixes: the measured show flag, nesting, case ------------------------------

def _show_flag_motion_blur(p):
    p["render_settings"]["beauty_show_flags"]["motion_blur"] = True


def test_measured_motion_blur_show_flag_must_be_listed_even_on_an_old_bundle(bundle):
    edit(bundle, _show_flag_motion_blur)
    record, _ = grade(bundle)
    assert record.status == FAIL and record.failure == FAIL_LOOK_UNRECORDED
    assert "beauty_show_flags.motion_blur" in record.detail
    edit(bundle, lambda p: p.update(pixel_moving_effects=[
        {"name": "motion_blur", "max_displacement_px": 0.5, "displacement_basis": "measured"}]))
    assert grade(bundle)[0].status == PASS


def test_measured_motion_blur_show_flag_alters_a_measure_render(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, _show_flag_motion_blur)
    record, _ = grade(bundle)
    assert record.failure == FAIL_LOOK_MEASURE_ALTERED


def test_a_pixel_moving_key_two_objects_deep_is_found():
    found = bl.look_effects_on({"camera": {"lens": {"lens_distortion": {"k1": -0.02}}}})
    assert found == [("camera.lens.lens_distortion", "lens_distortion")]


def test_on_off_words_ignore_case():
    assert not bl.is_on("lens_distortion", {"enabled": "OFF"})
    assert bl.is_on("lens_distortion", {"enabled": "On"})


# -- fix pass (visual overhaul, verifier): the records the host really writes -------

def _host_record():
    """beauty_look in the FFlightSimBeautyLook::Record shape: sidecar, the
    planner's own plan, and the applied rows the host echoes."""
    from core.scene.beauty_look import plan_beauty_look
    plan = plan_beauty_look(54.0, fps=30.0, width_px=1920)
    return {"sidecar": "C:/runs/x/beauty_look.json", "plan": plan,
            "applied": {"camera": {"fov_deg_unchanged": None,
                                   "MotionBlurAmount": plan["camera"]["MotionBlurAmount"],
                                   "MotionBlurTargetFPS": 30},
                        "lens_post": {k: v for k, v in plan["lens_post"].items()
                                      if isinstance(v, (int, float)) and not isinstance(v, bool)},
                        "tonemap": {"tonemapper": "filmic"}}}


def _contract_effects(motion_blur_on):
    return [{"name": n, "on": n == "motion_blur" and motion_blur_on, "transform": None,
             "max_displacement_px": 19.2 if n == "motion_blur" else None,
             "displacement_basis": "bound: MotionBlurMax percent of the width, by construction; "
                                   "not measured", "source": "beauty capture"}
            for n in bl.COMMANDLET_EFFECTS]


def test_the_planners_own_record_grades_as_the_schema_says(bundle):
    look = _host_record()

    def change(p):
        p["beauty_look"] = look
        p["render_settings"]["beauty_show_flags"]["motion_blur"] = True
        p["pixel_moving_effects"] = _contract_effects(True)
        p["beauty_samples"] = {"spatial": 8, "temporal": 1, "still_samples": 8, "shutter_s": 0.0167}
    edit(bundle, change)
    record, alignment = grade(bundle)
    # Consistent: the commandlet lists the motion blur it read back ...
    assert record.status == PASS, record.detail
    # ... and honestly not label aligned: a bound by construction is not a measurement.
    assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "motion_blur" in alignment.detail
    # The plan's descriptive rows are not switches once the host's applied echo exists.
    assert not [k for k, _ in bl.look_effects_on(look) if k.startswith("plan.")]
    # With the readback saying motion blur is off, the applied MotionBlurAmount is still caught.
    edit(bundle, lambda p: p.update(pixel_moving_effects=_contract_effects(False)))
    record, _ = grade(bundle)
    assert record.failure == FAIL_LOOK_UNRECORDED
    assert "applied.camera.MotionBlurAmount" in record.detail


def test_measure_with_the_hosts_applied_record_is_refused(bundle):
    edit(bundle, set_quality("measure"))
    edit(bundle, lambda p: p.update(beauty_look={"sidecar": "s.json", "plan": {},
                                                 "applied": {"exposure": {"ev100": 15.0}}}))
    assert grade(bundle)[0].failure == FAIL_LOOK_MEASURE_ALTERED
    assert bl.look_anything_on({"sidecar": "s.json"})
    assert not bl.look_anything_on({"applied": {}})
    assert not bl.look_anything_on({"applied": {"on": False}, "sidecar": ""})


def test_the_hosts_camelcase_echo_is_read():
    assert bl.look_effects_on({"applied": {"lens_post": {"SceneFringeIntensity": 0.4}}}) == [
        ("applied.lens_post.SceneFringeIntensity", "chromatic_aberration")]
    assert bl.look_effects_on({"applied": {"camera": {"MotionBlurAmount": 0.5}}}) == [
        ("applied.camera.MotionBlurAmount", "motion_blur")]
    assert bl.look_effects_on({"applied": {"lens_post": {"MotionBlurMax": 1.0,
                                                         "ScreenPercentage": 100}}}) == []
    assert bl.look_effects_on({"post": {"PaniniD": 0.2, "ScreenPercentage": 66.7}}) == [
        ("post.PaniniD", "panini"), ("post.ScreenPercentage", "upscale")]
    assert bl.measured_effects_on({"render_settings": {"beauty_show_flags": {
        "scene_color_fringe": True}}}) == [
        ("render_settings.beauty_show_flags.scene_color_fringe", "chromatic_aberration")]


def test_a_commandlet_shaped_pathtrace_render_passes(bundle):
    def change(p):
        p["scene"]["render_quality"] = "pathtrace"
        p["render_settings"]["beauty_path"] = {
            "quality": "pathtrace", "accumulation": {"captures_per_frame": 256},
            "path_tracer": {"samples_per_pixel": 256}}
        effects = _contract_effects(False)
        for e in effects:
            if e["name"] == "path_tracer_filter":
                e["on"] = True
        p["pixel_moving_effects"] = effects
        p["beauty_samples"] = {"spatial": 1, "temporal": 1, "still_samples": 1,
                               "path_tracer_spp": 256, "shutter_s": 0.0}
    edit(bundle, change)
    assert grade(bundle)[0].status == PASS
    # the render path's own record alone states the samples too
    edit(bundle, lambda p: p.update(beauty_samples={"spatial": 1, "temporal": 1, "shutter_s": 0.0}))
    assert grade(bundle)[0].status == PASS
    # two numbers for one PathTraceSpp that disagree are a malformed record
    edit(bundle, lambda p: p.update(beauty_samples={"path_tracer_spp": 128}))
    assert grade(bundle)[0].failure == FAIL_LOOK_RECORD


@pytest.mark.parametrize("change", [
    lambda p: p.update(beauty_samples={"spatial": 4}),
    lambda p: p.update(beauty_samples={"still_samples": 8}),
    lambda p: p["render_settings"].update(beauty_path={"accumulation": {"captures_per_frame": 2}}),
])
def test_measure_with_still_samples_is_refused(bundle, change):
    edit(bundle, set_quality("measure"))
    edit(bundle, change)
    assert grade(bundle)[0].failure == FAIL_LOOK_MEASURE_ALTERED


def _world_frames(*rows):
    def change(p):
        p["beauty_look"] = {}
        p["look_applied"]["world_beauty"] = {"frames": list(rows)}
    return change


def test_a_cloud_flagged_frame_is_not_label_aligned(bundle):
    edit(bundle, _world_frames({"frame": 0, "cloud_occludes_aircraft": True,
                                "cloud_occlusion_complete": True}))
    _, alignment = grade(bundle)
    assert alignment.status == FAIL and alignment.failure == FAIL_LOOK_NOT_ALIGNED
    assert "world lane flags a cloud" in alignment.detail


def test_an_unmodelled_cloud_frame_is_not_label_aligned(bundle):
    edit(bundle, _world_frames({"frame": 0, "cloud_occludes_aircraft": False,
                                "cloud_occlusion_complete": False}))
    _, alignment = grade(bundle)
    assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "not ruled out" in alignment.detail


def test_a_clear_modelled_frame_passes_and_a_measurement_supersedes_the_model(bundle):
    edit(bundle, _world_frames({"frame": 0, "cloud_occludes_aircraft": False,
                                "cloud_occlusion_complete": True}))
    assert grade(bundle)[1].status == PASS
    edit(bundle, _world_frames({"frame": 0, "cloud_occludes_aircraft": True,
                                "cloud_occlusion_complete": True}))
    edit(bundle, lambda p: p.update(cloud_occlusion={
        "policy": "labels_unoccluded", "subject_occluded_fraction": 0.0, "basis": "measured"}))
    assert grade(bundle)[1].status == PASS


def test_the_fov_is_read_where_the_host_writes_it(bundle):
    import math
    manifest = read_capture_manifest(bundle / "capture_manifest.json")
    frame = manifest["frames"][0]
    solver = math.degrees(2 * math.atan(frame["width_px"] / (2 * frame["fx_px"])))
    edit(bundle, lambda p: p.update(
        beauty_look={"applied": {"camera": {"fov_deg_unchanged": solver + 2}}}))
    _, alignment = grade(bundle)
    assert alignment.failure == FAIL_LOOK_NOT_ALIGNED and "pose solver" in alignment.detail
    edit(bundle, lambda p: p.update(beauty_look={}))
    _, alignment = grade(bundle)
    assert alignment.status == PASS and "pose solver" not in alignment.detail
