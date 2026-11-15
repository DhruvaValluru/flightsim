"""Pixel gate for the coastal aircraft PBR lane. Run ON THE WINDOWS LAPTOP, by
run_gate.ps1 (which renders the pair), on two frames of the same shot
(reference = CoastalWeathering 0, candidate = CoastalWeathering 1) and the
shot's ID image.

The ID image (core/capture/labels.py, "id_mask") is an 8-bit grey PNG whose
pixel value is the object's int_id: 0 = background, 1 = the primary airframe,
terrain and other objects their own ids. The numbers below cover ONLY the
pixels whose id is in ``--ids`` (default ``1``, the airframe). If the airframe
has labelled components with their own int_ids (the frame's labels list
them), add them: ``--ids 1,5,6``. Never ``mask > 0``: that takes the terrain.

On 8-bit luma, over those pixels:

* ``luma_ratio``      candidate mean luma / reference mean luma
* ``dark_share_delta`` change in the share of aircraft pixels with luma < 24
* ``clip_share_delta`` change in the share with luma >= 250
* ``detail_ratio``    candidate / reference mean |Laplacian| of luma (the
                      surface micro-structure the baked maps add)
* ``mean_abs_diff``   mean |candidate - reference| luma (reported, not gated)

PASS (exit 0) when luma_ratio is in [0.97, 1.08], dark_share_delta <= 0.01,
clip_share_delta <= 0.005 and detail_ratio >= 1.10. FAIL is exit 1.
REFUSED is exit 2: too few aircraft pixels, sizes differ, or the two frames
are pixel-identical over the aircraft (the switch never reached the render).

Two renders of the SAME scene are not pixel-identical when rain or temporal
AA is on, so an unwired switch usually shows up as detail_ratio near 1.0 and
a FAIL, not a refusal. A FAIL therefore does not by itself say the look is
wrong; a PASS does say the candidate differs in the wanted direction.

The thresholds are UNCALIBRATED proposals until one real pair of frames has
been through this script. Nothing here has been run on a rendered frame.

    python measure_gate.py --before ref\\a.png --after cand\\a.png --mask ref\\a_mask.png
"""

from __future__ import annotations

import argparse
import json
import sys

import numpy as np
from PIL import Image

LUMA_BAND = (0.97, 1.08)
DARK_LEVEL, CLIP_LEVEL = 24, 250
MAX_DARK_DELTA, MAX_CLIP_DELTA = 0.01, 0.005
MIN_DETAIL_RATIO = 1.10
MIN_AIRCRAFT_PIXELS = 2000
AIRFRAME_IDS = (1,)          # core/capture/labels.py: the primary airframe is always int_id 1
REFUSED = 2


def _refuse(message):
    print(f"REFUSED {message}", file=sys.stderr)
    raise SystemExit(REFUSED)


def _luma(path, size=None):
    image = Image.open(path).convert("L")
    if size and image.size != size:
        _refuse(f"{path}: size {image.size} is not the reference's {size}")
    return np.asarray(image, dtype=np.float64)


def _detail(luma, inside):
    lap = np.abs(4.0 * luma[1:-1, 1:-1] - luma[:-2, 1:-1] - luma[2:, 1:-1]
                 - luma[1:-1, :-2] - luma[1:-1, 2:])
    # only pixels whose whole 3x3 cross is aircraft: the silhouette edge is not detail
    core = (inside[1:-1, 1:-1] & inside[:-2, 1:-1] & inside[2:, 1:-1]
            & inside[1:-1, :-2] & inside[1:-1, 2:])
    return float(lap[core].mean()) if core.any() else 0.0


def measure(before, after, mask, ids=AIRFRAME_IDS):
    a = _luma(before)
    size = (a.shape[1], a.shape[0])
    b = _luma(after, size)
    id_image = Image.open(mask)
    if id_image.size != size:
        _refuse(f"{mask}: size {id_image.size} is not the frame's {size}; not this frame's ID image")
    m = np.isin(np.asarray(id_image.convert("L")), [int(i) for i in ids])
    count = int(m.sum())
    if count < MIN_AIRCRAFT_PIXELS:
        _refuse(f"{mask}: {count} pixels with int_id in {list(ids)}, fewer than "
                f"{MIN_AIRCRAFT_PIXELS}; the shot does not show enough airframe to judge")
    if np.array_equal(a[m], b[m]):
        _refuse("the two frames are pixel-identical over the aircraft: the "
                "CoastalWeathering switch did not reach the render (or one file was passed twice)")
    da, db = _detail(a, m), _detail(b, m)
    row = {
        "aircraft_ids": [int(i) for i in ids],
        "aircraft_pixels": count,
        "mean_luma_before": round(float(a[m].mean()), 2),
        "mean_luma_after": round(float(b[m].mean()), 2),
        "luma_ratio": round(float(b[m].mean() / max(a[m].mean(), 1e-6)), 4),
        "dark_share_delta": round(float((b[m] < DARK_LEVEL).mean() - (a[m] < DARK_LEVEL).mean()), 4),
        "clip_share_delta": round(float((b[m] >= CLIP_LEVEL).mean() - (a[m] >= CLIP_LEVEL).mean()), 4),
        "detail_ratio": round(db / max(da, 1e-6), 4),
        "mean_abs_diff": round(float(np.abs(b[m] - a[m]).mean()), 3),
    }
    row["checks"] = {
        "no_dark_regression": LUMA_BAND[0] <= row["luma_ratio"] <= LUMA_BAND[1]
                              and row["dark_share_delta"] <= MAX_DARK_DELTA,
        "no_blow_out": row["clip_share_delta"] <= MAX_CLIP_DELTA,
        "detail_improved": row["detail_ratio"] >= MIN_DETAIL_RATIO,
    }
    row["pass"] = all(row["checks"].values())
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--mask", required=True, help="the frame's ID image (pixel value = int_id)")
    ap.add_argument("--ids", default="1", help="comma-separated int_ids that are the airframe (default 1)")
    args = ap.parse_args(argv)
    row = measure(args.before, args.after, args.mask,
                  ids=[int(i) for i in args.ids.split(",") if i.strip()])
    print(json.dumps(row, indent=1))
    return 0 if row["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
