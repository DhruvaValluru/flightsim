"""The card's ``weather`` block: the rain, the storm's body, its lightning and its thunder.

One place assembles what a render needs to draw weather as weather rather
than as a fog colour: the 3D rain (core/scene/rain_particles.py), the
cumulonimbus with its anvil and rain shaft (core/scene/storm_cell.py), the
lightning (core/scene/lightning.py) and the thunder's constants
(core/scene/thunder.py). Every number is computed here, once, from the
spec; the host (ue/Plugins/FlightSimBridge FlightSimWeather) draws exactly
the card and derives nothing but the per-frame state (where the camera is,
what the shutter integrates).

ABSENT-CANONICAL like the world look: the block exists only when the spec
states ``environment.precipitation_rate_mmh`` or a ``thunderstorm``
weather event; any other spec gets no card key, byte for byte.

* rain:      a stated rate, or a thunderstorm (its shaft's rain; outside
             the shaft only the stated rate falls, ``ambient_fraction``);
* cell, lightning, thunder: a thunderstorm only, centred on the card's
             ``downburst`` block (the microburst the physics flies).

Nothing here reaches an equation of motion: the block is VISUAL, and its
couplings run one way -- the storm's physics places and sizes the storm's
body, never the reverse.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from . import lightning, rain_particles, storm_cell, thunder

#: The block's version and its keys, in their fixed order (each only when present).
VERSION = 1
CARD_KEYS = ("version", "rain", "cell", "lightning", "thunder")

#: What each element is graded by on Windows (docs/WEATHER.md).
WINDOWS_CLAUSES: Dict[str, str] = {
    "rain": "WX.1 drops on/off: a ground camera at rest, the drawn streaks' mean length within "
            "30 % of v_t t_shutter for the card's D0, the label passes byte-identical",
    "rain_motion": "WX.2 a chase camera at the spec's airspeed: streaks along the relative "
                   "velocity, a replay byte-identical (Gate 10-R)",
    "splash": "WX.3 a ground camera: splash crowns in the near field, none above max_agl_m",
    "cell": "WX.4 the tower's base within 10 % of base_m in a level shot; the shaft's "
            "transmittance across its diameter against storm_cell.transmittance",
    "lightning": "WX.5 a frame whose exposure covers a return stroke shows the channel; a "
                 "frame between strokes does not (lightning.window_power)",
    "thunder": "WX.6 the interactive window: the first clap of a flash after r_min / c, the "
               "host's selftest samples equal to the card's (relative 1e-9)",
}


def _stated(q) -> bool:
    return q is not None and q.value is not None


def weather_stated(spec) -> bool:
    rate = getattr(spec, "precipitation_rate_mmh", None)
    event = getattr(spec, "weather_event", None)
    return _stated(rate) or (event is not None and str(event.value) == "thunderstorm")


def wind_enu_mps(spec) -> tuple:
    """The stated wind as a vector it blows TOWARD (east, north, up)."""
    from ..fdm import units as u

    speed = u.kt_to_mps(float(spec.wind_speed.value))
    from_rad = math.radians(float(spec.wind_direction.value))
    return (-speed * math.sin(from_rad), -speed * math.cos(from_rad), 0.0)


def downburst_core_radius_m() -> float:
    """The core radius the thunderstorm composition flies (Downburst's default)."""
    from ..environment.downburst import Downburst

    return Downburst(0.0, 0.0).core_radius_m


def card_block(spec) -> Optional[Dict[str, Any]]:
    """The ``weather`` block in CARD_KEYS order, or None (absent-canonical)."""
    if not weather_stated(spec):
        return None
    from ..fdm import units as u

    storm = str(spec.weather_event.value) == "thunderstorm"
    rate_q = getattr(spec, "precipitation_rate_mmh", None)
    stated_rate = float(rate_q.value) if _stated(rate_q) else None
    seed = int(spec.seed.value)
    datum = float(spec.terrain_elevation.value)
    wind = wind_enu_mps(spec)
    airspeed = u.kt_to_mps(float(spec.airspeed.value))
    block: Dict[str, Any] = {"version": VERSION}
    cell = None
    if storm:
        cell = storm_cell.card_block(
            downburst_core_radius_m(), float(spec.latitude.value), datum,
            float(spec.wind_direction.value), math.hypot(wind[0], wind[1]), stated_rate, seed)
    if storm:
        shaft_rate = float(cell["shaft"]["rate_mmh"])
        block["rain"] = rain_particles.card_block(
            shaft_rate, cell["shaft"]["rate_source"], seed, float(spec.altitude.value), wind,
            airspeed, ambient_rate_mmh=stated_rate)
    else:
        block["rain"] = rain_particles.card_block(
            stated_rate, "stated", seed, float(spec.altitude.value), wind, airspeed)
    if storm:
        block["cell"] = cell
        block["lightning"] = lightning.card_block(seed, float(spec.duration.value), cell)
        block["thunder"] = thunder.card_block(datum)
    return block


def summary(block: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A compact record of the block (for a manifest or a log line)."""
    if block is None:
        return None
    out: Dict[str, Any] = {"version": block["version"]}
    rain = block.get("rain")
    if rain:
        out["rain"] = {"rate_mmh": rain["rate_mmh"], "rate_source": rain["rate_source"],
                       "particles": rain["particles"], "weight": rain["weight"]}
    if "cell" in block:
        cell = block["cell"]
        out["cell"] = {"base_m": cell["base_m"], "top_m": cell["top_m"],
                       "tower_radius_m": cell["tower_radius_m"]}
    if "lightning" in block:
        flashes = block["lightning"]["flashes"]
        out["lightning"] = {"flashes": len(flashes),
                            "cloud_to_ground": sum(1 for f in flashes if f["kind"] == "cg")}
    return out
