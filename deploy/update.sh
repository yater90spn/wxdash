#!/bin/sh
# Pull the latest code from GitHub; if anything changed, refresh dependencies
# and restart the server. Run by wxdash-update.timer every 5 minutes.
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
OWNER="$(stat -c %U "$DIR")"
as_owner() { runuser -u "$OWNER" -- "$@"; }

cd "$DIR"
as_owner git fetch --quiet origin
LOCAL=$(as_owner git rev-parse HEAD)
REMOTE=$(as_owner git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0

echo "updating $LOCAL -> $REMOTE"
REQ_BEFORE=$(sha1sum requirements.txt)
# The repo is the source of truth: discard any local edits to tracked files.
as_owner git reset --hard --quiet origin/main
if [ "$REQ_BEFORE" != "$(sha1sum requirements.txt)" ]; then
  as_owner "$DIR/.venv/bin/pip" install --quiet -r requirements.txt
fi
# Re-run install steps that may have changed (service files, autostart)
"$DIR/deploy/install.sh" --from-update
systemctl restart wxdash
echo "now at $(as_owner git rev-parse --short HEAD)"
