"""Gate 3b -- the three-rate convergence study: Richardson's observed order
per system response quantity, written where core/uncertainty.py reads it.

Row V9 (docs/vva/VV_REPORT.md) measured the branch's convergence once, on
the altitude of a B747 flight (0.098 m at 1/60 vs 1/120 s, 0.048 m at 1/120
vs 1/240 s, p = 1.03), and core/uncertainty.py has since ASSUMED p = 1 with
the two-rate safety factor Fs = 3 for every run's dt/2 twin. This study
flies the deterministic variant of the committed c172p example
(examples/cameras_waypoint.yaml: 1200 m, 100 kt CAS, open loop; turbulence
off, as core.uncertainty.twin_spec makes every twin) at 60, 120 and 240 Hz
through :func:`core.uncertainty.three_rate_study` and records, per SRQ
(altitude, north, east, TAS, pitch, roll, heading), the two peak
differences e_21 (60 vs 120) and e_32 (120 vs 240) and the observed order
p = ln(e_21 / e_32) / ln 2 (Roache 1994).

The study is written to ``data/convergence/gate3b_convergence.json``
(:data:`core.uncertainty.CONVERGENCE_STUDY_PATH`, committed, ASCII) with
``applies_to`` = the aircraft file's sha256, the JSBSim version and the
three rates. :func:`core.uncertainty.u_num_twin` reads it when present and
when the run IS that case (the same aircraft file on the same JSBSim, at
one of the study's first two rates, so the twin's pair lies inside the
studied range): the observed order, capped at the formal order of JSBSim's
default integrators (1: rotational rate and attitude by rectangular Euler,
read from the property tree), with Fs = 1.25. A run that is not the case
keeps p = 1, Fs = 3. The manifest (the existing experiments' form,
``core.experiments.manifest.RunManifest``) goes to
``runs/gate3b/convergence_manifest.json``.

NOT claimed: the order of another airframe, another condition or a
turbulent run; the asymptotic range (three rates are the minimum; an SRQ
whose differences are zero or not decreasing gets no order and keeps the
assumed one); anything about the model's fidelity (this is solution
verification, the integrator against itself).

Usage: ``.venv/bin/python -m experiments.gate3b_convergence [--seconds 10]
[--study PATH] [--out DIR]``
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.experiments.manifest import RunManifest, sha256_file  # noqa: E402
from core.uncertainty import (  # noqa: E402
    CONVERGENCE_STUDY_PATH, FORMAL_ORDER, SRQS, SRQ_UNITS, three_rate_study,
)

EXPERIMENT = "gate3b-convergence"
EXAMPLE = REPO / "examples" / "cameras_waypoint.yaml"
RATES_HZ = (60.0, 120.0, 240.0)
STUDY_VERSION = 1


def study_spec(seconds: float):
    """The committed example at the study's coarse rate for ``seconds``."""
    from core.scenario.spec import ScenarioSpec

    spec = ScenarioSpec.read(EXAMPLE)
    spec.set("duration", float(seconds), frm="gate3b convergence study: the flight's length")
    spec.set("rate", RATES_HZ[0], frm="gate3b convergence study: the coarse rate (dt, dt/2, dt/4)")
    return spec


def quiet_run(spec):
    from core.scenario.runner import run_spec

    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


def study_document(study: Mapping[str, Any], base_manifest: Mapping[str, Any],
                   seconds: float) -> Dict[str, Any]:
    """The file core/uncertainty.py reads: the orders, what they apply to,
    and every difference they came from."""
    fdm = base_manifest.get("fdm") or {}
    aircraft = fdm.get("aircraft") or {}
    srqs: Dict[str, Any] = {}
    for srq in SRQS:
        detail = dict(study["detail"].get(srq) or {})
        p = detail.get("p")
        detail["unit"] = SRQ_UNITS[srq]
        if p is None:
            detail["used_by_u_num"] = None
            detail["basis"] = ("no order: a difference is zero or absent, so u_num keeps the "
                               "assumed p = 1 with Fs = 3")
        elif not math.isfinite(p) or p <= 0.0:
            detail["used_by_u_num"] = None
            detail["basis"] = ("no order: the differences do not decrease with the step (outside "
                               "the asymptotic range); u_num keeps the assumed p = 1 with Fs = 3")
        else:
            detail["used_by_u_num"] = min(float(p), FORMAL_ORDER)
            detail["basis"] = (f"observed p = {p:.4g}, used as min(p, {FORMAL_ORDER:g}) with "
                               f"Fs = 1.25 (an observed order above the formal one is not trusted)")
        srqs[srq] = detail
    return {
        "study_version": STUDY_VERSION,
        "kind": "three_rate_study",
        "experiment": EXPERIMENT,
        "scenario": {"spec": str(EXAMPLE.relative_to(REPO)).replace("\\", "/"),
                     "spec_sha256": sha256_file(EXAMPLE), "duration_s": float(seconds),
                     "turbulence": "none", "hold_state": False},
        "applies_to": {"aircraft": aircraft.get("name"), "aircraft_sha256": aircraft.get("sha256"),
                       "jsbsim_version": fdm.get("jsbsim_version"),
                       "rates_hz": [float(r) for r in study["rates_hz"]],
                       "rule": ("a run of this aircraft file on this JSBSim at one of the first two "
                                "rates: its dt/2 twin's pair then lies inside the studied range")},
        "observed_p": {k: float(v) for k, v in study["observed_p"].items()
                       if math.isfinite(v) and v > 0.0},
        "formal_order": FORMAL_ORDER,
        "srqs": srqs,
        "digests": list(study["digests"]),
        "reference": "Roache 1994 (GCI, observed order); ASME V&V 20-2009 [unverified here]",
        "not_claimed": [
            "the order of another airframe, condition or a turbulent run",
            "the asymptotic range beyond three rates",
            "the model's fidelity: this is the integrator against itself",
        ],
    }


def run_study(seconds: float, runner: Optional[Callable[[Any], Any]] = None) -> Dict[str, Any]:
    flown: List[Any] = []
    base = runner if runner is not None else quiet_run

    def capture(spec):
        result = base(spec)
        flown.append(result)
        return result

    study = three_rate_study(study_spec(seconds), runner=capture)
    return study_document(study, flown[0].manifest, seconds)


def write_study(document: Mapping[str, Any], path: Path) -> Path:
    """ASCII JSON, sorted keys, one trailing newline (a committed file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="utf-8")
    return path


def build_manifest(document: Mapping[str, Any], study_path: Path) -> RunManifest:
    manifest = RunManifest(name=EXPERIMENT)
    manifest.parameters = {"rates_hz": list(RATES_HZ), "duration_s": document["scenario"]["duration_s"],
                           "srqs": list(SRQS), "formal_order": FORMAL_ORDER,
                           "turbulence": "none"}
    manifest.seeds = {"derivation": "turbulence off in all three flights: no stochastic stream"}
    manifest.components = {"study": "core.uncertainty.three_rate_study",
                           "runner": "core.scenario.runner.run_spec (closure not asserted)"}
    manifest.add_input("spec", EXAMPLE)
    manifest.add_output("study", study_path)
    manifest.notes = [f"{srq}: p = {d.get('p')}" for srq, d in document["srqs"].items()]
    return manifest


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 3b: the three-rate convergence study")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--study", default=str(CONVERGENCE_STUDY_PATH))
    ap.add_argument("--out", default=str(REPO / "runs" / "gate3b"))
    args = ap.parse_args(argv)
    document = run_study(args.seconds)
    study_path = write_study(document, Path(args.study))
    manifest_path = build_manifest(document, study_path).write(
        Path(args.out) / "convergence_manifest.json")
    print("GATE 3b -- three-rate convergence (60 / 120 / 240 Hz, turbulence off)")
    for srq, d in document["srqs"].items():
        p = d.get("p")
        print(f"  {srq:12s} e21 {d.get('e_coarse_mid', float('nan')):.4e}  "
              f"e32 {d.get('e_mid_fine', float('nan')):.4e}  "
              f"p {'-' if p is None else f'{p:.3f}'}  used {d.get('used_by_u_num')}")
    print(f"  study {study_path} sha256 {sha256_file(study_path)}")
    print(f"  manifest {manifest_path} sha256 {sha256_file(manifest_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
