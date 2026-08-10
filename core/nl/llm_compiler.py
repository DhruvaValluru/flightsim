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
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..scenario.fields import Quantity, Source
from ..scenario.spec import ScenarioSpec
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
    """

    spec: ScenarioSpec
    model: str
    raw_response: str
    compiler: str = "llm"


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
            # OMITTED field. The model may only claim what the prompt said.
            "source": {"type": "string", "enum": ["user", "inferred"]},
            "from": {
                "type": "string",
                "description": "The prompt phrase this value was read from.",
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
}

# The schema is generated FROM the spec's field list; a field added to one
# and not the other fails at import, not at 2 a.m. in a run manifest.
_SPEC_FIELDS = {name for _, name in ScenarioSpec.FIELD_ORDER}
_unknown = set(FIELD_VALUE_SCHEMAS) - _SPEC_FIELDS
assert not _unknown, f"llm_compiler schema names non-spec fields: {_unknown}"

RESPONSE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fields", "notes"],
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
    },
}

SYSTEM_PROMPT = """\
You compile flight-simulation prompts into a condition schema. Extract ONLY
what the prompt states or clearly implies; omit every field the prompt does
not mention (omitted fields get the system's documented defaults).

Rules:
- source "user" for explicit numbers ("250 kt" -> airspeed 250); source
  "inferred" for vague phrases ("strong wind" -> wind_speed 25). Record the
  exact prompt phrase in "from" either way.
- Canonical units only: metres for altitude/terrain elevation, knots for
  speeds, degrees for angles, seconds for duration. Convert stated units
  (feet, minutes, flight levels) and keep the original phrase in "from".
- Vague wind strength maps as: light/gentle 8 kt, moderate 15 kt,
  strong/stiff 25 kt, severe/gale 40 kt. "rough"/"turbulent" wind implies
  both a strong wind (25 kt) and moderate turbulence unless stated otherwise.
- Relative wind ("headwind", "crosswind") is a bearing offset from the
  aircraft heading (head 0, cross 90, tail 180), meteorological convention.
- "mountains"/"alpine"/"ridge" with no numbers: terrain_elevation 2000,
  inferred. A named real place you are confident of may set latitude,
  longitude and terrain_elevation, inferred, with the place name in "from".
- Do not judge feasibility. If the prompt commands something impossible,
  extract it literally -- the validator refuses it by name, which is the
  designed path. Never soften or "fix" a stated number.
- Anything you cannot express in the schema -- unknown aircraft, cinematic
  or camera language, weather the vocabulary lacks -- goes into "notes"
  verbatim, never guessed into a field.
"""


# -- parsing: strict, loud, never patched ---------------------------------

def _fail(reason: str) -> "LLMCompileError":
    return LLMCompileError(
        f"the language model's response was rejected: {reason}. The spec was "
        f"not built; re-run, rephrase, or use the offline compiler.")


def _parse_payload(text: str) -> Dict[str, Any]:
    """Parse the model's JSON strictly against the schema's intent.

    The API already constrains the shape, but this module does not trust the
    transport: everything is re-checked here so a malformed response -- from
    a mock, a cached file, or a future API change -- fails identically.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _fail(f"not valid JSON ({exc})") from None
    if not isinstance(payload, dict):
        raise _fail("top level is not an object")
    if set(payload) != {"fields", "notes"}:
        raise _fail(f"top-level keys {sorted(payload)} != ['fields', 'notes']")
    fields, notes = payload["fields"], payload["notes"]
    if not isinstance(fields, dict):
        raise _fail("'fields' is not an object")
    if not (isinstance(notes, list)
            and all(isinstance(n, str) for n in notes)):
        raise _fail("'notes' is not a list of strings")

    for name, entry in fields.items():
        if name not in FIELD_VALUE_SCHEMAS:
            raise _fail(f"unknown field {name!r}")
        if not isinstance(entry, dict) or set(entry) != {"value", "source", "from"}:
            raise _fail(f"field {name!r} must carry exactly value/source/from")
        if entry["source"] not in ("user", "inferred"):
            raise _fail(f"field {name!r} claims source {entry['source']!r}; "
                        f"only 'user' or 'inferred' may be claimed by a model")
        if not (isinstance(entry["from"], str) and entry["from"].strip()):
            raise _fail(f"field {name!r} has no provenance phrase")
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
    source = Source.USER if entry["source"] == "user" else Source.INFERRED
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
                       model: str = DEFAULT_MODEL) -> LLMCompileResult:
    """Turn a prompt into a spec via the Claude API. Does not run anything.

    ``client`` is an ``anthropic.Anthropic``-compatible object; the suite
    injects a mock here so no test touches the network. Left ``None``, the
    real SDK client is constructed and resolves its key from the
    environment.
    """
    if client is None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMCompileError(
                "the anthropic SDK is not installed; the LLM compiler is "
                "unavailable. Use the offline regex compiler.") from exc
        client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema",
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

    payload = _parse_payload(text)

    # Defaults come from the regex compiler run on an EMPTY prompt, so an
    # untouched field is bit-identical between the two compilers and the
    # validator cannot judge them differently on shared vocabulary.
    spec = compile_prompt("", name=name or _name_from(prompt.lower()))
    spec.prompt = prompt
    spec.notes = list(payload["notes"])

    for field_name, entry in payload["fields"].items():
        _overlay(spec, field_name, entry)

    return LLMCompileResult(spec=spec, model=str(getattr(response, "model", model)),
                            raw_response=text)


if __name__ == "__main__":   # pragma: no cover -- the live smoke, run by hand
    # python -m core.nl.llm_compiler "simulate a plane in rough wind over mountains"
    # Needs ANTHROPIC_API_KEY in the environment. The suite never runs this.
    import sys

    result = compile_prompt_llm(" ".join(sys.argv[1:]) or
                                "simulate a plane in rough wind conditions "
                                "over mountains")
    print(result.spec.render_table())
    print(f"\ncompiler: {result.compiler}  model: {result.model}")
