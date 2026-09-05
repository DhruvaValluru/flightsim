"""Package C: the closure assertion reaches the rendered artefact.

The render host has no controller, so every clip is open loop and the
closure assertion -- "a run that did not reach what it was commanded is
not evidence of anything" -- never ran on the artefact a person looks
at. Every run now flies the SAME spec closed loop headlessly, writes
capture/closure.json beside the clip, and FAILS by name when the
commanded state was not reached.
"""

import json
import time

import pytest
from starlette.testclient import TestClient

from core.control.autopilot import ClosureTolerance
from core.nl.compiler import compile_prompt
from webapp.server import app, manager
import webapp.capture as capture_module


DEMO = ("fly the 747 at 5000 ft over the prairie for 6 seconds with a "
        "chase camera capturing 3 images")


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


def finished(client, run_id, limit=900):
    for _ in range(limit):
        state = client.get(f"/runs/{run_id}").json()
        if state["status"] in ("done", "failed"):
            return state
        time.sleep(0.5)
    raise AssertionError(f"run {run_id} never finished")


def test_every_run_carries_a_closure_report(client):
    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    assert reply.status_code == 200, reply.json()
    run_id = reply.json()["run_id"]
    state = finished(client, run_id)
    assert state["status"] == "done", state["detail"]

    closure = state["capture"]["closure"]
    assert closure["ok"] is True
    assert [c["name"] for c in closure["checks"]] == [
        "altitude", "airspeed", "heading", "settled"]
    on_disk = json.loads(
        (manager.out_root / run_id / "capture" / "closure.json")
        .read_text(encoding="utf-8"))
    assert on_disk["checks"] == closure["checks"]
    # The pair is the same spec flown closed loop: its digest differs from
    # the open-loop capture only by hold_state.
    assert on_disk["pair_spec_digest"] != spec.digest()

    files = client.get(f"/runs/{run_id}/files").json()["files"]
    names = [f["name"] for f in files]
    assert "capture/closure.json" in names
    got = client.get(f"/runs/{run_id}/file/capture/closure.json")
    assert got.status_code == 200


def test_a_closure_the_aircraft_cannot_meet_fails_the_run_by_name(
        client, monkeypatch):
    """The safeguard: with a tolerance nothing can satisfy, the paired run
    fails and the run's status names the failing check. There is no path
    on which a run with a failed closure reports 'done'."""
    def impossible(self, altitudes_m, airspeeds_kt, headings_deg,
                   climb_rates_mps, tolerance=ClosureTolerance()):
        return real_closure(self, altitudes_m, airspeeds_kt, headings_deg,
                            climb_rates_mps,
                            ClosureTolerance(altitude_m=0.0,
                                             airspeed_kt=0.0,
                                             heading_deg=0.0,
                                             climb_rate_mps=0.0))

    from core.control.autopilot import Autopilot
    real_closure = Autopilot.closure
    monkeypatch.setattr(Autopilot, "closure", impossible)

    spec = compile_prompt(DEMO)
    reply = client.post("/capture", json={"spec": spec.to_dict()})
    state = finished(client, reply.json()["run_id"])
    assert state["status"] == "failed"
    assert state["detail"].startswith("[closure.")
    assert state["capture"]["closure"]["ok"] is False


def test_closure_run_refuses_when_the_autopilot_cannot_engage(
        tmp_path, monkeypatch):
    """A pair that cannot produce a closure report is a named refusal, not
    a silently missing file."""
    import core.scenario.runner as runner

    class NoClosure:
        closure = None
        output_digest = "x"

    monkeypatch.setattr(runner, "run_spec", lambda *a, **k: NoClosure())
    spec = compile_prompt(DEMO)
    with pytest.raises(capture_module.CaptureError) as caught:
        capture_module.closure_run(spec, tmp_path, {"key": "flat", "terrain": None})
    assert caught.value.constraint == "closure.unavailable"
    assert not (tmp_path / "capture" / "closure.json").exists()


def test_the_closure_pair_grades_the_clip_s_own_window(tmp_path):
    """The clip is capped at CLIP_SECONDS; the pair flies that window, not
    the spec's full duration, and says so in closure.json."""
    from webapp.runs import CLIP_SECONDS

    spec = compile_prompt("fly the 747 at 5000 ft over the prairie for 300 seconds")
    assert float(spec.duration.value) > CLIP_SECONDS
    verdict = capture_module.closure_run(
        spec, tmp_path, {"key": "flat", "terrain": None})
    assert verdict["duration_s"] == CLIP_SECONDS
    assert verdict["clip_seconds_cap"] == CLIP_SECONDS
    # The window word says what was graded (the first 22 s of a 300 s
    # flight), never "clip": a headless pair has no clip to name.
    assert verdict["window"] == "capped"
    assert verdict["spec_duration_s"] == 300.0
    assert verdict["ok"]
