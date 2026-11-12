"""Pixel gate for the alpine valley-fog lane. Run on the Windows laptop, from
the repository root in cmd.exe, with the web app up on 127.0.0.1:8008 (the Mac
only unit-tests the arithmetic and the file handling; it never produces a
result). No argument is left to fill in and no environment variable is read:

    python scripts\\run_test_scenarios.py --still --only 11 --spec-dir runs\\alpine_fog\\off
    python swarm\\lanes\\weather_fx\\fog\\alpine\\measure_fog.py keep baseline
    python swarm\\lanes\\weather_fx\\fog\\alpine\\measure_fog.py fog-spec
    python scripts\\run_test_scenarios.py --still --only 11 --spec-dir runs\\alpine_fog\\on
    python swarm\\lanes\\weather_fx\\fog\\alpine\\measure_fog.py keep candidate
    python swarm\\lanes\\weather_fx\\fog\\alpine\\measure_fog.py gate

The A/B is carried by the pinned spec, not by the shell: `fog-spec` copies the
baseline's pinned spec and adds `environment.valley_fog`, so the two runs
differ in that one key. Exit code of `gate`:

    0  pass      both clauses met
    1  fail      measured, and a clause is not met
    2  usage     bad input
    3  blocked   NOT MEASURED: there is no fog frame to judge (the candidate
                 run was refused or failed, or it is the baseline's picture).
                 Until the integrator ships `environment.valley_fog` this is
                 the answer, with the runner's own refusal as the reason.

Measurement. The frame is cut into 32 px blocks. In each block with enough
mid-tone, textured pixels every channel of the fogged frame is fitted against
the same pixels of the fog-free frame: fogged = T * clear + S (least squares,
sRGB decoded). T is the layer's transmittance on that block's rays. Smooth
blocks (sky) cannot be fitted and are left out.

Metric 1  fog_t_abs_error = |T_valley - T_ref|. T_valley is the lower quartile
          of T over the fogged blocks (T <= 0.5); T_ref is the valley-floor
          value from bake_alpine_fog (the engine's FogMaxOpacity floor, 0.08).
          Pass: <= 0.10. With fewer than 4 fogged blocks no fog was drawn and
          the metric is 1 - T_ref.
Metric 2  peak_delta = median over the untouched blocks (T >= 0.9) of the
          mean |fogged - clear| (linear). Pass: <= 0.02, and at least 4 such
          blocks must exist: the layer must leave the high terrain alone,
          which the aerial-perspective lane owns.
Printed, not gated: S / (1 - T), the fog's own colour, per channel.

Known biases, all part of what the Windows run measures: the frames are
tonemapped PNGs (pixels outside 0.02..0.60 linear in the clear frame are
dropped); auto-exposure reacting to the fog scales every block; the two stills
must be the same shot, pixel for pixel, which the pinned spec is there for.
The block size and the texture threshold are choices, not calibrated values.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
SCENARIO = 11
PASS_T_ABS_ERROR = 0.10
PASS_PEAK_DELTA = 0.02
MID_LO, MID_HI = 0.02, 0.60
BLOCK = 32
BLOCK_MIN_PIXELS = 256      # mid-tone pixels a channel needs in a block
BLOCK_MIN_VAR = 2.5e-5      # linear; below this the block has no texture to fit
FOGGED_T, UNTOUCHED_T = 0.5, 0.9
MIN_BLOCKS = 4
EXIT_PASS, EXIT_FAIL, EXIT_USAGE, EXIT_BLOCKED = 0, 1, 2, 3


def _bake():
    spec = importlib.util.spec_from_file_location("alpine_fog_bake", HERE / "bake_alpine_fog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _model() -> dict:
    return json.loads((HERE / "alpine_fog.json").read_text(encoding="utf-8"))["model"]


def valley_fog_key() -> dict:
    """The spec key the gate sets and the integrator must accept, in this shape."""
    model = _model()
    return {"top_m": model["fog_top_m_amsl"], "scale_height_m": model["scale_height_m"]}


def t_ref() -> float:
    """Transmittance from the 5000 m camera to the valley floor. The layer is
    thick enough there that FogMaxOpacity sets it on every ray down to 45 deg."""
    bake, model = _bake(), _model()
    return bake.transmittance(bake.slant_tau(5000.0, model["valley_floor_m_amsl"], 45.0))


def srgb_to_linear(rgb8):
    import numpy as np
    c = rgb8.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def block_fits(clear, fogged, block: int = BLOCK):
    """[(T rgb, S rgb, mean |fogged - clear|)] for every block that can be fitted."""
    import numpy as np
    rows = []
    height, width = clear.shape[:2]
    for y in range(0, height - block + 1, block):
        for x in range(0, width - block + 1, block):
            a = clear[y:y + block, x:x + block, :3].reshape(-1, 3)
            b = fogged[y:y + block, x:x + block, :3].reshape(-1, 3)
            t, s = [], []
            for ch in range(3):
                keep = (a[:, ch] > MID_LO) & (a[:, ch] < MID_HI)
                if int(keep.sum()) < BLOCK_MIN_PIXELS:
                    break
                u, v = a[keep, ch], b[keep, ch]
                var = float(np.var(u))
                if var < BLOCK_MIN_VAR:
                    break
                slope = float(np.mean((u - u.mean()) * (v - v.mean())) / var)
                t.append(slope)
                s.append(float(v.mean() - slope * u.mean()))
            if len(t) == 3:
                rows.append((t, s, float(np.mean(np.abs(b - a)))))
    return rows


def measure(clear, fogged, reference_t: float) -> dict:
    import numpy as np
    rows = block_fits(clear, fogged)
    if len(rows) < 2 * MIN_BLOCKS:
        raise ValueError(f"only {len(rows)} blocks of the baseline have mid-tone texture to fit against")
    t_rgb = np.array([r[0] for r in rows])
    s_rgb = np.array([r[1] for r in rows])
    delta = np.array([r[2] for r in rows])
    t = t_rgb.mean(axis=1)
    fog, untouched = t <= FOGGED_T, t >= UNTOUCHED_T
    fog_detected = int(fog.sum()) >= MIN_BLOCKS
    if fog_detected:
        t_valley = float(np.quantile(t[fog], 0.25))
        t_err = abs(t_valley - reference_t)
        colour = np.median(s_rgb[fog] / (1.0 - t_rgb[fog]), axis=0).tolist()
    else:
        t_valley, t_err, colour = None, 1.0 - reference_t, None
    peak = float(np.median(delta[untouched])) if int(untouched.sum()) >= MIN_BLOCKS else None
    ok = fog_detected and t_err <= PASS_T_ABS_ERROR and peak is not None and peak <= PASS_PEAK_DELTA
    return {
        "status": "pass" if ok else "fail",
        "t_ref": reference_t, "t_valley": t_valley,
        "fog_t_abs_error": t_err, "fog_t_abs_error_without_fog": 1.0 - reference_t,
        "peak_delta": peak,
        "blocks": {"fitted": len(rows), "fogged": int(fog.sum()), "untouched": int(untouched.sum())},
        "fog_detected": fog_detected,
        "fog_colour_linear_rgb": colour,
        "thresholds": {"fog_t_abs_error": PASS_T_ABS_ERROR, "peak_delta": PASS_PEAK_DELTA,
                       "min_blocks": MIN_BLOCKS},
    }


def _work(root: Path) -> Path:
    return root / "runs" / "alpine_fog"


def keep(which: str, root: Path = REPO) -> int:
    """Copy scenario 11's frame of the batch that just ran to runs/alpine_fog/<which>.png,
    straight from its run directory, with the runner's own outcome beside it."""
    work = _work(root)
    work.mkdir(parents=True, exist_ok=True)
    png, side = work / f"{which}.png", work / f"{which}.json"
    png.unlink(missing_ok=True)
    note = {"which": which, "scenario": SCENARIO, "frame": None, "outcome": None, "why": ""}
    summary = root / "runs" / "test_scenarios.json"
    rows = json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else []
    rows = rows if isinstance(rows, list) else rows.get("results", [])
    row = next((r for r in rows if int(r.get("number", -1)) == SCENARIO), None)
    if row is None:
        note["why"] = "runs/test_scenarios.json has no row for scenario 11: the runner did not run it"
    else:
        note.update(outcome=row.get("outcome"), why=str(row.get("why", "")),
                    run_id=row.get("run_id"), spec_sha256=row.get("spec_sha256"))
        if row.get("outcome") == "done" and row.get("run_id"):
            frames = root / "runs" / "webapp" / str(row["run_id"]) / "frames"
            cameras = sorted(d for d in frames.glob("*") if d.is_dir()) if frames.is_dir() else []
            found = sorted(cameras[0].glob("frame_*[0-9].png")) if cameras else []
            if found:
                shutil.copy2(found[0], png)
                note["frame"] = str(found[0])
            else:
                note["why"] = f"run {row['run_id']} is done but left no frame_*.png"
    side.write_text(json.dumps(note, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(note, indent=1, sort_keys=True))
    return EXIT_PASS if note["frame"] else EXIT_BLOCKED


def fog_spec(root: Path = REPO) -> int:
    """runs/alpine_fog/on/11.json = the baseline's pinned spec + environment.valley_fog."""
    source = _work(root) / "off" / f"{SCENARIO:02d}.json"
    if not source.is_file():
        print(f"blocked: {source} is missing, the baseline run pinned no spec", file=sys.stderr)
        return EXIT_BLOCKED
    pinned = json.loads(source.read_text(encoding="utf-8"))
    pinned["spec"].setdefault("environment", {})["valley_fog"] = valley_fog_key()
    target = _work(root) / "on" / f"{SCENARIO:02d}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(pinned, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {target}")
    return EXIT_PASS


def _blocked(reason: str) -> int:
    print(json.dumps({"status": "blocked", "measured": False, "reason": reason}, indent=1))
    return EXIT_BLOCKED


def gate(root: Path = REPO) -> int:
    work = _work(root)
    notes = {}
    for which in ("baseline", "candidate"):
        side = work / f"{which}.json"
        notes[which] = json.loads(side.read_text(encoding="utf-8")) if side.is_file() else {}
        if not (work / f"{which}.png").is_file():
            note = notes[which]
            return _blocked(f"no {which} frame: outcome {note.get('outcome')!r}, "
                            f"{note.get('why') or 'keep ' + which + ' was not run'}")
    on = work / "on" / f"{SCENARIO:02d}.json"
    asked = on.is_file() and "valley_fog" in (
        json.loads(on.read_text(encoding="utf-8"))["spec"].get("environment") or {})
    if not asked:
        return _blocked(f"{on} does not ask for valley_fog: fog-spec did not run before the candidate")
    base, cand = notes["baseline"], notes["candidate"]
    if base.get("run_id") is not None and base.get("run_id") == cand.get("run_id"):
        return _blocked("baseline and candidate are the same run: the candidate batch wrote no new row")
    if (work / "baseline.png").read_bytes() == (work / "candidate.png").read_bytes():
        return _blocked("baseline and candidate are the same picture byte for byte: no valley fog was drawn")

    import numpy as np
    from PIL import Image
    load = lambda path: srgb_to_linear(np.asarray(Image.open(path).convert("RGB")))  # noqa: E731
    clear, fog = load(work / "baseline.png"), load(work / "candidate.png")
    if clear.shape != fog.shape:
        print("the two frames differ in size", file=sys.stderr)
        return EXIT_USAGE
    try:
        result = measure(clear, fog, t_ref())
    except ValueError as exc:
        return _blocked(str(exc))
    result.update(measured=True, baseline_run=base.get("run_id"), candidate_run=cand.get("run_id"))
    print(json.dumps(result, indent=1))
    return EXIT_PASS if result["status"] == "pass" else EXIT_FAIL


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Pixel gate for the alpine valley fog (Windows laptop).")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("keep").add_argument("which", choices=("baseline", "candidate"))
    sub.add_parser("fog-spec")
    sub.add_parser("gate")
    a = p.parse_args(argv)
    if a.command == "keep":
        return keep(a.which)
    return fog_spec() if a.command == "fog-spec" else gate()


if __name__ == "__main__":
    sys.exit(main())
