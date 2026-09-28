"""Von Karman continuous turbulence beside JSBSim's Dryden (gap P2 of
docs/PHASE3_GAP_ANALYSIS.md; blueprint section 1, corrections 5 and 9;
work item P6).

Why a Python provider and not a JSBSim type
--------------------------------------------
The installed JSBSim 1.2.4 has no von Karman spectrum: ``FGWinds.h``
enumerates ``ttNone, ttStandard, ttCulp, ttMilspec, ttTustin`` (L183),
the last two Dryden. Its ``atmosphere/turb-*-fps`` channel cannot be
driven from outside (``Run`` overwrites it every step, FGWinds.cpp
L145-L150: a 10 fps write reads 0 after one step, measured), but its
``atmosphere/gust-*-fps`` channel PERSISTS until written again and is
summed into the total wind beside the Dryden process (L157; a 7 fps
write reads 7.0 after 11 steps and the total wind is wind + gust + turb
to the bit, measured). So the von Karman field is realised here, in
Python, and delivered through the gust channel by the environment stack
every step, zero included (docs/JSBSIM_CORRECTIONS.md 16-17).

The model
---------
Spectra (MIL-F-8785C 3.7.2.1, the von Karman form, as the blueprint
transcribes them [unverified here: the specification is not reachable
from this container]; ``Omega`` is spatial frequency in rad/length):

    Phi_u(Omega) = sigma_u^2 (2 L_u / pi) / [1 + (1.339 L_u Omega)^2]^(5/6)
    Phi_w(Omega) = sigma_w^2 (L_w / pi) [1 + (8/3)(1.339 L_w Omega)^2]
                                        / [1 + (1.339 L_w Omega)^2]^(11/6)
    Phi_v(Omega) = the same form as Phi_w with L_v, sigma_v

Normalised so that ``integral_0^inf Phi dOmega = sigma^2`` (checked
numerically in tests/test_von_karman.py: 1.0000 for both forms). The
spectral CONVENTION is the MIL-F-8785C one (scale length L in the
formula as written above, one-sided in Omega); MIL-HDBK-1797 rewrites
the same spectra with 2L and halves its scale lengths accordingly. The
model block names the convention so a reader with the other handbook
does not double a length.

Scale lengths: above 2000 ft ``L_u = 2 L_v = 2 L_w = 2500 ft`` (the
MIL-F-8785C convention as the blueprint's correction 5 states it
[unverified here]); at or below 1000 ft the low-altitude relations
``L_w = h``, ``L_u = L_v = h / (0.177 + 0.000823 h)^1.2`` (MIL-F-8785C
3.7.2.1, the form FGWinds.cpp L277-L278 transcribes for its Dryden
scales, with h in ft clipped at 10 ft as L273-L274 does); between 1000
and 2000 ft a linear interpolation of each length between its 1000-ft
value and its high-altitude value (FGWinds L281-L283 interpolates its
Dryden scales the same way; a stated choice here, the specification's
figure for that band is not readable from this container).

Intensities: the SAME sigma ladder as FGWinds.cpp L276-L288 (fetched
v1.2.4 source, read line by line): at or below 1000 ft ``sigma_w = 0.1
W20`` (L279) and ``sigma_u = sigma_v = sigma_w / (0.177 + 0.000823 h)^0.4``
(L280, MIL-F-8785C Fig. 11); above 2000 ft ``sigma_u = sigma_v = sigma_w
= POE(index, h)`` from the Fig. 7 probability-of-exceedance table
(L288; the table is FGWinds.cpp L95-L107, rows 1..7, columns 500..80000
ft, transcribed below); between 1000 and 2000 ft ``sigma_u = sigma_w =
0.1 W20 + (h - 1000)/1000 (POE(index, h) - 0.1 W20)`` (L284-L285).
FGWinds enters the ladder with the altitude ABOVE SEA LEVEL (``Run``
passes ``in.AltitudeASL``, L145; MIL-F-8785C's h is height above
ground); this module takes the same altitude so the two spectra are
compared at ONE sigma and says so (over this branch's flat-slab scenes
the difference is the spec's terrain elevation).

Rotational gust: ``sigma_p = 1.9 sigma_w / sqrt(L_w b)``, ``L_p =
sqrt(L_w b) / 2.6`` (Yeager, NASA CR-1998-206937 eqs. 8 and 10 as
FGWinds.cpp L292-L295 transcribes them [the report is unverified here]),
realised with the first-order (Dryden-form) spectrum Yeager's filter
has, ``Phi_p = sigma_p^2 (2 L_p / pi) / (1 + (L_p Omega)^2)``, with its
own phases. q_g and r_g are NOT delivered (no property receives them;
said so in every record).

The realisation (Shinozuka and Jan, J. Sound Vib. 25(1), 1972 [unverified
here]): a sum of N cosines with random phases. N = 256 target
frequencies, log-spaced from the table's fundamental ``Omega_0 = 2 pi /
X`` (X = the frozen field's length, TAS x the table's span) to just
below the spatial Nyquist ``pi / (TAS dt)``, each SNAPPED to the nearest
harmonic ``k Omega_0`` so every component completes whole cycles over
the table -- the sample mean is then exactly 0 and the sample variance
exactly ``sum A_k^2 / 2`` (coinciding harmonics merge; the count after
merging is recorded). Each amplitude is ``A_k = sqrt(2 E_k)`` with E_k
the spectrum's energy integrated (Simpson, 32 panels) over the bin
between the neighbouring harmonics' midpoints; the FIRST bin starts at
Omega = 0, so the spectrum's energy below the fundamental rides on the
lowest component (stated: the field has no wavelength longer than the
table) and only the energy above the last bin is lost (recorded as
``truncated_fraction`` per component, measured 0.2 % for u and 0.4 %
for w at the c172p's condition). Phases are ``uniform(0, 2 pi)`` from
``numpy.random.default_rng(SeedSequence(seed, spawn_key=(stable_hash
("von_karman"),)))`` -- the spec's seed through the named stream
``von_karman`` (``core.experiments.seeds.stable_hash``, SHA-256 based,
the same in every process), four rows (u, v, w, p) of N draws, so a
different seed gives a different table and the same seed the same
table to the bit.

The field is FROZEN and convected at the trim true airspeed along the
trim heading (Taylor's hypothesis, stated): row i of the table is the
field at ``x_i = TAS x i dt``; ``u`` is the air velocity along the
heading (positive = along it), ``v`` to its right, ``w`` down (NED
sign), and the stack rotates (u, v) into north/east by the heading the
table was built with. The table is written to the run card as
``%.17g`` strings so both hosts apply the same doubles.

NOT claimed: that the aircraft's motion off the initial heading is
followed (the field is frozen in the NED frame with u along the trim
heading); any time evolution of the field; q_g and r_g; the p_g
spectrum of MIL-F-8785C itself (Yeager's first-order form is used, as
FGWinds does); the specification's own numbers beyond what FGWinds
transcribes (marked [unverified here] above); anything beyond the
table's span (a step past its last row is delivered as zero and
counted); the engine side (the card block is pinned; nothing applies it
here).
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..experiments.seeds import stable_hash
from ..fdm import units as u
from ..records import AppliedVariable, JsbsimWrite, Model, NullTest, Readback
from .base import GustProvider, OwnShipState, Term, WindNED
from .turbulence import POE_SIGMA_W_FPS, TARGET_SIGMA_W_FPS, W20_KT, poe_index_for

#: The named seed stream: the spec's seed is folded through it and no
#: other subsystem's sequence moves (core/experiments/seeds.py's scheme).
SEED_STREAM = "von_karman"
#: Shinozuka-Jan components (target count before harmonics merge).
N_FREQUENCIES = 256
#: The von Karman spectral constant (MIL-F-8785C 3.7.2.1).
VK_CONSTANT = 1.339
#: The ladder's altitude bands, ft (FGWinds.cpp L276, L281, L286).
LOW_ALTITUDE_FT = 1000.0
HIGH_ALTITUDE_FT = 2000.0
#: The height the ladder is clipped at (FGWinds.cpp L273-L274).
MIN_HEIGHT_FT = 10.0
#: High-altitude scale lengths: L_u = 2 L_v = 2 L_w = 2500 ft (MIL-F-8785C
#: convention, blueprint correction 5 [unverified here]).
L_U_HIGH_FT = 2500.0
L_VW_HIGH_FT = L_U_HIGH_FT / 2.0
#: Yeager (NASA CR-1998-206937) eqs. 8 and 10 as FGWinds.cpp L292-L295 has them.
SIGMA_P_FACTOR = 1.9
L_P_DIVISOR = 2.6
#: The Fig. 7 probability-of-exceedance table, sigma in ft/s: rows = curve
#: index 1..7, columns = altitude ft (FGWinds.cpp L95-L107, "this is Figure
#: 7 from p. 49 of MIL-F-8785C"; transcribed number for number).
POE_ALTITUDES_FT = (500.0, 1750.0, 3750.0, 7500.0, 15000.0, 25000.0, 35000.0,
                    45000.0, 55000.0, 65000.0, 75000.0, 80000.0)
POE_TABLE_FPS: Tuple[Tuple[float, ...], ...] = (
    (3.2, 2.2, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    (4.2, 3.6, 3.3, 1.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    (6.6, 6.9, 7.4, 6.7, 4.6, 2.7, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0),
    (8.6, 9.6, 10.6, 10.1, 8.0, 6.6, 5.0, 4.2, 2.7, 0.0, 0.0, 0.0),
    (11.8, 13.0, 16.0, 15.1, 11.6, 9.7, 8.1, 8.2, 7.9, 4.9, 3.2, 2.1),
    (15.6, 17.6, 23.0, 23.6, 22.1, 20.0, 16.0, 15.1, 12.1, 7.9, 6.2, 5.1),
    (18.7, 21.5, 28.4, 30.2, 30.7, 31.0, 25.2, 23.1, 17.5, 10.7, 8.4, 7.2),
)
#: The JSBSim properties the stack writes for a gust provider, in NED order.
GUST_PROPERTIES = ("atmosphere/gust-north-fps", "atmosphere/gust-east-fps",
                   "atmosphere/gust-down-fps")
P_EQUIVALENT_PROPERTY = "gust/p-equivalent-rad_sec"
#: The telemetry columns a von Karman run returns (recorded, not graded).
TELEMETRY_COLUMNS = ("gust_north_mps", "gust_east_mps", "gust_down_mps",
                     "gust_p_equivalent_rad_s")
#: The card block's keys, in the order the host reads them.
CARD_KEYS = ("model", "seed", "sigma", "L", "tas_mps", "dt_s", "rows", "sha256")
#: The %.17g form both hosts write.
ROW_FORMAT = "%.17g"
MODEL_NAME = "von Karman continuous turbulence (MIL-F-8785C spectra, Shinozuka-Jan sum of cosines)"
STANDARD = "MIL-F-8785C 3.7.2.1 von Karman form; sigma ladder as FGWinds.cpp L276-L288 [unverified here]"
REFERENCES = (
    "MIL-F-8785C (1980) 3.7.2.1: the von Karman spectra, scale lengths and "
    "intensities (Fig. 7 exceedance table, Fig. 11) [unverified here: the "
    "specification is not reachable from this container]",
    "JSBSim v1.2.4 src/models/atmosphere/FGWinds.cpp L95-L107 (the Fig. 7 "
    "table), L145 (the ladder entered with AltitudeASL), L273-L295 (the sigma "
    "and scale ladder, sigma_p and L_p) (fetched, read)",
    "Yeager, J. C. (1998) NASA CR-1998-206937, eqs. 8 and 10 (sigma_p, L_p) as "
    "FGWinds transcribes them [unverified here]",
    "Shinozuka, M. and Jan, C.-M. (1972) J. Sound Vib. 25(1), 111-128: the "
    "sum-of-cosines simulation of a process from its spectrum [unverified here]",
    "MIL-HDBK-1797 (1997) App. A: the same spectra in the 2L convention, NOT the "
    "one used here [unverified here]",
)


# -- the ladders, transcribed ---------------------------------------------------

def poe_sigma_fps(index: int, altitude_ft: float) -> float:
    """FGTable::GetValue on the Fig. 7 table: the row of ``index`` (1..7),
    linear in altitude between columns and held at the ends (FGWinds.cpp
    L285, L288). Index 0 is the disabled process: 0."""
    if index <= 0:
        return 0.0
    if not 1 <= index <= 7:
        raise ValueError(f"the exceedance table has rows 1..7, not {index}")
    row = POE_TABLE_FPS[index - 1]
    if altitude_ft <= POE_ALTITUDES_FT[0]:
        return row[0]
    for (h0, s0), (h1, s1) in zip(zip(POE_ALTITUDES_FT, row),
                                  zip(POE_ALTITUDES_FT[1:], row[1:])):
        if altitude_ft <= h1:
            return s0 + (s1 - s0) * (altitude_ft - h0) / (h1 - h0)
    return row[-1]


def sigma_ladder_fps(altitude_ft: float, w20_fps: float,
                     poe_index: int) -> Tuple[float, float, float]:
    """``(sigma_u, sigma_v, sigma_w)`` in ft/s: FGWinds.cpp L273-L288.

    L273-L274 clip h at 10 ft; L276-L280 the low band (sigma_w = 0.1 W20,
    sigma_u = sigma_w / (0.177 + 0.000823 h)^0.4, and FGWinds gives v the
    u value through its filter, sigma_v = sigma_u); L281-L285 the linear
    interpolation to the exceedance table; L286-L288 the table alone.
    """
    h = max(float(altitude_ft), MIN_HEIGHT_FT)
    if h <= LOW_ALTITUDE_FT:
        sigma_w = 0.1 * w20_fps
        sigma_u = sigma_w / (0.177 + 0.000823 * h) ** 0.4
        return sigma_u, sigma_u, sigma_w
    if h <= HIGH_ALTITUDE_FT:
        table = poe_sigma_fps(poe_index, h)
        sigma = 0.1 * w20_fps + (h - LOW_ALTITUDE_FT) / 1000.0 * (table - 0.1 * w20_fps)
        return sigma, sigma, sigma
    sigma = poe_sigma_fps(poe_index, h)
    return sigma, sigma, sigma


def scale_lengths_ft(altitude_ft: float) -> Tuple[float, float, float]:
    """``(L_u, L_v, L_w)`` in ft for the von Karman form: L_u = 2 L_v =
    2 L_w = 2500 ft above 2000 ft; the low-altitude relations at or
    below 1000 ft (L_w = h, L_u = L_v = h/(0.177 + 0.000823 h)^1.2, h
    clipped at 10 ft); linear between (see the module docstring)."""
    h = max(float(altitude_ft), MIN_HEIGHT_FT)
    if h <= LOW_ALTITUDE_FT:
        l_u = h / (0.177 + 0.000823 * h) ** 1.2
        return l_u, l_u, h
    if h <= HIGH_ALTITUDE_FT:
        f = (h - LOW_ALTITUDE_FT) / (HIGH_ALTITUDE_FT - LOW_ALTITUDE_FT)
        l_u_low = LOW_ALTITUDE_FT / (0.177 + 0.000823 * LOW_ALTITUDE_FT) ** 1.2
        l_u = l_u_low + f * (L_U_HIGH_FT - l_u_low)
        l_w = LOW_ALTITUDE_FT + f * (L_VW_HIGH_FT - LOW_ALTITUDE_FT)
        return l_u, l_w, l_w
    return L_U_HIGH_FT, L_VW_HIGH_FT, L_VW_HIGH_FT


def p_gust_parameters(sigma_w: float, l_w: float, span: float) -> Tuple[float, float]:
    """``(sigma_p, L_p)``: Yeager eqs. 8 and 10 as FGWinds.cpp L292-L295
    transcribes them, in any one length unit (sigma_p is then per
    second in that unit's velocity; L_p in that length)."""
    if l_w <= 0.0 or span <= 0.0:
        raise ValueError("L_w and the span are positive lengths")
    root = math.sqrt(l_w * span)
    return SIGMA_P_FACTOR * sigma_w / root, root / L_P_DIVISOR


# -- the spectra ---------------------------------------------------------------------

def phi_u(omega, sigma: float, length: float):
    """MIL-F-8785C von Karman longitudinal spectrum (one-sided in Omega)."""
    x = VK_CONSTANT * length * np.asarray(omega, dtype=float)
    return sigma ** 2 * (2.0 * length / math.pi) / (1.0 + x * x) ** (5.0 / 6.0)


def phi_w(omega, sigma: float, length: float):
    """MIL-F-8785C von Karman vertical spectrum; the lateral one has the
    same form with L_v and sigma_v."""
    x = VK_CONSTANT * length * np.asarray(omega, dtype=float)
    x2 = x * x
    return sigma ** 2 * (length / math.pi) * (1.0 + (8.0 / 3.0) * x2) / (1.0 + x2) ** (11.0 / 6.0)


phi_v = phi_w


def phi_p(omega, sigma_p: float, l_p: float):
    """The first-order (Dryden-form) roll-gust spectrum Yeager's filter
    realises (FGWinds.cpp eq. (21)/(33)); NOT the MIL-F-8785C p_g form."""
    x = l_p * np.asarray(omega, dtype=float)
    return sigma_p ** 2 * (2.0 * l_p / math.pi) / (1.0 + x * x)


def cumulative_energy(phi, omega_max: float, points: int = 8192) -> Tuple[np.ndarray, np.ndarray]:
    """``C(Omega) = integral_0^Omega phi dOmega`` on a log-spaced grid up to
    ``omega_max``: the trapezoid rule in ln(Omega) (``phi Omega d ln Omega``,
    smooth for a power law) plus the flat piece below the first node."""
    grid = np.geomspace(omega_max * 1e-9, omega_max, points)
    values = np.asarray(phi(grid), dtype=float)
    increments = 0.5 * (values[1:] * grid[1:] + values[:-1] * grid[:-1]) * np.diff(np.log(grid))
    cumulative = np.concatenate(([0.0], np.cumsum(increments))) + float(phi(0.0)) * grid[0]
    return grid, cumulative


def spectrum_integral(phi, omega_max: float, points: int = 8192) -> float:
    """``integral_0^omega_max phi dOmega`` (the normalisation checks and
    the truncated fraction)."""
    return float(cumulative_energy(phi, omega_max, points)[1][-1])


def psd_slope(series: np.ndarray, field_length_m: float, omega_lo: float = 0.1,
              omega_hi: float = 1.0, bands: int = 12) -> Optional[Dict[str, Any]]:
    """The realised one-sided PSD's log-log slope between ``omega_lo`` and
    ``omega_hi`` rad/m: the periodogram of the table column (each
    harmonic's line carries A^2/2 exactly, no leakage), summed over
    log-spaced bands and divided by each band's width, then a least-
    squares line through (ln Omega, ln PSD). None when fewer than 6
    bands hold a line. Reported as measured; the -5/3 law is the
    expectation for Omega far above 1/(1.339 L)."""
    n = len(series)
    power = np.abs(np.fft.rfft(np.asarray(series, dtype=float))) ** 2 * 2.0 / n ** 2
    omega = np.arange(len(power)) * 2.0 * math.pi / field_length_m
    edges = np.geomspace(omega_lo, omega_hi, bands + 1)
    xs: List[float] = []
    ys: List[float] = []
    lines = 0
    for lo, hi in zip(edges[:-1], edges[1:]):
        inside = (omega >= lo) & (omega < hi) & (power > 0.0)
        if not inside.any():
            continue
        lines += int(inside.sum())
        xs.append(math.sqrt(lo * hi))
        ys.append(float(power[inside].sum() / (hi - lo)))
    if len(xs) < 6:
        return None
    slope, intercept = np.polyfit(np.log(xs), np.log(ys), 1)
    return {"slope": float(slope), "bands": len(xs), "lines": lines,
            "omega_lo_rad_per_m": omega_lo, "omega_hi_rad_per_m": omega_hi,
            "expected": -5.0 / 3.0}


# -- the phases and the harmonics ------------------------------------------------------

def phase_generator(seed: int) -> np.random.Generator:
    """``default_rng(SeedSequence(seed, spawn_key=(stable_hash('von_karman'),)))``
    -- the named stream, so no other subsystem's draws move."""
    return np.random.default_rng(
        np.random.SeedSequence(int(seed), spawn_key=(stable_hash(SEED_STREAM),)))


def draw_phases(seed: int, count: int) -> np.ndarray:
    """Four rows (u, v, w, p) of ``count`` phases, uniform on [0, 2 pi)."""
    return phase_generator(seed).uniform(0.0, 2.0 * math.pi, size=(4, count))


def harmonics(n_samples: int, n_frequencies: int = N_FREQUENCIES) -> np.ndarray:
    """The distinct harmonic numbers k (of the table's fundamental) that
    ``n_frequencies`` log-spaced targets between 1 and n/2 - 1 snap to."""
    if n_samples < 8:
        raise ValueError(f"a table of {n_samples} rows cannot carry a spectrum")
    k_max = n_samples // 2 - 1
    targets = np.geomspace(1.0, float(k_max), n_frequencies)
    return np.unique(np.rint(targets).astype(int))


def bin_energies(phi, omegas: np.ndarray) -> np.ndarray:
    """The spectrum's energy in each component's bin: edges at the
    midpoints between neighbouring components, the first bin from 0, the
    last bin as wide above its component as below; each energy is a
    difference of the cumulative integral (:func:`cumulative_energy`),
    so the first bin -- where a power-law spectrum falls by orders of
    magnitude -- is integrated on a log grid, not a linear one."""
    edges = np.empty(len(omegas) + 1)
    edges[0] = 0.0
    edges[1:-1] = 0.5 * (omegas[:-1] + omegas[1:])
    edges[-1] = omegas[-1] + (omegas[-1] - edges[-2])
    grid, cumulative = cumulative_energy(phi, float(edges[-1]))
    at_edges = np.interp(edges, grid, cumulative, left=0.0)
    return np.diff(at_edges)


# -- the provider ---------------------------------------------------------------------

class VonKarmanTurbulence(GustProvider):
    """The von Karman field, realised into a table and delivered through
    the gust channel every step (see the module docstring).

    ``intensity`` is one of the existing turbulence words (mapped to W20
    and the exceedance index exactly as the Dryden provider maps them)
    or a W20 in knots; ``altitude_m`` is the altitude the ladder is
    entered with (ASL, as FGWinds does); ``seed`` the spec's seed. The
    table is built by :meth:`prepare` from the FDM's own pre-trim true
    airspeed and span (``metrics/bw-ft``), or by :meth:`build` from
    stated numbers.
    """

    name = "von_karman_turbulence"
    card_word = "von_karman"

    def __init__(self, intensity, seed: int, altitude_m: float, duration_s: float,
                 rate_hz: float, heading_deg: float = 0.0, stated: Optional[Dict[str, Any]] = None) -> None:
        self.word: Optional[str]
        if isinstance(intensity, str):
            if intensity not in W20_KT:
                raise ValueError(f"unknown turbulence intensity {intensity!r}; known: "
                                 f"{sorted(W20_KT)} or a W20 in knots")
            self.word = intensity
            self.w20_kt = float(W20_KT[intensity])
            self.poe_index = poe_index_for(intensity)
        else:
            self.word = None
            self.w20_kt = float(intensity)
            if not self.w20_kt >= 0.0:
                raise ValueError("W20 is a wind speed in knots, at or above 0")
            # The exceedance row whose Fig. 7 value at this altitude is
            # nearest 0.1 W20 (a stated choice for a numeric intensity).
            h_ft = u.m_to_ft(altitude_m)
            self.poe_index = min(range(1, 8), key=lambda i: abs(
                poe_sigma_fps(i, max(h_ft, MIN_HEIGHT_FT)) - 0.1 * u.kt_to_fps(self.w20_kt)))
        self.seed = int(seed)
        self.altitude_m = float(altitude_m)
        self.duration_s = float(duration_s)
        self.rate_hz = float(rate_hz)
        self.dt_s = 1.0 / self.rate_hz
        self.heading_deg = float(heading_deg)
        self.stated = dict(stated or {})
        h_ft = u.m_to_ft(self.altitude_m)
        self.sigma_fps = sigma_ladder_fps(h_ft, u.kt_to_fps(self.w20_kt), self.poe_index)
        self.scale_ft = scale_lengths_ft(h_ft)
        self.sigma_mps = tuple(u.fps_to_mps(s) for s in self.sigma_fps)
        self.scale_m = tuple(u.ft_to_m(x) for x in self.scale_ft)
        self.table: Optional[np.ndarray] = None
        self.built: Optional[Dict[str, Any]] = None
        self.steps_beyond_table = 0
        self.steps_delivered = 0
        self.t_start_s: Optional[float] = None

    @property
    def silent(self) -> bool:
        """An intensity of zero: no field, nothing written but zeros."""
        return all(s == 0.0 for s in self.sigma_fps)

    @property
    def n_rows(self) -> int:
        return int(round(self.duration_s * self.rate_hz)) + 1

    # -- building the table -----------------------------------------------------

    def build(self, tas_mps: float, span_m: float, basis: str = "stated") -> np.ndarray:
        """Realise the frozen field at the FDM rate: rows ``[t_s, u, v, w,
        p_g]`` (m/s and rad/s) for ``t = 0 .. duration`` inclusive."""
        if not tas_mps > 0.0:
            raise ValueError("the field is convected at a positive true airspeed")
        if not span_m > 0.0:
            raise ValueError("the roll gust needs a positive span")
        n = self.n_rows
        t = np.arange(n) / self.rate_hz          # i / rate, correctly rounded
        x = tas_mps * t
        # Periodic over n samples: the fundamental is 2 pi / (TAS n dt).
        x_length = tas_mps * n * self.dt_s
        omega_0 = 2.0 * math.pi / x_length
        ks = harmonics(n)
        omegas = ks * omega_0
        phases = draw_phases(self.seed, len(omegas))
        sigma_u, sigma_v, sigma_w = self.sigma_mps
        l_u, l_v, l_w = self.scale_m
        sigma_p, l_p = p_gust_parameters(sigma_w, l_w, span_m)
        spectra = (
            ("u", lambda w: phi_u(w, sigma_u, l_u), sigma_u),
            ("v", lambda w: phi_v(w, sigma_v, l_v), sigma_v),
            ("w", lambda w: phi_w(w, sigma_w, l_w), sigma_w),
            ("p", lambda w: phi_p(w, sigma_p, l_p), sigma_p),
        )
        columns = [t]
        realised: Dict[str, Any] = {}
        arg = np.outer(x, omegas)
        for row, (label, phi, sigma) in enumerate(spectra):
            if sigma == 0.0:
                columns.append(np.zeros(n))
                realised[label] = {"sigma_commanded": 0.0, "sigma_amplitudes": 0.0,
                                   "truncated_fraction": 0.0}
                continue
            energies = bin_energies(phi, omegas)
            amplitudes = np.sqrt(2.0 * energies)
            series = (amplitudes[None, :] * np.cos(arg + phases[row][None, :])).sum(axis=1)
            columns.append(series)
            realised[label] = {
                "sigma_commanded": float(sigma),
                "sigma_amplitudes": float(math.sqrt(0.5 * float((amplitudes ** 2).sum()))),
                "truncated_fraction": float(max(0.0, 1.0 - float(energies.sum()) / sigma ** 2)),
                "psd_slope": None if label == "p" else psd_slope(series, x_length),
            }
        self.table = np.column_stack(columns)
        self.built = {
            "basis": basis, "tas_mps": float(tas_mps), "span_m": float(span_m),
            "rows": n, "dt_s": self.dt_s, "field_length_m": x_length,
            "omega_0_rad_per_m": omega_0, "omega_max_rad_per_m": float(omegas[-1]),
            "n_frequencies": N_FREQUENCIES, "n_distinct_harmonics": int(len(omegas)),
            "sigma_p_rad_s": sigma_p, "l_p_m": l_p, "realised": realised,
            "seed": self.seed, "seed_stream": SEED_STREAM,
            "seed_derivation": ("numpy default_rng(SeedSequence(seed, spawn_key=(stable_hash('"
                                + SEED_STREAM + "'),))); four rows (u, v, w, p) of uniform "
                                "[0, 2 pi) phases"),
            "heading_deg": self.heading_deg,
        }
        return self.table

    def prepare(self, fdm) -> Dict[str, Any]:
        """The pre-trim hook (the stack calls it after the atmosphere
        providers'): the table from the FDM's own true airspeed at the
        initial conditions and its span."""
        tas_mps = u.kt_to_mps(fdm.props.get("velocities/vtrue-kts"))
        span_m = u.ft_to_m(fdm.props.get("metrics/bw-ft"))
        self.build(tas_mps, span_m, basis="the FDM's velocities/vtrue-kts at the initial "
                                          "conditions before the trim and metrics/bw-ft")
        return dict(self.built)

    def _ensure(self, own_ship: OwnShipState) -> None:
        if self.table is None:
            self.build(own_ship.tas_mps, own_ship.span_m,
                       basis="the own-ship state at the first step (prepare was not called)")

    def row_at(self, time_s: float) -> Optional[np.ndarray]:
        """The table row for a step time, or None past the table. Row 0
        is the FIRST step the provider is asked for (the run's first step
        after the trim; JSBSim's clock is not 0 there -- the piston crank
        has stepped it, measured 5.0 s on the c172p), so the time of that
        first call is latched as the table's origin and recorded."""
        if self.t_start_s is None:
            self.t_start_s = float(time_s)
            if self.built is not None:
                self.built["t_start_s"] = self.t_start_s
        index = int(round((time_s - self.t_start_s) * self.rate_hz))
        if index < 0 or index >= len(self.table):
            return None
        return self.table[index]

    # -- delivery ------------------------------------------------------------------

    def gust_at(self, own_ship: OwnShipState, time_s: float) -> WindNED:
        self._ensure(own_ship)
        row = self.row_at(time_s)
        if row is None:
            self.steps_beyond_table += 1
            return WindNED()
        self.steps_delivered += 1
        psi = math.radians(self.heading_deg)
        along, right, down = float(row[1]), float(row[2]), float(row[3])
        return WindNED(along * math.cos(psi) - right * math.sin(psi),
                       along * math.sin(psi) + right * math.cos(psi), down)

    def p_equivalent_at(self, own_ship: OwnShipState, time_s: float) -> float:
        self._ensure(own_ship)
        row = self.row_at(time_s)
        return 0.0 if row is None else float(row[4])

    # -- the card -----------------------------------------------------------------------

    def card_rows(self) -> List[List[str]]:
        """Every row as ``%.17g`` strings: the form both hosts write."""
        if self.table is None:
            raise ValueError("the table is not built; call prepare(fdm) or build()")
        return [[ROW_FORMAT % v for v in row] for row in self.table]

    @staticmethod
    def rows_sha256(rows: Sequence[Sequence[str]]) -> str:
        """SHA-256 over the rows' text: fields joined by one space, rows
        by one newline, ASCII."""
        text = "\n".join(" ".join(row) for row in rows)
        return hashlib.sha256(text.encode("ascii")).hexdigest()

    def card_block(self) -> Dict[str, Any]:
        """The ``gust_table`` card block in the fixed key order."""
        rows = self.card_rows()
        return {
            "model": self.card_word, "seed": self.seed,
            "sigma": [float(s) for s in self.sigma_mps],
            "L": [float(x) for x in self.scale_m],
            "tas_mps": self.built["tas_mps"], "dt_s": self.dt_s,
            "rows": rows, "sha256": self.rows_sha256(rows),
        }

    # -- the records ----------------------------------------------------------------------

    def model_block(self) -> Model:
        return Model(
            name=MODEL_NAME, standard=STANDARD, version="1",
            parameters={
                "spectral_convention": "MIL-F-8785C (L as written; MIL-HDBK-1797's 2L form NOT used)",
                "sigma_mps": list(self.sigma_mps), "sigma_fps": list(self.sigma_fps),
                "L_m": list(self.scale_m), "L_ft": list(self.scale_ft),
                "L_relation_above_2000_ft": "L_u = 2 L_v = 2 L_w = 2500 ft",
                "altitude_m_for_ladder": self.altitude_m,
                "altitude_basis": "above sea level, as FGWinds.cpp L145 enters the ladder",
                "w20_kt": self.w20_kt, "poe_index": self.poe_index, "word": self.word,
                "n_frequencies": N_FREQUENCIES, "seed_stream": SEED_STREAM,
                "vk_constant": VK_CONSTANT, "sigma_p_factor": SIGMA_P_FACTOR,
                "l_p_divisor": L_P_DIVISOR,
                "p_gust_spectrum": "first-order Dryden form (Yeager's filter), own phases",
                "realisation": "frozen field convected at the trim TAS along the trim heading, "
                               "sum of cosines at harmonics of the table length",
                "built": None if self.built is None else {
                    k: v for k, v in self.built.items() if k != "realised"},
                "realised": None if self.built is None else self.built["realised"],
                "q_g_r_g": "not delivered",
            },
            references=REFERENCES)

    def applied_variables(self, delivery: Optional[Dict[str, Any]] = None) -> List[AppliedVariable]:
        """One record per stated ``turbulence_model`` field (``model``,
        and ``intensity`` / ``seed`` when the spec states them), each with
        the gust channel's read-back the stack measured (``delivery``)
        and a null test on the gust channel the FDM received."""
        if self.built is None:
            raise ValueError("VonKarmanTurbulence.prepare(fdm) was never called; there is "
                             "no table, read-back or null test to record")
        delivery = dict(delivery or {})
        gust = delivery.get("gust") or {}
        readback_errors = gust.get("max_abs_error") or {}
        last_written = gust.get("last_written") or {}
        last_read = gust.get("last_read") or {}
        prop = GUST_PROPERTIES[0]
        readback = None
        if prop in last_written and prop in last_read:
            readback = Readback(
                property=prop, value=float(last_read[prop]), written=float(last_written[prop]),
                tolerance=0.0, tolerance_kind="absolute",
                basis=("read back before the next step's write; the gust channel holds "
                       "the value written to the bit (7 fps read 7.0 after 11 steps, "
                       "measured on JSBSim 1.2.4); the per-step maximum over the run "
                       "is in parameters.per_step_readback"))
        p_delivery = gust.get("p_equivalent", "absent")
        channel_std = gust.get("channel_std_mps")
        realised = self.built["realised"]
        null = NullTest(
            quantity="std of the gust-down channel read back from JSBSim over the run",
            unit="m/s",
            with_value=0.0 if channel_std is None else float(channel_std.get("down", 0.0)),
            without_value=0.0,
            threshold=u.kt_to_mps(0.1),
            note=(f"without = the gust channel of the same run with no gust provider, which "
                  f"reads 0 (measured: the stack writes 0 every step); commanded sigma_w "
                  f"{self.sigma_mps[2]:.4f} m/s, realised over the table "
                  f"{realised['w']['sigma_amplitudes']:.4f} m/s; threshold the 0.1 kt speed floor"))
        writes = tuple(JsbsimWrite(p, "every step, zero included (the channel persists)")
                       for p in GUST_PROPERTIES)
        properties = list(GUST_PROPERTIES)
        if p_delivery == "property":
            writes = writes + (JsbsimWrite(P_EQUIVALENT_PROPERTY, "every step (the derived airframe declares it)"),)
            properties.append(P_EQUIVALENT_PROPERTY)
        parameters: Dict[str, Any] = {
            "delivery": {
                "gust_channel": "atmosphere/gust-*-fps, summed by JSBSim into the total wind "
                                "beside the Dryden process (FGWinds.cpp L157)",
                "p_equivalent": p_delivery,
                "p_equivalent_note": ("delivered into gust/p-equivalent-rad_sec"
                                      if p_delivery == "property" else
                                      "NOT delivered: the loaded airframe declares no "
                                      "gust/p-equivalent-rad_sec (a stock airframe; the "
                                      "gust_rotation injection adds it), so the roll gust "
                                      "reached nothing"),
                "steps_written": gust.get("steps_written", 0),
                "steps_delivered": self.steps_delivered,
                "steps_beyond_table": self.steps_beyond_table,
            },
            "per_step_readback": {
                "steps_checked": gust.get("steps_checked", 0),
                "max_abs_error": dict(readback_errors),
                "tolerance": 0.0, "agrees": all(e == 0.0 for e in readback_errors.values()),
                "basis": "each gust property read back before the next step's write",
            },
            "channel_std_mps": channel_std,
            "table": {k: v for k, v in self.built.items()},
            "table_sha256": self.rows_sha256(self.card_rows()),
            "sigma_commanded_mps": list(self.sigma_mps),
            "L_m": list(self.scale_m),
        }
        not_claimed = (
            "q_g and r_g: not delivered (no property receives them)",
            "the p_g spectrum of MIL-F-8785C itself: Yeager's first-order form is realised",
            "the field is frozen in the NED frame along the trim heading and convected at "
            "the trim true airspeed; the aircraft's later motion is not followed",
            "anything beyond the table's last row (delivered as zero and counted)",
            "the specification's own numbers beyond what FGWinds transcribes (unverified here)",
            "the engine side: the card block is pinned; nothing applies it here",
        ) + (() if p_delivery == "property" else (
            "the roll gust on this airframe: gust/p-equivalent-rad_sec is absent",))
        common = dict(model=MODEL_NAME, model_block=self.model_block(), references=REFERENCES,
                      properties_written=tuple(properties), jsbsim_writes=writes,
                      telemetry_columns=TELEMETRY_COLUMNS, frame_keys=TELEMETRY_COLUMNS,
                      readback=readback, not_claimed=not_claimed)
        out: List[AppliedVariable] = []
        model_stated = self.stated.get("model") or {"value": "von_karman", "source": "user"}
        out.append(AppliedVariable(
            name="turbulence_model.model", value=model_stated.get("value", "von_karman"),
            unit="word", source=str(model_stated.get("source", "user")),
            frm=model_stated.get("from"), std=model_stated.get("std"),
            parameters=parameters, null_test=null, **common))
        for field, unit in (("intensity", "W20 kt | word"), ("seed", "1")):
            stated = self.stated.get(field)
            if not stated or stated.get("value") is None:
                continue
            out.append(AppliedVariable(
                name=f"turbulence_model.{field}", value=stated["value"], unit=unit,
                source=str(stated.get("source", "user")), frm=stated.get("from"),
                std=stated.get("std"),
                parameters={"applied_to": "the von Karman field",
                            "w20_kt": self.w20_kt, "poe_index": self.poe_index,
                            "sigma_mps": list(self.sigma_mps), "seed": self.seed,
                            "seed_stream": SEED_STREAM, "table_sha256": parameters["table_sha256"],
                            "delivery": parameters["delivery"],
                            "per_step_readback": parameters["per_step_readback"]},
                null_test=null, **common))
        return out

    # -- vocabulary and provenance ---------------------------------------------------------

    def vocabulary(self) -> List[Term]:
        terms = []
        for word, w20 in W20_KT.items():
            index = poe_index_for(word)
            terms.append(Term(
                phrase=word, value=w20, unit="kt W20",
                standard=STANDARD, valid_range=(0.0, 100.0),
                note=(f"below 1000 ft sigma_w = 0.1 W20; above 2000 ft the Fig. 7 row "
                      f"{index} (measured Dryden sigma_w {POE_SIGMA_W_FPS[index]:g} ft/s at "
                      f"1000 m, target {TARGET_SIGMA_W_FPS[word]:g}); the words map as the "
                      f"Dryden provider maps them")))
        terms.append(Term("W20 in knots", "number", "kt", STANDARD, (0.0, 100.0),
                          note="a numeric intensity: the exceedance row nearest 0.1 W20 at "
                               "the altitude is used above 2000 ft (a stated choice)"))
        return terms

    def provenance(self) -> Dict[str, Any]:
        out = super().provenance()
        out.update({
            "model": self.card_word, "word": self.word, "w20_kt": self.w20_kt,
            "poe_index": self.poe_index, "seed": self.seed, "seed_stream": SEED_STREAM,
            "altitude_m": self.altitude_m, "sigma_mps": list(self.sigma_mps),
            "L_m": list(self.scale_m), "rows": self.n_rows, "dt_s": self.dt_s,
            "heading_deg": self.heading_deg,
            "built": None if self.built is None else {
                k: v for k, v in self.built.items() if k != "realised"},
            "delivery": "atmosphere/gust-*-fps every step, zero included; "
                        "gust/p-equivalent-rad_sec where the airframe declares it",
        })
        return out
