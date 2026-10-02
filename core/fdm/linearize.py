"""Linearisation of the trimmed JSBSim model (gap M2, validation row A5).

The installed JSBSim 1.2.4 exposes ``jsbsim.FGLinearization`` (measured
2026-09-28: ``dir(jsbsim)`` lists it, and it runs on a trimmed
``FGFDMExec``), so the Jacobian is JSBSim's own and this module does not
re-implement it. What JSBSim does, read from the sdist it was built from
(``src/math/FGStateSpace.cpp``, ``src/initialization/FGLinearization.cpp``,
jsbsim-1.2.4.tar.gz): the state is ``Vt, Alpha, Theta, Q`` (ft/s, rad,
rad, rad/s), one ``Rpm`` per propeller engine (none for a turbine), then
``Beta, Phi, P, Psi, R, Latitude, Longitude, Alt``; each state is
perturbed through the initial-condition object (``Alpha::set`` restores
beta, psi and theta so alpha moves alone; ``Theta::set`` moves gamma so
alpha stays), the model is re-initialised and run once with integration
suspended, the state derivative is read from JSBSim's own accelerations,
and the Jacobian column is the four-point central difference
``(8(f(h)-f(-h)) - (f(2h)-f(-2h))) / (12h)`` at ``h = 1e-4`` in each
state's own unit (``FGStateSpace::linearize``, the step is not settable
from Python).

Two things are measured here rather than trusted:

* the RESIDUAL. The classical eight states are perturbed again by THIS
  module, through the ``ic/`` properties and ``run_ic()`` (the same
  restoration of beta, psi and theta), the derivatives are read from the
  property tree (``accelerations/udot-ft_sec2`` and companions,
  ``aero/alphadot-rad_sec``, ``velocities/thetadot-rad_sec``,
  ``accelerations/qdot-rad_sec2``, ``aero/betadot-rad_sec``,
  ``velocities/phidot-rad_sec``, ``accelerations/pdot-rad_sec2``,
  ``accelerations/rdot-rad_sec2``; Vt-dot as ``(u udot + v vdot + w
  wdot)/Vt``, the formula ``FGStateSpace::Vt::getDeriv`` uses), and the
  two-point central difference at :data:`RESIDUAL_STEP` is compared with
  JSBSim's column: ``||A_measured - A_jsbsim||_F / ||A_jsbsim||_F`` per
  4x4 block, refused by name (``modes.residual``) above
  :data:`RESIDUAL_BOUND`. A second, wider perturbation
  (:data:`LINEAR_RANGE_STEP`) is reported unbounded as the linear range:
  how far the linear model predicts the nonlinear derivatives. One-sided
  differences are not used because the trim point is not an exact
  equilibrium (the c172p carries pdot = -0.27 rad/s^2 after a
  longitudinal trim, measured) and a one-sided difference keeps that
  residual derivative; the central difference cancels it.
* the DISTURBANCE. Linearising moves the executive's state by a little
  (measured on the c172p: 223 readable properties change by 1e-10 to
  1e-6, qdot from 1.2e-10 to -8.8e-6 rad/s^2, sim time unchanged). The
  analysis therefore never runs on the FDM that records a flight; it is
  given its own instance (:func:`core.fdm.modes.analyse_spec`) and the
  disturbance it caused is recorded.

Units. JSBSim's matrix is in its own units; the classical blocks returned
here are SI (``Vt`` in m/s by the similarity transform ``T A T^-1`` with
``T = diag(0.3048, 1, 1, 1)``; angles and rates are already SI), so the
eigenvalues are those of JSBSim's matrix exactly.

Not claimed: any linearisation about a state that is not trimmed (refused
``modes.untrimmed``); a model whose state names lack the eight classical
states (refused ``modes.linearization``); the engine, position and
heading states, which are carried in the full matrix but left out of the
classical blocks (the altitude and Rpm couplings are what the classical
approximation drops); that JSBSim's step of 1e-4 is optimal for a table
model with breakpoints near trim (the linear-range figure says how far
it holds; on the A320 the CD table has a breakpoint 0.5 mrad below the
250 kt / 3000 m trim alpha, measured); anything on Windows or an engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .errors import FDMError

#: The classical state ordering of the two 4x4 blocks, in JSBSim's names.
LONGITUDINAL_STATES = ("Vt", "Alpha", "Theta", "Q")
LATERAL_STATES = ("Beta", "Phi", "P", "R")
CLASSICAL_STATES = LONGITUDINAL_STATES + LATERAL_STATES

#: SI units of the classical states as returned here.
SI_UNITS = {"Vt": "m/s", "Alpha": "rad", "Theta": "rad", "Q": "rad/s",
            "Beta": "rad", "Phi": "rad", "P": "rad/s", "R": "rad/s"}

FT_TO_M = 0.3048

#: JSBSim's own step and scheme (FGStateSpace::linearize, jsbsim 1.2.4).
JSBSIM_STEP = 1e-4
JSBSIM_SCHEME = ("four-point central difference (8(f(h)-f(-h)) - (f(2h)-f(-2h)))/(12h), "
                 "h = 1e-4 in each state's own unit; FGStateSpace::numericalJacobian, "
                 "jsbsim 1.2.4 src/math/FGStateSpace.cpp")

#: This module's perturbation for the residual, in each state's own JSBSim
#: unit (ft/s, rad, rad/s): the same magnitude as JSBSim's, so the
#: comparison tests the assembly (the state route, the derivative reads,
#: the block extraction) and not the table's curvature.
RESIDUAL_STEP = 1e-4
#: The wider perturbation whose residual is reported as the linear range.
LINEAR_RANGE_STEP = 1e-3
#: Relative Frobenius residual per block above which the linearisation
#: is refused by name. Measured 2026-09-28 at RESIDUAL_STEP: c172p
#: longitudinal 3.0e-3 (the Q-row alpha entry differs by 0.114 rad/s^2
#: per rad, 0.33 percent, between the two routes; consistent with
#: FGStateSpace::run() re-settling the propeller with GetSteadyState() at
#: each perturbed point, where this module holds the rpm), lateral
#: 1.1e-5; A320 2.3e-9 and 7.1e-7; B747 measured in tests/test_modes.py.
RESIDUAL_BOUND = 1e-2

#: What is written to perturb each classical state, in the order written,
#: and what restores the others the way FGStateSpace does.
_STATE_IC = {
    "Vt": "ic/vt-fps", "Alpha": "ic/alpha-rad", "Theta": "ic/gamma-rad",
    "Q": "ic/q-rad_sec", "Beta": "ic/beta-rad", "Phi": "ic/phi-rad",
    "P": "ic/p-rad_sec", "R": "ic/r-rad_sec",
}
_STATE_READ = {
    "Vt": "velocities/vt-fps", "Alpha": "aero/alpha-rad",
    "Theta": "attitude/theta-rad", "Q": "velocities/q-rad_sec",
    "Beta": "aero/beta-rad", "Phi": "attitude/phi-rad",
    "P": "velocities/p-rad_sec", "R": "velocities/r-rad_sec",
}
_DERIVATIVE_PROPERTIES = (
    "velocities/u-fps", "velocities/v-fps", "velocities/w-fps", "velocities/vt-fps",
    "accelerations/udot-ft_sec2", "accelerations/vdot-ft_sec2", "accelerations/wdot-ft_sec2",
    "aero/alphadot-rad_sec", "velocities/thetadot-rad_sec", "accelerations/qdot-rad_sec2",
    "aero/betadot-rad_sec", "velocities/phidot-rad_sec", "accelerations/pdot-rad_sec2",
    "accelerations/rdot-rad_sec2",
)


class ModesError(FDMError):
    """A modal analysis refused by name (``modes.*``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


@dataclass(frozen=True)
class Residual:
    """The independent check of JSBSim's Jacobian, per classical block."""

    step: float
    longitudinal: float      # relative Frobenius, this module's A vs JSBSim's
    lateral: float
    max_abs: float           # largest single-entry difference, JSBSim units
    max_abs_entry: Tuple[str, str]
    bound: float

    @property
    def ok(self) -> bool:
        return (self.longitudinal <= self.bound) and (self.lateral <= self.bound)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step, "scheme": "two-point central difference through ic/ + run_ic()",
            "metric": "||A_measured - A_jsbsim||_F / ||A_jsbsim||_F per 4x4 block, JSBSim units",
            "longitudinal": self.longitudinal, "lateral": self.lateral,
            "max_abs": self.max_abs, "max_abs_entry": list(self.max_abs_entry),
            "bound": self.bound, "ok": self.ok,
        }


@dataclass(frozen=True)
class LinearModel:
    """JSBSim's linear model about the trim, with the SI classical blocks."""

    method: str
    state_names: Tuple[str, ...]        # JSBSim's, full
    state_units: Tuple[str, ...]
    input_names: Tuple[str, ...]
    input_units: Tuple[str, ...]
    A_full: np.ndarray                   # JSBSim units
    B_full: np.ndarray
    x0: np.ndarray
    u0: np.ndarray
    A_lon: np.ndarray                    # SI, LONGITUDINAL_STATES
    A_lat: np.ndarray                    # SI, LATERAL_STATES
    residual: Optional[Residual] = None
    linear_range: Optional[Dict[str, float]] = None
    disturbance: Optional[Dict[str, float]] = None
    step: float = JSBSIM_STEP
    scheme: str = JSBSIM_SCHEME

    def index(self, name: str) -> int:
        return self.state_names.index(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "step": self.step,
            "scheme": self.scheme,
            "states": {"longitudinal": list(LONGITUDINAL_STATES),
                       "lateral": list(LATERAL_STATES)},
            "units": {n: SI_UNITS[n] for n in CLASSICAL_STATES},
            "A_longitudinal": self.A_lon.tolist(),
            "A_lateral": self.A_lat.tolist(),
            "full": {
                "names": list(self.state_names), "units": list(self.state_units),
                "inputs": list(self.input_names), "input_units": list(self.input_units),
                "A": self.A_full.tolist(), "B": self.B_full.tolist(),
                "x0": self.x0.tolist(), "u0": self.u0.tolist(),
                "note": "JSBSim's own units (ft/s, rad, rad/s, rev/min, ft); "
                        "the classical blocks above are these rows and columns in SI",
            },
            "residual": None if self.residual is None else self.residual.to_dict(),
            "linear_range": self.linear_range,
            "disturbance": self.disturbance,
        }


def _executive(fdm):
    """The ``FGFDMExec`` behind a :class:`FlightDynamics`.

    Reached the way :mod:`core.fdm.trim` is handed it by the wrapper:
    inside the package, for a read-only analysis that gets its own
    instance. Nothing outside ``core/fdm`` does this.
    """
    exec_ = getattr(fdm, "_exec", None)
    if exec_ is None:
        raise ModesError("modes.linearization",
                         f"{fdm!r} carries no JSBSim executive to linearise")
    return exec_


def classical_block(A: np.ndarray, names: Sequence[str],
                    states: Sequence[str]) -> np.ndarray:
    """The rows and columns of ``states`` out of JSBSim's full matrix, in SI.

    The similarity transform ``T A T^-1`` with ``T`` the unit scale of
    each state (ft/s -> m/s for Vt, 1 otherwise) leaves the eigenvalues
    unchanged and puts the entries in SI.
    """
    idx = [list(names).index(s) for s in states]
    block = np.asarray(A, dtype=float)[np.ix_(idx, idx)]
    scale = np.array([FT_TO_M if s == "Vt" else 1.0 for s in states])
    return (scale[:, None] * block) / scale[None, :]


def read_derivatives(props) -> np.ndarray:
    """The eight classical state derivatives from the property tree,
    JSBSim units, in :data:`CLASSICAL_STATES` order."""
    g = props.get
    u, v, w, vt = g("velocities/u-fps"), g("velocities/v-fps"), g("velocities/w-fps"), g("velocities/vt-fps")
    ud, vd, wd = (g("accelerations/udot-ft_sec2"), g("accelerations/vdot-ft_sec2"),
                  g("accelerations/wdot-ft_sec2"))
    return np.array([
        (u * ud + v * vd + w * wd) / vt,
        g("aero/alphadot-rad_sec"), g("velocities/thetadot-rad_sec"),
        g("accelerations/qdot-rad_sec2"),
        g("aero/betadot-rad_sec"), g("velocities/phidot-rad_sec"),
        g("accelerations/pdot-rad_sec2"), g("accelerations/rdot-rad_sec2"),
    ])


class _Perturber:
    """Sets one classical state through ``ic/`` the way FGStateSpace does
    and re-initialises; restores the trim state on request."""

    def __init__(self, fdm, x0: Dict[str, float], psi0: float) -> None:
        self.fdm = fdm
        self.exec_ = _executive(fdm)
        self.x0 = dict(x0)
        self.psi0 = psi0
        self.base = {
            "ic/vt-fps": x0["Vt"], "ic/alpha-rad": x0["Alpha"], "ic/theta-rad": x0["Theta"],
            "ic/q-rad_sec": x0["Q"], "ic/beta-rad": x0["Beta"], "ic/psi-true-rad": psi0,
            "ic/phi-rad": x0["Phi"], "ic/p-rad_sec": x0["P"], "ic/r-rad_sec": x0["R"],
        }

    def _run_ic(self) -> None:
        if not self.exec_.run_ic():
            raise ModesError("modes.linearization", "run_ic() failed while perturbing the state")
        self.fdm.props.refresh()

    def restore(self) -> None:
        self.fdm.props.set_many(self.base)
        self._run_ic()

    def set(self, state: str, value: float) -> None:
        props = self.fdm.props
        props.set_many(self.base)
        if state == "Alpha":
            # FGStateSpace::Alpha::set: alpha, then beta, psi and theta put back.
            props.set("ic/alpha-rad", value)
            props.set("ic/beta-rad", self.x0["Beta"])
            props.set("ic/psi-true-rad", self.psi0)
            props.set("ic/theta-rad", self.x0["Theta"])
        elif state == "Theta":
            # FGStateSpace::Theta::set: gamma = theta - alpha, alpha kept.
            props.set("ic/gamma-rad", value - self.x0["Alpha"])
        elif state == "Beta":
            props.set("ic/beta-rad", value)
            props.set("ic/psi-true-rad", self.psi0)
        else:
            props.set(_STATE_IC[state], value)
        self._run_ic()

    def achieved(self, state: str) -> float:
        return self.fdm.props.get(_STATE_READ[state])


def measure_jacobian(perturber: _Perturber, step: float) -> np.ndarray:
    """The 8x8 classical Jacobian by two-point central differences at
    ``step`` (JSBSim units), read from the property tree."""
    J = np.zeros((8, 8))
    for j, state in enumerate(CLASSICAL_STATES):
        x = perturber.x0[state]
        perturber.set(state, x + step)
        if abs(perturber.achieved(state) - (x + step)) > 0.1 * step:
            raise ModesError("modes.linearization",
                             f"perturbing {state} by {step:g} achieved "
                             f"{perturber.achieved(state) - x:g}; the ic/ route did not take")
        f_plus = read_derivatives(perturber.fdm.props)
        perturber.set(state, x - step)
        f_minus = read_derivatives(perturber.fdm.props)
        J[:, j] = (f_plus - f_minus) / (2.0 * step)
    return J


def _relative_residual(J_measured: np.ndarray, J_jsbsim: np.ndarray,
                       rows: slice) -> float:
    ref = np.linalg.norm(J_jsbsim[rows, rows])
    diff = np.linalg.norm(J_measured[rows, rows] - J_jsbsim[rows, rows])
    return float(diff / ref) if ref > 0.0 else float("inf")


def linearize(fdm, residual_step: float = RESIDUAL_STEP,
              residual_bound: float = RESIDUAL_BOUND,
              linear_range_step: float = LINEAR_RANGE_STEP) -> LinearModel:
    """JSBSim's linear model about the trimmed state, checked and in SI.

    Raises :class:`ModesError` by name: ``modes.untrimmed`` when the FDM
    has not been trimmed, ``modes.linearization`` when JSBSim's
    linearisation is unavailable or its state lacks the classical eight,
    ``modes.residual`` when the independent Jacobian disagrees with
    JSBSim's beyond ``residual_bound``.
    """
    if not getattr(fdm, "is_trimmed", False):
        raise ModesError("modes.untrimmed",
                         f"{fdm!r} is not trimmed; a linearisation about an "
                         f"arbitrary state describes no flight condition")
    try:
        import jsbsim
        FGLinearization = jsbsim.FGLinearization
    except (ImportError, AttributeError) as exc:
        raise ModesError("modes.linearization",
                         f"the installed jsbsim exposes no FGLinearization: {exc}") from exc

    exec_ = _executive(fdm)
    props = fdm.props
    props.require(_DERIVATIVE_PROPERTIES)
    xdot_before = read_derivatives(props)

    lin = FGLinearization(exec_)
    names = tuple(lin.x_names)
    missing = [s for s in CLASSICAL_STATES if s not in names]
    if missing or "Psi" not in names:
        raise ModesError("modes.linearization",
                         f"JSBSim's state {names} lacks {missing or ['Psi']}; "
                         f"the classical blocks cannot be assembled")
    A_full = np.array(lin.system_matrix, dtype=float)
    B_full = np.array(lin.input_matrix, dtype=float)
    x0 = np.array(lin.x0, dtype=float)
    u0 = np.array(lin.u0, dtype=float)
    if not (np.all(np.isfinite(A_full)) and np.all(np.isfinite(B_full))):
        raise ModesError("modes.linearization", "JSBSim's linear model carries a non-finite entry")

    idx = {s: names.index(s) for s in CLASSICAL_STATES}
    x0_classical = {s: float(x0[idx[s]]) for s in CLASSICAL_STATES}
    J_jsbsim = A_full[np.ix_([idx[s] for s in CLASSICAL_STATES],
                             [idx[s] for s in CLASSICAL_STATES])]

    perturber = _Perturber(fdm, x0_classical, float(x0[names.index("Psi")]))
    J_measured = measure_jacobian(perturber, residual_step)
    J_wide = measure_jacobian(perturber, linear_range_step)
    perturber.restore()
    xdot_after = read_derivatives(props)

    lon, lat = slice(0, 4), slice(4, 8)
    diff = np.abs(J_measured - J_jsbsim)
    worst = np.unravel_index(int(diff.argmax()), diff.shape)
    residual = Residual(
        step=residual_step,
        longitudinal=_relative_residual(J_measured, J_jsbsim, lon),
        lateral=_relative_residual(J_measured, J_jsbsim, lat),
        max_abs=float(diff.max()),
        max_abs_entry=(CLASSICAL_STATES[worst[0]], CLASSICAL_STATES[worst[1]]),
        bound=residual_bound,
    )
    linear_range = {
        "step": linear_range_step,
        "longitudinal": _relative_residual(J_wide, J_jsbsim, lon),
        "lateral": _relative_residual(J_wide, J_jsbsim, lat),
        "note": "reported, not bounded: the same residual at a wider perturbation "
                "says how far the linear model predicts the nonlinear derivatives",
    }
    disturbance = {
        "max_abs_xdot_change": float(np.max(np.abs(xdot_after - xdot_before))),
        "unit": "JSBSim state-derivative units (ft/s^2, rad/s, rad/s^2)",
        "note": "the change linearising and restoring left in this executive's "
                "derivatives; why the run's own FDM is never linearised",
    }
    model = LinearModel(
        method="jsbsim.FGLinearization",
        state_names=names, state_units=tuple(lin.x_units),
        input_names=tuple(lin.u_names), input_units=tuple(lin.u_units),
        A_full=A_full, B_full=B_full, x0=x0, u0=u0,
        A_lon=classical_block(A_full, names, LONGITUDINAL_STATES),
        A_lat=classical_block(A_full, names, LATERAL_STATES),
        residual=residual, linear_range=linear_range, disturbance=disturbance,
    )
    check_residual(residual)
    return model


def check_residual(residual: Residual) -> None:
    """Refuse by name a residual beyond its bound."""
    if not residual.ok:
        raise ModesError(
            "modes.residual",
            f"the independent Jacobian differs from JSBSim's by "
            f"{residual.longitudinal:.3e} (longitudinal) and {residual.lateral:.3e} "
            f"(lateral) relative Frobenius at step {residual.step:g}; the bound is "
            f"{residual.bound:g}; the largest entry difference is {residual.max_abs:.3e} "
            f"at {residual.max_abs_entry}")
