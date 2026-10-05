"""The box and depth checks graded frame by frame, not only run by run.

``box_vs_mask`` and ``depth_vs_geometry`` (core/capture/verify.py) stop
at the first object-frame that fails and fail the whole run naming only
that one. This module runs THE SAME two check functions once per frame,
on a manifest holding just that frame, so every frame gets its own
verdict -- PASS, FAIL with the sentence that says why, or NOT RUN with
the reason -- and a reader can see every failing frame, not only the
first. Using the checks themselves (not a re-implementation) means the
per-frame verdict can never disagree with the run's: the run fails
exactly when some frame does.

Where the results go: ``frame_checks.json`` in the run directory (every
frame, plus the counts), and a ``checks`` section added to every frame's
own ``frame_NNNN.json``. Neither touches ``capture_manifest.json``, so the
run's verification stays bound to the manifest it graded.

A run without an engine render (a Linux or headless capture) has no ID
image or depth image to measure; every frame then reads NOT RUN with
that reason, stated, instead of a silent absence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

FRAME_CHECKS_JSON = "frame_checks.json"

NO_RENDER = ("not checked: no engine render for this frame (no ID image or "
             "depth image to measure). Only a run on the Windows Unreal host "
             "produces them; this frame keeps the predicted box and distance "
             "only")


def _per_frame_checks():
    from .verify import verify_box_vs_mask, verify_depth_vs_geometry

    return (("box_vs_mask", verify_box_vs_mask),
            ("depth_vs_geometry", verify_depth_vs_geometry))


def grade_frames(manifest: Dict, run_dir) -> Dict:
    """``{"frames": {file: {check: {status, detail, failure}, "ok": bool}},
    "counts": {check: {PASS: n, FAIL: n, NOT RUN: n}}, "failed_frames": [...]}``."""
    from . import verify

    run_dir = Path(run_dir)
    # Each check re-reads every camera's render.json; read them once for
    # the whole grading rather than once per frame.
    records = verify._engine_label_records(run_dir)
    original = verify._engine_label_records
    verify._engine_label_records = lambda _run_dir: records
    try:
        frames: Dict[str, Dict] = {}
        counts: Dict[str, Dict[str, int]] = {}
        failed: List[str] = []
        for record in manifest.get("frames", []):
            file = str(record.get("file"))
            camera = str(record.get("camera_id"))
            name = Path(file).name
            rendered = name in records.get(camera, {})
            one = dict(manifest, frames=[record])
            result: Dict = {}
            for check_name, check in _per_frame_checks():
                if not rendered:
                    entry = {"status": verify.NOT_RUN, "detail": NO_RENDER, "failure": None}
                else:
                    outcome = check(one, run_dir)
                    entry = {"status": outcome.status, "detail": outcome.detail,
                             "failure": outcome.failure}
                result[check_name] = entry
                counts.setdefault(check_name, {}).setdefault(entry["status"], 0)
                counts[check_name][entry["status"]] += 1
            result["ok"] = all(v["status"] != verify.FAIL for k, v in result.items()
                               if isinstance(v, dict))
            if not result["ok"]:
                failed.append(file)
            frames[file] = result
    finally:
        verify._engine_label_records = original
    return {"frames": frames, "counts": counts, "failed_frames": failed,
            "about": ("box_vs_mask and depth_vs_geometry run once per frame "
                      "(the same check functions as the run's verdict). PASS / "
                      "FAIL / NOT RUN per frame; a FAIL names why.")}


def write_frame_checks(run_dir, result: Dict) -> Path:
    """Write ``frame_checks.json`` and add each frame's verdict to its own
    sidecar (``checks``). Sidecars that do not exist are left alone."""
    run_dir = Path(run_dir)
    path = run_dir / FRAME_CHECKS_JSON
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    for file, checks in result["frames"].items():
        if not file.endswith(".png"):
            continue
        sidecar = run_dir / (file[:-len(".png")] + ".json")
        if not sidecar.is_file():
            continue
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        data["checks"] = checks
        sidecar.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def read_frame_checks(run_dir) -> Dict[str, Dict]:
    """``{file: checks}`` from a run's ``frame_checks.json``, or ``{}``."""
    path = Path(run_dir) / FRAME_CHECKS_JSON
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("frames") or {}
    except (OSError, ValueError):
        return {}
