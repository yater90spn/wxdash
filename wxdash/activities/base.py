"""Shared scoring helpers and the Activity base class.

Every activity turns a slice of hourly records into a "card":
  - a 0–10 score per hour and for the whole window
  - a short verdict ("chilly and breezy", "promising")
  - metric lines for the dashboard
  - one advice line ("Bring: …", "Comfort: …", "Plan: …")

Scoring uses piecewise-linear curves so every threshold can be tuned from
config.yaml without touching code: a curve is a list of [x, score] points.
"""
from __future__ import annotations

import copy
import math
from statistics import mean

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

THUNDER_CODES = {95, 96, 97, 99}
RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}
SNOW_CODES = {71, 73, 75, 77, 85, 86}
FOG_CODES = {45, 48}


def curve(x, points):
    """Piecewise-linear interpolation, clamped at the ends."""
    if x is None:
        return None
    pts = sorted(points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def compass(deg):
    if deg is None:
        return "—"
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def angle_diff(a, b):
    """Smallest absolute difference between two bearings (0–180)."""
    return abs((a - b + 180) % 360 - 180)


def mean_dir(degs, weights=None):
    degs = [d for d in degs if d is not None]
    if not degs:
        return None
    weights = weights or [1] * len(degs)
    x = sum(w * math.cos(math.radians(d)) for d, w in zip(degs, weights))
    y = sum(w * math.sin(math.radians(d)) for d, w in zip(degs, weights))
    return math.degrees(math.atan2(y, x)) % 360


def vals(hours, key):
    return [h[key] for h in hours if h.get(key) is not None]


def rng(values, fmt="{:.0f}", unit=""):
    """'51–56°F' or '54°F' when the range collapses."""
    if not values:
        return "—"
    lo, hi = fmt.format(min(values)), fmt.format(max(values))
    return f"{lo}{unit}" if lo == hi else f"{lo}–{hi}{unit}"


def clamp(x, lo=0.0, hi=10.0):
    return max(lo, min(hi, x))


def deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def sky_text(hours):
    codes = [h.get("weather_code") for h in hours]
    if any(c in THUNDER_CODES for c in codes):
        return "Thunderstorms possible"
    if any(c in SNOW_CODES for c in codes):
        return "Snow"
    rainy = sum(c in RAIN_CODES for c in codes)
    if rainy >= max(1, len(codes) // 2):
        return "Rain"
    if rainy:
        return "Showers at times"
    if any(c in FOG_CODES for c in codes):
        return "Fog"
    cc = vals(hours, "cloud_cover")
    c = mean(cc) if cc else 50
    if c < 15:
        return "Sunny" if any(h.get("is_day") for h in hours) else "Clear"
    if c < 35:
        return "Mostly sunny" if any(h.get("is_day") for h in hours) else "Mostly clear"
    if c < 60:
        return "Partly cloudy"
    if c < 85:
        return "Mostly cloudy"
    return "Overcast"


def rain_risk(hours, bands=(20, 40, 60)):
    pops = vals(hours, "precipitation_probability")
    pop = max(pops) if pops else 0
    amt = sum(vals(hours, "precipitation"))
    if pop < bands[0]:
        label = "Low rain risk"
    elif pop < bands[1]:
        label = f"Rain possible ({pop:.0f}%)"
    elif pop < bands[2]:
        label = f"Showers likely ({pop:.0f}%)"
    else:
        label = f"Rain likely ({pop:.0f}%)"
    if amt >= 0.05:
        label += f", ~{amt:.2f} in"
    return label, pop, amt


def wind_line(hours, unit="mph", conv=1.0, prefix=""):
    sp = [v * conv for v in vals(hours, "wind_speed_10m")]
    gu = [v * conv for v in vals(hours, "wind_gusts_10m")]
    d = mean_dir(vals(hours, "wind_direction_10m"), sp or None)
    s = f"{prefix}{compass(d)} {rng(sp)} {unit}"
    if gu and sp and max(gu) - max(sp) >= 5:
        s += f", gusts {max(gu):.0f} {unit}"
    return s, sp, gu, d


def confidence(hours, now):
    """Plain-language forecast confidence from lead time and model spread."""
    if not hours:
        return ""
    lead_h = (hours[0]["time"] - now).total_seconds() / 3600
    t_spread = max([h["spread"].get("temperature_2m", 0) for h in hours] or [0])
    p_spread = max([h["spread"].get("precipitation_probability", 0) for h in hours] or [0])
    w_spread = max([h["spread"].get("wind_speed_10m", 0) for h in hours] or [0])
    src = {h.get("source") for h in hours}
    has_hrrr = "ncep_hrrr_conus" in src
    if lead_h > 120:
        base = "Low confidence (5+ days out)"
    elif t_spread > 7 or p_spread > 35 or w_spread > 8:
        base = "Models disagree"
    elif lead_h > 72:
        base = "Moderate confidence"
    else:
        base = "Models agree"
    detail = []
    if t_spread > 4:
        detail.append(f"temp ±{t_spread / 2:.0f}°")
    if p_spread > 20:
        detail.append(f"rain {p_spread:.0f}% spread")
    if w_spread > 5:
        detail.append(f"wind ±{w_spread / 2:.0f}")
    tag = "HRRR" if has_hrrr else ("NBM" if "ncep_nbm_conus" in src else "GFS")
    return base + (f" · {', '.join(detail)}" if detail else "") + f" · {tag}"


class Activity:
    """Subclass and implement score_hour() and summarize()."""

    kind = "base"
    label = "Activity"
    advice_label = "Plan"
    defaults: dict = {}
    needs_marine = False

    def __init__(self, rules=None, place=None):
        self.rules = deep_merge(self.defaults, rules or {})
        self.place = place or {}

    def score_hour(self, h, ctx) -> tuple[float, dict]:
        """Return (score 0–10, factor breakdown) for one hour."""
        raise NotImplementedError

    def summarize(self, hours, scores, factors, ctx) -> dict:
        raise NotImplementedError

    def evaluate(self, hours, ctx):
        scores, factors = [], []
        for h in hours:
            s, f = self.score_hour(h, ctx)
            scores.append(round(clamp(s), 1))
            factors.append(f)
        # A window is only as good as its worst stretch: blend mean and min.
        overall = round(0.7 * mean(scores) + 0.3 * min(scores), 1) if scores else 0
        card = self.summarize(hours, scores, factors, ctx)
        card.setdefault("score", overall)
        card["hourly"] = [{"t": h["time"].isoformat(), "s": s} for h, s in zip(hours, scores)]
        card["confidence"] = confidence(hours, ctx["now"])
        card["kind"] = self.kind
        card["advice_label"] = card.get("advice_label", self.advice_label)
        return card


def dominant(penalties: dict, floor=0.4):
    """Name of the biggest penalty, or None if nothing matters much."""
    if not penalties:
        return None
    k, v = max(penalties.items(), key=lambda kv: kv[1])
    return k if v >= floor else None
