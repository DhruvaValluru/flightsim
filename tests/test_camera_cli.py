"""Camera Phase 1, package I: the instructor commands, end to end.

python -m flightsim.capture / flightsim.verify over the committed
examples, on the real headless flight dynamics -- the engine-less
demonstration path, exercised as a test so it cannot rot.
"""

import json
from pathlib import Path

import pytest

from core.capture.manifest import MANIFEST_VERSION
from core.scenario.camera import CameraSpec
from core.scenario.spec import ScenarioSpec
from flightsim.capture import main as capture_main
from flightsim.verify import main as verify_main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(scope="module")
def demo_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(out), "--max-previews", "3"])
    assert code == 0
    return out


def test_capture_writes_manifest_previews_and_telemetry(demo_run):
    manifest = json.loads(
        (demo_run / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == MANIFEST_VERSION
    assert len(manifest["frames"]) == 48          # 24 per camera, exact
    assert (demo_run / "telemetry.json").is_file()
    assert (demo_run / "scenario.yaml").is_file()
    previews = list((demo_run / "previews").rglob("*.png"))
    assert len(previews) == 3                     # capped by the flag
    # The manifest's digests are the run's own.
    run = json.loads((demo_run / "run.json").read_text(encoding="utf-8"))
    assert manifest["spec_digest"] == run["spec_digest"]
    assert manifest["output_digest"] == run["output_digest"]


def test_an_engine_less_capture_says_it_solved_over_the_pre_run(demo_run):
    """The manifest has to name the flight its aircraft labels describe.

    With no engine there IS only the headless pre-run, so this is not a
    failure -- it is the honest answer, and a consumer of these images
    can read it rather than assuming. On Windows with --render the same
    field reads "host flight" because the host flew the card first and
    the poses were re-solved over its telemetry.
    """
    from core.capture.manifest import SOLVE_PRE_RUN

    manifest = json.loads(
        (demo_run / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["solve_source"] == SOLVE_PRE_RUN
    # And no host flight was recorded, so nothing claims one.
    assert not (demo_run / "host_flight").exists()


def test_the_host_flight_can_be_declined_deliberately(capsys):
    """--no-host-flight is the old behaviour, kept because it is one
    commandlet pass cheaper. It has to be an explicit CHOICE -- the
    default is to solve over the flight the pixels are taken on -- and
    the help has to say what declining costs, or nobody choosing it
    knows they are choosing 1.38 m of label error.
    """
    with pytest.raises(SystemExit) as caught:
        capture_main(["--help"])
    assert caught.value.code == 0
    helptext = capsys.readouterr().out
    assert "--no-host-flight" in helptext
    assert "1.38 m" in helptext


def test_verify_passes_on_the_demo_run(demo_run, capsys):
    assert verify_main([str(demo_run)]) == 0
    out = capsys.readouterr().out
    assert "PASSED" in out
    assert "cross_view_consistency" in out


def test_two_camera_sets_align_in_time(demo_run, tmp_path, capsys):
    """The phase's headline property on REAL telemetry: the same
    simulation captured with a different camera set aligns
    frame-for-frame, proven by the alignment check itself."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    cockpit = CameraSpec.defaulted(camera_id="shoulder", preset="cockpit",
                                   aircraft="B747")
    cockpit.set("capture_count", 24, frm="same count, different view")
    spec.cameras = [cockpit]
    variant_spec = tmp_path / "variant.yaml"
    spec.write(variant_spec)
    variant_out = tmp_path / "variant"
    assert capture_main([str(variant_spec), "--out", str(variant_out),
                         "--max-previews", "0"]) == 0
    assert verify_main([str(variant_out), "--against",
                        str(demo_run)]) == 0
    assert "temporal_alignment" in capsys.readouterr().out


def test_refusal_example_refuses_by_name(tmp_path, capsys):
    code = capture_main([str(EXAMPLES / "cameras_refusal.yaml"),
                         "--out", str(tmp_path / "refused")])
    assert code == 2
    out = capsys.readouterr().out
    assert "camera.terrain_clearance" in out
    assert not (tmp_path / "refused" / "capture_manifest.json").exists()


def test_hazard_example_refuses_by_name(tmp_path, capsys):
    """The second refusal rule the phase never had an example for: a
    world-anchored camera stated inside the modelled tornado core is
    refused before anything flies, by name, and nothing is written."""
    code = capture_main([str(EXAMPLES / "cameras_hazard_refusal.yaml"),
                         "--out", str(tmp_path / "funnel")])
    assert code == 2
    out = capsys.readouterr().out
    assert "camera.hazard_intersection" in out
    assert "camera.terrain_clearance" not in out
    assert not (tmp_path / "funnel" / "capture_manifest.json").exists()


def test_card_carries_the_solved_pose_tracks(tmp_path):
    """python -m flightsim.capture --card: the run card's cameras block
    is the pose solver's own output, verbatim (the consume-verbatim
    contract's producing half)."""
    out = tmp_path / "carded"
    assert capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(out), "--max-previews", "0",
                         "--card"]) == 0
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (out / "capture_manifest.json").read_text(encoding="utf-8"))
    assert card["spec_digest"] == manifest["spec_digest"]
    assert len(card["cameras"]) == 2
    block = card["cameras"][0]
    assert block["camera_id"] == "chase0"
    poses = block["poses"]
    n = len(poses["t_s"])
    assert n == manifest["frames"][0]["sample_index"] + len(
        json.loads((out / "telemetry.json").read_text(
            encoding="utf-8"))["columns"]["t"]) - manifest["frames"][0][
                "sample_index"]
    for key in ("north_m", "east_m", "alt_m", "yaw_deg", "pitch_deg",
                "roll_deg", "focal_length_mm"):
        assert len(poses[key]) == n
    # Strictly increasing times: the commandlet refuses anything else.
    assert all(b > a for a, b in zip(poses["t_s"], poses["t_s"][1:]))
    # The capture times are the schedule's, sample-aligned.
    assert len(block["capture_times_s"]) == 24
    assert block["origin_x_m"] == manifest["frame"]["origin_x_m"]
    # Flat scene: the card declares the projected frame.
    assert card["scene_crs"] == manifest["frame"]["crs"]


def test_render_projects_the_spec_for_the_host_before_solving(tmp_path):
    """--render must apply the same host projection the webapp has
    applied since Gate 8.3.

    The render hosts have no autopilot, so the commandlet refuses a
    spec that commands a held state -- and hold_state defaults to TRUE.
    Without the projection, --render flew the scenario headlessly,
    solved every pose track, launched Unreal, and only then hit that
    refusal, having burned the whole run to learn something readable
    off the spec. Worse, the poses would have been solved over a
    closed-loop flight the open-loop host was never going to fly.
    """
    from webapp.runs import project_for_ue_host

    repo = Path(__file__).resolve().parents[1]
    spec = ScenarioSpec.read(repo / "examples" / "cameras_multi.yaml")
    assert bool(spec.hold_state.value) is True, (
        "the example no longer exercises the refusal this guards")

    project_for_ue_host(spec)
    assert bool(spec.hold_state.value) is False
    assert bool(spec.mass_held.value) is True
    assert str(spec.airspeed_kind.value) != "tas"
    # The move is recorded, never silent.
    assert "autopilot" in str(spec.hold_state.frm).lower()


# -- the single verification command (package I) ------------------------

def test_demo_runs_alignment_recovery_and_consistency(tmp_path, capsys):
    """One command, all three exit-criterion properties. Temporal
    alignment needs TWO runs of the same simulation, so flightsim.verify
    over one directory can never report it; this command captures both.
    """
    from flightsim.demo import main as demo_main

    code = demo_main(["--out", str(tmp_path / "demo"), "--max-previews", "0"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "temporal_alignment" in out
    assert "geometry_recovery" in out
    assert "cross_view_consistency" in out
    assert "DEMO PASSED" in out
    # Both directories exist and carry the deliverable.
    assert (tmp_path / "demo" / "capture_manifest.json").is_file()
    assert (tmp_path / "demo_variant" / "capture_manifest.json").is_file()


def test_demo_variant_is_the_same_simulation(tmp_path, capsys):
    """The alignment claim is only worth anything if the two runs really
    are one simulation: the camera-free digests must match while the spec
    digests differ."""
    import json

    from flightsim.demo import main as demo_main

    assert demo_main(["--out", str(tmp_path / "demo"),
                      "--max-previews", "0"]) == 0
    first = json.loads((tmp_path / "demo" / "capture_manifest.json")
                       .read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "demo_variant" / "capture_manifest.json")
                        .read_text(encoding="utf-8"))
    assert first["spec_digest"] != second["spec_digest"]
    assert first["simulation_digest"] == second["simulation_digest"]
    assert first["output_digest"] == second["output_digest"]


# -- terrain examples: real raster, no network (package I) --------------
#
# The phase asks for "a waypoint capture over real terrain" and "a
# refusal case with a camera placed inside a mountain". Both committed
# examples ran over a FLAT scene before this: the waypoint one because
# it needed a bake the instructor did not have, and the refusal one
# because it refused against the spec's flat datum rather than against a
# raster. A synthesised raster centred on the spec's own origin needs no
# network and no account, and reaches the ground callback as the same
# Heightfield a Copernicus bake produces.

def test_terrain_example_captures_over_a_real_raster(tmp_path):
    from core.capture.verify import verify_run

    out = tmp_path / "terrain"
    assert capture_main([str(EXAMPLES / "cameras_terrain.yaml"),
                         "--out", str(out), "--synth-terrain",
                         "--max-previews", "0"]) == 0
    manifest = json.loads((out / "capture_manifest.json")
                          .read_text(encoding="utf-8"))
    # A raster, not a datum: the manifest records its digest.
    assert manifest["scene"]["terrain_sha256"]
    assert manifest["scene"]["key"] == "terrain"
    report = verify_run(out)
    assert report.ok, report.render()


def test_camera_inside_a_mountain_refuses_against_the_raster(tmp_path,
                                                             capsys):
    """AS DOCUMENTED, with no flag: the example states
    scene.terrain_source: synthesised (spec 8), so the command its
    header gives refuses against the ridge. Before the bump the spec
    carried no terrain reference and the documented command ran it over
    the flat datum -- valid, and a lie about what the example shows."""
    out = tmp_path / "buried"
    code = capture_main([str(EXAMPLES / "cameras_mountain_refusal.yaml"),
                         "--out", str(out)])
    assert code == 2
    printed = capsys.readouterr().out
    assert "camera.terrain_clearance" in printed
    # Against the raster: the reported AGL is the ridge surface's, not
    # the spec's flat datum's.
    assert "m AGL" in printed
    assert "scene.terrain_source: synthesised" in printed
    assert not (out / "capture_manifest.json").exists()


def test_the_synth_terrain_flag_is_still_an_alias(tmp_path, capsys):
    """--synth-terrain keeps working on a spec whose terrain_source is
    auto (the cameras_terrain example), and says it is the alias."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_mountain_refusal.yaml")
    spec.set("scene.terrain_source", "auto", frm="test: the flag decides")
    auto = tmp_path / "auto.yaml"
    spec.write(auto)
    # Without the flag an auto spec flies the flat datum: the buried
    # camera is 2500 m above it, so nothing refuses -- proof the field,
    # not the flag, is what the committed example now relies on.
    with_flag = capture_main([str(auto), "--out", str(tmp_path / "flag"),
                              "--synth-terrain"])
    assert with_flag == 2
    printed = capsys.readouterr().out
    assert "camera.terrain_clearance" in printed
    assert "--synth-terrain" in printed


def test_a_flag_that_contradicts_the_stated_terrain_source_refuses(
        tmp_path, capsys):
    """A stated field and a contradicting flag: neither is dropped in
    silence -- refused by name (scene.terrain) before any flight."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    spec.set("scene.terrain_source", "flat", frm="test")
    flat = tmp_path / "flat.yaml"
    spec.write(flat)
    code = capture_main([str(flat), "--out", str(tmp_path / "x"),
                         "--synth-terrain"])
    assert code == 2
    assert "[scene.terrain]" in capsys.readouterr().out
    spec.set("scene.terrain_source", "baked", frm="test")
    baked = tmp_path / "baked.yaml"
    spec.write(baked)
    code = capture_main([str(baked), "--out", str(tmp_path / "y")])
    assert code == 2
    assert "no bake is named" in capsys.readouterr().out
    code = capture_main([str(baked), "--out", str(tmp_path / "z"),
                         "--terrain", str(tmp_path / "nowhere")])
    assert code == 2
    assert "not a whole bake" in capsys.readouterr().out


# -- every example loads at spec 8 and does what its header says ----------

def _header_outcome(path: Path) -> str:
    """'refuses:<name>' when the header states REFUSED [<name>], else
    'valid'."""
    import re

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        match = re.search(r"REFUSED \[([a-z_.]+)\]", line)
        if match:
            return f"refuses:{match.group(1)}"
    return "valid"


@pytest.mark.parametrize("name", sorted(
    p.name for p in EXAMPLES.glob("*.yaml") if p.name != "batch_matrix.yaml"))
def test_every_example_loads_at_spec_8_and_matches_its_header(name, tmp_path,
                                                              capsys):
    """batch_matrix.yaml is a batch file over cameras_multi.yaml, not a
    spec (tests/test_dataset.py runs it). Every other example reads at
    SPEC_VERSION, and either validates (its header states no refusal)
    or refuses BY THE NAME its header states, with the documented
    command's flags only (none)."""
    from core.scenario.spec import SPEC_VERSION
    from core.scenario.validate import validate

    path = EXAMPLES / name
    spec = ScenarioSpec.read(path)
    assert spec.to_dict()["spec_version"] == SPEC_VERSION
    outcome = _header_outcome(path)
    if outcome == "valid":
        report = validate(spec, check_feasibility=False)
        assert report.ok, report.render()
    else:
        expected = outcome.split(":", 1)[1]
        code = capture_main([str(path), "--out", str(tmp_path / "run")])
        assert code == 2
        assert f"[{expected}]" in capsys.readouterr().out


def test_synthesised_terrain_is_deterministic(tmp_path):
    """Two syntheses of the same origin are the same raster -- otherwise
    the committed refusal example would refuse on some runs and not on
    others."""
    from core.terrain.synthesis import ridge_for_origin

    a = ridge_for_origin(0.0, 0.0, size=128)
    b = ridge_for_origin(0.0, 0.0, size=128)
    assert a.digest() == b.digest()
    assert a.georeference.to_dict() == b.georeference.to_dict()


def test_the_synthesised_raster_is_centred_on_the_spec_origin(tmp_path):
    """A raster the flight is not over is a flat datum with extra
    steps: the spec's own origin must land on it."""
    from pyproj import Transformer

    from core.terrain.synthesis import ridge_for_origin

    field = ridge_for_origin(46.5, 8.5, size=128)
    forward = Transformer.from_crs("EPSG:4326", field.georeference.crs,
                                   always_xy=True)
    x, y = forward.transform(8.5, 46.5)
    assert field.contains(x, y)
    column, row = field._pixel_coords(x, y)
    assert abs(column - (field.width - 1) / 2.0) < 1.0
    assert abs(row - (field.height - 1) / 2.0) < 1.0


def test_a_terrain_impact_is_a_named_refusal_not_a_traceback(tmp_path,
                                                             capsys):
    """Flying a low example over a high ridge printed a stack trace at
    the instructor. An impact is a named outcome of the scenario."""
    from core.scenario.spec import ScenarioSpec

    spec = ScenarioSpec.read(EXAMPLES / "cameras_terrain.yaml")
    spec.set("altitude", 1000.0, frm="test: below the ridge")
    low = tmp_path / "low.yaml"
    spec.write(low)
    code = capture_main([str(low), "--out", str(tmp_path / "impact"),
                         "--synth-terrain", "--max-previews", "0"])
    assert code == 2
    assert "terrain.impact" in capsys.readouterr().out


def test_synthesised_terrain_cache_is_keyed_by_the_origin(tmp_path):
    """A cached raster reused after an example moved its origin would be
    a raster the flight is not over -- silently, and the camera checks
    would go back to measuring nothing."""
    from core.terrain.synthesis import ensure_ridge_for_origin

    first = ensure_ridge_for_origin(tmp_path, 46.0, 8.0, name="r", size=64)
    again = ensure_ridge_for_origin(tmp_path, 46.0, 8.0, name="r", size=64)
    moved = ensure_ridge_for_origin(tmp_path, 47.0, 8.0, name="r", size=64)
    assert first == again                       # same origin: reused
    assert moved != first                       # moved origin: a new raster
    assert moved.with_suffix(".r16").is_file()


# -- --camera-sets: alignment that actually runs -------------------------

def test_camera_sets_captures_twice_and_aligns(tmp_path, capsys):
    """The check that was real and almost never ran.

    Temporal alignment asserts that the CAMERA SET does not perturb the
    simulation or the capture clock. Exercising it used to mean
    capturing twice by hand and remembering --against, so in practice
    it reported NOT RUN -- which is not a pass, and was not being read
    as one either. One command now does both captures and grades them.
    """
    code = verify_main(["--camera-sets", str(EXAMPLES / "cameras_multi.yaml"),
                        "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "[PASS] temporal_alignment" in out
    assert "align exactly across the two camera sets" in out
    # Two runs, one per half of the spec's camera list.
    assert (tmp_path / "set_a" / "capture_manifest.json").is_file()
    assert (tmp_path / "set_b" / "capture_manifest.json").is_file()
    a = json.loads((tmp_path / "set_a" / "capture_manifest.json")
                   .read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "set_b" / "capture_manifest.json")
                   .read_text(encoding="utf-8"))
    # Different cameras, same flight: that is the whole property.
    assert ({c["camera_id"] for c in a["cameras"]}
            != {c["camera_id"] for c in b["cameras"]})
    assert a["output_digest"] == b["output_digest"]


def test_camera_sets_refuses_a_spec_with_one_camera(tmp_path, capsys):
    """Two sets need two cameras. One camera cannot demonstrate that the
    camera set makes no difference."""
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    spec.cameras = spec.cameras[:1]
    written = tmp_path / "one.yaml"
    spec.write(written)
    code = verify_main(["--camera-sets", str(written), "--out",
                        str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert code == 2
    assert "verify.camera_sets" in out
    assert "at least two" in out


def test_camera_sets_refuses_when_the_two_sets_ask_for_different_schedules(
        tmp_path, capsys):
    """A spurious red is worse than a NOT RUN.

    Alignment compares capture INSTANTS. Two sets that requested
    different schedules legitimately do not align -- that is the spec's
    shape, not a defect -- and grading them against each other would
    print a failure that is not one, which is how people learn to
    ignore a check.
    """
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    spec.cameras[1].set("capture_count", 11, frm="test")
    written = tmp_path / "mixed.yaml"
    spec.write(written)
    code = verify_main(["--camera-sets", str(written), "--out",
                        str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert code == 2
    assert "verify.camera_sets" in out
    assert "different capture schedules" in out
    # And it said so BEFORE flying anything.
    assert not (tmp_path / "out" / "set_a" / "capture_manifest.json").exists()


def test_camera_sets_will_not_also_take_a_run_directory(tmp_path):
    """It captures its own two runs; taking a third would leave which
    one was graded ambiguous."""
    with pytest.raises(SystemExit):
        verify_main([str(tmp_path), "--camera-sets",
                     str(EXAMPLES / "cameras_multi.yaml"),
                     "--out", str(tmp_path / "out")])


def test_capture_leaves_a_label_file_beside_every_frame(demo_run):
    """The CLI's own writer, on a real headless flight: every frame the
    manifest names has its sidecar, carrying the recorder's whole row
    at that instant -- wind, forces, controls -- not six numbers."""
    manifest = json.loads(
        (demo_run / "capture_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == MANIFEST_VERSION
    units = manifest["state_units"]
    for record in manifest["frames"]:
        sidecar = demo_run / (record["file"][:-4] + ".json")
        assert sidecar.is_file(), record["file"]
        state = json.loads(sidecar.read_text(encoding="utf-8"))["frame"]["state"]
        # The headless recorder's channels, at the frame's own sample.
        for channel in ("wind_north_mps", "lift_n", "alpha_deg", "n_z",
                        "elevator_deg", "agl_m", "tas_kt"):
            assert channel in state, channel
            assert channel in units, channel
        assert state["t"] == record["t_s"]
    assert "?" not in units.values(), (
        f"a recorded channel with no stated unit: "
        f"{[k for k, v in units.items() if v == '?']}")


def test_a_closure_failure_is_a_named_refusal_not_a_traceback(tmp_path,
                                                             capsys,
                                                             monkeypatch):
    """Measured: a 747 asked to HOLD altitude in severe turbulence did not
    settle within the declared tolerance, and the CLI unwound a
    ClosureError stack trace at the instructor. The runner's refusal to
    emit output is a named outcome of the scenario."""
    from core.control.autopilot import ClosureError
    import core.scenario.runner as runner_module

    def refuse(*args, **kwargs):
        raise ClosureError("closure: FAIL\n  FAIL settled  commanded 0.00 "
                           "m/s, achieved 1.08 (+1.08, tol 1.00)")

    # The CLI imports run_spec at call time from the runner module.
    monkeypatch.setattr(runner_module, "run_spec", refuse)
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"),
                         "--out", str(tmp_path / "unsettled"),
                         "--max-previews", "0"])
    assert code == 2
    out = capsys.readouterr().out
    assert "REFUSED -- run.closure" in out
    assert "Traceback" not in out
    assert not (tmp_path / "unsettled" / "capture_manifest.json").exists()


def test_event_example_captures_on_the_downburst_and_verifies(tmp_path):
    """The event-driven example the phase never had: frames fire only
    while the recorded sink rate is below the stated threshold, the
    count is the event's, and the run verifies."""
    from core.capture.verify import verify_run

    out = tmp_path / "on_sink"
    assert capture_main([str(EXAMPLES / "cameras_event_trigger.yaml"),
                         "--out", str(out), "--max-previews", "0"]) == 0
    manifest = json.loads((out / "capture_manifest.json")
                          .read_text(encoding="utf-8"))
    frames = manifest["frames"]
    assert len(frames) >= 10
    assert all(float(f["state"]["climb_rate_mps"]) < -10.0 for f in frames)
    # Not a clock: the first capture is well into the flight, where the
    # downburst is, and consecutive captures respect the refractory.
    assert frames[0]["t_s"] > 5.0
    gaps = [b["t_s"] - a["t_s"] for a, b in zip(frames, frames[1:])]
    assert min(gaps) >= 1.0 - 1e-6
    report = verify_run(out)
    assert report.ok, report.render()


# -- the mesh the render draws --------------------------------------------
#
# Measured (Camera Phase 1 initial run report): the CLI's --render never
# passed -mesh= (the web app has since the placeholder rule), so the
# commandlet drew the placeholder boxes under a manifest whose assets
# block named the real mesh. Imported -> the wrapper gets -mesh=; not
# imported -> aircraft.mesh, by name, before any flight or engine time.

def _is_render_wrapper(command) -> bool:
    return "render_ue_scenario" in str(command[0])


def _fake_run(commands):
    """Intercepts the render WRAPPER only; every other subprocess (the
    manifest's git rev-parse probe, say) runs for real."""
    import subprocess

    real_run = subprocess.run

    def run(command, **kwargs):
        if not _is_render_wrapper(command):
            return real_run(command, **kwargs)
        commands.append([str(part) for part in command])

        class Done:
            returncode = 0
        return Done()
    return run


def test_render_passes_the_imported_mesh_to_the_wrapper(tmp_path, monkeypatch):
    import core.util.platform as platform_module
    import assets_pipeline.importer as importer_module

    commands = []
    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: True)
    monkeypatch.setattr("subprocess.run", _fake_run(commands))
    out = tmp_path / "rendered"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out", str(out),
                         "--max-previews", "0", "--render", "--no-host-flight"])
    assert code == 0
    assert len(commands) == 1                     # one render wrapper call
    spec = ScenarioSpec.read(EXAMPLES / "cameras_multi.yaml")
    repo = Path(__file__).resolve().parents[1]
    expected = repo / "assets" / "generated" / str(spec.aircraft.value) / "mesh_manifest.json"
    assert [a for a in commands[0] if a.startswith("-mesh=")] == [f"-mesh={expected}"]
    assert "-labels" in commands[0]
    assert (out / "capture_manifest.json").is_file()


def test_render_refuses_an_unimported_mesh_before_any_flight(tmp_path, capsys,
                                                             monkeypatch):
    import core.util.platform as platform_module
    import assets_pipeline.importer as importer_module

    import subprocess

    real_run = subprocess.run

    def never(command, **kwargs):
        if _is_render_wrapper(command):
            raise AssertionError(f"the wrapper was launched: {command}")
        return real_run(command, **kwargs)

    monkeypatch.setattr(platform_module, "ue_available", lambda: True)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: False)
    monkeypatch.setattr("subprocess.run", never)
    out = tmp_path / "refused"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out", str(out),
                         "--max-previews", "0", "--render", "--no-host-flight"])
    assert code == 2
    text = capsys.readouterr().out
    assert "REFUSED -- aircraft.mesh" in text
    assert "scripts/import_aircraft.py" in text
    assert "structural datum" in text
    # Before any flight: nothing was run, nothing written.
    assert not out.exists()


def test_without_the_engine_an_unimported_mesh_is_not_a_refusal(tmp_path,
                                                                 monkeypatch):
    """Off Windows/Mac the render is refused later as ue.platform and the
    manifest is the deliverable, exactly as before: the mesh check applies
    only where the engine is."""
    import core.util.platform as platform_module
    import assets_pipeline.importer as importer_module

    monkeypatch.setattr(platform_module, "ue_available", lambda: False)
    monkeypatch.setattr(importer_module, "is_imported", lambda name: False)
    out = tmp_path / "engineless"
    code = capture_main([str(EXAMPLES / "cameras_multi.yaml"), "--out", str(out),
                         "--max-previews", "0", "--render", "--no-host-flight"])
    assert code == 0
    assert (out / "capture_manifest.json").is_file()
