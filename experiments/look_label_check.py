"""Do the labels still lie on the picture once the beauty look is on?

The verifier's ``look_label_alignment`` check reads what the RECORD says
about effects that move pixels. This harness measures the same question
from the PIXELS, the way Gate 6 decides its clauses: it reads one
frame's beauty image and the subject's mask from two bundles of the
same card and frame -- one rendered ``-quality=measure`` (the control:
Gate 6 passed on it) and one ``-quality=beauty`` (or ``pathtrace``) --
and reports how far the mask's edge sits from the subject's silhouette
in each picture, in pixels, against the gate tolerance.

    .venv/bin/python -m experiments.look_label_check \\
        --measure runs/visual/look/measure --beauty runs/visual/look/beauty \\
        [--camera chase] [--frame frame_0000.png] [--int-id 1] [--out report.json]

A bundle is a run directory (``frames/<camera>/``) or one camera's
folder. Each must hold the frame's PNG and its ``_mask.png``.

How the error is measured
-------------------------
* The silhouette proxy is the picture's luminance gradient (Rec. 709
  luma, central differences). The mask's boundary is the subject's
  pixels with a 4-neighbour outside it.
* **Offset**: the mask boundary is slid over integer shifts within
  ``SEARCH_RADIUS_PX``; the shift whose boundary pixels sit on the most
  gradient is where the picture's silhouette is, refined to sub-pixel
  by a parabola through its neighbours on each axis. Its length is the
  label error in pixels. A blur that is symmetric about the edge (a
  defocus, an accumulated shutter centred on the instant) leaves it at
  zero; a distortion, a fringe, a refraction or a crop moves it.
* **Edge distance**: each boundary pixel's distance to the nearest
  pixel whose gradient is in the top ``EDGE_PERCENTILE`` of the band
  around the mask (median and 90th percentile), capped at the search
  radius -- the spread the offset alone cannot show.
* **Self-validation control** (or the result is VOID): the same beauty
  picture shifted by ``CONTROL_SHIFT_PX`` must be measured as moved by
  at least ``CONTROL_SHIFT_PX - CONTROL_SLACK_PX``. A metric that cannot
  see a shift it was handed cannot certify that there is none.

The verdict is ALIGNED when the beauty's offset is within
``core.capture.verify.LOOK_ALIGNMENT_TOL_PX`` (the mask gate's tolerance
for a drawn mesh), its edge-distance p90 exceeds the measure bundle's
(in beauty pixels) by no more than that tolerance (a radial move such as
lens distortion leaves the best translation near zero but spreads the
edge), and the control is not void; the measure bundle's
offset is printed beside it as the floor this proxy reads on a picture
known to be aligned. Exit 0 ALIGNED, 1 NOT ALIGNED, 2 VOID or unreadable.
Masks of different sizes (beauty is 1920x1080 by default, measure
960x540) are each graded at their own resolution; the offsets are also
given in measure pixels, and the masks' agreement as an IoU after a
nearest-neighbour resample.

Every threshold below that is not the gate's is UNCALIBRATED: set by
probe render on the render machine (docs/visual/PROBE_LOG.md, the
verifier-tooling section, says which render sets each).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.capture.verify import LOOK_ALIGNMENT_TOL_PX  # noqa: E402

#: Largest shift the offset search tries, each axis, in pixels.
#: UNCALIBRATED: set by probe render on the render machine (the largest
#: lens-distortion displacement the look-dev lane records at the frame's
#: corners must be inside it).
SEARCH_RADIUS_PX = 6
#: The gradient percentile, inside the band around the mask, that counts
#: as a silhouette edge for the edge-distance figure.
#: UNCALIBRATED: set by probe render on the render machine (the measure
#: bundle's chase frame: its p90 edge distance should sit near 1 px).
EDGE_PERCENTILE = 80.0
#: The self-validation control's shift, in pixels, and how much of it the
#: offset must recover. UNCALIBRATED: set by probe render on the render
#: machine (the control on the measure chase frame must recover the shift
#: to within the slack, or the slack is wrong).
CONTROL_SHIFT_PX = 3
CONTROL_SLACK_PX = 1.0
#: The subject's mask value (core.capture.verify.AIRCRAFT_INSTANCE_ID).
DEFAULT_INT_ID = 1

UNCALIBRATED = {
    "SEARCH_RADIUS_PX": SEARCH_RADIUS_PX,
    "EDGE_PERCENTILE": EDGE_PERCENTILE,
    "CONTROL_SHIFT_PX": CONTROL_SHIFT_PX,
    "CONTROL_SLACK_PX": CONTROL_SLACK_PX,
}


# -- the measurement (pure; unit-tested on synthetic pictures) ---------------

def luminance(image: np.ndarray) -> np.ndarray:
    """Rec. 709 luma of an RGB(A) or grey picture, in [0, 1]."""
    a = np.asarray(image)
    scale = float(np.iinfo(a.dtype).max) if np.issubdtype(a.dtype, np.integer) else 1.0
    a = a.astype("float64") / scale
    if a.ndim == 2:
        return a
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def gradient_magnitude(gray: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(gray)
    return np.hypot(gx, gy)


def mask_boundary(mask: np.ndarray) -> np.ndarray:
    """Subject pixels with a 4-neighbour outside the subject (or the frame)."""
    m = np.asarray(mask, dtype=bool)
    padded = np.pad(m, 1, constant_values=False)
    inner = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    return m & ~inner


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    m = np.asarray(mask, dtype=bool)
    out = m.copy()
    padded = np.pad(m, radius, constant_values=False)
    h, w = m.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            out |= padded[radius + dy:radius + dy + h, radius + dx:radius + dx + w]
    return out


def shift_image(image: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """``out[y, x] = image[y - dy, x - dx]``, edges replicated."""
    a = np.asarray(image)
    pad = max(abs(dx), abs(dy))
    if pad == 0:
        return a.copy()
    widths = [(pad, pad), (pad, pad)] + [(0, 0)] * (a.ndim - 2)
    padded = np.pad(a, widths, mode="edge")
    h, w = a.shape[:2]
    return padded[pad - dy:pad - dy + h, pad - dx:pad - dx + w]


def _parabola(minus: float, centre: float, plus: float) -> float:
    denom = minus - 2.0 * centre + plus
    if denom >= 0.0:            # not a peak: no refinement
        return 0.0
    return float(np.clip(0.5 * (minus - plus) / denom, -0.5, 0.5))


def edge_alignment(image: np.ndarray, mask: np.ndarray,
                   search_px: int = SEARCH_RADIUS_PX,
                   edge_percentile: float = EDGE_PERCENTILE) -> Dict:
    """How far the mask's boundary sits from the picture's silhouette.

    ``offset_px`` = (dx, dy): the shift that, applied to the mask, puts
    its boundary on the most gradient. Positive dx means the picture's
    silhouette is to the right of the mask."""
    m = np.asarray(mask, dtype=bool)
    if m.shape != np.asarray(image).shape[:2]:
        raise ValueError(f"mask {m.shape} and picture {np.asarray(image).shape[:2]} differ in size")
    boundary = mask_boundary(m)
    ys, xs = np.nonzero(boundary)
    if ys.size == 0:
        raise ValueError("the subject has no pixels in the mask")
    g = gradient_magnitude(luminance(image))
    h, w = g.shape

    def score(dx: int, dy: int) -> float:
        yy = np.clip(ys + dy, 0, h - 1)
        xx = np.clip(xs + dx, 0, w - 1)
        return float(g[yy, xx].mean())

    r = int(search_px)
    table = {(dx, dy): score(dx, dy) for dy in range(-r - 1, r + 2) for dx in range(-r - 1, r + 2)}
    best = max(((dx, dy) for dy in range(-r, r + 1) for dx in range(-r, r + 1)),
               key=lambda k: (table[k], -(k[0] ** 2 + k[1] ** 2)))
    bx, by = best
    sub_x = _parabola(table[(bx - 1, by)], table[best], table[(bx + 1, by)])
    sub_y = _parabola(table[(bx, by - 1)], table[best], table[(bx, by + 1)])
    offset = (bx + sub_x, by + sub_y)

    band = dilate(boundary, r)
    threshold = float(np.percentile(g[band], edge_percentile)) if band.any() else 0.0
    edges = g >= max(threshold, 1e-12)
    distance = np.full(ys.size, float(r))
    for oy in range(-r, r + 1):
        for ox in range(-r, r + 1):
            d = math.hypot(ox, oy)
            if d > r:
                continue
            hit = edges[np.clip(ys + oy, 0, h - 1), np.clip(xs + ox, 0, w - 1)]
            distance = np.where(hit & (d < distance), d, distance)
    return {
        "offset_px": [round(offset[0], 4), round(offset[1], 4)],
        "offset_length_px": round(math.hypot(*offset), 4),
        "at_search_edge": abs(bx) == r or abs(by) == r,
        "edge_distance_median_px": round(float(np.median(distance)), 4),
        "edge_distance_p90_px": round(float(np.percentile(distance, 90)), 4),
        "boundary_pixels": int(ys.size),
        "edge_threshold": threshold,
    }


def control(image: np.ndarray, mask: np.ndarray, measured: Dict,
            shift_px: int = CONTROL_SHIFT_PX, slack_px: float = CONTROL_SLACK_PX,
            search_px: int = SEARCH_RADIUS_PX) -> Dict:
    """The self-validation control: shift the picture, the offset must follow."""
    moved = edge_alignment(shift_image(image, shift_px, 0), mask, search_px)
    recovered = moved["offset_px"][0] - measured["offset_px"][0]
    return {"shift_px": shift_px, "recovered_px": round(recovered, 4),
            "void": abs(recovered - shift_px) > slack_px}


def resample_nearest(mask: np.ndarray, shape: Tuple[int, int]) -> np.ndarray:
    m = np.asarray(mask)
    h, w = shape
    rows = np.minimum((np.arange(h) + 0.5) * m.shape[0] / h, m.shape[0] - 1).astype(int)
    cols = np.minimum((np.arange(w) + 0.5) * m.shape[1] / w, m.shape[1] - 1).astype(int)
    return m[rows][:, cols]


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 1.0


def compare(measure_image, measure_mask, beauty_image, beauty_mask,
            tolerance_px: float = LOOK_ALIGNMENT_TOL_PX) -> Dict:
    """The report over one frame of the two bundles (masks are booleans)."""
    measure = edge_alignment(measure_image, measure_mask)
    beauty = edge_alignment(beauty_image, beauty_mask)
    checks = {"measure": control(measure_image, measure_mask, measure),
              "beauty": control(beauty_image, beauty_mask, beauty)}
    to_measure = measure_mask.shape[1] / beauty_mask.shape[1]
    void = [name for name, c in checks.items() if c["void"]]
    if beauty["at_search_edge"]:
        void.append("beauty offset at the search edge (raise SEARCH_RADIUS_PX)")
    # A translation alone cannot see a radial move (lens distortion, a
    # panini squeeze, a crop rescale about the subject): the silhouette
    # sits off the mask on every side and the best shift is near zero.
    # The edge-distance p90 can, so its excess over the measure floor
    # (in beauty pixels) is graded against the same tolerance.
    measure_p90_in_beauty = measure["edge_distance_p90_px"] / to_measure
    spread_excess = beauty["edge_distance_p90_px"] - measure_p90_in_beauty
    aligned = beauty["offset_length_px"] <= tolerance_px and spread_excess <= tolerance_px
    verdict = "VOID" if void else ("ALIGNED" if aligned else "NOT ALIGNED")
    return {
        "verdict": verdict,
        "tolerance_px": tolerance_px,
        "beauty": beauty,
        "measure": measure,
        "beauty_offset_in_measure_px": round(beauty["offset_length_px"] * to_measure, 4),
        "beauty_minus_measure_px": round(beauty["offset_length_px"] * to_measure
                                         - measure["offset_length_px"], 4),
        "edge_p90_excess_over_measure_px": round(spread_excess, 4),
        "mask_iou_at_measure_size": round(iou(measure_mask,
                                              resample_nearest(beauty_mask, measure_mask.shape)), 4),
        "control": checks,
        "void_reasons": void,
        "uncalibrated": UNCALIBRATED,
    }


# -- the bundles --------------------------------------------------------------

def camera_folder(bundle: Path, camera: Optional[str]) -> Path:
    bundle = Path(bundle)
    frames = bundle / "frames"
    if frames.is_dir():
        cameras = sorted(p for p in frames.iterdir() if p.is_dir())
        if camera:
            folder = frames / camera
            if not folder.is_dir():
                raise FileNotFoundError(f"{bundle}: no camera {camera!r} under frames/")
            return folder
        if len(cameras) != 1:
            raise FileNotFoundError(f"{bundle}: {len(cameras)} cameras under frames/; name one with --camera")
        return cameras[0]
    return bundle


def first_frame(folder: Path) -> str:
    for path in sorted(folder.glob("frame_*.png")):
        if path.stem.count("_") == 1:            # frame_NNNN.png, not frame_NNNN_mask.png
            return path.name
    raise FileNotFoundError(f"{folder}: no frame_NNNN.png")


def read_png(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as image:
        return np.array(image)


def load(bundle: Path, camera: Optional[str], frame: Optional[str], int_id: int):
    folder = camera_folder(bundle, camera)
    name = frame or first_frame(folder)
    image = read_png(folder / name)
    mask_path = folder / f"{Path(name).stem}_mask.png"
    mask = read_png(mask_path)
    if mask.ndim == 3:
        mask = mask[..., 0]
    subject = mask == int_id
    if not subject.any():
        raise ValueError(f"{mask_path}: no pixel carries the subject's id {int_id}")
    return folder, name, image, subject


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--measure", required=True, help="the -quality=measure bundle (the control)")
    ap.add_argument("--beauty", required=True, help="the beauty (or pathtrace) bundle of the same card")
    ap.add_argument("--camera", default=None)
    ap.add_argument("--frame", default=None, help="frame file name (default: the first)")
    ap.add_argument("--int-id", type=int, default=DEFAULT_INT_ID)
    ap.add_argument("--out", default=None, help="write the report as JSON here")
    args = ap.parse_args(argv)
    try:
        m_folder, m_name, m_image, m_mask = load(Path(args.measure), args.camera, args.frame, args.int_id)
        b_folder, b_name, b_image, b_mask = load(Path(args.beauty), args.camera, args.frame, args.int_id)
        if m_name != b_name:
            raise ValueError(f"the bundles' frames differ ({m_name} against {b_name}); "
                             f"name one with --frame")
        report = compare(m_image, m_mask, b_image, b_mask)
    except (OSError, ValueError) as exc:
        print(f"REFUSED -- look_label_check: {exc}")
        return 2
    report.update({"measure_folder": str(m_folder), "beauty_folder": str(b_folder), "frame": b_name})
    beauty, measure = report["beauty"], report["measure"]
    print(f"look_label_check {b_name}: {report['verdict']}")
    print(f"  beauty  offset {beauty['offset_length_px']:.2f} px {beauty['offset_px']} "
          f"(tol {report['tolerance_px']:g} px); edge distance median "
          f"{beauty['edge_distance_median_px']:.2f} p90 {beauty['edge_distance_p90_px']:.2f} px")
    print(f"  measure offset {measure['offset_length_px']:.2f} px {measure['offset_px']} "
          f"(the proxy's floor on a picture known aligned)")
    print(f"  beauty in measure px {report['beauty_offset_in_measure_px']:.2f}; mask IoU "
          f"{report['mask_iou_at_measure_size']:.3f}; control recovered "
          f"{report['control']['beauty']['recovered_px']:.2f} of {CONTROL_SHIFT_PX} px")
    if report["void_reasons"]:
        print(f"  VOID: {', '.join(report['void_reasons'])}")
    print("  thresholds UNCALIBRATED (set by probe render on the render machine): "
          + ", ".join(f"{k}={v}" for k, v in UNCALIBRATED.items()))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"  written: {args.out}")
    return {"ALIGNED": 0, "NOT ALIGNED": 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
