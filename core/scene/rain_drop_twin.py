"""The beauty rain drop's shader arithmetic in Python (hyperreal rain, 2026-11-14).

``assets/shaders/weather/rain_drop_opacity.hlsl`` (M_RainDrops's opacity) and its offset
twin draw one drop of the rain box as a streak: Garg & Nayar's coverage D / (|v| t) of
the drop over its exposure, times the drops a drawn one stands for (``weight``), the
light of a streak widened to a pixel kept (x true width / drawn width), the beauty's
terms over it (the soft profile, the per-drop variation, the coverage cap, the depth
fade, and -- since generation 7 -- the near drop's defocus smear). This module evaluates
that arithmetic for one pixel of one drop, in double precision, for

* ``generation`` 6 (lane D, 2026-11-11: the shader before hyperreal rain -- the cap
  0.22 applied AFTER the soft profile, no defocus), and
* the current generation (hyperreal rain: the cap on the streak's MEAN under the
  profile, the defocus smear ``aperture_cm`` at most ``BEAUTY_RAIN_DEFOCUS_MAX_PX``
  pixels, the across blur the greater of the soft width and the sharp width plus the
  smear),

so the two can be compared on numbers, with no engine. tests/test_hyperreal_rain.py
evaluates the HLSL text itself against :func:`drop_pixel` and pins the calibration:
a near drop's MEAN coverage on a beauty STILL (the view's shutter: motion blur is off
on a still, beauty_look.SHUTTER_POLICY) within 0.5x..1.5x of generation 6's, the
streak wider and longer, its Gaussian core kept under the cap. The knobs are
weather_look.BEAUTY_RAIN_DEFOCUS_SHARE and BEAUTY_RAIN_MAX_COVERAGE.

What this is NOT: a render. The engine's float32, its rasterisation of the quad and
the translucency's blend are not modelled; the pixel's coverage is the shader's
return value for the pixel's corner coordinates. UNCALIBRATED on a frame.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional

from core.scene import weather_look
from core.scene.rain_field import presented_width_mm
from core.scene import precipitation

#: The soft profile's normalisers (rain_drop_opacity.hlsl: exp(-4 x^2) over |x| <= 1
#: averages 0.441; sqrt(sin(pi t)) over [0, 1] averages 0.763).
ACROSS_MEAN = 0.441
ALONG_MEAN = 0.763
#: The per-drop brightness (Vary): lerp(1, 0.4 + 0.6 h, vary), h uniform: its mean.
BRIGHT_MIN = 0.4
BRIGHT_SPAN = 0.6
#: The per-drop length factor (Vary): lerp(1, 0.45 + 1.1 h, vary).
LENGTH_MIN = 0.45
LENGTH_SPAN = 1.1
#: The lens-near fade (the first 30 cm are the glass's job): smoothstep(5, 30, range cm).
NEAR_FADE_CM = (5.0, 30.0)
#: The shader's pi literal (the along profile's sin(pi t)), kept so the twin is the text's.
PI_HLSL = 3.14159265
#: Generation 6's cap (weather_look.BEAUTY_RAIN_MAX_COVERAGE before hyperreal rain).
GENERATION_6_MAX_COVERAGE = 0.22
#: The card camera's documented daylight shutter (core/scenario/camera.py
#: DEFAULT_EXPOSURE): the view's shutter on a card still, the streak's on every frame
#: in generation 6 and on a beauty STILL now.
STILL_SHUTTER_S = 1.0 / 500.0
#: The reference view: 54 deg over 1280 px (rain_veil.BEAUTY_REFERENCE_PIXEL_RAD).
REFERENCE_FOV_DEG = 54.0
REFERENCE_WIDTH_PX = 1280


def smoothstep(e0: float, e1: float, x: float) -> float:
    """HLSL's smoothstep (the shader's R.Ss)."""
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    t = min(max((x - e0) / (e1 - e0), 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def saturate(x: float) -> float:
    return min(max(float(x), 0.0), 1.0)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def pixel_angle_rad(horizontal_fov_deg: float = REFERENCE_FOV_DEG,
                    width_px: int = REFERENCE_WIDTH_PX) -> float:
    """The angle of one pixel (FFlightSimWeather::Advance's PixelAngle)."""
    return 2.0 * math.tan(math.radians(float(horizontal_fov_deg)) * 0.5) / max(1, int(width_px))


def vary_mean_brightness(vary: float) -> float:
    """The mean of the per-drop brightness over the drops: 1 - 0.3 x vary."""
    return lerp(1.0, BRIGHT_MIN + 0.5 * BRIGHT_SPAN, saturate(vary))


def defocus_blur_cm(aperture_cm: float, range_cm: float, pixel_angle: float,
                    max_px: float = weather_look.BEAUTY_RAIN_DEFOCUS_MAX_PX) -> float:
    """The smear the shader adds to a drop at ``range_cm``: Aperture, at most
    ``max_px`` pixels at that range (the shader's RainDefocusMaxPx)."""
    if not (aperture_cm > 0.0):
        return 0.0
    return min(float(aperture_cm), float(max_px) * float(range_cm) * float(pixel_angle))


def current_shape(aperture_cm: float = 0.0, **overrides: float) -> Dict[str, float]:
    """The current beauty shape's shader inputs (weather_look.beauty_rain_shape
    at the heavy rate, every term on), the defocus smear given."""
    shape = weather_look.beauty_rain_shape(weather_look.BEAUTY_RAIN_HEAVY_MMH, 262144)
    row = {"soft": shape["softness"], "vary": shape["variation"],
           "max_streak_rad": shape["max_streak_rad"], "max_coverage": shape["max_coverage"],
           "depth_fade_cm": 0.0, "aperture_cm": float(aperture_cm), "generation": 8}
    row.update(overrides)
    return row


def generation_6_shape(**overrides: float) -> Dict[str, float]:
    """Generation 6's shader inputs: the same soft, varied streak with the cap 0.22
    after the profile and no defocus (the shader before hyperreal rain)."""
    row = current_shape(0.0, max_coverage=GENERATION_6_MAX_COVERAGE, generation=6)
    row.update(overrides)
    return row


def drop_pixel(diameter_mm: float, speed_mps: float, shutter_s: float, range_cm: float,
               pixel_angle: float, weight: float, shape: Mapping[str, Any],
               corner_x: float = 0.5, corner_y: float = 0.5, length_u: float = 0.5,
               bright_u: float = 0.5, width_mm: Optional[float] = None,
               edge: float = 1.0) -> Dict[str, float]:
    """One pixel of one drop's streak: rain_drop_opacity.hlsl's arithmetic, line
    for line, for ``shape["generation"]`` 6 or the current one.

    ``speed_mps`` is the drop's speed relative to the camera (fall speed less the
    wind and the camera's motion along it; the twin takes the magnitude);
    ``range_cm`` the drop's range (the shader's ``dist``); ``corner_x/y`` the
    pixel's place on the quad (UV0: 0..1 across, 0..1 along); ``length_u`` and
    ``bright_u`` the drop's two uniform hashes (0.5: the median drop); ``edge``
    the box-face fade (1 inside the box). Returns the streak and drawn width
    (cm), the mean coverage before the cap, and ``shown``, the pixel's coverage."""
    generation = int(shape.get("generation", 8))
    soft = float(shape.get("soft", 0.0))
    vary = float(shape.get("vary", 0.0))
    max_streak = float(shape.get("max_streak_rad", 0.0))
    max_coverage = float(shape.get("max_coverage", 1.0))
    depth_fade = float(shape.get("depth_fade_cm", 0.0))
    aperture = float(shape.get("aperture_cm", 0.0))
    if width_mm is None:
        width_mm = presented_width_mm(diameter_mm)
    speed_cm = float(speed_mps) * 100.0
    diameter_cm = float(diameter_mm) * 0.1
    streak = max(speed_cm * float(shutter_s), diameter_cm)
    bright = 1.0
    if vary > 0.0:
        streak *= lerp(1.0, LENGTH_MIN + LENGTH_SPAN * float(length_u), vary)
        bright = lerp(1.0, BRIGHT_MIN + BRIGHT_SPAN * float(bright_u), vary)
    dist = max(float(range_cm), 1.0)
    if max_streak > 0.0:
        streak = max(min(streak, max_streak * dist), diameter_cm)
    width_cm = float(width_mm) * 0.1
    sharp = max(width_cm, dist * float(pixel_angle))
    width = sharp
    if soft > 0.0:
        width *= 1.0 + soft
    blur = 0.0
    if generation >= 7 and aperture > 0.0:
        blur = defocus_blur_cm(aperture, dist, pixel_angle)
        streak += blur
        width = max(width, sharp + blur)
    coverage = (diameter_cm / streak) * (width_cm / width) * float(weight)
    profile = 1.0
    if soft > 0.0 or vary > 0.0:
        x = 2.0 * (float(corner_x) - 0.5)
        across = lerp(1.0, math.exp(-4.0 * x * x) / ACROSS_MEAN, saturate(soft))
        along = lerp(1.0, math.sqrt(max(math.sin(PI_HLSL * saturate(corner_y)), 0.0)) / ALONG_MEAN,
                     saturate(soft))
        profile = across * along * bright
    near_fade = smoothstep(NEAR_FADE_CM[0], NEAR_FADE_CM[1], dist)
    if generation >= 7:
        # The cap on the MEAN, the profile over it (a capped streak keeps its core).
        shown = min(saturate(coverage), max_coverage)
        if soft > 0.0 or vary > 0.0:
            shown = saturate(shown * profile)
    else:
        # Generation 6: the profile first, then the cap (a capped streak is a flat bar).
        shown = min(saturate(coverage * profile), max_coverage)
    if depth_fade > 0.0:
        shown *= math.exp(-dist / depth_fade)
    return {"streak_cm": streak, "width_cm": width, "sharp_cm": sharp, "blur_cm": blur,
            "coverage": coverage, "profile": profile, "shown": shown * float(edge) * near_fade}


def streak_statistics(diameter_mm: float, speed_mps: float, shutter_s: float, range_cm: float,
                      pixel_angle: float, weight: float, shape: Mapping[str, Any],
                      samples: int = 48, drops: int = 16, **kw: Any) -> Dict[str, float]:
    """The streak over its drawn quad and over the drops' hashes: the mean
    pixel coverage, the brightest pixel, the drawn size and the integrated light
    (mean x area, cm^2 of coverage: what Garg & Nayar conserve)."""
    total = 0.0
    peak = 0.0
    count = 0
    first: Optional[Dict[str, float]] = None
    for d in range(max(1, int(drops))):
        u = (d + 0.5) / max(1, int(drops))
        for i in range(samples):
            cx = (i + 0.5) / samples
            for j in range(samples):
                cy = (j + 0.5) / samples
                row = drop_pixel(diameter_mm, speed_mps, shutter_s, range_cm, pixel_angle, weight,
                                 shape, corner_x=cx, corner_y=cy, length_u=u, bright_u=u, **kw)
                if first is None:
                    first = row
                total += row["shown"]
                peak = max(peak, row["shown"])
                count += 1
    assert first is not None
    mean = total / count
    # The drawn quad at the median drop (length_u 0.5).
    median = drop_pixel(diameter_mm, speed_mps, shutter_s, range_cm, pixel_angle, weight, shape, **kw)
    return {"mean": mean, "peak": peak, "streak_cm": median["streak_cm"],
            "width_cm": median["width_cm"], "coverage": median["coverage"],
            "light_cm2": mean * median["streak_cm"] * median["width_cm"]}


def near_drop_comparison(range_m: float, diameter_mm: float = 2.0, weight: float = 1.0,
                         shutter_s: float = STILL_SHUTTER_S,
                         horizontal_fov_deg: float = REFERENCE_FOV_DEG,
                         width_px: int = REFERENCE_WIDTH_PX, **kw: Any) -> Dict[str, float]:
    """Generation 6 against the current generation for one drop at ``range_m``,
    through the view's lens, over ``shutter_s`` (a beauty STILL's by default:
    the view's, the same in both). Returns the two means and peaks and their
    ratios (current / generation 6), the drawn width and streak ratios, and the
    current streak's core-to-edge contrast (1 on a flat bar)."""
    pixel = pixel_angle_rad(horizontal_fov_deg, width_px)
    aperture = weather_look.beauty_rain_defocus_cm(horizontal_fov_deg)
    speed = precipitation.terminal_velocity_mps(diameter_mm)
    args = (diameter_mm, speed, shutter_s, float(range_m) * 100.0, pixel, weight)
    old = streak_statistics(*args, generation_6_shape(), **kw)
    new = streak_statistics(*args, current_shape(aperture), **kw)
    centre = drop_pixel(*args, current_shape(aperture), corner_x=0.5, corner_y=0.5)["shown"]
    flank = drop_pixel(*args, current_shape(aperture), corner_x=0.9, corner_y=0.5)["shown"]
    return {"generation_6_mean": old["mean"], "mean": new["mean"],
            "mean_ratio": new["mean"] / old["mean"] if old["mean"] > 0.0 else math.inf,
            "generation_6_peak": old["peak"], "peak": new["peak"],
            "peak_ratio": new["peak"] / old["peak"] if old["peak"] > 0.0 else math.inf,
            "width_ratio": new["width_cm"] / old["width_cm"],
            "streak_ratio": new["streak_cm"] / old["streak_cm"],
            "light_ratio": new["light_cm2"] / old["light_cm2"] if old["light_cm2"] > 0.0 else math.inf,
            "core_contrast": centre / flank if flank > 0.0 else math.inf,
            "aperture_cm": aperture, "pixel_angle_rad": pixel, "speed_mps": speed}
