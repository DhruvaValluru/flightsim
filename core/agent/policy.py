"""The authority limits, enforced in code (contracts §7; brainstorm
§7.2). Deterministic; no model; every denial BY NAME.

| Rule | Refusal |
|---|---|
| a field whose source is ``user``, ``inferred`` or ``sampled`` is never written; a system-chosen field moves only through a recorded edit | ``authority.stated_field`` |
| ``run``, ``render`` and ``export`` need the token ``validate()`` minted for that exact spec digest | ``authority.validation_token`` |
| a spec carrying a refusal is not run | ``authority.refusal_is_not_a_run`` |
| max tool calls, max re-samples per slot, max wall time | ``authority.budget`` |

The checks are one function, :meth:`Policy.check`, that the tool layer
calls BEFORE every tool with the tool's name and its keyword arguments
(and, for the token tools, the spec digest the campaign or run
carries). It raises :class:`Denial` -- an exception with a
``constraint`` so ``core.messages.explain`` renders the catalogue
sentence -- and the tool layer returns that as structured data and
writes it to the trace. There is no way to call a tool that skips the
check except by not using the tool layer, which the tests do not do.

The stated-field rule compares PROVENANCE, not values alone: the
reference is the spec as ``compile`` produced it (every field with its
source); a later spec input must carry every user / inferred / sampled
field of the reference with the same value and the same source, and
may not add a field claiming those sources (an assistant cannot state
on the person's behalf); a system-chosen field (default / derived /
model) may differ only as a recorded plan edit -- source ``derived`` (or a
model's declared ``model``) with a non-empty ``from``; a default whose
value changed with no edit recorded is a rewrite and is denied.

The token check is this module's OWN re-computation of the digest the
tool layer mints (``sha256(spec_digest + "validated")``): the thing that
produces the token is not the thing that verifies it. A token is
minted only by ``validate()`` and only for a spec with no refusal, so
"has a token" means "validated exactly as it is now".

Not claimed: a cryptographic secret -- the token is HMAC-free by
contract and stops an assistant from skipping validation, not an
adversary who reads this file; a check on what the capture subprocess
does with the spec it is handed (the verifier's job); enforcement
inside an external agent runtime's hook (brainstorm §7.2 asks for the
limit twice -- this is the first, in the tools; the second is the
runtime's, not written here).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

RULE_STATED_FIELD = "authority.stated_field"
RULE_TOKEN = "authority.validation_token"
RULE_REFUSAL = "authority.refusal_is_not_a_run"
RULE_BUDGET = "authority.budget"
RULES = (RULE_STATED_FIELD, RULE_TOKEN, RULE_REFUSAL, RULE_BUDGET)

#: Sources an assistant may never write (contracts §5.1, §7).
STATED_SOURCES = ("user", "inferred", "sampled")
#: Sources the system chooses (contracts §5.1: plannable).
SYSTEM_SOURCES = ("default", "derived", "model")
#: Sources a RECORDED edit leaves a moved field with: a planner's
#: ``derived`` or a model's declared ``model``, each quoting why. A
#: ``default`` whose value changed is a rewrite, not an edit.
EDIT_SOURCES = ("derived", "model")
#: Tools whose input carries a whole spec (checked for stated moves).
SPEC_TOOLS = ("validate", "plan_campaign")
#: Tools that need the validation token.
TOKEN_TOOLS = ("run", "render", "export")
#: The one rule name the token binds to.
TOKEN_SALT = "validated"


class Denial(Exception):
    """A named denial (``constraint`` is the rule); never a stack trace."""

    def __init__(self, constraint: str, message: str,
                 detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.constraint = constraint
        self.message = message
        self.detail = dict(detail or {})

    def explain(self) -> Dict[str, str]:
        """``{"sentence", "hint", "rule"}`` from the catalogue."""
        from core.messages import explain

        return explain(self)

    def as_output(self) -> Dict[str, Any]:
        words = self.explain()
        return {"refused": self.constraint, "sentence": words["sentence"],
                "hint": words["hint"] or self.message, "message": self.message,
                "detail": self.detail}


@dataclass
class Budget:
    """What the loop may spend. Counted by the policy on every
    attempted call (a denied call counts: a caller that is denied
    forever is stopped by the budget, not by patience)."""

    max_calls: int = 60
    max_resamples_per_slot: int = 3
    max_wall_seconds: float = 1800.0


# -- provenance, flattened ------------------------------------------------------

def flatten(spec_dict: Dict[str, Any], prefix: str = "") -> Dict[str, Dict[str, Any]]:
    """Every provenanced field of a spec dict as ``{path: {"value",
    "source", "from"}}``. A field is any mapping with both ``value`` and
    ``source`` keys; lists index as ``cameras[0]``. Written here from
    the spec's documented shape (fields.py ``Quantity.to_dict``), not
    imported from it."""
    out: Dict[str, Dict[str, Any]] = {}

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if "value" in node and "source" in node and isinstance(node["source"], str):
                out[path] = {"value": node["value"], "source": node["source"],
                             "from": node.get("from")}
                return
            for key, item in node.items():
                walk(item, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(spec_dict, prefix)
    return out


def stated_moves(reference: Dict[str, Dict[str, Any]],
                 candidate: Dict[str, Dict[str, Any]],
                 allow_new: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
    """The provenance violations between two flattened specs: a stated
    field moved or dropped, a field newly claiming a stated source
    (unless its source is in ``allow_new`` -- the sampler adds
    ``sampled`` leaves to a case), a system-chosen field moved without
    a recorded edit."""
    moves: List[Dict[str, Any]] = []
    for path, was in reference.items():
        now = candidate.get(path)
        if was["source"] in STATED_SOURCES:
            if now is None:
                moves.append({"path": path, "kind": "removed", "was": was})
            elif now["value"] != was["value"] or now["source"] != was["source"]:
                moves.append({"path": path, "kind": "moved", "was": was, "now": now})
        elif now is not None:
            if now["source"] in allow_new:
                continue                    # the sampler's own draw of a leaf
            if now["source"] in STATED_SOURCES:
                moves.append({"path": path, "kind": "stated on the person's behalf",
                              "was": was, "now": now})
            elif now["value"] != was["value"] and (
                    now["source"] not in EDIT_SOURCES or not now.get("from")):
                moves.append({"path": path, "kind": "moved without a recorded edit",
                              "was": was, "now": now})
    for path, now in candidate.items():
        if path in reference:
            continue
        if now["source"] in STATED_SOURCES and now["source"] not in allow_new:
            moves.append({"path": path, "kind": "stated on the person's behalf",
                          "now": now})
    return moves


def expected_token(spec_digest: str) -> str:
    """The policy's OWN computation of the token ``validate()`` mints
    for a digest. Kept apart from ``tools.mint_token`` on purpose."""
    return hashlib.sha256((str(spec_digest) + TOKEN_SALT).encode()).hexdigest()


# -- the policy -----------------------------------------------------------------------

@dataclass
class Policy:
    """The deterministic checks, with the state they need: the
    reference provenance (from ``compile``), the digests known to carry
    a refusal, the call count, the clock, the re-samples per slot."""

    budget: Budget = field(default_factory=Budget)
    clock: Callable[[], float] = time.monotonic
    reference: Optional[Dict[str, Dict[str, Any]]] = None
    reference_digest: Optional[str] = None
    refused: Dict[str, List[Dict[str, str]]] = field(default_factory=dict)
    calls: int = 0
    started: Optional[float] = None
    resamples: Dict[str, int] = field(default_factory=dict)

    # -- what the tools tell the policy ----------------------------------------------

    def note_compiled(self, spec_dict: Dict[str, Any], spec_digest: str,
                      refusals: List[Any]) -> None:
        """A compile happened: its spec's provenance is the reference
        every later spec input is compared with; its refusals mark the
        digest as not runnable."""
        self.reference = flatten(spec_dict)
        self.reference_digest = str(spec_digest)
        if refusals:
            self.note_refused(spec_digest, refusals)

    def note_refused(self, spec_digest: str, refusals: List[Any]) -> None:
        """Remember that ``spec_digest`` carries these refusals: names, or
        dicts with ``constraint`` and the rendered ``sentence`` (kept so
        the denial can quote the refusal's own sentence)."""
        kept = self.refused.setdefault(str(spec_digest), [])
        for item in refusals:
            if isinstance(item, dict):
                name, sentence = str(item.get("constraint") or ""), str(item.get("sentence") or "")
            else:
                name, sentence = str(item or ""), ""
            if name and not any(k["constraint"] == name for k in kept):
                kept.append({"constraint": name, "sentence": sentence})
        if not kept:
            self.refused.pop(str(spec_digest), None)

    def note_validated(self, spec_digest: str) -> None:
        self.refused.pop(str(spec_digest), None)

    # -- the checks ------------------------------------------------------------------

    def check(self, tool: str, kwargs: Dict[str, Any], *,
              spec_digest: Optional[str] = None) -> Dict[str, Any]:
        """Run every rule that applies to ``tool``; raise :class:`Denial`
        on the first that fails, else return ``{"ok": True}``.
        ``spec_digest`` is the digest the campaign or run named by the
        arguments carries (resolved by the tool layer; None when it
        could not be)."""
        self.calls += 1
        if self.started is None:
            self.started = self.clock()
        self._check_budget()
        if tool in SPEC_TOOLS and isinstance(kwargs.get("spec"), dict):
            self.check_spec(kwargs["spec"])
        if tool == "run":
            self._check_not_refused(spec_digest)
        if tool in TOKEN_TOOLS:
            self._check_token(kwargs.get("validation_token"), spec_digest)
        if tool == "sample":
            self._check_resamples(kwargs)
        return {"ok": True}

    def _check_budget(self) -> None:
        if self.calls > int(self.budget.max_calls):
            raise Denial(constraint="authority.budget",
                         message=f"{self.calls} tool calls; the allowance is "
                         f"{self.budget.max_calls}",
                         detail={"calls": self.calls, "max_calls": self.budget.max_calls})
        elapsed = self.clock() - float(self.started or 0.0)
        if elapsed > float(self.budget.max_wall_seconds):
            raise Denial(constraint="authority.budget",
                         message=f"{elapsed:.0f} s elapsed; the allowance is "
                         f"{self.budget.max_wall_seconds:g} s",
                         detail={"elapsed_seconds": round(elapsed, 3),
                                 "max_wall_seconds": self.budget.max_wall_seconds})

    def check_spec(self, spec_dict: Dict[str, Any],
                   allow_new: Tuple[str, ...] = ()) -> List[Dict[str, Any]]:
        """Compare a spec input with the reference; deny by name when a
        stated field moved. With no reference yet (no compile in this
        session) the spec's own provenance becomes the reference."""
        candidate = flatten(spec_dict)
        if self.reference is None:
            self.reference = candidate
            return []
        moves = stated_moves(self.reference, candidate, allow_new=allow_new)
        if moves:
            first = moves[0]
            raise Denial(
                constraint="authority.stated_field",
                message=f"{first['path']} {first['kind']}: "
                + (f"{first['was']['source']}-stated {first['was']['value']!r}"
                   if "was" in first else "")
                + (f" -> {first['now']['source']} {first['now']['value']!r}"
                   if "now" in first else "")
                + (f"; {len(moves) - 1} more" if len(moves) > 1 else ""),
                detail={"moves": moves})
        return moves

    def _check_not_refused(self, spec_digest: Optional[str]) -> None:
        kept = self.refused.get(str(spec_digest)) if spec_digest else None
        if kept:
            from core.messages import render

            first = kept[0]
            sentence = first["sentence"] or render(first["constraint"])
            raise Denial(constraint="authority.refusal_is_not_a_run",
                         message=f"{first['constraint']}: {sentence}",
                         detail={"spec_digest": spec_digest,
                                 "refusals": [k["constraint"] for k in kept]})

    def _check_token(self, token: Any, spec_digest: Optional[str]) -> None:
        if not token or not isinstance(token, str):
            raise Denial(constraint="authority.validation_token",
                         message="no validation_token was given; validate() mints one",
                         detail={"spec_digest": spec_digest})
        if spec_digest is None or token != expected_token(spec_digest):
            raise Denial(constraint="authority.validation_token",
                         message="the validation_token does not match the spec this step would "
                         "run; validate() the spec as it is now",
                         detail={"spec_digest": spec_digest})

    def _check_resamples(self, kwargs: Dict[str, Any]) -> None:
        start = kwargs.get("start")
        if start is None:
            return                          # a fresh draw of the next slots
        key = f"{kwargs.get('campaign_id')}:{int(start)}"
        self.resamples[key] = self.resamples.get(key, 0) + 1
        if self.resamples[key] > int(self.budget.max_resamples_per_slot):
            raise Denial(constraint="authority.budget",
                         message=f"slot {start} of campaign {kwargs.get('campaign_id')} re-sampled "
                         f"{self.resamples[key]} times; the allowance is "
                         f"{self.budget.max_resamples_per_slot}",
                         detail={"slot": key, "resamples": self.resamples[key]})


__all__ = ["RULES", "RULE_STATED_FIELD", "RULE_TOKEN", "RULE_REFUSAL", "RULE_BUDGET",
           "STATED_SOURCES", "SYSTEM_SOURCES", "EDIT_SOURCES", "SPEC_TOOLS", "TOKEN_TOOLS",
           "Denial", "Budget", "Policy", "flatten", "stated_moves", "expected_token"]
