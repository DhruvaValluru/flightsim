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


class LogProfileWind(WindProvider):
    """Surface-layer wind shear by the logarithmic law, with a roughness length.

    The log law is the similarity-theory result for the neutrally stratified
    surface layer:

        u(z) = (u* / k) * ln(z / z0)

    (Stull 1988, *An Introduction to Boundary Layer Meteorology*, §9.7;
    Monin-Obukhov similarity in the neutral limit). Parameterised here by a
    reference wind at a reference height, which eliminates the friction
    velocity:

        u(z) = U_ref * ln(z / z0) / ln(z_ref / z0)

    Validity, stated: the surface layer -- roughly the lowest 10% of the
    boundary layer, taken here as :data:`SURFACE_LAYER_TOP_M` = 300 m AGL.
    Above it the profile is HELD at u(300): the free-atmosphere wind is the
    steady provider's business, and pretending the log law extends upward
    would be using the formula outside its derivation. Below z0 the wind is
    zero (aerodynamically, the flow is between roughness elements). Neutral
    stratification is assumed; stability corrections (Monin-Obukhov psi
    terms) are NOT modelled, and docs/VALIDITY.md says so.

    Distinct from :class:`BoundaryLayerWind` (the engineering power law with
    an exponent): this is the form the brief's microburst regime wants
    composed with the downburst outflow, where the shear in the lowest
    hundred metres is the phenomenon.
    """

    name = "log_profile_wind"

    #: Davenport-Wieringa roughness classes, z0 in metres (Stull 1988,
    #: Table 9-6; WMO Guide No. 8). A subset with unambiguous words.
    ROUGHNESS_M = {
        "water": 0.0002,
        "open": 0.03,          # open flat terrain, grass
        "suburban": 0.5,
        "forest": 1.0,
    }
    STANDARD = ("log wind profile u(z) = (u*/k) ln(z/z0), neutral surface "
                "layer; z0 from Davenport-Wieringa roughness classes "
                "(Stull 1988 Table 9-6)")

    #: The surface layer: where the log law is derived and where it stays.
    SURFACE_LAYER_TOP_M = 300.0

    def __init__(
        self,
        reference_speed_mps: float,
        from_deg: float,
        reference_height_m: float = 10.0,
        terrain: str = "open",
    ) -> None:
        if terrain not in self.ROUGHNESS_M:
            raise ValueError(
                f"unknown terrain {terrain!r}; known: {sorted(self.ROUGHNESS_M)}"
            )
        z0 = self.ROUGHNESS_M[terrain]
        if reference_height_m <= z0:
            raise ValueError(
                f"reference height {reference_height_m} m must sit above the "
                f"roughness length z0 = {z0} m"
            )
        self.reference_speed_mps = float(reference_speed_mps)
        self.from_deg = float(from_deg) % 360.0
        self.reference_height_m = float(reference_height_m)
        self.terrain = terrain
        self.z0_m = z0

    def speed_at(self, agl_m: float) -> float:
        """Wind speed at a height above ground, m/s."""
        z = min(max(agl_m, 0.0), self.SURFACE_LAYER_TOP_M)
        if z <= self.z0_m:
            return 0.0
        return (self.reference_speed_mps
                * math.log(z / self.z0_m)
                / math.log(self.reference_height_m / self.z0_m))

    def wind_at(self, position: Position, time_s: float) -> WindNED:
        return WindNED.from_meteorological(self.speed_at(position.agl_m),
                                           self.from_deg)

    def vocabulary(self) -> List[Term]:
        return [
            Term(f"{terrain} terrain", z0, "m", self.STANDARD, (0.0001, 2.0),
                 note="roughness length z0; profile held above "
                      f"{self.SURFACE_LAYER_TOP_M:g} m AGL, zero below z0, "
                      "neutral stratification assumed")
            for terrain, z0 in self.ROUGHNESS_M.items()
        ]

    def card_block(self) -> Dict[str, float]:
        """The run card's ``log_profile`` block for the UE host's port."""
        return {
            "reference_speed_mps": self.reference_speed_mps,
            "from_deg": self.from_deg,
            "reference_height_m": self.reference_height_m,
            "z0_m": self.z0_m,
            "surface_layer_top_m": self.SURFACE_LAYER_TOP_M,
        }

    def provenance(self) -> Dict[str, Any]:
        return {**super().provenance(),
                "reference_speed_mps": self.reference_speed_mps,
                "reference_height_m": self.reference_height_m,
                "from_deg": self.from_deg, "terrain": self.terrain,
                "z0_m": self.z0_m,
                "surface_layer_top_m": self.SURFACE_LAYER_TOP_M}


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
