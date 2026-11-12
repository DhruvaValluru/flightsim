"""Windows-side gate for the alpine VRAM ledger. Run on the test laptop only.

One command, no arguments to fill in (repo root, venv python, web app NOT
already running on port 8008):

    python swarm\\lanes\\hardware_perf\\vram_budgeting\\alpine\\measure_vram_gate.py --tier 0

What it does, twice (pass "reference" = today's render path unchanged, then
pass "tier<N>" = the tier's settings):
  1. samples the GPU adapter memory counters with the app stopped (idle);
  2. starts the web app itself, so the settings are in the environment the
     render process inherits (FLIGHTSIM_GOOGLE_TILES_SSE, and the tier's
     cvars as a UE ``-ini:Engine:[SystemSettings]:`` override riding
     FLIGHTSIM_RENDER_SWITCHES);
  3. runs ``scripts/run_test_scenarios.py --still --only 11 --compiler regex``
     (scenario 11 = "A-4 over the matterhorn", the alpine scene) while a
     thread samples the counters with ``typeperf -sc 1``;
  4. copies that run's first frame and its render.log into
     runs/alpine_vram_gate/, stops the app, restores runs/test_scenarios.json.
Then it compares the two frames and prints/writes the verdict.

Pass = both renders finished AND zero device-lost lines in the tier pass AND
its peak GPU memory above idle <= the cap AND ground sharpness kept (median
over the lower-half grid cells of candidate/reference Laplacian variance
>= 0.95). 0.95 is a chosen threshold, not a validated one.

This gate measures GPU memory, device loss and (when the machine exposes the
counter) temperature. It does NOT measure frame time: a --still render is one
frame from a commandlet, so there is no frame-time series to read. The patch
it writes therefore never says ``measured: true`` for the whole hardware
budget; it lists exactly which fields were measured.

On the Mac only the parsers and the logic run, under unit test.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import zlib
from pathlib import Path

MB = 1024 * 1024
SHARPNESS_FLOOR = 0.95
SCENARIO_NUMBER = 11                      # "A-4 over the matterhorn" in run_test_scenarios.SCENARIOS
SCENARIO_WORD = "matterhorn"
SERVER = "http://127.0.0.1:8008"
REPO = Path(__file__).resolve().parents[5]
OUT = REPO / "runs" / "alpine_vram_gate"
MEM_COUNTERS = [r"\GPU Adapter Memory(*)\Shared Usage", r"\GPU Adapter Memory(*)\Dedicated Usage"]
TEMP_COUNTER = r"\Thermal Zone Information(*)\Temperature"
DEVICE_LOST = re.compile(r"DXGI_ERROR_DEVICE_(REMOVED|HUNG|RESET)|device (was )?(lost|removed)"
                         r"|GPU crash", re.I)


# ---------------------------------------------------------------- parsers

def parse_typeperf(text: str) -> dict:
    """typeperf CSV (file or stdout, banner lines tolerated) ->
    {'gpu_bytes': [per-sample sum of shared+dedicated], 'temp_c': [per-sample max]}"""
    rows = list(csv.reader(text.splitlines()))
    hi = next((i for i, r in enumerate(rows) if any("PDH-CSV" in c for c in r)), None)
    if hi is None:
        return {"gpu_bytes": [], "temp_c": []}
    head = rows[hi]
    mem = [i for i, h in enumerate(head) if "GPU Adapter Memory" in h
           and ("Shared Usage" in h or "Dedicated Usage" in h)]
    tmp = [i for i, h in enumerate(head) if "Thermal Zone" in h and "Temperature" in h]
    hi_prec = {i for i in tmp if "High Precision" in head[i]}

    def num(row, i):
        try:
            return float(row[i])
        except (ValueError, IndexError):
            return None

    gpu, temp = [], []
    for row in rows[hi + 1:]:
        m = [v for v in (num(row, i) for i in mem) if v is not None]
        if mem and len(m) == len(mem):
            gpu.append(sum(m))
        # Thermal Zone Temperature is kelvin (High Precision: tenths of a kelvin)
        t = [(v / 10 if i in hi_prec else v) - 273.15
             for i, v in ((i, num(row, i)) for i in tmp) if v]
        if t:
            temp.append(max(t))
    return {"gpu_bytes": gpu, "temp_c": temp}


def count_device_lost(log_text: str) -> int:
    return sum(1 for line in log_text.splitlines() if DEVICE_LOST.search(line))


def cvar_switch(cvars: dict) -> str:
    """The tier's cvars as one UE command-line config override token."""
    return "-ini:Engine:" + ",".join(f"[SystemSettings]:{k}={v}" for k, v in sorted(cvars.items()))


def read_png_gray(data: bytes) -> list:
    """Non-interlaced 8/16-bit grey, RGB, grey+alpha or RGBA PNG -> rows of
    0..255 luma floats. Stdlib only, so the gate needs no Pillow."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos, idat, w = 8, [], 0
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", body)
            if depth not in (8, 16) or ctype not in (0, 2, 4, 6) or lace:
                raise ValueError(f"unsupported PNG (depth {depth}, colour type {ctype}, interlace {lace})")
        elif kind == b"IDAT":
            idat.append(body)
    chans = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    bps = depth // 8
    bpp = chans * bps
    stride = w * bpp
    raw = zlib.decompress(b"".join(idat))
    prev = bytearray(stride)
    out = []
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + (((line[i - bpp] if i >= bpp else 0) + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif f != 0:
            raise ValueError(f"bad PNG filter {f}")
        prev = line
        top = line[0::bps]                 # most significant byte of every sample
        if chans >= 3:
            out.append([0.2126 * top[i] + 0.7152 * top[i + 1] + 0.0722 * top[i + 2]
                        for i in range(0, w * chans, chans)])
        else:
            out.append([float(v) for v in top[0::chans]])
    return out


def laplacian_variance(gray: list) -> float:
    """gray: rows of floats. Variance of the 4-neighbour Laplacian (sharpness)."""
    vals = [gray[y - 1][x] + gray[y + 1][x] + gray[y][x - 1] + gray[y][x + 1] - 4 * gray[y][x]
            for y in range(1, len(gray) - 1) for x in range(1, len(gray[0]) - 1)]
    return statistics.pvariance(vals) if len(vals) > 1 else 0.0


def ground_sharpness_ratio(ref: list, cand: list, box=None, rows: int = 4, cols: int = 8,
                           flat: float = 1.0):
    """Median over grid cells of candidate/reference Laplacian variance.

    Default region is the lower half of the frame, where the terrain is in the
    chase view; the median keeps the aircraft and any sky cells from deciding.
    Cells whose reference variance is below ``flat`` (fog, sky) are skipped.
    None when the frames differ in size or fewer than 4 cells have detail."""
    if len(ref) != len(cand) or not ref or len(ref[0]) != len(cand[0]):
        return None
    h, w = len(ref), len(ref[0])
    x0, y0, x1, y1 = box or (0, h // 2, w, h)
    ratios = []
    for r in range(rows):
        for c in range(cols):
            ya, yb = y0 + (y1 - y0) * r // rows, y0 + (y1 - y0) * (r + 1) // rows
            xa, xb = x0 + (x1 - x0) * c // cols, x0 + (x1 - x0) * (c + 1) // cols
            vr = laplacian_variance([row[xa:xb] for row in ref[ya:yb]])
            if vr >= flat:
                ratios.append(laplacian_variance([row[xa:xb] for row in cand[ya:yb]]) / vr)
    return statistics.median(ratios) if len(ratios) >= 4 else None


def evaluate(cap_mb: float, gpu_bytes: list, idle_bytes: list, device_lost,
             render_done, temp_c: list, sharp_ratio) -> dict:
    idle = statistics.median(idle_bytes) if idle_bytes else None
    peak = (max(gpu_bytes) - idle) / MB if gpu_bytes and idle is not None else None
    checks = {
        "render_done": None if render_done is None else bool(render_done),
        "no_device_lost": None if device_lost is None else device_lost == 0,
        "peak_under_cap": None if peak is None else peak <= cap_mb,
        "ground_sharpness_kept": None if sharp_ratio is None else sharp_ratio >= SHARPNESS_FLOOR,
    }
    measured = [name for name, have in (("peak_gpu_memory", peak is not None),
                                        ("device_loss", device_lost is not None),
                                        ("temperature", bool(temp_c))) if have]
    return {
        "cap_mb": cap_mb,
        "peak_gpu_mb_above_idle": None if peak is None else round(peak, 1),
        "gpu_samples": len(gpu_bytes),
        "device_lost_lines": device_lost,
        "temp_c_max": round(max(temp_c), 1) if temp_c else None,
        "ground_sharpness_ratio": None if sharp_ratio is None else round(sharp_ratio, 4),
        "checks": checks,
        "passed": all(v is True for v in checks.values()),
        "measured_fields": measured,
        "not_measured": ["frame_time"] + ([] if temp_c else ["temperature"]),
        "may_write_patch": {"peak_gpu_memory", "device_loss"} <= set(measured) and bool(render_done),
    }


# ------------------------------------------------- Windows orchestration

def _typeperf_once(counters: list) -> str:
    try:
        return subprocess.run(["typeperf", *counters, "-sc", "1"], capture_output=True,
                              text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


class Sampler(threading.Thread):
    """Samples the counters about every 2 s until stopped. A spike shorter than
    the gap between samples can be missed; the peak is a lower bound."""

    def __init__(self):
        super().__init__(daemon=True)
        self.gpu, self.temp, self._stop_flag, self._temp_ok = [], [], threading.Event(), True

    def sample(self):
        self.gpu += parse_typeperf(_typeperf_once(MEM_COUNTERS))["gpu_bytes"]
        if self._temp_ok:                 # the thermal counter is missing on some machines
            t = parse_typeperf(_typeperf_once([TEMP_COUNTER]))["temp_c"]
            self._temp_ok = bool(t)
            self.temp += t

    def run(self):
        while not self._stop_flag.is_set():
            self.sample()
            self._stop_flag.wait(1.0)

    def stop(self):
        self._stop_flag.set()
        self.join(60)


def _app_up() -> bool:
    try:
        urllib.request.urlopen(SERVER + "/status", timeout=5).read()
        return True
    except OSError:
        return False


def _kill_tree(proc) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/t", "/f"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(30)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_pass(label: str, env_extra: dict) -> dict:
    """One render of the alpine scene with env_extra set for the app. Returns
    {'idle','gpu','temp','done','why','frame','log_text','seconds'}."""
    OUT.mkdir(parents=True, exist_ok=True)
    idle = Sampler()
    for _ in range(8):
        idle.sample()
    env = {k: v for k, v in os.environ.items()
           if k not in ("FLIGHTSIM_GOOGLE_TILES_SSE", "FLIGHTSIM_RENDER_SWITCHES")}
    env.update(env_extra)
    summary = REPO / "runs" / "test_scenarios.json"
    keep = summary.read_bytes() if summary.is_file() else None
    out = {"idle": idle.gpu, "gpu": [], "temp": [], "done": False, "why": "", "frame": None,
           "log_text": None, "seconds": None, "env": env_extra}
    with open(OUT / f"{label}_app.log", "w") as app_log:
        app = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.server:app", "--port", "8008"],
                               cwd=REPO, env=env, stdout=app_log, stderr=subprocess.STDOUT)
        sampler = Sampler()
        try:
            deadline = time.monotonic() + 180
            while not _app_up():
                if app.poll() is not None or time.monotonic() > deadline:
                    out["why"] = f"the web app did not start; see {OUT / (label + '_app.log')}"
                    return out
                time.sleep(2)
            sampler.start()
            subprocess.run([sys.executable, str(REPO / "scripts" / "run_test_scenarios.py"), "--still",
                            "--only", str(SCENARIO_NUMBER), "--compiler", "regex"], cwd=REPO, env=env)
        finally:
            if sampler.is_alive():
                sampler.stop()
            _kill_tree(app)
    out["gpu"], out["temp"] = sampler.gpu, sampler.temp
    try:
        rows = json.loads(summary.read_text(encoding="utf-8"))
        row = next(r for r in rows if int(r["number"]) == SCENARIO_NUMBER)
    except (OSError, ValueError, StopIteration):
        row = {"outcome": "failed", "why": "no row for the scene in runs/test_scenarios.json"}
    finally:
        if keep is not None:
            summary.write_bytes(keep)
    if SCENARIO_WORD not in str(row.get("name", SCENARIO_WORD)).lower():
        row = {"outcome": "failed", "why": f"scenario {SCENARIO_NUMBER} is not the {SCENARIO_WORD} scene any more"}
    out["done"], out["why"], out["seconds"] = row.get("outcome") == "done", str(row.get("why", "")), row.get("seconds")
    run_dir = REPO / "runs" / "webapp" / str(row.get("run_id") or "-")
    if row.get("run_id") and run_dir.is_dir():
        logs = sorted(run_dir.rglob("render.log"))
        if logs:
            out["log_text"] = "\n".join(p.read_text(errors="replace") for p in logs)
            (OUT / f"{label}_render.log").write_text(out["log_text"], errors="replace")
        frames = sorted(p for p in run_dir.glob("frames/*/frame_*.png")
                        if re.fullmatch(r"frame_\d+\.png", p.name))
        if frames:
            out["frame"] = OUT / f"{label}.png"
            shutil.copy2(frames[0], out["frame"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--budget", type=Path, default=Path(__file__).with_name("alpine_vram_budget.json"))
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--no-cvars", action="store_true",
                    help="set only the tile SSE; do not pass the tier's cvars on the UE command line")
    ap.add_argument("--ground-box", default="", help="optional x0,y0,x1,y1; default is the lower half")
    a = ap.parse_args()
    if os.name != "nt":
        print("refused: this gate runs on the Windows test laptop only (typeperf, the pinned UE build)")
        return 2
    if _app_up():
        print("refused: a web app is already answering on port 8008; stop it first "
              "(the gate starts its own so the tier settings reach the render process)")
        return 2
    budget = json.loads(a.budget.read_text())
    tier = budget["tiers"][a.tier]
    sse = tier["cesium_tileset"]["MaximumScreenSpaceError"]
    env = {"FLIGHTSIM_GOOGLE_TILES_SSE": f"{sse:g}"}
    if not a.no_cvars:
        env["FLIGHTSIM_RENDER_SWITCHES"] = cvar_switch(tier["cvars"])

    ref = run_pass("reference", {})
    cand = run_pass(f"tier{a.tier}", env)
    ratio = None
    if ref["frame"] and cand["frame"]:
        box = tuple(int(v) for v in a.ground_box.split(",")) if a.ground_box else None
        ratio = ground_sharpness_ratio(read_png_gray(ref["frame"].read_bytes()),
                                       read_png_gray(cand["frame"].read_bytes()), box)
    lost = None if cand["log_text"] is None else count_device_lost(cand["log_text"] + "\n" + cand["why"])
    res = evaluate(float(budget["usable_vram_mb"]), cand["gpu"], cand["idle"], lost,
                   cand["done"] and ref["done"], cand["temp"], ratio)
    pool = tier["cvars"].get("r.Streaming.PoolSize")
    res.update({
        "tier": a.tier, "est_vram_mb": tier["est_vram_mb"], "settings_applied": env,
        # not a check: tells the reader whether the -ini: override visibly reached the engine
        "pool_cvar_seen_in_log": None if cand["log_text"] is None or a.no_cvars
        else bool(re.search(rf"r\.Streaming\.PoolSize\W+{pool}\b", cand["log_text"])),
        "reference": {"done": ref["done"], "why": ref["why"][:300],
                      "device_lost_lines": None if ref["log_text"] is None
                      else count_device_lost(ref["log_text"] + "\n" + ref["why"]),
                      "peak_gpu_mb_above_idle": evaluate(0, ref["gpu"], ref["idle"], None, None, [], None)
                      ["peak_gpu_mb_above_idle"]},
        "candidate_why": cand["why"][:300],
        "scene_wall_seconds": {"reference": ref["seconds"], "candidate": cand["seconds"]},
        "frames": {"reference": str(ref["frame"]), "candidate": str(cand["frame"])},
    })
    (OUT / f"tier{a.tier}_gate.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))
    patch = OUT / f"tier{a.tier}_budget_patch.json"
    if res["passed"] and res["may_write_patch"]:
        patch.write_text(json.dumps({
            "scenario": "alpine", "tier": a.tier, "measured_fields": res["measured_fields"],
            "not_measured": res["not_measured"], "usable_vram_mb": budget["usable_vram_mb"],
            "cvars": tier["cvars"], "cesium_tileset": tier["cesium_tileset"],
            "measurement": {k: res[k] for k in ("peak_gpu_mb_above_idle", "gpu_samples",
                                                "device_lost_lines", "temp_c_max",
                                                "ground_sharpness_ratio")},
        }, indent=1) + "\n")
        print(f"gate PASSED; wrote {patch}")
        return 0
    print("gate NOT passed: no budget patch written")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
