"""Every rendered frame four times: as rendered, with its 2-D boxes drawn
on, with its 3-D boxes drawn on, and with its 3-D boxes plus the airflow,
forces and flight-state panels (both in ``boxed3d/``, core/capture/
box3d.py and flight_overlay.py).

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
import os
from typing import Dict, Iterable, List, Optional, Sequence

#: Mask box (measured) and predicted box colours, legible on sky and ground.
MASK_BOX = (64, 255, 128)
PREDICTED_BOX = (255, 200, 40)
TAG_BG = (10, 12, 18)
OUT_SUBDIR = "boxed"
#: The third version: the 3-D box rebuilt from the record (core/capture/box3d.py).
OUT_SUBDIR_3D = "boxed3d"


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


def box3d_name(frame_name: str) -> str:
    """``frame_0042.png`` -> ``frame_0042_box3d.png``."""
    stem = frame_name[:-len(".png")] if frame_name.endswith(".png") else frame_name
    return f"{stem}_box3d.png"


def box3d_detailed_name(frame_name: str) -> str:
    """``frame_0042.png`` -> ``frame_0042_box3d_detailed.png``."""
    stem = frame_name[:-len(".png")] if frame_name.endswith(".png") else frame_name
    return f"{stem}_box3d_detailed.png"


def box3d_scene_name(frame_name: str) -> str:
    """``frame_0042.png`` -> ``frame_0042_box3d_scene.png``."""
    stem = frame_name[:-len(".png")] if frame_name.endswith(".png") else frame_name
    return f"{stem}_box3d_scene.png"


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


def _drawer_mtime() -> float:
    """The newest of the 3-D picture's drawing modules, so a picture drawn
    by older code is redrawn instead of reused."""
    here = Path(__file__).resolve().parent
    return max((here / n).stat().st_mtime for n in
               ("box3d.py", "flight_overlay.py", "flight_physics.py", "scene_overlay.py")
               if (here / n).is_file())


#: The pictures :func:`draw_box_frames` can write per frame.
PICTURE_KINDS = ("boxes", "plain", "detailed", "scene")


def _picture_plan(manifest, run_dir, out_subdir):
    from .box3d import draw_box3d_detailed_frame, draw_box3d_frame

    def draw_3d(rec, src, dst):
        return draw_box3d_frame(rec, src, dst, manifest=manifest)

    def draw_3d_detailed(rec, src, dst):
        return draw_box3d_detailed_frame(rec, src, dst, manifest=manifest)

    def draw_3d_scene(rec, src, dst):
        from .scene_overlay import draw_scene_frame

        return draw_scene_frame(rec, src, dst, manifest=manifest)

    code = _drawer_mtime()
    return {"boxes": (out_subdir, boxed_name, draw_box_frame, 0.0),
            "plain": (OUT_SUBDIR_3D, box3d_name, draw_3d, code),
            "detailed": (OUT_SUBDIR_3D, box3d_detailed_name, draw_3d_detailed, code),
            "scene": (OUT_SUBDIR_3D, box3d_scene_name, draw_3d_scene, code)}


def frame_source(run_dir: Path, record: Dict) -> Optional[Path]:
    """The image a frame's pictures are drawn on: the render, else the
    engine-free preview of the same frame; None when neither exists."""
    frame_file = Path(run_dir) / str(record.get("file", ""))
    if frame_file.is_file():
        return frame_file
    preview = (Path(run_dir) / "previews" / str(record.get("camera_id"))
               / f"preview_{int(record.get('index', 0)):04d}.png")
    return preview if preview.is_file() else None


def draw_box_frames(manifest: Dict, run_dir, cameras: Optional[Iterable[str]] = None,
                    out_subdir: str = OUT_SUBDIR,
                    kinds: Sequence[str] = ("boxes", "plain"),
                    indices: Optional[Iterable[int]] = None,
                    workers: Optional[int] = None, progress=None) -> List[Path]:
    """The boxed copies of the rendered frames: for every frame (or the
    frame ``indices``) of the ``cameras``, each picture in ``kinds``
    (``boxes`` 2-D boxes, ``plain`` / ``detailed`` / ``scene`` the 3-D
    pictures). Frames the renderer did not write are drawn on their
    preview, or skipped. A copy newer than its frame, the manifest and
    the drawing code is reused. Many frames draw on a thread pool (numpy
    and Pillow release the interpreter lock in the heavy work)."""
    run_dir = Path(run_dir)
    wanted = set(cameras) if cameras is not None else None
    only = set(int(i) for i in indices) if indices is not None else None
    manifest_path = run_dir / "capture_manifest.json"
    manifest_mtime = manifest_path.stat().st_mtime if manifest_path.is_file() else 0.0
    plan = _picture_plan(manifest, run_dir, out_subdir)
    jobs = []
    for record in manifest.get("frames", []):
        camera = str(record.get("camera_id"))
        if wanted is not None and camera not in wanted:
            continue
        if only is not None and int(record.get("index", -1)) not in only:
            continue
        source = frame_source(run_dir, record)
        if source is None:
            continue
        frame_name = Path(str(record.get("file", ""))).name
        for kind in kinds:
            subdir, namer, draw, code_mtime = plan[kind]
            target = run_dir / subdir / camera / namer(frame_name)
            if (target.is_file() and target.stat().st_mtime >= source.stat().st_mtime
                    and target.stat().st_mtime >= manifest_mtime
                    and target.stat().st_mtime >= code_mtime):
                jobs.append((None, target))
                continue
            jobs.append(((draw, record, source, target), target))
    todo = [j for j, _ in jobs if j is not None]
    n_workers = workers if workers is not None else min(4, max(1, (os.cpu_count() or 2) - 1))
    done = 0
    if progress:
        progress(0, len(todo))
    if len(todo) > 2 and n_workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            for future in as_completed([pool.submit(j[0], j[1], j[2], j[3]) for j in todo]):
                future.result()
                done += 1
                if progress:
                    progress(done, len(todo))
    else:
        for draw, record, source, target in todo:
            draw(record, source, target)
            done += 1
            if progress:
                progress(done, len(todo))
    return [target for _, target in jobs]
