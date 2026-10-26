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


def state():
    with _lock:
        return dict(_state, available=available())
