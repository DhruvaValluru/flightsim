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
    ("a320", "A320"), ("airbus", "A320"),
    ("f-16", "f16"), ("f16", "f16"),
    ("f-15", "f15"), ("f15", "f15"),
)

#: Turbulence words -> MIL-F-8785C severity. The standard defines intensity by
#: the wind speed at 20 ft AGL; §2.5 requires the citation rather than a magic
#: number, so the mapping carries it.
TURBULENCE_WORDS: Dict[str, float] = {
    "none": 0.0, "calm": 0.0, "smooth": 0.0,
    "light": 15.0, "mild": 15.0, "chop": 15.0,
    "bumpy": 15.0, "choppy": 15.0,
    "moderate": 30.0, "rough": 30.0,
    "violent": 45.0,
    "severe": 45.0, "heavy": 45.0,
}
TURBULENCE_STD = "MIL-F-8785C Fig.7 (W20, wind speed at 20 ft AGL)"

#: Vague wind strength -> knots. THIS TABLE IS THE CONTROL: a model
#: mapping one of these words to any other number is a measurable error,
#: not a matter of opinion (Gate 8.1 grades against it).
WIND_STRENGTH: Dict[str, float] = {
    "calm": 0.0, "no wind": 0.0,
    "light": 8.0, "gentle": 8.0,
    "breezy": 12.0,
    "moderate": 15.0,
    "gusty": 18.0,
    "strong": 25.0, "stiff": 25.0, "rough": 25.0,
    "severe": 40.0, "gale": 40.0, "violent": 40.0, "howling": 40.0,
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
    return (None, None)   # defaulted per aircraft by the caller


#: Defaulted cruise speed PER AIRCRAFT -- "typical transport cruise" was
#: 250 kt for everything, which a c172p cannot fly, so a bare "fly the
#: c172p through a tornado" refused on trim before the tornado ever
#: mattered. Values sit mid-envelope for each model.
CRUISE_DEFAULT_KT: Dict[str, float] = {
    "B747": 250.0, "737": 250.0, "A320": 250.0, "global5000": 250.0,
    "c172p": 100.0, "f16": 350.0, "f15": 350.0,
}


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


#: Surface vocabulary: word variants -> the modelled class
#: (core.environment.surface.SURFACE_CLASSES). Unlisted ground cover is
#: simply not set -- never guessed.
SURFACE_WORDS = {
    "grassland": ("grasslands", "grassland", "prairie", "plains", "meadow"),
    "desert": ("desert", "dunes"),
    "ocean": ("ocean", "the sea", "open water"),
    "forest": ("forest", "woods", "woodland"),
    "city": ("city", "urban", "downtown", "skyline"),
}


def _surface(text: str) -> Quantity:
    for word, variants in SURFACE_WORDS.items():
        for variant in variants:
            if _search(rf"{variant}", text):
                return Quantity.inferred(
                    word, frm=f"ground cover {variant!r}: roughness + "
                              f"thermal class (surface vocabulary)")
    return Quantity.default("unspecified",
                            frm="no ground cover stated; no surface coupling")


#: Severe-weather words -> the modelled event.
WEATHER_EVENT_WORDS = {
    "thunderstorm": ("thunderstorm", "storm cell", "storm"),
    "tornado": ("tornado", "twister"),
}


def _weather_event(text: str) -> Quantity:
    for event, variants in WEATHER_EVENT_WORDS.items():
        for variant in variants:
            if _search(rf"\b{variant}", text):
                # "through/into" aims the event's core AT the track (the
                # aim rides in the quantity's detail, so it is recorded,
                # serialized and digest-relevant like any other value);
                # anything else is the standard abeam flyby.
                aim = ("core" if _search(
                    rf"(?:through|into)\s+(?:a|the)?\s*{variant}", text)
                    else "abeam")
                return Quantity.inferred(
                    event, frm=f"severe weather {variant!r}, aim {aim} "
                               f"(documented composition/model; see "
                               f"conditions strip)", aim=aim)
    return Quantity.default("none", frm="no severe weather requested")


def _weather_date(text: str) -> Quantity:
    """An ISO date in the prompt asks for that day's ERA5 reanalysis wind."""
    match = _search(r"\b(20\d{2}-[01]\d-[0-3]\d)\b", text)
    if match:
        return Quantity.inferred(
            match.group(1), frm=f"historical weather date {match.group(1)} "
                                f"(ERA5 reanalysis applies at /run)")
    return Quantity.default("none", frm="no date stated; spec wind as given")


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
    # A bare "m" is minutes only after "for"/"during": after "over" it is
    # metres ("over 2000 m mountains", "over 3000 m terrain"), and reading
    # it as minutes gave those prompts a 120 000 s duration that the
    # capture then flew in full (measured: the webapp render-flow test hung
    # for the whole 2000-minute flight).
    m = _search(rf"(?:for|during)\s+{NUMBER}\s*(?:m|min|mins|minute|minutes)\b"
                rf"|over\s+{NUMBER}\s*(?:min|mins|minute|minutes)\b", text)
    if m:
        minutes = m.group(1) if m.group(1) is not None else m.group(2)
        return Quantity.user(float(minutes) * 60.0, "s", frm=m.group(0).strip())
    return Quantity.default(120.0, "s", frm="long enough to settle and observe")


def _heading(text: str) -> Quantity:
    m = _search(r"heading\s*(\d{1,3})", text)
    if m:
        return Quantity.user(float(m.group(1)) % 360.0, "deg", frm=m.group(0).strip())
    return Quantity.default(0.0, "deg", frm="due north")


# -- cameras (Camera Phase 1) --------------------------------------------

#: Named views -> camera presets. Deterministic and documented: the same
#: vocabulary the render presets implement, so a view word can only
#: request a view that exists.
CAMERA_VIEW_WORDS: Tuple[Tuple[str, str], ...] = (
    ("cockpit", "cockpit"),
    ("wingman", "wingman"),
    ("from the tower", "tower"),
    ("tower view", "tower"),
    ("control tower", "tower"),
    ("ground observer", "ground"),
    ("from the ground", "ground"),
    ("chase", "chase"),
)

#: Simple lens words -> focal length, mm. Documented middle choices:
#: "wide angle" is the classic 24 mm wide prime, "telephoto" the 85 mm
#: short tele. A stated "<n> mm lens" always wins as user.
LENS_WORDS: Dict[str, float] = {
    "wide angle": 24.0, "wide-angle": 24.0, "telephoto": 85.0,
}


def _camera(text: str, aircraft: str, terrain_elevation_m: float):
    """One CameraSpec when the prompt speaks camera language, else None.

    A named view, an image count ("50 images/frames/stills") or a lens
    word each earns the camera; everything unstated keeps the documented
    defaults (source ``default``, plannable). Shot language the
    vocabulary cannot express still goes to notes via CINEMATIC_WORDS.
    """
    from ..scenario.camera import CameraSpec

    preset = None
    preset_phrase = None
    for phrase, name in CAMERA_VIEW_WORDS:
        if _search(rf"\b{phrase}\b", text):
            preset, preset_phrase = name, phrase
            break
    count = _search(rf"(\d+)\s*(?:images|frames|stills|photos|pictures|"
                    rf"snapshots)\b", text)
    focal = None
    focal_quantity = None
    m = _search(rf"{NUMBER}\s*mm\s+lens", text)
    if m:
        focal_quantity = Quantity.user(float(m.group(1)), "mm",
                                       frm=m.group(0).strip())
    else:
        for word, mm in LENS_WORDS.items():
            if word in text:
                focal_quantity = Quantity.inferred(
                    mm, "mm", frm=f"{word!r} lens word (documented "
                                  f"mapping: wide angle 24 mm, telephoto "
                                  f"85 mm)")
                break
    if preset is None and count is None and focal_quantity is None:
        return None
    camera = CameraSpec.defaulted(
        camera_id="camera0", preset=preset or "chase", aircraft=aircraft,
        terrain_elevation_m=terrain_elevation_m,
        frm="camera language in the prompt; documented camera default")
    if preset is not None:
        camera.preset = Quantity(value=preset, source="inferred",
                                 frm=preset_phrase)
    if count is not None:
        camera.capture_count = Quantity(
            value=int(count.group(1)), unit="dimensionless",
            source="user", frm=count.group(0).strip())
    if focal_quantity is not None:
        camera.focal_length_mm = focal_quantity
    return camera


# -- the compiler --------------------------------------------------------

#: Words that describe a shot rather than a condition. Recognised only so they
#: can be reported as ignored -- §8 is explicit that the cinematic vocabulary
#: must not be the primary plugin surface, because a parser can only request
#: what its vocabulary can express. "camera" and "chase" left this list
#: when the camera vocabulary above learned to express them (Camera
#: Phase 1); genuinely unexpressible shot language stays reported.
CINEMATIC_WORDS = (
    "flyby", "fly-by", "cinematic", "dogfight", "airshow", "aerobatic",
    "shot", "dramatic", "epic",
)


def compile_prompt(prompt: str, name: Optional[str] = None) -> ScenarioSpec:
    """Turn a prompt into a spec. Does not run anything."""
    text = " ".join(prompt.lower().split())

    heading = _heading(text)
    airspeed, airspeed_kind = _airspeed(text)
    if airspeed is None:
        model = str(_aircraft(text).value)
        airspeed = Quantity.default(
            CRUISE_DEFAULT_KT.get(model, 250.0), "kt",
            frm=f"typical cruise for the {model}")
        airspeed_kind = Quantity.default("cas")
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
        surface=_surface(text),
        weather_date=_weather_date(text),
        weather_event=_weather_event(text),
    )

    camera = _camera(text, str(spec.aircraft.value),
                     float(spec.terrain_elevation.value))
    if camera is not None:
        spec.cameras = [camera]

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
