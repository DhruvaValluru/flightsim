"""The altitude guide: what an altitude looks like, so a prompt can ask for one.

A prompt's altitude ("at 3000 m", "at 10000 ft", "FL350") is height above
SEA LEVEL (the spec's ``altitude`` is metres MSL, the same datum JSBSim and
the validator use), while what a person pictures is height above the
GROUND. Over the sea the two agree; over Denver (about 1600 m up) "at
1000 m" is underground and the validator refuses it as
``altitude.terrain_clearance``. The guide shows both: a ladder of
checkpoints above the ground, each converted to the number to ask for
over the scene's ground, beside reference heights everyone knows.

Everything here is presentation: rounded, typical values for orientation,
never a limit the validator or the planner uses. The safety floor the
page draws IS the validator's, imported, so the picture and the refusal
cannot disagree.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .validate import MIN_CLEARANCE_M

FT_PER_M = 1.0 / 0.3048

#: Checkpoints ABOVE THE GROUND (m AGL), lowest first, each with what the
#: view and the flying are like there. Rounded, typical, for orientation.
CHECKPOINTS_AGL: List[Dict[str, Any]] = [
    {"agl_m": 60, "label": "Treetop / rooftop",
     "note": "take-off and landing only; buildings tower over the wings"},
    {"agl_m": 150, "label": "Very low",
     "note": "about the lowest legal height over open country (500 ft); "
             "cars and people easy to see"},
    {"agl_m": 300, "label": "Landing pattern",
     "note": "where small planes circle an airport (1,000 ft); streets and "
             "houses in detail"},
    {"agl_m": 600, "label": "Low cruise / scenic",
     "note": "good for footage of a city or a coastline; roads and rivers "
             "easy to follow"},
    {"agl_m": 1500, "label": "Small-plane cruise",
     "note": "a Cessna's usual cruise; towns look like a map, often near "
             "the cloud base"},
    {"agl_m": 3000, "label": "Mid altitude",
     "note": "the simulator's default (over flat ground); above most hills, "
             "below the big mountains"},
    {"agl_m": 6000, "label": "High",
     "note": "turboprops and fighters; above every peak in the Alps and the "
             "Rockies"},
    {"agl_m": 11000, "label": "Airliner cruise",
     "note": "where jets cruise (about 36,000 ft); the ground is hazy, "
             "above almost all weather"},
]

#: Reference heights. ``base`` says what the number is measured from:
#: "ground" (a structure's own height) or "sea" (a summit's elevation).
LANDMARKS: List[Dict[str, Any]] = [
    {"height_m": 93, "base": "ground", "label": "Statue of Liberty",
     "kind": "building"},
    {"height_m": 330, "base": "ground", "label": "Eiffel Tower",
     "kind": "building"},
    {"height_m": 443, "base": "ground", "label": "Empire State Building",
     "kind": "building"},
    {"height_m": 828, "base": "ground", "label": "Burj Khalifa",
     "kind": "building"},
    {"height_m": 1609, "base": "sea", "label": "Denver (the ground itself)",
     "kind": "ground"},
    {"height_m": 3776, "base": "sea", "label": "Mount Fuji", "kind": "peak"},
    {"height_m": 4478, "base": "sea", "label": "Matterhorn", "kind": "peak"},
    {"height_m": 8849, "base": "sea", "label": "Mount Everest",
     "kind": "peak"},
]

#: Where each aircraft in the vocabulary typically cruises and how high it
#: can go (m MSL). Rounded published figures for orientation only; the
#: flight model's own envelope is what the validator checks.
AIRCRAFT_TYPICAL: Dict[str, Dict[str, Any]] = {
    "c172p": {"label": "Cessna 172", "cruise_m": 2400, "ceiling_m": 4100},
    "DHC6": {"label": "Twin Otter", "cruise_m": 3000, "ceiling_m": 7600},
    "p51d": {"label": "P-51D Mustang", "cruise_m": 7600, "ceiling_m": 12800},
    "A4": {"label": "A-4 Skyhawk", "cruise_m": 9000, "ceiling_m": 12900},
    "A320": {"label": "Airbus A320", "cruise_m": 11000, "ceiling_m": 12100},
    "737": {"label": "Boeing 737", "cruise_m": 11000, "ceiling_m": 12500},
    "B747": {"label": "Boeing 747", "cruise_m": 10700, "ceiling_m": 13700},
    "global5000": {"label": "Global 5000", "cruise_m": 12500,
                   "ceiling_m": 15500},
    "f16": {"label": "F-16", "cruise_m": 9000, "ceiling_m": 15200},
    "f15": {"label": "F-15", "cruise_m": 9000, "ceiling_m": 19800},
}

HOW_TO_ASK = [
    "at 3000 m", "at 10000 ft", "FL350 (35,000 ft)",
]


def ask_for(agl_m: float, ground_m: float, unit: str = "m") -> float:
    """The altitude to put in the prompt for ``agl_m`` above ground at
    ``ground_m`` MSL, in ``unit`` ("m" or "ft"), rounded UP to a number
    people type -- never below the checkpoint it stands for."""
    msl = max(float(ground_m), 0.0) + float(agl_m)
    if unit == "ft":
        return float(math.ceil(msl * FT_PER_M / 100.0) * 100)
    step = 10.0 if msl < 1000 else 50.0 if msl < 5000 else 100.0
    return float(math.ceil(msl / step - 1e-9) * step)


def guide(ground_m: float = 0.0) -> Dict[str, Any]:
    """The whole guide for a scene whose ground is at ``ground_m`` MSL."""
    ground = float(ground_m)
    checkpoints = []
    for point in CHECKPOINTS_AGL:
        checkpoints.append({
            **point,
            "agl_ft": round(point["agl_m"] * FT_PER_M, -1),
            "ask_m": ask_for(point["agl_m"], ground),
            "ask_ft": ask_for(point["agl_m"], ground, unit="ft"),
        })
    return {
        "ground_m": ground,
        "datum": "the prompt's altitude is above SEA LEVEL (MSL); the "
                 "checkpoints are above the GROUND, converted to the "
                 "number to ask for over this ground",
        "min_clearance_m": MIN_CLEARANCE_M,
        "checkpoints": checkpoints,
        "landmarks": LANDMARKS,
        "aircraft": AIRCRAFT_TYPICAL,
        "how_to_ask": HOW_TO_ASK,
    }
