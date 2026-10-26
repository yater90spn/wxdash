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
- **Planner page `/plan`** is how Doug manages activities (he doesn't edit YAML).
  Data lives in `data/plans.json` (gitignored, so auto-update never touches it) via
  `wxdash/store.py`:
  - plans: one-off (`date`) or weekly (`days`), fixed `time` or `flex`
    {between, duration} = "best N hours in this range". Live rating preview via `POST /api/rate`.
  - watches: per-activity "suggest when score ≥ min_score" (surf, sailing, running,
    yardwork). Engine `watch_scan` adds `suggested: true` cards (max `max_suggestions`
    per activity, skips days where that activity is already planned; surf/sailing/yard
    limited to daylight). Planner shows the best window even when nothing qualifies.
  - places: added by name via Open-Meteo geocoding (`/api/geocode`); surf spots need
    `facing` (beach direction). They extend `locations:` in config.yaml.
- config.yaml `schedule:` still works but is empty; `lookahead_days` (7) sets how far
  ahead weekly plans and watches look.

## Layout
- `app.py` — Flask server. `--demo` (synthetic data), `--print` (cards to terminal).
  Serves `static/index.html` and `/api/dashboard`. config.yaml hot-reloads.
- `wxdash/sources/openmeteo.py`, `noaa.py` — fetchers (unixtime + zoneinfo so DST is correct).
- `wxdash/blend.py` — model blending, marine/tide attachment, tide state.
- `wxdash/activities/` — one scorer per activity; `base.py` has shared helpers.
- `wxdash/engine.py` — config → fetch (30-min cache, serves stale on failure) → cards.
- `wxdash/demo.py` — fake payloads shaped like the real APIs.
- `static/plan.html` — planner (desktop + phone). `app.py` has the JSON API.
- `static/index.html` — fixed 2560×720 layout: "now" panel left, swipeable
  activity cards, 36-hour strip (temp, feels-like, rain %, wind). Tap a card to
  highlight its window. Dims at night unless URL has `?nodim`. Bottom strip covers the
  whole forecast (`timeline_hours` = hours visible at once), drag/swipe to scroll; selecting
  a card scrolls to it and shows that card's place (`timelines[loc_key]`); "← Now" button
  and a 3-minute idle reset return it to now/home. Mouse-drag scrolling exists because the
  Pi's Chromium may deliver panel touches as mouse events. Polls `/api/version`
  every 20 s: reloads on new code, refreshes data when `plans_rev` changes.

## Past 24 h on the strip (actual vs forecast)
- Home timeline = `history_hours` (24) past hours + forecast; strip opens scrolled to "now"
  (`timeline_now_index`); "← Now"/"Now →" button returns. Other places' timelines have no past.
- `wxdash/sources/history.py`: actual = NWS observations (api.weather.gov, nearest reporting
  station via /points/…/stations, override with `obs_station:` in config), one obs per hour
  (closest to the top of the hour); feels-like computed with the BoM apparent-temp formula.
  Forecast = Open-Meteo Previous Runs API `*_previous_day1` (predicted 24 h before).
  No precip probability in previous runs, so past rain compares amounts (in).
  Nothing stored locally; cached like the forecast. Errors show in the left panel meta line.
- Drawn: actual temp white solid, actual feels white dashed; day-ahead forecast temp
  orange dashed, feels gray dotted; rain measured = filled bar, forecast = outline.
- Not yet verified against the live services from the Pi (sandbox can't reach them).

## Tide curve on the strip
- Forecast side only (not in the past section, by request — it's already busy). Soft teal
  area + line in the rain band, behind the rain bars, labeled at highs/lows ("H 7:21p").
- Home uses `tide_station` (config, Sandy Hook 8531680); a selected card's place uses its
  `noaa_station`. `Engine.tides_for` caches NOAA predictions 6 h; payload `tides[loc_key]`.

## Quick check (left panel buttons)
- One button per *enabled* watch (Surf / Sail / Run / Yard) above "⏻ Screen off" in the
  bottom-left. Tap → pop-up with a card rated for now → +2 h at the watch's place
  (`GET /api/check/<kind>?start=ISO&hours=N`, `Engine.quick_check`, no minimum score).
  Pop-up controls: day chips (Today…+6), start hour stepper (Today defaults to "Now";
  other days default to 7 AM), length 1–4 h. Card shows an after-dark warning
  (`card.warning`) but never swaps to a daylight window. Closes on outside tap, Close,
  or 60 s idle; the screen doesn't dim while it's open.
- Note: Open-Meteo suffixes daily keys per model (sunrise_ncep_…) when several models
  are requested; blend.py handles that (sunrise/sunset were blank before 2026-10-26).

## Screen power
- `wxdash/display.py` runs `wlopm --on/--off '*'` (DPMS on labwc; install.sh apt-installs wlopm).
- **Tap-to-wake does NOT work on this panel** (tested 2026-10-25 with deploy/screen-test.sh):
  in DPMS standby the Corsair re-enumerates its USB touch controller ("wch.cn TouchScreen",
  27c0:0859) and sends no touch events until the screen is on again. So no idle-off.
- Instead a server thread (`display.run_schedule`) applies `display.on_hours` (default
  06:00-23:00, None = always on) at the boundaries only, so manual Turn on/off from the
  planner holds until the next boundary. Dashboard has a "⏻ Screen off" button.
- **Daytime idle-dim via DDC/CI works** (dim-test.sh 2026-10-25: Xeneon Edge on /dev/i2c-20,
  VCP 0x10 brightness 0–100, was 95). `display.set_brightness` runs
  `ddcutil --bus N --noverify setvcp 10 V` (bus auto-detected). install.sh installs ddcutil,
  loads i2c-dev, adds the service user to `i2c` + a udev rule so it runs without root.
- Page dims after `display.dim_after` idle minutes to `display.dim` and restores
  `display.bright` on the first tap (swallowed). Turn on / scheduled on also restore `bright`.
  Planner Display section: dim after, brightness sliders (dim slider previews for 3 s).

## Hardware / OS
- Raspberry Pi 4B, Raspberry Pi OS **Trixie** (Wayland, **labwc**).
- Hostname `weatherdash`, user **`weatherpi`** (not `pi`), project at `/home/weatherpi/wxdash`.
- Browser binary is **`chromium`** (not `chromium-browser`).
- Display: Corsair Xeneon Edge 14.5" 2560×720 touchscreen. Video over micro-HDMI→HDMI.
  Touch only works over the screen's USB-C data link (HDMI is video only). The screen
  needs 5V/2A, more than the Pi's USB ports reliably supply, so it should be powered
  through a powered USB hub or USB-C power+data splitter. Touch works (taps register;
  swipes needed the mouse-drag fallback).

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

- 2026-10-25: planner page, watches/suggestions, places by search; YAML example
  schedule removed (those cards were placeholders, not Doug's real plans).

## Places in config
home = Atlantic Highlands; **sandy_hook_lot_b = Doug's main surf spot** (Sandy Hook South Beach
Lot B, 40.4175/-73.979, faces 90° E, offshore = W/SW, swell window NE–SE, all tides OK);
long_branch = secondary example surf spot (faces 100° ESE); sandy_hook_bay = sailing. Coordinates and beach orientation are starting
guesses for Doug to adjust.
