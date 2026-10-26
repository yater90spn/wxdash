# wxdash — activity-aware weather board

Pulls hourly forecasts from Open-Meteo (HRRR → NBM → GFS blend, plus the
Marine API and NOAA tide predictions), scores your scheduled activities hour
by hour, and shows a touch dashboard sized for a 2560×720 panel.

```
Saturday baseball · 10 AM–1 PM
Comfort: 6.2 / 10 — chilly and breezy
55–58°F · Feels like 50–53°F · Mostly cloudy
NW 13–17 mph, gusts 26 mph · Low rain risk
Bring: medium jacket + hat, blanket for the bleachers; wind matters more than rain.
```

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py --demo          # synthetic data, no network
.venv/bin/python app.py --print         # live data, cards printed to terminal
.venv/bin/python app.py                 # live dashboard on http://<pi>:8080
```

`config.yaml` hot-reloads — edit it and the screen picks it up on the next refresh.

## How it works

| File | Role |
|---|---|
| `wxdash/sources/openmeteo.py` | Forecast (multi-model) + marine fetch. Requests unixtime so the Nov 1 DST change doesn't skew hours. |
| `wxdash/sources/noaa.py` | CO-OPS tide predictions + observed water temp. Preferred over the modelled sea level, which Open-Meteo says is unreliable near coasts. |
| `wxdash/blend.py` | Picks the best model per variable per hour, records model spread for the confidence line. |
| `wxdash/activities/*.py` | One scorer per activity. |
| `wxdash/engine.py` | Schedule → windows (fixed or "best window") → cards. |
| `static/index.html` | The dashboard. |

**Model blending.** First non-null value in `models:` order wins. HRRR (3 km,
hourly updates) covers the next 18–48 h, then NBM and GFS take over. Some
variables only come from certain models: precipitation probability from NBM/GFS
and UV from GFS only (`VAR_PRIORITY` in `blend.py`).

**Confidence line.** "Models agree / Models disagree · temp ±4°" comes from the
spread between models for that window; anything 5+ days out is flagged low.

## Scoring rules

Every threshold is a curve of `[value, score]` points (linear between points),
overridable globally under `rules:` or per schedule entry:

```yaml
rules:
  spectator:
    feels_like: [[25,1],[35,3],[45,6],[55,8],[65,9.6],[70,10],[78,10],[84,8.5],[90,6]]
    wind:       [[0,0],[7,0],[12,0.4],[18,1.2],[25,3]]      # penalty points
    rain:       [[0,0],[20,0],[40,0.6],[60,1.8],[80,3.5]]   # penalty by % chance
```

Window score = 70% average + 30% worst hour, so one bad hour drags it down.

| Activity | Main inputs |
|---|---|
| `spectator` (alias `baseball`) | feels-like, wind, sun vs. temp, rain; clothing ladder → "Bring:" |
| `surf` | swell height/period/direction vs. beach `facing` and `swell_window`, wind offshore/cross/onshore, tide phase/trend prefs, water temp → wetsuit |
| `sailing` | wind in knots vs. boat's `wind_kt` ideal/reef/max, gust spread, waves, cold water, storms, visibility, trend (building/easing) |
| `running` | feels-like (dress +15°F), dew point, wet-bulb heat cap, wind (start into it), darkness |
| `yardwork` | `task: general/mow/leaves/spray/plant` — wet ground from prior rain, morning dew, leaf/spray wind limits, rain after spraying |

Add a new activity by subclassing `Activity` (`score_hour` + `summarize`) and
registering it in `activities/__init__.py`.

## Planning activities

Open **`http://weatherdash.local:8080/plan`** from any computer or phone on your network.

- **Add a plan:** pick the activity, place, a date (or weekdays) and a time range. Tick
  "I'm flexible" to have it pick the best N hours in that range. The rating shows
  while you fill in the form, and the dashboard updates within ~20 seconds of saving.
- **Watch for good conditions:** turn on surf, sailing, running or yard work, set the
  hours, days and the minimum score. Days that clear the bar show up as "Suggested"
  cards. If nothing qualifies, the planner shows the best window and its score.
- **Places:** "+ New place" searches by name. For a surf spot, set which way the
  beach faces so wind and swell can be judged.

Plans are saved in `data/plans.json` on the Pi (not in git, so updates never touch them).
`config.yaml` still holds built-in places, model settings and scoring rules.

## Raspberry Pi setup (Pi OS Bookworm/Trixie, labwc desktop)

The Pi runs a git clone of this repository and updates itself: every 5 minutes
`wxdash-update.timer` checks GitHub, pulls changes, and restarts the server; the
dashboard page notices the new version and reloads within a minute.

First-time setup (private repo, read-only deploy key):

```bash
sudo apt install -y git
ssh-keygen -t ed25519 -f ~/.ssh/wxdash_deploy -N "" -C "$(hostname)"
cat ~/.ssh/wxdash_deploy.pub     # add on GitHub: repo → Settings → Deploy keys (read-only)
git clone -c core.sshCommand="ssh -i $HOME/.ssh/wxdash_deploy -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  git@github.com:yater90spn/wxdash.git ~/wxdash
sudo ~/wxdash/deploy/install.sh
sudo reboot
```

`install.sh` is safe to re-run. It creates the venv, the `wxdash` server service
(listening on port 8080 on the network), the update timer, and adds the kiosk to
`~/.config/labwc/autostart` (merged with the system autostart so the taskbar stays).

Useful commands:

| What | Command |
|---|---|
| Server status / logs | `systemctl status wxdash` · `journalctl -u wxdash -n 50` |
| Update log | `journalctl -u wxdash-update -n 20` |
| Update now | `sudo systemctl start wxdash-update` |
| Kiosk log | `cat ~/.cache/wxdash-kiosk.log` |
| View from another computer | `http://weatherdash.local:8080` |
| Leave kiosk | Alt+F4 |

Local edits to tracked files on the Pi are overwritten by the next update —
make changes in the repository instead.

Display notes: the Xeneon Edge needs HDMI for video plus its USB-C connected to a
powered hub (5V/2A) that also connects to the Pi for touch. The screen dims from an
hour after sunset; add `?nodim` to the URL in `deploy/kiosk.sh` to disable.

Data: [Open-Meteo](https://open-meteo.com) (free for non-commercial use, no key)
and [NOAA CO-OPS](https://tidesandcurrents.noaa.gov). Tide data here is for
planning, not navigation.
