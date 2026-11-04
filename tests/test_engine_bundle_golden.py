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

import hashlib
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


# -- the relocated-bundle rule, on a tiny synthetic run directory -------------
#
# The fixture above was rendered on Windows and cites that machine's files
# by absolute path (the generated mesh manifest, the bake's geoid crop). On
# any other machine the verifier may take a same-named file under the run
# directory in their place ONLY when the card's recorded sha256 matches it;
# a same-named file the card does not vouch for is refused by the gate's own
# name, naming the path and the sha (core/capture/verify.py, module docstring).

WINDOWS_MESH_PATH = r"C:\Users\someone\flightsim\assets\generated\c172p\mesh_manifest.json"
WINDOWS_BAKE = r"C:\Users\someone\flightsim\runs\terrain\grand_canyon"


def test_a_relocated_file_is_taken_only_with_its_recorded_sha(tmp_path):
    from core.capture.verify import _REPO, _card_candidate, _named_file

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    data = b'{"version": 3}'
    (run_dir / "mesh_manifest.json").write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    candidate = _card_candidate(WINDOWS_MESH_PATH, _REPO)
    assert not candidate.exists() and candidate.name == "mesh_manifest.json"
    assert _REPO not in candidate.parents, "an absolute path is not joined to the repository"
    found, why = _named_file(candidate, sha, run_dir)
    assert why is None and found == run_dir / "mesh_manifest.json"
    found, why = _named_file(candidate, "00" * 32, run_dir)
    assert found is None
    assert "mesh_manifest.json" in why and "00" * 8 in why and sha[:16] in why
    found, why = _named_file(candidate, None, run_dir)
    assert found is None and "no sha256" in why and "mesh_manifest.json" in why
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _named_file(candidate, sha, empty) == (None, None)
    # A committed copy named for its aircraft, in a sub-folder of the run
    # (the fixture's cited/c172p_mesh_manifest.json), is the same file when
    # its sha says so; a file of any other name is not looked at, whatever
    # its bytes.
    cited = tmp_path / "cited_run" / "cited"
    cited.mkdir(parents=True)
    (cited / "c172p_mesh_manifest.json").write_bytes(data)
    (cited / "mesh_manifest.txt").write_bytes(data)
    assert _named_file(candidate, sha, cited.parent) == (cited / "c172p_mesh_manifest.json", None)
    found, why = _named_file(candidate, "00" * 32, cited.parent)
    assert found is None and "c172p_mesh_manifest.json" in why
    (cited / "c172p_mesh_manifest.json").unlink()
    assert _named_file(candidate, sha, cited.parent) == (None, None)
    # A relative card path is the repository's, read with the card's separators.
    relative = _card_candidate(r"assets\generated\c172p\mesh_manifest.json", _REPO)
    assert relative == _REPO / "assets" / "generated" / "c172p" / "mesh_manifest.json"


def _run_citing_a_relocated_mesh(tmp_path):
    """A fabricated run whose directory holds a version-3 mesh manifest 10 %
    taller than the painted box, and its manifest (in memory) citing that
    file at a Windows path that is not on this machine."""
    from tests.test_annotation_gates import (fabricate_run, fabricated_mesh_manifest,
                                             manifest_of)

    run_dir = tmp_path / "run"
    fabricate_run(run_dir)
    manifest = manifest_of(run_dir)
    mesh = json.dumps(fabricated_mesh_manifest(manifest["airframe"], taller=1.1)).encode("utf-8")
    (run_dir / "mesh_manifest.json").write_bytes(mesh)
    return manifest, run_dir, hashlib.sha256(mesh).hexdigest()


def test_mask_vs_geometry_grades_a_relocated_mesh_only_when_the_card_vouches_for_it(tmp_path):
    from core.capture.verify import FAIL_FILES, FAIL_MASK_OFFSET, verify_mask_vs_geometry

    manifest, run_dir, sha = _run_citing_a_relocated_mesh(tmp_path)
    cite = manifest.setdefault("assets", {})
    # Recorded sha matches: the relocated mesh IS the hull, and the taller
    # extent fails the extent clause naming the mesh as its basis.
    cite["mesh_manifest"] = {"path": WINDOWS_MESH_PATH, "sha256": sha, "note": None}
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_MASK_OFFSET, check.detail
    assert "mesh manifest version 3 measured extent" in check.detail
    assert WINDOWS_MESH_PATH in check.detail
    # Wrong sha: refused by name, the path and both shas named; the hull is
    # never taken from the unproven file.
    cite["mesh_manifest"] = {"path": WINDOWS_MESH_PATH, "sha256": "00" * 32, "note": None}
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_FILES, check.detail
    assert "mesh_manifest.json" in check.detail and "00" * 8 in check.detail
    assert sha[:16] in check.detail
    # No sha recorded: refused by name as well.
    cite["mesh_manifest"] = {"path": WINDOWS_MESH_PATH, "sha256": None, "note": None}
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_FILES, check.detail
    assert "no sha256" in check.detail and "mesh_manifest.json" in check.detail
    # A card naming no mesh at all is graded against the airframe box as before.
    cite["mesh_manifest"] = {"path": None, "sha256": None, "note": "none on the producer"}
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == "PASS", check.detail


def test_datum_independent_refuses_a_relocated_crop_the_block_does_not_vouch_for(tmp_path):
    from core.capture.verify import FAIL_DATUM, verify_datum_independent

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grand_canyon_geoid.gtx").write_bytes(b"not the crop the bake wrote")
    manifest = {
        "scene": {"terrain": WINDOWS_BAKE},
        "datum": {"undulation_m": -28.0, "gtx": {
            "file": "grand_canyon_geoid.gtx", "samples_file": "grand_canyon_geoid.json",
            "sha256": "ab" * 32, "samples_sha256": "cd" * 32}},
    }
    check = verify_datum_independent(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_DATUM, check.detail
    assert "grand_canyon_geoid.gtx" in check.detail and "ab" * 8 in check.detail
    assert "C:/Users/someone/flightsim/runs/terrain/grand_canyon_geoid.gtx" in check.detail
    manifest["datum"]["gtx"]["sha256"] = None
    check = verify_datum_independent(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_DATUM, check.detail
    assert "no sha256" in check.detail
    (run_dir / "grand_canyon_geoid.gtx").unlink()
    check = verify_datum_independent(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_DATUM, check.detail
    assert "is absent" in check.detail
