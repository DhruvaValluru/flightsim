"""The weather look the renderer draws: one card block from the spec.

The engine side of the weather the physics already flies
(FlightSimVisualScene.cpp ``ApplyWeatherLook``). Absent-canonical: a spec
that states none of it writes no block and its card is unchanged. VISUAL
ONLY -- nothing here enters the flight model; every value is read from a
spec field the physics or the look already carries:

* ``surface`` -- the spec's ground-cover word (core/environment/surface.py
  SURFACE_CLASSES), or None when unspecified. On the flat scene the host
  draws the ground with ``M_Ground_<Surface>`` (procedural, or the fetched
  Poly Haven texture: scripts/fetch_ground_textures.py); a georeferenced
  scene keeps its imagery and ignores the word.
* ``storm`` -- ``thunderstorm`` / ``tornado`` from ``weather_event``, or
  None: storm clouds (a low, thick, dense layer when the look carries
  none), rain shafts under the cell and lightning flashes, all beauty-only.
* ``rain_rate_mmh`` -- the stated ``environment.precipitation_rate_mmh``;
  under a thunderstorm with no stated rate, STORM_RAIN_MMH (a stated
  visual default, recorded as such in ``rain_source``). Drives the lens
  drops and the shafts' density.
* ``wetness`` -- 0..1 for the ground materials' puddles and the terrain's
  existing Wetness scalar: ``min(1, rate / WET_AT_MMH)`` (a stated
  mapping: a surface is fully wet from 4 mm/h), or the rain block's
  stated runway condition (``wet`` 0.8, ``standing_water`` 1.0).
* ``ice_eta_max`` -- the icing block's resolved eta_max (0 = none); the
  host scales the aircraft's ice overlay by eta(t) / ICE_FULL_ETA per step.
* ``seed`` -- the spec's seed: the lightning schedule and the shafts'
  placement are deterministic in it (Gate 10-R).

Not claimed: any of these looks is measured against a photograph; the
lightning schedule is not a model of charge; the shafts are not a model
of the rain field; the ice overlay is not an accretion shape.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

CARD_KEYS = ("surface", "storm", "rain_rate_mmh", "rain_source", "wetness", "ice_eta_max",
             "seed")
#: The thunderstorm's visual rain rate when the spec states none (heavy rain).
STORM_RAIN_MMH = 40.0
#: A surface reads fully wet from this rate (stated).
WET_AT_MMH = 4.0
#: The runway words' wetness (the rain block, core/environment/rain.py).
RUNWAY_WETNESS = {"dry": 0.0, "wet": 0.8, "standing_water": 1.0}
#: eta at which the ice overlay is fully opaque (icing's "severe" word).
ICE_FULL_ETA = 0.30
STORMS = ("thunderstorm", "tornado")


def _surface(spec) -> Optional[str]:
    word = str(getattr(spec.surface, "value", "unspecified"))
    return None if word in ("", "unspecified", "None") else word


def _storm(spec) -> Optional[str]:
    event = str(getattr(spec.weather_event, "value", "none"))
    return event if event in STORMS else None


def _ice(spec) -> float:
    block = getattr(spec, "icing", None)
    if block is None or block.is_default():
        return 0.0
    return float(block.resolved()["eta_max"].value or 0.0)


def weather_look_card_block(spec) -> Optional[Dict[str, Any]]:
    """The ``weather_look`` block, keys in CARD_KEYS order, or None when
    the spec states no surface, storm, rain, wet runway or ice."""
    surface = _surface(spec)
    storm = _storm(spec)
    rate = spec.precipitation_rate_mmh.value
    source = "environment.precipitation_rate_mmh" if rate is not None else None
    if rate is None and storm == "thunderstorm":
        rate, source = STORM_RAIN_MMH, "thunderstorm visual default"
    wetness = 0.0 if rate is None else min(1.0, float(rate) / WET_AT_MMH)
    rain_block = getattr(spec, "rain", None)
    if rain_block is not None and not rain_block.is_default():
        word = rain_block.runway_condition.value
        if word in RUNWAY_WETNESS:
            wetness = max(wetness, RUNWAY_WETNESS[word])
    ice = _ice(spec)
    if surface is None and storm is None and rate is None and wetness == 0.0 and ice == 0.0:
        return None
    block = {"surface": surface, "storm": storm,
             "rain_rate_mmh": None if rate is None else float(rate), "rain_source": source,
             "wetness": wetness, "ice_eta_max": ice, "seed": int(spec.seed.value)}
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"weather_look card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    return block
