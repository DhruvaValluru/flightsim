"""Every rendered frame twice: as rendered, and with its 2-D boxes drawn on.

For each object the frame's ``labels.objects[]`` records (the main
aircraft, every other aircraft, the scene aggregates when they have a
box), the boxed copy draws:

* the box measured from the engine's mask pixels (``bbox_2d_tight``),
  solid, when the engine's ID image was read;
* the box predicted from the geometry (``bbox_2d``), dashed, always --
  kept beside the mask box so the two can be compared by eye;
* a tag with the object id and, when both boxes exist, their IoU.

Nothing here decides a label: the boxes are the record's own numbers,
drawn. Whether they agree well enough is the verifier's ``box_vs_mask``.
The copies are written as ``boxed/<camera>/frame_NNNN_boxes.png`` beside
the run's ``frames/`` directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

#: Mask box (measured) and predicted box colours, legible on sky and ground.
MASK_BOX = (64, 255, 128)
PREDICTED_BOX = (255, 200, 40)
TAG_BG = (10, 12, 18)
OUT_SUBDIR = "boxed"


def boxed_name(frame_name: str) -> str:
    """``frame_0042.png`` -> ``frame_0042_boxes.png``."""
    stem = frame_name[:-len(".png")] if frame_name.endswith(".png") else frame_name
    return f"{stem}_boxes.png"


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)
    return inter / union if union > 0 else 0.0


def _box(value) -> Optional[List[float]]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError):
            return None
    return None


def _dashed_rect(draw, box, colour, width=2, dash=8):
    x0, y0, x1, y1 = box
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                             (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = max(abs(bx - ax), abs(by - ay))
        steps = max(1, int(length // dash))
        for i in range(0, steps, 2):
            t0, t1 = i / steps, min(1.0, (i + 1) / steps)
            draw.line([(ax + (bx - ax) * t0, ay + (by - ay) * t0),
                       (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                      fill=colour, width=width)


def _object_boxes(record: Dict) -> List[Dict]:
    """(id, mask box, predicted box) per object of the frame; the frame's
    own ``labels.bbox_2d`` stands in for a run with no ``objects[]``."""
    labels = record.get("labels") or {}
    entries = labels.get("objects")
    if not isinstance(entries, list):
        entries = [{"id": "aircraft", "bbox_2d": labels.get("bbox_2d")}]
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mask = _box(entry.get("bbox_2d_tight"))
        predicted = _box(entry.get("bbox_2d")) or _box(entry.get("landcover_bbox_2d"))
        if mask is None and predicted is None:
            continue
        out.append({"id": str(entry.get("id")), "mask": mask, "predicted": predicted})
    return out


def draw_box_frame(record: Dict, source: Path, target: Path) -> Path:
    """Write ``target``: ``source`` with the record's 2-D boxes drawn."""
    from PIL import Image, ImageDraw

    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for item in _object_boxes(record):
        mask, predicted = item["mask"], item["predicted"]
        if predicted is not None:
            _dashed_rect(draw, predicted, PREDICTED_BOX)
        if mask is not None:
            draw.rectangle(mask, outline=MASK_BOX, width=2)
        anchor = mask or predicted
        tag = item["id"]
        if mask is not None and predicted is not None:
            tag += f"  IoU {_iou(mask, predicted):.2f}"
        tx = max(0.0, min(anchor[0], width - 6 * len(tag) - 6))
        ty = anchor[1] - 14 if anchor[1] >= 14 else min(anchor[3] + 2, height - 14)
        draw.rectangle([tx, ty, tx + 6 * len(tag) + 6, ty + 12], fill=TAG_BG)
        draw.text((tx + 3, ty), tag, fill=MASK_BOX if mask is not None else PREDICTED_BOX)
    caption = ("solid green = box from the mask pixels   dashed amber = "
               "predicted box (geometry)")
    draw.rectangle([0, height - 16, width, height], fill=TAG_BG)
    draw.text((6, height - 14), caption, fill=(220, 225, 232))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target)
    return target


def draw_box_frames(manifest: Dict, run_dir, cameras: Optional[Iterable[str]] = None,
                    out_subdir: str = OUT_SUBDIR) -> List[Path]:
    """One boxed copy per rendered frame (every frame, no cap); frames
    the renderer did not write are skipped. A copy newer than both its
    frame and the manifest is reused."""
    run_dir = Path(run_dir)
    wanted = set(cameras) if cameras is not None else None
    manifest_path = run_dir / "capture_manifest.json"
    manifest_mtime = manifest_path.stat().st_mtime if manifest_path.is_file() else 0.0
    written: List[Path] = []
    for record in manifest.get("frames", []):
        camera = str(record.get("camera_id"))
        if wanted is not None and camera not in wanted:
            continue
        source = run_dir / str(record.get("file", ""))
        if not source.is_file():
            continue
        target = run_dir / out_subdir / camera / boxed_name(source.name)
        if (target.is_file() and target.stat().st_mtime >= source.stat().st_mtime
                and target.stat().st_mtime >= manifest_mtime):
            written.append(target)
            continue
        written.append(draw_box_frame(record, source, target))
    return written
