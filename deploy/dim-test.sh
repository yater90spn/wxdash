#!/bin/sh
# Can the Pi set the Corsair's brightness over HDMI (DDC/CI)? If yes, wxdash can
# dim the screen when idle while the monitor stays awake, so a tap still works.
#   ~/wxdash/deploy/dim-test.sh
command -v ddcutil >/dev/null || { echo "Installing ddcutil..."; sudo apt install -y -qq ddcutil >/dev/null; }
sudo modprobe i2c-dev 2>/dev/null

echo "== Monitors that answer DDC/CI"
sudo ddcutil detect 2>&1 | sed 's/^/   /'

echo "== Current brightness (VCP 0x10)"
OUT=$(sudo ddcutil getvcp 10 2>&1); echo "   $OUT"
CUR=$(echo "$OUT" | sed -n 's/.*current value = *\([0-9]*\).*/\1/p')
if [ -z "$CUR" ]; then
  echo
  echo "== Verdict: the monitor doesn't expose brightness over HDMI. Paste the above back into the chat."
  exit 0
fi

echo "== Dropping brightness to 0 for 5 seconds (it was $CUR)... watch the screen"
sudo ddcutil setvcp 10 0 2>&1 | sed 's/^/   /'
sleep 5
sudo ddcutil setvcp 10 "$CUR" 2>&1 | sed 's/^/   /'
echo "   restored to $CUR"
echo
echo "== Did the screen get clearly darker for those 5 seconds? Tell me in the chat, along with everything above."
