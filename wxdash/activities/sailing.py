"""Sailing — wind in knots, gustiness, chop, cold, storms."""
from statistics import mean

from .base import (THUNDER_CODES, Activity, compass, curve, mean_dir, rain_risk, rng,
                   sky_text, vals)

KT = 0.868976  # mph → knots


class Sailing(Activity):
    kind = "sailing"
    label = "Sailing"
    advice_label = "Plan"
    needs_marine = True
    defaults = {
        "wind_kt": {"ideal": [8, 15], "reef": 18, "max": 23},
        "gust_spread_kt": 8,   # gust minus sustained before it counts as "puffy"
        "wave_ft_max": 3,      # protected bay default; raise for open water
        "visibility_mi_min": 2,
        "cold_feels": [[30, 3], [40, 1.8], [50, 0.8], [58, 0]],
        "rain": [[0, 0], [30, 0], [50, 0.8], [70, 2], [100, 3]],
    }

    def __init__(self, rules=None, place=None):
        super().__init__(rules, place)
        self.wk = {**self.rules["wind_kt"], **self.place.get("wind_kt", {})}

    def score_hour(self, h, ctx):
        r, wk = self.rules, self.wk
        kt = (h.get("wind_speed_10m") or 0) * KT
        gkt = (h.get("wind_gusts_10m") or 0) * KT
        lo, hi = wk["ideal"]
        base = curve(kt, [[0, 0], [3, 1.5], [6, 5.5], [lo, 10], [hi, 10],
                          [wk["reef"], 6.5], [wk["max"], 2.5], [wk["max"] + 6, 0]])
        spread = gkt - kt
        gust_pen = max(0, spread - r["gust_spread_kt"]) * 0.35
        if gkt > wk["max"]:
            gust_pen += 1.5
        waves = h.get("wave_ft") or 0
        wave_pen = max(0, waves - r["wave_ft_max"]) * 1.2
        cold = curve(h.get("apparent_temperature") or 60, r["cold_feels"])
        rain = curve(h.get("precipitation_probability") or 0, r["rain"])
        vis_mi = h.get("visibility_mi")
        vis_pen = 3 if vis_mi is not None and vis_mi < r["visibility_mi_min"] else 0
        score = base - gust_pen - wave_pen - cold - rain - vis_pen
        storm = h.get("weather_code") in THUNDER_CODES
        if storm:
            score = min(score, 0.5)
        return score, {"kt": kt, "gkt": gkt, "storm": storm, "vis": vis_pen > 0}

    def summarize(self, hours, scores, factors, ctx):
        wk = self.wk
        kts = [f["kt"] for f in factors]
        gkts = [f["gkt"] for f in factors]
        avg, peak = (mean(kts), max(gkts)) if kts else (0, 0)
        lo, hi = wk["ideal"]
        if any(f["storm"] for f in factors):
            verdict = "thunderstorms — stay ashore"
        elif avg < 4:
            verdict = "drifter"
        elif avg < lo - 1:
            verdict = "light air"
        elif avg <= hi + 1 and peak < wk["reef"]:
            verdict = "ideal breeze"
        elif avg < wk["reef"]:
            verdict = "sporty"
        elif avg < wk["max"]:
            verdict = "heavy air"
        else:
            verdict = "overpowered"

        d = mean_dir(vals(hours, "wind_direction_10m"), kts or None)
        wind_s = f"{compass(d)} {rng(kts)} kt"
        if gkts and peak - max(kts) >= 4:
            wind_s += f", gusts {peak:.0f} kt"
        spread = mean(g - k for g, k in zip(gkts, kts)) if kts else 0
        steady = "steady" if spread < 5 else "puffy" if spread < 9 else "very puffy"
        trend = ""
        if len(kts) >= 2:
            delta = kts[-1] - kts[0]
            trend = "building" if delta >= 3 else "easing" if delta <= -3 else "holding"
        wave = vals(hours, "wave_ft")
        sea = f"Waves {rng(wave, fmt='{:.1f}', unit=' ft')}" if wave else ""
        air = vals(hours, "temperature_2m")
        water = ctx.get("water_obs_f") or (mean(vals(hours, "water_f")) if vals(hours, "water_f") else None)
        temp_s = f"Air {rng(air, unit='°F')}" + (f" / water {water:.0f}°F" if water else "")
        rl, pop, _ = rain_risk(hours, (30, 50, 70))

        plan = []
        if "storm" in verdict:
            plan.append("watch radar; don't leave the dock")
        elif peak >= wk["reef"] or avg > hi + 2:
            plan.append("reef before you leave the dock")
        elif avg < lo - 1:
            plan.append("full sail; bring the big headsail")
        else:
            plan.append("full main")
        if trend == "building":
            plan.append("breeze builds through the window — head upwind first")
        elif trend == "easing":
            plan.append("breeze fades late — don't get caught far downwind")
        fmin = min(vals(hours, "apparent_temperature") or [60])
        if water and water < 60:
            plan.append("cold water — life jacket on, dress for immersion")
        elif fmin < 55:
            plan.append("foulies + warm layers")
        if any(f["vis"] for f in factors):
            plan.append("poor visibility")
        if pop >= 50:
            plan.append("rain gear")

        lines = [wind_s + f" · {steady}" + (f", {trend}" if trend else "")]
        if sea:
            lines.append(sea)
        lines += [temp_s, sky_text(hours), rl]
        return {"verdict": verdict, "score_label": "Sailing",
                "lines": lines, "advice": "; ".join(plan) + "."}
