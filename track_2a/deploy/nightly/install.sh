#!/bin/sh
# Install the nightly job as a systemd timer. Needs Linux with systemd, Docker, and root.
# Without them it prints what it would do and exits 0 (so `make install-nightly` never fails on a laptop).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
if [ "$(uname -s)" != "Linux" ] || ! command -v systemctl >/dev/null 2>&1 || [ "$(id -u)" != "0" ]; then
  echo "install-nightly: needs Linux + systemd + root. To install on the server:"
  echo "  docker build -t gegenprobe:0.1.0 $HERE/../..      # versioned tag; the unit runs \${GP_IMAGE}"
  echo "  sudo install -d -o 10001 -g 0 -m 0750 /var/lib/gegenprobe/work /var/lib/gegenprobe/results   # image uid"
  echo "  sudo install -d -m 0700 /etc/gegenprobe && sudo install -m 0600 $HERE/alerts.env.example /etc/gegenprobe/alerts.env"
  echo "  sudo cp $HERE/gegenprobe-nightly.service $HERE/gegenprobe-nightly-failure.service $HERE/gegenprobe-nightly.timer /etc/systemd/system/"
  echo "  (no Docker: sudo sh $HERE/install.sh --venv  creates the gegenprobe system user and /var/lib/gegenprobe and installs"
  echo "   gegenprobe-nightly-venv.service as gegenprobe-nightly.service; checkout in /opt/gegenprobe/track_2a, venv in"
  echo "   /opt/gegenprobe/.venv, see the unit's header)"
  echo "  sudo systemctl daemon-reload && sudo systemctl enable --now gegenprobe-nightly.timer"
  echo "  systemctl list-timers gegenprobe-nightly.timer   # next run"
  echo "  journalctl -u gegenprobe-nightly.service          # last run"
  exit 0
fi
install -d -m 0700 /etc/gegenprobe
[ -f /etc/gegenprobe/alerts.env ] || install -m 0600 "$HERE/alerts.env.example" /etc/gegenprobe/alerts.env
if [ "${1:-}" = "--venv" ]; then
  # no Docker: the job runs as an unprivileged system user and writes only under /var/lib/gegenprobe
  id gegenprobe >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gegenprobe --shell /usr/sbin/nologin gegenprobe
  install -d -o gegenprobe -g gegenprobe -m 0750 /var/lib/gegenprobe /var/lib/gegenprobe/work /var/lib/gegenprobe/results
  [ -x /opt/gegenprobe/.venv/bin/python ] || echo "warning: /opt/gegenprobe/.venv missing (python3.11 -m venv /opt/gegenprobe/.venv && /opt/gegenprobe/.venv/bin/pip install --require-hashes -r /opt/gegenprobe/track_2a/requirements.lock)"
  install -m 0644 "$HERE/gegenprobe-nightly-venv.service" /etc/systemd/system/gegenprobe-nightly.service
else
  docker image inspect gegenprobe:0.1.0 >/dev/null 2>&1 || docker build -t gegenprobe:0.1.0 "$HERE/../.."
  install -d -o 10001 -g 0 -m 0750 /var/lib/gegenprobe/work /var/lib/gegenprobe/results   # the image's uid
  install -m 0644 "$HERE/gegenprobe-nightly.service" /etc/systemd/system/
fi
install -m 0644 "$HERE/gegenprobe-nightly-failure.service" "$HERE/gegenprobe-nightly.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gegenprobe-nightly.timer
systemctl list-timers gegenprobe-nightly.timer --no-pager
