"""R20-B (POST HOC, proposed in review): the P2 composite baseline, the closed-set reader vs the null-allowed free prompt,
the answer-times figure and the annotator session manifest recompute from committed files and say what they claim."""
import json
import os
import re

import pytest

from eval import annotation_manifest as AM
from eval import closed_vs_free as CF
from eval.gold2 import posthoc_composite as PC
from gegenprobe.paths import DATA, PDF_CACHE, RESULTS, WORK


# ---------------------------------------------------------------- P2 composite baseline
GOV_ANS = "Der Regierungsrat beantwortet die Interpellation wie folgt. "


@pytest.mark.parametrize("text,want", [
    (GOV_ANS + "Auszug aus dem Protokoll der Sitzung vom 3. März 2020. Später 9.5.2021.", "2020-03-03"),
    (GOV_ANS + "Ohne Stichwort, nur ein Datum: 9.5.2021.", None),  # no cue: null, no latest-date fallback
    ("Ein Text ohne Behörde. Sitzung vom 3. März 2020.", None),    # no government / answer cue: null
    ("", None),
])
def test_cue_only_is_the_reviewers_rule(text, want):
    assert PC.cue_only(text) == want


def test_composite_uses_latest_date_on_answers_and_cue_on_interventions():
    text = GOV_ANS + "Sitzung vom 3. März 2020."
    assert PC.composite_date(text, "answer", ["2019-01-01", "2021-05-09"]) == "2021-05-09"
    assert PC.composite_date(text, "answer", []) is None
    assert PC.composite_date(text, "intervention", ["2021-05-09"]) == "2020-03-03"


def test_p2_composite_rescores_from_committed_predictions():
    committed = json.loads(PC.OUT.read_text())
    got = json.loads(json.dumps(PC.rescore(committed["per_doc"])))
    for k, v in got.items():
        assert committed[k] == v, k
    d = committed["display"]
    assert (d["composite_exact"], d["composite_answer_dates"]) == ("46/62", "21/29")
    assert (d["pointer_exact"], d["pointer_answer_dates"]) == ("53/62", "24/29")
    assert (d["discordant"], d["mcnemar_p"], d["parliament_permutation_p"]) == ("9 vs 2", "0.065", "0.12")
    assert committed["intervention_typed"]["n"] == 31
    assert "POST HOC" in committed["label"] and "proposed in review" in committed["label"]
    # on answer-typed documents the composite is exactly the results-table baseline
    res = json.loads((RESULTS / "eval2" / "p2__publicai_swiss-ai_apertus-v1.5-8b.json").read_text())
    dd = {r["doc_id"]: r.get("doc_dates") or [] for r in res["per_doc"]}
    for p in committed["per_doc"]:
        if p["dtype"] == "answer":
            assert p["composite"] == (max(dd[p["doc_id"]]) if dd[p["doc_id"]] else None)


def _p2_texts_cached() -> bool:
    docs = [json.loads(x) for x in open(DATA / "gold2" / "p2_docs.jsonl")]
    return all((PDF_CACHE / f"{d['sha256']}.pdf").exists() for d in docs)


@pytest.mark.skipif(not _p2_texts_cached(), reason="P2 PDFs not cached (clean clone); the module would fetch them")
def test_p2_composite_file_recomputes_from_the_pdfs(tmp_path, monkeypatch):
    committed = json.loads(PC.OUT.read_text())
    monkeypatch.setattr(PC, "OUT", tmp_path / "c.json")
    assert json.loads(json.dumps(PC.main())) == committed


# ---------------------------------------------------------------- closed vs free (null allowed)
def test_closed_vs_free_recomputes(tmp_path, monkeypatch):
    committed = json.loads(CF.OUT.read_text())
    monkeypatch.setattr(CF, "OUT", tmp_path / "f.json")
    got = json.loads(json.dumps(CF.main()))
    assert got == committed
    d = got["display"]
    assert (d["p1_exact"], d["p1_answerless_dated"]) == ("130/154 vs 134/154", "6/90 vs 3/90")
    assert d["p2_exact_corrected_parser"] == "53/62 vs 54/62" and d["p6_exact"] == "59/68 vs 62/68"
    # what the closed design buys: every value among the printed dates, none printed nowhere
    for s, blk in got["sets"].items():
        c = blk["accuracy"][blk["arms"]["closed"]]
        assert c["values_among_printed_dates"] == c["values"] and c["values_printed_nowhere"] == 0, s
        # ... and what it does not: no accuracy gain over the free prompt that may say null
        assert not blk["paired"][f"{blk['arms']['closed']}_vs_{blk['arms']['free']}"]["mcnemar_exact_p"] < 0.05, s
    assert got["sets"]["P1"]["review_ranking"]["registered_null_vs_value_auroc"]["auroc"] == 0.969


# ---------------------------------------------------------------- answer-times figure
def test_fig6_draws_from_the_committed_answer_times(tmp_path, monkeypatch):
    pytest.importorskip("matplotlib")
    from report import figures as F
    monkeypatch.setattr(F, "OUT", tmp_path)
    assert F.fig6()
    svg = (tmp_path / "fig6_answer_times.svg").read_text()
    assert "post hoc" in svg and "Kriens" in svg
    assert (tmp_path / "fig6_answer_times.png").stat().st_size > 10_000


# ---------------------------------------------------------------- annotator session manifest
def test_manifest_ids_cover_p11_ranges():
    p = "label every packet `.work/p11/packets/IT-001.txt` … `IT-012.txt`; and NI-001.txt` … `NI-015.txt"
    ids = AM.assigned_ids(p)
    assert {f"IT-{i:03d}" for i in range(1, 13)} <= ids and {f"NI-{i:03d}" for i in range(1, 16)} <= ids
    assert AM.assigned_ids("label ONLY P8-001 to P8-003") >= {"P8-001", "P8-002", "P8-003"}


def test_committed_manifest_is_complete_and_text_free():
    m = json.loads(AM.OUT.read_text())
    s = m["summary"]
    assert s["n_sessions"] == 99 and m["vs_annotation_sessions"]["identical_times_models_and_counts"] == 96
    sess = json.loads((RESULTS / "eval" / "annotation_sessions.json").read_text())
    assert s["labels_96"] == sess["overall_all"]["label_files_total"] == 1864
    assert s["label_files_mtime_in_session"] == s["label_files"]
    assert m["transcripts_committed"] is False
    hexd = re.compile(r"[0-9a-f]{64}")
    for r in m["sessions"]:
        assert hexd.fullmatch(r["transcript"]["sha256"]) and r["start"] <= r["end"] and r["models"]
        assert r["label_files"] and all(hexd.fullmatch(f["sha256"]) for f in r["label_files"])
        assert set(r) == {"set", "work_dir", "role", "agent", "parent_session", "models", "start", "end", "transcript",
                          "label_files"}  # no prompt, no document text
    p11 = [r for r in m["sessions"] if r["set"].startswith("P11")]
    assert sorted(r["role"] for r in p11) == ["A1", "A2", "A3"]
    assert sum(len(r["label_files"]) for r in p11) == 69


@pytest.mark.skipif(not (AM.AS.TRANSCRIPTS.exists() and (WORK / "p11" / "ann").exists()) or os.environ.get("CI"),
                    reason="transcripts and .work/ exist only on the author's machine")
def test_manifest_hashes_match_the_local_files():
    m = json.loads(AM.OUT.read_text())
    for r in m["sessions"]:
        assert AM.sha256(AM.AS.TRANSCRIPTS / r["transcript"]["path"]) == r["transcript"]["sha256"], r["agent"]
        for f in r["label_files"]:
            assert AM.sha256(WORK.parent / f["path"]) == f["sha256"], f["path"]
