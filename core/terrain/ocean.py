"""Open-ocean stages: real places whose ground IS the flat slab.

GLO-30 has no tile over open ocean (core.terrain.glo30.dynamic_location:
"a cell the bucket lacks -- open ocean -- fails the fetch by name"), so an
ocean scene can never be baked. Far from land it needs no bake either:
the sea surface is the geoid, orthometric 0 m, which is exactly the flat
slab at a 0 m datum. Each point here was checked against the Copernicus
bucket's own tile list (tileList.txt, 2026-10-08): no GLO-30 tile -- so
no land -- in the 7 x 7 one-degree cells around it (about +/-330 km), far
past the horizon from any altitude this simulator flies a camera at.

Not claimed: waves, tides or the mean dynamic topography (the sea surface
departs from the geoid by about a metre); the ocean surface class's own
roughness and thermals are what the physics feels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class OceanPoint:
    """An open-ocean place, as a scene origin."""

    key: str
    title: str
    lat: float
    lon: float
    #: Prompt words that pick this ocean over the default.
    words: tuple


#: The cells checked (each +/-3 deg around the point) had no GLO-30 tile.
OPEN_OCEAN: Dict[str, OceanPoint] = {
    "atlantic": OceanPoint("atlantic", "the open North Atlantic", 35.0, -45.0,
                           ("atlantic",)),
    "pacific": OceanPoint("pacific", "the open North Pacific", 30.0, -150.0,
                          ("pacific",)),
    "indian": OceanPoint("indian", "the open Indian Ocean", -20.0, 75.0,
                         ("indian ocean",)),
}
#: The ocean a vague prompt ("over the ocean") gets.
DEFAULT_OCEAN = "atlantic"
#: How far a spec's origin may sit from a listed point and still be on it.
OCEAN_TOLERANCE_DEG = 0.05


def pick_open_ocean(prompt: Optional[str]) -> OceanPoint:
    """The ocean the prompt names among the listed ones, else the default."""
    text = (prompt or "").lower()
    for point in OPEN_OCEAN.values():
        if any(word in text for word in point.words):
            return point
    return OPEN_OCEAN[DEFAULT_OCEAN]


def open_ocean_at(lat: float, lon: float) -> Optional[OceanPoint]:
    """The listed open-ocean point these coordinates sit on, or None."""
    for point in OPEN_OCEAN.values():
        if (abs(float(lat) - point.lat) <= OCEAN_TOLERANCE_DEG
                and abs(float(lon) - point.lon) <= OCEAN_TOLERANCE_DEG):
            return point
    return None
