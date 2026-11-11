"""Visual round 5, lane L6: both sun models against NREL SPA (pvlib).

The run card's sun (core/environment/sun.py) and the renderer's sun
(core/sky/astro.py, written to sky.json and placed by FlightSimSky.cpp)
are checked at the instant each of the 14 visual-round scenes resolves
to. The error is the great-circle angle between the two sun directions
(a raw azimuth difference is meaningless at the zenith). Skips by name
when pvlib (requirements-dev.txt) is absent. Table: docs/visual/PROBE_LOG.md.
"""

import math

import pytest

pvlib = pytest.importorskip("pvlib", reason="pvlib not installed (requirements-dev.txt)")
pd = pytest.importorskip("pandas")

from core.environment import sun as sun_model  # noqa: E402
from core.nl.compiler import compile_prompt  # noqa: E402
from core.sky import astro  # noqa: E402
from core.sky.plan import resolve_instant  # noqa: E402
from scripts.run_test_scenarios import SCENARIOS  # noqa: E402

LIMIT_DEG = 0.1


def _spa(lat, lon, when):
    r = pvlib.solarposition.spa_python(pd.DatetimeIndex([when]), lat, lon,
                                       altitude=0, pressure=101325,
                                       temperature=10, delta_t=69.0)
    return float(r.apparent_elevation.iloc[0]), float(r.azimuth.iloc[0])


def _separation_deg(el1, az1, el2, az2):
    e1, e2 = math.radians(el1), math.radians(el2)
    c = (math.sin(e1) * math.sin(e2)
         + math.cos(e1) * math.cos(e2) * math.cos(math.radians(az1 - az2)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _scenes():
    for number, (name, prompt, _edits) in enumerate(SCENARIOS, 1):
        spec = compile_prompt(prompt)
        time_value = str(spec.time_of_day.value)
        yield (number, name, float(spec.latitude.value),
               float(spec.longitude.value),
               "noon" if time_value == "none" else time_value,
               str(spec.weather_date.value))


def test_fourteen_scenes():
    assert len(SCENARIOS) == 15


@pytest.mark.parametrize("scene", list(_scenes()), ids=lambda s: f"{s[0]:02d}")
def test_both_suns_within_a_tenth_of_a_degree_of_spa(scene):
    _n, _name, lat, lon, time_value, weather_date = scene
    card = sun_model.resolve(time_value, lat, lon)
    el, az = _spa(lat, lon, card.when_utc)
    assert abs(card.elevation_deg - el) < LIMIT_DEG
    assert _separation_deg(card.elevation_deg, card.azimuth_deg, el, az) < LIMIT_DEG

    instant = resolve_instant(time_value, weather_date, lat, lon)
    sky = astro.sun_position(instant.utc, lat, lon)
    el, az = _spa(lat, lon, instant.utc)
    assert abs(sky.elevation_deg - el) < LIMIT_DEG
    assert _separation_deg(sky.elevation_deg, sky.azimuth_deg, el, az) < LIMIT_DEG
