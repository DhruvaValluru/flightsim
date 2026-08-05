"""Exception types for the FDM layer.

Every one of these exists because the previous build had a silent fallback in
the same place (ASSUMPTIONS: §2.7 -- no silent fallbacks, anywhere).
"""


class FDMError(Exception):
    """Base for every error raised by the FDM layer."""


class AircraftResolutionError(FDMError):
    """The requested aircraft could not be resolved to exactly one model.

    Raised instead of falling back to a similarly-named model. The previous
    build resolved an F-15 request onto f16 aerodynamics and reported success
    (§1.4); there is no code path here that can substitute an airframe.
    """


class AircraftMismatchError(FDMError):
    """The model JSBSim actually loaded is not the model that was requested.

    This is the direct §1.4 regression guard. It compares the name reported by
    ``FGFDMExec.get_model_name()`` against the requested name after load.
    """


class UnknownPropertyError(FDMError):
    """A property name does not exist in the loaded model's catalog.

    JSBSim's property tree *silently creates* nodes on write: setting
    ``totally/made/up/property`` succeeds, reads back the value you wrote, and
    has no effect on the simulation. Reading a name that was never written
    returns 0.0 rather than raising. A typo in a wind property therefore
    produces a run that advertises a condition it does not have -- exactly the
    unverifiable-conditions failure of §1.6. Every access goes through the
    catalog so a typo is an error, not a lie.
    """


class ReadOnlyPropertyError(FDMError):
    """Attempted to write a property the model exposes as read-only.

    JSBSim ignores such writes and reports nothing, so the caller would
    otherwise believe it had commanded something it had not.
    """


class TrimError(FDMError):
    """Trim did not converge, or converged on a state that is not an equilibrium.

    JSBSim logs ``Trim Failed!!!`` and continues with partial state. In a
    research run that is a hard stop (§3.1, §5 Phase 0): an untrimmed aircraft
    makes the entire recording an initialisation transient (§1.1).
    """


class SimulationError(FDMError):
    """The integrator failed to advance, or produced a non-finite state."""
