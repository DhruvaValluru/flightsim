"""The web app can show the pictures a run produced.

Camera Phase 1 left the camera as a CLI feature. The page learned to
EDIT cameras -- 32 provenanced fields, in the review table, in the
digest -- and pressing Run mapped camera[0] back to the old
``-camera=<word>`` / ``-chase=`` preset flags, so four of those fields
reached the renderer and 28 changed nothing. The frames it rendered
survived on disk and no route served them, so the only visual output a
user could see was one mp4. No web run wrote a capture manifest.

These tests pin the half that was missing: the routes exist, they serve
real bytes, they refuse a path that tries to climb out of the run
directory, and a camera-carrying run is routed to the capture stage
rather than the single-pass preset path.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp.capture import inventory, wants_capture
from webapp.server import app, manager


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A finished run on disk, with images in the layout the manifest
    names."""
    monkeypatch.setattr(manager, "out_root", tmp_path)
    out = tmp_path / "run_test"
    for kind in ("frames", "overlays", "previews"):
        (out / kind / "chase0").mkdir(parents=True)
        (out / kind / "chase0" / "frame_0000.png").write_bytes(_png())
    (out / "frames" / "tower0").mkdir()
    (out / "frames" / "tower0" / "frame_0000.png").write_bytes(_png())
    (out / "capture_manifest.json").write_text(json.dumps({
        "manifest_version": 3,
        "cameras": [{"camera_id": "chase0", "preset": "chase",
                     "capture_count": 1, "trigger": "interval",
                     "schedule_basis": "count 1"},
                    {"camera_id": "tower0", "preset": "tower",
                     "capture_count": 1, "trigger": "interval",
                     "schedule_basis": "count 1"}],
    }), encoding="utf-8")
    (out / "verify.json").write_text(json.dumps({"ok": True, "checks": []}),
                                     encoding="utf-8")

    from webapp.runs import RunState

    state = RunState(run_id="run_test")
    state.status = "done"
    manager.runs["run_test"] = state
    return out


def _png() -> bytes:
    """A 1x1 PNG, written by hand so the test does not depend on an
    image library to produce its fixture."""
    import struct
    import zlib

    raw = b"\x00\xff\x00\x00"

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def test_the_page_can_list_what_images_a_run_produced(run_dir):
    client = TestClient(app)
    body = client.get("/runs/run_test/images").json()
    assert body["has_manifest"] and body["has_verify"]
    assert sorted(body["frames"]) == ["chase0", "tower0"]
    assert body["frames"]["chase0"] == ["frame_0000.png"]
    assert [c["camera_id"] for c in body["cameras"]] == ["chase0", "tower0"]


def test_a_rendered_frame_is_actually_served(run_dir):
    """The regression: the frames were on disk and unreachable over
    HTTP, so the page could only ever show one mp4."""
    client = TestClient(app)
    for kind in ("frames", "overlays", "previews"):
        reply = client.get(f"/runs/run_test/{kind}/chase0/frame_0000.png")
        assert reply.status_code == 200, kind
        assert reply.headers["content-type"] == "image/png"
        assert reply.content.startswith(b"\x89PNG")


def test_the_capture_manifest_and_verification_are_downloadable(run_dir):
    client = TestClient(app)
    manifest = client.get("/runs/run_test/capture_manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["manifest_version"] == 3
    assert client.get("/runs/run_test/verify.json").json()["ok"] is True


def test_a_run_without_a_manifest_says_why(tmp_path, monkeypatch):
    """A camera-less run takes the legacy clip path. The 404 has to
    explain that rather than looking like a broken route."""
    monkeypatch.setattr(manager, "out_root", tmp_path)
    (tmp_path / "bare").mkdir()
    reply = TestClient(app).get("/runs/bare/capture_manifest.json")
    assert reply.status_code == 404
    assert "stated no cameras" in reply.json()["error"]


#: Traversal attempts that actually REACH the image handler. Percent-
#: encoded, because an httpx client normalises literal "../.." before the
#: request is sent -- such a URL lands on whatever route the normalised
#: path matches and never exercises this handler at all, so testing it
#: here would prove nothing about the guard.
@pytest.mark.parametrize("path", [
    "/runs/run_test/frames/chase0/..%2f..%2f..%2fetc%2fpasswd",
    "/runs/run_test/frames/..%2f..%2fcapture_manifest.json",
    "/runs/run_test/frames/chase0/..%2f..%2fverify.json",
    "/runs/run_test/frames/%2e%2e%2f%2e%2e/frame_0000.png",
    "/runs/run_test/frames/chase0/frame_0000.png.txt",
    "/runs/run_test/frames/chase0/frame_0000.png%00.txt",
    "/runs/run_test/secrets/chase0/frame_0000.png",
    "/runs/run_test/frames/..%2ftower0/frame_0000.png",
])
def test_image_routes_refuse_to_climb_out_of_the_run(run_dir, path):
    """These routes take a filename from the browser. The only defence
    that holds is refusing to build a path out of anything but a known
    directory plus a matched name, then requiring the resolved path to
    stay inside the run."""
    reply = TestClient(app).get(path)
    assert reply.status_code == 404, f"{path} was served"
    assert not reply.content.startswith(b"\x89PNG")


def test_a_normalised_dot_segment_cannot_reach_outside_the_run(run_dir):
    """Worth pinning because it looks like a traversal and is not.

    A client collapses "frames/chase0/../.." before sending, so what
    arrives is /runs/run_test/verify.json -- a route that exists and is
    meant to be readable. The image handler is never reached. What
    matters is that the same trick cannot reach a file the run
    directory holds but no route publishes, so this puts one there and
    asks for it.
    """
    (run_dir / "render.log").write_text("engine log", encoding="utf-8")
    client = TestClient(app)
    reply = client.get("/runs/run_test/frames/chase0/../../render.log")
    assert reply.status_code == 404
    assert b"engine log" not in reply.content
    # And the normalisation really did happen, so the case is what the
    # docstring says it is rather than an accidental 404.
    landed = client.get("/runs/run_test/frames/chase0/../../verify.json")
    assert landed.url.path == "/runs/run_test/verify.json"
    assert landed.status_code == 200


def test_a_symlinked_camera_directory_cannot_serve_outside_the_run(
        run_dir, tmp_path):
    """The name patterns block "/" and "..", so they alone stop every
    textual traversal -- which leaves resolving the path and requiring
    it to stay inside the run as the guard for the case they cannot see:
    a symlink in the run directory pointing somewhere else. Without that
    check this request serves the file.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "frame_0000.png").write_bytes(_png())
    escape = run_dir / "frames" / "escape"
    try:
        escape.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):      # no symlinks on this FS
        pytest.skip("symlinks unavailable")
    reply = TestClient(app).get("/runs/run_test/frames/escape/frame_0000.png")
    assert reply.status_code == 404
    assert not reply.content.startswith(b"\x89PNG")


def test_inventory_reads_the_directories_not_the_manifest(run_dir):
    """A frame the manifest names but the renderer never wrote must not
    appear as an image the page then fails to load."""
    listing = inventory(run_dir)
    assert "tower0" not in listing["overlays"]      # never written
    assert "tower0" in listing["frames"]


def test_a_camera_carrying_spec_goes_to_the_capture_stage():
    """The routing decision itself: cameras stated means captured, not
    clipped."""
    from core.nl.compiler import compile_prompt
    from core.scenario.camera import CameraSpec

    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    assert not wants_capture(spec)
    spec.cameras = [CameraSpec.defaulted(camera_id="c0", preset="chase",
                                         aircraft="B747")]
    assert wants_capture(spec)


# -- the landmarks the engine projects are the ones the manifest names ---

def test_the_card_is_rewritten_with_the_re_solved_landmarks():
    """The failure the checks caught on the first web run that got far
    enough to be graded:

        verification FAILED: landmark_reprojection, cross_view_consistency

    core.capture.landmarks anchors its marks around the FLOWN TRACK, so
    the same names sit at different coordinates on a different flight.
    The card was rewritten after the host solve with the re-solved
    camera tracks but the PRE-RUN's landmarks, so the engine projected
    one set while the manifest declared another, and both engine-
    referenced checks measured exactly that disagreement. They did their
    job; a person had not noticed.
    """
    import inspect

    from webapp import runs

    source = inspect.getsource(runs.RunManager._render_flow)
    after = source.split("re-solved over the host's own flight")[0]
    rewrite = after[after.index("capture_resolve_over_host"):]
    assert "capture_landmark_set(" in rewrite, (
        "the landmarks must be recomputed over the host's flight before "
        "the card the render passes consume is written")
    assert '"landmarks": capture_landmarks' in rewrite


def test_landmarks_move_with_the_flight_they_were_solved_over():
    """Why the above matters, from the landmark module itself rather
    than by assertion: two different tracks give the same names
    different positions."""
    from core.capture.landmarks import scene_landmarks

    from tests.test_camera_poses import FRAME

    near = [{"north_m": float(i), "east_m": 0.0, "alt_m": 4500.0}
            for i in range(20)]
    far = [{"north_m": 5000.0 + i, "east_m": 0.0, "alt_m": 4500.0}
           for i in range(20)]
    a = {m["name"]: (m["north_m"], m["east_m"]) for m
         in scene_landmarks(FRAME, aircraft_track=near)}
    b = {m["name"]: (m["north_m"], m["east_m"]) for m
         in scene_landmarks(FRAME, aircraft_track=far)}
    shared = set(a) & set(b)
    assert shared, "the two sets share names"
    assert any(a[name] != b[name] for name in shared), (
        "same name, different place -- which is why the card and the "
        "manifest must be built from ONE flight")


# -- the clip is a convenience; the frames are the product ---------------

def test_a_capture_clip_never_deletes_the_frames(tmp_path, monkeypatch):
    """encode_clip deletes every frame but the middle one on success --
    right for the showcase, whose deliverable is the mp4, destructive
    here, where the frames ARE the deliverable and the manifest names
    every one of them by path."""
    from webapp.runs import RunManager

    frames = tmp_path / "frames"
    (frames / "chase").mkdir(parents=True)
    for i in range(4):
        (frames / "chase" / f"frame_{i:04d}.png").write_bytes(_png())

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"mp4")

        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr("webapp.runs.subprocess.run", fake_run)
    assert RunManager._encode_capture_clip(
        frames, tmp_path / "raw.mp4", ["chase"])
    assert len(list((frames / "chase").glob("frame_*.png"))) == 4, (
        "every frame the manifest names has to still be there")


def test_a_capture_clip_reads_a_camera_directory(tmp_path, monkeypatch):
    """A capture run keeps frames in frames/<camera_id>/, and the
    showcase encoder reads a flat frames/frame_%04d.png -- so it found
    nothing and failed the whole run at the very end, after the images,
    the manifest and the verification had all been written."""
    from webapp.runs import RunManager

    frames = tmp_path / "frames"
    (frames / "tower").mkdir(parents=True)
    (frames / "tower" / "frame_0000.png").write_bytes(_png())
    seen = {}

    def fake_run(command, **kwargs):
        seen["input"] = command[command.index("-i") + 1]
        Path(command[-1]).write_bytes(b"mp4")

        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr("webapp.runs.subprocess.run", fake_run)
    # An empty camera is skipped rather than encoded into nothing.
    (frames / "empty").mkdir()
    assert RunManager._encode_capture_clip(
        frames, tmp_path / "raw.mp4", ["empty", "tower"])
    assert "tower" in seen["input"]


def test_no_camera_has_frames_is_a_false_not_a_crash(tmp_path):
    from webapp.runs import RunManager

    frames = tmp_path / "frames"
    frames.mkdir()
    assert RunManager._encode_capture_clip(
        frames, tmp_path / "raw.mp4", ["nothing"]) is None


def test_the_encoder_names_the_camera_the_clip_came_from(tmp_path,
                                                         monkeypatch):
    """The telemetry panel is composited ONTO that clip and reads the
    same camera's render.json. A bare bool left the panel to guess, and
    it guessed a flat frames/render.json that a capture run does not
    have -- so the run died with FileNotFoundError after the images, the
    manifest and a PASSING verification were already on disk.
    """
    from webapp.runs import RunManager

    frames = tmp_path / "frames"
    (frames / "cockpit").mkdir(parents=True)
    (frames / "cockpit" / "frame_0000.png").write_bytes(_png())

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"mp4")

        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr("webapp.runs.subprocess.run", fake_run)
    assert RunManager._encode_capture_clip(
        frames, tmp_path / "raw.mp4", ["cockpit"]) == "cockpit"


def test_the_panel_reads_the_clip_s_own_camera():
    import inspect

    from webapp import runs

    source = inspect.getsource(runs.RunManager._render_flow)
    assert 'frames / clip_camera / "render.json"' in source, (
        "the panel must read the render.json of the camera whose frames "
        "the clip was encoded from")


def test_a_failed_panel_does_not_lose_a_verified_capture():
    """Same rule as the clip: on a capture run the images and their
    labels are the product. Losing a verified capture over a composite
    is the failure mode that threw away three good runs."""
    import inspect

    from webapp import runs

    source = inspect.getsource(runs.RunManager._render_flow)
    panel = source[source.index("compositing the telemetry panel"):]
    assert "if capture_solved is None:" in panel, (
        "only a clip-only run may fail over the panel")
    assert "raw_clip.replace(clip)" in panel, (
        "keep the unpanelled clip rather than leaving no video at all")


# -- the schedule has to fit the flight ----------------------------------

def test_the_solve_window_is_cut_to_the_clip():
    """The web run caps its clip at CLIP_SECONDS while the SPEC keeps
    its own duration, and the headless pre-run flies the spec's. Capture
    schedules solved over the full flight laid instants out past the end
    of the clip, and the render commandlet refused -- correctly, and
    only after flying for a minute:

        consume-poses: emitted 3 of the 4 scheduled images; the run
        ended before the schedule did, so the manifest would name frames
        that do not exist

    A manifest naming frames that cannot exist is the exact failure this
    phase is about. The schedule is cut to fit the flight.
    """
    from webapp.capture import clip_columns

    columns = {"t": [i * 0.5 for i in range(200)],   # 0 .. 99.5 s
               "lat_deg": [0.0] * 200}
    cut = clip_columns(columns, 22.0)
    assert cut["t"][-1] <= 22.0
    assert len(cut["t"]) == len(cut["lat_deg"]), "columns stay in step"
    assert len(cut["t"]) < 200


def test_a_flight_already_inside_the_clip_is_left_alone():
    from webapp.capture import clip_columns

    columns = {"t": [0.0, 1.0, 2.0], "lat_deg": [0.0, 0.0, 0.0]}
    assert clip_columns(columns, 22.0) == columns
    assert clip_columns(columns, None) == columns


def test_cutting_never_leaves_less_than_a_flight():
    """Two samples is the minimum a pose track can be solved over.
    Rather than hand the solver something it must refuse, a cap that
    short leaves the flight whole and lets the schedule check speak."""
    from webapp.capture import clip_columns

    columns = {"t": [0.0, 5.0, 10.0], "lat_deg": [0.0, 0.0, 0.0]}
    assert clip_columns(columns, 1.0) == columns


def test_the_solve_pass_card_states_no_cameras(tmp_path):
    """With a cameras block the render commandlet enters consume-poses
    and holds the pass to a capture schedule it is not producing images
    for -- and whose frames this pass throws away. The solve pass exists
    to record a flight."""
    import inspect

    from webapp import runs

    source = inspect.getsource(runs.RunManager._render_flow)
    assert '"cameras": None' in source, (
        "the solve pass card must carry no cameras block"
    )
    # And it is a DIFFERENT file from the one the render passes consume,
    # which carries the re-solved tracks.
    assert 'out / "host_flight" / "card.json"' in source


# -- which commandlet can fly the solve pass -----------------------------

def test_a_scripted_card_is_recognised(tmp_path):
    """The scenario commandlet REFUSES a card carrying control inputs,
    and it is right to: it exists as the Gate 5 parity reference against
    the headless run, which is hands off from trim, so scripted inputs
    would attribute a control input to the integration.

    Measured on Windows, from the web app's first host solve flight:

        LogFlightSimScenario: Error: this run card carries 4 scripted
        control inputs. The headless reference has none, so the two
        hosts would not be flying the same scenario. Use the render
        commandlet for a scenario with control inputs.

    Every showcase web run scripts the doublet -- it is what puts
    visible roll in the clip -- so every one of them hit this. The
    refusal is untouched; the caller picks the tool that can do the job,
    which is what the refusal itself says to do.
    """
    from webapp.runs import RunManager

    scripted = tmp_path / "scripted.json"
    scripted.write_text(json.dumps({
        "control_inputs": [{"t_s": 1.0, "aileron": 0.2}] * 4},
    ), encoding="utf-8")
    assert RunManager.card_has_control_inputs(scripted)

    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps({"control_inputs": []}), encoding="utf-8")
    assert not RunManager.card_has_control_inputs(plain)

    absent = tmp_path / "absent.json"
    absent.write_text(json.dumps({}), encoding="utf-8")
    assert not RunManager.card_has_control_inputs(absent)


def test_an_unreadable_card_does_not_decide_by_crashing(tmp_path):
    """It is a routing question, not a validation one -- the card is
    validated elsewhere. Answer false and let the pass refuse by name."""
    from webapp.runs import RunManager

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert RunManager.card_has_control_inputs(broken) is False
    assert RunManager.card_has_control_inputs(tmp_path / "gone.json") is False


def test_the_solve_pass_throws_its_frames_away(tmp_path, monkeypatch):
    """A render.json left inside the run would be found by the
    verifier's rglob and graded as though its frames were part of the
    capture. They are one camera's, from the PRE-RUN poses, and naming
    a landmark set the manifest does not carry is a FAIL by design.
    """
    from webapp.runs import RunManager

    manager_ = RunManager()
    card = tmp_path / "card.json"
    card.write_text(json.dumps(
        {"control_inputs": [{"t_s": 1.0}]}), encoding="utf-8")
    telemetry = tmp_path / "host_flight" / "host_telemetry.json"

    rendered = {}

    def fake_render(card, frames, scene, mesh, aircraft, telemetry=None,
                    **kwargs):
        rendered["frames"] = frames
        frames.mkdir(parents=True, exist_ok=True)
        (frames / "render.json").write_text("{}", encoding="utf-8")
        (frames / "frame_0000.png").write_bytes(_png())
        Path(telemetry).parent.mkdir(parents=True, exist_ok=True)
        Path(telemetry).write_text('{"columns": {}}', encoding="utf-8")
        return True

    monkeypatch.setattr(manager_, "_render", fake_render)
    assert manager_._fly_host(card, telemetry, {}, mesh=None, aircraft="B747")

    assert telemetry.is_file(), "the telemetry is the whole point"
    assert not rendered["frames"].exists(), (
        "the solve pass's frames and its render.json must not survive "
        "inside the run directory")
    assert not list(tmp_path.rglob("render.json"))


# -- an engine pass that fails has to SAY why ----------------------------

def test_the_page_gets_the_commandlet_s_reason_not_a_file_path(tmp_path):
    """A named refusal buried in twenty megabytes of UE start-up is as
    good as no answer: whoever is looking at a web page cannot grep a
    file they have to go and find. Both PowerShell wrappers have printed
    the commandlet's last words since 7cef57d; the web path named a path
    and made the reader go looking.
    """
    from webapp.runs import RunManager

    log = tmp_path / "host_telemetry.log"
    log.write_text("\n".join(
        ["LogInit: boot"] + [f"LogSomethingElse: line {i}" for i in range(400)]
        + ["LogFlightSimScenario: REFUSED camera.intrinsics: no width_px",
           "Error: commandlet exited 1"]), encoding="utf-8")

    words = RunManager.commandlet_last_words(log)
    assert "REFUSED camera.intrinsics" in words
    assert "Error: commandlet exited 1" in words
    assert "LogSomethingElse" not in words, (
        "the named lines are the point; the noise is what buries them")


def test_an_unrecognised_failure_still_says_something(tmp_path):
    """A log with no line this code knows about must not come back
    empty -- that would be the silence the change exists to remove."""
    from webapp.runs import RunManager

    log = tmp_path / "render.log"
    log.write_text("something went wrong in a way nobody anticipated\n" * 3,
                   encoding="utf-8")
    assert "nobody anticipated" in RunManager.commandlet_last_words(log)


def test_a_missing_log_is_not_a_crash(tmp_path):
    from webapp.runs import RunManager

    assert RunManager.commandlet_last_words(tmp_path / "nope.log") == ""


# -- one camera's frames, with one camera's labels -----------------------

@pytest.fixture
def labelled_run(tmp_path, monkeypatch):
    """A finished two-camera run whose manifest carries real records."""
    monkeypatch.setattr(manager, "out_root", tmp_path)
    out = tmp_path / "run_lbl"
    for camera_id in ("chase0", "tower0"):
        (out / "frames" / camera_id).mkdir(parents=True)
        (out / "frames" / camera_id / "frame_0000.png").write_bytes(_png())

    def record(camera_id, index):
        return {
            "index": index, "camera_id": camera_id,
            "file": f"frames/{camera_id}/frame_{index:04d}.png",
            "t_s": 1.0 * index, "sample_index": index * 10,
            "position_north_m": 1.0, "position_east_m": 2.0,
            "position_alt_m": 3.0,
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0,
            "focal_length_mm": 35.0, "sensor_width_mm": 36.0,
            "sensor_height_mm": 20.25, "width_px": 1280, "height_px": 720,
            "near_m": 0.1, "far_m": 100000.0,
            "principal_point_px": [640.0, 360.0],
            "fx_px": 1244.4, "fy_px": 1244.4,
            "aircraft": {"north_m": 9.0, "east_m": 8.0, "alt_m": 7.0,
                         "roll_deg": 0.0, "pitch_deg": 1.0,
                         "heading_deg": 2.0},
        }

    (out / "capture_manifest.json").write_text(json.dumps({
        "manifest_version": 3, "spec_digest": "a" * 64,
        "simulation_digest": "b" * 64, "output_digest": "c" * 64,
        "solve_source": "host flight", "seed": 0, "aircraft": "B747",
        "scene": {"key": "terrain", "terrain": "x", "terrain_sha256": "d"},
        "frame": {"crs": "EPSG:32631", "origin_x_m": 1.0},
        "landmarks": [{"name": "peak", "north_m": 0.0, "east_m": 0.0,
                       "alt_m": 0.0}],
        "software_revision": "deadbeef",
        "cameras": [{"camera_id": "chase0", "preset": "chase",
                     "capture_count": 2, "schedule_basis": "count 2"},
                    {"camera_id": "tower0", "preset": "tower",
                     "capture_count": 1, "schedule_basis": "count 1"}],
        "frames": [record("chase0", 0), record("chase0", 1),
                   record("tower0", 0)],
    }), encoding="utf-8")

    from webapp.runs import RunState

    state = RunState(run_id="run_lbl")
    state.status = "done"
    manager.runs["run_lbl"] = state
    return out


def test_one_camera_s_manifest_carries_only_its_frames(labelled_run):
    """The whole-run manifest interleaves every camera's frames in one
    list, which is right for verification and wrong for a person -- or a
    training pipeline -- that wants "the tower view"."""
    body = TestClient(app).get(
        "/runs/run_lbl/cameras/chase0/manifest.json").json()
    assert body["camera"]["camera_id"] == "chase0"
    assert [f["index"] for f in body["frames"]] == [0, 1]
    assert all(f["camera_id"] == "chase0" for f in body["frames"])


def test_one_camera_s_manifest_carries_the_context_it_needs(labelled_run):
    """Positions in grid metres about a recorded origin mean nothing
    without the CRS, and the labels mean nothing without knowing which
    flight they were solved over. Both ride along."""
    body = TestClient(app).get(
        "/runs/run_lbl/cameras/tower0/manifest.json").json()
    assert body["frame"]["crs"] == "EPSG:32631"
    assert body["solve_source"] == "host flight"
    assert body["landmarks"][0]["name"] == "peak"
    assert body["aircraft"] == "B747"
    assert body["spec_digest"] and body["output_digest"]
    assert body["run_id"] == "run_lbl"


def test_the_per_camera_route_is_not_swallowed_by_the_image_route(
        labelled_run):
    """`/runs/{id}/{kind}/{camera}/{name}` also matches this path, and
    FastAPI takes the first route declared. If the image route won, the
    answer would be a 404 for a manifest that exists."""
    reply = TestClient(app).get(
        "/runs/run_lbl/cameras/chase0/manifest.json")
    assert reply.status_code == 200
    assert reply.json()["camera"]["preset"] == "chase"


def test_a_camera_the_run_does_not_have_says_which_it_has(labelled_run):
    reply = TestClient(app).get(
        "/runs/run_lbl/cameras/nosuch/manifest.json")
    assert reply.status_code == 404
    assert "chase0" in reply.json()["error"]


@pytest.mark.parametrize("camera", ["..", "..%2f..", "a/b", "x" * 65])
def test_the_per_camera_route_refuses_an_unusable_name(labelled_run, camera):
    reply = TestClient(app).get(f"/runs/run_lbl/cameras/{camera}/manifest.json")
    assert reply.status_code == 404
    assert b"capture_manifest" not in reply.content


def test_a_clip_only_run_says_why_it_has_no_camera_manifest(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(manager, "out_root", tmp_path)
    (tmp_path / "bare").mkdir()
    reply = TestClient(app).get("/runs/bare/cameras/chase0/manifest.json")
    assert reply.status_code == 404
    assert "stated no cameras" in reply.json()["error"]


def test_the_frame_browser_is_served_and_reads_that_route():
    """The page the gallery links to. It has to exist, and it has to
    fetch the per-camera manifest rather than the whole-run one."""
    reply = TestClient(app).get("/frames.html")
    assert reply.status_code == 200
    assert "/cameras/" in reply.text and "manifest.json" in reply.text
    # Images are listed off the DIRECTORIES, not the manifest: a record
    # whose frame was never written must not render as a broken image.
    assert "/images" in reply.text


def test_the_gallery_links_to_each_camera_s_frames():
    page = (Path(__file__).resolve().parents[1]
            / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    assert "/frames.html?run=" in page
    assert "cameras/${id}/manifest.json" in page


# -- the points-of-view picker -------------------------------------------

def compiled_spec():
    from core.nl.compiler import compile_prompt

    return compile_prompt("fly the 747 at 10000 ft and 280 kt").to_dict()


def test_the_page_can_add_a_view_for_every_documented_preset():
    """Phase 1 asked for multiple cameras and the app could never state
    a second one: compile_prompt builds at most one CameraSpec and
    nothing appended to the list. Everything downstream already handled
    N -- the planners enumerate them, the capture stage solves a track
    each, the render runs one pass per camera.
    """
    from core.scenario.camera import CAMERA_PRESETS

    client = TestClient(app)
    spec = compiled_spec()
    assert spec.get("cameras") == []

    for preset in CAMERA_PRESETS:
        reply = client.post("/cameras", json={"spec": spec,
                                              "preset": preset})
        assert reply.status_code == 200, reply.json()
        spec = reply.json()["dict"]

    assert len(spec["cameras"]) == len(CAMERA_PRESETS)
    presets = [c["preset"] for c in reply.json()["cameras"]]
    assert presets == list(CAMERA_PRESETS)


def test_added_views_get_distinct_ids_and_keep_stated_ones():
    """A camera id NAMES A DIRECTORY (frames/<id>/), so two views sharing
    one id would put their frames in one place. The next free suffix is
    taken instead -- and no id already on the spec is touched, because
    renaming a stated field is exactly what this project refuses to do.
    """
    client = TestClient(app)
    spec = compiled_spec()
    for _ in range(3):
        spec = client.post("/cameras",
                           json={"spec": spec, "preset": "chase"}).json()["dict"]
    ids = [c["camera_id"]["value"] for c in spec["cameras"]]
    assert ids == ["chase", "chase1", "chase2"]
    assert len(set(ids)) == 3


def test_a_view_the_vocabulary_does_not_have_is_refused_by_name():
    client = TestClient(app)
    reply = client.post("/cameras", json={"spec": compiled_spec(),
                                          "preset": "helicopter"})
    assert reply.status_code == 409
    assert reply.json()["refused"] == "camera.preset"


def test_a_view_can_be_removed_and_the_rest_keep_their_ids():
    client = TestClient(app)
    spec = compiled_spec()
    for preset in ("chase", "tower", "cockpit"):
        spec = client.post("/cameras",
                           json={"spec": spec, "preset": preset}).json()["dict"]
    reply = client.post("/cameras", json={"spec": spec, "remove": 1})
    assert reply.status_code == 200
    assert [c["camera_id"] for c in reply.json()["cameras"]] == \
        ["chase", "cockpit"]


def test_removing_a_camera_that_is_not_there_says_so():
    client = TestClient(app)
    reply = client.post("/cameras", json={"spec": compiled_spec(),
                                          "remove": 4})
    assert reply.status_code == 400
    assert "does not exist" in reply.json()["error"]


def test_added_views_reach_the_capture_stage():
    """The routing decision the whole picker depends on: once the spec
    states cameras, the run is CAPTURED (poses solved in Python, one
    pass per camera, a manifest) rather than clipped."""
    from core.scenario.spec import ScenarioSpec

    client = TestClient(app)
    spec = compiled_spec()
    for preset in ("chase", "tower"):
        spec = client.post("/cameras",
                           json={"spec": spec, "preset": preset}).json()["dict"]
    assert wants_capture(ScenarioSpec.from_dict(spec))


def test_the_picker_offers_exactly_the_documented_presets():
    """The page's list and the validator's have to be the same set, or a
    button offers a view the run will refuse."""
    import re

    from core.scenario.camera import CAMERA_PRESETS

    page = (Path(__file__).resolve().parents[1]
            / "webapp" / "static" / "index.html").read_text(encoding="utf-8")
    block = re.search(r"const CAMERA_VIEWS = \[(.*?)\];", page, re.S)
    assert block, "the page's view list moved or was renamed"
    offered = re.findall(r'\["(\w+)"', block.group(1))
    assert offered == list(CAMERA_PRESETS)


# -- one flight, not two, on the web path --------------------------------

def test_each_camera_pass_records_its_own_host_flight():
    """THE REGRESSION.

    ``verify_flight_agreement`` keys host telemetry by the directory it
    sits in, so every camera pass needs its OWN ``-telemetry=`` path.
    The web path handed every pass one shared file -- and it was
    ``<run>/telemetry.json``, the headless PRE-RUN the manifest was
    solved from. So no per-camera host recording existed anywhere on
    disk and flight_agreement reported NOT RUN on every web run ever
    made, while the CLI reported a real number.
    """
    from webapp.capture import render_passes

    seen = {}

    def fake_render(card, frames, extra, telemetry):
        seen[frames.name] = telemetry
        (frames / "render.json").write_text("{}", encoding="utf-8")
        return True

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        render_passes(root / "card.json", root / "frames",
                      ["chase0", "tower0"], fake_render)

    assert sorted(seen) == ["chase0", "tower0"]
    for camera_id, path in seen.items():
        assert path.name == "host_telemetry.json"
        assert path.parent.name == camera_id, (
            "the host recording has to land in the camera's own "
            "directory or flight_agreement cannot key it")
    assert len(set(seen.values())) == 2, (
        "two passes sharing one telemetry path is the bug: the second "
        "overwrites the first and neither frame set is graded against "
        "the flight that produced it")


def test_the_web_manifest_names_the_flight_it_was_solved_over():
    """A web run's manifest has to answer the same question the CLI's
    does. It used to be hardcoded to the pre-run because that was the
    only flight the web path had."""
    import inspect

    from webapp import capture

    source = inspect.getsource(capture.write_manifest)
    assert 'solve_source=solved["solve_source"]' in source, (
        "the manifest must carry the flight the poses were actually "
        "solved over, not a constant")
    assert 'output_digest=solved["output_digest"]' in source


def test_resolve_over_host_reports_the_host_flight(tmp_path):
    """Re-solving over the host's recording changes what the manifest
    describes, and says so."""
    import json as _json

    from core.capture.hostflight import REQUIRED_CHANNELS
    from core.capture.manifest import SOLVE_HOST_FLIGHT, SOLVE_PRE_RUN
    from core.capture.poses import SceneFrame, solve_pose_track
    from core.capture.schedule import solve_schedule
    from core.nl.compiler import compile_prompt
    from core.scenario.camera import CameraSpec
    from webapp.capture import resolve_over_host

    from tests.test_camera_poses import FRAME, make_columns

    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    camera = CameraSpec.defaulted(camera_id="chase0", preset="chase",
                                  aircraft="B747")
    camera.set("capture_count", 4, frm="test")
    spec.cameras = [camera]
    columns = make_columns(duration_s=14.0)

    solved = {
        "frame": FRAME, "columns": columns,
        "tracks": [solve_pose_track(columns, camera, FRAME)],
        "schedules": [solve_schedule(columns, camera, FRAME)],
        "result": None, "terrain_elevation_m": 0.0,
        "solve_source": SOLVE_PRE_RUN, "output_digest": "pre-run",
    }

    host = tmp_path / "host_telemetry.json"
    host.write_text(_json.dumps({"columns": {
        name: [float(v) for v in columns[name]]
        for name in REQUIRED_CHANNELS}}), encoding="utf-8")

    out = resolve_over_host(spec, solved, host)
    assert out["solve_source"] == SOLVE_HOST_FLIGHT
    assert out["output_digest"] != "pre-run"
    assert len(out["tracks"]) == 1


def test_an_unreadable_host_flight_refuses_by_name(tmp_path):
    """Named, like every other camera refusal -- not a stack trace in a
    background thread the page can only report as 'failed'."""
    from webapp.capture import CaptureError, resolve_over_host

    bad = tmp_path / "host_telemetry.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(CaptureError) as caught:
        resolve_over_host(None, {}, bad)
    assert caught.value.constraint == "capture.host_flight"


def test_the_legacy_flags_refuse_multi_camera_by_name():
    """camera_render_flags is the LEGACY single-pass path. If a
    multi-camera spec ever reaches it, it must refuse rather than render
    cameras[0] and drop the rest silently -- which is what it used to
    do."""
    from core.nl.compiler import compile_prompt
    from core.scenario.camera import CameraSpec
    from webapp.runs import camera_render_flags

    spec = compile_prompt("fly the 747 at 10000 ft and 280 kt")
    spec.cameras = [
        CameraSpec.defaulted(camera_id="a", preset="chase", aircraft="B747"),
        CameraSpec.defaulted(camera_id="b", preset="tower", aircraft="B747"),
    ]
    with pytest.raises(ValueError, match="camera.multi_render"):
        camera_render_flags(spec)


def test_the_run_publishes_the_flight_its_panels_read():
    """<run>/telemetry.json is what the aero panel and the effect report
    read. It used to be written by the render pass; giving each camera
    pass its OWN recording left nothing there, and a run that had just
    flown reported "no recorded telemetry for this run".

    The host's solve flight is the right one to publish: it is the
    flight the pixels show, and host_determinism asserts every render
    pass matched it.
    """
    import inspect

    from webapp import runs

    source = inspect.getsource(runs.RunManager._render_flow)
    assert 'shutil.copyfile(host_telemetry, out / "telemetry.json")' in source


# -- that many seconds of that view --------------------------------------

def test_a_page_added_view_captures_the_whole_clip():
    """Picking a viewpoint and a clip length should give that many
    seconds of that view. It used to give three stills: the default
    trigger is one capture per second, so a 3 s clip produced 3 frames
    and the run read as a handful of photographs rather than a
    simulation from that angle.

    Planned, not set: the page chose it, the user did not state it, so
    an edit in the review table still wins.
    """
    client = TestClient(app)
    reply = client.post("/cameras", json={"spec": compiled_spec(),
                                          "preset": "tower"})
    fields = {f["name"]: f for f in reply.json()["cameras"][0]["fields"]}
    assert fields["trigger"]["value"] == "continuous"
    assert fields["trigger"]["source"] == "derived"


def test_continuous_captures_every_recorded_sample():
    """The whole flight as a sequence, at the rate it was recorded --
    which is the telemetry rate, not the render's 30 fps."""
    from core.capture.schedule import solve_schedule
    from core.scenario.camera import CameraSpec

    from tests.test_camera_poses import FRAME, make_columns

    columns = make_columns(duration_s=22.0)
    camera = CameraSpec.defaulted(camera_id="chase", preset="chase",
                                  aircraft="B747")
    camera.set("trigger", "continuous", frm="test")
    schedule = solve_schedule(columns, camera, FRAME)
    assert len(schedule) == len(columns["t"])
    assert schedule.times[0] == columns["t"][0]
    assert schedule.times[-1] == columns["t"][-1]
    assert "every recorded sample" in schedule.basis


def test_continuous_still_honours_a_stated_count():
    """A stated capture_count is a CONTRACT everywhere else, and it does
    not stop being one here: padding or truncating to fit would be the
    manifest naming frames the flight did not take."""
    from core.capture.schedule import ScheduleError, solve_schedule
    from core.scenario.camera import CameraSpec

    from tests.test_camera_poses import FRAME, make_columns

    columns = make_columns(duration_s=4.0)
    camera = CameraSpec.defaulted(camera_id="chase", preset="chase",
                                  aircraft="B747")
    camera.set("trigger", "continuous", frm="test")
    camera.set("capture_count", 7, frm="test")
    with pytest.raises(ScheduleError, match="count contract"):
        solve_schedule(columns, camera, FRAME)


def test_a_camera_clip_is_encoded_at_the_rate_its_frames_were_taken(tmp_path):
    """A continuous capture runs at the recorded telemetry rate, not at
    the render's 30 fps. Encoding at 30 would play the flight three
    times too fast."""
    from webapp.runs import RunManager

    manifest = tmp_path / "capture_manifest.json"
    manifest.write_text(json.dumps({"frames": [
        {"camera_id": "chase", "t_s": i * 0.1} for i in range(20)
    ]}), encoding="utf-8")
    assert RunManager._capture_fps(manifest, "chase") == pytest.approx(10.0)


def test_the_capture_rate_falls_back_rather_than_crashing(tmp_path):
    from webapp.runs import RunManager

    assert RunManager._capture_fps(tmp_path / "gone.json", "chase") > 0
    empty = tmp_path / "capture_manifest.json"
    empty.write_text(json.dumps({"frames": []}), encoding="utf-8")
    assert RunManager._capture_fps(empty, "chase") > 0


def test_every_view_gets_its_own_clip(tmp_path, monkeypatch):
    """The gallery used to show one clip for the whole run, from
    whichever camera happened to be first. A view is what the user
    picked, so each one gets the flight from that angle."""
    from webapp.runs import RunManager

    out = tmp_path / "run"
    frames = out / "frames"
    for camera_id in ("chase", "tower"):
        (frames / camera_id).mkdir(parents=True)
        for i in range(3):
            (frames / camera_id / f"frame_{i:04d}.png").write_bytes(_png())
    (frames / "still").mkdir()
    (frames / "still" / "frame_0000.png").write_bytes(_png())
    (out / "capture_manifest.json").write_text(
        json.dumps({"frames": []}), encoding="utf-8")

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"mp4")

        class Done:
            returncode = 0
        return Done()

    monkeypatch.setattr("webapp.runs.subprocess.run", fake_run)
    made = RunManager()._encode_camera_clips(
        out, frames, ["chase", "tower", "still"])
    assert made == ["chase", "tower"], "a single still is not a clip"
    assert (out / "clips" / "chase.mp4").is_file()
    assert (out / "clips" / "tower.mp4").is_file()


def test_a_camera_clip_is_served_and_guarded(labelled_run):
    client = TestClient(app)
    clips = labelled_run / "clips"
    clips.mkdir()
    (clips / "chase0.mp4").write_bytes(b"mp4")

    good = client.get("/runs/run_lbl/clips/chase0.mp4")
    assert good.status_code == 200
    assert good.headers["content-type"] == "video/mp4"

    for bad in ("..", "a/b", "x" * 65):
        assert client.get(
            f"/runs/run_lbl/clips/{bad}.mp4").status_code == 404


def test_the_inventory_lists_the_clips_that_exist(labelled_run):
    """Read off the directory like every other kind, so a clip the
    encoder failed to make is absent rather than a broken video."""
    from webapp.capture import inventory

    assert inventory(labelled_run)["clips"] == []
    (labelled_run / "clips").mkdir()
    (labelled_run / "clips" / "tower0.mp4").write_bytes(b"mp4")
    assert inventory(labelled_run)["clips"] == ["tower0"]


def test_the_frame_count_is_ten_a_second_whatever_the_clip():
    """The number the instructor actually sees, pinned to the rate.

    "why is it only 3 frames" had one cause with three doors: the
    interval default is one capture a second, so ANY path that built a
    camera without a number produced a handful of stills. The rate is
    not a guess -- core.scenario.card.SAMPLE_INTERVAL_S is the interval
    the run card hands the engine's recorder, and the headless recorder
    matches it -- so `continuous` is exactly 1/SAMPLE_INTERVAL_S frames
    per second of clip. This reads that constant rather than repeating
    it, so a change to the record rate lands here rather than in a
    surprise.
    """
    from core.capture.schedule import solve_schedule
    from core.scenario.card import SAMPLE_INTERVAL_S
    from core.scenario.camera import CameraSpec, plan_full_capture

    camera = CameraSpec.defaulted(camera_id="chase", preset="chase",
                                  aircraft="B747")
    assert plan_full_capture(camera, frm="test") is True

    for seconds in (3.0, 15.0, 22.0):
        n = int(round(seconds / SAMPLE_INTERVAL_S)) + 1
        columns = {"t": [round(i * SAMPLE_INTERVAL_S, 6) for i in range(n)]}
        assert len(solve_schedule(columns, camera)) == n
        # The complaint, as an assertion: never a contact sheet again.
        assert len(solve_schedule(columns, camera)) > 15


def test_the_frame_browser_does_not_fetch_every_png_at_once():
    """A continuous capture is hundreds of records, each with up to
    three images. The page must not open six hundred requests to show
    the two frames on the first screen."""
    page = (Path(__file__).resolve().parents[1]
            / "webapp" / "static" / "frames.html").read_text(encoding="utf-8")
    assert 'loading="lazy"' in page
    assert page.count("<img") == page.count('loading="lazy"'), (
        "every frame image in the browser must be lazily loaded")
