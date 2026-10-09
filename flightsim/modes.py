"""Linearised modal analysis of a scenario's trim point, against the bands.

    .venv/bin/python -m flightsim.modes examples/cameras_waypoint.yaml [--json out.json] [--category B]

Builds and trims a FRESH FDM from the spec (the same configuration a run
uses: :func:`core.scenario.runner.configure_from_spec`), linearises it
with JSBSim's own ``FGLinearization`` (:mod:`core.fdm.linearize`), checks
the Jacobian independently, names the modes and grades each against the
MIL-F-8785C Level bands for the airframe's class and the flight phase
category (:mod:`core.fdm.modes`), and prints one table. With ``--json``
the full record (matrices, eigenvalues, modes, bands, levels, method,
residual, references) is written as it appears under ``modes`` in a run
manifest.

A refusal is printed by name (``REFUSED -- modes.airframe_class: ...``,
``modes.untrimmed``, ``modes.linearization``, ``modes.residual``,
``trim``, ``spec.read``) and the exit code is 1; otherwise 0. The table
says ``unverified here`` beside the bands because the specification is
not reachable from this container; a level is a statement about the
JSBSim model, not about the aeroplane (docs/VALIDITY.md).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return "inf" if value > 0 else ("-inf" if value < 0 else "nan")
        return f"{value:.{digits}f}"
    return str(value)


def _mode_row(name: str, mode: Dict[str, Any], level: Dict[str, Any]) -> str:
    if mode.get("oscillatory"):
        wn, zeta, period = mode["omega_n_rad_s"], mode["zeta"], mode["period_s"]
        tau = mode.get("time_to_half_s", mode.get("time_to_double_s"))
        tau_label = "T1/2" if "time_to_half_s" in mode else "T2"
    else:
        wn, zeta, period = None, None, None
        if "time_constant_s" in mode:
            tau, tau_label = mode["time_constant_s"], "tau"
        elif "time_to_double_s" in mode:
            tau, tau_label = mode["time_to_double_s"], "T2"
        else:
            tau, tau_label = None, "-"
    lvl = level.get("level")
    return (f"  {name:<14}{_fmt(wn):>10}{_fmt(zeta):>8}{_fmt(period, 2):>10}"
            f"{(_fmt(tau, 2) + ' ' + tau_label):>14}{str(lvl if lvl is not None else '-'):>8}")


def render_table(record: Dict[str, Any]) -> str:
    """The printed table for one modes record (ASCII only)."""
    trim = record["trim"]
    lines = [
        f"modes: {record['aircraft']} (class {record['airframe_class']}, category "
        f"{record['flight_phase_category']}) at {trim['altitude_m']:.0f} m, "
        f"{trim['vt_mps']:.1f} m/s TAS, alpha {math.degrees(trim['alpha_rad']):.2f} deg; "
        f"method {record['linearization']['method']}",
        f"  {'mode':<14}{'wn rad/s':>10}{'zeta':>8}{'period s':>10}{'time s':>14}{'level':>8}",
    ]
    modes, levels = record["modes"], record["levels"]
    lines.append(_mode_row("short period", modes["short_period"], levels["short_period_damping"]))
    lines.append(_mode_row("phugoid", modes["phugoid"], levels["phugoid"]))
    lines.append(_mode_row("dutch roll", modes["dutch_roll"], levels["dutch_roll"]))
    lines.append(_mode_row("roll", modes["roll"], levels["roll"]))
    lines.append(_mode_row("spiral", modes["spiral"], levels["spiral"]))
    spf = levels.get("short_period_frequency", {})
    if spf.get("value", {}).get("cap") is not None:
        lines.append(f"  short-period CAP {spf['value']['cap']:.3f} 1/s^2/g "
                     f"(n/alpha {record['n_alpha_g_per_rad']:.2f} g/rad) level "
                     f"{spf.get('level')} [{spf.get('confidence')}]")
    res = record["linearization"]["residual"]
    rng = record["linearization"]["linear_range"]
    lines.append(f"  residual at step {res['step']:g}: longitudinal {res['longitudinal']:.2e}, "
                 f"lateral {res['lateral']:.2e} (bound {res['bound']:g}) "
                 f"{'ok' if res['ok'] else 'NOT OK'}; linear range at {rng['step']:g}: "
                 f"{rng['longitudinal']:.2e} / {rng['lateral']:.2e}")
    lines.append(f"  overall level {record['overall_level']}; bands {record['bands']['verification']}")
    lines.append("  a level describes the JSBSim model, not the aeroplane (no validated data)")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="linearise a scenario's trim point and grade its modes")
    parser.add_argument("spec", help="scenario spec YAML")
    parser.add_argument("--json", default=None, metavar="OUT",
                        help="write the full modes record here")
    parser.add_argument("--category", default="B", choices=("A", "B", "C"),
                        help="MIL-F-8785C flight phase category (default B: cruise)")
    args = parser.parse_args(argv)

    from core.fdm.errors import TrimError
    from core.fdm.linearize import ModesError
    from core.fdm.modes import analyse_spec
    from core.scenario.spec import ScenarioSpec

    try:
        spec = ScenarioSpec.read(args.spec)
    except Exception as exc:  # noqa: BLE001 -- the reason is printed by name
        print(f"REFUSED -- spec.read: {args.spec}: {exc}")
        return 1
    try:
        result = analyse_spec(spec, category=args.category)
    except ModesError as exc:
        print(f"REFUSED -- {exc.constraint}: {exc.message}")
        return 1
    except TrimError as exc:
        print(f"REFUSED -- trim: {exc}")
        return 1

    record = result.to_dict()
    print(render_table(record))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(record, indent=1), encoding="utf-8")
        print(f"  recorded: {out}")
    return 1 if record["refusals"] else 0


if __name__ == "__main__":
    sys.exit(main())
