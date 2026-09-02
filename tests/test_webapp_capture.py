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
                     "cross_view_consistency", "count_exactness"]

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
