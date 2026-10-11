"""Nightly operations: trend and staleness alerts, the cumulative ledger, the alert outbox, exit codes."""
import datetime as dt
import json

import pytest

from gegenprobe.monitor import nightly, notify


def _rates(rate, written=3400):
    return {"BE": dict(written=written, linked=int(written * rate / 100), rate=rate, docs=50000), "_docs_only": {}}


def test_trend_alert_fires_on_slow_drift_that_nightly_threshold_misses():
    history = [dict(ts=i, rates={"BE": 30.0 - 0.9 * i}) for i in range(7)]  # 0.9 pp a night, below the 2 pp alert
    cur = _rates(30.0 - 0.9 * 7)
    assert nightly.alerts({"BE": dict(_rates(history[-1]["rates"]["BE"])["BE"])}, cur) == []
    al = nightly.trend_alerts(history, cur, {"BE": "Bern"})
    assert [(a["body"], a["kind"], a["nights"]) for a in al] == [("BE", "rate_trend_drop", 7)]
    assert nightly.trend_alerts(history[:6], cur) == []  # fewer than 7 nights of history: no trend yet
    assert nightly.trend_alerts(history, _rates(26.0, written=10)) == []  # below MIN_AFFAIRS


def test_stale_exports_alert():
    now = dt.datetime(2026, 10, 10, 8, tzinfo=dt.timezone.utc).timestamp()
    assert nightly.stale_alert({"generated_at": "2026-10-10T04:45:00Z"}, now) == []
    al = nightly.stale_alert({"generated_at": "2026-10-06T04:45:00Z"}, now)
    assert al[0]["kind"] == "exports_stale" and al[0]["age_days"] == 4.1
    assert nightly.stale_alert(None, now) == []


def test_transient_fetch_failures_are_retried_permanent_ones_are_not():
    assert nightly.transient("fetch_error: URLError: <urlopen error timed out>")
    assert nightly.transient("fetch_error: text_timeout: tesseract exceeded 300 s")
    assert nightly.transient("fetch_error: HTTPError: HTTP Error 503: Service Unavailable")
    assert nightly.transient("fetch_error: Disallowed: https://x (robots.txt unreachable (URLError), fail-closed)")
    assert not nightly.transient("fetch_error: too_large: x")
    assert not nightly.transient("fetch_error: not_a_pdf: x")
    assert not nightly.transient("fetch_error: HTTPError: HTTP Error 404: Not Found")
    assert not nightly.transient("identity=False heading=True")


def _row(aid, verified=None, checks=None):
    r = dict(affair_id=aid, affair_number=f"2024.RRGR.{aid}", action="relink", opd_doc_id=aid * 10,
             source_doc_uid=f"uid{aid}", source_url=f"https://x/{aid}.pdf")
    if verified is not None:
        r.update(verified=verified, checks=checks or dict(identity=verified, heading=True, date_eq_event=verified))
    return r


def test_ledger_tracks_rows_across_nights(tmp_path):
    led = nightly.update_ledger({}, [_row(1, True), _row(2, False), _row(3, True)], {}, "2026-10-08")
    assert {v["affair_id"]: v["status"] for v in led.values()} == {1: "pending", 2: "review", 3: "pending"}
    path = tmp_path / "repair_BE_ledger.tsv"
    nightly.write_ledger(path, led)
    led = nightly.read_ledger(path)
    # night 2: row 1 still listed (no re-check), affair 2 now has its answer in OPD, affair 3 left the list unanswered
    led = nightly.update_ledger(led, [_row(1)], {2: dict(dAt=1)}, "2026-10-09")
    st = {v["affair_id"]: (v["status"], v["first_seen"], v["last_seen"]) for v in led.values()}
    assert st == {1: ("pending", "2026-10-08", "2026-10-09"), "2": ("resolved", "2026-10-08", "2026-10-08"),
                  "3": ("dropped", "2026-10-08", "2026-10-08")}
    nightly.write_ledger(path, led)
    assert path.read_text().splitlines()[0].split("\t") == nightly.LEDGER_COLS


def test_alerts_stay_in_the_outbox_when_sending_fails(monkeypatch, tmp_path):
    box = tmp_path / "outbox.json"
    al = [dict(kind="linking_rate_drop", body="BE", night="2026-10-09")]

    def down(alerts, run, force=False):
        raise OSError("webhook unreachable")

    monkeypatch.setattr(notify, "send", down)
    run = {}
    nightly.deliver(box, al, run)
    assert json.loads(box.read_text()) == al and run["notify_error"].startswith("OSError")
    monkeypatch.setattr(notify, "send", lambda alerts, run, force=False: ["webhook"] if alerts else [])
    run = {}
    nightly.deliver(box, al, run)
    assert not box.exists() and run["notified"] == ["webhook"] and run["notify_error"] is None


@pytest.mark.parametrize("raw,code", [("3", 3), ("0", 0), ("3   # exit code on alerts", 3), ("x", 3), (" 5 ", 5)])
def test_alert_exit_parsing(monkeypatch, raw, code):
    monkeypatch.setenv("GP_ALERT_EXIT", raw)
    assert notify.exit_code([{"kind": "x"}]) == code and notify.exit_code([]) == 0


def test_notify_test_exits_2_without_a_channel(monkeypatch, capsys):
    for k in ("GP_ALERT_WEBHOOK", "GP_ALERT_SMTP_HOST"):
        monkeypatch.delenv(k, raising=False)
    assert notify.main(["test"]) == 2
    assert "no channel configured" in capsys.readouterr().err


def test_alerts_env_template_has_no_trailing_comments():
    from gegenprobe.paths import ROOT

    for line in (ROOT / "deploy/nightly/alerts.env.example").read_text().splitlines():
        body = line.lstrip("#")
        if "=" in body and not line.startswith("# "):
            assert "#" not in body.split("=", 1)[1], line
