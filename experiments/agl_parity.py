"""AGL parity over the real ridge: the deferred Phase 6B stretch goal, measured.

Both hosts get real ground from the SAME baked raster (one raster, one sha):

* headless -- ``TerrainGround`` writes the raster elevation under the
  aircraft into the FDM every step (bilinear lookup on the 30 m grid);
* UE -- the flat query slab is replaced by collision geometry built from the
  raster's full 30 m grid (``collision_terrain`` in the card), traced by the
  plugin's own ground callback.

Then the SAME spec flies in both, hands off from trim, and ``agl_m`` is
compared on each host's own recorded clock under Gate 5 discipline
(gate5_ue_parity.compare's time-base rules, applied to the AGL channel).

Tolerance, stated before measuring
----------------------------------
The remaining difference between hosts is triangle-vs-bilinear interpolation
inside one 30 m cell plus whatever trajectory divergence altitude parity
already allows. On slopes up to the raster's p99 (~23 deg on the real
scenes) a 30 m cell's diagonal split can disagree with bilinear by a few
metres at mid-cell; the altitude channel's own tolerance is 5 m. AGL
tolerance: **p95 |Δ| <= 8 m and max |Δ| <= 20 m**. If the measurement holds,
the "physics ground: flat slab" label comes off the affected clips; if it
does not, these numbers get published and the label stays.

Usage: .venv/bin/python experiments/agl_parity.py [--skip-runs]
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from core.util.platform import ue_editor_path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.scenario.runner import run_spec  # noqa: E402
from core.terrain.glo30 import LOCATIONS  # noqa: E402
from core.terrain.ground import TerrainGround  # noqa: E402
from core.terrain.heightfield import Heightfield  # noqa: E402
from experiments.gate5_ue_parity import reference_spec, write_run_card  # noqa: E402

RULE = "=" * 96

TOLERANCE = {
    "p95_abs_m": 8.0,
    "max_abs_m": 20.0,
    #: The run must actually fly over varying ground, or "parity" is the
    #: flat slab in disguise: the raster elevation under the track must span
    #: at least this much.
    "min_ground_relief_m": 50.0,
}


def run_ue(card: Path, out: Path) -> None:
    editor = ue_editor_path()
    project = Path(__file__).resolve().parents[1] / "ue" / "FlightSim.uproject"
    out.unlink(missing_ok=True)
    command = [
        str(editor), str(project), "-run=FlightSimBridge.FlightSimScenario",
        f"-scenario={card}", f"-telemetry={out}",
        "-unattended", "-nopause", "-nosplash", "-nullrhi",
        "-stdout", "-FullStdOutLogOutput",
    ]
    log = out.with_suffix(".log")
    with log.open("w") as sink:
        proc = subprocess.run(command, stdout=sink, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL)
    if not out.is_file():
        raise RuntimeError(f"UE run wrote no telemetry (exit {proc.returncode}); "
                           f"see {log}")


def interpolate(times: Sequence[float], values: Sequence[float],
                at: float) -> float:
    from bisect import bisect_left

    i = bisect_left(times, at)
    if i <= 0:
        return values[0]
    if i >= len(times):
        return values[-1]
    t0, t1 = times[i - 1], times[i]
    f = 0.0 if t1 == t0 else (at - t0) / (t1 - t0)
    return values[i - 1] * (1.0 - f) + values[i] * f


def compare_agl(headless: Dict, unreal: Dict) -> Dict:
    """gate5 compare()'s time-base rules, applied to the agl channel."""
    a, b = headless["columns"], unreal["columns"]
    at, bt = a["t"], b["t"]
    start = max(at[1] if len(at) > 1 else at[0],
                bt[1] if len(bt) > 1 else bt[0])
    end = min(at[-1], bt[-1])
    grid = [t for t in at if start <= t <= end]
    differences = [abs(interpolate(at, a["agl_m"], t)
                       - interpolate(bt, b["agl_m"], t)) for t in grid]
    differences.sort()
    n = len(differences)
    agl_series = [interpolate(at, a["agl_m"], t) for t in grid]
    alt_series = [interpolate(at, a["altitude_m"], t) for t in grid]
    ground = [alt - agl for alt, agl in zip(alt_series, agl_series)]
    return {
        "samples": n,
        "overlap_s": [start, end],
        "p50_abs_m": differences[n // 2] if n else math.inf,
        "p95_abs_m": differences[int(n * 0.95)] if n else math.inf,
        "max_abs_m": differences[-1] if n else math.inf,
        "ground_relief_m": (max(ground) - min(ground)) if ground else 0.0,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AGL parity over real terrain")
    ap.add_argument("--out", default="runs/agl_parity")
    ap.add_argument("--terrain", default="runs/terrain/matterhorn")
    ap.add_argument("--skip-runs", action="store_true")
    args = ap.parse_args(argv)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    terrain = Path(args.terrain).resolve()

    location = LOCATIONS["matterhorn"]
    baked = Heightfield.read(terrain)
    ground = TerrainGround(baked)

    print(f"\n{RULE}\nAGL parity: one raster, both grounds\n{RULE}")
    spec = reference_spec("fly the 747 at 3600 m and 250 kt for 30 seconds")
    spec.set("latitude", location.origin_lat, frm="matterhorn scene origin")
    spec.set("longitude", location.origin_lon, frm="matterhorn scene origin")
    spec.set("heading", 236.0, frm="toward the Matterhorn massif")
    start_elev = ground.elevation_at(location.origin_lat, location.origin_lon)
    spec.set("terrain_elevation", round(start_elev, 1),
             frm="baked raster at the start point")

    card = write_run_card(spec, out / "card.json",
                          collision_terrain=str(terrain))
    print(f"  spec {spec.digest()[:16]}: 30 s over the massif, start ground "
          f"{start_elev:.1f} m")

    headless_path = out / "headless.json"
    unreal_path = out / "unreal.json"
    if not args.skip_runs:
        print("  flying headless with TerrainGround...")
        result = run_spec(spec, terrain_ground=ground)
        result.telemetry.write_json(headless_path)
        print("  flying the UE host with heightfield collision...")
        run_ue(out / "card.json", unreal_path)

    headless = json.loads(headless_path.read_text(encoding="utf-8"))
    unreal = json.loads(unreal_path.read_text(encoding="utf-8"))
    verdict = compare_agl(headless, unreal)

    relief_ok = verdict["ground_relief_m"] >= TOLERANCE["min_ground_relief_m"]
    parity_ok = (verdict["p95_abs_m"] <= TOLERANCE["p95_abs_m"]
                 and verdict["max_abs_m"] <= TOLERANCE["max_abs_m"])
    print(f"\n  ground relief along track: {verdict['ground_relief_m']:.1f} m "
          f"[{'ok' if relief_ok else 'FAIL -- track too flat to prove anything'}]")
    print(f"  |Δ agl| over {verdict['samples']} samples: p50 "
          f"{verdict['p50_abs_m']:.2f} m, p95 {verdict['p95_abs_m']:.2f} m, "
          f"max {verdict['max_abs_m']:.2f} m")
    print(f"  tolerance (stated first): p95 <= {TOLERANCE['p95_abs_m']} m, "
          f"max <= {TOLERANCE['max_abs_m']} m")

    verdict["tolerance"] = TOLERANCE
    verdict["ok"] = bool(parity_ok and relief_ok)
    verdict["consequence"] = (
        "AGL parity holds: the flat-slab label comes off clips whose cards "
        "carry collision_terrain" if verdict["ok"] else
        "AGL parity NOT established: the flat-slab label stays, these "
        "numbers are the published measurement")
    (out / "report.json").write_text(json.dumps(verdict, indent=1), encoding="utf-8")
    print(f"\n  wrote {out / 'report.json'}")
    print(f"\n  AGL PARITY: {'PASS' if verdict['ok'] else 'FAIL'}")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
