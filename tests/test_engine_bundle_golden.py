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


def _run_citing_a_relocated_mesh(tmp_path, taller=0.8, parts=()):
    """A fabricated run whose directory holds a version-3 mesh manifest
    ``taller`` times the painted box's height (20 % shorter by default,
    so the painted pixels poke out of it) naming ``parts`` as its part
    OBJs, none written, and its manifest (in memory) citing that file at
    a Windows path that is not on this machine."""
    from tests.test_annotation_gates import (fabricate_run, fabricated_mesh_manifest,
                                             manifest_of)

    run_dir = tmp_path / "run"
    fabricate_run(run_dir)
    manifest = manifest_of(run_dir)
    body = fabricated_mesh_manifest(manifest["airframe"], taller=taller)
    body["parts"] = list(parts)
    mesh = json.dumps(body).encode("utf-8")
    (run_dir / "mesh_manifest.json").write_bytes(mesh)
    return manifest, run_dir, hashlib.sha256(mesh).hexdigest()


def test_mask_vs_geometry_grades_a_relocated_mesh_only_when_the_card_vouches_for_it(tmp_path):
    from core.capture.verify import FAIL_FILES, FAIL_MASK_OFFSET, verify_mask_vs_geometry

    manifest, run_dir, sha = _run_citing_a_relocated_mesh(tmp_path)
    cite = manifest.setdefault("assets", {})
    # Recorded sha matches: the relocated mesh IS the hull, and the painted
    # pixels poking out of its shorter extent box fail, naming the mesh.
    cite["mesh_manifest"] = {"path": WINDOWS_MESH_PATH, "sha256": sha, "note": None}
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_MASK_OFFSET, check.detail
    assert "mesh manifest version 3 measured extent" in check.detail
    assert "outside the projected hull box" in check.detail
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


def test_a_vouched_mesh_without_its_vertex_files_bounds_the_silhouette_from_outside(tmp_path):
    """A12 retry 3, the Mac golden failure: the committed fixture holds
    the cited mesh manifest (sha-matched) but not the eight part OBJs the
    Windows machine has beside its own copy, so Windows grades the mask
    against the vertices' silhouette (130 px span) while the Mac has only
    the measured extent box (160.4x45.5 px, equal to the engine's own
    bbox_2d_hull to 0.01 px) and used to grade a real silhouette's extent
    against it (129x30 px: 24 % off). The box is an outer bound of the
    silhouette, so with the vertices absent the gate grades containment
    and names the missing files; with the OBJs beside the manifest the
    silhouette grade is back, as on the producing machine."""
    from core.capture.verify import (FAIL_MASK_OFFSET, PASS, _mesh_vertices_actor_m,
                                     verify_box_vs_mask, verify_mask_vs_geometry)

    manifest, run_dir, sha = _run_citing_a_relocated_mesh(tmp_path, taller=1.1,
                                                          parts=("body", "rudder"))
    manifest.setdefault("assets", {})["mesh_manifest"] = {
        "path": WINDOWS_MESH_PATH, "sha256": sha, "note": None}
    _mesh_vertices_actor_m.cache_clear()
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == PASS, check.detail
    assert "object-frames graded by containment only" in check.detail
    assert "2 of its 2 part OBJs are not beside" in check.detail
    assert "body.obj, rudder.obj" in check.detail and WINDOWS_MESH_PATH in check.detail
    # box_vs_mask: an IoU against an outer bound measures the box's slack,
    # not the paint, so that frame is not IoU-graded and the sentence says
    # so; the record's bbox_2d_tight is still re-counted to a pixel.
    check = verify_box_vs_mask(manifest, run_dir)
    assert check.status == PASS, check.detail
    assert "object-frames not IoU-graded" in check.detail
    assert "records' bbox_2d_tight re-counted" in check.detail and "vertex files" in check.detail
    # The vertices arrive beside the manifest (the extent box's corners, in
    # actor-frame centimetres as the converter writes them): the hull is
    # their silhouette again, and the 10 % taller mesh fails the extent
    # clause naming the vertices, exactly as the producing machine grades.
    mesh = json.loads((run_dir / "mesh_manifest.json").read_text(encoding="utf-8"))
    ext = mesh["mesh_extent_actor_m"]
    corners = [(x * 100.0, y * 100.0, z * 100.0)
               for x in ext["x"] for y in ext["y"] for z in ext["z"]]
    for part in mesh["parts"]:
        (run_dir / f"{part}.obj").write_text(
            "".join("v %.4f %.4f %.4f\n" % c for c in corners), encoding="utf-8")
    _mesh_vertices_actor_m.cache_clear()
    check = verify_mask_vs_geometry(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_MASK_OFFSET, check.detail
    assert "silhouette from 8 mesh vertices" in check.detail
    assert "containment" not in check.detail
    check = verify_box_vs_mask(manifest, run_dir)
    assert check.status == PASS and "not IoU-graded" not in check.detail, check.detail
    assert "lowest IoU 0." in check.detail


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
    # The card's path is echoed in the host's own separators (Windows prints
    # backslashes), so compare separator-neutrally.
    assert ("C:/Users/someone/flightsim/runs/terrain/grand_canyon_geoid.gtx"
            in check.detail.replace("\\", "/"))
    manifest["datum"]["gtx"]["sha256"] = None
    check = verify_datum_independent(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_DATUM, check.detail
    assert "no sha256" in check.detail
    (run_dir / "grand_canyon_geoid.gtx").unlink()
    check = verify_datum_independent(manifest, run_dir)
    assert check.status == FAIL and check.failure == FAIL_DATUM, check.detail
    assert "is absent" in check.detail
