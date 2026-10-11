"""Wording pins (claims_pins.json, gegenprobe.claims_pins) and the strict repository-root README: every mutation the
a skeptical reviewer made that `make claims` did NOT catch must now fail; the committed documents pass."""
import copy
import json

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe.paths import ROOT

DOCS = ("README.md", "technical_report.md", "docs/form_notes.md", "../README.md")


def _docs() -> dict[str, str]:
    return {d: (ROOT / d).read_text(encoding="utf-8") for d in DOCS if (ROOT / d).exists()}


def test_committed_documents_pass(monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert P.check() == []


# (document, text before, text after): the misses found in review, verbatim
J5_MISSES = [
    ("README.md", "H3a, F1 over the stronger OPD reading, is not confirmed",
     "H3a, F1 over the stronger OPD reading, is confirmed"),
    ("technical_report.md", "Not confirmed: H3a", "Confirmed: H3a"),
    ("README.md", "about three times the rules", "about five times the rules"),
    ("README.md", "doubles extraction", "triples extraction"),
    ("README.md", "Apertus adds about one document", "Apertus adds about four documents"),
    ("README.md", "The default runs no model.", "The default runs Apertus."),
    ("technical_report.md", "Apertus never writes a value.", "Apertus writes every value."),
    ("docs/form_notes.md", "Apertus only suggests.", "Apertus runs unattended."),
    ("README.md", "its order is a strong baseline", "its order is a weak baseline"),
    ("technical_report.md", "so it sits in a few parliaments", "so it sits in every parliament"),
    ("README.md", "Claude Code agents (Anthropic) wrote most code, documentation and the gold labels.",
     "The team wrote the code, documentation and the gold labels."),
    ("docs/form_notes.md", "Claude Code agents wrote the code and labels.", "The team wrote the code and labels."),
    ("README.md", "(our evaluation used Public AI, which may route outside Switzerland; with the local 8B no text leaves "
                  "the machine)", "(with Public AI no text leaves Switzerland)"),
]


@pytest.mark.parametrize("doc,before,after", J5_MISSES, ids=[f"{d}:{a[:28]}" for d, _, a in J5_MISSES])
def test_j5_round15_misses_now_fail(doc, before, after, monkeypatch):
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
    pcfg = dict(P.config(), pins=[], docs=["../README.md"])
    assert P.check(pcfg, root=tmp_path / "track_2a") == []
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert C.zone_check([], cfg=cfg, anchors={})
    assert P.check(pcfg, root=tmp_path / "track_2a")
