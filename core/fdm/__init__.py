"""Core flight dynamics. Zero Unreal dependency (§2.9)."""

from .aircraft import AircraftModel, available, resolve
from .errors import (
    AircraftMismatchError,
    AircraftResolutionError,
    FDMError,
    ReadOnlyPropertyError,
    SimulationError,
    TrimError,
    UnknownPropertyError,
)
from .fdm import DEFAULT_RATE_HZ, FlightDynamics
from .properties import PropertyAccess
from .state import AircraftState
from .trim import TrimDrift, TrimMode, mode_for, verify_trim_holds

__all__ = [
    "AircraftModel",
    "AircraftMismatchError",
    "AircraftResolutionError",
    "AircraftState",
    "DEFAULT_RATE_HZ",
    "FDMError",
    "FlightDynamics",
    "PropertyAccess",
    "ReadOnlyPropertyError",
    "SimulationError",
    "TrimDrift",
    "TrimError",
    "TrimMode",
    "UnknownPropertyError",
    "available",
    "mode_for",
    "resolve",
    "verify_trim_holds",
]
