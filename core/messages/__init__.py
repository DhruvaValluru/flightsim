"""The message catalogue: one plain sentence per refusal name, check and
progress state (contracts §8, §11; brainstorm §8.2).

The catalogue is ``catalog.yaml`` beside this file. A refusal reaches
the person in one of three shapes -- a ``Violation`` (``constraint``,
``message``, ``actual``, ``limit``, ``unit``), the same five keys as a
plain dict (the web app), or an exception whose class carries a
``constraint`` -- and :func:`explain` turns any of them into
``{"sentence", "hint", "rule"}``: the sentence in words, what to do,
and the rule name that the interface shows under a disclosure and the
agent writes into its trace. :func:`render` fills one sentence from
keyword parameters.

Placeholders. ``{name}`` is replaced by the parameter's value (numbers
shown short: ``89.5``, ``2``, ``1.2e+06``); ``{name:one|many}`` is a
plural form chosen by the numeric value of ``name`` (exactly 1 picks
the first). A placeholder with no value renders as nothing and the
sentence is tidied around the gap; rendering never raises. The
parameters :func:`explain` offers are the refusal's own fields plus
three derived ones: ``shortfall`` (limit - actual), ``excess``
(actual - limit) when both are numbers, and ``count`` (the number of
violations a report carries).

What is NOT claimed. The catalogue does not decide whether something
is refused -- the validators do, by name, and this module never
imports them. A sentence describes what the rule refuses in words; it
is not the rule, and the technical message the producer wrote is
still the authoritative account of the specific value. An unknown
name is NOT invented a sentence for: :func:`explain` returns the raw
name as the sentence with the technical message as the hint, and the
coverage test in ``tests/test_messages.py`` forbids that path for
every name the codebase emits.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

#: The catalogue file; one place, read once.
CATALOG_PATH = Path(__file__).with_name("catalog.yaml")

#: ``{name}`` or ``{name:singular|plural}``.
_PLACEHOLDER = re.compile(
    r"\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?::(?P<one>[^{}|]*)\|(?P<many>[^{}|]*))?\}")

#: What a rule name looks like when it stands alone in a dict's
#: ``refused`` slot (the web app also puts a whole paragraph there).
_NAME_RE = re.compile(r"^[a-z_]+(?:\.[a-z_]+)*$")

#: Exception classes the CLI already names on its REFUSED line but which
#: carry no ``constraint`` attribute themselves (flightsim/capture.py,
#: webapp/runs.py). Matched by class NAME so this module imports no
#: producer.
_EXCEPTION_NAMES = {
    "TerrainImpactError": "terrain.impact",
    "TrimError": "trim",
    "ClosureError": "run.closure",
    "WeatherUnavailableError": "weather.unavailable",
}

#: Sentences that identify the un-named ``ValueError`` /
#: ``LLMCompileError`` refusals (contracts §11: catalogued under new
#: names; the code keeps raising the exception). The test asserts each
#: sentence is still what the raise site says.
_SENTENCE_NAMES = (
    ("spec_version", "is not supported by this build", "spec.version"),
    ("capture manifest version", "is not supported", "manifest.version"),
    ("the language model's response was rejected", "", "compile.rejected"),
    ("the LLM compiler is unavailable", "", "compile.unavailable"),
    ("no LLM provider is configured", "", "compile.unavailable"),
)

_catalogue: Optional[Dict[str, Dict[str, str]]] = None


def catalogue() -> Dict[str, Dict[str, str]]:
    """The whole catalogue, ``{name: {"sentence": ..., "hint"?: ...}}``,
    loaded once and validated: every entry is a mapping with a string
    ``sentence`` and at most a string ``hint``. A malformed catalogue
    raises at first use, loudly, rather than rendering rule names."""
    global _catalogue
    if _catalogue is None:
        data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{CATALOG_PATH}: the catalogue is not a mapping")
        loaded: Dict[str, Dict[str, str]] = {}
        for name, entry in data.items():
            if not isinstance(entry, dict) or not isinstance(
                    entry.get("sentence"), str):
                raise ValueError(
                    f"{CATALOG_PATH}: entry {name!r} needs a string sentence")
            extra = set(entry) - {"sentence", "hint"}
            if extra or not isinstance(entry.get("hint", ""), str):
                raise ValueError(
                    f"{CATALOG_PATH}: entry {name!r} carries {sorted(extra)}; "
                    f"only sentence and hint are catalogue keys")
            loaded[str(name)] = dict(entry)
        _catalogue = loaded
    return _catalogue


def names() -> frozenset:
    """Every rule name the catalogue knows."""
    return frozenset(catalogue())


def is_catalogued(name: str) -> bool:
    return name in catalogue()


# -- rendering -------------------------------------------------------------

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def shown(value: Any) -> str:
    """A value as the sentence shows it: numbers short, everything else
    as-is (the randomisation ranges are strings like ``1950-2050``)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return str(value)
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.6g}"
    return str(value)


def _tidy(text: str) -> str:
    """Close the gaps an absent placeholder leaves: doubled spaces, empty
    brackets, a stray space before punctuation."""
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def fill(template: str, params: Mapping[str, Any]) -> str:
    """Fill ``{name}`` and ``{name:one|many}`` from ``params``; a missing
    or None parameter renders as nothing. Never raises."""
    def replace(match: "re.Match") -> str:
        name = match.group("name")
        value = params.get(name)
        if match.group("one") is not None:
            if value is None:
                return ""
            try:
                one = float(value) == 1.0
            except (TypeError, ValueError):
                one = False
            return match.group("one") if one else match.group("many")
        return shown(value)

    return _tidy(_PLACEHOLDER.sub(replace, template))


def render(name: str, **params: Any) -> str:
    """The catalogue sentence for ``name`` with its placeholders filled.
    An unknown name renders as the name itself -- never a KeyError, so
    a refusal is always shown, and never an invented sentence."""
    entry = catalogue().get(name)
    if entry is None:
        return name
    return fill(entry["sentence"], derive(params))


def hint(name: str, **params: Any) -> str:
    """The catalogue hint for ``name`` (filled), or ``""``."""
    entry = catalogue().get(name)
    if entry is None or not entry.get("hint"):
        return ""
    return fill(entry["hint"], derive(params))


# -- reading a refusal in any of its shapes ---------------------------------

def name_of(obj: Any) -> Optional[str]:
    """The rule name a refusal carries, in any of the shapes the code
    emits, or None when it carries none."""
    if isinstance(obj, str):
        return obj if _NAME_RE.match(obj) else _name_from_sentence(obj)
    if isinstance(obj, Mapping):
        constraint = obj.get("constraint")
        if isinstance(constraint, str) and constraint:
            return constraint
        refused = obj.get("refused")
        if isinstance(refused, str) and _NAME_RE.match(refused):
            return refused
        if isinstance(refused, str):
            return _name_from_sentence(refused)
        return None
    constraint = getattr(obj, "constraint", None)
    if isinstance(constraint, str) and constraint:
        return constraint
    if isinstance(obj, BaseException):
        by_class = _EXCEPTION_NAMES.get(type(obj).__name__)
        if by_class:
            return by_class
        return _name_from_sentence(str(obj))
    return None


def _name_from_sentence(text: str) -> Optional[str]:
    for head, tail, name in _SENTENCE_NAMES:
        if head in text and tail in text:
            return name
    return None


def technical(obj: Any) -> str:
    """The producer's own text for a refusal: the message it wrote."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, Mapping):
        message = obj.get("message")
        if isinstance(message, str) and message:
            return message
        refused = obj.get("refused")
        if isinstance(refused, str) and not _NAME_RE.match(refused):
            return refused
        return ""
    message = getattr(obj, "message", None)
    if isinstance(message, str) and message:
        return message
    if isinstance(obj, BaseException):
        return str(obj)
    return ""


def params_of(obj: Any) -> Dict[str, Any]:
    """The placeholder values a refusal offers: its own fields, every
    other key of a dict, and the derived ``shortfall`` / ``excess`` /
    ``count``."""
    params: Dict[str, Any] = {}
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            if isinstance(key, str):
                params[key] = value
    else:
        for key in ("constraint", "message", "actual", "limit", "unit"):
            value = getattr(obj, key, None)
            if value is not None:
                params[key] = value
    return derive(params)


def derive(params: Mapping[str, Any]) -> Dict[str, Any]:
    """``params`` plus the derived placeholders: ``shortfall`` (limit -
    actual) and ``excess`` (actual - limit) when both are numbers, and
    ``count`` (how many violations a report carries). Given values are
    never overwritten."""
    out: Dict[str, Any] = dict(params)
    actual, limit = out.get("actual"), out.get("limit")
    if _is_number(actual) and _is_number(limit):
        out.setdefault("shortfall", limit - actual)
        out.setdefault("excess", actual - limit)
    violations = out.get("violations")
    if isinstance(violations, (list, tuple)):
        out.setdefault("count", len(violations))
    return out


def explain(obj: Any, **extra: Any) -> Dict[str, str]:
    """``{"sentence", "hint", "rule"}`` for a Violation, a refusal dict,
    an exception, or a bare rule name.

    A known rule renders its catalogue sentence and hint from the
    refusal's fields (plus ``extra``). An unknown rule -- or a refusal
    that carries no name -- returns the raw name (or ``"refused"``) as
    the sentence and the producer's technical message as the hint, so
    nothing is ever hidden and nothing is ever invented; the coverage
    test forbids this path for every name the codebase emits.
    """
    rule = name_of(obj)
    params = params_of(obj)
    params.update(extra)
    if rule is not None and is_catalogued(rule):
        return {"sentence": render(rule, **params),
                "hint": hint(rule, **params),
                "rule": rule}
    return {"sentence": rule or "refused",
            "hint": technical(obj),
            "rule": rule or ""}


__all__ = ["CATALOG_PATH", "catalogue", "names", "is_catalogued", "render",
           "hint", "fill", "shown", "derive", "name_of", "technical",
           "params_of", "explain"]
