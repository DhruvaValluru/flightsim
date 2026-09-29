"""``trace.jsonl``: one line per tool call, beside the dataset
(contracts §7; brainstorm §7.3).

Each line is ``{t, tool, input, output, reason, policy}``: the UTC
time, the tool's name, what it was given (a spec is recorded as its
digest, not its whole dict, so a trace stays readable; everything
else verbatim), what came back (a denial is ``{"refused": name,
"sentence", "hint"}``), the caller's stated reason in one sentence,
and the policy check's result (``{"ok": true}`` or ``{"ok": false,
"rule": name, "sentence": ...}``). The controller's own decisions
(an escalation, a re-sample) are lines whose ``tool`` is
``"controller"`` so the file reads as the whole story.

Append-only, flushed per line, tolerant of a truncated last line --
the campaign ledger's shape. The trace is the audit the plan asks
for; it is not a second copy of the ledger and never says what a run
produced beyond what the tool returned.

Not claimed: OpenTelemetry spans (brainstorm §7.3 names them as an
option; nothing here emits one); a viewer.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TRACE = "trace.jsonl"

#: Keys whose value is a whole spec; the trace keeps their digest.
SPEC_KEYS = ("spec",)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def abbreviate(value: Any) -> Any:
    """A tool input as the trace records it: a spec dict becomes
    ``{"spec_digest": ...}``; everything else is kept verbatim (JSON
    default ``str`` for anything exotic)."""
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if key in SPEC_KEYS and isinstance(item, dict):
                out[key] = {"spec_digest": spec_digest(item)}
            else:
                out[key] = abbreviate(item)
        return out
    if isinstance(value, (list, tuple)):
        return [abbreviate(v) for v in value]
    return value


def spec_digest(spec_dict: Dict[str, Any]) -> str:
    """The digest of a spec given as a dict, computed the way
    ``ScenarioSpec.digest`` does (canonical JSON without ``prompt``
    and ``notes``) -- re-implemented here so the trace never imports
    the producer to describe what it was handed."""
    import hashlib

    payload = {k: v for k, v in spec_dict.items() if k not in ("prompt", "notes")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Trace:
    """Append-only JSONL beside the campaign."""

    def __init__(self, path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, tool: str, input: Dict[str, Any], output: Any,
               reason: str = "", policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = {
            "t": utc_now(),
            "tool": str(tool),
            "input": abbreviate(dict(input or {})),
            "output": abbreviate(output),
            "reason": str(reason or ""),
            "policy": dict(policy) if policy is not None else {"ok": True},
        }
        line = json.dumps(row, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        return row

    def rows(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        out: List[Dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
        return out

    def denials(self) -> List[Dict[str, Any]]:
        """Every line whose policy check said no."""
        return [r for r in self.rows()
                if isinstance(r.get("policy"), dict) and r["policy"].get("ok") is False]

    def calls(self, tool: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.rows()
        return [r for r in rows if tool is None or r.get("tool") == tool]
