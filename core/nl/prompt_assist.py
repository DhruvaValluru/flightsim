"""The language model rewrites the PROMPT itself, before and after Interpret.

The owner's ask (2026-11-19): when a prompt cannot run (the plane is too
close to the ground, too slow, ...) the model should work out why by
itself, say so under the Interpret button, and change the prompt so it
runs; and a prompt too vague to say much ("a plane flying") should be
expanded by the model into a specific one, almost prompting itself.

:func:`expand_prompt` turns a vague prompt into one specific sentence;
:func:`fix_prompt` rewrites a prompt so the named problems go away while
keeping everything else the user asked for. Both return a
:class:`PromptRewrite` (the new prompt and one plain sentence saying
what changed and why) or None when there is no model, the call fails or
the reply is unusable -- the page then shows the original verdict, never
nothing. The server re-interprets the rewritten prompt and keeps it only
when it actually runs (webapp/server.py, compile_endpoint).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence

#: The longest prompt the model may write (a rewrite is a sentence or two).
MAX_PROMPT_CHARS = 600

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "prompt": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["prompt", "explanation"],
}

_RULES = """Facts about this simulator:
- Altitudes in a prompt are ABOVE SEA LEVEL (feet, metres or FL). The ground at a
  place can be high: the Grand Canyon rim is ~7,000 ft, Yosemite's peaks ~9,000-13,000 ft,
  Denver ~5,300 ft, the Alps ~10,000-15,000 ft. Keep at least ~2,000 ft above the
  highest ground nearby; fast jets at least ~3,000 ft.
- Each aircraft has a stall speed and a top speed; jets cruise ~350-500 kt, small
  propeller planes ~100-180 kt. Leave out a speed rather than guess a wrong one.
- Weather words it understands: clear, scattered/broken/overcast clouds, rain, snow,
  thunderstorm (it brings its own lightning: write "thunderstorm", never the word
  "lightning", which is refused), fog, wind in knots, light/moderate/severe turbulence.
- "Above the clouds" is said with a cloud layer and a high altitude ("overcast clouds,
  at 35,000 ft"), never as the ground; the ground is a place or a surface word
  (ocean, city, desert, forest, mountains).
- Time words: dawn, morning, noon, afternoon, golden hour, sunset, dusk, night.
- The word "cinematic" asks for the highest-quality look.
Reply with JSON only: {"prompt": <the new prompt>, "explanation": <one short plain
sentence for the user saying what you changed and why>}. Write the prompt as one
or two plain English sentences, no lists, no JSON, under 60 words."""

EXPAND_SYSTEM = ("You turn a short or vague flight-simulation request into a specific "
                 "one the simulator can run. Keep every detail the user gave; fill in "
                 "only what is missing: an aircraft (from the list given), a real place, "
                 "an altitude safely above that place's ground, a time of day, the "
                 "weather and, if none is named, a chase view. Make it look good.\n"
                 + _RULES)

FIX_SYSTEM = ("You fix a flight-simulation request the simulator refused. You are "
              "given the request and the problems in plain words (each with a hint). "
              "Rewrite the request so every problem goes away, changing as LITTLE as "
              "possible: keep the aircraft, place, weather, time and view the user asked "
              "for unless one of them IS the problem; prefer the change a hint names "
              "(usually a higher altitude or a different speed).\n" + _RULES)


@dataclass
class PromptRewrite:
    kind: str               # "expanded" | "fixed"
    original: str
    prompt: str
    explanation: str
    model: Optional[str] = None
    problems: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


_NUMBER = re.compile(r"\d")
_DETAIL_WORDS = re.compile(
    r"\b(over|above|near|at|in|through|across|feet|ft|metres?|meters?|knots?|kt|fl\d+|"
    r"dawn|morning|noon|afternoon|evening|sunset|sunrise|dusk|night|golden|"
    r"rain|snow|storm|cloud|clouds|fog|wind|turbulen\w*|lightning|clear|"
    r"chase|cockpit|tower|ground|camera|view|orbit)\b", re.I)


def is_vague(prompt: str) -> bool:
    """Too little to go on: fewer than three details (place/altitude/time/
    weather/view words or any number) in a short prompt."""
    text = (prompt or "").strip()
    if not text:
        return False
    words = text.split()
    details = len(_DETAIL_WORDS.findall(text)) + (1 if _NUMBER.search(text) else 0)
    return len(words) < 14 and details < 3


def _client(client: Any = None, model: Optional[str] = None):
    from .repair import RepairError, _resolve_client

    try:
        return _resolve_client(client, model)
    except RepairError:
        return None, None


def _ask(client, model, system: str, text: str) -> Optional[Dict[str, str]]:
    try:
        response = client.messages.create(
            model=model, max_tokens=800, system=system,
            messages=[{"role": "user", "content": text}],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": REWRITE_SCHEMA}})
        reply = next(b.text for b in response.content if getattr(b, "type", None) == "text")
        data = json.loads(reply)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    prompt = str(data.get("prompt", "")).strip()
    explanation = str(data.get("explanation", "")).strip()
    if not prompt or len(prompt) > MAX_PROMPT_CHARS or prompt.startswith("{"):
        return None
    return {"prompt": prompt, "explanation": explanation}


def _aircraft_line(aircraft: Sequence[str]) -> str:
    return ("Aircraft available: " + ", ".join(aircraft) + ".") if aircraft else ""


def expand_prompt(prompt: str, aircraft: Sequence[str] = (), *, client: Any = None,
                  model: Optional[str] = None) -> Optional[PromptRewrite]:
    client, model = _client(client, model)
    if client is None:
        return None
    data = _ask(client, model, EXPAND_SYSTEM,
                f"{_aircraft_line(aircraft)}\n\nRequest: {prompt.strip()}")
    if data is None or data["prompt"].strip() == prompt.strip():
        return None
    return PromptRewrite("expanded", prompt, data["prompt"],
                         data["explanation"] or "added the missing details", model)


def fix_prompt(prompt: str, problems: Sequence[str], aircraft: Sequence[str] = (),
               history: Sequence[str] = (), *, client: Any = None,
               model: Optional[str] = None) -> Optional[PromptRewrite]:
    if not problems:
        return None
    client, model = _client(client, model)
    if client is None:
        return None
    text = (f"{_aircraft_line(aircraft)}\n\nRequest: {prompt.strip()}\n\nProblems:\n"
            + "\n".join(f"- {p}" for p in problems)
            + ("\n\nEarlier attempts that still failed:\n" + "\n".join(history)
               if history else ""))
    data = _ask(client, model, FIX_SYSTEM, text)
    if data is None or data["prompt"].strip() == prompt.strip():
        return None
    return PromptRewrite("fixed", prompt, data["prompt"],
                         data["explanation"] or "changed the request so it can run",
                         model, list(problems))
