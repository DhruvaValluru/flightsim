"""Phase 10, package 3: the sensor model.

A profile says what one camera does to an ideal picture; it is applied
as a seeded post-pass and the labels follow the pixels. Every number is
checked against the model's own arithmetic, the pass is shown to be
reproducible from its seed, and the verifier is shown to fail when the
recorded distortion stops describing the sensor labels.
"""

import copy
import json
import math
from dataclasses import replace

import numpy as np
import pytest

from core.capture.manifest import (
    build_capture_manifest, camera_angular_rate, write_capture_manifest,
)
from core.capture.poses import euler_to_quat, solve_pose_track
from core.capture.profile import (
    DEFAULT_PROFILE, CameraProfileError, apply_profile, apply_profile_to_run,
    available_profiles, distort_normalised, frame_seed, load_profile,
    pinhole_pixel_from_sensor, row_time_s, sensor_labels, sensor_pixel,
    undistort_normalised,
)
from core.capture.schedule import solve_schedule
from core.capture.verify import (
    FAIL, NOT_RUN, PASS, verify_sensor_files, verify_sensor_undistortion,
)
from core.nl.compiler import compile_prompt
from core.scenario.camera import CameraSpec
from core.scenario.spec import SPEC_VERSION, ScenarioSpec

from tests.test_camera_poses import FRAME, make_columns


RECORD = {"width_px": 1280, "height_px": 720, "fx_px": 1244.4, "fy_px": 1244.4,
          "principal_point_px": [640.0, 360.0]}


# -- profiles -------------------------------------------------------------

def test_the_shipped_profiles_load_and_cite_their_source():
    assert set(available_profiles()) >= {"ideal_pinhole", "synthetic_cmos_wide"}
    ideal = load_profile("ideal_pinhole")
    assert ideal.is_ideal and ideal.gain == 1.0 and ideal.source
    cmos = load_profile("synthetic_cmos_wide")
    assert not cmos.is_ideal
    assert cmos.basis == "synthetic"
    assert "ILLUSTRATIVE" in cmos.source and "Brown" in cmos.source
    assert "EMVA 1288" in cmos.source
    assert cmos.gain == pytest.approx(4.0)         # ISO 400 over base 100
    assert len(cmos.sha256) == 64


def test_a_profile_without_a_source_refuses_by_name(tmp_path):
    data = json.loads((tmp_path.parent / "x").parent.joinpath("x").name and "{}")
    data = json.loads(
        __import__("pathlib").Path("assets/camera_profiles/synthetic_cmos_wide.json")
        .read_text(encoding="utf-8"))
    data["source"] = "   "
    data["name"] = "unsourced"
    (tmp_path / "unsourced.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CameraProfileError, match="camera.profile") as info:
        load_profile("unsourced", profile_dir=tmp_path)
    assert "no source" in str(info.value)
    with pytest.raises(CameraProfileError, match="no camera profile"):
        load_profile("nonexistent", profile_dir=tmp_path)


def test_a_profile_with_an_unmodelled_part_refuses(tmp_path):
    import pathlib
    data = json.loads(pathlib.Path("assets/camera_profiles/synthetic_cmos_wide.json")
                      .read_text(encoding="utf-8"))
    data["name"] = "fisheye"
    data["distortion"]["model"] = "kannala-brandt"
    (tmp_path / "fisheye.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CameraProfileError, match="not modelled"):
        load_profile("fisheye", profile_dir=tmp_path)


# -- distortion -------------------------------------------------------------

def test_brown_conrady_forward_matches_the_formula():
    cmos = load_profile("synthetic_cmos_wide")
    x, y = 0.3, -0.2
    r2 = x * x + y * y
    radial = 1 + cmos.k1 * r2 + cmos.k2 * r2 ** 2 + cmos.k3 * r2 ** 3
    xd = x * radial + 2 * cmos.p1 * x * y + cmos.p2 * (r2 + 2 * x * x)
    yd = y * radial + cmos.p1 * (r2 + 2 * y * y) + 2 * cmos.p2 * x * y
    assert distort_normalised(cmos, x, y) == pytest.approx((xd, yd))


def test_undistortion_inverts_distortion_to_float_precision():
    cmos = load_profile("synthetic_cmos_wide")
    for x, y in ((0.0, 0.0), (0.3, -0.2), (-0.5, 0.28), (0.6, 0.6)):
        xd, yd = distort_normalised(cmos, x, y)
        assert undistort_normalised(cmos, xd, yd) == pytest.approx((x, y), abs=1e-9)


def test_the_ideal_profile_maps_every_pixel_to_itself():
    ideal = load_profile("ideal_pinhole")
    assert distort_normalised(ideal, 0.4, -0.3) == (0.4, -0.3)
    assert sensor_pixel(ideal, RECORD, (10.0, 5.0, 100.0), (1.0, 2.0, 3.0)) == \
        pytest.approx((640 + 1244.4 * 0.1, 360 + 1244.4 * 0.05))


# -- rolling shutter ----------------------------------------------------------

def test_row_time_is_a_linear_readout_centred_on_the_frame():
    cmos = load_profile("synthetic_cmos_wide")
    assert row_time_s(cmos, 0.0, 720.0) == pytest.approx(-cmos.readout_s / 2)
    assert row_time_s(cmos, 360.0, 720.0) == pytest.approx(0.0)
    assert row_time_s(cmos, 720.0, 720.0) == pytest.approx(cmos.readout_s / 2)
    assert row_time_s(load_profile("ideal_pinhole"), 100.0, 720.0) == 0.0


def test_sensor_pixel_round_trips_through_the_verifier_s_inverse():
    cmos = load_profile("synthetic_cmos_wide")
    omega = (0.3, -0.8, 0.5)
    for point in ((10.0, 5.0, 100.0), (-40.0, 20.0, 300.0), (0.0, 0.0, 50.0)):
        px = sensor_pixel(cmos, RECORD, point, omega)
        assert px is not None
        back = pinhole_pixel_from_sensor(cmos, RECORD, px[0], px[1], point[2], omega)
        ideal = (640 + 1244.4 * point[0] / point[2], 360 + 1244.4 * point[1] / point[2])
        assert back == pytest.approx(ideal, abs=1e-6)
    assert sensor_pixel(cmos, RECORD, (1.0, 1.0, -5.0), omega) is None


def test_a_yaw_rate_shears_a_vertical_bar_by_the_readout():
    """Rows at the top and bottom of a 50 ms readout under 2 rad/s of
    yaw see the scene turned by +-0.05 rad: fx*tan(0.1) apart."""
    ideal = load_profile("ideal_pinhole")
    rs = replace(ideal, readout_s=0.05)
    rec = {"width_px": 128, "height_px": 72, "fx_px": 124.4, "fy_px": 124.4,
           "principal_point_px": [64.0, 36.0]}
    bar = np.zeros((72, 128, 3))
    bar[:, 60:68] = 1.0
    out = apply_profile(bar, rs, rec, (0.0, 2.0, 0.0), seed=1)
    top = int(np.argmax(out[1, :, 0] > 0.5))
    bottom = int(np.argmax(out[70, :, 0] > 0.5))
    expected = 124.4 * math.tan(0.1)
    assert abs((top - bottom) - expected) < 2.0
    # Without a rate, the shutter does nothing to the picture.
    still = apply_profile(bar, rs, rec, (0.0, 0.0, 0.0), seed=1)
    assert np.allclose(still, np.round(bar * 255) / 255)


# -- exposure, vignetting, noise ---------------------------------------------

def test_the_post_pass_is_reproducible_from_its_seed():
    cmos = load_profile("synthetic_cmos_wide")
    rec = {"width_px": 128, "height_px": 72, "fx_px": 124.4, "fy_px": 124.4,
           "principal_point_px": [64.0, 36.0]}
    img = np.full((72, 128, 3), 0.1)
    a = apply_profile(img, cmos, rec, (0, 0, 0), frame_seed(7, "chase0", 3))
    b = apply_profile(img, cmos, rec, (0, 0, 0), frame_seed(7, "chase0", 3))
    c = apply_profile(img, cmos, rec, (0, 0, 0), frame_seed(7, "chase0", 4))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)
    # Seeds derive from the run seed, camera and frame -- all three.
    assert frame_seed(7, "chase0", 3) != frame_seed(8, "chase0", 3)
    assert frame_seed(7, "chase0", 3) != frame_seed(7, "tower0", 3)


def test_gain_vignetting_and_noise_do_what_they_say():
    cmos = load_profile("synthetic_cmos_wide")
    rec = {"width_px": 128, "height_px": 72, "fx_px": 124.4, "fy_px": 124.4,
           "principal_point_px": [64.0, 36.0]}
    img = np.full((72, 128, 3), 0.1)
    out = apply_profile(img, cmos, rec, (0, 0, 0), seed=3)
    # ISO 400 over base 100 at the reference exposure: x4 at the centre,
    # plus grain -- the mean over a patch is within the shot noise.
    centre = out[30:42, 58:70].mean()
    assert centre == pytest.approx(0.4, abs=0.01)
    # cos^4 fall-off: a pixel at 0.5 normalised radius sees cos^4 of
    # atan(0.5) -- 0.64 -- before the ADC. Measure without noise or
    # distortion, which would move the pixel.
    quiet = replace(cmos, noise_model="none", k1=0.0, k2=0.0, k3=0.0, p1=0.0,
                    p2=0.0, readout_s=0.0)
    out_q = apply_profile(img, quiet, rec, (0, 0, 0), seed=3)
    u = int(round(64 + 0.5 * 124.4))
    expected = 0.4 * (1.0 / math.sqrt(1.25)) ** 4
    assert out_q[36, u].mean() == pytest.approx(expected, abs=0.005)
    # Noise is shot + read: the grain's variance at 0.4 full well is
    # about 0.4*12000 electrons -> sigma/full_well ~ 0.0058, order of
    # magnitude and not more.
    grain = out[30:42, 58:70].std()
    assert 0.002 < grain < 0.02
    # The ideal profile is a no-op up to its own 8-bit ADC.
    ideal = apply_profile(img, load_profile("ideal_pinhole"), rec, (0, 0, 0), 1)
    assert np.allclose(ideal, np.round(img * 255) / 255)


# -- the spec, the manifest and the labels ------------------------------------

def test_spec_version_7_carries_the_profile_and_refuses_version_6():
    assert SPEC_VERSION == 7
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    camera = CameraSpec.defaulted(camera_id="c", preset="chase", aircraft="B747")
    assert str(camera.profile.value) == DEFAULT_PROFILE
    assert str(camera.profile.source) == "default"
    spec.cameras = [camera]
    data = spec.to_dict()
    assert data["spec_version"] == 7
    assert data["cameras"][0]["profile"]["value"] == "ideal_pinhole"
    data["spec_version"] = 6
    with pytest.raises(ValueError, match="spec_version 6"):
        ScenarioSpec.from_dict(data)


def test_an_unknown_profile_refuses_by_name_in_validation():
    from core.capture.validate import validate_cameras

    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    camera = CameraSpec.defaulted(camera_id="c", preset="chase", aircraft="B747")
    camera.set("profile", "leica_q3", frm="stated")
    spec.cameras = [camera]
    violations = validate_cameras(spec)
    assert [v.constraint for v in violations] == ["camera.profile"]
    assert "leica_q3" in violations[0].message


def counted(preset, camera_id, profile=DEFAULT_PROFILE, count=6):
    camera = CameraSpec.defaulted(camera_id=camera_id, preset=preset, aircraft="B747")
    camera.set("capture_count", count, frm="test")
    if profile != DEFAULT_PROFILE:
        camera.set("profile", profile, frm="test")
    return camera


def manifest_with(profile):
    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [counted("chase", "chase0", profile), counted("tower", "tower0")]
    columns = make_columns(duration_s=8.0, roll=lambda t: 20.0 * math.sin(0.5 * t),
                           heading=lambda t: (3.0 * t) % 360.0)
    tracks = [solve_pose_track(columns, c, FRAME) for c in spec.cameras]
    schedules = [solve_schedule(columns, c, FRAME) for c in spec.cameras]
    return build_capture_manifest(spec, columns, FRAME, tracks, schedules,
                                  output_digest="0" * 64), tracks


def test_the_manifest_records_the_profile_and_the_sensor_labels():
    manifest, tracks = manifest_with("synthetic_cmos_wide")
    by_id = {c["camera_id"]: c for c in manifest["cameras"]}
    assert by_id["chase0"]["profile"]["name"] == "synthetic_cmos_wide"
    assert by_id["chase0"]["profile"]["distortion"]["k1"] == -0.25
    assert "ILLUSTRATIVE" in by_id["chase0"]["profile"]["source"]
    assert by_id["tower0"]["profile"]["name"] == "ideal_pinhole"
    for record in manifest["frames"]:
        sensor = record["sensor"]
        assert sensor["profile"] == by_id[record["camera_id"]]["profile"]["name"]
        assert len(sensor["angular_rate_rad_s"]) == 3
        ls = sensor["labels_sensor"]
        assert set(ls["keypoints"]) == set(record["labels"]["keypoints"])
        if record["camera_id"] == "tower0":
            # The ideal profile maps the labels onto themselves.
            for name, kp in ls["keypoints"].items():
                ideal = record["labels"]["keypoints"][name]
                if ideal["u"] is not None:
                    assert kp["u"] == pytest.approx(ideal["u"], abs=1e-9)
                    assert kp["v"] == pytest.approx(ideal["v"], abs=1e-9)
        else:
            # The synthetic lens moves every in-frame keypoint.
            moved = [name for name, kp in ls["keypoints"].items()
                     if kp["u"] is not None
                     and abs(kp["u"] - record["labels"]["keypoints"][name]["u"]) > 0.5]
            assert moved, "a wide barrel lens that moved nothing"


def test_the_angular_rate_is_the_track_s_own():
    """The rate from the quaternions against the rate from the SAME
    track's Euler yaw -- two encodings of one rotation. The chase
    preset's aim lags the turning track, so its yaw rate is its own,
    not the aircraft's nominal 3 deg/s; what must hold is that the
    quaternion-derived rate about the camera's down axis (camera y)
    is the Euler yaw rate times cos(pitch), sample for sample."""
    manifest, tracks = manifest_with(DEFAULT_PROFILE)
    chase = tracks[0]
    for i in range(len(chase.t) - 1):
        rate = camera_angular_rate(chase, i)
        dt = chase.t[i + 1] - chase.t[i]
        dyaw = (chase.yaw_deg[i + 1] - chase.yaw_deg[i] + 180.0) % 360.0 - 180.0
        expected = math.radians(dyaw / dt) * math.cos(math.radians(chase.pitch_deg[i]))
        assert rate[1] == pytest.approx(expected, abs=2e-3), i
    assert any(abs(camera_angular_rate(chase, i)[1]) > 0.01
               for i in range(len(chase.t) - 1)), "the camera never turned"
    # A still camera turns at zero.
    still = replace(chase, quat=tuple(chase.quat[0] for _ in chase.quat))
    assert camera_angular_rate(still, 2) == [0.0, 0.0, 0.0]


def test_sensor_undistortion_passes_clean_and_fails_corrupted():
    manifest, _ = manifest_with("synthetic_cmos_wide")
    assert verify_sensor_undistortion(manifest).status == PASS
    # k1 corrupted in the RECORDED profile: the inverse no longer inverts.
    bad = copy.deepcopy(manifest)
    for block in bad["cameras"]:
        if block["camera_id"] == "chase0":
            block["profile"]["distortion"]["k1"] = -0.10
    check = verify_sensor_undistortion(bad)
    assert check.status == FAIL and "chase0" in check.detail
    # The angular rate dropped: the rolling shutter can no longer be undone.
    bad = copy.deepcopy(manifest)
    for record in bad["frames"]:
        if record["camera_id"] == "chase0":
            record["sensor"]["angular_rate_rad_s"] = [0.0, 0.0, 0.0]
    assert verify_sensor_undistortion(bad).status == FAIL
    # A frame naming a different profile than its camera block.
    bad = copy.deepcopy(manifest)
    bad["frames"][0]["sensor"]["profile"] = "ideal_pinhole"
    assert verify_sensor_undistortion(bad).status == FAIL
    # A version-4 manifest has no sensor block: NOT RUN by name.
    old = copy.deepcopy(manifest)
    for record in old["frames"]:
        del record["sensor"]
    assert verify_sensor_undistortion(old).status == NOT_RUN


def _png(path, width=64, height=36):
    from PIL import Image
    rgb = np.zeros((height, width, 3), dtype=np.uint8)
    rgb[:, :, 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    rgb[:, :, 1] = 128
    Image.fromarray(rgb, mode="RGB").save(path)


def test_the_post_pass_writes_a_sensor_frame_beside_each_rendered_frame(tmp_path):
    manifest, _ = manifest_with("synthetic_cmos_wide")
    # Small frames stand in for the render: the pass reads whatever size
    # is there and the record's intrinsics are the manifest's (1280x720),
    # so scale the intrinsics to the stand-in for this test.
    for record in manifest["frames"]:
        record["width_px"], record["height_px"] = 64, 36
        record["fx_px"] = record["fy_px"] = 62.2
        record["principal_point_px"] = [32.0, 18.0]
    write_capture_manifest(manifest, tmp_path)
    for record in manifest["frames"]:
        path = tmp_path / record["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        _png(path)
    written = apply_profile_to_run(tmp_path, manifest, run_seed=11)
    assert written == {"chase0": 6}            # the ideal tower is untouched
    sensor_json = json.loads((tmp_path / "frames" / "chase0" / "sensor.json")
                             .read_text(encoding="utf-8"))
    assert sensor_json["profile"]["name"] == "synthetic_cmos_wide"
    assert "sRGB" in sensor_json["linear_source"]
    assert len(sensor_json["frames"]) == 6
    for item in sensor_json["frames"]:
        assert (tmp_path / "frames" / "chase0" / item["sensor"]).is_file()
    assert not list((tmp_path / "frames" / "tower0").glob("*_sensor.png"))
    assert verify_sensor_files(manifest, tmp_path).status == PASS
    # Reproducible: the same run seed writes the same bytes.
    first = (tmp_path / "frames" / "chase0" / "frame_0002_sensor.png").read_bytes()
    apply_profile_to_run(tmp_path, manifest, run_seed=11)
    assert (tmp_path / "frames" / "chase0" / "frame_0002_sensor.png").read_bytes() == first
    apply_profile_to_run(tmp_path, manifest, run_seed=12)
    assert (tmp_path / "frames" / "chase0" / "frame_0002_sensor.png").read_bytes() != first
    # A declared sensor frame that is missing fails by name.
    (tmp_path / "frames" / "chase0" / "frame_0002_sensor.png").unlink()
    check = verify_sensor_files(manifest, tmp_path)
    assert check.status == FAIL and "frame_0002_sensor.png" in check.detail
    assert verify_sensor_files(manifest, None).status == NOT_RUN


def test_read_noise_is_what_a_dark_frame_shows():
    """Shot noise vanishes with the signal; read noise does not. A black
    frame through the synthetic sensor is not black: 3.5 electrons of
    read noise against a 12000-electron well and a 12-bit ADC (2.9
    electrons a step) rounds a fair fraction of pixels up to one level.
    Without read noise every pixel is exactly zero -- which is how the
    mutation guard on the read-noise term is caught."""
    cmos = load_profile("synthetic_cmos_wide")
    rec = {"width_px": 128, "height_px": 72, "fx_px": 124.4, "fy_px": 124.4,
           "principal_point_px": [64.0, 36.0]}
    dark = np.zeros((72, 128, 3))
    out = apply_profile(dark, cmos, rec, (0, 0, 0), seed=5)
    lit = float((out > 0).mean())
    assert 0.05 < lit < 0.6, f"{lit:.3f} of a dark frame's pixels are lit"
    # Their level is a few ADC steps: 3.5 electrons of read noise is 1.2
    # steps of a 2.9-electron ADC, and the largest of 27,648 Gaussian
    # draws sits near 4 sigma. Eight steps is 6.7 sigma -- a bound
    # nothing but a wrong model reaches.
    step = 1.0 / (2 ** cmos.bit_depth - 1)
    assert float(out.max()) <= 8 * step + 1e-12
    # And no read noise means a black frame stays black.
    quiet = replace(cmos, read_noise_e=0.0)
    assert not (apply_profile(dark, quiet, rec, (0, 0, 0), seed=5) > 0).any()
