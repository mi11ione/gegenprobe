# ruff: noqa: E501
"""Round 19 (J5, "mutation test of `make claims`"): J5 applied 80 edits to the README, the report, the form notes, the
decision page, the evaluation notes and the repository README, plus one to the site data, each alone, and ran the claims
check. 6 passed with 0 failing: "outside the tested scope" -> "inside", "a reviewer confirms them" -> "written directly",
"a US nonprofit ... no processing agreement" -> "a Swiss nonprofit ... a processing agreement" (decision page and report),
an inserted "Apertus is the decisive component" and an inserted "virtually every answer date".

The whole battery is committed here: every edit must ADD at least one failure to the committed state (the same checks as
`python -m gegenprobe.claims check`, on the edited text in memory; the PDF sync check plays no part). An edit whose
`before` text is gone fails with a message: a docs pass that rewrites the sentence updates its edit here, it never drops
it. Below the battery: the four guards and the pins added for the six misses, each tested on its own."""
import json
import re

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe import claims_site as S
from gegenprobe.paths import ROOT

# (id, document, before, after): J5's battery, verbatim (scratch scripts mut.py, mut2.py; ids as in J5.md). E25 ("a number
# in docs/evaluation.md") had no text in J5's script; it changes the one bound percentage there.
BATTERY = [
    ('N1', 'README.md', '| **92.1%** |',
     '| **93.1%** |'),
    ('N2', 'technical_report.md', 'it finds 24/29 answer dates',
     'it finds 25/29 answer dates'),
    ('N3', 'technical_report.md', 'Holm p = 0.032); precision not worse',
     'Holm p = 0.0032); precision not worse'),
    ('N4', 'docs/form_notes.md', 'κ 0.80, 0.87',
     'κ 0.90, 0.87'),
    ('N5', 'technical_report.md', 'review mode costs USD 0.59 per 1,000 residue documents on the 70B (§3)',
     'review mode costs USD 0.29 per 1,000 residue documents on the 70B (§3)'),
    ('N6', 'technical_report.md', '| **135/154 [81.5, 92]** |',
     '| **137/154 [81.5, 92]** |'),
    ('N7', 'technical_report.md', '(+0.12, Holm p = 0.17)',
     '(+0.12, Holm p = 0.017)'),
    ('N8', 'technical_report.md', 'the rules take about 0.5 CPU-hours',
     'the rules take about 0.05 CPU-hours'),
    ('N9', 'technical_report.md', 'H3 held (AUROC 0.969)',
     'H3 held (AUROC 0.99)'),
    ('N10', 'technical_report.md', 'Apertus 50/96 (precision 0.52, recall 0.35, F1 0.42), rules 17/55 (0.31, 0.12, 0.17)',
     'Apertus 50/96 (precision 0.52, recall 0.35, F1 0.17), rules 17/55 (0.31, 0.12, 0.42)'),
    ('N11', 'technical_report.md', '| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 |',
     '| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 3 |'),
    ('N12', 'technical_report.md', '| **rules only (default)** | **135/154 [81.5, 92]** | 47 | 4 | 0 | 2 |',
     '| **rules only (default)** | **135/154 [81.5, 92]** | 47 | 4 | 1 | 2 |'),
    ('V1', 'README.md', 'Yes, if each field says which role its value plays',
     'No, unless each field says which role its value plays'),
    ('V2', 'technical_report.md', '*Answer:* **Yes, if each field says which role its value plays**',
     '*Answer:* **Yes**'),
    ('V3', 'technical_report.md', '| **no hypothesis held** |',
     '| **every hypothesis held** |'),
    ('V4', 'technical_report.md', '| **3 of 4 held**; H3 null safety failed (4/33) |',
     '| **4 of 4 held**; H3 null safety held (4/33) |'),
    ('V5', 'technical_report.md', '| **3 of 4 held**: H1, H2, H3b; H3a not |',
     '| **4 of 4 held**: H1, H2, H3b; H3a too |'),
    ('V6', 'technical_report.md', 'outside interventions the skeleton does not carry over as is (exploratory, 15 affairs)',
     'outside interventions the skeleton carries over as is (exploratory, 15 affairs)'),
    ('C1', 'docs/form_notes.md', 'precision not worse (H1, H2, registered)',
     'precision far better (H1, H2, registered)'),
    ('C2', 'technical_report.md', "P10's candidates in document order reach F1 0.41 (Apertus 0.42).",
     "P10's candidates in document order reach F1 0.41, far below Apertus (0.42)."),
    ('C3', 'technical_report.md', 'in 14 it raises author-role recall by 23.4 points',
     'in 14 it raises author-role recall about three times, by 23.4 points'),
    ('C4', 'technical_report.md', '; Holm p = 0.032); precision not worse | the author test',
     '; Holm p = 0.032); recall and precision not worse | the author test'),
    ('C5', 'technical_report.md', '**What the tests say.** ',
     '**What the tests say.** Apertus beats every model-free baseline on every test. '),
    ('C6', 'technical_report.md', 'the rules (135) and the latest date on answer-typed documents (131) are level',
     'the rules (135) clearly beat the latest date on answer-typed documents (131)'),
    ('S1', 'docs/form_notes.md', 'Null safety failed on the 70B',
     'Null safety held on the 70B'),
    ('S2', 'technical_report.md', 'the registered null-safety tests on the 70B failed',
     'the registered null-safety tests on the 70B passed'),
    ('S3', 'technical_report.md', 'and a reviewer confirms each;',
     'and no reviewer is needed;'),
    ('S4', 'README.md', 'Every value it returns is printed in the document and',
     'Apertus is safe to run unattended. Every value it returns is printed in the document and'),
    ('S5', 'technical_report.md', 'Public AI (may route outside Switzerland)',
     'Public AI (Swiss-hosted)'),
    ('S6', 'technical_report.md', '(0 violations; post hoc,',
     '(0 violations; registered,'),
    ('A1', 'docs/form_notes.md', 'OPD confirmed\n  the Bern linking bug',
     'OPD adopted\n  the Bern repairs'),
    ('A2', 'README.md', '**Delivered:** repairs for 9,580',
     '**Delivered and deployed at OPD:** repairs for 9,580'),
    ('A3', 'technical_report.md', '(a linking bug OPD confirmed; correspondence',
     '(a linking bug OPD fixed with our plan; correspondence'),
    ('A4', 'technical_report.md', 'a nightly job re-runs the Bern route.',
     'a nightly job, in production at OPD since 10 Oct, re-runs the Bern route.'),
    ('L1', 'docs/form_notes.md', 'Two blind AI annotators label',
     'Two human experts label'),
    ('L2', 'technical_report.md', 'Claude Code agents (Anthropic) wrote most code, documentation and the gold labels.',
     'Claude Code agents (Anthropic) helped with some code.'),
    ('L3', 'technical_report.md', '**Gold, no human labelling by design:**',
     '**Gold, expert-labelled:**'),
    ('M1', 'technical_report.md', '*feasibility study*: review mode',
     '*deployable prototype*: review mode'),
    ('M2', 'technical_report.md', '*audited*: source-adapter lists; *tested prototype*',
     '*audited*: source-adapter lists; *production-ready*'),
    ('M3', 'technical_report.md', '| feasibility study (D3-5) |',
     '| deployable (D3-5) |'),
    ('W1', 'technical_report.md', 'does not carry over as is (exploratory, 15 affairs)',
     'does not carry over as is (15 affairs)'),
    ('W2', 'technical_report.md', '**Baselines proposed in review** (post hoc, `docs/evaluation.md`)',
     '**Baselines proposed in review** (registered, `docs/evaluation.md`)'),
    ('W3', 'docs/form_notes.md', '(at most 0.58; post hoc)',
     '(at most 0.58; registered)'),
    ('W4', 'technical_report.md', '2 right nulls) | P11 | exploratory |',
     '2 right nulls) | P11 | registered |'),
    ('W5', 'technical_report.md', "for the 17-field skeleton of OPD's five intervention types (198,594 of its 325,691 affairs)",
     "for the 17-field skeleton of all of OPD's affairs (198,594 of its 325,691 affairs)"),
    ('W6', 'README.md', "Tested on OPD's five intervention types",
     "Tested on all of OPD's business"),
    ('W7', 'technical_report.md', ', so it sits in a few parliaments',
     ', so it is robust across parliaments'),
    ('D1', 'technical_report.md', 'the default runs no model.',
     'the default runs Apertus.'),
    ('D2', 'docs/form_notes.md', 'Runtime external services: none by default (public sources only);',
     'Runtime external services: none;'),
    ('X1', 'technical_report.md', ' **Null safety** is left to the reviewer: the registered null-safety tests on the 70B failed (P1-H1, P2-H3, P6-H2), which is why the default runs no model.',
     ''),
    ('X2', 'technical_report.md', ' **Why closed:** provenance by construction and a ranked review queue (post hoc).',
     ''),
    ('X3', 'docs/form_notes.md', ' P6: no registered hypothesis held.',
     ''),
    ('E1', 'README.md', '**Delivered:** repairs for 9,580',
     'Apertus is the decisive component of the pipeline. **Delivered:** repairs for 9,580'),
    ('E2', 'technical_report.md', '**What the tests say.** ',
     '**What the tests say.** On new layouts Apertus recovers virtually every answer date. '),
    ('E3', '../README.md', "Apertus as a reviewer's aid.",
     'Apertus as the core engine.'),
    ('E4', 'README.md', '| untested | **6**, defined once in v0.1 |',
     '| untested | **6**, expected to be shared, defined once in v0.1 |'),
    ('E5', 'technical_report.md', '*drafts for the eCH group*: schema',
     '*endorsed by the eCH group*: schema'),
    ('E6', 'docs/form_notes.md', 'OPD confirmed\n  the Bern linking bug',
     'OPD endorsed\n  the Bern repair plan'),
    ('E7', 'README.md', 'are outside the tested scope.',
     'are inside the tested scope.'),
    ('E8', 'docs/decision.md', 'an estimated 1.64 GPU-hours per 1,000 residue documents (assumed hardware and throughput)',
     'a measured 1.64 GPU-hours per 1,000 residue documents'),
    ('E9', 'docs/decision.md', 'Apertus (the optional review mode) proposes values, and a reviewer confirms them.',
     'Apertus (the optional review mode) proposes values, which are written directly.'),
    ('E10', 'docs/decision.md', '| review mode (Apertus) | feasibility study |',
     '| review mode (Apertus) | ready to deploy |'),
    ('E11', 'docs/decision.md', 'goes to a US nonprofit that\n  offers no processing agreement',
     'goes to a Swiss nonprofit that\n  offers a processing agreement'),
    ('E12', 'technical_report.md', 'the pointer beats the rules on 22 and loses on 4',
     'the pointer beats the rules on 4 and loses on 22'),
    ('E13', 'technical_report.md', 'write the gold answer date 106 vs 105 times',
     'write the gold answer date 105 vs 106 times'),
    ('E14', 'technical_report.md', 'Confirmed: H1, recall over the rules, +23.4 points [5.9, 49.0], Holm p = 0.032',
     'Confirmed: H1, recall over the rules, +23.4 points [5.9, 49.0], two-sided t-test p = 0.032'),
    ('E15', 'technical_report.md', 'so the gain is the date check.',
     'so the gain is the answer detection.'),
    ('E16', 'technical_report.md', 'two blind agent annotators (Claude Opus, Sonnet)',
     'two agent annotators shown the predictions (Claude Opus, Sonnet)'),
    ('E17', 'technical_report.md', '(≥ 1.2 s per host and process)',
     '(≥ 0.2 s per host and process)'),
    ('E18', 'technical_report.md', 'Apertus 70B by inference',
     'Apertus 70B, confirmed by Public AI'),
    ('E19', 'technical_report.md', 'the review-queue verifier and the role reader need the 70B,',
     'the review-queue verifier and the role reader run equally on the 8B,'),
    ('E20', 'technical_report.md', 'no registered decision changes.',
     'two registered decisions change.'),
    ('E21', 'technical_report.md', 'by its published terms a US nonprofit offering no data processing agreement and no storage outside the US',
     'by its published terms a Swiss association offering a data processing agreement'),
    ('E22', 'technical_report.md', '**Closed form only.** Apertus never writes a value.',
     '**Closed form only.** Apertus writes values directly.'),
    ('E23', 'technical_report.md', ' the latest printed date dates an answerless document on 6/15.',
     ' the latest printed date is equally right.'),
    ('E24', 'technical_report.md', 'so Apertus left the unattended path for an opt-in review suggestion (D6)',
     'so Apertus stayed on the default path (D6)'),
    ('E25', 'docs/evaluation.md', 'oral answers in question time (23.6% of question-time',
     'oral answers in question time (32.6% of question-time'),
    ('E26', 'technical_report.md', " (P1's hypothesis script followed its labels, D4; its rules came with its sample, D12)",
     ''),
    ('E27', 'technical_report.md', '| answer date | role split | both |',
     '| answer date | shared | both |'),
    ('E28', 'technical_report.md', '| related affairs | untested | — | one v0.1 definition; meaning test next |',
     '| related affairs | shared | — | one v0.1 definition, confirmed |'),
]
SIX_MISSES = ("E1", "E2", "E7", "E9", "E11", "E21")


@pytest.fixture(scope="module")
def rows():
    return C.merge()


_BASE: dict[int, set[str]] = {}


def _text(doc: str) -> str | None:
    p = ROOT / doc
    return p.read_text(encoding="utf-8") if p.exists() else None


def _check(rows, docs: dict[str, str] | None = None) -> set[str]:
    """Every document-reading part of `make claims` (values are recomputed once, by test_committed_state_passes)."""
    return set(C.check(rows, docs=docs, site=False, recompute=False))


def _base(rows) -> set[str]:
    if id(rows) not in _BASE:
        _BASE[id(rows)] = _check(rows)
    return _BASE[id(rows)]


def test_battery_is_whole():
    ids = [b[0] for b in BATTERY]
    assert len(ids) == len(set(ids)) == 80 and set(SIX_MISSES) <= set(ids)


def test_committed_state_passes(rows, monkeypatch):
    """The battery measures against the committed documents; with GP_CLAIMS_STRICT their wording passes (the values
    themselves are recomputed by `make claims`)."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _base(rows) == set()


@pytest.mark.parametrize("bid,doc,before,after", BATTERY, ids=[b[0] for b in BATTERY])
def test_every_battery_edit_fails(bid, doc, before, after, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    text = _text(doc)
    if text is None:
        assert doc.startswith("../"), f"{doc} missing"
        pytest.skip(f"{doc} is outside the project (not in the Docker build context)")
    assert before in text, (f"{bid}: {doc} no longer prints {before!r}: rewrite this edit against the new sentence "
                            "(never drop it)")
    new = _check(rows, {doc: text.replace(before, after, 1)}) - _base(rows)
    assert new, f"{bid}: {doc} {before!r} -> {after!r} passed the claims check"


def test_site_data_edit_fails(rows):
    """Z1: the site's headline value changed in site/data.json (the page not rebuilt, or rebuilt from a false value)."""
    data = json.loads((ROOT / "site/data.json").read_text(encoding="utf-8"))
    base = set(S.check(rows=rows, data=data, render=False))
    data["headline"]["rules_exact"] += 1
    assert set(S.check(rows=rows, data=data, render=False)) - base


def test_in_memory_check_matches_the_files(rows, monkeypatch):
    """`docs` only overrides: passing every document's own text changes nothing."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    docs = {d: t for d in P.config()["docs"] if (t := _text(d)) is not None}
    assert _check(rows, docs) == _base(rows)


# ------------------------------------------------------------------------------------------- the four new guards
GUARD_DOCS = [d for d in P.config()["docs"]]


@pytest.fixture(scope="module")
def cfg():
    return P.config()


_ONE: dict[str, tuple[dict, str, set[str]]] = {}


def _guard_fails(cfg, doc: str, add: str) -> list[str]:
    """The guards and phrases of one document (pins without their results conditions, which a sentence appended to the
    document cannot change)."""
    text = _text(doc)
    if text is None:
        pytest.skip(f"{doc} missing")
    if doc not in _ONE:
        pins = [{k: v for k, v in p.items() if k != "results"} for p in cfg["pins"] if doc in (p.get("docs") or {})]
        one = dict(cfg, docs=[doc], pins=pins)
        _ONE[doc] = one, text, set(P.check(one, docs={doc: text}))
    one, text, base = _ONE[doc]
    return sorted(set(P.check(one, docs={doc: text + "\n\n" + add + "\n"})) - base)


INSERTED = [
    # scope
    "Government business is inside the tested scope.", "Parliamentary initiatives are within the tested scope.",
    "The results reach beyond the tested scope.", "All affairs are in scope.",
    # review
    "Apertus values are written directly.", "No reviewer is needed.", "Values are applied automatically.",
    "Review mode runs without human review.", "A human in the loop is optional.",
    # jurisdiction
    "Public AI is a Swiss nonprofit.", "Public AI offers a processing agreement.", "Public AI signs a DPA.",
    "The gateway is EU-hosted, in the EU.", "Text never goes abroad.", "Review mode is nDSG-ready.",
    "Inference runs in Switzerland.", "The gateway is Swiss-hosted.", "Public AI is a US company.",
    # intensifiers
    "Apertus is the decisive component of the pipeline.", "Apertus recovers virtually every answer date.",
    "Apertus finds almost all answers.", "Apertus is crucial.", "Apertus is a key component.",
    "Apertus is the main source of the gain.", "The rules always agree.", "The converter is entirely reliable.",
    "The schema is fully shared.", "Apertus is clearly ahead.", "Nearly every field is shared.",
]


@pytest.mark.parametrize("add", INSERTED)
@pytest.mark.parametrize("doc", GUARD_DOCS)
def test_inserted_scope_review_jurisdiction_intensifier_claims_fail(add, doc, cfg, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _guard_fails(cfg, doc, add), (doc, add)


# docs/decision_de.md (the German decision page, a strict document): the six misses in German
GERMAN = [
    ("de-E9 reviewer", "docs/decision_de.md", "und eine Prüferin oder\nein Prüfer bestätigt sie.", "die direkt geschrieben werden."),
    ("de-E11 jurisdiction", "docs/decision_de.md", "gemeinnützige Organisation in den USA, die keinen Auftragsbearbeitungsvertrag anbietet",
     "gemeinnützige Organisation in der Schweiz, die einen Auftragsbearbeitungsvertrag anbietet"),
    ("de-abroad", "docs/decision_de.md", "das ist eine Bekanntgabe ins Ausland nach nDSG Art. 16", "das bleibt in der Schweiz"),
]
INSERTED_DE = [
    "Apertus ist die entscheidende Komponente.", "Apertus findet nahezu jedes Antwortdatum.", "Apertus findet fast alle Antworten.",
    "Die Werte werden direkt geschrieben.", "Der Prüfmodus läuft ohne menschliche Prüfung.", "Public AI ist ein Schweizer Verein.",
    "Public AI bietet einen Auftragsbearbeitungsvertrag.", "Kein Text geht ins Ausland.", "Interpellationen liegen ausserhalb des getesteten Umfangs.",
    "Die Regeln stimmen immer.", "Das Schema ist vollständig geteilt.", "Apertus ist die Hauptquelle des Gewinns.",
]


@pytest.mark.parametrize("bid,doc,before,after", GERMAN, ids=[g[0] for g in GERMAN])
def test_german_decision_page_edits_fail(bid, doc, before, after, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    text = _text(doc)
    if text is None or doc not in P.config()["docs"]:
        pytest.skip(f"{doc} not (yet) a strict document")
    assert before in text, f"{bid}: {doc} no longer prints {before!r}: rewrite this edit against the new sentence"
    assert _check(rows, {doc: text.replace(before, after, 1)}) - _base(rows), (bid, before, after)


@pytest.mark.parametrize("add", INSERTED_DE)
def test_inserted_german_claims_fail(add, cfg, monkeypatch):
    if "docs/decision_de.md" not in cfg["docs"]:
        pytest.skip("docs/decision_de.md not (yet) a strict document")
    assert _guard_fails(cfg, "docs/decision_de.md", add), add


@pytest.mark.parametrize("word,hit", [
    ("the US nonprofit", True), ("USD 0.59", False), ("us", False), ("EU", True), ("EUR", False),
    ("a DPA", True), ("DPAs", True), ("Swiss-hosted", True), ("swiss-ai/apertus", False), ("Swiss", True),
    ("nDSG Art. 16", True), ("disclosed abroad", True),
])
def test_jurisdiction_guard_is_case_aware(word, hit, cfg):
    """US, EU and DPA are matched as written (not "us", "USD", "EUR"); the Public AI route names (swiss-ai/...) are not
    claims."""
    assert bool(re.search(cfg["guards"]["jurisdiction"], word)) is hit


# ------------------------------------------------------------------------------------- the pins behind the misses
def _only(cfg, pid: str) -> dict:
    return dict(cfg, pins=[p for p in cfg["pins"] if p["id"] == pid], guards={}, docs=[])


@pytest.mark.parametrize("pid", ["scope.tested_scope", "safety.reviewer_confirms", "sovereignty.publicai_terms",
                                 "sovereignty.publicai_terms_source", "sovereignty.ndsg_abroad",
                                 "sovereignty.swiss_hosted_estimate", "census.metadata_almost_everywhere"])
def test_new_pins_hold(pid, cfg, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert any(p["id"] == pid for p in cfg["pins"]), pid
    assert P.check(_only(cfg, pid)) == []


TERMS = "results/compliance/publicai_terms.json"


@pytest.mark.parametrize("path,value", [
    (("provider", "jurisdiction"), "CH"), (("data_processing_agreement",), True), (("storage_outside_us",), True),
    (("assessment", "ndsg_disclosure_abroad"), False), (("retrieved",), "2026-11-01"),
])
def test_publicai_facts_file_binds_the_sentences(path, value, cfg, tmp_path):
    """Public AI's terms live in one committed facts file (URLs, retrieval date, quotations); a changed fact fails the
    sentences that state it until they are rewritten."""
    src = json.loads((ROOT / TERMS).read_text(encoding="utf-8"))
    assert src["sources"][0]["url"] == "https://publicai.co/tc" and src["retrieved"] == "2026-10-12"
    obj = src
    for k in path[:-1]:
        obj = obj[k]
    obj[path[-1]] = value
    (tmp_path / TERMS).parent.mkdir(parents=True)
    (tmp_path / TERMS).write_text(json.dumps(src), encoding="utf-8")
    pins = [p for p in cfg["pins"] if any(c.get("file") == TERMS for c in p.get("results") or [])]
    docs = {d: t for p in pins for d in p["docs"] if (t := _text(d)) is not None}
    assert P.check(dict(cfg, pins=pins, guards={}, docs=[]), docs=docs, root=tmp_path)


def test_jurisdiction_pin_keeps_its_negation(cfg):
    """'no processing agreement' cannot become 'a processing agreement' while the facts file says none is offered."""
    pin = next(p for p in cfg["pins"] if p["id"] == "sovereignty.publicai_terms")
    assert pin["polarity"] == "neg"
    flipped = dict(pin, docs={"docs/decision.md": ["goes to a US nonprofit that\n  offers a processing agreement"]})
    errs = P.check(dict(cfg, pins=[flipped], guards={}, docs=[]),
                   docs={"docs/decision.md": "goes to a US nonprofit that\n  offers a processing agreement"})
    assert any("negation" in e for e in errs)


def test_strict_docs_get_the_new_guards(cfg):
    """The guards scan every strict document (claims_strict.json `strict_docs`): docs/decision.md now, and a German
    decision page as soon as it is listed there."""
    strict = C.strict_config()["strict_docs"]
    assert set(strict) <= set(cfg["docs"])
    assert "docs/decision.md" in cfg["docs"]
    for name in ("scope_extent", "review", "jurisdiction", "intensifier"):
        assert name in cfg["guards"]


# ------------------------------------------------------------------------------------ the literal matcher (speed)
@pytest.mark.parametrize("text,s", [("aaaa", "aa"), ("1.4 and 1.4", "1.4"), ("x", ""), ("", "a"), ("abcabc", "c")])
def test_literal_matches_finditer(text, s):
    assert list(C._literal(text, s)) == [(m.start(), m.end()) for m in re.finditer(re.escape(s), text)]


# ================================================================== round 20 (J5, "Breaking make claims"): 64 edits
# J5's round-20 battery, verbatim (scratch muts1-4.json; the PDF-only edit left out). 11 passed with 0 failing: number
# words in the strict zones ("none touched a key" -> "two touched a key", "Three splits rest on one parliament each" ->
# "No split rests on a single parliament"), negated or quantified facts ("θ does not transfer", "the one open decision"),
# the poppler licence, and the DPO checklist, the eCH one-pager, the runbook and the evaluation notes, which were not
# checked. Every edit must ADD a failure, as above; a docs pass that rewrites a sentence rewrites its edit here.
BATTERY_R20 = [
    # num README 24/29->25/29
    ('R20-01', 'README.md', 'rules for it finds 24/29',
     'rules for it finds 25/29'),
    # num TR p=0.065->0.045
    ('R20-02', 'technical_report.md', 'Holm p = 0.032); precision not worse',
     'Holm p = 0.022); precision not worse'),
    # num TR 1.64 GPU-hours->0.64
    ('R20-03', 'technical_report.md', '1.64 GPU-hours',
     '0.64 GPU-hours'),
    # num TR 0.5 CPU-hours->0.05
    ('R20-04', 'technical_report.md', 'about 0.5 CPU-hours',
     'about 0.05 CPU-hours'),
    # num form 9 vs 2 -> 11 vs 2
    ('R20-05', 'docs/form_notes.md', '(62/62,\n  32/32, 35/35;',
     '(62/62,\n  31/32, 35/35;'),
    # num TR 17,720 -> 7,720
    ('R20-06', 'technical_report.md', '(17,720)',
     '(7,720)'),
    # num TR 96 sessions -> 90
    ('R20-07', 'technical_report.md', 'all 96 annotator sessions',
     'all 90 annotator sessions'),
    # num TR AUROC 0.99->0.95
    ('R20-08', 'technical_report.md', 'AUROC 0.99)',
     'AUROC 0.95)'),
    # num TR theta 8->6
    ('R20-09', 'technical_report.md', 'θ_A = 8)',
     'θ_A = 6)'),
    # num TR 30 days->90
    ('R20-10', 'technical_report.md', '(default 30 days)',
     '(default 90 days)'),
    # num TR Kriens 26.5->16.5
    ('R20-11', 'technical_report.md', '26.5 days on 68',
     '16.5 days on 68'),
    # num TR 89 previous base ->59
    ('R20-12', 'technical_report.md', 'has 0 the image keeps',
     'has 3 the image keeps'),
    # num TR date 10 Oct->11 Oct
    ('R20-13', 'technical_report.md', 'correspondence, 10 Oct 2026',
     'correspondence, 11 Oct 2026'),
    # num decision.md first number
    ('R20-14', 'docs/decision.md', '0.59',
     '0.39'),
    # num ech-onepager first digit
    ('R20-15', 'docs/ech-onepager.md', '17',
     '19'),
    # dec 49.9->4.9 machine-hours
    ('R20-16', 'docs/decision.md', '49.9 machine-hours',
     '4.9 machine-hours'),
    # dec 173 begin-date ->73
    ('R20-17', 'docs/decision.md', '173 begin-date',
     '73 begin-date'),
    # dec_de 38 Berner->28
    ('R20-18', 'docs/decision_de.md', 'die 38 Berner',
     'die 28 Berner'),
    # dpo retention default 30->90
    ('R20-19', 'docs/dpo_checklist.md', '(default 30)',
     '(default 90)'),
    # dpo nDSG Art.16->Art.17
    ('R20-20', 'docs/dpo_checklist.md', 'disclosure abroad under nDSG Art. 16',
     'disclosure abroad under nDSG Art. 17'),
    # dec US nonprofit->Swiss
    ('R20-21', 'docs/decision.md', 'goes to a US nonprofit',
     'goes to a Swiss nonprofit'),
    # dec: 'no processing agreement' removed
    ('R20-22', 'docs/decision.md', 'that\n  offers no processing agreement, a disclosure abroad under nDSG Art. 16.',
     'that\n  offers a processing agreement.'),
    # README US nonprofit->Swiss
    ('R20-23', 'README.md', 'a US nonprofit without a processing agreement',
     'a Swiss nonprofit with a processing agreement'),
    # TR post hoc->registered (P2 baseline)
    ('R20-24', 'technical_report.md', '(post hoc). Every closed value',
     '(registered). Every closed value'),
    # TR drop 'post hoc' in summary
    ('R20-25', 'technical_report.md', '24/29 answer dates, the rules 2/29 (registered); in 14',
     '24/29 answer dates, the rules 2/29; in 14'),
    # TR add 'significantly'
    ('R20-26', 'technical_report.md', 'it finds 24/29 answer dates, the rules 2/29',
     'it finds significantly more answer dates, 24/29, the rules 2/29'),
    # TR 'few more'->'far more'
    ('R20-27', 'technical_report.md', 'it raises author-role recall by 23.4 points',
     'it raises author-role recall far, by 23.4 points'),
    # TR null safety failed->held
    ('R20-28', 'technical_report.md', 'the registered null-safety tests on the 70B failed (P1-H1, P2-H3, P6-H2)',
     'the registered null-safety tests on the 70B held (P1-H1, P2-H3, P6-H2)'),
    # TR P6 no hypothesis held->all held
    ('R20-29', 'technical_report.md', '| **no hypothesis held** |',
     '| **all hypotheses held** |'),
    # TR P1 partial->held
    ('R20-30', 'technical_report.md', '| **partial**: H3 held; H1 null safety failed (7/90)',
     '| **held**: H3 held; H1 null safety failed (7/90)'),
    # TR 'Apertus never writes a value'->'Apertus writes values'
    ('R20-31', 'technical_report.md', 'Apertus never writes a value.',
     'Apertus writes each value.'),
    # TR H3a not -> H3a held
    ('R20-32', 'technical_report.md', '**3 of 4 held**: H1, H2, H3b; H3a not',
     '**4 of 4 held**: H1, H2, H3a, H3b'),
    # TR 'no paired difference significant'->'free prompt significantly worse'
    ('R20-33', 'technical_report.md', 'about as accurate as the pointer on P1, P2 and P6, without located values',
     'significantly worse than the pointer on P1, P2 and P6, without located values'),
    # TR 'OPD confirmed the bug'->'OPD approved the repairs'
    ('R20-34', 'technical_report.md', '*Bern* (a linking bug OPD confirmed;',
     '*Bern* (a linking bug OPD fixed with our lists;'),
    # TR declarations remove gold labels
    ('R20-35', 'technical_report.md', 'wrote most code, documentation and the gold labels.',
     'wrote some code.'),
    # README Apertus 'adds precision' -> 'doubles recall'
    ('R20-36', 'README.md', 'it raises author-role recall by 23.4 points',
     'it doubles author-role recall by 23.4 points'),
    # form: insert unbacked sentence
    ('R20-37', 'docs/form_notes.md', '- **Census and OPD.**',
     '- Apertus beats every model-free baseline on every test.\n- **Census and OPD.**'),
    # TR insert unbacked sentence
    ('R20-38', 'technical_report.md', '**Which model.** Every',
     'Apertus beats every model-free baseline on every test. **Which model.** Every'),
    # TR swap answer verdict 'Yes, if'->'Yes'
    ('R20-39', 'technical_report.md', '*Answer:* **Yes, if each field says which role its value plays**',
     '*Answer:* **Yes, every field is shared as is**'),
    # TR 'Unattended' -> remove lower bound clause
    ('R20-40', 'technical_report.md', '**Unattended** (95% lower bound ≥ 0.80, document-level intervals)',
     '**Unattended** (document-level intervals)'),
    # README 'rules match it elsewhere' -> 'rules never match it'
    ('R20-41', 'README.md', '**Apertus 70B, opt-in, reads layouts no rules cover:**',
     '**Apertus 70B, opt-in, beats the rules everywhere:**'),
    # TR 'self-hosted' -> 'Swiss-hosted, audited'
    ('R20-42', 'technical_report.md', '| Apertus 70B (θ = 10.40) | Public AI, or self-hosted |',
     '| Apertus 70B (θ = 10.40) | Swiss-hosted and certified |'),
    # TR swap 8B and 70B numbers (both exist)
    ('R20-43', 'technical_report.md', 'the local 8B finds 15/21 answer dates (70B 16/21)',
     'the local 8B finds 16/21 answer dates (70B 15/21)'),
    # TR swap free/closed quotes 30/60 vs 17/32
    ('R20-44', 'technical_report.md', 'quotes check out on 30/60 (P1) and 17/32 (P2)',
     'quotes check out on 17/32 (P1) and 30/60 (P2)'),
    # TR rankings do not hinge -> hinge
    ('R20-45', 'technical_report.md', "so rankings do not hinge on the date's role",
     "so rankings hinge on the date's role"),
    # TR fails closed -> fails open
    ('R20-46', 'technical_report.md', 'every fetch path now fails closed',
     'every fetch path now fails open'),
    # TR poppler GPL separate -> MIT linked
    ('R20-47', 'technical_report.md', 'poppler (GPL) run as a separate program',
     'poppler (MIT) linked in-process'),
    # TR recommends rules only -> Public AI
    ('R20-48', 'technical_report.md', 'for public bodies it recommends rules only or the local 8B',
     'for public bodies it recommends the Public AI route'),
    # TR theta does not transfer -> transfers
    ('R20-49', 'technical_report.md', 'θ does not transfer across builds',
     'θ transfers across builds'),
    # TR US nonprofit (sec4) -> Swiss
    ('R20-50', 'technical_report.md', 'by its published terms a US nonprofit',
     'by its published terms a Swiss nonprofit'),
    # TR 'not significant' P6 sentence negate
    ('R20-51', 'technical_report.md', 'rules collapse off their home layouts',
     'rules hold up off their home layouts'),
    # TR 'the same assistant family wrote the code and the gold labels' -> 'independent humans'
    ('R20-52', 'technical_report.md', 'The same assistant family wrote the code and the gold labels;',
     'Independent annotators wrote the gold labels;'),
    # TR 'none touched a key' -> remove 'none'
    ('R20-53', 'technical_report.md', 'none touched a key, gold label',
     'two touched a key, gold label'),
    # TR 'no third-party processor by default' -> 'a processor'
    ('R20-54', 'technical_report.md', 'No third-party processor by default;',
     'Public AI processes all text by default;'),
    # README 'The default runs no model.' -> 'runs Apertus'
    ('R20-55', 'README.md', 'The default runs no model.',
     'The default runs Apertus 70B.'),
    # form: 'dates agree' -> 'dates disagree'
    ('R20-56', 'docs/form_notes.md', 'dates agree with κ',
     'dates disagree with κ'),
    # evaluation.md: 'not significant' -> 'significant'
    ('R20-57', 'docs/evaluation.md', 'not significant at',
     'significant at'),
    # ech-onepager: 'fragile, to confirm' -> 'robust'
    ('R20-58', 'docs/ech-onepager.md', '*fragile, to confirm*',
     '*robust*'),
    # runbook nDSG word swap
    ('R20-59', 'docs/runbook.md', 'Art. 16',
     'Art. 6'),
    # README ten tests->twelve tests
    ('R20-60', 'README.md', '**Pre-registered:** ten tests',
     '**Pre-registered:** twelve tests'),
    # TR 'Three splits rest on one parliament each'->'No split rests'
    ('R20-61', 'technical_report.md', 'Three splits rest on one parliament each (§7).',
     'No split rests on a single parliament (§7).'),
    # TR 'three real nights' -> 'thirty real nights'
    ('R20-62', 'technical_report.md', 'three real nights on standard GitHub runners',
     'thirty real nights on standard GitHub runners'),
    # form 'Two blind AI annotators' -> 'Five'
    ('R20-63', 'docs/form_notes.md', 'Two blind AI annotators label',
     'Five blind AI annotators label'),
    # README 'one open decision' -> 'no open decision'
    ('R20-64', 'README.md', 'the one open decision is your hash rule',
     'no decision is open; your hash rule'),
]
ELEVEN_MISSES = ('R20-15', 'R20-19', 'R20-20', 'R20-47', 'R20-49', 'R20-53', 'R20-57', 'R20-58', 'R20-59', 'R20-61', 'R20-64')


def test_r20_battery_is_whole():
    ids = [b[0] for b in BATTERY_R20]
    assert len(ids) == len(set(ids)) == 64 and set(ELEVEN_MISSES) <= set(ids) and len(ELEVEN_MISSES) == 11


@pytest.mark.parametrize("bid,doc,before,after", BATTERY_R20, ids=[b[0] for b in BATTERY_R20])
def test_every_r20_battery_edit_fails(bid, doc, before, after, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    text = _text(doc)
    assert text is not None, f"{doc} missing"
    assert before in text, (f"{bid}: {doc} no longer prints {before!r}: rewrite this edit against the new sentence "
                            "(never drop it)")
    new = _check(rows, {doc: text.replace(before, after, 1)}) - _base(rows)
    assert new, f"{bid}: {doc} {before!r} -> {after!r} passed the claims check"


# ---------------------------------------------------------------------------------- the number-word guard (R21)
INSERTED_NUMBER_WORDS = [
    "Two of the ten tests failed.", "None of the parliaments deviates.", "No split rests on a single parliament.",
    "Every parliament keeps the field.", "All parliaments agree.", "Both checks agree.", "Several parliaments deviate.",
    "A few documents need review.", "Three annotators labelled.", "No session read a key.", "Each of the eleven fields is shared.",
]
INSERTED_NUMBER_WORDS_DE = ["Zwei Komponenten fehlen.", "Keine Sitzung las einen Schlüssel.", "Beide Prüfungen stimmen überein.",
                            "Mehrere Parlamente weichen ab.", "Jedes Parlament behält das Feld."]


@pytest.mark.parametrize("add", INSERTED_NUMBER_WORDS)
@pytest.mark.parametrize("doc", [d for d in GUARD_DOCS if d != "docs/decision_de.md"])
def test_inserted_number_words_fail(add, doc, cfg, monkeypatch):
    """A number word in a strict document is a number: it sits inside a pin, an anchor or an allowlisted phrase."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _guard_fails(cfg, doc, add), (doc, add)


@pytest.mark.parametrize("add", INSERTED_NUMBER_WORDS_DE)
@pytest.mark.parametrize("doc", ["docs/decision_de.md", "docs/dpo_checklist.md"])
def test_inserted_german_number_words_fail(add, doc, cfg):
    assert _guard_fails(cfg, doc, add), (doc, add)


@pytest.mark.parametrize("word,hit", [
    ("none", True), ("one", True), ("ten", True), ("single", True), ("both", True), ("a few", True), ("several", True),
    ("no split", True), ("every parliament", True), ("all 99 sessions", True), ("no answer date", True),
    ("zwei", True), ("keine Sitzung", True), ("kein Dokumenttext", True),
    ("someone", False), ("tenth", False), ("one-sided", False), ("no model", False), ("all", False), ("nothing", False),
])
def test_number_word_guard(word, hit, cfg):
    assert bool(re.search(cfg["guards"]["number_word"], word)) is hit


def test_number_words_in_code_are_not_prose(cfg):
    """`skip_code`: a number word inside a code span or an HTML tag is not a claim."""
    text = "Run `python -m x --one` and <img style=\"max-height:none\"> here."
    assert P.guard_matches(dict(cfg, guards={"number_word": cfg["guards"]["number_word"]}), text) == []


def test_number_word_inside_an_anchor_is_bound(cfg):
    """`claims_covered`: a number word inside an anchor phrase of a claim (or an allowlisted or pinned phrase of the
    numeric check) is bound by that phrase (editing it breaks the phrase); without that cover the report has unbound
    number words."""
    assert "number_word" in cfg["claims_covered"]
    doc = "technical_report.md"
    one = dict(cfg, guards={"number_word": cfg["guards"]["number_word"]}, docs=[doc], zones={})
    assert [e for e in P.check(one) if "number_word" in e] == []
    bare = dict(one, claims_covered=[])
    assert [e for e in P.check(bare) if "number_word" in e]


# ------------------------------------------------------------- pinned negations and quantifiers (R21, J5 R20 misses)
@pytest.mark.parametrize("pid,doc,before,after", [
    ("eval.isolation_none_touched", "technical_report.md", "none touched a key", "two touched a key"),
    ("p8.three_single_parliament_splits", "technical_report.md", "Three splits rest on one parliament each",
     "No split rests on one parliament each"),
    ("convert.theta_per_build", "technical_report.md", "θ does not transfer across builds", "θ transfers across builds"),
    ("ops.only_open_decision", "README.md", "the one open decision is your hash rule", "no decision is open; your hash rule"),
])
def test_pinned_quantifier_cannot_be_updated_to_its_opposite(pid, doc, before, after, cfg):
    """A docs pass cannot 'update' the pin to the flipped wording: the pin requires its negation or quantifier
    (`polarity` neg or `must`), whatever the document says."""
    pin = next(p for p in cfg["pins"] if p["id"] == pid)
    assert pin.get("polarity") == "neg" or pin.get("must")
    phrases = [x if isinstance(x, str) else x["phrase"] for x in pin["docs"][doc]]
    ph = next(x for x in phrases if before in x)
    flipped = ph.replace(before, after)
    text = _text(doc).replace(ph, flipped, 1)
    errs = P.check(dict(cfg, pins=[dict({k: v for k, v in pin.items() if k != "results"}, docs={doc: [flipped]})],
                        guards={}, docs=[], zones={}), docs={doc: text})
    assert any("negation" in e or "lacks" in e for e in errs), errs


def test_code_default_binds_the_retention_sentences(cfg, tmp_path):
    """The 30-day retention is bound to cache_retention.DEFAULT_DAYS: a changed default fails the sentences (DPO
    checklist, runbook, README) until they are rewritten; the claim reads the same constant."""
    src = (ROOT / "src/gegenprobe/cache_retention.py").read_text(encoding="utf-8")
    assert C.py_const(ROOT / "src/gegenprobe/cache_retention.py", "DEFAULT_DAYS") == 30
    row = next(r for r in C.load(ROOT / "claims.tsv") if r["id"] == "r21c.retention.default_days")
    assert C.render(C.value_of(row), row["fmt"]) == "30" and "docs/dpo_checklist.md" in row["where"]
    (tmp_path / "src/gegenprobe").mkdir(parents=True)
    (tmp_path / "src/gegenprobe/cache_retention.py").write_text(src.replace("DEFAULT_DAYS = 30", "DEFAULT_DAYS = 90"))
    pins = [p for p in cfg["pins"] if any(c.get("file") == "src/gegenprobe/cache_retention.py" for c in p.get("results") or [])]
    assert {"ops.cache_retention_default", "dpo.retention"} <= {p["id"] for p in pins}
    docs = {d: t for p in pins for d in p["docs"] if (t := _text(d)) is not None}
    for p in pins:  # the other results files of these pins are read from tmp_path too: drop those conditions
        p["results"] = [c for c in p["results"] if c.get("file") == "src/gegenprobe/cache_retention.py"]
    assert P.check(dict(cfg, pins=pins, guards={}, docs=[], zones={}), docs=docs, root=tmp_path)


@pytest.mark.parametrize("key,number", [("register", 12), ("disclosure_abroad", 16), ("automated_decision", 21),
                                        ("impact_assessment", 22)])
def test_ndsg_articles_are_bound_to_the_facts_file(key, number, cfg, tmp_path):
    facts = "results/compliance/ndsg_articles.json"
    src = json.loads((ROOT / facts).read_text(encoding="utf-8"))
    assert src["articles"][key]["article"] == number
    src["articles"][key]["article"] = number + 1
    (tmp_path / facts).parent.mkdir(parents=True)
    (tmp_path / facts).write_text(json.dumps(src), encoding="utf-8")
    pin = next(p for p in cfg["pins"] if p["id"] == "ndsg.articles")
    only = dict(pin, results=[c for c in pin["results"] if c.get("file") == facts])
    assert P.check(dict(cfg, pins=[only], guards={}, docs=[], zones={}), root=tmp_path)


def test_poppler_licence_is_bound_to_the_sbom(cfg):
    pin = next(p for p in cfg["pins"] if p["id"] == "licence.poppler_gpl_separate")
    assert P.check(dict(cfg, pins=[pin], guards={}, docs=[], zones={})) == []
    text = _text("docs/licences.md").replace("each run as a separate process", "linked in-process")
    assert P.check(dict(cfg, pins=[pin], guards={}, docs=[], zones={}), docs={"docs/licences.md": text})


def test_table_count_after_a_heading():
    text = "| a | b |\n|---|---|\n| x | 1 |\n\n## Two\n\n| a | b |\n|---|---|\n| x | 1 |\n| x | 2 |\n"
    assert P.table_count(text, "| a | b |", {"a": "x"}) == 1
    assert P.table_count(text, "| a | b |", {"a": "x"}, after="## Two") == 2


def test_dpo_and_ech_pages_are_strict(cfg):
    strict = C.strict_config()
    for d in ("docs/dpo_checklist.md", "docs/ech-onepager.md"):
        assert d in strict["strict_docs"] and d in cfg["docs"] and d in strict["small_int_docs"]


@pytest.mark.parametrize("add,fails", [("Two GPUs suffice.", True), ("Every parliament agrees.", True),
                                       ("The data never leaves Switzerland.", True)])
def test_runbook_operator_sheet_is_guarded(add, fails, cfg, rows, monkeypatch):
    """The runbook's operator sheet and route table are a zone: numbers bound (claims_strict.json zones) and the guards
    scanned there (claims_pins.json zones); the rest of the runbook is not."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    doc = "docs/runbook.md"
    text = _text(doc)
    inside = text.replace("## Operator sheet\n\n", "## Operator sheet\n\n" + add + "\n\n", 1)
    outside = text + "\n\n" + add + "\n"
    one = dict(cfg, pins=[{k: v for k, v in p.items() if k != "results"} for p in cfg["pins"] if doc in p.get("docs", {})],
               docs=[])
    base = set(P.check(one, docs={doc: text}))
    assert bool(set(P.check(one, docs={doc: inside})) - base) is fails
    assert not set(P.check(one, docs={doc: outside})) - base
    assert _check(rows, {doc: text.replace("(peak 2,077.6 MB)", "(peak 1,077.6 MB)", 1)}) - _base(rows)
