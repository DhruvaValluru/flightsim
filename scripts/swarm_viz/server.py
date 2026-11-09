#!/usr/bin/env python3
"""Live swarm dashboard: a local HTTP server that serves index.html and /state.json.

Everything it shows comes from local files and local commands:

* Claude Code workflow runs under ~/.claude/projects/<project>/<session>/subagents/workflows/wf_*/
  (journal.jsonl, agent-*.meta.json, agent-*.jsonl) plus the run records and scripts in
  <session>/workflows/.
* git worktrees of this repository (``git worktree list --porcelain``), commits ahead of the
  base branch and uncommitted files per worktree.
* ruflo: its JSON stores .claude-flow/agents/store.json, tasks/store.json, swarm/swarm-state.json
  and daemon-state.json, and the memory stores .swarm/*.db, all read strictly read-only. The
  ``npx ruflo@3.74.1 agent list / task list / ...`` CLI is opt-in (``--ruflo-cli``): every call
  appends to the git-tracked .claude-flow/policy/state.json, so polling it would grow that file.
* the background pytest log runs/visual/logs/pytest_merged.log.

It never contacts GitHub, a PR, or CI. Python stdlib only.

Run:  python scripts/swarm_viz/server.py [--port 8787]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = "claude/vibrant-gauss-olema4"
RUFLO_PKG = "ruflo@3.74.1"

ACTIVE_WINDOW_S = 45.0  # an agent transcript touched within this many seconds is "active"
RUFLO_TTL_S = 20.0  # npx is slow: ruflo CLI results are reused for this long
GIT_TTL_S = 10.0
TAIL_BYTES = 256 * 1024  # how much of a transcript tail to scan for tool calls
TAIL_BYTES_MAX = 2 * 1024 * 1024
HEAD_BYTES = 64 * 1024
MEMORY_VALUE_MAX = 4000
LANE_PREFIX = "visual-overhaul/"

_TS_RE = re.compile(r'"timestamp"\s*:\s*"([0-9T:\.\-]+Z)"')
_PROGRESS_RE = re.compile(r"^([\.FEsxX]+)\s*(\[\s*\d+%\])?\s*$")
_SUMMARY_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)")
_SUMMARY_LINE_RE = re.compile(r"^=+ .*\bin [\d\.]+s.*=+$")


# --------------------------------------------------------------------------- helpers


def _iso_to_ms(text: str | None) -> int | None:
    if not text:
        return None
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    out: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except OSError:
        pass
    return out


def summarize_tool_input(name: str, inp) -> str:
    """One readable line for a tool_use input."""
    if not isinstance(inp, dict):
        return str(inp)[:160]
    for key in ("command", "file_path", "pattern", "query", "url", "path", "key", "skill", "prompt"):
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            text = val.strip().replace("\n", " ")
            desc = inp.get("description")
            if key == "command" and isinstance(desc, str) and desc:
                return f"{desc[:70]} | {text[:110]}"
            return text[:180]
    if isinstance(inp.get("description"), str):
        return inp["description"][:180]
    try:
        return json.dumps(inp, ensure_ascii=False)[:180]
    except (TypeError, ValueError):
        return str(inp)[:180]


def _tool_uses_from_lines(lines: list[str]) -> list[dict]:
    calls: list[dict] = []
    for line in lines:
        if '"tool_use"' not in line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        ts = obj.get("timestamp")
        for part in content:
            if isinstance(part, dict) and part.get("type") == "tool_use":
                name = str(part.get("name", "?"))
                calls.append({"name": name, "input": summarize_tool_input(name, part.get("input")), "ts": ts})
    return calls


def transcript_tail_tools(path: Path, size: int, want: int = 5) -> list[dict]:
    """The last ``want`` tool_use calls in an agent transcript, read from the file's tail."""
    chunk = TAIL_BYTES
    calls: list[dict] = []
    while True:
        start = max(0, size - chunk)
        try:
            with path.open("rb") as fh:
                fh.seek(start)
                data = fh.read(size - start)
        except OSError:
            return []
        lines = data.decode("utf-8", errors="replace").splitlines()
        if start > 0 and lines:
            lines = lines[1:]  # first line is probably cut
        calls = _tool_uses_from_lines(lines)
        if len(calls) >= want or start == 0 or chunk >= TAIL_BYTES_MAX:
            break
        chunk *= 4
    return calls[-want:]


def transcript_first_ts(path: Path) -> int | None:
    try:
        with path.open("rb") as fh:
            head = fh.read(HEAD_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    m = _TS_RE.search(head)
    return _iso_to_ms(m.group(1)) if m else None


def parse_script_meta(text: str) -> dict:
    """name, description and phase titles from a workflow script's ``export const meta``."""
    idx = text.find("export const meta")
    block = text[idx: idx + 4000] if idx >= 0 else text[:4000]
    end = block.find("\n}\n")
    if end > 0:
        block = block[: end + 2]
    name = re.search(r"\bname\s*:\s*['\"`]([^'\"`]+)['\"`]", block)
    desc = re.search(r"\bdescription\s*:\s*['\"`]([^'\"`]+)['\"`]", block)
    phases = re.findall(r"\btitle\s*:\s*['\"`]([^'\"`]+)['\"`]", block)
    return {
        "name": name.group(1) if name else None,
        "description": desc.group(1) if desc else None,
        "phases": phases,
    }


class _TailCache:
    """Caches per-transcript parsing keyed by (size, mtime) so a 3 s refresh stays cheap."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[tuple[int, float], dict]] = {}
        self._lock = threading.Lock()

    def get(self, path: Path, size: int, mtime: float) -> dict:
        key = str(path)
        sig = (size, mtime)
        with self._lock:
            hit = self._data.get(key)
            if hit and hit[0] == sig:
                return hit[1]
            first = hit[1].get("first_ts") if hit else None
        info = {
            "tools": transcript_tail_tools(path, size),
            "first_ts": first if first is not None else transcript_first_ts(path),
        }
        with self._lock:
            self._data[key] = (sig, info)
        return info


TAIL_CACHE = _TailCache()


# --------------------------------------------------------------------------- workflows


def collect_workflows(projects_root: Path, now: float | None = None, cache: _TailCache | None = None) -> dict:
    """Every session under ``projects_root`` with its workflow runs and their agents."""
    now = time.time() if now is None else now
    cache = cache or TAIL_CACHE
    sessions: list[dict] = []
    if not projects_root.is_dir():
        return {"sessions": sessions, "root": str(projects_root), "error": "projects root not found"}

    for sess_dir in sorted(p for p in projects_root.iterdir() if p.is_dir()):
        wf_root = sess_dir / "subagents" / "workflows"
        if not wf_root.is_dir():
            continue
        sess_jsonl = projects_root / f"{sess_dir.name}.jsonl"
        try:
            sess_mtime = sess_jsonl.stat().st_mtime
        except OSError:
            sess_mtime = 0.0
        scripts_dir = sess_dir / "workflows" / "scripts"
        scripts = sorted(scripts_dir.glob("*.js")) if scripts_dir.is_dir() else []
        runs = []
        for run_dir in sorted(wf_root.glob("wf_*")):
            if run_dir.is_dir():
                runs.append(_collect_run(run_dir, sess_dir, scripts, now, cache))
        last = max([sess_mtime] + [r["last_activity"] or 0 for r in runs]) if runs else sess_mtime
        sessions.append({
            "id": sess_dir.name,
            "mtime": sess_mtime,
            "last_activity": last,
            "runs": runs,
        })
    sessions.sort(key=lambda s: s["last_activity"], reverse=True)
    return {"sessions": sessions, "root": str(projects_root)}


def _collect_run(run_dir: Path, sess_dir: Path, scripts: list[Path], now: float, cache: _TailCache) -> dict:
    run_id = run_dir.name
    journal = _read_jsonl(run_dir / "journal.jsonl")
    started: dict[str, dict] = {}
    results: dict[str, dict] = {}
    failed: set[str] = set()
    launched = False
    for ev in journal:
        kind = ev.get("type")
        aid = ev.get("agentId")
        if kind == "launched":
            launched = True
        elif kind == "started" and aid:
            started[aid] = ev
        elif kind == "result" and aid:
            results[aid] = ev.get("result") if isinstance(ev.get("result"), dict) else {"value": ev.get("result")}
        elif kind == "failed" and aid:
            failed.add(aid)

    record = _read_json(sess_dir / "workflows" / f"{run_id}.json") or {}
    progress = {}
    for item in record.get("workflowProgress") or []:
        if isinstance(item, dict) and item.get("type") == "workflow_agent" and item.get("agentId"):
            progress[item["agentId"]] = item

    # script meta: a script named after this run, else the record's scriptPath, else the record text.
    meta = {"name": None, "description": None, "phases": []}
    script_path = None
    for s in scripts:
        if run_id in s.name:
            script_path = s
            break
    if script_path is None and record.get("scriptPath"):
        cand = Path(record["scriptPath"])
        if cand.is_file():
            script_path = cand
    if script_path is not None:
        try:
            meta = parse_script_meta(script_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    elif isinstance(record.get("script"), str):
        meta = parse_script_meta(record["script"])
    if record.get("workflowName") and not meta.get("name"):
        meta["name"] = record["workflowName"]
    if not meta.get("phases") and isinstance(record.get("phases"), list):
        meta["phases"] = [p.get("title") for p in record["phases"] if isinstance(p, dict)]

    agent_ids = set(started) | set(results) | set(failed)
    for meta_file in run_dir.glob("agent-*.meta.json"):
        agent_ids.add(meta_file.name[len("agent-"):-len(".meta.json")])
    for tr in run_dir.glob("agent-*.jsonl"):
        agent_ids.add(tr.name[len("agent-"):-len(".jsonl")])

    agents = []
    for aid in sorted(agent_ids):
        agents.append(_collect_agent(run_dir, aid, started.get(aid), results.get(aid), aid in failed,
                                     progress.get(aid), now, cache))
    agents.sort(key=lambda a: (a["start_ms"] or 0, a["id"]))

    phases = list(meta.get("phases") or [])
    for a in agents:
        if a["phase"] and a["phase"] not in phases:
            phases.append(a["phase"])

    status = record.get("status")
    if not status:
        if any(a["state"] == "active" for a in agents):
            status = "running"
        elif agents and all(a["state"] in ("done", "failed") for a in agents):
            status = "finished"
        elif launched:
            status = "running"
        else:
            status = "unknown"
    if status in ("completed", "killed", "failed"):
        # the run is over: an agent with neither a result nor a failure was stopped with it.
        for a in agents:
            if a["state"] in ("idle", "active"):
                a["state"] = "stopped"
                if a["mtime"] and not a["end_ms"]:
                    a["end_ms"] = int(a["mtime"] * 1000)
    mtimes = [a["mtime"] for a in agents if a["mtime"]]
    try:
        mtimes.append((run_dir / "journal.jsonl").stat().st_mtime)
    except OSError:
        pass
    if str(record.get("startTime", "")).isdigit():
        run_start = int(record["startTime"])
    else:
        starts = [a["start_ms"] for a in agents if a["start_ms"]]
        run_start = min(starts) if starts else None
    return {
        "id": run_id,
        "session": sess_dir.name,
        "name": meta.get("name") or run_id,
        "description": meta.get("description") or record.get("summary"),
        "phases": phases,
        "status": status,
        "start_ms": run_start,
        "duration_ms": record.get("durationMs"),
        "tokens": record.get("totalTokens"),
        "tool_calls": record.get("totalToolCalls"),
        "last_activity": max(mtimes) if mtimes else None,
        "agents": agents,
    }


def _collect_agent(run_dir: Path, aid: str, start_ev, result, is_failed: bool, prog, now: float,
                   cache: _TailCache) -> dict:
    meta = _read_json(run_dir / f"agent-{aid}.meta.json") or {}
    tr = run_dir / f"agent-{aid}.jsonl"
    try:
        st = tr.stat()
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, None
    info = cache.get(tr, size, mtime) if mtime is not None else {"tools": [], "first_ts": None}
    prog = prog or {}
    label = (start_ev or {}).get("label") or meta.get("description") or prog.get("label") or aid
    phase = (start_ev or {}).get("phase") or meta.get("workflowPhase") or prog.get("phaseTitle")

    age = max(0.0, now - mtime) if mtime is not None else None
    if is_failed or prog.get("state") == "failed" or meta.get("status") == "failed":
        state = "failed"
    elif result is not None:
        state = "done"
    elif age is not None and age < ACTIVE_WINDOW_S:
        state = "active"
    else:
        state = "idle"

    start_ms = prog.get("startedAt") or info.get("first_ts")
    end_ms = None
    if state in ("done", "failed"):
        if prog.get("startedAt") and prog.get("durationMs"):
            end_ms = prog["startedAt"] + prog["durationMs"]
        elif mtime is not None:
            end_ms = int(mtime * 1000)
    tools = info.get("tools") or []
    if not tools and prog.get("lastToolName"):
        tools = [{"name": prog["lastToolName"], "input": prog.get("lastToolSummary") or "", "ts": None}]
    result = result or {}
    commits = result.get("commits") or result.get("new_commits") or []
    if not isinstance(commits, list):
        commits = [str(commits)]
    fixed = result.get("fixed") if isinstance(result.get("fixed"), list) else []
    summary = result.get("summary") if isinstance(result.get("summary"), str) else None
    return {
        "id": aid,
        "label": label,
        "phase": phase,
        "state": state,
        "meta_status": meta.get("status"),
        "worktree": meta.get("worktreePath"),
        "branch": result.get("branch") if isinstance(result.get("branch"), str) else None,
        "transcript_bytes": size,
        "mtime": mtime,
        "age_s": round(age, 1) if age is not None else None,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "tokens": prog.get("tokens"),
        "tool_calls": prog.get("toolCalls"),
        "last_tools": tools,
        "commits": [str(c) for c in commits][:40],
        "fixed": [str(f)[:300] for f in fixed][:20],
        "summary": summary[:1500] if summary else None,
    }


# --------------------------------------------------------------------------- git


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 30.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
                              timeout=timeout, env={**os.environ, "npm_config_update_notifier": "false",
                                                    "NO_COLOR": "1", "FORCE_COLOR": "0"})
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, f"{type(exc).__name__}: {exc}"


def parse_worktree_porcelain(text: str) -> list[dict]:
    out: list[dict] = []
    cur: dict | None = None
    for line in text.splitlines():
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "branch": None, "head": None, "locked": False}
            out.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].removeprefix("refs/heads/")
        elif line == "detached":
            cur["branch"] = None
        elif line.startswith("locked"):
            cur["locked"] = True
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return out


def collect_git(repo: Path, base: str, runner=_run) -> dict:
    rc, out = runner(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
    if rc != 0:
        return {"error": out.strip()[:300], "worktrees": [], "base": base}
    wts = parse_worktree_porcelain(out)
    for wt in wts:
        wt["ahead"] = None
        wt["dirty"] = None
        wt["commits"] = []
        if wt.get("branch") and wt["branch"] != base:
            rc, cnt = runner(["git", "-C", str(repo), "rev-list", "--count", f"{base}..{wt['branch']}"])
            if rc == 0 and cnt.strip().isdigit():
                wt["ahead"] = int(cnt.strip())
            if wt["ahead"]:
                rc, log = runner(["git", "-C", str(repo), "log", "--oneline", "-n", "12", f"{base}..{wt['branch']}"])
                if rc == 0:
                    wt["commits"] = [l for l in log.splitlines() if l.strip()]
        elif wt.get("branch") == base:
            wt["ahead"] = 0
        if wt.get("path") and Path(wt["path"]).is_dir():
            rc, st = runner(["git", "-C", wt["path"], "status", "--porcelain"])
            if rc == 0:
                wt["dirty"] = len([l for l in st.splitlines() if l.strip()])
    # commits ahead of base across every worktree branch, each counted once (branches share history)
    branches = sorted({w["branch"] for w in wts if w.get("branch") and w["branch"] != base})
    unique = 0
    if branches:
        rc, cnt = runner(["git", "-C", str(repo), "rev-list", "--count", *branches, "--not", base])
        unique = int(cnt.strip()) if rc == 0 and cnt.strip().isdigit() else None
    return {"worktrees": wts, "base": base, "unique_ahead": unique}


# --------------------------------------------------------------------------- ruflo


def parse_cli_json(text: str):
    """The JSON document in a CLI's stdout, tolerating banner lines before or after it."""
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    for opener in ("{", "["):
        i = text.find(opener)
        while i >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(text[i:])
                return obj
            except ValueError:
                i = text.find(opener, i + 1)
    return None


def read_memory_db(db: Path, namespace: str) -> list[dict]:
    """Entries of one ruflo sqlite memory store, opened read-only (never locks or writes it)."""
    if not db.is_file():
        return []
    rows: list[dict] = []
    for uri in (f"file:{db}?mode=ro", f"file:{db}?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True, timeout=1.0)
            try:
                cols = {r[1] for r in con.execute("pragma table_info(memory_entries)")}
                if not {"key", "namespace"} <= cols:
                    return []
                value_col = "content" if "content" in cols else ("value" if "value" in cols else "''")
                upd = "updated_at" if "updated_at" in cols else "0"
                crt = "created_at" if "created_at" in cols else "0"
                cur = con.execute(
                    f"select key, {value_col}, {crt}, {upd} from memory_entries where namespace = ?", (namespace,))
                for key, val, created, updated in cur.fetchall():
                    rows.append({"key": key, "value": (val or "")[:MEMORY_VALUE_MAX],
                                 "created_at": created, "updated_at": updated, "store": db.name})
                return rows
            finally:
                con.close()
        except sqlite3.Error:
            rows = []
            continue
    return rows


def lane_of_key(key: str) -> str | None:
    """``visual-overhaul/<lane>/<topic>`` -> ``<lane>``; keys without a topic have no lane."""
    if not key.startswith(LANE_PREFIX):
        return None
    parts = key[len(LANE_PREFIX):].split("/")
    return parts[0] if len(parts) >= 2 and parts[0] else None


def merge_memory(cli_list, db_rows: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for row in db_rows:
        prev = by_key.get(row["key"])
        if prev is None or (row.get("updated_at") or 0) >= (prev.get("updated_at") or 0):
            by_key[row["key"]] = dict(row)
    items = cli_list if isinstance(cli_list, list) else (
        cli_list.get("entries") if isinstance(cli_list, dict) else None) or []
    for item in items:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        cur = by_key.setdefault(item["key"], {"key": item["key"], "value": None, "store": "cli"})
        cur.setdefault("created_at", item.get("createdAt"))
        cur["updated_at"] = cur.get("updated_at") or item.get("updatedAt")
        cur["size"] = item.get("size")
        cur["in_cli_list"] = True
    out = sorted(by_key.values(), key=lambda r: r["key"])
    for r in out:
        r["lane"] = lane_of_key(r["key"])
    return out


def daemon_summary(path: Path) -> dict:
    data = _read_json(path)
    if not isinstance(data, dict):
        return {"present": False}
    workers = data.get("workers") if isinstance(data.get("workers"), dict) else {}
    return {
        "present": True,
        "running": bool(data.get("running")),
        "started_at": data.get("startedAt"),
        "workers_total": len(workers),
        "workers_running": sum(1 for w in workers.values() if isinstance(w, dict) and w.get("isRunning")),
        "runs_total": sum(int(w.get("runCount") or 0) for w in workers.values() if isinstance(w, dict)),
        "workers": {k: {kk: w.get(kk) for kk in ("runCount", "successCount", "failureCount", "isRunning", "nextRun")}
                    for k, w in workers.items() if isinstance(w, dict)},
    }


RUFLO_COMMANDS = {
    "agents": ["agent", "list", "--format", "json"],
    "tasks": ["task", "list", "--format", "json"],
    "swarm": ["swarm", "status", "--format", "json"],
    "memory_list": ["memory", "list", "--namespace", "visual", "--format", "json"],
}


def _store_items(data, key: str) -> list:
    """``{"agents": {id: {...}}}`` (the store) or ``{"agents": [...]}`` (the CLI) -> a list."""
    items = data.get(key) if isinstance(data, dict) else None
    if isinstance(items, dict):
        items = list(items.values())
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def read_ruflo_stores(repo: Path) -> dict:
    """Ruflo agents, tasks and swarms from its JSON stores, without running (or writing) anything."""
    cf = repo / ".claude-flow"
    swarm = _read_json(cf / "swarm" / "swarm-state.json")
    swarms = _store_items(swarm, "swarms")
    return {
        "fetched_at": time.time(),
        "source": "stores",
        "agents": {"agents": _store_items(_read_json(cf / "agents" / "store.json"), "agents")},
        "tasks": {"tasks": _store_items(_read_json(cf / "tasks" / "store.json"), "tasks")},
        "swarm": {"swarms": swarms} if swarms else None,
        "memory_list": None,
    }


def collect_ruflo_cli(repo: Path, runner=_run) -> dict:
    out: dict = {"fetched_at": time.time(), "source": "cli"}
    for name, args in RUFLO_COMMANDS.items():
        rc, text = runner(["npx", "-y", RUFLO_PKG, *args], cwd=repo, timeout=90.0)
        parsed = parse_cli_json(text)
        out[name] = parsed if parsed is not None else {"raw": text.strip()[:2000], "rc": rc}
    return out


# --------------------------------------------------------------------------- pytest log


def parse_pytest_log(path: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    try:
        st = path.stat()
        with path.open("rb") as fh:
            fh.seek(max(0, st.st_size - 200_000))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return {"present": False, "path": str(path)}
    lines = text.splitlines()
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    pct = None
    for line in lines:
        m = _PROGRESS_RE.match(line.strip())
        if m:
            chars = m.group(1)
            counts["passed"] += chars.count(".")
            counts["failed"] += chars.count("F")
            counts["error"] += chars.count("E")
            counts["skipped"] += chars.count("s")
            if m.group(2):
                pct = int(re.sub(r"\D", "", m.group(2)))
    summary_line = None
    for line in reversed(lines):
        if _SUMMARY_LINE_RE.match(line.strip()):
            summary_line = line.strip()
            break
    final = None
    if summary_line:
        final = {}
        for n, word in _SUMMARY_COUNT_RE.findall(summary_line):
            word = {"errors": "error", "warnings": "warning"}.get(word, word)
            final[word] = int(n)
    failures = [l.strip()[:200] for l in lines if l.startswith("FAILED ") or l.startswith("ERROR ")][-20:]
    if final is not None:
        status = "failed" if final.get("failed") or final.get("error") else "passed"
    else:
        status = "running" if (now - st.st_mtime) < 600 else "stalled"
        if counts["failed"] or counts["error"]:
            status += "-with-failures"
    return {
        "present": True,
        "path": str(path),
        "mtime": st.st_mtime,
        "status": status,
        "percent": pct,
        "progress_counts": counts,
        "final": final,
        "summary_line": summary_line,
        "failures": failures,
        "tail": lines[-12:],
    }


# --------------------------------------------------------------------------- state assembly


class Collector:
    """Builds /state.json; slow sources (ruflo npx, git) refresh in background threads."""

    def __init__(self, projects_root: Path, repo: Path, base: str, use_ruflo: bool = True,
                 pytest_log: Path | None = None, ruflo_cli: bool = False) -> None:
        self.projects_root = projects_root
        self.repo = repo
        self.base = base
        self.use_ruflo = use_ruflo
        self.ruflo_cli = use_ruflo and ruflo_cli
        self.pytest_log = pytest_log or (repo / "runs" / "visual" / "logs" / "pytest_merged.log")
        self._lock = threading.Lock()
        self._ruflo: dict = {}
        self._ruflo_busy = False
        self._git: dict = {}
        self._git_at = 0.0
        self._git_busy = False

    def _refresh_ruflo(self) -> None:
        try:
            data = collect_ruflo_cli(self.repo)
        except Exception as exc:  # keep the dashboard alive whatever npx does
            data = {"fetched_at": time.time(), "error": str(exc)}
        with self._lock:
            self._ruflo = data
            self._ruflo_busy = False

    def _refresh_git(self) -> None:
        try:
            data = collect_git(self.repo, self.base)
        except Exception as exc:
            data = {"error": str(exc), "worktrees": [], "base": self.base}
        with self._lock:
            self._git = data
            self._git_at = time.time()
            self._git_busy = False

    def _kick(self) -> None:
        now = time.time()
        with self._lock:
            if self.ruflo_cli and not self._ruflo_busy and now - self._ruflo.get("fetched_at", 0) > RUFLO_TTL_S:
                self._ruflo_busy = True
                threading.Thread(target=self._refresh_ruflo, daemon=True).start()
            if not self._git_busy and now - self._git_at > GIT_TTL_S:
                self._git_busy = True
                threading.Thread(target=self._refresh_git, daemon=True).start()

    def state(self) -> dict:
        self._kick()
        now = time.time()
        wf = collect_workflows(self.projects_root, now)
        if self.use_ruflo and not self.ruflo_cli:
            stores = read_ruflo_stores(self.repo)
            with self._lock:
                self._ruflo = stores
        with self._lock:
            ruflo_cli = dict(self._ruflo)
            ruflo_busy = self._ruflo_busy
            git = dict(self._git)
        swarm_dir = self.repo / ".swarm"
        db_rows = read_memory_db(swarm_dir / "agentdb-memory.db", "visual") + read_memory_db(swarm_dir / "memory.db",
                                                                                              "visual")
        memory = merge_memory(ruflo_cli.get("memory_list"), db_rows)
        agents_cli = ruflo_cli.get("agents") if isinstance(ruflo_cli.get("agents"), dict) else {}
        tasks_cli = ruflo_cli.get("tasks") if isinstance(ruflo_cli.get("tasks"), dict) else {}
        return {
            "generated_at": now,
            "active_window_s": ACTIVE_WINDOW_S,
            "base": self.base,
            "repo": str(self.repo),
            "workflows": wf,
            "git": git,
            "ruflo": {
                "fetched_at": ruflo_cli.get("fetched_at"),
                "refreshing": ruflo_busy,
                "enabled": self.use_ruflo,
                "source": ruflo_cli.get("source"),
                "agents": agents_cli.get("agents") or [],
                "tasks": tasks_cli.get("tasks") or [],
                "swarm": ruflo_cli.get("swarm"),
                "memory": memory,
                "daemon": daemon_summary(self.repo / ".claude-flow" / "daemon-state.json"),
                "raw_errors": {k: v.get("raw") for k, v in ruflo_cli.items()
                               if isinstance(v, dict) and "raw" in v},
            },
            "pytest": parse_pytest_log(self.pytest_log, now),
        }


def projects_root_for(repo: Path) -> Path:
    """Claude Code's transcript folder for ``repo``: ~/.claude/projects/<path with / as ->."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(repo))


def main_repo_root(start: Path) -> Path:
    """The main worktree of the repository holding ``start`` (ruflo state lives there)."""
    rc, out = _run(["git", "-C", str(start), "worktree", "list", "--porcelain"])
    if rc == 0:
        wts = parse_worktree_porcelain(out)
        if wts:
            return Path(wts[0]["path"])
    return start


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


def host_is_loopback(host_header: str | None) -> bool:
    """True when an HTTP Host header names this machine's loopback interface.

    The server binds to loopback, but a web page from another origin can reach it by DNS
    rebinding (its own hostname re-pointed at 127.0.0.1). The browser then sends that foreign
    hostname as Host, so refusing it keeps transcript excerpts and memory values off other sites.
    """
    host = (host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        name = host.split("]", 1)[0] + "]"
    else:
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name in LOOPBACK_HOSTS


def make_handler(collector: Collector, index_path: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SwarmViz/1"

        def log_message(self, fmt, *args):  # quiet: the page polls every 3 s
            if os.environ.get("SWARM_VIZ_VERBOSE"):
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if not host_is_loopback(self.headers.get("Host")):
                self._send(403, b"forbidden: Host must be 127.0.0.1 or localhost", "text/plain")
                return
            url = urlparse(self.path)
            if url.path in ("/", "/index.html"):
                try:
                    self._send(200, index_path.read_bytes(), "text/html; charset=utf-8")
                except OSError as exc:
                    self._send(500, str(exc).encode(), "text/plain")
            elif url.path == "/state.json":
                q = parse_qs(url.query)
                body = json.dumps(collector.state(), indent=1 if "pretty" in q else None, default=str)
                self._send(200, body.encode("utf-8"), "application/json")
            elif url.path == "/healthz":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--projects-root", type=Path, default=None,
                    help="default: ~/.claude/projects/<the main checkout's path, dashed>")
    ap.add_argument("--repo", type=Path, default=None, help="repository main checkout (default: found with git)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--no-ruflo", action="store_true", help="show no ruflo agents, tasks or swarms")
    ap.add_argument("--ruflo-cli", action="store_true",
                    help="ask the npx ruflo CLI every 20 s instead of reading its stores "
                         "(each call appends to the tracked .claude-flow/policy/state.json)")
    ap.add_argument("--once", action="store_true", help="print /state.json once and exit")
    args = ap.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        ap.error("this dashboard binds to loopback only")
    repo = (args.repo or main_repo_root(HERE)).resolve()
    if args.projects_root is None:
        args.projects_root = projects_root_for(repo)
    collector = Collector(args.projects_root, repo, args.base, use_ruflo=not args.no_ruflo,
                          ruflo_cli=args.ruflo_cli)
    if args.once:
        if collector.ruflo_cli:
            collector._ruflo = collect_ruflo_cli(repo)
        collector._git = collect_git(repo, args.base)
        collector._git_at = time.time()
        print(json.dumps(collector.state(), indent=1, default=str))
        return 0
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(collector, HERE / "index.html"))
    srv.daemon_threads = True
    print(f"swarm-viz: http://{args.host}:{args.port}  (repo {repo}, projects {args.projects_root})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
