"""Wording pins (claims_pins.json, gegenprobe.claims_pins) and the strict repository-root README: every mutation found
in review that `make claims` did NOT catch must now fail; the committed documents pass."""
import copy
import json

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe.paths import ROOT

DOCS = ("README.md", "technical_report.md", "docs/form_notes.md", "../README.md",
        "docs/evaluation.md", "docs/operations.md")  # the last two hold the README detail moved there (R22)


def _docs() -> dict[str, str]:
    return {d: (ROOT / d).read_text(encoding="utf-8") for d in DOCS if (ROOT / d).exists()}


def test_committed_documents_pass(monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert P.check() == []


# (document, text before, text after): the misses found in review, verbatim
REVIEW_MISSES = [
    ("README.md", "H3a, F1 over the stronger OPD reading, is not confirmed",
     "H3a, F1 over the stronger OPD reading, is confirmed"),
    ("technical_report.md", "Not confirmed: H3a", "Confirmed: H3a"),
    ("docs/evaluation.md", "about three times the rules", "about five times the rules"),
    ("docs/evaluation.md", "doubles extraction", "triples extraction"),
    ("docs/form_notes.md", "it raises author-role recall by 23.4 points",
     "it raises author-role recall about four times, by 23.4 points"),
    ("README.md", "The default runs no model.", "The default runs Apertus."),
    ("technical_report.md", "Apertus never writes a value.", "Apertus writes every value."),
    ("docs/form_notes.md", "Apertus suggests and a reviewer confirms.", "Apertus runs unattended."),
    ("README.md", "its order is a strong baseline", "its order is a weak baseline"),
    ("technical_report.md", "so it sits in a few parliaments", "so it sits in every parliament"),
    ("README.md", "Claude Code agents (Anthropic) wrote most code, documentation and the gold labels.",
     "The team wrote the code, documentation and the gold labels."),
    ("docs/form_notes.md", "Claude Code agents wrote the code and labels.", "The team wrote the code and labels."),
    ("docs/operations.md",
     "(our evaluation used Public AI, which may route outside Switzerland; with the local 8B no text leaves "
                  "the machine)", "(with Public AI no text leaves Switzerland)"),
    # the headline answer, the no-invention and rollback sentences, the test count, the night-2 incident and the
    # D4/D12 caveat (number-free sentences that passed the claims check before they were pinned)
    ("README.md", "Yes, if each field says which role its value plays", "Yes, without qualification"),
    ("technical_report.md", "Yes, if each field says which role its value plays", "Yes, without qualification"),
    ("docs/form_notes.md", "Yes, if each field says which role its value plays", "Yes, without qualification"),
    ("../README.md", "Yes, if each field says which role its value plays", "Yes, without qualification"),
    ("docs/evaluation.md", "No closed-set arm returned a date printed nowhere", "No arm returned a date printed nowhere"),
    ("docs/form_notes.md", "Every value it returns\n  is a located printed value",
     "Every value the free prompt returns\n  is a located printed value"),
    ("README.md", "rolls the whole transaction back", "never rolls the transaction back"),
    ("README.md", "Ten tests, each with code", "Eleven tests, each with code"),
    ("docs/form_notes.md", "**Ten tests, frozen before any label**", "**Eleven tests, frozen before any label**"),
    ("docs/operations.md", "that second\n  night exposed a ledger bug, which is fixed", "that second\n  night ran clean"),
    ("README.md", " (P1's hypothesis script followed its labels and\n  its rules entered with its sample, both logged: "
                  "D4, D12)", ""),
    ("technical_report.md", " (P1's hypothesis script followed its labels, D4; its rules came with its sample, D12)", ""),
    # P10 against OPD's contributor list is level (H3a not confirmed), never "ahead"
    ("README.md", "is not confirmed\n  (+0.12, Holm p = 0.17)", "is ahead of OPD's list\n  (+0.12, Holm p = 0.17)"),
    ("technical_report.md", "Not confirmed: H3a, over OPD's list", "Ahead: H3a, over OPD's list"),
    ("docs/form_notes.md", "precision not worse (H1, H2, registered)",
     "precision ahead of OPD's contributor list (H1, H2, registered)"),
    # where document text goes at runtime
    ("README.md", "or nothing with the local 8B on CPU |", "or to any provider with the local 8B on CPU |"),
    ("technical_report.md", "or the local 8B, where no text leaves the machine)",
     "or any provider, where no text leaves Switzerland)"),
    # P8's sensitivity check
    ("README.md", "(5/7 verdicts hold;", "(7/7 verdicts hold;"),
]


@pytest.mark.parametrize("doc,before,after", REVIEW_MISSES, ids=[f"{d}:{a[:28]}" for d, _, a in REVIEW_MISSES])
def test_review_misses_now_fail(doc, before, after, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    docs = _docs()
    assert before in docs[doc], f"{doc} no longer prints {before!r}: update this regression case with the docs"
    docs[doc] = docs[doc].replace(before, after, 1)
    errs = P.check(docs=docs)
    assert errs, f"mutation {before!r} -> {after!r} in {doc} was not caught"


def test_inserted_claim_words_fail_where_no_pin_existed(monkeypatch):
    """Guards: a new verdict, multiplier or safety phrase anywhere in a scanned document fails."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    for add in ("Apertus is five times better.", "All hypotheses were confirmed.", "Apertus runs unattended.",
                "No text leaves Switzerland."):
        docs = _docs()
        docs["docs/form_notes.md"] += "\n" + add + "\n"
        assert P.check(docs=docs), add


def _only(pin_id: str) -> dict:
    cfg = P.config()
    return dict(cfg, pins=[p for p in cfg["pins"] if p["id"] == pin_id], guards={}, docs=[])


def test_verdict_pin_reads_the_result(tmp_path):
    """A verdict pin is bound to its results file: if the committed result changed, the sentence fails until rewritten."""
    cfg = _only("verdict.p10.h3a_not_confirmed")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/p10/p10_scores.json").read_text())
    src["primary"]["hypotheses"]["tests"]["H3a"]["verdict"] = "confirmed"
    (tmp_path / "results/p10").mkdir(parents=True)
    (tmp_path / "results/p10/p10_scores.json").write_text(json.dumps(src))
    errs = P.check(cfg, docs=_docs(), root=tmp_path)
    assert any("H3a.verdict is 'confirmed'" in e for e in errs), errs


def test_multiplier_pin_is_computed_from_the_result(tmp_path):
    cfg = _only("quant.p10_three_times")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/p10/p10_scores.json").read_text())
    src["primary"]["table"]["all"]["pointer"]["matched"] = 85  # 85/17 = 5: "about three times" no longer true
    (tmp_path / "results/p10").mkdir(parents=True)
    (tmp_path / "results/p10/p10_scores.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_polarity_stops_an_opposite_rewording_of_a_negative_verdict():
    cfg = copy.deepcopy(_only("verdict.p10.h3a_not_confirmed"))
    docs = _docs()
    docs["README.md"] = docs["README.md"].replace("is not confirmed", "is confirmed", 1)
    cfg["pins"][0]["docs"]["README.md"] = ["H3a, F1 over the stronger OPD reading, is confirmed"]  # pin "updated" too
    errs = P.check(cfg, docs=docs)
    assert any("states no negation" in e for e in errs), errs


def test_expression_evaluator_is_closed():
    assert P.evaluate("round(a / b)", dict(a=50, b=17)) == 3
    assert P.evaluate("lo < 0 < hi", dict(lo=-0.02, hi=0.54)) is True
    assert P.evaluate("'x' not in [a, b]", dict(a="y", b="z")) is True
    for bad in ("__import__('os')", "a.__class__", "(lambda: 1)()"):
        with pytest.raises((ValueError, KeyError)):
            P.evaluate(bad, dict(a=1))


def test_root_readme_is_strict(monkeypatch):
    """'50/141' -> '55/141' at the first occurrence in ../README.md passed, because the value also occurs later."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    rows = C.load(ROOT / "claims.tsv")
    docs = {"../README.md": (ROOT / "../README.md").read_text(encoding="utf-8")}
    assert C.zone_check(rows, docs=docs) == []
    docs["../README.md"] = docs["../README.md"].replace("50/141", "55/141", 1)
    errs = C.zone_check(rows, docs=docs)
    assert any("../README.md" in e and "55/141" in e for e in errs), errs


def test_root_readme_skipped_outside_the_build_context(monkeypatch, tmp_path):
    """Inside the Docker image the repository root is not there: the zone and the pins skip it unless strict."""
    monkeypatch.delenv("GP_CLAIMS_STRICT", raising=False)
    cfg = {"zones": {"../README.md": {"start": None, "end": None}}}
    monkeypatch.setattr(C, "ROOT", tmp_path / "track_2a")
    assert C.zone_check([], cfg=cfg, anchors={}) == []
    pcfg = dict(P.config(), pins=[], docs=["../README.md"], zones={})  # only the root README (no runbook zone)
    assert P.check(pcfg, root=tmp_path / "track_2a") == []
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert C.zone_check([], cfg=cfg, anchors={})
    assert P.check(pcfg, root=tmp_path / "track_2a")


def test_rollback_pin_reads_the_result(tmp_path):
    """The rollback sentence is bound to the PostgreSQL check: a re-run that changed rows fails it."""
    cfg = _only("safety.bern_rollback")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/repair/apply_be/apply_BE_pg_check.json").read_text())
    src["checks"]["2_rerun"]["unchanged"] = False
    (tmp_path / "results/repair/apply_be").mkdir(parents=True)
    (tmp_path / "results/repair/apply_be/apply_BE_pg_check.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_level_with_opd_pin_reads_the_result(tmp_path):
    """'level with OPD's contributor list' holds only while H3a is not confirmed (Holm p > 0.05)."""
    cfg = _only("verdict.p10.level_with_opd")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/p10/p10_scores.json").read_text())
    src["primary"]["hypotheses"]["tests"]["H3a"]["p_holm"] = 0.01
    (tmp_path / "results/p10").mkdir(parents=True)
    (tmp_path / "results/p10/p10_scores.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_no_invention_pin_reads_the_result(tmp_path):
    """The closed-set no-invention sentence fails if a closed-set arm invented a date."""
    cfg = _only("safety.no_invention_closed_set")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/eval2/posthoc_r5_p2_table.json").read_text())
    src["all_62_70b"]["pointer"]["fabricated"] = 1
    (tmp_path / "results/eval2").mkdir(parents=True)
    (tmp_path / "results/eval2/posthoc_r5_p2_table.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)
