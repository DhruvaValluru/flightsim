"""Intra-exposure motion blur: the velocity-line integral over the
shutter time (S1; gap S2; ADVANCEMENTS_BLUEPRINT section 3).

During an exposure of t_exp the scene point at a pixel moves along its
image velocity. With the flow f (pixels per telemetry interval dt,
screen +x right, +y down) the length of the streak is |f| t_exp / dt,
centred on the capture instant (a symmetric window: the exposure is
taken as centred on the frame's nominal time, as the rolling-shutter
model's rows are). The integral is evaluated as N equally weighted taps
at the symmetric offsets s_k = L (k / (N - 1) - 1/2), k = 0..N-1, along
f's direction, N = max(3, ceil(2 |f| t_exp / dt)) so neighbouring taps
sit L / (N - 1) <= L / (2 L - 1) apart, half a pixel plus 1 / (4 L - 2)
(McGuire et al. 2012's reconstruction
filter reduced to the linear-motion case, with bilinear sampling and
clamped edges). A flow FIELD gives every pixel its own streak; a
constant flow gives one streak for the frame. When the bundle says the
engine already accumulated sub-exposure captures (S4's
``-accumulate=K``: render.json ``frame_records[].accumulation.k > 1``)
the Python integral is NOT applied and the block records
``engine_accumulation`` instead -- blurring twice would be a lie.

Measured, not asserted: tests/test_blur.py moves a synthetic step edge
and shows the streak the integral makes is |f| t_exp / dt long within
0.25 px for streaks of 2 px and longer, at three sub-pixel edge
positions (the length is read off the row as the standard deviation of
the line spread function -- the row's finite difference -- times
sqrt(12), with the unblurred edge's own variance and the discrete tap
distribution's factor (N + 1) / (N - 1) removed, both stated in
:func:`streak_length_px`); an exposure of 0 leaves the frame identical
(the null: the taps all sit at offset 0 and a bilinear sample at an
integer offset returns the pixel itself). BELOW 2 px the three bilinear
taps are each a one-pixel triangle and the blur is WIDER than the
streak (measured: 1.0 px apparent at 0.5 px, 1.41 px at 1.0 px); the
block's ``sub_pixel_taps`` says so and no claim is made there.

What is NOT claimed: occlusion (a streak crosses whatever is behind it:
linear-motion blur, not occlusion-aware), rotation within the exposure
(the flow is a translation per pixel), non-uniform shutter timing, and
-- without the flow passes of S2 -- any per-pixel flow at all: the
constant flow a caller passes is a stated one.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

REFUSAL_MOTION_BLUR = "sensing.motion_blur"
BLUR_MODELS = ("velocity_line",)
#: The fewest taps an integral is evaluated with, and the most.
MIN_TAPS = 3
MAX_TAPS = 4096
#: The telemetry interval a flow in pixels per sample is measured over.
DEFAULT_DT_S = 0.1
#: The predicted blur below which the engine's accumulation records k = 1
#: (the blueprint's rule; the Python integral applies at any length).
SUB_PIXEL_BLUR_PX = 0.25
#: Below this streak length the three bilinear taps are wider than the
#: streak (see the module docstring); no length claim is made there.
MIN_STREAK_CLAIMED_PX = 2.0
APPLIED_BY_PYTHON = "python_velocity_line"
APPLIED_BY_ENGINE = "engine_accumulation"

REFERENCES = (
    "McGuire, Hennessy, Bukowski, Osman, A Reconstruction Filter for Plausible Motion Blur, "
    "I3D 2012 [unverified here]",
    "Haeberli & Akeley, The Accumulation Buffer, SIGGRAPH 1990 [unverified here]",
    "docs/ADVANCEMENTS_BLUEPRINT.md section 3, corrections applied",
)


class MotionBlurError(Exception):
    """A motion-blur block that cannot be applied, refused by name
    (``sensing.motion_blur``)."""

    constraint = "sensing.motion_blur"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{REFUSAL_MOTION_BLUR}: {message}")


def blur_length_px(flow_px_per_dt: float, exposure_s: float, dt_s: float = DEFAULT_DT_S) -> float:
    """|f| t_exp / dt: the streak length in pixels."""
    if not (isinstance(dt_s, (int, float)) and math.isfinite(dt_s) and dt_s > 0.0):
        raise MotionBlurError(f"the flow interval dt must be a positive number of seconds, not {dt_s!r}")
    if not (isinstance(exposure_s, (int, float)) and math.isfinite(exposure_s) and exposure_s >= 0.0):
        raise MotionBlurError(f"the exposure must be a non-negative number of seconds, not {exposure_s!r}")
    return abs(float(flow_px_per_dt)) * float(exposure_s) / float(dt_s)


def tap_count(blur_px: float) -> int:
    """N = max(3, ceil(2 L)): taps L / (N - 1) <= L / (2 L - 1) apart."""
    if not math.isfinite(blur_px) or blur_px < 0.0:
        raise MotionBlurError(f"a blur length must be a non-negative number of pixels, not {blur_px!r}")
    n = max(MIN_TAPS, int(math.ceil(2.0 * blur_px)))
    if n > MAX_TAPS:
        raise MotionBlurError(f"a streak of {blur_px:.1f} px needs {n} taps, more than {MAX_TAPS}; "
                              f"no camera this repo profiles blurs that far")
    return n


def tap_offsets(n: int, length_px: float) -> Tuple[float, ...]:
    """The symmetric offsets s_k = L (k/(N-1) - 1/2) along the streak."""
    if n < 2:
        raise MotionBlurError(f"an integral needs at least two taps, not {n}")
    return tuple(float(length_px) * (k / (n - 1) - 0.5) for k in range(n))


def _sample_bilinear(image, u, v):
    """image (H x W x C) at float pixel coordinates (u right, v down),
    edges clamped: a streak that runs off the frame repeats the edge
    rather than darkening (a black border would be a lie about the
    scene)."""
    import numpy as np

    height, width = image.shape[0], image.shape[1]
    u = np.clip(u, 0.0, width - 1.0)
    v = np.clip(v, 0.0, height - 1.0)
    u0 = np.floor(u).astype(int)
    v0 = np.floor(v).astype(int)
    u1 = np.minimum(u0 + 1, width - 1)
    v1 = np.minimum(v0 + 1, height - 1)
    du = (u - u0)[..., None]
    dv = (v - v0)[..., None]
    return (image[v0, u0] * (1 - du) * (1 - dv) + image[v0, u1] * du * (1 - dv)
            + image[v1, u0] * (1 - du) * dv + image[v1, u1] * du * dv)


def velocity_line_blur(frame, flow, exposure_s: float, dt_s: float = DEFAULT_DT_S):
    """(the blurred frame, the block): ``flow`` is (fx, fy) in pixels per
    dt for the whole frame or an H x W x 2 field. Exposure 0 returns the
    input array itself (the null); otherwise N taps along each pixel's
    streak, equally weighted, bilinear, edges clamped."""
    import numpy as np

    image = np.asarray(frame, dtype=np.float64)
    if image.ndim != 3:
        raise MotionBlurError(f"the frame must be H x W x C, not shape {image.shape}")
    height, width = image.shape[0], image.shape[1]
    field = np.asarray(flow, dtype=np.float64)
    if field.shape == (2,):
        field = np.broadcast_to(field, (height, width, 2))
    if field.shape != (height, width, 2):
        raise MotionBlurError(f"the flow must be (fx, fy) or an {height} x {width} x 2 field, "
                              f"not shape {field.shape}")
    if not np.all(np.isfinite(field)):
        raise MotionBlurError("the flow holds a non-finite value")
    speed = np.sqrt(field[..., 0] ** 2 + field[..., 1] ** 2)
    lengths = blur_length_px(1.0, exposure_s, dt_s) * speed     # |f| t_exp / dt per pixel
    length_max = float(lengths.max()) if lengths.size else 0.0
    n = tap_count(length_max)
    block = {
        "model": BLUR_MODELS[0], "applied_by": APPLIED_BY_PYTHON,
        "exposure_s": float(exposure_s), "dt_s": float(dt_s), "taps": n,
        "tap_offsets_px": list(tap_offsets(n, length_max)),
        "blur_px_max": length_max, "blur_px_mean": float(lengths.mean()) if lengths.size else 0.0,
        "flow_source": "field" if np.asarray(flow).shape != (2,) else "constant",
        "window": "symmetric about the capture instant, equal weights",
        "sub_pixel": bool(length_max < SUB_PIXEL_BLUR_PX),
        "sub_pixel_taps": bool(0.0 < length_max < MIN_STREAK_CLAIMED_PX),
        "references": list(REFERENCES),
    }
    if length_max == 0.0:
        return frame, block                                     # the null: nothing moved
    with np.errstate(invalid="ignore", divide="ignore"):
        direction = np.where(speed[..., None] > 0.0, field / np.maximum(speed, 1e-300)[..., None], 0.0)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    out = np.zeros_like(image)
    for k in range(n):
        s = lengths * (k / (n - 1) - 0.5)
        out += _sample_bilinear(image, xs + s * direction[..., 0], ys + s * direction[..., 1])
    return out / n, block


def lsf_variance_px2(row_values) -> float:
    """The variance (px^2) of a row's line spread function -- its finite
    difference, taken as a distribution over the half-integer positions
    -- for a row that runs from one level to another."""
    import numpy as np

    lsf = np.diff(np.asarray(row_values, dtype=np.float64))
    total = float(lsf.sum())
    if total == 0.0:
        raise MotionBlurError("the row has no edge to measure a streak on")
    x = np.arange(len(lsf)) + 0.5
    mean = float((x * lsf).sum() / total)
    return float((((x - mean) ** 2) * lsf).sum() / total)


def streak_length_px(blurred_row, reference_row, taps: int) -> float:
    """The streak length read off a blurred edge row: sqrt(12 x (var_blurred
    - var_reference) / ((N + 1) / (N - 1))). A box of length L has
    variance L^2 / 12; N equally spaced taps over it have (L^2 / 12) x
    (N + 1) / (N - 1) (the discrete uniform distribution's variance), and
    the unblurred edge's own variance rides on top: both are removed,
    both stated. Exact for the continuous model; the bilinear taps'
    own spread (up to 1/4 px^2 each) is what is left, so the estimate
    holds within 0.25 px for streaks of 2 px and longer (measured)."""
    if taps < 2:
        raise MotionBlurError(f"a streak needs at least two taps, not {taps}")
    factor = (taps + 1.0) / (taps - 1.0)
    difference = lsf_variance_px2(blurred_row) - lsf_variance_px2(reference_row)
    return math.sqrt(max(12.0 * difference / factor, 0.0))


def check_motion_blur_block(block: Mapping[str, Any]) -> Dict[str, Any]:
    """A profile's ``motion_blur`` block, shape-checked: model (one of
    BLUR_MODELS), dt_s > 0, engine_accumulation a bool. Unknown keys refuse."""
    if not isinstance(block, Mapping):
        raise MotionBlurError(f"the motion_blur block must be a mapping, not {block!r}")
    unknown = sorted(set(block) - {"model", "dt_s", "engine_accumulation"})
    if unknown:
        raise MotionBlurError(f"the motion_blur block carries unknown keys {unknown}")
    model = block.get("model")
    if model not in BLUR_MODELS:
        raise MotionBlurError(f"motion blur model {model!r} is not modelled ({BLUR_MODELS})")
    dt = block.get("dt_s", DEFAULT_DT_S)
    if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(dt) or dt <= 0.0:
        raise MotionBlurError(f"dt_s must be a positive number of seconds, not {dt!r}")
    accumulation = block.get("engine_accumulation", False)
    if not isinstance(accumulation, bool):
        raise MotionBlurError(f"engine_accumulation must be true or false, not {accumulation!r}")
    return {"model": model, "dt_s": float(dt), "engine_accumulation": accumulation}


def engine_accumulation_of(engine_record: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The render.json frame record's ``accumulation`` block when it says
    the engine accumulated more than one sub-exposure (k > 1), else None."""
    if not isinstance(engine_record, Mapping):
        return None
    block = engine_record.get("accumulation")
    if isinstance(block, Mapping) and isinstance(block.get("k"), (int, float)) and int(block["k"]) > 1:
        return {"k": int(block["k"]), "t0_s": block.get("t0_s"), "t1_s": block.get("t1_s")}
    return None


def engine_accumulation_block(accumulation: Mapping[str, Any], exposure_s: float) -> Dict[str, Any]:
    """The ``sensing.motion_blur`` block for a frame the ENGINE blurred
    by accumulation (S4): the Python integral is not applied."""
    return {"model": BLUR_MODELS[0], "applied_by": APPLIED_BY_ENGINE,
            "exposure_s": float(exposure_s), "k": int(accumulation["k"]),
            "t0_s": accumulation.get("t0_s"), "t1_s": accumulation.get("t1_s"),
            "taps": None, "blur_px_max": None, "blur_px_mean": None,
            "window": "the engine's sub-exposure captures between t0_s and t1_s",
            "note": "the bundle declares an accumulation of k > 1 sub-exposures, so the Python "
                    "integral was NOT applied (blurring twice would be a lie); the streak length "
                    "is graded by blur_vs_flow when a flow pass exists",
            "references": list(REFERENCES)}


def blur_record(block: Mapping[str, Any], null_max_abs_difference: float):
    """The ``sensing.motion_blur`` AppliedVariable (record 2): value = the
    largest streak (px); readback = the tap count against the rule
    max(3, ceil(2 L)) (exact); null test = exposure 0 leaves the frame
    identical (``bounded``, threshold 0, measured)."""
    from ..records import AppliedVariable, Model, NullTest, Readback

    taps = block.get("taps")
    length = block.get("blur_px_max")
    expected = tap_count(float(length)) if length is not None else None
    return AppliedVariable(
        name="sensing.motion_blur", value=length, unit="px", source="user",
        model_name="velocity-line integral over the exposure, N = max(3, ceil(2 |f| t_exp / dt)) symmetric taps",
        parameters={k: block.get(k) for k in ("model", "applied_by", "exposure_s", "dt_s", "taps",
                                              "blur_px_max", "blur_px_mean", "flow_source", "window",
                                              "sub_pixel", "sub_pixel_taps", "k", "t0_s", "t1_s")},
        references=tuple(block["references"]),
        frame_keys=(),
        null_test=NullTest(
            quantity="max |frame at exposure 0 - frame|", unit="1",
            with_value=float(null_max_abs_difference), without_value=0.0, threshold=0.0, kind="bounded",
            note="an exposure of 0 s leaves the frame identical; measured on the synthetic frame"),
        not_claimed=("linear motion per pixel: not occlusion-aware, no rotation within the exposure",
                     "streaks under 2 px: the three bilinear taps are wider than the streak (stated)",
                     "the flow is the caller's (a constant until S2's flow pass); per-object streaks "
                     "are not separated",
                     "engine accumulation (S4) is recorded from the bundle, never applied here"),
        std="McGuire et al. 2012; Haeberli & Akeley 1990 [unverified here]",
        readback=(None if taps is None else
                  Readback(property="taps", value=float(taps), written=float(expected),
                           tolerance=0.0, tolerance_kind="absolute",
                           basis="the tap count the integral used equals max(3, ceil(2 L)) for its own L")),
        model=Model(name="velocity_line", standard="McGuire et al. 2012 (linear case)", version="S1",
                          parameters={"taps": taps, "dt_s": block.get("dt_s"), "exposure_s": block.get("exposure_s")},
                          references=tuple(block["references"])),
    )
