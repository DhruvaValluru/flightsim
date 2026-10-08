"""The terrain bake starts at Interpret, in the background, and Run joins it.

A named place used to download its terrain only after Run was clicked
(/run refused terrain.unbaked, the page called /bake and waited minutes).
/compile now starts that bake as soon as the spec names the place; /bake
waits on the job already running instead of starting a second bake of the
same place; a failed job is retried, never served stale. The bake itself
is stubbed: no test reaches the network.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webapp.runs as runs
import webapp.server as server

REPO = Path(__file__).resolve().parents[1]
#: A named place no bake on a test machine covers (New York).
PROMPT = "fly the c172p at 3000 m over new york city"


class FakeBake:
    """bake_on_demand's stand-in: records each call and holds until released."""

    def __init__(self, fail_first: bool = False):
        self.calls = []
        self.release = threading.Event()
        self.fail_first = fail_first

    def __call__(self, lat, lon):
        self.calls.append((lat, lon))
        assert self.release.wait(10), "the test never released the bake"
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("tile server unreachable (test)")
        return {"key": "nyc_test", "title": "New York (test)", "origin_lat": lat,
                "origin_lon": lon}


@pytest.fixture()
def prefetch(monkeypatch, tmp_path):
    monkeypatch.setenv(runs.TERRAIN_PREFETCH_ENV, "on")
    # No bakes on this "machine", whatever the checkout's runs/ holds.
    monkeypatch.setattr(runs, "TERRAIN_DIR", tmp_path / "terrain")
    fresh = runs.TerrainPrefetch()
    monkeypatch.setattr(runs, "PREFETCH", fresh)
    monkeypatch.setattr(server, "PREFETCH", fresh)
    fake = FakeBake()
    monkeypatch.setattr(server, "bake_on_demand", fake)
    return fake


def compile_payload(client, prompt=PROMPT):
    return client.post("/compile", json={"prompt": prompt, "compiler": "regex"}).json()


def test_interpret_starts_the_bake_and_run_joins_it_instead_of_baking_twice(prefetch):
    client = TestClient(server.app)
    payload = compile_payload(client)
    status = payload["terrain_prefetch"]
    assert status["state"] == "downloading"
    assert (status["latitude"], status["longitude"]) == (40.7128, -74.006)
    # A second Interpret of the same place keeps the one job.
    assert compile_payload(client)["terrain_prefetch"]["state"] == "downloading"
    assert client.get("/bake/status", params={"latitude": 40.7128,
                                               "longitude": -74.006}).json()["state"] \
        == "downloading"

    # Run's /bake arrives while the download is still going: it waits on it.
    answer = {}
    waiter = threading.Thread(target=lambda: answer.update(
        response=client.post("/bake", json={"latitude": 40.7128, "longitude": -74.006})))
    waiter.start()
    prefetch.release.set()
    waiter.join(10)
    assert answer["response"].status_code == 200
    assert answer["response"].json()["title"] == "New York (test)"
    assert prefetch.calls == [(40.7128, -74.006)]          # one bake, never two
    done = client.get("/bake/status", params={"latitude": 40.7128,
                                               "longitude": -74.006}).json()
    assert done["state"] == "done" and done["title"] == "New York (test)"


def test_a_failed_background_bake_is_retried_by_run_not_served_stale(prefetch):
    prefetch.fail_first = True
    prefetch.release.set()
    client = TestClient(server.app)
    compile_payload(client)
    runs.PREFETCH._jobs[runs.TerrainPrefetch.key(40.7128, -74.006)]["finished"].wait(10)
    failed = client.get("/bake/status", params={"latitude": 40.7128,
                                                 "longitude": -74.006}).json()
    assert failed["state"] == "failed" and "unreachable" in failed["error"]
    response = client.post("/bake", json={"latitude": 40.7128, "longitude": -74.006})
    assert response.status_code == 200 and len(prefetch.calls) == 2


def test_no_place_and_prefetch_off_start_nothing(prefetch, monkeypatch):
    client = TestClient(server.app)
    assert compile_payload(client, "fly the c172p at 3000 m")["terrain_prefetch"] is None
    monkeypatch.setenv(runs.TERRAIN_PREFETCH_ENV, "off")
    assert compile_payload(client)["terrain_prefetch"] is None
    assert prefetch.calls == []
    assert client.get("/bake/status", params={"latitude": 1.0,
                                               "longitude": 2.0}).json() == {"state": "none"}


def test_the_compiled_spec_is_not_moved_by_the_probe(prefetch):
    """The prefetch asks /run's question on a COPY: the spec the page
    shows (and its digest) is exactly what compile produced."""
    prefetch.release.set()
    client = TestClient(server.app)
    off = compile_payload(client, PROMPT)
    from core.scenario.spec import ScenarioSpec

    assert ScenarioSpec.from_dict(off["spec"]["dict"]).digest() == off["spec"]["digest"]


def test_the_page_follows_the_download_and_run_says_it_is_waiting():
    page = (REPO / "webapp/static/index.html").read_text(encoding="utf-8")
    for anchor in ('id="terrainState"', "function showTerrainPrefetch",
                   "showTerrainPrefetch(payload.terrain_prefetch)", "/bake/status?latitude=",
                   "waiting for the terrain download that started at Interpret"):
        assert anchor in page, anchor
