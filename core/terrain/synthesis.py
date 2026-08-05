"""Procedural terrain by spectral synthesis, then erosion.

§3.2 asks for spectral synthesis rather than ad-hoc fractal noise, and the
reason is the research design rather than the look: a Fourier construction lets
you *prescribe* the statistics -- roughness exponent, RMS height, autocorrelation
length -- so terrain becomes a controllable independent variable instead of
whatever a noise function happened to produce.

The synthesis has three stages, in order.

1. **Spectral construction.** Filter white noise by a power spectrum
   P(k) ~ k^(-beta). For a self-affine surface with Hurst exponent H, the 2-D
   spectral exponent is beta = 2H + 2 (Voss 1985; Turcotte, *Fractals and Chaos
   in Geology and Geophysics*, ch. 7). H = 0.7-0.9 is the range measured for real
   topography, so that is the default.

2. **Thermal erosion.** Material on a slope steeper than the angle of repose
   slides. Real terrain rarely sustains past about 40 degrees, and the previous
   build produced near-vertical faces; this enforces the limit physically --
   material is moved downhill and conserved -- rather than by clipping the
   height, which would flatten peaks instead of building talus.

3. **Hydraulic erosion.** Stream-power incision, E = K * A^m * S^n, with A the
   upslope drainage area from a D8 flow routing (Howard & Kerby 1983; Whipple &
   Tucker 1999). This is what carves drainage networks, and drainage networks
   are what the eye recognises as real terrain -- fractal noise without them
   always reads as alien.

There is deliberately **no corridor carve**. §8 is explicit that a dead-straight
path to the horizon is the single most game-like element possible.

Determinism
-----------
Every stage is seeded from one explicit generator. Nothing here touches global
RNG state, so the same seed always produces a bit-identical raster (§7.4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import numpy as np

from .heightfield import Georeference, Heightfield

#: Hurst exponent measured for real topography. Turcotte ch. 7 reports
#: H ~ 0.7-0.9 across a wide range of landscapes.
DEFAULT_HURST = 0.8
#: Angle of repose for fractured rock and scree. Above this, material slides.
DEFAULT_REPOSE_DEG = 38.0
#: Stream-power exponents. m/n ~ 0.5 is the concavity of real river profiles.
STREAM_POWER_M = 0.5
STREAM_POWER_N = 1.0

TURCOTTE = "Turcotte, Fractals and Chaos in Geology and Geophysics, ch. 7"
STREAM_POWER = "Howard & Kerby 1983; Whipple & Tucker 1999 (stream-power incision)"


@dataclass(frozen=True)
class TerrainStatistics:
    """The prescribed statistics, which are the experimental variables.

    **Normalise on slope, not height.** RMS height and an outer-scale cutoff
    over-constrain a self-affine surface: suppressing the long wavelengths while
    holding total variance fixed forces that variance into the short ones, and
    the surface gets steep at pixel scale. Measured here, the same H = 0.8
    surface at 250 m RMS height gave a median slope of 23 degrees with no cutoff
    and 40 degrees with a 4 km cutoff -- from a parameter that was supposed to
    describe the *longest* wavelength present.

    RMS slope is the statistic Gate 4 checks and the one that decides whether
    terrain is physically plausible, so it is the primary control. Prescribing
    ``rms_height_m`` instead is still supported for the case where relief is the
    variable of interest, but only one of the two may be set.
    """

    hurst: float = DEFAULT_HURST
    #: Primary control. Real mountainous terrain sits around 15-30 degrees.
    rms_slope_deg: Optional[float] = 20.0
    #: Alternative control, for when relief rather than steepness is the
    #: independent variable. Mutually exclusive with ``rms_slope_deg``.
    rms_height_m: Optional[float] = None
    #: Longest wavelength present, in metres. Sets the autocorrelation length.
    outer_scale_m: Optional[float] = None
    repose_deg: float = DEFAULT_REPOSE_DEG
    erosion_iterations: int = 60
    erosion_strength: float = 0.35

    def __post_init__(self) -> None:
        if (self.rms_slope_deg is None) == (self.rms_height_m is None):
            raise ValueError(
                "prescribe exactly one of rms_slope_deg or rms_height_m: "
                "setting both over-constrains the surface and setting neither "
                "leaves its amplitude undefined"
            )
        if self.rms_slope_deg is not None and not 0 < self.rms_slope_deg < 60:
            raise ValueError(
                f"rms_slope_deg {self.rms_slope_deg} is outside any plausible "
                f"landscape; real terrain rarely sustains past 40 degrees"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hurst": self.hurst,
            "spectral_beta": 2.0 * self.hurst + 2.0,
            "rms_slope_deg": self.rms_slope_deg,
            "rms_height_m": self.rms_height_m,
            "outer_scale_m": self.outer_scale_m,
            "repose_deg": self.repose_deg,
            "erosion_iterations": self.erosion_iterations,
            "erosion_strength": self.erosion_strength,
            "spectral_standard": TURCOTTE,
            "erosion_standard": STREAM_POWER,
        }


def rms_slope_deg(z: np.ndarray, pixel_size_m: float) -> float:
    """RMS of the terrain gradient magnitude, in degrees."""
    dzdy, dzdx = np.gradient(z, pixel_size_m)
    return float(np.degrees(np.arctan(np.sqrt((dzdx ** 2 + dzdy ** 2).mean()))))


def spectral_surface(
    size: int,
    hurst: float,
    rng: np.random.Generator,
    pixel_size_m: float,
    outer_scale_m: Optional[float] = None,
) -> np.ndarray:
    """A self-affine surface with a prescribed spectral exponent.

    Built by filtering white noise in the Fourier domain, which gives exact
    control of the spectrum -- unlike summed octaves of value noise, where the
    resulting exponent is an emergent property of the octave weights.
    """
    beta = 2.0 * hurst + 2.0

    # Radial wavenumber grid, in cycles per metre.
    fx = np.fft.fftfreq(size, d=pixel_size_m)
    fy = np.fft.fftfreq(size, d=pixel_size_m)
    kx, ky = np.meshgrid(fx, fy, indexing="xy")
    k = np.hypot(kx, ky)
    k[0, 0] = 1.0                      # avoid division by zero at DC

    amplitude = k ** (-beta / 2.0)
    amplitude[0, 0] = 0.0              # zero mean

    if outer_scale_m is not None and outer_scale_m > 0:
        # Flatten the spectrum below the outer scale, so the surface has a
        # finite autocorrelation length instead of unbounded long-wavelength
        # power. This is the difference between a landscape and a slow ramp.
        k_outer = 1.0 / outer_scale_m
        amplitude *= 1.0 / (1.0 + (k_outer / np.maximum(k, 1e-12)) ** 2)

    # Hermitian-symmetric noise, so the inverse transform is real by
    # construction rather than by discarding an imaginary part.
    noise = rng.normal(size=(size, size))
    spectrum = np.fft.fft2(noise) * amplitude
    surface = np.real(np.fft.ifft2(spectrum))
    return surface - surface.mean()


def thermal_erosion(z: np.ndarray, pixel_size_m: float, repose_deg: float,
                    iterations: int = 40) -> np.ndarray:
    """Move material off slopes steeper than the angle of repose.

    Mass-conserving: what leaves a cell arrives in its downhill neighbours, so
    peaks grow talus rather than being flattened. Clipping the height instead
    would cap the mountains, which is not what a scree slope does.
    """
    z = z.copy()
    max_drop = math.tan(math.radians(repose_deg)) * pixel_size_m
    # Four-neighbour scheme; the diagonals are covered over several iterations
    # and including them makes the talus anisotropic on a square grid.
    shifts = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for _ in range(iterations):
        total_excess = np.zeros_like(z)
        deltas = []
        for dy, dx in shifts:
            neighbour = np.roll(np.roll(z, dy, axis=0), dx, axis=1)
            excess = np.maximum(z - neighbour - max_drop, 0.0)
            deltas.append((dy, dx, excess))
            total_excess += excess
        if total_excess.max() <= 1e-9:
            break
        # Move half the excess, apportioned between the downhill neighbours.
        with np.errstate(divide="ignore", invalid="ignore"):
            for dy, dx, excess in deltas:
                share = np.where(total_excess > 0, excess / total_excess, 0.0)
                moved = 0.5 * share * np.minimum(total_excess, max_drop * 4.0)
                z -= moved
                z += np.roll(np.roll(moved, -dy, axis=0), -dx, axis=1)
    return z


def flow_accumulation(z: np.ndarray) -> np.ndarray:
    """D8 upslope drainage area, in cells.

    Cells are processed from highest to lowest, so each one has already
    received everything that drains into it before it passes water on. That
    ordering is what makes a single pass correct.
    """
    height, width = z.shape
    accumulation = np.ones_like(z, dtype=np.float64)
    order = np.argsort(z, axis=None)[::-1]

    neighbours = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1), (0, 1),
                  (1, -1), (1, 0), (1, 1)]
    for flat in order:
        r, c = divmod(int(flat), width)
        here = z[r, c]
        steepest = 0.0
        target = None
        for dr, dc in neighbours:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < height and 0 <= cc < width):
                continue
            distance = math.hypot(dr, dc)
            drop = (here - z[rr, cc]) / distance
            if drop > steepest:
                steepest, target = drop, (rr, cc)
        if target is not None:
            accumulation[target] += accumulation[r, c]
    return accumulation


def hydraulic_erosion(
    z: np.ndarray,
    pixel_size_m: float,
    iterations: int = 60,
    strength: float = 0.35,
) -> np.ndarray:
    """Stream-power incision: E = K * A^m * S^n.

    Drainage networks, not a look. Fractal noise without them reads as alien
    however carefully its spectrum is tuned.
    """
    z = z.copy()
    for _ in range(iterations):
        area = flow_accumulation(z)
        dzdy, dzdx = np.gradient(z, pixel_size_m)
        slope = np.hypot(dzdx, dzdy)
        incision = (area ** STREAM_POWER_M) * (slope ** STREAM_POWER_N)
        peak = incision.max()
        if peak <= 0:
            break
        # Normalised so `strength` is metres of incision at the most active
        # cell per iteration, rather than an opaque coefficient.
        z -= incision * (strength / peak)
    return z


def generate(
    size: int = 512,
    pixel_size_m: float = 30.0,
    statistics: Optional[TerrainStatistics] = None,
    seed: int = 0,
    origin_x_m: float = 0.0,
    origin_y_m: float = 0.0,
    crs: str = "EPSG:32633",
    base_elevation_m: float = 500.0,
    name: str = "procedural",
) -> Heightfield:
    """Synthesise terrain into the same raster format a real DEM bakes to.

    The return type is the point: :class:`~core.terrain.heightfield.Heightfield`,
    identical to what :mod:`core.terrain.dem` produces, so the ground callback
    cannot tell the two apart (§3.2).
    """
    stats = statistics or TerrainStatistics()
    rng = np.random.default_rng(seed)

    surface = spectral_surface(size, stats.hurst, rng, pixel_size_m,
                               stats.outer_scale_m)
    # Normalise before eroding, so the erosion parameters act on a known
    # surface rather than on arbitrary units.
    if stats.rms_slope_deg is not None:
        current = rms_slope_deg(surface, pixel_size_m)
        if current > 0:
            surface *= math.tan(math.radians(stats.rms_slope_deg)) / math.tan(
                math.radians(current)
            )
    elif surface.std() > 0:
        surface *= stats.rms_height_m / surface.std()

    surface = thermal_erosion(surface, pixel_size_m, stats.repose_deg)
    surface = hydraulic_erosion(surface, pixel_size_m,
                                stats.erosion_iterations, stats.erosion_strength)
    # Erosion removes material, so re-enforce the repose limit on the freshly
    # cut valley walls.
    surface = thermal_erosion(surface, pixel_size_m, stats.repose_deg,
                              iterations=20)

    elevations = surface - surface.min() + base_elevation_m
    georeference = Georeference(
        crs=crs,
        origin_x_m=origin_x_m,
        origin_y_m=origin_y_m + (size - 1) * pixel_size_m,
        pixel_size_m=pixel_size_m,
    )
    return Heightfield.from_elevations(
        elevations, georeference, name=name,
        provenance={
            "producer": "spectral synthesis",
            "seed": seed,
            "size": size,
            "pixel_size_m": pixel_size_m,
            "statistics": stats.to_dict(),
        },
    )
