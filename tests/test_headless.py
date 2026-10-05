"""The unattended launcher (core/render/headless.py) on real child
processes: the exit code and output come back, a prompt reads end of
file, and a silent or overlong pass is stopped -- its whole tree -- and
named. The render-command pins route around it (tests/engine_launch.py),
so this is where it is measured."""

import sys
import time

import pytest

from core.render.headless import HeadlessResult, run_headless


def _python(code):
    return [sys.executable, "-c", code]


def test_the_exit_code_and_the_output_come_back(tmp_path):
    log = tmp_path / "pass.log"
    result = run_headless(_python("print('hello'); raise SystemExit(3)"), log,
                          stall=None, timeout=None, poll_seconds=0.1)
    assert result.returncode == 3 and result.refusal is None
    assert result.sentence() is None
    assert "hello" in log.read_text(encoding="utf-8")


def test_a_prompt_reads_end_of_file_instead_of_waiting(tmp_path):
    log = tmp_path / "pass.log"
    result = run_headless(_python("import sys; print(repr(sys.stdin.read()))"), log,
                          stall=None, timeout=60, poll_seconds=0.1)
    assert result.returncode == 0 and not result.timed_out
    assert "''" in log.read_text(encoding="utf-8")


def test_a_silent_pass_is_stopped_by_name(tmp_path):
    log = tmp_path / "pass.log"
    result = run_headless(_python("import time; time.sleep(120)"), log,
                          stall=1.0, timeout=None, poll_seconds=0.1)
    assert result.stalled and result.refusal == "render.stalled"
    assert result.seconds < 60
    assert result.sentence().startswith("render.stalled: the engine wrote nothing for 1 s")
    assert "render.stalled" in log.read_text(encoding="utf-8")


def test_the_run_limit_stops_a_pass_that_keeps_writing(tmp_path):
    log = tmp_path / "pass.log"
    busy = "import time\nwhile True:\n    print('x', flush=True)\n    time.sleep(0.05)"
    result = run_headless(_python(busy), log, stall=None, timeout=1.0, poll_seconds=0.1)
    assert result.timed_out and result.refusal == "render.timeout"
    assert result.seconds < 60
    # The limit that fired, whatever the environment says (it says
    # nothing here: FLIGHTSIM_RENDER_TIMEOUT_SECONDS has no default).
    assert result.sentence().startswith("render.timeout: the engine ran past 1 s")


def test_a_result_names_the_environment_s_limit_when_it_recorded_none(monkeypatch):
    monkeypatch.setenv("FLIGHTSIM_STALL_SECONDS", "7")
    monkeypatch.delenv("FLIGHTSIM_RENDER_TIMEOUT_SECONDS", raising=False)
    assert "7 s" in HeadlessResult(None, stalled=True).sentence()
    assert HeadlessResult(None, timed_out=True).sentence().startswith("render.timeout: ")


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX process groups; Windows kills the tree with taskkill /T")
def test_a_stall_kills_the_whole_tree(tmp_path):
    """The wrapper AND the engine under it: killing only the direct child
    left the editor running and holding its lock for the next case. The
    grandchild beats into a file; after the stop the beat ends."""
    beat = tmp_path / "beat"
    grandchild = ("import time\n"
                  "while True:\n"
                  f"    open({str(beat)!r}, 'a', encoding='utf-8').write('.')\n"
                  "    time.sleep(0.05)\n")
    parent = ("import subprocess, sys, time\n"
              f"subprocess.Popen([sys.executable, '-c', {grandchild!r}])\n"
              "time.sleep(120)\n")
    # The beat file is not watched, so the pass is silent and stalls.
    result = run_headless(_python(parent), tmp_path / "pass.log",
                          stall=1.0, timeout=None, poll_seconds=0.1)
    assert result.stalled
    assert beat.is_file(), "the grandchild never started"
    time.sleep(0.5)
    size = beat.stat().st_size
    time.sleep(1.0)
    assert beat.stat().st_size == size, "the grandchild outlived the stalled pass"
