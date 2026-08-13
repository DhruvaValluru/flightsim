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

#: The reanalysis hour applied (UTC). Noon is the documented convention --
#: a single stated choice rather than a hidden average.
HOUR_UTC = 12


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
