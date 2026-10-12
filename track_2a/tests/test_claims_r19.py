"""Round 18 (J5, "What the claims check misses"): 13 edits of the README, the report and the form notes passed `make
claims` with 0 failing. Fabricated human labelling, invented adoption ("Shipped", "Adopted by OPD", "In daily use"),
invented safety and cost claims ("hallucination-free", "GDPR-certified", "free to run"), comparatives outside the list
("dominating", "dramatically improves", precision -> recall) and a deleted caveat ("(not sample-checked)"). Each must
now ADD failures to the committed state; the guards, pins and the scoped-qualifier rule behind them are tested too."""
import json

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe.paths import ROOT

DOCS = ("README.md", "technical_report.md", "docs/form_notes.md", "../README.md")


def _docs() -> dict[str, str]:
    return {d: (ROOT / d).read_text(encoding="utf-8") for d in DOCS if (ROOT / d).exists()}


@pytest.fixture(scope="module")
def rows():
    return C.load(ROOT / "claims.tsv")


_BASE: dict[int, set[str]] = {}


def _errs(rows, docs) -> set[str]:
    return (set(P.check(docs=docs)) | set(C.zone_check(rows, docs=docs)) | set(C.pinned_check(docs=docs))
            | set(C.scoped_check(docs=docs)))


def _new_errors(rows, edits: list[tuple[str, str, str]]) -> list[str]:
    docs = _docs()
    base = _BASE.get(id(rows))
    if base is None:
        base = _BASE[id(rows)] = _errs(rows, docs)
    for doc, before, after in edits:
        assert before in docs[doc], f"{doc} no longer prints {before!r}: update this regression case with the docs"
        docs[doc] = docs[doc].replace(before, after, 1)
    return sorted(_errs(rows, docs) - base)


# J5's 13 misses (round 18), verbatim: (id, [(document, before, after)])
J5_R18_MISSES = [
    ("S15 clerks label", [("README.md", "Two blind agent annotators (Claude Opus and Sonnet) label each",
                           "Two parliamentary clerks (Bern and Vaud) label each")]),
    ("S16 human-labelled", [("technical_report.md",
                             "**Gold, no human labelling by design:** two blind agent annotators (Claude Opus, Sonnet)",
                             "**Gold, human-labelled:** two parliamentary clerks")]),
    ("M5 shipped", [("README.md", "3. **Apertus 70B (opt-in)", "3. **Shipped:** **Apertus 70B (opt-in)")]),
    ("M12 applied by OPD", [("README.md", "1. **Apply now:**", "1. **Already applied by OPD:**")]),
    ("M8 adopted by OPD", [("../README.md", "- **Ready for OPD:**", "- **Adopted by OPD:**")]),
    ("M7 deployed at OPD", [("docs/form_notes.md", "- **Delivered.** Repairs for 9,580",
                             "- **Deployed at OPD.** Repairs for 9,580")]),
    ("M11 in daily use", [("docs/form_notes.md", "- **Operations.**", "- **Operations.** In daily use by OPD since October.")]),
    ("S10 hallucination-free", [("docs/form_notes.md", "- **Sovereign and cheap to run.**",
                                 "- **Sovereign and cheap to run.** It is hallucination-free and GDPR-certified.")]),
    ("Q7 free to run", [("../README.md", "- **Sovereign and cheap to run:**", "- **Sovereign and free to run:**")]),
    ("C9 dominating", [("../README.md", "Italian interventions exact on the answer date (10 printed dates",
                        "Italian interventions exact on the answer date, dominating the latest date (10 printed dates")]),
    ("C12 dramatically improves", [("docs/form_notes.md", "it raises author-role recall by 23.4 points",
                                    "it dramatically improves author-role recall by 23.4 points")]),
    ("C1 precision -> recall", [("README.md", "(50/141 pairs vs 17/141); precision not worse |",
                                 "(50/141 pairs vs 17/141); recall not worse |")]),
    ("W6 caveat deleted", [("technical_report.md",
                            "the rules on 8/12 (in-sample in three);",
                            "the rules on 8/12;")]),
]


@pytest.mark.parametrize("edits", [e for _, e in J5_R18_MISSES], ids=[i for i, _ in J5_R18_MISSES])
def test_j5_round18_misses_now_fail(edits, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _new_errors(rows, edits), f"mutation {edits} was not caught"


@pytest.fixture(scope="module")
def pins_base():
    import os
    old = os.environ.get("GP_CLAIMS_STRICT")
    os.environ["GP_CLAIMS_STRICT"] = "1"
    try:
        return set(P.check(dict(P.config(), pins=[]), docs=_docs()))
    finally:
        if old is None:
            del os.environ["GP_CLAIMS_STRICT"]
        else:
            os.environ["GP_CLAIMS_STRICT"] = old


@pytest.mark.parametrize("add", [
    # labelling
    "Two lawyers checked every label.", "The gold is human-labelled.", "Parliamentary staff labelled the documents.",
    "Experts reviewed each answer.", "We labelled the set manually.", "The labels were hand-checked.",
    # adoption and maturity
    "OPD adopted the schema.", "The repairs are deployed.", "The converter shipped in October.",
    "Review mode is in daily use.", "The lists were rolled out to every canton.", "The nightly job is live at OPD.",
    "The repairs were applied by OPD.", "Review mode runs in production.",
    # evaluative, safety, cost
    "Apertus dominates every baseline.", "Apertus improves recall.", "Recall is far higher.", "The cost is lower.",
    "The pipeline is GDPR-compliant.", "It never hallucinates: hallucination-free.", "Outputs are guaranteed correct.",
    "The build is certified.", "The service is secure.", "Review mode is free.", "Runs cheaply anywhere.",
])
def test_inserted_labelling_adoption_evaluative_words_fail(add, pins_base, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    cfg = dict(P.config(), pins=[])  # the guards alone: an inserted word is outside every pin and allow phrase
    for doc in DOCS:
        docs = _docs()
        docs[doc] += "\n" + add + "\n"
        assert set(P.check(cfg, docs=docs)) - pins_base, (doc, add)


def test_model_free_and_arm_names_are_not_cost_words():
    """'model-free' (a hyphenated compound) is not a match of the cost guard; 'free prompt' is an allowlisted arm."""
    rx = P.config()["guards"]["cost"]
    import re
    assert not re.search(rx, "the model-free candidate finder")
    assert re.search(rx, "free to run") and re.search(rx, "cost-free")


def _only(pid: str) -> dict:
    return dict(P.config(), pins=[p for p in P.config()["pins"] if p["id"] == pid], guards={}, docs=[])


def test_precision_pin_reads_its_interval(tmp_path):
    """'Apertus adds precision' holds only while the post hoc interval of the precision difference excludes 0."""
    cfg = _only("cmp.p10.author_filter_precision")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/p10/p10_posthoc_baselines.json").read_text())
    src["display"]["author_filter"]["precision"]["ci_pts"] = [-0.4, 18.2]
    (tmp_path / "results/p10").mkdir(parents=True)
    (tmp_path / "results/p10/p10_posthoc_baselines.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_labelling_pin_reads_the_session_models(tmp_path):
    """'no human labelling': every annotator session ran Claude Opus or Sonnet (the sessions file, all 96)."""
    cfg = _only("labels.no_human_labelling")
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/eval/annotation_sessions.json").read_text())
    src["sets"][0]["sessions"][0]["models"] = ["human:clerk"]
    (tmp_path / "results/eval").mkdir(parents=True)
    (tmp_path / "results/eval/annotation_sessions.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_wildcard_path_step():
    d = {"sets": [{"s": [{"m": ["a"]}, {"m": ["b", "a"]}]}, {"s": [{"m": ["c"]}]}]}
    assert P._get(d, "sets.*.s.*.m.*") == ["a", "b", "a", "c"]
    assert P._get(d, "sets.*.s.*.m") == [["a"], ["b", "a"], ["c"]]
    assert P.evaluate("sorted(set(m))", {"m": P._get(d, "sets.*.s.*.m.*")}) == ["a", "b", "c"]


# ------------------------------------------------------------------------------------------------ scoped qualifiers
def test_scoped_snapshot_matches_the_committed_docs():
    assert C.scoped_check() == []


@pytest.mark.parametrize("doc,before,after", [
    ("README.md", "On 36 held-out whole", "On 36 whole"),
    ("README.md", "F1 is 0.80 (in-sample)", "F1 is 0.80"),
    ("README.md", "(Holm p = 0.032), registered;", "(Holm p = 0.032);"),
    ("technical_report.md", "36/43 (exploratory, post hoc, `oos_role_fit.json`)", "36/43 (`oos_role_fit.json`)"),
    ("README.md", "92.1%** would have answer text once the proposed repairs are applied",
     "92.1%** have answer text after the repairs"),
])
def test_removing_a_scoping_word_next_to_a_claim_fails(doc, before, after, rows, monkeypatch):
    """The generic rule: a qualifier recorded in the clause of a claim anchor or pin phrase may not disappear."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    docs = _docs()
    assert before in docs[doc], f"{doc} no longer prints {before!r}"
    docs[doc] = docs[doc].replace(before, after, 1)
    assert C.scoped_check(docs=docs), (doc, before)


def test_adding_a_caveat_never_fails():
    docs = _docs()
    before = "120/120 from P7 (Wilson 95% [96.9, 100])"
    assert before in docs["README.md"]
    docs["README.md"] = docs["README.md"].replace(before, "120/120 from P7 (Wilson 95% [96.9, 100]; uncorrected, at most)", 1)
    assert C.scoped_check(docs=docs) == []


def test_clauses_split_on_semicolons_cells_and_sentences():
    t = "A 1 (post hoc); B 2. C 3 | D 4 |\n\n- E 5"
    parts = [t[a:b] for a, b in C.clauses(t)]
    assert "A 1 (post hoc)" in parts and any(p.startswith("B 2") for p in parts) and "- E 5" in parts[-1]


# --------------------------------------------------------------------------------------------- the strict documents
def test_strict_docs_is_the_one_list():
    """claims_strict.json `strict_docs` names every strict document once: zones, small integers and the wording
    guards follow it (adding docs/decision.md is one line)."""
    s = C.strict_config()
    assert set(s["strict_docs"]) >= set(DOCS)
    assert set(s["strict_docs"]) <= set(s["zones"]) and set(s["strict_docs"]) <= set(s["small_int_docs"])
    assert set(s["strict_docs"]) <= set(P.config()["docs"])
    cfg = C.with_strict_docs({"strict_docs": ["docs/x.md"], "zones": {}})
    assert cfg["zones"]["docs/x.md"] == {"start": None, "end": None} and "docs/x.md" in cfg["small_int_docs"]
