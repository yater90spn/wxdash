"""NOAA CO-OPS tide predictions and water temperature (US stations).

Open-Meteo's sea_level_height_msl is modelled at ~8 km and is explicitly
unreliable near coasts, so for surfing/sailing a real tide station is
preferred. Find stations at https://tidesandcurrents.noaa.gov/
(e.g. 8531680 = Sandy Hook, NJ).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import requests

API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def _get(params, session=None, timeout=20):
    base = {
        "application": "wxdash",
        "time_zone": "lst_ldt",
        "units": "english",
        "format": "json",
    }
    base.update(params)
    s = session or requests
    r = s.get(API, params=base, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", "NOAA error"))
    return j


def fetch_tides(station, tz, days=7, session=None):
    """Hourly predictions + high/low events, as tz-aware datetimes."""
    start = datetime.now(tz).date() - timedelta(days=1)
    end = start + timedelta(days=days + 1)
    common = {
        "station": station,
        "product": "predictions",
        "datum": "MLLW",
        "begin_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
    }
    hourly = _get({**common, "interval": "h"}, session)["predictions"]
    hilo = _get({**common, "interval": "hilo"}, session)["predictions"]

    def parse(t):
        return datetime.strptime(t, "%Y-%m-%d %H:%M").replace(tzinfo=tz)

    return {
        "hourly": [(parse(p["t"]), float(p["v"])) for p in hourly],
        "events": [(parse(p["t"]), float(p["v"]), p["type"]) for p in hilo],
    }


def fetch_water_temp(station, session=None):
    """Latest observed water temp (°F) or None if station lacks a sensor."""
    try:
        j = _get({"station": station, "product": "water_temperature",
                  "date": "latest"}, session)
        return float(j["data"][-1]["v"])
    except Exception:
        return None
