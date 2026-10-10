from gegenprobe.monitor import nightly


def _idx(files):
    return {
        "files": [
            {"entity": "affairs", "type": "single", "size": files.pop("affairs"), "created": "t"},
            {
                "entity": "docs",
                "type": "split",
                "files": [{"filename": f"{k}.ndjson.gz", "size": v, "created": "t"} for k, v in files.items()],
            },
        ]
    }


def test_index_diff():
    old = _idx({"affairs": 10, "docs_BE": 5, "docs_ZH": 7})
    new = _idx({"affairs": 11, "docs_BE": 5, "docs_ZH": 8, "docs_TI": 3})
    d = nightly.index_diff(old, new)
    assert d["changed"] == ["affairs", "docs_ZH"] and d["new"] == ["docs_TI"] and d["unchanged"] == 1


def test_alerts():
    prev = {
        "BE": dict(written=3400, linked=900, rate=26.47, docs=50000),
        "ZH": dict(written=10000, linked=7000, rate=70.0, docs=33000),
        "XS": dict(written=10, linked=9, rate=90.0, docs=100),
    }
    cur = {
        "BE": dict(written=3410, linked=820, rate=24.05, docs=50010),
        "ZH": dict(written=10010, linked=7000, rate=69.93, docs=20000),
        "XS": dict(written=10, linked=1, rate=10.0, docs=100),
        "NEW": dict(written=60, linked=6, rate=10.0, docs=10),
        "_docs_only": {},
    }
    al = nightly.alerts(prev, cur, {"BE": "Bern", "ZH": "Zürich"})
    kinds = {(a["body"], a["kind"]) for a in al}
    assert kinds == {("BE", "linking_rate_drop"), ("ZH", "document_count_drop"), ("NEW", "new_body")}  # XS below MIN_AFFAIRS
    assert {a["body"]: a["name"] for a in al}["BE"] == "Bern"


def test_body_gone_alert():
    prev = {"BE": dict(written=3400, linked=900, rate=26.47, docs=50000), "ZH": dict(written=10000, linked=7000, rate=70.0,
                                                                                      docs=33000)}
    cur = {"BE": dict(prev["BE"]), "_docs_only": {}}
    assert [(a["body"], a["kind"]) for a in nightly.alerts(prev, cur)] == [("ZH", "body_gone")]


def test_notify_exit_code_and_quiet_nights(monkeypatch):
    from gegenprobe.monitor import notify

    monkeypatch.delenv("GP_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("GP_ALERT_SMTP_HOST", raising=False)
    assert notify.exit_code([]) == 0 and notify.exit_code([{"kind": "x"}]) == 3
    monkeypatch.setenv("GP_ALERT_EXIT", "0")
    assert notify.exit_code([{"kind": "x"}]) == 0
    assert notify.send([], {}) == [] and notify.send([{"kind": "x", "body": "B"}], {}) == []  # nothing configured
    assert "body_gone" in notify.text([dict(kind="body_gone", body="ZH", name="Zürich")], {})
