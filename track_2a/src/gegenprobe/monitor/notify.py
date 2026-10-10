"""Alert routing for the nightly job. Nothing is sent unless configured; alerts.json is always written.

  GP_ALERT_WEBHOOK      URL that receives one JSON POST per night with alerts (Slack/Teams/Matrix-compatible `text` field
                        plus the structured alerts)
  GP_ALERT_SMTP_HOST    SMTP relay (port GP_ALERT_SMTP_PORT, default 587, STARTTLS); GP_ALERT_SMTP_USER / _PASSWORD
                        optional; GP_ALERT_MAIL_FROM, GP_ALERT_MAIL_TO (comma-separated)
  GP_ALERT_EXIT         process exit code when alerts fired (default 3; "0" keeps the job green), so a scheduler, a CI
                        job or systemd OnFailure= can react

    python -m gegenprobe.monitor.notify test      send a test message through every configured channel
"""
from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage

from .. import net


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


def exit_code(alerts: list[dict]) -> int:
    return int(os.environ.get("GP_ALERT_EXIT", "3")) if alerts else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["test"]:
        used = send([dict(kind="test", body="TEST", name="test alert")], dict(bodies_rated=0), force=True)
        print(used or "no channel configured")
    else:
        print(__doc__)
