"""Gate 3b -- the physics layers' null ladder (rows A7-A9 and the ladder of
docs/vva/VV_PLAN.md section 3b; blueprint section 1, "Verification here").

Gate 3 asked whether each environment provider reached the equations of
motion. The advancement additions put eight more layers into the flight
(the stated day, humidity, von Karman turbulence, the wake pair, icing,
loading, the failure schedule, layered wind); this gate asks the same
question of each, through the one mechanism every layer's record already
names: :func:`core.record_null.run_null_pair` -- the identical spec with
the one registered field at its null value, both flown, the effect per
registered channel against its floor, both digests. On top of the
connectivity verdict each rung grades a STATED criterion, declared in
VV_PLAN.md before the run:

  ===================  =====================================================
  delta-T 0 vs +30     TAS / CAS at the first sample within 0.5 % of
                       1 / sqrt(sigma), sigma from P1's closed form, in both
                       runs
  dry vs 100 % RH      (A7) the density ratio humid / dry at the same P and T
                       within 0.05 % of 1 - 0.378 e / p; u_D from A&E 1996's
                       ~0.1 % difference in e_s
  vK vs none           (A9) the delivered sigma_w within 10 % of the ladder's
  vK vs Dryden         the same ladder sigma_w commanded to both (equal by
                       construction); the von Karman side within 10 %;
                       Dryden's own channel is internal to JSBSim (not graded)
  encounter vs none    peak |roll| > 5 deg at the stated geometry (P7's)
  far offset control   SILENT over the graded channels, the wake present
  eta 0 vs 0.2         the lift at fixed alpha (the ICs) falls by the factor
                       1 + eta k_lift within 1 %
  0 vs 136 kg aft      the CG, the trim elevator and the pitch all reached
  engine-out (A320)    the engine's thrust under 1 N on every sample after
                       the write, above 1 kN without
  jam (A320, TECS)     the jammed elevator holds within 1e-6 rad over 100
                       steps (the schedule's hold), the pair reached
  layered vs uniform   the delivered base wind equals the layers' linear
                       interpolation at the altitude within 1e-3 m/s
  ===================  =====================================================

plus A8, which flies nothing: JSBSim's standard day at delta-T 0 against the
US Standard Atmosphere 1976 table at 0 / 3000 / 11000 m (transcribed from
memory, [unverified here]; the transcription is checked here against the
1976 defining equations, which are also from memory).

Every row is PASS, FAIL or NOT RUN with its reason (:func:`row_status`: a
row PASSES only when its criterion is met AND its pair's verdict is the
expected one AND, for a pair expected to reach, the two output digests
differ -- a FAIL cannot read PASS). A refusal by name is NOT RUN with the
name. The result is written with a manifest in the existing experiments'
form (``core.experiments.manifest.RunManifest``, as experiments/
gate7_sweep.py writes it): ``runs/gate3b/gate3b_layers.json`` and
``runs/gate3b/manifest.json`` (``--out`` to move them).

NOT claimed: a null pair is connectivity and one-sided sensitivity, not
correctness; the criteria grade the model against its own closed forms and
stated standards, not against a measured aircraft (u_D is declared only
where a referent is named: A7, A8, A9). The rungs are 3 s flights; the
turbulence rows' sigma is over a 3 s realisation.

Usage: ``.venv/bin/python -m experiments.gate3b_layers [--out DIR]
[--seconds 3] [--only KEY ...]``
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.experiments.manifest import RunManifest, sha256_file  # noqa: E402
from core.record_null import NULL_FLOOR_REFERENCE, run_null_pair  # noqa: E402

EXPERIMENT = "gate3b-layers"
PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT RUN"
STATUSES = (PASS, FAIL, NOT_RUN)

#: The stated criteria (docs/vva/VV_PLAN.md section 3b; the blueprint's numbers).
TAS_CAS_TOLERANCE = 0.005            # 0.5 % of 1 / sqrt(sigma)
HUMIDITY_RATIO_TOLERANCE = 0.0005    # 0.05 % of 1 - 0.378 e / p (A7)
HUMIDITY_COEFFICIENT = 0.378         # 1 - M_water / M_dry, rounded as the relation is quoted
AE1996_ES_FRACTION = 0.001           # u_D: Alduchov & Eskridge 1996's ~0.1 % in e_s [unverified here]
SIGMA_W_TOLERANCE = 0.10             # A9: sigma_w within 10 % of the ladder
WAKE_ROLL_THRESHOLD_DEG = 5.0        # P7: peak |roll| past 5 deg at the stated geometry
LIFT_FACTOR_TOLERANCE = 0.01         # P5: lift at fixed alpha by the factor within 1 %
THRUST_OFF_N = 1.0                   # the force floor (core/record_null.py)
THRUST_ON_N = 1000.0                 # a running A320 engine is > 50 kN; 1 kN is "running"
LAYERED_SPEED_TOLERANCE_MPS = 1e-3   # one step's altitude change moves the speed ~1e-4 m/s
ISA_TOLERANCE = 0.001                # A8: 0.1 % relative, T, p and rho

#: The layers the shear tests fly (tests/test_shear.py LAYERS): 22.5 kt from 255 at 1500 m.
LAYERS = [[0.0, 5.0, 270.0], [1000.0, 15.0, 260.0], [2000.0, 30.0, 250.0]]
#: P7's demonstration geometry: the starboard vortex's line, 15 m above, 20 s old.
WAKE_GEOMETRY = {"generator": "B747", "generator_speed_kt": 250.0, "separation_s": 20.0,
                 "lateral_offset_m": 25.315, "vertical_offset_m": 15.0}
WAKE_FAR_OFFSET_M = 300.0

#: A8: the US Standard Atmosphere 1976 at geometric altitude (T K, p Pa, rho kg/m^3),
#: transcribed from memory of the published table [unverified here], at the table's
#: printed precision; ``ussa1976_defining`` re-derives each row from the defining
#: equations (also from memory) as a check on the transcription.
USSA_1976 = {
    0.0: (288.150, 1.01325e5, 1.2250),
    3000.0: (268.659, 7.0121e4, 9.0925e-1),
    11000.0: (216.774, 2.2700e4, 3.6480e-1),
}
#: Half a unit in the last printed digit of each column, per row: the table's own u_D.
USSA_1976_HALF_DIGIT = {
    0.0: (0.0005, 0.5, 0.00005),
    3000.0: (0.0005, 0.5, 0.000005),
    11000.0: (0.0005, 0.5, 0.000005),
}


# -- the status of a row ------------------------------------------------------------

def row_status(criterion_ok: Optional[bool], verdict: Optional[str],
               expected_verdict: str = "reached", digests_differ: Optional[bool] = None,
               not_run: Optional[str] = None) -> str:
    """PASS only when the criterion is met, the pair's verdict is the one
    expected and -- for a pair expected to reach -- the two output digests
    differ; NOT RUN when the row was refused or could not be graded (a
    reason is always carried beside it); FAIL otherwise."""
    if not_run:
        return NOT_RUN
    if criterion_ok is None or verdict is None:
        return NOT_RUN
    if criterion_ok is not True:
        return FAIL
    if verdict != expected_verdict:
        return FAIL
    if expected_verdict == "reached" and digests_differ is not True:
        return FAIL
    return PASS


# -- the specs ---------------------------------------------------------------------

def _prompt(aircraft: str, altitude_m: float, kt: float, seconds: float, extra: str = ""):
    from core.nl.compiler import compile_prompt

    text = f"fly the {aircraft} at {altitude_m:g} m and {kt:g} kt for {seconds:g} seconds"
    return compile_prompt(text + (f" {extra}" if extra else ""))


def c172p_spec(seconds: float, extra: str = "", **fields):
    """The c172p at 1500 m / 100 kt, open loop: the compiler's default
    hold_state engages the autopilot, whose sign probe trims at 6000 m /
    280 kt, outside the c172p's envelope (measured by P1 and P3)."""
    spec = _prompt("c172p", 1500.0, 100.0, seconds, extra)
    spec.set("hold_state", False, frm="gate3b: open loop (the c172p cannot hold its state here)")
    for path, value in fields.items():
        spec.set(path, value, frm="gate3b rung")
    return spec


def a320_spec(seconds: float, events, hold: bool = False, turbulence: Optional[str] = None):
    spec = _prompt("A320", 1500.0, 250.0, seconds)
    spec.set("hold_state", hold, frm="gate3b rung")
    if turbulence is not None:
        spec.set("turbulence", turbulence, frm="gate3b rung (the same seed both sides)")
    spec.set("failures.events", events, frm="gate3b rung")
    return spec


# -- reading a run -----------------------------------------------------------------

def record(run, name: str) -> Optional[Dict[str, Any]]:
    """The run manifest's applied-variable record of that name, or None."""
    block = (run.manifest.get("applied_variables") or {}).get("applied_variables") or ()
    for rec in block:
        if rec.get("name") == name:
            return rec
    return None


def _std(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / n)


# -- the graders: (pair, with_run, without_run) -> {ok, measured, note} ------------------

def grade_delta_t(pair, with_run, without_run) -> Dict[str, Any]:
    from core.environment.atmosphere import expected_density_ratio

    measured: Dict[str, Any] = {}
    ok = True
    for label, run, delta_t in (("with", with_run, float(pair.applied_value)),
                                ("without", without_run, float(pair.null_value))):
        c = run.telemetry.columns
        tas, cas, alt = float(c["tas_kt"][0]), float(c["cas_kt"][0]), float(c["altitude_m"][0])
        sigma = expected_density_ratio(delta_t, None, None, alt)
        predicted = 1.0 / math.sqrt(sigma)
        ratio = tas / cas
        rel = abs(ratio / predicted - 1.0)
        ok = ok and rel <= TAS_CAS_TOLERANCE
        measured[label] = {"delta_t_c": delta_t, "altitude_m": alt, "tas_kt": tas, "cas_kt": cas,
                           "tas_over_cas": ratio, "sigma_closed_form": sigma,
                           "one_over_sqrt_sigma": predicted, "relative_error": rel}
    measured["cas_difference_kt"] = measured["with"]["cas_kt"] - measured["without"]["cas_kt"]
    measured["tas_difference_kt"] = measured["with"]["tas_kt"] - measured["without"]["tas_kt"]
    return {"ok": ok, "measured": measured,
            "note": ("the first sample (the trimmed state); sigma is the ISA-sea-level density "
                     "ratio from core.environment.atmosphere.expected_density_ratio (P1's "
                     "transcription of JSBSim's own equations); CAS and EAS differ by the "
                     "compressibility term, ~0.05 % at 100 kt, inside the 0.5 %")}


def grade_humidity(pair, with_run, without_run) -> Dict[str, Any]:
    rec = record(with_run, "atmosphere.relative_humidity_pct")
    if rec is None:
        return {"ok": None, "measured": {}, "note": "NOT RUN: the humid run carries no "
                                                    "atmosphere.relative_humidity_pct record"}
    null = rec["null_test"]
    delivered = rec["parameters"]["delivered"]
    s = float(null["with"]) / float(null["without"])
    e_pa = float(delivered["vapour_pressure_pa"])
    p_pa = float(delivered["pressure_hpa"]) * 100.0
    d = 1.0 - HUMIDITY_COEFFICIENT * e_pa / p_pa
    e = s - d
    u_d = HUMIDITY_COEFFICIENT * AE1996_ES_FRACTION * e_pa / p_pa
    rel = abs(e) / d
    return {"ok": rel <= HUMIDITY_RATIO_TOLERANCE,
            "measured": {"density_humid_kgm3": float(null["with"]),
                         "density_dry_kgm3": float(null["without"]),
                         "S_density_ratio": s, "D_one_minus_0378_e_over_p": d,
                         "vapour_pressure_pa": e_pa, "pressure_pa": p_pa,
                         "temperature_k": float(delivered["temperature_k"]),
                         "rh_pct": float(delivered["rh_pct"]),
                         "vv20": {"E": e, "relative_E": rel, "u_D": u_d, "u_num": 0.0,
                                  "u_input": 0.0, "u_val": u_d,
                                  "validated_at_u_val": abs(e) <= u_d}},
            "note": ("S = JSBSim's density after the dew-point write over before it, on the same "
                     "FDM at the ICs (the record's null test: same P and T); D = the ideal-gas "
                     "moist-air relation with JSBSim's own delivered e and p; u_D = 0.378 x 0.1 % "
                     "x e / p (A&E 1996's e_s difference, unverified here); u_num 0 (a state, no "
                     "integration), u_input 0 (the RH is stated)")}


def _vk_sigma(with_run) -> Dict[str, Any]:
    rec = record(with_run, "turbulence_model.model")
    if rec is None:
        return {}
    params = rec["parameters"]
    commanded = float(params["sigma_commanded_mps"][2])
    delivered = float((params.get("channel_std_mps") or {}).get("down", 0.0))
    column = _std([float(v) for v in with_run.telemetry.columns["gust_down_mps"]])
    rel = abs(delivered - commanded) / commanded if commanded else float("inf")
    return {"sigma_w_commanded_mps": commanded, "sigma_w_delivered_mps": delivered,
            "sigma_w_recorded_column_mps": column, "relative_error": rel,
            "vv20": {"E": delivered - commanded, "relative_E": rel, "u_D": None,
                     "note": "the ladder is the standard (MIL-F-8785C through FGWinds' "
                             "transcription, unverified here); no u_D is declared, the row "
                             "grades the 10 % tolerance"}}


def grade_vk_none(pair, with_run, without_run) -> Dict[str, Any]:
    measured = _vk_sigma(with_run)
    if not measured:
        return {"ok": None, "measured": {}, "note": "NOT RUN: no turbulence_model.model record"}
    return {"ok": measured["relative_error"] <= SIGMA_W_TOLERANCE, "measured": measured,
            "note": ("delivered = the std of atmosphere/gust-down-fps read back from JSBSim before "
                     "every step's write over the run (the record's channel_std_mps); the recorded "
                     "10 Hz column's std beside it")}


def grade_vk_dryden(pair, with_run, without_run) -> Dict[str, Any]:
    measured = _vk_sigma(with_run)
    if not measured:
        return {"ok": None, "measured": {}, "note": "NOT RUN: no turbulence_model.model record"}
    measured["dryden_delivered_sigma_w"] = ("NOT RUN here: JSBSim's turb channel is not a "
                                            "recorded column (P6 measured 1.9 x the ladder on w "
                                            "over 60 s, tests/test_gust_provider.py)")
    return {"ok": measured["relative_error"] <= SIGMA_W_TOLERANCE, "measured": measured,
            "note": ("the same ladder sigma_w is commanded to both: the von Karman provider "
                     "transcribes FGWinds' ladder (L273-L288), the one JSBSim's Dryden process "
                     "reads, so the commanded numbers are equal by construction; the von Karman "
                     "side is graded on delivery and the aircraft's responses are compared by the "
                     "pair. The delivered channels are NOT within 10 % of each other (P6)")}


def grade_wake(pair, with_run, without_run) -> Dict[str, Any]:
    effect = {e.channel: e for e in pair.effects}.get("roll_deg")
    if effect is None:
        return {"ok": None, "measured": {}, "note": "NOT RUN: roll_deg is not a graded channel"}
    wake = with_run.manifest.get("wake") or {}
    gamma = (wake.get("prepared") or {}).get("gamma_0_m2_s")
    return {"ok": effect.peak_abs > WAKE_ROLL_THRESHOLD_DEG,
            "measured": {"peak_roll_difference_deg": effect.peak_abs,
                         "peak_abs_roll_with_deg": max(abs(float(v)) for v in
                                                       with_run.telemetry.columns["roll_deg"]),
                         "peak_abs_roll_without_deg": max(abs(float(v)) for v in
                                                          without_run.telemetry.columns["roll_deg"]),
                         "gamma_0_m2_s": gamma,
                         "peak_p_eq_rad_s": max(abs(float(v)) for v in
                                                with_run.telemetry.columns["wake_p_eq_rad_s"])},
            "note": ("the peak |roll(with) - roll(without)| against the stated 5 deg: the "
                     "longitudinally trimmed c172p rolls ~5.5 deg in 3 s open loop with no wake "
                     "at all, so the encounter's own absolute roll would not separate them")}


def grade_wake_control(pair, with_run, without_run) -> Dict[str, Any]:
    wake = with_run.manifest.get("wake") or {}
    gamma = (wake.get("prepared") or {}).get("gamma_0_m2_s")
    roll = max(abs(float(v)) for v in with_run.telemetry.columns["roll_deg"])
    present = gamma is not None and float(gamma) > 0.0
    return {"ok": present, "measured": {"gamma_0_m2_s": gamma, "peak_abs_roll_deg": roll},
            "note": ("a control: the same generator 300 m to the side; the wake is present "
                     "(Gamma_0 > 0) and the pair must read SILENT over its graded channels")}


def grade_icing(pair, with_run, without_run) -> Dict[str, Any]:
    rec = record(with_run, "icing.eta")
    if rec is None:
        return {"ok": None, "measured": {}, "note": "NOT RUN: no icing.eta record"}
    params = rec["parameters"]
    ratio = params["pre_trim"]["lift_ratio_with_factors"]
    k_entry = ((params.get("k_table") or {}).get("k_table") or {}).get("k_lift")
    k_lift = float(k_entry["value"]) if isinstance(k_entry, Mapping) else None
    eta = float(pair.applied_value)
    if k_lift is None or ratio is None:
        return {"ok": None, "measured": {"lift_ratio": ratio},
                "note": "NOT RUN: the record's k-table carries no lift value"}
    predicted = 1.0 + eta * k_lift
    rel = abs(float(ratio) / predicted - 1.0)
    c_with, c_without = with_run.telemetry.columns, without_run.telemetry.columns
    first = next((i for i, v in enumerate(c_with["icing_eta"]) if float(v) > 0.0), None)
    sample = None
    if first is not None and first < len(c_without["lift_n"]):
        sample = {"index": first, "t": float(c_with["t"][first]),
                  "lift_with_n": float(c_with["lift_n"][first]),
                  "lift_without_n": float(c_without["lift_n"][first]),
                  "ratio": float(c_with["lift_n"][first]) / float(c_without["lift_n"][first])}
    return {"ok": rel <= LIFT_FACTOR_TOLERANCE,
            "measured": {"eta": eta, "k_lift": k_lift, "predicted_factor": predicted,
                         "lift_ratio_at_fixed_alpha": float(ratio), "relative_error": rel,
                         "first_iced_sample": sample},
            "note": ("the lift at the ICs (fixed alpha) with the factors at eta_max over neutral, "
                     "each after a re-latch (the icing record's pre-trim measurement); the first "
                     "iced 10 Hz sample is reported beside it (twelve steps in, the alphas part)")}


def grade_loading(pair, with_run, without_run) -> Dict[str, Any]:
    effect = {e.channel: e for e in pair.effects}
    wanted = ("cg_x_m", "elevator_deg", "pitch_deg")
    missing = [w for w in wanted if w not in effect]
    if missing:
        return {"ok": None, "measured": {}, "note": f"NOT RUN: channels {missing} not graded"}
    rec = record(with_run, "loading.payload_kg")
    readback = None if rec is None else rec.get("readback")
    return {"ok": all(effect[w].reached is True for w in wanted),
            "measured": {w: {"peak_abs": effect[w].peak_abs, "floor": effect[w].floor,
                             "reached": effect[w].reached} for w in wanted}
                        | {"cg_readback": readback},
            "note": "the CG moves, the trim elevator differs and the pitch follows, each past its floor"}


def _run_clock_samples(run, t_applied_s: float) -> List[int]:
    failures = run.manifest.get("failures") or {}
    zero = float(failures.get("run_clock_zero_sim_time_s") or 0.0)
    dt = float(failures.get("dt_s") or 0.0)
    return [i for i, t in enumerate(run.telemetry.columns["t"])
            if float(t) - zero > t_applied_s + dt]


def grade_engine_out(pair, with_run, without_run) -> Dict[str, Any]:
    applied = (with_run.manifest.get("failures") or {}).get("applied") or []
    if not applied:
        return {"ok": None, "measured": {}, "note": "NOT RUN: the schedule applied nothing"}
    t_applied = float(applied[0]["t_applied_s"])
    after = _run_clock_samples(with_run, t_applied)
    c_with, c_without = with_run.telemetry.columns, without_run.telemetry.columns
    n = min(len(c_with["engine0_thrust_n"]), len(c_without["engine0_thrust_n"]))
    after = [i for i in after if i < n]
    if not after:
        return {"ok": None, "measured": {}, "note": "NOT RUN: no sample after the write"}
    worst_with = max(abs(float(c_with["engine0_thrust_n"][i])) for i in after)
    least_without = min(float(c_without["engine0_thrust_n"][i]) for i in after)
    return {"ok": worst_with < THRUST_OFF_N and least_without > THRUST_ON_N,
            "measured": {"t_applied_s": t_applied, "samples_after": len(after),
                         "max_thrust_after_with_n": worst_with,
                         "min_thrust_after_without_n": least_without,
                         "engine1_thrust_last_with_n": float(c_with["engine1_thrust_n"][-1])},
            "note": "engine 0's thrust on every 10 Hz sample after the cutoff write"}


def grade_jam(pair, with_run, without_run) -> Dict[str, Any]:
    failures = with_run.manifest.get("failures") or {}
    hold = (failures.get("hold") or [None])[0]
    if not hold or hold.get("ok") is None:
        return {"ok": None, "measured": {"hold": hold}, "note": "NOT RUN: no hold was measured"}
    return {"ok": bool(hold["ok"]), "measured": {"hold": hold, "applied": failures.get("applied")},
            "note": ("the schedule's own hold: the jammed elevator's position over the 100 steps "
                     "after the read-back against its position at the jam, tolerance 1e-6 rad. "
                     "On the c172p the same jam is SILENT by construction (open loop, the "
                     "command never moves; P3), so the row flies the A320 under TECS in moderate "
                     "turbulence (the same seed both sides)")}


def grade_layered(pair, with_run, without_run) -> Dict[str, Any]:
    from core.environment.base import Position
    from core.environment.shear import LayeredWind

    c = with_run.telemetry.columns
    k = len(c["t"]) - 1
    alt = float(c["altitude_m"][k])
    position = Position(float(c["lat_deg"][k]), float(c["lon_deg"][k]), alt,
                        float(c["agl_m"][k]), alt - float(c["agl_m"][k]))
    predicted = LayeredWind(LAYERS).profile_at(position)[0]
    delivered = float(c["wind_profile_speed_mps"][k])
    uniform = float(without_run.telemetry.columns["wind_profile_speed_mps"][k])
    err = abs(delivered - predicted)
    return {"ok": err <= LAYERED_SPEED_TOLERANCE_MPS,
            "measured": {"altitude_m": alt, "delivered_mps": delivered, "predicted_mps": predicted,
                         "abs_error_mps": err, "uniform_mps": uniform},
            "note": "the last sample's base wind against the layers' linear interpolation there"}


# -- the rungs -----------------------------------------------------------------------

@dataclass(frozen=True)
class Rung:
    """One rung of the ladder: a registered variable's null pair and the
    stated criterion graded on the two flights."""

    key: str
    title: str
    rows: Tuple[str, ...]
    variable: str
    criterion: str
    build: Callable[[float], Any]
    grade: Callable[..., Dict[str, Any]]
    expected_verdict: str = "reached"

    def definition(self) -> Dict[str, Any]:
        return {"key": self.key, "title": self.title, "rows": list(self.rows),
                "variable": self.variable, "criterion": self.criterion,
                "expected_verdict": self.expected_verdict}


RUNGS: Tuple[Rung, ...] = (
    Rung("delta_t", "delta-T 0 vs +30 degC (c172p)", ("V19", "ladder"),
         "atmosphere.temperature_deviation_c",
         "TAS / CAS at the first sample within 0.5 % of 1 / sqrt(sigma), sigma from P1's closed "
         "form, in both runs; the pair reached",
         lambda s: c172p_spec(s, **{"atmosphere.temperature_deviation_c": 30.0}), grade_delta_t),
    Rung("humidity", "dry vs 100 % RH (c172p)", ("A7", "V19", "ladder"),
         "atmosphere.relative_humidity_pct",
         "density ratio humid / dry at the same P and T within 0.05 % of 1 - 0.378 e / p; "
         "the pair reached",
         lambda s: c172p_spec(s, **{"atmosphere.relative_humidity_pct": 100.0}), grade_humidity),
    Rung("vk_vs_none", "von Karman (moderate) vs none (c172p)", ("A9", "V20", "ladder"),
         "turbulence_model.intensity",
         "the delivered sigma_w within 10 % of the ladder's; the pair reached",
         lambda s: c172p_spec(s, **{"turbulence_model.model": "von_karman",
                                    "turbulence_model.intensity": "moderate"}), grade_vk_none),
    Rung("vk_vs_dryden", "von Karman vs Dryden at the same word (c172p)", ("A9", "ladder"),
         "turbulence_model.model",
         "the same ladder sigma_w commanded to both, the von Karman side delivered within 10 %; "
         "the pair reached (the Dryden channel is JSBSim's own, not graded)",
         lambda s: c172p_spec(s, "with moderate turbulence",
                              **{"turbulence_model.model": "von_karman"}), grade_vk_dryden),
    Rung("wake", "wake encounter vs none (c172p behind a B747)", ("V16", "ladder"),
         "wake.generator",
         "peak |roll| > 5 deg at the stated geometry (25.315 m right, 15 m above, 20 s old, "
         "250 kt); the pair reached",
         lambda s: c172p_spec(s, **{f"wake.{k}": v for k, v in WAKE_GEOMETRY.items()}), grade_wake),
    Rung("wake_far_control", "wake 300 m to the side vs none (control)", ("V16", "ladder"),
         "wake.generator",
         "the wake present and the pair SILENT over its graded channels",
         lambda s: c172p_spec(s, **{f"wake.{k}": v for k, v in
                                    {**WAKE_GEOMETRY, "lateral_offset_m": WAKE_FAR_OFFSET_M}.items()}),
         grade_wake_control, expected_verdict="silent"),
    Rung("icing", "eta 0 vs 0.2 (c172p, the DHC6 row as a proxy)", ("ladder",),
         "icing.eta",
         "lift at fixed alpha falls by 1 + eta k_lift within 1 %; the pair reached",
         lambda s: c172p_spec(s, **{"icing.eta_max": 0.2}), grade_icing),
    Rung("loading", "0 vs 136 kg at the aft-most seat (c172p)", ("V13", "ladder"),
         "loading.payload_kg",
         "the CG, the trim elevator and the pitch each moved past its floor; the pair reached",
         lambda s: c172p_spec(s, **{"loading.payload": {"Right Passenger": 136.0}}), grade_loading),
    Rung("engine_out", "engine 0 out at 1 s vs none (A320, open loop)", ("V15", "ladder"),
         "failures.events",
         "engine 0's thrust under 1 N on every sample after the write, over 1 kN without; "
         "the pair reached",
         lambda s: a320_spec(s, [{"kind": "engine_out", "target": 0, "at_s": 1.0}]),
         grade_engine_out),
    Rung("jam", "elevator jam at 1 s vs none (A320, TECS, moderate Dryden)", ("V15", "ladder"),
         "failures.events",
         "the jammed elevator holds within 1e-6 rad over 100 steps; the pair reached",
         lambda s: a320_spec(s, [{"kind": "control_jam", "target": "elevator", "at_s": 1.0}],
                             hold=True, turbulence="moderate"), grade_jam),
    Rung("layered", "layered vs uniform wind (c172p, 20 kt from 270)", ("V17", "ladder"),
         "wind_profile.kind",
         "the delivered base wind equals the layers' interpolation at the altitude within "
         "1e-3 m/s; the pair reached",
         lambda s: _layered_spec(s), grade_layered),
)


def _layered_spec(seconds: float):
    spec = c172p_spec(seconds)
    spec.set("wind_speed", 20.0, frm="gate3b rung: the uniform wind the layers replace")
    spec.set("wind_direction", 270.0, frm="gate3b rung")
    spec.set("wind_profile.kind", "layered", frm="gate3b rung")
    spec.set("wind_profile.layers", LAYERS, frm="gate3b rung")
    return spec


def rung(key: str) -> Rung:
    for r in RUNGS:
        if r.key == key:
            return r
    raise KeyError(key)


# -- running a rung ------------------------------------------------------------------

def quiet_run(spec):
    """run_spec with closure not asserted and its chatter swallowed."""
    from core.scenario.runner import run_spec

    with contextlib.redirect_stdout(io.StringIO()):
        return run_spec(spec, assert_closure=False)


def _refusal(exc: BaseException) -> str:
    names = []
    constraint = getattr(exc, "constraint", None)
    if constraint:
        names.append(str(constraint))
    report = getattr(exc, "report", None)
    for v in getattr(report, "violations", ()) or ():
        names.append(str(getattr(v, "constraint", v)))
    head = ", ".join(names) if names else type(exc).__name__
    return f"refused {head}: {str(exc).splitlines()[0] if str(exc) else ''}".rstrip(": ")


def run_rung(r: Rung, seconds: float = 3.0,
             runner: Optional[Callable[[Any], Any]] = None) -> Dict[str, Any]:
    """Fly one rung through run_null_pair and grade it. A refusal (by name)
    or any failure to fly is NOT RUN with the reason."""
    flown: List[Any] = []
    base = runner if runner is not None else quiet_run

    def capture(spec):
        result = base(spec)
        flown.append(result)
        return result

    t0 = time.perf_counter()
    out: Dict[str, Any] = {**r.definition(), "seconds": seconds}
    try:
        spec = r.build(seconds)
        with contextlib.redirect_stdout(io.StringIO()):
            pair = run_null_pair(spec, r.variable, runner=capture)
    except Exception as exc:                       # a refusal by name, or a flight that failed
        out.update({"status": NOT_RUN, "reason": _refusal(exc), "verdict": None,
                    "elapsed_s": time.perf_counter() - t0})
        return out
    graded = r.grade(pair, flown[0], flown[1])
    status = row_status(graded["ok"], pair.verdict, r.expected_verdict, pair.digests_differ)
    d = pair.to_dict()
    out.update({
        "status": status,
        "reason": (graded.get("note") if status != NOT_RUN else
                   graded.get("note") or "the criterion could not be graded"),
        "criterion_ok": graded["ok"], "measured": graded["measured"],
        "verdict": pair.verdict, "applied_value": pair.applied_value,
        "null_value": pair.null_value, "digests": d["digests"],
        "effect": {name: {k: e[k] for k in ("unit", "peak_abs", "floor", "reached")}
                   for name, e in d["effect"].items()},
        "null_test": d["null_test"], "notes": d["notes"],
        "elapsed_s": time.perf_counter() - t0,
    })
    return out


# -- A8: JSBSim's standard day against the 1976 table ------------------------------------

def ussa1976_defining(z_m: float) -> Tuple[float, float, float]:
    """The 1976 model's defining equations below 11 km geopotential (from
    memory, [unverified here]): H = r0 Z / (r0 + Z), T = 288.15 - 6.5 H/km,
    p = 101325 (T / 288.15)^(g0 M0 / (R* L)), rho = p M0 / (R* T)."""
    r0, g0, m0, r_star, lapse = 6356766.0, 9.80665, 0.0289644, 8.31432, 0.0065
    h = r0 * z_m / (r0 + z_m)
    t = 288.15 - lapse * min(h, 11000.0)
    p = 101325.0 * (t / 288.15) ** (g0 * m0 / (r_star * lapse))
    return t, p, p * m0 / (r_star * t)


def jsbsim_standard_day(z_m: float, aircraft: str = "c172p") -> Tuple[float, float, float]:
    """JSBSim's atmosphere at geometric altitude ``z_m`` at delta-T 0 (the
    stock model's initial conditions latched; nothing flown)."""
    from core.fdm import FlightDynamics
    from core.fdm import units as u

    with contextlib.redirect_stdout(io.StringIO()):
        fdm = FlightDynamics(aircraft)
        fdm.set_initial_conditions({"h-sl-ft": u.m_to_ft(z_m), "vc-kts": 100.0})
    g = fdm.props.get
    return (u.rankine_to_kelvin(g("atmosphere/T-R")), u.psf_to_pa(g("atmosphere/P-psf")),
            u.slugft3_to_kgm3(g("atmosphere/rho-slugs_ft3")))


def a8_row(standard_day: Callable[[float], Tuple[float, float, float]] = jsbsim_standard_day
           ) -> Dict[str, Any]:
    """A8: E = S - D per altitude and quantity, u_D the table's half digit,
    u_num 0 (a state, not an integration), u_input 0 (the altitude is exact)."""
    rows = []
    ok = True
    for z, table in USSA_1976.items():
        s = standard_day(z)
        defining = ussa1976_defining(z)
        half = USSA_1976_HALF_DIGIT[z]
        entry = {"altitude_m": z}
        for i, name in enumerate(("temperature_k", "pressure_pa", "density_kgm3")):
            e = s[i] - table[i]
            rel = abs(e) / table[i]
            ok = ok and rel <= ISA_TOLERANCE
            entry[name] = {"S_jsbsim": s[i], "D_table": table[i], "E": e, "relative_E": rel,
                           "u_D": half[i], "u_val": half[i],
                           "validated_at_u_val": abs(e) <= half[i],
                           "transcription_vs_defining": defining[i] - table[i]}
        rows.append(entry)
    transcription_ok = all(abs(row[q]["transcription_vs_defining"]) <= 1.0001 * row[q]["u_D"]
                           for row in rows for q in ("temperature_k", "pressure_pa", "density_kgm3"))
    status = row_status(ok if transcription_ok else None, "reached", "reached", True,
                        not_run=None if transcription_ok else
                        "the transcribed table disagrees with the defining equations")
    return {"key": "a8_isa", "title": "JSBSim's standard day vs US Standard Atmosphere 1976",
            "rows": ["A8"], "variable": None,
            "criterion": "T, p and rho within 0.1 % of the 1976 table at 0 / 3000 / 11000 m",
            "status": status, "criterion_ok": ok, "transcription_ok": transcription_ok,
            "measured": rows,
            "reason": ("the table transcribed from memory [unverified here], checked against the "
                       "1976 defining equations (also from memory) within half its last digit; "
                       "JSBSim read at the latched ICs of the stock c172p, nothing flown")}


# -- the whole ladder, the manifest ----------------------------------------------------

def run_ladder(seconds: float = 3.0, only: Optional[Sequence[str]] = None,
               runner: Optional[Callable[[Any], Any]] = None,
               with_a8: bool = True) -> Dict[str, Any]:
    chosen = [r for r in RUNGS if not only or r.key in only]
    rows = []
    for r in chosen:
        print(f"  {r.key:18s} ...", end="", flush=True)
        row = run_rung(r, seconds=seconds, runner=runner)
        print(f" {row['status']:7s} ({row.get('verdict')}, {row['elapsed_s']:.1f} s)")
        rows.append(row)
    if with_a8 and (not only or "a8_isa" in only):
        rows.append(a8_row())
    counts = {s: sum(1 for row in rows if row["status"] == s) for s in STATUSES}
    return {"experiment": EXPERIMENT, "seconds": seconds, "rows": rows, "counts": counts,
            "gate": FAIL if counts[FAIL] else PASS, "floors": NULL_FLOOR_REFERENCE}


def build_manifest(result: Mapping[str, Any], ladder_path: Path,
                   specs: Mapping[str, str], seeds: Mapping[str, Any]) -> RunManifest:
    """The run manifest in the existing experiments' form (gate7_sweep.py):
    the rung definitions and tolerances as parameters, every rung's spec
    as an input by digest, the ladder file as the output."""
    manifest = RunManifest(name=EXPERIMENT)
    manifest.parameters = {
        "seconds": result["seconds"],
        "rungs": [r.definition() for r in RUNGS],
        "a8": {"altitudes_m": list(USSA_1976), "table": {str(k): list(v) for k, v in USSA_1976.items()},
               "source": "US Standard Atmosphere 1976, transcribed from memory [unverified here]"},
        "tolerances": {"tas_cas": TAS_CAS_TOLERANCE, "humidity_ratio": HUMIDITY_RATIO_TOLERANCE,
                       "sigma_w": SIGMA_W_TOLERANCE, "wake_roll_deg": WAKE_ROLL_THRESHOLD_DEG,
                       "lift_factor": LIFT_FACTOR_TOLERANCE, "thrust_off_n": THRUST_OFF_N,
                       "thrust_on_n": THRUST_ON_N, "layered_speed_mps": LAYERED_SPEED_TOLERANCE_MPS,
                       "isa": ISA_TOLERANCE},
        "floors": NULL_FLOOR_REFERENCE,
    }
    manifest.seeds = {"per_rung": dict(seeds),
                      "derivation": "each rung flies its spec's own stated seed (the compiler's "
                                    "default); the null run keeps it; no stream is derived here"}
    manifest.components = {"null_pair": "core.record_null.run_null_pair",
                           "runner": "core.scenario.runner.run_spec (closure not asserted)"}
    for key, text in specs.items():
        manifest.add_input_text(f"spec:{key}", text)
    manifest.add_output("ladder", ladder_path)
    manifest.notes = [f"{row['key']}: {row['status']}" for row in result["rows"]]
    return manifest


def write(result: Dict[str, Any], out: Path, seconds: float) -> Tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    ladder_path = out / "gate3b_layers.json"
    ladder_path.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n",
                           encoding="utf-8")
    specs, seeds = {}, {}
    for r in RUNGS:
        if any(row["key"] == r.key for row in result["rows"]):
            try:
                spec = r.build(seconds)
            except Exception:                       # recorded as NOT RUN already
                continue
            specs[r.key] = spec.to_yaml()
            seeds[r.key] = spec.seed.value
    manifest_path = build_manifest(result, ladder_path, specs, seeds).write(out / "manifest.json")
    return ladder_path, manifest_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Gate 3b: the physics layers' null ladder")
    ap.add_argument("--out", default=str(REPO / "runs" / "gate3b"))
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--only", nargs="*", default=None,
                    help="rung keys (and/or a8_isa) to run; all by default")
    args = ap.parse_args(argv)
    print("GATE 3b -- the physics layers' null ladder")
    result = run_ladder(args.seconds, args.only)
    ladder_path, manifest_path = write(result, Path(args.out), args.seconds)
    for row in result["rows"]:
        print(f"  [{row['status']:7s}] {row['key']:18s} {row['title']}")
    print(f"  counts {result['counts']}; ladder {ladder_path}")
    print(f"  manifest {manifest_path} sha256 {sha256_file(manifest_path)}")
    print(f"\n  GATE 3b: {result['gate']}")
    return 0 if result["gate"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
