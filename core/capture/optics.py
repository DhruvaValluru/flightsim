"""The optics: a diffraction-limited MTF with a Gaussian aberration term,
its point-spread kernel, and the slanted-edge measurement that checks
the kernel did what its MTF says (S1; gap S2; ADVANCEMENTS_BLUEPRINT
section 3, "Models and parameters").

The model, stated once. For a circular pupil at f-number N and
wavelength lambda the incoherent diffraction MTF is (Goodman,
Introduction to Fourier Optics, ch. 6)

    MTF_diff(nu) = (2 / pi) [acos(nu / nu_c) - (nu / nu_c) sqrt(1 - (nu / nu_c)^2)],
    nu_c = 1 / (lambda N)   (cycles per metre on the sensor), 0 beyond nu_c,

and residual aberrations are carried as one Gaussian blur of standard
deviation sigma on the sensor, MTF_ab(nu) = exp(-2 pi^2 sigma^2 nu^2).
The system MTF is the product. The kernel is the inverse FFT of that
MTF sampled on the pixel grid's frequencies (a real, even function, so
the PSF is real), shifted to the centre of an odd support, clipped at
zero (the truncation's ringing, stated) and normalised to energy 1; its
sha256 and the predicted MTF50 (the frequency at which the analytic MTF
falls to one half, in cycles per pixel) are recorded with it. The
kernel is SHIFT-INVARIANT: one PSF for the whole frame.

Measured, not asserted: :func:`esfr_mtf50` is an ISO 12233:2023 e-SFR
written from the definition (a slanted edge's sub-pixel crossings fitted
by a line; the pixels projected onto the edge normal and binned at a
quarter pixel into the edge spread function; its derivative windowed
and Fourier transformed) and tests/test_optics.py shows the MTF50 it
measures on a synthetic edge blurred by the kernel agrees with the
analytic one within 5 % in both regimes (aberration-dominated at the
default 28.1 um pitch, diffraction-dominated at a 2 um pitch; a
kernel whose MTF is still above 0.05 at Nyquist aliases on the grid,
is flagged ``aliased`` and makes no such claim). The
verifier's own e-SFR (core/capture/verify.py, ``psf_slanted_edge``) is
a second implementation of the same definition and shares no code.

What is NOT claimed: field-dependent aberrations (one Gaussian, one
kernel), chromatic aberration (one wavelength), the pixel aperture (the
kernel is applied to point-sampled pixels; a sensor's own aperture MTF
rides on the profile's other stages), flare, and -- at the default
pixel pitch, where the diffraction cutoff of 6.4 cycles per pixel sits
far above Nyquist -- any diffraction effect a pixel could see: the
kernel there is the Gaussian term alone and the block says
``sub_pixel_diffraction``.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

REFUSAL_OPTICS = "sensing.optics"
OPTICS_MODELS = ("diffraction_gaussian",)
DEFAULT_WAVELENGTH_NM = 550.0
#: The smallest odd support a kernel is built on, and the largest (a
#: 129-pixel PSF would be a lens this repo has no profile for).
MIN_SUPPORT_PX = 7
MAX_SUPPORT_PX = 129
#: The e-SFR's oversampling of the edge spread function (ISO 12233 bins
#: at a quarter pixel).
ESFR_OVERSAMPLE = 4
#: Below this pixel-normalised cutoff-to-Nyquist ratio the diffraction
#: term changes the sampled kernel by less than the ADC resolves; the
#: block then says the diffraction is sub-pixel.
SUB_PIXEL_CUTOFF_RATIO = 4.0
#: A system MTF still above this at Nyquist cannot be represented on the
#: pixel grid: the sampled kernel aliases and the e-SFR agreement is not
#: claimed (measured: sigma = 0.5 px, MTF 0.29 at Nyquist, 4.7 % off).
ALIASING_MTF_AT_NYQUIST = 0.05

REFERENCES = (
    "Goodman, Introduction to Fourier Optics, 3rd ed., ch. 6 (incoherent OTF of a circular pupil)",
    "ISO 12233:2023 (e-SFR, slanted edge) [unverified here]",
    "docs/ADVANCEMENTS_BLUEPRINT.md section 3, models and parameters",
)


class OpticsError(Exception):
    """An optics block that cannot be applied, refused by name (``sensing.optics``)."""

    constraint = "sensing.optics"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{REFUSAL_OPTICS}: {message}")


def _positive(value, what: str) -> float:
    if isinstance(value, bool):
        raise OpticsError(f"{what} must be a positive number, not {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise OpticsError(f"{what} must be a positive number, not {value!r}")
    if not math.isfinite(number) or number <= 0.0:
        raise OpticsError(f"{what} must be a positive number, not {value!r}")
    return number


# -- the MTF ------------------------------------------------------------------------

def diffraction_cutoff(wavelength_m: float, f_number: float) -> float:
    """nu_c = 1 / (lambda N), cycles per metre."""
    return 1.0 / (_positive(wavelength_m, "the wavelength") * _positive(f_number, "the f-number"))


def diffraction_mtf(nu, wavelength_m: float, f_number: float):
    """(2/pi)[acos(x) - x sqrt(1 - x^2)], x = nu / nu_c, 0 beyond the cutoff.
    ``nu`` may be an array (cycles per metre)."""
    import numpy as np

    x = np.clip(np.abs(np.asarray(nu, dtype=np.float64)) / diffraction_cutoff(wavelength_m, f_number),
                0.0, 1.0)
    return (2.0 / math.pi) * (np.arccos(x) - x * np.sqrt(1.0 - x * x))


def gaussian_mtf(nu, sigma_m: float):
    """exp(-2 pi^2 sigma^2 nu^2); sigma 0 is the identity."""
    import numpy as np

    s = float(sigma_m)
    if s < 0.0 or not math.isfinite(s):
        raise OpticsError(f"the aberration sigma must be a non-negative length, not {sigma_m!r}")
    return np.exp(-2.0 * math.pi ** 2 * s * s * np.square(np.asarray(nu, dtype=np.float64)))


def system_mtf(nu, wavelength_m: float, f_number: float, sigma_m: float):
    return diffraction_mtf(nu, wavelength_m, f_number) * gaussian_mtf(nu, sigma_m)


def mtf50_cyc_per_m(wavelength_m: float, f_number: float, sigma_m: float) -> float:
    """The analytic MTF50 by bisection on the monotone system MTF."""
    lo, hi = 0.0, diffraction_cutoff(wavelength_m, f_number)
    if float(system_mtf(hi, wavelength_m, f_number, sigma_m)) >= 0.5:
        return hi
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if float(system_mtf(mid, wavelength_m, f_number, sigma_m)) >= 0.5:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# -- the kernel ----------------------------------------------------------------------

def default_support_px(wavelength_m: float, f_number: float, sigma_m: float, pitch_m: float) -> int:
    """An odd support holding three sigma of the Gaussian and three Airy
    radii (1.22 lambda N) on each side, clamped to the stated bounds."""
    half = 3.0 * sigma_m / pitch_m + 3.0 * 1.22 * wavelength_m * f_number / pitch_m
    support = 2 * int(math.ceil(half)) + 1
    return int(max(MIN_SUPPORT_PX, min(MAX_SUPPORT_PX, support)))


def kernel(wavelength_m: float, f_number: float, sigma_m: float, pitch_m: float,
           support_px: Optional[int] = None):
    """The PSF kernel (support x support float64, energy 1) by inverse
    FFT of the system MTF on the support's frequency grid, and its
    metadata. Refuses ``sensing.optics`` for an even or out-of-range
    support."""
    import numpy as np

    wavelength = _positive(wavelength_m, "the wavelength")
    n_number = _positive(f_number, "the f-number")
    pitch = _positive(pitch_m, "the pixel pitch")
    sigma = float(sigma_m)
    if sigma < 0.0 or not math.isfinite(sigma):
        raise OpticsError(f"the aberration sigma must be a non-negative length, not {sigma_m!r}")
    support = int(support_px) if support_px is not None else default_support_px(wavelength, n_number, sigma, pitch)
    if support % 2 == 0 or not MIN_SUPPORT_PX <= support <= MAX_SUPPORT_PX:
        raise OpticsError(f"the kernel support must be an odd number of pixels in "
                          f"{MIN_SUPPORT_PX}..{MAX_SUPPORT_PX}, not {support_px!r}")
    freq = np.fft.fftfreq(support, d=pitch)                # cycles per metre
    fx, fy = np.meshgrid(freq, freq)
    radial = np.sqrt(fx * fx + fy * fy)
    mtf = system_mtf(radial, wavelength, n_number, sigma)
    psf = np.real(np.fft.ifft2(mtf))
    psf = np.fft.fftshift(psf)
    negative_energy = float(-psf[psf < 0.0].sum())
    psf = np.clip(psf, 0.0, None)
    total = float(psf.sum())
    if total <= 0.0:
        raise OpticsError("the kernel has no energy; the MTF sampled to nothing")
    psf = psf / total                                        # energy 1
    cutoff_px = diffraction_cutoff(wavelength, n_number) * pitch
    nyquist = float(system_mtf(0.5 / pitch, wavelength, n_number, sigma))
    meta = {
        "model": OPTICS_MODELS[0],
        "wavelength_nm": wavelength * 1e9,
        "f_number": n_number,
        "sigma_um": sigma * 1e6,
        "pixel_pitch_um": pitch * 1e6,
        "support_px": support,
        "cutoff_cyc_per_px": cutoff_px,
        "mtf50_predicted_cyc_per_px": mtf50_cyc_per_m(wavelength, n_number, sigma) * pitch,
        "kernel_energy": float(psf.sum()),
        "kernel_sha256": kernel_sha256(psf),
        "clipped_negative_energy": negative_energy,
        "mtf_at_nyquist": nyquist,
        "sub_pixel_diffraction": bool(cutoff_px >= SUB_PIXEL_CUTOFF_RATIO * 0.5),
        "aliased": bool(nyquist > ALIASING_MTF_AT_NYQUIST),
    }
    return psf, meta


def kernel_sha256(psf) -> str:
    """The digest of the kernel's float64 little-endian bytes, row-major."""
    import numpy as np

    return hashlib.sha256(np.ascontiguousarray(psf, dtype="<f8").tobytes()).hexdigest()


def convolve(frame, psf):
    """The frame (H x W or H x W x C floats) convolved with the kernel,
    'same' size, edges reflected, by FFT (numpy only)."""
    import numpy as np

    image = np.asarray(frame, dtype=np.float64)
    psf = np.asarray(psf, dtype=np.float64)
    k = psf.shape[0]
    pad = k // 2
    squeeze = image.ndim == 2
    if squeeze:
        image = image[..., None]
    padded = np.pad(image, ((pad, pad), (pad, pad), (0, 0)), mode="reflect")
    height, width = padded.shape[0], padded.shape[1]
    kernel_full = np.zeros((height, width), dtype=np.float64)
    kernel_full[:k, :k] = psf
    kernel_full = np.roll(kernel_full, (-pad, -pad), axis=(0, 1))
    spectrum = np.fft.rfft2(kernel_full)
    out = np.empty_like(padded)
    for c in range(padded.shape[2]):
        out[..., c] = np.fft.irfft2(np.fft.rfft2(padded[..., c]) * spectrum, s=(height, width))
    out = out[pad:pad + image.shape[0], pad:pad + image.shape[1]]
    return out[..., 0] if squeeze else out


# -- the slanted edge -------------------------------------------------------------------

def slanted_edge_image(width: int = 128, height: int = 96, angle_deg: float = 5.0,
                       low: float = 0.2, high: float = 0.8, centre_x: Optional[float] = None,
                       antialias: bool = False):
    """A synthetic edge: ``high`` right of a line through (centre_x, H/2)
    tilted ``angle_deg`` from vertical, ``low`` left of it. Point-sampled
    at pixel centres (the default: no pixel aperture, so the e-SFR of
    the unblurred edge is the sampling's own) or area-sampled."""
    import numpy as np

    cx = (width - 1) / 2.0 if centre_x is None else float(centre_x)
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    tilt = math.tan(math.radians(angle_deg))
    distance = (xs - (cx + tilt * (ys - (height - 1) / 2.0))) * math.cos(math.radians(angle_deg))
    if antialias:
        coverage = np.clip(distance + 0.5, 0.0, 1.0)
    else:
        coverage = (distance >= 0.0).astype(np.float64)
    return low + (high - low) * coverage


def _edge_line(gray) -> Tuple[float, float]:
    """(intercept, slope): the edge's x as a + b y from each row's
    derivative centroid."""
    import numpy as np

    height, width = gray.shape
    rows, crossings = [], []
    for y in range(height):
        row = gray[y]
        derivative = np.abs(np.diff(row))
        total = float(derivative.sum())
        if total <= 0.0:
            continue
        xs = np.arange(width - 1) + 0.5
        crossings.append(float((xs * derivative).sum() / total))
        rows.append(float(y))
    if len(rows) < 3:
        raise OpticsError("the slanted edge has fewer than three rows with a transition")
    slope, intercept = np.polyfit(np.asarray(rows), np.asarray(crossings), 1)
    return float(intercept), float(slope)


def esfr(gray, oversample: int = ESFR_OVERSAMPLE):
    """(frequencies cycles/px, MTF) of a slanted-edge image by the ISO
    12233 e-SFR written from the definition: the edge fitted by a line,
    every pixel's signed distance to it along the edge NORMAL binned at
    1/oversample px into the ESF, the LSF as its finite difference under
    a Hann window, the MTF as the normalised magnitude spectrum."""
    import numpy as np

    image = np.asarray(gray, dtype=np.float64)
    if image.ndim == 3:
        image = image.mean(axis=2)
    intercept, slope = _edge_line(image)
    cos_theta = 1.0 / math.sqrt(1.0 + slope * slope)
    height, width = image.shape
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    distance = (xs - (intercept + slope * ys)) * cos_theta
    bins = np.floor(distance * oversample).astype(int)
    bins -= bins.min()
    counts = np.bincount(bins.ravel())
    sums = np.bincount(bins.ravel(), weights=image.ravel())
    filled = counts > 0
    esf_values = np.empty(len(counts))
    esf_values[filled] = sums[filled] / counts[filled]
    # An empty bin (none at a quarter pixel on a 5 degree edge of any
    # size this repo renders; stated) takes its neighbour's value.
    for i in np.flatnonzero(~filled):
        esf_values[i] = esf_values[i - 1] if i > 0 else esf_values[filled][0]
    lsf = np.diff(esf_values)
    window = np.hanning(len(lsf))
    spectrum = np.abs(np.fft.rfft(lsf * window))
    if spectrum[0] <= 0.0:
        raise OpticsError("the edge spread function has no step")
    mtf = spectrum / spectrum[0]
    frequencies = np.fft.rfftfreq(len(lsf), d=1.0 / oversample)   # cycles per pixel
    return frequencies, mtf


def mtf50_from_curve(frequencies, mtf) -> float:
    """The first frequency at which the curve crosses one half, linearly
    interpolated; the last frequency when it never does."""
    import numpy as np

    f = np.asarray(frequencies, dtype=np.float64)
    m = np.asarray(mtf, dtype=np.float64)
    below = np.flatnonzero(m < 0.5)
    if below.size == 0:
        return float(f[-1])
    i = int(below[0])
    if i == 0:
        return 0.0
    f0, f1, m0, m1 = f[i - 1], f[i], m[i - 1], m[i]
    return float(f0 + (0.5 - m0) * (f1 - f0) / (m1 - m0))


def esfr_mtf50(gray, oversample: int = ESFR_OVERSAMPLE) -> float:
    """MTF50 in cycles per pixel measured on a slanted-edge image."""
    frequencies, mtf = esfr(gray, oversample)
    return mtf50_from_curve(frequencies, mtf)


# -- the block and the record ---------------------------------------------------------------

def check_optics_block(block: Mapping[str, Any]) -> Dict[str, Any]:
    """A profile's ``optics`` block, shape-checked: model (one of
    OPTICS_MODELS), wavelength_nm > 0, f_number > 0 or null (the camera's
    aperture at application), sigma_um >= 0, support_px odd or null.
    Unknown keys refuse: a block is never guessed at."""
    if not isinstance(block, Mapping):
        raise OpticsError(f"the optics block must be a mapping, not {block!r}")
    known = {"model", "wavelength_nm", "f_number", "sigma_um", "support_px"}
    unknown = sorted(set(block) - known)
    if unknown:
        raise OpticsError(f"the optics block carries unknown keys {unknown}")
    model = block.get("model")
    if model not in OPTICS_MODELS:
        raise OpticsError(f"optics model {model!r} is not modelled ({OPTICS_MODELS})")
    out = {"model": model,
           "wavelength_nm": _positive(block.get("wavelength_nm", DEFAULT_WAVELENGTH_NM), "the wavelength"),
           "f_number": None if block.get("f_number") is None else _positive(block["f_number"], "the f-number"),
           "sigma_um": float(block.get("sigma_um", 0.0)),
           "support_px": None if block.get("support_px") is None else int(block["support_px"])}
    if not math.isfinite(out["sigma_um"]) or out["sigma_um"] < 0.0:
        raise OpticsError(f"the aberration sigma must be a non-negative number of um, not {block.get('sigma_um')!r}")
    if out["support_px"] is not None and (out["support_px"] % 2 == 0
                                          or not MIN_SUPPORT_PX <= out["support_px"] <= MAX_SUPPORT_PX):
        raise OpticsError(f"the kernel support must be an odd number of pixels in "
                          f"{MIN_SUPPORT_PX}..{MAX_SUPPORT_PX}, not {block.get('support_px')!r}")
    return out


def pixel_pitch_m(record: Mapping[str, Any]) -> float:
    """The sensor pitch from a frame record's sensor width and pixel count."""
    return float(record["sensor_width_mm"]) * 1e-3 / float(record["width_px"])


def optics_block(profile_optics: Mapping[str, Any], record: Mapping[str, Any],
                 aperture_f: float) -> Tuple[Any, Dict[str, Any]]:
    """(kernel, the per-camera ``sensing.optics`` block) for a profile's
    optics block at this record's pitch; the f-number is the block's or
    the camera's aperture."""
    clean = check_optics_block(profile_optics)
    n_number = clean["f_number"] if clean["f_number"] is not None else _positive(aperture_f, "the aperture")
    psf, meta = kernel(clean["wavelength_nm"] * 1e-9, n_number, clean["sigma_um"] * 1e-6,
                       pixel_pitch_m(record), clean["support_px"])
    meta["f_number_basis"] = ("the profile's own f-number" if clean["f_number"] is not None
                              else "the camera's exposure aperture")
    meta["shift_invariant"] = True
    meta["references"] = list(REFERENCES)
    return psf, meta


def optics_record(block: Mapping[str, Any], null_max_abs_difference: float,
                  measured_mtf50: Optional[float] = None, measured_basis: str = ""):
    """The ``sensing.optics`` AppliedVariable (record 2): value = the
    predicted MTF50; readback = the kernel's energy against 1 (exact to
    1e-12); null test = an absent block leaves the frame bit-identical
    (``bounded``, threshold 0, the measured max |difference| given)."""
    from ..records import AppliedVariable, Model, NullTest, Readback

    return AppliedVariable(
        name="sensing.optics", value=float(block["mtf50_predicted_cyc_per_px"]), unit="cycles/px",
        source="user", model="diffraction MTF x Gaussian aberration; kernel by inverse FFT, energy 1",
        parameters={k: block[k] for k in ("model", "wavelength_nm", "f_number", "f_number_basis",
                                          "sigma_um", "pixel_pitch_um", "support_px",
                                          "cutoff_cyc_per_px", "mtf50_predicted_cyc_per_px",
                                          "kernel_sha256", "kernel_energy",
                                          "clipped_negative_energy", "mtf_at_nyquist",
                                          "sub_pixel_diffraction", "aliased")}
        | {"mtf50_measured_cyc_per_px": measured_mtf50, "mtf50_measured_basis": measured_basis},
        references=tuple(block["references"]),
        frame_keys=(),
        null_test=NullTest(
            quantity="max |frame with the block absent - frame|", unit="1",
            with_value=float(null_max_abs_difference), without_value=0.0, threshold=0.0, kind="bounded",
            note="an absent optics block leaves the frame bit-identical; measured on the synthetic frame"),
        not_claimed=("shift-invariant: one kernel for the whole field",
                     "one wavelength: no chromatic aberration",
                     "no pixel aperture in the kernel (point-sampled pixels)",
                     "no flare; the truncated kernel's negative ringing is clipped and its energy recorded"),
        std="Goodman, Introduction to Fourier Optics, ch. 6; ISO 12233:2023 [unverified here]",
        readback=Readback(property="kernel_energy", value=float(block["kernel_energy"]), written=1.0,
                          tolerance=1e-12, tolerance_kind="absolute",
                          basis="the normalised kernel sums to 1 to float64 round-off"),
        model_block=Model(name="diffraction_gaussian PSF", standard="Goodman ch. 6",
                          version="S1", parameters={k: block[k] for k in ("wavelength_nm", "f_number", "sigma_um")},
                          references=tuple(block["references"])),
    )
