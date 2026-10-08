"""Rain as particles: the drops a render draws around its camera, the splashes, the windshield.

The streaks of :mod:`core.scene.precipitation` are a screen-space probe: one
streak length per camera, on the optical axis. This module is what a render
needs to draw rain as DROPS in the world instead -- every drop a sample of
the same Marshall & Palmer distribution (the same fitted Lambda, the same
Atlas fall speed), so the particles and the probe can never disagree about
the rain they show.

The rain box. Drops are drawn inside a box that follows the camera (the
technique every real-time rain renderer uses): each drop has a fixed
seed position p0 in the box and a velocity v (the wind plus its own fall
speed), and its world position at time t is

    p(t) = camera + wrap(p0 + D(t) - camera)

with D(t) the displacement the air carried it (the integral of the wind,
accumulated by the host step by step, plus -v_t(D) t vertically) and wrap
folding into [-half, half) on each axis. The drop is therefore FIXED IN
THE AIR -- a camera that flies through the rain at 60 m/s sees the drops
rush past at 60 m/s -- and the box is only where drops are drawn. Nothing
in this is random at render time: every drop is a pure function of its
index, the card's seed and the time (Gate 10-R: a replay draws the same
drops in the same places).

What is sampled, per drop (index i, the card's seed s), by SPLITMIX64 --
specified here bit for bit so the C++ port draws the same drops
(the card carries a selftest of the first drops):

* u0, u1, u2 -> p0 = (2 u - 1) * half, metres, along the box's three axes
               (the host's engine X, Y, Z: the box is axis-aligned in the
               engine frame, a uniform box either way);
* u3         -> D by the inverse CDF of N(D) = N0 exp(-Lambda D) truncated
               to [D_RENDER_MIN_MM, D_MAX_MM]:
               D = Dmin - ln(1 - u3 (1 - exp(-Lambda (Dmax - Dmin)))) / Lambda;
* u4         -> a phase in [0, 1) (the splash and shimmer offset).

The drawn subset. A drop below D_RENDER_MIN_MM is never drawn: its streak
is fainter than the rain's own veil (the fog row already carries the
rain's extinction, Atlas 1953, counted once). The drops at or above it
number n_r = N0 / Lambda (exp(-Lambda Dmin) - exp(-Lambda Dmax)) per m^3;
the box holds n_r V of them. A render draws min(PARTICLE_BUDGET, n_r V)
and records the WEIGHT n_r V / drawn: each drawn streak stands for that
many drops, its opacity raised by the weight (clamped at opaque) -- the
mean light the streaks add is conserved, the count of distinct streaks
is not, and the record says so.

The streak (Garg & Nayar 2007, the photometry of a falling drop
[unverified here]): over the exposure a drop of diameter D moving at |v|
relative to the camera sweeps a streak of length |v| t_shutter; any one
point of the streak is covered by the drop for D / |v| of the exposure,
so the streak's opacity is D / (|v| t_shutter) (clamped at 1, times the
weight); the drop's radiance is close to the mean radiance of its
surroundings (Garg & Nayar: the drop refracts a ~165 deg cone of the
environment), which the material takes from the sky light.

The drop's shape (Beard & Chuang 1987 [unverified here]): the axis ratio
b/a = 1.0048 + 0.0057 D - 2.628 D^2 + 3.682 D^3 - 1.677 D^4, D the
equivolume diameter in CENTIMETRES; the horizontal width a drop presents
is D (b/a)^(-1/3).

The fall speed aloft (Foote & du Toit 1969 [unverified here]): v(rho) =
v0 (rho0 / rho)^0.4 -- drops fall faster in thinner air. The factor is
evaluated once at the run's altitude (ISA) and recorded; precipitation.py
keeps its sea-level number for the streak probe, unchanged.

Splashes. The number flux of drawn drops onto the ground is

    F = int N(D) v(D) dD   (drops m^-2 s^-1)

in closed form for the Atlas law over [Dmin, Dmax]. A render draws the
splashes in the square of half side SPLASH_RADIUS_M about the camera's
ground point -- F (2 R)^2 per second -- as SPLASH_BUDGET slots that each
relight every slot period at a new hashed position (PCG32 in the material,
:func:`splash_position`), world-fixed by the same wrap as the drops; the
weight again records how many splashes each drawn one stands for. A
crown lives SPLASH_LIFETIME_S (Worthington-type crown and its secondary
droplets for a mm drop at terminal velocity: tens of ms [unverified
here]).

The windshield (the simulator's own rain_surface force pass is the
model's shape: drops impinge, stick below a shedding airspeed and run
off above it). Impingement per m^2 of glass is n_r |V| cos(theta), V the
true airspeed and theta the glass's angle to the flow (WINDSHIELD_COS);
a drop runs off at RUNOFF_GAIN (V - V_SHED) above V_SHED and holds below
it. These two constants are STATED, not measured: the run-off law is the
weakest number here and is labelled so on the card.

Not claimed: drop collisions, coalescence or breakup in flight; the
rain's own wind (a drop is advected by the wind at the CAMERA, the box
being tens of metres); splashes on anything but the ground plane under
the camera; drop-on-glass coalescence; snow (a stated rate is rain).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import precipitation as rain_model

#: The smallest drop a render draws (mm). Below it a streak is under the
#: rain's veil (stated, not measured; the Windows streak clause grades it).
D_RENDER_MIN_MM = 1.0
#: The largest drop: raindrops break up above ~6 mm (Pruppacher & Klett
#: 1997 [unverified here]).
D_MAX_MM = 6.0
#: The rain box's half extent, metres (east, north, up).
BOX_HALF_M = (10.0, 10.0, 8.0)
#: The most drops a render draws, and the most splash slots.
PARTICLE_BUDGET = 262144
SPLASH_BUDGET = 4096
#: Splashes are drawn in the square of this half side about the camera's
#: ground point.
SPLASH_RADIUS_M = 10.0
SPLASH_LIFETIME_S = 0.06
#: Splashes are drawn only when the ground is inside the box.
SPLASH_MAX_AGL_M = BOX_HALF_M[2]
#: Foote & du Toit's exponent.
FALL_SPEED_DENSITY_EXPONENT = 0.4
#: The windshield: the glass's cosine to the flow, the shedding airspeed
#: (m/s) and the run-off gain (STATED; see the module docstring).
WINDSHIELD_COS = 0.5
V_SHED_MPS = 22.0
RUNOFF_GAIN = 0.35
#: Glass area the windshield drop count is reported over (m^2): one square
#: metre, so the number is a flux per unit area the material scales by its
#: own screen coverage.
GLASS_AREA_M2 = 1.0
#: ISA sea level and lapse, for the fall-speed factor.
ISA_T0_K = 288.15
ISA_LAPSE_K_PER_M = 0.0065
ISA_EXPONENT = 4.255876  # g / (R L) - 1 for density

MASK64 = (1 << 64) - 1
GOLDEN64 = 0x9E3779B97F4A7C15
#: The card's seed is masked to 53 bits: a JSON number carries it exactly.
SEED_MASK = (1 << 53) - 1

#: The card's ``weather.rain`` keys, in their fixed order.
CARD_KEYS = ("rate_mmh", "rate_source", "lambda", "n0", "d_render_min_mm", "d_max_mm",
             "box_half_m", "density_drawn_per_m3", "expected_in_box", "particles", "weight",
             "ambient_rate_mmh", "ambient_fraction", "fall_speed_factor", "wind_enu_mps", "seed",
             "splash", "windshield", "selftest")
SELFTEST_DROPS = 4

REFERENCES = (
    "Marshall & Palmer 1948; Atlas, Srivastava & Sekhon 1973 (core/scene/precipitation.py)",
    "Garg, K. & Nayar, S. K. 2007, Int. J. Comput. Vis. 75, 3 (vision and rain) [unverified here]",
    "Beard, K. V. & Chuang, C. 1987, J. Atmos. Sci. 44, 1509 (raindrop shape) [unverified here]",
    "Foote, G. B. & du Toit, P. S. 1969, J. Appl. Meteor. 8, 249 (fall speed aloft) "
    "[unverified here]",
    "Pruppacher, H. R. & Klett, J. D. 1997, Microphysics of Clouds and Precipitation "
    "[unverified here]",
    "Steele, G. L. 2014 / Vigna, S.: SplitMix64; O'Neill, M. E. 2014: PCG",
)

NOT_CLAIMED = (
    "no drop collisions, coalescence or breakup in flight",
    "every drop is advected by the wind at the camera, not its own",
    "splashes only on the ground plane under the camera",
    "the windshield run-off law (V_SHED_MPS, RUNOFF_GAIN) is stated, not measured",
    "a drawn streak stands for 'weight' drops: mean light conserved, distinct streaks not",
)


# -- the hashes the C++ and the material share --------------------------------

def splitmix64(x: int) -> int:
    """SplitMix64's output function on a 64-bit state (Steele / Vigna)."""
    z = (int(x) + GOLDEN64) & MASK64
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


def unit(seed: int, index: int, channel: int) -> float:
    """A uniform in [0, 1): splitmix64(seed XOR splitmix64(8 index + channel)),
    its top 53 bits."""
    key = splitmix64((int(index) * 8 + int(channel)) & MASK64)
    return (splitmix64((int(seed) & MASK64) ^ key) >> 11) * (1.0 / (1 << 53))


def pcg32(value: int) -> int:
    """PCG's RXS-M-XS 32-bit hash (O'Neill 2014; the form GPU code uses):
    the splash slots' positions in the material, and their reference here."""
    state = (int(value) * 747796405 + 2891336453) & 0xFFFFFFFF
    word = (((state >> ((state >> 28) + 4)) ^ state) * 277803737) & 0xFFFFFFFF
    return ((word >> 22) ^ word) & 0xFFFFFFFF


# -- the distribution ---------------------------------------------------------

def truncated_number_density(lam: float, d_min: float = D_RENDER_MIN_MM,
                             d_max: float = D_MAX_MM, n0: float = rain_model.MP_N0) -> float:
    """Drops per m^3 with D in [d_min, d_max]: N0 / Lambda (e^-L dmin - e^-L dmax)."""
    lam = float(lam)
    return n0 / lam * (math.exp(-lam * d_min) - math.exp(-lam * d_max))


def sample_diameter_mm(u: float, lam: float, d_min: float = D_RENDER_MIN_MM,
                       d_max: float = D_MAX_MM) -> float:
    """The inverse CDF of the truncated exponential (module docstring)."""
    lam = float(lam)
    span = 1.0 - math.exp(-lam * (d_max - d_min))
    return d_min - math.log(1.0 - float(u) * span) / lam


def axis_ratio(diameter_mm: float) -> float:
    """Beard & Chuang 1987: b/a with D in centimetres."""
    d = float(diameter_mm) / 10.0
    return 1.0048 + 0.0057 * d - 2.628 * d ** 2 + 3.682 * d ** 3 - 1.677 * d ** 4


def presented_width_mm(diameter_mm: float) -> float:
    """The horizontal width of an oblate drop of equivolume diameter D."""
    return float(diameter_mm) * axis_ratio(diameter_mm) ** (-1.0 / 3.0)


def isa_density_ratio(altitude_m: float) -> float:
    """rho / rho0 in the ISA troposphere (clamped at the tropopause)."""
    h = min(max(float(altitude_m), 0.0), 11000.0)
    return (1.0 - ISA_LAPSE_K_PER_M * h / ISA_T0_K) ** ISA_EXPONENT


def fall_speed_factor(altitude_m: float) -> float:
    """Foote & du Toit: v / v0 = (rho0 / rho)^0.4."""
    return isa_density_ratio(altitude_m) ** (-FALL_SPEED_DENSITY_EXPONENT)


def number_flux_per_m2_s(lam: float, d_min: float = D_RENDER_MIN_MM, d_max: float = D_MAX_MM,
                         n0: float = rain_model.MP_N0) -> float:
    """int N(D) v(D) dD over [d_min, d_max] for the Atlas law, closed form."""
    lam = float(lam)
    a, b, c = rain_model.ATLAS_A, rain_model.ATLAS_B, rain_model.ATLAS_C

    def piece(k: float) -> float:
        return (math.exp(-k * d_min) - math.exp(-k * d_max)) / k

    return n0 * (a * piece(lam) - b * piece(lam + c))


def drop(index: int, seed: int, lam: float, half: Sequence[float] = BOX_HALF_M,
         factor: float = 1.0) -> Dict[str, Any]:
    """Drop ``index``: its seed position (box axes 0, 1, 2), diameter, width,
    fall speed and phase."""
    p0 = [(2.0 * unit(seed, index, axis) - 1.0) * float(half[axis]) for axis in range(3)]
    diameter = sample_diameter_mm(unit(seed, index, 3), lam)
    return {"index": int(index), "p0_m": p0, "d_mm": diameter,
            "width_mm": presented_width_mm(diameter),
            "v_t_mps": rain_model.terminal_velocity_mps(diameter) * float(factor),
            "phase": unit(seed, index, 4)}


def wrap(value: float, half: float) -> float:
    """Fold into [-half, half)."""
    span = 2.0 * float(half)
    return (float(value) + half) % span - half


def drop_position(p0: Sequence[float], displacement: Sequence[float],
                  camera: Sequence[float], v_t_mps: float, time_s: float,
                  half: Sequence[float] = BOX_HALF_M) -> Tuple[float, float, float]:
    """The drop's world position (metres, east / north / up) -- the module
    docstring's p(t), ``displacement`` the air's horizontal displacement."""
    rel = (float(p0[0]) + float(displacement[0]) - float(camera[0]),
           float(p0[1]) + float(displacement[1]) - float(camera[1]),
           float(p0[2]) - float(v_t_mps) * float(time_s) - float(camera[2]))
    return tuple(float(camera[k]) + wrap(rel[k], half[k]) for k in range(3))


def streak_opacity(diameter_mm: float, speed_mps: float, shutter_s: float,
                   weight: float = 1.0) -> float:
    """Garg & Nayar's coverage: D / (|v| t), times the weight, clamped at 1."""
    sweep = float(speed_mps) * float(shutter_s)
    if sweep <= 0.0:
        return 1.0
    return min(1.0, float(diameter_mm) / 1000.0 / sweep * float(weight))


def splash_position(slot: int, cycle: int,
                    half_side_m: float = SPLASH_RADIUS_M) -> Tuple[float, float]:
    """Slot ``slot``'s place in its ``cycle``, before the ground wrap
    (assets/shaders/weather/rain_splash_offset.hlsl): h = pcg32(slot * 65536
    + cycle), x from its low 16 bits, y from its high 16, onto [-half, half]."""
    h = pcg32((int(slot) * 65536 + int(cycle)) & 0xFFFFFFFF)
    x = ((h & 0xFFFF) / 65535.0 * 2.0 - 1.0) * float(half_side_m)
    y = ((h >> 16) / 65535.0 * 2.0 - 1.0) * float(half_side_m)
    return x, y


def windshield(rate_density_per_m3: float, airspeed_mps: float) -> Dict[str, Any]:
    """The glass: drops impinging per m^2 per s, and the run-off speed."""
    v = max(float(airspeed_mps), 0.0)
    impinge = float(rate_density_per_m3) * v * WINDSHIELD_COS * GLASS_AREA_M2
    runoff = RUNOFF_GAIN * (v - V_SHED_MPS) if v > V_SHED_MPS else 0.0
    return {"impinge_per_m2_s": round(impinge, 4), "runoff_mps": round(runoff, 4),
            "v_shed_mps": V_SHED_MPS, "runoff_gain": RUNOFF_GAIN,
            "glass_cos": WINDSHIELD_COS, "airspeed_mps": round(v, 4),
            "basis": "impingement n_r |V| cos(theta); run-off RUNOFF_GAIN (V - V_SHED) above "
                     "V_SHED -- the two constants STATED, not measured"}


def splash(lam: float, rate_scale: float = 1.0) -> Dict[str, Any]:
    """The splash slots: the ground flux, the drawn rate and its weight."""
    flux = number_flux_per_m2_s(lam) * float(rate_scale)
    per_s = flux * (2.0 * SPLASH_RADIUS_M) ** 2
    active = per_s * SPLASH_LIFETIME_S
    slots = int(min(SPLASH_BUDGET, max(1, math.ceil(active))))
    # A slot is busy for one lifetime per relight, so the slots draw at most
    # slots / lifetime splashes a second; each relights once per period.
    drawn_per_s = min(per_s, slots / SPLASH_LIFETIME_S)
    period = slots / drawn_per_s if drawn_per_s > 0.0 else 0.0
    weight = per_s / drawn_per_s if drawn_per_s > 0.0 else 1.0
    return {"flux_per_m2_s": round(flux, 4), "radius_m": SPLASH_RADIUS_M,
            "per_s": round(per_s, 4), "lifetime_s": SPLASH_LIFETIME_S, "slots": slots,
            "period_s": round(period, 6), "weight": round(weight, 6),
            "max_agl_m": SPLASH_MAX_AGL_M, "hash": "pcg32(slot * 65536 + cycle)"}


def ambient_fraction(rate_mmh: float, ambient_rate_mmh: Optional[float]) -> float:
    """The share of the drawn drops a host shows OUTSIDE a storm's shaft:
    n_r(ambient) / n_r(rate), each at its own fitted Lambda (0 with no
    ambient rain). The drops keep the shaft's sizes -- stated."""
    if ambient_rate_mmh is None or float(ambient_rate_mmh) <= 0.0:
        return 0.0
    full = truncated_number_density(rain_model.fitted_lambda(rate_mmh))
    part = truncated_number_density(rain_model.fitted_lambda(ambient_rate_mmh))
    return min(1.0, part / full)


def card_block(rate_mmh: float, rate_source: str, seed: int, altitude_m: float,
               wind_enu_mps: Sequence[float], airspeed_mps: float,
               ambient_rate_mmh: Optional[float] = None) -> Dict[str, Any]:
    """``weather.rain`` in CARD_KEYS order. ``rate_mmh`` is the heaviest
    rain a host draws (a storm's shaft, or the stated rate); a host shows
    ``ambient_fraction`` of the drops where only ``ambient_rate_mmh``
    falls (outside the shaft) -- 1 when the two are the same rain."""
    numbers = rain_model.rain(rate_mmh)
    # The card's own rounded numbers drive the selftest, so a host reading
    # them draws exactly the drops the selftest lists.
    lam = round(numbers["lambda_fitted_per_mm"], 9)
    ambient = rate_mmh if ambient_rate_mmh is None and rate_source == "stated" else ambient_rate_mmh
    factor = round(fall_speed_factor(altitude_m), 9)
    density = truncated_number_density(lam)
    volume = 8.0 * BOX_HALF_M[0] * BOX_HALF_M[1] * BOX_HALF_M[2]
    expected = density * volume
    particles = int(min(PARTICLE_BUDGET, max(1, round(expected))))
    seed64 = int(seed) & SEED_MASK
    selftest = [drop(i, seed64, lam, factor=factor) for i in range(SELFTEST_DROPS)]
    for entry in selftest:
        for key in ("d_mm", "width_mm", "v_t_mps", "phase"):
            entry[key] = round(entry[key], 12)
        entry["p0_m"] = [round(v, 12) for v in entry["p0_m"]]
    return {
        "rate_mmh": round(float(rate_mmh), 4),
        "rate_source": str(rate_source),
        "lambda": lam,
        "n0": rain_model.MP_N0,
        "d_render_min_mm": D_RENDER_MIN_MM,
        "d_max_mm": D_MAX_MM,
        "box_half_m": list(BOX_HALF_M),
        "density_drawn_per_m3": round(density, 6),
        "expected_in_box": round(expected, 3),
        "particles": particles,
        "weight": round(max(1.0, expected / particles), 6),
        "ambient_rate_mmh": None if ambient is None else round(float(ambient), 4),
        "ambient_fraction": round(ambient_fraction(rate_mmh, ambient), 9),
        "fall_speed_factor": factor,
        "wind_enu_mps": [round(float(v), 6) for v in wind_enu_mps],
        "seed": seed64,
        "splash": splash(lam),
        "windshield": windshield(truncated_number_density(lam, d_min=rain_model.ATLAS_ZERO_MM),
                                 airspeed_mps),
        "selftest": selftest,
    }


def lambda_of(block: Dict[str, Any]) -> float:
    return float(block["lambda"])


def drops(block: Dict[str, Any], count: Optional[int] = None) -> List[Dict[str, Any]]:
    """The first ``count`` drops a card's block draws (all when None)."""
    n = int(block["particles"]) if count is None else int(count)
    return [drop(i, int(block["seed"]), float(block["lambda"]), block["box_half_m"],
                 float(block["fall_speed_factor"])) for i in range(n)]
