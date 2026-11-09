"""Dust and humidity haze: hygroscopic Mie growth, warm dust absorption and a
ground-hugging boundary-layer haze cap (visual overhaul, module
``dust-humidity-haze``, 2026-11-09).

An OVERLAY on the world beauty's atmosphere preset (core/scene/world_beauty.py,
``FFlightSimWorldBeauty::ApplyAtmosphere``), applied right after it, BEAUTY
ONLY: ``-quality=measure`` never builds the world beauty, so Gate 6's renders
are untouched. Nothing here reaches an equation of motion.

Three things, all from the card:

1. **Hygroscopic growth** (Hanel 1976): an aerosol swells with the relative
   humidity, and its scattering with it, as f(RH) = (1 - min(RH, 0.95))^-gamma,
   gamma by aerosol kind (:data:`RH_GAMMA`). The world preset's Mie extinction
   (``world_beauty.mie_split``) is multiplied by f(RH): humid air carries more
   of its haze in the atmosphere's Mie layer (milky, sun-forward aerial
   perspective) and less in the flat height fog.
2. **Dust** (desert surface, a METAR dust or sand code, or the card's
   ``weather.dust``): a warm Mie absorption colour (dust absorbs blue more than
   red), a tint on the atmosphere's "other" absorption layer and a tan
   volumetric fog albedo (:data:`DUST_ROWS`).
3. **The boundary-layer cap**: a second exponential fog through
   ``UExponentialHeightFogComponent::SetSecondFogData`` whose height offset is
   the inversion height, so from 1600-3000 m the haze reads as a layer with a
   top below the camera. The engine's fog is exponential, not a slab: the
   density at the inversion is ``second_fog_density`` and doubles every
   1 / (falloff x 0.1) m below it and halves as fast above it (SceneCore.cpp
   divides FogHeightFalloff by 1000 per cm; HeightFogCommon.ush uses exp2).
   The "flat top" is that steep halving, stated, not a hard edge.

**Visibility stays the card's.** The overlay's ground extinction is Koschmieder's
beta = 3.912 / V exactly as ``world_beauty.mie_split`` counts it: the grown Mie
and the second layer's ground extinction are taken out of the main height fog
(its density times ``fog_density_ratio``), and when together they would exceed
the haze (beta less Rayleigh) both are scaled down by one factor
(``renormalised``). ``visibility_model_km`` is what the overlay's three terms
sum to; :func:`parameters` asserts it is the card's within
:data:`VISIBILITY_TOLERANCE`.

**Labels.** Values only: nothing here moves a pixel (``pixel_moving: false``).
The second layer can dim the subject; the camera-to-subject Beer-Lambert
transmittance through it (:func:`subject_occlusion`, the
``world_beauty.occlusion`` row shape) is recorded per frame in
``world_beauty.frames[].cloud_path`` beside the clouds' rows, and a row whose
transmittance is under ``OCCLUSION_FLAG_TRANSMITTANCE`` (0.5) is flagged and
sets ``cloud_occludes_aircraft``, the same way a cloud does.

This module is the Python twin of the pure block in
``ue/Plugins/FlightSimBridge/Source/FlightSimBridge/Private/FlightSimDustHaze.cpp``
(``FLIGHTSIM-DUSTHAZE-PURE-BEGIN`` .. ``-END``); tests/test_dust_haze.py pins
the table by text and, where a C++ compiler exists, runs the block against
this file number for number.

EVERY value in :data:`DUST_ROWS`, :data:`RH_GAMMA`,
:data:`DEFAULT_INVERSION_HEIGHT_M` and :data:`DEFAULT_RH_PCT` is UNCALIBRATED:
set by probe render on the render machine (docs/visual/PROBE_LOG.md
## dust-humidity-haze). The haboob local fog volume (a duststorm wall) is NOT
here: it would hide the subject in a way this record cannot model.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple, Union

from . import world_beauty as wb
from .weather_visuals import ENGINE_FOG_DENSITY_PER_EXTINCTION

REFERENCES = (
    "Hanel, G. (1976), The properties of atmospheric aerosol particles as functions of the "
    "relative humidity at thermodynamic equilibrium with the surrounding moist air, "
    "Advances in Geophysics 19, 73-188 (f(RH) = (1 - RH)^-gamma)",
    "Koschmieder, H. (1924); Middleton, W. E. K. (1952), Vision through the Atmosphere "
    "(beta = 3.912 / V)",
    "Dubovik, O. et al. (2002), Variability of absorption and optical properties of key "
    "aerosol types observed in worldwide locations, J. Atmos. Sci. 59, 590-608 (dust "
    "single-scattering albedo lower in the blue)",
    "UE 5.7.4 SceneCore.cpp FExponentialHeightFogSceneInfo (FogDensity, FogHeightFalloff / "
    "1000 per cm; second fog height = actor Z + FogHeightOffset), HeightFogCommon.ush (exp2)",
)

#: The rows, in the C++ enum's order (EFlightSimDustRow).
ROWS: Tuple[str, ...] = ("none", "haze", "dust")

#: Field order of one row (the C++ pure block's DustFieldCount fields).
DUST_FIELDS: Tuple[str, ...] = (
    "mie_absorption_r", "mie_absorption_g", "mie_absorption_b",       # SetMieAbsorption colour
    "other_absorption_r", "other_absorption_g", "other_absorption_b",  # SetOtherAbsorption colour
    "other_absorption_scale",                                          # SetOtherAbsorptionScale (1/km)
    "vfog_albedo_r", "vfog_albedo_g", "vfog_albedo_b",                 # SetVolumetricFogAlbedo (sRGB bytes)
    "second_fog_density",      # engine FogDensity AT the inversion height (SetSecondFogData)
    "second_fog_falloff",      # engine FogHeightFalloff of the second fog
    "inversion_height_m",      # the second fog's offset above the fog actor (m), card overrides
)

#: The engine's own defaults (SkyAtmosphereComponent.cpp: MieAbsorption white;
#: OtherAbsorption (0.000650, 0.001881, 0.000085) stored as a colour / its
#: green and a scale of its green; ExponentialHeightFogComponent.cpp:
#: VolumetricFogAlbedo white). The ``none`` row is these: no tint.
ENGINE_OTHER_ABSORPTION = (0.000650 / 0.001881, 1.0, 0.000085 / 0.001881)
ENGINE_OTHER_ABSORPTION_SCALE = 0.001881

#: UNCALIBRATED: set by probe render on the render machine (every number).
#: Colours are relative (the green channel carries the visibility-matched
#: amount); dust absorbs blue more than red, so its Mie absorption colour rises
#: to the blue and the sky and the far terrain warm.
DUST_ROWS: Dict[str, Dict[str, float]] = {
    "none": dict(mie_absorption_r=1.0, mie_absorption_g=1.0, mie_absorption_b=1.0,
                 other_absorption_r=ENGINE_OTHER_ABSORPTION[0], other_absorption_g=1.0,
                 other_absorption_b=ENGINE_OTHER_ABSORPTION[2],
                 other_absorption_scale=ENGINE_OTHER_ABSORPTION_SCALE,
                 vfog_albedo_r=255, vfog_albedo_g=255, vfog_albedo_b=255,
                 second_fog_density=0.0, second_fog_falloff=0.015, inversion_height_m=1500.0),
    "haze": dict(mie_absorption_r=0.9, mie_absorption_g=1.0, mie_absorption_b=1.1,
                 other_absorption_r=ENGINE_OTHER_ABSORPTION[0], other_absorption_g=1.0,
                 other_absorption_b=ENGINE_OTHER_ABSORPTION[2],
                 other_absorption_scale=ENGINE_OTHER_ABSORPTION_SCALE,
                 vfog_albedo_r=245, vfog_albedo_g=245, vfog_albedo_b=245,
                 second_fog_density=0.0002, second_fog_falloff=0.015, inversion_height_m=1500.0),
    "dust": dict(mie_absorption_r=0.45, mie_absorption_g=1.0, mie_absorption_b=2.2,
                 other_absorption_r=0.45, other_absorption_g=1.0, other_absorption_b=0.30,
                 other_absorption_scale=0.0024,
                 vfog_albedo_r=222, vfog_albedo_g=196, vfog_albedo_b=160,
                 second_fog_density=0.0004, second_fog_falloff=0.015, inversion_height_m=1800.0),
}

#: Hanel's growth exponent by aerosol kind. UNCALIBRATED (literature orders of
#: magnitude: continental about 0.3, maritime about 0.5, mineral dust about 0.1
#: since it barely takes up water).
AEROSOLS: Tuple[str, ...] = ("continental", "maritime", "dust")
RH_GAMMA: Dict[str, float] = {"continental": 0.3, "maritime": 0.5, "dust": 0.1}
#: f(RH) stops growing here: the law diverges at saturation, where the air is
#: fog or cloud, which the card states separately.
RH_CAP = 0.95
#: The relative humidity when the card states none (percent). UNCALIBRATED.
DEFAULT_RH_PCT = 50.0
#: The inversion height when neither the card nor the row states one (m above
#: the fog actor, the scene datum). UNCALIBRATED.
DEFAULT_INVERSION_HEIGHT_M = 1500.0
#: The overlay's ground visibility is the card's within this share.
VISIBILITY_TOLERANCE = 0.05
#: The cloud_path row's layer name for the second fog.
LAYER_NAME = "dust_haze_second_fog"
#: Natural extinction (1/m) of one engine FogDensity unit at a near-zero falloff:
#: the repo's own conversion (weather_visuals.ENGINE_FOG_DENSITY_PER_EXTINCTION).
EXTINCTION_PER_M_PER_DENSITY = 1.0 / ENGINE_FOG_DENSITY_PER_EXTINCTION
#: FogHeightFalloff -> the exp2 rate per metre (SceneCore.cpp: / 1000 per cm).
FALLOFF_TO_PER_M = 0.1

#: METAR present-weather codes (WMO 4678) that select a row. A code may carry an
#: intensity (+/-), a proximity (VC) or a descriptor (BL, DR) before it.
DUST_CODES = ("DU", "SA", "DS", "SS", "PO")
HAZE_CODES = ("HZ", "FU", "BR")
_PREFIXES = ("+", "-", "VC", "BL", "DR")
#: The surface words (core/scenario/randomization.py "surface").
DESERT_SURFACES = ("desert",)
MARITIME_SURFACES = ("ocean",)

CALIBRATION = ("UNCALIBRATED: every DUST_ROWS value, RH_GAMMA, the inversion height and the "
               "second fog density are set by probe render on the render machine "
               "(docs/visual/PROBE_LOG.md ## dust-humidity-haze)")


def growth_factor(rh: float, gamma: float) -> float:
    """Hanel 1976: f(RH) = (1 - min(RH, RH_CAP))^-gamma, RH a fraction 0..1
    (below 0 is 0). f(0) = 1."""
    r = min(max(float(rh), 0.0), RH_CAP)
    return (1.0 - r) ** (-max(float(gamma), 0.0))


def _code_words(codes: Union[None, str, Iterable[str]]) -> Tuple[str, ...]:
    if codes is None:
        return ()
    if isinstance(codes, str):
        codes = codes.split()
    out = []
    for code in codes:
        word = str(code).strip().upper()
        changed = True
        while changed:
            changed = False
            for prefix in _PREFIXES:
                if word.startswith(prefix) and len(word) > len(prefix):
                    word, changed = word[len(prefix):], True
        out.append(word)
    return tuple(out)


def select_dust(biome: Optional[str], metar_codes: Union[None, str, Iterable[str]] = None,
                card_dust: Any = None) -> str:
    """The row: the card's ``weather.dust`` first (true -> dust, false ->
    none, or a row word); then a METAR dust or sand code (DU, SA, BLSA, DS,
    SS, PO) -> dust; then a desert surface -> dust; then a haze, smoke or mist
    code (HZ, FU, BR) -> haze; else none. Refuses an unknown word by name
    (dust_haze.row)."""
    if isinstance(card_dust, bool):
        return "dust" if card_dust else "none"
    if card_dust is not None:
        word = str(card_dust).strip().lower()
        if word not in ROWS:
            raise ValueError(f"dust_haze.row: weather.dust {card_dust!r} is not one of "
                             f"{', '.join(ROWS)} or true / false")
        return word
    words = _code_words(metar_codes)
    if any(any(w.startswith(c) for c in DUST_CODES) for w in words):
        return "dust"
    if biome is not None and str(biome).lower() in DESERT_SURFACES:
        return "dust"
    if any(any(w.startswith(c) for c in HAZE_CODES) for w in words):
        return "haze"
    return "none"


def aerosol_for(row: str, biome: Optional[str]) -> str:
    """dust for the dust row, maritime over the ocean, continental otherwise."""
    if row == "dust":
        return "dust"
    if biome is not None and str(biome).lower() in MARITIME_SURFACES:
        return "maritime"
    return "continental"


def second_fog_extinction_per_m(density: float, falloff: float, offset_m: float, z_m: float) -> float:
    """The second fog's natural extinction (1/m) at height z (m above the fog
    actor): density x the repo's unit x 2^(-falloff x 0.1 x (z - offset))."""
    if density <= 0.0:
        return 0.0
    return (density * EXTINCTION_PER_M_PER_DENSITY
            * 2.0 ** (-falloff * FALLOFF_TO_PER_M * (z_m - offset_m)))


def second_fog_tau(density: float, falloff: float, offset_m: float,
                   a_z_m: float, b_z_m: float, length_m: float) -> float:
    """Optical depth of a straight segment of ``length_m`` from height a to
    height b through the second fog: the exponential integrated exactly."""
    if density <= 0.0 or length_m <= 0.0:
        return 0.0
    k = falloff * FALLOFF_TO_PER_M * math.log(2.0)         # natural rate per m
    beta_a = second_fog_extinction_per_m(density, falloff, offset_m, a_z_m)
    dz = b_z_m - a_z_m
    x = k * dz
    if abs(x) < 1e-9:
        return beta_a * length_m
    return beta_a * length_m * (1.0 - math.exp(-x)) / x


def subject_occlusion(camera_z_m: float, subject_z_m: float, length_m: float,
                      second_fog: Dict[str, float]) -> Dict[str, Any]:
    """The camera-to-subject row through the second fog, in
    ``world_beauty.occlusion``'s shape: the path below the inversion
    (slab_path_m), the optical depth, the transmittance and whether it is
    under OCCLUSION_FLAG_TRANSMITTANCE."""
    tau = second_fog_tau(second_fog["density"], second_fog["falloff"], second_fog["offset_m"],
                         camera_z_m, subject_z_m, length_m)
    transmittance = math.exp(-tau)
    path = wb.slab_path_m(camera_z_m, subject_z_m, length_m, min(camera_z_m, subject_z_m, 0.0),
                          second_fog["offset_m"])
    return {"layer": LAYER_NAME, "path_m": path, "tau": tau, "transmittance": transmittance,
            "flagged": transmittance < wb.OCCLUSION_FLAG_TRANSMITTANCE}


def cloud_occlusion_entry(camera_z_m: float, subject_z_m: float, length_m: float,
                          second_fog: Dict[str, float]) -> Optional[Dict[str, Any]]:
    """The cloud_occlusion entry the frame gains when the second fog hides the
    subject (transmittance under 0.5), else None."""
    row = subject_occlusion(camera_z_m, subject_z_m, length_m, second_fog)
    return row if row["flagged"] else None


def parameters(rh_pct: Optional[float], visibility_km: Optional[float], dust_row: str,
               biome: Optional[str] = None, preset: Optional[str] = None,
               inversion_height_m: Optional[float] = None, fog_z_m: float = 0.0,
               camera_z_m: Optional[float] = None, subject_z_m: Optional[float] = None,
               length_m: Optional[float] = None) -> Dict[str, Any]:
    """Everything the overlay writes, in the shape of render.json
    ``world_beauty.dust_haze``.

    ``rh_pct`` None is DEFAULT_RH_PCT; ``visibility_km`` None or <= 0 is "not
    stated": the Mie and the main fog are left as the preset drew them and
    only the tints and the second layer are applied (no visibility to keep).
    ``preset`` None is the world preset a clear-sky card of this visibility
    selects. Heights are metres above the scene datum (world Z 0); the fog
    actor is at ``fog_z_m``."""
    if dust_row not in DUST_ROWS:
        raise ValueError(f"dust_haze.row: {dust_row!r} is not one of {', '.join(ROWS)}")
    row = DUST_ROWS[dust_row]
    rh_basis = "card" if rh_pct is not None else "default"
    rh_pct = DEFAULT_RH_PCT if rh_pct is None else float(rh_pct)
    rh = min(max(rh_pct / 100.0, 0.0), 1.0)
    aerosol = aerosol_for(dust_row, biome)
    gamma = RH_GAMMA[aerosol]
    f_rh = growth_factor(rh, gamma)
    stated = visibility_km is not None and float(visibility_km) > 0.0
    preset = preset or wb.select_preset(False, 0.0, False, 0.0, float(visibility_km or 0.0))
    inversion = float(row["inversion_height_m"] if inversion_height_m is None else inversion_height_m)
    offset = inversion - float(fog_z_m)
    density_row = float(row["second_fog_density"])
    falloff = float(row["second_fog_falloff"])
    ground_per_km = 1000.0 * second_fog_extinction_per_m(density_row, falloff, offset, -float(fog_z_m))

    out: Dict[str, Any] = {"row": dust_row, "aerosol": aerosol, "rh": rh, "rh_pct": rh_pct,
                           "rh_basis": rh_basis, "gamma": gamma, "f_rh": f_rh, "preset": preset}
    if stated:
        atm = wb.ATMOSPHERE[preset]
        split = wb.mie_split(float(visibility_km), atm["mie_share"], atm["mie_cap_per_km"])
        beta = split["beta_per_km"]
        haze = max(beta - wb.RAYLEIGH_GREEN_PER_KM, 0.0)
        mie_before = split["mie_extinction_per_km"]
        grown = mie_before * f_rh
        want = grown + ground_per_km
        scale = min(1.0, haze / want) if want > 0.0 else 1.0
        mie_after = grown * scale
        second_ground = ground_per_km * scale
        density = density_row * scale
        ff_before = split["fog_factor"]
        ff_after = max(ff_before - (mie_after - mie_before + second_ground) / beta, 0.0)
        total = mie_after + second_ground + ff_after * beta
        model_km = wb.KOSCHMIEDER / total if total > 0.0 else math.inf
        if abs(model_km / float(visibility_km) - 1.0) > VISIBILITY_TOLERANCE + 1e-12 \
                and float(visibility_km) >= wb.MIN_VISIBILITY_KM:
            raise ArithmeticError(f"overlay visibility {model_km:.4g} km against the card's "
                                  f"{float(visibility_km):.4g} km")
        out.update({
            "visibility_target_km": float(visibility_km), "visibility_model_km": model_km,
            "koschmieder_beta_per_km": beta, "mie_before": mie_before, "mie_after": mie_after,
            "mie_scattering_after": mie_after * wb.MIE_SINGLE_SCATTER_ALBEDO,
            "mie_absorption_after": mie_after * (1.0 - wb.MIE_SINGLE_SCATTER_ALBEDO),
            "fog_factor_before": ff_before, "fog_factor_after": ff_after,
            "fog_density_ratio": ff_after / ff_before if ff_before > 0.0 else 0.0,
            "renormalised": scale, "mie_basis": "grown by f(RH), renormalised to the card's visibility",
        })
    else:
        density = density_row
        second_ground = ground_per_km
        out.update({
            "visibility_target_km": None, "visibility_model_km": None,
            "koschmieder_beta_per_km": None, "mie_before": None, "mie_after": None,
            "mie_scattering_after": None, "mie_absorption_after": None,
            "fog_factor_before": None, "fog_factor_after": None, "fog_density_ratio": 1.0,
            "renormalised": 1.0,
            "mie_basis": "kept: the card states no visibility_km, so there is none to keep",
        })
    green = row["mie_absorption_g"]
    second = {"density": density, "falloff": falloff, "offset_m": offset}
    out.update({
        "mie_absorption_rgb": [row["mie_absorption_r"] / green, 1.0, row["mie_absorption_b"] / green],
        "other_absorption_rgb": [row["other_absorption_r"], row["other_absorption_g"],
                                 row["other_absorption_b"]],
        "other_absorption_scale": row["other_absorption_scale"],
        "vfog_albedo_rgb": [int(row["vfog_albedo_r"]), int(row["vfog_albedo_g"]),
                            int(row["vfog_albedo_b"])],
        "inversion_height_m": inversion,
        "second_fog": second,
        "second_fog_ground_extinction_per_km": second_ground,
        "subject_transmittance": None,
        "pixel_moving": False,
        "calibration": CALIBRATION,
    })
    if camera_z_m is not None and subject_z_m is not None and length_m is not None:
        occ = subject_occlusion(float(camera_z_m) - fog_z_m, float(subject_z_m) - fog_z_m,
                                float(length_m), {**second, "offset_m": offset})
        out["subject_transmittance"] = occ["transmittance"]
        out["subject_path"] = occ
    return out


# -- the card, read the way FlightSimDustHaze.cpp reads it ---------------------

def _obj(d: Any, key: str) -> Dict[str, Any]:
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def _num(d: Dict[str, Any], key: str) -> Optional[float]:
    v = d.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def magnus_rh_pct(temperature_c: float, dew_point_c: float) -> float:
    """RH from temperature and dew point (Magnus, Sonntag 1990 constants)."""
    def es(t):
        return 6.112 * math.exp(17.62 * t / (243.12 + t))
    return min(100.0, 100.0 * es(min(dew_point_c, temperature_c)) / es(temperature_c))


def card_inputs(card: Dict[str, Any]) -> Dict[str, Any]:
    """The overlay's inputs from a run card, in the C++ reader's order:
    rh from look.rh_pct, weather.rh_pct, the atmosphere block's stated
    relative humidity, or its stated dew point against 15 degC + the stated
    deviation (Magnus); the biome is weather_look.surface; the METAR codes are
    look.present_weather or weather.present_weather; the dust word
    weather.dust or look.dust; the inversion look.inversion_height_m or
    weather.inversion_height_m; the visibility look.visibility_km."""
    look = _obj(card, "look") or _obj(_obj(card, "randomization"), "look")
    weather = _obj(card, "weather")
    stated = _obj(_obj(card, "atmosphere_properties"), "stated")
    rh = _num(look, "rh_pct")
    if rh is None:
        rh = _num(weather, "rh_pct")
    if rh is None:
        rh = _num(_obj(stated, "relative_humidity_pct"), "value")
    if rh is None:
        dew = _num(_obj(stated, "dew_point_c"), "value")
        if dew is not None:
            dt = _num(_obj(stated, "temperature_deviation_c"), "value") or 0.0
            rh = magnus_rh_pct(15.0 + dt, dew)
    codes = look.get("present_weather", weather.get("present_weather"))
    dust = weather.get("dust", look.get("dust"))
    inversion = _num(look, "inversion_height_m")
    if inversion is None:
        inversion = _num(weather, "inversion_height_m")
    surface = _obj(card, "weather_look").get("surface")
    return {"rh_pct": rh, "biome": surface if isinstance(surface, str) else None,
            "metar_codes": codes if isinstance(codes, (str, list)) else None,
            "card_dust": dust, "inversion_height_m": inversion,
            "visibility_km": _num(look, "visibility_km")}


def card_parameters(card: Dict[str, Any], preset: Optional[str] = None) -> Dict[str, Any]:
    """:func:`parameters` for a run card (what the C++ Apply records)."""
    i = card_inputs(card)
    row = select_dust(i["biome"], i["metar_codes"], i["card_dust"])
    return parameters(i["rh_pct"], i["visibility_km"], row, biome=i["biome"], preset=preset,
                      inversion_height_m=i["inversion_height_m"])


def spec_parameters(spec) -> Dict[str, Any]:
    """:func:`parameters` for a scenario spec: the stated relative humidity
    (or dew point against 15 degC + the deviation), the surface word and the
    randomisation block's visibility. The expected values the verifier
    compares against render.json ``world_beauty.dust_haze``."""
    atmosphere = getattr(spec, "atmosphere", None)

    def value(name):
        q = getattr(atmosphere, name, None)
        v = getattr(q, "value", None)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    rh = value("relative_humidity_pct")
    if rh is None and value("dew_point_c") is not None:
        rh = magnus_rh_pct(15.0 + (value("temperature_deviation_c") or 0.0), value("dew_point_c"))
    word = str(getattr(getattr(spec, "surface", None), "value", "") or "")
    biome = None if word in ("", "unspecified", "None") else word
    vis_q = getattr(getattr(spec, "randomization", None), "visibility_km", None)
    vis = getattr(vis_q, "value", None)
    vis = float(vis) if isinstance(vis, (int, float)) and not isinstance(vis, bool) and vis > 0 else None
    return parameters(rh, vis, select_dust(biome), biome=biome)


def table_rows() -> Sequence[Sequence[float]]:
    """DUST_ROWS as the C++ table's rows (ROWS x DUST_FIELDS)."""
    return [[float(DUST_ROWS[r][f]) for f in DUST_FIELDS] for r in ROWS]
