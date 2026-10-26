"""Open-Meteo fetchers: multi-model atmospheric forecast + marine.

All times are requested as unixtime and converted with zoneinfo, because
Open-Meteo's ISO timestamps use one fixed UTC offset for the whole response
and ignore DST transitions inside the forecast range.
"""
from __future__ import annotations

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

HOURLY_VARS = [
    "temperature_2m",
    "dew_point_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "wet_bulb_temperature_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
    "sunshine_duration",
    "uv_index",
    "is_day",
]

MARINE_VARS = [
    "wave_height",
    "wave_direction",
    "wave_period",
    "swell_wave_height",
    "swell_wave_direction",
    "swell_wave_period",
    "swell_wave_peak_period",
    "secondary_swell_wave_height",
    "secondary_swell_wave_direction",
    "secondary_swell_wave_period",
    "wind_wave_height",
    "sea_surface_temperature",
    "sea_level_height_msl",
]

# HRRR: 3 km, hourly updates, 18-48 h horizon. NBM: NWS statistical blend,
# has native precip probability. GFS seamless: 16-day backbone + UV index.
DEFAULT_MODELS = ["ncep_hrrr_conus", "ncep_nbm_conus", "ncep_gfs_seamless"]


def fetch_forecast(lat, lon, models=None, days=7, session=None, timeout=20):
    models = models or DEFAULT_MODELS
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(HOURLY_VARS),
        "daily": "sunrise,sunset",
        "models": ",".join(models),
        "forecast_days": days,
        "past_hours": 12,  # lets yardwork look back for wet ground
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timeformat": "unixtime",
        "timezone": "auto",
    }
    s = session or requests
    r = s.get(FORECAST_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    data["_models"] = models
    return data


def fetch_marine(lat, lon, days=7, session=None, timeout=20):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(MARINE_VARS),
        "forecast_days": min(days, 8),
        "past_hours": 6,
        "length_unit": "metric",  # converted locally so units are unambiguous
        "cell_selection": "sea",
        "timeformat": "unixtime",
        "timezone": "auto",
    }
    s = session or requests
    r = s.get(MARINE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()
