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
    "CIRRUS_FBM_MEAN", "CIRRUS_FBM_SIGMA", "CIRRUS_FIBRE_MEAN", "CIRRUS_LOOK", "CIRRUS_MAX_M",
    "CIRRUS_MIN_DRAWN_COVER", "CIRRUS_RADIUS_KM", "CIRRUS_SLANT_FLOOR", "CIRRUS_SORT_PRIORITY",
    "CIRRUS_SWITCH", "CIRRUS_SWITCH_DEFAULT", "CIRRUS_SWITCH_WORDS", "CIRRUS_WIND_GAIN", "cirrus_cover",
    "cirrus_drift_mps", "cirrus_fibres", "cirrus_flow", "cirrus_frame", "cirrus_mode", "cirrus_opacity",
    "cirrus_patch", "cirrus_phase", "cirrus_sheet", "cirrus_streak_dir_deg",
    "cirrus_threshold", "cirrus_thickness", "material_scalars",
]

#: ``-look-cirrus=on|off`` (FlightSimClouds.cpp Build; FLIGHTSIM_RENDER_SWITCHES
#: too): OFF by default since generation 2 (2026-11-15, lane sky-cirrus2: off
#: until the sheet reads as a photograph by eye on the render machine); off
#: builds nothing (the round-95 upper sky); another word refuses
#: ``world_beauty.cirrus: -look-cirrus=...``.
CIRRUS_SWITCH = "-look-cirrus"
CIRRUS_SWITCH_WORDS: Tuple[str, ...] = ("on", "off")
CIRRUS_SWITCH_DEFAULT = "off"

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

#: The patch field's moments (cirrus_patch over a 120 x 120 grid of the patch
#: frame, -60..60, at seed 17: mean 0.4997, sigma 0.0901; re-measured by
#: tests/test_cirrus.py). Properties of the noise, not look values: the shader
#: cuts at the quantile threshold = MEAN + SIGMA x probit(1 - cover), so the share
#: of the sky inside a cirrus patch is the cover (the plan's cirrus_coverage, a
#: fraction of the sky, ERA5's high cloud cover; 0 = none).
CIRRUS_FBM_MEAN = 0.5
CIRRUS_FBM_SIGMA = 0.09
#: The fibre field's mean at the default FibreSharpness (6): 0.294 on the same
#: grid. Where a fibre is finer than the pixel's footprint the shader draws this
#: mean instead (a veil), so the far sheet never aliases into the round-1 tape.
CIRRUS_FIBRE_MEAN = 0.29
#: The slant path's floor: 1 / max(|V.z|, 0.25), at most 4x the vertical path, so
#: the grazing sheet near the horizon thickens by perspective without turning
#: opaque white (round 1's 0.15 let it reach 6.7x).
CIRRUS_SLANT_FLOOR = 0.25

#: The look (the material's scalar parameters, cirrus.hlsl's inputs; C++
#: CirrusLook / CirrusLookName). Generation 2 (2026-11-15, lane sky-cirrus2):
#: the round-1 look (6 km x 48 km streaks, opacity to 0.6) drew hard, evenly
#: spaced tape on #13 and white smears on #3; this one draws sparse patches of
#: thin hooked fibres. The real-world number each value matches:
#:   StreakScaleKm  the fibres' cross-stream spacing: cirrus fibratus filaments and
#:                  uncinus fallstreak heads are ~0.5-2 km wide (Heymsfield 1975)
#:   StreakAspect   along / across: fibratus filaments run 5-20 km (x6 -> ~9 km)
#:   EdgeSigmas     the patch edge in sigmas of the patch field: patches fade into the blue
#:   FibreStrength  the share of the thickness carried by the fibres (the rest is a faint
#:                  veil between them, cirrostratus-like)
#:   FibreSharpness the ridge exponent: ~16 % of a patch is inside a bright fibre
#:   PatchScaleKm   the patch size: cirrus fields come in patches tens of km across
#:                  (mesoscale bands 20-100 km)
#:   FlowWarpKm     the slow across-stream warp: the streak direction turns by up to
#:   FlowLenKm        ~30 degrees over ~30 km (jet-level flow curvature)
#:   HookWarpKm     the fine warp: the uncinus hooks, ~1 km over ~4 km
#:   HookLenKm
#:   DetailFade     fibres finer than DetailFade x StreakScaleKm per pixel draw their mean
#:   OpticalDepth   vertical optical depth at full thickness: thin cirrus is 0.03-0.3
#:                  (Sassen & Cho 1992); 0.4 sits just above its top (generation 3)
#:   MaxOpacity     the cap: 1 - exp(-0.4 x 1.4) ~ 0.43 -> 0.42, so the blue reads through
#:   Albedo         ice scatters nearly all it intercepts
#:   AmbientGain    x the sky's distant scattered luminance
#:   ForwardG       Henyey-Greenstein asymmetry of ice crystals (0.7-0.8, Baran 2009)
#:   ForwardShare   the blend of that lobe with an isotropic term (multiple scattering stand-in)
#:   ForwardCap     the lobe's cap (its peak would be (1+g)/(1-g)^2 = 19 at g 0.7)
#:   RimFadeShare   the sheet fades out over this share of the radius at the rim
#:   SunDirSign     1: SkyAtmosphereLightDirection points TOWARDS the sun; -1 flips it
#: Generation 3 (2026-11-16, Mac editor look check, scene 3; review: the preview was
#: too sparse and faint): FibreStrength 0.85 -> 0.92 (brighter fibres, less veil),
#: PatchScaleKm 40 -> 25 (more, smaller patches: two to four in a wide view),
#: OpticalDepth 0.3 -> 0.4 and MaxOpacity 0.35 -> 0.42 (the top of thin cirrus;
#: the blue still reads through). Stills: scratchpad lookdev/sky3-cirrus/{c1,c2,c3,final}.
#: UNCALIBRATED beyond the Mac look-dev stills.
CIRRUS_LOOK: Dict[str, float] = {
    "StreakScaleKm": 1.5,
    "StreakAspect": 6.0,
    "EdgeSigmas": 2.0,
    "FibreStrength": 0.92,
    "FibreSharpness": 6.0,
    "PatchScaleKm": 25.0,
    "FlowWarpKm": 10.0,
    "FlowLenKm": 30.0,
    "HookWarpKm": 1.0,
    "HookLenKm": 4.0,
    "DetailFade": 0.5,
    "OpticalDepth": 0.4,
    "MaxOpacity": 0.42,
    "Albedo": 0.95,
    "AmbientGain": 1.0,
    "ForwardG": 0.7,
    "ForwardShare": 0.6,
    "ForwardCap": 8.0,
    "RimFadeShare": 0.2,
    "SunDirSign": 1.0,
}
#: The field's fixed seed offsets (cirrus.hlsl FCirrusNoise; one uint each).
_SEED_PATCH = (101, 113)
_SEED_FLOW, _SEED_HOOK = 701, 719
_SEED_FIBRES = (211, 223)
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
    """The switch word as the host reads it: ``on`` or ``off`` (the default, an
    empty word); any other word is the host's refusal ``world_beauty.cirrus``."""
    chosen = (word or "").strip() or CIRRUS_SWITCH_DEFAULT
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

def cirrus_frame(x_km: float, y_km: float, streak_dir_deg: float) -> Tuple[float, float]:
    """The seeded kilometre frame turned onto the streak axis: ``(along, across)``
    in km. A compass bearing b points along (sin b, cos b) in engine X east /
    Y north (the scene's drift law)."""
    ang = math.radians(float(streak_dir_deg))
    dx, dy = math.sin(ang), math.cos(ang)
    return float(x_km) * dx + float(y_km) * dy, float(x_km) * dy - float(y_km) * dx


def cirrus_patch(px: float, py: float, seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Patch: the coverage field in 0..1 (mean CIRRUS_FBM_MEAN) on
    the patch frame (km / PatchScaleKm): two gradient octaves. 8 hashes."""
    return 0.5 + 0.5 * (0.65 * _perlin2(px + 1.3, py + 7.1, seed + _SEED_PATCH[0])
                        + 0.35 * _perlin2(px * 2.03 + 5.7, py * 2.03 + 2.9, seed + _SEED_PATCH[1]))


def cirrus_flow(along: float, across: float, look: Optional[Dict[str, float]] = None,
                seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Flow: the warped across-stream coordinate (km). A slow warp
    (FlowWarpKm over FlowLenKm) turns the streak direction across the sky; a
    fine one (HookWarpKm over HookLenKm) bends the fibres into hooks. 8 hashes."""
    L = CIRRUS_LOOK if look is None else look
    fl, hl = max(L["FlowLenKm"], 1e-3), max(L["HookLenKm"], 1e-3)
    c = across + L["FlowWarpKm"] * _perlin2(along / fl + 3.3, across / fl + 1.1, seed + _SEED_FLOW)
    return c + L["HookWarpKm"] * _perlin2(along / hl + 8.9, c / hl + 6.2, seed + _SEED_HOOK)


def cirrus_fibres(qa: float, qc: float, sharpness: float = 6.0, seed: int = CIRRUS_NOISE_SEED) -> float:
    """FCirrusNoise::Fibres: thin bright filaments in 0..1 on the stretched frame
    (qa along / (scale x aspect), qc across / scale): two ridged octaves
    (1 - |noise|) raised to ``sharpness``. 8 hashes."""
    r1 = 1.0 - abs(_perlin2(qa + 2.2, qc + 3.7, seed + _SEED_FIBRES[0]))
    r2 = 1.0 - abs(_perlin2(qa * 2.1 + 7.5, qc * 2.7 + 1.9, seed + _SEED_FIBRES[1]))
    return min(max(0.65 * r1 + 0.35 * r2, 0.0), 1.0) ** max(float(sharpness), 1.0)


def cirrus_threshold(cover: float) -> float:
    """The patch field value at the (1 - cover) quantile: the shader's cut."""
    c = min(max(float(cover), 0.0), 1.0)
    return CIRRUS_FBM_MEAN + CIRRUS_FBM_SIGMA * probit_approx(1.0 - c)


def cirrus_thickness(x_km: float, y_km: float, cover: float, streak_dir_deg: float,
                     look: Optional[Dict[str, float]] = None, seed: int = CIRRUS_NOISE_SEED,
                     footprint_km: float = 0.0) -> float:
    """The veil's thickness 0..1 at a point of the frame (cirrus.hlsl before the
    opacity): the patch field cut at the cover's quantile with a soft edge
    EdgeSigmas wide, times the fibres (a faint veil 1 - FibreStrength between
    them) on the flow-warped stretched frame. ``footprint_km`` is the pixel's
    footprint (the shader's fwidth): fibres finer than DetailFade x StreakScaleKm
    draw CIRRUS_FIBRE_MEAN."""
    L = CIRRUS_LOOK if look is None else look
    ps = max(L["PatchScaleKm"], 1e-3)
    thr = cirrus_threshold(cover)
    soft = CIRRUS_FBM_SIGMA * max(L["EdgeSigmas"], 0.1)
    patch = min(max((cirrus_patch(x_km / ps, y_km / ps, seed) - thr) / max(soft, 1e-4), 0.0), 1.0)
    along, across = cirrus_frame(x_km, y_km, streak_dir_deg)
    c = cirrus_flow(along, across, L, seed)
    scale = max(L["StreakScaleKm"], 1e-3)
    fib = cirrus_fibres(along / (scale * max(L["StreakAspect"], 1.0)), c / scale, L["FibreSharpness"], seed)
    w = min(max(1.0 - float(footprint_km) / (scale * max(L["DetailFade"], 1e-3)), 0.0), 1.0)
    fib = CIRRUS_FIBRE_MEAN + (fib - CIRRUS_FIBRE_MEAN) * w
    fs = min(max(L["FibreStrength"], 0.0), 1.0)
    return patch * ((1.0 - fs) + fs * fib)


def cirrus_opacity(thick: float, view_z_abs: float, look: Optional[Dict[str, float]] = None) -> float:
    """The pixel's opacity: Beer's law on the slant path (1 / max(|V.z|, CIRRUS_SLANT_FLOOR))
    through a veil of vertical optical depth OpticalDepth x thick, capped at
    MaxOpacity so the sky reads through everywhere."""
    L = CIRRUS_LOOK if look is None else look
    slant = 1.0 / max(abs(float(view_z_abs)), CIRRUS_SLANT_FLOOR)
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
