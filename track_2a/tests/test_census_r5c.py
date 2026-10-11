"""Census consistency on the site and in the shipped data files."""

import csv
import json

from gegenprobe.paths import DATA, ROOT

SITE = ROOT / "site"
RES = ROOT / "results" / "census"


def _site():
    return json.loads((SITE / "data.json").read_text(encoding="utf-8"))


def test_oral_answers_split_from_written_missing():
    d = _site()
    for k, h in d["headline"]["periods"].items():
        assert h["written_missing"] == h["missing"] - h["oral"] and h["in_writing"] == h["written"] - h["oral"], k
    a = d["headline"]["periods"]["all"]
    assert (a["missing"], a["oral"], a["written_missing"], a["in_writing"]) == (16749, 1422, 15327, 89846)
    rows = {r["key"]: r for r in d["parliaments"]["rows"]}
    for r in rows.values():
        for c in r["periods"].values():
            assert c["written_missing"] == c["agenda"] + c["parentless"] + c["image_only"] + c["absent"], r["key"]
    vs = rows["VS"]["periods"]["y2425"]
    assert (vs["missing"], vs["oral"], vs["written_missing"], vs["in_writing"]) == (315, 305, 10, 271)
    assert "of the 271 answered in writing, 10 (4%)" in rows["VS"]["safe_say"]
    o = d["parliaments"]["oral_reconcile"]
    assert (o["vs_typed_oral"], o["vs_stub_proxy"], o["vs_question_time"], o["vs_stub_exact"]) == (1017, 1016, 1, 1008)
    assert o["typed_oral"] == 1422 and "1,017" in rows["VS"]["oral_note"]


def test_csv_columns_name_what_they_count():
    with open(SITE / "parliaments.csv", encoding="utf-8") as f:
        rows = {r["key"]: r for r in csv.DictReader(f)}
    head = list(next(iter(rows.values())))
    assert "median_days" not in head and "median_days_all_types" in head and "all_missing" not in head
    for p in ("all", "since2015", "y2425"):
        for t in ("interpellation", "question", "motion", "postulate"):
            assert f"{p}_median_days_{t}" in head and f"{p}_n_{t}" in head
    ne = rows["NE"]
    assert ne["median_days_all_types"] == "25" and float(ne["since2015_median_days_interpellation"]) == 70
    assert all(r[f"{p}_n_{t}"] == "" or int(r[f"{p}_n_{t}"]) >= 10 for r in rows.values()
               for p in ("all", "y2425") for t in ("interpellation", "question"))
    readme = (SITE / "interventions_README.md").read_text(encoding="utf-8")
    assert "median_days_all_types" in readme and "written_missing" in readme


def test_question_json_current_verification_and_names():
    q = json.loads((RES / "question.json").read_text(encoding="utf-8"))
    names = {b["body"]: b for b in q["bodies"]}
    assert names["VS"]["name"] == "Valais" and names["VS"]["opd_name"] == "Wallis"
    assert names["VD"]["name"] == "Vaud" and names["VD"]["opd_name"] == "Waadt"
    assert all(b["name"] not in ("Wallis", "Waadt", "Tessin", "Genf") for b in q["same_day_bodies"] + q["bodies"])
    for p in ("question.json", "matrix.json", "answer_days_robust.json"):
        t = (RES / p).read_text(encoding="utf-8")
        assert "39/39" not in t, p
    assert "2,421 of 2,459" in q["caveats"][0]


def test_meaning_tested_per_field():
    cls = json.loads((DATA / "schema" / "field_verdict_classes.json").read_text())
    f = {x["key"]: x for c in cls for x in c.get("fields", [])}
    assert len(f) == 17
    measured = {k for k, x in f.items() if x["meaning_tested"] == "measured"}
    assert measured == {"type", "date_answer", "procedural_history", "procedural_state", "decision_outcome"}
    cmp_ = json.loads((RES / "comparability.json").read_text())
    for k in measured:  # every 'measured' cites a key that exists in comparability.json
        for key in f[k]["evidence"].split(" ", 1)[1].split(", "):
            assert key in cmp_, (k, key)
    # P8 (eval/prereg9): the seven fields tested on documents carry the registered verdict from results/p8
    h = json.loads((RES.parent / "p8" / "p8_hypotheses.json").read_text())["fields"]
    p8 = {k for k, x in f.items() if x.get("p8")}
    assert p8 == set(h) == {"submitter", "co_signatories", "date_submission", "addressed_body", "language",
                            "government_recommendation", "type"}
    for k in p8:
        assert f[k]["p8"]["verdict"] == h[k]["verdict"], k
        assert f[k]["p8"]["evidence"] == f"results/p8/p8_hypotheses.json fields.{k}"
    assert {k for k in p8 if not f[k]["p8"]["robust"]} == {"addressed_body", "government_recommendation"}
    qv = json.loads((RES.parent / "p8" / "p8_posthoc.json").read_text())["verdicts_on_qwen_labels"]
    for k in p8:  # robust = the registered verdict also on agreed labels only and on Qwen's labels
        assert f[k]["p8"]["robust"] == (h[k]["verdict_agreed_only"] == h[k]["verdict"] == qv[k]["verdict"]), k
    assert {k for k in p8 if h[k]["verdict"] == "role_split"} <= {x["key"] for c in cls if c["key"] == "shared_with_role_split"
                                                                 for x in c["fields"]}
    s = _site()["schema"]
    assert s["tested_counts"]["shared"] == {"measured (P8)": 1, "by definition, untested": 6}
    assert s["tested_counts"]["shared_with_role_split"] == {"measured": 5, "measured (P8)": 5}
    assert s["meaning_measured"] == 11 and s["meaning_p8"] == 7  # type is measured both ways


def test_answer_days_by_trust_tier():
    r = json.loads((RES / "answer_days_by_trust.json").read_text(encoding="utf-8"))
    q = json.loads((RES / "question.json").read_text(encoding="utf-8"))["national"]
    assert r["pooled"]["median"] == q["median_days"] == 68 and r["pooled"]["n"] == q["n_durations"]
    assert sum(t["n"] for t in r["tiers"].values()) == r["pooled"]["n"]
    assert r["tiers"]["same_day"]["median"] == 0 and r["tiers"]["verified"]["bodies"] == 2
