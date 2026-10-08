"""The rain the beauty camera sees: 3-D drops in the scene, one card block.

The engine draws real geometry for a stated rain rate
(FlightSimRainParticles.cpp): thousands of thin streaks in a world-aligned
box ahead of the camera, each falling at its own drop's terminal speed,
advanced on the FDM's time every captured frame, occluded by the aircraft
and the ground, lit by the scene's sun and sky, and blurred by the lens
like anything else at that range. Beauty-only: the label captures never
see them (BeautyOnlyActors), so masks, classes and depths are unchanged.

What this block gives the host, from the stated rate R (mm/h):

* the DROPS -- Marshall & Palmer's exponential N(D) = N0 exp(-Lambda D)
  with the FITTED Lambda (core/scene/precipitation.py, the same closure
  the look's extinction uses), truncated to D_MIN_MM..D_MAX_MM: drops
  under 0.5 mm are left to the extinction (the fog row) and drops over
  6 mm break up. The host draws each drop's D from that truncated law
  with its seeded stream (inverse CDF), and its fall speed from Atlas,
  Srivastava & Sekhon 1973, v(D) = a - b exp(-c D) (``fall_speed_law``);
* the COUNT -- a THINNED sample, stated: the physical density of the
  visible drops (``visible_density_per_m3``, about 230 per m^3 at 1 mm/h)
  in the box would be hundreds of thousands, so the host draws
  MAX_DROPS x n(R) / n(REFERENCE_RATE_MMH) of them (never fewer than
  MIN_DROPS): heavier rain draws more drops in proportion to the
  visible drops' density, and the rest of the rain's optical effect is
  the extinction the fog row already carries (counted once there);
* the BOX -- ``box_m`` a side, its near face at the camera, recentred on
  the camera every frame (12 m: past it a 1.5 mm drop covers under a
  seventh of a pixel's width in a 60-degree, 1280-px view, so the budget
  is spent where rain is seen); a drop leaving it re-enters on the far
  side (toroidal wrap in world axes), so the field is stationary in the
  world and the camera flies through it; drops nearer than ``near_m`` are not
  drawn (a drop on the lens is the lens-drops look's, not this one's);
* the STREAK -- each drop is drawn as its own motion relative to the
  camera (drop velocity minus the camera's, from the solved pose track)
  over ``streak_exposure_s``. That exposure is a STATED LOOK CHOICE, not
  the card's shutter: at the presets' 1/500 s a falling drop moves 1.3 cm
  and is sub-pixel past a metre (measured on the owner's batch: "heavy
  rain" rendered no visible rain), so the streaks are drawn at 1/60 s,
  the exposure a video camera in rain shows. The width is the drop's
  diameter, floored at ``min_width_px`` of the pixel footprint at the
  drop's range, with its opacity scaled by diameter / drawn width so a
  sub-pixel drop covers what it physically covers.

Not claimed: the thinning is a stated sample, not the physical count; no
wind advection (the drops fall straight down in the world; a moving
camera still streaks them along its own motion); Atlas's law is for
sea-level air; no splashes, ripples on surfaces, or accumulation; the
drop's optics (refraction, the bright rim) are a lit translucent
material, not a ray-traced sphere of water; snow is not modelled.
"""

from __future__ import annotations

import math
from typing import Any, Dict

from .precipitation import ATLAS_A, ATLAS_B, ATLAS_C, MP_N0, _checked, fitted_lambda

#: The drawn drops' diameter range (mm): smaller ones are the extinction's,
#: larger ones break up (Pruppacher & Klett's ~6 mm) [unverified here].
D_MIN_MM = 0.5
D_MAX_MM = 6.0
#: The instance budget at REFERENCE_RATE_MMH and above, and the floor.
MAX_DROPS = 20000
MIN_DROPS = 1500
#: The rate the budget is spent at (the thunderstorm's visual rate,
#: core/scene/weather_look.py STORM_RAIN_MMH).
REFERENCE_RATE_MMH = 40.0
#: The box: a cube this many metres a side, its near face at the camera.
BOX_M = 12.0
#: Drops nearer than this to the camera are not drawn (metres).
NEAR_M = 0.5
#: The streak exposure (seconds): a stated look choice, see the docstring.
STREAK_EXPOSURE_S = 1.0 / 60.0
#: The narrowest drawn streak, in pixels at the drop's range.
MIN_WIDTH_PX = 1.0
#: The drop material's opacity at full coverage (a lit translucent streak).
OPACITY = 0.55

CARD_KEYS = ("rate_mmh", "lambda_per_mm", "d_min_mm", "d_max_mm", "fall_speed_law",
             "visible_density_per_m3", "count", "box_m", "near_m", "streak_exposure_s",
             "min_width_px", "opacity", "seed")


def visible_density_per_m3(lam: float, n0: float = MP_N0) -> float:
    """Drops per m^3 with D_MIN_MM <= D <= D_MAX_MM: N0 / Lambda x
    (exp(-Lambda D_MIN) - exp(-Lambda D_MAX))."""
    lam = float(lam)
    return n0 / lam * (math.exp(-lam * D_MIN_MM) - math.exp(-lam * D_MAX_MM))


def drop_count(rate_mmh: float) -> int:
    """The drawn drops: MAX_DROPS x n(R) / n(REFERENCE), clamped to
    [MIN_DROPS, MAX_DROPS]."""
    share = (visible_density_per_m3(fitted_lambda(_checked(rate_mmh)))
             / visible_density_per_m3(fitted_lambda(REFERENCE_RATE_MMH)))
    return int(min(MAX_DROPS, max(MIN_DROPS, round(MAX_DROPS * share))))


def diameter_mm(u: float, lam: float) -> float:
    """The inverse CDF of the truncated exponential the host samples: u in
    [0, 1) -> D in [D_MIN_MM, D_MAX_MM]. The host's FlightSimRainParticles.cpp
    RainDropDiameterMm is this formula."""
    lam = float(lam)
    span = 1.0 - math.exp(-lam * (D_MAX_MM - D_MIN_MM))
    return D_MIN_MM - math.log(1.0 - float(u) * span) / lam


def particle_block(rate_mmh: float, seed: int) -> Dict[str, Any]:
    """The ``rain_particles`` card block in CARD_KEYS order."""
    rate = _checked(rate_mmh)
    lam = fitted_lambda(rate)
    block = {"rate_mmh": round(rate, 4), "lambda_per_mm": round(lam, 6),
             "d_min_mm": D_MIN_MM, "d_max_mm": D_MAX_MM,
             "fall_speed_law": [ATLAS_A, ATLAS_B, ATLAS_C],
             "visible_density_per_m3": round(visible_density_per_m3(lam), 4),
             "count": drop_count(rate), "box_m": BOX_M, "near_m": NEAR_M,
             "streak_exposure_s": round(STREAK_EXPOSURE_S, 6),
             "min_width_px": MIN_WIDTH_PX, "opacity": OPACITY, "seed": int(seed)}
    if tuple(block) != CARD_KEYS:
        raise RuntimeError(f"rain_particles card keys {list(block)} are not the fixed order "
                           f"{list(CARD_KEYS)}")
    return block
