"""Airframe-extent terrain contact: the wings feel the mountain, not just the CG.

JSBSim's ground model asks one question -- terrain elevation under the
aircraft -- so a banked wingtip could pass through a slope while the physics,
looking straight down from the CG, saw hundreds of metres of clearance. This
module closes that gap the honest way: the wing is sampled at fixed span
stations (each wingtip and each mid-semi-span point), every station's position
is computed from the aircraft's own attitude and the FDM's own wingspan
(``metrics/bw-ft``, verified against the live property catalog of the pinned
JSBSim on 2026-08-11), and a station below the local terrain surface ends the
run as a named terrain impact.

What this is NOT: a mesh intersection. Four point samples along the span
cannot feel a rock spire between stations, and the fuselage, nose and tail are
not sampled (JSBSim has no length metric to derive them from; inventing one
would be fabrication). The claim is exactly "no sampled span station is below
the terrain surface", and every consumer states it that way.

Stations outside the raster are unchecked -- there is no data to check
against, and :meth:`Heightfield.elevation_at`'s edge clamp would otherwise
manufacture a cliff at the raster boundary.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from ..fdm import units as u
from .ground import TerrainGround

# Fractions of the semi-span, negative = left wing. The CG (0.0) is
# deliberately absent: terrain under the aircraft itself is JSBSim's own
# ground model, already wired through TerrainGround / the UE collision mesh.
STATION_FRACTIONS: Tuple[Tuple[str, float], ...] = (
    ("left wingtip", -1.0),
    ("left mid-span", -0.5),
    ("right mid-span", 0.5),
    ("right wingtip", 1.0),
)


@dataclass(frozen=True)
class TerrainImpact:
    """One span station below the terrain surface. The run ends here."""

    station: str
    time_s: float
    penetration_m: float          # terrain elevation minus station altitude
    station_altitude_m: float     # MSL
    terrain_m: float              # MSL, bilinear at the station's position
    lat_deg: float                # aircraft (not station) position
    lon_deg: float

    def describe(self) -> str:
        return (f"terrain impact: {self.station} {self.penetration_m:.1f} m "
                f"below the surface at t={self.time_s:.2f} s "
                f"(station {self.station_altitude_m:.0f} m MSL, terrain "
                f"{self.terrain_m:.0f} m MSL at "
                f"{self.lat_deg:.5f} N, {self.lon_deg:.5f} E)")


class TerrainImpactError(RuntimeError):
    """Raised by the headless runner when a span station enters the terrain.

    An impact is a crash, and the runner's contract is to raise rather than
    hand back a clean recording of a failure -- the same posture as the
    closure assertion and the UE host's ``Crashed`` refusal.
    """

    def __init__(self, impact: TerrainImpact) -> None:
        super().__init__(impact.describe())
        self.impact = impact


def station_offsets_ned(roll_deg: float, pitch_deg: float, heading_deg: float,
                        wingspan_m: float) -> Iterable[
                            Tuple[str, float, float, float]]:
    """(name, north_m, east_m, down_m) of each span station relative to the CG.

    A span station is the body-frame vector (0, y, 0), y = fraction x b/2,
    rotated to NED by the standard ZYX Euler sequence (yaw psi, pitch theta,
    roll phi) -- the second column of the body-to-NED direction cosine
    matrix. Level flight puts the tips on the horizon; a right roll puts the
    right tip below the CG by y*cos(theta)*sin(phi). Same math, same order,
    in the UE host's CheckAirframeContact -- change one, change both.
    """
    phi = math.radians(roll_deg)
    theta = math.radians(pitch_deg)
    psi = math.radians(heading_deg)
    sin_phi, cos_phi = math.sin(phi), math.cos(phi)
    sin_theta, cos_theta = math.sin(theta), math.cos(theta)
    sin_psi, cos_psi = math.sin(psi), math.cos(psi)
    half_span = wingspan_m / 2.0
    for name, fraction in STATION_FRACTIONS:
        y = fraction * half_span
        north = y * (sin_theta * sin_phi * cos_psi - cos_phi * sin_psi)
        east = y * (sin_theta * sin_phi * sin_psi + cos_phi * cos_psi)
        down = y * (cos_theta * sin_phi)
        yield name, north, east, down


class AirframeContact:
    """Per-step span-station contact check against a baked raster."""

    def __init__(self, ground: TerrainGround, wingspan_m: float) -> None:
        if wingspan_m <= 0.0:
            raise ValueError(
                f"wingspan {wingspan_m} m: the FDM reported no usable span, "
                f"and a zero-span check silently reduces to the CG check "
                f"that already exists. Refusing to pretend otherwise.")
        self.ground = ground
        self.wingspan_m = float(wingspan_m)

    @classmethod
    def from_fdm(cls, ground: TerrainGround, fdm) -> "AirframeContact":
        """Span from the FDM's own model: metrics/bw-ft (verified live)."""
        return cls(ground, u.ft_to_m(fdm.props.get("metrics/bw-ft")))

    def check(self, state, time_s: float) -> Optional[TerrainImpact]:
        """None if every in-raster station clears the surface, else the impact."""
        x, y = self.ground.project(state.lat_deg, state.lon_deg)
        heightfield = self.ground.heightfield
        for name, north, east, down in station_offsets_ned(
                state.roll_deg, state.pitch_deg, state.heading_deg,
                self.wingspan_m):
            px, py = x + east, y + north
            if not heightfield.contains(px, py):
                continue
            terrain_m = heightfield.elevation_at(px, py)
            station_altitude_m = state.altitude_m - down
            if station_altitude_m < terrain_m:
                return TerrainImpact(
                    station=name, time_s=float(time_s),
                    penetration_m=terrain_m - station_altitude_m,
                    station_altitude_m=station_altitude_m,
                    terrain_m=terrain_m,
                    lat_deg=state.lat_deg, lon_deg=state.lon_deg)
        return None

    def provenance(self) -> dict:
        return {
            "name": "airframe_contact",
            "wingspan_m": self.wingspan_m,
            "stations": [name for name, _ in STATION_FRACTIONS],
            "claim": "no sampled span station below the terrain surface; "
                     "point samples at span stations, not a mesh "
                     "intersection; fuselage/nose/tail not sampled",
        }
