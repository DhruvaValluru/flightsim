"""The physical sky: positions, instants, exposure, and the plan's contract.

Reference positions were computed with astropy 6 (IAU 2006/2000A, standard
refraction) and pinned here as literals -- astropy is a development
reference, not a dependency. Only bodies ABOVE the horizon are compared:
below it the refraction conventions differ and nothing is drawn anyway.
"""

import json
import math
from datetime import datetime, timezone

import pytest

from core.nl.compiler import compile_prompt
from core.sky import astro
from core.sky.plan import (
    CAMERA_EV100, DEFAULT_DATE, SkyError, ev100_for, plan_sky,
    resolve_instant, star_batches, sun_horizontal_lux,
)
from tests.engine_launch import launch_through_run


def _utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# (instant, lat, lon, body, azimuth, elevation) -- astropy, above horizon.
ASTROPY = [
    ("2025-12-24T23:00:00", -33.9, 151.2, "sun", 86.3914, 50.5004),
    ("2026-03-20T12:00:00", 0.0, 0.0, "sun", None, 88.1409),
    ("2024-01-25T17:54:00", 45.98, 7.66, "moon", 74.3053, 17.1411),
    ("2026-03-20T12:00:00", 0.0, 0.0, "moon", 59.1294, 68.8377),
    ("2026-06-21T04:30:00", 37.74, -119.6, "moon", 241.1158, 33.9276),
    ("2026-09-30T02:00:00", 64.1, -21.9, "moon", 139.9484, 43.6029),
]


@pytest.mark.parametrize("when,lat,lon,body,az,el", ASTROPY)
def test_positions_match_astropy(when, lat, lon, body, az, el):
    fn = astro.sun_position if body == "sun" else astro.moon_position
    got = fn(_utc(when), lat, lon)
    # Sun: ~0.01 deg. Moon: truncated series + spherical parallax, ~0.05.
    tol = 0.03 if body == "sun" else 0.06
    assert abs(got.elevation_deg - el) < tol
    if az is not None:   # azimuth is ill-conditioned at the zenith
        assert abs((got.azimuth_deg - az + 180) % 360 - 180) < tol


def test_sirius_precessed_to_date_matches_astropy():
    when = _utc("2024-01-25T17:54:00")
    jd = astro.julian_day(when)
    ra, dec = astro.precess_j2000(6.752481 * 15.0, -16.716116, jd)
    az, el = astro.equatorial_to_horizontal(ra, dec, jd, 45.98, 7.66)
    assert abs(float(el) - 6.8382) < 0.03
    assert abs(float(az) - 122.6300) < 0.03


def test_a_known_full_moon_is_full_and_a_known_new_moon_is_new():
    full = astro.moon_position(_utc("2024-01-25T17:54:00"), 0.0, 0.0)
    assert full.illuminated_fraction > 0.99
    new = astro.moon_position(_utc("2024-02-09T22:59:00"), 0.0, 0.0)
    assert new.illuminated_fraction < 0.01
    # Waxing a week after new, waning a week after full.
    assert astro.moon_position(_utc("2024-02-16T12:00:00"), 0, 0).waxing
    assert not astro.moon_position(_utc("2024-02-01T12:00:00"), 0, 0).waxing


def test_half_moon_is_a_tenth_of_full_not_half():
    assert astro.moon_relative_brightness(0.0) == 1.0
    assert 0.07 < astro.moon_relative_brightness(90.0) < 0.13


def test_star_luminance_conserves_illuminance():
    radius = 0.043
    when = _utc("2026-03-20T00:00:00")
    for batch in star_batches(when, 45.98, 7.66, radius):
        solid = math.pi * math.radians(radius) ** 2
        expected = float(astro.star_illuminance_lux(batch["vmag"]))
        assert batch["luminance_nits"] * solid == pytest.approx(expected,
                                                                rel=1e-3)


# -- the instant ---------------------------------------------------------


def test_clock_times_are_local_mean_solar_unless_marked_utc():
    local = resolve_instant("12:00", "none", 0.0, 90.0)
    assert local.utc == datetime(2026, 3, 20, 6, 0, tzinfo=timezone.utc)
    assert "local mean solar" in local.basis
    utc = resolve_instant("12:00Z", "none", 0.0, 90.0)
    assert utc.utc == datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)
    assert local.date_source.startswith("default")
    assert DEFAULT_DATE.isoformat() == "2026-03-20"


def test_the_date_comes_from_the_time_then_the_weather_date():
    dated = resolve_instant("2024-01-25T18:00Z", "2023-06-01", 0.0, 0.0)
    assert dated.utc.date().isoformat() == "2024-01-25"
    assert dated.date_source == "time_of_day"
    weather = resolve_instant("18:00Z", "2023-06-01", 0.0, 0.0)
    assert weather.utc.date().isoformat() == "2023-06-01"
    assert weather.date_source == "weather_date"


@pytest.mark.parametrize("word,target,rising", [
    ("sunrise", 0.5, True), ("sunset", 0.5, False), ("dawn", -4.0, True),
    ("dusk", -4.0, False), ("golden hour", 6.0, False),
])
def test_time_words_solve_for_the_sun(word, target, rising):
    instant = resolve_instant(word, "none", 45.98, 7.66)
    sun = astro.sun_position(instant.utc, 45.98, 7.66)
    assert sun.elevation_deg == pytest.approx(target, abs=0.01)
    later = astro.sun_position(
        instant.utc.replace(minute=(instant.utc.minute + 5) % 60), 45.98, 7.66)
    # (minute wrap aside, 5 minutes later the sun has moved the right way)
    if instant.utc.minute < 55:
        assert (later.elevation_deg > sun.elevation_deg) == rising


def test_noon_is_the_highest_sun_and_night_the_lowest():
    noon = resolve_instant("noon", "none", 45.98, 7.66)
    night = resolve_instant("night", "none", 45.98, 7.66)
    el_noon = astro.sun_position(noon.utc, 45.98, 7.66).elevation_deg
    el_night = astro.sun_position(night.utc, 45.98, 7.66).elevation_deg
    assert el_noon == pytest.approx(90 - 45.98, abs=0.6)   # equinox
    assert el_night == pytest.approx(-(90 - 45.98), abs=0.6)


def test_impossible_and_unknown_times_refuse_by_name():
    with pytest.raises(SkyError, match="polar day or night"):
        resolve_instant("sunset", "2026-06-21", 78.2, 15.6)
    with pytest.raises(SkyError, match="unknown time_of_day"):
        resolve_instant("teatime", "none", 0.0, 0.0)
    with pytest.raises(SkyError, match="not a clock time"):
        resolve_instant("25:00", "none", 0.0, 0.0)


# -- light and exposure -----------------------------------------------------


def test_exposure_follows_the_meter_by_day_and_darkens_at_night():
    assert ev100_for(100000.0) == pytest.approx(math.log2(100000 / 2.5))
    assert 14.5 < ev100_for(sun_horizontal_lux(60.0)) < 15.8   # sunny 16
    full_moon = ev100_for(0.27)
    moonless = ev100_for(0.0005)
    # Night renders under-exposed relative to a meter (half rate).
    assert full_moon > math.log2(0.27 / 2.5) + 3.0
    assert moonless < full_moon < ev100_for(700.0)
    lux = [sun_horizontal_lux(e) for e in range(-20, 91, 5)]
    assert lux == sorted(lux)


def test_plan_is_deterministic_serialisable_and_consistent():
    a = plan_sky("dusk", "none", 45.98, 7.66, 4500.0, 1600.0)
    b = plan_sky("dusk", "none", 45.98, 7.66, 4500.0, 1600.0)
    assert a == b
    text = json.dumps(a)
    text.encode("ascii")
    assert a["exposure"]["bias"] == pytest.approx(
        CAMERA_EV100 - a["exposure"]["ev100"], abs=1e-3)


def test_night_draws_stars_day_does_not_and_clouds_clear_the_flight():
    night = plan_sky("night", "none", 45.98, 7.66, 4500.0, 1600.0)
    day = plan_sky("noon", "none", 45.98, 7.66, 4500.0, 1600.0)
    assert night["stars"]["drawn"] and night["stars"]["count"] > 2000
    assert not day["stars"]["drawn"] and day["stars"]["batches"] == []
    assert night["sun"]["transmittance_min_elevation_deg"] == -90.0
    assert day["sun"]["transmittance_min_elevation_deg"] == 90.0
    # Flight 2.9 km above the ground: the cloud base sits >= 1 km over it.
    assert day["clouds"]["bottom_km"] >= 2.9 + 1.0
    assert "VISUAL ONLY" in day["clouds"]["basis"]
    by_mag = sorted(night["stars"]["batches"], key=lambda b: b["vmag"])
    assert by_mag[0]["luminance_nits"] > by_mag[-1]["luminance_nits"]


def test_post_processing_is_per_camera_kind():
    chase = plan_sky("noon", "none", 0, 0, 3000, 0, camera_preset="chase")
    cockpit = plan_sky("noon", "none", 0, 0, 3000, 0, camera_preset="cockpit")
    assert chase["post_process"]["kind"] == "external"
    assert cockpit["post_process"]["kind"] == "cockpit"
    assert (cockpit["post_process"]["vignette_intensity"]
            > chase["post_process"]["vignette_intensity"])
    assert chase["lighting"] == {"global_illumination": "lumen",
                                 "reflections": "lumen",
                                 "shadows": "virtual_shadow_maps"}


# -- the spec field --------------------------------------------------------


@pytest.mark.parametrize("prompt,value,source", [
    ("fly the c172p at sunset", "sunset", "inferred"),
    ("fly the c172p in the afternoon", "afternoon", "inferred"),
    ("fly the c172p at midnight", "midnight", "inferred"),
    ("fly the c172p in the evening", "golden hour", "inferred"),
    ("fly the c172p at 6:30 pm", "18:30", "user"),
    ("fly the c172p at 21:15z", "21:15Z", "user"),
    ("fly the c172p at 3000 m", "none", "default"),
])
def test_the_parser_reads_time_of_day(prompt, value, source):
    spec = compile_prompt(prompt)
    assert str(spec.time_of_day.value) == value
    assert str(spec.time_of_day.source) == source


def test_an_impossible_time_is_a_validation_violation():
    from core.scenario.validate import validate

    spec = compile_prompt("fly the c172p at sunset")
    spec.set("latitude", 78.2, frm="test")
    spec.set("longitude", 15.6, frm="test")
    spec.set("weather_date", "2026-06-21", frm="test")
    fields = [v.constraint for v in validate(spec).violations]
    assert "environment.time_of_day" in fields


# -- the web app's wiring ---------------------------------------------------


def test_the_physical_sky_is_opt_in(monkeypatch):
    from webapp.runs import physical_sky_enabled

    monkeypatch.delenv("FLIGHTSIM_SKY", raising=False)
    assert not physical_sky_enabled(compile_prompt("fly the c172p"))
    stated = compile_prompt("fly the c172p at dusk")
    assert not physical_sky_enabled(stated)
    monkeypatch.setenv("FLIGHTSIM_SKY", "physical")
    assert physical_sky_enabled(stated)
    monkeypatch.setenv("FLIGHTSIM_SKY", "legacy")
    assert not physical_sky_enabled(stated)
    monkeypatch.setenv("FLIGHTSIM_SKY", "physical")
    assert physical_sky_enabled(compile_prompt("fly the c172p"))


def test_the_sky_sidecar_replaces_the_calibrated_sun_flags(tmp_path,
                                                           monkeypatch):
    import webapp.runs as runs
    from core.scenario.camera import default_cameras

    spec = compile_prompt("fly the c172p at night")
    scene = {"key": "flat", "terrain": None, "imagery": None}
    sky = runs.write_sky_plan(spec, scene, default_cameras(spec)[0],
                              tmp_path)
    plan = json.loads(sky.read_text(encoding="ascii"))
    assert plan["stars"]["drawn"]
    # A flat scene has no drape to carry night lights: recorded, not fatal.
    assert plan["night_lights"]["sidecar"] is None

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)

    launch_through_run(monkeypatch)
    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                            scene, tmp_path / "no_mesh.json", "c172p",
                            sky=sky)
    command = captured["command"]
    assert f"-sky={sky}" in command
    assert not any(arg.startswith(("-sun-elev", "-sun-azim",
                                   "-exposure-bias")) for arg in command)
    assert any(arg.startswith("-fog-density=") for arg in command)
