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
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..environment.surface import SURFACE_CLASSES
from ..scenario.fields import Quantity, Source
from ..scenario.spec import ScenarioSpec
from ..terrain.glo30 import LOCATIONS
from .compiler import TURBULENCE_STD, TURBULENCE_WORDS, compile_prompt, _name_from

#: The model the compiler asks for. Recorded verbatim in the result so the
#: manifest can say which model produced the spec.
DEFAULT_MODEL = "claude-opus-5"

#: Aircraft the schema lets the model name: exactly the models the regex
#: vocabulary can reach, so the two compilers share an aircraft vocabulary
#: and ``aircraft.exists`` validation stays the only authority on what flies.
AIRCRAFT_MODELS = ("737", "A320", "B747", "c172p", "f15", "f16", "global5000")

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
    at a repair.
    """


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
}

# The schema is generated FROM the spec's field list; a field added to one
# and not the other fails at import, not at 2 a.m. in a run manifest.
_SPEC_FIELDS = {name for _, name in ScenarioSpec.FIELD_ORDER}
_unknown = set(FIELD_VALUE_SCHEMAS) - _SPEC_FIELDS
assert not _unknown, f"llm_compiler schema names non-spec fields: {_unknown}"

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


SYSTEM_PROMPT = """\
You are the scene DIRECTOR for a flight-simulation compiler. Turn the
prompt into a COHERENT scene: fill every field the prompt justifies --
aircraft, place, altitude, airspeed, heading, wind speed AND direction,
turbulence, surface, weather event, date -- so that the fields agree with
each other and with what the prompt evokes. Every value you write
declares how it was chosen; a guess you do not declare is the one
failure this protocol cannot forgive.

Respond with EXACTLY this top-level shape -- three keys, no others:
{"fields": {"<field name>": {"value": ..., "source": "...", "from": "..."},
 ...}, "notes": [...], "questions": [...]}
"notes" and "questions" are TOP-LEVEL keys beside "fields", never inside
"fields"; "fields" contains ONLY schema field names. Each field object
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
- Aircraft with real licensed 3-D models: B747, A320, c172p -- prefer
  these for GUESSES ("small plane" -> c172p, "airliner/jet" -> A320 or
  B747). 737, global5000, f15 and f16 have real flight physics but no
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
- Anything the schema cannot express -- unknown aircraft, cinematic or
  camera language, weather the vocabulary lacks -- goes into "notes"
  verbatim, never guessed into a field.

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


# -- parsing: strict, loud, never patched ---------------------------------

def _fail(reason: str) -> "LLMCompileError":
    return LLMCompileError(
        f"the language model's response was rejected: {reason}. The spec was "
        f"not built; re-run, rephrase, or use the offline compiler.")


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
    if set(payload) != {"fields", "notes", "questions"}:
        raise _fail(f"top-level keys {sorted(payload)} != "
                    f"['fields', 'notes', 'questions']")
    fields, notes = payload["fields"], payload["notes"]
    if not isinstance(fields, dict):
        raise _fail("'fields' is not an object")
    if not (isinstance(notes, list)
            and all(isinstance(n, str) for n in notes)):
        raise _fail("'notes' is not a list of strings")

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
    except Exception as exc:   # transport/API errors, shown not swallowed
        raise _fail(f"API call failed ({type(exc).__name__}: {exc})") from exc

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
