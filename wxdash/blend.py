"""Turn raw Open-Meteo/NOAA payloads into a single list of hourly records.

Each record is a dict with the blended value for every variable, plus the
per-model values and a model "spread" so the dashboard can show confidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta

M_TO_FT = 3.28084

# Ordered preference per variable. Models returning null for an hour (HRRR
# beyond ~48 h, variables a model doesn't produce) are skipped automatically.
DEFAULT_PRIORITY = ["ncep_hrrr_conus", "ncep_nbm_conus", "ncep_gfs_seamless"]
VAR_PRIORITY = {
    # HRRR has no precip probability; NBM's is calibrated, GFS's is ensemble-based.
    "precipitation_probability": ["ncep_nbm_conus", "ncep_gfs_seamless"],
    # Only GFS produces UV.
    "uv_index": ["ncep_gfs_seamless"],
}
SPREAD_VARS = ["temperature_2m", "precipitation_probability", "wind_speed_10m",
               "wind_gusts_10m", "precipitation"]


def _series(hourly, var, model, n_models):
    if n_models == 1:
        return hourly.get(var)
    return hourly.get(f"{var}_{model}")


def blend_forecast(raw, tz, priority=None, var_priority=None):
    models = raw["_models"]
    priority = priority or [m for m in DEFAULT_PRIORITY if m in models] + \
        [m for m in models if m not in DEFAULT_PRIORITY]
    vp = {**VAR_PRIORITY, **(var_priority or {})}
    h = raw["hourly"]
    times = [datetime.fromtimestamp(t, tz) for t in h["time"]]
    # Recover base variable names by stripping the model suffix
    base_vars = set()
    for k in h:
        if k == "time":
            continue
        base = k
        for m in models:
            if k.endswith("_" + m):
                base = k[: -(len(m) + 1)]
                break
        base_vars.add(base)

    out = []
    for i, t in enumerate(times):
        rec = {"time": t, "models": {}, "spread": {}}
        for var in base_vars:
            per_model = {}
            for m in models:
                s = _series(h, var, m, len(models))
                if s is not None and i < len(s) and s[i] is not None:
                    per_model[m] = s[i]
            order = vp.get(var, priority)
            val = next((per_model[m] for m in order if m in per_model), None)
            if val is None and per_model:  # model outside the priority list
                val = next(iter(per_model.values()))
            rec[var] = val
            if var in SPREAD_VARS and len(per_model) > 1:
                vals = list(per_model.values())
                rec["spread"][var] = max(vals) - min(vals)
            if per_model:
                rec["models"][var] = per_model
        rec["source"] = next((m for m in priority
                              if m in rec["models"].get("temperature_2m", {})), None)
        out.append(rec)

    # Visibility comes back in ft or m depending on unit settings; normalise to miles.
    units = raw.get("hourly_units", {})
    vis_unit = next((u for k, u in units.items() if k.startswith("visibility")), "m")
    div = 5280.0 if vis_unit in ("ft", "feet") else 1609.34
    for rec in out:
        v = rec.get("visibility")
        rec["visibility_mi"] = None if v is None else v / div

    daily = raw.get("daily", {})
    sun = []
    for sr, ss in zip(daily.get("sunrise", []), daily.get("sunset", [])):
        sun.append((datetime.fromtimestamp(sr, tz), datetime.fromtimestamp(ss, tz)))
    return out, sun


def attach_marine(hours, raw_marine, tz):
    if not raw_marine:
        return
    mh = raw_marine["hourly"]
    idx = {datetime.fromtimestamp(t, tz): i for i, t in enumerate(mh["time"])}
    for rec in hours:
        i = idx.get(rec["time"])
        if i is None:
            continue

        def g(k):
            s = mh.get(k)
            return s[i] if s and i < len(s) else None

        def ft(k):
            v = g(k)
            return None if v is None else v * M_TO_FT

        rec["wave_ft"] = ft("wave_height")
        rec["swell_ft"] = ft("swell_wave_height")
        rec["swell_dir"] = g("swell_wave_direction")
        rec["swell_period"] = g("swell_wave_peak_period") or g("swell_wave_period")
        rec["swell2_ft"] = ft("secondary_swell_wave_height")
        rec["swell2_dir"] = g("secondary_swell_wave_direction")
        rec["swell2_period"] = g("secondary_swell_wave_period")
        rec["wind_wave_ft"] = ft("wind_wave_height")
        sst = g("sea_surface_temperature")
        rec["water_f"] = None if sst is None else sst * 9 / 5 + 32
        lvl = ft("sea_level_height_msl")
        if lvl is not None and rec.get("tide_ft") is None:
            rec["tide_ft"] = lvl
            rec["tide_source"] = "model"


def attach_tides(hours, tides):
    """Overlay NOAA station predictions (preferred over the model)."""
    if not tides:
        return
    table = {t.replace(minute=0, second=0): v for t, v in tides["hourly"]}
    for rec in hours:
        v = table.get(rec["time"])
        if v is not None:
            rec["tide_ft"] = v
            rec["tide_source"] = "noaa"
    for rec in hours:
        rec.setdefault("_tide_events", tides["events"])


def tide_state(hours, i, events=None):
    """Return (trend, phase) at index i: trend rising/falling/slack,
    phase low/mid/high relative to the surrounding tidal range."""
    t = hours[i]
    if t.get("tide_ft") is None:
        return None, None
    prev = hours[i - 1]["tide_ft"] if i > 0 and hours[i - 1].get("tide_ft") is not None else None
    nxt = hours[i + 1]["tide_ft"] if i + 1 < len(hours) and hours[i + 1].get("tide_ft") is not None else None
    delta = None
    if prev is not None and nxt is not None:
        delta = (nxt - prev) / 2
    elif nxt is not None:
        delta = nxt - t["tide_ft"]
    elif prev is not None:
        delta = t["tide_ft"] - prev
    trend = "slack" if delta is None or abs(delta) < 0.15 else ("rising" if delta > 0 else "falling")
    lo_i, hi_i = max(0, i - 7), min(len(hours), i + 7)
    window = [h["tide_ft"] for h in hours[lo_i:hi_i] if h.get("tide_ft") is not None]
    lo, hi = min(window), max(window)
    frac = 0.5 if hi - lo < 0.1 else (t["tide_ft"] - lo) / (hi - lo)
    phase = "low" if frac < 0.3 else ("high" if frac > 0.7 else "mid")
    return trend, phase


def next_tide_event(events, after):
    if not events:
        return None
    for t, v, typ in events:
        if t >= after:
            return {"time": t, "ft": v, "type": "High" if typ == "H" else "Low"}
    return None
