"""A long scenario batch has bounded memory: a check before each scene, the
summary on disk after each scene, --resume, and engine helpers reaped."""

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run_test_scenarios as rts  # noqa: E402

SCENES = [(f"s{n}", f"prompt {n}", {}) for n in range(1, 6)]


def _args(**kw):
    return SimpleNamespace(**{"server": "http://x", "resume": False, **kw})


def _gather(tmp_path):
    return lambda results: tmp_path / "gallery" / "index.html"


def test_low_memory_waits_then_refuses_by_name():
    clock = iter(range(0, 1000, 10))
    slept = []
    words = rts.wait_ready("s", 4096, 30, probe=lambda: 1000.0,
                           status=lambda: (200, {"busy": False, "editor_running": False}),
                           sleep=slept.append, clock=lambda: next(clock))
    assert words.startswith("[batch.low_memory]") and "1000 MB free" in words
    assert slept, "it waited before refusing"


def test_memory_coming_back_lets_the_scene_run():
    free = iter([100.0, 100.0, 9000.0])
    assert rts.wait_ready("s", 4096, 600, probe=lambda: next(free),
                          status=lambda: (200, {}), sleep=lambda s: None,
                          clock=lambda: 0.0) is None


def test_an_editor_left_running_holds_the_next_scene():
    words = rts.wait_ready("s", 0, 0, probe=lambda: None,
                           status=lambda: (200, {"busy": False, "editor_running": True}),
                           sleep=lambda s: None, clock=lambda: 0.0)
    assert words.startswith("[batch.app_busy]")


def test_the_summary_is_on_disk_after_every_scene_and_a_stop_is_named(tmp_path):
    summary = tmp_path / "s.json"
    seen = []

    def run(server, number, name, prompt, edits, args):
        # the scenes before this one are already written
        on_disk = [r["number"] for r in json.loads(summary.read_text(encoding="utf-8"))] if summary.is_file() else []
        seen.append(on_disk)
        return {"number": number, "name": name, "prompt": prompt, "outcome": "done"}

    gates = iter([None, None, None, "[batch.low_memory] only 1 MB free"])
    code = rts.run_batch(_args(), set(range(1, 6)), SCENES, run, lambda: next(gates),
                         summary, _gather(tmp_path))
    assert code == 3
    assert seen == [[], [1], [1, 2]]
    assert [r["number"] for r in json.loads(summary.read_text(encoding="utf-8"))] == [1, 2, 3]


def test_resume_runs_only_what_the_last_batch_did_not_finish(tmp_path):
    summary = tmp_path / "s.json"
    summary.write_text(json.dumps([
        {"number": 1, "name": "s1", "outcome": "done", "run_id": "a"},
        {"number": 2, "name": "s2", "outcome": "refused"},
        {"number": 3, "name": "s3", "outcome": "failed"}]), encoding="utf-8")
    ran = []

    def run(server, number, name, prompt, edits, args):
        ran.append(number)
        return {"number": number, "name": name, "outcome": "done"}

    code = rts.run_batch(_args(resume=True), set(range(1, 6)), SCENES, run, lambda: None,
                         summary, _gather(tmp_path))
    assert code == 0 and ran == [3, 4, 5]
    rows = json.loads(summary.read_text(encoding="utf-8"))
    assert [r["number"] for r in rows] == [1, 2, 3, 4, 5]
    assert rows[0]["run_id"] == "a"


def test_available_memory_reads_on_this_machine():
    free = rts.available_mb()
    assert free is None or free > 0


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
def test_a_helper_left_behind_by_a_finished_pass_is_reaped(tmp_path):
    from core.render.headless import run_headless

    pid_file = tmp_path / "pid"
    child = (f"import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',"
             f"'import time; time.sleep(60)']); open({str(pid_file)!r},'w',encoding='utf-8').write(str(p.pid))")
    result = run_headless([sys.executable, "-c", child], tmp_path / "log", stall=None, timeout=60)
    assert result.returncode == 0
    pid = int(pid_file.read_text(encoding="utf-8"))
    for _ in range(50):
        alive = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                               capture_output=True, text=True).stdout.strip()
        if not alive or alive.startswith("Z"):
            break
        time.sleep(0.1)
    assert not alive or alive.startswith("Z")
