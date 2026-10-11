"""The nine single-number edits that got past `make claims` in review, each now caught.

An earlier version made only the headline blocks strict; the README, the technical report and the form notes are now strict end to
end, so a number edited anywhere in them, or a new number in a new sentence, must be bound to its claim by an anchor at
its position. Each test edits one committed document in memory and expects the check to name the edited token.
"""
import pytest

from gegenprobe import claims
from gegenprobe.paths import ROOT


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
    return claims.zone_check(rows, cfg, docs={doc: bad}) + claims.anchor_check(rows, docs={doc: bad})


@pytest.mark.parametrize("doc,old,new,token", [
    # a number still printed correctly elsewhere in the same document
    ("README.md", "the rules (12/40 → 24/40)", "the rules (12/40 → 29/40)", "29/40"),
    ("README.md", "κ 0.80–0.93 on P1 and P2", "κ 0.85–0.93 on P1 and P2", "0.85"),
    ("technical_report.md", "| **pointer** | **53/62** [74.7, 92.2] | **24/29**",
     "| **pointer** | **53/62** [74.7, 92.2] | **29/29**", "29/29"),
    # a number the earlier version bound to no claim in the README
    ("README.md", "9.3 GB peak", "8.3 GB peak", "8.3"),
    # report numbers the earlier version left unchecked: a cascade cell, an interval, a count
    ("technical_report.md", "| cascade | 139/154 [84.6, 94] | 56 |", "| cascade | 139/154 [84.6, 94] | 58 |", "58"),
    ("technical_report.md", "**53/62** [74.7, 92.2]", "**53/62** [76.7, 92.2]", "[76.7, 92.2]"),
    ("technical_report.md", "no decision invented (0/36)", "no decision invented (1/36)", "1/36"),
])
def test_r13_single_number_edit_fails(rows, cfg, doc, old, new, token):
    errs = _errs(rows, cfg, doc, old, new)
    assert any(f"'{token}'" in e for e in errs), errs


@pytest.mark.parametrize("doc,anchor", [
    ("README.md", "### 2. The census: where the answers are\n"),
    ("technical_report.md", "## 3. Use of Apertus\n"),
])
def test_r13_new_false_sentence_in_the_body_fails(rows, cfg, doc, anchor):
    """A reviewer added a new false sentence to the README body and the report body; both passed in an earlier version."""
    errs = _errs(rows, cfg, doc, anchor, anchor + "\nApertus also dates 97.5% of the 412 Jura answers.\n")
    assert any("'97.5%'" in e for e in errs) and any("'412'" in e for e in errs), errs


def test_r13_p7_numbers_are_bound(rows):
    """P7 left the headline tiles; its numbers (120/120; 113/120 vs 127/146; 214 vs 369 rows; 86.7%; 146/146)
    are anchored where the body reports them, in README, report and form notes."""
    anchors = claims.anchor_config()
    by_id = {r["id"]: r for r in rows}
    for doc in ("README.md", "technical_report.md", "docs/form_notes.md"):
        bound = {by_id[c]["shown"] for c, per in anchors.items() if doc in per and c in by_id}
        assert {"120/120", "113/120", "127/146", "369", "86.7%", "146/146"} <= bound, doc


def test_r13_best_no_model_rule_is_the_best(rows):
    """'the best no-model rule' (127/146) must have the highest date-hit share among the no-model arms."""
    import json
    arms = json.loads((ROOT / "results/p7/p7_posthoc_r8.json").read_text())["ablation"]["arms"]
    share = {k: a["annotated"]["date_hit"] / a["annotated"]["n"] for k, a in arms.items()
             if k in ("trivial", "rule_any_view") and a["annotated"].get("date_hit") is not None}
    assert max(share, key=share.get) == "trivial"
    assert (arms["trivial"]["annotated"]["date_hit"], arms["trivial"]["annotated"]["n"]) == (127, 146)


def test_r13_form_notes_fit_the_form():
    assert len(_text("docs/form_notes.md")) <= 5000
