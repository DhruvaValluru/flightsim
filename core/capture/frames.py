"""Per-camera frame counts of a render, and the camera that drew nothing.

The renderer draws one camera per pass into ``frames/<camera id>/``. A
camera whose directory holds no ``frame_NNNN.png`` is a pass that wrote
nothing, and the run must say so by name instead of skipping it.
``frames_by_camera`` is the one per-camera counter; the label stage's
summary imports it from here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence

_FRAME = re.compile(r"frame_\d{4}\.png")


def frames_by_camera(frames_dir: Path, camera_ids: Sequence[str]) -> Dict[str, int]:
    """Count ``frame_NNNN.png`` in ``frames/<camera id>/`` for each id
    (the labelled-run companions ``frame_NNNN_mask.png`` etc. do not count)."""
    counts: Dict[str, int] = {}
    for camera_id in camera_ids:
        directory = Path(frames_dir) / str(camera_id)
        counts[str(camera_id)] = (
            sum(1 for p in directory.iterdir() if _FRAME.fullmatch(p.name))
            if directory.is_dir() else 0)
    return counts


def empty_camera_ids(frames_dir: Path, camera_ids: Sequence[str]) -> List[str]:
    """The expected camera ids that have zero frames, in the given order."""
    return [c for c, n in frames_by_camera(frames_dir, camera_ids).items() if n == 0]


def camera_empty_message(camera_id: str) -> str:
    return f"render.camera_empty: {camera_id}"
