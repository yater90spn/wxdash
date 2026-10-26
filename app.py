#!/usr/bin/env python3
"""wxdash server.

  python3 app.py                 # live data, http://0.0.0.0:8080
  python3 app.py --demo          # synthetic data, no network needed
  python3 app.py --print         # print the cards to the terminal and exit
"""
import argparse
import json
import logging
import os
import subprocess

from flask import Flask, jsonify, send_from_directory

from wxdash.engine import Engine, load_config

HERE = os.path.dirname(os.path.abspath(__file__))


def code_version():
    """Git commit of the running code; the page reloads itself when this changes."""
    try:
        return subprocess.run(["git", "-C", HERE, "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or "dev"
    except Exception:
        return "dev"


VERSION = code_version()


def create_app(config_path, demo=False):
    app = Flask(__name__, static_folder=None)
    state = {"engine": Engine(load_config(config_path), demo=demo),
             "mtime": os.path.getmtime(config_path)}

    def engine():
        # Hot-reload config.yaml when it changes — edit and the screen updates next refresh.
        m = os.path.getmtime(config_path)
        if m != state["mtime"]:
            state["engine"] = Engine(load_config(config_path), demo=demo)
            state["mtime"] = m
        return state["engine"]

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(HERE, "static"), "index.html")

    @app.get("/api/version")
    def version():
        return jsonify({"version": VERSION})

    @app.get("/api/dashboard")
    def dashboard():
        try:
            return jsonify({**engine().dashboard(), "version": VERSION})
        except Exception as e:
            logging.exception("dashboard failed")
            return jsonify({"error": str(e)}), 503

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--print", action="store_true", dest="print_only")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.print_only:
        d = Engine(load_config(a.config), demo=a.demo).dashboard()
        for c in d["cards"]:
            print(f"\n{c['title']} — {c['day']}, {c['when']}  [{c['location']}]")
            print(f"{c['score_label']}: {c['score']} / 10 — {c['verdict']}")
            for line in c["lines"]:
                print(line)
            print(f"{c['advice_label']}: {c['advice']}")
            print(f"({c['confidence']})")
        if d["errors"]:
            print("\nErrors:", json.dumps(d["errors"], indent=1))
        return

    create_app(a.config, a.demo).run(host=a.host, port=a.port, threaded=True)


if __name__ == "__main__":
    main()
