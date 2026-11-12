"""Windows-side gate for the alpine capture ladder. Run on the test laptop only.

It measures nothing itself: it reads what the laptop recorded while one tier
rendered and decides whether the tier held and whether the frame got better.
On the Mac only its parsers and image arithmetic run, under unit test.

  --reference / --candidate  resolved PNGs (tier 0 frame / the tier under test)
  --ridge-box  x0,y0,x1,y1   box on the ridge-against-sky silhouette  (pixels of the
  --ground-box x0,y0,x1,y1   box on textured ground or rock            1280x800 reference)
  --typeperf / --idle        typeperf CSVs of "\\GPU Adapter Memory(*)\\Shared Usage",
                             "...\\Dedicated Usage" and
                             "\\Thermal Zone Information(*)\\Temperature",
                             during the render and for ~20 s before it
  --resolve-report           the .resolve.json resolve_capture.py wrote beside the frame
  --log                      UE log of the render (device-lost lines counted)
  --frames                   UE CsvProfiler file (-csvprofile), FrameTime column in ms

Pass (tier N >= 1) = zero device-lost lines AND max frame time <= 1000 ms AND
peak GPU memory above idle <= 491 MB AND peak temperature <= 90 C AND seam
excess <= 1.0 level (tiled tiers) AND sample spread <= 1.0 level (multi-sample
tiers) AND alias ratio <= 0.75 AND ground sharpness ratio >= 1.0 (tiers 2, 3).

alias ratio: the candidate is box-averaged down to the reference's 1280x800
and the diagonal-band share of the ridge box is divided by the reference's
(lower = fewer stair steps on the silhouette at the same size).
ground sharpness ratio: the reference is Lanczos-enlarged to the candidate's
size and the Laplacian variance of the ground box is compared there (above 1
= the larger frame holds detail the 1280 frame did not).

With --write-measured, a hardware_budget patch with measured=true is written
ONLY when the tier passed and frame time, memory and temperature were all
present in the inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

import numpy as np

LANE = Path(__file__).resolve().parent
MB = 1024 * 1024
DEVICE_LOST = re.compile(r"DXGI_ERROR_DEVICE_(REMOVED|HUNG|RESET)|device (was )?(lost|removed)|GPU crash", re.I)


# ---- image arithmetic -------------------------------------------------------
def alias_fraction(gray: np.ndarray) -> float:
    """Share of 2x2 Haar detail energy in the diagonal (HH) band. A stair-stepped
    edge puts energy there at every step corner; a resolved edge does not."""
    g = gray.astype(np.float64)
    a, b, c, d = g[:-1, :-1], g[:-1, 1:], g[1:, :-1], g[1:, 1:]
    hh = ((a - b - c + d) ** 2).sum()
    rest = ((a + b - c - d) ** 2).sum() + ((a - b + c - d) ** 2).sum()
    return float(hh / (hh + rest + 1e-12))


def sharpness(gray: np.ndarray) -> float:
    """Variance of the 4-neighbour Laplacian."""
    g = gray.astype(np.float64)
    lap = g[1:-1, :-2] + g[1:-1, 2:] + g[:-2, 1:-1] + g[2:, 1:-1] - 4 * g[1:-1, 1:-1]
    return float(lap.var())


def seam_excess(gray: np.ndarray, grid) -> float:
    """Mean absolute step across the tile seams minus the mean step 2..8 px to
    either side, in 8-bit levels. 0 for a 1x1 grid."""
    g = gray.astype(np.float64)
    worst = 0.0
    for axis, n in ((1, grid[0]), (0, grid[1])):
        step = np.abs(np.diff(g, axis=axis)).mean(axis=1 - axis)
        for k in range(1, n):
            s = k * g.shape[axis] // n - 1
            near = [step[s + o] for o in (-8, -6, -4, -2, 2, 4, 6, 8)]
            worst = max(worst, float(step[s] - np.mean(near)))
    return worst


def box_reduce(gray: np.ndarray, k: int) -> np.ndarray:
    h, w = gray.shape
    return gray.astype(np.float64).reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def pixel_metrics(ref_img, cand_img, ridge_box, ground_box) -> dict:
    """ref_img, cand_img: PIL images; boxes (x0, y0, x1, y1) in reference pixels."""
    from PIL import Image
    ref, cand = (np.asarray(i.convert("L")) for i in (ref_img, cand_img))
    k = cand.shape[1] // ref.shape[1]
    if k < 1 or cand.shape != (ref.shape[0] * k, ref.shape[1] * k):
        raise SystemExit(f"candidate {cand.shape} is not a whole multiple of reference {ref.shape}")
    x0, y0, x1, y1 = ridge_box
    ridge = (slice(y0, y1), slice(x0, x1))
    x0, y0, x1, y1 = (v * k for v in ground_box)
    ground = (slice(y0, y1), slice(x0, x1))
    ref_up = ref if k == 1 else np.asarray(ref_img.convert("L").resize(cand.shape[::-1], Image.LANCZOS))
    return {"alias_ratio": alias_fraction(box_reduce(cand, k)[ridge]) / max(alias_fraction(ref[ridge]), 1e-12),
            "ground_sharpness_ratio": sharpness(cand[ground]) / max(sharpness(ref_up[ground]), 1e-12)}


# ---- recorded-run parsers ---------------------------------------------------
def parse_typeperf(text: str) -> dict:
    """-> {'gpu_bytes': [shared+dedicated per sample], 'temp_c': [max per sample]}"""
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return {"gpu_bytes": [], "temp_c": []}
    head = rows[0]
    mem = [i for i, h in enumerate(head) if "GPU Adapter Memory" in h
           and ("Shared Usage" in h or "Dedicated Usage" in h)]
    tmp = [i for i, h in enumerate(head) if "Thermal Zone" in h and "Temperature" in h]

    def num(row, i):
        try:
            return float(row[i])
        except (ValueError, IndexError):
            return None

    gpu, temp = [], []
    for row in rows[1:]:
        m = [num(row, i) for i in mem]
        if mem and None not in m:
            gpu.append(sum(m))
        # the counter is kelvin; "High Precision Temperature" is tenths of a kelvin
        t = [(v / 10 if "High Precision" in head[i] else v) - 273.15
             for i in tmp if (v := num(row, i)) is not None]
        if t:
            temp.append(max(t))
    return {"gpu_bytes": gpu, "temp_c": temp}


def parse_frames(text: str) -> list:
    """FrameTime column (ms) of a UE CsvProfiler file; metadata rows are skipped."""
    rows = list(csv.reader(text.splitlines()))
    col = next((i for i, h in enumerate(rows[0]) if h.strip() == "FrameTime"), None) if rows else None
    out = []
    for row in rows[1:]:
        if row and row[0].startswith("["):
            continue
        try:
            out.append(float(row[col]))
        except (ValueError, IndexError, TypeError):
            pass
    return out


def count_device_lost(text: str) -> int:
    return sum(1 for line in text.splitlines() if DEVICE_LOST.search(line))


# ---- the decision -----------------------------------------------------------
def decide(tier_plan: dict, gate: dict, m: dict) -> dict:
    """m: measurements; a key that was not measured is absent or None."""
    checks = {}
    tier = tier_plan["tier"]

    def check(name, value, ok):
        checks[name] = {"value": value, "pass": None if value is None else bool(ok(value))}

    check("device_lost_lines", m.get("device_lost_lines"), lambda v: v == 0)
    check("max_frame_ms", m.get("max_frame_ms"), lambda v: v <= gate["frame_ms_ceiling"])
    check("gpu_mb_above_idle", m.get("gpu_mb_above_idle"), lambda v: v <= gate["gpu_mb_above_idle_ceiling"])
    check("peak_temp_c", m.get("peak_temp_c"), lambda v: v <= gate["temp_c_ceiling"])
    if tier >= 1:
        check("seam_excess_levels", m.get("seam_excess_levels"), lambda v: v <= gate["seam_excess_levels_ceiling"])
        check("alias_ratio", m.get("alias_ratio"), lambda v: v <= gate["alias_ratio_ceiling"])
    if str(tier) in gate["ground_sharpness_floor"]:
        check("ground_sharpness_ratio", m.get("ground_sharpness_ratio"),
              lambda v: v >= gate["ground_sharpness_floor"][str(tier)])
    if tier_plan["samples_per_pixel"] > 1:
        check("sample_spread_levels", m.get("sample_spread_levels"),
              lambda v: v <= gate["sample_spread_levels_ceiling"])
    unmeasured = [k for k, c in checks.items() if c["pass"] is None]
    failed = [k for k, c in checks.items() if c["pass"] is False]
    return {"tier": tier, "checks": checks, "unmeasured": unmeasured, "failed": failed,
            "passed": not failed and not unmeasured}


def measured_patch(tier_plan: dict, verdict: dict) -> dict | None:
    """The hardware_budget patch, or None unless everything was measured and passed."""
    if not verdict["passed"]:
        return None
    return {"measured": True,
            "max_capture_width": tier_plan["delivered_px"][0],
            "max_pass_render_px": tier_plan["pass_render_px"],
            "capture_ladder_tier": tier_plan["tier"],
            "measurements": {k: c["value"] for k, c in verdict["checks"].items()}}


def _box(s: str):
    return tuple(int(v) for v in s.split(","))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", type=int, required=True)
    for name in ("reference", "candidate", "typeperf", "idle", "log", "frames", "resolve-report", "write-measured"):
        ap.add_argument(f"--{name}", type=Path)
    ap.add_argument("--ridge-box")
    ap.add_argument("--ground-box")
    a = ap.parse_args()
    plan = json.loads((LANE / "alpine_capture_ladder.json").read_text())
    tier_plan = next(t for t in plan["tiers"] if t["tier"] == a.tier)
    m = {}
    if a.log:
        m["device_lost_lines"] = count_device_lost(a.log.read_text(errors="replace"))
    if a.frames and (f := parse_frames(a.frames.read_text(errors="replace"))):
        m["max_frame_ms"] = max(f)
    if a.typeperf and a.idle:
        run, idle = (parse_typeperf(p.read_text(errors="replace")) for p in (a.typeperf, a.idle))
        if run["gpu_bytes"] and idle["gpu_bytes"]:
            m["gpu_mb_above_idle"] = (max(run["gpu_bytes"]) - float(np.median(idle["gpu_bytes"]))) / MB
        if run["temp_c"]:
            m["peak_temp_c"] = max(run["temp_c"])
    if a.resolve_report:
        m["sample_spread_levels"] = json.loads(a.resolve_report.read_text())["sample_spread_levels"]
    if a.candidate and a.tier >= 1:
        from PIL import Image
        m["seam_excess_levels"] = seam_excess(np.asarray(Image.open(a.candidate).convert("L")), tier_plan["grid"])
        if a.reference and a.ridge_box and a.ground_box:
            m.update(pixel_metrics(Image.open(a.reference), Image.open(a.candidate),
                                   _box(a.ridge_box), _box(a.ground_box)))
    verdict = decide(tier_plan, plan["gate"], m)
    print(json.dumps(verdict, indent=1))
    patch = measured_patch(tier_plan, verdict)
    if a.write_measured and patch:
        a.write_measured.write_text(json.dumps(patch, indent=1) + "\n")
        print(f"wrote {a.write_measured}")
    elif a.write_measured:
        print("no measured patch written: " + ", ".join(verdict["failed"] + verdict["unmeasured"]))
    raise SystemExit(0 if verdict["passed"] else 1)


if __name__ == "__main__":
    main()
