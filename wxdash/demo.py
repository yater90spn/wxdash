"""Synthetic payloads shaped exactly like Open-Meteo/NOAA responses.

Used with --demo so the dashboard can be developed and tested offline.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta


def _hours(tz, days, past=12):
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=past)
    return [start + timedelta(hours=i) for i in range(days * 24 + past)]


def fake_forecast(lat, lon, models, tz, days=7):
    rnd = random.Random(42)
    times = _hours(tz, days)
    now = datetime.now(tz)
    hourly = {"time": [int(t.timestamp()) for t in times]}
    units = {}

    def base(t, k):
        day = (t - times[0]).total_seconds() / 86400
        hr = t.hour + t.minute / 60
        diurnal = math.sin((hr - 9) / 24 * 2 * math.pi)  # peak ~3 PM
        trend = 54 - 4 * math.sin(day / 3.0) + (-6 if 2.5 < day < 4.0 else 0)
        temp = trend + 6 * diurnal
        cloud = max(0, min(100, 55 + 40 * math.sin(day * 1.7 + 1) + rnd.uniform(-10, 10)))
        wind = max(1, 9 + 6 * math.sin(day * 1.3) + 3 * max(0, diurnal) + rnd.uniform(-1.5, 1.5))
        rain_bump = math.exp(-((day - 4.6) ** 2) / 0.08)  # a front mid-week
        pop = max(0, min(100, 8 + 75 * rain_bump + rnd.uniform(-3, 3)))
        return {
            "temperature_2m": temp,
            "dew_point_2m": temp - 10 - 4 * max(0, diurnal),
            "relative_humidity_2m": 70 - 15 * diurnal,
            "apparent_temperature": temp - 0.35 * wind + 2 * max(0, diurnal) * (1 - cloud / 100),
            "wet_bulb_temperature_2m": temp - 5,
            "precipitation_probability": pop,
            "precipitation": 0.06 * rain_bump if pop > 40 else 0,
            "weather_code": 61 if pop > 55 else (3 if cloud > 85 else 2 if cloud > 45 else 1 if cloud > 15 else 0),
            "cloud_cover": cloud,
            "visibility": 52000 if pop < 50 else 15000,
            "wind_speed_10m": wind,
            "wind_direction_10m": (292 + 25 * math.sin(day * 0.9)) % 360,
            "wind_gusts_10m": wind * 1.6,
            "shortwave_radiation": max(0, 520 * math.sin((hr - 7) / 11 * math.pi)) * (1 - cloud / 130) if 7 < hr < 18 else 0,
            "sunshine_duration": 3600 * (1 - cloud / 100) if 7 < hr < 18 else 0,
            "uv_index": max(0, 4 * math.sin((hr - 7) / 11 * math.pi)) * (1 - cloud / 140) if 7 < hr < 18 else 0,
            "is_day": 1 if 7 <= hr < 18 else 0,
        }

    offsets = {"ncep_hrrr_conus": (0.8, -1.0), "ncep_nbm_conus": (0.0, 0.0), "ncep_gfs_seamless": (-1.2, 1.5)}
    for m in models:
        dt, dw = offsets.get(m, (0, 0))
        for var in base(times[0], m):
            key = var if len(models) == 1 else f"{var}_{m}"
            col = []
            for t in times:
                lead = (t - now).total_seconds() / 3600
                v = base(t, m)[var]
                if m == "ncep_hrrr_conus" and lead > 48:
                    v = None
                elif m == "ncep_hrrr_conus" and var == "precipitation_probability":
                    v = None
                elif m != "ncep_gfs_seamless" and var == "uv_index":
                    v = None
                elif v is not None:
                    if var in ("temperature_2m", "apparent_temperature", "dew_point_2m"):
                        v += dt * (1 + max(0, lead) / 72)
                    if var in ("wind_speed_10m", "wind_gusts_10m"):
                        v = max(0, v + dw)
                    v = round(v, 1) if var != "weather_code" else int(v)
                col.append(v)
            hourly[key] = col
            units[key] = "m" if var == "visibility" else ""
    d0 = times[12].date()
    daily = {"time": [], "sunrise": [], "sunset": []}
    for i in range(days):
        d = d0 + timedelta(days=i)
        daily["time"].append(int(datetime(d.year, d.month, d.day, tzinfo=tz).timestamp()))
        daily["sunrise"].append(int(datetime(d.year, d.month, d.day, 7, 14, tzinfo=tz).timestamp()))
        daily["sunset"].append(int(datetime(d.year, d.month, d.day, 18, 13, tzinfo=tz).timestamp()))
    return {"hourly": hourly, "hourly_units": units, "daily": daily, "_models": models}


def fake_marine(tz, days, facing=100):
    times = _hours(tz, days, past=6)
    h = {"time": [int(t.timestamp()) for t in times]}
    cols = {k: [] for k in ["wave_height", "wave_direction", "wave_period", "swell_wave_height",
                             "swell_wave_direction", "swell_wave_period", "swell_wave_peak_period",
                             "secondary_swell_wave_height", "secondary_swell_wave_direction",
                             "secondary_swell_wave_period", "wind_wave_height",
                             "sea_surface_temperature", "sea_level_height_msl"]}
    for t in times:
        day = (t - times[0]).total_seconds() / 86400
        sw = 0.75 + 0.45 * math.sin(day * 0.9 + 0.5)
        cols["swell_wave_height"].append(round(sw, 2))
        cols["swell_wave_direction"].append(round((facing + 30 + 15 * math.sin(day)) % 360))
        cols["swell_wave_period"].append(round(8.5 + 2 * math.sin(day * 0.7), 1))
        cols["swell_wave_peak_period"].append(round(9.5 + 2 * math.sin(day * 0.7), 1))
        cols["secondary_swell_wave_height"].append(0.3)
        cols["secondary_swell_wave_direction"].append(60)
        cols["secondary_swell_wave_period"].append(6)
        cols["wind_wave_height"].append(0.2)
        cols["wave_height"].append(round(sw * 1.1, 2))
        cols["wave_direction"].append(cols["swell_wave_direction"][-1])
        cols["wave_period"].append(8)
        cols["sea_surface_temperature"].append(16.7)
        hrs = (t - times[0]).total_seconds() / 3600
        cols["sea_level_height_msl"].append(round(0.7 * math.sin(2 * math.pi * hrs / 12.42), 2))
    h.update(cols)
    return {"hourly": h}


def fake_tides(tz, days):
    start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    hourly, events = [], []
    for i in range((days + 2) * 24):
        t = start + timedelta(hours=i)
        hourly.append((t, round(2.4 + 2.3 * math.sin(2 * math.pi * (i - 3) / 12.42), 2)))
    # high/low events: extrema of the sine
    k = 0
    while True:
        hrs = 3 + 12.42 / 4 + k * 12.42 / 2
        t = start + timedelta(hours=hrs)
        if t > start + timedelta(days=days + 2):
            break
        events.append((t.replace(second=0, microsecond=0), 4.7 if k % 2 == 0 else 0.1, "H" if k % 2 == 0 else "L"))
        k += 1
    return {"hourly": hourly, "events": events}
