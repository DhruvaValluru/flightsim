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
from typing import Any, Dict, List, Optional, Tuple

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
    m = _search(rf"(?:for|during|over)\s+{NUMBER}\s*(?:m|min|mins|minute|minutes)\b", text)
    if m:
        return Quantity.user(float(m.group(1)) * 60.0, "s", frm=m.group(0).strip())
    return Quantity.default(120.0, "s", frm="long enough to settle and observe")


def _heading(text: str) -> Quantity:
    m = _search(r"heading\s*(\d{1,3})", text)
    if m:
        return Quantity.user(float(m.group(1)) % 360.0, "deg", frm=m.group(0).strip())
    return Quantity.default(0.0, "deg", frm="due north")


# -- cameras (Camera Phase 1; vocabulary completed in the gap closure) --

#: Named views -> camera presets. Deterministic and documented: the same
#: vocabulary the render presets implement, so a view word can only
#: request a view that exists. EVERY view named in a sentence becomes a
#: camera ("chase and wingman views" is two), in the order named.
CAMERA_VIEW_WORDS: Tuple[Tuple[str, str], ...] = (
    ("cockpit", "cockpit"),
    ("wingman", "wingman"),
    ("from the tower", "tower"),
    ("tower view", "tower"),
    ("control tower", "tower"),
    ("the tower", "tower"),
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

#: Words that imply imagery without naming a view. A prompt with one of
#: these and NO view word earns the regex path's one clarifying
#: question (which view?) -- the same question the LLM path may ask --
#: and, meanwhile, the documented default chase camera, so the spec
#: still carries what the words did say (a count, a lens).
IMAGERY_WORDS: Tuple[str, ...] = (
    "image", "images", "photo", "photos", "photograph", "picture",
    "pictures", "footage", "film", "video", "frames", "stills",
    "snapshot", "snapshots", "capture", "render", "camera", "shot",
)
CAMERA_QUESTION_ID = "camera_view"
CAMERA_VIEW_OPTIONS = ("chase", "wingman", "tower", "ground", "cockpit")

#: Simple move phrases -> keyframed moves over the whole flight. Each
#: is ONE documented shape, keyed in absolute seconds over the spec's
#: duration (a shorter clip is rescaled by the clip selector, see
#: rescale_moves): "zoom in" doubles the focal length, "zoom out"
#: halves it; "push in" halves an aircraft-relative offset, "pull back"
#: doubles it; "orbit" turns the offset a full circle (ORBIT_SEGMENTS
#: keyframes, a polygon whose chord error is stated). Offsets exist
#: only on the chase and wingman presets, so a push/pull/orbit asked of
#: a tower, ground or cockpit view is reported as ignored, by name.
MOVE_WORDS: Tuple[Tuple[str, str], ...] = (
    ("zoom in", "zoom_in"), ("zoom out", "zoom_out"),
    ("push in", "push_in"), ("move closer", "push_in"),
    ("move in closer", "push_in"),
    ("pull back", "pull_back"), ("pull away", "pull_back"),
    ("orbit", "orbit"), ("circle around", "orbit"), ("circle the", "orbit"),
)
ZOOM_FACTOR = 2.0
DOLLY_FACTOR = 2.0
ORBIT_SEGMENTS = 32
OFFSET_PRESETS = ("chase", "wingman")


def camera_questions(prompt: str) -> List[Dict[str, Any]]:
    """The regex path's clarifying question, or []: asked exactly when
    the prompt speaks of imagery and names no view."""
    text = " ".join(prompt.lower().split())
    if _view_mentions(text):
        return []
    if not any(_search(rf"\b{word}\b", text) for word in IMAGERY_WORDS):
        return []
    return [{"id": CAMERA_QUESTION_ID,
             "question": "Which point of view should the camera take?",
             "options": list(CAMERA_VIEW_OPTIONS)}]


def _view_mentions(text: str) -> List[Tuple[str, str]]:
    """(phrase, preset) for every view named, in sentence order, each
    preset once."""
    found = []
    for phrase, name in CAMERA_VIEW_WORDS:
        m = _search(rf"\b{phrase}s?\b", text)       # "tower views" too
        if m:
            found.append((m.start(), phrase, name))
    found.sort()
    out: List[Tuple[str, str]] = []
    seen = set()
    for _, phrase, name in found:
        if name not in seen:
            seen.add(name)
            out.append((phrase, name))
    return out


def _answered_view(answers) -> Optional[Tuple[str, str]]:
    """The view a camera_view answer names, or None."""
    for answer in answers or []:
        if str(answer.get("id")) != CAMERA_QUESTION_ID:
            continue
        text = " ".join(str(answer.get("answer", "")).lower().split())
        mentions = _view_mentions(text)
        if mentions:
            return mentions[0]
        for name in CAMERA_VIEW_OPTIONS:
            if name in text:
                return (name, name)
    return None


def move_keyframes(kind: str, camera, duration_s: float) -> Optional[List[Dict]]:
    """The keyframes one move word means for one camera, or None when
    that camera cannot make the move (no offset to push, pull or
    orbit)."""
    focal = float(camera.focal_length_mm.value)
    preset = str(camera.preset.value)
    if kind == "zoom_in":
        return [{"t_s": 0.0, "focal_length_mm": focal},
                {"t_s": duration_s, "focal_length_mm": focal * ZOOM_FACTOR}]
    if kind == "zoom_out":
        return [{"t_s": 0.0, "focal_length_mm": focal},
                {"t_s": duration_s, "focal_length_mm": focal / ZOOM_FACTOR}]
    if preset not in OFFSET_PRESETS:
        return None
    f = float(camera.offset_forward_m.value)
    r = float(camera.offset_right_m.value)
    u = float(camera.offset_up_m.value)
    if kind in ("push_in", "pull_back"):
        scale = (1.0 / DOLLY_FACTOR) if kind == "push_in" else DOLLY_FACTOR
        return [{"t_s": 0.0, "offset_forward_m": f, "offset_right_m": r,
                 "offset_up_m": u},
                {"t_s": duration_s, "offset_forward_m": f * scale,
                 "offset_right_m": r * scale, "offset_up_m": u * scale}]
    if kind == "orbit":
        import math

        frames = []
        for k in range(ORBIT_SEGMENTS + 1):
            a = 2.0 * math.pi * k / ORBIT_SEGMENTS
            frames.append({
                "t_s": duration_s * k / ORBIT_SEGMENTS,
                "offset_forward_m": round(f * math.cos(a) - r * math.sin(a), 6),
                "offset_right_m": round(f * math.sin(a) + r * math.cos(a), 6),
            })
        return frames
    raise ValueError(f"unknown move kind {kind!r}")


def _cameras(text: str, aircraft: str, terrain_elevation_m: float,
             duration_s: float, answers=None):
    """Every camera the prompt (and a camera_view answer) speaks of, and
    the notes about what could not be expressed.

    A named view, an image count ("50 images/frames/stills"), a lens
    word or a move phrase each earns a camera; everything unstated
    keeps the documented defaults (source ``default``, plannable). The
    count, the lens and the moves apply to EVERY camera named. Ids are
    the preset names, exactly as the page's picker names its views.
    """
    from ..scenario.camera import CameraSpec, plan_full_capture

    notes: List[str] = []
    mentions = _view_mentions(text)
    answered = _answered_view(answers)
    if not mentions and answered is not None:
        mentions = [answered]
    count = _search(rf"(\d+)\s*(?:images|frames|stills|photos|pictures|"
                    rf"snapshots)\b", text)
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
    moves: List[Tuple[str, str]] = []
    for phrase, kind in MOVE_WORDS:
        if _search(rf"\b{phrase}\b", text) and kind not in [k for _, k in moves]:
            moves.append((phrase, kind))
    imagery = any(_search(rf"\b{word}\b", text) for word in IMAGERY_WORDS)
    if not mentions and count is None and focal_quantity is None \
            and not moves and not imagery:
        return [], notes
    if not mentions:
        # Imagery, a count, a lens or a move with no view: the documented
        # default view, and the question (camera_questions) asks which.
        mentions = [(None, "chase")]
    cameras = []
    for phrase, preset in mentions:
        camera = CameraSpec.defaulted(
            camera_id=preset, preset=preset, aircraft=aircraft,
            terrain_elevation_m=terrain_elevation_m,
            frm="camera language in the prompt; documented camera default")
        if phrase is not None:
            camera.preset = Quantity(value=preset, source="inferred",
                                     frm=phrase)
        if count is not None:
            camera.capture_count = Quantity(
                value=int(count.group(1)), unit="dimensionless",
                source="user", frm=count.group(0).strip())
        else:
            # No number in the prompt, so nothing to honour exactly: a
            # view named in words means the whole flight from that view,
            # at the rate it was recorded -- the same thing the page's
            # picker gives.
            plan_full_capture(camera, frm="a view named in the prompt with "
                                          "no count captures the whole clip")
        if focal_quantity is not None:
            camera.focal_length_mm = focal_quantity
        for phrase_m, kind in moves:
            keyframes = move_keyframes(kind, camera, duration_s)
            if keyframes is None:
                notes.append(
                    f"ignored move {phrase_m!r} for the {preset} view: only "
                    f"the chase and wingman views carry an offset to push, "
                    f"pull or orbit")
                continue
            camera.moves = _merge_moves(camera.moves, keyframes)
            notes.append(f"move {phrase_m!r} -> {kind} keyframes over "
                         f"{duration_s:g} s on the {preset} view")
        cameras.append(camera)
    return cameras, notes


def _merge_moves(existing: List[Dict], added: List[Dict]) -> List[Dict]:
    """Keyframes of two moves on one camera, merged by time: a zoom and
    an orbit together are one keyframe list carrying both fields."""
    by_t: Dict[float, Dict] = {}
    for frame in list(existing) + list(added):
        entry = by_t.setdefault(float(frame["t_s"]), {"t_s": float(frame["t_s"])})
        for key, value in frame.items():
            if key != "t_s":
                entry[key] = value
    return [by_t[t] for t in sorted(by_t)]


def rescale_moves(spec, old_duration_s: float, new_duration_s: float) -> int:
    """A move phrase spans the whole flight; when the flight's duration
    is edited (the page's clip selector) every camera whose keyframes
    ended at the OLD duration is rescaled to end at the new one. Returns
    how many cameras moved. Keyframes ending elsewhere are someone's
    stated times and are left alone."""
    if old_duration_s <= 0 or new_duration_s <= 0:
        return 0
    factor = new_duration_s / old_duration_s
    moved = 0
    for camera in spec.cameras:
        if not camera.moves:
            continue
        last = max(float(m["t_s"]) for m in camera.moves)
        if abs(last - old_duration_s) > 1e-9:
            continue
        camera.moves = [{**m, "t_s": round(float(m["t_s"]) * factor, 9)}
                        for m in camera.moves]
        moved += 1
    return moved


# -- the compiler --------------------------------------------------------

#: Words that describe a shot rather than a condition. Recognised only so they
#: can be reported as ignored -- §8 is explicit that the cinematic vocabulary
#: must not be the primary plugin surface, because a parser can only request
#: what its vocabulary can express. "camera" and "chase" left this list
#: when the camera vocabulary above learned to express them (Camera
#: Phase 1); genuinely unexpressible shot language stays reported.
CINEMATIC_WORDS = (
    "flyby", "fly-by", "cinematic", "dogfight", "airshow", "aerobatic",
    "dramatic", "epic",
    # a pan is an aim move; every preset aims at the aircraft, so there
    # is nothing for it to express -- reported, never guessed.
    "pan left", "pan right", "tilt up", "tilt down",
)


def compile_prompt(prompt: str, name: Optional[str] = None,
                   answers=None) -> ScenarioSpec:
    """Turn a prompt into a spec. Does not run anything. ``answers``
    is the page's answer round ([{id, answer}]); the regex path has
    exactly one question it can answer, camera_view."""
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

    cameras, camera_notes = _cameras(
        text, str(spec.aircraft.value), float(spec.terrain_elevation.value),
        float(spec.duration.value), answers=answers)
    if cameras:
        spec.cameras = cameras
    spec.notes.extend(camera_notes)

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
