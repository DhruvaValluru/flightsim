"""Compile a prompt into a scenario spec with a language model.

The LLM fills THE SAME schema the regex compiler fills (§2.6 unchanged:
``prompt -> spec -> validate -> run``, never ``prompt -> run``). What it adds
is breadth: sentence shapes the regex vocabulary cannot parse. What it does
NOT add is trust:

* The model's output is constrained to a JSON schema generated from
  :class:`ScenarioSpec`'s own fields, parsed strictly, and rejected loudly on
  any deviation -- a response that fails parsing is an error shown to the
  user, never silently patched into a runnable spec.
* Every produced value carries the existing provenance tags: an explicit
  number in the prompt is ``user`` (with the phrase recorded), a vague phrase
  is ``inferred``, an untouched field is ``default`` -- and the defaults are
  BYTE-IDENTICAL to the regex compiler's, because they are built by running
  the regex compiler on an empty prompt and overlaying only what the model
  stated. On the regex compiler's own vocabulary the validator therefore
  judges both compilers' specs identically.
* The EXISTING ``validate()`` still governs. An impossible request compiles
  to a spec that is refused by name (``altitude.terrain_clearance``,
  ``airspeed.stall_margin``, ``envelope.trim_feasible``) exactly as today;
  this module never pre-judges feasibility.
* Anything the prompt mentions that the schema cannot express goes to
  ``spec.notes``, not the bin -- the same rule the regex compiler follows.
* The model knows exactly which real terrain bakes exist: a locations block
  is GENERATED into the system prompt from :data:`core.terrain.glo30.LOCATIONS`
  (same generated-not-hand-copied discipline as the schema), so a prompt
  naming the Matterhorn lands on the real bake's origin exactly, and a place
  the system cannot render is never given invented coordinates.
* The model may ask AT MOST one round of AT MOST three clarifying questions,
  and only where the prompt is ambiguous in a way that materially changes
  the scenario with no basis to infer (which mountains; which aircraft).
  Both bounds are enforced in parsing, not just requested in the prompt. A
  field decided by an answer is the user speaking: source ``user`` with the
  question and answer recorded in ``from``. Questions are a control against
  misinterpretation; they add no claims, and the Q&A transcript is a
  historical note beside the prompt (§2.6 unchanged).

The reproducibility claim does not move. The spec is the reproducible unit;
the prompt is a historical note (§2.6 was written for exactly this moment).
The LLM adds nondeterminism on the prompt->spec edge only; the caller records
prompt, model id, raw response and which compiler ran, and the spec-review
step is the control for misinterpretation.

``ANTHROPIC_API_KEY`` comes from the environment via the SDK's own
resolution. It is never read by this module, never stored, and never written
to any manifest.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..environment.sun import NAMED_TIMES as SUN_NAMED_TIMES
from ..environment.sun import canonical_time_of_day
from ..environment.surface import SURFACE_CLASSES
from ..scenario.blocks import MAX_TRAFFIC, TRAFFIC_TRACKS, TrafficSpec
from ..scenario.camera import (CAMERA_PRESETS, CameraSpec,
                               plan_full_capture)
from ..scenario.fields import Quantity, Source
from ..scenario.randomization import (
    HOUR_WINDOWS, LOCATION_RANGES, POLICY_CAMERA_LEAVES, POLICY_LEAVES,
    enable_for_policy,
)
from ..scenario.spec import ScenarioSpec
from ..terrain.glo30 import LOCATIONS
from .compiler import (MOVE_KINDS, RANDOMIZATION_FAMILIES, TURBULENCE_STD,
                       TURBULENCE_WORDS, apply_mountain_scene, apply_moves,
                       apply_randomization_phrases, compile_prompt,
                       prompt_moves, _name_from)

#: The model the compiler asks for. Recorded verbatim in the result so the
#: manifest can say which model produced the spec.
DEFAULT_MODEL = "claude-opus-5"

#: Aircraft the schema lets the model name: exactly the models the regex
#: vocabulary can reach, so the two compilers share an aircraft vocabulary
#: and ``aircraft.exists`` validation stays the only authority on what flies.
AIRCRAFT_MODELS = ("737", "A320", "A4", "B747", "c172p", "f15", "f16",
                   "global5000")

#: Canonical turbulence labels and their W20 (the regex compiler's own
#: mapping, deduplicated to the labels the spec vocabulary stores).
TURBULENCE_LABELS = {
    "none": 0.0, "light": 15.0, "moderate": 30.0, "severe": 45.0,
}

#: Hard cap on clarifying questions per response, enforced in parsing.
MAX_QUESTIONS = 3

#: Human names that should land on each real terrain bake. Keyed by
#: ``LOCATIONS``' own keys; :func:`_assert_locations_covered` keeps this
#: table and the bake list from drifting apart at import time.
LOCATION_ALIASES: Dict[str, Tuple[str, ...]] = {
    "matterhorn": ("Matterhorn", "Zermatt", "the Alps", "Pennine Alps",
                   "Swiss Alps", "Monte Rosa"),
    "yosemite": ("Yosemite", "Yosemite Valley", "Sierra Nevada",
                 "Half Dome", "El Capitan"),
    "fuji": ("Mount Fuji", "Fuji", "Fujisan", "Japan volcano"),
    "everest": ("Everest", "Mount Everest", "the Himalayas", "Himalaya",
                "Lhotse", "Sagarmatha"),
    "grand_canyon": ("Grand Canyon", "the canyon", "Colorado River canyon",
                     "Vishnu Temple"),
    "flint_hills": ("Flint Hills", "Kansas", "Kansas prairie",
                    "tallgrass prairie", "the prairie"),
}

#: Ground elevation at each bake's origin, metres MSL -- the showcase
#: matrix's own ``ground_m`` convention, measured from the bake raster
#: (matterhorn 1859.2, yosemite 1230.9, rounded). NOT summit height: the
#: spec's terrain_elevation is the flat physics slab / clearance datum.
LOCATION_TERRAIN_ELEVATION_M: Dict[str, float] = {
    "matterhorn": 1860.0,
    "yosemite": 1230.0,
    # Phase 9 bakes, measured from each raster at its origin (2026-08-11):
    "fuji": 1465.0,
    "everest": 4720.0,
    "grand_canyon": 1340.0,
    "flint_hills": 413.0,
}


def _assert_locations_covered(location_keys, table) -> None:
    """Every renderable bake must appear in the generated locations block.

    Called at import against both per-location tables so a bake added to
    ``LOCATIONS`` without prompt coverage fails here, not silently in a
    session where the model guesses coordinates for a place it should know.
    """
    missing = set(location_keys) - set(table)
    assert not missing, (f"terrain bakes missing from the LLM prompt's "
                         f"locations block: {sorted(missing)}")


_assert_locations_covered(LOCATIONS, LOCATION_ALIASES)
_assert_locations_covered(LOCATIONS, LOCATION_TERRAIN_ELEVATION_M)


def llm_available() -> bool:
    """A provider is configured. Presence check only -- no secret value is
    ever read, stored or logged by this module.

    True when an alternate provider is selected via ``FLIGHTSIM_LLM``
    (e.g. a local Ollama model -- see :mod:`core.nl.providers`), when
    the Anthropic SDK path is usable (key present, SDK importable), or --
    the zero-config default -- when nothing is set at all: an unset
    ``FLIGHTSIM_LLM`` with no Anthropic key resolves to the hosted relay,
    which needs no client-side secret. ``FLIGHTSIM_LLM=none`` opts out.
    This mirrors ``providers.resolve_client`` exactly.
    """
    provider = os.environ.get("FLIGHTSIM_LLM", "").strip().lower()
    if provider in ("none", "off"):
        return False
    if provider:
        return True
    if "ANTHROPIC_API_KEY" not in os.environ:
        return True                     # the hosted relay default
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


class LLMCompileError(Exception):
    """The model's response could not be accepted as a spec.

    Raised for transport failures, refusals, malformed JSON, unknown fields,
    out-of-vocabulary values and wrong types. The message is user-facing:
    the web app renders it as the outcome of /compile rather than guessing
    at a repair -- so it is a plain sentence, never an exception's repr.
    ``constraint`` is the catalogue name when the failure has its own
    (``compile.unreachable``: the call never reached a model); the
    sentence-named ones (``compile.rejected``, ``compile.unavailable``)
    leave it None. ``details`` carries the technical text (the transport
    error's class and message) for a log or a disclosure, never for the
    default path.
    """

    def __init__(self, message: str, constraint: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.constraint = constraint
        self.details = dict(details or {})


#: The sentence a transport failure shows: what happened and what the
#: person can do, with nothing of the exception in it.
UNREACHABLE_SENTENCE = ("the language model could not be reached; the "
                        "offline compiler is available meanwhile")


@dataclass(frozen=True)
class LLMCompileResult:
    """A compiled spec plus the evidence of how it was produced.

    ``raw_response`` is the model's verbatim JSON text and ``model`` the id
    that produced it; both belong in the run's provenance sidecar (never in
    a UE-written manifest string -- the prompt may contain non-ASCII).

    ``questions`` is non-empty when the model needs one round of
    clarification; ``spec`` is then the PARTIAL spec (confident fields over
    the documented defaults), honest to run as-is if the user declines to
    answer. ``transcript`` is the messages list actually sent on an answer
    round -- prompt, question turn, answer turn -- and joins the prompt in
    the UTF-8 provenance sidecar as a historical note, never as evidence.
    """

    spec: ScenarioSpec
    model: str
    raw_response: str
    compiler: str = "llm"
    questions: Tuple[Dict[str, Any], ...] = ()
    transcript: Optional[Tuple[Dict[str, str], ...]] = None


# -- the schema, generated from the spec's own fields ---------------------

def _field_schema(value_schema: Dict[str, Any]) -> Dict[str, Any]:
    """One provenanced field: a value, who stated it, and the phrase."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "source", "from"],
        "properties": {
            "value": value_schema,
            # "default" is deliberately absent: a defaulted field is an
            # OMITTED field. "user" is what the prompt states, "inferred"
            # the documented vocabulary mapping of its phrase, "model" the
            # director's own interpretation -- a declared guess, which the
            # planners may later move exactly like a default.
            "source": {"type": "string",
                       "enum": ["user", "inferred", "model"]},
            "from": {
                "type": "string",
                "description": "The prompt phrase this value was read from "
                               "(for source 'model': the quoted phrase the "
                               "guess interprets -- REQUIRED, never empty).",
            },
        },
    }


#: Value schema per LLM-settable field. Everything absent from this table
#: (rate, seed, mass_held, hold_state) is host policy, not scenario
#: vocabulary, and the model cannot touch it.
FIELD_VALUE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "aircraft": {"type": "string", "enum": list(AIRCRAFT_MODELS)},
    "altitude": {"type": "number", "description": "metres MSL"},
    "airspeed": {"type": "number", "description": "knots"},
    "airspeed_kind": {"type": "string", "enum": ["cas", "tas"]},
    "heading": {"type": "number", "description": "degrees true"},
    "latitude": {"type": "number", "description": "degrees north"},
    "longitude": {"type": "number", "description": "degrees east"},
    "terrain_elevation": {"type": "number", "description": "metres MSL"},
    "duration": {"type": "number", "description": "seconds"},
    "wind_speed": {"type": "number", "description": "knots"},
    "wind_direction": {
        "type": "number",
        "description": "degrees, meteorological (the bearing the wind is FROM)",
    },
    "turbulence": {"type": "string", "enum": sorted(TURBULENCE_LABELS)},
    "surface": {"type": "string", "enum": sorted(SURFACE_CLASSES)},
    "weather_event": {
        "type": "string", "enum": ["none", "thunderstorm", "tornado"],
    },
    "weather_date": {
        "type": "string",
        "description": "ISO date YYYY-MM-DD ONLY when the prompt states a "
                       "date; that day's ERA5 reanalysis wind applies. "
                       "Never invent a date.",
    },
    "time_of_day": {
        "type": "string",
        "description": "Render sun ONLY (never physics): one of "
                       + ", ".join(sorted(SUN_NAMED_TIMES))
                       + ", or a clock time HH:MM (local SOLAR time) / "
                       "HH:MMZ (UTC), when the prompt states or clearly "
                       "evokes a time of day.",
    },
}

# The schema is generated FROM the spec's field list; a field added to one
# and not the other fails at import, not at 2 a.m. in a run manifest.
# time_of_day is spec 9's optional, absent-canonical environment field
# (not in FIELD_ORDER, so a spec that omits it keeps its canonical form).
_SPEC_FIELDS = {name for _, name in ScenarioSpec.FIELD_ORDER} | {"time_of_day"}
_unknown = set(FIELD_VALUE_SCHEMAS) - _SPEC_FIELDS
assert not _unknown, f"llm_compiler schema names non-spec fields: {_unknown}"

#: Hard cap on cameras per response, enforced in parsing like MAX_QUESTIONS.
MAX_CAMERAS = 4

#: Value schema per LLM-settable CAMERA field: the view, the lens, the
#: capture schedule, the aircraft-relative placement of a following view
#: and its aim. Placement is in the primary aircraft's heading frame
#: (the -chase= convention), every value provenanced like any field; the
#: system prompt carries the calibrated per-airframe chase table so the
#: model scales "close behind" to the airframe instead of guessing.
#: World-anchored placement (scene / geographic) stays with YAML and the
#: review table: the model is never handed coordinates to invent.
CAMERA_FIELD_VALUE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "preset": {"type": "string", "enum": list(CAMERA_PRESETS)},
    "focal_length_mm": {"type": "number", "description": "millimetres"},
    "capture_count": {
        "type": "number",
        "description": "exact number of images to capture (whole number)",
    },
    "period_s": {"type": "number",
                 "description": "seconds between captures"},
    "offset_forward_m": {"type": "number",
                         "description": "metres ahead (+) / behind (-) of "
                                        "the primary along its heading "
                                        "(chase and wingman only)"},
    "offset_right_m": {"type": "number",
                       "description": "metres right (+) / left (-) of the "
                                      "primary (chase and wingman only)"},
    "offset_up_m": {"type": "number",
                    "description": "metres above (+) / below (-) the "
                                   "primary (chase and wingman only)"},
    "aim_mode": {"type": "string", "enum": ["aircraft", "bearing"],
                 "description": "aircraft = look at the primary; bearing = "
                                "look along aim_bearing_deg / "
                                "aim_elevation_deg"},
    "aim_bearing_deg": {"type": "number",
                        "description": "degrees true the camera looks along"},
    "aim_elevation_deg": {"type": "number",
                          "description": "degrees above (+) / below (-) the "
                                         "horizon"},
}

#: Fields that only mean something on a following (offset) view, and
#: fields the cockpit view cannot honour (it looks where the nose does).
_OFFSET_CAMERA_FIELDS = ("offset_forward_m", "offset_right_m", "offset_up_m")
_AIM_CAMERA_FIELDS = ("aim_mode", "aim_bearing_deg", "aim_elevation_deg")

#: The camera's moves over the clip: the regex compiler's own keyframe
#: shapes, named. Not a CameraSpec field (the keyframes are), so it sits
#: beside CAMERA_FIELD_VALUE_SCHEMAS rather than in it.
CAMERA_MOVES_KEY = "moves"
CAMERA_MOVES_VALUE_SCHEMA: Dict[str, Any] = {
    "type": "array", "items": {"type": "string", "enum": list(MOVE_KINDS)},
    "description": "camera moves over the whole clip",
}

# Same generated-not-hand-copied discipline: the camera schema is tied
# to CameraSpec's own field list at import time.
_CAMERA_FIELDS = set(CameraSpec.FIELD_ORDER)
_unknown_camera = set(CAMERA_FIELD_VALUE_SCHEMAS) - _CAMERA_FIELDS
assert not _unknown_camera, (
    f"llm_compiler camera schema names non-camera fields: "
    f"{_unknown_camera}")

#: Spec 8 (contracts §2.2): the traffic fields the model may write --
#: the airframe (the one field with no default), the track and the
#: range; the livery stays with YAML. Bounded by MAX_TRAFFIC entries.
TRAFFIC_FIELD_VALUE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "aircraft": {"type": "string", "enum": list(AIRCRAFT_MODELS)},
    "track": {"type": "string", "enum": list(TRAFFIC_TRACKS)},
    "range_m": {"type": "number",
                "description": "metres from the primary aircraft"},
}
_unknown_traffic = set(TRAFFIC_FIELD_VALUE_SCHEMAS) - set(TrafficSpec.FIELD_ORDER)
assert not _unknown_traffic, (
    f"llm_compiler traffic schema names non-traffic fields: "
    f"{_unknown_traffic}")

#: Spec 8 (contracts §5.3): the policy leaves the model may write, a
#: deliberately hand-listed subset of the sampler's POLICY_LEAVES (the
#: livery and wind-direction leaves stay with YAML), each value the
#: distribution leaf itself in the documented forms. Bounded: the
#: schema per leaf admits only that leaf's forms and vocabulary.
LLM_RANDOMIZATION_LEAVES: Tuple[str, ...] = (
    "location", "weather_date", "hour_local", "visibility_km", "cloud_cover",
    "precipitation", "wind_speed_kt", "turbulence", "surface", "aircraft",
    "traffic_count",
)
LLM_RANDOMIZATION_CAMERA_LEAVES: Tuple[str, ...] = (
    "preset", "focal_length_mm", "offset_jitter_m",
)
# The same generated-not-hand-copied discipline as the camera schema:
# a leaf listed here that the sampler does not know fails at import.
_unknown_policy = set(LLM_RANDOMIZATION_LEAVES) - set(POLICY_LEAVES)
assert not _unknown_policy, (
    f"llm_compiler randomization schema names leaves the sampler lacks: "
    f"{_unknown_policy}")
_unknown_policy_camera = (set(LLM_RANDOMIZATION_CAMERA_LEAVES)
                          - set(POLICY_CAMERA_LEAVES))
assert not _unknown_policy_camera, (
    f"llm_compiler randomization camera schema names leaves the sampler "
    f"lacks: {_unknown_policy_camera}")

_NUMBER_PAIR = {"type": "array", "items": {"type": "number"},
                "minItems": 2, "maxItems": 2}
_FORM_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "choice": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "uniform": _NUMBER_PAIR, "loguniform": _NUMBER_PAIR, "beta": _NUMBER_PAIR,
    "normal": {"type": "object", "additionalProperties": False,
               "required": ["sigma"],
               "properties": {"mean": {"type": "number"},
                              "sigma": {"type": "number"}}},
    "lognormal": {"type": "object", "additionalProperties": False,
                  "required": ["median", "sigma"],
                  "properties": {"median": {"type": "number"},
                                 "sigma": {"type": "number"}}},
    "weibull": {"type": "object", "additionalProperties": False,
                "required": ["k", "lambda"],
                "properties": {"k": {"type": "number"},
                               "lambda": {"type": "number"}}},
    "poisson": {"type": "number"},
    "uniform_dates": {"type": "array", "items": {"type": "string"},
                      "minItems": 2, "maxItems": 2,
                      "description": "[\"YYYY-MM-DD\", \"YYYY-MM-DD\"]"},
}


def _leaf_value_schema(entry: Dict[str, Any], name: str) -> Dict[str, Any]:
    """One policy leaf's value: an object naming exactly one of the
    leaf's admitted distribution forms, plus its modifiers."""
    properties: Dict[str, Any] = {}
    for form in entry["forms"]:
        schema = json.loads(json.dumps(_FORM_SCHEMAS[form]))
        if form == "choice":
            words = entry.get("words")
            if name == "location":
                words = tuple(LOCATIONS) + tuple(LOCATION_RANGES)
            if words:
                schema["items"] = {"type": "string", "enum": list(words)}
        properties[form] = schema
    if "choice" in entry["forms"]:
        properties["weights"] = {"type": "array", "items": {"type": "number"},
                                 "minItems": 1}
    if entry["kind"] in ("number", "integer"):
        properties["clip"] = _NUMBER_PAIR
    if "poisson" in entry["forms"]:
        properties["max"] = {"type": "number"}
    properties["gated_by"] = {"type": "string",
                              "description": "'<leaf> <op> <value>' over a "
                                             "leaf drawn before this one"}
    unit = entry.get("unit")
    return {"type": "object", "additionalProperties": False,
            "properties": properties,
            "description": f"distribution over {name}"
                           + (f" ({unit})" if unit else "")
                           + f"; exactly one of {list(entry['forms'])}"}


RANDOMIZATION_FIELD_VALUE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    name: _leaf_value_schema(POLICY_LEAVES[name], name)
    for name in LLM_RANDOMIZATION_LEAVES
}
RANDOMIZATION_CAMERA_VALUE_SCHEMAS: Dict[str, Dict[str, Any]] = {
    name: _leaf_value_schema(POLICY_CAMERA_LEAVES[name], name)
    for name in LLM_RANDOMIZATION_CAMERA_LEAVES
}
#: The group key of the randomization block (its value is a mapping of
#: camera leaves, applied to every camera).
RANDOMIZATION_GROUP = "cameras"

#: Canonical unit per numeric field -- a redundant "unit" key in a model
#: response is tolerated ONLY when it states exactly this.
CANONICAL_UNITS: Dict[str, str] = {
    "altitude": "m", "airspeed": "kt", "heading": "deg",
    "latitude": "deg", "longitude": "deg", "terrain_elevation": "m",
    "duration": "s", "wind_speed": "kt", "wind_direction": "deg",
}

#: One clarifying question: an id the answer round refers back to, the
#: question itself, and concrete options (the UI always also allows
#: free text; options are never a closed set).
QUESTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "question", "options"],
    "properties": {
        "id": {"type": "string"},
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"},
                    "minItems": 1},
    },
}

RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fields", "notes", "questions"],
    "properties": {
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: _field_schema(value_schema)
                for name, value_schema in FIELD_VALUE_SCHEMAS.items()
            },
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Prompt content the schema cannot express.",
        },
        "questions": {
            "type": "array",
            "items": QUESTION_SCHEMA,
            "maxItems": MAX_QUESTIONS,
            "description": "Clarifying questions; [] when nothing needs "
                           "asking. One round only.",
        },
        "cameras": {
            "type": "array",
            "maxItems": MAX_CAMERAS,
            "description": "Cameras the prompt asks for; [] when no "
                           "camera or capture language appears.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    **{name: _field_schema(value_schema)
                       for name, value_schema
                       in CAMERA_FIELD_VALUE_SCHEMAS.items()},
                    CAMERA_MOVES_KEY: _field_schema(CAMERA_MOVES_VALUE_SCHEMA),
                },
            },
        },
        "randomization": {
            "type": "object",
            "additionalProperties": False,
            "description": "The variation the prompt asks for, one entry "
                           "per policy leaf; {} when nothing is to vary.",
            "properties": {
                **{name: _field_schema(value_schema)
                   for name, value_schema
                   in RANDOMIZATION_FIELD_VALUE_SCHEMAS.items()},
                RANDOMIZATION_GROUP: _field_schema({
                    "type": "object", "additionalProperties": False,
                    "description": "camera leaves, applied to every camera",
                    "properties": dict(RANDOMIZATION_CAMERA_VALUE_SCHEMAS),
                }),
            },
        },
        "traffic": {
            "type": "array",
            "maxItems": MAX_TRAFFIC,
            "description": "Other aircraft the prompt asks to fly beside "
                           "the primary; [] when it names none.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["aircraft"],
                "properties": {
                    name: _field_schema(value_schema)
                    for name, value_schema
                    in TRAFFIC_FIELD_VALUE_SCHEMAS.items()
                },
            },
        },
    },
}

def _locations_block() -> str:
    """The world the system can actually render, generated from LOCATIONS.

    Generated, never hand-copied (the schema's own discipline): a bake added
    to ``core.terrain.glo30.LOCATIONS`` appears here on the next import or
    the import-time assert above fails.
    """
    lines = ["Real terrain bakes -- the ONLY named places that render real "
             "ground (Copernicus GLO-30 + satellite imagery):"]
    for key, location in LOCATIONS.items():
        aliases = ", ".join(LOCATION_ALIASES[key])
        lines.append(
            f'- {key} ({location.title}; names that mean this place: '
            f'{aliases}): latitude {location.origin_lat}, longitude '
            f'{location.origin_lon}, terrain_elevation '
            f'{LOCATION_TERRAIN_ELEVATION_M[key]:g}')
    # A worked example, generated from the first bake: naming a listed
    # place must set ALL THREE fields, and smaller models in particular
    # follow the example where they skim the rule.
    key, location = next(iter(LOCATIONS.items()))
    lines.append(
        f'Example: a prompt (or a clarifying answer) naming the {key} sets '
        f'ALL THREE fields together -- latitude {location.origin_lat} '
        f'(inferred), longitude {location.origin_lon} (inferred), '
        f'terrain_elevation {LOCATION_TERRAIN_ELEVATION_M[key]:g} '
        f'(inferred), each with the place name in "from" -- never just one '
        f'of them.')
    lines.append(
        'Any OTHER real place: never invent coordinates. Ask ONE clarifying '
        'question for latitude/longitude instead -- explicit coordinates '
        '(from the prompt or the answer, source "user") are fetched and '
        'baked on demand from the same verified GLO-30 pipeline.')
    return "\n".join(lines)


def _chase_table_block() -> str:
    """The calibrated chase framing per airframe, GENERATED from
    :data:`core.scenario.camera.CHASE_OFFSETS` so the prompt and the
    renderer's own framing cannot drift apart."""
    from ..scenario.camera import CHASE_OFFSETS, FALLBACK_CHASE_OFFSET

    rows = [f"    {name}: D = {abs(f):g} m behind, {u:g} m up"
            for name, (f, _, u) in CHASE_OFFSETS.items()]
    f, _, u = FALLBACK_CHASE_OFFSET
    rows.append(f"    any other airframe: about {abs(f):g} m behind, "
                f"{u:g} m up")
    return "\n".join(rows)


def _randomization_block() -> str:
    """The randomisation paragraph, generated from the deterministic
    compiler's RANDOMIZATION_FAMILIES (the control) and the sampler's
    ranges -- never hand-copied."""
    lines = ['Randomisation ("randomization" is a top-level object beside '
             '"fields"; {} when the prompt asks for NOTHING to vary):',
             '- A prompt that asks to VARY something writes one entry per '
             'policy leaf, {"value": <distribution leaf>, "source", "from"}, '
             'the value being the leaf itself in one of its documented '
             'forms. The documented phrases and the leaves they mean (the '
             'deterministic vocabulary; write these EXACT leaves for these '
             'phrases):']
    phrases = {"weather": "varied weather", "times_of_day": "different times "
               "of day", "dawn_dusk": "dawn and dusk only",
               "lighting": "varied lighting", "traffic": "mixed traffic",
               "viewpoints": "random viewpoints", "seasons": "different seasons"}
    for family, leaves in RANDOMIZATION_FAMILIES.items():
        lines.append(f'  "{phrases[family]}" -> {json.dumps(leaves)}')
    ranges = ", ".join(sorted(LOCATION_RANGES))
    lines.append('  "across the Rockies" / "over the Alps" -> {"location": '
                 '{"choice": ["rockies"]}} -- range names: ' + ranges + '; '
                 'bake names: ' + ", ".join(LOCATIONS) + '. A range with no '
                 'bake is refused BY NAME downstream; write it anyway.')
    lines.append('- hour_local is local mean time; its choice form names '
                 'windows: ' + ", ".join(f"{k} {v[0]:g}-{v[1]:g} h"
                                         for k, v in HOUR_WINDOWS.items()) + '.')
    lines.append('- A leaf is written ONLY for something the prompt asks to '
                 'vary; a fixed value ("at dawn", "in rain") is a "fields" '
                 'entry or a note, never a leaf. Never vary a field the '
                 'prompt states.')
    lines.append('- A variation the leaves cannot express ("vary the moon '
                 'phase") goes to "notes" verbatim; the deterministic '
                 'vocabulary refuses it by name.')
    return "\n".join(lines)


#: The response's top-level keys, in the schema's own order. The system
#: prompt's shape sentence is GENERATED from this so the two cannot
#: drift: the prompt said "three keys" for a whole phase after
#: "cameras" became the fourth (Phase 1 initial run report).
RESPONSE_TOP_LEVEL_KEYS: Tuple[str, ...] = tuple(RESPONSE_SCHEMA["properties"])
_COUNT_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                7: "seven", 8: "eight", 9: "nine"}


def response_shape_sentence(keys: Tuple[str, ...] = RESPONSE_TOP_LEVEL_KEYS) -> str:
    """The one sentence in the system prompt that states the top-level
    shape, written from the schema's key list."""
    quoted = ", ".join(f'"{k}"' for k in keys)
    count = _COUNT_WORDS.get(len(keys), str(len(keys)))
    others = [k for k in keys if k != "fields"]
    others_quoted = (", ".join(f'"{k}"' for k in others[:-1])
                     + f' and "{others[-1]}"')
    example = ", ".join(
        '"fields": {"<field name>": {"value": ..., "source": "...", '
        '"from": "..."}, ...}' if k == "fields" else f'"{k}": [...]'
        for k in keys)
    return (f"Respond with EXACTLY this top-level shape -- {count} keys "
            f"({quoted}), no others:\n{{{example}}}\n{others_quoted} are "
            f'TOP-LEVEL keys beside "fields", never inside\n"fields"; '
            f'"fields" contains ONLY schema field names.')


SYSTEM_PROMPT = """\
You are the scene DIRECTOR for a flight-simulation compiler. Turn the
prompt into a COHERENT scene: fill every field the prompt justifies --
aircraft, place, altitude, airspeed, heading, wind speed AND direction,
turbulence, surface, weather event, date, time of day -- so that the
fields agree with each other and with what the prompt evokes. Every value you write
declares how it was chosen; a guess you do not declare is the one
failure this protocol cannot forgive.

__RESPONSE_SHAPE__ Each field object
carries EXACTLY value/source/from -- no "unit", no extra keys. "from" is
ONLY the quoted prompt phrase, no commentary around it. A value is never
null, and a field is never written just to state absence ("none",
"unspecified", "no X mentioned") -- omit it instead.

The three sources you may claim:
- "user": the prompt states it explicitly ("250 kt" -> airspeed 250).
- "inferred": the documented vocabulary maps the prompt's own phrase
  ("strong wind" -> wind_speed 25; the mappings below are the control).
- "model": YOUR interpretation, where the prompt implies a value neither
  stated nor in the vocabulary. Allowed and encouraged -- "treetop
  level" -> altitude 150, "screaming along" -> a high fraction of that
  airframe's envelope -- but "from" MUST quote the prompt phrase you are
  interpreting. Prefer a vocabulary word where one exists; go numeric
  only where vocabulary cannot express the implication.
A field the prompt gives NO basis for at all is OMITTED: the documented
defaults and the deterministic planners fill it. OMISSION IS THE ONLY
WAY to say "not specified" -- NEVER write null, "none" or an empty
value into a field (surface has no "none" word: unspecified ground
cover means the field is absent; an unknown location means latitude/
longitude/terrain_elevation are absent, never null). Mountainous
terrain is terrain_elevation, not a surface class. Downstream planners
may move "model" values into the flyable envelope exactly as they move
defaults; "user" values are never moved -- infeasible ones are refused
by name, which is the designed path.

Coherence rules:
- Fields must agree ACROSS the scene, each row quoting its own phrase:
  "storm chasing in a small plane over Kansas" -> c172p (small plane) +
  flint_hills (Kansas) + low altitude (chasing) + weather_event
  thunderstorm (storm) + strong wind + heading toward the activity.
  Never a coherent-sounding contradiction (a desert surface on an ocean
  prompt; a jet for "puttering around").
- Do not judge feasibility. If the prompt commands something impossible,
  extract it literally -- the validator refuses it by name. Never soften
  or "fix" a stated number.

Extraction rules:
- Canonical units only: metres for altitude/terrain elevation, knots for
  speeds, degrees for angles, seconds for duration. Convert stated units
  (feet, minutes, flight levels) and keep the original phrase in "from".
- airspeed_kind: set ONLY when the prompt says "true airspeed"/"TAS".
  Never guess it -- calibrated is the default and the render host can
  honour nothing else.
- Aircraft with real 3-D models: B747, A320, c172p and A4 -- prefer
  these for GUESSES ("small plane" -> c172p, "airliner/jet" -> A320 or
  B747). A4 is the Douglas A-4 Skyhawk (a single-seat carrier attack
  jet): "a4", "A-4", "Skyhawk" or "A-4E/F/G" ALWAYS mean A4, never f15
  or f16. 737, global5000, f15 and f16 have real flight physics but no
  3-D model: use them ONLY when the prompt names them (the render will
  refuse them with the reason; placeholder airframes never render).
- Vague wind strength maps as: light/gentle 8 kt, breezy 12 kt,
  moderate 15 kt, gusty 18 kt, strong/stiff/rough 25 kt,
  severe/gale/violent/howling 40 kt. "rough"/"turbulent" wind implies
  both a strong wind (25 kt) and moderate turbulence unless stated
  otherwise.
- Turbulence words: smooth/calm -> none, bumpy/choppy/mild -> light,
  rough (air) -> moderate, violent/heavy -> severe.
- Relative wind ("headwind", "crosswind") is a bearing offset from the
  aircraft heading (head 0, cross 90, tail 180), meteorological
  convention (the bearing the wind is FROM).
- Ground cover maps to the surface vocabulary: grasslands/prairie/plains
  -> "grassland", desert/dunes -> "desert", ocean/sea/open water ->
  "ocean", forest/woods -> "forest", city/urban/downtown -> "city".
  Each class is a documented roughness + thermal model; ground cover the
  vocabulary lacks (swamp, tundra, ice shelf) goes to "notes", never to
  the nearest-looking class.
- Anything the schema cannot express -- unknown aircraft, cinematic
  language, weather the vocabulary lacks -- goes into "notes" verbatim,
  never guessed into a field.

Cameras ("cameras" is a top-level list beside "fields"; [] when the
prompt has no camera or capture language):
- Named views map to presets: chase (following), wingman (formation),
  tower / "from the tower", ground / "ground observer", cockpit /
  "over the shoulder". Each camera entry carries provenanced fields
  exactly like "fields": preset, focal_length_mm, capture_count,
  period_s, offset_forward_m, offset_right_m, offset_up_m, aim_mode,
  aim_bearing_deg, aim_elevation_deg, moves -- nothing else.
- An exact image count ("50 images/frames/stills") is capture_count,
  source "user". Lens words: ultra wide -> 16 mm, wide angle -> 24 mm,
  telephoto / long lens -> 85 mm, super telephoto -> 200 mm (inferred);
  "<n> mm lens" is user.
- Placement of a chase or wingman view is an offset in the PRIMARY
  aircraft's heading frame: offset_forward_m (negative = behind),
  offset_right_m (negative = left), offset_up_m (negative = below).
  Write offsets ONLY when the prompt places the camera ("low and behind",
  "off the left wing", "from above", "300 m back"); otherwise omit them
  and the calibrated framing applies. Scale every unstated distance to
  the airframe from its calibrated chase framing D (behind, up):
__CHASE_TABLE__
  "close" ~0.6 D, "far" ~4 D, "very far" ~10 D; "behind" -> forward -D
  with up as calibrated; a side view -> right +-D; "above"/"overhead"
  -> up D (combined with behind: up ~D/2); "below" -> negative up. A
  stated distance ("300 m", "500 ft") is user and always wins; a
  direction word scaled from the table is inferred.
- Aim: omit (the camera looks at the primary) unless the prompt points
  the camera elsewhere: "looking north/east/south/west" -> aim_mode
  "bearing", aim_bearing_deg 0/90/180/270; "looking ahead" -> the
  heading; aim_elevation_deg "down at the ground" -90, "down" -30, "at
  the horizon" 0. Never invent the bearing of a feature you were not
  given; keep the aim on the aircraft and put the feature in "notes".
  The cockpit view takes no aim and no offset.
- Moves over the clip ("moves", a list): "zoom in" zoom_in, "zoom out"
  zoom_out, "push in"/"move closer" push_in, "pull back"/"pull away"
  pull_back, "orbit"/"circle around" orbit. Push, pull and orbit need a
  chase or wingman view; zoom works on every view.
- When the prompt implies imagery ("photograph", "capture", "images
  of") but names NO viewpoint, you MAY ask one camera-intent question
  (which view?) under the same one-round/three-question caps. A prompt
  with no camera language at all gets no camera and no question: the
  documented default view applies.

Traffic ("traffic" is a top-level list beside "fields"; [] when the
prompt names no second aircraft):
- "with an A320 crossing 400 m ahead", "a 737 in formation", "a
  Cessna overtaking" -> one entry per other aircraft, at most two,
  each carrying provenanced fields exactly like "fields": aircraft
  (REQUIRED, the airframe named), track (formation | crossing |
  overtaking, when the prompt says how it flies), range_m (metres
  from the primary, when stated). Nothing else; livery and geometry
  are not yours to invent. The PRIMARY aircraft stays in "fields".
- A second aircraft named without a track is still a traffic entry
  (the documented default track applies); a formation or a crowd the
  list cannot hold ("a squadron", "busy airspace") goes to "notes".

""" + _randomization_block() + """

""" + _locations_block() + """

Geography rules:
- A prompt naming a listed place (by key or any of its names) sets latitude,
  longitude and terrain_elevation EXACTLY to that place's listed values --
  never rounded, never adjusted -- source "inferred" with the place name in
  "from". The exact coordinates are what lands the scenario on the real bake.
- Coordinates NEVER carry source "model": a listed place is "inferred",
  stated coordinates are "user", and any model-sourced coordinate is
  DISCARDED as an invented place.
- A ground-cover word that is ALSO a listed place's alias ("the
  prairie" -> flint_hills) sets BOTH: the surface class AND the place's
  exact coordinates. Ground cover alone never suppresses a place the
  list can render.
- You MAY choose a listed bake as a declared guess (source "model",
  EXACT listed coordinates, quoting the phrase that guided it) when the
  prompt strongly evokes one: desert/canyon -> grand_canyon,
  prairie/plains -> flint_hills, valley -> yosemite, volcano -> fuji.
  When nothing evokes a place, leave the location fields absent -- the
  deterministic scene planner places unlocated scenes on a fitting
  bake; that is not your job to force.
- A named place NOT in the list: NEVER invent coordinates. Ask which listed
  place (or the generic ridge) fits, or record the place name verbatim in
  "notes". Coordinates you were not given do not exist.
- "mountains"/"alpine"/"ridge" with no name and no numbers: set
  terrain_elevation 2000, inferred (the generic-ridge fallback) -- and this
  is the canonical case for a clarifying question ("which mountains?") with
  the listed real places plus "a generic ridge" as the options.
- A prompt that STATES a terrain height ("over 2000 m terrain") is
  determined: generic ridge at that stated elevation, NO question.

Clarifying questions:
- Guess freely in DECLARED space; ask (in "questions") ONLY when a wrong
  guess would misrepresent what the clip IS: which mountains when
  mountains are unnamed, which aircraft when nothing in the prompt
  constrains the choice. At most 3 questions, one round ever.
- NEVER ask about anything the rules above already map ("windy" -> 25 kt is
  the documented inference, not a question), anything a declared "model"
  guess covers honestly (altitude, speed, sun, heading), or where the
  documented default is fine (duration, integration rate).
- A prompt that mentions NO place gets NO location question: flat
  default ground IS the documented default. Ask about location only
  when the prompt implies terrain ("mountains", a named place) without
  determining it. Never ask for a heading.
- Each question carries an id, the question text, and concrete options (the
  user may also answer free-text). Fields you ARE confident of must still
  arrive in "fields" in the same response -- a question round is not an
  empty round; every non-question field is extracted as usual.
- "questions" is [] when nothing needs asking.
- When the conversation already contains your questions and the user's
  answers: produce the final complete response with "questions": [] --
  never ask again. A field decided by an answer is source "user" with
  "from" recording both, exactly this shape:
  answer to "<question>": "<answer>"
  A field read from the original prompt keeps its ordinary user/inferred
  tag. An answer that names a listed place follows the geography rules
  (exact listed coordinates).
"""

SYSTEM_PROMPT = SYSTEM_PROMPT.replace("__RESPONSE_SHAPE__",
                                      response_shape_sentence())
assert "__RESPONSE_SHAPE__" not in SYSTEM_PROMPT
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("__CHASE_TABLE__", _chase_table_block())
assert "__CHASE_TABLE__" not in SYSTEM_PROMPT
for _key in RESPONSE_TOP_LEVEL_KEYS:
    assert f'"{_key}"' in SYSTEM_PROMPT, (
        f"the system prompt never names top-level key {_key!r}")
assert f"{_COUNT_WORDS[len(RESPONSE_TOP_LEVEL_KEYS)]} keys" in SYSTEM_PROMPT
del _key


# -- parsing: strict, loud, never patched ---------------------------------

def _fail(reason: str) -> "LLMCompileError":
    return LLMCompileError(
        f"the language model's response was rejected: {reason}. The spec was "
        f"not built; re-run, rephrase, or use the offline compiler.")


def _named_aircraft(prompt: str):
    """Every aircraft the prompt states by an AIRCRAFT_WORDS phrase (a
    variant suffix like A-4E or c172p allowed), as (phrase, model) in the
    order they appear; [] when none."""
    import re

    from .compiler import AIRCRAFT_WORDS

    text = prompt.lower()
    found = {}
    for phrase, model in AIRCRAFT_WORDS:
        match = re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![0-9])", text)
        if match and (model not in found or match.start() < found[model][0]):
            found[model] = (match.start(), phrase)
    return [(phrase, model) for model, (_, phrase) in
            sorted(found.items(), key=lambda item: item[1][0])]


def _parse_payload(text: str, *, allow_questions: bool = True) -> Dict[str, Any]:
    """Parse the model's JSON strictly against the schema's intent.

    The API already constrains the shape, but this module does not trust the
    transport: everything is re-checked here so a malformed response -- from
    a mock, a cached file, or a future API change -- fails identically.
    ``allow_questions=False`` is the answer round: a model that asks again
    is rejected by name, which is what keeps the protocol to one round
    without any server-side state machine.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _fail(f"not valid JSON ({exc})") from None
    if not isinstance(payload, dict):
        raise _fail("top level is not an object")
    # An ABSENT notes/questions key carries exactly the claim an empty
    # list does, and OpenAI-compatible endpoints receive the schema as
    # guidance rather than grammar (their strict mode rejects this
    # schema's optional fields -- measured: gpt-4.1-mini omits the empty
    # lists). Defaulting the two list keys keeps every real rail -- the
    # fields vocabulary, types, sources and bounds below -- exactly as
    # strict as before; any OTHER unknown or missing key still refuses.
    payload.setdefault("notes", [])
    payload.setdefault("questions", [])
    # An absent cameras key claims exactly what [] does (no camera
    # language) -- the same OpenAI-compat tolerance the two list keys
    # above get; every per-entry rail below stays fully strict.
    payload.setdefault("cameras", [])
    # Spec 8: an absent randomization block claims what {} does, and an
    # absent traffic list what [] does.
    payload.setdefault("randomization", {})
    payload.setdefault("traffic", [])
    if set(payload) != set(RESPONSE_TOP_LEVEL_KEYS):
        raise _fail(f"top-level keys {sorted(payload)} != "
                    f"{sorted(RESPONSE_TOP_LEVEL_KEYS)}")
    fields, notes = payload["fields"], payload["notes"]
    if not isinstance(fields, dict):
        raise _fail("'fields' is not an object")
    if not (isinstance(notes, list)
            and all(isinstance(n, str) for n in notes)):
        raise _fail("'notes' is not a list of strings")
    # A model that nests the camera list one level down, under "fields",
    # has said something unambiguous in the wrong place (measured on the
    # keyless tier: the whole response was refused as "unknown field
    # 'cameras'" and the page fell back to the regex compiler). A LIST
    # of camera mappings there is lifted to where the schema puts it,
    # recorded in the notes; anything else under that name still
    # refuses as the unknown field it is, and every per-camera rail
    # below stays as strict as before.
    # The same holds for traffic (a list) and randomization (a mapping),
    # and for the shapes gpt-4.1-mini was measured to send on the relay
    # (2026-10-01, the owner's machine: "unknown field 'cameras'" with the
    # lift above in place): the section wrapped as {"value": ...}, a single
    # camera mapping instead of a list, or the section stated BOTH under
    # fields and at the top level. The top-level statement wins; a nested
    # copy is lifted only into an empty slot, otherwise dropped -- either
    # way recorded in the notes. Nothing is guessed: the lifted entries
    # face every per-entry rail below exactly as top-level ones do.
    for section, kind in (("cameras", list), ("traffic", list),
                          ("randomization", dict)):
        if section not in fields:
            continue
        nested = fields.pop(section)
        if isinstance(nested, dict) and "value" in nested \
                and isinstance(nested["value"], kind):
            nested = nested["value"]
        if (kind is list and isinstance(nested, dict)
                and not {"value", "source", "from"} & set(nested)):
            nested = [nested]           # one entry stated without its list
        if not isinstance(nested, kind):
            # A provenanced scalar ({"value": "chase", ...}) is not a
            # camera list: the unknown field it is, by name, as before.
            raise _fail(f"unknown field {section!r}")
        if not payload[section]:
            payload[section] = nested
            notes.append(f"the model nested {section!r} under 'fields'; lifted "
                         f"to the top-level {section} (schema position)")
        else:
            notes.append(f"the model stated {section!r} both under 'fields' and "
                         f"at the top level; the top-level one is used")

    questions = payload["questions"]
    if not isinstance(questions, list):
        raise _fail("'questions' is not a list")
    if questions and not allow_questions:
        raise _fail("the model asked questions in the answer round; the "
                    "protocol allows exactly one question round")
    if len(questions) > MAX_QUESTIONS:
        raise _fail(f"{len(questions)} questions exceed the cap of "
                    f"{MAX_QUESTIONS}")
    for question in questions:
        if not (isinstance(question, dict)
                and set(question) == {"id", "question", "options"}):
            raise _fail("each question must carry exactly id/question/options")
        if not (isinstance(question["id"], str) and question["id"].strip()):
            raise _fail("a question has no id")
        if not (isinstance(question["question"], str)
                and question["question"].strip()):
            raise _fail(f"question {question['id']!r} has no text")
        options = question["options"]
        if not (isinstance(options, list) and options
                and all(isinstance(o, str) and o.strip() for o in options)):
            raise _fail(f"question {question['id']!r} has no usable options "
                        f"(a non-empty list of strings is required)")

    # A null value is JSON's spelling of omission (measured: gpt-4.1-mini
    # writes "latitude": null for an unknown place despite the rules).
    # Dropping the ENTRY carries exactly the claim omission does -- the
    # documented default -- while every actually-claimed value below still
    # faces the full vocabulary/type/source checks.
    for name in [n for n, e in fields.items()
                 if isinstance(e, dict) and e.get("value") is None]:
        del fields[name]
    # Coordinates are never INVENTED into a spec -- but the director may
    # CHOOSE a listed bake as a declared guess ("scene-setting": a windy
    # evocative prompt lands on real terrain instead of a featureless
    # slab). The line: a model-sourced latitude/longitude pair is kept
    # ONLY when it sits exactly on a listed bake's origin (the world the
    # system can actually render); anything else is an invented place and
    # is dropped like a null (measured: gpt-4.1-mini invents Sahara
    # coordinates for placeless prompts).
    lat_entry, lon_entry = fields.get("latitude"), fields.get("longitude")

    def _model_sourced(entry):
        return isinstance(entry, dict) and entry.get("source") == "model"

    if _model_sourced(lat_entry) or _model_sourced(lon_entry):
        on_listed_origin = False
        try:
            lat, lon = float(lat_entry["value"]), float(lon_entry["value"])
            on_listed_origin = any(
                abs(lat - loc.origin_lat) <= 0.05
                and abs(lon - loc.origin_lon) <= 0.05
                for loc in LOCATIONS.values())
        except (TypeError, KeyError, ValueError):
            on_listed_origin = False
        if not on_listed_origin:
            for name in ("latitude", "longitude", "terrain_elevation"):
                if _model_sourced(fields.get(name)):
                    del fields[name]
    # A DATE is data, not vibes: the prompt rules already say never
    # invent one, and the mechanical rail backs them up (measured:
    # gpt-4.1-mini wrote weather_date 2023-06-01 from the word
    # "evening", which would pull a real day's ERA5 reanalysis the user
    # never asked about). A model-sourced date is dropped as invented;
    # stated dates arrive as "user"/"inferred" and stand.
    if _model_sourced(fields.get("weather_date")):
        del fields["weather_date"]
    for name, entry in fields.items():
        if name not in FIELD_VALUE_SCHEMAS:
            raise _fail(f"unknown field {name!r}")
        if not isinstance(entry, dict):
            raise _fail(f"field {name!r} must carry exactly value/source/from")
        # A redundant "unit" key stating the CANONICAL unit is a true
        # statement, tolerated and dropped (measured: gpt-4.1-mini writes
        # it at temp 0 despite the rules); any OTHER unit is a real claim
        # of a non-canonical unit and refuses loudly.
        if set(entry) == {"value", "source", "from", "unit"}:
            if entry["unit"] != CANONICAL_UNITS.get(name):
                raise _fail(f"field {name!r} claims unit {entry['unit']!r}; "
                            f"canonical is {CANONICAL_UNITS.get(name)!r}")
            entry = {k: v for k, v in entry.items() if k != "unit"}
            fields[name] = entry
        if set(entry) != {"value", "source", "from"}:
            raise _fail(f"field {name!r} must carry exactly value/source/from")
        if entry["source"] not in ("user", "inferred", "model"):
            raise _fail(f"field {name!r} claims source {entry['source']!r}; "
                        f"only 'user', 'inferred' or 'model' may be claimed")
        if not (isinstance(entry["from"], str) and entry["from"].strip()):
            # The load-bearing rail for guesses: a model-sourced value with
            # no declared reason is a SILENT guess, the graded failure the
            # scene director exists to prevent.
            if entry["source"] == "model":
                raise _fail(f"field {name!r} is a model guess with no "
                            f"declared reason; a guess must quote the "
                            f"prompt phrase it interprets")
            raise _fail(f"field {name!r} has no provenance phrase")
        # A field decided by a clarifying answer is the USER speaking: the
        # 'answer to "...": "..."' shape may only carry source "user".
        if entry["from"].strip().startswith("answer to") and entry["source"] != "user":
            raise _fail(f"field {name!r} was filled from a clarifying answer "
                        f"but claims source {entry['source']!r}; an answered "
                        f"field is the user speaking, source 'user'")
        value_schema = FIELD_VALUE_SCHEMAS[name]
        value = entry["value"]
        if value_schema["type"] == "number":
            # bool is an int subclass; a model answering `true` for an
            # altitude must not arrive as 1.0 metres.
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _fail(f"field {name!r} value {value!r} is not a number")
        elif "enum" in value_schema and value not in value_schema["enum"]:
            raise _fail(f"field {name!r} value {value!r} is outside the "
                        f"vocabulary {value_schema['enum']}")
        elif name == "time_of_day":
            # Not an enum (clock times are open), but not free text
            # either: the same parser the deterministic compiler and the
            # render flow use decides, and its canonical spelling is what
            # the spec stores.
            try:
                entry["value"] = canonical_time_of_day(value)
            except ValueError as exc:
                raise _fail(f"field 'time_of_day': {exc}") from None

    # Cameras (Camera Phase 1): a bounded repeated block, every entry
    # facing the same rails the scalar fields face -- unknown camera
    # fields refuse, sources are claimed from the same three, a model
    # guess must quote its phrase, values face the camera vocabulary.
    cameras = payload["cameras"]
    if not isinstance(cameras, list):
        raise _fail("'cameras' is not a list")
    if len(cameras) > MAX_CAMERAS:
        raise _fail(f"{len(cameras)} cameras exceed the cap of "
                    f"{MAX_CAMERAS}")
    for index, block in enumerate(cameras):
        if not isinstance(block, dict) or not block:
            raise _fail(f"camera {index} must be an object of camera "
                        f"fields")
        for name in [n for n, e in block.items()
                     if isinstance(e, dict) and e.get("value") is None]:
            del block[name]
        for name, entry in block.items():
            if name not in CAMERA_FIELD_VALUE_SCHEMAS \
                    and name != CAMERA_MOVES_KEY:
                raise _fail(f"camera {index}: unknown camera field "
                            f"{name!r}")
            if not isinstance(entry, dict) \
                    or set(entry) != {"value", "source", "from"}:
                raise _fail(f"camera {index} field {name!r} must carry "
                            f"exactly value/source/from")
            if entry["source"] not in ("user", "inferred", "model"):
                raise _fail(f"camera {index} field {name!r} claims source "
                            f"{entry['source']!r}; only 'user', "
                            f"'inferred' or 'model' may be claimed")
            if not (isinstance(entry["from"], str)
                    and entry["from"].strip()):
                if entry["source"] == "model":
                    raise _fail(f"camera {index} field {name!r} is a "
                                f"model guess with no declared reason; a "
                                f"guess must quote the prompt phrase it "
                                f"interprets")
                raise _fail(f"camera {index} field {name!r} has no "
                            f"provenance phrase")
            value = entry["value"]
            if name == CAMERA_MOVES_KEY:
                if not isinstance(value, list) \
                        or any(v not in MOVE_KINDS for v in value):
                    raise _fail(f"camera {index} field 'moves' value "
                                f"{value!r} must be a list drawn from "
                                f"{list(MOVE_KINDS)}")
                continue
            value_schema = CAMERA_FIELD_VALUE_SCHEMAS[name]
            if value_schema["type"] == "number":
                if isinstance(value, bool) \
                        or not isinstance(value, (int, float)) \
                        or not math.isfinite(value):
                    raise _fail(f"camera {index} field {name!r} value "
                                f"{value!r} is not a number")
                if name == "capture_count" and float(value) != int(value):
                    raise _fail(f"camera {index}: a capture count of "
                                f"{value!r} is not a whole number of "
                                f"images")
            elif "enum" in value_schema \
                    and value not in value_schema["enum"]:
                raise _fail(f"camera {index} field {name!r} value "
                            f"{value!r} is outside the vocabulary "
                            f"{value_schema['enum']}")

    # -- randomization (spec 8): every rail strict, shape by name ------
    randomization = payload["randomization"]
    if not isinstance(randomization, dict):
        raise _fail("'randomization' is not an object of policy leaves")
    from ..scenario.validate import policy_problems

    for name in [n for n, e in list(randomization.items())
                 if isinstance(e, dict) and e.get("value") is None]:
        del randomization[name]
    for name, entry in randomization.items():
        if name not in RANDOMIZATION_FIELD_VALUE_SCHEMAS \
                and name != RANDOMIZATION_GROUP:
            raise _fail(f"randomization: unknown policy leaf {name!r}; the "
                        f"leaves are {sorted(RANDOMIZATION_FIELD_VALUE_SCHEMAS)}"
                        f" and the group {RANDOMIZATION_GROUP!r}")
        if not isinstance(entry, dict) \
                or set(entry) != {"value", "source", "from"}:
            raise _fail(f"randomization leaf {name!r} must carry exactly "
                        f"value/source/from")
        if entry["source"] not in ("user", "inferred", "model"):
            raise _fail(f"randomization leaf {name!r} claims source "
                        f"{entry['source']!r}; only 'user', 'inferred' or "
                        f"'model' may be claimed")
        if not (isinstance(entry["from"], str) and entry["from"].strip()):
            raise _fail(f"randomization leaf {name!r} has no provenance "
                        f"phrase; a variation must quote the phrase that "
                        f"asked for it")
        value = entry["value"]
        if not isinstance(value, dict) or not value:
            raise _fail(f"randomization leaf {name!r} value must be a "
                        f"distribution mapping")
        if name == RANDOMIZATION_GROUP:
            unknown = set(value) - set(RANDOMIZATION_CAMERA_VALUE_SCHEMAS)
            if unknown:
                raise _fail(f"the randomization block's cameras group names "
                            f"unknown camera leaves {sorted(unknown)}; the "
                            f"leaves are "
                            f"{sorted(RANDOMIZATION_CAMERA_VALUE_SCHEMAS)}")
            for sub, sub_leaf in value.items():
                allowed = RANDOMIZATION_CAMERA_VALUE_SCHEMAS[sub]["properties"] \
                    .get("choice", {}).get("items", {}).get("enum")
                if allowed is not None and isinstance(sub_leaf, dict) \
                        and isinstance(sub_leaf.get("choice"), list):
                    outside = [v for v in sub_leaf["choice"] if v not in allowed]
                    if outside:
                        raise _fail(f"randomization camera leaf {sub!r} choice "
                                    f"{outside} is outside the vocabulary "
                                    f"{allowed}")
        else:
            forms = [f for f in POLICY_LEAVES[name]["forms"] if f in value]
            if len(forms) != 1:
                raise _fail(f"randomization leaf {name!r} must name exactly "
                            f"one of {list(POLICY_LEAVES[name]['forms'])}")
            allowed = RANDOMIZATION_FIELD_VALUE_SCHEMAS[name]["properties"] \
                .get("choice", {}).get("items", {}).get("enum")
            if allowed is not None and isinstance(value.get("choice"), list):
                outside = [v for v in value["choice"] if v not in allowed]
                if outside:
                    raise _fail(f"randomization leaf {name!r} choice "
                                f"{outside} is outside the vocabulary "
                                f"{allowed}")
        problems = policy_problems({name: value})
        if problems:
            raise _fail("randomization leaf of an undocumented form: "
                        + "; ".join(problems))

    # -- traffic (spec 8, contracts §2.2): the same rails as a camera --
    traffic = payload["traffic"]
    if not isinstance(traffic, list):
        raise _fail("'traffic' is not a list")
    if len(traffic) > MAX_TRAFFIC:
        raise _fail(f"{len(traffic)} traffic aircraft exceed the cap of "
                    f"{MAX_TRAFFIC}")
    for index, block in enumerate(traffic):
        if not isinstance(block, dict) or not block:
            raise _fail(f"traffic {index} must be an object of traffic "
                        f"fields")
        for name in [n for n, e in block.items()
                     if isinstance(e, dict) and e.get("value") is None]:
            del block[name]
        if "aircraft" not in block:
            raise _fail(f"traffic {index} names no aircraft; the airframe "
                        f"is the one traffic field with no default")
        for name, entry in block.items():
            if name not in TRAFFIC_FIELD_VALUE_SCHEMAS:
                raise _fail(f"traffic {index}: unknown traffic field "
                            f"{name!r}")
            if not isinstance(entry, dict) \
                    or set(entry) != {"value", "source", "from"}:
                raise _fail(f"traffic {index} field {name!r} must carry "
                            f"exactly value/source/from")
            if entry["source"] not in ("user", "inferred", "model"):
                raise _fail(f"traffic {index} field {name!r} claims source "
                            f"{entry['source']!r}; only 'user', "
                            f"'inferred' or 'model' may be claimed")
            if not (isinstance(entry["from"], str)
                    and entry["from"].strip()):
                raise _fail(f"traffic {index} field {name!r} has no "
                            f"provenance phrase")
            value_schema = TRAFFIC_FIELD_VALUE_SCHEMAS[name]
            value = entry["value"]
            if value_schema["type"] == "number":
                if isinstance(value, bool) \
                        or not isinstance(value, (int, float)):
                    raise _fail(f"traffic {index} field {name!r} value "
                                f"{value!r} is not a number")
            elif "enum" in value_schema \
                    and value not in value_schema["enum"]:
                raise _fail(f"traffic {index} field {name!r} value "
                            f"{value!r} is outside the vocabulary "
                            f"{value_schema['enum']}")
    return payload


def _overlay(spec: ScenarioSpec, name: str, entry: Dict[str, Any]) -> None:
    """Set one spec field from a parsed model entry, with provenance."""
    source = {"user": Source.USER, "inferred": Source.INFERRED,
              "model": Source.MODEL}[entry["source"]]
    frm = entry["from"].strip()
    value = entry["value"]
    schema = FIELD_VALUE_SCHEMAS[name]
    if schema["type"] == "number":
        value = float(value)
    if name == "turbulence":
        # Same detail the regex compiler attaches: the citation and the W20
        # the label maps to, so "what does moderate mean" stays answerable.
        quantity = Quantity(value=value, source=source, frm=frm,
                            std=TURBULENCE_STD,
                            detail={"W20_kt": TURBULENCE_LABELS[value]})
    else:
        current = getattr(spec, name)
        quantity = Quantity(value=value, unit=current.unit, source=source,
                            frm=frm)
    setattr(spec, name, quantity)


# -- the compiler ---------------------------------------------------------

def compile_prompt_llm(prompt: str, name: Optional[str] = None,
                       client: Any = None,
                       model: str = DEFAULT_MODEL,
                       questions: Optional[Sequence[Dict[str, Any]]] = None,
                       answers: Optional[Sequence[Dict[str, str]]] = None,
                       ) -> LLMCompileResult:
    """Turn a prompt into a spec via the Claude API. Does not run anything.

    ``client`` is an ``anthropic.Anthropic``-compatible object; the suite
    injects a mock here so no test touches the network. Left ``None``, the
    real SDK client is constructed and resolves its key from the
    environment (checked for PRESENCE first so a missing key is a named,
    actionable error rather than a TypeError from client construction).

    ``answers`` makes this the answer round: the conversation becomes the
    original prompt, the model's own ``questions`` (which the caller echoes
    back), and the user's answers -- and a response that asks again is
    rejected. Round-ness is carried entirely by whether ``answers`` was
    supplied; there is no other state.
    """
    if client is None:
        # An explicitly selected alternate provider (FLIGHTSIM_LLM= --
        # e.g. a free local Ollama model) wins over a present Anthropic
        # key: choosing a provider is a statement, not a fallback.
        from .providers import resolve_client

        try:
            resolved = resolve_client()
        except ValueError as exc:      # misconfigured provider, fix named
            raise LLMCompileError(str(exc)) from exc
        if resolved is not None:
            client, provider_model = resolved
            if model == DEFAULT_MODEL:
                model = provider_model
        # Presence check only -- no secret value is read, stored or logged.
        elif "ANTHROPIC_API_KEY" not in os.environ:
            raise LLMCompileError(
                "no LLM provider is configured in this process's "
                "environment, so the LLM compiler is unavailable. In the "
                "environment of the SERVER process -- the flightsim-web "
                "launch.json entry, or the shell that runs uvicorn -- either "
                "set ANTHROPIC_API_KEY (Claude API), or set "
                "FLIGHTSIM_LLM=ollama for a free local model (with the "
                "ollama service running). The offline regex compiler "
                "remains available meanwhile.")
        else:
            try:
                import anthropic
            except ImportError as exc:
                raise LLMCompileError(
                    "the anthropic SDK is not installed; the LLM compiler "
                    "is unavailable. Use the offline regex compiler.") from exc
            client = anthropic.Anthropic()

    answering = answers is not None
    if answering and not questions:
        raise LLMCompileError(
            "answers were supplied without the questions they answer; the "
            "answer round must echo the question round's questions back")

    messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
    if answering:
        # The API-idiomatic shape: the model's question turn re-enters the
        # conversation as an assistant message, the answers as a user one.
        messages.append({"role": "assistant",
                         "content": json.dumps({"questions": list(questions)})})
        messages.append({"role": "user",
                         "content": json.dumps({"answers": list(answers)})})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=messages,
            # A short structured extraction behind a UI button: low effort
            # cuts the interactive latency substantially and this size of
            # task does not need deep reasoning. The schema constraint and
            # the strict parse are the correctness rails either way.
            output_config={"effort": "low",
                           "format": {"type": "json_schema",
                                      "schema": RESPONSE_SCHEMA}},
        )
    except LLMCompileError:
        raise
    except Exception as exc:   # transport/API errors: named, never swallowed
        # The call never reached a model, so nothing was "rejected": the
        # sentence says what happened in words, and the exception's
        # class and text ride in details for a log, not the page.
        raise LLMCompileError(
            UNREACHABLE_SENTENCE, constraint="compile.unreachable",
            details={"error": f"{type(exc).__name__}: {exc}"}) from exc

    if getattr(response, "stop_reason", None) == "refusal":
        raise _fail("the model declined the request (stop_reason=refusal)")
    try:
        text = next(block.text for block in response.content
                    if getattr(block, "type", None) == "text")
    except StopIteration:
        raise _fail("the response carries no text block") from None

    payload = _parse_payload(text, allow_questions=not answering)

    # Defaults come from the regex compiler run on an EMPTY prompt, so an
    # untouched field is bit-identical between the two compilers and the
    # validator cannot judge them differently on shared vocabulary.
    spec = compile_prompt("", name=name or _name_from(prompt.lower()))
    spec.prompt = prompt
    spec.notes = list(payload["notes"])

    for field_name, entry in payload["fields"].items():
        _overlay(spec, field_name, entry)

    # An aircraft the prompt NAMES (the deterministic vocabulary's phrases,
    # whole words) is the user's, not the model's to reinterpret: a model
    # that read "a4" as an F-15 is overruled, and the note says so.
    named = _named_aircraft(prompt)
    if named and str(spec.aircraft.value) not in {model for _, model in named}:
        phrase, model = named[0]
        spec.notes.append(f"the language model chose {spec.aircraft.value!r} but the "
                          f"prompt names {phrase!r}, which is {model}; the named "
                          f"aircraft is used")
        spec.aircraft = Quantity.user(model, frm=phrase)

    # An aircraft the vocabulary LACKS is asked about, as on the regex
    # tier (P2 report, the open LLM-tier finding: the model put "the
    # dragon" in notes and the default B747 flew without a word). When
    # the model chose no aircraft and the prompt names a SPECIFIC
    # subject the vocabulary cannot map, the regex tier's own rails
    # apply: the name is carried as stated and refused by name
    # (aircraft.exists), and the aircraft question is asked -- unless
    # the model asked one, or its three are used. A KIND of aircraft
    # ("an aircraft", "a small plane") stays the model's judgment, as
    # the system prompt words it. The answer round reads the person's
    # answer the regex tier's way when the model leaves it unset again.
    if not named and str(spec.aircraft.source) == "default":
        from .compiler import _answered_aircraft, _named_subject, aircraft_question

        answered = _answered_aircraft(answers) if answering else None
        subject = _named_subject(" ".join(prompt.lower().split()))
        if answered is not None:
            spec.aircraft = answered
        elif subject is not None and not subject[1]:
            spec.aircraft = Quantity.user(subject[0], frm=subject[0])
            asked = aircraft_question(prompt)
            already = any("aircraft" in f"{q['id']} {q['question']}".lower()
                          for q in payload["questions"])
            if (not answering and asked is not None and not already
                    and len(payload["questions"]) < MAX_QUESTIONS):
                payload["questions"].append(asked)
                spec.notes.append(f"the prompt names {subject[0]!r}, which the "
                                  f"aircraft vocabulary does not hold; asked "
                                  f"which aircraft should fly")

    # A heading the prompt STATES ("heading east", "heading 090") is the
    # user's: claimed as a model guess, the terrain planner would re-aim it
    # along the ridge (measured: "heading east" flew 19 deg).
    from .compiler import _heading
    stated = _heading(prompt.lower())
    if str(stated.source) == "user" and (
            str(spec.heading.source) != "user"
            or float(spec.heading.value) != float(stated.value)):
        if float(spec.heading.value) != float(stated.value):
            spec.notes.append(f"the language model chose heading "
                              f"{spec.heading.value} but the prompt says "
                              f"{stated.frm!r}; the stated heading is used")
        spec.heading = stated

    # Cameras overlay AFTER the fields: the default offsets and the
    # world-anchored placements depend on the (possibly model-chosen)
    # aircraft and terrain datum.
    duration_s = float(spec.duration.value)
    model_moves = False
    for index, block in enumerate(payload["cameras"]):
        preset_entry = block.get("preset")
        preset = str(preset_entry["value"]) if preset_entry else "chase"
        camera = CameraSpec.defaulted(
            camera_id=f"camera{index}", preset=preset,
            aircraft=str(spec.aircraft.value),
            terrain_elevation_m=float(spec.terrain_elevation.value),
            frm="camera language in the prompt; documented camera default")
        moves_entry = block.pop(CAMERA_MOVES_KEY, None)
        # A field the view cannot honour is said in the notes by name,
        # never applied where the pose solver would ignore it.
        dropped = [n for n in block
                   if (n in _OFFSET_CAMERA_FIELDS
                       and preset not in ("chase", "wingman"))
                   or (n in _AIM_CAMERA_FIELDS and preset == "cockpit")]
        for name in dropped:
            spec.notes.append(
                f"camera {index} ({preset}): {name} "
                f"{block[name]['value']!r} from {block[name]['from']!r} not "
                f"applied -- "
                + ("only the chase and wingman views follow at an offset"
                   if name in _OFFSET_CAMERA_FIELDS else
                   "the cockpit view looks where the aircraft points"))
            del block[name]
        for name, entry in block.items():
            current = getattr(camera, name)
            value = entry["value"]
            schema = CAMERA_FIELD_VALUE_SCHEMAS[name]
            if schema["type"] == "number":
                value = int(value) if name == "capture_count" \
                    else float(value)
            setattr(camera, name, Quantity(
                value=value, unit=current.unit,
                source={"user": Source.USER, "inferred": Source.INFERRED,
                        "model": Source.MODEL}[entry["source"]],
                frm=entry["from"].strip()))
        # A bearing aim with no bearing looks along the flight path.
        if str(camera.aim_mode.value) == "bearing" \
                and "aim_bearing_deg" not in block:
            camera.plan("aim_bearing_deg",
                        float(spec.heading.value) % 360.0,
                        frm="no bearing stated; the aircraft's heading")
        # Same rule as the regex compiler and the page's picker: a view
        # the model named without a count is the whole clip from that
        # view. A count or a trigger the model DID state is a stated
        # field and is left exactly as it is.
        plan_full_capture(camera, frm="a view named in the prompt with "
                                      "no count captures the whole clip")
        if moves_entry is not None:
            model_moves = True
            phrase = moves_entry["from"].strip()
            apply_moves(camera, [(phrase, kind) for kind
                                 in dict.fromkeys(moves_entry["value"])],
                        duration_s, spec.notes)
        spec.cameras.append(camera)

    # Move words the model left out ("orbit", "zoom in", "pull back") still
    # move the camera: the regex compiler's vocabulary is the control, as
    # for randomization phrases. A move word with no camera earns the
    # documented default view, exactly as on the regex tier.
    stated = [] if model_moves else prompt_moves(prompt)
    if stated and not spec.cameras:
        camera = CameraSpec.defaulted(
            camera_id="camera0", preset="chase",
            aircraft=str(spec.aircraft.value),
            terrain_elevation_m=float(spec.terrain_elevation.value),
            frm="a camera move in the prompt; documented camera default")
        plan_full_capture(camera, frm="a view named in the prompt with "
                                      "no count captures the whole clip")
        spec.cameras.append(camera)
    for camera in spec.cameras:
        apply_moves(camera, stated, duration_s, spec.notes)

    # Spec 8 (contracts §2.2): every traffic aircraft the model named,
    # the documented defaults under the fields it did not state.
    for block in payload["traffic"]:
        aircraft_entry = block["aircraft"]
        entry = TrafficSpec.defaulted(str(aircraft_entry["value"]))
        for name, field_entry in block.items():
            current = getattr(entry, name)
            value = field_entry["value"]
            if TRAFFIC_FIELD_VALUE_SCHEMAS[name]["type"] == "number":
                value = float(value)
            setattr(entry, name, Quantity(
                value=value, unit=current.unit,
                source={"user": Source.USER, "inferred": Source.INFERRED,
                        "model": Source.MODEL}[field_entry["source"]],
                frm=field_entry["from"].strip()))
        spec.traffic.append(entry)

    # Spec 8: the policy the model wrote, one provenanced Quantity whose
    # value is the leaf mapping, attributed per leaf; the block switches
    # on. An EMPTY block falls back to the deterministic vocabulary --
    # the control -- which maps the documented phrases and records an
    # unmapped variation for the sampler to refuse by name.
    randomization = payload["randomization"]
    if randomization:
        policy = {name: entry["value"] for name, entry in randomization.items()}
        attribution = {name: entry["from"].strip()
                       for name, entry in randomization.items()}
        sources = {name: entry["source"] for name, entry in randomization.items()}
        best = ("user" if "user" in sources.values() else
                "inferred" if "inferred" in sources.values() else "model")
        phrases = list(dict.fromkeys(attribution.values()))
        spec.randomization_policy = Quantity(
            value=policy, source=Source(best), frm="; ".join(phrases),
            detail={"attribution": attribution, "sources": sources})
        enable_for_policy(spec, frm=f"{phrases[0]}: the randomisation block "
                                    f"is on")
        if RANDOMIZATION_GROUP in policy and not spec.cameras:
            camera = CameraSpec.defaulted(
                camera_id="camera0", preset="chase",
                aircraft=str(spec.aircraft.value),
                terrain_elevation_m=float(spec.terrain_elevation.value),
                frm=f"{attribution[RANDOMIZATION_GROUP]!r}: one documented "
                    f"default camera for the viewpoint policy to vary")
            plan_full_capture(camera, frm="a viewpoint policy with no count "
                                          "captures the whole clip")
            spec.cameras.append(camera)
    else:
        apply_randomization_phrases(spec, prompt)
    # Unnamed mountains: the synthesised scene, as on the regex tier (a
    # place the model set, or a drawn location, keeps it auto).
    apply_mountain_scene(spec, prompt)

    # The event AIM rides in the quantity's detail (digest-relevant: it
    # decides whether the vortex axis sits ON the track or 2.5 core radii
    # abeam, and which camera the render uses). The regex compiler records
    # it; an LLM-set weather_event must carry the SAME detail or a
    # "through a tornado" clip quietly becomes the flyby with the funnel
    # off-camera (measured -- run b303b23cc7ee). Same regex, same words.
    event = str(spec.weather_event.value)
    if event != "none" and "aim" not in spec.weather_event.detail:
        import re as _re

        from .compiler import WEATHER_EVENT_WORDS

        aim = "abeam"
        for variant in WEATHER_EVENT_WORDS.get(event, ()):
            if _re.search(rf"(?:through|into)\s+(?:a|the)?\s*{variant}",
                          prompt, _re.IGNORECASE):
                aim = "core"
                break
        q = spec.weather_event
        spec.weather_event = Quantity(
            value=q.value, unit=q.unit, source=q.source, frm=q.frm,
            std=q.std, detail={**q.detail, "aim": aim})

    return LLMCompileResult(
        spec=spec, model=str(getattr(response, "model", model)),
        raw_response=text,
        questions=tuple(dict(q) for q in payload["questions"]),
        transcript=tuple(dict(m) for m in messages) if answering else None,
    )


if __name__ == "__main__":   # pragma: no cover -- the live smoke, run by hand
    # python -m core.nl.llm_compiler "simulate a plane in rough wind over mountains"
    # Needs ANTHROPIC_API_KEY in the environment. The suite never runs this.
    import sys

    result = compile_prompt_llm(" ".join(sys.argv[1:]) or
                                "simulate a plane in rough wind conditions "
                                "over mountains")
    print(result.spec.render_table())
    print(f"\ncompiler: {result.compiler}  model: {result.model}")
