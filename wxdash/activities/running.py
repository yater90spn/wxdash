"""Running — you generate heat, so the ideal is much colder than standing around."""
from statistics import mean

from .base import (Activity, compass, curve, mean_dir, rain_risk, rng, sky_text, vals)


class Running(Activity):
    kind = "running"
    label = "Running"
    advice_label = "Wear"
    defaults = {
        "feels_like": [[0, 1], [15, 4], [28, 7], [38, 9.5], [45, 10], [55, 10],
                       [62, 8.5], [70, 6.5], [78, 4.5], [85, 2.5], [92, 1]],
        # Dew point is the best single measure of how hard humid running feels.
        "dew_point": [[50, 0], [55, 0.4], [60, 1.2], [65, 2.4], [70, 3.8], [75, 5]],
        "wet_bulb_danger": 76,  # °F wet-bulb: serious heat-stress territory
        "wind": [[0, 0], [10, 0], [15, 0.8], [20, 1.8], [30, 3.5]],
        "rain": [[0, 0], [40, 0], [60, 0.6], [80, 1.2], [100, 1.5]],
        "dress_offset": 15,  # dress as if it's this many °F warmer
    }

    def score_hour(self, h, ctx):
        r = self.rules
        fl = h.get("apparent_temperature")
        base = curve(fl, r["feels_like"]) if fl is not None else 6
        dew = curve(h.get("dew_point_2m") or 40, r["dew_point"])
        wind = curve(h.get("wind_speed_10m") or 0, r["wind"])
        rain = curve(h.get("precipitation_probability") or 0, r["rain"])
        if (h.get("precipitation") or 0) > 0.1:
            rain += 1
        uv = 0.5 if (h.get("uv_index") or 0) >= 7 else 0
        score = base - dew - wind - rain - uv
        wb = h.get("wet_bulb_temperature_2m")
        heat_risk = wb is not None and wb >= r["wet_bulb_danger"]
        if heat_risk:
            score = min(score, 2)
        return score, {"dew": dew, "heat_risk": heat_risk, "dark": not h.get("is_day", 1)}

    def summarize(self, hours, scores, factors, ctx):
        r = self.rules
        temps = vals(hours, "temperature_2m")
        feels = vals(hours, "apparent_temperature")
        dews = vals(hours, "dew_point_2m")
        sp = vals(hours, "wind_speed_10m")
        wdir = mean_dir(vals(hours, "wind_direction_10m"), sp or None)
        rl, pop, _ = rain_risk(hours, (30, 50, 70))
        avg = mean(scores) if scores else 0
        verdict = ("rough" if avg < 3 else "tough" if avg < 5 else "decent" if avg < 6.5
                   else "good" if avg < 8 else "PR weather")
        if any(f["heat_risk"] for f in factors):
            verdict = "heat-stress risk"

        dress = (feels[0] if feels else 50) + r["dress_offset"]
        if dress >= 70:
            wear = ["singlet, shorts"]
        elif dress >= 60:
            wear = ["T-shirt, shorts"]
        elif dress >= 50:
            wear = ["long sleeve, shorts"]
        elif dress >= 40:
            wear = ["long sleeve, tights, light gloves"]
        elif dress >= 30:
            wear = ["base layer + wind jacket, tights, gloves, hat"]
        else:
            wear = ["thermal base + jacket, tights, mittens, buff"]
        if dews and max(dews) >= 65:
            wear.append("carry water, slow the pace")
        uvs = vals(hours, "uv_index")
        if uvs and max(uvs) >= 5:
            wear.append("sunscreen")
        if sp and mean(sp) >= 10 and wdir is not None:
            wear.append(f"start out into the {compass(wdir)} wind, finish with it at your back")
        if any(f["dark"] for f in factors):
            wear.append("headlamp + reflective gear")
        if pop >= 60:
            wear.append("cap for the rain")

        dew_s = f"Dew point {rng(dews, unit='°F')}"
        if dews:
            m = max(dews)
            dew_s += (" · crisp" if m < 50 else " · comfortable" if m < 58 else
                      " · sticky" if m < 65 else " · humid" if m < 70 else " · oppressive")
        return {
            "verdict": verdict,
            "score_label": "Running",
            "lines": [
                f"{rng(temps, unit='°F')} · feels {rng(feels, unit='°F')}",
                dew_s,
                f"{compass(wdir)} {rng(sp)} mph",
                sky_text(hours),
                rl,
            ],
            "advice": "; ".join(wear) + ".",
        }
