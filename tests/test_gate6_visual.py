"""Gate 6's measurements, exercised against frames built to lie.

The gate's verdict is only worth what its measurements can refuse. Each test
here constructs the failure the corresponding clause exists to catch -- a far
ridge as crisp as the near one, a "shadow" that is really the aircraft's own
dark body, a sky that pumps with bank -- and asserts the measurement says no.
"""

import json
import math

import numpy as np
import pytest

from experiments.gate6_visual import (
    SKY_BAND_ROWS, TERRAIN_BAND_ROWS, THRESHOLDS, load_rgb,
    measure_aircraft_shadow, measure_exposure, measure_exposure_control,
    measure_extinction, measure_valley_shadow, write_png_rgb,
)

WIDTH, HEIGHT = 320, 180


def frame(sky=(120, 140, 190), ground=(120, 115, 105)):
    """A horizon-split RGB frame: sky above row 90, ground below."""
    rgb = np.zeros((3, HEIGHT, WIDTH), dtype=np.int64)
    for channel in range(3):
        rgb[channel, :90, :] = sky[channel]
        rgb[channel, 90:, :] = ground[channel]
    return rgb


def paint(rgb, x, y, colour, half=8):
    for channel in range(3):
        rgb[channel, y - half:y + half + 1, x - half:x + half + 1] = colour[channel]
    return rgb


def manifest_for(tmp_path, records):
    (tmp_path / "render.json").write_text(json.dumps({
        "frames": len(records),
        "scene": {"visual": True, "exposure": "manual, AutoExposureBias 11.0"},
        "frame_records": records,
    }))
    return tmp_path


def landmark(px, py, visible=True):
    return {"visible": visible, "px": px, "py": py}


# -- extinction -----------------------------------------------------------


def extinction_scene(tmp_path, far_colour):
    """Two 'peaks' against the sky; the near one is always warm rock."""
    rgb = frame()
    near = (150, 130, 100)                     # warm rock against blue sky
    paint(rgb, 80, 88, near)
    paint(rgb, 200, 88, far_colour)
    name = "frame_0000.png"
    write_png_rgb(tmp_path / name, rgb)
    manifest_for(tmp_path, [{
        "frame": name, "t": 1.0, "roll_deg": 0.0,
        "landmarks": {"near_peak": landmark(80, 80),
                      "far_peak": landmark(200, 80)},
    }])
    return tmp_path


def test_a_hazed_far_ridge_is_extinction(tmp_path):
    check = measure_extinction(extinction_scene(tmp_path, (122, 138, 185)))
    assert check.ok, check.detail


def test_a_far_ridge_as_crisp_as_the_near_one_is_not(tmp_path):
    """The old build's look: distance changes nothing. Must fail."""
    check = measure_extinction(extinction_scene(tmp_path, (150, 130, 100)))
    assert not check.ok


def test_a_peak_out_of_frame_is_not_silently_passed(tmp_path):
    directory = extinction_scene(tmp_path, (122, 138, 185))
    manifest = json.loads((directory / "render.json").read_text())
    manifest["frame_records"][-1]["landmarks"]["far_peak"]["visible"] = False
    (directory / "render.json").write_text(json.dumps(manifest))
    check = measure_extinction(directory)
    assert not check.ok
    assert "not in frame" in check.detail


# -- cast shadows ---------------------------------------------------------


def test_terrain_cast_shadows_are_counted_in_the_terrain_band(tmp_path):
    lit = frame()
    shadowed = lit.copy()
    row = (TERRAIN_BAND_ROWS[0] + TERRAIN_BAND_ROWS[1]) // 2
    shadowed[:, row - 20:row + 20, 40:WIDTH - 40] -= 30      # a broad band
    with_path = write_png_rgb(tmp_path / "with.png", shadowed)
    without_path = write_png_rgb(tmp_path / "without.png", lit)
    check = measure_valley_shadow(with_path, without_path)
    area = (2 * 20) * (WIDTH - 80)
    assert (area >= THRESHOLDS["min_valley_shadow_px"]) == check.ok


def test_a_sliver_of_shadow_is_not_a_shadowed_valley(tmp_path):
    lit = frame()
    shadowed = lit.copy()
    shadowed[:, TERRAIN_BAND_ROWS[0] + 5:TERRAIN_BAND_ROWS[0] + 8, 40:80] -= 30
    check = measure_valley_shadow(write_png_rgb(tmp_path / "a.png", shadowed),
                                  write_png_rgb(tmp_path / "b.png", lit))
    assert not check.ok


def test_the_aircrafts_dark_body_is_not_its_shadow(tmp_path):
    """The failure the body-exclusion exists for.

    Hiding the aircraft removes its body -- pixels that were dark aircraft
    over bright ground. Those darken when it appears, exactly like a shadow,
    and they are not one. A measurement without the exclusion reports every
    aircraft as having a ground shadow, including one whose shadow is off.
    """
    hidden = frame()
    present = hidden.copy()
    paint(present, 160, 120, (20, 20, 20), half=12)          # body only
    check = measure_aircraft_shadow(
        write_png_rgb(tmp_path / "with.png", present),
        write_png_rgb(tmp_path / "without.png", hidden))
    assert not check.ok

    # Body plus a genuinely separate darkened patch on the ground: passes.
    with_shadow = present.copy()
    with_shadow[:, 130:160, 40:120] -= 30
    check = measure_aircraft_shadow(
        write_png_rgb(tmp_path / "with2.png", with_shadow),
        write_png_rgb(tmp_path / "without2.png", hidden))
    assert check.ok, check.detail


# -- exposure -------------------------------------------------------------


def exposure_run(tmp_path, sky_for):
    records = []
    for i in range(40):
        t = 0.5 * (i + 1)
        roll = 17.0 * math.sin(max(0.0, (t - 4.0)) / 12.0 * math.pi) \
            if 4.0 <= t <= 16.0 else 0.0
        level = sky_for(t, roll)
        name = f"frame_{i:04d}.png"
        write_png_rgb(tmp_path / name, frame(sky=(level, level, level)))
        records.append({"frame": name, "t": t, "roll_deg": roll})
    manifest_for(tmp_path, records)
    return tmp_path


def test_a_steady_sky_does_not_breathe(tmp_path):
    check = measure_exposure(exposure_run(tmp_path, lambda t, roll: 128))
    assert check.ok, check.detail


def test_a_sky_that_pumps_with_bank_breathes(tmp_path):
    check = measure_exposure(
        exposure_run(tmp_path, lambda t, roll: 128 + int(abs(roll))))
    assert not check.ok


def test_the_clause_is_vacuous_without_banking(tmp_path):
    directory = exposure_run(tmp_path, lambda t, roll: 128)
    manifest = json.loads((directory / "render.json").read_text())
    for record in manifest["frame_records"]:
        record["roll_deg"] = 0.1
    (directory / "render.json").write_text(json.dumps(manifest))
    check = measure_exposure(directory)
    assert not check.ok
    assert "without any banking" in check.detail


def test_the_control_must_actually_pump(tmp_path):
    """A flat auto-exposure control proves the metric measures nothing."""
    directory = exposure_run(tmp_path, lambda t, roll: 128)
    manifest = json.loads((directory / "render.json").read_text())
    manifest["scene"]["exposure"] = "auto (default metering)"
    (directory / "render.json").write_text(json.dumps(manifest))
    check = measure_exposure_control(directory)
    assert not check.ok

    directory2 = tmp_path / "pump"
    directory2.mkdir()
    exposure_run(directory2, lambda t, roll: 128 + int(2.5 * abs(roll)))
    manifest = json.loads((directory2 / "render.json").read_text())
    manifest["scene"]["exposure"] = "auto (default metering)"
    (directory2 / "render.json").write_text(json.dumps(manifest))
    check = measure_exposure_control(directory2)
    assert check.ok, check.detail


def test_a_manual_render_cannot_pose_as_the_control(tmp_path):
    directory = exposure_run(tmp_path,
                             lambda t, roll: 128 + int(2.5 * abs(roll)))
    check = measure_exposure_control(directory)   # manifest says manual
    assert not check.ok
    assert "controls for nothing" in check.detail


# -- the png round trip ---------------------------------------------------


def test_png_writer_round_trips(tmp_path):
    rgb = frame()
    paint(rgb, 50, 50, (200, 10, 30))
    path = write_png_rgb(tmp_path / "roundtrip.png", rgb)
    back = load_rgb(path)
    assert back.shape == rgb.shape
    assert (back == rgb).all()
