"""Judge one stress-ladder run and write the measured hardware budget.

Runs on the Windows laptop after a render (run_ladder.py calls it); stdlib
only. On the Mac it is exercised by tests on synthetic files, which is a
check of the arithmetic and never a measurement.

A run passes a tier when, for that run:
  * render.log shows the tier's ``-FlightSimStressTier=N`` marker (else the
    tier was never applied: ``tier_not_applied``);
  * render.log has no device-lost / GPU-crash / out-of-memory line;
  * at least ``min_frames`` frames exist and the p95 wall time between frames
    is under the limit (wall clock from frame file mtimes: it includes
    readback and PNG encode, so it bounds GPU frame time from above);
  * free system RAM never dropped under the floor (shared-memory GPU);
  * the CPU did not throttle (last third of ``% Processor Performance`` vs
    the first third) and the thermal zone, where Windows exposes one, stayed
    under the limit;
  * the first, middle and last frame are real pictures (not black, not flat).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import struct
import zlib
from pathlib import Path

DEVICE_LOST = re.compile(
    r"DXGI_ERROR_DEVICE_(REMOVED|HUNG|RESET)|DXGI_ERROR_DRIVER_INTERNAL_ERROR"
    r"|device (being |was )?(lost|removed)|GPU ?Crash|D3D ?device.*(lost|removed)", re.I)
OUT_OF_MEMORY = re.compile(
    r"Out of video memory|E_OUTOFMEMORY|Ran out of memory|OutOfMemory", re.I)
TIER_MARKER = re.compile(r"-FlightSimStressTier=(\d+)")
FRAME_NAME = re.compile(r"frame_\d+\.png$")


def scan_log(text: str) -> dict:
    marker = TIER_MARKER.search(text)
    return {"device_lost": len(DEVICE_LOST.findall(text)),
            "out_of_memory": len(OUT_OF_MEMORY.findall(text)),
            "tier_marker": int(marker.group(1)) if marker else None}


def percentile(values, q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    s = sorted(values)
    if not s:
        raise ValueError("no_values")
    k = (len(s) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def frame_files(run_dir: Path) -> list:
    """The frames of the camera with the most frames (beauty copies excluded)."""
    by_dir = {}
    for p in Path(run_dir).rglob("frame_*.png"):
        if FRAME_NAME.search(p.name):
            by_dir.setdefault(p.parent, []).append(p)
    if not by_dir:
        return []
    return sorted(max(by_dir.values(), key=len))


def frame_intervals_ms(frames: list) -> list:
    times = [p.stat().st_mtime for p in frames]
    return [(b - a) * 1000.0 for a, b in zip(times, times[1:])]


def parse_typeperf(path: Path) -> dict:
    """typeperf CSV -> {counter suffix (lower case): [row sums]}.

    Instances are summed per row (one GPU adapter may list several LUIDs).
    A blank cell is a missed sample and is skipped."""
    series: dict = {}
    path = Path(path)
    if not path.is_file():
        return series
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        rows = [r for r in csv.reader(fh) if r]
    if len(rows) < 2:
        return series
    names = [h.rsplit("\\", 1)[-1].strip().lower() for h in rows[0][1:]]
    for row in rows[1:]:
        sums: dict = {}
        for name, cell in zip(names, row[1:]):
            try:
                sums[name] = sums.get(name, 0.0) + float(cell)
            except ValueError:
                continue
        for name, value in sums.items():
            series.setdefault(name, []).append(value)
    return series


def _unfilter(kind: int, line: bytearray, prev: bytes, bpp: int) -> None:
    if kind == 0:
        return
    for i in range(len(line)):
        a = line[i - bpp] if i >= bpp else 0
        b = prev[i]
        if kind == 1:
            pred = a
        elif kind == 2:
            pred = b
        elif kind == 3:
            pred = (a + b) >> 1
        elif kind == 4:
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
        else:
            raise ValueError(f"png_bad_filter:{kind}")
        line[i] = (line[i] + pred) & 0xFF


def png_stats(path: Path, step: int = 4) -> dict:
    """Black fraction, clipped fraction and luma standard deviation of a
    non-interlaced RGB/RGBA PNG (8 or 16 bit), sampling every ``step`` pixel."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("png_bad_signature")
    pos, idat, head = 8, [], None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            head = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        pos += 12 + length
    if head is None:
        raise ValueError("png_no_header")
    width, height, depth, colour, _, _, interlace = head
    if colour not in (2, 6) or depth not in (8, 16) or interlace:
        raise ValueError(f"png_unsupported:colour{colour}_depth{depth}_interlace{interlace}")
    size = depth // 8
    bpp = (3 if colour == 2 else 4) * size
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    prev = bytes(stride)
    lumas, black, clipped = [], 0, 0
    for y in range(height):
        start = y * (stride + 1)
        line = bytearray(raw[start + 1:start + 1 + stride])
        _unfilter(raw[start], line, prev, bpp)
        prev = bytes(line)
        if y % step:
            continue
        for x in range(0, width, step):
            o = x * bpp
            r, g, b = line[o], line[o + size], line[o + 2 * size]  # high bytes
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            lumas.append(luma)
            black += luma < 4.0
            clipped += r >= 254 and g >= 254 and b >= 254
    n = len(lumas)
    return {"width": width, "height": height,
            "black_fraction": black / n, "clipped_fraction": clipped / n,
            "luma_stddev": statistics.pstdev(lumas)}


def _third_means(values: list):
    k = max(1, len(values) // 3)
    return statistics.fmean(values[:k]), statistics.fmean(values[-k:])


def judge_run(run_dir: Path, tier: int, thresholds: dict,
              sampler_csv: Path = None, thermal_csv: Path = None) -> dict:
    """One run -> {"pass", "reasons", "metrics"}. Every refusal is named."""
    run_dir = Path(run_dir)
    reasons, m = [], {"tier": tier, "run_dir": str(run_dir)}

    logs = sorted(run_dir.rglob("*.log"))
    log = scan_log("\n".join(p.read_text(encoding="utf-8", errors="replace") for p in logs))
    m.update(device_lost=log["device_lost"], out_of_memory=log["out_of_memory"])
    if not logs:
        reasons.append("no_render_log")
    elif log["tier_marker"] != tier:
        reasons.append(f"tier_not_applied:log_has_{log['tier_marker']}")
    if log["device_lost"] > thresholds["device_lost_max"]:
        reasons.append(f"device_lost:{log['device_lost']}")
    if log["out_of_memory"]:
        reasons.append(f"out_of_memory:{log['out_of_memory']}")

    frames = frame_files(run_dir)
    m["frames"] = len(frames)
    if len(frames) < thresholds["min_frames"]:
        reasons.append(f"too_few_frames:{len(frames)}")
    else:
        gaps = frame_intervals_ms(frames)
        m["frame_wall_ms_median"] = round(statistics.median(gaps), 2)
        m["frame_wall_ms_p95"] = round(percentile(gaps, 95), 2)
        m["frame_wall_ms_max"] = round(max(gaps), 2)
        if m["frame_wall_ms_p95"] > thresholds["frame_wall_ms_p95_max"]:
            reasons.append(f"frame_time_p95:{m['frame_wall_ms_p95']}ms")
        pictures = []
        for p in {frames[0], frames[len(frames) // 2], frames[-1]}:
            s = png_stats(p)
            pictures.append(s)
            if s["black_fraction"] > thresholds["black_fraction_max"]:
                reasons.append(f"black_frame:{p.name}")
            if s["luma_stddev"] < thresholds["luma_stddev_min"]:
                reasons.append(f"flat_frame:{p.name}")
        m["frame_width"], m["frame_height"] = pictures[0]["width"], pictures[0]["height"]
        m["black_fraction_max"] = round(max(s["black_fraction"] for s in pictures), 4)
        m["clipped_fraction_max"] = round(max(s["clipped_fraction"] for s in pictures), 4)

    s = parse_typeperf(sampler_csv) if sampler_csv else {}
    ram, perf = s.get("available mbytes"), s.get("% processor performance")
    gpu = [a + b for a, b in zip(s.get("shared usage", []), s.get("dedicated usage", []))]
    if not ram or not perf or not gpu:
        reasons.append("sampler_empty")
    else:
        m["available_ram_mb_min"] = round(min(ram), 1)
        m["gpu_memory_mb_peak"] = round(max(gpu) / (1024 * 1024), 1)
        first, last = _third_means(perf)
        m["throttle_ratio"] = round(last / first, 3) if first > 0 else 0.0
        if m["available_ram_mb_min"] < thresholds["available_ram_mb_min"]:
            reasons.append(f"low_ram:{m['available_ram_mb_min']}MB")
        if m["throttle_ratio"] < thresholds["throttle_ratio_min"]:
            reasons.append(f"cpu_throttled:{m['throttle_ratio']}")
    kelvin = parse_typeperf(thermal_csv).get("temperature") if thermal_csv else None
    if kelvin:
        m["temperature_c_max"] = round(max(kelvin) - 273.15, 1)
        if m["temperature_c_max"] > thresholds["temperature_c_max"]:
            reasons.append(f"too_hot:{m['temperature_c_max']}C")
    else:
        m["temperature_c_max"] = None   # no thermal zone counter on this machine

    return {"pass": not reasons, "reasons": reasons, "metrics": m}


def summarise(ladder: dict, results: list) -> dict:
    """Run verdicts -> the measured budget. A tier is sustained when it has
    ``runs_per_tier`` verdicts and all pass; the sustained tier is the highest
    one with every tier below it sustained too. ``measured`` is true only when
    tier 0 is sustained."""
    need = ladder["protocol"]["runs_per_tier"]
    by_tier: dict = {}
    for r in results:
        by_tier.setdefault(r["metrics"]["tier"], []).append(r)
    sustained = None
    for t in ladder["tiers"]:
        runs = by_tier.get(t["tier"], [])
        if len(runs) >= need and all(r["pass"] for r in runs):
            sustained = t["tier"]
        else:
            break
    out = {"lane": ladder["lane"], "scenario": "alpine", "measured": sustained is not None,
           "sustained_tier": sustained,
           "device_lost_total": sum(r["metrics"]["device_lost"] for r in results),
           "runs": results}
    if sustained is None:
        out["refused"] = "tier0_not_sustained"
        return out
    tier = ladder["tiers"][sustained]
    runs = by_tier[sustained]
    peak = max(r["metrics"]["gpu_memory_mb_peak"] for r in runs)
    out["budget"] = {
        "tier": "integrated", "rhi": "d3d11", "hardware_ray_tracing": False,
        "measured": True, "stress_tier": sustained,
        # the most GPU memory this machine was SEEN to hold through 3 runs
        "usable_vram_mb": int(peak),
        "max_capture_width": tier["width"], "max_capture_height": tier["height"],
        "gpu_render_jobs": 1, "cvars": tier["cvars"], "tileset": tier["tileset"],
        "frame_wall_ms_p95": max(r["metrics"]["frame_wall_ms_p95"] for r in runs),
        "available_ram_mb_min": min(r["metrics"]["available_ram_mb_min"] for r in runs),
        "throttle_ratio_min": min(r["metrics"]["throttle_ratio"] for r in runs),
        "temperature_c_max": max((r["metrics"]["temperature_c_max"] for r in runs
                                  if r["metrics"]["temperature_c_max"] is not None),
                                 default=None),
    }
    return out


def main(argv=None) -> int:
    lane = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ladder", type=Path, default=lane / "alpine_ladder.json")
    ap.add_argument("--results", type=Path, required=True,
                    help="JSON list of judge_run verdicts (run_ladder.py writes it)")
    ap.add_argument("--out", type=Path, default=lane / "measured" / "hardware_budget_measured.json")
    a = ap.parse_args(argv)
    summary = summarise(json.loads(a.ladder.read_text()), json.loads(a.results.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(f"sustained_tier={summary['sustained_tier']} "
          f"device_lost_total={summary['device_lost_total']} measured={summary['measured']}")
    return 0 if summary["measured"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
