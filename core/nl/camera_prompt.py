"""Camera placement from a sentence: "behind and above both planes, about 300 m back".

The page lets a user describe where the camera should be instead of
picking a preset. A language model (or, when none is reachable, the
rule parser below) turns the sentence into a small, schema-checked
*intent*: which kind of view, and an offset in metres from the main
aircraft's own heading frame. Nothing the model says is evidence of
geometry: the intent is only ever the user's own phrase read as numbers,
and the geometry that decides whether every aircraft is in view is
computed here, deterministically, from the spec (:func:`fit_all_in_view`).

What this does and does not do:

* The camera is a ``chase`` view (it follows the main aircraft; the
  offset is forward / right / up in that aircraft's heading frame), or
  the world-anchored ``ground`` / ``tower`` presets the sentence names.
* ``anchor: "centre"`` measures the offset from the middle of all the
  aircraft instead of from the main one, so "above both planes" is above
  both.
* The fit check places every aircraft at the start, middle and end of the
  clip, works out the angle from the camera's axis, and widens the lens
  (down to :data:`MIN_FOCAL_MM`) and then pulls the camera back until all
  of them are inside the frame with a margin. It reports what it did, and
  says so when it hit :data:`MAX_BACK_M` and could not fit them all. It
  models the aircraft as points plus a size margin and the main aircraft's
  airspeed as its ground speed; the camera's follow lag is ignored.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: The views a sentence may ask for.
VIEWS = ("follow", "ground", "tower")
ANCHORS = ("primary", "centre")

#: Widest lens the fit may use before it pulls the camera back instead.
MIN_FOCAL_MM = 18.0
#: How far back the fit may pull the camera, metres.
MAX_BACK_M = 6000.0
#: Margin on the frame (fraction of the half-angle kept clear) and the
#: aircraft's own size in metres (half a wingspan, generously).
FRAME_MARGIN = 0.85
AIRCRAFT_RADIUS_M = 20.0

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
                                "tower position"},
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
        "quote": {"type": "string",
                  "description": "the words of the sentence this reads"},
        "note": {"type": "string",
                 "description": "one short sentence: what was understood, "
                                "and any distance the sentence left open "
                                "that a default filled"},
    },
}

SYSTEM_PROMPT = """\
You place a camera in a flight simulation from one sentence. Reply with
JSON that matches the schema. Do not invent anything the sentence does not
say; where it leaves a distance open, choose a sensible default and say so
in "note".

Coordinates: metres, in the MAIN aircraft's own heading frame. forward_m is
along its heading (negative = behind it), right_m is to its right (negative
= left), up_m is above it (negative = below).

- "behind", "chase", "trailing" -> negative forward_m (default -150).
- "in front", "ahead", "head-on" -> positive forward_m.
- "left" / "right" side views -> right_m negative / positive (default 150).
- "above", "overhead", "from the top", "bird's eye" -> positive up_m
  (default 150); a straight-down view is up_m large and forward_m, right_m 0.
- "from the ground", "from the runway" -> view "ground"; "from the tower"
  -> view "tower"; every other camera is view "follow".
- "both planes", "all aircraft", "the pair", "the formation" -> anchor
  "centre" and show_all true. A sentence about only the main aircraft is
  anchor "primary".
- Numbers and units the sentence states win: "300 m", "1 km" (1000 m),
  "500 ft" (152.4 m), "a mile" (1609 m). Words: "close" ~ 60 m, "far" ~ 400 m,
  "very far" ~ 1000 m.
"""


@dataclass
class CameraIntent:
    """The sentence, read as numbers."""

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

    def to_dict(self) -> Dict[str, Any]:
        return {"view": self.view, "anchor": self.anchor,
                "forward_m": self.forward_m, "right_m": self.right_m,
                "up_m": self.up_m, "show_all": self.show_all,
                "quote": self.quote, "note": self.note,
                "reader": self.reader, "model": self.model}


class CameraPromptError(ValueError):
    """The sentence could not be read; the message says why."""


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

    context = (f"The scene has {1 + len(spec.traffic)} aircraft: the main "
               f"{spec.aircraft.value}"
               + "".join(f" and a {e.aircraft.value} at "
                         f"{e.placement()['ahead_m']:g} m ahead, "
                         f"{e.placement()['right_m']:g} m right, "
                         f"{e.placement()['up_m']:g} m up"
                         for e in spec.traffic if e.placed())
               + ".")
    try:
        response = client.messages.create(
            model=model, max_tokens=1000, system=SYSTEM_PROMPT,
            messages=[{"role": "user",
                       "content": f"{context}\nCamera sentence: {prompt}"}],
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
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value):
            raise CameraPromptError(f"{key} is not a finite number")
        numbers[key] = float(value)
    if not isinstance(data["show_all"], bool):
        raise CameraPromptError("show_all is not a boolean")
    return CameraIntent(view=data["view"], anchor=data["anchor"],
                        show_all=data["show_all"], quote=str(data["quote"]),
                        note=str(data["note"]), **numbers)


# -- the rule reader (no model reachable) -------------------------------------

_UNITS = {"m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
          "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
          "kilometre": 1000.0, "kilometres": 1000.0,
          "ft": 0.3048, "feet": 0.3048, "foot": 0.3048, "mile": 1609.344,
          "miles": 1609.344}
_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(km|kilometres?|kilometers?|metres?|"
                     r"meters?|miles?|feet|foot|ft|m)\b")
_WORD_DISTANCE = (("very far", 1000.0), ("far", 400.0), ("close", 60.0),
                  ("tight", 60.0), ("near", 80.0))


def parse_intent_rules(prompt: str) -> CameraIntent:
    """The deterministic reader: direction words and a stated distance.
    Used when no language model is reachable; it understands less, and
    says what it did not."""
    text = " ".join(prompt.lower().split())
    if not text:
        raise CameraPromptError("the camera sentence is empty")
    distance = None
    for match in _NUMBER.finditer(text):
        distance = float(match.group(1)) * _UNITS[match.group(2)]
        break
    if distance is None:
        for word, metres in _WORD_DISTANCE:
            if re.search(rf"\b{word}\b", text):
                distance = metres
                break
    d = distance if distance is not None else 150.0

    view = "follow"
    if re.search(r"\b(ground|runway|spectator|observer)\b", text):
        view = "ground"
    if re.search(r"\btower\b", text):
        view = "tower"
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
        up, said = (d if forward == right == 0.0 else max(d * 0.4, 30.0)), said + ["above"]
    elif re.search(r"\b(below|under|beneath|low)\b", text):
        up, said = -max(d * 0.3, 20.0), said + ["below"]
    if not said:
        forward, up = -d, 30.0
        said = ["no direction named; defaulted to behind"]
    elif up == 0.0:
        up = 20.0 if view == "follow" else 0.0
    anchor_centre = bool(re.search(
        r"\b(both|all|every|two|three|pair|formation|aircraft|planes)\b", text))
    note = (f"read '{prompt.strip()}' with the rule parser ({', '.join(said)}"
            f"; distance {d:g} m"
            f"{'' if distance is not None else ', a default'}); a language "
            f"model would read looser wording")
    return CameraIntent(view=view, anchor="centre" if anchor_centre else "primary",
                        forward_m=forward, right_m=right, up_m=up,
                        show_all=anchor_centre or True, quote=prompt.strip(),
                        note=note, reader="rules")


def read_intent(prompt: str, spec, client: Any = None) -> Tuple[CameraIntent, Optional[str]]:
    """The model's reading, or the rules' when the model cannot be used.
    Returns the intent and the reason the model was skipped (or None)."""
    from .llm_compiler import llm_available

    if llm_available():
        try:
            return parse_intent_llm(prompt, spec, client=client), None
        except CameraPromptError as exc:
            return parse_intent_rules(prompt), str(exc)
    return parse_intent_rules(prompt), "no language model is configured"


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
                    sensor_h: float, duration_s: float) -> FitReport:
    """Widen the lens, then pull the camera back, until every aircraft is
    inside the frame at the start, middle and end of the clip."""
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
        if math.isfinite(worst) and focal * limit / worst >= MIN_FOCAL_MM:
            focal = focal * limit / worst
            report.widened = True
            break
        if focal > MIN_FOCAL_MM:
            focal = MIN_FOCAL_MM
            report.widened = True
            continue
        # the lens is already at its widest: pull the camera back
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
            f"/ {offset[2]:.0f} m up (the widest lens, {MIN_FOCAL_MM:g} mm, was not enough)")
    if report.capped:
        report.notes.append(
            f"NOT every aircraft fits: the camera reached the {MAX_BACK_M:g} m "
            f"limit with the widest lens; move the aircraft closer together or "
            f"state a different view")
    return report


# -- building the camera -------------------------------------------------------

def centre_of_aircraft(spec) -> Tuple[float, float, float]:
    """Mean (forward, right, up) of the aircraft at the start of the clip."""
    points = _aircraft_positions(spec, 0.0)
    n = len(points)
    return tuple(sum(p[i] for p in points) / n for i in range(3))


def build_camera(spec, intent: CameraIntent, camera_id: str):
    """A :class:`CameraSpec` for the intent, every stated number carrying
    the user's own words as its provenance. Returns (camera, notes)."""
    from ..scenario.camera import CameraSpec, plan_full_capture

    frm = f"camera sentence: {intent.quote!r}" if intent.quote else "camera sentence"
    preset = {"follow": "chase", "ground": "ground", "tower": "tower"}[intent.view]
    camera = CameraSpec.defaulted(
        camera_id=camera_id, preset=preset, aircraft=str(spec.aircraft.value),
        terrain_elevation_m=float(spec.terrain_elevation.value), frm=frm)
    notes = [f"{intent.reader}: {intent.note}".strip()] if intent.note else []
    plan_full_capture(camera, frm="a view added from the page captures the whole clip")
    if preset != "chase":
        notes.append(f"a {preset} camera is a fixed place; it looks at the main "
                     f"aircraft and its lens is the default")
        return camera, notes

    offset = (intent.forward_m, intent.right_m, intent.up_m)
    if intent.anchor == "centre":
        c = centre_of_aircraft(spec)
        offset = tuple(o + ci for o, ci in zip(offset, c))
        notes.append(f"measured from the middle of all {1 + len(spec.traffic)} aircraft "
                     f"({c[0]:.0f} m ahead, {c[1]:.0f} m right, {c[2]:.0f} m up of the "
                     f"main one)")
    camera.set("offset_forward_m", float(offset[0]), frm=frm)
    camera.set("offset_right_m", float(offset[1]), frm=frm)
    camera.set("offset_up_m", float(offset[2]), frm=frm)

    if intent.show_all and any(e.placed() for e in spec.traffic):
        report = fit_all_in_view(
            spec, offset, float(camera.focal_length_mm.value),
            float(camera.sensor_width_mm.value),
            float(camera.sensor_height_mm.value),
            float(spec.duration.value))
        if report.pulled_back:
            camera.set("offset_forward_m", float(report.offset[0]), frm=frm)
            camera.set("offset_right_m", float(report.offset[1]), frm=frm)
            camera.set("offset_up_m", float(report.offset[2]), frm=frm)
        if report.widened:
            camera.plan("focal_length_mm", round(report.focal_mm, 2),
                        frm="widened so every aircraft is in frame")
        notes.extend(report.notes)
    return camera, notes
