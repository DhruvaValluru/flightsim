"""The physical sky plan: what the UE host draws and how it exposes.

One function, :func:`plan_sky`, turns a spec (place, date, time of day,
altitude, weather event) into the ``sky.json`` sidecar the render
commandlet reads via ``-sky=``. Everything the host would otherwise pick
by eye is computed here, deterministically, and recorded:

* **Sun**: true position for the instant, 120 000 lux outside the
  atmosphere (UE's physical-units convention; SkyAtmosphere applies the
  transmittance), per-pixel atmosphere transmittance.
* **Moon**: position, phase and illuminance. The host draws it as a real
  sphere lit by the sun, so the terminator and phase come from geometry;
  a second atmosphere light (index 1) carries the moonlight itself.
* **Stars**: the Hipparcos naked-eye catalogue (``assets/sky``),
  precessed to date, each drawn as an emissive disc whose luminance
  conserves the star's illuminance. Atmospheric extinction is left to
  the host's aerial perspective, which already applies to them.
* **Exposure**: EV100 from modelled horizontal illuminance (the incident
  light-meter equation, calibration constant C = 250 -> E = 2.5 * 2^EV).
  Below daylight the render deliberately under-exposes at half rate --
  a meter would render a moonlit field as noon, which is not what night
  looks like. Realised as UE's physical camera (f/4, 1/60 s, ISO 100)
  plus exposure compensation, constant over the clip (Gate 6's rule).
* **Clouds**: a volumetric layer, VISUAL ONLY, not from data; its base is
  placed above the flight so the camera stays clear of it.
* **Post-processing** per camera preset: filmic tonemapping (UE's
  default), bloom, lens flare, vignette, grain, fringe.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import astro

REPO = Path(__file__).resolve().parents[2]
STAR_CATALOGUE = REPO / "assets" / "sky" / "hipparcos_bright.csv"

SKY_VERSION = 1

#: The sun's date when the spec names none (no weather_date, no date in
#: time_of_day): the March 2026 equinox -- twelve-hour days everywhere,
#: recorded as a default in every sky.json.
DEFAULT_DATE = date(2026, 3, 20)

#: Sun illuminance outside the atmosphere, lux. The solar constant in
#: visible terms is ~128 klx; UE's documented physical-sky value is
#: 120 klx, which is what its SkyAtmosphere was tuned against.
SUN_ILLUMINANCE_LUX = 120000.0
#: Full-moon illuminance outside the atmosphere at normal incidence, lux
#: (~0.27 lux at the ground under a clear sky).
FULL_MOON_LUX = 0.32
#: Night-sky floor (starlight + airglow), lux.
NIGHT_SKY_LUX = 5.0e-4

#: The physical camera the exposure is realised through: f/4, 1/60 s,
#: ISO 100 -> EV100 = log2(N^2 / t) = log2(960).
CAMERA_FSTOP = 4.0
CAMERA_SHUTTER_PER_S = 60.0
CAMERA_ISO = 100.0
CAMERA_EV100 = math.log2(CAMERA_FSTOP ** 2 * CAMERA_SHUTTER_PER_S
                         * 100.0 / CAMERA_ISO)

#: Horizontal illuminance at which the exposure stops tracking the meter
#: and starts rendering "night" (sunset-ish light).
DAYLIGHT_LUX = 400.0
EV100_RANGE = (-4.0, 16.0)

#: Stars fainter than this are not drawn (naked-eye limit, dark site).
STAR_LIMIT_VMAG = 6.5
#: Stars are drawn only once the sun is this far down: in daylight and
#: early civil twilight the sky out-shines every one of them anyway.
STARS_BELOW_SUN_ELEVATION_DEG = -4.0

#: Accepted time words -> how the instant is found. ("elev", target,
#: rising?) solves for the sun crossing that elevation; ("lmst", h)
#: is local mean solar time; ("extreme", max?) the day's highest or
#: lowest sun.
TIME_WORDS: Dict[str, Tuple] = {
    "dawn": ("elev", -4.0, True),
    "sunrise": ("elev", 0.5, True),
    "morning": ("lmst", 9.0),
    "noon": ("extreme", True),
    "midday": ("extreme", True),
    "afternoon": ("lmst", 15.0),
    "golden hour": ("elev", 6.0, False),
    "sunset": ("elev", 0.5, False),
    "dusk": ("elev", -4.0, False),
    "twilight": ("elev", -8.0, False),
    "night": ("extreme", False),
    "midnight": ("extreme", False),
}

_CLOCK = re.compile(r"^(?:(\d{4}-\d{2}-\d{2})t)?(\d{1,2}):(\d{2})(z?)$")


class SkyError(ValueError):
    """A time of day that cannot happen at this place and date."""


# -- the instant -------------------------------------------------------------


@dataclass(frozen=True)
class Instant:
    utc: datetime
    basis: str
    date_source: str


def _date_for(time_value: str, weather_date: Optional[str]) -> Tuple[date, str]:
    match = _CLOCK.match(time_value)
    if match and match.group(1):
        return date.fromisoformat(match.group(1)), "time_of_day"
    if weather_date and weather_date != "none":
        return date.fromisoformat(weather_date), "weather_date"
    return DEFAULT_DATE, "default (March 2026 equinox)"


def scene_date(time_value: str, weather_date: Optional[str]) -> Tuple[date, str]:
    """The calendar date a spec's sky is planned for, and where it came
    from: an ISO prefix on ``time_of_day``, else ``weather_date``, else
    :data:`DEFAULT_DATE`. The same resolution the sky plan itself uses,
    so the terrain's seasonal look (core.xplane.drape's snow cover) and
    the sun agree on the month."""
    return _date_for(" ".join(str(time_value).strip().lower().split()),
                     weather_date)


def _solar_midnight_utc(day: date, lon_deg: float) -> datetime:
    """00:00 local mean solar time of ``day`` at ``lon_deg``, as UTC."""
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start - timedelta(hours=lon_deg / 15.0)


def _elevations(start: datetime, lat: float, lon: float,
                step_min: float = 4.0) -> Tuple[List[datetime], np.ndarray]:
    times = [start + timedelta(minutes=step_min * i)
             for i in range(int(24 * 60 / step_min) + 1)]
    els = np.array([astro.sun_position(t, lat, lon).elevation_deg
                    for t in times])
    return times, els


def _bisect(a: datetime, b: datetime, fn) -> datetime:
    fa = fn(a)
    for _ in range(30):
        mid = a + (b - a) / 2
        if (fn(mid) > 0) == (fa > 0):
            a, fa = mid, fn(mid)
        else:
            b = mid
    return a + (b - a) / 2


def resolve_instant(time_value: str, weather_date: Optional[str],
                    lat_deg: float, lon_deg: float) -> Instant:
    """The UTC instant a spec's ``time_of_day`` names.

    ``HH:MM`` is local MEAN SOLAR time (UTC + longitude/15 h) -- no
    time-zone database, and stated as such; ``HH:MMZ`` is UTC; either may
    carry an ISO date prefix (``2026-12-24T18:30``). Words solve for the
    sun's geometry on the date. Raises :class:`SkyError` for an instant
    that does not occur (a sunset in polar day).
    """
    value = " ".join(str(time_value).strip().lower().split())
    day, date_source = _date_for(value, weather_date)
    midnight = _solar_midnight_utc(day, lon_deg)

    match = _CLOCK.match(value)
    if match:
        hour, minute = int(match.group(2)), int(match.group(3))
        if hour > 23 or minute > 59:
            raise SkyError(f"time_of_day {time_value!r} is not a clock time")
        if match.group(4):
            utc = datetime(day.year, day.month, day.day, hour, minute,
                           tzinfo=timezone.utc)
            return Instant(utc, f"{hour:02d}:{minute:02d} UTC", date_source)
        utc = midnight + timedelta(hours=hour, minutes=minute)
        return Instant(utc, f"{hour:02d}:{minute:02d} local mean solar time "
                            f"(UTC{lon_deg / 15.0:+.2f} h; no time-zone "
                            f"database)", date_source)

    rule = TIME_WORDS.get(value)
    if rule is None:
        raise SkyError(
            f"unknown time_of_day {time_value!r}; use HH:MM (local solar), "
            f"HH:MMZ (UTC), or one of {sorted(TIME_WORDS)}")
    if rule[0] == "lmst":
        utc = midnight + timedelta(hours=rule[1])
        return Instant(utc, f"{value}: {rule[1]:04.1f} h local mean solar "
                            f"time", date_source)

    times, els = _elevations(midnight, lat_deg, lon_deg)
    if rule[0] == "extreme":
        i = int(np.argmax(els) if rule[1] else np.argmin(els))
        # Refine on a one-minute grid either side of the coarse extreme.
        lo = times[max(i - 1, 0)]
        fine = [lo + timedelta(minutes=k) for k in range(9)]
        vals = [astro.sun_position(t, lat_deg, lon_deg).elevation_deg
                for t in fine]
        pick = int(np.argmax(vals) if rule[1] else np.argmin(vals))
        what = "highest" if rule[1] else "lowest"
        return Instant(fine[pick], f"{value}: the sun's {what} point of the "
                                   f"day", date_source)

    _, target, rising = rule
    for i in range(len(els) - 1):
        a, b = els[i] - target, els[i + 1] - target
        crosses = (a < 0 <= b) if rising else (a >= 0 > b)
        if crosses:
            utc = _bisect(times[i], times[i + 1],
                          lambda t: astro.sun_position(
                              t, lat_deg, lon_deg).elevation_deg - target)
            return Instant(utc, f"{value}: sun {'rising' if rising else 'setting'}"
                                f" through {target:+.1f} deg", date_source)
    raise SkyError(
        f"{value!r} does not occur at {lat_deg:.2f}, {lon_deg:.2f} on "
        f"{day.isoformat()}: the sun never {'rises' if rising else 'sets'} "
        f"through {target:+.1f} deg that day (polar day or night). State a "
        f"clock time instead.")


# -- light and exposure ---------------------------------------------------


def _twilight_lux(el: float) -> float:
    """Horizontal illuminance below the horizon, log-linear between the
    standard twilight values (sunset ~700 lx, civil end 3.4 lx, nautical
    end 0.008 lx, astronomical end 0.0008 lx)."""
    table = ((-18.0, math.log10(8e-4)), (-12.0, math.log10(8e-3)),
             (-6.0, math.log10(3.4)), (0.0, math.log10(700.0)))
    if el <= table[0][0]:
        return 0.0
    for (e0, l0), (e1, l1) in zip(table, table[1:]):
        if el <= e1:
            return 10.0 ** (l0 + (l1 - l0) * (el - e0) / (e1 - e0))
    return 700.0


def sun_horizontal_lux(el: float) -> float:
    """Clear-sky global horizontal illuminance from the sun, lux.

    Above the horizon: direct beam through the Meinel air-mass law
    (0.7^(AM^0.678)) with the Kasten-Young air mass, plus a diffuse term,
    floored at the sunset value; below it the twilight table.
    """
    if el <= 0.0:
        return _twilight_lux(el)
    s = math.sin(math.radians(el))
    air_mass = 1.0 / (s + 0.50572 * (el + 6.07995) ** -1.6364)
    direct = 128000.0 * s * 0.7 ** (air_mass ** 0.678)
    diffuse = 0.12 * 128000.0 * math.sqrt(s)
    return max(direct + diffuse, 700.0)


def ev100_for(horizontal_lux: float) -> float:
    """The render's EV100 for a scene lit at ``horizontal_lux``.

    Daylight: the incident-meter equation, EV100 = log2(E / 2.5). Below
    DAYLIGHT_LUX the exposure falls at HALF the meter's rate, so a moonlit
    scene renders dark-but-legible and a moonless one near black, rather
    than both as noon.
    """
    e = max(horizontal_lux, 1e-6)
    if e >= DAYLIGHT_LUX:
        ev = math.log2(e / 2.5)
    else:
        ev = math.log2(DAYLIGHT_LUX / 2.5) + 0.5 * math.log2(e / DAYLIGHT_LUX)
    return float(min(max(ev, EV100_RANGE[0]), EV100_RANGE[1]))


# -- stars -------------------------------------------------------------------


def load_catalogue(path: Path = STAR_CATALOGUE):
    """(hip, ra_deg, dec_deg, vmag, bv) arrays from the committed subset."""
    hip, ra, dec, vmag, bv = [], [], [], [], []
    with open(path, encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            hip.append(int(row["hip"]))
            ra.append(float(row["ra_hours"]) * 15.0)
            dec.append(float(row["dec_deg"]))
            vmag.append(float(row["vmag"]))
            bv.append(float(row["bv"]) if row["bv"] else math.nan)
    return (np.array(hip), np.array(ra), np.array(dec), np.array(vmag),
            np.array(bv))


#: B-V bins for batching (blue-white / white / yellow / orange-red).
_BV_EDGES = (0.0, 0.5, 1.1)


def star_batches(when: datetime, lat: float, lon: float,
                 angular_radius_deg: float,
                 limit_vmag: float = STAR_LIMIT_VMAG) -> List[Dict]:
    """Visible stars grouped by (half-magnitude, colour) into batches the
    host instances in one draw each. Luminance conserves each star's
    illuminance over its drawn disc: L = E / (pi theta^2)."""
    _, ra, dec, vmag, bv = load_catalogue()
    jd = astro.julian_day(when)
    ra_d, dec_d = astro.precess_j2000(ra, dec, jd)
    az, el = astro.equatorial_to_horizontal(ra_d, dec_d, jd, lat, lon)
    keep = (el > 0.0) & (vmag <= limit_vmag)
    solid_angle = math.pi * math.radians(angular_radius_deg) ** 2
    mag_bin = np.round(vmag * 2.0) / 2.0
    bv_bin = np.digitize(np.nan_to_num(bv, nan=0.6), _BV_EDGES)
    bv_centres = np.array([-0.1, 0.25, 0.8, 1.4])
    batches = []
    for m in np.unique(mag_bin[keep]):
        for c in range(len(bv_centres)):
            sel = keep & (mag_bin == m) & (bv_bin == c)
            if not sel.any():
                continue
            lum = float(astro.star_illuminance_lux(m)) / solid_angle
            batches.append({
                "vmag": float(m),
                "luminance_nits": round(lum, 6),
                "color": [round(float(x), 4)
                          for x in astro.bv_to_rgb([bv_centres[c]])[0]],
                "az_el_deg": [[round(float(a), 4), round(float(e), 4)]
                              for a, e in zip(az[sel], el[sel])],
            })
    return batches


# -- per-camera post-processing -----------------------------------------------

#: Lens character per camera kind. External cameras are a long lens on a
#: chase ship; the cockpit view is a wide lens behind a canopy. Values are
#: UE post-process settings; the tonemapper is UE's filmic (ACES-fitted)
#: default for both, stated rather than re-tuned.
POST_PROCESS = {
    "external": {"bloom_intensity": 0.5, "lens_flare_intensity": 0.15,
                 "vignette_intensity": 0.3, "film_grain_intensity": 0.03,
                 "chromatic_aberration": 0.12, "motion_blur_amount": 0.0},
    "cockpit": {"bloom_intensity": 0.65, "lens_flare_intensity": 0.05,
                "vignette_intensity": 0.5, "film_grain_intensity": 0.08,
                "chromatic_aberration": 0.0, "motion_blur_amount": 0.0},
}


def post_process_for(preset: str) -> Dict:
    kind = "cockpit" if preset == "cockpit" else "external"
    return {"kind": kind, "tonemapper": "filmic (UE default)",
            **POST_PROCESS[kind]}


# -- the plan -------------------------------------------------------------------


def _direction(body: astro.Body) -> Dict:
    return {"azimuth_deg": round(body.azimuth_deg, 4),
            "elevation_deg": round(body.elevation_deg, 4),
            "angular_radius_deg": round(body.angular_radius_deg, 5),
            "distance_km": round(body.distance_km, 1)}


def plan_sky(time_value: str, weather_date: Optional[str], lat: float,
             lon: float, altitude_msl_m: float, ground_elevation_m: float,
             camera_preset: str = "chase", weather_event: str = "none",
             fov_deg: float = 55.0, width_px: int = 1280,
             night_lights: Optional[Dict] = None) -> Dict:
    """The complete ``sky.json`` for one render. Pure: same inputs, same
    bytes."""
    instant = resolve_instant(time_value, weather_date, lat, lon)
    sun = astro.sun_position(instant.utc, lat, lon)
    moon = astro.moon_position(instant.utc, lat, lon)

    moon_rel = astro.moon_relative_brightness(moon.phase_angle_deg)
    sun_lux = sun_horizontal_lux(sun.elevation_deg)
    moon_lux = (0.27 * moon_rel * math.sin(math.radians(moon.elevation_deg))
                if moon.elevation_deg > 0 else 0.0)
    horizontal = sun_lux + moon_lux + NIGHT_SKY_LUX
    ev100 = ev100_for(horizontal)

    # One pixel's angular radius: the smallest disc that still rasterises
    # stably under temporal AA.
    star_radius = max(fov_deg / width_px, 0.02)
    draw_stars = sun.elevation_deg < STARS_BELOW_SUN_ELEVATION_DEG
    stars = (star_batches(instant.utc, lat, lon, star_radius)
             if draw_stars else [])

    storm = weather_event in ("thunderstorm", "tornado")
    agl_km = max(altitude_msl_m - ground_elevation_m, 0.0) / 1000.0
    cloud_bottom = max(2.0 if not storm else 1.2, agl_km + 1.0)

    plan = {
        "sky_version": SKY_VERSION,
        "instant_utc": instant.utc.isoformat(timespec="seconds"),
        "time_of_day": str(time_value),
        "time_basis": instant.basis,
        "date_source": instant.date_source,
        "observer": {"latitude_deg": lat, "longitude_deg": lon},
        "sun": {
            **_direction(sun),
            "illuminance_lux": SUN_ILLUMINANCE_LUX,
            "horizontal_illuminance_lux": round(sun_lux, 6),
            # §6.6's +90 deg transmittance floor keeps the daytime ground
            # lit from georeferenced origins; once the sun is down the
            # engine default restores the planet's shadow, or terrain
            # would stay sunlit from below the horizon.
            "transmittance_min_elevation_deg": 90.0 if sun.elevation_deg > 0
            else -90.0,
            "per_pixel_transmittance": True,
        },
        "moon": {
            **_direction(moon),
            "phase_angle_deg": round(moon.phase_angle_deg, 3),
            "illuminated_fraction": round(moon.illuminated_fraction, 4),
            "waxing": moon.waxing,
            "illuminance_lux": round(FULL_MOON_LUX * moon_rel, 6),
            "horizontal_illuminance_lux": round(moon_lux, 6),
            "albedo": 0.12,
            "basis": "sphere lit by the sun light: phase and terminator "
                     "are geometric; Meeus ch. 47 truncated series",
        },
        "stars": {
            "drawn": draw_stars,
            "catalogue": "Hipparcos (via HYG v4.1, CC BY-SA 4.0), V <= "
                         f"{STAR_LIMIT_VMAG}",
            "angular_radius_deg": round(star_radius, 5),
            "count": sum(len(b["az_el_deg"]) for b in stars),
            "note": ("precessed J2000 -> date; extinction from the host's "
                     "aerial perspective; colours approximate")
            if draw_stars else
            (f"sun at {sun.elevation_deg:+.1f} deg: the sky out-shines the "
             f"stars, none drawn"),
            "batches": stars,
        },
        "exposure": {
            "ev100": round(ev100, 3),
            "horizontal_illuminance_lux": round(horizontal, 6),
            "camera": {"fstop": CAMERA_FSTOP,
                       "shutter_per_s": CAMERA_SHUTTER_PER_S,
                       "iso": CAMERA_ISO,
                       "ev100": round(CAMERA_EV100, 4)},
            # UE: effective EV100 = physical-camera EV100 - bias.
            "bias": round(CAMERA_EV100 - ev100, 4),
            "basis": "incident meter E = 2.5 * 2^EV100 above "
                     f"{DAYLIGHT_LUX:g} lx; half-rate below (night renders "
                     "dark, not metered to noon); constant over the clip",
        },
        "clouds": {
            "enabled": True,
            "bottom_km": round(cloud_bottom, 3),
            "thickness_km": 6.0 if storm else 3.0,
            "basis": "VISUAL ONLY, not from weather data: UE volumetric "
                     "cloud layer, base placed >= 1 km above the flight so "
                     "the camera stays clear",
        },
        "fog": {"inscattering": "sky-atmosphere ambient contribution "
                                "(dims with the sun)"},
        "lighting": {"global_illumination": "lumen",
                     "reflections": "lumen",
                     "shadows": "virtual_shadow_maps"},
        "post_process": post_process_for(camera_preset),
    }
    if night_lights:
        plan["night_lights"] = night_lights
    return plan
