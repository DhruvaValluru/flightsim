"""The beauty look (look-dev lane): physics of the sun and exposure, the named
presets, the sidecar, the web app's plumbing, and the C++ that reads it kept
in step with the Python that writes it (the C++ is uncompiled on the
authoring machine, so its agreement with this module is pinned as text)."""

import json
import math
import re
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene.beauty_look import BeautyLookError

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
SCENE_CPP = (PRIVATE / "FlightSimVisualScene.cpp").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")


def plan(elevation=40.0, **kw):
    kw.setdefault("fps", 30)
    kw.setdefault("width_px", 1920)
    return bl.plan_beauty_look(elevation, **kw)


# -- presets ---------------------------------------------------------------------


def test_the_four_grades_and_two_lenses_are_named():
    assert bl.GRADE_NAMES == ("golden_hour", "desert_noon", "storm", "overcast")
    assert bl.LENS_NAMES == ("standard", "cinematic")
    assert bl.validate_grade(" Storm ") == "storm"
    assert bl.validate_lens("CINEMATIC") == "cinematic"


@pytest.mark.parametrize("call, word", [(bl.validate_grade, "teal_orange"),
                                        (bl.validate_lens, "fisheye"),
                                        (bl.validate_grade, "")])
def test_an_unknown_preset_refuses_by_name(call, word):
    with pytest.raises(BeautyLookError) as err:
        call(word)
    assert err.value.constraint == "render.beauty_look"


def test_grade_follows_weather_then_sun():
    assert bl.grade_for(60.0, "thunderstorm")[0] == "storm"
    assert bl.grade_for(60.0, "tornado")[0] == "storm"
    assert bl.grade_for(60.0, "none", raining=True)[0] == "storm"
    assert bl.grade_for(8.0)[0] == "golden_hour"
    assert bl.grade_for(bl.GOLDEN_HOUR_BELOW_DEG)[0] == "desert_noon"
    assert plan(8.0, grade="desert_noon")["grade_basis"] == "stated by the caller"


@pytest.mark.parametrize("preset, grade", [("storm", "storm"), ("rain", "storm"),
                                           ("overcast", "overcast"), ("hazy", "overcast"),
                                           ("clear", "desert_noon")])
def test_the_world_preset_chooses_the_grade_before_the_sun(preset, grade):
    """The world lane's selector is the one source: an overcast or hazy
    world never takes a sunny grade."""
    assert bl.grade_for(60.0, world_preset=preset)[0] == grade
    assert plan(60.0, world_preset=preset)["grade"] == grade


def test_the_world_preset_is_read_from_the_card_like_the_host_reads_it():
    from core.scene.world_beauty import OVERCAST_COVER

    deck = {"look": {"clouds": [{"cover": OVERCAST_COVER, "base_m": 900.0, "top_m": 2400.0}]}}
    assert bl.world_preset_for_card(deck)[0] == "overcast"
    # A layer with no depth is not a layer (FlightSimClouds.cpp bCardLayer).
    flat = {"look": {"clouds": [{"cover": 0.9, "base_m": 900.0, "top_m": 900.0}]}}
    assert bl.world_preset_for_card(flat)[0] == "clear"
    assert bl.world_preset_for_card({"weather_look": {"rain_rate_mmh": 3.0}})[0] == "rain"
    assert bl.world_preset_for_card({"weather_look": {"storm": "thunderstorm"}})[0] == "storm"
    assert bl.world_preset_for_card({"randomization": {"look": {"visibility_km": 6.0}}})[0] == "hazy"
    assert bl.world_preset_for_card(None)[0] == "clear"


# -- the sun ---------------------------------------------------------------------


def test_the_sun_is_the_physical_skys_outer_space_lux_at_every_elevation():
    """ONE transmittance model: the light carries the outer-space number the
    -sky= plan uses, and the engine's per-pixel transmittance dims it once
    (the air-mass falloff is never also put into the lux)."""
    from core.sky.plan import SUN_ILLUMINANCE_LUX

    for e in (3, 8, 15, 30, 50, 70, 90):
        row = bl.sun_lux_for(e)
        assert row["lux"] == SUN_ILLUMINANCE_LUX <= bl.SUN_LUX_CEILING
        assert row["source"] == "outer_space" and row["transmittance"] == "engine_per_pixel"
    ground = bl.sun_lux_for(90.0)["ground_direct_normal_lux_reference"]
    assert 95000.0 <= ground <= 110000.0                # clear-sky DNI at the zenith, reference only
    assert not hasattr(bl, "UE_ZENITH_TRANSMITTANCE")


def test_the_world_lane_turns_per_pixel_transmittance_on_for_every_beauty_sun():
    """The premise of the outer-space lux, pinned on both sides: the world
    look sets it without a plan, the -sky= plan states it, and the host
    refuses outer-space lux without it."""
    clouds = (PRIVATE / "FlightSimClouds.cpp").read_text(encoding="utf-8")
    assert "SunLight->bPerPixelAtmosphereTransmittance = true;" in clouds
    assert "bBeauty && !WorldBeauty.Build(" in RENDER_CPP
    from core.sky.plan import plan_sky  # noqa: F401  (the plan's own key)
    assert '"per_pixel_transmittance": True' in (REPO / "core/sky/plan.py").read_text(encoding="utf-8")
    assert 'Transmittance == TEXT("engine_per_pixel") && !bPerPixel' in LOOK_CPP


def test_a_stated_sun_wins_and_a_bad_one_refuses():
    row = bl.sun_lux_for(30.0, stated=50000.0)
    assert (row["lux"], row["source"], row["transmittance"]) == (50000.0, "stated", "engine_per_pixel")
    assert row["basis"].startswith("scene.sun_lux as stated, on the light unchanged")
    with pytest.raises(BeautyLookError):
        bl.sun_lux_for(30.0, stated=-5.0)


def test_a_sun_below_the_horizon_sets_no_lux():
    assert bl.sun_lux_for(-3.0)["lux"] is None
    assert "-sun-lux" not in " ".join(bl.beauty_look_flags(Path("x.json"), plan(-3.0)))
    # A sunlit EV100 over the host's unitless sun would be a black frame.
    assert plan(-3.0)["exposure"]["ev100"] is None


@pytest.mark.parametrize("e", [3.0, 10.0, 30.0, 60.0])
def test_the_plan_never_colours_the_sun(e):
    """The atmosphere is the only owner of the sun's colour: no temperature
    band, no grade temperature, and the host has no tint to decide on."""
    for p in (plan(e), plan(e, weather_event="thunderstorm"), plan(e, physical_sky=True)):
        assert "temperature_k" not in p["sun"]
        assert "per-pixel atmosphere transmittance" in p["sun"]["colour"]
    assert not hasattr(bl, "SUN_TEMPERATURE_BANDS")
    sun_block = LOOK_CPP[LOOK_CPP.index("// -- sun (the lux"):LOOK_CPP.index("// -- tonemap, grade")]
    assert "SetUseTemperature" not in sun_block and "SetTemperature" not in sun_block
    assert "!= FColor::White" not in LOOK_CPP


def test_one_warmth_owner_per_grade():
    """ColorGain is neutral on every grade: WhiteTemp is each grade's only
    colour-temperature knob, and no grade carries a sun temperature."""
    for name, row in bl.GRADES.items():
        assert row["ColorGain"] == [1.0, 1.0, 1.0, 1.0], name
        assert "sun_temperature_k" not in row, name
        assert 6000.0 <= row["WhiteTemp"] <= 6800.0, name


# -- exposure ---------------------------------------------------------------------


def test_a_sunlit_scene_sits_at_ev100_14_to_15():
    for e in (25.0, 35.0, 50.0, 80.0):
        assert 14.0 <= plan(e)["exposure"]["ev100"] <= 15.0


def test_every_renderable_elevation_stays_near_the_meter():
    """The UNCALIBRATED bands are guarded against drifting from physics at
    EVERY renderable elevation, both edges of each band included, not only
    at its middle (the old lowest band sat ~2 stops dark at the floor)."""
    import numpy

    from core.environment.sun import RENDER_FLOOR_DEG

    for e in numpy.arange(RENDER_FLOOR_DEG, 90.01, 0.5):
        meter = bl.meter_ev100(bl.clear_sky_horizontal_lux(float(e)))
        assert abs(bl.ev100_band(float(e))[0] - meter) <= bl.EV100_METER_TOLERANCE_STOPS, (e, meter)
    for low, _ in bl.EV100_BANDS[:-1]:
        for e in (low - 1e-6, low):
            meter = bl.meter_ev100(bl.clear_sky_horizontal_lux(e))
            assert abs(bl.ev100_band(e)[0] - meter) <= bl.EV100_METER_TOLERANCE_STOPS, (e, meter)
    evs = [ev for _, ev in bl.EV100_BANDS]
    assert evs == sorted(evs, reverse=True)


def test_the_exposure_meters_the_light_the_look_and_the_deck_give():
    """The lighting look's sun and sky-fill scales and brightness stops, and
    the world preset's deck, all move the one EV100 the host applies."""
    from core.scene.hero_lighting import OVERCAST_ILLUMINANCE_FRACTION

    clear = plan(40.0)["exposure"]
    assert clear["scene_light_stops"] == 0.0
    dim = plan(40.0, sun_intensity_scale=0.3, sky_light_scale=2.0)["exposure"]
    assert dim["ev100"] < clear["ev100"]                        # opens for a dimmer sun
    bright = plan(40.0, brightness_ev=0.5)["exposure"]
    assert bright["ev100"] == pytest.approx(clear["ev100"] - 0.5)
    deck = plan(40.0, world_preset="overcast", sun_intensity_scale=0.3)["exposure"]
    assert deck["ev100"] == pytest.approx(
        clear["ev100"] + math.log2(OVERCAST_ILLUMINANCE_FRACTION), abs=1e-3)
    assert deck["meter_horizontal_lux_reference"] == clear["meter_horizontal_lux_reference"]
    assert deck["meter_horizontal_lux_scene"] < deck["meter_horizontal_lux_reference"]
    with pytest.raises(BeautyLookError):
        plan(40.0, brightness_ev=float("nan"))


def test_the_compensation_lands_the_target_through_the_physical_camera():
    exposure = plan(30.0, fps=24)["exposure"]
    assert exposure["shutter_s"] == pytest.approx(1.0 / 48.0)        # 180 degrees
    camera = math.log2(exposure["aperture_f"] ** 2 / exposure["shutter_s"] * 100.0 / 100.0)
    assert exposure["camera_ev100"] == pytest.approx(camera, abs=1e-4)
    # UE: effective EV100 = camera EV100 - AutoExposureBias
    assert exposure["camera_ev100"] - exposure["AutoExposureBias"] == pytest.approx(
        exposure["ev100"], abs=1e-3)


def test_the_grade_offset_adds_to_the_band():
    clear = plan(10.0, grade="golden_hour")["exposure"]["ev100"]
    storm = plan(10.0, grade="storm")["exposure"]["ev100"]
    assert storm == pytest.approx(clear + bl.GRADES["storm"]["ev100_offset"]
                                  - bl.GRADES["golden_hour"]["ev100_offset"])


def test_the_physical_sky_keeps_its_own_sun_and_exposure():
    sky = plan(20.0, physical_sky=True)
    assert sky["exposure"]["ev100"] is None
    assert sky["sun"]["lux"] is None and "temperature_k" not in sky["sun"]
    assert bl.beauty_look_flags(Path("b.json"), sky) == [f"-beauty-look={Path('b.json').resolve()}"]


# -- tonemap, lens, labels --------------------------------------------------------


def test_the_tonemapper_is_ue_57s_filmic_defaults_stated():
    # Read from UE 5.7.4 Engine/Source/Runtime/Engine/Private/Scene.cpp.
    assert bl.TONEMAP == {"FilmSlope": 0.88, "FilmToe": 0.55, "FilmShoulder": 0.26,
                          "FilmBlackClip": 0.0, "FilmWhiteClip": 0.04,
                          "ToneCurveAmount": 1.0}


@pytest.mark.parametrize("lens", bl.LENS_NAMES)
def test_no_preset_moves_pixels_off_the_labels(lens):
    effects = plan(lens=lens)["pixel_effects"]
    assert effects["pixel_moving"] == []
    assert bl.LENSES[lens]["SceneFringeIntensity"] == 0.0
    assert effects["lens_distortion"]["on"] is False
    assert effects["motion_blur"]["max_smear_px"] == pytest.approx(
        bl.LENSES[lens]["MotionBlurMax"] / 100.0 * 1920)


def test_a_fringe_would_be_recorded_as_pixel_moving():
    lens = dict(bl.LENSES["standard"], SceneFringeIntensity=0.5)
    assert bl.pixel_effects(lens, 1920)["pixel_moving"] == ["chromatic_aberration"]


def test_depth_of_field_only_on_cinematic_and_shutter_is_180():
    assert plan(lens="standard")["camera"]["depth_of_field"] is False
    cine = plan(lens="cinematic")["camera"]
    assert cine["depth_of_field"] is True and "aircraft" in cine["focus"]
    assert cine["MotionBlurAmount"] == 0.5 and cine["MotionBlurTargetFPS"] == 30


def test_the_focal_length_round_trips_the_solved_fov():
    """The FOV is the solver's: the focal length is derived from it and
    gives back the same lens (35 mm on 36 mm -> 54.43 deg -> 35 mm)."""
    fov = math.degrees(2.0 * math.atan(36.0 / (2.0 * 35.0)))
    assert bl.focal_length_mm(36.0, fov) == pytest.approx(35.0)
    assert plan()["camera"]["fov"].startswith("the pose solver's, unchanged")


def test_the_vignette_stays_off_on_standard():
    # The owner rejected edge shading on 2026-10-11 (core/sky/plan.py).
    assert bl.LENSES["standard"]["VignetteIntensity"] == 0.0


def test_every_number_a_probe_must_set_is_listed():
    p = plan()
    assert set(p["uncalibrated"]) == set(bl.UNCALIBRATED)
    source = (REPO / "core/scene/beauty_look.py").read_text(encoding="utf-8")
    for name in bl.UNCALIBRATED:
        at = re.search(rf"^{name}\b[^\n]*=", source, re.M).start()
        comment = source[source.rfind("\n\n", 0, at):at]       # the comment above it
        assert "UNCALIBRATED: set by probe render on the render machine" in \
            " ".join(comment.replace("#:", " ").split()), name


@pytest.mark.parametrize("bad", [dict(sensor_width_mm=[]), dict(sensor_width_mm=[0.0]),
                                 dict(fps=0), dict(lens="zoom")])
def test_a_plan_that_cannot_be_made_refuses_by_name(bad):
    with pytest.raises(BeautyLookError) as err:
        plan(**bad)
    assert err.value.constraint == "render.beauty_look"


def test_the_sidecar_is_ascii_and_deterministic(tmp_path):
    a = bl.write_beauty_look(plan(12.0, lens="cinematic"), tmp_path / "a.json")
    b = bl.write_beauty_look(plan(12.0, lens="cinematic"), tmp_path / "b.json")
    assert a.read_bytes() == b.read_bytes()
    a.read_bytes().decode("ascii")                          # gotcha 13
    assert json.loads(a.read_text(encoding="utf-8"))["beauty_look_version"] == bl.BEAUTY_LOOK_VERSION


def test_flags_carry_the_sidecar_and_the_lux():
    p = plan(40.0)
    flags = bl.beauty_look_flags(Path("/tmp/x/beauty_look.json"), p)
    assert flags[0].startswith("-beauty-look=") and flags[0].endswith("beauty_look.json")
    assert flags[1] == f"-sun-lux={p['sun']['lux']:g}"
    assert bl.beauty_look_flags(None) == []


@pytest.mark.parametrize("e", [10, 20, 40, 50, 60, 90])
def test_the_sun_lux_flag_round_trips_the_plan(e):
    p = plan(float(e))
    assert float(bl.beauty_look_flags(Path("b.json"), p)[1].split("=", 1)[1]) == p["sun"]["lux"]
    stated = plan(float(e), stated_sun_lux=98765.4321)
    assert float(bl.beauty_look_flags(Path("b.json"), stated)[1].split("=", 1)[1]) == 98765.4321


# -- the C++ that reads the sidecar ------------------------------------------------


def _cpp_keys():
    return set(re.findall(r"FLIGHTSIM_BEAUTY_(?:FLOAT|VECTOR)\(\w+, (\w+)\)", LOOK_CPP))


@pytest.mark.parametrize("block", ["tonemap", "color_grade", "lens_post", "local_exposure",
                                   "reflections"])
def test_every_post_process_key_the_python_writes_the_host_applies(block):
    keys = {k for k in plan(lens="cinematic")[block] if k[0].isupper()}
    explicit = {"DepthOfFieldBladeCount", "LumenFrontLayerTranslucencyReflections",
                "LocalExposureMethod"}
    for key in keys:
        assert key in _cpp_keys() or (key in explicit and f'TEXT("{key}")' in LOOK_CPP), key
        assert f"bOverride_{key}" in LOOK_CPP or key in _cpp_keys(), key


def test_the_host_reads_the_camera_and_exposure_fields_the_python_writes():
    for key in ("sensor_width_mm", "depth_of_field", "aperture_f", "MotionBlurAmount",
                "MotionBlurTargetFPS"):
        assert f'TEXT("{key}")' in LOOK_CPP, key
        assert key in plan()["camera"], key
    for key in ("ev100", "shutter_s", "iso"):
        assert f'TEXT("{key}")' in LOOK_CPP and key in plan()["exposure"], key
    for key in ("lux", "transmittance"):
        assert f'TEXT("{key}")' in LOOK_CPP and key in plan()["sun"], key
    assert f"BeautyLookSupportedVersion = {bl.BEAUTY_LOOK_VERSION};" in LOOK_CPP


def test_the_host_formulas_are_the_python_ones():
    assert "FMath::Log2((ApertureF * ApertureF / ShutterSeconds) * (100.0 / Iso))" in LOOK_CPP
    assert ("SensorWidthMm / (2.0 * FMath::Tan(FMath::DegreesToRadians(HorizontalFovDeg) * 0.5))"
            in LOOK_CPP)
    assert "Settings.AutoExposureBias = static_cast<float>(CameraEv - Ev100);" in LOOK_CPP


def test_a_physical_camera_keeps_its_aperture():
    # The card triple's / -sky= plan's f-number is part of its EV100; the
    # beauty lens must not replace it (the exposure would shift unrecorded).
    camera = LOOK_CPP[LOOK_CPP.index("// -- camera: sensor"):LOOK_CPP.index("// -- exposure:")]
    guard = camera.index("if (bPhysicalAlready)")
    assert guard < camera.index("Settings.DepthOfFieldFstop = static_cast<float>(ApertureF);")
    assert "RoundToInt(" not in LOOK_CPP   # int64 from a double; RoundToInt32 into int32 members


def test_the_host_never_touches_the_fov():
    assert not re.search(r"FOVAngle\s*=", LOOK_CPP)


def test_measure_and_sidecar_less_beauty_keep_the_v0_capture():
    """ApplyBeautyPostProcess still sets exactly the V0 Lumen overrides
    before the sidecar is even looked for, and returns when there is none;
    it is still called only under -Visual -quality=beauty."""
    body = SCENE_CPP[SCENE_CPP.index("void FFlightSimVisualScene::ApplyBeautyPostProcess"):]
    body = body[:body.index("\n}\n")]
    assert "FFlightSimBeautyLook::Apply(Capture, FCommandLine::Get());" in body
    apply = LOOK_CPP[LOOK_CPP.index("void FFlightSimBeautyLook::Apply("):]
    v0 = apply.index("EReflectionMethod::Lumen;")
    assert apply.index("EDynamicGlobalIlluminationMethod::Lumen;") < v0
    assert v0 < apply.index('TEXT("beauty-look=")') < apply.index("return;   // no sidecar")
    call = RENDER_CPP.index("FFlightSimVisualScene::ApplyBeautyPostProcess(Capture);")
    assert "if (bVisual && bBeauty)" in RENDER_CPP[call - 120:call]


def test_the_commandlet_hooks_are_in_place():
    call = RENDER_CPP.index("FFlightSimVisualScene::ApplyBeautyPostProcess(Capture);")
    after = RENDER_CPP[call:call + 600]
    assert "return Fail(FFlightSimBeautyLook::LastError());" in after
    assert "FFlightSimBeautyLook::RecordExposure(ExposureMode" in after
    focus = RENDER_CPP.index("FFlightSimBeautyLook::UpdatePerFrame(Capture, Scenario.Aircraft);")
    # The focus is set before the frame's first beauty capture: the
    # render-path lane's still sub-frames (same pose) sit between the hook
    # and the read-back capture, and see the same focus (integration).
    between = RENDER_CPP[focus:RENDER_CPP.index("Capture->CaptureScene();", focus)]
    assert len(between) < 600, between
    assert "for (int32 SubFrame = 1; SubFrame < BeautySubFrames; ++SubFrame)" in between
    assert 'Root->SetObjectField(TEXT("beauty_look"), BeautyLook);' in RENDER_CPP


def test_the_host_adds_no_visual_only_actor():
    assert "BeautyOnlyActors" not in LOOK_CPP
    assert "SpawnActor" not in LOOK_CPP


def test_the_host_refusal_is_catalogued():
    from core.messages import is_catalogued

    assert 'TEXT("render.beauty_look: %s")' in LOOK_CPP
    assert is_catalogued("render.beauty_look")


# -- the web app ------------------------------------------------------------------


def _spec(prompt="fly the 747 at 280 kt"):
    from core.nl.compiler import compile_prompt

    return compile_prompt(prompt)


def _render_command(tmp_path, monkeypatch, beauty_look):
    import webapp.runs as runs
    from tests.engine_launch import launch_through_run

    captured = {}
    launch_through_run(monkeypatch)
    monkeypatch.setattr(runs.subprocess, "run",
                        lambda command, **kw: captured.setdefault("command", list(command)))
    spec = _spec()
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                            {"key": "flat", "terrain": None, "imagery": None},
                            tmp_path / "missing_mesh.json", "B747",
                            camera_flags=runs.camera_render_flags(spec),
                            beauty_look=beauty_look)
    return captured["command"]


def test_measure_writes_no_sidecar_and_adds_no_flag(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "measure")
    assert runs.write_beauty_look_plan(_spec(), tmp_path, None) is None
    assert not (tmp_path / "beauty_look.json").exists()
    command = _render_command(tmp_path, monkeypatch, None)
    assert not any(t.startswith(("-beauty-look=", "-sun-lux=")) for t in command)


def test_beauty_writes_the_sidecar_and_the_command_carries_it(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    path = runs.write_beauty_look_plan(_spec(), tmp_path, None)
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    # The default look's noon sun (50 deg): desert_noon, standard lens.
    assert sidecar["grade"] == "desert_noon" and sidecar["lens"] == "standard"
    assert sidecar["camera"]["fps"] == runs.FPS
    command = _render_command(tmp_path, monkeypatch, path)
    assert f"-beauty-look={path.resolve()}" in command
    assert f"-sun-lux={sidecar['sun']['lux']:g}" in command
    assert sidecar["sun"]["source"] == "outer_space"
    assert "-quality=beauty" in command


def test_the_storm_look_chooses_the_storm_grade(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    spec = _spec("fly the c172 into a thunderstorm")
    path = runs.write_beauty_look_plan(spec, tmp_path, runs.STORM_LOOK)
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert str(spec.weather_event.value) == "thunderstorm"
    assert sidecar["sun_elevation_deg"] == runs.STORM_LOOK["sun_elev"]
    assert sidecar["grade"] == "storm" and sidecar["grade_basis"] == "weather event thunderstorm"
    forced = runs.write_beauty_look_plan(_spec(), tmp_path, None, grade="golden_hour",
                                         lens="cinematic")
    forced = json.loads(forced.read_text(encoding="utf-8"))
    assert (forced["grade"], forced["lens"]) == ("golden_hour", "cinematic")
    with pytest.raises(BeautyLookError):
        runs.write_beauty_look_plan(_spec(), tmp_path, None, lens="anamorphic")


def test_sensor_widths_follow_the_camera_order(tmp_path, monkeypatch):
    """The host indexes the widths by -camera-index= (spec.cameras order)."""
    from types import SimpleNamespace

    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    spec = _spec()
    spec.cameras = [SimpleNamespace(sensor_width_mm=SimpleNamespace(value=36.0)),
                    SimpleNamespace(sensor_width_mm=SimpleNamespace(value=23.76)),
                    SimpleNamespace(sensor_width_mm=None)]
    sidecar = json.loads(runs.write_beauty_look_plan(spec, tmp_path, None).read_text(encoding="utf-8"))
    assert sidecar["camera"]["sensor_width_mm"] == [36.0, 23.76, bl.DEFAULT_SENSOR_WIDTH_MM]
    # A width that is there but unreadable raises instead of becoming 36 mm.
    spec.cameras = [SimpleNamespace(sensor_width_mm=SimpleNamespace(value="wide"))]
    with pytest.raises(ValueError):
        runs.write_beauty_look_plan(spec, tmp_path, None)


def test_the_sky_sidecar_sets_elevation_and_keeps_sun_and_exposure(tmp_path, monkeypatch):
    import webapp.runs as runs

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    sky = tmp_path / "sky.json"
    sky.write_text(json.dumps({"sun": {"elevation_deg": 8.0}}), encoding="ascii")
    path = runs.write_beauty_look_plan(_spec(), tmp_path, None, sky=sky)
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert sidecar["sun_elevation_deg"] == 8.0 and sidecar["grade"] == "golden_hour"
    assert sidecar["exposure"]["ev100"] is None and sidecar["sun"]["lux"] is None
    assert not any(t.startswith("-sun-lux=") for t in runs.beauty_look_render_flags(path))


def test_the_card_world_preset_and_the_lighting_look_reach_the_plan(tmp_path, monkeypatch):
    """One source: the card's world preset picks the grade, the deck and the
    beauty X-Plane condition; the lighting look's knobs reach the EV100."""
    import webapp.runs as runs
    from core.scene.world_beauty import OVERCAST_COVER

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    (tmp_path / "card.json").write_text(json.dumps({"look": {"clouds": [
        {"cover": OVERCAST_COVER, "base_m": 1200.0, "top_m": 2600.0}]}}), encoding="utf-8")
    look = {"sun_elev": 40.0, "sun_azim": 120.0, "exposure_bias": 10.0, "fog_density": 0.002,
            "sun_intensity_scale": 0.3, "lighting": {"brightness_ev": 0.9}}
    path = runs.write_beauty_look_plan(_spec(), tmp_path, look)
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    assert sidecar["world_preset"] == "overcast" and sidecar["grade"] == "overcast"
    assert sidecar["exposure"]["brightness_ev"] == 0.9
    assert sidecar["exposure"]["scene_light_stops"] < 0.0
    assert runs.beauty_xplane_condition(path) == "ocast"
    assert runs.beauty_xplane_condition(None) is None          # measure: unchanged
    (tmp_path / "card.json").write_text("{}", encoding="utf-8")
    clear = runs.write_beauty_look_plan(_spec(), tmp_path, None)
    assert runs.beauty_xplane_condition(clear) is None          # clear keeps the look's choice


def test_a_planned_beauty_look_record_passes_verify_look_record(tmp_path):
    """The look-dev lane and the verifier agree on motion blur: the plan's
    'softens' row nests under beauty_look.plan, the commandlet's
    RenderWriteLookContract lists motion_blur in pixel_moving_effects
    (a bound by construction), and the record grades PASS."""
    import shutil

    from core.capture.manifest import read_capture_manifest
    from core.capture.verify import PASS, verify_look_record

    assert 'RenderPixelEffect(TEXT("motion_blur"), bMotionBlur' in RENDER_CPP
    fixture = REPO / "tests" / "fixtures" / "engine_bundle_min"
    for lens in bl.LENS_NAMES:
        run = tmp_path / lens
        shutil.copytree(fixture, run)
        render = run / "frames" / "chase" / "render.json"
        payload = json.loads(render.read_text(encoding="utf-8"))
        p = plan(30.0, lens=lens)
        payload["scene"]["render_quality"] = "beauty"
        payload["beauty_look"] = {"sidecar": "beauty_look.json", "plan": p, "applied": {},
                                  "per_frame": {"frames": 1}}
        payload.setdefault("render_settings", {})["beauty_show_flags"] = {"motion_blur": True}
        payload["pixel_moving_effects"] = [{
            "name": "motion_blur", "on": True, "transform": None,
            "max_displacement_px": p["pixel_effects"]["motion_blur"]["max_smear_px"],
            "displacement_basis": "bound: MotionBlurMax percent of the width, by construction; not measured",
            "source": "beauty capture"}]
        render.write_text(json.dumps(payload), encoding="utf-8")
        record = verify_look_record(read_capture_manifest(run / "capture_manifest.json"), run)
        assert record.status == PASS, (lens, record.detail)


def test_the_config_surface_stays_frozen():
    """No new FLIGHTSIM_* name: the beauty look needs no switch."""
    source = (REPO / "webapp/runs.py").read_text(encoding="utf-8")
    assert "FLIGHTSIM_BEAUTY" not in source
    assert "FLIGHTSIM_BEAUTY" not in (REPO / "core/scene/beauty_look.py").read_text(encoding="utf-8")


def test_the_weather_defaults_are_untouched():
    """The owner's rule: storm weather stays on by default in the web app."""
    import webapp.runs as runs

    assert runs.WEATHER_DEFAULT_BACKEND == "procedural"
    assert runs.WEATHER_DEFAULT_GAIN == 4.0 and runs.WEATHER_DEFAULT_STYLE == "cinematic"
