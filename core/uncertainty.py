"""Per-run uncertainty in the ASME V&V 20 form (ADVANCEMENTS_BLUEPRINT
section 2, R1): u_num from a dt/2 twin, u_input by GUM propagation, u_val
per system response quantity, u_D absent per run.

**u_num** (:func:`u_num_twin`). The run is flown again at twice the
integration rate with turbulence off (the dt/2 TWIN: a stochastic
process re-seeded at another rate is a different draw, not a refined
solution), and for each SRQ the peak absolute difference between the
two recordings on the coarse run's sample times is the Richardson
error estimate e = |S_dt - S_dt/2| / (2^p - 1), reported as the GCI
u_num = Fs x e (Roache 1994, "Perspective: a method for uniform
reporting of grid refinement studies", J. Fluids Eng. 116(3); ASME V&V
20-2009's solution-verification section [unverified here]). With no
three-rate study the order is ASSUMED p = 1 (V9 observed 1.03 on this
branch) with the two-rate safety factor Fs = 3; when
:func:`three_rate_study` ran, its observed p per SRQ is used with
Fs = 1.25. Which one applies is stated in every ``basis``. With no
order handed in, the committed study (``data/convergence/
gate3b_convergence.json``, experiments/gate3b_convergence.py) supplies
it when the run is that study's case (:func:`study_observed_p`: the same
aircraft file and JSBSim, one of its first two rates), capped at the
integrators' formal order 1; any other run keeps the assumption.

**u_input** (:func:`u_x`, :func:`u_input_for`). GUM JCGM 100:2008 eq. 10,
first order: u_input(SRQ) = |c_i| u_x with c_i the sensitivity of the
SRQ to the variable. u_x by the spec's provenance source rank: ``user``
0 unless a tolerance is stated with the value (the user said so
exactly); ``inferred`` (b/2)/sqrt(3) for a vocabulary bin of width b
(a uniform distribution across the bin, GUM 4.3.7), b from the
registry; ``sampled`` 0 (the draw IS the value; its distribution is the
campaign's, not the run's); ``model``/``default`` the registry's
declared spread. The sensitivity is measured by a CENTRAL +-u_x pair
(:func:`central_sensitivity`), run only when u_x is non-zero; the
SRQ compared is its value at the final common sample.

**u_val** per SRQ = sqrt(u_num^2 + sum_i u_input_i^2); ``u_D`` is
absent because no referent is added by this area, so the block is
a statement of the run's own uncertainty, NOT a validation.

The runner is injectable (``runner(spec) -> RunResult``); the default
is :func:`core.scenario.runner.run_spec` with closure not asserted.

NOT claimed: u_num is from one dt/2 twin on a deterministic variant with
an assumed order unless the three-rate study ran; the twin's SRQ
differences are interpolated onto the coarse sample times (the
recorder's sample count differs by one between rates, measured: 11 vs
10 samples in 1 s at 120 and 240 Hz). u_input is first-order and the
central pair is a secant, not a derivative. The north/east SRQs are
derived from the recorded latitude/longitude by the WGS 84 radii at
the first sample. Nothing here validates the model.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .registry import REGISTRY, Registry, VariableRecord

#: The system response quantities u_num is reported for.
SRQS = ("altitude_m", "north_m", "east_m", "tas_kt", "pitch_deg", "roll_deg", "heading_deg")
SRQ_UNITS = {"altitude_m": "m", "north_m": "m", "east_m": "m", "tas_kt": "kt",
             "pitch_deg": "deg", "roll_deg": "deg", "heading_deg": "deg"}

#: Roache 1994: the safety factor for a two-grid (here two-rate) estimate
#: with an assumed order, and for a three-grid estimate with an observed one.
FS_TWO_RATE = 3.0
FS_THREE_RATE = 1.25
#: The order assumed when no three-rate study ran (V9 observed 1.03).
ASSUMED_ORDER = 1.0
#: The refinement ratio: the twin runs at twice the rate.
REFINEMENT_RATIO = 2.0
#: P8: the committed three-rate study (experiments/gate3b_convergence.py
#: writes it), read by :func:`study_observed_p` when a run IS its case.
CONVERGENCE_STUDY_PATH = Path(__file__).resolve().parents[1] / "data" / "convergence" / "gate3b_convergence.json"
#: The formal order of JSBSim 1.2.4's default integrators, read from the
#: property tree on the c172p: rotational rate and attitude by rectangular
#: Euler (``simulation/integrator/rate/rotational`` and
#: ``position/rotational`` = 1), translational rate Adams-Bashforth 2 (3),
#: position Adams-Bashforth 3 (4) -- the coupled system is first order. The
#: committed study's observed order is used up to it (Roache: an observed
#: order above the formal one is not trusted).
FORMAL_ORDER = 1.0

FORM = "ASME V&V 20; u_D absent per run"

#: WGS 84 (for the north/east metres from the recorded lat/lon).
_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)


def _wgs84_radii(lat_deg: float) -> Tuple[float, float]:
    """(meridional, prime-vertical) radii of curvature in metres."""
    s = math.sin(math.radians(lat_deg))
    w = math.sqrt(1.0 - _WGS84_E2 * s * s)
    return _WGS84_A * (1.0 - _WGS84_E2) / (w ** 3), _WGS84_A / w


def srq_series(columns: Mapping[str, Sequence[float]]) -> Dict[str, Any]:
    """Each SRQ as a numpy array over the recording: the recorded column
    where one exists; ``north_m``/``east_m`` from ``lat_deg``/``lon_deg``
    relative to the first sample by the WGS 84 radii there; ``heading_deg``
    unwrapped so a crossing of 360 is not a 360 deg difference. An SRQ
    whose source column is absent is left out (stated by the caller)."""
    import numpy as np

    out: Dict[str, Any] = {}
    for name in ("altitude_m", "tas_kt", "pitch_deg", "roll_deg"):
        if name in columns:
            out[name] = np.asarray(columns[name], dtype=float)
    if "heading_deg" in columns:
        out["heading_deg"] = np.degrees(np.unwrap(np.radians(np.asarray(columns["heading_deg"], dtype=float))))
    if "lat_deg" in columns and "lon_deg" in columns and len(columns["lat_deg"]):
        lat = np.asarray(columns["lat_deg"], dtype=float)
        lon = np.asarray(columns["lon_deg"], dtype=float)
        r_m, r_n = _wgs84_radii(float(lat[0]))
        out["north_m"] = np.radians(lat - lat[0]) * r_m
        out["east_m"] = np.radians(lon - lon[0]) * r_n * math.cos(math.radians(float(lat[0])))
    return out


def richardson(difference: float, p: float, fs: float,
               ratio: float = REFINEMENT_RATIO) -> Dict[str, float]:
    """e = |S_dt - S_dt/2| / (r^p - 1); GCI = Fs x e."""
    if p <= 0.0:
        raise ValueError(f"the order p must be positive, not {p}")
    e = abs(float(difference)) / (ratio ** p - 1.0)
    return {"error_estimate": e, "gci": fs * e}


def observed_order(e_coarse_mid: float, e_mid_fine: float,
                   ratio: float = REFINEMENT_RATIO) -> float:
    """p = ln(e_21 / e_32) / ln r from a three-rate study (Roache 1994)."""
    if e_mid_fine <= 0.0 or e_coarse_mid <= 0.0:
        raise ValueError("an observed order needs two positive differences")
    return math.log(e_coarse_mid / e_mid_fine) / math.log(ratio)


def twin_spec(spec, factor: float = REFINEMENT_RATIO, turbulence_off: bool = True):
    """The dt/2 twin: the same spec at ``factor`` x the rate, turbulence
    off (stated in the twin's provenance text)."""
    from .scenario.spec import ScenarioSpec

    twin = ScenarioSpec.from_dict(spec.to_dict())
    twin.set("rate", float(spec.rate.value) * factor,
             frm=f"dt/{factor:g} twin of the run for u_num (rate x {factor:g})")
    if turbulence_off:
        twin.set("turbulence", "none", frm="dt/2 twin: turbulence off (a stochastic "
                                           "process re-seeded at another rate is a "
                                           "different draw, not a refined solution)")
    return twin


def _default_runner() -> Callable[[Any], Any]:
    from .scenario.runner import run_spec

    return lambda spec: run_spec(spec, assert_closure=False)


def _peak_difference(coarse_t, coarse, fine_t, fine) -> Tuple[float, int]:
    """Peak |coarse - fine| with the fine series interpolated onto the
    coarse sample times (the two recorders do not sample at the same
    instants); the comparison stops at the last common time. Both clocks
    are taken from their own first sample (the trimmed state): a piston
    engine's crank ends on a rate-dependent step, so JSBSim's clock at the
    first sample differs between rates (P8, the c172p example: 4.933 /
    4.900 / 4.879 s at 60 / 120 / 240 Hz) and a comparison on the raw
    clock measured that phase shift -- 25 x the altitude difference on
    the elapsed time -- instead of the integration error."""
    import numpy as np

    coarse_t = coarse_t - coarse_t[0]
    fine_t = fine_t - fine_t[0]
    t_end = min(float(coarse_t[-1]), float(fine_t[-1]))
    keep = coarse_t <= t_end + 1e-9
    fine_on_coarse = np.interp(coarse_t[keep], fine_t, fine)
    d = np.abs(coarse[keep] - fine_on_coarse)
    k = int(np.argmax(d))
    return float(d[k]), int(np.sum(keep))


def study_observed_p(base, spec, path=None) -> Optional[Dict[str, Any]]:
    """The committed three-rate study's orders when it applies to this run
    (P8): the same aircraft file (sha256) on the same JSBSim version, the
    run's rate one of the study's first two rates (so the dt/2 twin's pair
    lies inside the studied range). Each positive finite order is capped
    at :data:`FORMAL_ORDER`. None when the file is absent or unreadable,
    the base run carries no manifest (a fake runner), or the run is not
    the study's case -- u_num then keeps the assumed order."""
    target = Path(path) if path is not None else CONVERGENCE_STUDY_PATH
    manifest = getattr(base, "manifest", None)
    if not target.is_file() or not isinstance(manifest, Mapping):
        return None
    try:
        raw = target.read_bytes()
        study = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    applies = study.get("applies_to") if isinstance(study, Mapping) else None
    fdm = manifest.get("fdm") if isinstance(manifest.get("fdm"), Mapping) else {}
    if not isinstance(applies, Mapping):
        return None
    try:
        rates = [float(r) for r in applies.get("rates_hz") or ()]
        rate = float(spec.rate.value)
    except (TypeError, ValueError, AttributeError):
        return None
    if (len(rates) != 3 or rate not in rates[:2]
            or (fdm.get("aircraft") or {}).get("sha256") != applies.get("aircraft_sha256")
            or fdm.get("jsbsim_version") != applies.get("jsbsim_version")):
        return None
    orders = {srq: min(float(p), FORMAL_ORDER)
              for srq, p in (study.get("observed_p") or {}).items()
              if srq in SRQS and isinstance(p, (int, float)) and not isinstance(p, bool)
              and math.isfinite(float(p)) and float(p) > 0.0}
    if not orders:
        return None
    return {"observed_p": orders, "path": target.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "rates_hz": rates, "formal_order": FORMAL_ORDER}


def u_num_twin(spec, runner: Optional[Callable[[Any], Any]] = None,
               observed_p: Optional[Mapping[str, float]] = None,
               base_result=None, study_path=None) -> Dict[str, Any]:
    """u_num per SRQ from the dt/2 twin. ``observed_p`` (from
    :func:`three_rate_study`) switches the estimate to the observed order
    with Fs = 1.25; otherwise the committed study (:func:`study_observed_p`,
    ``study_path`` to point elsewhere) does when the run is its case, and
    otherwise p = 1 is assumed with Fs = 3. ``base_result`` reuses an
    already-flown base run; the twin is always flown here."""
    import numpy as np

    run = runner if runner is not None else _default_runner()
    t0 = time.perf_counter()
    base = base_result if base_result is not None else run(spec)
    study = None
    if observed_p is None:
        study = study_observed_p(base, spec, path=study_path)
        if study is not None:
            observed_p = study["observed_p"]
    twin = twin_spec(spec)
    fine = run(twin)
    elapsed = time.perf_counter() - t0
    base_srq = srq_series(base.telemetry.columns)
    fine_srq = srq_series(fine.telemetry.columns)
    coarse_t = np.asarray(base.telemetry.columns["t"], dtype=float)
    fine_t = np.asarray(fine.telemetry.columns["t"], dtype=float)
    dt = 1.0 / float(spec.rate.value)
    per_srq: Dict[str, Any] = {}
    for srq in SRQS:
        if srq not in base_srq or srq not in fine_srq:
            per_srq[srq] = {"value": None, "unit": SRQ_UNITS[srq],
                            "basis": "NOT RUN: the recording carries no column for this SRQ"}
            continue
        diff, n = _peak_difference(coarse_t, base_srq[srq], fine_t, fine_srq[srq])
        if observed_p is not None and srq in observed_p:
            p, fs, order_basis = float(observed_p[srq]), FS_THREE_RATE, "observed from the three-rate study"
            if study is not None:
                order_basis += (f" {study['path']} (sha256 {study['sha256'][:12]}), capped at the "
                                f"formal order {FORMAL_ORDER:g}")
        else:
            p, fs, order_basis = ASSUMED_ORDER, FS_TWO_RATE, "assumed (no three-rate study; V9 observed 1.03)"
        est = richardson(diff, p, fs)
        per_srq[srq] = {
            "value": est["gci"], "unit": SRQ_UNITS[srq], "difference": diff,
            "error_estimate": est["error_estimate"], "p": p, "fs": fs,
            "coarse_dt_s": dt, "fine_dt_s": dt / REFINEMENT_RATIO, "samples_compared": n,
            "basis": (f"GCI = Fs x |S_dt - S_dt/2| / (2^p - 1), Fs = {fs:g}, p = {p:g} "
                      f"({order_basis}); peak over {n} coarse samples with the twin "
                      f"interpolated onto them; turbulence off in both"),
        }
    return {
        "srq": per_srq,
        "twin": {"spec_digest": fine.spec_digest, "output_digest": fine.output_digest,
                 "rate_hz": float(twin.rate.value), "turbulence": str(twin.turbulence.value)},
        "base": {"spec_digest": base.spec_digest, "output_digest": base.output_digest,
                 "rate_hz": float(spec.rate.value)},
        "order_source": (study if study is not None else
                         "given" if observed_p is not None else "assumed"),
        "elapsed_s": elapsed,
        "reference": "Roache 1994 (GCI); ASME V&V 20-2009 solution verification [unverified here]",
    }


def three_rate_study(spec, runner: Optional[Callable[[Any], Any]] = None) -> Dict[str, Any]:
    """dt, dt/2, dt/4 with turbulence off: the observed order per SRQ,
    for :func:`u_num_twin`'s ``observed_p``. An SRQ whose differences
    are not both positive gets no order (stated)."""
    import numpy as np

    run = runner if runner is not None else _default_runner()
    base = twin_spec(spec, factor=1.0)
    mid = twin_spec(spec, factor=2.0)
    fine = twin_spec(spec, factor=4.0)
    results = [run(s) for s in (base, mid, fine)]
    series = [srq_series(r.telemetry.columns) for r in results]
    times = [np.asarray(r.telemetry.columns["t"], dtype=float) for r in results]
    orders: Dict[str, Optional[float]] = {}
    detail: Dict[str, Any] = {}
    for srq in SRQS:
        if any(srq not in s for s in series):
            orders[srq] = None
            detail[srq] = {"basis": "NOT RUN: column absent"}
            continue
        e21, _ = _peak_difference(times[0], series[0][srq], times[1], series[1][srq])
        e32, _ = _peak_difference(times[1], series[1][srq], times[2], series[2][srq])
        try:
            p = observed_order(e21, e32)
        except ValueError:
            p = None
        orders[srq] = p
        detail[srq] = {"e_coarse_mid": e21, "e_mid_fine": e32, "p": p}
    return {"observed_p": {k: v for k, v in orders.items() if v is not None},
            "detail": detail,
            "digests": [r.output_digest for r in results],
            "rates_hz": [float(s.rate.value) for s in (base, mid, fine)]}


# -- u_input ------------------------------------------------------------------

def u_x(source: str, entry: VariableRecord, stated_tolerance: Optional[float] = None) -> Tuple[float, str]:
    """The standard uncertainty of the applied value by source rank, and
    the rule sentence that produced it."""
    rule = entry.u_input_rule
    if source == "user":
        if stated_tolerance is not None:
            return abs(float(stated_tolerance)), "user: the stated tolerance"
        return 0.0, "user: 0 (no tolerance stated with the value)"
    if source == "inferred":
        if rule.bin_width is None:
            raise ValueError(f"{entry.name}: an inferred value needs a vocabulary bin width, "
                             f"and the registry declares none ({rule.note})")
        b = float(rule.bin_width)
        return (b / 2.0) / math.sqrt(3.0), f"inferred: (b/2)/sqrt(3) for a vocabulary bin of width b = {b:g} {entry.unit} (uniform, GUM 4.3.7)"
    if source == "sampled":
        return 0.0, "sampled: 0 (the draw is the value; its distribution is the campaign's)"
    if source in ("model", "default", "derived"):
        return float(rule.declared_spread), f"{source}: the registry's declared spread {rule.declared_spread:g} {entry.unit}"
    raise ValueError(f"unknown provenance source {source!r}")


def central_sensitivity(spec, entry: VariableRecord, u: float,
                        runner: Optional[Callable[[Any], Any]] = None) -> Dict[str, Any]:
    """c_i per SRQ from the central pair x +- u: (S(x+u) - S(x-u)) / (2u),
    S = the SRQ at the final common sample. Refuses a zero u."""
    from .scenario.spec import ScenarioSpec

    if u <= 0.0:
        raise ValueError("a central pair needs a positive u_x")
    if entry.spec_path is None:
        raise ValueError(f"{entry.name} has no spec field to perturb")
    section, leaf = entry.spec_path.split(".")
    data = spec.to_dict()
    x = float(data[section][leaf]["value"])
    run = runner if runner is not None else _default_runner()

    def at(value: float):
        d = {k: (dict(v) if isinstance(v, Mapping) else v) for k, v in data.items()}
        d[section] = dict(d[section])
        d[section][leaf] = dict(d[section][leaf], value=value, source="derived")
        d[section][leaf]["from"] = f"central sensitivity pair for {entry.name}"
        return run(ScenarioSpec.from_dict(d))

    plus, minus = at(x + u), at(x - u)
    s_plus, s_minus = srq_series(plus.telemetry.columns), srq_series(minus.telemetry.columns)
    out: Dict[str, Any] = {}
    for srq in SRQS:
        if srq in s_plus and srq in s_minus and len(s_plus[srq]) and len(s_minus[srq]):
            n = min(len(s_plus[srq]), len(s_minus[srq]))
            out[srq] = float((s_plus[srq][n - 1] - s_minus[srq][n - 1]) / (2.0 * u))
        else:
            out[srq] = None
    return {"sensitivity": out, "u_x": u, "x": x,
            "digests": {"plus": plus.output_digest, "minus": minus.output_digest},
            "basis": "central pair x +- u_x; S = the SRQ at the final common sample; "
                     "a secant, labelled GUM c_i to first order"}


def u_input_for(entry: VariableRecord, stated: Mapping[str, Any], spec=None,
                runner: Optional[Callable[[Any], Any]] = None,
                sensitivity: Optional[Mapping[str, Optional[float]]] = None) -> Dict[str, Any]:
    """The record's ``u_input`` block {value, unit, rule, sensitivity} for
    one variable from the spec's provenanced mapping. The sensitivity is
    measured by the central pair when u_x > 0 and none is given; a zero
    u_x runs no pair and says so."""
    source = str(stated.get("source", "default"))
    ux, rule = u_x(source, entry, stated.get("tolerance"))
    block: Dict[str, Any] = {"value": ux, "unit": entry.unit, "rule": rule, "sensitivity": None,
                             "sensitivity_basis": None}
    if sensitivity is not None:
        block["sensitivity"] = dict(sensitivity)
        block["sensitivity_basis"] = "given"
    elif ux > 0.0 and spec is not None:
        pair = central_sensitivity(spec, entry, ux, runner=runner)
        block["sensitivity"] = pair["sensitivity"]
        block["sensitivity_basis"] = pair["basis"]
        block["sensitivity_digests"] = pair["digests"]
    else:
        block["sensitivity_basis"] = ("no pair run: u_x is 0, so u_input is 0 for every SRQ"
                                      if ux == 0.0 else "no pair run: no spec to perturb")
    return block


def u_val(u_num: Mapping[str, Any], u_input: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """u_val per SRQ = sqrt(u_num^2 + sum_i (c_i u_x_i)^2); None where u_num
    was not run. Each term is listed so the sum is checkable."""
    out: Dict[str, Any] = {}
    for srq in SRQS:
        num = (u_num.get("srq", {}).get(srq) or {}).get("value")
        terms: Dict[str, Optional[float]] = {}
        for name, block in u_input.items():
            sens = (block.get("sensitivity") or {}).get(srq)
            ux = float(block.get("value") or 0.0)
            terms[name] = 0.0 if ux == 0.0 else (None if sens is None else abs(float(sens)) * ux)
        if num is None or any(v is None for v in terms.values()):
            out[srq] = {"value": None, "unit": SRQ_UNITS[srq], "u_num": num, "u_input_terms": terms,
                        "basis": "NOT RUN: a term is missing"}
            continue
        total = math.sqrt(float(num) ** 2 + sum(float(v) ** 2 for v in terms.values()))
        out[srq] = {"value": total, "unit": SRQ_UNITS[srq], "u_num": num, "u_input_terms": terms,
                    "basis": "sqrt(u_num^2 + sum u_input_i^2); u_D absent"}
    return out


def uncertainty_block(u_num: Mapping[str, Any], u_input: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """The top-level ``uncertainty`` block for run.json and the capture manifest."""
    return {"u_num": dict(u_num), "u_input": {k: dict(v) for k, v in u_input.items()},
            "u_val": u_val(u_num, u_input), "form": FORM,
            "not_claimed": [
                "u_D: no referent is added per run, so this is the run's own uncertainty, "
                "not a validation",
                "u_num is one dt/2 twin with an assumed order unless the three-rate study ran",
                "u_input is first-order (GUM eq. 10) with a secant sensitivity",
            ]}


def uncertainty_for_run(spec, runner: Optional[Callable[[Any], Any]] = None,
                        registry: Registry = REGISTRY, base_result=None,
                        observed_p: Optional[Mapping[str, float]] = None) -> Dict[str, Any]:
    """The whole block for one run: the dt/2 twin plus u_input for every
    registered spec field the spec states."""
    num = u_num_twin(spec, runner=runner, observed_p=observed_p, base_result=base_result)
    inputs: Dict[str, Dict[str, Any]] = {}
    for name, stated in registry.stated_variables(spec.to_dict()).items():
        inputs[name] = u_input_for(registry.get(name), stated, spec=spec, runner=runner)
    return uncertainty_block(num, inputs)


def record_u_num(u_num: Mapping[str, Any], srq: str) -> Optional[Dict[str, Any]]:
    """The record-level ``u_num`` {srq, value, basis} for one SRQ, or None
    when that SRQ was not run."""
    part = (u_num.get("srq") or {}).get(srq)
    if not part or part.get("value") is None:
        return None
    return {"srq": srq, "value": part["value"], "basis": part["basis"]}
