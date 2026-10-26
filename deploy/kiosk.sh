#!/bin/sh
# Started at desktop login. Waits for the wxdash server, then opens the
# dashboard full-screen. Log: ~/.cache/wxdash-kiosk.log
LOG="$HOME/.cache/wxdash-kiosk.log"
mkdir -p "$HOME/.cache"
exec >>"$LOG" 2>&1
echo "--- kiosk start $(date)"

URL="http://127.0.0.1:8080/"

# Wait up to ~2 minutes for the server (python fallback in case curl is missing)
i=0
until python3 -c "import urllib.request; urllib.request.urlopen('${URL}api/version', timeout=2)" 2>/dev/null; do
  i=$((i + 1)); [ "$i" -gt 60 ] && echo "server not reachable, launching anyway" && break
  sleep 2
done

# Trixie ships 'chromium'; older Pi OS ships 'chromium-browser'
BROWSER=$(command -v chromium || command -v chromium-browser)
if [ -z "$BROWSER" ]; then echo "no chromium found"; exit 1; fi
echo "launching $BROWSER"

exec "$BROWSER" \
  --kiosk --app="$URL" \
  --noerrdialogs --disable-infobars --no-first-run \
  --disable-session-crashed-bubble --disable-features=Translate \
  --password-store=basic --check-for-update-interval=31536000 \
  --overscroll-history-navigation=0 --disable-pinch \
  --touch-events=enabled
