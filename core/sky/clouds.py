"""The sky plan's cloud fields: type, coverage, density, detail, seed (sky step 5).

Sky step 5 of the owner's X-Plane-12 brief (docs/visual/XPLANE_SKY_BRIEF.md;
design docs/visual/XPLANE_SKY_DESIGN.md §7). :func:`plan_cloud_block` turns
what :func:`core.sky.plan.plan_sky` already knows (the storm word, the layer's
placement, the instant and the place) plus an optional ERA5 cloud-cover dict
into the extra keys of ``sky.json`` "clouds". Everything is pure: same inputs,
same bytes.

BEAUTY ONLY. The measure host (FlightSimSky.cpp ``FFlightSimSky::Build``)
reads ``enabled`` / ``bottom_km`` / ``thickness_km`` only, so a measure render
is byte-identical with or without these keys. ``FFlightSimWorldBeauty::
ApplyClouds`` (FlightSimClouds.cpp, ``-quality=beauty``) reads them through
``FFlightSimSkyPlan::Load`` (sky step 2) by one precedence law: ``-cloud-type=``
> the card's ``look.clouds[0]`` > this block > the shape's default
(``core.scene.world_beauty.layer_source``). The type words and the volumetric
row each draws are defined once, in :mod:`core.scene.world_beauty`
(``PLAN_CLOUD_TYPES``, ``PLAN_CLOUD_SHAPES``, ``CLOUDS``).

Every threshold here is a look choice: UNCALIBRATED. Nothing here draws by
itself and nothing here has been rendered (UNMEASURED; the Windows commands
are in docs/VISUAL_FIDELITY_PLAN.md §8 "Sky step 5": rounds 104/105 for the
altocumulus row under -cloud-type=, and the web-app /compile + /run lines for
a dated prompt that exercise this plan path, ERA5 -> sky.json ->
FFlightSimSkyPlan -> ApplyClouds, with the sky.json and render.json keys to
read).
"""

from __future__ import annotations

import zlib
from typing import Any, Dict, Optional, Tuple

from core.scene.world_beauty import (
    CLOUD_MARCH_SWITCH_WORDS, CLOUD_OVERCAST_COVER, CLOUDS,
    FAIR_CLOUD_SHADOW_MIN_COVER, PLAN_CLOUD_SHAPES, PLAN_CLOUD_TYPES,
    STRATOCUMULUS_MIN_COVER,
)

__all__ = [
    "ALTOCUMULUS_MIN_MID_COVER", "CIRRUS_MIN_HIGH_COVER", "CLOUD_COVER_KEYS",
    "CUMULUS_MIN_LOW_COVER", "DEFAULT_CLOUD_TYPE", "DEFAULT_MARCH_TIER",
    "PLAN_CLOUD_TYPES", "STORM_CLOUD_TYPE", "cloud_type_from_cover",
    "coverage_source_text", "default_cloud_type", "derive_seed",
    "plan_cloud_block",
]

#: The fractions an ERA5 cover dict carries (core.environment.era5
#: fetch_reanalysis_cloud_cover): low / mid / high level cloud fraction and
#: the total, each 0..1.
CLOUD_COVER_KEYS: Tuple[str, ...] = ("low", "mid", "high", "total")

#: Without a cover: the type the default beauty frame has drawn since round 95
#: (the plan's VISUAL ONLY slab reshaped to the cumulus row), so a plan without
#: weather data draws exactly what it drew before this step, by construction.
DEFAULT_CLOUD_TYPE = "cumulus"
#: A thunderstorm or tornado spec: the storm's own deck, whatever ERA5 says
#: (the storm is the spec's word; the host's storm preset stands above the
#: plan's type anyway, world_beauty.layer_source).
STORM_CLOUD_TYPE = "nimbostratus"
#: The step 3 cvar set the plan asks for (``-cloud-march=`` words; "auto" is the
#: GPU class, the only word the plan writes: the plan knows no GPU).
DEFAULT_MARCH_TIER = "auto"

#: Type law thresholds (cloud_type_from_cover), on hourly level fractions.
#: UNCALIBRATED: the two Open-Meteo endpoints disagree hour by hour on these
#: fractions (design §0.11), so no threshold here is a measured boundary.
#: A mid-level fraction this high, above the low one, reads as an altocumulus
#: sheet rather than scattered cumulus.
ALTOCUMULUS_MIN_MID_COVER = 0.3
#: Any lower fraction at least this (world_beauty.FAIR_CLOUD_SHADOW_MIN_COVER:
#: the cover at which a layer starts to matter to the ground) draws cumulus.
CUMULUS_MIN_LOW_COVER = FAIR_CLOUD_SHADOW_MIN_COVER
#: High cloud alone at least this is a cirrus sky (no volumetric layer; step 6's
#: sheet draws the cirrus_coverage).
CIRRUS_MIN_HIGH_COVER = 0.2


def _fraction(value: Any) -> float:
    number = float(value)
    if number != number:   # NaN
        raise ValueError("a cloud fraction is NaN")
    return min(max(number, 0.0), 1.0)


def default_cloud_type(storm: bool) -> str:
    """The type a plan without a cover draws: nimbostratus for a storm spec,
    else :data:`DEFAULT_CLOUD_TYPE` (round 95's frame by construction)."""
    return STORM_CLOUD_TYPE if storm else DEFAULT_CLOUD_TYPE


def cloud_type_from_cover(low: float, mid: float, high: float, storm: bool) -> Tuple[str, float, str]:
    """``(cloud_type, coverage, basis)`` from the three level fractions.

    In order (the first that fires; every threshold UNCALIBRATED): a storm spec
    -> nimbostratus at its row's default cover; ``max(low, mid)`` >=
    CLOUD_OVERCAST_COVER -> overcast at that max; low >= STRATOCUMULUS_MIN_COVER
    -> stratocumulus at the low fraction; mid >= ALTOCUMULUS_MIN_MID_COVER and
    mid > low -> altocumulus at the mid fraction; low >= CUMULUS_MIN_LOW_COVER ->
    cumulus at the low fraction; high >= CIRRUS_MIN_HIGH_COVER -> cirrus at the
    high fraction (no volumetric layer); else clear at 0. The coverage is the
    fraction of the level that named the type, 0..1."""
    low, mid, high = _fraction(low), _fraction(mid), _fraction(high)
    if storm:
        return (STORM_CLOUD_TYPE, CLOUDS[STORM_CLOUD_TYPE]["default_cover"],
                f"storm spec: {STORM_CLOUD_TYPE} at its row's default cover; the ERA5 fractions are recorded, not used")
    if max(low, mid) >= CLOUD_OVERCAST_COVER:
        return ("overcast", max(low, mid),
                f"max(low, mid) {max(low, mid):.2f} >= CLOUD_OVERCAST_COVER {CLOUD_OVERCAST_COVER:g}")
    if low >= STRATOCUMULUS_MIN_COVER:
        return ("stratocumulus", low, f"low {low:.2f} >= STRATOCUMULUS_MIN_COVER {STRATOCUMULUS_MIN_COVER:g}")
    if mid >= ALTOCUMULUS_MIN_MID_COVER and mid > low:
        return ("altocumulus", mid,
                f"mid {mid:.2f} >= ALTOCUMULUS_MIN_MID_COVER {ALTOCUMULUS_MIN_MID_COVER:g} and above low {low:.2f}")
    if low >= CUMULUS_MIN_LOW_COVER:
        return ("cumulus", low, f"low {low:.2f} >= CUMULUS_MIN_LOW_COVER {CUMULUS_MIN_LOW_COVER:g}")
    if high >= CIRRUS_MIN_HIGH_COVER:
        return ("cirrus", high,
                f"high {high:.2f} >= CIRRUS_MIN_HIGH_COVER {CIRRUS_MIN_HIGH_COVER:g} with low {low:.2f} and mid "
                f"{mid:.2f} below their thresholds: no volumetric layer")
    return ("clear", 0.0, f"low {low:.2f}, mid {mid:.2f}, high {high:.2f} all below their thresholds")


def derive_seed(instant_utc: str, lat: float, lon: float, altitude_msl_m: float) -> int:
    """A deterministic seed from the inputs the plan already has (the instant,
    the place and the altitude), used when the caller states none. CRC-32 of a
    fixed ASCII rendering: the same bytes on every platform."""
    text = f"{instant_utc}|{float(lat):.6f}|{float(lon):.6f}|{float(altitude_msl_m):.1f}"
    return int(zlib.crc32(text.encode("ascii")) & 0x7FFFFFFF)


def coverage_source_text(cover: Optional[Dict[str, Any]], weather_date: Optional[str],
                         cloud_type: str, note: Optional[str]) -> str:
    """The provenance string recorded as ``coverage_source``: the provider's
    source for a fetched cover, else which default and why. A fetched cover
    is stamped with ITS ``date`` and ``hour_utc`` (the UTC day and hour the
    web app asked the archive for: the plan instant's, which is the day after
    or before ``weather_date`` when the local time crosses the UTC day
    boundary), never with ``weather_date`` itself; the default texts name
    ``weather_date`` because that is what the spec stated."""
    if cover is not None:
        source = str(cover.get("source") or "ERA5 reanalysis via Open-Meteo archive")
        when = str(cover.get("date") or weather_date or "")
        hour = cover.get("hour_utc")
        stamp = f", {when}T{int(hour):02d}Z" if hour is not None and when else (f", {when}" if when else "")
        return f"{source}{stamp}, cloud_cover_low/mid/high"
    row = f"CLOUDS[{cloud_type}].default_cover"
    if note:
        return f"default ({note}): {row}"
    if not weather_date or weather_date == "none":
        return f"default (no weather_date): {row}"
    return f"default (no cloud cover given for weather_date {weather_date}): {row}"


def plan_cloud_block(*, storm: bool, weather_date: Optional[str], instant_utc: str, lat: float, lon: float,
                     altitude_msl_m: float, cloud_cover: Optional[Dict[str, Any]] = None,
                     cloud_cover_note: Optional[str] = None, seed: Optional[int] = None) -> Dict[str, Any]:
    """The step 5 keys of the plan's "clouds" block (added to ``enabled``,
    ``bottom_km``, ``thickness_km`` and ``basis``, which the caller computes
    exactly as before).

    ``cloud_cover``: the provider's dict (``low``, ``mid``, ``high``, ``total``
    fractions, ``source``, ``date`` and ``hour_utc`` -- the UTC day and hour
    of the plan's instant, which may differ from ``weather_date``) or None for
    the stated default; ``cloud_cover_note`` says why there is none when a date was given
    (an unreachable archive, a sampled cover that wins, a synthesised ridge).
    ``seed``: the spec's (recorded ``"spec.seed"``), else derived from the
    inputs (:func:`derive_seed`). ``density`` and ``detail`` are 1.0: multipliers
    of the type's CLOUDS row (design D2: one source of truth per type), so the
    default frame is the row itself. Pure: same inputs, same bytes."""
    inputs = None
    if cloud_cover is not None:
        inputs = {key: round(_fraction(cloud_cover.get(key, 0.0)), 4) for key in CLOUD_COVER_KEYS}
        cloud_type, coverage, type_basis = cloud_type_from_cover(
            inputs["low"], inputs["mid"], inputs["high"], storm)
        cirrus = inputs["high"]
    else:
        cloud_type = default_cloud_type(storm)
        coverage = CLOUDS[cloud_type]["default_cover"]
        type_basis = (f"default: no cloud cover (storm spec: {STORM_CLOUD_TYPE})" if storm
                      else f"default: no cloud cover ({DEFAULT_CLOUD_TYPE}, the round-95 frame by construction)")
        cirrus = 0.0
    assert cloud_type in PLAN_CLOUD_TYPES
    if seed is None:
        seed_value, seed_source = derive_seed(instant_utc, lat, lon, altitude_msl_m), \
            "derived: CRC-32 of instant_utc, latitude, longitude, altitude (no spec seed given)"
    else:
        seed_value, seed_source = int(seed), "spec.seed"
    shape = PLAN_CLOUD_SHAPES[cloud_type]
    return {
        "cloud_type": cloud_type,
        "coverage": round(float(coverage), 4),
        "density": 1.0,
        "detail": 1.0,
        "cirrus_coverage": round(float(cirrus), 4),
        "coverage_source": coverage_source_text(cloud_cover, weather_date, cloud_type, cloud_cover_note),
        "cover_inputs": inputs,
        "cloud_type_basis": type_basis,
        "volumetric_row": shape,
        "seed": seed_value,
        "seed_source": seed_source,
        "march_tier": DEFAULT_MARCH_TIER,
        "march_tier_basis": ("the sky step 3 cvar set the beauty host applies (-cloud-march="
                             + "|".join(CLOUD_MARCH_SWITCH_WORDS)
                             + "); auto is the GPU class; a -cloud-march= word on the render command line wins"),
        "fields_basis": ("BEAUTY ONLY (FFlightSimWorldBeauty::ApplyClouds under -quality=beauty); the measure "
                         "host reads enabled/bottom_km/thickness_km only. density and detail are multipliers "
                         "of core/scene/world_beauty.py CLOUDS[cloud_type] (1 = the row). UNCALIBRATED; "
                         "UNMEASURED until a Windows render"),
    }
