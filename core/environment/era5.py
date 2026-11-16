"""Historical weather from ERA5 reanalysis, honestly scoped.

A spec with a ``weather_date`` flies the MEAN WIND that the ERA5 reanalysis
records for that place, day and altitude -- fetched through the free
Open-Meteo archive API (which serves ERA5-derived hourly fields, no account
required) at the pressure level nearest the spec's altitude.

What this is: the hourly mean state of a ~25 km global reanalysis grid --
the real synoptic wind, with full provenance (level, hour, source).
What this is NOT, stated: gusts, turbulence, convection or anything at
scales below the grid (turbulence stays the spec's own word); a forecast;
a measurement at the aircraft (reanalysis blends model and observations).
The wind is applied as a recorded spec edit BEFORE the digest is answered,
and never overrides a USER-stated wind.

Sky step 5 (the owner's X-Plane-12 brief): :func:`fetch_reanalysis_cloud_cover`
reads the same archive's hourly ``cloud_cover_low/mid/high`` for the sky
plan's cloud type and coverage. Clouds are VISUAL ONLY (the beauty render),
so unlike the wind this never edits the spec, never touches the digest and
never refuses a run: an unreachable archive leaves the plan's stated default,
recorded as a default with the error text.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict

#: ERA5 reanalysis archive: SURFACE fields only (10 m / 100 m wind), any
#: date since 1940.
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
#: Archived NWP model analyses: PRESSURE-LEVEL winds, dates from 2022-01-01.
#: (Measured 2026-08-11: the ERA5 archive endpoint returns nulls for
#: pressure-level variables; this endpoint serves them.)
HISTORICAL_FORECAST_URL = ("https://historical-forecast-api.open-meteo.com"
                           "/v1/forecast")
#: First date the pressure-level source covers.
PRESSURE_LEVEL_FROM = "2022-01-01"

#: Standard-atmosphere geometric altitude (m) of each pressure level the
#: archive serves. The spec's altitude picks the NEAREST level; both the
#: level and its nominal altitude are recorded in the edit's provenance.
PRESSURE_LEVEL_ALTITUDE_M: Dict[int, float] = {
    1000: 110.0, 925: 760.0, 850: 1500.0, 700: 3000.0, 600: 4200.0,
    500: 5600.0, 400: 7200.0, 300: 9200.0, 250: 10400.0, 200: 11800.0,
}

#: The reanalysis hour applied to the WIND (UTC). Noon is the documented
#: convention -- a single stated choice rather than a hidden average. The
#: cloud cover (fetch_reanalysis_cloud_cover) takes the sky plan's own instant
#: hour instead: the clouds are drawn for the moment the sun is planned at.
HOUR_UTC = 12

#: The hourly cloud fields the ERA5 archive serves (percent), in the order
#: the cover dict's ``total``, ``low``, ``mid``, ``high`` are read.
CLOUD_COVER_FIELDS = ("cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high")
#: What the archive's fraction is, stated on every cover dict.
CLOUD_COVER_SOURCE = ("ERA5 reanalysis via Open-Meteo archive API, hourly cloud fraction "
                      "of a ~25 km grid cell; ERA5T values for recent months may be revised")


class WeatherUnavailableError(RuntimeError):
    """The archive could not answer -- offline, bad date, or out of range."""


def nearest_pressure_level(altitude_m: float) -> int:
    return min(PRESSURE_LEVEL_ALTITUDE_M,
               key=lambda level: abs(PRESSURE_LEVEL_ALTITUDE_M[level]
                                     - float(altitude_m)))


def fetch_reanalysis_wind(lat: float, lon: float, date_iso: str,
                          altitude_m: float, timeout_s: float = 15.0) -> Dict:
    """Historical mean wind for (place, date, altitude), source stated.

    Dates from 2022: the wind at the pressure level nearest the altitude,
    from archived NWP analyses (the ERA5 archive endpoint serves no
    pressure-level fields -- measured, not assumed). Earlier dates: the
    ERA5 100 m surface wind, with the level honestly labeled -- it is NOT
    the cruise-level wind and the provenance string says so. Raises
    WeatherUnavailableError by name rather than guessing.
    """
    at_pressure_level = date_iso >= PRESSURE_LEVEL_FROM
    if at_pressure_level:
        level = nearest_pressure_level(altitude_m)
        url = HISTORICAL_FORECAST_URL
        speed_key = f"wind_speed_{level}hPa"
        direction_key = f"wind_direction_{level}hPa"
        level_note = (f"{level} hPa "
                      f"(~{PRESSURE_LEVEL_ALTITUDE_M[level]:.0f} m)")
        source = ("archived NWP model analysis via Open-Meteo "
                  "historical-forecast API (~10-25 km hourly mean state; "
                  "no sub-grid gusts)")
        level_altitude = PRESSURE_LEVEL_ALTITUDE_M[level]
    else:
        level = 0
        url = ARCHIVE_URL
        speed_key = "wind_speed_100m"
        direction_key = "wind_direction_100m"
        level_note = "100 m AGL"
        source = ("ERA5 reanalysis via Open-Meteo archive API -- SURFACE "
                  "wind at 100 m AGL, the only level ERA5 serves here; "
                  "NOT the cruise-level wind")
        level_altitude = 100.0
    params = urllib.parse.urlencode({
        "latitude": f"{float(lat):.4f}", "longitude": f"{float(lon):.4f}",
        "start_date": date_iso, "end_date": date_iso,
        "hourly": f"{speed_key},{direction_key}",
        "wind_speed_unit": "kn",
    })
    try:
        with urllib.request.urlopen(f"{url}?{params}",
                                    timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hourly = payload["hourly"]
        speed_kt = float(hourly[speed_key][HOUR_UTC])
        from_deg = float(hourly[direction_key][HOUR_UTC])
    except Exception as exc:
        raise WeatherUnavailableError(
            f"historical weather (Open-Meteo) could not answer for "
            f"({lat:.3f}, {lon:.3f}) on {date_iso}: "
            f"{type(exc).__name__}: {exc}") from exc
    return {
        "speed_kt": round(speed_kt, 1),
        "from_deg": round(from_deg, 0) % 360.0,
        "level_hpa": level,
        "level_note": level_note,
        "level_altitude_m": level_altitude,
        "hour_utc": HOUR_UTC,
        "source": source,
    }


def fetch_reanalysis_cloud_cover(lat: float, lon: float, date_iso: str,
                                 hour_utc: int, timeout_s: float = 15.0) -> Dict:
    """Historical cloud cover by level for (place, date, UTC hour), as fractions.

    Sky step 5. The ERA5 archive (``ARCHIVE_URL``, any date since 1940)
    serves ``cloud_cover`` and ``cloud_cover_low/mid/high`` hourly in
    percent; this returns them as 0..1 fractions under ``total``, ``low``,
    ``mid`` and ``high`` with the hour, the date and a ``source`` string.
    ``date_iso`` and ``hour_utc`` are the sky plan INSTANT's UTC date and
    UTC hour (``core.sky.plan.resolve_instant(...).utc``), not the wind's
    noon convention and NOT the spec's ``weather_date``: that is a LOCAL
    date, and a local evening west of Greenwich or a local morning east of
    it falls on the next or the previous UTC day (20:00 at New York on
    2024-01-15 is 2024-01-16T00:56Z). The clouds are planned for the moment
    the sun is, and the returned ``date`` is the UTC day the hour index
    belongs to. A null hour (the archive serves nulls for dates it has not
    assimilated) raises :class:`WeatherUnavailableError` by name, like any
    network failure, rather than guessing a sky. The caller (the web app)
    records the default instead and never refuses the run: clouds are VISUAL
    ONLY. Pure on its answer: the values are copied into sky.json, so a plan
    is deterministic once written.
    """
    hour = int(hour_utc)
    if not 0 <= hour <= 23:
        raise WeatherUnavailableError(
            f"historical cloud cover: hour_utc {hour_utc!r} is not 0..23")
    params = urllib.parse.urlencode({
        "latitude": f"{float(lat):.4f}", "longitude": f"{float(lon):.4f}",
        "start_date": date_iso, "end_date": date_iso,
        "hourly": ",".join(CLOUD_COVER_FIELDS),
    })
    try:
        with urllib.request.urlopen(f"{ARCHIVE_URL}?{params}",
                                    timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        hourly = payload["hourly"]
        percents = [hourly[field][hour] for field in CLOUD_COVER_FIELDS]
        if any(value is None for value in percents):
            raise ValueError(
                f"the archive returned null cloud cover at {hour:02d}Z "
                f"(not yet assimilated for {date_iso})")
        fractions = [min(max(float(value), 0.0), 100.0) / 100.0
                     for value in percents]
    except Exception as exc:
        raise WeatherUnavailableError(
            f"historical cloud cover (Open-Meteo ERA5 archive) could not "
            f"answer for ({lat:.3f}, {lon:.3f}) on {date_iso} at {hour:02d}Z: "
            f"{type(exc).__name__}: {exc}") from exc
    total, low, mid, high = fractions
    return {
        "low": round(low, 4),
        "mid": round(mid, 4),
        "high": round(high, 4),
        "total": round(total, 4),
        "hour_utc": hour,
        "date": date_iso,
        "source": CLOUD_COVER_SOURCE,
    }
