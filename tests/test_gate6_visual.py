"""Gate 6's measurements, exercised against frames built to lie.

The gate's verdict is only worth what its measurements can refuse. Each test
here constructs the failure the corresponding clause exists to catch -- a far
ridge as crisp as the near one, a "shadow" that is really the aircraft's own
dark body, a sky that pumps with bank -- and asserts the measurement says no.
"""

import json
import math
import re

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
    }), encoding="utf-8")
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
    manifest = json.loads((directory / "render.json").read_text(encoding="utf-8"))
    manifest["frame_records"][-1]["landmarks"]["far_peak"]["visible"] = False
    (directory / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
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
    manifest = json.loads((directory / "render.json").read_text(encoding="utf-8"))
    for record in manifest["frame_records"]:
        record["roll_deg"] = 0.1
    (directory / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
    check = measure_exposure(directory)
    assert not check.ok
    assert "without any banking" in check.detail


def test_the_control_must_actually_pump(tmp_path):
    """A flat auto-exposure control proves the metric measures nothing."""
    directory = exposure_run(tmp_path, lambda t, roll: 128)
    manifest = json.loads((directory / "render.json").read_text(encoding="utf-8"))
    manifest["scene"]["exposure"] = "auto (default metering)"
    (directory / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
    check = measure_exposure_control(directory)
    assert not check.ok

    directory2 = tmp_path / "pump"
    directory2.mkdir()
    exposure_run(directory2, lambda t, roll: 128 + int(2.5 * abs(roll)))
    manifest = json.loads((directory2 / "render.json").read_text(encoding="utf-8"))
    manifest["scene"]["exposure"] = "auto (default metering)"
    (directory2 / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
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


# -- Phase 2 look clauses: each built to lie, each refused -----------------

from pathlib import Path  # noqa: E402

from experiments.gate6_visual import (  # noqa: E402
    CLOUD_GROUND_ROWS, LOOK_RUNS, LOOK_THRESHOLDS, koschmieder_fog_density,
    look_clauses, measure_cloud_base, measure_exposure_low_sun,
    measure_extinction_vs_visibility, measure_wet_surface_null,
)

REPO = Path(__file__).resolve().parents[1]
BRIDGE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge"
COMMANDLET = BRIDGE / "Private/FlightSimRenderCommandlet.cpp"
SCENE = BRIDGE / "Private/FlightSimVisualScene.cpp"
DIRECTOR_H = BRIDGE / "Public/FlightSimCameraDirector.h"

CLOUD_HEIGHT, CLOUD_WIDTH = 540, 960


def tall_frame(sky=(120, 140, 190), ground=(120, 115, 105)):
    """The gate's real 960x540 geometry: sky above row 260, ground below,
    so CLOUD_GROUND_ROWS (300..540) is ground and SKY_BAND_ROWS is sky."""
    rgb = np.zeros((3, CLOUD_HEIGHT, CLOUD_WIDTH), dtype=np.int64)
    for channel in range(3):
        rgb[channel, :260, :] = sky[channel]
        rgb[channel, 260:, :] = ground[channel]
    return rgb


def still(directory, rgb, look=None, records=None):
    directory.mkdir(parents=True, exist_ok=True)
    name = "frame_0000.png"
    write_png_rgb(directory / name, rgb)
    manifest = {
        "frames": 1,
        "scene": {"visual": True, "exposure": "manual, AutoExposureBias 11.0"},
        "frame_records": records or [{"frame": name, "t": 1.0, "roll_deg": 0.0}],
    }
    if look is not None:
        manifest["look_applied"] = look
    (directory / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def cloud_scene(tmp_path, above_rows, below_rows):
    """A control still, then 'clouds' painted into the given row bands."""
    control = tall_frame()
    above = control.copy()
    above[:, above_rows[0]:above_rows[1], :] -= 40
    below = control.copy()
    below[:, below_rows[0]:below_rows[1], :] -= 40
    look = {"clouds": {"drawn": True, "cover_parameter": "CloudCoverage"}}
    return (still(tmp_path / "cloud_above", above, look),
            still(tmp_path / "cloud_below", below, look),
            still(tmp_path / "cloud_control", control))


def test_a_layer_above_changes_only_the_sky_and_one_below_only_the_ground(tmp_path):
    clause = measure_cloud_base(*cloud_scene(tmp_path, SKY_BAND_ROWS, CLOUD_GROUND_ROWS))
    assert clause.status == "PASS", clause.detail
    assert clause.ok and clause.ran


def test_a_base_drawn_at_the_wrong_height_fails_the_bracket(tmp_path):
    """The 'above' layer leaking into the ground band: its base is not
    above the camera, whatever the record says."""
    leaking = (SKY_BAND_ROWS[0], CLOUD_GROUND_ROWS[1])
    clause = measure_cloud_base(*cloud_scene(tmp_path, leaking, CLOUD_GROUND_ROWS))
    assert clause.status == "FAIL"


def test_a_layer_that_changes_nothing_is_not_a_cloud(tmp_path):
    clause = measure_cloud_base(*cloud_scene(tmp_path, (0, 0), (0, 0)))
    assert clause.status == "FAIL"


def extinction_pair(tmp_path, clear_far, hazy_far):
    rgb = frame()
    near = (150, 130, 100)
    out = []
    for name, far_colour in (("visibility_clear", clear_far), ("visibility_hazy", hazy_far)):
        image = rgb.copy()
        paint(image, 80, 88, near)
        paint(image, 200, 88, far_colour)
        directory = still(tmp_path / name, image,
                          look={"fog": {"fog_density": koschmieder_fog_density(10.0)}},
                          records=[{"frame": "frame_0000.png", "t": 1.0, "roll_deg": 0.0,
                                    "landmarks": {"near_peak": landmark(80, 80),
                                                  "far_peak": landmark(200, 80)}}])
        out.append(directory)
    return out


def test_a_hazier_day_fades_the_far_ridge_more(tmp_path):
    clear, hazy = extinction_pair(tmp_path, (140, 132, 130), (122, 138, 185))
    clause = measure_extinction_vs_visibility(clear, hazy)
    assert clause.status == "PASS", clause.detail


def test_a_fog_density_that_is_not_an_extinction_shows_no_order(tmp_path):
    """Same far contrast at 50 km and 10 km: the number reached nothing."""
    clear, hazy = extinction_pair(tmp_path, (140, 132, 130), (140, 132, 130))
    clause = measure_extinction_vs_visibility(clear, hazy)
    assert clause.status == "FAIL"


def test_a_peak_out_of_frame_fails_the_visibility_clause_too(tmp_path):
    clear, hazy = extinction_pair(tmp_path, (140, 132, 130), (122, 138, 185))
    manifest = json.loads((hazy / "render.json").read_text(encoding="utf-8"))
    manifest["frame_records"][-1]["landmarks"]["far_peak"]["visible"] = False
    (hazy / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert measure_extinction_vs_visibility(clear, hazy).status == "FAIL"


def wet_scene(tmp_path, terrain_delta, sky_delta, parameter="Wetness"):
    dry = frame()
    wet = dry.copy()
    wet[:, TERRAIN_BAND_ROWS[0]:TERRAIN_BAND_ROWS[1], :] -= terrain_delta
    wet[:, SKY_BAND_ROWS[0]:SKY_BAND_ROWS[1], :] -= sky_delta
    look = {"precipitation": {"precipitation": "rain", "wetness": 1.0,
                              "wetness_parameter": parameter}}
    return still(tmp_path / "wet", wet, look), still(tmp_path / "wet_control", dry)


def test_rain_that_darkens_the_ground_and_not_the_sky_is_wetness(tmp_path):
    clause = measure_wet_surface_null(*wet_scene(tmp_path, 30, 0))
    assert clause.status == "PASS", clause.detail


def test_rain_that_changes_the_sky_fails_the_null(tmp_path):
    """The sky does not get wet; a sky change is another switch."""
    clause = measure_wet_surface_null(*wet_scene(tmp_path, 30, 30))
    assert clause.status == "FAIL"


def test_a_wetness_parameter_the_material_lacks_fails_by_name(tmp_path):
    clause = measure_wet_surface_null(*wet_scene(tmp_path, 30, 0, parameter="absent"))
    assert clause.status == "FAIL"
    assert "absent" in clause.detail


def night_run(tmp_path, sky_for, name="night", ground=(120, 115, 105)):
    directory = tmp_path / name
    directory.mkdir()
    records = []
    for i in range(40):
        t = 0.5 * (i + 1)
        roll = 17.0 * math.sin(max(0.0, (t - 4.0)) / 12.0 * math.pi) \
            if 4.0 <= t <= 16.0 else 0.0
        level = sky_for(t, roll)
        frame_name = f"frame_{i:04d}.png"
        write_png_rgb(directory / frame_name, frame(sky=(level, level, level), ground=ground))
        records.append({"frame": frame_name, "t": t, "roll_deg": roll})
    manifest_for(directory, records)
    manifest = json.loads((directory / "render.json").read_text(encoding="utf-8"))
    manifest["look_applied"] = {"sun": {"sun_elevation_deg": -12.0}}
    (directory / "render.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_a_steady_twilight_sky_holds(tmp_path):
    clause = measure_exposure_low_sun(night_run(tmp_path, lambda t, roll: 40))
    assert clause.status == "PASS", clause.detail


def test_black_night_frames_cannot_pass_the_exposure_clause(tmp_path):
    clause = measure_exposure_low_sun(
        night_run(tmp_path, lambda t, roll: 0, ground=(0, 0, 0)))
    assert clause.status == "FAIL"
    assert "black" in clause.detail


def test_a_twilight_sky_that_pumps_with_bank_breathes(tmp_path):
    clause = measure_exposure_low_sun(
        night_run(tmp_path, lambda t, roll: 40 + int(abs(roll))))
    assert clause.status == "FAIL"


def test_every_look_clause_reports_not_run_with_its_measurement_when_unrendered(tmp_path):
    clauses = look_clauses(tmp_path)
    assert [clause.name for clause in clauses] == [
        "cloud base bracket", "extinction follows visibility",
        "wet surface null test", "exposure holds at -12 deg sun"]
    for clause in clauses:
        assert clause.status == "NOT RUN" and not clause.ran and not clause.ok
        assert clause.measurement, clause.name
        assert "measurement:" in clause.render()


def test_the_look_controls_change_one_switch_each():
    """Every look run is the terrain shot plus its own switch; the control
    of each pair carries the switch's 'off' spelling."""
    assert LOOK_RUNS["cloud_control"][1] == ["-seconds=2", "-cloud-cover=0"]
    assert "-precip=rain" in LOOK_RUNS["wet"][1]
    assert "-precip=none" in LOOK_RUNS["wet_control"][1]
    assert "-sun-elev=-12" in LOOK_RUNS["night"][1]
    clear = [f for f in LOOK_RUNS["visibility_clear"][1] if f.startswith("-fog-density=")][0]
    hazy = [f for f in LOOK_RUNS["visibility_hazy"][1] if f.startswith("-fog-density=")][0]
    assert float(hazy.split("=")[1]) == pytest.approx(3.912 / 10000.0, rel=1e-3)
    assert float(clear.split("=")[1]) == pytest.approx(3.912 / 50000.0, rel=1e-3)
    assert all(shot == "terrain" for shot, _ in LOOK_RUNS.values())
    assert LOOK_THRESHOLDS["cloud_min_changed_px"] > LOOK_THRESHOLDS["cloud_max_leak_px"]


# -- engine source pins (UNCOMPILED here; the text is what can be measured) --


def _vector_literal(source: str, name: str):
    match = re.search(rf"FVector {name} = FVector\(([^)]*)\);", source)
    assert match, name
    return tuple(float(part.strip().rstrip("f")) for part in match.group(1).split(","))


def test_the_camera_director_defaults_are_pythons_constants():
    """The C++ defaults are read from the header text and compared with
    camera.py. What they reach differs, and the header says so: the
    wingman default is live (only -wingman-abeam= overrides it); the chase
    default is a fallback no shipped host flies -- the commandlet's shot
    constants (-170/16, -400/200) and -chase=, and the interactive host's
    own -170/16, override it on every preset-mode run -- so this pins the
    fallback, not a rendered frame."""
    from core.scenario.camera import (FALLBACK_CHASE_OFFSET, SHOULDER_OFFSET,
                                      WINGMAN_OFFSET)

    header = DIRECTOR_H.read_text(encoding="utf-8")
    assert _vector_literal(header, "ChaseOffsetMetres") == tuple(FALLBACK_CHASE_OFFSET)
    assert _vector_literal(header, "WingmanOffsetMetres") == tuple(WINGMAN_OFFSET)
    assert _vector_literal(header, "ShoulderOffsetMetres") == tuple(SHOULDER_OFFSET)


def test_the_commandlet_no_longer_span_scales_the_shoulder_offset():
    source = COMMANDLET.read_text(encoding="utf-8")
    block = re.search(r'CameraPreset == TEXT\("shoulder"\)\)\n\t\{(.*?)\n\t\}', source, re.S)
    assert block, "the shoulder preset block is gone"
    text = block.group(1)
    assert "ShoulderOffsetMetres.Z * Scale" not in text
    assert "metrics/bw-ft" not in text
    assert "*= Scale" not in text
    assert "unscaled" in text


def test_every_label_capture_is_aa_free_per_contracts_section_1():
    """The label-pass rule as text: every show flag the contract lists is
    set false inside ConfigureLabelCapture, and rendering state does not
    persist (no temporal history)."""
    source = COMMANDLET.read_text(encoding="utf-8")
    block = re.search(r"auto ConfigureLabelCapture = \[&\]\(USceneCaptureComponent2D\* Label\)\n\t\t\{(.*?)\n\t\t\};",
                      source, re.S)
    assert block, "ConfigureLabelCapture is gone"
    text = block.group(1)
    for flag in ("AntiAliasing", "TemporalAA", "ScreenPercentage", "Fog", "Atmosphere",
                 "VolumetricFog", "Cloud", "Bloom", "MotionBlur", "DepthOfField",
                 "LensFlares", "Translucency"):
        assert f"Label->ShowFlags.Set{flag}(false);" in text, flag
    assert "Label->bAlwaysPersistRenderingState = false;" in text


def test_render_settings_reads_every_contracted_switch_back():
    """render.json.render_settings: the console variables contracts §10
    names, read through IConsoleManager with 'absent' as the miss value,
    the AA method per capture, exposure mode and EV100, the offsets."""
    source = COMMANDLET.read_text(encoding="utf-8")
    block = re.search(r"TSharedPtr<FJsonObject> RenderSettings = MakeShared<FJsonObject>\(\);(.*?)"
                      r'Root->SetObjectField\(TEXT\("render_settings"\), RenderSettings\);',
                      source, re.S)
    assert block, "render_settings is not written"
    text = block.group(1)
    for name in ("r.AntiAliasingMethod", "r.DynamicGlobalIlluminationMethod",
                 "r.Shadow.Virtual.Enable", "r.Nanite.ProjectEnabled", "r.ScreenPercentage",
                 "r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange", "r.CustomDepth"):
        assert f'TEXT("{name}")' in text, name
    assert 'FString(TEXT("absent"))' in text
    assert "IConsoleManager::Get().FindConsoleVariable(Name)" in text
    for key in ("anti_aliasing", "exposure_mode", "ev100", "cockpit_offset_m",
                "chase_offset_m", "wingman_offset_m", "rhi", "shader_platform"):
        assert f'TEXT("{key}")' in text, key
    assert 'Root->SetObjectField(TEXT("look_applied"), Look);' in source
    assert 'Scene->SetNumberField(TEXT("terrain_posting_m"), VisualScene.TerrainPostingMetres);' in source


def test_the_scene_consumes_exactly_the_look_keys_weather_visuals_defines():
    """The card keys the engine reads are the ones core/scene/weather_visuals.py
    produces -- read from that module's ENGINE_PARAMETERS, not retyped."""
    from core.scene.weather_visuals import CARD_LOOK_KEY, ENGINE_PARAMETERS

    source = COMMANDLET.read_text(encoding="utf-8")
    assert f'TEXT("{CARD_LOOK_KEY}")' in source
    for key in ENGINE_PARAMETERS:
        assert f'TEXT("{key}")' in source, f"look key {key} is not read by the commandlet"
    scene = SCENE.read_text(encoding="utf-8")
    # The scene never applies the card's aerosol (double count); it records it.
    assert "MieScatteringScale" in scene
    assert 'TEXT("card_aerosol")' in source


def test_the_terrain_is_tiled_at_a_stated_budget_and_the_posting_recorded():
    scene = SCENE.read_text(encoding="utf-8")
    assert "MaxVerticesPerSideGeoreferenced" not in scene
    assert "constexpr int32 SceneTerrainTileVerticesPerSide = 256;" in scene
    assert "TerrainPostingMetres = Stride * Terrain.PixelSizeMetres;" in scene
    assert 'TEXT("TerrainTile_r%d_c%d")' in scene
    assert "int32 TerrainTriangleBudget = 4000000;" in (
        BRIDGE / "Public/FlightSimVisualScene.h").read_text(encoding="utf-8")


def test_the_settle_in_placement_is_the_directors_resting_pose():
    """The commandlet's pre-placement asks the director where the preset
    rests (PresetRestingPose: this preset's offset from the CG, the point
    every preset updates from) instead of computing a station from the
    actor origin -- the structural datum, 33.7 m ahead of the B747's CG,
    which opened every preset-mode chase clip 136 m behind the CG with
    the lag dragging it in over the first ~1.5 s of written frames."""
    source = COMMANDLET.read_text(encoding="utf-8")
    block = re.search(r"// Start it where it will settle\.(.*?)\n\t\}\n", source, re.S)
    assert block, "the settle-in placement is gone"
    text = block.group(1)
    assert "Director->PresetRestingPose(Station, Look)" in text
    assert "GetActorLocation()" not in text
    director = (BRIDGE / "Private/FlightSimCameraDirector.cpp").read_text(encoding="utf-8")
    body = re.search(r"bool AFlightSimCameraDirector::PresetRestingPose\((.*?)\n\}\n",
                     director, re.S)
    assert body, "PresetRestingPose is gone"
    assert "TargetAimPoint(TargetTransform)" in body.group(1)
    assert "RefreshTargetMovement()" in body.group(1)
    assert "GetLocation()" not in body.group(1)
    # One arithmetic: the definition, the two lagged presets, the resting pose.
    assert director.count("HeadingOffsetStation(") >= 5


def test_render_json_root_camera_preset_is_the_preset_that_flew():
    """Contracts §1: the root camera_preset was a hard-coded "LaggedChase"
    on every pass, wingman and tower included; it carries the preset word
    the pass ran with, the same value as scene.camera_preset."""
    source = COMMANDLET.read_text(encoding="utf-8")
    assert 'Root->SetStringField(TEXT("camera_preset"), CameraPreset);' in source
    assert 'Scene->SetStringField(TEXT("camera_preset"), CameraPreset);' in source
    assert 'TEXT("camera_preset"), TEXT("LaggedChase")' not in source


def test_the_plugin_includes_only_the_json_headers_the_engine_ships():
    """Dom/JsonValues.h (plural) exists in no UE 5.x tree; the include
    stopped the first Windows build (C1083) before anything could be
    measured. The Json module's Dom/ holds JsonObject.h and JsonValue.h."""
    shipped = {"Dom/JsonObject.h", "Dom/JsonValue.h"}
    for path in list(BRIDGE.rglob("*.cpp")) + list(BRIDGE.rglob("*.h")):
        for header in re.findall(r'#include "(Dom/[^"]+)"', path.read_text(encoding="utf-8")):
            assert header in shipped, f"{path.name} includes {header}, which the engine does not ship"


def test_the_build_targets_include_order_is_the_pinned_engines():
    """The two Target.cs files state an EngineIncludeOrderVersion; it
    was left at Unreal5_5 when the pin moved to 5.7, and UnrealBuildTool
    then compiles the project against the older include order (a warning
    on every build, and the header shims the engine kept for 5.5 rather
    than 5.7's). The enum name is built from the one pinned version,
    core.util.platform.UE_ENGINE_VERSION, so this moves with the pin."""
    from core.util.platform import UE_ENGINE_VERSION

    wanted = "EngineIncludeOrderVersion.Unreal" + UE_ENGINE_VERSION.replace(".", "_")
    for name in ("FlightSim.Target.cs", "FlightSimEditor.Target.cs"):
        text = (REPO / "ue/Source" / name).read_text(encoding="utf-8")
        assert f"IncludeOrderVersion = {wanted};" in text, f"{name} does not pin {wanted}"
        assert "Unreal5_5" not in text, f"{name} still says Unreal5_5"
