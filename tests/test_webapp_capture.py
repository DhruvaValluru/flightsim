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
