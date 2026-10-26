#!/bin/sh
# One-time (and re-runnable) setup for wxdash on Raspberry Pi OS.
#   sudo ~/wxdash/deploy/install.sh
# Sets up: Python venv, the wxdash server service, the auto-update timer,
# and the kiosk browser at desktop login. Safe to run again at any time.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="$(stat -c %U "$DIR")"
HOME_DIR="$(getent passwd "$OWNER" | cut -d: -f6)"
FROM_UPDATE=0; [ "$1" = "--from-update" ] && FROM_UPDATE=1

if [ "$(id -u)" -ne 0 ]; then echo "run with sudo"; exit 1; fi
as_owner() { runuser -u "$OWNER" -- "$@"; }
echo "wxdash: $DIR (user $OWNER)"

# 1. Python environment
if [ ! -x "$DIR/.venv/bin/python" ]; then
  as_owner python3 -m venv "$DIR/.venv"
fi
[ "$FROM_UPDATE" = 1 ] || as_owner "$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

# 1b. Screen power control (DPMS on the Wayland desktop)
if ! command -v wlopm >/dev/null 2>&1; then
  apt-get install -y -qq wlopm >/dev/null 2>&1 || echo "note: couldn't install wlopm; screen on/off won't work"
fi

# 2. Server service (listens on the network so you can open http://<host>:8080 elsewhere)
cat > /etc/systemd/system/wxdash.service <<EOF
[Unit]
Description=wxdash weather dashboard server
After=network-online.target
Wants=network-online.target

[Service]
User=$OWNER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python app.py --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 3. Auto-update from GitHub every 5 minutes
cat > /etc/systemd/system/wxdash-update.service <<EOF
[Unit]
Description=wxdash: pull updates from GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$DIR/deploy/update.sh
EOF
cat > /etc/systemd/system/wxdash-update.timer <<EOF
[Unit]
Description=wxdash: check GitHub for updates every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
chmod +x "$DIR/deploy/"*.sh
systemctl daemon-reload
if [ "$FROM_UPDATE" = 0 ]; then
  systemctl enable --now wxdash.service
  systemctl enable --now wxdash-update.timer
  systemctl restart wxdash.service
fi

# 4. Kiosk at desktop login (labwc, the Pi OS Bookworm/Trixie desktop).
# A user autostart file replaces the system one, so start from the system
# file (taskbar, desktop, etc.) and add the kiosk line once.
AUTO_DIR="$HOME_DIR/.config/labwc"
AUTO="$AUTO_DIR/autostart"
KIOSK_LINE="$DIR/deploy/kiosk.sh &"
as_owner mkdir -p "$AUTO_DIR"
if [ ! -f "$AUTO.wxdash-backup" ] && [ -f "$AUTO" ]; then
  as_owner cp "$AUTO" "$AUTO.wxdash-backup"
fi
TMP=$(mktemp)
[ -f /etc/xdg/labwc/autostart ] && grep -v 'kiosk.sh' /etc/xdg/labwc/autostart > "$TMP" || true
[ -f "$AUTO" ] && grep -v 'kiosk.sh' "$AUTO" | grep -vxFf "$TMP" >> "$TMP" || true
echo "$KIOSK_LINE" >> "$TMP"
install -o "$OWNER" -g "$(id -gn "$OWNER")" -m 644 "$TMP" "$AUTO"
rm -f "$TMP"

# Remove the XDG autostart variant if it was added by hand, to avoid two browsers
rm -f "$HOME_DIR/.config/autostart/wxdash.desktop"

echo "done. server: http://$(hostname).local:8080   (reboot to test the kiosk)"
