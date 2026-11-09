"""Humidity-gated condensation on the airframe (visual overhaul, module
"condensation-solver"): the Python twin of FlightSimCondensation.cpp.

BEAUTY ONLY. Nothing here touches the flight model: every input is a read
of the FDM's own state (or the card's stated humidity), and the output is
an opacity per site that drives a translucent, beauty-only actor the label
captures never draw.

The test, per site: take the air the airframe accelerates, find its local
pressure ``p_l`` and (isentropic, dry adiabat) temperature

    T_l = T * (p_l / p) ** 0.2857

and compare the vapour the free stream carries with what the local air can
hold:

    dq = q_v(RH, T, p) - q_sat(T_l, p_l)          (mixing ratios, g/kg)
    dq_visible = q_v - q_sat(T_l + OnsetCoolingK, p_l)
    opacity = clamp(OpacityPerGkg * dq_visible, 0, 1)   (0 below VisibleMinGkg)

``dq`` is the equilibrium condensate (recorded); ``dq_visible`` asks the air
to cool OnsetCoolingK below its dew point first (droplet growth lag).

``q_v`` is conserved through the expansion (no water is added or lost
before it condenses). The saturation vapour pressure is the Magnus form
core/environment/atmosphere.py already transcribes from JSBSim
(``saturated_vapour_pressure_psf``), over liquid water at every
temperature (no ice phase: stated, not modelled).

The sites (each self-gating: dry air or high, cold air holds too little
water for any expansion to show):

* ``tip`` -- the wingtip vortex cores. Elliptic-loading root circulation
  ``Gamma = Nz W / (rho V b pi/4)``, a Lamb-Oseen core of radius
  ``rc = CoreRadiusSpanFraction * b`` (rc = the radius of PEAK swirl), whose
  centre pressure deficit is ``dp = 0.87 rho Gamma^2 / (4 pi^2 rc^2)``
  (0.87 = ln 2 x 1.1209^2: the Lamb-Oseen integral with rc taken at the
  peak-velocity radius rather than the Gaussian width).
* ``sheet`` -- the upper-wing suction sheet. ``CL = Nz W / (qbar S)``,
  ``Cp_min = -(SheetCpMinAtZeroLift + CpMinPerCL * CL)`` (the spec's
  zero-lift term was 1; measured too eager, see the constant), ``p_l = p (1 + 0.7 M^2 Cp_min)``
  (``qbar = 0.7 p M^2`` for gamma = 1.4: the definition of Cp, no
  compressibility rule is applied to Cp_min itself).
* ``lex`` -- the leading-edge-extension vortex (J-11 class, LexEnabled):
  above ``LexAlphaOnsetDeg`` its core suction grows as
  ``Cp = -LexCpPerDeg * (alpha - onset)``, ``p_l`` as for the sheet.
* ``cone`` -- the transonic vapour cone, only for
  ``ConeMachMin <= M <= ConeMachMax``: the flow over the body reaches
  ``ConeLocalMach``; ``T_l / T = (1 + 0.2 M^2) / (1 + 0.2 M_l^2)`` (constant
  total temperature) and ``p_l / p = (T_l / T) ** 3.5``. The cloud ends at
  the recompression shock (the cone's aft edge, drawn sharp).

UNCALIBRATED: every CONDENSATION_DEFAULTS value, the 0.87 Lamb-Oseen factor
and the compressible Cp form above are engineering approximations, set by
the probe renders docs/visual/PROBE_LOG.md "## condensation-solver" names
(a humid low pass at M 0.95; a 5 g pull-up in the forest rain scene).
Droplet growth time (the cloud's onset lag) is not modelled; VisibleMinGkg
stands in for it and for a thin cloud's invisibility.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Tuple

from core.environment import atmosphere as atm

#: The C++ twin, ue/.../Private/FlightSimCondensation.cpp, reads these by
#: name from look_manifest.json constants.condensation (aircraft_look.py
#: copies them there); its fallbacks are these numbers (pinned by test).
CONDENSATION_DEFAULTS: Dict[str, float] = {
    # -- the physics (the spec's set) --------------------------------------
    "CpMinPerCL": 1.2,
    "CoreRadiusSpanFraction": 0.03,
    "LexAlphaOnsetDeg": 12.0,
    "ConeLocalMach": 1.15,
    "ConeMachMin": 0.85,
    "ConeMachMax": 1.05,
    "OpacityPerGkg": 0.6,
    "LifetimeS": 1.2,
    # -- the physics, beyond it ---------------------------------------------
    # Below this condensed mixing ratio nothing is drawn (droplet growth
    # time and a thin cloud's invisibility, not modelled otherwise).
    "VisibleMinGkg": 0.05,
    # The local air must cool this far below its dew point before the cloud
    # shows: the opacity uses q_sat(T_l + OnsetCoolingK, p_l). A stand-in for
    # droplet growth time over a millisecond-scale transit (not modelled).
    "OnsetCoolingK": 6.0,
    # The sheet's zero-lift suction: Cp_min = -(SheetCpMinAtZeroLift +
    # CpMinPerCL CL). The spec wrote 1.0 here; the twin measured that 1.0
    # makes the sheet fully opaque at 1 g in any humid low-level air (as
    # strong as a 5 g tip core), so the default is a thin wing's ~0.3.
    "SheetCpMinAtZeroLift": 0.3,
    "LexCpPerDeg": 0.12,
    # -- the geometry (FlightSimCondensation.cpp places the sites) ----------
    # 1 on an airframe with leading-edge extensions (its look config says so).
    "LexEnabled": 0.0,
    # The LEX apex, metres aft of the nose vertex, out from the centreline
    # (mirrored) and up from the nose vertex; the vortex tube's length.
    "LexAftOfNoseM": 6.0,
    "LexSpanM": 1.2,
    "LexUpM": 0.2,
    "LexLengthM": 6.0,
    # The cone: from the max-cross-section station aft to the shock, this
    # fraction of the body's length.
    "ConeLengthBodyFraction": 0.18,
    # The sheet: span stations (fractions of the semi-span) and the chord
    # fraction from the leading edge it covers.
    "SheetSpanStartFraction": 0.35,
    "SheetSpanEndFraction": 0.9,
    "SheetChordFraction": 0.55,
    # The tip vortex ribbons.
    "TipStartWidthM": 0.3,
    "TipSpreadMPerS": 1.2,
}

SITES: Tuple[str, ...] = ("tip", "sheet", "lex", "cone")
MODEL = "isentropic+Magnus"
#: Lamb-Oseen centre deficit with rc at the peak-swirl radius
#: (ln 2 x 1.12091^2 = 0.8709). UNCALIBRATED for a rolled-up tip vortex.
LAMB_OSEEN_CORE_FACTOR = 0.87
#: R / cp for dry air (gamma 1.4).
POISSON_EXPONENT = 0.2857
#: R_dry / R_water from the JSBSim constants atmosphere.py transcribes.
EPSILON = atm.R_DRY / atm.R_WATER
CALIBRATION = ("UNCALIBRATED: every CONDENSATION_DEFAULTS value, the 0.87 Lamb-Oseen "
               "factor and the compressible Cp form are engineering approximations; "
               "set by probe render on the render machine")
LABEL_CONVENTION = "translucent media: not in mask, class or depth (trail convention)"

# JSBSim unit factors (the FDM reads arrive in these).
PA_PER_PSF = 47.880258980
KGM3_PER_SLUGFT3 = 515.378818
M_PER_FT = 0.3048
MPS_PER_KT = 0.514444
N_PER_LBF = 4.448221615


def constants(overrides: Optional[Mapping[str, float]] = None) -> Dict[str, float]:
    out = dict(CONDENSATION_DEFAULTS)
    if overrides:
        unknown = set(overrides) - set(out)
        if unknown:
            raise ValueError(f"unknown condensation constants {sorted(unknown)}")
        out.update({k: float(v) for k, v in overrides.items()})
    return out


# -- thermodynamics -----------------------------------------------------------

def saturation_vapour_pressure_pa(t_k: float) -> float:
    """atmosphere.py's Magnus form (JSBSim's), in pascals."""
    return atm.saturated_vapour_pressure_psf(t_k * atm.R_PER_K) * atm.JSBSIM_PSF_TO_PA


def mixing_ratio(e_pa: float, p_pa: float) -> float:
    """kg water per kg dry air; a vapour pressure at or above the total
    pressure saturates everything (returned as infinity)."""
    if e_pa >= p_pa:
        return math.inf
    return EPSILON * e_pa / (p_pa - e_pa)


def vapour_mixing_ratio(rh_pct: float, t_k: float, p_pa: float) -> float:
    return mixing_ratio(max(rh_pct, 0.0) / 100.0 * saturation_vapour_pressure_pa(t_k), p_pa)


def saturation_mixing_ratio(t_k: float, p_pa: float) -> float:
    return mixing_ratio(saturation_vapour_pressure_pa(t_k), p_pa)


def isentropic_temperature(t_k: float, p_pa: float, p_local_pa: float) -> float:
    return t_k * (p_local_pa / p_pa) ** POISSON_EXPONENT


def condensed_gkg(rh_pct: float, t_k: float, p_pa: float,
                  t_local_k: float, p_local_pa: float) -> float:
    """dq = q_v - q_sat(T_l, p_l), g/kg (negative: still unsaturated)."""
    return 1000.0 * (vapour_mixing_ratio(rh_pct, t_k, p_pa)
                     - saturation_mixing_ratio(t_local_k, p_local_pa))


# -- the sites ----------------------------------------------------------------

def _ok(x: Any, positive: bool = True) -> bool:
    if x is None:
        return False
    try:
        v = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and (v > 0.0 if positive else True)


#: The state keys (SI) each site needs; a missing or non-finite one (or a
#: non-positive one where it must be positive) drops the site.
SITE_INPUTS: Dict[str, Tuple[str, ...]] = {
    "tip": ("t_k", "p_pa", "nz", "weight_n", "rho_kgm3", "v_mps", "b_m"),
    "sheet": ("t_k", "p_pa", "nz", "weight_n", "qbar_pa", "s_m2", "mach"),
    "lex": ("t_k", "p_pa", "alpha_deg", "mach"),
    "cone": ("t_k", "p_pa", "mach"),
}
SIGNED_INPUTS = ("nz", "alpha_deg")
#: The local pressure never falls below this fraction of ambient (a guard,
#: not physics: the vortex formula has no floor of its own).
MIN_PRESSURE_RATIO = 0.05


def missing_inputs(site: str, state: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(k for k in SITE_INPUTS[site]
                 if not _ok(state.get(k), positive=k not in SIGNED_INPUTS))


def site_local(site: str, state: Mapping[str, Any],
               c: Mapping[str, float]) -> Optional[Tuple[float, float]]:
    """(p_l Pa, T_l K) at a site, or None when the site does not apply
    (gated off, or an input absent)."""
    if missing_inputs(site, state):
        return None
    t, p = float(state["t_k"]), float(state["p_pa"])
    if site == "tip":
        nz, w, rho = abs(float(state["nz"])), float(state["weight_n"]), float(state["rho_kgm3"])
        v, b = float(state["v_mps"]), float(state["b_m"])
        gamma = nz * w / (rho * v * b * math.pi / 4.0)
        rc = c["CoreRadiusSpanFraction"] * b
        dp = LAMB_OSEEN_CORE_FACTOR * rho * gamma ** 2 / (4.0 * math.pi ** 2 * rc ** 2)
        p_l = max(p - dp, MIN_PRESSURE_RATIO * p)
        return p_l, isentropic_temperature(t, p, p_l)
    if site in ("sheet", "lex"):
        m = float(state["mach"])
        if site == "sheet":
            cl = abs(float(state["nz"])) * float(state["weight_n"]) / (
                float(state["qbar_pa"]) * float(state["s_m2"]))
            cp = -(c["SheetCpMinAtZeroLift"] + c["CpMinPerCL"] * cl)
        else:
            if c["LexEnabled"] < 0.5:
                return None
            excess = float(state["alpha_deg"]) - c["LexAlphaOnsetDeg"]
            if excess <= 0.0:
                return None
            cp = -c["LexCpPerDeg"] * excess
        p_l = max(p * (1.0 + 0.7 * m * m * cp), MIN_PRESSURE_RATIO * p)
        return p_l, isentropic_temperature(t, p, p_l)
    if site == "cone":
        m = float(state["mach"])
        if not (c["ConeMachMin"] <= m <= c["ConeMachMax"]):
            return None
        ml = c["ConeLocalMach"]
        ratio = (1.0 + 0.2 * m * m) / (1.0 + 0.2 * ml * ml)
        return p * ratio ** 3.5, t * ratio
    raise ValueError(f"unknown site {site!r}; one of {SITES}")


def site_dq(site: str, state: Mapping[str, Any],
            overrides: Optional[Mapping[str, float]] = None,
            visible: bool = False) -> Optional[float]:
    """The condensed mixing ratio at a site, g/kg (negative = unsaturated),
    or None when the site does not apply or the humidity is unknown.
    ``visible`` evaluates the saturation OnsetCoolingK warmer (the onset)."""
    c = constants(overrides)
    if not _ok(state.get("rh_pct"), positive=False):
        return None
    local = site_local(site, state, c)
    if local is None:
        return None
    p_l, t_l = local
    if visible:
        t_l += c["OnsetCoolingK"]
    return condensed_gkg(float(state["rh_pct"]), float(state["t_k"]), float(state["p_pa"]), t_l, p_l)


def opacity(dq_gkg: Optional[float], overrides: Optional[Mapping[str, float]] = None) -> float:
    """clamp(OpacityPerGkg * dq, 0, 1); pass the VISIBLE dq (site_dq(...,
    visible=True)). Below VisibleMinGkg, nothing."""
    c = constants(overrides)
    if dq_gkg is None or not math.isfinite(dq_gkg) or dq_gkg < c["VisibleMinGkg"]:
        return 0.0
    return min(max(c["OpacityPerGkg"] * dq_gkg, 0.0), 1.0)


def solve(state: Mapping[str, Any],
          overrides: Optional[Mapping[str, float]] = None) -> Dict[str, Dict[str, Any]]:
    """Every site's {dq_gkg, opacity}, plus 'dropped' (the absent inputs)
    where a site could not be evaluated -- the shape of render.json
    aircraft_look.condensation.per_frame[].sites."""
    out: Dict[str, Dict[str, Any]] = {}
    for site in SITES:
        dq = site_dq(site, state, overrides)
        seen = site_dq(site, state, overrides, visible=True)
        row: Dict[str, Any] = {"dq_gkg": dq, "dq_visible_gkg": seen,
                               "opacity": opacity(seen, overrides)}
        missing = missing_inputs(site, state)
        if missing:
            row["dropped"] = list(missing)
        out[site] = row
    return out


def state_from_fdm(props: Mapping[str, Any], rh_pct: Optional[float]) -> Dict[str, Optional[float]]:
    """The SI state from JSBSim property reads (the names the C++ reads)."""
    def g(name: str, scale: float = 1.0) -> Optional[float]:
        v = props.get(name)
        return None if v is None else float(v) * scale
    return {
        "nz": g("accelerations/Nz"),
        "t_k": g("atmosphere/T-R", 1.0 / atm.R_PER_K),
        "p_pa": g("atmosphere/P-psf", PA_PER_PSF),
        "rho_kgm3": g("atmosphere/rho-slugs_ft3", KGM3_PER_SLUGFT3),
        "mach": g("velocities/mach"),
        "alpha_deg": g("aero/alpha-deg"),
        "qbar_pa": g("aero/qbar-psf", PA_PER_PSF),
        "v_mps": g("velocities/vtrue-kts", MPS_PER_KT),
        "b_m": g("metrics/bw-ft", M_PER_FT),
        "s_m2": g("metrics/Sw-sqft", M_PER_FT ** 2),
        "weight_n": g("inertia/weight-lbs", N_PER_LBF),
        "rh_pct": rh_pct,
    }


#: The FDM properties the C++ reads (physics unchanged: reads only).
FDM_READS = ("accelerations/Nz", "atmosphere/T-R", "atmosphere/P-psf",
             "atmosphere/rho-slugs_ft3", "velocities/mach", "aero/alpha-deg",
             "aero/qbar-psf", "velocities/vtrue-kts", "metrics/bw-ft",
             "metrics/Sw-sqft", "inertia/weight-lbs", "atmosphere/RH")
