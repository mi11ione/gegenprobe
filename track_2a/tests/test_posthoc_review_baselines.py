"""Post-hoc baselines proposed in review (P10 positional rule and role set, P2 keyword rule, P7 overlap, P8 Qwen
sensitivity): each result file recomputes from committed inputs, and the arms are what their docstrings say."""
import json

import pytest

from eval.gold2 import posthoc_keyword as KW
from eval.p7 import posthoc_overlap as P7O
from eval.p8 import qwen_sensitivity as QS
from eval.p10 import arms as A10
from eval.p10 import posthoc_baselines as PB
from gegenprobe.paths import DATA, PDF_CACHE


# ---------------------------------------------------------------- P10
def test_order_mapping_is_the_registered_opd_mapping():
    assert PB.order_pairs([]) == []
    assert PB.order_pairs(["A B"]) == [("A B", "sole_author")]
    assert PB.order_pairs(["A B", "C D", "E F"]) == [("A B", "first_signatory"), ("C D", "co_signatory"),
                                                     ("E F", "co_signatory")]
    names = ["X Y", "Z W"]
    assert PB.order_pairs(names) == [tuple(x) for x in A10.opd_pairs(PB.as_opd_meta(names), "first_and_co")]
    assert PB.order_pairs_fc(["A B"]) == [("A B", "first_signatory")]


def test_candidates_are_used_in_document_order():
    cs = [dict(value="Late", kind="person", doc="answer", page=1, char_start=0),
          dict(value="Group", kind="parliamentary_group", doc="question", page=2, char_start=5),
          dict(value="Early", kind="person", doc="question", page=1, char_start=9)]
    assert PB.cand_names(cs) == ["Early", "Group", "Late"]
    assert PB.cand_names(cs, persons_only=True) == ["Early", "Late"]


def test_p10_posthoc_file_recomputes(tmp_path, monkeypatch):
    committed = json.loads(PB.OUT.read_text())
    monkeypatch.setattr(PB, "OUT", tmp_path / "p.json")
    got = json.loads(json.dumps(PB.main()))
    assert got == committed
    a = got["primary"]["arms"]
    assert (a["pointer"]["matched"], a["pointer"]["pairs_predicted"], a["pointer"]["pairs_gold"]) == (50, 96, 141)
    assert (a["cand_order"]["matched"], a["cand_order"]["pairs_predicted"]) == (52, 111)
    assert (a["cand_joint"]["matched"], a["opd_first"]["matched"], a["rules"]["matched"]) == (16, 37, 17)  # registered
    w = got["primary"]["paired"]["cand_order"]["wins_losses_ties"]["by_matched_pairs"]
    assert (w["first_ahead"], w["arm_ahead"], w["tie"]) == (8, 7, 19)
    assert "POST HOC" in got["label"] and "proposed in review" in got["label"]


def test_p10_role_set_is_closed_in_the_gold():
    rs = PB.role_set()
    assert rs["gold"]["people"] == 197 and rs["gold"]["other_role"] == 0 and rs["gold"]["supporter_role"] == 0
    assert sum(rs["gold"]["roles"].values()) == 197
    assert all(rs["annotators"][a]["other_role"] == 0 for a in ("A1", "A2", "A3"))


# ---------------------------------------------------------------- P2
@pytest.mark.parametrize("text,dtype,want", [
    ("Der Regierungsrat beantwortet die Interpellation wie folgt. " * 2
     + "Auszug aus dem Protokoll der Sitzung vom 3. März 2020. Später 9.5.2021.", "answer", "2020-03-03"),
    ("Le Conseil d'Etat répond comme suit à la question posée par le député. Lausanne, le 4 avril 2019 et 1.2.2020.",
     "answer", "2020-02-01"),
    ("Der Regierungsrat beantwortet die Interpellation wie folgt. Sitzung vom 3. März 2020.", "intervention", None),
    ("Ein Text ohne Behörde, aber mit einem Datum: 3. März 2020, und noch mehr Worte hier.", "answer", None),
])
def test_keyword_rule(text, dtype, want):
    assert KW.keyword_date(text, dtype) == want


def _p2_texts_cached() -> bool:
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    return all((PDF_CACHE / f"{d['sha256']}.pdf").exists() for d in docs)


@pytest.mark.skipif(not _p2_texts_cached(), reason="P2 PDFs not cached (clean clone); the module would fetch them")
def test_p2_keyword_file_recomputes(tmp_path, monkeypatch):
    committed = json.loads(KW.OUT.read_text())
    monkeypatch.setattr(KW, "OUT", tmp_path / "k.json")
    got = json.loads(json.dumps(KW.main()))
    assert got == committed
    assert got["summary"]["pointer_answer_dates_found"] == [24, 29]
    assert got["summary"]["keyword_answer_dates_found"] == [16, 29]
    assert got["reviewer_input"]["keyword"]["exact"] == 47  # the reviewer's run, two documents unreachable


# ---------------------------------------------------------------- P7
def test_p7_overlap_recomputes_and_matches_posthoc_r8(tmp_path, monkeypatch):
    committed = json.loads(P7O.OUT.read_text())
    monkeypatch.setattr(P7O, "OUT", tmp_path / "o.json")
    got = json.loads(json.dumps(P7O.main()))
    assert got == committed and got["all_match"]
    assert got["frame"]["promoted"] == {"p7": 135, "trivial": 206}
    assert {k: got["frame"]["overlap"][k] for k in ("both", "p7_only", "trivial_only")} == dict(
        both=126, p7_only=9, trivial_only=80)


# ---------------------------------------------------------------- P8
def test_p8_qwen_copy_has_no_text_fields():
    for r in map(json.loads, QS.QWEN_COMMITTED.read_text(encoding="utf-8").splitlines()):
        assert set(r) == {"id", "valid", "label"}
        assert r["label"] is None or ("notes" not in r["label"] and "raw" not in r["label"])


def test_p8_sensitivity_recomputes(tmp_path, monkeypatch):
    committed = json.loads(QS.OUT.read_text())
    monkeypatch.setattr(QS, "OUT", tmp_path / "s.json")
    got = json.loads(json.dumps(QS.main()))
    assert got == committed
    assert all(got["qwen_copy_matches_p8_qwen"].values())
    for f, v in got["fields"].items():  # the registered verdicts are read, never changed
        assert v["registered"] == json.loads((QS.C.R8 / "p8_hypotheses.json").read_text())["fields"][f]["verdict"]
