"""Plans, watches and user-added places, edited from the /plan page.

Stored as JSON in data/plans.json. That file is untracked (gitignored), so the
Pi's auto-update (git reset --hard) never touches it.

  plans:   things you intend to do — one-off (date) or repeating (days),
           at a fixed time or "best window between" (flex).
  watches: activities the dashboard should look for on its own and suggest
           when conditions are good (e.g. surf, sailing).
  places:  locations added from the planner by name search; they extend
           the locations in config.yaml.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid

DEFAULT_WATCHES = {
    "surf": {"enabled": True, "location": "sandy_hook_lot_b", "between": "06:00-18:00",
             "duration": 2, "min_score": 6.5, "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
    "sailing": {"enabled": True, "location": "sandy_hook_bay", "between": "10:00-18:00",
                "duration": 3, "min_score": 7.0, "days": ["sat", "sun"]},
    "running": {"enabled": False, "location": "home", "between": "06:00-19:00",
                "duration": 1, "min_score": 8.0, "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
    "yardwork": {"enabled": False, "location": "home", "between": "09:00-17:00",
                 "duration": 3, "min_score": 7.5, "days": ["sat", "sun"]},
}

# Screen power: turn the display off after idle_minutes without a touch (0 = never),
# except during keep_on hours (e.g. "06:30-08:30"), when it stays on.
DEFAULT_DISPLAY = {"idle_minutes": 10, "keep_on": None}

TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d-([01]?\d|2[0-4]):[0-5]\d$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class ValidationError(ValueError):
    pass


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s[:40] or "place"


class Store:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if not os.path.exists(path):
            self._write({"plans": [], "watches": DEFAULT_WATCHES, "places": {}})

    # ---------- io ----------
    def _read(self):
        try:
            with open(self.path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.setdefault("plans", [])
        data.setdefault("places", {})
        w = data.setdefault("watches", {})
        for k, v in DEFAULT_WATCHES.items():
            w.setdefault(k, dict(v))
        disp = data.setdefault("display", {})
        for k, v in DEFAULT_DISPLAY.items():
            disp.setdefault(k, v)
        return data

    def _write(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    def load(self):
        with self._lock:
            return self._read()

    def revision(self):
        try:
            return str(os.path.getmtime(self.path))
        except OSError:
            return "0"

    # ---------- validation ----------
    @staticmethod
    def clean_plan(p, kinds, locations):
        out = {}
        kind = p.get("activity")
        if kind not in kinds:
            raise ValidationError("Pick an activity")
        out["activity"] = kind
        loc = p.get("location") or "home"
        if loc not in locations:
            raise ValidationError(f"Unknown place '{loc}'")
        out["location"] = loc
        label = (p.get("label") or "").strip()
        if label:
            out["label"] = label[:60]
        if p.get("date"):
            if not DATE_RE.match(p["date"]):
                raise ValidationError("Date must be YYYY-MM-DD")
            out["date"] = p["date"]
        else:
            days = [d for d in (p.get("days") or []) if d in DAYS]
            if not days:
                raise ValidationError("Pick a date or at least one weekday")
            out["days"] = days
        span = (p.get("time") or "").replace(" ", "")
        if not TIME_RE.match(span):
            raise ValidationError("Times must look like 10:00-13:00")
        a, b = span.split("-")
        if b <= a:
            raise ValidationError("End time must be after start time")
        if p.get("flex"):
            dur = int(p.get("duration") or 1)
            out["flex"] = {"between": span, "duration": max(1, min(dur, 12))}
        else:
            out["time"] = span
        if isinstance(p.get("rules"), dict) and p["rules"]:
            out["rules"] = {k: v for k, v in p["rules"].items() if k in ("task",)}
        if p.get("enabled") is False:
            out["enabled"] = False
        return out

    # ---------- plans ----------
    def add_plan(self, plan):
        with self._lock:
            d = self._read()
            plan = {**plan, "id": uuid.uuid4().hex[:8], "created": int(time.time())}
            d["plans"].append(plan)
            self._write(d)
            return plan

    def update_plan(self, pid, plan):
        with self._lock:
            d = self._read()
            for i, p in enumerate(d["plans"]):
                if p["id"] == pid:
                    d["plans"][i] = {**plan, "id": pid, "created": p.get("created")}
                    self._write(d)
                    return d["plans"][i]
            raise KeyError(pid)

    def delete_plan(self, pid):
        with self._lock:
            d = self._read()
            n = len(d["plans"])
            d["plans"] = [p for p in d["plans"] if p["id"] != pid]
            if len(d["plans"]) == n:
                raise KeyError(pid)
            self._write(d)

    # ---------- watches ----------
    def update_watch(self, kind, w, locations):
        with self._lock:
            d = self._read()
            if kind not in d["watches"]:
                raise ValidationError("Not a watchable activity")
            cur = d["watches"][kind]
            if "enabled" in w:
                cur["enabled"] = bool(w["enabled"])
            if "location" in w:
                if w["location"] not in locations:
                    raise ValidationError("Unknown place")
                cur["location"] = w["location"]
            if "between" in w:
                span = w["between"].replace(" ", "")
                if not TIME_RE.match(span):
                    raise ValidationError("Hours must look like 06:00-18:00")
                cur["between"] = span
            if "duration" in w:
                cur["duration"] = max(1, min(int(w["duration"]), 12))
            if "min_score" in w:
                cur["min_score"] = max(0.0, min(float(w["min_score"]), 10.0))
            if "days" in w:
                days = [x for x in w["days"] if x in DAYS]
                if not days:
                    raise ValidationError("Pick at least one day")
                cur["days"] = days
            self._write(d)
            return cur

    # ---------- display ----------
    def update_display(self, upd):
        with self._lock:
            d = self._read()
            cur = d["display"]
            if "idle_minutes" in upd:
                m = int(upd["idle_minutes"])
                if not 0 <= m <= 240:
                    raise ValidationError("Idle time must be 0–240 minutes")
                cur["idle_minutes"] = m
            if "keep_on" in upd:
                k = (upd["keep_on"] or "").replace(" ", "")
                if k and not TIME_RE.match(k):
                    raise ValidationError("Keep-on hours must look like 06:30-08:30")
                cur["keep_on"] = k or None
            self._write(d)
            return cur

    # ---------- places ----------
    def add_place(self, place, existing):
        name = (place.get("name") or "").strip()
        try:
            lat, lon = float(place["lat"]), float(place["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Place needs a name and coordinates")
        if not name or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValidationError("Place needs a name and valid coordinates")
        rec = {"name": name[:60], "lat": round(lat, 4), "lon": round(lon, 4)}
        if place.get("facing") not in (None, ""):
            rec["facing"] = float(place["facing"]) % 360
        if place.get("noaa_station"):
            rec["noaa_station"] = re.sub(r"\D", "", str(place["noaa_station"]))[:8]
        with self._lock:
            d = self._read()
            key, n = _slug(name), 2
            base = key
            while key in existing or key in d["places"]:
                key, n = f"{base}_{n}", n + 1
            d["places"][key] = rec
            self._write(d)
            return key, rec

    def delete_place(self, key):
        with self._lock:
            d = self._read()
            if key not in d["places"]:
                raise KeyError(key)
            used = [p for p in d["plans"] if p.get("location") == key]
            used += [k for k, w in d["watches"].items() if w.get("location") == key]
            if used:
                raise ValidationError("That place is used by a plan or watch")
            del d["places"][key]
            self._write(d)
