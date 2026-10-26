# wxdash — project context

Activity-aware hourly weather dashboard. Owner: Doug. Built in a claude.ai session
(Oct 2026); this file carries that context into Claude Code sessions on the Pi.

## What it does
- Pulls hourly forecasts from Open-Meteo, blending models in priority order
  HRRR → NBM → GFS (first non-null per hour; precip probability from NBM/GFS,
  UV from GFS only). Marine API for waves/swell/water temp. NOAA CO-OPS station
  8531680 (Sandy Hook) for tides + observed water temp.
- Scores scheduled activities 0–10 per hour and per window, and writes a verdict,
  metric lines and one advice line ("Bring:", "Comfort:", "Plan:", "Wear:").
- Activities: spectator (alias baseball), surf, sailing, running, yardwork
  (task: general/mow/leaves/spray/plant). Thresholds are piecewise-linear curves,
  overridable in config.yaml under `rules:` or per schedule entry.
- Schedule entries are fixed (`time: "10:00-13:00"`), flexible
  (`flex: {between: "06:00-19:00", duration: 1}` picks the best window) or
  one-off (`date:`). `lookahead_days` controls how far ahead cards show.

## Layout
- `app.py` — Flask server. `--demo` (synthetic data), `--print` (cards to terminal).
  Serves `static/index.html` and `/api/dashboard`. config.yaml hot-reloads.
- `wxdash/sources/openmeteo.py`, `noaa.py` — fetchers (unixtime + zoneinfo so DST is correct).
- `wxdash/blend.py` — model blending, marine/tide attachment, tide state.
- `wxdash/activities/` — one scorer per activity; `base.py` has shared helpers.
- `wxdash/engine.py` — config → fetch (30-min cache, serves stale on failure) → cards.
- `wxdash/demo.py` — fake payloads shaped like the real APIs.
- `static/index.html` — fixed 2560×720 layout: "now" panel left, swipeable
  activity cards, 36-hour strip (temp, feels-like, rain %, wind). Tap a card to
  highlight its window. Dims at night unless URL has `?nodim`.

## Hardware / OS
- Raspberry Pi 4B, Raspberry Pi OS **Trixie** (Wayland, **labwc**).
- Hostname `weatherdash`, user **`weatherpi`** (not `pi`), project at `/home/weatherpi/wxdash`.
- Browser binary is **`chromium`** (not `chromium-browser`).
- Display: Corsair Xeneon Edge 14.5" 2560×720 touchscreen. Video over micro-HDMI→HDMI.
  Touch only works over the screen's USB-C data link (HDMI is video only). The screen
  needs 5V/2A, more than the Pi's USB ports reliably supply, so it should be powered
  through a powered USB hub or USB-C power+data splitter. Touch under Linux not yet
  confirmed: check `sudo libinput list-devices`.

## Deployment
- Code lives at github.com/yater90spn/wxdash (private). Changes are pushed there;
  the Pi updates itself (`deploy/update.sh` via `wxdash-update.timer`, every 5 min:
  fetch → reset --hard origin/main → re-run install.sh → restart wxdash). The page polls
  `/api/version` (git short hash) and reloads when it changes. Don't edit tracked files on
  the Pi; they get overwritten.
- `deploy/install.sh` (run with sudo, re-runnable) writes the systemd units with the
  repo owner's username/paths, server on 0.0.0.0:8080, and adds `deploy/kiosk.sh` to
  `~/.config/labwc/autostart`, merged with `/etc/xdg/labwc/autostart` so the taskbar survives.
- `deploy/kiosk.sh` finds `chromium` or `chromium-browser` and logs to `~/.cache/wxdash-kiosk.log`.
- Live view from the LAN: http://weatherdash.local:8080

## History
- 2026-10-25: lookahead_days 3 → 7 (3 hid weekend cards Sun–Wed). Stale-data indicator.
  Kiosk at login was failing on the original manual install (autostart line probably
  still pointed at /home/pi); replaced by install.sh. Live Open-Meteo/NOAA calls were
  never tested from the dev sandbox; verify with `.venv/bin/python app.py --print`.

## Places in config
home = Atlantic Highlands; long_branch = surf spot (beach faces 100° ESE, so offshore wind
is from the WNW); sandy_hook_bay = sailing. Coordinates and beach orientation are starting
guesses for Doug to adjust.
