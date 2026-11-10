"""Round 2 (exposure-storm): ONE exposure owner on both paths, the meter
that opens a deck or a no-Lumen frame, and the breathing fixes. The first
Windows renders (runs/visual/head, commit ef361bd6) put shot c, rain under a
deck with a -sky= plan, at a luma mean of 3.6/255: the plan's clear-sky
EV100 stood and the deck's correction never applied."""

import json
from pathlib import Path

import pytest

from core.scene import beauty_look as bl
from core.scene.beauty_look import BeautyLookError
from core.sky.plan import plan_sky

REPO = Path(__file__).resolve().parents[1]
PRIVATE = REPO / "ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private"
LOOK_CPP = (PRIVATE / "FlightSimBeautyLook.cpp").read_text(encoding="utf-8")
LOOK_H = (PRIVATE / "FlightSimBeautyLook.h").read_text(encoding="utf-8")
RENDER_CPP = (PRIVATE / "FlightSimRenderCommandlet.cpp").read_text(encoding="utf-8")
API = (REPO / "scripts" / "check_bridge_api.sh").read_text(encoding="utf-8")


def sky_exposure(elevation_hint="noon"):
    """A real -sky= plan's exposure block (Yosemite, shot c's place)."""
    return plan_sky(elevation_hint, None, 37.7275, -119.61, 1700.0, 1200.0)["exposure"]


def plan(elevation=28.0, **kw):
    kw.setdefault("fps", 30)
    kw.setdefault("width_px", 1920)
    return bl.plan_beauty_look(elevation, **kw)


# -- one owner, two bases ---------------------------------------------------------


@pytest.mark.parametrize("preset", ["rain", "storm", "overcast"])
def test_the_deck_opens_the_sky_plan_exactly_as_it_opens_the_band(preset):
    block = sky_exposure()
    sky = plan(physical_sky=True, world_preset=preset, sky_exposure=block)["exposure"]
    band = plan(world_preset=preset)["exposure"]
    clear_sky = plan(physical_sky=True, world_preset="clear", sky_exposure=block)["exposure"]
    assert sky["base"] == "sky_plan" and band["base"] == "band"
    assert sky["ev100"] - sky["base_ev100"] == pytest.approx(band["ev100"] - band["base_ev100"])
    assert sky["scene_light_stops"] < 0.0           # the deck opens the exposure
    assert sky["ev100"] < clear_sky["ev100"]
    assert sky["owner"] == band["owner"]


def test_a_clear_sky_plan_keeps_its_own_ev100_and_camera():
    block = sky_exposure()
    exposure = plan(physical_sky=True, world_preset="clear", sky_exposure=block)["exposure"]
    assert exposure["ev100"] == pytest.approx(block["ev100"])
    assert exposure["over_sky_plan"] is True
    assert exposure["aperture_f"] == block["camera"]["fstop"]
    assert exposure["iso"] == block["camera"]["iso"]
    assert exposure["shutter_s"] == pytest.approx(1.0 / block["camera"]["shutter_per_s"])
    # The host's compensation lands the plan's own bias when nothing moves it.
    assert exposure["AutoExposureBias"] == pytest.approx(block["bias"], abs=2e-3)


def test_the_lighting_looks_scales_move_the_sky_plan_too():
    block = sky_exposure()
    dim = plan(physical_sky=True, world_preset="clear", sky_exposure=block,
               sun_intensity_scale=0.5, sky_light_scale=0.5, brightness_ev=1.0)["exposure"]
    assert dim["ev100"] == pytest.approx(block["ev100"] - 1.0 - 1.0, abs=1e-3)


def test_without_a_plan_exposure_the_plan_still_stands():
    assert plan(physical_sky=True)["exposure"]["ev100"] is None
    assert "meter" not in plan(physical_sky=True)["exposure"]


@pytest.mark.parametrize("block", [{"ev100": 12.0}, {"ev100": "x", "camera": {}},
                                   {"ev100": 12.0, "camera": {"fstop": 4.0, "shutter_per_s": 0.0,
                                                              "iso": 100.0}}])
def test_an_unreadable_plan_exposure_refuses_by_name(block):
    with pytest.raises(BeautyLookError) as err:
        plan(physical_sky=True, sky_exposure=block)
    assert err.value.constraint == "render.beauty_look"


# -- the meter --------------------------------------------------------------------


@pytest.mark.parametrize("preset", bl.DECK_PRESETS)
def test_a_deck_is_metered_to_its_own_target(preset):
    meter = plan(world_preset=preset)["exposure"]["meter"]
    assert meter["deck"] is True
    assert meter["target_p90_luma"] == bl.EXPOSURE_METER_TARGET_P90[preset]


def test_a_clear_look_is_metered_only_without_lumen():
    meter = plan(world_preset="clear")["exposure"]["meter"]
    assert meter["deck"] is False
    assert meter["no_lumen_gi_target_p90_luma"] == bl.EXPOSURE_METER_TARGET_P90["no_lumen_gi"]
    assert all(0.0 < v < 1.0 for v in bl.EXPOSURE_METER_TARGET_P90.values())
    assert "EXPOSURE_METER_TARGET_P90" in plan()["uncalibrated"]


def test_the_host_reads_the_meter_the_python_writes():
    for key in ("deck", "target_p90_luma", "no_lumen_gi_target_p90_luma", "over_sky_plan"):
        assert f'TEXT("{key}")' in LOOK_CPP, key
    assert "DoesPlatformSupportLumenGI(GMaxRHIShaderPlatform)" in LOOK_CPP
    assert "static bool ExposureMeter(double& TargetP90, FString& Trigger);" in LOOK_H
    # The meter runs only when this look owns the exposure.
    body = LOOK_CPP[LOOK_CPP.index("bool FFlightSimBeautyLook::ExposureMeter"):]
    assert "!State.bExposureApplied" in body[:400]


def test_the_commandlet_meters_a_beauty_deck_with_the_storm_loop():
    hook = RENDER_CPP.index("FFlightSimBeautyLook::ExposureMeter(BeautyMeterTarget, BeautyMeterTrigger)")
    loop = RENDER_CPP.index("if ((Weather.DrawsCell() || bBeautyMeter) && !bAutoExposure)")
    assert hook < loop
    assert "bVisual && bBeauty && !Weather.DrawsCell()" in RENDER_CPP[hook - 200:hook]
    assert 'MeterRow->SetStringField(TEXT("trigger")' in RENDER_CPP[loop:]


def test_the_sky_plan_override_keeps_the_plan_camera():
    branch = LOOK_CPP[LOOK_CPP.index("else if (bPhysicalAlready && bOverSkyPlan && bSkyPlanRun)"):]
    branch = branch[:branch.index("else if (bPhysicalAlready)")]
    assert "Settings.AutoExposureBias = static_cast<float>(CameraEv - Ev100);" in branch
    assert "Settings.DepthOfFieldFstop =" not in branch
    assert "Settings.CameraShutterSpeed =" not in branch


def test_the_meter_symbols_are_checked_before_a_build():
    block = API[API.index("BEGIN exposure-storm"):API.index("END exposure-storm")]
    for needle in ("DoesPlatformSupportLumenGI", "GMaxRHIShaderPlatform", "LexToString(EShaderPlatform"):
        assert needle in block, needle


# -- the web app ------------------------------------------------------------------


def test_the_web_app_hands_the_plan_exposure_to_the_beauty_look(tmp_path, monkeypatch):
    import webapp.runs as runs
    from core.nl.compiler import compile_prompt

    monkeypatch.setenv("FLIGHTSIM_RENDER_QUALITY", "beauty")
    sky = plan_sky("noon", None, 37.7275, -119.61, 1700.0, 1200.0)
    (tmp_path / "sky.json").write_text(json.dumps(sky), encoding="ascii")
    (tmp_path / "card.json").write_text(json.dumps(
        {"look": {"precipitation": "rain", "precipitation_rate_mmh": 12.0}}), encoding="utf-8")
    path = runs.write_beauty_look_plan(compile_prompt("fly the 747 at 280 kt"), tmp_path, None,
                                       sky=tmp_path / "sky.json")
    exposure = json.loads(path.read_text(encoding="utf-8"))["exposure"]
    assert exposure["base"] == "sky_plan" and exposure["over_sky_plan"] is True
    assert exposure["base_ev100"] == sky["exposure"]["ev100"]
    assert exposure["ev100"] < sky["exposure"]["ev100"]
    assert exposure["meter"]["deck"] is True
