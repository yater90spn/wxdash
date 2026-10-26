"""Sitting outside for a few hours — kids' baseball, soccer sidelines, etc."""
from statistics import mean

from .base import Activity, curve, dominant, rain_risk, rng, sky_text, vals, wind_line


class Spectator(Activity):
    kind = "spectator"
    label = "Outdoor spectator"
    advice_label = "Bring"
    defaults = {
        # Your bands: 65–78 ideal, 55–65 cool, 45–55 cold, <45 uncomfortable.
        "feels_like": [[25, 1], [35, 3], [45, 6], [55, 8], [65, 9.6], [70, 10],
                       [78, 10], [84, 8.5], [90, 6], [97, 3], [105, 1]],
        # Penalty points. <7 negligible, 7–12 noticeable, 12–18 uncomfortable, 18+ major.
        "wind": [[0, 0], [7, 0], [12, 0.4], [18, 1.2], [25, 3], [35, 5]],
        # Sun adds comfort when it's cool and subtracts when it's hot.
        "sun_bonus_below": 65, "sun_bonus": 0.8,
        "sun_penalty_above": 80, "sun_penalty": 1.0,
        # Rain probability penalty: <20 ignore, 20–40 possible, 40–60 gear, >60 disruptive.
        "rain": [[0, 0], [20, 0], [40, 0.6], [60, 1.8], [80, 3.5], [100, 4.5]],
        "rain_bands": [20, 40, 60],
        "uv_sunscreen": 4,
    }

    def score_hour(self, h, ctx):
        r = self.rules
        fl = h.get("apparent_temperature")
        base = curve(fl, r["feels_like"]) if fl is not None else 5
        wind = curve(h.get("wind_speed_10m") or 0, r["wind"])
        gust_extra = 0.3 if (h.get("wind_gusts_10m") or 0) >= 25 else 0
        sunny = (h.get("cloud_cover") or 100) < 40 and (h.get("shortwave_radiation") or 0) > 250
        sun = 0.0
        if sunny and fl is not None and fl < r["sun_bonus_below"]:
            sun = r["sun_bonus"]
        elif sunny and fl is not None and fl > r["sun_penalty_above"]:
            sun = -r["sun_penalty"]
        rain = curve(h.get("precipitation_probability") or 0, r["rain"])
        if (h.get("precipitation") or 0) >= 0.05:
            rain += 1
        if h.get("weather_code") in (95, 96, 97, 99):
            rain += 4  # lightning stops games
        cold = max(0, 10 - base) if (fl or 70) < 70 else 0
        heat = max(0, 10 - base) if (fl or 70) > 78 else 0
        score = base - wind - gust_extra + sun - rain
        return score, {"wind": wind + gust_extra, "rain": rain, "cold": cold, "heat": heat}

    def summarize(self, hours, scores, factors, ctx):
        r = self.rules
        temps = vals(hours, "temperature_2m")
        feels = vals(hours, "apparent_temperature")
        wl, sp, gu, _ = wind_line(hours)
        rl, pop, amt = rain_risk(hours, r["rain_bands"])
        sky = sky_text(hours)
        fmin = min(feels) if feels else 60
        favg = mean(feels) if feels else 60
        wavg = mean(sp) if sp else 0

        # Verdict words
        t_word = ("frigid" if favg < 35 else "cold" if favg < 45 else "chilly" if favg < 55
                  else "cool" if favg < 65 else "pleasant" if favg < 78 else "warm" if favg < 86
                  else "hot" if favg < 94 else "very hot")
        w_word = ("" if wavg < 7 else "light breeze" if wavg < 12 else "breezy" if wavg < 18
                  else "windy" if wavg < 25 else "very windy")
        dew = vals(hours, "dew_point_2m")
        extra = []
        if w_word:
            extra.append(w_word)
        if dew and mean(dew) >= 65:
            extra.append("muggy")
        if pop >= 40:
            extra.append("showery")
        verdict = t_word + (" and " + " and ".join(extra) if extra else "")

        # Clothing: dress for the coldest hour, nudged by sun/cloud and wind
        cc = vals(hours, "cloud_cover")
        eff = fmin
        if cc and mean(cc) > 70 and fmin < 65:
            eff -= 2
        if cc and mean(cc) < 35 and fmin < 65:
            eff += 3
        if wavg >= 12:
            eff -= 2
        if eff >= 75:
            wear = "shorts + cap"
        elif eff >= 65:
            wear = "T-shirt, light layer for later"
        elif eff >= 57:
            wear = "hoodie or light jacket"
        elif eff >= 50:
            wear = "medium jacket"
        elif eff >= 44:
            wear = "medium jacket + hat"
        elif eff >= 35:
            wear = "winter coat, hat, gloves"
        else:
            wear = "winter coat, hat, gloves, blanket, hand warmers"
        items = [wear]
        if 35 <= eff < 50:
            items.append("blanket for the bleachers")
        if pop >= r["rain_bands"][1]:
            items.append("umbrella or poncho")
        elif pop >= r["rain_bands"][0]:
            items.append("rain shell in the bag")
        uvs = vals(hours, "uv_index")
        if uvs and max(uvs) >= r["uv_sunscreen"]:
            items.append("sunscreen")
        if sky in ("Sunny", "Mostly sunny"):
            items.append("sunglasses")
        if favg >= 85:
            items.append("extra water")

        # Clothing already answers "how cold"; the note says what else matters.
        pen = {k: mean(f[k] for f in factors) for k in ("wind", "rain", "heat")}
        top = dominant(pen)
        if top == "wind":
            note = ("wind and rain both matter" if pen["rain"] >= 0.4
                    else "wind matters more than rain")
        elif top == "rain":
            note = "rain is the main concern" + ("; wind adds to it" if pen["wind"] >= 0.4 else "")
        elif top == "heat":
            note = "heat is the main concern — find shade"
        elif favg < 55:
            note = "calm and dry — just dress warm"
        else:
            note = "no weather worries"

        return {
            "verdict": verdict,
            "score_label": "Comfort",
            "lines": [
                rng(temps, unit="°F"),
                f"Feels like {rng(feels, unit='°F')}",
                sky,
                wl,
                rl,
            ],
            "advice": f"{', '.join(items)}; {note}.",
        }
