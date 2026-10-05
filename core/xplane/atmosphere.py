"""The simulator's sky as a physical atmosphere, computed here.

The committed ``atmosphere`` shader archive (assets/physical_renders/
Resources/shaders/bin/spv/atmosphere.xsa) takes Bruneton's
``AtmosphereParameters`` block -- solar_irradiance, sun_angular_radius,
rayleigh_density / rayleigh_scattering, mie_density / mie_scattering /
mie_extinction / mie_phase_function_g, absorption_density /
absorption_extinction, ground_albedo, mu_s_min, bottom_radius /
top_radius plus two luminance-conversion members -- and precomputes
transmittance and scattering the way Bruneton & Neyret (2008) / Bruneton
(2017) do; ``scatter_render_atmosphere`` then draws the sky per pixel from
those tables, and the terrain pass lights the ground with ``u_E_sun``
times the transmittance (both read from the disassembled SPIR-V; see
assets/logic_reports/README.md). The parameter VALUES are set by CPU code
the decompilation does not contain. So this module runs the SAME model
with Bruneton's published Earth parameters (the reference demo's
``model.cc``, at 680 / 550 / 440 nm), stated as proposed defaults in every
record it writes, and integrates the two scattering terms numerically
instead of through lookup tables.

What it produces, for a sun direction and an observer altitude:

* the sun's irradiance at the ground after transmittance (the DIRECT
  light), in W m^-2 nm^-1 per RGB band;
* the sky radiance in any view direction from single Rayleigh + Mie
  scattering (no multiple-scattering orders: stated);
* the cosine-weighted sky irradiance on a horizontal surface (the
  AMBIENT light) and the radiance just above the horizon away from the
  sun (the HORIZON / fog colour);
* those three as 8-bit sRGB colours, white-balanced by the sun's own
  spectrum and normalised per quantity -- what the
  render takes through ``-xplane-direct``, ``-xplane-ambient`` and
  ``-xplane-horizon`` (colours only; intensities stay the look's, as the
  commandlet's contract says).

It replaces the decoded ``sky_colors_*.png`` tables (whose night and
full-day anchor angles were assumptions) by DAY. Single scattering gives
no light once the sun is below the horizon (the twilight sky is lit by
the scattering orders this module does not integrate), so below
:data:`MODEL_SUN_ELEVATION_FLOOR_DEG` the caller keeps the simulator's
own tables, which were measured for exactly those sun angles; the look
records which source each colour came from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Tuple

import numpy as np

#: Bruneton 2017 reference demo, model.cc, Earth: all lengths in metres,
#: coefficients per metre, RGB sampled at 680 / 550 / 440 nm. PROPOSED
#: defaults: the simulator's own values are CPU-set and not committed.
BRUNETON_PROVENANCE = ("Bruneton & Neyret 2008 / Bruneton 2017 reference "
                       "implementation (model.cc) Earth parameters at "
                       "680/550/440 nm; the simulator's atmosphere block "
                       "has this layout, its values are not committed")
WAVELENGTHS_NM = (680.0, 550.0, 440.0)
BOTTOM_RADIUS_M = 6360000.0
TOP_RADIUS_M = 6420000.0
#: Rayleigh: kRayleigh / lambda^4 with kRayleigh = 1.24062e-6 (lambda in um).
RAYLEIGH_SCATTERING_PER_M = tuple(1.24062e-6 / (wl / 1000.0) ** 4
                                  for wl in WAVELENGTHS_NM)
RAYLEIGH_SCALE_HEIGHT_M = 8000.0
#: Mie: Angstrom beta 5.328e-3, alpha 0 -> scattering = beta / H * albedo.
MIE_SCALE_HEIGHT_M = 1200.0
MIE_ANGSTROM_BETA = 5.328e-3
MIE_SINGLE_SCATTERING_ALBEDO = 0.9
MIE_SCATTERING_PER_M = MIE_ANGSTROM_BETA / MIE_SCALE_HEIGHT_M * MIE_SINGLE_SCATTERING_ALBEDO
MIE_EXTINCTION_PER_M = MIE_ANGSTROM_BETA / MIE_SCALE_HEIGHT_M
MIE_PHASE_G = 0.8
#: Ozone: 300 DU over a tent profile 10..25..40 km; cross sections at the
#: three bands give these peak extinctions (the demo's values).
OZONE_EXTINCTION_PER_M = (0.650e-6, 1.881e-6, 0.085e-6)
OZONE_LAYER_M = (10000.0, 25000.0, 40000.0)
#: Solar irradiance at the three bands, W m^-2 nm^-1 (the demo's table).
SOLAR_IRRADIANCE = (1.474000, 1.850400, 1.911980)
SUN_ANGULAR_RADIUS_RAD = 0.004675
GROUND_ALBEDO = 0.1
#: Below this sun elevation the single-scattering model is not trusted
#: (no multiple scattering: the twilight sky would go black); callers
#: fall back to the decoded sky tables there.
MODEL_SUN_ELEVATION_FLOOR_DEG = 3.0
#: Integration: samples along a ray and over the sky hemisphere.
RAY_SAMPLES = 48
SKY_AZIMUTH_SAMPLES = 24
SKY_ZENITH_SAMPLES = 12


@dataclass(frozen=True)
class Atmosphere:
    """One parameter set; the defaults are Bruneton's Earth."""

    bottom_radius_m: float = BOTTOM_RADIUS_M
    top_radius_m: float = TOP_RADIUS_M
    rayleigh_scattering: Tuple[float, float, float] = RAYLEIGH_SCATTERING_PER_M
    rayleigh_scale_height_m: float = RAYLEIGH_SCALE_HEIGHT_M
    mie_scattering: float = MIE_SCATTERING_PER_M
    mie_extinction: float = MIE_EXTINCTION_PER_M
    mie_scale_height_m: float = MIE_SCALE_HEIGHT_M
    mie_phase_g: float = MIE_PHASE_G
    ozone_extinction: Tuple[float, float, float] = OZONE_EXTINCTION_PER_M
    ozone_layer_m: Tuple[float, float, float] = OZONE_LAYER_M
    solar_irradiance: Tuple[float, float, float] = SOLAR_IRRADIANCE
    sun_angular_radius_rad: float = SUN_ANGULAR_RADIUS_RAD
    ground_albedo: float = GROUND_ALBEDO
    provenance: str = BRUNETON_PROVENANCE

    def record(self) -> Dict[str, object]:
        return {
            "model": "Bruneton precomputed-atmosphere parameter set, integrated "
                     "numerically (single scattering)",
            "provenance": self.provenance,
            "wavelengths_nm": list(WAVELENGTHS_NM),
            "bottom_radius_m": self.bottom_radius_m,
            "top_radius_m": self.top_radius_m,
            "rayleigh_scattering_per_m": [float(v) for v in self.rayleigh_scattering],
            "rayleigh_scale_height_m": self.rayleigh_scale_height_m,
            "mie_scattering_per_m": self.mie_scattering,
            "mie_extinction_per_m": self.mie_extinction,
            "mie_scale_height_m": self.mie_scale_height_m,
            "mie_phase_g": self.mie_phase_g,
            "ozone_extinction_per_m": list(self.ozone_extinction),
            "ozone_layer_m": list(self.ozone_layer_m),
            "solar_irradiance_w_m2_nm": list(self.solar_irradiance),
            "ground_albedo": self.ground_albedo,
            "multiple_scattering": "not integrated (single scattering only)",
        }


# -- geometry ---------------------------------------------------------------

def _ray_sphere_exit(r: float, mu: float, radius: float) -> float:
    """Distance along a ray from radius ``r`` with cosine ``mu`` to the
    zenith until it leaves a sphere of ``radius`` (the far intersection),
    or -1 when it never meets it."""
    disc = r * r * (mu * mu - 1.0) + radius * radius
    if disc < 0.0:
        return -1.0
    return -r * mu + math.sqrt(disc)


def _ray_sphere_entry(r: float, mu: float, radius: float) -> float:
    """The near intersection distance, or -1 when the ray misses."""
    disc = r * r * (mu * mu - 1.0) + radius * radius
    if disc < 0.0:
        return -1.0
    d = -r * mu - math.sqrt(disc)
    return d if d > 0.0 else -1.0


def _path_length(atm: Atmosphere, r: float, mu: float) -> Tuple[float, bool]:
    """How far a ray travels inside the atmosphere before it hits the
    ground or leaves the top, and whether it hits the ground."""
    ground = _ray_sphere_entry(r, mu, atm.bottom_radius_m)
    if ground > 0.0:
        return ground, True
    return _ray_sphere_exit(r, mu, atm.top_radius_m), False


# -- densities and extinction ----------------------------------------------

def _densities(atm: Atmosphere, altitude_m: np.ndarray
               ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    h = np.clip(altitude_m, 0.0, atm.top_radius_m - atm.bottom_radius_m)
    rayleigh = np.exp(-h / atm.rayleigh_scale_height_m)
    mie = np.exp(-h / atm.mie_scale_height_m)
    lo, peak, hi = atm.ozone_layer_m
    ozone = np.where(h < peak, (h - lo) / (peak - lo), (hi - h) / (hi - peak))
    ozone = np.clip(ozone, 0.0, 1.0)
    return rayleigh, mie, ozone


def _extinction(atm: Atmosphere, altitude_m: np.ndarray) -> np.ndarray:
    """Per-metre extinction, shape (..., 3)."""
    rayleigh, mie, ozone = _densities(atm, altitude_m)
    return (rayleigh[..., None] * np.asarray(atm.rayleigh_scattering)
            + mie[..., None] * atm.mie_extinction
            + ozone[..., None] * np.asarray(atm.ozone_extinction))


def transmittance(atm: Atmosphere, r: float, mu: float,
                  samples: int = RAY_SAMPLES) -> np.ndarray:
    """Transmittance along the ray from radius ``r`` at zenith cosine
    ``mu`` to the top of the atmosphere (or to the ground: then the
    optical depth is to the ground). Shape (3,)."""
    length, _ = _path_length(atm, r, mu)
    if length <= 0.0:
        return np.ones(3)
    t = (np.arange(samples) + 0.5) / samples * length
    radius = np.sqrt(r * r + t * t + 2.0 * r * t * mu)
    depth = _extinction(atm, radius - atm.bottom_radius_m).sum(axis=0) * (length / samples)
    return np.exp(-depth)


def sun_transmittance(atm: Atmosphere, altitude_m: float,
                      sun_elevation_deg: float) -> np.ndarray:
    """Transmittance from an observer to the sun, zero below the
    geometric horizon (the ground blocks the ray)."""
    r = atm.bottom_radius_m + max(0.0, altitude_m)
    mu = math.sin(math.radians(sun_elevation_deg))
    _, hits_ground = _path_length(atm, r, mu)
    if hits_ground:
        return np.zeros(3)
    return transmittance(atm, r, mu)


# -- phase functions ---------------------------------------------------------

def rayleigh_phase(cos_theta: np.ndarray) -> np.ndarray:
    return 3.0 / (16.0 * math.pi) * (1.0 + cos_theta * cos_theta)


def mie_phase(g: float, cos_theta: np.ndarray) -> np.ndarray:
    """Cornette-Shanks, the form Bruneton's demo uses."""
    k = 3.0 / (8.0 * math.pi) * (1.0 - g * g) / (2.0 + g * g)
    return k * (1.0 + cos_theta * cos_theta) / (1.0 + g * g - 2.0 * g * cos_theta) ** 1.5


# -- single scattering -------------------------------------------------------

def sky_radiance(atm: Atmosphere, altitude_m: float, view_elevation_deg: float,
                 view_azimuth_deg: float, sun_elevation_deg: float,
                 sun_azimuth_deg: float, samples: int = RAY_SAMPLES) -> np.ndarray:
    """Single-scattered radiance (W m^-2 sr^-1 nm^-1, shape (3,)) seen along
    a view direction: the integral of (Rayleigh + Mie) in-scatter times the
    transmittance to the sun and back to the eye along the ray, up to the
    top of the atmosphere or the ground."""
    r = atm.bottom_radius_m + max(0.0, altitude_m)
    ve, va = math.radians(view_elevation_deg), math.radians(view_azimuth_deg)
    se, sa = math.radians(sun_elevation_deg), math.radians(sun_azimuth_deg)
    view = np.array([math.cos(ve) * math.sin(va), math.cos(ve) * math.cos(va), math.sin(ve)])
    sun = np.array([math.cos(se) * math.sin(sa), math.cos(se) * math.cos(sa), math.sin(se)])
    cos_theta = float(np.dot(view, sun))
    length, _ = _path_length(atm, r, view[2])
    if length <= 0.0:
        return np.zeros(3)
    step = length / samples
    t = (np.arange(samples) + 0.5) * step
    # The point along the ray in the local frame (observer at (0, 0, r)).
    px, py, pz = view[0] * t, view[1] * t, r + view[2] * t
    radius = np.sqrt(px * px + py * py + pz * pz)
    altitude = radius - atm.bottom_radius_m
    rayleigh, mie, _ = _densities(atm, altitude)
    # Optical depth from the eye to each sample (cumulative, midpoint).
    ext = _extinction(atm, altitude)
    depth_eye = np.cumsum(ext, axis=0) * step - ext * (step / 2.0)
    t_eye = np.exp(-depth_eye)
    # Transmittance from each sample to the sun: mu_s at the sample.
    mu_s = (px * sun[0] + py * sun[1] + pz * sun[2]) / radius
    t_sun = np.empty((samples, 3))
    for i in range(samples):
        _, blocked = _path_length(atm, float(radius[i]), float(mu_s[i]))
        t_sun[i] = 0.0 if blocked else transmittance(atm, float(radius[i]), float(mu_s[i]), samples=16)
    scatter = (rayleigh[:, None] * np.asarray(atm.rayleigh_scattering) * rayleigh_phase(cos_theta)
               + mie[:, None] * atm.mie_scattering * mie_phase(atm.mie_phase_g, cos_theta))
    integrand = scatter * t_eye * t_sun
    return np.asarray(atm.solar_irradiance) * integrand.sum(axis=0) * step


def sun_irradiance(atm: Atmosphere, altitude_m: float,
                   sun_elevation_deg: float) -> np.ndarray:
    """The sun's irradiance on a surface facing it at the observer, after
    transmittance (W m^-2 nm^-1, shape (3,)); zero below the horizon."""
    return np.asarray(atm.solar_irradiance) * sun_transmittance(atm, altitude_m, sun_elevation_deg)


def sky_irradiance(atm: Atmosphere, altitude_m: float, sun_elevation_deg: float,
                   sun_azimuth_deg: float) -> np.ndarray:
    """Cosine-weighted irradiance of the sky dome on a horizontal surface
    (the AMBIENT light), by midpoint quadrature over the hemisphere."""
    total = np.zeros(3)
    for j in range(SKY_ZENITH_SAMPLES):
        elevation = (j + 0.5) / SKY_ZENITH_SAMPLES * 90.0
        cos_z = math.sin(math.radians(elevation))
        sin_z = math.cos(math.radians(elevation))
        d_omega = (math.pi / 2.0 / SKY_ZENITH_SAMPLES) * (2.0 * math.pi / SKY_AZIMUTH_SAMPLES) * sin_z
        for i in range(SKY_AZIMUTH_SAMPLES):
            azimuth = (i + 0.5) / SKY_AZIMUTH_SAMPLES * 360.0
            total += sky_radiance(atm, altitude_m, elevation, azimuth,
                                  sun_elevation_deg, sun_azimuth_deg, samples=16) * cos_z * d_omega
    return total


def horizon_radiance(atm: Atmosphere, altitude_m: float, sun_elevation_deg: float,
                     sun_azimuth_deg: float, elevation_deg: float = 2.0) -> np.ndarray:
    """The sky just above the horizon on the side away from the sun: the
    colour distant terrain fades into (the HORIZON / fog colour)."""
    return sky_radiance(atm, altitude_m, elevation_deg,
                        (sun_azimuth_deg + 180.0) % 360.0,
                        sun_elevation_deg, sun_azimuth_deg)


# -- colours for the render --------------------------------------------------

def _srgb8(linear: np.ndarray, white: np.ndarray) -> Tuple[int, int, int]:
    """A spectral RGB triple as a COLOUR: divided band by band by the
    sun's top-of-atmosphere spectrum (so an unattenuated sun is white, as
    the render's sun light is white at full intensity), normalised to its
    brightest band and sRGB-encoded 8-bit. The render takes colours, not
    intensities."""
    balanced = np.asarray(linear, dtype=float) / np.asarray(white, dtype=float)
    peak = float(np.max(balanced))
    if not peak > 0.0:
        return (0, 0, 0)
    v = np.clip(balanced / peak, 0.0, 1.0)
    enc = np.where(v <= 0.0031308, 12.92 * v, 1.055 * np.power(v, 1.0 / 2.4) - 0.055)
    return tuple(int(round(float(c) * 255.0)) for c in enc)


@dataclass
class SkyLighting:
    direct: Tuple[int, int, int]
    ambient: Tuple[int, int, int]
    horizon: Tuple[int, int, int]
    #: The physical quantities behind the colours, for the record.
    sun_irradiance: Tuple[float, float, float]
    sky_irradiance: Tuple[float, float, float]
    horizon_radiance: Tuple[float, float, float]
    sun_elevation_deg: float
    sun_azimuth_deg: float
    altitude_m: float
    atmosphere: Dict[str, object] = field(default_factory=dict)

    def record(self) -> Dict[str, object]:
        return {
            "direct_srgb8": list(self.direct), "ambient_srgb8": list(self.ambient),
            "horizon_srgb8": list(self.horizon),
            "sun_irradiance_w_m2_nm": [round(v, 6) for v in self.sun_irradiance],
            "sky_irradiance_w_m2_nm": [round(v, 6) for v in self.sky_irradiance],
            "horizon_radiance_w_m2_sr_nm": [round(v, 8) for v in self.horizon_radiance],
            "sun_elevation_deg": self.sun_elevation_deg,
            "sun_azimuth_deg": self.sun_azimuth_deg, "altitude_m": self.altitude_m,
            "atmosphere": self.atmosphere,
            "note": "colours are each quantity white-balanced by the sun's "
                    "top-of-atmosphere spectrum and normalised to the brightest "
                    "band; intensities stay the look's (the commandlet's contract)",
        }


def sky_lighting(sun_elevation_deg: float, sun_azimuth_deg: float,
                 altitude_m: float = 0.0, atm: Atmosphere = Atmosphere()) -> SkyLighting:
    """The direct, ambient and horizon colours for a sun position, from
    the atmosphere model: what :func:`core.xplane.sky_lighting` reads
    from the decoded tables, computed instead."""
    direct = sun_irradiance(atm, altitude_m, sun_elevation_deg)
    ambient = sky_irradiance(atm, altitude_m, sun_elevation_deg, sun_azimuth_deg)
    horizon = horizon_radiance(atm, altitude_m, sun_elevation_deg, sun_azimuth_deg)
    white = np.asarray(atm.solar_irradiance)
    return SkyLighting(direct=_srgb8(direct, white), ambient=_srgb8(ambient, white),
                       horizon=_srgb8(horizon, white),
                       sun_irradiance=tuple(float(v) for v in direct),
                       sky_irradiance=tuple(float(v) for v in ambient),
                       horizon_radiance=tuple(float(v) for v in horizon),
                       sun_elevation_deg=float(sun_elevation_deg),
                       sun_azimuth_deg=float(sun_azimuth_deg),
                       altitude_m=float(altitude_m), atmosphere=atm.record())
