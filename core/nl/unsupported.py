"""Prompt words the tool cannot honour, refused by name -- never dropped.

A prompt can name something the spec was never told: a thing the
simulator does not model at all ("birds", "hail", "a ship below"), or a
condition the spec DOES carry but that the compiler which read this
prompt did not set ("fog" through the offline parser). Before this,
both were silently ignored: "an A320 in heavy snow with birds nearby"
flew a clear, empty sky with no word said.

:func:`unsupported_words` scans the prompt against two tables and returns
one refusal per concept, each naming the word as written:

* ``prompt.unsupported`` -- the simulator has no model of it; remove it
  from the prompt (the refusal says what the nearest supported thing is,
  where there is one);
* ``prompt.not_set`` -- the spec has a field for it, but the compiled spec
  did not set it (the field is still its default); state it in the
  review table, or compile with the language model, which reads it.

A concept the compiled spec DID act on (a stated precipitation rate, an
icing block, a randomisation leaf that draws it) is not refused: the
check reads the spec, not only the words.
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

#: The two refusal names (the message catalogue's entries).
REFUSAL_NAMES = {"unsupported": {"constraint": "prompt.unsupported"},
                 "not_set": {"constraint": "prompt.not_set"}}
PROMPT_UNSUPPORTED = REFUSAL_NAMES["unsupported"]["constraint"]
PROMPT_NOT_SET = REFUSAL_NAMES["not_set"]["constraint"]

#: (regex over the lowercased prompt, what it is, the nearest supported thing)
NOT_MODELLED: Tuple[Tuple[str, str, Optional[str]], ...] = (
    (r"\b(?:birds?|flocks? of birds|geese|seagulls?|bird strikes?)\b",
     "birds", None),
    (r"\bdrones?\b|\bquadcopters?\b|\buavs?\b", "drones", "a second aircraft (traffic)"),
    (r"\bhelicopters?\b|\bchoppers?\b", "helicopters",
     "a second fixed-wing aircraft (traffic)"),
    (r"\b(?:ships?|boats?|vessels?|aircraft carriers?)\b", "ships", None),
    (r"\b(?:cars?|trucks?|vehicles?|trains?)\b", "ground vehicles", None),
    (r"\b(?:people|crowds?|pedestrians?|persons?)\b", "people", None),
    (r"\bhail(?:storm|stones?)?\b", "hail", "thunderstorm (weather_event)"),
    (r"\b(?:hurricanes?|typhoons?|(?:tropical )?cyclones?|tropical storms?)\b",
     "hurricanes and tropical cyclones",
     "strong wind, severe turbulence and heavy rain, or a thunderstorm (weather_event)"),
    (r"\blightning(?: strikes?| bolts?)?\b", "lightning", "thunderstorm (weather_event)"),
    (r"\bvolcanic ash\b|\bash clouds?\b", "volcanic ash", None),
    (r"\b(?:sand|dust)\s?storms?\b|\bhaboob\b", "sand / dust storms", "low visibility"),
    (r"\b(?:smoke|wildfires?|forest fires?)\b", "smoke and fire", "low visibility"),
    (r"\brainbows?\b", "rainbows", None),
    (r"\baurora(?:s| borealis| australis)?\b|\bnorthern lights\b", "aurora", None),
    (r"\b(?:crash(?:es|ing)?|explosions?|explod\w*|collisions?|collid\w*|"
     r"mid-?air)\b", "crashes and collisions", None),
    (r"\b(?:missiles?|bombs?|gunfire|dogfights?)\b", "weapons", None),
    (r"\b(?:engine fires?|smoke trails?|contrails?)\b", "engine smoke / contrails", None),
)


def _precipitation_set(spec) -> bool:
    event = getattr(getattr(spec, "weather_event", None), "value", "none")
    if str(event) not in ("none", "None", ""):
        return True                    # a storm event brings its own precipitation
    rate = getattr(spec, "precipitation_rate_mmh", None)
    if rate is not None and getattr(rate, "value", None) not in (None, 0, 0.0):
        return True
    policy = getattr(spec, "randomization_policy", None)
    leaves = (policy.value or {}) if policy is not None else {}
    return "precipitation" in leaves


def _icing_set(spec) -> bool:
    icing = getattr(spec, "icing", None)
    return icing is not None and not icing.is_default()


def _fog_set(spec) -> bool:
    policy = getattr(spec, "randomization_policy", None)
    leaves = (policy.value or {}) if policy is not None else {}
    return "visibility_km" in leaves or bool(getattr(spec.randomization, "is_enabled",
                                                     lambda: False)())


def _route_set(spec) -> bool:
    route = getattr(spec, "route", None)
    return route is not None and not route.is_default()


#: The remedy for a field no compiler fills: the route is drawn, not
#: written, so the sentence points at the map rather than at the table
#: or the language model.
ROUTE_REMEDY = ("Draw the path on the route map (Draw the flight path, under the review "
                "table), which writes it into the spec; no compiler reads a path from words")

#: (regex, what it is, the field that carries it, "is it set in this spec?",
#:  the remedy sentence -- None for the table-or-language-model remedy)
CARRIED: Tuple[Tuple[str, str, str, Callable, Optional[str]], ...] = (
    (r"\b(?:rain(?:y|ing|fall)?|drizzle|showers?|downpour)\b", "rain",
     "environment.precipitation_rate_mmh (or varied weather)", _precipitation_set, None),
    (r"\b(?:snow(?:y|ing|fall|storm)?|sleet|blizzard)\b", "snow",
     "environment.precipitation_rate_mmh (or varied weather)", _precipitation_set, None),
    (r"\b(?:icing|icy|ice accretion|freezing rain|rime ice)\b", "icing",
     "the icing block (icing.*)", _icing_set, None),
    (r"\b(?:fog(?:gy)?|mist(?:y)?|haze|hazy)\b", "fog / haze",
     "randomization.fog_density or varied weather (visibility)", _fog_set, None),
    # Route words (docs/ROUTE.md): a path is drawn on the route map, never
    # compiled from a sentence. "orbit" is the chase camera's word and is
    # not here; "circle" is, unless the camera does the circling.
    (r"\bfly(?:ing)? to\b|\bwaypoints?\b|\bfollow(?:ing)? the (?:valley|river|coast(?:line)?"
     r"|ridge|road)\b|\baround the (?:peak|mountain|summit|hill)\b"
     r"|(?<!camera )(?<!chase )\bcircl(?:e|es|ing)\b",
     "a flight path", "route.waypoints", _route_set, ROUTE_REMEDY),
)


def unsupported_words(prompt: Optional[str], spec) -> List[Tuple[str, str, str]]:
    """``[(constraint, sentence, word)]`` for every concept in the prompt
    the compiled spec does not honour (``word`` as the prompt wrote it,
    for the plain-language sentence). Empty for no prompt."""
    text = " ".join(str(prompt or "").lower().split())
    if not text:
        return []
    out: List[Tuple[str, str]] = []
    for pattern, what, nearest in NOT_MODELLED:
        match = re.search(pattern, text)
        if match:
            out.append((
                PROMPT_UNSUPPORTED,
                f'the prompt asks for "{match.group(0)}" ({what}), which this '
                f"simulator does not model; remove it from the prompt"
                + (f" (the nearest supported thing: {nearest})" if nearest else ""),
                match.group(0)))
    for pattern, what, field, is_set, remedy in CARRIED:
        match = re.search(pattern, text)
        if match:
            try:
                honoured = bool(is_set(spec))
            except Exception:
                honoured = False
            if not honoured:
                out.append((
                    PROMPT_NOT_SET,
                    f'the prompt says "{match.group(0)}" ({what}) but the compiled '
                    f"spec does not set it -- it would fly without it. "
                    + (remedy if remedy is not None else
                       f"State it in the review table ({field}), or compile with the "
                       f"language model, which reads it"),
                    match.group(0)))
    return out
