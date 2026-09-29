"""Phase 2, package I part 2: the guided page's endpoints
(``webapp/generate.py`` over ``core.campaign`` and ``core.messages``).

The rules under test: the question round is the compilers' (an imagery
prompt naming no viewpoint is asked which); every refusal reaches the
page as a catalogue sentence with the rule name ONLY under ``details``;
progress is read from the ledger and nothing else (a ledger the test
writes by hand is reported as written); the download is a zip whose
card names the format; the event stream emits. Campaigns run the REAL
headless pipeline on two-second flights (about a second a case, no
engine); nothing here renders a pixel, and the fake capture runner
stands in only where a failed capture is the point.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import webapp.generate as generate_module
from core.campaign import Campaign
from core.campaign.ledger import Ledger
from webapp.server import app, generator

#: An imagery prompt that names no viewpoint: the compilers ask which.
ASKS_VIEW = "photos of the a320 for 2 seconds in varied weather at different times of day"
ANSWER = [{"id": "camera_view", "answer": "chase"}]
#: Two-second flights: ~19 frames a case at the recorder's cadence.
IMAGES = 20

NAME_RE = r"^[a-z_]+(?:\.[a-z_]+)+$"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "root", tmp_path / "campaigns")
    monkeypatch.setattr(generate_module, "CAPTURE_RUNNER", None)
    return TestClient(app)


@pytest.fixture(scope="module")
def done_campaign(tmp_path_factory):
    """One real campaign run to done through the service (the module
    shares it: ~2 s of headless flying)."""
    root = tmp_path_factory.mktemp("done")
    service = generate_module.GenerateService(root)
    started = service.start(ASKS_VIEW, answers=ANSWER, images=IMAGES, fmt="coco",
                            seed=7, workers=1, tier="regex")
    service.wait(started["id"], timeout=120)
    assert not service.threads[started["id"]].is_alive(), (
        f"campaign thread still running after 120 s; recorded error: "
        f"{service.errors.get(started['id'])!r}")
    campaign = Campaign.open(root / started["id"])
    assert campaign.state == "done", campaign.record
    return {"root": root, "id": started["id"], "service": service}


@pytest.fixture()
def done_client(done_campaign, monkeypatch):
    monkeypatch.setattr(generator, "root", done_campaign["root"])
    return TestClient(app)


def _rule_named(payload, keys=("sentence", "hint", "headline", "paragraph")):
    """True when any default field carries a bare rule name."""
    import re

    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and re.match(NAME_RE, value.strip()):
            return True
    return False


# -- ask / clarify -------------------------------------------------------------

def test_the_page_is_served_and_linked_from_the_expert_page(client):
    page = client.get("/generate.html")
    assert page.status_code == 200
    for state in ("s-ask", "s-clarify", "s-preview", "s-generate", "s-review", "s-download"):
        assert f'id="{state}"' in page.text, state
    assert 'class="expert"' in page.text          # every screen names its command
    assert "<details>" in page.text or "<details" in page.text   # the rule under a disclosure
    assert "EventSource" in page.text              # server-sent events, polling fallback
    assert "/generate.html" in client.get("/").text


def test_an_imagery_prompt_with_no_viewpoint_gets_the_compilers_question(client):
    response = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "regex",
                                                   "images": IMAGES})
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "clarify"
    assert 1 <= len(payload["questions"]) <= generate_module.MAX_QUESTIONS
    assert payload["questions"][0]["id"] == "camera_view"
    assert "chase" in payload["questions"][0]["options"]
    assert payload["headline"] == "A few questions before generating."
    assert payload["expert"][0].startswith("python -m flightsim.campaign ")
    assert "--plan" in payload["expert"][0]
    # A prompt that names its view is not asked.
    named = client.post("/generate/plan", json={"prompt": ASKS_VIEW + ", chase view",
                                                "tier": "regex", "images": IMAGES}).json()
    assert named["state"] == "preview" and named["questions"] == [] if "questions" in named else True


def test_the_answer_round_yields_the_plan_preview_in_words(client):
    first = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "regex",
                                                "images": IMAGES}).json()
    response = client.post("/generate/plan", json={
        "prompt": ASKS_VIEW, "tier": "regex", "images": IMAGES, "format": "yolo",
        "questions": first["questions"], "answers": ANSWER})
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "preview" and payload["ok"] is True
    words = payload["paragraph"]
    # airframes, places, conditions, viewpoints, count, format
    assert "A320" in words and "images" in words and "chase view" in words
    assert "YOLO" in words and "flat ground" in words and "cloud cover" in words
    assert payload["refusals"] == []
    est = payload["estimate"]
    assert est["frames_per_case"]["estimate"] == 21          # 2 s at 0.1 s + 1
    assert est["frames_per_case"]["measured"] is None
    assert est["projected_bytes"] is None and est["within_free"] is None
    assert "not measured" in est["basis"]                    # unmeasured is no claim
    assert est["free_bytes"] > 0
    assert payload["spec_digest"] == len(payload["spec_digest"]) * "0" or len(payload["spec_digest"]) == 64
    assert '--answer "camera_view=chase"' in payload["expert"][0]
    assert not _rule_named(payload)


def test_llm_death_falls_back_to_the_offline_compiler_and_says_so(client, monkeypatch):
    from core.nl.llm_compiler import LLMCompileError

    def dead(*a, **k):
        raise LLMCompileError("the LLM compiler is unavailable: no SDK")

    monkeypatch.setattr(generate_module, "compile_prompt_llm", dead)
    payload = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "llm",
                                                  "images": IMAGES}).json()
    assert payload["tier"] == "regex" and "offline compiler" in payload["note"]
    assert payload["state"] == "clarify"           # the regex path's question still asked


# -- the catalogue-only rule ---------------------------------------------------

def test_a_refusal_renders_as_a_catalogue_sentence_never_a_raw_rule_name(client):
    response = client.post("/generate/plan", json={
        "prompt": "fly the 747 at 500 m over 2000 m terrain, chase view", "tier": "regex"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    refusal = payload["refusals"][0]
    # The default fields are words; the rule lives under details only.
    assert refusal["sentence"].startswith("A starting height of 500 m is too close")
    assert "altitude.terrain_clearance" not in refusal["sentence"]
    assert "altitude.terrain_clearance" not in refusal["hint"]
    assert not _rule_named(refusal)
    assert refusal["details"]["rule"] == "altitude.terrain_clearance"
    assert refusal["details"]["catalogued"] is True
    assert refusal["details"]["limit"] == 2030.0
    # A 409 takes the same shape (an export format the system does not write).
    refused = client.post("/generate/start", json={"prompt": ASKS_VIEW, "answers": ANSWER,
                                                   "images": IMAGES, "format": "parquet",
                                                   "tier": "regex"})
    assert refused.status_code == 409
    body = refused.json()
    assert body["sentence"] == "That export format is not one the system writes."
    assert not _rule_named(body)
    assert body["details"]["rule"] == "export.format"


def test_words_keeps_the_rule_out_of_every_default_field():
    from core.scenario.validate import Violation

    rendered = generate_module.words(Violation(
        "airspeed.stall_margin", "below 1.05 x Vs", actual=95.0, limit=118.2, unit="kt CAS"))
    assert rendered["sentence"] == ("A speed of 95 knots is too slow for this aircraft to "
                                    "keep flying; it needs at least 118.2 knots.")
    assert rendered["hint"] == "Ask for a faster speed."
    assert rendered["details"] == {"rule": "airspeed.stall_margin", "message": "below 1.05 x Vs",
                                   "catalogued": True, "actual": 95.0, "limit": 118.2,
                                   "unit": "kt CAS"}
    # The three campaign refusals are catalogued (0958a45): the page
    # shows the catalogue sentence, never the producer's text.
    from core.campaign import CampaignError

    rendered = generate_module.words(CampaignError("campaign.state", "a done campaign cannot pause"))
    assert rendered["sentence"] == "The campaign is not in a state where that action is possible."
    assert rendered["details"] == {"rule": "campaign.state", "message": "a done campaign cannot pause",
                                   "catalogued": True, "detail": {}}
    # An uncatalogued name (a name the catalogue genuinely lacks): the
    # producer's own message stands in, the name is still only under
    # details, and the gap is visible as catalogued: false.
    rendered = generate_module.words(CampaignError("campaign.no_such_rule", "the producer's own words"))
    assert rendered["sentence"] == "the producer's own words"
    assert rendered["hint"] == ""
    assert rendered["details"]["rule"] == "campaign.no_such_rule"
    assert rendered["details"]["catalogued"] is False


def test_the_capture_log_s_refusals_are_read_by_name(tmp_path):
    log = tmp_path / "capture.log"
    log.write_text("JSBSim startup beginning ...\nREFUSED -- by name:\n"
                   "  [camera.terrain_clearance] camera[0] 'tower': the stated placement sits "
                   "inside the terrain (requested -1779.2 m AGL, limit 2 m AGL)\n",
                   encoding="utf-8")
    refusals = generate_module.capture_refusals(log)
    assert len(refusals) == 1
    assert refusals[0]["sentence"].startswith("The camera's path drops 1781.2 m below")
    assert refusals[0]["details"]["rule"] == "camera.terrain_clearance"
    log.write_text("REFUSED -- aircraft.mesh: no imported model\n", encoding="utf-8")
    assert generate_module.capture_refusals(log)[0]["details"]["rule"] == "aircraft.mesh"
    assert generate_module.capture_refusals(tmp_path / "missing.log") == []


# -- preview -------------------------------------------------------------------

def test_the_preview_flies_one_case_and_measures_it(client):
    plan = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "regex",
                                               "images": IMAGES, "answers": ANSWER}).json()
    response = client.post("/generate/preview", json={"spec": plan["spec"], "images": IMAGES})
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True and payload["status"] == "verified"
    assert payload["engine"] is False and payload["drawn"] is False     # no engine here
    picture = payload["picture"]
    assert picture["kind"] == "previews" and picture["name"] == "preview_0000.png"
    image = client.get(picture["url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    measured = payload["measured"]
    assert measured["frames"] > 0 and measured["bytes"] > 0 and measured["wall_seconds"] > 0
    est = payload["estimate"]
    assert est["frames_per_case"]["measured"] == measured["frames"]
    assert est["cases_needed"] == -(-IMAGES // measured["frames"])
    assert est["projected_bytes"] == measured["bytes"] * est["cases_needed"]
    assert est["within_free"] is True and "measured" in est["basis"]
    assert payload["verification_words"]["verdict"] == "Passed."
    assert "--max-previews 1" in payload["expert"][0]
    # The image route does not climb out of the preview.
    escape = client.get(f"/generate/preview/{payload['preview_id']}/previews/../../etc/passwd")
    assert escape.status_code == 404
    assert client.get(f"/generate/preview/{payload['preview_id']}/previews/chase/nope.png").status_code == 404


def test_a_preview_whose_capture_refuses_says_why_in_words(client, monkeypatch):
    monkeypatch.setattr(generate_module, "CAPTURE_RUNNER", "tests.test_campaign:failing_capture")
    plan = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "regex",
                                               "images": IMAGES, "answers": ANSWER}).json()
    response = client.post("/generate/preview", json={"spec": plan["spec"], "images": IMAGES})
    assert response.status_code == 409
    body = response.json()
    assert body["sentence"] == "The sample scenario could not be flown."
    assert body["details"]["log_tail"] == ["the test broke this capture"]
    assert not _rule_named(body)


# -- generate: progress from the ledger --------------------------------------------

def test_progress_is_read_from_a_ledger_the_test_wrote(client):
    root = generator.root
    campaign = Campaign.create(ASKS_VIEW, answers=ANSWER, images=100, seed=7,
                               out=root / "abcdefabcdef", tier="regex")
    ledger = Ledger(campaign.dir / "ledger.jsonl")
    ledger.append({"index": 0, "status": "running", "attempt": 1})
    ledger.append({"index": 0, "status": "verified", "case_id": "a" * 16, "run_dir": "x",
                   "ok": True, "verified": True, "frames": 40, "yield": 40, "bytes": 1000,
                   "wall_seconds": 2.0, "sampled": {"cloud_cover": 0.2, "precipitation": "rain"},
                   "refusals": ["randomization.sun_elevation_min_deg"]})
    ledger.append({"index": 1, "status": "refused", "refusals": ["randomization.infeasible"],
                   "ok": False, "verified": False, "frames": 0, "yield": 0})
    ledger.append({"index": 2, "status": "rendered", "case_id": "b" * 16, "run_dir": "y",
                   "ok": True, "verified": False, "frames": 40, "yield": 0, "bytes": 3000,
                   "wall_seconds": 4.0, "sampled": {"cloud_cover": 0.8, "precipitation": "none"}})
    with (campaign.dir / "ledger.jsonl").open("a") as fh:
        fh.write('{"index": 3, "status": "verified", "yield": 99')       # killed mid-write
    campaign._transition("running")
    response = client.get("/generate/abcdefabcdef")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["headline"] == "Generating: 40 of 100 images so far."
    assert payload["frames_verified"] == 40 and payload["frames_captured"] == 80
    assert payload["fraction"] == 0.4 and payload["indices"] == 3
    assert payload["cases"] == {"sampled": 0, "refused": 1, "running": 0, "rendered": 1,
                                "verified": 1, "failed": 0}
    assert payload["cases_words"]["verified"] == {"count": 1, "sentence": "Checked."}
    # Refused and why: catalogue sentences, names under details.
    names = {r["details"]["rule"]: r for r in payload["refusals_words"]}
    assert set(names) == {"randomization.infeasible", "randomization.sun_elevation_min_deg"}
    assert names["randomization.infeasible"]["count"] == 1
    # The sentence reads correctly without the draw count (the ledger's
    # refusal list carries names only): no "of came out" gap.
    assert names["randomization.infeasible"]["sentence"].startswith("Every attempt to draw")
    assert "(" not in names["randomization.infeasible"]["sentence"]
    assert not any(_rule_named(r) for r in payload["refusals_words"])
    # What is varying: histograms over the rows' draws (the refused slot drew nothing).
    varying = payload["varying"]
    assert varying["cloud_cover"]["kind"] == "numeric" and varying["cloud_cover"]["n"] == 2
    assert varying["cloud_cover"]["min"] == 0.2 and varying["cloud_cover"]["max"] == 0.8
    assert sum(varying["cloud_cover"]["counts"]) == 2
    assert varying["precipitation"] == {"kind": "categorical", "n": 2,
                                        "counts": {"none": 1, "rain": 1}}
    # Time from the MEASURED per-case cost: 40 frames and 3 s a case, 60 frames to go.
    timing = payload["timing"]
    assert timing["frames_per_case"] == 40 and timing["seconds_per_case"] == 3.0
    assert timing["remaining_cases"] == 2 and timing["seconds_remaining"] == 6.0
    assert timing["basis"] == "measured over completed cases"
    assert payload["disk"]["bytes_per_case"] == 2000
    assert payload["expert"][0].endswith("--status")
    assert not _rule_named(payload)
    # A campaign this server never heard of, and a malformed id.
    assert client.get("/generate/0123456789ab").status_code == 404
    assert client.get("/generate/../etc").status_code == 404


def test_progress_before_any_case_makes_no_time_claim(client):
    Campaign.create(ASKS_VIEW, answers=ANSWER, images=10, out=generator.root / "0123456789ab",
                    tier="regex")
    payload = client.get("/generate/0123456789ab").json()
    assert payload["state"] == "planned"
    assert payload["headline"] == "The campaign is planned and waiting to start."
    assert payload["timing"]["seconds_remaining"] is None
    assert payload["timing"]["remaining_cases"] is None
    assert "nothing is estimated" in payload["timing"]["basis"]
    assert payload["varying"] == {}


# -- the real thing: start, events, gallery, download ---------------------------

def test_start_runs_the_campaign_and_the_stream_emits(client):
    response = client.post("/generate/start", json={
        "prompt": ASKS_VIEW, "answers": ANSWER, "images": IMAGES, "format": "coco",
        "seed": 7, "workers": 1, "tier": "regex", "plan_digest": "not the digest"})
    assert response.status_code == 200, response.json()
    started = response.json()
    assert started["state"] == "running" and started["recompiled"] is True
    assert started["headline"] == "Generating."
    assert started["expert"][0].startswith('python -m flightsim.campaign "photos of the a320')
    campaign_id = started["id"]
    # A second campaign while one runs is refused in words.
    generator.wait(campaign_id, timeout=120)
    # A campaign thread still alive here is a hang, not a slow run: say
    # so with what it recorded, instead of streaming events forever.
    assert not generator.threads[campaign_id].is_alive(), (
        f"campaign thread still running after 120 s; recorded error: "
        f"{generator.errors.get(campaign_id)!r}")
    assert Campaign.open(generator.root / campaign_id).state == "done"
    events = []
    with client.stream("GET", f"/generate/{campaign_id}/events?interval=0.05&limit=200") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        for line in stream.iter_lines():
            events.append(line)
    kinds = [l.split(": ", 1)[1] for l in events if l.startswith("event: ")]
    assert kinds[0] == "progress" and kinds[-1] == "end"
    data = [json.loads(l[len("data: "):]) for l in events if l.startswith("data: ")]
    assert data[0]["state"] == "done" and data[0]["frames_verified"] >= IMAGES
    # Nothing here claims a picture was drawn: the done sentence names the
    # labels; the drawn-aware tail is the page's to pass (progress_from).
    assert data[0]["headline"].startswith("Every requested image has its labels generated and checked")
    assert "has been generated" not in data[0]["headline"]
    # Pause after done is an illegal transition: refused, not a 500.
    paused = client.post(f"/generate/{campaign_id}/pause")
    assert paused.status_code == 409 and paused.json()["details"]["rule"] == "campaign.state"
    assert client.get(f"/generate/{campaign_id}/events").status_code == 200
    assert client.get("/generate/0123456789ab/events").status_code == 404


def test_the_gallery_lists_each_case_s_picture_off_the_directories(done_client, done_campaign):
    campaign_id = done_campaign["id"]
    response = done_client.get(f"/generate/{campaign_id}/frames")
    assert response.status_code == 200
    payload = response.json()
    assert payload["drawn"] is False and "geometry previews" in payload["what"]
    assert len(payload["items"]) >= 2
    first = payload["items"][0]
    assert first["kind"] == "previews" and first["verified"] is True
    assert first["status_words"] == "Checked."
    assert set(first["sampled"]) >= {"cloud_cover", "precipitation"}
    image = done_client.get(first["url"])
    assert image.status_code == 200 and image.content[:4] == b"\x89PNG"
    bad = done_client.get(f"/generate/{campaign_id}/frames/{first['case_id']}/previews/chase/..%2f..%2fspec.yaml")
    assert bad.status_code == 404
    assert done_client.get(f"/generate/{campaign_id}/frames/zzzz/previews/chase/preview_0000.png").status_code == 404
    # A picture the renderer never wrote is not listed: remove one and it disappears.
    run_dir = done_campaign["root"] / campaign_id / "runs" / first["case_id"]
    (run_dir / "previews" / first["camera_id"] / first["name"]).unlink()
    again = done_client.get(f"/generate/{campaign_id}/frames").json()
    assert all(i["case_id"] != first["case_id"] or i["name"] != first["name"]
               for i in again["items"])


def test_the_download_is_a_zip_whose_card_names_the_format(done_client, done_campaign):
    campaign_id = done_campaign["id"]
    response = done_client.get(f"/generate/{campaign_id}/download?format=yolo")
    assert response.status_code == 200, response.json()
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["x-dataset-format"] == "yolo"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert "yolo/dataset.json" in names and "yolo/DATASET_CARD.md" in names
    assert "yolo/data.yaml" in names
    assert any(n.startswith("yolo/labels/") and n.endswith(".txt") for n in names)
    card = json.loads(archive.read("yolo/dataset.json"))
    assert card["format"] == "yolo" and card["formats"] == ["yolo"]
    assert "yolo" in archive.read("yolo/DATASET_CARD.md").decode("utf-8")
    # The campaign's own format when none is given; an unknown one refused in words.
    default = done_client.get(f"/generate/{campaign_id}/download")
    assert default.status_code == 200 and default.headers["x-dataset-format"] == "coco"
    refused = done_client.get(f"/generate/{campaign_id}/download?format=parquet")
    assert refused.status_code == 409
    assert refused.json()["sentence"] == "That export format is not one the system writes."


def test_a_download_with_nothing_verified_is_refused_in_words(client):
    Campaign.create(ASKS_VIEW, answers=ANSWER, images=10, out=generator.root / "0123456789ab",
                    tier="regex")
    response = client.get("/generate/0123456789ab/download?format=coco")
    assert response.status_code == 409
    body = response.json()
    assert body["details"]["rule"].startswith("export.")
    assert not _rule_named(body)


def test_cancel_and_resume_go_through_the_campaign_s_own_transitions(client):
    Campaign.create(ASKS_VIEW, answers=ANSWER, images=10, out=generator.root / "0123456789ab",
                    tier="regex")
    resumed = client.post("/generate/0123456789ab/cancel")
    assert resumed.status_code == 200 and resumed.json()["state"] == "cancelled"
    assert resumed.json()["headline"] == "The campaign was cancelled."
    assert resumed.json()["expert"][0].endswith("--cancel")
    again = client.post("/generate/0123456789ab/resume")
    assert again.status_code == 409 and again.json()["details"]["rule"] == "campaign.state"
    assert client.post("/generate/0123456789ab/restart").status_code == 404


def test_the_paragraph_reads_the_spec_not_a_template():
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("fly the 747 in severe turbulence with 20 kt wind from 270, tower view "
                          "for 30 seconds")
    words = generate_module.paragraph(spec, 5, "voc")
    assert words.startswith("5 images of the B747")
    assert "20 kt of wind from" in words and "severe turbulence" in words
    assert "tower view" in words and "30 s" in words and "VOC" in words
    one = generate_module.paragraph(compile_prompt("fly the a320"), 1, "coco")
    assert one.startswith("1 image of the A320") and "chase view (the default" in one


# -- the findings of the phase-2 review (webapp area) ---------------------------

def test_a_bare_catalogued_name_and_a_nameless_refused_line_are_read_by_name(tmp_path):
    """``flightsim.capture`` prints ``REFUSED -- trim: ...`` (a bare name
    the catalogue keeps as spelled) and ``REFUSED -- <exception text>``
    for a spec it cannot read; whether a head is a name is the
    catalogue's question, not the regex's shape (a dot was required)."""
    log = tmp_path / "capture.log"
    log.write_text("REFUSED -- trim: no trim at 60 kt\n"
                   "REFUSED -- terrain.impact: x\n", encoding="utf-8")
    refusals = generate_module.capture_refusals(log)
    assert [r["details"]["rule"] for r in refusals] == ["trim", "terrain.impact"]
    assert refusals[0]["details"]["catalogued"] is True
    assert not _rule_named(refusals[0]) and refusals[0]["sentence"].endswith(".")
    # A nameless line whose sentence the catalogue recognises (spec.version).
    log.write_text("REFUSED -- spec_version 99 is not supported by this build\n",
                   encoding="utf-8")
    versioned = generate_module.capture_refusals(log)
    assert len(versioned) == 1 and versioned[0]["details"]["rule"] == "spec.version"
    # A head that merely looks like a name is not one: no invented refusal.
    log.write_text("REFUSED -- by name:\nREFUSED -- not_a_rule: whatever\n", encoding="utf-8")
    assert generate_module.capture_refusals(log) == []


def test_the_paragraph_says_what_ground_a_mountain_prompt_really_flies_over():
    """'over mountains' raises the flat datum to 2000 m (the compiler's
    inferred terrain_elevation); no ridge is synthesised unless
    scene.terrain_source says so. The plan must say that, not 'sea level'."""
    from core.nl.compiler import compile_prompt

    spec = compile_prompt("500 images of airliners over mountains in varied weather and "
                          "lighting, chase and tower views",
                          answers=[{"id": "aircraft", "answer": "B747"}])
    assert float(spec.terrain_elevation.value) == 2000.0
    words = generate_module.paragraph(spec, 3, "coco")
    assert words.startswith("3 images of the B747, over flat ground raised to a 2000 m datum")
    assert "no hills or mountains are in the pictures" in words
    assert "no place was named" in words and "sea level" not in words
    spec.set("scene.terrain_source", "synthesised", frm="test")
    ridge = generate_module.paragraph(spec, 3, "coco")
    assert "over a synthesised ridge" in ridge and "not a real place" in ridge
    flat = generate_module.paragraph(compile_prompt("fly the a320"), 1, "coco")
    assert "over flat ground at sea level (no place was named)" in flat


def test_an_uncatalogued_reason_never_reaches_the_sentence():
    """A worker-pool crash writes ``BrokenProcessPool: ...`` into the
    record; the page's sentence is the catalogue's for the state and the
    exception's text stays under the disclosure."""
    raw = "BrokenProcessPool: A process in the process pool was terminated abruptly"
    rendered = generate_module._reason_words(raw, "failed")
    assert rendered["sentence"] == "The campaign stopped on an error."
    assert rendered["details"]["message"] == raw
    assert rendered["details"]["rule"] == "progress.campaign.failed"
    assert "BrokenProcessPool" not in rendered["sentence"] + rendered["hint"]
    # A catalogued head still renders as that refusal.
    named = generate_module._reason_words("campaign.target_unreachable: 3 slot(s) refused", "failed")
    assert named["details"]["rule"] == "campaign.target_unreachable"
    assert named["sentence"].startswith("The campaign could not reach")
    # The ledger's own tally on done is the state's sentence with the numbers under details.
    done = generate_module._reason_words("1000 verified frame(s) of 3", "done",
                                         done=1000, total=3, cases_verified=1)
    assert done["sentence"].startswith("Every requested image has its labels generated and checked")
    assert done["details"]["cases_verified"] == 1 and done["details"]["message"] == "1000 verified frame(s) of 3"


def test_progress_puts_a_thread_error_and_the_done_tally_in_words(client):
    root = generator.root
    campaign = Campaign.create(ASKS_VIEW, answers=ANSWER, images=3, seed=7,
                               out=root / "0123456789ab", tier="regex")
    ledger = Ledger(campaign.dir / "ledger.jsonl")
    ledger.append({"index": 0, "status": "verified", "case_id": "c" * 16, "run_dir": "x",
                   "ok": True, "verified": True, "frames": 1000, "yield": 1000, "bytes": 10,
                   "wall_seconds": 1.0, "sampled": {}})
    campaign._transition("running")
    campaign._transition("done", "1000 verified frame(s) of 3")
    payload = generate_module.progress_from(
        campaign.record, ledger.rows(), campaign.dir,
        thread_error="BrokenProcessPool: A process in the process pool was terminated abruptly")
    assert payload["state"] == "done" and payload["cases_verified"] == 1
    assert payload["frames_verified"] == 1000 and payload["images_target"] == 3
    assert payload["reason_words"]["details"]["catalogued"] is True
    assert payload["reason_words"]["sentence"] == payload["headline"]
    assert payload["thread_error_words"]["sentence"] == "The campaign stopped on an error."
    assert "BrokenProcessPool" in payload["thread_error_words"]["details"]["message"]
    for key in ("headline", "reason_words", "thread_error_words"):
        value = payload[key]["sentence"] if isinstance(payload[key], dict) else payload[key]
        assert "BrokenProcessPool" not in value and "verified frame(s)" not in value
    assert generate_module.progress_from(campaign.record, ledger.rows(), campaign.dir)[
        "thread_error_words"] is None


def test_the_gallery_names_the_view_not_the_camera_directory(done_client, done_campaign):
    items = done_client.get(f"/generate/{done_campaign['id']}/frames").json()["items"]
    assert items and all(it["camera_words"] == "chase view" for it in items)
    assert generate_module._camera_id_words("tower_0") == "tower view"
    assert generate_module._camera_id_words("chase") == "chase view"
    assert generate_module.camera_views(Path("/nonexistent")) == {}


def test_the_page_s_default_path_interpolates_no_code_identifier():
    """The page prints the count with the catalogue's sentence, the view's
    words and the catalogue's error sentence -- never the ledger's status
    key, the camera directory or an exception's text."""
    html = (generate_module.REPO / "webapp" / "static" / "generate.html").read_text(encoding="utf-8")
    assert "${cw[s].count} ${s}" not in html
    assert "${cw[s].count} × ${cw[s].sentence}" in html
    assert "it.camera_words || it.camera_id" in html
    assert "refusalHtml(p.thread_error_words)" in html
    assert "esc(p.thread_error)" not in html
    expert = (generate_module.REPO / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert "capture_manifest.v5" not in expert
    assert "capture_manifest.v${manifestVersion}.schema.json" in expert


def test_the_done_headline_carries_the_numbers_and_says_whether_a_picture_was_drawn(tmp_path):
    """Measured at 5bd6864: the done headline read 'Every requested image
    has its labels generated and checked' whatever the tally, and
    progress_from passed no numbers to the sentence. The page passes
    done / total / cases_verified / drawn; the catalogue's done sentence
    carries them, and its tail says 'no picture was drawn on this
    machine' unless a case was drawn."""
    campaign = Campaign.create(ASKS_VIEW, answers=ANSWER, images=3, seed=7,
                               out=tmp_path / "0123456789ab", tier="regex")
    ledger = Ledger(campaign.dir / "ledger.jsonl")
    ledger.append({"index": 0, "status": "verified", "case_id": "c" * 16, "run_dir": "x",
                   "ok": True, "verified": True, "frames": 1000, "yield": 1000, "bytes": 10,
                   "wall_seconds": 1.0, "sampled": {}})
    campaign._transition("running")
    campaign._transition("done", "1000 verified frame(s) of 3")
    payload = generate_module.progress_from(campaign.record, ledger.rows(), campaign.dir)
    assert payload["headline"] == (
        "Every requested image has its labels generated and checked "
        "(1000 pictures from 1 scenario, 3 asked for); no picture was drawn on this machine.")
    assert payload["reason_words"]["sentence"] == payload["headline"]
    assert "generated and checked." not in payload["headline"]
    ledger.append({"index": 1, "status": "verified", "case_id": "d" * 16, "run_dir": "y",
                   "ok": True, "verified": True, "frames": 1, "yield": 1, "bytes": 10,
                   "wall_seconds": 1.0, "sampled": {}, "drawn": True})
    payload = generate_module.progress_from(campaign.record, ledger.rows(), campaign.dir)
    assert payload["drawn"] is True
    assert payload["headline"] == (
        "Every requested image has its labels generated and checked "
        "(1001 pictures from 2 scenarios, 3 asked for), and its picture drawn.")


def test_the_page_renders_only_with_an_engine_and_the_model(client, monkeypatch):
    """Measured on the macOS CI runner: ue_available() is True on every
    Mac by design, so the preview and the campaign asked for --render
    with no model imported and the capture refused aircraft.mesh -- a
    campaign that ended 'failed' on a machine that could have drawn the
    geometry preview. Rendering is decided by render_here(): the engine
    AND an imported model for every airframe, with the reason in words."""
    from core.nl.compiler import compile_prompt

    spec = compile_prompt(ASKS_VIEW + ", chase view")
    monkeypatch.setattr(generate_module, "ue_available", lambda: False)
    render, note = generate_module.render_here(spec)
    assert render is False and "no engine" in note

    monkeypatch.setattr(generate_module, "ue_available", lambda: True)
    monkeypatch.setattr(generate_module, "is_imported", lambda name: False)
    render, note = generate_module.render_here(spec)
    assert render is False and "not imported" in note and "A320" in note

    monkeypatch.setattr(generate_module, "is_imported", lambda name: True)
    render, note = generate_module.render_here(spec)
    assert render is True and "rendered" in note

    # A traffic airframe counts too: the scene draws it.
    from types import SimpleNamespace

    monkeypatch.setattr(generate_module, "is_imported",
                        lambda name: name != "B747")
    spec.traffic.append(SimpleNamespace(aircraft=SimpleNamespace(value="B747")))
    render, note = generate_module.render_here(spec)
    assert render is False and "B747" in note and "A320" not in note
    spec.traffic.pop()

    # The preview on the 'engine but no model' machine falls back to the
    # geometry preview and says so, instead of refusing by aircraft.mesh.
    monkeypatch.setattr(generate_module, "is_imported", lambda name: False)
    plan = client.post("/generate/plan", json={"prompt": ASKS_VIEW, "tier": "regex",
                                               "images": IMAGES, "answers": ANSWER}).json()
    response = client.post("/generate/preview", json={"spec": plan["spec"], "images": IMAGES})
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["engine"] is False and payload["drawn"] is False
    assert "not imported" in payload["render_note"]
    assert payload["picture"]["kind"] == "previews"
