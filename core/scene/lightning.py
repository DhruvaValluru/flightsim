"""Lightning: when the flashes come, what each one looks like, and how much light it gives.

A thunderstorm's lightning is drawn from the published statistics of real
flashes, once, in Python, with the run's seed -- the schedule, every
stroke's time and the channel's whole geometry go onto the card and the
host draws exactly that (Gate 10-R: a replay strikes the same bolts at the
same instants). Nothing here couples to the equations of motion; lightning
is a VISUAL of the storm the physics already flies (the microburst, gust
front and turbulence composition of core/scenario/runner.py).

The schedule. Flashes arrive as a Poisson process at FLASH_RATE_PER_MIN
(an active cell: one to ten a minute [unverified here]). Each is
cloud-to-ground with probability 1 / (1 + Z), Z = IC_CG_RATIO
(Prentice & Mackerras 1977: Z ~ 2-5 at mid-latitudes [unverified here]),
else intra-cloud.

A cloud-to-ground flash (Rakov & Uman 2003 [unverified here]):

* a STEPPED LEADER of LEADER_S_RANGE descends the channel -- drawn as the
  channel growing from the cloud to the ground, faint, with its branches;
* the FIRST RETURN STROKE when it touches down, then subsequent strokes
  down the same main channel (no branches): the count geometric with mean
  STROKES_MEAN (about a fifth of flashes single-stroke), the intervals
  log-normal, geometric mean INTERSTROKE_GM_S;
* with probability CONTINUING_P a continuing current after the last
  stroke, log-normal duration about CONTINUING_GM_S -- the long, steady
  glow that makes a bolt "hang" in a video.

Each stroke's optical power per metre of channel is

    P(t) = Pp [k (e^-(t/tau_f) - e^-(t/tau_r)) + g e^-(t/tau_g)],  t >= 0

-- a microsecond rise, a tens-of-microseconds fall (Krider, Dawson & Uman
1968 [unverified here]) and a millisecond after-glow of the cooling
channel; k normalises the double exponential to peak 1. A frame does not
see P(t): it sees its MEAN over the shutter, which this module computes in
closed form (:func:`window_power`) -- a 1/500 s exposure that misses a
stroke shows no bolt, exactly as a camera does.

The channel. A tortuous random walk from the charge region to the strike
point: segments of SEGMENT_M, each turned from the last by a random angle
of TORTUOSITY_DEG at Hill's 8 m scale, grown as sqrt(L / 8 m) for a longer
segment (Hill 1968: mean absolute change ~16 deg [unverified here]),
steered toward the strike point harder as it nears the ground, never
upward, and corrected linearly along its arc length so it lands EXACTLY on
the strike point. Branches leave the main channel with BRANCH_P per node
and die in the air; they glow with the leader and the first stroke only.

Light. The luminous power per metre is LUMINOUS_EFFICACY_LM_PER_W times
the optical power. A host draws the channel as a line source: a channel
of luminous power Phi' (lm/m) seen across width w has luminance
Phi' / (pi^2 w) -- the width cancels where the host widens a sub-pixel
channel to a pixel (energy conserved). The flash's light on the scene is
a point source at the channel's centroid of intensity Phi' L / (4 pi) cd.

Not claimed: the leader's step-by-step stepping (drawn as a smooth descent),
dart leaders, M-components, upward flashes, the anvil "spider" crawlers;
the IC channel is drawn only as the cloud's glow; the absolute optical power
is the literature's order of magnitude, measured by no frame here.
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: The schedule.
FLASH_RATE_PER_MIN = 6.0
IC_CG_RATIO = 3.0
MAX_FLASHES = 200
#: Cloud-to-ground strokes.
STROKES_MEAN = 4.0
STROKES_MAX = 20
INTERSTROKE_GM_S = 0.060
INTERSTROKE_SIGMA_LN = 0.7
LEADER_S_RANGE = (0.015, 0.035)
CONTINUING_P = 0.3
CONTINUING_GM_S = 0.100
CONTINUING_SIGMA_LN = 0.7
#: Intra-cloud pulses.
IC_PULSES = (1, 4)
IC_INTERVAL_S = (0.010, 0.120)
#: The light curve (W/m, s).
FIRST_STROKE_PEAK_W_PER_M = 6.0e5
SUBSEQUENT_STROKE_FRACTION = 0.5
IC_PEAK_W_PER_M = 1.5e5
RISE_S = 2.0e-6
FALL_S = 6.0e-5
GLOW_FRACTION = 0.02
GLOW_S = 1.0e-3
CONTINUING_W_PER_M = 3.0e3
LEADER_W_PER_M = 6.0e2
BRANCH_STROKE_SHARE = 0.25
LUMINOUS_EFFICACY_LM_PER_W = 80.0
#: The channel.
SEGMENT_M = 25.0
TORTUOSITY_DEG = 16.0
HILL_SCALE_M = 8.0
BRANCH_P = 0.06
BRANCH_SEGMENTS = (6, 30)
BRANCH_SPREAD_DEG = (25.0, 55.0)
#: Where a CG channel starts above the cloud base (m) and how far from the
#: tower axis it may strike, in tower radii.
START_ABOVE_BASE_M = (500.0, 2500.0)
STRIKE_RADIUS_TOWERS = 1.2
COORD_DECIMALS = 1

#: The card's ``weather.lightning`` keys, in their fixed order.
CARD_KEYS = ("rate_per_min", "ic_cg_ratio", "seed", "light_curve", "flashes", "selftest")
FLASH_KEYS = ("index", "t_s", "kind", "leader", "strokes", "continuing", "channels",
              "centroid_enu_m", "length_m")

REFERENCES = (
    "Rakov, V. A. & Uman, M. A. 2003, Lightning: Physics and Effects (CUP) [unverified here]",
    "Krider, E. P., Dawson, G. A. & Uman, M. A. 1968, J. Geophys. Res. 73, 3335 "
    "(peak optical power of return strokes) [unverified here]",
    "Hill, R. D. 1968, J. Geophys. Res. 73, 1897 (channel tortuosity) [unverified here]",
    "Prentice, S. A. & Mackerras, D. 1977, J. Appl. Meteor. 16, 545 (IC:CG ratio) "
    "[unverified here]",
)

NOT_CLAIMED = (
    "the stepped leader is drawn as a smooth descent, not step by step",
    "no dart leaders, M-components, upward flashes or anvil crawlers",
    "intra-cloud flashes are drawn only as the cloud's glow",
    "the optical power is the literature's order of magnitude, not a measured frame",
)


def _peak_norm() -> float:
    """k: 1 / max(e^-(t/tau_f) - e^-(t/tau_r))."""
    t_star = math.log(FALL_S / RISE_S) * FALL_S * RISE_S / (FALL_S - RISE_S)
    return 1.0 / (math.exp(-t_star / FALL_S) - math.exp(-t_star / RISE_S))


PEAK_NORM = _peak_norm()


def _exp_integral(tau: float, a: float, b: float) -> float:
    """int_a^b e^-(t/tau) dt for 0 <= a <= b."""
    return tau * (math.exp(-a / tau) - math.exp(-b / tau))


def stroke_energy(peak: float, a: float, b: float) -> float:
    """int_a^b P(t) dt (J/m), times relative to the stroke's onset (P = 0 before)."""
    a = max(0.0, float(a))
    b = max(0.0, float(b))
    if b <= a:
        return 0.0
    return float(peak) * (PEAK_NORM * (_exp_integral(FALL_S, a, b) - _exp_integral(RISE_S, a, b))
                          + GLOW_FRACTION * _exp_integral(GLOW_S, a, b))


def stroke_total_energy(peak: float) -> float:
    """The whole stroke's optical energy per metre."""
    return float(peak) * (PEAK_NORM * (FALL_S - RISE_S) + GLOW_FRACTION * GLOW_S)


def _overlap(a: float, b: float, lo: float, hi: float) -> float:
    return max(0.0, min(b, hi) - max(a, lo))


def window_power(flash: Dict[str, Any], a: float, b: float) -> Dict[str, float]:
    """The flash's MEAN optical power per metre (W/m) over the window [a, b]
    of run time -- what an exposure from a to b integrates -- for the main
    channel and for its branches, and the leader's progress (0..1) at b."""
    a = float(a)
    b = float(b)
    span = b - a
    if span <= 0.0:
        raise ValueError(f"an exposure window must have positive length, not [{a}, {b}]")
    main = 0.0
    branch = 0.0
    for k, stroke in enumerate(flash["strokes"]):
        t0 = float(stroke["t_s"])
        energy = stroke_energy(float(stroke["peak_w_per_m"]), a - t0, b - t0)
        main += energy
        if k == 0:
            branch += BRANCH_STROKE_SHARE * energy
    continuing = flash.get("continuing")
    if continuing:
        t0 = float(continuing["t_s"])
        end = t0 + float(continuing["duration_s"])
        main += float(continuing["w_per_m"]) * _overlap(a, b, t0, end)
    progress = 0.0
    leader = flash.get("leader")
    if leader:
        t0, t1 = float(leader[0]), float(leader[1])
        lit = LEADER_W_PER_M * _overlap(a, b, t0, t1)
        main += lit
        branch += lit
        progress = min(1.0, max(0.0, (b - t0) / (t1 - t0)))
    else:
        progress = 1.0 if b >= float(flash["t_s"]) else 0.0
    return {"main_w_per_m": main / span, "branch_w_per_m": branch / span,
            "leader_progress": progress}


def intensity_cd(flash: Dict[str, Any], power: Dict[str, float]) -> float:
    """The flash as a point source: K (P_main L_main + P_branch L_branch) / (4 pi)."""
    main_len = sum(c["length_m"] for c in flash["channels"] if c["kind"] == "main")
    branch_len = sum(c["length_m"] for c in flash["channels"] if c["kind"] == "branch")
    lumens = LUMINOUS_EFFICACY_LM_PER_W * (power["main_w_per_m"] * main_len
                                           + power["branch_w_per_m"] * branch_len)
    return lumens / (4.0 * math.pi)


def line_luminance(power_w_per_m: float, width_m: float) -> float:
    """A channel's luminance (cd/m^2) drawn across ``width_m``: K P' / (pi^2 w)."""
    return LUMINOUS_EFFICACY_LM_PER_W * float(power_w_per_m) / (math.pi ** 2 * float(width_m))


# -- geometry --------------------------------------------------------------

Vec = Tuple[float, float, float]


def _norm(v: Sequence[float]) -> Vec:
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


def _perturb(rng: random.Random, d: Vec, sigma_rad: float) -> Vec:
    """Turn d by a Gaussian angle about a uniformly random perpendicular."""
    helper = (1.0, 0.0, 0.0) if abs(d[0]) < 0.9 else (0.0, 1.0, 0.0)
    p = _norm((d[1] * helper[2] - d[2] * helper[1], d[2] * helper[0] - d[0] * helper[2],
               d[0] * helper[1] - d[1] * helper[0]))
    q = (d[1] * p[2] - d[2] * p[1], d[2] * p[0] - d[0] * p[2], d[0] * p[1] - d[1] * p[0])
    phi = rng.uniform(0.0, 2.0 * math.pi)
    axis = tuple(math.cos(phi) * p[k] + math.sin(phi) * q[k] for k in range(3))
    angle = rng.gauss(0.0, sigma_rad)
    return _norm((math.cos(angle) * d[0] + math.sin(angle) * axis[0],
                  math.cos(angle) * d[1] + math.sin(angle) * axis[1],
                  math.cos(angle) * d[2] + math.sin(angle) * axis[2]))


def _sigma(segment_m: float) -> float:
    return math.radians(TORTUOSITY_DEG) * math.sqrt(segment_m / HILL_SCALE_M)


def _length(points: Sequence[Sequence[float]]) -> float:
    return sum(math.dist(points[i], points[i + 1]) for i in range(len(points) - 1))


def _round(points: Sequence[Sequence[float]]) -> List[List[float]]:
    return [[round(float(c), COORD_DECIMALS) for c in p] for p in points]


def cg_main_channel(rng: random.Random, start: Vec, strike: Tuple[float, float]) -> List[Vec]:
    """The main channel from ``start`` (east, north, up) to the ground at ``strike``."""
    points: List[Vec] = [start]
    target = (strike[0], strike[1], 0.0)
    d = _norm((target[0] - start[0], target[1] - start[1], target[2] - start[2]))
    height = start[2]
    guard = int(8.0 * height / SEGMENT_M) + 50
    while points[-1][2] > 0.0 and guard > 0:
        guard -= 1
        p = points[-1]
        to_target = _norm((target[0] - p[0], target[1] - p[1], target[2] - p[2]))
        fraction_down = 1.0 - max(0.0, p[2]) / height
        pull = 0.25 + 0.75 * fraction_down ** 2
        d = _perturb(rng, d, _sigma(SEGMENT_M))
        d = _norm((d[0] + pull * to_target[0], d[1] + pull * to_target[1],
                   d[2] + pull * to_target[2]))
        if d[2] > -0.2:
            d = _norm((d[0], d[1], -0.2))
        step = SEGMENT_M * rng.uniform(0.6, 1.4)
        q = (p[0] + step * d[0], p[1] + step * d[1], p[2] + step * d[2])
        if q[2] <= 0.0:
            t = p[2] / (p[2] - q[2])
            q = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), 0.0)
        points.append(q)
    # Land exactly on the strike point: the horizontal miss spread linearly
    # along the arc length (the top stays where it started).
    miss = (strike[0] - points[-1][0], strike[1] - points[-1][1])
    total = _length(points)
    run = 0.0
    out: List[Vec] = [points[0]]
    for i in range(1, len(points)):
        run += math.dist(points[i - 1], points[i])
        f = run / total if total > 0.0 else 1.0
        out.append((points[i][0] + f * miss[0], points[i][1] + f * miss[1], points[i][2]))
    out[-1] = (strike[0], strike[1], 0.0)
    return out


def branch_channel(rng: random.Random, origin: Vec, along: Vec) -> List[Vec]:
    """A branch leaving the main channel at ``origin``, dying in the air."""
    d = _perturb(rng, along, math.radians(rng.uniform(*BRANCH_SPREAD_DEG)))
    if d[2] > -0.1:
        d = _norm((d[0], d[1], -0.1))
    points: List[Vec] = [origin]
    for _ in range(rng.randint(*BRANCH_SEGMENTS)):
        p = points[-1]
        d = _perturb(rng, d, _sigma(SEGMENT_M))
        if d[2] > -0.1:
            d = _norm((d[0], d[1], -0.1))
        step = SEGMENT_M * rng.uniform(0.5, 1.2)
        q = (p[0] + step * d[0], p[1] + step * d[1], p[2] + step * d[2])
        if q[2] < 50.0:
            break
        points.append(q)
    return points


def ic_channel(rng: random.Random, start: Vec, reach_m: float) -> List[Vec]:
    """An intra-cloud channel: a mostly horizontal walk inside the cloud."""
    heading = rng.uniform(0.0, 2.0 * math.pi)
    d = _norm((math.cos(heading), math.sin(heading), rng.uniform(-0.15, 0.15)))
    points: List[Vec] = [start]
    run = 0.0
    while run < reach_m:
        p = points[-1]
        d = _perturb(rng, d, _sigma(SEGMENT_M))
        d = _norm((d[0], d[1], 0.3 * d[2]))
        step = SEGMENT_M * 4.0
        points.append((p[0] + step * d[0], p[1] + step * d[1], p[2] + step * d[2]))
        run += step
    return points


def _centroid(channels: Sequence[Dict[str, Any]]) -> List[float]:
    """The length-weighted centroid of the channels' segments."""
    total = 0.0
    acc = [0.0, 0.0, 0.0]
    for channel in channels:
        pts = channel["points"]
        for i in range(len(pts) - 1):
            seg = math.dist(pts[i], pts[i + 1])
            total += seg
            for k in range(3):
                acc[k] += seg * 0.5 * (pts[i][k] + pts[i + 1][k])
    return [round(c / total, COORD_DECIMALS) for c in acc] if total > 0.0 else [0.0, 0.0, 0.0]


def _geometric(rng: random.Random, mean: float, cap: int) -> int:
    p = 1.0 / mean
    n = 1
    while rng.random() > p and n < cap:
        n += 1
    return n


def make_flash(rng: random.Random, index: int, t_s: float, kind: str,
               cell: Dict[str, Any]) -> Dict[str, Any]:
    """One flash (FLASH_KEYS order) in the cell's local frame."""
    tower = float(cell["tower_radius_m"])
    base = float(cell["base_m"])
    channels: List[Dict[str, Any]] = []
    strokes: List[Dict[str, Any]] = []
    leader = None
    continuing = None
    if kind == "cg":
        r0 = 0.6 * tower * math.sqrt(rng.random())
        a0 = rng.uniform(0.0, 2.0 * math.pi)
        start = (r0 * math.cos(a0), r0 * math.sin(a0), base + rng.uniform(*START_ABOVE_BASE_M))
        r1 = STRIKE_RADIUS_TOWERS * tower * math.sqrt(rng.random())
        a1 = rng.uniform(0.0, 2.0 * math.pi)
        strike = (r1 * math.cos(a1), r1 * math.sin(a1))
        main = cg_main_channel(rng, start, strike)
        channels.append({"kind": "main", "points": main})
        stop = int(0.9 * len(main))
        for i in range(1, max(1, stop)):
            if rng.random() < BRANCH_P:
                along = _norm((main[i][0] - main[i - 1][0], main[i][1] - main[i - 1][1],
                               main[i][2] - main[i - 1][2]))
                branch = branch_channel(rng, main[i], along)
                if len(branch) > 2:
                    channels.append({"kind": "branch", "points": branch})
        leader_s = rng.uniform(*LEADER_S_RANGE)
        leader = [round(t_s, 6), round(t_s + leader_s, 6)]
        t = t_s + leader_s
        count = _geometric(rng, STROKES_MEAN, STROKES_MAX)
        for k in range(count):
            peak = FIRST_STROKE_PEAK_W_PER_M * (1.0 if k == 0 else SUBSEQUENT_STROKE_FRACTION
                                                * rng.uniform(0.5, 1.5))
            strokes.append({"t_s": round(t, 6), "peak_w_per_m": round(peak, 3)})
            if k + 1 < count:
                t += math.exp(math.log(INTERSTROKE_GM_S) + rng.gauss(0.0, INTERSTROKE_SIGMA_LN))
        if rng.random() < CONTINUING_P:
            duration = math.exp(math.log(CONTINUING_GM_S) + rng.gauss(0.0, CONTINUING_SIGMA_LN))
            continuing = {"t_s": round(t + 1.0e-4, 6), "duration_s": round(duration, 6),
                          "w_per_m": CONTINUING_W_PER_M}
    else:
        r0 = tower * math.sqrt(rng.random())
        a0 = rng.uniform(0.0, 2.0 * math.pi)
        top = float(cell["anvil_bottom_m"])
        height = rng.uniform(base + 2000.0, max(base + 2500.0, top))
        start = (r0 * math.cos(a0), r0 * math.sin(a0), height)
        reach = rng.uniform(2000.0, 8000.0)
        channels.append({"kind": "main", "points": ic_channel(rng, start, reach)})
        t = t_s
        for k in range(rng.randint(*IC_PULSES)):
            strokes.append({"t_s": round(t, 6), "peak_w_per_m": round(IC_PEAK_W_PER_M
                                                                     * rng.uniform(0.5, 1.5), 3)})
            t += rng.uniform(*IC_INTERVAL_S)
    for channel in channels:
        channel["points"] = _round(channel["points"])
        channel["length_m"] = round(_length(channel["points"]), 3)
    return {"index": int(index), "t_s": round(t_s, 6), "kind": kind, "leader": leader,
            "strokes": strokes, "continuing": continuing,
            "channels": [{"kind": c["kind"], "length_m": c["length_m"], "points": c["points"]}
                         for c in channels],
            "centroid_enu_m": _centroid(channels),
            "length_m": round(sum(c["length_m"] for c in channels), 3)}


def schedule(seed: int, duration_s: float, rate_per_min: float = FLASH_RATE_PER_MIN,
             ic_cg_ratio: float = IC_CG_RATIO) -> List[Tuple[float, str]]:
    """(time, kind) of every flash in [0, duration_s): a Poisson process."""
    rng = random.Random(int(seed) * 1_000_003 + 17)
    rate = float(rate_per_min) / 60.0
    p_cg = 1.0 / (1.0 + float(ic_cg_ratio))
    out: List[Tuple[float, str]] = []
    t = rng.expovariate(rate)
    while t < float(duration_s) and len(out) < MAX_FLASHES:
        out.append((t, "cg" if rng.random() < p_cg else "ic"))
        t += rng.expovariate(rate)
    return out


def flashes(seed: int, duration_s: float, cell: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every flash of the run, each from its own generator (seed, index)."""
    out = []
    for index, (t_s, kind) in enumerate(schedule(seed, duration_s)):
        rng = random.Random((int(seed) * 7919 + index) * 104_729 + 3)
        out.append(make_flash(rng, index, t_s, kind, cell))
    return out


def light_curve_block() -> Dict[str, Any]:
    return {"rise_s": RISE_S, "fall_s": FALL_S, "peak_norm": PEAK_NORM,
            "glow_fraction": GLOW_FRACTION, "glow_s": GLOW_S,
            "leader_w_per_m": LEADER_W_PER_M, "branch_stroke_share": BRANCH_STROKE_SHARE,
            "luminous_efficacy_lm_per_w": LUMINOUS_EFFICACY_LM_PER_W}


def selftest(flash_list: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """window_power at a few exposures of the first cloud-to-ground flash
    (the first flash when there is none): the host's port is checked
    against these."""
    if not flash_list:
        return []
    flash = next((f for f in flash_list if f["kind"] == "cg"), flash_list[0])
    t0 = float(flash["strokes"][0]["t_s"])
    out = []
    for a, b in ((t0 - 0.001, t0 + 0.001), (t0 - 0.0005, t0 + 0.0015), (t0 + 0.0001, t0 + 0.0021),
                 (float(flash["t_s"]), t0), (t0 - 1.0 / 60.0, t0 + 1.0 / 60.0)):
        if b <= a:
            continue
        power = window_power(flash, a, b)
        out.append({"flash": int(flash["index"]), "a_s": a, "b_s": b,
                    "main_w_per_m": power["main_w_per_m"],
                    "branch_w_per_m": power["branch_w_per_m"],
                    "leader_progress": power["leader_progress"],
                    "intensity_cd": intensity_cd(flash, power)})
    return out


def card_block(seed: int, duration_s: float, cell: Dict[str, Any]) -> Dict[str, Any]:
    """``weather.lightning`` in CARD_KEYS order."""
    flash_list = flashes(seed, duration_s, cell)
    return {"rate_per_min": FLASH_RATE_PER_MIN, "ic_cg_ratio": IC_CG_RATIO, "seed": int(seed),
            "light_curve": light_curve_block(), "flashes": flash_list,
            "selftest": selftest(flash_list)}


def flash_at(block: Dict[str, Any], index: int) -> Optional[Dict[str, Any]]:
    for flash in block["flashes"]:
        if int(flash["index"]) == int(index):
            return flash
    return None
