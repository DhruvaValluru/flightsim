"""Render lighting: named presets and exact sun angles (VISUAL ONLY).

The ``lighting`` block (core/scenario/blocks.py ``LightingSpec``) lets a
spec say how the render is lit, on top of whatever placed the sun before
it (the documented default look, a stated ``environment.time_of_day``,
or the storm look):

* a **preset** word -- ``natural`` (change nothing), ``sunny``,
  ``super_bright``, ``soft``, ``hazy``, ``overcast``, ``golden_hour``,
  ``dramatic`` -- that supplies every knob below it did not get stated;
* the **sun direction in exact degrees** -- ``sun_elevation_deg`` above
  the horizon and ``sun_azimuth_deg`` the compass bearing the light comes
  FROM (0 north, 90 east), each overriding the preset and the time of day;
* **brightness** in stops (``brightness_ev``, added to the calibrated
  exposure) and four engine knobs: ``sun_intensity`` (x the calibrated
  sun), ``color_temperature_k`` (the sun's colour), ``shadow_softness_deg``
  (the sun disc's angular size: 0.5 is the real sun, larger blurs the
  shadow edge the way cloud-diffused light does), ``sky_fill`` (x the
  calibrated sky light, i.e. how bright the shadows are) and ``haze``
  (the height-fog density).

Precedence, field by field: a stated value > the preset's value > the
look underneath. A field neither states nor the preset names leaves the
look underneath alone, so ``natural`` with nothing stated is exactly the
look the render had before this module existed.

What is NOT claimed: the preset numbers were chosen by eye against the
engine's documented defaults (sun disc 0.5357 deg, sky light 1.0, 6500 K
white), not probe-calibrated against the Gate 6 exposure clauses the way
the dawn and noon looks were (gotcha 7). They are a starting point you
adjust, recorded with the run as stated, not a measured configuration.
Physics never reads any of this.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: The knobs a preset may supply, in the order the block lists them.
KNOBS = ("sun_elevation_deg", "brightness_ev", "sun_intensity",
         "color_temperature_k", "shadow_softness_deg", "sky_fill", "haze")

#: Named looks. Every value is a knob from :data:`KNOBS`; a knob a preset
#: leaves out keeps the look underneath. ``natural`` names nothing.
PRESETS: Dict[str, Dict[str, float]] = {
    "natural": {},
    "sunny": {"sun_elevation_deg": 55.0, "brightness_ev": 0.2, "sun_intensity": 1.15,
              "color_temperature_k": 5900.0, "shadow_softness_deg": 0.53,
              "sky_fill": 1.0, "haze": 0.0009},
    "super_bright": {"sun_elevation_deg": 72.0, "brightness_ev": 0.6, "sun_intensity": 1.6,
                     "color_temperature_k": 6300.0, "shadow_softness_deg": 0.45,
                     "sky_fill": 1.35, "haze": 0.0005},
    "soft": {"sun_elevation_deg": 38.0, "brightness_ev": 0.3, "sun_intensity": 0.75,
             "color_temperature_k": 6100.0, "shadow_softness_deg": 6.0,
             "sky_fill": 1.4, "haze": 0.002},
    "hazy": {"sun_elevation_deg": 35.0, "brightness_ev": 0.4, "sun_intensity": 0.85,
             "color_temperature_k": 5600.0, "shadow_softness_deg": 1.5,
             "sky_fill": 1.25, "haze": 0.006},
    "overcast": {"sun_elevation_deg": 45.0, "brightness_ev": 0.9, "sun_intensity": 0.3,
                 "color_temperature_k": 6800.0, "shadow_softness_deg": 25.0,
                 "sky_fill": 2.0, "haze": 0.0035},
    "golden_hour": {"sun_elevation_deg": 7.0, "brightness_ev": 0.4, "sun_intensity": 0.95,
                    "color_temperature_k": 3300.0, "shadow_softness_deg": 0.9,
                    "sky_fill": 0.75, "haze": 0.0018},
    "dramatic": {"sun_elevation_deg": 14.0, "brightness_ev": -0.2, "sun_intensity": 1.4,
                 "color_temperature_k": 4800.0, "shadow_softness_deg": 0.3,
                 "sky_fill": 0.45, "haze": 0.001},
}

PRESET_NAMES = tuple(PRESETS)

#: Spoken spellings the block accepts for a preset (normalised first).
ALIASES = {
    "default": "natural", "none": "natural", "normal": "natural",
    "sun": "sunny", "clear": "sunny", "bright": "sunny",
    "super bright": "super_bright", "very bright": "super_bright",
    "extra bright": "super_bright", "superbright": "super_bright",
    "cloudy": "overcast", "grey": "overcast", "gray": "overcast",
    "diffuse": "soft", "soft light": "soft",
    "golden": "golden_hour", "golden hour": "golden_hour", "sunset": "golden_hour",
    "low sun": "dramatic", "contrast": "dramatic", "high contrast": "dramatic",
    "haze": "hazy", "misty": "hazy",
}

#: Inclusive bounds a stated value must lie in (the validator refuses the
#: rest by name, ``lighting.range``). The elevation floor is the render
#: floor of core.environment.sun: no twilight/night scene below it.
RANGES: Dict[str, tuple] = {
    "sun_elevation_deg": (2.0, 90.0),
    "sun_azimuth_deg": (0.0, 360.0),
    "brightness_ev": (-5.0, 5.0),
    "sun_intensity": (0.01, 10.0),
    "color_temperature_k": (1700.0, 12000.0),
    "shadow_softness_deg": (0.0, 45.0),
    "sky_fill": (0.0, 10.0),
    "haze": (0.0, 0.05),
}

#: Engine look keys -> the commandlet flags core.render.flags emits for
#: them (only when present, so a look without them is unchanged).
ENGINE_KEYS = ("sun_intensity_scale", "sky_light_scale", "sun_temperature_k",
               "sun_source_angle_deg")


def canonical_preset(word: Any) -> str:
    """A preset word normalised onto :data:`PRESET_NAMES`; ValueError
    names the accepted words for anything else."""
    text = " ".join(str(word).strip().lower().replace("-", " ").split())
    text = ALIASES.get(text, text)
    text = text.replace(" ", "_")
    if text not in PRESETS:
        raise ValueError(f"lighting preset {word!r} is not one of "
                         f"{list(PRESET_NAMES)}")
    return text


def compass_to_engine_azimuth(compass_deg: float) -> float:
    """The commandlet's ``-sun-azim`` (yaw toward the sun) for a compass
    bearing -- the same convention as
    core.scenario.randomization.engine_sun_azimuth, restated so this
    module imports nothing from the scenario package."""
    return (90.0 - float(compass_deg)) % 360.0


def engine_to_compass_azimuth(engine_deg: float) -> float:
    """Inverse of :func:`compass_to_engine_azimuth`."""
    return (90.0 - float(engine_deg)) % 360.0


def effective_values(stated: Mapping[str, Any]) -> Dict[str, Any]:
    """Every knob after precedence (stated > preset), plus ``preset``
    and ``sun_azimuth_deg``; None where neither says anything.

    ``stated``: the block's values by field name, None for unstated
    (``brightness_ev`` 0.0 counts as unstated: it is the block's
    default and adds nothing)."""
    preset = canonical_preset(stated.get("preset") or "natural")
    table = PRESETS[preset]
    out: Dict[str, Any] = {"preset": preset}
    for knob in KNOBS:
        value = stated.get(knob)
        if knob == "brightness_ev" and value is not None and float(value) == 0.0:
            value = None
        out[knob] = float(value) if value is not None else table.get(knob)
    azimuth = stated.get("sun_azimuth_deg")
    out["sun_azimuth_deg"] = None if azimuth is None else float(azimuth) % 360.0
    return out


def apply(base: Mapping[str, Any], stated: Mapping[str, Any],
          exposure_for_elevation) -> Dict[str, Any]:
    """The look the commandlet is given: ``base`` (the four look numbers,
    ``sun_azim`` the ENGINE yaw) with the lighting block layered on.

    ``exposure_for_elevation(elevation_deg) -> bias`` re-derives the
    calibrated exposure when the sun moves (the webapp's interpolation
    between the dawn and noon calibrations); brightness and the preset's
    stops are added on top. The returned dict carries the four look keys,
    the engine keys of :data:`ENGINE_KEYS` that are set, a ``lighting``
    record (compass azimuth, every effective knob) and a ``note``."""
    values = effective_values(stated)
    look: Dict[str, Any] = {key: base[key] for key in
                            ("sun_elev", "sun_azim", "exposure_bias", "fog_density")
                            if key in base}
    moved = []
    if values["sun_elevation_deg"] is not None:
        look["sun_elev"] = round(values["sun_elevation_deg"], 2)
        look["exposure_bias"] = exposure_for_elevation(look["sun_elev"])
        moved.append("elevation")
    if values["sun_azimuth_deg"] is not None:
        look["sun_azim"] = round(compass_to_engine_azimuth(values["sun_azimuth_deg"]), 2)
        moved.append("azimuth")
    if values["brightness_ev"] is not None:
        look["exposure_bias"] = round(float(look["exposure_bias"]) + values["brightness_ev"], 2)
    if values["haze"] is not None:
        look["fog_density"] = values["haze"]
    engine = {
        "sun_intensity_scale": values["sun_intensity"],
        "sky_light_scale": values["sky_fill"],
        "sun_temperature_k": values["color_temperature_k"],
        "sun_source_angle_deg": values["shadow_softness_deg"],
    }
    look.update({key: value for key, value in engine.items() if value is not None})
    compass = engine_to_compass_azimuth(look["sun_azim"])
    look["lighting"] = {
        "preset": values["preset"],
        "sun_elevation_deg": look["sun_elev"],
        "sun_azimuth_deg": round(compass, 2),
        "engine_sun_azimuth_deg": look["sun_azim"],
        **{knob: values[knob] for knob in KNOBS if knob != "sun_elevation_deg"},
        "calibrated": False,
    }
    parts = [f"lighting '{values['preset']}'",
             f"sun {look['sun_elev']:g} deg up, light from {compass:.0f} deg (compass)"]
    if values["brightness_ev"]:
        parts.append(f"brightness {values['brightness_ev']:+g} EV")
    for label, key, unit in (("sun x", "sun_intensity", ""),
                             ("colour", "color_temperature_k", " K"),
                             ("shadow softness", "shadow_softness_deg", " deg"),
                             ("sky fill x", "sky_fill", ""),
                             ("haze", "haze", "")):
        if values[key] is not None:
            parts.append(f"{label}{'' if label.endswith('x') else ' '}{values[key]:g}{unit}")
    look["note"] = ("; ".join(parts) + " (VISUAL; preset values are uncalibrated "
                    "starting points, not a Gate 6 measured look)")
    return look


#: The rain look: the engine knobs a stated rain rate implies, at anchor
#: rates (mm/h). Rain falls from cloud, so the sun dims, the shadows soften
#: and fill from the sky, the light cools and the air thickens; between the
#: anchors the knobs are interpolated on log(rate), and held beyond them.
#: Measured on the owner's machine before this: "heavy rain" (10 mm/h)
#: rendered a clear, sunny day -- the rain's extinction reached the render
#: only through the randomisation block, and its streaks are sub-pixel at
#: the default 1/500 s shutter. Chosen by eye like the presets, NOT a
#: radiative model of a raining sky; a stated lighting value or preset
#: still wins over it.
RAIN_ANCHORS = (
    (0.1, {"sun_intensity": 0.85, "sky_fill": 1.1, "color_temperature_k": 6300.0,
           "shadow_softness_deg": 1.5, "haze": 0.002, "brightness_ev": -0.2}),
    (1.0, {"sun_intensity": 0.6, "sky_fill": 1.3, "color_temperature_k": 6600.0,
           "shadow_softness_deg": 4.0, "haze": 0.0035, "brightness_ev": -0.2}),
    (4.0, {"sun_intensity": 0.4, "sky_fill": 1.5, "color_temperature_k": 6800.0,
           "shadow_softness_deg": 12.0, "haze": 0.007, "brightness_ev": -0.1}),
    (10.0, {"sun_intensity": 0.25, "sky_fill": 1.6, "color_temperature_k": 7000.0,
            "shadow_softness_deg": 25.0, "haze": 0.012, "brightness_ev": 0.0}),
    (30.0, {"sun_intensity": 0.15, "sky_fill": 1.7, "color_temperature_k": 7200.0,
            "shadow_softness_deg": 35.0, "haze": 0.02, "brightness_ev": 0.1}),
)


def rain_knobs(rate_mmh: float) -> Dict[str, float]:
    """The rain look's knobs for a rain rate (mm/h), interpolated on
    log(rate) between :data:`RAIN_ANCHORS` and held beyond them."""
    import math

    rate = float(rate_mmh)
    if rate <= RAIN_ANCHORS[0][0]:
        return dict(RAIN_ANCHORS[0][1])
    for (r0, k0), (r1, k1) in zip(RAIN_ANCHORS, RAIN_ANCHORS[1:]):
        if rate <= r1:
            t = (math.log(rate) - math.log(r0)) / (math.log(r1) - math.log(r0))
            return {name: round(k0[name] + t * (k1[name] - k0[name]),
                                0 if name == "color_temperature_k" else 5 if name == "haze" else 2)
                    for name in k0}
    return dict(RAIN_ANCHORS[-1][1])


def with_rain(stated: Mapping[str, Any], rate_mmh: float, base_fog: float) -> Dict[str, Any]:
    """``stated`` with every knob it (or its preset) leaves open filled
    from the rain look; the haze never thins the air below ``base_fog``
    (a storm look's own fog stays)."""
    open_knobs = effective_values(stated)
    out = dict(stated)
    for name, value in rain_knobs(rate_mmh).items():
        if name == "haze":
            value = max(value, float(base_fog))
        if open_knobs.get(name) is None:
            out[name] = round(value, 5)
    return out


def problems(stated: Mapping[str, Any]) -> list:
    """(kind, message) for every stated value the render cannot take:
    ``"preset"`` for an unknown preset word, ``"range"`` for a number out
    of :data:`RANGES` or not a number. The validator refuses them as
    ``lighting.preset`` / ``lighting.range``."""
    out = []
    try:
        canonical_preset(stated.get("preset") or "natural")
    except ValueError as exc:
        out.append(("preset", str(exc)))
    for name, (low, high) in RANGES.items():
        value = stated.get(name)
        if value is None:
            continue
        if isinstance(value, bool):
            out.append(("range", f"lighting.{name} must be a number, not {value!r}"))
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out.append(("range", f"lighting.{name} must be a number, not {value!r}"))
            continue
        if not low <= number <= high:
            out.append(("range",
                        f"lighting.{name} = {number:g} is outside {low:g}..{high:g}"))
    return out


def stated_values(block) -> Dict[str, Optional[Any]]:
    """{field: value} from a ``LightingSpec`` (None where unstated)."""
    return {name: quantity.value for name, quantity in block.quantities()}
