"""Steady wind and the atmospheric boundary layer."""

from __future__ import annotations

import math
from typing import Any, Dict, List

from .base import Position, Term, WindNED, WindProvider

#: Vague strength words. Values are the mid-points of the Beaufort-derived
#: bands used in aviation weather reporting, not invented numbers.
STRENGTH_KT = {
    "calm": 0.0,
    "light": 8.0,
    "moderate": 15.0,
    "strong": 25.0,
    "gale": 40.0,
}
STRENGTH_STD = "Beaufort scale mid-band, as used in aviation surface wind reporting"


class SteadyWind(WindProvider):
    """A uniform wind field. The simplest possible provider, and the reference.

    Direction is meteorological: the bearing the wind blows *from*.
    """

    name = "steady_wind"

    def __init__(self, speed_mps: float, from_deg: float, down_mps: float = 0.0) -> None:
        if speed_mps < 0:
            raise ValueError(f"wind speed cannot be negative: {speed_mps}")
        self.speed_mps = float(speed_mps)
        self.from_deg = float(from_deg) % 360.0
        self.down_mps = float(down_mps)
        self._vector = WindNED.from_meteorological(self.speed_mps, self.from_deg,
                                                   self.down_mps)

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        return self._vector

    def vocabulary(self) -> List[Term]:
        return [
            Term(phrase, value, "kt", STRENGTH_STD, (0.0, 100.0))
            for phrase, value in STRENGTH_KT.items()
        ]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "speed_mps": self.speed_mps, "from_deg": self.from_deg,
                "down_mps": self.down_mps}


class BoundaryLayerWind(WindProvider):
    """Wind shear through the atmospheric boundary layer.

    Wind speed falls toward the surface because of friction. The engineering
    standard is the power law

        V(h) = V_ref * (h / h_ref) ** alpha

    with the exponent set by surface roughness. This is the form used in
    MIL-F-8785C for the mean wind profile and in wind-engineering practice
    generally; the logarithmic law is more accurate very near the ground but
    needs a roughness length rather than an exponent and is undefined at h = 0.

    Above the boundary layer depth the profile is flat: the free atmosphere is
    not slowed by the surface.
    """

    name = "boundary_layer"

    #: Power-law exponent by terrain type. ASCE 7 / Davenport roughness classes.
    EXPONENT = {
        "water": 0.10,
        "open": 0.14,          # open country, the classic 1/7 power law
        "suburban": 0.22,
        "urban": 0.33,
        "mountainous": 0.28,
    }
    STANDARD = "power law V ~ h^alpha; exponents from ASCE 7 / Davenport roughness classes"

    def __init__(
        self,
        reference_speed_mps: float,
        from_deg: float,
        reference_height_m: float = 10.0,
        terrain: str = "open",
        layer_depth_m: float = 600.0,
    ) -> None:
        if terrain not in self.EXPONENT:
            raise ValueError(
                f"unknown terrain {terrain!r}; known: {sorted(self.EXPONENT)}"
            )
        if reference_height_m <= 0:
            raise ValueError("reference height must be positive")
        self.reference_speed_mps = float(reference_speed_mps)
        self.from_deg = float(from_deg) % 360.0
        self.reference_height_m = float(reference_height_m)
        self.terrain = terrain
        self.layer_depth_m = float(layer_depth_m)
        self.alpha = self.EXPONENT[terrain]

    def speed_at(self, agl_m: float) -> float:
        """Wind speed at a height above ground."""
        height = max(agl_m, 0.0)
        if height >= self.layer_depth_m:
            height = self.layer_depth_m
        # Below the reference height the power law still applies; it simply
        # tends to zero at the surface, which is the physical no-slip condition.
        return self.reference_speed_mps * (
            max(height, 0.0) / self.reference_height_m
        ) ** self.alpha

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        return WindNED.from_meteorological(self.speed_at(position.agl_m),
                                           self.from_deg)

    def vocabulary(self) -> List[Term]:
        return [
            Term(f"{terrain} terrain", alpha, None, self.STANDARD, (0.05, 0.40),
                 note="boundary-layer power-law exponent")
            for terrain, alpha in self.EXPONENT.items()
        ]

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "reference_speed_mps": self.reference_speed_mps,
                "reference_height_m": self.reference_height_m,
                "from_deg": self.from_deg, "terrain": self.terrain,
                "alpha": self.alpha, "layer_depth_m": self.layer_depth_m}
