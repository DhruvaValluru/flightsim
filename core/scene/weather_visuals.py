"""The look coupling: ONE table from spec values to engine parameters.

Contracts §5.4 (brainstorm §5.4): the visual parameters a render is
given -- fog, clouds, precipitation, sun, cloud drift, exposure -- are
computed here from the SAME numbers the physics and the record use, so
"a low-visibility draw looks like one in the image as well as in the
wind field". The engine consumes what the CARD carries: the block this
module builds (``look_block``) is recorded under the card's
``randomization.look`` (``core.scenario.randomization.card_block``) and
every row is meant to be read by the render pass from that one record
rather than from a flag list rebuilt by thirteen callers (contracts §9).
The four Phase 10 flags (``RENDER_FLAGS``) stay for back-compatibility
and carry the same numbers.

Every row is a pure function with the formula stated beside it, so a
test can re-implement each row from the documentation and compare
(the producer/verifier rule). What each row IS and IS NOT claimed to
be:

* ``fog_extinction_per_m`` -- Koschmieder's relation between the
  meteorological visibility V and the extinction coefficient beta,
  beta = 3.912 / V (the 2 % contrast threshold: ln(1/0.02) = 3.912),
  in 1/m for V in km: beta = 3.912 / (1000 * V). The number is written
  to the engine's ``FogDensity`` in the block's own documented unit
  ("1/m", ``core.scenario.randomization`` fog_density; the Phase 10
  ``-fog-density`` flag carried that unit, calibrated at 0.0012 clear /
  0.010 hazy). Whether ``UExponentialHeightFogComponent::FogDensity``
  IS a per-metre extinction is NOT claimed here: Gate 6's extinction
  clause measures it from pixels (the ``max_extinction_ratio`` pattern),
  and that measurement, not this table, decides.
* ``aerosol`` -- the dimensionless Mie scattering scale that would put
  the SAME extinction into ``USkyAtmosphereComponent`` alone:
  beta_km / UE_MIE_EXTINCTION_PER_KM (Epic's documented sea-level Mie
  scattering + absorption at scale 1). Recorded so the Look lane can
  choose which component carries the haze; driving BOTH at once double
  counts and is the Look lane's Gate 6 clause to settle -- not
  claimed here.
* ``clouds`` -- one layer ``{cover, base_m, top_m}`` from the spec's
  cloud fields; no layer when the cover is zero. A top the spec does
  not state is base + ``DEFAULT_CLOUD_THICKNESS_M`` (stated, not
  measured). Open-Meteo serves cover per layer but no base height, so a
  base the policy does not draw is ``DEFAULT_CLOUD_BASE_M``.
* ``precipitation`` / ``wetness`` -- the word and a 0..1 material
  scalar (``WETNESS``); rain and snow also FLOOR the visibility
  (``PRECIPITATION_VISIBILITY_FLOOR_KM``) before the fog row. Particles
  are NOT drawn this phase (no Niagara asset exists);
  ``not_claimed`` says so in the block.
* ``cloud_drift_mps`` / ``cloud_drift_from_deg`` -- the wind speed in
  m/s (1 kt = 0.514444 m/s) and its meteorological direction, for the
  cloud material's per-tick offset.
* ``ev100`` -- per camera, from the spec's exposure triple:
  EV100 = log2(N^2 / t) - log2(ISO / 100). Replaces the Phase 10
  exposure bias when the Look lane's manual exposure lands; the bias
  is still recorded beside it.
* the sun row (elevation, compass azimuth, engine azimuth) is the
  existing ``core.scenario.randomization`` computation and is added by
  ``render_look`` there, not duplicated here.

Not claimed anywhere in this module: moon, stars, precipitation
particles, sea state, foliage sway (``NOT_CLAIMED``).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

#: Koschmieder: ln(1 / 0.02) for the 2 % contrast threshold.
KOSCHMIEDER_CONSTANT = 3.912
#: Epic's documented sea-level Mie extinction at MieScatteringScale 1:
#: scattering 0.003996 + absorption 0.000444 per km.
UE_MIE_EXTINCTION_PER_KM = 0.003996 + 0.000444
#: The commandlet's default FogDensity (FlightSimVisualScene.h): what a
#: render gets when no look is given.
ENGINE_FOG_DENSITY_DEFAULT = 0.0025
#: Cloud layer geometry the spec does not state (metres): stated, not
#: measured.
DEFAULT_CLOUD_BASE_M = 1500.0
DEFAULT_CLOUD_THICKNESS_M = 1000.0
#: 0..1 wetness scalar per precipitation word (roughness/specular on
#: the terrain and airframe materials).
WETNESS = {"none": 0.0, "rain": 1.0, "snow": 0.6}
#: Visibility ceiling under precipitation, km (a rain draw is never a
#: 60 km day).
PRECIPITATION_VISIBILITY_FLOOR_KM = {"none": None, "rain": 10.0, "snow": 5.0}
KT_TO_MPS = 0.514444
#: What this phase does NOT draw, stated in every block.
NOT_CLAIMED = ("precipitation_particles", "moon", "stars", "sea_state",
               "foliage_sway")

#: The card ``look`` keys this module produces, and the engine
#: parameter each drives (contracts §5.4 table). The sun keys are added
#: by ``core.scenario.randomization.render_look``.
ENGINE_PARAMETERS: Dict[str, str] = {
    "fog_extinction_per_m": "UExponentialHeightFogComponent::FogDensity",
    "aerosol": "USkyAtmosphereComponent Mie scattering scale",
    "clouds": "UVolumetricCloudComponent layer bottom altitude / thickness "
              "/ coverage (cloud shadows on)",
    "precipitation": "visibility floor (word recorded; no particles)",
    "wetness": "Wetness scalar on the terrain and airframe materials",
    "cloud_drift_mps": "UVolumetricCloudComponent material wind offset per "
                       "tick",
    "cloud_drift_from_deg": "the drift's meteorological direction",
    "ev100": "manual exposure AEM_Manual (CameraShutterSpeed / CameraISO / "
             "DepthOfFieldFstop) per camera",
    "sun_elevation_deg": "SunLight rotation pitch (-elevation)",
    "sun_azimuth_deg": "compass azimuth, recorded",
    "engine_sun_azimuth_deg": "SunLight rotation yaw (+180)",
}
#: The Phase 10 flags, kept: look key -> commandlet flag. ``card.look``
#: overrides them when present.
RENDER_FLAGS: Dict[str, str] = {
    "sun_elev": "-sun-elev", "sun_azim": "-sun-azim",
    "exposure_bias": "-exposure-bias", "fog_density": "-fog-density",
}
#: Where the block lands in the run card.
CARD_LOOK_KEY = "look"


def fog_extinction_per_m(visibility_km: float) -> float:
    """Koschmieder: beta = 3.912 / V, V in km -> beta in 1/m."""
    v = float(visibility_km)
    if not v > 0.0:
        raise ValueError(f"visibility must be positive km, not {v!r}")
    return KOSCHMIEDER_CONSTANT / (1000.0 * v)


def visibility_km_for_extinction(beta_per_m: float) -> float:
    """The inverse: V = 3.912 / (1000 beta)."""
    b = float(beta_per_m)
    if not b > 0.0:
        raise ValueError(f"extinction must be positive 1/m, not {b!r}")
    return KOSCHMIEDER_CONSTANT / (1000.0 * b)


def aerosol_scale(visibility_km: float) -> float:
    """The Mie scattering scale carrying beta alone:
    (3.912 / V) / UE_MIE_EXTINCTION_PER_KM."""
    return (KOSCHMIEDER_CONSTANT / float(visibility_km)) / UE_MIE_EXTINCTION_PER_KM


def visibility_floor_km(visibility_km: float, precipitation: str) -> float:
    """The visibility after the precipitation floor:
    min(V, floor[word]); an unknown word refuses."""
    if precipitation not in PRECIPITATION_VISIBILITY_FLOOR_KM:
        raise ValueError(f"precipitation word {precipitation!r} is not one "
                         f"of {sorted(PRECIPITATION_VISIBILITY_FLOOR_KM)}")
    floor = PRECIPITATION_VISIBILITY_FLOOR_KM[precipitation]
    v = float(visibility_km)
    return v if floor is None else min(v, floor)


def cloud_layers(cloud_cover: float, cloud_base_m: Optional[float] = None,
                 cloud_top_m: Optional[float] = None) -> List[Dict[str, float]]:
    """``[{cover, base_m, top_m}]`` -- one layer, or none at zero cover.
    Base defaults to DEFAULT_CLOUD_BASE_M, top to base +
    DEFAULT_CLOUD_THICKNESS_M."""
    cover = float(cloud_cover)
    if not 0.0 <= cover <= 1.0:
        raise ValueError(f"cloud cover is a fraction 0..1, not {cover!r}")
    if cover <= 0.0:
        return []
    base = DEFAULT_CLOUD_BASE_M if cloud_base_m is None else float(cloud_base_m)
    top = base + DEFAULT_CLOUD_THICKNESS_M if cloud_top_m is None else float(cloud_top_m)
    if not top > base:
        raise ValueError(f"cloud top {top} m is not above its base {base} m")
    return [{"cover": round(cover, 4), "base_m": round(base, 1),
             "top_m": round(top, 1)}]


def wetness(precipitation: str) -> float:
    if precipitation not in WETNESS:
        raise ValueError(f"precipitation word {precipitation!r} is not one "
                         f"of {sorted(WETNESS)}")
    return WETNESS[precipitation]


def cloud_drift_mps(wind_speed_kt: float) -> float:
    """kt -> m/s (1 kt = 1852 m / 3600 s = 0.514444 m/s)."""
    return round(float(wind_speed_kt) * KT_TO_MPS, 4)


def ev100(aperture_f: float, shutter_s: float, iso: float) -> float:
    """EV100 = log2(N^2 / t) - log2(ISO / 100)."""
    n, t, s = float(aperture_f), float(shutter_s), float(iso)
    if not (n > 0 and t > 0 and s > 0):
        raise ValueError("aperture, shutter and ISO must be positive")
    return round(math.log2(n * n / t) - math.log2(s / 100.0), 4)


def look_block(values: Dict[str, Any]) -> Dict[str, Any]:
    """The look from plain spec values (no spec object here). Keys read:
    ``visibility_km`` (or ``fog_density`` in 1/m when no visibility was
    drawn), ``cloud_cover``, ``cloud_base_m``, ``cloud_top_m``,
    ``precipitation``, ``wind_speed_kt``, ``wind_direction_deg``,
    ``exposures`` ({camera_id: (aperture_f, shutter_s, iso)}). Absent
    keys take the documented defaults (clear sky, no precipitation,
    calm)."""
    precipitation = str(values.get("precipitation", "none"))
    visibility = values.get("visibility_km")
    if visibility is None:
        density = values.get("fog_density")
        visibility = (visibility_km_for_extinction(density)
                      if density is not None and float(density) > 0.0
                      else visibility_km_for_extinction(ENGINE_FOG_DENSITY_DEFAULT))
    visibility = visibility_floor_km(visibility, precipitation)
    beta = fog_extinction_per_m(visibility)
    return {
        "visibility_km": round(float(visibility), 4),
        "fog_extinction_per_m": float(f"{beta:.6g}"),
        "aerosol": round(aerosol_scale(visibility), 4),
        "clouds": cloud_layers(values.get("cloud_cover", 0.0),
                               values.get("cloud_base_m"),
                               values.get("cloud_top_m")),
        "precipitation": precipitation,
        "wetness": wetness(precipitation),
        "cloud_drift_mps": cloud_drift_mps(values.get("wind_speed_kt", 0.0)),
        "cloud_drift_from_deg": float(values.get("wind_direction_deg", 0.0)) % 360.0,
        "ev100": {str(camera_id): ev100(*triple)
                  for camera_id, triple in
                  dict(values.get("exposures") or {}).items()},
        "not_claimed": list(NOT_CLAIMED),
    }
