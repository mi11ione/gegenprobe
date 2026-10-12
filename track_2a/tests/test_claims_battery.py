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
    ('N3', 'technical_report.md', 'exact McNemar p = 0.065; parliament permutation p = 0.12; post hoc',
     'exact McNemar p = 0.0065; parliament permutation p = 0.12; post hoc'),
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
    ('C1', 'docs/form_notes.md', "50/141, level with OPD's contributor list",
     "50/141, well above OPD's contributor list"),
    ('C2', 'technical_report.md', 'most of the gain comes from the model-free candidate finder',
     'most of the gain comes from Apertus'),
    ('C3', 'technical_report.md', '| about one document |',
     '| about ten documents |'),
    ('C4', 'technical_report.md', '| Apertus adds precision deciding who is an author',
     '| Apertus adds recall and precision deciding who is an author'),
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
    ('S4', 'README.md', 'Apertus only picks values printed in the document,',
     'Apertus is safe to run unattended; it only picks values printed in the document,'),
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
    ('M1', 'technical_report.md', '| *feasibility study* · *drafts for the eCH group* |',
     '| *deployable prototype* · *drafts for the eCH group* |'),
    ('M2', 'technical_report.md', '*audited* · *tested prototype*',
     '*audited* · *production-ready*'),
    ('M3', 'technical_report.md', '| feasibility study (D3-5) |',
     '| deployable (D3-5) |'),
    ('W1', 'technical_report.md', 'does not carry over as is (exploratory, 15 affairs)',
     'does not carry over as is (15 affairs)'),
    ('W2', 'technical_report.md', 'parliament permutation p = 0.12; post hoc, proposed in review)',
     'parliament permutation p = 0.12; registered)'),
    ('W3', 'docs/form_notes.md', '(+7.3 points,\n  post hoc)',
     '(+7.3 points,\n  registered)'),
    ('W4', 'technical_report.md', '| **12/12** Italian answer dates (P11, exploratory) |',
     '| **12/12** Italian answer dates (P11, registered) |'),
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
    ('X2', 'technical_report.md', ' **Why closed:** for provenance and a review ranking, not accuracy.',
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
    ('E5', 'technical_report.md', '| *feasibility study* · *drafts for the eCH group* |',
     '| *feasibility study* · *endorsed by the eCH group* |'),
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
    ('E13', 'technical_report.md', 'right alone on 9 documents vs 2',
     'right alone on 2 documents vs 9'),
    ('E14', 'technical_report.md', '(exact McNemar p = 0.065;',
     '(two-sided t-test p = 0.065;'),
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
