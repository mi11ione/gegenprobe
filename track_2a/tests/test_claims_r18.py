"""Round 17 (J5): the mutations that passed `make claims` must now fail. Nine missed edits of the README, the report and
the form notes (comparatives, the maturity table, sovereignty and recommendation sentences, Apertus's role, an inserted
claim, small integers), the evidence site (site/index.html) and an unanchored edit of the report that the PDF no longer
matches. Each mutation must ADD failures to the committed state, so these tests hold while other numbers move."""
import json
import re
import shutil
import textwrap

import pytest

from gegenprobe import claims as C
from gegenprobe import claims_pins as P
from gegenprobe import claims_site as S
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
    ("README.md", "with precision not worse (P10, H1 and H2, registered)",
     "with precision ahead of the rules (P10, H1 and H2, registered)"),
    # 2. the maturity table (what the rubric scores rigour against)
    ("technical_report.md", "*feasibility study*: review mode",
     "*deployable prototype*: review mode"),
    ("technical_report.md", "*drafts for the eCH group*: schema v0.1",
     "*final eCH standard*: schema v0.1"),
    # 3. every one -> most
    ("docs/form_notes.md", "every one from model-free rules", "most from model-free rules"),
    # 4. a false sovereignty claim
    ("README.md", "The Apertus 8B runs locally on CPU", "The Apertus 70B runs locally on a laptop CPU"),
    # 5. the review flag
    ("README.md", "`needs_review: true`\n  for OPD's", "`needs_review: false`\n  for OPD's"),
    # 6. the data-protection recommendation
    ("technical_report.md", "it recommends rules only or the local 8B", "it recommends the Public AI gateway"),
    # 7. Apertus's role
    ("README.md", "Apertus as a reviewer's aid", "Apertus as the unattended extractor"),
    ("README.md", "**Apertus 70B, opt-in, reads layouts no rules cover:**",
     "**Apertus 70B, essential, reads layouts no rules cover:**"),
    # 8. a new sentence without numbers or verdict words
    ("README.md", "- **Suggestions go to a reviewer;",
     "**Apertus beats the rules on every field we tested.**\n- **Suggestions go to a reviewer;"),
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
    ("../README.md", "in 7 parliaments,\n  mostly the submission date", "in 6 parliaments,\n  mostly the submission date"),
    ("technical_report.md", "dates 7 of 90 answerless documents", "dates 5 of 90 answerless documents"),
    ("docs/form_notes.md", "The 9 held results", "The 8 held results"),
    ("README.md", "- **Suggestions go to a reviewer;", "- In 3 parliaments the rules fail.\n- **Suggestions go to a reviewer;"),
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


# -------------------------------------------------------------------------------------------------------- the site
@pytest.fixture(scope="module")
def site():
    cfg = S.config()
    page = (ROOT / "site/index.html").read_text(encoding="utf-8")
    data = json.loads((ROOT / "site/data.json").read_text(encoding="utf-8"))
    return cfg, page, data, S._template()


def _site_new(site, rows, **kw) -> list[str]:
    cfg, page, data, template = site
    base = set(S.check(cfg, rows, page, data, template, render=False))
    args = dict(cfg=cfg, rows=rows, page=page, data=data, template=template, render=False) | kw
    return sorted(set(S.check(**args)) - base)


def test_committed_site_matches_its_claims(site, rows):
    cfg, page, data, template = site
    assert S.check(cfg, rows, page, data, template, render=False) == []


def test_site_edit_92_3_to_95_3_fails(site, rows):
    """J5: '92.3% after every counted repair' -> '95.3%' in site/index.html passed every check."""
    page = site[1]
    m = re.search(r"(\d+\.\d)% after every counted repair", page)
    assert m, "the site no longer prints '...% after every counted repair'"
    assert _site_new(site, rows, page=page.replace(m.group(0), "95.3% after every counted repair"))
    assert _site_new(site, rows, page=page.replace(m.group(1), "95.3"))


def test_site_rebuilt_from_a_changed_data_json_fails(site, rows):
    """A consistent page (template + data.json) whose headline value no longer matches its claim fails the binding."""
    cfg, _, data, template = site
    d = json.loads(json.dumps(data))
    d["headline"]["at_most"]["all"]["after_repair"] = 0.953
    errs = _site_new(site, rows, data=d, page=S.expected_html(d, template))
    assert any("after_repair" in e for e in errs), errs


def test_site_number_written_by_the_template_fails(site, rows):
    cfg, _, data, template = site
    t = template.replace("'Can one schema hold Swiss parliamentary business?",
                         "'95.3% of fields: can one schema hold Swiss parliamentary business?", 1)
    assert t != template
    errs = _site_new(site, rows, template=t, page=S.expected_html(data, t))
    assert any("95.3%" in e for e in errs), errs


def test_site_unbound_number_on_the_first_screen_fails(site, rows):
    """Completeness: the hero reading a data.json number no binding covers fails."""
    cfg, _, data, template = site
    t = template.replace("$('#heroLine').textContent = ",
                         "$('#heroLine').dataset.n = H.naive_fab; $('#heroLine').textContent = ", 1)
    assert t != template
    errs = _site_new(site, rows, template=t, page=S.expected_html(data, t))
    assert any("headline.naive_fab" in e for e in errs), errs


def test_js_literals_scanner():
    code = "a = `x ${b ? `in ${c} 92.3%` : 'q 7'} y`; // c 5\n d = \"e\" /* f 6 */; r = /\\d+/g"
    lits = S.js_literals(code)
    assert "x   y" in lits and any("92.3%" in s for s in lits) and "q 7" in lits and "e" in lits
    assert not any("5" in s or "6" in s for s in lits)


@pytest.mark.skipif(S.chrome() is None, reason="no Chrome/Chromium for the rendered first screen")
def test_rendered_first_screen(site):
    txt = S.rendered_hero(ROOT / "site/index.html", site[0], S.chrome())
    assert txt and "Can one schema hold Swiss parliamentary business?" in txt


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
    ("*feasibility study*: review mode, whole and virtual affairs",
     "*deployable prototype*: review mode, whole and virtual affairs"),
    ("for public bodies it recommends rules only or the local 8B", "for public bodies it recommends the Public AI gateway"),
    ("the rules (135) and the latest date on answer-typed documents (131)",
     "the latest date on answer-typed documents (135) and the rules (131)"),
])
def test_pdf_unanchored_drift_fails(pdf_raw, before, after):
    """J5: pdf_check only looked for anchor phrases, so an unanchored sentence (the maturity table) could drift."""
    from report import pdf_check
    md = (ROOT / "technical_report.md").read_text(encoding="utf-8")
    assert before in md
    assert pdf_check.drift(md.replace(before, after, 1), pdf_raw)
