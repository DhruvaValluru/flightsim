"""The world's beauty look: atmosphere depth, cloud shapes, the tiles' grade and
wet response, the lightning's sky pulse, and the ground scatter's placement law.

Visual overhaul, world lane (2026-11-09). Everything here is BEAUTY ONLY:
``-quality=measure`` (every render Gate 6 passed on) never reaches it; the
render commandlet calls ``FFlightSimWorldBeauty::Build`` only under
``-quality=beauty`` (FlightSimClouds.cpp). Nothing here reaches an equation of
motion.

This module is the Python twin of the pure block in
``ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimClouds.cpp``
(between ``FLIGHTSIM-WORLD-PURE-BEGIN`` and ``FLIGHTSIM-WORLD-PURE-END``) and of
the placement law in ``FlightSimGroundDetail.cpp`` (its own pure block).
``tests/test_world_beauty.py`` compiles those blocks with the machine's C++
compiler and checks them against this file, number for number, so the two
cannot drift.

EVERY look value below is UNCALIBRATED: set by probe render on the render
machine. They were chosen on a Mac that cannot compile or render the bridge
(Xcode above UE 5.7's cap, no Cesium), from the literature's orders of
magnitude and the engine's own defaults, never from a frame. The probe that
should set each one is named in ``docs/visual/PROBE_LOG.md`` (## world). The
render records the row it used (``look_applied.world_beauty``), so a frame is
always traceable to its numbers, and ``-world-beauty-overrides=<json>``
replaces any of them at run time for a probe sweep without a rebuild
(``validate_overrides`` is the schema).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import tiles_delight
from .rain_field import MASK64, splitmix64, unit

# -- the atmosphere presets -------------------------------------------------------

#: The look presets, in the C++ enum's order (EFlightSimWorldPreset).
PRESETS: Tuple[str, ...] = ("clear", "hazy", "overcast", "rain", "storm")

#: Selection thresholds (select_preset). UNCALIBRATED: set by probe render on
#: the render machine.
HAZY_VISIBILITY_KM = 15.0
OVERCAST_COVER = 0.75

#: Koschmieder's contrast threshold: beta = 3.912 / V (Middleton 1952).
KOSCHMIEDER = 3.912
#: The engine's default Rayleigh extinction at its green channel (1/km,
#: SkyAtmosphereComponent.cpp: 0.013558), the part of the Koschmieder beta the
#: atmosphere already carries before any aerosol is added.
RAYLEIGH_GREEN_PER_KM = 0.013558
#: The engine's default Mie single-scattering albedo: 0.003996 / (0.003996 +
#: 0.000444) = 0.9 (SkyAtmosphereComponent.cpp). Kept, so only the amount of
#: aerosol changes, not its kind.
MIE_SINGLE_SCATTER_ALBEDO = 0.9
#: The shortest visibility the split is evaluated at (km); a fog bank below it
#: stays the height fog's.
MIN_VISIBILITY_KM = 0.05

#: Field order of one atmosphere row: the C++ FFlightSimAtmosphereRow's order.
ATMOSPHERE_FIELDS: Tuple[str, ...] = (
    "mie_scale_height_km",          # SetMieExponentialDistribution (engine default 1.2)
    "mie_anisotropy",               # SetMieAnisotropy (engine default 0.8)
    "mie_share",                    # share of the haze extinction moved from fog to Mie
    "mie_cap_per_km",               # the Mie extinction never exceeds this (1/km)
    "aerial_perspective_scale",     # SetAerialPespectiveViewDistanceScale (engine 1.0)
    "ground_albedo_r",              # SetGroundAlbedo, sRGB bytes: the horizon fill
    "ground_albedo_g",
    "ground_albedo_b",
    "vfog_distance_m",              # SetVolumetricFogDistance
    "vfog_scattering_distribution", # SetVolumetricFogScatteringDistribution (g)
    "vfog_extinction_scale",        # SetVolumetricFogExtinctionScale
    "cloud_bottom_occlusion",       # SetSkyLightCloudBottomOcclusion
    "rain_readability_gain",        # x the weather rain's weight (beauty only)
    "wetness_floor",                # the tiles' wetness at least this under the preset
    "tiles_dehaze",                 # dark-object subtraction of the baked imagery
    "tiles_saturation",             # luma-preserving saturation of the baked imagery
    "tiles_detail_strength",        # near-field detail normal strength
    "lightning_sky_gain",           # sky light x (1 + gain x flash) at a flash
)

#: UNCALIBRATED: set by probe render on the render machine (every number).
ATMOSPHERE: Dict[str, Dict[str, float]] = {
    "clear": dict(mie_scale_height_km=1.2, mie_anisotropy=0.80, mie_share=0.6, mie_cap_per_km=0.25,
                  aerial_perspective_scale=1.0, ground_albedo_r=92, ground_albedo_g=96,
                  ground_albedo_b=78, vfog_distance_m=8000.0, vfog_scattering_distribution=0.75,
                  vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.5, rain_readability_gain=1.0,
                  wetness_floor=0.0, tiles_dehaze=0.10, tiles_saturation=1.10,
                  tiles_detail_strength=0.6, lightning_sky_gain=0.0),
    "hazy": dict(mie_scale_height_km=1.6, mie_anisotropy=0.76, mie_share=0.6, mie_cap_per_km=0.6,
                 aerial_perspective_scale=1.15, ground_albedo_r=110, ground_albedo_g=110,
                 ground_albedo_b=100, vfog_distance_m=8000.0, vfog_scattering_distribution=0.7,
                 vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.5, rain_readability_gain=1.0,
                 wetness_floor=0.0, tiles_dehaze=0.06, tiles_saturation=1.06,
                 tiles_detail_strength=0.6, lightning_sky_gain=0.0),
    "overcast": dict(mie_scale_height_km=1.4, mie_anisotropy=0.70, mie_share=0.4, mie_cap_per_km=0.6,
                     aerial_perspective_scale=1.0, ground_albedo_r=80, ground_albedo_g=82,
                     ground_albedo_b=78, vfog_distance_m=6000.0, vfog_scattering_distribution=0.4,
                     vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.75, rain_readability_gain=1.0,
                     wetness_floor=0.0, tiles_dehaze=0.04, tiles_saturation=0.97,
                     tiles_detail_strength=0.5, lightning_sky_gain=0.0),
    "rain": dict(mie_scale_height_km=1.0, mie_anisotropy=0.65, mie_share=0.3, mie_cap_per_km=0.8,
                 aerial_perspective_scale=1.0, ground_albedo_r=64, ground_albedo_g=66,
                 ground_albedo_b=62, vfog_distance_m=4000.0, vfog_scattering_distribution=0.3,
                 vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.85, rain_readability_gain=1.5,
                 wetness_floor=0.6, tiles_dehaze=0.03, tiles_saturation=0.92,
                 tiles_detail_strength=0.5, lightning_sky_gain=0.0),
    "storm": dict(mie_scale_height_km=1.8, mie_anisotropy=0.65, mie_share=0.3, mie_cap_per_km=0.8,
                  aerial_perspective_scale=1.0, ground_albedo_r=52, ground_albedo_g=54,
                  ground_albedo_b=52, vfog_distance_m=4000.0, vfog_scattering_distribution=0.3,
                  vfog_extinction_scale=1.0, cloud_bottom_occlusion=0.9, rain_readability_gain=1.5,
                  wetness_floor=0.85, tiles_dehaze=0.03, tiles_saturation=0.90,
                  tiles_detail_strength=0.5, lightning_sky_gain=3.0),
}


def select_preset(storm: bool, rain_rate_mmh: float, precipitation_rain: bool,
                  cloud_cover: float, visibility_km: float) -> str:
    """The look preset for a card: a drawn or stated thunderstorm is ``storm``;
    any stated rain rate or a ``rain`` word is ``rain``; a deck of
    OVERCAST_COVER or more is ``overcast``; air under HAZY_VISIBILITY_KM is
    ``hazy``; anything else is ``clear``. A visibility of 0 or less means
    "not stated" and never selects ``hazy``."""
    if storm:
        return "storm"
    if rain_rate_mmh > 0.0 or precipitation_rain:
        return "rain"
    if cloud_cover >= OVERCAST_COVER:
        return "overcast"
    if 0.0 < visibility_km < HAZY_VISIBILITY_KM:
        return "hazy"
    return "clear"


def mie_split(visibility_km: float, share: float, cap_per_km: float) -> Dict[str, float]:
    """Move ``share`` of the air's haze from the height fog into the sky
    atmosphere's Mie layer, so distance turns hazy through the atmosphere's
    own scattering (the sun's forward glow, the bluing of far ridges) instead
    of a flat fog colour.

    beta = 3.912 / V (1/km, Koschmieder); the haze is beta less the Rayleigh the
    atmosphere already carries; Mie extinction = min(share x haze, cap), split
    by the engine's own single-scattering albedo. The fog keeps the rest: its
    density times ``fog_factor`` = 1 - mie / beta, so the extinction at the
    ground is the visibility's, counted once (the double count
    weather_visuals.py warns of is avoided by construction). Returns 1/km
    values and the factor."""
    visibility = max(float(visibility_km), MIN_VISIBILITY_KM)
    beta = KOSCHMIEDER / visibility
    haze = max(beta - RAYLEIGH_GREEN_PER_KM, 0.0)
    mie = min(max(float(share), 0.0) * haze, max(float(cap_per_km), 0.0))
    return {
        "beta_per_km": beta,
        "mie_extinction_per_km": mie,
        "mie_scattering_per_km": mie * MIE_SINGLE_SCATTER_ALBEDO,
        "mie_absorption_per_km": mie * (1.0 - MIE_SINGLE_SCATTER_ALBEDO),
        "fog_factor": 1.0 - (mie / beta if beta > 0.0 else 0.0),
    }


# -- the cloud presets -------------------------------------------------------------

CLOUD_PRESETS: Tuple[str, ...] = ("cumulus", "stratocumulus", "overcast", "nimbostratus")

#: Selection thresholds (select_cloud). UNCALIBRATED.
CLOUD_OVERCAST_COVER = 0.85
STRATOCUMULUS_MAX_THICKNESS_M = 900.0
STRATOCUMULUS_MIN_COVER = 0.5

CLOUD_FIELDS: Tuple[str, ...] = (
    "extinction_per_m",   # the cloud's extinction inside a full cell (1/m)
    "shape_scale_km",     # the base shape noise's feature size
    "detail_scale_km",    # the erosion noise's feature size
    "detail_erosion",     # how much the detail noise eats the edges (0..1)
    "bottom_softness",    # share of the layer's thickness the base fades over
    "top_rounding",       # share of the layer's thickness the top rounds over
    "coverage_contrast",  # how hard the coverage threshold cuts
    "default_cover",      # the cover a layer gets when the card states none (fair mode)
)

#: UNCALIBRATED: set by probe render on the render machine. The extinctions are
#: the literature's order for water clouds (0.02 to 0.1 /m: sigma = 3 LWC /
#: (2 rho r_e) with LWC 0.2 to 0.5 g/m^3, r_e 5 to 10 um), below the storm
#: tower's 0.19 /m (core/scene/storm_cell.py).
CLOUDS: Dict[str, Dict[str, float]] = {
    "cumulus": dict(extinction_per_m=0.05, shape_scale_km=2.5, detail_scale_km=0.35,
                    detail_erosion=0.35, bottom_softness=0.08, top_rounding=0.6,
                    coverage_contrast=1.6, default_cover=0.35),
    "stratocumulus": dict(extinction_per_m=0.04, shape_scale_km=4.0, detail_scale_km=0.5,
                          detail_erosion=0.25, bottom_softness=0.15, top_rounding=0.3,
                          coverage_contrast=1.3, default_cover=0.6),
    "overcast": dict(extinction_per_m=0.03, shape_scale_km=8.0, detail_scale_km=0.8,
                     detail_erosion=0.15, bottom_softness=0.2, top_rounding=0.15,
                     coverage_contrast=1.0, default_cover=0.95),
    "nimbostratus": dict(extinction_per_m=0.045, shape_scale_km=6.0, detail_scale_km=0.6,
                         detail_erosion=0.2, bottom_softness=0.1, top_rounding=0.4,
                         coverage_contrast=1.2, default_cover=0.98),
}

#: The fair-weather layer ``-beauty-clouds=fair`` adds when the card states no
#: cloud (a stated stylisation, recorded; never the default). UNCALIBRATED.
FAIR_LAYER = {"cover": 0.35, "base_m": 1500.0, "top_m": 2700.0}

#: The seeded noise offset spans this many km, so two seeds never share a sky.
CLOUD_SEED_SPAN_KM = 1000.0
#: The extinction scale on the material (1 = the row's 1/m read as the engine's
#: unit); the WX.4-style probe sets it. UNCALIBRATED.
CLOUD_EXTINCTION_SCALE = 1.0
#: A frame whose camera-to-aircraft path through a layer leaves less than this
#: estimated transmittance is flagged ``cloud_occludes_aircraft``. UNCALIBRATED.
OCCLUSION_FLAG_TRANSMITTANCE = 0.5


def select_cloud(cover: float, thickness_m: float, preset: str) -> str:
    """The cloud shape for a layer: the storm and rain presets draw
    nimbostratus; a deck of CLOUD_OVERCAST_COVER or more is overcast; a thin
    (<= STRATOCUMULUS_MAX_THICKNESS_M), broken (>= STRATOCUMULUS_MIN_COVER)
    layer is stratocumulus; anything else is cumulus."""
    if preset in ("storm", "rain"):
        return "nimbostratus"
    if cover >= CLOUD_OVERCAST_COVER:
        return "overcast"
    if thickness_m <= STRATOCUMULUS_MAX_THICKNESS_M and cover >= STRATOCUMULUS_MIN_COVER:
        return "stratocumulus"
    return "cumulus"


def cloud_seed_offset_km(seed: int) -> Tuple[float, float, float]:
    """The noise offset of a seeded sky: three uniforms of the card's seed
    (rain_field.unit, index 0, channels 0..2) times CLOUD_SEED_SPAN_KM."""
    return tuple(unit(int(seed), 0, channel) * CLOUD_SEED_SPAN_KM for channel in range(3))


def slab_path_m(a_z_m: float, b_z_m: float, length_m: float, base_m: float, top_m: float) -> float:
    """The length (m) of a straight segment of ``length_m`` from height a to
    height b that lies inside the slab [base, top]."""
    if not top_m > base_m or length_m <= 0.0:
        return 0.0
    if a_z_m == b_z_m:
        return length_m if base_m <= a_z_m <= top_m else 0.0
    t0 = (base_m - a_z_m) / (b_z_m - a_z_m)
    t1 = (top_m - a_z_m) / (b_z_m - a_z_m)
    lo, hi = min(t0, t1), max(t0, t1)
    lo, hi = max(lo, 0.0), min(hi, 1.0)
    return max(hi - lo, 0.0) * length_m


def occlusion(a_z_m: float, b_z_m: float, length_m: float, base_m: float, top_m: float,
              cover: float, extinction_per_m: float, extinction_scale: float) -> Dict[str, float]:
    """The ESTIMATED transmittance of the cloud layer between the camera and
    the aircraft: the path inside the slab times the cover (the expected
    share of it in cloud) times the extinction. An estimate of the mean, not
    the drawn noise's value; recorded per frame so a consumer can drop frames
    whose mask shows an aircraft the beauty hides."""
    path = slab_path_m(a_z_m, b_z_m, length_m, base_m, top_m)
    tau = path * max(cover, 0.0) * max(extinction_per_m, 0.0) * max(extinction_scale, 0.0)
    transmittance = math.exp(-tau)
    return {"path_m": path, "tau": tau, "transmittance": transmittance,
            "flagged": transmittance < OCCLUSION_FLAG_TRANSMITTANCE}


#: The lightning's sky pulse: flash power at the camera normalised by this
#: illuminance (lux) reads as a full flash. UNCALIBRATED.
LIGHTNING_REFERENCE_LUX = 50.0


def sky_pulse_scale(flash_norm: float, gain: float) -> float:
    """The sky light's multiplier during a flash: 1 + gain x clamp(flash, 0, 1)."""
    return 1.0 + max(gain, 0.0) * min(max(flash_norm, 0.0), 1.0)


# -- the tiles' look (the material parameter collection) ----------------------------

#: MPC_FlightSimWorld's scalars: the contract between
#: scripts/ue_create_materials.py (the collection and M_FlightSimTilesBeauty),
#: assets/shaders/world/tiles_*.hlsl and FlightSimClouds.cpp. Defaults are what
#: a material reads before the render sets anything (dry, ungraded: the look
#: Cesium's own material has). The detail constants are UNCALIBRATED.
WORLD_MPC = "MPC_FlightSimWorld"
WORLD_MPC_SCALARS: Dict[str, float] = {
    "Wetness": 0.0,
    "PuddleAmount": 0.0,
    "Dehaze": 0.0,
    "Saturation": 1.0,
    "DetailStrength": 0.0,
    "DetailFadeM": 1500.0,
    "DetailScaleM": 2.0,
    # tiles-delight (core/scene/tiles_delight.py): 0 is a pass-through.
    "DelightAmount": 0.0,
    "DelightBlueGate": 4.0,
}
#: How much of the wetness becomes standing water on flat ground. UNCALIBRATED.
PUDDLE_SHARE_OF_WETNESS = 0.5


def tiles_parameters(preset: str, card_wetness: float) -> Dict[str, float]:
    """The collection's values for a preset and the card's wetness (the larger
    of the card's and the preset's floor)."""
    row = ATMOSPHERE[preset]
    wet = max(min(max(card_wetness, 0.0), 1.0), row["wetness_floor"])
    out = dict(WORLD_MPC_SCALARS)
    out.update({"Wetness": wet, "PuddleAmount": wet * PUDDLE_SHARE_OF_WETNESS,
                "Dehaze": row["tiles_dehaze"], "Saturation": row["tiles_saturation"],
                "DetailStrength": row["tiles_detail_strength"],
                # tiles-delight: the preset's de-light amount (tiles_delight.DELIGHT_DEFAULTS).
                "DelightAmount": tiles_delight.amount_for(preset),
                "DelightBlueGate": tiles_delight.DELIGHT_BLUE_GATE})
    return out


# -- run-time overrides -------------------------------------------------------------

OVERRIDE_SECTIONS = {"atmosphere": (PRESETS, ATMOSPHERE_FIELDS),
                     "clouds": (CLOUD_PRESETS, CLOUD_FIELDS)}
OVERRIDE_CONSTANTS = ("cloud_extinction_scale", "occlusion_flag_transmittance",
                      "lightning_reference_lux", "detail_fade_m", "detail_scale_m",
                      "puddle_share_of_wetness")


def validate_overrides(doc: Dict[str, Any]) -> List[str]:
    """The names an overrides file may carry (``-world-beauty-overrides=``):
    {"atmosphere": {preset: {field: number}}, "clouds": {shape: {field: number}},
    "constants": {name: number}}. Returns every problem, by name; [] is valid.
    The host refuses a file with any (world_beauty.overrides)."""
    problems: List[str] = []
    if not isinstance(doc, dict):
        return ["the overrides file is not a JSON object"]
    for key in doc:
        if key not in OVERRIDE_SECTIONS and key != "constants":
            problems.append(f"unknown section {key!r}")
    for section, (rows, fields) in OVERRIDE_SECTIONS.items():
        block = doc.get(section, {})
        if not isinstance(block, dict):
            problems.append(f"{section} is not an object")
            continue
        for row, values in block.items():
            if row not in rows:
                problems.append(f"{section}.{row} is not one of {list(rows)}")
                continue
            if not isinstance(values, dict):
                problems.append(f"{section}.{row} is not an object")
                continue
            for field, value in values.items():
                if field not in fields:
                    problems.append(f"{section}.{row}.{field} is not a field")
                elif not isinstance(value, (int, float)) or isinstance(value, bool):
                    problems.append(f"{section}.{row}.{field} is not a number")
    constants = doc.get("constants", {})
    if not isinstance(constants, dict):
        problems.append("constants is not an object")
    else:
        for name, value in constants.items():
            if name not in OVERRIDE_CONSTANTS:
                problems.append(f"constants.{name} is not one of {list(OVERRIDE_CONSTANTS)}")
            elif not isinstance(value, (int, float)) or isinstance(value, bool):
                problems.append(f"constants.{name} is not a number")
    return problems


# -- the ground scatter (FlightSimGroundDetail.cpp) ----------------------------------

SCATTER_FORMAT = "flightsim.ground_scatter"
SCATTER_VERSION = 1
#: Licences a scatter asset may carry: redistributable, no NC (the project rule).
SCATTER_LICENCES = ("CC0-1.0", "CC-BY-4.0")
#: The most instances one sidecar may place, over all species (the host's cap too).
MAX_TOTAL_INSTANCES = 100000
#: Where the pins live (scripts/fetch_scatter_assets.py writes their sha256s).
PINS_PATH = Path(__file__).resolve().parents[2] / "assets" / "scatter" / "polyhaven_pins.json"

#: Per-biome species, density and size. UNCALIBRATED: set by probe render
#: (a nadir density probe against WorldCover tree fraction is V4's clause).
#: The meshes are the paths scripts/ue_import_scatter.py (TODO, recorded)
#: imports the pinned glTFs to.
BIOMES: Dict[str, Dict[str, Any]] = {
    "forest": {
        "species": [
            {"id": "fir_tree_01", "density_per_ha": 25.0, "scale_min": 0.8, "scale_max": 1.25,
             "cull_end_m": 4000.0},
            {"id": "jacaranda_tree", "density_per_ha": 4.0, "scale_min": 0.8, "scale_max": 1.1,
             "cull_end_m": 4000.0},
            {"id": "shrub_02", "density_per_ha": 60.0, "scale_min": 0.7, "scale_max": 1.3,
             "cull_end_m": 1200.0},
            {"id": "rock_moss_set_01", "density_per_ha": 3.0, "scale_min": 0.6, "scale_max": 1.4,
             "cull_end_m": 1500.0},
            {"id": "grass_medium_01", "density_per_ha": 200.0, "scale_min": 0.8, "scale_max": 1.2,
             "cull_end_m": 400.0},
        ],
    },
    "desert": {
        "species": [
            {"id": "quiver_tree_01", "density_per_ha": 1.5, "scale_min": 0.8, "scale_max": 1.2,
             "cull_end_m": 3000.0},
            {"id": "searsia_lucida", "density_per_ha": 6.0, "scale_min": 0.7, "scale_max": 1.2,
             "cull_end_m": 1500.0},
            {"id": "wild_rooibos_bush", "density_per_ha": 20.0, "scale_min": 0.6, "scale_max": 1.3,
             "cull_end_m": 900.0},
            {"id": "namaqualand_boulder_02", "density_per_ha": 2.0, "scale_min": 0.5,
             "scale_max": 1.5, "cull_end_m": 2000.0},
        ],
    },
}
#: The sidecar's placement constants (FlightSimGroundDetail.cpp reads each).
#: UNCALIBRATED.
SCATTER_DEFAULTS: Dict[str, float] = {
    "half_east_m": 1500.0,
    "half_north_m": 1500.0,
    "exclusion_radius_m": 150.0,   # nothing within this of the start (the runway, the takeoff)
    "max_slope_deg": 32.0,         # steeper hits are rejected
    "step_reject_m": 2.5,          # a probe ring spanning more than this is a roof or cliff edge
    "probe_offset_m": 4.0,         # the probe ring's radius
    "sink_m": 0.3,                 # every instance sinks this far (no floating roots)
    "resnap_radius_m": 800.0,      # re-traced each frame within this of the camera
    "trace_up_m": 3000.0,
    "trace_down_m": 3000.0,
}


def species_seed(seed: int, species_index: int) -> int:
    """One species' stream: splitmix64(seed + index + 1)."""
    return splitmix64((int(seed) + int(species_index) + 1) & MASK64)


def instance_count(density_per_ha: float, half_east_m: float, half_north_m: float,
                   max_instances: int) -> int:
    """round(density x area / 1 ha), at most max_instances."""
    area_m2 = 4.0 * max(half_east_m, 0.0) * max(half_north_m, 0.0)
    count = int(math.floor(max(density_per_ha, 0.0) * area_m2 / 1.0e4 + 0.5))
    return max(min(count, int(max_instances)), 0)


def placement(seed: int, species_index: int, index: int, half_east_m: float, half_north_m: float,
              scale_min: float, scale_max: float) -> Tuple[float, float, float, float]:
    """(east m, north m, yaw deg, scale) of one instance, relative to the
    region's centre: uniforms 0..3 of the species' stream."""
    key = species_seed(seed, species_index)
    east = (2.0 * unit(key, index, 0) - 1.0) * half_east_m
    north = (2.0 * unit(key, index, 1) - 1.0) * half_north_m
    yaw = 360.0 * unit(key, index, 2)
    scale = scale_min + (scale_max - scale_min) * unit(key, index, 3)
    return east, north, yaw, scale


def excluded(east_m: float, north_m: float, centre_east_m: float, centre_north_m: float,
             radius_m: float) -> bool:
    return math.hypot(east_m - centre_east_m, north_m - centre_north_m) < radius_m


def placements(sidecar: Dict[str, Any], species_index: int) -> List[Tuple[float, float, float, float]]:
    """Every kept (east, north, yaw, scale) of one species, region-relative,
    before the trace (the host then drops slopes, edges and misses)."""
    region = sidecar["region"]
    species = sidecar["species"][species_index]
    exclusion = sidecar.get("exclusion", {})
    count = instance_count(species["density_per_ha"], region["half_east_m"],
                           region["half_north_m"], species.get("max_instances", MAX_TOTAL_INSTANCES))
    out = []
    for i in range(count):
        east, north, yaw, scale = placement(sidecar["seed"], species_index, i, region["half_east_m"],
                                            region["half_north_m"], species["scale_min"],
                                            species["scale_max"])
        if excluded(east + region.get("centre_east_m", 0.0), north + region.get("centre_north_m", 0.0),
                    exclusion.get("centre_east_m", 0.0), exclusion.get("centre_north_m", 0.0),
                    exclusion.get("radius_m", 0.0)):
            continue
        out.append((east, north, yaw, scale))
    return out


def load_pins(path: Path = PINS_PATH) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def pin_complete(pin: Dict[str, Any]) -> bool:
    """A pin is usable when its licence is allowed and every file it names
    (the root glTF and each include) carries a sha256."""
    if pin.get("licence") not in SCATTER_LICENCES:
        return False
    files = [pin.get("root", {})] + list(pin.get("includes", {}).values())
    return all(isinstance(f.get("sha256"), str) and len(f["sha256"]) == 64 for f in files)


def scatter_sidecar(biome: str, seed: int, pins: Optional[Dict[str, Any]] = None,
                    region: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """The sidecar the host's -ground-scatter= reads. Each species carries its
    pin (source URL, licence, the root's sha256) and ``pinned``: the host
    draws only pinned species and records the rest as not drawn (no asset
    without a pinned source, sha256 and licence)."""
    if biome not in BIOMES:
        raise ValueError(f"biome {biome!r} is not one of {sorted(BIOMES)}")
    pins = load_pins() if pins is None else pins
    reg = {"centre_east_m": 0.0, "centre_north_m": 0.0,
           "half_east_m": SCATTER_DEFAULTS["half_east_m"],
           "half_north_m": SCATTER_DEFAULTS["half_north_m"]}
    reg.update(region or {})
    species = []
    total = 0
    for row in BIOMES[biome]["species"]:
        pin = pins["assets"].get(row["id"])
        if pin is None:
            raise ValueError(f"species {row['id']!r} has no pin in {PINS_PATH.name}")
        count = instance_count(row["density_per_ha"], reg["half_east_m"], reg["half_north_m"],
                               MAX_TOTAL_INSTANCES)
        budget = max(MAX_TOTAL_INSTANCES - total, 0)
        total += min(count, budget)
        species.append({
            "id": row["id"],
            "mesh": f"/Game/FlightSim/Scatter/{row['id']}/{row['id']}",
            "density_per_ha": row["density_per_ha"],
            "scale_min": row["scale_min"],
            "scale_max": row["scale_max"],
            "cull_end_m": row["cull_end_m"],
            "max_instances": budget,
            "source_url": pin["root"]["url"],
            "licence": pin["licence"],
            "sha256": pin["root"].get("sha256"),
            "pinned": pin_complete(pin),
        })
    return {
        "format": SCATTER_FORMAT,
        "version": SCATTER_VERSION,
        "biome": biome,
        "seed": int(seed),
        "region": reg,
        "exclusion": {"centre_east_m": 0.0, "centre_north_m": 0.0,
                      "radius_m": SCATTER_DEFAULTS["exclusion_radius_m"]},
        **{k: v for k, v in SCATTER_DEFAULTS.items()
           if k not in ("half_east_m", "half_north_m", "exclusion_radius_m")},
        "species": species,
        "visual_only": True,
        "not_claimed": [
            "no collision: the flight model and the ground callback never see these",
            "positions are a seeded uniform scatter, not the land cover's trees",
            "instances may stand on flat roofs or water the tiles carry (no land-cover mask yet)",
        ],
    }


def sidecar_sha256(sidecar: Dict[str, Any]) -> str:
    """The digest of the sidecar as written (sorted keys, the file's bytes)."""
    return hashlib.sha256(dumps(sidecar).encode("utf-8")).hexdigest()


def dumps(sidecar: Dict[str, Any]) -> str:
    return json.dumps(sidecar, indent=2, sort_keys=True) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Write a ground-scatter sidecar (-ground-scatter=).")
    parser.add_argument("--biome", required=True, choices=sorted(BIOMES))
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--half-m", type=float, default=SCATTER_DEFAULTS["half_east_m"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    sidecar = scatter_sidecar(args.biome, args.seed,
                              region={"half_east_m": args.half_m, "half_north_m": args.half_m})
    args.out.write_text(dumps(sidecar), encoding="utf-8")
    unpinned = [s["id"] for s in sidecar["species"] if not s["pinned"]]
    print(f"wrote {args.out} ({args.biome}, seed {args.seed}); "
          + (f"NOT pinned yet (drawn as nothing): {unpinned}; run scripts/fetch_scatter_assets.py"
             if unpinned else "every species pinned"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
