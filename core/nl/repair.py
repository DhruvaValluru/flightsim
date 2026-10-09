"""Repair a refused scenario with the language model, the way the user wants.

The owner's ask (2026-10-09): when a scenario cannot run, say what to
keep ("keep the altitude") and have the model change the rest so the
refusals go away. :func:`repair_spec` hands the model the spec's fields,
the refusals in plain words (the catalogue's sentence and hint, which
for the trim refusal already names the smallest change that works) and
the instruction, applies the edits it returns as USER edits with the
instruction as their provenance, re-validates, and feeds any remaining
refusal back for another round, up to ``rounds`` rounds.

Only the fields in REPAIRABLE may be edited: the numbers a scenario is
made of, never the place, the cameras, the route or the dataset blocks.
A field the instruction asks to keep is listed as untouchable in the
prompt and refused if the model edits it anyway. Without a model (none
configured, or it fails) the deterministic fallback applies the trim
refusal's own suggestion, honouring the kept field, so the button never
does nothing silently: it says which reader did the work.

Not claimed: that the model's edit is the best one, only that the result
validates (or the last round's refusals are returned, named).
"""

from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: The fields the model may change, with the unit the table shows.
REPAIRABLE: Tuple[str, ...] = ("altitude", "airspeed", "heading", "wind_speed",
                               "wind_direction", "turbulence", "duration",
                               "precipitation_rate_mmh")
#: The words an instruction uses for a field it wants kept.
KEEP_WORDS = {
    "altitude": ("altitude", "height", "alt"),
    "airspeed": ("speed", "airspeed", "kt", "knots"),
    "heading": ("heading",),
    "wind_speed": ("wind",),
    "wind_direction": ("wind direction",),
    "turbulence": ("turbulence",),
    "duration": ("duration", "seconds", "length"),
    "precipitation_rate_mmh": ("rain", "precipitation", "snow"),
}
MAX_ROUNDS = 3
MAX_INSTRUCTION = 300

SYSTEM_PROMPT = """You repair a flight-simulation scenario that its validator refused.
You are given the scenario's fields, the refusals in plain words (each with a hint,
sometimes naming the smallest change that works), and what the user wants kept.
Reply with JSON only: {"edits": [{"field": <name>, "value": <number or word>, "why": <one sentence>}], "note": <one sentence>}.
Rules: edit only the fields listed as editable; never edit a field listed as kept;
make the smallest changes that remove every refusal; prefer the change a hint
names; numbers in the units shown; no more than three edits per round."""

REPAIR_SCHEMA = {
    "type": "object",
    "properties": {
        "edits": {"type": "array", "items": {
            "type": "object",
            "properties": {"field": {"type": "string"},
                           "value": {"type": ["number", "string"]},
                           "why": {"type": "string"}},
            "required": ["field", "value", "why"]}},
        "note": {"type": "string"},
    },
    "required": ["edits", "note"],
}


class RepairError(Exception):
    """The model could not be used, or replied outside the rules."""


@dataclass
class Edit:
    field: str
    before: Any
    after: Any
    why: str
    round: int

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "from": self.before, "to": self.after,
                "why": self.why, "round": self.round}


@dataclass
class RepairResult:
    spec: Any
    ok: bool
    edits: List[Edit] = field(default_factory=list)
    rounds: int = 0
    reader: str = "llm"
    model: Optional[str] = None
    note: str = ""
    remaining: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "edits": [e.to_dict() for e in self.edits],
                "rounds": self.rounds, "reader": self.reader, "model": self.model,
                "note": self.note, "remaining": self.remaining}


def kept_fields(instruction: str) -> List[str]:
    """The REPAIRABLE fields the instruction says to keep ("keep the
    altitude", "don't change the speed", "same heading")."""
    text = instruction.lower()
    if not re.search(r"\b(keep|hold|same|don'?t (?:change|touch|move)|leave|fixed|stay)\b", text):
        return []
    kept = []
    for name, words in KEEP_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", text) for w in words):
            kept.append(name)
    # "wind" alone keeps the speed, not the direction (its own phrase).
    return kept


def refusal_words(violations) -> List[Dict[str, str]]:
    from ..messages import explain

    out = []
    for v in violations:
        words = explain(v)
        out.append({"rule": v.constraint, "sentence": words["sentence"],
                    "hint": words["hint"]})
    return out


def _fields_block(spec, kept: List[str]) -> str:
    lines = []
    for name in REPAIRABLE:
        q = getattr(spec, name)
        unit = f" {q.unit}" if q.unit else ""
        state = "KEPT, never edit" if name in kept else "editable"
        lines.append(f"- {name} = {q.value}{unit} ({state})")
    lines.append(f"- aircraft = {spec.aircraft.value} (not editable)")
    return "\n".join(lines)


def _ask(client, model: str, spec, kept: List[str], refusals: List[Dict[str, str]],
         instruction: str, history: List[str]) -> Dict[str, Any]:
    text = (f"Scenario fields:\n{_fields_block(spec, kept)}\n\n"
            f"Refusals:\n" + "\n".join(f"- {r['sentence']} {r['hint']}".strip() for r in refusals)
            + f"\n\nThe user wants: {instruction or 'the smallest change that makes it run'}\n"
            + ("\nEarlier rounds:\n" + "\n".join(history) if history else ""))
    try:
        response = client.messages.create(
            model=model, max_tokens=600, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": REPAIR_SCHEMA}})
        reply = next(b.text for b in response.content if getattr(b, "type", None) == "text")
        data = json.loads(reply)
    except Exception as exc:
        raise RepairError(f"the language model could not be used ({type(exc).__name__})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
        raise RepairError("the model's reply is not an edit list")
    return data


def _resolve_client(client, model):
    from .llm_compiler import DEFAULT_MODEL, llm_available

    if client is not None:
        return client, model or DEFAULT_MODEL
    if not llm_available():
        raise RepairError("no language model is configured")
    from .providers import resolve_client

    try:
        resolved = resolve_client()
    except ValueError as exc:
        raise RepairError(str(exc)) from exc
    if resolved is not None:
        return resolved[0], (model or resolved[1])
    try:
        import anthropic
    except ImportError as exc:
        raise RepairError("the anthropic SDK is not installed") from exc
    return anthropic.Anthropic(), model or DEFAULT_MODEL


def _apply(spec, edits: List[Dict[str, Any]], kept: List[str], instruction: str,
           round_no: int) -> List[Edit]:
    applied = []
    for entry in edits[:3]:
        name = str(entry.get("field", ""))
        if name not in REPAIRABLE:
            raise RepairError(f"the model edited {name!r}, which is not one of the editable fields")
        if name in kept:
            raise RepairError(f"the model edited {name!r}, which the instruction keeps")
        value = entry.get("value")
        current = getattr(spec, name)
        if isinstance(current.value, (int, float)) and not isinstance(current.value, bool):
            try:
                value = float(value)
            except (TypeError, ValueError) as exc:
                raise RepairError(f"the model's value for {name} is not a number") from exc
        else:
            value = str(value)
        before = current.value
        spec.set(name, value, frm=f"repaired by the model ({instruction or 'make it run'}): "
                                  f"{str(entry.get('why', '')).strip()[:200]}")
        applied.append(Edit(name, before, value, str(entry.get("why", "")).strip(), round_no))
    return applied


def _fallback(spec, violations, kept: List[str], instruction: str) -> RepairResult:
    """No model: the trim refusal's own suggestion, honouring a kept field."""
    from ..scenario.validate import trim_suggestion, validate

    trim = [v for v in violations if v.constraint == "envelope.trim_feasible"]
    if not trim:
        return RepairResult(spec, False, reader="rules", remaining=refusal_words(violations),
                            note="no language model is configured and only the trim refusal "
                                 "has a rule-based repair")
    keep = "altitude" if "altitude" in kept else "airspeed" if "airspeed" in kept else None
    suggestion = trim_suggestion(spec, keep=keep)
    m = re.match(r"change the (altitude|speed) to ([\d.]+) (m|kt)", suggestion or "")
    if not m:
        return RepairResult(spec, False, reader="rules", remaining=refusal_words(violations),
                            note="no nearby condition trims with the kept field kept")
    name = "altitude" if m.group(1) == "altitude" else "airspeed"
    before = getattr(spec, name).value
    value = float(m.group(2))
    spec.set(name, value, frm=f"repaired by the rules ({instruction or 'make it run'}): {suggestion}")
    report = validate(spec)
    return RepairResult(spec, report.ok, [Edit(name, before, value, suggestion, 1)], 1, "rules",
                        None, suggestion, refusal_words(report.violations))


def repair_spec(spec, instruction: str = "", *, client: Any = None, model: Optional[str] = None,
                rounds: int = MAX_ROUNDS) -> RepairResult:
    """The spec edited until it validates (or ``rounds`` rounds have been
    spent), by the model, else by the rules. The spec passed in is edited
    in place; a copy is what the rounds work on until one validates."""
    from ..scenario.validate import validate

    instruction = (instruction or "").strip()[:MAX_INSTRUCTION]
    kept = kept_fields(instruction)
    report = validate(spec)
    if report.ok:
        return RepairResult(spec, True, note="nothing to repair: the scenario already runs")
    try:
        client, model = _resolve_client(client, model)
    except RepairError as exc:
        result = _fallback(spec, report.violations, kept, instruction)
        result.note = f"{exc}; {result.note}" if result.note else str(exc)
        return result
    work = copy.deepcopy(spec)
    edits: List[Edit] = []
    history: List[str] = []
    violations = report.violations
    note = ""
    for round_no in range(1, max(1, rounds) + 1):
        refusals = refusal_words(violations)
        data = _ask(client, model, work, kept, refusals, instruction, history)
        note = str(data.get("note", "")).strip()
        applied = _apply(work, data.get("edits", []), kept, instruction, round_no)
        edits.extend(applied)
        history.append(f"round {round_no}: " + "; ".join(
            f"{e.field} {e.before} -> {e.after}" for e in applied) or "no edits")
        report = validate(work)
        if report.ok:
            _copy_into(spec, work)
            return RepairResult(spec, True, edits, round_no, "llm", model, note, [])
        if not applied:
            break
        violations = report.violations
        history[-1] += " -- still refused: " + "; ".join(v.constraint for v in violations)
    _copy_into(spec, work)
    return RepairResult(spec, False, edits, len(history), "llm", model, note,
                        refusal_words(report.violations))


def _copy_into(spec, work) -> None:
    for name in REPAIRABLE:
        setattr(spec, name, getattr(work, name))
