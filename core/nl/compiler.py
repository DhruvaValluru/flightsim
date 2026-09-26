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

Randomisation phrases (spec 8, contracts §5.3) are the one exception to
"reported in notes": a sentence that asks to VARY something the
vocabulary cannot vary is recorded on the policy (``unmapped``) and the
sampler refuses it by name, ``randomization.vocabulary``, quoting the
sentence -- on every surface that samples (the page's verdict, /run, the
capture command, a batch). ``RANDOMIZATION_WORDS`` is the table.
"""

from __future__ import annotations

import json
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

#: The regex path's aircraft question (asked beside the camera one, see
#: :func:`camera_questions`): the options are plain names, each a phrase
#: AIRCRAFT_WORDS maps, so a chosen option compiles through the same
#: vocabulary as the prompt.
AIRCRAFT_QUESTION_ID = "aircraft"
AIRCRAFT_QUESTION = "Which aircraft should fly?"
AIRCRAFT_OPTIONS: Tuple[str, ...] = (
    "Boeing 747", "Airbus A320", "Cessna 172", "Boeing 737", "Global 5000",
    "F-16", "F-15",
)

#: Words that name a KIND of aircraft, not a type ("a small plane",
#: "airliners"): the question is asked and, meanwhile, the documented
#: default flies -- it is a member of the kind, the way the default
#: chase view is a view. A SPECIFIC name the vocabulary lacks ("the
#: dragon", "a Pilatus PC-12") is the person speaking: it is carried as
#: stated and refused by name (``aircraft.exists``), never replaced.
AIRCRAFT_CLASS_WORDS: Tuple[str, ...] = (
    "plane", "planes", "aircraft", "airplane", "airplanes", "aeroplane",
    "aeroplanes", "airliner", "airliners", "jet", "jets", "jetliner",
    "jetliners", "transport", "transports", "fighter", "fighters",
)

#: Words a flight or imagery verb may be followed by that are NOT the
#: thing flown: no subject is named, the documented default applies and
#: nothing is asked (exactly today's behaviour for "fly at 6000 m").
_NOT_A_SUBJECT = frozenset("""
at over above across through into in on from with for along around under
below toward towards up down out low high fast slow slowly quickly north
south east west heading straight level it them this that these those same
again then and or to by of off the a an my our your some one two
mountain mountains ridge ridges terrain valley canyon peak peaks hill hills
ground sea ocean desert forest city coast coastline river lake island
tornado twister storm thunderstorm cloud clouds rain snow fog weather wind
winds crosswind headwind tailwind sunrise sunset dawn dusk night day
morning evening noon sun moon sky horizon
chase wingman tower cockpit camera cameras view views image images photo
photos picture pictures footage film video frames stills snapshot
snapshots capture render shot shots scene scenes flight flights approach
landing takeoff climb descent cruise
yosemite matterhorn fuji everest alps rockies himalayas kansas
""".split())
_SUBJECT_VERBS = (r"(?:fly|flying|flies|chase|chasing|follow|following|"
                  r"track|tracking|film|filming|photograph|photographing|"
                  r"render|rendering|simulate|simulating|land|landing)")
_SUBJECT_OF = (r"(?:images?|photos?|photographs?|pictures?|stills|frames|"
               r"footage|video|shots?|snapshots?|captures?|renders?|"
               r"dataset|views?|camera)\s+of")
_SUBJECT_PHRASE = re.compile(
    rf"\b(?:{_SUBJECT_VERBS}|{_SUBJECT_OF})\s+"
    r"(?:(?:the|a|an|my|our|some|this|that)\s+)?"
    r"([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*))?", re.IGNORECASE)


def _search(pattern: str, text: str) -> Optional[re.Match]:
    return re.search(pattern, text, flags=re.IGNORECASE)


# -- individual extractors ----------------------------------------------


def _named_subject(text: str) -> Optional[Tuple[str, bool]]:
    """``(phrase, is_class_word)`` for the thing a flight or imagery
    verb names when no AIRCRAFT_WORDS phrase matched, or None when the
    slot after the verb is empty (a preposition, a place, a number)."""
    for phrase, _ in AIRCRAFT_WORDS:
        if phrase in text:
            return None
    for m in _SUBJECT_PHRASE.finditer(text):
        first, second = m.group(1), m.group(2)
        if first in _NOT_A_SUBJECT or first[0].isdigit():
            continue
        if first in AIRCRAFT_CLASS_WORDS:
            return first, True
        if second in AIRCRAFT_CLASS_WORDS:
            return f"{first} {second}", True
        if second and second not in _NOT_A_SUBJECT \
                and not second[0].isdigit():
            return f"{first} {second}", False
        return first, False
    return None


def aircraft_question(text: str) -> Optional[Dict[str, Any]]:
    """The aircraft question, when the prompt names a kind of aircraft
    or a name the vocabulary lacks; None when it names a known type or
    no aircraft at all."""
    if _named_subject(" ".join(text.lower().split())) is None:
        return None
    return {"id": AIRCRAFT_QUESTION_ID, "question": AIRCRAFT_QUESTION,
            "options": list(AIRCRAFT_OPTIONS)}


def _answered_aircraft(answers) -> Optional[Quantity]:
    """The aircraft an ``aircraft`` answer names (source ``user``, the
    question and answer recorded), or None when nothing answered it.
    An answer the vocabulary cannot map is still the person speaking:
    it is carried as stated and refused by name, never defaulted."""
    for answer in answers or []:
        if str(answer.get("id")) != AIRCRAFT_QUESTION_ID:
            continue
        text = " ".join(str(answer.get("answer", "")).lower().split())
        if not text:
            continue
        frm = f'answer to "{AIRCRAFT_QUESTION}": "{answer.get("answer")}"'
        for phrase, model in AIRCRAFT_WORDS:
            if phrase in text:
                return Quantity.user(model, frm=frm)
        for model in dict((m, None) for _, m in AIRCRAFT_WORDS):
            if model.lower() == text:
                return Quantity.user(model, frm=frm)
        return Quantity.user(text, frm=frm)
    return None


def _aircraft(text: str, answers=None) -> Quantity:
    for phrase, model in AIRCRAFT_WORDS:
        if phrase in text:
            return Quantity.user(model, frm=phrase)
    answered = _answered_aircraft(answers)
    if answered is not None:
        return answered
    subject = _named_subject(text)
    if subject is not None and not subject[1]:
        # A name the vocabulary lacks is stated, not guessed around:
        # validate() refuses it as aircraft.exists, by name.
        return Quantity.user(subject[0], frm=subject[0])
    return Quantity.default("B747", frm="widest measured trim envelope of the "
                                        "candidate transports")


def _other_airframes(text: str, primary: str) -> List[str]:
    """Aircraft phrases naming a model other than the primary, in the
    text with the traffic clauses removed: a second aircraft the
    compiler could not place."""
    out: List[str] = []
    seen = {primary}
    for phrase, model in AIRCRAFT_WORDS:
        if model not in seen and _search(rf"\b{re.escape(phrase)}\b", text):
            seen.add(model)
            out.append(phrase)
    return out


# -- traffic (spec 8, contracts §2.2): the scripted second aircraft ------

#: Track words -> the TRAFFIC_TRACKS kind (core.scenario.blocks).
TRAFFIC_TRACK_WORDS: Tuple[Tuple[str, str], ...] = (
    ("in formation", "formation"), ("formation", "formation"),
    ("alongside", "formation"),
    ("crossing", "crossing"), ("crosses", "crossing"),
    ("overtaking", "overtaking"), ("overtakes", "overtaking"),
    ("passing", "overtaking"),
)
_AIRCRAFT_ALT = "|".join(re.escape(p) for p, _ in
                         sorted(AIRCRAFT_WORDS, key=lambda e: -len(e[0])))
_TRACK_ALT = "|".join(re.escape(p) for p, _ in
                      sorted(TRAFFIC_TRACK_WORDS, key=lambda e: -len(e[0])))
#: "with an A320 crossing 400 m ahead", "and a 737 in formation": a
#: lead-in word, an airframe the vocabulary knows, a track word, an
#: optional range. The lead-in is required so "the 747 crossing the
#: alps" stays the primary's own flight.
TRAFFIC_PHRASE = re.compile(
    rf"\b(?:with|and|plus)\s+(?:(?:an?|the|another|one|a second)\s+)?"
    rf"(?P<aircraft>{_AIRCRAFT_ALT})\s+(?:(?:traffic|aircraft)\s+)?"
    rf"(?P<track>{_TRACK_ALT})\b"
    rf"(?:\s+(?:at|from|about|some|roughly)?\s*(?P<range>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>km|m|metres?|meters?)\b"
    r"(?:\s+(?:ahead|away|off|out|behind|abeam|to the side|in front))?)?",
    re.IGNORECASE)


def _traffic(text: str):
    """(traffic entries, the text with their clauses removed). Every
    field a clause states is ``user`` with the phrase; the rest are the
    documented traffic defaults. More entries than the contract allows
    are all recorded and refused by name (``traffic.count``), never
    silently dropped."""
    from ..scenario.blocks import TrafficSpec

    entries = []
    for m in TRAFFIC_PHRASE.finditer(text):
        model = dict(AIRCRAFT_WORDS)[m.group("aircraft").lower()]
        track = dict(TRAFFIC_TRACK_WORDS)[m.group("track").lower()]
        clause = m.group(0).strip()
        entry = TrafficSpec.defaulted(model, track=track)
        entry.aircraft = Quantity.user(model, frm=clause)
        entry.track = Quantity.user(track, frm=m.group("track"))
        if m.group("range"):
            metres = float(m.group("range"))
            if m.group("unit").lower() == "km":
                metres *= 1000.0
            entry.range_m = Quantity.user(
                metres, "m", frm=f"{m.group('range')} {m.group('unit')}")
        entries.append(entry)
    return entries, TRAFFIC_PHRASE.sub(" ", text)


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
    # Minutes are spelled out: a bare "m" is metres everywhere else in
    # this vocabulary, and "over 2000 m terrain" once compiled to a
    # 2000-minute flight (a user-stated field that was wrong, which the
    # provenance rules can never catch).
    m = _search(rf"(?:for|during|over)\s+{NUMBER}\s*(?:min|mins|minute|minutes)\b", text)
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
    ("tower camera", "tower"),
    ("ground camera", "ground"),
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
    """The regex path's clarifying questions, or []: the aircraft when
    the prompt names a kind of aircraft or a name the vocabulary lacks
    (:func:`aircraft_question`), and the view when the prompt speaks of
    imagery and names no view. Each is asked once; the answer round
    compiles with the answers and asks nothing."""
    text = " ".join(prompt.lower().split())
    questions: List[Dict[str, Any]] = []
    asked = aircraft_question(text)
    if asked is not None:
        questions.append(asked)
    if _view_mentions(text):
        return questions
    if not any(_search(rf"\b{word}\b", text) for word in IMAGERY_WORDS):
        return questions
    questions.append({"id": CAMERA_QUESTION_ID,
                      "question": "Which point of view should the camera take?",
                      "options": list(CAMERA_VIEW_OPTIONS)})
    return questions


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


# -- randomisation (spec 8, package F; contracts §5.3) ---------------------

#: The documented policy each phrase family writes (contracts §5.2
#: numbers). Keyed by family; RANDOMIZATION_WORDS maps phrases to
#: families. Every leaf here is one core.scenario.randomization
#: POLICY_LEAVES entry (asserted at import).
RANDOMIZATION_FAMILIES: Dict[str, Dict[str, Any]] = {
    "weather": {
        "cloud_cover": {"beta": [2, 2]},
        "visibility_km": {"lognormal": {"median": 25, "sigma": 0.6},
                          "clip": [1, 80]},
        "precipitation": {"choice": ["none", "rain", "snow"],
                          "weights": [7, 2, 1], "gated_by": "cloud_cover > 0.6"},
    },
    "times_of_day": {
        "hour_local": {"uniform": [5.5, 20.0]},
    },
    "dawn_dusk": {
        "hour_local": {"choice": ["dawn", "dusk"]},
    },
    "lighting": {
        "hour_local": {"uniform": [5.5, 20.0]},
        "weather_date": {"uniform_dates": ["2024-01-01", "2024-12-31"]},
    },
    "traffic": {
        "traffic_count": {"poisson": 0.7, "max": 2},
    },
    "viewpoints": {
        "cameras": {
            "preset": {"choice": ["chase", "tower", "wingman", "ground"]},
            "focal_length_mm": {"loguniform": [24, 400]},
            "offset_jitter_m": {"normal": {"sigma": 5}},
        },
    },
}

#: Words that mean "vary": a sentence carrying one that no family below
#: matched is refused by name. "different" and "mixed" alone are NOT
#: intent words (too common in ordinary prompts); they count only inside
#: the phrases below.
VARIATION_INTENT = (r"\b(?:vary|varied|varying|variety|random|randomly|"
                    r"randomi[sz]ed?|assorted|various)\b")
_VARY = (r"(?:varied|varying|variable|random|randomi[sz]ed|mixed|different|"
         r"assorted|various|a (?:range|variety|mix) of)")

#: Phrase (regex over the lowercased prompt) -> family. Longer phrases
#: first; every match is removed from the text before the intent scan.
#: Location ranges are their own family: "across the Rockies" -> a
#: location choice restricted to that range (refused by name by the
#: sampler until a bake in the range exists).
RANDOMIZATION_WORDS: Tuple[Tuple[str, str], ...] = (
    (rf"{_VARY} weather(?: conditions)?", "weather"),
    (r"weather (?:that )?varies", "weather"),
    (r"dawn (?:and|or) dusk(?: only)?", "dawn_dusk"),
    (r"(?:at )?sunrise (?:and|or) sunset(?: only)?", "dawn_dusk"),
    (rf"{_VARY} light(?:ing)?(?: conditions)?", "lighting"),
    (r"light(?:ing)? (?:that )?varies", "lighting"),
    (rf"{_VARY} times? of (?:the )?day", "times_of_day"),
    (rf"{_VARY} hours(?: of the day)?", "times_of_day"),
    (r"(?:at )?all hours(?: of the day)?", "times_of_day"),
    (r"any time of (?:the )?day", "times_of_day"),
    (r"throughout the day", "times_of_day"),
    (rf"{_VARY} (?:viewpoints?|views?|perspectives?|angles|"
     rf"camera (?:angles?|positions?|placements?|views?))", "viewpoints"),
    (rf"{_VARY} traffic", "traffic"),
    (r"(?:other|background|some|with) traffic", "traffic"),
)
#: The nouns the phrase table can vary, for a conjunction: "varied
#: weather and lighting" is every noun varied, not the first. An item
#: the table cannot vary is reported in a note (see _dangling_items),
#: never silently dropped.
_FAMILY_NOUN = (r"(?:weather(?: conditions)?|light(?:ing)?(?: conditions)?|"
                r"times? of (?:the )?day|hours(?: of the day)?|"
                r"viewpoints?|views?|perspectives?|angles|"
                r"camera (?:angles?|positions?|placements?|views?)|traffic)")
_CONJUNCTION = re.compile(
    rf"\b({_VARY})\s+({_FAMILY_NOUN})\s*(?:,|,?\s*and|,?\s*or)\s+"
    rf"(?={_FAMILY_NOUN}\b)", re.IGNORECASE)
_DANGLING = re.compile(
    rf"\b(?:{_VARY})\s+{_FAMILY_NOUN}\s*(?:,|,?\s*and|,?\s*or)\s+"
    rf"(?!(?:{_VARY})\b)([a-z][a-z-]*)", re.IGNORECASE)


def _expand_conjunctions(text: str) -> str:
    """'varied weather and lighting' -> 'varied weather varied lighting'
    (and on through a list), so each noun meets the phrase table."""
    previous = None
    while previous != text:
        previous = text
        text = _CONJUNCTION.sub(lambda m: f"{m.group(1)} {m.group(2)} "
                                          f"{m.group(1)} ", text)
    return text


#: Words after "varied weather and ..." that do not name a thing to
#: vary: the list has ended and the sentence moved on.
_NOT_A_VARIED_ITEM = frozenset("""
the a an some more then also at over above across through into in on
from with for along around under below toward towards up down out to by
of off it them this that these those
chase wingman tower cockpit ground camera cameras view views image images
photo photos picture pictures footage film video frames stills snapshot
snapshots capture render shot shots
""".split())


def _dangling_items(text: str) -> List[Tuple[str, str]]:
    """(phrase, item) for every 'varied <noun> and <item>' whose item
    the table cannot vary and which is not a view, an article or a
    preposition -- the request the compiler read and could not honour."""
    out = []
    for m in _DANGLING.finditer(text):
        item = m.group(1).lower()
        if item in _NOT_A_VARIED_ITEM or re.fullmatch(_FAMILY_NOUN, item):
            continue
        out.append((m.group(0).strip(), item))
    return out


#: Range words -> the LOCATION_RANGES key (core.scenario.randomization).
LOCATION_RANGE_WORDS: Tuple[Tuple[str, str], ...] = (
    ("rocky mountains", "rockies"), ("rockies", "rockies"),
    ("swiss alps", "alps"), ("the alps", "alps"),
    ("cascades", "cascades"), ("cascade range", "cascades"),
    ("sierra nevada", "sierra_nevada"), ("the sierras", "sierra_nevada"),
    ("himalayas", "himalayas"), ("himalaya", "himalayas"),
    ("colorado plateau", "colorado_plateau"),
    ("great plains", "great_plains"),
)
_RANGE_PHRASE = r"(?:across|over|above|through|around|along) (?:the )?({words})"

#: What each family's leaves need to be UNSTATED for the family to
#: apply: a leaf whose target the prompt already states is dropped with
#: a note, never sampled over a stated value.
_FAMILY_TARGETS = {
    "weather_date": ("weather_date",),
    "hour_local": (),
    "location": ("latitude", "longitude"),
}


def _sentences(prompt: str) -> List[str]:
    return [s.strip() for s in re.split(r"[.;!?\n]+", prompt) if s.strip()]


def _randomization(text: str, prompt: str, spec) -> Tuple[Dict[str, Any],
                                                          Dict[str, str],
                                                          List[str], List[str]]:
    """(policy, attribution, unmapped sentences, notes) for the prompt.

    Deterministic: every family matched writes its documented leaves,
    attributed to the quoted phrase (``attribution[leaf] = phrase``); a
    sentence with variation intent and no family is returned unmapped
    (the sampler refuses it by name). A leaf whose target field the
    prompt already states is dropped with a note.
    """
    policy: Dict[str, Any] = {}
    attribution: Dict[str, str] = {}
    notes: List[str] = []
    for phrase, item in _dangling_items(text):
        notes.append(
            f"randomization: {phrase!r} -- the vocabulary cannot vary "
            f"{item!r}, so it is not varied; only the rest of the phrase "
            f"is")
    consumed = _expand_conjunctions(text)
    matched: List[Tuple[int, str, str]] = []
    for pattern, family in RANDOMIZATION_WORDS:
        for m in re.finditer(pattern, consumed, flags=re.IGNORECASE):
            matched.append((m.start(), m.group(0).strip(), family))
        consumed = re.sub(pattern, " ", consumed, flags=re.IGNORECASE)
    words = "|".join(re.escape(w) for w, _ in LOCATION_RANGE_WORDS)
    for m in re.finditer(_RANGE_PHRASE.format(words=words), consumed,
                         flags=re.IGNORECASE):
        key = dict(LOCATION_RANGE_WORDS)[m.group(1).lower()]
        matched.append((m.start(), m.group(0).strip(), f"location:{key}"))
    consumed = re.sub(_RANGE_PHRASE.format(words=words), " ", consumed,
                      flags=re.IGNORECASE)
    matched.sort()
    for _, phrase, family in matched:
        if family.startswith("location:"):
            leaves: Dict[str, Any] = {
                "location": {"choice": [family.split(":", 1)[1]]}}
        else:
            leaves = RANDOMIZATION_FAMILIES[family]
        for leaf, distribution in leaves.items():
            stated = [f for f in _FAMILY_TARGETS.get(leaf, ())
                      if getattr(spec, f).source in ("user", "inferred")]
            if stated:
                notes.append(
                    f"randomization: {phrase!r} would vary {leaf}, but "
                    f"{', '.join(stated)} is stated in the prompt; not varied")
                continue
            if leaf in policy and policy[leaf] != distribution:
                notes.append(
                    f"randomization: {phrase!r} names {leaf} a second way; "
                    f"the first phrase ({attribution[leaf]!r}) stands")
                continue
            policy[leaf] = json.loads(json.dumps(distribution))
            attribution.setdefault(leaf, phrase)
    unmapped: List[str] = []
    if re.search(VARIATION_INTENT, consumed, flags=re.IGNORECASE):
        # Quote the ORIGINAL sentence(s) carrying the leftover intent.
        leftover = [s for s in _sentences(consumed)
                    if re.search(VARIATION_INTENT, s, flags=re.IGNORECASE)]
        for sentence in _sentences(prompt):
            probe = _expand_conjunctions(sentence.lower())
            for pattern, _ in RANDOMIZATION_WORDS:
                probe = re.sub(pattern, " ", probe, flags=re.IGNORECASE)
            probe = re.sub(_RANGE_PHRASE.format(words=words), " ", probe,
                           flags=re.IGNORECASE)
            if re.search(VARIATION_INTENT, probe, flags=re.IGNORECASE):
                unmapped.append(sentence)
        if not unmapped:
            unmapped = leftover
    return policy, attribution, unmapped, notes


def apply_randomization_phrases(spec, prompt: str) -> None:
    """Write the prompt's randomisation phrases onto ``spec``: the
    policy (inferred, attributed per leaf), the block switched on by
    the first phrase, one default camera when viewpoints are to vary
    and none was named, and the unmapped sentences the sampler refuses
    by name. A prompt with no variation language changes nothing."""
    from ..scenario.randomization import enable_for_policy

    text = " ".join(prompt.lower().split())
    policy, attribution, unmapped, notes = _randomization(text, prompt, spec)
    spec.notes.extend(notes)
    if not policy and not unmapped:
        return
    phrases = list(dict.fromkeys(attribution.values()))
    detail: Dict[str, Any] = {"attribution": dict(attribution)}
    if unmapped:
        detail["unmapped"] = list(unmapped)
    spec.randomization_policy = Quantity.inferred(
        policy, frm="; ".join(phrases) if phrases else "variation asked for "
                                                        "in words the "
                                                        "vocabulary lacks",
        **detail)
    if policy:
        enable_for_policy(spec, frm=f"{phrases[0]}: the randomisation "
                                    f"block is on")
    if "cameras" in policy and not spec.cameras:
        from ..scenario.camera import CameraSpec, plan_full_capture

        camera = CameraSpec.defaulted(
            camera_id="chase", preset="chase", aircraft=str(spec.aircraft.value),
            terrain_elevation_m=float(spec.terrain_elevation.value),
            frm=f"{attribution['cameras']!r}: one documented default camera "
                f"for the viewpoint policy to vary")
        plan_full_capture(camera, frm="a viewpoint policy with no count "
                                      "captures the whole clip")
        spec.cameras = [camera]


def _assert_families_are_leaves() -> None:
    """Import-time guard: every family leaf is a policy leaf the sampler
    knows (the table is the control, not a second vocabulary)."""
    from ..scenario.randomization import POLICY_CAMERA_LEAVES, POLICY_LEAVES

    for family, leaves in RANDOMIZATION_FAMILIES.items():
        for leaf, distribution in leaves.items():
            if leaf == "cameras":
                unknown = set(distribution) - set(POLICY_CAMERA_LEAVES)
            else:
                unknown = set() if leaf in POLICY_LEAVES else {leaf}
            assert not unknown, (f"RANDOMIZATION_FAMILIES[{family!r}] names "
                                 f"leaves the sampler lacks: {sorted(unknown)}")


_assert_families_are_leaves()


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
    two questions it can answer, aircraft and camera_view
    (:func:`camera_questions`)."""
    text = " ".join(prompt.lower().split())
    # The second aircraft's clause leaves the text first: its airframe
    # is not the primary and its range is not an altitude.
    traffic, text = _traffic(text)
    aircraft = _aircraft(text, answers)
    model = str(aircraft.value)

    heading = _heading(text)
    airspeed, airspeed_kind = _airspeed(text)
    if airspeed is None:
        airspeed = Quantity.default(
            CRUISE_DEFAULT_KT.get(model, 250.0), "kt",
            frm=f"typical cruise for the {model}")
        airspeed_kind = Quantity.default("cas")
    wind_speed, wind_direction = _wind(text, float(heading.value))

    spec = ScenarioSpec(
        name=name or _name_from(text),
        prompt=prompt,
        aircraft=aircraft,
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

    if traffic:
        spec.traffic = traffic
    for phrase in _other_airframes(text, model):
        spec.notes.append(
            f"a second aircraft {phrase!r} is named but not as traffic, so "
            f"it is not in the scene; say 'with the {phrase} crossing', "
            f"'in formation' or 'overtaking' to fly it as a scripted "
            f"second aircraft")

    cameras, camera_notes = _cameras(
        text, str(spec.aircraft.value), float(spec.terrain_elevation.value),
        float(spec.duration.value), answers=answers)
    if cameras:
        spec.cameras = cameras
    spec.notes.extend(camera_notes)

    # Spec 8: the randomisation phrases, after the cameras exist (a
    # viewpoint policy varies the cameras the prompt named).
    apply_randomization_phrases(spec, prompt)

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
