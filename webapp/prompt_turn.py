"""A turn the prompt asks for, flown as a planned route.

"steep left banking turn", "turning right", "circle over the city" used
to land only in the spec's notes: no compiler maps a manoeuvre, and the
only thing that makes the aircraft turn is the route block (the
autopilot flies its waypoints, docs/ROUTE.md). This planner closes that
gap: when the prompt asks for a turn and no route is drawn, it lays an
arc in the direction asked, at the bank asked (steep 45 deg, gentle 20,
else 30), sized to the clip's own length and airspeed, checks it with
the route rules (core.control.route.route_problems) and flies it through
the route pre-flight (webapp.route_map.check_route) -- widening the
radius until the autopilot closes on it -- and writes it into the spec as
the SYSTEM's plan (source derived, the phrase on record). A drawn route,
a user-stated autopilot choice, or no turn words leave the spec alone.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

#: The phrases that ask for a turn (word-bounded: "return", "turbulence"
#: and "turn on" do not count).
_TURN = re.compile(
    r"\b(?:(?P<dir1>left|right)[\s-]+(?:hand\s+)?(?:turn|bank|banking|orbit|circle)"
    r"|(?:turn|turning|turns|bank|banking|banks|roll|rolling|rolls|break|breaking)"
    r"\s+(?:hard\s+|steeply\s+|gently\s+)?(?:to\s+(?:the\s+)?)?(?P<dir2>left|right)"
    r"|banking\s+turn|steep\s+turn|(?P<circle>circl(?:e|es|ing)|orbit(?:s|ing)?|360))\b",
    re.IGNORECASE)
_STEEP = re.compile(r"\b(steep|steeply|hard|tight|aggressive|sharp|max(?:imum)?)\b", re.I)
_GENTLE = re.compile(r"\b(gentle|gently|shallow|slight|slow|lazy|easy|wide)\b", re.I)

BANK_STEEP_DEG, BANK_DEFAULT_DEG, BANK_GENTLE_DEG = 45.0, 30.0, 20.0
#: Radius tries, as multiples of the level-turn radius at the bank: the
#: autopilot's pursuit needs room to roll in and close on the arc
#: (Windows r13: 1.5x closed at 45 deg / 200 kt, tighter did not).
RADIUS_STEPS = (1.5, 1.75, 2.0, 2.4, 3.0, 4.0)
#: The share of the clip spent straight before rolling in.
LEAD_SHARE = 0.05
TURN_FROM = "planned from the prompt's turn ('{phrase}'): an arc the autopilot flies"


def turn_request(prompt: Optional[str]) -> Optional[Dict[str, Any]]:
    """{phrase, direction, bank_deg, circle} or None: what turn the prompt
    asks for (left unless 'right' is said)."""
    if not prompt:
        return None
    m = _TURN.search(prompt)
    if not m:
        return None
    direction = (m.group("dir1") or m.group("dir2") or "").lower()
    if not direction:
        direction = "right" if re.search(r"\bright\b", prompt, re.I) else "left"
    bank = (BANK_STEEP_DEG if _STEEP.search(prompt) else
            BANK_GENTLE_DEG if _GENTLE.search(prompt) else BANK_DEFAULT_DEG)
    return {"phrase": m.group(0), "direction": direction, "bank_deg": bank,
            "circle": bool(m.group("circle"))}


def arc_waypoints(heading_deg: float, direction: str, radius_m: float, distance_m: float,
                  altitude_m: float, lead_m: float, step_deg: float = 6.0) -> List[Dict[str, float]]:
    """The route: ``lead_m`` straight along the heading, then an arc of
    ``radius_m`` turning ``direction`` until ``distance_m`` in all, as
    scene-frame waypoints (east, north, alt; the origin not repeated)."""
    sign = -1.0 if direction == "left" else 1.0
    h0 = math.radians(heading_deg)
    fx, fy = math.sin(h0), math.cos(h0)               # forward (east, north)
    rx, ry = math.cos(h0), -math.sin(h0)              # right
    sx, sy = fx * lead_m, fy * lead_m
    pts = [{"east_m": round(sx, 2), "north_m": round(sy, 2), "alt_m": round(altitude_m, 2)}]
    arc = max(0.0, distance_m - lead_m)
    sweep = arc / radius_m
    n = max(2, int(math.ceil(math.degrees(sweep) / step_deg)))
    cx, cy = sx + rx * sign * radius_m, sy + ry * sign * radius_m   # turn centre
    for i in range(1, n + 1):
        a = sweep * i / n
        # Position on the circle: start at (sx, sy), rotate about the centre.
        px = cx - sign * radius_m * (rx * math.cos(a) - fx * sign * math.sin(a))
        py = cy - sign * radius_m * (ry * math.cos(a) - fy * sign * math.sin(a))
        pts.append({"east_m": round(px, 2), "north_m": round(py, 2), "alt_m": round(altitude_m, 2)})
    return pts


def plan_prompt_turn(spec, duration_cap_s: Optional[float] = None,
                     fly_check=None) -> Optional[Dict[str, Any]]:
    """Plan the prompt's turn as a route (see the module doc). Returns a
    note dict when a route was planned, {"refused": ...} when the turn was
    asked but no arc closed, None when nothing applies."""
    from core.control.route import route_problems, tas_kt_for_spec, turn_radius_m

    route = getattr(spec, "route", None)
    if route is None or not route.is_default():
        return None
    request = turn_request(getattr(spec, "prompt", None))
    if request is None:
        return None
    if str(spec.hold_state.source) not in ("default", "model", "derived") \
            and not bool(spec.hold_state.value):
        return None                                   # the user switched the autopilot off
    duration = float(spec.duration.value)
    if duration_cap_s:
        duration = min(duration, float(duration_cap_s))
    tas = tas_kt_for_spec(spec)
    v = tas * 0.514444
    distance = 0.95 * v * duration
    altitude = float(spec.altitude.value)
    heading = float(spec.heading.value)
    bank = request["bank_deg"]
    r_level = turn_radius_m(tas, bank)
    if fly_check is None:
        from webapp.route_map import check_route as fly_check
    tried = []
    for k in RADIUS_STEPS:
        radius = k * r_level
        wps = arc_waypoints(heading, request["direction"], radius, distance, altitude,
                            LEAD_SHARE * distance)
        problems = route_problems(wps, bank, tas_kt=tas, duration_s=duration,
                                  altitude0_m=altitude)
        if problems:
            tried.append({"radius_m": round(radius, 1), "problems": [p["constraint"] for p in problems]})
            continue
        trial = spec.__class__.from_dict(spec.to_dict())
        trial.set("hold_state", True, frm="the planned turn needs the autopilot")
        result = fly_check(trial, wps, bank)
        if not result.get("ok"):
            tried.append({"radius_m": round(radius, 1),
                          "problems": [v_.get("constraint") for v_ in result.get("violations") or []]})
            continue
        frm = TURN_FROM.format(phrase=request["phrase"])
        if not bool(spec.hold_state.value):
            spec.plan("hold_state", True, frm=frm)
        spec.plan("route.waypoints", wps, frm=frm)
        spec.plan("route.bank_limit_deg", bank, frm=frm)
        heading_change = math.degrees((distance * (1 - LEAD_SHARE)) / radius)
        return {"planned": True, "phrase": request["phrase"], "direction": request["direction"],
                "bank_limit_deg": bank, "radius_m": round(radius, 1),
                "heading_change_deg": round(heading_change, 1), "tas_kt": round(tas, 1),
                "seconds": round(duration, 2), "tried": tried}
    return {"refused": "route.turn_plan", "phrase": request["phrase"],
            "message": (f"the prompt asks for a turn ('{request['phrase']}') but no arc up to "
                        f"{RADIUS_STEPS[-1]:g}x the {bank:g} deg turn radius closed in "
                        f"{duration:g} s; it flies straight"),
            "tried": tried}
