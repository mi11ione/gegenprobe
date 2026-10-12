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
    ("README.md", "submitter 12/40 → 24/40 |", "submitter 12/40 → 29/40 |", "29/40"),
    ("README.md", "κ 0.80–0.93 on P1 and P2", "κ 0.85–0.93 on P1 and P2", "0.85"),
    ("technical_report.md", "| **pointer** | **53/62** [74.7, 92.2] | **24/29**",
     "| **pointer** | **53/62** [74.7, 92.2] | **29/29**", "29/29"),
    # a number in the README's facts table (the 8B's 9.3 GB peak moved to docs/evaluation.md, R22)
    ("README.md", "about 0.5 CPU-hours for all 902,754", "about 0.6 CPU-hours for all 902,754", "0.6"),
    # report numbers the earlier version left unchecked: a cascade cell, an interval, a count
    ("technical_report.md", "| cascade | 139/154 [84.6, 94] | 56 |", "| cascade | 139/154 [84.6, 94] | 58 |", "58"),
    ("technical_report.md", "**53/62** [74.7, 92.2]", "**53/62** [76.7, 92.2]", "[76.7, 92.2]"),
    ("technical_report.md", "| recall 99/120, precision 99/99 |", "| recall 99/120, precision 98/99 |", "98/99"),
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
    """P7's registered result (120/120) is anchored in README and report, the queue's base rate (86.7%) in the report;
    the baselines proposed in review (106 vs 105 on the shared promotions, 113 vs 127 over all) are post hoc and stay in
    docs/evaluation.md (R22), where their claims list it; the form notes (5,000 characters) keep 120/120."""
    anchors = claims.anchor_config()
    by_id = {r["id"]: r for r in rows}
    for doc, need in (("README.md", {"120/120"}), ("technical_report.md", {"120/120", "86.7%"})):
        bound = {by_id[c]["shown"] for c, per in anchors.items() if doc in per and c in by_id}
        assert need <= bound, doc
    in_eval = {r["shown"] for r in rows if "docs/evaluation.md" in r["where"].split(",")}
    assert {"106", "105", "113", "127"} <= in_eval
    form = {by_id[c]["shown"] for c, per in anchors.items() if "docs/form_notes.md" in per and c in by_id}
    assert {"120/120"} <= form


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
