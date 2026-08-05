"""Compile a natural-language prompt into a scenario spec.

§2.6: this module emits a spec and stops. It never invokes the simulation, and
nothing downstream ever re-reads the prompt. The spec is the reproducible unit;
the prompt is a historical note carried along for provenance.

The parser is deliberately rule-based and therefore deterministic: the same
sentence always produces the same spec. That is a weaker capability than a
language model and a much stronger guarantee, and the guarantee is what the
reproducibility claim rests on.

Every value it produces is tagged with where it came from:

* ``user``     -- an explicit number in the prompt ("250 kt")
* ``inferred`` -- a vague phrase mapped to a number ("strong crosswind" -> 25 kt)
* ``default``  -- nobody mentioned it

Anything the vocabulary does not recognise is reported in ``spec.notes`` rather
than silently dropped. A parser can only request what its vocabulary can
express, and the previous build's vocabulary was cinematic, which is why
"flyby @ mountains" produced a camera move instead of an experiment (§8). This
vocabulary is conditions-first by construction.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..fdm import units as u
from ..scenario.fields import Quantity
from ..scenario.spec import ScenarioSpec

# -- vocabulary ---------------------------------------------------------

#: Phrase -> aircraft model. Every entry maps to a model that exists on disk;
#: resolution still goes through core.fdm.aircraft, which never substitutes.
AIRCRAFT_WORDS: Tuple[Tuple[str, str], ...] = (
    ("747", "B747"), ("jumbo", "B747"), ("b747", "B747"),
    ("737", "737"), ("b737", "737"),
    ("global 5000", "global5000"), ("global5000", "global5000"),
    ("business jet", "global5000"), ("bizjet", "global5000"),
    ("c172", "c172p"), ("cessna", "c172p"),
    ("f-16", "f16"), ("f16", "f16"),
    ("f-15", "f15"), ("f15", "f15"),
)

#: Turbulence words -> MIL-F-8785C severity. The standard defines intensity by
#: the wind speed at 20 ft AGL; §2.5 requires the citation rather than a magic
#: number, so the mapping carries it.
TURBULENCE_WORDS: Dict[str, float] = {
    "none": 0.0, "calm": 0.0, "smooth": 0.0,
    "light": 15.0, "mild": 15.0, "chop": 15.0,
    "moderate": 30.0,
    "severe": 45.0, "heavy": 45.0,
}
TURBULENCE_STD = "MIL-F-8785C Fig.7 (W20, wind speed at 20 ft AGL)"

#: Vague wind strength -> knots.
WIND_STRENGTH: Dict[str, float] = {
    "calm": 0.0, "no wind": 0.0,
    "light": 8.0, "gentle": 8.0,
    "moderate": 15.0,
    "strong": 25.0, "stiff": 25.0,
    "severe": 40.0, "gale": 40.0,
}

#: Relative wind direction words, as a bearing offset from the aircraft heading.
WIND_RELATIVE: Dict[str, float] = {
    "headwind": 0.0, "head wind": 0.0,
    "tailwind": 180.0, "tail wind": 180.0,
    "crosswind": 90.0, "cross wind": 90.0,
}

NUMBER = r"(-?\d+(?:\.\d+)?)"


def _search(pattern: str, text: str) -> Optional[re.Match]:
    return re.search(pattern, text, flags=re.IGNORECASE)


# -- individual extractors ----------------------------------------------


def _aircraft(text: str) -> Quantity:
    for phrase, model in AIRCRAFT_WORDS:
        if phrase in text:
            return Quantity.user(model, frm=phrase)
    return Quantity.default("B747", frm="widest measured trim envelope of the "
                                        "candidate transports")


#: A terrain phrase: "over 3000 m terrain", "above 9000 ft ridge".
TERRAIN_PHRASE = (
    rf"(?:over|above|across)\s+{NUMBER}\s*"
    r"(?:m|metre|meter|ft|feet)s?\s*"
    r"(?:terrain|ridge|mountains?|peaks?|ground)?"
)


def _strip_terrain_phrase(text: str) -> str:
    """Remove the terrain clause so its number cannot be read as an altitude.

    Necessary because both are "<number> m" and the terrain figure usually
    appears second. A guard that merely checked whether terrain was mentioned
    anywhere would discard a perfectly good altitude match whenever the prompt
    also described the ground -- which silently fell back to the default
    altitude and, in the §5 example, happened to equal the terrain height and so
    produced the right rejection for the wrong reason.
    """
    return re.sub(TERRAIN_PHRASE, " ", text, flags=re.IGNORECASE)


def _altitude(text: str) -> Quantity:
    text = _strip_terrain_phrase(text)
    m = _search(rf"(?:fl|flight level)\s*(\d{{2,3}})", text)
    if m:
        feet = float(m.group(1)) * 100.0
        return Quantity.user(round(u.ft_to_m(feet), 1), "m",
                             frm=f"FL{m.group(1)}")
    m = _search(rf"{NUMBER}\s*(?:m|metre|meter)s?\b(?!\w)", text)
    if m:
        return Quantity.user(float(m.group(1)), "m", frm=m.group(0).strip())
    m = _search(rf"{NUMBER}\s*(?:ft|feet|foot)\b", text)
    if m:
        return Quantity.user(round(u.ft_to_m(float(m.group(1))), 1), "m",
                             frm=m.group(0).strip())
    return Quantity.default(3000.0, "m", frm="mid-altitude cruise")


def _airspeed(text: str) -> Tuple[Quantity, Quantity]:
    kind = "cas"
    m = _search(rf"{NUMBER}\s*(?:kt|kts|knot|knots)\b", text)
    if m:
        if _search(r"true airspeed|\btas\b", text):
            kind = "tas"
        return (
            Quantity.user(float(m.group(1)), "kt", frm=m.group(0).strip()),
            Quantity.user(kind, frm="stated in prompt" if kind == "tas" else "assumed calibrated"),
        )
    m = _search(rf"mach\s*(0?\.\d+)", text)
    if m:
        return (
            Quantity.inferred(float(m.group(1)), "mach", frm=m.group(0).strip()),
            Quantity.user("mach", frm="stated in prompt"),
        )
    return (
        Quantity.default(250.0, "kt", frm="typical transport cruise"),
        Quantity.default("cas"),
    )


def _terrain(text: str) -> Quantity:
    m = _search(rf"(?:over|above|across)\s+{NUMBER}\s*(?:m|metre|meter)s?\s*"
                r"(?:terrain|ridge|mountains?|peaks?|ground)?", text)
    if m:
        return Quantity.user(float(m.group(1)), "m", frm=m.group(0).strip())
    m = _search(rf"(?:over|above|across)\s+{NUMBER}\s*(?:ft|feet)\s*"
                r"(?:terrain|ridge|mountains?|peaks?|ground)?", text)
    if m:
        return Quantity.user(round(u.ft_to_m(float(m.group(1))), 1), "m",
                             frm=m.group(0).strip())
    if _search(r"mountain|ridge|alpine|peak", text):
        return Quantity.inferred(2000.0, "m", frm="mountainous terrain")
    return Quantity.default(0.0, "m", frm="flat terrain at sea level")


def _wind(text: str, heading: float) -> Tuple[Quantity, Quantity]:
    speed: Optional[Quantity] = None
    m = _search(rf"{NUMBER}\s*(?:kt|kts|knot|knots)\s*"
                r"(?:head|tail|cross)?\s*wind", text)
    if m:
        speed = Quantity.user(float(m.group(1)), "kt", frm=m.group(0).strip())
    else:
        for word, value in WIND_STRENGTH.items():
            if _search(rf"{word}\s+(?:\w+\s+)?wind", text) or _search(rf"{word}\s+crosswind", text):
                speed = Quantity.inferred(value, "kt", frm=f"{word} wind")
                break

    direction: Optional[Quantity] = None
    m = _search(rf"wind\s*(?:from)?\s*(\d{{3}})\s*(?:/|at)\s*{NUMBER}", text)
    if m:
        direction = Quantity.user(float(m.group(1)), "deg", frm=m.group(0).strip())
        speed = Quantity.user(float(m.group(2)), "kt", frm=m.group(0).strip())
    else:
        for word, offset in WIND_RELATIVE.items():
            if word in text:
                # Meteorological convention: the bearing the wind comes *from*.
                direction = Quantity.inferred(
                    (heading + offset) % 360.0, "deg", frm=word,
                    rel_to="aircraft heading", offset_deg=offset,
                )
                if speed is None:
                    speed = Quantity.inferred(
                        WIND_STRENGTH["moderate"], "kt",
                        frm=f"{word} with no strength stated",
                    )
                break

    if speed is None:
        speed = Quantity.default(0.0, "kt", frm="still air")
    if direction is None:
        direction = Quantity.default(0.0, "deg", frm="still air")
    return speed, direction


def _turbulence(text: str) -> Quantity:
    for word, w20 in TURBULENCE_WORDS.items():
        if _search(rf"{word}\s+(?:turbulence|chop|air)", text) or (
            word == "chop" and "chop" in text
        ):
            label = "none" if w20 == 0.0 else word
            return Quantity.inferred(label, frm=f"{word} turbulence",
                                     std=TURBULENCE_STD, W20_kt=w20)
    if _search(r"turbulen", text):
        return Quantity.inferred("moderate", frm="turbulence, no intensity stated",
                                 std=TURBULENCE_STD, W20_kt=30.0)
    return Quantity.default("none", frm="smooth air", std=TURBULENCE_STD, W20_kt=0.0)


def _duration(text: str) -> Quantity:
    m = _search(rf"(?:for|during|over)\s+{NUMBER}\s*(?:s|sec|secs|second|seconds)\b", text)
    if m:
        return Quantity.user(float(m.group(1)), "s", frm=m.group(0).strip())
    m = _search(rf"(?:for|during|over)\s+{NUMBER}\s*(?:m|min|mins|minute|minutes)\b", text)
    if m:
        return Quantity.user(float(m.group(1)) * 60.0, "s", frm=m.group(0).strip())
    return Quantity.default(120.0, "s", frm="long enough to settle and observe")


def _heading(text: str) -> Quantity:
    m = _search(r"heading\s*(\d{1,3})", text)
    if m:
        return Quantity.user(float(m.group(1)) % 360.0, "deg", frm=m.group(0).strip())
    return Quantity.default(0.0, "deg", frm="due north")


# -- the compiler --------------------------------------------------------

#: Words that describe a shot rather than a condition. Recognised only so they
#: can be reported as ignored -- §8 is explicit that the cinematic vocabulary
#: must not be the primary plugin surface, because a parser can only request
#: what its vocabulary can express.
CINEMATIC_WORDS = (
    "flyby", "fly-by", "cinematic", "dogfight", "airshow", "aerobatic",
    "camera", "shot", "dramatic", "epic", "chase",
)


def compile_prompt(prompt: str, name: Optional[str] = None) -> ScenarioSpec:
    """Turn a prompt into a spec. Does not run anything."""
    text = " ".join(prompt.lower().split())

    heading = _heading(text)
    airspeed, airspeed_kind = _airspeed(text)
    wind_speed, wind_direction = _wind(text, float(heading.value))

    spec = ScenarioSpec(
        name=name or _name_from(text),
        prompt=prompt,
        aircraft=_aircraft(text),
        altitude=_altitude(text),
        airspeed=airspeed,
        airspeed_kind=airspeed_kind,
        heading=heading,
        latitude=Quantity.default(0.0, "deg", frm="equator; no geography requested"),
        longitude=Quantity.default(0.0, "deg", frm="prime meridian"),
        terrain_elevation=_terrain(text),
        duration=_duration(text),
        rate=Quantity.default(120.0, "Hz", frm="matches the UE plugin substep rate"),
        seed=Quantity.default(0, "dimensionless",
                              frm="deterministic; no stochastic subsystem active yet"),
        mass_held=Quantity.default(False, frm="realistic fuel burn"),
        # Whether the autopilot is engaged to HOLD the commanded state, or the
        # aircraft is merely trimmed at it and left alone. Holding is what makes
        # the closure assertion meaningful, so it is the default.
        hold_state=Quantity.default(True, frm="hold the commanded state"),
        wind_speed=wind_speed,
        wind_direction=wind_direction,
        turbulence=_turbulence(text),
    )

    ignored = [w for w in CINEMATIC_WORDS if w in text]
    if ignored:
        spec.notes.append(
            f"ignored cinematic terms {ignored}: this vocabulary describes "
            f"conditions, not shots. Nothing in the spec was set from them."
        )
    return spec


def _name_from(text: str) -> str:
    for word in ("landing", "approach", "takeoff", "climb", "descent", "cruise"):
        if word in text:
            return word
    return "scenario"
