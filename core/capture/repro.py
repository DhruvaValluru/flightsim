"""Render reproducibility: measure it, and say exactly what was measured.

VALIDITY has said since Phase 0 that physics is bit-reproducible and
rendering is not. That is a claim about Movie Render Queue, and this
system does not use it: the frames come from an offscreen SceneCapture
in a commandlet, warmed up for a fixed number of captures, with manual
exposure, async compilation finished before the first frame -- every
input the same on every run. Whether the pixels come out the same is a
question, and this module is how it is answered.

Two frame sets, rendered from ONE card by ONE build, are compared frame
by frame: SHA-256 of the PNG bytes first (the engine records its own
per frame in render.json; the file's is computed here), and where they
differ, the per-pixel difference is measured -- maximum absolute over
any channel, mean absolute, and the fraction of pixels that differ at
all. The verdict vocabulary is fixed and small:

    bit-identical  every frame's bytes are the same in both sets
    bounded        at least one frame differs; the numbers above bound
                   by how much
    incomplete     a frame present in one set is absent from the other
                   -- no comparison of what is not there

Nothing here rounds, thresholds or forgives: a one-bit difference in
one pixel is "bounded", with max 1 and fraction 1/N, and the report
says so. What a bounded result MEANS for a dataset is VALIDITY's to
state, from these numbers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional

BIT_IDENTICAL = "bit-identical"
BOUNDED = "bounded"
INCOMPLETE = "incomplete"


def frame_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frame_names(directory: Path) -> List[str]:
    """The plain frames of a render directory, in order: frame_NNNN.png
    and nothing else (masks, depth and sensor frames carry suffixes)."""
    return sorted(p.name for p in Path(directory).glob("frame_*.png")
                  if p.stem[-4:].isdigit() and len(p.stem) == len("frame_0000"))


def engine_digests(directory: Path) -> Dict[str, str]:
    """{frame name: sha256} the render commandlet recorded in that
    directory's render.json, or {} when it recorded none (an older
    build, or no render.json)."""
    path = Path(directory) / "render.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    records = payload.get("frame_records") or []
    return {str(r["frame"]): str(r["sha256"]) for r in records
            if isinstance(r, dict) and r.get("frame") and r.get("sha256")}


def pixel_difference(path_a: Path, path_b: Path) -> Dict:
    """Per-pixel comparison of two same-sized PNGs."""
    import numpy as np
    from PIL import Image

    with Image.open(path_a) as a, Image.open(path_b) as b:
        pa = np.asarray(a.convert("RGB"), dtype=np.int16)
        pb = np.asarray(b.convert("RGB"), dtype=np.int16)
    if pa.shape != pb.shape:
        return {"comparable": False,
                "reason": f"sizes differ: {pa.shape[:2]} vs {pb.shape[:2]}"}
    diff = np.abs(pa - pb)
    per_pixel = diff.max(axis=2)
    return {
        "comparable": True,
        "max_abs": int(diff.max()),
        "mean_abs": float(diff.mean()),
        "fraction_differing": float((per_pixel > 0).mean()),
        "pixels": int(per_pixel.size),
    }


def compare_frame_sets(dir_a, dir_b) -> Dict:
    """The measurement. Frame by frame, bytes first, pixels where the
    bytes differ."""
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    names_a, names_b = frame_names(dir_a), frame_names(dir_b)
    union = sorted(set(names_a) | set(names_b))
    engine_a, engine_b = engine_digests(dir_a), engine_digests(dir_b)
    frames = []
    identical = 0
    missing = 0
    max_abs = 0
    fractions: List[float] = []
    means: List[float] = []
    engine_agrees: Optional[bool] = True if (engine_a and engine_b) else None
    for name in union:
        pa, pb = dir_a / name, dir_b / name
        entry: Dict = {"frame": name}
        if not pa.is_file() or not pb.is_file():
            entry["status"] = "missing in " + ("A" if not pa.is_file() else "B")
            missing += 1
            frames.append(entry)
            continue
        ha, hb = frame_sha256(pa), frame_sha256(pb)
        entry["sha256_a"], entry["sha256_b"] = ha, hb
        # The engine's own record of what it wrote, against the file:
        # a disagreement here is a tampered or replaced frame, not a
        # render difference, and is reported apart.
        if engine_agrees is not None:
            ea, eb = engine_a.get(name), engine_b.get(name)
            if ea != ha or eb != hb:
                engine_agrees = False
                entry["engine_record_disagrees"] = True
        if ha == hb:
            entry["status"] = BIT_IDENTICAL
            identical += 1
        else:
            entry["status"] = BOUNDED
            entry["difference"] = pixel_difference(pa, pb)
            if entry["difference"].get("comparable"):
                max_abs = max(max_abs, entry["difference"]["max_abs"])
                fractions.append(entry["difference"]["fraction_differing"])
                means.append(entry["difference"]["mean_abs"])
        frames.append(entry)
    compared = len(union) - missing
    if missing:
        verdict = INCOMPLETE
    elif compared and identical == compared:
        verdict = BIT_IDENTICAL
    elif compared:
        verdict = BOUNDED
    else:
        verdict = INCOMPLETE
    return {
        "verdict": verdict,
        "frames_in_union": len(union),
        "frames_compared": compared,
        "frames_identical": identical,
        "frames_differing": compared - identical,
        "frames_missing": missing,
        "max_abs_per_pixel": max_abs,
        "max_fraction_differing": max(fractions) if fractions else 0.0,
        "mean_abs_over_differing_frames": (sum(means) / len(means)) if means else 0.0,
        "engine_digests_agree_with_files": engine_agrees,
        "frames": frames,
    }


def describe(report: Dict) -> str:
    """One paragraph a person can quote, saying no more than the numbers."""
    v = report["verdict"]
    if v == BIT_IDENTICAL:
        return (f"BIT-IDENTICAL: all {report['frames_compared']} frames have "
                f"the same bytes in both renders.")
    if v == BOUNDED:
        return (f"BOUNDED: {report['frames_differing']} of "
                f"{report['frames_compared']} frames differ; the largest "
                f"per-pixel difference on any channel is "
                f"{report['max_abs_per_pixel']} of 255, at most "
                f"{100 * report['max_fraction_differing']:.2f}% of a frame's "
                f"pixels differ at all, and the mean absolute difference over "
                f"the differing frames is "
                f"{report['mean_abs_over_differing_frames']:.4f}.")
    return (f"INCOMPLETE: {report['frames_missing']} frame(s) present in one "
            f"render and absent from the other; nothing is claimed about "
            f"frames that do not exist.")
