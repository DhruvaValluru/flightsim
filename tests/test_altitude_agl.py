"""Altitude above the ground (owner, 2026-11-13: frames sat too close to the
ground). A prompt may state height above the ground, and a defaulted altitude
is lifted to clear the terrain, below the airframe's ceiling."""

import pytest

from core.nl.compiler import compile_prompt, stated_agl
from webapp.runs import DEFAULT_AGL_M, plan_flyable_defaults


@pytest.mark.parametrize("phrase,metres", [
    ("1500 m above the ground", 1500.0),
    ("2000 ft agl", 609.6),
    ("800 metres above the terrain", 800.0),
    ("1,200 m above ground level", 1200.0),
])
def test_agl_phrases_are_read(phrase, metres):
    assert stated_agl(f"chase view of the a4 {phrase} for 6 seconds")[0] == pytest.approx(metres, abs=0.1)


def test_plain_altitude_is_not_agl():
    assert stated_agl("chase view of the a4 at 3000 m over yosemite") is None


def test_agl_adds_the_places_ground():
    spec = compile_prompt("chase view of the a4 over yosemite 1500 m above the ground for 6 seconds")
    ground = float(spec.terrain_elevation.value)
    assert ground > 500
    assert float(spec.altitude.value) == pytest.approx(ground + 1500.0, abs=0.5)
    assert str(spec.altitude.source) == "user"


def test_agl_over_the_sea_is_msl():
    spec = compile_prompt("chase view of the 747 over the ocean 2000 m above the ground for 6 seconds")
    assert float(spec.altitude.value) == pytest.approx(
        float(spec.terrain_elevation.value) + 2000.0, abs=0.5)


def test_default_altitude_clears_high_ground():
    spec = compile_prompt("chase view of the a4 over the matterhorn for 6 seconds")
    assert str(spec.altitude.source) == "default"
    plan_flyable_defaults(spec)
    ground = float(spec.terrain_elevation.value)
    assert float(spec.altitude.value) - ground >= DEFAULT_AGL_M - 1


def test_default_lift_stays_below_the_ceiling():
    from core.scenario.altitude_guide import AIRCRAFT_TYPICAL
    spec = compile_prompt("chase view of the c172p over everest for 6 seconds")
    plan_flyable_defaults(spec)
    assert float(spec.altitude.value) <= max(
        0.85 * AIRCRAFT_TYPICAL["c172p"]["ceiling_m"],
        float(spec.terrain_elevation.value) + 300.0) + 1


def test_stated_altitude_is_never_lifted():
    spec = compile_prompt("chase view of the a4 at 1500 m over yosemite for 6 seconds")
    plan_flyable_defaults(spec)
    assert float(spec.altitude.value) == 1500.0


def test_default_over_flat_ground_is_unchanged():
    spec = compile_prompt("fly the a4 for 10 seconds")
    plan_flyable_defaults(spec)
    assert float(spec.altitude.value) == 3000.0
