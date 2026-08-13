"""Severe weather (Phase 9.2/9.3): storm composition and the Rankine tornado.

The claims under test: the tornado is the documented kinematic vortex and
nothing more; the thunderstorm is a COMPOSITION of pieces that each passed
their own gates; both reach the FDM measurably in both hosts; the funnel
is labeled a visual marker; a stated turbulence word is never moved.
"""

import math
from pathlib import Path

import pytest

from core.environment.tornado import (
    R_CORE_M, V_MAX_MPS, W_MAX_MPS, TornadoVortex,
)
from core.nl.compiler import compile_prompt
from core.scenario.validate import validate

REPO = Path(__file__).resolve().parents[1]
BRIDGE = (REPO / "ue" / "Plugins" / "FlightSimBridge" / "Source"
          / "FlightSimBridge" / "Private")


# -- the vortex field ----------------------------------------------------


def test_rankine_profile_peaks_at_the_core_and_decays_as_one_over_r():
    t = TornadoVortex(0.0, 0.0)
    def speed(r):
        n, e, _ = t.wind_components(r, 0.0, 300.0)
        return math.hypot(n, e)
    assert speed(R_CORE_M) == pytest.approx(V_MAX_MPS)
    assert speed(R_CORE_M / 2) == pytest.approx(V_MAX_MPS / 2)
    assert speed(2 * R_CORE_M) == pytest.approx(V_MAX_MPS / 2)
    assert speed(10 * R_CORE_M) == pytest.approx(V_MAX_MPS / 10)


def test_rotation_is_cyclonic_counter_clockwise_from_above():
    t = TornadoVortex(0.0, 0.0)
    north_rim = t.wind_components(R_CORE_M, 0.0, 300.0)
    east_rim = t.wind_components(0.0, R_CORE_M, 300.0)
    assert north_rim[1] < 0        # north of the centre: flow WEST
    assert east_rim[0] > 0         # east of the centre: flow NORTH


def test_updraft_lives_in_the_core_and_the_field_fades_aloft():
    t = TornadoVortex(0.0, 0.0)
    assert t.wind_components(0.0, 0.0, 300.0)[2] == pytest.approx(-W_MAX_MPS)
    assert t.wind_components(2 * R_CORE_M, 0.0, 300.0)[2] == 0.0
    assert t.wind_components(R_CORE_M, 0.0, 5000.0) == (0.0, 0.0, 0.0)
    half = t.wind_components(R_CORE_M, 0.0, 2250.0)   # midway through fade
    assert math.hypot(half[0], half[1]) == pytest.approx(V_MAX_MPS / 2)


# -- vocabulary and composition ------------------------------------------


def test_storm_words_compile_and_unknown_events_refuse():
    assert str(compile_prompt(
        "fly the 747 through a thunderstorm").weather_event.value) \
        == "thunderstorm"
    assert str(compile_prompt(
        "fly the c172p near a tornado").weather_event.value) == "tornado"
    spec = compile_prompt("fly the 747 at 3000 m")
    spec.set("weather_event", "hurricane", frm="test")
    report = validate(spec, check_feasibility=False)
    assert [v.constraint for v in report.violations] == [
        "environment.weather_event"]


def test_thunderstorm_composition_never_moves_a_stated_word():
    from webapp.runs import apply_weather_event

    storm = compile_prompt("fly the 747 through a thunderstorm at 3000 m")
    apply_weather_event(storm)
    assert str(storm.turbulence.value) == "severe"
    assert "composition" in storm.turbulence.frm

    stated = compile_prompt(
        "fly the 747 through a thunderstorm in light turbulence")
    apply_weather_event(stated)
    assert str(stated.turbulence.value) == "light"    # never moved

    # A tornado brings its environment: system-chosen ambient fields are
    # planned to the composition's documented figures (source derived) --
    # the vortex is still the position-coupled field on top.
    twister = compile_prompt("fly the 747 near a tornado at 1000 m")
    apply_weather_event(twister)
    assert str(twister.turbulence.value) == "severe"
    assert str(twister.turbulence.source) == "derived"
    assert float(twister.wind_speed.value) == 25.0    # vocabulary 'strong'
    assert str(twister.wind_speed.source) == "derived"

    # Stated conditions are never moved by the composition.
    calm_stated = compile_prompt(
        "fly the 747 near a tornado at 1000 m with 5 kt wind and "
        "light turbulence")
    apply_weather_event(calm_stated)
    assert float(calm_stated.wind_speed.value) == 5.0
    assert str(calm_stated.turbulence.value) == "light"


# -- the physics reaches the FDM -----------------------------------------


def test_tornado_run_output_differs_from_plain_run():
    from core.scenario.runner import run_spec

    plain = compile_prompt("fly the 747 at 800 m and 250 kt for 4 seconds")
    twister = compile_prompt(
        "fly the 747 near a tornado at 800 m and 250 kt for 4 seconds")
    a = run_spec(plain, validate_first=False)
    # assert_closure=False: the vortex legitimately defeats the autopilot
    # (measured: +7.5 m/s residual climb at 4 s -- the tornado doing its
    # job); a held-state tornado spec through the STRICT path raises
    # ClosureError, which is its own honest behaviour, not this test's.
    b = run_spec(twister, validate_first=False, assert_closure=False)
    assert a.output_digest != b.output_digest
    assert "tornado" in str(b.manifest["environment"]).lower()


# -- the UE port (source-pinned) -----------------------------------------


def test_ue_tornado_port_mirrors_the_python_field():
    text = (BRIDGE / "FlightSimScenarioWorld.cpp").read_text()
    body = text.split("FFlightSimScenarioWorld::TornadoWindMps", 1)[-1]
    head = body.split("bool FFlightSimScenarioWorld::Crashed", 1)[0]
    assert "Vt * (De / R) * Fade" in head          # cyclonic sense
    assert "Card.TornadoRCoreMetres / R" in head   # 1/r exterior
    assert "TornadoWindMps(Card, North, East, AglMetres" in text  # Step wiring


def test_funnel_is_labeled_a_visual_marker():
    text = (BRIDGE / "FlightSimScenarioWorld.cpp").read_text()
    assert "VISUAL marker of" in text
    assert "not condensation" in text
    # And the mesh never enters the physics: no collision on the funnel.
    funnel = text.split("TornadoFunnel", 1)[-1].split("RegisterComponent", 1)[0]
    assert "NoCollision" in funnel


def test_through_a_tornado_aims_the_core_at_the_track():
    """'through/into a tornado' records aim=core in the spec (digest-
    relevant detail) and both hosts place the vortex axis ON the track;
    'near a tornado' stays the 2.5-core-radii flyby."""
    from core.nl.compiler import compile_prompt

    through = compile_prompt("fly the c172p through a tornado")
    near = compile_prompt("fly the c172p near a tornado")
    assert through.weather_event.detail["aim"] == "core"
    assert near.weather_event.detail["aim"] == "abeam"
    assert through.digest() != near.digest()


def test_defaulted_altitude_descends_into_the_vortex_band():
    """The vortex fades out by 3000 m AGL, exactly the default cruise: a
    defaulted altitude drops to 800 m (recorded); a stated one never
    moves, even when that honestly puts the plane above the tornado."""
    from core.nl.compiler import compile_prompt
    from webapp.runs import plan_weather_event

    spec = compile_prompt("fly the c172p through a tornado")
    assert str(spec.altitude.source) == "default"
    plan_weather_event(spec)
    assert float(spec.altitude.value) == 800.0
    assert "never moved" in spec.altitude.frm

    stated = compile_prompt("fly the c172p at 2800 m through a tornado")
    plan_weather_event(stated)
    assert float(stated.altitude.value) == 2800.0
