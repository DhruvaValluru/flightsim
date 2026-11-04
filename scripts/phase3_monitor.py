#!/usr/bin/env python3
"""Phase 3 progress terminals. Read-only. Standard library only.

  python scripts/phase3_monitor.py progress   # window 1: bars per letter, machines, caps
  python scripts/phase3_monitor.py mac        # window 2: live command stream from the Mac agents
  python scripts/phase3_monitor.py windows    # window 3: Windows stream + messages in flight

Reads docs/phase3/events_mac.log and docs/phase3/events_windows.log, the box
state files in docs/phase3/state/, and tasks/phase3_checklist.md (the tick-box sheet). Every 30 s it
runs `git fetch origin <branch>` and reads the other machine's log from
origin/<branch> so Windows lines appear on the Mac without a pull. It never
writes to the repo and never sends messages.

Letters A..F and their boxes come from tasks/phase3_checklist.md ("- [ ] **A1 · ...").
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
P3 = ROOT / "docs" / "phase3"
TODO = ROOT / "tasks" / "phase3_checklist.md"
FETCH_EVERY = 30
STAGES = ["planned", "aligned", "built", "ticked"]
CAP_BOX, CAP_LETTER = 3, 5

CSI = "\x1b["
def c(code: str, s: str) -> str:
    return f"{CSI}{code}m{s}{CSI}0m"
BOLD, DIM, RED, GREEN, YEL, BLUE, CYAN = "1", "2", "31", "32", "33", "34", "36"


def branch() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "HEAD"


def git_fetch(br: str) -> None:
    subprocess.call(["git", "fetch", "-q", "origin", br], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def read_log_local(name: str) -> list[dict]:
    p = P3 / f"events_{name}.log"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def read_log_origin(name: str, br: str) -> list[dict]:
    try:
        txt = subprocess.check_output(["git", "show", f"origin/{br}:docs/phase3/events_{name}.log"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    out = []
    for line in txt.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def merged_log(name: str, br: str) -> list[dict]:
    seen, out = set(), []
    for ev in read_log_local(name) + read_log_origin(name, br):
        key = (ev.get("t"), ev.get("agent"), ev.get("kind"), ev.get("cmd"), ev.get("note"))
        if key in seen:
            continue
        seen.add(key)
        out.append(ev)
    out.sort(key=lambda e: e.get("t", 0))
    return out


def boxes_by_letter() -> dict[str, list[tuple[str, bool]]]:
    letters: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    if not TODO.exists():
        return letters
    for m in re.finditer(r"- \[( |x|X)\] \*\*([A-F])(\d+)", TODO.read_text(encoding="utf-8")):
        letters[m.group(2)].append((m.group(2) + m.group(3), m.group(1).lower() == "x"))
    return letters


def box_states() -> dict[str, dict]:
    out = {}
    for p in (P3 / "state").glob("*.json"):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            out[p.stem] = {}
    return out


def stage_index(box: str, ticked: bool, st: dict) -> int:
    if ticked:
        return 4
    s = (st.get("stage") or "").lower()
    if s in ("built", "pushed", "proving", "prove", "lettertest", "sync"):
        return 3
    if s in ("aligned", "build", "building"):
        return 2
    if s in ("planned", "align", "aligning"):
        return 1
    return 0


def bar(n: int, total: int, width: int) -> str:
    if total == 0:
        return c(DIM, "·" * width)
    fill = int(round(width * n / total))
    return c(GREEN, "█" * fill) + c(DIM, "░" * (width - fill))


def fmt_t(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def elapsed(t: float) -> str:
    s = int(time.time() - t)
    return f"{s//3600}h{(s%3600)//60:02d}m" if s >= 3600 else f"{s//60}m{s%60:02d}s"


def current_activity(events: list[dict]) -> list[str]:
    """Open 'start' events with no matching 'end' yet, newest last."""
    open_cmds: dict[tuple, dict] = {}
    for ev in events:
        key = (ev.get("agent"), ev.get("box"), ev.get("cmd"))
        if ev.get("kind") == "start":
            open_cmds[key] = ev
        elif ev.get("kind") == "end":
            open_cmds.pop(key, None)
    lines = []
    for ev in sorted(open_cmds.values(), key=lambda e: e.get("t", 0))[-4:]:
        lines.append(f"{c(YEL, ev.get('agent',''))} {ev.get('box','')} {c(DIM, (ev.get('cmd') or '')[:60])} {c(CYAN, elapsed(ev.get('t', time.time())))}")
    return lines


def last_message(events: list[dict]) -> str:
    for ev in reversed(events):
        if ev.get("stage") == "msg" or (ev.get("note") or "").startswith("msg "):
            return f"{fmt_t(ev.get('t',0))} {ev.get('machine','')}: {ev.get('note','')}"
    return c(DIM, "none yet")


def fail_counts(events: list[dict]) -> tuple[Counter, Counter]:
    per_box, per_letter = Counter(), Counter()
    for ev in events:
        if ev.get("kind") == "note" and (ev.get("note") or "").startswith("FAIL"):
            b = ev.get("box") or ""
            if b:
                per_box[b] += 1
                per_letter[b[0]] += 1
    return per_box, per_letter


def screen_progress(mac: list[dict], win: list[dict], br: str) -> str:
    cols = shutil.get_terminal_size((100, 30)).columns
    letters = boxes_by_letter()
    states = box_states()
    width = max(20, min(40, cols - 50))
    out = [c(BOLD, f"FlightSim Phase 3 · progress · branch {br} · {time.strftime('%H:%M:%S')}"), ""]
    for L in "ABCDEF":
        bx = letters.get(L, [])
        total = len(bx)
        counts = Counter()
        for name, ticked in bx:
            counts[stage_index(name, ticked, states.get(name, {}))] += 1
        ticked_n = counts[4]
        built_n = ticked_n + counts[3]
        aligned_n = built_n + counts[2]
        planned_n = aligned_n + counts[1]
        out.append(f"  {c(BOLD, L)}  {bar(ticked_n, total, width)}  {ticked_n:2d}/{total:<2d} ticked  "
                   f"{c(DIM, f'planned {planned_n}  aligned {aligned_n}  built {built_n}')}")
    out.append("")
    out.append(c(BOLD, "Mac now"))
    out += ["  " + l for l in (current_activity(mac) or [c(DIM, "idle")])]
    out.append(c(BOLD, "Windows now"))
    out += ["  " + l for l in (current_activity(win) or [c(DIM, "idle")])]
    out.append("")
    out.append(c(BOLD, "Last message between machines: ") + last_message(mac + win))
    pb, pl = fail_counts(mac + win)
    if pb:
        out.append(c(BOLD, "Failures vs caps"))
        for b, n in sorted(pb.items()):
            col = RED if n >= CAP_BOX else YEL
            out.append(f"  {b:<4} {c(col, str(n))}/{CAP_BOX}")
        for L, n in sorted(pl.items()):
            col = RED if n >= CAP_LETTER else YEL
            out.append(f"  letter {L} {c(col, str(n))}/{CAP_LETTER}")
    out.append("")
    out.append(c(DIM, "read-only · fetches origin every 30 s · Ctrl-C to close"))
    return "\n".join(out)


def screen_stream(events: list[dict], title: str) -> str:
    rows = shutil.get_terminal_size((100, 30)).lines
    cols = shutil.get_terminal_size((100, 30)).columns
    out = [c(BOLD, f"FlightSim Phase 3 · {title} · {time.strftime('%H:%M:%S')}"), ""]
    for ev in events[-(rows - 4):]:
        kind = ev.get("kind")
        t = fmt_t(ev.get("t", 0))
        who = f"{ev.get('agent','')}/{ev.get('box','') or '-'}"
        if kind == "start":
            line = f"{t} {c(YEL, who):<28} ▶ {ev.get('cmd','')}"
        elif kind == "end":
            rc = ev.get("exit", 0)
            mark = c(GREEN, f"exit {rc}") if rc == 0 else c(RED, f"exit {rc}")
            line = f"{t} {c(YEL, who):<28} ■ {mark} {c(DIM, str(ev.get('secs','')) + 's')} {ev.get('cmd','')[:cols-60]}"
        else:
            note = ev.get("note", "")
            col = RED if note.startswith("FAIL") else (GREEN if note.startswith("PASS") else BLUE)
            line = f"{t} {c(YEL, who):<28} · {c(col, note)}"
        out.append(line[:cols + 40])
    return "\n".join(out)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "progress"
    br = os.environ.get("FLIGHTSIM_BRANCH") or branch()
    last_fetch = 0.0
    try:
        while True:
            if time.time() - last_fetch > FETCH_EVERY:
                git_fetch(br)
                last_fetch = time.time()
            mac = merged_log("mac", br)
            win = merged_log("windows", br)
            if mode == "mac":
                body = screen_stream(mac, "Mac agents, live commands")
            elif mode == "windows":
                body = screen_stream(win, "Windows agents, live commands and messages")
            else:
                body = screen_progress(mac, win, br)
            sys.stdout.write(f"{CSI}2J{CSI}H" + body + "\n")
            sys.stdout.flush()
            time.sleep(2)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
