"""The last ~24 hours: what actually happened vs what was forecast a day earlier.

- Actual: NWS station observations (api.weather.gov), nearest station to the
  location found automatically (or set `obs_station:` in config.yaml).
- Forecast: Open-Meteo Previous Runs API, `*_previous_day1` = the value that was
  predicted 24 hours before each hour.
Nothing is stored locally; both services keep several days of history.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import requests

PREV_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
NWS = "https://api.weather.gov"
UA = "wxdash home weather dashboard (github.com/yater90spn/wxdash)"


# ---------------- forecast as it stood a day earlier ----------------
def fetch_prev_forecast(lat, lon, tz, session=None, timeout=20):
    s = session or requests
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m_previous_day1,apparent_temperature_previous_day1,precipitation_previous_day1",
        "past_days": 2, "forecast_days": 1,
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "timeformat": "unixtime", "timezone": "auto",
    }
    r = s.get(PREV_URL, params=params, timeout=timeout)
    r.raise_for_status()
    h = r.json().get("hourly", {})
    out = {}
    for i, t in enumerate(h.get("time", [])):
        dt = (datetime.fromtimestamp(t, tz) if isinstance(t, (int, float))
              else datetime.fromisoformat(t).replace(tzinfo=tz))
        out[dt] = {
            "fc_temp": _at(h, "temperature_2m_previous_day1", i),
            "fc_feels": _at(h, "apparent_temperature_previous_day1", i),
            "fc_precip": _at(h, "precipitation_previous_day1", i),
        }
    return out


def _at(h, k, i):
    v = h.get(k)
    return v[i] if v and i < len(v) else None


# ---------------- actual observations ----------------
_station_cache = {}


def find_station(lat, lon, session=None, timeout=20):
    """Nearest NWS observation station that is reporting temperature."""
    key = (round(lat, 3), round(lon, 3))
    if key in _station_cache:
        return _station_cache[key]
    s = session or requests
    hdr = {"User-Agent": UA, "Accept": "application/geo+json"}
    r = s.get(f"{NWS}/points/{lat:.4f},{lon:.4f}/stations", headers=hdr, timeout=timeout)
    r.raise_for_status()
    feats = r.json().get("features", [])
    for f in feats[:5]:
        p = f.get("properties", {})
        sid = p.get("stationIdentifier")
        if not sid:
            continue
        try:
            o = s.get(f"{NWS}/stations/{sid}/observations/latest", headers=hdr, timeout=timeout).json()
            if (o.get("properties", {}).get("temperature") or {}).get("value") is not None:
                _station_cache[key] = (sid, p.get("name", sid))
                return _station_cache[key]
        except Exception:
            continue
    raise RuntimeError("no reporting NWS station nearby")


def _val(prop, kind):
    """Convert an NWS quantity {value, unitCode} to °F / mph / inches / %."""
    if not prop or prop.get("value") is None:
        return None
    v, u = prop["value"], (prop.get("unitCode") or "")
    if kind == "temp":
        return v * 9 / 5 + 32 if u.endswith("degC") else v
    if kind == "speed":
        if u.endswith("km_h-1"):
            return v * 0.621371
        if u.endswith("m_s-1"):
            return v * 2.23694
        if u.endswith("kn") or u.endswith("kt"):
            return v * 1.15078
        return v
    if kind == "precip":
        if u.endswith(":mm"):
            return v / 25.4
        if u.endswith(":m"):
            return v * 39.3701
        return v
    return v


def apparent_f(temp_f, rh, wind_mph):
    """Australian BoM apparent temperature (shade), the same family of formula as
    Open-Meteo's feels-like, so actual and forecast compare like for like."""
    if temp_f is None:
        return None
    if rh is None or wind_mph is None:
        return temp_f
    ta = (temp_f - 32) * 5 / 9
    e = rh / 100 * 6.105 * math.exp(17.27 * ta / (237.7 + ta))
    at = ta + 0.33 * e - 0.70 * (wind_mph * 0.44704) - 4.0
    return at * 9 / 5 + 32


def fetch_observations(station, tz, hours=30, session=None, timeout=20):
    """Hourly actuals keyed by local top-of-hour datetimes."""
    s = session or requests
    hdr = {"User-Agent": UA, "Accept": "application/geo+json"}
    start = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = s.get(f"{NWS}/stations/{station}/observations", params={"start": start},
              headers=hdr, timeout=timeout)
    r.raise_for_status()
    best = {}   # hour -> (distance from top of hour, record)
    for f in r.json().get("features", []):
        p = f.get("properties", {})
        try:
            ts = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00")).astimezone(tz)
        except Exception:
            continue
        hour = (ts + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        dist = abs((ts - hour).total_seconds())
        temp = _val(p.get("temperature"), "temp")
        if temp is None:
            continue
        rh = p.get("relativeHumidity", {}).get("value") if p.get("relativeHumidity") else None
        wind = _val(p.get("windSpeed"), "speed")
        rec = {
            "obs_temp": temp,
            "obs_feels": apparent_f(temp, rh, wind),
            "obs_dew": _val(p.get("dewpoint"), "temp"),
            "obs_wind": wind,
            "obs_gust": _val(p.get("windGust"), "speed"),
            "obs_dir": (p.get("windDirection") or {}).get("value"),
            "obs_precip": _val(p.get("precipitationLastHour"), "precip"),
            "obs_text": p.get("textDescription"),
        }
        if hour not in best or dist < best[hour][0]:
            # keep the observation closest to the top of the hour, but don't lose a
            # rain total reported by the routine hourly report
            prev = best.get(hour, (None, {}))[1]
            if rec["obs_precip"] is None and prev.get("obs_precip") is not None:
                rec["obs_precip"] = prev["obs_precip"]
            best[hour] = (dist, rec)
        elif rec["obs_precip"] is not None and best[hour][1].get("obs_precip") is None:
            best[hour][1]["obs_precip"] = rec["obs_precip"]
    return {h: rec for h, (_, rec) in best.items()}
