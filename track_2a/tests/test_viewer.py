"""The committed evidence viewer: renders from site/data.json alone, shows every view's data, and carries document text
only as short excerpt windows (never full texts)."""
import json
import re

from gegenprobe.viewer.__main__ import SITE, render
from gegenprobe.viewer.data import EXCERPT_MAX


def _texts(o, out):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "t" and isinstance(v, str):
                out.append(v)
            else:
                _texts(v, out)
    elif isinstance(o, list):
        for v in o:
            _texts(v, out)
    return out


def test_committed_site_has_no_full_texts():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    assert all("text" not in doc for doc in d["documents"]), "full page texts must never be committed"
    ex = _texts(d["documents"], [])
    assert ex and max(map(len, ex)) <= EXCERPT_MAX + 20


def test_every_view_has_data():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    assert len(d["documents"]) == 154
    assert len(d["parliaments"]["rows"]) == 89 and len(d["parliaments"]["fields"]) == 17
    ev = d["evaluation"]
    assert {"rules", "pointer", "cascade", "naive_plain", "naive_null"} <= set(ev["arms"])
    assert {"H1", "H2", "H3", "H4"} <= set(ev["hypotheses"])
    assert d["headline"]["gap"] == 16749


def test_render_is_self_contained(tmp_path):
    p = render(json.loads((SITE / "data.json").read_text(encoding="utf-8")), tmp_path)
    html = p.read_text(encoding="utf-8")
    assert "/*DATA*/" not in html
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    assert srcs == [], "no external scripts"
    blob = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    json.loads(blob.replace("<\\/", "</"))


LINKS = ("attached", "agenda", "parentless", "image_only", "oral", "absent")


def test_parliament_rows_are_internally_consistent():
    """One denominator per row: every written-answer intervention sits in exactly one place, in every period."""
    p = json.loads((SITE / "data.json").read_text(encoding="utf-8"))["parliaments"]
    for r in p["rows"]:
        for per, c in r["periods"].items():
            assert sum(c[k] for k in LINKS) == c["written"], (r["key"], per)
            assert c["missing"] == c["written"] - c["attached"], (r["key"], per)
            if c["written"]:
                assert abs(c["with_text"] - c["attached"] / c["written"]) < 1e-9
                assert c["with_text"] <= c["after_repair"] <= 1
        assert r["periods"]["y2425"]["written"] <= r["periods"]["since2015"]["written"] <= r["periods"]["all"]["written"]
    nat = sum(r["periods"]["all"]["written"] - r["periods"]["all"]["attached"] for r in p["rows"])
    assert nat == p["national"]["gap"] == 16749
    be = next(r for r in p["rows"] if r["key"] == "BE")["periods"]["all"]
    assert (be["written"], be["attached"], be["agenda"], be["parentless"], be["absent"]) == (3409, 382, 517, 2459, 49)
    labels = {r["key"]: r["label"] for r in p["rows"]}
    assert labels["BE"] == "Bern (canton)" and labels["351"] == "Bern (city)"


def test_findings_and_csv_shipped():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    st = {f["id"]: f["status"] for f in d["parliaments"]["findings"]}
    assert st["be_answers_unlinked"] == "confirmed_bug" and st["grparl_384_date"] == "source_discrepancy"
    rows = (SITE / "parliaments.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1 + len(d["parliaments"]["rows"]) and rows[0].startswith("key,label,level,canton,all_written")


def test_evaluation_baselines():
    ev = json.loads((SITE / "data.json").read_text(encoding="utf-8"))["evaluation"]["baselines"]
    assert ev["always_null"] == {"exact": 90, "n": 154}
    assert ev["suggestions"]["right"] == 9 and ev["suggestions"]["of"] == 16
