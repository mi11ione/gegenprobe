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


# ---- v3: census-first site, research dataset, workbench, Bern reconciliation, P2 error profile
def test_research_dataset_shipped_and_consistent():
    import gzip

    from gegenprobe.census.interventions import COLS, load

    rows = load(SITE / "interventions.tsv.gz")
    assert len(rows) == 91268 and list(rows[0]) == COLS
    assert (SITE / "interventions.tsv.gz").stat().st_size <= 4 * 1024 * 1024
    src = SITE.parent / "results" / "census" / "interventions.tsv.gz"
    assert gzip.open(SITE / "interventions.tsv.gz").read() == gzip.open(src).read()
    assert sum(r["link_status"] != "attached" for r in rows) == 16749
    assert all(r["opd_url"] == f"https://openparldata.ch/item/affairs/{r['affair_id']}" for r in rows)
    sh = [r for r in rows if r["body"] == "SH" and r["days_to_answer_alt"] != ""]
    assert sh and all(r["answer_hid_alt"] in ("6", "") or r["answer_date_alt"] == r["answer_date"] for r in sh)
    assert (SITE / "interventions_README.md").exists()


def test_missing_lists_match_the_table():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    m = json.loads((SITE / "missing.json").read_text(encoding="utf-8"))
    assert "missing" not in d["parliaments"], "missing lists ship in missing.json, not inline"
    for r in d["parliaments"]["rows"]:
        listed = m.get(r["key"], {"rows": []})["rows"]
        assert len(listed) == r["periods"]["all"]["missing"], r["key"]
        assert sum(1 for x in listed if x[3] and x[3] >= 2015) == r["periods"]["since2015"]["missing"], r["key"]


def test_one_period_for_headline_and_table():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    for k, h in d["headline"]["periods"].items():
        rows = d["parliaments"]["rows"]
        assert h["written"] == sum(r["periods"][k]["written"] for r in rows)
        assert h["missing"] == sum(r["periods"][k]["missing"] for r in rows)
    assert all(r["safe_say_period"] in ("all years", "2024–25 and all years") for r in d["parliaments"]["rows"])


def test_bern_numbers_and_trust():
    p = json.loads((SITE / "data.json").read_text(encoding="utf-8"))["parliaments"]
    v = [x["v"] for x in p["bern_numbers"]]
    for n in (3532, 229, 3303, 527, 2638, 138, 3394, 2459, 49, 155, 24, 3409, 3027):
        assert n in v, n
    assert p["research"]["bern_verified"]["date_equal"] == 2421 and p["research"]["bern_verified"]["n"] == 2459
    be = next(r for r in p["rows"] if r["key"] == "BE")
    assert be["trust"]["tier"] == "verified"
    assert p["research"]["schaffhausen"]["median_days"] == 0 and p["research"]["schaffhausen"]["median_days_alt"] == 71


def test_workbench_queue_and_p2_profile():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    q = [x for x in d["documents"]
         if x["rules"]["status"] == "abstain" and x["pointer"]["cands"] and x["pointer"]["margin"] is not None]
    assert len(q) == 93
    p2 = d["evaluation"]["p2"]
    for a, x in p2["arms"].items():
        f = p2["profile"][a]
        assert f["right"] + f["right_null"] + f["missed"] + f["wrong_date"] + f["date_no_answer"] == x["n"], a
    cv, a = p2["cascade_vs_pointer"], p2["arms"]
    assert cv["pointer_only"] - cv["cascade_only"] == a["pointer"]["exact"] - a["cascade"]["exact"]
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for s in ("Not in OpenParlData ≠ not published by the parliament", "demo on held-out documents", 'id="bern-numbers"',
              "not a ranking"):
        assert s in html, s


# ---- round 3: self-hosted fonts, coverage gaps, answer times within one type, oral question time in "safe to say"
def test_fonts_self_hosted(tmp_path):
    from gegenprobe.viewer.__main__ import TEMPLATE

    html = TEMPLATE.read_text(encoding="utf-8")
    assert "fonts.googleapis" not in html and "fonts.gstatic" not in html
    urls = set(re.findall(r'url\("(fonts/[^"]+)"\)', html))
    assert urls and all((SITE / u).exists() for u in urls), urls
    assert all((SITE / "fonts" / f).exists() for f in ("OFL-Archivo.txt", "OFL-IBM-Plex-Mono.txt", "SOURCES.txt"))
    render(json.loads((SITE / "data.json").read_text(encoding="utf-8")), tmp_path)
    assert all((tmp_path / u).exists() for u in urls), "build --out DIR ships the fonts next to index.html"


def test_coverage_gaps_and_times_within_type():
    p = json.loads((SITE / "data.json").read_text(encoding="utf-8"))["parliaments"]
    rows = {r["key"]: r for r in p["rows"]}
    for k in ("SZ", "UR", "GL", "AI", "GE"):
        assert rows[k]["coverage"] == "coverage_gap", k
        assert "coverage" in rows[k]["safe_say"], k
    assert {g["key"] for g in p["coverage"]["gaps"]} >= {"SZ", "UR", "GL", "AI", "GE"}
    assert all(r["coverage"] == "measured" for r in rows.values() if r["periods"]["all"]["written"] >= 20)
    assert p["types"][0] == "Interpellation"
    be = rows["BE"]["times"]["all"]["Interpellation"]
    assert be["n"] >= 10 and be["q1"] <= be["median"] <= be["q3"]
    assert rows["VS"]["times"] == {}, "same-day bodies show no answer time"
    gr = rows["GR"]
    assert gr["periods"]["y2425"]["oral"] == 62 and "orally in the sitting (question time)" in gr["safe_say"]


# ---- round 4: five tests incl. P3b, schema record near the top, canton names, Ticino date trust, list-page links
def test_r4_p3b_schema_and_cantons():
    d = json.loads((SITE / "data.json").read_text(encoding="utf-8"))
    p3b = d["evaluation"]["p3b"]
    assert p3b["verdict"] == "replicated" and p3b["n"] == 36
    f = {x["key"]: x for x in p3b["fields"]}
    assert f["answer_date"]["arms"]["C"] == [20, 35] and f["answer_date"]["arms"]["CA"] == [31, 35]
    assert f["affair_type"]["arms"]["C"] == [35, 36] and f["affair_type"]["tier"] == "extractable unattended"
    sv = d["schema"]
    assert len(sv["fields"]) == 17 and {x["cls"] for x in sv["fields"]} == {"shared", "shared_with_role_split"}
    assert len(sv["body_specific"]) == 3
    qa = sv["sample"]["record"]["qa"][0]["answer_date"]
    assert qa["page"] and qa["char_end"] > qa["char_start"] and qa["quote"]
    assert sv["sample"]["record"]["government_recommendation"]["null_reason"]
    rows = {r["key"]: r for r in d["parliaments"]["rows"]}
    assert rows["TI"]["label"] == "Ticino (canton)" and rows["TI"]["alt"] == "Tessin"
    assert rows["VS"]["label"] == "Valais (canton)" and rows["GE"]["label"] == "Genève (canton)"
    assert rows["TI"]["trust"]["tier"] == "verified" and rows["TI"]["trust"]["by"] == "title"
    assert rows["TI"]["years"][0] == 2016 and "OCR recovers" not in rows["TI"]["safe_say"]
    m = json.loads((SITE / "missing.json").read_text(encoding="utf-8"))
    assert all(x[5] == 1 for x in m["5192"]["rows"]), "Lugano's affairs point at one list page"
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "Five pre-registered tests" in html and "Four pre-registered" not in html
    for s in ("Tessin (canton)", "newsroom", "which OCR recovers"):
        assert s not in html, s
