import copy
import datetime as dt
import json
import re

import pytest

from gegenprobe.paths import RESULTS
from gegenprobe.schema.schema_v0_1 import Affair, DateValue, TypedNull
from gegenprobe.schema.samples import BE91_SHA, CHE_SHA, _pages
from gegenprobe.validate import check_affair, distractor, find_dates, normalise_date, recheck, self_deletion, summarise, validate
from gegenprobe.validate.report import to_markdown


@pytest.mark.parametrize(
    "s,iso",
    [
        ("28. August 2024", "2024-08-28"),
        ("28.08.2024", "2024-08-28"),
        ("28.8.2024", "2024-08-28"),
        ("28 août 2024", "2024-08-28"),
        ("28 agosto 2024", "2024-08-28"),
        ("2024-08-28", "2024-08-28"),
        ("1er août 2024", "2024-08-01"),
        ("1° agosto 2024", "2024-08-01"),
        ("1º marzo 2023", "2023-03-01"),
        ("1. März 2023", "2023-03-01"),
        ("3 sept. 2024", "2024-09-03"),
        ("28. Aug. 2024", "2024-08-28"),
        ("Mittwoch, 28. August 2024", "2024-08-28"),
        ("28/08/2024", "2024-08-28"),
        ("31 décembre 1999", "1999-12-31"),
        ("17 giugno 2005", "2005-06-17"),
        ("7. Januar 2014", "2014-01-07"),
        ("19 novembre 2025", "2025-11-19"),
    ],
)
def test_normalise_ok(s, iso):
    assert normalise_date(s) == iso


@pytest.mark.parametrize(
    "s",
    [
        "28.08.24",
        "30.02.2024",
        "August 2024",
        "2024",
        "RRB 879/2024 vom 28. August 2024",
        "28.08.2024 und 29.08.2024",
        "",
        "Sept. 2024",
        "32.01.2024",
    ],
)
def test_normalise_refused(s):
    assert normalise_date(s) is None


def test_find_dates_spans():
    t = "Letzte Bearbeitung: 19.03.2024 | Version: 4\nRRB-Nr.: 879/2024 vom 28. August 2024"
    got = find_dates(t)
    assert [g["iso"] for g in got] == ["2024-03-19", "2024-08-28"]
    for g in got:
        assert t[g["start"] : g["end"]] == g["raw"]


def _dv(page, s, e, quote, value="2024-08-28"):
    return DateValue(value=value, basis="normalised", route="rule", doc="d", page=page, char_start=s, char_end=e, quote=quote)


def test_recheck_codes():
    pages = ["Kopf\nRRB-Nr.: 879/2024 vom 28. August 2024\n", "Seite 2"]
    i = pages[0].index("28. August")
    assert recheck(_dv(1, i, i + 15, "28. August 2024"), pages).code == "ok"
    assert recheck(_dv(3, i, i + 15, "28. August 2024"), pages).code == "page_out_of_range"
    assert recheck(_dv(1, i, i + 999, "28. August 2024"), pages).code == "span_out_of_range"
    assert recheck(_dv(1, i, i + 15, "29. August 2024"), pages).code == "quote_mismatch"
    assert recheck(_dv(1, i, i + 15, "28. August 2024", value="2024-08-29"), pages).code == "value_not_in_span"
    meta = DateValue(value="2024-08-28", basis="metadata", route="metadata", source="opd:events/1")
    assert recheck(meta, pages).code == "no_span"


SAMPLE_TEXTS = {"be-ogd:0778ef860e7d4e5c8ab89d1fe2922a42": BE91_SHA, "fedlex:eli/fga/2014/2095/de": CHE_SHA}


def test_samples_span_recheck_when_texts_cached():
    texts = {k: _pages(v) for k, v in SAMPLE_TEXTS.items()}
    texts = {k: v for k, v in texts.items() if v is not None}
    if not texts:
        pytest.skip("sample PDFs not cached in WORK (dev-only check)")
    for p in sorted((RESULTS / "schema" / "samples").glob("*.json")):
        r = validate(json.loads(p.read_text()), texts)
        assert r["schema_ok"] and not r["issues"], (p.name, r)
        assert all(s["ok"] for s in r["spans"] if s["code"] != "text_missing"), (p.name, r["spans"])


def test_consistency_rules():
    obj = json.loads((RESULTS / "schema" / "samples" / "be_2024_RRGR_91.json").read_text())
    assert check_affair(Affair.model_validate(obj)) == []
    bad = copy.deepcopy(obj)
    bad["government_recommendation"] = dict(kind="value", value="reject", basis="metadata", route="metadata", source="x")
    assert [i.rule for i in check_affair(Affair.model_validate(bad))] == ["N5"]
    bad = copy.deepcopy(obj)
    bad["answer_link_status"] = "oral"
    assert "N4" in {i.rule for i in check_affair(Affair.model_validate(bad))}
    bad = copy.deepcopy(obj)
    bad["documents"][2]["image_only"] = True
    assert "N3" in {i.rule for i in check_affair(Affair.model_validate(bad))}


def test_validate_reports_schema_errors():
    r = validate({"ref": {}})
    assert not r["schema_ok"] and r["errors"]


# --------------------------------------------------------------------------- harnesses with toy converters
ANCHOR = re.compile(r"RRB-Nr\.:\s*\d+/\d{4}\s+vom\s+")
DOC = [
    "Interpellation 2024.RRGR.91\nEingereicht am 13.03.2024\nRRB-Nr.: 879/2024 vom 28. August 2024\nAntwort des Regierungsrates\n"
]


def anchored(pages, field):
    """Picks a date only right after an RRB anchor; else a typed null."""
    for p, t in enumerate(pages, 1):
        m = ANCHOR.search(t)
        if m:
            for d in find_dates(t[m.end() : m.end() + 40]):
                s, e = m.end() + d["start"], m.end() + d["end"]
                return DateValue(
                    value=d["iso"], basis="normalised", route="rule", doc="d", page=p, char_start=s, char_end=e, quote=t[s:e]
                )
    return TypedNull(null_reason="present_unanchored", route="rule", evidence="no RRB anchor")


def last_date(pages, field):
    """The naive behaviour: return the last date in the document, whatever it is."""
    best = None
    for p, t in enumerate(pages, 1):
        for d in find_dates(t):
            best = DateValue(
                value=d["iso"],
                basis="normalised",
                route="rule",
                doc="d",
                page=p,
                char_start=d["start"],
                char_end=d["end"],
                quote=d["raw"],
            )
    return best or TypedNull(null_reason="not_in_corpus", route="rule", evidence="no date")


def test_self_deletion_pass_and_fail():
    assert self_deletion(anchored, DOC, "answer_date").result == "pass"
    assert self_deletion(last_date, DOC, "answer_date").result == "fail"  # falls back to the submission date
    none_doc = ["Eingereicht am 13.03.2024\n"]
    assert self_deletion(anchored, none_doc, "answer_date").result == "skipped"


def test_distractor_pass_and_fail():
    r = distractor(anchored, DOC, "answer_date")
    assert r.result == "pass", r
    r = distractor(last_date, DOC, "answer_date")
    assert r.result == "fail" and "footer" in r.detail
    r = distractor(anchored, ["Eingereicht am 13.03.2024\n"], "answer_date", lang="fr")
    assert r.result == "pass"


def test_distractor_date_absent_from_doc():
    from gegenprobe.validate.harness import absent_date

    pages = ["19.03.2031 und 20.03.2031"]
    assert absent_date(pages) == dt.date(2031, 3, 21)


def test_summarise():
    recs = [
        dict(field="answer_date", test="distractor", result="pass"),
        dict(field="answer_date", test="distractor", result="fail"),
        dict(field="answer_date", test="self_deletion", result="skipped"),
    ]
    s = summarise(recs)
    assert s["answer_date"]["distractor"] == dict(passed=1, failed=1, skipped=0, n=2)
    assert "| answer_date | distractor | 1/2 | 1 | 0 |" in to_markdown(s)
