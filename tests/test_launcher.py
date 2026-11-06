"""The double-click launcher (Phase 3 E6): `Launch FlightSim.cmd` ->
scripts/launch_windows.ps1. Source-reading tests: the real launch is the
Windows session's (notes/E6.md windows_steps 4-8). The container Verify
is test_steps_run_in_the_planned_order + test_launcher_has_no_prompt_anywhere."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CMD = REPO / "Launch FlightSim.cmd"
PS1 = REPO / "scripts" / "launch_windows.ps1"
STEPS = ("install", "preflight", "build", "materials", "aircraft", "bake", "server")


def _cmd():
    return CMD.read_text(encoding="utf-8")


def _ps1():
    return PS1.read_text(encoding="utf-8")


def test_launcher_cmd_runs_the_ps1_non_interactively():
    text = _cmd()
    assert text.startswith("@echo off")
    assert 'cd /d "%~dp0"' in text, "the .cmd must run from its own folder (decision 1)"
    run = re.search(r'powershell (.*)-File "scripts\\launch_windows\.ps1"', text)
    assert run, "the .cmd does not start scripts\\launch_windows.ps1"
    assert "-NoProfile" in run.group(1)
    assert "-ExecutionPolicy Bypass" in run.group(1)
    assert "-NoExit" not in text
    raw = CMD.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""), "a .cmd needs CRLF line ends"
    # failure keeps the window open without asking anything (decision 3)
    assert 'if not "%RC%"=="0" cmd /k' in text
    assert text.rstrip().endswith("exit /b %RC%")


def _code_only(text):
    """The lines that run: comments (rem / #) may TALK about prompts."""
    return "\n".join(line for line in text.splitlines()
                     if not re.match(r"\s*(rem\b|#)", line, re.IGNORECASE))


def test_launcher_has_no_prompt_anywhere():
    for path, text in ((CMD, _cmd()), (PS1, _ps1())):
        lowered = _code_only(text).lower().replace("-nopause", "")
        for prompt in ("pause", "read-host", "set /p", "choice", "readkey", "-noexit -file",
                       "$host.ui"):
            assert prompt not in lowered, f"{path.name} prompts via {prompt}"


def test_steps_run_in_the_planned_order():
    text = _ps1()
    indexes = []
    for n, name in enumerate(STEPS, start=1):
        match = re.search(rf'Invoke-Step {n} "{name}"', text)
        assert match, f"no Invoke-Step {n} {name}"
        indexes.append(match.start())
    assert indexes == sorted(indexes) and len(set(indexes)) == 7
    assert len(re.findall(r"Invoke-Step \d ", text)) == 7
    assert re.search(r'Log "step \$n/7 \$name"', text), "each step announces itself as step n/7 <name>"
    # the step's own work follows its oracle call (the header comment lists the files too)
    code = _code_only(text)
    assert code.index('launch_check.py", "build"') < code.index("build_ue.ps1\"))")
    assert code.index('launch_check.py", "materials"') < code.index("ue_create_materials.py")
    assert code.index('launch_check.py", "aircraft"') < code.index("import_aircraft.py")


def test_each_skip_line_is_the_agreed_word(monkeypatch, capsys, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "launch_check_words", REPO / "scripts" / "launch_check.py")
    lc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lc)
    import core.util.platform as platform
    from assets_pipeline import importer
    built = tmp_path / "bridge.dll"
    built.write_bytes(b"")
    monkeypatch.setattr(platform, "ue_bridge_binary", lambda repo: built)
    monkeypatch.setattr(platform, "binary_stale_reason", lambda repo: None)
    monkeypatch.setattr(lc, "check_materials", lambda repo, engine_version=None: None)
    monkeypatch.setattr(importer, "configured_aircraft", lambda: {})
    for step in ("build", "materials", "aircraft"):
        assert lc.main([step, "--repo", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "build up to date", "materials up to date", "aircraft up to date"]
    text = _ps1()
    assert 'Log "READY"' in text
    assert 'Log "FAILED ${step}: $reason"' in text
    assert 'Log "build built"' in text
    assert 'Log "materials created"' in text
    assert 'Log "aircraft imported $name"' in text
    # the oracle's lines reach the log unchanged: every program runs through Invoke-Logged
    assert text.count("Invoke-Logged") >= 10


def test_ready_is_written_after_the_server_answers():
    text = _ps1()
    wait = text.index("Invoke-WebRequest -Uri $url -UseBasicParsing")
    opened = text.index("Start-Process $url")
    ready = text.index('Log "READY"')
    assert wait < opened < ready
    assert 'Stop-With "server" "server.not_answering' in text
    assert text.index('Stop-With "server"') < ready
    assert text.rstrip().endswith("exit 0")


def test_a_relaunch_closes_the_old_server_window_too():
    """E6: stopping only uvicorn left its powershell -NoExit window open, one
    more per launch. The hosts are read before the kill (a dead process has
    no parent to look up) and only ones running the server are matched."""
    text = _ps1()
    hosts = text.index("$hosts = @(Get-ServerHosts $owner)")
    kill = text.index("Stop-Process -Id $owner -Force")
    closed = text.index("Stop-Process -Id $hostPid -Force")
    assert hosts < kill < closed
    assert '-notlike "*uvicorn webapp.server:app*"' in text
    assert "$parent.ProcessId -eq $PID" in text


def test_launcher_sets_no_flightsim_variable_and_leaves_tiles_and_weather_alone():
    for text in (_cmd(), _ps1()):
        assert "FLIGHTSIM_" not in text
        assert "$env:" not in text
        assert "tiles" not in text.lower().replace("tiles and\n# weather stay exactly as the repo configures them", "")
        assert "weather" not in text.lower().replace("tiles and\n# weather stay exactly as the repo configures them", "")


def test_failures_name_their_step():
    text = _ps1()
    reasons = {
        "install": "install.lock_failed",
        "preflight": "toolchain.pin_unreadable",
        "build": "engine.binary_stale",
        "materials": "materials.failed",
        "aircraft": "aircraft.import_failed",
        "bake": "bake.failed",
        "server": "server.not_answering",
    }
    for step, reason in reasons.items():
        assert re.search(rf'Stop-With "{step}" "?[^\n]*{re.escape(reason)}', text), (
            f"step {step} never fails as {reason}")
    assert text.count('"host.smart_app_control"') == 2, "build and materials report a SAC block by name"
    assert "function Test-SmartAppControl" in text
    assert "3077|3033" in text and "4551" in text
    # every Stop-With names one of the seven steps and nothing else
    for step in re.findall(r'Stop-With "(\w+)"', text):
        assert step in STEPS


def test_bake_step_is_d5s_exact_command():
    text = _ps1()
    calls = re.findall(r'Invoke-Logged \$venvPython @\("scripts\\bake_terrain\.py"([^)]*)\)', text)
    assert calls == [', "--places"'], "the bake step is .venv python scripts\\bake_terrain.py --places, nothing else"
    code = _code_only(text)
    assert code.count("scripts\\bake_terrain.py") == 1, "the bake command is typed once"
    assert "bake_terrain.py --all" not in code and "--source" not in code
    for retyped in ("bake grand_canyon up to date", "bake yosemite up to date", "baking (", "baked"):
        assert retyped not in text, f"the launcher re-types D5's line {retyped!r}"
    assert '$script:lastExit -eq 2) { Stop-With "bake" "bake.usage' in text
    assert 'FAILED ' in text and '"^bake \\S+ FAILED "' in text


def test_a_commandlet_import_does_not_reach_for_the_content_browser():
    """The materials step imports in a commandlet on a fresh download: with the
    sync on, the engine asserts on the Slate application it does not have."""
    ini = (REPO / "ue" / "Config" / "DefaultEngine.ini").read_text(encoding="utf-8")
    assert "Interchange.FeatureFlags.Import.SyncToBrowser=0" in ini


def test_the_materials_step_can_see_a_failed_material():
    """MATERIAL-FAILED is a Python print, which stdout drops without this flag."""
    text = (REPO / "scripts" / "launch_windows.ps1").read_text(encoding="utf-8")
    step = text[text.index('Invoke-Step 4 "materials"'):text.index("Invoke-Step 5")]
    assert '"-FullStdOutLogOutput"' in step and '"MATERIAL-FAILED"' in step
