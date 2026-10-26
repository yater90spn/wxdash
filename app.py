#!/usr/bin/env python3
"""wxdash server.

  python3 app.py                 # live data, http://0.0.0.0:8080  (planner at /plan)
  python3 app.py --demo          # synthetic data, no network needed
  python3 app.py --print         # print the cards to the terminal and exit
"""
import argparse
import json
import logging
import os
import socket
import subprocess
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_from_directory

from wxdash.activities import REGISTRY
from wxdash.engine import Engine, load_config
from wxdash.store import Store, ValidationError

HERE = os.path.dirname(os.path.abspath(__file__))
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

# What the planner offers. Order = order in the dropdown.
ACTIVITIES = [
    {"kind": "spectator", "label": "Outdoor event / game", "hint": "Sitting or standing outside: games, practices, events"},
    {"kind": "surf", "label": "Surfing", "hint": "Needs a surf spot (a place with a beach direction)"},
    {"kind": "sailing", "label": "Sailing", "hint": "Wind in knots, gusts, waves"},
    {"kind": "running", "label": "Running", "hint": "Dress for +15°F; humidity matters"},
    {"kind": "yardwork", "label": "Yard work", "hint": "Pick a task: wet grass, wind and rain matter differently",
     "tasks": ["general", "mow", "leaves", "spray", "plant"]},
]


def code_version():
    """Git commit of the running code; the page reloads itself when this changes."""
    try:
        return subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or "dev"
    except Exception:
        return "dev"


VERSION = code_version()


def slim(card):
    return {k: card[k] for k in ("day", "date", "when", "score", "score_label", "verdict",
                                 "lines", "advice", "advice_label", "location", "confidence",
                                 "hourly", "start", "end") if k in card}


def create_app(config_path, demo=False, data_path=None):
    app = Flask(__name__, static_folder=None)
    store = Store(data_path or os.path.join(HERE, "data", "plans.json"))
    state = {"engine": Engine(load_config(config_path), demo=demo, store=store),
             "mtime": os.path.getmtime(config_path)}

    def engine():
        # Hot-reload config.yaml when it changes.
        m = os.path.getmtime(config_path)
        if m != state["mtime"]:
            state["engine"] = Engine(load_config(config_path), demo=demo, store=store)
            state["mtime"] = m
        return state["engine"]

    def err(msg, code=400):
        return jsonify({"error": msg}), code

    def body():
        return request.get_json(silent=True) or {}

    # ---------- pages ----------
    @app.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "static"), "index.html")

    @app.get("/plan")
    def planner_page():
        return send_from_directory(os.path.join(HERE, "static"), "plan.html")

    # ---------- dashboard ----------
    @app.get("/api/version")
    def version():
        return jsonify({"version": VERSION, "plans_rev": store.revision()})

    @app.get("/api/dashboard")
    def dashboard():
        try:
            port = request.host.rsplit(":", 1)[-1] if ":" in request.host else "80"
            planner_url = f"{socket.gethostname()}.local:{port}/plan"
            return jsonify({**engine().dashboard(), "version": VERSION, "planner_url": planner_url})
        except Exception as e:
            logging.exception("dashboard failed")
            return err(str(e), 503)

    # ---------- planner ----------
    def location_list(e, data):
        cfg_locs = e.cfg.get("locations", {})
        out = []
        for k, v in e.locations(data).items():
            out.append({"key": k, "name": v.get("name", k), "custom": k not in cfg_locs,
                        "surf_spot": "facing" in v, "lat": v.get("lat"), "lon": v.get("lon")})
        return out

    def upcoming(e, plan, now, limit=3):
        occ, notes = [], []
        for d in e._dates(plan, now):
            card, why = e.card_for(plan, d, now)
            if card:
                occ.append(slim(card))
            elif why and plan.get("date"):
                notes.append(why)
            if len(occ) >= limit:
                break
        return occ, notes

    @app.get("/api/planner")
    def planner():
        e = engine()
        e.errors = []
        data = store.load()
        now = datetime.now(e.tz)
        plans = []
        for p in data["plans"]:
            occ, notes = upcoming(e, p, now)
            plans.append({**p, "upcoming": occ, "notes": notes})
        try:
            planned = e.build_cards(now, data)
            _, status = e.watch_scan(now, data, planned)
        except Exception as ex:
            logging.exception("watch scan failed")
            status = {}
            e.errors.append(str(ex))
        return jsonify({
            "plans": plans,
            "watches": data["watches"],
            "watch_status": status,
            "activities": ACTIVITIES,
            "locations": location_list(e, data),
            "lookahead_days": e.cfg.get("lookahead_days", 7),
            "forecast_days": e.cfg.get("forecast_days", 7),
            "today": now.date().isoformat(),
            "demo": demo,
            "errors": e.errors,
        })

    def clean(p):
        e = engine()
        return Store.clean_plan(p, set(REGISTRY), e.locations())

    @app.post("/api/rate")
    def rate():
        """Rate a plan without saving it (live preview while filling in the form)."""
        try:
            plan = clean(body())
        except ValidationError as ex:
            return err(str(ex))
        e = engine()
        now = datetime.now(e.tz)
        occ, notes = upcoming(e, plan, now, limit=7)
        if not occ and not notes:
            notes = [f"No matching days in the next {e.cfg.get('lookahead_days', 7)} days"]
        return jsonify({"upcoming": occ, "notes": notes})

    @app.post("/api/plans")
    def add_plan():
        try:
            return jsonify(store.add_plan(clean(body())))
        except ValidationError as ex:
            return err(str(ex))

    @app.put("/api/plans/<pid>")
    def update_plan(pid):
        try:
            return jsonify(store.update_plan(pid, clean(body())))
        except ValidationError as ex:
            return err(str(ex))
        except KeyError:
            return err("Plan not found", 404)

    @app.delete("/api/plans/<pid>")
    def delete_plan(pid):
        try:
            store.delete_plan(pid)
            return jsonify({"ok": True})
        except KeyError:
            return err("Plan not found", 404)

    @app.put("/api/watches/<kind>")
    def update_watch(kind):
        try:
            return jsonify(store.update_watch(kind, body(), engine().locations()))
        except (ValidationError, ValueError) as ex:
            return err(str(ex))

    # ---------- places ----------
    @app.get("/api/geocode")
    def geocode():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"results": []})
        if demo:
            return jsonify({"results": [
                {"name": q.title(), "detail": "New Jersey, United States", "lat": 40.35, "lon": -74.07},
                {"name": q.title() + " Park", "detail": "New York, United States", "lat": 40.7, "lon": -73.9},
            ]})
        try:
            r = requests.get(GEOCODE_URL, params={"name": q, "count": 8, "language": "en",
                                                  "format": "json"}, timeout=10)
            r.raise_for_status()
            res = []
            for x in r.json().get("results", []) or []:
                detail = ", ".join(v for v in (x.get("admin1"), x.get("country")) if v)
                res.append({"name": x.get("name"), "detail": detail,
                            "lat": x.get("latitude"), "lon": x.get("longitude")})
            return jsonify({"results": res})
        except Exception as ex:
            return err(f"Place search failed: {ex}", 502)

    @app.post("/api/places")
    def add_place():
        try:
            key, rec = store.add_place(body(), engine().cfg.get("locations", {}))
            return jsonify({"key": key, **rec})
        except ValidationError as ex:
            return err(str(ex))

    @app.delete("/api/places/<key>")
    def delete_place(key):
        try:
            store.delete_place(key)
            return jsonify({"ok": True})
        except ValidationError as ex:
            return err(str(ex))
        except KeyError:
            return err("Only places added in the planner can be removed here", 404)

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--data", default=os.path.join(HERE, "data", "plans.json"))
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--print", action="store_true", dest="print_only")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.print_only:
        d = Engine(load_config(a.config), demo=a.demo, store=Store(a.data)).dashboard()
        for c in d["cards"]:
            tag = "  [suggested]" if c.get("suggested") else ""
            print(f"\n{c['title']} — {c['day']}, {c['when']}  [{c['location']}]{tag}")
            print(f"{c['score_label']}: {c['score']} / 10 — {c['verdict']}")
            for line in c["lines"]:
                print(line)
            print(f"{c['advice_label']}: {c['advice']}")
            print(f"({c['confidence']})")
        if d["errors"]:
            print("\nErrors:", json.dumps(d["errors"], indent=1))
        return

    create_app(a.config, a.demo, a.data).run(host=a.host, port=a.port, threaded=True)


if __name__ == "__main__":
    main()
