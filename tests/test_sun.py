"""The render sun (visual-fidelity plan V1): core.environment.sun, the
time_of_day spec field, both compilers, and the webapp's look."""

from datetime import date, datetime, timedelta, timezone

import pytest

from core.environment.sun import (
    DEFAULT_DATE,
    RENDER_FLOOR_DEG,
    SunError,
    canonical_time_of_day,
    require_renderable,
    resolve,
    solar_position,
)
from core.nl.compiler import compile_prompt
from core.scenario.fields import Source
from tests.engine_launch import launch_through_run

MATTERHORN = (45.9763, 7.6586)
YOSEMITE = (37.7456, -119.5936)

#: Apparent elevation and azimuth from pvlib 0.16.1's NREL SPA
#: (spa_python, sea-level pressure, 10 C) -- an independent algorithm,
#: so agreement is a measurement of ours, not a restatement of it.
SPA_REFERENCE = [
    (45.9763, 7.6586, "2026-06-21T10:30:00+00:00", 64.3031, 146.0878),
    (45.9763, 7.6586, "2026-12-21T12:00:00+00:00", 20.2369, 187.9588),
    (37.7456, -119.5936, "2026-03-20T20:00:00+00:00", 52.3293, 177.6633),
    (37.7456, -119.5936, "2026-09-01T14:10:00+00:00", 7.3775, 85.3110),
    (-33.87, 151.21, "2026-01-15T02:00:00+00:00", 77.2415, 4.6550),
    (69.65, 18.96, "2026-06-21T23:00:00+00:00", 3.3412, 3.1980),
    (38.5, -96.5, "2026-05-10T23:30:00+00:00", 21.0984, 276.4786),
]


@pytest.mark.parametrize("lat,lon,when,elevation,azimuth", SPA_REFERENCE)
def test_solar_position_matches_nrel_spa(lat, lon, when, elevation, azimuth):
    ours_e, ours_a = solar_position(lat, lon, datetime.fromisoformat(when))
    assert ours_e == pytest.approx(elevation, abs=0.02)
    assert ((ours_a - azimuth + 180.0) % 360.0) - 180.0 == \
        pytest.approx(0.0, abs=0.02)


def test_naive_datetimes_are_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        solar_position(0.0, 0.0, datetime(2026, 3, 20, 12))


@pytest.mark.parametrize("raw,canonical", [
    ("Dawn", "dawn"), ("midday", "noon"), ("evening", "golden hour"),
    ("  Golden   Hour ", "golden hour"), ("9:05", "09:05"),
    ("17:40z", "17:40Z"), ("17:40 UTC", "17:40Z"), ("nighttime", "night"),
])
def test_canonical_spellings(raw, canonical):
    assert canonical_time_of_day(raw) == canonical


@pytest.mark.parametrize("bad", ["teatime", "25:00", "12:60", "", "noonish"])
def test_unknown_times_are_refused(bad):
    with pytest.raises(ValueError, match="not one of"):
        canonical_time_of_day(bad)


def test_solar_noon_is_the_highest_sun_and_due_south():
    noon = resolve("noon", *MATTERHORN, date(2026, 3, 20))
    # At the equinox the noon sun stands at 90 - latitude (plus a little
    # declination drift and refraction).
    assert noon.elevation_deg == pytest.approx(90.0 - MATTERHORN[0], abs=0.5)
    assert noon.azimuth_deg == pytest.approx(180.0, abs=0.5)
    for offset in ("11:30", "12:30"):
        assert resolve(offset, *MATTERHORN, date(2026, 3, 20)).elevation_deg \
            < noon.elevation_deg


def test_southern_hemisphere_noon_sun_is_in_the_north():
    """The old fixed look put the noon sun at azimuth 180 everywhere --
    in Sydney that is the wrong half of the sky."""
    noon = resolve("noon", -33.87, 151.21, date(2026, 1, 15))
    assert min(noon.azimuth_deg, 360.0 - noon.azimuth_deg) < 5.0


def test_elevation_events_land_on_their_elevation_and_side():
    day = date(2026, 6, 21)
    dawn = resolve("dawn", *YOSEMITE, day)
    golden = resolve("golden hour", *YOSEMITE, day)
    sunrise = resolve("sunrise", *YOSEMITE, day)
    # Geometric targets; the apparent value adds refraction (~0.1 deg
    # at 8 deg, ~0.25 deg at 3 deg).
    assert dawn.elevation_deg == pytest.approx(8.0, abs=0.35)
    assert golden.elevation_deg == pytest.approx(8.0, abs=0.35)
    assert sunrise.elevation_deg == pytest.approx(3.0, abs=0.5)
    assert 0.0 < dawn.azimuth_deg < 180.0        # rising: eastern sky
    assert 180.0 < golden.azimuth_deg < 360.0    # setting: western sky
    assert sunrise.when_utc < dawn.when_utc < golden.when_utc


def test_an_event_that_never_happens_refuses_by_name():
    """Tromso in December: the sun never reaches 8 deg, so there is no
    'dawn' as defined -- refused, never quietly moved to noon."""
    with pytest.raises(SunError) as caught:
        resolve("dawn", 69.65, 18.96, date(2026, 12, 21))
    assert caught.value.constraint == "sun.event_absent"


def test_utc_clock_time_is_that_exact_instant():
    sun = resolve("17:40Z", *YOSEMITE, date(2026, 9, 1))
    when = datetime(2026, 9, 1, 17, 40, tzinfo=timezone.utc)
    assert sun.when_utc == when
    assert (sun.elevation_deg, sun.azimuth_deg) == \
        solar_position(*YOSEMITE, when)


def test_solar_clock_time_follows_longitude():
    """Local SOLAR 12:00 is later in UTC the further west you are:
    4 minutes per degree (plus the equation of time)."""
    east = resolve("12:00", 0.0, 0.0, date(2026, 3, 20)).when_utc
    west = resolve("12:00", 0.0, -90.0, date(2026, 3, 20)).when_utc
    assert (west - east).total_seconds() == pytest.approx(
        timedelta(hours=6).total_seconds(), abs=60.0)


def test_missing_date_uses_the_recorded_default():
    sun = resolve("noon", *MATTERHORN)
    assert sun.when_utc.date() == DEFAULT_DATE
    assert "no date stated" in sun.basis


def test_night_resolves_then_refuses_to_render():
    sun = resolve("night", *MATTERHORN, date(2026, 6, 21))
    assert sun.elevation_deg < RENDER_FLOOR_DEG
    with pytest.raises(SunError) as caught:
        require_renderable(sun)
    assert caught.value.constraint == "sun.below_render_floor"
    require_renderable(resolve("noon", *MATTERHORN, date(2026, 6, 21)))


# -- the spec field and the compilers ---------------------------------------

@pytest.mark.parametrize("prompt,value,source", [
    ("fly the c172 over yosemite at dawn", "dawn", Source.INFERRED),
    ("an evening flight in the 747", "golden hour", Source.INFERRED),
    ("fly the 747 at 17:40z", "17:40Z", Source.USER),
    ("fly the cessna at 5 pm", "17:00", Source.USER),
    ("fly the cessna at 10:15 am", "10:15", Source.USER),
    ("fly the c172 in the afternoon", "afternoon", Source.INFERRED),
    ("fly the c172 at 1500 m and 100 kt", "none", Source.DEFAULT),
])
def test_compiler_reads_the_time_of_day(prompt, value, source):
    q = compile_prompt(prompt).time_of_day
    assert (q.value, q.source) == (value, source)


def test_afternoon_is_not_read_as_noon():
    assert compile_prompt("an afternoon flight").time_of_day.value == \
        "afternoon"


def test_time_of_day_is_digest_relevant_and_round_trips():
    from core.scenario.spec import ScenarioSpec

    base = compile_prompt("fly the c172 at 1500 m")
    dawn = compile_prompt("fly the c172 at 1500 m")
    dawn.set("time_of_day", "dawn")
    assert base.digest() != dawn.digest()
    assert ScenarioSpec.from_dict(dawn.to_dict()).digest() == dawn.digest()


def test_llm_time_of_day_is_canonicalised_and_checked():
    from core.nl.llm_compiler import LLMCompileError, compile_prompt_llm
    from tests.test_llm_compiler import entry, fake_client

    result = compile_prompt_llm("an evening flight", client=fake_client({
        "fields": {"time_of_day": entry("Evening", "inferred", "evening")},
        "notes": [], "questions": []}))
    assert result.spec.time_of_day.value == "golden hour"
    assert result.spec.time_of_day.source is Source.INFERRED

    with pytest.raises(LLMCompileError, match="time_of_day"):
        compile_prompt_llm("a teatime flight", client=fake_client({
            "fields": {"time_of_day": entry("teatime", "model", "teatime")},
            "notes": [], "questions": []}))


# -- the webapp's look --------------------------------------------------------

def test_no_time_of_day_means_the_default_look():
    from webapp.runs import sun_look

    assert sun_look(compile_prompt("fly the 747 at 280 kt")) is None


def test_exposure_is_interpolated_between_calibrations_and_held_outside():
    from experiments.showcase_matrix import TIME_OF_DAY
    from webapp.runs import exposure_bias_for

    dawn, noon = TIME_OF_DAY["dawn"], TIME_OF_DAY["noon"]
    assert exposure_bias_for(dawn["sun_elev"])[0] == dawn["exposure_bias"]
    assert exposure_bias_for(noon["sun_elev"])[0] == noon["exposure_bias"]
    middle = (dawn["sun_elev"] + noon["sun_elev"]) / 2.0
    bias, basis = exposure_bias_for(middle)
    assert bias == pytest.approx(
        (dawn["exposure_bias"] + noon["exposure_bias"]) / 2.0, abs=0.01)
    assert "interpolated" in basis
    assert exposure_bias_for(3.0) == (dawn["exposure_bias"],
                                      exposure_bias_for(3.0)[1])
    assert "held" in exposure_bias_for(3.0)[1]
    assert "held" in exposure_bias_for(70.0)[1]


def test_a_stated_time_reaches_the_render_command(tmp_path, monkeypatch):
    import webapp.runs as runs

    spec = compile_prompt("fly the c172 over yosemite at dawn")
    spec.set("latitude", YOSEMITE[0])
    spec.set("longitude", YOSEMITE[1])
    look = runs.sun_look(spec)
    assert look["sun_elev"] == pytest.approx(8.0, abs=0.35)
    assert "NOAA" in look["note"] and "VISUAL" in look["note"]

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = list(command)

    launch_through_run(monkeypatch)
    monkeypatch.setattr(runs.subprocess, "run", fake_run)
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "frames",
                            {"key": "flat", "terrain": None, "imagery": None},
                            tmp_path / "missing_mesh.json", "c172p",
                            look=look)
    command = captured["command"]
    assert f"-sun-elev={look['sun_elev']}" in command
    assert f"-sun-azim={look['sun_azim']}" in command
    assert f"-exposure-bias={look['exposure_bias']}" in command


def test_start_refuses_a_night_render_by_name(tmp_path):
    from webapp.runs import RunManager

    spec = compile_prompt("a night flight in the c172")
    result = RunManager(out_root=tmp_path).start(spec, {})
    assert result["constraint"] == "sun.below_render_floor"
