"""The wake-vortex pair: a Burnham-Hallock pair trailed by a generating
aircraft ahead and above the own ship, delivered through JSBSim's gust
channel and the rotational-gust injection (ADVANCEMENTS_BLUEPRINT section
1, work item P7; needs P2's ``gust_rotation`` injection and P6's
``GustProvider`` + stack sum).

The model, stated
-----------------
The generator (weight W, span b, speed V, in air of density rho) trails a
pair of counter-rotating vortices of initial circulation

    Gamma_0 = W / (rho V b_0),        b_0 = pi b / 4   (elliptic loading)

at lateral separation ``b_0`` (the pair's centre is the generator's
track), descending at their mutual induction speed ``w_0 = Gamma_0 / (2
pi b_0)``. Each vortex has the Burnham-Hallock tangential profile (1982)

    V(r) = Gamma / (2 pi r) * r^2 / (r^2 + r_c^2)

with the core radius ``r_c = 0.035 b`` (Proctor's convention, a STATED
choice: the measured cores of large aircraft lie between 0.02 and 0.05
b, and the number chosen decides the peak swirl). The pair's velocity at
a point is the sum of the two profiles; a purely azimuthal axisymmetric
field is divergence-free, so the sum is too (measured numerically in
tests/test_wake.py). Sign conventions of the WAKE FRAME: x along the
generator's heading, y to the right, z UP for the field arithmetic (the
delivered ``w`` is NED down, ``w_down = -w_up``); seen from behind, the
starboard vortex (y = +b_0/2) turns counter-clockwise and the port one
clockwise, so the air between them moves down and the air outside them
up. The pair induces no axial velocity: ``u`` is identically 0.

The own ship meets the pair on a stated geometry: its CG sits
``lateral_offset_m`` to the right of the pair's centreline and
``vertical_offset_m`` above it at the run's first step, and the wake's
age there is ``separation_s`` (the generator passed that point that
many seconds earlier; the age then evolves as ``separation_s + t -
x_along / V_g`` as the own ship moves along the track -- constant when
both fly at the same speed) or a held ``age_s``. The generator is placed
``V_g x age_0`` ahead along the own ship's initial heading and ``w_0 x
age_0`` above the pair (the pair's descent at its initial speed, held
constant: a stated choice), which is the ``wake_generator`` track
core/capture/poses.py draws. The generator's speed is the spec's
``generator_speed_kt`` or, unstated, the own ship's initial true
airspeed.

The translational part of the field at the own ship's CG goes into
``atmosphere/gust-*-fps`` through the stack's sum (P6: written every
step, zero included, read back before the next write). The rotational
part is the uniform-lift strip-theory equivalent roll rate

    p_eq = (12 / b^3) * integral_{-b/2}^{b/2} w_up(y) y dy

over the OWN span (32-point Gauss-Legendre; ``w_up`` the upwash at the
span station, the wing taken level: a station at y moving down at p y
when rolling at p is what an upwash of p y is equivalent to, so a
linear upwash p y gives exactly p and a uniform one gives 0), delivered
into ``gust/p-equivalent-rad_sec``, which P2's injection sums into the
ROLL axis's roll-damping term (Clp < 0: a positive p_eq rolls the
aircraft left, which is what an upwash on the right wing does). The
rolling-moment coefficient ratio

    RCR = |Clp p_eq b / (2 V)| / (|Clda| delta_a,max)

is recorded where the airframe's ROLL axis states ``Clp`` and the
aileron term as plain values and its FCS states the aileron range (the
c172p does; the B747's aileron term is a Mach table and the ratio is
recorded absent, said so).

Decay: ``none`` holds ``Gamma_0`` (the age is recorded either way);
``sarpkaya`` takes the non-dimensional eddy dissipation rate ``eps*``
and Brunt-Vaisala frequency ``N*`` as DECLARED inputs (Sarpkaya, J.
Aircraft 37(1), 2000 [unverified here]: T = t w_0 / b_0, and the demise
time from the fit ``eps* T_d^(3/4) = 0.7475`` as remembered from
Sarpkaya 1998 / 2000, so ``T_d = (0.7475 / eps*)^(4/3)``); the
circulation history between T = 0 and T_d is taken LINEAR to demise (a
stated simplification: the paper's smooth curve is not reproduced
here), and a stated ``N* > 0`` bounds the demise at a quarter buoyancy
period ``pi / (2 N*)`` (a stated bound, not the paper's stratified
curve). A wake of negative age (the generator not yet past) has no
circulation.

Refusals by name (``WakeError.constraint``; the same list the validator
renders as Violations, through one function :func:`problems`):
``wake.generator`` (a generator that is not a configured airframe, or
one whose model states no span or no weight), ``wake.geometry`` (an
offset or speed that is not a number, neither or both of separation and
age, a negative age), ``wake.model`` (a decay model other than none or
sarpkaya), ``wake.decay`` (sarpkaya asked with eps* missing or outside
0 < eps* <= 1, or N* outside 0..1). A stated eps* or N* beside the
``none`` model is carried, not applied, and recorded as unread (P6's
uniform-kind precedent); a stated block with no generator attaches no
wake and the runner records the unread fields in the stack's notes.

NOT claimed: a stated core radius (the choice of 0.035 b decides the
peak swirl); no Crow instability, no vortex linking, no ground effect,
no stratification-dependent decay unless parameterised through N* (and
then only the stated bound); the pair's descent is w_0 x age with the
initial circulation; the field is frozen along a straight track (the
generator flew the own ship's initial heading at one speed); a
strip-theory roll moment only (uniform lift, level wing, no tail, no
yaw or pitch moment, no Clr coupling); the Sarpkaya constants are a
transcription from memory; the host port (FlightSimWake.h/.cpp, P9) and
its selftest against the card's vectors are a Windows step; nothing
here is validated against a measured encounter.
"""

from __future__ import annotations

import contextlib
import io
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..fdm import units as u
from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from ..scenario.blocks import WAKE_DECAY_MODELS, WAKE_STANDARDS, configured_airframes
from .base import GustProvider, OwnShipState, Position, Term, WindNED

#: r_c = 0.035 b -- Proctor's convention for the core radius (a stated choice).
CORE_RADIUS_FACTOR = 0.035
#: b_0 = pi b / 4 -- the vortex spacing of an elliptically loaded wing.
B0_FACTOR = math.pi / 4.0
#: The strip-theory integral is taken by Gauss-Legendre quadrature of this order.
GL_POINTS = 32
#: The decay models the block may name (core/scenario/blocks.py: the spec's vocabulary).
DECAY_MODELS = WAKE_DECAY_MODELS
#: Sarpkaya's demise-time fit: eps* T_d^(3/4) = 0.7475 [from memory, unverified here].
SARPKAYA_DEMISE_CONSTANT = 0.7475
#: The declared-input ranges (dimensionless; Sarpkaya's figures span eps* ~ 0.01..1).
EPS_STAR_RANGE = (0.0, 1.0)      # 0 excluded (a demise time needs a dissipation rate)
N_STAR_RANGE = (0.0, 1.0)
#: Flat-earth metres per degree of latitude (the runner's own placement rule
#: for the severe-weather features, core/scenario/runner.py).
METRES_PER_DEGREE = 111_320.0
#: The one property the rotational gust goes to (P2's injection).
P_EQUIVALENT_PROPERTY = "gust/p-equivalent-rad_sec"
GUST_PROPERTIES = ("atmosphere/gust-north-fps", "atmosphere/gust-east-fps",
                   "atmosphere/gust-down-fps")
#: The XML injection a stated wake needs on the own airframe.
INJECTIONS = ("gust_rotation",)
#: The recorder columns (core/scenario/runner.py records them through
#: Recorder ``extra`` from the provider's last evaluation, 0 without one):
#: the wake velocity at the own CG in the wake frame (u along the axis,
#: identically 0; v to the right; w DOWN, the NED sign the gust channel
#: carries), the equivalent roll rate, the circulation at the age, the
#: age, the own CG's offsets from the pair's centre, and the RCR (0 where
#: the aileron term is not readable, said in the record).
TELEMETRY_COLUMNS = ("wake_u_mps", "wake_v_mps", "wake_w_mps", "wake_p_eq_rad_s",
                     "wake_gamma_m2_s", "wake_age_s", "wake_lateral_m", "wake_vertical_m",
                     "wake_rcr")
#: The card block's keys, in the fixed order the host reads (refused
#: ``card.wake`` otherwise), and each selftest vector's.
CARD_KEYS = ("generator", "gamma_0", "b_0", "r_c", "decay", "geometry", "selftest")
SELFTEST_KEYS = ("y_m", "z_m", "age_s", "u_mps", "v_mps", "w_mps", "p_eq_rad_s")
SELFTEST_COUNT = 5
#: The rate floor the in-run null test grades against (0.1 deg/s, the
#: branch's null floor for a rate channel, in rad/s: core/record_null.py).
P_EQ_NULL_THRESHOLD_RAD_S = math.radians(0.1)

MODEL_NAME = "Burnham-Hallock vortex pair with uniform-lift strip theory"
STANDARD = ("Burnham & Hallock, DOT-TSC-FAA-79-103 Vol. IV (1982): V(r) = Gamma/(2 pi r) "
            "r^2/(r^2 + r_c^2) per vortex; Gamma_0 = W/(rho V b_0), b_0 = pi b/4; r_c = 0.035 b "
            "(Proctor); p_eq = (12/b^3) int w(y) y dy (uniform-lift strip theory, 32-point "
            "Gauss-Legendre); optional Sarpkaya (2000) decay with eps*, N* as declared inputs "
            "[all unverified here]")
REFERENCES = (
    "Burnham, D. C. & Hallock, J. N., Chicago monostatic acoustic vortex sensing system, "
    "Vol. IV: wake vortex decay, DOT-TSC-FAA-79-103 (1982) [unverified here]",
    "Hallock, J. N. & Burnham, D. C., Decay characteristics of wake vortices from jet "
    "transport aircraft, AIAA 97-0060 [unverified here]",
    "Proctor, F. H., The NASA-Langley wake vortex modelling effort in support of AVOSS, "
    "AIAA 98-0589 (the 0.035 b core convention) [unverified here]",
    "Sarpkaya, T., New model for vortex decay in the atmosphere, J. Aircraft 37(1) 53-61 "
    "(2000) [unverified here; the demise-time constant 0.7475 from memory]",
    "Gerz, T., Holzapfel, F. & Darracq, D., Commercial aircraft wake vortices, Progress in "
    "Aerospace Sciences 38 (2002) [unverified here]",
    "ADVANCEMENTS_BLUEPRINT section 1, work item P7; core/control/systems/gust_rotation.xml "
    "(P2) for the roll-damping sum the equivalent roll rate enters",
)


class WakeError(ValueError):
    """A wake refusal, by name (``.constraint``)."""

    def __init__(self, constraint: str, message: str, actual=None, limit=None,
                 unit=None) -> None:
        self.constraint = constraint
        self.message = message
        self.actual = actual
        self.limit = limit
        self.unit = unit
        super().__init__(f"{constraint}: {message}")


def _number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


# -- the closed forms ---------------------------------------------------------------

def vortex_spacing(span_m: float) -> float:
    """b_0 = pi b / 4 (elliptic loading)."""
    return B0_FACTOR * float(span_m)


def core_radius(span_m: float) -> float:
    """r_c = 0.035 b (Proctor's convention, a stated choice)."""
    return CORE_RADIUS_FACTOR * float(span_m)


def initial_circulation(weight_n: float, rho_kgm3: float, speed_mps: float,
                        spacing_m: float) -> float:
    """Gamma_0 = W / (rho V b_0), m^2/s."""
    if not (weight_n > 0.0 and rho_kgm3 > 0.0 and speed_mps > 0.0 and spacing_m > 0.0):
        raise ValueError("Gamma_0 needs a positive weight, density, speed and spacing")
    return float(weight_n) / (float(rho_kgm3) * float(speed_mps) * float(spacing_m))


def descent_speed(gamma_m2_s: float, spacing_m: float) -> float:
    """w_0 = Gamma / (2 pi b_0): the pair's mutual induction speed."""
    return float(gamma_m2_s) / (2.0 * math.pi * float(spacing_m))


def burnham_hallock(r_m: float, gamma_m2_s: float, r_c_m: float) -> float:
    """The tangential velocity of one vortex at radius r: Gamma/(2 pi r)
    x r^2/(r^2 + r_c^2), written as Gamma r / (2 pi (r^2 + r_c^2)) so it
    is 0 at the centre and Gamma/(4 pi r_c) at r = r_c."""
    r = float(r_m)
    return float(gamma_m2_s) * r / (2.0 * math.pi * (r * r + float(r_c_m) ** 2))


def pair_velocity(y_m: float, z_m: float, gamma_m2_s: float, spacing_m: float,
                  r_c_m: float) -> Tuple[float, float]:
    """(v, w_up) at (y, z) in the wake frame (y right, z UP), from the
    starboard vortex (+b_0/2, counter-clockwise seen from behind) and the
    port vortex (-b_0/2, clockwise), each Burnham-Hallock. The pair's
    centre is the origin; the air between the cores moves down."""
    v = 0.0
    w = 0.0
    for y0, sign in ((+0.5 * spacing_m, +1.0), (-0.5 * spacing_m, -1.0)):
        dy = float(y_m) - y0
        dz = float(z_m)
        r = math.hypot(dy, dz)
        if r == 0.0:
            continue
        speed = burnham_hallock(r, gamma_m2_s, r_c_m)
        # Counter-clockwise tangential direction is (-dz, dy) / r.
        v += sign * speed * (-dz / r)
        w += sign * speed * (dy / r)
    return v, w


_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(GL_POINTS)


def p_equivalent(upwash_at, span_m: float) -> float:
    """p_eq = (12 / b^3) int_{-b/2}^{b/2} w_up(y) y dy by Gauss-Legendre
    quadrature of order ``GL_POINTS`` (y = b x / 2): = (3 / b) sum_i
    w_i x_i w_up(b x_i / 2). ``upwash_at(y)`` is the upwash (positive
    UP, m/s) at span station y (positive right of the CG)."""
    b = float(span_m)
    if not b > 0.0:
        raise ValueError("the strip-theory integral needs a positive span")
    total = 0.0
    for x, weight in zip(_GL_NODES, _GL_WEIGHTS):
        total += float(weight) * float(x) * float(upwash_at(0.5 * b * float(x)))
    return 3.0 / b * total


def sarpkaya_demise_time(eps_star: float, n_star: float = 0.0) -> float:
    """The non-dimensional demise time T_d = (0.7475 / eps*)^(4/3) [from
    memory, unverified here], bounded by pi / (2 N*) when N* > 0 (a
    stated bound; see the module docstring)."""
    if not eps_star > 0.0:
        raise ValueError("a demise time needs eps* > 0")
    demise = (SARPKAYA_DEMISE_CONSTANT / float(eps_star)) ** (4.0 / 3.0)
    if n_star > 0.0:
        demise = min(demise, math.pi / (2.0 * float(n_star)))
    return demise


def circulation_at(age_s: float, gamma_0: float, spacing_m: float, model: str,
                   eps_star: Optional[float] = None, n_star: Optional[float] = None) -> float:
    """Gamma(age): Gamma_0 for the ``none`` model (0 before the generator has
    passed); the sarpkaya history Gamma_0 max(0, 1 - T / T_d), T = age w_0 / b_0."""
    if age_s < 0.0:
        return 0.0
    if model == "none":
        return float(gamma_0)
    if model != "sarpkaya":
        raise WakeError("wake.model", f"unknown decay model {model!r}; known: {list(DECAY_MODELS)}",
                        actual=model)
    w0 = descent_speed(gamma_0, spacing_m)
    t_scale = float(spacing_m) / w0
    demise = sarpkaya_demise_time(float(eps_star), 0.0 if n_star is None else float(n_star))
    fraction = max(0.0, 1.0 - (float(age_s) / t_scale) / demise)
    return float(gamma_0) * fraction


# -- the generator's data and the own airframe's aileron term -----------------------

@dataclass(frozen=True)
class GeneratorData:
    """The generating airframe's weight and span, read from its loaded
    JSBSim model (``inertia/weight-lbs`` as the XML ships it, ``metrics/bw-ft``)."""

    aircraft: str
    weight_lb: float
    span_ft: float
    xml_sha256: str

    @property
    def weight_n(self) -> float:
        return u.lb_to_kg(self.weight_lb) * u.G0

    @property
    def span_m(self) -> float:
        return u.ft_to_m(self.span_ft)

    def to_dict(self) -> Dict[str, Any]:
        return {"aircraft": self.aircraft, "weight_lb": self.weight_lb, "weight_n": self.weight_n,
                "span_ft": self.span_ft, "span_m": self.span_m, "xml_sha256": self.xml_sha256,
                "source": "the stock JSBSim model as loaded: inertia/weight-lbs and metrics/bw-ft"}


_GENERATORS: Dict[str, GeneratorData] = {}


def generator_data(aircraft: Any) -> GeneratorData:
    """The generator's W and b, refused ``wake.generator`` for an
    airframe that is not configured or whose model states no span or no
    weight. Cached per name (one JSBSim load each)."""
    if not isinstance(aircraft, str) or not aircraft.strip():
        raise WakeError("wake.generator", f"the generator must name an airframe, not {aircraft!r}",
                        actual=aircraft)
    if aircraft in _GENERATORS:
        return _GENERATORS[aircraft]
    airframes = configured_airframes()
    if aircraft not in airframes:
        raise WakeError("wake.generator",
                        f"{aircraft!r} is not a configured airframe (one of {airframes}); a "
                        f"generator's weight and span come from its flight model",
                        actual=aircraft)
    from ..fdm import FDMError, FlightDynamics

    try:
        with contextlib.redirect_stdout(io.StringIO()):
            fdm = FlightDynamics(aircraft)
        weight = float(fdm.props.get("inertia/weight-lbs"))
        span = float(fdm.props.get("metrics/bw-ft"))
        sha = fdm.model.sha256
    except FDMError as exc:
        raise WakeError("wake.generator", f"{aircraft!r} could not be loaded: {exc}",
                        actual=aircraft) from exc
    if not (weight > 0.0 and math.isfinite(weight)):
        raise WakeError("wake.generator",
                        f"{aircraft!r} states no weight (inertia/weight-lbs {weight}); Gamma_0 "
                        f"needs one", actual=weight, unit="lb")
    if not (span > 0.0 and math.isfinite(span)):
        raise WakeError("wake.generator",
                        f"{aircraft!r} states no span (metrics/bw-ft {span}); b_0 and r_c need one",
                        actual=span, unit="ft")
    data = GeneratorData(aircraft, weight, span, sha)
    _GENERATORS[aircraft] = data
    return data


def aileron_authority(aircraft: str) -> Dict[str, Any]:
    """What the own airframe's stock XML says the RCR needs: the ROLL
    axis's ``Clp`` and aileron coefficients as plain ``<value>`` terms and
    the FCS aileron range in radians -- or ``available: false`` with the
    reason (a table, a missing term, no range). Reads the stock file;
    nothing is written."""
    from ..fdm import aircraft as ac

    model = ac.resolve(aircraft)
    text = model.xml_path.read_text(encoding="utf-8")
    out: Dict[str, Any] = {"available": False, "aircraft": model.name, "clp": None, "clda": None,
                           "aileron_max_rad": None, "reason": None}
    aero = re.search(r"<aerodynamics.*?</aerodynamics>", text, re.S)
    roll = re.search(r'<axis\s+name="ROLL".*?</axis>', aero.group(0), re.S) if aero else None
    if roll is None:
        out["reason"] = "the airframe's aerodynamics declare no ROLL axis"
        return out
    functions = re.findall(r"<function\b.*?</function>", roll.group(0), re.S)

    def plain_value(property_name: str, label: str) -> Optional[float]:
        for function in functions:
            if f"<property>{property_name}</property>" not in function:
                continue
            if "<table" in function:
                out["reason"] = f"the {label} term is a table, not a plain value"
                return None
            values = re.findall(r"<value>\s*([-+0-9.eE]+)\s*</value>", function)
            if len(values) != 1:
                out["reason"] = f"the {label} term carries {len(values)} plain values, not one"
                return None
            return float(values[0])
        out["reason"] = f"the ROLL axis has no term in {property_name}"
        return None

    clp = plain_value("velocities/p-aero-rad_sec", "roll-damping")
    if clp is None:
        return out
    clda = plain_value("fcs/left-aileron-pos-rad", "aileron")
    if clda is None:
        return out
    fcs = re.search(r"<flight_control.*?</flight_control>", text, re.S)
    component = None
    if fcs:
        for candidate in re.findall(r"<aerosurface_scale\b.*?</aerosurface_scale>", fcs.group(0), re.S):
            if "<output>fcs/left-aileron-pos-rad</output>" in candidate:
                component = candidate
                break
    limits = re.search(r"<range>\s*<min>\s*([-+0-9.eE]+)\s*</min>\s*<max>\s*([-+0-9.eE]+)\s*</max>",
                       component, re.S) if component else None
    if limits is None:
        out["reason"] = "the FCS states no aerosurface_scale range for the left aileron"
        return out
    gain = re.search(r"<gain>\s*([-+0-9.eE]+)\s*</gain>", component)
    scale = float(gain.group(1)) if gain else 1.0
    out.update({"available": True, "clp": clp, "clda": clda,
                "aileron_max_rad": scale * max(abs(float(limits.group(1))), abs(float(limits.group(2)))),
                "reason": None,
                "basis": ("Clp and the aileron coefficient read as the one <value> of the ROLL "
                          "axis functions in velocities/p-aero-rad_sec and fcs/left-aileron-pos-rad "
                          "of the stock XML; the aileron limit as the FCS aerosurface_scale "
                          "range x gain")})
    return out


# -- the block's problems, one list -----------------------------------------------

def problems(generator: Any, generator_speed_kt: Any, lateral_offset_m: Any,
             vertical_offset_m: Any, separation_s: Any, age_s: Any, model: Any,
             eps_star: Any, n_star: Any) -> List[WakeError]:
    """Every way a stated wake block departs from the contract (the module
    docstring's refusals), in field order. A block with no generator
    yields nothing here (nothing is applied; the runner records the
    unread fields)."""
    out: List[WakeError] = []
    if generator is None:
        return out
    try:
        generator_data(generator)
    except WakeError as exc:
        out.append(exc)
    if generator_speed_kt is not None and not (_number(generator_speed_kt)
                                               and float(generator_speed_kt) > 0.0):
        out.append(WakeError("wake.geometry",
                             f"the generator's speed must be a positive number of knots or absent, "
                             f"not {generator_speed_kt!r}", actual=generator_speed_kt, unit="kt"))
    for name, value in (("lateral_offset_m", lateral_offset_m),
                        ("vertical_offset_m", vertical_offset_m)):
        if not _number(value):
            out.append(WakeError("wake.geometry",
                                 f"{name} must be a finite number of metres, not {value!r}",
                                 actual=value, unit="m"))
    stated = [(n, v) for n, v in (("separation_s", separation_s), ("age_s", age_s)) if v is not None]
    if not stated:
        out.append(WakeError("wake.geometry",
                             "an encounter states the wake's age: separation_s (the generator "
                             "passed that many seconds before the run's first step) or age_s (held)"))
    elif len(stated) == 2:
        out.append(WakeError("wake.geometry",
                             "separation_s and age_s are two spellings of the wake's age; state one"))
    else:
        name, value = stated[0]
        if not (_number(value) and float(value) >= 0.0):
            out.append(WakeError("wake.geometry",
                                 f"{name} must be a non-negative number of seconds, not {value!r}",
                                 actual=value, limit=0.0, unit="s"))
    if model not in DECAY_MODELS:
        out.append(WakeError("wake.model",
                             f"the decay model must be one of {list(DECAY_MODELS)}, not {model!r}",
                             actual=model))
    elif model == "sarpkaya":
        if eps_star is None:
            out.append(WakeError("wake.decay",
                                 "the sarpkaya decay needs eps_star, the non-dimensional eddy "
                                 "dissipation rate (a declared input)"))
        elif not (_number(eps_star) and EPS_STAR_RANGE[0] < float(eps_star) <= EPS_STAR_RANGE[1]):
            out.append(WakeError("wake.decay",
                                 f"eps_star must lie in ({EPS_STAR_RANGE[0]:g}, {EPS_STAR_RANGE[1]:g}], "
                                 f"not {eps_star!r}", actual=eps_star, limit=EPS_STAR_RANGE[1]))
        if n_star is not None and not (_number(n_star)
                                       and N_STAR_RANGE[0] <= float(n_star) <= N_STAR_RANGE[1]):
            out.append(WakeError("wake.decay",
                                 f"n_star must lie in {N_STAR_RANGE[0]:g}..{N_STAR_RANGE[1]:g} or be "
                                 f"absent, not {n_star!r}", actual=n_star, limit=N_STAR_RANGE[1]))
    return out


@dataclass(frozen=True)
class Stated:
    """One stated field with its provenance, as the spec carried it."""

    value: Any
    source: str = "user"
    frm: Optional[str] = None
    std: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"value": self.value, "source": self.source, "from": self.frm, "std": self.std}


def _stated(quantity) -> Optional[Stated]:
    """A block field as a :class:`Stated`, or None when it is at its
    default or unstated (``value: null``)."""
    if quantity is None or str(quantity.source) == "default" or quantity.value is None:
        return None
    return Stated(quantity.value, str(quantity.source), quantity.frm, quantity.std)


def wake_injections_for(spec) -> Tuple[str, ...]:
    """The XML injection a spec's wake block needs: ``("gust_rotation",)``
    when a generator is stated, nothing otherwise (the stock airframe,
    hashes unchanged)."""
    block = getattr(spec, "wake", None)
    if block is None or block.is_default() or block.generator.value is None:
        return ()
    return INJECTIONS


def unread_wake_fields(spec) -> List[str]:
    """The wake fields a spec states beside no generator (carried, not
    applied), for the runner's note."""
    block = getattr(spec, "wake", None)
    if block is None or block.is_default() or block.generator.value is not None:
        return []
    return [name for name, q in block.quantities()
            if name != "generator" and _stated(q) is not None]


# -- the provider -------------------------------------------------------------------

class WakeVortexPair(GustProvider):
    """The pair as the stack delivers it (see the module docstring)."""

    name = "wake_vortex_pair"

    def __init__(self, generator: GeneratorData, lateral_offset_m: float, vertical_offset_m: float,
                 heading_deg: float, separation_s: Optional[float] = None,
                 age_s: Optional[float] = None, model: str = "none",
                 eps_star: Optional[float] = None, n_star: Optional[float] = None,
                 generator_speed_kt: Optional[float] = None, own_aircraft: Optional[str] = None,
                 stated: Optional[Dict[str, Optional[Stated]]] = None) -> None:
        found = problems(generator.aircraft, generator_speed_kt, lateral_offset_m,
                         vertical_offset_m, separation_s, age_s, model, eps_star, n_star)
        if found:
            raise found[0]
        self.generator = generator
        self.lateral_offset_m = float(lateral_offset_m)
        self.vertical_offset_m = float(vertical_offset_m)
        self.heading_deg = float(heading_deg)
        self.separation_s = None if separation_s is None else float(separation_s)
        self.age_held_s = None if age_s is None else float(age_s)
        self.model = str(model)
        self.eps_star = None if eps_star is None else float(eps_star)
        self.n_star = None if n_star is None else float(n_star)
        self.generator_speed_kt = None if generator_speed_kt is None else float(generator_speed_kt)
        self.own_aircraft = own_aircraft
        self.stated: Dict[str, Optional[Stated]] = dict(stated or {})
        #: Fields carried but not applied (eps*/N* beside the ``none`` model).
        self.unread_stated_fields = [f for f in ("eps_star", "n_star")
                                     if self.model == "none" and getattr(self, f) is not None]
        self.b_0_m = vortex_spacing(generator.span_m)
        self.r_c_m = core_radius(generator.span_m)
        #: Filled by :meth:`prepare` from the FDM.
        self.prepared: Optional[Dict[str, Any]] = None
        self.gamma_0: Optional[float] = None
        self.w_0: Optional[float] = None
        self.rho_kgm3: Optional[float] = None
        self.speed_mps: Optional[float] = None
        self.own_span_m: Optional[float] = None
        self.own_tas0_mps: Optional[float] = None
        self.rcr: Dict[str, Any] = {"available": False, "reason": "prepare(fdm) was not called"}
        #: Per-step bookkeeping.
        self.origin: Optional[Tuple[float, float, float]] = None
        self.t_start_s: Optional[float] = None
        self._cache_key: Optional[Tuple[float, float, float, float]] = None
        self.last: Dict[str, float] = {c: 0.0 for c in TELEMETRY_COLUMNS}
        self.peak_abs_p_eq = 0.0
        self.peak_abs_w = 0.0
        self.steps_evaluated = 0
        self.steps_before_generator = 0

    @classmethod
    def from_spec(cls, spec) -> Optional["WakeVortexPair"]:
        """The provider a spec asks for, or None for the default block and
        for a block that names no generator (nothing applied; the runner
        records the unread fields). Refuses by name what the validator
        refuses."""
        block = spec.wake
        if block.is_default() or block.generator.value is None:
            return None
        return cls(generator_data(block.generator.value),
                   lateral_offset_m=block.lateral_offset_m.value,
                   vertical_offset_m=block.vertical_offset_m.value,
                   heading_deg=float(spec.heading.value),
                   separation_s=block.separation_s.value, age_s=block.age_s.value,
                   model=block.model.value, eps_star=block.eps_star.value, n_star=block.n_star.value,
                   generator_speed_kt=block.generator_speed_kt.value,
                   own_aircraft=str(spec.aircraft.value),
                   stated={name: _stated(q) for name, q in block.quantities()})

    # -- the pre-trim hook ---------------------------------------------------------------

    @property
    def age_0_s(self) -> float:
        """The wake's age at the own ship's position at the run's first step."""
        return self.age_held_s if self.age_held_s is not None else float(self.separation_s)

    def prepare(self, fdm) -> Dict[str, Any]:
        """The stack's pre-trim hook (after the atmosphere providers', so
        rho is the stated day's): the air density at the encounter
        altitude, the own span and true airspeed at the initial
        conditions, the generator's speed, Gamma_0, w_0 and the aileron
        term for the RCR."""
        self.rho_kgm3 = u.slugft3_to_kgm3(fdm.props.get("atmosphere/rho-slugs_ft3"))
        self.own_span_m = u.ft_to_m(fdm.props.get("metrics/bw-ft"))
        self.own_tas0_mps = u.kt_to_mps(fdm.props.get("velocities/vtrue-kts"))
        self.speed_mps = (self.own_tas0_mps if self.generator_speed_kt is None
                          else u.kt_to_mps(self.generator_speed_kt))
        self.gamma_0 = initial_circulation(self.generator.weight_n, self.rho_kgm3, self.speed_mps,
                                           self.b_0_m)
        self.w_0 = descent_speed(self.gamma_0, self.b_0_m)
        own = self.own_aircraft or fdm.aircraft_name
        base = own.split("-")[0]
        self.rcr = aileron_authority(base)
        # The first recorded sample precedes the first step: it carries the
        # field at the STATED geometry (the offsets and age_0 as the spec
        # says them), so the columns never read 0 for a wake that is there.
        _, v, w_down = self.velocity(self.lateral_offset_m, self.vertical_offset_m, self.age_0_s)
        p_eq = self.p_eq(self.lateral_offset_m, self.vertical_offset_m, self.age_0_s)
        self.last = {
            "wake_u_mps": 0.0, "wake_v_mps": v, "wake_w_mps": w_down, "wake_p_eq_rad_s": p_eq,
            "wake_gamma_m2_s": self.circulation(self.age_0_s), "wake_age_s": self.age_0_s,
            "wake_lateral_m": self.lateral_offset_m, "wake_vertical_m": self.vertical_offset_m,
            "wake_rcr": self.rcr_at(p_eq, self.own_tas0_mps),
        }
        self.prepared = {
            "rho_kgm3": self.rho_kgm3, "rho_basis": ("atmosphere/rho-slugs_ft3 at the initial "
                                                     "conditions after the atmosphere providers' "
                                                     "pre-trim writes: the encounter altitude"),
            "own_span_m": self.own_span_m, "own_tas0_mps": self.own_tas0_mps,
            "generator_speed_mps": self.speed_mps,
            "generator_speed_basis": ("the spec's generator_speed_kt" if self.generator_speed_kt
                                      is not None else "the own ship's true airspeed at the "
                                                       "initial conditions (unstated)"),
            "gamma_0_m2_s": self.gamma_0, "b_0_m": self.b_0_m, "r_c_m": self.r_c_m,
            "w_0_mps": self.w_0, "age_0_s": self.age_0_s,
            "descent_m": self.w_0 * self.age_0_s, "ahead_m": self.speed_mps * self.age_0_s,
            "rcr": dict(self.rcr), "generator": self.generator.to_dict(),
        }
        return dict(self.prepared)

    def _ensure(self, own_ship: OwnShipState) -> None:
        if self.prepared is None:
            # prepare was not called (a stack driven by hand): the own-ship
            # state and ISA density at the altitude stand in, said in the record.
            self.rho_kgm3 = 1.225 * math.exp(-own_ship.position.altitude_m / 8500.0)
            self.own_span_m = own_ship.span_m
            self.own_tas0_mps = own_ship.tas_mps
            self.speed_mps = (own_ship.tas_mps if self.generator_speed_kt is None
                              else u.kt_to_mps(self.generator_speed_kt))
            self.gamma_0 = initial_circulation(self.generator.weight_n, self.rho_kgm3,
                                               self.speed_mps, self.b_0_m)
            self.w_0 = descent_speed(self.gamma_0, self.b_0_m)
            self.prepared = {"basis": "the own-ship state at the first step (prepare was not "
                                      "called); rho from an exponential ISA stand-in",
                             "gamma_0_m2_s": self.gamma_0, "b_0_m": self.b_0_m, "r_c_m": self.r_c_m,
                             "w_0_mps": self.w_0, "age_0_s": self.age_0_s, "rho_kgm3": self.rho_kgm3,
                             "own_span_m": self.own_span_m, "generator_speed_mps": self.speed_mps,
                             "descent_m": self.w_0 * self.age_0_s,
                             "ahead_m": self.speed_mps * self.age_0_s, "rcr": dict(self.rcr)}

    # -- the field ---------------------------------------------------------------------------

    def circulation(self, age_s: float) -> float:
        return circulation_at(age_s, self.gamma_0, self.b_0_m, self.model, self.eps_star, self.n_star)

    def velocity(self, y_m: float, z_up_m: float, age_s: float) -> Tuple[float, float, float]:
        """(u, v, w_down) at (y, z UP) in the wake frame at a wake age: the
        pair's field with the circulation at that age; u is 0."""
        gamma = self.circulation(age_s)
        v, w_up = pair_velocity(y_m, z_up_m, gamma, self.b_0_m, self.r_c_m)
        return 0.0, v, -w_up

    def p_eq(self, y_m: float, z_up_m: float, age_s: float, span_m: Optional[float] = None) -> float:
        """The equivalent roll rate of the field over a level wing of
        ``span_m`` (the own span by default) centred at (y, z)."""
        gamma = self.circulation(age_s)
        b = self.own_span_m if span_m is None else float(span_m)
        return p_equivalent(
            lambda station: pair_velocity(y_m + station, z_up_m, gamma, self.b_0_m, self.r_c_m)[1], b)

    def rcr_at(self, p_eq: float, tas_mps: float) -> float:
        """|Clp p_eq b / (2 V)| / (|Clda| delta_a,max), 0 where unavailable."""
        if not self.rcr.get("available") or not tas_mps > 0.0:
            return 0.0
        moment = abs(self.rcr["clp"] * p_eq * self.own_span_m / (2.0 * tas_mps))
        return moment / (abs(self.rcr["clda"]) * self.rcr["aileron_max_rad"])

    def relative_position(self, own_ship: OwnShipState, time_s: float) -> Dict[str, float]:
        """The own CG's (along, y, z UP) from the pair's centre and the
        wake's age there, from the flat-earth displacement since the
        first step's position (the origin, latched then)."""
        p = own_ship.position
        if self.origin is None:
            self.origin = (p.latitude_deg, p.longitude_deg, p.altitude_m)
            self.t_start_s = float(time_s)
        lat0, lon0, alt0 = self.origin
        d_north = (p.latitude_deg - lat0) * METRES_PER_DEGREE
        d_east = (p.longitude_deg - lon0) * METRES_PER_DEGREE * math.cos(math.radians(lat0))
        psi = math.radians(self.heading_deg)
        along = d_north * math.cos(psi) + d_east * math.sin(psi)
        across = -d_north * math.sin(psi) + d_east * math.cos(psi)
        t_run = float(time_s) - self.t_start_s
        if self.age_held_s is not None:
            age = self.age_held_s
        else:
            age = self.separation_s + t_run - along / self.speed_mps
        return {"along_m": along, "y_m": self.lateral_offset_m + across,
                "z_m": self.vertical_offset_m + (p.altitude_m - alt0), "age_s": age, "t_run_s": t_run}

    def evaluate(self, own_ship: OwnShipState, time_s: float) -> Dict[str, float]:
        """The field at the own ship: the CG velocity, p_eq over the own
        span, the circulation, the age, the offsets and the RCR. Cached for
        the (time, position) the stack asks twice per step."""
        self._ensure(own_ship)
        p = own_ship.position
        key = (float(time_s), p.latitude_deg, p.longitude_deg, p.altitude_m)
        if key == self._cache_key:
            return self.last
        rel = self.relative_position(own_ship, time_s)
        age = rel["age_s"]
        _, v, w_down = self.velocity(rel["y_m"], rel["z_m"], age)
        p_eq = self.p_eq(rel["y_m"], rel["z_m"], age)
        gamma = self.circulation(age)
        if age < 0.0:
            self.steps_before_generator += 1
        self.last = {
            "wake_u_mps": 0.0, "wake_v_mps": v, "wake_w_mps": w_down, "wake_p_eq_rad_s": p_eq,
            "wake_gamma_m2_s": gamma, "wake_age_s": age, "wake_lateral_m": rel["y_m"],
            "wake_vertical_m": rel["z_m"], "wake_rcr": self.rcr_at(p_eq, own_ship.tas_mps),
        }
        self.peak_abs_p_eq = max(self.peak_abs_p_eq, abs(p_eq))
        self.peak_abs_w = max(self.peak_abs_w, abs(w_down))
        self.steps_evaluated += 1
        self._cache_key = key
        return self.last

    def gust_at(self, own_ship: OwnShipState, time_s: float) -> WindNED:
        """The pair's velocity at the own CG in NED: v along the wake
        frame's right axis (heading + 90 deg), w down."""
        last = self.evaluate(own_ship, time_s)
        psi = math.radians(self.heading_deg)
        v = last["wake_v_mps"]
        return WindNED(-v * math.sin(psi), v * math.cos(psi), last["wake_w_mps"])

    def p_equivalent_at(self, own_ship: OwnShipState, time_s: float) -> float:
        return self.evaluate(own_ship, time_s)["wake_p_eq_rad_s"]

    def recorder_extras(self):
        """The nine wake columns from the last evaluation (Recorder ``extra``)."""
        def reader(column: str):
            return lambda _fdm: float(self.last[column])
        return {column: reader(column) for column in TELEMETRY_COLUMNS}

    # -- the generator's track and the card ------------------------------------------------

    def generator_geometry(self) -> Dict[str, Any]:
        """Where the generator flies relative to the own ship's first
        sample (core/capture/poses.py ``wake_generator``): ahead along the
        own initial heading by V_g age_0, to the LEFT by the lateral offset
        (the own ship is to the right of the pair's centre), above by the
        pair's descent minus the vertical offset; at V_g, wings level."""
        self._require_prepared()
        return {"heading_deg": self.heading_deg, "speed_mps": self.speed_mps,
                "ahead_m": self.speed_mps * self.age_0_s, "right_m": -self.lateral_offset_m,
                "above_m": self.w_0 * self.age_0_s - self.vertical_offset_m,
                "descent_m": self.w_0 * self.age_0_s, "age_0_s": self.age_0_s,
                "aircraft": self.generator.aircraft}

    def _require_prepared(self) -> None:
        if self.prepared is None or self.gamma_0 is None:
            raise ValueError("WakeVortexPair.prepare(fdm) was never called; Gamma_0 needs the "
                             "density, the own span and the speeds")

    def selftest_vectors(self) -> List[Dict[str, float]]:
        """Five (y, z) probes in the wake frame at age_0 with the expected
        u, v, w (down) and p_eq over the own span: the vectors the host
        port must reproduce to 1e-9 (P9's Windows step)."""
        self._require_prepared()
        b0, rc = self.b_0_m, self.r_c_m
        probes = ((0.0, 0.0), (0.5 * b0 + rc, 0.0), (0.5 * b0, 0.5 * b0),
                  (-0.25 * b0, -0.25 * b0), (self.lateral_offset_m, self.vertical_offset_m))
        age = self.age_0_s
        out = []
        for y, z in probes:
            u_, v, w = self.velocity(y, z, age)
            out.append({"y_m": y, "z_m": z, "age_s": age, "u_mps": u_, "v_mps": v, "w_mps": w,
                        "p_eq_rad_s": self.p_eq(y, z, age)})
        if len(out) != SELFTEST_COUNT or any(tuple(o) != SELFTEST_KEYS for o in out):
            raise RuntimeError("the selftest vectors are not five rows in the fixed key order")
        return out

    def decay_block(self) -> Dict[str, Any]:
        demise = None
        t_scale = None
        if self.gamma_0 is not None:
            t_scale = self.b_0_m / self.w_0
            if self.model == "sarpkaya":
                demise = sarpkaya_demise_time(self.eps_star, 0.0 if self.n_star is None else self.n_star)
        return {"model": self.model, "eps_star": self.eps_star, "n_star": self.n_star,
                "t_0_s": t_scale, "demise_time_nd": demise,
                "demise_time_s": None if demise is None else demise * t_scale,
                "gamma_at_age_0_m2_s": None if self.gamma_0 is None else self.circulation(self.age_0_s),
                "unread_stated_fields": list(self.unread_stated_fields),
                "form": ("Gamma_0 held (age recorded)" if self.model == "none" else
                         "Gamma_0 max(0, 1 - T/T_d), T = age w_0/b_0, T_d = (0.7475/eps*)^(4/3) "
                         "bounded by pi/(2 N*) for N* > 0 [from memory, unverified here]")}

    def card_block(self) -> Dict[str, Any]:
        """The ``wake`` card block in the fixed key order ``CARD_KEYS``:
        the generator's data and placement, Gamma_0, b_0, r_c, the decay,
        the geometry and the selftest vectors the host checks."""
        self._require_prepared()
        block = {
            "generator": {**self.generator.to_dict(), **self.generator_geometry(),
                          "rho_kgm3": self.rho_kgm3},
            "gamma_0": self.gamma_0,
            "b_0": self.b_0_m,
            "r_c": self.r_c_m,
            "decay": self.decay_block(),
            "geometry": {
                "lateral_offset_m": self.lateral_offset_m, "vertical_offset_m": self.vertical_offset_m,
                "separation_s": self.separation_s, "age_s": self.age_held_s, "age_0_s": self.age_0_s,
                "own_span_m": self.own_span_m, "own_aircraft": self.own_aircraft,
                "heading_deg": self.heading_deg, "w_0_mps": self.w_0,
                "frame": ("x along heading_deg, y right, z up for the probes; the delivered w is "
                          "NED down; u is 0 (no axial induction); p_eq over the own span, level "
                          "wing, delivered into gust/p-equivalent-rad_sec"),
                "age_rule": ("held at age_s" if self.age_held_s is not None else
                             "separation_s + t - x_along / V_g (the own ship's along-track "
                             "distance from its first step)"),
                "core_radius_rule": "r_c = 0.035 b (Proctor)", "spacing_rule": "b_0 = pi b / 4",
                "quadrature": f"{GL_POINTS}-point Gauss-Legendre over the own span",
            },
            "selftest": self.selftest_vectors(),
        }
        if tuple(block) != CARD_KEYS:
            raise RuntimeError(f"wake card keys {list(block)} are not the fixed order {list(CARD_KEYS)}")
        return block

    # -- the records ----------------------------------------------------------------------------

    def model_block(self) -> Model:
        name = MODEL_NAME + (" and Sarpkaya decay" if self.model == "sarpkaya" else "")
        return Model(
            name=name, standard=STANDARD, version="1",
            parameters={
                "gamma_0_m2_s": self.gamma_0, "b_0_m": self.b_0_m, "r_c_m": self.r_c_m,
                "w_0_mps": self.w_0, "rho_kgm3": self.rho_kgm3, "generator": self.generator.to_dict(),
                "generator_speed_mps": self.speed_mps, "own_span_m": self.own_span_m,
                "core_radius_factor": CORE_RADIUS_FACTOR, "spacing_factor": B0_FACTOR,
                "profile": "Burnham-Hallock V(r) = Gamma r / (2 pi (r^2 + r_c^2))",
                "strip_theory": f"p_eq = (12/b^3) int w_up(y) y dy, {GL_POINTS}-point Gauss-Legendre, "
                                f"uniform lift, level wing",
                "decay": self.decay_block(), "rcr": dict(self.rcr),
                "frame": "x along the heading, y right, z up (w delivered NED down)",
            },
            references=REFERENCES)

    def _not_claimed(self, p_delivery: str) -> Tuple[str, ...]:
        out = (
            "the core radius is a stated convention (0.035 b), not a measurement of this generator",
            "no Crow instability, no vortex linking, no ground effect",
            "no stratification-dependent decay beyond the stated N* bound; the decay constants "
            "are a transcription from memory [unverified here]",
            "the pair descends at w_0 x age with the initial circulation, along a straight track "
            "at one speed (the frozen wake is not followed in time)",
            "a strip-theory roll moment only: uniform lift, level wing, no tail, no yaw or pitch "
            "moment, no Clr coupling",
            "the host port (FlightSimWake.h/.cpp) and its selftest are P9's Windows step",
            "nothing is validated against a measured encounter",
        )
        if not self.rcr.get("available"):
            out = out + (f"the rolling-moment coefficient ratio: absent ({self.rcr.get('reason')})",)
        if p_delivery != "property":
            out = out + ("the roll gust on this airframe: gust/p-equivalent-rad_sec is absent",)
        return out

    def applied_variables(self, delivery: Optional[Dict[str, Any]] = None) -> List[AppliedVariable]:
        """One record per stated ``wake`` field, each with the gust
        channel's and the roll property's read-back the stack measured
        (``delivery``) and an in-run null test on the equivalent roll rate
        delivered."""
        self._require_prepared()
        delivery = dict(delivery or {})
        gust = delivery.get("gust") or {}
        errors = gust.get("max_abs_error") or {}
        last_written = gust.get("last_written") or {}
        last_read = gust.get("last_read") or {}
        p_delivery = gust.get("p_equivalent", "absent")
        readback = None
        prop = P_EQUIVALENT_PROPERTY if p_delivery == "property" else GUST_PROPERTIES[2]
        if prop in last_written and prop in last_read:
            readback = Readback(
                property=prop, value=float(last_read[prop]), written=float(last_written[prop]),
                tolerance=0.0, tolerance_kind="absolute",
                basis=("read back before the next step's write; the gust channel and the injected "
                       "property hold the value written to the bit (measured on JSBSim 1.2.4, "
                       "tests/test_wake.py); the per-step maximum over the run is in "
                       "parameters.per_step_readback"))
        writes = tuple(JsbsimWrite(p, "every step, zero included (the channel persists; the stack "
                                      "sums the gust providers)") for p in GUST_PROPERTIES)
        properties = list(GUST_PROPERTIES)
        if p_delivery == "property":
            writes = writes + (JsbsimWrite(P_EQUIVALENT_PROPERTY,
                                           "every step (the derived airframe declares it)"),)
            properties.append(P_EQUIVALENT_PROPERTY)
        null = NullTest(
            quantity="peak |equivalent roll rate| delivered over the run (wake_p_eq_rad_s)",
            unit="rad/s", with_value=self.peak_abs_p_eq, without_value=0.0,
            threshold=P_EQ_NULL_THRESHOLD_RAD_S, kind="reached",
            note=(f"without = no wake provider, whose roll property reads 0 every step; peak "
                  f"|w_down| {self.peak_abs_w:.4f} m/s over {self.steps_evaluated} steps "
                  f"({self.steps_before_generator} before the generator had passed); threshold the "
                  f"0.1 deg/s rate floor; the two-flight pair is core.record_null.run_null_pair"
                  + ("" if p_delivery == "property" else
                     "; NOT delivered: the airframe declares no gust/p-equivalent-rad_sec")))
        parameters: Dict[str, Any] = {
            "prepared": dict(self.prepared),
            "delivery": {
                "gust_channel": "atmosphere/gust-*-fps (v rotated by the heading, w down)",
                "p_equivalent": p_delivery,
                "steps_written": gust.get("steps_written", 0),
                "steps_evaluated": self.steps_evaluated,
                "steps_before_generator": self.steps_before_generator,
            },
            "per_step_readback": {
                "steps_checked": gust.get("steps_checked", 0),
                "max_abs_error": dict(errors), "tolerance": 0.0,
                "agrees": all(e == 0.0 for e in errors.values()),
                "basis": "each gust property and the roll property read back before the next write",
            },
            "peak_abs_p_eq_rad_s": self.peak_abs_p_eq, "peak_abs_w_mps": self.peak_abs_w,
            "last": dict(self.last), "decay": self.decay_block(), "rcr": dict(self.rcr),
            "unread_stated_fields": list(self.unread_stated_fields),
            "card": {k: v for k, v in self.card_block().items() if k != "selftest"},
        }
        common = dict(model_name=MODEL_NAME, model=self.model_block(), references=REFERENCES,
                      properties_written=tuple(properties), jsbsim_writes=writes,
                      telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                      readback=readback, null_test=null, not_claimed=self._not_claimed(p_delivery))
        units = {"generator": "word", "generator_speed_kt": "kt", "lateral_offset_m": "m",
                 "vertical_offset_m": "m", "separation_s": "s", "age_s": "s", "model": "word",
                 "eps_star": "1", "n_star": "1"}
        out: List[AppliedVariable] = []
        for field, unit in units.items():
            stated = self.stated.get(field)
            if stated is None:
                if field != "generator":
                    continue
                stated = Stated(self.generator.aircraft)
            out.append(AppliedVariable(
                name=f"wake.{field}", value=stated.value, unit=unit, source=stated.source,
                frm=stated.frm, std=stated.std or WAKE_STANDARDS.get(field),
                parameters={**parameters, "applied_to": ("carried, not applied (model none)"
                                                          if field in self.unread_stated_fields
                                                          else "the pair's field")},
                **common))
        return out

    # -- vocabulary, manifest, provenance ---------------------------------------------------------

    def manifest_block(self) -> Dict[str, Any]:
        return {"applied": self.prepared is not None,
                "stated": {f: None if s is None else s.to_dict() for f, s in self.stated.items()},
                "prepared": self.prepared, "decay": self.decay_block(), "rcr": dict(self.rcr),
                "peak_abs_p_eq_rad_s": self.peak_abs_p_eq, "peak_abs_w_mps": self.peak_abs_w,
                "steps_evaluated": self.steps_evaluated,
                "steps_before_generator": self.steps_before_generator,
                "unread_stated_fields": list(self.unread_stated_fields),
                "last": dict(self.last),
                "card": None if self.prepared is None or self.gamma_0 is None else self.card_block()}

    def vocabulary(self) -> List[Term]:
        return [Term("none", "Gamma_0 held", None, WAKE_STANDARDS["model"],
                     note="the age is recorded either way"),
                Term("sarpkaya", "T_d = (0.7475/eps*)^(4/3)", None, WAKE_STANDARDS["sarpkaya"],
                     valid_range=EPS_STAR_RANGE, note="eps* and N* are declared inputs")]

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({"model": MODEL_NAME, "generator": self.generator.to_dict(),
                    "lateral_offset_m": self.lateral_offset_m,
                    "vertical_offset_m": self.vertical_offset_m,
                    "separation_s": self.separation_s, "age_s": self.age_held_s,
                    "decay": self.model, "eps_star": self.eps_star, "n_star": self.n_star,
                    "gamma_0_m2_s": self.gamma_0, "b_0_m": self.b_0_m, "r_c_m": self.r_c_m,
                    "injections": list(INJECTIONS),
                    "delivery": "atmosphere/gust-*-fps every step through the stack's sum; "
                                "gust/p-equivalent-rad_sec where the airframe declares it"})
        return out
