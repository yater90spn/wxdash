"""Glue: config → fetch → blend → schedule → score → dashboard JSON."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

import requests
import yaml

from . import blend
from .activities import REGISTRY
from .activities.base import compass, sky_text
from .sources import noaa, openmeteo

log = logging.getLogger("wxdash")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _hm(s):
    h, m = s.strip().split(":")
    return int(h), int(m)


def _span(s):
    a, b = s.split("-")
    return _hm(a), _hm(b)


def fmt_time(dt):
    return dt.strftime("%-I %p") if dt.minute == 0 else dt.strftime("%-I:%M %p")


def fmt_span(a, b):
    sa, sb = fmt_time(a), fmt_time(b)
    if sa[-2:] == sb[-2:]:
        sa = sa[:-3]
    return f"{sa}–{sb}"


class Engine:
    def __init__(self, cfg, demo=False, store=None):
        self.cfg = cfg
        self.store = store
        self.tz = ZoneInfo(cfg.get("timezone", "America/New_York"))
        self.demo = demo
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "wxdash/0.1 (home dashboard)"
        self._cache = {}  # location key -> (fetched_at, hours, sun, extras)
        self._lock = threading.Lock()
        self.errors = []
        self._fetched = {}

    # ---------- data ----------
    def locations(self, data=None):
        """config.yaml locations plus places added from the planner."""
        places = dict(self.cfg.get("locations", {}))
        if self.store:
            data = data or self.store.load()
            for k, v in data.get("places", {}).items():
                places.setdefault(k, v)
        return places

    def _place(self, key):
        places = self.locations()
        if key not in places:
            raise KeyError(f"Unknown location '{key}'")
        return places[key]

    def _fetch(self, key, need_marine):
        p = self._place(key)
        models = self.cfg.get("models") or openmeteo.DEFAULT_MODELS
        days = self.cfg.get("forecast_days", 7)
        if self.demo:
            from .demo import fake_forecast, fake_marine, fake_tides
            raw = fake_forecast(p["lat"], p["lon"], models, self.tz, days)
            marine = fake_marine(self.tz, days, p.get("facing", 100)) if need_marine else None
            tides = fake_tides(self.tz, days) if need_marine and p.get("noaa_station") else None
            water_obs = None
        else:
            raw = openmeteo.fetch_forecast(p["lat"], p["lon"], models, days, self.session)
            marine = tides = water_obs = None
            if need_marine:
                mlat, mlon = p.get("marine_lat", p["lat"]), p.get("marine_lon", p["lon"])
                try:
                    marine = openmeteo.fetch_marine(mlat, mlon, days, self.session)
                except Exception as e:
                    self.errors.append(f"marine {key}: {e}")
                st = p.get("noaa_station")
                if st:
                    try:
                        tides = noaa.fetch_tides(st, self.tz, days, self.session)
                    except Exception as e:
                        self.errors.append(f"tides {key}: {e}")
                    water_obs = noaa.fetch_water_temp(st, self.session)
        hours, sun = blend.blend_forecast(raw, self.tz, var_priority=self.cfg.get("var_priority"))
        blend.attach_marine(hours, marine, self.tz)
        blend.attach_tides(hours, tides)
        return hours, sun, {"water_obs_f": water_obs}

    def data_for(self, key, need_marine=False):
        ttl = 60 * self.cfg.get("refresh_minutes", 30)
        ck = (key, need_marine)
        with self._lock:
            hit = self._cache.get(ck)
            if hit and time.time() - hit[0] < ttl:
                self._fetched[key] = min(self._fetched.get(key, hit[0]), hit[0])
                return hit[1:]
            try:
                hours, sun, extras = self._fetch(key, need_marine)
                self._cache[ck] = (time.time(), hours, sun, extras)
                self._fetched[key] = time.time()
                return hours, sun, extras
            except Exception as e:
                log.exception("fetch failed for %s", key)
                self.errors.append(f"forecast {key}: {e}")
                if hit:  # serve stale rather than blank the screen
                    self._fetched[key] = hit[0]
                    return hit[1:]
                raise

    # ---------- schedule ----------
    def _dates(self, entry, now, look=None):
        look = look or self.cfg.get("lookahead_days", 7)
        if entry.get("enabled") is False:
            return []
        if entry.get("date"):
            d = entry["date"]
            d = d if not isinstance(d, str) else datetime.strptime(d, "%Y-%m-%d").date()
            return [d]
        days = [x.lower()[:3] for x in entry.get("days", DAYS)]
        out = []
        for i in range(look):
            d = (now + timedelta(days=i)).date()
            if DAYS[d.weekday()] in days:
                out.append(d)
        return out

    def _ctx(self, hours, now, extras):
        index_of = {h["time"]: i for i, h in enumerate(hours)}

        def rain_before(t, n):
            i = index_of.get(t, 0)
            return sum(h.get("precipitation") or 0 for h in hours[max(0, i - n):i])

        def rain_after(t, n):
            i = index_of.get(t, 0)
            return sum(h.get("precipitation") or 0 for h in hours[i:i + n])

        return {"now": now, "all_hours": hours, "index_of": index_of,
                "rain_before": rain_before, "rain_after": rain_after, **extras}

    def card_for(self, entry, d, now):
        """Score one occurrence of an entry. Returns (card, None) or (None, reason)."""
        kind = entry["activity"]
        cls = REGISTRY.get(kind)
        if not cls:
            return None, f"unknown activity '{kind}'"
        loc = entry.get("location", "home")
        try:
            place = {**self._place(loc), **entry.get("spot", {})}
        except KeyError as e:
            return None, str(e)
        rules = {**self.cfg.get("rules", {}).get(kind, {}), **entry.get("rules", {})}
        act = cls(rules=rules, place=place)
        try:
            hours, sun, extras = self.data_for(loc, act.needs_marine)
        except Exception as e:
            return None, f"forecast unavailable ({e})"
        ctx = self._ctx(hours, now, extras)
        cur_hour = now.replace(minute=0, second=0, microsecond=0)

        flex = entry.get("flex")
        span = entry.get("time") if not flex else flex["between"]
        (h1, m1), (h2, m2) = _span(span)
        w_start = datetime(d.year, d.month, d.day, h1, m1, tzinfo=self.tz)
        if (h2, m2) == (24, 0):
            w_end = datetime(d.year, d.month, d.day, tzinfo=self.tz) + timedelta(days=1)
        else:
            w_end = datetime(d.year, d.month, d.day, h2, m2, tzinfo=self.tz)
        if w_end <= now:
            return None, "that time has already passed"
        sl = [h for h in hours if w_start <= h["time"] < w_end and h["time"] >= cur_hour]
        if entry.get("daylight"):
            # first light (~30 min before sunrise) to sunset
            sun_d = next(((a, b) for a, b in sun if a.date() == d), None)
            if sun_d:
                dawn, dusk = sun_d[0] - timedelta(minutes=30), sun_d[1]
                sl = [h for h in sl if h["time"] + timedelta(minutes=30) >= dawn
                      and h["time"] + timedelta(minutes=30) <= dusk]
            if not sl:
                return None, "no daylight hours in that window"
        if not sl:
            last = hours[-1]["time"] if hours else now
            if w_start > last:
                return None, f"beyond the forecast (goes to {last.strftime('%a %b %-d')})"
            return None, "no forecast hours in that window"
        if flex:
            n = max(1, int(flex.get("duration", 1)))
            per = [act.score_hour(h, ctx)[0] for h in sl]
            best, best_i = -99, 0
            for i in range(0, max(1, len(sl) - n + 1)):
                seg = per[i:i + n]
                val = 0.7 * mean(seg) + 0.3 * min(seg)
                if val > best:
                    best, best_i = val, i
            sl = sl[best_i:best_i + n]
        card = act.evaluate(sl, ctx)
        start, end = sl[0]["time"], sl[-1]["time"] + timedelta(hours=1)
        day = "Today" if d == now.date() else ("Tomorrow" if d == (now + timedelta(days=1)).date()
                                               else d.strftime("%A"))
        card.update({
            "id": f"{entry.get('id', kind)}-{d.isoformat()}",
            "plan_id": entry.get("id"),
            "title": entry.get("label") or act.label,
            "day": day,
            "date": d.isoformat(),
            "when": fmt_span(start, end) + (" · best window" if flex else ""),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "location": place.get("name", loc),
            "live": start <= now < end,
            "flex": bool(flex),
            "suggested": False,
        })
        return card, None

    def _entries(self, data):
        entries = [dict(e, source="config") for e in self.cfg.get("schedule") or []]
        if data:
            entries += [dict(p, source="plan") for p in data.get("plans", [])]
        return entries

    def build_cards(self, now, data=None):
        cards = []
        for entry in self._entries(data):
            for d in self._dates(entry, now):
                card, why = self.card_for(entry, d, now)
                if card:
                    cards.append(card)
                elif why and why.startswith("unknown"):
                    self.errors.append(why)
        cards.sort(key=lambda c: c["start"])
        return cards

    def watch_scan(self, now, data, planned):
        """Best window per day for each enabled watch.

        Returns (suggestion cards, status per watch). A day becomes a suggestion
        when its best window scores at least min_score and you don't already
        have that activity planned that day.
        """
        from .activities import REGISTRY as R
        sugg, status = [], {}
        taken = {(c["kind"], c["date"]) for c in planned}
        for kind, w in (data or {}).get("watches", {}).items():
            if not w.get("enabled") or kind not in R:
                continue
            entry = {"id": f"watch-{kind}", "activity": kind, "location": w["location"],
                     "flex": {"between": w["between"], "duration": w["duration"]},
                     "days": w.get("days", DAYS),
                     "daylight": kind in ("surf", "sailing", "yardwork")}
            days = []
            for d in self._dates(entry, now):
                card, _ = self.card_for(entry, d, now)
                if card:
                    days.append(card)
            good = [c for c in days if c["score"] >= w["min_score"] and (kind, c["date"]) not in taken]
            good = sorted(good, key=lambda c: -c["score"])[: int(self.cfg.get("max_suggestions", 3))]
            for c in good:
                c["suggested"] = True
                c["title"] = R[kind].label
                c["when"] = c["when"].replace(" · best window", "")
            sugg += good
            best = max(days, key=lambda c: c["score"], default=None)
            status[kind] = {
                "suggested": len(good),
                "best": None if not best else {
                    "day": best["day"], "when": best["when"].replace(" · best window", ""),
                    "score": best["score"], "verdict": best["verdict"],
                    "detail": " · ".join(best["lines"][:3]), "advice": best["advice"],
                    "advice_label": best["advice_label"],
                },
                "days_checked": len(days),
            }
        return sugg, status

    # ---------- dashboard ----------
    def dashboard(self, now=None):
        self.errors = []
        self._fetched = {}
        now = now or datetime.now(self.tz)
        home_key = self.cfg.get("home", "home")
        hours, sun, _ = self.data_for(home_key)
        cur = now.replace(minute=0, second=0, microsecond=0)
        idx = next((i for i, h in enumerate(hours) if h["time"] >= cur), 0)
        n = self.cfg.get("timeline_hours", 36)
        tl = []
        for h in hours[idx: idx + n]:
            tl.append({
                "t": h["time"].isoformat(),
                "temp": h.get("temperature_2m"),
                "feels": h.get("apparent_temperature"),
                "dew": h.get("dew_point_2m"),
                "pop": h.get("precipitation_probability"),
                "precip": h.get("precipitation"),
                "wind": h.get("wind_speed_10m"),
                "gust": h.get("wind_gusts_10m"),
                "dir": h.get("wind_direction_10m"),
                "cloud": h.get("cloud_cover"),
                "code": h.get("weather_code"),
                "day": h.get("is_day"),
                "uv": h.get("uv_index"),
                "src": (h.get("source") or "").replace("ncep_", "").split("_")[0].upper(),
                "spread": round(h["spread"].get("temperature_2m", 0), 1),
            })
        h0 = hours[idx]
        today_sun = next(((a, b) for a, b in sun if a.date() == now.date()), None)
        now_block = {
            "temp": h0.get("temperature_2m"),
            "feels": h0.get("apparent_temperature"),
            "dew": h0.get("dew_point_2m"),
            "sky": sky_text([h0]),
            "code": h0.get("weather_code"),
            "is_day": h0.get("is_day"),
            "wind": f"{compass(h0.get('wind_direction_10m'))} {h0.get('wind_speed_10m') or 0:.0f} mph",
            "gust": h0.get("wind_gusts_10m"),
            "pop": h0.get("precipitation_probability"),
            "uv": h0.get("uv_index"),
            "vis_mi": h0.get("visibility_mi"),
            "sunrise": today_sun[0].strftime("%-I:%M") if today_sun else None,
            "sunset": today_sun[1].strftime("%-I:%M") if today_sun else None,
            "hi": max((h["temperature_2m"] for h in hours if h["time"].date() == now.date()
                       and h.get("temperature_2m") is not None), default=None),
            "lo": min((h["temperature_2m"] for h in hours if h["time"].date() == now.date()
                       and h.get("temperature_2m") is not None), default=None),
        }
        data = self.store.load() if self.store else None
        cards = self.build_cards(now, data)
        sugg, _ = self.watch_scan(now, data, cards)
        cards = sorted(cards + sugg, key=lambda c: c["start"])
        oldest = min(self._fetched.values()) if self._fetched else time.time()
        return {
            "data_age_min": round((time.time() - oldest) / 60),
            "refresh_minutes": self.cfg.get("refresh_minutes", 30),
            "generated": now.isoformat(),
            "place": self._place(home_key).get("name", home_key),
            "demo": self.demo,
            "now": now_block,
            "timeline": tl,
            "cards": cards,
            "errors": self.errors,
        }
