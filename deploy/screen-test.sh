#!/bin/sh
# Diagnose tap-to-wake. Run on the Pi (desktop terminal or SSH):
#   ~/wxdash/deploy/screen-test.sh
# It turns the screen off, checks whether the touch panel is still connected
# and still sends touches, then turns the screen back on and prints a verdict.

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "$WAYLAND_DISPLAY" ]; then
  WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR" 2>/dev/null | grep -E '^wayland-[0-9]+$' | head -1)
  export WAYLAND_DISPLAY
fi
if ! command -v wlopm >/dev/null; then echo "wlopm is missing: sudo apt install wlopm"; exit 1; fi
if [ -z "$WAYLAND_DISPLAY" ]; then echo "No desktop session found. Is the dashboard showing on the screen?"; exit 1; fi
command -v libinput >/dev/null || sudo apt install -y -qq libinput-tools >/dev/null

touch_devs() { grep -B1 -A0 -iE 'touch' /proc/bus/input/devices | grep -i 'Name=' | sed 's/.*Name=//'; }
TMP=$(mktemp -d)

echo "== 1. Recent wake attempts from the dashboard (server log, last hour)"
journalctl -u wxdash --since "-60min" --no-pager 2>/dev/null | grep -E 'display/power' | tail -5 | sed 's/^/   /'
[ -z "$(journalctl -u wxdash --since '-60min' --no-pager 2>/dev/null | grep 'display/power')" ] && echo "   (none)"

echo "== 2. With the screen ON"
lsusb > "$TMP/usb_on"; touch_devs > "$TMP/touch_on"
echo "   touch devices:"; sed 's/^/     /' "$TMP/touch_on"; [ -s "$TMP/touch_on" ] || echo "     (none found!)"

echo "== 3. Turning the screen OFF for ~20 seconds..."
wlopm --off '*'; sleep 6
lsusb > "$TMP/usb_off"; touch_devs > "$TMP/touch_off"
echo "   touch devices now:"; sed 's/^/     /' "$TMP/touch_off"; [ -s "$TMP/touch_off" ] || echo "     (none)"
echo "   USB changes:"; diff "$TMP/usb_on" "$TMP/usb_off" | grep '^[<>]' | sed 's/^/     /'; diff -q "$TMP/usb_on" "$TMP/usb_off" >/dev/null && echo "     (none)"

echo ">> TAP THE DARK SCREEN a few times now (listening 10 s; may ask for your password)"
sudo timeout 10 libinput debug-events 2>/dev/null | grep -E 'TOUCH_DOWN|POINTER_BUTTON|POINTER_MOTION' | head -3 > "$TMP/events"
echo "   events seen while off:"; sed 's/^/     /' "$TMP/events"; [ -s "$TMP/events" ] || echo "     (none)"

echo "== 4. Turning the screen back ON"
wlopm --on '*'

echo
echo "== Verdict"
if [ -s "$TMP/touch_on" ] && [ ! -s "$TMP/touch_off" ]; then
  echo "   The monitor disconnects its touch panel in standby, so a tap can't wake it."
elif [ ! -s "$TMP/events" ]; then
  echo "   The touch panel stays connected but sends nothing while the screen is off."
else
  echo "   Touches DO arrive while the screen is off. The problem is in the browser or the wake request."
fi
echo "   Paste everything above back into the chat."
rm -rf "$TMP"
