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

_state = {"on": True, "error": None, "dimmed": False}
_ddc = {"bus": None, "checked_at": 0.0}
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


def run_schedule(get_hours, get_tz, demo=False, interval=30, get_bright=None):
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
                if want and get_bright:
                    try:
                        set_brightness(get_bright(), dimmed=False, demo=demo)
                    except Exception:
                        pass
                log.info("schedule: screen %s", "on" if want else "off")
                prev = want
        except Exception as ex:
            log.warning("schedule: %s", ex)   # e.g. desktop not up yet at boot; retried next tick
        time.sleep(interval)


# ---------- brightness over DDC/CI (monitor stays awake, so touch keeps working) ----------
def _ddc_bus():
    """I2C bus number of the monitor, found once with `ddcutil detect` (re-tried every 2 min)."""
    import re
    import time
    if _ddc["bus"] is not None or time.time() - _ddc["checked_at"] < 120:
        return _ddc["bus"]
    _ddc["checked_at"] = time.time()
    exe = shutil.which("ddcutil")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "detect", "--terse"], capture_output=True, text=True, timeout=30)
        m = re.search(r"/dev/i2c-(\d+)", r.stdout)
        _ddc["bus"] = m.group(1) if m else None
    except Exception:
        _ddc["bus"] = None
    return _ddc["bus"]


def ddc_available():
    return shutil.which("ddcutil") is not None and _ddc_bus() is not None


def set_brightness(value, dimmed, demo=False):
    """Set monitor brightness 0-100 via DDC/CI. dimmed records which mode we're in."""
    value = max(0, min(100, int(value)))
    with _lock:
        if not demo:
            bus = _ddc_bus()
            if bus is None:
                _state["error"] = "monitor brightness control not available (ddcutil / i2c access)"
                raise RuntimeError(_state["error"])
            r = subprocess.run([shutil.which("ddcutil"), "--bus", bus, "--noverify", "setvcp", "10", str(value)],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                _state["error"] = (r.stderr or r.stdout or "ddcutil failed").strip()[:200]
                raise RuntimeError(_state["error"])
        _state.update(dimmed=bool(dimmed), error=None, brightness=value)
        return dict(_state)


def quick():
    """Cheap state for frequent polling (no hardware probing)."""
    with _lock:
        return {"on": _state["on"], "dimmed": _state["dimmed"]}


def state():
    with _lock:
        s = dict(_state, available=available())
    s["dim_available"] = ddc_available()
    return s
