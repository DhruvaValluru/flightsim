"""Modal analysis against the handling-qualities bands (gap M2, row A5).

From the SI classical blocks of :mod:`core.fdm.linearize` this module
takes the eigenvalues, names the modes, and grades each against the
Level 1/2/3 bands of MIL-F-8785C (the numbers MIL-STD-1797A carries
forward where they are cited) for the airframe's class and the flight
phase category. The result is a RECORD OF A RESULT, not an
``AppliedVariable``: nothing is applied to the run, no property is
written, no trajectory changes; the analysis reads a trimmed state and
reports what the linear model says about it. It is attached to the run
manifest under ``modes`` (:func:`modes_block`) and printed by
``python -m flightsim.modes``.

Eigenvalue-to-mode mapping (stated, guarded, not inferred from the data):

* longitudinal 4x4 (``Vt, alpha, theta, q``): complex pairs sorted by
  natural frequency, highest first; the first pair is the SHORT PERIOD,
  the second the PHUGOID. With one pair and two real roots, the pair is
  the short period when its natural frequency exceeds the larger real
  root's magnitude, else it is the phugoid; the real roots make the other
  mode, reported ``oscillatory: false``. Four real roots: the two largest
  in magnitude are the short period, the two smallest the phugoid.
* lateral-directional 4x4 (``beta, phi, p, r``): the complex pair of
  highest natural frequency is the DUTCH ROLL; of the real roots the
  most negative (largest magnitude) is the ROLL mode and the smallest in
  magnitude the SPIRAL. Two complex pairs (a coupled roll-spiral, the
  "lateral phugoid") are reported as such: the roll and spiral entries
  carry the second pair and ``coupled: true``.

For a pair ``sigma +/- j omega``: ``omega_n = |lambda|``, ``zeta =
-sigma/omega_n``, ``period = 2 pi / omega``. For a real root ``sigma``:
time constant ``-1/sigma`` (stable), time to double ``ln 2 / sigma``
(unstable) or time to half ``ln 2 / -sigma`` (stable).

The bands are encoded in :data:`BANDS` with the reference designation
and section for each. The specification document is not reachable from
this container (the network allows only the terrain buckets and
sourceforge), so every table is marked ``unverified here`` with the
confidence the encoder has in it: ``high`` where the numbers are the
well-known ones (short-period damping Table IV, phugoid 3.2.1.2, roll
Table VII, spiral Table VIII, Dutch roll Table VI), ``moderate`` for the
short-period frequency bounds, which the specification gives as figures
of ``omega_sp^2/(n/alpha)`` (the control anticipation parameter) and
which are encoded from memory of those figures. ``n/alpha`` is taken
from the linear model as ``-V A[alpha, alpha] / g`` (g per rad), an
approximation that neglects the alpha-dot and pitch-rate lift terms,
stated in the record.

Airframe class (MIL-F-8785C 3.1.1) comes from :data:`AIRFRAME_CLASS`,
keyed by the configured airframe name; an airframe with no class is
refused by name (``modes.airframe_class``) rather than graded against a
guessed one. Flight phase category defaults to ``B`` (non-terminal,
gradual manoeuvres: cruise), which is what every run on this branch is.

Not claimed: that any airframe meets or fails a handling-qualities
requirement -- the bands are applied to a stock JSBSim model with no
validated data (docs/VALIDITY.md), so a level is a statement about the
model, not about the aeroplane; the CO/GA rows of Table VI (a Category A
combat phase this branch never flies); the pilot-in-the-loop criteria
(bandwidth, time delay, PIO) which need a control system the runs do not
carry; a class for an airframe not in :data:`AIRFRAME_CLASS`; anything
about the DHC6 or p51d, which do not load in this container (measured
2026-09-28: no JSBSim aircraft named dhc6; the p51d engine file is
missing).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .linearize import (
    LATERAL_STATES, LONGITUDINAL_STATES, FT_TO_M, LinearModel, ModesError, linearize,
)

#: Standard gravity, m/s^2, for n/alpha.
G0 = 9.80665

#: The record's own version key; readers key on it. Optional, absent-canonical
#: in the run manifest (ADVANCEMENTS_CONTRACTS rule 0: no manifest bump here).
MODES_VERSION = 1

#: MIL-F-8785C 3.1.1 airplane classes for the configured airframes. The
#: class is a statement about the aeroplane's role and weight, cited per
#: entry; it is not read from the JSBSim model.
AIRFRAME_CLASS: Dict[str, Dict[str, str]] = {
    "c172p": {"class": "I", "source": "MIL-F-8785C 3.1.1 Class I, small light aeroplanes "
                                       "(light utility, primary trainer); Cessna 172P MTOW "
                                       "2550 lb (FAA TCDS 3A12) -- unverified here"},
    "DHC6": {"class": "II", "source": "MIL-F-8785C 3.1.1 Class II, medium weight, low-to-"
                                      "medium manoeuvrability (light/medium transport); "
                                      "DHC-6 MTOW 12500 lb -- unverified here; land-based (II-L)"},
    "A320": {"class": "III", "source": "MIL-F-8785C 3.1.1 Class III, large, heavy, low-to-"
                                       "medium manoeuvrability (heavy transport); A320 MTOW "
                                       "about 78 t -- unverified here"},
    "B747": {"class": "III", "source": "MIL-F-8785C 3.1.1 Class III, large, heavy (heavy "
                                       "transport); B747 MTOW about 380 t -- unverified here"},
    "p51d": {"class": "IV", "source": "MIL-F-8785C 3.1.1 Class IV, high-manoeuvrability "
                                      "(fighter); P-51D -- unverified here"},
    "A4": {"class": "IV", "source": "MIL-F-8785C 3.1.1 Class IV, high-manoeuvrability "
                                    "(attack / fighter); A-4 Skyhawk -- unverified here"},
    "f16": {"class": "IV", "source": "MIL-F-8785C 3.1.1 Class IV, high-manoeuvrability "
                                     "(fighter); F-16 -- unverified here"},
}

CLASSES = ("I", "II", "III", "IV")
CATEGORIES = ("A", "B", "C")

REFERENCES = (
    "MIL-F-8785C, Military Specification: Flying Qualities of Piloted Airplanes, "
    "5 November 1980 (sections 3.2.1.2, 3.2.2.1.1, 3.2.2.1.2, 3.3.1.1, 3.3.1.2, 3.3.1.3; "
    "Tables IV, VI, VII, VIII; Figures 1-3)",
    "MIL-STD-1797A, Flying Qualities of Piloted Aircraft, 30 January 1990 "
    "(the successor; carries the same numbers where cited here)",
    "MIL-HDBK-1797, Flying Qualities of Piloted Aircraft (handbook to the standard)",
)

UNVERIFIED = ("unverified here: encoded from memory; the specification is not reachable "
              "from this container (network limited to the terrain buckets and sourceforge)")


def _classes(*names: str) -> Tuple[str, ...]:
    return tuple(names)


#: The bands. Each table: reference, section, confidence, and the levels.
#: A level's entry is what the mode must satisfy to be AT LEAST that level.
BANDS: Dict[str, Dict[str, Any]] = {
    "short_period_damping": {
        "reference": "MIL-F-8785C 3.2.2.1.2, Table IV",
        "quantity": "zeta_sp", "confidence": "high", "verification": UNVERIFIED,
        # category -> level -> (min zeta, max zeta)
        "levels": {
            "A": {1: (0.35, 1.30), 2: (0.25, 2.00), 3: (0.15, math.inf)},
            "B": {1: (0.30, 2.00), 2: (0.20, 2.00), 3: (0.15, math.inf)},
            "C": {1: (0.35, 1.30), 2: (0.25, 2.00), 3: (0.15, math.inf)},
        },
    },
    "short_period_frequency": {
        "reference": "MIL-F-8785C 3.2.2.1.1, Figures 1-3 (omega_sp^2/(n/alpha) bounds "
                     "and the omega_sp floor)",
        "quantity": "CAP = omega_sp^2 / (n/alpha), 1/s^2 per g; omega_sp, rad/s",
        "confidence": "moderate: the figure boundaries from memory", "verification": UNVERIFIED,
        # category -> level -> (min CAP, max CAP, min omega_sp)
        "levels": {
            "A": {1: (0.28, 3.6, 1.0), 2: (0.16, 10.0, 0.6), 3: (0.16, math.inf, 0.0)},
            "B": {1: (0.085, 3.6, 0.0), 2: (0.038, 10.0, 0.0), 3: (0.038, math.inf, 0.0)},
            "C": {1: (0.16, 3.6, 0.7), 2: (0.096, 10.0, 0.4), 3: (0.096, math.inf, 0.0)},
        },
    },
    "phugoid": {
        "reference": "MIL-F-8785C 3.2.1.2",
        "quantity": "zeta_p; for an unstable phugoid the time to double, s",
        "confidence": "high", "verification": UNVERIFIED,
        # level -> min zeta (Levels 1, 2); Level 3 -> min time to double, s
        "levels": {1: {"min_zeta": 0.04}, 2: {"min_zeta": 0.0}, 3: {"min_time_to_double_s": 55.0}},
    },
    "dutch_roll": {
        "reference": "MIL-F-8785C 3.3.1.1, Table VI (the general rows; the CO/GA "
                     "Category A row is not applied)",
        "quantity": "min zeta_d, min zeta_d*omega_d (rad/s), min omega_d (rad/s)",
        "confidence": "high", "verification": UNVERIFIED,
        # level -> category -> [(classes, (min zeta, min zeta*omega, min omega)), ...]
        "levels": {
            1: {"A": [(_classes("I", "IV"), (0.19, 0.35, 1.0)),
                      (_classes("II", "III"), (0.19, 0.35, 0.4))],
                "B": [(_classes("I", "II", "III", "IV"), (0.08, 0.15, 0.4))],
                "C": [(_classes("I", "IV"), (0.08, 0.15, 1.0)),
                      (_classes("II", "III"), (0.08, 0.10, 0.4))]},
            2: {c: [(_classes("I", "II", "III", "IV"), (0.02, 0.05, 0.4))] for c in CATEGORIES},
            3: {c: [(_classes("I", "II", "III", "IV"), (0.0, 0.0, 0.4))] for c in CATEGORIES},
        },
    },
    "roll": {
        "reference": "MIL-F-8785C 3.3.1.2, Table VII",
        "quantity": "max roll-mode time constant, s",
        "confidence": "high", "verification": UNVERIFIED,
        # level -> category -> [(classes, max tau), ...]
        "levels": {
            1: {"A": [(_classes("I", "IV"), 1.0), (_classes("II", "III"), 1.4)],
                "B": [(_classes("I", "II", "III", "IV"), 1.4)],
                "C": [(_classes("I", "IV"), 1.0), (_classes("II", "III"), 1.4)]},
            2: {"A": [(_classes("I", "IV"), 1.4), (_classes("II", "III"), 3.0)],
                "B": [(_classes("I", "II", "III", "IV"), 3.0)],
                "C": [(_classes("I", "IV"), 1.4), (_classes("II", "III"), 3.0)]},
            3: {c: [(_classes("I", "II", "III", "IV"), 10.0)] for c in CATEGORIES},
        },
    },
    "spiral": {
        "reference": "MIL-F-8785C 3.3.1.3, Table VIII",
        "quantity": "min time to double amplitude, s (a stable spiral meets every level)",
        "confidence": "high", "verification": UNVERIFIED,
        # level -> category -> min time to double
        "levels": {1: {"A": 12.0, "B": 20.0, "C": 12.0},
                   2: {"A": 8.0, "B": 8.0, "C": 8.0},
                   3: {"A": 4.0, "B": 4.0, "C": 4.0}},
    },
}

#: The level reported when a mode fails even Level 3.
BELOW_LEVEL_3 = "below 3"


# -- eigenvalues to modes ------------------------------------------------------

def _pairs_and_reals(eigenvalues: np.ndarray, tol: float = 1e-9):
    """Complex-conjugate pairs (one representative each, imag > 0) sorted
    by natural frequency descending, and the real roots sorted by
    magnitude descending."""
    pairs = sorted((e for e in eigenvalues if e.imag > tol), key=lambda e: -abs(e))
    reals = sorted((float(e.real) for e in eigenvalues if abs(e.imag) <= tol),
                   key=lambda r: -abs(r))
    return pairs, reals


def _pair_mode(e: complex) -> Dict[str, Any]:
    wn = float(abs(e))
    zeta = float(-e.real / wn) if wn > 0.0 else float("nan")
    period = float(2.0 * math.pi / abs(e.imag))
    out = {"oscillatory": True, "eigenvalues": [[float(e.real), float(e.imag)],
                                                [float(e.real), -float(e.imag)]],
           "omega_n_rad_s": wn, "zeta": zeta, "period_s": period,
           "stable": bool(e.real < 0.0)}
    if e.real < 0.0:
        out["time_to_half_s"] = float(math.log(2.0) / -e.real)
    elif e.real > 0.0:
        out["time_to_double_s"] = float(math.log(2.0) / e.real)
    return out


def _real_mode(roots: Sequence[float]) -> Dict[str, Any]:
    """A non-oscillatory mode made of real roots (one or two)."""
    out: Dict[str, Any] = {"oscillatory": False,
                           "eigenvalues": [[float(r), 0.0] for r in roots],
                           "stable": all(r < 0.0 for r in roots)}
    if len(roots) == 1:
        r = float(roots[0])
        if r < 0.0:
            out["time_constant_s"] = -1.0 / r
            out["time_to_half_s"] = math.log(2.0) / -r
        elif r > 0.0:
            out["time_to_double_s"] = math.log(2.0) / r
        else:
            out["time_constant_s"] = math.inf
    return out


def longitudinal_modes(A_lon: np.ndarray) -> Dict[str, Dict[str, Any]]:
    """Short period and phugoid from the 4x4 longitudinal block."""
    eig = np.linalg.eigvals(np.asarray(A_lon, dtype=float))
    pairs, reals = _pairs_and_reals(eig)
    if len(pairs) >= 2:
        short, phugoid = _pair_mode(pairs[0]), _pair_mode(pairs[1])
    elif len(pairs) == 1:
        largest_real = abs(reals[0]) if reals else 0.0
        if abs(pairs[0]) > largest_real:
            short, phugoid = _pair_mode(pairs[0]), _real_mode(reals[:2])
        else:
            short, phugoid = _real_mode(reals[:2]), _pair_mode(pairs[0])
    else:
        short, phugoid = _real_mode(reals[:2]), _real_mode(reals[2:4])
    return {"short_period": short, "phugoid": phugoid,
            "eigenvalues": [[float(e.real), float(e.imag)] for e in eig]}


def lateral_modes(A_lat: np.ndarray) -> Dict[str, Dict[str, Any]]:
    """Dutch roll, roll and spiral from the 4x4 lateral-directional block."""
    eig = np.linalg.eigvals(np.asarray(A_lat, dtype=float))
    pairs, reals = _pairs_and_reals(eig)
    if pairs:
        dutch = _pair_mode(pairs[0])
    else:
        # No oscillation: the middle two real roots stand where the pair would be.
        dutch = _real_mode(reals[1:3]) if len(reals) >= 3 else _real_mode(reals)
        reals = [reals[0], reals[-1]] if len(reals) >= 2 else reals
    if len(pairs) >= 2:
        coupled = _pair_mode(pairs[1])
        coupled["coupled"] = True
        coupled["note"] = "roll and spiral are a coupled oscillatory pair (lateral phugoid)"
        roll, spiral = dict(coupled), dict(coupled)
    else:
        by_magnitude = sorted(reals, key=lambda r: -abs(r))
        roll = _real_mode(by_magnitude[:1]) if by_magnitude else _real_mode([])
        spiral = _real_mode(by_magnitude[-1:]) if len(by_magnitude) >= 2 else _real_mode([])
        roll["coupled"] = spiral["coupled"] = False
    return {"dutch_roll": dutch, "roll": roll, "spiral": spiral,
            "eigenvalues": [[float(e.real), float(e.imag)] for e in eig]}


def n_alpha(A_lon: np.ndarray, vt_mps: float) -> float:
    """``n/alpha`` in g per rad from the alpha-dot row: ``-V A[alpha,alpha]/g``.
    Neglects the alpha-dot and pitch-rate lift terms (stated in the record)."""
    A = np.asarray(A_lon, dtype=float)
    i = LONGITUDINAL_STATES.index("Alpha")
    return float(-vt_mps * A[i, i] / G0)


# -- the bands ---------------------------------------------------------------------

def _class_row(rows: Sequence[Tuple[Tuple[str, ...], Any]], airframe_class: str):
    for classes, value in rows:
        if airframe_class in classes:
            return value
    raise ModesError("modes.airframe_class", f"no band row for class {airframe_class!r}")


def _check_inputs(airframe_class: str, category: str) -> None:
    if airframe_class not in CLASSES:
        raise ModesError("modes.airframe_class",
                         f"class {airframe_class!r} is not one of {CLASSES}")
    if category not in CATEGORIES:
        raise ModesError("modes.airframe_class",
                         f"flight phase category {category!r} is not one of {CATEGORIES}")


def level_short_period_damping(zeta: float, category: str) -> Dict[str, Any]:
    table = BANDS["short_period_damping"]
    levels = table["levels"][category]
    level: Any = BELOW_LEVEL_3
    for n in (1, 2, 3):
        lo, hi = levels[n]
        if lo <= zeta <= hi:
            level = n
            break
    return {"level": level, "value": {"zeta": zeta},
            "band": {str(n): {"min_zeta": levels[n][0], "max_zeta": levels[n][1]} for n in (1, 2, 3)},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"]}


def level_short_period_frequency(omega_n: float, n_per_alpha: float,
                                 category: str) -> Dict[str, Any]:
    table = BANDS["short_period_frequency"]
    levels = table["levels"][category]
    cap = omega_n ** 2 / n_per_alpha if n_per_alpha > 0.0 else float("nan")
    level: Any = BELOW_LEVEL_3
    if math.isfinite(cap):
        for n in (1, 2, 3):
            lo, hi, wmin = levels[n]
            if lo <= cap <= hi and omega_n >= wmin:
                level = n
                break
    return {"level": level, "value": {"cap": cap, "omega_n_rad_s": omega_n,
                                      "n_alpha_g_per_rad": n_per_alpha},
            "band": {str(n): {"min_cap": levels[n][0], "max_cap": levels[n][1],
                              "min_omega_n_rad_s": levels[n][2]} for n in (1, 2, 3)},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"],
            "note": "n/alpha = -V A[alpha,alpha]/g from the linear model; the alpha-dot and "
                    "pitch-rate lift terms are neglected"}


def level_phugoid(mode: Dict[str, Any]) -> Dict[str, Any]:
    table = BANDS["phugoid"]
    levels = table["levels"]
    level: Any = BELOW_LEVEL_3
    if mode.get("oscillatory"):
        zeta = float(mode["zeta"])
        if zeta >= levels[1]["min_zeta"]:
            level = 1
        elif zeta >= levels[2]["min_zeta"]:
            level = 2
        elif mode.get("time_to_double_s", 0.0) >= levels[3]["min_time_to_double_s"]:
            level = 3
        value = {"zeta": zeta, "time_to_double_s": mode.get("time_to_double_s")}
    else:
        # Non-oscillatory: stable roots satisfy zeta >= 0.04 in spirit
        # (no oscillation to damp); an unstable root is graded by its
        # time to double against Level 3.
        if mode.get("stable"):
            level = 1
        else:
            unstable = [r for r, _ in mode["eigenvalues"] if r > 0.0]
            t2 = math.log(2.0) / max(unstable) if unstable else math.inf
            level = 3 if t2 >= levels[3]["min_time_to_double_s"] else BELOW_LEVEL_3
        value = {"zeta": None, "non_oscillatory": True}
    return {"level": level, "value": value,
            "band": {"1": levels[1], "2": levels[2], "3": levels[3]},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"]}


def level_dutch_roll(mode: Dict[str, Any], airframe_class: str, category: str) -> Dict[str, Any]:
    table = BANDS["dutch_roll"]
    band = {str(n): _class_row(table["levels"][n][category], airframe_class) for n in (1, 2, 3)}
    level: Any = BELOW_LEVEL_3
    if mode.get("oscillatory"):
        zeta, wn = float(mode["zeta"]), float(mode["omega_n_rad_s"])
        for n in (1, 2, 3):
            zmin, zwmin, wmin = band[str(n)]
            if zeta >= zmin and zeta * wn >= zwmin and wn >= wmin:
                level = n
                break
        value = {"zeta": zeta, "omega_n_rad_s": wn, "zeta_omega_n": zeta * wn}
    else:
        value = {"non_oscillatory": True}
        level = BELOW_LEVEL_3 if not mode.get("stable") else 3
    return {"level": level, "value": value,
            "band": {n: {"min_zeta": b[0], "min_zeta_omega_n": b[1], "min_omega_n_rad_s": b[2]}
                     for n, b in band.items()},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"]}


def level_roll(mode: Dict[str, Any], airframe_class: str, category: str) -> Dict[str, Any]:
    table = BANDS["roll"]
    band = {str(n): _class_row(table["levels"][n][category], airframe_class) for n in (1, 2, 3)}
    level: Any = BELOW_LEVEL_3
    tau = mode.get("time_constant_s")
    if tau is not None and not mode.get("coupled"):
        for n in (1, 2, 3):
            if tau <= band[str(n)]:
                level = n
                break
    return {"level": level, "value": {"time_constant_s": tau, "coupled": bool(mode.get("coupled"))},
            "band": {n: {"max_time_constant_s": b} for n, b in band.items()},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"]}


def level_spiral(mode: Dict[str, Any], category: str) -> Dict[str, Any]:
    table = BANDS["spiral"]
    band = {str(n): table["levels"][n][category] for n in (1, 2, 3)}
    level: Any = BELOW_LEVEL_3
    t2 = mode.get("time_to_double_s")
    if mode.get("coupled"):
        level = BELOW_LEVEL_3 if not mode.get("stable") else 1
    elif mode.get("stable") or t2 is None:
        level = 1
    else:
        for n in (1, 2, 3):
            if t2 >= band[str(n)]:
                level = n
                break
    return {"level": level, "value": {"time_to_double_s": t2, "stable": bool(mode.get("stable")),
                                      "time_to_half_s": mode.get("time_to_half_s")},
            "band": {n: {"min_time_to_double_s": b} for n, b in band.items()},
            "reference": table["reference"], "confidence": table["confidence"],
            "verification": table["verification"]}


def assign_levels(modes: Dict[str, Dict[str, Any]], airframe_class: str, category: str,
                  n_per_alpha: float) -> Dict[str, Dict[str, Any]]:
    """Every mode graded against its band for the class and category."""
    _check_inputs(airframe_class, category)
    sp = modes["short_period"]
    out: Dict[str, Dict[str, Any]] = {}
    if sp.get("oscillatory"):
        out["short_period_damping"] = level_short_period_damping(float(sp["zeta"]), category)
        out["short_period_frequency"] = level_short_period_frequency(
            float(sp["omega_n_rad_s"]), n_per_alpha, category)
    else:
        note = {"level": BELOW_LEVEL_3 if not sp.get("stable") else None,
                "value": {"non_oscillatory": True},
                "note": "the short period is not oscillatory here; Table IV and the CAP "
                        "figures grade an oscillatory pair and are not applied",
                "reference": BANDS["short_period_damping"]["reference"]}
        out["short_period_damping"] = dict(note)
        out["short_period_frequency"] = dict(note, reference=BANDS["short_period_frequency"]["reference"])
    out["phugoid"] = level_phugoid(modes["phugoid"])
    out["dutch_roll"] = level_dutch_roll(modes["dutch_roll"], airframe_class, category)
    out["roll"] = level_roll(modes["roll"], airframe_class, category)
    out["spiral"] = level_spiral(modes["spiral"], category)
    return out


def worst_level(levels: Dict[str, Dict[str, Any]]) -> Any:
    """The overall level: the worst of the graded modes (None ignored)."""
    graded = [v.get("level") for v in levels.values() if v.get("level") is not None]
    if not graded:
        return None
    if any(g == BELOW_LEVEL_3 for g in graded):
        return BELOW_LEVEL_3
    return max(int(g) for g in graded)


# -- the analysis ------------------------------------------------------------------

def airframe_class_of(aircraft: str) -> Dict[str, str]:
    entry = AIRFRAME_CLASS.get(str(aircraft))
    if entry is None:
        raise ModesError("modes.airframe_class",
                         f"no MIL-F-8785C class is stated for airframe {aircraft!r}; "
                         f"the bands depend on it and none is guessed")
    return entry


@dataclass(frozen=True)
class ModesResult:
    """One modal analysis: a result record, not an AppliedVariable."""

    aircraft: str
    airframe_class: str
    class_source: str
    category: str
    trim: Dict[str, float]
    model: LinearModel
    longitudinal: Dict[str, Any]
    lateral: Dict[str, Any]
    levels: Dict[str, Dict[str, Any]]
    n_alpha_g_per_rad: float

    @property
    def modes(self) -> Dict[str, Dict[str, Any]]:
        return {"short_period": self.longitudinal["short_period"],
                "phugoid": self.longitudinal["phugoid"],
                "dutch_roll": self.lateral["dutch_roll"],
                "roll": self.lateral["roll"], "spiral": self.lateral["spiral"]}

    @property
    def overall_level(self) -> Any:
        return worst_level(self.levels)

    def to_dict(self) -> Dict[str, Any]:
        full_eig = np.linalg.eigvals(self.model.A_full)
        return {
            "modes_version": MODES_VERSION,
            "kind": "result",
            "kind_note": "a result of the trimmed state, not an AppliedVariable: nothing "
                         "is applied to the run; no property is written; no trajectory changes",
            "attempted": True,
            "aircraft": self.aircraft,
            "airframe_class": self.airframe_class,
            "airframe_class_source": self.class_source,
            "flight_phase_category": self.category,
            "trim": dict(self.trim),
            "linearization": self.model.to_dict(),
            "eigenvalues": {
                "longitudinal": self.longitudinal["eigenvalues"],
                "lateral": self.lateral["eigenvalues"],
                "full": [[float(e.real), float(e.imag)] for e in full_eig],
            },
            "modes": self.modes,
            "n_alpha_g_per_rad": self.n_alpha_g_per_rad,
            "levels": self.levels,
            "overall_level": self.overall_level,
            "bands": bands_block(self.airframe_class, self.category),
            "references": list(REFERENCES),
            "refusals": [] if self.model.residual is None or self.model.residual.ok
                        else ["modes.residual"],
            "not_claimed": [
                "a handling-qualities statement about the aeroplane: the model is stock "
                "JSBSim with no validated data (docs/VALIDITY.md), so a level describes "
                "the model",
                "the band numbers as re-checked against the specification here "
                "(every table is marked unverified here with its confidence)",
                "the pilot-in-the-loop criteria (bandwidth, time delay, PIO)",
                "the engine, altitude, heading and position couplings (left out of the "
                "classical 4x4 blocks; carried in the full matrix)",
                "the Category A combat (CO/GA) Dutch-roll row",
            ],
        }


def bands_block(airframe_class: str, category: str) -> Dict[str, Any]:
    """The band rows that apply to this class and category, with references."""
    _check_inputs(airframe_class, category)
    dr = BANDS["dutch_roll"]
    roll = BANDS["roll"]
    return {
        "short_period_damping": {"reference": BANDS["short_period_damping"]["reference"],
                                 "levels": {str(n): list(v) for n, v in
                                            BANDS["short_period_damping"]["levels"][category].items()},
                                 "confidence": BANDS["short_period_damping"]["confidence"]},
        "short_period_frequency": {"reference": BANDS["short_period_frequency"]["reference"],
                                   "levels": {str(n): list(v) for n, v in
                                              BANDS["short_period_frequency"]["levels"][category].items()},
                                   "confidence": BANDS["short_period_frequency"]["confidence"]},
        "phugoid": {"reference": BANDS["phugoid"]["reference"],
                    "levels": {str(n): v for n, v in BANDS["phugoid"]["levels"].items()},
                    "confidence": BANDS["phugoid"]["confidence"]},
        "dutch_roll": {"reference": dr["reference"],
                       "levels": {str(n): list(_class_row(dr["levels"][n][category], airframe_class))
                                  for n in (1, 2, 3)},
                       "confidence": dr["confidence"]},
        "roll": {"reference": roll["reference"],
                 "levels": {str(n): _class_row(roll["levels"][n][category], airframe_class)
                            for n in (1, 2, 3)},
                 "confidence": roll["confidence"]},
        "spiral": {"reference": BANDS["spiral"]["reference"],
                   "levels": {str(n): BANDS["spiral"]["levels"][n][category] for n in (1, 2, 3)},
                   "confidence": BANDS["spiral"]["confidence"]},
        "verification": UNVERIFIED,
    }


def analyse(fdm, aircraft: str, category: str = "B",
            model: Optional[LinearModel] = None) -> ModesResult:
    """Linearise a trimmed FDM (its own instance) and grade the modes.

    ``aircraft`` is the configured airframe name the class is looked up
    by. ``model`` may be passed when the linearisation was done already.
    Refuses by name: ``modes.airframe_class``, and the linearisation's
    ``modes.untrimmed`` / ``modes.linearization`` / ``modes.residual``.
    """
    entry = airframe_class_of(aircraft)
    _check_inputs(entry["class"], category)
    if model is None:
        model = linearize(fdm)
    vt_mps = float(model.x0[model.index("Vt")]) * FT_TO_M
    trim = {
        "vt_mps": vt_mps,
        "alpha_rad": float(model.x0[model.index("Alpha")]),
        "theta_rad": float(model.x0[model.index("Theta")]),
        "altitude_m": float(model.x0[model.index("Alt")]) * FT_TO_M if "Alt" in model.state_names else float("nan"),
    }
    lon = longitudinal_modes(model.A_lon)
    lat = lateral_modes(model.A_lat)
    na = n_alpha(model.A_lon, vt_mps)
    levels = assign_levels({**lon, **lat}, entry["class"], category, na)
    return ModesResult(aircraft=str(aircraft), airframe_class=entry["class"],
                       class_source=entry["source"], category=category, trim=trim,
                       model=model, longitudinal=lon, lateral=lat, levels=levels,
                       n_alpha_g_per_rad=na)


def analyse_spec(spec, category: str = "B") -> ModesResult:
    """Build and trim a FRESH FDM from the spec (the run's own is never
    linearised: the disturbance is measured in :mod:`core.fdm.linearize`)
    and analyse it."""
    from ..scenario.runner import configure_from_spec  # lazy: the runner imports this module

    fdm = configure_from_spec(spec)
    return analyse(fdm, str(spec.aircraft.value), category=category)


def modes_block(spec, category: str = "B") -> Dict[str, Any]:
    """The manifest's ``modes`` block: the result, or a record of the
    refusal by name. A refused analysis never aborts a run -- it is a
    result about the run, so the block says which name refused and why."""
    try:
        return analyse_spec(spec, category=category).to_dict()
    except ModesError as exc:
        return {"modes_version": MODES_VERSION, "kind": "result", "attempted": False,
                "refusal": exc.constraint, "reason": exc.message,
                "aircraft": str(spec.aircraft.value)}
