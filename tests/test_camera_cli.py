"""Camera Phase 1, package I: the instructor commands, end to end.

python -m flightsim.capture / flightsim.verify over the committed
examples, on the real headless flight dynamics -- the off-mac
demonstration path, exercised as a test so it cannot rot.
"""

import json
from pathlib import Path

import pytest

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
    assert manifest["manifest_version"] == 2
    assert len(manifest["frames"]) == 48          # 24 per camera, exact
    assert (demo_run / "telemetry.json").is_file()
    assert (demo_run / "scenario.yaml").is_file()
    previews = list((demo_run / "previews").rglob("*.png"))
    assert len(previews) == 3                     # capped by the flag
    # The manifest's digests are the run's own.
    run = json.loads((demo_run / "run.json").read_text(encoding="utf-8"))
    assert manifest["spec_digest"] == run["spec_digest"]
    assert manifest["output_digest"] == run["output_digest"]


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
    out = tmp_path / "buried"
    code = capture_main([str(EXAMPLES / "cameras_mountain_refusal.yaml"),
                         "--out", str(out), "--synth-terrain"])
    assert code == 2
    printed = capsys.readouterr().out
    assert "camera.terrain_clearance" in printed
    # Against the raster: the reported AGL is the ridge surface's, not
    # the spec's flat datum's.
    assert "m AGL" in printed
    assert not (out / "capture_manifest.json").exists()


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
