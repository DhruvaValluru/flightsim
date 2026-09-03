"""The capture half, on the page.

Camera Phase 1's brief asked for "a defined number of images rather than
a clip", with every frame carrying enough geometry to be used as labeled
data -- and landed that as a CLI while the webapp still produced only a
clip. These tests pin the surface that closes it (user request
2026-09-01: "i want the web app the interface where they can access
everything"):

* a capture run produces the manifest, previews and verification, on a
  machine with no engine at all -- the half that runs everywhere;
* the page can enumerate and download every artefact, and CANNOT be
  talked into serving anything else;
* an exact frame count is a contract here too, and the verifier's own
  report is what the page shows -- not a re-derivation of it;
* a named capture refusal is reported by name, never swallowed and
  never allowed to masquerade as a successful capture.
"""

import json
import zipfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from core.nl.compiler import compile_prompt
from webapp.server import app, manager
import webapp.capture as capture_module
import webapp.runs as runs_module


DEMO = ("fly the 747 at 5000 ft over the prairie for 3 seconds with a "
        "chase camera capturing 4 images")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "out_root", tmp_path / "runs")
    monkeypatch.setattr(manager, "_active", None)
    # Pin the flat scene: on a machine with the control ridge baked,
    # pick_scene puts any prompt with a terrain elevation onto the ridge
    # and this 5000 ft prairie run refuses terrain.clearance under
    # 3299 m peaks before the closure pair is ever reached. These tests
    # are about the closure pair, not scene selection.
    import webapp.server as server_module
    import webapp.runs as runs_module
    flat = {"key": "flat", "kind": "flat", "terrain": None,
            "imagery": None, "label": "flat (test)"}
    monkeypatch.setattr(server_module, "pick_scene", lambda spec: flat)
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: flat)
    return TestClient(app)


def finished(client, run_id, limit=600):
    """Poll the run to completion; the worker is a daemon thread."""
    import time

    for _ in range(limit):
        state = client.get(f"/runs/{run_id}").json()
        if state["status"] in ("done", "failed"):
            return state
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} never finished")


@pytest.fixture()
def captured(client):
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    return run_id, finished(client, run_id)


# -- the capture itself ---------------------------------------------------

def test_capture_runs_without_an_engine(captured):
    """The load-bearing property: no pixels, no editor, no platform gate
    -- and still the full labeled-data deliverable. This suite runs on a
    machine with no Unreal host, so a pass here IS the evidence."""
    run_id, state = captured
    assert state["status"] == "done"
    assert state["clip"] is None
    assert "no pixels" in state["detail"]

    capture = state["capture"]
    assert capture["frames"] == 4                 # the stated count, exactly
    assert [c["frames"] for c in capture["cameras"]] == [4]
    assert capture["previews"] == 4


def test_the_page_shows_the_verifier_s_own_report(captured, client):
    """The five checks come from verify.json as run -- the page renders a
    report, it does not compute a second opinion. A discrepancy between
    the two would be exactly the kind of self-confirming verification
    this phase refused to build."""
    run_id, state = captured
    verification = state["capture"]["verification"]
    assert verification["ok"] is True
    names = [c["name"] for c in verification["checks"]]
    assert names == ["manifest_version", "fields_finite", "geometry_recovery",
                     "cross_view_consistency", "count_exactness",
                     "engine_parity"]
    # No engine on this machine: the engine-parity check is AWAITING in
    # those words -- not passed (nothing was rendered), not failed (the
    # run never claimed pixels), and not counted among the passed.
    engine = verification["checks"][-1]
    assert engine["ok"] is None and engine["status"] == "AWAITING"
    assert "awaiting engine frames" in engine["detail"]
    assert verification["awaiting"] == ["engine_parity"]
    assert verification["passed"] == 5 and verification["ran"] == 5

    on_disk = json.loads(
        (manager.out_root / run_id / "capture" / "verify.json")
        .read_text(encoding="utf-8"))
    assert on_disk == verification


def test_the_manifest_describes_its_own_flight(captured, client):
    """Two hosts, two telemetry files, neither presented as the other:
    the manifest sits beside the headless telemetry it was solved from,
    so a reader can always tell which flight a number came from."""
    run_id, _ = captured
    capture_dir = manager.out_root / run_id / "capture"
    manifest = json.loads(
        (capture_dir / "capture_manifest.json").read_text(encoding="utf-8"))
    telemetry = json.loads(
        (capture_dir / "telemetry.json").read_text(encoding="utf-8"))
    assert manifest["frames"]
    # Every captured instant is inside the flight recorded next to it.
    times = telemetry["columns"]["t"]
    for record in manifest["frames"]:
        assert min(times) <= record["t_s"] <= max(times)


# -- everything downloadable ---------------------------------------------

def test_every_artefact_is_listed_and_downloadable(captured, client):
    run_id, _ = captured
    files = client.get(f"/runs/{run_id}/files").json()["files"]
    names = [f["name"] for f in files]
    for expected in ("provenance.json", "scenario.yaml",
                     "capture/capture_manifest.json", "capture/verify.json",
                     "capture/telemetry.json", "capture/run.json"):
        assert expected in names, expected
    assert all(f["note"] for f in files)        # every entry says what it is

    previews = next(f for f in files if "previews" in f["name"])
    assert previews["count"] == 4

    for name in names:
        if "previews" in name:
            continue
        got = client.get(f"/runs/{run_id}/file/{name}")
        assert got.status_code == 200, name
        assert len(got.content) > 0
    first_image = previews["images"][0]
    assert client.get(f"/runs/{run_id}/file/{first_image}").status_code == 200


def test_the_bundle_carries_exactly_what_was_listed(captured, client):
    run_id, _ = captured
    files = client.get(f"/runs/{run_id}/files").json()["files"]
    listed = set()
    for entry in files:
        listed.update(entry.get("images") or [entry["name"]])

    bundle = client.get(f"/runs/{run_id}/bundle.zip")
    assert bundle.status_code == 200
    path = manager.out_root / run_id / "bundle.zip"
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == listed


def test_the_download_route_serves_only_this_run_s_own_files(captured,
                                                             client):
    """A whitelist built from what the run wrote, not a path check: a
    name the run never produced is a 404 whatever it looks like.

    The traversals are PERCENT-ENCODED on purpose. A plain "../x" is
    collapsed by the HTTP client before the request is sent, so testing
    it would test httpx, not this route; the encoded forms arrive at the
    handler intact and are what a real attempt looks like.
    """
    run_id, _ = captured
    for attempt in ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "..%2Fbundle.zip",
                    "capture%2F..%2F..%2Fsecrets.json",
                    "does_not_exist.json", "/etc/passwd"):
        assert client.get(
            f"/runs/{run_id}/file/{attempt}").status_code == 404, attempt


# -- refusals -------------------------------------------------------------

def test_a_named_capture_refusal_is_reported_not_swallowed(client,
                                                           monkeypatch):
    """A capture that cannot honour the spec says which constraint
    refused. It must never report a successful capture with no manifest
    behind it."""
    def refuse(spec, out, scene, report):
        raise capture_module.CaptureError(
            "camera.schedule", "4 captures over a 3 s run at 1 s period")

    monkeypatch.setattr(capture_module, "capture_run", refuse)
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "failed"
    assert state["capture"]["refused"] == "camera.schedule"
    assert "3 s run" in state["capture"]["message"]


def test_both_endpoints_refuse_the_same_spec_the_same_way(client):
    """/capture and /run share one preparation function, so the planner
    ORDER and every named refusal are the same by construction. A camera
    inside the terrain is refused before either does any work."""
    spec = compile_prompt(DEMO)
    spec.set("cameras[0].position_mode", "scene", frm="test")
    spec.set("cameras[0].position_alt_m", -500.0,
             frm="test: below the terrain")
    payload = {"spec": spec.to_dict()}
    capture_reply = client.post("/capture", json=payload)
    run_reply = client.post("/run", json=payload)
    assert capture_reply.status_code == 409
    assert capture_reply.json()["refused"] == "validation"
    constraints = {v["constraint"]
                   for v in capture_reply.json()["violations"]}
    assert "camera.terrain_clearance" in constraints
    # /run refuses identically (it may stop at the platform gate first on
    # a machine with no engine -- the spec refusal is what is shared).
    assert run_reply.status_code == 409


def test_a_render_run_captures_beside_the_clip(monkeypatch):
    """On a render-capable host the clip and the manifest come out of the
    SAME run: the capture phase is part of the render flow, not a
    separate thing the user has to remember."""
    import inspect

    source = inspect.getsource(runs_module.RunManager._render_flow)
    assert "_capture_phase" in source
    assert source.index("_capture_phase") < source.index('run.push("done"')


def test_a_refused_track_writes_no_manifest(tmp_path, monkeypatch):
    """A solved track the scene refuses stops the capture BEFORE the
    manifest exists. A manifest is a claim that the geometry is real; a
    refused run must not leave one behind for a reader to trust."""
    from core.scenario.validate import Violation
    import core.capture.validate as validate_module

    monkeypatch.setattr(
        validate_module, "track_violations",
        lambda *a, **k: [Violation(
            constraint="camera.terrain_clearance",
            message="the solved track enters the terrain",
            actual=-3.0, limit=2.0, unit="m")])

    spec = compile_prompt(DEMO)
    out = tmp_path / "run"
    with pytest.raises(capture_module.CaptureError) as caught:
        capture_module.capture_run(
            spec, out, {"key": "flat", "terrain": None})
    assert caught.value.constraint == "camera.terrain_clearance"
    assert not (out / "capture" / "capture_manifest.json").exists()


# -- the frames flow: the engine pass once per camera ---------------------
# The engine cannot run here, so _render is stubbed with an HONEST engine:
# it reads the card's cameras block exactly as the commandlet does, writes
# one PNG per scheduled instant named by its index, and a render.json whose
# applied pose is the solved pose at that instant. Anything the flow claims
# about frames must then be backed by files this stub wrote.

TWO_CAMERA = ("fly the 747 at 5000 ft over the prairie for 3 seconds with "
              "a chase camera capturing 4 images")


def two_camera_spec():
    from core.scenario.camera import CameraSpec

    spec = compile_prompt(TWO_CAMERA)
    tower = CameraSpec.defaulted(camera_id="tower0", preset="tower",
                                 aircraft="B747")
    tower.set("capture_count", 4, frm="test: the same count, a second view")
    spec.cameras.append(tower)
    return spec


def honest_engine(calls, short_for=None, fail_for=None):
    """A _render stub that behaves like the consume-poses pass."""
    from PIL import Image

    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera_flags=None, camera_index=None,
                    log=None, **kwargs):
        calls.append({"card": Path(card), "frames": Path(frames),
                      "camera_index": camera_index, "camera_flags": camera_flags,
                      "telemetry": telemetry, "log": log})
        if fail_for is not None and camera_index == fail_for:
            return False
        block = json.loads(Path(card).read_text(encoding="utf-8"))[
            "cameras"][camera_index]
        poses = block["poses"]
        times = block["capture_times_s"]
        if short_for is not None and camera_index == short_for:
            times = times[:-1]
        frames = Path(frames)
        frames.mkdir(parents=True, exist_ok=True)
        records = []
        for index, t in enumerate(times):
            k = poses["t_s"].index(t)
            records.append({
                "frame_index": index, "frame": f"{index:04d}.png",
                "t_scheduled_s": t, "t_applied_s": poses["t_s"][k],
                "camera_applied_north_m": poses["north_m"][k],
                "camera_applied_east_m": poses["east_m"][k],
                "camera_applied_alt_m": poses["alt_m"][k],
                "camera_applied_yaw_deg": poses["yaw_deg"][k],
                "camera_applied_pitch_deg": poses["pitch_deg"][k],
                "camera_applied_roll_deg": poses["roll_deg"][k],
            })
            Image.new("RGB", (block["width_px"], block["height_px"]),
                      (30, 30, 30)).save(frames / f"{index:04d}.png")
        (frames / "render.json").write_text(json.dumps({
            "host": "unreal", "camera_consume_poses": True,
            "camera_index": camera_index,
            "width": block["width_px"], "height": block["height_px"],
            "step_s": 1.0 / 120.0,
            "frames_scheduled": len(block["capture_times_s"]),
            "frames_captured": len(times),
            "frame_records": records,
        }), encoding="utf-8")
        if log is not None:
            Path(log).write_text("stub editor log\n", encoding="utf-8")
        return True
    return fake_render


@pytest.fixture()
def engine_stubs(tmp_path, monkeypatch):
    """Everything around the engine held open so the flow under test is
    reached on a machine with no engine, no ffmpeg and no meshes."""
    from webapp.runs import RunManager

    flat = {"key": "flat", "kind": "flat", "terrain": None,
            "imagery": None, "label": "flat (test)"}
    monkeypatch.setattr(runs_module, "pick_scene", lambda spec: flat)
    monkeypatch.setattr(runs_module, "ensure_control_ridge", lambda: None)
    monkeypatch.setattr(runs_module, "ensure_aircraft_model",
                        lambda spec, report: None)
    encoded = []

    def fake_encode(ffmpeg, frames_dir, times, clip, lead_in_s=None):
        encoded.append({"frames_dir": Path(frames_dir), "times": list(times),
                        "clip": Path(clip)})
        Path(clip).write_bytes(b"mp4")
        return True

    monkeypatch.setattr(runs_module, "encode_scheduled_clip", fake_encode)
    import core.util.platform as plat
    monkeypatch.setattr(plat, "find_ffmpeg", lambda: Path("ffmpeg"))
    # The clip flow's own encoder/panel, for the clip-only comparison.
    monkeypatch.setattr(runs_module, "encode_clip",
                        lambda frames, clip: bool(clip.write_bytes(b"x")) or True)
    monkeypatch.setattr(runs_module, "build_panel_clip",
                        lambda *a, **k: True)
    return {"manager": RunManager(out_root=tmp_path / "runs"),
            "encoded": encoded, "monkeypatch": monkeypatch}


def test_frames_flow_invokes_the_engine_once_per_camera(engine_stubs):
    """The gap this closes: the page's render flow never entered the
    commandlet's consume-poses branch. Now a frames run writes the card
    WITH the cameras block and runs one pass per camera, each with its
    own -camera-index and its own capture/frames/<camera_id> directory,
    and the status line names what came out of it."""
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    manager = engine_stubs["manager"]
    spec = two_camera_spec()
    run = RunState(run_id="framesrun")
    manager._render_flow(run, spec, provenance={}, render="frames")
    assert run.status == "done", run.detail
    out = manager.out_root / "framesrun"

    # One pass per camera, in card order, by index, into its own directory,
    # with NO preset words (the card's track places the camera).
    assert [c["camera_index"] for c in calls] == [0, 1]
    assert [c["frames"] for c in calls] == [
        out / "capture" / "frames" / "camera0",
        out / "capture" / "frames" / "tower0"]
    assert all(c["camera_flags"] is None for c in calls)
    assert calls[0]["telemetry"] == out / "telemetry.json"
    assert calls[1]["telemetry"] is None
    assert [c["log"] for c in calls] == [
        out / "capture" / "frames" / "camera0" / "render.log",
        out / "capture" / "frames" / "tower0" / "render.log"]

    # The card carries the solved tracks and capture instants -- the SAME
    # block the CLI's --card writes -- over the whole 3 s run.
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert [b["camera_id"] for b in card["cameras"]] == ["camera0", "tower0"]
    assert len(card["cameras"][0]["capture_times_s"]) == 4
    assert card["duration_s"] == 3.0
    manifest = json.loads(
        (out / "capture" / "capture_manifest.json").read_text(encoding="utf-8"))
    assert [r["t_s"] for r in manifest["frames"] if r["camera_id"] == "camera0"] \
        == card["cameras"][0]["capture_times_s"]

    # Exactly the scheduled PNGs, named by manifest index, per camera.
    for camera_id in ("camera0", "tower0"):
        names = sorted(p.name for p in
                       (out / "capture" / "frames" / camera_id).glob("*.png"))
        assert names == ["0000.png", "0001.png", "0002.png", "0003.png"]

    # The counts say what was rendered, and engine parity graded it.
    assert run.capture["scheduled"] == 8
    assert run.capture["rendered"] == 8 and run.capture["verified"] == 8
    assert [(c["camera_id"], c["scheduled"], c["rendered"], c["verified"])
            for c in run.capture["cameras"]] == [
        ("camera0", 4, 4, 4), ("tower0", 4, 4, 4)]
    engine = [c for c in run.capture["verification"]["checks"]
              if c["name"] == "engine_parity"][0]
    assert engine["ok"] is True, engine["detail"]
    assert run.capture["verification"]["ok"] is True

    # The clip is a by-product of camera 0's frames at their instants.
    assert engine_stubs["encoded"][0]["frames_dir"] == \
        out / "capture" / "frames" / "camera0"
    assert engine_stubs["encoded"][0]["times"] == \
        card["cameras"][0]["capture_times_s"]
    assert run.clip == str(out / "clip.mp4")

    # Provenance records the choice; the status line names the product.
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"] == "frames"
    assert provenance["window_s"] == 3.0
    assert run.render == "frames"
    assert "8 frames across 2 camera(s) rendered" in run.detail
    assert "8 verified" in run.detail and "by-product of 'camera0'" in run.detail

    # The frames are listed and downloadable as their own artefact class.
    files = capture_module.run_artifacts(out)
    frames_entry = next(f for f in files if f["name"] == "capture/frames/camera0")
    assert frames_entry["count"] == 4 and "rendered" in frames_entry["note"]
    assert "capture/frames/tower0/render.json" in [f["name"] for f in files]


def test_a_failed_engine_pass_fails_the_run_by_name(engine_stubs):
    """A pass that returns without render.json fails the run as
    render.frames, and nothing presents the previews as frames."""
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls, fail_for=1)))
    manager = engine_stubs["manager"]
    run = RunState(run_id="failedpass")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "failed"
    assert "[render.frames]" in run.detail and "tower0" in run.detail
    assert "no render.json" in run.detail
    # Camera 0 rendered, camera 1 did not: counted honestly, never dressed
    # up as a frame set, and the verifier says why.
    counts = {c["camera_id"]: (c["rendered"], c["verified"])
              for c in run.capture["cameras"]}
    assert counts == {"camera0": (4, 4), "tower0": (0, 0)}
    engine = [c for c in run.capture["verification"]["checks"]
              if c["name"] == "engine_parity"][0]
    assert engine["ok"] is False
    assert run.clip is None
    assert not engine_stubs["encoded"]


def test_a_short_engine_pass_fails_the_run_by_name(engine_stubs):
    """render.json reporting 3 of 4 scheduled frames is a failed pass,
    named, not a frame set with a frame missing."""
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls, short_for=0)))
    manager = engine_stubs["manager"]
    run = RunState(run_id="shortpass")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "failed"
    assert "[render.frames]" in run.detail
    assert "captured 3 of 4 scheduled" in run.detail
    assert len(calls) == 1                     # stopped at the first bad pass
    assert run.capture["cameras"][0]["rendered"] == 3
    assert run.capture["cameras"][0]["verified"] == 3


def test_the_clip_flow_reports_zero_rendered(engine_stubs):
    """Clip only: the SAME capture summary, with rendered 0 and the words
    saying so -- today's behaviour, now named."""
    from webapp.runs import RunManager, RunState

    def clip_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera_flags=None, camera_index=None,
                    log=None):
        assert camera_index is None and camera_flags is not None
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(clip_render))
    manager = engine_stubs["manager"]
    run = RunState(run_id="cliprun")
    manager._render_flow(run, two_camera_spec(), provenance={}, render="clip")
    assert run.status == "done", run.detail
    out = manager.out_root / "cliprun"
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    assert "cameras" not in card                # the preset pass, unchanged
    assert card["duration_s"] == 3.0
    assert run.capture["rendered"] == 0 and run.capture["verified"] == 0
    assert run.capture["scheduled"] == 8
    assert run.detail.startswith("clip only: 8 frames scheduled, 0 rendered")
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"] == "clip"


def test_a_headless_run_reports_zero_rendered(captured):
    """The count contract on the headless path: scheduled 4, rendered 0,
    verified 0, and 'no pixels' in the status -- a preview is not a
    frame."""
    run_id, state = captured
    capture = state["capture"]
    assert capture["scheduled"] == 4
    assert capture["rendered"] == 0 and capture["verified"] == 0
    assert capture["cameras"][0]["rendered"] == 0
    assert state["render"] == "none"
    assert "no pixels" in state["detail"] and "4 previews" in state["detail"]
    provenance = json.loads(
        (manager.out_root / run_id / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"] == "none"


def test_a_pass_missing_a_png_fails_the_run_by_name(engine_stubs):
    """render.json says 4 of 4, but a PNG named by index is not on disk:
    the file is the frame, so the pass is short and the run fails."""
    from webapp.runs import RunManager, RunState

    calls = []
    honest = honest_engine(calls)

    def lossy(card, frames, *args, **kwargs):
        ok = honest(card, frames, *args, **kwargs)
        (Path(frames) / "0002.png").unlink()
        return ok

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(lossy))
    manager = engine_stubs["manager"]
    run = RunState(run_id="lossypass")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "failed"
    assert "[render.frames]" in run.detail
    assert "1 of 4 scheduled PNGs are missing" in run.detail
    assert "0002.png" in run.detail
    assert run.capture["cameras"][0]["rendered"] == 3


def test_a_dishonest_engine_pass_fails_engine_parity(engine_stubs):
    """The counts are right and every PNG exists, but the engine placed
    the camera 20 cm off the solved pose: engine parity FAILS the run by
    name. Frames whose recorded geometry is quietly wrong are not a
    frame set."""
    from webapp.runs import RunManager, RunState

    calls = []
    honest = honest_engine(calls)

    def drifting(card, frames, *args, **kwargs):
        ok = honest(card, frames, *args, **kwargs)
        report = Path(frames) / "render.json"
        render = json.loads(report.read_text(encoding="utf-8"))
        render["frame_records"][1]["camera_applied_east_m"] += 0.20
        report.write_text(json.dumps(render), encoding="utf-8")
        return ok

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(drifting))
    manager = engine_stubs["manager"]
    run = RunState(run_id="driftpass")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "failed"
    assert "[render.frames] engine parity" in run.detail
    assert "0.200 m" in run.detail
    # Rendered, yes; verified, not those frames -- and the page shows it.
    assert run.capture["rendered"] == 8
    assert run.capture["verified"] == 6


def test_the_by_product_clip_shows_each_frame_at_its_instant():
    """The concat playlist the by-product clip is encoded from: frame i
    is held from its instant until the next, the last for the stated
    hold, listed twice so the demuxer applies its duration. Clip time
    is simulation time -- no render fps anywhere."""
    from core.capture.render_pass import concat_playlist

    text = concat_playlist([0.0, 0.5, 1.5, 3.0],
                           ["0000.png", "0001.png", "0002.png", "0003.png"],
                           last_hold_s=1.0)
    lines = text.strip().splitlines()
    assert lines[0] == "ffconcat version 1.0"
    assert lines[1:] == [
        "file '0000.png'", "duration 0.500000",
        "file '0001.png'", "duration 1.000000",
        "file '0002.png'", "duration 1.500000",
        "file '0003.png'", "duration 1.000000",
        "file '0003.png'"]
    with pytest.raises(ValueError):
        concat_playlist([0.0, 1.0, 1.0], ["a", "b", "c"])
    with pytest.raises(ValueError):
        concat_playlist([0.0, 1.0], ["a"])


# -- the render choice: one form, three words, one endpoint ---------------

STATIC_INDEX = Path(runs_module.REPO) / "webapp" / "static" / "index.html"


def test_the_run_form_offers_the_three_render_words():
    """The choice is visible before the run starts, in exactly these
    words, and the page reads which are available (and why not) from
    /status rather than deciding for itself."""
    page = STATIC_INDEX.read_text(encoding="utf-8")
    assert 'id="render"' in page
    for word, value in (("Render frames and clip", "frames"),
                        ("Clip only", "clip"), ("Headless", "none")):
        assert f'<option value="{value}">{word}</option>' in page, word
    assert "render_unavailable_reason" in page
    assert "render_default" in page
    assert 'render: $("render").value' in page


def test_status_states_the_render_choices_and_the_reason(client):
    status = client.get("/status").json()
    assert isinstance(status["render_available"], bool)
    choices = {c["value"]: c for c in status["render_choices"]}
    assert [c["label"] for c in status["render_choices"]] == [
        "Render frames and clip", "Clip only", "Headless"]
    assert choices["none"]["available"] is True
    if status["render_available"]:
        assert status["render_unavailable_reason"] is None
        assert status["render_default"] == "frames"
        assert all(c["available"] for c in choices.values())
    else:
        assert status["render_unavailable_reason"]
        assert status["render_default"] == "none"
        for word in ("frames", "clip"):
            assert choices[word]["available"] is False
            assert choices[word]["reason"] == status["render_unavailable_reason"]


def test_an_engine_choice_is_refused_by_name_with_the_reason(client,
                                                            monkeypatch):
    """render=frames or clip on a machine without the engine: 409
    ue.platform carrying the machine's reason, and no run is started.
    The choice never degrades to headless behind the user's back."""
    import core.util.platform as plat
    import webapp.server as server_module

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this machine: set UE_ROOT")
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    spec = compile_prompt(DEMO)
    for word in ("frames", "clip"):
        reply = client.post("/run", json={"spec": spec.to_dict(),
                                          "render": word})
        assert reply.status_code == 409, word
        body = reply.json()
        assert body["constraint"] == "ue.platform"
        assert body["reason"] == "no engine on this machine: set UE_ROOT"
        assert body["render"] == word
    assert client.get("/status").json()["busy"] is False
    # A word outside the three is a schema error, not a guess.
    assert client.post("/run", json={"spec": spec.to_dict(),
                                     "render": "video"}).status_code == 422


def test_render_none_on_run_is_the_headless_flow(client):
    """POST /run with render=none is the same headless run /capture
    starts: no platform gate, provenance render 'none', the status line
    says no pixels."""
    spec = compile_prompt(DEMO)
    reply = client.post("/run", json={"spec": spec.to_dict(),
                                      "render": "none"})
    assert reply.status_code == 200, reply.json()
    assert reply.json()["render"] == "none"
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "done", state["detail"]
    assert state["render"] == "none"
    assert "no pixels" in state["detail"]
    provenance = json.loads(
        (manager.out_root / reply.json()["run_id"] / "provenance.json")
        .read_text(encoding="utf-8"))
    assert provenance["render"] == "none"


@pytest.fixture()
def engine_client(client, engine_stubs, monkeypatch):
    """The HTTP client with the platform gate held open and the engine
    stubbed, so the three choices can be exercised end to end through
    POST /run on a machine with no engine."""
    import core.util.platform as plat
    import webapp.server as server_module

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_unavailable_reason", lambda: None)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    monkeypatch.setattr(runs_module, "editor_running", lambda: False)
    return client


def test_render_frames_on_run_records_the_choice_and_names_the_product(
        engine_client, engine_stubs):
    from webapp.runs import RunManager

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    spec = two_camera_spec()
    reply = engine_client.post("/run", json={"spec": spec.to_dict(),
                                             "render": "frames"})
    assert reply.status_code == 200, reply.json()
    assert reply.json()["render"] == "frames"
    run_id = reply.json()["run_id"]
    state = finished(engine_client, run_id)
    assert state["status"] == "done", state["detail"]
    assert state["render"] == "frames"
    assert [c["camera_index"] for c in calls] == [0, 1]
    assert "8 frames across 2 camera(s) rendered" in state["detail"]
    assert state["capture"]["rendered"] == 8
    assert state["clip"] is not None
    provenance = json.loads(
        (manager.out_root / run_id / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render"] == "frames"
    # The frame set is served: every PNG the run listed downloads.
    files = engine_client.get(f"/runs/{run_id}/files").json()["files"]
    frames = [f for f in files if f["name"].startswith("capture/frames/")
              and "images" in f]
    assert [f["count"] for f in frames] == [4, 4]
    got = engine_client.get(f"/runs/{run_id}/file/{frames[0]['images'][0]}")
    assert got.status_code == 200 and got.headers["content-type"] == "image/png"


def test_render_clip_on_run_is_todays_flow(engine_client, engine_stubs):
    from webapp.runs import RunManager

    def clip_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera_flags=None, camera_index=None,
                    log=None):
        assert camera_index is None
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(clip_render))
    spec = compile_prompt(DEMO)
    # Omitting the field is the endpoint's historic meaning: clip.
    reply = engine_client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    assert reply.json()["render"] == "clip"
    state = finished(engine_client, reply.json()["run_id"])
    assert state["status"] == "done", state["detail"]
    assert state["render"] == "clip"
    assert state["detail"].startswith("clip only: 4 frames scheduled, 0 rendered")
    provenance = json.loads(
        (manager.out_root / reply.json()["run_id"] / "provenance.json")
        .read_text(encoding="utf-8"))
    assert provenance["render"] == "clip"
