"""Cross-language question/answer links (gegenprobe/findings/cross_language.py): the committed finding is recomputed from
the committed census tables (OPD tag signal), and the post-hoc Valais re-score is internally consistent with P5's
registered result."""
import json

from gegenprobe.findings import cross_language as C
from gegenprobe.paths import RESULTS

OUT = json.loads(C.OUT.read_text(encoding="utf-8"))


def test_opd_tag_counts_recompute_from_committed_tables():
    pairs = C.linked_docs()
    per = C.tag_counts(pairs, "tag")
    tot = OUT["totals"]
    assert sum(b["affairs_with_q_and_a"] for b in per.values()) == tot["affairs_with_q_and_a"]
    assert sum(b.get("evaluable", 0) for b in per.values()) == tot["opd_tag_evaluable"]
    assert sum(b.get("cross", 0) for b in per.values()) == tot["opd_tag_cross"]
    assert sum(b.get("first_pair_cross", 0) for b in per.values()) == tot["opd_tag_first_pair_cross"]
    for row in OUT["bodies"]:
        assert per[row["body"]].get("cross", 0) == row["opd_tag"]["cross"]
        assert per[row["body"]].get("first_pair_cross", 0) == row["opd_tag"]["first_pair_cross"]
    strict = {(r["body"], r["affair"]) for r in C.strict_cases(pairs, "tag")}
    assert strict == {(r["body"], r["affair"]) for r in OUT["no_same_language_pair"]}
    assert len(strict) == tot["opd_tag_cross"]


def test_classify_rules():
    q = [dict(id=1, tag=("fr",))]
    assert C.classify(dict(question=q, answer=[dict(id=2, tag=("de",))]), "tag") == "cross"
    assert C.classify(dict(question=q, answer=[dict(id=2, tag=("de",)), dict(id=3, tag=("fr",))]), "tag") == "same"
    assert C.classify(dict(question=q, answer=[dict(id=2, tag=None)]), "tag") is None
    assert C.first_pair_cross(dict(question=q, answer=[dict(id=2, tag=("de",)), dict(id=3, tag=("fr",))]), "tag")
    assert C.url_lang("https://x/INT_2023.09.264_ANT_D1.pdf") == "de"
    assert C.url_lang("https://x/INT_2023.09.264_DEP_Final_FR.pdf") == "fr"
    assert C.url_lang("https://x/I-070-2012-vorstossantwort-de.pdf") == "de"
    assert C.url_lang("https://x/15_INT_335_Texte_CE.pdf") is None
    assert C.text_lang("der die das und nicht ist mit") == "de"
    assert C.text_lang("les des est pour une der") == "fr"


def test_valais_posthoc_consistent_with_registered_p5():
    v = OUT["valais_pairing_by_number"]
    assert v["status"].startswith("post hoc")
    registered = json.loads((RESULTS / "eval6" / "p5__none.json").read_text())["per_affair"]
    vs = {r["affair_id"] for r in registered if r["body"] == "VS"}
    assert {r["affair_id"] for r in v["rows"]} == vs and v["affairs"] == 4
    assert v["gold_answers"] == 11 and v["rules_right"] == 0  # docs/qa.md: rules-only Valais Q/A 0/11
    assert v["by_number_right"] <= v["by_number_predicted"]
    assert all(r["q_text"] == "fr" and r["a_text"] == "de" for r in v["rows"])
