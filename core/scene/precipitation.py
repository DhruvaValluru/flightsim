"""Precipitation: the drop-size distribution, the fall speed, the streak, the extinction.

W3 (docs/ADVANCEMENTS_BLUEPRINT.md section 4, "Corrections applied"). What a
rain render is GIVEN, from one stated rain rate R (``environment.
precipitation_rate_mmh``, mm/h):

* the DROP-SIZE DISTRIBUTION -- Marshall & Palmer 1948's exponential
  N(D) = N0 exp(-Lambda D), N0 = 8000 m^-3 mm^-1, D in mm. MP's own
  Lambda = 4.1 R^-0.21 mm^-1 does NOT reproduce R through the fall-speed
  law below: the rain rate the distribution carries,

      R(Lambda) = 6 pi 1e-4 int D^3 v(D) N(D) dD
                = 6 pi 1e-4 N0 6 [a / Lambda^4 - b / (Lambda + c)^4]   (mm/h)

  (the closed form of the integral with v(D) = a - b exp(-c D)), gives
  4.73 mm/h at a stated 4 (18 % over, measured here). So Lambda is FITTED:
  solved by bisection so that R(Lambda) equals the stated R (closure
  measured within 1e-9 relative; the contract is 1 %), with MP's Lambda
  recorded beside it. The Atlas law is negative below 0.109 mm; the rate
  integral clamps it at zero there (the incomplete-gamma form of the same
  moment), a share of R of 1.3e-5 at 4 mm/h, 4.9e-5 at 1 mm/h and 3.2e-3
  at 0.01 mm/h (measured by an independent quadrature);
* the MEDIAN-VOLUME DIAMETER D0 = 3.67 / Lambda (exact for an
  exponential distribution) -- the drop the streak model draws;
* the TERMINAL VELOCITY v(D) = 9.65 - 10.3 exp(-0.6 D) m/s (Atlas,
  Srivastava & Sekhon 1973, D in mm; sea-level air), v_t = v(D0). The
  Gunn & Kinzer 1949 anchor v(2 mm) = 6.5 m/s is pinned (6.548);
* the STREAK -- the drop's velocity RELATIVE to the camera (drop minus
  camera, in camera axes x right, y down, z forward) over the shutter,
  projected: for a drop at camera-frame (X, Y, Z) the pixel rate is
  u' = f_x (V_x Z - X V_z) / Z^2, v' = f_y (V_y Z - Y V_z) / Z^2, and the
  streak is t_shutter (u', v') px -- linear in the shutter and, on the
  optical axis, inverse in the range (both measured). The card's per-camera
  numbers are on the optical axis at REFERENCE_RANGE_M: ``stationary``
  (a camera at rest; the drop falls across a level view) and
  ``relative`` (the camera moving at the spec's airspeed at the preset's
  stated angle to its view axis, VIEW_TO_VELOCITY_DEG);
* the EXTINCTION by Atlas 1953 (J. Meteor. 10, 486 [unverified here]):
  geometric optics, extinction efficiency 2 over the drops' cross
  sections, sigma = 2 int (pi D^2 / 4) N(D) dD = pi N0 / Lambda^3 (1/m
  with the mm^2 -> m^2 factor). RECONCILED with the Koschmieder fog row
  (``core.scene.weather_visuals``) so that nothing is counted twice: a
  stated or drawn visibility is a METEOROLOGICAL visibility -- the total
  extinction an observer sees, rain included -- so the rain's sigma is
  NOT added to it. The fog row's extinction is max(3.912 / V, sigma_rain):
  the rain can only lower a visibility that was clearer than the rain
  allows, never stack on one that already includes it; and the streaks
  are additive screen-space light with NO extinction of their own, so the
  rain's attenuation enters the render exactly once, through the fog row;
* the RATE BOUNDS -- MIL-HDBK-310 [unverified here]: a stated rate must
  be a positive number no larger than RAIN_RATE_MAX_MMH (31.2 mm/min,
  the one-minute world-record extreme the handbook cites), refused
  ``look.precipitation_rate``; a rate above the handbook's operational
  1 % worst-month value (0.8 mm/min = 48 mm/h) is accepted and flagged.

Not claimed: screen-space rain with a physical length; no volumetric rain,
no splashes, no accumulation, no wet-lens drops; snow is stated ABSENT
(its own fall speed, about 1 m/s per Gunn & Marshall 1958, is not
modelled: a rate is rain); the drops are advected by no wind in the card
numbers (the wind is an input of :func:`relative_velocity_camera`);
Atlas's law is for sea-level air (no density correction); the particles
are a probe until the engine half (W5, M_RainStreaks on the beauty capture
only) is compiled and measured.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

#: Marshall & Palmer 1948: N0 (m^-3 mm^-1) and Lambda = 4.1 R^-0.21 (mm^-1).
MP_N0 = 8000.0
MP_LAMBDA_A = 4.1
MP_LAMBDA_B = -0.21
#: Atlas, Srivastava & Sekhon 1973: v(D) = a - b exp(-c D), m/s, D in mm.
ATLAS_A = 9.65
ATLAS_B = 10.3
ATLAS_C = 0.6
#: The median-volume diameter of an exponential DSD: D0 = 3.67 / Lambda.
MEDIAN_VOLUME_FACTOR = 3.67
#: 6 pi 1e-4: mm^3 m/s per m^3 -> mm/h (pi/6 x 1e-9 x 3.6e6).
RATE_FACTOR = 6.0 * math.pi * 1e-4
#: MIL-HDBK-310 rain-rate bounds [unverified here], mm/h.
RAIN_RATE_MAX_MMH = 31.2 * 60.0
RAIN_RATE_OPERATIONAL_MMH = 0.8 * 60.0
#: Where the fitted Lambda is searched (mm^-1): R(0.3) is 6e4 mm/h, R(40) 7e-5.
LAMBDA_BRACKET = (0.3, 40.0)
#: The closure the contract asks of the fit (relative).
CLOSURE_TOLERANCE = 0.01
#: The card's streak geometry: the drop on the optical axis this far away.
REFERENCE_RANGE_M = 20.0
#: The preset's stated angle between its view axis and its own velocity
#: (degrees): chase and cockpit look along the track, the wingman looks
#: abeam at the aircraft, an explicit camera is graded at the abeam worst
#: case; ground and tower cameras do not move (None).
VIEW_TO_VELOCITY_DEG: Dict[str, Optional[float]] = {
    "chase": 0.0, "cockpit": 0.0, "wingman": 90.0, "explicit": 90.0,
    "ground": None, "tower": None,
}
#: The card's ``look.precipitation`` keys, in their fixed order.
CARD_KEYS = ("rate_mmh", "lambda", "d0_mm", "v_t_mps", "streak_px", "density")
KT_TO_MPS = 0.514444

REFERENCES = (
    "Marshall, J. S. & Palmer, W. McK. 1948, J. Meteor. 5, 165 [unverified here]",
    "Atlas, D., Srivastava, R. C. & Sekhon, R. S. 1973, Rev. Geophys. Space Phys. 11, 1 "
    "[unverified here]",
    "Gunn, R. & Kinzer, G. D. 1949, J. Meteor. 6, 243 (v(2 mm) = 6.49 m/s) [unverified here]",
    "Atlas, D. 1953, J. Meteor. 10, 486 (optical extinction by rainfall) [unverified here]",
    "MIL-HDBK-310 (1997), rainfall rate [unverified here]",
    "Koschmieder 1924 (the fog row, core/scene/weather_visuals.py)",
)

NOT_CLAIMED = (
    "screen-space rain with a physical length; no volumetric rain, splashes or accumulation",
    "snow is not modelled: a stated rate is rain",
    "Atlas's fall speed is for sea-level air (no density correction)",
    "the particles are a probe until the engine half (W5) is compiled and measured",
)


class PrecipitationError(Exception):
    """A rain rate that cannot be drawn, refused by name
    (``look.precipitation_rate``)."""

    def __init__(self, constraint: str, message: str) -> None:
        self.constraint = constraint
        self.message = message
        super().__init__(f"{constraint}: {message}")


def rate_problem(value: Any) -> Optional[str]:
    """Why a STATED rate cannot be drawn, or None (None = unstated, no rain)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return f"environment.precipitation_rate_mmh must be a number of mm/h, not {value!r}"
    try:
        rate = float(value)
    except (TypeError, ValueError):
        return f"environment.precipitation_rate_mmh must be a number of mm/h, not {value!r}"
    if not math.isfinite(rate) or rate <= 0.0:
        return (f"environment.precipitation_rate_mmh must be a positive rain rate, not "
                f"{value!r} (no rain is the field unstated)")
    if rate > RAIN_RATE_MAX_MMH:
        return (f"environment.precipitation_rate_mmh {rate:g} mm/h exceeds the "
                f"{RAIN_RATE_MAX_MMH:g} mm/h one-minute extreme MIL-HDBK-310 cites")
    return None


def _checked(rate_mmh: Any) -> float:
    problem = rate_problem(rate_mmh)
    if problem is not None or rate_mmh is None:
        raise PrecipitationError("look.precipitation_rate", problem or "no rate stated")
    return float(rate_mmh)


def terminal_velocity_mps(diameter_mm: float) -> float:
    """Atlas et al. 1973: v(D) = 9.65 - 10.3 exp(-0.6 D), m/s."""
    return ATLAS_A - ATLAS_B * math.exp(-ATLAS_C * float(diameter_mm))


def mp_lambda(rate_mmh: float) -> float:
    """Marshall & Palmer's own Lambda = 4.1 R^-0.21, mm^-1."""
    return MP_LAMBDA_A * float(rate_mmh) ** MP_LAMBDA_B


#: Where the Atlas law crosses zero: v(D*) = 0 at D* = ln(b / a) / c = 0.109 mm.
ATLAS_ZERO_MM = math.log(ATLAS_B / ATLAS_A) / ATLAS_C


def _cubic_moment_below(k: float, x: float) -> float:
    """int_0^x D^3 exp(-k D) dD = (6 / k^4) [1 - exp(-k x) sum_{j<=3} (k x)^j / j!]."""
    kx = k * x
    return 6.0 / k ** 4 * (1.0 - math.exp(-kx) * (1.0 + kx + kx * kx / 2.0 + kx ** 3 / 6.0))


def rate_for_lambda(lam: float, n0: float = MP_N0, clamp: bool = True) -> float:
    """The rain rate (mm/h) an exponential DSD carries under the Atlas law:
    the closed form of the module docstring, with the law's negative part
    below ATLAS_ZERO_MM clamped to zero (``clamp``) by the incomplete-gamma
    form of the same integral -- a drop does not fall upward."""
    lam = float(lam)
    whole = 6.0 * (ATLAS_A / lam ** 4 - ATLAS_B / (lam + ATLAS_C) ** 4)
    if clamp:
        whole -= (ATLAS_A * _cubic_moment_below(lam, ATLAS_ZERO_MM)
                  - ATLAS_B * _cubic_moment_below(lam + ATLAS_C, ATLAS_ZERO_MM))
    return RATE_FACTOR * n0 * whole


def fitted_lambda(rate_mmh: float, n0: float = MP_N0) -> float:
    """Lambda (mm^-1) such that rate_for_lambda(Lambda) = R, by bisection
    (R(Lambda) is monotone decreasing on the bracket)."""
    rate = _checked(rate_mmh)
    lo, hi = LAMBDA_BRACKET
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if rate_for_lambda(mid, n0) > rate:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def negative_speed_fraction(lam: float, n0: float = MP_N0) -> float:
    """The share of R(Lambda) the clamp removes (the Atlas law's negative
    part, D below 0.109 mm), measured by midpoint quadrature -- apart from
    the incomplete-gamma form the rate uses, so the two check each other."""
    d_star = ATLAS_ZERO_MM
    steps = 2000
    h = d_star / steps
    total = 0.0
    for i in range(steps):
        d = (i + 0.5) * h
        total += d ** 3 * terminal_velocity_mps(d) * n0 * math.exp(-lam * d) * h
    return abs(RATE_FACTOR * total) / rate_for_lambda(lam, n0)


def extinction_per_m(lam: float, n0: float = MP_N0) -> float:
    """Atlas 1953, geometric optics: sigma = pi N0 / Lambda^3 x 1e-6 (1/m)."""
    return math.pi * n0 / float(lam) ** 3 * 1e-6


def number_density_per_m3(lam: float, n0: float = MP_N0) -> float:
    """Drops per cubic metre: N0 / Lambda."""
    return n0 / float(lam)


def liquid_water_g_m3(lam: float, n0: float = MP_N0) -> float:
    """rho_w (pi / 6) int D^3 N dD = pi rho_w N0 / Lambda^4 x 1e-9 kg/m^3, in g/m^3."""
    return math.pi * 1000.0 * n0 / float(lam) ** 4 * 1e-9 * 1000.0


def relative_velocity_camera(drop_velocity_enu: Sequence[float],
                             camera_velocity_enu: Sequence[float],
                             camera_axes_enu: Sequence[Sequence[float]]) -> Tuple[float, float, float]:
    """The drop's velocity relative to the camera in camera axes (x right,
    y down, z forward): (v_drop - v_cam) . each axis, the axes given as
    ENU unit vectors (right, down, forward)."""
    rel = [float(a) - float(b) for a, b in zip(drop_velocity_enu, camera_velocity_enu)]
    return tuple(sum(r * float(c) for r, c in zip(rel, axis)) for axis in camera_axes_enu)


def streak_vector_px(v_rel_camera: Sequence[float], shutter_s: float, fx_px: float,
                     fy_px: float, range_m: float, x_m: float = 0.0,
                     y_m: float = 0.0) -> Tuple[float, float, float]:
    """(du, dv, length) px: the drop at camera-frame (x_m, y_m, range_m)
    moving at ``v_rel_camera`` over the shutter (module docstring)."""
    vx, vy, vz = (float(v) for v in v_rel_camera)
    z = float(range_m)
    if not z > 0.0:
        raise ValueError(f"a drop's range must be positive metres, not {range_m!r}")
    t = float(shutter_s)
    du = t * float(fx_px) * (vx * z - float(x_m) * vz) / (z * z)
    dv = t * float(fy_px) * (vy * z - float(y_m) * vz) / (z * z)
    return du, dv, math.hypot(du, dv)


def preset_streaks(preset: str, shutter_s: float, fx_px: float, fy_px: float,
                   camera_speed_mps: float, v_t_mps: float,
                   range_m: float = REFERENCE_RANGE_M) -> Dict[str, Any]:
    """The card's per-camera streak numbers on the optical axis at
    ``range_m``: stationary (the fall across a level view) and relative
    (the camera's velocity at the preset's stated angle to its view)."""
    stationary = streak_vector_px((0.0, v_t_mps, 0.0), shutter_s, fx_px, fy_px, range_m)
    angle = VIEW_TO_VELOCITY_DEG.get(str(preset))
    speed = 0.0 if angle is None else float(camera_speed_mps)
    theta = math.radians(angle or 0.0)
    v_cam = (speed * math.sin(theta), 0.0, speed * math.cos(theta))
    relative = streak_vector_px((-v_cam[0], v_t_mps - v_cam[1], -v_cam[2]), shutter_s,
                                fx_px, fy_px, range_m)
    return {"stationary_px": round(stationary[2], 4), "relative_px": round(relative[2], 4),
            "relative_vector_px": [round(relative[0], 4), round(relative[1], 4)],
            "range_m": float(range_m), "shutter_s": float(shutter_s),
            "fx_px": round(float(fx_px), 4), "camera_speed_mps": round(speed, 4),
            "view_to_velocity_deg": angle}


def reconcile_extinction(visibility_km: float, rain_extinction: float) -> Dict[str, Any]:
    """The fog row with the rain counted ONCE: beta = max(3.912 / V,
    sigma_rain), V the meteorological (total) visibility."""
    from .weather_visuals import KOSCHMIEDER_CONSTANT, fog_extinction_per_m

    beta_visibility = fog_extinction_per_m(visibility_km)
    beta = max(beta_visibility, float(rain_extinction))
    return {"fog_extinction_per_m": beta,
            "visibility_km": KOSCHMIEDER_CONSTANT / (1000.0 * beta),
            "visibility_extinction_per_m": beta_visibility,
            "rain_extinction_per_m": float(rain_extinction),
            "limited_by": "rain" if float(rain_extinction) > beta_visibility else "visibility",
            "basis": "the stated visibility is the total (rain included): the rain's Atlas "
                     "extinction floors the fog row's, never adds to it; the streaks carry "
                     "no extinction"}


def rain(rate_mmh: float) -> Dict[str, Any]:
    """Every number the rain look records, from the stated rate."""
    rate = _checked(rate_mmh)
    lam = fitted_lambda(rate)
    lam_mp = mp_lambda(rate)
    d0 = MEDIAN_VOLUME_FACTOR / lam
    closed = rate_for_lambda(lam)
    return {
        "rate_mmh": rate,
        "lambda_fitted_per_mm": lam,
        "lambda_mp_per_mm": lam_mp,
        "rate_at_mp_lambda_mmh": rate_for_lambda(lam_mp),
        "closure": abs(closed - rate) / rate,
        "closure_tolerance": CLOSURE_TOLERANCE,
        "n0_per_m3_mm": MP_N0,
        "d0_mm": d0,
        "v_t_mps": terminal_velocity_mps(d0),
        "number_density_per_m3": number_density_per_m3(lam),
        "liquid_water_g_m3": liquid_water_g_m3(lam),
        "extinction_per_m": extinction_per_m(lam),
        "negative_speed_fraction": negative_speed_fraction(lam),
        "beyond_operational_1pct": rate > RAIN_RATE_OPERATIONAL_MMH,
    }


def card_block(rate_mmh: float, cameras: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """``look.precipitation`` in CARD_KEYS order. ``cameras``: one mapping
    per camera {camera_id, preset, shutter_s, fx_px, fy_px, speed_mps}."""
    numbers = rain(rate_mmh)
    streaks = {}
    for camera in cameras:
        streaks[str(camera["camera_id"])] = preset_streaks(
            camera["preset"], camera["shutter_s"], camera["fx_px"], camera["fy_px"],
            camera["speed_mps"], numbers["v_t_mps"])
    return {"rate_mmh": round(numbers["rate_mmh"], 4),
            "lambda": round(numbers["lambda_fitted_per_mm"], 6),
            "d0_mm": round(numbers["d0_mm"], 6),
            "v_t_mps": round(numbers["v_t_mps"], 6),
            "streak_px": streaks,
            "density": round(numbers["number_density_per_m3"], 4)}


def spec_rain_cameras(spec) -> list:
    """The per-camera inputs of :func:`card_block` from a spec: each
    camera's shutter and focal length in pixels, and its speed (the spec's
    airspeed, kt -> m/s, for a preset that moves with the aircraft)."""
    from ..scenario.camera import default_cameras

    cameras = list(spec.cameras) or list(default_cameras(spec))
    out = []
    speed = float(spec.airspeed.value) * KT_TO_MPS
    for camera in cameras:
        focal = float(camera.focal_length_mm.value)
        fx = focal * float(camera.width_px.value) / float(camera.sensor_width_mm.value)
        fy = focal * float(camera.height_px.value) / float(camera.sensor_height_mm.value)
        out.append({"camera_id": str(camera.camera_id.value), "preset": str(camera.preset.value),
                    "shutter_s": float(camera.exposure.shutter_s.value), "fx_px": fx,
                    "fy_px": fy, "speed_mps": speed})
    return out
