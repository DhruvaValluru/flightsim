"""Visual sheets for the annotation gates (Phase 2, package D; contracts §4).

    .venv/bin/python tests/visual/annotation_sheets.py [RUN_DIR] [--out DIR]

Stands the verifier up on a run directory -- a real rendered run when
one is given, else the fabricated run of tests/test_annotation_gates.py
(written under ``<out>/fabricated_run``) -- and writes one PNG per check
under ``build/visual/`` (or ``--out``):

    mask_integers_only.png    the ID image colourised by id; pixels that
                              carry an undeclared value, or an id whose
                              class the class image contradicts, in red
    mask_vs_geometry.png      the mask's edge (white), the projected hull
                              wireframe (yellow), the CG cross (cyan), the
                              hull box's centre (magenta) and the mask
                              box's centre (green), per aircraft object
    box_vs_mask.png           the tight box (green) and the projected hull
                              box (yellow), the IoU stamped
    depth_vs_geometry.png     the depth heatmap; the nearest keypoint
                              marked with its predicted depth beside the
                              measured depth under the mask
    visibility_vs_scene.png   each alone pass beside the full ID pass, the
                              footprint pixels the full pass hides in red
    identity_stable.png       the id strip: one row per object, one column
                              per frame of every camera, the cell coloured
                              by the integer that frame maps the id to,
                              and the engine's echo per camera

Each sheet carries the check's verdict and detail in its caption, and
``sheets.json`` beside them records, per sheet, the verdict, the
failure name, whether the sheet was DRAWN and the error if it was not:
a painter that throws still yields a captioned placeholder (a sheet
never hides the verdict) but is recorded as not drawn, the CLI exits 1,
and the test asserts the record and the drawn marks themselves. The
sheet draws what the verifier measured, through the verifier's own
helpers; it decides nothing. PIL and numpy only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.capture.manifest import read_capture_manifest          # noqa: E402
from core.capture.verify import (                                  # noqa: E402
    FAIL, _aircraft_entries, _bundle_frames, _declared_objects, _labelled_ids,
    _object_geometry, _pinhole, _projected_hull, _read_depth_metres,
    _read_gray_png, _render_frame_records, axes_from_quat,
    verify_box_vs_mask, verify_depth_vs_geometry, verify_identity_stable,
    verify_mask_integers_only, verify_mask_vs_geometry,
    verify_visibility_vs_scene,
)
from tests.visual import draw                                      # noqa: E402

SHEETS = ("mask_integers_only", "mask_vs_geometry", "box_vs_mask",
          "depth_vs_geometry", "visibility_vs_scene", "identity_stable")
#: The per-sheet record written beside the PNGs: {check: {file, drawn,
#: error, status, failure, verdict, detail}}.
SHEETS_RECORD = "sheets.json"
DEFAULT_OUT = REPO / "build" / "visual"
#: Frames per sheet: the first frame of each camera, up to this many.
PANELS = 2
PANEL_WIDTH = 640


def _frames(manifest: Dict, run_dir: Path, prefer_occluded: bool = False) -> List[Tuple]:
    """(record, camera, name, engine, folder) for the first frame of each
    camera with a bundle -- or, when asked, the first frame per camera
    whose record shows an occlusion."""
    chosen: Dict[str, Tuple] = {}
    for item in _bundle_frames(manifest, run_dir):
        record, camera = item[0], item[1]
        occluded = any(e.get("visible_fraction") is not None and e["visible_fraction"] < 1.0
                       for e in (record.get("labels") or {}).get("objects") or [])
        if camera not in chosen or (prefer_occluded and occluded and not chosen[camera][1]):
            chosen[camera] = (item, occluded)
    return [item for item, _ in list(chosen.values())[:PANELS]]


def _verdict_lines(check) -> List[str]:
    text = f"[{check.status}] {check.name}"
    if check.status == FAIL and check.failure:
        text += f" -- {check.failure}"
    detail = check.detail
    lines = [text]
    while detail:
        lines.append(detail[:150])
        detail = detail[150:]
        if len(lines) >= 4:
            break
    return lines


def _panel(rgb: np.ndarray, title: str) -> Image.Image:
    image = draw.shrink(draw.to_image(rgb), PANEL_WIDTH)
    return draw.caption(image, [title], size=12)


def sheet_mask_integers_only(manifest, run_dir) -> Image.Image:
    labelled = _labelled_ids(_declared_objects(manifest))
    class_of = {i: int(e.get("class_id", 0)) for i, e in labelled.items()}
    panels = []
    for record, camera, name, engine, folder in _frames(manifest, run_dir):
        mask = _read_gray_png(folder / engine["labels"]["mask"])
        rgb = draw.colourise(mask)
        offending = np.zeros(mask.shape, dtype=bool)
        for value in np.unique(mask):
            if int(value) != 0 and int(value) not in labelled:
                offending |= mask == value
        if engine["labels"].get("class_mask"):
            classes = _read_gray_png(folder / engine["labels"]["class_mask"])
            if classes is not None and classes.shape == mask.shape:
                lut = np.zeros(int(mask.max()) + 1, dtype=np.int64)
                for i, c in class_of.items():
                    if i < lut.size:
                        lut[i] = c
                offending |= (mask != 0) & (classes.astype(np.int64) != lut[mask.astype(np.int64)])
        rgb = draw.paint(rgb, offending, draw.RED)
        values = ", ".join(str(int(v)) for v in np.unique(mask))
        panels.append(_panel(rgb, f"{camera}/{name}: ids {{{values}}}; "
                                  f"{int(offending.sum())} offending px in red"))
    legend = draw.legend({f"{e.get('id')} = {i}": draw.colour_of(i)
                          for i, e in sorted(labelled.items())} | {"offending": draw.RED})
    return draw.stack([legend, draw.side_by_side(panels)])


def _object_overlays(manifest, record, engine, folder):
    """Per aircraft object with geometry: (entry, geometry, hull, mask hit)."""
    mask = _read_gray_png(folder / engine["labels"]["mask"])
    axes = axes_from_quat(record["quaternion_wxyz"])
    out = []
    for entry in _aircraft_entries(_declared_objects(manifest)):
        geometry, _ = _object_geometry(manifest, record, entry, axes)
        if geometry is None:
            continue
        out.append((entry, geometry, _projected_hull(record, geometry),
                    mask == int(entry["int_id"])))
    return mask, out


def sheet_mask_vs_geometry(manifest, run_dir) -> Image.Image:
    panels = []
    for record, camera, name, engine, folder in _frames(manifest, run_dir):
        mask, objects = _object_overlays(manifest, record, engine, folder)
        rgb = draw.dim(draw.colourise(mask))
        for entry, geometry, hull, hit in objects:
            rgb = draw.paint(rgb, draw.outline(hit), draw.WHITE)
        image = draw.to_image(rgb)
        pen = ImageDraw.Draw(image)
        for entry, geometry, hull, hit in objects:
            corners = [_pinhole(record, c) for c in geometry["corners"]]
            draw.wire(pen, corners, draw.YELLOW)
            draw.cross(pen, _pinhole(record, geometry["cg"]), draw.CYAN)
            if hit.any():
                ys, xs = np.nonzero(hit)
                draw.cross(pen, ((xs.min() + xs.max() + 1) / 2.0,
                                 (ys.min() + ys.max() + 1) / 2.0), draw.GREEN)
            if hull is not None:
                unclipped = hull[0]
                draw.cross(pen, ((unclipped[0] + unclipped[2]) / 2.0,
                                 (unclipped[1] + unclipped[3]) / 2.0), draw.MAGENTA, size=5)
            if hull and hull[1]:
                draw.label(pen, (hull[1][0], max(0.0, hull[1][1] - 16)), str(entry.get("id")))
        panels.append(_panel(np.asarray(image), f"{camera}/{name}"))
    legend = draw.legend({"mask edge": draw.WHITE, "projected hull": draw.YELLOW,
                          "CG": draw.CYAN, "hull box centre": draw.MAGENTA,
                          "mask box centre": draw.GREEN})
    return draw.stack([legend, draw.side_by_side(panels)])


def sheet_box_vs_mask(manifest, run_dir) -> Image.Image:
    from core.capture.verify import _iou

    panels = []
    for record, camera, name, engine, folder in _frames(manifest, run_dir):
        mask, objects = _object_overlays(manifest, record, engine, folder)
        image = draw.to_image(draw.dim(draw.colourise(mask)))
        pen = ImageDraw.Draw(image)
        for entry, geometry, hull, hit in objects:
            if hull is None or hull[1] is None:
                continue
            draw.box(pen, hull[1], draw.YELLOW)
            if hit.any():
                ys, xs = np.nonzero(hit)
                tight = (float(xs.min()), float(ys.min()), float(xs.max()) + 1.0,
                         float(ys.max()) + 1.0)
                draw.box(pen, tight, draw.GREEN)
                draw.label(pen, (tight[0], tight[3] + 2),
                           f"{entry.get('id')} IoU {_iou(tight, hull[1]):.3f}")
        panels.append(_panel(np.asarray(image), f"{camera}/{name}"))
    legend = draw.legend({"tight box (mask)": draw.GREEN, "projected hull box": draw.YELLOW})
    return draw.stack([legend, draw.side_by_side(panels)])


def sheet_depth_vs_geometry(manifest, run_dir) -> Image.Image:
    panels = []
    for record, camera, name, engine, folder in _frames(manifest, run_dir):
        mask, objects = _object_overlays(manifest, record, engine, folder)
        depth = _read_depth_metres(folder, engine["labels"], int(record["width_px"]),
                                   int(record["height_px"]))
        if isinstance(depth, str):
            panels.append(_panel(np.zeros(mask.shape + (3,), np.uint8), f"{camera}/{name}: {depth}"))
            continue
        # The colour range is the aircraft objects' depth band (their
        # hull corners), not the whole scene's: the ground plane runs to
        # the horizon and would flatten every airframe to one colour.
        corners = [c[2] for _, geometry, _, _ in objects for c in geometry["corners"]]
        finite = depth[np.isfinite(depth)]
        if corners:
            lo, hi = min(corners) * 0.9, max(corners) * 1.1
        elif finite.size:
            lo, hi = float(finite.min()), float(np.percentile(finite, 99))
        else:
            lo, hi = 0.0, 1.0
        rgb = draw.heatmap(depth, lo, hi)
        for entry, geometry, hull, hit in objects:
            rgb = draw.paint(rgb, draw.outline(hit), draw.WHITE)
        image = draw.to_image(rgb)
        pen = ImageDraw.Draw(image)
        lines = [f"{camera}/{name}: colour range {lo:.0f}-{hi:.0f} m (the aircraft's "
                 f"band; nearer/farther saturate; black = sky)"]
        for entry, geometry, hull, hit in objects:
            if not hit.any() or not geometry["keypoints"]:
                continue
            kp_name, kp = min(geometry["keypoints"].items(), key=lambda kv: kv[1][2])
            px = _pinhole(record, kp)
            draw.cross(pen, px, draw.WHITE, size=6)
            under = depth[hit]
            under = under[np.isfinite(under)]
            measured = f"{under.min():.1f}" if under.size else "none"
            text = (f"{entry.get('id')}: nearest keypoint {kp_name} predicted "
                    f"{kp[2]:.1f} m; mask nearest {measured} m, median "
                    f"{np.median(under):.1f} m; CG {geometry['cg'][2]:.1f} m")
            lines.append(text)
            if px is not None:
                draw.label(pen, (px[0] + 8, px[1] - 8), f"{kp_name} {kp[2]:.0f} m")
        panel = draw.shrink(image, PANEL_WIDTH)
        panels.append(draw.caption(panel, lines, size=12))
    return draw.side_by_side(panels)


def sheet_visibility_vs_scene(manifest, run_dir) -> Image.Image:
    id_of = {int(e["int_id"]): str(e.get("id")) for e in _declared_objects(manifest)}
    rows = []
    for record, camera, name, engine, folder in _frames(manifest, run_dir, prefer_occluded=True):
        mask = _read_gray_png(folder / engine["labels"]["mask"])
        panels = [_panel(draw.colourise(mask), f"{camera}/{name}: full ID pass")]
        for declared in engine["labels"].get("objects") or []:
            if not isinstance(declared, dict) or not declared.get("alone_png"):
                continue
            int_id = int(declared["int_id"])
            alone = _read_gray_png(folder / declared["alone_png"])
            footprint = alone == int_id
            rgb = draw.colourise(alone)
            hidden = footprint & (mask != int_id)
            rgb = draw.paint(rgb, hidden, draw.RED)
            n_alone = int(footprint.sum())
            n_vis = int((mask == int_id).sum())
            fraction = f"{n_vis / n_alone:.3f}" if n_alone else "n/a"
            panels.append(_panel(rgb, f"alone {id_of.get(int_id, int_id)}: {n_alone} px, "
                                      f"visible {n_vis} ({fraction}); hidden in red"))
        rows.append(draw.side_by_side(panels))
    return draw.stack(rows)


def sheet_identity_stable(manifest, run_dir) -> Image.Image:
    objects = _declared_objects(manifest)
    ids = [str(o.get("id")) for o in objects]
    columns: List[Tuple[str, Dict[str, Optional[int]]]] = []
    for record in manifest.get("frames", []):
        mapping = {str(e.get("id")): (int(e["int_id"]) if e.get("int_id") is not None else None)
                   for e in (record.get("labels") or {}).get("objects") or []
                   if isinstance(e, dict)}
        columns.append((f"{record.get('camera_id')}/{record.get('index')}", mapping))
    frames_dir = Path(run_dir) / "frames"
    if frames_dir.is_dir():
        import json
        for camera_dir in sorted(p for p in frames_dir.iterdir() if p.is_dir()):
            path = camera_dir / "render.json"
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not _render_frame_records(payload):
                continue
            echoed = {str(e.get("id")): int(e["int_id"]) for e in payload.get("objects") or []
                      if isinstance(e, dict) and e.get("int_id") is not None}
            columns.append((f"{camera_dir.name} engine echo", echoed))
    cell, left, top = 34, 190, 70
    width = left + cell * max(1, len(columns)) + 8
    height = top + cell * max(1, len(ids)) + 8
    image = Image.new("RGB", (width, height), (16, 16, 20))
    pen = ImageDraw.Draw(image)
    for j, (title, _) in enumerate(columns):
        for k, part in enumerate(title.split("/")):
            draw.label(pen, (left + j * cell + 2, 4 + k * 14), part[:8], size=10, background=None)
    for i, object_id in enumerate(ids):
        draw.label(pen, (4, top + i * cell + 10), object_id, size=11, background=None)
        for j, (_, mapping) in enumerate(columns):
            value = mapping.get(object_id)
            colour = draw.colour_of(value) if value is not None else draw.GREY
            x, y = left + j * cell, top + i * cell
            pen.rectangle([x, y, x + cell - 3, y + cell - 3], fill=colour)
            draw.label(pen, (x + 10, y + 9), str(value) if value is not None else "-",
                       size=12, background=None)
    reference = {str(o.get("id")): int(o["int_id"]) for o in objects}
    return draw.caption(image, [f"objects[]: {reference}; a cell whose integer differs "
                                f"from its row's is a changed id"], size=12)


def write_sheets(run_dir, out_dir=DEFAULT_OUT) -> Dict[str, Path]:
    """Every sheet for a run directory; returns {check: path}, and writes
    ``SHEETS_RECORD`` beside them saying which sheets were drawn."""
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = read_capture_manifest(run_dir / "capture_manifest.json")
    checks = {
        "mask_integers_only": verify_mask_integers_only(manifest, run_dir),
        "mask_vs_geometry": verify_mask_vs_geometry(manifest, run_dir),
        "box_vs_mask": verify_box_vs_mask(manifest, run_dir),
        "depth_vs_geometry": verify_depth_vs_geometry(manifest, run_dir),
        "visibility_vs_scene": verify_visibility_vs_scene(manifest, run_dir),
        "identity_stable": verify_identity_stable(manifest, run_dir),
    }
    painters = {
        "mask_integers_only": sheet_mask_integers_only,
        "mask_vs_geometry": sheet_mask_vs_geometry,
        "box_vs_mask": sheet_box_vs_mask,
        "depth_vs_geometry": sheet_depth_vs_geometry,
        "visibility_vs_scene": sheet_visibility_vs_scene,
        "identity_stable": sheet_identity_stable,
    }
    written: Dict[str, Path] = {}
    record: Dict[str, Dict] = {}
    for name in SHEETS:
        verdict = _verdict_lines(checks[name])
        try:
            body = painters[name](manifest, run_dir)
            drawn, error = True, None
        except Exception as exc:              # a sheet never hides the verdict
            drawn, error = False, f"{exc.__class__.__name__}: {exc}"
            body = Image.new("RGB", (640, 120), (40, 16, 16))
            ImageDraw.Draw(body).text((8, 8), f"could not draw: {exc}"[:90],
                                      fill=draw.WHITE, font=draw.font(12))
        sheet = draw.caption(body, verdict, size=13)
        path = out_dir / f"{name}.png"
        sheet.save(path)
        written[name] = path
        record[name] = {"file": path.name, "drawn": drawn, "error": error,
                        "status": checks[name].status, "failure": checks[name].failure,
                        "verdict": verdict[0], "detail": checks[name].detail}
    (out_dir / SHEETS_RECORD).write_text(json.dumps(record, indent=1), encoding="utf-8")
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="write the annotation sheets")
    parser.add_argument("run_dir", nargs="?", default=None,
                        help="a run directory with a rendered bundle; fabricated when absent")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    out = Path(args.out)
    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        from tests.test_annotation_gates import fabricate_run

        run_dir = out / "fabricated_run"
        if run_dir.exists():
            import shutil
            shutil.rmtree(run_dir)
        fabricate_run(run_dir)
        print(f"fabricated run: {run_dir}")
    written = write_sheets(run_dir, out)
    record = json.loads((out / SHEETS_RECORD).read_text(encoding="utf-8"))
    undrawn = 0
    for name, path in written.items():
        entry = record[name]
        note = "" if entry["drawn"] else f"  NOT DRAWN: {entry['error']}"
        undrawn += not entry["drawn"]
        print(f"  {name}: {path}  {entry['verdict']}{note}")
    print(f"  record: {out / SHEETS_RECORD}")
    if undrawn:
        print(f"  {undrawn} sheet(s) could not be drawn; the verdicts above stand, "
              f"the pictures do not")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
