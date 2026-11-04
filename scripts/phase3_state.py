#!/usr/bin/env python3
"""Read and update docs/phase3/state/<box>.json without composing JSON by hand.

  phase3_state.py set A4 stage=planned letter=A unit=A4
  phase3_state.py set A4 budget_used=12 needs_windows='["render"]'   # values parse as JSON when they can
  phase3_state.py get A4 [key]
  phase3_state.py incr A4 budget_used [n]
  phase3_state.py append A4 failures "packet path"
  phase3_state.py claim A4 flightsim/capture.py webapp/runs.py       # exit 1 if another box holds one
  phase3_state.py release A4
  phase3_state.py list [letter]

One writer at a time: the caller serialises. `set` merges keys; it never
deletes. Every write stamps `updated`.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "docs" / "phase3" / "state"


def path(box: str) -> Path:
    return STATE / f"{box}.json"


def load(box: str) -> dict:
    p = path(box)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def save(box: str, d: dict) -> None:
    d["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STATE.mkdir(parents=True, exist_ok=True)
    path(box).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse(v: str):
    try:
        return json.loads(v)
    except json.JSONDecodeError:
        return v


def main(a: list[str]) -> int:
    if len(a) < 1:
        print(__doc__); return 2
    cmd = a[0]
    if cmd == "list":
        for p in sorted(STATE.glob("*.json")):
            if p.stem == "peers" or (len(a) > 1 and not p.stem.startswith(a[1])):
                continue
            d = load(p.stem)
            print(f"{p.stem:6} stage={d.get('stage','-'):10} verdict={d.get('verdict','-'):6} budget={d.get('budget_used','-')} failures={len(d.get('failures',[]))} claims={len(d.get('claims',[]))}")
        return 0
    if len(a) < 2:
        print(__doc__); return 2
    box = a[1]
    d = load(box)
    if cmd == "get":
        if len(a) > 2:
            v = d.get(a[2]); print(json.dumps(v) if not isinstance(v, str) else v)
        else:
            print(json.dumps(d, indent=2, sort_keys=True))
        return 0
    if cmd == "set":
        for kv in a[2:]:
            k, _, v = kv.partition("=")
            d[k] = parse(v)
        save(box, d); return 0
    if cmd == "incr":
        n = int(a[3]) if len(a) > 3 else 1
        d[a[2]] = int(d.get(a[2], 0) or 0) + n
        save(box, d); print(d[a[2]]); return 0
    if cmd == "append":
        d.setdefault(a[2], [])
        if not isinstance(d[a[2]], list):
            d[a[2]] = [d[a[2]]]
        d[a[2]].append(parse(a[3]))
        save(box, d); return 0
    if cmd == "claim":
        want = a[2:]
        for p in STATE.glob("*.json"):
            if p.stem in (box, "peers"):
                continue
            o = load(p.stem)
            if (o.get("stage") or "") in ("built", "pushed", "ticked") or o.get("verdict") == "PASS":
                continue
            held = set(o.get("claims", [])) & set(want)
            if held:
                print(f"BUSY {p.stem} holds {sorted(held)}"); return 1
        d["claims"] = sorted(set(d.get("claims", [])) | set(want))
        save(box, d); print("CLAIMED", d["claims"]); return 0
    if cmd == "release":
        d["claims"] = []
        save(box, d); return 0
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
