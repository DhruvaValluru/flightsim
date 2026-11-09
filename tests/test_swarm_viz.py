"""Tests for the live swarm dashboard's state collector (scripts/swarm_viz/server.py).

Everything runs on a fake ~/.claude/projects tree in tmp_path; no npx, no network.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "swarm_viz"))

import server as sv  # noqa: E402

NOW = 1_800_000_000.0


def _tool_line(name: str, inp: dict, ts: str = "2026-11-09T18:00:00.000Z") -> str:
    return json.dumps({
        "type": "assistant", "timestamp": ts,
        "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t", "name": name, "input": inp}]},
    })


def _write_agent(run: Path, aid: str, label: str, phase: str, tools: list[tuple[str, dict]], mtime: float,
                 worktree: str | None = None, pad: int = 0) -> None:
    meta = {"agentType": "workflow-subagent", "description": label, "workflowPhase": phase}
    if worktree:
        meta["worktreePath"] = worktree
    (run / f"agent-{aid}.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    lines = [json.dumps({"type": "user", "timestamp": "2026-11-09T17:00:00.000Z", "message": {"content": "go"}})]
    if pad:
        lines.append(json.dumps({"type": "user", "message": {"content": "x" * pad}}))
    lines += [_tool_line(n, i) for n, i in tools]
    tr = run / f"agent-{aid}.jsonl"
    tr.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.utime(tr, (mtime, mtime))


@pytest.fixture()
def fake_tree(tmp_path: Path) -> Path:
    root = tmp_path / "projects"
    sess = root / "sess-lead"
    run = sess / "subagents" / "workflows" / "wf_live-001"
    run.mkdir(parents=True)
    (sess / "workflows" / "scripts").mkdir(parents=True)
    (sess / "workflows" / "scripts" / "my-flow-wf_live-001.js").write_text(
        "export const meta = {\n  name: 'my-flow',\n  description: 'demo flow',\n  phases: [\n"
        "    { title: 'Build', detail: 'x' },\n    { title: 'Review', detail: 'y' },\n  ],\n}\n\nconst X = 1\n",
        encoding="utf-8")
    journal = [
        {"type": "launched"},
        {"type": "started", "key": "k1", "agentId": "a1", "label": "build:world", "phase": "Build"},
        {"type": "started", "key": "k2", "agentId": "a2", "label": "build:aircraft", "phase": "Build"},
        {"type": "started", "key": "k3", "agentId": "a3", "label": "review:world", "phase": "Review"},
        {"type": "started", "key": "k4", "agentId": "a4", "label": "build:broken", "phase": "Build"},
        {"type": "result", "key": "k2", "agentId": "a2",
         "result": {"branch": "wt-2", "commits": ["abc123 do it"], "summary": "done"}},
        {"type": "failed", "key": "k4", "agentId": "a4"},
    ]
    (run / "journal.jsonl").write_text("\n".join(json.dumps(j) for j in journal) + "\nnot json\n", encoding="utf-8")
    _write_agent(run, "a1", "build:world", "Build",
                 [("Read", {"file_path": f"/f{i}.py"}) for i in range(7)] + [("Bash", {"command": "ls -la", "description": "List"})],
                 NOW - 5, worktree="/wt/one")
    _write_agent(run, "a2", "build:aircraft", "Build", [("Write", {"file_path": "/x.py", "content": "y"})], NOW - 500)
    _write_agent(run, "a3", "review:world", "Review", [("Grep", {"pattern": "foo"})], NOW - 300)
    _write_agent(run, "a4", "build:broken", "Build", [("Bash", {"command": "false"})], NOW - 2)
    (root / "sess-lead.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(root / "sess-lead.jsonl", (NOW, NOW))

    # an older, finished session whose run record says it was killed
    old = root / "sess-old"
    orun = old / "subagents" / "workflows" / "wf_old-002"
    orun.mkdir(parents=True)
    (old / "workflows").mkdir(parents=True)
    (orun / "journal.jsonl").write_text(json.dumps({"type": "launched"}) + "\n" + json.dumps(
        {"type": "started", "agentId": "b1", "label": "build:B1", "phase": "Build"}) + "\n", encoding="utf-8")
    _write_agent(orun, "b1", "build:B1", "Build", [("Edit", {"file_path": "/old.py"})], NOW - 90_000)
    (old / "workflows" / "wf_old-002.json").write_text(json.dumps({
        "runId": "wf_old-002", "status": "killed", "workflowName": "old-flow", "startTime": "1799900000000",
        "phases": [{"title": "Build"}],
        "workflowProgress": [{"type": "workflow_agent", "agentId": "b1", "startedAt": 1799900001000, "tokens": 42,
                              "toolCalls": 3}],
    }), encoding="utf-8")
    (root / "sess-old.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(root / "sess-old.jsonl", (NOW - 90_000, NOW - 90_000))
    (root / "memory").mkdir()  # not a session: no subagents dir
    return root


def _run_by_id(wf: dict, rid: str) -> dict:
    for s in wf["sessions"]:
        for r in s["runs"]:
            if r["id"] == rid:
                return r
    raise KeyError(rid)


def test_sessions_sorted_lead_first(fake_tree: Path) -> None:
    wf = sv.collect_workflows(fake_tree, now=NOW, cache=sv._TailCache())
    assert [s["id"] for s in wf["sessions"]] == ["sess-lead", "sess-old"]


def test_agent_states_from_journal_and_mtime(fake_tree: Path) -> None:
    wf = sv.collect_workflows(fake_tree, now=NOW, cache=sv._TailCache())
    run = _run_by_id(wf, "wf_live-001")
    states = {a["id"]: a["state"] for a in run["agents"]}
    assert states == {"a1": "active", "a2": "done", "a3": "idle", "a4": "failed"}
    assert run["status"] == "running"


def test_script_meta_name_and_phases(fake_tree: Path) -> None:
    run = _run_by_id(sv.collect_workflows(fake_tree, now=NOW, cache=sv._TailCache()), "wf_live-001")
    assert run["name"] == "my-flow"
    assert run["description"] == "demo flow"
    assert run["phases"] == ["Build", "Review"]


def test_last_five_tool_calls_and_sizes(fake_tree: Path) -> None:
    run = _run_by_id(sv.collect_workflows(fake_tree, now=NOW, cache=sv._TailCache()), "wf_live-001")
    a1 = next(a for a in run["agents"] if a["id"] == "a1")
    assert [c["name"] for c in a1["last_tools"]] == ["Read", "Read", "Read", "Read", "Bash"]
    assert a1["last_tools"][-1]["input"].startswith("List | ls -la")
    assert a1["last_tools"][0]["input"] == "/f3.py"
    assert a1["transcript_bytes"] == (fake_tree / "sess-lead/subagents/workflows/wf_live-001/agent-a1.jsonl").stat().st_size
    assert a1["worktree"] == "/wt/one"
    assert a1["start_ms"] == sv._iso_to_ms("2026-11-09T17:00:00.000Z")
    a2 = next(a for a in run["agents"] if a["id"] == "a2")
    assert a2["commits"] == ["abc123 do it"] and a2["branch"] == "wt-2"
    assert a2["end_ms"] == int((NOW - 500) * 1000)


def test_tail_reader_expands_past_a_huge_line(tmp_path: Path) -> None:
    run = tmp_path / "r"
    run.mkdir()
    _write_agent(run, "z", "x", "P", [("Bash", {"command": "echo hi"})], NOW, pad=sv.TAIL_BYTES + 10_000)
    # the only tool call sits after a line bigger than the first tail window
    tr = run / "agent-z.jsonl"
    tr.write_text(tr.read_text(encoding="utf-8") + json.dumps({"type": "user", "message": {"content": "y" * (sv.TAIL_BYTES + 5)}}) + "\n", encoding="utf-8")
    calls = sv.transcript_tail_tools(tr, tr.stat().st_size)
    assert [c["name"] for c in calls] == ["Bash"]


def test_finished_run_record_marks_leftover_agents_stopped(fake_tree: Path) -> None:
    run = _run_by_id(sv.collect_workflows(fake_tree, now=NOW, cache=sv._TailCache()), "wf_old-002")
    assert run["status"] == "killed"
    assert run["name"] == "old-flow"
    assert run["start_ms"] == 1799900000000
    b1 = run["agents"][0]
    assert b1["state"] == "stopped"
    assert b1["tokens"] == 42 and b1["start_ms"] == 1799900001000


def test_tail_cache_reuses_until_file_changes(fake_tree: Path) -> None:
    cache = sv._TailCache()
    tr = fake_tree / "sess-lead/subagents/workflows/wf_live-001/agent-a3.jsonl"
    st = tr.stat()
    first = cache.get(tr, st.st_size, st.st_mtime)
    assert cache.get(tr, st.st_size, st.st_mtime) is first
    with tr.open("a") as fh:
        fh.write(_tool_line("Edit", {"file_path": "/new.py"}) + "\n")
    st2 = tr.stat()
    again = cache.get(tr, st2.st_size, st2.st_mtime)
    assert again is not first and again["tools"][-1]["name"] == "Edit"


def test_missing_root_is_reported_not_raised(tmp_path: Path) -> None:
    wf = sv.collect_workflows(tmp_path / "nope", now=NOW)
    assert wf["sessions"] == [] and "error" in wf


def test_worktree_porcelain_and_git_counts() -> None:
    text = ("worktree /repo\nHEAD aaa\nbranch refs/heads/main-base\n\n"
            "worktree /repo/.claude/worktrees/w1\nHEAD bbb\nbranch refs/heads/wt-1\nlocked claude agent\n\n"
            "worktree /repo/det\nHEAD ccc\ndetached\n")
    calls = []

    def runner(cmd, cwd=None, timeout=30.0):
        calls.append(cmd)
        if cmd[3:5] == ["worktree", "list"]:
            return 0, text
        if "rev-list" in cmd and "--not" in cmd:
            assert cmd[-2:] == ["--not", "main-base"] and "wt-1" in cmd
            return 0, "5\n"
        if "rev-list" in cmd:
            return 0, "3\n"
        if cmd[3] == "log":
            return 0, "c1 one\nc2 two\nc3 three\n"
        if "status" in cmd:
            return 0, " M a.py\n?? b.py\n"
        return 1, ""

    g = sv.collect_git(Path("/repo"), "main-base", runner=runner)
    wts = {w["path"]: w for w in g["worktrees"]}
    assert wts["/repo"]["ahead"] == 0
    assert wts["/repo/.claude/worktrees/w1"]["ahead"] == 3
    assert wts["/repo/.claude/worktrees/w1"]["locked"] is True
    assert wts["/repo/.claude/worktrees/w1"]["commits"] == ["c1 one", "c2 two", "c3 three"]
    assert wts["/repo/det"]["branch"] is None and wts["/repo/det"]["ahead"] is None
    assert g["unique_ahead"] == 5
    assert not any("push" in c or "fetch" in c for cmd in calls for c in cmd)


def test_parse_cli_json_tolerates_banners() -> None:
    assert sv.parse_cli_json('{"a": 1}') == {"a": 1}
    assert sv.parse_cli_json('[INFO] booting\n{"agents": [], "total": 0}\ndone') == {"agents": [], "total": 0}
    assert sv.parse_cli_json("Unknown flag --format") is None
    assert sv.parse_cli_json("") is None


def test_ruflo_cli_falls_back_to_raw_text() -> None:
    def runner(cmd, cwd=None, timeout=30.0):
        assert cmd[:3] == ["npx", "-y", sv.RUFLO_PKG]
        if cmd[3] == "agent":
            return 0, '{"agents": [{"agentId": "x"}]}'
        return 1, "error: unknown option '--format'"

    out = sv.collect_ruflo_cli(Path("/repo"), runner=runner)
    assert out["agents"]["agents"][0]["agentId"] == "x"
    assert out["tasks"]["raw"].startswith("error") and out["tasks"]["rc"] == 1


def _make_memory_db(path: Path, rows: list[tuple[str, str, str, int]]) -> None:
    con = sqlite3.connect(path)
    con.execute("create table memory_entries (id text, key text, namespace text, content text, created_at int, updated_at int)")
    con.executemany("insert into memory_entries values (?, ?, ?, ?, ?, ?)",
                    [(k, k, ns, v, t, t) for k, ns, v, t in rows])
    con.commit()
    con.close()


def test_memory_merge_db_values_and_lanes(tmp_path: Path) -> None:
    a = tmp_path / "agentdb-memory.db"
    b = tmp_path / "memory.db"
    _make_memory_db(a, [("visual-overhaul/world/decisions", "visual", "new value", 20),
                        ("visual-overhaul/status", "visual", "top", 5),
                        ("other/x", "default", "nope", 1)])
    _make_memory_db(b, [("visual-overhaul/world/decisions", "visual", "old value", 10)])
    rows = sv.read_memory_db(a, "visual") + sv.read_memory_db(b, "visual")
    cli = [{"key": "visual-overhaul/status", "size": 3, "createdAt": 5, "updatedAt": 5},
           {"key": "visual-overhaul/pins/only-cli", "size": 9}]
    mem = {m["key"]: m for m in sv.merge_memory(cli, rows)}
    assert set(mem) == {"visual-overhaul/world/decisions", "visual-overhaul/status", "visual-overhaul/pins/only-cli"}
    assert mem["visual-overhaul/world/decisions"]["value"] == "new value"
    assert mem["visual-overhaul/world/decisions"]["lane"] == "world"
    assert mem["visual-overhaul/status"]["lane"] is None and mem["visual-overhaul/status"]["in_cli_list"]
    assert mem["visual-overhaul/pins/only-cli"]["value"] is None and mem["visual-overhaul/pins/only-cli"]["lane"] == "pins"
    # the store was opened read-only: nothing changed on disk
    assert sv.read_memory_db(tmp_path / "missing.db", "visual") == []


def test_daemon_summary(tmp_path: Path) -> None:
    p = tmp_path / "daemon-state.json"
    p.write_text(json.dumps({"running": False, "workers": {
        "map": {"runCount": 2, "isRunning": True}, "audit": {"runCount": 0, "isRunning": False}}}), encoding="utf-8")
    d = sv.daemon_summary(p)
    assert d["present"] and not d["running"]
    assert d["workers_total"] == 2 and d["workers_running"] == 1 and d["runs_total"] == 2
    assert sv.daemon_summary(tmp_path / "none.json") == {"present": False}


def test_pytest_log_running_and_final(tmp_path: Path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("........ [ 10%]\n..F.s... [ 20%]\n", encoding="utf-8")
    r = sv.parse_pytest_log(log, now=log.stat().st_mtime + 5)
    assert r["status"] == "running-with-failures" and r["percent"] == 20
    assert r["progress_counts"] == {"passed": 14, "failed": 1, "error": 0, "skipped": 1}
    log.write_text("........ [100%]\nFAILED tests/test_x.py::test_y - boom\n"
                   "===== 1 failed, 2900 passed, 6 skipped, 3 warnings in 812.10s (0:13:32) =====\n", encoding="utf-8")
    r = sv.parse_pytest_log(log, now=log.stat().st_mtime + 5)
    assert r["status"] == "failed"
    assert r["final"] == {"failed": 1, "passed": 2900, "skipped": 6, "warning": 3}
    assert r["failures"] == ["FAILED tests/test_x.py::test_y - boom"]
    assert sv.parse_pytest_log(tmp_path / "absent.log")["present"] is False


def test_summarize_tool_input() -> None:
    assert sv.summarize_tool_input("Bash", {"command": "a\nb"}) == "a b"
    assert sv.summarize_tool_input("Read", {"file_path": "/p"}) == "/p"
    assert sv.summarize_tool_input("X", {"n": 1}) == '{"n": 1}'
    assert sv.summarize_tool_input("X", "raw") == "raw"


def test_server_serves_page_and_state(fake_tree: Path, tmp_path: Path) -> None:
    collector = sv.Collector(fake_tree, tmp_path / "repo", "main-base", use_ruflo=False)
    collector._git_at = time.time() + 3600  # keep git out of this test
    srv = sv.ThreadingHTTPServer(("127.0.0.1", 0), sv.make_handler(collector, REPO / "scripts/swarm_viz/index.html"))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode()
        assert "cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js" in page
        assert "/state.json" in page
        st = json.loads(urllib.request.urlopen(base + "/state.json", timeout=5).read())
        assert [s["id"] for s in st["workflows"]["sessions"]][0] == "sess-lead"
        assert st["ruflo"]["enabled"] is False and st["pytest"]["present"] is False
        # DNS rebinding: a foreign Host header is refused even though the socket is loopback
        req = urllib.request.Request(base + "/state.json", headers={"Host": "attacker.example"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == 403
    finally:
        srv.shutdown()
        srv.server_close()


def test_page_polls_only_local_state() -> None:
    page = (REPO / "scripts/swarm_viz/index.html").read_text(encoding="utf-8")
    assert 'fetch("/state.json"' in page
    assert page.count("fetch(") == 1
    for banned in ("api.github.com", "github.com/", "/pulls", "actions/runs"):
        assert banned not in page
    src = (REPO / "scripts/swarm_viz/server.py").read_text(encoding="utf-8")
    assert "gh " not in src and "api.github.com" not in src


def test_main_refuses_non_loopback_bind() -> None:
    with pytest.raises(SystemExit):
        sv.main(["--host", "0.0.0.0", "--once"])


def test_host_is_loopback() -> None:
    for ok in ("127.0.0.1:8787", "localhost:8787", "LOCALHOST", "[::1]:8787", "127.0.0.1"):
        assert sv.host_is_loopback(ok), ok
    for bad in (None, "", "attacker.example:8787", "127.0.0.1.attacker.example", "localhost.evil:80", "[::2]:8787"):
        assert not sv.host_is_loopback(bad), bad


def test_ruflo_read_from_stores_without_the_cli(tmp_path: Path) -> None:
    cf = tmp_path / ".claude-flow"
    for sub, name, body in (("agents", "store.json", {"agents": {"a1": {"agentId": "a1", "status": "busy"}}}),
                            ("tasks", "store.json", {"tasks": {"t1": {"taskId": "t1", "status": "in_progress"}}}),
                            ("swarm", "swarm-state.json", {"swarms": {"s1": {"swarmId": "s1"}}})):
        (cf / sub).mkdir(parents=True)
        (cf / sub / name).write_text(json.dumps(body), encoding="utf-8")
    collector = sv.Collector(tmp_path / "projects", tmp_path, "base")
    assert collector.ruflo_cli is False  # the CLI writes policy state; it stays opt-in
    collector._git_at = time.time() + 3600
    collector._kick = lambda: None  # no background thread may start in this test
    st = collector.state()
    assert st["ruflo"]["source"] == "stores"
    assert [a["agentId"] for a in st["ruflo"]["agents"]] == ["a1"]
    assert [t["taskId"] for t in st["ruflo"]["tasks"]] == ["t1"]
    assert st["ruflo"]["swarm"]["swarms"][0]["swarmId"] == "s1"
    assert sv.read_ruflo_stores(tmp_path / "missing")["agents"] == {"agents": []}


def test_ruflo_cli_is_never_run_by_default(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(sv, "collect_ruflo_cli", lambda *a, **k: calls.append(a) or {})
    collector = sv.Collector(tmp_path / "projects", tmp_path, "base")
    collector._git_at = time.time() + 3600
    collector.state()
    time.sleep(0.05)
    assert calls == []


def test_projects_root_follows_the_checkout() -> None:
    root = sv.projects_root_for(Path("/Users/someone/flight.sim"))
    assert root == Path.home() / ".claude" / "projects" / "-Users-someone-flight-sim"
