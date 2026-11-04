"""One real engine frame, committed as a fixture and pinned.

``tests/fixtures/engine_bundle_min/`` is a whole minimal run directory
(``capture_manifest.json`` plus ``frames/<camera>/`` with render.json, the
frame's mask, depth and label files) rendered on Windows: 1 camera, 1
frame, lowest resolution. Windows commits data only: the pinned values
live in ``GOLDEN.json`` beside it (the tight box, visible fraction and
depth median of the aircraft's record) and the run it was copied from in
``RUN_ID``; this test is final code. Until the fixture is committed every
test here skips with one named reason -- the one allowed skip.

GOLDEN.json: ``{"camera_id", "frame", "int_id", "bbox_2d_tight":
[u0, v0, u1, v1], "visible_fraction", "depth_median_m"}``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from core.capture.manifest import read_capture_manifest
from core.capture.verify import FAIL, verify_run

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "engine_bundle_min"
SKIP_REASON = "windows: fixture engine_bundle_min not committed yet"
needs_fixture = pytest.mark.skipif(not FIXTURE.exists(), reason=SKIP_REASON)

FIXTURE_MAX_BYTES = 2 * 1024 * 1024
#: Exact for the pixel box; the ranges are floats through JSON.
FRACTION_TOL = 1e-6
DEPTH_REL_TOL = 1e-4


def _golden():
    return json.loads((FIXTURE / "GOLDEN.json").read_text(encoding="utf-8"))


def _record(golden):
    manifest = read_capture_manifest(FIXTURE / "capture_manifest.json")
    for frame in manifest["frames"]:
        if str(frame["camera_id"]) != str(golden["camera_id"]):
            continue
        if Path(str(frame["file"])).name != golden["frame"]:
            continue
        for entry in frame["labels"]["objects"]:
            if entry.get("int_id") == golden["int_id"]:
                return entry
    raise AssertionError(f"no record for {golden} in the fixture's manifest")


@needs_fixture
def test_fixture_under_2mb():
    total = sum(p.stat().st_size for p in FIXTURE.rglob("*") if p.is_file())
    assert total < FIXTURE_MAX_BYTES, f"{total} bytes"
    assert (FIXTURE / "RUN_ID").read_text(encoding="utf-8").strip()


@needs_fixture
def test_tight_box_pinned():
    golden = _golden()
    record = _record(golden)
    assert [float(v) for v in record["bbox_2d_tight"]] == [float(v) for v in golden["bbox_2d_tight"]]
    # ... and is the box of the committed mask's own pixels, to a pixel.
    camera = FIXTURE / "frames" / str(golden["camera_id"])
    render = json.loads((camera / "render.json").read_text(encoding="utf-8"))
    mask_name = next(r["labels"]["mask"] for r in render["frame_records"]
                     if r.get("frame") == golden["frame"])
    mask = np.asarray(Image.open(camera / mask_name))
    ys, xs = np.nonzero(mask == golden["int_id"])
    assert [float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
            float(ys.max()) + 1.0] == [float(v) for v in golden["bbox_2d_tight"]]


@needs_fixture
def test_visible_fraction_pinned():
    golden = _golden()
    assert _record(golden)["visible_fraction"] == pytest.approx(
        golden["visible_fraction"], abs=FRACTION_TOL)


@needs_fixture
def test_depth_median_pinned():
    golden = _golden()
    assert _record(golden)["depth_median_m"] == pytest.approx(
        golden["depth_median_m"], rel=DEPTH_REL_TOL)


@needs_fixture
def test_verify_run_has_no_fail():
    report = verify_run(FIXTURE)
    failed = [f"{c.name}: {c.detail}" for c in report.checks if c.status == FAIL]
    assert not failed, failed
