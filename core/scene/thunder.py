"""Thunder: the sound a listener hears from a flash on the card, synthesised from its channel.

Thunder is the channel's own shock, heard piece by piece: every segment of
the bolt sends out a pressure pulse when a stroke heats it, and the pulses
arrive in the order of their distance -- the nearest segment first (the
crack), the farthest last (the rumble that rolls on for seconds). This
module synthesises exactly that sum from the channel geometry on the card,
so the thunder of a drawn bolt belongs to THAT bolt: its delay, its length,
its claps where the channel runs across the line of sight.

The model (Few 1969's tortuous-channel picture [unverified here]):

* each segment i (midpoint m, length l, direction u) of a channel heated by
  stroke k radiates an N-wave of half-period T and amplitude A at the
  listener P, arriving at t_k + r / c, r = |P - m|;
* c = 331.3 sqrt(T_K / 273.15) m/s, T_K the ISA temperature at the scene's
  datum;
* the N-wave's initial half-period T0 = 1 / (2 f_m), f_m = 0.63 c / R0 the
  dominant frequency of a cylindrical shock of relaxation radius
  R0 = sqrt(E_l / (pi p0)), E_l the energy per metre ENERGY_PER_M;
* weak-shock lengthening and decay: T = T0 sqrt(L), A ~ 1 / sqrt(L),
  L = 1 + LENGTHENING ln(r / R0);
* spreading A ~ l / r, the stroke's energy share sqrt(Pp_k / Pp_0), and
  the segment's directivity D = floor + (1 - floor) sin(angle(u, P - m)):
  a segment radiates most broadside (Few's claps);
* absorption: a one-pole low-pass whose corner falls with distance,
  f_c = ABSORPTION_F0_HZ / (1 + r / ABSORPTION_R_M) (an approximation of
  ISO 9613-1's frequency-dependent absorption, stated);
* refraction: thunder is rarely heard past ~25 km (Fleagle 1949
  [unverified here]): a smoothstep fade from AUDIBLE_FULL_M to AUDIBLE_MAX_M.

The synthesis is specified sample by sample in :func:`synthesise` so the
host's port (the interactive window plays thunder) produces the same
samples; the card carries a selftest on a fixed three-segment flash.

The amplitude reference PRESSURE_REF_PA_M (pascal-metres per metre of
segment) is a CALIBRATION constant: one 25 m segment broadside at 1 km
gives 10 Pa. Absolute loudness is therefore stated, not measured; the
relative loudness of near and far bolts is the model's.

Rain noise (the offline soundtrack only): band-limited noise at
RAIN_SPL_DB_AT_1MMH + 10 log10(R) dB SPL (stated).

Not claimed: ground reflection, wind and temperature-gradient refraction
beyond the fade, the listener moving during a clip, the infrasonic
component.
"""

from __future__ import annotations

import math
import random
import struct
import wave
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SAMPLE_RATE_HZ = 48000
ENERGY_PER_M = 1.0e6
P0_PA = 101325.0
LENGTHENING = 0.5
DIRECTIVITY_FLOOR = 0.15
PRESSURE_REF_PA_M = 400.0
R_MIN_M = 10.0
ABSORPTION_F0_HZ = 3000.0
ABSORPTION_R_M = 800.0
AUDIBLE_FULL_M = 15000.0
AUDIBLE_MAX_M = 25000.0
TAIL_TIME_CONSTANTS = 5.0
#: WAV full scale (Pa): 100 Pa is 134 dB SPL.
FULL_SCALE_PA = 100.0
P_REF_SPL = 20.0e-6
RAIN_SPL_DB_AT_1MMH = 50.0
RAIN_BAND_HZ = (500.0, 8000.0)

#: The card's ``weather.thunder`` keys, in their fixed order.
CARD_KEYS = ("sound_speed_mps", "temperature_k", "sample_rate_hz", "energy_per_m",
             "relaxation_radius_m", "t0_s", "lengthening", "directivity_floor",
             "pressure_ref_pa_m", "absorption_f0_hz", "absorption_r_m", "audible_full_m",
             "audible_max_m", "full_scale_pa", "selftest")

REFERENCES = (
    "Few, A. A. 1969, J. Geophys. Res. 74, 6926 (power spectrum of thunder) [unverified here]",
    "Fleagle, R. G. 1949, J. Meteor. 6, 208 (audibility of thunder) [unverified here]",
    "ISO 9613-1:1993 (atmospheric absorption of sound) [unverified here]",
)

NOT_CLAIMED = (
    "no ground reflection, no refraction beyond the audibility fade",
    "the listener is fixed for the length of a clip",
    "absolute loudness is the stated PRESSURE_REF_PA_M calibration",
)


def temperature_k(datum_m: float) -> float:
    """ISA temperature at the scene datum."""
    return 288.15 - 0.0065 * min(max(float(datum_m), 0.0), 11000.0)


def sound_speed_mps(temp_k: float) -> float:
    return 331.3 * math.sqrt(float(temp_k) / 273.15)


def relaxation_radius_m() -> float:
    return math.sqrt(ENERGY_PER_M / (math.pi * P0_PA))


def t0_s(c: float) -> float:
    """The N-wave's initial half-period: 1 / (2 f_m), f_m = 0.63 c / R0."""
    return 1.0 / (2.0 * 0.63 * float(c) / relaxation_radius_m())


def audibility(r: float) -> float:
    if r <= AUDIBLE_FULL_M:
        return 1.0
    if r >= AUDIBLE_MAX_M:
        return 0.0
    x = (AUDIBLE_MAX_M - r) / (AUDIBLE_MAX_M - AUDIBLE_FULL_M)
    return x * x * (3.0 - 2.0 * x)


def segments(flash: Dict[str, Any]) -> List[Tuple[int, Tuple[float, float, float], float,
                                                  Tuple[float, float, float]]]:
    """(stroke index, midpoint, length, unit direction) of every heated
    segment, in the synthesis order: strokes, then channels, then points.
    A branch is heated by the first stroke only."""
    out = []
    for k, _stroke in enumerate(flash["strokes"]):
        for channel in flash["channels"]:
            if channel["kind"] == "branch" and k > 0:
                continue
            pts = channel["points"]
            for i in range(len(pts) - 1):
                a, b = pts[i], pts[i + 1]
                d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
                length = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
                if length <= 0.0:
                    continue
                mid = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]), 0.5 * (a[2] + b[2]))
                out.append((k, mid, length, (d[0] / length, d[1] / length, d[2] / length)))
    return out


def pulse(c: float, listener: Sequence[float], mid: Sequence[float], length: float,
          direction: Sequence[float], energy_ratio: float) -> Dict[str, float]:
    """One segment's N-wave at the listener: delay, half-period, amplitude, corner."""
    rel = (float(listener[0]) - mid[0], float(listener[1]) - mid[1], float(listener[2]) - mid[2])
    r = max(R_MIN_M, math.sqrt(rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2))
    cos = abs(rel[0] * direction[0] + rel[1] * direction[1] + rel[2] * direction[2]) / r
    sin = math.sqrt(max(0.0, 1.0 - cos * cos))
    directivity = DIRECTIVITY_FLOOR + (1.0 - DIRECTIVITY_FLOOR) * sin
    lengthen = 1.0 + LENGTHENING * math.log(max(r, relaxation_radius_m()) / relaxation_radius_m())
    half = t0_s(c) * math.sqrt(lengthen)
    amplitude = (PRESSURE_REF_PA_M * length / r * directivity * math.sqrt(energy_ratio)
                 / math.sqrt(lengthen) * audibility(r))
    corner = ABSORPTION_F0_HZ / (1.0 + r / ABSORPTION_R_M)
    return {"r_m": r, "delay_s": r / c, "half_s": half, "amplitude_pa": amplitude,
            "corner_hz": corner}


def synthesise(flash: Dict[str, Any], listener: Sequence[float], c: float,
               sample_rate: int = SAMPLE_RATE_HZ) -> Tuple[List[float], float]:
    """The flash's thunder at ``listener`` (Pa), sample 0 at the flash's t_s;
    returns (samples, first arrival in s after t_s). Sample by sample:

        n0 = round((t_k - t_s + r / c) fs), N = ceil(2 T fs),
        tail = ceil(TAIL_TIME_CONSTANTS fs / (2 pi f_c)),
        alpha = 1 - exp(-2 pi f_c / fs), y = 0,
        for j in 0 .. N + tail - 1:
            x = A (1 - j / (fs T)) if j < N else 0;  y += alpha (x - y);
            out[n0 + j] += y
    """
    fs = int(sample_rate)
    t_s = float(flash["t_s"])
    peak0 = float(flash["strokes"][0]["peak_w_per_m"]) if flash["strokes"] else 1.0
    plan = []
    end = 0
    first = math.inf
    for k, mid, length, direction in segments(flash):
        stroke = flash["strokes"][k]
        p = pulse(c, listener, mid, length, direction, float(stroke["peak_w_per_m"]) / peak0)
        if p["amplitude_pa"] <= 0.0:
            continue
        arrival = float(stroke["t_s"]) - t_s + p["delay_s"]
        n0 = int(round(arrival * fs))
        count = int(math.ceil(2.0 * p["half_s"] * fs))
        tail = int(math.ceil(TAIL_TIME_CONSTANTS * fs / (2.0 * math.pi * p["corner_hz"])))
        plan.append((n0, count, tail, p))
        end = max(end, n0 + count + tail)
        first = min(first, arrival)
    out = [0.0] * end
    for n0, count, tail, p in plan:
        alpha = 1.0 - math.exp(-2.0 * math.pi * p["corner_hz"] / fs)
        amplitude = p["amplitude_pa"]
        inv = 1.0 / (fs * p["half_s"])
        y = 0.0
        for j in range(count + tail):
            x = amplitude * (1.0 - j * inv) if j < count else 0.0
            y += alpha * (x - y)
            out[n0 + j] += y
    return out, (first if plan else math.inf)


def rain_noise(rate_mmh: float, seconds: float, seed: int,
               sample_rate: int = SAMPLE_RATE_HZ) -> List[float]:
    """Band-limited rain noise (Pa) at RAIN_SPL_DB_AT_1MMH + 10 log10(R) dB SPL."""
    fs = int(sample_rate)
    rng = random.Random(int(seed) * 31 + 5)
    level_db = RAIN_SPL_DB_AT_1MMH + 10.0 * math.log10(max(float(rate_mmh), 1e-6))
    rms = P_REF_SPL * 10.0 ** (level_db / 20.0)
    hp = 1.0 - math.exp(-2.0 * math.pi * RAIN_BAND_HZ[0] / fs)
    lp = 1.0 - math.exp(-2.0 * math.pi * RAIN_BAND_HZ[1] / fs)
    low = 0.0
    smooth = 0.0
    raw = []
    for _ in range(int(seconds * fs)):
        x = rng.gauss(0.0, 1.0)
        low += hp * (x - low)
        smooth += lp * ((x - low) - smooth)
        raw.append(smooth)
    measured = math.sqrt(sum(v * v for v in raw) / len(raw)) if raw else 1.0
    return [v * rms / measured for v in raw]


def write_wav(path: str, samples: Sequence[float], sample_rate: int = SAMPLE_RATE_HZ,
              full_scale_pa: float = FULL_SCALE_PA) -> Dict[str, Any]:
    """16-bit mono PCM, FULL_SCALE_PA at full scale; clipped samples counted."""
    clipped = 0
    frames = bytearray()
    for v in samples:
        q = int(round(float(v) / full_scale_pa * 32767.0))
        if q > 32767 or q < -32768:
            clipped += 1
            q = max(-32768, min(32767, q))
        frames += struct.pack("<h", q)
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(bytes(frames))
    return {"path": path, "samples": len(samples), "clipped": clipped,
            "full_scale_pa": full_scale_pa, "sample_rate_hz": int(sample_rate)}


def soundtrack(weather: Dict[str, Any], seconds: float,
               listener_at: Callable[[float], Sequence[float]],
               sample_rate: int = SAMPLE_RATE_HZ, rain: bool = True) -> List[float]:
    """The run's sound (Pa): every flash's thunder heard at the listener's
    position at the flash's own time, plus the rain noise."""
    fs = int(sample_rate)
    total = int(math.ceil(float(seconds) * fs))
    out = [0.0] * total
    thunder = weather.get("thunder")
    lightning = weather.get("lightning")
    if thunder and lightning:
        c = float(thunder["sound_speed_mps"])
        for flash in lightning["flashes"]:
            clip, _first = synthesise(flash, listener_at(float(flash["t_s"])), c, fs)
            start = int(round(float(flash["t_s"]) * fs))
            for j, v in enumerate(clip):
                if 0 <= start + j < total:
                    out[start + j] += v
    rain_block = weather.get("rain")
    if rain and rain_block:
        noise = rain_noise(float(rain_block["rate_mmh"]), seconds, int(rain_block["seed"]), fs)
        for j in range(min(total, len(noise))):
            out[j] += noise[j]
    return out


#: The fixed selftest flash: three segments, two strokes, one branch.
SELFTEST_FLASH = {
    "index": 0, "t_s": 0.0, "kind": "cg",
    "strokes": [{"t_s": 0.02, "peak_w_per_m": 600000.0}, {"t_s": 0.08, "peak_w_per_m": 300000.0}],
    "channels": [
        {"kind": "main", "length_m": 0.0,
         "points": [[0.0, 0.0, 1200.0], [30.0, 10.0, 1150.0], [20.0, -15.0, 1100.0]]},
        {"kind": "branch", "length_m": 0.0,
         "points": [[30.0, 10.0, 1150.0], [60.0, 30.0, 1120.0]]},
    ],
}
SELFTEST_LISTENER = (1500.0, -400.0, 2.0)
SELFTEST_SAMPLE_RATE_HZ = 8000
SELFTEST_POINTS = 24


def selftest(c: float) -> Dict[str, Any]:
    """The fixed flash synthesised at a reduced rate: the host's port must
    reproduce these samples (relative 1e-9)."""
    samples, first = synthesise(SELFTEST_FLASH, SELFTEST_LISTENER, c, SELFTEST_SAMPLE_RATE_HZ)
    nonzero = [i for i, v in enumerate(samples) if v != 0.0]
    lo, hi = nonzero[0], nonzero[-1]
    picks = sorted({lo + (hi - lo) * k // (SELFTEST_POINTS - 1) for k in range(SELFTEST_POINTS)})
    return {"flash": SELFTEST_FLASH, "listener_enu_m": list(SELFTEST_LISTENER),
            "sample_rate_hz": SELFTEST_SAMPLE_RATE_HZ, "length": len(samples),
            "first_arrival_s": first, "samples": [[i, samples[i]] for i in picks]}


def card_block(datum_m: float) -> Dict[str, Any]:
    """``weather.thunder`` in CARD_KEYS order."""
    temp = temperature_k(datum_m)
    c = sound_speed_mps(temp)
    return {"sound_speed_mps": c, "temperature_k": temp, "sample_rate_hz": SAMPLE_RATE_HZ,
            "energy_per_m": ENERGY_PER_M, "relaxation_radius_m": relaxation_radius_m(),
            "t0_s": t0_s(c), "lengthening": LENGTHENING, "directivity_floor": DIRECTIVITY_FLOOR,
            "pressure_ref_pa_m": PRESSURE_REF_PA_M, "absorption_f0_hz": ABSORPTION_F0_HZ,
            "absorption_r_m": ABSORPTION_R_M, "audible_full_m": AUDIBLE_FULL_M,
            "audible_max_m": AUDIBLE_MAX_M, "full_scale_pa": FULL_SCALE_PA,
            "selftest": selftest(c)}


def arrival_window(flash: Dict[str, Any], listener: Sequence[float],
                   c: float) -> Optional[Tuple[float, float]]:
    """(first, last) arrival after the flash's t_s of any segment, unfiltered."""
    times = []
    t_s = float(flash["t_s"])
    for k, mid, _length, _direction in segments(flash):
        r = max(R_MIN_M, math.dist(listener, mid))
        times.append(float(flash["strokes"][k]["t_s"]) - t_s + r / c)
    return (min(times), max(times)) if times else None
