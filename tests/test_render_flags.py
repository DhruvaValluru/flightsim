"""Phase 2, package A (contracts §9): ONE render-command builder.

Measured before it existed: the CLI's ``--render`` and the web app's
``RunManager._render`` assembled the commandlet's flags by hand, in two
files, and disagreed -- the CLI had no ``-mesh=`` until the placeholder
rule, no look unless the randomisation block was on, no ``-shot`` and
no size; neither passed ``-deterministic``. Nothing compared them.

These tests drive BOTH code paths over one compiled spec with the
subprocess intercepted, capture the two commands, and assert the flag
lists agree apart from the tokens the launcher itself owns (the
editor/project/-run tokens and the launcher switches on the web app's
side; the wrapper script and its positional card/frames on the CLI's,
which the wrapper turns into ``-scenario= -frames=`` and, per camera,
``-camera-index=N -telemetry=``).

Not verified here: that the commandlet accepts the list (no engine on
this platform); that ``render_ue_scenario.ps1`` forwards every token
(``tests/test_powershell_scripts.py`` reads the script; the first
Windows render measures it).
"""

import json
from pathlib import Path

import pytest

from core.nl.compiler import compile_prompt
from core.render.flags import (
    DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_LOOK, DEFAULT_WIDTH, LAUNCHER_FLAGS,
    WRAPPER_OWNED_PREFIXES, for_wrapper, render_flags, switches_present,
)
from core.scenario.spec import ScenarioSpec
from flightsim.capture import main as capture_main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SPEC = EXAMPLES / "cameras_multi.yaml"


# -- the builder on its own -----------------------------------------------

def _flags(**overrides):
    kwargs = dict(scene=None, mesh=None, look=None, camera_flags=None,
                  width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fps=DEFAULT_FPS)
    kwargs.update(overrides)
    return render_flags("/abs/card.json", "/abs/frames", **kwargs)


def test_the_defaults_are_the_showcase_matrix_s_numbers():
    """One default look and one size, stated twice on purpose (the
    builder must not import the experiments package); this pin is what
    keeps the two copies equal."""
    from experiments.showcase_matrix import (
        FPS, HEIGHT, TIME_OF_DAY, VISIBILITY, WIDTH,
    )

    assert DEFAULT_LOOK == {**TIME_OF_DAY["noon"],
                            "fog_density": VISIBILITY["clear"]}
    assert (DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS) == (WIDTH, HEIGHT, FPS)


def test_the_mesh_is_forwarded_verbatim_and_only_when_given():
    """The line the placeholder rule hangs on (mutation guard: remove
    the forwarding and this fails)."""
    mesh = Path("/abs/assets/generated/B747/mesh_manifest.json")
    with_mesh = _flags(mesh=mesh)
    assert [t for t in with_mesh if t.startswith("-mesh=")] == [f"-mesh={mesh}"]
    assert not [t for t in _flags(mesh=None) if t.startswith("-mesh=")]


def test_the_opt_in_passes_are_emitted_once_each():
    flags = _flags(labels=True, linear=True, deterministic=True)
    assert switches_present(flags) == ("-Visual", "-labels", "-linear",
                                       "-deterministic")
    # A switch the caller already stated through ``extra`` (the web
    # app's per-camera loop hands in -labels) is not stated twice.
    twice = _flags(labels=True, extra=["-camera-index=0", "-labels"])
    assert twice.count("-labels") == 1
    assert twice.index("-labels") == twice.index("-camera-index=0") + 1
    off = _flags(labels=False, linear=False, deterministic=False)
    assert switches_present(off) == ("-Visual",)


def test_the_void_tier_has_no_scene_and_no_sun():
    void = _flags(void=True, scene={"terrain": "ridge", "imagery": "x"})
    assert "-Visual" not in void and "-shot=showcase" not in void
    assert not [t for t in void if t.startswith(("-terrain=", "-imagery=",
                                                 "-sun-", "-fog-",
                                                 "-exposure-"))]
    assert "-GeorefTerrain" not in void
    visual = _flags(scene={"terrain": "ridge", "imagery": "x"})
    assert visual[visual.index("-GeorefTerrain") + 1] == "-terrain=ridge"
    assert "-imagery=x" in visual


def test_a_partial_look_is_completed_from_the_default_key_by_key():
    """The storm look states a fog; the time-of-day looks do not. The
    web app always filled the gap with the clear default; so does the
    builder."""
    flags = _flags(look={"sun_elev": 10.0, "sun_azim": 180.0,
                         "exposure_bias": 9.6})
    assert "-sun-elev=10.0" in flags
    assert f"-fog-density={DEFAULT_LOOK['fog_density']}" in flags
    default = _flags(look=None)
    for key, flag in (("sun_elev", "-sun-elev"), ("sun_azim", "-sun-azim"),
                      ("exposure_bias", "-exposure-bias"),
                      ("fog_density", "-fog-density")):
        assert f"{flag}={DEFAULT_LOOK[key]}" in default


def test_for_wrapper_strips_exactly_what_the_wrapper_adds_itself():
    flags = _flags(telemetry="/abs/host_telemetry.json",
                   extra=["-camera-index=1"], mesh="/abs/m.json")
    forwarded = for_wrapper(flags)
    assert not [t for t in forwarded if t.startswith(WRAPPER_OWNED_PREFIXES)]
    assert not set(forwarded) & set(LAUNCHER_FLAGS)
    # Everything else survives, in order.
    kept = [t for t in flags if t not in LAUNCHER_FLAGS
            and not t.startswith(WRAPPER_OWNED_PREFIXES)]
    assert forwarded == kept
    assert "-mesh=/abs/m.json" in forwarded and "-Visual" in forwarded


# -- both callers, one spec ---------------------------------------------

def _fake_subprocess(commands, wanted):
    """Intercepts the render launch only; every other subprocess (the
    manifest's git rev-parse probe) runs for real."""
    import subprocess

    real_run = subprocess.run

    def run(command, **kwargs):
        if not wanted(command):
            return real_run(command, **kwargs)
        commands.append([str(part) for part in command])

        class Done:
            returncode = 0
        return Done()
    return run


@pytest.fixture
def imported_repo(tmp_path, monkeypatch):
    """A repository root where the spec's model IS imported: the mesh
    manifest exists at the path both callers resolve (the CLI through
    its REPO, the web app through the path the run flow hands it), so
    both must forward the same -mesh=."""
    import flightsim.capture as capture_module

    spec = ScenarioSpec.read(SPEC)
    aircraft = str(spec.aircraft.value)
    mesh = tmp_path / "assets" / "generated" / aircraft / "mesh_manifest.json"
    mesh.parent.mkdir(parents=True)
    mesh.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(capture_module, "REPO", tmp_path)
    return tmp_path, mesh


def _cli_command(out, monkeypatch):
    import assets_pipeline.importer as importer_module
    import core.util.platform as platform_module

    commands = []
    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    monkeypatch.setattr("subprocess.run", _fake_subprocess(
        commands, lambda c: any("render_ue_scenario" in str(p) for p in c)))
    code = capture_main([str(SPEC), "--out", str(out), "--max-previews", "0",
                         "--render", "--no-host-flight"])
    assert code == 0
    assert len(commands) == 1
    return commands[0]


def _webapp_command(out, mesh, monkeypatch):
    """The web app's per-camera pass, exactly as _render_flow's lambda
    and webapp.capture.render_passes drive it (consume-poses, so no
    preset camera flags; -camera-index=N and -labels through extra)."""
    import webapp.runs as runs

    commands = []
    monkeypatch.setattr(runs.subprocess, "run", _fake_subprocess(
        commands, lambda c: "FlightSimRender" in " ".join(map(str, c))))
    spec = ScenarioSpec.read(SPEC)
    frames = out / "frames" / "chase0"
    runs.RunManager._render(
        out / "card.json", frames,
        {"key": "flat", "terrain": None, "imagery": None},
        mesh, str(spec.aircraft.value),
        telemetry=frames / "host_telemetry.json",
        look=runs.render_look_for(spec, None),
        camera_flags=None, extra=["-camera-index=0", "-labels"])
    assert len(commands) == 1
    return commands[0]


def test_the_cli_and_the_web_app_build_the_same_flags(imported_repo, tmp_path,
                                                       monkeypatch):
    from core.util.platform import ue_runner_command

    repo, mesh = imported_repo
    cli = _cli_command(tmp_path / "cli", monkeypatch)
    web = _webapp_command(tmp_path / "web", mesh, monkeypatch)

    # The CLI hands the wrapper <card> <frames> then the forwarded flags;
    # the wrapper writes -scenario= -frames= itself and, per camera,
    # -camera-index= -telemetry=, plus the launcher tokens.
    prefix = ue_runner_command(repo, "render_ue_scenario")
    assert cli[:len(prefix)] == prefix
    assert cli[len(prefix):len(prefix) + 2] == [
        str(tmp_path / "cli" / "card.json"), str(tmp_path / "cli" / "frames")]
    cli_flags = cli[len(prefix) + 2:]
    assert not [t for t in cli_flags if t.startswith(WRAPPER_OWNED_PREFIXES)]
    assert not set(cli_flags) & set(LAUNCHER_FLAGS)

    # The web app launches the editor itself.
    assert web[2] == "-run=FlightSimBridge.FlightSimRender"
    web_flags = for_wrapper(web[3:])

    assert cli_flags == web_flags, (
        f"the two render paths drifted:\n  cli only: "
        f"{sorted(set(cli_flags) - set(web_flags))}\n  web only: "
        f"{sorted(set(web_flags) - set(cli_flags))}")
    assert set(cli_flags) == set(web_flags)     # the contract's words

    # And both carry what the plan names.
    for command in (cli, web):
        assert [t for t in command if t.startswith("-mesh=")] == [f"-mesh={mesh}"]
        assert "-labels" in command
        assert "-Visual" in command
        assert "-deterministic" in command
        for key, flag in (("sun_elev", "-sun-elev"), ("sun_azim", "-sun-azim"),
                          ("exposure_bias", "-exposure-bias"),
                          ("fog_density", "-fog-density")):
            assert f"{flag}={DEFAULT_LOOK[key]}" in command
    # The web app's own per-camera tokens are there, once each.
    assert web.count("-camera-index=0") == 1
    assert web.count("-labels") == 1
    assert [t for t in web if t.startswith("-telemetry=")] == [
        f"-telemetry={tmp_path / 'web' / 'frames' / 'chase0' / 'host_telemetry.json'}"]


def test_the_web_app_s_legacy_single_pass_is_byte_identical(tmp_path,
                                                             monkeypatch):
    """The camera-less preset path: the recorded expectation (the
    pre-camera build's list, as tests/test_camera_spec.py reconstructs
    it) -- no -labels, no -deterministic, launcher tokens where they
    always were. The builder changed nothing here."""
    import webapp.runs as runs
    from experiments.showcase_matrix import (
        EDITOR, FPS, HEIGHT, TIME_OF_DAY, VISIBILITY, WIDTH,
    )

    commands = []
    monkeypatch.setattr(runs.subprocess, "run", _fake_subprocess(
        commands, lambda c: True))
    spec = compile_prompt("fly the 747 at 280 kt")
    card, frames = tmp_path / "card.json", tmp_path / "frames"
    runs.RunManager._render(card, frames,
                            {"key": "flat", "terrain": None, "imagery": None},
                            tmp_path / "missing_mesh.json", "B747",
                            camera_flags=runs.camera_render_flags(spec))
    tod = TIME_OF_DAY["noon"]
    assert commands[0] == [
        str(EDITOR), str(runs.REPO / "ue" / "FlightSim.uproject"),
        "-run=FlightSimBridge.FlightSimRender",
        f"-scenario={card}", f"-frames={frames}",
        "-Visual", "-shot=showcase",
        f"-chase={runs.WEBAPP_CHASE['B747']}", "-camera=chase",
        f"-fps={FPS}", f"-width={WIDTH}", f"-height={HEIGHT}",
        f"-sun-elev={tod['sun_elev']}", f"-sun-azim={tod['sun_azim']}",
        f"-exposure-bias={tod['exposure_bias']}",
        f"-fog-density={VISIBILITY['clear']}",
        "-unattended", "-nopause", "-nosplash",
        "-stdout", "-FullStdOutLogOutput",
        "-RenderOffScreen", "-AllowCommandletRendering",
    ]


def test_the_solve_pass_gains_nothing(tmp_path, monkeypatch):
    """_fly_host's throw-away render (a scripted card, telemetry only)
    passes Path("") for the mesh and no extra: no -mesh=, no -labels,
    no -deterministic -- its pixels are discarded, only its flight is
    kept, and a pin it did not have before would change nothing but the
    bytes the test above guards."""
    import webapp.runs as runs

    commands = []
    monkeypatch.setattr(runs.subprocess, "run", _fake_subprocess(
        commands, lambda c: True))
    telemetry = tmp_path / "host_flight" / "host_telemetry.json"
    runs.RunManager._render(tmp_path / "card.json", tmp_path / "solve_frames",
                            {"key": "flat", "terrain": None, "imagery": None},
                            Path(""), "B747", telemetry=telemetry)
    command = commands[0]
    assert f"-telemetry={telemetry}" in command
    assert switches_present(command) == ("-Visual",)
    assert not [t for t in command if t.startswith("-mesh=")]


def test_the_cli_void_tier_forwards_no_scene(imported_repo, tmp_path,
                                             monkeypatch):
    import assets_pipeline.importer as importer_module
    import core.util.platform as platform_module

    repo, mesh = imported_repo
    commands = []
    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    monkeypatch.setattr("subprocess.run", _fake_subprocess(
        commands, lambda c: any("render_ue_scenario" in str(p) for p in c)))
    code = capture_main([str(SPEC), "--out", str(tmp_path / "void"),
                         "--max-previews", "0", "--render",
                         "--no-host-flight", "--void"])
    assert code == 0
    command = commands[0]
    assert "-Visual" not in command
    assert not [t for t in command if t.startswith(("-sun-", "-terrain="))]
    assert f"-mesh={mesh}" in command
    assert "-labels" in command and "-deterministic" in command
