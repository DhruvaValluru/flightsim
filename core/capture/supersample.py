"""Supersampled beauty: the Python mirror of FlightSimSupersample.cpp's pure block.

The commandlet's ``-supersample=N`` (``-quality=beauty`` only, N from 1 to
4) renders the beauty into a target N times the output size per axis and
reduces the frame read back from it to the output size before the PNG is
written. The reduction is an exact N x N box in linear light: each 8-bit
sRGB byte is decoded, the N^2 values of the block are summed row by row,
left to right, divided by N^2, and encoded to the nearest byte. This
module is the same arithmetic, number for number (tests/test_supersample.py
compiles the C++ block and compares), plus what the C++ does not ship:

* :func:`lanczos3_downsample` -- the separable Lanczos-3 the lane weighed
  against the box, kept only so the test can MEASURE why the box won;
* :func:`edge_report` -- how far from a synthetic edge the reduced frame
  differs from what a label mask (pixel-centre sampled at the output size)
  says, and where its 50 % crossing sits.

The decision (recorded in docs/visual/PROBE_LOG.md "## supersample"): the
box changes only the output pixels an edge crosses, and its crossing sits
on the geometric edge to within the 1/(2N) px quantisation of the internal
samples; the Lanczos-3 rings out to about 2.5 output px, so it would have
to be listed in render.json ``pixel_moving_effects``. The box is not
pixel-moving and is recorded in ``beauty_samples`` instead.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

MIN_FACTOR = 1
MAX_FACTOR = 4
FALLBACK_MAX_TEXTURE_SIDE = 16384
#: UNCALIBRATED, the C++ RenderBytesPerPixel (see the C++ comment for the sum).
RENDER_BYTES_PER_PIXEL = 112.0
#: UNCALIBRATED, the C++ TsrHistoryBytesPerPixel (per TSR history pixel).
TSR_HISTORY_BYTES_PER_PIXEL = 24.0
#: UNCALIBRATED, the C++ VramBudgetMiBDefault.
VRAM_BUDGET_MIB_DEFAULT = 7168.0
#: The commandlet's beauty r.TSR.History.ScreenPercentage
#: (RenderBeautyTsrHistoryScreenPercentage).
TSR_HISTORY_SCREEN_PERCENTAGE = 200.0
#: The factor the beauty contact sheet asks for when none is stated.
SHEET_DEFAULT_FACTOR = 2

CHECK_OK, CHECK_FACTOR, CHECK_SIZE, CHECK_VRAM = 0, 1, 2, 3
CHECK_WORDS = {CHECK_OK: "ok", CHECK_FACTOR: "factor", CHECK_SIZE: "size", CHECK_VRAM: "vram"}


def srgb_to_linear(encoded: float) -> float:
    return encoded / 12.92 if encoded <= 0.04045 else math.pow((encoded + 0.055) / 1.055, 2.4)


def build_tables() -> Tuple[List[float], List[float]]:
    """``decode[b]`` (byte b in linear light) and ``threshold[b]`` (the
    linear value half-way, in the encoded domain, between b and b + 1)."""
    decode = [srgb_to_linear(b / 255.0) for b in range(256)]
    threshold = [srgb_to_linear((b + 0.5) / 255.0) for b in range(255)]
    return decode, threshold


_DECODE, _THRESHOLD = build_tables()
_DECODE_NP = np.array(_DECODE, dtype=np.float64)
_THRESHOLD_NP = np.array(_THRESHOLD, dtype=np.float64)


def encode_linear(linear: float, threshold: Sequence[float] = _THRESHOLD) -> int:
    """The number of thresholds at or below ``linear`` (the C++ binary search)."""
    low, high = 0, 255
    while low < high:
        mid = (low + high) // 2
        if linear < threshold[mid]:
            high = mid
        else:
            low = mid + 1
    return low


def box_downsample_reference(data: Sequence[int], out_width: int, out_height: int,
                             factor: int, channels: int) -> List[int]:
    """The C++ loop, line for line, on a flat byte list."""
    if out_width < 1 or out_height < 1 or not MIN_FACTOR <= factor <= MAX_FACTOR or channels < 1:
        raise ValueError("render.supersample: bad box-filter arguments")
    in_width = out_width * factor
    count = float(factor) * factor
    out = [0] * (out_width * out_height * channels)
    for y in range(out_height):
        for x in range(out_width):
            for c in range(channels):
                total = 0.0
                for j in range(factor):
                    row = y * factor + j
                    for i in range(factor):
                        total += _DECODE[data[(row * in_width + x * factor + i) * channels + c]]
                out[(y * out_width + x) * channels + c] = encode_linear(total / count)
    return out


def box_downsample(image: np.ndarray, factor: int) -> np.ndarray:
    """``image`` (H*N, W*N[, C]) uint8 reduced to (H, W[, C]), bitwise the
    C++ result: the block is summed in the same order (rows, then columns,
    from 0.0), divided by N^2 and encoded by threshold count."""
    if not MIN_FACTOR <= int(factor) <= MAX_FACTOR:
        raise ValueError(f"render.supersample: factor {factor} is not from {MIN_FACTOR} to {MAX_FACTOR}")
    image = np.asarray(image)
    if image.dtype != np.uint8:
        raise ValueError("render.supersample: the box filter takes 8-bit sRGB")
    factor = int(factor)
    height, width = image.shape[0] // factor, image.shape[1] // factor
    if height * factor != image.shape[0] or width * factor != image.shape[1] or height < 1 or width < 1:
        raise ValueError(f"render.supersample: {image.shape[:2]} is not a multiple of {factor}")
    linear = _DECODE_NP[image]
    total = np.zeros((height, width) + image.shape[2:], dtype=np.float64)
    for j in range(factor):
        for i in range(factor):
            total = total + linear[j::factor, i::factor]
    mean = total / (float(factor) * factor)
    return np.searchsorted(_THRESHOLD_NP, mean, side="right").astype(np.uint8)


def box_downsample_linear(linear: np.ndarray, factor: int) -> np.ndarray:
    """The same box on a float (linear-light) image, unencoded: what the
    edge measurement reads."""
    linear = np.asarray(linear, dtype=np.float64)
    height, width = linear.shape[0] // factor, linear.shape[1] // factor
    total = np.zeros((height, width) + linear.shape[2:], dtype=np.float64)
    for j in range(factor):
        for i in range(factor):
            total = total + linear[j::factor, i::factor]
    return total / (float(factor) * factor)


def _lanczos3(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.sinc(x) * np.sinc(x / 3.0)
    return np.where(np.abs(x) < 3.0, out, 0.0)


def _lanczos_axis(linear: np.ndarray, factor: int, axis: int) -> np.ndarray:
    n_in = linear.shape[axis]
    n_out = n_in // factor
    weights = np.zeros((n_out, n_in))
    for o in range(n_out):
        centre = (o + 0.5) * factor          # the output centre in internal px
        taps = np.arange(n_in) + 0.5
        w = _lanczos3((taps - centre) / factor)
        weights[o] = w / w.sum()
    moved = np.moveaxis(linear, axis, 0)
    reduced = np.tensordot(weights, moved, axes=(1, 0))
    return np.moveaxis(reduced, 0, axis)


def lanczos3_downsample(linear: np.ndarray, factor: int) -> np.ndarray:
    """A separable Lanczos-3 reduction (kernel width 3 output px), centred
    on the same output centres as the box. Measurement only: not shipped."""
    return _lanczos_axis(_lanczos_axis(np.asarray(linear, dtype=np.float64), factor, 0), factor, 1)


def estimate_vram_mib(internal_width: int, internal_height: int,
                      tsr_history_screen_percentage: float = TSR_HISTORY_SCREEN_PERCENTAGE) -> float:
    pixels = float(internal_width) * internal_height
    history = tsr_history_screen_percentage / 100.0 if tsr_history_screen_percentage > 0.0 else 1.0
    total = pixels * (RENDER_BYTES_PER_PIXEL + TSR_HISTORY_BYTES_PER_PIXEL * history * history)
    return total / (1024.0 * 1024.0)


def check(factor: int, out_width: int, out_height: int,
          tsr_history_screen_percentage: float = TSR_HISTORY_SCREEN_PERCENTAGE,
          max_texture_side: int = FALLBACK_MAX_TEXTURE_SIDE,
          budget_mib: float = VRAM_BUDGET_MIB_DEFAULT) -> int:
    if not MIN_FACTOR <= factor <= MAX_FACTOR:
        return CHECK_FACTOR
    if out_width * factor > max_texture_side or out_height * factor > max_texture_side:
        return CHECK_SIZE
    if estimate_vram_mib(out_width * factor, out_height * factor,
                         tsr_history_screen_percentage) > budget_mib:
        return CHECK_VRAM
    return CHECK_OK


def refuse_reason(factor: int, out_width: int, out_height: int, **kwargs) -> Optional[str]:
    """``render.supersample: ...`` when the commandlet would refuse, else None."""
    verdict = check(factor, out_width, out_height, **kwargs)
    if verdict == CHECK_OK:
        return None
    if verdict == CHECK_FACTOR:
        return (f"render.supersample: -supersample={factor} is not a whole number from "
                f"{MIN_FACTOR} to {MAX_FACTOR}")
    if verdict == CHECK_SIZE:
        return (f"render.supersample: -supersample={factor} at {out_width}x{out_height} is over "
                f"the texture limit")
    estimate = estimate_vram_mib(out_width * factor, out_height * factor,
                                 kwargs.get("tsr_history_screen_percentage",
                                            TSR_HISTORY_SCREEN_PERCENTAGE))
    return (f"render.supersample: -supersample={factor} at {out_width}x{out_height} needs an "
            f"estimated {estimate:.0f} MiB of render targets, over the "
            f"{kwargs.get('budget_mib', VRAM_BUDGET_MIB_DEFAULT):.0f} MiB budget")


# -- the synthetic edge ---------------------------------------------------------

def half_plane(width: int, height: int, angle_deg: float, offset_px: float,
               scale: float = 1.0) -> np.ndarray:
    """1.0 where the pixel centre lies on the bright side of a straight edge,
    point-sampled at pixel centres of a ``width`` x ``height`` grid that is
    ``scale`` times finer than the OUTPUT grid. The edge is the line through
    the output frame's centre shifted by ``offset_px`` OUTPUT px along its
    normal, at ``angle_deg`` from vertical. This is how both the label mask
    (scale 1) and each supersampled beauty sample (scale N) see geometry."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    x_out = (xs + 0.5) / scale
    y_out = (ys + 0.5) / scale
    nx, ny = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    cx, cy = width / scale / 2.0, height / scale / 2.0
    signed = (x_out - cx) * nx + (y_out - cy) * ny - offset_px
    return (signed >= 0.0).astype(np.float64)


def signed_distance(width: int, height: int, angle_deg: float, offset_px: float) -> np.ndarray:
    """Each OUTPUT pixel centre's signed distance (output px) to the edge."""
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    nx, ny = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return (xs + 0.5 - width / 2.0) * nx + (ys + 0.5 - height / 2.0) * ny - offset_px


def edge_report(reduced: np.ndarray, mask: np.ndarray, angle_deg: float, offset_px: float,
                margin: int = 0, tol: float = 1.0 / 255.0) -> Dict[str, float]:
    """Where the reduced (linear, full-frame) image disagrees with the label
    mask of the same edge (:func:`half_plane` at the output size).

    ``reach_px``: the largest |distance| from the edge of an output pixel
    whose value differs from the mask's by more than ``tol`` (an 8-bit
    step): how far from the edge the filter changed what the label says.
    ``edge_px``: the largest error, along the edge's normal, of the edge's
    position read back from the image: per row (per column for a mostly
    horizontal edge) the bright run's length is the line's sum of values,
    which an area-preserving filter keeps, so the edge sits at the line's
    end minus that sum. ``overshoot``: how far the values leave [0, 1]
    (ringing). ``margin`` lines at the border are left out (a Lanczos'
    truncated taps)."""
    reduced = np.asarray(reduced, dtype=np.float64)
    height, width = reduced.shape[:2]
    distance = signed_distance(width, height, angle_deg, offset_px)
    inner = (slice(margin, height - margin or None), slice(margin, width - margin or None))
    differs = np.abs(reduced[inner] - mask[inner]) > tol
    reach = float(np.abs(distance[inner][differs]).max()) if differs.any() else 0.0
    nx, ny = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    cx, cy = width / 2.0, height / 2.0
    worst = 0.0
    if abs(nx) >= abs(ny):
        lines, length, along, across = reduced, width, nx, ny
        centre_along, centre_across = cx, cy
    else:
        lines, length, along, across = reduced.T, height, ny, nx
        centre_along, centre_across = cy, cx
    for k in range(margin, lines.shape[0] - margin):
        # where the edge crosses this line's middle, in pixels along it
        crossing = centre_along + (offset_px - (k + 0.5 - centre_across) * across) / along
        if not margin + 1 <= crossing <= length - margin - 1:
            continue
        bright = float(lines[k].sum())
        estimate = length - bright if along > 0 else bright
        worst = max(worst, abs(estimate - crossing) * abs(along))
    overshoot = float(max(0.0, reduced.max() - 1.0, -reduced.min()))
    return {"reach_px": reach, "edge_px": worst, "overshoot": overshoot}


def beauty_samples_record(factor: int, out_width: int, out_height: int,
                          tsr_history_screen_percentage: float = TSR_HISTORY_SCREEN_PERCENTAGE,
                          budget_mib: float = VRAM_BUDGET_MIB_DEFAULT,
                          max_texture_side: int = FALLBACK_MAX_TEXTURE_SIDE) -> Dict:
    """What FFlightSimSupersample::Record merges into render.json
    ``beauty_samples`` (same keys; the bases are the defaults')."""
    return {
        "spatial": factor * factor,
        "supersample": factor,
        "supersample_filter": "box" if factor > 1 else "none",
        "supersample_filter_space": ("linear light: the tonemapped sRGB 8-bit beauty decoded, "
                                     "averaged, re-encoded"),
        "supersample_pixel_moving": False,
        "supersample_alignment": ("exact integer box: output pixel x is the mean of internal "
                                  "pixels x*N .. x*N+N-1, whose centres average to the output centre"),
        "internal_width_px": out_width * factor,
        "internal_height_px": out_height * factor,
        "output_width_px": out_width,
        "output_height_px": out_height,
        "supersample_tsr_history_screen_percentage": tsr_history_screen_percentage,
        "supersample_vram_estimate_mib": estimate_vram_mib(out_width * factor, out_height * factor,
                                                           tsr_history_screen_percentage),
        "supersample_vram_budget_mib": budget_mib,
        "supersample_vram_budget_basis": "VramBudgetMiBDefault, UNCALIBRATED",
        "supersample_max_texture_side": max_texture_side,
        "supersample_max_texture_side_basis": "FallbackMaxTextureSide (the RHI reported none)",
    }
