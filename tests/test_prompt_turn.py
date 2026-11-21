"""A turn the prompt asks for becomes a planned route (webapp/prompt_turn.py)."""

from __future__ import annotations

import math

import pytest

from core.control.route import route_problems, turn_radius_m
from core.nl.compiler import compile_prompt
from webapp.prompt_turn import arc_waypoints, plan_prompt_turn, turn_request


@pytest.mark.parametrize("prompt, direction, bank", [
    ("A-4 in a steep left banking turn over Manhattan", "left", 45.0),
    ("cessna turning right over the grand canyon", "right", 30.0),
    ("a gentle right turn over the bay", "right", 20.0),
    ("747 circling over the city", "left", 30.0),
    ("hard break left at 3000 ft", "left", 45.0),
])
def test_turn_words_are_read(prompt, direction, bank):
    req = turn_request(prompt)
    assert req is not None and req["direction"] == direction and req["bank_deg"] == bank


@pytest.mark.parametrize("prompt", [
    "A-4 over Manhattan at 3000 feet", "return to base through turbulence",
    "turn on the landing lights", None, ""])
def test_no_turn_is_read_where_none_is_asked(prompt):
    assert turn_request(prompt) is None


def test_the_arc_starts_along_the_heading_and_turns_the_way_asked():
    for direction, sign in (("left", -1), ("right", 1)):
        pts = arc_waypoints(90.0, direction, 1000.0, 1500.0, 900.0, 50.0)
        assert pts[0]["east_m"] == pytest.approx(50.0) and pts[0]["north_m"] == pytest.approx(0.0)
        end = pts[-1]
        # Heading east: a left turn bends north (+north), a right turn south.
        assert math.copysign(1, end["north_m"]) == -sign
        # Every arc point is R from the centre.
        cy = 1000.0 if direction == "left" else -1000.0
        for p in pts[1:]:
            assert math.hypot(p["east_m"] - 50.0, p["north_m"] - cy) == pytest.approx(1000.0, abs=0.5)


def _spec(prompt):
    spec = compile_prompt(prompt)
    spec.prompt = prompt
    return spec


def test_a_turn_prompt_plans_a_route_the_rules_accept():
    spec = _spec("A-4 in a steep left banking turn at 3000 m over the desert, 6 seconds")
    calls = []

    def fly_ok(trial, wps, bank):
        calls.append((wps, bank))
        assert bool(trial.hold_state.value)
        return {"ok": True}

    note = plan_prompt_turn(spec, duration_cap_s=22.0, fly_check=fly_ok)
    assert note["planned"] and note["direction"] == "left" and note["bank_limit_deg"] == 45.0
    assert str(spec.route.waypoints.source) == "derived"
    assert bool(spec.hold_state.value)
    wps = spec.route.waypoints.value
    tas = note["tas_kt"]
    assert not route_problems(wps, 45.0, tas_kt=tas, duration_s=note["seconds"],
                              altitude0_m=float(spec.altitude.value))
    assert note["radius_m"] >= 1.5 * turn_radius_m(tas, 45.0) - 1e-6
    assert len(calls) == 1


def test_a_turn_that_never_closes_flies_straight_and_says_why():
    spec = _spec("cessna turning right at 1500 m, 6 seconds")
    note = plan_prompt_turn(spec, fly_check=lambda *a: {"ok": False, "violations": [
        {"constraint": "route.closure"}]})
    assert note["refused"] == "route.turn_plan" and spec.route.is_default()
    assert note["tried"] and all("route.closure" in t["problems"] or t["problems"] for t in note["tried"])


def test_a_drawn_route_or_no_turn_words_are_left_alone():
    spec = _spec("A-4 at 3000 m over the desert, 6 seconds")
    assert plan_prompt_turn(spec, fly_check=lambda *a: {"ok": True}) is None
    spec = _spec("A-4 turning left at 3000 m, 6 seconds")
    spec.set("route.waypoints", [{"east_m": 0.0, "north_m": 500.0, "alt_m": 3000.0}], frm="drawn")
    before = spec.route.waypoints.value
    assert plan_prompt_turn(spec, fly_check=lambda *a: {"ok": True}) is None
    assert spec.route.waypoints.value == before
