"""Camera placement from a sentence: "behind and above both planes, about 300 m back".

The page lets a user describe where the camera should be instead of
picking a preset. A language model (or, when none is reachable, the
rule parser below) turns the sentence into a small, schema-checked
*intent*: which kind of view, an offset in metres from the main
aircraft's own heading frame, and optionally a lens, an aim and the
camera's moves over the clip. Nothing the model says is evidence of
geometry: the intent is only ever the user's own phrase read as numbers,
and the geometry that decides whether every aircraft is in view is
computed here, deterministically, from the spec (:func:`fit_all_in_view`).

What this does and does not do:

* The camera is a ``chase`` view (it follows the main aircraft; the
  offset is forward / right / up in that aircraft's heading frame), the
  ``cockpit`` view, or the world-anchored ``ground`` / ``tower`` presets
  the sentence names.
* The model is told the scene it is placing a camera in: the aircraft,
  its heading, speed and clip length, the other aircraft, every camera
  already in the spec, and a distance table SCALED TO THE AIRCRAFT
  (:func:`framing_distances`), so "close behind" a Cessna and "close
  behind" a 747 are different distances, and "a bit closer" can name an
  existing camera (``edit_camera_id``) and give its new numbers.
* ``anchor: "centre"`` measures the offset from the middle of all the
  aircraft instead of from the main one, so "above both planes" is above
  both.
* A lens ("telephoto", "35 mm"), an aim ("looking north", "looking down
  at the ground": a fixed bearing and elevation instead of the aircraft)
  and moves (zoom in / out, push in, pull back, orbit -- the regex
  compiler's own keyframe shapes) are optional; an omitted one keeps the
  camera's current value.
* The fit check places every aircraft at the start, middle and end of the
  clip, works out the angle from the camera's axis, and widens the lens
  (down to :data:`MIN_FOCAL_MM`) and then pulls the camera back until all
  of them are inside the frame with a margin. A lens the sentence stated
  is never widened; the camera is pulled back instead. It reports what
  it did, and says so when it hit :data:`MAX_BACK_M` and could not fit
  them all. It models the aircraft as points plus a size margin and the
  main aircraft's airspeed as its ground speed; the camera's follow lag
  is ignored. A camera aimed away from the aircraft is not fitted.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .compiler import MOVE_KINDS, prompt_moves

#: The views a sentence may ask for, and the preset each one builds.
VIEWS = ("follow", "ground", "tower", "cockpit")
VIEW_PRESETS = {"follow": "chase", "ground": "ground", "tower": "tower",
                "cockpit": "cockpit"}
ANCHORS = ("primary", "centre")
#: What the camera looks at: the main aircraft (the default), or a fixed
#: compass bearing and elevation.
AIMS = ("aircraft", "bearing")

#: Widest lens the fit may use before it pulls the camera back instead.
MIN_FOCAL_MM = 18.0
#: How far back the fit may pull the camera, metres.
MAX_BACK_M = 6000.0
#: Margin on the frame (fraction of the half-angle kept clear) and the
#: aircraft's own size in metres (half a wingspan, generously).
FRAME_MARGIN = 0.85
AIRCRAFT_RADIUS_M = 20.0

#: Distance words as multiples of the aircraft's calibrated chase
#: distance (the per-airframe table in core.scenario.camera): the chase
#: view IS the documented "default" distance for that airframe.
DISTANCE_SCALE = {"close": 0.6, "default": 1.0, "far": 4.0, "very_far": 10.0}

#: The camera schedule fields an edit carries over from the camera it
#: replaces, so "move it closer" does not reset a stated image count.
SCHEDULE_FIELDS = ("trigger", "capture_count", "period_s", "distance_m",
                   "event_channel", "event_threshold", "event_direction",
                   "refractory_s")

INTENT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["view", "anchor", "forward_m", "right_m", "up_m",
                 "show_all", "quote", "note"],
    "properties": {
        "view": {"type": "string", "enum": list(VIEWS),
                 "description": "follow = a camera that follows the main "
                                "aircraft at an offset; ground = a fixed "
                                "observer on the ground; tower = a fixed "
                                "tower position; cockpit = over the "
                                "pilot's shoulder"},
        "anchor": {"type": "string", "enum": list(ANCHORS),
                   "description": "what the offset is measured from: the "
                                  "main aircraft, or the centre of all the "
                                  "aircraft in the scene"},
        "forward_m": {"type": "number",
                      "description": "metres ahead (+) or behind (-) along "
                                     "the main aircraft's heading"},
        "right_m": {"type": "number",
                    "description": "metres to the right (+) or left (-) of "
                                   "the main aircraft's heading"},
        "up_m": {"type": "number",
                 "description": "metres above (+) or below (-)"},
        "show_all": {"type": "boolean",
                     "description": "true when the sentence wants every "
                                    "aircraft in view (the default for a "
                                    "scene with more than one)"},
        "edit_camera_id": {"type": "string",
                           "description": "the id of an EXISTING camera the "
                                          "sentence changes; omit (or \"\") "
                                          "for a new camera"},
        "focal_length_mm": {"type": "number",
                            "description": "lens focal length in mm, only "
                                           "when the sentence asks for a lens"},
        "aim": {"type": "string", "enum": list(AIMS),
                "description": "aircraft = look at the main aircraft; "
                               "bearing = look along aim_bearing_deg / "
                               "aim_elevation_deg"},
        "aim_bearing_deg": {"type": "number",
                            "description": "compass bearing to look along, "
                                           "degrees true (0 north, 90 east)"},
        "aim_elevation_deg": {"type": "number",
                              "description": "degrees above (+) or below (-) "
                                             "the horizon"},
        "moves": {"type": "array",
                  "items": {"type": "string", "enum": list(MOVE_KINDS)},
                  "description": "the camera's moves over the clip; [] for "
                                 "none"},
        "quote": {"type": "string",
                  "description": "the words of the sentence this reads"},
        "note": {"type": "string",
                 "description": "one short sentence: what was understood, "
                                "and any distance the sentence left open "
                                "that a default filled"},
    },
}

SYSTEM_PROMPT = """\
You place a camera in a flight simulation from one sentence. The user
message starts with the SCENE (the aircraft, a distance table scaled to
it, and the cameras that already exist) and then the camera sentence.
Reply with JSON that matches the schema. Do not invent anything the
sentence does not say; where it leaves a distance open, take it from the
scene's distance table and say so in "note".

Coordinates: metres, in the MAIN aircraft's own heading frame. forward_m is
along its heading (negative = behind it), right_m is to its right (negative
= left), up_m is above it (negative = below).

Placement (distances come from the scene's table, never a fixed number):
- "behind", "chase", "trailing" -> forward_m = -default; up_m = the chase
  height unless the sentence says above or below.
- "in front", "ahead", "head-on" -> forward_m = +default.
- "left" / "right" side views -> right_m = -default / +default.
- "above", "overhead", "from the top", "bird's eye" alone -> up_m =
  default (a straight-down view is up_m large, forward_m and right_m 0);
  combined with another direction ("behind and above") -> up_m about
  half of default.
- "below", "underneath" -> negative up_m.
- Distance words: "close"/"tight" -> close, "far" -> far, "very far" ->
  very far. Numbers and units the sentence states always win: "300 m",
  "1 km" (1000 m), "500 ft" (152.4 m), "a mile" (1609 m).
- "from the ground", "from the runway" -> view "ground"; "from the tower"
  -> view "tower"; "cockpit", "pilot's view", "over the shoulder" ->
  view "cockpit"; every other camera is view "follow". Offsets only
  matter for "follow".

Which aircraft:
- "both planes", "all aircraft", "the pair", "the formation" -> anchor
  "centre" and show_all true. A sentence about only the main aircraft is
  anchor "primary"; show_all stays true unless it says ONLY the main
  one ("just the lead jet", "only the main plane").

Editing an existing camera:
- When the sentence changes a camera the scene lists ("closer", "a bit
  lower", "move the chase cam left", "zoom the tower view in", "make it
  wider"), set edit_camera_id to that camera's id and give the COMPLETE
  resulting numbers, starting from its listed values: "closer" ~0.6x the
  distance, "a bit closer" ~0.8x, "further"/"back off" ~1.6x, "a bit
  further" ~1.25x; "higher"/"lower" moves up_m by about the close
  distance. Keep its view unless the sentence changes it. With one
  camera listed, "it"/"the camera" means that one.
- A sentence describing a new viewpoint is a new camera: omit
  edit_camera_id.

Lens (focal_length_mm), only when the sentence asks for one, else omit:
- "ultra wide" 16, "wide"/"wide angle" 24, "normal" 35, "tight"/"close-up
  lens"/"telephoto"/"long lens" 85, "super telephoto" 200, "<n> mm" n.
  On an edit, "zoom in"/"tighter" as a STATIC change multiplies the
  listed lens by ~1.5, "wider" divides it by ~1.5.

Aim, only when the sentence points the camera somewhere other than the
aircraft, else omit (the camera looks at the main aircraft):
- "looking north/east/south/west" -> aim "bearing", aim_bearing_deg
  0/90/180/270; "looking ahead/forward" -> the main aircraft's heading
  from the scene; "looking back" -> heading + 180.
- aim_elevation_deg: "down at the ground" -90, "down" -30, "at the
  horizon" 0, "up at the sky" +30. Default 0.
- Never invent the bearing of an object the scene does not locate ("the
  mountain", "the city"): keep aim on the aircraft and say so in "note".

Moves over the clip ("moves"), only when the sentence asks the camera to
move, else omit:
- "zooms in" zoom_in, "zooms out" zoom_out, "pushes in"/"moves closer
  during" push_in, "pulls back"/"pulls away" pull_back, "orbits"/
  "circles around" orbit. Only follow cameras can push, pull or orbit;
  zoom works on every view.
- On an edit the scene lists the camera's current moves: "moves" is the
  COMPLETE list it should have afterwards (repeat the ones kept; [] to
  stop them). Omitting "moves" keeps them.
"""


@dataclass
class CameraIntent:
    """The sentence, read as numbers. ``None`` on an optional field means
    the sentence did not ask for it: the camera keeps its current value."""

    view: str = "follow"
    anchor: str = "primary"
    forward_m: float = -150.0
    right_m: float = 0.0
    up_m: float = 30.0
    show_all: bool = True
    quote: str = ""
    note: str = ""
    reader: str = "rules"           #: "llm" | "rules"
    model: Optional[str] = None
    edit_camera_id: Optional[str] = None
    focal_length_mm: Optional[float] = None
    aim: Optional[str] = None
    aim_bearing_deg: Optional[float] = None
    aim_elevation_deg: Optional[float] = None
    moves: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"view": self.view, "anchor": self.anchor,
                "forward_m": self.forward_m, "right_m": self.right_m,
                "up_m": self.up_m, "show_all": self.show_all,
                "edit_camera_id": self.edit_camera_id,
                "focal_length_mm": self.focal_length_mm,
                "aim": self.aim, "aim_bearing_deg": self.aim_bearing_deg,
                "aim_elevation_deg": self.aim_elevation_deg,
                "moves": self.moves,
                "quote": self.quote, "note": self.note,
                "reader": self.reader, "model": self.model}


class CameraPromptError(ValueError):
    """The sentence could not be read; the message says why."""


# -- the scene the reader is told about -------------------------------------

def chase_framing(aircraft: str) -> Tuple[float, float, float]:
    """The airframe's calibrated chase offset (forward, right, up): the
    table entry, or the length-scaled derivation for an unlisted one."""
    from ..scenario.camera import CHASE_OFFSETS, derive_chase_offset

    return tuple(CHASE_OFFSETS.get(aircraft) or derive_chase_offset(aircraft))


def framing_distances(aircraft: str) -> Dict[str, float]:
    """Distance words in metres for THIS airframe: multiples of its
    calibrated chase distance (:data:`DISTANCE_SCALE`), plus the chase
    view's own height (``chase_up``)."""
    forward, _, up = chase_framing(aircraft)
    base = abs(forward)
    out = {word: round(base * scale, 1) for word, scale in DISTANCE_SCALE.items()}
    out["chase_up"] = round(up, 1)
    return out


def _view_of(camera) -> str:
    preset = str(camera.preset.value)
    return {"chase": "follow", "wingman": "follow (wingman)"}.get(preset, preset)


def describe_camera(camera) -> str:
    """One line for the scene block: what the model can edit."""
    from .compiler import describe_moves

    aim = str(camera.aim_mode.value)
    if aim == "bearing":
        aim = (f"bearing {float(camera.aim_bearing_deg.value):g} deg, "
               f"elevation {float(camera.aim_elevation_deg.value):g} deg")
    moves = describe_moves(camera.moves) or ["none"]
    return (f"- {camera.camera_id.value}: view {_view_of(camera)}; offset "
            f"forward {float(camera.offset_forward_m.value):g} m, right "
            f"{float(camera.offset_right_m.value):g} m, up "
            f"{float(camera.offset_up_m.value):g} m; lens "
            f"{float(camera.focal_length_mm.value):g} mm; aim {aim}; moves "
            f"{', '.join(moves)}")


def scene_context(spec) -> str:
    """The SCENE block the model reads before the sentence."""
    from ..scenario.camera import _measured_mesh_length_m

    aircraft = str(spec.aircraft.value)
    d = framing_distances(aircraft)
    length = _measured_mesh_length_m(aircraft)
    lines = [
        "SCENE",
        f"Main aircraft: {aircraft}"
        + (f" ({length:.1f} m long)" if length else "")
        + f", heading {float(spec.heading.value):g} deg true, airspeed "
          f"{float(spec.airspeed.value):g} kt; the clip lasts "
          f"{float(spec.duration.value):g} s.",
        f"Distance table for this aircraft (metres): close {d['close']:g}, "
        f"default {d['default']:g}, far {d['far']:g}, very far "
        f"{d['very_far']:g}; chase height {d['chase_up']:g}.",
        "Default lens 35 mm (about 54 degrees across).",
    ]
    others = [e for e in spec.traffic if e.placed()]
    if others:
        lines.append(f"Other aircraft ({len(others)}):")
        for e in others:
            p = e.placement()
            lines.append(f"- a {e.aircraft.value} at {p['ahead_m']:g} m ahead, "
                         f"{p['right_m']:g} m right, {p['up_m']:g} m up")
    else:
        lines.append("No other aircraft.")
    if spec.cameras:
        lines.append(f"Cameras already in the scene ({len(spec.cameras)}):")
        lines.extend(describe_camera(c) for c in spec.cameras)
    else:
        lines.append("No cameras yet.")
    return "\n".join(lines)


# -- the model reader --------------------------------------------------------

def parse_intent_llm(prompt: str, spec, client: Any = None,
                     model: Optional[str] = None) -> CameraIntent:
    """Read the sentence with the language model the compiler uses.

    ``client`` is anthropic-shaped (the suite injects a mock); left
    ``None`` it resolves exactly as ``compile_prompt_llm`` does. Any
    transport or schema failure raises :class:`CameraPromptError`; the
    caller falls back to the rule reader and says so.
    """
    from .llm_compiler import DEFAULT_MODEL

    model = model or DEFAULT_MODEL
    if client is None:
        from .providers import resolve_client

        try:
            resolved = resolve_client()
        except ValueError as exc:
            raise CameraPromptError(str(exc)) from exc
        if resolved is not None:
            client, provider_model = resolved
            if model == DEFAULT_MODEL:
                model = provider_model
        elif "ANTHROPIC_API_KEY" not in os.environ:
            raise CameraPromptError("no language model is configured")
        else:
            try:
                import anthropic
            except ImportError as exc:
                raise CameraPromptError("the anthropic SDK is not installed") from exc
            client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=model, max_tokens=1000, system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": f"{scene_context(spec)}\n\n"
                                  f"Camera sentence: {prompt}"}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema",
                                      "schema": INTENT_SCHEMA}})
        text = next(b.text for b in response.content
                    if getattr(b, "type", None) == "text")
        data = json.loads(text)
    except Exception as exc:
        raise CameraPromptError(
            f"the language model could not be used ({type(exc).__name__})") from exc
    intent = intent_from_dict(data)
    intent.reader, intent.model = "llm", model
    return intent


def _finite(data: Dict[str, Any], key: str) -> Optional[float]:
    """An optional number: absent or null is None, anything else must be a
    finite number."""
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise CameraPromptError(f"{key} is not a finite number")
    return float(value)


def intent_from_dict(data: Any) -> CameraIntent:
    """Strict parse of the model's JSON: unknown keys, wrong types and
    out-of-vocabulary words are refused by name, never repaired."""
    if not isinstance(data, dict):
        raise CameraPromptError("the reply is not a JSON object")
    unknown = set(data) - set(INTENT_SCHEMA["properties"])
    missing = set(INTENT_SCHEMA["required"]) - set(data)
    if unknown or missing:
        raise CameraPromptError(
            f"the reply's keys are wrong (unknown {sorted(unknown)}, "
            f"missing {sorted(missing)})")
    if data["view"] not in VIEWS or data["anchor"] not in ANCHORS:
        raise CameraPromptError(
            f"view {data['view']!r} / anchor {data['anchor']!r} are outside "
            f"{VIEWS} / {ANCHORS}")
    numbers = {}
    for key in ("forward_m", "right_m", "up_m"):
        value = _finite(data, key)
        if value is None:
            raise CameraPromptError(f"{key} is not a finite number")
        numbers[key] = value
    if not isinstance(data["show_all"], bool):
        raise CameraPromptError("show_all is not a boolean")
    edit = data.get("edit_camera_id")
    if edit is not None and not isinstance(edit, str):
        raise CameraPromptError("edit_camera_id is not a string")
    focal = _finite(data, "focal_length_mm")
    if focal is not None and focal <= 0.0:
        raise CameraPromptError(f"focal_length_mm {focal:g} is not positive")
    aim = data.get("aim")
    if aim is not None and aim not in AIMS:
        raise CameraPromptError(f"aim {aim!r} is outside {AIMS}")
    moves = data.get("moves")
    if moves is not None:
        if not isinstance(moves, list) \
                or any(m not in MOVE_KINDS for m in moves):
            raise CameraPromptError(
                f"moves {moves!r} must be a list drawn from {MOVE_KINDS}")
        moves = list(dict.fromkeys(moves))
    return CameraIntent(view=data["view"], anchor=data["anchor"],
                        show_all=data["show_all"], quote=str(data["quote"]),
                        note=str(data["note"]),
                        edit_camera_id=(edit.strip() or None) if edit else None,
                        focal_length_mm=focal, aim=aim,
                        aim_bearing_deg=_finite(data, "aim_bearing_deg"),
                        aim_elevation_deg=_finite(data, "aim_elevation_deg"),
                        moves=moves, **numbers)


# -- the rule reader (no model reachable) -------------------------------------

_UNITS = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
          "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
          "kilometre": 1000.0, "kilometres": 1000.0,
          "ft": 0.3048, "feet": 0.3048, "foot": 0.3048, "mile": 1609.344,
          "miles": 1609.344}
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(km|kilometres?|kilometers?|metres?|"
                     r"meters?|miles?|feet|foot|ft|m)\b")
_WORD_DISTANCE = (("very far", "very_far"), ("far", "far"), ("close", "close"),
                  ("tight", "close"), ("near", "close"))
_LENS = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b")
_LENS_WORDS = (("ultra wide", 16.0), ("ultra-wide", 16.0),
               ("super telephoto", 200.0), ("wide angle", 24.0),
               ("wide-angle", 24.0), ("telephoto", 85.0), ("long lens", 85.0))
_COMPASS = {"north": 0.0, "east": 90.0, "south": 180.0, "west": 270.0}
#: The sentence restricts the view to the main aircraft.
_ONLY_MAIN = re.compile(r"\b(only|just)\b[^,.;]*\b(main|lead|primary|first)\b|"
                        r"\b(main|lead|primary|first) (aircraft|plane|jet)"
                        r" only\b")


def parse_intent_rules(prompt: str, spec=None) -> CameraIntent:
    """The deterministic reader: direction words, a stated distance, a
    lens, a compass aim and move words. Used when no language model is
    reachable; it understands less (no edits of an existing camera), and
    says what it did not. Distances are scaled to ``spec``'s aircraft
    when a spec is given."""
    text = " ".join(prompt.lower().split())
    if not text:
        raise CameraPromptError("the camera sentence is empty")
    table = framing_distances(str(spec.aircraft.value)) if spec is not None \
        else {"close": 60.0, "default": 150.0, "far": 400.0,
              "very_far": 1000.0, "chase_up": 20.0}
    chase_up = max(table["chase_up"], 2.0)
    distance = None
    for match in _NUMBER.finditer(text):
        distance = float(match.group(1)) * _UNITS[match.group(2)]
        break
    if distance is None:
        for word, key in _WORD_DISTANCE:
            if re.search(rf"\b{word}\b", text):
                distance = table[key]
                break
    d = distance if distance is not None else table["default"]

    view = "follow"
    if re.search(r"\b(ground|runway|spectator|observer)\b", text):
        view = "ground"
    if re.search(r"\btower\b", text):
        view = "tower"
    if re.search(r"\b(cockpit|pilot'?s view|over the shoulder)\b", text):
        view = "cockpit"
    forward = right = up = 0.0
    said = []
    if re.search(r"\b(behind|trailing|chase|rear|back)\b", text):
        forward, said = -d, said + ["behind"]
    elif re.search(r"\b(in front|ahead|head[- ]?on|front)\b", text):
        forward, said = d, said + ["ahead"]
    if re.search(r"\b(left|port)\b", text):
        right, said = -d, said + ["left"]
    elif re.search(r"\b(right|starboard)\b", text):
        right, said = d, said + ["right"]
    if re.search(r"\b(above|overhead|top|bird'?s[- ]eye|high|over)\b", text):
        up, said = (d if forward == right == 0.0 else max(d * 0.4, chase_up)), said + ["above"]
    elif re.search(r"\b(below|under|beneath|low)\b", text):
        up, said = -max(d * 0.3, chase_up), said + ["below"]
    if not said:
        forward, up = -d, chase_up
        said = ["no direction named; defaulted to behind"]
    elif up == 0.0:
        up = chase_up if view == "follow" else 0.0
    only_main = bool(_ONLY_MAIN.search(text))
    anchor_centre = not only_main and bool(re.search(
        r"\b(both|all|every|two|three|pair|formation|aircraft|planes)\b", text))
    show_all = not only_main

    focal = None
    m = _LENS.search(text)
    if m:
        focal = float(m.group(1))
    else:
        for word, mm in _LENS_WORDS:
            if word in text:
                focal = mm
                break
    aim = bearing = elevation = None
    m = re.search(r"\blooking (north|east|south|west)\b", text)
    if m:
        aim, bearing, elevation = "bearing", _COMPASS[m.group(1)], 0.0
    elif re.search(r"\blooking (straight )?down\b", text):
        straight = re.search(r"\blooking straight down\b", text)
        aim, elevation = "bearing", -90.0 if straight else -30.0
        bearing = float(spec.heading.value) if spec is not None else 0.0
    moves = [kind for _, kind in prompt_moves(text)] or None
    extras = ([f"lens {focal:g} mm"] if focal else []) \
        + ([f"aim {bearing:g} deg / {elevation:g} deg"] if aim else []) \
        + ([f"moves {', '.join(moves)}"] if moves else [])
    note = (f"read '{prompt.strip()}' with the rule parser ({', '.join(said)}"
            f"; distance {d:g} m"
            f"{'' if distance is not None else ', a default for this aircraft'}"
            f"{'; ' + '; '.join(extras) if extras else ''}); a language "
            f"model would read looser wording and edits of an existing camera")
    return CameraIntent(view=view, anchor="centre" if anchor_centre else "primary",
                        forward_m=forward, right_m=right, up_m=up,
                        show_all=show_all, quote=prompt.strip(),
                        note=note, reader="rules", focal_length_mm=focal,
                        aim=aim, aim_bearing_deg=bearing,
                        aim_elevation_deg=elevation, moves=moves)


def read_intent(prompt: str, spec, client: Any = None) -> Tuple[CameraIntent, Optional[str]]:
    """The model's reading, or the rules' when the model cannot be used.
    Returns the intent and the reason the model was skipped (or None)."""
    from .llm_compiler import llm_available

    if llm_available():
        try:
            return parse_intent_llm(prompt, spec, client=client), None
        except CameraPromptError as exc:
            return parse_intent_rules(prompt, spec), str(exc)
    return parse_intent_rules(prompt, spec), "no language model is configured"


# -- geometry: where is every aircraft, and is it in the frame? --------------

@dataclass
class FitReport:
    focal_mm: float
    offset: Tuple[float, float, float]
    widened: bool = False
    pulled_back: bool = False
    capped: bool = False
    worst_fraction: float = 0.0     #: largest use of the half-frame (1.0 = edge)
    notes: List[str] = field(default_factory=list)


def _aircraft_positions(spec, t: float) -> List[Tuple[float, float, float]]:
    """Every aircraft's (forward, right, up) metres from the main aircraft
    at ``t`` seconds, in the main aircraft's heading frame. The main one is
    the origin; a stationary aircraft falls astern at the main aircraft's
    speed, an offset one drifts at its stated speed difference."""
    speed = float(spec.airspeed.value) * 0.514444
    out = [(0.0, 0.0, 0.0)]
    for entry in spec.traffic:
        if not entry.placed():
            continue
        p = entry.placement()
        if str(entry.track.value) == "stationary":
            ahead = p["ahead_m"] - speed * t
        else:
            ahead = p["ahead_m"] + p["speed_delta_kt"] * 0.514444 * t
        out.append((ahead, p["right_m"], p["up_m"]))
    return out


def _worst_ratio(points, camera, focal_mm, sensor_w, sensor_h) -> float:
    """Largest fraction of the half-frame any aircraft uses when the camera
    at ``camera`` looks at the main aircraft (origin). > 1 = outside."""
    cf, cr, cu = camera
    ax, ay, az = -cf, -cr, -cu                    # view axis: camera -> origin
    norm = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    ax, ay, az = ax / norm, ay / norm, az / norm
    # right axis: horizontal, perpendicular to the view axis (forward, right)
    hx, hy = ax, ay
    hn = math.hypot(hx, hy)
    if hn < 1e-9:                                 # straight down: use heading
        rx, ry = 0.0, 1.0
    else:
        rx, ry = -hy / hn, hx / hn
    half_w = (sensor_w / 2.0) / focal_mm
    half_h = (sensor_h / 2.0) / focal_mm
    worst = 0.0
    for f, r, u in points:
        vx, vy, vz = f - cf, r - cr, u - cu
        z = vx * ax + vy * ay + vz * az
        if z <= 1.0:
            return float("inf")                   # behind the camera
        x = vx * rx + vy * ry
        # (view axis, right axis, up axis) are orthonormal, so the part of
        # the offset along the up axis is what is left of its length
        y = math.sqrt(max(vx * vx + vy * vy + vz * vz - z * z - x * x, 0.0))
        size = AIRCRAFT_RADIUS_M / z
        worst = max(worst, (abs(x) / z + size) / half_w,
                    (y / z + size) / half_h)
    return worst


def fit_all_in_view(spec, camera, base_focal_mm: float, sensor_w: float,
                    sensor_h: float, duration_s: float,
                    lock_focal: bool = False) -> FitReport:
    """Widen the lens, then pull the camera back, until every aircraft is
    inside the frame at the start, middle and end of the clip. A
    ``lock_focal`` lens (one the user stated) is never widened: the
    camera is pulled back instead."""
    times = [0.0, duration_s / 2.0, duration_s]
    points = [p for t in times for p in _aircraft_positions(spec, t)]
    focal = base_focal_mm
    offset = camera
    report = FitReport(focal_mm=focal, offset=offset)
    limit = FRAME_MARGIN
    while True:
        worst = _worst_ratio(points, offset, focal, sensor_w, sensor_h)
        if worst <= limit:
            break
        # the half-frame use is proportional to the focal length, so the
        # longest lens that fits is a straight ratio
        if not lock_focal:
            if math.isfinite(worst) and focal * limit / worst >= MIN_FOCAL_MM:
                focal = focal * limit / worst
                report.widened = True
                break
            if focal > MIN_FOCAL_MM:
                focal = MIN_FOCAL_MM
                report.widened = True
                continue
        # the lens is at its widest (or stated): pull the camera back
        back = math.sqrt(offset[0] ** 2 + offset[1] ** 2 + offset[2] ** 2)
        if back >= MAX_BACK_M:
            report.capped = True
            break
        offset = (offset[0] * 1.25 if offset[0] else -30.0,
                  offset[1] * 1.25, offset[2] * 1.25)
        report.pulled_back = True
    report.focal_mm = focal
    report.offset = offset
    report.worst_fraction = _worst_ratio(points, offset, focal, sensor_w, sensor_h)
    if report.widened:
        report.notes.append(f"lens widened from {base_focal_mm:g} mm to {focal:.1f} mm "
                            f"to keep every aircraft in frame")
    if report.pulled_back:
        report.notes.append(
            f"camera pulled back to {offset[0]:.0f} m forward / {offset[1]:.0f} m right "
            f"/ {offset[2]:.0f} m up "
            + (f"(the stated {focal:g} mm lens is kept)" if lock_focal else
               f"(the widest lens, {MIN_FOCAL_MM:g} mm, was not enough)"))
    if report.capped:
        report.notes.append(
            f"NOT every aircraft fits: the camera reached the {MAX_BACK_M:g} m "
            f"limit with {'the stated' if lock_focal else 'the widest'} lens; move the aircraft closer together or "
            f"state a different view")
    return report


# -- building the camera -------------------------------------------------------

def centre_of_aircraft(spec) -> Tuple[float, float, float]:
    """Mean (forward, right, up) of the aircraft at the start of the clip."""
    points = _aircraft_positions(spec, 0.0)
    n = len(points)
    return tuple(sum(p[i] for p in points) / n for i in range(3))


def find_camera(spec, camera_id: Optional[str]) -> Optional[int]:
    """Index of the spec's camera named ``camera_id``, or None."""
    if not camera_id:
        return None
    for index, camera in enumerate(spec.cameras):
        if str(camera.camera_id.value) == camera_id:
            return index
    return None


def build_camera(spec, intent: CameraIntent, camera_id: str, existing=None):
    """A :class:`CameraSpec` for the intent, every stated number carrying
    the user's own words as its provenance. ``existing`` is the camera an
    edit replaces: its lens, aim, schedule and moves carry over unless the
    sentence restates them. Returns (camera, notes)."""
    from ..scenario.camera import CameraSpec, plan_full_capture
    from ..scenario.fields import PLANNABLE_SOURCES
    from .compiler import apply_moves, describe_moves

    frm = f"camera sentence: {intent.quote!r}" if intent.quote else "camera sentence"
    preset = VIEW_PRESETS[intent.view]
    if existing is not None and intent.view == "follow" \
            and str(existing.preset.value) in ("chase", "wingman"):
        preset = str(existing.preset.value)          # a wingman stays a wingman
    notes = [f"{intent.reader}: {intent.note}".strip()] if intent.note else []
    old_kinds = describe_moves(existing.moves) if existing is not None else []
    if existing is not None and str(existing.preset.value) == preset:
        camera = CameraSpec.from_dict(existing.to_dict())
        camera.moves = []
    else:
        camera = CameraSpec.defaulted(
            camera_id=camera_id, preset=preset, aircraft=str(spec.aircraft.value),
            terrain_elevation_m=float(spec.terrain_elevation.value), frm=frm)
        if existing is not None:
            for name in SCHEDULE_FIELDS:
                setattr(camera, name, getattr(existing, name))
        else:
            plan_full_capture(camera, frm="a view added from the page captures "
                                          "the whole clip")

    if intent.focal_length_mm is not None:
        camera.set("focal_length_mm", float(intent.focal_length_mm), frm=frm)

    if intent.aim is not None:
        if preset == "cockpit":
            notes.append("the cockpit view looks where the aircraft points; "
                         "the stated aim was not applied")
        elif intent.aim == "aircraft":
            camera.set("aim_mode", "aircraft", frm=frm)
        else:
            bearing = intent.aim_bearing_deg
            if bearing is None:
                bearing = float(spec.heading.value)
                notes.append(f"no bearing stated; looking along the aircraft's "
                             f"heading, {bearing:g} deg")
            camera.set("aim_mode", "bearing", frm=frm)
            camera.set("aim_bearing_deg", float(bearing) % 360.0, frm=frm)
            camera.set("aim_elevation_deg",
                       max(-90.0, min(90.0, float(intent.aim_elevation_deg or 0.0))),
                       frm=frm)

    if preset in ("chase", "wingman"):
        offset = (intent.forward_m, intent.right_m, intent.up_m)
        if intent.anchor == "centre":
            c = centre_of_aircraft(spec)
            offset = tuple(o + ci for o, ci in zip(offset, c))
            notes.append(f"measured from the middle of all {1 + len(spec.traffic)} "
                         f"aircraft ({c[0]:.0f} m ahead, {c[1]:.0f} m right, "
                         f"{c[2]:.0f} m up of the main one)")
        camera.set("offset_forward_m", float(offset[0]), frm=frm)
        camera.set("offset_right_m", float(offset[1]), frm=frm)
        camera.set("offset_up_m", float(offset[2]), frm=frm)

        if intent.show_all and any(e.placed() for e in spec.traffic):
            if str(camera.aim_mode.value) != "aircraft":
                notes.append("the camera looks away from the aircraft, so "
                             "nothing was done to keep every aircraft in frame")
            else:
                lock = camera.focal_length_mm.source not in PLANNABLE_SOURCES
                report = fit_all_in_view(
                    spec, offset, float(camera.focal_length_mm.value),
                    float(camera.sensor_width_mm.value),
                    float(camera.sensor_height_mm.value),
                    float(spec.duration.value), lock_focal=lock)
                if report.pulled_back:
                    camera.set("offset_forward_m", float(report.offset[0]), frm=frm)
                    camera.set("offset_right_m", float(report.offset[1]), frm=frm)
                    camera.set("offset_up_m", float(report.offset[2]), frm=frm)
                if report.widened:
                    camera.plan("focal_length_mm", round(report.focal_mm, 2),
                                frm="widened so every aircraft is in frame")
                notes.extend(report.notes)
    elif any((intent.forward_m, intent.right_m, intent.up_m)) \
            and preset != "cockpit":
        notes.append(f"a {preset} camera has a fixed place; the offset in the "
                     f"sentence does not apply to it")

    if intent.moves is not None:
        kinds = list(intent.moves)
    elif "custom" in old_kinds:
        kinds = []
        camera.moves = [dict(m) for m in existing.moves]
        notes.append("kept the camera's hand-keyed moves as they were")
    else:
        kinds = old_kinds
        if kinds:
            notes.append(f"kept the camera's moves ({', '.join(kinds)}), "
                         f"re-keyed on its new placement")
    apply_moves(camera, [(kind.replace("_", " "), kind) for kind in kinds],
                float(spec.duration.value), notes)
    return camera, notes
