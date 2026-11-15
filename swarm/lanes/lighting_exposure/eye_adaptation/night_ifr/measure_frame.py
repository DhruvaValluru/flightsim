#!/usr/bin/env python3
"""The pixel gate for lighting_exposure.eye_adaptation.night_ifr.

Runs on the WINDOWS laptop against frames it rendered (Pillow is in
requirements.txt). On the Mac only the arithmetic is tested.

Four frames of the same camera and instant:

    --reference       the calibrated look (eye off, brightness_ev 0)
    --dark-bracket    the look rendered 0.3 EV darker  (brightness_ev -0.3)
    --bright-bracket  the look rendered 0.3 EV brighter (brightness_ev +0.3)
    --frame           the candidate (the eye on)

The brackets ARE the gate's edges, rendered through the same tonemapper, so
no tone curve is modelled or inverted here: a monotone tonemapper keeps a
candidate that is inside +/-0.3 EV between its two brackets, pixel by pixel.

Metric, ``ev_offset``: per usable pixel, the candidate's place between the
reference and the bracket on its side, in log2 of sRGB-decoded luma, scaled
to the bracket's stops; then the median. Positive = exposed darker (the eye
closed). The interpolation is linear between two rendered points 0.3 EV
apart, so the tone curve's local slope cancels to first order. A pixel is
usable when it is mid-range (luma 8..235) in all four frames and each bracket
is at least 2 codes from the reference.

PASS when |ev_offset| <= 0.3 (the candidate's median pixel is not outside a
bracket), at least 0.5 % of the pixels were usable, and the eye helped:
closing must not add clipped pixels (luma >= 254), opening must not add
crushed ones (luma <= 1). With ``--expected`` the sign must agree when
|expected| >= 0.1. Exit 0 pass, 1 fail, 2 usage.

``display_ev_offset`` (the two-frame log ratio, no brackets) is printed for
information only: a filmic curve stretches or squeezes it, so it is not gated.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, Dict, Optional, Sequence

GATE_EV = 0.3
MID_LO, MID_HI = 8, 235
MIN_BRACKET_CODES = 2
MIN_USABLE_FRACTION = 0.005
SIGN_CHECK_ABOVE_EV = 0.1


def srgb_eotf(v: float) -> float:
    v = min(max(v, 0.0), 1.0)
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


_LOG = [math.log2(srgb_eotf(i / 255.0)) if i else -math.inf for i in range(256)]


def _median(values):
    values = sorted(values)
    return values[len(values) // 2]


def compare(candidate: Sequence[int], reference: Sequence[int],
            dark: Sequence[int], bright: Sequence[int],
            bracket_ev: float = GATE_EV, expected: Optional[float] = None) -> Dict[str, Any]:
    """All four are 8-bit luma sequences of the same length."""
    n = len(candidate)
    if not n or any(len(x) != n for x in (reference, dark, bright)):
        raise ValueError("frames must be the same non-zero size")
    if bracket_ev <= 0:
        raise ValueError("bracket_ev must be positive")
    evs, display = [], []
    for c, r, d, b in zip(candidate, reference, dark, bright):
        if not all(MID_LO <= v <= MID_HI for v in (c, r, d, b)):
            continue
        if r - d < MIN_BRACKET_CODES or b - r < MIN_BRACKET_CODES:
            continue
        if c <= r:
            evs.append(bracket_ev * (_LOG[r] - _LOG[c]) / (_LOG[r] - _LOG[d]))
        else:
            evs.append(-bracket_ev * (_LOG[c] - _LOG[r]) / (_LOG[b] - _LOG[r]))
        display.append(_LOG[r] - _LOG[c])
    usable = len(evs) / n
    out: Dict[str, Any] = {
        "usable_fraction": round(usable, 5),
        "clipped_fraction": round(sum(1 for c in candidate if c >= 254) / n, 5),
        "clipped_fraction_reference": round(sum(1 for r in reference if r >= 254) / n, 5),
        "crushed_fraction": round(sum(1 for c in candidate if c <= 1) / n, 5),
        "crushed_fraction_reference": round(sum(1 for r in reference if r <= 1) / n, 5),
        "gate_ev": GATE_EV, "bracket_ev": bracket_ev, "expected_offset_ev": expected,
    }
    reasons = []
    if usable < MIN_USABLE_FRACTION:
        out["ev_offset"] = None
        out["display_ev_offset"] = None
        reasons.append("too few usable pixels to meter (frame near black or clipped, "
                       "or the brackets did not move it)")
    else:
        ev = _median(evs)
        out["ev_offset"] = round(ev, 3)
        out["display_ev_offset"] = round(_median(display), 3)
        if abs(ev) > GATE_EV:
            reasons.append(f"ev_offset {ev:+.3f} is outside +/-{GATE_EV}")
        if ev > 0 and out["clipped_fraction"] > out["clipped_fraction_reference"]:
            reasons.append("the eye closed but clipped pixels went up")
        if ev < 0 and out["crushed_fraction"] > out["crushed_fraction_reference"]:
            reasons.append("the eye opened but crushed pixels went up")
        if expected is not None and abs(expected) >= SIGN_CHECK_ABOVE_EV and ev * expected <= 0:
            reasons.append(f"ev_offset {ev:+.3f} has the wrong sign for the expected {expected:+.2f}")
    out["pass"] = not reasons
    out["reasons"] = reasons
    return out


def _luma(path: str):
    from PIL import Image  # Windows venv; not needed for the Mac tests
    with Image.open(path) as im:
        return im.convert("L").tobytes(), im.size


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--frame", required=True)
    p.add_argument("--reference", required=True)
    p.add_argument("--dark-bracket", required=True)
    p.add_argument("--bright-bracket", required=True)
    p.add_argument("--bracket-ev", type=float, default=GATE_EV)
    p.add_argument("--expected", type=float, default=None)
    try:
        a = p.parse_args(argv)
    except SystemExit:
        return 2
    frames = [_luma(x) for x in (a.frame, a.reference, a.dark_bracket, a.bright_bracket)]
    if len({size for _, size in frames}) != 1:
        print(f"frame sizes differ: {[size for _, size in frames]}", file=sys.stderr)
        return 2
    result = compare(*(data for data, _ in frames), bracket_ev=a.bracket_ev, expected=a.expected)
    print(json.dumps(result, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
