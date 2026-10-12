#!/bin/sh
# Install the nightly job as a systemd timer. Needs Linux with systemd, Docker, and root.
# Without them it prints what it would do and exits 0 (so `make install-nightly` never fails on a laptop).
#   sh install.sh [--venv] [--user-agent "your-product/0.1 (+https://your.org/contact)"]
# GP_USER_AGENT is required: --user-agent writes it into /etc/gegenprobe/alerts.env; without it the value already there
# is used. The template's placeholder, a value without an http(s) contact URL, a reserved example domain or an e-mail
# address is refused: nothing is installed beyond the alerts.env template and the script exits 1 (fail-closed; the
# night itself refuses the same values, gegenprobe.monitor.nightly.ua_refusal).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
VENV=""
UA_ARG=""
VENV_PY=/opt/gegenprobe/.venv/bin/python
TESSDATA_PINNED=/opt/gegenprobe/tessdata-pinned   # = TESSDATA_PREFIX in gegenprobe-nightly-venv.service
while [ $# -gt 0 ]; do
  case "$1" in
    --venv) VENV=1 ;;
    --user-agent) [ $# -ge 2 ] || { echo "install-nightly: --user-agent needs a value" >&2; exit 2; }; UA_ARG="$2"; shift ;;
    --user-agent=*) UA_ARG="${1#*=}" ;;
    *) echo "install-nightly: unknown argument $1 (use --venv, --user-agent VALUE)" >&2; exit 2 ;;
  esac
  shift
done
# ua_ok VALUE: a contact URL whose host can reach someone (same rule as gegenprobe.monitor.nightly.contact_url), no e-mail
ua_ok() {
  case "$1" in *@*) return 1 ;; esac
  printf '%s\n' "$1" | grep -Eo 'https?://[A-Za-z0-9.-]+' | sed 's#^https\{0,1\}://##; s#\.$##' | tr 'A-Z' 'a-z' \
    | grep '\.' | grep -Evq '(^|\.)(example\.(com|net|org|ch)|example|invalid|test|localhost|set-me|change-me)$'
}
if [ -n "$UA_ARG" ] && ! ua_ok "$UA_ARG"; then
  echo "install-nightly: --user-agent '$UA_ARG' names no contact URL that reaches you (or contains an e-mail address); refused" >&2
  exit 1
fi
if [ "$(uname -s)" != "Linux" ] || ! command -v systemctl >/dev/null 2>&1 || [ "$(id -u)" != "0" ]; then
  echo "install-nightly: needs Linux + systemd + root. To install on the server:"
  echo "  docker build -t gegenprobe:0.1.0 $HERE/../..      # versioned tag; the unit runs \${GP_IMAGE}"
  echo "  sudo install -d -o 10001 -g 0 -m 0750 /var/lib/gegenprobe/work /var/lib/gegenprobe/results   # image uid"
  echo "  sudo install -d -m 0700 /etc/gegenprobe && sudo install -m 0600 $HERE/alerts.env.example /etc/gegenprobe/alerts.env"
  echo "  sudoedit /etc/gegenprobe/alerts.env   # REQUIRED: GP_USER_AGENT=<your product>/0.1 (+https://<your contact page>)"
  echo "  sudo cp $HERE/gegenprobe-nightly.service $HERE/gegenprobe-nightly-failure.service $HERE/gegenprobe-nightly.timer /etc/systemd/system/"
  echo "  (on the server: sudo sh $HERE/install.sh [--venv] --user-agent '<your product>/0.1 (+https://<your contact page>)')"
  echo "  (no Docker: sudo sh $HERE/install.sh --venv  creates the gegenprobe system user and /var/lib/gegenprobe, puts the"
  echo "   pinned OCR models into $TESSDATA_PINNED (sha256-checked) and installs gegenprobe-nightly-venv.service as"
  echo "   gegenprobe-nightly.service; checkout in /opt/gegenprobe/track_2a, venv in /opt/gegenprobe/.venv, see the unit's header)"
  echo "  sudo systemctl daemon-reload && sudo systemctl enable --now gegenprobe-nightly.timer"
  echo "  systemctl list-timers gegenprobe-nightly.timer   # next run"
  echo "  journalctl -u gegenprobe-nightly.service          # last run"
  exit 0
fi
install -d -m 0700 /etc/gegenprobe
[ -f /etc/gegenprobe/alerts.env ] || install -m 0600 "$HERE/alerts.env.example" /etc/gegenprobe/alerts.env
if [ -n "$UA_ARG" ]; then  # one GP_USER_AGENT line: the given value replaces the template's placeholder (or an older value)
  tmp=$(mktemp)
  grep -v '^GP_USER_AGENT=' /etc/gegenprobe/alerts.env > "$tmp" || true
  printf 'GP_USER_AGENT=%s\n' "$UA_ARG" >> "$tmp"
  install -m 0600 "$tmp" /etc/gegenprobe/alerts.env
  rm -f "$tmp"
fi
UA_SET=$(sed -n 's/^GP_USER_AGENT=//p' /etc/gegenprobe/alerts.env | tail -n 1)
if ! ua_ok "$UA_SET"; then
  echo "install-nightly: GP_USER_AGENT in /etc/gegenprobe/alerts.env is '${UA_SET:-unset}': it names no contact URL that" >&2
  echo "  reaches you. Nothing installed (fail-closed). Set your own product token and contact URL, e.g." >&2
  echo "  sudo sh $0 ${VENV:+--venv }--user-agent 'opd-gegenprobe/0.1 (+https://www.openparldata.ch)'" >&2
  exit 1
fi
if [ -n "$VENV" ]; then
  # no Docker: the job runs as an unprivileged system user and writes only under /var/lib/gegenprobe
  id gegenprobe >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gegenprobe --shell /usr/sbin/nologin gegenprobe
  install -d -o gegenprobe -g gegenprobe -m 0750 /var/lib/gegenprobe /var/lib/gegenprobe/work /var/lib/gegenprobe/results
  [ -x "$VENV_PY" ] || echo "warning: /opt/gegenprobe/.venv missing (python3.11 -m venv /opt/gegenprobe/.venv && /opt/gegenprobe/.venv/bin/pip install --require-hashes -r /opt/gegenprobe/track_2a/requirements.lock)"
  # OCR with the models the OCR numbers were measured with, as in the image: the pinned tessdata_fast files (deu, fra,
  # ita, eng) into $TESSDATA_PINNED, each sha256-checked, then tesseract checked with them under GP_OCR_REQUIRE_PINNED=1
  # (gegenprobe.ocr_models, the same code as `make ocr-models`). The unit points tesseract there (TESSDATA_PREFIX) and
  # refuses other models (GP_OCR_REQUIRE_PINNED=1); /opt is read-only for the job. Fail-closed: no unit without them.
  if ! GP_USER_AGENT="$UA_SET" PYTHONPATH="$HERE/../../src" "$VENV_PY" -m gegenprobe.ocr_models "$TESSDATA_PINNED"; then
    echo "install-nightly: the pinned OCR models are not ready in $TESSDATA_PINNED (venv, tesseract-ocr and network to" >&2
    echo "  raw.githubusercontent.com needed; reason above). Nothing installed (fail-closed)." >&2
    exit 1
  fi
  chmod -R a+rX,go-w "$TESSDATA_PINNED"
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
