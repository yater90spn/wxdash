"""Yard work. Set `task` in rules to tune: general | mow | leaves | spray | plant."""
from statistics import mean

from .base import Activity, compass, curve, mean_dir, rain_risk, rng, sky_text, vals


class Yardwork(Activity):
    kind = "yardwork"
    label = "Yard work"
    advice_label = "Plan"
    defaults = {
        "task": "general",
        "feels_like": [[25, 1], [35, 4], [45, 7.5], [52, 9.5], [55, 10], [70, 10],
                       [78, 8], [85, 5], [92, 2.5], [100, 0.5]],
        "dew_point": [[55, 0], [62, 0.5], [68, 1.5], [74, 3]],
        "rain": [[0, 0], [20, 0], [40, 1], [60, 3], [80, 5]],
        "wet_ground_in": 0.1,   # rain in prior 12 h that leaves grass wet
        "leaf_wind_mph": 12,
        "spray_wind_mph": 10,
        "spray_rainfree_h": 24,
    }

    def score_hour(self, h, ctx):
        r = self.rules
        task = r["task"]
        fl = h.get("apparent_temperature")
        score = curve(fl, r["feels_like"]) if fl is not None else 7
        score -= curve(h.get("dew_point_2m") or 50, r["dew_point"])
        score -= curve(h.get("precipitation_probability") or 0, r["rain"])
        if (h.get("precipitation") or 0) >= 0.02:
            score -= 3
        if (h.get("uv_index") or 0) >= 8:
            score -= 0.5
        spd = h.get("wind_speed_10m") or 0
        wet = ctx["rain_before"](h["time"], 12) >= r["wet_ground_in"]
        dewy = (h.get("temperature_2m") or 60) - (h.get("dew_point_2m") or 40) < 3 \
            and h["time"].hour < 11
        if task in ("mow", "general") and (wet or dewy):
            score -= 3 if task == "mow" else 1
        if task == "leaves":
            score -= max(0, spd - r["leaf_wind_mph"] + 3) * 0.5
            if wet:
                score -= 1.5  # wet leaves mat down
        if task == "spray":
            if spd > r["spray_wind_mph"]:
                score -= 5
            if ctx["rain_after"](h["time"], r["spray_rainfree_h"]) >= 0.05:
                score -= 4
        if task == "plant":
            score += 0.5 if 50 <= (fl or 0) <= 70 and (h.get("cloud_cover") or 0) > 50 else 0
        return score, {"wet": wet, "dewy": dewy, "spd": spd}

    def summarize(self, hours, scores, factors, ctx):
        r = self.rules
        task = r["task"]
        temps = vals(hours, "temperature_2m")
        feels = vals(hours, "apparent_temperature")
        sp = vals(hours, "wind_speed_10m")
        wdir = mean_dir(vals(hours, "wind_direction_10m"), sp or None)
        rl, pop, _ = rain_risk(hours)
        avg = mean(scores) if scores else 0
        verdict = ("skip it" if avg < 3 else "workable" if avg < 5.5
                   else "good" if avg < 7.5 else "perfect yard weather")

        plan = []
        if any(f["wet"] for f in factors):
            plan.append("ground still wet from earlier rain" +
                        (" — wait to mow" if task in ("mow", "general") else ""))
        elif any(f["dewy"] for f in factors):
            dry_by = next((h["time"] for h, f in zip(hours, factors) if not f["dewy"]), None)
            plan.append(f"dew on the grass{' until ~' + dry_by.strftime('%-I %p') if dry_by else ''}")
        if task == "leaves" and sp and mean(sp) > r["leaf_wind_mph"] + 4:
            plan.append(f"too windy to blow leaves ({compass(wdir)} {mean(sp):.0f} mph)")
        elif task == "leaves" and sp and max(sp) > r["leaf_wind_mph"] - 3 and wdir is not None:
            plan.append(f"breezy from the {compass(wdir)} — work downwind, pile leaves "
                        f"on the {compass(wdir + 180)} side")
        if task == "spray":
            if sp and max(sp) > r["spray_wind_mph"]:
                plan.append("too windy to spray — drift")
            if ctx["rain_after"](hours[-1]["time"], r["spray_rainfree_h"]) >= 0.05:
                plan.append(f"rain within {r['spray_rainfree_h']} h will wash it off")
        fmax = max(feels) if feels else 60
        fmin = min(feels) if feels else 60
        if fmax >= 85:
            plan.append("start early, water + shade breaks")
        elif fmin < 45:
            plan.append("gloves + warm layer")
        elif fmin < 55:
            plan.append("long sleeves, layer you can shed")
        uvs = vals(hours, "uv_index")
        if uvs and max(uvs) >= 6:
            plan.append("hat + sunscreen")
        if pop >= 40:
            plan.append("finish before the rain")
        if not plan:
            plan.append("no weather obstacles")

        return {
            "verdict": verdict,
            "score_label": "Yard",
            "lines": [
                f"{rng(temps, unit='°F')} · feels {rng(feels, unit='°F')}",
                f"{compass(wdir)} {rng(sp)} mph",
                sky_text(hours),
                rl,
                f"UV {max(uvs):.0f}" if uvs else "UV —",
            ],
            "advice": "; ".join(plan) + ".",
        }
