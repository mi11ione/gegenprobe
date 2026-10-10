#!/bin/sh
# Install the nightly job as a systemd timer. Needs Linux with systemd, Docker, and root.
# Without them it prints what it would do and exits 0 (so `make install-nightly` never fails on a laptop).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
if [ "$(uname -s)" != "Linux" ] || ! command -v systemctl >/dev/null 2>&1 || [ "$(id -u)" != "0" ]; then
  echo "install-nightly: needs Linux + systemd + root. To install on the server:"
  echo "  docker build -t gegenprobe:0.1.0 $HERE/../..      # versioned tag; the unit runs \${GP_IMAGE}"
  echo "  sudo install -d -m 0700 /etc/gegenprobe && sudo install -m 0600 $HERE/alerts.env.example /etc/gegenprobe/alerts.env"
  echo "  sudo cp $HERE/gegenprobe-nightly.service $HERE/gegenprobe-nightly-failure.service $HERE/gegenprobe-nightly.timer /etc/systemd/system/"
  echo "  (no Docker: use gegenprobe-nightly-venv.service instead of gegenprobe-nightly.service, see the file header)"
  echo "  sudo systemctl daemon-reload && sudo systemctl enable --now gegenprobe-nightly.timer"
  echo "  systemctl list-timers gegenprobe-nightly.timer   # next run"
  echo "  journalctl -u gegenprobe-nightly.service          # last run"
  exit 0
fi
docker image inspect gegenprobe:0.1.0 >/dev/null 2>&1 || docker build -t gegenprobe:0.1.0 "$HERE/../.."
install -d -m 0700 /etc/gegenprobe
[ -f /etc/gegenprobe/alerts.env ] || install -m 0600 "$HERE/alerts.env.example" /etc/gegenprobe/alerts.env
install -m 0644 "$HERE/gegenprobe-nightly.service" "$HERE/gegenprobe-nightly-failure.service" \
  "$HERE/gegenprobe-nightly.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gegenprobe-nightly.timer
systemctl list-timers gegenprobe-nightly.timer --no-pager
