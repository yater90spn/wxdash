"""Turn the kiosk display on/off (DPMS) on the Pi's Wayland desktop.

Uses `wlopm` (wlroots output power manager), which works with labwc, the
Raspberry Pi OS desktop. DPMS puts the panel in standby (backlight off) but
keeps the output configured, so touch input still reaches the browser and a
tap can wake it.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import threading

_state = {"on": True, "error": None}
_lock = threading.Lock()


def _wayland_env():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env = dict(os.environ, XDG_RUNTIME_DIR=runtime)
    if not env.get("WAYLAND_DISPLAY"):
        socks = sorted(p for p in glob.glob(os.path.join(runtime, "wayland-*")) if not p.endswith(".lock"))
        if socks:
            env["WAYLAND_DISPLAY"] = os.path.basename(socks[0])
    return env


def available():
    return shutil.which("wlopm") is not None


def set_power(on, demo=False):
    """Returns the new state dict. Raises RuntimeError with a readable reason."""
    with _lock:
        if not demo:
            exe = shutil.which("wlopm")
            if not exe:
                _state["error"] = "wlopm is not installed (sudo apt install wlopm)"
                raise RuntimeError(_state["error"])
            env = _wayland_env()
            if not env.get("WAYLAND_DISPLAY"):
                _state["error"] = "no desktop session found (is anyone logged in on the Pi?)"
                raise RuntimeError(_state["error"])
            r = subprocess.run([exe, "--on" if on else "--off", "*"], env=env,
                               capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                _state["error"] = (r.stderr or r.stdout or "wlopm failed").strip()[:200]
                raise RuntimeError(_state["error"])
        _state.update(on=bool(on), error=None)
        return dict(_state)


def in_hours(span, now):
    """True if now (a datetime) falls inside "HH:MM-HH:MM"; spans may cross midnight."""
    if not span:
        return True
    a, b = span.split("-")
    m = now.hour * 60 + now.minute
    s = int(a.split(":")[0]) * 60 + int(a.split(":")[1])
    e = int(b.split(":")[0]) * 60 + int(b.split(":")[1])
    return s <= m < e if s < e else (m >= s or m < e)


def run_schedule(get_hours, get_tz, demo=False, interval=30):
    """Background loop: switch the screen at the on/off boundaries only, so a
    manual Turn on/off from the planner holds until the next boundary."""
    import logging
    import time
    from datetime import datetime
    log = logging.getLogger("wxdash.display")
    prev = None
    while True:
        try:
            want = in_hours(get_hours(), datetime.now(get_tz()))
            if want != prev:
                set_power(want, demo=demo)
                log.info("schedule: screen %s", "on" if want else "off")
                prev = want
        except Exception as ex:
            log.warning("schedule: %s", ex)   # e.g. desktop not up yet at boot; retried next tick
        time.sleep(interval)


def state():
    with _lock:
        return dict(_state, available=available())
