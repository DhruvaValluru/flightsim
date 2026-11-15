"""The coastal physical-light-units pixel gate: one command, no hand-typed
numbers. Run on the Windows laptop in the repo root (never on the Mac for a
result; the Mac only unit-tests it on synthetic frames and sidecars).

    .\\.venv\\Scripts\\python.exe swarm\\lanes\\lighting_exposure\\physical_light_units\\coastal\\coastal_gate.py ^
        --baseline-step <stepA> --candidate-step <stepB> --shot <key>

It reads what the repo's own sheet runner wrote for two steps of the SAME
shot (experiments/visual_contact_sheet.py, write_shots and main):

    runs/visual/<step>/shots.json   {"shots": {<key>: {"run_dir": ..., "refused"|"failed": ...}}}
    runs/visual/<step>/<key>.png    the frame
    <run_dir>/beauty_look.json      the sidecar the render read (core/scene/beauty_look.py
                                    plan_beauty_look: "sun_elevation_deg", "exposure")

and takes every number from the two sidecars. It REFUSES by name (exit 2)
instead of guessing when:

  shots.missing / shot.missing / shot.refused / shot.failed / frame.missing
  sidecar.missing            no beauty_look.json under the run_dir (a measure-quality run)
  exposure.ev100_null        the sidecar's exposure.ev100 is null. beauty_look.py writes
                             null when the sun is at or below the horizon, and on the
                             physical-sky path when the -sky= plan handed over no EV100;
                             the host's own exposure then stands and there is no number
                             to gate against.
  sun.mismatch               the two runs' sun elevations differ by more than 0.05 deg
  candidate.not_coastal_base the candidate sidecar's exposure.basis does not name the
                             coastal table: the integrator's change did not run for this
                             shot (not merged, or the shot is not a coastal one). The four
                             fixed sheet shots a b c d are inland and always land here.
  exposure.unchanged         baseline and candidate EV100 are equal: nothing to measure
  exposure.shift_below_gate  the two EV100s differ by 0.3 stop or less: a frame that did
                             not move would pass the 0.3 tolerance, so nothing is proved.
                             The nominal coastal row (sun 12 deg, 15 km) is such a case:
                             table 12.83 against the band's 13.0.

Checks (exit 0 all pass, 1 any fail):
  table_base_error_ev      candidate exposure.base_ev100 minus the table's target_ev100
                           at the sidecar's sun elevation. Pass: |error| <= 0.01.
                           A sidecar check, not a pixel check.
  ev_error_stops           measure_exposure.measure with expected shift = baseline
                           exposure.ev100 - candidate exposure.ev100 (the full targets,
                           so the deck, grade and brightness terms cancel only if they
                           are equal in both runs, which the same shot guarantees).
                           Pass: |error| <= 0.3.
  highlight_clip_fraction  as measure_exposure.

Known limit, not resolved here: the sidecar's exposure.meter block says the
host re-meters the beauty frame once (90th-percentile luma) "only when the
host finds Lumen GI unsupported on its shader platform". The D3D11 laptop
has no Lumen, so the host may move AutoExposureBias away from the sidecar's
EV100 there; ev_error_stops would then report that movement as error. Whether
it does is UNMEASURED.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

from PIL import Image

LANE = Path(__file__).resolve().parent
REPO = LANE.parents[3]
VISUAL_ROOT = REPO / "runs" / "visual"
COASTAL_BASIS_WORD = "coastal"
TABLE_BASE_TOL_EV = 0.01
SUN_TOL_DEG = 0.05


class Refused(Exception):
    pass


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"coastal_plu_{name}", LANE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_step(root: Path, step: str, shot: str) -> Tuple[Path, Dict[str, Any]]:
    """(frame, beauty_look sidecar) of one shot of one step, or Refused."""
    directory = Path(root) / step
    shots_path = directory / "shots.json"
    try:
        rows = json.loads(shots_path.read_text(encoding="utf-8")).get("shots", {})
    except (OSError, ValueError) as exc:
        raise Refused(f"shots.missing: {shots_path} ({exc.__class__.__name__})")
    row = rows.get(shot)
    if row is None:
        raise Refused(f"shot.missing: step {step} has no shot {shot!r} (has {sorted(rows)})")
    for key in ("refused", "failed"):
        if row.get(key):
            raise Refused(f"shot.{key}: step {step} shot {shot}: {row[key]}")
    frame = directory / f"{shot}.png"
    if not frame.is_file():
        raise Refused(f"frame.missing: {frame}")
    run_dir = Path(str(row.get("run_dir") or ""))
    sidecar = run_dir / "beauty_look.json"
    if not row.get("run_dir") or not sidecar.is_file():
        found = sorted(run_dir.rglob("beauty_look.json")) if row.get("run_dir") and run_dir.is_dir() else []
        if not found:
            raise Refused(f"sidecar.missing: no beauty_look.json under {run_dir} "
                          f"(step {step}; a measure-quality run writes none)")
        sidecar = found[0]
    return frame, json.loads(sidecar.read_text(encoding="utf-8"))


def exposure_of(step: str, look: Dict[str, Any]) -> Dict[str, Any]:
    exposure = look.get("exposure") or {}
    if exposure.get("ev100") is None:
        raise Refused(f"exposure.ev100_null: step {step}: {exposure.get('basis', 'no exposure block')}")
    return exposure


def gate(root: Path, baseline_step: str, candidate_step: str, shot: str,
         visibility_km: float) -> Dict[str, Any]:
    base_frame, base_look = read_step(root, baseline_step, shot)
    cand_frame, cand_look = read_step(root, candidate_step, shot)
    base_exp = exposure_of(baseline_step, base_look)
    cand_exp = exposure_of(candidate_step, cand_look)
    sun_base, sun_cand = float(base_look["sun_elevation_deg"]), float(cand_look["sun_elevation_deg"])
    if abs(sun_base - sun_cand) > SUN_TOL_DEG:
        raise Refused(f"sun.mismatch: baseline sun {sun_base:g} deg, candidate {sun_cand:g} deg")
    basis = str(cand_exp.get("basis") or "")
    if COASTAL_BASIS_WORD not in basis.lower():
        raise Refused("candidate.not_coastal_base: the candidate's exposure.basis is "
                      f"{basis!r}; the coastal table did not set this shot's base EV100")
    base_ev, cand_ev = float(base_exp["ev100"]), float(cand_exp["ev100"])
    if abs(base_ev - cand_ev) < 1e-6:
        raise Refused(f"exposure.unchanged: both runs are at EV100 {base_ev:g}")
    measure = _load("measure_exposure")
    if abs(base_ev - cand_ev) <= measure.GATE_EV:
        raise Refused(f"exposure.shift_below_gate: the expected shift is {base_ev - cand_ev:+.3f} "
                      f"stops, inside the {measure.GATE_EV:g} stop tolerance, so a frame whose "
                      "exposure did not move at all would pass; render the shot at a sun "
                      "elevation where the table and the baseline differ by more")

    table_ev = measure.table_target_ev100(sun_cand, visibility_km)
    table_error = float(cand_exp["base_ev100"]) - table_ev
    pixels = measure.measure(Image.open(base_frame), Image.open(cand_frame), base_ev, cand_ev)
    if "refused" in pixels:
        raise Refused(f"pixels.too_few_midtones: {pixels['refused']}")
    pixels.pop("target_ev100", None)
    table_ok = abs(table_error) <= TABLE_BASE_TOL_EV
    return {
        "shot": shot, "baseline_step": baseline_step, "candidate_step": candidate_step,
        "sun_elevation_deg": sun_cand, "visibility_km": visibility_km,
        "baseline_ev100": base_ev, "candidate_ev100": cand_ev,
        "candidate_base_ev100": float(cand_exp["base_ev100"]),
        "candidate_basis": basis,
        "table_target_ev100": round(table_ev, 4),
        "table_base_error_ev": round(table_error, 4),
        "table_base_pass": bool(table_ok),
        **pixels,
        "pass": bool(table_ok and pixels["pass"]),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--baseline-step", required=True)
    parser.add_argument("--candidate-step", required=True)
    parser.add_argument("--shot", required=True, help="the shot key both steps rendered")
    parser.add_argument("--visibility-km", type=float, default=15.0,
                        help="the sea-haze visibility the integrator's lookup used (default 15)")
    parser.add_argument("--root", type=Path, default=VISUAL_ROOT, help="runs/visual")
    args = parser.parse_args(argv)
    try:
        result = gate(args.root, args.baseline_step, args.candidate_step, args.shot,
                      args.visibility_km)
    except Refused as exc:
        print(f"REFUSED {exc}")
        return 2
    print(json.dumps(result, indent=1))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
