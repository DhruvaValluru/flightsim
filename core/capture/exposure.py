"""Physical camera exposure: EV100 from aperture, shutter and ISO.

The one formula (ISO 2720 / the "exposure value at ISO 100" the
brainstorm section 9.7 and contracts section 10 name):

    EV100 = log2(N^2 / t * 100 / ISO)

with N the aperture f-number, t the shutter time in seconds and ISO the
sensor speed. It is what the engine's manual exposure computes from
``CameraShutterSpeed`` (1/t), ``CameraISO`` and ``DepthOfFieldFstop``
when ``AutoExposureApplyPhysicalCameraExposure`` is on, and it is what
``FFlightSimVisualScene::ExposureValue100`` (C++) re-implements so the
render manifest can record the number the capture was set to. Two
implementations of one formula: ``tests/test_exposure.py`` hand-computes
the reference (f/8, 1/500 s, ISO 100 -> log2(64 * 500) = 14.966) against
this module and pins the C++ source text to the same expression.

What is claimed
---------------
* ``ev100`` is the formula above, refused BY NAME (``camera.exposure``)
  for a non-positive or non-numeric input, never a stack trace.
* ``PRESET_DEFAULTS`` restates the spec-8 exposure defaults per preset
  (contracts section 10: one daylight triple f/8, 1/500 s, ISO 100 for
  every preset today). It is a RESTATEMENT, not an import of
  ``core.scenario.camera.EXPOSURE_DEFAULTS``: the test that compares the
  two tables is the only place they meet.
* ``shutter_for_ev100`` is the inverse used when a card carries a
  Python-computed EV100 but no triple (``randomization.look.ev100``):
  the engine is handed N = 1, ISO = 100 and t = 2^-EV100, which the same
  formula maps back to that EV100 exactly.

What is NOT claimed
-------------------
* That a frame rendered at this EV100 has any particular brightness: the
  engine's calibration constant (K = 12.5 in the extended luminance
  range, a different scale without it) is the engine's, and whether the
  extended range was on is READ BACK into ``render.json.render_settings``
  (``r.DefaultFeature.AutoExposure.ExtendDefaultLuminanceRange``), never
  assumed here. The Gate 6 exposure clauses measure from pixels.
* That the exposure was applied at all: only ``render.json``'s
  ``render_settings.exposure_mode`` says which path the capture took.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

#: The refusal name for a triple that cannot be exposed with.
REFUSAL_NAME = "camera.exposure"

#: The exposure triple order everywhere: (aperture f-number, shutter s, ISO).
EXPOSURE_FIELDS = ("aperture_f", "shutter_s", "iso")

#: The daylight triple contracts section 10 states for every preset.
DAYLIGHT_TRIPLE: Tuple[float, float, float] = (8.0, 1.0 / 500.0, 100.0)

#: Per-preset defaults (restated from the contracts, not imported; the
#: preset names are the spec's five words).
PRESET_DEFAULTS: Dict[str, Tuple[float, float, float]] = {
    "chase": DAYLIGHT_TRIPLE,
    "cockpit": DAYLIGHT_TRIPLE,
    "wingman": DAYLIGHT_TRIPLE,
    "ground": DAYLIGHT_TRIPLE,
    "tower": DAYLIGHT_TRIPLE,
    "explicit": DAYLIGHT_TRIPLE,
}

#: The render manifest's exposure-mode spellings (render.json
#: ``render_settings.exposure_mode``), so a reader matches on a name.
EXPOSURE_MODE_AUTO = "auto"
EXPOSURE_MODE_BIAS = "manual_bias"
EXPOSURE_MODE_PHYSICAL = "manual_ev100"


class ExposureError(ValueError):
    """A triple that cannot be exposed with, refused by name."""

    name = REFUSAL_NAME

    def __init__(self, message: str):
        super().__init__(f"{REFUSAL_NAME}: {message}")


def _positive(value, field: str) -> float:
    if isinstance(value, bool):
        raise ExposureError(f"{field} must be a positive number, not {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ExposureError(f"{field} must be a positive number, not {value!r}")
    if not math.isfinite(number) or not number > 0.0:
        raise ExposureError(f"{field} must be a positive number, not {value!r}")
    return number


def ev100(aperture_f, shutter_s, iso) -> float:
    """EV100 = log2(N^2 / t * 100 / ISO). Unrounded."""
    n = _positive(aperture_f, "aperture_f")
    t = _positive(shutter_s, "shutter_s")
    s = _positive(iso, "iso")
    return math.log2((n * n / t) * (100.0 / s))


def preset_default(preset: str) -> Tuple[float, float, float]:
    """The documented triple for a preset word; an unknown word refuses
    by name rather than guessing a lens."""
    try:
        return PRESET_DEFAULTS[str(preset)]
    except KeyError:
        raise ExposureError(f"no exposure default for preset {preset!r}; "
                            f"presets are {sorted(PRESET_DEFAULTS)}")


def ev100_for_preset(preset: str) -> float:
    return ev100(*preset_default(preset))


def shutter_for_ev100(value, aperture_f: float = 1.0, iso: float = 100.0) -> float:
    """The inverse: the shutter time t that puts (N, t, ISO) at EV100 =
    value, t = N^2 * 100 / (ISO * 2^EV100). With the defaults N = 1 and
    ISO = 100 this is 2^-EV100, which is how a card's Python-computed
    EV100 is handed to the engine without a triple."""
    if isinstance(value, bool):
        raise ExposureError(f"ev100 must be a finite number, not {value!r}")
    try:
        ev = float(value)
    except (TypeError, ValueError):
        raise ExposureError(f"ev100 must be a finite number, not {value!r}")
    if not math.isfinite(ev):
        raise ExposureError(f"ev100 must be a finite number, not {value!r}")
    n = _positive(aperture_f, "aperture_f")
    s = _positive(iso, "iso")
    return (n * n * 100.0) / (s * math.pow(2.0, ev))


def describe(aperture_f, shutter_s, iso) -> str:
    """The manifest's human line for a triple: what the engine was set to."""
    value = ev100(aperture_f, shutter_s, iso)
    return (f"EV100 {value:.2f} (f/{float(aperture_f):g}, "
            f"{float(shutter_s):.6g} s, ISO {float(iso):g})")
