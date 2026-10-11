"""Alert routing for the nightly job. Nothing is sent unless configured; alerts.json is always written.

  GP_ALERT_WEBHOOK      URL that receives one JSON POST per night with alerts (Slack/Teams/Matrix-compatible `text` field
                        plus the structured alerts)
  GP_ALERT_SMTP_HOST    SMTP relay (port GP_ALERT_SMTP_PORT, default 587, STARTTLS); GP_ALERT_SMTP_USER / _PASSWORD
                        optional; GP_ALERT_MAIL_FROM, GP_ALERT_MAIL_TO (comma-separated)
  GP_ALERT_EXIT         process exit code when alerts fired (default 3; "0" keeps the job green), so a scheduler, a CI
                        job or systemd OnFailure= can react

    python -m gegenprobe.monitor.notify test      send a test message through every configured channel
                                                  (exit 0 sent, 2 no channel configured, 1 a channel failed)

Outbox (WORK/nightly/outbox.json): alerts not yet delivered. It is written atomically (temporary file in the same directory,
fsync, rename), so a crash or a full disk mid-write leaves the previous outbox intact, never a half-written one. An outbox that
cannot be parsed anyway (edited by hand, disk error) is moved aside to outbox.json.corrupt-<UTC timestamp> and reported as an
`outbox_corrupt` alert; the night continues instead of failing every night on the same file.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from .. import net
from gegenprobe.compliance import fetchguard

fetchguard.ensure()  # fail-closed: no fetch without the RFC 9309 matcher (compliance/fetchguard.py)


def write_json_atomic(path: Path, obj) -> None:
    """Write JSON so that readers see either the old or the new file, never a partial one (tmp + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, indent=1, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    try:  # persist the rename itself (POSIX); not available on every platform/filesystem
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_outbox(outbox: Path, alerts: list[dict]) -> None:
    write_json_atomic(outbox, alerts)


def read_outbox(outbox: Path) -> tuple[list[dict], list[dict]]:
    """(pending alerts, alerts about the outbox itself). A corrupt outbox is quarantined, never fatal."""
    if not outbox.exists():
        return [], []
    try:
        pending = json.loads(outbox.read_text(encoding="utf-8"))
        if not isinstance(pending, list) or not all(isinstance(a, dict) and "kind" in a for a in pending):
            raise ValueError(f"expected a JSON list of alerts, got {type(pending).__name__}")
        return pending, []
    except (ValueError, UnicodeDecodeError) as e:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        bad = outbox.with_name(f"{outbox.name}.corrupt-{stamp}")
        os.replace(outbox, bad)
        print(f"alert outbox {outbox} unreadable ({type(e).__name__}); moved to {bad}", file=sys.stderr)
        return [], [dict(body="_outbox", name="nightly alert outbox", kind="outbox_corrupt", quarantined=str(bad),
                         error=f"{type(e).__name__}: {str(e)[:160]}")]


def text(alerts: list[dict], run: dict) -> str:
    if not alerts:
        return f"Gegenprobe nightly: no alerts ({run.get('bodies_rated', '?')} parliaments rated)."
    lines = [f"Gegenprobe nightly: {len(alerts)} alert(s)"]
    for a in alerts:
        name = a.get("name") or a.get("body")
        detail = {k: v for k, v in a.items() if k not in ("body", "name", "kind")}
        lines.append(f"- {a['kind']} · {name} ({a.get('body')}): {json.dumps(detail, ensure_ascii=False)}")
    return "\n".join(lines)


def send(alerts: list[dict], run: dict, force: bool = False) -> list[str]:
    """Send through every configured channel; returns the channels used. Only nights with alerts are sent (or force)."""
    if not alerts and not force:
        return []
    msg, used = text(alerts, run), []
    hook = os.environ.get("GP_ALERT_WEBHOOK")
    if hook:
        body = json.dumps(dict(text=msg, alerts=alerts, run=run), ensure_ascii=False).encode()
        req = urllib.request.Request(hook, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": net.UA})
        with urllib.request.urlopen(req, timeout=30):
            pass
        used.append("webhook")
    host = os.environ.get("GP_ALERT_SMTP_HOST")
    if host:
        m = EmailMessage()
        m["Subject"] = f"[gegenprobe] {len(alerts)} alert(s)" if alerts else "[gegenprobe] test"
        m["From"] = os.environ.get("GP_ALERT_MAIL_FROM", "gegenprobe@localhost")
        m["To"] = os.environ["GP_ALERT_MAIL_TO"]
        m.set_content(msg)
        with smtplib.SMTP(host, int(os.environ.get("GP_ALERT_SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            if os.environ.get("GP_ALERT_SMTP_USER"):
                s.login(os.environ["GP_ALERT_SMTP_USER"], os.environ.get("GP_ALERT_SMTP_PASSWORD", ""))
            s.send_message(m)
        used.append("smtp")
    return used


def alert_exit() -> int:
    """GP_ALERT_EXIT as an int; tolerant of a trailing comment or whitespace copied from an env template."""
    raw = os.environ.get("GP_ALERT_EXIT", "3").split("#", 1)[0].strip()
    try:
        return int(raw)
    except ValueError:
        print(f"GP_ALERT_EXIT={raw!r} is not an integer; using 3", file=sys.stderr)
        return 3


def exit_code(alerts: list[dict]) -> int:
    return alert_exit() if alerts else 0


def main(argv: list[str]) -> int:
    if argv == ["test"]:
        try:
            used = send([dict(kind="test", body="TEST", name="test alert")], dict(bodies_rated=0), force=True)
        except Exception as e:
            print(f"sending failed: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if not used:
            print("no channel configured (set GP_ALERT_WEBHOOK or GP_ALERT_SMTP_HOST)", file=sys.stderr)
            return 2
        print("sent via", ", ".join(used))
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
