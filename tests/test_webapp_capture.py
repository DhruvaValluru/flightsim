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
        "manifest_version": 2,
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
    assert manifest.json()["manifest_version"] == 2
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
