"""The offline ACES 2.0 SDR display step (core/capture/display.py) and the
CC0 show LUTs (scripts/make_show_luts.py, assets/looks/)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from core.capture import display
from core.capture.beauty_look import PIXEL_MOVING_KEYS

REPO = Path(__file__).resolve().parents[1]

HAVE_OCIO = importlib.util.find_spec("PyOpenColorIO") is not None
HAVE_EXR = importlib.util.find_spec("OpenEXR") is not None
NO_OCIO = ("PyOpenColorIO is not installed (optional: "
           "pip install --require-hashes --no-deps -r requirements-display.txt)")
NO_EXR = "OpenEXR is not installed (optional: requirements-display.txt)"

#: Vendored reference, computed once with the pinned wheel (opencolorio
#: 2.5.2, macOS arm64, 2026-11-09): Linear Rec.709 (sRGB) 0.18 grey ->
#: sRGB - Display / ACES 2.0 - SDR 100 nits (Rec.709). Display code value.
REF_GREY_18 = 0.3491875
#: The ACES 2.0 view is analytic in OCIO 2.5's CPU path; float32
#: differences across platforms are ~1e-6. 1e-4 is ~1/40 of an 8-bit step.
REF_TOLERANCE = 1e-4


def _make_luts():
    spec = importlib.util.spec_from_file_location(
        "make_show_luts", REPO / "scripts" / "make_show_luts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_show_luts"] = module
    spec.loader.exec_module(module)
    return module


def _identity_cube(path: Path, size: int) -> Path:
    grid = np.arange(size) / (size - 1)
    lines = [f"LUT_3D_SIZE {size}"]
    for b in grid:
        for g in grid:
            for r in grid:
                lines.append(f"{r:.6f} {g:.6f} {b:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# -- LUTs ---------------------------------------------------------------------

def test_identity_cube_is_a_bit_exact_pass_through(tmp_path):
    cube = _identity_cube(tmp_path / "identity.cube", 33)
    rng = np.random.default_rng(7)
    img = rng.random((16, 16, 3), dtype=np.float32)
    img[0, 0] = (0.0, 1.0, 0.5)
    out = display.apply_cube(img, cube)
    assert out.dtype == np.float32
    assert np.array_equal(out, img)


def test_two_point_identity_reproduces_its_inputs():
    table = np.zeros((2, 2, 2, 3))
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                table[b, g, r] = (r, g, b)
    rng = np.random.default_rng(3)
    img = rng.random((1000, 3))
    # Every ordering of the fractions (all six tetrahedra) and the ties.
    img[:6] = [(0.9, 0.5, 0.1), (0.9, 0.1, 0.5), (0.5, 0.1, 0.9),
               (0.5, 0.9, 0.1), (0.1, 0.9, 0.5), (0.1, 0.5, 0.9)]
    img[6:9] = [(0.5, 0.5, 0.5), (0.3, 0.3, 0.7), (0.7, 0.2, 0.7)]
    assert np.array_equal(display.tetrahedral(img, table), img)


def test_tetrahedral_interpolates_a_non_identity_table():
    # out = 2 * in, a linear map: tetrahedral interpolation is exact on it.
    table = np.zeros((3, 3, 3, 3))
    grid = np.array([0.0, 0.5, 1.0])
    for bi, b in enumerate(grid):
        for gi, g in enumerate(grid):
            for ri, r in enumerate(grid):
                table[bi, gi, ri] = (2 * r, 2 * g, 2 * b)
    img = np.array([[0.25, 0.6, 0.9], [1.5, -0.2, 0.5]])
    out = display.tetrahedral(img, table)
    assert np.allclose(out, 2 * np.clip(img, 0, 1))


def test_lut_generation_is_deterministic(tmp_path):
    make = _make_luts()
    index = make.generate(tmp_path)
    shipped = json.loads((REPO / "assets/looks/looks.json").read_text(encoding="utf-8"))
    assert index == shipped
    for entry in shipped["looks"]:
        assert entry["licence"] == "CC0-1.0"
        regenerated = (tmp_path / entry["file"]).read_bytes()
        on_disk = (REPO / "assets/looks" / entry["file"]).read_bytes()
        assert hashlib.sha256(regenerated).hexdigest() == entry["sha256"]
        assert regenerated == on_disk
    assert {e["name"] for e in shipped["looks"]} == {"warm_print", "broadcast_neutral"}


def test_show_luts_parse_and_stay_in_range():
    for name, entry in display.show_luts().items():
        table, lo, hi = display.read_cube(REPO / "assets/looks" / entry["file"])
        assert table.shape == (33, 33, 33, 3)
        assert table.min() >= 0.0 and table.max() <= 1.0
        # 18 % grey (ACEScct) stays near grey through either look.
        grey = display.tetrahedral(np.array([[0.4135884] * 3]), table, lo, hi)[0]
        assert np.all(np.abs(grey - 0.4135884) < 0.03), (name, grey)


# -- refusals ------------------------------------------------------------------

def test_refuses_a_png_without_its_linear_exr(tmp_path):
    png = tmp_path / "frame_0000.png"
    png.write_bytes(b"not read")
    with pytest.raises(display.DisplayError) as exc:
        display.load_linear(png)
    assert exc.value.constraint == "look.display_input"


def test_refuses_on_measure(tmp_path):
    with pytest.raises(display.DisplayError) as exc:
        display.check_quality({"scene": {"render_quality": "measure"}})
    assert exc.value.constraint == "look.display_on_measure"
    with pytest.raises(display.DisplayError):
        display.check_quality({})            # no quality named: refused too
    assert display.check_quality({"quality": "beauty"}) == "beauty"


def test_bundle_refusal_is_recorded_not_swallowed(tmp_path):
    # A beauty render with no linear EXR: refused, and the refusal is in
    # render.json so the missing _aces2.png is explained.
    (tmp_path / "render.json").write_text(json.dumps(
        {"quality": "beauty", "beauty_look": {}}), encoding="utf-8")
    (tmp_path / "frame_0000.png").write_bytes(b"x")
    record = display.apply_to_bundle(tmp_path, {"display": "aces2"})
    assert record["refused"] == "look.display_input"
    saved = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert saved["beauty_look"]["display"]["refused"] == "look.display_input"
    assert not (tmp_path / "frame_0000_aces2.png").exists()
    assert (tmp_path / "frame_0000.png").read_bytes() == b"x"


@pytest.mark.parametrize("payload", [{"scene": {"render_quality": "measure"}},
                                     {"quality": "measure", "beauty_look": {}},
                                     {}])
def test_measure_manifest_is_left_byte_identical(tmp_path, payload):
    # Writing beauty_look into a measure (or quality-less) render.json
    # flips has_look_record, so look_label_alignment would grade a bundle
    # it otherwise leaves NOT RUN. The refusal is returned, not written.
    from core.capture.beauty_look import has_look_record

    manifest = tmp_path / "render.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    before = manifest.read_bytes()
    (tmp_path / "frame_0000.png").write_bytes(b"x")
    record = display.apply_to_bundle(tmp_path, {"display": "aces2"})
    assert record["refused"] == "look.display_on_measure"
    assert manifest.read_bytes() == before
    assert has_look_record(json.loads(before)) == has_look_record(
        json.loads(manifest.read_bytes()))


def test_the_showcase_encoder_keeps_the_aces2_frames(tmp_path, monkeypatch):
    # The web app's camera-less path runs the display step, then
    # encode_clip, which prunes frames after a good encode. It used to
    # glob frame_*.png: every _aces2.png was deleted (render.json still
    # named them) and, for an odd frame count, the "middle frame" kept
    # was an _aces2.png while every engine PNG went.
    import subprocess
    from experiments import showcase_matrix

    clip = tmp_path / "clip.mp4"
    for i in range(3):
        (tmp_path / f"frame_{i:04d}.png").write_bytes(b"x")
        (tmp_path / f"frame_{i:04d}_aces2.png").write_bytes(b"x")

    def fake_run(command, capture_output):
        clip.write_bytes(b"mp4")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(showcase_matrix.subprocess, "run", fake_run)
    assert showcase_matrix.encode_clip(tmp_path, clip)
    assert sorted(p.name for p in tmp_path.glob("frame_*.png")) == [
        "frame_0000_aces2.png", "frame_0001.png", "frame_0001_aces2.png",
        "frame_0002_aces2.png"]


def test_missing_ocio_is_a_named_refusal(monkeypatch):
    monkeypatch.setitem(sys.modules, "PyOpenColorIO", None)
    with pytest.raises(display.DisplayError) as exc:
        display.ocio_view(np.zeros((1, 3), np.float32))
    assert exc.value.constraint == "look.display_unavailable"


def test_the_look_switch_hooks():
    import webapp.runs as runs

    look = runs.resolve_look_switch("cinematic_aces2", None)
    assert (look["quality"], look["lens"], look["display"]) == ("beauty", "cinematic", "aces2")
    assert display.commandlet_tokens(look) == ["-linear"]
    assert display.commandlet_tokens(runs.resolve_look_switch("cinematic", None)) == []
    assert display.commandlet_tokens(None) == []
    assert "cinematic_aces2" in runs.LOOK_CHOICES
    # The existing switch keeps its quality and lens (camera-motion-layer adds
    # its own key to it; this module adds none).
    assert {k: runs.LOOK_SWITCHES["cinematic"][k] for k in ("quality", "lens")} == {
        "quality": "beauty", "lens": "cinematic"}
    assert "display" not in runs.LOOK_SWITCHES["cinematic"]


def test_record_moves_no_pixels():
    record = display.display_record("frame_0000_aces2.png", version="2.5.2")
    assert record["pixel_moving"] is False
    assert not set(record) & set(PIXEL_MOVING_KEYS)
    assert record["ocio_config"] == "ocio://studio-config-v4.0.0_aces-v2.0_ocio-v2.5"
    assert record["ocio_config"] != "ocio://default"
    assert record["input"] == "linear_exr"
    assert record["input_basis"] == "UNVERIFIED pre-tonemap"
    assert record["lut"] is None


# -- OpenColorIO (optional) ------------------------------------------------------

@pytest.mark.skipif(not HAVE_OCIO, reason=NO_OCIO)
def test_aces2_sdr_view_matches_the_vendored_reference():
    patch = np.array([[0.18, 0.18, 0.18], [0.0, 0.0, 0.0]], dtype=np.float32)
    out = display.ocio_view(patch)
    assert np.all(np.abs(out[0] - REF_GREY_18) < REF_TOLERANCE), out[0]
    assert np.all(np.abs(out[1]) < 1e-6), "black must stay black"
    record = display.display_record("frame_0000_aces2.png")
    assert record["ocio_version"].startswith("2.")
    assert record["ocio_config"] == display.OCIO_CONFIG


@pytest.mark.skipif(not (HAVE_OCIO and HAVE_EXR), reason=f"{NO_OCIO}; {NO_EXR}")
def test_bundle_end_to_end(tmp_path):
    import Imath
    import OpenEXR
    from PIL import Image

    img = np.full((4, 6, 3), 0.18, np.float32)
    img[0, 0] = 0.0
    header = OpenEXR.Header(6, 4)
    header["channels"] = {c: Imath.Channel(Imath.PixelType(Imath.PixelType.HALF))
                          for c in "RGB"}
    handle = OpenEXR.OutputFile(str(tmp_path / "frame_0000_linear.exr"), header)
    handle.writePixels({c: img[..., i].astype(np.float16).tobytes()
                        for i, c in enumerate("RGB")})
    handle.close()
    Image.new("RGB", (6, 4), (1, 2, 3)).save(tmp_path / "frame_0000.png")
    engine_png = (tmp_path / "frame_0000.png").read_bytes()
    (tmp_path / "render.json").write_text(json.dumps(
        {"quality": "beauty", "beauty_look": {"grade": "x"}}), encoding="utf-8")
    record = display.apply_to_bundle(tmp_path, {"display": "aces2"}, lut="warm_print")
    assert "refused" not in record
    assert record["lut"]["name"] == "warm_print"
    out = np.asarray(Image.open(tmp_path / "frame_0000_aces2.png"))
    assert out[0, 0].tolist() == [0, 0, 0]
    assert (tmp_path / "frame_0000.png").read_bytes() == engine_png
    saved = json.loads((tmp_path / "render.json").read_text(encoding="utf-8"))
    assert saved["beauty_look"]["display"]["frames"] == ["frame_0000_aces2.png"]
