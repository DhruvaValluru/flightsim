"""The beauty-only cirrus sheet (sky step 6 of the owner's X-Plane-12 brief).

UE draws ONE volumetric cloud layer, so the high cirrus the reference photograph
shows across its upper sky (long translucent wisps and streaks with feathered
ends, brighter white where thicker, the blue reading through everywhere) is a
separate sheet: one earth-curved translucent disc at 10-13 km, ABOVE the
flight, on ``M_FlightSimCirrus`` (scripts/ue_create_materials.py
``create_world_cirrus``; the Custom node body is
assets/shaders/world/cirrus.hlsl). The host is ``FFlightSimWorldBeauty::
ApplyCirrus`` (FlightSimClouds.cpp, ``-quality=beauty`` only); this module is
its Python twin: every constant below is pinned to the C++ pure block, the
shader and the material script by tests/test_cirrus.py.

VISUAL ONLY. The actor is in ``BeautyOnlyActors`` (hidden on every label
capture), the material is unlit and translucent and writes no depth, no custom
depth and no velocity, so the mask, class, depth and boxes never see it; the
measure quality never builds it; nothing here reaches the flight model or the
exposure (plan.py's ev100 is computed before the clouds block and never reads
it). Deterministic: the noise is hashed on a seeded kilometre frame
(``world_beauty.cloud_seed_offset_km``), the streak direction is the card's
drift bearing or a seeded one, the drift is the scene's own law.

Every look value here is UNCALIBRATED (set by probe render on the render
machine) and the whole sheet is UNMEASURED until the Windows laptop renders it
(the command is in docs/VISUAL_FIDELITY_PLAN.md §8 "Sky step 6"). Nothing here
has been rendered; never claim it reads as veils.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from .rain_field import unit
from .world_beauty import PRESETS, _perlin2, probit_approx

__all__ = [
    "CIRRUS_BASE_M", "CIRRUS_CLEARANCE_M", "CIRRUS_COVER_SOURCES", "CIRRUS_DEFAULT_COVER",
    "CIRRUS_FBM_MEAN", "CIRRUS_FBM_SIGMA", "CIRRUS_LOOK", "CIRRUS_MAX_M",
    "CIRRUS_MIN_DRAWN_COVER", "CIRRUS_RADIUS_KM", "CIRRUS_SORT_PRIORITY", "CIRRUS_SWITCH",
    "CIRRUS_SWITCH_WORDS", "CIRRUS_WIND_GAIN", "cirrus_cover", "cirrus_drift_mps",
    "cirrus_ends", "cirrus_fibres", "cirrus_frame", "cirrus_mode", "cirrus_opacity",
    "cirrus_phase", "cirrus_sheet", "cirrus_streak_dir_deg", "cirrus_streaks",
    "cirrus_threshold", "cirrus_thickness", "material_scalars",
]

#: ``-look-cirrus=on|off`` (FlightSimClouds.cpp Build; FLIGHTSIM_RENDER_SWITCHES
#: too): on by default in beauty; off builds nothing (the round-95 upper sky);
#: another word refuses ``world_beauty.cirrus: -look-cirrus=...``.
CIRRUS_SWITCH = "-look-cirrus"
CIRRUS_SWITCH_WORDS: Tuple[str, ...] = ("on", "off")

#: The altitude law (C++ CirrusSheetAltitudeM): the sheet sits at
#: max(CIRRUS_BASE_M, camera + CIRRUS_CLEARANCE_M), capped at CIRRUS_MAX_M, so it
#: is ABOVE the camera by construction (the owner's >= 1 km clearance rule holds
#: with margin; a 747 at 10 km gets cirrus at 11.5 km) and fades out over the
#: clearance as the camera climbs into the cap. Cirrus genuinely lives at
#: 8-13 km in the mid-latitudes; the numbers are still look values: UNCALIBRATED.
CIRRUS_BASE_M = 10000.0
CIRRUS_CLEARANCE_M = 1500.0
CIRRUS_MAX_M = 13000.0
#: The disc: the distant sheet's ring builder (48 rings x 96 segments, rings
#: densifying towards the centre, each dropped by the earth's curvature) at a
#: larger radius, since the sheet is higher and so farther to its horizon.
CIRRUS_RADIUS_KM = 400.0
#: Translucent sort priority: the distant sheet draws at -100; the cirrus is
#: farther from every camera it can overlap, so it draws first (design D13).
CIRRUS_SORT_PRIORITY = -101
#: The cover drawn when the plan carries NO cloud-cover data (a plan without a
#: weather_date, or none at all) or when -cloud-type=cirrus asks for a cirrus sky
#: the data does not give: the reference photograph's upper half is roughly a
#: third veiled. A stated stylisation, recorded as such. UNCALIBRATED.
CIRRUS_DEFAULT_COVER = 0.35
#: Below this cover nothing is built (the disc would be all edge).
CIRRUS_MIN_DRAWN_COVER = 0.02
#: The cirrus drifts with the scene's drift law at CIRRUS_WIND_GAIN x the card's
#: cloud-base drift (jet-level winds run faster than the boundary layer's; the
#: plan carries no wind at altitude). UNCALIBRATED.
CIRRUS_WIND_GAIN = 2.0
#: Where the drawn cover came from (C++ CirrusCoverSourceName, in this order).
CIRRUS_COVER_SOURCES: Tuple[str, ...] = ("off", "preset", "switch", "plan", "default")

#: The streak field's moments (cirrus_streaks over a 240 x 240 grid of the
#: stretched frame, -60..60, at seed 17: mean 0.5003, sigma 0.0774; re-measured
#: by tests/test_cirrus.py). Properties of the noise, not look values: the shader
#: cuts at the quantile threshold = MEAN + SIGMA x probit(1 - cover), so the drawn
#: share of the sheet is the cover (within 1 % at 0.2..0.9 on the replica).
CIRRUS_FBM_MEAN = 0.5
CIRRUS_FBM_SIGMA = 0.077

#: The look (the material's scalar parameters, cirrus.hlsl's inputs; C++
#: CirrusLook / CirrusLookName). UNCALIBRATED: set by probe render on the render
#: machine. Each one:
#:   StreakScaleKm  the cross-stream feature size (km); along the stream it is x StreakAspect
#:   StreakAspect   how much longer than wide a streak is (cirrus fibratus runs tens of km)
#:   EdgeSigmas     the cut's soft edge in sigmas of the field: a veil, not a cut-out
#:   FibreStrength  how deeply the fine along-stream filaments modulate the thickness
#:   FeatherWidth   the width (in the ends noise's units) over which a streak thins to nothing
#:   OpticalDepth   the veil's vertical optical depth at full thickness (cirrus: 0.1..1)
#:   MaxOpacity     the opacity cap: the blue reads through everywhere
#:   Albedo         ice scatters nearly all it intercepts
#:   AmbientGain    x the sky's distant scattered luminance
#:   ForwardG       the Henyey-Greenstein asymmetry of the ice (strongly forward)
#:   ForwardShare   the blend of that lobe with an isotropic term (multiple scattering stand-in)
#:   ForwardCap     the lobe's cap (its peak would be (1+g)/(1-g)^2 = 19 at g 0.7)
#:   RimFadeShare   the sheet fades out over this share of the radius at the rim
#:   SunDirSign     1: SkyAtmosphereLightDirection points TOWARDS the sun (read in the 5.7
#:                  source, UNVERIFIED on the laptop); -1 flips it for the A/B
CIRRUS_LOOK: Dict[str, float] = {
    "StreakScaleKm": 6.0,
    "StreakAspect": 8.0,
    "EdgeSigmas": 2.5,
    "FibreStrength": 0.6,
    "FeatherWidth": 0.15,
    "OpticalDepth": 0.6,
    "MaxOpacity": 0.6,
    "Albedo": 0.95,
    "AmbientGain": 1.0,
    "ForwardG": 0.7,
    "ForwardShare": 0.6,
    "ForwardCap": 8.0,
    "RimFadeShare": 0.2,
    "SunDirSign": 1.0,
}
#: The field's fixed seed offsets (cirrus.hlsl FCirrusNoise; one uint each).
_SEED_WARP_A, _SEED_WARP_C = 701, 719
_SEED_OCTAVES = (101, 113, 127)
_SEED_FIBRES = (211, 223)
_SEED_ENDS = 307
#: The hashed field's own seed (the material's noise is seeded through
#: SeedOffsetKm, the frame offset; the lattice seed is fixed, like the layers' 7u).
CIRRUS_NOISE_SEED = 17


def material_scalars() -> Dict[str, float]:
    """``M_FlightSimCirrus``' scalar parameters with the default a material has
    before the render sets them (scripts/ue_create_materials.py
    WORLD_CIRRUS_SCALARS, pinned equal): the plan's cover (the default), the
    streak bearing, the radius, the per-frame fade, then the look."""
    out: Dict[str, float] = {"Coverage": CIRRUS_DEFAULT_COVER, "StreakDirDeg": 0.0,
                             "RadiusKm": CIRRUS_RADIUS_KM, "SheetFade": 1.0}
    out.update(CIRRUS_LOOK)
    return out


def cirrus_mode(word: Optional[str]) -> str:
    """The switch word as the host reads it: ``on`` (the default, an empty word)
    or ``off``; any other word is the host's refusal ``world_beauty.cirrus``."""
    chosen = (word or "").strip() or "on"
    if chosen not in CIRRUS_SWITCH_WORDS:
        raise ValueError(f"world_beauty.cirrus: -look-cirrus={chosen} is not on or off")
    return chosen


def cirrus_sheet(camera_m: float) -> Dict[str, float]:
    """Where the sheet sits for a camera at ``camera_m`` (C++ CirrusSheetAltitudeM):
    ``altitude_m`` = min(max(CIRRUS_BASE_M, camera + CIRRUS_CLEARANCE_M), CIRRUS_MAX_M),
    never below the camera; ``fade`` 1 with the full clearance above the camera,
    0 with the camera at the cap (the sheet is never seen from inside or above)."""
    cam = float(camera_m)
    altitude = min(max(CIRRUS_BASE_M, cam + CIRRUS_CLEARANCE_M), CIRRUS_MAX_M)
    fade = min(max((altitude - cam) / CIRRUS_CLEARANCE_M, 0.0), 1.0)
    return {"altitude_m": altitude, "fade": fade}


def cirrus_cover(switch_word: str, switch_type_cirrus: bool, cover_from_data: bool,
                 plan_cirrus_coverage: float, preset: str) -> Tuple[float, str]:
    """``(cover, source)`` the host draws (C++ CirrusCover), in order:
    ``-look-cirrus=off`` -> 0 ("off"); a rain or storm preset -> 0 ("preset": the
    deck covers the sky); ``-cloud-type=cirrus`` with no data cover above 0 ->
    CIRRUS_DEFAULT_COVER ("switch"); a plan whose cover came from data (ERA5
    cover_inputs present) -> its cirrus_coverage, 0 included ("plan": a clear
    upper sky stays clear); else CIRRUS_DEFAULT_COVER ("default"). Clamped 0..1."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; one of {PRESETS}")
    if cirrus_mode(switch_word) == "off":
        return 0.0, "off"
    if preset in ("rain", "storm"):
        return 0.0, "preset"
    plan = min(max(float(plan_cirrus_coverage), 0.0), 1.0)
    if switch_type_cirrus and not (cover_from_data and plan > 0.0):
        return CIRRUS_DEFAULT_COVER, "switch"
    if cover_from_data:
        return plan, "plan"
    return CIRRUS_DEFAULT_COVER, "default"


def cirrus_streak_dir_deg(seed: int, drift_mps: float, drift_from_deg: float) -> float:
    """The streaks' compass bearing (C++ CirrusStreakDirDeg): the card's drift
    bearing when it drifts (streaks run along the wind; a bearing and its
    opposite are one axis), else a seeded bearing (rain_field.unit, index 1,
    channel 0: index 0 is the noise offset's) so a still card is still
    deterministic. Always 0 <= bearing < 360."""
    if float(drift_mps) > 0.0:
        return float(drift_from_deg) % 360.0
    return unit(int(seed), 1, 0) * 360.0


def cirrus_drift_mps(drift_mps: float) -> float:
    """The speed the sheet drifts at: the card's drift x CIRRUS_WIND_GAIN."""
    return max(float(drift_mps), 0.0) * CIRRUS_WIND_GAIN


# -- the shader's field, replicated (cirrus.hlsl FCirrusNoise) ---------------------------

def cirrus_frame(x_km: float, y_km: float, streak_dir_deg: float, scale_km: float,
                 aspect: float) -> Tuple[float, float]:
    """The seeded kilometre frame turned onto the streak axis and stretched along
    it: ``(qa, qc)`` = (along / (scale x aspect), across / scale). A compass
    bearing b points along (sin b, cos b) in engine X east / Y north (the scene's
    drift law)."""
    ang = math.radians(float(streak_dir_deg))
    dx, dy = math.sin(ang), math.cos(ang)
    along = float(x_km) * dx + float(y_km) * dy
    across = float(x_km) * dy - float(y_km) * dx
    scale = max(float(scale_km), 1e-3)
    return along / (scale * max(float(aspect), 1.0)), across / scale


def cirrus_streaks(qa: float, qc: float, seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Streaks: the streak field in 0..1 (mean CIRRUS_FBM_MEAN).
    A slow flow warp curves the streaks (the hooks of cirrus uncinus), then
    three gradient-noise octaves (0.5 / 0.3 / 0.2 at 1 / 2.1 / 4.3) on the
    stretched frame. 20 hashes."""
    wa = _perlin2(qa * 0.7 + 3.3, qc * 0.7 + 1.1, seed + _SEED_WARP_A)
    wc = _perlin2(qa * 0.7 + 8.9, qc * 0.7 + 6.2, seed + _SEED_WARP_C)
    a = qa + 0.35 * wa
    c = qc + 0.35 * wc
    f = (0.5 * _perlin2(a + 1.3, c + 7.1, seed + _SEED_OCTAVES[0])
         + 0.3 * _perlin2(a * 2.1 + 5.7, c * 2.1 + 2.9, seed + _SEED_OCTAVES[1])
         + 0.2 * _perlin2(a * 4.3 + 9.1, c * 4.3 + 4.4, seed + _SEED_OCTAVES[2]))
    return 0.5 + 0.5 * f


def cirrus_fibres(qa: float, qc: float, seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Fibres: the fine filaments along the stream, 0..1 about 0.5
    (two octaves, 4x and 8x finer ACROSS the stream than along it). 8 hashes."""
    return 0.5 + 0.5 * (0.6 * _perlin2(qa * 1.5 + 2.2, qc * 6.0 + 3.7, seed + _SEED_FIBRES[0])
                        + 0.4 * _perlin2(qa * 3.0 + 7.5, qc * 12.0 + 1.9, seed + _SEED_FIBRES[1]))


def cirrus_ends(qa: float, qc: float, seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Ends: a slow along-stream gradient noise whose zero
    crossings thin a streak to nothing (its feathered ends). 4 hashes."""
    return _perlin2(qa * 0.3 + 4.1, qc * 1.0 + 2.6, seed + _SEED_ENDS)


def cirrus_threshold(cover: float) -> float:
    """The field value at the (1 - cover) quantile: the shader's cut."""
    c = min(max(float(cover), 0.0), 1.0)
    return CIRRUS_FBM_MEAN + CIRRUS_FBM_SIGMA * probit_approx(1.0 - c)


def _smoothstep(a: float, b: float, x: float) -> float:
    t = min(max((x - a) / max(b - a, 1e-9), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def cirrus_thickness(x_km: float, y_km: float, cover: float, streak_dir_deg: float,
                     look: Optional[Dict[str, float]] = None, seed: int = CIRRUS_NOISE_SEED) -> float:
    """The veil's thickness 0..1 at a point of the frame (cirrus.hlsl before the
    opacity): the field cut at the cover's quantile with a soft edge EdgeSigmas
    wide, modulated by the fibres (1 - FibreStrength .. 1) and thinned to nothing
    at the ends noise's zero crossings (smoothstep(0, FeatherWidth, |ends|))."""
    L = CIRRUS_LOOK if look is None else look
    qa, qc = cirrus_frame(x_km, y_km, streak_dir_deg, L["StreakScaleKm"], L["StreakAspect"])
    thr = cirrus_threshold(cover)
    soft = CIRRUS_FBM_SIGMA * L["EdgeSigmas"]
    thick = min(max((cirrus_streaks(qa, qc, seed) - thr) / max(soft, 1e-4), 0.0), 1.0)
    thick *= (1.0 - L["FibreStrength"]) + L["FibreStrength"] * cirrus_fibres(qa, qc, seed)
    thick *= _smoothstep(0.0, max(L["FeatherWidth"], 1e-3), abs(cirrus_ends(qa, qc, seed)))
    return thick


def cirrus_opacity(thick: float, view_z_abs: float, look: Optional[Dict[str, float]] = None) -> float:
    """The pixel's opacity: Beer's law on the slant path (1 / max(|V.z|, 0.15))
    through a veil of vertical optical depth OpticalDepth x thick, capped at
    MaxOpacity so the sky reads through everywhere."""
    L = CIRRUS_LOOK if look is None else look
    slant = 1.0 / max(abs(float(view_z_abs)), 0.15)
    tau = max(float(thick), 0.0) * L["OpticalDepth"] * slant
    return min(L["MaxOpacity"], 1.0 - math.exp(-tau))


def cirrus_phase(cos_theta: float, look: Optional[Dict[str, float]] = None) -> float:
    """The light per unit opacity relative to an isotropic veil: a
    Henyey-Greenstein lobe (normalised so isotropic = 1), capped at ForwardCap,
    blended ForwardShare with 1. cos_theta is the scattering angle's cosine
    (1 = the sun straight behind the veil, as seen from the camera)."""
    L = CIRRUS_LOOK if look is None else look
    g = L["ForwardG"]
    mu = min(max(float(cos_theta), -1.0), 1.0)
    hg = (1.0 - g * g) / max(1.0 + g * g - 2.0 * g * mu, 1e-4) ** 1.5
    return (1.0 - L["ForwardShare"]) + L["ForwardShare"] * min(hg, L["ForwardCap"])


def record_basis() -> Dict[str, Any]:
    """The fixed strings the host records (documentation for the render.json reader)."""
    return {
        "labels": ("BeautyOnlyActors; unlit translucent, no depth write, no custom depth, no velocity, "
                   "no shadow; the measure quality never builds it"),
        "visual_only": True,
        "calibration": "UNCALIBRATED: set by probe render on the render machine",
    }
