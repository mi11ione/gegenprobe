"""Stale procedural states (gegenprobe.findings.stale_states): the record check on synthetic records, and the committed
results/findings/stale_states.json equal to a fresh derivation from the committed records and census tables."""
import gzip
import json

import pytest

from gegenprobe.findings import stale_states as ss


def _rec(state="submitted", answer_doc="opd:2", answer_date=None, dates=()):
    qa = dict(answer_doc=answer_doc) if answer_doc else {}
    if answer_date:
        qa["answer_date"] = dict(kind="value", value=answer_date, route="rule")
    return dict(procedural_state=dict(kind="value", value=state, source="opd:events/7"),
                qa=[qa], dates=list(dates), ref=dict(body_key="X", opd_id=1))


def test_submitted_with_attached_answer_is_stale():
    ev = ss.stale_state(_rec())
    assert ev["kind"] == "answer_attached" and ev["answer_docs"] == ["opd:2"] and ev["state_source"] == "opd:events/7"


def test_submitted_with_answer_date_only_is_stale():
    ev = ss.stale_state(_rec(answer_doc=None, answer_date="2020-02-01"))
    assert ev["kind"] == "answer_dated" and ev["answer_dates"][0]["value"] == "2020-02-01"


def test_answer_role_in_dates_counts_and_order_is_reported():
    sub = dict(role="submitted", date=dict(kind="value", value="2020-03-01", source="opd:events/7"))
    ans = dict(role="answered", date=dict(kind="value", value="2020-02-01", source="opd:events/6"))
    ev = ss.stale_state(_rec(answer_doc=None, dates=[sub, ans]))
    assert ev["state_date"] == "2020-03-01" and ev["answer_before_state"] is True


def test_not_stale():
    assert ss.stale_state(_rec(state="answered")) is None
    assert ss.stale_state(_rec(answer_doc=None)) is None  # submitted, no answer anywhere
    r = _rec()
    r["procedural_state"] = dict(kind="null", null_reason="not_in_corpus")
    assert ss.stale_state(r) is None
    dated_null = dict(role="answered", date=dict(kind="null", null_reason="not_extracted"))
    assert ss.stale_state(_rec(answer_doc=None, dates=[dated_null])) is None


def test_committed_files_match_fresh_derivation():
    if not ss.OUT.exists() or not (ss.ROOT / "data" / "census" / "events.tsv.gz").exists():
        pytest.skip("stale_states inputs or output not present")
    text, tsv = ss.render()
    assert json.loads(text) == json.loads(ss.OUT.read_text(encoding="utf-8"))
    assert gzip.decompress(tsv) == gzip.decompress(ss.OUT_TSV.read_bytes())
    d = json.loads(text)
    assert d["records"]["n_records"] == 120
    c = d["census"]["totals"]
    assert max(c["stale_attached"], c["stale_answer_event"]) <= c["stale"] <= c["stale_attached"] + c["stale_answer_event"]
    assert c["strict"] <= c["stale_answer_event"] <= c["stale"] <= c["last_state_submitted"]
