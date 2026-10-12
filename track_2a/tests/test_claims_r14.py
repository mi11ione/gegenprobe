"""The edits that got past `make claims` in review, each now caught, and the later numbers.

  1 a scope word flipped ("post hoc" -> "registered") in the report, the README or the form notes
  2 a result-table cell below 10 (the P2 pointer's answerless dated 4 -> 1)
  3 a statement without a number ("blind AI annotators" -> "blind human annotators", "OPD confirmed" -> "OPD disputes")
  4 an edited technical_report.md with a stale 444_Report.pdf
  5 a summary-number file whose generator no longer produces it (make run step `numbers`)
"""
import json

import pytest

from gegenprobe import claims
from gegenprobe.paths import RESULTS, ROOT


@pytest.fixture(scope="module")
def rows():
    return claims.load(ROOT / "claims.tsv")


@pytest.fixture(scope="module")
def cfg():
    return claims.strict_config()


def _text(doc):
    return (ROOT / doc).read_text(encoding="utf-8")


def _errs(rows, cfg, doc, old, new):
    t = _text(doc)
    assert old in t, (doc, old)
    bad = t.replace(old, new, 1)
    docs = {doc: bad}
    return (claims.zone_check(rows, cfg, docs=docs) + claims.anchor_check(rows, docs=docs)
            + claims.pinned_check(cfg, docs=docs))


# ---- 1 scope words are bound to their claims
@pytest.mark.parametrize("doc,old,new", [
    ("technical_report.md", "registered against the rules (the baselines post hoc, proposed",
     "registered against the rules (the baselines registered, proposed"),
    ("technical_report.md", "302/302 is an exhaustiveness check (post hoc",
     "302/302 is an exhaustiveness check (registered"),
    ("technical_report.md", "at recall 39/137 (exploratory)", "at recall 39/137 (registered)"),
    ("README.md", "who is an author (+7.3 points, post hoc)", "who is an author (+7.3 points, registered)"),
    ("README.md", "recall 286/345 (in-sample)", "recall 286/345 (held out)"),
    ("README.md", "**Federal level (exploratory,", "**Federal level (registered,"),
    ("docs/form_notes.md", "4 from OPD's labels, post hoc", "4 from OPD's labels, registered"),
    ("docs/form_notes.md", "cascade's 138/154, post hoc)", "cascade's 138/154, registered)"),
])
def test_r14_scope_word_flip_fails(rows, cfg, doc, old, new):
    errs = _errs(rows, cfg, doc, old, new)
    assert errs, (doc, old, new)


def test_r14_new_unbound_scope_word_fails(rows, cfg):
    errs = _errs(rows, cfg, "technical_report.md", "## 3. Use of Apertus\n", "## 3. Use of Apertus\n\nAll of it is registered.\n")
    assert any("scope word 'registered'" in e for e in errs), errs


def test_r14_every_scope_word_in_the_strict_documents_is_bound(rows, cfg):
    errs = [e for e in claims.zone_check(rows, cfg) if "scope word" in e]
    assert errs == []


# ---- 2 result-table cells below 10
@pytest.mark.parametrize("old,new,token", [
    ("| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 | 0 | 4 |",
     "| **pointer** | **53/62** [74.7, 92.2] | **24/29** [65.5, 92.4] | 8 | 0 | 1 |", "1"),
    ("| cascade | 139/154 [84.6, 94] | 56 | 11 | 0 | 7 |", "| cascade | 139/154 [84.6, 94] | 56 | 11 | 0 | 3 |", "3"),
    ("| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 0 |",
     "| rules only | 35/62 [44.1, 68.1] | **2/29** [1.9, 22] | 2 | 0 | 3 |", "3"),  # R19: the P6 table moved to docs
])
def test_r14_small_table_cell_edit_fails(rows, cfg, old, new, token):
    errs = _errs(rows, cfg, "technical_report.md", old, new)
    assert any(f"'{token}' is not bound" in e for e in errs), errs


def test_r14_small_table_cells_carry_their_own_claims(rows):
    by_id = {r["id"]: r for r in rows}
    assert by_id["r14.tbl.p2.pointer.answerless"]["shown"] == "4"
    assert by_id["r14.tbl.p1.model_free_cascade_post_hoc.answerless"]["shown"] == "4"


# ---- 3 pinned statements
@pytest.mark.parametrize("doc,old,new", [
    ("README.md", "Blind AI annotators judged 120/120", "Blind human annotators judged 120/120"),
    ("docs/form_notes.md", "OPD confirmed", "OPD disputes"),
    ("technical_report.md", "only picks values printed in the document", "picks values from the document"),
])
def test_r14_pinned_statement_edit_fails(rows, cfg, doc, old, new):
    errs = _errs(rows, cfg, doc, old, new)
    assert any(e.startswith("pinned") for e in errs), errs


# ---- 4 the PDF is checked against the markdown
def test_r14_pdf_check_flags_a_stale_pdf():
    from report import pdf_check
    phrases = pdf_check.phrases()
    assert len(phrases) > 300
    text = "\n".join(phrases)
    assert pdf_check.check(text=text) == []
    stale = text.replace("53/62", "52/62")
    assert any("53/62" in p for p in pdf_check.check(text=stale))


def test_r14_pdf_normalisation_joins_hyphenated_line_breaks():
    from report import pdf_check
    assert pdf_check.normalise("parliament-\ncluster **p = 0.031**") == "parliament-cluster p = 0.031"


@pytest.mark.skipif(not __import__("shutil").which("pdftotext"), reason="pdftotext (poppler) not installed")
def test_r14_committed_pdf_matches_the_report():
    from report import pdf_check
    assert pdf_check.check() == []


# ---- 5 summary-number files regenerate byte-identical, and a changed source fails
def test_r14_numbers_regenerate_byte_identical():
    from report import numbers_step
    r = numbers_step.regenerate()
    assert r["failed"] == {} and r["diffs"] == [] and r["files"] >= 15


def test_r14_numbers_step_catches_a_changed_source(monkeypatch):
    from report import numbers_step, r13_numbers
    real = r13_numbers.p7
    monkeypatch.setattr(r13_numbers, "p7", lambda: {**real(), "p7": dict(date_hit=115, n=120, share=115 / 120)})
    r = numbers_step.regenerate([("report.r13_numbers", "main")])
    assert any("r13_numbers.json" in d for d in r["diffs"]), r


def test_r14_numbers_step_writes_nothing(tmp_path):
    from report import numbers_step
    target = ROOT / "results" / "report" / "r14_numbers.json"
    before = target.read_bytes()
    with numbers_step.capture_writes() as store:
        target.write_text("tampered", encoding="utf-8")
    assert target.read_bytes() == before and store[target.resolve()] == b"tampered"


# ---- later numbers
def test_r14_numbers():
    d = json.loads((RESULTS / "report" / "r14_numbers.json").read_text(encoding="utf-8"))
    c = d["coverage"]
    # after the r18 re-tiering of Valais's 140 date_window fetch rows (results/repair/adapters/retier/retier_r18.json)
    assert (c["row_checked"], c["agenda"], c["review"], c["repaired"]) == (8949, 592, 39, 9580)
    assert (c["share_row_checked"], c["points_unchecked"], c["share_all"]) == ("91.5%", "0.6", "92.1%")
    a = d["p1_model_free_cascade"]["arms"]
    assert (a["model_free_cascade"]["exact"], a["apertus_cascade"]["exact"], a["rules"]["exact"]) == (138, 139, 135)
    assert a["model_free_cascade"]["printed_nowhere"] == 0
    t = d["answer_times"]
    assert t["names"] == "Kriens and Valais" and (t["rho_same_affairs"], t["rho_plain_without_same_day"]) == (0.997, 0.832)


def test_r14_converter_coverage():
    d = json.loads((RESULTS / "convert" / "coverage_by_parliament.json").read_text(encoding="utf-8"))
    s = d["summary"]
    assert s["by_status"] == {"frozen rules": 15, "source adapter": 38, "metadata only": 38}
    assert s["bodies"] == sum(s["by_status"].values()) == len(d["rows"])
    rules = json.loads((ROOT / "data" / "convert" / "rules_coverage.json").read_text(encoding="utf-8"))["bodies_with_rules"]
    assert {r["body"] for r in d["rows"] if r["status"] == "frozen rules"} == set(rules)
    p2 = {r["body"] for r in d["rows"] if "P2" in r["tests"]}
    assert len(p2) == 15 and not p2 & set(rules)  # P2 = parliaments the rules never saw
    assert s["v0_2_parliaments"] == 26
