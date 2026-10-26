"""Surfing. Everything directional is relative to the beach.

Spot config:
  facing:        compass bearing the beach looks out toward (ocean side), e.g. 105 = ESE
  swell_window:  [from_deg, to_deg] directions swell can reach the spot (default facing ±75°)
  wave_ft:       {min, ideal: [lo, hi], max} for your ability and board
  tide:          {phase: [low|mid|high...], trend: [rising|falling...]} preferences, or omit
"""
from statistics import mean

from ..blend import next_tide_event, tide_state
from .base import (Activity, angle_diff, compass, curve, mean_dir, rng, sky_text, vals)


def _in_window(d, lo, hi):
    if d is None:
        return False
    lo, hi, d = lo % 360, hi % 360, d % 360
    return lo <= d <= hi if lo <= hi else (d >= lo or d <= hi)


def wetsuit(water_f):
    if water_f is None:
        return None
    if water_f >= 72:
        return "trunks / rash guard"
    if water_f >= 66:
        return "springsuit or 2 mm"
    if water_f >= 60:
        return "3/2"
    if water_f >= 54:
        return "4/3 + booties"
    if water_f >= 48:
        return "5/4 hooded, booties, gloves"
    return "6/5 hooded, 7 mm booties, lobster mitts"


class Surf(Activity):
    kind = "surf"
    label = "Surfing"
    advice_label = "Comfort"
    needs_marine = True
    defaults = {
        "wave_ft": {"min": 1.5, "ideal": [3, 6], "max": 9},
        "period": [[4, 1], [6, 4], [8, 7], [10, 9], [12, 10], [16, 10]],
        "glassy_below": 5,  # mph — any direction is fine this light
        "offshore": [[0, 10], [15, 10], [22, 7], [30, 4]],
        "cross": [[0, 10], [5, 9], [10, 7], [15, 4.5], [22, 2.5]],
        "onshore": [[0, 10], [5, 8], [8, 5.5], [12, 3.5], [18, 1.5], [25, 0.5]],
        "weights": {"swell": 0.6, "wind": 0.4},
        "tide_penalty": 1.5,
    }

    def __init__(self, rules=None, place=None):
        super().__init__(rules, place)
        self.facing = float(self.place.get("facing", 90))
        w = self.place.get("swell_window") or [self.facing - 75, self.facing + 75]
        self.window = w
        self.wave = {**self.rules["wave_ft"], **self.place.get("wave_ft", {})}
        self.tide_pref = self.place.get("tide") or {}

    def wind_kind(self, wind_from):
        off = (self.facing + 180) % 360  # offshore wind blows FROM the land side
        d = angle_diff(wind_from, off)
        return "offshore" if d <= 45 else ("onshore" if d >= 135 else "cross-shore")

    def score_hour(self, h, ctx):
        r = self.rules
        ht, per, sdir = h.get("swell_ft"), h.get("swell_period"), h.get("swell_dir")
        if ht is None:
            ht, per, sdir = h.get("wave_ft") or 0, h.get("wave_period") or 6, h.get("swell_dir")
        lo, hi = self.wave["ideal"]
        mn, mx = self.wave["min"], self.wave["max"]
        h_score = curve(ht, [[0, 0], [mn * 0.6, 0.5], [mn, 3], [lo, 8], [hi, 10],
                              [mx, 6], [mx + 4, 1]])
        p_score = curve(per or 0, r["period"])
        if sdir is not None:
            off_axis = angle_diff(sdir, self.facing)
            d_mult = 1.0 if off_axis <= 30 else 0.85 if off_axis <= 55 else 0.55 if off_axis <= 80 else 0.15
            if not _in_window(sdir, *self.window):
                d_mult = min(d_mult, 0.2)
        else:
            d_mult = 0.8
        swell = (0.6 * h_score + 0.4 * p_score) * d_mult

        spd = h.get("wind_speed_10m") or 0
        wdir = h.get("wind_direction_10m")
        kind = self.wind_kind(wdir) if wdir is not None else "cross-shore"
        if spd < r["glassy_below"]:
            wind = 10
        else:
            wind = curve(spd, r["offshore" if kind == "offshore" else
                               "onshore" if kind == "onshore" else "cross"])

        w = r["weights"]
        score = w["swell"] * swell + w["wind"] * wind
        if ht < mn:
            score = min(score, 2.5)

        i = ctx["index_of"].get(h["time"])
        trend, phase = tide_state(ctx["all_hours"], i) if i is not None else (None, None)
        tide_pen = 0
        if self.tide_pref and phase:
            if self.tide_pref.get("phase") and phase not in self.tide_pref["phase"]:
                tide_pen += r["tide_penalty"]
            if self.tide_pref.get("trend") and trend not in self.tide_pref["trend"]:
                tide_pen += r["tide_penalty"] / 2
        score -= tide_pen
        return score, {"swell": swell, "wind": wind, "wind_kind": kind,
                       "tide": (trend, phase), "tide_pen": tide_pen}

    def summarize(self, hours, scores, factors, ctx):
        avg = mean(scores) if scores else 0
        verdict = ("flat" if avg < 1.5 else "poor" if avg < 3.5 else "fair" if avg < 5
                   else "promising" if avg < 6.8 else "good" if avg < 8.5 else "firing")

        air = vals(hours, "temperature_2m")
        feels = vals(hours, "apparent_temperature")
        water = ctx.get("water_obs_f") or (mean(vals(hours, "water_f")) if vals(hours, "water_f") else None)

        sp = vals(hours, "wind_speed_10m")
        wdir = mean_dir(vals(hours, "wind_direction_10m"), sp or None)
        kinds = [f["wind_kind"] for f in factors]
        kind = max(set(kinds), key=kinds.count) if kinds else "—"
        if sp and max(sp) < self.rules["glassy_below"]:
            wind_s = f"Glassy — {compass(wdir)} {rng(sp)} mph"
        else:
            wind_s = f"{kind.capitalize()} {compass(wdir)} {rng(sp)} mph"
        gu = vals(hours, "wind_gusts_10m")
        if gu and sp and max(gu) - max(sp) >= 6:
            wind_s += f", gusts {max(gu):.0f}"

        sh = vals(hours, "swell_ft") or vals(hours, "wave_ft")
        sper = vals(hours, "swell_period")
        sdir = mean_dir(vals(hours, "swell_dir"))
        swell_s = (f"{compass(sdir)} swell {mean(sh):.1f} ft @ {mean(sper):.0f} sec"
                   if sh and sper else "Swell data unavailable")
        s2 = vals(hours, "swell2_ft")
        if s2 and mean(s2) >= 1.0:
            swell_s += f" + {compass(mean_dir(vals(hours, 'swell2_dir')))} {mean(s2):.1f} ft"

        tides = [f["tide"] for f in factors if f["tide"][0]]
        if tides:
            trend, phase = tides[len(tides) // 2]
            tide_s = f"{trend.capitalize()} tide" if trend != "slack" else f"Slack {phase} tide"
            ev = next_tide_event(hours[0].get("_tide_events"), hours[0]["time"])
            if ev:
                tide_s += f" · {ev['type']} {ev['time'].strftime('%-I:%M %p')}"
            if hours[0].get("tide_source") == "model":
                tide_s += " (model)"
        else:
            tide_s = "Tide data unavailable"

        # Comfort: changing on the beach vs. once in the water
        f0 = feels[0] if feels else (air[0] if air else 60)
        spd0 = sp[0] if sp else 0
        change = ("frigid getting changed" if f0 < 40 else "cold getting changed" if f0 < 55
                  else "brisk getting changed" if f0 < 65 else "easy getting changed")
        if spd0 >= 15 and f0 < 65:
            change = change.replace("getting changed", "and windy getting changed")
        suit = wetsuit(water)
        if water is None:
            once = "check water temp"
        elif water < 48:
            once = f"cold even suited — {suit}"
        else:
            once = f"comfortable once suited in a {suit}"

        air_line = f"Air {rng(air, unit='°F')}"
        if water is not None:
            air_line += f" / water {water:.0f}°F"
        return {
            "verdict": verdict,
            "score_label": "Conditions",
            "lines": [air_line, wind_s, swell_s, tide_s, sky_text(hours)],
            "advice": f"{change}, {once}.",
        }
