"""Surface classes: what the ground cover does to the air, by the book.

A surface word in the spec ("over grasslands", "over the ocean") changes the
air in exactly the two ways this repository already models, and no others:

* **Roughness** -- the neutral surface-layer log profile
  (:class:`~core.environment.wind.LogProfileWind`), with z0 from the
  Davenport-Wieringa classes (Stull 1988 Table 9-6). Wind decays honestly
  toward the ground below the 300 m surface-layer top and is HELD at the
  spec's own wind above it, so cruise flight over any surface flies the
  spec's stated wind.
* **Thermal forcing** -- Allen's convective updraft model
  (NASA/TM-2006-214019), with (w*, zi) anchored on the TM's OWN Table 2
  monthly climatology for Desert Rock NV. Desert uses the July mean
  directly -- the TM's site is desert. Every other land class borrows a
  monthly mean AS A STATED PROXY (the basis string says so); the ocean
  gets no thermals at all rather than an invented weak value.

What a surface class deliberately does NOT claim: no ground-cover visuals
(a flat scene still renders the labeled slab until a measured visual pass
exists -- see BRIEF_PHASE9), no building-resolved flow for "city" (z0 is
the only aerodynamic statement about buildings; the urban heat island is
NOT separately modelled and the basis string says so), no stability
corrections (LogProfileWind is neutral-layer by construction, stated in
its own docstring).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .thermals import SEASON_TABLE
from .wind import LogProfileWind


@dataclass(frozen=True)
class SurfaceClass:
    word: str                 # the spec vocabulary word
    roughness: str            # LogProfileWind.ROUGHNESS_M key
    z0_m: float               # copied out for display/provenance
    #: (w*, zi) for AllenThermals, or None for "no thermals modelled".
    thermals: Optional[Tuple[float, float]]
    thermal_basis: str
    description: str


def _z0(key: str) -> float:
    return LogProfileWind.ROUGHNESS_M[key]


_TM = "NASA/TM-2006-214019 Table 2 (Desert Rock NV climatology)"

SURFACE_CLASSES: Dict[str, SurfaceClass] = {
    "grassland": SurfaceClass(
        "grassland", "open", _z0("open"), SEASON_TABLE["spring"],
        f"{_TM} April mean as a stated proxy for temperate grassland",
        "open flat terrain, grass"),
    "desert": SurfaceClass(
        "desert", "smooth", _z0("smooth"), SEASON_TABLE["summer"],
        f"{_TM} July mean; the TM's own site is desert",
        "featureless arid land"),
    "ocean": SurfaceClass(
        "ocean", "water", _z0("water"), None,
        "no convective thermals modelled over water (rather than an "
        "invented weak value)",
        "open water"),
    "forest": SurfaceClass(
        "forest", "forest", _z0("forest"), SEASON_TABLE["autumn"],
        f"{_TM} October mean as a stated proxy for forest canopy",
        "closed forest canopy"),
    "city": SurfaceClass(
        "city", "city", _z0("city"), SEASON_TABLE["spring"],
        f"{_TM} April mean as a stated proxy; the urban heat island is "
        f"NOT separately modelled",
        "centres of large towns and cities"),
}

#: The spec default: no ground cover stated, no surface coupling attached.
UNSPECIFIED = "unspecified"


def surface_class(word: str) -> Optional[SurfaceClass]:
    """The class for a spec word, or None for the default. Raises on an
    unknown word -- the validator turns that into a named refusal rather
    than letting an unmodelled surface run as if it were modelled."""
    if word == UNSPECIFIED:
        return None
    if word not in SURFACE_CLASSES:
        raise ValueError(
            f"unknown surface {word!r}; modelled classes: "
            f"{sorted(SURFACE_CLASSES)} (or {UNSPECIFIED!r})")
    return SURFACE_CLASSES[word]
