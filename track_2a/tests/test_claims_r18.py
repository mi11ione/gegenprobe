"""Round 17 (J5): the mutations that passed `make claims` must now fail. Nine missed edits of the README, the report and
the form notes (comparatives, the maturity table, sovereignty and recommendation sentences, Apertus's role, an inserted
claim, small integers), the evidence site (now the app: site/, claims_app.json) and an unanchored edit of the report
that the PDF no longer matches. Each mutation must ADD failures to the committed state, so these tests hold while other
numbers move."""
import json
import re
import shutil
import textwrap

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe import claims_app as S
from gegenprobe.paths import ROOT

DOCS = ("README.md", "technical_report.md", "docs/form_notes.md", "../README.md")


def _docs() -> dict[str, str]:
    return {d: (ROOT / d).read_text(encoding="utf-8") for d in DOCS if (ROOT / d).exists()}


@pytest.fixture(scope="module")
def rows():
    return C.load(ROOT / "claims.tsv")


def _new_errors(rows, doc: str, before: str, after: str) -> list[str]:
    """Wording pins + strict zone + anchors on the documents with `before` replaced by `after`, minus the errors the
    committed documents already have."""
    docs = _docs()
    assert before in docs[doc], f"{doc} no longer prints {before!r}: update this regression case with the docs"

    base = _BASE.get(id(rows))
    if base is None:
        base = _BASE[id(rows)] = _errs(rows, docs)
    docs[doc] = docs[doc].replace(before, after, 1)
    return sorted(_errs(rows, docs) - base)


_BASE: dict[int, set[str]] = {}


def _errs(rows, docs) -> set[str]:
    return set(P.check(docs=docs)) | set(C.zone_check(rows, docs=docs))


# (document, text before, text after): J5's nine misses, verbatim where the docs still print them
J5_MISSES = [
    # 1. a comparative flipped: level -> ahead
    ("README.md", "(50/141 pairs vs 17/141); precision not worse |",
     "(50/141 pairs vs 17/141); precision ahead of the rules |"),
    # 2. the maturity table (what the rubric scores rigour against)
    ("technical_report.md", "| *feasibility study* · *drafts",
     "| *deployable prototype* · *drafts"),
    ("technical_report.md", "*drafts for the eCH group* | review mode",
     "*final eCH standard* | review mode"),
    # 3. every one -> most
    ("docs/form_notes.md", "every one from model-free rules", "most from model-free rules"),
    # 4. a false sovereignty claim
    ("README.md", "or nothing with the local 8B on CPU |", "or nothing with the local 70B on a laptop CPU |"),
    # 5. the review flag
    ("README.md", "`needs_review: true`; a settings file", "`needs_review: false`; a settings file"),
    # 6. the data-protection recommendation
    ("technical_report.md", "it recommends rules only or the local 8B", "it recommends the Public AI gateway"),
    # 7. Apertus's role
    ("README.md", "proposes values and a reviewer confirms each |", "runs as the unattended extractor |"),
    ("README.md", "**Apertus 70B (opt-in) reads layouts no rules cover:**",
     "**Apertus 70B, essential, reads layouts no rules cover:**"),
    # 8. a new sentence without numbers or verdict words
    ("README.md", "- **Auditable by construction:**",
     "**Apertus beats the rules on every field we tested.**\n- **Auditable by construction:**"),
    # 9. small integers in prose
    ("README.md", "4 come from\nparliamentary practice, 4 partly from OPD's tagging",
     "5 come from\nparliamentary practice, 3 partly from OPD's tagging"),
]


@pytest.mark.parametrize("doc,before,after", J5_MISSES, ids=[f"{d}:{a[:30]}" for d, _, a in J5_MISSES])
def test_j5_misses_now_fail(doc, before, after, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _new_errors(rows, doc, before, after), f"mutation {before!r} -> {after!r} in {doc} was not caught"


@pytest.mark.parametrize("add", [
    "Apertus outperforms OPD's contributor list.", "Review mode is production-ready.", "The 70B runs locally.",
    "Apertus is behind the rules nowhere.", "Most fields are shared.", "The converter always finds the author.",
    "Apertus is the best extractor.", "Review mode is ready to deploy.",
])
def test_inserted_evaluative_words_fail(add, monkeypatch):
    """The comparative, maturity, quantifier and deployment guards: such a word outside a pinned or allowlisted phrase
    fails in every scanned document."""
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    for doc in DOCS:
        docs = _docs()
        docs[doc] += "\n" + add + "\n"
        assert set(P.check(docs=docs)) - set(P.check(docs=_docs())), (doc, add)


def test_comparative_pin_reads_the_result(tmp_path):
    """'level with document order' holds only while both cluster intervals of Apertus minus document order span 0."""
    cfg = dict(P.config(), pins=[p for p in P.config()["pins"] if p["id"] == "cmp.p10.order_level"], guards={}, docs=[])
    assert P.check(cfg) == []
    src = json.loads((ROOT / "results/p10/p10_posthoc_baselines.json").read_text())
    src["display"]["pointer_vs_cand_order"]["recall"]["ci_pts"] = [1.0, 12.0]  # Apertus ahead: "level" no longer true
    (tmp_path / "results/p10").mkdir(parents=True)
    (tmp_path / "results/p10/p10_posthoc_baselines.json").write_text(json.dumps(src))
    assert P.check(cfg, docs=_docs(), root=tmp_path)


def test_split_sources_bound_to_table_1():
    """The prose split '4 practice, 4 partly OPD, 2 open' is counted from Table 1's source column of the report."""
    t = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    h = "| field | class | source |"
    assert [P.table_count(t, h, {"class": "split", "source": s}) for s in ("^practice", "^both", "^open")] == [4, 4, 2]
    cfg = dict(P.config(), pins=[p for p in P.config()["pins"] if p["id"] == "schema.split_sources"], guards={}, docs=[])
    docs = _docs()
    assert P.check(cfg, docs=docs) == []
    docs["technical_report.md"] = t.replace("| decision outcome | role split | practice |",
                                            "| decision outcome | role split | open |")
    assert P.check(cfg, docs=docs)


def test_list_selector_in_pin_paths():
    assert P._get({"rows": [{"key": "ZH", "n": 1}, {"key": "BE", "n": 2}]}, "rows.[key=BE].n") == 2
    with pytest.raises(KeyError):
        P._get({"rows": [{"key": "BE"}, {"key": "BE"}]}, "rows.[key=BE]")


# ---------------------------------------------------------------------------------------------------- small integers
@pytest.mark.parametrize("doc,before,after", [
    ("README.md", "in 7 parliaments, mostly the submission date", "in 8 parliaments, mostly the submission date"),
    ("../README.md", "in 7 parliaments, mostly the submission date", "in 6 parliaments, mostly the submission date"),
    ("technical_report.md", "dates 7 of 90 answerless documents", "dates 5 of 90 answerless documents"),
    ("docs/form_notes.md", "The 9 held results", "The 8 held results"),
    ("README.md", "- **Auditable by construction:**", "- In 3 parliaments the rules fail.\n- **Auditable by construction:**"),
])
def test_small_integers_in_prose_are_bound(doc, before, after, rows, monkeypatch):
    monkeypatch.setenv("GP_CLAIMS_STRICT", "1")
    assert _new_errors(rows, doc, before, after), (doc, before, after)


@pytest.mark.parametrize("text,structural", [
    ("1. **Apply now:** lists", True), ("## 3. Use of Apertus", True), ("agents, §7)", True), ("(Fig. 1)", True),
    ("*Figure 2. Where", True), ("**Table 1. The 17 fields", True), ("`GP_GGUF=1`", True),
    ('<img style="margin:0 auto">', True), ("in 7 parliaments", False), ("4 fields are in OPD's metadata", False),
])
def test_structural_small_integers(text, structural):
    m = re.search(r"(?<![\w.])\d(?![\w])", text)
    assert C.small_structural(text, m.start(), m.end(), C._code_spans(text)) is structural


# -------------------------------------------------------------------------------------------------------- the app
# (the evidence site's first screen was replaced by the app on 12 Oct 2026; its stated numbers sit under claims_app.json)
def _app_copy(dst, core_edit=None):
    """A copy of the committed site's checked files (static files, _headers, core.json, index.json), core.json edited."""
    from gegenprobe.app.build import STATIC
    src = ROOT / "site"
    (dst / "data").mkdir(parents=True)
    for n in STATIC + ("_headers",):
        shutil.copy(src / n, dst / n)
    shutil.copy(src / "data" / "index.json", dst / "data" / "index.json")
    core = json.loads((src / "data" / "core.json").read_text(encoding="utf-8"))
    if core_edit:
        core_edit(core)
    (dst / "data" / "core.json").write_text(json.dumps(core, ensure_ascii=False), encoding="utf-8")
    return dst


@pytest.fixture(scope="module")
def app_base(tmp_path_factory, rows):
    d = _app_copy(tmp_path_factory.mktemp("app"))
    return d, set(S.check(rows=rows, site=d, render=False))


def _app_new(app_base, rows, tmp_path, core_edit=None, sources=None) -> list[str]:
    d = _app_copy(tmp_path / "site", core_edit) if core_edit else app_base[0]
    return sorted(set(S.check(rows=rows, site=d, render=False, sources=sources)) - app_base[1])


def test_committed_app_matches_its_claims(rows):
    assert S.check(rows=rows, render=False) == []


def test_app_edit_92_1_to_95_3_fails(app_base, rows, tmp_path):
    """J5's site mutation on the app: the stated share after every counted repair changed in core.json."""
    def edit(c):
        assert c["bound"]["share_after"].endswith("%")
        c["bound"]["share_after"] = "95.3%"
    errs = _app_new(app_base, rows, tmp_path, core_edit=edit)
    assert any("share_after" in e and "r9p.share_all" in e for e in errs), errs


def test_app_repair_count_edit_fails(app_base, rows, tmp_path):
    """A changed repair count fails the binding and the cross-check against the queue and the parliaments."""
    def edit(c):
        c["bound"]["repaired"] += 1
    errs = _app_new(app_base, rows, tmp_path, core_edit=edit)
    assert any("r6d.repaired" in e for e in errs) and any("queue" in e for e in errs), errs


def test_app_number_written_by_the_script_fails(app_base, rows, tmp_path):
    from gegenprobe.app.build import APP
    js = (APP / "app.js").read_text(encoding="utf-8")
    t = js.replace("<dt>Scope</dt><dd>", "<dt>Scope</dt><dd>95.3% of ", 1)
    assert t != js
    errs = _app_new(app_base, rows, tmp_path, sources={"app.js": t})
    assert any("95.3%" in e for e in errs), errs


def test_app_number_in_the_page_text_fails(app_base, rows, tmp_path):
    from gegenprobe.app.build import APP
    page = (APP / "index.html").read_text(encoding="utf-8")
    t = page.replace("Affair number, title words", "Affair number (of 92,000), title words", 1)
    assert t != page
    errs = _app_new(app_base, rows, tmp_path, sources={"index.html": t})
    assert any("92,000" in e for e in errs), errs


def test_app_unbound_stated_number_fails(app_base, rows, tmp_path):
    """Completeness: a new number in core.json `bound` fails until claims_app.json binds it."""
    def edit(c):
        c["bound"]["naive_fab"] = 1
    errs = _app_new(app_base, rows, tmp_path, core_edit=edit)
    assert any("bound.naive_fab" in e and "bound to no claim" in e for e in errs), errs


def test_js_literals_scanner():
    code = "a = `x ${b ? `in ${c} 92.3%` : 'q 7'} y`; // c 5\n d = \"e\" /* f 6 */; r = /\\d+/g"
    lits = S.js_literals(code)
    assert "x   y" in lits and any("92.3%" in s for s in lits) and "q 7" in lits and "e" in lits
    assert not any("5" in s or "6" in s for s in lits)


def test_marked_text_skips_meta():
    dom = '<div data-claims="about"><p>17 fields</p><div data-meta="files"><span>2,421 rows</span></div><b>10</b></div><p>99</p>'
    assert S.marked_text(dom) == {"about": "17 fields 10"}


@pytest.mark.skipif(S.chrome() is None, reason="no Chrome/Chromium for the rendered app")
def test_rendered_app_states_its_numbers(rows):
    doms = S.render_routes(ROOT / "site", ["#/about", "#/queue"], S.chrome())
    about = S.marked_text(doms["#/about"])["about"]
    queue = S.marked_text(doms["#/queue"])["queue"]
    b = json.loads((ROOT / "site" / "data" / "core.json").read_text(encoding="utf-8"))["bound"]
    assert f"{b['p2_pointer'][0]}/{b['p2_pointer'][1]}" in about and f"+{b['p10_points']}" in about
    # the queue's group headers: each step with its stated count (all three bound)
    assert f"Apply now · {b['now']:,}" in queue and f"(Bern) · {b['after_hash']:,}" in queue
    assert f"Fetch from the parliaments · {b['fetch']:,}" in queue


# --------------------------------------------------------------------------------------------------------- the PDF
@pytest.fixture(scope="module")
def pdf_raw():
    from report import pdf_check
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext not installed")
    return pdf_check.pdf_text(pdf_check.PDF)


def test_pdf_whole_text_in_sync(pdf_raw):
    from report import pdf_check
    md = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    assert pdf_check.drift(md, pdf_raw) == []
    flat = re.sub(r"\s+", " ", pdf_raw)  # robust to line breaks, re-wrapping, ligatures and soft hyphens
    # long tokens (file paths) stay whole, as a PDF line break never splits them
    assert pdf_check.drift(md, "\n".join(textwrap.wrap(flat, 47, break_long_words=False, break_on_hyphens=False))) == []
    assert pdf_check.drift(md, pdf_raw.replace("fi", "ﬁ").replace("interventions", "inter-\nventions")) == []


@pytest.mark.parametrize("before,after", [
    ("*feasibility study* · *drafts for the eCH group* | review mode, whole and virtual affairs",
     "*deployable prototype* · *drafts for the eCH group* | review mode, whole and virtual affairs"),
    ("for public bodies it recommends rules only or the local 8B", "for public bodies it recommends the Public AI gateway"),
    ("(cascade alone right on 5, rules alone on 1, p = 0.22)",
     "(cascade alone right on 1, rules alone on 5, p = 0.22)"),
])
def test_pdf_unanchored_drift_fails(pdf_raw, before, after):
    """J5: pdf_check only looked for anchor phrases, so an unanchored sentence (the maturity table) could drift."""
    from report import pdf_check
    md = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    assert before in md
    assert pdf_check.drift(md.replace(before, after, 1), pdf_raw)
