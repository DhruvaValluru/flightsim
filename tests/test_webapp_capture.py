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

import io
import json
import subprocess
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
                     "flight_fidelity", "schedule_fidelity", "pose_fidelity",
                     "aim_fidelity", "engine_parity"]
    # No engine on this machine: the engine-parity check is AWAITING in
    # those words -- not passed (nothing was rendered), not failed (the
    # run never claimed pixels), and not counted among the passed.
    engine = verification["checks"][-1]
    assert engine["ok"] is None and engine["status"] == "AWAITING"
    assert "awaiting engine frames" in engine["detail"]
    assert verification["awaiting"] == ["engine_parity"]
    # One camera: cross-view consistency had nothing to grade and is
    # SKIPPED with its reason -- counted in neither passed nor ran, so
    # the tally is 8/8, never a 9/9 the check did not earn. The flight,
    # schedule, pose and aim checks RAN: capture/ carries telemetry.json
    # and scenario.yaml beside the manifest.
    assert verification["passed"] == 8 and verification["ran"] == 8
    assert verification["skipped"] == [
        {"name": "cross_view_consistency", "reason": "single camera"}]
    cross = verification["checks"][3]
    assert cross["ok"] is None and cross["status"] == "SKIPPED"
    assert "8/8 checks" in verification["summary"]
    by_name = {c["name"]: c for c in verification["checks"]}
    assert by_name["flight_fidelity"]["ok"] is True
    assert by_name["flight_fidelity"]["data"]["digests_equal"] is True
    assert by_name["schedule_fidelity"]["ok"] is True
    assert by_name["pose_fidelity"]["ok"] is True
    assert by_name["pose_fidelity"]["data"]["digests_equal"] == {"camera0": True}
    assert by_name["aim_fidelity"]["ok"] is True
    assert by_name["aim_fidelity"]["data"]["cameras"]["camera0"]["kind"] == \
        "aircraft-lagged"

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

def test_the_page_run_routes_jsbsim_to_a_stamped_log(client, capfd):
    """A page run constructs every model under the run's own sink: the
    banner JSBSim prints from C++ on every construction lands in
    <run>/jsbsim.log -- one '# load N:' stamp naming the model and the
    caller before each -- and nothing of it reaches the server's
    console (fd 1, read here with capfd). The run is started through
    the manager directly, so only the run's own loads are in the
    reading (the request handlers' planning has its own sink since
    round 3: test_the_request_handlers_route_their_planning below)."""
    import re

    spec = compile_prompt(DEMO)
    capfd.readouterr()                          # the compile's own loads
    started = manager.start_capture(spec, provenance={"prompt": DEMO})
    run_id = started["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "done", state
    console = capfd.readouterr().out
    assert "JSBSim startup beginning" not in console
    assert "JSBSim Flight Dynamics Model" not in console
    log = manager.out_root / run_id / "jsbsim.log"
    assert log.is_file()
    assert not (manager.out_root / run_id / "capture" / "jsbsim.log").exists()
    text = log.read_text(encoding="utf-8")
    banners = text.count("JSBSim startup beginning")
    stamps = re.findall(r"^# load (\d+): (\S+) called from ([\w.]+)$", text,
                        re.M)
    assert banners >= 2 and len(stamps) == banners
    assert [int(n) for n, _, _ in stamps] == list(range(1, banners + 1))
    assert all(label.startswith("FlightDynamics(") for _, label, _ in stamps)
    assert all(caller.startswith("core.") or caller.startswith("webapp.")
               for _, _, caller in stamps)
    # The capture flight's loads are counted from the run's continuous
    # numbering and the status lines say where they went.
    capture_loads = state["capture"]["jsbsim_model_loads"]
    assert state["capture"]["jsbsim_log"] == "jsbsim.log"
    assert 1 <= capture_loads < banners
    lines = [e["detail"] for e in state["events"]]
    assert any(line.startswith(f"JSBSim output: jsbsim.log ({capture_loads} "
                               f"model loads routed there for the capture "
                               f"flight") for line in lines), lines
    assert any(line.startswith("JSBSim output: jsbsim.log (") and
               "for the closure flight" in line for line in lines), lines
    # The page lists the log with a note and serves it.
    files = client.get(f"/runs/{run_id}/files").json()["files"]
    entry = next(f for f in files if f["name"] == "jsbsim.log")
    assert "stamp per model construction" in entry["note"]
    assert client.get(f"/runs/{run_id}/file/jsbsim.log").status_code == 200


def test_the_request_handlers_route_their_planning_to_the_server_log(
        client, capfd):
    """/compile, /run and /capture construct models BEFORE a run
    directory exists (plan_flyable_defaults, the envelope measurement,
    validate). Their banners go to the server-level planning log,
    <runs root>/jsbsim.log, stamped and counted -- /status names the
    log and the count -- and nothing reaches the server console (fd 1,
    read with capfd), while the run that follows keeps its own log."""
    import re

    log = manager.out_root / "jsbsim.log"
    assert not log.exists()
    # The count in /status is since this PROCESS started (the manager is
    # one per server; the test client shares it across tests), so the
    # comparison is a delta against the fresh log.
    before = client.get("/status").json()["planning_model_loads"]
    capfd.readouterr()
    reply = client.post("/compile", json={"prompt": DEMO, "compiler": "regex"})
    assert reply.status_code == 200, reply.json()
    console = capfd.readouterr()
    assert "JSBSim startup beginning" not in console.out + console.err
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    compile_banners = text.count("JSBSim startup beginning")
    assert compile_banners >= 1
    # Every construction is stamped and counted; JSBSim prints its
    # banner on some of them (measured: 7 stamped loads, 3 banners on
    # this compile), so the count is the stamps', never the banners'.
    stamps = re.findall(r"^# load (\d+): (\S+) called from ([\w.]+)$", text,
                        re.M)
    assert len(stamps) >= compile_banners
    status = client.get("/status").json()
    assert status["planning_log"] == str(log)
    assert status["planning_model_loads"] - before == len(stamps)
    assert all(caller.startswith(("core.", "webapp.")) for _, _, caller in stamps)
    # /capture: the same planning, then the run in its own log.
    spec = compile_prompt(DEMO).to_dict()
    capfd.readouterr()
    reply = client.post("/capture", json={"spec": spec})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "done", state
    console = capfd.readouterr()
    assert "JSBSim startup beginning" not in console.out + console.err
    assert "JSBSim Flight Dynamics Model" not in console.out + console.err
    text = log.read_text(encoding="utf-8")
    planning_banners = text.count("JSBSim startup beginning")
    assert planning_banners > compile_banners
    planning_stamps = len(re.findall(r"^# load \d+: ", text, re.M))
    assert client.get("/status").json()["planning_model_loads"] - before == \
        planning_stamps > len(stamps)
    run_log = manager.out_root / run_id / "jsbsim.log"
    assert run_log.is_file()
    assert run_log.read_text(encoding="utf-8").count(
        "JSBSim startup beginning") >= 2
    # The run's stamps number from 1 in ITS log: the planning sink and
    # the run sink are different slots (per thread), not one shared one.
    assert re.search(r"^# load 1: ", run_log.read_text(encoding="utf-8"),
                     re.M)
    # /run with render none plans the same way.
    capfd.readouterr()
    reply = client.post("/run", json={"spec": spec, "render": "none"})
    assert reply.status_code == 200, reply.json()
    finished(client, reply.json()["run_id"])
    console = capfd.readouterr()
    assert "JSBSim startup beginning" not in console.out + console.err
    assert log.read_text(encoding="utf-8").count(
        "JSBSim startup beginning") > planning_banners


def test_the_console_sink_is_one_slot_per_thread(tmp_path):
    """A request handler entering the planning sink while the run
    thread is inside the run's own must neither steal that slot nor
    lose its own when the run's block exits: the sink is per thread."""
    import threading

    from core.fdm.console import active_console, jsbsim_console

    seen = {}
    gate_in = threading.Event()
    gate_out = threading.Event()

    def runner():
        with jsbsim_console(tmp_path / "run.log") as sink:
            seen["run_inside"] = active_console() is sink
            gate_in.set()
            gate_out.wait(5.0)
            seen["run_still"] = active_console() is sink
        seen["run_after"] = active_console()

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    assert gate_in.wait(5.0)
    assert active_console() is None          # this thread has no sink
    with jsbsim_console(tmp_path / "planning.log") as planning:
        assert active_console() is planning
        gate_out.set()
        thread.join(5.0)
        assert active_console() is planning  # the run's exit did not clear it
    assert active_console() is None
    assert seen == {"run_inside": True, "run_still": True, "run_after": None}


def test_a_direct_capture_run_routes_jsbsim_to_its_own_log(tmp_path, capfd):
    """capture_run called with no sink active (a script, a test) opens
    capture/jsbsim.log for itself: the same stamps, nothing on fd 1."""
    import re

    spec = compile_prompt(DEMO)
    flat = {"key": "flat", "kind": "flat", "terrain": None, "imagery": None}
    capfd.readouterr()
    lines = []
    outcome = capture_module.capture_run(spec, tmp_path, flat, lines.append)
    console = capfd.readouterr().out
    assert "JSBSim startup beginning" not in console
    log = tmp_path / "capture" / "jsbsim.log"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    banners = text.count("JSBSim startup beginning")
    stamps = re.findall(r"^# load (\d+): ", text, re.M)
    assert banners >= 1 and len(stamps) == banners
    assert outcome.summary["jsbsim_log"] == "capture/jsbsim.log"
    assert outcome.summary["jsbsim_model_loads"] == banners
    assert any(line.startswith(f"JSBSim output: capture/jsbsim.log "
                               f"({banners} model loads routed there")
               for line in lines), lines
    files = capture_module.run_artifacts(tmp_path)
    entry = next(f for f in files if f["name"] == "capture/jsbsim.log")
    assert "direct capture" in entry["note"]


def test_every_artefact_is_listed_and_downloadable(captured, client):
    run_id, _ = captured
    files = client.get(f"/runs/{run_id}/files").json()["files"]
    names = [f["name"] for f in files]
    for expected in ("provenance.json", "scenario.yaml", "jsbsim.log",
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


def manifest_beside(card):
    """The capture manifest a run wrote beside its card: out/capture/
    capture_manifest.json (the webapp) or out/capture_manifest.json (the
    CLI). An honest engine draws the aircraft where its own FDM is; for
    a stub that is where the manifest says it is."""
    card = Path(card)
    for candidate in (card.parent / "capture" / "capture_manifest.json",
                      card.parent / "capture_manifest.json"):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no capture manifest beside {card}")


def manifest_record(manifest, camera_id, index):
    return next(r for r in manifest["frames"]
                if r["camera_id"] == camera_id and r["index"] == index)


def drawn_aircraft(manifest, camera_id, index):
    """The ``aircraft_applied_*`` fields of an honest engine record."""
    record = manifest_record(manifest, camera_id, index)
    return {"aircraft_applied_north_m": record["aircraft"]["north_m"],
            "aircraft_applied_east_m": record["aircraft"]["east_m"],
            "aircraft_applied_alt_m": record["aircraft"]["alt_m"]}


def honest_engine(calls, short_for=None, fail_for=None):
    """A _render stub that behaves like the consume-poses pass: the
    applied pose is the solved one, the aircraft is DRAWN at the
    manifest's labelled pixel (tests.test_camera_verify.honest_frame)
    and the engine's own measurement of that pixel is recorded."""
    from core.capture.verify import labelled_pixel

    from tests.test_camera_verify import engine_pixel_fields, honest_frame

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
        manifest = manifest_beside(card)
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
                "t_pose_s": t,
                "camera_applied_north_m": poses["north_m"][k],
                "camera_applied_east_m": poses["east_m"][k],
                "camera_applied_alt_m": poses["alt_m"][k],
                "camera_applied_yaw_deg": poses["yaw_deg"][k],
                "camera_applied_pitch_deg": poses["pitch_deg"][k],
                "camera_applied_roll_deg": poses["roll_deg"][k],
                **drawn_aircraft(manifest, block["camera_id"], index),
                **engine_pixel_fields(
                    manifest_record(manifest, block["camera_id"], index)),
            })
            u, v, depth = labelled_pixel(
                manifest_record(manifest, block["camera_id"], index))
            honest_frame(frames / f"{index:04d}.png", block["width_px"],
                         block["height_px"],
                         pixel=(u, v) if depth > 0 else None)
        (frames / "render.json").write_text(json.dumps({
            "host": "unreal", "camera_consume_poses": True,
            "camera_index": camera_index,
            "width": block["width_px"], "height": block["height_px"],
            "step_s": 1.0 / 120.0,
            "frames_scheduled": len(block["capture_times_s"]),
            "frames_captured": len(times),
            # The pass stops after the last scheduled instant.
            "steps_taken": int(round(times[-1] * 120.0)),
            "stepped_s": times[-1],
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


def test_the_frames_run_records_its_passes_and_the_clip(engine_stubs):
    """What each engine pass cost (it stops after the last scheduled
    instant: steps_taken / stepped_s from render.json) is said per pass
    in the status and recorded in provenance as render_passes, and the
    by-product clip's expected length is stated before encoding and
    recorded with whether it encoded -- also when it did not."""
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    manager = engine_stubs["manager"]
    run = RunState(run_id="passes")
    lines = []
    original_push = run.push

    def push(status, detail):
        lines.append((status, detail))
        original_push(status, detail)

    run.push = push
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "done", run.detail
    out = manager.out_root / "passes"
    card = json.loads((out / "card.json").read_text(encoding="utf-8"))
    last = card["cameras"][0]["capture_times_s"][-1]
    provenance = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["render_passes"] == [
        {"camera_id": "camera0", "camera_index": 0, "scheduled": 4,
         "rendered": 4, "steps_taken": int(round(last * 120.0)),
         "stepped_s": last},
        {"camera_id": "tower0", "camera_index": 1, "scheduled": 4,
         "rendered": 4, "steps_taken": int(round(last * 120.0)),
         "stepped_s": last}]
    assert provenance["clip_encoded"] is True
    assert provenance["clip_seconds"] == pytest.approx(last + 1.0)
    assert run.capture["render_passes"] == provenance["render_passes"]
    assert run.capture["clip"] == {"encoded": True,
                                   "seconds": pytest.approx(last + 1.0),
                                   "by_product_of": "camera0"}
    rendering = [d for s, d in lines if s == "rendering"]
    assert any(d.startswith("camera 'camera0': 4 of 4 scheduled frames "
                            "rendered (engine stepped ") for d in rendering)
    assert any(f"in {int(round(last * 120.0))} steps)" in d for d in rendering)
    encoding = [d for s, d in lines if s == "encoding"]
    assert f"{last + 1.0:.3f} s of clip = black to t=" in encoding[0]
    assert "a 1 s hold" in encoding[0]
    assert provenance["render"] == "frames"          # the earlier fields stay

    # The clip did not come out: recorded as such, the expected length
    # still stated, the run still done on its frames.
    def no_ffmpeg(ffmpeg, frames_dir, times, clip, lead_in_s=None):
        raise RuntimeError("ffmpeg.missing: no ffmpeg found (test)")

    engine_stubs["monkeypatch"].setattr(runs_module, "encode_scheduled_clip",
                                        no_ffmpeg)
    run = RunState(run_id="noclip")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "done", run.detail
    assert run.clip is None and run.detail.endswith("; no clip")
    provenance = json.loads((manager.out_root / "noclip" / "provenance.json")
                            .read_text(encoding="utf-8"))
    assert provenance["clip_encoded"] is False
    assert provenance["clip_seconds"] == pytest.approx(last + 1.0)
    assert len(provenance["render_passes"]) == 2


def test_the_by_product_clip_s_ffmpeg_command_is_pinned(tmp_path, monkeypatch):
    """The exact argv the by-product clip is encoded with, the playlist
    it reads (a black lead-in PNG at the frames' size listed first for
    the time to the first instant, each frame held to the next, the
    last held and repeated to terminate) and the clip's expected
    length. Nothing here needs ffmpeg: subprocess.run is stubbed and the
    argv is the claim."""
    from PIL import Image

    from core.capture import render_pass
    from core.capture.render_pass import (
        CLIP_LEAD_NAME, encode_scheduled_clip, scheduled_clip_seconds,
    )

    frames_dir = tmp_path / "frames" / "cam"
    frames_dir.mkdir(parents=True)
    for index in range(3):
        Image.new("RGB", (64, 36), (30, 30, 30)).save(
            frames_dir / f"{index:04d}.png")
    ran = []

    def fake_run(command, capture_output=False, **kwargs):
        ran.append(list(command))
        Path(command[-1]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render_pass.subprocess, "run", fake_run)
    clip = tmp_path / "clip.mp4"
    assert encode_scheduled_clip(Path("ffmpeg"), frames_dir, [0.5, 1.0, 2.0],
                                 clip) is True
    playlist = frames_dir / "clip_playlist.ffconcat"
    assert ran == [[
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(playlist),
        "-vsync", "vfr", "-c:v", "libx264", "-preset", "medium",
        "-crf", "19", "-pix_fmt", "yuv420p", str(clip)]]
    assert playlist.read_text(encoding="utf-8").splitlines() == [
        "ffconcat version 1.0",
        f"file '../{CLIP_LEAD_NAME}'", "duration 0.500000",
        "file '0000.png'", "duration 0.500000",
        "file '0001.png'", "duration 1.000000",
        "file '0002.png'", "duration 1.000000",
        "file '0002.png'"]
    lead = tmp_path / "frames" / CLIP_LEAD_NAME
    with Image.open(lead) as image:
        assert image.size == (64, 36)
        assert image.getpixel((0, 0)) == (0, 0, 0)
    # The lead-in never lands among a camera's rendered frames.
    assert sorted(p.name for p in frames_dir.glob("*.png")) == [
        "0000.png", "0001.png", "0002.png"]
    # Expected length: lead (first instant) + span + the 1 s hold.
    assert scheduled_clip_seconds([0.5, 1.0, 2.0]) == pytest.approx(3.0)
    assert scheduled_clip_seconds([0.5, 1.0, 2.0], lead_in_s=0.0) == \
        pytest.approx(2.5)
    # No lead-in when the first instant is t=0: no lead entry, no PNG.
    lead.unlink()
    assert encode_scheduled_clip(Path("ffmpeg"), frames_dir, [0.0, 1.0, 2.0],
                                 clip) is True
    assert playlist.read_text(encoding="utf-8").splitlines()[1] == \
        "file '0000.png'"
    assert not lead.exists()


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
    /status rather than deciding for itself. Headless is the option
    marked selected in the served markup: the safe initial state."""
    page = STATIC_INDEX.read_text(encoding="utf-8")
    assert 'id="render"' in page
    for word, value, markup in (
            ("Render frames and clip", "frames",
             '<option value="frames">Render frames and clip</option>'),
            ("Clip only", "clip", '<option value="clip">Clip only</option>'),
            ("Headless", "none",
             '<option value="none" selected>Headless</option>')):
        assert markup in page, word
    assert "render_unavailable_reason" in page
    assert "render_default" in page
    assert 'render: $("render").value' in page


def test_the_run_form_starts_disabled_on_headless_until_status_answers():
    """The 'hidden default' the bar names: before /status answers (and
    for good, if it never does) the served page must not offer an
    engine option as the default. Pinned at the source: the select
    ships disabled with Headless selected; applyRenderChoices reads the
    default from render_default ONLY, enables the control only once it
    has that word, disables an unavailable option with the reason, and
    the unreachable-server branch leaves the control disabled and says
    so. No second spelling of the default rule exists in the page."""
    page = STATIC_INDEX.read_text(encoding="utf-8")
    assert '<select id="render" disabled>' in page
    assert '<option value="none" selected>Headless</option>' in page
    assert ('<span id="renderNote" class="dim">waiting for /status (Headless '
            'until the server says what this machine supports)</span>') in page
    assert 'if (status.render_default) select.value = status.render_default;' in page
    assert 'select.disabled = !status.render_default;' in page
    assert 'option.disabled = !choice.available;' in page
    assert 'unavailable: ${choice.reason}' in page
    assert 'option.title = choice.available ? "" : choice.reason;' in page
    assert ('"render choice unavailable: server unreachable (Headless is the "'
            in page)
    # One assignment of the select's value in the whole page: the server's
    # render_default, never a page-side guess.
    assert page.count("select.value = ") == 1
    assert page.count('.value = "frames"') == 0


APPLY_RENDER_CHOICES_HARNESS = """
const options = [
  {value: "frames", textContent: "Render frames and clip", disabled: false, title: ""},
  {value: "clip", textContent: "Clip only", disabled: false, title: ""},
  {value: "none", textContent: "Headless", disabled: false, title: ""},
];
const select = {options, disabled: true, _value: "none",
                get value() { return this._value; },
                set value(v) { this._value = v; }};
const note = {textContent: "waiting for /status"};
const $ = id => ({render: select, renderNote: note})[id];
%s
applyRenderChoices(JSON.parse(process.argv[2]));
console.log(JSON.stringify({
  disabled: select.disabled, value: select.value, note: note.textContent,
  options: options.map(o => ({value: o.value, disabled: o.disabled,
                              text: o.textContent, title: o.title})),
}));
"""


def apply_render_choices(tmp_path, payload):
    """Run the page's applyRenderChoices, verbatim from the served HTML,
    under node against a minimal DOM shim, and return what it did."""
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the string-level test pins the "
                    "source instead")
    page = STATIC_INDEX.read_text(encoding="utf-8")
    source = re.search(r"function applyRenderChoices\(status\) \{.*?\n\}\n",
                       page, re.S).group(0)
    harness = tmp_path / "apply_render_choices.js"
    harness.write_text(APPLY_RENDER_CHOICES_HARNESS % source, encoding="utf-8")
    proc = subprocess.run([node, str(harness), json.dumps(payload)],
                          capture_output=True, text=True, check=True, encoding="utf-8")
    return json.loads(proc.stdout)


def test_apply_render_choices_honours_the_status_payload(client, tmp_path):
    """The page's own JS, driven by the real /status payload of this
    machine and by a mac-like one: an unavailable option is disabled
    with the reason in its label and title, the default is the server's
    render_default, the control is enabled only then, and a payload
    without render_default leaves it disabled on Headless."""
    status = client.get("/status").json()
    result = apply_render_choices(tmp_path, status)
    assert result["disabled"] is False
    assert result["value"] == status["render_default"]
    by_value = {o["value"]: o for o in result["options"]}
    assert by_value["none"]["disabled"] is False
    if status["render_available"]:
        assert result["value"] == "frames" and result["note"] == ""
        assert not any(o["disabled"] for o in result["options"])
    else:
        reason = status["render_unavailable_reason"]
        assert result["value"] == "none"
        for word, label in (("frames", "Render frames and clip"),
                            ("clip", "Clip only")):
            assert by_value[word]["disabled"] is True
            assert by_value[word]["text"] == f"{label} \u2014 unavailable: {reason}"
            assert by_value[word]["title"] == reason
        assert result["note"] == f"engine options disabled: {reason}"

    engine = {"render_available": True, "render_unavailable_reason": None,
              "render_default": "frames",
              "render_choices": [{"value": w, "label": l, "available": True,
                                  "reason": None}
                                 for w, l in (("frames", "Render frames and clip"),
                                              ("clip", "Clip only"),
                                              ("none", "Headless"))]}
    result = apply_render_choices(tmp_path, engine)
    assert result["disabled"] is False and result["value"] == "frames"
    assert result["note"] == ""
    assert not any(o["disabled"] for o in result["options"])

    # No render_default (a server that never said): disabled, Headless.
    result = apply_render_choices(tmp_path, {})
    assert result["disabled"] is True and result["value"] == "none"
    assert result["note"].startswith("render choice unavailable")


def test_status_default_is_the_cli_s_own_rule(client, monkeypatch):
    """/status's render_default is render_choice_default() -- the one rule
    the CLI uses -- under both gate states, not a second spelling."""
    import core.util.platform as plat
    from core.capture.render_pass import render_choice_default

    for available in (False, True):
        monkeypatch.setattr(plat, "ue_available", lambda a=available: a)
        monkeypatch.setattr(plat, "ue_unavailable_reason",
                            lambda a=available: None if a else "no engine (test)")
        status = client.get("/status").json()
        assert status["render_default"] == render_choice_default()
        assert status["render_default"] == ("frames" if available else "none")
        assert status["render_available"] is available


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


def test_a_turbulent_spec_is_refused_frames_by_name(engine_client,
                                                     engine_stubs):
    """Host parity is measured and REFUSED for turbulence realisations
    (docs/VALIDITY.md): the engine's aircraft could not be labelled from
    the manifest, so render=frames on a turbulent spec is 409
    render.host_parity BEFORE any run -- never rendered and then failed.
    Clip only keeps its visual-only label and stays available."""
    from webapp.runs import RunManager

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    spec = two_camera_spec()
    spec.set("turbulence", "moderate", frm="test: a turbulence realisation")
    reply = engine_client.post("/run", json={"spec": spec.to_dict(),
                                             "render": "frames"})
    assert reply.status_code == 409, reply.json()
    body = reply.json()
    assert body["constraint"] == "render.host_parity"
    assert "turbulence 'moderate'" in body["refused"]
    assert "host parity" in body["refused"] and "Clip only" in body["refused"]
    assert body["render"] == "frames"
    assert calls == []
    assert engine_client.get("/status").json()["busy"] is False
    # The pure rule, both cases the flow can meet.
    from core.capture.render_pass import frames_host_parity_refusal

    calm = two_camera_spec()
    assert frames_host_parity_refusal(calm) is None
    assert "lee-rotor" in frames_host_parity_refusal(calm, rotor_attached=True)
    assert "turbulence 'moderate'" in frames_host_parity_refusal(spec)


def test_a_rotor_attached_frames_run_fails_by_name(engine_stubs):
    """The lee rotor is decided inside the flow (terrain scene, wind, and
    the pre-flight says it acts): a frames run that would carry it fails
    [render.host_parity] before any capture or editor time. The rule is
    stubbed to say the rotor is attached; the flow must honour it."""
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    seen = []

    def rotor_rule(spec, rotor_attached=False):
        seen.append(rotor_attached)
        return "stub: lee-rotor turbulence is attached on this terrain scene"

    engine_stubs["monkeypatch"].setattr(runs_module,
                                        "frames_host_parity_refusal",
                                        rotor_rule)
    manager = engine_stubs["manager"]
    run = RunState(run_id="rotorframes")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "failed"
    assert run.detail.startswith("[render.host_parity] stub: lee-rotor")
    assert seen == [False]           # the flat test scene attaches no rotor
    assert calls == []               # no editor time was spent
    assert run.capture is None       # no capture was solved either
    # The clip flow never consults the rule: its label is visual-only.
    seen.clear()
    run = RunState(run_id="rotorclip")

    def clip_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera_flags=None, camera_index=None,
                    log=None):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(clip_render))
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="clip")
    assert run.status == "done", run.detail
    assert seen == []


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
    reply = engine_client.post("/run", json={"spec": spec.to_dict(),
                                             "render": "clip"})
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


def test_an_omitted_render_field_resolves_through_the_one_default_rule(
        client, engine_stubs, monkeypatch):
    """POST /run without the field is not a second spelling of the
    default: it resolves through render_choice_default() -- headless on
    a machine without the engine (never a ue.platform refusal for a
    choice the client did not make), frames where the engine exists --
    and the reply echoes the resolved word."""
    import core.util.platform as plat
    import webapp.server as server_module
    from core.capture.render_pass import render_choice_default
    from webapp.runs import RunManager

    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this machine (test)")
    assert render_choice_default() == "none"
    spec = two_camera_spec()
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    assert reply.json()["render"] == "none" == render_choice_default()
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "done", state["detail"]
    assert state["render"] == "none" and "no pixels" in state["detail"]

    monkeypatch.setattr(plat, "ue_available", lambda: True)
    monkeypatch.setattr(plat, "ue_unavailable_reason", lambda: None)
    monkeypatch.setattr(server_module, "refuse_placeholder_mesh",
                        lambda spec: None)
    monkeypatch.setattr(runs_module, "editor_running", lambda: False)
    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    assert render_choice_default() == "frames"
    reply = client.post("/run", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    assert reply.json()["render"] == "frames" == render_choice_default()
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "done", state["detail"]
    assert state["render"] == "frames"
    assert [c["camera_index"] for c in calls] == [0, 1]
    # The page prints the server's word, with no fallback of its own.
    page = STATIC_INDEX.read_text(encoding="utf-8")
    assert 'render: ${payload.render})' in page
    assert '|| "clip"' not in page


def test_status_disables_the_engine_options_on_a_mac_without_the_engine(
        client, monkeypatch, tmp_path):
    """On macOS the gate looks for the editor and the built bridge
    exactly as on Windows: with neither, /status reports the engine
    choices unavailable WITH the reason and render_default 'none', so
    the page never selects an option the machine cannot honour."""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("UE_ROOT", str(tmp_path / "UE_5.5"))
    # The editor probe is the mac pgrep; on a non-mac CI runner faking
    # the platform there is no pgrep and no editor. Pin it: this test is
    # about the render gate, not the editor lock.
    import webapp.runs as runs_module
    monkeypatch.setattr(runs_module, "editor_running", lambda: False)
    status = client.get("/status").json()
    assert status["platform"] == "mac"
    assert status["render_available"] is False
    assert status["render_default"] == "none"
    assert status["render_unavailable_reason"].startswith(
        "no engine on this machine: set UE_ROOT")
    choices = {c["value"]: c for c in status["render_choices"]}
    for word in ("frames", "clip"):
        assert choices[word]["available"] is False
        assert choices[word]["reason"] == status["render_unavailable_reason"]
    assert choices["none"]["available"] is True
    # And the run itself is refused by name before any editor time.
    reply = client.post("/run", json={"spec": two_camera_spec().to_dict(),
                                      "render": "frames"})
    assert reply.status_code == 409
    assert reply.json()["constraint"] == "ue.platform"
    assert reply.json()["reason"] == status["render_unavailable_reason"]


# -- the geometry preview on the page (package I, done properly) ----------

def test_the_page_s_previews_are_full_resolution_with_a_contact_sheet(
        captured, client):
    """The capture summary says what the previews are (the record's own
    resolution, the measured seconds per frame, a contact sheet per
    camera) and the file list carries the sheet as its own entry above
    the per-frame gallery, with the previews still counted as 4."""
    from PIL import Image

    run_id, state = captured
    capture = state["capture"]
    manifest = client.get(
        f"/runs/{run_id}/file/capture/capture_manifest.json").json()
    record = manifest["frames"][0]
    assert capture["preview_scale"] == 1
    assert capture["preview_resolution"] == [record["width_px"],
                                             record["height_px"]]
    assert 0.0 < capture["preview_s_per_frame"] < 0.5
    # The flown track comes from the run's own telemetry at the rate
    # measured from its samples (the recorder's 13-step spacing: 9.23 Hz).
    import numpy as np

    telemetry = client.get(f"/runs/{run_id}/file/capture/telemetry.json").json()
    t = telemetry["columns"]["t"]
    rate = 1.0 / float(np.median(np.diff(t)))
    assert 9.0 < rate < 10.0
    assert capture["preview_track_source"] == (
        f"track: telemetry {rate:g} Hz ({len(t)} points, no decimation)")
    camera_id = record["camera_id"]
    assert capture["contact_sheets"] == {
        camera_id: f"capture/contact_sheets/{camera_id}.png"}
    assert manifest["aircraft_metrics"]["span_source"] == "metrics/bw-ft"

    files = client.get(f"/runs/{run_id}/files").json()["files"]
    sheet = next(f for f in files if f.get("sheet"))
    assert sheet["name"] == f"capture/contact_sheets/{camera_id}.png"
    assert "contact sheet" in sheet["note"]
    previews = next(f for f in files if f["name"] == f"capture/previews/{camera_id}")
    assert previews["count"] == 4                 # the sheet is not a preview
    assert all(name.endswith(".png") and "preview_" in name
               for name in previews["images"])
    got = client.get(f"/runs/{run_id}/file/{previews['images'][0]}")
    assert got.status_code == 200
    from io import BytesIO
    assert Image.open(BytesIO(got.content)).size == (record["width_px"],
                                                     record["height_px"])
    assert client.get(f"/runs/{run_id}/file/{sheet['name']}").status_code == 200
    run_json = client.get(f"/runs/{run_id}/file/capture/run.json").json()
    assert run_json["previews"]["scale"] == 1
    assert run_json["previews"]["count"] == 4
    assert run_json["previews"]["track_source"] == capture["preview_track_source"]


def test_the_page_s_preview_scale_field_is_honoured_or_refused_by_name(client):
    from PIL import Image
    from io import BytesIO

    spec = compile_prompt(DEMO)
    bad = client.post("/capture", json={"spec": spec.to_dict(),
                                        "preview_scale": 0})
    assert bad.status_code == 409
    assert bad.json()["constraint"] == "preview.scale"
    assert "preview.scale" in bad.json()["refused"]
    # 3 does not divide the default camera's 1280x720: refused by name
    # before the run starts (no run id), never floored to 426x240.
    three = client.post("/capture", json={"spec": spec.to_dict(),
                                          "preview_scale": 3})
    assert three.status_code == 409, three.json()
    assert three.json()["constraint"] == "preview.scale"
    assert "3 does not divide 1280x720 exactly (426.67x240)" in three.json()["refused"]
    assert "run_id" not in three.json()
    three_run = client.post("/run", json={"spec": spec.to_dict(),
                                          "preview_scale": 3, "render": "none"})
    assert three_run.status_code == 409 and three_run.json()["constraint"] == "preview.scale"
    reply = client.post("/capture", json={"spec": spec.to_dict(),
                                          "preview_scale": 2})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "done", state["detail"]
    capture = state["capture"]
    assert capture["preview_scale"] == 2
    assert capture["previews"] == 4
    manifest = client.get(
        f"/runs/{run_id}/file/capture/capture_manifest.json").json()
    record = manifest["frames"][0]
    assert capture["preview_resolution"] == [record["width_px"] // 2,
                                             record["height_px"] // 2]
    got = client.get(f"/runs/{run_id}/file/capture/previews/"
                     f"{record['camera_id']}/preview_00000.png")
    assert Image.open(BytesIO(got.content)).size == (record["width_px"] // 2,
                                                     record["height_px"] // 2)


def test_the_frames_run_overlays_the_reprojected_geometry_on_every_frame(
        engine_stubs):
    """A frames run draws the manifest's geometry over every rendered
    PNG under capture/overlays/<camera_id>/, the frame's own size,
    counts them in the summary and lists them as their own artefact
    class with the note that says what they are."""
    from PIL import Image

    from core.capture.verify import labelled_pixel
    from webapp.runs import RunManager, RunState

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    manager = engine_stubs["manager"]
    run = RunState(run_id="overlayrun")
    manager._render_flow(run, two_camera_spec(), provenance={},
                         render="frames")
    assert run.status == "done", run.detail
    out = manager.out_root / "overlayrun"
    assert run.capture["overlays"] == 8
    assert 0.0 < run.capture["overlay_s_per_frame"] < 0.5
    manifest = json.loads(
        (out / "capture" / "capture_manifest.json").read_text(encoding="utf-8"))
    for camera_id in ("camera0", "tower0"):
        names = sorted(p.name for p in
                       (out / "capture" / "overlays" / camera_id).glob("*.png"))
        assert names == ["0000.png", "0001.png", "0002.png", "0003.png"]
    record = next(r for r in manifest["frames"]
                  if r["camera_id"] == "camera0" and r["index"] == 2)
    frame = Image.open(out / "capture" / record["file"])
    overlay = Image.open(out / "capture" / "overlays" / "camera0" / "0002.png")
    assert overlay.size == frame.size
    u, v, depth = labelled_pixel(record)
    assert depth > 0
    assert overlay.getpixel((int(round(u)), int(round(v)))) != \
        frame.getpixel((int(round(u)), int(round(v))))
    files = capture_module.run_artifacts(out)
    entry = next(f for f in files if f["name"] == "capture/overlays/camera0")
    assert entry["count"] == 4
    assert "reprojected geometry over the rendered frame" in entry["note"]
    assert entry["images"][0] == "capture/overlays/camera0/0000.png"
    assert any(l["detail"].startswith("8 overlay(s): the manifest's aircraft")
               for l in run.events if l["status"] == "capture")


# -- the page itself: downloads, galleries and the verifier's table --------
# The capture card and the files panel are built by PURE functions on the
# page (between PAGE_CAPTURE_BEGIN and PAGE_CAPTURE_END: HTML from the
# server's JSON, no DOM, no fetch). They are run VERBATIM under node here
# against the real /runs/{id} and /files payloads, so the words the card
# prints -- the count contract, the fallback label, the verifier's table --
# are pinned by a test, not by reading the source.

PAGE_CAPTURE_HARNESS = """
%s
const input = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const files = input.files || {};
const out = {
  terminal: runIsTerminal(input.run),
  clip: clipHtml(input.runId, input.run),
  card: captureCardHtml(input.run),
  strip: downloadStripHtml(input.runId, files.downloads || []),
  galleries: (files.galleries || []).map(g => galleryHtml(input.runId, input.run, g)),
  files: filesHtml(input.runId, files.files || []),
  moves: (input.cameras || []).map(cameraMovesHtml),
  telemetry: telemetrySource(input.run, files),
  refusals: (input.refusals || []).map(r => refusalWords(r.payload, r.verb)),
};
console.log(JSON.stringify(out));
"""


def page_capture(tmp_path, run, files, run_id="run1", cameras=None,
                 refusals=None):
    """Render the page's capture card, download strip and files panel
    (and, given the compile payload's camera blocks, their move rows;
    given ``refusals`` as [{"payload", "verb"}], their refusal lines)
    under node from the page's own source, and return the HTML of each."""
    import re
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the page's HTML builders need it")
    page = STATIC_INDEX.read_text(encoding="utf-8")
    block = re.search(r"// PAGE_CAPTURE_BEGIN\n(.*?)// PAGE_CAPTURE_END",
                      page, re.S).group(1)
    harness = tmp_path / "page_capture.js"
    harness.write_text(PAGE_CAPTURE_HARNESS % block, encoding="utf-8")
    payload = tmp_path / "page_capture_input.json"
    payload.write_text(json.dumps({"run": run, "files": files,
                                   "runId": run_id, "cameras": cameras,
                                   "refusals": refusals}),
                       encoding="utf-8")
    proc = subprocess.run([node, str(harness), str(payload)],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def text_of(html):
    """The words a reader sees: tags stripped, whitespace collapsed."""
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def links_of(html, cls):
    """The hrefs of the anchors carrying CSS class ``cls``."""
    import re

    return re.findall(r'<a class="dl dl-' + cls + r'" href="([^"]+)"', html)


@pytest.fixture()
def frames_run(engine_client, engine_stubs):
    """A two-camera frames run through POST /run with the honest engine
    stub: 8 PNGs on disk, the clip a by-product, the counts verified."""
    from webapp.runs import RunManager

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls)))
    reply = engine_client.post("/run", json={"spec": two_camera_spec().to_dict(),
                                             "render": "frames"})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(engine_client, run_id)
    assert state["status"] == "done", state["detail"]
    return run_id, state


def test_the_frames_zip_carries_exactly_the_frame_set(frames_run,
                                                      engine_client):
    """/runs/{id}/frames.zip is the frame set alone: every rendered PNG
    the file list names under capture/frames/<camera_id>/ plus each
    camera's render.json -- no previews, no overlays, no contact sheets,
    no logs. The download strip offers one button per artefact class
    the run wrote, in the stated order."""
    run_id, _ = frames_run
    payload = engine_client.get(f"/runs/{run_id}/files").json()
    files = payload["files"]
    listed_pngs = set()
    for entry in files:
        if entry["name"].startswith("capture/frames/") and "images" in entry:
            listed_pngs.update(entry["images"])
    assert len(listed_pngs) == 8
    render_jsons = {f["name"] for f in files
                    if f["name"].startswith("capture/frames/")
                    and f["name"].endswith("/render.json")}
    assert render_jsons == {"capture/frames/camera0/render.json",
                            "capture/frames/tower0/render.json"}

    got = engine_client.get(f"/runs/{run_id}/frames.zip")
    assert got.status_code == 200
    assert got.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(manager.out_root / run_id / "frames.zip") as archive:
        names = set(archive.namelist())
    assert names == listed_pngs | render_jsons
    assert not any("previews" in n or "overlays" in n or "contact_sheets" in n
                   or n.endswith(".log") for n in names)
    # The bundle still carries everything (previews, overlays, logs...);
    # the frames zip is the subset a user wanting "the frame set" takes.
    assert len(listed_pngs) < sum(
        len(f["images"]) if "images" in f else 1 for f in files)

    downloads = payload["downloads"]
    assert [d["class"] for d in downloads] == [
        "frames", "manifest", "verification", "telemetry", "clip", "everything"]
    by_class = {d["class"]: d for d in downloads}
    assert by_class["frames"]["href"] == "frames.zip"
    assert by_class["verification"]["href"] == "file/capture/verify.json"
    assert by_class["verification"]["label"] == "verify.json"
    assert by_class["verification"]["note"].startswith(
        "capture/verify.json: the verification checks as run")
    assert by_class["frames"]["note"] == (
        "8 PNG(s) across 2 camera(s) (camera0, tower0), named by manifest "
        "index, with each camera's render.json")
    assert by_class["manifest"]["href"] == "file/capture/capture_manifest.json"
    assert by_class["telemetry"]["href"] == "file/capture/telemetry.json"
    assert by_class["clip"]["href"] == "file/clip.mp4"
    assert by_class["clip"]["note"].startswith("clip.mp4: by-product of 'camera0'")
    assert by_class["everything"]["href"] == "bundle.zip"
    total = sum(len(f["images"]) if "images" in f else 1 for f in files)
    assert by_class["everything"]["note"] == f"{total} file(s): every artefact listed below"
    # Every class's route answers.
    for d in downloads:
        assert engine_client.get(f"/runs/{run_id}/{d['href']}").status_code == 200, d


def test_the_frames_zip_is_refused_by_name_without_rendered_frames(
        captured, client, engine_client, engine_stubs):
    """A headless run has no frame set and says so -- a 404 with the
    run's own reason, never an empty zip; and its strip offers no
    frames.zip. The clip-only run is refused in its own words."""
    from webapp.runs import RunManager

    run_id, _ = captured
    got = client.get(f"/runs/{run_id}/frames.zip")
    assert got.status_code == 404
    assert got.json()["constraint"] == "frames.none"
    assert got.json()["error"].startswith(
        "no rendered frames: this was a headless run (no engine pass)")
    assert not (manager.out_root / run_id / "frames.zip").exists()
    downloads = client.get(f"/runs/{run_id}/files").json()["downloads"]
    assert [d["class"] for d in downloads] == ["manifest", "verification",
                                               "telemetry", "everything"]

    def clip_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    look=None, camera_flags=None, camera_index=None,
                    log=None):
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(clip_render))
    # The panel step writes clip.mp4 on a real run; the stub does too, so
    # the strip's clip button is judged against a file on disk.
    engine_stubs["monkeypatch"].setattr(
        runs_module, "build_panel_clip",
        lambda card, manifest, conditions, raw, clip, fps=None:
            bool(Path(clip).write_bytes(b"mp4")) or True)
    reply = engine_client.post("/run", json={"spec": compile_prompt(DEMO).to_dict(),
                                             "render": "clip"})
    assert reply.status_code == 200, reply.json()
    clip_id = reply.json()["run_id"]
    assert finished(engine_client, clip_id)["status"] == "done"
    got = engine_client.get(f"/runs/{clip_id}/frames.zip")
    assert got.status_code == 404
    assert got.json()["error"] == (
        "no rendered frames: this was a clip-only run; choose 'Render "
        "frames and clip' for the frame set")
    downloads = engine_client.get(f"/runs/{clip_id}/files").json()["downloads"]
    assert [d["class"] for d in downloads] == ["manifest", "verification",
                                               "telemetry", "clip", "everything"]
    assert downloads[3]["note"] == "clip.mp4: the rendered clip (clip only: no frame set)"


def test_the_page_s_download_strip_offers_one_button_per_class(
        captured, client, tmp_path):
    """The page's strip, from the real /files payload of the headless
    run: exactly one button per download class the server listed, each
    linking the server's route, and no frames.zip when no frame was
    rendered; the strip sits at the top of the capture card."""
    run_id, state = captured
    payload = client.get(f"/runs/{run_id}/files").json()
    html = page_capture(tmp_path, state, payload, run_id)
    strip = html["strip"]
    classes = [d["class"] for d in payload["downloads"]]
    assert classes == ["manifest", "verification", "telemetry", "everything"]
    for d in payload["downloads"]:
        assert links_of(strip, d["class"]) == [f"/runs/{run_id}/{d['href']}"]
        assert d["label"] in text_of(strip) and d["note"] in text_of(strip)
    assert links_of(strip, "frames") == []
    assert "frames.zip" not in strip
    assert strip.count('<a class="dl ') == len(classes)
    # The card carries the strip's holder FIRST, then the geometry words.
    card = html["card"]
    assert card.index('id="captureDownloads"') < card.index("capture geometry")
    # A synthetic frames-run listing: the frames button appears, first.
    frames_payload = {"downloads": [
        {"class": "frames", "label": "frames.zip", "href": "frames.zip",
         "note": "48 PNG(s) across 2 camera(s) (chase0, tower0), named by "
                 "manifest index, with each camera's render.json"},
        {"class": "clip", "label": "clip.mp4", "href": "file/clip.mp4",
         "note": "clip.mp4: by-product of 'chase0' (the frame set is the "
                 "deliverable)"}]}
    strip = page_capture(tmp_path, state, frames_payload, "abc")["strip"]
    assert links_of(strip, "frames") == ["/runs/abc/frames.zip"]
    assert strip.count('<a class="dl ') == 2
    assert text_of(strip).startswith("downloads frames.zip 48 PNG(s) across 2 camera(s)")


def img_srcs(html):
    import re

    return re.findall(r'<img [^>]*src="([^"]+)"', html)


def test_the_file_list_describes_a_gallery_per_camera_from_the_manifest(
        captured, client, frames_run, engine_client):
    """/files "galleries": per camera, the manifest's records matched
    against the files on disk. A headless run lists NO frames (there
    are none) and its 4 previews with the manifest's instants; the
    frames run lists 4 frames per camera, each with its overlay, and
    the previews beside them. A count in a gallery is a count of files
    the run can serve."""
    run_id, _ = captured
    payload = client.get(f"/runs/{run_id}/files").json()
    manifest = client.get(
        f"/runs/{run_id}/file/capture/capture_manifest.json").json()
    times = [r["t_s"] for r in manifest["frames"]]
    galleries = payload["galleries"]
    assert [g["camera_id"] for g in galleries] == ["camera0"]
    camera = galleries[0]
    assert camera["scheduled"] == 4 and camera["frames"] == []
    assert [p["t_s"] for p in camera["previews"]] == times
    assert [p["index"] for p in camera["previews"]] == [0, 1, 2, 3]
    assert camera["previews"][0]["file"] == "capture/previews/camera0/preview_00000.png"
    assert camera["contact_sheet"] == "capture/contact_sheets/camera0.png"
    for item in camera["previews"]:
        assert client.get(f"/runs/{run_id}/file/{item['file']}").status_code == 200

    frames_id, _ = frames_run
    galleries = engine_client.get(f"/runs/{frames_id}/files").json()["galleries"]
    assert [g["camera_id"] for g in galleries] == ["camera0", "tower0"]
    for gallery in galleries:
        cam = gallery["camera_id"]
        assert gallery["scheduled"] == 4
        assert [f["file"] for f in gallery["frames"]] == [
            f"capture/frames/{cam}/{i:04d}.png" for i in range(4)]
        assert [f["overlay"] for f in gallery["frames"]] == [
            f"capture/overlays/{cam}/{i:04d}.png" for i in range(4)]
        assert len(gallery["previews"]) == 4
        for item in gallery["frames"]:
            assert engine_client.get(
                f"/runs/{frames_id}/file/{item['file']}").status_code == 200
            assert engine_client.get(
                f"/runs/{frames_id}/file/{item['overlay']}").status_code == 200
    # No manifest, no galleries (a refused capture wrote none).
    assert capture_module.run_galleries(manager.out_root / "nowhere") == []


def test_a_headless_run_records_why_the_machine_has_no_engine(
        client, monkeypatch):
    """The platform gate's own reason travels with the run (state and
    provenance), so the page labels the previews as the fallback with
    the server's words, never a page-side guess."""
    import core.util.platform as plat

    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine (test): set UE_ROOT")
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "done", state["detail"]
    assert state["engine_reason"] == "no engine (test): set UE_ROOT"
    provenance = json.loads(
        (manager.out_root / run_id / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["engine_unavailable_reason"] == "no engine (test): set UE_ROOT"


def test_the_page_s_galleries_show_every_frame_and_label_previews_as_the_fallback(
        captured, client, frames_run, engine_client, tmp_path):
    """The page's own gallery builder against the real payloads.

    Headless: the heading is the count contract ("4 scheduled, 0
    rendered (headless), previews only"), the pictures are the previews
    labelled "fallback" with the server's recorded reason, every count
    shown equals the number of <img> tags, and no preview count stands
    beside the word "frames". Frames run: every rendered frame is shown
    (count == img tags == the verifier's rendered count), captioned with
    its index and instant from the manifest, the overlay behind a
    toggle, the previews behind a "not frames" disclosure. Clip only:
    the fallback names the clip-only choice."""
    import re

    run_id, state = captured
    payload = client.get(f"/runs/{run_id}/files").json()
    html = page_capture(tmp_path, state, payload, run_id)
    assert len(html["galleries"]) == 1
    gallery = html["galleries"][0]
    words = text_of(gallery)
    assert words.startswith("camera0 : 4 scheduled, 0 rendered (headless), previews only")
    # The fallback names the platform gate's reason ONCE -- the sentence
    # /status and the CLI print, which already begins "no engine ..."
    # on every platform (Linux: "no engine on this OS", macOS and
    # Windows: "no engine on this machine: set UE_ROOT ...") -- never
    # prefixed with a second "no engine" clause. Compared by count, not
    # by the platform's wording, so the CI legs all grade the same thing.
    reason = state["engine_reason"]
    expected = (reason if reason
                else "headless run by choice; choose Render frames and clip "
                     "for the frame set")
    assert f"previews (fallback: {expected}; showing 4 of 4 preview(s), " \
           f"which are NOT frames)" in words
    if reason:
        assert reason.startswith("no engine")
        assert words.count("no engine") == reason.count("no engine") == 1
    srcs = img_srcs(gallery)
    previews = [s for s in srcs if "/previews/" in s]
    assert len(previews) == 4 == payload["galleries"][0]["scheduled"]
    assert [s for s in srcs if "/contact_sheets/" in s] == [
        f"/runs/{run_id}/file/capture/contact_sheets/camera0.png"]
    assert not [s for s in srcs if "/frames/" in s]
    # With no rendered frame the sheet stays where it is: under the
    # fallback label, above the preview thumbnails, no disclosure.
    assert "<details>" not in gallery
    assert gallery.index("fallback") < gallery.index('class="sheet"') \
        < gallery.index('data-kind="previews"')
    # "4 frames", "4 rendered", "captured 4": none of it, anywhere.
    assert re.search(r"\b4 (rendered )?frames?\b", words) is None
    assert "captured" not in words and "4 rendered" not in words
    # The captions carry the manifest's instants.
    manifest = client.get(
        f"/runs/{run_id}/file/capture/capture_manifest.json").json()
    for record in manifest["frames"]:
        assert f"#{record['index']} t={record['t_s']:.3f} s" in words
    # The card's own galleries holder starts as the per-camera list.
    card_words = text_of(html["card"])
    assert "camera0 : 4 scheduled, 0 rendered (headless), previews only" in card_words
    assert 'id="captureGalleries"' in html["card"]

    # Clip only: the same summary, the fallback in its own words.
    clip_state = json.loads(json.dumps(state))
    clip_state["render"] = "clip"
    clip_words = text_of(page_capture(tmp_path, clip_state, payload, run_id)["galleries"][0])
    assert "camera0 : 4 scheduled, 0 rendered (clip only), previews only" in clip_words
    assert ("previews (fallback: clip-only run; choose Render frames and clip "
            "for the frame set; showing 4 of 4 preview(s), which are NOT frames)"
            in clip_words)

    # Frames run: every frame shown, captioned, overlays a toggle away.
    frames_id, frames_state = frames_run
    frames_payload = engine_client.get(f"/runs/{frames_id}/files").json()
    html = page_capture(tmp_path, frames_state, frames_payload, frames_id)
    assert len(html["galleries"]) == 2
    manifest = engine_client.get(
        f"/runs/{frames_id}/file/capture/capture_manifest.json").json()
    for gallery, counts in zip(html["galleries"], frames_state["capture"]["cameras"]):
        cam = counts["camera_id"]
        words = text_of(gallery)
        assert words.startswith(f"{cam} : 4 scheduled, 4 rendered, 4 verified "
                                f"— showing 4 of 4 rendered frame(s)")
        assert counts["rendered"] == 4
        frame_imgs = re.findall(r'<img loading="lazy" src="([^"]+)" data-frame="[^"]+"'
                                r' data-overlay="([^"]+)">', gallery)
        assert [src for src, _ in frame_imgs] == [
            f"/runs/{frames_id}/file/capture/frames/{cam}/{i:04d}.png" for i in range(4)]
        assert [ov for _, ov in frame_imgs] == [
            f"/runs/{frames_id}/file/capture/overlays/{cam}/{i:04d}.png" for i in range(4)]
        assert f"toggleOverlays('{cam}', this.checked)" in gallery
        assert "show the reprojected-geometry overlays (4 of 4)" in words
        for record in (r for r in manifest["frames"] if r["camera_id"] == cam):
            assert f"#{record['index']} t={record['t_s']:.3f} s" in words
        # Previews: behind a disclosure that says they are not frames,
        # never beside the frames as peers.
        assert "<details><summary" in gallery
        assert "geometry previews (not frames): 4 shown, and their contact sheet" in words
        assert gallery.index('data-kind="frames"') < gallery.index("<details>")
        assert gallery.index("<details>") < gallery.index('data-kind="previews"')
        assert "fallback" not in words
        # The contact sheet is a mosaic of PREVIEWS: on a frames run it
        # sits inside the previews' disclosure, never above the rendered
        # frames -- the first picture under a rendered count is a frame.
        sheet = gallery.index('class="sheet"')
        assert gallery.index("<details>") < sheet < gallery.index('data-kind="previews"')
        first_img = gallery.index("<img ")
        assert 'class="sheet"' not in gallery[first_img:first_img + 40]
        assert "/frames/" in gallery[first_img:gallery.index(">", first_img)]
    # The files panel no longer draws thumbnails of its own: one row per
    # image class with its count, the pictures in the galleries above.
    files_words = text_of(html["files"])
    assert "<img" not in html["files"]
    assert "capture/frames/camera0 — 4 rendered frame(s) for camera 'camera0'" in files_words
    assert "(4 file(s), in the capture card's gallery)" in files_words


def test_the_page_s_verification_table_is_verify_json_s_own_table(
        captured, client, tmp_path):
    """The card shows the verifier's checks as the CHECK / STATUS /
    MEASURED / TOLERANCE / WHERE table flightsim.verify prints -- the
    rows are verify.json's "table" verbatim (the same measured_text,
    tolerance_text and where), the tally is verify.json's "summary"
    line verbatim, and only the rows that did not PASS get a detail
    line, as in the CLI. Nothing is re-derived on the page."""
    import html as html_module
    import re

    run_id, state = captured
    verification = state["capture"]["verification"]
    on_disk = json.loads(
        (manager.out_root / run_id / "capture" / "verify.json")
        .read_text(encoding="utf-8"))
    assert on_disk["table"] == verification["table"]
    card = page_capture(tmp_path, state, {}, run_id)["card"]
    table = re.search(r'<table class="verify">.*?</table>', card, re.S).group(0)
    header = re.findall(r"<th>([^<]+)</th>", table)
    assert header == ["CHECK", "STATUS", "MEASURED", "TOLERANCE", "WHERE"]
    rows = []
    for match in re.finditer(
            r'<tr class="check check-(\w+)" title="([^"]*)">'
            r'<td>([^<]*)</td><td><b style="color:#[0-9a-f]{6}">(\w+)</b></td>'
            r'<td>([^<]*)</td><td>([^<]*)</td><td class="dim">([^<]*)</td></tr>',
            table):
        cls, title, name, status, measured, tolerance, where = (
            html_module.unescape(g) for g in match.groups())
        assert cls == status
        rows.append([name, status, measured, tolerance, where])
        check = next(c for c in verification["checks"] if c["name"] == name)
        assert title == check["detail"]
    assert rows == [list(r) for r in verification["table"]]
    assert len(rows) == 10
    # The numbers a reader checks: geometry recovery's measured px against
    # its tolerance and the worst frame, straight from the verifier.
    geometry = next(r for r in rows if r[0] == "geometry_recovery")
    assert re.fullmatch(r"[0-9.e-]+ px", geometry[2]) and geometry[3] == "0.5 px"
    assert geometry[4].startswith("worst camera0 #")
    # Detail lines only for the rows that did not PASS, in the CLI's form.
    details = re.findall(r'<tr class="detail"><td></td><td colspan="4" class="dim">'
                         r'\[(\w+)\] (\w+): ', table)
    assert details == [("SKIPPED", "cross_view_consistency"),
                       ("AWAITING", "engine_parity")]
    # The tally is the verifier's own line, verbatim, followed by a link
    # to the file it was rendered from.
    assert f"<b>{verification['summary']}</b>" in card
    assert (f"<b>{verification['summary']}</b> <a class=\"dim filelink\" "
            f"href=\"/runs/{run_id}/file/capture/verify.json\" target=\"_blank\">"
            f"capture/verify.json</a>") in card
    assert client.get(f"/runs/{run_id}/file/capture/verify.json").status_code == 200
    # No run id in the payload, no link invented.
    anonymous = json.loads(json.dumps(state)); anonymous.pop("run_id")
    assert "filelink" not in page_capture(tmp_path, anonymous, {}, run_id)["card"]
    assert verification["summary"].startswith("verification PASSED (8/8 checks; 1 skipped: "
                                              "cross_view_consistency (single camera); "
                                              "1 awaiting engine frames: engine_parity)")
    assert "checks ran;" not in text_of(card)


def test_a_mid_run_refusal_keeps_its_offending_value(client, monkeypatch,
                                                     tmp_path):
    """camera.terrain_clearance's message never states the AGL it
    measured -- that number lives in the Violation's actual/limit/unit.
    A refusal raised mid-capture now carries the three through
    CaptureError into run.capture, the status line and the card, in the
    same "(measured X, limit Y)" shape the pre-run verdict uses."""
    from core.scenario.validate import Violation
    import core.capture.validate as validate_module

    monkeypatch.setattr(
        validate_module, "track_violations",
        lambda *a, **k: [Violation(
            constraint="camera.terrain_clearance",
            message="tower0: the stated placement sits inside or on the "
                    "scene's terrain (checked over the whole run window)",
            actual=-12.3, limit=30.0, unit="m AGL")])
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "failed"
    assert state["capture"] == {
        "refused": "camera.terrain_clearance",
        "message": "tower0: the stated placement sits inside or on the "
                   "scene's terrain (checked over the whole run window)",
        "actual": -12.3, "limit": 30.0, "unit": "m AGL"}
    expected = ("[camera.terrain_clearance] tower0: the stated placement sits "
                "inside or on the scene's terrain (checked over the whole run "
                "window) (measured -12.3 m AGL, limit 30 m AGL)")
    assert state["detail"] == expected
    assert [e["detail"] for e in state["events"] if e["status"] == "capture"][-1] \
        == expected
    # The card prints the same words.
    card = page_capture(tmp_path, state, {}, "refusedrun")["card"]
    assert ("[camera.terrain_clearance] tower0: the stated placement sits "
            "inside or on the scene's terrain (checked over the whole run "
            "window) (measured -12.3 m AGL, limit 30 m AGL)") in text_of(card)
    assert "capture refused" in text_of(card)
    # A refusal with no value (a schedule refusal) renders without the clause.
    assert capture_module.CaptureError("camera.schedule", "4 over 3 s").render() \
        == "[camera.schedule] 4 over 3 s"
    assert capture_module.CaptureError("camera.schedule", "4 over 3 s").as_dict() \
        == {"refused": "camera.schedule", "message": "4 over 3 s",
            "actual": None, "limit": None, "unit": None}


def test_the_closure_report_names_its_units_and_the_graded_window(
        captured, client, frames_run, tmp_path):
    """Each closure row carries the tolerance's unit, and the heading
    says which flight was graded: closure.json's window (the clip's
    capped window on a headless or clip run; the full duration a frames
    run steps) with its length in seconds."""
    run_id, state = captured
    closure = state["capture"]["closure"]
    # The window word names what was GRADED: a headless run has no clip
    # to name, so closure.json says "capped" (the first min(duration,
    # cap) seconds) and records the spec's own duration beside it.
    assert closure["window"] == "capped" and closure["duration_s"] == 3.0
    assert closure["clip_seconds_cap"] == 22.0
    assert closure["spec_duration_s"] == 3.0
    words = text_of(page_capture(tmp_path, state, {}, run_id)["card"])
    assert ("closure PASSED — the same spec flown closed loop, graded over "
            "the settled half of 3 s (the first 3 s, the same window a clip "
            "would cover, capped at 22 s)") in words
    assert "clip's window" not in words
    # A clip run names its clip; a capped flight names the whole flight.
    clip_state = json.loads(json.dumps(state))
    clip_state["render"] = "clip"
    assert ("graded over the settled half of 3 s (the first 3 s, the clip's "
            "window, capped at 22 s)") in text_of(
                page_capture(tmp_path, clip_state, {}, run_id)["card"])
    capped_state = json.loads(json.dumps(state))
    capped_state["capture"]["closure"].update({"duration_s": 22.0,
                                               "spec_duration_s": 120.0})
    assert ("graded over the settled half of 22 s (the first 22 s of the 120 s "
            "flight, the same window a clip would cover, capped at 22 s)") in text_of(
                page_capture(tmp_path, capped_state, {}, run_id)["card"])
    for check in closure["checks"]:
        assert (f"ok {check['name']}: commanded {check['commanded']:.2f} "
                f"{check['unit']}, achieved {check['achieved']:.2f} "
                f"{check['unit']} (tol {check['tolerance']:g} {check['unit']})") in words
    assert "altitude: commanded 1524.00 m, achieved 1524.00 m (tol 15 m)" in words
    assert "settled half)" not in words
    # The heading links the file it is rendered from.
    card = page_capture(tmp_path, state, {}, run_id)["card"]
    assert (f"capped at 22 s)</span> <a class=\"dim filelink\" "
            f"href=\"/runs/{run_id}/file/capture/closure.json\" target=\"_blank\">"
            f"capture/closure.json</a><ul>") in card
    assert client.get(f"/runs/{run_id}/file/capture/closure.json").status_code == 200

    frames_id, frames_state = frames_run
    closure = frames_state["capture"]["closure"]
    assert closure["window"] == "full duration"
    words = text_of(page_capture(tmp_path, frames_state, {}, frames_id)["card"])
    assert ("graded over the settled half of 3 s (full duration: a frames run "
            "steps the whole flight)") in words


# -- a FAILED run is terminal for the page: card, strip and files ----------

def test_poll_draws_the_page_through_the_one_terminal_rule():
    """poll() used to draw the card and the files panel only on
    status "done" and stop silently on "failed" -- the refused-capture
    branch of the card was dead on the live page and a failed run's
    files were unreachable from it. Pinned at the source: poll asks
    runIsTerminal (done OR failed), and no other comparison against
    "done" exists in the page's run handling."""
    import re

    page = STATIC_INDEX.read_text(encoding="utf-8")
    poll = re.search(r"async function poll\(\) \{.*?\n\}\n", page, re.S).group(0)
    assert "if (runIsTerminal(run)) {" in poll
    assert "clipHtml(activeRun, run)" in poll
    assert "renderCapture(run);" in poll and "initFilesPanel(activeRun, run);" in poll
    assert 'run.status === "done"' not in poll
    assert '"failed"' not in poll
    rule = re.search(r"function runIsTerminal\(run\) \{\n(.*?)\n\}", page, re.S).group(1)
    assert rule.strip() == 'return run.status === "done" || run.status === "failed";'


def test_a_mid_run_refusal_is_terminal_and_its_files_are_one_click_away(
        client, monkeypatch, tmp_path):
    """The refused-capture path the page actually takes: a
    camera.terrain_clearance refusal through POST /capture ends
    "failed" with provenance.json, scenario.yaml, status.json and
    jsbsim.log on disk. The page's own functions on that payload: the
    run is terminal, the card is the refusal with its constraint and
    measured value (and says the run ended on it), the strip offers
    "everything", the files panel lists each file the run wrote, and
    the clip words say there was no engine pass. A live run is not
    terminal."""
    from core.scenario.validate import Violation
    import core.capture.validate as validate_module

    monkeypatch.setattr(
        validate_module, "track_violations",
        lambda *a, **k: [Violation(
            constraint="camera.terrain_clearance",
            message="tower0: the stated placement sits inside or on the "
                    "scene's terrain (checked over the whole run window)",
            actual=-12.3, limit=30.0, unit="m AGL")])
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "failed"
    payload = client.get(f"/runs/{run_id}/files").json()
    names = [f["name"] for f in payload["files"]]
    assert names == ["provenance.json", "scenario.yaml", "status.json", "jsbsim.log"]
    assert [d["class"] for d in payload["downloads"]] == ["everything"]
    assert payload["galleries"] == []
    html = page_capture(tmp_path, state, payload, run_id)
    assert html["terminal"] is True
    card = text_of(html["card"])
    assert card.startswith("capture refused — [camera.terrain_clearance] tower0: ")
    assert "(measured -12.3 m AGL, limit 30 m AGL)" in card
    assert ("the run ended failed on this refusal; every file it wrote before "
            "refusing is listed below") in card
    assert html["card"].index('id="captureDownloads"') < html["card"].index("capture refused")
    assert links_of(html["strip"], "everything") == [f"/runs/{run_id}/bundle.zip"]
    assert "4 file(s): every artefact listed below" in text_of(html["strip"])
    files = html["files"]
    for name in names:
        assert f'href="/runs/{run_id}/file/{name}"' in files
        assert client.get(f"/runs/{run_id}/file/{name}").status_code == 200
    assert "status.json" in text_of(files) and "the verdict it ended on" in text_of(files)
    assert text_of(html["clip"]) == ("no clip: this was a headless run (the geometry "
                                     "below is the deliverable; no engine pass ran)")
    # A run still in flight is not terminal: nothing is drawn yet.
    live = dict(state, status="capture", detail="flying the spec headlessly")
    assert page_capture(tmp_path, live, payload, run_id)["terminal"] is False


def test_a_short_engine_pass_shows_its_partial_frame_set_on_the_page(
        engine_client, engine_stubs, tmp_path):
    """The other failed payload: an engine pass that captured 3 of 4
    scheduled frames fails the run by name (render.frames) and leaves
    the manifest, verify.json, the previews and the partial frame
    directory on disk. On the page: the run is terminal; the card's
    count contract says "8 scheduled, 3 rendered, 3 verified (engine
    pass FAILED: <the status line>)"; the strip offers frames.zip with
    the 3 PNGs, the manifest, the telemetry and everything (no clip:
    none was encoded); camera0's gallery shows its 3 rendered frames
    and tower0's says the pass rendered nothing for it; the clip words
    name the failure."""
    import re

    from webapp.runs import RunManager

    calls = []
    engine_stubs["monkeypatch"].setattr(
        RunManager, "_render", staticmethod(honest_engine(calls, short_for=0)))
    reply = engine_client.post("/run", json={"spec": two_camera_spec().to_dict(),
                                             "render": "frames"})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(engine_client, run_id)
    assert state["status"] == "failed"
    assert state["detail"].startswith("[render.frames] camera 'camera0': ")
    assert "captured 3 of 4 scheduled" in state["detail"]
    assert state["clip"] is None
    payload = engine_client.get(f"/runs/{run_id}/files").json()
    names = [f["name"] for f in payload["files"]]
    for name in ("capture/capture_manifest.json", "capture/verify.json",
                 "capture/frames/camera0", "capture/frames/camera0/render.json",
                 "capture/previews/camera0", "capture/previews/tower0",
                 "status.json"):
        assert name in names, name
    assert "clip.mp4" not in names
    frames_entry = next(f for f in payload["files"] if f["name"] == "capture/frames/camera0")
    assert len(frames_entry["images"]) == 3
    assert [d["class"] for d in payload["downloads"]] == [
        "frames", "manifest", "verification", "telemetry", "everything"]

    html = page_capture(tmp_path, state, payload, run_id)
    assert html["terminal"] is True
    card = text_of(html["card"])
    assert ("capture geometry — 8 scheduled, 3 rendered, 3 verified (engine pass "
            f"FAILED: {state['detail']})") in card
    assert card.index("engine pass FAILED") < card.index("8 geometry preview(s)")
    assert "camera0 : 4 scheduled, 3 rendered, 3 verified" in card
    assert "tower0 : 4 scheduled, 0 rendered, 0 verified" in card
    assert "verification FAILED" in card
    assert links_of(html["strip"], "frames") == [f"/runs/{run_id}/frames.zip"]
    assert "3 PNG(s) across 1 camera(s) (camera0)" in text_of(html["strip"])
    assert links_of(html["strip"], "clip") == []
    zipped = engine_client.get(f"/runs/{run_id}/frames.zip")
    assert zipped.status_code == 200
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert sorted(archive.namelist()) == [
            "capture/frames/camera0/0000.png", "capture/frames/camera0/0001.png",
            "capture/frames/camera0/0002.png", "capture/frames/camera0/render.json"]
    galleries = [text_of(g) for g in html["galleries"]]
    assert galleries[0].startswith("camera0 : 4 scheduled, 3 rendered, 3 verified "
                                   "— showing 3 of 3 rendered frame(s)")
    assert len(re.findall(r'data-frame="[^"]+/frames/camera0/', html["galleries"][0])) == 3
    assert galleries[1].startswith("tower0 : 4 scheduled, 0 rendered, 0 verified")
    assert ("previews (fallback: the engine pass rendered no frame for this camera "
            "(the run's status names the failure); showing 4 of 4 preview(s), "
            "which are NOT frames)") in galleries[1]
    assert f'href="/runs/{run_id}/file/capture/verify.json"' in html["files"]
    assert text_of(html["clip"]) == ("no clip: the run FAILED before a clip was "
                                     f"encoded — {state['detail']}")
    # A done frames run whose by-product did not encode says so too.
    unencoded = dict(state, status="done", clip=None)
    assert text_of(page_capture(tmp_path, unencoded, payload, run_id)["clip"]) == (
        "no clip: the by-product clip was not encoded (the status lines say why); "
        "the frame set below is the deliverable")
    assert "engine pass FAILED" not in text_of(
        page_capture(tmp_path, unencoded, {}, run_id)["card"])


# -- the page's status log is the whole event log --------------------------

def test_the_run_payload_carries_the_whole_event_log(client, tmp_path):
    """/runs/{id} used to carry events[-20:]: a three- or four-camera
    frames run (two "rendering" lines per camera plus the capture,
    closure, encoding and overlay lines) lost its first status lines
    from the page silently while status.json kept them all. The payload
    now carries every event, equal to what status.json holds."""
    from webapp.runs import RunState

    run = RunState(run_id="abcdef123456")
    run.out_dir = str(tmp_path / "abcdef123456")
    Path(run.out_dir).mkdir()
    for index in range(24):
        run.push("rendering", f"line {index}")
    run.push("done", "line 24")
    assert len(run.events) == 25
    assert run.as_dict()["events"] == run.events
    assert [e["detail"] for e in run.as_dict()["events"]][:3] == [
        "line 0", "line 1", "line 2"]
    log = json.loads((Path(run.out_dir) / "status.json").read_text(encoding="utf-8"))
    assert log["events"] == run.as_dict()["events"]
    # Through HTTP, the same 25 lines in order.
    manager.runs[run.run_id] = run
    try:
        state = client.get(f"/runs/{run.run_id}").json()
    finally:
        manager.runs.pop(run.run_id, None)
    assert len(state["events"]) == 25
    assert [e["detail"] for e in state["events"]] == [f"line {i}" for i in range(25)]


# -- the review table shows the cameras' keyframed moves -------------------

def test_the_review_table_shows_each_camera_s_keyframed_moves(tmp_path):
    """/compile sends each camera's ``moves`` (the keyframes the pose
    track interpolates: data inside the camera record, digest-relevant)
    and their recorded provenance (``moves_source`` / ``moves_from``,
    one for the whole list). cameraMovesHtml renders one row per
    keyframe after the fields -- its place, the instant and every keyed
    field as an INPUT with its unit -- and the source column prints the
    list's recorded source word in that source's own colour, or, when
    the spec recorded none, "spec data (no recorded source)" in the
    default colour: the rows used to say "keyframe" in the user's green
    although CameraSpec.moves recorded no source at all. renderSpec
    appends them; a camera without moves gets no row; the CLI table
    prints the same source word."""
    import re

    from tests.test_camera_poses import explicit_camera_with_moves
    from webapp.server import _spec_payload

    spec = compile_prompt(DEMO)
    spec.cameras.append(explicit_camera_with_moves())
    payload = _spec_payload(spec)
    assert payload["cameras"][0]["moves"] == []
    assert payload["cameras"][1]["moves"] == [
        {"t_s": 0.0, "position_north_m": 0.0, "focal_length_mm": 35.0},
        {"t_s": 10.0, "position_north_m": 2000.0, "focal_length_mm": 85.0}]
    assert payload["cameras"][1]["moves_source"] is None
    assert payload["cameras"][1]["moves_from"] is None
    rows = page_capture(tmp_path, {}, {}, "r", cameras=payload["cameras"])["moves"]
    assert rows[0] == ""
    assert rows[1].count('<tr class="move">') == 2
    # No recorded source: said so, in the default colour, never green.
    assert rows[1].count('<td class="src-default" data-src="cameras[1].moves">'
                         'spec data (no recorded source)</td>') == 2
    assert "src-user" not in rows[1] and ">keyframe<" not in rows[1]
    words = text_of(rows[1])
    assert ("move 1 of 2 t_s = s, position_north_m = m, focal_length_mm = mm "
            "spec data (no recorded source) keyframe 1 of 2 (spec data, "
            "digest-relevant): the pose track interpolates linearly to the "
            "next keyframe and holds past the last") in words
    assert "move 2 of 2 t_s = s, position_north_m = m, focal_length_mm = mm" in words
    # Every value is an input that writes back into dict.cameras[1].moves[k].
    inputs = re.findall(r'<input data-name="([^"]+)" data-src-key="([^"]+)" '
                        r'data-camera="(\d+)" data-move="(\d+)" '
                        r'data-field="([^"]+)" value="([^"]*)">', rows[1])
    assert inputs == [
        ("cameras[1].moves[0].t_s", "cameras[1].moves", "1", "0", "t_s", "0"),
        ("cameras[1].moves[0].position_north_m", "cameras[1].moves", "1", "0",
         "position_north_m", "0"),
        ("cameras[1].moves[0].focal_length_mm", "cameras[1].moves", "1", "0",
         "focal_length_mm", "35"),
        ("cameras[1].moves[1].t_s", "cameras[1].moves", "1", "1", "t_s", "10"),
        ("cameras[1].moves[1].position_north_m", "cameras[1].moves", "1", "1",
         "position_north_m", "2000"),
        ("cameras[1].moves[1].focal_length_mm", "cameras[1].moves", "1", "1",
         "focal_length_mm", "85")]
    # The units are the camera's own field units, never guessed.
    units = {f["name"]: f["unit"] for f in payload["cameras"][1]["fields"]}
    assert units["position_north_m"] == "m" and units["focal_length_mm"] == "mm"
    assert "position_north_m = <input" in rows[1] and "> m, focal_length_mm" in rows[1]
    assert "no recorded source" in spec.render_table()
    # A recorded provenance: the source word in its own colour, the note
    # before the keyframe words -- on the page and in the CLI table.
    spec.cameras[1].set_moves(spec.cameras[1].moves,
                              frm="stated: dolly north 0 to 2000 m, 35 to 85 mm")
    payload = _spec_payload(spec)
    assert payload["cameras"][1]["moves_source"] == "user"
    assert payload["cameras"][1]["moves_from"] == "stated: dolly north 0 to 2000 m, 35 to 85 mm"
    rows = page_capture(tmp_path, {}, {}, "r", cameras=payload["cameras"])["moves"]
    assert rows[1].count('<td class="src-user" data-src="cameras[1].moves">user</td>') == 2
    assert "no recorded source" not in rows[1]
    assert ("user stated: dolly north 0 to 2000 m, 35 to 85 mm — keyframe 1 of 2"
            in text_of(rows[1]).replace("&mdash;", "—"))
    table = spec.render_table()
    assert "no recorded source" not in table
    assert re.search(r"moves\s+2 keyframes\s+user\s+stated: dolly north 0 to "
                     r"2000 m, 35 to 85 mm: t=0.0s; t=10.0s", table), table
    # renderSpec appends the rows after each camera's field rows.
    page = STATIC_INDEX.read_text(encoding="utf-8")
    render_spec = re.search(r"function renderSpec\(payload\) \{.*?\n\}\n", page, re.S).group(0)
    assert 'body.insertAdjacentHTML("beforeend", cameraMovesHtml(cam));' in render_spec
    assert render_spec.index("for (const f of cam.fields)") \
        < render_spec.index("cameraMovesHtml(cam)")


def test_keyframes_are_edited_in_the_table_and_written_back(tmp_path):
    """The DOM: renderSpec draws the dolly's two keyframe rows; editing
    one keyframe's focal length repaints EVERY source cell of that
    list "user (edited)" (one decision, one provenance) and
    editedSpecDict writes the value into dict.cameras[1].moves[1] with
    the list's provenance recorded as the user's edit -- and /run's own
    parser (ScenarioSpec.from_dict) accepts that dict, keyframe and
    provenance intact, while a source word outside Source is refused
    by name. The untouched camera and keyframe are unchanged."""
    from core.scenario.spec import ScenarioSpec
    from tests.test_camera_poses import explicit_camera_with_moves
    from webapp.server import _spec_payload

    spec = compile_prompt(DEMO)
    spec.cameras.append(explicit_camera_with_moves())
    payload = {"compiler": "regex", "model": None, "spec": _spec_payload(spec),
               "validation": {"ok": True, "warnings": [], "violations": []}}
    snaps = page_dom(tmp_path, {}, [
        {"do": "renderSpec", "payload": payload},
        {"do": "editedSpecDict"},
        {"do": "setInput", "name": "cameras[1].moves[1].focal_length_mm",
         "value": "70"},
        {"do": "editedSpecDict"},
    ])
    table = snaps[0]["specTable"]
    assert table.count('<tr class="move">') == 2
    assert table.count('data-src="cameras[1].moves">spec data (no recorded source)') == 2
    # Untouched: the dict is the compiled one, provenance unrecorded.
    untouched = snaps[1]["dict"]["cameras"][1]
    assert untouched["moves"] == spec.cameras[1].moves
    assert untouched["moves_source"] is None and untouched["moves_from"] is None
    assert snaps[2]["sourceCells"] == [
        '<td class="src-edited" data-src="cameras[1].moves">user (edited)</td>'] * 2
    edited = snaps[3]["dict"]
    dolly = edited["cameras"][1]
    assert dolly["moves"] == [
        {"t_s": 0.0, "position_north_m": 0.0, "focal_length_mm": 35.0},
        {"t_s": 10.0, "position_north_m": 2000.0, "focal_length_mm": 70}]
    assert dolly["moves_source"] == "user"
    assert dolly["moves_from"] == "edited in the web UI"
    assert edited["cameras"][0]["moves"] == [] and "moves_source" not in edited["cameras"][0]
    reparsed = ScenarioSpec.from_dict(edited)
    assert reparsed.cameras[1].moves[1]["focal_length_mm"] == 70
    assert reparsed.cameras[1].moves_source == "user"
    assert reparsed.cameras[1].moves_from == "edited in the web UI"
    assert reparsed.digest() != spec.digest()
    assert reparsed.to_dict()["cameras"][1]["moves_source"] == "user"
    bad = json.loads(json.dumps(edited))
    bad["cameras"][1]["moves_source"] = "planner"
    with pytest.raises(ValueError, match="moves_source.*'planner'"):
        ScenarioSpec.from_dict(bad)


# -- a finished run outlives the server process ---------------------------

def recovered(run_id):
    """A fresh manager over the same runs root: what a restarted server
    would reconstruct for this run."""
    from webapp.runs import RunManager

    fresh = RunManager(out_root=manager.out_root)
    run = fresh.get(run_id)
    return run.as_dict() if run is not None else None


def test_a_finished_headless_run_survives_a_server_restart(captured, client,
                                                            monkeypatch):
    """Recovery is keyed on provenance.json and status.json, not on a
    clip: a headless run comes back "done" with the SAME capture summary
    (rebuilt from the manifest, verify.json, capture/run.json and
    closure.json), its render word, its engine reason and its whole
    event log, plus one "recovered" event. Through HTTP, after the
    manager forgets everything, /runs/{id} and /files still answer."""
    run_id, state = captured
    assert (manager.out_root / run_id / "status.json").is_file()
    assert not (manager.out_root / run_id / "clip.mp4").exists()
    back = recovered(run_id)
    assert back is not None
    assert back["status"] == "done" and back["detail"] == state["detail"]
    assert back["capture"] == state["capture"]
    assert back["render"] == "none" and back["clip"] is None
    assert back["engine_reason"] == state["engine_reason"]
    assert back["scene"] == state["scene"]
    assert back["spec_digest"] == state["spec_digest"]
    assert back["events"][:-1] == state["events"]
    assert back["events"][-1]["status"] == "done"
    assert back["events"][-1]["detail"] == "recovered after a server restart"

    monkeypatch.setattr(manager, "runs", {})          # the restart
    reply = client.get(f"/runs/{run_id}")
    assert reply.status_code == 200
    assert reply.json()["capture"] == state["capture"]
    files = client.get(f"/runs/{run_id}/files").json()
    names = [f["name"] for f in files["files"]]
    assert "status.json" in names
    entry = next(f for f in files["files"] if f["name"] == "status.json")
    assert "status log" in entry["note"]
    log = client.get(f"/runs/{run_id}/file/status.json").json()
    assert log["status"] == "done" and log["events"] == state["events"]
    assert [d["class"] for d in files["downloads"]] == ["manifest", "verification",
                                                        "telemetry",
                                                        "everything"]


def test_a_finished_frames_run_survives_a_server_restart(frames_run,
                                                          engine_client,
                                                          monkeypatch):
    """The frames run's card comes back whole: counts, verification,
    closure, overlays, the engine passes and the by-product clip -- all
    from files the page links."""
    run_id, state = frames_run
    back = recovered(run_id)
    assert back is not None
    assert back["status"] == "done" and back["detail"] == state["detail"]
    assert back["capture"] == state["capture"]
    for key in ("render_passes", "clip", "overlays", "overlay_s_per_frame",
                "closure", "verification", "jsbsim_log", "jsbsim_model_loads"):
        assert key in back["capture"], key
    assert back["capture"]["rendered"] == 8 and back["capture"]["verified"] == 8
    assert back["capture"]["clip"]["by_product_of"] == "camera0"
    assert back["render"] == "frames"
    assert back["clip"] == str(manager.out_root / run_id / "clip.mp4")
    assert back["events"][:-1] == state["events"][-len(back["events"]) + 1:]
    monkeypatch.setattr(manager, "runs", {})
    assert engine_client.get(f"/runs/{run_id}").json()["capture"] == state["capture"]
    assert engine_client.get(f"/runs/{run_id}/frames.zip").status_code == 200


def test_a_refused_capture_survives_a_server_restart(client, monkeypatch):
    """A refused capture wrote no manifest; its refusal (constraint,
    message, value) is read back from status.json and the run is
    "failed", as it was."""
    from core.scenario.validate import Violation
    import core.capture.validate as validate_module

    monkeypatch.setattr(
        validate_module, "track_violations",
        lambda *a, **k: [Violation(
            constraint="camera.terrain_clearance", message="inside the terrain",
            actual=-3.0, limit=30.0, unit="m AGL")])
    reply = client.post("/capture", json={"spec": compile_prompt(DEMO).to_dict()})
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "failed"
    back = recovered(run_id)
    assert back["status"] == "failed" and back["detail"] == state["detail"]
    assert back["capture"] == state["capture"]
    assert back["capture"]["actual"] == -3.0


def test_an_interrupted_run_stays_absent_and_a_legacy_clip_run_recovers(tmp_path):
    """No status.json and no clip: the process died under the run and
    there is no worker to resume -- absent, which the page reports. A
    run from before status.json existed (clip.mp4 beside provenance)
    recovers as it always did. No provenance at all: absent."""
    from webapp.runs import RunManager

    root = tmp_path / "runs"
    fresh = RunManager(out_root=root)
    interrupted = root / "abc123"
    interrupted.mkdir(parents=True)
    (interrupted / "provenance.json").write_text(json.dumps(
        {"render": "none", "spec_digest": "x", "scene": {"kind": "flat"}}),
        encoding="utf-8")
    assert fresh.get("abc123") is None
    legacy = root / "def456"
    legacy.mkdir()
    (legacy / "provenance.json").write_text(json.dumps(
        {"render": "clip", "spec_digest": "y", "scene": {"kind": "flat"}}),
        encoding="utf-8")
    (legacy / "clip.mp4").write_bytes(b"mp4")
    run = fresh.get("def456")
    assert run is not None and run.status == "done"
    assert run.detail == "clip ready (recovered after a server restart)"
    assert run.clip == str(legacy / "clip.mp4") and run.render == "clip"
    assert run.capture is None
    bare = root / "0123abc"
    bare.mkdir()
    (bare / "clip.mp4").write_bytes(b"mp4")
    assert fresh.get("0123abc") is None
    assert fresh.get("../abc123") is None


def test_a_terminal_push_writes_the_status_log_before_the_status_shows(tmp_path):
    """status.json is on disk BEFORE run.status reads "done": a page
    that sees "done" and lists the files sees status.json in the list,
    and the bundle it then builds carries it."""
    from webapp.runs import RunState

    out = tmp_path / "run"
    out.mkdir()
    run = RunState(run_id="abc", out_dir=str(out))
    run.push("capture", "solving")
    assert not (out / "status.json").exists()
    seen = []
    original = run.write_status

    def spy(*args, **kwargs):
        seen.append(run.status)          # the status as it was when written
        original(*args, **kwargs)

    run.write_status = spy
    run.push("done", "no pixels")
    assert seen == ["capture"]
    log = json.loads((out / "status.json").read_text(encoding="utf-8"))
    assert log["status"] == "done" and log["detail"] == "no pixels"
    assert [e["status"] for e in log["events"]] == ["capture", "done"]
    assert log["capture_refused"] is None and log["closure_refused"] is None
    # No out_dir (a run driven directly): nothing written, nothing raised.
    RunState(run_id="def").push("done", "x")


# -- page round 3: the flight path is drawn from the file the run listed --

def refused_mid_run(client, monkeypatch):
    """A capture refused mid-run (camera.terrain_clearance, with its
    measured value): the run ends failed having written no telemetry."""
    from core.scenario.validate import Violation
    import core.capture.validate as validate_module

    monkeypatch.setattr(
        validate_module, "track_violations",
        lambda *a, **k: [Violation(
            constraint="camera.terrain_clearance",
            message="tower0: the stated placement sits inside or on the "
                    "scene's terrain (checked over the whole run window)",
            actual=-12.3, limit=30.0, unit="m AGL")])
    reply = client.post("/capture", json={"spec": compile_prompt(DEMO).to_dict()})
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "failed"
    return run_id, state


def engine_stubs_root(run_id):
    """The run directory of a run started through the engine client
    (the manager the app serves, whose out_root the fixture pinned)."""
    return manager.out_root / run_id


def test_the_flight_path_is_drawn_from_the_telemetry_file_the_run_listed(
        captured, client, frames_run, engine_client, monkeypatch, tmp_path):
    """A headless run has no out/telemetry.json (that file is the render
    flow's), so /runs/<id>/telemetry.json answers 404 -- and the page
    used to omit the flight path although capture/telemetry.json was
    listed and downloadable. telemetrySource picks the file from the
    run's OWN listing: the headless payload resolves to
    capture/telemetry.json through the whitelist route (and that route
    serves the lat/lon/altitude channels the chart draws); a frames run
    keeps the rendered flight's telemetry.json; the mid-run refusal,
    which wrote no telemetry, resolves to nothing and draws nothing."""
    run_id, state = captured
    assert client.get(f"/runs/{run_id}/telemetry.json").status_code == 404
    payload = client.get(f"/runs/{run_id}/files").json()
    names = [f["name"] for f in payload["files"]]
    assert "capture/telemetry.json" in names and "telemetry.json" not in names
    source = page_capture(tmp_path, state, payload, run_id)["telemetry"]
    assert source == {"name": "capture/telemetry.json",
                      "href": "file/capture/telemetry.json",
                      "flight": "the headless capture flight the manifest "
                                "describes"}
    served = client.get(f"/runs/{run_id}/{source['href']}")
    assert served.status_code == 200
    columns = served.json()["columns"]
    assert len(columns["lat_deg"]) == len(columns["lon_deg"]) == \
        len(columns["altitude_m"]) == len(columns["t"]) >= 2
    # A frames run keeps the rendered flight's telemetry.json (the
    # commandlet's -telemetry= recorder writes it) when it exists. The
    # engine stub records none, so the stubbed run honestly resolves to
    # the capture flight's file; once the rendered flight's file is on
    # disk (written here as the real engine would), the rendered
    # flight wins, by name, through the same whitelist route.
    frames_id, frames_state = frames_run
    frames_payload = engine_client.get(f"/runs/{frames_id}/files").json()
    assert "telemetry.json" not in [f["name"] for f in frames_payload["files"]]
    assert page_capture(tmp_path, frames_state, frames_payload,
                        frames_id)["telemetry"]["name"] == "capture/telemetry.json"
    out = engine_stubs_root(frames_id)
    (out / "telemetry.json").write_bytes(
        (out / "capture" / "telemetry.json").read_bytes())
    frames_payload = engine_client.get(f"/runs/{frames_id}/files").json()
    assert "telemetry.json" in [f["name"] for f in frames_payload["files"]]
    source = page_capture(tmp_path, frames_state, frames_payload, frames_id)["telemetry"]
    assert source == {"name": "telemetry.json", "href": "file/telemetry.json",
                      "flight": "the rendered flight"}
    assert engine_client.get(f"/runs/{frames_id}/{source['href']}").status_code == 200
    # The refusal wrote no telemetry: nothing to draw from, and the
    # page says so instead of guessing a route.
    refused_id, refused_state = refused_mid_run(client, monkeypatch)
    refused_payload = client.get(f"/runs/{refused_id}/files").json()
    assert not any(f["name"].endswith("telemetry.json") for f in refused_payload["files"])
    assert page_capture(tmp_path, refused_state, refused_payload, refused_id)["telemetry"] is None
    # No listing at all (the /files fetch failed): nothing is drawn.
    assert page_capture(tmp_path, state, {}, run_id)["telemetry"] is None


# -- page round 3: the page's DOM glue, executed -----------------------------
# poll(), renderCapture(), initFilesPanel(), initFlightPath(),
# toggleOverlays(), renderSpec() and startRun() touch the document and
# fetch, so the pure-block harness above cannot reach them and they were
# pinned only by regex on the source. tests/page_dom.js loads the page's
# OWN script over a small document (the body's markup parsed into
# elements) with fetch answered from the real TestClient payloads, runs
# the actions and returns a snapshot of the document after each.

PAGE_DOM = Path(__file__).resolve().parent / "page_dom.js"


def page_dom(tmp_path, routes, actions):
    """Run the page's glue under node over the minimal DOM: ``routes``
    maps "METHOD /path" to {"status", "body"} (or {"throw": true} for
    a dead fetch); ``actions`` is the list page_dom.js executes. Returns
    one snapshot per action."""
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the page's DOM glue needs it")
    payload = tmp_path / "page_dom_input.json"
    payload.write_text(json.dumps({"index": str(STATIC_INDEX), "routes": routes,
                                   "actions": actions}), encoding="utf-8")
    proc = subprocess.run([node, str(PAGE_DOM), str(payload)],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def run_routes(client, run_id, state=None):
    """The routes a finished run answers: /status, /runs/<id>, its
    /files listing and every file the listing carries (served from the
    TestClient, so the DOM is drawn from what the server serves)."""
    routes = {"GET /status": {"body": client.get("/status").json()}}
    routes[f"GET /runs/{run_id}"] = {
        "body": state if state is not None else client.get(f"/runs/{run_id}").json()}
    files = client.get(f"/runs/{run_id}/files").json()
    routes[f"GET /runs/{run_id}/files"] = {"body": files}
    for entry in files["files"]:
        if entry["name"].endswith(".json"):
            reply = client.get(f"/runs/{run_id}/file/{entry['name']}")
            routes[f"GET /runs/{run_id}/file/{entry['name']}"] = {
                "status": reply.status_code, "body": reply.json()}
    return routes


def test_poll_draws_the_headless_page_s_dom_from_the_run_s_payloads(
        captured, client, monkeypatch, tmp_path):
    """poll() on the live page, executed over the DOM: the status log is
    every event line; the download strip lands INSIDE the capture card
    (#captureDownloads, above the heading) and not in the files panel;
    the galleries REPLACE the card's per-camera count list; the flight
    path is drawn from capture/telemetry.json through the whitelist
    route (never /runs/<id>/telemetry.json) and its formula line names
    the file; a terminal run schedules no further poll. A run still in
    flight draws no card, no strip, no files and re-polls in 2 s; an
    unrecoverable run (404) says so. A mid-run refusal reaches the card
    on the live page with its constraint and value, the strip with
    'everything', and draws no flight path."""
    run_id, state = captured
    routes = run_routes(client, run_id, state)
    payload = routes[f"GET /runs/{run_id}/files"]["body"]
    pure = page_capture(tmp_path, state, payload, run_id)
    snap = page_dom(tmp_path, routes, [{"do": "poll", "runId": run_id}])[0]
    for event in state["events"]:
        assert event["status"] in snap["status"] and event["detail"] in snap["status"]
    assert snap["timeouts"] == []
    # The strip: in the card, above its heading, exactly the pure builder's.
    card = snap["captureArea"]
    assert snap["captureDownloads"] == pure["strip"]
    assert card.index('<div class="dlstrip">') < card.index("capture geometry")
    assert "dlstrip" not in snap["filesArea"]
    assert text_of(snap["filesArea"]).startswith("files from this run download all (.zip)")
    # The galleries replaced the count list.
    assert snap["captureGalleries"] == "".join(pure["galleries"])
    assert "<ul>" not in snap["captureGalleries"]
    assert 'data-kind="previews"' in card and "<li>" not in snap["captureGalleries"]
    # The flight path, from the listed file, named.
    assert f"GET /runs/{run_id}/file/capture/telemetry.json" in snap["fetches"]
    assert f"GET /runs/{run_id}/telemetry.json" not in snap["fetches"]
    path = text_of(snap["pathArea"])
    assert path.startswith("flight path — top-down ground track, north up")
    telemetry = routes[f"GET /runs/{run_id}/file/capture/telemetry.json"]["body"]
    samples = len(telemetry["columns"]["t"])
    assert (f"ground track = capture/telemetry.json's own lat/lon channels "
            f"({samples} samples at {telemetry['interval_s']} s; the headless "
            f"capture flight the manifest describes), projected to metres") in path
    assert 'id="pathCanvas"' in snap["pathArea"] and 'id="profileCanvas"' in snap["pathArea"]
    assert text_of(snap["clipArea"]).startswith(
        "scene: flat (test) no clip: this was a headless run (the geometry below "
        "is the deliverable; no engine pass ran) flight path")

    # Still in flight: nothing drawn, another poll in 2 s.
    live = dict(state, status="capture", detail="flying the spec headlessly")
    live_routes = dict(routes, **{f"GET /runs/{run_id}": {"body": live}})
    snap = page_dom(tmp_path, live_routes, [{"do": "poll", "runId": run_id}])[0]
    assert snap["captureArea"] is None and snap["clipArea"] == ""
    assert snap["timeouts"] == [2000]
    assert f"GET /runs/{run_id}/files" not in snap["fetches"]
    assert "flying the spec headlessly" in snap["status"]
    # Not recoverable: said, and no further poll.
    gone = {f"GET /runs/{run_id}": {"status": 404, "body": {"error": "no such run"}}}
    snap = page_dom(tmp_path, gone, [{"do": "poll", "runId": run_id}])[0]
    assert snap["status"] == (f"run {run_id} is not recoverable (interrupted, or "
                              f"its files were removed)")
    assert snap["timeouts"] == []

    # The refusal path, on the live page.
    refused_id, refused_state = refused_mid_run(client, monkeypatch)
    routes = run_routes(client, refused_id, refused_state)
    snap = page_dom(tmp_path, routes, [{"do": "poll", "runId": refused_id}])[0]
    card = text_of(snap["captureArea"])
    assert "capture refused — [camera.terrain_clearance] tower0:" in card
    assert "(measured -12.3 m AGL, limit 30 m AGL)" in card
    assert links_of(snap["captureDownloads"], "everything") == [f"/runs/{refused_id}/bundle.zip"]
    assert snap["captureGalleries"] is None       # the refused card has no galleries holder
    assert text_of(snap["pathArea"]) == ("flight path omitted: this run listed no "
                                         "telemetry file (nothing was flown to record)")
    assert "pathCanvas" not in snap["pathArea"]
    assert f'href="/runs/{refused_id}/file/status.json"' in snap["filesArea"]


def test_toggle_overlays_swaps_every_frame_s_src_and_href_both_ways(
        frames_run, engine_client, tmp_path):
    """The frames run on the live page: poll() draws both cameras'
    galleries with every rendered frame; toggleOverlays(camera, on)
    swaps each of THAT camera's frame thumbnails to its overlay file
    and the anchor's href with it, leaves the other camera alone, and
    swaps back."""
    run_id, state = frames_run
    routes = run_routes(engine_client, run_id, state)
    snaps = page_dom(tmp_path, routes, [
        {"do": "poll", "runId": run_id},
        {"do": "toggleOverlays", "camera": "camera0", "on": True},
        {"do": "toggleOverlays", "camera": "camera0", "on": False},
        {"do": "toggleOverlays", "camera": "tower0", "on": True},
    ])
    frame = lambda cam, i: f"/runs/{run_id}/file/capture/frames/{cam}/{i:04d}.png"
    overlay = lambda cam, i: f"/runs/{run_id}/file/capture/overlays/{cam}/{i:04d}.png"
    before = snaps[0]["frames"]
    assert [(f["camera"], f["src"], f["href"]) for f in before] == [
        (cam, frame(cam, i), frame(cam, i))
        for cam in ("camera0", "tower0") for i in range(4)]
    assert "8 scheduled, 8 rendered, 8 verified" in text_of(snaps[0]["captureArea"])
    assert links_of(snaps[0]["captureDownloads"], "frames") == [f"/runs/{run_id}/frames.zip"]
    on = snaps[1]["frames"]
    assert [(f["src"], f["href"]) for f in on if f["camera"] == "camera0"] == [
        (overlay("camera0", i), overlay("camera0", i)) for i in range(4)]
    assert [(f["src"], f["href"]) for f in on if f["camera"] == "tower0"] == [
        (frame("tower0", i), frame("tower0", i)) for i in range(4)]
    assert snaps[2]["frames"] == before
    tower = snaps[3]["frames"]
    assert [(f["src"], f["href"]) for f in tower if f["camera"] == "tower0"] == [
        (overlay("tower0", i), overlay("tower0", i)) for i in range(4)]
    assert [(f["src"], f["href"]) for f in tower if f["camera"] == "camera0"] == [
        (frame("camera0", i), frame("camera0", i)) for i in range(4)]
    # The clip is a by-product of camera 0: the video sits in the clip area.
    assert f'<video id="clipVideo" controls src="/runs/{run_id}/clip.mp4">' in snaps[0]["clipArea"]


# -- page round 3: one refusal shape for the whole page --------------------

def run_refusal_payloads(client, monkeypatch):
    """Every named 409 /run can answer, collected LIVE: ue.platform (this
    OS has no engine), preview.scale (0, and 3 on 1280x720),
    aircraft.mesh (the f15, with the platform gate held open),
    render.host_parity (a turbulent spec asked for frames), and the
    manager's own render.choice and run.busy refusals."""
    import core.util.platform as plat
    from webapp.runs import RunState

    spec = compile_prompt(DEMO)
    out = {}
    monkeypatch.setattr(plat, "ue_available", lambda: False)
    monkeypatch.setattr(plat, "ue_unavailable_reason",
                        lambda: "no engine on this OS: the render half needs "
                                "macOS, or Windows with Unreal Engine 5.5 and "
                                "the FlightSimBridge built")
    reply = client.post("/run", json={"spec": spec.to_dict(), "render": "frames"})
    assert reply.status_code == 409
    out["ue.platform"] = reply.json()
    for scale in (0, 3):
        reply = client.post("/run", json={"spec": spec.to_dict(), "render": "none",
                                          "preview_scale": scale})
        assert reply.status_code == 409
        out[f"preview.scale {scale}"] = reply.json()
    monkeypatch.setattr(plat, "ue_available", lambda: True)
    f15 = compile_prompt("fly the f15 at 5000 m and 350 kt for 3 seconds with "
                         "a chase camera capturing 4 images")
    reply = client.post("/run", json={"spec": f15.to_dict(), "render": "frames"})
    assert reply.status_code == 409
    out["aircraft.mesh"] = reply.json()
    turbulent = compile_prompt("fly the 747 at 5000 ft over the prairie in "
                               "moderate turbulence for 3 seconds with a "
                               "chase camera capturing 4 images")
    reply = client.post("/run", json={"spec": turbulent.to_dict(),
                                      "render": "frames"})
    assert reply.status_code == 409
    out["render.host_parity"] = reply.json()
    out["render.choice"] = manager.start(spec, {}, render="video")
    active = RunState(run_id="abc123def456")
    active.status = "rendering"
    monkeypatch.setitem(manager.runs, "abc123def456", active)
    monkeypatch.setattr(manager, "_active", "abc123def456")
    out["run.busy"] = manager.start(spec, {}, render="frames")
    out["run.busy capture"] = manager.start_capture(spec, {})
    return out


def test_every_run_refusal_reads_in_the_verdict_s_one_shape(
        client, monkeypatch, tmp_path):
    """startRun's generic branch printed 'refused [ue.platform]: REFUSED
    ue.platform: <six lines> -- <reason>' -- the constraint twice, the
    CLI's paragraph, and never the choice that was refused. Every 409
    now carries the validation verdict's keys (constraint, message,
    actual, limit, unit) and the page renders each with the ONE
    refusalWords(): '[constraint] message (requested X, limit Y)'. The
    words are pinned per payload, from the server's live answers."""
    payloads = run_refusal_payloads(client, monkeypatch)
    for name, payload in payloads.items():
        for key in ("refused", "constraint", "message", "actual", "limit", "unit"):
            assert key in payload, (name, key)
    assert payloads["ue.platform"]["actual"] == "frames"
    assert payloads["ue.platform"]["limit"] == "none (Headless)"
    assert payloads["ue.platform"]["render"] == "frames"        # its own key stays
    assert payloads["ue.platform"]["refused"].startswith("REFUSED ue.platform")
    assert payloads["preview.scale 3"]["actual"] == 3
    assert payloads["preview.scale 3"]["limit"] == "divides 1280x720"
    assert payloads["preview.scale 0"]["limit"] == "a positive whole number"
    assert payloads["aircraft.mesh"]["actual"] == "f15"
    assert payloads["aircraft.mesh"]["limit"] == "A320, B747, DHC6, c172p"
    assert payloads["render.host_parity"]["actual"] == "frames"
    assert payloads["render.choice"]["actual"] == "video"
    assert payloads["run.busy"]["actual"] == "abc123def456 rendering"
    lines = page_capture(tmp_path, {}, {}, "r", refusals=[
        {"payload": p, "verb": "requested"} for p in payloads.values()])["refusals"]
    words = dict(zip(payloads, (text_of(line) for line in lines)))
    assert words["ue.platform"] == (
        "[ue.platform] no engine on this OS: the render half needs macOS, or "
        "Windows with Unreal Engine 5.5 and the FlightSimBridge built "
        "(requested frames, limit none (Headless))")
    assert words["preview.scale 3"] == (
        "[preview.scale] preview.scale: 3 does not divide 1280x720 exactly "
        "(426.67x240); the preview draws at 1/N of the record's resolution "
        "and never floors a size (camera camera0) (requested 3, limit divides "
        "1280x720)")
    assert words["preview.scale 0"].endswith(
        "(requested 0, limit a positive whole number)")
    assert words["aircraft.mesh"] == (
        "[aircraft.mesh] the f15 has real flight physics but no licensed 3-D "
        "model is configured for it, and placeholder airframes never render. "
        "Airframes with a model this machine can build: A320, B747, DHC6, "
        "c172p. (requested f15, limit A320, B747, DHC6, c172p)")
    assert words["render.host_parity"].startswith(
        "[render.host_parity] turbulence 'moderate': same-seed host parity")
    assert words["render.host_parity"].endswith(
        "(requested frames, limit clip or none (the choices whose labels need "
        "no host parity))")
    assert words["render.choice"] == (
        "[render.choice] render must be one of frames, clip, none (requested "
        "video, limit frames, clip, none)")
    assert words["run.busy"] == (
        "[run.busy] a run is already rendering (abc123def456); one editor "
        "instance at a time (requested abc123def456 rendering, limit one "
        "editor instance at a time)")
    # Each constraint is named exactly once, and the CLI's paragraph
    # never reaches the page.
    for name, line in words.items():
        constraint = payloads[name]["constraint"]
        assert line.count(f"[{constraint}]") == 1, line
        assert "REFUSED ue.platform" not in line
    # The verdict's own lines go through the same function: a Violation
    # with a unit prints it on both numbers, one without a value prints
    # no clause.
    verdict = page_capture(tmp_path, {}, {}, "r", refusals=[
        {"payload": {"constraint": "envelope.ceiling", "message": "too high",
                     "actual": 50000, "limit": 45000, "unit": "ft"},
         "verb": "requested"},
        {"payload": {"constraint": "camera.schedule", "message": "4 over 3 s",
                     "actual": None, "limit": None, "unit": None},
         "verb": "measured"}])["refusals"]
    assert text_of(verdict[0]) == ("[envelope.ceiling] too high (requested "
                                   "50000 ft, limit 45000 ft)")
    assert text_of(verdict[1]) == "[camera.schedule] 4 over 3 s"


def test_the_live_page_prints_a_run_refusal_in_the_one_shape(
        client, monkeypatch, tmp_path):
    """The DOM: the review table drawn from a real /compile payload, Run
    pressed, the server answering 409 ue.platform (this OS) -- the
    status reads 'refused — [ue.platform] <reason> (requested frames,
    limit none (Headless))', the constraint once, no paragraph; the
    run area is shown and no run is polled. The pre-run verdict, drawn
    through the same function, prints a violation's unit on both
    numbers."""
    compiled = client.post("/compile", json={"prompt": DEMO,
                                             "compiler": "regex"}).json()
    payloads = run_refusal_payloads(client, monkeypatch)
    routes = {"GET /status": {"body": client.get("/status").json()},
              "POST /run": {"status": 409, "body": payloads["ue.platform"]}}
    snaps = page_dom(tmp_path, routes, [
        {"do": "renderSpec", "payload": compiled},
        {"do": "startRun", "endpoint": "/run"},
        {"do": "renderVerdict", "payload": {
            "ok": False, "warnings": [], "violations": [
                {"constraint": "envelope.ceiling", "message": "too high",
                 "actual": 50000, "limit": 45000, "unit": "ft"}]}},
    ])
    status = text_of(snaps[1]["statusHtml"])
    assert status == (
        "refused — [ue.platform] no engine on this OS: the render half needs "
        "macOS, or Windows with Unreal Engine 5.5 and the FlightSimBridge "
        "built (requested frames, limit none (Headless))")
    assert status.count("ue.platform") == 1
    assert "REFUSED" not in status
    assert snaps[1]["runAreaDisplay"] == ""
    assert snaps[1]["timeouts"] == [] and "GET /runs/" not in "".join(snaps[1]["fetches"])
    import html

    assert html.unescape(text_of(snaps[2]["verdict"])) == (
        "REFUSED — by name: [envelope.ceiling] too high (requested 50000 ft, "
        "limit 45000 ft)")
    assert snaps[2]["runDisabled"] is True
    # The busy refusal, the same way.
    routes["POST /run"] = {"status": 409, "body": payloads["run.busy"]}
    snap = page_dom(tmp_path, routes, [
        {"do": "renderSpec", "payload": compiled},
        {"do": "startRun", "endpoint": "/run"}])[1]
    assert text_of(snap["statusHtml"]) == (
        "refused — [run.busy] a run is already rendering (abc123def456); one "
        "editor instance at a time (requested abc123def456 rendering, limit "
        "one editor instance at a time)")


# -- page round 3: the gallery shows WHICH frames failed engine parity -----

@pytest.fixture()
def drifting_run(engine_client, engine_stubs):
    """A two-camera frames run through POST /run whose engine placed
    frame 1 of EACH camera 20 cm east of the solved pose: every PNG
    exists, the counts are right, and engine parity fails the run by
    name -- 8 rendered, 6 verified."""
    from webapp.runs import RunManager

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
    reply = engine_client.post("/run", json={"spec": two_camera_spec().to_dict(),
                                             "render": "frames"})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(engine_client, run_id)
    assert state["status"] == "failed", state["detail"]
    return run_id, state


def test_the_gallery_captions_each_frame_that_failed_engine_parity(
        drifting_run, frames_run, captured, client, engine_client, tmp_path):
    """engine_parity's data recorded per-camera counts and one worst
    frame, so a reader could not see from the thumbnails which frames
    the verifier rejected. verify.json now carries one entry per graded
    frame (index, t_s, ok, the measured gaps, that frame's own problem
    sentences); /files' galleries attach it to each rendered frame; and
    the gallery captions a failed frame "parity FAIL: <the verifier's
    sentence>" in the FAIL colour with a red outline, the heading
    counting them -- the number of FAIL captions equals rendered minus
    verified. An honest pass and a headless run carry no such words."""
    import re

    run_id, state = drifting_run
    assert state["capture"]["rendered"] == 8 and state["capture"]["verified"] == 6
    verdict = engine_client.get(f"/runs/{run_id}/file/capture/verify.json").json()
    parity = next(c for c in verdict["checks"] if c["name"] == "engine_parity")
    frames = parity["data"]["frames"]
    assert sorted(frames) == ["camera0", "tower0"]
    for cam, entries in frames.items():
        assert [e["index"] for e in entries] == [0, 1, 2, 3]
        assert [e["ok"] for e in entries] == [True, False, True, True]
        assert entries[1]["problems"] == [
            "applied position 0.200 m from the solved pose (tol 0.1)"]
        assert entries[1]["gaps"]["position_m"] == pytest.approx(0.2)
        assert all(e["problems"] == [] for e in entries if e["ok"])
        assert all(e["gaps"]["position_m"] == pytest.approx(0.0)
                   for e in entries if e["ok"])
    payload = engine_client.get(f"/runs/{run_id}/files").json()
    failed = [(g["camera_id"], f["index"]) for g in payload["galleries"]
              for f in g["frames"] if f["parity"]["ok"] is False]
    assert failed == [("camera0", 1), ("tower0", 1)]
    assert len(failed) == state["capture"]["rendered"] - state["capture"]["verified"]
    assert payload["galleries"][0]["frames"][1]["parity"]["problems"] == [
        "applied position 0.200 m from the solved pose (tol 0.1)"]
    html = page_capture(tmp_path, state, payload, run_id)
    assert len(html["galleries"]) == 2
    captions = []
    for gallery in html["galleries"]:
        cam = re.match(r'<div class="gallery"><b>([^<]+)</b>', gallery).group(1)
        words = text_of(gallery)
        assert (f"{cam} : 4 scheduled, 4 rendered, 3 verified — showing 4 of 4 "
                f"rendered frame(s) — 1 of them failed engine parity (captioned "
                f"and outlined below)") in words
        assert gallery.count('<figure class="thumb parity-fail">') == 1
        assert gallery.count('<figure class="thumb">') == 7      # 3 frames + 4 previews
        caption = re.search(r'<figcaption class="dim">#1 t=([\d.]+) s <span '
                            r'class="verdict-refused">— parity FAIL: ([^<]+)'
                            r'</span></figcaption>', gallery)
        assert caption, gallery
        captions.append(caption.group(2))
        t1 = payload["galleries"][0]["frames"][1]["t_s"]
        assert caption.group(1) == f"{t1:.3f}"
        # The failed thumbnail is the frame it says it is.
        figure = re.search(r'<figure class="thumb parity-fail">.*?</figure>', gallery).group(0)
        assert f"/runs/{run_id}/file/capture/frames/{cam}/0001.png" in figure
    assert captions == ["applied position 0.200 m from the solved pose (tol 0.1)"] * 2
    assert "".join(html["galleries"]).count("parity FAIL") == 2
    assert "8 scheduled, 8 rendered, 6 verified" in text_of(html["card"])
    # The honest pass: every frame verified, no FAIL caption, no outline.
    honest_id, honest_state = frames_run
    honest_payload = engine_client.get(f"/runs/{honest_id}/files").json()
    assert all(f["parity"]["ok"] is True and f["parity"]["problems"] == []
               for g in honest_payload["galleries"] for f in g["frames"])
    honest_html = "".join(page_capture(tmp_path, honest_state, honest_payload,
                                       honest_id)["galleries"])
    assert "parity FAIL" not in honest_html and "parity-fail" not in honest_html
    assert "failed engine parity" not in honest_html
    # Headless: nothing was graded, so verify.json records no frame and
    # the previews carry no verdict.
    headless_id, headless_state = captured
    headless = client.get(f"/runs/{headless_id}/file/capture/verify.json").json()
    awaiting = next(c for c in headless["checks"] if c["name"] == "engine_parity")
    assert awaiting["ok"] is None and awaiting["data"]["frames"] == {}
    headless_payload = client.get(f"/runs/{headless_id}/files").json()
    assert all("parity" not in p for g in headless_payload["galleries"]
               for p in g["previews"])
    assert "parity" not in "".join(page_capture(tmp_path, headless_state,
                                                headless_payload, headless_id)["galleries"])


# -- page round 3: the review table escapes what it interpolates ----------

def test_the_review_table_escapes_values_and_provenance_notes(client, tmp_path):
    """renderSpec wrote `value="${value}"` and provenanceNote's quoted
    phrase -- the user's own prompt words, as the model quotes them --
    straight into innerHTML, so a prompt with a double quote or "<"
    broke the input attribute or injected markup into the table the
    user is asked to check before running. Every interpolation now goes
    through esc(): the DOM shows the phrase as text, the input's value
    attribute carries the quote escaped, and editedSpecDict reads the
    value back intact (round trip), an edit with a quote included."""
    compiled = client.post("/compile", json={"prompt": DEMO,
                                             "compiler": "regex"}).json()
    spec = compiled["spec"]
    altitude = next(f for f in spec["fields"] if f["name"] == "altitude")
    altitude["source"] = "model"
    altitude["from"] = 'say "hi" <b>x</b>'
    altitude["std"] = 'std <i>note</i>'
    camera_id = next(f for f in spec["cameras"][0]["fields"]
                     if f["name"] == "camera_id")
    camera_id["value"] = 'tow"er<0>'
    spec["cameras"][0]["camera_id"] = 'tow"er<0>'
    spec["dict"]["cameras"][0]["camera_id"]["value"] = 'tow"er<0>'
    aircraft = next(f for f in spec["fields"] if f["name"] == "aircraft")
    aircraft["value"] = 'B7"47<x>'
    spec["dict"]["aircraft"]["aircraft"]["value"] = 'B7"47<x>'
    spec["notes"] = ['a <note> "quoted"']
    compiled["validation"]["warnings"] = ['<w>arning "one"']
    compiled["llm_note"] = 'fell <back> "here"'
    snaps = page_dom(tmp_path, {}, [
        {"do": "renderSpec", "payload": compiled},
        {"do": "editedSpecDict"},
        {"do": "setInput", "name": "cameras[0].camera_id", "value": 'new"<id>'},
        {"do": "editedSpecDict"},
    ])
    table = snaps[0]["specTable"]
    assert "<b>x</b>" not in table and "<i>note</i>" not in table
    assert ('interpreting &ldquo;say &quot;hi&quot; &lt;b&gt;x&lt;/b&gt;&rdquo;'
            in table)
    assert "&mdash; std &lt;i&gt;note&lt;/i&gt;" in table
    assert ('<input data-name="cameras[0].camera_id" data-camera="0" '
            'data-field="camera_id" value="tow&quot;er&lt;0&gt;">') in table
    assert '<b>camera[0] tow&quot;er&lt;0&gt;</b>' in table
    assert '<input data-name="aircraft" value="B7&quot;47&lt;x&gt;">' in table
    assert '<x>' not in table
    assert "<note>" not in table
    notes = snaps[0]["statusHtml"]      # the status is untouched by renderSpec
    assert notes == ""
    page = snaps[0]
    assert "&lt;w&gt;arning &quot;one&quot;" in page["verdict"] and "<w>" not in page["verdict"]
    # The value survives the round trip through the input attribute.
    assert snaps[1]["dict"]["cameras"][0]["camera_id"]["value"] == 'tow"er<0>'
    assert snaps[1]["dict"]["aircraft"]["aircraft"]["value"] == 'B7"47<x>'
    assert snaps[1]["dict"]["aircraft"]["aircraft"]["source"] == \
        spec["dict"]["aircraft"]["aircraft"]["source"]
    assert snaps[1]["dict"]["cameras"][0]["camera_id"]["source"] != "user (edited)"
    edited = snaps[3]["dict"]["cameras"][0]["camera_id"]
    assert edited == {**snaps[1]["dict"]["cameras"][0]["camera_id"],
                      "value": 'new"<id>', "source": "user",
                      "from": "edited in the web UI"}
    assert snaps[2]["sourceCell"] == (
        '<td class="src-edited" data-src="cameras[0].camera_id">user (edited)</td>')


# -- page round 3: a missing file listing is said by name ------------------

def test_a_failed_file_listing_is_said_by_name_in_the_card(
        captured, client, tmp_path):
    """initFilesPanel returned silently when /files was not ok, threw,
    or listed nothing: the card kept its bare per-camera count list
    with no strip and no word saying why. On the DOM: an HTTP 500, a
    dead fetch and an empty list each print the failure by name where
    the strip would be (inside the card), the files panel stays empty,
    the count list stays (the honest state), and the flight path says
    the listing did not arrive instead of claiming no telemetry was
    written."""
    run_id, state = captured
    routes = run_routes(client, run_id, state)
    files_route = f"GET /runs/{run_id}/files"
    cases = {
        "http": ({"status": 500, "body": {"error": "boom"}},
                 f"files: /runs/{run_id}/files answered HTTP 500 — downloads "
                 f"and galleries unavailable"),
        "dead": ({"throw": True},
                 f"files: /runs/{run_id}/files could not be fetched (TypeError: "
                 f"fetch failed: GET /runs/{run_id}/files) — downloads and "
                 f"galleries unavailable"),
        "empty": ({"body": {"files": [], "downloads": [], "galleries": []}},
                  f"files: this run listed no files (/runs/{run_id}/files "
                  f"answered an empty list) — nothing to download, no gallery "
                  f"to show"),
    }
    for name, (route, words) in cases.items():
        snap = page_dom(tmp_path, dict(routes, **{files_route: route}),
                        [{"do": "poll", "runId": run_id}])[0]
        assert snap["captureDownloads"] == f'<div class="verdict-refused">{words}</div>', name
        assert snap["filesArea"] == "", name
        assert "dlstrip" not in snap["captureArea"], name
        # The count list is the card's honest state until a listing arrives.
        assert "<ul><li><b>camera0</b>: 4 scheduled, 0 rendered (headless), " \
               "previews only</li></ul>" in snap["captureGalleries"], name
        path = text_of(snap["pathArea"])
        if name == "empty":
            assert path == ("flight path omitted: this run listed no telemetry "
                            "file (nothing was flown to record)"), name
        else:
            assert path == ("flight path omitted: the file listing did not arrive "
                            "(the files panel says why), so no telemetry file "
                            "can be named"), name
        assert "pathCanvas" not in snap["pathArea"], name
    # With the real listing the strip is there and nothing is refused.
    snap = page_dom(tmp_path, routes, [{"do": "poll", "runId": run_id}])[0]
    assert "verdict-refused" not in snap["captureDownloads"]
    assert links_of(snap["captureDownloads"], "everything") == [f"/runs/{run_id}/bundle.zip"]
